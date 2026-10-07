# -*- coding: utf-8 -*-
"""매크로 허브 트레이 앱 — 실행하면 트레이에 상주하며 허브(웹 화면·트리거·상시 매크로)를 돌린다.

    pythonw app.py                  트레이 앱 시작 (이미 떠 있으면 웹 화면만 연다)
    python app.py --install-autostart   로그온 시 자동 시작 등록 (HKCU Run — 관리자 권한 불필요)
    python app.py --remove-autostart    등록 해제
    python app.py --quiet           시작 알림 풍선 없이 (자동 시작용)

트레이 아이콘: 초록=켜 둔 상시 매크로가 모두 동작 중 · 노랑=멈췄거나 일시정지/재시작 중 · 회색=켜 둔 게 없음
메뉴: 서버·도구 상태와 시작/재시작·일시정지·도구별 명령·로그(저장소 맨 위 services.json 이 있을 때만 — 없어도 된다),
예약 작업, 🔗 바로가기(config.local.json 의 "links"). 서버·워처는 작업 스케줄러 대신 허브가 띄우고 지킨다(macros\svc_*.py, extsvc.py).
  얼굴은 허브 화면에서 고른 스킨(모습)의 강아지 역할 캐릭터를 따른다. 스킨이 없으면 직접 그린 강아지.
왼쪽 클릭/더블클릭 = 웹 화면 열기, 우클릭 = 메뉴(상시 매크로 켜기/끄기, 재개, 자동 시작, 종료).
알림 풍선: 매크로가 ctx.notify() 를 부르거나, 자동 실행된 매크로가 실패하거나, 상시 매크로가 죽었을 때.
"""
import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PORT = 8630
URL = 'http://127.0.0.1:%d/' % PORT
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'WorkKit'
def _pick_python(exe):
    """허브용 파이썬 — 개발 PC 는 .venv, 설치본(WorkKitSetup.exe)은 저장소 맨 위 runtime\\ 에 든 내장 파이썬."""
    for cand in (os.path.join(HERE, '.venv', 'Scripts', exe), os.path.join(HERE, '..', '..', 'runtime', exe)):
        if os.path.isfile(cand):
            return os.path.normpath(cand)
    return os.path.join(HERE, '.venv', 'Scripts', exe)


PYTHONW = _pick_python('pythonw.exe')
LOG = os.path.join(HERE, 'data.local', 'app.log')


def message_box(text, title='매크로 허브'):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def _redirect_std():
    """pythonw 에는 표준출력이 없다 — 파일로 돌려 둬야 print/예외가 사라지지 않는다."""
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        f = open(LOG, 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


_redirect_std()

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    message_box('pystray / Pillow 가 없습니다. setup.bat 을 먼저 실행하세요.')
    sys.exit(1)

import extsvc  # noqa: E402
import kit  # noqa: E402
import macrohub as hub  # noqa: E402
import skinicon  # noqa: E402

SERVICES_JSON = os.path.join(extsvc.ROOT, 'services.json')


def log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write('%s  %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg))
    except OSError:
        pass


# ---------------------------------------------------------------- 로그온 시 자동 시작

def autostart_command():
    """로그온 자동 시작 — WorkKit.exe(감시자: 트레이 앱이 죽으면 다시 띄운다)가 있으면 그것, 없으면 launcher.py."""
    if os.path.isfile(os.path.join(HERE, 'WorkKit.exe')):
        return '"%s" --background' % os.path.join(HERE, 'WorkKit.exe')
    return '"%s" "%s" --background' % (PYTHONW, os.path.join(HERE, 'launcher.py'))


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_NAME)[0] == autostart_command()
    except OSError:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------- 단일 인스턴스 · 남은 러너 정리

def already_running():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\workkit-app')
    already_running.handle = mutex            # 프로세스가 끝날 때까지 쥐고 있는다
    return ctypes.windll.kernel32.GetLastError() == 183


def kill_orphan_runners():
    """이전 허브가 비정상 종료돼 남은 이 폴더의 runner.py 를 정리한다 — 안 그러면 같은 매크로가 둘 떠서 서로 방해한다."""
    me = os.getpid()
    for pid, (_ppid, name) in hub.pl.snapshot().items():
        if pid == me or name.lower() not in ('python.exe', 'pythonw.exe'):
            continue
        cmd = hub.pl.command_line(pid)
        if cmd and 'runner.py' in cmd and HERE.lower() in cmd.lower():
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=hub.NO_WINDOW)
            log('남은 러너 정리: pid %d' % pid)


