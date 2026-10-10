import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ══════════════════════════════════════════════════════════════
//  MK-提示词大全 / MK Prompt Library —— 前端
//
//  以 web/prompt_preset.js（MK-提示词预设管理）为原型派生的「图片化提示词库」。
//
//  相对预设管理节点：
//   1. 「提示词预设管理」按钮 -> 「提示词预设选择」；
//   2. 去掉「提示词类型 / 提示词细分」两个下拉控件；
//   3. 分类结构由扁平「类型 / 细分」改为**多级嵌套树**；
//   4. 细分列表改为**缩略图网格**，点图即把提示词写入文本框；
//   5. 新增缩略图上传（只保存压缩图，原图不落盘），走后端 /mk_prompt_asset。
//
//  命名隔离：storage key 用 mk_prompt_library*，CSS 类用 mk-pl-*，
//  全局变量用 MK_PromptLibrary_* / _mkPl*，与预设管理节点互不覆盖。
//  数据亦独立（key = mk_prompt_library），两节点提示词库互不影响。
// ══════════════════════════════════════════════════════════════

// ── 内联：界面语言检测（同 prompt_preset.js） ──
function mkLang() {
    let v = "";
    try { v = app?.ui?.settings?.settingsLookup?.["Comfy.Locale"]?.value || ""; } catch (e) {}
    if (!v) { try { v = app?.ui?.settings?.getSettingValue?.("Comfy.Locale") || ""; } catch (e) {} }
    if (!v) { try { v = document.documentElement.lang || ""; } catch (e) {} }
    v = String(v || "").toLowerCase();
    if (v.startsWith("zh")) return "zh";
    if (v) return "en";
    return "zh";
}
function _pl_(zh, en) { return mkLang() === "en" ? en : zh; }

// ── 内联：存储层（复用后端 /mk_prompt_store，见 nodes/prompt_preset.py） ──
const MK_PL_UI_KEY = "mk_prompt_library_ui_state";
const MK_PL_GEOMETRY_KEYS = ["mk_prompt_library_picker_geometry"];
const _plPending = new Map();
let _plUiInit = null;
let _plUiTimer = null;

function mkLocalGet(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
function mkLocalSet(key, val) { try { localStorage.setItem(key, val); } catch (e) {} }

async function _plFetchJson(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
}

function mkStoreLoad(key, { fallbackValue = null } = {}) {
    let loc = null;
    const locStr = mkLocalGet(key);
    if (locStr != null) { try { loc = JSON.parse(locStr); } catch (e) { loc = null; } }
    if (_plPending.has(key)) {
        const p = _plPending.get(key);
        return p.catch(() => loc ?? fallbackValue);
    }
    const p = (async () => {
        const url = api.apiURL("/mk_prompt_store?key=" + encodeURIComponent(key));
        try {
            const r = await _plFetchJson(url);
            if (r && r.found && r.data != null) {
                mkLocalSet(key, JSON.stringify(r.data));
                return r.data;
            }
            if (loc != null) { mkStoreSave(key, loc).catch(() => {}); return loc; }
            return fallbackValue;
        } catch (e) {
            return loc ?? fallbackValue;
        }
    })();
    _plPending.set(key, p);
    const finish = () => _plPending.delete(key);
    p.then(finish, finish);
    return p;
}

function mkStoreSave(key, data) {
    mkLocalSet(key, JSON.stringify(data));
    const url = api.apiURL("/mk_prompt_store");
    return _plFetchJson(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, data }),
    }).catch(() => {});
}

function _plStoreUIInit() {
    if (_plUiInit) return _plUiInit;
    _plUiInit = (async () => {
        try {
            const url = api.apiURL("/mk_prompt_store?key=" + encodeURIComponent(MK_PL_UI_KEY));
            const r = await _plFetchJson(url);
            const remote = (r && r.found && r.data && typeof r.data === "object") ? r.data : null;
            if (remote) {
                let wrote = false;
                for (const k of MK_PL_GEOMETRY_KEYS) {
                    if (Object.prototype.hasOwnProperty.call(remote, k) && remote[k] !== undefined) {
                        const v = remote[k];
                        mkLocalSet(k, typeof v === "object" ? JSON.stringify(v) : String(v));
                        wrote = true;
                    }
                }
                if (!wrote) _plPushGeometryToCloud();
            } else {
                _plPushGeometryToCloud();
            }
        } catch (e) {}
    })();
    return _plUiInit;
}

function _plReadGeometryMap() {
    const map = {};
    for (const k of MK_PL_GEOMETRY_KEYS) { const v = mkLocalGet(k); if (v != null) map[k] = v; }
    return map;
}

function _plPushGeometryToCloud() {
    const map = _plReadGeometryMap();
    if (Object.keys(map).length) mkStoreSave(MK_PL_UI_KEY, map).catch(() => {});
}

function _plStoreQueueGeometry() {
    if (_plUiTimer) clearTimeout(_plUiTimer);
    _plUiTimer = setTimeout(() => { _plUiTimer = null; _plPushGeometryToCloud(); }, 400);
}

// ═══════════════════════════════════════════════
//  常量
// ═══════════════════════════════════════════════
const _NODE_TYPE = "MK_PromptLibrary";
const _NODE_NAME_ZH = "MK-提示词大全";
const _NODE_NAME_EN = "MK Prompt Library";
const _LIB_KEY = "mk_prompt_library";
const _LIB_VERSION = 1;
const _FAV_ID = "c_favorites";
const _ASSET_ROUTE = "/mk_prompt_asset";
const _THUMB_MAX = 320;          // 缩略图最长边（px），小图不放大
const _NO_IMAGE = { zh: "无图", en: "No image" };
// 拖拽类型：dragover 里浏览器禁止读取 dataTransfer 的值（只能看 types），
// 因此把「父级 id」编码进类型名，用 types 判断是否为同级拖拽。
const _NODE_DRAG_TYPE = "application/x-mk-pl-node";
const _NODE_PARENT_TYPE_PREFIX = "application/x-mk-pl-parent-";

let _libRestorePromise = null;

// ═══════════════════════════════════════════════
//  数据模型
// ═══════════════════════════════════════════════
function _libNewId(prefix) {
    return prefix + "_" + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4);
}

function _libNormalizeItem(item) {
    if (!item || typeof item !== "object") return null;
    return {
        id: typeof item.id === "string" && item.id ? item.id : _libNewId("p"),
        name: String(item.name || ""),
        prompt: typeof item.prompt === "string" ? item.prompt : "",
        thumb: typeof item.thumb === "string" ? item.thumb : "",
        order: Number.isFinite(item.order) ? item.order : 0,
    };
}

function _libNormalizeNode(node) {
    if (!node || typeof node !== "object") return null;
    const n = {
        id: typeof node.id === "string" && node.id ? node.id : _libNewId("c"),
        name: String(node.name || ""),
        order: Number.isFinite(node.order) ? node.order : 0,
        children: [],
        items: [],
    };
    n.children = (Array.isArray(node.children) ? node.children : []).map(_libNormalizeNode).filter(Boolean);
    n.items = (Array.isArray(node.items) ? node.items : []).map(_libNormalizeItem).filter(Boolean);
    return n;
}

function _libNormalize(data) {
    const out = { version: _LIB_VERSION, tree: [] };
    if (!data || typeof data !== "object") return out;
    out.tree = (Array.isArray(data.tree) ? data.tree : []).map(_libNormalizeNode).filter(Boolean);
    return out;
}

function _libEnsureFavorites(lib) {
    if (!lib.tree.some(n => n.id === _FAV_ID)) {
        lib.tree.unshift({
            id: _FAV_ID, name: _pl_("收藏", "Favorites"), order: -10000,
            children: [], items: [],
        });
    }
    return lib;
}

function _libEnsureDefaultCategory(lib) {
    if (!lib.tree.some(n => n.id !== _FAV_ID)) {
        lib.tree.push({
            id: _libNewId("c"), name: _pl_("默认分类", "Default"), order: 1000,
            children: [], items: [],
        });
    }
    return lib;
}

function _libWalk(nodes, fn, parent = null, depth = 0) {
    for (const node of nodes) {
        fn(node, parent, depth);
        _libWalk(node.children, fn, node, depth + 1);
    }
}

function _libFindPath(nodes, id, trail = []) {
    for (const node of nodes) {
        const next = [...trail, node];
        if (node.id === id) return next;
        const r = _libFindPath(node.children, id, next);
        if (r) return r;
    }
    return null;
}

function _libFindNode(lib, id) {
    const path = _libFindPath(lib.tree, id);
    return path ? path[path.length - 1] : null;
}

function _libSiblingsOf(lib, id) {
    const path = _libFindPath(lib.tree, id);
    if (!path) return null;
    return path.length === 1 ? lib.tree : path[path.length - 2].children;
}

/** 父级标识：根级返回 "root"，否则返回父节点 id（用于拖拽同级判定）。 */
function _libParentKey(lib, id) {
    const path = _libFindPath(lib.tree, id);
    if (!path || path.length <= 1) return "root";
    return path[path.length - 2].id;
}

