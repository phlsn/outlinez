"""Speicherorte je Betriebssystem (Einstellungen, Log, auf dem Mac auch Laufzeitumgebung und Modelle)."""

import os
import sys
from pathlib import Path

APP_NAME = "Outlinez"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


def config_dir() -> Path:
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