# ---------------------------------------------------------------- 상태 · 아이콘

COLORS = {'ok': (46, 196, 138), 'warn': (255, 166, 77), 'idle': (176, 166, 214)}   # 민트 · 피치 · 라일락(허브 화면 theme.css 와 같은 결)
BADGE, BADGE_LINE = (241, 236, 255, 255), (138, 114, 238, 255)                      # 파스텔 원 배경 · 테두리


def make_icon(kind):
    """스킨 얼굴(있으면) 또는 직접 그린 강아지 + 우하단 상태 점."""
    sid = hub.state.get('skin')
    if sid:
        face = skinicon.face_icon(os.path.join(hub.SKIN_DIR, sid), kind, 256)
        if face:
            img = face.copy()
            _status_dot(ImageDraw.Draw(img), kind)
            return img.resize((64, 64), Image.LANCZOS)
    return draw_dog_icon(kind)


def _status_dot(d, kind):
    d.ellipse((150, 150, 250, 250), fill=(255, 255, 255, 255), outline=BADGE_LINE, width=8)
    d.ellipse((168, 168, 232, 232), fill=COLORS[kind] + (255,))


def draw_dog_icon(kind, dot=True, size=64):
    """강아지 얼굴 + 우하단 상태 점. 표정이 상태를 말한다.
    ok=눈 뜨고 귀 쫑긋 · warn=귀가 처지고 땀 · idle=눈 감고 Z.
    트레이는 16~32px 로 줄어 보이므로 4배 큰 캔버스에 그린 뒤 줄여 부드럽게 만든다."""
    S = 256
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    black, ink, white = (37, 39, 44, 255), (22, 22, 25, 255), (250, 247, 242, 255)

    # 파스텔 원 배지 — 어두운·밝은 작업 표시줄 어디서나 강아지가 보이게
    d.ellipse((4, 4, S - 5, S - 5), fill=BADGE, outline=BADGE_LINE, width=10)

    # 귀 (뒤) — 상태에 따라 모양이 다르다
    if kind == 'warn':      # 처짐
        left = [(60, 70), (14, 118), (18, 196), (66, 168), (86, 100)]
    elif kind == 'idle':    # 느슨
        left = [(58, 64), (20, 108), (24, 180), (68, 158), (84, 96)]
    else:                   # 쫑긋
        left = [(50, 92), (30, 20), (112, 58), (96, 104)]
    right = [(S - x, y) for x, y in left]
    d.polygon(left, fill=ink)
    d.polygon(right, fill=ink)

    # 머리 · 흰 줄무늬 · 주둥이
    d.ellipse((38, 52, 218, 232), fill=black)
    d.polygon([(116, 54), (140, 54), (156, 138), (100, 138)], fill=white)
    d.ellipse((118, 50, 138, 72), fill=white)
    d.ellipse((74, 134, 182, 224), fill=white)

    # 눈
    for cx in (92, 164):
        if kind == 'idle':
            d.arc((cx - 20, 98, cx + 20, 138), 15, 165, fill=(245, 238, 228, 255), width=9)
        else:
            d.ellipse((cx - 19, 96, cx + 19, 140), fill=white)
            dy = 6 if kind == 'warn' else 0
            d.ellipse((cx - 13, 102 + dy, cx + 13, 134 + dy), fill=(122, 74, 34, 255))
            d.ellipse((cx - 8, 110 + dy, cx + 8, 128 + dy), fill=(13, 13, 16, 255))
            d.ellipse((cx - 9, 106 + dy, cx - 2, 113 + dy), fill=white)
    # 주황 눈썹 점
    for cx in (90, 166):
        d.ellipse((cx - 10, 70, cx + 10, 82), fill=(185, 115, 58, 255))

    # 볼터치
    for cx in (66, 190):
        d.ellipse((cx - 17, 160, cx + 17, 182), fill=(255, 158, 196, 230))

    # 코 · 입
    d.ellipse((108, 152, 148, 180), fill=ink)
    d.ellipse((116, 156, 132, 164), fill=(255, 255, 255, 120))
    d.line([(128, 180), (128, 196)], fill=ink, width=7)
    d.arc((100, 186, 130, 214), 10, 170, fill=ink, width=7)
    d.arc((126, 186, 156, 214), 10, 170, fill=ink, width=7)

    if kind == 'warn':      # 땀방울
        d.polygon([(206, 40), (186, 84), (226, 84)], fill=(121, 196, 255, 255))
        d.ellipse((186, 66, 226, 106), fill=(121, 196, 255, 255))
    if kind == 'idle':      # Z
        d.line([(188, 28), (226, 28), (188, 64), (226, 64)], fill=(138, 160, 255, 255), width=11, joint='curve')

    if dot:
        _status_dot(d, kind)           # 상태 점 (우하단)
    return img.resize((size, size), Image.LANCZOS)


