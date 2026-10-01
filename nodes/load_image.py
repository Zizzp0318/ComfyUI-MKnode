"""MK-加载图像

在 ComfyUI 原生 LoadImage 的基础上，增加「按总像素等比缩放」能力。
图像加载逻辑直接复用原生 LoadImage，保证 pyav / Pillow 两条加载路径
（含动画 WebP 回退、EXIF 旋转、alpha 转遮罩）与上游始终一致。
"""

import math
import os

import torch

import comfy.utils
import folder_paths
from comfy_api.latest import io
from nodes import LoadImage as _NativeLoadImage

RESIZE_MODES = ["禁用", "按总像素"]
UPSCALE_METHODS = ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]


def _align_to_multiple(value: int, multiple: int) -> int:
    """把 value 就近取整到 multiple 的整数倍，结果至少为一个 multiple。"""
    if multiple <= 1:
        return max(1, value)
    return max(multiple, ((value + multiple // 2) // multiple) * multiple)


def _compute_target_size(width: int, height: int, megapixels: float, multiple: int):
    """按目标总像素等比推算目标宽高，再对齐到 multiple 的整数倍。"""
    target_pixels = megapixels * 1_000_000.0
    scale = math.sqrt(target_pixels / float(width * height))
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    return _align_to_multiple(new_width, multiple), _align_to_multiple(new_height, multiple)


def _upscale_bchw(samples: torch.Tensor, width: int, height: int, upscale_method: str) -> torch.Tensor:
    """common_upscale 的薄封装。

    lanczos 走的是 PIL 灰度路径，对单通道 (B,1,H,W) 输入会先 squeeze 成
    (B,H,W)，而 common_upscale 按原始维度数原样返回，导致少一维。这里补回来。
    """
    out = comfy.utils.common_upscale(samples, width, height, upscale_method, "disabled")
    if out.ndim == samples.ndim - 1:
        out = out.unsqueeze(1)
    return out


def _resize_image(images: torch.Tensor, width: int, height: int, upscale_method: str) -> torch.Tensor:
    """(B,H,W,C) -> (B,C,H,W) 缩放 -> 还原。"""
    samples = images.movedim(-1, 1)
    samples = _upscale_bchw(samples, width, height, upscale_method)
    return samples.movedim(1, -1)


def _resize_mask(mask: torch.Tensor, width: int, height: int, upscale_method: str, source_size) -> torch.Tensor:
    """遮罩缩放到与图像一致的尺寸。

    原生 LoadImage 在图像没有 alpha 通道时会返回 64x64 的占位遮罩，
    其尺寸与图像并不一致；这种情况下直接生成目标尺寸的全零遮罩。
    """
    if tuple(mask.shape[-2:]) != tuple(source_size):
        return torch.zeros((mask.shape[0], height, width), dtype=mask.dtype, device=mask.device)
    return _upscale_bchw(mask.unsqueeze(1), width, height, upscale_method).squeeze(1)


class MKLoadImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["image"])
        return io.Schema(
            node_id="MK_LoadImage",
            display_name="MK-加载图像",
            category="MK节点",
            description="加载图像并可按目标总像素等比缩放，尺寸倍数用于把宽高对齐到指定整数倍。",
            search_aliases=["load image", "resize image", "load and resize", "加载图像", "缩放加载"],
            inputs=[
                io.Combo.Input(
                    "image",
                    display_name="图像",
                    options=sorted(files),
                    upload=io.UploadType.image,
                ),
                io.Combo.Input(
                    "resize_mode",
                    display_name="缩放模式",
                    options=RESIZE_MODES,
                    default=RESIZE_MODES[0],
                    tooltip="「禁用」保持原始尺寸；「按总像素」按目标总像素等比缩放。",
                ),
                io.Float.Input(
                    "target_megapixels",
                    display_name="目标总像素",
                    default=1.0,
                    min=0.01,
                    max=16.0,
                    step=0.01,
                    tooltip="单位为百万像素(MP)，1 表示约 100 万像素。仅在缩放模式为「按总像素」时生效。",
                ),
                io.Int.Input(
                    "size_multiple",
                    display_name="尺寸倍数",
                    default=1,
                    min=1,
                    max=256,
                    step=1,
                    tooltip="把缩放后的宽高就近对齐到该值的整数倍，1 表示不对齐。",
                ),
                io.Combo.Input(
                    "upscale_method",
                    display_name="缩放算法",
                    options=UPSCALE_METHODS,
                    default="lanczos",
                ),
            ],
            outputs=[
                io.Image.Output("IMAGE", display_name="图像"),
                io.Mask.Output("MASK", display_name="遮罩"),
                io.Int.Output("WIDTH", display_name="宽度"),
                io.Int.Output("HEIGHT", display_name="高度"),
            ],
        )

    @classmethod
    def execute(cls, image, resize_mode, target_megapixels, size_multiple, upscale_method):
        images, mask = _NativeLoadImage().load_image(image)
        height, width = images.shape[1], images.shape[2]

        if resize_mode == RESIZE_MODES[1]:
            new_width, new_height = _compute_target_size(width, height, target_megapixels, size_multiple)
        else:
            new_width, new_height = width, height

        if (new_width, new_height) != (width, height):
            images = _resize_image(images, new_width, new_height, upscale_method)
            mask = _resize_mask(mask, new_width, new_height, upscale_method, (height, width))

        return io.NodeOutput(images, mask, new_width, new_height)

    @classmethod
    def fingerprint_inputs(cls, image, resize_mode, target_megapixels, size_multiple, upscale_method):
        # 与原生 LoadImage 一致：按文件内容哈希判断是否需要重新执行
        return _NativeLoadImage.IS_CHANGED(image)

    @classmethod
    def validate_inputs(cls, image, resize_mode, target_megapixels, size_multiple, upscale_method):
        return _NativeLoadImage.VALIDATE_INPUTS(image)
