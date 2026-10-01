import { app } from "../../scripts/app.js";

/**
 * MK 视频节点尺寸修复
 *
 * 问题根因（对应前端 src/composables/node/useNodeImage.ts 的 useNodeVideo）：
 *
 *   let minHeight = 256, minWidth = 256
 *   video.onloadeddata = () => setMinDimensions(video)   // 用【当时】的 node.size[0] 换算
 *   const widget = node.addDOMWidget(VIDEO_WIDGET_NAME, 'video', container, {...})
 *   widget.serialize = false
 *   widget.computeLayoutSize = () => ({ minHeight, minWidth })   // ← 注意这一句
 *
 * 这个 minWidth / minHeight 会被 LGraphNode 当作硬约束：
 *   - computeSize() 里 `if (widgetWidth > size[0]) size[0] = widgetWidth` —— minWidth 反过来撑大节点宽度
 *   - _arrangeWidgets() 里 `if (y > bodyHeight) this.setSize([...])` —— 控件高度不够就把节点顶回去
 * 而且它是在「视频加载那一刻」按当时的节点宽度算出来就固定的，所以每次重新加载尺寸都会跳变。
 *
 * 修法的关键：官方是在 addDOMWidget 返回之后【又赋值了一次】computeLayoutSize，
 * 所以单纯在 addDOMWidget 里赋值会被它冲掉。这里用访问器属性接管该字段，
 * 让官方那次赋值落空（setter 忽略写入），读取时始终返回我们自己的实现。
 *
 * 注意不要把这个属性定义成只读：useNodeImage.ts 是 ES 模块（严格模式），
 * 官方那句赋值遇到只读属性会直接抛 TypeError，预览会整个挂掉。
 */

const VIDEO_PREVIEW_WIDGET_NAME = "video-preview";
const DEFAULT_VIDEO_SIZE = 256;

/**
 * 预览区的最小高度。
 *
 * 必须是**固定值**——不能由视频尺寸推导，否则就是「节点根据视频自动调整大小」这个老问题。
 * 之所以不设成 0：新建节点时 computeSize 不含视频高度，节点会小到 80px 左右，
 * 预览区直接看不见。这里给一个和「MK-视频加载（高级）」观感相当的下限，
 * 高于它的部分可以随意缩放。
 */
const MIN_PREVIEW_HEIGHT = 256;

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

      const computeLayoutSize = () => {
        // 画布模式：宽度不设下限（节点可自由变窄）；
        // 高度给一个固定下限，既不随视频尺寸变化，也保证新建节点时预览可见。
        if (!isVueNodesMode()) {
          return { minHeight: MIN_PREVIEW_HEIGHT, minWidth: 0 };
        }

        // Vue 节点模式：控件高度就是视频显示高度，按【当前】宽度实时等比换算。
        // 该模式下 WidgetLegacy.vue 直接拿 minHeight 当控件高度，返回 0 会让视频不可见，
        // 所以这里必须给一个实时值；关键是「实时」，不能像官方那样缓存加载时刻的结果。
        const video = element?.querySelector?.("video");
        const videoWidth = video?.videoWidth;
        const videoHeight = video?.videoHeight;
        if (!videoWidth || !videoHeight) {
          return { minHeight: MIN_PREVIEW_HEIGHT, minWidth: 0 };
        }
        const nodeWidth = node?.size?.[0] || DEFAULT_VIDEO_SIZE;
        return {
          minHeight: Math.max(
            MIN_PREVIEW_HEIGHT,
            Math.round((nodeWidth * videoHeight) / videoWidth)
          ),
          minWidth: 0,
        };
      };

      // 用访问器接管：官方随后的 `widget.computeLayoutSize = ...` 会被 setter 吞掉
      Object.defineProperty(widget, "computeLayoutSize", {
        configurable: true,
        enumerable: false,
        get: () => computeLayoutSize,
        set: () => {},
      });

      return widget;
    };
  },
});
