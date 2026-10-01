# ComfyUI-MKnode

MK 系列 ComfyUI 自定义节点合集：图像加载 / 选择 / 保存，视频加载 / 保存。

所有节点都在 **`MK节点`** 分类下。

## 节点一览

| 节点 | 说明 |
| --- | --- |
| MK-加载图像 | 加载图像，可按目标总像素等比缩放 |
| MK-图像选择器 | 执行时暂停，手动挑选图像后再继续 |
| MK-图像保存 | 保存图像，支持 PNG / JPEG / WEBP |
| MK-加载视频 | 从 input 目录加载视频 |
| MK-保存视频 | 保存视频，支持 mp4 / mkv / webm |

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Zizzp0318/ComfyUI-MKnode.git
```

重启 ComfyUI 即可，无需额外依赖（只用到 ComfyUI 自带的 torch / Pillow / PyAV）。

## 节点参数

### MK-加载图像

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 图像 | — | 从 input 目录选择，支持直接上传 |
| 缩放模式 | 禁用 | `禁用` 保持原尺寸；`按总像素` 按目标总像素等比缩放 |
| 目标总像素 | 1 | 单位为**百万像素(MP)**，1 表示约 100 万像素。范围 0.01 ~ 16 |
| 尺寸倍数 | 1 | 把宽高**就近对齐**到该值的整数倍，1 表示不对齐。常用于避免 VAE 不整除报错 |
| 缩放算法 | lanczos | nearest-exact / bilinear / area / bicubic / lanczos |

输出：`图像`、`遮罩`、`宽度`、`高度`。

> `禁用` 模式下的输出与官方 LoadImage **逐元素完全一致**，可直接替换现有工作流中的加载节点。

### MK-图像选择器

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 图像 | — | 待选择的图像，多张时平铺显示在节点上 |
| 模式 | 等待选择 | `等待选择` 执行时暂停，点选后点「确认选择」继续；`自动通过` 不暂停，直接放行全部图像 |

输出：`选中图像`、`选中索引`（逗号分隔）。

点选图像后按钮会显示已选数量，点「确认选择」继续；点「取消运行」中断整个执行。

### MK-图像保存

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 图像 | — | 要保存的图像 |
| 文件名前缀 | ComfyUI | 支持 `%date:yyyy-MM-dd%`、`%width%`、`%height%`、`%batch_num%` 等占位符 |
| 图像格式 | PNG | PNG / JPEG / WEBP |
| 图像质量 | 95 | 1 ~ 100，**仅 JPEG 与 WEBP 生效** |
| 保存元数据 | 关 | 开启后写入提示词与工作流信息（PNG 用文本块，JPEG / WEBP 用 EXIF UserComment） |
| 仅预览 | 关 | 开启后只写临时目录，不占用输出目录 |

输出：`图像`（原样透传，便于串接）。

> 若以 `--disable-metadata` 启动 ComfyUI，即使开关打开也不会写入元数据（与官方 SaveImage 行为一致）。

### MK-加载视频

从 input 目录加载视频，支持直接上传。节点上会显示视频预览。

### MK-保存视频

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 视频 | — | 要保存的视频 |
| 文件名前缀 | video/ComfyUI | 支持占位符 |
| 格式 | auto | auto / mp4 / mkv / webm。auto 时 AV1 用 WebM，其余用 MP4 |
| 编解码器 | auto | auto / h264 / av1，可选重新编码并指定 CRF |

输出：`视频`（原样透传）。

## 关于视频节点尺寸

官方 `LoadVideo` / `SaveVideo` 在加载视频后节点尺寸会被固定，无法自由缩放，且每次重新加载尺寸会跳变。

原因是前端 `useNodeVideo` 把「按**加载那一刻**的节点宽度算出的等比高度」写入了控件的最小尺寸约束，而这个值算出来就冻结了；`LGraphNode` 又把它当作节点宽度和高度的硬下限。

本包通过 `web/video_node_resize.js` 接管该控件的尺寸计算，让节点可以自由缩放。该修复**同时作用于官方节点**，如果不想改动官方节点行为，删掉脚本里 `TARGET_NODE_NAMES` 的后两项即可。

## 说明

- 图像加载直接复用官方 `LoadImage` 的加载逻辑，保证 pyav / Pillow 两条路径（含动画 WebP 回退、EXIF 旋转、alpha 转遮罩）与上游一致。
- 图像选择器迁移自 [Comfyui_LG_Tools](https://github.com/LAOGOU-666/Comfyui_LG_Tools) 的 ImageSelector，交互逻辑保持一致，并删除了 `keep_last_selection` 模式。
- 新增节点使用 V3 API（`io.ComfyNode` / `io.Schema` / `io.NodeOutput`）；图像选择器为交互式输出节点，保留 V1 写法。

## 自测

仓库内带一份自测脚本，覆盖 schema、尺寸算法、各格式保存、元数据开关、仅预览、i18n 结构等：

```bash
cd ComfyUI
python custom_nodes/ComfyUI-MKnode/_selftest.py
```

脚本会在 `input/` 临时生成测试图并自行清理。

## 许可

[MIT](LICENSE)
