// Comfyui_MKnode —— MK-提示词预设图库 前端
//
// 点「预设图库」弹出悬浮面板：
//   左侧：全部图片 / 「写真图片」内置分组（10 个子分类，只读）/ 自建分类（可嵌套，右键加子分类）
//   右侧：缩略图网格 = 预览图 + 下方提示词，点一张把提示词填入节点文本框
//
// 内置素材来自 web/ppg_data/（由 tools/build_ppg_templates.py 生成），只读、不参与工作流保存。
// 自建分类与其中的素材存后端文件（mk_ppg_store.py），落在
// <ComfyUI>/user/default/MKnode/Prompt Preset/，更新插件不丢。
//
// 命名隔离：节点 id MK_PromptPresetGallery、扩展名 Comfyui_MKnode.PromptPresetGallery、
// 样式 id mk-ppg-style。

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "MK_PromptPresetGallery";
const BUTTON_LABEL = "预设图库";
const SAVE_LABEL = "当前提示词存为预设";
const DEFAULT_WIDTH = 320;

const STYLE_ID = "mk-ppg-style";
const DATA_BASE = new URL("./ppg_data/", import.meta.url);
const BATCH = 90;                        // 网格每次渲染多少张，滚到底再追加

const FIXED_ITEMS = [
    { kind: "all", label: "全部图片" },
];

const ICON = {
    grid: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><rect x="3.2" y="3.2" width="7" height="7" rx="1.6"/><rect x="13.8" y="3.2" width="7" height="7" rx="1.6"/><rect x="3.2" y="13.8" width="7" height="7" rx="1.6"/><rect x="13.8" y="13.8" width="7" height="7" rx="1.6"/></svg>',
    folder: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M3.2 7.6A2.4 2.4 0 0 1 5.6 5.2h3.6l2 2h6.8a2.4 2.4 0 0 1 2.4 2.4v7A2.4 2.4 0 0 1 18 19H5.6a2.4 2.4 0 0 1-2.4-2.4z"/></svg>',
    tray: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M3.5 13.5l2.2-8A2 2 0 0 1 7.6 4h8.8a2 2 0 0 1 1.9 1.5l2.2 8"/><path d="M3.5 13.5h5l1 2.5h5l1-2.5h5v4A2.5 2.5 0 0 1 17.5 20h-11A2.5 2.5 0 0 1 4 17.5z"/></svg>',
    chev: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg>',
    image: '<svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><rect x="3" y="4.5" width="18" height="15" rx="2.2"/><circle cx="8.6" cy="9.8" r="1.5"/><path d="M20.2 16.4l-4.6-4.6-5.4 5.4-2.6-2.6-4 4"/></svg>',
};

