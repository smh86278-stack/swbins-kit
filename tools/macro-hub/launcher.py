# -*- coding: utf-8 -*-
"""매크로 허브 입구 — MacroHub.exe 로 묶인다(build_exe.bat). 표준 라이브러리만 쓴다.

    MacroHub.exe                허브가 안 떠 있으면 띄우고(감시자가 된다) 허브 창을 연다
    MacroHub.exe --background   창 없이 허브만 띄운다(로그온 자동 시작용)
    MacroHub.exe --page=/ops    창을 열 때 그 화면으로
    MacroHub.exe --install      바로가기(시작 메뉴·바탕화면)와 로그온 자동 시작을 이 exe 로 등록

감시자(죽지 않는 앱): 이 프로세스가 트레이 앱(app.py --child)을 자식으로 띄우고 지킨다.
  - 트레이 '종료'로 끝나면(종료 코드 0) 감시자도 끝난다. '허브 다시 시작'(종료 코드 3)이면 바로 다시 띄운다.
  - 오류로 죽으면(0 이 아닌 종료 코드·강제 종료) 다시 띄운다. 5분 안에 다섯 번 죽으면 멈추고 알린다.
  - 감시자는 한 번에 하나(뮤텍스 Local\\macro-hub-watch). 이미 있으면 창만 열고 끝난다.
허브가 띄운 서버·워처는 원래 허브와 떨어진 프로세스라 트레이 앱이 다시 떠도 끊기지 않는다(extsvc.py).
"""
import ctypes
import datetime
import os
import subprocess
import sys
import threading
import time
import urllib.request

if getattr(sys, 'frozen', False):                       # MacroHub.exe 로 묶였을 때는 exe 가 놓인 폴더
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))

PORT = 8610
URL = 'http://127.0.0.1:%d' % PORT
PYTHONW = os.path.join(HERE, '.venv', 'Scripts', 'pythonw.exe')
APP = os.path.join(HERE, 'app.py')
ELECTRON = os.path.join(HERE, 'pet', 'node_modules', 'electron', 'dist', 'electron.exe')
SHELL_DIR = os.path.join(HERE, 'shell')
ICON = os.path.join(HERE, 'web', 'app.ico')
EXE = os.path.join(HERE, 'MacroHub.exe')
LOG = os.path.join(HERE, 'data.local', 'app.log')
DETACHED = 0x00000008 | 0x00000200                       # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
CRASH_LIMIT, CRASH_WINDOW = 5, 300


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write('%s  [감시] %s\n' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg))
    except OSError:
        pass


def message_box(text, title='매크로 허브'):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x30)


def hub_up(timeout=0.8):
    try:
        with urllib.request.urlopen(URL + '/api/info', timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def open_window(page='/', wait=30):
    """허브 창(Electron, shell\\)을 연다. 허브가 막 뜨는 중이면 응답할 때까지 기다린다.
    창은 한 번에 하나라 이미 열려 있으면 그 창이 앞으로 나온다. Electron 이 없으면 브라우저로."""
    deadline = time.time() + wait
    while not hub_up() and time.time() < deadline:
        time.sleep(0.5)
    if os.path.isfile(ELECTRON) and os.path.isdir(SHELL_DIR):
        subprocess.Popen([ELECTRON, SHELL_DIR, '--page=' + page], cwd=SHELL_DIR, creationflags=DETACHED,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        import webbrowser
        webbrowser.open(URL + page)


def watch(quiet):
    """트레이 앱을 자식으로 띄우고 지킨다. 트레이 '종료'(종료 코드 0)면 같이 끝난다."""
    crashes = []
    log('감시 시작 (pid %d)' % os.getpid())
    while True:
        args = [PYTHONW, APP, '--child'] + (['--quiet'] if quiet or crashes else [])
        started = time.time()
        try:
            code = subprocess.call(args, cwd=HERE)
        except OSError as e:
            message_box('트레이 앱을 띄우지 못했습니다.\n\n%s\n\n%s' % (args[0], e))
            return
        if code == 0:
            log('트레이 앱이 정상 종료 — 감시도 끝냅니다')
            return
        if code == 3:                                     # 트레이 '허브 다시 시작' — 죽은 게 아니다
            log('허브 다시 시작 요청 — 바로 다시 띄웁니다')
            continue
        now = time.time()
        crashes = [t for t in crashes if now - t < CRASH_WINDOW] + [now]
        log('트레이 앱이 비정상 종료(코드 %s, %d초 동안 돌았음) — 다시 띄웁니다 (%d/%d)'
            % (code, now - started, len(crashes), CRASH_LIMIT))
        if len(crashes) >= CRASH_LIMIT:
            message_box('매크로 허브가 %d분 안에 %d번 죽어서 다시 띄우기를 멈췄습니다.\n'
                        '기록: %s\n\n허브가 띄운 서버·워처는 계속 돌고 있습니다.' % (CRASH_WINDOW // 60, CRASH_LIMIT, LOG))
            return
        time.sleep(min(30, 2 ** len(crashes)))


def install():
    """바로가기(시작 메뉴·바탕화면) + 로그온 자동 시작을 MacroHub.exe 로."""
    target = EXE if os.path.isfile(EXE) else PYTHONW
    args = '' if target == EXE else '"%s"' % os.path.abspath(__file__)
    ps = r'''
$w = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
  $s = $w.CreateShortcut((Join-Path $dir '매크로 허브.lnk'))
  $s.TargetPath = '%s'; $s.Arguments = '%s'; $s.WorkingDirectory = '%s'; $s.IconLocation = '%s,0'
  $s.Description = '매크로 허브 — 매크로·상시 서비스·예약 작업'; $s.Save(); Write-Output $s.FullName
}
''' % (target, args, HERE, ICON)
    out = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True,
                         encoding='utf-8', errors='replace', creationflags=0x08000000)
    import winreg
    run = '"%s" --background' % EXE if target == EXE else '"%s" "%s" --background' % (PYTHONW, os.path.abspath(__file__))
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, 'MacroHub', 0, winreg.REG_SZ, run)
    log('설치: 바로가기 %s · 자동 시작 %s' % (out.stdout.strip().replace('\n', ', ') or out.stderr.strip(), run))
    return out.stdout.strip(), run


def main():
    args = sys.argv[1:]
    page = next((a.split('=', 1)[1] for a in args if a.startswith('--page=')), '/')
    if '--install' in args:
        links, run = install()
        message_box('바로가기를 만들었습니다:\n%s\n\n로그온 자동 시작: %s' % (links, run))
        return
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\macro-hub-watch')
    already = ctypes.windll.kernel32.GetLastError() == 183
    if already or (hub_up() and not os.environ.get('MACROHUB_FORCE_WATCH')):
        # 감시자가 이미 있다(또는 감시자 없이 허브가 떠 있다 — 개발 중 app.py 를 직접 띄운 경우): 창만 연다
        if '--background' not in args:
            open_window(page)
        return
    if '--background' not in args:
        threading.Thread(target=open_window, args=(page,), daemon=True).start()
    watch(quiet='--background' in args)
    del mutex


if __name__ == '__main__':
    main()
