"""Outlinez als eigenes Programmfenster (Windows: Edge WebView2, macOS: WebKit), ohne Browser und Konsole.

Start: Verknüpfung / Outlinez.app oder  uv run app.py
"""

import os
import socket
import sys
from pathlib import Path

from paths import IS_MAC, IS_WINDOWS, config_dir

ROOT = Path(__file__).parent
ICON = ROOT / "assets" / "outlinez.ico"
ICON_PNG = ROOT / "static" / "icon.png"
LOG_DIR = config_dir()

# Ohne Konsole (pythonw bzw. Start aus der .app): Ausgaben und Fehler in eine Logdatei schreiben
if sys.stdout is None or sys.stderr is None or os.environ.get("OUTLINEZ_LOG"):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(LOG_DIR / "app.log", "w", encoding="utf-8", buffering=1)

import webview  # noqa: E402
from webview.dom import DOMEventHandler  # noqa: E402

import server  # noqa: E402

IMAGE_TYPES = ("Bilder (*.jpg;*.jpeg;*.png;*.webp;*.tif;*.tiff;*.bmp)", "Alle Dateien (*.*)")


class Api:
    """Wird im Fenster als window.pywebview.api bereitgestellt."""

    def __init__(self):
        self._window = None

    def pick_files(self):
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=IMAGE_TYPES)
        return list(result or [])

    def pick_folder(self, start=""):
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start or "")
        return result[0] if result else None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def on_drop(event):
    files = (event.get("dataTransfer") or {}).get("files") or []
    paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
    if paths:
        server.manager.add_paths(paths)


def on_start(window):
    window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
    if IS_WINDOWS:
        try:  # eigenes Fenstersymbol statt Python-Symbol
            from System import Action
            from System.Drawing import Icon

            window.native.Invoke(Action(lambda: setattr(window.native, "Icon", Icon(str(ICON)))))
        except Exception as e:
            print("Symbol nicht gesetzt:", e)


def brand_process():
    """Taskleiste bzw. Dock sollen Outlinez zeigen, nicht Python."""
    if IS_WINDOWS:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Outlinez.App")
    elif IS_MAC:
        try:
            from AppKit import NSApplication, NSImage
            from Foundation import NSBundle

            info = NSBundle.mainBundle().infoDictionary()
            info["CFBundleName"] = "Outlinez"
            NSApplication.sharedApplication().setApplicationIconImage_(
                NSImage.alloc().initWithContentsOfFile_(str(ICON_PNG)))
        except Exception as e:
            print("Dock-Symbol nicht gesetzt:", e)


def main():
    brand_process()
    port = int(os.environ.get("OUTLINEZ_PORT") or free_port())  # fester Port nur für Tests
    server.start_background(port)

    api = Api()
    window = webview.create_window(
        "Outlinez", f"http://127.0.0.1:{port}/?native=1", js_api=api,
        width=1320, height=860, min_size=(900, 600), background_color="#1c1c1f",
    )
    api._window = window
    webview.start(on_start, window, gui="edgechromium" if IS_WINDOWS else None, private_mode=False,
                  storage_path=str(LOG_DIR / "webview"))
    os._exit(0)  # Hintergrund-Threads (Server, GPU) sofort beenden


if __name__ == "__main__":
    main()
