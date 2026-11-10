"""Bildliste, Verarbeitungs-Warteschlange, Einstellungen und Ordnerüberwachung."""

import json
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

import core
import export
from paths import config_dir

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
SUFFIX = "-freigestellt"
CACHE_SIZE = 24  # so viele Ergebnisse bleiben dekodiert im Speicher, ältere werden bei Bedarf neu berechnet

CONFIG_DIR = config_dir()
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LEGACY_SETTINGS = CONFIG_DIR.parent / "Freisteller" / "settings.json"  # bis zur Umbenennung in Outlinez

APP_DEFAULTS = {
    # HR (2048 px) nur mit NVIDIA-Karte als Standard; auf Mac/CPU ist es sehr speicher- und zeithungrig
    "model": "hr" if core.DEVICE == "cuda" else "standard",
    "out_mode": "beside",  # beside | folder
    "out_dir": "",
    "watch_dir": "",
    "watch_on": False,
}


@dataclass
class Job:
    id: int
    name: str
    path: Path | None = None
    data: bytes | None = None        # Quelldaten bei hochgeladenen Bildern
    auto_save: bool = False
    status: str = "queued"           # queued | processing | done | error
    model: str = "standard"
    seconds: float | None = None
    error: str | None = None
    saved_to: str | None = None
    created: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status, "model": self.model,
                "seconds": self.seconds, "error": self.error, "saved_to": self.saved_to,
                "has_path": self.path is not None}


