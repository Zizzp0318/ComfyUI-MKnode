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
check("  注册了 MK_PromptConcat", "MK_PromptConcat" in mappings)
check("  注册了 MK_ImageCrop", "MK_ImageCrop" in mappings)
check("  MK_LoadImage 指向本模块的类", mappings.get("MK_LoadImage") is MKLoadImage)
check("  显示名映射与类映射一一对应",
      set(pkg.NODE_DISPLAY_NAME_MAPPINGS) == set(mappings),
      f"{set(pkg.NODE_DISPLAY_NAME_MAPPINGS)} vs {set(mappings)}")
check("  MK_PromptConcat 显示名为 MK-提示词拼接",
      pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_PromptConcat") == "MK-提示词拼接",
      pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_PromptConcat"))

pkg_dir = os.path.dirname(os.path.abspath(pkg.__file__))
web_dir = os.path.join(pkg_dir, pkg.WEB_DIRECTORY.lstrip("./"))
print("  WEB_DIRECTORY        :", pkg.WEB_DIRECTORY, "->", web_dir)
check("  WEB_DIRECTORY 目录存在", os.path.isdir(web_dir), web_dir)
check("  前端 JS 存在", os.path.isfile(os.path.join(web_dir, "image_selector.js")))
check("  提示词拼接前端 JS 存在", os.path.isfile(os.path.join(web_dir, "prompt_concat.js")))

print()
print("=== 7. 图像选择器契约（V3 节点 + V1 兼容层）===")
from Comfyui_MKnode.nodes.image_selector import MKImageSelector, ROUTE_SELECT, EVENT_UPDATE, EVENT_SELECTION

it = MKImageSelector.INPUT_TYPES()
print("  INPUT_TYPES required :", list(it["required"].keys()))
print("  INPUT_TYPES hidden   :", list(it["hidden"].keys()))
print("  RETURN_TYPES         :", MKImageSelector.RETURN_TYPES, MKImageSelector.RETURN_NAMES)
print("  OUTPUT_NODE/IS_LIST  :", MKImageSelector.OUTPUT_NODE, MKImageSelector.OUTPUT_IS_LIST, MKImageSelector.INPUT_IS_LIST)
print("  路由                 :", ROUTE_SELECT)
print("  事件                 :", EVENT_UPDATE, "/", EVENT_SELECTION)

# V3 节点的 INPUT_TYPES 兼容层与 V1 写法不同：
#   V1 -> ("always_pause", {...})   V3 shim -> ("COMBO", {"options": [...]})
_mode_spec = it["required"]["mode"]
_mode_options = _mode_spec[0] if isinstance(_mode_spec[0], list) else _mode_spec[1].get("options")
check("  mode 选项已移除 keep_last_selection",
      list(_mode_options) == ["always_pause", "passthrough"],
      str(_mode_options))
check("  hidden 含 prompt/unique_id/extra_pnginfo",
      set(it["hidden"]) == {"prompt", "unique_id", "extra_pnginfo"})
check("  返回类型 IMAGE/STRING", tuple(MKImageSelector.RETURN_TYPES) == ("IMAGE", "STRING"))
check("  是输出节点且输入取列表", MKImageSelector.OUTPUT_NODE and MKImageSelector.INPUT_IS_LIST)
check("  输出为列表(仅第1路)", list(MKImageSelector.OUTPUT_IS_LIST) == [True, False])
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
    check("  顶层键含 MK_ImageSelector", "MK_ImageSelector" in loc, str(list(loc.keys())))
    check("  顶层键均为已注册节点 id", set(loc.keys()) <= set(pkg.NODE_CLASS_MAPPINGS),
          f"未知键: {set(loc.keys()) - set(pkg.NODE_CLASS_MAPPINGS)}")
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
print("=== 10. 图像裁剪（MK_ImageCrop）===")
from Comfyui_MKnode.nodes.image_crop import MKImageCrop, POSITIONS, POSITION_KEYWORDS

crop_schema = MKImageCrop.GET_SCHEMA()
print("  node_id      :", crop_schema.node_id)
print("  display_name :", crop_schema.display_name)
print("  category     :", crop_schema.category)
print("  inputs       :", [(i.id, getattr(i, "display_name", None)) for i in crop_schema.inputs])
print("  outputs      :", [(o.id, getattr(o, "display_name", None)) for o in crop_schema.outputs])

check("  node_id 为 MK_ImageCrop", crop_schema.node_id == "MK_ImageCrop", crop_schema.node_id)
check("  显示名为 MK-图像裁剪", crop_schema.display_name == "MK-图像裁剪", crop_schema.display_name)
check("  分类为 MK节点", crop_schema.category == "MK节点", crop_schema.category)
check("  输入 id 保持源包中文原样",
      [i.id for i in crop_schema.inputs] == ["图像", "宽度", "高度", "位置", "X轴偏移", "Y轴偏移"],
      str([i.id for i in crop_schema.inputs]))
check("  输出为 IMAGE/x/y",
      [o.id for o in crop_schema.outputs] == ["IMAGE", "x", "y"],
      str([o.id for o in crop_schema.outputs]))
check("  所有输入都有中文显示名",
      all(getattr(i, "display_name", None) for i in crop_schema.inputs),
      str([(i.id, getattr(i, "display_name", None)) for i in crop_schema.inputs]))
check("  位置选项 9 个且为中文",
      len(POSITIONS) == 9 and POSITIONS[0] == "左上角", str(POSITIONS))
check("  位置选项与方位关键字表一一对应",
      set(POSITIONS) == set(POSITION_KEYWORDS),
      str(set(POSITIONS) ^ set(POSITION_KEYWORDS)))

# 用「像素值编码自身坐标」的图：裁剪结果可以直接和期望区域逐元素比对。
# 只比返回的坐标是不够的——坐标对但内容取错区域，光看坐标发现不了。
CH, CW = 60, 100
crop_src = torch.zeros((1, CH, CW, 3))
crop_src[0, :, :, 0] = torch.arange(CW).float() / CW          # R 通道编码 x
crop_src[0, :, :, 1] = torch.arange(CH).float().view(-1, 1) / CH  # G 通道编码 y

# 期望坐标按「位置语义」手推（不引用实现里的公式），100x60 图上裁 40x20
EXPECT_POS = [
    ("左上角", 0, 0),
    ("上方居中", 30, 0),
    ("右上角", 60, 0),
    ("右侧居中", 60, 20),
    ("右下角", 60, 40),
    ("下方居中", 30, 40),
    ("左下角", 0, 40),
    ("左侧居中", 0, 20),
    ("居中", 30, 20),
]
for pos, ex, ey in EXPECT_POS:
    out, gx, gy = MKImageCrop.execute(
        图像=crop_src, 宽度=40, 高度=20, 位置=pos, X轴偏移=0, Y轴偏移=0).result
    same = bool((out == crop_src[:, ey:ey + 20, ex:ex + 40, :]).all())
    print(f"  {pos:6s} -> x={gx:<3d} y={gy:<3d} shape={tuple(out.shape)} 内容一致={same}")
    check(f"  {pos} 坐标正确", (gx, gy) == (ex, ey), f"得到 ({gx},{gy}) 期望 ({ex},{ey})")
    check(f"  {pos} 尺寸正确", tuple(out.shape) == (1, 20, 40, 3), str(tuple(out.shape)))
    check(f"  {pos} 内容正确", same)

# 偏移量叠加在基准位置之上
out, gx, gy = MKImageCrop.execute(
    图像=crop_src, 宽度=40, 高度=20, 位置="居中", X轴偏移=10, Y轴偏移=-5).result
print(f"  居中+偏移(10,-5) -> x={gx} y={gy} shape={tuple(out.shape)}")
check("  偏移叠加正确", (gx, gy) == (40, 15), f"得到 ({gx},{gy}) 期望 (40,15)")
check("  偏移后内容正确", bool((out == crop_src[:, 15:35, 40:80, :]).all()))

# 裁剪尺寸超过原图 → 收敛到原图
out, gx, gy = MKImageCrop.execute(
    图像=crop_src, 宽度=250, 高度=200, 位置="居中", X轴偏移=0, Y轴偏移=0).result
print(f"  尺寸超原图 250x200 -> x={gx} y={gy} shape={tuple(out.shape)}")
check("  超尺寸收敛到原图", tuple(out.shape) == (1, CH, CW, 3), str(tuple(out.shape)))
check("  超尺寸后起点归零", (gx, gy) == (0, 0), f"得到 ({gx},{gy})")

# 越界：夹回边界但「不重算尺寸」，所以负偏移会让结果变小 —— 上游行为，刻意保留
out, gx, gy = MKImageCrop.execute(
    图像=crop_src, 宽度=40, 高度=20, 位置="居中", X轴偏移=-50, Y轴偏移=0).result
print(f"  负偏移越界(-50) -> x={gx} y={gy} shape={tuple(out.shape)}")
check("  负偏移起点夹到 0", gx == 0, str(gx))
check("  负偏移结果变窄（上游行为）", tuple(out.shape) == (1, 20, 20, 3), str(tuple(out.shape)))

out, gx, gy = MKImageCrop.execute(
    图像=crop_src, 宽度=40, 高度=20, 位置="左上角", X轴偏移=90, Y轴偏移=0).result
print(f"  右越界(+90) -> x={gx} y={gy} shape={tuple(out.shape)}")
check("  右越界结果变窄（上游行为）", tuple(out.shape) == (1, 20, 10, 3), str(tuple(out.shape)))

# 批量：每张图用同一组参数，batch 维必须保留
batch = torch.cat([crop_src, crop_src * 0.5, crop_src * 0.25], dim=0)
out, gx, gy = MKImageCrop.execute(
    图像=batch, 宽度=40, 高度=20, 位置="居中", X轴偏移=0, Y轴偏移=0).result
print(f"  批量 batch=3 -> shape={tuple(out.shape)}")
check("  批量裁剪保留 batch 维", tuple(out.shape) == (3, 20, 40, 3), str(tuple(out.shape)))
check("  批量每张各自裁剪（未串图）", bool((out[0] == out[1] * 2).all()))

check("  已注册 MK_ImageCrop", "MK_ImageCrop" in pkg.NODE_CLASS_MAPPINGS)
check("  显示名已登记",
      pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_ImageCrop") == "MK-图像裁剪",
      str(pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_ImageCrop")))

print()
print("=== 11. 提示词拼接（MK_PromptConcat，V1）===")
from Comfyui_MKnode.nodes.prompt_concat import (
    MKPromptConcat,
    MAX_PROMPT_INPUTS,
    _prompt_input_name,
)

it_pc = MKPromptConcat.INPUT_TYPES()
print("  required :", dict(it_pc["required"]))
print("  optional :", dict(it_pc["optional"]))
print("  RETURN_TYPES/NAMES :", MKPromptConcat.RETURN_TYPES, MKPromptConcat.RETURN_NAMES)
print("  FUNCTION/CATEGORY  :", MKPromptConcat.FUNCTION, MKPromptConcat.CATEGORY)

check("  分隔符为必填且默认 ', '",
      it_pc["required"]["分隔符"][1].get("default") == ", ", str(it_pc["required"]["分隔符"]))
check("  仅声明 提示词_01（其余由前端动态添加）",
      list(it_pc["optional"].keys()) == ["提示词_01"], str(list(it_pc["optional"].keys())))
check("  提示词_01 是 forceInput（无文本框）",
      it_pc["optional"]["提示词_01"][1].get("forceInput") is True)
check("  返回单个 STRING", MKPromptConcat.RETURN_TYPES == ("STRING",))
check("  输出名为 提示词", MKPromptConcat.RETURN_NAMES == ("提示词",))
check("  分类为 MK节点", MKPromptConcat.CATEGORY == "MK节点")
check("  非输出节点", not getattr(MKPromptConcat, "OUTPUT_NODE", False))
check("  输入名生成正确",
      _prompt_input_name(1) == "提示词_01" and _prompt_input_name(10) == "提示词_10")

# 直接按 ComfyUI 的调用方式传参：分隔符 + 若干 提示词_NN
node_pc = MKPromptConcat()
pc_cases = [
    ("空输入", {}, ""),
    ("单个", {"提示词_01": "a"}, "a"),
    ("两个", {"提示词_01": "a", "提示词_02": "b"}, "a, b"),
    ("跳空", {"提示词_01": "a", "提示词_02": "", "提示词_03": "c"}, "a, c"),
    ("None 跳过", {"提示词_01": "a", "提示词_02": None, "提示词_03": "c"}, "a, c"),
    ("按序号排序（字典乱序）",
     {"提示词_03": "c", "提示词_01": "a", "提示词_02": "b"}, "a, b, c"),
    ("列表展开", {"提示词_01": ["a", "b"], "提示词_02": "c"}, "a, b, c"),
    ("超出上限被忽略",
     {**{_prompt_input_name(i): f"p{i}" for i in range(1, 11)}, "提示词_11": "x"},
     ", ".join(f"p{i}" for i in range(1, 11))),
]
for label, kw, expect in pc_cases:
    got = node_pc.concat(**kw)[0]
    print(f"  {label:20s} -> {got!r}")
    check(f"  concat {label}", got == expect, f"got {got!r} 期望 {expect!r}")

for sep, kw, expect in [
    (" | ", {"提示词_01": "a", "提示词_02": "b"}, "a | b"),
    ("", {"提示词_01": "a", "提示词_02": "b"}, "ab"),
    ("\n", {"提示词_01": "a", "提示词_02": "b"}, "a\nb"),
]:
    got = node_pc.concat(分隔符=sep, **kw)[0]
    print(f"  分隔符 {sep!r:8s} -> {got!r}")
    check(f"  分隔符 {sep!r} 生效", got == expect, f"got {got!r} 期望 {expect!r}")

# 前端常量必须与后端一致，否则会出现「加到第 11 个后端不认」这类错位
js_pc = os.path.join(pkg_dir, "web", "prompt_concat.js")
if os.path.isfile(js_pc):
    with open(js_pc, encoding="utf-8") as f:
        js_pc_src = f.read()
    check("  前端匹配节点名", '"MK_PromptConcat"' in js_pc_src)
    check("  扩展名已加包前缀", "Comfyui_MKnode.PromptConcat" in js_pc_src)
    check("  不再引用源包扩展名", "MK_Tools.PromptConcat" not in js_pc_src)
    check(f"  前端上限与后端一致（{MAX_PROMPT_INPUTS}）",
          f"MAX_INPUTS = {MAX_PROMPT_INPUTS}" in js_pc_src)
    check("  前端输入前缀与后端一致", '"提示词_"' in js_pc_src)
    check("  加载工作流后也会收敛输入端", "onConfigure" in js_pc_src)
    # 这两条防回归：浏览器实测出来的两个真实缺陷
    # 1) 输入端被整个删空后 stabilize 只补「已连接」的槽，节点会卡死 → 需有下限
    check("  输入端有下限（删空后能自愈）", "MIN_INPUTS" in js_pc_src)
    # 2) 用「已用数量 + 1」命名，序号有缺口时会补出重名输入 → 需按最大序号推进
    check("  补输入端按最大序号推进（避免重名）", "maxIndexOf" in js_pc_src)

# 语言包条目（这里独立读一次，不依赖第 8 节的分支）
loc_all = {}
if os.path.isfile(loc_path):
    with open(loc_path, encoding="utf-8") as f:
        loc_all = json.load(f)
pc_loc = loc_all.get("MK_PromptConcat")
check("  语言包含 MK_PromptConcat", pc_loc is not None)
if pc_loc:
    pc_valid_ids = set(it_pc["required"]) | set(it_pc["optional"])
    check("  语言包输入 id 均合法",
          set(pc_loc.get("inputs", {})) <= pc_valid_ids,
          f"多余: {set(pc_loc.get('inputs', {})) - pc_valid_ids}")
    check("  语言包输出按索引翻译",
          set(pc_loc.get("outputs", {})) == {str(i) for i in range(len(MKPromptConcat.RETURN_TYPES))},
          str(sorted(pc_loc.get("outputs", {}))))
    check("  语言包 display_name 与注册一致",
          pc_loc.get("display_name") == pkg.NODE_DISPLAY_NAME_MAPPINGS["MK_PromptConcat"],
          f"{pc_loc.get('display_name')!r}")
    check("  未配置无效的 options 翻译",
          all("options" not in v for v in pc_loc.get("inputs", {}).values()))

print()
print("=== 12. 图像对比（MK_ImageCompare）===")
from Comfyui_MKnode.nodes.image_compare import MKImageCompare

ic_schema = MKImageCompare.GET_SCHEMA()
print("  node_id     :", ic_schema.node_id)
print("  inputs      :", [(i.id, type(i).__name__) for i in ic_schema.inputs])
print("  outputs     :", [(o.id, o.display_name, o.io_type) for o in ic_schema.outputs])
check("node_id 为 MK_ImageCompare", ic_schema.node_id == "MK_ImageCompare", ic_schema.node_id)
check("display_name 为 MK-图像对比", ic_schema.display_name == "MK-图像对比", ic_schema.display_name)
check("分类为 MK节点", ic_schema.category == "MK节点", ic_schema.category)
check("输入为 image_a / image_b", [i.id for i in ic_schema.inputs] == ["image_a", "image_b"],
      str([i.id for i in ic_schema.inputs]))
check("两个输入都是可选", all(getattr(i, "optional", False) for i in ic_schema.inputs))
check("输出只有 1 个 IMAGE", [(o.id, o.io_type) for o in ic_schema.outputs] == [("image", "IMAGE")],
      str([(o.id, o.io_type) for o in ic_schema.outputs]))
check("是输出节点（需要 ui 回传）", bool(ic_schema.is_output_node))

from Comfyui_MKnode.nodes import image_compare as ic_mod

_ic_a = np.random.rand(2, 24, 32, 3).astype(np.float32)
_ic_b = np.random.rand(1, 24, 32, 3).astype(np.float32)
# 直接用 torch 张量走真实 save_images 路径
import torch as _torch
_ic_a = _torch.from_numpy(_ic_a)
_ic_b = _torch.from_numpy(_ic_b)

_ic_out = MKImageCompare.execute(image_a=_ic_a, image_b=_ic_b)
check("图像A 原样透传（同一对象）", _ic_out.result[0] is _ic_a)
check("批次维度未被改动", tuple(_ic_out.result[0].shape) == tuple(_ic_a.shape))
check("ui.a_images 数量 = A 的批次", len(_ic_out.ui["a_images"]) == 2, str(_ic_out.ui["a_images"]))
check("ui.b_images 数量 = B 的批次", len(_ic_out.ui["b_images"]) == 1, str(_ic_out.ui["b_images"]))
check("图片引用带 type=temp",
      all(item.get("type") == "temp" and item.get("filename") for item in _ic_out.ui["a_images"]))

_ic_only_b = MKImageCompare.execute(image_a=None, image_b=_ic_b)
check("只接 B 时输出为空", _ic_only_b.result[0] is None)
check("只接 B 时 b 仍可预览", len(_ic_only_b.ui["b_images"]) == 1)
check("只接 B 时 a 为空", _ic_only_b.ui["a_images"] == [])

_ic_none = MKImageCompare.execute()
check("两个都不接时不报错", _ic_none.result[0] is None and _ic_none.ui == {"a_images": [], "b_images": []})

# 保存失败要降级为「不显示」，不能把整条流程炸掉
import nodes as _comfy_nodes

_orig_preview_cls = _comfy_nodes.PreviewImage


class _BoomPreview:
    def save_images(self, *args, **kwargs):
        raise RuntimeError("boom")


_comfy_nodes.PreviewImage = _BoomPreview
try:
    check("保存失败时降级为空列表", ic_mod._save_preview(_ic_a, "mk.test.boom") == [])
finally:
    _comfy_nodes.PreviewImage = _orig_preview_cls


# 前端契约：面板挂载点、接口名、交互常量
def _read(rel):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), rel), encoding="utf-8") as f:
        return f.read()


