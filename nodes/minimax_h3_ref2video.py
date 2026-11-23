"""MK-Minimax H3多参考生视频

完整复制官方 comfy_extras/nodes_minimax_h3.py 里的 MiniMaxH3ReferenceToVideo（ref2va）。

与官方的唯一区别：官方的参考素材输入用的是 io.Autogrow —— 前端平时只给一个「+」，
点一次才长出一个槽位，没点出来的槽位是隐藏的。这里换成固定数量的常驻插槽：
9 个参考图、3 个参考视频、3 个视频原声、3 个参考音频，全都直接摆在节点上。

其余（参数、默认值、缩放规则、token 顺序、输出）与官方逐行一致，
提示词里依旧用 <Picture i> / <Video k> / <Audio j> 指代，序号按类型各自从 1 开始。
"""

import math

import torch

import nodes
import comfy.audio
import comfy.model_management
import comfy.nested_tensor
import comfy.utils
import node_helpers
from comfy_api.latest import io

CANVAS_MULTIPLE = 32
BASE_SHORT_EDGE = 768
MAX_PIXELS = 768 * 1344
REF_IMAGE_SHORT_EDGE = 2048
FPS = 24
AUDIO_LATENT_FPS = 40

# 常驻槽位数量：想少几个就改这里（官方上限就是 9 / 3 / 3 / 3）
REF_IMAGE_SLOTS = 9
REF_VIDEO_SLOTS = 3
REF_VIDEO_AUDIO_SLOTS = 3
REF_AUDIO_SLOTS = 3


def align_frame_count(n):
    while n % 17 != 5:
        n += 1
    return n