function _libSortNodes(list) {
    return [...list].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.name.localeCompare(b.name));
}
function _libSortItems(list) {
    return [...list].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.name.localeCompare(b.name));
}

function _libCollectNodes(lib) {
    const out = [];
    _libWalk(lib.tree, (node, _parent, depth) => {
        out.push({ node, depth });
    });
    return out;
}

function _libNodePath(lib, id) {
    const path = _libFindPath(lib.tree, id);
    if (!path) return "";
    return path.map(n => n.id === _FAV_ID ? _pl_("收藏", "Favorites") : (n.name || "未命名")).join(" / ");
}

// ── 加载 / 保存 ──
async function _loadLibrary(force = false) {
    if (!force && _libRestorePromise) return _libRestorePromise;
    _libRestorePromise = mkStoreLoad(_LIB_KEY, { fallbackValue: { version: _LIB_VERSION, tree: [] } })
        .then(data => {
            const lib = _libEnsureDefaultCategory(_libEnsureFavorites(_libNormalize(data)));
            try { localStorage.setItem(_LIB_KEY, JSON.stringify(lib)); } catch (_) {}
            return lib;
        })
        .catch(() => _libEnsureDefaultCategory(_libEnsureFavorites(_libNormalize(null))));
    return _libRestorePromise;
}

async function _saveLibrary(lib) {
    _libEnsureFavorites(lib);
    _libRestorePromise = Promise.resolve(lib);
    const result = await mkStoreSave(_LIB_KEY, lib);
    return result?.ok === true;
}

// ═══════════════════════════════════════════════
//  缩略图：生成 / 上传 / 删除 / 取址
// ═══════════════════════════════════════════════
function _mkLoadImageFromFile(file) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(_pl_("图片解码失败", "Failed to decode image"))); };
        img.src = url;
    });
}

/** 读取图片文件 → canvas 等比缩到最长边 320px → 导出 WebP(0.8)，不支持则回退 JPEG。 */
async function _mkMakeThumbDataUrl(file) {
    const img = await _mkLoadImageFromFile(file);
    const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
    if (!w || !h) throw new Error(_pl_("空图片", "Empty image"));
    const scale = Math.min(1, _THUMB_MAX / Math.max(w, h));
    const tw = Math.max(1, Math.round(w * scale)), th = Math.max(1, Math.round(h * scale));
    const canvas = document.createElement("canvas");
    canvas.width = tw; canvas.height = th;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, tw, th);
    let dataUrl = canvas.toDataURL("image/webp", 0.8);
    if (!/^data:image\/webp/i.test(dataUrl)) dataUrl = canvas.toDataURL("image/jpeg", 0.8);
    return dataUrl;
}

async function _mkUploadAsset(dataUrl) {
    const res = await fetch(api.apiURL(_ASSET_ROUTE), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataUrl }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const r = await res.json();
    if (!r || !r.ok || !r.name) throw new Error(r?.error || _pl_("上传失败", "Upload failed"));
    return r.name;
}

function _mkDeleteAsset(name) {
    if (!name) return;
    fetch(api.apiURL(_ASSET_ROUTE), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "delete", name }),
    }).catch(() => {});
}

function _mkAssetUrl(name) {
    return api.apiURL(_ASSET_ROUTE + "?name=" + encodeURIComponent(name));
}

// ═══════════════════════════════════════════════
//  写回节点文本框
// ═══════════════════════════════════════════════
function _libSetNodeText(node, text) {
    const widget = node.widgets?.find(w => w?.name === "text");
    if (!widget) return false;
    widget.value = text;
    try { widget.callback?.(text); } catch (_) {}
    const el = widget.element || widget.inputEl;
    if (el && "value" in el && el.value !== text) {
        el.value = text;
        el.dispatchEvent(new Event("input", { bubbles: true }));
    }
    try { app.graph?.change?.(); } catch (_) {}
    return true;
}

// ═══════════════════════════════════════════════
//  收藏（右键文本框 → 收藏到提示词库）
// ═══════════════════════════════════════════════
async function _libAddFavorite(prompt) {
    const text = String(prompt || "").trim();
    if (!text) return false;
    const lib = _libEnsureFavorites(await _loadLibrary(true));
    const fav = _libFindNode(lib, _FAV_ID);
    const snippet = text.replace(/\s+/g, " ").slice(0, 36) || _pl_("提示词", "Prompt");
    let name = snippet, i = 2;
    while (fav.items.some(it => it.name === name)) name = `${snippet} (${i++})`;
    const order = fav.items.reduce((m, it) => Math.max(m, it.order ?? 0), 0) + 1000;
    fav.items.push({ id: _libNewId("p"), name, prompt: text, thumb: "", order });
    await _saveLibrary(lib);
    _syncAllLibraryWidgets(lib);
    window.dispatchEvent(new CustomEvent("mk:prompt-library-changed", { detail: lib }));
    return true;
}

