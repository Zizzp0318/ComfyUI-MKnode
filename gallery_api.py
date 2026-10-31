"""HTTP 路由：把图库暴露给前端（索引 / 缩略图 / 原图 / 导入 / 删除）。

一个库一组 /<prefix>/*（姿态库 = /mkposes/*），加库只需在 register() 里补一行。

图片一律走 ?name=<文件名>，不用 {name} 路径模板 —— 用户文件名里可能有花括号
（从浏览器复制的图片常叫 {F8B9D27A-...}.jpg），aiohttp 的路径模板匹配不了，
会 404 得莫名其妙。
"""

import asyncio
import json
from pathlib import Path

from aiohttp import web

from .mkg import library, paths, store
from .mkg.constants import IMAGE_EXTS, LIB_NAMES, MAX_UPLOAD_BYTES
from .mkg.errors import GalleryMissing
from .mkg.util import log

try:
    from server import PromptServer
except ImportError:  # 脱离 ComfyUI 单独导入时不注册路由
    PromptServer = None

MAX_META_BYTES = 64 * 1024
CHUNK = 64 * 1024
THUMB_EXTS = (".jpg", ".jpeg")


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(
        data,
        status=status,
        dumps=lambda obj: json.dumps(obj, ensure_ascii=False),
        headers={"Cache-Control": "no-cache"},
    )


def _serve(folder: Path, name: str, exts) -> web.Response:
    """只允许读 folder 下的文件；name 里的路径部分一律丢掉，后缀按白名单放行。"""
    safe = Path(str(name or "")).name
    target = (folder / safe).resolve()
    if folder.resolve() not in target.parents or not target.is_file():
        raise web.HTTPNotFound()
    if target.suffix.lower() not in exts:
        raise web.HTTPNotFound()
    # 图片可能被同名覆盖（用户重导一张），所以只允许协商缓存，不能强缓存
    return web.FileResponse(target, headers={"Cache-Control": "no-cache"})


async def _read_limited(part, limit: int, label: str) -> bytes:
    """流式读一个上传分片，超过 limit 立刻停，不把内存吃满。"""
    chunks, total = [], 0
    while True:
        chunk = await part.read_chunk(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError(f"{label}超过 {limit // (1024 * 1024)} MB 上限")
        chunks.append(chunk)
    return b"".join(chunks)


def _make_handlers(lib: str):
    """为某个库生成一组处理函数，闭包各自捕获 lib，互不影响。"""
    name = LIB_NAMES.get(lib, lib)

    async def lib_index(request):
        try:
            data = await asyncio.to_thread(library.index, lib)
        except GalleryMissing as err:
            return _json({"error": str(err)}, status=503)
        except Exception as err:  # 数据文件坏了之类，别让前端只看到 500 空白
            log(f"[MK 图库] {name}索引读取失败：{err}")
            return _json({"error": f"{name}索引读取失败：{err}"}, status=500)
        return _json(data)

    async def lib_thumb(request):
        file = request.query.get("name") or ""
        path = await asyncio.to_thread(store.ensure_thumb, lib, file)
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})

    async def lib_img(request):
        return _serve(paths.img_dir(lib), request.query.get("name") or "", IMAGE_EXTS)

    async def lib_upload(request):
        if not request.content_type.startswith("multipart/"):
            return _json({"error": "导入接口只接受 multipart/form-data 上传"}, status=400)
        try:
            reader = await request.multipart()
        except Exception as err:
            return _json({"error": f"读取上传内容失败：{err}"}, status=400)

        uploads, meta = [], {}
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "meta":
                try:
                    raw = await _read_limited(part, MAX_META_BYTES, "表单信息")
                    meta = json.loads(raw.decode("utf-8", "replace")) or {}
                except Exception:
                    meta = {}
                continue
            if part.name != "images" or not part.filename:
                continue
            try:
                data = await _read_limited(part, MAX_UPLOAD_BYTES, f"「{part.filename}」")
            except ValueError as err:
                uploads.append((part.filename, None, str(err)))
                continue
            uploads.append((part.filename, data, None))

        if not uploads:
            return _json({"error": "没有收到图片文件"}, status=400)

        good = [(filename, data) for filename, data, error in uploads if not error]
        failed = [
            {"name": filename, "error": error} for filename, _data, error in uploads if error
        ]
        if good:
            saved, more_failed = await asyncio.to_thread(
                store.add_many, lib, good, meta.get("name"), meta.get("cat")
            )
            failed.extend(more_failed)
        else:
            saved = []

        index = await asyncio.to_thread(library.index, lib)
        # ids 与 saved 一一对应：前端拿它跳到刚落盘的那张（显示名由用户填，不能从文件名推）
        return _json(
            {
                "ids": saved,
                "failed": failed,
                "total": index["total"],
                "categories": index["categories"],
            }
        )

    async def lib_delete(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        files = payload.get("files")
        if not isinstance(files, list):
            files = [payload.get("file")]
        files = [str(item) for item in files if item]
        if not files:
            return _json({"error": "缺少要删除的文件名"}, status=400)

        deleted = [item for item in files if await asyncio.to_thread(store.remove, lib, item)]
        if not deleted:
            return _json({"error": f"{name}里没找到这些图：{'、'.join(files)}"}, status=404)
        index = await asyncio.to_thread(library.index, lib)
        return _json({"deleted": deleted, "total": index["total"]})

    async def lib_reveal(request):
        """告诉前端数据到底在哪个目录（页脚右键 / 复制路径用）。"""
        return _json(
            {
                "lib": lib,
                "dir": str(paths.lib_dir(lib)),
                "img": str(paths.img_dir(lib)),
                "index": str(paths.index_file(lib)),
            }
        )

    return [
        ("/index.json", lib_index, "GET"),
        ("/thumb", lib_thumb, "GET"),
        ("/img", lib_img, "GET"),
        ("/upload", lib_upload, "POST"),
        ("/delete", lib_delete, "POST"),
        ("/paths", lib_reveal, "GET"),
    ]


def register_lib(lib: str, prefix: str) -> None:
    instance = getattr(PromptServer, "instance", None) if PromptServer else None
    if instance is None:
        return
    routes = instance.routes
    for path, handler, method in _make_handlers(lib):
        getattr(routes, method.lower())(f"/{prefix}{path}")(handler)


def register() -> None:
    # 加库只需在此追加一行
    register_lib("pose", "mkposes")
    register_lib("garment", "mkgarments")
    register_lib("face", "mkfaces")


try:
    register()
except Exception as err:  # 路由冲突之类，别把整个 ComfyUI 启动拖死
    log(f"[MK 图库] 路由注册失败（节点仍可用）：{err}")
