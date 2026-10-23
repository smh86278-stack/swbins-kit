# -*- coding: utf-8 -*-
"""📚 갤러리 견본 — 웹 페이지 바뀜 알림. 지난번 글자는 이 자동화 전용 폴더(ctx.data_dir)의 last.txt 에 둔다."""
import os

META = {
    "name": "웹 페이지 바뀜 알림",
    "icon": "🔔",
    "desc": "웹 페이지의 한 부분(공지 첫 글·가격·상태 글자) 이 지난번과 달라지면 알린다.",
    "steps": ["페이지 열기 (화면 없이)", "고른 부분의 글자 읽기 (selector)", "지난번과 다르면 알림 (mail 칸이 yes 면 메일로도)"],
    "kind": "ctx",
    "target": "web",
    "motion": "search",
    "headless": True,
    "params": {"url": "https://example.com", "selector": "h1", "mail": "no"},
    "hint": "url 과 selector(예: h1 · .notice li · #price — 모르면 「말로 부탁하기」에 페이지 주소와 함께 물어보세요)를 넣고 「자동 실행」을 켜면 30분마다 봐요",
    "triggers": [{"type": "schedule", "every": "30m"}],
    "timeout": 120,
}

YES = ("yes", "y", "1", "true", "on", "예", "네")


def run(ctx):
    page = ctx.page
    url = ctx.param("url")
    page.goto(url)
    now = " ".join(page.locator(ctx.param("selector") or "body").first.inner_text().split())[:500]
    ctx.log("지금:", now[:120])
    f = os.path.join(ctx.data_dir, "last.txt")
    try:
        with open(f, encoding="utf-8") as fh:
            before = fh.read()
    except OSError:
        before = None
    if before is None:
        ctx.log("처음 봤습니다 — 다음부터 바뀌면 알려요")
    elif before != now:
        ctx.notify("🔔 페이지가 바뀌었어요", now[:120])
        if ctx.param("mail").strip().lower() in YES and ctx.for_real("바뀜 알림 메일 보내기"):
            import kit
            kit.alert("🔔 페이지가 바뀌었어요", "%s\n\n전: %s\n지금: %s" % (url, before[:300], now[:300]))
    else:
        ctx.log("그대로입니다")
    if ctx.for_real("지금 글자 기억하기"):
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(now)
