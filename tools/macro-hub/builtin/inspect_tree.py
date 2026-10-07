# -*- coding: utf-8 -*-
META = {"name": "창·컨트롤 구조 보기", "kind": "ctx", "hidden": True}


def run(ctx):
    """params.title 이 비어 있으면 열린 창 목록을, 있으면 그 창의 컨트롤 트리를 출력한다."""
    from pywinauto import Desktop

    title = (ctx.params.get('title') or '').strip()
    wins = [w for w in Desktop(backend='uia').windows() if (w.window_text() or '').strip()]
    if not title:
        ctx.log('열린 창 %d개 — 제목(일부)을 입력하면 구조를 봅니다.' % len(wins))
        for w in wins:
            ctx.log('  %-40s [%s]' % (w.window_text()[:40], w.element_info.class_name))
        return
    ctx_win = ctx.window(title, timeout=5)
    ctx.log('창: %s\n' % ctx_win.window_text())
    ctx_win.print_control_identifiers()