def data_dir(macro_id):
    return os.path.join(HERE, 'data.local', re.sub(r'[^\w\-]+', '_', macro_id))


def paused_flag(m):
    return os.path.join(data_dir(m['id']), 'paused.flag')


def services():
    return [m for m in hub.discover() if m['service']]


def compute_state():
    enabled = [m for m in services() if hub.state['enabled'].get(m['id'])]
    if not enabled:
        return 'idle', '켜 둔 상시 매크로 없음'
    paused = [m for m in enabled if os.path.exists(paused_flag(m))]
    down = [m for m in enabled if not hub.running_run(m['id'])]
    if down:
        return 'warn', '시작 중/멈춤: ' + ', '.join(m['name'] for m in down)
    if paused:
        return 'warn', '일시정지: ' + ', '.join(m['name'] for m in paused)
    return 'ok', '상시 %d개 동작 중' % len(enabled)


# ---------------------------------------------------------------- 메뉴

ELECTRON = os.path.join(HERE, 'pet', 'node_modules', 'electron', 'dist', 'electron.exe')
SHELL_DIR = os.path.join(HERE, 'shell')
EXE = os.path.join(HERE, 'WorkKit.exe')


def open_window(page='/'):
    """허브 전용 창(shell\, Electron)으로 연다. 이미 열려 있으면 그 창이 앞으로 나온다. Electron 이 없으면 브라우저로."""
    if os.path.isfile(ELECTRON) and os.path.isdir(SHELL_DIR):
        subprocess.Popen([ELECTRON, SHELL_DIR, '--page=' + page], cwd=SHELL_DIR, creationflags=0x00000008 | 0x00000200,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(URL.rstrip('/') + page)


def close_window():
    key = SHELL_DIR.lower()
    for pid, (_ppid, name) in hub.pl.snapshot().items():
        if name.lower() == 'electron.exe' and key in (hub.pl.command_line(pid) or '').lower():
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=hub.NO_WINDOW)


def open_ui(icon=None, item=None):
    open_window('/')


# ---------------------------------------------------------------- 서버·도구 (services.json — 선택)

def tools_config():
    """저장소 맨 위 services.json(선택) — 없거나 깨졌으면 빈 목록. 서버·도구 메뉴는 그때 안 보인다."""
    try:
        with open(SERVICES_JSON, encoding='utf-8-sig') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    pick = lambda k: [x for x in (cfg.get(k) or []) if isinstance(x, dict)] if isinstance(cfg.get(k), list) else []
    return {'services': pick('services'), 'watchers': pick('watchers')}


def company_title(base='매크로 허브'):
    """트레이 이름 — 설정에 회사 이름이 있으면 '매크로 허브 · 회사'."""
    try:
        name = kit.company_name()
    except Exception:
        name = ''
    return '%s · %s' % (base, name) if name else base


def link_items():
    """🔗 바로가기 — config.local.json 의 "links": [{"label", "url"}]. 비었으면 메뉴를 숨긴다."""
    try:
        links = kit.section('links', []) or []
    except Exception:
        links = []
    for x in links if isinstance(links, list) else []:
        if not isinstance(x, dict):
            continue
        url = str(x.get('url') or '').strip()
        if url.startswith(('http://', 'https://')):
            yield pystray.MenuItem(str(x.get('label') or url)[:60], opener(url))


def _wpath(w, rel):
    if not rel:
        return None
    return rel if os.path.isabs(rel) else (os.path.join(w['dir'], rel) if w.get('dir') else None)


