#!/bin/sh
# 맥 — 자동화가 쓰는 .venv 를 만든다(Playwright). 허브 자체는 표준 라이브러리만 쓴다.
# 웹 자동화는 설치된 Google Chrome 을 쓴다(브라우저를 따로 받지 않는다).
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "python3 이 없습니다 — https://www.python.org 에서 설치한 뒤 다시 실행하세요"; exit 1; }
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
echo
echo "끝났습니다. start.command 를 더블클릭하면 허브가 열립니다."
