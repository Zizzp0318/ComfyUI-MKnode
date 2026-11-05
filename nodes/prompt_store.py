"""MK 提示词存储 API（``/mk_prompt_store``）

原本注册在 ``nodes/prompt_preset.py``（MK-提示词预设管理）里。该节点移除后，
仍有一个使用方需要这条路由：**MK-提示词大全**（``MK_PromptLibrary``）
的前端 ``web/prompt_library.js`` 把整个提示词库 JSON 存在这里
（key = ``mk_prompt_library``）。因此把路由独立成模块，保持路径与行为不变。

数据落在 ``<ComfyUI 用户目录>/Comfyui_MKnode/<key>.json``，
位于插件目录之外，更新/整体替换插件目录时不会丢数据。

路径：/mk_prompt_store
  GET  ?key=<name>  -> {"key","data","found"}
  POST {key,data}   -> {"ok":true}
"""

import os
import json
import logging

from aiohttp import web
from server import PromptServer

# 后端存储路由（前端 web/prompt_library.js 依赖此路径，改动需同步）
ROUTE_STORE = "/mk_prompt_store"
# 存储子目录名（落在 ComfyUI 用户目录下，位于插件目录之外，更新插件不丢数据）
_STORE_SUBDIR = "Comfyui_MKnode"


def _mk_store_dir():
    """返回存储目录（<user_dir>/Comfyui_MKnode），并确保存在。"""
    try:
        import folder_paths  # 延迟导入：避免在无 ComfyUI 环境的静态检查时报错
        base = folder_paths.get_user_directory()
    except Exception:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_data")
    d = os.path.join(base, _STORE_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def _mk_store_safe_key(key):
    """仅允许 [A-Za-z0-9_.-]，防止路径穿越。"""
    if not isinstance(key, str):
        return None
    key = key.strip()
    if not key or len(key) > 128:
        return None
    if not key.replace(".", "").replace("-", "").replace("_", "").isalnum():
        return None
    return key


async def _mk_store_get(request):
    key = _mk_store_safe_key(request.rel_url.query.get("key", ""))
    if not key:
        return web.json_response({"error": "invalid key"}, status=400)
    path = os.path.join(_mk_store_dir(), key + ".json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response({"key": key, "data": data, "found": True})
    except FileNotFoundError:
        return web.json_response({"key": key, "data": None, "found": False})
    except Exception as e:
        return web.json_response({"key": key, "data": None, "found": False, "error": str(e)})


async def _mk_store_post(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)
    key = _mk_store_safe_key(body.get("key"))
    if not key:
        return web.json_response({"error": "invalid key"}, status=400)
    path = os.path.join(_mk_store_dir(), key + ".json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body.get("data"), f, ensure_ascii=False, indent=2)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def _register_store_routes():
    """注册存储路由。

    PromptServer 未初始化时只告警不抛异常——否则整个包导入失败，
    会把其余 MK 节点一起带下线。真实运行环境下 instance 一定存在。
    """
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        logging.warning("[MK] PromptServer 尚未初始化，MK-提示词大全的存储路由未注册")
        return
    instance.routes.get(ROUTE_STORE)(_mk_store_get)
    instance.routes.post(ROUTE_STORE)(_mk_store_post)


_register_store_routes()
