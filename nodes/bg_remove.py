"""MK-图片背景移除（MK_BgRemove）。

迁移自 ComfyUI-RMBG 的「去除背景 (RMBG)」节点，完整保留 4 个模型后端与全部参数：
RMBG-2.0（BiRefNet）、INSPYRENET、BEN、BEN2。

与源插件的差异：
- 改为 V3（NODE 2.0）接口：`io.ComfyNode` + `define_schema`；
- 不再依赖源插件的 AILab_utils，工具函数在本文件内自带；
- 颜色选择用 ComfyUI 原生的 COLOR 控件（源插件靠自己的前端 JS 提供取色器）；
- 模型目录仍为 `ComfyUI/models/RMBG/<模型名>/`，与源插件一致，已有缓存可直接复用。

模型许可：
- RMBG-2.0 / BEN / BEN2：Apache-2.0；INSPYRENET：MIT。
- 本迁移脚本沿用源插件的 GPL-3.0 约定，使用时请一并遵守原模型许可。
"""

from __future__ import annotations

import contextlib
import gc
import importlib.util
import json
import os
import sys
import types
import warnings

import comfy.model_management as mm
import folder_paths
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageFilter
from comfy_api.latest import io
from torchvision import transforms

# 模型表：与源插件完全一致，repo/cache_dir 保持原样以便复用已下载的缓存
AVAILABLE_MODELS = {
    "RMBG-2.0": {
        "type": "rmbg",
        "repo_id": "1038lab/RMBG-2.0",
        "files": {
            "config.json": "config.json",
            "model.safetensors": "model.safetensors",
            "birefnet.py": "birefnet.py",
            "BiRefNet_config.py": "BiRefNet_config.py",
        },
        "cache_dir": "RMBG-2.0",
    },
    "INSPYRENET": {
        "type": "inspyrenet",
        "repo_id": "1038lab/inspyrenet",
        "files": {"inspyrenet.safetensors": "inspyrenet.safetensors"},
        "cache_dir": "INSPYRENET",
    },
    "BEN": {
        "type": "ben",
        "repo_id": "1038lab/BEN",
        "files": {"model.py": "model.py", "BEN_Base.pth": "BEN_Base.pth"},
        "cache_dir": "BEN",
    },
    "BEN2": {
        "type": "ben2",
        "repo_id": "1038lab/BEN2",
        "files": {"BEN2_Base.pth": "BEN2_Base.pth", "BEN2.py": "BEN2.py"},
        "cache_dir": "BEN2",
    },
}

MODEL_DIR = os.path.join(folder_paths.models_dir, "RMBG")


# 第三方模型代码里的弃用警告：timm 的旧导入路径、torch.meshgrid 少了 indexing 参数。
# 它们只影响日志可读性，不影响结果，因此在调用模型前后临时静音。
_DEPRECATION_FILTERS = (
    (r".*timm\.models\.layers.*", FutureWarning),
    (r".*torch\.meshgrid.*", UserWarning),
)


@contextlib.contextmanager
def _quiet_model_warnings():
    """只在包裹的这段调用里屏蔽模型自带的弃用警告，不影响其它节点的日志。"""
    with warnings.catch_warnings():
        for message, category in _DEPRECATION_FILTERS:
            warnings.filterwarnings("ignore", message=message, category=category)
        yield


def _relocate_timm_import(source: str) -> str:
    """把 `from timm.models.layers import ...` 换成新路径，避免每次加载都刷 FutureWarning。

    只有当前 timm 确实提供 timm.layers 时才替换，老版本保持原样。
    """
    if importlib.util.find_spec("timm.layers") is None:
        return source
    return source.replace("from timm.models.layers import", "from timm.layers import")


# --- 通用工具 -----------------------------------------------------------------

def _device() -> torch.device:
    return mm.get_torch_device()


def _clean_vram() -> None:
    gc.collect()
    mm.soft_empty_cache()


def _tensor2pil(image: torch.Tensor) -> Image.Image:
    return Image.fromarray(np.clip(255.0 * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))


