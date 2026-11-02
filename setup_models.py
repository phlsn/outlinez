"""Lädt die KI-Modelle einmalig herunter (wird vom Installer aufgerufen).

uv run setup_models.py [standard] [hr]   (ohne Angabe: beide)
"""

import os
import sys

os.environ["HF_HUB_OFFLINE"] = "0"  # die installierte App läuft offline, hier wird aber geladen

import core  # noqa: E402  (setzt HF_HOME für die installierte App)
from huggingface_hub import snapshot_download  # noqa: E402


def main():
    names = sys.argv[1:] or list(core.MODELS)
    for n, name in enumerate(names, 1):
        repo, revision, _ = core.MODELS[name]
        print(f"Lade KI-Modell {n}/{len(names)} ({name}) ...", flush=True)
        snapshot_download(repo, revision=revision)
    print("Modelle bereit.", flush=True)


if __name__ == "__main__":
    main()
