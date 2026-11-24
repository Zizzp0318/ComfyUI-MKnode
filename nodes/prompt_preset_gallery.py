"""MK-提示词预设图库（MK_PromptPresetGallery）

第一阶段：只搭外观 —— 一个多行文本输入框，下方一个「预设图库」按钮（占位，点击暂无面板）。

后续步骤：
- 按钮点开图片化预设库面板，点缩略图把对应提示词填进文本框；
- 库数据与缩略图的存储/路由。
"""

from comfy_api.latest import io


class MKPromptPresetGallery(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_PromptPresetGallery",
            display_name="MK-提示词预设图库",
            category="MK节点",
            description="提示词文本框 + 下方「预设图库」按钮（面板待实现）。",
            search_aliases=["prompt preset", "prompt gallery", "提示词预设", "预设图库"],
            inputs=[
                io.String.Input("text", display_name="提示词", multiline=True, dynamic_prompts=True),
            ],
            outputs=[
                io.String.Output("STRING", display_name="提示词"),
            ],
        )

    @classmethod
    def execute(cls, text) -> io.NodeOutput:
        return io.NodeOutput(text)
