"""MK-自适应最长边（MK_AdaptiveLongestEdge）

跟「MK-自适应百万像素」是同一思路，只是把衡量标准从「总像素」换成「最长边」：
读输入图像的长边像素数（宽、高里较大的那个），再夹到你设定的分辨率区间里。

典型接法：缩放到最长边的节点 / 需要「长边 = 多少像素」的上采样参数，
接上它就能让目标尺寸跟着输入图片自己变，而不会把大图拉得过大、小图放得过大。

判定规则（最长边 = max(宽, 高)）：

| 情况 | 输出 |
| --- | --- |
| 最长边 < 最小分辨率 | 最小分辨率 |
| 最长边 > 最大分辨率 | 最大分辨率 |
| 落在两者之间 | 图像本身的最长边 |
| 最小 == 最大 | 该值（区间退化成一个点） |

其它约定：

- 单位是**像素**，输入输出都是整数（像素没有小数）。
- 最小 > 最大时自动换位，不会出现空区间。
- 图像批次（多帧）取第一帧的宽高；同一批次的帧尺寸本来就相同。
"""

from comfy_api.latest import io

# 数值范围：64 像素 ~ 16384 像素（16K 超宽也够用）
MIN_EDGE_LIMIT = 64
MAX_EDGE_LIMIT = 16384


def _first_image(image):
    """批次可能以 list 形式传进来，取第一张。"""
    if isinstance(image, (list, tuple)):
        return image[0] if image else None
    return image


def longest_edge_of(image) -> int:
    """取图像的最长边（宽、高里较大的那个）。

    Args:
        image: ComfyUI 的 IMAGE，形状为 (B, H, W, C)（也兼容不带批次维的 (H, W, C)）。

    Returns:
        最长边的像素数；拿不到图像时返回 0。
    """
    tensor = _first_image(image)
    if tensor is None:
        return 0
    # 倒数第 3、2 维固定是 H、W（最后一位是通道）
    height = int(tensor.shape[-3])
    width = int(tensor.shape[-2])
    return max(width, height)


def clamp_edge(edge: int, min_resolution: int, max_resolution: int) -> int:
    """把实际最长边夹到 [min, max] 区间；min > max 时自动换位。"""
    low, high = (min_resolution, max_resolution) if min_resolution <= max_resolution \
        else (max_resolution, min_resolution)
    return int(min(max(int(edge), int(low)), int(high)))


class MKAdaptiveLongestEdge(io.ComfyNode):
    """按图像最长边输出分辨率，并限制在你设定的区间内。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_AdaptiveLongestEdge",
            display_name="MK-自适应最长边",
            category="MK节点",
            description=(
                "读取输入图像的宽与高，取较长的一边作为分辨率输出，并限制在设定的最小值与最大值之间。"
                "图像最长边小于最小值时输出最小值，大于最大值时输出最大值，落在区间内则输出图像实际最长边。"
            ),
            inputs=[
                io.Image.Input(
                    "image",
                    display_name="图像",
                    tooltip="用来读取尺寸的图像。多帧批次按第一帧的宽高计算。",
                ),
                io.Int.Input(
                    "min_resolution",
                    display_name="最小分辨率",
                    default=512,
                    min=MIN_EDGE_LIMIT,
                    max=MAX_EDGE_LIMIT,
                    step=1,
                    tooltip="下限（像素）。图像最长边小于它时，直接输出这个值。",
                ),
                io.Int.Input(
                    "max_resolution",
                    display_name="最大分辨率",
                    default=2048,
                    min=MIN_EDGE_LIMIT,
                    max=MAX_EDGE_LIMIT,
                    step=1,
                    tooltip="上限（像素）。图像最长边大于它时，直接输出这个值。与最小值填一样则固定输出该值。",
                ),
            ],
            outputs=[
                io.Int.Output(
                    "LONGEST_EDGE",
                    display_name="最长边",
                    tooltip="夹在区间内的最长边像素数，可直接接缩放节点的宽/高、或「按最长边缩放」的目标尺寸。",
                ),
            ],
        )

    @classmethod
    def execute(cls, image, min_resolution, max_resolution):
        actual = longest_edge_of(image)
        value = clamp_edge(actual, min_resolution, max_resolution)
        return io.NodeOutput(value)
