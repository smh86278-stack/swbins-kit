# -*- coding: utf-8 -*-
"""맥 Taskhand.app 의 실행부 — .app 안의 키트를 쓸 수 있는 곳으로 옮기고, .venv 를 만들고, 허브를 띄운다.

    Taskhand.app/Contents/MacOS/Taskhand   (셸 — 파이썬 3.10+ 을 찾아 이 파일을 부른다)
      → python3 mac_launch.py --src <.app/Contents/Resources/kit>

.app 안은 서명돼 있어 고치면 안 된다 — 허브는 자기 폴더에 상태·기록(state.local.json · data.local …)을 쓰므로
키트를 ~/Library/Application Support/Taskhand/kit 로 옮겨 거기서 돌린다. 새 버전 .app 이면 코드만 바꾸고
설정·기록(KEEP)은 그대로 둔다(윈도우 설치 파일 installer/install_main.py 와 같은 목록).

한 번 더 누르면: 허브가 돌고 있으면 「열기 / 끄기」를 묻는다.
    --smoke     CI 시험 — 옮기기·.venv·허브 띄우기·화면 확인·끄기를 대화 상자 없이
"""
import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

PORT = 8630
APP = 'Taskhand'
SUPPORT = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', APP)
KIT = os.path.join(SUPPORT, 'kit')
LOGS = os.path.join(os.path.expanduser('~'), 'Library', 'Logs', APP)
PIDFILE = os.path.join(SUPPORT, 'hub.pid')
# 사용자 설정·기록 — 새 버전으로 바꿀 때 지우지도 덮지도 않는다 (installer/install_main.py KEEP 과 같게 + .venv)
KEEP = ['config.local.json', 'tools/macro-hub/state.local.json', 'tools/macro-hub/secrets.local.json',
        'tools/macro-hub/runs.jsonl', 'tools/macro-hub/data.local', 'tools/macro-hub/macros.local',
        'tools/macro-hub/shell/window.local.json', 'inbox', 'tools/macro-hub/.venv']


def kept(rel):
    rel = rel.replace(os.sep, '/')
    return any(rel == k or rel.startswith(k + '/') for k in KEEP)


