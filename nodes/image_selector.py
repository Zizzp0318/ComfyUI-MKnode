"""MK-图像选择器（Node API V3）

迁移自 Comfyui_LG_Tools 的 ImageSelector 节点（原分类 🎈LAOGOU/Image）。

相对原版的改动：

命名隔离（必须）：
- 节点类型名 ImageSelector -> MK_ImageSelector
- 分类 -> MK节点
- 路由 /image_selector/select -> /mk_image_selector/select
  （必须改：源包在 import 时就注册了原路径，重复注册会让 aiohttp 抛错）
- WS 事件加 mk_ 前缀，避免两个包的前端监听器互相抢事件
- 共享存储挂在 _mk_selector_node_data 上，与源包隔离

功能调整：
- 删除 keep_last_selection 模式（原「自动使用上次选择」），
  连同其分支与配套的 last_selection 存储一起移除

API 版本（V1 -> V3）：
- 节点定义由 INPUT_TYPES / RETURN_TYPES 改为 io.ComfyNode + define_schema。
- 对应关系：
    INPUT_IS_LIST = True            -> io.Schema(is_input_list=True)
    OUTPUT_NODE = True              -> io.Schema(is_output_node=True)
    OUTPUT_IS_LIST = (True, False)  -> 输出逐个声明 io.Image.Output(..., is_output_list=True)
    hidden = {prompt, unique_id, extra_pnginfo} -> io.Hidden.*，执行时用 cls.hidden.* 读取
    IS_CHANGED                      -> fingerprint_inputs
    return {"result": (...)}        -> return io.NodeOutput(...)
- 节点 id、输入 id、输出顺序与选项值均未变化，旧工作流可直接打开；
  前端通过 nodeData.name === "MK_ImageSelector" 匹配，也不受影响。

中文显示名由 locales/zh/nodeDefs.json 提供，内部 id 与选项值保持英文，
以免影响 API 调用与已保存的工作流 JSON。
"""

import logging
import time
from threading import Event

import torch
from aiohttp import web
from nodes import PreviewImage
from server import PromptServer

import comfy.model_management
from comfy_api.latest import io

ROUTE_SELECT = "/mk_image_selector/select"
EVENT_UPDATE = "mk_image_selector_update"
# 说明：EVENT_SELECTION 原供 keep_last_selection 模式通知前端同步选中态使用。
# 该模式已按需求删除，此事件当前不再发送，但保留常量与前端监听器——
# 交互链路无法自动化验证，此处刻意减少改动面，确认无用后可一并清理。
EVENT_SELECTION = "mk_image_selector_selection"

MODE_ALWAYS_PAUSE = "always_pause"
MODE_PASSTHROUGH = "passthrough"
MODE_OPTIONS = [MODE_ALWAYS_PAUSE, MODE_PASSTHROUGH]

_SESSION_KEYS = ("event", "selected_indices", "images", "total_count", "cancelled")


class ImageSelectorCancelled(Exception):
    pass


def get_selector_storage():
    """获取图像选择器的共享存储空间"""
    if not hasattr(PromptServer.instance, "_mk_selector_node_data"):
        PromptServer.instance._mk_selector_node_data = {}
    return PromptServer.instance._mk_selector_node_data


def _cleanup_session_data(node_id):
    """清理会话数据。

    与源实现一致：只删会话字段，不删 node_id 这个空条目——
    execute 的等待循环依赖 `node_id in node_data` 作为存活判断。
    """
    node_data = get_selector_storage()
    if node_id in node_data:
        for key in _SESSION_KEYS:
            if key in node_data[node_id]:
                del node_data[node_id][key]


def _flatten_images(images):
    """把上游传入的 IMAGE 批次拆成单张 (1, H, W, C) 列表。

    与源实现逐行等价：列表里的非 Tensor 元素被静默跳过，
    非法维度/类型抛 ValueError（由 execute 的兜底分支接管）。
    """
    image_list = []
    if isinstance(images, list):
        for img in images:
            if isinstance(img, torch.Tensor):
                if len(img.shape) == 4:
                    for i in range(img.shape[0]):
                        image_list.append(img[i:i + 1])
                elif len(img.shape) == 3:
                    image_list.append(img.unsqueeze(0))
    elif isinstance(images, torch.Tensor):
        if len(images.shape) == 4:
            for i in range(images.shape[0]):
                image_list.append(images[i:i + 1])
        elif len(images.shape) == 3:
            image_list.append(images.unsqueeze(0))
        else:
            raise ValueError(f"不支持的图像维度: {images.shape}")
    else:
        raise ValueError(f"不支持的输入类型: {type(images)}")
    return image_list


