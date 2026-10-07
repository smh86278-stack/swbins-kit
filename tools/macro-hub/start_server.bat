@echo off
echo ============================================
echo  Macro hub  http://127.0.0.1:8630/
echo  Stop: close this window or press Ctrl+C
echo ============================================
cd /d "%~dp0"
python macrohub.py --port 8630 %*
