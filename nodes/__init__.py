"""MK 节点汇总。

新增节点时：
1. 在 nodes/ 下新建模块（如 nodes/my_node.py）
2. 从模块导入节点类
3. 把节点类加进 NODE_CLASSES
"""

from .adaptive_megapixels import MKAdaptiveMegapixels
from .any_switch import MKAnySwitch
from .fast_groups import MKFastGroupsBypasser, MKFastGroupsMuter
from .image_compare import MKImageCompare
from .image_crop import MKImageCrop
from .image_selector import MKImageSelector
from .load_image import MKLoadImage
from .lora_loader import MKLoraLoaderModelOnly
from .prompt_concat import MKPromptConcat
from .prompt_library import MKPromptLibrary
from .prompt_preset import MKPromptPreset
from .save_image import MKSaveImage

NODE_CLASSES = [
    MKLoadImage,
    MKImageSelector,
    MKImageCompare,
    MKAnySwitch,
    MKFastGroupsMuter,
    MKFastGroupsBypasser,
    MKPromptConcat,
    MKPromptPreset,
    MKPromptLibrary,
    MKImageCrop,
    MKAdaptiveMegapixels,
    MKLoraLoaderModelOnly,
    MKSaveImage,
]

__all__ = [
    "NODE_CLASSES",
    "MKLoadImage",
    "MKImageSelector",
    "MKImageCompare",
    "MKAnySwitch",
    "MKFastGroupsMuter",
    "MKFastGroupsBypasser",
    "MKPromptConcat",
    "MKPromptPreset",
    "MKPromptLibrary",
    "MKImageCrop",
    "MKAdaptiveMegapixels",
    "MKLoraLoaderModelOnly",
    "MKSaveImage",
]
