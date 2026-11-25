"""MK-Qwen Image 2.1提示词增强（MK_QwenImage21PromptEnhancer）。

用 Qwen 官方的 PE-T2I / PE-I2I 提示词增强模型改写提示词。

模型本体就是普通的 CLIP 文本编码器（Qwen3.5-VL 9B 微调），所以整条链路完全走 ComfyUI
自带能力，不需要 transformers、也不需要 llama-cpp：

    comfy.sd.load_clip(..., clip_type=CLIPType.QWEN_IMAGE)
      → clip.tokenize(提示词, image=参考图, thinking=…, system_prompt=…)
      → clip.generate(...) → clip.decode()

和内置 TextGenerate 节点是同一套机制。系统提示词用的是 Qwen 官方随 PE 模型发布的
提示词工程规则，见 `qwen_pe_prompts.py`。

参考图只需「让模型看懂」，不需要原图分辨率：每张按「每张像素数量」单独等比缩到目标
像素数（只缩不放、长宽对齐到 32 的倍数、不补边不裁边），再以列表逐张送进 tokenizer。
1 MP ≈ 1024 个视觉 token，所以这个参数就是显存与速度的主开关。
"""

from __future__ import annotations

import gc
import json
import math
import re

import comfy.model_management
import comfy.sd
import folder_paths
import torch
from comfy.sd import CLIPType
from comfy_api.latest import io

from .qwen_pe_prompts import build_system_prompt

# 官方模型卡给出的采样参数：温度 1.0 / top_p 0.95 / top_k 20；
# 文生图版靠 presence_penalty 1.5 抑制复读，图生图版不加惩罚。
SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "repetition_penalty": 1.0}
PRESENCE_PENALTY = {"文生图": 1.5, "图生图": 0.0}

# 视觉塔的 patch 几何：patch 16 × merge 2 → 一个视觉 token 覆盖 32×32 像素。
# 长宽必须能被它整除，否则 comfy 的 patchify reshape 会直接失败，所以缩放时先对齐。
VISION_FACTOR = 32
# 极端长条图的安全上限（单边像素）：只做兜底，不参与每张的像素预算
MAX_IMAGE_EDGE = 2048
# 每张参考图缩放到的目标像素数；1 MP = 1024×1024，与包内其它节点同口径
_PIXELS_PER_MP = 1024 * 1024
# 模型侧 process_qwen2vl_images 的 min_pixels：比它小的图会被内部放大，这里先补齐好让 token 预估准
_MIN_PIXELS = 3136
MP_MIN, MP_MAX, MP_DEFAULT = 0.10, 4.00, 1.00
# 生成预算至少留这么多 token，否则模型来不及输出 JSON
MIN_GENERATE_TOKENS = 64

# 已加载的 CLIP：路径 → clip。同名模型被多个节点共用时复用同一份权重
_LOADED: dict[str, object] = {}


def _pe_choices(kind: str) -> list[str]:
    """列出 models/text_encoders 里的 PE 模型（kind 为 t2i 或 i2i）。"""
    try:
        names = folder_paths.get_filename_list("text_encoders")
    except Exception:
        names = []
    marker = f"pe_{kind}"
    hits = [n for n in names if marker in n.lower()]
    if not hits:
        return [f"（未找到 pe_{kind} 模型，请把 Qwen 官方 PE 模型放进 models/text_encoders）"]
    return hits


def _is_placeholder(name: str) -> bool:
    return name.startswith("（未找到")


def _model_path(name: str) -> str:
    path = folder_paths.get_full_path("text_encoders", name)
    if not path:
        raise FileNotFoundError(f"找不到 PE 模型文件：{name}。请确认它放在 ComfyUI/models/text_encoders/ 下。")
    return path


def _get_clip(name: str):
    """按文件名加载 PE 模型；已加载过的直接复用。"""
    if _is_placeholder(name):
        raise FileNotFoundError(
            "没有找到可用的 PE 模型。请把 Qwen 官方 PE 模型（qwen3.5_9b_qwen_image_2.1_pe_t2i / pe_i2i）"
            "放进 ComfyUI/models/text_encoders/ 后重启或刷新节点。"
        )
    path = _model_path(name)
    clip = _LOADED.get(path)
    if clip is not None:
        return clip
    clip = comfy.sd.load_clip(
        ckpt_paths=[path],
        embedding_directory=folder_paths.get_folder_paths("embeddings"),
        clip_type=CLIPType.QWEN_IMAGE,
    )
    _LOADED[path] = clip
    return clip


def _unload_clip(name: str) -> bool:
    """丢掉缓存的模型引用并清显存缓存。返回是否真的卸载了东西。"""
    try:
        path = _model_path(name)
    except Exception:
        path = None
    removed = False
    if path is not None and path in _LOADED:
        _LOADED.pop(path, None)
        removed = True
    gc.collect()
    comfy.model_management.soft_empty_cache()
    return removed


