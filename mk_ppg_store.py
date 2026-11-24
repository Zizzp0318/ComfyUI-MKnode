"""MK-提示词预设图库 · 用户数据存储（``/mk_ppg/*``）

用户自建的分类树、素材图片、提示词都落在**插件目录之外**，更新/重装插件不会丢：

    <ComfyUI>/user/default/MKnode/Prompt Preset/
        tree.json                 分类树（可嵌套，任意层）
        <分类 id>/items.json      该分类的素材条目 [{"f": 文件名, "p": 提示词, "t": 时间戳}]
        <分类 id>/0001.webp       素材图（上传后统一转 WebP，长边 320）

删除分类是真删除：`rmcat` 直接删掉分类目录（items.json + 全部素材图），不留副本。

路由：
    GET  /mk_ppg/tree?                  -> {"cats": [...]}（每个节点带 count）
    POST /mk_ppg/tree                   {"cats": [...]}
    GET  /mk_ppg/items?cat=<id>         -> {"items": [...]}
    POST /mk_ppg/items?cat=<id>         {"items": [...]}
    POST /mk_ppg/upload?cat=<id>        multipart: prompt + image(可选) -> {"item": {...}}
    POST /mk_ppg/move                   {"from","to","index"} 素材换分类（图片文件一起搬）
    POST /mk_ppg/rmcat?cat=<id>         真删除该分类目录（不可恢复）
    GET  /mk_ppg/asset?cat=<id>&f=<名>  素材图
"""

import io
import json
import logging
import os
import re
import shutil
import time

from aiohttp import web

try:
    from server import PromptServer
except ImportError:          # 脱离 ComfyUI 单独导入时不注册路由
    PromptServer = None

BASE_SUBDIR = ("default", "MKnode", "Prompt Preset")
CAT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}\.(webp|png|jpg|jpeg)$", re.I)
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
THUMB_WIDTH = 320
THUMB_QUALITY = 82
MAX_TREE_DEPTH = 4


# ───────────────────────── 基础路径 / 读写 ─────────────────────────