// ═══════════════════════════════════════════════
//  弹窗：提示词预设选择
// ═══════════════════════════════════════════════
async function _openLibraryPicker(node) {
    try { await _plStoreUIInit(); } catch (_) {}
    let lib = _libEnsureDefaultCategory(_libEnsureFavorites(await _loadLibrary(true)));
    const zh = mkLang() !== "en";
    const geometryKey = "mk_prompt_library_picker_geometry";

    // ── 骨架 ──
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;z-index:2000005;background:#0009;display:block;padding:20px;box-sizing:border-box";
    const dialog = document.createElement("div");
    dialog.style.cssText = "box-sizing:border-box;position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(880px,calc(100vw - 40px));height:min(720px,calc(100vh - 40px));display:flex;flex-direction:column;background:#202124;color:#fff;border:1px solid #555;border-radius:8px;box-shadow:0 16px 48px #0009;font:13px Arial,sans-serif;overflow:hidden";
    dialog.innerHTML =
        `<div data-titlebar style="display:flex;align-items:center;padding:13px 16px;border-bottom:1px solid #444;font-size:15px;font-weight:600;flex:none;user-select:none;-webkit-user-select:none;cursor:move">`
        + `<span data-title style="flex:1;color:#e7b94f">${zh ? "提示词大全" : "Prompt Library"}</span>`
        + `<button data-close style="background:transparent;border:0;border-radius:0;color:#e7b94f;padding:5px 8px;font:14px Arial,sans-serif;font-weight:700;cursor:pointer">${zh ? "完成" : "Done"}</button>`
        + `</div>`
        + `<div data-home style="display:flex;flex:1;min-height:0;padding:0;overflow:hidden;user-select:none;-webkit-user-select:none">`
        + `  <aside data-left-pane style="box-sizing:border-box;flex:0 0 34%;width:34%;min-width:170px;max-width:80%;display:flex;flex-direction:column;min-height:0;padding:12px 10px;overflow:hidden">`
        + `    <div style="display:flex;align-items:center;gap:8px;padding:0 4px 10px"><span style="flex:1;color:#fff;font-weight:600">${zh ? "分类" : "Categories"}</span><button type="button" data-add-category title="${zh ? "新建顶级分类" : "New top-level category"}" style="width:28px;height:28px;background:#303030;color:#e7b94f;border:1px solid #454545;border-radius:4px;font-size:18px;line-height:1;cursor:pointer">+</button></div>`
        + `    <div data-tree-list style="display:flex;flex-direction:column;gap:2px;overflow:auto;min-height:0;flex:1"></div>`
        + `  </aside>`
        + `  <div data-split-divider style="width:4px;flex:none;background:#3a3a3a;cursor:col-resize"></div>`
        + `  <section data-right-pane style="box-sizing:border-box;flex:1 1 0;min-width:0;display:flex;flex-direction:column;min-height:0;padding:12px 14px">`
        + `    <div style="display:flex;align-items:center;gap:8px;padding:0 2px 10px;border-bottom:1px solid #3a3a3a"><span data-right-title style="flex:1;color:#fff;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${zh ? "提示词" : "Prompts"}</span><span data-right-count style="flex:none;color:#8a8f98;font-size:12px"></span>`
        + `      <button type="button" data-upload style="background:#2f6b46;color:#fff;border:0;border-radius:4px;padding:5px 10px;cursor:pointer;font-size:12px">${zh ? "上传配图" : "Upload image"}</button>`
        + `      <button type="button" data-add-item style="background:#343b49;color:#fff;border:0;border-radius:4px;padding:5px 10px;cursor:pointer;font-size:12px">${zh ? "新增条目" : "New item"}</button>`
        + `    </div>`
        + `    <div data-batch-bar style="display:none;align-items:center;gap:8px;padding:6px 2px;border-bottom:1px solid #3a3a3a"><span data-batch-count style="color:#e7b94f;font-size:12px;font-weight:600;flex:none"></span><span style="flex:1"></span><button type="button" data-batch-all style="background:transparent;color:#9db7a6;border:0;padding:3px 6px;cursor:pointer;font-size:12px">${zh ? "全选" : "Select all"}</button><button type="button" data-batch-move style="background:#343b49;color:#e7b94f;border:1px solid #555;border-radius:4px;padding:3px 8px;cursor:pointer;font-size:12px">${zh ? "移动到…" : "Move to…"}</button><button type="button" data-batch-clear style="background:transparent;color:#c75c5c;border:0;padding:3px 6px;cursor:pointer;font-size:12px">${zh ? "取消选择" : "Clear"}</button></div>`
        + `    <div data-grid style="display:flex;flex-wrap:wrap;gap:10px;align-content:flex-start;overflow:auto;padding:6px 2px;flex:1;min-height:0"></div>`
        + `  </section>`
        + `</div>`
        + `<div data-editor style="display:none;flex:1;flex-direction:column;min-height:0;padding:12px 16px">`
        + `  <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px"><select data-editor-cat style="flex:0 0 42%;padding:5px 8px;background:#151617;color:#9db7a6;border:1px solid #151617;border-radius:4px;font-size:13px"></select><input data-editor-name type="text" spellcheck="false" placeholder="${zh ? "条目名称" : "Item name"}" style="flex:1;min-width:0;padding:5px 8px;background:#151617;color:#eee;border:1px solid #151617;border-radius:4px;font-size:13px" /></div>`
        + `  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">`
        + `    <div data-editor-thumb style="width:72px;height:72px;flex:none;border:1px solid #3a3a3a;border-radius:5px;background:#151617 center/contain no-repeat;display:flex;align-items:center;justify-content:center;color:#5a5f66;font-size:11px">${zh ? "无图" : "No image"}</div>`
        + `    <div style="display:flex;flex-direction:column;gap:6px"><button type="button" data-editor-img style="background:#343b49;color:#fff;border:1px solid #555;border-radius:4px;padding:5px 9px;cursor:pointer;font-size:12px">${zh ? "更换图片" : "Change image"}</button><button type="button" data-editor-rmimg style="background:#343b49;color:#c75c5c;border:1px solid #555;border-radius:4px;padding:5px 9px;cursor:pointer;font-size:12px">${zh ? "删除图片" : "Remove image"}</button></div>`
        + `    <div style="flex:1"></div>`
        + `  </div>`
        + `  <div style="display:flex;gap:8px;justify-content:flex-end;padding:0 0 10px"><button type="button" data-import style="background:#343b49;color:#fff;border:1px solid #555;border-radius:4px;padding:5px 9px;cursor:pointer;font-size:12px">${zh ? "导入 .txt / .md" : "Import .txt / .md"}</button><button type="button" data-back style="background:#343b49;color:#fff;border:1px solid #555;border-radius:4px;padding:5px 9px;cursor:pointer;font-size:12px">${zh ? "取消" : "Cancel"}</button><button type="button" data-save style="background:#2f6b46;color:#fff;border:0;border-radius:4px;padding:5px 10px;cursor:pointer;font-size:12px">${zh ? "保存" : "Save"}</button></div>`
        + `  <textarea data-editor-text spellcheck="false" placeholder="${zh ? "在此填写该条目的提示词…" : "Write the prompt for this item…"}" style="box-sizing:border-box;flex:1;min-height:100px;resize:none;padding:10px;background:#151617;color:#eee;border:1px solid #151617;border-radius:5px;font:12px/1.5 Consolas,monospace"></textarea>`
        + `</div>`
        + `<div data-resize title="${zh ? "拖动调整窗口大小" : "Drag to resize"}" style="position:absolute;right:1px;bottom:1px;width:18px;height:18px;cursor:nwse-resize;touch-action:none;user-select:none;background:linear-gradient(135deg,transparent 0 48%,#666 49% 55%,transparent 56% 66%,#888 67% 73%,transparent 74%)"></div>`;
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    // ── 样式 ──
    const style = document.createElement("style");
    style.textContent = `
        .mk-pl-tree-row { display:flex; align-items:center; gap:5px; padding:6px 8px; border-radius:4px; cursor:pointer; color:#ddd; min-width:0; }
        .mk-pl-tree-row:hover { background:#2c2e33; }
        .mk-pl-tree-row.active { background:#343b49; color:#fff; box-shadow: inset 2px 0 0 #e7b94f; }
        .mk-pl-tree-row.mk-pl-dragging { opacity:.5; border:1px dashed #4CAF50; }
        .mk-pl-tree-toggle { flex:none; width:14px; text-align:center; color:#9aa0a6; font-size:11px; line-height:1; }
        .mk-pl-tree-label { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .mk-pl-tree-count { flex:none; color:#8a8f98; font-size:11px; }
        .mk-pl-tree-btn { flex:none; background:transparent; border:0; color:#9aa0a6; cursor:pointer; font-size:13px; padding:1px 3px; border-radius:3px; line-height:1; }
        .mk-pl-tree-btn:hover { background:#3a3d44; color:#fff; }
        .mk-pl-fav { color:#e7b94f !important; font-weight:700; }
        .mk-pl-card { width:134px; border:1px solid #3a3a3a; border-radius:6px; background:#2a2c30; overflow:hidden; cursor:pointer; display:flex; flex-direction:column; transition:border-color .15s, box-shadow .15s; }
        .mk-pl-card:hover { border-color:#6b7077; }
        .mk-pl-card.mk-pl-picked { border-color:#e7b94f; box-shadow:0 0 0 1px #e7b94f inset; }
        .mk-pl-card.mk-pl-checked { border-color:#9db7a6; box-shadow:0 0 0 1px #9db7a6 inset; }
        .mk-pl-card.mk-pl-dragging { opacity:.5; border:1px dashed #4CAF50; }
        .mk-pl-thumb { width:100%; height:98px; background:#151617; display:flex; align-items:center; justify-content:center; color:#5a5f66; font-size:11px; overflow:hidden; }
        .mk-pl-thumb img { width:100%; height:100%; object-fit:contain; display:block; }
        .mk-pl-card-name { padding:5px 7px; font-size:12px; color:#eaeaea; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .mk-pl-card-actions { display:flex; border-top:1px solid #383a3f; }
        .mk-pl-card-actions button { flex:1; background:transparent; border:0; border-right:1px solid #383a3f; color:#b8bcc2; cursor:pointer; font-size:11px; padding:4px 0; }
        .mk-pl-card-actions button:last-child { border-right:0; }
        .mk-pl-card-actions button:hover { background:#3a3d44; color:#fff; }
        .mk-pl-card-actions button[data-act="del"]:hover { color:#c75c5c; }
        .mk-pl-insert-marker { flex:none; border-radius:2px; background:#4CAF50; box-shadow:0 0 6px rgba(76,175,80,.8); }
        .mk-pl-empty { width:100%; margin:auto; padding:24px; text-align:center; color:#9aa0a6; }
        .mk-pl-grid-drop { outline:2px dashed #4CAF50; outline-offset:-6px; }
        [data-editor] select:focus, [data-editor] input:focus, [data-editor] textarea:focus { outline:none !important; border:1px solid #888 !important; box-shadow:none !important; }
        input.mk-text-box-modal-input:focus { outline:none !important; border:1px solid #666 !important; }
    `;
    dialog.appendChild(style);

    overlay.addEventListener("contextmenu", e => { e.preventDefault(); e.stopPropagation(); });

    // ── 几何（记忆位置尺寸）──
    try {
        const saved = JSON.parse(localStorage.getItem(geometryKey) || "null");
        if (saved && [saved.left, saved.top, saved.width, saved.height].every(Number.isFinite)) {
            const width = Math.max(420, Math.min(innerWidth - 40, saved.width)), height = Math.max(340, Math.min(innerHeight - 40, saved.height));
            dialog.style.transform = "none"; dialog.style.width = `${width}px`; dialog.style.height = `${height}px`;
            dialog.style.left = `${Math.max(0, Math.min(innerWidth - width, saved.left))}px`;
            dialog.style.top = `${Math.max(0, Math.min(innerHeight - height, saved.top))}px`;
        }
    } catch (_) {}

    const titleBar = dialog.querySelector("[data-titlebar]");
    titleBar.addEventListener("pointerdown", event => {
        if (event.button !== 0 || event.target.closest("button")) return;
        event.preventDefault();
        const rect = dialog.getBoundingClientRect(), sx = event.clientX, sy = event.clientY;
        dialog.style.transform = "none"; dialog.style.left = `${rect.left}px`; dialog.style.top = `${rect.top}px`;
        const move = e => {
            dialog.style.left = `${Math.max(0, Math.min(innerWidth - rect.width, rect.left + e.clientX - sx))}px`;
            dialog.style.top = `${Math.max(0, Math.min(innerHeight - rect.height, rect.top + e.clientY - sy))}px`;
        };
        const end = () => {
            titleBar.removeEventListener("pointermove", move);
            const r = dialog.getBoundingClientRect();
            try { localStorage.setItem(geometryKey, JSON.stringify({ left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) })); } catch (_) {}
            _plStoreQueueGeometry();
        };
        titleBar.setPointerCapture(event.pointerId);
        titleBar.addEventListener("pointermove", move);
        titleBar.addEventListener("pointerup", end, { once: true });
        titleBar.addEventListener("pointercancel", end, { once: true });
    });
    const resizeHandle = dialog.querySelector("[data-resize]");
    resizeHandle.addEventListener("pointerdown", event => {
        if (event.button !== 0) return;
        event.preventDefault(); event.stopPropagation();
        const rect = dialog.getBoundingClientRect(), sx = event.clientX, sy = event.clientY, sw = rect.width, sh = rect.height;
        dialog.style.transform = "none"; dialog.style.left = `${rect.left}px`; dialog.style.top = `${rect.top}px`;
        const move = e => {
            const width = Math.max(460, Math.min(innerWidth - rect.left - 20, sw + e.clientX - sx));
            const height = Math.max(360, Math.min(innerHeight - rect.top - 20, sh + e.clientY - sy));
            dialog.style.width = `${width}px`; dialog.style.height = `${height}px`;
        };
        const end = () => {
            resizeHandle.removeEventListener("pointermove", move);
            const r = dialog.getBoundingClientRect();
            try { localStorage.setItem(geometryKey, JSON.stringify({ left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) })); } catch (_) {}
            _plStoreQueueGeometry();
        };
        resizeHandle.setPointerCapture(event.pointerId);
        resizeHandle.addEventListener("pointermove", move);
        resizeHandle.addEventListener("pointerup", end, { once: true });
        resizeHandle.addEventListener("pointercancel", end, { once: true });
    });

    // ── 左栏分隔条拖动 ──
    const home = dialog.querySelector("[data-home]");
    const leftPane = home.querySelector("[data-left-pane]");
    const splitDivider = home.querySelector("[data-split-divider]");
    splitDivider.addEventListener("pointerdown", event => {
        if (event.button !== 0) return;
        event.preventDefault();
        const startX = event.clientX, startWidth = leftPane.getBoundingClientRect().width, bounds = home.getBoundingClientRect();
        const move = e => {
            const width = Math.max(150, Math.min(bounds.width - 260, startWidth + e.clientX - startX));
            leftPane.style.width = `${width}px`; leftPane.style.flex = `0 0 ${width}px`;
        };
        const end = () => splitDivider.removeEventListener("pointermove", move);
        splitDivider.setPointerCapture(event.pointerId);
        splitDivider.addEventListener("pointermove", move);
        splitDivider.addEventListener("pointerup", end, { once: true });
        splitDivider.addEventListener("pointercancel", end, { once: true });
    });

    // ── DOM 引用 ──
    const treeList = home.querySelector("[data-tree-list]");
    const grid = home.querySelector("[data-grid]");
    const rightTitle = home.querySelector("[data-right-title]");
    const rightCount = home.querySelector("[data-right-count]");
    const batchBar = home.querySelector("[data-batch-bar]");
    const batchCount = home.querySelector("[data-batch-count]");
    const batchAll = home.querySelector("[data-batch-all]");
    const batchMoveBtn = home.querySelector("[data-batch-move]");
    const batchClear = home.querySelector("[data-batch-clear]");
    const editorView = dialog.querySelector("[data-editor]");
    const title = dialog.querySelector("[data-title]");
    const closeButton = dialog.querySelector("[data-close]");
    const editorCat = dialog.querySelector("[data-editor-cat]");
    const editorName = dialog.querySelector("[data-editor-name]");
    const editorThumb = dialog.querySelector("[data-editor-thumb]");
    const editorText = dialog.querySelector("[data-editor-text]");

    // 隐藏文件输入
    const uploadInput = document.createElement("input");
    uploadInput.type = "file"; uploadInput.accept = "image/*"; uploadInput.multiple = true; uploadInput.style.display = "none";
    const replaceInput = document.createElement("input");
    replaceInput.type = "file"; replaceInput.accept = "image/*"; replaceInput.style.display = "none";
    overlay.append(uploadInput, replaceInput);

    // ── 通用小工具 ──
    const notify = message => {
        let note = dialog.querySelector("[data-notice]");
        if (!note) {
            note = document.createElement("div"); note.dataset.notice = "1";
            note.style.cssText = "position:absolute;z-index:5;top:56px;left:50%;transform:translateX(-50%);max-width:calc(100% - 32px);padding:8px 12px;background:#343b49;color:#fff;border:1px solid #555;border-radius:5px;box-shadow:0 4px 12px #0008;pointer-events:none;text-align:center";
            dialog.appendChild(note);
        }
        note.textContent = message;
        clearTimeout(note._timer);
        note._timer = setTimeout(() => note.remove(), 3200);
    };
    const mkButton = (label, action, danger = false) => {
        const b = document.createElement("button"); b.type = "button"; b.textContent = label;
        b.style.cssText = `position:relative;z-index:1;pointer-events:auto;background:${danger ? "#492d2d" : "#343b49"};color:#fff;border:1px solid #555;border-radius:4px;padding:5px 9px;cursor:pointer;white-space:nowrap`;
        b.addEventListener("click", event => { event.stopPropagation(); action(event); });
        return b;
    };
    const mask = () => {
        const shade = document.createElement("div"); shade.dataset.modal = "1";
        shade.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:#000a;display:flex;align-items:center;justify-content:center;padding:20px;pointer-events:auto";
        const box = document.createElement("div");
        box.style.cssText = "width:min(440px,100%);padding:16px;background:#25282c;color:#fff;border:1px solid #555;border-radius:7px;box-shadow:0 12px 36px #0009;font:13px Arial,sans-serif";
        shade.appendChild(box); document.body.appendChild(shade);
        return { shade, box };
    };
    const askText = (label, initial = "") => new Promise(resolve => {
        const { shade, box } = mask();
        const head = document.createElement("div"); head.textContent = label; head.style.cssText = "font-weight:600;margin-bottom:12px";
        const input = document.createElement("input"); input.value = initial; input.maxLength = 100; input.className = "mk-text-box-modal-input";
        input.style.cssText = "box-sizing:border-box;width:100%;padding:8px;background:#151617;color:#fff;border:1px solid #555;border-radius:4px";
        const actions = document.createElement("div"); actions.style.cssText = "display:flex;justify-content:flex-end;gap:8px;margin-top:14px";
        const finish = value => { document.removeEventListener("keydown", onKey, true); shade.remove(); resolve(value); };
        const onKey = e => { if (e.key === "Escape") finish(null); };
        input.addEventListener("keydown", e => { if (e.key === "Enter") finish(input.value.trim()); });
        document.addEventListener("keydown", onKey, true);
        actions.append(mkButton(zh ? "取消" : "Cancel", () => finish(null)), mkButton(zh ? "确定" : "OK", () => finish(input.value.trim())));
        box.append(head, input, actions);
        setTimeout(() => { input.focus(); input.select(); }, 0);
    });
    const askConfirm = (message, dangerLabel) => new Promise(resolve => {
        const { shade, box } = mask();
        const text = document.createElement("div"); text.textContent = message; text.style.cssText = "line-height:1.5;white-space:pre-wrap";
        const actions = document.createElement("div"); actions.style.cssText = "display:flex;justify-content:flex-end;gap:8px;margin-top:14px";
        const finish = value => { document.removeEventListener("keydown", onKey, true); shade.remove(); resolve(value); };
        const onKey = e => { if (e.key === "Escape") finish(false); };
        document.addEventListener("keydown", onKey, true);
        const del = mkButton(dangerLabel || (zh ? "删除" : "Delete"), () => finish(true), true); del.style.color = "#c75c5c";
        actions.append(mkButton(zh ? "取消" : "Cancel", () => finish(false)), del);
        box.append(text, actions);
    });
    const showMoveMenu = (items, x, y) => {
        const list = Array.isArray(items) ? items.filter(Boolean) : [items].filter(Boolean);
        if (!list.length) return;
        const targets = _libCollectNodes(lib);
        if (!targets.length) { notify(zh ? "没有分类可移动" : "No categories"); return; }
        document.querySelector(".mk-pl-move-menu")?.remove();
        const menu = document.createElement("div");
        menu.className = "mk-pl-move-menu";
        menu.style.cssText = `position:fixed;z-index:2147483647;left:${x}px;top:${y}px;min-width:170px;max-height:280px;overflow:auto;background:#2a2a2a;border:1px solid #555;border-radius:5px;box-shadow:0 4px 14px #0009;padding:4px 0`;
        for (const { node: n, depth } of targets) {
            const entry = document.createElement("div");
            entry.textContent = (n.id === _FAV_ID ? "★ " + (zh ? "收藏" : "Favorites") : (n.name || "未命名"));
            entry.style.cssText = `padding:7px 12px 7px ${12 + depth * 14}px;cursor:pointer;color:#ddd;font-size:13px;white-space:nowrap`;
            entry.addEventListener("mouseenter", () => { entry.style.background = "#3a3a3a"; entry.style.color = "#e7b94f"; });
            entry.addEventListener("mouseleave", () => { entry.style.background = "transparent"; entry.style.color = "#ddd"; });
            entry.addEventListener("click", async () => { menu.remove(); await moveItemsToNode(list, n.id); });
            menu.appendChild(entry);
        }
        document.body.appendChild(menu);
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth - 4) menu.style.left = `${window.innerWidth - rect.width - 4}px`;
        if (rect.bottom > window.innerHeight - 4) menu.style.top = `${window.innerHeight - rect.height - 4}px`;
        const dismiss = e => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("pointerdown", dismiss, true); } };
        setTimeout(() => document.addEventListener("pointerdown", dismiss, true), 0);
    };

    // ── 状态 ──
    let selectedId = lib.tree.find(n => n.id !== _FAV_ID)?.id || _FAV_ID;
    let pickedId = null;
    let editingItemId = null;
    const selectedKeys = new Set();   // 批量多选（存条目 id）
    const expanded = new Set();
    _libWalk(lib.tree, n => { if (n.children.length) expanded.add(n.id); });

    // ── 持久化 ──
    const persist = async () => {
        const ok = await _saveLibrary(lib);
        _syncAllLibraryWidgets(lib);
        if (!ok) notify(zh ? "保存失败，数据已暂存本地。" : "Save failed; data kept locally.");
        return ok;
    };

    // ── 树 & 网格渲染 ──
    let nodeInsert = null;   // { parentList, index }
    let itemInsert = null;   // { list, index }

    const clearMarker = root => root.querySelector(".mk-pl-insert-marker")?.remove();

    const renderTree = () => {
        treeList.replaceChildren();
        const build = (node, depth) => {
            const isFav = node.id === _FAV_ID;
            const row = document.createElement("div");
            row.className = "mk-pl-tree-row" + (selectedId === node.id ? " active" : "");
            row.dataset.nodeRow = "1";
            row.dataset.nodeId = node.id;
            row.style.paddingLeft = `${6 + depth * 14}px`;
            row.draggable = !isFav;

            const toggle = document.createElement("span");
            toggle.className = "mk-pl-tree-toggle";
            toggle.textContent = node.children.length ? (expanded.has(node.id) ? "▾" : "▸") : "·";
            toggle.addEventListener("click", e => {
                e.stopPropagation();
                if (!node.children.length) return;
                if (expanded.has(node.id)) expanded.delete(node.id); else expanded.add(node.id);
                renderTree();
            });

            const label = document.createElement("span");
            label.className = "mk-pl-tree-label" + (isFav ? " mk-pl-fav" : "");
            label.textContent = (isFav ? "★ " : "") + (node.name || (zh ? "未命名" : "Untitled"));
            label.title = _libNodePath(lib, node.id);

            const count = document.createElement("span");
            count.className = "mk-pl-tree-count";
            count.textContent = String(node.items.length);

            row.append(toggle, label, count);

            if (!isFav) {
                const addChild = document.createElement("button");
                addChild.type = "button"; addChild.className = "mk-pl-tree-btn"; addChild.textContent = "+"; addChild.title = zh ? "新建子分类" : "New subcategory";
                addChild.addEventListener("click", async e => { e.stopPropagation(); await createCategory(node); });
                const rename = document.createElement("button");
                rename.type = "button"; rename.className = "mk-pl-tree-btn"; rename.textContent = "✎"; rename.title = zh ? "重命名" : "Rename";
                rename.addEventListener("click", async e => { e.stopPropagation(); await renameCategory(node); });
                const del = document.createElement("button");
                del.type = "button"; del.className = "mk-pl-tree-btn"; del.textContent = "×"; del.title = zh ? "删除" : "Delete"; del.style.color = "#c75c5c";
                del.addEventListener("click", async e => { e.stopPropagation(); await removeCategory(node); });
                row.append(addChild, rename, del);
            }

            row.addEventListener("click", () => { selectedId = node.id; selectedKeys.clear(); renderAll(); });

            // 拖拽：同级重排（跨级请用「移动」按钮）
            if (!isFav) {
                row.addEventListener("dragstart", event => {
                    if (event.target.closest("button")) { event.preventDefault(); return; }
                    event.dataTransfer.effectAllowed = "move";
                    event.dataTransfer.setData(_NODE_DRAG_TYPE, node.id);
                    event.dataTransfer.setData(_NODE_PARENT_TYPE_PREFIX + _libParentKey(lib, node.id), "1");
                    row.classList.add("mk-pl-dragging");
                });
                row.addEventListener("dragend", () => { row.classList.remove("mk-pl-dragging"); clearMarker(treeList); nodeInsert = null; });
                row.addEventListener("dragover", event => {
                    const types = event.dataTransfer ? Array.from(event.dataTransfer.types) : [];
                    if (!types.includes(_NODE_DRAG_TYPE)) return;
                    const list = _libSiblingsOf(lib, node.id);
                    if (!list) return;
                    // 仅接受「同级」拖拽（dragover 读不到值，改用编码了父级的类型判断）
                    if (!types.includes(_NODE_PARENT_TYPE_PREFIX + _libParentKey(lib, node.id))) return;
                    event.preventDefault();
                    const rect = row.getBoundingClientRect();
                    const rows = [...treeList.querySelectorAll("[data-node-row]")].filter(r => _libSiblingsOf(lib, r.dataset.nodeId) === list);
                    const idx = rows.indexOf(row);
                    if (idx < 0) return;
                    const insertIndex = event.clientY - rect.top < rect.height / 2 ? idx : idx + 1;
                    nodeInsert = { list, index: insertIndex };
                    clearMarker(treeList);
                    const marker = document.createElement("div");
                    marker.className = "mk-pl-insert-marker";
                    marker.style.cssText = "height:3px;margin:0 4px";
                    const refRow = rows[insertIndex] || null;
                    treeList.insertBefore(marker, refRow);
                });
                row.addEventListener("drop", async event => {
                    const dragId = event.dataTransfer?.getData(_NODE_DRAG_TYPE);
                    if (!dragId || !nodeInsert) return;
                    event.preventDefault(); event.stopPropagation();
                    const { index } = nodeInsert;
                    nodeInsert = null; clearMarker(treeList);
                    const list = _libSiblingsOf(lib, dragId);
                    if (!list) return;
                    const from = list.findIndex(n => n.id === dragId);
                    if (from < 0) return;
                    const [moved] = list.splice(from, 1);
                    const to = from < index ? index - 1 : index;
                    list.splice(Math.max(0, Math.min(list.length, to)), 0, moved);
                    list.forEach((n, i) => { n.order = (i + 1) * 1000; });
                    await persist(); renderAll();
                });
            }

            treeList.appendChild(row);
            if (node.children.length && expanded.has(node.id)) {
                for (const child of _libSortNodes(node.children)) build(child, depth + 1);
            }
        };
        for (const rootNode of _libSortNodes(lib.tree)) build(rootNode, 0);
        if (!lib.tree.length) {
            const empty = document.createElement("div");
            empty.textContent = zh ? "还没有分类" : "No categories";
            empty.style.cssText = "padding:16px;text-align:center;color:#9aa0a6";
            treeList.appendChild(empty);
        }
    };

    const renderGrid = () => {
        grid.replaceChildren();
        const catNode = _libFindNode(lib, selectedId);
        const isFav = selectedId === _FAV_ID;
        rightTitle.textContent = catNode ? ((isFav ? "★ " : "") + (catNode.name || (zh ? "未命名" : "Untitled"))) : (zh ? "提示词" : "Prompts");
        const items = catNode ? _libSortItems(catNode.items) : [];
        rightCount.textContent = items.length ? (zh ? `${items.length} 条` : `${items.length} items`) : "";
        if (!catNode) return;
        // 批量多选栏（网格内有选中项时显示）
        const selectedInView = items.filter(it => selectedKeys.has(it.id));
        if (selectedInView.length) {
            batchBar.style.display = "flex";
            batchCount.textContent = zh ? `已选 ${selectedInView.length} 项` : `${selectedInView.length} selected`;
            batchAll.textContent = items.length && items.every(it => selectedKeys.has(it.id))
                ? (zh ? "取消全选" : "Deselect all") : (zh ? "全选" : "Select all");
        } else {
            batchBar.style.display = "none";
        }
        if (!items.length) {
            const empty = document.createElement("div");
            empty.className = "mk-pl-empty";
            empty.textContent = zh ? "这个分类还没有条目；点右上角「上传配图」或「新增条目」添加。" : "No items here yet. Use “Upload image” or “New item”.";
            grid.appendChild(empty);
            return;
        }
        for (const item of items) {
            const card = document.createElement("div");
            card.className = "mk-pl-card" + (pickedId === item.id ? " mk-pl-picked" : "") + (selectedKeys.has(item.id) ? " mk-pl-checked" : "");
            card.dataset.itemCard = "1";
            card.dataset.itemId = item.id;
            card.draggable = true;
            card.style.position = "relative";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox"; checkbox.checked = selectedKeys.has(item.id);
            checkbox.title = zh ? "多选" : "Select";
            checkbox.style.cssText = "position:absolute;left:5px;top:5px;z-index:2;width:16px;height:16px;cursor:pointer;accent-color:#e7b94f";
            checkbox.addEventListener("click", e => e.stopPropagation());
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) selectedKeys.add(item.id); else selectedKeys.delete(item.id);
                renderGrid();
            });
            card.appendChild(checkbox);

            const thumb = document.createElement("div");
            thumb.className = "mk-pl-thumb";
            if (item.thumb) {
                const img = document.createElement("img");
                img.src = _mkAssetUrl(item.thumb);
                img.loading = "lazy";
                img.alt = item.name || "";
                img.draggable = false;
                img.addEventListener("error", () => { thumb.textContent = zh ? "图片丢失" : "Missing image"; });
                thumb.appendChild(img);
            } else {
                thumb.textContent = zh ? _NO_IMAGE.zh : _NO_IMAGE.en;
            }

            const nameEl = document.createElement("div");
            nameEl.className = "mk-pl-card-name";
            nameEl.textContent = item.name || (zh ? "未命名" : "Untitled");
            nameEl.title = item.name || "";

            const actions = document.createElement("div");
            actions.className = "mk-pl-card-actions";
            const mkAct = (label, act, title) => {
                const b = document.createElement("button");
                b.type = "button"; b.textContent = label; b.dataset.act = act; b.title = title || label;
                b.addEventListener("click", e => { e.stopPropagation(); });
                return b;
            };
            const editBtn = mkAct(zh ? "编辑" : "Edit", "edit", zh ? "编辑名称与提示词" : "Edit name and prompt");
            editBtn.addEventListener("click", () => openEditor(item.id));
            const imgBtn = mkAct(zh ? "换图" : "Image", "img", zh ? "更换/上传配图" : "Change image");
            imgBtn.addEventListener("click", () => replaceItemImage(item));
            const moveBtn = mkAct(zh ? "移动" : "Move", "move", zh ? "移动到其他分类" : "Move to category");
            moveBtn.addEventListener("click", e => showMoveMenu([item], e.clientX, e.clientY));
            const delBtn = mkAct(zh ? "删除" : "Del", "del", zh ? "删除条目" : "Delete item");
            delBtn.addEventListener("click", async () => {
                if (!await askConfirm(zh ? `确定删除条目“${item.name}”？` : `Delete item “${item.name}”?`, zh ? "删除" : "Delete")) return;
                const idx = catNode.items.findIndex(i => i.id === item.id);
                if (idx >= 0) catNode.items.splice(idx, 1);
                if (item.thumb) _mkDeleteAsset(item.thumb);
                if (pickedId === item.id) pickedId = null;
                await persist(); renderGrid();
            });
            actions.append(editBtn, imgBtn, moveBtn, delBtn);

            card.addEventListener("click", () => {
                pickedId = item.id;
                _libSetNodeText(node, item.prompt);
                renderGrid();
                notify(zh ? "已填入提示词" : "Prompt inserted");
            });
            card.addEventListener("dblclick", () => openEditor(item.id));

            // 网格内拖拽重排
            card.addEventListener("dragstart", event => {
                if (event.target.closest("button, input")) { event.preventDefault(); return; }
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("application/x-mk-pl-item", item.id);
                card.classList.add("mk-pl-dragging");
            });
            card.addEventListener("dragend", () => { card.classList.remove("mk-pl-dragging"); clearMarker(grid); itemInsert = null; });
            card.addEventListener("dragover", event => {
                if (!event.dataTransfer || !Array.from(event.dataTransfer.types).includes("application/x-mk-pl-item")) return;
                event.preventDefault();
                const rect = card.getBoundingClientRect();
                const cards = [...grid.querySelectorAll("[data-item-card]")];
                const idx = cards.indexOf(card);
                const insertIndex = event.clientX - rect.left < rect.width / 2 ? idx : idx + 1;
                itemInsert = { list: catNode.items, index: insertIndex, sorted: items };
                clearMarker(grid);
                const marker = document.createElement("div");
                marker.className = "mk-pl-insert-marker";
                marker.style.cssText = "width:3px;align-self:stretch";
                const ref = cards[insertIndex] || null;
                if (ref) grid.insertBefore(marker, ref); else grid.appendChild(marker);
            });
            card.addEventListener("drop", async event => {
                const dragId = event.dataTransfer?.getData("application/x-mk-pl-item");
                if (!dragId || !itemInsert) return;
                event.preventDefault(); event.stopPropagation();
                const ordered = _libSortItems(catNode.items);
                const from = ordered.findIndex(i => i.id === dragId);
                const { index } = itemInsert; itemInsert = null; clearMarker(grid);
                if (from < 0) return;
                const [moved] = ordered.splice(from, 1);
                const to = from < index ? index - 1 : index;
                ordered.splice(Math.max(0, Math.min(ordered.length, to)), 0, moved);
                ordered.forEach((it, i) => { it.order = (i + 1) * 1000; });
                await persist(); renderGrid();
            });

            card.append(thumb, nameEl, actions);
            grid.appendChild(card);
        }
    };

    // 网格拖放上传（拖文件进网格）
    grid.addEventListener("dragover", event => {
        if (!event.dataTransfer || !Array.from(event.dataTransfer.types).includes("Files")) return;
        event.preventDefault();
        grid.classList.add("mk-pl-grid-drop");
    });
    grid.addEventListener("dragleave", () => grid.classList.remove("mk-pl-grid-drop"));
    grid.addEventListener("drop", async event => {
        const files = event.dataTransfer?.files ? [...event.dataTransfer.files] : [];
        if (!files.length) return;
        event.preventDefault();
        grid.classList.remove("mk-pl-grid-drop");
        await importImageFiles(files);
    });

    const renderAll = () => { renderTree(); renderGrid(); };

    // ── 分类操作 ──
    const createCategory = async parentNode => {
        const name = await askText(parentNode
            ? (zh ? `在“${parentNode.name}”下新建子分类` : `New subcategory in “${parentNode.name}”`)
            : (zh ? "新建顶级分类" : "New top-level category"));
        if (!name) return;
        const list = parentNode ? parentNode.children : lib.tree;
        if (list.some(n => n.name === name)) { notify(zh ? "同级下分类名已存在。" : "A sibling category already has this name."); return; }
        const nextOrder = list.reduce((m, n) => Math.max(m, n.order ?? 0), 0) + 1000;
        const nodeNew = { id: _libNewId("c"), name, order: nextOrder, children: [], items: [] };
        list.push(nodeNew);
        if (parentNode) expanded.add(parentNode.id);
        selectedId = nodeNew.id;
        await persist(); renderAll();
    };

    const renameCategory = async nodeRef => {
        if (nodeRef.id === _FAV_ID) return;
        const next = await askText(zh ? `重命名分类“${nodeRef.name}”` : `Rename “${nodeRef.name}”`, nodeRef.name);
        if (!next || next === nodeRef.name) return;
        const list = _libSiblingsOf(lib, nodeRef.id) || [];
        if (list.some(n => n !== nodeRef && n.name === next)) { notify(zh ? "同级下分类名已存在。" : "A sibling category already has this name."); return; }
        nodeRef.name = next;
        await persist(); renderAll();
    };

    const removeCategory = async nodeRef => {
        if (nodeRef.id === _FAV_ID) return;
        if (!await askConfirm(zh ? `删除分类“${nodeRef.name}”及其全部子分类与条目？` : `Delete “${nodeRef.name}” and all its subcategories/items?`, zh ? "删除" : "Delete")) return;
        const thumbs = [];
        _libWalk([nodeRef], n => { for (const it of n.items) if (it.thumb) thumbs.push(it.thumb); });
        const list = _libSiblingsOf(lib, nodeRef.id);
        if (list) {
            const idx = list.indexOf(nodeRef);
            if (idx >= 0) list.splice(idx, 1);
        }
        thumbs.forEach(_mkDeleteAsset);
        if (selectedId === nodeRef.id || !_libFindNode(lib, selectedId)) {
            selectedId = lib.tree.find(n => n.id !== _FAV_ID)?.id || _FAV_ID;
        }
        await persist(); renderAll();
    };

    // ── 条目操作 ──
    const moveItemsToNode = async (items, targetId) => {
        const toNode = _libFindNode(lib, targetId);
        if (!toNode) return;
        let moved = 0;
        for (const item of items) {
            let holder = null;
            _libWalk(lib.tree, n => { if (n.items.includes(item)) holder = n; });
            if (!holder || holder === toNode) continue;
            holder.items.splice(holder.items.indexOf(item), 1);
            item.order = toNode.items.reduce((m, it) => Math.max(m, it.order ?? 0), 0) + 1000;
            toNode.items.push(item);
            moved++;
        }
        selectedId = targetId;
        selectedKeys.clear();
        await persist(); renderAll();
        if (moved) notify(zh ? `已移动 ${moved} 条` : `Moved ${moved} item(s)`);
    };

    const importImageFiles = async (files, targetNode = null) => {
        const nodeTarget = targetNode || _libFindNode(lib, selectedId);
        if (!nodeTarget) return;
        const images = files.filter(f => f && (f.type || "").startsWith("image/"));
        if (!images.length) { notify(zh ? "请选择图片文件。" : "Please choose image files."); return; }
        let done = 0;
        for (const file of images) {
            try {
                notify(zh ? `正在处理 ${done + 1}/${images.length}…` : `Processing ${done + 1}/${images.length}…`);
                const dataUrl = await _mkMakeThumbDataUrl(file);
                const name = await _mkUploadAsset(dataUrl);
                const itemName = file.name.replace(/\.[^.]+$/, "").slice(0, 40) || (zh ? "提示词" : "Prompt");
                const order = nodeTarget.items.reduce((m, it) => Math.max(m, it.order ?? 0), 0) + 1000;
                nodeTarget.items.push({ id: _libNewId("p"), name: itemName, prompt: "", thumb: name, order });
                done++;
            } catch (err) {
                console.error("[MK-提示词大全] 处理图片失败:", err);
            }
        }
        await persist(); renderGrid();
        notify(done ? (zh ? `已添加 ${done} 条，点「编辑」填写提示词。` : `Added ${done} item(s). Click “Edit” to write prompts.`)
                   : (zh ? "上传失败。" : "Upload failed."));
    };

    const replaceItemImage = item => {
        replaceInput._target = item;
        replaceInput.value = "";
        replaceInput.click();
    };
    replaceInput.addEventListener("change", async () => {
        const file = replaceInput.files?.[0];
        const item = replaceInput._target;
        replaceInput.value = "";
        if (!file || !item) return;
        try {
            notify(zh ? "正在处理图片…" : "Processing image…");
            const dataUrl = await _mkMakeThumbDataUrl(file);
            const name = await _mkUploadAsset(dataUrl);
            const old = item.thumb;
            item.thumb = name;
            if (old) _mkDeleteAsset(old);
            await persist();
            if (editingItemId === item.id) refreshEditorThumb(item);
            renderGrid();
            notify(zh ? "配图已更新" : "Image updated");
        } catch (err) {
            console.error("[MK-提示词大全] 更换图片失败:", err);
            notify(zh ? "更换图片失败。" : "Failed to change image.");
        }
    });

    uploadInput.addEventListener("change", async () => {
        const files = uploadInput.files ? [...uploadInput.files] : [];
        uploadInput.value = "";
        if (files.length) await importImageFiles(files);
    });

    // ── 编辑器 ──
    const refreshEditorThumb = item => {
        if (item.thumb) {
            editorThumb.style.backgroundImage = `url("${_mkAssetUrl(item.thumb)}")`;
            editorThumb.textContent = "";
        } else {
            editorThumb.style.backgroundImage = "";
            editorThumb.textContent = zh ? "无图" : "No image";
        }
    };

    const openEditor = itemId => {
        const holder = (() => { let h = null; _libWalk(lib.tree, n => { if (n.items.some(it => it.id === itemId)) h = n; }); return h; })();
        if (!holder) return;
        const item = holder.items.find(it => it.id === itemId);
        editingItemId = itemId;
        title.textContent = zh ? "编辑条目" : "Edit item";
        closeButton.disabled = true; closeButton.style.opacity = "0.45"; closeButton.style.cursor = "not-allowed";
        editorCat.innerHTML = _libCollectNodes(lib).map(({ node: n, depth }) => {
            const label = ("　".repeat(depth)) + (n.id === _FAV_ID ? "★ " + (zh ? "收藏" : "Favorites") : (n.name || "未命名"));
            return `<option value="${n.id}"${n.id === holder.id ? " selected" : ""}>${label.replace(/</g, "&lt;")}</option>`;
        }).join("");
        editorName.value = item.name || "";
        editorText.value = item.prompt || "";
        refreshEditorThumb(item);
        home.style.display = "none";
        editorView.style.display = "flex";
        setTimeout(() => editorText.focus(), 0);
    };

    const closeEditor = () => {
        editingItemId = null;
        editorView.style.display = "none";
        home.style.display = "flex";
        closeButton.disabled = false; closeButton.style.opacity = "1"; closeButton.style.cursor = "pointer";
        title.textContent = zh ? "提示词大全" : "Prompt Library";
        renderAll();
    };

    dialog.querySelector("[data-save]").addEventListener("click", async () => {
        if (!editingItemId) return;
        const holder = (() => { let h = null; _libWalk(lib.tree, n => { if (n.items.some(it => it.id === editingItemId)) h = n; }); return h; })();
        if (!holder) { closeEditor(); return; }
        const item = holder.items.find(it => it.id === editingItemId);
        const targetId = editorCat.value;
        const newName = editorName.value.trim();
        item.prompt = editorText.value;
        if (newName) item.name = newName;
        const targetNode = _libFindNode(lib, targetId);
        if (targetNode && targetNode !== holder) {
            holder.items.splice(holder.items.indexOf(item), 1);
            item.order = targetNode.items.reduce((m, it) => Math.max(m, it.order ?? 0), 0) + 1000;
            targetNode.items.push(item);
            selectedId = targetId;
        }
        await persist();
        closeEditor();
    });
    dialog.querySelector("[data-back]").addEventListener("click", closeEditor);

    const importTextInput = document.createElement("input");
    importTextInput.type = "file"; importTextInput.accept = ".txt,.md,text/plain,text/markdown"; importTextInput.style.display = "none";
    overlay.appendChild(importTextInput);
    dialog.querySelector("[data-import]").addEventListener("click", () => { importTextInput.value = ""; importTextInput.click(); });
    importTextInput.addEventListener("change", async () => {
        const file = importTextInput.files?.[0];
        importTextInput.value = "";
        if (!file) return;
        if (!/\.(txt|md)$/i.test(file.name)) { notify(zh ? "只支持 .txt 和 .md。" : "Only .txt and .md are supported."); return; }
        try { editorText.value = await file.text(); setTimeout(() => editorText.focus(), 0); }
        catch (err) { notify(String(err?.message || err)); }
    });
    editorText.addEventListener("dragover", event => { event.preventDefault(); editorText.style.borderColor = "#68b38a"; });
    editorText.addEventListener("dragleave", () => { editorText.style.borderColor = "#151617"; });
    editorText.addEventListener("drop", async event => {
        const file = event.dataTransfer?.files?.[0];
        if (!file) return;
        event.preventDefault(); editorText.style.borderColor = "#151617";
        if (!/\.(txt|md)$/i.test(file.name)) { notify(zh ? "只支持 .txt 和 .md。" : "Only .txt and .md are supported."); return; }
        try { editorText.value = await file.text(); } catch (err) { notify(String(err?.message || err)); }
    });

    dialog.querySelector("[data-editor-img]").addEventListener("click", () => {
        const holder = (() => { let h = null; _libWalk(lib.tree, n => { if (n.items.some(it => it.id === editingItemId)) h = n; }); return h; })();
        if (!holder) return;
        replaceItemImage(holder.items.find(it => it.id === editingItemId));
    });
    dialog.querySelector("[data-editor-rmimg]").addEventListener("click", async () => {
        const holder = (() => { let h = null; _libWalk(lib.tree, n => { if (n.items.some(it => it.id === editingItemId)) h = n; }); return h; })();
        if (!holder) return;
        const item = holder.items.find(it => it.id === editingItemId);
        if (!item.thumb) return;
        _mkDeleteAsset(item.thumb);
        item.thumb = "";
        await persist();
        refreshEditorThumb(item);
    });

    // ── 顶部按钮 ──
    home.querySelector("[data-add-category]").addEventListener("click", () => createCategory(null));
    home.querySelector("[data-upload]").addEventListener("click", () => { uploadInput.value = ""; uploadInput.click(); });

    // ── 批量多选栏 ──
    batchAll.addEventListener("click", () => {
        const catNode = _libFindNode(lib, selectedId);
        if (!catNode) return;
        const all = catNode.items;
        if (all.length && all.every(it => selectedKeys.has(it.id))) selectedKeys.clear();
        else all.forEach(it => selectedKeys.add(it.id));
        renderGrid();
    });
    batchMoveBtn.addEventListener("click", e => {
        const catNode = _libFindNode(lib, selectedId);
        if (!catNode) return;
        const keys = catNode.items.filter(it => selectedKeys.has(it.id));
        if (keys.length) showMoveMenu(keys, e.clientX, e.clientY);
    });
    batchClear.addEventListener("click", () => { selectedKeys.clear(); renderGrid(); });
    home.querySelector("[data-add-item]").addEventListener("click", async () => {
        const nodeTarget = _libFindNode(lib, selectedId);
        if (!nodeTarget) return;
        const name = await askText(zh ? "新建条目名称" : "New item name");
        if (!name) return;
        const order = nodeTarget.items.reduce((m, it) => Math.max(m, it.order ?? 0), 0) + 1000;
        const item = { id: _libNewId("p"), name, prompt: "", thumb: "", order };
        nodeTarget.items.push(item);
        await persist(); renderGrid();
        openEditor(item.id);
    });

    // ── 关闭 ──
    const onKey = event => { if (event.key === "Escape" && !document.querySelector("[data-modal]")) close(); };
    const onExternal = event => {
        const next = event.detail;
        if (!next || typeof next !== "object") return;
        lib = _libEnsureDefaultCategory(_libEnsureFavorites(_libNormalize(next)));
        expanded.clear();
        _libWalk(lib.tree, n => { if (n.children.length) expanded.add(n.id); });
        if (!_libFindNode(lib, selectedId)) selectedId = lib.tree[0]?.id || _FAV_ID;
        closeEditor();
    };
    const close = () => {
        document.removeEventListener("keydown", onKey, true);
        window.removeEventListener("mk:prompt-library-changed", onExternal);
        overlay.remove();
        node._mkLibraryDialogOpen = false;
    };
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("mk:prompt-library-changed", onExternal);
    dialog.querySelector("[data-close]").addEventListener("click", close);

    renderAll();
}

