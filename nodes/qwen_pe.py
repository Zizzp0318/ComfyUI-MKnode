"""MK-Qwen Image 2.1提示词增强（MK_QwenImage21PromptEnhancer）。

用 Qwen 官方的 PE-T2I / PE-I2I 提示词增强模型改写提示词。

模型本体就是普通的 CLIP 文本编码器（Qwen3.5-VL 9B 微调），所以整条链路完全走 ComfyUI
自带能力，不需要 transformers、也不需要 llama-cpp：

    comfy.sd.load_clip(..., clip_type=CLIPType.QWEN_IMAGE)
      → clip.tokenize(提示词, image=参考图, thinking=…, system_prompt=…)
      → clip.generate(...) → clip.decode()

和内置 TextGenerate 节点是同一套机制。系统提示词用的是 Qwen 官方随 PE 模型发布的
提示词工程规则，见 `qwen_pe_prompts.py`。
"""

from __future__ import annotations

import gc
import json
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

# 参考图统一缩放到的上限（长边像素），模型侧不需要原图分辨率
MAX_IMAGE_EDGE = 1280
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


def _fit(image: torch.Tensor, size: tuple[int, int]) -> torch.Tensor:
    """等比缩放到不超过 size，再居中补边到正好 size（模型要求所有参考图同尺寸）。"""
    height, width = int(image.shape[1]), int(image.shape[2])
    target_h, target_w = size
    scale = min(target_w / width, target_h / height)
    new_w = max(1, round(width * scale))
    new_h = max(1, round(height * scale))
    if (new_w, new_h) != (width, height):
        image = torch.nn.functional.interpolate(
            image.movedim(-1, 1), size=(new_h, new_w), mode="bicubic", align_corners=False, antialias=True
        ).movedim(1, -1)
    pad_bottom, pad_right = target_h - new_h, target_w - new_w
    if pad_bottom or pad_right:
        top, left = pad_bottom // 2, pad_right // 2
        image = torch.nn.functional.pad(
            image, (0, 0, left, pad_right - left, top, pad_bottom - top), mode="replicate"
        )
    return image.clamp_(0.0, 1.0)


def _images_batch(images: list[torch.Tensor]) -> torch.Tensor:
    """把多张参考图拼成一个批次：先各自缩到上限，再统一补到同一尺寸。"""
    frames = [_first_frame(image) for image in images]
    heights = [int(f.shape[1]) for f in frames]
    widths = [int(f.shape[2]) for f in frames]
    scale = min(1.0, MAX_IMAGE_EDGE / max(max(heights), max(widths)))
    size = (max(1, round(max(heights) * scale)), max(1, round(max(widths) * scale)))
    return torch.cat([_fit(frame, size) for frame in frames], dim=0)


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
        max_output_tokens,
        context_length,
        seed,
        enable_thinking,
        auto_unload,
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
        if references:
            batch = _images_batch(references)
            tokenize_kwargs["image"] = batch
            tokenize_kwargs["llama_template"] = _vision_template(batch.shape[0], bool(enable_thinking))
        tokens = clip.tokenize(prompt.strip(), **tokenize_kwargs)

        # 「上下文长度」是总预算，扣掉提示词占用的部分才是能生成的量
        budget = int(context_length) - _prompt_token_count(tokens)
        max_length = max(MIN_GENERATE_TOKENS, min(int(max_output_tokens), budget))

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