def watcher_status(w):
    """(표시, 일시정지 플래그 경로, 일시정지 여부). 도구가 30초마다 갱신하는 state 파일의 수정 시각으로 생존을 본다.
    state 파일이 없는 도구(허브 매크로 자체)는 허브 실행 상태로 본다."""
    pause = _wpath(w, w.get('pause_file'))
    paused = bool(pause and os.path.exists(pause))
    sf = _wpath(w, w.get('state_file'))
    if sf:
        st, alive = {}, False
        try:
            alive = time.time() - os.path.getmtime(sf) < 150
            st = extsvc.read_state(sf)
        except OSError:
            pass
        state = str(st.get('state', ''))
        if not alive:
            label = '⛔ 멈춤'
        elif paused:
            label = '⏸ 일시정지'
        elif state == 'waiting':
            label = '⚠ 설정 필요'
        elif state == 'error':
            label = '⚠ 오류'
        else:
            label = '✅ 동작 중'
    else:
        r = hub.running_run(w.get('hub', ''))
        label = '⏸ 일시정지' if paused else ('✅ 동작 중' if r else '⛔ 멈춤')
    return label, pause, paused


def _balloon(icon, title, text):
    try:
        icon.notify(str(text)[:250], str(title)[:60])
    except Exception as e:
        log('풍선 실패: %s' % e)


def hub_action(mid, action):
    def run(icon, item):
        ok, msg = hub.service_action(mid, action)
        _balloon(icon, '매크로 허브', msg)
        refresh(icon)
    return run


def show_status_command(w):
    """도구의 status_command(JSON {"lines": [...]} 를 내는 .ps1)를 숨겨서 돌리고 결과를 풍선으로."""
    def run(icon, item):
        def work():
            cmd = w['status_command']
            f = _wpath(w, cmd.get('file'))
            try:
                args = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', f]
                args += [a for a in str(cmd.get('args') or '').split() if a]
                out = subprocess.run(args, capture_output=True, timeout=60, creationflags=hub.NO_WINDOW).stdout
                lines = json.loads(out.decode('utf-8', 'replace') or '{}').get('lines') or ['표시할 내용이 없습니다.']
                _balloon(icon, w['name'], '[%s]\n' % watcher_status(w)[0] + '\n'.join(map(str, lines)))
            except Exception as e:
                _balloon(icon, w['name'], '상태 조회 실패: %s' % e)
        threading.Thread(target=work, daemon=True).start()
    return run


def run_tool_command(w, c):
    """도구별 명령(설정·진단 등) — 사용자와 대화하는 것이라 PowerShell 창을 띄운다."""
    def run(icon, item):
        args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass']
        if c.get('console'):
            args.append('-NoExit')
        args += ['-File', _wpath(w, c['file'])] + [a for a in str(c.get('args') or '').split() if a]
        subprocess.Popen(args, cwd=w.get('dir') or None, creationflags=0x00000010)     # CREATE_NEW_CONSOLE
    return run


def toggle_pause(path, name):
    def run(icon, item):
        try:
            if os.path.exists(path):
                os.remove(path)
                _balloon(icon, name, '다시 자동으로 동작합니다.')
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('manual')
                _balloon(icon, name, '멈췄습니다.')
        except OSError as e:
            _balloon(icon, name, '전환 실패: %s' % e)
        refresh(icon)
    return run


def opener(target, program=None):
    def run(icon, item):
        if program:
            subprocess.Popen([program, target])
        elif target.startswith('http'):
            webbrowser.open(target)
        else:
            os.startfile(target)
    return run


def start_plain(s):
    """허브 매크로가 없는 서버(services.json 에 start 만 있는 것)는 시작 배치를 허브와 떨어진 프로세스로 띄운다."""
    def run(icon, item):
        try:
            extsvc.launch(['cmd.exe', '/c', s['start']], cwd=s.get('dir'), log=os.path.join(extsvc.ROOT, 'logs', s['key'] + '.log'))
            _balloon(icon, s['name'], '시작했습니다.')
        except Exception as e:
            _balloon(icon, s['name'], '시작 실패: %s' % e)
    return run


