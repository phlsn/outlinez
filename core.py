"""Freistellen mit BiRefNet: Bild rein, RGBA-Bild mit transparentem Hintergrund raus."""

import io
import os
import threading
from pathlib import Path

from paths import cache_dir  # noqa: E402

ROOT = Path(__file__).parent
if (ROOT / ".installed").exists():
    # Installierte App: Modelle liegen (nur lesbar) im App-Ordner und werden bei der Deinstallation
    # mit entfernt. Der Installer hat sie geladen, also nichts nachladen. Den Modell-Code kopiert
    # transformers beim Laden in einen Ordner, der beschreibbar sein muss.
    os.environ.setdefault("HF_HOME", str(ROOT / "models"))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_MODULES_CACHE", str(cache_dir() / "hf-modules"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
# Mac: Operationen ohne MPS-Kernel (z. B. deform_conv2d in BiRefNet) laufen dann auf dem Prozessor
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

from modelinfo import MODELS  # noqa: E402

if torch.cuda.is_available():
    DEVICE = "cuda"
elif torch.backends.mps.is_available():
    DEVICE = "mps"  # Apple Silicon
else:
    DEVICE = "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

_models: dict[str, torch.nn.Module] = {}
_lock = threading.Lock()

Image.MAX_IMAGE_PIXELS = 300_000_000


def get_model(name: str) -> torch.nn.Module:
    if name not in MODELS:
        raise ValueError(f"Unbekanntes Modell: {name} (verfügbar: {', '.join(MODELS)})")
    if name not in _models:
        from transformers import AutoModelForImageSegmentation

        repo, revision, _ = MODELS[name]
        model = AutoModelForImageSegmentation.from_pretrained(repo, revision=revision, trust_remote_code=True)
        _models[name] = model.to(DEVICE, DTYPE).eval()
        if DEVICE == "cuda":
            # Erster Durchlauf initialisiert die CUDA-Kernel (~2 s), danach geht es schnell.
            # Auf Mac/CPU bringt das nichts und kostet mit dem HR-Modell sehr lange.
            with torch.inference_mode():
                _models[name](torch.zeros(1, 3, MODELS[name][2], MODELS[name][2], device=DEVICE, dtype=DTYPE))
    return _models[name]


def device_name() -> str:
    if DEVICE == "cuda":
        return torch.cuda.get_device_name(0)
    return "Apple-Grafikeinheit (MPS)" if DEVICE == "mps" else "Prozessor (ohne GPU, langsamer)"


def memory_gb() -> float:
    """Arbeitsspeicher des Rechners in GB."""
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong),
                        ("avail_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                        ("avail_virtual", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]

        status = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.total / 1024**3
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3


HR_MIN_MEMORY_GB = 15.5  # "16 GB"-Rechner melden etwas weniger


def hr_supported() -> bool:
    """Das HR-Modell (2048 px) braucht ohne NVIDIA-Karte sehr viel Arbeitsspeicher; mit 8 GB
    lagert das System so stark aus, dass die App einfriert."""
    return DEVICE == "cuda" or memory_gb() >= HR_MIN_MEMORY_GB


def read_image(source: str | Path | bytes) -> Image.Image:
    """Liest JPG/PNG/WebP/TIF (auch 16 Bit und CMYK) als 8-Bit-RGB."""
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            arr = np.asarray(img, dtype=np.float32)
            arr = arr / max(arr.max(), 1.0) * 255.0
            img = Image.fromarray(arr.astype(np.uint8))
        return img.convert("RGB")
    except Exception:
        # Pillow kann z. B. 16-Bit-RGB-TIFs nicht lesen, OpenCV schon.
        arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
        if arr is None:
            raise ValueError("Bildformat wird nicht unterstützt")
        if arr.dtype == np.uint16:
            arr = (arr / 257).astype(np.uint8)
        elif arr.dtype != np.uint8:
            arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
        elif arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGB)
        else:
            arr = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_BGR2RGB)
        return Image.fromarray(arr)


