// Comfyui_MKnode —— MK-禁用多框 / MK-忽略多框 前端
//
// 迁移自 rgthree-comfy 的 Fast Groups Muter / Fast Groups Bypasser
// （src_web/comfyui/fast_groups_muter.ts + fast_groups_bypasser.ts + services/fast_groups_service.ts）。
//
// 上游是**纯前端虚拟节点**：靠 canvas 自绘 widget + LiteGraph 注册。这在 Nodes 2.0
// （Vue 渲染）下有两个硬伤——① 节点菜单来自后端 /object_info，虚拟节点不一定出现；
// ② 自绘 widget 的 draw/mouse 钩子不再被调用，面板会空白。
//
// 本实现的做法：
// - 后端补了零输入零输出的空节点（nodes/fast_groups.py），菜单里一定能看到；
// - 面板完全用 DOM 画（addDOMWidget），列表行是真实按钮，两种渲染模式通用；
// - 分组收集、成员判定、模式切换、排序/过滤/开关规则等业务逻辑逐条对齐上游。
//
// 命名隔离：扩展名带包前缀；CSS 类前缀 mk-fg-；节点属性键沿用上游同名（属性只属于本节点）。

import { app } from "../../scripts/app.js";

const STYLE_ID = "mk-fg-style";

// 面板版本：v2 = 修掉「切工作流后分组算不出成员（全灰、点了没反应）」
const PANEL_VERSION = "v2";

// LiteGraph 的节点模式常量
const MODE_ON = 0; // ALWAYS
const MODE_NEVER = 2; // 禁用（Mute）
const MODE_BYPASS = 4; // 忽略（ComfyUI 的 Bypass）

const MIN_PANEL_HEIGHT = 150;
const MIN_NODE_SIZE = [300, 300];
const DEFAULT_NODE_SIZE = [340, 430];
const REFRESH_MS = 700;

// 节点属性键（与上游保持一致，方便对照文档）
const P = {
    matchColors: "matchColors",
    matchTitle: "matchTitle",
    showNav: "showNav",
    showAllGraphs: "showAllGraphs",
    sort: "sort",
    customSortAlphabet: "customSortAlphabet",
    toggleRestriction: "toggleRestriction",
};

const PROPERTY_DEFAULTS = {
    [P.matchColors]: "",
    [P.matchTitle]: "",
    [P.showNav]: true,
    [P.showAllGraphs]: true,
    [P.sort]: "position",
    [P.customSortAlphabet]: "",
    [P.toggleRestriction]: "default",
};

// 两种节点只差「关掉时改成什么模式」与几个中文标签
const TYPE_CONFIG = {
    MK_FastGroupsMuter: {
        offMode: MODE_NEVER,
        onText: "启用",
        offText: "禁用",
        offAllText: "全部禁用",
        unit: "禁用",
    },
    MK_FastGroupsBypasser: {
        offMode: MODE_BYPASS,
        onText: "启用",
        offText: "忽略",
        offAllText: "全部忽略",
        unit: "忽略",
    },
};