def _enabled_item(mid, label='상시 실행 (허브가 지킴)'):
    m = hub.find_macro(mid)
    if not m:
        return pystray.MenuItem('(허브에 없는 매크로: %s)' % mid, None, enabled=False)
    return pystray.MenuItem(label, toggle_service(m), checked=lambda item, mid=mid: bool(hub.state['enabled'].get(mid)))


def server_items(cfg):
    for s in cfg['services']:
        if s.get('port') == hub_port():
            continue                                        # 매크로 허브 자신
        alive = extsvc.port_open(s['port'], timeout=0.2)
        sub, mid = [], s.get('hub')
        if alive:
            sub.append(pystray.MenuItem('브라우저로 열기', opener('http://localhost:%s/' % s['port'])))
        if mid:
            sub.append(pystray.MenuItem('재시작' if alive else '시작', hub_action(mid, 'restart')))
            sub.append(_enabled_item(mid))
        elif s.get('start') and not alive:
            sub.append(pystray.MenuItem('시작', start_plain(s)))
        if s.get('dir') and os.path.isdir(s['dir']):
            sub.append(pystray.MenuItem('폴더 열기', opener(s['dir'])))
        yield pystray.MenuItem('%s %s  (%s)' % ('✅' if alive else '⛔', s['name'], s['port']), pystray.Menu(*sub))


def watcher_items(cfg):
    for w in cfg['watchers']:
        label, pause, paused = watcher_status(w)
        sub, mid = [], w.get('hub')
        if (w.get('status_command') or {}).get('file'):
            sub.append(pystray.MenuItem(w['status_command'].get('label') or '상태 확인', show_status_command(w)))
        if pause:
            sub.append(pystray.MenuItem('재개 (다시 자동으로)' if paused else '일시정지', toggle_pause(pause, w['name'])))
        for c in w.get('commands') or []:
            if c.get('file') and os.path.exists(_wpath(w, c['file']) or ''):
                sub.append(pystray.MenuItem(str(c.get('label')), run_tool_command(w, c)))
        lf = _wpath(w, w.get('log_file'))
        if lf and os.path.exists(lf):
            sub.append(pystray.MenuItem('로그 열기', opener(lf, 'notepad.exe')))
        if mid:
            sub.append(pystray.MenuItem('지금 실행 (되살리기)' if label.startswith('⛔') else '다시 띄우기', hub_action(mid, 'restart')))
            sub.append(_enabled_item(mid))
        if w.get('dir') and os.path.isdir(w['dir']):
            sub.append(pystray.MenuItem('폴더 열기', opener(w['dir'])))
        yield pystray.MenuItem('%s  %s' % (w['name'], label), pystray.Menu(*sub))


def hub_port():
    return PORT


def _group(title, entries, problems=0):
    """하위 메뉴 묶음. 문제가 있으면 이름에 (⚠ n) — 접혀 있어도 이상이 보이게."""
    return pystray.MenuItem('%s%s' % (title, '  (⚠ %d)' % problems if problems else ''), pystray.Menu(*entries))