ic_js = _read("web/image_compare.js")
check("前端扩展名带包前缀", 'name: "Comfyui_MKnode.ImageCompare"' in ic_js)
check("前端只处理 MK_ImageCompare", 'NODE_TYPE = "MK_ImageCompare"' in ic_js)
check("前端用 addDOMWidget 挂载", "addDOMWidget(" in ic_js)
check("前端读取 ui.a_images / ui.b_images",
      "a_images" in ic_js and "b_images" in ic_js)
check("前端用 clip-path 做分割对比", "clipPath" in ic_js and "inset(0 " in ic_js)
check("没有画布钩子（Nodes 2.0 不调用）",
      "onDrawBackground" not in ic_js and "graph_mouse" not in ic_js)

ic_loc = loc_all.get("MK_ImageCompare")
check("语言包含 MK_ImageCompare", ic_loc is not None)
if ic_loc:
    ic_valid = {i.id for i in ic_schema.inputs}
    check("  语言包输入 id 均合法",
          set(ic_loc.get("inputs", {})) <= ic_valid,
          f"多余: {set(ic_loc.get('inputs', {})) - ic_valid}")
    check("  语言包输出按索引翻译",
          set(ic_loc.get("outputs", {})) == {"0"},
          str(sorted(ic_loc.get("outputs", {}))))
    check("  语言包 display_name 与注册一致",
          ic_loc.get("display_name") == pkg.NODE_DISPLAY_NAME_MAPPINGS["MK_ImageCompare"],
          f"{ic_loc.get('display_name')!r}")

