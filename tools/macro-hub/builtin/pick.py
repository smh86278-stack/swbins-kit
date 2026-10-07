# -*- coding: utf-8 -*-
META = {"name": "요소 찍기", "kind": "ctx", "hidden": True}


def run(ctx):
    """3초 뒤 마우스 아래에 있는 컨트롤을 읽어, 매크로에 붙여 넣을 코드를 만든다."""
    import ctypes
    from ctypes import wintypes
    from pywinauto import Desktop

    ctx.log('3초 뒤 마우스 아래의 컨트롤을 읽습니다. 찍을 곳에 마우스를 올려 두세요.')
    for n in (3, 2, 1):
        ctx.log('  %d…' % n)
        ctx.sleep(1)
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    el = Desktop(backend='uia').from_point(pt.x, pt.y)
    info = el.element_info
    top = el.top_level_parent()
    ctx.log('좌표 (%d, %d)' % (pt.x, pt.y))
    ctx.log('창     : %s' % top.window_text())
    ctx.log('종류   : %s' % info.control_type)
    ctx.log('이름   : %s' % info.name)
    ctx.log('auto_id: %s' % info.automation_id)
    ctx.log('클래스 : %s' % info.class_name)
    ctx.log('')
    ctx.log('# 매크로에 붙여 넣기')
    import re
    ctx.log("win = ctx.window(r'%s')" % re.escape(top.window_text()).replace("'", "\\'"))
    crit = []
    if info.automation_id:
        crit.append("auto_id='%s'" % info.automation_id)
    if info.name:
        crit.append("title='%s'" % info.name.replace("'", "\\'"))
    crit.append("control_type='%s'" % info.control_type)
    ctx.log("ctrl = win.child_window(%s)" % ', '.join(crit))
    ctx.log("ctrl.click_input()   # 또는 ctrl.type_keys('...') · ctrl.set_text('...')")
