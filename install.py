"""Erstellt das Programmsymbol und Verknüpfungen auf dem Desktop und im Startmenü.

uv run install.py            Verknüpfungen anlegen
uv run install.py --remove   Verknüpfungen entfernen
"""

import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.resolve()
ICON = ROOT / "assets" / "outlinez.ico"
ICON_PNG = ROOT / "static" / "icon.png"   # auch Logo und Favicon der Oberfläche
VARIANTS = ROOT / "assets" / "icon-varianten"
VARIANT = 3  # gewählte Higgsfield-Variante (variante-1.png bis variante-4.png)
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
LINK_DIRS = [
    Path(os.environ["USERPROFILE"]) / "Desktop",
    Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]
LINKS = [d / "Outlinez.lnk" for d in LINK_DIRS]
LEGACY_LINKS = [d / "Freisteller.lnk" for d in LINK_DIRS]  # vor der Umbenennung


def make_icon(variant: int = VARIANT):
    """Schneidet die dunkle Kachel aus der generierten Variante aus (der karierte Rand dort ist
    nur gemalt, keine echte Transparenz) und speichert PNG und ICO."""
    rgb = np.asarray(Image.open(VARIANTS / f"variante-{variant}.png").convert("RGB"))
    dark = (rgb.astype(np.float32) @ [0.299, 0.587, 0.114] < 90).astype(np.uint8)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    tile = max(contours, key=cv2.contourArea)

    # Kachel gefüllt (inkl. Motiv), 4-fach überabgetastet für eine glatte Kante
    k = 4
    big = np.zeros((rgb.shape[0] * k, rgb.shape[1] * k), np.uint8)
    cv2.drawContours(big, [tile * k], -1, 255, -1, lineType=cv2.LINE_AA)
    big = cv2.erode(big, np.ones((3 * k, 3 * k), np.uint8))  # hellen Saum vom gemalten Rand abschneiden
    alpha = cv2.resize(big, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_AREA)

    x, y, w, h = cv2.boundingRect(tile)
    side = int(max(w, h) * 1.04)
    cx, cy = x + w // 2, y + h // 2
    img = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    img = img.crop((cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side)).resize((512, 512), Image.LANCZOS)

    ICON.parent.mkdir(exist_ok=True)
    img.save(ICON_PNG)
    img.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def create_links():
    if not PYTHONW.exists():
        sys.exit("Die Umgebung fehlt noch. Bitte zuerst einmal 'uv sync' ausführen.")
    make_icon()
    remove_links()
    for link in LINKS:
        link.parent.mkdir(parents=True, exist_ok=True)
        ps = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
            "$s.TargetPath = $env:TARGET; $s.Arguments = $env:ARGS; $s.WorkingDirectory = $env:WD;"
            "$s.IconLocation = $env:ICO; $s.Description = 'Bilder lokal freistellen'; $s.Save()"
        )
        env = {**os.environ, "LNK": str(link), "TARGET": str(PYTHONW), "ARGS": f'"{ROOT / "app.py"}"',
               "WD": str(ROOT), "ICO": str(ICON)}
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True)
        print("Angelegt:", link)


def remove_links():
    for link in LINKS + LEGACY_LINKS:
        if link.exists():
            link.unlink()
            print("Entfernt:", link)


if __name__ == "__main__":
    remove_links() if "--remove" in sys.argv else create_links()
