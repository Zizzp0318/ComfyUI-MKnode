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
    MKFastGroupsBypasser,
    MKFastGroupsMuter,
    MKImageCompare,
    MKImageCrop,
    MKImageMergeMask,
    MKCropRestore,
    MKMaskCrop,
    MKFacePicker,
    MKGarmentPicker,
    MKImageSelector,
    MKPosePicker,
    MKLoadImage,
    MKLoraLoaderModelOnly,
    MKPromptConcat,
    MKPromptLibrary,
    MKQwenImage21PromptEnhancer,
    MKVRAMCleanup,
    MKRAMCleanup,
    MKPromptPreset,
    MKSaveImage,
    MKTiledUpscale,
    MKTiledUpscaleStitch,
)

WEB_DIRECTORY = "./web"

# 图库：注册 /mkposes /mkgarments /mkfaces 路由，并准备用户素材目录
from . import gallery_api  # noqa: E402,F401
from .mkg import bootstrap  # noqa: E402

bootstrap.ensure_userdata()

NODE_CLASS_MAPPINGS = {
    "MK_LoadImage": MKLoadImage,
    "MK_ImageSelector": MKImageSelector,
    "MK_ImageCompare": MKImageCompare,
    "MK_AnySwitch": MKAnySwitch,
    "MK_FastGroupsMuter": MKFastGroupsMuter,
    "MK_FastGroupsBypasser": MKFastGroupsBypasser,
    "MK_PromptConcat": MKPromptConcat,
    "MK_PromptPreset": MKPromptPreset,
    "MK_PromptLibrary": MKPromptLibrary,
    "MK_QwenImage21PromptEnhancer": MKQwenImage21PromptEnhancer,
    "MK_VRAMCleanup": MKVRAMCleanup,
    "MK_RAMCleanup": MKRAMCleanup,
    "MK_ImageCrop": MKImageCrop,
    "MK_ImageMergeMask": MKImageMergeMask,
    "MK_MaskCrop": MKMaskCrop,
    "MK_CropRestore": MKCropRestore,
    "MK_AdaptiveMegapixels": MKAdaptiveMegapixels,
    "MK_BgRemove": MKBgRemove,
    "MK_AdaptiveLongestEdge": MKAdaptiveLongestEdge,
    "MK_LoraLoaderModelOnly": MKLoraLoaderModelOnly,
    "MK_SaveImage": MKSaveImage,
    "MK_TiledUpscale": MKTiledUpscale,
    "MK_TiledUpscaleStitch": MKTiledUpscaleStitch,
    "MKPosePicker": MKPosePicker,
    "MKGarmentPicker": MKGarmentPicker,
    "MKFacePicker": MKFacePicker,
}

# V3 节点的显示名以 Schema 内的 display_name 为准，这里保持一致
NODE_DISPLAY_NAME_MAPPINGS = {
    "MK_LoadImage": "MK-加载图像",
    "MK_ImageSelector": "MK-图像选择器",
    "MK_ImageCompare": "MK-图像对比",
    "MK_AnySwitch": "MK-任意切换",
    "MK_FastGroupsMuter": "MK-禁用多框",
    "MK_FastGroupsBypasser": "MK-忽略多框",
    "MK_PromptConcat": "MK-提示词拼接",
    "MK_PromptPreset": "MK-提示词预设管理",
    "MK_PromptLibrary": "MK-提示词大全",
    "MK_QwenImage21PromptEnhancer": "MK-Qwen Image 2.1提示词增强",
    "MK_VRAMCleanup": "MK-显存清理",
    "MK_RAMCleanup": "MK-内存清理",
    "MK_ImageCrop": "MK-图像裁剪",
    "MK_ImageMergeMask": "MK-图像合并（遮罩）",
    "MK_MaskCrop": "MK-遮罩裁剪",
    "MK_CropRestore": "MK-裁剪恢复",
    "MK_AdaptiveMegapixels": "MK-自适应百万像素",
    "MK_BgRemove": "MK-图片背景移除",
    "MK_AdaptiveLongestEdge": "MK-自适应最长边",
    "MK_LoraLoaderModelOnly": "MK-Lora加载器",
    "MK_SaveImage": "MK-图像保存",
    "MK_TiledUpscale": "MK-图像分块",
    "MK_TiledUpscaleStitch": "MK-分块合并",
    "MKPosePicker": "MK-姿态库",
    "MKGarmentPicker": "MK-服装库",
    "MKFacePicker": "MK-脸模库",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
