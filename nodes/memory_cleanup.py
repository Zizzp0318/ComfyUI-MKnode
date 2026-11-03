"""MK-显存清理（MK_VRAMCleanup）/ MK-内存清理（MK_RAMCleanup）。

两个「透传 + 执行清理」的节点：输入什么原样输出什么，节点本身只做清理副作用。
因此都声明为输出节点，并用 `fingerprint_inputs` 返回时间戳，保证每次排队都会真正执行
一次（否则 ComfyUI 会因为输入没变而跳过）。

迁移自 Comfyui-Memory_Cleanup，改写为 V3（NODE 2.0）接口，并补齐了非 Windows 平台的保护。
"""

from __future__ import annotations

import ctypes
import gc
import platform
import time

import comfy.model_management
import psutil
from comfy_api.latest import io
from server import PromptServer

IS_WINDOWS = platform.system() == "Windows"

# 只有 Windows 才有的内核 API，按需初始化，避免在别的平台 import 就炸
_kernel32 = None
_psapi = None
if IS_WINDOWS:
    try:
        from ctypes import wintypes

        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _psapi = ctypes.WinDLL("psapi", use_last_error=True)

        _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        _kernel32.OpenProcess.restype = wintypes.HANDLE
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32.SetSystemFileCacheSize.argtypes = [ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
        _kernel32.SetSystemFileCacheSize.restype = wintypes.BOOL
        _kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        _kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL
        _psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        _psapi.EmptyWorkingSet.restype = wintypes.BOOL
    except Exception:  # 极少数精简系统上 psapi 不可用，退化为只做 gc
        _kernel32 = None
        _psapi = None

# 打开进程所需的权限：清工作集只需要 PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION
_PROCESS_ACCESS = 0x0100 | 0x0400


def _ram_usage() -> tuple[float, float]:
    """返回（内存占用百分比，可用内存 MB）。"""
    memory = psutil.virtual_memory()
    return memory.percent, memory.available / (1024 * 1024)


def _trim_file_cache() -> None:
    """收缩系统文件缓存（Windows）或归还堆内存（Linux）。"""
    if _kernel32 is not None:
        _kernel32.SetSystemFileCacheSize(ctypes.c_size_t(-1), ctypes.c_size_t(-1), 0)
        return
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def _empty_working_sets() -> None:
    """把其它进程的工作集还给系统；权限不足的进程直接跳过。"""
    if _psapi is None or _kernel32 is None:
        return
    for process in psutil.process_iter(["pid"]):
        handle = None
        try:
            handle = _kernel32.OpenProcess(_PROCESS_ACCESS, False, process.info["pid"])
            if handle:
                _psapi.EmptyWorkingSet(handle)
        except Exception:
            continue
        finally:
            if handle:
                _kernel32.CloseHandle(handle)


def _trim_own_working_set() -> None:
    """收缩本进程（ComfyUI）的工作集，把不用的 DLL / 页还给系统。"""
    if _kernel32 is None:
        return
    _kernel32.SetProcessWorkingSetSize(ctypes.c_void_p(-1), ctypes.c_size_t(-1), ctypes.c_size_t(-1))


class MKVRAMCleanup(io.ComfyNode):
    """卸载模型并清空显存缓存，数据原样透传。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_VRAMCleanup",
            display_name="MK-显存清理",
            category="MK节点",
            description=(
                "卸载已加载的模型并清空显存缓存，输入的数据原样输出，可以插在任意连线中间。"
                "每次排队都会真正执行一次，不会被 ComfyUI 的缓存跳过。"
            ),
            search_aliases=["vram", "显存", "清理显存", "empty cache", "unload model", "memory clean"],
            is_output_node=True,
            inputs=[
                io.Boolean.Input(
                    "offload_model",
                    display_name="卸载模型",
                    default=True,
                    tooltip="卸载当前已加载的所有模型，释放它们占用的显存。",
                ),
                io.Boolean.Input(
                    "offload_cache",
                    display_name="清空缓存",
                    default=True,
                    tooltip="回收 Python 垃圾并清空显存缓存池，同时通知队列释放内存。",
                ),
                io.AnyType.Input(
                    "anything",
                    display_name="输入",
                    optional=True,
                    tooltip="任意类型，原样透传到输出。不接也可以单独执行清理。",
                ),
            ],
            outputs=[
                io.AnyType.Output(
                    "output",
                    display_name="输出",
                    tooltip="与输入相同的数据。",
                ),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        # 时间戳每次都变，保证节点每次排队都执行
        return float(time.time())

    @classmethod
    def execute(cls, offload_model, offload_cache, anything=None):
        if offload_model:
            comfy.model_management.unload_all_models()

        if offload_cache:
            gc.collect()
            comfy.model_management.soft_empty_cache()
            try:
                PromptServer.instance.prompt_queue.set_flag("free_memory", True)
            except Exception:
                pass

        print(f"[MK-显存清理] 完成（卸载模型: {offload_model}, 清空缓存: {offload_cache}）")
        return io.NodeOutput(anything)


class MKRAMCleanup(io.ComfyNode):
    """清理系统内存：文件缓存、各进程工作集、本进程未使用的 DLL。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_RAMCleanup",
            display_name="MK-内存清理",
            category="MK节点",
            description=(
                "回收系统内存：收缩文件缓存、清空各进程工作集、归还本进程未使用的 DLL。"
                "输入的数据原样输出，可插在任意连线中间。每次排队都会真正执行一次。"
                "非 Windows 平台只做能做的部分（Linux 下归还堆内存）。"
            ),
            search_aliases=["ram", "内存", "清理内存", "memory clean", "working set"],
            is_output_node=True,
            inputs=[
                io.Boolean.Input(
                    "clean_file_cache",
                    display_name="清理文件缓存",
                    default=True,
                    tooltip="收缩系统的文件缓存，把干净页还给可用内存。",
                ),
                io.Boolean.Input(
                    "clean_processes",
                    display_name="清理进程内存",
                    default=True,
                    tooltip="遍历所有进程清空工作集；权限不足的进程会自动跳过。",
                ),
                io.Boolean.Input(
                    "clean_dlls",
                    display_name="清理未使用DLL",
                    default=True,
                    tooltip="收缩 ComfyUI 自身进程的工作集，归还暂时用不到的 DLL 与页面。",
                ),
                io.Int.Input(
                    "retry_times",
                    display_name="重试次数",
                    default=3,
                    min=1,
                    max=10,
                    step=1,
                    tooltip="重复清理的轮数，每轮间隔 1 秒。系统释放内存需要一点时间，多跑几轮效果更好。",
                ),
                io.AnyType.Input(
                    "anything",
                    display_name="输入",
                    optional=True,
                    tooltip="任意类型，原样透传到输出。不接也可以单独执行清理。",
                ),
            ],
            outputs=[
                io.AnyType.Output(
                    "output",
                    display_name="输出",
                    tooltip="与输入相同的数据。",
                ),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float(time.time())

    @classmethod
    def execute(cls, clean_file_cache, clean_processes, clean_dlls, retry_times, anything=None):
        before_percent, before_available = _ram_usage()

        for _ in range(max(1, int(retry_times))):
            if clean_file_cache:
                try:
                    _trim_file_cache()
                except Exception:
                    pass
            if clean_processes:
                _empty_working_sets()
            if clean_dlls:
                try:
                    _trim_own_working_set()
                except Exception:
                    pass
            time.sleep(1)

        after_percent, after_available = _ram_usage()
        freed = after_available - before_available
        print(
            f"[MK-内存清理] 完成（{before_percent:.1f}% → {after_percent:.1f}%，"
            f"可用内存 {freed:+.0f} MB）"
        )
        return io.NodeOutput(anything)


__all__ = ["MKVRAMCleanup", "MKRAMCleanup"]