const CSS = `
.mk-fg-wrap {
    box-sizing: border-box;
    width: 100%;
    height: 100%;
    min-height: 150px;
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 6px;
    background: #1b1b1d;
    border: 1px solid #333;
    border-radius: 6px;
    font: 12px/1.4 Arial, "Microsoft YaHei", sans-serif;
    color: #ddd;
    overflow: hidden;
}
.mk-fg-head {
    flex: none;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: #9aa0a6;
}
.mk-fg-head .mk-fg-count { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mk-fg-head button {
    width: 20px; height: 20px; padding: 0; line-height: 1;
    border: 1px solid #4a4d52; border-radius: 3px;
    background: #2a2d31; color: #cfd3d8; font-size: 12px; cursor: pointer;
}
.mk-fg-head button:hover { background: #34383d; }
.mk-fg-head button.is-on { border-color: #6d8fb8; color: #cfe4ff; }
.mk-fg-actions { flex: none; display: flex; gap: 5px; }
.mk-fg-actions button {
    flex: 1 1 0;
    height: 22px;
    padding: 0 4px;
    border: 1px solid #4a4d52;
    border-radius: 3px;
    background: #2a2d31;
    color: #cfd3d8;
    font: 11px Arial, "Microsoft YaHei", sans-serif;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.mk-fg-actions button:hover { background: #34383d; color: #fff; }
.mk-fg-settings {
    flex: none;
    display: none;
    flex-direction: column;
    gap: 4px;
    padding: 6px;
    border: 1px solid #3a3d42;
    border-radius: 4px;
    background: #232528;
}
.mk-fg-settings.is-open { display: flex; }
.mk-fg-field { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #9aa0a6; }
.mk-fg-field > span { flex: none; width: 58px; }
.mk-fg-field > input, .mk-fg-field > select {
    flex: 1 1 0;
    min-width: 0;
    height: 20px;
    padding: 0 4px;
    border: 1px solid #45484d;
    border-radius: 3px;
    background: #1b1b1d;
    color: #ddd;
    font: 11px Arial, "Microsoft YaHei", sans-serif;
}
.mk-fg-check { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #9aa0a6; cursor: pointer; }
.mk-fg-check input { margin: 0; }
.mk-fg-list {
    flex: 1 1 0%;
    min-height: 0;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding-right: 2px;
}
.mk-fg-row {
    flex: none;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 2px 4px;
    border: 1px solid #3a3d42;
    border-radius: 4px;
    background: #26282b;
    cursor: pointer;
    user-select: none;
}
.mk-fg-row:hover { border-color: #565b61; background: #2c2f33; }
.mk-fg-row.is-on { border-color: #4d6b8a; background: #2a3340; }
.mk-fg-switch {
    flex: none;
    width: 40px;
    height: 18px;
    padding: 0;
    border: 1px solid #4a4d52;
    border-radius: 9px;
    background: #333639;
    color: #9aa0a6;
    font: 10px Arial, "Microsoft YaHei", sans-serif;
    cursor: pointer;
}
.mk-fg-row.is-on .mk-fg-switch { border-color: #6d8fb8; background: #3f5a78; color: #eaf3ff; }
.mk-fg-name {
    flex: 1 1 0;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11px;
    color: #c8ccd1;
}
.mk-fg-row.is-on .mk-fg-name { color: #eef4fb; }
.mk-fg-nav {
    flex: none;
    width: 18px;
    height: 18px;
    padding: 0;
    line-height: 1;
    border: 1px solid #45484d;
    border-radius: 3px;
    background: transparent;
    color: #8f959b;
    font-size: 11px;
    cursor: pointer;
}
.mk-fg-nav:hover { color: #cfe4ff; border-color: #6d8fb8; }
.mk-fg-empty {
    flex: 1 1 0%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #6d7278;
    font-size: 11px;
    text-align: center;
    padding: 8px;
}
`;

function injectStyle() {
    if (typeof document === "undefined") return;
    if (document.getElementById(STYLE_ID)) return;
    const el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = CSS;
    document.head.appendChild(el);
}

// ─────────────────────────── 图结构工具 ───────────────────────────

/** 当前画布上的图（Nodes 2.0 下 app.canvas 可能没有 getCurrentGraph，回落到 app.graph） */
function currentGraph() {
    return app.canvas?.getCurrentGraph?.() || app.graph;
}

function nodesOf(graph) {
    return graph?._nodes || graph?.nodes || [];
}

function nodesOfGroups(graph) {
    return graph?._groups || graph?.groups || [];
}

/**
 * 节点包围盒 [x, y, w, h]。
 *
 * **这里不能用 `node.getBounding()`**：它读的是 `boundingRect`，而 `boundingRect`
 * 只在「画布真正绘制到该节点的那一帧」才由 `measure()` 更新；节点不在可视区、
 * 或前端切到别的工作流标签再切回来时，它还是初始的 `[0,0,0,0]`。
 * 一旦所有节点都算出 0 尺寸的框，任何分组都算不出成员——面板会整片变灰，
 * 点开关也不会有任何反应（进一次子图再退出来触发重绘才恢复）。
 *
 * `measure()` 不依赖渲染，直接用 pos/size 现算，任何时候都准。
 */
function boundingOf(node) {
    if (node && typeof node.measure === "function") {
        const out = [0, 0, 0, 0];
        try {
            node.measure(out, app.canvas?.ctx);
            if (out.every((v) => Number.isFinite(v)) && (out[2] > 0 || out[3] > 0)) return out;
        } catch (e) {
            /* 忽略：退回 pos/size */
        }
    }
    // 老前端没有 measure 时退回 getBounding，最后退回 pos/size
    try {
        if (typeof node?.getBounding === "function") {
            const b = node.getBounding();
            const arr = [Number(b?.[0]), Number(b?.[1]), Number(b?.[2]), Number(b?.[3])];
            if (arr.every((v) => Number.isFinite(v)) && (arr[2] > 0 || arr[3] > 0)) return arr;
        }
    } catch (e) {
        /* 忽略 */
    }
    const pos = node?.pos || [0, 0];
    const size = node?.size || [0, 0];
    return [Number(pos[0]) || 0, Number(pos[1]) || 0, Number(size[0]) || 0, Number(size[1]) || 0];
}

