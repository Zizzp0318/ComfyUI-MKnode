"""MK-MiniMax H3素材加载 · 上传与预览端点（``/mk_h3/*``）

节点的 DOM 面板（``web/h3_media_loader.js``）不直接读本地文件，所有素材都经由这里：

    POST /mk_h3/upload_asset        multipart: file + kind(image|video|audio)
                                    -> {"ok":true,"path":"MKnode/h3/image/x.png",...}
    GET  /mk_h3/asset_preview?path  图片缩略图（长边 256，JPEG）
    GET  /mk_h3/audio_preview?path  音频本体（支持 Range，供 <audio> 试听/拖动）
    GET  /mk_h3/audio_waveform?path 音频波形峰值（服务端解码，任意格式都能画）
    GET  /mk_h3/video_preview?path  视频本体（支持 Range，供 <video> 播放/拖动）
    GET  /mk_h3/asset_video_thumb?path  视频首帧缩略图（JPEG，长边 512）

素材统一存进 ``<ComfyUI>/input/MKnode/h3/<kind>/``，返回的是 input 相对路径
（``MKnode/h3/image/xxx.png``），和官方「加载图像」同一套路：工作流自带路径、
换机器只要素材跟着 input 走就能用。

路径解析兼容三种写法：绝对路径、input/output 相对路径，以及旧 JZL 插件留下的
``jzl/image/xxx.png``（那份工作流直接搬过来也能读）。
"""

import asyncio
import io
import logging
import os

from aiohttp import web

try:
    from server import PromptServer
except ImportError:          # 脱离 ComfyUI 单独导入时不注册路由
    PromptServer = None

# 上传落点：input/MKnode/h3/<kind>/
SUBDIR = ("MKnode", "h3")
KINDS = ("image", "video", "audio")

EXT_ALLOW = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"},
    "video": {".mp4", ".mov", ".webm", ".avi", ".mkv"},
    "audio": {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"},
}

THUMB_IMAGE_EDGE = 256
THUMB_VIDEO_EDGE = 512
PREVIEW_QUALITY = 80
VIDEO_THUMB_QUALITY = 82

_EXT_OF = {ext: kind for kind, exts in EXT_ALLOW.items() for ext in exts}


# ───────────────────────── 基础 ─────────────────────────

def _err(msg: str, status: int = 400):
    return web.json_response({"ok": False, "error": msg}, status=status)


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return _EXT_OF.get(ext, "")


def resolve_media_path(path: str) -> str:
    """素材路径 → 服务器绝对路径；找不到返回空串。"""
    p = (path or "").strip()
    if not p:
        return ""
    if os.path.isfile(p):
        return p
    try:
        import folder_paths
        in_dir = folder_paths.get_input_directory()
        out_dir = folder_paths.get_output_directory()
    except Exception:
        return ""
    for cand in (
        os.path.join(in_dir, p),
        os.path.join(out_dir, p),
        os.path.join(in_dir, "jzl", p),            # 旧 JZL 插件的相对路径
        os.path.join(in_dir, *SUBDIR, p),
    ):
        if os.path.isfile(cand):
            return cand
    return ""


# ───────────────────────── 上传 ─────────────────────────

def _clean_upload_name(raw) -> str:
    """multipart 里的 filename → 安全文件名。

    aiohttp 按 latin-1 解 Content-Disposition，而浏览器发的是 UTF-8 原始字节，
    中文/日文文件名会变成乱码 —— 这里还原一次。只保留最后一段，防目录穿越。
    """
    name = str(raw or "").strip()
    if not name:
        return ""
    try:
        name = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return os.path.basename(name.replace("\\", "/"))


async def post_upload(request):
    """浏览器选文件 → 存进 input/MKnode/h3/<kind>/，返回 input 相对路径。"""
    try:
        post = await request.post()
        file = post.get("file")
        kind = (post.get("kind") or "image").strip()
        if kind not in KINDS:
            kind = "image"
        if not file or not getattr(file, "file", None):
            return _err("未收到文件")
        filename = _clean_upload_name(file.filename)
        if not filename:
            return _err("文件名为空")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in EXT_ALLOW[kind]:
            return _err(f"{kind} 类型不支持扩展名 {ext}")

        import folder_paths
        sub = os.path.join(*SUBDIR, kind)
        out_dir = os.path.join(folder_paths.get_input_directory(), sub)
        os.makedirs(out_dir, exist_ok=True)

        # 重名自动加 (N)，与官方 /upload/image 一致
        stem, suffix = os.path.splitext(filename)
        dest = os.path.join(out_dir, filename)
        i = 1
        while os.path.exists(dest):
            filename = f"{stem} ({i}){suffix}"
            dest = os.path.join(out_dir, filename)
            i += 1
        with open(dest, "wb") as f:
            f.write(file.file.read())

        rel = os.path.join(sub, filename).replace("\\", "/")
        return web.json_response({
            "ok": True,
            "path": rel,
            "name": filename,
            "subfolder": sub.replace("\\", "/"),
            "type": "input",
        })
    except Exception as exc:
        logging.exception("[MK-素材加载] 上传失败")
        return _err(f"上传失败：{exc}", 500)


