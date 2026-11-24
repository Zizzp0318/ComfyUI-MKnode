"""MK-批量图像

官方 `comfy_extras/nodes_post_processing.py` 的 `BatchImagesNode`（Batch Images，
中文界面叫「图像批处理」）的复制版，唯一目的：**能容忍空输入**。

官方实现是 `io.Autogrow`（prefix="image", min=1, max=50）+ `batch_images()`：

    max_channels = max(image.shape[-1] for image in images)   # ← 这里不判空

只要某个口连着「MK-多媒体素材解包」里未装载的槽位（值是 ``None``），
就抛 ``AttributeError: 'NoneType' object has no attribute 'shape'``。

本版改了两处（批处理算法本身逐行保留）：

1. **插槽常驻**：9 个可选 IMAGE 输入（与「MK-多媒体素材加载」的 9 个图片槽位对齐），
   不用点「+」加槽；未连线和空槽位都是 ``None``，统一跳过；
2. **全空报清晰错误**：一个可用图像都没有时直接抛
   「MK-批量图像：9 个输入口都没有图像……」，而不是让下游炸在 ``.shape`` 上。

其余行为与官方完全一致：
- 通道数对齐到最大值（不足的补一列常量 1.0，即 alpha 当不透明）；
- 尺寸对齐到**第一张**图像的宽高（双线性 + center 裁剪）；
- 输出 ``[B, H, W, C]`` 的单条 IMAGE。

不同尺寸的图会被缩到第一张的尺寸——这是官方行为，故意不改。
"""

import comfy.utils
import torch
from comfy_api.latest import io

IMAGE_SLOTS = 9


def batch_images(images):
    """把一组 IMAGE 张量拼成一条 batch（与官方 ``batch_images`` 逐行一致）。

    调用方负责过滤 ``None``；这里再兜一层空列表，避免下游拿到 ``None`` 再崩。
    """
    images = [image for image in images if image is not None]
    if len(images) == 0:
        return None
    # 先取最大通道数，再把通道不足的补齐（官方用 (0, 1) 补一列常量 1.0）
    max_channels = max(image.shape[-1] for image in images)
    padded = []
    for image in images:
        if image.shape[-1] < max_channels:
            padded.append(torch.nn.functional.pad(image, (0, 1), mode="constant", value=1.0))
        else:
            padded.append(image)
    # 再统一尺寸到第一张（双线性缩放 + center 裁剪），与官方同一套 common_upscale
    first_shape = padded[0].shape
    resized = []
    for image in padded:
        if image.shape[1:] != first_shape[1:]:
            resized.append(comfy.utils.common_upscale(
                image.movedim(-1, 1), first_shape[2], first_shape[1], "bilinear", "center"
            ).movedim(1, -1))
        else:
            resized.append(image)
    return torch.cat(resized, dim=0)


class MKBatchImages(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        inputs = []
        for i in range(1, IMAGE_SLOTS + 1):
            inputs.append(io.Image.Input(
                f"image_{i}", display_name=f"图像 {i}", optional=True,
                tooltip=f"第 {i} 路图像；接「MK-多媒体素材解包」参考图 {i} 时，"
                        f"该槽位未装载会自动跳过，不会报 NoneType"))
        return io.Schema(
            node_id="MK_BatchImages",
            display_name="MK-批量图像",
            category="MK节点",
            description="把最多 9 路图像拼成一条 batch（通道与尺寸自动对齐）。"
                        "空输入（未连线 / 素材加载的槽位未装载）自动跳过；"
                        "全部为空时给出明确错误提示。",
            search_aliases=[
                "batch", "image batch", "batch images", "combine images",
                "merge images", "stack images", "批量图像", "图像批处理", "批处理", "拼接图像",
            ],
            inputs=inputs,
            outputs=[io.Image.Output(display_name="图像")],
        )

    @classmethod
    def execute(cls, image_1=None, image_2=None, image_3=None,
                image_4=None, image_5=None, image_6=None,
                image_7=None, image_8=None, image_9=None) -> io.NodeOutput:
        slots = (image_1, image_2, image_3, image_4, image_5,
                 image_6, image_7, image_8, image_9)
        kept = [image for image in slots if image is not None]

        if not kept:
            raise ValueError(
                "MK-批量图像：%d 个输入口都没有图像（全部未连线，或素材加载节点里对应槽位未装载）。"
                "请至少接通一路有素材的图像。" % IMAGE_SLOTS
            )

        if len(kept) < len(slots):
            print("[MK-批量图像] 跳过 %d 个空输入，实际合并 %d 张（尺寸对齐到第一张 %dx%d）"
                  % (len(slots) - len(kept), len(kept),
                     int(kept[0].shape[2]), int(kept[0].shape[1])))

        return io.NodeOutput(batch_images(kept))


NODE_CLASSES = [MKBatchImages]
