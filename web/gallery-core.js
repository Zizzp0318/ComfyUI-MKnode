/**
 * MK 图库画廊内核。
 *
 * 一个节点 = 一块面板：上面预览，中间工具栏（分类 / 搜索 / 导入 / 随机），下面是缩略图栅格。
 * 库相关的差异全部由入口文件传进来（节点名、路由前缀、参数名、文案），这里不写死任何一个库。
 *
 * 设计约束（都是踩过坑的，别改）：
 *   1. 原生参数全部隐藏但保留序列化：前端崩了节点照样能跑，API 调用也不受影响。
 *   2. DOM widget 绝不能参与内容高度计算，否则节点只能拉长、缩不回来。
 *   3. 滚轮要在 window 捕获阶段拦，否则画布会先把它当成缩放。
 *   4. 随机模式必须靠 IS_CHANGED 返回 NaN 强制重跑，否则第二次点队列毫无反应。
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const MODE_FIXED = "固定选中";
const MODE_RANDOM_ALL = "全库随机";
const MODE_RANDOM_FILTERED = "范围内随机";
// 下拉里的顺序：最常用的固定选中排第一，全库随机放最后（用它的机会最少）
const MODES = [MODE_FIXED, MODE_RANDOM_FILTERED, MODE_RANDOM_ALL];
const ALL = "全部";
const ALL_INDEX = -1;
const SEED_RANDOM = -1;

const GALLERY_HEIGHT = 580;
const MIN_GALLERY_H = 380;
const NODE_CHROME_H = 38;
const PARAM_ROW_H = 24;

const PREVIEW_MIN = 120;
const PREVIEW_MAX = 460;
const MIN_CELL = 58;

const VERSION = "mk-v3.0";

const CSS = `
.gp-root{
  --gp-bg:var(--comfy-menu-bg,#1e2128);
  --gp-panel:var(--comfy-input-bg,#12141a);
  --gp-fg:var(--input-text,#e6e8ee);
  --gp-dim:var(--descrip-text,#96a0b0);
  --gp-line:var(--border-color,#39404d);
  --gp-ac:#4f8cff;
  box-sizing:border-box;position:absolute;inset:0;pointer-events:auto;display:flex;flex-direction:column;gap:6px;padding:6px;
  background:var(--gp-bg);color:var(--gp-fg);border-radius:6px;overflow:hidden;
  font:12px/1.35 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
}
.gp-root *{box-sizing:border-box}
.gp-stage{position:relative;flex:0 0 auto;display:flex;align-items:center;justify-content:center;
  background:#fff;border:1px solid var(--gp-line);border-radius:8px;overflow:hidden}
.gp-stage-img{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.gp-stage-img img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.gp-stage[data-stale="1"] .gp-stage-img{opacity:.4}
.gp-stage .gp-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:#8b93a1;font-size:12px;text-align:center;padding:10px}
.gp-badge{position:absolute;left:6px;top:6px;z-index:2;max-width:calc(100% - 12px);padding:2px 7px;border-radius:5px;
  background:rgba(14,16,20,.72);color:#fff;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gp-badge[hidden]{display:none}
.gp-stage-ctrl{position:absolute;left:6px;right:6px;bottom:6px;z-index:2;display:flex;align-items:center;gap:6px;
  background:rgba(14,16,20,.5);border-radius:6px;padding:3px 8px;backdrop-filter:blur(2px)}
.gp-stage-ctrl[hidden]{display:none}
.gp-stage-ctrl span{flex:0 0 auto;color:#fff;font-size:11px;opacity:.85;pointer-events:none}
.gp-stage-range{flex:1 1 auto;min-width:0;height:14px;accent-color:var(--gp-ac);cursor:pointer}
.gp-tools{display:flex;gap:4px}
.gp-tools select,.gp-tools input{height:26px;border-radius:6px;border:1px solid var(--gp-line);
  background:var(--gp-panel);color:var(--gp-fg);font-size:12px;padding:0 6px;min-width:0}
.gp-tools select{flex:0 0 96px}
.gp-tools input{flex:1 1 auto}
.gp-tools input::placeholder{color:var(--gp-dim)}
.gp-tools input:focus,.gp-tools select:focus{outline:1px solid var(--gp-ac);outline-offset:-1px}
.gp-tools select:disabled{opacity:.55;cursor:default}
.gp-btn{flex:0 0 auto;height:26px;padding:0 9px;border-radius:6px;border:1px solid var(--gp-line);
  background:var(--gp-panel);color:var(--gp-fg);font-size:12px;cursor:pointer}
.gp-btn:hover{border-color:var(--gp-ac)}
.gp-grid{pointer-events:auto;flex:1 1 0;min-height:0;min-width:0;overflow-y:scroll;overscroll-behavior:contain;
  display:grid;gap:4px;padding:6px;grid-template-columns:repeat(auto-fill,minmax(58px,1fr));
  grid-auto-rows:max-content;align-content:start;
  background:var(--gp-panel);border-radius:8px;border:1px solid var(--gp-line)}
.gp-grid::-webkit-scrollbar{width:8px}
.gp-grid::-webkit-scrollbar-thumb{background:#3c4351;border-radius:4px}
.gp-cell{position:relative;aspect-ratio:3/4;border-radius:5px;overflow:hidden;cursor:pointer;
  background:#fff;border:1px solid transparent}
.gp-cell img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
.gp-cell:hover{border-color:var(--gp-ac)}
.gp-cell[data-on="1"]{border-color:var(--gp-ac);box-shadow:0 0 0 2px rgba(79,140,255,.4)}
/* 删除：平时不占视觉，悬浮才露出 ×；点它就地把格子换成「删除 / 取消」两块，
   不用系统确认框（原生 confirm 会挡住整个画布，还会让浏览器焦点跑掉） */
.gp-del{position:absolute;right:2px;top:2px;z-index:2;width:18px;height:18px;padding:0;
  display:flex;align-items:center;justify-content:center;border:0;border-radius:4px;
  background:rgba(12,14,18,.62);color:#fff;font-size:13px;line-height:1;cursor:pointer;
  opacity:0;transition:opacity .12s}
