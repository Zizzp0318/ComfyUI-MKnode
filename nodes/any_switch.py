"""MK-任意切换（MK_AnySwitch）

迁移自 rgthree-comfy 的 ``Any Switch (rgthree)``（``py/any_switch.py`` +
``src_web/comfyui/any_switch.ts``）。

行为（与上游逐行保持一致）：

- 输入端数量由前端动态维护，命名 ``any_01``、``any_02``……
- 执行时按输入顺序找**第一个非空值**输出；全空则输出 ``None``
- 什么类型都能接、都能出（输出槽类型是 ``*``，实际类型由连进来的线决定）

本模块相对源包的改动：

- 分类 ``rgthree`` → ``MK节点``，与包内其余节点统一
- 只导出节点类，注册统一交给包根 ``__init__.py``
- 上游 ``utils.FlexibleOptionalInputType`` / ``AnyType`` 内联到这里，
  不再依赖 rgthree 的 ``utils.py``（避免跨包 import）
- 补充 ``DESCRIPTION`` / ``SEARCH_ALIASES`` / ``OUTPUT_TOOLTIPS``，便于搜索与提示

为什么用 V1 而不是 V3：

``any_01``…``any_NN`` 并不在 ``INPUT_TYPES`` 里，由前端 ``web/any_switch.js``
在运行时 addInput 添加。V1 的 ``execution.get_input_data`` 对「连线型（link）输入」
不做声明校验，这些未声明的输入会作为 ``**kwargs`` 传进 ``switch``。
V3 的 ``execute`` 走 ``get_finalized_class_inputs`` 做严格校验，需要
``accept_all_inputs`` 之类的额外开关才等价；这里保留 V1 写法以最小化风险
（与 ``MK_PromptConcat`` 的选择一致）。
"""

from typing import Union

# 动态输入端序号前缀。前端 web/any_switch.js 依赖同一约定，改动需同步。
INPUT_PREFIX = "any_"

# 输入端数量下限（含末尾那个空槽）。与前端 MIN_INPUTS 保持一致。
MIN_INPUTS = 5

# 输入端数量上限，防止极端情况下无限加槽。与前端 MAX_INPUTS 保持一致。
MAX_INPUTS = 64


class AnyType(str):
    """永不返回 True 的「不等于」比较，让 ComfyUI 认为它可以接任何类型。

    出处：pythongosssss 的 AnyType，rgthree 原样引用。
    """

    def __ne__(self, __value: object) -> bool:  # noqa: D105
        return False


class FlexibleOptionalInputType(dict):
    """让节点接受任意未声明的输入键。

    ComfyUI 在 PR #2666 之后不只看 ``__contains__``，还会取该键对应的
    ``(type,)`` 元组做校验，所以这里对任何未知键都返回 ``(self.type,)``。
    """

    def __init__(self, type, data: Union[dict, None] = None):  # noqa: A002
        self.type = type
        self.data = data
        if self.data is not None:
            for k, v in self.data.items():
                self[k] = v

    def __getitem__(self, key):
        if self.data is not None and key in self.data:
            return self.data[key]
        return (self.type,)

    def __contains__(self, key):  # noqa: D105
        return True


any_type = AnyType("*")


def _is_context_empty(ctx) -> bool:
    """判断 rgthree 的 CONTEXT 是否为空（所有值都是 None）。"""
    return not ctx or all(v is None for v in ctx.values())


def is_none(value) -> bool:
    """判断一个输入值是否算「空」。

    除 ``None`` 之外，还把 rgthree 的 CONTEXT（含 model/clip 的 dict）
    中全空的情况也视为空；这样上下文节点接进来时能正确跳过空上下文。
    """
    if value is not None:
        if isinstance(value, dict) and "model" in value and "clip" in value:
            return _is_context_empty(value)
    return value is None


def input_name(index: int) -> str:
    """序号 → 输入 id，如 1 -> 'any_01'。"""
    return f"{INPUT_PREFIX}{str(index).zfill(2)}"


class MKAnySwitch:
    """按顺序输出第一个非空输入，接什么类型就变成什么类型。"""

    DESCRIPTION = (
        "把多个任意类型的输入按顺序比较，输出第一个非空的值。"
        "输入端可动态增减：连满当前输入后会自动补一个空槽。"
    )
    SEARCH_ALIASES = [
        "any switch", "switch", "any", "first non empty", "fallback",
        "任意切换", "切换", "选择", "多路切换", "任意",
    ]
    CATEGORY = "MK节点"
    FUNCTION = "switch"
    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("任意",)
    OUTPUT_TOOLTIPS = ("第一个非空输入的值；全为空时输出空。",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            # 未知键一律当作「任意类型」的连线输入；具体槽位由前端添加
            "optional": FlexibleOptionalInputType(any_type),
        }

    def switch(self, **kwargs):
        """挑第一个非空的输入输出。

        Args:
            **kwargs: 由前端动态添加的 ``any_NN`` 输入。

        Returns:
            (第一个非空值 或 None,)
        """
        any_value = None
        for key, value in kwargs.items():
            if key.startswith(INPUT_PREFIX) and not is_none(value):
                any_value = value
                break
        return (any_value,)
