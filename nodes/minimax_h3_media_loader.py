"""MK-多媒体素材加载 / MK-多媒体素材解包

把「9 张参考图 + 3 段参考视频 + 3 段参考音频」的装载工作收进一个节点：面板由前端
``web/h3_media_loader.js`` 绘制（九宫格 + 试听/播放 + 每槽位开关与视频/音频参数），
配置统一存进 ``media_settings``（JSON 字符串，随工作流保存），执行时按槽位顺序读盘。

两个节点配对使用，中间只走一根线：

    MK-多媒体素材加载 ──素材总线（MK_REF2VA_BUS）──> MK-多媒体素材解包 ──18 个素材口──> 参考生视频

- 加载：19 个槽位读盘后打包成一条总线（``{ref_image_1: tensor, ...}``），画布上只有一根线；
- 解包：把总线拆回 18 个常驻素材口，口名与本包「MK-Minimax H3多参考生视频」的输入口逐字一致
  （``ref_image_1..9`` / ``ref_video_1..3`` / ``ref_video_audio_1..3`` / ``ref_audio_1..3``），一根线一个口直连。

总线用的是自定义类型 ``MK_REF2VA_BUS``：只能本包这两个节点之间互连，接到别的类型会直接连不上，
不会出现「插错了跑一半才发现」的情况。

迁移自 ComfyUI-JZL-MiniMax-H3 的「📥 MiniMax 素材加载」（``JZL_MiniMaxH3MediaLoader``），
装载逻辑（Exif 旋转、PyAV 抽帧、强制帧率/跳帧/宽高/帧数上限、音轨跟着画面裁、
音频切片、脏数据钳制）逐行保留；总线改成 ``MK_REF2VA_BUS``（与上游的 ``JZL_REF2VA_BUS``
互不干扰，两个插件同装也不会串线）。

参数约定（与前端一致，后端做类型钳制，脏数据不会炸）：
  images[i] = {path, enabled, scale_mode, target_megapixels, scale_method}
  videos[i] = {path, enabled, force_rate, skip, width, height, cap}
  audios[i] = {path, enabled, start, duration}
未启用 / 未上传 / 文件丢失的槽位 → 总线里对应键为 None（等同解包后该口未连线）。

图片槽位只有两种状态：
  scale_mode = off         原图直出（EXIF 旋转 + 转 RGB，不缩放）
  scale_mode = megapixels  缩放到 target_megapixels 百万像素（1 MP = 1024×1024，
                           与官方「缩放图像（像素）」同口径；宽高各自就近对齐到 size_multiple）
  scale_method            缩放方式：nearest-exact / bilinear / area / bicubic / lanczos（默认）
对齐规则与官方一致（round(边长 × scale / 尺寸倍数) × 尺寸倍数），不裁边；
宽高各自对齐，所以比例可能和原图有 1~3% 偏差（尺寸倍数为 1 时不偏差）。
"""

import json
import math
import os

import numpy as np
import torch

try:
    import folder_paths
except Exception:  # 非 ComfyUI 环境（单测）下允许导入
    folder_paths = None

IMAGE_COUNT = 9
AUDIO_COUNT = 3
VIDEO_COUNT = 3

# 抽帧硬上限：防止误填（如 cap=0 且视频极长）时一次性吃光内存
MAX_VIDEO_FRAMES_HARD = 6000

# 输出口顺序 = 本包「MK-Minimax H3多参考生视频」的输入顺序（1 起算）
OUTPUT_KEYS = tuple(
    [f"ref_image_{i}" for i in range(1, IMAGE_COUNT + 1)]
    + [f"ref_video_{i}" for i in range(1, VIDEO_COUNT + 1)]
    + [f"ref_video_audio_{i}" for i in range(1, VIDEO_COUNT + 1)]
    + [f"ref_audio_{i}" for i in range(1, AUDIO_COUNT + 1)]
)
OUTPUT_TYPES = tuple("AUDIO" if "audio" in key else "IMAGE" for key in OUTPUT_KEYS)

# 自定义总线类型：加载端打包、解包端拆开，只能这两头互连（与上游 JZL_REF2VA_BUS 区分）
BUS_TYPE = "MK_REF2VA_BUS"
BUS_NAME = "素材总线"

# ── 图片槽位的缩放选项 ────────────────────────────────────
# 只保留「禁用」与「按总像素」：按最长边 / 尺寸对齐 / 裁剪位置已移除
IMAGE_SCALE_MODES = ("off", "megapixels")

