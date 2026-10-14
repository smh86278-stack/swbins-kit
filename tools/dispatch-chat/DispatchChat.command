#!/bin/sh
# 맥에서 더블클릭하면 디스패치 대화 앱을 띄운다(파이썬 3.9 이상 — 맥에 기본으로 있는 python3 로 된다)
cd "$(dirname "$0")" && exec python3 chat.py "$@"
