import { app } from "../../scripts/app.js";

// ============================================================
// MK-多媒体素材加载 —— 前端（DOM 面板，旧 LiteGraph 与 Nodes 2.0 通用）
//   把「素材库」子工作流（9 图 + 3 音频 + 3 视频）收成一个节点：
//     上：3×3 九宫格参考图（正方形预览，长边自适应）
//     中：3 个音频（预览窗 宽:高 = 2:1，带播放进度条 + 音频裁剪）
//     下：3 个视频（正方形预览 + 视频设置）
//   所有配置都存进 media_settings（JSON 字符串 widget）→ 随工作流保存，
//   后端 nodes/minimax_h3_media_loader.py 解析后给出 18 个常驻素材输出口，
//   口名与本包「MK-Minimax H3多参考生视频」的输入口逐字一致，一根线一个口直连。
//
//   迁移自 ComfyUI-JZL-MiniMax-H3 的 js/h3_media_loader.js，改动只有四处：
//   - 节点 id / 扩展名 / DOM widget 名 / DOM 属性与 CSS 类前缀换成 MK 的
//   - 上传与预览路由换成 /mk_h3/*（后端 mk_h3_media_store.py）
//   - 配色不再依赖上游的 jz_theme.js，本文件自己注入一套 --mk-h3m-* 变量
//   - 面板标题与状态栏文案改成 MK 版
//   布局算法（九宫格拟合、面板高度贴合、重绘前停播放器）与原版逐行一致。
// ============================================================

const NODE_TYPE = "MK_MinimaxH3MediaLoader";
const SETTINGS_WIDGET = "media_settings";
const DOM_WIDGET_NAME = "mk_h3_media";

const UPLOAD_ENDPOINT = "/mk_h3/upload_asset";
const IMAGE_PREVIEW = "/mk_h3/asset_preview";
const AUDIO_PREVIEW = "/mk_h3/audio_preview";
const VIDEO_PREVIEW = "/mk_h3/video_preview";
const VIDEO_THUMB = "/mk_h3/asset_video_thumb";
const AUDIO_WAVEFORM = "/mk_h3/audio_waveform";

const IMG_COUNT = 9;
const AUDIO_COUNT = 3;
const VIDEO_COUNT = 3;

// ── 配色：自带一套 --mk-h3m-* 变量 ─────────────────────────
// 面板里所有颜色都写成 var(--mk-h3m-*)，深/浅主题各一套值（照搬上游 jz_theme 的色板），
// 只在本包里用，和上游插件同装也不会互相覆盖。切主题时由 MutationObserver 重算。
const PALETTE = {
    // 变量名: [深色主题值, 浅色主题值]
    "--mk-h3m-bg": ["#1b1b1f", "#ffffff"],
    "--mk-h3m-bg-soft": ["#1e1e1e", "#f4f5f7"],
    "--mk-h3m-bg-raise": ["#2a2a2e", "#e9eaee"],
    "--mk-h3m-bg-deep": ["#111111", "#f7f8fa"],
    "--mk-h3m-border": ["#3a3a3a", "#c9ced6"],
    "--mk-h3m-text": ["#dddddd", "#23262a"],
    "--mk-h3m-text-strong": ["#eeeeee", "#15181c"],
    "--mk-h3m-text-dim": ["#888888", "#5c626b"],
    "--mk-h3m-accent-bg": ["#2a4a6a", "#2f6fbf"],
    "--mk-h3m-accent-green": ["#2f5a3a", "#1f7a4a"],
    "--mk-h3m-accent-text": ["#cfe3f7", "#ffffff"],
    "--mk-h3m-on-accent": ["#cfe3f7", "#ffffff"],
    "--mk-h3m-info": ["#cfe3f7", "#1b5e9c"],
    "--mk-h3m-ok": ["#9fd6a4", "#1f7a3a"],
    "--mk-h3m-warn": ["#c9a86a", "#8a5f10"],
    "--mk-h3m-error": ["#e08a8a", "#a32626"],
    "--mk-h3m-orange": ["#e8a87c", "#8a4a1f"],
    "--mk-h3m-tint-info": ["#2a3a4a", "#e3edf9"],
    "--mk-h3m-tint-warn": ["#5a4a2a", "#fdf1d6"],
    "--mk-h3m-tint-ok": ["#2d5a3a", "#e7f5e9"],
    "--mk-h3m-tint-error": ["#7a2a2a", "#fdeaea"],
    "--mk-h3m-panel-2": ["#2f3540", "#eceef2"],
    "--mk-h3m-inset": ["#141414", "#f5f6f8"],
    "--mk-h3m-float": ["#2a2a2e", "#ffffff"],
    "--mk-h3m-btn-warn": ["#b45309", "#c2410c"],
    "--mk-h3m-btn-primary": ["#2d5a88", "#1f6fd0"],
    "--mk-h3m-btn-info": ["#2a3a4a", "#1f6fd0"],
    "--mk-h3m-btn-ok": ["#2d5a3a", "#1f7a3a"],
    "--mk-h3m-btn-error": ["#7a2a2a", "#b3261e"],
};

function prefersLightTheme() {
    const html = document.documentElement;
    const body = document.body;
    if (html?.classList?.contains("light-theme")) return true;
    if (html?.classList?.contains("dark-theme")) return false;
    if (body?.classList?.contains("light-theme")) return true;
    if (body?.classList?.contains("dark-theme")) return false;
    try {
        const palette = app?.ui?.settings?.getSettingValue?.("Comfy.ColorPalette");
        if (palette === "light") return true;
        if (palette === "dark") return false;
    } catch (_) { /* ignore */ }
    return false;
}

function applyMkTheme() {
    const light = prefersLightTheme();
    const root = document.documentElement;
    for (const [name, [dark, bright]] of Object.entries(PALETTE)) {
        root.style.setProperty(name, light ? bright : dark);
    }
    root.dataset.mkH3mTheme = light ? "light" : "dark";
}

let mkThemeInstalled = false;

function installMkTheme() {
    if (mkThemeInstalled) return;
    mkThemeInstalled = true;
    applyMkTheme();
    const observer = new MutationObserver(applyMkTheme);
    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class", "data-theme"],
    });
    if (document.body) {
        observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    }
}

const ACCEPT = {
    image: "image/*",
    audio: "audio/*",
    video: "video/*",
};

const VIDEO_FIELDS = [
    {
        key: "force_rate", label: "强制帧率", step: 0.01, min: 0, max: 240, unit: "fps",
        hint: "0 = 保持原帧率（与「XB-BOX 加载视频」一致）",
    },
    {
        key: "skip", label: "跳过帧数", step: 1, min: 0, unit: "帧",
        hint: "在改帧率之后计数，从第 N 帧开始取（视频音轨同步从对应时间开始）",
    },
    {
        key: "width", label: "输出宽度", step: 2, min: 0, unit: "px",
        hint: "0 = 保持原尺寸；只填一边时另一边按比例并偶数对齐",
    },
    {
        key: "height", label: "输出高度", step: 2, min: 0, unit: "px",
        hint: "0 = 保持原尺寸",
    },
    {
        key: "cap", label: "帧数上限", step: 1, min: 0, unit: "帧",
        hint: "0 = 不限制（后端另有 6000 帧安全上限）；视频音轨同步裁到相同长度",
    },
];

const AUDIO_FIELDS = [
    {
        key: "start", label: "开始时间", step: 0.01, min: 0, unit: "秒",
        hint: "步长 0.01 秒；◀ ▶ 微调（按住连续调）",
    },
    {
        key: "duration", label: "音频时长", step: 0.01, min: 0, unit: "秒",
        hint: "0 = 取到结尾；步长 0.01 秒；◀ ▶ 微调（按住连续调）",
    },
];

// ── 小工具 ────────────────────────────────────────────────

function el(tag, css, text) {
    const node = document.createElement(tag);
    if (css) node.style.cssText = css;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

function readWidgetValue(w) {
    return w ? (w._state?.value ?? w.value) : undefined;
}

function setWidgetValue(node, w, value) {
    if (!w) return;
    w.value = value;
    if (w._state) w._state.value = value;
    node?.graph?.setDirtyCanvas?.(true, true);
}

function toNum(v, fallback = 0) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
}

function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
}

function fmtTime(sec) {
    const s = Number.isFinite(sec) && sec > 0 ? sec : 0;
    const m = Math.floor(s / 60);
    const rest = s - m * 60;
    return `${m}:${rest < 10 ? "0" : ""}${rest.toFixed(2)}`;
}

function trimNum(v) {
    // 0.5 → "0.5"，10 → "10"（对话框回填用）
    return String(Math.round(Number(v) * 1000) / 1000);
}

// 步长的小数位数：0.01 → 2，2 → 0
function stepDecimals(step) {
    const s = String(step ?? 1);
    const i = s.indexOf(".");
    return i < 0 ? 0 : (s.length - i - 1);
}

// 隐藏 number 输入框自带的上下小三角（改用左右按钮微调）
function ensureStepperStyle() {
    if (document.getElementById("mk-h3m-stepper-style")) return;
    const style = document.createElement("style");
    style.id = "mk-h3m-stepper-style";
    style.textContent = [
        ".mk-h3m-num::-webkit-outer-spin-button,",
        ".mk-h3m-num::-webkit-inner-spin-button{-webkit-appearance:none;margin:0;}",
        ".mk-h3m-num{-moz-appearance:textfield;appearance:textfield;}",
    ].join("");
    document.head.appendChild(style);
}

// 按住不放连续微调（调时长/帧率很省手）
function bindHoldRepeat(btn, step) {
    let delayTimer = null;
    let repeatTimer = null;
    const stop = () => {
        clearTimeout(delayTimer);
        clearInterval(repeatTimer);
        delayTimer = null;
        repeatTimer = null;
    };
    // pointer capture：光标移出按钮也能收到 pointerup，不需要往 window 上挂监听
    btn.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        try { btn.setPointerCapture?.(e.pointerId); } catch (_) {}
        step();
        delayTimer = setTimeout(() => {
            repeatTimer = setInterval(step, 90);
        }, 420);
    });
    ["pointerup", "pointercancel", "lostpointercapture", "blur"].forEach(
        (ev) => btn.addEventListener(ev, stop)
    );
    return stop;
}