def build_menu():
    """맨 위에는 묶음만 둔다 — 서버·도구·예약·설정을 다 펼치면 20줄 가까이 된다."""
    def items():
        yield pystray.MenuItem('매크로 허브 열기', open_ui, default=True)
        yield pystray.MenuItem('⏰ 운영 화면 열기', lambda icon, item: open_window('/ops'))
        yield pystray.Menu.SEPARATOR
        cfg = tools_config()

        servers = list(server_items(cfg))
        down = sum(1 for s, it in zip([s for s in cfg['services'] if s.get('port') != PORT], servers)
                   if s.get('hub') and it.text.startswith('⛔'))       # 허브가 지키는 서버만 센다(나머지는 평소 꺼져 있을 수 있다)
        if servers:
            yield _group('🌐 서버', servers, down)

        tools = list(watcher_items(cfg))
        bad = sum(1 for it in tools if '⛔' in it.text or '⚠' in it.text)
        mapped = {x.get('hub') for x in cfg['services'] + cfg['watchers']}
        for m in (m for m in services() if m['id'] not in mapped):      # services.json 에 안 걸린 상시 매크로
            tools.append(pystray.MenuItem('상시: ' + m['name'], toggle_service(m),
                                          checked=lambda item, m=m: bool(hub.state['enabled'].get(m['id']))))
            if os.path.exists(paused_flag(m)):
                tools.append(pystray.MenuItem('   ▶ 일시정지 해제 (%s)' % m['name'], resume(m)))
        if tools:
            yield _group('🔧 도구', tools, bad)

        # 예약 작업(job_*·스케줄 트리거) — 켜기/끄기와 지금 실행. 마지막 실행이 실패면 묶음에 표시
        jobs = [m for m in hub.discover() if not m['service'] and any(t.get('type') == 'schedule' for t in m['triggers'])]
        if jobs:
            failed = sum(1 for m in jobs if (hub.macro_view(m).get('last') or {}).get('status') in ('fail', 'timeout'))
            yield _group('⏰ 예약 작업', [pystray.MenuItem(m['name'], pystray.Menu(
                _enabled_item(m['id'], '예약 켜기'),
                pystray.MenuItem('지금 실행', hub_action(m['id'], 'run')))) for m in jobs], failed)

        links = list(link_items())
        if links:
            yield pystray.MenuItem('🔗 바로가기', pystray.Menu(*links))
        settings = [pystray.MenuItem('화면 펫 (강아지·고양이)', toggle_pet, checked=lambda item: bool(hub.pet_pids())),
                    pystray.MenuItem('로그온 시 자동 시작', toggle_autostart, checked=lambda item: autostart_enabled()),
                    pystray.MenuItem('실패 알림 메일  (예약·상시 실패 → 내 메일함)', toggle_alert,
                                     checked=lambda item: hub.alertmail.settings_of(hub.state.get('alert'))['on']),
                    pystray.MenuItem('✉ 메일·계정 설정…', open_mail_settings)]
        if '--child' in sys.argv:                 # 감시자 아래에서만 — 혼자 떠 있으면 다시 띄워 줄 쪽이 없다
            settings.append(pystray.MenuItem('허브 다시 시작  (코드를 고친 뒤 · 서비스는 끊기지 않음)', restart_app))
        yield pystray.MenuItem('⚙ 설정', pystray.Menu(*settings))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('종료  (서버·워처는 계속 돕니다)', quit_app)
    return pystray.Menu(items)


def toggle_service(m):
    def action(icon, item):
        hub.set_enabled(m['id'], not hub.state['enabled'].get(m['id']))
        refresh(icon)
    return action


def resume(m):
    def action(icon, item):
        try:
            os.remove(paused_flag(m))
        except OSError:
            pass
        refresh(icon)
    return action


def toggle_autostart(icon, item):
    set_autostart(not autostart_enabled())


def open_mail_settings(icon, item):
    """메일·계정 설정 창(저장소 맨 위 setup_gui.py)을 연다."""
    gui = os.path.join(extsvc.ROOT, 'setup_gui.py')
    subprocess.Popen([PYTHONW, gui], cwd=extsvc.ROOT, creationflags=0x00000008)


def toggle_alert(icon, item):
    hub.set_alert(not hub.alertmail.settings_of(hub.state.get('alert'))['on'])
    refresh(icon)


def toggle_pet(icon, item):
    """켜면 상태를 기억해 두었다가 다음에 허브가 시작할 때 펫도 같이 뜬다."""
    on = not hub.pet_pids()
    if not hub.set_pet(on):
        icon.notify('pet 폴더에서 npm install 을 먼저 실행하세요.', '화면 펫을 켤 수 없습니다')
    refresh(icon)


RESTART = {'on': False}


def restart_app(icon, item):
    """허브(트레이 앱)만 다시 띄운다 — 종료 코드 3 으로 끝나면 감시자(WorkKit.exe)가 바로 다시 띄운다.
    서버·워처는 허브와 떨어진 프로세스라 그대로 돌고, 다시 뜬 허브가 넘겨받는다. 허브 창·펫은 다시 붙는다."""
    log('다시 시작 요청')
    RESTART['on'] = True
    hub.shutdown_children()
    icon.stop()


def quit_app(icon, item):
    log('종료 요청')
    hub.stop_pet()                   # 허브 없이 남은 펫은 '연결 중…' 만 보여 주므로 같이 끈다(켜 둔 상태는 기억돼 있어 다음에 다시 뜬다)
    close_window()                   # 허브 창도 같은 이유로 닫는다
    hub.shutdown_children()
    icon.stop()


_last = {'sig': None}


