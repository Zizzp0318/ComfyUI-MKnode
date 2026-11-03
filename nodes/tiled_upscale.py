"""MK-图像分块（MK_TiledUpscale）/ MK-分块合并（MK_TiledUpscaleStitch）。

一条完整链路：

    MK-图像分块 ──tiles（列表）──> 你的采样/重绘节点 ──> MK-分块合并 ──image
                 └──stitcher──────────────────────────────^
                 └──before（原图放大到成品尺寸，用于对比）

「图像分块」先按成品百万像素算出目标尺寸，再把图切成模型一次能吃下的小块：
每块单独送进采样器，跑完由「分块合并」按原位置拼回去、在接缝处做羽化混合，
最后缩放到你要的成品尺寸。

本模块基于 V3（NODE 2.0）接口：节点为 `io.ComfyNode` 子类，用 `define_schema`
声明输入输出，`execute` 返回 `io.NodeOutput`。
"""

from __future__ import annotations

import sys

import torch

from comfy_api.latest import io

from ._tiled_helpers import (
    describe_plan,
    lab_to_rgb,
    plan_tiles,
    resample_batch,
    rgb_to_lab,
)

# 分块信息连线用的自定义类型：只在「图像分块」与「分块合并」之间传递一个 dict
STITCHER_TYPE = "MK_TILE_STITCHER"
STITCHER_KIND = "mk_tile_stitcher"

TileStitcher = io.Custom(STITCHER_TYPE)

NEEDS_UPSCALE_NODE = (
    "找不到 ComfyUI 自带的「放大图像（使用模型）」节点。请更新 ComfyUI，"
    "或者干脆不接放大模型：那样会用普通插值放大。"
)


def _core_nodes() -> dict:
    """ComfyUI 自带节点类，按节点 ID 索引；不在 ComfyUI 里运行时为空。"""
    mappings = getattr(sys.modules.get("nodes"), "NODE_CLASS_MAPPINGS", None)
    return mappings if isinstance(mappings, dict) else {}


def _rgb(image: torch.Tensor, who: str) -> torch.Tensor:
    """校验并裁剪成正好三通道的 BHWC 批次。"""
    if not isinstance(image, torch.Tensor) or image.ndim != 4:
        raise ValueError(f"{who} 需要 BHWC 格式的 IMAGE 批次。")
    image = image.float()
    if image.shape[-1] == 1:
        return image.expand(-1, -1, -1, 3)
    return image[..., :3]


def _model_enlarge(upscale_model, image: torch.Tensor, width: int, height: int) -> torch.Tensor:
    """用放大模型反复放大，直到盖住目标尺寸。

    每一趟都直接调用 ComfyUI 自带的「放大图像（使用模型）」节点，这里不复制它的实现。
    返回的图会大于或等于目标尺寸，由调用方缩到准确尺寸。
    """
    runner = _core_nodes().get("ImageUpscaleWithModel")
    if runner is None or not hasattr(runner, "execute"):
        raise RuntimeError(NEEDS_UPSCALE_NODE)
    for _ in range(4):
        if image.shape[2] >= width and image.shape[1] >= height:
            break
        before = image.shape[1:3]
        image = runner.execute(upscale_model=upscale_model, image=image).result[0]
        image = _rgb(image, "MK-图像分块")
        if image.shape[1] <= before[0] or image.shape[2] <= before[1]:
            break  # 1x 模型，再放大也没用
    return image


# 颜色比对用的小图长边格数，每格是它覆盖区域的均值
COLOR_CELLS = 32
# LAB 单位。让在两张图里都接近平坦的通道（黑白照片的颜色通道）增益保持在 1 附近
COLOR_FLOOR = 0.5
COLOR_GAIN_MAX = 3.0


def _averaged_lab(rgb: torch.Tensor) -> torch.Tensor:
    """小尺寸均值图的 LAB：细节被抹平，颜色保留。"""
    height, width = int(rgb.shape[1]), int(rgb.shape[2])
    scale = COLOR_CELLS / max(height, width)
    size = (max(2, min(height, round(height * scale))), max(2, min(width, round(width * scale))))
    small = torch.nn.functional.interpolate(rgb.movedim(-1, 1), size=size, mode="area")
    return rgb_to_lab(small.movedim(1, -1))