# ───────────────────────── 预览 ─────────────────────────

async def get_asset_preview(request):
    """图片缩略图：长边 256 的 JPEG（面板九宫格用）。"""
    path = (request.query.get("path") or "").strip()
    if not path:
        return _err("缺少 path")
    if kind_of(path) != "image":
        return _err("仅支持图片预览")
    full = resolve_media_path(path)
    if not full:
        return _err("文件不存在", 404)
    try:
        from PIL import Image, ImageOps
        img = Image.open(full)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((THUMB_IMAGE_EDGE, THUMB_IMAGE_EDGE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=PREVIEW_QUALITY)
        return web.Response(body=buf.getvalue(), content_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=300"})
    except Exception as exc:
        logging.exception("[MK-素材加载] 图片预览失败")
        return _err(f"预览失败：{exc}", 500)


async def get_audio_preview(request):
    """音频本体（FileResponse 自带 Range 支持，<audio> 才能拖动进度）。"""
    path = (request.query.get("path") or "").strip()
    if not path:
        return _err("缺少 path")
    if kind_of(path) != "audio":
        return _err("仅支持音频预览")
    full = resolve_media_path(path)
    if not full:
        return _err("文件不存在", 404)
    try:
        return web.FileResponse(full)
    except Exception as exc:
        logging.exception("[MK-素材加载] 音频读取失败")
        return _err(f"音频读取失败：{exc}", 500)


async def get_video_preview(request):
    """视频本体（Range 支持，<video> 可播放/拖动）。"""
    path = (request.query.get("path") or "").strip()
    if not path:
        return _err("缺少 path")
    if kind_of(path) != "video":
        return _err("仅支持视频预览")
    full = resolve_media_path(path)
    if not full:
        return _err("文件不存在", 404)
    try:
        return web.FileResponse(full)
    except Exception as exc:
        logging.exception("[MK-素材加载] 视频读取失败")
        return _err(f"视频读取失败：{exc}", 500)


# ───────────────────────── 音频波形（给裁剪面板画图用） ─────────────────────────

WAVE_BUCKETS_DEFAULT = 600
WAVE_BUCKETS_MIN = 100
WAVE_BUCKETS_MAX = 2000
_WAVE_CACHE = {}            # (path, mtime_ns, size, buckets) -> 响应字典
_WAVE_CACHE_MAX = 12


def _wave_bins_soundfile(full):
    """soundfile 路径：分块读（不整段进内存）→ [(min,max), ...]"""
    import numpy as np
    import soundfile as sf
    bins = []
    with sf.SoundFile(full) as f:
        sr = int(f.samplerate)
        total = len(f)
        step = max(1, int(sr * 0.05))          # 50ms 一桶，够画波形了
        for block in f.blocks(blocksize=step, dtype="float32", always_2d=True):
            mono = block.max(axis=1)
            bins.append((float(np.min(mono)), float(np.max(mono))))
    return bins, sr, total


def _wave_bins_pyav(full):
    """PyAV 路径（mp3 / m4a / aac / opus / wma 等）：逐帧解码后累积 min/max。"""
    import av
    import numpy as np
    bins = []
    sr = 0
    total = 0
    with av.open(full) as container:
        if not container.streams.audio:
            raise RuntimeError("没有音频流")
        stream = container.streams.audio[0]
        sr = int(stream.codec_context.sample_rate or 44100)
        for frame in container.decode(stream):
            arr = frame.to_ndarray()
            if arr.ndim > 1:
                # [C, n] 取通道极值；[n, C] 也兼容
                axis = 0 if arr.shape[0] <= 8 else 1
                mono = arr.max(axis=axis)
            else:
                mono = arr
            mono = mono.astype(np.float32, copy=False)
            bins.append((float(np.min(mono)), float(np.max(mono))))
            total += int(frame.samples or 0)
    return bins, sr, total


def _resample_bins(bins, buckets):
    """把任意长度的 (min,max) 序列重采样成固定 buckets → 扁平 [min0,max0,min1,max1,...]"""
    n = len(bins)
    if n == 0:
        return [0.0] * (buckets * 2)
    out = []
    for i in range(buckets):
        a = int(i * n / buckets)
        b = max(a + 1, int((i + 1) * n / buckets))
        seg = bins[a:min(b, n)] or [bins[min(a, n - 1)]]
        out.append(min(p[0] for p in seg))
        out.append(max(p[1] for p in seg))
    return out


def decode_waveform(full, buckets):
    """→ (duration_sec, sample_rate, peaks)；同步函数，调用方丢到线程池。"""
    bins, sr, total = [], 0, 0
    try:
        bins, sr, total = _wave_bins_soundfile(full)
    except Exception:
        bins, sr, total = _wave_bins_pyav(full)
    if not bins or sr <= 0:
        raise RuntimeError("没有解出音频数据")
    duration = (total / float(sr)) if total > 0 else 0.0
    if duration <= 0:
        duration = len(bins) * 0.05        # 兜底：按 50ms/桶估
    return duration, sr, _resample_bins(bins, buckets)


async def get_audio_waveform(request):
    """音频波形峰值：返回固定桶数的 [min,max]，前端拿它画波形 + 选区。

    服务端解码（soundfile 优先，退 PyAV），所以 m4a / opus / wma 这些浏览器不一定
    支持的格式也能画出来。
    """
    path = (request.query.get("path") or "").strip()
    if not path:
        return _err("缺少 path")
    if kind_of(path) != "audio":
        return _err("仅支持音频")
    full = resolve_media_path(path)
    if not full:
        return _err("文件不存在", 404)
    try:
        buckets = int(request.query.get("buckets", WAVE_BUCKETS_DEFAULT))
    except (TypeError, ValueError):
        buckets = WAVE_BUCKETS_DEFAULT
    buckets = max(WAVE_BUCKETS_MIN, min(WAVE_BUCKETS_MAX, buckets))

    try:
        st = os.stat(full)
        key = (full, int(st.st_mtime_ns), st.st_size, buckets)
    except OSError:
        return _err("文件不存在", 404)
    cached = _WAVE_CACHE.get(key)
    if cached is not None:
        return web.json_response(cached, headers={"Cache-Control": "no-cache"})

    try:
        duration, sr, peaks = await asyncio.to_thread(decode_waveform, full, buckets)
    except Exception as exc:
        logging.exception("[MK-素材加载] 波形解码失败")
        return _err(f"波形解码失败：{exc}", 500)

    body = {
        "ok": True,
        "duration": round(float(duration), 4),
        "sample_rate": int(sr),
        "buckets": buckets,
        "peaks": [round(float(v), 5) for v in peaks],
    }
    if len(_WAVE_CACHE) >= _WAVE_CACHE_MAX:
        _WAVE_CACHE.clear()               # 简单粗暴：满了全清，反正重算也就几百毫秒
    _WAVE_CACHE[key] = body
    return web.json_response(body, headers={"Cache-Control": "no-cache"})


async def get_asset_video_thumb(request):
    """视频首帧缩略图：浏览器解不了 HEVC/H.265 时用它兜底，预览窗不会空白。

    PyAV 解码（ComfyUI 自带），不依赖系统 ffmpeg。
    """
    path = (request.query.get("path") or "").strip()
    if not path:
        return _err("缺少 path")
    if kind_of(path) != "video":
        return _err("仅支持视频预览")
    full = resolve_media_path(path)
    if not full:
        return _err("文件不存在", 404)
    try:
        import av
        from PIL import Image
        img = None
        with av.open(full) as container:
            if not container.streams.video:
                return _err("没有视频流", 404)
            stream = container.streams.video[0]
            for frame in container.decode(stream):
                img = Image.fromarray(frame.reformat(format="rgb24").to_ndarray())
                break
        if img is None:
            return _err("抽帧失败", 500)
        img.thumbnail((THUMB_VIDEO_EDGE, THUMB_VIDEO_EDGE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=VIDEO_THUMB_QUALITY)
        return web.Response(body=buf.getvalue(), content_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=300"})
    except Exception as exc:
        logging.exception("[MK-素材加载] 视频首帧抽取失败")
        return _err(f"缩略图失败：{exc}", 500)


# ───────────────────────── 注册 ─────────────────────────

def _register(method: str, path: str, handler) -> None:
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        logging.warning("[MK] PromptServer 尚未初始化，素材加载的存储/预览路由未注册")
        return
    getattr(instance.routes, method)(path)(handler)


for _method, _path, _handler in (
    ("post", "/mk_h3/upload_asset", post_upload),
    ("get", "/mk_h3/asset_preview", get_asset_preview),
    ("get", "/mk_h3/audio_preview", get_audio_preview),
    ("get", "/mk_h3/audio_waveform", get_audio_waveform),
    ("get", "/mk_h3/video_preview", get_video_preview),
    ("get", "/mk_h3/asset_video_thumb", get_asset_video_thumb),
):
    _register(_method, _path, _handler)
