# -*- coding: utf-8 -*-
"""외부 프로그램(웹 서버·워처)을 허브 상시 매크로로 지킨다 — 작업 스케줄러(로그온 시작·1분 워치독)를 대신한다.

    import extsvc
    extsvc.supervise(ctx, cmd=[...], owns=META["owns"], cwd=..., notify=..., tail=...)   # 상주형
    extsvc.run_once(ctx, cmd=[...], cwd=...)                                             # 예약 실행형

진짜 프로그램은 **허브와 떨어진 프로세스**로 띄운다(잠깐 사는 중간 프로세스를 거쳐 부모 관계를 끊는다).
  - 허브를 끄거나 다시 켜도 프로그램은 계속 돈다 — 인박스의 claude 작업이나 서버가 중간에 끊기지 않는다.
  - 허브가 다시 뜨면 이미 돌고 있는 프로그램을 META["owns"] 로 찾아 그대로 지켜본다(중복 실행 없음).
  - 허브 화면·트레이에서 '상시 실행'을 끄면 그때 진짜로 끈다(macrohub.stop_owned 가 owns 로 찾아 끈다).

META["owns"] — 이 매크로가 책임지는 프로세스: [{"name": ["php.exe"], "has": ["0.0.0.0:9000"]}, ...]
  name 중 하나와 이름이 같고, has 의 문자열이 커맨드라인에 모두 들어 있으면(대소문자 무시) 그 프로세스다.
"""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))          # 저장소 맨 위
NO_WINDOW = 0x08000000
LAUNCH_MARK = '--extsvc-launch'
# 허브가 러너에 넣는 환경변수 — 바깥 프로그램(claude 등)까지 새면 동작이 달라진다
HUB_ENV = ('MACROHUB_CTX', 'PYTHONUTF8', 'PYTHONIOENCODING', 'PYTHONUNBUFFERED')

_pl = None


def _proclist():
    global _pl
    if _pl is None:
        spec = importlib.util.spec_from_file_location('proc_live', os.path.join(HERE, '..', 'proc-live', 'proc-live.py'))
        _pl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_pl)
    return _pl


# ---------------------------------------------------------------- 환경

def system_python(windowed=True):
    """이 순서로 고른다: python-path.txt → %LOCALAPPDATA%\\Python\\pythoncore-3.14-64 → PATH."""
    exe = 'pythonw.exe' if windowed else 'python.exe'
    try:
        with open(os.path.join(ROOT, 'python-path.txt'), encoding='utf-8-sig') as f:
            p = f.readline().strip().strip('"')
        if p:
            cand = os.path.join(os.path.dirname(p), exe)
            if os.path.isfile(cand):
                return cand
            if os.path.isfile(p):
                return p
    except OSError:
        pass
    base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Python', 'pythoncore-3.14-64')
    for name in (exe, 'python.exe'):
        if os.path.isfile(os.path.join(base, name)):
            return os.path.join(base, name)
    return exe


def fresh_env():
    """지금 레지스트리의 사용자 환경변수(API 토큰 등)를 다시 읽어 얹는다.
    허브는 로그온 때 뜬 환경을 계속 쓰므로, 나중에 바꾼 값이 반영되게 한다(스케줄러는 매번 새로 읽었다)."""
    env = {k: v for k, v in os.environ.items() if k not in HUB_ENV}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as k:
            i = 0
            while True:
                try:
                    name, val, typ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if name.lower() in ('path', 'temp', 'tmp') or not isinstance(val, str):
                    continue                                  # PATH 는 시스템 값과 합쳐진 것이라 덮지 않는다
                # Windows 환경변수 이름은 대소문자를 가리지 않는데 os.environ 은 'ONEDRIVE' 처럼 대문자로 들고 있다.
                # 레지스트리의 'OneDrive' 를 따로 얹으면 같은 이름이 둘이 되어, PowerShell 5.1 Start-Process 가
                # "항목이 이미 추가되었습니다(OneDrive/ONEDRIVE)" 로 죽는다 — 인박스 워커가 claude 를 못 띄운 적이 있다.
                for dup in [k2 for k2 in env if k2.lower() == name.lower()]:
                    del env[dup]
                env[name] = os.path.expandvars(val) if typ == winreg.REG_EXPAND_SZ else val
    except OSError:
        pass
    return env


