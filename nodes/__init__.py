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
from .ignore_groups import MKIgnoreGroups, MKIgnoreGroupsYouth
from .image_compare import MKImageCompare
from .image_crop import MKImageCrop
from .image_selector import MKImageSelector
from .load_image import MKLoadImage
from .image_merge_mask import MKImageMergeMask
from .mask_crop import MKCropRestore, MKMaskCrop
from .mask_is_empty import MKMaskIsEmpty
from .minimax_h3_media_loader import MKMinimaxH3MediaLoader, MKMinimaxH3MediaUnpack
from .minimax_h3_ref2video import MKMinimaxH3ReferenceToVideo
from .lora_loader import MKLoraLoaderModelOnly
from .prompt_concat import MKPromptConcat
from .prompt_preset_gallery import MKPromptPresetGallery
from .memory_cleanup import MKRAMCleanup, MKVRAMCleanup
from .qwen_pe import MKQwenImage21PromptEnhancer
from .save_image import MKSaveImage
from .tiled_upscale import MKTiledUpscale, MKTiledUpscaleStitch
from .text_encode_qwen_image21 import MKTextEncodeQwenImage21

NODE_CLASSES = [
    MKLoadImage,
    MKImageSelector,
    MKImageCompare,
    MKAnySwitch,
    MKIgnoreGroups,
    MKIgnoreGroupsYouth,
    MKPromptConcat,
    MKPromptPresetGallery,
    MKQwenImage21PromptEnhancer,
    MKVRAMCleanup,
    MKRAMCleanup,
    MKImageCrop,
    MKImageMergeMask,
    MKMaskCrop,
    MKMaskIsEmpty,
    MKCropRestore,
    MKMinimaxH3MediaLoader,
    MKMinimaxH3MediaUnpack,
    MKMinimaxH3ReferenceToVideo,
    MKAdaptiveMegapixels,
    MKBgRemove,
    MKAdaptiveLongestEdge,
    MKLoraLoaderModelOnly,
    MKSaveImage,
    MKTiledUpscale,
    MKTiledUpscaleStitch,
    MKTextEncodeQwenImage21,
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
    "MKPromptPresetGallery",
    "MKQwenImage21PromptEnhancer",
    "MKVRAMCleanup",
    "MKRAMCleanup",
    "MKImageCrop",
    "MKImageMergeMask",
    "MKMaskCrop",
    "MKMaskIsEmpty",
    "MKCropRestore",
    "MKMinimaxH3MediaLoader",
    "MKMinimaxH3MediaUnpack",
    "MKMinimaxH3ReferenceToVideo",
    "MKAdaptiveMegapixels",
    "MKBgRemove",
    "MKAdaptiveLongestEdge",
    "MKLoraLoaderModelOnly",
    "MKSaveImage",
    "MKTiledUpscale",
    "MKTiledUpscaleStitch",
    "MKTextEncodeQwenImage21",
]
