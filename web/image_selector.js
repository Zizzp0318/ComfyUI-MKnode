// MK-图像选择器 —— 前端（DOM widget 版，同时兼容旧版 LiteGraph 与 Nodes 2.0）
//
// 与旧实现的区别：
//   旧版把所有交互都画在 LiteGraph 的 canvas 上（onDrawBackground 画图、
//   onMouseDown/Move/Up 做命中检测、app.canvas.graph_mouse 取坐标）。
//   Nodes 2.0 用 Vue 渲染节点，这些 canvas hook 不再被调用，节点会变成空白。
//   现在改为 addDOMWidget + div/img 网格 + DOM 按钮，两种渲染模式行为完全一致。
//
// 保持不变：
//   - 节点类型 MK_ImageSelector、WS 事件名、后端路由 /mk_image_selector/select
//   - 选中态 selected_images 的序列化字段名（旧工作流仍可恢复）

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "MK_ImageSelector";
const ROUTE_SELECT = "/mk_image_selector/select";
const EVENT_UPDATE = "mk_image_selector_update";
const EVENT_SELECTION = "mk_image_selector_selection";
const STYLE_ID = "mk-isel-style";

// 面板是「弹性 widget」：高度跟随节点本体剩余空间，由用户拖拽决定
// （不要给 widget 设 computeSize / getHeight，否则会被判定为固定高度，节点高度被锁死）
const MIN_PANEL_HEIGHT = 200;
const MIN_NODE_SIZE = [320, 320];
const DEFAULT_NODE_SIZE = [360, 560];

// 候选图 ≤ 该数量时按原比例自适应铺排；超过则回到小方格 + 滚动
const MAX_FIT_COUNT = 4;
const CARD_GAP = 6;

// 预览排布版本号，显示在状态栏里：改了前端后用它确认浏览器加载的是新脚本
const LAYOUT_VERSION = "fit-v2";

const MODE_ALWAYS_PAUSE = "always_pause";
const MODE_PASSTHROUGH = "passthrough";

