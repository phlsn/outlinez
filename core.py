"""Freistellen mit BiRefNet: Bild rein, RGBA-Bild mit transparentem Hintergrund raus."""

import io
import os
import threading
from pathlib import Path

ROOT = Path(__file__).parent
if (ROOT / ".installed").exists():
    # Installierte App: Modelle liegen im App-Ordner und werden bei der Deinstallation mit entfernt
    os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
# Mac: Operationen ohne MPS-Kernel (z. B. deform_conv2d in BiRefNet) laufen dann auf dem Prozessor
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

MODELS = {
    # name: (Hugging-Face-Repo, festgelegte Version, Eingabeauflösung)
    "standard": ("ZhengPeng7/BiRefNet", "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4", 1024),
    "hr": ("ZhengPeng7/BiRefNet_HR", "a7a562f6fd16021180f2f4348f4de003a2d3d1e1", 2048),
}

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
        # Erster Durchlauf initialisiert die GPU-Kernel (~2 s), danach geht es schnell.
        with torch.inference_mode():
            _models[name](torch.zeros(1, 3, MODELS[name][2], MODELS[name][2], device=DEVICE, dtype=DTYPE))
    return _models[name]


def device_name() -> str:
    if DEVICE == "cuda":
        return torch.cuda.get_device_name(0)
    return "Apple-Grafikeinheit (MPS)" if DEVICE == "mps" else "Prozessor (ohne GPU, langsamer)"


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
    with _lock:
        try:
            arr = _run(img, model_name, refine, DEVICE)
        except torch.OutOfMemoryError:
            # Sehr große Bilder: Maske auf der GPU, Kantenbereinigung im RAM.
            torch.cuda.empty_cache()
            arr = _run(img, model_name, refine, "cpu")
        finally:
            if DEVICE == "cuda":
                torch.cuda.empty_cache()
    return Image.fromarray(arr, "RGBA")

