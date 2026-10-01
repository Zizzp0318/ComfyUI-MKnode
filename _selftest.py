import math
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "custom_nodes")

import numpy as np
from PIL import Image

# 自备测试数据，保证脚本可重复运行
ALPHA_PNG = "mk_test_alpha.png"
NOALPHA_JPG = "mk_test_noalpha.jpg"
if not (os.path.exists(os.path.join("input", ALPHA_PNG)) and os.path.exists(os.path.join("input", NOALPHA_JPG))):
    _rgb = np.random.randint(0, 255, (600, 900, 3), dtype=np.uint8)
    _a = np.random.randint(0, 255, (600, 900), dtype=np.uint8)
    Image.fromarray(np.dstack([_rgb, _a]), "RGBA").save(os.path.join("input", ALPHA_PNG))
    Image.fromarray(_rgb, "RGB").save(os.path.join("input", NOALPHA_JPG), quality=90)
    print("[fixture] 已生成测试图 900x600（带 alpha / 不带 alpha）")

import Comfyui_MKnode as pkg
from Comfyui_MKnode.nodes.load_image import MKLoadImage, _compute_target_size

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  <-- {detail}"))
    if not cond:
        fails.append(label)


print("=== 1. schema 构建与校验 ===")
schema = MKLoadImage.GET_SCHEMA()
print("  node_id     :", schema.node_id)
print("  display_name:", schema.display_name)
print("  category    :", schema.category)
print("  inputs      :", [i.id for i in schema.inputs])
print("  outputs     :", [(o.id, o.display_name) for o in schema.outputs])
check("node_id 正确", schema.node_id == "MK_LoadImage", schema.node_id)
check("display_name 为 MK-加载图像", schema.display_name == "MK-加载图像", schema.display_name)
check("输入数量为 5", len(schema.inputs) == 5)
check("输出数量为 4", len(schema.outputs) == 4)
check("输出顺序 IMAGE/MASK/WIDTH/HEIGHT", [o.id for o in schema.outputs] == ["IMAGE", "MASK", "WIDTH", "HEIGHT"])

print()
print("=== 2. 目标尺寸算法 ===")
cases = [
    # (w, h, mp, multiple, 期望)
    (900, 600, 1.0, 1, None),
    (900, 600, 1.0, 64, None),
    (1000, 1000, 1.0, 1, (1000, 1000)),
    (1000, 1000, 4.0, 1, (2000, 2000)),
    (1000, 1000, 0.25, 1, (500, 500)),
    (1000, 1000, 1.0, 64, (1024, 1024)),
]
for w, h, mp, mult, expect in cases:
    nw, nh = _compute_target_size(w, h, mp, mult)
    ratio_in = w / h
    ratio_out = nw / nh
    pixels = nw * nh
    print(f"  {w}x{h} mp={mp} mult={mult} -> {nw}x{nh}  pixels={pixels:,}  比例偏差={abs(ratio_out - ratio_in) / ratio_in:.4%}")
    if expect:
        check(f"  {w}x{h} mp={mp} mult={mult} 精确匹配", (nw, nh) == expect, f"got {(nw, nh)}")
    if mult > 1:
        check(f"  {w}x{h} mult={mult} 可被整除", nw % mult == 0 and nh % mult == 0, f"{(nw, nh)}")

print()
print("=== 3. execute 全分支（含 alpha 与无 alpha）===")
methods = ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]
from nodes import LoadImage as _NativeRef

for fname in ["mk_test_alpha.png", "mk_test_noalpha.jpg"]:
    print(f"  --- {fname} ---")
    native_mask_shape = tuple(_NativeRef().load_image(fname)[1].shape)
    for mode, mp, mult in [("禁用", 1.0, 1), ("按总像素", 1.0, 1), ("按总像素", 0.25, 64)]:
        for method in methods:
            try:
                imgs, mask, w, h = MKLoadImage.execute(
                    image=fname,
                    resize_mode=mode,
                    target_megapixels=mp,
                    size_multiple=mult,
                    upscale_method=method,
                ).result
                # 语义：禁用模式遮罩保持原生形状；缩放模式遮罩必须跟随输出图像尺寸
                expect_mask = native_mask_shape if mode == "禁用" else (mask.shape[0], h, w)
                ok = (
                    tuple(imgs.shape[1:3]) == (h, w)
                    and imgs.shape[-1] == 3
                    and tuple(mask.shape) == tuple(expect_mask)
                    and mask.shape[0] == imgs.shape[0]
                )
                print(f"    {mode:6s} mp={mp:<5} mult={mult:<3} {method:14s} img={tuple(imgs.shape)} mask={tuple(mask.shape)} -> {'OK' if ok else 'MISMATCH 期望'+str(expect_mask)}")
                if not ok:
                    fails.append(f"{fname} {mode} {method}")
            except Exception as e:
                print(f"    {mode:6s} mp={mp:<5} mult={mult:<3} {method:14s} ERROR {type(e).__name__}: {e}")
                fails.append(f"{fname} {mode} {method} raised")

