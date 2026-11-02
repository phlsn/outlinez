"""Lokaler Server für die Oberfläche: uv run server.py  ->  http://127.0.0.1:7860"""

import argparse
import io
import os
import secrets
import subprocess
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from PIL import Image

import export
from jobs import Manager
from paths import IS_MAC

STATIC = Path(__file__).parent / "static"
TOKEN = secrets.token_urlsafe(24)

app = FastAPI(title="Outlinez", docs_url=None, redoc_url=None)
manager = Manager()


def check_token(x_token: str = Header(""), token: str = ""):
    # Fremde Webseiten können die Seite nicht auslesen und kennen den Schlüssel daher nicht.
    if not secrets.compare_digest(x_token or token, TOKEN):
        raise HTTPException(403, "Ungültiger Zugriff")


def job_or_404(job_id: int):
    if job_id not in manager.jobs:
        raise HTTPException(404, "Bild nicht gefunden")
    return job_id


@app.get("/", response_class=HTMLResponse)
def index():
    html = (STATIC / "index.html").read_text("utf-8")
    return html.replace("__TOKEN__", TOKEN)


@app.get("/icon.png")
def icon():
    return FileResponse(STATIC / "icon.png", headers={"Cache-Control": "max-age=86400"})


api = Depends(check_token)


@app.get("/api/state", dependencies=[api])
def state():
    return manager.state()


@app.put("/api/settings", dependencies=[api])
async def settings(request: Request):
    return manager.update_settings(await request.json())


@app.post("/api/upload", dependencies=[api])
def upload(files: list[UploadFile] = File(...)):
    return [manager.add_upload(f.filename, f.file.read()).id for f in files]


@app.post("/api/add_paths", dependencies=[api])
async def add_paths(request: Request):
    body = await request.json()
    return [j.id for j in manager.add_paths(body.get("paths", []))]


def _image_response(img: Image.Image, max_size: int) -> Response:
    img = img.copy()
    img.thumbnail((max_size, max_size), Image.BILINEAR)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/original/{job_id}", dependencies=[api])
def original(job_id: int = Depends(job_or_404), max: int = 800):
    return _image_response(manager.original(job_id), min(max, 4000))


@app.get("/api/preview/{job_id}", dependencies=[api])
def preview(job_id: int = Depends(job_or_404), max: int = 900):
    try:
        original, cutout = manager.images(job_id)
    except LookupError as e:
        raise HTTPException(409, str(e))
    data, media = export.preview(original, cutout, manager.options(), min(max, 4000))
    return Response(data, media_type=media, headers={"Cache-Control": "max-age=3600"})


@app.post("/api/save", dependencies=[api])
async def save(request: Request):
    body = await request.json()
    ids = body.get("ids") or [j.id for j in manager.jobs.values() if j.status == "done"]
    results = []
    for job_id in ids:
        try:
            results.append({"id": job_id, "path": manager.save(job_id)})
        except Exception as e:
            results.append({"id": job_id, "error": str(e)})
    return results


@app.get("/api/download/{job_id}", dependencies=[api])
def download(job_id: int = Depends(job_or_404)):
    job = manager.jobs[job_id]
    opt = manager.options()
    original, cutout = manager.images(job_id)
    filename = f"{Path(job.name).stem}-freigestellt.{opt.format}"
    media = {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg", "psd": "image/vnd.adobe.photoshop"}
    return Response(export.encode(original, cutout, opt), media_type=media[opt.format],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/redo/{job_id}", dependencies=[api])
def redo(job_id: int = Depends(job_or_404)):
    manager.redo(job_id)


@app.delete("/api/jobs/{job_id}", dependencies=[api])
def remove(job_id: int = Depends(job_or_404)):
    manager.remove(job_id)


@app.delete("/api/jobs", dependencies=[api])
def clear():
    manager.remove()


@app.post("/api/reveal", dependencies=[api])
async def reveal(request: Request):
    """Gespeicherte Datei im Explorer bzw. Finder zeigen."""
    path = Path((await request.json()).get("path", ""))
    if not path.exists():
        raise HTTPException(404, "Nicht gefunden")
    if IS_MAC:
        subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
    elif path.is_file():
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        os.startfile(path)


def start_background(port: int) -> uvicorn.Server:
    """Server und Modell-Laden im Hintergrund starten (für die native App)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=manager.load_model, daemon=True).start()
    manager.configure_watch()
    return server


def main():
    parser = argparse.ArgumentParser(description="Outlinez im Browser")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    threading.Thread(target=manager.load_model, daemon=True).start()
    manager.configure_watch()
    print(f"Outlinez läuft: {url}")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