def _keep_colors(tile: torch.Tensor, source: torch.Tensor, strength: float) -> torch.Tensor:
    """把重绘后的分块拉回它原来那块图的颜色。

    重绘块和源块画的是同一处内容，所以每个 LAB 通道做一次直线拟合
    source = gain x redraw + offset，拟合用两张小尺寸均值图。拟合跟随的是
    「两张图共有的内容」：老照片上的噪点不会把直线拽偏。若改成匹配各通道的
    方差（Color Match 的 lab 方法、面向无关参考图的做法），噪点会被当成颜色，
    一张干净重绘的浅色噪点照片会饱和到两倍。
    """
    mine, wanted = _averaged_lab(tile), _averaged_lab(source)
    mean = mine.mean(dim=(1, 2), keepdim=True)
    wanted_mean = wanted.mean(dim=(1, 2), keepdim=True)
    variance = ((mine - mean) ** 2).mean(dim=(1, 2), keepdim=True)
    shared = ((mine - mean) * (wanted - wanted_mean)).mean(dim=(1, 2), keepdim=True)
    gain = ((shared + COLOR_FLOOR**2) / (variance + COLOR_FLOOR**2)).clamp(0.0, COLOR_GAIN_MAX)
    matched = lab_to_rgb((rgb_to_lab(tile) - mean) * gain + wanted_mean)
    return tile + (matched - tile) * strength


def _ramp(length: int, rise: int, fall: int) -> torch.Tensor:
    """分块一条边上的混合权重：开头 ``rise`` 像素渐入、结尾 ``fall`` 像素渐出，中间为 1。

    一个块的渐入与相邻块的渐出在同一段上相加正好等于 1。
    """
    weights = torch.ones(length, dtype=torch.float32)
    rise = max(0, min(int(rise), length))
    fall = max(0, min(int(fall), length))
    if rise:
        weights[:rise] = torch.arange(1, rise + 1, dtype=torch.float32) / (rise + 1)
    if fall:
        weights[length - fall :] *= torch.arange(fall, 0, -1, dtype=torch.float32) / (fall + 1)
    return weights


def _shared(starts: list[int], size: int, start: int) -> tuple[int, int]:
    """这一块与前一后一块在像素上的重叠量。"""
    index = starts.index(start)
    before = starts[index - 1] + size - start if index > 0 else 0
    after = start + size - starts[index + 1] if index + 1 < len(starts) else 0
    return max(0, before), max(0, after)


