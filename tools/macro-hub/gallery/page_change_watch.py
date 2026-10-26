# -*- coding: utf-8 -*-
"""📚 갤러리 견본 — 웹 페이지 바뀜 알림. 지난번 글자는 이 자동화 전용 폴더(ctx.data_dir)의 last.txt 에 둔다."""
import os

META = {
    "name": "웹 페이지 바뀜 알림",
    "icon": "🔔",
    "desc": "웹 페이지의 한 부분(공지 첫 글·가격·상태 글자) 이 지난번과 달라지면 알린다.",
    "keywords": ["바뀌", "바뀜", "변경", "달라", "공지", "게시판", "가격", "새 글", "알려", "알림", "감시", "지켜"],  # 만들기 칸에 적은 말과 맞춰 비슷한 견본으로 띄운다(말 줄기 — 조사·어미가 붙어도 맞게)
    "steps": ["페이지 열기 (화면 없이)", "고른 부분의 글자 읽기 (selector)", "지난번과 다르면 알림 (mail 칸이 yes 면 메일로도)"],
    "kind": "ctx",
    "target": "web",
    "motion": "search",
    "headless": True,
    "params": {"url": "https://example.com", "selector": "p", "mail": "no"},
    "hint": "url 과 selector(예: p · h1 · .notice li · #price — 모르면 「말로 부탁하기」에 페이지 주소와 함께 물어보세요)를 넣고 「자동 실행」을 켜면 30분마다 봐요",
    "triggers": [{"type": "schedule", "every": "30m"}],
    "timeout": 120,
}

YES = ("yes", "y", "1", "true", "on", "예", "네")
FIND_SEC = 10        # 고른 부분을 기다리는 시간(초) — 없는 selector 로 30초씩 기다리다 시간 초과 대신 바로 알아듣는 말로


def run(ctx):
    page = ctx.page
    url = ctx.param("url")
    page.goto(url)
    sel = ctx.param("selector") or "body"
    part = page.locator(sel).first
    try:
        part.wait_for(state="attached", timeout=FIND_SEC * 1000)
    except Exception:
        raise RuntimeError("페이지에서 selector '%s' 에 맞는 부분을 찾지 못했습니다 (%d초) — 페이지가 바뀌었을 수 있어요. "
                           "selector 를 고치세요 (모르면 body)" % (sel, FIND_SEC))
    now = " ".join(part.inner_text().split())[:500]
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
