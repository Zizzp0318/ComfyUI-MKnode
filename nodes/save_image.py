"""MK-图像保存

在官方 SaveImage 的基础上增加：
- 图像格式：PNG / JPEG / WEBP
- 图像质量：1-100，仅 JPEG / WEBP 生效
- 保存元数据开关：默认关，开启后写入提示词与工作流信息
- 仅预览开关：默认关，开启后写入 temp 目录而非 output 目录

文件名前缀、计数、子目录、%date% 等占位符替换全部沿用
folder_paths.get_save_image_path，与官方节点行为一致。
"""

import json
import os

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import folder_paths
from comfy.cli_args import args
from comfy_api.latest import io, ui

IMAGE_FORMATS = ["PNG", "JPEG", "WEBP"]
EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}

# EXIF UserComment 标签，JPEG / WEBP 用它承载提示词
EXIF_USER_COMMENT = 0x9286

# PNG 压缩级别，与官方 SaveImage 保持一致
PNG_COMPRESS_LEVEL = 4


def _collect_metadata(prompt, extra_pnginfo) -> dict:
    """汇总要写入的元数据，与官方 SaveImage 的字段一致。"""
    metadata = {}
    if prompt is not None:
        metadata["prompt"] = prompt
    if extra_pnginfo is not None:
        metadata.update(extra_pnginfo)
    return metadata


class MKSaveImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_SaveImage",
            display_name="MK-图像保存",
            category="MK节点",
            description="保存图像到 ComfyUI 输出目录，支持 PNG / JPEG / WEBP 与质量、元数据、仅预览控制。",
            search_aliases=["save image", "save", "export image", "保存图像"],
            is_output_node=True,
            inputs=[
                io.Image.Input("images", display_name="图像"),
                io.String.Input(
                    "filename_prefix",
                    display_name="文件名前缀",
                    default="ComfyUI",
                    tooltip="保存文件的前缀。支持 %date:yyyy-MM-dd%、%width%、%height%、%batch_num% 等占位符。",
                ),
                io.Combo.Input(
                    "image_format",
                    display_name="图像格式",
                    options=IMAGE_FORMATS,
                    default="PNG",
                ),
                io.Int.Input(
                    "quality",
                    display_name="图像质量",
                    default=95,
                    min=1,
                    max=100,
                    step=1,
                    tooltip="仅 JPEG 与 WEBP 生效，数值越高画质越好、文件越大。PNG 为无损格式，此项无效。",
                ),
                io.Boolean.Input(
                    "save_metadata",
                    display_name="保存元数据",
                    default=False,
                    label_on="开",
                    label_off="关",
                    tooltip="开启后把提示词与工作流信息写入图像。PNG 写入文本块，JPEG / WEBP 写入 EXIF。",
                ),
                io.Boolean.Input(
                    "preview_only",
                    display_name="仅预览",
                    default=False,
                    label_on="开",
                    label_off="关",
                    tooltip="开启后只写入临时目录用于预览，不占用输出目录。",
                ),
            ],
            outputs=[
                io.Image.Output("images", display_name="图像"),
            ],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
        )

    @classmethod
    def execute(cls, images, filename_prefix, image_format, quality, save_metadata, preview_only):
        if preview_only:
            base_dir = folder_paths.get_temp_directory()
            folder_type = io.FolderType.temp
        else:
            base_dir = folder_paths.get_output_directory()
            folder_type = io.FolderType.output

        height, width = (images.shape[1], images.shape[2]) if len(images.shape) == 4 else (0, 0)
        full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, base_dir, width, height
        )

        extension = EXTENSIONS[image_format]

        # --disable-metadata 启动参数优先级最高，与官方 SaveImage 行为一致
        metadata = {}
        if save_metadata and not args.disable_metadata:
            metadata = _collect_metadata(cls.hidden.prompt, cls.hidden.extra_pnginfo)

        results: list[ui.SavedResult] = []
        for batch_number, image in enumerate(images):
            array = np.clip(255.0 * image.cpu().numpy(), 0, 255).astype(np.uint8)
            pil_image = Image.fromarray(array)

            # JPEG 不支持 Alpha 通道（RGBA / LA / P 等），保存前统一转为 RGB 三通道，
            # 否则 PIL 会抛出 "cannot write mode RGBA as JPEG"。PNG / WEBP 保留原通道。
            if image_format == "JPEG" and pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            filename_with_batch_num = filename.replace("%batch_num%", str(batch_number))
            file = f"{filename_with_batch_num}_{counter:05}_.{extension}"

            save_kwargs = {}
            if image_format == "PNG":
                save_kwargs["compress_level"] = PNG_COMPRESS_LEVEL
                if metadata:
                    pnginfo = PngInfo()
                    for key, value in metadata.items():
                        pnginfo.add_text(key, json.dumps(value))
                    save_kwargs["pnginfo"] = pnginfo
            else:
                save_kwargs["quality"] = quality
                if metadata:
                    exif = pil_image.getexif()
                    exif[EXIF_USER_COMMENT] = json.dumps(metadata)
                    save_kwargs["exif"] = exif

            pil_image.save(os.path.join(full_output_folder, file), **save_kwargs)
            results.append(ui.SavedResult(filename=file, subfolder=subfolder, type=folder_type))
            counter += 1

        return io.NodeOutput(images, ui={"images": results})
