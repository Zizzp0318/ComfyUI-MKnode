"""MK-Qwen Image 2.1文本编码器

完整复制官方 comfy_extras/nodes_qwen.py 里的 TextEncodeQwenImage21。

与官方的唯一区别：官方的参考图像输入用的是 io.Autogrow —— 前端平时只给一个「+」，
点一次才长出一个槽位，没点出来的槽位是隐藏的。这里换成 16 个常驻插槽
（image_1 ... image_16），全都直接摆在节点上。

其余（resolution 缩放规则、alpha 处理、文本编码器与 VAE 用同一份缩放结果、
keep_vision、positive/negative 的 reference_latents、latent 输出尺寸）与官方逐行一致。
"""

import math

import torch

import comfy.model_management
import comfy.utils
import node_helpers
from comfy_api.latest import io

# 常驻槽位数量：想少几个就改这里（官方上限就是 16）
IMAGE_SLOTS = 16


class MKTextEncodeQwenImage21(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        inputs = [
            io.Clip.Input("clip"),
            io.String.Input("prompt", multiline=True, dynamic_prompts=True),
            io.String.Input("negative_prompt", multiline=True, dynamic_prompts=True),
            io.Vae.Input("vae", optional=True),
            io.Int.Input("resolution", default=1024, min=0, max=4096, step=32,
                         tooltip="Reference images are resized to about resolution x resolution pixels, at multiples of 32, preserving aspect ratio. 0 keeps each reference at its own size, rounded to a multiple of 32. "),
        ]
        # 参考图像：官方为 Autogrow（names=image_1..image_16, min=0），这里改成常驻槽位
        for i in range(1, IMAGE_SLOTS + 1):
            inputs.append(io.Image.Input(
                f"image_{i}", display_name=f"参考图像 {i}", optional=True,
                tooltip=f"参考图像 {i}，会被文本编码器读取，并作为 VAE latent 拼接到序列中。"))

        return io.Schema(
            node_id="MK_TextEncodeQwenImage21",
            display_name="MK-Qwen Image 2.1文本编码器",
            category="MK节点",
            description="Qwen Image 2.1 的文本编码：提示词 + 参考图像 -> positive / negative / 空 latent。与官方节点的唯一差别：参考图像插槽全部常驻，不用点「+」加槽。",
            search_aliases=["qwen image", "qwen image 2.1", "text encode", "文本编码", "文本编码器"],
            inputs=inputs,
            outputs=[
                io.Conditioning.Output(display_name="positive"),
                io.Conditioning.Output(display_name="negative"),
                io.Latent.Output(display_name="latent",
                                 tooltip="Empty latent on the first reference image's size, to match with sampling as any other size shifts the edit."),
            ],
        )

    @classmethod
    def execute(cls, clip, prompt, negative_prompt, vae=None, resolution=1024, **kwargs) -> io.NodeOutput:
        # 常驻插槽 -> 原来的 autogrow 字典（顺序即槽位顺序，和官方按序号排序后一致）
        images = {}
        for i in range(1, IMAGE_SLOTS + 1):
            value = kwargs.get(f"image_{i}")
            if value is not None:
                images[f"image_{i}"] = value
        images = images or {}

        ref_latents = []
        images_vl = []
        latent_w = latent_h = resolution or 1024
        for name in sorted(images, key=lambda n: int(n.rsplit("_", 1)[-1])):
            image = images[name]
            if image is None:
                continue
            # 文本编码器与 VAE 用同一份缩放结果，这样每个视觉槽位都覆盖 2x2 个 latent；每个输入只用一张图
            samples = image[:1].movedim(-1, 1)
            if resolution > 0:
                ratio = samples.shape[3] / samples.shape[2]
                width = round(math.sqrt(resolution * resolution * ratio) / 32) * 32
                height = round(math.sqrt(resolution * resolution / ratio) / 32) * 32
            else:
                width, height = round(samples.shape[3] / 32) * 32, round(samples.shape[2] / 32) * 32
            width, height = max(32, width), max(32, height)
            if (width, height) == (samples.shape[3], samples.shape[2]):
                s = image[:1]
            else:
                s = comfy.utils.common_upscale(samples, width, height, "lanczos", "disabled").movedim(1, -1)
            if not images_vl:
                latent_w, latent_h = width, height
            rgb = s[:, :, :, :3]
            if s.shape[-1] > 3:
                rgb = rgb * s[:, :, :, 3:] + (1.0 - s[:, :, :, 3:])  # 视觉塔看的是白底合成图，VAE 保留四通道
            images_vl.append(rgb)
            if vae is not None:
                ref_latents.append(vae.encode(s))

        keep_vision = len(ref_latents) == 0
        positive = clip.encode_from_tokens_scheduled(clip.tokenize(prompt, images=images_vl, keep_vision=keep_vision, prevent_empty_text=True))
        negative = clip.encode_from_tokens_scheduled(clip.tokenize(negative_prompt, images=images_vl, keep_vision=keep_vision, prevent_empty_text=True))
        if len(ref_latents) > 0:
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": ref_latents}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": ref_latents}, append=True)
        latent = torch.zeros([1, 64, latent_h // 16, latent_w // 16], device=comfy.model_management.intermediate_device())
        return io.NodeOutput(positive, negative, {"samples": latent})