print("=== 13. 任意切换（MK_AnySwitch，V1）===")
from Comfyui_MKnode.nodes.any_switch import (
    MKAnySwitch,
    AnyType,
    any_type,
    is_none,
    input_name,
    INPUT_PREFIX,
    MIN_INPUTS,
    MAX_INPUTS,
)

as_it = MKAnySwitch.INPUT_TYPES()
print("  required :", dict(as_it["required"]))
print("  optional 类型:", type(as_it["optional"]).__name__)
print("  RETURN_TYPES/NAMES :", MKAnySwitch.RETURN_TYPES, MKAnySwitch.RETURN_NAMES)
print("  FUNCTION/CATEGORY  :", MKAnySwitch.FUNCTION, MKAnySwitch.CATEGORY)

check("  已注册", "MK_AnySwitch" in pkg.NODE_CLASS_MAPPINGS)
check("  显示名为 MK-任意切换",
      pkg.NODE_DISPLAY_NAME_MAPPINGS["MK_AnySwitch"] == "MK-任意切换",
      pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_AnySwitch"))
check("  required 为空（输入全靠前端动态添加）", as_it["required"] == {})
check("  optional 是 FlexibleOptionalInputType", isinstance(as_it["optional"], dict) and "any_05" in as_it["optional"])
check("  未声明输入取到 ('*',)", as_it["optional"]["any_05"] == ("*",), str(as_it["optional"]["any_05"]))
check("  任意怪键也被接受", as_it["optional"]["不是输入名"] == ("*",))
check("  返回单个 AnyType", MKAnySwitch.RETURN_TYPES == (any_type,) and isinstance(any_type, AnyType))
check("  AnyType 与任何类型比对都不相等", (any_type != "IMAGE") is False)
check("  输出名为 任意", MKAnySwitch.RETURN_NAMES == ("任意",))
check("  分类为 MK节点", MKAnySwitch.CATEGORY == "MK节点")
check("  非输出节点", not getattr(MKAnySwitch, "OUTPUT_NODE", False))
check("  输入 id 补零", input_name(1) == "any_01" and input_name(12) == "any_12", input_name(12))
check("  输入前缀与前端约定一致", INPUT_PREFIX == "any_")
check("  端数上下限合理", MIN_INPUTS >= 1 and MAX_INPUTS >= MIN_INPUTS,
      f"{MIN_INPUTS}/{MAX_INPUTS}")

# is_none：None 算空；0 / 空串 / 普通 dict 不算空；全空的 rgthree CONTEXT 算空
for label, value, expect in [
    ("None", None, True),
    ("0", 0, False),
    ("空字符串", "", False),
    ("空列表", [], False),
    ("空 context", {"model": None, "clip": None}, True),
    ("有内容 context", {"model": "m", "clip": None}, False),
    ("普通 dict", {"a": None}, False),
]:
    check(f"  is_none {label}", is_none(value) is expect, str(value))

# switch：按顺序取第一个非空
node_as = MKAnySwitch()
as_cases = [
    ("全空", {}, None),
    ("单个", {"any_01": "a"}, "a"),
    ("跳过 None", {"any_01": None, "any_02": "b"}, "b"),
    ("跳过空 context", {"any_01": {"model": None, "clip": None}, "any_02": 7}, 7),
    ("0 先命中（不被当空）", {"any_01": 0, "any_02": "b"}, 0),
    ("空字符串先命中", {"any_01": "", "any_02": "b"}, ""),
    ("字典顺序即优先级", {"any_01": "x", "any_02": "y"}, "x"),
    ("非 any_ 前缀忽略", {"foo": "z"}, None),
    ("任意对象原样透传", {"any_03": ("T",)}, ("T",)),
]
for label, kw, expect in as_cases:
    got = node_as.switch(**kw)[0]
    print(f"  {label:22s} -> {got!r}")
    check(f"  switch {label}", got == expect or got is expect, f"got {got!r} 期望 {expect!r}")

# ComfyUI 真实校验路径：未声明的 any_NN 不会被当成「未知输入」拦下
import asyncio  # noqa: E402
import execution  # noqa: E402
import nodes as _comfy_nodes  # noqa: E402

_prev_maps = (dict(_comfy_nodes.NODE_CLASS_MAPPINGS), dict(_comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS))
try:
    _comfy_nodes.NODE_CLASS_MAPPINGS.update(pkg.NODE_CLASS_MAPPINGS)
    _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS.update(pkg.NODE_DISPLAY_NAME_MAPPINGS)
    _as_prompt = {
        "1": {"class_type": "MK_PromptConcat", "inputs": {"分隔符": " | "}},
        "2": {"class_type": "MK_PromptConcat", "inputs": {"分隔符": " - "}},
        "3": {"class_type": "MK_AnySwitch",
              "inputs": {"any_01": ["1", 0], "any_02": ["2", 0], "any_07": ["1", 0]}},
        "4": {"class_type": "MK_SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "mk_selftest",
                         "image_format": "PNG", "quality": 95,
                         "save_metadata": False, "preview_only": True}},
    }
    _as_ok, _as_err, _as_partial, _ = asyncio.run(execution.validate_prompt("selftest", _as_prompt, None))