const CSS = `
.mk-ppg-overlay{position:fixed;inset:0;z-index:99990;background:rgba(0,0,0,.38);animation:mk-ppg-fade .12s ease-out;}
.mk-ppg-panel{
  position:fixed;inset:0;margin:auto;z-index:99991;display:flex;flex-direction:column;
  width:min(1200px,calc(100vw - 48px));height:min(800px,calc(100vh - 48px));
  background:var(--comfy-menu-bg,#1f1f22);color:var(--fg-color,#e7e7e7);
  border:1px solid var(--border-color,#3c3c3c);border-radius:14px;overflow:hidden;
  box-shadow:0 24px 72px rgba(0,0,0,.55);font-size:13px;line-height:1.5;
  font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
}
.mk-ppg-head{flex:0 0 46px;display:flex;align-items:center;gap:9px;padding:0 10px 0 16px;
  border-bottom:1px solid var(--border-color,#3c3c3c);
  background:color-mix(in srgb,var(--fg-color,#fff) 4%,var(--comfy-menu-bg,#1f1f22));}
.mk-ppg-head .mk-ppg-title{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:500;}
.mk-ppg-head .mk-ppg-title svg{opacity:.75}
.mk-ppg-close{margin-left:auto;width:28px;height:28px;display:flex;align-items:center;justify-content:center;
  border:none;border-radius:8px;background:transparent;color:inherit;cursor:pointer;font-size:15px;opacity:.62;}
.mk-ppg-close:hover{background:color-mix(in srgb,var(--fg-color,#fff) 10%,transparent);opacity:1}
.mk-ppg-body{flex:1;display:flex;min-height:0}
.mk-ppg-rail{flex:0 0 248px;width:248px;display:flex;flex-direction:column;min-height:0;
  border-right:1px solid var(--border-color,#3c3c3c);
  background:color-mix(in srgb,var(--fg-color,#fff) 2%,var(--comfy-menu-bg,#1f1f22));}
.mk-ppg-scroll{flex:1;min-height:0;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:2px;}
.mk-ppg-scroll::-webkit-scrollbar,.mk-ppg-grid::-webkit-scrollbar{width:9px}
.mk-ppg-scroll::-webkit-scrollbar-thumb,.mk-ppg-grid::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--fg-color,#fff) 16%,transparent);border-radius:8px}
.mk-ppg-scroll::-webkit-scrollbar-track,.mk-ppg-grid::-webkit-scrollbar-track{background:transparent}
.mk-ppg-item{display:flex;align-items:center;gap:9px;width:100%;padding:7px 9px;border:none;border-radius:8px;
  background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;}
.mk-ppg-item>svg{flex:0 0 16px;opacity:.7}
.mk-ppg-item .mk-ppg-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mk-ppg-item .mk-ppg-num{font-size:11.5px;color:var(--muted-foreground,#9b9b9b);font-variant-numeric:tabular-nums}
.mk-ppg-item:hover{background:color-mix(in srgb,var(--fg-color,#fff) 7%,transparent)}
.mk-ppg-item.is-active{background:color-mix(in srgb,var(--primary,#4f7cff) 17%,transparent);color:var(--primary,#4f7cff);font-weight:500}
.mk-ppg-item.is-active>svg{opacity:1}
.mk-ppg-item.is-active .mk-ppg-num{color:inherit;opacity:.75}
.mk-ppg-group{display:flex;align-items:center;gap:8px;width:100%;padding:7px 9px;border:none;border-radius:8px;
  background:transparent;color:inherit;font:inherit;font-size:13px;text-align:left;cursor:pointer;font-weight:500}
.mk-ppg-group:hover{background:color-mix(in srgb,var(--fg-color,#fff) 7%,transparent)}
.mk-ppg-group>.mk-ppg-chev{flex:0 0 14px;display:flex;opacity:.55;transition:transform .12s}
.mk-ppg-group.is-open>.mk-ppg-chev{transform:rotate(90deg)}
.mk-ppg-badge{margin-left:auto;font-size:10px;line-height:1.6;padding:0 5px;border-radius:5px;
  background:color-mix(in srgb,var(--fg-color,#fff) 10%,transparent);color:var(--muted-foreground,#9b9b9b);font-weight:400}
.mk-ppg-kids{margin:2px 0 2px 16px;padding-left:8px;display:flex;flex-direction:column;gap:2px;
  border-left:1px solid var(--border-color,#3c3c3c)}
.mk-ppg-kids .mk-ppg-item{padding:6px 8px;font-size:12.5px}
.mk-ppg-sec{display:flex;align-items:center;gap:6px;margin:14px 4px 4px;font-size:11.5px;
  color:var(--muted-foreground,#9b9b9b);letter-spacing:.02em}
.mk-ppg-sec .mk-ppg-add{margin-left:auto;width:22px;height:22px;display:flex;align-items:center;justify-content:center;
  border:none;border-radius:6px;background:transparent;color:inherit;cursor:pointer;font-size:14px;line-height:1}
.mk-ppg-sec .mk-ppg-add:hover{background:color-mix(in srgb,var(--fg-color,#fff) 10%,transparent);color:var(--fg-color,#fff)}
.mk-ppg-cat{position:relative}
.mk-ppg-cat .mk-ppg-del{position:absolute;right:5px;top:50%;transform:translateY(-50%);
  width:20px;height:20px;display:flex;align-items:center;justify-content:center;border:none;border-radius:6px;
  background:transparent;color:var(--muted-foreground,#9b9b9b);cursor:pointer;font-size:12px;opacity:0;transition:opacity .12s}
.mk-ppg-cat:hover .mk-ppg-del{opacity:.85}
.mk-ppg-cat .mk-ppg-del:hover{background:color-mix(in srgb,var(--destructive,#e24b4a) 20%,transparent);color:var(--destructive,#e24b4a);opacity:1}
.mk-ppg-cat:hover .mk-ppg-num{opacity:0}
.mk-ppg-hint{margin:6px 10px 10px;font-size:12px;color:var(--muted-foreground,#9b9b9b)}
.mk-ppg-input{width:100%;box-sizing:border-box;padding:6px 8px;border-radius:7px;
  border:1px solid var(--primary,#4f7cff);background:var(--comfy-input-bg,#2a2a2a);color:inherit;
  font:inherit;font-size:13px;outline:none}
.mk-ppg-rail-foot:empty{display:none}
.mk-ppg-rail-foot{display:flex;align-items:center;gap:8px;padding:10px;font-size:12px;
  border-top:1px solid var(--border-color,#3c3c3c);background:color-mix(in srgb,var(--destructive,#e24b4a) 6%,transparent)}
.mk-ppg-rail-foot .mk-ppg-msg{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;opacity:.85}
.mk-ppg-btn{padding:4px 9px;border-radius:7px;border:1px solid var(--border-color,#3c3c3c);
  background:color-mix(in srgb,var(--fg-color,#fff) 7%,transparent);color:inherit;font:inherit;font-size:12px;cursor:pointer}
.mk-ppg-btn:hover{background:color-mix(in srgb,var(--fg-color,#fff) 13%,transparent)}
.mk-ppg-btn.is-danger{border-color:color-mix(in srgb,var(--destructive,#e24b4a) 45%,transparent);
  background:color-mix(in srgb,var(--destructive,#e24b4a) 18%,transparent);color:var(--destructive,#e24b4a)}
.mk-ppg-btn.is-danger:hover{background:color-mix(in srgb,var(--destructive,#e24b4a) 28%,transparent)}
.mk-ppg-btn.is-primary{padding:6px 16px;font-size:12.5px;color:#fff;
  border-color:color-mix(in srgb,var(--primary,#4f7cff) 55%,transparent);
  background:color-mix(in srgb,var(--primary,#4f7cff) 30%,transparent)}
.mk-ppg-btn.is-primary:hover{background:color-mix(in srgb,var(--primary,#4f7cff) 42%,transparent)}
.mk-ppg-main{flex:1;min-width:0;display:flex;flex-direction:column;padding:14px;min-height:0}
.mk-ppg-grid{flex:1;min-height:0;overflow-y:auto;display:grid;align-content:start;
  grid-template-columns:repeat(auto-fill,minmax(152px,1fr));gap:12px;padding-right:2px}
.mk-ppg-card{display:flex;flex-direction:column;gap:6px;padding:6px;border-radius:10px;cursor:pointer;
  border:1px solid transparent;background:color-mix(in srgb,var(--fg-color,#fff) 3%,transparent);
  transition:border-color .12s,background .12s}
.mk-ppg-card:hover{border-color:color-mix(in srgb,var(--primary,#4f7cff) 55%,transparent);
  background:color-mix(in srgb,var(--primary,#4f7cff) 9%,transparent)}
.mk-ppg-card.is-picked{border-color:var(--primary,#4f7cff)}
.mk-ppg-card img{width:100%;aspect-ratio:2/3;object-fit:contain;border-radius:7px;display:block;
  background:color-mix(in srgb,var(--fg-color,#fff) 6%,transparent)}
.mk-ppg-card .mk-ppg-p{font-size:11px;line-height:1.45;color:var(--muted-foreground,#8f8f8f);
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}
.mk-ppg-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;
  border:1.5px dashed color-mix(in srgb,var(--fg-color,#fff) 15%,transparent);border-radius:12px;
  color:var(--muted-foreground,#9b9b9b);text-align:center;padding:20px}
.mk-ppg-empty svg{opacity:.4}
.mk-ppg-empty .mk-ppg-empty-t{font-size:13px;color:color-mix(in srgb,var(--fg-color,#fff) 68%,transparent)}
.mk-ppg-empty .mk-ppg-empty-s{font-size:12px;opacity:.8;line-height:1.6}
.mk-ppg-foot{flex:0 0 30px;display:flex;align-items:center;gap:12px;padding:0 14px;font-size:11.5px;
  color:var(--muted-foreground,#9b9b9b);border-top:1px solid var(--border-color,#3c3c3c);
  background:color-mix(in srgb,var(--fg-color,#fff) 2%,var(--comfy-menu-bg,#1f1f22))}
.mk-ppg-foot .mk-ppg-sp{flex:1}
.mk-ppg-toast{position:absolute;right:18px;bottom:44px;padding:7px 13px;border-radius:8px;font-size:12px;
  background:color-mix(in srgb,var(--primary,#4f7cff) 22%,var(--comfy-menu-bg,#1f1f22));
  border:1px solid color-mix(in srgb,var(--primary,#4f7cff) 45%,transparent);
  color:var(--fg-color,#fff);opacity:0;transform:translateY(6px);transition:opacity .15s,transform .15s;pointer-events:none}
.mk-ppg-toast.is-on{opacity:1;transform:translateY(0)}
.mk-ppg-chev{flex:0 0 14px;display:flex;align-items:center;opacity:.55;transition:transform .12s}
.mk-ppg-chev.is-open{transform:rotate(90deg)}
.mk-ppg-chev.is-empty{opacity:0}
.mk-ppg-menu{position:fixed;z-index:100001;min-width:152px;padding:6px;border-radius:10px;
  background:var(--comfy-menu-bg,#1f1f22);border:1px solid var(--border-color,#3c3c3c);
  box-shadow:0 12px 32px rgba(0,0,0,.45);display:flex;flex-direction:column;gap:2px}
.mk-ppg-menu button{display:block;width:100%;text-align:left;padding:6px 10px;border:none;border-radius:7px;
  background:transparent;color:inherit;font:inherit;font-size:12.5px;cursor:pointer}
.mk-ppg-menu button:hover{background:color-mix(in srgb,var(--fg-color,#fff) 9%,transparent)}
.mk-ppg-menu button.is-danger{color:var(--destructive,#e24b4a)}
.mk-ppg-menu button.is-danger:hover{background:color-mix(in srgb,var(--destructive,#e24b4a) 18%,transparent)}
.mk-ppg-menu-scroll{max-height:320px;overflow-y:auto}
.mk-ppg-item.is-drop{background:color-mix(in srgb,var(--primary,#4f7cff) 24%,transparent);
  box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--primary,#4f7cff) 70%,transparent)}
.mk-ppg-card.is-dragging{opacity:.45}
.mk-ppg-tag{align-self:flex-start;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:10px;line-height:1.6;padding:0 5px;border-radius:4px;
  background:color-mix(in srgb,var(--fg-color,#fff) 9%,transparent);color:var(--muted-foreground,#9b9b9b)}
.mk-ppg-addcard{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;
  min-height:120px;border:1.5px dashed color-mix(in srgb,var(--fg-color,#fff) 18%,transparent);border-radius:10px;
  color:var(--muted-foreground,#9b9b9b);cursor:pointer;font-size:12px;background:transparent}
.mk-ppg-addcard:hover{border-color:color-mix(in srgb,var(--primary,#4f7cff) 55%,transparent);
  color:var(--primary,#4f7cff);background:color-mix(in srgb,var(--primary,#4f7cff) 7%,transparent)}
.mk-ppg-addcard span:first-child{font-size:20px;line-height:1}
.mk-ppg-noimg{width:100%;aspect-ratio:2/3;border-radius:7px;display:flex;align-items:center;justify-content:center;
  background:color-mix(in srgb,var(--fg-color,#fff) 6%,transparent);color:var(--muted-foreground,#8f8f8f);
  font-size:11px;text-align:center;padding:8px}
.mk-ppg-mask{position:absolute;inset:0;z-index:100002;background:rgba(0,0,0,.45);
  display:flex;align-items:center;justify-content:center}
.mk-ppg-dlg{width:min(460px,calc(100% - 40px));max-height:calc(100% - 40px);display:flex;flex-direction:column;
  gap:12px;padding:16px;border-radius:12px;background:var(--comfy-menu-bg,#1f1f22);
  border:1px solid var(--border-color,#3c3c3c);box-shadow:0 18px 50px rgba(0,0,0,.5)}
.mk-ppg-dlg .mk-ppg-dlg-t{font-size:14px;font-weight:500}
.mk-ppg-dlg .mk-ppg-drop{display:flex;align-items:center;justify-content:center;gap:10px;height:150px;
  border:1.5px dashed color-mix(in srgb,var(--fg-color,#fff) 18%,transparent);border-radius:10px;
  color:var(--muted-foreground,#9b9b9b);font-size:12px;cursor:pointer;overflow:hidden;position:relative}
.mk-ppg-dlg .mk-ppg-drop:hover{border-color:color-mix(in srgb,var(--primary,#4f7cff) 55%,transparent)}
.mk-ppg-dlg .mk-ppg-drop img{max-width:100%;max-height:100%;object-fit:contain}
.mk-ppg-dlg textarea{width:100%;box-sizing:border-box;min-height:120px;resize:vertical;padding:8px 10px;
  border-radius:8px;border:1px solid var(--border-color,#3c3c3c);background:var(--comfy-input-bg,#2a2a2a);
  color:inherit;font:inherit;font-size:12.5px;line-height:1.55;outline:none}
.mk-ppg-dlg textarea:focus{border-color:var(--primary,#4f7cff)}
.mk-ppg-dlg .mk-ppg-dlg-f{display:flex;justify-content:flex-end;gap:8px}
.mk-ppg-dlg .mk-ppg-dlg-f button{padding:6px 14px;border-radius:8px;border:1px solid var(--border-color,#3c3c3c);
  background:color-mix(in srgb,var(--fg-color,#fff) 7%,transparent);color:inherit;font:inherit;font-size:12.5px;cursor:pointer}
.mk-ppg-dlg .mk-ppg-dlg-f button:hover{background:color-mix(in srgb,var(--fg-color,#fff) 13%,transparent)}
.mk-ppg-dlg .mk-ppg-dlg-f button.is-primary{border-color:color-mix(in srgb,var(--primary,#4f7cff) 55%,transparent);
  background:color-mix(in srgb,var(--primary,#4f7cff) 22%,transparent);color:#fff}
@keyframes mk-ppg-fade{from{opacity:0}to{opacity:1}}
`;

