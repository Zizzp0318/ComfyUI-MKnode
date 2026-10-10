"""MK-提示词大全（MK_PromptLibrary）

以 ``MK-提示词预设管理``（``nodes/prompt_preset.py`` + ``web/prompt_preset.js``）为原型
派生的**图片化提示词库**节点。相对预设管理节点：

取消：
- 输出端的「数字转中文」（原 ``text_zh_num``），只保留单一 ``text`` 输出；
- 输入端的「提示词类型」「提示词细分」两个下拉控件。

新增：
- 「提示词预设选择」按钮（替代原「提示词预设管理」），弹出**多级分类树 + 缩略图网格**；
- 支持上传提示词配图（**只保存压缩后的缩略图**，原图不落盘）、编辑提示词、移动分类；
- 点击网格中的图片 → 直接把该条提示词写入节点文本框。

数据结构（独立于预设管理，互不影响）：
    {
      "version": 1,
      "tree": [
        {
          "id": "c_xxx", "name": "人像", "order": 1000,
          "children": [ { "id": "c_yyy", "name": "城市", "children": [], "items": [] } ],
          "items": [ { "id": "p_zzz", "name": "特写", "prompt": "……",
                       "thumb": "t_abc.webp", "order": 1000 } ]
        }
      ]
    }

存储：
- 库数据（JSON）复用 ``/mk_prompt_store``（见 ``prompt_preset.py``），key = ``mk_prompt_library``；
- 缩略图二进制另走后端资源路由 ``/mk_prompt_asset``，落盘于
  ``<ComfyUI 用户目录>/Comfyui_MKnode/mk_prompt_assets/``（插件目录之外，更新插件不丢数据）。
"""

import os
import re
import base64
import secrets
import logging

from aiohttp import web
from server import PromptServer

# 后端资源路由（前端 web/prompt_library.js 依赖此路径，改动需同步）
ROUTE_ASSET = "/mk_prompt_asset"
# 存储子目录名（与 prompt_preset.py 保持一致，落在 ComfyUI 用户目录下）
_STORE_SUBDIR = "Comfyui_MKnode"
# 缩略图子目录
_ASSET_SUBDIR = "mk_prompt_assets"
# 单张缩略图体积上限（前端已压缩到 ~10-20KB，此处仅作兜底防护）
_MAX_ASSET_BYTES = 4 * 1024 * 1024

_MIME_EXT = {
    "image/webp": "webp",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
}
_EXT_MIME = {
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
}
# 资源文件名白名单：字母/数字开头，仅允许 [A-Za-z0-9_.-]
_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,96}$")


class _MKTextType(str):
    """与 Comfyroll 文本端口一致：可连接到任意下游输入类型。"""

    def __ne__(self, other):
        return False


_MK_TEXT_TYPE = _MKTextType("*")


class MKPromptLibrary:
    """MK-提示词大全（MK_PromptLibrary）

    单一文本输入/输出 + 「提示词预设选择」按钮。图片化的提示词库放在前端弹窗里
    （多级分类树 + 缩略图网格），点图即把提示词写回文本框。
    """

    DESCRIPTION = (
        "图片化提示词库：点击「提示词预设选择」，在缩略图网格中点选图片即可把对应提示词"
        "填入文本框；支持多级分类、上传配图（只存压缩缩略图）、编辑与移动。"
    )
    SEARCH_ALIASES = [
        "prompt library", "prompt gallery", "prompt manager", "text box",
        "提示词大全", "提示词库", "提示词选择", "文本框", "图片提示词",
    ]
    CATEGORY = "MK节点"
    FUNCTION = "execute"
    RETURN_TYPES = (_MK_TEXT_TYPE,)
    RETURN_NAMES = ("text",)
    OUTPUT_TOOLTIPS = ("选中的提示词文本。",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "",
                }),
            },
        }

    def execute(self, text):
        return (text if text is not None else "",)


# ============ MK 提示词库 · 缩略图资源 API ============
# 前端 web/prompt_library.js 上传/读取缩略图走这里。
#
# 路径：/mk_prompt_asset
#   POST {dataUrl, mime?}          -> {"ok":true,"name":"t_xxx.webp"}
#   POST {action:"delete", name}   -> {"ok":true}
#   GET  ?name=<file>              -> 图片字节（长缓存）


def _mk_asset_dir():
    """返回缩略图目录（<user_dir>/Comfyui_MKnode/mk_prompt_assets），并确保存在。"""
    try:
        import folder_paths  # 延迟导入：避免在无 ComfyUI 环境的静态检查时报错
        base = folder_paths.get_user_directory()
    except Exception:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_data")
    d = os.path.join(base, _STORE_SUBDIR, _ASSET_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def _mk_safe_asset_name(name):
    """校验资源文件名，防止路径穿越。"""
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or len(name) > 96:
        return None
    if ".." in name or "/" in name or "\\" in name:
        return None
    if not _ASSET_NAME_RE.match(name):
        return None
    return name


async def _mk_asset_post(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)

    action = str(body.get("action") or "upload")

    # ── 删除 ──
    if action == "delete":
        name = _mk_safe_asset_name(body.get("name"))
        if not name:
            return web.json_response({"error": "invalid name"}, status=400)
        path = os.path.join(_mk_asset_dir(), name)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"ok": True})

    # ── 上传（dataURL）──
    data_url = body.get("dataUrl") or body.get("data_url")
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return web.json_response({"error": "missing dataUrl"}, status=400)
    try:
        header, b64 = data_url.split(",", 1)
    except ValueError:
        return web.json_response({"error": "bad dataUrl"}, status=400)

    mime = header[5:].split(";", 1)[0].strip().lower()
    ext = _MIME_EXT.get(mime)
    if not ext:
        return web.json_response({"error": "unsupported image type: " + mime}, status=400)

    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return web.json_response({"error": "bad base64"}, status=400)
    if not raw:
        return web.json_response({"error": "empty image"}, status=400)
    if len(raw) > _MAX_ASSET_BYTES:
        return web.json_response({"error": "image too large"}, status=413)

    name = "t_" + secrets.token_hex(8) + "." + ext
    try:
        with open(os.path.join(_mk_asset_dir(), name), "wb") as f:
            f.write(raw)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"ok": True, "name": name})


async def _mk_asset_get(request):
    name = _mk_safe_asset_name(request.rel_url.query.get("name", ""))
    if not name:
        return web.Response(status=400, text="invalid name")
    path = os.path.join(_mk_asset_dir(), name)
    if not os.path.isfile(path):
        return web.Response(status=404, text="not found")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    ctype = _EXT_MIME.get(ext, "application/octet-stream")
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        return web.Response(status=500, text=str(e))
    # 文件名随机、内容不变，可长期缓存
    return web.Response(
        body=data,
        content_type=ctype,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def _register_asset_routes():
    """注册资源路由。

    PromptServer 未初始化时只告警不抛异常——否则整个包导入失败，
    会把其余 MK 节点一起带下线。真实运行环境下 instance 一定存在。
    """
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        logging.warning("[MK] PromptServer 尚未初始化，MK-提示词大全的资源路由未注册")
        return
    instance.routes.get(ROUTE_ASSET)(_mk_asset_get)
    instance.routes.post(ROUTE_ASSET)(_mk_asset_post)


_register_asset_routes()