finally:
    _comfy_nodes.NODE_CLASS_MAPPINGS.clear()
    _comfy_nodes.NODE_CLASS_MAPPINGS.update(_prev_maps[0])
    _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS.clear()
    _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS.update(_prev_maps[1])

print("  validate_prompt ->", _as_ok, _as_err)
check("  含未声明动态输入的 prompt 通过校验", _as_ok is True, str(_as_err))

# 前端契约
as_js = _read("web/any_switch.js")
check("  前端扩展名带包前缀", 'name: "Comfyui_MKnode.AnySwitch"' in as_js)
check("  前端只处理 MK_AnySwitch", 'NODE_TYPE = "MK_AnySwitch"' in as_js)
check("  前端输入前缀与后端一致", f'INPUT_PREFIX = "{INPUT_PREFIX}"' in as_js)
check(f"  前端下限与后端一致（{MIN_INPUTS}）", f"MIN_INPUTS = {MIN_INPUTS}" in as_js)
check(f"  前端上限与后端一致（{MAX_INPUTS}）", f"MAX_INPUTS = {MAX_INPUTS}" in as_js)
check("  用 addInput 动态加槽", "this.addInput(" in as_js)
check("  加载工作流后也会收敛输入端", "onConfigure" in as_js)
check("  连线变化后收敛", "onConnectionsChange" in as_js)
check("  无画布钩子（Nodes 2.0 不调用）",
      all(k not in as_js.replace("// 不碰任何 canvas 绘制钩子（onDrawBackground / onMouseDown / graph_mouse 等）。", "")
          for k in ("onDrawBackground", "graph_mouse", "onMouseDown")))