// ───────────────────────────── 注册 ─────────────────────────────

app.registerExtension({
    name: "Comfyui_MKnode.PromptPresetGallery",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            addGalleryButton(this);
            return r;
        };
    },
});

function addGalleryButton(node) {
    if (node.widgets?.some((w) => w.name === BUTTON_LABEL)) return null;

    const btn = node.addWidget("button", BUTTON_LABEL, null, () => openPanel(node));
    if (!btn) return null;
    btn.serialize = false;

    // 第二个按钮：把当前提示词存成预设（点开选分类）
    let saveBtn = null;
    saveBtn = node.addWidget("button", SAVE_LABEL, null, () => openSaveMenu(node, saveBtn));
    if (saveBtn) saveBtn.serialize = false;

    const size = node.computeSize?.();
    if (size) {
        node.setSize([Math.max(node.size[0] || DEFAULT_WIDTH, DEFAULT_WIDTH), size[1]]);
    }
    return btn;
}

// ───────────────────── 当前提示词存为预设 ─────────────────────

const UNCAT_NAME = "未分类";

function readNodePrompt(node) {
    const ws = node.widgets || [];
    const w = ws.find((x) => x.name === "text") || ws.find((x) => typeof x.value === "string" && (x.inputEl || x.element));
    if (!w) return "";
    const el = w.inputEl || w.element?.querySelector?.("textarea");
    const value = el?.value ?? w.value;
    return String(value || "").trim();
}

// 按钮文字临时变成结果提示，过一会儿自己恢复
function flashButton(node, btn, label, ms = 1800) {
    if (!btn) return;
    btn.label = label;
    node.setDirtyCanvas?.(true, true);
    clearTimeout(btn._mkSaveTimer);
    btn._mkSaveTimer = setTimeout(() => {
        btn.label = SAVE_LABEL;
        node.setDirtyCanvas?.(true, true);
    }, ms);
}

// 「未分类」没有就建一个（顶层）
async function ensureUncategorizedCat() {
    const cats = await fetchTree();
    const hit = cats.find((c) => c.name === UNCAT_NAME);
    if (hit) return hit.id;
    const id = newCatId();
    const saved = await saveTreeApi(plainTree(cats).concat([{ id, name: UNCAT_NAME, children: [] }]));
    return (saved.find((c) => c.id === id) || { id }).id;
}

async function openSaveMenu(node, btn) {
    const text = readNodePrompt(node);
    if (!text) {
        flashButton(node, btn, "✗ 提示词是空的");
        return;
    }

    let cats = [];
    try {
        cats = await fetchTree();
    } catch (_) { /* 读不到分类就当没有，走未分类 */ }

    const uncat = cats.find((c) => c.name === UNCAT_NAME);
    const items = [{
        label: uncat ? UNCAT_NAME : UNCAT_NAME + "（新建）",
        depth: 0,
        onClick: () => savePreset(node, btn, uncat ? uncat.id : null, UNCAT_NAME, text),
    }];

    const walk = (list, depth) => (list || []).forEach((n) => {
        if (n.id !== uncat?.id) {
            items.push({ label: n.name, depth, onClick: () => savePreset(node, btn, n.id, n.name, text) });
        }
        walk(n.children, depth + 1);
    });
    walk(cats, 0);

    showMenuAboveNode(node, items);
}

async function savePreset(node, btn, catId, catName, text) {
    try {
        const target = catId || await ensureUncategorizedCat();
        await uploadItem(target, null, text);
        flashButton(node, btn, "✓ 已存到「" + catName + "」");
    } catch (err) {
        flashButton(node, btn, "✗ 保存失败，看控制台");
        console.error("[MK] 存为预设失败：", err);
    }
}

// 节点在屏幕上的位置（画布缩放/平移后也算得准）
function nodeScreenRect(node) {
    const canvasEl = app.canvas?.canvas;
    if (!canvasEl) return null;
    const box = canvasEl.getBoundingClientRect();
    const ds = app.canvas.ds;
    const scale = ds?.scale || 1;
    const p = ds?.convertOffsetToCanvas
        ? ds.convertOffsetToCanvas([node.pos[0], node.pos[1]])
        : [(node.pos[0] + (ds?.offset?.[0] || 0)) * scale, (node.pos[1] + (ds?.offset?.[1] || 0)) * scale];
    const size = node.size || [DEFAULT_WIDTH, 100];
    return { left: box.left + p[0], top: box.top + p[1], width: size[0] * scale, height: size[1] * scale };
}

