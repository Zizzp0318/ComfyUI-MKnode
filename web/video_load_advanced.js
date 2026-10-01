/**
 * MK-视频加载（高级）前端界面
 *
 * 迁移自 ComfyUI-AICoser-Tools 的 AICoser_LoadVideoUpload 前端，
 * 仅保留该节点所需的函数，其余节点的 UI 代码未搬入。
 *
 * 相对原版的改动：节点名/扩展名/路由/DOM 控件名/内部字段全部加 MK 前缀做隔离，
 * 界面文案汉化。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

function getWidgetByName(node, name) {
    return node?.widgets?.find((w) => w.name === name);
}

function registerExtensionSafe(extension) {
    try {
        app.registerExtension(extension);
    } catch (e) {
        const message = String(e?.message || e || "");
        if (message.includes("already registered")) {
            console.warn(`[Comfyui_MKnode] extension already registered, skipped: ${extension?.name}`);
            return;
        }
        throw e;
    }
}

function getViewUrl(filename) {
    const previewParam = app.getPreviewFormatParam?.() || "";
    const randParam = app.getRandParam?.() || "";
    const normalized = String(filename || "").replace(/\\/g, "/");
    const parts = normalized.split("/");
    const basename = parts.pop() || "";
    const subfolder = parts.join("/");
    const subfolderParam = subfolder ? `&subfolder=${encodeURIComponent(subfolder)}` : "";
    return api.apiURL(`/view?filename=${encodeURIComponent(basename)}&type=input${subfolderParam}${previewParam}${randParam}`);
}

async function fetchVideoMetadata(filename) {
    if (!filename) return null;
    const resp = await api.fetchApi(`/mk_video_metadata?filename=${encodeURIComponent(filename)}`);
    if (!resp.ok) {
        throw new Error(`video metadata failed: HTTP ${resp.status}`);
    }
    return await resp.json();
}

function isFilesDragEvent(e) {
    const dt = e?.dataTransfer;
    if (!dt) return false;
    if (dt.files && dt.files.length > 0) return true;
    // Some browsers only set types during dragover
    return Array.from(dt.types || []).includes("Files");
}

const MK_UPLOAD_SUBFOLDER = "mk_video_uploads";

async function uploadOneVideo(file) {
    const body = new FormData();
    body.append("image", file, file.name);
    body.append("type", "input");
    body.append("subfolder", MK_UPLOAD_SUBFOLDER);

    const resp = await api.fetchApi("/upload/image", {
        method: "POST",
        body,
    });
    if (!resp.ok) {
        throw new Error(`Upload failed: HTTP ${resp.status}`);
    }
    const json = await resp.json();
    const name = json?.name;
    const subfolder = json?.subfolder || MK_UPLOAD_SUBFOLDER;
    if (!name) return "";
    return subfolder ? `${subfolder}/${name}` : name;
}

function getVideoWidget(node) {
    return getWidgetByName(node, "video");
}

function setWidgetValue(node, name, value) {
    const w = getWidgetByName(node, name);
    if (!w) return;
    w.value = value;
    w.callback?.(w.value);
    app.graph.setDirtyCanvas(true);
}

function getWidgetNumber(node, name, fallback = 0) {
    const w = getWidgetByName(node, name);
    const n = Number(w?.value);
    return Number.isFinite(n) ? n : fallback;
}

const MK_VIDEO_NODE_MIN_WIDTH = 460;
const MK_VIDEO_NODE_MIN_HEIGHT = 560;
const MK_VIDEO_NODE_DEFAULT_HEIGHT = 640;
const MK_VIDEO_PREVIEW_MIN_HEIGHT = 160;
const MK_VIDEO_PREVIEW_MAX_HEIGHT = 360;
const MK_VIDEO_WIDGET_BASE_HEIGHT = 150;

function createVideoUploadUI(node) {
    const videoWidget = getVideoWidget(node);
    if (!videoWidget) {
        throw new Error("video widget not found");
    }
    const previewFpsWidget = getWidgetByName(node, "preview_fps");
    if (previewFpsWidget) {
        previewFpsWidget.type = "hidden";
        previewFpsWidget.computeSize = () => [0, -4];
    }
    let sourceVideoMeta = null;
    let metadataRequestId = 0;

    const container = document.createElement("div");
    container.style.cssText =
        "box-sizing:border-box;width:100%;min-height:280px;padding:6px;background:var(--comfy-menu-bg);border:1px solid var(--border-color);border-radius:6px;margin:4px 0;pointer-events:auto;display:flex;flex-direction:column;gap:6px;overflow:visible;position:relative;z-index:10;";

    const drop = document.createElement("div");
    drop.textContent = "拖入视频，或点击此处上传";
    drop.style.cssText =
        "padding:7px;border:1px dashed var(--border-color);border-radius:6px;text-align:center;cursor:pointer;font-size:12px;";

    const video = document.createElement("video");
    video.controls = false;
    video.preload = "metadata";
    video.disablePictureInPicture = true;
    video.setAttribute("controlsList", "nodownload noplaybackrate");
    video.style.cssText = "display:block;width:100%;height:100%;object-fit:fill;background:#000;";

    const previewWrap = document.createElement("div");
    previewWrap.style.cssText = `width:100%;height:${MK_VIDEO_PREVIEW_MIN_HEIGHT}px;overflow:hidden;background:#000;border-radius:4px;margin:0 auto;`;
    previewWrap.appendChild(video);

    const info = document.createElement("div");
    info.style.cssText = "box-sizing:border-box;font-size:11px;line-height:1.25;opacity:0.95;min-height:42px;overflow:hidden;padding:4px 6px;background:rgba(0,0,0,0.18);border-radius:4px;display:flex;flex-direction:column;gap:2px;";

    const controls = document.createElement("div");
    controls.style.cssText = "box-sizing:border-box;display:flex;align-items:center;gap:6px;padding:4px 6px;background:rgba(0,0,0,0.18);border-radius:4px;";

    const playBtn = document.createElement("button");
    playBtn.textContent = "▶";
    playBtn.style.cssText = "width:30px;height:24px;padding:0;background:var(--comfy-input-bg);color:var(--input-text);border:1px solid var(--border-color);border-radius:4px;cursor:pointer;font-size:12px;line-height:1;";

    const frameLabel = document.createElement("div");
    frameLabel.style.cssText = "min-width:82px;font-size:11px;opacity:0.95;white-space:nowrap;";

    const progressWrap = document.createElement("div");
    progressWrap.style.cssText = "position:relative;flex:1;height:18px;cursor:pointer;";

    const progressTrack = document.createElement("div");
    progressTrack.style.cssText = "position:absolute;left:0;right:0;top:7px;height:4px;background:rgba(255,255,255,0.18);border-radius:999px;overflow:hidden;";

    const rangeFill = document.createElement("div");
    rangeFill.style.cssText = "position:absolute;top:0;height:100%;background:rgba(80,180,255,0.28);";

    const progressFill = document.createElement("div");
    progressFill.style.cssText = "position:absolute;left:0;top:0;height:100%;width:0%;background:rgba(255,255,255,0.72);";

    const startMarker = document.createElement("div");
    startMarker.style.cssText = "position:absolute;top:2px;width:2px;height:14px;background:#6cf;border-radius:2px;transform:translateX(-1px);";

    const endMarker = document.createElement("div");
    endMarker.style.cssText = "position:absolute;top:2px;width:2px;height:14px;background:#f96;border-radius:2px;transform:translateX(-1px);";

    progressTrack.appendChild(rangeFill);
    progressTrack.appendChild(progressFill);
    progressWrap.appendChild(progressTrack);
    progressWrap.appendChild(startMarker);
    progressWrap.appendChild(endMarker);
    controls.appendChild(playBtn);
    controls.appendChild(frameLabel);
    controls.appendChild(progressWrap);

    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:5px;flex-wrap:wrap;";

    const mkBtn = (label) => {
        const b = document.createElement("button");
        b.textContent = label;
        b.style.cssText =
            "flex:1;min-width:96px;padding:5px 6px;background:var(--comfy-input-bg);color:var(--input-text);border:1px solid var(--border-color);border-radius:4px;cursor:pointer;font-size:11px;";
        return b;
    };
    const setStartBtn = mkBtn("设置起点");
    const setEndBtn = mkBtn("设置终点");
    const resetRangeBtn = mkBtn("重置范围");

    row.appendChild(setStartBtn);
    row.appendChild(setEndBtn);
    row.appendChild(resetRangeBtn);

    const refreshSource = () => {
        const filename = videoWidget.value;
        const requestId = ++metadataRequestId;
        sourceVideoMeta = null;
        video.pause();
        if (!filename) {
            video.removeAttribute("src");
            video.load();
            info.replaceChildren();
            return;
        }
        video.src = getViewUrl(filename);
        video.load();
        updateInfo();
        resizeNode();
        fetchVideoMetadata(filename)
            .then((meta) => {
                if (requestId !== metadataRequestId) return;
                sourceVideoMeta = meta;
                updateInfo();
                resizeNode();
            })
            .catch((e) => {
                if (requestId !== metadataRequestId) return;
                console.warn("[MK_VideoLoadAdvanced] video metadata unavailable, using preview_fps fallback", filename, e);
                updateInfo();
            });
    };

    const getOutputSize = () => {
        const sourceWidth = video.videoWidth || 0;
        const sourceHeight = video.videoHeight || 0;
        const customWidth = Math.max(0, Math.floor(getWidgetNumber(node, "custom_width", 0)));
        const customHeight = Math.max(0, Math.floor(getWidgetNumber(node, "custom_height", 0)));
        if (customWidth > 0 && customHeight > 0) return [customWidth, customHeight];
        if (customWidth > 0 && sourceWidth > 0 && sourceHeight > 0) {
            return [customWidth, Math.max(1, Math.round(sourceHeight * (customWidth / sourceWidth)))];
        }
        if (customHeight > 0 && sourceWidth > 0 && sourceHeight > 0) {
            return [Math.max(1, Math.round(sourceWidth * (customHeight / sourceHeight))), customHeight];
        }
        return [sourceWidth || 16, sourceHeight || 9];
    };

    const resizeNode = () => {
        requestAnimationFrame(() => {
            const width = Math.max(MK_VIDEO_NODE_MIN_WIDTH, node.size?.[0] || MK_VIDEO_NODE_MIN_WIDTH);
            const height = Math.max(MK_VIDEO_NODE_MIN_HEIGHT, node.size?.[1] || MK_VIDEO_NODE_DEFAULT_HEIGHT);
            if ((node.size?.[0] || 0) < MK_VIDEO_NODE_MIN_WIDTH || (node.size?.[1] || 0) < MK_VIDEO_NODE_MIN_HEIGHT) {
                node.setSize?.([width, height]);
            }
            const [outputWidth, outputHeight] = getOutputSize();
            const aspectRatio = outputWidth / outputHeight;
            const maxPreviewWidth = Math.max(1, width - 24);
            const naturalHeight = Math.max(MK_VIDEO_PREVIEW_MIN_HEIGHT, maxPreviewWidth / aspectRatio);
            const previewHeight = Math.min(MK_VIDEO_PREVIEW_MAX_HEIGHT, naturalHeight);
            const previewWidth = Math.min(maxPreviewWidth, Math.max(1, previewHeight * aspectRatio));
            previewWrap.style.width = `${previewWidth}px`;
            previewWrap.style.height = `${previewHeight}px`;
            node._mkVideoWidgetHeight = MK_VIDEO_WIDGET_BASE_HEIGHT + previewHeight;
            app.graph.setDirtyCanvas(true, true);
        });
    };

    const getSourceFps = () => Math.max(1, Number(sourceVideoMeta?.fps) || getWidgetNumber(node, "preview_fps", 24));
    const getDisplayFps = () => {
        const forceRate = Number(getWidgetNumber(node, "force_rate", 0));
        return Math.max(1, forceRate > 0 ? forceRate : getSourceFps());
    };
    const getPreviewRange = () => {
        const sourceFps = getSourceFps();
        const displayFps = getDisplayFps();
        const duration = Number.isFinite(video.duration) ? video.duration : 0;
        const sourceTotalFrames = duration > 0 ? Math.round(duration * sourceFps) : 0;
        const displayTotalFrames = duration > 0 ? Math.round(duration * displayFps) : 0;
        const startFrame = Math.max(0, Math.min(displayTotalFrames, Math.floor(getWidgetNumber(node, "skip_first_frames", 0))));
        const cap = Math.max(0, Math.floor(getWidgetNumber(node, "frame_load_cap", 0)));
        const endFrame = cap > 0 ? Math.min(displayTotalFrames, startFrame + cap) : displayTotalFrames;
        const loadedTotalFrames = Math.max(0, endFrame - startFrame);
        return { sourceFps, displayFps, sourceTotalFrames, displayTotalFrames, startFrame, endFrame, loadedTotalFrames };
    };
    const clampFrameToPreviewRange = (frame) => {
        const { startFrame, endFrame } = getPreviewRange();
        if (endFrame > startFrame) return Math.max(startFrame, Math.min(frame, endFrame));
        return Math.max(0, frame);
    };
    const seekToPreviewStart = () => {
        const { displayFps, startFrame } = getPreviewRange();
        if (displayFps > 0) video.currentTime = (startFrame + 0.001) / displayFps;
        updateInfo();
    };
    const seekToPreviewStartIfOutside = () => {
        const { displayFps, startFrame, endFrame } = getPreviewRange();
        if (displayFps <= 0) return;
        const frame = Math.floor((video.currentTime || 0) * displayFps);
        if (frame < startFrame || (endFrame > startFrame && frame >= endFrame)) {
            video.currentTime = (startFrame + 0.001) / displayFps;
        }
        updateInfo();
    };

    const getOutputSizeText = () => getOutputSize().join("x");

    const updateCustomControls = () => {
        const { displayFps, displayTotalFrames, startFrame, endFrame } = getPreviewRange();
        const displayFrame = Math.max(0, Math.min(displayTotalFrames, Math.round((video.currentTime || 0) * displayFps)));
        const total = Math.max(1, displayTotalFrames);
        const startPct = Math.max(0, Math.min(100, (startFrame / total) * 100));
        const endPct = Math.max(startPct, Math.min(100, ((endFrame || displayTotalFrames) / total) * 100));
        const currentPct = Math.max(0, Math.min(100, (displayFrame / total) * 100));
        playBtn.textContent = video.paused ? "▶" : "❚❚";
        frameLabel.textContent = `${displayFrame}/${displayTotalFrames}`;
        progressFill.style.width = `${currentPct}%`;
        rangeFill.style.left = `${startPct}%`;
        rangeFill.style.width = `${Math.max(0, endPct - startPct)}%`;
        startMarker.style.left = `${startPct}%`;
        endMarker.style.left = `${endPct}%`;
        startMarker.title = `起点 ${startFrame}`;
        endMarker.title = `终点 ${endFrame || displayTotalFrames}`;
    };

    const updateInfo = () => {
        const { displayFps, displayTotalFrames, startFrame, endFrame } = getPreviewRange();
        const displayFrame = Math.max(0, Math.min(displayTotalFrames, Math.round((video.currentTime || 0) * displayFps)));
        const fileLine = document.createElement("div");
        fileLine.textContent = videoWidget.value || "";
        fileLine.title = videoWidget.value || "";
        fileLine.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;";

        const metaLine = document.createElement("div");
        metaLine.textContent = [
            `输出 ${getOutputSizeText()}`,
            `帧率 ${displayFps}`,
            `帧 ${displayFrame}/${displayTotalFrames}`,
            `范围 ${startFrame}-${endFrame}`,
        ].join("   ");
        metaLine.title = metaLine.textContent;
        metaLine.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";

        info.replaceChildren(fileLine, metaLine);
        updateCustomControls();
    };

    const seekToClientX = (clientX) => {
        const rect = progressWrap.getBoundingClientRect();
        if (!rect.width) return;
        const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        const { displayFps, displayTotalFrames } = getPreviewRange();
        const targetFrame = Math.max(0, Math.min(displayTotalFrames, Math.round(displayTotalFrames * pct)));
        if (displayFps > 0) video.currentTime = targetFrame / displayFps;
        updateInfo();
    };

    const chooseFile = async (file) => {
        if (!file) return;
        if (file.type && !file.type.startsWith("video/") && file.type !== "image/gif") return;
        const name = await uploadOneVideo(file);
        if (!videoWidget.options.values.includes(name)) {
            videoWidget.options.values.push(name);
        }
        videoWidget.value = name;
        videoWidget.callback?.(name);
        refreshSource();
        app.graph.setDirtyCanvas(true);
    };

    drop.onclick = () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "video/webm,video/mp4,video/x-matroska,video/quicktime,image/gif";
        input.onchange = async (e) => {
            try {
                await chooseFile(e.target.files?.[0]);
            } finally {
                input.remove();
            }
        };
        document.body.appendChild(input);
        input.click();
    };

    container.addEventListener("dragover", (e) => {
        if (!isFilesDragEvent(e)) return;
        e.preventDefault();
        e.stopPropagation();
        drop.style.borderColor = "#4a6";
    });
    container.addEventListener("dragleave", () => {
        drop.style.borderColor = "var(--border-color)";
    });
    container.addEventListener("drop", async (e) => {
        if (!isFilesDragEvent(e)) return;
        e.preventDefault();
        e.stopPropagation();
        drop.style.borderColor = "var(--border-color)";
        await chooseFile(Array.from(e.dataTransfer?.files || [])[0]);
    });

    const preventVideoFullscreenGesture = (e) => {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation?.();
    };
    previewWrap.addEventListener("dblclick", preventVideoFullscreenGesture, true);
    video.addEventListener("dblclick", preventVideoFullscreenGesture, true);
    video.addEventListener("mousedown", (e) => {
        if (e.detail > 1) preventVideoFullscreenGesture(e);
    }, true);
    video.addEventListener("pointerdown", (e) => {
        if (e.detail > 1) preventVideoFullscreenGesture(e);
    }, true);
    video.addEventListener("fullscreenchange", () => {
        if (document.fullscreenElement === video) {
            document.exitFullscreen?.();
        }
    });
    video.addEventListener("loadedmetadata", seekToPreviewStart);
    video.addEventListener("loadedmetadata", resizeNode);
    video.addEventListener("timeupdate", () => {
        const { displayFps, startFrame, endFrame } = getPreviewRange();
        if (!video.paused && startFrame > 0 && video.currentTime * displayFps < startFrame) {
            video.currentTime = startFrame / displayFps;
            updateInfo();
            return;
        }
        if (!video.paused && endFrame > 0 && video.currentTime * displayFps >= endFrame) {
            video.currentTime = startFrame / displayFps;
            if (video.paused) {
                updateInfo();
            }
            return;
        }
        updateInfo();
    });
    video.addEventListener("seeked", updateInfo);
    video.addEventListener("play", updateInfo);
    video.addEventListener("pause", updateInfo);

    playBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const { displayFps, startFrame, endFrame } = getPreviewRange();
        if (displayFps > 0 && endFrame > startFrame && (video.currentTime * displayFps < startFrame || video.currentTime * displayFps >= endFrame)) {
            video.currentTime = startFrame / displayFps;
        }
        if (video.paused) {
            video.play();
        } else {
            video.pause();
        }
        updateInfo();
    };

    progressWrap.addEventListener("pointerdown", (e) => {
        const wasPaused = video.paused;
        if (!wasPaused) video.pause();
        e.preventDefault();
        e.stopPropagation();
        progressWrap.setPointerCapture?.(e.pointerId);
        seekToClientX(e.clientX);
        const move = (moveEvent) => seekToClientX(moveEvent.clientX);
        const up = () => {
            progressWrap.removeEventListener("pointermove", move);
            progressWrap.removeEventListener("pointerup", up);
            progressWrap.removeEventListener("pointercancel", up);
        };
        progressWrap.addEventListener("pointermove", move);
        progressWrap.addEventListener("pointerup", up);
        progressWrap.addEventListener("pointercancel", up);
    });

    setStartBtn.onclick = () => {
        const currentFrame = Math.max(0, Math.round((video.currentTime || 0) * getDisplayFps()));
        setWidgetValue(node, "skip_first_frames", currentFrame);
        seekToPreviewStart();
    };
    setEndBtn.onclick = () => {
        const currentFrame = Math.max(0, Math.round((video.currentTime || 0) * getDisplayFps()));
        const startFrame = Math.max(0, Math.floor(getWidgetNumber(node, "skip_first_frames", 0)));
        setWidgetValue(node, "frame_load_cap", Math.max(0, currentFrame - startFrame));
        seekToPreviewStartIfOutside();
    };
    resetRangeBtn.onclick = () => {
        setWidgetValue(node, "skip_first_frames", 0);
        setWidgetValue(node, "frame_load_cap", 0);
        seekToPreviewStart();
    };

    container.appendChild(drop);
    container.appendChild(previewWrap);
    container.appendChild(controls);
    container.appendChild(info);
    container.appendChild(row);

    const origCallback = videoWidget.callback;
    videoWidget.callback = function (value) {
        origCallback?.call(this, value);
        refreshSource();
    };

    for (const name of ["force_rate", "custom_width", "custom_height", "frame_load_cap", "skip_first_frames", "select_every_nth", "preview_fps"]) {
        const w = getWidgetByName(node, name);
        if (!w) continue;
        const orig = w.callback;
        w.callback = function (value) {
            orig?.call(this, value);
            if (name === "force_rate" || name === "skip_first_frames" || name === "frame_load_cap") {
                seekToPreviewStart();
            }
            updateInfo();
            resizeNode();
        };
    }

    refreshSource();
    resizeNode();
    return { container, refreshSource, updateInfo, resizeNode };
}

registerExtensionSafe({
    name: "Comfyui_MKnode.VideoLoadAdvanced",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "MK_VideoLoadAdvanced") return;

        function scheduleEnsureVideoUploadUI(node) {
            requestAnimationFrame(() => ensureVideoUploadUI(node));
            setTimeout(() => ensureVideoUploadUI(node), 50);
            setTimeout(() => ensureVideoUploadUI(node), 250);
        }

        function mountVideoUploadWidget(node, container) {
            const widget = node.addDOMWidget("mk_video_upload", "customwidget", container);
            widget.serialize = false;
            widget.hideOnZoom = false;
            widget.computeSize = function (width) {
                const height = node._mkVideoWidgetHeight || MK_VIDEO_WIDGET_BASE_HEIGHT + MK_VIDEO_PREVIEW_MIN_HEIGHT;
                return [width, height];
            };
            node._mkVideoWidget = widget;
            return widget;
        }

        function ensureVideoUploadUI(node) {
            if (node._mkVideoUI) {
                const widgetMissing = !node._mkVideoWidget || !node.widgets?.includes(node._mkVideoWidget);
                if (widgetMissing) {
                    mountVideoUploadWidget(node, node._mkVideoUI.container);
                }
                node._mkVideoUI.refreshSource?.();
                node._mkVideoUI.resizeNode?.();
                return node._mkVideoUI;
            }

            let ui = null;
            try {
                ui = createVideoUploadUI(node);
            } catch (e) {
                if (e?.message === "video widget not found") {
                    console.warn("[MK_VideoLoadAdvanced] video widget not found, retrying", node?.widgets?.map((w) => w?.name));
                    return null;
                }
                console.error("[MK_VideoLoadAdvanced] failed to create video UI", e);
                const container = document.createElement("div");
                container.style.cssText = "box-sizing:border-box;width:100%;min-height:80px;padding:8px;background:#2a1111;border:1px solid #a44;border-radius:6px;color:#fff;font-size:12px;white-space:pre-wrap;pointer-events:auto;";
                container.textContent = `MK 视频界面创建失败：\n${e?.message || e}`;
                ui = {
                    container,
                    refreshSource: () => {},
                    updateInfo: () => {},
                    resizeNode: () => {},
                };
            }
            if (!ui) return null;

            node._mkVideoUI = ui;
            mountVideoUploadWidget(node, ui.container);
            node.setSize([
                Math.max(MK_VIDEO_NODE_MIN_WIDTH, node.size?.[0] || MK_VIDEO_NODE_MIN_WIDTH),
                Math.max(MK_VIDEO_NODE_DEFAULT_HEIGHT, node.size?.[1] || MK_VIDEO_NODE_DEFAULT_HEIGHT),
            ]);
            app.graph.setDirtyCanvas(true, true);
            return ui;
        }
        window.__mkEnsureVideoUploadUI = ensureVideoUploadUI;
        window.__mkScanVideoUploadUI?.();

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origOnNodeCreated?.apply(this, arguments);
            scheduleEnsureVideoUploadUI(this);
            return r;
        };

        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = origOnConfigure?.apply(this, arguments);
            scheduleEnsureVideoUploadUI(this);
            return r;
        };

        const origOnAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function () {
            const r = origOnAdded?.apply(this, arguments);
            scheduleEnsureVideoUploadUI(this);
            return r;
        };

        const origOnResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function () {
            const r = origOnResize?.apply(this, arguments);
            this._mkVideoUI?.resizeNode?.();
            return r;
        };
    },
    setup() {
        const fallbackEnsure = (node) => {
            if (node._mkVideoUI && node._mkVideoWidget && node.widgets?.includes(node._mkVideoWidget)) {
                node._mkVideoUI.refreshSource?.();
                node._mkVideoUI.resizeNode?.();
                return;
            }
            if (!node._mkVideoUI) {
                try {
                    node._mkVideoUI = createVideoUploadUI(node);
                } catch (e) {
                    console.error("[MK_VideoLoadAdvanced] fallback create failed", e);
                    return;
                }
            }
            const widget = node.addDOMWidget("mk_video_upload", "customwidget", node._mkVideoUI.container);
            widget.serialize = false;
            widget.hideOnZoom = false;
            widget.computeSize = function (width) {
                const height = node._mkVideoWidgetHeight || MK_VIDEO_WIDGET_BASE_HEIGHT + MK_VIDEO_PREVIEW_MIN_HEIGHT;
                return [width, height];
            };
            node._mkVideoWidget = widget;
            node.setSize([
                Math.max(MK_VIDEO_NODE_MIN_WIDTH, node.size?.[0] || MK_VIDEO_NODE_MIN_WIDTH),
                Math.max(MK_VIDEO_NODE_DEFAULT_HEIGHT, node.size?.[1] || MK_VIDEO_NODE_DEFAULT_HEIGHT),
            ]);
            node._mkVideoUI.refreshSource?.();
            node._mkVideoUI.resizeNode?.();
            app.graph.setDirtyCanvas(true, true);
        };
        const scan = () => {
            for (const node of app.graph?._nodes || []) {
                if (node?.type === "MK_VideoLoadAdvanced") {
                    if (window.__mkEnsureVideoUploadUI) {
                        window.__mkEnsureVideoUploadUI(node);
                    }
                    if (!node.widgets?.some((w) => w?.name === "mk_video_upload")) {
                        fallbackEnsure(node);
                    }
                }
            }
        };
        window.__mkScanVideoUploadUI = scan;
        requestAnimationFrame(scan);
        for (const delay of [50, 250, 500, 1000, 1500, 2500, 4000, 6000]) {
            setTimeout(scan, delay);
        }
    },
});