check("  类型跟随不读本节点槽位（断线能回到 *）", "typeUpstream" in as_js and "slotType(node, dir" not in as_js)

as_loc = loc_all.get("MK_AnySwitch")
check("  语言包含 MK_AnySwitch", as_loc is not None)
if as_loc:
    check("  语言包不翻译动态输入（避免死键）",
          not as_loc.get("inputs"), str(as_loc.get("inputs")))
    check("  语言包输出按索引翻译", set(as_loc.get("outputs", {})) == {"0"},
          str(sorted(as_loc.get("outputs", {}))))
    check("  语言包 display_name 与注册一致",
          as_loc.get("display_name") == pkg.NODE_DISPLAY_NAME_MAPPINGS["MK_AnySwitch"],
          f"{as_loc.get('display_name')!r}")

print("=== 14. 禁用多框 / 忽略多框（MK_FastGroups*，V1 空节点）===")
from Comfyui_MKnode.nodes.fast_groups import (  # noqa: E402
    MKFastGroupsMuter,
    MKFastGroupsBypasser,
)

for cls, node_id, display, off_mode in [
    (MKFastGroupsMuter, "MK_FastGroupsMuter", "MK-禁用多框", 2),
    (MKFastGroupsBypasser, "MK_FastGroupsBypasser", "MK-忽略多框", 4),
]:
    print(f"  --- {node_id} ---")
    it = cls.INPUT_TYPES()
    check(f"  {node_id} 已注册", node_id in pkg.NODE_CLASS_MAPPINGS)
    check(f"  {node_id} 显示名为 {display}",
          pkg.NODE_DISPLAY_NAME_MAPPINGS.get(node_id) == display,
          pkg.NODE_DISPLAY_NAME_MAPPINGS.get(node_id))
    check(f"  {node_id} 无输入", it["required"] == {}, str(it["required"]))
    check(f"  {node_id} 无输出（纯 UI 节点）", cls.RETURN_TYPES == (), str(cls.RETURN_TYPES))
    check(f"  {node_id} 不是输出节点", not getattr(cls, "OUTPUT_NODE", False))
    check(f"  {node_id} 分类为 MK节点", cls.CATEGORY == "MK节点")
    check(f"  {node_id} noop 返回空元组", cls().noop() == ())
    check(f"  {node_id} 关闭模式为 {off_mode}", cls.MODE_OFF == off_mode, str(cls.MODE_OFF))
    check(f"  {node_id} 开启模式为 0（ALWAYS）", cls.MODE_ON == 0, str(cls.MODE_ON))