class Manager:
    def __init__(self):
        self.jobs: OrderedDict[int, Job] = OrderedDict()
        self.cache: OrderedDict[int, tuple[Image.Image, Image.Image]] = OrderedDict()
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)
        self.next_id = 1
        self.rev = 0                 # steigt bei jeder Änderung, damit die Oberfläche neu lädt
        self.ready = False
        self.load_error = None
        self.load_step = "Starte …"          # aktueller Ladeschritt für die Statuszeile
        self.load_started = time.time()
        self.settings = {**export.DEFAULTS, **APP_DEFAULTS}
        try:
            source = SETTINGS_FILE if SETTINGS_FILE.exists() else LEGACY_SETTINGS
            saved = json.loads(source.read_text("utf-8-sig"))
            self.settings.update({k: v for k, v in saved.items() if k in self.settings})
        except (OSError, ValueError):
            pass
        self.hr_supported = core.hr_supported()
        if not self.hr_supported:
            self.settings["model"] = "standard"
        self._observer = None
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------- Einstellungen ----------
    def update_settings(self, changes: dict) -> dict:
        with self.lock:
            for k, v in changes.items():
                if k == "shadow" and isinstance(v, dict):
                    self.settings["shadow"] = {**self.settings["shadow"], **v}
                elif k == "model" and v == "hr" and not self.hr_supported:
                    continue  # zu wenig Arbeitsspeicher, siehe core.hr_supported
                elif k in self.settings:
                    self.settings[k] = v
            self.rev += 1
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2, ensure_ascii=False), "utf-8")
            except OSError:
                pass
        if {"watch_on", "watch_dir", "out_dir", "out_mode"} & changes.keys():
            self.configure_watch()
        return self.settings

    def options(self) -> export.Options:
        return export.Options.from_settings(self.settings)

    # ---------- Bilder hinzufügen ----------
    def _add(self, **kw) -> Job:
        with self.lock:
            job = Job(id=self.next_id, model=self.settings["model"], **kw)
            self.next_id += 1
            self.jobs[job.id] = job
            self.rev += 1
            self.wake.notify()
            return job

    def add_upload(self, name: str, data: bytes) -> Job:
        return self._add(name=name or "eingefuegt.png", data=data)

    def add_paths(self, paths, auto_save=False) -> list[Job]:
        added = []
        for p in map(Path, paths):
            if p.is_dir():
                files = sorted(f for f in p.iterdir() if f.suffix.lower() in EXTENSIONS and SUFFIX not in f.stem)
            elif p.is_file() and p.suffix.lower() in EXTENSIONS:
                files = [p]
            else:
                files = []
            added += [self._add(name=f.name, path=f, auto_save=auto_save) for f in files]
        return added

    def redo(self, job_id: int):
        with self.lock:
            job = self.jobs[job_id]
            job.status, job.model, job.error, job.saved_to = "queued", self.settings["model"], None, None
            self.cache.pop(job_id, None)
            self.rev += 1
            self.wake.notify()

    def remove(self, job_id: int | None = None):
        with self.lock:
            ids = [job_id] if job_id is not None else list(self.jobs)
            for i in ids:
                self.jobs.pop(i, None)
                self.cache.pop(i, None)
            self.rev += 1

    # ---------- Verarbeitung ----------
    def load_model(self):
        def progress(text):
            with self.lock:
                self.load_step = text
                self.rev += 1

        try:
            core.get_model(self.settings["model"], progress)
            self.ready = True
        except Exception as e:
            self.load_error = str(e)
        finally:
            with self.lock:
                self.rev += 1

    def _source(self, job: Job) -> Image.Image:
        return core.read_image(job.path if job.path else job.data)

    def _process(self, job: Job) -> tuple[Image.Image, Image.Image]:
        original = self._source(job)
        start = time.perf_counter()
        cutout = core.remove_background(original, job.model)
        job.seconds = round(time.perf_counter() - start, 2)
        self._remember(job.id, original, cutout)
        return original, cutout

    def _remember(self, job_id, original, cutout):
        with self.lock:
            self.cache[job_id] = (original, cutout)
            self.cache.move_to_end(job_id)
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)

    def images(self, job_id: int) -> tuple[Image.Image, Image.Image]:
        with self.lock:
            job = self.jobs[job_id]
            if job_id in self.cache:
                self.cache.move_to_end(job_id)
                return self.cache[job_id]
        if job.status != "done":
            raise LookupError("Noch nicht fertig")
        return self._process(job)

    def original(self, job_id: int) -> Image.Image:
        with self.lock:
            job = self.jobs[job_id]
            if job_id in self.cache:
                return self.cache[job_id][0]
        return self._source(job)

    def _worker(self):
        while True:
            with self.lock:
                while not self.ready or not any(j.status == "queued" for j in self.jobs.values()):
                    self.wake.wait(timeout=1.0)
                job = next(j for j in self.jobs.values() if j.status == "queued")
                job.status = "processing"
                self.rev += 1
            try:
                self._process(job)
                job.status = "done"
                if job.auto_save:
                    self.save(job.id)
            except Exception as e:
                traceback.print_exc()
                job.status, job.error = "error", str(e) or e.__class__.__name__
            with self.lock:
                self.rev += 1

    # ---------- Speichern ----------
    def target_path(self, job: Job, opt: export.Options) -> Path:
        stem = Path(job.name).stem
        if self.settings["out_mode"] == "beside" and job.path:
            folder = job.path.parent
        elif self.settings["out_dir"]:
            folder = Path(self.settings["out_dir"])
        else:
            raise ValueError("Bitte einen Ausgabeordner wählen")
        return folder / f"{stem}{SUFFIX}.{opt.format}"

    def save(self, job_id: int) -> str:
        job = self.jobs[job_id]
        opt = self.options()
        target = self.target_path(job, opt)
        original, cutout = self.images(job_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(export.encode(original, cutout, opt))
        tmp.replace(target)
        with self.lock:
            job.saved_to = str(target)
            self.rev += 1
        return job.saved_to

    # ---------- Ordnerüberwachung ----------
    def configure_watch(self):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        if self._observer:
            self._observer.stop()
            self._observer = None
        folder = Path(self.settings["watch_dir"]) if self.settings["watch_dir"] else None
        if not (self.settings["watch_on"] and folder and folder.is_dir()):
            return
        manager = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                self.handle(event.src_path, event.is_directory)

            def on_moved(self, event):
                self.handle(event.dest_path, event.is_directory)

            def handle(self, path, is_dir):
                p = Path(path)
                if is_dir or p.suffix.lower() not in EXTENSIONS or SUFFIX in p.stem or p.parent != folder:
                    return
                threading.Thread(target=manager._add_when_complete, args=(p,), daemon=True).start()

        self._observer = Observer()
        self._observer.schedule(Handler(), str(folder), recursive=False)
        self._observer.start()

    def _add_when_complete(self, path: Path):
        # warten, bis die Datei fertig kopiert ist (Größe bleibt gleich)
        last = -1
        for _ in range(120):
            try:
                size = path.stat().st_size
            except OSError:
                return
            if size == last and size > 0:
                break
            last = size
            time.sleep(0.5)
        self.add_paths([path], auto_save=True)

    def state(self) -> dict:
        with self.lock:
            return {"rev": self.rev, "ready": self.ready, "load_error": self.load_error,
                    "load_step": self.load_step, "load_seconds": int(time.time() - self.load_started),
                    "device": core.device_name(), "settings": self.settings,
                    "hr_supported": self.hr_supported, "memory_gb": round(core.memory_gb()),
                    "jobs": [j.public() for j in self.jobs.values()]}
