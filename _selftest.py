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
print("=== 10. 提示词拼接（MK_PromptConcat，V1）===")
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
if fails:
    print(f"### 失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print("### 全部通过")
