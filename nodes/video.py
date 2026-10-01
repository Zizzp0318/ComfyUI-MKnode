"""MK-加载视频 / MK-保存视频

迁移自 ComfyUI 官方 comfy_extras/nodes_video.py 的 LoadVideo 与 SaveVideo。

相对原版的改动：
- 节点 id / 显示名 / 分类改为 MK 系列
- 输入输出补充中文显示名
- 预览控件的尺寸行为由前端 web/video_node_resize.js 修正（见该文件说明）

节点逻辑本身与官方保持一致。
"""

import os
import weakref

import folder_paths
from comfy.cli_args import args
from comfy_api.latest import InputImpl, Types, io, ui


def _codec_input(supported_codecs: list[str], *, optional=False, hidden=False):
    """构造编解码器下拉框，与官方 SaveVideo 的实现一致。"""
    codec_options = []
    if "auto" in supported_codecs:
        codec_options.append(io.DynamicCombo.Option("auto", []))
    if "h264" in supported_codecs:
        codec_options.append(
            io.DynamicCombo.Option(
                "h264",
                [
                    io.DynamicCombo.Input(
                        "encoding",
                        display_name="编码模式",
                        options=[
                            io.DynamicCombo.Option("auto", []),
                            io.DynamicCombo.Option(
                                "re-encode",
                                [
                                    io.Float.Input(
                                        "crf", default=23.0, min=0.0, max=51.0, step=1.0,
                                        display_name="CRF",
                                        tooltip="数值越低画质越高、文件越大。",
                                    ),
                                ],
                            ),
                        ],
                        optional=True,
                        tooltip="自动：保留兼容的 H.264 码流。重新编码：应用自定义编码参数。",
                    ),
                ],
            )
        )
    if "av1" in supported_codecs:
        codec_options.append(
            io.DynamicCombo.Option(
                "av1",
                [
                    io.DynamicCombo.Input(
                        "encoding",
                        display_name="编码模式",
                        options=[
                            io.DynamicCombo.Option("auto", []),
                            io.DynamicCombo.Option(
                                "re-encode",
                                [
                                    io.Float.Input(
                                        "crf", default=30.0, min=0.0, max=63.0, step=1.0,
                                        display_name="CRF",
                                        tooltip="数值越低画质越高、文件越大。",
                                    ),
                                ],
                            ),
                        ],
                        optional=True,
                        tooltip="自动：保留兼容的 AV1 码流。重新编码：应用自定义编码参数。",
                    ),
                ],
            )
        )
    return io.DynamicCombo.Input(
        "codec",
        display_name="编解码器",
        options=codec_options,
        optional=optional,
        tooltip="输出视频的编解码器。自动会保留兼容的源码流。",
        extra_dict={"hidden": True} if hidden else None,
    )


_preview_results: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _preview_input_video(file: str, video=None) -> ui.PreviewVideo:
    """加载类节点直接把 input 目录里的原文件作为预览，不必转码。"""
    name, _ = folder_paths.annotated_filepath(file)
    subfolder, _, filename = name.replace("\\", "/").rpartition("/")
    result = ui.SavedResult(filename, subfolder, io.FolderType.input)
    if video is not None:
        _preview_results[video] = (folder_paths.get_annotated_filepath(file), result)
    return ui.PreviewVideo([result])


class MKLoadVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["video"])
        return io.Schema(
            node_id="MK_LoadVideo",
            display_name="MK-加载视频",
            category="MK节点",
            description="从 ComfyUI 的 input 目录加载视频文件。",
            search_aliases=["load video", "open video", "import video", "加载视频", "视频"],
            has_intermediate_output=True,
            inputs=[
                io.Combo.Input(
                    "file",
                    display_name="视频文件",
                    options=sorted(files),
                    upload=io.UploadType.video,
                ),
            ],
            outputs=[
                io.Video.Output("video", display_name="视频"),
            ],
        )

    @classmethod
    def execute(cls, file) -> io.NodeOutput:
        video_path = folder_paths.get_annotated_filepath(file)
        source = InputImpl.VideoFromFile(video_path)
        return io.NodeOutput(source, ui=_preview_input_video(file, source))

    @classmethod
    def fingerprint_inputs(cls, file):
        # 用修改时间代替哈希，避免大文件重复读取
        return os.path.getmtime(folder_paths.get_annotated_filepath(file))

    @classmethod
    def validate_inputs(cls, file):
        if not folder_paths.exists_annotated_filepath(file):
            return "Invalid video file: {}".format(file)
        return True


class MKSaveVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_SaveVideo",
            display_name="MK-保存视频",
            category="MK节点",
            description="把输入视频保存到 ComfyUI 的输出目录。",
            search_aliases=["save video", "export video", "保存视频", "视频"],
            is_output_node=True,
            inputs=[
                io.Video.Input("video", display_name="视频", tooltip="要保存的视频。"),
                io.String.Input(
                    "filename_prefix",
                    display_name="文件名前缀",
                    default="video/ComfyUI",
                    tooltip="保存文件的前缀。支持 %date:yyyy-MM-dd%、%width%、%height% 等占位符。",
                ),
                io.DynamicCombo.Input(
                    "format",
                    display_name="格式",
                    options=[
                        io.DynamicCombo.Option("auto", [_codec_input(["auto", "h264", "av1"])]),
                        io.DynamicCombo.Option("mp4", [_codec_input(["auto", "h264", "av1"])]),
                        io.DynamicCombo.Option("mkv", [_codec_input(["auto", "h264", "av1"])]),
                        io.DynamicCombo.Option("webm", [_codec_input(["auto", "av1"])]),
                    ],
                    tooltip="输出容器格式。自动：AV1 用 WebM，其余用 MP4。",
                ),
                _codec_input(["auto", "h264", "av1"], optional=True, hidden=True),
            ],
            outputs=[
                io.Video.Output("video", display_name="视频", tooltip="原样透传的输入视频。"),
            ],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
        )

    @classmethod
    def execute(cls, video, filename_prefix, format, codec=None) -> io.NodeOutput:
        if isinstance(format, dict):
            format_name = format["format"]
            codec = format.get("codec") or codec
        else:
            format_name = format
        if codec is None:
            codec = {"codec": "auto"}
        codec_name = codec["codec"]
        if format_name == "auto":
            format_name = "webm" if codec_name == "av1" else "mp4"
        encoding = codec.get("encoding") or {}

        width, height = video.get_dimensions()
        full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix,
            folder_paths.get_output_directory(),
            width,
            height,
        )

        saved_metadata = None
        if not args.disable_metadata:
            metadata = {}
            if cls.hidden.extra_pnginfo is not None:
                metadata.update(cls.hidden.extra_pnginfo)
            if cls.hidden.prompt is not None:
                metadata["prompt"] = cls.hidden.prompt
            if len(metadata) > 0:
                saved_metadata = metadata

        file = f"{filename}_{counter:05}_.{Types.VideoContainer.get_extension(format_name)}"
        video.save_to(
            os.path.join(full_output_folder, file),
            format=Types.VideoContainer(format_name),
            codec=Types.VideoCodec(codec_name),
            metadata=saved_metadata,
            crf=encoding.get("crf"),
        )

        return io.NodeOutput(
            video,
            ui=ui.PreviewVideo([ui.SavedResult(file, subfolder, io.FolderType.output)]),
        )
