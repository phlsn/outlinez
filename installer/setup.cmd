@echo off
rem Ersteinrichtung von Hand wiederholen (macht der Installer sonst selbst):
rem laedt Komponenten und KI-Modelle, setzt abgebrochene Downloads fort, installiert offline.
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0fetch.py" --manifest "%~dp0manifest.json" --hf-home "%~dp0models" ^
  --venv "%~dp0.venv" --uv "%~dp0bin\uv.exe" --work "%~dp0downloads" --compile "%~dp0."