def _predict_mask(image: torch.Tensor, model_name: str) -> torch.Tensor:
    """image: (1,3,H,W) float 0..1 -> Alpha-Maske (1,1,H,W) in Originalgröße."""
    model = get_model(model_name)
    size = MODELS[model_name][2]
    x = F.interpolate(image, size=(size, size), mode="bilinear", align_corners=False, antialias=True)
    x = ((x - MEAN.to(x.device)) / STD.to(x.device)).to(DTYPE)
    pred = model(x)[-1].sigmoid().float()
    pred = F.interpolate(pred, size=image.shape[-2:], mode="bilinear", align_corners=False)
    return pred.clamp(0, 1)


def _box_blur(x: torch.Tensor, r: int) -> torch.Tensor:
    """Separabler Boxfilter (wie cv2.blur) über kumulierte Summen, O(1) je Pixel."""
    for dim in (-2, -1):
        p1, p2 = r // 2, r - 1 - r // 2
        pad = (0, 0, p1, p2) if dim == -2 else (p1, p2, 0, 0)
        c = F.pad(x, pad, mode="replicate").cumsum(dim)
        c = torch.cat([torch.zeros_like(c.narrow(dim, 0, 1)), c], dim)
        n = x.shape[dim]
        x = (c.narrow(dim, r, n) - c.narrow(dim, 0, n)) / r
    return x


def _blur_fusion(fg, bg, image, alpha, r):
    blurred_alpha = _box_blur(alpha, r)
    blurred_fg = _box_blur(fg * alpha, r) / (blurred_alpha + 1e-5)
    blurred_bg = _box_blur(bg * (1 - alpha), r) / ((1 - blurred_alpha) + 1e-5)
    fg = blurred_fg + alpha * (image - alpha * blurred_fg - (1 - alpha) * blurred_bg)
    return fg.clamp(0, 1), blurred_bg


def _estimate_foreground(image: torch.Tensor, alpha: torch.Tensor) -> torch.Tensor:
    """Schätzt die reinen Vordergrundfarben an halbtransparenten Kanten,
    damit Haare und Ränder keinen Farbsaum vom alten Hintergrund behalten
    (Approximate Fast Foreground Colour Estimation, Forte & Pitié 2021)."""
    fg, blurred_bg = _blur_fusion(image, image, image, alpha, 90)
    fg, _ = _blur_fusion(fg, blurred_bg, image, alpha, 6)
    return fg


@torch.inference_mode()
def _run(img: Image.Image, model_name: str, refine: bool, device: str) -> np.ndarray:
    image = torch.from_numpy(np.array(img)).to(device).permute(2, 0, 1).unsqueeze(0).float() / 255.0
    alpha = _predict_mask(image.to(DEVICE), model_name).to(device)
    rgb = _estimate_foreground(image, alpha) if refine else image
    rgba = (torch.cat([rgb, alpha], 1)[0] * 255 + 0.5).to(torch.uint8)
    return rgba.permute(1, 2, 0).cpu().numpy()


def remove_background(img: Image.Image, model_name: str = "standard", refine: bool = True) -> Image.Image:
    # Auf dem Mac teilen sich GPU und System den Speicher: dort nur das Modell auf der GPU,
    # die Kantenbereinigung in voller Bildgröße auf dem Prozessor.
    refine_device = "cpu" if DEVICE == "mps" else DEVICE
    with _lock:
        try:
            arr = _run(img, model_name, refine, refine_device)
        except torch.OutOfMemoryError:
            # Sehr große Bilder: Maske auf der GPU, Kantenbereinigung im RAM.
            torch.cuda.empty_cache()
            arr = _run(img, model_name, refine, "cpu")
        finally:
            if DEVICE == "cuda":
                torch.cuda.empty_cache()
            elif DEVICE == "mps":
                torch.mps.empty_cache()
    return Image.fromarray(arr, "RGBA")

