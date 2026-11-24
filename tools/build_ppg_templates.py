"""把「写真提示词汇总」单文件 HTML 拆成 MK-提示词预设图库 的内置模板数据。

用法（可以传多个源文件，按参数顺序叠加）：
    python tools/build_ppg_templates.py "第一份.html" "第二份.html" [...]
    python tools/build_ppg_templates.py --width 180 --quality 72 "第一份.html" [...]
    python tools/build_ppg_templates.py --no-resize "第一份.html"     # 保留原始图片字节

产物（都在 web/ppg_data/ 下；每次重建会先清空 img/，避免改名后留残影）：
    manifest.json                        组名 + 子分类清单（含各自条数与文件名）
    cat_<id>.json                        该分类条目：[{"s": 缩略图相对路径, "p": 提示词, "n": 原文件名}]
    img/<id>/v<源序号>/<序号>.webp        缩略图

图片默认重新编码：宽缩到 180px、WebP q72（卡片显示宽度约 134px，够看且体积约原来的六成）；
重编码后若反而变大就保留原始字节。`--width 0` 或 `--no-resize` 关闭压缩。

分类是启发式的：对提示词做关键词加权打分，取分数最高的场景；都不命中归到「综合其他」。
多个源之间提示词完全相同的条目会去掉（按提示词 md5 判重），图片字节相同的同图不同词仍保留。

手工分类（EXTRA_CATS，默认「萌妹 mengmei」）不受本脚本影响：重建时只把它的
cat_<id>.json 读回来挂进 manifest 最前，条目与 img/<id>/ 一律不动。
往这类分类追加内容用：python tools/import_gallery_html.py --html 画廊.html --cat-id mengmei --cat-name 萌妹
"""

import base64
import hashlib
import io
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "web", "ppg_data")

GROUP = {"id": "portrait", "name": "写真图片"}

# (id, 名称, [(关键词, 权重)])：权重越高的词越能代表该场景
RULES = [
    ("bedroom", "卧室", [
        ("bedroom", 8), ("on the bed", 6), ("bedsheet", 6), ("bed sheet", 6),
        ("pillow", 4), ("mattress", 5), ("duvet", 5),
    ]),
    ("bath", "浴室", [
        ("bathroom", 6), ("bathtub", 8), ("shower", 5), ("washbasin", 6),
        ("sink", 2), ("towel wrapped", 4),
    ]),
    ("living", "客厅·沙发", [
        ("sofa", 6), ("couch", 6), ("living room", 8), ("hotel room", 7),
        ("armchair", 5), ("kitchen", 6), ("dining table", 5), ("curtain", 2),
    ]),
    ("studio", "影棚·纯色", [
        ("backdrop", 7), ("seamless", 6), ("photo studio", 9), ("in a studio", 9),
        ("studio background", 9), ("white background", 7), ("gray background", 6),
        ("grey background", 6), ("studio lighting", 1),
    ]),
    ("pool", "泳池·海边", [
        ("swimming pool", 9), ("pool", 5), ("beach", 9), ("seaside", 9),
        ("ocean", 8), ("bikini", 7), ("swimsuit", 7), ("sand", 4), ("waves", 3),
    ]),
    ("street", "城市·街拍", [
        ("street", 7), ("city", 5), ("alley", 6), ("sidewalk", 6), ("crosswalk", 6),
        ("neon", 5), ("urban", 5), ("storefront", 6), ("subway", 6), ("train", 3),
        ("cafe", 5), ("restaurant", 5), ("shop window", 5), ("downtown", 5),
        ("station", 4), ("bus stop", 5), ("bridge", 3), ("mall", 4),
    ]),
    ("nature", "自然·公园", [
        ("park", 5), ("garden", 6), ("forest", 8), ("grass", 5), ("trees", 4),
        ("flowers", 4), ("lake", 7), ("river", 5), ("mountain", 7),
        ("countryside", 7), ("field of", 5), ("outdoor", 4), ("sunlight", 2),
        ("golden hour", 3),
    ]),
    ("car", "车内", [
        ("car", 6), ("vehicle", 5), ("driving", 6), ("backseat", 7),
        ("driver seat", 7), ("steering wheel", 7),
    ]),
    ("indoor", "室内其他", [
        ("indoor", 3), ("room", 2), ("window", 2), ("apartment", 5),
        ("hallway", 5), ("stairs", 4), ("floor", 2),
    ]),
]
OTHER = ("other", "综合其他")