print()
print("=== 4. 禁用模式必须与原生 LoadImage 完全一致 ===")
from nodes import LoadImage as Native

for fname in ["mk_test_alpha.png", "mk_test_noalpha.jpg"]:
    n_img, n_mask = Native().load_image(fname)
    o_img, o_mask, w, h = MKLoadImage.execute(fname, "禁用", 1.0, 1, "lanczos").result
    same_img = bool((n_img == o_img).all()) and n_img.shape == o_img.shape
    same_mask = bool((n_mask == o_mask).all()) and n_mask.shape == o_mask.shape
    print(f"  {fname}: image 一致={same_img} mask 一致={same_mask}  WIDTH/HEIGHT={w}x{h} 原生={n_img.shape[2]}x{n_img.shape[1]}")
    check(f"  {fname} 图像与原生一致", same_img)
    check(f"  {fname} 遮罩与原生一致", same_mask)
    check(f"  {fname} 宽高输出正确", (w, h) == (n_img.shape[2], n_img.shape[1]))

print()
print("=== 5. fingerprint / validate ===")
fp1 = MKLoadImage.fingerprint_inputs("mk_test_alpha.png", "禁用", 1.0, 1, "lanczos")
fp2 = MKLoadImage.fingerprint_inputs("mk_test_alpha.png", "按总像素", 4.0, 64, "area")
print("  fingerprint 同文件不同参数一致:", fp1 == fp2)
check("  fingerprint 为文件哈希(与参数无关)", fp1 == fp2)
check("  validate 合法文件返回 True", MKLoadImage.validate_inputs("mk_test_alpha.png", "禁用", 1.0, 1, "lanczos") is True)
bad = MKLoadImage.validate_inputs("__not_exist__.png", "禁用", 1.0, 1, "lanczos")
print("  validate 非法文件返回:", repr(bad))
check("  validate 非法文件返回错误串", isinstance(bad, str))

print()
print("=== 6. 注册入口 ===")
mappings = pkg.NODE_CLASS_MAPPINGS
print("  NODE_CLASS_MAPPINGS  :", list(mappings.keys()))
print("  NODE_DISPLAY_NAME    :", pkg.NODE_DISPLAY_NAME_MAPPINGS)
check("  注册了 MK_LoadImage", "MK_LoadImage" in mappings)
check("  注册了 MK_ImageSelector", "MK_ImageSelector" in mappings)
check("  MK_LoadImage 指向本模块的类", mappings.get("MK_LoadImage") is MKLoadImage)
check("  显示名映射与类映射一一对应",
      set(pkg.NODE_DISPLAY_NAME_MAPPINGS) == set(mappings),
      f"{set(pkg.NODE_DISPLAY_NAME_MAPPINGS)} vs {set(mappings)}")

pkg_dir = os.path.dirname(os.path.abspath(pkg.__file__))
web_dir = os.path.join(pkg_dir, pkg.WEB_DIRECTORY.lstrip("./"))
print("  WEB_DIRECTORY        :", pkg.WEB_DIRECTORY, "->", web_dir)
check("  WEB_DIRECTORY 目录存在", os.path.isdir(web_dir), web_dir)
check("  前端 JS 存在", os.path.isfile(os.path.join(web_dir, "image_selector.js")))

print()
print("=== 7. 图像选择器（V1）契约 ===")
from Comfyui_MKnode.nodes.image_selector import MKImageSelector, ROUTE_SELECT, EVENT_UPDATE, EVENT_SELECTION

it = MKImageSelector.INPUT_TYPES()
print("  INPUT_TYPES required :", list(it["required"].keys()))
print("  INPUT_TYPES hidden   :", list(it["hidden"].keys()))
print("  RETURN_TYPES         :", MKImageSelector.RETURN_TYPES, MKImageSelector.RETURN_NAMES)
print("  OUTPUT_NODE/IS_LIST  :", MKImageSelector.OUTPUT_NODE, MKImageSelector.OUTPUT_IS_LIST, MKImageSelector.INPUT_IS_LIST)
print("  路由                 :", ROUTE_SELECT)
print("  事件                 :", EVENT_UPDATE, "/", EVENT_SELECTION)
check("  mode 选项已移除 keep_last_selection",
      it["required"]["mode"][0] == ["always_pause", "passthrough"],
      str(it["required"]["mode"][0]))
check("  hidden 含 prompt/unique_id/extra_pnginfo",
      set(it["hidden"]) == {"prompt", "unique_id", "extra_pnginfo"})
check("  返回类型 IMAGE/STRING", MKImageSelector.RETURN_TYPES == ("IMAGE", "STRING"))
check("  是输出节点且输入取列表", MKImageSelector.OUTPUT_NODE and MKImageSelector.INPUT_IS_LIST)
check("  输出为列表(仅第1路)", MKImageSelector.OUTPUT_IS_LIST == (True, False))
check("  分类为 MK节点", MKImageSelector.CATEGORY == "MK节点")