class MKTiledUpscale(io.ComfyNode):
    """按目标百万像素把图切成小块，每块单独重绘。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_TiledUpscale",
            display_name="MK-图像分块",
            category="MK节点",
            description=(
                "设定成品的百万像素，把图片切成模型一次能重绘的小块。整张图放得进一块时就不切。"
                "分块送去采样器跑完，再接「MK-分块合并」，连同分块信息一路连过去即可。"
                "小图不会被拉去重绘它本来没有的细节：最多重绘到自身百万像素的「最大放大倍数」，"
                "剩下的部分用普通插值放大。连一根「报告」出去能看到这次到底做了什么。"
            ),
            search_aliases=[
                "tiled upscale",
                "分块放大",
                "图像分块",
                "切块",
                "分块",
                "百万像素",
                "放大",
            ],
            inputs=[
                io.Image.Input(
                    "image",
                    display_name="图像",
                    tooltip="要放大并切块的图片。",
                ),
                io.Float.Input(
                    "megapixels",
                    display_name="成品百万像素",
                    default=4.0,
                    min=0.0,
                    max=64.0,
                    step=0.05,
                    tooltip="成品的总像素，单位百万。填 0 表示保持原图尺寸。",
                ),
                io.UpscaleModel.Input(
                    "upscale_model",
                    display_name="放大模型",
                    optional=True,
                    tooltip=(
                        "可选。切块前先用它把图放大一遍。不接则用普通插值（lanczos）放大。"
                    ),
                ),
                io.Float.Input(
                    "tile_megapixels",
                    display_name="单块百万像素",
                    default=2.0,
                    min=0.25,
                    max=16.0,
                    step=0.05,
                    tooltip=(
                        "模型一次最多重绘多少。接近这个大小的图只切一块。"
                        "Qwen Image 2.1、Krea 2 用 2；SDXL 用 1。"
                    ),
                ),
                io.Int.Input(
                    "overlap",
                    display_name="重叠像素",
                    default=128,
                    min=0,
                    max=1024,
                    step=8,
                    tooltip="相邻分块共享多少像素。拼接时在这一条上做羽化过渡。",
                ),
                io.Int.Input(
                    "multiple",
                    display_name="对齐倍数",
                    default=32,
                    min=1,
                    max=256,
                    step=1,
                    tooltip="每块的宽高都会对齐到这个数的整数倍。32 对各种模型都适用；Qwen Image 2.1 必须用 32。",
                ),
                io.Float.Input(
                    "max_growth",
                    display_name="最大放大倍数",
                    default=8.0,
                    min=1.0,
                    max=64.0,
                    step=0.5,
                    tooltip=(
                        "小图最多重绘到自身百万像素的这个倍数，再往上只能普通插值放大。"
                        "想让很小的图硬撑到大尺寸，就把它调高。"
                    ),
                ),
            ],
            outputs=[
                io.Image.Output(
                    "tiles",
                    display_name="分块",
                    tooltip="切好的分块，逐个输出。接在后面的节点会为每块各跑一次。",
                    is_output_list=True,
                ),
                TileStitcher.Output(
                    "stitcher",
                    display_name="分块信息",
                    tooltip="「MK-分块合并」需要的分块信息，原样连过去即可。",
                ),
                io.Image.Output(
                    "before",
                    display_name="原图参考",
                    tooltip="原图用普通插值放大到成品尺寸的样子，方便和结果对比。",
                ),
                io.Int.Output(
                    "width",
                    display_name="成品宽",
                    tooltip="成品宽度（像素）。",
                ),
                io.Int.Output(
                    "height",
                    display_name="成品高",
                    tooltip="成品高度（像素）。",
                ),
                io.String.Output(
                    "report",
                    display_name="报告",
                    tooltip="这一两句话说明本次对这张图做了什么。",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        image,
        megapixels,
        upscale_model=None,
        tile_megapixels=2.0,
        overlap=128,
        multiple=32,
        max_growth=8.0,
    ):
        source = _rgb(image, "MK-图像分块")
        height, width = int(source.shape[1]), int(source.shape[2])
        plan = plan_tiles(
            width, height, megapixels, tile_megapixels, overlap, multiple, max_growth
        )
        redraw_width, redraw_height = plan["redraw"]
        result_width, result_height = plan["result"]

        enlarged = source
        # 重绘尺寸只比原图大不到一个网格步长时，不值得再走一趟模型
        if upscale_model is not None and redraw_width * redraw_height > width * height * 1.05:
            enlarged = _model_enlarge(upscale_model, source, redraw_width, redraw_height)
        base = resample_batch(enlarged, redraw_width, redraw_height, "lanczos")
        before = resample_batch(source, result_width, result_height, "lanczos")
        tiles = [
            base[:, top:bottom, left:right, :].contiguous()
            for left, top, right, bottom in plan["boxes"]
        ]
        stitcher = {"kind": STITCHER_KIND, "version": 1, "plan": plan, "tiles": tiles}
        report = describe_plan(plan)
        return io.NodeOutput(tiles, stitcher, before, result_width, result_height, report)


class MKTiledUpscaleStitch(io.ComfyNode):
    """把重绘后的分块拼回整图，接缝做羽化并缩放到成品尺寸。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_TiledUpscaleStitch",
            display_name="MK-分块合并",
            category="MK节点",
            description=(
                "模型重绘完分块后，由它拼回整图：接缝处羽化混合，再缩放到你要的成品尺寸。"
                "「保色」会先把每块对齐到原图同一块的颜色，让各块之间颜色一致，整图保留原本的色调。"
            ),
            search_aliases=[
                "tiled upscale stitch",
                "分块合并",
                "拼接分块",
                "合并分块",
                "缝合",
            ],
            is_input_list=True,
            inputs=[
                io.Image.Input(
                    "tiles",
                    display_name="分块",
                    tooltip=(
                        "重绘后的分块，顺序要和「MK-图像分块」输出的一致。"
                        "回来的块尺寸变了也没关系，会被适配到对应位置。"
                    ),
                ),
                TileStitcher.Input(
                    "stitcher",
                    display_name="分块信息",
                    tooltip="「MK-图像分块」输出的分块信息。",
                ),
                io.Float.Input(
                    "keep_colors",
                    display_name="保色",
                    default=1.0,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    optional=True,
                    tooltip=(
                        "1 表示保留原图颜色：每块对齐到原图同一块。"
                        "调低可以让模型自己的配色透出来；0 为关闭。"
                    ),
                ),
            ],
            outputs=[
                io.Image.Output(
                    "image",
                    display_name="图像",
                    tooltip=(
                        "成品图，尺寸就是你要的尺寸。输入是多张图（列表）时，"
                        "输出同样是一组图，每张对应一张成品。"
                    ),
                    is_output_list=True,
                ),
            ],
        )

    @classmethod
    def execute(cls, tiles, stitcher, keep_colors=None):
        # 输入是列表：一张图对应一组分块 + 一个 stitcher，多张图时依次排开
        stitchers = list(stitcher) if isinstance(stitcher, (list, tuple)) else [stitcher]
        if not stitchers or any(
            not isinstance(item, dict) or item.get("kind") != STITCHER_KIND for item in stitchers
        ):
            raise ValueError("「MK-分块合并」需要「MK-图像分块」输出的分块信息。")
        strength = keep_colors[0] if isinstance(keep_colors, (list, tuple)) and keep_colors else keep_colors
        strength = 1.0 if strength is None else max(0.0, min(1.0, float(strength)))
        counts = [len(item["plan"]["boxes"]) for item in stitchers]
        expected = sum(counts)

        redrawn = [_rgb(tile, "MK-分块合并") for tile in (tiles if isinstance(tiles, (list, tuple)) else [tiles])]
        if len(redrawn) == 1 and expected > 1 and redrawn[0].shape[0] % expected == 0:
            # 分块是被打包成一个批次回来的，按当初的切法拆开
            per_tile = redrawn[0].shape[0] // expected
            redrawn = list(redrawn[0].split(per_tile, dim=0))
        if len(redrawn) != expected:
            has = f"{len(stitchers)} 个分块信息共" if len(stitchers) > 1 else "分块信息里"
            raise ValueError(
                f"「MK-分块合并」收到 {len(redrawn)} 个分块，而{has} {expected} 个。"
                "请把「MK-图像分块」的每个分块按顺序走完同一串节点再送进来。"
            )

        pictures = []
        start = 0
        for item, count in zip(stitchers, counts):
            pictures.append(_join(redrawn[start : start + count], item, strength))
            start += count
        return io.NodeOutput(pictures)


