"""Erstellt beim Bauen die Download-Liste für die Ersteinrichtung.

uv run --no-project --with packaging python installer/make_manifest.py win|mac AUSGABE.json

Enthält für die Zielplattform jedes Python-Paket (Wheel aus uv.lock, mit Adresse, Größe,
SHA-256) und jede Datei der KI-Modelle (Hugging Face). Mit der Gesamtgröße kann der
Downloader Fortschritt, Rate und Restzeit anzeigen.
"""

import json
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

from packaging import tags
from packaging.markers import Marker
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modelinfo import MODELS  # noqa: E402

PY = (3, 12)
BUNDLE_DIR: Path
TARGETS = {
    "win": {
        "platforms": ["win_amd64"],
        "env": {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "platform_machine": "AMD64"},
    },
    "mac": {
        # ab macOS 14 (PyTorch-Wheels; LSMinimumSystemVersion in build_macos.sh), Apple Silicon
        "platforms": list(tags.mac_platforms((14, 0), "arm64")),
        "env": {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix", "platform_machine": "arm64"},
    },
}


def head_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"])


def build_bundled(name: str, sdist: dict) -> dict:
    """Quellpaket einmal beim Bauen zu einem Wheel machen; es wird dem Installer beigelegt,
    damit die Ersteinrichtung nichts kompilieren muss. Nur reine Python-Pakete."""
    src = Path(tempfile.mkdtemp()) / sdist["url"].rsplit("/", 1)[-1]
    urllib.request.urlretrieve(sdist["url"], src)
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(BUNDLE_DIR), str(src)],
                   check=True, capture_output=True)
    wheel = next(BUNDLE_DIR.glob(f"{name.replace('-', '_')}-*.whl"))
    if not wheel.name.endswith("-py3-none-any.whl") and "-none-any" not in wheel.name:
        sys.exit(f"{name} ist kein reines Python-Paket, kann nicht beigelegt werden")
    return {"kind": "bundled", "label": name, "path": f"wheels/{wheel.name}", "bundled": f"bundled/{wheel.name}",
            "url": None, "sha256": None, "size": wheel.stat().st_size}


def wheels(target: dict) -> list[dict]:
    env = {"python_version": "3.12", "python_full_version": "3.12.14", "implementation_name": "cpython",
           "platform_python_implementation": "CPython", **target["env"]}
    supported = list(tags.cpython_tags(PY, platforms=target["platforms"])) + \
        list(tags.compatible_tags(PY, interpreter="cp312", platforms=target["platforms"]))
    rank = {t: i for i, t in enumerate(supported)}

    exported = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--no-header", "--no-annotate", "--no-emit-project",
         "--format", "requirements-txt"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    wanted = {}
    for line in exported.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        req, _, marker = line.partition(";")
        name, _, version = req.strip().partition("==")
        if not marker.strip() or Marker(marker.strip()).evaluate(env):
            wanted[canonicalize_name(name)] = version.strip()

    lock = tomllib.loads((ROOT / "uv.lock").read_text("utf-8"))
    out = []
    for pkg in lock["package"]:
        name = canonicalize_name(pkg["name"])
        if wanted.get(name) != pkg["version"]:
            continue
        best = None
        for w in pkg.get("wheels", []):
            filename = w["url"].rsplit("/", 1)[-1].replace("%2B", "+")
            r = min((rank[t] for t in parse_wheel_filename(filename)[3] if t in rank), default=None)
            if r is not None and (best is None or r < best[0]):
                best = (r, w, filename)
        if best is None:
            if "sdist" not in pkg:
                sys.exit(f"Kein passendes Wheel für {name} {pkg['version']}")
            out.append(build_bundled(name, pkg["sdist"]))  # nur als Quellpaket verfügbar
            del wanted[name]
            continue
        _, w, filename = best
        out.append({"kind": "wheel", "label": name, "path": f"wheels/{filename}", "url": w["url"],
                    "sha256": w["hash"].removeprefix("sha256:"), "size": w.get("size") or head_size(w["url"])})
        del wanted[name]
    if wanted:
        sys.exit(f"Nicht im Lockfile gefunden: {wanted}")
    return out


def model_files() -> list[dict]:
    out = []
    for name, (repo, rev, _) in MODELS.items():
        with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}/revision/{rev}?blobs=true", timeout=60) as r:
            info = json.load(r)
        folder = f"hub/models--{repo.replace('/', '--')}/snapshots/{rev}"
        for s in info["siblings"]:
            f = s["rfilename"]
            out.append({"kind": "model", "label": f"KI-Modell {name}", "path": f"{folder}/{f}",
                        "url": f"https://huggingface.co/{repo}/resolve/{rev}/{f}",
                        "sha256": (s.get("lfs") or {}).get("sha256"), "size": s["size"]})
    return out


def main():
    global BUNDLE_DIR
    target, dest = sys.argv[1], Path(sys.argv[2]).resolve()
    BUNDLE_DIR = dest.parent / "bundled"  # beigelegte Wheels liegen neben der Download-Liste
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    files = wheels(TARGETS[target]) + model_files()
    total = sum(f["size"] for f in files if f["kind"] != "bundled")
    dest.write_text(json.dumps({"platform": target, "total": total, "files": files}, indent=1), "utf-8")
    print(f"Download-Liste {target}: {len(files)} Dateien, {total / 1e9:.2f} GB -> {dest}")


if __name__ == "__main__":
    main()
