"""对外查询层：给节点和 HTTP 路由用的统一口径。

节点只认 label（字符串），前端只认 file（文件名），中间这层负责把两边的说法对上。
"""

from pathlib import Path
from typing import Optional

from . import paths, store
from .constants import ALL, LIB_NAMES, LIB_NOUNS
from .errors import GalleryMissing


def _labels(items: list) -> list:
    """给每个条目算一个唯一 label（节点参数存的就是它）。

    同名图很常见（不同批次都叫「站姿 01」），重名时按顺序补 (2)(3)，
    保证下拉 / 工作流里存的值一定能找回唯一一条。
    """
    seen: dict = {}
    out = []
    for item in items:
        name = item["name"]
        count = seen.get(name, 0) + 1
        seen[name] = count
        out.append(name if count == 1 else f"{name} ({count})")
    return out


def items(lib: str = "pose") -> list:
    """全部条目（含 label），顺序即 library.json 里的顺序。"""
    raw = store.load(lib)["items"]
    labels = _labels(raw)
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "label": labels[i],
            "cat": item["cat"],
            "file": item["file"],
            "added": item["added"],
        }
        for i, item in enumerate(raw)
    ]


def categories(lib: str = "pose") -> list:
    """分类及条目数：[{name, count}]，只包含还有图的分类。

    顺序按 `library.json` 里登记的先后（导入时新建的分类就按创建顺序排队），
    没登记的补在后面。**没有图的分类不会出现在这里** —— 删掉最后一张图，
    这个分类就跟着消失，下拉里不会留一个点进去空空如也的死分类。
    """
    data = store.load(lib)
    counts: dict = {}
    for item in data["items"]:
        counts[item["cat"]] = counts.get(item["cat"], 0) + 1
    order = [str(cat) for cat in data["categories"] if str(cat) in counts]
    order += [cat for cat in counts if cat not in order]
    return [{"name": cat, "count": counts[cat]} for cat in order]


def index(lib: str = "pose") -> dict:
    """前端一次拿全：分类、条目、总数。"""
    rows = items(lib)
    return {
        "lib": lib,
        "noun": LIB_NOUNS.get(lib, "图"),
        "total": len(rows),
        "categories": categories(lib),
        "items": rows,
    }


def find(label: str, lib: str = "pose") -> dict:
    """按 label 找条目；找不到给中文报错（多半是图被删了）。"""
    rows = items(lib)
    name = LIB_NAMES.get(lib, "图库")
    empty_hint = (
        f"{name}还是空的。\n"
        f"在节点面板里点「导入」放几张图，或者把图片直接丢进 "
        f"{paths.describe(paths.img_dir(lib))} 再刷新。"
    )
    if not rows:
        raise GalleryMissing(empty_hint)

    text = str(label or "").strip()
    for item in rows:
        if item["label"] == text:
            return item
    # 兜底：老工作流 / 手改过数据时可能只存了名字，重名就取第一个
    for item in rows:
        if item["name"] == text:
            return item
    if not text:
        raise GalleryMissing(f"还没有选{LIB_NOUNS.get(lib, '图')}。请在「{name}」节点里点一张图。")
    raise GalleryMissing(
        f"{name}里没有「{text}」这一项。\n"
        f"它可能已经被删掉或改名了 —— 请在节点里重新选一张{LIB_NOUNS.get(lib, '图')}。"
    )


def pool(category: str = ALL, lib: str = "pose") -> list:
    """随机的候选池。

    指定分类但一张都没有时退到全库，不因为空组合把节点卡死
    （分类可能是刚在别的节点里删空的）。
    """
    rows = items(lib)
    if not rows:
        raise GalleryMissing(
            f"{LIB_NAMES.get(lib, '图库')}还是空的。\n"
            f"在节点面板里点「导入」放几张图，或者把图片直接丢进 "
            f"{paths.describe(paths.img_dir(lib))} 再刷新。"
        )
    key = str(category or "").strip()
    if key and key != ALL:
        matched = [item for item in rows if item["cat"] == key]
        if matched:
            return matched
    return rows


def resolve(file: str, lib: str = "pose") -> Path:
    """条目的原图路径；文件不在就报错说清在哪找。"""
    path = paths.img_dir(lib) / Path(str(file or "")).name
    if not path.is_file():
        raise FileNotFoundError(
            f"图片文件不见了：{path.name}\n"
            f"请确认 {paths.describe(paths.img_dir(lib))} 里还在；"
            f"如果是从别处删的，重新导入一次即可。"
        )
    return path


def resolve_thumb(file: str, lib: str = "pose") -> Optional[Path]:
    return store.ensure_thumb(lib, Path(str(file or "")).name)


def describe_filter(category: str) -> str:
    """把「分类」参数归一成筛选值（空 / 空白一律当「全部」）。"""
    return str(category or "").strip() or ALL