// 在节点按钮上方弹出分类选择菜单
let _saveMenu = null;

function closeSaveMenu() {
    if (!_saveMenu) return;
    _saveMenu.remove();
    _saveMenu = null;
    document.removeEventListener("mousedown", onSaveMenuDown, true);
    document.removeEventListener("keydown", onSaveMenuKey, true);
}

function onSaveMenuDown(e) {
    if (_saveMenu && !_saveMenu.contains(e.target)) closeSaveMenu();
}

function onSaveMenuKey(e) {
    if (e.key === "Escape") { e.stopPropagation(); closeSaveMenu(); }
}

function showMenuAboveNode(node, items) {
    ensureStyle();
    closeSaveMenu();

    const menu = document.createElement("div");
    menu.className = "mk-ppg-menu mk-ppg-menu-scroll";
    items.forEach((it) => {
        const b = document.createElement("button");
        b.textContent = it.label;
        b.style.paddingLeft = (10 + (it.depth || 0) * 14) + "px";
        b.title = it.label;
        b.addEventListener("click", () => {
            closeSaveMenu();
            it.onClick();
        });
        menu.appendChild(b);
    });

    menu.style.visibility = "hidden";
    document.body.appendChild(menu);
    const w = menu.offsetWidth;
    const h = menu.offsetHeight;
    const rect = nodeScreenRect(node);
    if (rect) {
        // 贴在按钮上方：以节点左下角为基准往上让出两个按钮的高度
        const left = Math.min(Math.max(8, rect.left + 6), Math.max(8, innerWidth - w - 8));
        const top = Math.min(Math.max(8, rect.top + rect.height - 36 - h), Math.max(8, innerHeight - h - 8));
        menu.style.left = Math.round(left) + "px";
        menu.style.top = Math.round(top) + "px";
    } else {
        menu.style.left = "24px";
        menu.style.top = "24px";
    }
    menu.style.visibility = "visible";

    _saveMenu = menu;
    setTimeout(() => {
        document.addEventListener("mousedown", onSaveMenuDown, true);
        document.addEventListener("keydown", onSaveMenuKey, true);
    }, 0);
}

// ───────────────────────────── 数据 ─────────────────────────────