const CSS = `
.mk-isel-wrap {
    box-sizing: border-box;
    width: 100%;
    height: 100%;
    /* 兜底下限：极端情况下（父级高度不确定）也不至于塌成 0 */
    min-height: 200px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px;
    background: #1b1b1d;
    border: 1px solid #333;
    border-radius: 6px;
    font: 12px/1.4 Arial, sans-serif;
    color: #ddd;
    overflow: hidden;
}
.mk-isel-wrap[data-executing="1"] { border-color: #3fbf4a; }
.mk-isel-head {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 18px;
}
.mk-isel-status { font-weight: 600; color: #9aa0a6; }
.mk-isel-ver {
    padding: 0 5px;
    border-radius: 8px;
    background: #2a2d31;
    color: #6f757c;
    font: 10px/15px Arial, sans-serif;
}
.mk-isel-wrap[data-executing="1"] .mk-isel-status { color: #4CAF50; }
.mk-isel-count { margin-left: auto; color: #e7b94f; font-variant-numeric: tabular-nums; }
.mk-isel-grid {
    box-sizing: border-box;
    /* flex-basis 用 0（而不是 auto）：网格尺寸不再由图片内容撑开，
       否则单张大图会把 DOM 组件顶大，进而把节点高度顶大 */
    flex: 1 1 0%;
    min-height: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
    gap: 6px;
    align-content: start;
    overflow: auto;
    padding-right: 2px;
}
/* 候选图 ≤ 4 张：切到「按图片原始比例排布」模式。
   卡片宽高与位置全部由 JS 依 naturalWidth/naturalHeight 算好后写成 px，
   所以横图得到横卡、竖图得到竖卡，既不裁切也不会反过来撑大节点。 */
.mk-isel-grid.is-fit {
    display: block;
    position: relative;
    align-content: normal;
    overflow: hidden;
    padding-right: 0;
}
.mk-isel-grid.is-fit .mk-isel-card {
    position: absolute;
    aspect-ratio: auto;
    min-width: 0;
    min-height: 0;
}
.mk-isel-card {
    box-sizing: border-box;
    position: relative;
    aspect-ratio: 1 / 1;
    border: 2px solid #3a3a3a;
    border-radius: 5px;
    overflow: hidden;
    background: #111;
    cursor: pointer;
    transition: border-color .12s ease, box-shadow .12s ease;
}
.mk-isel-card:hover { border-color: #6b7077; }
.mk-isel-card img {
    /* 绝对定位：图片自身尺寸完全不参与布局计算，节点高度只由用户拖拽决定 */
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
    pointer-events: none;
}
.mk-isel-card.is-selected { border-color: #4CAF50; box-shadow: 0 0 0 1px #4CAF50 inset; }
.mk-isel-card.is-selected::after {
    content: "";
    position: absolute;
    inset: 0;
    background: rgba(76, 175, 80, .14);
    pointer-events: none;
}
.mk-isel-card.is-broken { opacity: .35; }
.mk-isel-badge {
    position: absolute;
    left: 3px;
    top: 3px;
    min-width: 15px;
    padding: 0 3px;
    border-radius: 3px;
    background: rgba(0, 0, 0, .72);
    color: #fff;
    font: 11px/15px Arial, sans-serif;
    text-align: center;
    pointer-events: none;
}
.mk-isel-card.is-selected .mk-isel-badge { background: #4CAF50; }
.mk-isel-empty {
    grid-column: 1 / -1;
    padding: 28px 12px;
    text-align: center;
    color: #7d848c;
    line-height: 1.7;
}
.mk-isel-actions { flex: none; display: flex; gap: 6px; }
.mk-isel-actions button {
    flex: 1;
    padding: 6px 8px;
    border: 1px solid #4a4d52;
    border-radius: 4px;
    background: #343b49;
    color: #eee;
    font: 12px Arial, sans-serif;
    cursor: pointer;
}
.mk-isel-actions button:hover:not(:disabled) { background: #3f4757; }
.mk-isel-actions button:disabled { opacity: .45; cursor: default; }
.mk-isel-actions button[data-act="confirm"] { background: #2f6b46; border-color: #2f6b46; }
.mk-isel-actions button[data-act="confirm"]:hover:not(:disabled) { background: #3a8053; }
.mk-isel-actions button[data-act="cancel"]:hover:not(:disabled) { background: #5a3434; }
`;

function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = CSS;
    document.head.appendChild(el);
}

function assetUrl(item) {
    const filename = encodeURIComponent(item.filename || "");
    const type = encodeURIComponent(item.type || "temp");
    const subfolder = encodeURIComponent(item.subfolder || "");
    return api.apiURL(
        `/view?filename=${filename}&type=${type}&subfolder=${subfolder}&rand=${Math.random()}`
    );
}

function findNodeById(id) {
    const graph = app?.graph;
    if (!graph) return null;
    return (
        graph._nodes_by_id?.[id] ||
        graph.getNodeById?.(id) ||
        graph.getNodeById?.(Number(id)) ||
        null
    );
}

/** 兼容取基类 serialize/configure：Nodes 2.0 下 LiteGraph 仍是图结构本体，但加一层保护 */
function baseProto() {
    return (typeof window !== "undefined" && window.LiteGraph?.LGraphNode?.prototype) || null;
}

// ── 自适应铺排布局（justified layout）─────────────────────────────────────────
// 旧实现把预览区固定切成 N 等分的格子，格子形状与图片无关：
// 一张 1440×1080 的横图被塞进竖格，即使 object-fit: contain 不裁切，
// 视觉上也只是“一根横条悬在竖框里”，看起来仍像竖幅。
// 现在枚举所有「分行方式」，给每种方式算出行高 → 逐行按宽度铺满，
// 取图片总面积最大的那种，于是卡片形状 = 图片形状。

