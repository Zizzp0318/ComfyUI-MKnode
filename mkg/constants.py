"""全局常量：库名、文案、图片规格、上传上限。

这里只放不随环境变化的值；路径全在 paths.py。
"""

# ---------------------------------------------------------------- 库
# 加库时：这里加一行 → paths.LIB_SUBDIR 加目录 → nodes 加一个类 → api 注册一行 → 前端加一个入口文件。
LIBS = ("pose", "garment", "face")

LIB_NAMES = {"pose": "姿态库", "garment": "服装库", "face": "脸模库"}
LIB_NOUNS = {"pose": "姿态", "garment": "服装", "face": "脸模"}
LIB_UNITS = {"pose": "个", "garment": "套", "face": "张"}
# HTTP 前缀：/mkposes/* /mkgarments/* /mkfaces/*
LIB_PREFIX = {"pose": "mkposes", "garment": "mkgarments", "face": "mkfaces"}

ALL = "全部"

# 没给分类时落在这里。用户可以自己再建别的分类。
UNSORTED = "未分类"

# ---------------------------------------------------------------- 文件
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

THUMB_SIDE = 360  # 缩略图长边
THUMB_QUALITY = 86
WEBP_QUALITY = 95
WEBP_METHOD = 4

ILLEGAL_CHARS = '\\/:*?"<>|'
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}

# 显示名 / 分类名的长度上限
MAX_LABEL = 60

# ---------------------------------------------------------------- 上限
# 网页导入单张上限：读分片时流式判断，超了立刻断
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
