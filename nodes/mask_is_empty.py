"""MK-遮罩是否为空（MK_MaskIsEmpty）

迁移自 GoohaiTools-comfyui 的「孤海遮罩检测」
（``nodes/遮罩检测.py``，节点 id ``GuHaiMaskDetect``）。

用途：判断一张遮罩里到底有没有内容，输出布尔值，方便接「跳过分支 / 开关 / 条件执行」。
典型场景：抠图或分割之后，先看遮罩是不是空的，空图就不往下跑。

判定规则（与原节点完全一致）：

- 像素值 **> 0.5** 视为有效（遮罩通常是 0–1 的浮点，0.5 就是黑白分界）；
- 「过滤最小值」是**有效面积占全图的百分比**：
  - 设为 **0** → 只要存在有效像素就输出 True（不算面积，最省事）；
  - 其余值 → 有效面积占比 **≥** 该值才输出 True，否则 False（滤掉零星噪点）；
- 遮罩里一个有效像素都没有时直接输出 False，不做除法。

批量说明：传入 ``[B, H, W]`` 时按整批一起算（总面积 = B×H×W），
即「这一批里有没有足够多的有效像素」，与原节点的 ``squeeze()`` 行为一致。

相对源节点的改动只有命名与描述：
- 节点 id ``GuHaiMaskDetect`` -> ``MK_MaskIsEmpty``，显示名 -> ``MK-遮罩是否为空``；
- 分类 ``孤海工具箱`` -> ``MK节点``；
- 输入 id 改为英文（``mask`` / ``min_area_percent``），中文显示名与提示走 Schema，
  符合本包「内部 id 用英文」的约定；输出语义不变（True = 有内容，即非空）。
"""

import numpy as np
import torch
from comfy_api.latest import io

# 有效像素阈值：与原节点一致
PIXEL_THRESHOLD = 0.5


class MKMaskIsEmpty(io.ComfyNode):
    """判断遮罩里有没有有效内容（可要求最小有效面积占比）。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_MaskIsEmpty",
            display_name="MK-遮罩是否为空",
            category="MK节点",
            description=(
                "判断遮罩里有没有有效内容，输出布尔值：True = 有遮罩（非空），False = 空遮罩。"
                "「过滤最小值」是有效面积占全图的百分比，用来滤掉零星噪点；设为 0 则只看有没有像素。"
            ),
            search_aliases=[
                "mask empty", "mask detect", "mask exists", "is empty", "has mask",
                "遮罩检测", "遮罩为空", "空遮罩", "有无遮罩", "判断遮罩",
            ],
            inputs=[
                io.Mask.Input(
                    "mask",
                    display_name="遮罩",
                    tooltip="要判断的遮罩。多帧批次按整批一起统计。",
                ),
                io.Float.Input(
                    "min_area_percent",
                    display_name="过滤最小值",
                    default=3.0,
                    min=0.0,
                    max=10.0,
                    step=0.1,
                    display_mode=io.NumberDisplay.slider,
                    tooltip=(
                        "有效面积占全图的百分比阈值（像素值 > 0.5 才算有效）。"
                        "有效占比 ≥ 该值输出 True。设为 0 时不计算面积，只要有一个有效像素就输出 True。"
                    ),
                ),
            ],
            outputs=[
                io.Boolean.Output(
                    "has_mask",
                    display_name="是否有遮罩",
                    tooltip="True = 遮罩非空（有效面积达到阈值）；False = 空遮罩或有效面积不足。",
                ),
            ],
        )

    @classmethod
    def execute(cls, mask, min_area_percent):
        if isinstance(mask, torch.Tensor):
            arr = mask.detach().cpu().numpy()
        else:
            arr = np.asarray(mask)

        # 空遮罩（形状里带 0）直接判空，避免下面的除法出现 0/0
        if arr.size == 0:
            return io.NodeOutput(False)

        valid = arr > PIXEL_THRESHOLD
        if not valid.any():
            return io.NodeOutput(False)

        # 阈值 0：不算面积，有像素即为 True
        if float(min_area_percent) == 0.0:
            return io.NodeOutput(True)

        area_ratio = float(valid.sum()) / float(arr.size) * 100.0
        return io.NodeOutput(bool(area_ratio >= float(min_area_percent)))
