"""MK 图像分块 / 分块合并的纯计算部分。

三块互不依赖的纯函数，便于单独验证：
- 分块规划：`plan_tiles` / `describe_plan` —— 只算数字，不碰张量；
- 重采样：`resample_batch` —— lanczos 走 PIL 浮点，其余走 torch；
- 颜色：`rgb_to_lab` / `lab_to_rgb` —— 纯 torch 的 sRGB <-> CIELAB，不依赖 cv2。

分块规则用一句话概括：
1. 重绘尺寸取目标尺寸，但不超过原图百万像素的 `max_growth` 倍、也不小于一个分块，
   避免小图被拉去重绘出它本来没有的细节；
2. 重绘尺寸按原图比例切成 k x k 块，尺寸不超过 `tile_megapixels` 时只切一块；
3. 重绘尺寸与目标尺寸的差额，最后由普通放大补齐。
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image

# 分块可以超出 tile_megapixels 这么多倍才真正切开：一个 2 MP 的图对齐到 32 像素网格
# 之后常常是 2.05~2.1 MP，为此多切一块不划算。
TILE_SLACK = 1.125
# 网格对齐会再加一点余量，但绝不允许因此把一张图切开。
SNAP_SLACK = 1.03
# 受 max_growth 限制的重绘尺寸只要达到目标尺寸的这个比例，就直接按目标尺寸重绘：
# 没人愿意为了 5% 的差额再走一次重采样。
NEAR_ENOUGH = 0.9
# 避免块的长边/短边超过这个比例；只有一块时保持原图比例，不做限制。
MAX_TILE_ASPECT = 2.2
# 百万像素级的图，每边放大不到这个倍数时肉眼几乎看不出变化。
MIN_VISIBLE_GROWTH = 1.6
# 每边小于这个倍数视为「缩小」，报告里会说清楚，而不是提示「尺寸太接近」。
SHRINK_BELOW = 0.97
MAX_TILES = 144


def _round_half_up(value: float) -> int:
    """四舍五入。Python 的 round 是银行家舍入，.5 会向偶数靠，这里不用它。"""
    return int(math.floor(value + 0.5))


def snap_to_multiple(value: float, multiple: int) -> int:
    """对齐到最近的倍数，且至少一步（与官方 Image Resize 的 Multiple 规则一致）。"""
    step = max(1, int(multiple))
    return max(step, _round_half_up(value / step) * step)


def megapixel_size(width: int, height: int, megapixels: float, multiple: int) -> tuple[int, int]:
    """按百万像素求目标尺寸，结果与官方 Image Resize 的 megapixels 模式一致。"""
    scale = math.sqrt(float(megapixels) * 1e6 / (int(width) * int(height)))
    return (
        snap_to_multiple(max(1, _round_half_up(width * scale)), multiple),
        snap_to_multiple(max(1, _round_half_up(height * scale)), multiple),
    )


def _starts(length: int, tile: int, count: int) -> list[int]:
    """把 ``count`` 块均匀铺满 ``length`` 像素时，每一块的左边界。"""
    if count <= 1 or tile >= length:
        return [0]
    return [_round_half_up(index * (length - tile) / (count - 1)) for index in range(count)]


def _side(length: int, count: int, overlap: int, multiple: int) -> int:
    """``count`` 块带 ``overlap`` 重叠盖住 ``length`` 时，单块的长度。"""
    if count <= 1:
        return length
    tile = math.ceil((length + (count - 1) * overlap) / count / multiple) * multiple
    return max(multiple, min(length, tile))


def _grid(width: int, height: int, cap_pixels: float, overlap: int, multiple: int) -> tuple[int, int, int, int]:
    """盖住整图所需的最少等大分块（单块不超过 ``cap_pixels``），同样块数下取最接近正方形。

    返回 (列数, 行数, 块宽, 块高)。
    """
    for count in range(1, MAX_TILES + 1):
        best = None
        for columns in range(1, count + 1):
            if count % columns:
                continue
            rows = count // columns
            tile_width = _side(width, columns, overlap, multiple)
            tile_height = _side(height, rows, overlap, multiple)
            if tile_width * tile_height > cap_pixels:
                continue
            aspect = max(tile_width / tile_height, tile_height / tile_width)
            if count > 1 and aspect > MAX_TILE_ASPECT:
                continue
            score = (abs(math.log(tile_width / tile_height)), columns)
            if best is None or score < best[0]:
                best = (score, columns, rows, tile_width, tile_height)
        if best is not None:
            return best[1:]
    raise ValueError(
        f"这张图会被切成超过 {MAX_TILES} 块，请调小成品百万像素或调大分块像素。"
    )


def plan_tiles(
    source_width: int,
    source_height: int,
    megapixels: float,
    tile_megapixels: float = 2.0,
    overlap: int = 128,
    multiple: int = 32,
    max_growth: float = 8.0,
) -> dict:
    """把一次分块放大规划成纯数字。

    ``megapixels`` 为 0 表示保持原尺寸（对成品图做一次轻量处理）。
    返回成品尺寸、重绘尺寸、单块尺寸、每块在重绘图中的坐标（逐行）以及两个方向的重叠像素。
    """
    width, height = int(source_width), int(source_height)
    if width <= 0 or height <= 0:
        raise ValueError("需要一张大于 0x0 的图片。")
    multiple = max(1, int(multiple))
    overlap = max(0, int(overlap))
    tile_mp = float(tile_megapixels)
    if tile_mp <= 0:
        raise ValueError("分块百万像素必须大于 0。")
    growth = max(1.0, float(max_growth))
    source_mp = width * height / 1e6
    keep_size = float(megapixels) <= 0
    asked_mp = source_mp if keep_size else float(megapixels)

    if keep_size:
        result_width, result_height = width, height
    else:
        result_width, result_height = megapixel_size(width, height, asked_mp, multiple)

    limit_mp = max(tile_mp, growth * source_mp)
    limited = (not keep_size) and limit_mp < asked_mp * NEAR_ENOUGH
    if keep_size:
        redraw_width = snap_to_multiple(width, multiple)
        redraw_height = snap_to_multiple(height, multiple)
    elif limited:
        redraw_width, redraw_height = megapixel_size(width, height, limit_mp, multiple)
    else:
        redraw_width, redraw_height = result_width, result_height

    columns, rows, tile_width, tile_height = _grid(
        redraw_width, redraw_height, tile_mp * TILE_SLACK * SNAP_SLACK * 1e6, overlap, multiple
    )
    xs = _starts(redraw_width, tile_width, columns)
    ys = _starts(redraw_height, tile_height, rows)
    boxes = [(x, y, x + tile_width, y + tile_height) for y in ys for x in xs]
    overlap_x = tile_width - (xs[1] - xs[0]) if len(xs) > 1 else 0
    overlap_y = tile_height - (ys[1] - ys[0]) if len(ys) > 1 else 0

    result_mp = result_width * result_height / 1e6
    growth_per_side = math.sqrt(result_mp / source_mp)
    # 目标百万像素明显小于原图：这是用户主动缩小，不算「尺寸太接近」
    shrunk = (not keep_size) and growth_per_side < SHRINK_BELOW
    return {
        "source": (width, height),
        "source_megapixels": source_mp,
        "asked_megapixels": asked_mp,
        "keep_size": keep_size,
        "result": (result_width, result_height),
        "redraw": (redraw_width, redraw_height),
        "tile": (tile_width, tile_height),
        "columns": len(xs),
        "rows": len(ys),
        "boxes": boxes,
        "overlap": (max(0, overlap_x), max(0, overlap_y)),
        "enlarged": limited,
        "shrunk": shrunk,
        "too_close": (not keep_size)
        and (not shrunk)
        and source_mp >= 1.0
        and growth_per_side < MIN_VISIBLE_GROWTH,
        "suggested_megapixels": math.ceil(source_mp * MIN_VISIBLE_GROWTH**2 * 2) / 2,
    }


def _megapixels_text(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text} MP"


def describe_plan(plan: dict) -> str:
    """用一两句话说清楚这次分块对这张图做了什么。"""
    source_width, source_height = plan["source"]
    result_width, result_height = plan["result"]
    redraw_width, redraw_height = plan["redraw"]
    tiles = len(plan["boxes"])
    tile_width, tile_height = plan["tile"]
    head = f"{source_width} x {source_height} px ({_megapixels_text(plan['source_megapixels'])})"
    redraw = _megapixels_text(redraw_width * redraw_height / 1e6)
    if tiles == 1:
        how = f"按单块 {redraw_width} x {redraw_height} px 重绘"
    else:
        how = (
            f"按 {redraw} 重绘，切成 {tiles} 块，每块 "
            f"{tile_width} x {tile_height} px"
        )
    if plan["keep_size"]:
        return f"{head} 保持原尺寸：{how}。"
    text = f"{head} -> {result_width} x {result_height} px ({_megapixels_text(result_width * result_height / 1e6)})：{how}"
    if plan["enlarged"]:
        text += "，之后用普通插值补齐到成品尺寸。这张图本来就小，没有更多细节可供重绘。"
    else:
        text += "。"
    if plan.get("shrunk"):
        text += " 原图比要求的尺寸更大，先缩小再处理。"
    if plan["too_close"]:
        text += (
            " 这一尺寸接近原图尺寸，变化会很小："
            f"建议改成 {_megapixels_text(plan['suggested_megapixels'])} 或更大。"
        )
    return text


def _lanczos_resize(batch: torch.Tensor, width: int, height: int) -> torch.Tensor:
    """逐通道用 PIL 的 lanczos 做浮点重采样，不经过 uint8 往返，遮罩也不会被量化。"""
    device = batch.device
    array = batch.detach().cpu().numpy().astype(np.float32, copy=False)
    frames = []
    for frame in array:
        channels = [
            np.asarray(
                Image.fromarray(
                    np.ascontiguousarray(frame[:, :, index]), mode="F"
                ).resize((width, height), Image.LANCZOS),
                dtype=np.float32,
            )
            for index in range(frame.shape[-1])
        ]
        frames.append(np.stack(channels, axis=-1))
    result = torch.from_numpy(np.stack(frames, axis=0))
    # lanczos 会振铃越界，图像值域只有 0..1
    return result.clamp_(0.0, 1.0).to(device)


_INTERPOLATION_MODES = ("lanczos", "bicubic", "bilinear", "nearest", "area")
_TORCH_MODES = {
    "bicubic": "bicubic",
    "bilinear": "bilinear",
    "nearest": "nearest-exact",
    "area": "area",
}


def resample_batch(
    batch: torch.Tensor, width: int, height: int, interpolation: str = "lanczos"
) -> torch.Tensor:
    """缩放一个 BHWC 浮点批次；遮罩以 BHW1 形式走同一条路径。

    尺寸已经一致时原样返回，空缩放保持逐位相同。lanczos 和 bicubic 可能过冲，
    会夹回 0..1；bilinear 与 bicubic 缩小时带抗锯齿。
    """
    if not isinstance(batch, torch.Tensor) or batch.ndim != 4:
        raise ValueError("重采样需要一个 BHWC 批次。")
    if interpolation not in _INTERPOLATION_MODES:
        raise ValueError(
            f"插值方式必须是 {_INTERPOLATION_MODES} 之一，收到 '{interpolation}'。"
        )
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("重采样目标尺寸不能为 0。")
    if batch.shape[2] == width and batch.shape[1] == height:
        return batch
    batch = batch.float()
    if interpolation == "lanczos":
        return _lanczos_resize(batch, width, height)
    moved = batch.movedim(-1, 1).contiguous()
    kwargs = {}
    if interpolation in ("bilinear", "bicubic"):
        downscale = width < moved.shape[-1] or height < moved.shape[-2]
        kwargs = {"align_corners": False, "antialias": downscale}
    resized = functional.interpolate(
        moved, size=(height, width), mode=_TORCH_MODES[interpolation], **kwargs
    )
    if interpolation == "bicubic":
        resized = resized.clamp_(0.0, 1.0)
    return resized.movedim(1, -1).contiguous()


# --- 纯 torch 的 sRGB <-> CIELAB -------------------------------------------------
# D65 白点，全程 float32，BHWC 输入输出。不用 cv2 / numpy，
# 张量在哪个设备上就在哪个设备上算。

_D65 = (0.95047, 1.0, 1.08883)
_DELTA = 6.0 / 29.0

_RGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
_XYZ_TO_RGB = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)


def _matrix(rows, like: torch.Tensor) -> torch.Tensor:
    return torch.tensor(rows, dtype=like.dtype, device=like.device)


def rgb_to_lab(rgb: torch.Tensor) -> torch.Tensor:
    """BHWC 的 sRGB（0..1）转 CIELAB（L 在 0..100，a/b 带符号）。"""
    rgb = rgb.clamp(0.0, 1.0)
    linear = torch.where(
        rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4
    )
    xyz = linear @ _matrix(_RGB_TO_XYZ, rgb).T
    scaled = xyz / _matrix([_D65], rgb)
    f = torch.where(
        scaled > _DELTA**3,
        scaled.clamp_min(1e-12) ** (1.0 / 3.0),
        scaled / (3.0 * _DELTA**2) + 4.0 / 29.0,
    )
    fx, fy, fz = f.unbind(-1)
    return torch.stack(
        [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], dim=-1
    )


def lab_to_rgb(lab: torch.Tensor) -> torch.Tensor:
    """BHWC 的 CIELAB 转回 sRGB，结果夹在 0..1。"""
    lightness, a, b = lab.unbind(-1)
    fy = (lightness + 16.0) / 116.0
    f = torch.stack([fy + a / 500.0, fy, fy - b / 200.0], dim=-1)
    scaled = torch.where(
        f > _DELTA, f**3, 3.0 * _DELTA**2 * (f - 4.0 / 29.0)
    )
    xyz = scaled * _matrix([_D65], lab)
    linear = (xyz @ _matrix(_XYZ_TO_RGB, lab).T).clamp_min(0.0)
    srgb = torch.where(
        linear <= 0.0031308,
        linear * 12.92,
        1.055 * linear ** (1.0 / 2.4) - 0.055,
    )
    return srgb.clamp(0.0, 1.0)


__all__ = [
    "MAX_TILES",
    "describe_plan",
    "lab_to_rgb",
    "megapixel_size",
    "plan_tiles",
    "resample_batch",
    "rgb_to_lab",
    "snap_to_multiple",
]