// ═══════════════════════════════════════════════
//  节点控件安装 / 同步
// ═══════════════════════════════════════════════
function _syncAllLibraryWidgets(lib = null) {
    if (!lib) return;
    for (const n of app.graph?._nodes || []) {
        if (n?.type === _NODE_TYPE || n?.comfyClass === _NODE_TYPE) {
            if (n._mkLibraryWidget) {
                n._mkLibraryWidget.name = mkLang() === "en" ? "Select Prompt" : "提示词预设选择";
                n._mkLibraryWidget.label = n._mkLibraryWidget.name;
            }
        }
    }
}

function _installLibraryControls(node) {
    if (node._mkLibraryReady) return;
    node._mkLibraryReady = true;
    node._mkLibraryWidget = node.addWidget("button", mkLang() === "en" ? "Select Prompt" : "提示词预设选择", null, () => {
        if (!node._mkLibraryDialogOpen) {
            node._mkLibraryDialogOpen = true;
            _openLibraryPicker(node).catch(error => {
                console.error("[MK-提示词大全] 打开提示词库失败:", error);
                node._mkLibraryDialogOpen = false;
            });
        }
    });
    _loadLibrary().then(lib => _syncAllLibraryWidgets(lib)).catch(() => {});
}

// ═══════════════════════════════════════════════
//  双语补丁
// ═══════════════════════════════════════════════
function applyBilingual(node) {
    const isEn = mkLang() === "en";
    if (node._mkOrigTitle == null) node._mkOrigTitle = node.title || _NODE_NAME_ZH;
    node.title = isEn ? _NODE_NAME_EN : (node.title && node.title !== _NODE_NAME_EN ? node.title : _NODE_NAME_ZH);

    const outMap = isEn ? { text: "Prompt" } : { text: "提示词" };
    for (const output of node.outputs || []) {
        if (output._mkOrigName == null) output._mkOrigName = output.name;
        output.name = outMap[output._mkOrigName] ?? output._mkOrigName;
    }

    const txt = node.widgets?.find(w => w && w.name === "text");
    if (txt) {
        txt.label = isEn ? "Text" : "文本";
        const want = "";
        if (txt.element && typeof txt.element.setAttribute === "function" && txt.element.getAttribute("placeholder") !== want) {
            txt.element.setAttribute("placeholder", want);
        }
        if (txt.options && txt.options.placeholder !== want) txt.options.placeholder = want;
    }

    if (node._mkLibraryWidget) {
        node._mkLibraryWidget.name = isEn ? "Select Prompt" : "提示词预设选择";
        node._mkLibraryWidget.label = node._mkLibraryWidget.name;
    }
    node.setDirtyCanvas?.(true, true);
}

