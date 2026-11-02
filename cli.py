"""Stapelverarbeitung: uv run cli.py EINGABE... [-o AUSGABEORDNER] [Optionen]

Beispiele:
  uv run cli.py foto.jpg
  uv run cli.py C:\\Fotos\\Shooting -o C:\\Fotos\\freigestellt --crop --margin 3
  uv run cli.py C:\\Fotos\\*.tif --model hr --bg ffffff --format jpg
  uv run cli.py C:\\Fotos\\Produkte --format psd --shadow ground --shadow-opacity 0.6
"""

import argparse
import glob
import sys
import time
from pathlib import Path

import core
import export
from jobs import EXTENSIONS, SUFFIX


def collect(inputs: list[str]) -> list[Path]:
    files = []
    for pattern in inputs:
        for p in map(Path, glob.glob(pattern) or [pattern]):
            if p.is_dir():
                files += sorted(f for f in p.iterdir() if f.suffix.lower() in EXTENSIONS and SUFFIX not in f.stem)
            elif p.is_file():
                files.append(p)
            else:
                print(f"Nicht gefunden: {p}", file=sys.stderr)
    return files


def main():
    parser = argparse.ArgumentParser(description="Bilder lokal freistellen (BiRefNet).")
    parser.add_argument("inputs", nargs="+", help="Dateien, Ordner oder Muster wie *.jpg")
    parser.add_argument("-o", "--out", help="Ausgabeordner (Standard: Unterordner 'freigestellt' neben dem Bild)")
    parser.add_argument("--model", choices=list(core.MODELS), default="standard")
    parser.add_argument("--format", choices=export.FORMATS, default="png")
    parser.add_argument("--bg", help="Hintergrundfarbe als Hex, z. B. ffffff (Standard: transparent)")
    parser.add_argument("--crop", action="store_true", help="auf das Motiv zuschneiden")
    parser.add_argument("--margin", type=float, default=0, help="Rand beim Zuschneiden in Prozent")
    parser.add_argument("--shadow", choices=["none", "drop", "ground", "perspective"], default="none")
    parser.add_argument("--shadow-opacity", type=float, default=0.5, help="0 bis 1")
    parser.add_argument("--shadow-softness", type=float, default=0.5, help="0 bis 1")
    parser.add_argument("--shadow-angle", type=float, help="Richtung in Grad (0 = rechts, 90 = unten)")
    parser.add_argument("--shadow-distance", type=float, default=0.5, help="Abstand bzw. Länge, 0 bis 1")
    parser.add_argument("--overwrite", action="store_true", help="vorhandene Ergebnisse überschreiben")
    args = parser.parse_args()

    files = collect(args.inputs)
    if not files:
        sys.exit("Keine Bilder gefunden.")
    angle = args.shadow_angle if args.shadow_angle is not None else (300 if args.shadow == "perspective" else 45)
    opt = export.Options.from_settings({
        "format": args.format, "bg": "color" if args.bg else "transparent", "color": f"#{(args.bg or 'ffffff').lstrip('#')}",
        "crop": args.crop, "margin": args.margin,
        "shadow": {"kind": args.shadow, "opacity": args.shadow_opacity, "softness": args.shadow_softness,
                   "angle": angle, "distance": args.shadow_distance},
    })

    print(f"{len(files)} Bild(er), Modell '{args.model}' auf {core.DEVICE} ...")
    core.get_model(args.model)
    failed = 0
    for n, f in enumerate(files, 1):
        out_dir = Path(args.out) if args.out else f.parent / "freigestellt"
        target = out_dir / f"{f.stem}{SUFFIX}.{opt.format}"
        if target.exists() and not args.overwrite:
            print(f"[{n}/{len(files)}] {f.name}: übersprungen (existiert)")
            continue
        try:
            start = time.perf_counter()
            original = core.read_image(f)
            data = export.encode(original, core.remove_background(original, args.model), opt)
            out_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            print(f"[{n}/{len(files)}] {f.name} -> {target}  ({time.perf_counter() - start:.1f} s)")
        except Exception as e:
            failed += 1
            print(f"[{n}/{len(files)}] {f.name}: FEHLER {e}", file=sys.stderr)
    if failed:
        sys.exit(f"{failed} Bild(er) fehlgeschlagen.")


if __name__ == "__main__":
    main()
