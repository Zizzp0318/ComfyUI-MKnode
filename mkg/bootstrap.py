"""启动准备：建好用户素材目录，写一份说明，把路径打到控制台。

节点本身不依赖这里 —— 全失败也只是少两行日志。
"""

from . import paths
from .constants import LIBS
from .util import log

_ready = False

README = """MK 图库 · 用户素材目录
=====================

这里存的是你自己加的图片和分类，升级 / 重装插件都不会动它。
换盘或集中管理：设环境变量 MK_GALLERY_DATA_DIR 指向别处。

pose/  garment/  face/     姿态库 / 服装库 / 脸模库，三个库结构一样
  library.json   图库数据：每张图的名称、分类、对应文件名
  img/           图片本体（导入时统一转成 WebP）
  thumbs/        缩略图，删掉会自动重建，不用备份

想批量加图：把图片直接丢进对应库的 img/，然后在节点里点一下页脚的条目数刷新，
新图会以「未分类」加进来。
分类在节点里导入时新建；某个分类的最后一张图被删掉，这个分类也会跟着消失。
"""


def _write_readme() -> None:
    target = paths.user_root() / "说明.txt"
    if target.is_file():
        return
    try:
        target.write_text(README, encoding="utf-8")
    except OSError:
        pass


def ensure_userdata() -> None:
    global _ready
    if _ready:
        return
    _ready = True
    try:
        paths.user_root().mkdir(parents=True, exist_ok=True)
        _write_readme()
        for lib in LIBS:
            paths.ensure_dirs(lib)
    except Exception as err:
        log(f"[MK 图库] 用户素材目录准备失败（不影响使用）：{err}")
        return
    log(f"[MK 图库] 素材目录：{paths.user_root()}")
