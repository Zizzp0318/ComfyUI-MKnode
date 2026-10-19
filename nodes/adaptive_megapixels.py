"""MK-自适应百万像素（MK_AdaptiveMegapixels）

用途：把「一张图到底按多少百万像素处理」交给图自己决定，同时不让它超出你允许的区间。
典型接法：`MK-加载图像（缩放模式=按总像素）` → 本节点 → 目标总像素；
或者直接把输出接到任何需要「百万像素(MP)」的节点上。

判定规则（按输入图像的实际总像素 = 宽 × 高）：

| 情况 | 输出 |
| --- | --- |
| 实际总像素 < 最小百万像素 | 最小百万像素 |
| 实际总像素 > 最大百万像素 | 最大百万像素 |
| 落在两者之间 | 图像本身的总像素（换算成 MP） |
| 最小 == 最大 | 该值（区间退化为一个点） |

几点说明：

- 单位是**百万像素(MP)**，1 MP = 1,000,000 像素，跟官方「按总像素缩放」里的 MP 一致。
- 输出保留 **2 位小数**（如 1080×1928 = 2.08224 MP → 2.08），避免小数点后拖一长串；
  需要更细的精度可以改 `_OUTPUT_DIGITS`。
- 最小 > 最大时按「最小值/最大值」自动换位，不会出现空区间。
- 图像批次（多帧）取第一帧的宽高；同一批次的帧尺寸本来就相同。
"""

from comfy_api.latest import io

# 数值范围：0.01 MP（约 100×100）~ 64 MP（约 8K 以上），够覆盖常见需求
MIN_MP_LIMIT = 0.01
MAX_MP_LIMIT = 64.0

# 输出保留的小数位数：2 位（2.08224 MP → 2.08）。想要更细的精度改这里即可。
_OUTPUT_DIGITS = 2


def _first_image(image):
    """批次可能以 list 形式传进来，取第一张。"""
    if isinstance(image, (list, tuple)):
        return image[0] if image else None
    return image


def megapixels_of(image) -> float:
    """取图像的总像素并换算成百万像素(MP)。

    Args:
        image: ComfyUI 的 IMAGE，形状为 (B, H, W, C)（也兼容不带批次维的 (H, W, C)）。

    Returns:
        总像素 / 1,000,000。
    """
    tensor = _first_image(image)
    if tensor is None:
        return 0.0
    # 倒数第 3、2 维固定是 H、W（最后一位是通道）
    height = int(tensor.shape[-3])
    width = int(tensor.shape[-2])
    return (width * height) / 1_000_000.0


def clamp_megapixels(megapixels: float, min_megapixels: float, max_megapixels: float) -> float:
    """把实际百万像素夹到 [min, max] 区间；min > max 时自动换位。"""
    low, high = (min_megapixels, max_megapixels) if min_megapixels <= max_megapixels \
        else (max_megapixels, min_megapixels)
    value = min(max(megapixels, low), high)
    return round(value, _OUTPUT_DIGITS)


class MKAdaptiveMegapixels(io.ComfyNode):
    """按图像实际像素数输出百万像素，并限制在你设定的区间内。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_AdaptiveMegapixels",
            display_name="MK-自适应百万像素",
            category="MK节点",
            description=(
                "读取输入图像的总像素（宽×高），换算成百万像素输出，并限制在设定的最小值与最大值之间。"
                "图像比最小值还小时输出最小值，比最大值还大时输出最大值，落在区间内则输出图像实际像素。"
            ),
            inputs=[
                io.Image.Input(
                    "image",
                    display_name="图像",
                    tooltip="用来读取像素数的图像。多帧批次按第一帧的宽高计算。",
                ),
                io.Float.Input(
                    "min_megapixels",
                    display_name="最小百万像素",
                    default=1.0,
                    min=MIN_MP_LIMIT,
                    max=MAX_MP_LIMIT,
                    step=0.01,
                    tooltip="下限。图像总像素低于它时，直接输出这个值。",
                ),
                io.Float.Input(
                    "max_megapixels",
                    display_name="最大百万像素",
                    default=4.0,
                    min=MIN_MP_LIMIT,
                    max=MAX_MP_LIMIT,
                    step=0.01,
                    tooltip="上限。图像总像素高于它时，直接输出这个值。与最小值填一样则固定输出该值。",
                ),
            ],
            outputs=[
                io.Float.Output(
                    "MEGAPIXELS",
                    display_name="百万像素",
                    tooltip="夹在区间内的百万像素数（保留 2 位小数），可直接接「按总像素缩放」的目标总像素。",
                ),
            ],
        )

    @classmethod
    def execute(cls, image, min_megapixels, max_megapixels):
        actual = megapixels_of(image)
        value = clamp_megapixels(actual, min_megapixels, max_megapixels)
        return io.NodeOutput(value)