/** 分组包围盒；_bounding 可能是数组，也可能是 {0,1,2,3} 类对象 */
function boundingOfGroup(group) {
    // 优先 getBounding()：新版 litegraph 的 _bounding 是布局 store 的视图，
    // 切工作流后要先同步一次才拿到当前值
    try {
        if (typeof group?.getBounding === "function") {
            const b = group.getBounding();
            if (b) {
                const arr = [Number(b[0]), Number(b[1]), Number(b[2] ?? b.width), Number(b[3] ?? b.height)];
                if (arr.every((v) => Number.isFinite(v)) && (arr[2] > 0 || arr[3] > 0)) return arr;
            }
        }
    } catch (e) {
        /* 忽略：继续读字段 */
    }
    const raw = group?._bounding || group?.bounding || group?._size;
    if (!raw) {
        const pos = group?.pos || group?._pos || [0, 0];
        const size = group?.size || group?._size || [0, 0];
        return [Number(pos[0]) || 0, Number(pos[1]) || 0, Number(size[0]) || 0, Number(size[1]) || 0];
    }
    const w = raw[2] ?? raw.width ?? 0;
    const h = raw[3] ?? raw.height ?? 0;
    return [Number(raw[0]) || 0, Number(raw[1]) || 0, Number(w) || 0, Number(h) || 0];
}

/**
 * 一次刷新内复用同一份包围盒，避免 G 个分组把 N 个节点各算一遍（O(G·N) → O(N)）。
 * 轮询每 700ms 跑一次，这个优化在几百节点的工作流上差别明显。
 */
function makeBoundingReader() {
    const cache = new Map();
    return (node) => {
        let value = cache.get(node);
        if (!value) {
            value = boundingOf(node);
            cache.set(node, value);
        }
        return value;
    };
}

/** 某个分组内的直接节点（按「节点中心落在分组框内」判定，与上游一致） */
function membersOf(group, readBounding) {
    const read = readBounding || boundingOf;
    const graph = group?.graph || currentGraph();
    const box = boundingOfGroup(group);
    const [gx, gy, gw, gh] = box;
    if (!(gw > 0 || gh > 0)) return [];
    return nodesOf(graph).filter((node) => {
        const b = read(node);
        const cx = b[0] + b[2] * 0.5;
        const cy = b[1] + b[3] * 0.5;
        return cx >= gx && cx < gx + gw && cy >= gy && cy < gy + gh;
    });
}

/** 深度遍历子图，返回节点与它所在子图的节点（模式切换要连子图内部一起改） */
function forEachNodeDeep(nodes, fn) {
    const stack = [...nodes];
    const seen = new Set();
    while (stack.length) {
        const node = stack.pop();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        fn(node);
        const sub = node.subgraph || node.subGraph;
        if (sub) {
            const children = nodesOf(sub);
            for (let i = children.length - 1; i >= 0; i--) stack.push(children[i]);
        }
    }
}

/** 把若干节点（含子图内部）整体设为某个模式 */
function setModeDeep(nodes, mode) {
    forEachNodeDeep(nodes, (node) => {
        node.mode = mode;
    });
}

/** 分组是否「至少有一个节点处于启用状态」 */
function groupIsOn(members) {
    return members.some((node) => node.mode === MODE_ON);
}

/** 收集所有分组：当前图 + （可选）各级子图里的分组 */
function collectGroups(includeSubGraphs) {
    const root = currentGraph();
    const result = [];
    const seenGraph = new Set();

    const walk = (graph, depth) => {
        if (!graph || seenGraph.has(graph) || depth > 16) return;
        seenGraph.add(graph);
        for (const group of nodesOfGroups(graph)) {
            if (!group) continue;
            result.push({ group, graph });
        }
        if (!includeSubGraphs) return;
        for (const node of nodesOf(graph)) {
            const sub = node?.subgraph || node?.subGraph;
            if (sub) walk(sub, depth + 1);
        }
    };
    walk(root, 0);
    return result;
}

