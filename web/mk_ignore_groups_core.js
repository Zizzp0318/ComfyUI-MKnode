// Comfyui_MKnode —— 「禁用（忽略）多组」两个版本共用的分组扫描逻辑
//
// MK-禁用（忽略）多组老关怀版（web/ignore_groups.js，自绘 DOM 面板）
// 与 MK-禁用（忽略）多组青春版（web/ignore_groups_youth.js，用 ComfyUI 原生 widget）
// 只差在「怎么画」，分组怎么找、开关怎么落、状态怎么判，全在这里。
//
// 这里只放纯函数：不碰 DOM、不缓存、不持有节点引用，参数传进来什么就算什么。
// 子图相关的事实（ComfyUI 前端 1.5x）：
// - Subgraph 继承 LGraph，编组在 `subgraph._groups` 上，与根图互不相干；
// - 子图实例节点 `node.isSubgraphNode()` 为 true，`node.subgraph` 就是那张子图；
// - 节点自己的 `node.graph` 就是它所在的图（根图或子图）。

// ── 几何 ──

/** 取编组的包围盒 [x, y, w, h]，兼容 _bounding / bounding / pos+size 三种存法。 */
export function gBounds(g) {
    if (g._bounding) return [...g._bounding];
    if (g.bounding) return [...g.bounding];
    const p = g.pos || [0, 0], s = g.size || [0, 0];
    return [p[0], p[1], s[0], s[1]];
}

/** 取编组颜色，统一成 #rrggbb；没设颜色返回空串。 */
export function getGroupColor(g) {
    const c = g.color;
    if (c) {
        if (typeof c === "number") return "#" + c.toString(16).padStart(6, "0");
        if (typeof c === "string" && c.startsWith("#") && (c.length === 4 || c.length === 7)) {
            if (c.length === 4) return "#" + c[1] + c[1] + c[2] + c[2] + c[3] + c[3];
            return c;
        }
    }
    return "";
}

/** 取节点的包围盒；折叠状态的节点只有标题条那么高。 */
export function nBounds(n) {
    const p = n.pos || [0, 0];
    const s = n.size || [100, 60];
    if (n.collapsed || n._collapsed) {
        const titleH = (typeof LiteGraph !== "undefined" && LiteGraph.NODE_TITLE_HEIGHT) || 30;
        let collapsedW = n._collapsed_width;
        if (!collapsedW || collapsedW <= 0) {
            const title = (typeof n.getTitle === "function" ? n.getTitle() : n.title) || "";
            collapsedW = Math.max(80, title.length * 7 + 50);
        }
        return [p[0], p[1], collapsedW, titleH];
    }
    return [p[0], p[1], s[0], s[1]];
}

/** 两个矩形是否相交。 */
export function hit(a, b) {
    return !(a[0] + a[2] <= b[0] || a[0] >= b[0] + b[2] ||
             a[1] + a[3] <= b[1] || a[1] >= b[1] + b[3]);
}

/** inner 是否完整落在 outer 里（判断嵌套编组用）。 */
export function inside(inner, outer) {
    return inner[0] >= outer[0] && inner[1] >= outer[1] &&
           inner[0] + inner[2] <= outer[0] + outer[2] &&
           inner[1] + inner[3] <= outer[1] + outer[3];
}

// ── 图结构 ──

const _gidCache = new WeakMap();
let _gidSeq = 0;

/** 图的稳定标识：优先用 LGraph.id，没有就临时分配一个（同一实例始终同一个）。 */
export function gidOf(g) {
    if (!g) return "g0";
    if (g.id != null) return String(g.id);
    let id = _gidCache.get(g);
    if (!id) {
        id = "g" + (++_gidSeq);
        _gidCache.set(g, id);
    }
    return id;
}

/**
 * 这张图里「真的被实例化」的子图（递归、去重）。
 * 只顺着节点上的 subgraph 引用走，工作流里没被用到的子图定义不会算进来。
 */
export function descendantSubgraphs(graph) {
    const out = [];
    const seen = new Set();
    function walk(g, level) {
        if (!g || level > 8) return;
        for (const n of (g._nodes || [])) {
            if (typeof n.isSubgraphNode !== "function" || !n.isSubgraphNode()) continue;
            const sg = n.subgraph;
            if (!sg || seen.has(sg)) continue;
            seen.add(sg);
            out.push(sg);
            walk(sg, level + 1);
        }
    }
    walk(graph, 0);
    return out;
}