# ---------------------------------------------------------------- 프로세스 찾기 · 끄기

def _matches(spec, name, cmdline):
    names = [n.lower() for n in (spec.get('name') or [])]
    if names and name.lower() not in names:
        return False
    low = (cmdline or '').lower()
    if LAUNCH_MARK in low:
        return False                                          # 띄우는 중간 프로세스는 세지 않는다
    return all(h.lower() in low for h in (spec.get('has') or []))


def find(owns):
    """owns 에 맞는 프로세스 PID 목록. 이름이 맞는 것만 커맨드라인을 읽는다(전부 읽으면 느리다)."""
    pl = _proclist()
    names = {n.lower() for s in owns for n in (s.get('name') or [])}
    out = []
    for pid, (_ppid, name) in pl.snapshot().items():
        if names and name.lower() not in names:
            continue
        cmd = pl.command_line(pid)
        if cmd and any(_matches(s, name, cmd) for s in owns):
            out.append(pid)
    return sorted(out)


def kill(owns):
    """owns 에 맞는 프로세스를 자식까지 끈다. 끈 PID 목록."""
    pids = find(owns)
    for pid in pids:
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW)
    return pids


def port_open(port, host='127.0.0.1', timeout=0.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------- 띄우기

_LAUNCHER = r'''
import json, subprocess, sys
a = json.loads(sys.argv[1])
out = open(a["log"], "ab") if a.get("log") else subprocess.DEVNULL
kw = dict(cwd=a.get("cwd"), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
flags = 0x08000000 | 0x00000200            # 창 없음 · 새 프로세스 그룹
try:
    p = subprocess.Popen(a["cmd"], creationflags=flags | 0x01000000, **kw)     # 작업 개체에서도 벗어나 본다
except OSError:
    p = subprocess.Popen(a["cmd"], creationflags=flags, **kw)
print(p.pid)
'''


def _rotate(log, limit=1024 * 1024):
    try:
        if os.path.getsize(log) > limit:
            if os.path.exists(log + '.1'):
                os.remove(log + '.1')
            os.rename(log, log + '.1')
    except OSError:
        pass


def launch(cmd, cwd=None, log=None, env=None):
    """cmd 를 허브와 떨어진 프로세스로 띄운다. 중간 프로세스가 바로 끝나므로 허브의 프로세스 트리에 남지 않는다."""
    if log:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        _rotate(log)
    arg = json.dumps({'cmd': cmd, 'cwd': cwd, 'log': log}, ensure_ascii=False)
    r = subprocess.run([sys.executable, '-c', _LAUNCHER, arg, LAUNCH_MARK], env=env or fresh_env(),
                       capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError('띄우기 실패: ' + (r.stderr or r.stdout).strip()[-300:])
    return int(r.stdout.strip() or 0)


# ---------------------------------------------------------------- 알림 · 로그 따라 읽기

def pump_notify(ctx, path):
    """도구가 남긴 알림 큐(notify.jsonl)를 읽어 허브 알림으로 보내고 비운다.
    여러 건이면 마지막 것만, 3분보다 오래된 것은 흘려보낸다."""
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        os.remove(path)
    except OSError:
        return
    last = None
    for ln in lines:
        try:
            last = json.loads(ln)
        except ValueError:
            continue
    if not isinstance(last, dict):
        return
    try:
        ts = time.mktime(time.strptime(str(last.get('ts', '')), '%Y-%m-%d %H:%M:%S'))
        if time.time() - ts > 180:
            return
    except ValueError:
        pass
    level = 'warning' if any(w in str(last.get('level', '')).lower() for w in ('warn', 'error')) else 'info'
    ctx.notify(str(last.get('title') or ''), str(last.get('text') or ''), level)


class Tail:
    """로그 파일에 새로 붙은 줄을 허브 로그로 옮긴다(허브 화면에서 실시간으로 보이게). 시작 위치는 파일 끝."""

    def __init__(self, path):
        self.path = path
        self.pos = os.path.getsize(path) if path and os.path.exists(path) else 0

    def lines(self, limit=200):
        if not self.path or not os.path.exists(self.path):
            return []
        size = os.path.getsize(self.path)
        if size < self.pos:                                   # 잘렸거나 새로 만들어졌다
            self.pos = 0
        if size == self.pos:
            return []
        with open(self.path, 'rb') as f:
            f.seek(self.pos)
            data = f.read(min(size - self.pos, 256 * 1024))
        self.pos += len(data)
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('cp949', 'replace')
        return [ln for ln in text.replace('\ufeff', '').splitlines() if ln.strip()][-limit:]


def read_state(path):
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- 지키기

def supervise(ctx, cmd, owns, cwd=None, log=None, port=None, notify=None, tail=None, state=None, busy=None,
              grace=20, every=5):
    """상주형 프로그램을 지킨다. 이미 돌고 있으면 넘겨받고, 없거나 죽으면 다시 띄운다. 이 함수는 끝나지 않는다.
    notify: 알림 큐 파일 · tail: 허브 로그로 옮길 로그 파일 · state + busy: state.json 의 state 값 → 고양이 모션
    (예: {"busy": "write"}) · port: 뜬 뒤 응답을 확인해 로그로만 알린다(첫 컴파일이 긴 서버도 있다)."""
    pids = find(owns)
    if pids:
        ctx.log('이미 돌고 있어 그대로 지켜봅니다 (PID %s)' % ', '.join(map(str, pids)))
    tailer = Tail(tail) if tail else None
    quick_deaths, started, port_seen = 0, (time.time() if pids else None), False
    known = set(pids)
    while True:
        snap = _proclist().snapshot()
        alive = bool(known) and all(p in snap for p in known)
        if not alive:
            known = set(find(owns))
            alive = bool(known)
        if not alive:
            if started is not None:
                lived = time.time() - started
                ctx.log('프로그램이 끝났습니다 (%d초 동안 돌았음) — 다시 띄웁니다' % lived)
                quick_deaths = quick_deaths + 1 if lived < 60 else 0
                if quick_deaths >= 3:
                    raise RuntimeError('세 번 연달아 금방 죽었습니다 — 로그를 확인하세요' + (' (%s)' % (log or tail) if (log or tail) else ''))
            ctx.log('띄웁니다: ' + ' '.join(cmd))
            launch(cmd, cwd, log)
            deadline = time.time() + grace
            while time.time() < deadline and not known:
                time.sleep(1)
                known = set(find(owns))
            if not known:
                quick_deaths += 1
                ctx.log('%d초 안에 뜨지 않았습니다' % grace)
                if quick_deaths >= 3:
                    raise RuntimeError('세 번 연달아 띄우지 못했습니다' + (' — 로그: %s' % log if log else ''))
                started = None
                time.sleep(every)
                continue
            started, port_seen = time.time(), False
            ctx.log('떴습니다 (PID %s)' % ', '.join(map(str, sorted(known))))
        if quick_deaths and started is not None and time.time() - started > 60:
            quick_deaths = 0                                  # 1분 넘게 잘 돌았으면 연달아 죽은 횟수를 잊는다
        if port and not port_seen and port_open(port):
            port_seen = True
            ctx.log('포트 %s 응답' % port)
        if tailer:
            for ln in tailer.lines():
                ctx.log('  ' + ln)
        pump_notify(ctx, notify)
        if state and busy:
            kind = busy.get(str(read_state(state).get('state', '')))
            if kind:
                ctx.motion(kind, hold=every * 2 + 1)
        time.sleep(every)


def run_once(ctx, cmd, cwd=None, timeout=None):
    """예약 실행형 — 끝날 때까지 기다리며 출력을 허브 로그로 옮긴다. 0 이 아니면 실패로 끝낸다."""
    ctx.log('실행: ' + ' '.join(cmd))
    env = fresh_env()
    env['PYTHONIOENCODING'] = 'utf-8'                        # 출력만 utf-8 로 받는다(동작에는 영향 없음)
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    for raw in iter(p.stdout.readline, b''):
        try:
            line = raw.decode('utf-8')
        except UnicodeDecodeError:
            line = raw.decode('cp949', 'replace')
        ctx.log(line.rstrip('\r\n'))
    code = p.wait(timeout=timeout)
    if code:
        raise SystemExit(code)