let toastHost = null;
function notify(msg, isError = false) {
    try {
        if (!toastHost) {
            toastHost = el("div", [
                "position:fixed", "right:18px", "bottom:18px", "z-index:100000",
                "display:flex", "flex-direction:column", "gap:8px", "pointer-events:none",
            ].join(";"));
            document.body.appendChild(toastHost);
        }
        const box = el("div", [
            "max-width:420px", "padding:9px 14px", "border-radius:8px",
            `background:${isError ? "rgba(150,40,40,.94)" : "rgba(30,90,60,.94)"}`,
            "color:#fff", "font-size:12px", "line-height:1.45",
            "box-shadow:0 6px 20px rgba(0,0,0,.45)", "transition:opacity .25s",
        ].join(";"), msg);
        toastHost.appendChild(box);
        setTimeout(() => { box.style.opacity = "0"; }, 2400);
        setTimeout(() => { box.remove(); }, 2800);
    } catch (_) { /* ignore */ }
}

// ── 图片槽位的缩放 / 裁剪常量（与后端一致） ────────────────

const SCALE_MODES = [
    { value: "off", label: "禁用" },
    { value: "megapixels", label: "按总像素" },
];

// 缩放方式：与 ComfyUI 官方 upscale_method 同一套（名字与中文一致）
const SCALE_METHODS = [
    { value: "nearest-exact", label: "邻近-精确" },
    { value: "bilinear", label: "双线性插值" },
    { value: "area", label: "区域" },
    { value: "bicubic", label: "双三次插值" },
    { value: "lanczos", label: "Lanczos（高质量抗锯齿）" },
];
const SCALE_METHOD_DEFAULT = "lanczos";
// 摘要里用的短名
const METHOD_SHORT = {
    "nearest-exact": "邻近", bilinear: "双线性", area: "区域",
    bicubic: "双三次", lanczos: "Lanczos",
};

// 目标总像素的快捷档位
const MP_PRESETS = [0.5, 1, 2, 4, 8];

// 图片设置：缩放模式 + 目标总像素 + 缩放方式（按最长边 / 尺寸对齐 / 裁剪位置已移除）
const IMAGE_FIELDS = [
    {
        key: "scale_mode", label: "缩放模式", type: "select", options: SCALE_MODES,
        hint: "「禁用」原图直出；「按总像素」等比缩放到下面填的百万像素",
    },
    {
        key: "target_megapixels", label: "目标总像素", type: "number",
        step: 0.01, min: 0.01, max: 64, unit: "MP",
        presets: MP_PRESETS,
        showIf: (s) => s.scale_mode === "megapixels",
        hint: "1.00 MP ≈ 100 万像素（如 1152×864）；等比缩放，比例与原图一致",
    },
    {
        key: "size_multiple", label: "尺寸倍数", type: "number",
        step: 1, min: 1, max: 256,
        presets: [1, 8, 16, 32, 64],
        showIf: (s) => s.scale_mode === "megapixels",
        hint: "把缩放后的宽高就近对齐到该值的整数倍（1 = 不对齐），常用于避开 VAE 不整除",
    },
    {
        key: "scale_method", label: "缩放方式", type: "select", options: SCALE_METHODS,
        showIf: (s) => s.scale_mode === "megapixels",
        hint: "缩小建议 Lanczos / 区域；放大建议 Lanczos / 双三次；邻近-精确不产生新像素（块状）",
    },
];

// ── 配置（与后端 parse_settings 一一对应） ─────────────────

function defaultSettings() {
    return {
        version: 1,
        images: Array.from({ length: IMG_COUNT }, () => ({
            path: "", enabled: true,
            scale_mode: "off", target_megapixels: 1, scale_method: SCALE_METHOD_DEFAULT,
            size_multiple: 1,
        })),
        audios: Array.from({ length: AUDIO_COUNT }, () => ({
            path: "", enabled: true, start: 0, duration: 0,
        })),
        videos: Array.from({ length: VIDEO_COUNT }, () => ({
            path: "", enabled: true, force_rate: 0, skip: 0, width: 0, height: 0, cap: 0,
        })),
    };
}

function normalizeSettings(raw) {
    const base = defaultSettings();
    let src = raw;
    if (typeof raw === "string") {
        try { src = raw.trim() ? JSON.parse(raw) : {}; } catch (_) { src = {}; }
    }
    if (!src || typeof src !== "object") src = {};

    const fill = (list, defs, map) => {
        const arr = Array.isArray(list) ? list : [];
        return defs.map((_, i) => {
            const it = (arr[i] && typeof arr[i] === "object") ? arr[i] : {};
            return map(it);
        });
    };
    const pickValue = (v, defs) => {
        const s = String(v ?? "");
        return defs.some((d) => String(d.value) === s) ? s : String(defs[0].value);
    };
    const pickMethod = (v) => {
        const s = String(v ?? "");
        return SCALE_METHODS.some((m) => m.value === s) ? s : SCALE_METHOD_DEFAULT;
    };

    base.images = fill(src.images, base.images, (it) => ({
        path: String(it.path || ""),
        enabled: it.enabled !== false,
        scale_mode: pickValue(it.scale_mode, SCALE_MODES),
        target_megapixels: clamp(toNum(it.target_megapixels, 1), 0.01, 64),
        scale_method: pickMethod(it.scale_method),
        size_multiple: clamp(Math.round(toNum(it.size_multiple, 1)), 1, 256),
    }));
    base.audios = fill(src.audios, base.audios, (it) => ({
        path: String(it.path || ""),
        enabled: it.enabled !== false,
        start: Math.max(0, toNum(it.start, 0)),
        duration: Math.max(0, toNum(it.duration, 0)),
    }));
    base.videos = fill(src.videos, base.videos, (it) => ({
        path: String(it.path || ""),
        enabled: it.enabled !== false,
        force_rate: Math.max(0, toNum(it.force_rate, 0)),
        skip: Math.max(0, Math.round(toNum(it.skip, 0))),
        width: Math.max(0, Math.round(toNum(it.width, 0))),
        height: Math.max(0, Math.round(toNum(it.height, 0))),
        cap: Math.max(0, Math.round(toNum(it.cap, 0))),
    }));
    return base;
}

function getSettingsWidget(node) {
    return (node.widgets || []).find((w) => w.name === SETTINGS_WIDGET) || null;
}

function readSettings(node) {
    const st = node.__mkH3M;
    if (st && st.settings) return st.settings;
    const w = getSettingsWidget(node);
    const s = normalizeSettings(readWidgetValue(w));
    if (st) st.settings = s;
    return s;
}

function persistSettings(node) {
    const st = node.__mkH3M;
    if (!st) return;
    setWidgetValue(node, st.widget, JSON.stringify(st.settings));
}

// ── 上传 / 预览地址 ───────────────────────────────────────

function previewUrl(kind, path) {
    if (!path) return "";
    const base = kind === "image" ? IMAGE_PREVIEW : (kind === "audio" ? AUDIO_PREVIEW : VIDEO_PREVIEW);
    return `${base}?path=${encodeURIComponent(path)}`;
}

// 视频首帧缩略图：浏览器解不了 HEVC/H.265 时兜底显示
function videoThumbUrl(path) {
    if (!path) return "";
    return `${VIDEO_THUMB}?path=${encodeURIComponent(path)}`;
}

function fileNameOf(path) {
    const s = String(path || "");
    const i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
    return i >= 0 ? s.slice(i + 1) : s;
}

async function uploadFile(kind, file) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    const res = await fetch(UPLOAD_ENDPOINT, { method: "POST", body: fd });
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok || !data || !data.ok || !data.path) {
        throw new Error((data && data.error) || `上传失败（HTTP ${res.status}）`);
    }
    return data;
}

function pickFile(node, kind, slotIndex) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ACCEPT[kind] || "*/*";
    input.style.display = "none";
    document.body.appendChild(input);
    input.addEventListener("change", async () => {
        const file = input.files && input.files[0];
        input.remove();
        if (!file) return;
        applyUploadedFile(node, kind, slotIndex, file);
    });
    // 用户取消时不留垃圾节点
    input.addEventListener("cancel", () => input.remove());
    input.click();
}

async function applyUploadedFile(node, kind, slotIndex, file) {
    try {
        const info = await uploadFile(kind, file);
        const settings = readSettings(node);
        const list = settings[`${kind}s`];
        if (!list || !list[slotIndex]) return;
        list[slotIndex].path = info.path;
        list[slotIndex].enabled = true;   // 新素材默认启用
        persistSettings(node);
        renderSlot(node, kind, slotIndex);
        notify(`已载入 ${kind === "image" ? "图片" : kind === "audio" ? "音频" : "视频"}${slotIndex + 1}：${info.name || file.name}`);
    } catch (err) {
        notify(`上传失败：${err.message || err}`, true);
    }
}

function bindDropTarget(node, holder, kind, slotIndex) {
    holder.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.stopPropagation();
        holder.style.outline = "2px solid var(--mk-h3m-btn-primary)";
    });
    const clear = () => { holder.style.outline = "none"; };
    holder.addEventListener("dragleave", clear);
    holder.addEventListener("drop", (e) => {
        e.preventDefault();
        e.stopPropagation();
        clear();
        const file = e.dataTransfer?.files?.[0];
        if (file) applyUploadedFile(node, kind, slotIndex, file);
    });
}

// ── 通用小部件：编号 / 开关 / 清除 ─────────────────────────

function numberBadge(text) {
    return el("div", [
        "position:absolute", "left:5px", "top:5px", "z-index:3",
        "min-width:16px", "height:16px", "padding:0 4px", "box-sizing:border-box",
        "display:flex", "align-items:center", "justify-content:center",
        "border-radius:5px", "background:rgba(0,0,0,.55)", "color:#fff",
        "font-size:10px", "font-weight:600", "line-height:1", "pointer-events:none",
    ].join(";"), text);
}

function toggleSwitch(enabled, onChange) {
    const btn = el("button", [
        "position:absolute", "right:5px", "top:5px", "z-index:4",
        "width:32px", "height:17px", "padding:0", "border-radius:9px",
        "border:1px solid rgba(255,255,255,.5)", "cursor:pointer",
        "display:flex", "align-items:center", "transition:background .15s",
        "background:rgba(0,0,0,.45)",
    ].join(";"));
    btn.title = "开启 / 关闭本槽位";
    const knob = el("span", [
        "width:13px", "height:13px", "border-radius:50%", "background:#fff",
        "position:absolute", "left:2px", "transition:left .15s, background .15s",
        "box-shadow:0 1px 3px rgba(0,0,0,.5)",
    ].join(";"));
    btn.appendChild(knob);
    const paint = (on) => {
        btn.style.background = on ? "rgba(45,160,95,.85)" : "rgba(0,0,0,.45)";
        knob.style.left = on ? "16px" : "2px";
        knob.style.background = on ? "#fff" : "rgba(255,255,255,.72)";
    };
    paint(!!enabled);
    btn.addEventListener("mousedown", (e) => e.stopPropagation());
    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const next = !btn.__mkH3MOn;
        btn.__mkH3MOn = next;
        paint(next);
        onChange(next);
    });
    btn.__mkH3MOn = !!enabled;
    return btn;
}

