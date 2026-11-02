"""Fertige Dateien aus Original + Freistellung erzeugen: PNG/WebP/JPG oder PSD mit Ebenen."""

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

import psd
from effects import Shadow, compose, content_box, make_shadow

FORMATS = ("png", "webp", "jpg", "psd")

DEFAULTS = {
    "bg": "transparent",  # transparent | color
    "color": "#ffffff",
    "crop": False,
    "margin": 3,          # Prozent
    "format": "psd",
    "shadow": {"kind": "none", "opacity": 0.5, "softness": 0.5, "angle": 45, "distance": 0.5},
}


@dataclass
class Options:
    format: str = "png"
    bg: tuple[int, int, int] | None = None
    crop: bool = False
    margin: float = 0.03
    shadow: Shadow = field(default_factory=Shadow)

    @classmethod
    def from_settings(cls, s: dict) -> "Options":
        s = {**DEFAULTS, **(s or {})}
        fmt = s["format"] if s["format"] in FORMATS else "png"
        bg = None
        if s["bg"] == "color":
            bg = hex_to_rgb(s["color"])
        elif fmt == "jpg":
            bg = (255, 255, 255)
        return cls(fmt, bg, bool(s["crop"]), float(s["margin"]) / 100, Shadow.from_dict(s.get("shadow")))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def _parts(original: Image.Image, cutout: Image.Image, opt: Options):
    rgba = np.asarray(cutout, np.float32) / 255.0
    fg, alpha = rgba[..., :3], np.ascontiguousarray(rgba[..., 3])
    shadow = make_shadow(alpha, opt.shadow)
    orig = np.asarray(original.convert("RGB"))
    if opt.crop:
        x0, y0, x1, y1 = content_box(alpha, shadow, opt.margin)
        fg, alpha, shadow, orig = fg[y0:y1, x0:x1], alpha[y0:y1, x0:x1], shadow[y0:y1, x0:x1], orig[y0:y1, x0:x1]
    return fg, alpha, shadow, orig


def render(original: Image.Image, cutout: Image.Image, opt: Options) -> Image.Image:
    fg, alpha, shadow, _ = _parts(original, cutout, opt)
    return Image.fromarray(compose(fg, alpha, shadow, opt.bg))


def write_psd(fp, original: Image.Image, cutout: Image.Image, opt: Options) -> None:
    fg, alpha, shadow, orig = _parts(original, cutout, opt)
    h, w = alpha.shape
    full = np.full((h, w), 255, np.uint8)
    to8 = lambda x: (x * 255 + 0.5).astype(np.uint8)

    layers = [psd.Layer("Original", orig, alpha=full, visible=False)]
    if opt.bg is not None:
        layers.append(psd.Layer("Hintergrund", np.broadcast_to(np.uint8(opt.bg), (h, w, 3)), alpha=full))
    if opt.shadow.kind != "none":
        layers.append(psd.Layer("Schatten", np.zeros((h, w, 3), np.uint8), alpha=to8(shadow), blend="mul "))
    layers.append(psd.Layer("Motiv", to8(fg), alpha=full, mask=to8(alpha)))

    psd.write_psd(fp, w, h, layers, compose(fg, alpha, shadow, opt.bg))


def encode(original: Image.Image, cutout: Image.Image, opt: Options) -> bytes:
    buf = io.BytesIO()
    if opt.format == "psd":
        write_psd(buf, original, cutout, opt)
    else:
        img = render(original, cutout, opt)
        if opt.format == "jpg":
            img.convert("RGB").save(buf, "JPEG", quality=95, subsampling=0)
        elif opt.format == "webp":
            img.save(buf, "WEBP", quality=95)
        else:
            img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def preview(original: Image.Image, cutout: Image.Image, opt: Options, max_size: int = 900) -> tuple[bytes, str]:
    """Schnelle, verkleinerte Vorschau mit allen Einstellungen (PSD wird wie PNG gezeigt)."""
    scale = min(1.0, max_size / max(cutout.size))
    if scale < 1:
        size = (max(1, round(cutout.width * scale)), max(1, round(cutout.height * scale)))
        original, cutout = original.resize(size, Image.BILINEAR), cutout.resize(size, Image.BILINEAR)
    img = render(original, cutout, opt)
    buf = io.BytesIO()
    if img.mode == "RGB":
        img.save(buf, "JPEG", quality=88)
        return buf.getvalue(), "image/jpeg"
    img.save(buf, "PNG", compress_level=1)
    return buf.getvalue(), "image/png"


def extension(opt: Options) -> str:
    return opt.format