# 空节点混在真实 prompt 里不能影响校验
_prev_maps2 = (dict(_comfy_nodes.NODE_CLASS_MAPPINGS), dict(_comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS))
try:
    _comfy_nodes.NODE_CLASS_MAPPINGS.update(pkg.NODE_CLASS_MAPPINGS)
    _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS.update(pkg.NODE_DISPLAY_NAME_MAPPINGS)
    _fg_prompt = {
        "1": {"class_type": "EmptyImage",
              "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}},
        "2": {"class_type": "MK_FastGroupsMuter", "inputs": {}},
        "3": {"class_type": "MK_FastGroupsBypasser", "inputs": {}},
        "4": {"class_type": "MK_SaveImage",
              "inputs": {"images": ["1", 0], "filename_prefix": "mk_selftest",
                         "image_format": "PNG", "quality": 95,
                         "save_metadata": False, "preview_only": True}},
    }
    _fg_ok, _fg_err, _fg_partial, _ = asyncio.run(execution.validate_prompt("selftest_fg", _fg_prompt, None))
finally:
    _comfy_nodes.NODE_CLASS_MAPPINGS.clear()
    _comfy_nodes.NODE_CLASS_MAPPINGS.update(_prev_maps2[0])
    _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS.clear()
    _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS.update(_prev_maps2[1])

print("  validate_prompt ->", _fg_ok, _fg_err)
check("  空 UI 节点混在 prompt 中校验通过", _fg_ok is True, str(_fg_err))
check("  空 UI 节点不进入执行列表", "2" not in _fg_partial and "3" not in _fg_partial, str(_fg_partial))

# 前端契约
fg_js = _read("web/fast_groups.js")
check("  前端扩展名带包前缀", 'name: "Comfyui_MKnode.FastGroups"' in fg_js)
check("  同时处理两个节点类型",
      "MK_FastGroupsMuter: {" in fg_js and "MK_FastGroupsBypasser: {" in fg_js)
check("  用 addDOMWidget 挂面板（Nodes 2.0 才不空白）", "addDOMWidget(" in fg_js)
check("  禁用用 mode=2、忽略用 mode=4",
      "MODE_NEVER = 2" in fg_js and "MODE_BYPASS = 4" in fg_js)
check("  无画布绘制/命中钩子",
      all(k not in fg_js for k in ("onDrawBackground", "graph_mouse", "isInsideRectangle")))
check("  按分组行的 DOM 按钮切换", 'className = "mk-fg-switch"' in fg_js)
check("  有轮询刷新（分组与状态会变）", "setInterval(" in fg_js and "mkFgRefresh" in fg_js)
check("  支持宽度自适应（面板高度跟节点）", "mkFgSyncPanelHeight" in fg_js)
check("  覆盖 onConfigure 且调用基类",
      "const onConfigure = nodeType.prototype.onConfigure;" in fg_js)
# 回归：boundingRect 只在「画布画到该节点的那一帧」才更新，切工作流/滚出可视区后会变 [0,0,0,0]。
# 必须用 measure() 现算，否则所有分组都算不出成员（面板全灰、点了没反应）。
check("  节点包围盒用 measure() 现算（不依赖每帧缓存）",
      "typeof node.measure === \"function\"" in fg_js and "node.measure(out, app.canvas?.ctx)" in fg_js)
check("  分组包围盒优先 getBounding（同步布局 store）",
      "typeof group?.getBounding === \"function\"" in fg_js)
check("  面板版本标记存在（便于确认脚本已刷新）",
      'PANEL_VERSION = "v4"' in fg_js)
# v4：节点高度按内容自适应，只有一个分组时不再拖一大片空白
check("  节点高度按内容自适应", "mkFgFitHeight" in fg_js and "mkFgContentHeight" in fg_js)
check("  内容过高时改为列表内滚动", "MAX_CONTENT_HEIGHT" in fg_js)
check("  内容没变时不改节点尺寸（不跟手动拉尺寸打架）", "_mkFgFitContent" in fg_js)
# 性能模型（v3）：分组快照跨面板共享 + TTL、拖动跳过、动作走一次计算
check("  分组快照跨面板共享（getGroupSnapshot + TTL）",
      "function getGroupSnapshot()" in fg_js and "SNAPSHOT_TTL" in fg_js)
check("  拖动/框选时跳过重算", "function isInteracting()" in fg_js and "isInteracting())" in fg_js)
check("  点击后只按已有成员刷新（不再逐组重算）", "mkFgAfterChange" in fg_js)
check("  页面在后台时不重算", "document.hidden" in fg_js)
check("  不再有每面板独立的全量收集函数", "function collectGroups" not in fg_js)
check("  属性键与上游一致",
      all(f'{k}:' in fg_js for k in ("matchColors", "matchTitle", "showNav", "showAllGraphs",
                                     "sort", "customSortAlphabet", "toggleRestriction")))
# 只检查「代码」里有没有依赖 rgthree：注释里提到上游名字是正常的（说明来源）
import re as _re  # noqa: E402

fg_code_only = _re.sub(r"/\*[\s\S]*?\*/", "", fg_js)  # 去掉块注释
fg_code_only = "\n".join(
    line for line in fg_code_only.splitlines() if not line.strip().startswith("//")
)
check("  不引用 rgthree 的任何文件（注释提及不算）",
      "rgthree" not in fg_code_only.lower().replace("rgthree-comfy", ""))

for node_id in ("MK_FastGroupsMuter", "MK_FastGroupsBypasser"):
    fg_loc = loc_all.get(node_id)
    check(f"  语言包含 {node_id}", fg_loc is not None)
    if fg_loc:
        check(f"    {node_id} 不翻译不存在的输入输出",
              not fg_loc.get("inputs") and not fg_loc.get("outputs"),
              f"{fg_loc.get('inputs')}/{fg_loc.get('outputs')}")
        check(f"    {node_id} display_name 与注册一致",
              fg_loc.get("display_name") == pkg.NODE_DISPLAY_NAME_MAPPINGS[node_id],
              f"{fg_loc.get('display_name')!r}")

print("=== 15. Lora加载器（MK_LoraLoaderModelOnly）===")
from Comfyui_MKnode.nodes.lora_loader import MKLoraLoaderModelOnly, NONE_OPTION  # noqa: E402

lo_it = MKLoraLoaderModelOnly.INPUT_TYPES()
lo_options = lo_it["required"]["lora_name"][0]
print("  required :", list(lo_it["required"]))
print("  LoRA 选项:", lo_options[:5], f"（共 {len(lo_options)} 个）")
print("  RETURN_TYPES/NAMES :", MKLoraLoaderModelOnly.RETURN_TYPES, MKLoraLoaderModelOnly.RETURN_NAMES)

check("  已注册", "MK_LoraLoaderModelOnly" in pkg.NODE_CLASS_MAPPINGS)
check("  显示名为 MK-Lora加载器",
      pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_LoraLoaderModelOnly") == "MK-Lora加载器",
      pkg.NODE_DISPLAY_NAME_MAPPINGS.get("MK_LoraLoaderModelOnly"))
check("  「无」排在第一位", lo_options and lo_options[0] == NONE_OPTION, str(lo_options[:2]))
check("  「无」只有一项（不重复）", lo_options.count(NONE_OPTION) == 1, str(lo_options[:3]))
check("  输入为 model/lora_name/strength_model",
      list(lo_it["required"]) == ["model", "lora_name", "strength_model"],
      str(list(lo_it["required"])))
check("  强度范围与官方一致（-100~100，默认 1.0，步长 0.01）",
      (lo_it["required"]["strength_model"][1]["min"],
       lo_it["required"]["strength_model"][1]["max"],
       lo_it["required"]["strength_model"][1]["default"],
       lo_it["required"]["strength_model"][1]["step"]) == (-100.0, 100.0, 1.0, 0.01),
      str(lo_it["required"]["strength_model"][1]))
check("  单输出 MODEL", MKLoraLoaderModelOnly.RETURN_TYPES == ("MODEL",))
check("  输出名为 模型", MKLoraLoaderModelOnly.RETURN_NAMES == ("模型",))
check("  分类为 MK节点", MKLoraLoaderModelOnly.CATEGORY == "MK节点")
check("  非输出节点", not getattr(MKLoraLoaderModelOnly, "OUTPUT_NODE", False))

# 选「无」：不加载、不碰文件系统、原样返回
lo_node = MKLoraLoaderModelOnly()
lo_model = object()
lo_out = lo_node.load_lora_model_only(lo_model, NONE_OPTION, 1.0)
check("  选「无」原样返回同一个对象", lo_out[0] is lo_model)
check("  选「无」后没有缓存任何 LoRA", lo_node.loaded_lora is None)
check("  空字符串也当作「无」", lo_node.load_lora_model_only(lo_model, "", 1.0)[0] is lo_model)
# 强度 0：与官方一致，短路返回原模型（不会去解析文件路径）
check("  强度 0 原样返回（不读文件）",
      lo_node.load_lora_model_only(lo_model, "不存在的.safetensors", 0)[0] is lo_model)
# 文件不存在时保持官方行为：抛 FileNotFoundError
lo_raised = None
try:
    lo_node.load_lora_model_only(lo_model, "不存在的.safetensors", 1.0)
except Exception as exc:  # noqa: BLE001
    lo_raised = exc
check("  文件缺失时抛 FileNotFoundError（与官方一致）",
      isinstance(lo_raised, FileNotFoundError), type(lo_raised).__name__ if lo_raised else "None")

# 前端/文档契约：本节点没有自定义前端脚本，靠原生 widget 即可
check("  没有为该节点引入前端脚本", not os.path.isfile(os.path.join(pkg_dir, "web", "lora_loader.js")))
lo_loc = loc_all.get("MK_LoraLoaderModelOnly")
check("  语言包含 MK_LoraLoaderModelOnly", lo_loc is not None)
if lo_loc:
    check("  语言包输入 id 均合法",
          set(lo_loc.get("inputs", {})) <= set(lo_it["required"]),
          str(set(lo_loc.get("inputs", {})) - set(lo_it["required"])))
    check("  语言包输出按索引翻译", set(lo_loc.get("outputs", {})) == {"0"},
          str(sorted(lo_loc.get("outputs", {}))))
    check("  语言包 display_name 与注册一致",
          lo_loc.get("display_name") == pkg.NODE_DISPLAY_NAME_MAPPINGS["MK_LoraLoaderModelOnly"],
          f"{lo_loc.get('display_name')!r}")

print("=== 16. 提示词大全：分类排序（前端契约）===")
pl_js = _read("web/prompt_library.js")
check("  有同级上移/下移实现", "function _libMoveNode(lib, id, direction)" in pl_js)
check("  拖拽与按钮共用同一套编号规则", "function _libApplyCategoryOrder(list)" in pl_js)
check("  拖拽落位按显示顺序重排", "_libApplyCategoryOrder(sorted)" in pl_js)
check("  分类行有 ↑ / ↓ 按钮", 'up.textContent = "↑"' in pl_js and 'down.textContent = "↓"' in pl_js)
check("  按钮挂在「非收藏」行上（收藏固定第一）",
      "if (!isFav) {" in pl_js and "up.disabled = pos <= 0" in pl_js)
check("  末位时下移按钮禁用", "down.disabled = pos < 0 || pos >= siblingsRest.length - 1" in pl_js)
check("  上移/下移后存盘并重绘",
      "await moveCategory(node, -1)" in pl_js and "await moveCategory(node, 1)" in pl_js)
check("  有按钮样式（平时压暗 / hover 提亮）", ".mk-pl-tree-move" in pl_js)
check("  分类下拉/移动目标按显示顺序遍历", "for (const node of _libSortNodes(nodes))" in pl_js)

print()
if fails:
    print(f"### 失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print("### 全部通过")
