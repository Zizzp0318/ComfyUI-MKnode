"""MK-提示词拼接（MK_PromptConcat）

迁移自 Comfyui-MK_Tools 的 ``nodes/prompt_concat.py``
（其本身改编自 ComfyUI-Easy-Use 的 ``easy promptConcat``）。

本模块相对源包版本的改动：

- 分类 ``MK_Tools/工具`` → ``MK节点``，与包内其余节点统一
- 只导出节点类，注册统一交给包根 ``__init__.py``
  （源包是在模块里自建 ``NODE_CLASS_MAPPINGS``）
- 补充 ``DESCRIPTION`` / ``SEARCH_ALIASES`` / ``OUTPUT_TOOLTIPS``，便于搜索与提示
- 输入名拼装抽成 ``_prompt_input_name()``，上限抽成 ``MAX_PROMPT_INPUTS``，
  供前后端对齐

刻意保持不变（兼容性优先）：

- 节点 id 仍是 ``MK_PromptConcat``。已发布的 node_id 不能改，
  否则引用它的已保存工作流会失联。
- 内部输入 id 仍是中文（``分隔符`` / ``提示词_01``…``提示词_10``）。
  包内其他节点遵循「内部 id 用英文、显示名走 locales」的约定，本节点是例外——
  为兼容源包已保存的工作流而保留原 id。它们本来就是中文，无需额外翻译。

为什么用 V1 而不是 V3：

动态输入 ``提示词_02``…``提示词_10`` 并不出现在 ``INPUT_TYPES`` 里，
只在运行时由前端 ``web/prompt_concat.js`` 添加。``execution.py`` 的
``get_input_data`` 对「连线型（link）输入」不做声明校验，所以这些未声明的
输入仍会作为 ``**kwargs`` 传进 ``concat``。V3 的 ``execute`` 走
``get_finalized_class_inputs`` 校验，需要额外的 ``accept_all_inputs`` 才等价，
改动面更大；这里保留 V1 写法以最小化风险。
"""

# 动态输入端上限。前端 web/prompt_concat.js 里有一份同样的常量，改动需同步。
MAX_PROMPT_INPUTS = 10

# 输入 id 前缀，前端同样依赖这个约定。
_PROMPT_PREFIX = "提示词_"


def _prompt_input_name(index: int) -> str:
    """序号 → 输入 id，如 1 -> '提示词_01'。"""
    return f"{_PROMPT_PREFIX}{str(index).zfill(2)}"


class MKPromptConcat:
    """把多个提示词按指定分隔符拼成一条字符串。

    输入端可动态增减：连满当前输入端会自动补一个空槽，最多 10 个；
    空值（未连接 / 空串）不参与拼接。
    """

    DESCRIPTION = (
        "把多个提示词用指定分隔符拼接成一条字符串，空输入自动跳过。"
        "输入端可动态增减，最多 10 个。"
    )
    SEARCH_ALIASES = [
        "prompt concat", "concat prompt", "join prompt", "combine prompt",
        "string join", "merge prompt", "提示词拼接", "拼接", "合并提示词",
    ]
    CATEGORY = "MK节点"
    FUNCTION = "concat"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词",)
    OUTPUT_TOOLTIPS = ("拼接后的提示词。",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # 参数名必须与 concat() 的形参一致
                "分隔符": ("STRING", {"multiline": False, "default": ", "}),
            },
            "optional": {
                # 只有第一个输入写进 schema，其余 02…10 由前端按需添加。
                # forceInput：不生成文本框，只留一个连线槽。
                _prompt_input_name(1): (
                    "STRING",
                    {"multiline": False, "default": "", "forceInput": True},
                ),
            },
        }

    def concat(self, 分隔符=", ", **kwargs):
        """按序拼接 提示词_01…提示词_10，跳过空值。

        Args:
            分隔符: 连接各段提示词的字符串。
            **kwargs: 由前端动态添加的 ``提示词_NN`` 输入。

        Returns:
            (拼接结果,)
        """

        def to_string(value):
            """把任意输入转成字符串；列表/元组递归展开后仍用逗号连接。"""
            if isinstance(value, (list, tuple)):
                return ", ".join(to_string(v) for v in value)
            return str(value)

        prompts = []
        for i in range(1, MAX_PROMPT_INPUTS + 1):
            value = kwargs.get(_prompt_input_name(i))
            if not value:
                continue
            text = to_string(value)
            if text:
                prompts.append(text)

        return (to_string(分隔符).join(prompts),)