# 手工维护的分类：不走关键词分类、重建时原样保留（cat_<id>.json 与 img/<id>/ 都不动）。
# 用 tools/import_gallery_html.py 往里追加图片与提示词。
EXTRA_CATS = [
    ("mengmei", "萌妹"),
]


def classify(text):
    low = text.lower()
    best_id, best_score = None, 0
    for cat_id, _name, kws in RULES:
        score = 0
        for kw, weight in kws:
            if kw in low:
                # 高权重词（>=6）按出现次数叠加，弱词只算一次，避免“room”刷分
                score += weight * low.count(kw) if weight >= 6 else weight
        if score > best_score:
            best_id, best_score = cat_id, score
    return best_id or OTHER[0]


def _parse_js_array(html, name):
    """取出 `const NAME=[...]` 这个数组（JSON 兼容写法，直接按 JSON 解）。"""
    for key in (f"const {name}=", f"const {name} ="):
        start = html.find(key)
        if start >= 0:
            break
    else:
        return None
    arr = html.index("[", start)
    return json.JSONDecoder().raw_decode(html[arr:])[0]


def load_entries(html_path):
    """统一成 [{i: 序号, n: 原文件名, p: 提示词, b: 图片 data URI}]。

    见过三种写法，都要能吃：
    1) <script id="DATA" type="application/json">[...]</script>，每条自带 b
    2) const DATA=[...]，每条自带 b
    3) const DATA=[...] + const IMGS=[...]，图片按下标与 DATA 一一对应
    """
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    tag = '<script id="DATA" type="application/json">'
    start = html.find(tag)
    if start >= 0:
        end = html.find("</script>", start)
        raw, imgs = json.loads(html[start + len(tag):end]), None
    else:
        raw, imgs = _parse_js_array(html, "DATA"), _parse_js_array(html, "IMGS")
        if raw is None:
            raise SystemExit(f"{os.path.basename(html_path)} 里没找到 DATA，结构可能变了")
        if imgs is not None and len(imgs) != len(raw):
            raise SystemExit(f"{os.path.basename(html_path)} 的 DATA({len(raw)}) 与 IMGS({len(imgs)}) 数量不一致")

    out = []
    for pos, e in enumerate(raw):
        img = e.get("b") or (imgs[pos] if imgs else None)
        if not img:
            continue
        # 三种写法的「序号 / 文件名」字段名不同，逐个兜底
        if e.get("i") is not None:
            idx = int(e["i"])
        elif isinstance(e.get("n"), str) and e["n"].isdigit():
            idx = int(e["n"])
        elif isinstance(e.get("n"), int):
            idx = int(e["n"])
        else:
            idx = pos + 1
        fname = e.get("f")
        if not fname:
            n = e.get("n")
            fname = n if isinstance(n, str) and not n.isdigit() else f"item{idx}"
        out.append({"i": idx, "n": fname, "p": e["p"], "b": img})
    return out


