"""杂项：日志出口与原子写盘。"""

import uuid
from pathlib import Path


def log(msg: str) -> None:
    """全插件唯一的日志出口。

    flush=True 是必须的：ComfyUI 的 stdout 常被启动器接管或重定向到文件，
    默认按 8KB 块缓冲 —— 启动时的提示不 flush 等于没写。
    """
    print(msg, flush=True)


def _tmp_beside(path: Path) -> Path:
    return path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """先写同目录临时文件再 replace：并发读到的永远是完整文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_beside(path)
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_beside(path)
    try:
        tmp.write_text(text, encoding=encoding)
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
