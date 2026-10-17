// MK-图像对比 —— 前端（DOM 组件版，旧 LiteGraph 与 Nodes 2.0 通用）
//
// 对应后端 nodes/image_compare.py。执行时后端把两张图存成临时文件，
// 通过 ui.a_images / ui.b_images 回传；这里把它们叠加显示：
//   - 底层：图像B（after）
//   - 上层：图像A（before），用 clip-path 从左往右裁到鼠标位置
//   - 分割线 + 圆形把手跟随鼠标横坐标
// 交互与官方 ImageCompare 节点一致（鼠标在预览区内移动即移动分割线）。
//
// 之所以不用官方那个 imagecompare widget：核心扩展 Comfy.ImageCompare 只对
// comfyClass === "ImageCompare" 的节点接线，自建节点拿不到它的 onExecuted 逻辑。

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "MK_ImageCompare";
const STYLE_ID = "mk-ic-style";

const MIN_PANEL_HEIGHT = 200;
const MIN_NODE_SIZE = [360, 340];
const DEFAULT_NODE_SIZE = [420, 380];

const CSS = `
.mk-ic-wrap {
    box-sizing: border-box;
    width: 100%;
    height: 100%;
    min-height: 200px;
    display: flex;
    flex-direction: column;
    padding: 6px;
    background: #1b1b1d;
    border: 1px solid #333;
    border-radius: 6px;
    font: 12px/1.4 Arial, sans-serif;
    color: #ddd;
    overflow: hidden;
}
.mk-ic-batch {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 0 2px 4px;
    font-size: 11px;
    color: #9aa0a6;
}
.mk-ic-batchnav { display: flex; align-items: center; gap: 4px; }
.mk-ic-batchnav.is-hidden { visibility: hidden; }
.mk-ic-batchnav button {
    width: 18px;
    height: 18px;
    padding: 0;
    line-height: 1;
    border: 1px solid #4a4d52;
    border-radius: 3px;
    background: #2a2d31;
    color: #cfd3d8;
    font: 11px Arial, sans-serif;
    cursor: pointer;
}
.mk-ic-batchnav button:hover:not(:disabled) { background: #3a3f46; }
.mk-ic-batchnav button:disabled { opacity: .35; cursor: default; }
.mk-ic-index {
    min-width: 30px;
    text-align: center;
    color: #e7b94f;
    font-variant-numeric: tabular-nums;
}
.mk-ic-view {
    position: relative;
    flex: 1 1 0%;
    min-height: 0;
    overflow: hidden;
    border-radius: 5px;
    background: #121214;
    cursor: ew-resize;
}
.mk-ic-view img {
    /* 绝对定位：图片尺寸不参与布局，节点高度只由用户拖拽决定 */
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
    pointer-events: none;
    user-select: none;
}
.mk-ic-handle {
    position: absolute;
    top: 0;
    height: 100%;
    width: 24px;
    margin-left: -12px;
    pointer-events: none;
    z-index: 10;
}
.mk-ic-line {
    position: absolute;
    left: 50%;
    width: 1px;
    margin-left: -0.5px;
    background: rgba(255, 255, 255, .45);
}
.mk-ic-line-top { top: 0; height: calc(50% - 14px); }
.mk-ic-line-bottom { bottom: 0; height: calc(50% - 14px); }
.mk-ic-knob {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 22px;
    height: 22px;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    border: 2px solid #fff;
    background: rgba(255, 255, 255, .22);
    box-shadow: 0 1px 6px rgba(0, 0, 0, .55);
    backdrop-filter: blur(2px);
}
.mk-ic-empty {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
    text-align: center;
    color: #7d848c;
    line-height: 1.7;
}
.mk-ic-empty[hidden] { display: none; }
`;

function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = CSS;
    document.head.appendChild(el);
}

/** 把后端回传的图片引用转成可显示的 URL（与官方扩展同一套参数） */
function imageUrl(item) {
    const params = new URLSearchParams(item);
    return api.apiURL(`/view?${params}&rand=${Math.random()}`);
}