/** 颜色归一化：支持 ComfyUI 预设色名与 #abc / #aabbcc */
function normalizeColor(color) {
    let value = String(color || "").trim().toLowerCase();
    if (!value) return "";
    const preset = globalThis.LGraphCanvas?.node_colors?.[value];
    if (preset?.groupcolor) value = String(preset.groupcolor).toLowerCase();
    value = value.replace("#", "");
    if (value.length === 3) value = value.replace(/(.)(.)(.)/, "$1$1$2$2$3$3");
    return value ? `#${value}` : "";
}

/** 自定义字母表排序：按前缀匹配，没匹配上的排后面 */
function compareByCustomAlphabet(aTitle, bTitle, alphabet) {
    const a = String(aTitle || "").toLocaleLowerCase();
    const b = String(bTitle || "").toLocaleLowerCase();
    const indexOf = (title) => {
        for (const [index, alpha] of alphabet.entries()) {
            if (alpha && title.startsWith(alpha)) return index;
        }
        return -1;
    };
    const ai = indexOf(a);
    const bi = indexOf(b);
    if (ai > -1 && bi > -1) {
        return ai === bi ? a.localeCompare(b) : ai - bi;
    }
    if (ai > -1) return -1;
    if (bi > -1) return 1;
    return a.localeCompare(b);
}

// ─────────────────────────── 组件注册 ───────────────────────────

// 同一时间可能有多个本类节点，用一个轮询统一刷新（上游也用同一个思路的 service）
const activeNodes = new Set();
let pollTimer = null;

function ensurePolling() {
    if (pollTimer || typeof setInterval !== "function") return;
    pollTimer = setInterval(() => {
        for (const node of activeNodes) {
            try {
                node.mkFgRefresh?.();
            } catch (e) {
                console.warn("[MK] 分组面板刷新失败", e);
            }
        }
    }, REFRESH_MS);
}

function stopPollingIfIdle() {
    if (activeNodes.size || !pollTimer) return;
    clearInterval(pollTimer);
    pollTimer = null;
}

// 便于确认前端脚本已刷新（浏览器缓存旧文件时不会打印这一行）
if (typeof console !== "undefined") {
    console.info(`[MK] MK-禁用多框 / MK-忽略多框 已加载（分组面板 ${PANEL_VERSION}）`);
}

