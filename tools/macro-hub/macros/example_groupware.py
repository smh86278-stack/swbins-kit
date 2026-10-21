# -*- coding: utf-8 -*-
META = {
    "name": "예제 · 그룹웨어 새 글 확인",
    "desc": "사내 그룹웨어·인트라넷의 공지 게시판이나 결재 대기 목록을 열어, 지난번에 없던 줄이 생기면 알린다. "
            "복사해서 주소·목록 줄만 바꿔 쓰는 견본.",
    "steps": ["목록 화면 열기 (로그인 화면이면 secret 의 아이디·비밀번호로 로그인)",
              "목록 줄 읽기", "지난번에 없던 줄이 있으면 알림"],
    "kind": "ctx",
    "target": "web",
    "headless": True,                       # 처음 로그인이 막히면(보안 문자 등) False 로 바꿔 한 번 손으로 로그인 — 로그인은 프로필에 남는다
    "params": {
        "url": "https://groupware.example.com/board/notice",   # 공지 게시판 또는 결재 대기 목록 주소
        "rows": "table tbody tr",           # 목록 한 줄을 가리키는 CSS — 사이트마다 다르다(요소 찍기·개발자 도구로 확인)
        "max_rows": "20",
        "id_key": "groupware_id",           # secrets.local.json 의 키 이름
        "pw_key": "groupware_pw",
    },
    "triggers": [],                         # 예: [{"type": "schedule", "every": "30m"}] — 켜는 건 허브에서
    "timeout": 180,
}

import json
import os


def login_if_needed(ctx, page):
    """비밀번호 칸이 보이면 로그인 화면으로 보고 아이디·비밀번호를 넣는다."""
    pw = page.locator('input[type=password]')
    if not pw.count() or not pw.first.is_visible():
        return False
    ctx.log("로그인 화면 — secret 의 아이디·비밀번호로 로그인합니다")
    user = page.locator('input[type=text]:visible, input[type=email]:visible, input:not([type]):visible').first
    user.fill(ctx.secret(ctx.params["id_key"]))
    pw.first.fill(ctx.secret(ctx.params["pw_key"]))
    pw.first.press("Enter")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    return True


def run(ctx):
    page = ctx.page
    url = ctx.params["url"]
    page.goto(url)
    if login_if_needed(ctx, page):
        page.goto(url)                      # 로그인 뒤 첫 화면(홈)으로 가는 사이트가 많다
    page.wait_for_timeout(1500)
    rows = page.locator(ctx.params["rows"])
    n = min(rows.count(), int(ctx.params.get("max_rows") or 20))
    if not n:
        raise RuntimeError("목록 줄을 못 찾았습니다 — 'rows'(%s) 가 이 화면에 맞는지 확인하세요. 지금 화면: %s"
                           % (ctx.params["rows"], page.title()))
    now = [" ".join(rows.nth(i).inner_text().split())[:200] for i in range(n)]
    ctx.log("목록 %d줄 읽음" % n)

    state = os.path.join(ctx.data_dir, "seen.json")
    try:
        with open(state, encoding="utf-8") as f:
            seen = set(json.load(f))
    except (OSError, ValueError):
        seen = None                         # 처음 — 지금 목록을 기준으로 삼고 알리지 않는다
    new = [r for r in now if seen is not None and r not in seen]
    for r in new:
        ctx.log("새 줄:", r)
    if new:
        ctx.notify("새 글 %d개" % len(new), new[0] + (" 외 %d개" % (len(new) - 1) if len(new) > 1 else ""))
    elif seen is None:
        ctx.log("처음 실행 — 지금 목록을 기억해 두었습니다. 다음부터 새 줄만 알립니다")
    else:
        ctx.log("새 줄 없음")
    keep = now + [r for r in (seen or ()) if r not in now]     # 지금 목록을 앞에 — 오래된 것부터 500줄 넘게는 버린다
    with open(state, "w", encoding="utf-8") as f:
        json.dump(keep[:500], f, ensure_ascii=False)
