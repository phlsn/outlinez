@echo off
rem Ersteinrichtung der installierten App: Abhaengigkeiten und KI-Modelle in den App-Ordner laden.
rem Wird vom Installer aufgerufen und kann bei Problemen auch von Hand erneut ausgefuehrt werden.
setlocal
cd /d "%~dp0"
rem Python liegt dem Setup bei; uv soll keins herunterladen
set "UV_PYTHON=%~dp0python\python.exe"
set "UV_PYTHON_DOWNLOADS=never"
set "UV_CACHE_DIR=%~dp0.uv-cache"
set "HF_HUB_DISABLE_PROGRESS_BARS=1"

echo Lade Komponenten (ca. 3 GB) ...
"%~dp0bin\uv.exe" sync --frozen --no-progress || exit /b 1
"%~dp0bin\uv.exe" cache clean >nul 2>&1

echo Lade KI-Modelle (ca. 1,8 GB) ...
"%~dp0.venv\Scripts\python.exe" setup_models.py || exit /b 2
echo Fertig.
