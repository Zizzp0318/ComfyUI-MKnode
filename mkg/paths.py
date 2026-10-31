"""目录布局。全插件只有这里拼路径。

用户素材一律放 ComfyUI 的 user 目录下，**不在插件目录里**：

    <ComfyUI>/user/Comfyui_MKnode/mk_gallery/
        pose/   garment/   face/        三个库各一份，结构相同
            library.json    图库数据（名称 / 分类 / 文件对应关系）
            img/            原图（导入时统一转成 WebP）
            thumbs/         缩略图，可随手删，会按需重生成

这样插件目录只剩代码（几百 KB），升级 / 重装 / 换版本都不会碰用户数据。
换盘或集中管理：设环境变量 MK_GALLERY_DATA_DIR。
"""

import os
from pathlib import Path
from typing import Optional

from .constants import LIBS

NODE_DIR = Path(__file__).resolve().parents[1]
LIB_SUBDIR = {"pose": "pose", "garment": "garment", "face": "face"}

_root_cache: Optional[Path] = None


def _comfy_user_root() -> Optional[Path]:
    """ComfyUI 的 user 目录。新版有 folder_paths.get_user_directory()。"""
    try:
        import folder_paths
    except Exception:
        return None
    getter = getattr(folder_paths, "get_user_directory", None)
    if getter is None:
        return None
    try:
        return Path(getter())
    except Exception:
        return None


def _comfy_root_by_tree() -> Optional[Path]:
    """顺着插件目录往上找 ComfyUI 根（同层有 main.py 和 custom_nodes/）。

    比写死 parents[1] 结实：管理器可能把插件装在 custom_nodes/<作者>/<插件>/ 下。
    """
    for parent in list(NODE_DIR.parents)[:5]:
        if (parent / "main.py").is_file() and (parent / "custom_nodes").is_dir():
            return parent
    return None


def user_root() -> Path:
    """用户素材根目录，进程内只解析一次。"""
    global _root_cache
    if _root_cache is not None:
        return _root_cache

    env = (os.environ.get("MK_GALLERY_DATA_DIR") or "").strip()
    if env:
        custom = Path(env).expanduser()
        _root_cache = custom if custom.is_absolute() else (NODE_DIR / custom).resolve()
        return _root_cache

    user = _comfy_user_root()
    if user is None:
        comfy = _comfy_root_by_tree()
        user = (comfy / "user") if comfy is not None else None
    # 兜底：都找不到就放插件里（.gitignore 忽略）。正常安装不会走到这里。
    _root_cache = (user / "Comfyui_MKnode" / "mk_gallery") if user is not None else (NODE_DIR / "userdata")
    return _root_cache


def lib_dir(lib: str = "pose") -> Path:
    return user_root() / LIB_SUBDIR[lib]


def img_dir(lib: str = "pose") -> Path:
    return lib_dir(lib) / "img"


def thumb_dir(lib: str = "pose") -> Path:
    return lib_dir(lib) / "thumbs"


def index_file(lib: str = "pose") -> Path:
    return lib_dir(lib) / "library.json"


def ensure_dirs(lib: str = "pose") -> None:
    img_dir(lib).mkdir(parents=True, exist_ok=True)
    thumb_dir(lib).mkdir(parents=True, exist_ok=True)


def describe(path: Path) -> str:
    """报错信息里给人看的路径：插件内显示相对路径，插件外显示绝对路径。"""
    try:
        return path.resolve().relative_to(NODE_DIR).as_posix() + "/"
    except ValueError:
        return str(path)


def all_dirs() -> list:
    return [lib_dir(lib) for lib in LIBS]