def encode_image(raw, width, quality):
    """把缩略图按宽度缩一下再压成 WebP；压完更大就用原图。"""
    if not width:
        return raw
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        return raw
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if w > width:
        im = im.resize((width, max(1, round(h * width / w))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=5)
    out = buf.getvalue()
    return out if len(out) < len(raw) else raw


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("用法：python tools/build_ppg_templates.py [--width 180] [--quality 72] [--no-resize] <源 HTML ...>")

    img_width, img_quality = 180, 72
    sources = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--width":
            img_width = int(args[i + 1]); i += 2
        elif a == "--quality":
            img_quality = int(args[i + 1]); i += 2
        elif a == "--no-resize":
            img_width = 0; i += 1
        else:
            sources.append(a); i += 1
    if not sources:
        raise SystemExit("没给源 HTML")
    print(f"图片处理：{'保留原图' if not img_width else f'宽 {img_width}px / q{img_quality}'}")

    # 收集：按 (源序号, 条目) 存；提示词完全相同的只留第一次出现的
    entries = []
    seen = set()
    for src_idx, src in enumerate(sources, 1):
        batch = load_entries(src)
        kept = 0
        for e in batch:
            digest = hashlib.md5(e["p"].strip().encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            entries.append((src_idx, e))
            kept += 1
        print(f"源 {src_idx}: {os.path.basename(src)} -> {len(batch)} 条，去重后新增 {kept} 条")

    buckets = {}
    for src_idx, e in entries:
        buckets.setdefault(classify(e["p"]), []).append((src_idx, e))

    # 直接覆盖同名文件，不整目录删除（批量删文件风险高，也容易误删）。
    # 文件名与结构由分类 / 源序号 / 序号决定，重建后若有对不上的旧文件，末尾会报出来。
    img_root = os.path.join(OUT_DIR, "img")
    os.makedirs(img_root, exist_ok=True)
    written = set()

    order = [c[0] for c in RULES] + [OTHER[0]]
    names = {c[0]: c[1] for c in RULES}
    names[OTHER[0]] = OTHER[1]

    manifest = {"version": 1, "total": len(entries), "group": GROUP, "cats": []}
    img_bytes = 0
    orig_bytes = 0
    for cat_id in order:
        items = buckets.get(cat_id, [])
        if not items:
            continue
        items.sort(key=lambda t: (t[0], int(t[1]["i"])))

        out = []
        counters = {}
        for src_idx, e in items:
            seq = counters.get(src_idx, 0) + 1
            counters[src_idx] = seq
            cat_img_dir = os.path.join(img_root, cat_id, f"v{src_idx}")
            os.makedirs(cat_img_dir, exist_ok=True)
            fname = f"{seq:04d}.webp"
            raw = base64.b64decode(e["b"].split(",", 1)[1])
            data = encode_image(raw, img_width, img_quality)
            orig_bytes += len(raw)
            img_bytes += len(data)
            dest = os.path.join(cat_img_dir, fname)
            written.add(os.path.abspath(dest))
            with open(dest, "wb") as f:
                f.write(data)
            out.append({"s": f"img/{cat_id}/v{src_idx}/{fname}", "p": e["p"], "n": e["n"]})

        cat_file = f"cat_{cat_id}.json"
        with open(os.path.join(OUT_DIR, cat_file), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

        manifest["cats"].append({
            "id": cat_id,
            "name": names[cat_id],
            "count": len(out),
            "file": cat_file,
        })
        print(f"  {names[cat_id]:8} {len(out):5} 条")

    # 手工维护的分类：只读回自己的 cat_<id>.json 挂到清单最前，图片与条目一律不动
    for cat_id, cat_name in EXTRA_CATS:
        cat_file = f"cat_{cat_id}.json"
        cat_path = os.path.join(OUT_DIR, cat_file)
        if not os.path.isfile(cat_path):
            continue
        try:
            with open(cat_path, encoding="utf-8") as f:
                kept = json.load(f)
        except Exception as exc:
            print(f"  跳过 {cat_name}（读 {cat_file} 失败：{exc}）")
            continue
        if not kept:
            continue
        manifest["cats"].insert(0, {
            "id": cat_id,
            "name": cat_name,
            "count": len(kept),
            "file": cat_file,
        })
        manifest["total"] += len(kept)
        print(f"  {cat_name:8} {len(kept):5} 条（手工维护，保留）")

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("完成：", os.path.abspath(OUT_DIR), "| 合计", manifest["total"], "条")
    print(f"图片：{orig_bytes / 1024 / 1024:.1f} MB -> {img_bytes / 1024 / 1024:.1f} MB"
          f"（省 {100 - img_bytes * 100 / max(orig_bytes, 1):.0f}%）")

    stale = 0
    keep_dirs = [os.path.join(img_root, cid) for cid, _n in EXTRA_CATS]
    for root, _dirs, files in os.walk(img_root):
        if any(os.path.abspath(root).startswith(os.path.abspath(d)) for d in keep_dirs):
            continue
        for name in files:
            if os.path.abspath(os.path.join(root, name)) not in written:
                stale += 1
    if stale:
        print(f"注意：img/ 下还有 {stale} 个本次没有写到的旧文件（没有自动删除，需要的话手动清理）")


if __name__ == "__main__":
    main()