app.registerExtension({
    name: "Comfyui_MKnode.ImageCompare",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        injectStyle();

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);

            this.mkBeforeImages = [];
            this.mkAfterImages = [];
            this.mkBeforeIndex = 0;
            this.mkAfterIndex = 0;
            this.mkPosition = 50;

            this.buildComparePanel();

            if (!Array.isArray(this.size) || this.size[1] < MIN_NODE_SIZE[1]) {
                this.setSize([...DEFAULT_NODE_SIZE]);
            }

            return result;
        };

        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function () {
            const result = onResize?.apply(this, arguments);
            const sync = () => this.syncPanelHeight();
            if (typeof requestAnimationFrame === "function") requestAnimationFrame(sync);
            else sync();
            return result;
        };

        // 后端执行完把 a_images / b_images 塞进来
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            const data = message || {};
            this.mkBeforeImages = (Array.isArray(data.a_images) ? data.a_images : []).map(
                imageUrl
            );
            this.mkAfterImages = (Array.isArray(data.b_images) ? data.b_images : []).map(
                imageUrl
            );

            // 与官方一致：有新一轮数据就回到第一张
            this.mkBeforeIndex = 0;
            this.mkAfterIndex = 0;

            this.renderCompare();
        };

        // ── 构建 DOM 面板 ──
        nodeType.prototype.buildComparePanel = function () {
            const wrap = document.createElement("div");
            wrap.className = "mk-ic-wrap";

            const batch = document.createElement("div");
            batch.className = "mk-ic-batch";

            const navA = this.createBatchNav("图像A", "before");
            const navB = this.createBatchNav("图像B", "after");
            batch.appendChild(navA.root);
            batch.appendChild(navB.root);

            const view = document.createElement("div");
            view.className = "mk-ic-view";

            const afterImg = document.createElement("img");
            afterImg.draggable = false;
            afterImg.alt = "图像B";

            const beforeImg = document.createElement("img");
            beforeImg.draggable = false;
            beforeImg.alt = "图像A";

            const handle = document.createElement("div");
            handle.className = "mk-ic-handle";
            const lineTop = document.createElement("div");
            lineTop.className = "mk-ic-line mk-ic-line-top";
            const lineBottom = document.createElement("div");
            lineBottom.className = "mk-ic-line mk-ic-line-bottom";
            const knob = document.createElement("div");
            knob.className = "mk-ic-knob";
            handle.append(lineTop, knob, lineBottom);

            const empty = document.createElement("div");
            empty.className = "mk-ic-empty";
            empty.textContent = "执行到本节点时，这里会显示图像A与图像B的对比。";

            view.append(afterImg, beforeImg, handle, empty);

            wrap.append(batch, view);

            this._wrapEl = wrap;
            this._viewEl = view;
            this._beforeImgEl = beforeImg;
            this._afterImgEl = afterImg;
            this._handleEl = handle;
            this._emptyEl = empty;
            this._batchEl = batch;
            this._navA = navA;
            this._navB = navB;

            // 鼠标在预览区内移动即拖动分割线（官方同款交互）
            const moveTo = (clientX) => {
                const rect = view.getBoundingClientRect();
                if (!rect.width) return;
                const pct = ((clientX - rect.left) / rect.width) * 100;
                this.mkPosition = Math.max(0.5, Math.min(99.5, pct));
                this.applyPosition();
            };
            view.addEventListener("mousemove", (event) => moveTo(event.clientX));
            view.addEventListener("pointerdown", (event) => {
                moveTo(event.clientX);
                view.setPointerCapture?.(event.pointerId);
            });
            view.addEventListener("pointermove", (event) => {
                if (event.buttons) moveTo(event.clientX);
            });
            // 避免拖着分割线移动时拖动整个节点
            view.addEventListener("pointerdown", (event) => event.stopPropagation());
            view.addEventListener("mousedown", (event) => event.stopPropagation());

            this.renderCompare();

            if (typeof this.addDOMWidget !== "function") {
                console.warn("[MK] 当前前端不支持 addDOMWidget，图像对比面板无法挂载");
                return;
            }

            const widget = this.addDOMWidget("mk_ic_panel", "mk_ic", wrap, {
                serialize: false,
                hideOnZoom: false,
                getValue: () => "",
                setValue: () => {},
                getMinHeight: () => MIN_PANEL_HEIGHT,
            });
            if (widget && widget.options) {
                widget.options.minNodeSize = [MIN_NODE_SIZE[0], MIN_NODE_SIZE[1]];
            }
            this._panelWidget = widget;

            this.syncPanelHeight();
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => this.syncPanelHeight());
                setTimeout(() => this.syncPanelHeight(), 80);
            }
        };

        /** 批量导航（A/B 各自 >1 张时才显示） */
        nodeType.prototype.createBatchNav = function (label, kind) {
            const root = document.createElement("div");
            root.className = "mk-ic-batchnav is-hidden";

            const text = document.createElement("span");
            text.textContent = label;

            const prev = document.createElement("button");
            prev.type = "button";
            prev.textContent = "‹";
            prev.title = "上一张";

            const index = document.createElement("span");
            index.className = "mk-ic-index";

            const next = document.createElement("button");
            next.type = "button";
            next.textContent = "›";
            next.title = "下一张";

            prev.addEventListener("click", (event) => {
                event.stopPropagation();
                this.stepBatch(kind, -1);
            });
            next.addEventListener("click", (event) => {
                event.stopPropagation();
                this.stepBatch(kind, 1);
            });

            root.append(text, prev, index, next);
            return { root, index, prev, next };
        };

        nodeType.prototype.stepBatch = function (kind, delta) {
            const list = kind === "before" ? this.mkBeforeImages : this.mkAfterImages;
            const key = kind === "before" ? "mkBeforeIndex" : "mkAfterIndex";
            if (!Array.isArray(list) || list.length < 2) return;
            this[key] = (this[key] + delta + list.length) % list.length;
            this.renderCompare();
        };

        /** 面板高度跟随节点（图片是绝对定位，不会反过来撑大节点） */
        nodeType.prototype.syncPanelHeight = function () {
            const wrap = this._wrapEl;
            const widget = this._panelWidget;
            if (!wrap || !widget || !Array.isArray(this.size)) return;

            let h = widget.computedHeight;
            if (!(typeof h === "number" && h > 0)) {
                const top = Number.isFinite(widget.y) ? widget.y : 90;
                h = this.size[1] - top - 6;
            }
            const px = Math.max(MIN_PANEL_HEIGHT, Math.round(h - 4));
            wrap.style.height = px + "px";
            wrap.style.minHeight = px + "px";
        };

        nodeType.prototype.applyPosition = function () {
            const handle = this._handleEl;
            const before = this._beforeImgEl;
            if (!handle || !before) return;

            const pos = this.mkPosition;
            // 只有两张图都在时才做分割对比；单图时整张显示、不裁切
            const hasBoth = Boolean(
                this.mkBeforeImages[this.mkBeforeIndex] && this.mkAfterImages[this.mkAfterIndex]
            );

            handle.style.display = hasBoth ? "block" : "none";
            handle.style.left = pos + "%";
            before.style.clipPath = hasBoth ? `inset(0 ${100 - pos}% 0 0)` : "none";
        };

        nodeType.prototype.updateBatchUI = function () {
            const apply = (nav, list, index) => {
                const show = Array.isArray(list) && list.length > 1;
                nav.root.classList.toggle("is-hidden", !show);
                if (!show) return;
                nav.index.textContent = `${index + 1} / ${list.length}`;
                nav.prev.disabled = index <= 0;
                nav.next.disabled = index >= list.length - 1;
            };
            apply(this._navA, this.mkBeforeImages, this.mkBeforeIndex);
            apply(this._navB, this.mkAfterImages, this.mkAfterIndex);
        };

        nodeType.prototype.renderCompare = function () {
            if (!this._viewEl) return;

            const before = this.mkBeforeImages[this.mkBeforeIndex] || "";
            const after = this.mkAfterImages[this.mkAfterIndex] || "";

            this._beforeImgEl.src = before;
            this._beforeImgEl.style.display = before ? "block" : "none";
            this._afterImgEl.src = after;
            this._afterImgEl.style.display = after ? "block" : "none";

            const hasAny = Boolean(before || after);
            this._emptyEl.hidden = hasAny;

            this.updateBatchUI();
            this.applyPosition();
        };
    },
});