def refresh(icon):
    kind, text = compute_state()
    cfg = tools_config()
    sig = (kind, text, hub.state.get('skin'), tuple(sorted((k, v) for k, v in hub.state['enabled'].items())),
           tuple(os.path.exists(paused_flag(m)) for m in services()),
           tuple(extsvc.port_open(s['port'], timeout=0.2) for s in cfg['services'] if s.get('port') != PORT),
           tuple(watcher_status(w)[0] for w in cfg['watchers']),       # 메뉴에 보이는 서버·도구 상태가 바뀌면 다시 그린다
           os.path.getmtime(SERVICES_JSON) if os.path.exists(SERVICES_JSON) else 0)   # services.json 을 고치면 바로 반영
    if sig != _last['sig']:
        _last['sig'] = sig
        log('상태: %s — %s' % (kind, text))
        icon.icon = make_icon(kind)
        icon.title = (company_title() + ' — ' + text)[:120]
        icon.update_menu()


# ---------------------------------------------------------------- 알림 풍선

def notifier(icon):
    """허브 이벤트 버스를 듣고 풍선으로 알린다."""
    q = queue.Queue(maxsize=1000)
    with hub.lock:
        hub.subs.append(q)
    last_fail = {}

    def balloon(title, text):
        try:
            icon.notify(str(text)[:250], str(title)[:60])
        except Exception as e:
            log('풍선 실패: %s' % e)

    while True:
        try:
            msg = json.loads(q.get())
        except ValueError:
            continue
        kind = msg.get('t')
        if kind == 'notify':
            balloon(msg.get('title') or msg.get('macro', '매크로 허브'), msg.get('text', ''))
        elif kind == 'note':
            balloon('매크로 허브', msg.get('text', ''))
        elif kind == 'run':
            r = msg['run']
            if r.get('tool') or r['status'] not in ('fail', 'timeout'):
                continue
            if r['trigger'] == 'manual':
                continue                                        # 직접 실행한 건 화면에서 이미 보고 있다
            if time.time() - last_fail.get(r['macro'], 0) < 60:  # 계속 죽는 상시 매크로가 풍선을 도배하지 않게
                continue
            last_fail[r['macro']] = time.time()
            balloon('매크로 실패' if r['trigger'] != 'service' else '상시 매크로가 멈췄습니다',
                    '%s (%s) — 로그는 허브 화면에서 확인하세요' % (r['name'], '시간 초과' if r['status'] == 'timeout' else '오류'))


def watcher(icon):
    while True:
        try:
            refresh(icon)
        except Exception as e:
            log('상태 갱신 오류: %s' % e)
        time.sleep(2)


# ---------------------------------------------------------------- 시작

def main():
    args = set(sys.argv[1:])
    if '--install-autostart' in args or '--remove-autostart' in args:
        set_autostart('--install-autostart' in args)
        print('자동 시작:', '등록됨' if autostart_enabled() else '해제됨')
        return
    if already_running():                       # 이미 떠 있으면 창만 열고 끝낸다(바로가기를 또 눌렀을 때)
        open_window('/')
        return

    kill_orphan_runners()
    try:
        srv = hub.start_services('127.0.0.1', PORT)
    except OSError as e:
        log('서버 시작 실패: %s' % e)
        message_box('포트 %d 를 쓸 수 없습니다.\n다른 매크로 허브(콘솔 모드)가 떠 있는지 확인하세요.\n\n%s' % (PORT, e))
        return
    threading.Thread(target=srv.serve_forever, daemon=True, name='http').start()

    icon = pystray.Icon('macro-hub', make_icon('idle'), company_title(), build_menu())

    def setup(icon):
        icon.visible = True
        threading.Thread(target=notifier, args=(icon,), daemon=True).start()
        threading.Thread(target=watcher, args=(icon,), daemon=True).start()
        log('트레이 앱 시작 (pid %d)' % os.getpid())
        if hub.state.get('pet'):
            hub.start_pet()
        if '--quiet' not in args:
            icon.notify('트레이 아이콘을 클릭하면 웹 화면이 열립니다.', '매크로 허브가 시작되었습니다')

    icon.run(setup)
    if RESTART['on']:
        log('트레이 앱 종료 — 감시자가 다시 띄운다')
        sys.exit(3)
    log('트레이 앱 종료')


if __name__ == '__main__':
    main()