/** 枚举 n 张图的所有「连续分行」方式（n ≤ 4 时最多 8 种） */
function enumerateRows(n) {
    const out = [];
    const walk = (start, acc) => {
        if (start === n) {
            out.push(acc.slice());
            return;
        }
        for (let end = start + 1; end <= n; end += 1) {
            acc.push([start, end]);
            walk(end, acc);
            acc.pop();
        }
    };
    walk(0, []);
    return out;
}

/**
 * 评估一种分行方式。
 * 每一行按「铺满容器宽度」反推行高：h = 可用宽 / 该行宽高比之和。
 * 所有行都铺满宽度后若总高超过容器，则整体等比缩小（此时行会变窄并居中）。
 */
function evaluateRows(items, parts, width, height, gap) {
    const rows = parts.map(([start, end]) => {
        const slice = items.slice(start, end);
        const ratioSum = slice.reduce((sum, item) => sum + item.ar, 0);
        const availWidth = width - gap * (slice.length - 1);
        return { slice, ratioSum, h: availWidth / ratioSum };
    });

    const gapTotal = gap * (rows.length - 1);
    const rawHeight = rows.reduce((sum, row) => sum + row.h, 0) + gapTotal;

    if (rawHeight > height + 0.5 && rawHeight - gapTotal > 0) {
        const scale = Math.max(0.01, (height - gapTotal) / (rawHeight - gapTotal));
        rows.forEach((row) => {
            row.h *= scale;
        });
    }

    const area = rows.reduce(
        (sum, row) => sum + row.slice.reduce((acc, item) => acc + item.ar * row.h * row.h, 0),
        0
    );

    // 只按面积选会挑出「3+1」这种突兀的分行（4 张时 3+1 与 2+2 面积几乎相同）。
    // 加一个行长度均衡惩罚，让 2+2 这类整齐排版优先。
    const counts = rows.map((row) => row.slice.length);
    const imbalance = Math.max(...counts) - Math.min(...counts);

    return { rows, area, score: area / (1 + 0.12 * imbalance * imbalance) };
}

/** 返回 { rows: [{ slice, h, x, y }] } 或 null */
function computeFitLayout(items, width, height, gap) {
    if (!items.length || width < 40 || height < 40) return null;

    let best = null;
    enumerateRows(items.length).forEach((parts) => {
        const candidate = evaluateRows(items, parts, width, height, gap);
        if (!best || candidate.score > best.score) best = candidate;
    });
    if (!best) return null;

    const totalHeight =
        best.rows.reduce((sum, row) => sum + row.h, 0) + gap * (best.rows.length - 1);

    let y = Math.max(0, (height - totalHeight) / 2);
    best.rows.forEach((row) => {
        const rowWidth =
            row.slice.reduce((sum, item) => sum + item.ar * row.h, 0) + gap * (row.slice.length - 1);
        let x = Math.max(0, (width - rowWidth) / 2);
        row.slice.forEach((item) => {
            item.w = item.ar * row.h;
            item.x = x;
            item.y = y;
            x += item.w + gap;
        });
        y += row.h + gap;
    });

    return best.rows;
}

