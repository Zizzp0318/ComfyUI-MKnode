# -*- coding: utf-8 -*-
"""把画廊 HTML 里的图片 + 提示词**追加**到 MK-提示词预设图库 的某个分类。

与 build_ppg_templates.py（整体重建）互补：本脚本只动自己的分类，
不动其它分类的 cat_*.json 与 img/ 子目录，manifest 只做增量更新，可反复重跑（幂等）。

用法：
    python tools/import_gallery_html.py --html "画廊.html" --cat-id mengmei --cat-name 萌妹
    python tools/import_gallery_html.py --html "画廊.html" --cat-id mengmei --cat-name 萌妹 --width 180 --quality 72

支持的源 HTML 写法（自动探测）：
    1) const ITEMS=[...] / const DATA=[...]，每条含 p（提示词）+ img（data URI）
    2) const DATA=[...] + const IMGS=[...]（图片按下标对应）
    3) <script id="DATA" type="application/json">[...]</script>

产物：
    web/ppg_data/cat_<id>.json         [{"s": 缩略图相对路径, "p": 提示词, "n": 源序号}]
    web/ppg_data/img/<id>/v<n>/xxxx.webp
    web/ppg_data/manifest.json         分类清单 + total（增量）
"""

import argparse
import base64
import io
import json
import os
import re
import shutil
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "web", "ppg_data")


def _js_array(html, name):
    for key in ("const %s = " % name, "const %s=" % name):
        i = html.find(key)
        if i >= 0:
            arr = html.index("[", i)
            return json.JSONDecoder().raw_decode(html[arr:])[0]
    return None


def load_entries(html_path):
    with open(html_path, "r", encoding="utf-8", errors="replace") as fh:
        html = fh.read()

    tag = '<script id="DATA" type="application/json">'
    start = html.find(tag)
    if start >= 0:
        end = html.find("</script>", start)
        raw, imgs = json.loads(html[start + len(tag):end]), None
    else:
        raw = _js_array(html, "ITEMS") or _js_array(html, "DATA")
        imgs = _js_array(html, "IMGS")
        if raw is None:
            raise SystemExit("%s 里没找到 ITEMS/DATA" % os.path.basename(html_path))
        if imgs is not None and len(imgs) != len(raw):
            raise SystemExit("DATA(%d) 与 IMGS(%d) 数量不一致" % (len(raw), len(imgs)))

    out = []
    for pos, e in enumerate(raw):
        blob = e.get("img") or e.get("b") or (imgs[pos] if imgs else None)
        if not blob:
            continue
        prompt = (e.get("p") or "").strip()
        if not prompt:
            continue
        no = e.get("no") if e.get("no") is not None else e.get("i", pos + 1)
        out.append({"no": int(no), "p": prompt, "b": blob})
    return out


def encode(blob, width, quality):
    """缩到指定宽度压成 WebP；压完反而更大就用原始字节。"""
    raw = base64.b64decode(blob.split(",", 1)[1]) if "," in blob else base64.b64decode(blob)
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
    data = buf.getvalue()
    return data if len(data) < len(raw) else raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--cat-id", required=True, help="分类 id，例如 mengmei")
    ap.add_argument("--cat-name", required=True, help="分类显示名，例如 萌妹")
    ap.add_argument("--width", type=int, default=180, help="缩略图宽度，0=保留原图")
    ap.add_argument("--quality", type=int, default=72, help="WebP 质量")
    ap.add_argument("--top", action="store_true", help="分类放在清单最前（默认插到首位）")
    args = ap.parse_args()

    entries = load_entries(args.html)
    print("源条目：%d（%s）" % (len(entries), os.path.basename(args.html)))
    if not entries:
        raise SystemExit("源文件里没有可用条目")

    cat_id = args.cat_id
    img_dir = os.path.join(DATA_DIR, "img", cat_id, "v1")
    os.makedirs(img_dir, exist_ok=True)
    for name in os.listdir(img_dir):           # 清掉本分类上次的残留
        p = os.path.join(img_dir, name)
        if os.path.isfile(p):
            os.remove(p)

    out, raw_total, img_total = [], 0, 0
    for idx, e in enumerate(entries, 1):
        fname = "%04d.webp" % idx
        dest = os.path.join(img_dir, fname)
        data = encode(e["b"], args.width, args.quality)
        with open(dest, "wb") as fh:
            fh.write(data)
        raw_total += len(base64.b64decode(e["b"].split(",", 1)[1]) if "," in e["b"] else b"")
        img_total += len(data)
        out.append({"s": "img/%s/v1/%s" % (cat_id, fname), "p": e["p"], "n": "src_%03d" % e["no"]})

    cat_file = "cat_%s.json" % cat_id
    with open(os.path.join(DATA_DIR, cat_file), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print("写入 %s：%d 条" % (cat_file, len(out)))

    man_path = os.path.join(DATA_DIR, "manifest.json")
    if os.path.isfile(man_path):
        shutil.copy2(man_path, man_path + ".bak")
        with open(man_path, "r", encoding="utf-8") as fh:
            man = json.load(fh)
    else:
        man = {"version": 1, "total": 0, "group": {"id": "portrait", "name": "写真图片"}, "cats": []}

    others = [c for c in man.get("cats", []) if c.get("id") != cat_id]
    base_total = sum(int(c.get("count") or 0) for c in others)
    if not base_total:
        base_total = int(man.get("total") or 0)
    entry = {"id": cat_id, "name": args.cat_name, "count": len(out), "file": cat_file}
    man["cats"] = [entry] + others          # 萌妹放最前，打开就看得见
    man["total"] = base_total + len(out)
    man.setdefault("version", 1)
    man.setdefault("group", {"id": "portrait", "name": "写真图片"})
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=2)

    print("manifest：total=%d，分类 %d 个" % (man["total"], len(man["cats"])))
    print("图片：%.1f MB -> %.2f MB（%d 张，平均 %.1f KB）" % (
        raw_total / 1048576.0, img_total / 1048576.0, len(out), img_total / 1024.0 / max(1, len(out))))
    print("分类顺序：" + " / ".join("%s(%s)" % (c["name"], c["count"]) for c in man["cats"]))


if __name__ == "__main__":
    sys.exit(main())
