@echo off
rem Start the tray app (no console window). If it is already running, this just opens the web page.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
