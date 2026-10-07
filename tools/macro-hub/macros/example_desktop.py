# -*- coding: utf-8 -*-
META = {
    "name": "예제 · 계산기 조작",
    "desc": "계산기를 새로 띄워 두 수를 더하고 결과를 읽은 뒤 닫는다. 마우스·키보드를 쓰지 않는다(UIA invoke).",
    "kind": "ctx",
    "target": "desktop",
    "no_mouse": True,          # 마우스·키보드가 필요한 순간이 오면 몰래 쓰지 않고 오류로 멈춘다
    "params": {"a": "12", "b": "30"},
    "triggers": [],
    "timeout": 60,
}


def run(ctx):
    before = ctx.window_handles()             # 열려 있던 창은 건드리지 않도록 미리 기억해 둔다
    ctx.start("calc.exe")
    win = ctx.window(r"(계산기|Calculator)", timeout=20, exclude=before)
    ctx.log("찾은 창:", win.window_text())

    def press(auto_id):
        ctx.click(win.child_window(auto_id=auto_id, control_type="Button"))

    press("clearButton")
    for ch in str(ctx.params.get("a", "")):
        press("num%sButton" % ch)
    press("plusButton")
    for ch in str(ctx.params.get("b", "")):
        press("num%sButton" % ch)
    press("equalButton")
    ctx.log("결과:", win.child_window(auto_id="CalculatorResults").window_text())
    win.close()
