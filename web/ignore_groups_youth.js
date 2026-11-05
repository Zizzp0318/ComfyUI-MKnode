// Comfyui_MKnode —— MK-禁用（忽略）多组青春版 前端
//
// 与「老关怀版」（web/ignore_groups.js）是同一个功能的两种皮：
// - 老关怀版：自绘 DOM 面板（行更高、字号更大），带「UI 组件大小」缩放，给眼睛吃力的场景用；
// - 青春版（本文件）：全部用 ComfyUI **原生 widget** ——
//     每个编组 = 一个原生开关（toggle），设置入口 = 一个原生按钮（不再是右上角的齿轮图标）；
//   不提供放大/缩小设置，节点宽高就是 ComfyUI 的默认行为。
//
// 两个版本共用分组扫描与状态判定：web/mk_ignore_groups_core.js。
// 开关状态仍存在节点 properties（mk_ig_*）里，随工作流保存；widget 本身设为
// serialize:false，所以分组增减不会把 widgets_values 的顺序搞乱。
//
// 命名隔离：节点 id MK_IgnoreGroupsYouth、扩展名 Comfyui_MKnode.IgnoreGroupsYouth。

import { app } from "../../scripts/app.js";
import {
    buildEntries,
    collectNodes,
    getAllNestedGroups,
    getGroupState,
    bypassGroup,
    restoreGroup,
} from "./mk_ignore_groups_core.js";

const NODE_TYPE = "MK_IgnoreGroupsYouth";

// 分组与节点状态都不是响应式的，只能定时比对
const POLL_MS = 500;

// 默认宽度：原生 widget 的名字列比较窄，给个稍宽一点的起点，用户仍可自由拖
const DEFAULT_WIDTH = 280;

app.registerExtension({
    name: "Comfyui_MKnode.IgnoreGroupsYouth",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origCreated?.apply(this, arguments);
            this.size = [DEFAULT_WIDTH, this.size[1]];
            buildYouthUI(this);
        };

        const origConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            origConfigure?.apply(this, arguments);
            if (this._mkIgySync) this._mkIgySync();
        };

        // 原生 UI 下没有齿轮，右键菜单里也留一个入口，和「设置」按钮等价
        const origGetExtra = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
            if (origGetExtra) origGetExtra.apply(this, arguments);
            options.unshift({
                content: "⚙ 禁用（忽略）多组 设置",
                callback: () => this._mkIgyShowSettings?.(),
            });
        };
    },
});


