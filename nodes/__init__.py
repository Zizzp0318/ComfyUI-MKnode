"""MK 节点汇总。

新增节点时：
1. 在 nodes/ 下新建模块（如 nodes/my_node.py）
2. 从模块导入节点类
3. 把节点类加进 NODE_CLASSES
"""

from .image_crop import MKImageCrop
from .image_selector import MKImageSelector
from .load_image import MKLoadImage
from .prompt_concat import MKPromptConcat
from .prompt_library import MKPromptLibrary
from .prompt_preset import MKPromptPreset
from .save_image import MKSaveImage

NODE_CLASSES = [
    MKLoadImage,
    MKImageSelector,
    MKPromptConcat,
    MKPromptPreset,
    MKPromptLibrary,
    MKImageCrop,
    MKSaveImage,
]

__all__ = [
    "NODE_CLASSES",
    "MKLoadImage",
    "MKImageSelector",
    "MKPromptConcat",
    "MKPromptPreset",
    "MKPromptLibrary",
    "MKImageCrop",
    "MKSaveImage",
]
