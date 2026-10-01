"""MK-视频加载（高级）

迁移自 ComfyUI-AICoser-Tools 的 AICoser_LoadVideoUpload 节点。

相对原版的改动：
- 节点 id / 显示名 / 分类改为 MK 系列，输入输出补中文显示名
- 上传子目录 aicoser_uploads -> mk_video_uploads
- 路由 /aicoser/video_metadata -> /mk_video_metadata（避免与源包冲突）
- 日志前缀改为 [MK_VideoLoadAdvanced]

取帧、缩放、音频提取、元数据逻辑与原版一致。
"""

import hashlib
import os
import re
import shutil
import subprocess

import numpy as np
import torch
from aiohttp import web
from server import PromptServer

import folder_paths
from comfy_api.latest import io

try:
    import cv2
except ImportError:
    cv2 = None


VIDEO_EXTENSIONS = ["webm", "mp4", "mkv", "gif", "mov"]
BIGMAX = 2**31 - 1
MK_UPLOAD_SUBFOLDER = "mk_video_uploads"
ROUTE_VIDEO_METADATA = "/mk_video_metadata"

_LOG = "[MK_VideoLoadAdvanced]"

_FFMPEG_PATH = None


def _empty_audio(sample_rate=44100):
    return {"waveform": torch.zeros((1, 2, 0), dtype=torch.float32), "sample_rate": int(sample_rate)}


def _ffmpeg_path():
    global _FFMPEG_PATH
    if _FFMPEG_PATH is not None:
        return _FFMPEG_PATH
    paths = []
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        imageio_path = get_ffmpeg_exe()
        if imageio_path:
            paths.append(imageio_path)
    except Exception:
        pass
    system_path = shutil.which("ffmpeg")
    if system_path:
        paths.append(system_path)
    if os.path.isfile("ffmpeg"):
        paths.append(os.path.abspath("ffmpeg"))
    if os.path.isfile("ffmpeg.exe"):
        paths.append(os.path.abspath("ffmpeg.exe"))
    _FFMPEG_PATH = paths[0] if paths else ""
    return _FFMPEG_PATH


def _read_video_audio(video_path, start_time=0, duration=0):
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        print(f"{_LOG} 未找到 ffmpeg，跳过音频，video={video_path}")
        return _empty_audio()
    args = [ffmpeg, "-i", video_path]
    if start_time > 0:
        args += ["-ss", str(start_time)]
    if duration > 0:
        args += ["-t", str(duration)]
    try:
        res = subprocess.run(args + ["-f", "f32le", "-"], capture_output=True, check=True)
        stderr = res.stderr.decode("utf-8", errors="ignore")
        match = re.search(r", (\d+) Hz, (\w+), ", stderr)
        sample_rate = int(match.group(1)) if match else 44100
        channel_name = match.group(2) if match else "stereo"
        channels = {"mono": 1, "stereo": 2}.get(channel_name, 2)
        if not res.stdout:
            print(f"{_LOG} 音频为空，video={video_path}, start={start_time}, duration={duration}")
            return _empty_audio(sample_rate)
        audio = torch.frombuffer(bytearray(res.stdout), dtype=torch.float32)
        usable = (audio.numel() // channels) * channels
        if usable <= 0:
            return _empty_audio(sample_rate)
        audio = audio[:usable].reshape((-1, channels)).transpose(0, 1).unsqueeze(0)
        return {"waveform": audio, "sample_rate": sample_rate}
    except Exception as e:
        print(f"{_LOG} 音频提取失败，video={video_path}, start={start_time}, duration={duration}, error={e}")
        return _empty_audio()


def _list_input_videos():
    """递归列出 input 目录下的所有视频文件（相对路径）。"""
    input_dir = folder_paths.get_input_directory()
    files = []
    for root, _, names in os.walk(input_dir):
        for name in names:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in VIDEO_EXTENSIONS:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, input_dir).replace("\\", "/")
            files.append(rel)
    return sorted(files)


def _target_video_size(width, height, custom_width, custom_height):
    """只给一边时按原比例推算另一边。"""
    if custom_width <= 0 and custom_height <= 0:
        return width, height
    if custom_width > 0 and custom_height > 0:
        return int(custom_width), int(custom_height)
    if custom_width > 0:
        return int(custom_width), max(1, int(round(height * (custom_width / width))))
    return max(1, int(round(width * (custom_height / height)))), int(custom_height)


def _read_video_metadata(video_path):
    if cv2 is None:
        raise RuntimeError("MK-视频加载（高级）需要 opencv-python")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"video could not be opened: {video_path}")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        if fps <= 0:
            fps = 24.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = float(frame_count / fps) if frame_count > 0 and fps > 0 else 0.0
        return {
            "fps": fps,
            "frame_count": frame_count,
            "duration": duration,
            "width": width,
            "height": height,
        }
    finally:
        cap.release()


