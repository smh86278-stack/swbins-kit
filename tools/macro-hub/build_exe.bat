@echo off
rem Build MacroHub.exe (launcher + watchdog) and the app icon. Needs once: .venv\Scripts\python.exe -m pip install pyinstaller
"%~dp0.venv\Scripts\python.exe" "%~dp0build_exe.py"
pause
