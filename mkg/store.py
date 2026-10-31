"""图库数据层：library.json 的读写、img/ 目录对齐、导入与删除。

一个文件 = 一个条目（单图库，没有视角概念）。数据只有两份东西：

    library.json   {version, categories[], items[{id,name,cat,file,added}]}
    img/           图片本体，文件名由显示名派生
    thumbs/        缩略图，派生文件，删了会重建

**目录即真相的一半**：用户直接把图片丢进 img/ 也会被认出来（扫描时补登记，
分类记为「未分类」）。所以扫描要和 library.json 对齐，两边对不上时以文件为准。
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from . import paths
from .constants import IMAGE_EXTS, UNSORTED
from .images import clean_label, safe_stem, to_thumb_bytes, to_webp_bytes
from .util import atomic_write_bytes, atomic_write_text, log

_lock = threading.RLock()
_cache: dict = {}  # lib -> {"sig": (json_mtime, dir_sig), "data": dict}


# ------------------------------------------------------------------ 基础读写


def _mtime(path: Path) -> Optional[int]:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _dir_sig(folder: Path) -> tuple:
    """目录签名：文件数 + 最新 mtime。同名覆盖源图时目录 mtime 不变，
    光看目录会漏判，所以带上每个文件里最新的那个。
    """
    try:
        entries = [e for e in os.scandir(folder) if e.is_file()]
    except OSError:
        return (0, 0)
    newest = 0
    for entry in entries:
        try:
            newest = max(newest, entry.stat().st_mtime_ns)
        except OSError:
            continue
    return (len(entries), newest)


def _empty() -> dict:
    return {"version": 1, "categories": [], "items": []}


def _new_id(taken: set) -> str:
    while True:
        value = uuid.uuid4().hex[:8]
        if value not in taken:
            return value


def _read(lib: str) -> dict:
    path = paths.index_file(lib)
    data = None
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as err:
            log(f"[MK 图库] {path} 读不出来，按空库重建：{err}")
    if not isinstance(data, dict):
        data = _empty()
    data.setdefault("version", 1)
    data.setdefault("categories", [])
    data.setdefault("items", [])
    if not isinstance(data["categories"], list):
        data["categories"] = []
    if not isinstance(data["items"], list):
        data["items"] = []
    return data


def _write(lib: str, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    atomic_write_text(paths.index_file(lib), payload + "\n")


# ------------------------------------------------------------------ 与 img/ 对齐


def _reconcile(data: dict, lib: str) -> bool:
    """让 items 与 img/ 里的实际文件对齐。返回是否改动过（需要写盘）。

    - 条目指向的文件不在了 → 删条目（顺手清缩略图），工作流里选它时会得到友好报错；
    - 目录里有条目没登记的文件 → 补登记成「未分类」，名字取文件名；
    - 同名不同后缀（a.png / a.webp）只认一个，避免同一个图出现两次。
    """
    folder = paths.img_dir(lib)
    try:
        present = {
            entry.name
            for entry in os.scandir(folder)
            if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTS
        }
    except OSError:
        present = set()

    changed = False
    kept, used_stems, taken_ids = [], set(), set()

    for raw in data["items"]:
        if not isinstance(raw, dict):
            changed = True
            continue
        file = str(raw.get("file") or "")
        if file not in present:
            changed = True
            _drop_thumb(lib, file)
            continue
        stem = Path(file).stem.lower()
        if stem in used_stems:
            changed = True
            continue
        used_stems.add(stem)
        item_id = str(raw.get("id") or "")
        if not item_id or item_id in taken_ids:
            item_id = _new_id(taken_ids)
            changed = True
        taken_ids.add(item_id)
        entry = {
            "id": item_id,
            "name": clean_label(raw.get("name") or Path(file).stem, Path(file).stem),
            "cat": clean_label(raw.get("cat") or UNSORTED, UNSORTED),
            "file": file,
            "added": int(raw.get("added") or 0),
        }
        if entry != raw:
            changed = True
        kept.append(entry)

    # 手工丢进 img/ 的文件排在已有条目之后：用户刚放进去的图应该出现在末尾，
    # 而不是因为文件 mtime 更早被塞到最前面找不到。
    cursor = max((item["added"] for item in kept), default=0)
    for file in sorted(present):
        if Path(file).stem.lower() in used_stems:
            continue
        used_stems.add(Path(file).stem.lower())
        try:
            cursor = max(cursor, int((folder / file).stat().st_mtime))
        except OSError:
            pass
        cursor += 1
        kept.append(
            {
                "id": _new_id(taken_ids),
                "name": clean_label(Path(file).stem, Path(file).stem),
                "cat": UNSORTED,
                "file": file,
                "added": cursor,
            }
        )
        taken_ids.add(kept[-1]["id"])
        changed = True

    if changed:
        # 同秒导入的按插入顺序（stable sort），别让名字决定先后
        kept.sort(key=lambda item: item["added"])
    data["items"] = kept
    if _sync_categories(data):
        changed = True

    return changed


def _sync_categories(data: dict) -> bool:
    """分类列表以条目为准：还有图的留着（保持登记时的顺序），一张不剩的直接删掉。

    用户把某个分类的最后一张图删了，这个分类就该跟着消失 —— 否则下拉里会留一个
    点进去空空如也、还会被写进工作流的死分类。返回是否改动过。
    """
    used: list = []
    for item in data["items"]:
        if item["cat"] not in used:
            used.append(item["cat"])
    ordered = [str(cat) for cat in data["categories"] if str(cat) in used]
    ordered += [cat for cat in used if cat not in ordered]
    if ordered == list(data["categories"]):
        return False
    data["categories"] = ordered
    return True


def load(lib: str = "pose") -> dict:
    """读图库数据（带缓存，目录一变就重扫）。调用方不要就地改返回值。"""
    with _lock:
        index = paths.index_file(lib)
        sig = (_mtime(index), _dir_sig(paths.img_dir(lib)))
        hit = _cache.get(lib)
        if hit and hit["sig"] == sig:
            return hit["data"]

        data = _read(lib)
        if _reconcile(data, lib):
            try:
                _write(lib, data)
            except OSError as err:
                log(f"[MK 图库] 写 {index.name} 失败（本次改动只留在内存里）：{err}")
        sig = (_mtime(index), _dir_sig(paths.img_dir(lib)))
        _cache[lib] = {"sig": sig, "data": data}
        return data


def invalidate(lib: str = "pose") -> None:
    """丢掉缓存，下次 load 重新扫目录。"""
    _cache.pop(lib, None)


# ------------------------------------------------------------------ 缩略图


def thumb_name(file: str) -> str:
    return f"{Path(file).stem}.jpg"


def _drop_thumb(lib: str, file: str) -> None:
    if not file:
        return
    try:
        (paths.thumb_dir(lib) / thumb_name(file)).unlink(missing_ok=True)
    except OSError:
        pass


def ensure_thumb(lib: str, file: str) -> Optional[Path]:
    """拿缩略图路径；没有就用原图现生成一张。

    缩略图不入库也不随插件分发，首次请求现场生成，之后由浏览器缓存兜着。
    """
    target = paths.thumb_dir(lib) / thumb_name(file)
    if target.is_file():
        return target
    source = paths.img_dir(lib) / file
    if not source.is_file():
        return None
    try:
        raw = source.read_bytes()
        atomic_write_bytes(target, to_thumb_bytes(raw))
    except Exception as err:
        log(f"[MK 图库] 缩略图生成失败 {file}：{err}")
        return None
    return target


# ------------------------------------------------------------------ 写入


def _unique_file(lib: str, stem: str, taken: set) -> str:
    name, dup = f"{stem}.webp", 2
    while name in taken or (paths.img_dir(lib) / name).exists():
        name = f"{stem} ({dup}).webp"
        dup += 1
    return name


def add_many(
    lib: str,
    uploads: list,
    name: Optional[str] = None,
    cat: Optional[str] = None,
) -> tuple:
    """批量导入：统一转 WebP、生成缩略图、登记进 library.json。

    uploads 是 [(原始文件名, bytes)]。一次只写一遍 library.json —— 逐张写
    几百张时会变成 O(n²) 的写放大。

    返回 (saved, failed)：saved 是新条目的 id 列表，failed 是 [{name, error}]。
    """
    paths.ensure_dirs(lib)
    base_name = clean_label(name or "", "")
    category = clean_label(cat or "", UNSORTED)

    with _lock:
        data = _read(lib)
        _reconcile(data, lib)
        # 所有图统一存成 <stem>.webp，文件名唯一就等于主干唯一，不用再单独防重名
        taken_files = {item["file"] for item in data["items"]}
        taken_ids = {item["id"] for item in data["items"]}

        saved, failed = [], []
        total = len(uploads)
        # 时间戳只用来排序，但必须是单调递增的：同一秒里连导几批时，
        # 单看 time() 会出现「后导入的排到前面」，列表顺序就跟操作顺序对不上了。
        base = max(int(time.time()), max((item["added"] for item in data["items"]), default=0) + 1)
        for position, (filename, raw) in enumerate(uploads, 1):
            if not raw:
                failed.append({"name": filename, "error": "文件是空的"})
                continue
            try:
                webp = to_webp_bytes(raw)
            except Exception as err:
                failed.append({"name": filename, "error": f"读不出这张图（{err}）"})
                continue

            # 多张共用一个名称时自动编号，避免互相覆盖
            display = base_name or clean_label(Path(filename).stem, "未命名")
            if base_name and total > 1:
                display = f"{base_name} {position}"
            file = _unique_file(lib, safe_stem(display), taken_files)
            try:
                atomic_write_bytes(paths.img_dir(lib) / file, webp)
            except OSError as err:
                failed.append({"name": filename, "error": f"写文件失败（{err}）"})
                continue

            taken_files.add(file)
            item_id = _new_id(taken_ids)
            taken_ids.add(item_id)
            data["items"].append(
                {
                    "id": item_id,
                    "name": display,
                    "cat": category,
                    "file": file,
                    "added": base + position,
                }
            )
            saved.append(item_id)

            try:
                atomic_write_bytes(
                    paths.thumb_dir(lib) / thumb_name(file), to_thumb_bytes(webp)
                )
            except Exception as err:  # 缩略图失败不影响入库，下次访问会重建
                log(f"[MK 图库] 缩略图生成失败 {file}：{err}")

        if saved:
            data["items"].sort(key=lambda item: item["added"])
            _sync_categories(data)
            _write(lib, data)
            invalidate(lib)
        return saved, failed


def remove(lib: str, file: str) -> bool:
    """删掉一张图：原图、缩略图、library.json 里的条目一起清。"""
    target_name = Path(str(file or "").replace("\\", "/")).name
    if not target_name:
        return False
    target = (paths.img_dir(lib) / target_name).resolve()
    if target.parent != paths.img_dir(lib).resolve():
        return False

    with _lock:
        data = _read(lib)
        before = len(data["items"])
        data["items"] = [item for item in data["items"] if item["file"] != target_name]
        removed_entry = len(data["items"]) != before
        if not target.is_file() and not removed_entry:
            return False
        if target.is_file():
            try:
                target.unlink()
            except OSError:
                return False
        _drop_thumb(lib, target_name)
        _sync_categories(data)  # 删掉最后一张图，分类也跟着消失
        _write(lib, data)
        invalidate(lib)
        return True


def stats(lib: str = "pose") -> dict:
    data = load(lib)
    return {"total": len(data["items"]), "categories": len(data["categories"])}