# 路由/事件必须与源包隔离，否则 aiohttp 重复注册会报错
check("  路由带 mk_ 前缀（避免与 LG_Tools 冲突）", ROUTE_SELECT.startswith("/mk_"), ROUTE_SELECT)
check("  事件名带 mk_ 前缀", EVENT_UPDATE.startswith("mk_") and EVENT_SELECTION.startswith("mk_"))

lg_route = os.path.join(os.path.dirname(pkg_dir), "Comfyui_LG_Tools", "py", "image_selector.py")
if os.path.isfile(lg_route):
    with open(lg_route, encoding="utf-8") as f:
        lg_src = f.read()
    check("  路由确实与源包不同", ROUTE_SELECT not in lg_src)
    check("  源包仍在（用户要求保留）", True)

print()
print("=== 8. 中文语言包（locales/zh/nodeDefs.json）===")
import json

loc_path = os.path.join(pkg_dir, "locales", "zh", "nodeDefs.json")
check("  语言包文件存在", os.path.isfile(loc_path), loc_path)
if os.path.isfile(loc_path):
    with open(loc_path, encoding="utf-8") as f:
        loc = json.load(f)  # 顺带验证 JSON 合法性

    # 顶层键必须是 object_info 里的节点名，否则前端匹配不上
    check("  顶层键为 MK_ImageSelector", list(loc.keys()) == ["MK_ImageSelector"], str(list(loc.keys())))
    node_loc = loc.get("MK_ImageSelector", {})

    req_ids = set(it["required"].keys())
    loc_input_ids = set(node_loc.get("inputs", {}).keys())
    print("  已翻译输入 :", sorted(loc_input_ids))
    print("  未翻译输入 :", sorted(req_ids - loc_input_ids) or "无")
    check("  输入 id 全部存在", loc_input_ids <= req_ids,
          f"多余: {loc_input_ids - req_ids}")

    # 输出按索引翻译（官方文档：第一个输出为 "0"）
    n_out = len(MKImageSelector.RETURN_TYPES)
    loc_out = node_loc.get("outputs", {})
    check(f"  输出按索引 0..{n_out - 1} 翻译",
          set(loc_out.keys()) == {str(i) for i in range(n_out)},
          str(sorted(loc_out.keys())))

    # COMBO 选项标签翻译：官方文档列了 inputs.<id>.options 字段，但前端 1.53.6 未实现
    # （证据：15 个官方语言包中无一使用该字段，唯一命中是 advanced_options 这个输入 id 的误报）。
    # 故选项值保持英文，这里断言不要误加无效配置。
    opt_loc = node_loc.get("inputs", {}).get("mode", {}).get("options")
    actual_opts = it["required"]["mode"][0]
    print("  模式选项（界面直接显示英文值）:", actual_opts)
    check("  mode 未配置无效的 options 翻译（前端不支持该字段）",
          opt_loc is None, str(opt_loc))

    check("  节点 display_name 与注册一致",
          node_loc.get("display_name") == pkg.NODE_DISPLAY_NAME_MAPPINGS["MK_ImageSelector"],
          f"{node_loc.get('display_name')!r} vs {pkg.NODE_DISPLAY_NAME_MAPPINGS['MK_ImageSelector']!r}")

    # 源码中不应再有任何 keep_last_selection 的代码引用
    # （注释里提到该词是允许的，所以只匹配带引号的字符串字面量）
    for rel in ("nodes/image_selector.py", "web/image_selector.js"):
        with open(os.path.join(pkg_dir, rel), encoding="utf-8") as f:
            src = f.read()
        check(f"  {rel} 无 keep_last_selection 代码引用",
              '"keep_last_selection"' not in src and "'keep_last_selection'" not in src)

print()
print("=== 9. 图像保存节点（MK_SaveImage）===")
import shutil
import tempfile

import folder_paths
import torch
from PIL import Image as PILImage

from comfy_api.latest._io import HiddenHolder
from Comfyui_MKnode.nodes.save_image import EXTENSIONS, IMAGE_FORMATS, MKSaveImage

s9 = MKSaveImage.GET_SCHEMA()
print("  node_id      :", s9.node_id)
print("  display_name :", s9.display_name)
print("  inputs       :", [(i.id, getattr(i, "display_name", None)) for i in s9.inputs])
check("  node_id 为 MK_SaveImage", s9.node_id == "MK_SaveImage", s9.node_id)
check("  显示名为 MK-图像保存", s9.display_name == "MK-图像保存", s9.display_name)
check("  分类为 MK节点", s9.category == "MK节点", s9.category)
check("  是输出节点", s9.is_output_node is True)
check("  输入齐全",
      [i.id for i in s9.inputs] == ["images", "filename_prefix", "image_format",
                                    "quality", "save_metadata", "preview_only"],
      str([i.id for i in s9.inputs]))
