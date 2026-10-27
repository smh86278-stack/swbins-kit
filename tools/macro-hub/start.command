#!/bin/sh
# 맥 — 허브를 띄우고 브라우저로 연다. 이 창을 닫거나 Ctrl+C 로 끈다.
# 데스크톱 자동화·창 트리거·트레이·자동 시작은 윈도우 전용이다(README 「맥에서 쓰기」).
cd "$(dirname "$0")" || exit 1
[ -d .venv ] || sh ./setup.sh
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
echo "============================================"
echo " Taskhand  http://127.0.0.1:8630/"
echo " 끄기: 이 창을 닫거나 Ctrl+C"
echo "============================================"
exec "$PY" macrohub.py --port 8630 --open "$@"