app.registerExtension({
    name: "Comfyui_MKnode.FastGroups",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        const config = TYPE_CONFIG[nodeData?.name];
        if (!config) return;

        // ── 属性初始化 ──
        nodeType.prototype.mkFgInitProperties = function () {
            this.properties = this.properties || {};
            for (const [key, value] of Object.entries(PROPERTY_DEFAULTS)) {
                if (this.properties[key] === undefined) this.properties[key] = value;
            }
        };

        /** 读属性，类型不对时回落到默认值 */
        nodeType.prototype.mkFgProp = function (key) {
            const value = this.properties?.[key];
            if (value === undefined || value === null) return PROPERTY_DEFAULTS[key];
            return value;
        };

        // ── 面板构建 ──
        nodeType.prototype.mkFgBuildPanel = function () {
            injectStyle();

            const wrap = document.createElement("div");
            wrap.className = "mk-fg-wrap";

            // 顶部：分组数量 + 设置开关
            const head = document.createElement("div");
            head.className = "mk-fg-head";
            const count = document.createElement("span");
            count.className = "mk-fg-count";
            count.textContent = "分组 0 个";
            const gear = document.createElement("button");
            gear.type = "button";
            gear.textContent = "⚙";
            gear.title = "设置：排序、过滤、开关规则";
            gear.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                settings.classList.toggle("is-open");
                gear.classList.toggle("is-on", settings.classList.contains("is-open"));
            });
            head.appendChild(count);
            head.appendChild(gear);

            // 批量操作
            const actions = document.createElement("div");
            actions.className = "mk-fg-actions";
            const makeAction = (label, title, handler) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.textContent = label;
                btn.title = title;
                btn.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    handler();
                });
                actions.appendChild(btn);
                return btn;
            };
            makeAction("全部启用", "把所有分组的节点都恢复启用", () => this.mkFgEnableAll());
            makeAction(config.offAllText, `把所有分组的节点都${config.unit}`, () => this.mkFgDisableAll());
            makeAction("反转", "启用与关闭互换", () => this.mkFgToggleAll());

            // 设置区
            const settings = this.mkFgBuildSettings();

            // 分组列表
            const list = document.createElement("div");
            list.className = "mk-fg-list";

            const empty = document.createElement("div");
            empty.className = "mk-fg-empty";
            empty.textContent = "当前画布上还没有分组。用 Ctrl+G 选中若干节点即可建组。";

            wrap.appendChild(head);
            wrap.appendChild(actions);
            wrap.appendChild(settings);
            wrap.appendChild(list);
            wrap.appendChild(empty);

            // 避免点按面板时拖动节点
            wrap.addEventListener("pointerdown", (event) => event.stopPropagation());
            wrap.addEventListener("mousedown", (event) => event.stopPropagation());

            this._mkFgWrap = wrap;
            this._mkFgCountEl = count;
            this._mkFgListEl = list;
            this._mkFgEmptyEl = empty;
            this._mkFgRows = [];

            if (typeof this.addDOMWidget !== "function") {
                console.warn("[MK] 当前前端不支持 addDOMWidget，分组面板无法挂载");
                return;
            }

            const widget = this.addDOMWidget("mk_fg_panel", "mk_fg", wrap, {
                serialize: false,
                hideOnZoom: false,
                getValue: () => "",
                setValue: () => {},
                getMinHeight: () => MIN_PANEL_HEIGHT,
            });
            if (widget?.options) widget.options.minNodeSize = [MIN_NODE_SIZE[0], MIN_NODE_SIZE[1]];
            this._mkFgWidget = widget;

            this.mkFgSyncPanelHeight();
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => this.mkFgSyncPanelHeight());
                setTimeout(() => this.mkFgSyncPanelHeight(), 80);
            }
        };

        /** 设置区：所有可调项都写回 node.properties，随工作流保存 */
        nodeType.prototype.mkFgBuildSettings = function () {
            const root = document.createElement("div");
            root.className = "mk-fg-settings";

            const addField = (label, input) => {
                const row = document.createElement("label");
                row.className = "mk-fg-field";
                const span = document.createElement("span");
                span.textContent = label;
                row.appendChild(span);
                row.appendChild(input);
                root.appendChild(row);
                return input;
            };
            const addCheck = (label, key) => {
                const row = document.createElement("label");
                row.className = "mk-fg-check";
                const input = document.createElement("input");
                input.type = "checkbox";
                input.dataset.k = key;
                input.addEventListener("change", () => {
                    this.properties[key] = Boolean(input.checked);
                    this.mkFgRefresh(true);
                });
                const span = document.createElement("span");
                span.textContent = label;
                row.appendChild(input);
                row.appendChild(span);
                root.appendChild(row);
                return input;
            };
            const addSelect = (label, key, options) => {
                const select = document.createElement("select");
                select.dataset.k = key;
                for (const [value, text] of options) {
                    const option = document.createElement("option");
                    option.value = value;
                    option.textContent = text;
                    select.appendChild(option);
                }
                select.addEventListener("change", () => {
                    this.properties[key] = select.value;
                    this.mkFgRefresh(true);
                });
                addField(label, select);
                return select;
            };
            const addText = (label, key, placeholder) => {
                const input = document.createElement("input");
                input.type = "text";
                input.dataset.k = key;
                input.placeholder = placeholder || "";
                input.addEventListener("input", () => {
                    this.properties[key] = input.value;
                    this.mkFgRefresh(true);
                });
                addField(label, input);
                return input;
            };

            this._mkFgSortEl = addSelect("排序", P.sort, [
                ["position", "按位置"],
                ["alphanumeric", "按名称"],
                ["custom alphabet", "自定义字母"],
            ]);
            this._mkFgAlphaEl = addText("自定义字母", P.customSortAlphabet, "如 zyx 或 sdxl,pro,sd");
            this._mkFgTitleEl = addText("标题过滤", P.matchTitle, "支持正则");
            this._mkFgColorEl = addText("颜色过滤", P.matchColors, "如 #3f789e,red");
            this._mkFgRestrictionEl = addSelect("开关规则", P.toggleRestriction, [
                ["default", "默认"],
                ["max one", "最多一个"],
                ["always one", "始终一个"],
            ]);
            this._mkFgNavEl = addCheck("显示跳转箭头", P.showNav);
            this._mkFgGraphsEl = addCheck("包含子图分组", P.showAllGraphs);

            return root;
        };

        /** 设置控件的值从 properties 同步回来（加载工作流后需要） */
        nodeType.prototype.mkFgSyncSettings = function () {
            const set = (el, value) => {
                if (!el) return;
                if (el.type === "checkbox") el.checked = Boolean(value);
                else el.value = String(value ?? "");
            };
            set(this._mkFgSortEl, this.mkFgProp(P.sort));
            set(this._mkFgAlphaEl, this.mkFgProp(P.customSortAlphabet));
            set(this._mkFgTitleEl, this.mkFgProp(P.matchTitle));
            set(this._mkFgColorEl, this.mkFgProp(P.matchColors));
            set(this._mkFgRestrictionEl, this.mkFgProp(P.toggleRestriction));
            set(this._mkFgNavEl, this.mkFgProp(P.showNav));
            set(this._mkFgGraphsEl, this.mkFgProp(P.showAllGraphs));
        };

        /** 面板高度跟着节点走：内容在内部滚动，不反过来把节点顶大 */
        nodeType.prototype.mkFgSyncPanelHeight = function () {
            const wrap = this._mkFgWrap;
            const widget = this._mkFgWidget;
            if (!wrap || !widget || !Array.isArray(this.size)) return;

            let h = widget.computedHeight;
            if (!(typeof h === "number" && h > 0)) {
                const top = Number.isFinite(widget.y) ? widget.y : 90;
                h = this.size[1] - top - 6;
            }
            const px = Math.max(MIN_PANEL_HEIGHT, Math.round(h - 4));
            wrap.style.height = `${px}px`;
            wrap.style.minHeight = `${px}px`;
        };

        // ── 分组列表 ──
        /** 按属性过滤 + 排序，得到要显示的分组 */
        nodeType.prototype.mkFgEntries = function () {
            const includeSub = this.mkFgProp(P.showAllGraphs) !== false;
            let groups = collectGroups(includeSub);

            // 颜色过滤
            const colorFilter = String(this.mkFgProp(P.matchColors) || "")
                .split(",")
                .map((c) => normalizeColor(c))
                .filter(Boolean);
            if (colorFilter.length) {
                groups = groups.filter(({ group }) => {
                    const color = normalizeColor(group.color);
                    return color && colorFilter.includes(color);
                });
            }

            // 标题过滤（支持正则；写错了就当不过滤，并提示一次）
            const titlePattern = String(this.mkFgProp(P.matchTitle) || "").trim();
            if (titlePattern) {
                let regex = null;
                try {
                    regex = new RegExp(titlePattern, "i");
                } catch (e) {
                    if (!this._mkFgBadRegex) {
                        this._mkFgBadRegex = true;
                        console.warn("[MK] 标题过滤不是合法正则，已忽略：", titlePattern);
                    }
                    regex = null;
                }
                if (regex) groups = groups.filter(({ group }) => regex.test(String(group.title || "")));
            } else {
                this._mkFgBadRegex = false;
            }

            // 排序
            const sort = String(this.mkFgProp(P.sort) || "position");
            if (sort === "alphanumeric") {
                groups.sort((a, b) => String(a.group.title || "").localeCompare(String(b.group.title || "")));
            } else if (sort === "custom alphabet") {
                const raw = String(this.mkFgProp(P.customSortAlphabet) || "").replace(/\n/g, "");
                const alphabet = raw
                    ? (raw.includes(",") ? raw.toLocaleLowerCase().split(",") : raw.toLocaleLowerCase().trim().split(""))
                          .map((a) => a.trim())
                          .filter(Boolean)
                    : [];
                if (alphabet.length) {
                    groups.sort((a, b) => compareByCustomAlphabet(a.group.title, b.group.title, alphabet));
                } else {
                    groups.sort((a, b) => String(a.group.title || "").localeCompare(String(b.group.title || "")));
                }
            } else {
                const step = (value) => Math.floor((Number(value) || 0) / 30);
                groups.sort((a, b) => {
                    const ay = step(boundingOfGroup(a.group)[1]);
                    const by = step(boundingOfGroup(b.group)[1]);
                    if (ay === by) {
                        return step(boundingOfGroup(a.group)[0]) - step(boundingOfGroup(b.group)[0]);
                    }
                    return ay - by;
                });
            }

            // 同一轮里所有分组共用一份包围盒缓存
            const readBounding = makeBoundingReader();
            return groups.map(({ group, graph }) => {
                const members = membersOf(group, readBounding);
                return {
                    key: `${graph?.id ?? "g"}:${group.title ?? ""}`,
                    group,
                    graph,
                    members,
                    on: groupIsOn(members),
                };
            });
        };

        /** 重建行元素 */
        nodeType.prototype.mkFgRenderRows = function (entries) {
            const list = this._mkFgListEl;
            if (!list) return;
            list.replaceChildren();
            this._mkFgRows = [];

            entries.forEach((entry, index) => {
                const row = document.createElement("div");
                row.className = "mk-fg-row";
                row.dataset.index = String(index);

                const toggle = document.createElement("button");
                toggle.type = "button";
                toggle.className = "mk-fg-switch";
                toggle.textContent = entry.on ? config.onText : config.offText;

                const name = document.createElement("span");
                name.className = "mk-fg-name";
                name.textContent = entry.group.title || "(未命名分组)";
                name.title = entry.group.title || "";

                row.appendChild(toggle);
                row.appendChild(name);

                if (this.mkFgProp(P.showNav) !== false) {
                    const nav = document.createElement("button");
                    nav.type = "button";
                    nav.className = "mk-fg-nav";
                    nav.textContent = "↗";
                    nav.title = "跳转到该分组";
                    nav.addEventListener("click", (event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        this.mkFgFocusGroup(entry.group);
                    });
                    row.appendChild(nav);
                }

                row.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    this.mkFgChange(entry.group, undefined, false);
                });

                list.appendChild(row);
                this._mkFgRows.push({ el: row, toggle, entry });
            });

            this.mkFgUpdateRows();
        };

        /** 只更新行的开关状态，不重建 DOM（避免闪烁与悬停丢失） */
        nodeType.prototype.mkFgUpdateRows = function () {
            for (const row of this._mkFgRows || []) {
                row.el.classList.toggle("is-on", Boolean(row.entry.on));
                row.toggle.textContent = row.entry.on ? config.onText : config.offText;
                row.toggle.setAttribute("aria-pressed", row.entry.on ? "true" : "false");
            }
        };

        /**
         * 刷新面板。
         * @param force 为 true 时无条件重建行（改设置后需要）
         */
        nodeType.prototype.mkFgRefresh = function (force) {
            if (!this._mkFgListEl) return;

            const entries = this.mkFgEntries();

            // 分组的「身份序列」变了才重建 DOM（顺序、数量、标题）
            const keySeq = entries.map((e) => e.key).join("|");
            const needRebuild = force || keySeq !== this._mkFgKeySeq;
            this._mkFgKeySeq = keySeq;

            if (needRebuild) {
                this.mkFgRenderRows(entries);
            } else {
                // 复用行元素，只把最新的 entry 挂回去（members/on 已重算）
                this._mkFgRows.forEach((row, index) => {
                    row.entry = entries[index] || row.entry;
                });
                this.mkFgUpdateRows();
            }

            if (this._mkFgCountEl) {
                if (!entries.length) {
                    this._mkFgCountEl.textContent = "分组 0 个";
                } else {
                    const onCount = entries.filter((e) => e.on).length;
                    this._mkFgCountEl.textContent = `分组 ${entries.length} 个 · 已启用 ${onCount}`;
                }
            }

            const hasGroups = entries.length > 0;
            this._mkFgListEl.style.display = hasGroups ? "" : "none";
            if (this._mkFgEmptyEl) this._mkFgEmptyEl.style.display = hasGroups ? "none" : "";
        };

        // ── 模式切换 ──
        /**
         * 切换某个分组。
         * @param group 分组对象
         * @param force 指定目标状态；不传则取反
         * @param skipOtherCheck 批量操作时跳过「开关规则」的联动
         */
        nodeType.prototype.mkFgChange = function (group, force, skipOtherCheck) {
            const members = membersOf(group);
            const restriction = String(this.mkFgProp(P.toggleRestriction) || "default");
            let newValue = force !== undefined ? Boolean(force) : !groupIsOn(members);

            if (!skipOtherCheck) {
                if (newValue && restriction.includes(" one")) {
                    // 最多一个 / 始终一个：打开这个就把别的都关掉
                    for (const entry of this.mkFgEntries()) {
                        if (entry.group === group) continue;
                        if (entry.on) this.mkFgChange(entry.group, false, true);
                    }
                } else if (!newValue && restriction === "always one") {
                    // 始终一个：允许关，但前提是还有别的开着
                    const othersOn = this.mkFgEntries().some((e) => e.group !== group && e.on);
                    if (!othersOn) newValue = true;
                }
            }

            setModeDeep(members, newValue ? MODE_ON : config.offMode);
            this.mkFgRefresh(true);
            currentGraph()?.setDirtyCanvas?.(true, true);
        };

        /** 全部启用 / 全部关闭 / 反转 */
        nodeType.prototype.mkFgEnableAll = function () {
            const restriction = String(this.mkFgProp(P.toggleRestriction) || "default");
            const onlyOne = restriction.includes(" one");
            const entries = this.mkFgEntries();
            entries.forEach((entry, index) => {
                setModeDeep(membersOf(entry.group), onlyOne && index > 0 ? config.offMode : MODE_ON);
            });
            this.mkFgRefresh(true);
            currentGraph()?.setDirtyCanvas?.(true, true);
        };

        nodeType.prototype.mkFgDisableAll = function () {
            const restriction = String(this.mkFgProp(P.toggleRestriction) || "default");
            const alwaysOne = restriction === "always one";
            const entries = this.mkFgEntries();
            entries.forEach((entry, index) => {
                setModeDeep(membersOf(entry.group), alwaysOne && index === 0 ? MODE_ON : config.offMode);
            });
            this.mkFgRefresh(true);
            currentGraph()?.setDirtyCanvas?.(true, true);
        };

        nodeType.prototype.mkFgToggleAll = function () {
            const restriction = String(this.mkFgProp(P.toggleRestriction) || "default");
            const onlyOne = restriction.includes(" one");
            const entries = this.mkFgEntries();
            let foundOn = false;
            for (const entry of entries) {
                const target = onlyOne && foundOn ? false : !entry.on;
                foundOn = foundOn || target;
                setModeDeep(membersOf(entry.group), target ? MODE_ON : config.offMode);
            }
            if (!foundOn && restriction === "always one" && entries.length) {
                setModeDeep(membersOf(entries[entries.length - 1].group), MODE_ON);
            }
            this.mkFgRefresh(true);
            currentGraph()?.setDirtyCanvas?.(true, true);
        };

        /** 跳转到分组：有 canvas 就居中并缩放，没有就静默跳过（Nodes 2.0 无 canvas 时） */
        nodeType.prototype.mkFgFocusGroup = function (group) {
            const canvas = app.canvas;
            if (!canvas) return;
            try {
                if (typeof canvas.centerOnNode === "function") {
                    canvas.centerOnNode(group);
                }
                const size = boundingOfGroup(group);
                const scale = Number(canvas.ds?.scale) || 1;
                const viewW = canvas.canvas?.width || 0;
                const viewH = canvas.canvas?.height || 0;
                if (size[2] > 0 && size[3] > 0 && viewW && viewH && typeof canvas.setZoom === "function") {
                    const zoomX = viewW / size[2] - 0.02;
                    const zoomY = viewH / size[3] - 0.02;
                    canvas.setZoom(Math.min(scale, zoomX, zoomY), [viewW / 2, viewH / 2]);
                }
                canvas.setDirty?.(true, true);
            } catch (e) {
                console.warn("[MK] 跳转到分组失败", e);
            }
        };

        // ── 生命周期 ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            this.mkFgInitProperties();
            this.mkFgBuildPanel();
            this.mkFgSyncSettings();
            activeNodes.add(this);
            ensurePolling();
            this.mkFgRefresh(true);
            if (typeof this.setSize === "function") {
                if (!Array.isArray(this.size) || this.size[1] < MIN_NODE_SIZE[1]) {
                    this.setSize([...DEFAULT_NODE_SIZE]);
                }
            }
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            this.mkFgInitProperties();
            this.mkFgSyncSettings();
            activeNodes.add(this);
            ensurePolling();
            this.mkFgRefresh(true);
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => this.mkFgSyncPanelHeight());
            }
            return result;
        };

        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function () {
            const result = onResize?.apply(this, arguments);
            const sync = () => this.mkFgSyncPanelHeight();
            if (typeof requestAnimationFrame === "function") requestAnimationFrame(sync);
            else sync();
            return result;
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            activeNodes.delete(this);
            stopPollingIfIdle();
            const result = onRemoved?.apply(this, arguments);
            return result;
        };
    },
});