# 缩放方式：与 ComfyUI 官方的 upscale_method 同一套名字（顺序即前端下拉顺序）
SCALE_METHODS = ("nearest-exact", "bilinear", "area", "bicubic", "lanczos")
SCALE_METHOD_DEFAULT = "lanczos"
# 映射到 PIL 的重采样滤镜（area 对应 ComfyUI 的 adaptive_avg_pool2d，用 BOX 最接近）
_PIL_RESAMPLE = {
    "nearest-exact": "NEAREST",
    "bilinear": "BILINEAR",
    "area": "BOX",
    "bicubic": "BICUBIC",
    "lanczos": "LANCZOS",
}

# 缩放上限：单边与总像素各自设死，填得过大时按比例压回来（避免 9 张一起 OOM）
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_PIXELS = 64_000_000

# 1 MP = 1024 × 1024 像素：与官方「缩放图像（像素）」（ImageScaleToTotalPixels）同一口径，
# 这样面板上填的 MP 与官方缩放节点填的 MP 是同一个意思
_PIXELS_PER_MP = 1024 * 1024

# 目标总像素的取值范围（前端输入框同口径）
MP_MIN, MP_MAX, MP_DEFAULT = 0.01, 64.0, 1.0          # 百万像素（MP）


# ── 配置 JSON：解析 / 归一化（前端写什么进来都不能把后端弄崩） ─────────────

def _default_image_slot():
    """图片槽位默认值：不缩放、原图直出。"""
    return {
        "path": "", "enabled": True,
        "scale_mode": "off",              # off / megapixels
        "target_megapixels": MP_DEFAULT,  # 按总像素：目标总像素（MP）
        "scale_method": SCALE_METHOD_DEFAULT,   # 缩放方式（仅在缩放时生效）
        "size_multiple": 1,               # 尺寸倍数：宽高就近对齐到该值的整数倍（1 = 不对齐）
    }


def _default_settings():
    return {
        "version": 1,
        "images": [_default_image_slot() for _ in range(IMAGE_COUNT)],
        "audios": [{"path": "", "enabled": True, "start": 0.0, "duration": 0.0}
                   for _ in range(AUDIO_COUNT)],
        "videos": [{"path": "", "enabled": True, "force_rate": 0.0, "skip": 0,
                    "width": 0, "height": 0, "cap": 0} for _ in range(VIDEO_COUNT)],
    }


def _as_float(value, default=0.0, lo=None, hi=None):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    if lo is not None and f < lo:
        f = lo
    if hi is not None and f > hi:
        f = hi
    return f


def _as_int(value, default=0, lo=None, hi=None):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def _as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("0", "false", "no", "off", "关", "关闭", "禁用"):
        return False
    if text in ("1", "true", "yes", "on", "开", "开启", "启用"):
        return True
    return default


def _as_path(value):
    return str(value or "").strip().replace("\\", "/")


def _pick(value, allowed, default):
    """枚举字段：不在白名单里就用默认值（前端写脏了也不会炸）。"""
    v = str(value or "").strip()
    return v if v in allowed else default


def _slot_list(raw, key, count):
    """取出某一类槽位数组，长度不足补空、超长截断。"""
    items = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(items, list):
        items = []
    out = [it if isinstance(it, dict) else {} for it in items[:count]]
    while len(out) < count:
        out.append({})
    return out


def parse_settings(raw):
    """media_settings（JSON 字符串或 dict）→ 归一化配置。任何异常都退回默认配置。"""
    data = raw
    if isinstance(raw, str):
        text = raw.strip()
        try:
            data = json.loads(text) if text else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    images = [{
        "path": _as_path(it.get("path")),
        "enabled": _as_bool(it.get("enabled"), True),
        "scale_mode": _pick(it.get("scale_mode"), IMAGE_SCALE_MODES, "off"),
        "target_megapixels": _as_float(it.get("target_megapixels"), MP_DEFAULT, MP_MIN, MP_MAX),
        "scale_method": _pick(it.get("scale_method"), SCALE_METHODS, SCALE_METHOD_DEFAULT),
        "size_multiple": _as_int(it.get("size_multiple"), 1, 1, 256),
    } for it in _slot_list(data, "images", IMAGE_COUNT)]

    audios = [{
        "path": _as_path(it.get("path")),
        "enabled": _as_bool(it.get("enabled"), True),
        "start": _as_float(it.get("start"), 0.0, 0.0),
        "duration": _as_float(it.get("duration"), 0.0, 0.0),
    } for it in _slot_list(data, "audios", AUDIO_COUNT)]

    videos = [{
        "path": _as_path(it.get("path")),
        "enabled": _as_bool(it.get("enabled"), True),
        "force_rate": _as_float(it.get("force_rate"), 0.0, 0.0, 240.0),
        "skip": _as_int(it.get("skip"), 0, 0),
        "width": _as_int(it.get("width"), 0, 0),
        "height": _as_int(it.get("height"), 0, 0),
        "cap": _as_int(it.get("cap"), 0, 0),
    } for it in _slot_list(data, "videos", VIDEO_COUNT)]

    return {"version": 1, "images": images, "audios": audios, "videos": videos}