check("  输出为 images", [o.id for o in s9.outputs] == ["images"])
check("  hidden 含 prompt/extra_pnginfo",
      set(h.name for h in s9.hidden) == {"prompt", "extra_pnginfo"},
      str([h.name for h in s9.hidden]))

v1 = MKSaveImage.INPUT_TYPES()["required"]
print("  默认值       : format=%s quality=%s metadata=%s preview_only=%s" % (
    v1["image_format"][1]["default"], v1["quality"][1]["default"],
    v1["save_metadata"][1]["default"], v1["preview_only"][1]["default"]))
# V3 的 Combo 经 V1 兼容层转换后是 ["COMBO", {"options": [...]}]，选项在 options 里
fmt_opts = v1["image_format"][1].get("options")
print("  格式选项     :", fmt_opts)
check("  格式选项 PNG/JPEG/WEBP", fmt_opts == ["PNG", "JPEG", "WEBP"], str(fmt_opts))
check("  格式默认 PNG", v1["image_format"][1]["default"] == "PNG")
check("  质量默认 95 且范围 1-100",
      v1["quality"][1]["default"] == 95 and v1["quality"][1]["min"] == 1 and v1["quality"][1]["max"] == 100)
check("  保存元数据默认关", v1["save_metadata"][1]["default"] is False)
check("  仅预览默认关", v1["preview_only"][1]["default"] is False)

# --- 用临时目录替代真实 output/temp，避免污染用户环境 ---
tmp_out = tempfile.mkdtemp(prefix="mk_save_out_")
tmp_tmp = tempfile.mkdtemp(prefix="mk_save_tmp_")
_orig_out, _orig_tmp = folder_paths.get_output_directory, folder_paths.get_temp_directory
folder_paths.get_output_directory = lambda: tmp_out
folder_paths.get_temp_directory = lambda: tmp_tmp

PROMPT = {"1": {"class_type": "MK_SaveImage", "inputs": {}}}
EXTRA = {"workflow": {"nodes": [], "extra": {"ds": {"scale": 1}}}}


def make_cls(prompt=None, extra=None):
    """构造带 hidden 的类克隆，模拟执行器注入。"""
    clone = MKSaveImage.PREPARE_CLASS_CLONE(None)
    clone.hidden = HiddenHolder(
        unique_id="1", prompt=prompt, extra_pnginfo=extra, dynprompt=None,
        auth_token_comfy_org=None, api_key_comfy_org=None,
    )
    return clone


def make_tensor(w=48, h=32, value=0.5, noise=False):
    if noise:
        # 噪声图才能体现压缩质量差异；纯色图无论质量高低都压得极小
        return torch.rand((1, h, w, 3), dtype=torch.float32)
    return torch.full((1, h, w, 3), value, dtype=torch.float32)