function clearButton(onClick) {
    const btn = el("button", [
        "position:absolute", "right:5px", "bottom:5px", "z-index:4",
        "width:18px", "height:18px", "padding:0", "border-radius:5px",
        "border:1px solid rgba(255,255,255,.35)", "background:rgba(0,0,0,.5)",
        "color:#fff", "font-size:11px", "line-height:1", "cursor:pointer",
        "opacity:0", "transition:opacity .15s",
    ].join(";"), "✕");
    btn.title = "清除本槽位素材";
    btn.addEventListener("mousedown", (e) => e.stopPropagation());
    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        onClick();
    });
    return btn;
}

function slotShell(css) {
    const cell = el("div", [
        "position:relative", "border-radius:8px", "overflow:hidden",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-inset)",
        "box-sizing:border-box", "cursor:pointer",
        ...css,
    ].join(";"));
    cell.addEventListener("mouseenter", () => {
        cell.querySelectorAll("[data-mk-h3m-clear]").forEach((b) => { b.style.opacity = "1"; });
    });
    cell.addEventListener("mouseleave", () => {
        cell.querySelectorAll("[data-mk-h3m-clear]").forEach((b) => { b.style.opacity = "0"; });
    });
    return cell;
}

function applyEnabledLook(cell, enabled, hasMedia) {
    cell.style.opacity = enabled ? "1" : ".42";
    cell.style.filter = enabled ? "none" : "grayscale(85%)";
    cell.style.borderColor = hasMedia
        ? (enabled ? "var(--mk-h3m-border)" : "var(--mk-h3m-border)")
        : "var(--mk-h3m-border)";
}

// ── 图片槽位（正方形，长边自适应，底部带参数栏） ───────────

function imageSpecText(item) {
    if ((item.scale_mode || "off") !== "megapixels") return "原图直出";
    const m = METHOD_SHORT[item.scale_method] || "Lanczos";
    return `缩放到 ${toNum(item.target_megapixels, 1).toFixed(2)} MP · ${m}`;
}

function renderImageSlot(node, index, cell) {
    const settings = readSettings(node);
    const item = settings.images[index];
    cell.innerHTML = "";

    const box = el("div", "position:absolute;left:0;right:0;top:0;bottom:22px;display:flex;align-items:center;justify-content:center;background:#0b0b0d;");
    cell.appendChild(box);

    if (item.path) {
        const img = el("img", "max-width:100%;max-height:100%;width:100%;height:100%;object-fit:contain;display:block;");
        img.src = previewUrl("image", item.path);
        img.draggable = false;
        img.onerror = () => {
            box.innerHTML = "";
            box.appendChild(el("div", "color:var(--mk-h3m-error);font-size:11px;padding:6px;text-align:center;",
                "图片无法预览\n" + fileNameOf(item.path)));
        };
        box.appendChild(img);
    } else {
        box.appendChild(el("div", "color:var(--mk-h3m-text-dim);font-size:12px;text-align:center;line-height:1.5;", "＋\n点击或拖入图片"));
    }

    // 文件名（贴底栏上沿的渐隐条）
    if (item.path) {
        const nameRow = el("div", [
            "position:absolute", "left:0", "right:0", "bottom:22px", "z-index:2",
            "padding:8px 5px 3px", "font-size:10px", "color:#eaeaea", "line-height:1.2",
            "background:linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,.72) 70%)",
            "white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis",
            "pointer-events:none",
        ].join(";"), fileNameOf(item.path));
        nameRow.title = item.path;
        cell.appendChild(nameRow);
    }

    // 底部栏：参数摘要 + 「图片设置」
    const footer = el("div", [
        "position:absolute", "left:0", "right:0", "bottom:0", "height:22px", "z-index:3",
        "display:flex", "align-items:center", "gap:4px", "padding:0 5px",
        "box-sizing:border-box", "background:var(--mk-h3m-bg-soft)",
        "border-top:1px solid var(--mk-h3m-border)",
    ].join(";"));
    const spec = el("div", [
        "flex:1 1 auto", "font-size:10px", "color:var(--mk-h3m-text-dim)",
        "white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis",
    ].join(";"), imageSpecText(item));
    spec.title = "当前图片参数：" + imageSpecText(item);
    footer.appendChild(spec);

    const setBtn = el("button", [
        "flex:0 0 auto", "height:17px", "padding:0 8px", "border-radius:5px",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-btn-info)",
        "color:#fff", "font-size:10px", "cursor:pointer", "line-height:1",
    ].join(";"), "图片设置");
    setBtn.title = "缩放模式 / 目标总像素 / 目标最长边 / 尺寸对齐 / 裁剪位置";
    setBtn.addEventListener("mousedown", (e) => e.stopPropagation());
    setBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openParamDialog(node, "image", index);
    });
    footer.appendChild(setBtn);
    cell.appendChild(footer);

    cell.appendChild(numberBadge(String(index + 1)));
    cell.appendChild(toggleSwitch(item.enabled, (on) => {
        const s = readSettings(node);
        s.images[index].enabled = on;
        persistSettings(node);
        renderSlot(node, "image", index);
    }));

    if (item.path) {
        const clr = clearButton(() => {
            const s = readSettings(node);
            s.images[index].path = "";
            persistSettings(node);
            renderSlot(node, "image", index);
        });
        clr.dataset.mkH3mClear = "1";
        clr.style.bottom = "26px";
        cell.appendChild(clr);
    }

    applyEnabledLook(cell, item.enabled, !!item.path);
    cell.title = item.path ? `${item.path}\n点击可更换图片` : "点击选择图片（也可直接拖入）";
}

// ── 音频槽位（预览窗 2:1，带播放进度条） ────────────────────