function newCatId() {
    return "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

let _manifest = null;
const _catCache = new Map();

function loadManifest() {
    if (_manifest) return Promise.resolve(_manifest);
    return fetch(new URL("manifest.json", DATA_BASE), { cache: "no-cache" })
        .then((r) => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then((m) => { _manifest = m; return m; });
}

function loadCat(file) {
    if (_catCache.has(file)) return _catCache.get(file);
    const p = fetch(new URL(file, DATA_BASE), { cache: "no-cache" })
        .then((r) => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then((list) => list.map((it) => ({ url: new URL(it.s, DATA_BASE).href, prompt: it.p })));
    _catCache.set(file, p);
    return p;
}

// 用户数据接口（后端 mk_ppg_store.py，落 user/default/MKnode/Prompt Preset/）
async function fetchTree() {
    const r = await api.fetchApi("/mk_ppg/tree", { cache: "no-cache" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.error || ("HTTP " + r.status));
    return d.cats || [];
}

async function saveTreeApi(nodes) {
    const r = await api.fetchApi("/mk_ppg/tree", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cats: nodes }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.error || ("HTTP " + r.status));
    return d.cats || [];
}

async function fetchItems(catId) {
    const r = await api.fetchApi("/mk_ppg/items?cat=" + encodeURIComponent(catId), { cache: "no-cache" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.error || ("HTTP " + r.status));
    return d.items || [];
}

async function saveItemsApi(catId, items) {
    const r = await api.fetchApi("/mk_ppg/items?cat=" + encodeURIComponent(catId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.error || ("HTTP " + r.status));
    return d.items || [];
}

async function uploadItem(catId, file, prompt) {
    const fd = new FormData();
    fd.append("prompt", prompt || "");
    if (file) fd.append("image", file, file.name || "image");
    const r = await api.fetchApi("/mk_ppg/upload?cat=" + encodeURIComponent(catId), { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.error || ("HTTP " + r.status));
    return d.item;
}

// 把某条素材换到另一个分类（图片文件后端一起搬）
async function moveItemApi(fromCat, toCat, index) {
    const r = await api.fetchApi("/mk_ppg/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from: fromCat, to: toCat, index }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.error || ("HTTP " + r.status));
    return d;
}

async function rmCatApi(catId) {
    const r = await api.fetchApi("/mk_ppg/rmcat?cat=" + encodeURIComponent(catId), { method: "POST" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.error || ("HTTP " + r.status));
}

function assetUrl(catId, fname) {
    return api.apiURL("/mk_ppg/asset?cat=" + encodeURIComponent(catId) + "&f=" + encodeURIComponent(fname));
}

// 分类树的小工具
function findNode(nodes, id) {
    for (const node of nodes) {
        if (node.id === id) return node;
        const hit = findNode(node.children || [], id);
        if (hit) return hit;
    }
    return null;
}

function removeNode(nodes, id) {
    const i = nodes.findIndex((n) => n.id === id);
    if (i >= 0) { nodes.splice(i, 1); return true; }
    return nodes.some((n) => removeNode(n.children || [], id));
}

function subtreeIds(node) {
    return [node.id].concat((node.children || []).reduce((acc, c) => acc.concat(subtreeIds(c)), []));
}

function plainTree(nodes) {
    return (nodes || []).map((n) => ({ id: n.id, name: n.name, children: plainTree(n.children) }));
}

// 把提示词写进节点的文本框
function fillPrompt(node, text) {
    const widgets = node.widgets || [];
    const w = widgets.find((x) => x.name === "text") || widgets.find((x) => x.type === "customtext") ||
        widgets.find((x) => typeof x.value === "string" && x.element);
    if (!w) return false;

    w.value = text;
    if (w.inputEl) {
        w.inputEl.value = text;
        w.inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (w.element) {
        const ta = w.element.querySelector?.("textarea");
        if (ta) {
            ta.value = text;
            ta.dispatchEvent(new Event("input", { bubbles: true }));
        }
    }
    node.onWidgetChanged?.(w.name, text, text, w);
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
    return true;
}

// 复制到剪贴板：优先 Clipboard API，非安全上下文（比如用局域网 IP 打开）退回到 execCommand
async function copyText(text) {
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (_) { /* 落到下面的兜底 */ }

    try {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        Object.assign(ta.style, { position: "fixed", top: "0", left: "-9999px", opacity: "0" });
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, text.length);
        const ok = document.execCommand("copy");
        ta.remove();
        return ok;
    } catch (_) {
        return false;
    }
}

// ───────────────────────────── 面板 ─────────────────────────────

let _panel = null;

function closePanel() {
    if (!_panel) return;
    const p = _panel;
    _panel = null;
    p.cleanup();
}

function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = CSS;
    document.head.appendChild(el);
}

function openPanel(node) {
    closePanel();
    ensureStyle();

    let tree = [];                        // 服务端分类树 [{id,name,children,count}]
    let openIds = new Set();              // 展开的节点 id
    let pendingAdd = null;                // { parentId: string|null } 正在新建的分类
    let pendingRename = null;             // { id } 正在重命名的分类
    let cancelAdd = null;
    let cancelRename = null;
    let activeItems = [];                 // 当前视图里的素材（扁平，仅用于计数）
    let itemsByCat = new Map();           // 当前视图按分类拆开的素材：catId -> [item]
    let ctxMenu = null;
    let active = { kind: "pending" };     // pending | all | builtin | ucat
    let groupOpen = true;                 // 「写真图片」是否展开
    let pickedCard = null;
    let gridState = null;                 // { items, shown, grid }
    let mainToken = 0;                    // 连续切换分类时，丢弃过期的渲染结果
    let toastTimer = 0;

    const overlay = document.createElement("div");
    overlay.className = "mk-ppg-overlay";

    const panel = document.createElement("div");
    panel.className = "mk-ppg-panel";
    panel.innerHTML =
        '<div class="mk-ppg-head">' +
            '<div class="mk-ppg-title">' + ICON.grid + '<span>提示词预设图库</span></div>' +
            '<button class="mk-ppg-close" title="关闭（Esc）">✕</button>' +
        '</div>' +
        '<div class="mk-ppg-body">' +
            '<aside class="mk-ppg-rail">' +
                '<div class="mk-ppg-scroll">' +
                    '<div class="mk-ppg-fixed"></div>' +
                    '<div class="mk-ppg-builtin"></div>' +
                    '<div class="mk-ppg-sec"><span>分类</span><button class="mk-ppg-add" title="新建分类">＋</button></div>' +
                    '<div class="mk-ppg-cats"></div>' +
                '</div>' +
                '<div class="mk-ppg-rail-foot"></div>' +
            '</aside>' +
            '<main class="mk-ppg-main"></main>' +
        '</div>' +
        '<div class="mk-ppg-foot"><span class="mk-ppg-count"></span><span class="mk-ppg-sp"></span>' +
            '<span>Esc 关闭</span></div>' +
        '<div class="mk-ppg-toast"></div>';

    document.body.appendChild(overlay);
    document.body.appendChild(panel);

    const fixedBox = panel.querySelector(".mk-ppg-fixed");
    const builtinBox = panel.querySelector(".mk-ppg-builtin");
    const catsBox = panel.querySelector(".mk-ppg-cats");
    const railFoot = panel.querySelector(".mk-ppg-rail-foot");
    const mainEl = panel.querySelector(".mk-ppg-main");
    const countEl = panel.querySelector(".mk-ppg-count");
    const toastEl = panel.querySelector(".mk-ppg-toast");

    function toast(text) {
        toastEl.textContent = text;
        toastEl.classList.add("is-on");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toastEl.classList.remove("is-on"), 1400);
    }

    // ── 左栏 ──
    function renderRail() {
        const manifest = _manifest;
        const total = manifest?.total || 0;

        fixedBox.textContent = "";
        FIXED_ITEMS.forEach((it) => {
            const btn = document.createElement("button");
            btn.className = "mk-ppg-item" + (active.kind === it.kind ? " is-active" : "");
            btn.innerHTML = ICON.grid +
                '<span class="mk-ppg-name"></span><span class="mk-ppg-num"></span>';
            btn.querySelector(".mk-ppg-name").textContent = it.label;
            btn.querySelector(".mk-ppg-num").textContent = String(total);
            btn.addEventListener("click", () => { active = { kind: it.kind }; renderRail(); renderMain(); });
            fixedBox.appendChild(btn);
        });

        // 内置：写真图片 → 子分类（只读，无删除）
        builtinBox.textContent = "";
        if (manifest) {
            const group = document.createElement("button");
            group.className = "mk-ppg-group" + (groupOpen ? " is-open" : "");
            group.innerHTML = '<span class="mk-ppg-chev">' + ICON.chev + '</span>' + ICON.tray +
                '<span class="mk-ppg-name"></span><span class="mk-ppg-badge">内置</span>';
            group.querySelector(".mk-ppg-name").textContent = manifest.group?.name || "写真图片";
            group.addEventListener("click", () => { groupOpen = !groupOpen; renderRail(); });
            builtinBox.appendChild(group);

            if (groupOpen) {
                const kids = document.createElement("div");
                kids.className = "mk-ppg-kids";
                (manifest.cats || []).forEach((c) => {
                    const btn = document.createElement("button");
                    btn.className = "mk-ppg-item" +
                        (active.kind === "builtin" && active.catId === c.id ? " is-active" : "");
                    btn.innerHTML = ICON.folder +
                        '<span class="mk-ppg-name"></span><span class="mk-ppg-num"></span>';
                    btn.querySelector(".mk-ppg-name").textContent = c.name;
                    btn.querySelector(".mk-ppg-num").textContent = String(c.count);
                    btn.addEventListener("click", () => {
                        active = { kind: "builtin", catId: c.id, name: c.name };
                        renderRail();
                        renderMain();
                    });
                    kids.appendChild(btn);
                });
                builtinBox.appendChild(kids);
            }
        } else {
            const hint = document.createElement("div");
            hint.className = "mk-ppg-hint";
            hint.textContent = "内置素材加载中…";
            builtinBox.appendChild(hint);
        }

        // 自建分类（可嵌套；右键菜单加子分类 / 重命名 / 删除）
        catsBox.textContent = "";
        if (!tree.length && !pendingAdd) {
            const hint = document.createElement("div");
            hint.className = "mk-ppg-hint";
            hint.textContent = "还没有分类，点上面的 ＋ 新建（分类上右键可加子分类）";
            catsBox.appendChild(hint);
        }
        renderTreeNodes(tree, catsBox, 0);
        if (pendingAdd && pendingAdd.parentId === null) appendAddRow(catsBox, 0, null);

        // 底栏
        if (active.kind === "pending") countEl.textContent = "加载中…";
        else if (active.kind === "all") countEl.textContent = "全部图片 · " + total + " 个预设";
        else if (active.kind === "builtin") {
            const c = (manifest?.cats || []).find((x) => x.id === active.catId);
            countEl.textContent = "写真图片 / " + (c?.name || active.name) + " · " + (c?.count || 0) + " 个预设";
        } else if (active.kind === "ucat") {
            countEl.textContent = "分类「" + active.name + "」 · " + activeItems.length + " 个预设";
        }
    }

    function nodeTotal(node) {
        return (node.count || 0) + (node.children || []).reduce((n, c) => n + nodeTotal(c), 0);
    }

    // 递归渲染分类树：层级靠左内边距区分
    function renderTreeNodes(nodes, container, depth) {
        (nodes || []).forEach((n) => {
            const hasKids = (n.children || []).length > 0;

            if (pendingRename && pendingRename.id === n.id) {
                appendRenameRow(container, depth, n);
                return;
            }

            const wrap = document.createElement("div");
            wrap.className = "mk-ppg-cat";

            const btn = document.createElement("button");
            btn.className = "mk-ppg-item" + (active.kind === "ucat" && active.id === n.id ? " is-active" : "");
            btn.style.paddingLeft = (9 + depth * 13) + "px";
            btn.innerHTML = '<span class="mk-ppg-chev' + (openIds.has(n.id) ? " is-open" : "") +
                (hasKids ? "" : " is-empty") + '">' + ICON.chev + "</span>" + ICON.folder +
                '<span class="mk-ppg-name"></span><span class="mk-ppg-num"></span>';
            btn.querySelector(".mk-ppg-name").textContent = n.name;
            btn.querySelector(".mk-ppg-num").textContent = String(nodeTotal(n));
            btn.addEventListener("click", () => {
                if (hasKids) {
                    if (openIds.has(n.id)) openIds.delete(n.id); else openIds.add(n.id);
                }
                active = { kind: "ucat", id: n.id, name: n.name };
                renderRail();
                renderMain();
            });
            btn.addEventListener("contextmenu", (e) => {
                e.preventDefault();
                e.stopPropagation();
                openCtxMenu(e.clientX, e.clientY, n);
            });

            // 把素材卡片拖到这个分类上 = 移动
            btn.addEventListener("dragover", (e) => {
                const types = Array.from(e.dataTransfer?.types || []);
                if (!types.includes("application/x-mk-ppg-item") && !types.includes("text/plain")) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                btn.classList.add("is-drop");
            });
            btn.addEventListener("dragleave", () => btn.classList.remove("is-drop"));
            btn.addEventListener("drop", (e) => {
                btn.classList.remove("is-drop");
                const raw = e.dataTransfer?.getData("application/x-mk-ppg-item") ||
                    e.dataTransfer?.getData("text/plain");
                if (!raw) return;
                e.preventDefault();
                let payload;
                try { payload = JSON.parse(raw); } catch (_) { return; }
                if (!payload || typeof payload.index !== "number" || payload.from === n.id) return;
                moveItem(payload.from, n.id, payload.index);
            });

            const del = document.createElement("button");
            del.className = "mk-ppg-del";
            del.title = "删除分类";
            del.textContent = "✕";
            del.addEventListener("click", (e) => { e.stopPropagation(); askDeleteCat(n); });

            wrap.appendChild(btn);
            wrap.appendChild(del);
            container.appendChild(wrap);

            if (pendingAdd && pendingAdd.parentId === n.id) appendAddRow(container, depth + 1, n.id);
            if (hasKids && openIds.has(n.id)) renderTreeNodes(n.children, container, depth + 1);
        });
    }

    function appendAddRow(container, depth, parentId) {
        const row = document.createElement("div");
        row.className = "mk-ppg-cat";
        const input = document.createElement("input");
        input.className = "mk-ppg-input";
        input.style.marginLeft = (4 + depth * 13) + "px";
        input.placeholder = parentId ? "子分类名称，回车确认" : "分类名称，回车确认";
        row.appendChild(input);
        container.appendChild(row);
        input.focus();
        input.scrollIntoView({ block: "nearest" });

        let done = false;
        const finish = (commit) => {
            if (done) return;
            done = true;
            cancelAdd = null;
            const value = input.value.trim();
            pendingAdd = null;
            if (commit && value) createCat(parentId, value);
            else renderRail();
        };
        cancelAdd = () => finish(false);

        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") { e.preventDefault(); finish(true); }
            else if (e.key === "Escape") { e.preventDefault(); finish(false); }
            e.stopPropagation();
        });
        input.addEventListener("blur", () => finish(true));
    }

    function appendRenameRow(container, depth, node) {
        const row = document.createElement("div");
        row.className = "mk-ppg-cat";
        const input = document.createElement("input");
        input.className = "mk-ppg-input";
        input.style.marginLeft = (4 + depth * 13) + "px";
        input.value = node.name;
        row.appendChild(input);
        container.appendChild(row);
        input.focus();
        input.select();

        let done = false;
        const finish = (commit) => {
            if (done) return;
            done = true;
            pendingRename = null;
            cancelRename = null;
            const value = input.value.trim();
            if (commit && value && value !== node.name) {
                node.name = value;
                if (active.kind === "ucat" && active.id === node.id) active.name = value;
                persistTree().then(() => { renderRail(); });
            } else {
                renderRail();
            }
        };
        cancelRename = () => finish(false);

        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") { e.preventDefault(); finish(true); }
            else if (e.key === "Escape") { e.preventDefault(); finish(false); }
            e.stopPropagation();
        });
        input.addEventListener("blur", () => finish(true));
    }

    async function persistTree() {
        try {
            tree = await saveTreeApi(plainTree(tree));
        } catch (err) {
            toast("保存分类失败：" + (err?.message || err));
        }
    }

    async function createCat(parentId, name) {
        const node = {
            id: newCatId(),
            name,
            count: 0,
            children: [],
        };
        if (parentId) {
            const parent = findNode(tree, parentId);
            if (parent) {
                parent.children = parent.children || [];
                parent.children.push(node);
                openIds.add(parentId);
            }
        } else {
            tree.push(node);
        }
        await persistTree();
        active = { kind: "ucat", id: node.id, name: node.name };
        renderRail();
        renderMain();
    }

    async function askDeleteCat(node) {
        const ids = subtreeIds(node);
        const extra = ids.length > 1 ? "（含 " + (ids.length - 1) + " 个子分类及其素材）" : "";
        askConfirm("删除「" + node.name + "」" + extra + "？", async () => {
            for (const id of ids) {
                try { await rmCatApi(id); } catch (_) { /* 目录不存在就算了 */ }
            }
            removeNode(tree, node.id);
            if (active.kind === "ucat" && ids.includes(active.id)) active = { kind: "all" };
            await persistTree();
            renderRail();
            renderMain();
        });
    }

    // 通用的底部确认条（避免用浏览器原生 confirm）
    function askConfirm(message, onYes) {
        railFoot.textContent = "";

        const msg = document.createElement("span");
        msg.className = "mk-ppg-msg";
        msg.textContent = message;
        msg.title = message;

        const ok = document.createElement("button");
        ok.className = "mk-ppg-btn is-danger";
        ok.textContent = "删除";
        ok.addEventListener("click", async () => {
            railFoot.textContent = "";
            await onYes();
        });

        const cancel = document.createElement("button");
        cancel.className = "mk-ppg-btn";
        cancel.textContent = "取消";
        cancel.addEventListener("click", () => { railFoot.textContent = ""; });

        railFoot.appendChild(msg);
        railFoot.appendChild(ok);
        railFoot.appendChild(cancel);
    }

    // ── 右键菜单 ──
    function closeCtxMenu() {
        if (!ctxMenu) return;
        ctxMenu.remove();
        ctxMenu = null;
        document.removeEventListener("mousedown", onDocDown, true);
        document.removeEventListener("keydown", onCtxKey, true);
    }

    function onDocDown(e) {
        if (ctxMenu && !ctxMenu.contains(e.target)) closeCtxMenu();
    }

    function onCtxKey(e) {
        if (e.key === "Escape") { e.stopPropagation(); closeCtxMenu(); }
    }

    // 右键菜单的小工具：建条目、摆位置（夹进视口）
    function mkMenuItem(label, fn, danger) {
        const b = document.createElement("button");
        b.textContent = label;
        if (danger) b.className = "is-danger";
        b.addEventListener("click", () => { closeCtxMenu(); fn(); });
        return b;
    }

    function showMenuAt(menu, x, y) {
        menu.style.visibility = "hidden";
        document.body.appendChild(menu);
        const w = menu.offsetWidth;
        const h = menu.offsetHeight;
        menu.style.left = Math.round(Math.min(Math.max(8, x), Math.max(8, innerWidth - w - 8))) + "px";
        menu.style.top = Math.round(Math.min(Math.max(8, y), Math.max(8, innerHeight - h - 8))) + "px";
        menu.style.visibility = "visible";
        ctxMenu = menu;
        setTimeout(() => {
            document.addEventListener("mousedown", onDocDown, true);
            document.addEventListener("keydown", onCtxKey, true);
        }, 0);
    }

    function openCtxMenu(x, y, node) {
        closeCtxMenu();
        const menu = document.createElement("div");
        menu.className = "mk-ppg-menu";

        menu.appendChild(mkMenuItem("新建子分类", () => {
            pendingAdd = { parentId: node.id };
            openIds.add(node.id);
            renderRail();
        }));
        menu.appendChild(mkMenuItem("重命名", () => {
            pendingRename = { id: node.id };
            renderRail();
        }));
        menu.appendChild(mkMenuItem("删除分类", () => askDeleteCat(node), true));

        showMenuAt(menu, x, y);
    }

    // 「移动到分类…」：把所有自建分类按层级列出来（素材当前所在的分类除外）
    function openMoveMenu(x, y, fromCat, idx) {
        const flat = [];
        const walk = (nodes, path) => {
            (nodes || []).forEach((n) => {
                const p = path.concat(n.name);
                flat.push({ node: n, depth: path.length });
                walk(n.children, p);
            });
        };
        walk(tree, []);

        const targets = flat.filter((t) => t.node.id !== fromCat);
        if (!targets.length) {
            toast("还没有别的分类，先新建一个");
            return;
        }

        closeCtxMenu();
        const menu = document.createElement("div");
        menu.className = "mk-ppg-menu mk-ppg-menu-scroll";
        targets.forEach((t) => {
            const b = mkMenuItem(t.node.name, () => moveItem(fromCat, t.node.id, idx));
            b.style.paddingLeft = (10 + t.depth * 14) + "px";
            b.title = t.node.name;
            menu.appendChild(b);
        });
        showMenuAt(menu, x, y);
    }

    async function moveItem(fromCat, toCat, index) {
        if (!fromCat || !toCat || fromCat === toCat) return;
        const target = findNode(tree, toCat);
        try {
            await moveItemApi(fromCat, toCat, index);
            tree = await fetchTree();
            renderRail();
            if (active.kind === "ucat") renderMain();   // 汇总视图里两边都受影响，直接重画
            toast("已移到「" + (target?.name || "目标分类") + "」");
        } catch (err) {
            toast("移动失败：" + (err?.message || err));
        }
    }

    // ── 右栏 ──
    function showEmpty(title, sub, action) {
        mainEl.textContent = "";
        const box = document.createElement("div");
        box.className = "mk-ppg-empty";
        box.innerHTML = ICON.image +
            '<div class="mk-ppg-empty-t"></div><div class="mk-ppg-empty-s"></div>';
        box.querySelector(".mk-ppg-empty-t").textContent = title;
        box.querySelector(".mk-ppg-empty-s").textContent = sub;
        if (action) {
            const btn = document.createElement("button");
            btn.className = "mk-ppg-btn is-primary";
            btn.textContent = action.label;
            btn.addEventListener("click", action.onClick);
            box.appendChild(btn);
        }
        mainEl.appendChild(box);
        gridState = null;
    }

    function cardFor(item) {
        const card = document.createElement("div");
        card.className = "mk-ppg-card";

        if (item.url) {
            const img = document.createElement("img");
            img.src = item.url;
            img.loading = "lazy";
            img.decoding = "async";
            img.alt = "";
            card.appendChild(img);
        } else {
            const ph = document.createElement("div");
            ph.className = "mk-ppg-noimg";
            ph.textContent = "纯文本预设";
            card.appendChild(ph);
        }

        const p = document.createElement("div");
        p.className = "mk-ppg-p";
        p.textContent = item.prompt;

        // 汇总视图（一级分类）里标一下这条来自哪个子分类
        if (item.catLabel) {
            const tag = document.createElement("div");
            tag.className = "mk-ppg-tag";
            tag.textContent = item.catLabel;
            card.appendChild(tag);
        }
        card.appendChild(p);

        card.addEventListener("click", async () => {
            if (!fillPrompt(node, item.prompt)) {
                toast("没找到文本框");
                return;
            }
            if (pickedCard) pickedCard.classList.remove("is-picked");
            pickedCard = card;
            card.classList.add("is-picked");
            const copied = await copyText(item.prompt);
            toast(copied ? "已填入并复制提示词" : "已填入提示词（复制失败）");
        });

        // 自建分类里的素材：可拖到左栏分类、右键可改提示词 / 移动 / 删除
        if (item.catId !== undefined) {
            card.draggable = true;
            card.title = "拖到左侧分类可移动，右键有更多操作";
            card.addEventListener("dragstart", (e) => {
                card.classList.add("is-dragging");
                const payload = JSON.stringify({ from: item.catId, index: item.idx });
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("application/x-mk-ppg-item", payload);
                e.dataTransfer.setData("text/plain", payload);
            });
            card.addEventListener("dragend", () => card.classList.remove("is-dragging"));
            card.addEventListener("contextmenu", (e) => {
                e.preventDefault();
                e.stopPropagation();
                openCardMenu(e.clientX, e.clientY, item.catId, item.idx);
            });
        }
        return card;
    }

    function openCardMenu(x, y, catId, idx) {
        closeCtxMenu();
        const menu = document.createElement("div");
        menu.className = "mk-ppg-menu";
        menu.appendChild(mkMenuItem("编辑提示词", () => openEditor(catId, idx)));
        menu.appendChild(mkMenuItem("移动到分类…", () => openMoveMenu(x, y, catId, idx)));
        menu.appendChild(mkMenuItem("删除素材", () => {
            askConfirm("删除这条素材？（图片文件保留在分类目录里）", async () => {
                const list = (itemsByCat.get(catId) || []).slice();
                if (idx < 0 || idx >= list.length) { renderMain(); return; }
                list.splice(idx, 1);
                try {
                    itemsByCat.set(catId, await saveItemsApi(catId, list));
                } catch (err) {
                    toast("删除失败：" + (err?.message || err));
                }
                tree = await fetchTree();
                renderRail();
                renderMain();
            });
        }, true));
        showMenuAt(menu, x, y);
    }

    // 添加素材的入口卡片（放在网格第一格）
    function addCard(catId) {
        const card = document.createElement("div");
        card.className = "mk-ppg-addcard";
        card.innerHTML = "<span>＋</span><span>添加素材</span>";
        card.addEventListener("click", () => openEditor(catId, null));
        return card;
    }

    // 添加 / 编辑素材的弹窗。idx 为空 = 新增
    function openEditor(catId, idx) {
        const isEdit = idx !== null && idx !== undefined;
        const cur = isEdit ? (itemsByCat.get(catId) || [])[idx] : null;
        let file = null;
        let objectUrl = "";

        const mask = document.createElement("div");
        mask.className = "mk-ppg-mask";
        mask.innerHTML =
            '<div class="mk-ppg-dlg">' +
                '<div class="mk-ppg-dlg-t"></div>' +
                '<div class="mk-ppg-drop"></div>' +
                '<textarea placeholder="粘贴或输入提示词"></textarea>' +
                '<div class="mk-ppg-dlg-f">' +
                    '<button data-role="cancel">取消</button>' +
                    '<button data-role="save" class="is-primary">保存</button>' +
                '</div>' +
            '</div>';
        panel.appendChild(mask);

        const dlg = mask.querySelector(".mk-ppg-dlg");
        const drop = mask.querySelector(".mk-ppg-drop");
        const ta = mask.querySelector("textarea");
        dlg.querySelector(".mk-ppg-dlg-t").textContent = isEdit ? "编辑提示词" : "添加素材";

        // 图片区：新增可选图；编辑时只显示当前图（换图请删掉重加）
        const fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.accept = "image/*";
        fileInput.style.display = "none";
        mask.appendChild(fileInput);

        function paintDrop() {
            drop.textContent = "";
            const src = objectUrl || (cur?.f ? assetUrl(active.id, cur.f) : "");
            if (src) {
                const img = document.createElement("img");
                img.src = src;
                img.alt = "";
                drop.appendChild(img);
                return;
            }
            drop.textContent = isEdit ? "这条素材没有配图" : "点击选择图片（可留空）";
        }
        paintDrop();

        if (!isEdit) {
            drop.addEventListener("click", () => fileInput.click());
            fileInput.addEventListener("change", () => {
                const f = fileInput.files?.[0];
                if (!f) return;
                file = f;
                if (objectUrl) URL.revokeObjectURL(objectUrl);
                objectUrl = URL.createObjectURL(f);
                paintDrop();
            });
        }

        if (isEdit) ta.value = cur.p || "";
        ta.focus();

        const closeDlg = () => {
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            mask.remove();
        };

        mask.querySelector('[data-role="cancel"]').addEventListener("click", closeDlg);
        mask.addEventListener("mousedown", (e) => { if (e.target === mask) closeDlg(); });

        mask.querySelector('[data-role="save"]').addEventListener("click", async () => {
            const prompt = ta.value.trim();
            if (!prompt && !file) {
                toast("提示词和图片至少给一个");
                return;
            }
            const btn = mask.querySelector('[data-role="save"]');
            btn.disabled = true;
            btn.textContent = "保存中…";
            try {
                if (isEdit) {
                    const list = (itemsByCat.get(catId) || []).slice();
                    if (cur) list[idx] = { ...cur, p: prompt };
                    itemsByCat.set(catId, await saveItemsApi(catId, list));
                } else {
                    await uploadItem(catId, file, prompt);
                }
                closeDlg();
                toast(isEdit ? "已保存" : "已添加");
                tree = await fetchTree();
                renderMain();
                renderRail();
            } catch (err) {
                btn.disabled = false;
                btn.textContent = "保存";
                toast("保存失败：" + (err?.message || err));
            }
        });
    }

    function appendBatch() {
        const st = gridState;
        if (!st) return false;
        const end = Math.min(st.items.length, st.shown + BATCH);
        if (end <= st.shown) return false;
        const frag = document.createDocumentFragment();
        for (let i = st.shown; i < end; i += 1) frag.appendChild(cardFor(st.items[i]));
        st.grid.appendChild(frag);
        st.shown = end;
        return true;
    }

    // 首屏没铺满就继续抽，直到能滚动或抽完（避免一屏只有几张）
    function fillViewport() {
        const st = gridState;
        if (!st) return;
        for (let guard = 0; guard < 40; guard += 1) {
            if (st.shown >= st.items.length) return;
            const h = st.grid.clientHeight;
            if (h === 0) { appendBatch(); return; }
            if (st.grid.scrollHeight > h + 240) return;
            if (!appendBatch()) return;
        }
    }

    function startGrid() {
        mainEl.textContent = "";
        const grid = document.createElement("div");
        grid.className = "mk-ppg-grid";
        mainEl.appendChild(grid);
        gridState = { items: [], shown: 0, grid };
        grid.addEventListener("scroll", () => {
            if (grid.scrollTop + grid.clientHeight >= grid.scrollHeight - 300) appendBatch();
        });
        return gridState;
    }

    // 追加一批条目（「全部图片」边加载边往网格里塞）
    function pushItems(list) {
        if (!gridState || !list.length) return;
        gridState.items.push(...list);
        fillViewport();
    }

    function showLoading() {
        mainEl.textContent = "";
        const el = document.createElement("div");
        el.className = "mk-ppg-empty";
        el.innerHTML = '<div class="mk-ppg-empty-s">加载中…</div>';
        mainEl.appendChild(el);
        gridState = null;
    }

    async function renderMain() {
        const token = ++mainToken;
        pickedCard = null;

        if (active.kind === "pending") {
            showLoading();
            return;
        }

        // 自建分类：素材来自后端 user 目录；点一级分类时把子孙分类的素材一起汇总出来
        if (active.kind === "ucat") {
            showLoading();
            try {
                const root = findNode(tree, active.id);
                const ids = root ? subtreeIds(root) : [active.id];
                const lists = await Promise.all(ids.map(async (id) => ({ id, items: await fetchItems(id) })));
                if (token !== mainToken) return;

                itemsByCat = new Map(lists.map((l) => [l.id, l.items]));
                activeItems = [];
                const multi = ids.length > 1;
                const flat = [];
                lists.forEach(({ id, items }) => {
                    const label = multi ? (findNode(tree, id)?.name || "") : "";
                    items.forEach((it, idx) => {
                        activeItems.push(it);
                        flat.push({
                            url: it.f ? assetUrl(id, it.f) : "",
                            prompt: it.p,
                            catId: id,
                            idx,
                            catLabel: label,
                        });
                    });
                });

                // 空分类：直接给一个「添加素材」按钮（注意不能先塞卡片再 showEmpty，会被一起清掉）
                if (!flat.length) {
                    showEmpty(
                        "还没有素材",
                        ids.length > 1
                            ? "这个分类和它的子分类都还是空的；新素材会加到「" + (root?.name || active.name) + "」本身"
                            : "新素材会加到当前分类",
                        { label: "＋ 添加素材", onClick: () => openEditor(active.id, null) }
                    );
                    return;
                }

                startGrid();
                gridState.grid.appendChild(addCard(active.id));   // 任何分类（含一级）都能往自己身上加
                pushItems(flat);
            } catch (err) {
                if (token !== mainToken) return;
                showEmpty("读取分类失败", String(err?.message || err));
            }
            return;
        }

        showLoading();
        try {
            const manifest = await loadManifest();
            if (token !== mainToken) return;

            if (active.kind === "builtin") {
                const c = manifest.cats.find((x) => x.id === active.catId);
                const items = c ? await loadCat(c.file) : [];
                if (token !== mainToken) return;
                if (!items.length) {
                    showEmpty("没有内容", "这个分类还是空的");
                    return;
                }
                startGrid();
                pushItems(items);
                return;
            }

            // 全部图片：先出第一个分类，其余分类边加载边追加，不再等 10 个 JSON 都到齐
            let started = false;
            for (const c of manifest.cats) {
                const items = await loadCat(c.file);
                if (token !== mainToken) return;
                if (!started) { started = true; startGrid(); }   // 第一批到之前保留“加载中”
                pushItems(items);
            }
            if (!started) showEmpty("没有内容", "内置素材为空");
        } catch (err) {
            if (token !== mainToken) return;
            showEmpty("内置素材加载失败", String(err?.message || err) + "（检查 web/ppg_data/ 是否存在）");
        }
    }

    // ── 事件 ──（面板用 inset:0 + margin:auto 居中，随窗口自动居中，无需手动定位）
    function onKeyDown(e) {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        if (ctxMenu) { closeCtxMenu(); return; }
        const mask = panel.querySelector(".mk-ppg-mask");
        if (mask) {
            const cancel = mask.querySelector('[data-role="cancel"]');
            if (cancel) { cancel.click(); return; }
        }
        if (cancelAdd) { cancelAdd(); return; }
        if (cancelRename) { cancelRename(); return; }
        closePanel();
    }

    overlay.addEventListener("mousedown", (e) => { e.preventDefault(); closePanel(); });
    panel.querySelector(".mk-ppg-close").addEventListener("click", () => closePanel());
    panel.querySelector(".mk-ppg-add").addEventListener("click", () => {
        closeCtxMenu();
        pendingRename = null;
        pendingAdd = { parentId: null };
        renderRail();
    });
    panel.addEventListener("contextmenu", (e) => e.preventDefault());
    window.addEventListener("keydown", onKeyDown, true);

    renderRail();
    renderMain();          // pending 状态先显示“加载中”

    // 自建分类树与内置素材并行加载
    fetchTree()
        .then((cats) => { tree = cats; renderRail(); })
        .catch((err) => {
            const hint = document.createElement("div");
            hint.className = "mk-ppg-hint";
            hint.textContent = "分类读取失败：" + (err?.message || err);
            catsBox.appendChild(hint);
        });

    loadManifest()
        .then((m) => {
            // 默认落在第一个子分类：首屏只要一个 JSON，比「全部图片」快得多
            if (active.kind === "pending") {
                const first = (m.cats || [])[0];
                active = first
                    ? { kind: "builtin", catId: first.id, name: first.name }
                    : { kind: "all" };
            }
            renderRail();
            return renderMain();
        })
        .catch(() => {
            if (active.kind === "pending") active = { kind: "all" };
            renderRail();
            return renderMain();
        });

    _panel = {
        cleanup() {
            clearTimeout(toastTimer);
            closeCtxMenu();
            window.removeEventListener("keydown", onKeyDown, true);
            overlay.remove();
            panel.remove();
        },
    };
}