.gp-cell:hover .gp-del,.gp-cell:focus-within .gp-del{opacity:1}
.gp-del:hover{background:#e5484d}
.gp-cell[data-arm="1"] .gp-del{opacity:0;pointer-events:none}
/* 压暗但别压死：要能认出「删的是不是这张」 */
.gp-cell[data-arm="1"] img{opacity:.55}
.gp-ask{position:absolute;inset:0;z-index:2;display:none;flex-direction:column;justify-content:center;
  gap:4px;padding:5px;background:rgba(10,12,16,.55)}
.gp-cell[data-arm="1"] .gp-ask{display:flex}
.gp-ask button{height:22px;min-width:0;padding:0 2px;border-radius:4px;font-size:11px;line-height:1;
  border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.12);color:#fff;cursor:pointer}
.gp-ask .gp-ask-ok{background:#e5484d;border-color:#e5484d}
.gp-ask .gp-ask-ok:hover{filter:brightness(1.1)}
.gp-ask .gp-ask-no:hover{background:rgba(255,255,255,.24)}
.gp-cell[data-busy="1"] .gp-ask{opacity:.55;pointer-events:none}
.gp-blank{grid-column:1/-1;padding:18px 10px;text-align:center;color:var(--gp-dim);font-size:12px;line-height:1.7}
.gp-blank b{display:block;color:var(--gp-fg);font-weight:600;margin-bottom:2px}
.gp-blank code{font-family:ui-monospace,Consolas,monospace;font-size:11px;word-break:break-all;opacity:.75}
.gp-foot{flex:0 0 auto;display:flex;align-items:center;gap:6px;color:var(--gp-dim);font-size:11px;min-height:20px}
.gp-count{flex:0 0 auto;padding:0;border:0;background:none;color:var(--gp-dim);font:inherit;cursor:pointer}
.gp-count:hover{color:var(--gp-ac)}
.gp-mode{flex:0 0 auto;height:18px;border-radius:4px;border:1px solid var(--gp-line);
  background:var(--gp-panel);color:var(--gp-fg);font-size:11px;padding:0 2px;cursor:pointer}
.gp-mode:focus{outline:1px solid var(--gp-ac);outline-offset:-1px}
.gp-msg{flex:1 1 auto;min-width:0;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gp-ver{flex:0 0 auto;opacity:.35}
.gp-root[data-drop="1"] .gp-grid{outline:2px dashed var(--gp-ac);outline-offset:-4px}
.gp-root[data-busy="1"] .gp-grid,.gp-root[data-busy="1"] .gp-tools{opacity:.5;pointer-events:none}
.gp-root[data-busy="1"] .gp-dlg-box{opacity:.55;pointer-events:none}
.gp-dlg{position:absolute;inset:0;z-index:6;display:flex;align-items:center;justify-content:center;
  padding:8px;background:rgba(8,10,14,.6)}
.gp-dlg[hidden]{display:none}
.gp-dlg-box{box-sizing:border-box;width:100%;max-height:100%;overflow:auto;display:flex;flex-direction:column;
  gap:8px;padding:10px;background:var(--gp-bg);border:1px solid var(--gp-line);border-radius:8px;
  box-shadow:0 10px 28px rgba(0,0,0,.5)}
.gp-dlg-box *{box-sizing:border-box}
.gp-dlg-head{display:flex;align-items:center;justify-content:space-between;font-size:12px;font-weight:600}
.gp-dlg-x{border:0;background:transparent;color:var(--gp-fg);opacity:.55;font-size:15px;line-height:1;
  padding:2px 5px;cursor:pointer;border-radius:4px}
.gp-dlg-x:hover{opacity:1}
.gp-dlg-pick{display:flex;align-items:center;gap:6px}
.gp-dlg-pick button{flex:0 0 auto;height:26px;padding:0 9px;border-radius:6px;border:1px solid var(--gp-line);
  background:var(--gp-panel);color:var(--gp-fg);font-size:12px;cursor:pointer}
.gp-dlg-pick button:hover{border-color:var(--gp-ac)}
.gp-dlg-count{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:11px;opacity:.55}
.gp-dlg-preview{height:130px;display:flex;align-items:center;justify-content:center;overflow:hidden;
  background:#fff;border:1px solid var(--gp-line);border-radius:6px;color:#8b93a1;font-size:12px}
.gp-dlg-preview img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.gp-dlg-row{display:flex;align-items:center;gap:6px;font-size:12px}
.gp-dlg-row > span{flex:0 0 32px;opacity:.7}
.gp-dlg-row input{flex:1 1 auto;min-width:0;height:26px;border-radius:6px;
  border:1px solid var(--gp-line);background:var(--gp-panel);color:var(--gp-fg);font-size:12px;padding:0 6px}
.gp-dlg-row input::placeholder{opacity:.4}
.gp-dlg-row input:focus{outline:1px solid var(--gp-ac);outline-offset:-1px}
/* 分类是「可选可填」的：原生 datalist 在画布容器里弹不出来，还会因多节点同 id 串台，
   所以列表自己画，输入框照旧自由输入 */
.gp-cat{position:relative;flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:4px}
.gp-cat-line{display:flex;gap:4px;align-items:center}
.gp-cat-line input{flex:1 1 auto;min-width:0;height:26px;border-radius:6px;border:1px solid var(--gp-line);
  background:var(--gp-panel);color:var(--gp-fg);font-size:12px;padding:0 6px}
.gp-cat-line input:focus{outline:1px solid var(--gp-ac);outline-offset:-1px}
.gp-cat-toggle{flex:0 0 auto;width:26px;height:26px;padding:0;border-radius:6px;border:1px solid var(--gp-line);
  background:var(--gp-panel);color:var(--gp-fg);font-size:12px;line-height:1;cursor:pointer}
.gp-cat-toggle:hover{border-color:var(--gp-ac)}
.gp-cat-menu{position:absolute;left:0;right:0;top:calc(100% + 4px);z-index:6;
  max-height:132px;overflow:auto;display:flex;flex-direction:column;gap:1px;
  padding:3px;border:1px solid var(--gp-line);border-radius:6px;background:var(--gp-panel);
  box-shadow:0 6px 18px rgba(0,0,0,.35)}
/* 下方放不下时翻到输入框上面：分类这行靠底，往下展开会盖住「导入 / 取消」 */
.gp-cat-menu[data-up="1"]{top:auto;bottom:calc(100% + 4px)}
.gp-cat-menu[hidden]{display:none}
.gp-cat-item{display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:3px 6px;border-radius:4px;font-size:12px;cursor:pointer}
.gp-cat-item:hover{background:rgba(79,140,255,.18)}
.gp-cat-item[data-new="1"]{color:var(--gp-ac)}
.gp-cat-item em{font-style:normal;color:var(--gp-dim);font-size:11px}
.gp-cat-empty{padding:3px 6px;font-size:11px;opacity:.5}
.gp-dlg-hint{min-height:15px;font-size:11px;line-height:1.35;opacity:.55}
.gp-dlg-foot{display:flex;justify-content:flex-end;gap:6px}
.gp-dlg-foot button{height:26px;padding:0 14px;border-radius:6px;border:1px solid var(--gp-line);
  background:var(--gp-panel);color:var(--gp-fg);font-size:12px;cursor:pointer}
.gp-dlg-foot button:hover{border-color:var(--gp-ac)}
.gp-dlg-foot .gp-dlg-ok{background:var(--gp-ac);border-color:var(--gp-ac);color:#fff}
.gp-dlg-foot .gp-dlg-ok:hover{filter:brightness(1.08)}
.gp-dlg-foot button:disabled{opacity:.5;cursor:default}
`;

function injectCSS() {
	if (document.getElementById("mk-gallery-style")) return;
	const el = document.createElement("style");
	el.id = "mk-gallery-style";
	el.textContent = CSS;
	document.head.append(el);
}

/** 每个库的数据目录只问一次，多个节点共用。 */
const pathCache = new Map();
function libraryPaths(route) {
	if (!pathCache.has(route)) {
		const p = api
			.fetchApi(`/${route}/paths`)
			.then((res) => (res.ok ? res.json() : null))
			.catch(() => null);
		pathCache.set(route, p);
	}
	return pathCache.get(route);
}

/**
 * 注册一个图库节点。
 * @param {object} opts
 * @param {string} opts.extension      扩展名，如 ComfyUI.MKGallery.Pose
 * @param {string} opts.nodeName       节点 ID，如 MKPosePicker
 * @param {string} opts.route          HTTP 前缀，如 mkposes
 * @param {string} opts.widgetName     选图参数名，如 姿态
 * @param {string} opts.itemLabel      文案里的名词，如 姿态
 * @param {string} opts.unit           计数单位，如 个
 * @param {string} opts.domWidgetName  画布控件名，如 mk_pose_gallery
 */
export function defineGallery(opts) {
	const { extension, nodeName, route, widgetName, itemLabel, unit, domWidgetName } = opts;

	app.registerExtension({
		name: extension,
		beforeRegisterNodeDef(nodeType, nodeData) {
			if (nodeData.name !== nodeName) return;
			// 同一原型只包一次；标记放原型上，实例属性用来区分具体节点
			if (nodeType.prototype.__mkPatched) return;
			nodeType.prototype.__mkPatched = true;

			const onResize = nodeType.prototype.onResize;
			nodeType.prototype.onResize = function () {
				const r = onResize?.apply(this, arguments);
				const sync = () => this.__mkSyncHeight?.();
				if (typeof requestAnimationFrame === "function") requestAnimationFrame(sync);
				else sync();
				return r;
			};

			const onNodeCreated = nodeType.prototype.onNodeCreated;
			nodeType.prototype.onNodeCreated = function () {
				const r = onNodeCreated?.apply(this, arguments);
				// 画廊装不上也不能影响节点本身可用：只告警，保留控件与输出
				try {
					setup(this);
				} catch (err) {
					console.error(`[MK-${itemLabel}库] 画廊初始化失败，节点参数仍可用：`, err);
				}
				return r;
			};

			const onConfigure = nodeType.prototype.onConfigure;
			nodeType.prototype.onConfigure = function () {
				const r = onConfigure?.apply(this, arguments);
				try {
					trimOutputs(this);
					this.__mkClampHeight?.();
					this.__mkResync?.();
				} catch (err) {
					console.warn(`[MK-${itemLabel}库] 恢复工作流后同步失败：`, err);
				}
				return r;
			};

			const onExecuted = nodeType.prototype.onExecuted;
			nodeType.prototype.onExecuted = function (message) {
				onExecuted?.apply(this, arguments);
				const picked = message?.picked?.[0];
				if (picked) this.__mkApply?.(picked);
			};
		},
	});

	function setup(node) {
		injectCSS();

		const w = (name) => node.widgets?.find((x) => x.name === name);
		const modeWidget = w("模式");
		const itemWidget = w(widgetName);
		const catWidget = w("分类");
		const seedWidget = w("种子");
		if (!modeWidget || !itemWidget || !catWidget) return;

		// 画廊不能参与父容器的内容高度计算：外面套一层 wrap 占位，画廊在 wrap 内绝对定位铺满
		const wrap = document.createElement("div");
		wrap.style.cssText = "position:relative;width:100%;height:100%;overflow:hidden";

		const root = document.createElement("div");
		root.className = "gp-root";
		root.innerHTML = `
			<div class="gp-stage">
				<div class="gp-stage-img"><span class="gp-empty">载入${itemLabel}库…</span></div>
				<div class="gp-badge" hidden></div>
				<div class="gp-stage-ctrl" hidden>
					<span>预览</span>
					<input class="gp-stage-range" type="range" min="15" max="85" step="1" value="55"
						title="拖动调整预览图占节点高度的比例；拉高节点预览会跟着变大">
				</div>
			</div>
			<div class="gp-tools">
				<select class="gp-cat-sel" title="按分类筛选"></select>
				<input class="gp-search" type="text" placeholder="搜索名称 / 分类">
				<button class="gp-btn gp-imp" type="button"
					title="导入${itemLabel}图（点这里选图，或按 Ctrl+V 粘贴、把图片拖进面板）">导入</button>
				<button class="gp-btn gp-shuffle" type="button" title="从当前筛选里随机挑一张">随机</button>
			</div>
			<div class="gp-grid"></div>
			<div class="gp-foot">
				<button class="gp-count" type="button" title="刷新（改了 img 目录后点这里）"></button>
				<select class="gp-mode" title="取图方式">
					${MODES.map((m) => `<option value="${m}">${m}</option>`).join("")}
				</select>
				<span class="gp-msg"></span>
				<span class="gp-ver" title="插件版本标记，用于确认前端脚本已更新">${VERSION}</span>
			</div>
			<div class="gp-dlg" hidden>
				<div class="gp-dlg-box">
					<div class="gp-dlg-head">导入${itemLabel}图<button class="gp-dlg-x" type="button" title="关闭">×</button></div>
					<div class="gp-dlg-pick">
						<button class="gp-dlg-file" type="button">选择文件…</button>
						<button class="gp-dlg-clip" type="button" title="读系统剪贴板里的图片">从剪贴板</button>
						<span class="gp-dlg-count"></span>
					</div>
					<div class="gp-dlg-preview"></div>
					<label class="gp-dlg-row"><span>名称</span>
						<input class="gp-dlg-name" type="text" maxlength="60"></label>
					<div class="gp-dlg-row"><span>分类</span>
						<div class="gp-cat">
							<div class="gp-cat-line">
								<input class="gp-dlg-cat" type="text" maxlength="60" autocomplete="off"
									placeholder="选一个，或直接输入新分类">
								<button class="gp-cat-toggle" type="button" title="选择已有分类">▾</button>
							</div>
							<div class="gp-cat-menu" hidden></div>
						</div></div>
					<div class="gp-dlg-hint"></div>
					<div class="gp-dlg-foot">
						<button class="gp-dlg-cancel" type="button">取消</button>
						<button class="gp-dlg-ok" type="button">导入</button>
					</div>
				</div>
			</div>`;

		const stage = root.querySelector(".gp-stage");
		const stageImg = root.querySelector(".gp-stage-img");
		const badge = root.querySelector(".gp-badge");
		const stageCtrl = root.querySelector(".gp-stage-ctrl");
		const stageRange = root.querySelector(".gp-stage-range");
		const catSel = root.querySelector(".gp-cat-sel");
		const searchInput = root.querySelector(".gp-search");
		const grid = root.querySelector(".gp-grid");
		const countBtn = root.querySelector(".gp-count");
		const modeSel = root.querySelector(".gp-mode");
		const msgEl = root.querySelector(".gp-msg");

		// 选图对话框不上屏，点「选择文件…」再叫出来
		const fileInput = document.createElement("input");
		fileInput.type = "file";
		fileInput.accept = "image/*";
		fileInput.multiple = true;
		fileInput.style.display = "none";
		root.append(fileInput);

		const importBtn = root.querySelector(".gp-imp");
		const shuffleBtn = root.querySelector(".gp-shuffle");
		const dlg = root.querySelector(".gp-dlg");
		const dlgBody = dlg.querySelector(".gp-dlg-box");
		const dlgName = dlg.querySelector(".gp-dlg-name");
		const dlgCat = dlg.querySelector(".gp-dlg-cat");
		const catMenu = dlg.querySelector(".gp-cat-menu");
		const catToggle = dlg.querySelector(".gp-cat-toggle");
		const dlgPreview = dlg.querySelector(".gp-dlg-preview");
		const dlgCount = dlg.querySelector(".gp-dlg-count");
		const dlgHint = dlg.querySelector(".gp-dlg-hint");
		const dlgOk = dlg.querySelector(".gp-dlg-ok");

		wrap.appendChild(root);

		const gallery = node.addDOMWidget(domWidgetName, domWidgetName, wrap, {
			serialize: false,
			hideOnZoom: false,
			getMinHeight: () => MIN_GALLERY_H,
		});

		/** 除画廊外还占掉多少高度：标题栏 + 内边距 + 当前可见的参数行。 */
		function chromeHeight() {
			let rows = 0;
			for (const widget of node.widgets ?? []) {
				if (widget === gallery || widget.hidden) continue;
				rows += 1;
			}
			return NODE_CHROME_H + rows * PARAM_ROW_H;
		}

		let curGalleryH = GALLERY_HEIGHT;
		let previewH = 260;
		let previewManual = false;

		function applyStageHeight() {
			stage.style.height = `${previewH}px`;
			const pct = Math.round(((previewH - PREVIEW_MIN) / (PREVIEW_MAX - PREVIEW_MIN)) * 100);
			stageRange.value = String(pct);
			stageRange.title = `预览 ${previewH}px — 拖动调整预览图占节点高度的比例`;
		}

		stageRange.oninput = () => {
			previewManual = true;
			previewH = Math.round(
				PREVIEW_MIN + (Number(stageRange.value) / 100) * (PREVIEW_MAX - PREVIEW_MIN),
			);
			applyStageHeight();
		};
		applyStageHeight();

		// 新版前端把 wheel 冒泡到画布层就当缩放并在那里 preventDefault，
		// 所以要在 window 捕获阶段先拦。但必须分清"这一下该滚谁"：
		//   · 指针下有自己的滚动容器（分类列表 / 对话框 / 栅格）→ 滚它
		//   · 对话框开着但没有可滚容器 → 吞掉，别让背后的画布缩放
		//   · 其余情况才轮到缩略图栅格
		function scrollableUnder(target) {
			let el = target instanceof Element ? target : null;
			while (el && root.contains(el)) {
				if (el.scrollHeight > el.clientHeight + 1) {
					const overflowY = getComputedStyle(el).overflowY;
					if (overflowY === "auto" || overflowY === "scroll") return el;
				}
				el = el.parentElement;
			}
			return null;
		}

		function onWheel(e) {
			if (!node.graph) return; // 节点已从画布移除
			const target = e.target;
			if (!(target instanceof Node) || !root.contains(target)) return;

			const step =
				e.deltaMode === 1
					? e.deltaY * 16
					: e.deltaMode === 2
						? e.deltaY * grid.clientHeight
						: e.deltaY;
			const scroller = scrollableUnder(target);
			const inDialog = target instanceof Element && dlg.contains(target);

			if (scroller || inDialog) {
				e.preventDefault();
				e.stopPropagation();
				e.stopImmediatePropagation?.();
				if (scroller) scroller.scrollTop += step;
				return;
			}
			if (grid.scrollHeight <= grid.clientHeight + 1) return; // 没得滚，让画布缩放
			e.preventDefault();
			e.stopPropagation();
			e.stopImmediatePropagation?.();
			grid.scrollTop += step;
		}
		window.addEventListener("wheel", onWheel, { capture: true, passive: false });

		const st = {
			db: null,
			query: "",
			sel: null,
			stale: false,
			notice: "",
			lastCat: "",
			cells: new Map(),
			scrollTo: null,
			dir: "",
		};

		// 索引请求的共享 Promise：同一个节点同时只发一次 /index.json
		let dbPromise = null;

		// 正在等「删除 / 取消」的那一格，全局同时只允许一个
		let armedCell = null;

		// ---------- 与节点原生控件同步 ----------
		let syncing = false;
		// 我们自己写 widget 时不要反过来再触发一轮「从 widget 同步界面」：
		// 那会把栅格整个重建一遍，点到下面某张图时滚动位置会被弹回顶部。
		let writing = false;

		function setWidget(widget, value) {
			if (!widget || widget.value === value) return;
			writing = true;
			try {
				widget.value = value;
				widget.callback?.(value);
			} finally {
				writing = false;
			}
			node.graph?.setDirtyCanvas(true, true);
		}

		const isRandom = () => modeWidget.value !== MODE_FIXED;

		function currentCategory() {
			const value = catWidget.value;
			return value && value !== ALL ? value : ALL;
		}

		/** 与后端 library.pool() 同一套口径，用来显示候选数。 */
		function scopedPool() {
			if (!st.db) return [];
			if (modeWidget.value === MODE_RANDOM_ALL) return st.db.items;
			const cat = currentCategory();
			if (cat === ALL) return st.db.items;
			const matched = st.db.items.filter((item) => item.cat === cat);
			return matched.length ? matched : st.db.items;
		}

		/** 按当前分类 + 搜索词，栅格里实际显示哪些。 */
		function visibleItems() {
			if (!st.db) return [];
			const cat = currentCategory();
			let list = cat === ALL ? st.db.items : st.db.items.filter((item) => item.cat === cat);
			const q = st.query;
			if (q) {
				list = list.filter(
					(item) =>
						item.name.toLowerCase().includes(q) ||
						item.cat.toLowerCase().includes(q) ||
						item.label.toLowerCase().includes(q),
				);
			}
			return list;
		}

		// ---------- 参数显隐：不生效不展示 ----------
		const hiddenOrig = new Map();
		function showWidget(widget, on) {
			if (!widget) return;
			if (on) {
				if (!hiddenOrig.has(widget)) return;
				const orig = hiddenOrig.get(widget);
				if (orig) widget.computeSize = orig;
				else delete widget.computeSize;
				widget.hidden = false;
				hiddenOrig.delete(widget);
				return;
			}
			if (hiddenOrig.has(widget)) return;
			hiddenOrig.set(widget, widget.computeSize);
			// 高度归零是 litegraph 里隐藏 widget 的通行做法，节点也会跟着缩
			widget.computeSize = () => [0, -4];
			widget.hidden = true;
		}

		function applyVisibility() {
			// 界面上只留画廊：模式 → 页脚那个小下拉；分类 → 工具栏下拉；种子 → 页脚
			// 只是隐藏（hidden + 高度归零），widget 的值仍会正常序列化给 Python。
			for (const widget of [modeWidget, itemWidget, catWidget, seedWidget]) {
				showWidget(widget, false);
			}
			modeSel.value = modeWidget.value;
			node.graph?.setDirtyCanvas(true, true);
		}

		/**
		 * 把参数值修正成后端认识的样子。
		 *
		 * 主要是防旧工作流：老版本有「视角 / 筛选系列 / 筛选分类」六个参数，
		 * 按位置恢复时会把「视角」的值塞进「分类」、把「筛选系列」的名字塞进「种子」，
		 * ComfyUI 提交前校验 INT 会直接报 "not a valid INT"。这里在恢复后立刻纠正，
		 * 用户只会看到「选的图不在了」这种中文提示，而不是看不懂的英文报错。
		 */
		function sanitizeWidgets() {
			if (!MODES.includes(modeWidget.value)) setWidget(modeWidget, MODE_FIXED);
			for (const widget of [itemWidget, catWidget]) {
				if (typeof widget.value !== "string") {
					setWidget(widget, widget.value == null ? "" : String(widget.value));
				}
			}
			const seed = Number(seedWidget?.value);
			if (!Number.isFinite(seed) || typeof seedWidget.value !== "number") {
				setWidget(seedWidget, Number.isFinite(seed) ? Math.trunc(seed) : SEED_RANDOM);
			}
			// 分类还没拉到就先不动，renderCatSel 会在有数据后再兜一次
			if (
				st.db?.categories?.length &&
				catWidget.value !== ALL &&
				!existingCats().includes(catWidget.value)
			) {
				setWidget(catWidget, ALL);
			}
		}

		// 种子没有界面入口：`种子` 参数默认 -1，随机模式每次都重抽一遍。
		// 只有通过 API 显式传值时才走确定性抽取，工作流里看不到这个开关是故意的。

		// ---------- 渲染 ----------
		function thumbURL(file) {
			return api.apiURL(`/${route}/thumb?name=${encodeURIComponent(file)}`);
		}
		function imgURL(file) {
			return api.apiURL(`/${route}/img?name=${encodeURIComponent(file)}`);
		}

		function renderStage() {
			const item = st.sel;
			if (!item) {
				stageImg.innerHTML = `<span class="gp-empty">${
					st.db && st.db.total ? "在下面点一张图" : `还没有${itemLabel}图`
				}</span>`;
				badge.hidden = true;
				stageCtrl.hidden = true;
				stage.dataset.stale = "0";
				return;
			}
			stageImg.innerHTML = `<img src="${imgURL(item.file)}" draggable="false" alt="">`;
			badge.hidden = false;
			stageCtrl.hidden = false;
			badge.textContent = `${st.stale ? "上次 · " : ""}${item.cat} · ${item.name}`;
			stage.dataset.stale = st.stale ? "1" : "0";
		}

		function select(item, write) {
			st.sel = item;
			if (write) setWidget(itemWidget, item.label);
			renderStage();
			markSelection();
			renderFoot();
		}

		function markSelection() {
			for (const [item, cell] of st.cells) {
				cell.dataset.on = item === st.sel ? "1" : "0";
			}
		}

		function renderCatSel() {
			let cat = currentCategory();
			let found =
				cat === ALL ? ALL_INDEX : st.db.categories.findIndex((entry) => entry.name === cat);
			if (cat !== ALL && found < 0) {
				// 分类被删空了 / 数据文件被改过：落回「全部」，别让用户对着一个不存在的筛选发呆
				cat = ALL;
				found = ALL_INDEX;
				setWidget(catWidget, ALL);
			}
			catSel.replaceChildren();
			const add = (value, text) => {
				const opt = document.createElement("option");
				opt.value = String(value);
				opt.textContent = text;
				catSel.append(opt);
			};
			add(ALL_INDEX, `${ALL} ${st.db.items.length}`);
			st.db.categories.forEach((entry, index) => {
				add(index, `${entry.name} ${entry.count}`);
			});
			catSel.value = String(found);
			// 全库随机不看分类，下拉锁住，免得用户以为筛选生效了
			const lock = modeWidget.value === MODE_RANDOM_ALL;
			catSel.disabled = lock;
			catSel.title = lock ? "全库随机时忽略分类筛选" : "按分类筛选";
		}

		let gridCols = 0;
		function layoutGridCols(count) {
			const inner = grid.clientWidth - 12;
			if (inner <= 0 || count <= 0) return;
			const maxCols = Math.max(1, Math.floor((inner + 4) / (MIN_CELL + 4)));
			let cols = 0;
			// 只在「末行会剩一个」时改排列（7 张 / 上限 6 列 → 4+3），
			// 其余保持 CSS auto-fill，筛选变化时缩略图尺寸不会跳
			if (count > maxCols && count % maxCols === 1) {
				cols = Math.ceil(count / Math.ceil(count / maxCols));
			}
			if (cols === gridCols) return;
			gridCols = cols;
			grid.style.gridTemplateColumns = cols ? `repeat(${cols}, minmax(0, 1fr))` : "";
		}

		let gridRaf = 0;
		if (typeof ResizeObserver !== "undefined") {
			new ResizeObserver(() => {
				cancelAnimationFrame(gridRaf);
				gridRaf = requestAnimationFrame(() => {
					gridCols = -1;
					layoutGridCols(st.cells.size);
				});
			}).observe(grid);
		}

		function renderBlank() {
			const blank = document.createElement("div");
			blank.className = "gp-blank";
			const total = st.db?.total ?? 0;
			if (!total) {
				blank.innerHTML = `<b>这里还没有${itemLabel}图</b>
					点上面的「导入」，或把图片拖进面板 / 按 Ctrl+V 粘贴<br>
					<code>${st.dir || "ComfyUI/user/Comfyui_MKnode/mk_gallery"}</code>`;
			} else if (st.query) {
				blank.innerHTML = `<b>没有匹配「${st.query}」的${itemLabel}</b>换个词，或者把搜索框清空`;
			} else {
				blank.innerHTML = `<b>这个分类还是空的</b>可以在导入时选择别的分类，或直接把图拖进来`;
			}
			return blank;
		}

		function renderGrid() {
			const list = visibleItems();
			const frag = document.createDocumentFragment();
			st.cells.clear();
			for (const item of list) {
				const cell = document.createElement("div");
				cell.className = "gp-cell";
				cell.title = `${item.name}\n分类：${item.cat}\n右键可删除`;
				const img = document.createElement("img");
				img.loading = "lazy";
				img.decoding = "async";
				img.draggable = false;
				img.src = thumbURL(item.file);

				const del = document.createElement("button");
				del.type = "button";
				del.className = "gp-del";
				del.title = "删除这张图";
				del.setAttribute("aria-label", "删除");
				del.textContent = "×";
				del.onclick = (e) => {
					e.stopPropagation();
					armDelete(cell);
				};

				// 格子就那么宽，横排两个按钮会挤成小方块认不出来，所以竖着排
				const ask = document.createElement("div");
				ask.className = "gp-ask";
				const ok = document.createElement("button");
				ok.type = "button";
				ok.className = "gp-ask-ok";
				ok.textContent = "删除";
				ok.onclick = (e) => {
					e.stopPropagation();
					ok.textContent = "…";
					deleteItem(item, cell);
				};
				const no = document.createElement("button");
				no.type = "button";
				no.className = "gp-ask-no";
				no.textContent = "取消";
				no.onclick = (e) => {
					e.stopPropagation();
					disarm(cell);
				};
				ask.append(ok, no);

				cell.append(img, del, ask);
				// 待确认时点格子 = 反悔（此时缩略图被压暗，点到的其实是确认层）
				cell.onclick = () => {
					if (cell.dataset.arm === "1") {
						disarm(cell);
						return;
					}
					pickCell(item);
				};
				// 右键也走同一套确认，不再用系统弹窗
				cell.oncontextmenu = (e) => {
					e.preventDefault();
					e.stopPropagation();
					armDelete(cell);
				};
				st.cells.set(item, cell);
				frag.append(cell);
			}
			if (!list.length) frag.append(renderBlank());
			grid.replaceChildren(frag);
			layoutGridCols(list.length);
			markSelection();
			renderFoot();

			// 随机模式下预览的可能是上一次的结果，不在当前筛选范围里就压暗提示
			const stale = isRandom() && st.sel ? !scopedPool().includes(st.sel) : false;
			if (stale !== st.stale) {
				st.stale = stale;
				renderStage();
			}

			// 导入后 / 刷新后跳到目标那一格
			if (st.scrollTo) {
				const cell = [...st.cells].find(([item]) => item.id === st.scrollTo)?.[1];
				st.scrollTo = null;
				if (cell) cell.scrollIntoView({ block: "nearest", inline: "nearest" });
			}
		}

		function renderFoot() {
			const total = st.db?.total ?? 0;
			const shown = st.cells.size;
			const filtered = st.query || currentCategory() !== ALL;
			countBtn.textContent = filtered ? `${shown} / ${total} ${unit}` : `${total} ${unit}`;
			countBtn.title = st.notice || "点一下刷新（改了 img 目录后用这个）";
			const hint = isRandom() ? (modeWidget.value === MODE_RANDOM_ALL ? "全库抽" : "按分类抽") : "";
			msgEl.textContent = st.notice || hint;
		}

		/** 点缩略图 = 就要这一张。随机模式下顺带切回固定选中。 */
		function pickCell(item) {
			const wasRandom = isRandom();
			if (wasRandom) setWidget(modeWidget, MODE_FIXED);
			st.stale = false;
			// 不重建栅格：点深处那张图时滚动位置要留在原地
			select(item, true);
			if (wasRandom) {
				renderCatSel();
				applyVisibility();
			}
		}

		// ---------- 删除确认 ----------

		/**
		 * 进入「待确认」：格子就地换成「删除 / 取消」，同时只允许一格。
		 *
		 * 不用 window.confirm 的两个原因：原生弹窗会挡住整个画布、各浏览器的样式还各不相同；
		 * 更要紧的是它没法告诉你「删的是哪张」——图被压暗、按钮就在图上，误删的概率低得多。
		 */
		function armDelete(cell) {
			if (!cell || cell.dataset.busy === "1") return;
			if (armedCell && armedCell !== cell) disarm(armedCell);
			armedCell = cell;
			cell.dataset.arm = "1";
		}

		function disarm(cell) {
			if (!cell) return;
			cell.dataset.arm = "0";
			if (armedCell === cell) armedCell = null;
		}

		// 点别处 / 按 Esc = 反悔。捕获阶段拦，免得先被格子的选中逻辑吃掉
		function onArmPointerDown(e) {
			if (armedCell && !armedCell.contains(e.target)) disarm(armedCell);
		}
		function onArmKeyDown(e) {
			if (e.key !== "Escape" || !armedCell) return;
			e.preventDefault();
			e.stopPropagation();
			disarm(armedCell);
		}
		root.addEventListener("pointerdown", onArmPointerDown, true);
		document.addEventListener("keydown", onArmKeyDown);

		// ---------- 提示 / 忙 ----------
		let noticeTimer = null;
		function setNotice(text, ms = 5000) {
			st.notice = text || "";
			renderFoot();
			clearTimeout(noticeTimer);
			if (text) noticeTimer = setTimeout(() => setNotice(""), ms);
		}

		function setBusy(on) {
			root.dataset.busy = on ? "1" : "0";
		}

		// ---------- 导入 ----------
		const IMAGE_NAME = /\.(png|jpe?g|webp|bmp)$/i;
		const isImageFile = (file) =>
			!!file && ((file.type || "").startsWith("image/") || IMAGE_NAME.test(file.name || ""));
		const stemOf = (name) => String(name || "").replace(/\.[^.\\/]+$/, "").trim();

		let pending = [];
		let previewURL = "";

		function releasePreview() {
			if (previewURL) URL.revokeObjectURL(previewURL);
			previewURL = "";
			dlgPreview.replaceChildren();
		}

		function showPreview(file) {
			releasePreview();
			if (!file) {
				dlgPreview.textContent = "没有预览";
				return;
			}
			previewURL = URL.createObjectURL(file);
			const img = document.createElement("img");
			img.src = previewURL;
			img.alt = "";
			img.draggable = false;
			dlgPreview.append(img);
		}

		// ---------- 分类：可选已有，也可直接输入新建 ----------
		function existingCats() {
			return (st.db?.categories ?? []).map((entry) => entry.name);
		}

		function catCount(name) {
			return st.db?.categories?.find((entry) => entry.name === name)?.count ?? 0;
		}

		function closeCatMenu() {
			catMenu.hidden = true;
		}

		function renderCatMenu() {
			const query = dlgCat.value.trim();
			const low = query.toLowerCase();
			const all = existingCats();
			const shown = low ? all.filter((cat) => cat.toLowerCase().includes(low)) : all;

			catMenu.replaceChildren();
			// 输入的不是已有分类 → 顶部给一条「新建」，让用户确信能自己造
			if (query && !all.includes(query)) {
				const item = document.createElement("div");
				item.className = "gp-cat-item";
				item.dataset.new = "1";
				item.textContent = `新建分类「${query}」`;
				item.onclick = () => {
					dlgCat.value = query;
					closeCatMenu();
					updateHint();
					focusCatInput();
				};
				catMenu.append(item);
			}
			for (const cat of shown) {
				const item = document.createElement("div");
				item.className = "gp-cat-item";
				item.textContent = cat;
				const num = document.createElement("em");
				num.textContent = String(catCount(cat));
				item.append(num);
				item.onclick = () => {
					dlgCat.value = cat;
					closeCatMenu();
					updateHint();
					focusCatInput();
				};
				catMenu.append(item);
			}
			if (!catMenu.childElementCount) {
				const empty = document.createElement("div");
				empty.className = "gp-cat-empty";
				empty.textContent = all.length ? "没有匹配的分类，直接输入即新建" : "还没有分类，直接输入即新建";
				catMenu.append(empty);
			}
			catMenu.hidden = false;
			placeCatMenu();
		}

		/**
		 * 菜单是绝对定位的（不参与布局，展开不会把对话框顶高），所以要自己算方向：
		 * 下方放不下、会盖住「导入 / 取消」时就翻到输入框上方。
		 */
		function placeCatMenu() {
			catMenu.dataset.up = "0";
			const box = dlgBody.getBoundingClientRect();
			const menu = catMenu.getBoundingClientRect();
			if (menu.bottom <= box.bottom - 40) return;
			const anchor = catMenu.parentElement.getBoundingClientRect();
			if (anchor.top - menu.height > box.top) catMenu.dataset.up = "1";
		}

		// 选完把光标放回输入框，但不能让刚关掉的菜单又弹起来：
		// focus() 是同步派发事件的，用一个一次性开关拦住它自己触发的那次。
		let suppressFocusOpen = false;
		function focusCatInput() {
			suppressFocusOpen = true;
			dlgCat.focus();
			suppressFocusOpen = false;
		}

		function updateHint() {
			const total = pending.length;
			if (!total) {
				dlgHint.textContent = "";
				dlgOk.disabled = true;
				return;
			}
			dlgOk.disabled = false;
			const name = dlgName.value.trim();
			const cat = dlgCat.value.trim();
			const parts = [];
			if (!name) {
				parts.push(total > 1 ? `${total} 张各用自己的文件名当名字` : "留空就用文件名当名字");
			} else if (total > 1) {
				parts.push(`${total} 张依次命名「${name} 1」「${name} 2」…`);
			} else {
				parts.push(`名称「${name}」`);
			}
			if (cat && !existingCats().includes(cat)) parts.push(`新分类「${cat}」`);
			dlgHint.textContent = parts.join(" · ");
		}

		function openImport(files) {
			const list = Array.from(files || []).filter(isImageFile);
			if (!list.length) {
				setNotice("没识别到图片，支持 png / jpg / webp / bmp");
				return;
			}
			// 对话框已经开着（点了「选择文件…」换一批）：保留用户填过的名称与分类
			const reopen = !dlg.hidden;
			pending = list;
			if (!reopen) {
				dlgName.value = list.length === 1 ? stemOf(list[0].name) : "";
				// 分类默认沿用上一次导入用的，或者当前正筛着的那个。
				// 上一次用的那个可能已经因为图删光了而消失，得先确认它还在。
				const last = st.lastCat && existingCats().includes(st.lastCat) ? st.lastCat : "";
				const cat = currentCategory();
				dlgCat.value = last || (cat === ALL ? "" : cat);
				closeCatMenu();
			}
			dlgCount.textContent = list.length > 1 ? `已选 ${list.length} 张` : list[0].name || "已选 1 张";
			showPreview(list[0]);
			dlg.hidden = false;
			updateHint();
			dlgName.focus();
			dlgName.select();
		}

		function closeImport() {
			dlg.hidden = true;
			closeCatMenu();
			pending = [];
			releasePreview();
			fileInput.value = "";
		}

		function confirmImport() {
			const list = pending.slice();
			if (!list.length) {
				closeImport();
				return;
			}
			const meta = { name: dlgName.value.trim(), cat: dlgCat.value.trim() };
			st.lastCat = meta.cat;
			closeImport();
			return uploadFiles(list, meta);
		}

		async function uploadFiles(files, meta = {}) {
			const list = Array.from(files || []).filter(isImageFile);
			if (!list.length) {
				setNotice("没识别到图片，支持 png / jpg / webp / bmp");
				return;
			}
			setBusy(true);
			setNotice(`导入中 ${list.length} 张…`, 60000);
			const form = new FormData();
			form.append("meta", JSON.stringify(meta));
			for (const file of list) form.append("images", file, file.name);
			try {
				const res = await api.fetchApi(`/${route}/upload`, { method: "POST", body: form });
				const out = await res.json().catch(() => ({}));
				if (!res.ok) throw new Error(out?.error || `HTTP ${res.status}`);
				const saved = out.ids || [];
				const failed = out.failed || [];
				if (!saved.length) throw new Error(failed[0]?.error || "服务端没有存下任何图片");

				// 清掉搜索词、把分类切到刚导入的那个，免得新图被上一次的筛选挡住
				searchInput.value = "";
				st.query = "";
				if (meta.cat) setWidget(catWidget, meta.cat);
				const db = await refresh(saved[0]);
				const fresh = db?.items.find((item) => item.id === saved[0]);
				if (fresh) select(fresh, true);

				setNotice(
					failed.length
						? `导入 ${saved.length} 张，${failed.length} 张失败（${failed[0].error}）`
						: `已导入 ${saved.length} 张`,
				);
			} catch (err) {
				setNotice(`导入失败：${err.message}`);
				console.error(`[MK-${itemLabel}库] 导入失败：`, err);
			} finally {
				setBusy(false);
				fileInput.value = "";
			}
		}

		/** 剪贴板里的图没有文件名，按「剪贴板 月日-时分」起一个。 */
		function clipboardFile(blob, type) {
			const now = new Date();
			const pad = (n) => String(n).padStart(2, "0");
			const ext = (type.split("/")[1] || "png").replace("jpeg", "jpg");
			const stamp = `${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
			return new File([blob], `剪贴板 ${stamp}.${ext}`, { type });
		}

		async function pasteFromClipboard() {
			if (!navigator.clipboard?.read) {
				setNotice("这个浏览器不支持读剪贴板，直接按 Ctrl+V 粘贴");
				return;
			}
			try {
				const items = await navigator.clipboard.read();
				const files = [];
				for (const item of items) {
					const type = item.types.find((t) => t.startsWith("image/"));
					if (!type) continue;
					files.push(clipboardFile(await item.getType(type), type));
				}
				if (!files.length) {
					setNotice("剪贴板里没有图片");
					return;
				}
				openImport(files);
			} catch (err) {
				setNotice("读不到剪贴板，直接按 Ctrl+V 粘贴");
				console.warn(`[MK-${itemLabel}库] 剪贴板读取失败：`, err);
			}
		}

		async function deleteItem(item, cell) {
			if (!cell || cell.dataset.busy === "1") return;
			cell.dataset.busy = "1";
			try {
				const res = await api.fetchApi(`/${route}/delete`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ files: [item.file] }),
				});
				const out = await res.json().catch(() => ({}));
				if (!res.ok) throw new Error(out?.error || `HTTP ${res.status}`);
				if (st.sel === item) st.sel = null;
				armedCell = null;
				await refresh(null);
				setNotice(`已删除「${item.name}」`);
			} catch (err) {
				// 失败要还原，否则那一格会卡在「…」上，点也点不动
				delete cell.dataset.busy;
				const ok = cell.querySelector(".gp-ask-ok");
				if (ok) ok.textContent = "删除";
				setNotice(`删除失败：${err.message}`);
				console.error(`[MK-${itemLabel}库] 删除失败：`, err);
			}
		}

		// 「导入」和「随机」各有独立类名，一律用上面取好的引用，别拿 .gp-btn 当选择器
		importBtn.onclick = () => fileInput.click();
		shuffleBtn.onclick = () => {
			const list = visibleItems();
			if (!list.length) {
				setNotice("这个范围里没有图");
				return;
			}
			pickCell(list[Math.floor(Math.random() * list.length)]);
		};

		fileInput.onchange = () => {
			const files = Array.from(fileInput.files || []);
			fileInput.value = ""; // 清掉，允许重复选同一个文件
			openImport(files);
		};

		dlg.querySelector(".gp-dlg-x").onclick = closeImport;
		dlg.querySelector(".gp-dlg-cancel").onclick = closeImport;
		dlg.querySelector(".gp-dlg-file").onclick = () => fileInput.click();
		dlg.querySelector(".gp-dlg-clip").onclick = () => pasteFromClipboard();
		dlgOk.onclick = () => confirmImport();
		dlgName.oninput = updateHint;

		// 分类：点箭头展开全部，输入即过滤；输入新名字时列表顶部给「新建」。
		// 不要用 blur 关菜单 —— 点列表项时 blur 先触发，点击就丢了。
		catToggle.onclick = () => {
			if (catMenu.hidden) renderCatMenu();
			else closeCatMenu();
			focusCatInput();
		};
		// 鼠标一按下就展开：只监听 input 的话，第一次点进来列表是空的
		dlgCat.addEventListener("pointerdown", () => {
			if (catMenu.hidden) renderCatMenu();
		});
		dlgCat.addEventListener("focus", () => {
			if (suppressFocusOpen) return;
			if (catMenu.hidden) renderCatMenu();
		});
		dlgCat.addEventListener("input", () => {
			updateHint();
			renderCatMenu();
		});
		dlgCat.addEventListener("keydown", (e) => {
			if (e.key === "ArrowDown" && catMenu.hidden) {
				e.preventDefault();
				renderCatMenu();
			}
		});
		// 点对话框别处收起列表；列表项在 .gp-cat 里面，不会被这条误关
		dlgBody.addEventListener("pointerdown", (e) => {
			if (!(e.target instanceof Element) || !e.target.closest(".gp-cat")) closeCatMenu();
		});

		// 回车导入、Esc 关闭；中文输入法选字时的回车不算
		dlgBody.addEventListener("keydown", (e) => {
			if (e.key === "Enter" && !e.isComposing) {
				e.preventDefault();
				e.stopPropagation();
				confirmImport();
			} else if (e.key === "Escape") {
				e.preventDefault();
				e.stopPropagation();
				if (!catMenu.hidden) closeCatMenu();
				else closeImport();
			}
		});
		dlg.addEventListener("click", (e) => {
			if (e.target === dlg) closeImport();
		});

		// 复制图片后在画布上按 Ctrl+V 也能导入；焦点在输入框里时不动
		function onPaste(e) {
			const target = e.target;
			if (target instanceof HTMLElement && target.closest("input,textarea")) return;
			const near =
				!dlg.hidden ||
				node.is_selected ||
				root.matches(":hover") ||
				root.contains(document.activeElement);
			if (!near) return;
			const files = Array.from(e.clipboardData?.files || []).filter(isImageFile);
			if (!files.length) return;
			e.preventDefault();
			e.stopPropagation();
			openImport(files);
		}
		document.addEventListener("paste", onPaste);

		// 拖图片进面板 = 导入；拦在面板这一层，否则画布会把图当成节点素材吞掉
		const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes("Files");
		let dragDepth = 0;
		const onDragEnter = (e) => {
			if (!hasFiles(e)) return;
			e.preventDefault();
			dragDepth += 1;
			root.dataset.drop = "1";
		};
		const onDragOver = (e) => {
			if (hasFiles(e)) e.preventDefault();
		};
		const onDragLeave = () => {
			dragDepth = Math.max(0, dragDepth - 1);
			if (!dragDepth) root.dataset.drop = "0";
		};
		const onDrop = (e) => {
			if (!e.dataTransfer?.files?.length) return;
			e.preventDefault();
			e.stopPropagation();
			dragDepth = 0;
			root.dataset.drop = "0";
			openImport(e.dataTransfer.files);
		};
		root.addEventListener("dragenter", onDragEnter);
		root.addEventListener("dragover", onDragOver);
		root.addEventListener("dragleave", onDragLeave);
		root.addEventListener("drop", onDrop);

		// 节点删掉后摘掉全局监听，否则面板没了还在接粘贴 / 滚轮
		const prevRemoved = node.onRemoved;
		node.onRemoved = function () {
			document.removeEventListener("paste", onPaste);
			document.removeEventListener("keydown", onArmKeyDown);
			window.removeEventListener("wheel", onWheel, { capture: true });
			cancelAnimationFrame(gridRaf);
			return prevRemoved?.apply(this, arguments);
		};

		// ---------- 工具栏 ----------
		catSel.onchange = () => {
			const index = Number(catSel.value);
			const name = index === ALL_INDEX ? ALL : st.db?.categories[index]?.name || ALL;
			setWidget(catWidget, name);
			renderCatSel();
			renderGrid();
		};

		let searchTimer = null;
		searchInput.oninput = () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				st.query = searchInput.value.trim().toLowerCase();
				renderGrid();
			}, 130);
		};

		modeSel.onchange = () => {
			setWidget(modeWidget, modeSel.value);
			syncFromWidgets();
		};
		countBtn.onclick = () => {
			refresh(null)
				.then((db) => setNotice(`已刷新，共 ${db.total} ${unit}`))
				.catch((err) => setNotice(`刷新失败：${err.message}`));
		};

		// ---------- 数据 ----------
		function applyDB(db) {
			db.byLabel = new Map(db.items.map((item) => [item.label, item]));
			db.byId = new Map(db.items.map((item) => [item.id, item]));
			st.db = db;
			st.dir = st.dir || "";
		}

		function renderAll() {
			renderCatSel();
			renderGrid();
			renderStage();
			applyVisibility();
		}

		/** 重新拉索引并重建画廊；pickId 是导入后想立刻选中的那条。 */
		function refresh(pickId) {
			return loadDB(true).then((db) => {
				applyDB(db);
				const keep = db.byLabel.get(itemWidget.value);
				const fresh = pickId ? db.byId.get(pickId) : null;
				// 记住的选中项还在就留着；不在（被删了）就落到第一张
				let target = fresh || keep || db.items[0] || null;
				st.scrollTo = pickId || null;
				if (target) select(target, true);
				else {
					st.sel = null;
					setWidget(itemWidget, "");
					renderStage();
				}
				renderAll();
				return db;
			});
		}

		function loadDB(force) {
			if (force || !dbPromise) {
				dbPromise = api
					.fetchApi(`/${route}/index.json`)
					.then(async (res) => {
						const body = await res.json().catch(() => ({}));
						if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
						return body;
					})
					.catch((err) => {
						dbPromise = null;
						throw err;
					});
			}
			return dbPromise;
		}

		// 工作流恢复 / 参数被外部改动后，把界面拉回和 widget 一致
		function syncFromWidgets() {
			if (syncing || writing || !st.db) {
				if (!st.db) applyVisibility();
				return;
			}
			syncing = true;
			try {
				modeSel.value = modeWidget.value;
				const item = st.db.byLabel.get(itemWidget.value);
				if (item && item !== st.sel) {
					st.sel = item;
					renderStage();
					markSelection();
				}
				renderCatSel();
				renderGrid();
				applyVisibility();
			} finally {
				syncing = false;
			}
		}

		for (const widget of [modeWidget, itemWidget, catWidget]) {
			const orig = widget.callback;
			widget.callback = function (...args) {
				const r = orig?.apply(this, args);
				syncFromWidgets();
				return r;
			};
		}

		// 执行后把真正抽到的项同步到画廊，并写下拉值，切回固定选中时还能保留
		node.__mkApply = (picked) => {
			if (!st.db || !picked) return;
			const item = st.db.byId.get(picked.id) || st.db.byLabel.get(picked.label);
			if (!item) return;
			// 抽到的可能不在当前筛选里，那种情况预览要压暗提示「上次」
			st.stale = isRandom() && !scopedPool().some((row) => row.id === item.id);
			select(item, true);
		};

		node.__mkResync = () => {
			sanitizeWidgets();
			syncFromWidgets();
		};

		// ---------- 启动 ----------
		libraryPaths(route)
			.then((info) => {
				if (!info?.img) return;
				st.dir = info.img;
				// 空库时空白提示里要显示数据目录，路径回来晚了就补画一次
				if (st.db && !st.db.total) renderGrid();
			})
			.catch(() => {});

		loadDB()
			.then((db) => {
				applyDB(db);
				// 先记下恢复出来的值：下面 select() 会把它改写，之后再判断就永远「不在了」
				const saved = itemWidget.value;
				const keep = saved ? db.byLabel.get(saved) : null;
				if (keep) select(keep, false);
				else if (db.items.length) select(db.items[0], true);
				else {
					st.sel = null;
					renderStage();
				}
				renderAll();
				if (saved && !keep) {
					setNotice(`上次选的「${saved}」已经不在了`, 8000);
				}
			})
			.catch((err) => {
				root.innerHTML = `<div class="gp-blank">${itemLabel}库载入失败：${err.message}<br>
					请确认 ComfyUI 控制台里的报错</div>`;
				console.error(`[MK-${itemLabel}库]`, err);
			});

		// 先按默认收一遍参数，避免刚拖出来时一排灰条
		sanitizeWidgets();
		applyVisibility();
		applyDB({ items: [], categories: [], total: 0 });
		renderAll();
		node.setSize([440, GALLERY_HEIGHT + chromeHeight()]);

		// 只处理「历史版本失控存下的超大尺寸」：超过上限就拉回默认，正常拖高不动
		node.__mkClampHeight = () => {
			if (node.size[1] > 2400) node.setSize([node.size[0], chromeHeight() + GALLERY_HEIGHT]);
			node.__mkSyncHeight?.();
		};
		node.__mkClampHeight();

		gallery.options.minNodeSize = [440, MIN_GALLERY_H + 120];

		// 面板高度跟随节点：不溢出（不会越拉越长），同时缩小能跟着缩
		function syncPanelHeight() {
			const y = Number.isFinite(gallery.y) && gallery.y > 20 ? Number(gallery.y) : 96;
			const byNode = node.size[1] - y;
			const byAlloc = Number(gallery.computedHeight);
			const avail = Number.isFinite(byAlloc) && byAlloc > 0 ? Math.min(byNode, byAlloc) : byNode;
			const px = Math.max(MIN_GALLERY_H, Math.min(4000, Math.round(avail - 6)));
			if (px === curGalleryH) return;
			curGalleryH = px;
			if (!previewManual) previewH = Math.max(140, Math.min(320, Math.round(px * 0.42)));
			applyStageHeight();
		}
		node.__mkSyncHeight = syncPanelHeight;
		syncPanelHeight();
		if (typeof requestAnimationFrame === "function") {
			requestAnimationFrame(syncPanelHeight);
			setTimeout(syncPanelHeight, 80);
		}
	}

	/**
	 * 本节点只有一个输出。旧工作流存着 image / pose_name / pose_info 三个槽，
	 * litegraph 恢复时会照抄存档的 outputs，这里直接摘掉多余的。
	 */
	function trimOutputs(node) {
		const OUTPUT_COUNT = 1;
		if ((node.outputs?.length ?? 0) <= OUTPUT_COUNT) return;
		while (node.outputs.length > OUTPUT_COUNT) {
			node.removeOutput(node.outputs.length - 1);
		}
		const need = node.computeSize()[1];
		if (node.size[1] < need) node.setSize([node.size[0], need]);
		node.graph?.setDirtyCanvas(true, true);
	}
}