function renderAudioSlot(node, index, cell) {
    const settings = readSettings(node);
    const item = settings.audios[index];
    cell.innerHTML = "";

    const body = el("div", [
        "position:absolute", "inset:0", "display:flex", "flex-direction:column",
        "justify-content:center", "gap:4px", "padding:5px 8px 24px", "box-sizing:border-box",
        "background:var(--mk-h3m-bg-soft)",
    ].join(";"));
    cell.appendChild(body);

    // 第一行：文件名 + 播放进度时间（同一行，2:1 的矮窗口才放得下）
    const nameRow = el("div", [
        "display:flex", "align-items:baseline", "gap:6px", "min-width:0",
    ].join(";"));
    const nameText = el("div", [
        "flex:1 1 auto", "min-width:0", "font-size:11px", "color:var(--mk-h3m-text)",
        "white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis",
    ].join(";"), item.path ? `🎧 ${fileNameOf(item.path)}` : "🎧 点击或拖入音频");
    nameText.title = item.path || "";
    nameRow.appendChild(nameText);
    const timeRow = el("div", [
        "flex:0 0 auto", "font-size:9px", "color:var(--mk-h3m-text-dim)",
        "white-space:nowrap", "font-variant-numeric:tabular-nums",
    ].join(";"), "");
    nameRow.appendChild(timeRow);
    body.appendChild(nameRow);

    // 底部「音频裁剪」：空槽位也要有，这样才能先设参数、选好素材后直接生效
    const footer = el("div", [
        "position:absolute", "left:0", "right:0", "bottom:0", "height:22px", "z-index:3",
        "display:flex", "align-items:center", "justify-content:flex-end",
        "padding:0 6px", "box-sizing:border-box", "pointer-events:none",
    ].join(";"));
    const setBtn = el("button", [
        "pointer-events:auto", "height:17px", "padding:0 8px", "border-radius:5px",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-btn-info)",
        "color:#fff", "font-size:10px", "cursor:pointer", "line-height:1",
    ].join(";"), "音频裁剪");
    setBtn.title = "波形上框选裁剪区间：开始时间 / 音频时长";
    setBtn.addEventListener("mousedown", (e) => e.stopPropagation());
    setBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openParamDialog(node, "audio", index);
    });
    footer.appendChild(setBtn);
    cell.appendChild(footer);

    if (!item.path) {
        body.appendChild(el("div", "font-size:11px;color:var(--mk-h3m-text-dim);", "未载入素材"));
        cell.appendChild(numberBadge(String(index + 1)));
        cell.appendChild(toggleSwitch(item.enabled, (on) => {
            const s = readSettings(node);
            s.audios[index].enabled = on;
            persistSettings(node);
            renderSlot(node, "audio", index);
        }));
        applyEnabledLook(cell, item.enabled, false);
        return;
    }

    // 播放控制 + 进度条
    const row = el("div", "display:flex;align-items:center;gap:5px;min-width:0;");
    const audio = document.createElement("audio");
    audio.preload = "metadata";
    audio.src = previewUrl("audio", item.path);
    // 挂进槽位（display:none 不占位）：脱离 DOM 的 <audio> 重绘时抓不到，
    // 会一直播下去 —— 这就是「改了时长，旧的那条还在放被裁掉部分」的根源。
    audio.style.display = "none";
    audio.dataset.mkH3mAudio = "1";
    cell.appendChild(audio);

    const playBtn = el("button", [
        "flex:0 0 auto", "width:20px", "height:20px", "padding:0", "border-radius:50%",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-bg-raise)",
        "color:var(--mk-h3m-text-strong)", "font-size:9px", "cursor:pointer", "line-height:1",
    ].join(";"), "▶");
    playBtn.title = "试听（按「开始时间 / 音频时长」预览）";
    row.appendChild(playBtn);

    const track = el("div", [
        "position:relative", "flex:1 1 auto", "min-width:0", "height:7px", "border-radius:4px",
        "background:var(--mk-h3m-bg-deep)", "border:1px solid var(--mk-h3m-border)",
        "cursor:pointer", "overflow:hidden",
    ].join(";"));
    const trimRange = el("div", [
        "position:absolute", "top:0", "bottom:0", "left:0", "width:100%",
        "background:rgba(90,160,230,.20)", "pointer-events:none",
    ].join(";"));
    const fill = el("div", [
        "position:absolute", "top:0", "bottom:0", "left:0", "width:0%",
        "background:var(--mk-h3m-btn-primary)", "pointer-events:none",
    ].join(";"));
    track.appendChild(trimRange);
    track.appendChild(fill);
    row.appendChild(track);
    body.appendChild(row);

    const start = Math.max(0, toNum(item.start, 0));
    const dur = Math.max(0, toNum(item.duration, 0));
    // 试听区间：start ~ start+dur（dur=0 → 到结尾）。播放只能在这个窗口里跑。
    const trimEnd = dur > 0 ? start + dur : Infinity;
    const inWindow = (t) => t >= start - 0.01 && t < trimEnd - 0.005;

    const paintTime = () => {
        const total = Number.isFinite(audio.duration) ? audio.duration : 0;
        const cur = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
        const pct = total > 0 ? clamp((cur / total) * 100, 0, 100) : 0;
        fill.style.width = `${pct}%`;
        const trimTo = dur > 0 ? Math.min(total || (start + dur), start + dur) : total;
        timeRow.textContent = `${fmtTime(cur)}/${fmtTime(total)} 取${trimNum(start)}–${trimTo.toFixed(2)}s`;
        timeRow.title = `播放进度 ${fmtTime(cur)} / ${fmtTime(total)}；实际取用 ${trimNum(start)}–${trimTo.toFixed(2)} 秒`;
    };

    const paintTrim = () => {
        const total = Number.isFinite(audio.duration) ? audio.duration : 0;
        if (total <= 0) { trimRange.style.left = "0%"; trimRange.style.width = "100%"; return; }
        const s = clamp(start, 0, total);
        const e = dur > 0 ? clamp(s + dur, 0, total) : total;
        trimRange.style.left = `${(s / total) * 100}%`;
        trimRange.style.width = `${Math.max(0, ((e - s) / total) * 100)}%`;
    };

    audio.addEventListener("loadedmetadata", () => {
        paintTrim();
        // 载入后光标默认停在裁剪起点（而不是 0），所见即所取
        if (start > 0 && start < (audio.duration || 0)) {
            try { audio.currentTime = start; } catch (_) {}
        }
        paintTime();
    });
    audio.addEventListener("timeupdate", () => {
        const cur = audio.currentTime || 0;
        if (cur >= trimEnd - 0.01) {
            // 到裁剪末尾：停下并回到起点，下次点播放重头放这一小段
            audio.pause();
            try { audio.currentTime = start; } catch (_) {}
        } else if (cur < start - 0.01) {
            // 进度被拖到裁剪区之前（或残留位置）：拉回起点
            try { audio.currentTime = start; } catch (_) {}
        }
        paintTime();
    });
    audio.addEventListener("play", () => {
        playBtn.textContent = "❚❚";
        // 关键：每次起播都确保落在裁剪窗口内（否则会放出被裁掉的部分）
        const cur = audio.currentTime || 0;
        if (!inWindow(cur)) {
            try { audio.currentTime = start; } catch (_) {}
        }
    });
    audio.addEventListener("pause", () => { playBtn.textContent = "▶"; });
    audio.addEventListener("ended", () => { playBtn.textContent = "▶"; });
    audio.addEventListener("error", () => { timeRow.textContent = "音频无法预览"; });

    playBtn.addEventListener("mousedown", (e) => e.stopPropagation());
    playBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (audio.paused) {
            // 同时只允许一个音频在响
            document.querySelectorAll("audio[data-mk-h3m-audio]").forEach((a) => {
                if (a !== audio) { try { a.pause(); } catch (_) {} }
            });
            audio.dataset.mkH3mAudio = "1";
            if (!inWindow(audio.currentTime || 0)) {
                try { audio.currentTime = start; } catch (_) { /* 元数据未就绪 */ }
            }
            audio.play().catch((err) => notify(`无法播放：${err.message || err}`, true));
        } else {
            audio.pause();
        }
    });

    let seeking = false;
    const seek = (ev) => {
        const rect = track.getBoundingClientRect();
        if (!rect.width || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
        const ratio = clamp((ev.clientX - rect.left) / rect.width, 0, 1);
        try { audio.currentTime = ratio * audio.duration; } catch (_) {}
        paintTime();
    };
    // 用 pointer capture 拖动进度条：不在 window 上挂监听，重绘后不会累积泄漏
    track.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        seeking = true;
        try { track.setPointerCapture?.(e.pointerId); } catch (_) {}
        seek(e);
    });
    track.addEventListener("pointermove", (e) => { if (seeking) seek(e); });
    const endSeek = (e) => {
        seeking = false;
        try { track.releasePointerCapture?.(e.pointerId); } catch (_) {}
    };
    track.addEventListener("pointerup", endSeek);
    track.addEventListener("pointercancel", endSeek);
    // 进度条的 click 不能冒泡到格子（否则会被当成「换素材」）
    track.addEventListener("click", (e) => e.stopPropagation());

    cell.appendChild(numberBadge(String(index + 1)));
    cell.appendChild(toggleSwitch(item.enabled, (on) => {
        const s = readSettings(node);
        s.audios[index].enabled = on;
        persistSettings(node);
        renderSlot(node, "audio", index);
    }));

    const clr = clearButton(() => {
        const s = readSettings(node);
        s.audios[index].path = "";
        persistSettings(node);
        renderSlot(node, "audio", index);
    });
    clr.dataset.mkH3mClear = "1";
    clr.style.bottom = "26px";
    cell.appendChild(clr);

    applyEnabledLook(cell, item.enabled, true);
    paintTime();
}

// ── 视频槽位（正方形预览 + 底部「视频设置」） ────────────────

function videoSpecText(item) {
    const parts = [];
    parts.push(item.force_rate > 0 ? `${trimNum(item.force_rate)}fps` : "原帧率");
    if (item.skip > 0) parts.push(`跳${item.skip}`);
    parts.push((item.width || item.height) ? `${item.width || "auto"}×${item.height || "auto"}` : "原尺寸");
    parts.push(item.cap > 0 ? `${item.cap}帧` : "不限帧");
    return parts.join(" · ");
}

function renderVideoSlot(node, index, cell) {
    const settings = readSettings(node);
    const item = settings.videos[index];
    cell.innerHTML = "";

    const preview = el("div", [
        "position:absolute", "left:0", "right:0", "top:0", "bottom:22px",
        "display:flex", "align-items:center", "justify-content:center",
        "background:#0b0b0d",
    ].join(";"));
    cell.appendChild(preview);

    if (item.path) {
        const thumb = videoThumbUrl(item.path);
        const video = document.createElement("video");
        video.src = previewUrl("video", item.path);
        video.poster = thumb;
        video.muted = true;
        video.loop = true;
        video.playsInline = true;
        video.preload = "metadata";
        video.dataset.mkH3mVideo = "1";
        video.style.cssText = "width:100%;height:100%;object-fit:contain;display:block;";
        preview.appendChild(video);

        const playHint = el("div", [
            "position:absolute", "left:50%", "top:50%", "transform:translate(-50%,-50%)",
            "width:38px", "height:38px", "border-radius:50%", "background:rgba(0,0,0,.5)",
            "color:#fff", "font-size:15px", "display:flex", "align-items:center",
            "justify-content:center", "pointer-events:none", "z-index:2",
        ].join(";"), "▶");
        preview.appendChild(playHint);

        video.addEventListener("click", (e) => {
            e.stopPropagation();
            if (video.paused) {
                document.querySelectorAll("video[data-mk-h3m-video]").forEach((v) => {
                    if (v !== video) { try { v.pause(); } catch (_) {} }
                });
                video.dataset.mkH3mVideo = "1";
                video.play().catch(() => {});
            } else {
                video.pause();
            }
        });
        video.addEventListener("play", () => { playHint.style.display = "none"; });
        video.addEventListener("pause", () => { playHint.style.display = "flex"; });
        // 浏览器不支持该编码（HEVC/H.265 等）→ 首帧缩略图兜底，预览窗不会空白
        video.addEventListener("error", () => {
            preview.innerHTML = "";
            const poster = el("img", "max-width:100%;max-height:100%;width:100%;height:100%;object-fit:contain;display:block;");
            poster.src = thumb;
            poster.draggable = false;
            preview.appendChild(poster);
            preview.appendChild(el("div", [
                "position:absolute", "left:0", "right:0", "bottom:0", "z-index:2",
                "padding:3px 5px", "font-size:9px", "color:#e8c98a", "text-align:center",
                "background:linear-gradient(0deg, rgba(0,0,0,.75), rgba(0,0,0,0))",
            ].join(";"), "首帧预览（浏览器不解该编码，不影响使用）"));
        });
    } else {
        preview.appendChild(el("div", "color:var(--mk-h3m-text-dim);font-size:12px;text-align:center;line-height:1.5;",
            "＋\n点击或拖入视频"));
    }

    // 底部栏：参数摘要 + 视频设置
    const footer = el("div", [
        "position:absolute", "left:0", "right:0", "bottom:0", "height:22px", "z-index:3",
        "display:flex", "align-items:center", "gap:4px", "padding:0 5px",
        "box-sizing:border-box", "background:var(--mk-h3m-bg-soft)",
        "border-top:1px solid var(--mk-h3m-border)",
    ].join(";"));
    const spec = el("div", [
        "flex:1 1 auto", "font-size:10px", "color:var(--mk-h3m-text-dim)",
        "white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis",
    ].join(";"), videoSpecText(item));
    spec.title = "当前视频参数：" + videoSpecText(item);
    footer.appendChild(spec);

    const setBtn = el("button", [
        "flex:0 0 auto", "height:17px", "padding:0 8px", "border-radius:5px",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-btn-info)",
        "color:#fff", "font-size:10px", "cursor:pointer", "line-height:1",
    ].join(";"), "视频设置");
    setBtn.title = "强制帧率 / 跳过帧数 / 输出宽高 / 帧数上限";
    setBtn.addEventListener("mousedown", (e) => e.stopPropagation());
    setBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openParamDialog(node, "video", index);
    });
    footer.appendChild(setBtn);
    cell.appendChild(footer);

    cell.appendChild(numberBadge(String(index + 1)));
    cell.appendChild(toggleSwitch(item.enabled, (on) => {
        const s = readSettings(node);
        s.videos[index].enabled = on;
        persistSettings(node);
        renderSlot(node, "video", index);
    }));

    if (item.path) {
        const clr = clearButton(() => {
            const s = readSettings(node);
            s.videos[index].path = "";
            persistSettings(node);
            renderSlot(node, "video", index);
        });
        clr.dataset.mkH3mClear = "1";
        clr.style.bottom = "26px";
        cell.appendChild(clr);
    }

    applyEnabledLook(cell, item.enabled, !!item.path);
    cell.title = item.path ? `${item.path}\n点击可更换视频` : "点击选择视频（也可直接拖入）";
}