def _pil2tensor(image: Image.Image) -> torch.Tensor:
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


def _normalize_process_res(process_res: int, step: int = 128, minimum: int = 256, maximum: int = 2048) -> int:
    process_res = max(minimum, min(maximum, int(process_res)))
    return min(maximum, max(minimum, (process_res // step) * step))


def _hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    value = str(hex_color).strip().lstrip("#")
    if len(value) == 6:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)
    if len(value) == 8:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), int(value[6:8], 16))
    raise ValueError(f"背景色格式不对：{hex_color!r}，请用 #RRGGBB 或 #RRGGBBAA。")


class _ModelCache:
    """模型加载基类：按模型名缓存，切换模型时释放上一个。"""

    base_dir = MODEL_DIR

    def __init__(self):
        self.model = None
        self.current_model_version = None

    def cache_dir(self, model_name: str) -> str:
        path = os.path.join(self.base_dir, AVAILABLE_MODELS[model_name]["cache_dir"])
        os.makedirs(path, exist_ok=True)
        return path

    def check_model_cache(self, model_name: str) -> tuple[bool, str]:
        folder = self.cache_dir(model_name)
        missing = [
            name
            for name, target in AVAILABLE_MODELS[model_name]["files"].items()
            if not os.path.exists(os.path.join(folder, target))
        ]
        if missing:
            return False, f"缺少模型文件：{', '.join(missing)}"
        return True, "ok"

    def download_model(self, model_name: str) -> tuple[bool, str]:
        info = AVAILABLE_MODELS[model_name]
        folder = self.cache_dir(model_name)
        try:
            from huggingface_hub import hf_hub_download

            for name in info["files"]:
                print(f"[MK-背景移除] 下载 {name} ...")
                hf_hub_download(repo_id=info["repo_id"], filename=name, local_dir=folder)
            return True, "下载完成"
        except Exception as exc:
            return False, (
                f"下载 {model_name} 失败：{exc}\n"
                f"请手动把模型文件放到 {folder} 下（需要的文件：{list(info['files'])}），"
                f"或配置 HuggingFace 镜像后重试。"
            )

    def clear(self) -> None:
        if self.model is not None:
            try:
                self.model.cpu()
            except Exception:
                pass
            self.model = None
        self.current_model_version = None
        _clean_vram()

    def ensure(self, model_name: str) -> None:
        """模型缺失时先尝试下载，再加载。"""
        ready, message = self.check_model_cache(model_name)
        if not ready:
            print(f"[MK-背景移除] {message}，尝试自动下载 ...")
            ok, detail = self.download_model(model_name)
            if not ok:
                raise RuntimeError(detail)
        self.load(model_name)

    def load(self, model_name: str) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def process(self, images, model_name: str, params: dict):  # pragma: no cover - 子类实现
        raise NotImplementedError