/**
 * 收集分组条目。每条自带所属的图（graph）与唯一键（key）：
 * - 本图的分组：key = 组名，旧工作流里保存的开关集合可以原样继续用；
 * - 子图里的分组：key = `sg:<图id>:<组名>`，只用于内部区分，避免与根图同名组撞车；
 * - label 一律是纯组名，界面上不加任何前缀。
 *
 * @param {object} graph 宿主图（根图或子图）
 * @param {boolean} includeSubgraphs 是否连子图内部的编组一起收集
 */
export function buildEntries(graph, includeSubgraphs) {
    if (!graph) return [];

    const graphs = [graph];
    if (includeSubgraphs) {
        for (const sg of descendantSubgraphs(graph)) graphs.push(sg);
    }

    const out = [];
    graphs.forEach((g, gi) => {
        const groups = (g && g._groups) || [];
        if (!groups.length) return;
        const isHost = (g === graph);
        const gid = gidOf(g);
        groups.forEach(gr => {
            const title = (gr.title || "").trim() || "Unnamed";
            out.push({
                title,
                label: title,
                key: isHost ? title : `sg:${gid}:${title}`,
                bounds: gBounds(gr),
                ref: gr,
                color: getGroupColor(gr),
                graph: g,
                gid,
                order: gi,
            });
        });
    });
    return out;
}

/**
 * 组内节点 = 落在组矩形里的节点。
 * 只在本组所属的那张图里找；完全落在组内的其它组（嵌套子组）也算进来。
 *
 * @param {object} entry 分组条目
 * @param {object[]} entries 同一批分组条目（用来判断嵌套）
 * @param {object} [fallbackGraph] entry 没带 graph 时用它兜底
 */
export function collectNodes(entry, entries, fallbackGraph) {
    const g = entry.graph || fallbackGraph;
    if (!g || !g._nodes) return [];
    const all = entries || [];
    const pb = entry.bounds;
    const rects = [pb];
    all.forEach(ag => {
        if (ag.graph === g && ag.ref !== entry.ref && inside(ag.bounds, pb)) {
            rects.push(ag.bounds);
        }
    });
    return g._nodes.filter(n => {
        const nb = nBounds(n);
        return rects.some(r => hit(nb, r));
    });
}

/** 逐层找出所有嵌套子组（父组开关要联动子组），限制在同一张图内。 */
export function getAllNestedGroups(entry, entries) {
    const all = entries || [];
    const g = entry.graph;
    const result = [];
    const visited = new Set();
    visited.add(entry.ref);
    function findNested(parent) {
        all.forEach(ag => {
            if (ag.graph !== g) return;
            if (!visited.has(ag.ref) && inside(ag.bounds, parent.bounds)) {
                visited.add(ag.ref);
                result.push(ag);
                findNested(ag);
            }
        });
    }
    findNested(entry);
    return result;
}

// ── 开关 ──

/** 节点当前是否算「开着」：没被 Mute(2)、没被 Bypass(4)、也没被 flags.disabled。 */
export function isNodeActive(n) {
    return n.mode !== 4 && n.mode !== 2 && !n.flags?.disabled;
}

/** true = 全开，false = 全关，null = 半开（混合状态）。 */
export function getGroupState(entry, entries) {
    const nodes = collectNodes(entry, entries);
    if (nodes.length === 0) return true;
    const allActive = nodes.every(n => isNodeActive(n));
    const allInactive = nodes.every(n => !isNodeActive(n));
    if (allActive) return true;
    if (allInactive) return false;
    return null;
}

/** 关闭一组：disable ? Mute(2) : Bypass(4)。 */
export function bypassGroup(entry, entries, disable) {
    collectNodes(entry, entries).forEach(n => {
        if (disable) n.mode = 2;
        else n.mode = 4;
    });
}

/** 打开一组：mode 归零，并清掉另一套禁用标记 flags.disabled。 */
export function restoreGroup(entry, entries) {
    collectNodes(entry, entries).forEach(n => {
        n.mode = 0;
        if (n.flags) n.flags.disabled = false;
    });
}