class MKImageSelector(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MK_ImageSelector",
            display_name="MK-图像选择器",
            category="MK节点",
            description="把上游图像拆成多张，执行时暂停并在节点上点选，返回选中的图像与索引。",
            search_aliases=[
                "image selector", "pick image", "choose image", "select image",
                "图像选择", "选图", "选择图像",
            ],
            inputs=[
                io.Image.Input(
                    "images",
                    display_name="图像",
                    tooltip="待选择的图像。多张时会平铺显示在节点上，点击即可选中。",
                ),
                io.Combo.Input(
                    "mode",
                    display_name="模式",
                    options=MODE_OPTIONS,
                    default=MODE_ALWAYS_PAUSE,
                    tooltip="等待选择：执行时暂停，等你在节点上点选后点确认继续。"
                            "自动通过：不暂停，直接放行全部图像。",
                ),
            ],
            outputs=[
                io.Image.Output(
                    "selected_images",
                    display_name="选中图像",
                    tooltip="被选中的图像",
                    is_output_list=True,
                ),
                io.String.Output(
                    "selected_indices",
                    display_name="选中索引",
                    tooltip="被选中的图像序号，多个以英文逗号分隔",
                ),
            ],
            hidden=[io.Hidden.prompt, io.Hidden.unique_id, io.Hidden.extra_pnginfo],
            is_input_list=True,
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, images, mode):
        # 与原 IS_CHANGED 一致：始终视为已变化，保证每次执行都停下来等选择。
        return float(time.time())

    @classmethod
    def execute(cls, images, mode):
        node_id = ""
        image_list = []

        try:
            node_id = str(cls.hidden.unique_id)
            actual_mode = mode[0] if isinstance(mode, list) else mode
            prompt = cls.hidden.prompt

            # 获取共享存储空间
            node_data = get_selector_storage()

            image_list = _flatten_images(images)
            total_count = len(image_list)

            preview_images = []
            saver = PreviewImage()
            for img in image_list:
                try:
                    result = saver.save_images(images=img, prompt=prompt)
                    if 'ui' in result and 'images' in result['ui']:
                        preview_images.extend(result['ui']['images'])
                except Exception:
                    continue

            try:
                PromptServer.instance.send_sync(EVENT_UPDATE, {
                    "id": node_id,
                    "urls": preview_images,
                })
            except Exception:
                pass

            if actual_mode == MODE_PASSTHROUGH:
                _cleanup_session_data(node_id)
                all_indices = ','.join(str(i) for i in range(total_count))
                return io.NodeOutput(image_list, all_indices)

            if node_id in node_data:
                del node_data[node_id]

            event = Event()
            node_data[node_id] = {
                "event": event,
                "selected_indices": None,
                "images": image_list,
                "total_count": total_count,
                "cancelled": False,
            }

            while node_id in node_data:
                node_info = node_data[node_id]
                if node_info.get("cancelled", False):
                    _cleanup_session_data(node_id)
                    raise ImageSelectorCancelled("用户取消选择")

                if "selected_indices" in node_info and node_info["selected_indices"] is not None:
                    break

                time.sleep(0.1)

            if node_id in node_data:
                node_info = node_data[node_id]
                selected_indices = node_info.get("selected_indices")

                if selected_indices is not None and len(selected_indices) > 0:
                    valid_indices = [idx for idx in selected_indices if 0 <= idx < total_count]
                    if valid_indices:
                        selected_images = [image_list[idx] for idx in valid_indices]

                        _cleanup_session_data(node_id)
                        indices_str = ','.join(str(i) for i in valid_indices)
                        return io.NodeOutput(selected_images, indices_str)
                    else:
                        _cleanup_session_data(node_id)
                        return io.NodeOutput(
                            [image_list[0]] if total_count > 0 else [],
                            "0" if total_count > 0 else "",
                        )
                else:
                    _cleanup_session_data(node_id)
                    return io.NodeOutput(
                        [image_list[0]] if total_count > 0 else [],
                        "0" if total_count > 0 else "",
                    )
            else:
                return io.NodeOutput(
                    [image_list[0]] if total_count > 0 else [],
                    "0" if total_count > 0 else "",
                )

        except ImageSelectorCancelled:
            raise comfy.model_management.InterruptProcessingException()
        except Exception:
            _cleanup_session_data(node_id)
            if image_list:
                return io.NodeOutput([image_list[0]], "0")
            else:
                return io.NodeOutput([], "")


def _register_route(handler):
    """注册交互路由。

    PromptServer 未初始化时只告警不抛异常——否则整个包导入失败，
    会把 MK-加载图像 一起带下线。真实运行环境下 instance 一定存在。
    """
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        logging.warning("[MK] PromptServer 尚未初始化，MK-图像选择器的交互路由未注册")
        return handler
    instance.routes.post(ROUTE_SELECT)(handler)
    return handler


@_register_route
async def select_image_handler(request):
    try:
        data = await request.json()
        node_id = data.get("node_id")
        selected_indices = data.get("selected_indices", [])
        action = data.get("action")

        # 获取共享存储空间
        node_data = get_selector_storage()

        if node_id not in node_data:
            return web.json_response({"success": False, "error": "节点数据不存在"})

        try:
            node_info = node_data[node_id]

            if "total_count" not in node_info:
                return web.json_response({"success": False, "error": "节点已完成处理"})

            if action == "cancel":
                node_info["cancelled"] = True
                node_info["selected_indices"] = []
            elif action == "select" and isinstance(selected_indices, list):
                valid_indices = [
                    idx for idx in selected_indices
                    if isinstance(idx, int) and 0 <= idx < node_info["total_count"]
                ]
                if valid_indices:
                    node_info["selected_indices"] = valid_indices
                    node_info["cancelled"] = False
                else:
                    return web.json_response({"success": False, "error": "选择索引无效"})
            else:
                return web.json_response({"success": False, "error": "无效操作"})

            node_info["event"].set()
            return web.json_response({"success": True})

        except Exception:
            if node_id in node_data and "event" in node_data[node_id]:
                node_data[node_id]["event"].set()
            return web.json_response({"success": False, "error": "处理失败"})

    except Exception:
        return web.json_response({"success": False, "error": "请求失败"})