def _join(redrawn: list[torch.Tensor], stitcher: dict, strength: float) -> torch.Tensor:
    """把一张图的各块拼回整图，接缝处羽化。"""
    plan = stitcher["plan"]
    boxes = plan["boxes"]
    sources = stitcher["tiles"]
    redraw_width, redraw_height = plan["redraw"]
    result_width, result_height = plan["result"]
    tile_width, tile_height = plan["tile"]
    lefts = sorted({box[0] for box in boxes})
    tops = sorted({box[1] for box in boxes})
    batch = max(tile.shape[0] for tile in redrawn)
    total = torch.zeros((batch, redraw_height, redraw_width, 3), dtype=torch.float32)
    weight = torch.zeros((redraw_height, redraw_width), dtype=torch.float32)

    for tile, source, (left, top, right, bottom) in zip(redrawn, sources, boxes):
        tile = resample_batch(tile.cpu(), tile_width, tile_height, "lanczos")
        if strength > 0.0:
            reference = source.cpu()
            if reference.shape[0] not in (1, tile.shape[0]):
                reference = reference[:1]
            tile = _keep_colors(tile, reference, strength)
        share_left, share_right = _shared(lefts, tile_width, left)
        share_top, share_bottom = _shared(tops, tile_height, top)
        mask = _ramp(tile_height, share_top, share_bottom)[:, None] * _ramp(tile_width, share_left, share_right)[None, :]
        total[:, top:bottom, left:right, :] += tile * mask[None, :, :, None]
        weight[top:bottom, left:right] += mask

    merged = total / weight.clamp_min(1e-6)[None, :, :, None]
    return resample_batch(merged.clamp_(0.0, 1.0), result_width, result_height, "lanczos")


__all__ = ["MKTiledUpscale", "MKTiledUpscaleStitch", "STITCHER_TYPE", "STITCHER_KIND"]
