"""Comfyui_MKnode —— MK 系列节点包。

这里用 NODE_CLASS_MAPPINGS 注册而不是 V3 的 comfy_entrypoint，原因是
ComfyUI 的加载器对两者是 if/elif 二选一，而包内同时存在：
- V3 节点（io.ComfyNode 子类，如 MKLoadImage）
- V1 节点（如 MKImageSelector 交互式输出节点；MKPromptConcat 依赖
  未在 INPUT_TYPES 声明的动态输入，见其模块 docstring）

执行器用 `issubclass(class_def, _ComfyNodeInternal)` 判定版本，
因此两类节点可以混在 NODE_CLASS_MAPPINGS 里一起注册。
"""

from .nodes import (
    MKAdaptiveLongestEdge,
    MKAdaptiveMegapixels,
    MKBgRemove,
    MKAnySwitch,
    MKIgnoreGroups,
    MKIgnoreGroupsYouth,
    MKImageCompare,
    MKImageCrop,
    MKImageMergeMask,
    MKCropRestore,
    MKMaskCrop,
    MKMaskIsEmpty,
    MKMinimaxH3MediaLoader,
    MKMinimaxH3MediaUnpack,
    MKMinimaxH3ReferenceToVideo,
    MKImageSelector,
    MKLoadImage,
    MKLoraLoaderModelOnly,
    MKPromptConcat,
    MKPromptPresetGallery,
    MKQwenImage21PromptEnhancer,
    MKVRAMCleanup,
    MKRAMCleanup,
    MKSaveImage,
    MKTiledUpscale,
    MKTiledUpscaleStitch,
    MKTextEncodeQwenImage21,
)

WEB_DIRECTORY = "./web"

# 提示词预设图库的用户数据路由（/mk_ppg/*，落 user/default/MKnode/Prompt Preset）与
# 素材加载的上传/预览路由（/mk_h3/*，落 input/MKnode/h3/<kind>），import 即注册
from . import mk_h3_media_store  # noqa: E402,F401
from . import mk_ppg_store  # noqa: E402,F401

NODE_CLASS_MAPPINGS = {
    "MK_LoadImage": MKLoadImage,
    "MK_ImageSelector": MKImageSelector,
    "MK_ImageCompare": MKImageCompare,
    "MK_AnySwitch": MKAnySwitch,
    "MK_IgnoreGroups": MKIgnoreGroups,
    "MK_IgnoreGroupsYouth": MKIgnoreGroupsYouth,
    "MK_PromptConcat": MKPromptConcat,
    "MK_PromptPresetGallery": MKPromptPresetGallery,
    "MK_QwenImage21PromptEnhancer": MKQwenImage21PromptEnhancer,
    "MK_VRAMCleanup": MKVRAMCleanup,
    "MK_RAMCleanup": MKRAMCleanup,
    "MK_ImageCrop": MKImageCrop,
    "MK_ImageMergeMask": MKImageMergeMask,
    "MK_MaskCrop": MKMaskCrop,
    "MK_MaskIsEmpty": MKMaskIsEmpty,
    "MK_CropRestore": MKCropRestore,
    "MK_MinimaxH3MediaLoader": MKMinimaxH3MediaLoader,
    "MK_MinimaxH3MediaUnpack": MKMinimaxH3MediaUnpack,
    "MK_MinimaxH3ReferenceToVideo": MKMinimaxH3ReferenceToVideo,
    "MK_AdaptiveMegapixels": MKAdaptiveMegapixels,
    "MK_BgRemove": MKBgRemove,
    "MK_AdaptiveLongestEdge": MKAdaptiveLongestEdge,
    "MK_LoraLoaderModelOnly": MKLoraLoaderModelOnly,
    "MK_SaveImage": MKSaveImage,
    "MK_TiledUpscale": MKTiledUpscale,
    "MK_TiledUpscaleStitch": MKTiledUpscaleStitch,
    "MK_TextEncodeQwenImage21": MKTextEncodeQwenImage21,
}

# V3 节点的显示名以 Schema 内的 display_name 为准，这里保持一致
NODE_DISPLAY_NAME_MAPPINGS = {
    "MK_LoadImage": "MK-加载图像",
    "MK_ImageSelector": "MK-图像选择器",
    "MK_ImageCompare": "MK-图像对比",
    "MK_AnySwitch": "MK-任意切换",
    "MK_IgnoreGroups": "MK-禁用（忽略）多组老年关怀版",
    "MK_IgnoreGroupsYouth": "MK-禁用（忽略）多组青春版",
    "MK_PromptConcat": "MK-提示词拼接",
    "MK_PromptPresetGallery": "MK-提示词预设图库",
    "MK_QwenImage21PromptEnhancer": "MK-Qwen Image 2.1提示词增强",
    "MK_VRAMCleanup": "MK-显存清理",
    "MK_RAMCleanup": "MK-内存清理",
    "MK_ImageCrop": "MK-图像裁剪",
    "MK_ImageMergeMask": "MK-图像合并（遮罩）",
    "MK_MaskCrop": "MK-遮罩裁剪",
    "MK_MaskIsEmpty": "MK-遮罩是否为空",
    "MK_CropRestore": "MK-裁剪恢复",
    "MK_MinimaxH3MediaLoader": "MK-MiniMax H3素材加载",
    "MK_MinimaxH3MediaUnpack": "MK-MiniMax H3素材解包",
    "MK_MinimaxH3ReferenceToVideo": "MK-Minimax H3多参考生视频",
    "MK_AdaptiveMegapixels": "MK-自适应百万像素",
    "MK_BgRemove": "MK-图片背景移除",
    "MK_AdaptiveLongestEdge": "MK-自适应最长边",
    "MK_LoraLoaderModelOnly": "MK-Lora加载器",
    "MK_SaveImage": "MK-图像保存",
    "MK_TiledUpscale": "MK-图像分块",
    "MK_TiledUpscaleStitch": "MK-分块合并",
    "MK_TextEncodeQwenImage21": "MK-Qwen Image 2.1文本编码器",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