// ═══════════════════════════════════════════════
//  textarea（class + 右键收藏）
// ═══════════════════════════════════════════════
function ensureTextarea(node) {
    const tag = ta => {
        if (!ta) return;
        if (!ta._mkPlTagged) {
            ta._mkPlTagged = true;
            ta.classList.add("mk-pl-textbox");
        }
        if (ta.getAttribute("placeholder") !== "") ta.setAttribute("placeholder", "");
        if (!ta._mkPlFavReady) {
            ta._mkPlFavReady = true;
            ta.addEventListener("contextmenu", event => {
                event.preventDefault(); event.stopPropagation();
                document.querySelector(".mk-pl-fav-context")?.remove();
                const ctx = document.createElement("div");
                ctx.className = "mk-pl-fav-context";
                ctx.style.cssText = `position:fixed;z-index:100002;left:${Math.max(4, Math.min(innerWidth - 160, event.clientX))}px;top:${Math.max(4, Math.min(innerHeight - 44, event.clientY))}px;padding:4px;background:#202124;border:1px solid #666;border-radius:5px;box-shadow:0 5px 18px #0009`;
                const fav = document.createElement("button");
                fav.type = "button";
                fav.textContent = mkLang() === "en" ? "Add to Library" : "收藏到提示词库";
                fav.style.cssText = "padding:6px 12px;border:0;border-radius:3px;background:transparent;color:#eee;cursor:pointer;white-space:nowrap;font-size:14px";
                fav.addEventListener("mouseenter", () => { fav.style.color = "#e7b94f"; fav.style.fontWeight = "bold"; });
                fav.addEventListener("mouseleave", () => { fav.style.color = "#eee"; fav.style.fontWeight = ""; });
                fav.addEventListener("click", async clickEvent => {
                    clickEvent.preventDefault(); clickEvent.stopPropagation();
                    fav.disabled = true;
                    const value = ta.value || node.widgets?.find(w => w?.name === "text")?.value;
                    try { await _libAddFavorite(value); }
                    catch (err) { console.error("[MK-提示词大全] 收藏失败:", err); }
                    ctx.remove();
                });
                ctx.appendChild(fav);
                document.body.appendChild(ctx);
                const dismiss = de => { if (!ctx.contains(de.target)) { ctx.remove(); document.removeEventListener("pointerdown", dismiss, true); } };
                setTimeout(() => document.addEventListener("pointerdown", dismiss, true), 0);
            });
        }
    };
    const tryAttach = () => {
        const wid = node.id;
        for (const sel of [`textarea[data-node-id="${wid}"]`, `textarea[node-id="${wid}"]`, `[data-node-id="${wid}"] textarea`]) {
            const ta = document.querySelector(sel);
            if (ta) { tag(ta); return true; }
        }
        const txtWidget = node.widgets?.find(w => w?.name === "text");
        if (txtWidget?.element) { tag(txtWidget.element); return true; }
        return false;
    };
    if (!tryAttach()) {
        const obs = new MutationObserver(() => { if (tryAttach()) obs.disconnect(); });
        obs.observe(document.body, { childList: true, subtree: true });
        setTimeout(() => obs.disconnect(), 30000);
    }
    setTimeout(tryAttach, 0);
    setTimeout(tryAttach, 50);
}

