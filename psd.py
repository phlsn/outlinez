"""Minimaler PSD-Schreiber für RGB-Ebenen mit Transparenz und Ebenenmaske.

psd-tools kann keine Ebenenmasken erzeugen, deshalb wird die Dateistruktur hier nach der
Adobe-Spezifikation selbst geschrieben; nur die RLE-Kompression kommt aus psd-tools.
"""

import struct
from dataclasses import dataclass

import numpy as np
from psd_tools.compression import encode_rle


@dataclass
class Layer:
    name: str
    rgb: np.ndarray                    # HxWx3 uint8
    alpha: np.ndarray | None = None    # HxW uint8, Transparenz (None = deckend)
    mask: np.ndarray | None = None     # HxW uint8, bearbeitbare Ebenenmaske
    blend: str = "norm"                # 'norm', 'mul ' ...
    opacity: int = 255
    visible: bool = True


def _rle(plane: np.ndarray) -> bytes:
    h, w = plane.shape
    return encode_rle(np.ascontiguousarray(plane, np.uint8).tobytes(), w, h, 8, 1)


def _pascal(name: str) -> bytes:
    raw = name.encode("latin-1", "replace")[:255]
    data = bytes([len(raw)]) + raw
    return data + b"\0" * (-len(data) % 4)


def _unicode_name(name: str) -> bytes:
    # 'luni': Ebenenname als UTF-16, damit Umlaute in Photoshop korrekt erscheinen
    body = struct.pack(">I", len(name)) + name.encode("utf-16-be")
    body += b"\0" * (-len(body) % 4)
    return b"8BIM" + b"luni" + struct.pack(">I", len(body)) + body


def write_psd(fp, width: int, height: int, layers: list[Layer], composite: np.ndarray) -> None:
    """layers: von unten nach oben. composite: HxWx3 oder HxWx4 uint8 (zusammengesetztes Bild)."""
    records, channel_data = b"", b""
    for layer in layers:
        planes = []
        if layer.alpha is not None:
            planes.append((-1, layer.alpha))
        planes += [(i, layer.rgb[:, :, i]) for i in range(3)]
        if layer.mask is not None:
            planes.append((-2, layer.mask))

        encoded = [(cid, struct.pack(">H", 1) + _rle(p)) for cid, p in planes]
        rec = struct.pack(">iiii", 0, 0, height, width)
        rec += struct.pack(">H", len(encoded))
        rec += b"".join(struct.pack(">hI", cid, len(d)) for cid, d in encoded)
        flags = 0x08 | (0 if layer.visible else 0x02)
        rec += b"8BIM" + layer.blend.encode("ascii") + struct.pack(">BBBB", layer.opacity, 0, flags, 0)

        extra = b""
        if layer.mask is not None:
            extra += struct.pack(">I", 20) + struct.pack(">iiii", 0, 0, height, width) + struct.pack(">BBH", 0, 0, 0)
        else:
            extra += struct.pack(">I", 0)
        n_ranges = len(planes) - (1 if layer.mask is not None else 0)
        extra += struct.pack(">I", 8 + 8 * n_ranges) + struct.pack(">HH", 0, 0xFFFF) * 2 * (1 + n_ranges)
        extra += _pascal(layer.name) + _unicode_name(layer.name)
        rec += struct.pack(">I", len(extra)) + extra

        records += rec
        channel_data += b"".join(d for _, d in encoded)

    has_alpha = composite.ndim == 3 and composite.shape[2] == 4
    count = -len(layers) if has_alpha else len(layers)
    layer_info = struct.pack(">h", count) + records + channel_data
    layer_info += b"\0" * (-len(layer_info) % 4)
    layer_section = struct.pack(">I", len(layer_info)) + layer_info + struct.pack(">I", 0)

    n_channels = composite.shape[2]
    out = b"8BPS" + struct.pack(">H", 1) + b"\0" * 6
    out += struct.pack(">HIIHH", n_channels, height, width, 8, 3)  # 8 Bit, RGB
    out += struct.pack(">I", 0)  # Farbmodus-Daten
    out += struct.pack(">I", 0)  # Bildressourcen
    fp.write(out)
    fp.write(struct.pack(">I", len(layer_section)) + layer_section)

    planar = np.ascontiguousarray(np.moveaxis(composite, 2, 0)).reshape(n_channels * height, width)
    fp.write(struct.pack(">H", 1) + _rle(planar))