async def mk_video_metadata(request):
    """供前端读取源视频的帧率 / 帧数 / 尺寸，用于预览与信息展示。"""
    video = request.query.get("filename") or request.query.get("video") or ""
    if not video:
        return web.json_response({"error": "filename is required"}, status=400)
    if not folder_paths.exists_annotated_filepath(video):
        return web.json_response({"error": f"Invalid video file: {video}"}, status=404)
    try:
        video_path = folder_paths.get_annotated_filepath(video)
        meta = _read_video_metadata(video_path)
        meta["filename"] = video
        return web.json_response(meta)
    except Exception as e:
        print(f"{_LOG} 读取视频元数据失败，video={video}, error={e}")
        return web.json_response({"error": str(e)}, status=500)


def _register_route():
    """注册元数据路由。

    PromptServer 未初始化时只告警不抛异常——否则整个包导入失败，
    会把其他 MK 节点一起带下线。真实运行环境下 instance 一定存在。
    """
    import logging
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        logging.warning(f"{_LOG} PromptServer 尚未初始化，视频元数据路由未注册")
        return
    instance.routes.get(ROUTE_VIDEO_METADATA)(mk_video_metadata)


_register_route()


def _delete_uploaded_video(video, video_path):
    """删除上传的视频。只允许删 mk_video_uploads 子目录内的文件，避免误删。"""
    input_dir = os.path.abspath(folder_paths.get_input_directory())
    target_path = os.path.abspath(video_path)
    allowed_dir = os.path.abspath(os.path.join(input_dir, MK_UPLOAD_SUBFOLDER))

    try:
        common = os.path.commonpath([allowed_dir, target_path])
    except ValueError:
        print(f"{_LOG} 跳过删除：路径非法 video={video} path={video_path}")
        return False

    if common != allowed_dir:
        print(f"{_LOG} 跳过删除：不在 {MK_UPLOAD_SUBFOLDER} 内 video={video} path={video_path}")
        return False

    if not os.path.isfile(target_path):
        print(f"{_LOG} 跳过删除：文件不存在 video={video} path={video_path}")
        return False

    try:
        os.remove(target_path)
        print(f"{_LOG} 已删除上传的视频 video={video} path={video_path}")
        return True
    except Exception as e:
        print(f"{_LOG} 删除失败 video={video} path={video_path} error={e}")
        return False


def _read_video_frames(video_path, force_rate, custom_width, custom_height,
                       frame_load_cap, skip_first_frames, select_every_nth):
    if cv2 is None:
        raise RuntimeError("MK-视频加载（高级）需要 opencv-python")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"video could not be opened: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    if fps <= 0:
        fps = 24.0

    source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    source_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    source_duration = float(source_frame_count / fps) if source_frame_count > 0 else 0.0

    skip_first_frames = max(0, int(skip_first_frames or 0))
    select_every_nth = max(1, int(select_every_nth or 1))
    frame_load_cap = max(0, int(frame_load_cap or 0))
    force_rate = float(force_rate or 0)

    target_fps = fps if force_rate <= 0 else force_rate
    sample_interval = max(1, int(round(fps / target_fps))) if force_rate > 0 else 1
    effective_step = max(1, sample_interval * select_every_nth)

    if skip_first_frames > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, skip_first_frames)

    frames = []
    evaluated = skip_first_frames
    loaded = 0
    target_width = source_width
    target_height = source_height

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if (evaluated - skip_first_frames) % effective_step != 0:
            evaluated += 1
            continue

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if target_width <= 0 or target_height <= 0:
            target_height, target_width = frame.shape[:2]

        new_width, new_height = _target_video_size(
            target_width, target_height, int(custom_width or 0), int(custom_height or 0)
        )
        if new_width != frame.shape[1] or new_height != frame.shape[0]:
            frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)

        frames.append(frame.astype(np.float32) / 255.0)
        loaded += 1
        evaluated += 1

        if frame_load_cap > 0 and loaded >= frame_load_cap:
            break

    cap.release()

    if not frames:
        raise RuntimeError("No frames generated")

    images = torch.from_numpy(np.stack(frames, axis=0))
    loaded_height = int(images.shape[1])
    loaded_width = int(images.shape[2])
    loaded_fps = fps / effective_step if effective_step > 0 else fps
    audio_start_time = skip_first_frames / fps if fps > 0 else 0
    audio_duration = len(frames) / loaded_fps if frame_load_cap > 0 and loaded_fps > 0 else 0
    audio = _read_video_audio(video_path, audio_start_time, audio_duration)

    video_info = {
        "source_fps": fps,
        "source_frame_count": source_frame_count,
        "source_duration": source_duration,
        "source_width": source_width,
        "source_height": source_height,
        "loaded_fps": loaded_fps,
        "loaded_frame_count": len(frames),
        "loaded_duration": len(frames) / loaded_fps if loaded_fps > 0 else 0,
        "loaded_width": loaded_width,
        "loaded_height": loaded_height,
        "skip_first_frames": skip_first_frames,
        "select_every_nth": select_every_nth,
    }
    return images, len(frames), audio, video_info, video_info


