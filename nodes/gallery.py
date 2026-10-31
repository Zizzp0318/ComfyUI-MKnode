"""MK-姿态库 / 服装库 / 脸模库：点一张图，输出 IMAGE 给后面的采样 / ControlNet。

三个节点共用一套取图逻辑（_pick）和同一副骨架（_Picker），只是底层库不同：
pose / garment / face。新增库：constants 加库名 → paths 加目录 → 这里加一个类 + 映射。

取图方式三种，和旧版一致（去掉视角与系列之后，筛选只剩「分类」）：

    固定选中    用选中的那张，走 ComfyUI 缓存，参数不变不重复执行
    全库随机    忽略分类，全库抽一张
    范围内随机  在「分类」里抽；分类是空的就退到全库

种子：
    -1  每次执行用系统熵重抽（界面上没有入口，默认就是它）
    >=0 确定性抽取：同种子 + 同参数 = 同一张（目前只有 API 调用会用到）

参数里的「姿态 / 服装 / 脸模」和「分类」故意用 STRING 而不是 COMBO：
COMBO 的值一旦被删掉（图或分类没了），ComfyUI 会在提交前就报
"Value not in list"，用户只看到一句看不懂的英文；STRING 能一路走到我们这边，
由 library.find() 给出「哪张图没了、怎么办」的中文提示。
"""

import random

import numpy as np
import torch
from PIL import Image

from ..mkg import library
from ..mkg.constants import ALL

MODE_FIXED = "固定选中"
MODE_RANDOM_ALL = "全库随机"
MODE_RANDOM_FILTERED = "范围内随机"
MODES = [MODE_FIXED, MODE_RANDOM_ALL, MODE_RANDOM_FILTERED]

SEED_RANDOM = -1
SEED_MAX = 2**31 - 1


def _resolve_seed(seed) -> tuple:
    """把「种子」参数解析成 (实际种子, 是否自动)。

    -1 用系统熵现取一个（真随机），实际值会回传前端，方便一键钉住复现。
    """
    try:
        value = int(seed)
    except (TypeError, ValueError):
        value = SEED_RANDOM
    if value < 0:
        return random.SystemRandom().randrange(0, SEED_MAX), True
    return min(value, SEED_MAX), False


def _load_image(path) -> torch.Tensor:
    with Image.open(path) as im:
        pixels = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(pixels)[None, ...]


def _pick(lib: str, 模式: str, 名称: str, 分类: str, 种子) -> dict:
    """按模式选一张图，返回 ComfyUI 的 {"ui", "result"}。"""
    mode = 模式 if 模式 in MODES else MODE_FIXED
    category = library.describe_filter(分类)

    actual_seed = None
    if mode == MODE_FIXED:
        item = library.find(名称, lib)
    else:
        actual_seed, _auto = _resolve_seed(种子)
        rng = random.Random(actual_seed)
        # 全库随机 = 不限分类；两者都走 pool()，空库时的报错文案也就统一了
        item = rng.choice(library.pool(ALL if mode == MODE_RANDOM_ALL else category, lib))

    path = library.resolve(item["file"], lib)
    image = _load_image(path)
    picked = {
        "id": item["id"],
        "name": item["name"],
        "label": item["label"],
        "cat": item["cat"],
        "seed": actual_seed,
        "mode": mode,
    }
    return {"ui": {"picked": [picked]}, "result": (image,)}


class _Picker:
    """三个库共用的节点骨架：只有「库 / 参数名 / 文案」不同。

    `姿态` `服装` `脸模` 三个参数名不能统一成 `名称` —— 它们会原样变成工作流里的键，
    改了老工作流就接不上，而且下拉/报错里叫「服装」比叫「名称」更像人话。
    """

    CATEGORY = "MK_Gallery"
    FUNCTION = "pick"
    RETURN_TYPES = ("IMAGE",)
    LIB = "pose"
    ITEM_NAME = "姿态"
    RETURN_NAMES = ("姿态图",)
    DESCRIPTION = "点一张参考图，输出 IMAGE。图库数据存在 ComfyUI/user 下，升级插件不会丢。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模式": (MODES, {"default": MODE_FIXED}),
                # 两个 STRING 都是给画廊写值的：界面上被隐藏，值照常序列化进工作流
                cls.ITEM_NAME: ("STRING", {"default": "", "multiline": False}),
                "分类": ("STRING", {"default": ALL, "multiline": False}),
                "种子": (
                    "INT",
                    {
                        "default": SEED_RANDOM,
                        "min": SEED_RANDOM,
                        "max": SEED_MAX,
                        "step": 1,
                        "tooltip": "-1 = 每次随机；>=0 = 用这个种子，同参数下可复现",
                    },
                ),
            }
        }

    @classmethod
    def IS_CHANGED(cls, 模式=MODE_FIXED, 分类=ALL, 种子=SEED_RANDOM, **kwargs):
        """告诉 ComfyUI 这次要不要复用缓存。

        随机模式且种子是 -1 时必须每次都跑：否则参数没变 → 判定未变 → 直接复用上次
        结果，节点不执行也就不会回传 picked，用户点第二次队列毫无反应。
        返回 NaN 表示「每次都不一样」。

        选中项（姿态 / 服装 / 脸模）本来就参与 ComfyUI 的参数签名，不用在这里重复列。
        """
        if 模式 == MODE_FIXED:
            return ""
        try:
            value = int(种子)
        except (TypeError, ValueError):
            value = SEED_RANDOM
        if value < 0:
            return float("nan")
        return f"seed={value}|{模式}|{分类}"


class MKPosePicker(_Picker):
    """白模姿态参考图选择器。"""

    LIB = "pose"
    ITEM_NAME = "姿态"
    RETURN_NAMES = ("姿态图",)

    def pick(self, 模式, 姿态, 分类, 种子=SEED_RANDOM):
        return _pick(self.LIB, 模式, 姿态, 分类, 种子)


class MKGarmentPicker(_Picker):
    """服装穿搭参考图选择器。"""

    LIB = "garment"
    ITEM_NAME = "服装"
    RETURN_NAMES = ("服装图",)

    def pick(self, 模式, 服装, 分类, 种子=SEED_RANDOM):
        return _pick(self.LIB, 模式, 服装, 分类, 种子)


class MKFacePicker(_Picker):
    """脸模参考图选择器。"""

    LIB = "face"
    ITEM_NAME = "脸模"
    RETURN_NAMES = ("脸模图",)

    def pick(self, 模式, 脸模, 分类, 种子=SEED_RANDOM):
        return _pick(self.LIB, 模式, 脸模, 分类, 种子)


NODE_CLASS_MAPPINGS = {
    "MKPosePicker": MKPosePicker,
    "MKGarmentPicker": MKGarmentPicker,
    "MKFacePicker": MKFacePicker,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MKPosePicker": "MK-姿态库",
    "MKGarmentPicker": "MK-服装库",
    "MKFacePicker": "MK-脸模库",
}
