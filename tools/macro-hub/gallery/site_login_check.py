# -*- coding: utf-8 -*-
"""📚 갤러리 견본 — 사이트 로그인 후 확인. 계정은 파일에 쓰지 않고 secrets.local.json 의 site_id · site_pw 로."""

META = {
    "name": "사이트 로그인 후 확인",
    "icon": "🔐",
    "desc": "사이트에 로그인해서 로그인 뒤에만 보이는 글자(예: 로그아웃)가 보이는지 확인한다. 안 보이면 실패 — 그 순간 화면이 남는다.",
    "steps": ["로그인 화면 열기", "이미 로그인돼 있으면 건너뜀", "아이디·비밀번호 넣고 로그인 누르기", "확인 글자가 보이는지 보기"],
    "kind": "ctx",
    "target": "web",
    "motion": "web",
    "params": {"login_url": "https://example.com/login", "id_label": "아이디", "pw_label": "비밀번호",
               "button": "로그인", "expect_text": "로그아웃"},
    "secrets": ["site_id", "site_pw"],
    "hint": "login_url 과 칸 이름표(id_label·pw_label — 화면에 보이는 글자)를 그 사이트에 맞게 바꾸고, secrets.local.json 에 site_id · site_pw 를 넣으세요",
    "triggers": [],
    "web_timeout": 20,
    "timeout": 180,
}


def run(ctx):
    page = ctx.page
    expect = ctx.param("expect_text").strip()
    page.goto(ctx.param("login_url"))
    if expect and page.get_by_text(expect).first.is_visible():
        ctx.log("이미 로그인돼 있습니다 — 「%s」 보임" % expect)
        return
    page.get_by_label(ctx.param("id_label")).first.fill(ctx.secret("site_id"))
    page.get_by_label(ctx.param("pw_label")).first.fill(ctx.secret("site_pw"))
    page.get_by_role("button", name=ctx.param("button")).first.click()
    page.wait_for_load_state()
    if expect:
        try:
            page.get_by_text(expect).first.wait_for(state="visible")
        except Exception:
            raise RuntimeError("로그인 뒤 「%s」 글자가 안 보입니다 — 비밀번호가 바뀌었거나 화면이 바뀌었을 수 있습니다" % expect)
    ctx.log("로그인 확인 — %s" % page.title())
