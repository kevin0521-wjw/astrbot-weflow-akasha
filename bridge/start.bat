@echo off
cd /d "%~dp0"
set "PYTHON=%~dp0venv\Scripts\python.exe"
"%PYTHON%" main.py
pause
