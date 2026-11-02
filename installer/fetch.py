"""Ersteinrichtung: lädt alle Dateien der Download-Liste mit Fortschritt, Rate und Restzeit,
prüft Größe und SHA-256, setzt abgebrochene Downloads fort und installiert die Pakete offline.
Nur Standardbibliothek (läuft mit dem beigelegten Python, bevor Pakete installiert sind).

python fetch.py --manifest M --hf-home H --venv V --uv UV --work W [--cancel-file F] [--stamp TEXT] [--compile DIR]

Ausgabe für den Windows-Installer: "@@S <Abschnitt>" und "@@P <Promille> <Text>".
Exit-Code: 0 fertig, 3 abgebrochen, 1 Fehler. Die Mac-Ersteinrichtung nutzt die Klasse Setup direkt.
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

CHUNK = 1 << 20
RETRIES = 4


class Cancelled(Exception):
    pass


def fmt_bytes(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB".replace(".", ",")
    return f"{n / 1e6:.0f} MB"


def fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "Restzeit wird berechnet …"
    if seconds < 60:
        return f"noch ca. {max(5, math.ceil(seconds / 5) * 5)} Sek."
    if seconds < 3600:
        return f"noch ca. {math.ceil(seconds / 60)} Min."
    return f"noch ca. {int(seconds // 3600)} Std. {math.ceil(seconds % 3600 / 60)} Min."


class Setup:
    def __init__(self, manifest: Path, hf_home: Path, venv: Path, uv: Path, work: Path,
                 report, cancel: threading.Event):
        self.manifest = json.loads(manifest.read_text("utf-8"))
        self.base = manifest.parent
        self.hf_home, self.venv, self.uv, self.work = hf_home, venv, uv, work
        self.report = report            # report(abschnitt, promille | None, text)
        self.cancel = cancel
        self.files = self.manifest["files"]
        self.total = sum(f["size"] for f in self.files if f["kind"] != "bundled")
        self.done = 0
        self.samples = deque()
        self.last_report = 0.0

    # ---------- Pfade ----------
    def target(self, f) -> Path:
        if f["kind"] == "bundled":
            return self.base / f["bundled"]
        return (self.hf_home if f["kind"] == "model" else self.work) / f["path"]

    def complete(self, f) -> bool:
        t = self.target(f)
        return t.exists() and t.stat().st_size == f["size"]

    def partial(self, f) -> int:
        part = self.target(f).with_name(self.target(f).name + ".part")
        size = part.stat().st_size if part.exists() else 0
        return size if size <= f["size"] else 0

    # ---------- Fortschritt ----------
    def add(self, n: int, label: str, force=False):
        self.done += n
        now = time.monotonic()
        self.samples.append((now, self.done))
        while self.samples and now - self.samples[0][0] > 8:
            self.samples.popleft()
        if not force and now - self.last_report < 0.3:
            return
        self.last_report = now
        rate = eta = None
        if len(self.samples) > 1 and now - self.samples[0][0] > 1.5:
            rate = (self.done - self.samples[0][1]) / (now - self.samples[0][0])
            eta = (self.total - self.done) / rate if rate > 0 else None
        parts = [f"{fmt_bytes(self.done)} von {fmt_bytes(self.total)}"]
        parts.append(f"{fmt_bytes(rate)}/s" if rate else "Verbinde …")
        parts.append(fmt_eta(eta))
        parts.append(label)
        self.report("Komponenten und KI-Modelle werden geladen",
                    int(1000 * self.done / max(self.total, 1)), " · ".join(parts))

    # ---------- Laden ----------
    def download_all(self):
        todo = []
        for f in self.files:
            if f["kind"] == "bundled":
                continue
            if self.complete(f):
                self.done += f["size"]
            else:
                self.done += self.partial(f)  # angefangene Downloads werden fortgesetzt
                todo.append(f)
        self.add(0, "", force=True)
        for f in todo:
            self.fetch(f)

    def fetch(self, f):
        t = self.target(f)
        t.parent.mkdir(parents=True, exist_ok=True)
        part = t.with_name(t.name + ".part")
        label = f["label"] + (f" ({fmt_bytes(f['size'])})" if f["size"] > 50e6 else "")
        counted = self.partial(f)  # Bytes dieser Datei, die schon in self.done stecken
        for attempt in range(RETRIES):
            pos = part.stat().st_size if part.exists() else 0
            if pos > f["size"]:
                part.unlink()
                pos = 0
            self.add(pos - counted, label)
            counted = pos
            try:
                headers = {"User-Agent": "Outlinez-Setup"}
                if pos:
                    headers["Range"] = f"bytes={pos}-"
                with urllib.request.urlopen(urllib.request.Request(f["url"], headers=headers), timeout=30) as r:
                    if pos and r.status != 206:  # Server kann nicht fortsetzen
                        self.add(-counted, label)
                        counted = pos = 0
                    with open(part, "ab" if pos else "wb") as out:
                        while chunk := r.read(CHUNK):
                            if self.cancel.is_set():
                                raise Cancelled()
                            out.write(chunk)
                            counted += len(chunk)
                            self.add(len(chunk), label)
                break
            except Cancelled:
                raise
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                if attempt == RETRIES - 1:
                    raise RuntimeError(f"Download fehlgeschlagen: {f['url']} ({e})") from e
                self.report(None, None, f"Verbindung unterbrochen, neuer Versuch … ({e})")
                for _ in range(10 * (attempt + 1)):
                    if self.cancel.is_set():
                        raise Cancelled()
                    time.sleep(0.2)
        self.verify(f, part)
        part.replace(t)

    def verify(self, f, part: Path):
        if part.stat().st_size != f["size"]:
            part.unlink()
            raise RuntimeError(f"Datei unvollständig: {f['path']}")
        if f["sha256"]:
            h = hashlib.sha256()
            with open(part, "rb") as fp:
                while chunk := fp.read(8 * CHUNK):
                    if self.cancel.is_set():
                        raise Cancelled()
                    h.update(chunk)
            if h.hexdigest() != f["sha256"]:
                part.unlink()
                raise RuntimeError(f"Prüfsumme falsch, Datei beschädigt: {f['path']}")

    # ---------- Installieren ----------
    def install(self, compile_dir: Path | None = None):
        self.report("Komponenten werden installiert", 1000, "Das dauert etwa eine Minute …")
        if self.venv.exists():
            shutil.rmtree(self.venv)
        env = {**os.environ, "UV_CACHE_DIR": str(self.work / "uv-cache"), "UV_PYTHON_DOWNLOADS": "never"}
        run = lambda *a: subprocess.run([str(self.uv), *a], env=env, check=True, capture_output=True, text=True)
        run("venv", str(self.venv), "--python", sys.executable, "--no-project")
        py = self.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        wheels = [str(self.target(f)) for f in self.files if f["kind"] in ("wheel", "bundled")]
        run("pip", "install", "--python", str(py), "--offline", "--no-index", "--no-deps", "--compile-bytecode", *wheels)
        if compile_dir:  # App-Dateien vorkompilieren (Program Files ist später schreibgeschützt)
            subprocess.run([sys.executable, "-m", "compileall", "-q", "-l", str(compile_dir)], capture_output=True)
        shutil.rmtree(self.work, ignore_errors=True)  # geladene Pakete werden nicht mehr gebraucht

    def run(self, compile_dir: Path | None = None):
        self.download_all()
        self.install(compile_dir)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--hf-home", type=Path, required=True)
    p.add_argument("--venv", type=Path, required=True)
    p.add_argument("--uv", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--cancel-file", type=Path)
    p.add_argument("--stamp", help="nach Erfolg in VENV/.outlinez-version schreiben")
    p.add_argument("--compile", type=Path)
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Umlaute und „·“ sauber an den Installer

    cancel = threading.Event()
    if a.cancel_file:
        a.cancel_file.unlink(missing_ok=True)

        def watch():
            while not cancel.is_set():
                if a.cancel_file.exists():
                    cancel.set()
                time.sleep(0.2)
        threading.Thread(target=watch, daemon=True).start()

    section = [""]

    def report(title, permille, text):
        if title and title != section[0]:
            section[0] = title
            print(f"@@S {title}", flush=True)
        if permille is not None:
            print(f"@@P {permille} {text}", flush=True)
        else:
            print(text, flush=True)

    try:
        Setup(a.manifest, a.hf_home, a.venv, a.uv, a.work, report, cancel).run(a.compile)
        if a.stamp:
            (a.venv / ".outlinez-version").write_text(a.stamp)
    except Cancelled:
        print("Abgebrochen.", flush=True)
        sys.exit(3)
    except subprocess.CalledProcessError as e:
        print(f"Fehler bei der Installation: {e.stderr or e}", flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"Fehler: {e}", flush=True)
        sys.exit(1)
    print("Fertig.", flush=True)
    cancel.set()


if __name__ == "__main__":
    main()