class _RMBGBiRefNet(_ModelCache):
    """RMBG-2.0：BiRefNet，走 transformers 加载。"""

    def load(self, model_name: str) -> None:
        if self.current_model_version == model_name:
            return
        self.clear()
        folder = self.cache_dir(model_name)
        device = _device()

        try:
            self._load_with_transformers(folder)
        except Exception as modern_error:
            print(f"[MK-背景移除] 新版 transformers 加载失败，回退标准加载：{modern_error}")
            try:
                from transformers import AutoModelForImageSegmentation

                self.model = AutoModelForImageSegmentation.from_pretrained(
                    folder, trust_remote_code=True, local_files_only=True
                )
            except Exception as standard_error:
                raise RuntimeError(
                    f"RMBG-2.0 加载失败。新版方式：{modern_error}；标准方式：{standard_error}"
                ) from standard_error

        self.model.eval()
        for param in self.model.parameters():
            param.requires_grad = False
        if device.type == "cuda":
            self.model.half()
        torch.set_float32_matmul_precision("high")
        self.model.to(device)
        self.current_model_version = model_name

    def _load_with_transformers(self, folder: str) -> None:
        """把仓库里的 birefnet.py 当普通模块执行，构造模型并手动灌权重。

        新版 transformers 对 remote code 的校验更严，直接走 AutoModel 容易失败，
        因此这里按源插件的方式自己组装。
        """
        from transformers import PreTrainedModel

        config_path = os.path.join(folder, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            json.load(f)  # 只做存在性校验，实际配置由 BiRefNetConfig 提供

        bi_config_path = os.path.join(folder, "BiRefNet_config.py")
        spec = importlib.util.spec_from_file_location("BiRefNetConfig", bi_config_path)
        config_module = importlib.util.module_from_spec(spec)
        sys.modules["BiRefNetConfig"] = config_module
        spec.loader.exec_module(config_module)

        birefnet_path = os.path.join(folder, "birefnet.py")
        with open(birefnet_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 仓库里是包内相对导入，这里改成顶层导入；顺带修掉 mask 的 dtype 不匹配
        content = content.replace(
            "from .BiRefNet_config import BiRefNetConfig", "from BiRefNetConfig import BiRefNetConfig"
        )
        content = content.replace(
            "attn = attn.view(B_ // nW, nW, self.num_heads, N, N) + mask.unsqueeze(1).unsqueeze(0)",
            "attn = attn.view(B_ // nW, nW, self.num_heads, N, N) + mask.to(attn.dtype).unsqueeze(1).unsqueeze(0)",
        )
        content = _relocate_timm_import(content)

        module_name = f"mk_birefnet_{abs(hash(birefnet_path))}"
        module = types.ModuleType(module_name)
        module.__file__ = birefnet_path
        sys.modules[module_name] = module
        with _quiet_model_warnings():
            exec(content, module.__dict__)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, PreTrainedModel) and attr is not PreTrainedModel:
                self.model = attr(getattr(config_module, "BiRefNetConfig")())
                weights = os.path.join(folder, "model.safetensors")
                import safetensors.torch

                self.model.load_state_dict(safetensors.torch.load_file(weights))
                return
        raise RuntimeError("birefnet.py 里找不到可用的模型类")

    def process(self, images, model_name: str, params: dict):
        self.ensure(model_name)
        device = _device()
        resolution = _normalize_process_res(params["process_res"])
        transform = transforms.Compose([
            transforms.Resize((resolution, resolution)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

        def to_mask(outputs) -> torch.Tensor:
            if isinstance(outputs, list) and outputs:
                return outputs[-1].float().sigmoid().cpu()
            if isinstance(outputs, dict) and "logits" in outputs:
                return outputs["logits"].float().sigmoid().cpu()
            if isinstance(outputs, torch.Tensor):
                return outputs.float().sigmoid().cpu()
            if hasattr(outputs, "last_hidden_state"):
                return outputs.last_hidden_state.float().sigmoid().cpu()
            for value in getattr(outputs, "values", lambda: [])():
                if isinstance(value, torch.Tensor):
                    return value.float().sigmoid().cpu()
            raise RuntimeError("无法识别的模型输出格式")

        sizes = [_tensor2pil(img).size for img in images]
        batch = torch.cat([transform(_tensor2pil(img).convert("RGB")).unsqueeze(0) for img in images], dim=0)
        batch = batch.to(device)
        if device.type == "cuda":
            batch = batch.half()

        def postprocess(result: torch.Tensor, size: tuple[int, int]) -> Image.Image:
            mask = result.squeeze() * (1 + (1 - params["sensitivity"]))
            mask = torch.clamp(mask, 0, 1)
            mask = F.interpolate(mask.unsqueeze(0).unsqueeze(0), size=(size[1], size[0]), mode="bilinear").squeeze()
            return _tensor2pil(mask)

        with torch.no_grad(), _quiet_model_warnings():
            try:
                results = to_mask(self.model(batch))
                return [postprocess(r, s) for r, s in zip(results, sizes)]
            except Exception as batch_error:
                if len(images) == 1 or "Sizes of tensors must match" not in str(batch_error):
                    raise
                # 批次尺寸不一致时退化为逐张推理
                print("[MK-背景移除] 批次推理失败，改为逐张处理")
                masks = []
                for img, size in zip(images, sizes):
                    single = transform(_tensor2pil(img).convert("RGB")).unsqueeze(0).to(device)
                    if device.type == "cuda":
                        single = single.half()
                    masks.append(postprocess(to_mask(self.model(single))[0], size))
                return masks


class _Inspyrenet(_ModelCache):
    """INSPYRENET：用 transparent_background 包，模型文件自动缓存。"""

    def load(self, model_name: str) -> None:
        if self.current_model_version == model_name:
            return
        self.clear()
        import transparent_background

        with _quiet_model_warnings():
            self.model = transparent_background.Remover()
        self.current_model_version = model_name

    def process(self, image, model_name: str, params: dict):
        self.ensure(model_name)
        original = _tensor2pil(image)
        width, height = original.size
        resized = original.resize(
            (params["process_res"], int(params["process_res"] * height / width)), Image.LANCZOS
        )
        foreground = self.model.process(resized, type="rgba")
        return foreground.resize((width, height), Image.LANCZOS).split()[-1]


class _BEN(_ModelCache):
    """BEN：仓库自带 model.py，动态执行后加载权重。"""

    module_file = "model.py"
    weights_file = "BEN_Base.pth"
    weights_loader = "loadcheckpoints"

    def load(self, model_name: str) -> None:
        if self.current_model_version == model_name:
            return
        self.clear()
        folder = self.cache_dir(model_name)
        module_path = os.path.join(folder, self.module_file)
        module_name = f"mk_{model_name.lower()}_{abs(hash(module_path))}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        with _quiet_model_warnings():
            spec.loader.exec_module(module)

        self.model = module.BEN_Base()
        getattr(self.model, self.weights_loader)(os.path.join(folder, self.weights_file))
        self.model.eval()
        for param in self.model.parameters():
            param.requires_grad = False
        torch.set_float32_matmul_precision("high")
        self.model.to(_device())
        self.current_model_version = model_name

    def process(self, image, model_name: str, params: dict):
        self.ensure(model_name)
        original = _tensor2pil(image)
        width, height = original.size
        resized = original.resize(
            (params["process_res"], int(params["process_res"] * height / width)), Image.LANCZOS
        )
        with torch.no_grad(), _quiet_model_warnings():
            _, foreground = self.model.inference(resized.convert("RGBA"))
        return foreground.resize((width, height), Image.LANCZOS).split()[-1]


class _BEN2(_BEN):
    """BEN2：与 BEN 同一套加载方式，只是文件与推理接口不同，支持批处理。"""

    module_file = "BEN2.py"
    weights_file = "BEN2_Base.pth"

    def process(self, images, model_name: str, params: dict):
        self.ensure(model_name)
        masks = []
        for image in images:
            original = _tensor2pil(image)
            width, height = original.size
            resized = original.resize(
                (params["process_res"], int(params["process_res"] * height / width)), Image.LANCZOS
            )
            with torch.no_grad(), _quiet_model_warnings():
                result = self.model.inference([resized.convert("RGBA")])
            if not isinstance(result, list):
                result = [result]
            masks.append(result[0].resize((width, height), Image.LANCZOS).split()[-1])
        return masks


_MODEL_POOL: dict[str, _ModelCache] = {}


def _get_loader(model_name: str) -> _ModelCache:
    if model_name not in _MODEL_POOL:
        kind = AVAILABLE_MODELS[model_name]["type"]
        _MODEL_POOL[model_name] = {
            "rmbg": _RMBGBiRefNet,
            "inspyrenet": _Inspyrenet,
            "ben": _BEN,
            "ben2": _BEN2,
        }[kind]()
    return _MODEL_POOL[model_name]


def _refine_foreground(image_bchw: torch.Tensor, masks_b1hw: torch.Tensor) -> torch.Tensor:
    """Fast Foreground Colour Estimation：在边缘过渡带上做颜色回收，减少白边。"""
    import cv2

    batch = image_bchw.shape[0]
    if batch != masks_b1hw.shape[0]:
        raise ValueError("图像与遮罩的批次大小不一致")
    image_np = image_bchw.cpu().numpy()
    mask_np = masks_b1hw.cpu().numpy()

    refined = []
    for index in range(batch):
        mask = mask_np[index, 0]
        binary = (mask > 0.45).astype(np.float32)
        edge_blur = cv2.GaussianBlur(binary, (3, 3), 0)
        transition = np.logical_and(mask > 0.05, mask < 0.95)
        alpha = 0.85
        mask_refined = np.where(transition, alpha * mask + (1 - alpha) * edge_blur, binary)
        edge_region = np.logical_and(mask > 0.2, mask < 0.8)
        mask_refined = np.where(edge_region, mask_refined * 0.98, mask_refined)

        channels = [image_np[index, c] * mask_refined for c in range(image_np.shape[1])]
        refined.append(np.stack(channels))
    return torch.from_numpy(np.stack(refined))


class MKBgRemove(io.ComfyNode):
    """一键抠图：输出带透明通道的图像、遮罩与遮罩可视化图。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MK_BgRemove",
            display_name="MK-图片背景移除",
            category="MK节点",
            description=(
                "用 RMBG-2.0 / INSPYRENET / BEN / BEN2 抠掉图片背景。"
                "输出带透明通道的图像、遮罩，以及遮罩的可视化图。"
                "「背景」选 Alpha 输出透明图，选 Color 则合成到指定底色上。"
                "模型放在 ComfyUI/models/RMBG/ 下，缺失时会尝试自动下载。"
            ),
            search_aliases=[
                "rmbg", "remove background", "抠图", "去背景", "背景移除", "透明背景", "matting",
            ],
            inputs=[
                io.Image.Input("image", display_name="图像", tooltip="要去背景的图片，支持批次。"),
                io.Combo.Input(
                    "model",
                    options=list(AVAILABLE_MODELS.keys()),
                    default="RMBG-2.0",
                    display_name="模型",
                    tooltip="RMBG-2.0 综合最稳；BEN2 对细节发丝更好；INSPYRENET 对纯色背景快。",
                ),
                io.Float.Input(
                    "sensitivity",
                    display_name="灵敏度",
                    default=1.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="调低会收缩前景（保留更少），调高会吃掉更多边缘过渡。1.0 为模型原始输出。",
                ),
                io.Int.Input(
                    "process_res",
                    display_name="处理分辨率",
                    default=1024,
                    min=256,
                    max=2048,
                    step=128,
                    tooltip="推理时把图缩到这个分辨率再算遮罩。越高越准，也越吃显存。",
                ),
                io.Int.Input(
                    "mask_blur",
                    display_name="遮罩羽化",
                    default=0,
                    min=0,
                    max=64,
                    step=1,
                    tooltip="给遮罩边缘加高斯模糊，0 表示不处理。",
                ),
                io.Int.Input(
                    "mask_offset",
                    display_name="遮罩偏移",
                    default=0,
                    min=-64,
                    max=64,
                    step=1,
                    tooltip="正数向外扩张遮罩（多留边），负数向内收缩（少留边）。",
                ),
                io.Boolean.Input(
                    "invert_output",
                    display_name="反转输出",
                    default=False,
                    tooltip="把图像和遮罩一起反转，用于「保留背景、去掉主体」这类需求。",
                ),
                io.Boolean.Input(
                    "refine_foreground",
                    display_name="优化前景",
                    default=False,
                    tooltip="用前景颜色回收算法处理边缘过渡，能减少白边，但会慢一些。",
                ),
                io.Boolean.Input(
                    "unload_model",
                    display_name="卸载模型",
                    default=False,
                    tooltip="跑完把模型移出显存。批量做多张时建议关闭以便复用。",
                ),
                io.Combo.Input(
                    "background",
                    options=["Alpha", "Color"],
                    default="Alpha",
                    display_name="背景",
                    tooltip="Alpha：输出透明背景；Color：合成到下面的背景色上。",
                ),
                io.Color.Input(
                    "background_color",
                    display_name="背景色",
                    default="#222222",
                    tooltip="「背景」选 Color 时使用的底色，支持 #RRGGBB 与 #RRGGBBAA。",
                ),
            ],
            outputs=[
                io.Image.Output("IMAGE", display_name="图像", tooltip="去背后的图像；Alpha 模式下为 4 通道。"),
                io.Mask.Output("MASK", display_name="遮罩", tooltip="前景遮罩，白色为保留区域。"),
                io.Image.Output("MASK_IMAGE", display_name="遮罩图", tooltip="把遮罩转成三通道图，方便预览。"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image,
        model,
        sensitivity=1.0,
        process_res=1024,
        mask_blur=0,
        mask_offset=0,
        invert_output=False,
        refine_foreground=False,
        unload_model=False,
        background="Alpha",
        background_color="#222222",
    ):
        params = {
            "sensitivity": sensitivity,
            "process_res": process_res,
            "mask_blur": mask_blur,
            "mask_offset": mask_offset,
            "invert_output": invert_output,
            "refine_foreground": refine_foreground,
            "background": background,
            "background_color": background_color,
        }
        loader = _get_loader(model)

        images = [img for img in image] if image.ndim == 4 else [image]
        mask_pils: list[Image.Image] = []

        if AVAILABLE_MODELS[model]["type"] in ("rmbg", "ben2"):
            chunk = 4
            for start in range(0, len(images), chunk):
                batch = images[start : start + chunk]
                result = loader.process(batch, model, params)
                if isinstance(result, Image.Image):
                    result = [result]
                mask_pils.extend(result)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        else:
            for img in images:
                mask_pils.append(loader.process(img, model, params))

        out_images, out_masks = [], []
        for img, mask_pil in zip(images, mask_pils):
            mask_pil = mask_pil.convert("L")
            mask_tensor = _pil2tensor(mask_pil)
            mask_tensor = torch.clamp(mask_tensor * (1 + (1 - sensitivity)), 0, 1)
            mask_pil = _tensor2pil(mask_tensor)

            if mask_blur > 0:
                mask_pil = mask_pil.filter(ImageFilter.GaussianBlur(radius=mask_blur))
            if mask_offset != 0:
                filter_cls = ImageFilter.MaxFilter if mask_offset > 0 else ImageFilter.MinFilter
                for _ in range(abs(mask_offset)):
                    mask_pil = mask_pil.filter(filter_cls(3))
            if invert_output:
                mask_pil = Image.fromarray(255 - np.array(mask_pil))

            original = _tensor2pil(img)
            source = original.convert("RGBA")
            if refine_foreground:
                image_bchw = torch.from_numpy(np.array(original)).permute(2, 0, 1).unsqueeze(0) / 255.0
                mask_b1hw = torch.from_numpy(np.array(mask_pil)).unsqueeze(0).unsqueeze(0) / 255.0
                refined = _refine_foreground(image_bchw, mask_b1hw)
                refined_pil = _tensor2pil(refined[0].permute(1, 2, 0))
                r, g, b = refined_pil.convert("RGB").split()
                foreground = Image.merge("RGBA", (r, g, b, mask_pil))
            else:
                r, g, b, _ = source.split()
                foreground = Image.merge("RGBA", (r, g, b, mask_pil))

            if background == "Color":
                canvas = Image.new("RGBA", original.size, _hex_to_rgba(background_color))
                out_images.append(_pil2tensor(Image.alpha_composite(canvas, foreground).convert("RGB")))
            else:
                out_images.append(_pil2tensor(foreground))
            out_masks.append(_pil2tensor(mask_pil))

        mask_images = [
            m.reshape((-1, 1, m.shape[-2], m.shape[-1])).movedim(1, -1).expand(-1, -1, -1, 3)
            for m in out_masks
        ]

        if unload_model:
            loader.clear()

        return io.NodeOutput(
            torch.cat(out_images, dim=0),
            torch.cat(out_masks, dim=0),
            torch.cat(mask_images, dim=0),
        )


__all__ = ["MKBgRemove"]