// ── 槽位渲染分发 ─────────────────────────────────────────

const KIND_COUNT = { image: IMG_COUNT, audio: AUDIO_COUNT, video: VIDEO_COUNT };

// 重绘前必须把旧播放器停掉：脱离 DOM 的 <audio>/<video> 仍会继续播放，
// 造成「改了音频时长，旧的那条还在放被裁掉的部分」这种假象。
function stopMediaIn(el) {
    if (!el || !el.querySelectorAll) return;
    el.querySelectorAll("audio, video").forEach((m) => {
        try { m.pause(); } catch (_) { /* ignore */ }
        try {
            m.removeAttribute("src");
            m.load();
        } catch (_) { /* ignore */ }
    });
}

function slotCell(node, kind, index) {
    const st = node.__mkH3M;
    return st?.cells?.[kind]?.[index] || null;
}

function renderSlot(node, kind, index) {
    const cell = slotCell(node, kind, index);
    if (!cell) return;
    stopMediaIn(cell);
    if (kind === "image") renderImageSlot(node, index, cell);
    else if (kind === "audio") renderAudioSlot(node, index, cell);
    else renderVideoSlot(node, index, cell);
    updateSectionMeta(node, kind);       // 折叠头右侧的「N 个已载入」
    node.setDirtyCanvas?.(true, true);
}

function renderAllSlots(node) {
    for (const kind of ["image", "audio", "video"]) {
        for (let i = 0; i < KIND_COUNT[kind]; i++) renderSlot(node, kind, i);
    }
    // 重绘后内容高度可能变化（无滚动条模式）→ 让节点高度重新贴合
    setTimeout(() => {
        try { node.__mkH3M?.fitPanelHeight?.(); } catch (_) {}
    }, 40);
}

// ── 音频裁剪面板：波形图 + 拖拽框选 + 试听 ─────────────────
// 波形由后端 /mk_h3/audio_waveform 解码后给（服务端解码，m4a / opus / wma 也能画）。

const WAVE_BUCKETS = 600;

function attachWaveTrimmer(host, item, current, syncFields) {
    const head = el("div", "display:flex;align-items:center;gap:8px;margin-bottom:5px;");
    const playBtn = el("button", [
        "flex:0 0 auto", "height:24px", "padding:0 10px", "border-radius:6px",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-btn-info)",
        "color:#fff", "font-size:11px", "cursor:pointer", "line-height:1",
    ].join(";"), "▶ 试听");
    playBtn.title = "按当前裁剪区间试听";
    const info = el("div", [
        "flex:1 1 auto", "min-width:0", "font-size:10px", "color:var(--mk-h3m-text-dim)",
        "white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis",
    ].join(";"), "加载波形…");
    head.appendChild(playBtn);
    head.appendChild(info);

    const canvas = document.createElement("canvas");
    canvas.style.cssText = [
        "width:100%", "height:92px", "display:block", "border-radius:6px",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-bg-deep)",
        "cursor:crosshair", "touch-action:none", "box-sizing:border-box",
    ].join(";");
    const legend = el("div", [
        "font-size:10px", "color:var(--mk-h3m-text-dim)", "margin-top:3px", "line-height:1.3",
    ].join(";"), "在波形上拖动框选；拖两端手柄微调；点空白重新框选");

    const audio = document.createElement("audio");
    audio.preload = "auto";
    audio.style.display = "none";

    host.appendChild(head);
    host.appendChild(canvas);
    host.appendChild(legend);
    host.appendChild(audio);

    const state = { dur: 0, peaks: null, buckets: 0, maxAbs: 1, playPos: -1 };
    const round2 = (v) => Math.round(v * 100) / 100;

    // 当前生效区间：duration = 0 视为「到结尾」
    const trimRange = () => {
        const total = state.dur;
        const s = clamp(toNum(current.start, 0), 0, total || 0);
        const d = Math.max(0, toNum(current.duration, 0));
        const e = d > 0 ? Math.min(total, s + d) : total;
        return [s, Math.max(s + 0.01, e)];
    };

    const draw = () => {
        const w = canvas.clientWidth, h = canvas.clientHeight;
        if (!w || !h) return;
        const dpr = window.devicePixelRatio || 1;
        const pw = Math.round(w * dpr), ph = Math.round(h * dpr);
        if (canvas.width !== pw || canvas.height !== ph) {
            canvas.width = pw;
            canvas.height = ph;
        }
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);

        const mid = h / 2;
        ctx.strokeStyle = "rgba(255,255,255,.12)";
        ctx.beginPath();
        ctx.moveTo(0, Math.round(mid) + .5);
        ctx.lineTo(w, Math.round(mid) + .5);
        ctx.stroke();

        if (!state.peaks || !state.buckets || state.dur <= 0) return;

        const [s, e] = trimRange();
        const xs = (s / state.dur) * w;
        const xe = (e / state.dur) * w;

        // 选区底色
        ctx.fillStyle = "rgba(90,160,230,.20)";
        ctx.fillRect(xs, 0, Math.max(1, xe - xs), h);

        // 波形
        const step = w / state.buckets;
        const amp = (mid - 4) / state.maxAbs;
        for (let i = 0; i < state.buckets; i++) {
            const mn = state.peaks[2 * i], mx = state.peaks[2 * i + 1];
            if (mn === undefined || mx === undefined) continue;
            const x = i * step;
            const y0 = mid - mx * amp, y1 = mid - mn * amp;
            const inSel = (x + step) >= xs && x <= xe;
            ctx.fillStyle = inSel ? "rgba(127,182,240,.95)" : "rgba(150,162,178,.42)";
            ctx.fillRect(x, Math.min(y0, y1), Math.max(1, step * 0.9),
                         Math.max(1, Math.abs(y1 - y0)));
        }

        // 两端手柄
        ctx.fillStyle = "var(--mk-h3m-btn-primary)";
        ctx.fillStyle = "#2d7ae0";
        ctx.fillRect(xs - 1, 0, 2.5, h);
        ctx.fillRect(xe - 1.5, 0, 2.5, h);

        // 播放头
        if (state.playPos >= 0) {
            ctx.fillStyle = "#ff7b72";
            ctx.fillRect((state.playPos / state.dur) * w - 1, 0, 2, h);
        }
    };

    const paintInfo = () => {
        if (!state.dur) return;
        const [s, e] = trimRange();
        info.textContent = `时长 ${fmtTime(state.dur)}`;
        legend.textContent =
            `取 ${s.toFixed(2)} – ${e.toFixed(2)} s（共 ${(e - s).toFixed(2)}s）` +
            "  ·  波形上拖动框选，拖两端手柄微调";
    };

    const syncAll = () => { syncFields(); paintInfo(); draw(); };

    // ── 拖拽交互 ──────────────────────────────────────────
    const timeAt = (clientX) => {
        const rect = canvas.getBoundingClientRect();
        if (!rect.width || state.dur <= 0) return 0;
        return clamp((clientX - rect.left) / rect.width, 0, 1) * state.dur;
    };

    let drag = null;
    canvas.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        if (state.dur <= 0) return;
        const t = timeAt(e.clientX);
        const [s, en] = trimRange();
        const tol = state.dur * 0.02;                 // 手柄判定半径（约 2% 宽度）
        if (Math.abs(t - s) <= tol) drag = { mode: "start" };
        else if (Math.abs(t - en) <= tol) drag = { mode: "end" };
        else if (t > s && t < en) drag = { mode: "move", grab: t - s };
        else {
            drag = { mode: "new", anchor: t };
            current.start = round2(t);
            current.duration = 0;                     // 先当成「到结尾」，拖开再定
            syncAll();
        }
        try { canvas.setPointerCapture?.(e.pointerId); } catch (_) {}
        if (drag.mode !== "new") draw();
    });

    canvas.addEventListener("pointermove", (e) => {
        if (!drag) return;
        e.stopPropagation();
        const t = timeAt(e.clientX);
        const total = state.dur;
        const [s, en] = trimRange();
        if (drag.mode === "start") {
            const ns = clamp(t, 0, en - 0.02);
            current.start = round2(ns);
            current.duration = en >= total - 0.005 ? 0 : round2(en - ns);
            syncAll();
        } else if (drag.mode === "end") {
            const ne = clamp(t, s + 0.02, total);
            current.start = round2(s);
            current.duration = ne >= total - 0.005 ? 0 : round2(ne - s);
            syncAll();
        } else if (drag.mode === "move") {
            const span = Math.max(0.02, en - s);
            const ns = clamp(t - drag.grab, 0, Math.max(0, total - span));
            current.start = round2(ns);
            if (current.duration > 0) current.duration = round2(span);
            syncAll();
        } else if (drag.mode === "new") {
            const a = drag.anchor;
            const lo = Math.min(a, t), hi = Math.max(a, t);
            current.start = round2(lo);
            current.duration = hi >= total - 0.005 ? 0 : round2(hi - lo);
            syncAll();
        }
    });

    const endDrag = (e) => {
        if (!drag) return;
        drag = null;
        try { canvas.releasePointerCapture?.(e.pointerId); } catch (_) {}
        syncAll();
    };
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);

    // ── 试听（只在裁剪区间内放）───────────────────────────
    const ensureSrc = () => {
        if (audio.src || !item.path) return;
        audio.src = previewUrl("audio", item.path);
        audio.load();
    };
    playBtn.addEventListener("mousedown", (e) => e.stopPropagation());
    playBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!item.path) { notify("这个槽位还没选音频", true); return; }
        ensureSrc();
        if (!audio.paused) { audio.pause(); return; }
        const [s] = trimRange();
        try { audio.currentTime = s; } catch (_) { /* 元数据未就绪 */ }
        audio.play().catch((err) => notify(`无法播放：${err.message || err}`, true));
    });
    audio.addEventListener("play", () => { playBtn.textContent = "❚❚ 暂停"; });
    audio.addEventListener("pause", () => {
        playBtn.textContent = "▶ 试听";
        state.playPos = -1;
        draw();
    });
    audio.addEventListener("timeupdate", () => {
        const [s, en] = trimRange();
        state.playPos = Number.isFinite(audio.currentTime) ? audio.currentTime : -1;
        if (state.playPos >= en - 0.01) {
            audio.pause();
            try { audio.currentTime = s; } catch (_) {}
            state.playPos = -1;
        }
        draw();
    });
    audio.addEventListener("error", () => { info.textContent = "音频无法预览（格式不被浏览器支持）"; });

    // ── 拉波形 ────────────────────────────────────────────
    (async () => {
        if (!item.path) {
            info.textContent = "未选择音频";
            return;
        }
        try {
            const r = await fetch(
                `${AUDIO_WAVEFORM}?path=${encodeURIComponent(item.path)}&buckets=${WAVE_BUCKETS}`,
                { cache: "no-cache" });
            const d = await r.json().catch(() => ({}));
            if (!r.ok || !d.ok) throw new Error(d.error || `HTTP ${r.status}`);
            state.dur = Math.max(0, Number(d.duration) || 0);
            state.peaks = Array.isArray(d.peaks) ? d.peaks : [];
            state.buckets = Math.max(0, Number(d.buckets) || 0);
            let maxAbs = 0;
            for (const v of state.peaks) maxAbs = Math.max(maxAbs, Math.abs(Number(v) || 0));
            state.maxAbs = maxAbs || 1;
            // 把越界的裁剪参数收回有效范围
            if (state.dur > 0) {
                if (toNum(current.start, 0) > state.dur) current.start = 0;
                if (toNum(current.duration, 0) > state.dur) current.duration = 0;
            }
            syncAll();
            requestAnimationFrame(draw);
        } catch (err) {
            info.textContent = `波形加载失败（仍可直接填数字）：${err.message || err}`;
        }
    })();

    // 对话框宽度变化时重绘
    if (typeof ResizeObserver !== "undefined") {
        try { new ResizeObserver(() => draw()).observe(canvas); } catch (_) {}
    }
    requestAnimationFrame(() => { paintInfo(); draw(); });
}

