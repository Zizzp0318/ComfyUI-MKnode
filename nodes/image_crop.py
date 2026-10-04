"""MK-图像裁剪（MK_ImageCrop）

迁移自 Comfyui-MK_Tools 的 ``nodes/image_crop.py``
（其本身迁移自 ComfyUI_essentials 的 ``ImageCrop+`` / 🔧 Image Crop）。

本模块相对源包版本的改动：

- 分类 ``MK_Tools/image`` → ``MK节点``，与包内其余节点统一
- 由 V1 改写为 V3（``io.ComfyNode`` / ``io.Schema`` / ``io.NodeOutput``），
  与包内其他纯计算节点一致；输入输出补上中文显示名与提示
- 位置映射表从函数内提到模块级常量，方便复用与查阅
- 只导出节点类，注册统一交给包根 ``__init__.py``
- 补充 ``DESCRIPTION`` / ``SEARCH_ALIASES``

刻意保持不变（兼容性优先）：

- 节点 id 仍是 ``MK_ImageCrop``。已发布的 node_id 不能改，
  否则引用它的已保存工作流会失联。
- 内部输入 id 与 ``位置`` 的选项值都是中文（``图像`` / ``宽度`` / ``位置`` /
  ``左上角``…）。包内其他节点遵循「内部 id 用英文、显示名走 locales」的约定，
  本节点是例外——为兼容源包已保存的工作流而保留原样。它们本来就是中文，
  显示名直接写在 schema 里，因此不需要额外的语言包条目。

裁剪逻辑与坐标计算逐行照搬源包，未做任何改动，包括它的边界处理方式：

- 先把 ``宽度`` / ``高度`` 收敛到不超过原图尺寸；
- 越界时把 ``x2`` / ``y2`` 夹到图像边界、把 ``x`` / ``y`` 夹到 0，
  **但不会据此重算 x2 / y2**。因此负偏移会让裁剪结果变小，而不是平移窗口。
  这与上游 ComfyUI_essentials 的行为一致，刻意保留，以免与源包产出不一致。
"""

from comfy_api.latest import io
from nodes import MAX_RESOLUTION

# 位置选项（同时也是 COMBO 的选项值，保持中文以兼容源包工作流）
POSITIONS = [
    "左上角",
    "上方居中",
    "右上角",
    "右侧居中",
    "右下角",
    "下方居中",
    "左下角",
    "左侧居中",
    "居中",
]

# 中文选项 → 内部方位关键字。关键字同时被多个判断命中时，
# 后判定的轴会覆盖先判定的（见 execute 里的注释）。
POSITION_KEYWORDS = {
    "左上角": "top-left",
    "上方居中": "top-center",
    "右上角": "top-right",
    "右侧居中": "right-center",
    "右下角": "bottom-right",
    "下方居中": "bottom-center",
    "左下角": "bottom-left",
    "左侧居中": "left-center",
    "居中": "center",
}


class MKImageCrop(io.ComfyNode):
    """按指定的宽度、高度、位置与偏移量裁剪图像。

    支持批量：同一组裁剪参数会应用到批次里的每一张图。
    """

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_ImageCrop",
            display_name="MK-图像裁剪",
            category="MK节点",
            description=(
                "按指定的宽度、高度、位置与偏移量裁剪图像，并输出实际裁剪起点的 x/y 坐标。"
                "裁剪尺寸超过原图时会自动收敛到原图尺寸。"
            ),
            search_aliases=[
                "crop", "crop image", "image crop", "trim image", "cut image",
                "图像裁剪", "裁剪", "切图", "截图",
            ],
            inputs=[
                io.Image.Input(
                    "图像",
                    display_name="图像",
                    tooltip="待裁剪的图像，支持批量；批次内每张图使用同一组裁剪参数。",
                ),
                io.Int.Input(
                    "宽度",
                    display_name="宽度",
                    default=256,
                    min=0,
                    max=MAX_RESOLUTION,
                    step=8,
                    tooltip="裁剪宽度，步长 8。超过原图宽度时自动收敛到原图宽度。",
                ),
                io.Int.Input(
                    "高度",
                    display_name="高度",
                    default=256,
                    min=0,
                    max=MAX_RESOLUTION,
                    step=8,
                    tooltip="裁剪高度，步长 8。超过原图高度时自动收敛到原图高度。",
                ),
                io.Combo.Input(
                    "位置",
                    display_name="位置",
                    options=POSITIONS,
                    default=POSITIONS[0],
                    tooltip="裁剪的基准位置，可用 X/Y 轴偏移继续微调。",
                ),
                io.Int.Input(
                    "X轴偏移",
                    display_name="X 轴偏移",
                    default=0,
                    min=-99999,
                    step=1,
                    tooltip="在基准位置之上再横向移动的距离，可为负。",
                ),
                io.Int.Input(
                    "Y轴偏移",
                    display_name="Y 轴偏移",
                    default=0,
                    min=-99999,
                    step=1,
                    tooltip="在基准位置之上再纵向移动的距离，可为负。",
                ),
            ],
            outputs=[
                io.Image.Output("IMAGE", display_name="图像"),
                io.Int.Output("x", display_name="X 坐标"),
                io.Int.Output("y", display_name="Y 坐标"),
            ],
        )

    @classmethod
    def execute(cls, 图像, 宽度, 高度, 位置, X轴偏移, Y轴偏移):
        """裁剪图像并返回 (裁剪结果, x, y)。"""
        _, oh, ow, _ = 图像.shape

        # 裁剪尺寸不能超过原图
        width = min(ow, 宽度)
        height = min(oh, 高度)

        x = 0
        y = 0

        position = POSITION_KEYWORDS.get(位置, 位置)

        # 先按 "center" 给两个轴都定一个基准，再由 top/bottom/left/right
        # 覆盖对应轴——顺序不能调换，否则 "top-center" 这类会被 center 覆盖回去。
        if "center" in position:
            x = round((ow - width) / 2)
            y = round((oh - height) / 2)
        if "top" in position:
            y = 0
        if "bottom" in position:
            y = oh - height
        if "left" in position:
            x = 0
        if "right" in position:
            x = ow - width

        x += X轴偏移
        y += Y轴偏移

        x2 = x + width
        y2 = y + height

        # 边界保护：与上游一致，夹取 x2/y2 后不再回头重算 x/y 对应的尺寸
        if x2 > ow:
            x2 = ow
        if x < 0:
            x = 0
        if y2 > oh:
            y2 = oh
        if y < 0:
            y = 0

        image = 图像[:, y:y2, x:x2, :]

        return io.NodeOutput(image, x, y)