def _first_frame(image) -> torch.Tensor:
    """IMAGE 可能是批次，取第一帧（多图靠多根输入线表达，不靠批次）。"""
    if isinstance(image, (list, tuple)):
        image = image[0] if image else None
    if not isinstance(image, torch.Tensor) or image.ndim != 4:
        raise ValueError("参考图需要 BHWC 格式的 IMAGE。")
    return image[:1].float()[..., :3]


def _target_size(width: int, height: int, megapixels: float) -> tuple[int, int]:
    """单张图按目标总像素算输出尺寸：只缩不放，长宽对齐到 VISION_FACTOR。

    对齐口径与 comfy 的 ``smart_resize``（factor = patch 16 × merge 2 = 32）一致：
    这里先对齐，送进 tokenizer 的尺寸就不会再被它改一次，token 预估也就准了。
    """
    px = max(0.0, float(megapixels)) * _PIXELS_PER_MP
    if width <= 0 or height <= 0 or px <= 0:
        return max(VISION_FACTOR, width), max(VISION_FACTOR, height)
    scale = min(1.0, math.sqrt(px / float(width * height)))      # 只缩不放：小图不白烧 token
    tw = max(VISION_FACTOR, int(round(width * scale / VISION_FACTOR)) * VISION_FACTOR)
    th = max(VISION_FACTOR, int(round(height * scale / VISION_FACTOR)) * VISION_FACTOR)
    edge = max(tw, th)
    if edge > MAX_IMAGE_EDGE:                                    # 极端长条图兜底
        k = MAX_IMAGE_EDGE / float(edge)
        tw = max(VISION_FACTOR, int(tw * k) // VISION_FACTOR * VISION_FACTOR)
        th = max(VISION_FACTOR, int(th * k) // VISION_FACTOR * VISION_FACTOR)
    if tw * th < _MIN_PIXELS:                                    # 极小图：模型反正会放大，先补齐
        k = math.sqrt(_MIN_PIXELS / float(tw * th))
        tw = int(math.ceil(tw * k / VISION_FACTOR)) * VISION_FACTOR
        th = int(math.ceil(th * k / VISION_FACTOR)) * VISION_FACTOR
    return tw, th


def _vision_tokens(height: int, width: int) -> int:
    """这张图会占多少个视觉 token（32×32 像素一个）。"""
    return max(1, (int(height) // VISION_FACTOR)) * max(1, (int(width) // VISION_FACTOR))


def _prepare_image(image, megapixels: float) -> torch.Tensor:
    """单张参考图缩到目标像素数：各自等比缩放，不补边、不裁边、不放大小图。

    多张图尺寸不同也没关系 —— Qwen 的 tokenizer 本来就是逐张处理
    （``images[i]`` → 各自 ``process_qwen2vl_images``），所以这里不做共同画布。
    """
    frame = _first_frame(image)
    height, width = int(frame.shape[1]), int(frame.shape[2])
    target_w, target_h = _target_size(width, height, megapixels)
    if (target_w, target_h) != (width, height):
        frame = torch.nn.functional.interpolate(
            frame.movedim(-1, 1), size=(target_h, target_w),
            mode="bicubic", align_corners=False, antialias=True,
        ).movedim(1, -1)
    return frame.clamp_(0.0, 1.0)


def _vision_template(count: int, thinking: bool) -> str:
    """图生图用的聊天模板：先按顺序插入 <image1>…<imageN> 视觉块，再接指令。

    ComfyUI 自带的 qwen35 模板不带 `imageN` 文字标签，而官方 PE-I2I 是按
    `<image1>`、`<image2>` 这套标注训练的，所以这里自己拼模板（与 qwen_image21
    的 tokenizer 做法一致）。传了自定义模板后 tokenizer 不再附加思考块，因此
    这里一并写入。
    """
    refs = " ".join(
        f"<image{index}><|vision_start|><|image_pad|><|vision_end|>" for index in range(1, count + 1)
    )
    template = f"<|im_start|>user\n{refs}{{}}<|im_end|>\n<|im_start|>assistant\n"
    return template + ("<think>\n" if thinking else "<think>\n\n</think>\n\n")


def _prompt_token_count(tokens) -> int:
    """估算提示词占用的 token 数，用来算还剩多少生成预算。"""
    try:
        for value in tokens.values():
            if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple)):
                return len(value[0])
    except Exception:
        pass
    return 0


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_REWRITTEN = re.compile(r'"rewritten_prompt"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)
# 生成预算被耗尽时 JSON 常缺收尾引号，这里允许值一直取到结尾
_REWRITTEN_OPEN = re.compile(r'"rewritten_prompt"\s*:\s*"((?:[^"\\]|\\.)*)', re.DOTALL)


def _unescape(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def _parse_rewritten(text: str) -> str:
    """从模型输出里取出 rewritten_prompt。

    模型按要求先思考、再输出一行 JSON；这里依次做：去思考块 → 去代码围栏 →
    解析 JSON → 正则兜底（含 JSON 被截断的情况）。
    """
    if not text:
        return ""
    cleaned = _THINK_BLOCK.sub("", text).strip()
    cleaned = _FENCE.sub("", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        chunk = cleaned[start : end + 1]
        try:
            data = json.loads(chunk)
            if isinstance(data, dict):
                value = data.get("rewritten_prompt")
                if isinstance(value, str):
                    return value.strip()
        except json.JSONDecodeError:
            pass
    match = _REWRITTEN.search(cleaned) or _REWRITTEN_OPEN.search(cleaned)
    if match:
        return _unescape(match.group(1)).strip()
    # 没有 JSON：如果整段就是提示词（模型被要求只回纯文本时），原样返回
    return "" if cleaned.startswith("{") else cleaned


class MKQwenImage21PromptEnhancer(io.ComfyNode):
    """用 Qwen 官方 PE 模型把简短提示词改写成完整提示词。"""

    @classmethod
    def define_schema(cls):
        image_inputs = [
            io.Image.Input(
                f"image{index}",
                display_name=f"参考图{index}",
                optional=True,
                tooltip="图生图模式的参考图，最多 9 张。提示词里用 <image1>…<image9> 指代。",
            )
            for index in range(1, 10)
        ]
        return io.Schema(
            node_id="MK_QwenImage21PromptEnhancer",
            display_name="MK-Qwen Image 2.1提示词增强",
            category="MK节点",
            description=(
                "用 Qwen 官方的提示词增强模型（PE-T2I / PE-I2I）把简短描述改写成完整的画面提示词。"
                "文生图模式只按文字扩写；图生图模式可接最多 9 张参考图，模型会识别图片内容、"
                "主体关系和场景，再写成改图指令。输出只有增强后的提示词纯文本。"
            ),
            search_aliases=[
                "qwen prompt enhancer",
                "提示词增强",
                "提示词改写",
                "prompt rewrite",
                "PE",
                "qwen image 2.1",
            ],
            inputs=[
                io.String.Input(
                    "prompt",
                    display_name="提示词",
                    multiline=True,
                    default="",
                    tooltip="要增强的原始提示词。图生图时用 <image1>、<image2> 指代第几张参考图。",
                ),
                io.Combo.Input(
                    "task_mode",
                    options=["文生图", "图生图"],
                    default="文生图",
                    display_name="任务模式",
                    tooltip="文生图用 PE-T2I 模型扩写描述；图生图用 PE-I2I 模型改写编辑指令。",
                ),
                io.Combo.Input(
                    "output_language",
                    options=["中文", "英文"],
                    default="中文",
                    display_name="输出语言",
                    tooltip="增强后描述文字的语言。用户明确要求的画面文字、专有名词保持原文。",
                ),
                io.Combo.Input(
                    "t2i_model",
                    options=_pe_choices("t2i"),
                    display_name="文生图PE模型",
                    tooltip="任务模式为「文生图」时使用的官方 PE 模型（models/text_encoders）。",
                ),
                io.Combo.Input(
                    "i2i_model",
                    options=_pe_choices("i2i"),
                    display_name="图生图PE模型",
                    tooltip="任务模式为「图生图」时使用的官方 PE 模型（models/text_encoders）。",
                ),
                io.Float.Input(
                    "image_megapixels",
                    display_name="每张像素数量",
                    default=MP_DEFAULT,
                    min=MP_MIN,
                    max=MP_MAX,
                    step=0.05,
                    tooltip=(
                        "图生图时每张参考图的像素上限（1 MP = 1024×1024）：大图缩到这个值，"
                        "小图保持原样（不放大），不补边也不裁边，长宽对齐到 32 的倍数。"
                        "图只是喂给视觉塔「看懂」用的：1 MP ≈ 1024 个视觉 token，0.5 MP 大多数画面够用，"
                        "要看小字 / 纹理再往上调。调小能明显减少视觉 token、省显存也更快。"
                    ),
                ),
                io.Int.Input(
                    "max_output_tokens",
                    display_name="最大生成token",
                    default=4096,
                    min=MIN_GENERATE_TOKENS,
                    max=32768,
                    tooltip="思考过程与增强提示词共用这段预算。开启思考后建议 4096 起，官方示例为 16256（文生图）/ 24000（图生图）。",
                ),
                io.Int.Input(
                    "context_length",
                    display_name="上下文长度",
                    default=8192,
                    min=1024,
                    max=131072,
                    tooltip="本次调用允许的总 token 上限（提示词 + 生成）。可用生成量不会超过它。",
                ),
                io.Int.Input(
                    "seed",
                    display_name="随机种",
                    default=0,
                    min=0,
                    max=0xFFFFFFFFFFFFFFFF,
                    control_after_generate=True,
                    tooltip="采样随机种子。同种子同输入结果稳定。",
                ),
                io.Boolean.Input(
                    "enable_thinking",
                    display_name="启用思考",
                    default=True,
                    tooltip=(
                        "先思考再输出提示词。两个官方 PE 模型都是用思考块训练的，关闭会损失质量；"
                        "启用时要保证「最大生成token」够用。"
                    ),
                ),
                io.Boolean.Input(
                    "auto_unload",
                    display_name="卸载模型",
                    default=True,
                    tooltip="生成完成后卸载 PE 模型并释放显存。关闭可让下次调用更快。",
                ),
                *image_inputs,
            ],
            outputs=[
                io.String.Output(
                    "enhanced_prompt",
                    display_name="增强提示词",
                    tooltip="改写后的提示词纯文本，可直接接「文本编码」或采样器。",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt,
        task_mode,
        output_language,
        t2i_model,
        i2i_model,
        image_megapixels=MP_DEFAULT,
        max_output_tokens=4096,
        context_length=8192,
        seed=0,
        enable_thinking=True,
        auto_unload=True,
        image1=None,
        image2=None,
        image3=None,
        image4=None,
        image5=None,
        image6=None,
        image7=None,
        image8=None,
        image9=None,
    ):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("请先填写要增强的提示词。")

        model_name = t2i_model if task_mode == "文生图" else i2i_model
        references = [
            image
            for image in (image1, image2, image3, image4, image5, image6, image7, image8, image9)
            if image is not None
        ]
        if task_mode == "图生图" and not references:
            raise ValueError("图生图模式需要至少连接一张参考图。")
        if task_mode == "文生图":
            references = []

        clip = _get_clip(model_name)
        system_prompt = build_system_prompt(task_mode, output_language)

        tokenize_kwargs = {"thinking": bool(enable_thinking), "system_prompt": system_prompt}
        vision_tokens = 0
        if references:
            # 逐张缩放后以列表传给 tokenizer：每张按自己的长宽比缩到目标像素数，
            # 不拼成同一个 batch，所以不需要补边 / 裁边（Qwen 内部本来就是逐张编码）。
            images = [_prepare_image(image, image_megapixels) for image in references]
            tokenize_kwargs["images"] = images
            tokenize_kwargs["llama_template"] = _vision_template(len(images), bool(enable_thinking))
            vision_tokens = sum(
                _vision_tokens(int(t.shape[1]), int(t.shape[2])) for t in images
            )
            print("[MK-提示词增强] %d 张参考图 × %.2f MP → 约 %d 个视觉 token（首张 %dx%d）"
                  % (len(images), float(image_megapixels), vision_tokens,
                     int(images[0].shape[2]), int(images[0].shape[1])))
        tokens = clip.tokenize(prompt.strip(), **tokenize_kwargs)

        # 「上下文长度」是总预算，扣掉提示词占用的部分才是能生成的量
        prompt_tokens = _prompt_token_count(tokens)
        budget = int(context_length) - prompt_tokens
        max_length = max(MIN_GENERATE_TOKENS, min(int(max_output_tokens), budget))
        if budget < int(max_output_tokens):
            print("[MK-提示词增强] ⚠️ 上下文不足：提示词 %d token（其中视觉 %d）+ 期望生成 %d > 上下文 %d，"
                  "本次生成长度压到 %d；建议把「上下文长度」提到 ≥ %d"
                  % (prompt_tokens, vision_tokens, int(max_output_tokens), int(context_length),
                     max_length, prompt_tokens + int(max_output_tokens)))

        generated = clip.generate(
            tokens,
            do_sample=True,
            max_length=max_length,
            presence_penalty=PRESENCE_PENALTY[task_mode],
            seed=int(seed),
            **SAMPLING,
        )
        text = clip.decode(generated)
        enhanced = _parse_rewritten(text)

        if auto_unload:
            _unload_clip(model_name)

        if not enhanced:
            raise RuntimeError(
                "模型没有返回可用的提示词。常见原因：只生成了思考内容就耗尽预算、"
                "或输出为空。请提高「最大生成token」（或降低「开启思考」）后重试。"
            )
        return io.NodeOutput(enhanced)


__all__ = ["MKQwenImage21PromptEnhancer"]