// ── 参数对话框（图片 / 视频 / 音频共用） ─────────────────────

const DIALOG_ID = "mk-h3m-param-dialog";

const DIALOG_TITLES = {
    image: ["🖼️", "图片", "设置"],
    video: ["🎬", "视频", "设置"],
    audio: ["🎧", "音频", "裁剪"],
};
const DIALOG_FIELDS = { image: IMAGE_FIELDS, video: VIDEO_FIELDS, audio: AUDIO_FIELDS };

function closeDialog() {
    const overlay = document.getElementById(DIALOG_ID);
    if (!overlay) return;
    // 关掉正在试听的音频/视频，避免后台继续播
    overlay.querySelectorAll("audio, video").forEach((m) => {
        try { m.pause(); m.removeAttribute("src"); m.load(); } catch (_) { /* ignore */ }
    });
    overlay.remove();
}

function openParamDialog(node, kind, index) {
    closeDialog();
    const settings = readSettings(node);
    const list = settings[`${kind}s`];
    const item = list[index];
    if (!item) return;

    const fields = DIALOG_FIELDS[kind] || AUDIO_FIELDS;
    const [icon, cn, action] = DIALOG_TITLES[kind] || ["⚙️", "槽位", "设置"];
    const title = `${icon} ${cn}${index + 1} ${action}`;
    const sub = item.path ? fileNameOf(item.path) : "（未选择素材，参数会先保存，选好素材后生效）";

    const overlay = el("div", [
        "position:fixed", "inset:0", "background:rgba(0,0,0,.55)", "z-index:99999",
        "display:flex", "align-items:center", "justify-content:center",
    ].join(";"));
    overlay.id = DIALOG_ID;
    overlay.addEventListener("mousedown", (e) => {
        if (e.target === overlay) closeDialog();
    });

    const panel = el("div", [
        "background:var(--mk-h3m-bg)", "border:1px solid var(--mk-h3m-border)",
        "border-radius:10px", "padding:16px", "width:380px", "max-width:92vw",
        "box-shadow:0 12px 40px rgba(0,0,0,.6)", "color:var(--mk-h3m-text)",
    ].join(";"));
    overlay.appendChild(panel);

    panel.appendChild(el("div", "font-size:14px;font-weight:600;color:var(--mk-h3m-text-strong);margin-bottom:2px;", title));
    panel.appendChild(el("div", "font-size:11px;color:var(--mk-h3m-text-dim);margin-bottom:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;", sub));

    const current = { ...item };   // 对话框内的编辑缓冲，确定时整体写回
    const rows = [];               // 用于 showIf 动态显隐
    ensureStepperStyle();

    // 音频：先摆一块波形区域（字段渲染完再异步填内容）
    let waveHost = null;
    if (kind === "audio") {
        waveHost = el("div", "margin-bottom:10px;");
        panel.appendChild(waveHost);
    }

    const refreshVisibility = () => {
        for (const r of rows) {
            const on = !r.field.showIf || r.field.showIf(current);
            r.row.style.display = on ? "flex" : "none";
            if (r.hint) r.hint.style.display = on ? "block" : "none";
            if (r.presets) r.presets.style.display = on ? "flex" : "none";
        }
    };

    const labelOf = (field) =>
        el("div", "flex:0 0 72px;font-size:12px;color:var(--mk-h3m-text);", field.label);

    // 数字字段：◀ [输入框] 单位 ▶（可按住连续调）
    const buildNumberField = (field) => {
        const row = el("div", "display:flex;align-items:center;gap:6px;margin-bottom:9px;");
        row.appendChild(labelOf(field));

        const stepVal = Number(field.step ?? 1);
        const dec = stepDecimals(field.step);

        const mkStepBtn = (text, title) => {
            const b = el("button", [
                "flex:0 0 auto", "width:22px", "height:26px", "padding:0",
                "display:flex", "align-items:center", "justify-content:center",
                "border-radius:6px", "border:1px solid var(--mk-h3m-border)",
                "background:var(--mk-h3m-bg-raise)", "color:var(--mk-h3m-text-strong)",
                "font-size:13px", "line-height:1", "cursor:pointer",
                "user-select:none", "touch-action:none",
            ].join(";"), text);
            b.title = title;
            return b;
        };
        const decBtn = mkStepBtn("◀", `减 ${stepVal}${field.unit || ""}（可按住连续调整）`);
        const incBtn = mkStepBtn("▶", `加 ${stepVal}${field.unit || ""}（可按住连续调整）`);
        row.appendChild(decBtn);

        const input = document.createElement("input");
        input.type = "number";
        input.className = "mk-h3m-num";
        input.step = String(stepVal);
        if (field.min !== undefined) input.min = String(field.min);
        if (field.max !== undefined) input.max = String(field.max);
        input.value = trimNum(current[field.key] ?? 0);
        input.style.cssText = [
            "flex:1 1 auto", "min-width:0", "height:26px", "padding:0 8px",
            "box-sizing:border-box", "border-radius:6px", "text-align:center",
            "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-bg-deep)",
            "color:var(--mk-h3m-text-strong)", "font-size:12px", "outline:none",
        ].join(";");
        row.appendChild(input);

        const writeBuf = (v) => {
            current[field.key] = dec === 0 ? Math.round(v) : Number(v.toFixed(dec));
            refreshVisibility();
        };
        const nudge = (dir) => {
            let v = toNum(input.value, 0) + dir * stepVal;
            if (field.min !== undefined) v = Math.max(field.min, v);
            if (field.max !== undefined) v = Math.min(field.max, v);
            // 按步长精度取整，杜绝 0.01 步进累积出 4.0100000001 这种尾巴
            v = dec === 0 ? Math.round(v) : Number(v.toFixed(dec));
            input.value = dec === 0 ? String(v) : v.toFixed(dec);
            writeBuf(v);
        };
        bindHoldRepeat(decBtn, () => nudge(-1));
        bindHoldRepeat(incBtn, () => nudge(1));
        input.addEventListener("input", () => {
            let v = toNum(input.value, 0);
            if (field.min !== undefined) v = Math.max(field.min, v);
            if (field.max !== undefined) v = Math.min(field.max, v);
            writeBuf(v);
        });

        if (field.unit) row.appendChild(el("div", "flex:0 0 auto;min-width:18px;font-size:11px;color:var(--mk-h3m-text-dim);", field.unit));
        row.appendChild(incBtn);
        panel.appendChild(row);

        let hint = null;
        if (field.hint) {
            hint = el("div", "font-size:10px;color:var(--mk-h3m-text-dim);margin:-5px 0 9px 78px;line-height:1.3;", field.hint);
            panel.appendChild(hint);
        }

        // 快捷档位（目标值一点即填）
        let presets = null;
        if (field.presets && field.presets.length) {
            presets = el("div", "display:flex;flex-wrap:wrap;gap:4px;margin:-4px 0 9px 78px;");
            for (const p of field.presets) {
                const b = el("button", [
                    "flex:0 0 auto", "min-width:26px", "height:20px", "padding:0 6px",
                    "border-radius:5px", "border:1px solid var(--mk-h3m-border)",
                    "background:var(--mk-h3m-bg-raise)", "color:var(--mk-h3m-text)",
                    "font-size:10px", "line-height:1", "cursor:pointer",
                ].join(";"), String(p));
                b.title = `填 ${p}（当前 ${trimNum(p)}）`;
                b.addEventListener("mousedown", (e) => e.stopPropagation());
                b.addEventListener("click", (e) => {
                    e.stopPropagation();
                    input.value = trimNum(p);
                    current[field.key] = p;
                    refreshVisibility();
                });
                presets.appendChild(b);
            }
            panel.appendChild(presets);
        }

        return { row, hint, presets, input };
    };

    // 下拉字段：原生 select（选项值可为数字，如尺寸对齐）
    const buildSelectField = (field) => {
        const row = el("div", "display:flex;align-items:center;gap:6px;margin-bottom:9px;");
        row.appendChild(labelOf(field));

        const sel = document.createElement("select");
        sel.style.cssText = [
            "flex:1 1 auto", "min-width:0", "height:26px", "padding:0 6px",
            "box-sizing:border-box", "border-radius:6px", "cursor:pointer",
            "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-bg-deep)",
            "color:var(--mk-h3m-text-strong)", "font-size:12px", "outline:none",
        ].join(";");
        for (const opt of field.options) {
            const o = document.createElement("option");
            o.value = String(opt.value);
            o.textContent = opt.label;
            o.style.background = "var(--mk-h3m-bg-deep)";
            o.style.color = "var(--mk-h3m-text-strong)";
            sel.appendChild(o);
        }
        sel.value = String(current[field.key] ?? field.options[0].value);
        sel.addEventListener("change", () => {
            current[field.key] = field.numeric ? toNum(sel.value, 0) : sel.value;
            refreshVisibility();
        });
        sel.addEventListener("mousedown", (e) => e.stopPropagation());
        row.appendChild(sel);
        panel.appendChild(row);

        let hint = null;
        if (field.hint) {
            hint = el("div", "font-size:10px;color:var(--mk-h3m-text-dim);margin:-5px 0 9px 78px;line-height:1.3;", field.hint);
            panel.appendChild(hint);
        }
        return { row, hint, presets: null };
    };

    for (const field of fields) {
        let built;
        if (field.type === "select") built = buildSelectField(field);
        else built = buildNumberField(field);
        rows.push({ field, ...built });
    }
    refreshVisibility();

    // 音频裁剪面板：波形 + 拖拽框选 + 试听（字段就绪后再挂，拖动时可同步输入框）
    if (kind === "audio" && waveHost) {
        const startRow = rows.find((r) => r.field.key === "start");
        const durRow = rows.find((r) => r.field.key === "duration");
        attachWaveTrimmer(waveHost, item, current, () => {
            if (startRow?.input) startRow.input.value = trimNum(current.start);
            if (durRow?.input) durRow.input.value = trimNum(current.duration);
        });
    }

    const btnRow = el("div", "display:flex;justify-content:flex-end;gap:8px;margin-top:12px;");
    const cancel = el("button", [
        "height:28px", "padding:0 14px", "border-radius:6px",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-bg-raise)",
        "color:var(--mk-h3m-text)", "font-size:12px", "cursor:pointer",
    ].join(";"), "取消");
    cancel.addEventListener("click", closeDialog);
    const ok = el("button", [
        "height:28px", "padding:0 14px", "border-radius:6px",
        "border:1px solid var(--mk-h3m-border)", "background:var(--mk-h3m-btn-primary)",
        "color:#fff", "font-size:12px", "cursor:pointer",
    ].join(";"), "确定");
    btnRow.appendChild(cancel);
    btnRow.appendChild(ok);
    panel.appendChild(btnRow);

    const commit = () => {
        const latest = readSettings(node);
        const target = latest[`${kind}s`][index];
        for (const field of fields) {
            if (!(field.key in current)) continue;
            target[field.key] = current[field.key];
        }
        persistSettings(node);
        closeDialog();
        renderSlot(node, kind, index);
    };
    ok.addEventListener("click", commit);
    panel.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); commit(); }
        if (e.key === "Escape") { e.preventDefault(); closeDialog(); }
    });

    document.body.appendChild(overlay);
    const firstRow = rows[0];
    setTimeout(() => {
        try {
            const firstInput = firstRow?.row?.querySelector("input, select");
            firstInput?.focus?.();
            firstInput?.select?.();
        } catch (_) {}
    }, 30);
}

