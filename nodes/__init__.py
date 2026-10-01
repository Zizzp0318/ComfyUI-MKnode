"""MK 节点汇总。

新增节点时：
1. 在 nodes/ 下新建模块（如 nodes/my_node.py）
2. 从模块导入节点类
3. 把节点类加进 NODE_CLASSES
"""

from .image_selector import MKImageSelector
from .load_image import MKLoadImage
from .save_image import MKSaveImage
from .video import MKLoadVideo, MKSaveVideo
from .video_load_advanced import MKVideoLoadAdvanced

NODE_CLASSES = [
    MKLoadImage,
    MKImageSelector,
    MKSaveImage,
    MKLoadVideo,
    MKSaveVideo,
    MKVideoLoadAdvanced,
]

__all__ = [
    "NODE_CLASSES",
    "MKLoadImage",
    "MKImageSelector",
    "MKSaveImage",
    "MKLoadVideo",
    "MKSaveVideo",
    "MKVideoLoadAdvanced",
]
