"""MK-禁用多框 / MK-忽略多框（MK_FastGroupsMuter / MK_FastGroupsBypasser）

迁移自 rgthree-comfy 的 ``Fast Groups Muter (rgthree)`` 与
``Fast Groups Bypasser (rgthree)``（``src_web/comfyui/fast_groups_muter.ts`` /
``fast_groups_bypasser.ts`` / ``services/fast_groups_service.ts``）。

这两个节点**没有实际的计算逻辑**：它们在画布上把所有「分组（Group）」列成开关，
点一下就把该分组内的节点整体改成「启用 / 禁用（Mute）」或「启用 / 忽略（Bypass）」。

本模块为什么要给它们建一个后端类：

- 上游是**纯前端虚拟节点**（``RgthreeBaseVirtualNode``，只在 ``LiteGraph`` 注册，
  后端没有对应类）。这种方式在 Nodes 2.0 的 Vue 渲染下：① 节点菜单读的是后端
  ``/object_info``，虚拟节点不一定出现；② 它自绘 canvas widget 的交互也不会被调用。
- 所以这里补一个**零输入零输出的空节点**，让节点由后端正式注册、在两种渲染模式下
  都能出现在菜单里；面板完全由前端 DOM 组件绘制（见 ``web/fast_groups.js``）。
- 空节点不会进入执行：``RETURN_TYPES = ()`` 且不是输出节点，ComfyUI 校验时只做
  输入检查，不会被执行（实测 ``validate_prompt`` 通过，且不参与执行列表）。
"""


class _MKGroupsUINode:
    """两个节点共用的空实现：纯 UI 节点，不参与计算。"""

    CATEGORY = "MK节点"
    FUNCTION = "noop"
    RETURN_TYPES = ()
    INPUT_TYPES_MODE = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    def noop(self):
        """空节点被执行时什么都不做。"""
        return ()


class MKFastGroupsMuter(_MKGroupsUINode):
    """把当前工作流里的分组列成「启用 / 禁用」开关。"""

    DESCRIPTION = (
        "把当前工作流里的所有分组列成开关，点一下即可把该分组内的节点整体禁用（Mute）或恢复启用。"
        "开关列表由节点面板自动维护，支持按位置/名称排序、按标题或颜色过滤。"
    )
    SEARCH_ALIASES = [
        "fast groups muter", "group mute", "mute group", "muter",
        "禁用多框", "分组禁用", "分组静音", "多框禁用",
    ]
    INPUT_TYPES_MODE = "mute"

    # 供前端与测试读取的模式值（LiteGraph 的 mode 常量）
    MODE_ON = 0  # LiteGraph.ALWAYS
    MODE_OFF = 2  # LiteGraph.NEVER


class MKFastGroupsBypasser(_MKGroupsUINode):
    """把当前工作流里的分组列成「启用 / 忽略」开关。"""

    DESCRIPTION = (
        "把当前工作流里的所有分组列成开关，点一下即可把该分组内的节点整体忽略（Bypass）或恢复启用。"
        "与禁用不同，忽略节点会把输入原样透传给输出。"
    )
    SEARCH_ALIASES = [
        "fast groups bypasser", "group bypass", "bypass group", "bypasser",
        "忽略多框", "分组忽略", "多框忽略", "旁路分组",
    ]
    INPUT_TYPES_MODE = "bypass"

    MODE_ON = 0  # LiteGraph.ALWAYS
    MODE_OFF = 4  # ComfyUI 的 BYPASS