class MKVideoLoadAdvanced(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        files = _list_input_videos()
        if not files:
            files = [""]
        return io.Schema(
            node_id="MK_VideoLoadAdvanced",
            display_name="MK-视频加载（高级）",
            category="MK节点",
            description="从 input 目录加载视频并拆成图像序列，支持抽帧、缩放、裁剪区间与音频提取。",
            search_aliases=["load video", "video frames", "视频加载", "视频"],
            inputs=[
                io.Combo.Input("video", display_name="视频", options=files),
                io.Float.Input(
                    "force_rate", display_name="强制帧率", default=0, min=0, max=240, step=1,
                    tooltip="0 表示保持源帧率；大于 0 时按该帧率抽帧。",
                ),
                io.Int.Input(
                    "custom_width", display_name="自定义宽度", default=0, min=0, max=16384, step=8,
                    tooltip="0 表示保持源宽度。只填一边时另一边按原比例推算。",
                ),
                io.Int.Input(
                    "custom_height", display_name="自定义高度", default=0, min=0, max=16384, step=8,
                    tooltip="0 表示保持源高度。只填一边时另一边按原比例推算。",
                ),
                io.Int.Input(
                    "frame_load_cap", display_name="最大加载帧数", default=0, min=0, max=BIGMAX, step=1,
                    tooltip="0 表示不限制。",
                ),
                io.Int.Input(
                    "skip_first_frames", display_name="跳过开头帧数", default=0, min=0, max=BIGMAX, step=1,
                ),
                io.Int.Input(
                    "select_every_nth", display_name="每 N 帧取 1", default=1, min=1, max=BIGMAX, step=1,
                ),
                io.Float.Input(
                    "preview_fps", display_name="预览帧率", default=24, min=1, max=240, step=1,
                    tooltip="仅影响节点上的预览播放速度，不影响实际输出。",
                ),
                io.Boolean.Input(
                    "delete_after_load", display_name="加载后删除", default=False,
                    label_on="开", label_off="关",
                    tooltip="加载完成后删除该视频。仅对上传到 mk_video_uploads 的文件生效。",
                ),
            ],
            outputs=[
                io.Image.Output("images", display_name="图像"),
                io.Int.Output("frame_count", display_name="帧数"),
                io.Audio.Output("audio", display_name="音频"),
                io.Custom("AICOSER_VIDEOINFO").Output("video_info", display_name="视频信息"),
                io.Custom("VHS_VIDEOINFO").Output("vhs_video_info", display_name="VHS视频信息"),
            ],
        )

    @classmethod
    def execute(cls, video, force_rate, custom_width, custom_height, frame_load_cap,
                skip_first_frames, select_every_nth, preview_fps, delete_after_load=False):
        if not video:
            raise ValueError("video is empty")
        if not folder_paths.exists_annotated_filepath(video):
            raise ValueError(f"Invalid video file: {video}")
        video_path = folder_paths.get_annotated_filepath(video)
        result = _read_video_frames(
            video_path, force_rate, custom_width, custom_height,
            frame_load_cap, skip_first_frames, select_every_nth,
        )
        if delete_after_load:
            _delete_uploaded_video(video, video_path)
        return io.NodeOutput(*result)

    @classmethod
    def fingerprint_inputs(cls, video, **kwargs):
        if not video or not folder_paths.exists_annotated_filepath(video):
            return ""
        video_path = folder_paths.get_annotated_filepath(video)
        m = hashlib.sha256()
        with open(video_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                m.update(chunk)
        for key in ("force_rate", "custom_width", "custom_height", "frame_load_cap",
                    "skip_first_frames", "select_every_nth", "delete_after_load"):
            m.update(str(kwargs.get(key, "")).encode("utf-8"))
        return m.digest().hex()

    @classmethod
    def validate_inputs(cls, video, **kwargs):
        if not video:
            return "video is empty"
        if not folder_paths.exists_annotated_filepath(video):
            return f"Invalid video file: {video}"
        return True