// ── 节点装配 ─────────────────────────────────────────────

// 分组折叠状态：存在节点 properties（随工作流保存），键名沿用包内 mk_ 前缀
const FOLDED_KEY = "mk_h3m_folded";

function readFolded(node, kind, fallback) {
    const m = node.properties?.[FOLDED_KEY];
    return (m && typeof m[kind] === "boolean") ? m[kind] : fallback;
}

function writeFolded(node, kind, folded) {
    if (!node.properties) node.properties = {};
    const cur = node.properties[FOLDED_KEY];
    const m = (cur && typeof cur === "object") ? { ...cur } : {};
    m[kind] = folded;
    node.properties[FOLDED_KEY] = m;
    try { node.graph?.setDirtyCanvas?.(true, true); } catch (_) {}
}

function gridStyle() {
    return [
        "flex:0 0 auto", "display:grid", "grid-template-columns:repeat(3, minmax(0,1fr))",
        "gap:6px",
    ].join(";");
}

function buildSlotGrid(node, kind, count, cellStyle) {
    const grid = el("div", gridStyle());
    node.__mkH3M.cells[kind] = [];
    for (let i = 0; i < count; i++) {
        const cell = slotShell([`aspect-ratio:${cellStyle}`, "width:100%"]);
        bindDropTarget(node, cell, kind, i);
        cell.addEventListener("mousedown", (e) => {
            // 左键点空白处 = 选/换素材（开关、按钮自己 stopPropagation）
            if (e.button !== 0) return;
            e.stopPropagation();
        });
        cell.addEventListener("click", (e) => {
            if (e.button !== 0) return;
            e.stopPropagation();
            pickFile(node, kind, i);
        });
        node.__mkH3M.cells[kind].push(cell);
        grid.appendChild(cell);
    }
    return grid;
}

// 可折叠分组：标题行可点，折叠时只藏显示、不影响装载
function buildSection(node, kind, title, count, cellStyle, defaultFolded) {
    const folded = readFolded(node, kind, defaultFolded);

    const header = el("div", [
        "flex:0 0 auto", "display:flex", "align-items:center", "gap:6px",
        "padding:2px 4px", "border-radius:5px", "cursor:pointer",
        "user-select:none", "transition:background .12s",
    ].join(";"));
    header.title = "点击折叠 / 展开这一组（折叠只影响显示，装载照旧）";

    const arrow = el("span", [
        "flex:0 0 auto", "width:10px", "text-align:center",
        "font-size:9px", "color:var(--mk-h3m-text-dim)", "line-height:1",
    ].join(";"), folded ? "▶" : "▼");
    const label = el("span", [
        "flex:0 0 auto", "font-size:11px", "font-weight:600",
        "color:var(--mk-h3m-info)", "letter-spacing:.3px",
    ].join(";"), title);
    const meta = el("span", [
        "flex:0 1 auto", "margin-left:auto", "font-size:10px",
        "color:var(--mk-h3m-text-dim)", "white-space:nowrap",
        "overflow:hidden", "text-overflow:ellipsis",
    ].join(";"), "");

    header.appendChild(arrow);
    header.appendChild(label);
    header.appendChild(meta);

    const body = buildSlotGrid(node, kind, count, cellStyle);
    body.style.display = folded ? "none" : "grid";

    header.addEventListener("mouseenter", () => {
        header.style.background = "var(--mk-h3m-bg-raise)";
    });
    header.addEventListener("mouseleave", () => {
        header.style.background = "transparent";
    });
    header.addEventListener("pointerdown", (e) => e.stopPropagation());
    header.addEventListener("mousedown", (e) => e.stopPropagation());
    header.addEventListener("click", (e) => {
        e.stopPropagation();
        const willOpen = body.style.display === "none";
        body.style.display = willOpen ? "grid" : "none";
        arrow.textContent = willOpen ? "▼" : "▶";
        writeFolded(node, kind, !willOpen);
        // 折叠 / 展开后让节点高度重新贴合内容（允许收缩，否则底部会永远留一截）
        setTimeout(() => {
            try { node.__mkH3M?.fitPanelHeight?.(true); } catch (_) {}
        }, 30);
    });

    node.__mkH3M.sections[kind] = { header, body, meta, label, arrow };
    return { header, body };
}

// 工作流载入后 properties 才反序列化 → 再按存下来的折叠状态重应用一遍
function applyFoldedState(node) {
    const st = node.__mkH3M;
    if (!st?.sections) return;
    const m = node.properties?.[FOLDED_KEY];
    if (!m || typeof m !== "object") return;
    for (const kind of ["image", "audio", "video"]) {
        const sec = st.sections[kind];
        if (!sec || typeof m[kind] !== "boolean") continue;
        const folded = m[kind];
        sec.body.style.display = folded ? "none" : "grid";
        if (sec.arrow) sec.arrow.textContent = folded ? "▶" : "▼";
    }
    setTimeout(() => {
        try { st.fitPanelHeight?.(true); } catch (_) {}
    }, 30);
}

// 折叠头右侧的「N 个已载入」提示（折叠时也能看出这组有没有素材）
function updateSectionMeta(node, kind) {
    const sec = node.__mkH3M?.sections?.[kind];
    if (!sec) return;
    const settings = readSettings(node);
    const list = settings[`${kind}s`] || [];
    const loaded = list.filter((it) => it.path);
    const enabled = loaded.filter((it) => it.enabled).length;
    if (!loaded.length) {
        sec.meta.textContent = "";
        sec.meta.style.color = "var(--mk-h3m-text-dim)";
        return;
    }
    sec.meta.textContent = enabled === loaded.length
        ? `${loaded.length} 个已载入`
        : `${loaded.length} 个已载入 · ${loaded.length - enabled} 个已关闭`;
    sec.meta.style.color = enabled ? "var(--mk-h3m-ok)" : "var(--mk-h3m-text-dim)";
}

function buildPanel(node) {
    const container = el("div", [
        "width:100%", "height:100%", "display:flex", "flex-direction:column", "gap:6px",
        "padding:8px", "box-sizing:border-box",
        // 不留滚动条：内容高度由 fitPanelHeight 反映到节点高度上（永远全部可见）
        "overflow:hidden", "background:var(--mk-h3m-bg)", "border-radius:8px",
    ].join(";"));
    container.addEventListener("pointerdown", (e) => e.stopPropagation());
    container.addEventListener("mousedown", (e) => e.stopPropagation());

    const head = el("div", "flex:0 0 auto;display:flex;align-items:center;gap:8px;");
    head.appendChild(el("div", "font-size:12px;font-weight:600;color:var(--mk-h3m-text-strong);", "📥 多媒体素材加载"));
    const status = el("div", [
        "flex:1 1 auto", "font-size:10px", "color:var(--mk-h3m-text-dim)",
        "white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis", "text-align:right",
    ].join(";"), "9 图 丨 3 音频 丨 3 视频 → 素材总线");
    status.title = "执行后显示实际载入数量";
    head.appendChild(status);
    node.__mkH3M.status = status;
    container.appendChild(head);

    // 参考图：默认展开
    const imgSec = buildSection(node, "image", `🖼️ 参考图 1–${IMG_COUNT}`,
                                IMG_COUNT, "1 / 1", false);
    container.appendChild(imgSec.header);
    container.appendChild(imgSec.body);

    // 参考音频：默认折叠（平时用不到）
    const audSec = buildSection(node, "audio", `🎧 参考音频 1–${AUDIO_COUNT}`,
                                AUDIO_COUNT, "2 / 1", true);
    container.appendChild(audSec.header);
    container.appendChild(audSec.body);

    // 参考视频：默认折叠
    const vidSec = buildSection(node, "video", `🎬 参考视频 1–${VIDEO_COUNT}`,
                                VIDEO_COUNT, "1 / 1", true);
    container.appendChild(vidSec.header);
    container.appendChild(vidSec.body);

    return container;
}

