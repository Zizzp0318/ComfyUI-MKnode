import { app } from "../../scripts/app.js";

/**
 * MK 视频节点尺寸修复
 *
 * 问题根因（对应前端 src/composables/node/useNodeImage.ts 的 useNodeVideo）：
 *
 *   let minHeight = 256, minWidth = 256
 *   video.onloadeddata = () => setMinDimensions(video)   // 用【当时】的 node.size[0] 换算
 *   widget.computeLayoutSize = () => ({ minHeight, minWidth })
 *
 * 这个 minWidth / minHeight 一旦算出来就固定了，而它会被 LGraphNode 当作硬约束：
 *   - computeSize() 里 `if (widgetWidth > size[0]) size[0] = widgetWidth` —— minWidth 反过来撑大节点宽度
 *   - _arrangeWidgets() 里 `if (y > bodyHeight) this.setSize([...])` —— 控件高度不够就把节点顶回去
 *
 * 于是出现三个症状：
 *   1. 节点没法变窄（被 minWidth 顶住）
 *   2. 节点没法变矮（被 minHeight 顶住）
 *   3. 每次重新加载视频都按新的宽度重算一遍最小尺寸，节点尺寸随之跳变
 *
 * 修法：接管 computeLayoutSize
 *   - minWidth 一律返回 0，宽度不再被约束
 *   - 画布模式下 minHeight 也返回 0（控件会填满节点剩余空间），节点完全自由缩放
 *   - Vue 节点模式下控件高度即视频高度，改为按【当前】节点宽度实时换算，不缓存过期值
 */

const VIDEO_PREVIEW_WIDGET_NAME = "video-preview";
const DEFAULT_VIDEO_SIZE = 256;

/**
 * 需要修复的节点名。
 * 官方 LoadVideo / SaveVideo 一并列入——它们的症状完全相同。
 * 如果不想改动官方节点的行为，把最后两项删掉即可。
 */
const TARGET_NODE_NAMES = new Set([
  "MK_LoadVideo",
  "MK_SaveVideo",
  "LoadVideo",
  "SaveVideo",
]);

const isVueNodesMode = () =>
  typeof LiteGraph !== "undefined" && !!LiteGraph.vueNodesMode;

app.registerExtension({
  name: "Comfyui_MKnode.VideoNodeFreeResize",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!TARGET_NODE_NAMES.has(nodeData.name)) return;

    const originalAddDOMWidget = nodeType.prototype.addDOMWidget;
    if (typeof originalAddDOMWidget !== "function") return;

    nodeType.prototype.addDOMWidget = function (name, type, element, options) {
      const widget = originalAddDOMWidget.apply(this, arguments);
      if (!widget || name !== VIDEO_PREVIEW_WIDGET_NAME) return widget;

      const node = this;

      widget.computeLayoutSize = () => {
        if (!isVueNodesMode()) {
          // 画布模式：控件填满节点剩余空间，不施加任何下限
          return { minHeight: 0, minWidth: 0 };
        }

        // Vue 节点模式：控件高度就是视频显示高度，按当前宽度实时等比换算
        const video = element?.querySelector?.("video");
        const videoWidth = video?.videoWidth;
        const videoHeight = video?.videoHeight;
        if (!videoWidth || !videoHeight) {
          return { minHeight: DEFAULT_VIDEO_SIZE, minWidth: 0 };
        }
        const nodeWidth = node?.size?.[0] || DEFAULT_VIDEO_SIZE;
        return {
          minHeight: Math.round((nodeWidth * videoHeight) / videoWidth),
          minWidth: 0,
        };
      };

      return widget;
    };
  },
});
