@echo off
rem Start the desktop pet. It connects to the hub at 127.0.0.1:8610, so the hub (tray app) must be running.
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0"
