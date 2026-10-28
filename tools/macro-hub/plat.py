# -*- coding: utf-8 -*-
"""윈도우·맥 차이를 한곳에 — 허브·자동화·게이트웨이가 함께 쓴다. 표준 라이브러리만.

    import plat
    plat.IS_WIN · plat.IS_MAC
    subprocess.Popen(args, **plat.bg())          창 없이 띄우기(윈도우) · 새 세션으로 띄우기(맥 — 트리째 끄려고)
    plat.kill_tree(pid)                          자식까지 끄기 (taskkill /T · killpg)
    plat.open_path(path) · plat.reveal(path)     폴더 열기 · 파일 위치 보여 주기
    plat.venv_python(here, 'python')             .venv 또는 내장 runtime 의 파이썬
    plat.keychain_put(text) → 'keychain:<id>'    맥 키체인에 비밀값 (윈도우는 DPAPI 를 그대로 쓴다)
    plat.fix_path()                              맥: Finder 로 켠 앱의 짧은 PATH 를 로그인 셸 PATH 로 늘리기
    plat.single_instance(name)                   중복 실행 막기 — 이미 떠 있으면 False

맥 지원은 일부 기능만이다 — 데스크톱 자동화·창 트리거·트레이·자동 시작은 윈도우 전용(README 「맥에서 쓰기」).
"""
import base64
import os
import signal
import subprocess
import sys
import tempfile
import uuid

IS_WIN = os.name == 'nt'
IS_MAC = sys.platform == 'darwin'

NO_WINDOW = 0x08000000 if IS_WIN else 0          # CREATE_NO_WINDOW — 윈도우 밖에서는 creationflags 를 쓰면 ValueError
DETACHED = 0x00000008 if IS_WIN else 0           # DETACHED_PROCESS


def bg(flags=None):
    """Popen 에 붙일 인자 — 윈도우는 creationflags(기본 창 없음), 맥은 새 세션(kill_tree 가 그룹째 끈다)."""
    if IS_WIN:
        return {'creationflags': NO_WINDOW if flags is None else flags}
    return {'start_new_session': True}


def kill_tree(pid):
    """pid 와 그 자식까지 끈다. 이미 끝났으면 조용히 넘어간다."""
    try:
        if IS_WIN:
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW)
            return
        try:
            pg = os.getpgid(pid)
        except ProcessLookupError:
            return
        if pg == pid and pg != os.getpgrp():                 # bg() 로 띄운 것은 자기 그룹의 대장이다 — 그룹째
            os.killpg(pg, signal.SIGKILL)
        else:                                                # 내 그룹에 섞여 있으면 그것만(나까지 끄지 않게)
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def open_path(path):
    """폴더·파일을 기본 프로그램으로 연다(탐색기 · Finder)."""
    if IS_WIN:
        os.startfile(path)
    else:
        subprocess.Popen(['open' if IS_MAC else 'xdg-open', path])


def reveal(path):
    """파일이 든 폴더를 열고 그 파일을 골라 둔다."""
    if IS_WIN:
        subprocess.Popen(['explorer', '/select,', path])
    elif IS_MAC:
        subprocess.Popen(['open', '-R', path])
    else:
        subprocess.Popen(['xdg-open', os.path.dirname(path)])


def venv_python(here, name='python'):
    """허브용 파이썬 — 개발 PC 는 .venv, 윈도우 설치본은 저장소 맨 위 runtime\\ 의 내장 파이썬.
    name 은 'python'·'pythonw'(맥에는 pythonw 가 없어 python 으로)."""
    if IS_WIN:
        exe = name + '.exe'
        cands = (os.path.join(here, '.venv', 'Scripts', exe), os.path.join(here, '..', '..', 'runtime', exe))
    else:
        cands = (os.path.join(here, '.venv', 'bin', 'python3'), os.path.join(here, '.venv', 'bin', 'python'))
    for cand in cands:
        if os.path.isfile(cand):
            return os.path.normpath(cand)
    return cands[0]