function buildYouthUI(node) {

    let filter = "";
    let mode = "default";          // default | always_one | at_most_one
    let active = null;
    let activeSet = null;
    let igDisable = false;         // false = 关闭时绕过(Bypass)；true = 关闭时禁用(Mute)
    let sortOrder = "position";    // position | alphabet
    let colorFilter = "none";
    let includeSubgraphs = true;
    // 开关颜色：原生 toggle 只会跟随全局主题（暗色下几乎是黑的），
    // 这里给每个开关盖一层自绘，让「开」用得上自定义颜色。
    let swColor = "#a89961";
    let selfChanging = false;
    let dirty = true;

    if (node.properties) {
        if (node.properties.mk_ig_filter != null) filter = node.properties.mk_ig_filter;
        if (node.properties.mk_ig_mode != null) mode = node.properties.mk_ig_mode;
        if (node.properties.mk_ig_active != null) active = node.properties.mk_ig_active;
        if (node.properties.mk_ig_active_set != null) activeSet = node.properties.mk_ig_active_set;
        if (node.properties.mk_ig_disable != null) igDisable = !!node.properties.mk_ig_disable;
        if (node.properties.mk_ig_sort_order != null) sortOrder = node.properties.mk_ig_sort_order;
        if (node.properties.mk_ig_color_filter != null) colorFilter = node.properties.mk_ig_color_filter;
        if (node.properties.mk_ig_include_subgraphs != null) includeSubgraphs = !!node.properties.mk_ig_include_subgraphs;
        if (node.properties.mk_ig_switch_color != null) swColor = node.properties.mk_ig_switch_color;
    }

    function save() {
        node.properties = node.properties || {};
        node.properties.mk_ig_filter = filter;
        node.properties.mk_ig_mode = mode;
        node.properties.mk_ig_active = active;
        node.properties.mk_ig_active_set = activeSet;
        node.properties.mk_ig_disable = igDisable;
        node.properties.mk_ig_sort_order = sortOrder;
        node.properties.mk_ig_color_filter = colorFilter;
        node.properties.mk_ig_include_subgraphs = includeSubgraphs;
        node.properties.mk_ig_switch_color = swColor;
    }

    // 载入工作流 / 撤销后重新读属性
    function _mkIgySync() {
        filter = (node.properties && node.properties.mk_ig_filter) || "";
        mode = (node.properties && node.properties.mk_ig_mode) || "default";
        active = (node.properties && node.properties.mk_ig_active) || null;
        activeSet = (node.properties && node.properties.mk_ig_active_set) || null;
        igDisable = (node.properties && node.properties.mk_ig_disable) || false;
        sortOrder = (node.properties && node.properties.mk_ig_sort_order) || "position";
        colorFilter = (node.properties && node.properties.mk_ig_color_filter) || "none";
        includeSubgraphs = node.properties && node.properties.mk_ig_include_subgraphs != null
            ? !!node.properties.mk_ig_include_subgraphs
            : true;
        swColor = (node.properties && node.properties.mk_ig_switch_color) || "#a89961";
        lastSig = "";
        lastStateSig = "";
        prevVisibleKeys = new Set();
        _preserveActive = true;
        _widgetSig = "";
        dirty = true;
        refresh(true);
    }

    // ── 宿主图：节点可能在根图，也可能被拖进子图 ──
    function hostGraph() {
        return (node && node.graph) || app.graph;
    }

    let _rgCache = null;
    function rawEntries(invalidate) {
        if (invalidate) { _rgCache = null; }
        if (_rgCache) return _rgCache;
        _rgCache = buildEntries(hostGraph(), includeSubgraphs);
        return _rgCache;
    }

    // 可见分组：非空组 + 关键词 + 颜色，再按设置排序
    function visible(cachedAll) {
        let list = cachedAll || rawEntries();
        if (!cachedAll) list = list.slice();
        list = list.filter(g => collectNodes(g, list).length > 0);
        if (filter.trim()) {
            const kw = filter.trim().toLowerCase();
            list = list.filter(g => (g.label || g.title).toLowerCase().includes(kw));
        }
        if (colorFilter && colorFilter !== "none") {
            list = list.filter(g => {
                if (colorFilter === "__transparent__") return !g.color;
                return g.color && g.color.toLowerCase() === colorFilter.toLowerCase();
            });
        }
        if (sortOrder === "position") {
            list.sort((a, b) => {
                if (a.order !== b.order) return a.order - b.order;
                const ax = a.bounds[0], ay = a.bounds[1];
                const bx = b.bounds[0], by = b.bounds[1];
                if (ay !== by) return ay - by;
                return ax - bx;
            });
        } else {
            list.sort((a, b) =>
                (a.label || a.title).localeCompare(b.label || b.title, undefined, { sensitivity: "base" })
            );
        }
        return list;
    }

    function isOnOf(entry) {
        return mode === "default"
            ? (Array.isArray(activeSet) && activeSet.includes(entry.key))
            : entry.key === active;
    }

    function computeStateSig(list) {
        return list.map(g => {
            const s = getGroupState(g, rawEntries());
            return g.key + ":" + (s === true ? "1" : s === false ? "0" : "m");
        }).join("\x00");
    }

    function hexToRgba(hex, alpha) {
        if (!hex || hex.length < 7) return `rgba(120,120,120,${alpha})`;
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r},${g},${b},${alpha})`;
    }

    // 给原生 toggle 换一层皮：行高、点击、序列化都还是原生的，只改「画」。
    // 原生未开启时是深灰圆点，暗色皮肤下几乎看不出状态；这里改成
    // 开 = 自定义颜色（半透明底 + 实心圆点），关 = 中性灰。
    function paintToggle(w) {
        w.drawWidget = function (ctx, options) {
            const { width, showText = true } = options || {};
            const height = this.height;
            const y = this.y;
            const margin = (this.constructor && this.constructor.margin) || 10;
            const on = !!this.value;
            const x = margin;
            const bw = width - margin * 2;
            const radius = height * 0.5;
            const knobX = x + bw - height * 0.55;
            const centerY = y + height * 0.5;

            ctx.save();

            ctx.beginPath();
            ctx.roundRect(x, y, bw, height, radius);
            ctx.fillStyle = on ? hexToRgba(swColor, 0.32) : "rgba(0,0,0,0.28)";
            ctx.fill();
            ctx.strokeStyle = on ? swColor : "rgba(255,255,255,0.20)";
            ctx.lineWidth = 1;
            ctx.stroke();

            if (showText) {
                ctx.textBaseline = "middle";
                ctx.textAlign = "left";
                ctx.fillStyle = on ? "#ffffff" : "rgba(255,255,255,0.70)";
                ctx.fillText(this.name, x + height * 0.55, centerY);

                ctx.textAlign = "right";
                ctx.fillStyle = on ? swColor : "rgba(255,255,255,0.55)";
                ctx.fillText(
                    on ? (this.options?.on || "开") : (this.options?.off || "关"),
                    knobX - height * 0.5,
                    centerY
                );
            }

            ctx.beginPath();
            ctx.arc(knobX, centerY, height * 0.3, 0, Math.PI * 2);
            ctx.fillStyle = on ? swColor : "#6b6b6b";
            ctx.fill();

            ctx.restore();
        };
    }

    // 颜色深浅决定文字用黑还是白（浅色底上白字看不清）
    function isLightColor(hex) {
        if (!hex || hex.length < 7) return false;
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return (0.299 * r + 0.587 * g + 0.114 * b) > 150;
    }

    // Nodes 2.0（Vue 渲染）下开关是 ToggleGroup 的两个分段按钮，
    // 选中态写死在样式表里（data-[state=on]:bg-secondary-background），
    // 不走 canvas 的 drawWidget，所以只能补一段「只作用于本节点」的 CSS。
    let _colorStyleEl = null;
    let _colorKey = "";

    function syncColorStyle(force) {
        const key = `${node.id}|${swColor}`;
        if (!force && key === _colorKey) return;
        _colorKey = key;

        if (!_colorStyleEl) {
            _colorStyleEl = document.createElement("style");
            document.head.appendChild(_colorStyleEl);
        }
        _colorStyleEl.id = "mk-igy-color-" + (node.id ?? "0");
        const safe = /^#[0-9a-fA-F]{6}$/.test(swColor) ? swColor : "#a89961";
        const fg = isLightColor(safe) ? "#1b1b1b" : "#ffffff";
        const sel = `.lg-node[data-node-id="${node.id}"]`;
        _colorStyleEl.textContent =
            `${sel} [data-state="on"] {` +
            ` background-color: ${safe} !important; color: ${fg} !important; }` +
            `${sel} [data-state="on"]:hover { background-color: ${safe} !important; }`;
    }

    // 换色后立刻重画 / 重刷样式（canvas 与 Vue 两种渲染各管一条）
    function repaintWidgets() {
        _widgets.forEach(paintToggle);
        syncColorStyle(true);
        try { node.setDirtyCanvas?.(true, true); } catch (_) {}
        try { app.graph?.setDirtyCanvas?.(true, true); } catch (_) {}
    }

    // ── 原生 widget：设置按钮 + 每组一个开关 ──

    let _widgets = [];      // 由本节点维护的分组开关
    let _widgetSig = "";    // 当前 widget 对应的分组键序列
    let _settingsBtn = null;

    function ensureSettingsButton() {
        if (_settingsBtn) return _settingsBtn;
        // 原生按钮：点一下开设置弹窗（不再用右上角齿轮图标）
        _settingsBtn = node.addWidget("button", "设置", null, () => {
            showSettings();
        });
        if (_settingsBtn) _settingsBtn.serialize = false;
        return _settingsBtn;
    }

    function removeGroupWidgets() {
        _widgets.forEach(w => {
            try { node.removeWidget(w); } catch (_) { /* 老前端没有 removeWidget 时忽略 */ }
        });
        _widgets = [];
    }

    function rebuildGroupWidgets(list) {
        removeGroupWidgets();
        list.forEach(entry => {
            const w = node.addWidget("toggle", entry.title, isOnOf(entry), (value) => {
                handleToggle(entry.key, !!value);
            }, { on: "开", off: "关" });
            if (!w) return;
            w.serialize = false;      // 状态走 properties，不写 widgets_values
            w._mkIgyKey = entry.key;
            paintToggle(w);           // 自定义配色
            _widgets.push(w);
        });
    }

    // 分组列表变了就重建 widget，否则只同步开关值（不打断用户点击手感）
    function syncWidgets(list) {
        ensureSettingsButton();
        const sig = list.map(g => g.key).join("\x00");
        if (sig !== _widgetSig) {
            _widgetSig = sig;
            rebuildGroupWidgets(list);
            return;
        }
        list.forEach((entry, i) => {
            const w = _widgets[i];
            if (!w) return;
            const on = isOnOf(entry);
            if (w.value !== on) w.value = on;
        });
    }

    // ── 状态 ──

    let lastSig = "";
    let lastStateSig = "";
    let prevVisibleKeys = new Set();
    let _preserveActive = false;

    function refresh(forceApply) {
        const cachedAll = rawEntries(true);

        ensureGraphHooks(hostGraph());
        cachedAll.forEach(g => ensureGraphHooks(g.graph));

        const list = visible(cachedAll);
        const currentVisibleKeys = new Set(list.map(g => g.key));
        const sig = list.map(g => g.key).join("\x00");
        const listChanged = (sig !== lastSig);
        lastSig = sig;

        let stateChanged = false;

        if (mode === "default") {
            if (!Array.isArray(activeSet)) {
                activeSet = [];
                cachedAll.forEach(g => {
                    if (getGroupState(g, cachedAll) !== false) activeSet.push(g.key);
                });
                stateChanged = true;
            } else {
                const allKeys = new Set(cachedAll.map(g => g.key));
                const before = activeSet.length;
                activeSet = activeSet.filter(t => allKeys.has(t));
                if (activeSet.length !== before) stateChanged = true;

                if (listChanged) {
                    list.forEach(g => {
                        if (!prevVisibleKeys.has(g.key)) {
                            const gs = getGroupState(g, cachedAll);
                            const idx = activeSet.indexOf(g.key);
                            if (gs === true && idx < 0) {
                                activeSet.push(g.key);
                                stateChanged = true;
                            } else if (gs === false && idx >= 0) {
                                activeSet.splice(idx, 1);
                                stateChanged = true;
                            }
                        }
                    });
                }
            }
        } else if (!_preserveActive) {
            const hasFilter = !!(filter.trim() || (colorFilter && colorFilter !== "none"));

            if (active && !cachedAll.some(g => g.key === active)) {
                active = (mode === "always_one" && list.length) ? list[0].key : null;
                stateChanged = true;
            }
            if (active && hasFilter) {
                const filteredKeys = new Set(list.map(g => g.key));
                if (!filteredKeys.has(active)) {
                    active = (mode === "always_one" && list.length) ? list[0].key : null;
                    stateChanged = true;
                }
            }
            if (mode === "always_one" && !active && list.length) {
                active = list[0].key;
                stateChanged = true;
            }
        }

        _preserveActive = false;
        if (stateChanged) save();

        if (forceApply || stateChanged || listChanged) {
            selfChanging = true;
            try {
                const touched = new Set();
                list.forEach(g => {
                    if (isOnOf(g)) restoreGroup(g, cachedAll);
                    else bypassGroup(g, cachedAll, igDisable);
                    touched.add(g.graph || hostGraph());
                });
                markGraphsChanged(touched);
            } finally {
                selfChanging = false;
            }
        }

        prevVisibleKeys = currentVisibleKeys;
        syncWidgets(list);
        syncColorStyle();
    }


    function handleToggle(entryKey, value) {
        if (mode === "default") {
            if (!Array.isArray(activeSet)) activeSet = [];
            const entries = rawEntries();
            const grp = entries.find(g => g.key === entryKey);

            if (value) {
                if (!activeSet.includes(entryKey)) activeSet.push(entryKey);
                // 打开父组时连同嵌套子组一起打开
                if (grp) {
                    getAllNestedGroups(grp, entries).forEach(ng => {
                        if (!activeSet.includes(ng.key)) activeSet.push(ng.key);
                    });
                }
            } else {
                const off = new Set([entryKey]);
                if (grp) getAllNestedGroups(grp, entries).forEach(ng => off.add(ng.key));
                activeSet = activeSet.filter(t => !off.has(t));
            }
        } else {
            active = value ? entryKey : null;
        }
        save();
        refresh(true);
    }


    // ── 图变更钩子（每张图一层，子图内部改动也能触发刷新） ──
    const _hookedGraphs = new WeakSet();

    function ensureGraphHooks(g) {
        if (!g || typeof g.change !== "function" || _hookedGraphs.has(g)) return;
        _hookedGraphs.add(g);
        const orig = g.change;
        g.change = function () {
            if (!selfChanging) dirty = true;
            return orig.apply(this, arguments);
        };
    }

    function markGraphsChanged(graphs) {
        const seen = new Set();
        (graphs || []).forEach(g => {
            if (!g || typeof g.change !== "function" || seen.has(g)) return;
            seen.add(g);
            try { g.change(); } catch (_) {}
        });
    }

    ensureGraphHooks(hostGraph());


    // ── 设置弹窗（原生 UI 下没有缩放/主题色：那是老关怀版的东西） ──
    let _settingsCleanup = null;

    function showSettings() {
        if (_settingsCleanup) { _settingsCleanup(); _settingsCleanup = null; }

        const overlay = document.createElement("div");
        overlay.id = "mk_igy_overlay";
        Object.assign(overlay.style, {
            position: "fixed", inset: "0", zIndex: "99998",
            background: "transparent", cursor: "default",
        });
        document.body.appendChild(overlay);

        const pop = document.createElement("div");
        pop.id = "mk_igy_pop";
        Object.assign(pop.style, {
            position: "fixed",
            left: Math.max(8, Math.round(innerWidth / 2 - 130)) + "px",
            top: Math.max(8, Math.round(innerHeight / 2 - 260)) + "px",
            background: "#2a2a2a", border: "1px solid #555",
            borderRadius: "8px", padding: "14px 18px",
            zIndex: "99999", minWidth: "250px",
            boxShadow: "0 4px 24px rgba(0,0,0,0.6)",
            color: "#e0e0e0", fontFamily: "inherit",
        });

        function closePopup() {
            if (overlay.parentNode) overlay.remove();
            if (pop.parentNode) pop.remove();
            document.removeEventListener("keydown", onEsc);
            document.removeEventListener("mousedown", closeColorPanel);
            _settingsCleanup = null;
        }
        _settingsCleanup = closePopup;

        overlay.addEventListener("mousedown", (e) => {
            e.preventDefault(); e.stopPropagation(); closePopup();
        });
        function onEsc(e) { if (e.key === "Escape") closePopup(); }
        document.addEventListener("keydown", onEsc);

        const mkLabel = (text, marginBottom = "4px") => {
            const el = document.createElement("div");
            el.textContent = text;
            Object.assign(el.style, {
                fontSize: "13px", fontWeight: "bold", marginBottom,
            });
            return el;
        };

        const mkInputStyle = (el, marginBottom = "14px") => {
            Object.assign(el.style, {
                width: "100%", padding: "5px 8px", fontSize: "13px",
                background: "#1a1a1a", border: "1px solid #555", borderRadius: "4px",
                color: "#e0e0e0", outline: "none", boxSizing: "border-box", marginBottom,
            });
            return el;
        };

        const titleEl = document.createElement("div");
        titleEl.textContent = "⚙ 禁用（忽略）多组 设置";
        Object.assign(titleEl.style, {
            fontSize: "15px", fontWeight: "bold", marginBottom: "14px",
            color: "#e0e0e0", borderBottom: "1px solid #444", paddingBottom: "8px",
        });
        pop.appendChild(titleEl);

        function applyAll() {
            filter = fInput.value;
            colorFilter = cFilter;
            igDisable = dRadioDisable.checked;
            sortOrder = sSelect.value;
            includeSubgraphs = !!sgCheck.checked;

            const newMode = mSelect.value;
            if (newMode !== mode) {
                if (newMode === "default") {
                    activeSet = visible().map(g => g.key);
                } else if (newMode === "always_one") {
                    const fl = visible();
                    const ft = new Set(fl.map(g => g.key));
                    const match = (activeSet || []).find(t => ft.has(t));
                    active = match || (fl.length ? fl[0].key : null);
                    activeSet = null;
                } else {
                    const fl = visible();
                    const ft = new Set(fl.map(g => g.key));
                    const match = (activeSet || []).find(t => ft.has(t));
                    active = match || null;
                    activeSet = null;
                }
                mode = newMode;
            } else if (mode === "always_one" && !active) {
                const list = visible();
                if (list.length) active = list[0].key;
            }

            save();
            _widgetSig = "";   // 过滤/排序/分组范围变了，widget 需要重建
            refresh(true);
        }

        // 路由控制
        pop.appendChild(mkLabel("路由控制", "6px"));
        const dRow = document.createElement("div");
        Object.assign(dRow.style, { display: "flex", alignItems: "center", gap: "20px", marginBottom: "14px" });

        const dRadioBypass = document.createElement("input");
        dRadioBypass.type = "radio"; dRadioBypass.name = "mk_igy_close_mode";
        dRadioBypass.value = "bypass"; dRadioBypass.checked = !igDisable; dRadioBypass.style.cursor = "pointer";
        const dLblBypass = document.createElement("label");
        dLblBypass.style.cursor = "pointer"; dLblBypass.style.fontSize = "13px";
        dLblBypass.appendChild(dRadioBypass); dLblBypass.appendChild(document.createTextNode(" 绕过（ctrl+b）"));

        const dRadioDisable = document.createElement("input");
        dRadioDisable.type = "radio"; dRadioDisable.name = "mk_igy_close_mode";
        dRadioDisable.value = "disable"; dRadioDisable.checked = !!igDisable; dRadioDisable.style.cursor = "pointer";
        const dLblDisable = document.createElement("label");
        dLblDisable.style.cursor = "pointer"; dLblDisable.style.fontSize = "13px";
        dLblDisable.appendChild(dRadioDisable); dLblDisable.appendChild(document.createTextNode(" 禁用（ctrl+m）"));

        dRow.appendChild(dLblBypass); dRow.appendChild(dLblDisable); pop.appendChild(dRow);
        dRadioBypass.addEventListener("change", applyAll);
        dRadioDisable.addEventListener("change", applyAll);

        // 包含子图分组
        const sgRow = document.createElement("label");
        sgRow.title = "把子图内部的编组也列出来。开关改的是子图定义，所有实例一起生效。";
        Object.assign(sgRow.style, {
            display: "flex", alignItems: "center", gap: "8px",
            fontSize: "13px", marginBottom: "14px", cursor: "pointer", userSelect: "none",
        });
        const sgCheck = document.createElement("input");
        sgCheck.type = "checkbox";
        sgCheck.checked = !!includeSubgraphs;
        sgCheck.style.cursor = "pointer";
        const sgTxt = document.createElement("span");
        sgTxt.textContent = "包含子图分组";
        sgRow.appendChild(sgCheck);
        sgRow.appendChild(sgTxt);
        pop.appendChild(sgRow);
        sgCheck.addEventListener("change", applyAll);

        // 关键词筛选
        pop.appendChild(mkLabel("关键词筛选"));
        const fInput = mkInputStyle(document.createElement("input"));
        fInput.type = "text"; fInput.value = filter; fInput.placeholder = "留空 = 显示所有组";
        pop.appendChild(fInput);
        let filterTimer = null;
        fInput.addEventListener("input", () => {
            if (filterTimer) clearTimeout(filterTimer);
            filterTimer = setTimeout(applyAll, 200);
        });

        // 颜色筛选
        pop.appendChild(mkLabel("颜色筛选"));
        let cFilter = colorFilter || "none";

        const cdContainer = document.createElement("div");
        Object.assign(cdContainer.style, { position: "relative", width: "100%", marginBottom: "14px" });

        const cdTrigger = document.createElement("div");
        Object.assign(cdTrigger.style, {
            width: "100%", padding: "5px 8px", fontSize: "13px",
            background: "#1a1a1a", border: "1px solid #555", borderRadius: "4px",
            color: "#e0e0e0", boxSizing: "border-box",
            cursor: "pointer", display: "flex", alignItems: "center", gap: "6px", userSelect: "none",
        });
        const cdColorRect = document.createElement("span");
        Object.assign(cdColorRect.style, {
            display: "inline-block", width: "44px", height: "14px",
            borderRadius: "2px", border: "1px solid #555", flexShrink: "0",
        });
        const cdColorText = document.createElement("span");
        Object.assign(cdColorText.style, { flex: "1" });
        const cdArrow = document.createElement("span");
        cdArrow.textContent = "\u25BE";
        Object.assign(cdArrow.style, { marginLeft: "auto", fontSize: "11px", color: "#888" });
        cdTrigger.appendChild(cdColorRect); cdTrigger.appendChild(cdColorText); cdTrigger.appendChild(cdArrow);

        function updateColorPreview() {
            if (cFilter === "none") {
                cdColorRect.style.display = "none"; cdColorText.textContent = "无";
            } else if (cFilter === "__transparent__") {
                cdColorRect.style.display = "inline-block"; cdColorRect.style.background = "transparent";
                cdColorText.textContent = "透明色";
            } else {
                cdColorRect.style.display = "inline-block"; cdColorRect.style.background = cFilter;
                cdColorText.textContent = cFilter.toUpperCase();
            }
        }
        updateColorPreview();
        cdContainer.appendChild(cdTrigger);

        let cdPanel = null;

        function buildColorOptions() {
            const allRaw = rawEntries();
            const colorMap = new Map();
            allRaw.forEach(g => { const c = g.color || "__transparent__"; if (!colorMap.has(c)) colorMap.set(c, g); });
            const colors = Array.from(colorMap.keys());
            if (cdPanel) { cdPanel.remove(); cdPanel = null; }
            cdPanel = document.createElement("div");
            Object.assign(cdPanel.style, {
                position: "absolute", left: "0", right: "0", top: "calc(100% + 2px)",
                background: "#1a1a1a", border: "1px solid #555", borderRadius: "4px",
                zIndex: "100001", maxHeight: "200px", overflowY: "auto",
                boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
            });
            function makeColorItem(bgColor, label, value, isTransparent, isNone) {
                const item = document.createElement("div");
                Object.assign(item.style, {
                    display: "flex", alignItems: "center", gap: "8px",
                    padding: "5px 8px", cursor: "pointer", fontSize: "13px",
                });
                item.addEventListener("mouseenter", () => { item.style.background = "#3a3a3a"; });
                item.addEventListener("mouseleave", () => { item.style.background = "transparent"; });
                if (!isNone) {
                    const rect = document.createElement("span");
                    Object.assign(rect.style, {
                        display: "inline-block", width: "44px", height: "16px",
                        borderRadius: "2px", border: "1px solid #555",
                        background: isTransparent ? "transparent" : bgColor, flexShrink: "0",
                    });
                    item.appendChild(rect);
                }
                const txt = document.createElement("span");
                txt.textContent = label; txt.style.color = "#fff"; item.appendChild(txt);
                item.addEventListener("click", (e) => {
                    e.stopPropagation(); cFilter = value; updateColorPreview();
                    if (cdPanel) { cdPanel.remove(); cdPanel = null; } applyAll();
                });
                return item;
            }
            cdPanel.appendChild(makeColorItem("#2a2a2a", "无", "none", false, true));
            colors.forEach(c => {
                if (c === "__transparent__") cdPanel.appendChild(makeColorItem("#2A2A2A", "透明色", "__transparent__", true, false));
                else cdPanel.appendChild(makeColorItem(c, c.toUpperCase(), c, false, false));
            });
            cdContainer.appendChild(cdPanel);
        }
        cdTrigger.addEventListener("click", (e) => {
            e.stopPropagation();
            if (cdPanel) { cdPanel.remove(); cdPanel = null; } else { buildColorOptions(); }
        });
        pop.appendChild(cdContainer);

        const closeColorPanel = (e) => {
            if (cdPanel && !cdContainer.contains(e.target)) { cdPanel.remove(); cdPanel = null; }
        };
        document.addEventListener("mousedown", closeColorPanel);

        // 切换模式
        pop.appendChild(mkLabel("切换模式"));
        const mSelect = mkInputStyle(document.createElement("select"));
        [["default", "默认"], ["always_one", "始终开启1个"], ["at_most_one", "最多开启1个"]].forEach(([val, txt]) => {
            const opt = document.createElement("option"); opt.value = val; opt.textContent = txt; mSelect.appendChild(opt);
        });
        mSelect.value = mode; pop.appendChild(mSelect);
        mSelect.addEventListener("change", applyAll);

        // 排序
        pop.appendChild(mkLabel("排序"));
        const sSelect = mkInputStyle(document.createElement("select"));
        [["position", "按位置"], ["alphabet", "按首字母"]].forEach(([val, txt]) => {
            const opt = document.createElement("option"); opt.value = val; opt.textContent = txt; sSelect.appendChild(opt);
        });
        sSelect.value = sortOrder; pop.appendChild(sSelect);
        sSelect.addEventListener("change", applyAll);

        // 开关颜色（原生 toggle 默认只有主题色，暗色下几乎是黑的）
        const colorLabel = mkLabel("开关颜色");
        colorLabel.title = "「开」状态下开关的颜色，暗色皮肤下更容易辨认。";
        pop.appendChild(colorLabel);

        const colorRow = document.createElement("div");
        Object.assign(colorRow.style, {
            display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px",
        });

        const cInput = document.createElement("input");
        cInput.type = "color"; cInput.value = swColor;
        Object.assign(cInput.style, {
            width: "36px", height: "28px", padding: "0",
            border: "1px solid #555", borderRadius: "4px", background: "#1a1a1a", cursor: "pointer",
        });

        const cHex = document.createElement("input");
        cHex.type = "text"; cHex.value = swColor;
        Object.assign(cHex.style, {
            flex: "1", padding: "5px 8px", fontSize: "13px",
            background: "#1a1a1a", border: "1px solid #555", borderRadius: "4px",
            color: "#e0e0e0", outline: "none", boxSizing: "border-box",
        });

        colorRow.appendChild(cInput);
        colorRow.appendChild(cHex);
        pop.appendChild(colorRow);

        function applyColor() {
            swColor = cInput.value;
            save();
            repaintWidgets();
        }

        cInput.addEventListener("input", () => { cHex.value = cInput.value; applyColor(); });
        cHex.addEventListener("input", () => {
            if (/^#[0-9a-fA-F]{6}$/.test(cHex.value)) { cInput.value = cHex.value; applyColor(); }
        });

        document.body.appendChild(pop);
        pop.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); });
    }

    node._mkIgyShowSettings = showSettings;
    node._mkIgySync = _mkIgySync;


    // 用户手动 ctrl+b / ctrl+m 后，等 ComfyUI 处理完再看
    function onKeyDown(e) {
        if ((e.ctrlKey || e.metaKey) &&
            (e.key === "m" || e.key === "b" || e.key === "M" || e.key === "B")) {
            setTimeout(() => { dirty = true; }, 100);
        }
    }
    document.addEventListener("keydown", onKeyDown);

    // 后台标签页不轮询，切回来补一次
    let pageVisible = !document.hidden;
    function onVisibilityChange() {
        const nowVisible = !document.hidden;
        if (nowVisible && !pageVisible) { pageVisible = true; dirty = true; }
        else { pageVisible = nowVisible; }
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    let _lastHost = null;

    const timer = setInterval(() => {
        // 节点被删掉：收摊
        if (!node.graph) {
            clearInterval(timer);
            if (_colorStyleEl) { _colorStyleEl.remove(); _colorStyleEl = null; }
            document.removeEventListener("visibilitychange", onVisibilityChange);
            document.removeEventListener("keydown", onKeyDown);
            return;
        }

        const host = hostGraph();
        if (!host || !host._nodes || host._nodes.indexOf(node) < 0) return;

        // node.id 在加入画布后才分配，配色 CSS 的选择器要跟着刷新
        syncColorStyle();

        // 节点被拖进/拖出子图：缓存、签名、widget 全部重来
        if (host !== _lastHost) {
            _lastHost = host;
            ensureGraphHooks(host);
            rawEntries(true);
            lastSig = "";
            lastStateSig = "";
            prevVisibleKeys = new Set();
            _widgetSig = "";
            _preserveActive = true;
            dirty = true;
        }

        if (!pageVisible) return;

        if (dirty) {
            dirty = false;
            const cachedAll = rawEntries(true);
            const list = visible(cachedAll);
            const sig = list.map(g => g.key).join("\x00");
            const listChanged = (sig !== lastSig);
            const stateSig = computeStateSig(list);
            const stateChanged = (stateSig !== lastStateSig);

            if (listChanged || stateChanged) {
                lastStateSig = stateSig;
                selfChanging = true;
                try {
                    const syncChanged = syncExternalState(cachedAll);
                    if (listChanged || syncChanged) {
                        refresh(true);
                    } else {
                        syncWidgets(list);
                    }
                    markGraphsChanged([host]);
                } finally {
                    selfChanging = false;
                }
            }
        }
    }, POLL_MS);

    // 外部改动（别处 ctrl+b/m、新增分组）回灌到 active / activeSet
    function syncExternalState(cachedAll) {
        const host = hostGraph();
        if (!host || !host._nodes || host._nodes.indexOf(node) < 0) return false;

        let changed = false;

        if (mode === "default") {
            if (!Array.isArray(activeSet)) return false;
            rawEntries().forEach(g => {
                const gs = getGroupState(g, cachedAll);
                const isActive = activeSet.includes(g.key);
                if (gs === true && !isActive) {
                    activeSet.push(g.key);
                    changed = true;
                } else if (gs === false && isActive) {
                    activeSet = activeSet.filter(t => t !== g.key);
                    changed = true;
                }
            });
        } else {
            const filteredList = visible(cachedAll);
            if (mode === "always_one") {
                if (active) {
                    const grp = filteredList.find(g => g.key === active);
                    if (grp && getGroupState(grp, cachedAll) === false) {
                        const nextActive = filteredList.find(g => getGroupState(g, cachedAll) === true);
                        active = nextActive ? nextActive.key : (filteredList.length ? filteredList[0].key : null);
                        changed = true;
                    } else if (!grp) {
                        active = filteredList.length
                            ? (filteredList.find(g => getGroupState(g, cachedAll) === true) || filteredList[0]).key
                            : null;
                        changed = true;
                    }
                }
                if (!active && filteredList.length) {
                    const firstActive = filteredList.find(g => getGroupState(g, cachedAll) === true);
                    if (firstActive) {
                        active = firstActive.key;
                        changed = true;
                    }
                }
            } else if (mode === "at_most_one") {
                if (active) {
                    const grp = filteredList.find(g => g.key === active);
                    if (!grp || getGroupState(grp, cachedAll) === false) {
                        active = null;
                        changed = true;
                    }
                }
                if (!active) {
                    for (const g of filteredList) {
                        if (getGroupState(g, cachedAll) === true) {
                            active = g.key;
                            changed = true;
                            break;
                        }
                    }
                }
            }
        }

        if (changed) save();
        return changed;
    }


    // 首屏
    ensureSettingsButton();
    syncColorStyle(true);
    refresh(false);
    lastStateSig = computeStateSig(visible());
    dirty = false;
}