try:
    # 1) 三种格式都能落盘且可重新打开
    for fmt in IMAGE_FORMATS:
        out = make_cls().execute(
            images=make_tensor(), filename_prefix=f"fmt_{fmt}", image_format=fmt,
            quality=95, save_metadata=False, preview_only=False,
        )
        imgs, res = out.result[0], out.ui["images"][0]
        path = os.path.join(tmp_out, res["filename"])
        ok_ext = res["filename"].endswith("." + EXTENSIONS[fmt])
        opened = PILImage.open(path)
        ok_size = opened.size == (48, 32)
        print(f"  {fmt:5s} -> {res['filename']}  尺寸={opened.size}  type={res['type']}")
        check(f"  {fmt} 扩展名正确", ok_ext, res["filename"])
        check(f"  {fmt} 尺寸正确", ok_size, str(opened.size))
        check(f"  {fmt} 透传 images", imgs.shape == (1, 32, 48, 3))
        check(f"  {fmt} 写入 output 目录", res["type"] == "output")

    # 2) 质量参数对 JPEG / WEBP 生效（必须用噪声图，纯色图压缩后大小几乎不随质量变化）
    for fmt in ("JPEG", "WEBP"):
        sizes = {}
        for q in (10, 95):
            r = make_cls().execute(
                images=make_tensor(w=256, h=256, noise=True), filename_prefix=f"q_{fmt}_{q}",
                image_format=fmt, quality=q, save_metadata=False, preview_only=False,
            ).ui["images"][0]
            sizes[q] = os.path.getsize(os.path.join(tmp_out, r["filename"]))
        print(f"  {fmt} 质量 10 -> {sizes[10]:,}B ; 质量 95 -> {sizes[95]:,}B")
        check(f"  {fmt} 质量生效（高质量文件明显更大）", sizes[95] > sizes[10] * 2, str(sizes))

    # 3) 元数据开关
    r_off = make_cls(PROMPT, EXTRA).execute(
        images=make_tensor(), filename_prefix="meta_off", image_format="PNG",
        quality=95, save_metadata=False, preview_only=False,
    ).ui["images"][0]
    r_on = make_cls(PROMPT, EXTRA).execute(
        images=make_tensor(), filename_prefix="meta_on", image_format="PNG",
        quality=95, save_metadata=True, preview_only=False,
    ).ui["images"][0]
    txt_off = PILImage.open(os.path.join(tmp_out, r_off["filename"])).info
    txt_on = PILImage.open(os.path.join(tmp_out, r_on["filename"])).info
    print("  元数据关 -> PNG 文本块:", [k for k in txt_off if k in ("prompt", "workflow")] or "无")
    print("  元数据开 -> PNG 文本块:", [k for k in txt_on if k in ("prompt", "workflow")])
    check("  关闭时 PNG 不写元数据", "prompt" not in txt_off and "workflow" not in txt_off)
    check("  开启时 PNG 写入 prompt", "prompt" in txt_on)
    check("  开启时 PNG 写入 workflow", "workflow" in txt_on)

    r_jpg = make_cls(PROMPT, EXTRA).execute(
        images=make_tensor(), filename_prefix="meta_jpg", image_format="JPEG",
        quality=95, save_metadata=True, preview_only=False,
    ).ui["images"][0]
    exif = PILImage.open(os.path.join(tmp_out, r_jpg["filename"])).getexif()
    has_comment = 0x9286 in exif
    print("  元数据开 -> JPEG EXIF UserComment:", "有" if has_comment else "无")
    check("  开启时 JPEG 写入 EXIF", has_comment)

    r_webp = make_cls(PROMPT, EXTRA).execute(
        images=make_tensor(), filename_prefix="meta_webp", image_format="WEBP",
        quality=95, save_metadata=True, preview_only=False,
    ).ui["images"][0]
    exif_w = PILImage.open(os.path.join(tmp_out, r_webp["filename"])).getexif()
    print("  元数据开 -> WEBP EXIF UserComment:", "有" if 0x9286 in exif_w else "无")
    check("  开启时 WEBP 写入 EXIF", 0x9286 in exif_w)

    # 4) 仅预览：写 temp 且不碰 output
    before_out = set(os.listdir(tmp_out))
    r_prev = make_cls().execute(
        images=make_tensor(), filename_prefix="prev", image_format="PNG",
        quality=95, save_metadata=False, preview_only=True,
    ).ui["images"][0]
    after_out = set(os.listdir(tmp_out))
    print(f"  仅预览 -> {r_prev['filename']}  type={r_prev['type']}")
    check("  仅预览写入 temp 目录", r_prev["type"] == "temp")
    check("  仅预览文件确实在 temp 目录",
          os.path.isfile(os.path.join(tmp_tmp, r_prev["filename"])))
    check("  仅预览不写 output 目录", before_out == after_out,
          str(after_out - before_out))

    # 5) 文件名占位符与计数递增
    r_a = make_cls().execute(images=make_tensor(), filename_prefix="seq",
                             image_format="PNG", quality=95,
                             save_metadata=False, preview_only=False).ui["images"][0]
    r_b = make_cls().execute(images=make_tensor(), filename_prefix="seq",
                             image_format="PNG", quality=95,
                             save_metadata=False, preview_only=False).ui["images"][0]
    print("  连续保存:", r_a["filename"], "->", r_b["filename"])
    check("  计数递增不覆盖", r_a["filename"] != r_b["filename"])

    r_w = make_cls().execute(images=make_tensor(w=48, h=32), filename_prefix="dim_%width%x%height%",
                             image_format="PNG", quality=95,
                             save_metadata=False, preview_only=False).ui["images"][0]
    print("  %width%/%height% 替换:", r_w["filename"])
    check("  %width%/%height% 占位符生效", "dim_48x32" in r_w["filename"], r_w["filename"])
finally:
    folder_paths.get_output_directory = _orig_out
    folder_paths.get_temp_directory = _orig_tmp
    shutil.rmtree(tmp_out, ignore_errors=True)
    shutil.rmtree(tmp_tmp, ignore_errors=True)

print()
print("=== 10. 视频节点（MK_LoadVideo / MK_SaveVideo）===")
from Comfyui_MKnode.nodes.video import MKLoadVideo, MKSaveVideo

lv = MKLoadVideo.GET_SCHEMA()
print("  MKLoadVideo :", lv.node_id, "|", lv.display_name, "|", lv.category,
      "| intermediate =", lv.has_intermediate_output)
print("    inputs :", [(i.id, getattr(i, "display_name", None)) for i in lv.inputs])
print("    outputs:", [(o.id, getattr(o, "display_name", None)) for o in lv.outputs])
check("  加载视频 node_id 正确", lv.node_id == "MK_LoadVideo", lv.node_id)
check("  加载视频显示名正确", lv.display_name == "MK-加载视频", lv.display_name)
check("  加载视频分类为 MK节点", lv.category == "MK节点")
check("  加载视频保留 intermediate 输出", lv.has_intermediate_output is True)
check("  加载视频输入为 file", [i.id for i in lv.inputs] == ["file"])
check("  加载视频输出为 video", [o.id for o in lv.outputs] == ["video"])

