# -*- coding: utf-8 -*-
"""맥 메뉴 막대 아이콘 — 윈도우 트레이(app.py)의 맥 판, 꼭 필요한 것만.

    .venv/bin/python3 mac_menubar.py           (mac_launch.py 가 허브를 띄운 뒤 같이 띄운다)
    .venv/bin/python3 mac_menubar.py --check   (CI 시험 — 화면 없이 아이콘·메뉴만 만들어 보고 끝)

메뉴: 허브 상태 · Taskhand 열기 · 운영 화면 · 로그인 때 자동 시작(켜고 끄기) · 허브 다시 띄우기 · 끄기(허브와 메뉴 막대).
허브 띄우기·끄기·자동 시작은 mac_launch.py 의 것을 그대로 쓴다. pystray 맥 백엔드(pyobjc)는 주 스레드에서만 돈다.
"""
import os
import subprocess
import sys

import mac_launch as ML

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, 'web', 'app.ico')


def status_text(_item=None):
    return '허브: 도는 중' if ML.port_open() else '허브: 꺼짐'


def open_url(path=''):
    subprocess.run(['open', ML.url() + path])


def restart_hub():
    ML.stop_hub()
    with open(os.path.join(ML.LOGS, 'hub.log'), 'ab') as log:
        ok = ML.start_hub(log)
    ML.notify('허브를 다시 띄웠습니다' if ok else '허브를 띄우지 못했습니다 — 기록: ~/Library/Logs/Taskhand/hub.log')


def toggle_autostart():
    on = ML.set_autostart(not ML.autostart_enabled())
    ML.notify('로그인 때 자동으로 켜집니다' if on else '로그인 때 자동 시작을 껐습니다')


def menu_spec():
    """(글자 또는 글자 함수, 할 일, 체크 함수, 기본 항목) — pystray 없이도 시험할 수 있게 목록으로 둔다. None 은 구분선."""
    return [
        (status_text, None, None, False),
        None,
        ('Taskhand 열기', open_url, None, True),
        ('운영 화면', lambda: open_url('ops'), None, False),
        None,
        ('로그인 때 자동 시작', toggle_autostart, lambda: ML.autostart_enabled(), False),
        ('허브 다시 띄우기', restart_hub, None, False),
        None,
        ('끄기 (허브와 메뉴 막대)', 'quit', None, False),
    ]


def build(pystray):
    from PIL import Image
    image = Image.open(ICON).convert('RGBA').resize((64, 64))

    def quit_all(icon, _item):
        ML.stop_hub()
        ML.stop_menubar()
        icon.stop()

    def runner(f):                                    # pystray 는 인자 수(0~2)를 본다 — 기본값 인자를 두지 않고 감싼다
        return lambda _icon, _item: f()

    def item(spec):
        if spec is None:
            return pystray.Menu.SEPARATOR
        text, action, checked, default = spec
        if action is None:
            return pystray.MenuItem(text, None, enabled=False)
        act = quit_all if action == 'quit' else runner(action)
        kw = {'checked': (lambda f: lambda _item: f())(checked)} if checked else {}   # 체크 표시는 인자가 메뉴 항목 하나
        return pystray.MenuItem(text, act, default=default, **kw)

    icon = pystray.Icon('Taskhand', image, 'Taskhand')
    icon.menu = pystray.Menu(*[item(s) for s in menu_spec()])
    return icon


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    import pystray
    icon = build(pystray)
    if '--check' in argv:
        print('메뉴 막대 준비 됨 —', len([s for s in menu_spec() if s]), '항목')
        return 0
    with open(ML.MENU_PIDFILE, 'w') as f:                   # 직접 띄웠을 때도 mac_launch 가 찾게
        f.write(str(os.getpid()))
    icon.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
