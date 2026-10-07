# -*- coding: utf-8 -*-
META = {
    "name": "예제 · 웹 열기",
    "desc": "Chrome 으로 example.com 을 열어 제목을 읽는다. 웹 매크로의 뼈대.",
    "kind": "ctx",
    "target": "web",
    "params": {"url": "https://example.com"},
    "triggers": [],
    "timeout": 120,
}


def run(ctx):
    page = ctx.page
    page.goto(ctx.params.get("url") or "https://example.com")
    ctx.log("제목:", page.title())
    # 로그인이 필요한 사이트는 ctx.secret("키") 로 값을 읽는다 — 파일에 직접 적지 않는다.
    # page.fill("#id", ctx.secret("site_id")); page.click("text=로그인")