def read_version(root):
    try:
        with open(os.path.join(root, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def sync(src, dst):
    """src(.app 안) → dst. 버전이 같으면 아무것도 안 한다. 바꾼 파일 수."""
    if os.path.isdir(dst) and read_version(src) and read_version(src) == read_version(dst):
        return 0
    os.makedirs(dst, exist_ok=True)
    want = set()
    n = 0
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        dirs[:] = [d for d in dirs if not kept(os.path.normpath(os.path.join(rel_root, d)))]
        for f in files:
            rel = os.path.normpath(os.path.join(rel_root, f))
            if kept(rel):
                continue
            want.add(rel)
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(os.path.join(root, f), out)
            n += 1
    for root, dirs, files in os.walk(dst):                   # 지난 버전에만 있던 코드 파일은 지운다
        rel_root = os.path.relpath(root, dst)
        dirs[:] = [d for d in dirs if not kept(os.path.normpath(os.path.join(rel_root, d)))]
        for f in files:
            rel = os.path.normpath(os.path.join(rel_root, f))
            if rel not in want and not kept(rel) and not f.endswith('.pyc'):
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass
    return n


def hub_dir():
    return os.path.join(KIT, 'tools', 'macro-hub')


def venv_python():
    return os.path.join(hub_dir(), '.venv', 'bin', 'python3')


def ensure_venv(log):
    """허브 .venv(Playwright) — 없거나 requirements.txt 가 바뀌었으면 설치. 실패해도 허브는 뜬다(웹 자동화만 안 됨)."""
    req = os.path.join(hub_dir(), 'requirements.txt')
    mark = os.path.join(hub_dir(), '.venv', 'requirements.done')
    try:
        with open(req, 'rb') as f:
            want = f.read()
    except OSError:
        want = b''
    if os.path.isfile(venv_python()) and os.path.isfile(mark):
        with open(mark, 'rb') as f:
            if f.read() == want:
                return True
    if not os.path.isfile(venv_python()):
        r = subprocess.run([sys.executable, '-m', 'venv', os.path.join(hub_dir(), '.venv')], stdout=log, stderr=log)
        if r.returncode:
            return False
    r = subprocess.run([venv_python(), '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', req],
                       stdout=log, stderr=log)
    if r.returncode:
        return False
    with open(mark, 'wb') as f:
        f.write(want)
    return True


def port_open(timeout=0.5):
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=timeout):
            return True
    except OSError:
        return False


def start_hub(log, wait=30, abort=False):
    py = venv_python() if os.path.isfile(venv_python()) else sys.executable
    env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONFAULTHANDLER='1')   # 기록이 바로 남게 · 멈추면 스레드 위치를 찍을 수 있게
    p = subprocess.Popen([py, os.path.join(hub_dir(), 'macrohub.py'), '--port', str(PORT)], cwd=hub_dir(), env=env,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    with open(PIDFILE, 'w') as f:
        f.write(str(p.pid))
    end = time.time() + wait
    while time.time() < end:
        if port_open():
            return p.pid
        if p.poll() is not None:
            return None
        time.sleep(0.25)
    if not abort:                                            # 늦게라도 뜰 수 있다 — 그대로 둔다
        return None
    # CI 시험: 어디서 멈췄는지 hub.log 에 남기고(faulthandler 가 SIGABRT 에 스레드 위치를 찍는다) 끈다
    try:
        os.kill(p.pid, signal.SIGABRT)
        p.wait(5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
    return None


def stop_hub():
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)          # 허브 + 허브가 띄운 자동화까지(상시 서비스는 따로 떠 있어 남는다)
    except OSError:
        return False
    for _ in range(40):
        if not port_open():
            break
        time.sleep(0.25)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    return True


def dialog(text, buttons=('확인',), default=None):
    """osascript 대화 상자 → 누른 단추 이름(닫으면 '')."""
    btns = '{%s}' % ', '.join(json.dumps(b, ensure_ascii=False) for b in buttons)
    script = 'display dialog %s buttons %s default button %s with title "Taskhand"' % (
        json.dumps(text, ensure_ascii=False), btns, json.dumps(default or buttons[-1], ensure_ascii=False))
    r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    out = r.stdout.strip()
    return out.split(':', 1)[1] if out.startswith('button returned:') else ''


def notify(text):
    subprocess.run(['osascript', '-e', 'display notification %s with title "Taskhand"' % json.dumps(text, ensure_ascii=False)],
                   capture_output=True)


def url():
    return 'http://127.0.0.1:%d/' % PORT


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='.app 안의 키트 폴더')
    ap.add_argument('--smoke', action='store_true', help='CI 시험 — 대화 상자 없이 띄우고 화면을 확인한 뒤 끈다')
    a = ap.parse_args(argv)
    os.makedirs(LOGS, exist_ok=True)
    os.makedirs(SUPPORT, exist_ok=True)

    if port_open() and not a.smoke:
        pick = dialog('Taskhand 허브가 돌고 있습니다.', ('끄기', '열기'), '열기')
        if pick == '끄기':
            if not stop_hub():
                dialog('허브를 끄지 못했습니다 — 이 앱이 띄운 허브가 아니면 그 창(터미널)에서 끄세요.')
        elif pick == '열기':
            subprocess.run(['open', url()])
        return 0

    with open(os.path.join(LOGS, 'hub.log'), 'ab') as log:
        first = not os.path.isdir(KIT)
        changed = sync(a.src, KIT)
        if changed and not a.smoke:
            notify('처음 준비 중입니다 — 1~2분 걸릴 수 있어요' if first else '새 버전으로 바꾸는 중입니다')
        venv_ok = ensure_venv(log)
        log.flush()
        pid = start_hub(log, 90 if a.smoke else 30, abort=a.smoke)
    if not pid:
        msg = '허브를 띄우지 못했습니다 — 기록: ' + os.path.join(LOGS, 'hub.log')
        if a.smoke:
            print(msg)
            return 1
        dialog(msg)
        return 1
    if a.smoke:
        with urllib.request.urlopen(url(), timeout=10) as r:
            page = r.read().decode('utf-8', 'replace')
        ok = 'data-os="mac"' in page
        print('venv', venv_ok, '· 화면', r.status, '· data-os=mac', ok)
        stop_hub()
        return 0 if ok and venv_ok else 1
    if not venv_ok:
        notify('웹 자동화 준비(Playwright 설치)에 실패했습니다 — 허브는 열립니다. 기록: ~/Library/Logs/Taskhand')
    subprocess.run(['open', url()])
    return 0


if __name__ == '__main__':
    sys.exit(main())