# ── 文件定位 / 加载 ────────────────────────────────────────────────

def resolve_media_path(path):
    """素材路径 → 绝对路径：绝对路径直接用；相对路径按 input/output 目录解析。

    额外认两组前缀：``MKnode/h3/<kind>/...``（本节点上传后写入的相对路径）与
    ``jzl/<kind>/...``（从 JZL 插件搬过来的工作流直接可用）。
    """
    p = (path or "").strip()
    if not p:
        return ""
    p = p.replace("\\", "/")
    if os.path.isfile(p):
        return p
    if folder_paths is None:
        return ""
    try:
        in_dir = folder_paths.get_input_directory()
        out_dir = folder_paths.get_output_directory()
    except Exception:
        return ""
    for cand in (
        os.path.join(in_dir, p),
        os.path.join(out_dir, p),
        os.path.join(in_dir, "jzl", p),
        os.path.join(in_dir, "MKnode", "h3", p),
    ):
        if os.path.isfile(cand):
            return cand
    return ""


# ── 图片槽位：缩放到目标总像素 ──────────────────────────────
#
# 「按总像素」时用官方 ImageScaleToTotalPixels 的公式算目标 (tw, th)：
#   round(边长 × scale / 尺寸倍数) × 尺寸倍数，scale = sqrt(MP × 1024² / 原面积)
# 只缩放、不裁边；宽高各自对齐，比例可能和原图有 1~3% 偏差（尺寸倍数为 1 时无偏差）。

def _clamp_target(nw, nh):
    """单边 / 总像素双重上限，超了按比例压回来。返回 (nw, nh, capped)。"""
    capped = False
    edge = max(nw, nh)
    if edge > MAX_IMAGE_EDGE:
        k = MAX_IMAGE_EDGE / float(edge)
        nw, nh = max(1, int(round(nw * k))), max(1, int(round(nh * k)))
        capped = True
    if nw * nh > MAX_IMAGE_PIXELS:
        k = math.sqrt(MAX_IMAGE_PIXELS / float(nw * nh))
        nw, nh = max(1, int(round(nw * k))), max(1, int(round(nh * k)))
        capped = True
    return nw, nh, capped


