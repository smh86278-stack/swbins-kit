# -*- coding: utf-8 -*-
"""업무 자동화 키트 제거 — '앱 및 기능' · 시작 메뉴 「업무 자동화 키트 제거」가 부른다(설치본의 runtime\\python.exe 로).

    python uninstall.py           묻고 지운다
    python uninstall.py --yes     묻지 않고 지운다(설정은 백업해 둔다)

- 키트 프로그램(허브·서비스·매크로)을 끄고, 로그온 자동 시작·바로가기·'앱 및 기능' 항목을 지운 뒤 설치 폴더를 지운다.
- '설정은 남기기'를 고르면 설정·기록(config.local.json, data.local 등)을 %LOCALAPPDATA%\\WorkKit-설정백업 으로 옮겨 두고,
  다음에 다시 설치하면 설치 프로그램이 되돌려 놓는다.
- 이 스크립트는 지울 폴더 안의 파이썬으로 돈다 — 자기 자신은 못 지우므로, 끝날 때 잠깐 뒤에 폴더를 지우는 명령을 따로 띄우고 끝난다.
"""
import ctypes
import os
import shutil
import subprocess
import sys

APP_NAME = '업무 자동화 키트'
APP_ID = 'WorkKit'
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
BACKUP_DIR = os.path.join(LOCAL, APP_ID + '-설정백업')
START_DIR = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs', APP_NAME)
DESKTOP_LNK = os.path.join(os.path.expanduser('~'), 'Desktop', APP_NAME + '.lnk')
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\%s' % APP_ID
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NO_WINDOW = 0x08000000
NEW_GROUP = 0x00000200
BREAKAWAY = 0x01000000

KEEP = ['config.local.json', 'tools/macro-hub/state.local.json', 'tools/macro-hub/secrets.local.json',
        'tools/macro-hub/runs.jsonl', 'tools/macro-hub/data.local', 'tools/macro-hub/macros.local',
        'tools/macro-hub/shell/window.local.json', 'inbox']

MB_YESNO, MB_YESNOCANCEL, MB_ICONQUESTION, MB_ICONINFO = 0x4, 0x3, 0x20, 0x40
IDYES, IDNO = 6, 7


def ask(text, buttons=MB_YESNO):
    return ctypes.windll.user32.MessageBoxW(None, text, APP_NAME + ' 제거', buttons | MB_ICONQUESTION)


def is_install_dir(path):
    """설치 프로그램이 깐 폴더인지 — 개발용 저장소(git)를 실수로 지우지 않게."""
    return os.path.isfile(os.path.join(path, 'install.json')) and not os.path.isdir(os.path.join(path, '.git'))


def stop_running(target):
    ps = ("$t = [IO.Path]::GetFullPath('%s').TrimEnd('\\') + '\\'; "
          "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($t, "
          "[StringComparison]::OrdinalIgnoreCase) -and $_.ProcessId -ne %d } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }") % (
              target.replace("'", "''"), os.getpid())
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
                   capture_output=True, creationflags=NO_WINDOW, timeout=60)


def backup_settings(target):
    if os.path.isdir(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)
    for rel in KEEP:
        src, dst = os.path.join(target, rel), os.path.join(BACKUP_DIR, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def unregister():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, APP_ID)
    except OSError:
        pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    shutil.rmtree(START_DIR, ignore_errors=True)
    try:
        os.remove(DESKTOP_LNK)
    except OSError:
        pass


def remove_later(target):
    """이 파이썬이 끝난 뒤 폴더를 지운다(2초 기다렸다가)."""
    # 부른 쪽(앱 및 기능·터미널)이 작업 묶음(job)째 정리해도 살아남게 묶음에서 빠져나가고(BREAKAWAY),
    # 작업 폴더는 지울 폴더 밖(TEMP)에 둔다 — cmd 가 그 폴더 안에 서 있으면 rmdir 이 실패한다.
    cmd = 'ping -n 3 127.0.0.1 >nul & rmdir /s /q "%s"' % target
    cwd = os.environ.get('TEMP') or os.path.dirname(target)
    for flags in (NO_WINDOW | NEW_GROUP | BREAKAWAY, NO_WINDOW | NEW_GROUP):
        try:
            subprocess.Popen(['cmd', '/c', cmd], cwd=cwd, creationflags=flags, close_fds=True)
            return
        except OSError:          # 묶음이 빠져나가기를 허락하지 않으면 그냥 띄운다
            continue


def main(argv):
    target = HERE
    if not is_install_dir(target):
        print('설치 폴더가 아닙니다(개발용 저장소이거나 install.json 이 없음): %s' % target)
        return 2
    keep = True
    if '--yes' not in argv:
        r = ask('%s 를 이 PC 에서 지웁니다.\n\n설정과 기록(메일 설정·감시 기록 등)은 남겨 둘까요?\n'
                '  예 — 남겨 둔다(다시 설치하면 되살아남)\n  아니요 — 모두 지운다' % APP_NAME, MB_YESNOCANCEL)
        if r not in (IDYES, IDNO):
            return 1
        keep = (r == IDYES)
    stop_running(target)
    if keep:
        backup_settings(target)
    elif os.path.isdir(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)
    unregister()
    if '--yes' not in argv:
        ctypes.windll.user32.MessageBoxW(None, '지웠습니다.' + ('\n설정 백업: %s' % BACKUP_DIR if keep else ''),
                                         APP_NAME + ' 제거', MB_ICONINFO)
    remove_later(target)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
