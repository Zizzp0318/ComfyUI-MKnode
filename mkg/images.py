"""图片处理：转 WebP、缩略图、显示名与文件名清洗。"""

import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from .constants import (
    ILLEGAL_CHARS,
    IMAGE_EXTS,
    MAX_LABEL,
    RESERVED_NAMES,
    THUMB_QUALITY,
    THUMB_SIDE,
    WEBP_METHOD,
    WEBP_QUALITY,
)


def _flatten(im: Image.Image) -> Image.Image:
    """转正 EXIF、透明底铺白。

    白模线稿常带 alpha，直接 convert("RGB") 会变成全黑，缩略图看起来像坏图。
    """
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        return flat
    return im.convert("RGB")


def to_webp_bytes(raw: bytes) -> bytes:
    """任意图片字节 → WebP 字节（保持原尺寸）。解不开就抛异常。"""
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(raw)) as im:
        _flatten(im).save(buffer, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
    return buffer.getvalue()


def to_thumb_bytes(raw: bytes) -> bytes:
    """任意图片字节 → 长边 THUMB_SIDE 的 JPEG。"""
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(raw)) as im:
        thumb = _flatten(im)
        thumb.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.LANCZOS)
        thumb.save(buffer, "JPEG", quality=THUMB_QUALITY, optimize=True)
    return buffer.getvalue()


def clean_label(raw: str, fallback: str = "") -> str:
    """显示名 / 分类名：去控制字符与路径符号，保留中文与空格。"""
    text = str(raw or "").strip()
    text = "".join(ch for ch in text if ord(ch) >= 32 and ch not in ILLEGAL_CHARS).strip(" .")
    return text[:MAX_LABEL] or fallback


def safe_stem(raw: str) -> str:
    """把任意名字洗成能落盘的文件名主干（不含扩展名）。"""
    name = Path(str(raw or "").replace("\\", "/")).name
    stem = Path(name).stem.strip(" .")
    stem = "".join(ch for ch in stem if ch not in ILLEGAL_CHARS and ord(ch) >= 32).strip(" .")
    if not stem:
        stem = "未命名"
    if stem.upper() in RESERVED_NAMES:
        stem = "_" + stem
    return stem[:MAX_LABEL]


def is_image(name: str) -> bool:
    return Path(str(name or "")).suffix.lower() in IMAGE_EXTS


def image_name(name: str) -> Optional[str]:
    """URL 传上来的文件名，只留 basename；不是图片后缀就返回 None。"""
    base = Path(str(name or "").replace("\\", "/")).name
    if not base or not is_image(base):
        return None
    return base
