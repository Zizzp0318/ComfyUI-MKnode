"""MK-图像选择器

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

ROUTE_SELECT = "/mk_image_selector/select"
EVENT_UPDATE = "mk_image_selector_update"
# 说明：EVENT_SELECTION 原供 keep_last_selection 模式通知前端同步选中态使用。
# 该模式已按需求删除，此事件当前不再发送，但保留常量与前端监听器——
# 交互链路无法自动化验证，此处刻意减少改动面，确认无用后可一并清理。
EVENT_SELECTION = "mk_image_selector_selection"


class ImageSelectorCancelled(Exception):
    pass


def get_selector_storage():
    """获取图像选择器的共享存储空间"""
    if not hasattr(PromptServer.instance, "_mk_selector_node_data"):
        PromptServer.instance._mk_selector_node_data = {}
    return PromptServer.instance._mk_selector_node_data


class MKImageSelector(PreviewImage):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "mode": (["always_pause", "passthrough"], {"default": "always_pause"}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "unique_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("selected_images", "selected_indices")
    FUNCTION = "select_image"
    CATEGORY = "MK节点"
    OUTPUT_NODE = True
    OUTPUT_IS_LIST = (True, False)
    INPUT_IS_LIST = True

    @classmethod
    def IS_CHANGED(cls, images, **kwargs):
        return float(time.time())

    def select_image(self, images, mode, prompt=None, unique_id=None, extra_pnginfo=None):
        try:
            node_id = str(unique_id[0]) if isinstance(unique_id, list) else str(unique_id)
            actual_mode = mode[0] if isinstance(mode, list) else mode

            # 获取共享存储空间
            node_data = get_selector_storage()

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

            preview_images = []
            for i, img in enumerate(image_list):
                try:
                    result = self.save_images(images=img, prompt=prompt)
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

            if actual_mode == "passthrough":
                self.cleanup_session_data(node_id)
                all_indices = ','.join(str(i) for i in range(len(image_list)))
                return {"result": (image_list, all_indices)}

            if node_id in node_data:
                del node_data[node_id]

            event = Event()
            node_data[node_id] = {
                "event": event,
                "selected_indices": None,
                "images": image_list,
                "total_count": len(image_list),
                "cancelled": False,
            }

            while node_id in node_data:
                node_info = node_data[node_id]
                if node_info.get("cancelled", False):
                    self.cleanup_session_data(node_id)
                    raise ImageSelectorCancelled("用户取消选择")

                if "selected_indices" in node_info and node_info["selected_indices"] is not None:
                    break

                time.sleep(0.1)

            if node_id in node_data:
                node_info = node_data[node_id]
                selected_indices = node_info.get("selected_indices")

                if selected_indices is not None and len(selected_indices) > 0:
                    valid_indices = [idx for idx in selected_indices if 0 <= idx < len(image_list)]
                    if valid_indices:
                        selected_images = [image_list[idx] for idx in valid_indices]

                        self.cleanup_session_data(node_id)
                        indices_str = ','.join(str(i) for i in valid_indices)
                        return {"result": (selected_images, indices_str)}
                    else:
                        self.cleanup_session_data(node_id)
                        return {"result": ([image_list[0]] if len(image_list) > 0 else [], "0" if len(image_list) > 0 else "")}
                else:
                    self.cleanup_session_data(node_id)
                    return {"result": ([image_list[0]] if len(image_list) > 0 else [], "0" if len(image_list) > 0 else "")}
            else:
                return {"result": ([image_list[0]] if len(image_list) > 0 else [], "0" if len(image_list) > 0 else "")}

        except ImageSelectorCancelled:
            raise comfy.model_management.InterruptProcessingException()
        except Exception:
            node_data = get_selector_storage()
            if node_id in node_data:
                self.cleanup_session_data(node_id)
            if 'image_list' in locals() and len(image_list) > 0:
                return {"result": ([image_list[0]], "0")}
            else:
                return {"result": ([], "")}

    def cleanup_session_data(self, node_id):
        """清理会话数据"""
        node_data = get_selector_storage()
        if node_id in node_data:
            session_keys = ["event", "selected_indices", "images", "total_count", "cancelled"]
            for key in session_keys:
                if key in node_data[node_id]:
                    del node_data[node_id][key]


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
                valid_indices = [idx for idx in selected_indices if isinstance(idx, int) and 0 <= idx < node_info["total_count"]]
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