def python_names():
    """상시 서비스 넘겨받기(META owns)에서 '파이썬 프로세스' 로 볼 이름들."""
    return ('python.exe', 'pythonw.exe') if IS_WIN else ('python', 'python3', 'Python')


# ---------------------------------------------------------------- 맥 키체인

KEYCHAIN_PREFIX = 'keychain:'
KEYCHAIN_SERVICE = 'Taskhand'
KEYCHAIN_B64 = 'b64:'


def keychain_put(text, account=None):
    """비밀값을 로그인 키체인에 넣고 설정 파일에 남길 표식 'keychain:<계정>' 을 돌려준다."""
    account = account or uuid.uuid4().hex
    # base64 로 넣는다 — security -w 는 ASCII 가 아닌 값(한글 등)을 16진수로 돌려줘 그대로 읽으면 깨진다
    data = KEYCHAIN_B64 + base64.b64encode(text.encode('utf-8')).decode('ascii')
    r = subprocess.run(['security', 'add-generic-password', '-U', '-s', KEYCHAIN_SERVICE, '-a', account, '-w', data],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError('키체인에 넣지 못했습니다: %s' % (r.stderr or r.stdout).strip())
    return KEYCHAIN_PREFIX + account


def keychain_get(marker):
    account = marker[len(KEYCHAIN_PREFIX):] if marker.startswith(KEYCHAIN_PREFIX) else marker
    r = subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', account, '-w'],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError('키체인에서 비밀값을 찾지 못했습니다 — 다른 맥·사용자에서 만든 설정이면 다시 넣으세요')
    out = r.stdout.rstrip('\n')
    return base64.b64decode(out[len(KEYCHAIN_B64):]).decode('utf-8') if out.startswith(KEYCHAIN_B64) else out


# ---------------------------------------------------------------- 맥 PATH

def _login_shell_path():
    try:
        p = subprocess.run([os.environ.get('SHELL') or '/bin/zsh', '-lc', 'printf "%s" "$PATH"'],
                           capture_output=True, timeout=5, stdin=subprocess.DEVNULL)
        lines = p.stdout.decode('utf-8', 'replace').strip().splitlines()
        return lines[-1] if p.returncode == 0 and lines else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def _extra_dirs():
    home = os.path.expanduser('~')
    dirs = [os.path.join(home, '.local', 'bin'), os.path.join(home, '.claude', 'local'), '/opt/homebrew/bin',
            '/usr/local/bin', os.path.join(home, '.npm-global', 'bin'), os.path.join(home, '.volta', 'bin')]
    nvm = os.path.join(home, '.nvm', 'versions', 'node')
    if os.path.isdir(nvm):
        dirs += [os.path.join(nvm, v, 'bin') for v in sorted(os.listdir(nvm), reverse=True)]
    return dirs


def fix_path():
    """맥에서 Finder·.app 으로 켜면 PATH 가 /usr/bin:/bin 뿐이라 claude·node 를 못 찾는다 —
    로그인 셸 PATH 와 흔한 설치 위치를 붙여 둔다(자식 프로세스도 물려받는다). 윈도우는 아무것도 안 한다."""
    if IS_WIN or os.environ.get('TASKHAND_PATH_FIXED'):
        return
    parts = (os.environ.get('PATH') or '').split(os.pathsep) + _login_shell_path().split(':') + _extra_dirs()
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys(p for p in parts if p))
    os.environ['TASKHAND_PATH_FIXED'] = '1'


# ---------------------------------------------------------------- 중복 실행 막기

_held = []


def single_instance(name):
    """같은 name 으로 이미 떠 있으면 False. 윈도우는 이름 있는 뮤텍스, 맥은 잠금 파일(fcntl) — 둘 다 프로세스가 끝나면 풀린다."""
    if IS_WIN:
        import ctypes
        h = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\' + name)
        already = ctypes.windll.kernel32.GetLastError() == 183
        _held.append(h)
        return not already
    import fcntl
    fh = open(os.path.join(tempfile.gettempdir(), 'taskhand-%s-%d.lock' % (name, os.getuid())), 'w')
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _held.append(fh)
    return True