def base_dir() -> str:
    try:
        import folder_paths
        root = folder_paths.get_user_directory()
    except Exception:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_data")
    d = os.path.join(root, *BASE_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def cat_dir(cat_id: str) -> str:
    return os.path.join(base_dir(), cat_id)


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: str, obj) -> None:
    """先写临时文件再替换，避免写一半断电留下坏 JSON。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _json(data, status: int = 200):
    return web.json_response(
        data, status=status,
        dumps=lambda o: json.dumps(o, ensure_ascii=False),
        headers={"Cache-Control": "no-cache"},
    )


def _err(msg: str, status: int = 400):
    return _json({"ok": False, "error": msg}, status=status)


# ───────────────────────── 分类树 ─────────────────────────

def _clean_name(name) -> str:
    if not isinstance(name, str):
        return ""
    return name.strip()[:40]


def _sanitize_nodes(nodes, depth: int = 0) -> list:
    """只保留合法的节点：id 合规、名字非空、去重、层数受限。"""
    out = []
    seen = set()
    if not isinstance(nodes, list) or depth > MAX_TREE_DEPTH:
        return out
    for node in nodes:
        if not isinstance(node, dict):
            continue
        cid = node.get("id")
        name = _clean_name(node.get("name"))
        if not isinstance(cid, str) or not CAT_ID_RE.match(cid) or cid in seen or not name:
            continue
        seen.add(cid)
        out.append({
            "id": cid,
            "name": name,
            "children": _sanitize_nodes(node.get("children"), depth + 1),
        })
    return out


def load_tree() -> list:
    data = _read_json(os.path.join(base_dir(), "tree.json"), {"cats": []})
    cats = data.get("cats") if isinstance(data, dict) else None
    return _sanitize_nodes(cats or [])


def save_tree(nodes: list) -> list:
    cleaned = _sanitize_nodes(nodes)
    _write_json(os.path.join(base_dir(), "tree.json"), {"cats": cleaned})
    return cleaned


def _count_items(cat_id: str) -> int:
    items = _read_json(os.path.join(cat_dir(cat_id), "items.json"), [])
    return len(items) if isinstance(items, list) else 0


def _tree_with_counts(nodes: list) -> list:
    out = []
    for node in nodes:
        out.append({
            "id": node["id"],
            "name": node["name"],
            "count": _count_items(node["id"]),
            "children": _tree_with_counts(node.get("children") or []),
        })
    return out


# ───────────────────────── 素材条目 ─────────────────────────

def load_items(cat_id: str) -> list:
    raw = _read_json(os.path.join(cat_dir(cat_id), "items.json"), [])
    if not isinstance(raw, list):
        return []
    out = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        prompt = it.get("p")
        if not isinstance(prompt, str):
            continue
        fname = it.get("f") if isinstance(it.get("f"), str) else ""
        if fname and not FILE_RE.match(fname):
            fname = ""
        out.append({"f": fname, "p": prompt, "t": it.get("t") or 0})
    return out


def save_items(cat_id: str, items: list) -> list:
    os.makedirs(cat_dir(cat_id), exist_ok=True)
    cleaned = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("p"), str):
            continue
        fname = it.get("f") if isinstance(it.get("f"), str) else ""
        if fname and not FILE_RE.match(fname):
            continue
        cleaned.append({"f": fname, "p": it["p"], "t": it.get("t") or 0})
    _write_json(os.path.join(cat_dir(cat_id), "items.json"), cleaned)
    return cleaned


def _next_seq(folder: str) -> int:
    biggest = 0
    try:
        for name in os.listdir(folder):
            stem = name.split(".")[0]
            if stem.isdigit():
                biggest = max(biggest, int(stem))
    except OSError:
        pass
    return biggest + 1


def _to_webp(raw: bytes):
    """上传图统一转 WebP（长边 320）；不是图片就返回 None。"""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        return None
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > THUMB_WIDTH:
        scale = THUMB_WIDTH / max(w, h)
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=THUMB_QUALITY, method=5)
    return buf.getvalue()


# ───────────────────────── 路由 ─────────────────────────

async def get_tree(request):
    try:
        return _json({"ok": True, "cats": _tree_with_counts(load_tree())})
    except Exception as exc:
        logging.exception("[MK] 读取分类树失败")
        return _err(f"读取分类树失败：{exc}", 500)


async def post_tree(request):
    try:
        body = await request.json()
    except Exception:
        return _err("请求体不是合法 JSON")
    try:
        saved = save_tree(body.get("cats") if isinstance(body, dict) else [])
        return _json({"ok": True, "cats": _tree_with_counts(saved)})
    except Exception as exc:
        logging.exception("[MK] 保存分类树失败")
        return _err(f"保存分类树失败：{exc}", 500)


async def get_items(request):
    cat = request.query.get("cat", "")
    if not CAT_ID_RE.match(cat):
        return _err("分类 id 非法")
    try:
        return _json({"ok": True, "items": load_items(cat)})
    except Exception as exc:
        return _err(f"读取素材失败：{exc}", 500)


async def post_items(request):
    cat = request.query.get("cat", "")
    if not CAT_ID_RE.match(cat):
        return _err("分类 id 非法")
    try:
        body = await request.json()
    except Exception:
        return _err("请求体不是合法 JSON")
    try:
        items = save_items(cat, body.get("items") if isinstance(body, dict) else [])
        return _json({"ok": True, "items": items})
    except Exception as exc:
        logging.exception("[MK] 保存素材失败")
        return _err(f"保存素材失败：{exc}", 500)


async def post_upload(request):
    cat = request.query.get("cat", "")
    if not CAT_ID_RE.match(cat):
        return _err("分类 id 非法")

    prompt = ""
    image_bytes = None
    try:
        reader = await request.multipart()
    except Exception:
        return _err("需要 multipart 上传")

    try:
        async for part in reader:
            if part.name == "prompt":
                prompt = (await part.text()).strip()
            elif part.name == "image" and part.filename:
                chunk = bytearray()
                while True:
                    piece = await part.read_chunk(64 * 1024)
                    if not piece:
                        break
                    chunk.extend(piece)
                    if len(chunk) > MAX_UPLOAD_BYTES:
                        return _err("图片太大（上限 12MB）", 413)
                image_bytes = bytes(chunk)
    except Exception as exc:
        return _err(f"解析上传内容失败：{exc}")

    if not prompt and not image_bytes:
        return _err("提示词和图片至少给一个")

    folder = cat_dir(cat)
    os.makedirs(folder, exist_ok=True)

    fname = ""
    if image_bytes:
        webp = _to_webp(image_bytes)
        if webp is None:
            return _err("这个文件不是可识别的图片")
        seq = _next_seq(folder)
        fname = f"{seq:04d}.webp"
        with open(os.path.join(folder, fname), "wb") as f:
            f.write(webp)

    items = load_items(cat)
    item = {"f": fname, "p": prompt, "t": int(time.time())}
    items.append(item)
    save_items(cat, items)
    return _json({"ok": True, "item": item, "count": len(items)})


async def post_move(request):
    """把某条素材从 A 分类挪到 B 分类：图片文件一起搬，目标重名就重新编号。"""
    try:
        body = await request.json()
    except Exception:
        return _err("请求体不是合法 JSON")
    if not isinstance(body, dict):
        return _err("请求体格式不对")

    src = body.get("from", "")
    dst = body.get("to", "")
    try:
        index = int(body.get("index", -1))
    except (TypeError, ValueError):
        return _err("序号非法")
    if not CAT_ID_RE.match(src or "") or not CAT_ID_RE.match(dst or ""):
        return _err("分类 id 非法")
    if src == dst:
        return _err("目标分类和当前分类相同")

    src_items = load_items(src)
    if index < 0 or index >= len(src_items):
        return _err("素材序号越界", 404)

    item = src_items.pop(index)
    fname = item.get("f") or ""
    if fname:
        src_path = os.path.join(cat_dir(src), fname)
        if os.path.isfile(src_path):
            os.makedirs(cat_dir(dst), exist_ok=True)
            dst_path = os.path.join(cat_dir(dst), fname)
            if os.path.exists(dst_path):          # 目标已有同名文件，换个号
                fname = f"{_next_seq(cat_dir(dst)):04d}.webp"
                item["f"] = fname
                dst_path = os.path.join(cat_dir(dst), fname)
            os.replace(src_path, dst_path)
        else:
            item["f"] = ""                        # 图已经不在了，当纯文本挪过去

    dst_items = load_items(dst)
    dst_items.append(item)

    save_items(src, src_items)
    save_items(dst, dst_items)
    return _json({
        "ok": True,
        "item": item,
        "from_items": src_items,
        "to_items": dst_items,
        "from_count": len(src_items),
        "to_count": len(dst_items),
    })


async def post_rmcat(request):
    """真删除分类目录：items.json 与全部素材图一起删掉，不进回收站。"""
    cat = request.query.get("cat", "")
    if not CAT_ID_RE.match(cat):
        return _err("分类 id 非法")
    folder = cat_dir(cat)
    if not os.path.isdir(folder):
        return _json({"ok": True, "removed": False})
    # 只允许删 base_dir 正下方的那一级目录，防止任何路径拼接意外删到别处
    root = os.path.abspath(base_dir())
    if os.path.dirname(os.path.abspath(folder)) != root:
        return _err("分类路径越界", 403)
    try:
        shutil.rmtree(folder)
        return _json({"ok": True, "removed": True})
    except Exception as exc:
        logging.exception("[MK] 删除分类目录失败")
        return _err(f"删除分类失败：{exc}", 500)


async def get_asset(request):
    cat = request.query.get("cat", "")
    fname = request.query.get("f", "")
    if not CAT_ID_RE.match(cat) or not FILE_RE.match(fname):
        return _err("参数非法")
    folder = cat_dir(cat)
    path = os.path.join(folder, fname)
    # 防目录穿越：解析后的真实路径必须还在分类目录里
    if os.path.commonpath([os.path.realpath(path), os.path.realpath(folder)]) != os.path.realpath(folder):
        return _err("参数非法", 403)
    if not os.path.isfile(path):
        return _err("文件不存在", 404)
    return web.FileResponse(path, headers={"Cache-Control": "max-age=3600"})


def _register(method: str, path: str, handler) -> None:
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        logging.warning("[MK] PromptServer 尚未初始化，提示词预设图库的存储路由未注册")
        return
    getattr(instance.routes, method)(path)(handler)


for _method, _path, _handler in (
    ("get", "/mk_ppg/tree", get_tree),
    ("post", "/mk_ppg/tree", post_tree),
    ("get", "/mk_ppg/items", get_items),
    ("post", "/mk_ppg/items", post_items),
    ("post", "/mk_ppg/upload", post_upload),
    ("post", "/mk_ppg/move", post_move),
    ("post", "/mk_ppg/rmcat", post_rmcat),
    ("get", "/mk_ppg/asset", get_asset),
):
    _register(_method, _path, _handler)
