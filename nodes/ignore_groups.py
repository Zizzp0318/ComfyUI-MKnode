"""MK-禁用（忽略）多组（MK_IgnoreGroups）

迁移自 GoohaiTools-comfyui 的「忽略多组 孤海」（``nodes/忽略多组.py`` +
``web/js/nodes pass.js``，节点 id ``忽略多组孤海``）。

节点本身没有输入输出，只是给前端一个挂载点：真正的面板由
``web/ignore_groups.js`` 用 DOM 画在节点上，列出当前画布的所有编组，
每行一个开关，把整组节点切到「启用 / 绕过(Bypass) / 禁用(Mute)」。

保持原节点行为（迁移时不改逻辑，只按本包约定改名）：
- ``INPUT_TYPES`` 为空、``RETURN_TYPES = ()``、``OUTPUT_NODE = True``；
- 分类改到 ``MK节点``，节点 id ``忽略多组孤海`` -> ``MK_IgnoreGroups``，
  显示名 -> ``MK-禁用（忽略）多组``；
- 前端的属性键 ``guhai_ig_*`` -> ``mk_ig_*``、DOM id/类名前缀 -> ``mk-ig-*``，
  避免两包同时安装时互相覆盖。

沿用 V1 写法：本节点是纯 UI 节点，没有 schema 可声明，V3 的
``io.Schema`` 在这里只能写成空壳，反而多一层包装。
"""


class MKIgnoreGroups:
    """MK-禁用（忽略）多组 — 通过开关控制工作流中各编组的禁用/绕过状态"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "MK节点"
    OUTPUT_NODE = True

    def execute(self):
        return ()
