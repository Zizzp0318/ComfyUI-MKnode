"""MK 节点汇总。

新增节点时：
1. 在 nodes/ 下新建模块（如 nodes/my_node.py）
2. 从模块导入节点类
3. 把节点类加进 NODE_CLASSES
"""

from .adaptive_longest_edge import MKAdaptiveLongestEdge
from .bg_remove import MKBgRemove
from .adaptive_megapixels import MKAdaptiveMegapixels
from .any_switch import MKAnySwitch
from .gallery import MKFacePicker, MKGarmentPicker, MKPosePicker
from .ignore_groups import MKIgnoreGroups, MKIgnoreGroupsYouth
from .image_compare import MKImageCompare
from .image_crop import MKImageCrop
from .image_selector import MKImageSelector
from .load_image import MKLoadImage
from .image_merge_mask import MKImageMergeMask
from .mask_crop import MKCropRestore, MKMaskCrop
from .mask_is_empty import MKMaskIsEmpty
from .lora_loader import MKLoraLoaderModelOnly
from .prompt_concat import MKPromptConcat
from .prompt_library import MKPromptLibrary
# 存储路由（MK-提示词大全前端使用 /mk_prompt_store），import 即注册
from . import prompt_store  # noqa: F401
from .memory_cleanup import MKRAMCleanup, MKVRAMCleanup
from .qwen_pe import MKQwenImage21PromptEnhancer
from .save_image import MKSaveImage
from .tiled_upscale import MKTiledUpscale, MKTiledUpscaleStitch

NODE_CLASSES = [
    MKLoadImage,
    MKImageSelector,
    MKImageCompare,
    MKAnySwitch,
    MKIgnoreGroups,
    MKIgnoreGroupsYouth,
    MKPromptConcat,
    MKPromptLibrary,
    MKQwenImage21PromptEnhancer,
    MKVRAMCleanup,
    MKRAMCleanup,
    MKImageCrop,
    MKImageMergeMask,
    MKMaskCrop,
    MKMaskIsEmpty,
    MKCropRestore,
    MKAdaptiveMegapixels,
    MKBgRemove,
    MKAdaptiveLongestEdge,
    MKLoraLoaderModelOnly,
    MKSaveImage,
    MKTiledUpscale,
    MKTiledUpscaleStitch,
    MKPosePicker,
    MKGarmentPicker,
    MKFacePicker,
]

__all__ = [
    "NODE_CLASSES",
    "MKLoadImage",
    "MKImageSelector",
    "MKImageCompare",
    "MKAnySwitch",
    "MKIgnoreGroups",
    "MKIgnoreGroupsYouth",
    "MKPromptConcat",
    "MKPromptLibrary",
    "MKQwenImage21PromptEnhancer",
    "MKVRAMCleanup",
    "MKRAMCleanup",
    "MKImageCrop",
    "MKImageMergeMask",
    "MKMaskCrop",
    "MKMaskIsEmpty",
    "MKCropRestore",
    "MKAdaptiveMegapixels",
    "MKBgRemove",
    "MKAdaptiveLongestEdge",
    "MKLoraLoaderModelOnly",
    "MKSaveImage",
    "MKTiledUpscale",
    "MKTiledUpscaleStitch",
    "MKPosePicker",
    "MKGarmentPicker",
    "MKFacePicker",
]