// ── CSS ──
(function () {
    const cssId = "mk-prompt-library-css";
    if (document.getElementById(cssId)) return;
    const s = document.createElement("style");
    s.id = cssId;
    s.textContent = `
textarea.mk-pl-textbox {
    box-sizing: border-box !important;
    border: 1px solid transparent !important;
}
textarea.mk-pl-textbox:focus,
textarea.mk-pl-textbox:focus-visible,
textarea.mk-pl-textbox:active {
    outline: none !important;
    box-shadow: none !important;
    border-color: #666 !important;
}`;
    document.head.appendChild(s);
})();

// ═══════════════════════════════════════════════
//  注册扩展
// ═══════════════════════════════════════════════
app.registerExtension({
    name: "Comfyui_MKnode.PromptLibrary",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== _NODE_TYPE) return;

        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            applyBilingual(this);
            ensureTextarea(this);
            _installLibraryControls(this);
            return r;
        };

        const origConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = origConfigure?.apply(this, arguments);
            applyBilingual(this);
            ensureTextarea(this);
            _installLibraryControls(this);
            return r;
        };
    },
});

// 热修复入口 / 对外接口
if (typeof window !== "undefined") {
    window.MK_PromptLibrary_applyBilingualAll = function () {
        const graph = app.graph || window.graph;
        let n = 0;
        for (const nd of graph?._nodes || []) {
            if (nd.type === _NODE_TYPE) { applyBilingual(nd); ensureTextarea(nd); n++; }
        }
        return { patched: n, lang: mkLang() };
    };
    window._mkAddPromptLibraryFavorite = async prompt => _libAddFavorite(prompt);
}