lv_v1 = MKLoadVideo.INPUT_TYPES()["required"]["file"][1]
print("    上传标记 image_upload/video_upload:", {k: v for k, v in lv_v1.items() if "upload" in k})
check("  加载视频启用视频上传", lv_v1.get("video_upload") is True, str(lv_v1))

sv = MKSaveVideo.GET_SCHEMA()
print("  MKSaveVideo :", sv.node_id, "|", sv.display_name, "|", sv.category,
      "| output_node =", sv.is_output_node)
print("    inputs :", [(i.id, getattr(i, "display_name", None)) for i in sv.inputs])
print("    outputs:", [(o.id, getattr(o, "display_name", None)) for o in sv.outputs])
check("  保存视频 node_id 正确", sv.node_id == "MK_SaveVideo", sv.node_id)
check("  保存视频显示名正确", sv.display_name == "MK-保存视频", sv.display_name)
check("  保存视频是输出节点", sv.is_output_node is True)
check("  保存视频输入含 video/filename_prefix/format",
      [i.id for i in sv.inputs][:3] == ["video", "filename_prefix", "format"],
      str([i.id for i in sv.inputs]))
check("  保存视频 hidden 含 prompt/extra_pnginfo",
      {h.name for h in sv.hidden} == {"prompt", "extra_pnginfo"},
      str([h.name for h in sv.hidden]))

# format 是 DynamicCombo，确认容器选项齐全
fmt_in = next(i for i in sv.inputs if i.id == "format")
fmt_opts = getattr(fmt_in, "options", None)
fmt_names = [getattr(o, "key", None) or getattr(o, "value", None) or o for o in (fmt_opts or [])]
print("    format 容器选项:", fmt_names)
check("  format 含 auto/mp4/mkv/webm",
      fmt_names == ["auto", "mp4", "mkv", "webm"], str(fmt_names))

# 注册表
check("  两个视频节点都已注册",
      "MK_LoadVideo" in pkg.NODE_CLASS_MAPPINGS and "MK_SaveVideo" in pkg.NODE_CLASS_MAPPINGS)