def _align_down_to(value, multiple):
    """向下取整到 multiple 的倍数（上限压回后用它保证仍然是倍数）。"""
    if multiple <= 1:
        return max(1, int(value))
    return max(multiple, (int(value) // multiple) * multiple)


def _target_size(w, h, target_mp, multiple=1):
    """按总像素算目标尺寸 → (tw, th, capped)。

    与官方「缩放图像（像素）」（``ImageScaleToTotalPixels``）**逐行一致**：

        total    = target_mp * 1024 * 1024
        scale_by = sqrt(total / (w * h))
        width    = round(w * scale_by / steps) * steps
        height   = round(h * scale_by / steps) * steps

    注意不能用「先 round 到像素、再就近对齐到倍数」的两步写法：那会多出一次中间取整，
    碰到 x.5 的边界就跟官方差一个步长（例：2920x1944 @1MP 步数8，两步写法 840，官方 832）。

    只有结果越过单边/总量上限时才会压回（下游防 OOM），压回后向下对齐到倍数。
    """
    if w <= 0 or h <= 0:
        return max(1, w), max(1, h), False
    target_px = float(target_mp) * _PIXELS_PER_MP
    if target_px <= 0:
        return w, h, False
    steps = max(1, int(multiple))
    scale = math.sqrt(target_px / float(w * h))
    tw = max(steps, int(round(w * scale / steps)) * steps)
    th = max(steps, int(round(h * scale / steps)) * steps)
    tw, th, capped = _clamp_target(tw, th)
    if capped:
        tw = _align_down_to(tw, steps)
        th = _align_down_to(th, steps)
    return tw, th, capped


def _resample_of(method):
    """缩放方式名 → PIL 重采样滤镜（不认识的回落 Lanczos）。"""
    from PIL import Image
    return getattr(Image, _PIL_RESAMPLE.get(method, "LANCZOS"), Image.LANCZOS)


def prepare_image(path, item=None):
    """按槽位设置处理图片：EXIF 旋转 → RGB → 按指定缩放方式缩放到目标总像素。

    返回 (PIL.Image, 提示文本)；提示文本非空表示目标尺寸过大、被上限压过。
    """
    from PIL import Image, ImageOps
    item = item or {}
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)      # EXIF 旋转
    img = img.convert("RGB")
    w0, h0 = img.size
    note = ""
    if item.get("scale_mode", "off") != "megapixels":   # 禁用：原图直出
        return img, note
    tw, th, capped = _target_size(w0, h0, item.get("target_megapixels") or MP_DEFAULT,
                                  item.get("size_multiple") or 1)
    if (tw, th) != (w0, h0):
        img = img.resize((tw, th), _resample_of(item.get("scale_method")))
    if capped:
        note = "目标尺寸过大，已按上限压到 %dx%d（单边 %d / 总量 %dMP）" % (
            tw, th, MAX_IMAGE_EDGE, MAX_IMAGE_PIXELS // _PIXELS_PER_MP)
    return img, note


def pil_to_tensor(img):
    """PIL(RGB) → IMAGE tensor [1, H, W, 3]（0-1）。"""
    arr = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(arr)[None]


def load_image(path):
    """图片 → IMAGE tensor [1, H, W, C]（RGB，0-1）。不套槽位的缩放/裁剪设置。"""
    return pil_to_tensor(prepare_image(path)[0])


def _read_audio_file(path):
    """音频文件 → (waveform [C, L] tensor, sample_rate)。

    soundfile 覆盖 wav/flac/ogg；m4a/aac/mp3 等走 PyAV（ComfyUI 自带解码器）；
    torchaudio 兜底。
    """
    try:
        import soundfile as sf
        data, sample_rate = sf.read(path, dtype="float32")
        if data.ndim == 1:
            data = data[None, :]
        else:
            data = data.T
        return torch.from_numpy(np.ascontiguousarray(data)), int(sample_rate)
    except Exception:
        pass

    try:
        import av
        with av.open(path) as container:
            if not container.streams.audio:
                raise RuntimeError("没有音频流")
            stream = container.streams.audio[0]
            sample_rate = int(stream.codec_context.sample_rate or 44100)
            channels = int(stream.codec_context.channels or 1)
            chunks = [_av_audio_ndarray(frame, channels) for frame in container.decode(stream)]
        chunks = [c for c in chunks if c is not None and c.shape[1] > 0]
        if not chunks:
            raise RuntimeError("没有解出音频帧")
        return torch.from_numpy(np.ascontiguousarray(np.concatenate(chunks, axis=1))), sample_rate
    except Exception:
        pass

    import torchaudio
    waveform, sample_rate = torchaudio.load(path)  # [C, L]
    return waveform, int(sample_rate)


def _av_audio_ndarray(frame, channels):
    """PyAV 音频帧 → [C, L] float32（-1~1）。"""
    arr = frame.to_ndarray()
    if arr.ndim == 1:
        arr = arr[None, :]
    elif arr.shape[0] != channels:
        arr = arr.reshape(-1, channels).T
    if arr.dtype == np.int16:
        arr = arr.astype(np.float32) / 32768.0
    elif arr.dtype == np.int32:
        arr = arr.astype(np.float32) / 2147483648.0
    elif arr.dtype == np.uint8:
        arr = (arr.astype(np.float32) - 128.0) / 128.0
    else:
        arr = arr.astype(np.float32)
    return arr


def _make_audio(waveform, sample_rate):
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    return {"waveform": waveform.unsqueeze(0), "sample_rate": int(sample_rate)}


def load_audio(path, start=0.0, duration=0.0):
    """音频 → AUDIO dict，按 start（秒）/duration（秒，0=到结尾）切片。"""
    waveform, sample_rate = _read_audio_file(path)  # [C, L]
    total = waveform.shape[-1]
    s_idx = 0 if start <= 0 else int(round(start * sample_rate))
    s_idx = max(0, min(s_idx, total))
    if duration and duration > 0:
        e_idx = min(total, s_idx + int(round(duration * sample_rate)))
    else:
        e_idx = total
    if e_idx <= s_idx:
        raise ValueError(f"切片区间为空（开始 {start:g}s / 时长 {duration:g}s，"
                         f"素材总长 {total / max(1, sample_rate):.2f}s）")
    return _make_audio(waveform[:, s_idx:e_idx], sample_rate)


def _video_target_size(sw, sh, width, height):
    """视频输出尺寸：两边都填直接用；只填一边按比例算另一边并偶数对齐；都不填保持原尺寸。"""
    w, h = int(width or 0), int(height or 0)
    if w > 0 and h > 0:
        return w, h
    if w > 0 and sw > 0:
        return w, max(2, int(round(sh * w / float(sw) / 2.0)) * 2)
    if h > 0 and sh > 0:
        return max(2, int(round(sw * h / float(sh) / 2.0)) * 2), h
    return None


def load_video_frames(path, force_rate=0.0, skip=0, width=0, height=0, cap=0):
    """视频 → IMAGE 序列 [T, H, W, C]。

    参数含义与「XB-BOX - 🎬 加载视频」一致：
      force_rate   强制帧率（0 = 保持原帧率）
      skip         跳过前 N 帧（在改帧率之后计数）
      width/height 输出尺寸（0 = 保持原尺寸；只填一边则另一边按比例+偶数对齐）
      cap          帧数上限（0 = 不限制，另有 6000 帧安全上限）
    """
    import av

    rate = float(force_rate or 0)
    step = (1.0 / rate) if rate > 0 else 0.0
    skip = max(0, int(skip or 0))
    limit = int(cap or 0)
    hard_capped = limit <= 0 or limit > MAX_VIDEO_FRAMES_HARD
    if hard_capped:
        limit = MAX_VIDEO_FRAMES_HARD

    frames = []
    with av.open(path) as container:
        if not container.streams.video:
            raise RuntimeError("该文件没有视频流")
        stream = container.streams.video[0]
        try:
            stream.thread_type = "AUTO"
        except Exception:
            pass
        target = _video_target_size(stream.codec_context.width or 0,
                                    stream.codec_context.height or 0, width, height)
        time_base = float(stream.time_base) if stream.time_base else 0.0
        next_t = 0.0
        index = 0          # 改帧率后已见过的帧序号（skip / cap 都按它计数）
        for frame in container.decode(stream):
            if step > 0:
                t = float(frame.pts * time_base) if (frame.pts is not None and time_base) else index / rate
                if t + 1e-6 < next_t:
                    continue
                next_t += step
                while next_t <= t + 1e-6:
                    next_t += step
            if index < skip:
                index += 1
                continue
            if len(frames) >= limit:
                break
            index += 1
            if target:
                frame = frame.reformat(width=target[0], height=target[1],
                                       format="rgb24", interpolation="BILINEAR")
            else:
                frame = frame.reformat(format="rgb24")
            arr = frame.to_ndarray()  # [H, W, 3] uint8
            frames.append(torch.from_numpy(np.ascontiguousarray(arr)).float() / 255.0)

    if not frames:
        raise RuntimeError("视频没有可用帧（检查「跳过帧数 / 帧数上限」）")
    if hard_capped and len(frames) >= limit:
        print("[MK-素材加载] ⚠️ 视频 %s 已达安全上限 %d 帧（未填帧数上限），"
              "如需完整加载请在「视频设置」里调高帧数上限" % (os.path.basename(path), limit))
    fh, fw = frames[0].shape[0], frames[0].shape[1]
    est_gb = len(frames) * fh * fw * 3 * 4 / float(1024 ** 3)
    if est_gb >= 4.0:
        print("[MK-素材加载] ⚠️ 视频 %s：%d 帧 %dx%d 约需 %.1f GB 内存，"
              "建议在「视频设置」里限制帧数上限或输出宽高"
              % (os.path.basename(path), len(frames), fw, fh, est_gb))
    return torch.stack(frames)


def _slice_audio(waveform, sample_rate, start_time=0.0, duration=0.0):
    """按秒切片（start_time/duration，0 = 到头）；区间为空返回 None。"""
    total = waveform.shape[-1]
    s_idx = 0 if start_time <= 0 else int(round(start_time * sample_rate))
    s_idx = max(0, min(s_idx, total))
    if duration and duration > 0:
        e_idx = min(total, s_idx + int(round(duration * sample_rate)))
    else:
        e_idx = total
    if e_idx <= s_idx:
        return None
    return waveform[..., s_idx:e_idx]


def load_video_audio(path, start_time=0.0, duration=0.0):
    """视频内嵌音轨 → AUDIO dict（无音轨返回 None）。

    start_time / duration 与「帧数上限 + 跳过帧数 + 强制帧率」对齐：
    视频只取前 N 帧时，音轨也只取对应那段，避免「画面裁了、声音没裁」。
    """
    try:
        import av
        with av.open(path) as container:
            if not container.streams.audio:
                return None
            stream = container.streams.audio[0]
            sample_rate = int(stream.codec_context.sample_rate or 44100)
            channels = int(stream.codec_context.channels or 1)
            chunks = [_av_audio_ndarray(frame, channels) for frame in container.decode(stream)]
        chunks = [c for c in chunks if c is not None and c.shape[1] > 0]
        if not chunks:
            return None
        waveform = torch.from_numpy(np.ascontiguousarray(np.concatenate(chunks, axis=1)))
        cut = _slice_audio(waveform, sample_rate, start_time=start_time, duration=duration)
        if cut is None or cut.shape[-1] == 0:
            return None
        return _make_audio(cut, sample_rate)
    except Exception:
        return None


def video_effective_rate(path, force_rate=0.0):
    """视频实际输出帧率：填了强制帧率用它，否则用源帧率。读不到时按 24fps 估算。"""
    rate = float(force_rate or 0)
    if rate > 0:
        return rate
    try:
        import av
        with av.open(path) as container:
            if container.streams.video:
                st = container.streams.video[0]
                src = float(st.average_rate) if st.average_rate else 0.0
                if src > 0:
                    return src
    except Exception:
        pass
    return 24.0


# ── 节点 ──────────────────────────────────────────────────────────

class MKMinimaxH3MediaLoader:
    """9 图 + 3 视频（含原声）+ 3 音频 → 18 个常驻输出口，直连参考生视频节点。

    media_settings 由前端 DOM 面板读写（每槽位的素材路径 / 开关 / 视频与音频参数），
    随工作流保存。执行时按槽位顺序装载素材，输出口名与本包
    「MK-Minimax H3多参考生视频」的输入口逐字一致，可直接一根对一根连线。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "media_settings": ("STRING", {
                    "default": json.dumps(_default_settings(), ensure_ascii=False),
                    "multiline": True,
                    "dynamicPrompts": False,
                    "tooltip": "素材配置 JSON（由节点面板自动维护：9 图 / 3 音频 / 3 视频的路径、开关与参数）",
                }),
            },
        }

    RETURN_TYPES = (BUS_TYPE,)
    RETURN_NAMES = (BUS_NAME,)
    FUNCTION = "load"
    CATEGORY = "MK节点"
    # 不是输出节点：总线只要被「MK-多媒体素材解包」接上就会执行，ui 摘要也照常回传；
    # 悬空不接时不会白白读盘抽帧。
    OUTPUT_NODE = False

    @classmethod
    def IS_CHANGED(cls, media_settings="", **kwargs):
        """素材文件被替换（同名覆盖）也必须重跑，否则会用上一次的缓存结果。"""
        cfg = parse_settings(media_settings)
        sig = [media_settings if isinstance(media_settings, str) else json.dumps(cfg, sort_keys=True)]
        for group in ("images", "audios", "videos"):
            for item in cfg[group]:
                p = resolve_media_path(item.get("path"))
                if not p:
                    continue
                try:
                    st = os.stat(p)
                    # 用纳秒级 mtime：同一秒内同名覆盖（脚本写素材）也能触发重跑
                    sig.append("%s|%d|%d" % (p, int(st.st_mtime_ns), st.st_size))
                except Exception:
                    sig.append(p)
        return "mk_h3_media|" + "|".join(sig)

    def load(self, media_settings=""):
        cfg = parse_settings(media_settings)
        bus = {key: None for key in OUTPUT_KEYS}
        report = {"image": [0, 0], "audio": [0, 0], "video": [0, 0]}  # [载入数, 启用数]
        errors = []

        # 9 张参考图 → ref_image_1..9
        for i, item in enumerate(cfg["images"]):
            key = "ref_image_%d" % (i + 1)
            enabled = item["enabled"]
            path = resolve_media_path(item["path"])
            if enabled:
                report["image"][1] += 1
            if not enabled or not path:
                if enabled and item["path"]:
                    errors.append("图片%d：文件不存在（%s）" % (i + 1, item["path"]))
                continue
            try:
                pil, note = prepare_image(path, item)
                bus[key] = pil_to_tensor(pil)
                report["image"][0] += 1
                if note:
                    errors.append("图片%d：%s" % (i + 1, note))
            except Exception as exc:
                errors.append("图片%d：%s" % (i + 1, exc))

        # 3 段参考视频 → ref_video_1..3 + ref_video_audio_1..3
        for i, item in enumerate(cfg["videos"]):
            vkey = "ref_video_%d" % (i + 1)
            enabled = item["enabled"]
            path = resolve_media_path(item["path"])
            if enabled:
                report["video"][1] += 1
            if not enabled or not path:
                if enabled and item["path"]:
                    errors.append("视频%d：文件不存在（%s）" % (i + 1, item["path"]))
                continue
            try:
                bus[vkey] = load_video_frames(
                    path, force_rate=item["force_rate"], skip=item["skip"],
                    width=item["width"], height=item["height"], cap=item["cap"])
                report["video"][0] += 1
            except Exception as exc:
                errors.append("视频%d：%s" % (i + 1, exc))
            # 音轨跟着画面裁：跳过帧数 / 帧数上限 换算成秒，视频裁到哪音轨裁到哪
            # （否则画面只取 5 帧、声音却是整段，下游会以为「帧数上限没生效」）
            try:
                rate = video_effective_rate(path, item["force_rate"])
                a_start = (item["skip"] / rate) if rate > 0 else 0.0
                a_dur = (item["cap"] / rate) if (item["cap"] > 0 and rate > 0) else 0.0
                bus["ref_video_audio_%d" % (i + 1)] = load_video_audio(
                    path, start_time=a_start, duration=a_dur)
            except Exception:
                bus["ref_video_audio_%d" % (i + 1)] = None

        # 3 段独立音频 → ref_audio_1..3
        for i, item in enumerate(cfg["audios"]):
            akey = "ref_audio_%d" % (i + 1)
            enabled = item["enabled"]
            path = resolve_media_path(item["path"])
            if enabled:
                report["audio"][1] += 1
            if not enabled or not path:
                if enabled and item["path"]:
                    errors.append("音频%d：文件不存在（%s）" % (i + 1, item["path"]))
                continue
            try:
                bus[akey] = load_audio(path, start=item["start"], duration=item["duration"])
                report["audio"][0] += 1
            except Exception as exc:
                errors.append("音频%d：%s" % (i + 1, exc))

        summary = "图片 %d/%d 丨 音频 %d/%d 丨 视频 %d/%d" % (
            report["image"][0], report["image"][1],
            report["audio"][0], report["audio"][1],
            report["video"][0], report["video"][1],
        )
        print("[MK-素材加载] %s（数字为 载入/启用）" % summary)
        for err in errors[:10]:
            print("[MK-素材加载] ⚠️ %s" % err)

        info = summary if not errors else summary + " 丨 异常 %d" % len(errors)
        return {"ui": {"media_info": [info], "media_errors": [errors[:10]]},
                "result": (bus,)}


# ── 解包节点 ──────────────────────────────────────────────────────

class MKMinimaxH3MediaUnpack:
    """把「MK-多媒体素材加载」打的总线拆回 18 个素材口。

    输出口名与本包「MK-Minimax H3多参考生视频」的输入口逐字一致，一根线一个口直连。
    总线里为 None 的槽位（未启用 / 未上传 / 文件丢失）解出来同样是 None，等于该口没连线。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bus": (BUS_TYPE, {
                    "force_input": True,
                    "tooltip": "接「MK-多媒体素材加载」的素材总线",
                }),
            },
        }

    RETURN_TYPES = OUTPUT_TYPES
    RETURN_NAMES = OUTPUT_KEYS
    FUNCTION = "unpack"
    CATEGORY = "MK节点"
    OUTPUT_NODE = False

    def unpack(self, bus):
        if not isinstance(bus, dict):
            bus = {}
        return tuple(bus.get(key) for key in OUTPUT_KEYS)
