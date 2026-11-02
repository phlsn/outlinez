@echo off
title Outlinez
cd /d "%~dp0"
uv run server.py %*
if errorlevel 1 pause
