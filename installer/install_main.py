# -*- coding: utf-8 -*-
"""업무 자동화 키트 설치 프로그램 — WorkKitSetup.exe 로 묶인다(build_installer.py). 표준 라이브러리(tkinter)만 쓴다.

    WorkKitSetup.exe                 설치 화면
    WorkKitSetup.exe /S              무인 설치(IT 담당자 일괄 배포용) — 기본 폴더 · 바로가기 · 로그온 자동 시작, 설정 마법사는 띄우지 않음
    WorkKitSetup.exe /S /D=D:\\Kit    무인 설치 + 폴더 지정

- 관리자 권한이 필요 없다 — 사용자 폴더(%LOCALAPPDATA%\\WorkKit)에 깔고 HKCU 에만 등록한다.
- 키트 파일과 내장 파이썬(runtime\\)이 이 exe 안의 payload.zip 에 들어 있다 — 받는 PC 에 파이썬·인터넷이 없어도 된다.
- 다시 설치(업데이트)해도 설정·기록은 그대로 둔다: config.local.json, 허브의 state/secrets/runs, data.local, macros.local.
  zip 에 든 파일만 덮어쓰고, 내장 파이썬(runtime\\)만 통째로 갈아 끼운다.
- 제거는 '앱 및 기능' 또는 시작 메뉴 「업무 자동화 키트 제거」(uninstall.py).
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

APP_NAME = '업무 자동화 키트'
APP_ID = 'WorkKit'
NO_WINDOW = 0x08000000
NEW_CONSOLE = 0x00000010
DETACHED = 0x00000008

if getattr(sys, 'frozen', False):
    BUNDLE = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build')
PAYLOAD = os.path.join(BUNDLE, 'payload.zip')

DEFAULT_DIR = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), APP_ID)
BACKUP_DIR = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), APP_ID + '-설정백업')
START_DIR = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs', APP_NAME)
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\%s' % APP_ID
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

# 다시 깔거나 지울 때 남기는 사용자 파일(설치 폴더 기준)
KEEP = ['config.local.json', 'tools/macro-hub/state.local.json', 'tools/macro-hub/secrets.local.json',
        'tools/macro-hub/runs.jsonl', 'tools/macro-hub/data.local', 'tools/macro-hub/macros.local',
        'tools/macro-hub/shell/window.local.json', 'inbox']


def payload_version():
    try:
        with zipfile.ZipFile(PAYLOAD) as z:
            return z.read('VERSION').decode('utf-8').strip()
    except (OSError, KeyError, zipfile.BadZipFile):
        return '?'


# ---------------------------------------------------------------- 설치 단계

def stop_running(target):
    """설치 폴더 안의 프로그램(허브·서비스·매크로)을 끈다 — 파일을 덮어쓰려면 꺼져 있어야 한다."""
    ps = ("$t = [IO.Path]::GetFullPath('%s').TrimEnd('\\') + '\\'; "
          "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($t, "
          "[StringComparison]::OrdinalIgnoreCase) -and $_.ProcessId -ne %d } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }") % (
              target.replace("'", "''"), os.getpid())
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
                   capture_output=True, creationflags=NO_WINDOW, timeout=60)
    time.sleep(1)


def restore_backup(target):
    """예전에 '설정은 남기고 제거'했으면 그 설정을 되돌려 놓는다(이미 설정이 있으면 건드리지 않음)."""
    if not os.path.isdir(BACKUP_DIR) or os.path.exists(os.path.join(target, 'config.local.json')):
        return False
    for rel in KEEP:
        src = os.path.join(BACKUP_DIR, rel)
        dst = os.path.join(target, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    return True


def extract(target, progress):
    rt = os.path.join(target, 'runtime')
    if os.path.isdir(rt):
        shutil.rmtree(rt, ignore_errors=True)
    with zipfile.ZipFile(PAYLOAD) as z:
        names = z.namelist()
        for i, name in enumerate(names, 1):
            z.extract(name, target)
            if i % 200 == 0 or i == len(names):
                progress(i / len(names))


def _ps_shortcut(path, target, args, workdir, icon, desc):
    q = lambda s: s.replace("'", "''")
    return ("$s = $w.CreateShortcut('%s'); $s.TargetPath = '%s'; $s.Arguments = '%s'; $s.WorkingDirectory = '%s'; "
            "$s.IconLocation = '%s'; $s.Description = '%s'; $s.Save();") % (
                q(path), q(target), q(args), q(workdir), q(icon), q(desc))


def make_shortcuts(target, desktop):
    py, pyw = os.path.join(target, 'runtime', 'python.exe'), os.path.join(target, 'runtime', 'pythonw.exe')
    hub = os.path.join(target, 'tools', 'macro-hub')
    icon = os.path.join(hub, 'web', 'app.ico')
    os.makedirs(START_DIR, exist_ok=True)
    cmds = ['$w = New-Object -ComObject WScript.Shell;',
            _ps_shortcut(os.path.join(START_DIR, APP_NAME + '.lnk'), pyw, '"%s"' % os.path.join(hub, 'launcher.py'),
                         hub, icon, '허브를 띄우고 창을 연다'),
            _ps_shortcut(os.path.join(START_DIR, '메일·계정 설정.lnk'), pyw, '"%s"' % os.path.join(target, 'setup_gui.py'),
                         target, icon, '회사 이름·메일 서버·알림 받을 주소를 설정한다'),
            _ps_shortcut(os.path.join(START_DIR, APP_NAME + ' 제거.lnk'), py, '"%s"' % os.path.join(target, 'uninstall.py'),
                         target, icon, '키트를 이 PC 에서 지운다')]
    if desktop:
        desk = os.path.join(os.path.expanduser('~'), 'Desktop', APP_NAME + '.lnk')
        cmds.append(_ps_shortcut(desk, pyw, '"%s"' % os.path.join(hub, 'launcher.py'), hub, icon, APP_NAME))
    r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ' '.join(cmds)],
                       capture_output=True, creationflags=NO_WINDOW, timeout=60)
    if r.returncode != 0:
        raise RuntimeError('바로가기를 만들지 못했습니다: %s' % r.stderr.decode('cp949', 'replace')[-300:])


def register(target, autostart, version, desktop=True):
    import winreg
    pyw = os.path.join(target, 'runtime', 'pythonw.exe')
    launcher = os.path.join(target, 'tools', 'macro-hub', 'launcher.py')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if autostart:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, '"%s" "%s" --background' % (pyw, launcher))
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except OSError:
                pass
    size_kb = 0
    for root, _dirs, files in os.walk(target):
        for f in files:
            try:
                size_kb += os.path.getsize(os.path.join(root, f)) // 1024
            except OSError:
                pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in (('DisplayName', APP_NAME), ('DisplayVersion', version), ('Publisher', APP_NAME),
                          ('InstallLocation', target),
                          ('DisplayIcon', os.path.join(target, 'tools', 'macro-hub', 'web', 'app.ico')),
                          ('UninstallString', '"%s" "%s"' % (os.path.join(target, 'runtime', 'python.exe'),
                                                             os.path.join(target, 'uninstall.py')))):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, 'EstimatedSize', 0, winreg.REG_DWORD, size_kb)
        winreg.SetValueEx(k, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, 'NoRepair', 0, winreg.REG_DWORD, 1)
    with open(os.path.join(target, 'install.json'), 'w', encoding='utf-8') as f:
        json.dump({'version': version, 'installed': time.strftime('%Y-%m-%d %H:%M:%S'), 'desktop': bool(desktop),
                   'autostart': bool(autostart)}, f, ensure_ascii=False, indent=1)


def check_target(target):
    target = os.path.abspath(target)
    if len(target) <= 3:
        raise RuntimeError('드라이브 맨 위에는 설치할 수 없습니다 — 폴더를 하나 정해 주세요')
    if os.path.isdir(target) and os.listdir(target) and not os.path.isfile(os.path.join(target, 'install.json')):
        raise RuntimeError('비어 있지 않은 폴더입니다(키트 설치 폴더가 아님): %s' % target)
    return target


def install(target, desktop=True, autostart=True, progress=lambda f: None, say=lambda s: None):
    """설치(또는 업데이트). 돌려주는 값: (설치 폴더, 처음 설치인가)."""
    if not os.path.isfile(PAYLOAD):
        raise RuntimeError('설치 파일이 손상됐습니다(payload.zip 없음)')
    target = check_target(target)
    fresh = not os.path.isfile(os.path.join(target, 'install.json'))
    version = payload_version()
    os.makedirs(target, exist_ok=True)
    if not fresh:
        say('실행 중인 키트를 끄는 중…')
        stop_running(target)
    say('파일을 푸는 중…')
    extract(target, progress)
    if restore_backup(target):
        say('예전 설정을 되돌렸습니다')
    say('바로가기 만드는 중…')
    make_shortcuts(target, desktop)
    say('등록하는 중…')
    register(target, autostart, version, desktop)
    return target, fresh


def launch_after(target, first):
    py = os.path.join(target, 'runtime', 'python.exe')
    pyw = os.path.join(target, 'runtime', 'pythonw.exe')
    if first or not os.path.isfile(os.path.join(target, 'config.local.json')):
        subprocess.Popen([pyw, os.path.join(target, 'setup_gui.py')], cwd=target, creationflags=DETACHED)
    subprocess.Popen([pyw, os.path.join(target, 'tools', 'macro-hub', 'launcher.py')],
                     cwd=os.path.join(target, 'tools', 'macro-hub'), creationflags=DETACHED)


# ---------------------------------------------------------------- 화면

def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title('%s 설치 — %s' % (APP_NAME, payload_version()))
    root.resizable(False, False)
    try:
        root.iconbitmap(os.path.join(BUNDLE, 'app.ico'))
    except tk.TclError:
        pass
    pad = {'padx': 14, 'pady': 4}
    tk.Label(root, text=APP_NAME, font=('Malgun Gothic', 15, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', padx=14, pady=(14, 2))
    tk.Label(root, justify='left', fg='#555', font=('Malgun Gothic', 9),
             text='예약 작업 · 실패 알림 메일 · 사이트 감시 · 폴더 백업 · 정기 메일을 한곳에서.\n'
                  '관리자 권한 없이 내 계정에만 설치됩니다. 다시 설치해도 설정은 남습니다.').grid(
        row=1, column=0, columnspan=3, sticky='w', **pad)
    tk.Label(root, text='설치 폴더', font=('Malgun Gothic', 9)).grid(row=2, column=0, sticky='w', **pad)
    path = tk.StringVar(value=DEFAULT_DIR)
    tk.Entry(root, textvariable=path, width=46).grid(row=2, column=1, sticky='we', pady=4)

    def browse():
        d = filedialog.askdirectory(initialdir=os.path.dirname(path.get()) or DEFAULT_DIR)
        if d:
            path.set(os.path.join(os.path.normpath(d), APP_ID) if os.listdir(d) else os.path.normpath(d))
    tk.Button(root, text='찾아보기…', command=browse).grid(row=2, column=2, padx=(4, 14))
    desktop, autostart = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    tk.Checkbutton(root, text='바탕화면 바로가기', variable=desktop).grid(row=3, column=0, columnspan=3, sticky='w', padx=10)
    tk.Checkbutton(root, text='Windows 로그온 때 자동 시작 (예약 작업·감시가 돌려면 켜 두세요)', variable=autostart).grid(
        row=4, column=0, columnspan=3, sticky='w', padx=10)
    bar = ttk.Progressbar(root, length=420, maximum=1.0)
    bar.grid(row=5, column=0, columnspan=3, sticky='we', padx=14, pady=(10, 2))
    status = tk.StringVar(value='')
    tk.Label(root, textvariable=status, fg='#555', font=('Malgun Gothic', 9)).grid(row=6, column=0, columnspan=3, sticky='w', **pad)
    btns = tk.Frame(root)
    btns.grid(row=7, column=0, columnspan=3, sticky='e', padx=14, pady=(4, 14))
    go = tk.Button(btns, text='설치', width=10)
    go.pack(side='right', padx=(6, 0))
    tk.Button(btns, text='닫기', width=10, command=root.destroy).pack(side='right')

    def ui(fn, *a):
        root.after(0, fn, *a)

    def work():
        try:
            target, first = install(path.get(), desktop.get(), autostart.get(),
                                    progress=lambda f: ui(bar.configure, value=f), say=lambda s: ui(status.set, s))
        except Exception as e:      # 화면에 그대로 보여 준다
            ui(status.set, '설치하지 못했습니다')
            ui(messagebox.showerror, APP_NAME, str(e))
            ui(go.configure, state='normal')
            return
        ui(status.set, '설치를 마쳤습니다 — %s' % target)

        def done():
            msg = ('설치를 마쳤습니다.\n\n%s\n\n' % target +
                   ('이어서 뜨는 「메일·계정 설정」 창에서 회사 이름·메일 계정을 정하세요.\n' if first else '') +
                   '허브가 뜨면 ⏰ 예약 작업에서 쓸 기능을 켭니다.')
            messagebox.showinfo(APP_NAME, msg)
            launch_after(target, first)
            root.destroy()
        ui(done)

    def start():
        go.configure(state='disabled')
        threading.Thread(target=work, daemon=True).start()
    go.configure(command=start)
    root.mainloop()


def silent(argv):
    target = DEFAULT_DIR
    for a in argv:
        if a.upper().startswith('/D='):
            target = a[3:].strip('"')
    try:
        install(target, desktop=True, autostart=True)
    except Exception as e:
        sys.stderr.write('설치 실패: %s\n' % e)
        return 1
    return 0


if __name__ == '__main__':
    args = sys.argv[1:]
    if any(a.upper() in ('/S', '--SILENT') for a in args):
        sys.exit(silent(args))
    gui()
