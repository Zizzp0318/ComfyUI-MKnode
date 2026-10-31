"""mkg —— MK 图库的 Python 侧。

分层（只允许上层调下层，不要反向 import）：

    constants   常量           无依赖
    paths       目录布局        constants
    images      图片处理        constants
    store       数据读写        paths / images
    library     对外查询        store / paths

节点和路由都只用 library / store，前端只认 HTTP 路由。
"""

from .errors import GalleryMissing  # noqa: F401

__all__ = ["GalleryMissing"]