check("  视频节点显示名已登记",
      pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_LoadVideo") == "MK-加载视频"
      and pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_SaveVideo") == "MK-保存视频")

print()
print("=== 11. 视频节点尺寸修复脚本 ===")
js_path = os.path.join(pkg_dir, "web", "video_node_resize.js")
check("  修复脚本存在", os.path.isfile(js_path), js_path)
if os.path.isfile(js_path):
    with open(js_path, encoding="utf-8") as f:
        js = f.read()
    check("  挂接的控件名与官方一致（video-preview）",
          '"video-preview"' in js, "未找到 video-preview")
    for nid in ("MK_LoadVideo", "MK_SaveVideo", "LoadVideo", "SaveVideo"):
        check(f"  覆盖节点 {nid}", f'"{nid}"' in js)
    check("  minWidth 不再施加约束", "minWidth: 0" in js)
    check("  通过 addDOMWidget 挂钩", "addDOMWidget" in js)
    check("  Vue 模式下按当前宽度实时换算", "vueNodesMode" in js)

    # 官方是在 addDOMWidget 返回之后【又赋值一次】computeLayoutSize，
    # 所以必须用访问器接管，直接赋值会被冲掉（这是之前失效的原因）
    check("  用 Object.defineProperty 访问器接管 computeLayoutSize",
          "Object.defineProperty(widget" in js and "get:" in js and "set:" in js)
    check("  未使用 writable:false（ES 模块严格模式下官方赋值会抛错）",
          "writable" not in js)
    check("  最小高度是固定常量，不由视频尺寸推导",
          "MIN_PREVIEW_HEIGHT = 256" in js)

print()
print("=== 12. 视频加载（高级）===")
import av

from Comfyui_MKnode.nodes.video_load_advanced import (
    MK_UPLOAD_SUBFOLDER,
    ROUTE_VIDEO_METADATA,
    MKVideoLoadAdvanced,
    _list_input_videos,
    _target_video_size,
)

va = MKVideoLoadAdvanced.GET_SCHEMA()
print("  node_id      :", va.node_id)
print("  display_name :", va.display_name)
print("  inputs       :", [(i.id, getattr(i, "display_name", None)) for i in va.inputs])
print("  outputs      :", [(o.id, getattr(o, "display_name", None)) for o in va.outputs])
check("  node_id 正确", va.node_id == "MK_VideoLoadAdvanced", va.node_id)
check("  显示名为 MK-视频加载（高级）", va.display_name == "MK-视频加载（高级）", va.display_name)
check("  分类为 MK节点", va.category == "MK节点", va.category)
check("  输入齐全",
      [i.id for i in va.inputs] == ["video", "force_rate", "custom_width", "custom_height",
                                    "frame_load_cap", "skip_first_frames", "select_every_nth",
                                    "preview_fps", "delete_after_load"],
      str([i.id for i in va.inputs]))
check("  输出 5 路", [o.id for o in va.outputs] ==
      ["images", "frame_count", "audio", "video_info", "vhs_video_info"],
      str([o.id for o in va.outputs]))
check("  所有输入都有中文显示名",
      all(getattr(i, "display_name", None) for i in va.inputs),
      str([(i.id, getattr(i, "display_name", None)) for i in va.inputs]))
check("  路由已加 mk_ 前缀", ROUTE_VIDEO_METADATA.startswith("/mk_"), ROUTE_VIDEO_METADATA)
check("  上传目录已改名", MK_UPLOAD_SUBFOLDER == "mk_video_uploads", MK_UPLOAD_SUBFOLDER)

# 只给一边时按比例推算另一边
size_cases = [
    ((1920, 1080, 0, 0), (1920, 1080)),
    ((1920, 1080, 640, 0), (640, 360)),
    ((1920, 1080, 0, 360), (640, 360)),
    ((1920, 1080, 800, 600), (800, 600)),
]
for args, expect in size_cases:
    got = _target_video_size(*args)
    print(f"  _target_video_size{args} -> {got}")
    check(f"  尺寸推算 {args[2]}x{args[3]}", got == expect, f"得到 {got} 期望 {expect}")

# --- 造测试视频并跑真实取帧 ---
test_video = "mk_test_adv.mp4"
video_abs = os.path.join("input", test_video)
container = av.open(video_abs, mode="w")
stream = container.add_stream("libx264", rate=24)
stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
for i in range(24):
    arr = np.full((48, 64, 3), (i * 10) % 256, dtype=np.uint8)
    for pkt in stream.encode(av.VideoFrame.from_ndarray(arr, format="rgb24")):
        container.mux(pkt)
for pkt in stream.encode():
    container.mux(pkt)
container.close()
print(f"  [fixture] 生成测试视频 24 帧 64x48 -> {test_video}")

try:
    check("  _list_input_videos 能列出测试视频", test_video in _list_input_videos(),
          str(_list_input_videos()[:5]))

    def run(**kw):
        args = dict(video=test_video, force_rate=0, custom_width=0, custom_height=0,
                    frame_load_cap=0, skip_first_frames=0, select_every_nth=1,
                    preview_fps=24, delete_after_load=False)
        args.update(kw)
        return MKVideoLoadAdvanced.execute(**args).result

    imgs, count, audio, vinfo, _ = run()
    print(f"  全量加载: images={tuple(imgs.shape)} count={count} "
          f"audio={tuple(audio['waveform'].shape)}@{audio['sample_rate']}")
    check("  全量加载帧数正确", count == 24, str(count))
    check("  图像形状为 (N,H,W,3)", tuple(imgs.shape) == (24, 48, 64, 3), str(tuple(imgs.shape)))
    check("  帧数输出与图像一致", count == imgs.shape[0])
    check("  音频为 waveform/sample_rate 结构",
          "waveform" in audio and "sample_rate" in audio, str(list(audio.keys())))
    check("  视频信息字段齐全",
          {"source_fps", "loaded_fps", "loaded_frame_count", "loaded_width", "loaded_height"}
          <= set(vinfo), str(sorted(vinfo.keys())))
    check("  图像值域在 0~1", float(imgs.min()) >= 0.0 and float(imgs.max()) <= 1.0,
          f"min={float(imgs.min())} max={float(imgs.max())}")

    _, c2, _, _, _ = run(frame_load_cap=5)
    print("  frame_load_cap=5 ->", c2)
    check("  最大加载帧数生效", c2 == 5, str(c2))

    _, c3, _, _, _ = run(select_every_nth=2)
    print("  select_every_nth=2 ->", c3)
    check("  隔帧抽取生效", c3 == 12, str(c3))

    _, c4, _, _, _ = run(skip_first_frames=10)
    print("  skip_first_frames=10 ->", c4)
    check("  跳过开头帧生效", c4 == 14, str(c4))

    imgs5, _, _, v5, _ = run(custom_width=32)
    print("  custom_width=32 ->", tuple(imgs5.shape), "| info", v5["loaded_width"], "x", v5["loaded_height"])
    check("  只给宽度时高度按比例", tuple(imgs5.shape) == (24, 24, 32, 3), str(tuple(imgs5.shape)))

    imgs6, _, _, v6, _ = run(custom_width=96, custom_height=96)
    check("  宽高都指定时精确匹配", tuple(imgs6.shape) == (24, 96, 96, 3), str(tuple(imgs6.shape)))

    # 指纹与校验
    fp = MKVideoLoadAdvanced.fingerprint_inputs(test_video, force_rate=0)
    fp2 = MKVideoLoadAdvanced.fingerprint_inputs(test_video, force_rate=30)
    check("  指纹随参数变化", fp != fp2)
    check("  校验合法文件返回 True",
          MKVideoLoadAdvanced.validate_inputs(test_video) is True)
    bad = MKVideoLoadAdvanced.validate_inputs("__nope__.mp4")
    print("  非法文件校验返回:", repr(bad))
    check("  校验非法文件返回错误串", isinstance(bad, str))
    check("  空文件名校验报错", isinstance(MKVideoLoadAdvanced.validate_inputs(""), str))
finally:
    try:
        os.remove(video_abs)
    except OSError:
        pass

print()
print("=== 12b. 「加载后删除」的安全边界 ===")
from Comfyui_MKnode.nodes.video_load_advanced import _delete_uploaded_video

input_root = folder_paths.get_input_directory()
upload_dir = os.path.join(input_root, MK_UPLOAD_SUBFOLDER)
os.makedirs(upload_dir, exist_ok=True)
inside_rel = f"{MK_UPLOAD_SUBFOLDER}/mk_del_probe.mp4"
inside_abs = os.path.join(input_root, MK_UPLOAD_SUBFOLDER, "mk_del_probe.mp4")
outside_abs = os.path.join(input_root, "mk_del_probe_outside.mp4")

with open(inside_abs, "wb") as f:
    f.write(b"\x00" * 16)
with open(outside_abs, "wb") as f:
    f.write(b"\x00" * 16)

try:
    # 1) 子目录内：应当删除
    ok = _delete_uploaded_video(inside_rel, inside_abs)
    check("  子目录内的文件可被删除", ok is True and not os.path.exists(inside_abs),
          f"返回 {ok} 存在={os.path.exists(inside_abs)}")

    # 2) 子目录外：必须拒绝（破坏性操作的安全底线）
    ok2 = _delete_uploaded_video("mk_del_probe_outside.mp4", outside_abs)
    check("  子目录外的文件拒绝删除", ok2 is False and os.path.exists(outside_abs),
          f"返回 {ok2} 存在={os.path.exists(outside_abs)}")

    # 3) 路径穿越：必须拒绝
    ok3 = _delete_uploaded_video(f"{MK_UPLOAD_SUBFOLDER}/../mk_del_probe_outside.mp4", outside_abs)
    check("  路径穿越尝试被拒绝", ok3 is False and os.path.exists(outside_abs),
          f"返回 {ok3} 存在={os.path.exists(outside_abs)}")
finally:
    for p in (inside_abs, outside_abs):
        try:
            os.remove(p)
        except OSError:
            pass

print()
print("=== 13. 视频加载（高级）前端脚本 ===")
js_adv = os.path.join(pkg_dir, "web", "video_load_advanced.js")
check("  前端脚本存在", os.path.isfile(js_adv), js_adv)
if os.path.isfile(js_adv):
    with open(js_adv, encoding="utf-8") as f:
        js = f.read()
    check("  匹配新节点名", '"MK_VideoLoadAdvanced"' in js)
    check("  不再匹配旧节点名", '"AICoser_LoadVideoUpload"' not in js)
    check("  路由已隔离", "/mk_video_metadata" in js and "/aicoser/video_metadata" not in js)
    check("  上传目录已隔离", '"mk_video_uploads"' in js and '"aicoser_uploads"' not in js)
    check("  DOM 控件名已隔离", '"mk_video_upload"' in js and '"aicoser_video_upload"' not in js)
    check("  扩展名已改", "Comfyui_MKnode.VideoLoadAdvanced" in js)
    for s in ("拖入视频，或点击此处上传", "设置起点", "设置终点", "重置范围",
              "输出 ", "帧率 ", "帧 ", "范围 "):
        check(f"  已汉化「{s.strip()}」", s in js)
    # 不应带入其他节点的 UI 代码
    check("  未带入 BatchLoadImages 的 UI", "createBrowserUI" not in js)
    check("  未带入 VNCCS 的 UI", "createVNCCSVisualUI" not in js)

    # 预览区几何：这几个断言防止「画面变形」和「控件高度无限增长」回归
    check("  video 用 object-fit:contain（不是 fill）",
          "object-fit:contain" in js and "object-fit:fill" not in js)
    check("  预览框用 flex:1 吃掉剩余空间（不是写死高度）",
          "flex:1 1 auto" in js)
    check("  控件用 computeLayoutSize 申请空间（不是 computeSize）",
          "widget.computeLayoutSize" in js and "widget.computeSize" not in js)
    check("  不在 JS 里按节点尺寸反推控件高度",
          "_mkVideoWidgetHeight" not in js)
    check("  容器撑满分配高度", "height:100%" in js)

    # 防止反复中断视频的 /view 流式请求（会导致服务端刷 ConnectionResetError）
    check("  refreshSource 有「同名文件跳过」守卫", "lastLoadedFilename" in js)
    check("  已移除 8 次定时重扫", "for (const delay of" not in js)
    check("  上传后走强制刷新（重传同名文件也要重载）", "refreshSource(true)" in js)

print()
if fails:
    print(f"### 失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print("### 全部通过")