app.registerExtension({
    name: "Comfyui_MKnode.ImageSelector",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        injectStyle();

        // 捕获注册时的原始实现：serialize / configure 必须先调用基类，
        // 否则工作流里的 id / pos / size / widgets_values 会全部丢失。
        const baseSerialize = nodeType.prototype.serialize;
        const baseConfigure = nodeType.prototype.configure;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);

            this.isChooser = true;
            this.selected_images = new Set();
            this.anti_selected = new Set();
            this.imageData = [];
            this.currentMode = MODE_ALWAYS_PAUSE;
            this.isWaitingSelection = false;
            this.isCancelling = false;
            this.isExecuting = false;

            this.buildSelectorPanel();

            if (!Array.isArray(this.size) || this.size[1] < MIN_NODE_SIZE[1]) {
                this.setSize([...DEFAULT_NODE_SIZE]);
            }

            return result;
        };

        // 节点被拖动缩放大小时，同步面板高度（在 arrange 之后，computedHeight 已更新）
        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function () {
            const result = onResize?.apply(this, arguments);
            const sync = () => this.syncPanelHeight();
            if (typeof requestAnimationFrame === "function") requestAnimationFrame(sync);
            else sync();
            return result;
        };

        // 节点删除时断开尺寸观察器，避免残留引用
        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            this._gridResizeObserver?.disconnect?.();
            this._gridResizeObserver = null;
            return onRemoved?.apply(this, arguments);
        };

        // ── 构建 DOM 面板 ──
        nodeType.prototype.buildSelectorPanel = function () {
            const wrap = document.createElement("div");
            wrap.className = "mk-isel-wrap";
            wrap.dataset.executing = "0";

            const head = document.createElement("div");
            head.className = "mk-isel-head";

            const status = document.createElement("span");
            status.className = "mk-isel-status";
            status.textContent = "等待选择";

            const count = document.createElement("span");
            count.className = "mk-isel-count";

            const version = document.createElement("span");
            version.className = "mk-isel-ver";
            version.textContent = LAYOUT_VERSION;
            version.title = "预览排布版本（用于确认前端脚本已是最新）";

            head.appendChild(status);
            head.appendChild(version);
            head.appendChild(count);

            const grid = document.createElement("div");
            grid.className = "mk-isel-grid";

            const actions = document.createElement("div");
            actions.className = "mk-isel-actions";

            const confirmBtn = document.createElement("button");
            confirmBtn.type = "button";
            confirmBtn.dataset.act = "confirm";
            confirmBtn.textContent = "确认选择";
            confirmBtn.disabled = true;
            confirmBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                this.executeSelection();
            });

            const cancelBtn = document.createElement("button");
            cancelBtn.type = "button";
            cancelBtn.dataset.act = "cancel";
            cancelBtn.textContent = "取消";
            cancelBtn.disabled = true;
            cancelBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                this.cancelSelection();
            });

            actions.appendChild(confirmBtn);
            actions.appendChild(cancelBtn);

            wrap.appendChild(head);
            wrap.appendChild(grid);
            wrap.appendChild(actions);

            this._wrapEl = wrap;
            this._gridEl = grid;
            this._statusEl = status;
            this._countEl = count;
            this._confirmBtn = confirmBtn;
            this._cancelBtn = cancelBtn;

            this.renderGrid();

            if (typeof this.addDOMWidget !== "function") {
                console.warn("[MK] 当前前端不支持 addDOMWidget，图像选择器面板无法挂载");
                return;
            }

            // 只给「最小高度」，不给固定高度 / computeSize：
            // ComfyUI 会把它当成弹性 widget，面板自动占满节点本体剩余空间，
            // 用户拖节点下边缘时面板跟着变高变矮，图片再大也不会反过来把节点撑大。
            const widget = this.addDOMWidget("mk_isel_panel", "mk_isel", wrap, {
                serialize: false,
                hideOnZoom: false,
                getValue: () => "",
                setValue: () => {},
                getMinHeight: () => MIN_PANEL_HEIGHT,
            });

            if (widget && widget.options) {
                // 节点最小尺寸（宽, 高），避免拖到面板不可见
                widget.options.minNodeSize = [MIN_NODE_SIZE[0], MIN_NODE_SIZE[1]];
            }
            this._panelWidget = widget;

            // 预览区尺寸变化（节点缩放 / 侧栏开合）时重排卡片，卡片是绝对定位，不会引发循环
            if (typeof ResizeObserver === "function" && !this._gridResizeObserver) {
                this._gridResizeObserver = new ResizeObserver(() => this.layoutCards());
                this._gridResizeObserver.observe(grid);
            }

            this.syncPanelHeight();
            // 首帧布局可能还没算完，稍后再对齐两次
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => this.syncPanelHeight());
                setTimeout(() => this.syncPanelHeight(), 80);
            }

            this.updateUI();
        };

        // ── 面板高度跟随节点 ──
        // 面板高度只由节点尺寸决定，绝不反过来由图片撑开：
        //   1) 优先用 ComfyUI 算好的 widget.computedHeight（节点本体剩余空间）；
        //   2) 拿不到就按节点高度估算（顶部标题/槽位约 90px）；
        // 同时写 height 与 minHeight —— 在 Vue 渲染下 flex 会忽略 height，
        // 但 minHeight 一定生效，这样面板既能铺满、又不会跟着图片变大。
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

            // 面板一变高变矮，预览区尺寸就变了，需要重排卡片
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => this.layoutCards());
            } else {
                this.layoutCards();
            }
        };

        // ── 渲染缩略图网格 ──
        nodeType.prototype.renderGrid = function () {
            const grid = this._gridEl;
            if (!grid) return;

            grid.replaceChildren();

            const data = Array.isArray(this.imageData) ? this.imageData : [];

            // 1～4 张：按图片原始比例自适应铺排；5 张以上：小方格 + 滚动
            const fitMode = data.length >= 1 && data.length <= MAX_FIT_COUNT;
            grid.classList.toggle("is-fit", fitMode);
            grid.style.gridTemplateColumns = "";
            grid.style.gridTemplateRows = "";

            if (!data.length) {
                const empty = document.createElement("div");
                empty.className = "mk-isel-empty";
                empty.textContent = "执行到本节点时，候选图像会显示在这里。";
                grid.appendChild(empty);
                return;
            }

            data.forEach((item, index) => {
                const card = document.createElement("div");
                card.className =
                    "mk-isel-card" + (this.selected_images.has(index) ? " is-selected" : "");
                card.dataset.index = String(index);
                card.title = `第 ${index + 1} 张`;

                const img = document.createElement("img");
                img.draggable = false;
                img.alt = `image ${index + 1}`;
                img.src = assetUrl(item);
                img.addEventListener("error", () => card.classList.add("is-broken"));
                // 图片加载完成后才知道真实宽高比，重新排一次版
                if (!img.complete) {
                    img.addEventListener("load", () => this.layoutCards());
                }

                const badge = document.createElement("span");
                badge.className = "mk-isel-badge";
                badge.textContent = String(index + 1);

                card.appendChild(img);
                card.appendChild(badge);
                card.addEventListener("click", (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    this.toggleImageSelection(index);
                });

                grid.appendChild(card);
            });

            this.layoutCards();
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => this.layoutCards());
            }
        };

        // ── 按图片真实宽高比排布卡片 ──
        // 位置与尺寸全部写成 px，卡片绝对定位，绝不参与网格尺寸计算，
        // 因此不存在「图片把节点顶大」的回环。
        nodeType.prototype.layoutCards = function () {
            const grid = this._gridEl;
            if (!grid) return;

            const cards = Array.from(grid.querySelectorAll(".mk-isel-card"));
            if (!cards.length) return;

            if (!grid.classList.contains("is-fit")) {
                cards.forEach((card) => {
                    card.style.left = "";
                    card.style.top = "";
                    card.style.width = "";
                    card.style.height = "";
                });
                return;
            }

            const width = grid.clientWidth;
            const height = grid.clientHeight;
            if (width < 40 || height < 40) return;

            const items = cards.map((card) => {
                const img = card.querySelector("img");
                const nw = img?.naturalWidth || 0;
                const nh = img?.naturalHeight || 0;
                const ar = nw > 0 && nh > 0 ? nw / nh : 1;
                return { card, ar };
            });

            const rows = computeFitLayout(items, width, height, CARD_GAP);
            if (!rows) return;

            rows.forEach((row) => {
                row.slice.forEach((item) => {
                    item.card.style.left = Math.round(item.x) + "px";
                    item.card.style.top = Math.round(item.y) + "px";
                    item.card.style.width = Math.max(1, Math.round(item.w)) + "px";
                    item.card.style.height = Math.max(1, Math.round(row.h)) + "px";
                });
            });
        };

        // ── 只刷新选中态，不重建 DOM（避免图片重新加载闪烁） ──
        nodeType.prototype.syncSelectionUI = function () {
            const grid = this._gridEl;
            if (grid) {
                grid.querySelectorAll(".mk-isel-card").forEach((card) => {
                    const index = Number(card.dataset.index);
                    card.classList.toggle("is-selected", this.selected_images.has(index));
                });
            }
            this.updateUI();
        };

        nodeType.prototype.ensurePropertiesValid = function () {
            if (!(this.selected_images instanceof Set)) {
                this.selected_images = new Set();
            }
            if (!(this.anti_selected instanceof Set)) {
                this.anti_selected = new Set();
            }
        };

        nodeType.prototype.toggleImageSelection = function (index) {
            this.ensurePropertiesValid();

            if (this.selected_images.has(index)) {
                this.selected_images.delete(index);
            } else {
                this.selected_images.add(index);
            }

            this.syncSelectionUI();
        };

        // ── 状态栏与按钮 ──
        nodeType.prototype.updateUI = function () {
            if (!this._statusEl) return;

            this.ensurePropertiesValid();

            const selectedCount = this.selected_images.size;
            const totalCount = Array.isArray(this.imageData) ? this.imageData.length : 0;
            const confirmBtn = this._confirmBtn;
            const cancelBtn = this._cancelBtn;

            if (this.isCancelling) {
                this._statusEl.textContent = "正在取消…";
                this._countEl.textContent = "";
                confirmBtn.textContent = "确认选择";
                confirmBtn.disabled = true;
                cancelBtn.textContent = "取消";
                cancelBtn.disabled = true;
            } else if (this.isWaitingSelection) {
                this._statusEl.textContent = "等待选择";
                this._countEl.textContent = totalCount ? `${selectedCount} / ${totalCount}` : "";
                confirmBtn.textContent =
                    selectedCount > 1 ? `确认选择 (${selectedCount})` : "确认选择";
                confirmBtn.disabled = selectedCount === 0;
                cancelBtn.textContent = "取消运行";
                cancelBtn.disabled = false;
            } else {
                const modeText =
                    { [MODE_ALWAYS_PAUSE]: "等待选择", [MODE_PASSTHROUGH]: "自动通过" }[
                        this.currentMode
                    ] || "未知模式";
                this._statusEl.textContent = modeText;
                this._countEl.textContent = totalCount ? `${totalCount} 张` : "";
                confirmBtn.textContent = "确认选择";
                confirmBtn.disabled = true;
                cancelBtn.textContent = "取消";
                cancelBtn.disabled = true;
            }
        };

        nodeType.prototype.setExecutingState = function (isExecuting) {
            this.isExecuting = Boolean(isExecuting);
            if (this._wrapEl) {
                this._wrapEl.dataset.executing = this.isExecuting ? "1" : "0";
            }
            this.updateUI();
        };

        // ── 提交 / 取消 ──
        nodeType.prototype.executeSelection = function () {
            if (!this.isWaitingSelection) return;

            this.ensurePropertiesValid();

            const selectedIndices = Array.from(this.selected_images);

            fetch(ROUTE_SELECT, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    node_id: this.id.toString(),
                    action: "select",
                    selected_indices: selectedIndices,
                }),
            })
                .then((response) => response.json())
                .then((data) => {
                    if (!data.success) {
                        console.error("[MK] 选择请求失败:", data.error);
                    }
                })
                .catch((error) => {
                    console.error("[MK] 选择请求异常:", error);
                });

            this.isWaitingSelection = false;
            this.setExecutingState(false);
        };

        nodeType.prototype.cancelSelection = function () {
            if (!this.isWaitingSelection) return;

            this.isCancelling = true;
            this.updateUI();

            fetch(ROUTE_SELECT, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    node_id: this.id.toString(),
                    action: "cancel",
                    selected_indices: [],
                }),
            })
                .then((response) => response.json())
                .then((data) => {
                    if (!data.success) {
                        console.error("[MK] 取消请求失败:", data.error);
                    }
                })
                .catch((error) => {
                    console.error("[MK] 取消请求异常:", error);
                })
                .finally(() => {
                    this.isCancelling = false;
                    this.setExecutingState(false);
                });
        };

        // ── 序列化：保留选中态，字段名与旧版一致 ──
        nodeType.prototype.serialize = function () {
            const proto = baseProto();
            const fn = proto?.serialize || baseSerialize;
            const data = fn ? fn.call(this) : {};

            data.isWaitingSelection = this.isWaitingSelection;
            data.currentMode = this.currentMode;

            if (this.selected_images && this.selected_images.size > 0) {
                data.selected_images = Array.from(this.selected_images);
            }

            data.isExecuting = this.isExecuting || false;

            return data;
        };

        nodeType.prototype.configure = function (data) {
            const proto = baseProto();
            const fn = proto?.configure || baseConfigure;
            if (fn) {
                fn.call(this, data);
            }

            this.isWaitingSelection = data.isWaitingSelection || false;
            this.currentMode = data.currentMode || MODE_ALWAYS_PAUSE;

            this.ensurePropertiesValid();
            this.selected_images.clear();
            if (data.selected_images && Array.isArray(data.selected_images)) {
                data.selected_images.forEach((index) => {
                    this.selected_images.add(index);
                });
            }

            if (this._gridEl) {
                this.renderGrid();
            }
            this.updateUI();
            // 加载工作流时尺寸来自存档，重新对齐面板高度
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => this.syncPanelHeight());
            }

            if (data.isExecuting) {
                setTimeout(() => this.setExecutingState(true), 100);
            }
        };
    },

    setup() {
        console.info(`[MK] MK-图像选择器 已加载，预览排布版本 ${LAYOUT_VERSION}`);
        const originalInterrupt = api.interrupt;

        api.interrupt = function () {
            const graph = app?.graph;
            if (graph?._nodes_by_id) {
                Object.values(graph._nodes_by_id).forEach((node) => {
                    if (node?.isChooser && node.isWaitingSelection) {
                        node.cancelSelection("interrupt");
                    }
                });
            }

            return originalInterrupt.apply(this, arguments);
        };

        api.addEventListener(EVENT_UPDATE, (event) => {
            const data = event.detail || {};
            const node = findNodeById(data.id);

            if (!node || !node.isChooser) return;

            node.setExecutingState(false);

            const urls = Array.isArray(data.urls) ? data.urls : [];
            node.imageData = urls.map((url, index) => ({
                index,
                filename: url.filename,
                subfolder: url.subfolder,
                type: url.type,
            }));

            const modeWidget = node.widgets?.find((w) => w.name === "mode");
            const currentMode = modeWidget ? modeWidget.value : MODE_ALWAYS_PAUSE;

            node.currentMode = currentMode;
            node.isWaitingSelection = currentMode === MODE_ALWAYS_PAUSE;
            node.isCancelling = false;

            node.ensurePropertiesValid();
            node.selected_images.clear();
            node.anti_selected.clear();

            node.renderGrid();
            node.updateUI();

            if (currentMode === MODE_ALWAYS_PAUSE) {
                node.setExecutingState(true);
            }
        });

        api.addEventListener(EVENT_SELECTION, (event) => {
            const data = event.detail || {};
            const node = findNodeById(data.id);
            if (!node || !node.isChooser) return;

            node.isWaitingSelection = false;
            node.isCancelling = false;

            if (Array.isArray(data.selected_indices)) {
                node.ensurePropertiesValid();
                node.selected_images.clear();
                data.selected_indices.forEach((index) => node.selected_images.add(index));
            }

            node.syncSelectionUI();
        });
    },
});
