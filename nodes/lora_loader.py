"""MK-Lora加载器（MK_LoraLoaderModelOnly）

迁移自 ComfyUI 官方 ``nodes.py`` 的 ``LoraLoaderModelOnly``
（"LoRA加载器（仅模型）"），并新增一个「无」选项。

相对官方版本的改动：

- ``lora_name`` 下拉框第一项固定是 **"无"**：选中它时**不加载任何 LoRA**，
  直接把输入的 MODEL 原样输出。官方节点必须挂一个 LoRA 文件才能用，
  做「可选开关式 LoRA」时很别扭。
- 默认选中 "无"（combo 的第一项即默认值），这样新拉出来的节点不会因为
  找不到默认 LoRA 直接报错；确认要加 LoRA 时在下拉里选文件即可。
- 分类 ``model/loaders`` → ``MK节点``，与包内其余节点统一
- 补充 ``DESCRIPTION`` / ``SEARCH_ALIASES`` / ``OUTPUT_TOOLTIPS`` /
  各输入的 ``tooltip``，便于搜索与提示

刻意保持不变（行为等价优先）：

- LoRA 文件的解析、缓存（``self.loaded_lora`` 按路径复用）、错误处理
  （文件不存在时 ``get_full_path_or_raise`` 抛错）、``strength_model == 0``
  时短路返回原模型——都与官方 ``LoraLoader.load_lora`` 逐行一致。
"""

import comfy.sd
import comfy.utils
import folder_paths

# 「不加载」哨兵值。前端 web 里没有同名常量，改动只需同步 README。
NONE_OPTION = "无"


class MKLoraLoaderModelOnly:
    """给扩散模型叠加 LoRA；选「无」则原样透传。"""

    DESCRIPTION = (
        "给扩散模型加载 LoRA，只影响模型、不碰 CLIP。"
        "「LoRA」选「无」时不加载任何 LoRA，把输入模型原样输出，可用来做可选开关。"
    )
    SEARCH_ALIASES = [
        "lora", "load lora", "apply lora", "lora loader", "lora model",
        "lora加载器", "加载lora", "Lora加载器", "仅模型",
    ]
    CATEGORY = "MK节点"
    FUNCTION = "load_lora_model_only"
    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("模型",)
    OUTPUT_TOOLTIPS = ("加载了 LoRA 的模型；选「无」时就是输入的模型本身。",)

    def __init__(self):
        self.loaded_lora = None

    @classmethod
    def INPUT_TYPES(cls):
        # 「无」放第一项 → 新建节点时默认就是它
        lora_options = [NONE_OPTION] + folder_paths.get_filename_list("loras")
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "要叠加 LoRA 的扩散模型。"}),
                "lora_name": (
                    lora_options,
                    {"tooltip": "要加载的 LoRA 文件。选「无」则不加载任何 LoRA，模型原样输出。"},
                ),
                "strength_model": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": -100.0,
                        "max": 100.0,
                        "step": 0.01,
                        "tooltip": "LoRA 对模型的影响强度，可以为负数；为 0 时同样等于不加载。",
                    },
                ),
            }
        }

    def load_lora_model_only(self, model, lora_name, strength_model):
        """加载 LoRA 并返回新模型；选「无」或强度为 0 时原样返回输入模型。"""
        # 新增分支：不加载
        if not lora_name or lora_name == NONE_OPTION:
            return (model,)

        # 以下与官方 LoraLoader.load_lora 的「仅模型」路径等价
        if strength_model == 0:
            return (model,)

        lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
        lora = None
        lora_metadata = None
        if self.loaded_lora is not None:
            if self.loaded_lora[0] == lora_path:
                lora = self.loaded_lora[1]
                lora_metadata = self.loaded_lora[2] if len(self.loaded_lora) > 2 else None
            else:
                self.loaded_lora = None

        if lora is None:
            lora, lora_metadata = comfy.utils.load_torch_file(
                lora_path, safe_load=True, return_metadata=True
            )
            self.loaded_lora = (lora_path, lora, lora_metadata)

        model_lora, _ = comfy.sd.load_lora_for_models(
            model, None, lora, strength_model, 0, lora_metadata=lora_metadata
        )
        return (model_lora,)
