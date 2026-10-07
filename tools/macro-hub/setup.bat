@echo off
rem Create the private virtualenv used by macros (Playwright + pywinauto). The hub itself needs no packages.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
echo.
echo Done. Browser macros use the installed Google Chrome (no browser download).
pause