def video_latent_t(frame_count):
    return 2 if frame_count <= 5 else ((frame_count - 5) // 17) * 5 + 2


def temporal_shape(length):
    frame_count = align_frame_count(max(5, length))
    duration = frame_count / FPS
    return frame_count, video_latent_t(frame_count), round(duration * AUDIO_LATENT_FPS)


def adapt_canvas(width, height):
    """768 短边成图、总量不超过 768*1344，各轴就近对齐到 32。"""
    ratio = width / height
    if ratio >= 1.0:
        nom_w, nom_h = BASE_SHORT_EDGE * ratio, BASE_SHORT_EDGE
    else:
        nom_w, nom_h = BASE_SHORT_EDGE, BASE_SHORT_EDGE / ratio
    if nom_w * nom_h > MAX_PIXELS:
        s = math.sqrt(MAX_PIXELS / (nom_w * nom_h))
        nom_w, nom_h = nom_w * s, nom_h * s
    return (max(CANVAS_MULTIPLE, round(nom_w / CANVAS_MULTIPLE) * CANVAS_MULTIPLE),
            max(CANVAS_MULTIPLE, round(nom_h / CANVAS_MULTIPLE) * CANVAS_MULTIPLE))


def _resize(image, width, height, crop):
    # image [B, H, W, C] -> [B, height, width, 3]
    samples = image[..., :3].movedim(-1, 1)
    samples = comfy.utils.common_upscale(samples, width, height, "lanczos", crop)
    return samples.movedim(1, -1)


def _encode_ref_audio(audio_vae, audio):
    waveform = audio["waveform"]  # [B, C, L]
    sr = audio["sample_rate"]
    vae_sr = getattr(audio_vae, "audio_sample_rate", 32000)
    if sr != vae_sr:
        waveform = comfy.audio.resample(waveform, sr, vae_sr)
    z = audio_vae.encode(waveform[:1].movedim(1, -1))  # [1, 32, 2, T]
    return z, z.shape[-1]


def _av_latent(width, height, latent_t, audio_t, batch_size=1):
    video = torch.zeros([batch_size, 24, latent_t, height // 16, width // 16],
                        device=comfy.model_management.intermediate_device())
    audio = torch.zeros([batch_size, 32, 2, audio_t],
                        device=comfy.model_management.intermediate_device())
    return {"samples": comfy.nested_tensor.NestedTensor((video, audio))}


def _empty_av_latent(width, height, length, batch_size=1):
    frame_count, latent_t, audio_t = temporal_shape(length)
    return _av_latent(width, height, latent_t, audio_t, batch_size), frame_count


class MKMinimaxH3ReferenceToVideo(io.ComfyNode):
    """ref2va：提示词 + 参考图 / 参考视频 / 参考音频 -> 条件 + 音视频 latent。

    参考素材按固定顺序进入描述：先图片，再视频（每段视频的原声 <Audio j>
    紧挨在它的 <Video k> 之前），最后是独立音频。序号按类型各自 1 起算。
    """

    @classmethod
    def define_schema(cls):
        inputs = [
            io.Clip.Input("clip"),
            io.Vae.Input("vae", optional=True, tooltip="视频VAE。没有它，参考图像/视频将只能对文本编码器进行条件控制。"),
            io.Vae.Input("audio_vae", optional=True, tooltip="音频VAE。没有它，参考音频将只能对文本编码器进行条件控制。"),
            io.String.Input("prompt", multiline=True, dynamic_prompts=True),
            io.Int.Input("width", default=1344, min=32, max=nodes.MAX_RESOLUTION, step=32),
            io.Int.Input("height", default=768, min=32, max=nodes.MAX_RESOLUTION, step=32),
            io.Int.Input("length", default=124, min=5, max=3600, step=17, tooltip="以24帧/秒计算的帧数(124≈5秒，训练范围约为124-362)"),
            io.Combo.Input("ref_image_size", display_name="参考图像尺寸", options=["match", "max"], default="match",
                tooltip="参考图像尺寸。'match'会将每个参考(仅缩小，保持比例)缩放到生成图像的像素面积;'max'使用参考流程的2048px短边以获得最佳身份一致性。参考token会贯穿每一步采样，因此'max'速度会慢数倍。"),
        ]
        # 参考图：官方为 Autogrow（prefix="ref_image_", max=9），这里改成常驻槽位
        for i in range(1, REF_IMAGE_SLOTS + 1):
            inputs.append(io.Image.Input(
                f"ref_image_{i}", display_name=f"参考图 {i}", optional=True,
                tooltip=f"参考图 {i}，提示词里写 <Picture {i}>（超过 2048 短边会被缩小，不会放大）"))
        # 参考视频：官方为 Autogrow（prefix="ref_video_", max=3）
        for i in range(1, REF_VIDEO_SLOTS + 1):
            inputs.append(io.Image.Input(
                f"ref_video_{i}", display_name=f"参考视频 {i}", optional=True,
                tooltip=f"参考视频 {i} 的画面帧，24 fps，时长 2-15 秒，提示词里写 <Video {i}>"))
        # 视频原声：官方为 Autogrow（prefix="ref_video_audio_", max=3），与同序号视频配对
        for i in range(1, REF_VIDEO_AUDIO_SLOTS + 1):
            inputs.append(io.Audio.Input(
                f"ref_video_audio_{i}", display_name=f"参考视频音频 {i}", optional=True,
                tooltip=f"第 {i} 段参考视频的原声，接线时与「参考视频 {i}」同号配对"))
        # 独立音频：官方为 Autogrow（prefix="ref_audio_", max=3）
        for i in range(1, REF_AUDIO_SLOTS + 1):
            inputs.append(io.Audio.Input(
                f"ref_audio_{i}", display_name=f"参考音频 {i}", optional=True,
                tooltip=f"独立参考音频 {i}，提示词里写 <Audio {i}>"))

        return io.Schema(
            node_id="MK_MinimaxH3ReferenceToVideo",
            display_name="MK-Minimax H3多参考生视频",
            category="MK节点",
            description="<Picture i> / <Video k> / <Audio j> 参考条件（MiniMax H3）。与官方节点的唯一差别：参考素材插槽全部常驻，不用点「+」加槽。",
            search_aliases=["minimax", "h3", "reference to video", "ref2va", "多参考生视频", "参考生视频"],
            inputs=inputs,
            outputs=[io.Conditioning.Output(display_name="positive"), io.Latent.Output()],
        )

    @classmethod
    def execute(cls, clip, prompt, width, height, length, ref_image_size="match",
                vae=None, audio_vae=None, **kwargs) -> io.NodeOutput:
        latent, frame_count = _empty_av_latent(width, height, length)

        # 常驻插槽 -> 原来的 autogrow 字典（顺序即槽位顺序，和官方前端给出的顺序一致）
        def slots(prefix, count):
            found = {}
            for i in range(1, count + 1):
                value = kwargs.get(f"{prefix}{i}")
                if value is not None:
                    found[f"{prefix}{i}"] = value
            return found

        ref_images = slots("ref_image_", REF_IMAGE_SLOTS)
        ref_videos = slots("ref_video_", REF_VIDEO_SLOTS)
        ref_video_audios = slots("ref_video_audio_", REF_VIDEO_AUDIO_SLOTS)
        ref_audios = slots("ref_audio_", REF_AUDIO_SLOTS)

        ref_items = []   # 给 tokenizer 的素材清单，按请求顺序
        ref_blocks = []  # 给 DiT 的素材块，同一顺序

        for img in (ref_images or {}).values():
            if img is None:
                continue
            h, w = img.shape[1], img.shape[2]
            if ref_image_size == "match":
                # 等比缩放（只缩不放）到本次生成的像素面积
                scale = min(1.0, math.sqrt((width * height) / (w * h)))
            else:
                scale = min(1.0, REF_IMAGE_SHORT_EDGE / min(w, h))
            tw = max(CANVAS_MULTIPLE, round(w * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
            th = max(CANVAS_MULTIPLE, round(h * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
            resized = _resize(img[:1], tw, th, "disabled")
            ref_items.append({"type": "image", "data": resized})
            if vae is not None:
                z = vae.encode(resized)
                ref_blocks.append({"kind": "image", "latent_h": th // 16, "latent_w": tw // 16, "latent": z})

        ref_video_audios = ref_video_audios or {}
        for name, video_frames in (ref_videos or {}).items():
            if video_frames is None:
                continue
            # 按序号配对的原声：ref_video_audio_N 属于 ref_video_N
            soundtrack = ref_video_audios.get("ref_video_audio_" + name.rsplit("_", 1)[-1])
            vh, vw = video_frames.shape[1], video_frames.shape[2]
            cw, ch = adapt_canvas(vw, vh)
            if vw * vh < cw * ch:
                cw = max(CANVAS_MULTIPLE, round(vw / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
                ch = max(CANVAS_MULTIPLE, round(vh / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
            frames = _resize(video_frames, cw, ch, "disabled")
            if frames.shape[0] > frame_count:
                frames = frames[:frame_count]
            n = frames.shape[0]
            if n < 5:
                raise ValueError("MiniMax H3 reference videos need at least 5 frames (~0.2s at 24 fps)")
            while n % 17 != 5:
                n -= 1
            frames = frames[:n]
            if soundtrack is not None:
                # 原声有自己独立的 <Audio j> 标签，排在 <Video k> 之前
                ref_items.append({"type": "audio"})
            # Qwen 按 2 fps 带时间戳看视频
            sample_idx = list(range(0, frames.shape[0], FPS // 2))
            qwen_frames = frames[sample_idx]
            ref_items.append({"type": "video", "data": qwen_frames,
                              "timestamps": [i / 2.0 for i in range(len(sample_idx))]})
            if vae is None:
                continue
            z = vae.encode(frames)
            audio_latent, ref_audio_t = (None, 0)
            if soundtrack is not None and audio_vae is not None:
                audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, soundtrack)
            ref_blocks.append({"kind": "video_audio" if ref_audio_t else "video",
                               "latent_t": z.shape[2], "latent_h": ch // 16, "latent_w": cw // 16,
                               "ref_audio_t": ref_audio_t, "latent": z, "audio_latent": audio_latent})

        for audio in (ref_audios or {}).values():
            if audio is None:
                continue
            ref_items.append({"type": "audio"})
            if audio_vae is not None:
                audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, audio)
                ref_blocks.append({"kind": "audio", "ref_audio_t": ref_audio_t, "audio_latent": audio_latent})

        tokens = clip.tokenize(prompt, minimax_ref_items=ref_items)
        cond = clip.encode_from_tokens_scheduled(tokens)
        if ref_blocks:
            cond = node_helpers.conditioning_set_values(cond, {"minimax_refs": ref_blocks})
        return io.NodeOutput(cond, latent)