function setupMediaLoader(node) {
    if (node.__mkH3M) return;

    const widget = getSettingsWidget(node);
    node.__mkH3M = {
        settings: normalizeSettings(readWidgetValue(widget)),
        widget,
        cells: { image: [], audio: [], video: [] },
        sections: { image: null, audio: null, video: null },   // 折叠头（含已载入提示）
        status: null,
    };

    // 隐藏内部 JSON widget（存储用，不给用户看）
    const hideTargets = new Set([SETTINGS_WIDGET]);
    for (const w of node.widgets || []) {
        if (!w || !hideTargets.has(w.name)) continue;
        w.hidden = true;
        if (!w.options) w.options = {};
        w.options.hidden = true;
        w.computeSize = () => [0, -4];
    }
    try { if (Array.isArray(node.widgets)) node.widgets = node.widgets.slice(); } catch (_) {}

    const container = buildPanel(node);
    const dom = node.addDOMWidget?.(DOM_WIDGET_NAME, "MK_H3_MEDIA", container, {
        serialize: false,
        hideOnZoom: false,
    });
    if (dom) {
        try { delete dom.computeSize; } catch (_) { dom.computeSize = undefined; }
        dom.options = dom.options || {};
        dom.options.serialize = false;
        // 最小高度只留「三个分组标题」的余量：实际高度由 fitPanelHeight 精确贴合内容，
        // 折叠后能一直缩到只剩标题行（给 900 会永远在底部留一截空白）
        dom.options.getMinHeight = () => 220;
        dom.options.getHeight = () => "100%";
        dom.computeLayoutSize = () => ({ minHeight: 220, maxHeight: undefined, minWidth: 640 });
    }
    node.__mkH3M.dom = dom;

    // 最小宽度锁定：3 列正方形格子挤到 640 以下就没法看了
    const lockWidth = () => {
        try {
            const w = Number(node.size?.[0]);
            if (Number.isFinite(w) && w < 640) {
                node.setSize?.([640, Math.max(node.size?.[1] || 780, 220)]);
            }
        } catch (_) {}
    };
    node.min_width = 640;
    node.minWidth = 640;

    const syncWidth = () => {
        try {
            const fullW = Number.isFinite(node.size?.[0]) ? node.size[0] : 0;
            if (dom && fullW && dom.width !== fullW) dom.width = fullW;
        } catch (_) {}
    };

    // 面板不留滚动条：内容多高，节点就多高。
    // 宽度变化时精确贴合（可增可减）；只拖高度时只增不减，避免和用户拖拽打架。
    let fitTimer = null;
    let verifyTimer = null;
    let fitAllowShrink = true;
    let selfResizing = false;
    // overflow:hidden 时 scrollHeight 永远 ≥ clientHeight，量不出「内容比视口矮」→ 累加子元素高度。
    // 子元素用 getBoundingClientRect（会被画布缩放），除以容器自身的缩放系数换算回 CSS px，避免取整误差。
    // 折叠起来的分组（display:none）整段跳过，连它的 gap 也不算，这样折叠后高度能真正收下去。
    const measureContentHeight = () => {
        const kids = container.children;
        if (!kids || !kids.length) return container.scrollHeight;
        const cs = getComputedStyle(container);
        const gap = parseFloat(cs.rowGap) || 0;
        const padTop = parseFloat(cs.paddingTop) || 0;
        const padBottom = parseFloat(cs.paddingBottom) || 0;
        const rectH = container.getBoundingClientRect().height;
        const scale = (rectH > 0 && container.clientHeight > 0)
            ? rectH / container.clientHeight
            : 1;
        const safeScale = (Number.isFinite(scale) && scale > 0.05) ? scale : 1;
        let h = 0;
        let visible = 0;
        for (let i = 0; i < kids.length; i++) {
            if (kids[i].style.display === "none") continue;   // 折叠掉的整组不占高度
            const kh = kids[i].getBoundingClientRect().height;
            h += kh > 0 ? kh / safeScale : kids[i].offsetHeight;
            visible += 1;
        }
        h += gap * Math.max(0, visible - 1);
        return Math.ceil(h + padTop + padBottom);
    };
    const fitPanelHeight = () => {
        fitTimer = null;
        try {
            const need = measureContentHeight();   // 真实内容高度（不依赖 scrollHeight）
            const cur = Number(node.size?.[1]) || 0;
            const clientH = container.clientHeight;
            // DOM 还没布局好（clientHeight=0）时不能量，否则会把节点撑爆
            if (!need || !cur || clientH <= 0) return;
            // 节点高度 ↔ 面板高度是 1:1 的：差多少补多少，不用去猜标题栏高度（猜错会越调越大）
            const delta = need - clientH;
            const shouldResize = fitAllowShrink ? Math.abs(delta) > 2 : delta > 2;
            if (shouldResize) {
                // 自己改的尺寸不要再回头量一次（改完布局还没生效，会越量越大）
                selfResizing = true;
                node.setSize?.([node.size?.[0] || 700, Math.max(220, cur + delta)]);
                setTimeout(() => { selfResizing = false; }, 120);
                // 复核一次：aspect-ratio 取整可能让真实内容比预算多几像素，按实测差值补齐（只补一次，不会循环）
                clearTimeout(verifyTimer);
                verifyTimer = setTimeout(() => {
                    try {
                        const over = container.scrollHeight - container.clientHeight;
                        if (over > 1) {
                            node.setSize?.([node.size?.[0], (Number(node.size?.[1]) || 0) + over]);
                        }
                    } catch (_) {}
                }, 180);
            }
        } catch (_) {}
    };
    const scheduleFit = (allowShrink = false) => {
        fitAllowShrink = allowShrink;
        clearTimeout(fitTimer);
        fitTimer = setTimeout(() => requestAnimationFrame(fitPanelHeight), 30);
    };
    // 折叠 / 展开需要「允许收缩」，否则节点会一直停在展开时的高度，底部留着空白
    node.__mkH3M.fitPanelHeight = (allowShrink = false) => scheduleFit(!!allowShrink);

    let lastWidth = Number(node.size?.[0]) || 0;
    const prevResize = node.onResize;
    node.onResize = function (...args) {
        const r = prevResize?.apply(this, args);
        syncWidth();
        lockWidth();
        if (selfResizing) return r;   // 自己触发的尺寸变化，不重新量
        const w = Number(node.size?.[0]) || 0;
        const widthChanged = Math.abs(w - lastWidth) > 0.5;
        lastWidth = w;
        // 宽度变了 → 格子尺寸变了 → 高度精确贴合；否则只保证不被裁切
        scheduleFit(widthChanged);
        return r;
    };
    // 首次真正被绘制时（标签页切回来 / 后台加载的工作流）再贴合一次：
    // 之前 clientHeight 可能是 0，量不到内容高度
    if (dom) {
        let firstDrawn = false;
        dom.options.onDraw = () => {
            if (firstDrawn || container.clientHeight <= 0) return;
            firstDrawn = true;
            scheduleFit(true);
        };
    }

    // 首次布局：按「音频 / 视频默认折叠」给个接近真实内容的初始高度，随后再精确贴合
    lockWidth();
    syncWidth();
    if (!Number.isFinite(node.size?.[1]) || node.size[1] < 700) {
        try { node.setSize?.([node.size?.[0] || 700, 800]); } catch (_) {}
    }
    renderAllSlots(node);
    lastWidth = Number(node.size?.[0]) || 0;
    requestAnimationFrame(syncWidth);
    setTimeout(() => { syncWidth(); lockWidth(); scheduleFit(false); }, 60);
    setTimeout(() => scheduleFit(true), 320);

    // 执行回传：显示实际载入数量（后端 ui.media_info）
    const prevExecuted = node.onExecuted;
    node.onExecuted = function (message) {
        const r = prevExecuted?.apply(this, arguments);
        try {
            const unp = (v) => (Array.isArray(v) ? v[0] : v);
            const info = unp(message?.media_info);
            if (info && node.__mkH3M?.status) {
                node.__mkH3M.status.textContent = String(info);
                node.__mkH3M.status.title = String(info);
                node.__mkH3M.status.style.color = "var(--mk-h3m-ok)";
            }
            const errs = unp(message?.media_errors);
            if (Array.isArray(errs) && errs.length) {
                notify(errs[0], true);
            }
        } catch (_) {}
        return r;
    };
}

// 工作流载入后 widgets_values 是异步还原的 → 重新读一次并整体重绘
// （只在配置真的变化时才重绘：避免重复渲染把正在加载的 <audio>/<video> 请求打断）
function refreshFromWidget(node) {
    if (!node.__mkH3M) return;
    node.__mkH3M.widget = getSettingsWidget(node) || node.__mkH3M.widget;
    const next = normalizeSettings(readWidgetValue(node.__mkH3M.widget));
    const prevSig = JSON.stringify(node.__mkH3M.settings || {});
    const nextSig = JSON.stringify(next);
    node.__mkH3M.settings = next;
    if (prevSig === nextSig) return;
    renderAllSlots(node);
}

app.registerExtension({
    name: "Comfyui_MKnode.H3MediaLoader",
    async setup() {
        // 注入 --mk-h3m-* 配色变量（深/浅主题各一套），面板本身零外部依赖
        installMkTheme();
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            try {
                setupMediaLoader(this);
            } catch (err) {
                console.error("[MK-素材加载] 初始化失败", err);
            }
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const r = onConfigure?.apply(this, arguments);
            const self = this;
            [0, 120, 400].forEach((ms) => setTimeout(() => {
                try { refreshFromWidget(self); } catch (_) {}
                try { applyFoldedState(self); } catch (_) {}
            }, ms));
            return r;
        };
    },
});
