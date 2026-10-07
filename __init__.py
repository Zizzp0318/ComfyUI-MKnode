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
    MKImageCrop,
    MKImageSelector,
    MKLoadImage,
    MKPromptConcat,
    MKPromptPreset,
    MKSaveImage,
)

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "MK_LoadImage": MKLoadImage,
    "MK_ImageSelector": MKImageSelector,
    "MK_PromptConcat": MKPromptConcat,
    "MK_PromptPreset": MKPromptPreset,
    "MK_ImageCrop": MKImageCrop,
    "MK_SaveImage": MKSaveImage,
}

# V3 节点的显示名以 Schema 内的 display_name 为准，这里保持一致
NODE_DISPLAY_NAME_MAPPINGS = {
    "MK_LoadImage": "MK-加载图像",
    "MK_ImageSelector": "MK-图像选择器",
    "MK_PromptConcat": "MK-提示词拼接",
    "MK_PromptPreset": "MK-提示词预设管理",
    "MK_ImageCrop": "MK-图像裁剪",
    "MK_SaveImage": "MK-图像保存",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
