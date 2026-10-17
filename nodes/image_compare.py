"""MK-图像对比（Node API V3）

行为对齐 ComfyUI 官方节点 ImageCompare（comfy_extras/nodes_image_compare.py）：

- 两个可选 IMAGE 输入（图像A / 图像B）；
- `is_output_node = True`，执行时把两张图存进 temp 目录，把图片引用
  通过 `ui.a_images / ui.b_images` 回传给前端；
- 前端在节点上把两张图叠在一起，鼠标横向移动即可拖动分割线对比。

与官方节点的差异（按需求）：

- **新增一个 IMAGE 输出**（图像A），可把 A 图继续传给下游；
- 节点 id / 显示名 / 分类改为 MK_ImageCompare / MK-图像对比 / MK节点；
- 不依赖官方前端那个 `imagecompare` widget（它只给 comfyClass==="ImageCompare"
  的节点接线），改为包内 `web/image_compare.js` 自绘 DOM 组件，
  旧 LiteGraph 与 Nodes 2.0 两种渲染层都能正常显示。

为什么自己存图：官方也是用 PreviewImage 把 Tensor 落成临时文件，
前端只拿 `/view?...` URL 显示，节点本身不向下游传图。
"""

import logging

import nodes
from comfy_api.latest import io

COMPARE_PREFIX_A = "mk.compare.a"
COMPARE_PREFIX_B = "mk.compare.b"


def _save_preview(images, prefix):
    """把一批图像存成临时文件，返回前端可直接用的图片引用列表。

    与官方实现相同：借 PreviewImage.save_images，拿到 {"ui": {"images": [...]}}。
    单张失败不影响另一张，异常只记日志——对比节点不该因为写盘失败而中断整条流程。
    """
    if images is None or len(images) == 0:
        return []
    try:
        result = nodes.PreviewImage().save_images(images, prefix)
    except Exception as exc:  # noqa: BLE001 - 失败降级为不显示
        logging.warning("[MK] MK-图像对比 保存预览图失败: %s", exc)
        return []
    if isinstance(result, dict):
        return result.get("ui", {}).get("images", []) or []
    return []


class MKImageCompare(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MK_ImageCompare",
            display_name="MK-图像对比",
            category="MK节点",
            description="把图像A与图像B叠在一起，拖动分割线对比差异；"
                        "同时把图像A原样输出给下游。",
            search_aliases=[
                "image compare", "compare images", "diff", "before after",
                "图像对比", "对比", "前后对比",
            ],
            inputs=[
                io.Image.Input(
                    "image_a",
                    display_name="图像A",
                    tooltip="对比的基准图（左侧/上层）。执行后会原样从「图像A」输出。",
                    optional=True,
                ),
                io.Image.Input(
                    "image_b",
                    display_name="图像B",
                    tooltip="对比的参照图（底层，被分割线遮住的部分）。仅供显示，不输出。",
                    optional=True,
                ),
            ],
            outputs=[
                io.Image.Output(
                    "image",
                    display_name="图像A",
                    tooltip="把输入的图像A原样透传出去，方便接后续处理。",
                ),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, image_a=None, image_b=None) -> io.NodeOutput:
        ui = {
            "a_images": _save_preview(image_a, COMPARE_PREFIX_A),
            "b_images": _save_preview(image_b, COMPARE_PREFIX_B),
        }

        # 只给了 B 没给 A 时，输出退化为 None（下游会收到空），但仍可正常对比显示
        return io.NodeOutput(image_a, ui=ui)


NODE_CLASSES = [MKImageCompare]
