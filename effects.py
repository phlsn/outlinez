"""Schatten aus der Freistellmaske erzeugen und Ebenen zusammensetzen."""

import math
from dataclasses import dataclass, fields

import cv2
import numpy as np

SHADOW_KINDS = ("none", "drop", "ground", "perspective")
WORK_SIZE = 1600  # Schatten sind weich, also reicht eine reduzierte Arbeitsauflösung


@dataclass
class Shadow:
    kind: str = "none"       # none | drop | ground | perspective
    opacity: float = 0.5     # 0..1
    softness: float = 0.5    # 0..1
    angle: float = 45.0      # Richtung, in die der Schatten fällt (0 = rechts, 90 = unten)
    distance: float = 0.5    # 0..1, Versatz (Schlagschatten) bzw. Länge (perspektivisch)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Shadow":
        d = d or {}
        return cls(**{f.name: type(f.default)(d[f.name]) for f in fields(cls) if f.name in d})


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(a, (0, 0), max(sigma, 0.5)) if sigma > 0.3 else a


def _warp(a: np.ndarray, m) -> np.ndarray:
    return cv2.warpAffine(a, np.float32(m), (a.shape[1], a.shape[0]), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _contact(a, base_y, size, softness):
    """Dunkle Kontaktzone direkt unter dem Motiv."""
    band = a * (np.arange(a.shape[0])[:, None] > base_y - 0.03 * size)
    k = 0.15
    band = _warp(band, [[1, 0, 0], [0, k, base_y * (1 - k) + 0.004 * size]])
    return _blur(band, size * (0.004 + 0.01 * softness))


def make_shadow(alpha: np.ndarray, s: Shadow) -> np.ndarray:
    """Schatten-Deckkraft (float32 0..1, gleiche Größe wie alpha)."""
    h, w = alpha.shape
    if s.kind == "none" or s.opacity <= 0:
        return np.zeros_like(alpha)

    scale = min(1.0, WORK_SIZE / max(h, w))
    a = cv2.resize(alpha, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    ys, xs = np.nonzero(a > 0.5)
    if len(ys) == 0:
        return np.zeros_like(alpha)
    base = float(ys.max())
    size = float(max(xs.max() - xs.min(), ys.max() - ys.min()) + 1)
    rad = math.radians(s.angle)
    soft = s.softness

    if s.kind == "drop":
        dist = s.distance * 0.08 * size
        sh = _warp(a, [[1, 0, math.cos(rad) * dist], [0, 1, math.sin(rad) * dist]])
        sh = _blur(sh, size * (0.003 + 0.04 * soft))

    elif s.kind == "ground":
        # Silhouette flach auf den Boden legen, nach hinten und vorne um die Standfläche verteilt
        k = 0.05 + 0.05 * soft
        cx = float(xs.mean())
        sx = 1.08 + 0.1 * soft
        back = _warp(a, [[sx, 0, cx * (1 - sx)], [0, k, base * (1 - k)]])
        front = _warp(a, [[sx, 0, cx * (1 - sx)], [0, -0.5 * k, base * (1 + 0.5 * k)]])
        flat = _blur(np.maximum(back, front), size * (0.012 + 0.04 * soft))
        sh = np.clip(0.85 * flat + 0.8 * _contact(a, base, size, soft), 0, 1)

    elif s.kind == "perspective":
        length = 0.3 + 1.2 * s.distance
        sx = length * math.cos(rad)
        sy = 0.5 * length * math.sin(rad)
        if abs(sy) < 0.08:
            sy = 0.08 if sy >= 0 else -0.08
        # Punkt in Höhe (base - y) über dem Boden wandert um diese Höhe * (sx, sy)
        cast = _warp(a, [[1, -sx, sx * base], [0, -sy, base + sy * base]])
        # Nah am Motiv scharf und dunkel, weiter weg weicher und heller
        dist = cv2.distanceTransform((a < 0.5).astype(np.uint8), cv2.DIST_L2, 5)
        t = np.clip(dist / (0.6 * size * length), 0, 1)
        sharp = _blur(cast, size * (0.002 + 0.006 * soft))
        blurry = _blur(cast, size * (0.02 + 0.06 * soft))
        sh = (sharp * (1 - t) + blurry * t) * (1 - 0.65 * t)
        sh = np.clip(np.maximum(sh, 0.9 * _contact(a, base, size, soft)), 0, 1)

    else:
        raise ValueError(f"Unbekannte Schattenart: {s.kind}")

    sh = cv2.resize(sh, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(sh * s.opacity, 0, 1).astype(np.float32)


def content_box(alpha: np.ndarray, shadow: np.ndarray, margin: float) -> tuple[int, int, int, int]:
    """Begrenzungsrahmen von Motiv und Schatten plus Rand (Anteil der größeren Seite)."""
    mask = (alpha > 0.03) | (shadow > 0.03)
    ys, xs = np.nonzero(mask)
    h, w = alpha.shape
    if len(ys) == 0:
        return 0, 0, w, h
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    pad = int(max(x1 - x0, y1 - y0) * margin)
    return max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, w), min(y1 + pad, h)


def compose(fg: np.ndarray, alpha: np.ndarray, shadow: np.ndarray, bg: tuple[int, int, int] | None) -> np.ndarray:
    """fg: HxWx3 float 0..1, alpha/shadow: HxW. Ergebnis: uint8 RGB (mit bg) oder RGBA (ohne)."""
    a = alpha[:, :, None]
    s = shadow[:, :, None]
    if bg is not None:
        base = np.asarray(bg, np.float32) / 255.0
        rgb = fg * a + base * (1 - s) * (1 - a)
        return (rgb * 255 + 0.5).astype(np.uint8)
    out_a = a + s * (1 - a)
    rgb = np.where(out_a > 1e-6, fg * a / np.maximum(out_a, 1e-6), 0)
    return (np.dstack([rgb, out_a]) * 255 + 0.5).astype(np.uint8)
