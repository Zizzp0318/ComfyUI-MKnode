# ComfyUI-MKnode

MK 系列 ComfyUI 自定义节点合集：图像加载 / 选择 / 保存、提示词拼接。

所有节点都在 **`MK节点`** 分类下。

## 节点一览

| 节点 | 说明 |
| --- | --- |
| MK-加载图像 | 加载图像，可按目标总像素等比缩放 |
| MK-图像选择器 | 执行时暂停，手动挑选图像后再继续 |
| MK-图像裁剪 | 按位置与偏移裁剪图像，输出实际裁剪起点坐标 |
| MK-提示词拼接 | 把多段提示词按分隔符拼成一条，输入端可动态增减 |
| MK-图像保存 | 保存图像，支持 PNG / JPEG / WEBP |

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Zizzp0318/ComfyUI-MKnode.git
pip install -r ComfyUI-MKnode/requirements.txt
```

重启 ComfyUI 即可。本包不需要额外依赖，`requirements.txt` 只是空占位，保证上面的 `pip install` 命令依然可用。

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

### MK-图像裁剪

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 图像 | — | 待裁剪的图像，支持批量（批次内每张图用同一组参数） |
| 宽度 | 256 | 裁剪宽度，步长 8。超过原图宽度时自动收敛到原图宽度 |
| 高度 | 256 | 裁剪高度，步长 8。超过原图高度时自动收敛到原图高度 |
| 位置 | 左上角 | 左上角 / 上方居中 / 右上角 / 右侧居中 / 右下角 / 下方居中 / 左下角 / 左侧居中 / 居中 |
| X 轴偏移 | 0 | 在基准位置之上再横向移动，可为负 |
| Y 轴偏移 | 0 | 在基准位置之上再纵向移动，可为负 |

输出：`图像`（裁剪结果）、`X 坐标`、`Y 坐标`（实际裁剪起点，已过边界检查）。

- 裁剪尺寸超过原图时自动收敛到原图尺寸，不会报错。
- 越界时把裁剪框夹回图像范围内，**但不会据此重算尺寸**——因此负偏移会让结果变小，而不是把窗口平移出去。这与上游 `ImageCrop+` 的行为一致，刻意保留。

> 裁剪节点迁移自 [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) 的 `ImageCrop+`。
> 为兼容源包已保存的工作流，节点 id（`MK_ImageCrop`）、内部输入 id（`图像`、`宽度`…）
> 与「位置」的选项值都保持中文原样，与包内其他节点「内部 id 用英文」的约定不同。

### MK-提示词拼接

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 分隔符 | `, ` | 连接各段提示词的字符串 |
| 提示词 01 ~ 10 | 空 | 待拼接的提示词，**只能连线**，不提供文本框 |

输出：`提示词`（拼接结果）。

- 输入端是动态的：连满当前输入后节点会自动补一个空槽，最多 10 个；断开末尾输入会自动收起。
- 空输入（未连接或空串）不参与拼接，因此最终结果里不会出现多余的分隔符。

> 拼接节点迁移自 [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) 的 `easy promptConcat`。
> 为兼容源包已保存的工作流，节点 id（`MK_PromptConcat`）与内部输入 id（`分隔符`、`提示词_01`…）
> 都保持了原样，与包内其他节点「内部 id 用英文」的约定不同。

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

## 说明

- 图像加载直接复用官方 `LoadImage` 的加载逻辑，保证 pyav / Pillow 两条路径（含动画 WebP 回退、EXIF 旋转、alpha 转遮罩）与上游一致。
- 图像选择器迁移自 [Comfyui_LG_Tools](https://github.com/LAOGOU-666/Comfyui_LG_Tools) 的 ImageSelector，交互逻辑保持一致，并删除了 `keep_last_selection` 模式。
- 图像裁剪迁移自 [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) 的 `ImageCrop+`，坐标计算与边界处理逐行保持上游行为。
- 提示词拼接迁移自 [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) 的 `easy promptConcat`，节点 id 与内部输入 id 保持原样以兼容源包工作流。
- 新增节点使用 V3 API（`io.ComfyNode` / `io.Schema` / `io.NodeOutput`）；图像选择器（交互式输出）与提示词拼接（依赖未声明的动态输入）保留 V1 写法。

## 自测

仓库内带一份自测脚本，覆盖 schema、尺寸算法、裁剪坐标、各格式保存、元数据开关、仅预览、i18n 结构等：

```bash
cd ComfyUI
python custom_nodes/ComfyUI-MKnode/_selftest.py
```

脚本会在 `input/` 下生成并复用测试图（`mk_test_alpha.png` / `mk_test_noalpha.jpg`），**不会自动删除**——介意的话跑完手动清理。

## 许可

[MIT](LICENSE)
