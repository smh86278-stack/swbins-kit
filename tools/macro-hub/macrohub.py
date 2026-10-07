# -*- coding: utf-8 -*-
"""매크로 허브 — 회사 업무 화면 처리를 매크로로 돌리는 실시간 프로그램 (본인 전용, Windows).

    python macrohub.py                http://127.0.0.1:8630/
    python macrohub.py --port 8700 --open

하는 일
  - macros\\ (예제, git 에 들어감) · macros.local\\ (실제 업무 매크로, git 제외) 의 *.py 를 목록으로 보여 준다.
  - 매크로를 웹 화면 버튼으로 실행하고, 로그를 실시간으로 본다. 중지 버튼으로 프로세스 트리째 끈다.
  - 자동 실행 트리거: 프로세스가 뜰 때 · 창이 나타날 때 · 시간 예약. 매크로별로 켜야만 동작한다(기본 꺼짐).
  - 녹화: 웹은 playwright codegen, 데스크톱은 '요소 찍기'(마우스 아래 컨트롤 → 코드 조각).

매크로는 .venv 의 파이썬(runner.py)에서 별도 프로세스로 돈다 — 허브는 표준 라이브러리만 쓴다.
계정·비밀번호는 secrets.local.json 에 두고 매크로에서는 ctx.secret('키') 로 읽는다.
허브 화면은 이 PC(127.0.0.1)에서만 열리고, 실행 요청에는 토큰을 요구한다.
"""
import argparse
import ast
import atexit
import ctypes
import ctypes.wintypes as wt
import datetime
import importlib.util
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DIR_EXAMPLE = os.path.join(HERE, 'macros')
DIR_LOCAL = os.path.join(HERE, 'macros.local')
DIR_BUILTIN = os.path.join(HERE, 'builtin')
F_STATE = os.path.join(HERE, 'state.local.json')
F_RUNS = os.path.join(HERE, 'runs.jsonl')
RUNNER = os.path.join(HERE, 'runner.py')
def _pick_python(exe):
    """허브용 파이썬 — 개발 PC 는 .venv, 설치본(WorkKitSetup.exe)은 저장소 맨 위 runtime\\ 에 든 내장 파이썬."""
    for cand in (os.path.join(HERE, '.venv', 'Scripts', exe), os.path.join(HERE, '..', '..', 'runtime', exe)):
        if os.path.isfile(cand):
            return os.path.normpath(cand)
    return os.path.join(HERE, '.venv', 'Scripts', exe)


VENV_PY = _pick_python('python.exe')
PYTHON = VENV_PY if os.path.exists(VENV_PY) else sys.executable
WEB_DIR = os.path.join(HERE, 'web')
WEB = os.path.join(WEB_DIR, 'index.html')
STATIC_TYPES = {'css': 'text/css; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'svg': 'image/svg+xml',
                'png': 'image/png', 'apng': 'image/apng', 'webp': 'image/webp', 'gif': 'image/gif', 'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg', 'mp4': 'video/mp4', 'webm': 'video/webm', 'json': 'application/json; charset=utf-8'}
SKIN_DIR = os.path.join(WEB_DIR, 'skins')

TOKEN = secrets.token_urlsafe(24)
NO_WINDOW = 0x08000000

# 프로세스 스냅샷은 proc-live 와 같은 코드를 쓴다
_spec = importlib.util.spec_from_file_location('proc_live', os.path.join(HERE, '..', 'proc-live', 'proc-live.py'))
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)

sys.path.insert(0, HERE)
import alertmail  # noqa: E402
import runner  # noqa: E402  (read_meta 재사용 — playwright 는 import 하지 않는다)
import winevents  # noqa: E402

lock = threading.RLock()
subs = []


def broadcast(msg):
    data = json.dumps(msg, ensure_ascii=False)
    with lock:
        for q in list(subs):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


# ---------------------------------------------------------------- 상태 파일

state = {'enabled': {}}


def load_state():
    try:
        with open(F_STATE, encoding='utf-8') as f:
            state.update(json.load(f))
    except (OSError, ValueError):
        pass


UI_MODES = ('auto', 'light', 'dark')          # 화면 모드 — 자동(Windows 설정을 따름) · 라이트 · 다크


def ui_mode():
    m = state.get('theme')
    return m if m in UI_MODES else 'auto'


def render_page(path):
    """화면 HTML — 실행 토큰과 화면 모드를 심는다(<html data-mode="__MODE__">). 요청마다 읽으니 고치면 새로고침만으로 보인다."""
    with open(path, encoding='utf-8') as f:
        return f.read().replace('__TOKEN__', TOKEN).replace('__MODE__', ui_mode())


def save_state():
    try:
        with open(F_STATE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


# ---------------------------------------------------------------- 매크로 목록

_cache = {'sig': None, 'items': []}


def _scan(base, local):
    out = []
    if not os.path.isdir(base):
        return out
    for fn in sorted(os.listdir(base)):
        if fn.endswith('.py') and not fn.startswith('_'):
            out.append((os.path.join(base, fn), local))
    return out


MOTIONS = ('web', 'desktop', 'write', 'mail', 'search')     # 펫 고양이가 일할 때 보이는 모습의 종류(runner.py 설명 참고)


def default_motion(meta):
    m = meta.get('motion') or meta.get('target')
    return m if m in MOTIONS else None


def discover():
    """매크로 목록. 예약 시각을 허브 화면에서 바꿨으면(state['schedule']) 그 값을 덧씌운다 —
    META 의 schedule 트리거는 기본값으로 남고(meta_triggers), 창·프로세스 트리거는 그대로다."""
    items = _discover_files()
    ov = state.get('schedule') or {}
    if not ov:
        return items
    out = []
    for it in items:
        if it['id'] in ov:
            keep = [t for t in it['triggers'] if t.get('type') != 'schedule']
            it = dict(it, triggers=keep + list(ov[it['id']]), meta_triggers=it['triggers'])
        out.append(it)
    return out


def _discover_files():
    files = _scan(DIR_EXAMPLE, False) + _scan(DIR_LOCAL, True)
    sig = tuple((p, os.path.getmtime(p)) for p, _ in files)
    if sig == _cache['sig']:
        return _cache['items']
    items = []
    for path, local in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        meta = runner.read_meta(path)
        items.append({
            'id': ('local/' if local else '') + stem, 'path': path, 'local': local,
            'name': meta.get('name') or stem, 'desc': meta.get('desc', ''),
            'kind': meta.get('kind', 'ctx'), 'target': meta.get('target', ''),
            'params': meta.get('params') or {}, 'triggers': meta.get('triggers') or [],
            'service': bool(meta.get('service')),
            'motion': default_motion(meta),
            'owns': meta.get('owns') or [],
            'timeout': int(meta.get('timeout', 0 if meta.get('service') else 600)),
            'cooldown': int(meta.get('cooldown', 10)),
            'valid': bool(meta) or True,
        })
    _cache.update(sig=sig, items=items)
    return items


def find_macro(mid):
    return next((m for m in discover() if m['id'] == mid), None)


# ---------------------------------------------------------------- 실행

class Run:
    def __init__(self, macro_id, name, trigger, tool=False):
        self.id = int(time.time() * 1000)
        self.macro = macro_id
        self.name = name
        self.trigger = trigger
        self.tool = tool
        self.started = time.time()
        self.ended = None
        self.status = 'running'
        self.code = None
        self.lines = deque(maxlen=1500)
        self.proc = None
        self.stopping = False
        self.motion_default = None       # 일반 매크로는 META 의 일 종류, 상시 매크로는 None(평소엔 지켜보기만)
        self.motion = None
        self.motion_until = None         # ctx.motion(hold=) 로 잠깐만 보일 때 끝나는 시각(ms)

    def summary(self):
        return {'id': self.id, 'macro': self.macro, 'name': self.name, 'trigger': self.trigger.get('kind', 'manual'),
                'detail': self.trigger.get('detail', ''), 'started': int(self.started * 1000),
                'ended': int(self.ended * 1000) if self.ended else None,
                'status': self.status, 'code': self.code, 'tool': self.tool}


runs = deque(maxlen=300)
runs_by_id = {}
last_fire = {}


def running_run(macro_id):
    with lock:
        return next((r for r in runs if r.macro == macro_id and r.status == 'running'), None)


def kill_tree(proc):
    try:
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW)
    except OSError:
        pass


def start_run(macro_id, params=None, trigger=None, path=None, name=None, tool=False, timeout=600, motion=None):
    trigger = trigger or {'kind': 'manual'}
    if running_run(macro_id) and not tool:
        return None, '이미 실행 중입니다'
    run = Run(macro_id, name or macro_id, trigger, tool)
    run.motion = run.motion_default = motion
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONUNBUFFERED='1',
               MACROHUB_CTX=json.dumps({'macro': macro_id, 'params': params or {}, 'trigger': trigger}, ensure_ascii=False))
    try:
        run.proc = subprocess.Popen([PYTHON, '-u', RUNNER, path], cwd=HERE, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    except OSError as e:
        return None, '실행 실패: %s' % e
    with lock:
        runs.append(run)
        runs_by_id[run.id] = run
    broadcast({'t': 'run', 'run': run.summary()})
    threading.Thread(target=_pump, args=(run,), daemon=True).start()
    threading.Thread(target=_watch, args=(run, timeout), daemon=True).start()
    return run, None


NOTIFY_PREFIX = '@@notify '
MOTION_PREFIX = '@@motion '


def _set_motion(run, raw):
    """ctx.motion() — 고양이가 보일 일의 모습을 바꾼다. 로그에는 남기지 않는다."""
    try:
        req = json.loads(raw)
        kind, hold = req.get('motion'), req.get('hold')
    except (ValueError, AttributeError):
        return
    run.motion = kind if kind in MOTIONS else run.motion_default
    run.motion_until = None
    if kind in MOTIONS and isinstance(hold, (int, float)) and hold > 0:
        run.motion_until = int((time.time() + min(float(hold), 3600)) * 1000)
    broadcast({'t': 'motion', 'macro': run.macro, 'motion': run.motion, 'until': run.motion_until})


def _pump(run):
    for raw in iter(run.proc.stdout.readline, b''):
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        if line.startswith(MOTION_PREFIX):
            _set_motion(run, line[len(MOTION_PREFIX):])
            continue
        if line.startswith(NOTIFY_PREFIX):          # ctx.notify() — 알림으로 바꾸고 로그에는 사람이 읽는 형태로 남긴다
            try:
                n = json.loads(line[len(NOTIFY_PREFIX):])
                line = '🔔 %s — %s' % (n.get('title', ''), n.get('text', ''))
                broadcast({'t': 'notify', 'title': n.get('title', ''), 'text': n.get('text', ''),
                           'level': n.get('level', 'info'), 'macro': run.name})
            except ValueError:
                pass
        run.lines.append(line)
        broadcast({'t': 'log', 'run': run.id, 'line': line})


def _watch(run, timeout):
    try:
        run.code = run.proc.wait(timeout=timeout or None)
    except subprocess.TimeoutExpired:
        run.lines.append('⏱ 제한 시간(%d초)을 넘겨 중지합니다' % timeout)
        broadcast({'t': 'log', 'run': run.id, 'line': run.lines[-1]})
        run.status = 'timeout'
        kill_tree(run.proc)
        run.code = run.proc.wait()
    run.ended = time.time()
    if run.status == 'running':
        run.status = 'stopped' if run.stopping else ('ok' if run.code == 0 else 'fail')
    if not run.tool:
        rec = dict(run.summary(), tail=list(run.lines)[-30:])
        try:
            with open(F_RUNS, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        except OSError:
            pass
        if run.status in alertmail.ALERT_STATUS:
            threading.Thread(target=_alert_mail, args=(rec,), daemon=True).start()
    broadcast({'t': 'run', 'run': run.summary()})


def _alert_mail(rec):
    """예약 작업·상시 서비스가 실패하면 내 메일함에 알림을 넣는다(alertmail.py). 못 넣으면 허브 화면에 알린다."""
    try:
        alertmail.on_run_end(rec, state.get('alert'))
    except Exception as e:
        broadcast({'t': 'note', 'text': '실패 알림 메일을 넣지 못했습니다: %s' % e})


def set_alert(on):
    a = dict(state.get('alert') or {})
    a['on'] = bool(on)
    state['alert'] = a
    save_state()


def stop_run(run_id):
    run = runs_by_id.get(run_id)
    if not run or run.status != 'running':
        return False
    run.stopping = True
    kill_tree(run.proc)
    return True


def stop_owned(m):
    """META["owns"] 에 맞는 바깥 프로그램을 끈다(extsvc 로 지키는 서버·워처). 허브를 끌 때는 부르지 않는다 —
    그래서 허브를 다시 켜도 프로그램은 끊기지 않고, 상시 실행을 '끌' 때만 진짜로 멈춘다."""
    if not m.get('owns'):
        return []
    import extsvc
    return extsvc.kill(m['owns'])


def set_enabled(mid, on):
    """상시 매크로·예약 매크로 켜기/끄기. 상시 매크로를 끄면 지키던 바깥 프로그램까지 멈춘다."""
    m = find_macro(mid)
    if not m:
        return False
    state['enabled'][mid] = bool(on)
    save_state()
    if not on and m['service']:
        r = running_run(mid)
        if r:
            stop_run(r.id)
        stop_owned(m)
    broadcast({'t': 'macros'})
    return True


def service_action(mid, action):
    """운영 화면·트레이의 시작/중지/재시작/지금 실행. 돌려주는 값: (ok, 안내 문구)"""
    m = find_macro(mid)
    if not m:
        return False, '허브에 없는 매크로: %s' % mid
    if action == 'start':
        set_enabled(mid, True)
        return True, '%s — 상시 실행을 켰습니다(몇 초 안에 뜹니다)' % m['name'] if m['service'] else '%s — 예약 실행을 켰습니다' % m['name']
    if action == 'stop':
        set_enabled(mid, False)
        return True, '%s — 멈췄습니다' % m['name']
    if action == 'restart':
        if m['service']:
            if not state['enabled'].get(mid):
                set_enabled(mid, True)
            killed = stop_owned(m)
            return True, '%s — 다시 띄웁니다%s' % (m['name'], ' (끈 PID %s)' % ', '.join(map(str, killed)) if killed else '')
        action = 'run'
    if action == 'run':
        if m['service']:
            return service_action(mid, 'restart')
        run, err = run_macro(mid, None, {'kind': 'manual', 'detail': '지금 실행'})
        return (True, '%s — 실행했습니다' % m['name']) if run else (False, err)
    return False, '알 수 없는 동작: %s' % action


def run_macro(macro_id, params=None, trigger=None):
    m = find_macro(macro_id)
    if not m:
        return None, '매크로를 찾을 수 없습니다'
    merged = {k: v for k, v in m['params'].items()}
    merged.update({k: v for k, v in (params or {}).items() if k in m['params'] or not m['params']})
    return start_run(m['id'], merged, trigger, m['path'], m['name'], timeout=m['timeout'],
                     motion=None if m['service'] else m['motion'])


# ---------------------------------------------------------------- 자동 실행 트리거

user32 = ctypes.WinDLL('user32', use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]


DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def days_match(spec, weekday):
    spec = (spec or 'daily').lower().replace(' ', '')
    if spec in ('daily', '*', ''):
        return True
    for part in spec.split(','):
        if '-' in part:
            a, b = part.split('-', 1)
            if a in DAYS and b in DAYS and DAYS.index(a) <= weekday <= DAYS.index(b):
                return True
        elif part in DAYS and DAYS.index(part) == weekday:
            return True
    return False


def parse_every(text):
    m = re.fullmatch(r'\s*(\d+)\s*([smh])\s*', str(text))
    return int(m.group(1)) * {'s': 1, 'm': 60, 'h': 3600}[m.group(2)] if m else None


HUB_BOOT = time.time()
SCHED_LAST = {}                      # (매크로 id, 'every' 값) → 마지막으로 쏜 시각. 간격을 바꾸면 새로 센다


def every_base(mid, every):
    """간격 예약을 세기 시작할 시각 — 이번 허브에서 쏜 시각, 없으면 허브가 뜨기 전 마지막 실행(runs.jsonl),
    그것도 없으면 허브가 뜬 시각. (허브를 다시 켤 때마다 '10분마다' 가 다시 세지며 밀리던 것을 막는다)"""
    key = (mid, every)
    if key not in SCHED_LAST:
        last = (LAST_RUN.get(mid) or {}).get('started')
        SCHED_LAST[key] = min(HUB_BOOT, last / 1000) if last else HUB_BOOT
    return SCHED_LAST[key]


def valid_days(spec):
    spec = (spec or 'daily').lower().replace(' ', '')
    if spec in ('daily', '*'):
        return True
    for part in spec.split(','):
        ends = part.split('-', 1)
        if not part or any(e not in DAYS for e in ends):
            return False
    return True


def clean_schedule(items):
    """화면에서 받은 예약 트리거 검사. (정리된 목록, 오류 문구)"""
    if not isinstance(items, list) or not items:
        return None, '예약을 하나 이상 넣으세요'
    out = []
    for t in items[:10]:
        t = t if isinstance(t, dict) else {}
        if t.get('every'):
            sec = parse_every(t['every'])
            if not sec or sec < 60:
                return None, '간격은 1m 이상으로(예: 10m, 2h): %s' % t.get('every')
            out.append({'type': 'schedule', 'every': str(t['every']).strip()})
        elif t.get('at'):
            at = str(t['at']).strip()
            if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', at):
                return None, '시각은 HH:MM 으로(예: 09:30): %s' % at
            days = str(t.get('days') or 'daily').strip().lower()
            if not valid_days(days):
                return None, '요일은 daily · mon-fri · mon,wed 처럼: %s' % days
            out.append({'type': 'schedule', 'at': at, 'days': days})
        else:
            return None, '예약마다 every 또는 at 이 필요합니다'
    return out, None


def next_fire(m, trg, now=None):
    """이 예약이 다음에 쏠 시각(epoch 초). 모르면 None."""
    now = now or time.time()
    if 'every' in trg:
        sec = parse_every(trg['every'])
        if not sec:
            return None
        return max(now, every_base(m['id'], trg['every']) + sec)
    if 'at' in trg:
        try:
            hh, mm = map(int, str(trg['at']).split(':'))
        except ValueError:
            return None
        base = datetime.datetime.fromtimestamp(now).replace(second=0, microsecond=0)
        for d in range(0, 8):
            cand = (base + datetime.timedelta(days=d)).replace(hour=hh, minute=mm)
            if cand.timestamp() >= now - 59 and days_match(trg.get('days'), cand.weekday()):
                return cand.timestamp()
    return None


def schedule_view():
    """예약 화면용 — 예약 트리거가 있는 매크로(상시 매크로 제외)."""
    out = []
    for m in discover():
        meta = m.get('meta_triggers', m['triggers'])
        if m['service'] or not any(t.get('type') == 'schedule' for t in m['triggers'] + meta):
            continue
        sched = [t for t in m['triggers'] if t.get('type') == 'schedule']
        enabled = bool(state['enabled'].get(m['id']))
        nexts = [n for n in (next_fire(m, t) for t in sched) if n] if enabled else []
        v = macro_view(m)
        out.append({'id': m['id'], 'name': m['name'], 'desc': m['desc'], 'enabled': enabled,
                    'running': v['running'], 'last': v['last'], 'schedule': sched,
                    'default': [t for t in meta if t.get('type') == 'schedule'],
                    'overridden': m['id'] in (state.get('schedule') or {}),
                    'next': int(min(nexts) * 1000) if nexts else None})
    return out


def today_at(at, now):
    """'HH:MM' → 오늘 그 시각(epoch 초)."""
    try:
        hh, mm = map(int, str(at).split(':'))
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()
    except ValueError:
        return None


def at_due(trg, sched_from, now):
    """시각 예약(at·days)이 '지난번 확인(sched_from, epoch 초) ~ 지금(now, datetime)' 사이에 왔으면 그 시각(epoch 초), 아니면 None."""
    if 'at' not in trg or not days_match(trg.get('days'), now.weekday()):
        return None
    at_ts = today_at(trg['at'], now)
    return at_ts if at_ts is not None and sched_from < at_ts <= now.timestamp() else None


def ran_since(mid, ts):
    """이 매크로가 ts(epoch 초) 이후에 시작된 적이 있나 — 지금 허브의 실행 + 허브가 뜨기 전 기록(runs.jsonl)."""
    with lock:
        if any(r.macro == mid and not r.tool and r.started >= ts for r in runs):
            return True
    last = LAST_RUN.get(mid)
    return bool(last and (last.get('started') or 0) >= ts * 1000)


def fire(m, trigger):
    now = time.time()
    if running_run(m['id']):
        return
    if now - last_fire.get(m['id'], 0) < m['cooldown']:
        return
    last_fire[m['id']] = now
    run, err = run_macro(m['id'], None, trigger)
    if err:
        broadcast({'t': 'note', 'text': '%s: %s' % (m['name'], err)})


win_events = queue.Queue(maxsize=5000)      # winevents 훅 스레드가 채운다 — (hwnd, 'show'|'name')


def window_info(hwnd):
    """보이는 창이고 제목이 있으면 (제목, pid), 아니면 None."""
    if not user32.IsWindowVisible(hwnd):
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    if not n:
        return None
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return buf.value, pid.value


def trigger_loop():
    """창 트리거는 Windows 창 이벤트가 올 때 바로 처리하고(폴링 아님), 프로세스·시간 예약은 0.5초마다 훑는다."""
    prev_procs = pl.snapshot()
    seen_titles = {}                           # hwnd -> 마지막으로 본 제목 (같은 제목 반복 이벤트 무시)
    fired_hwnd = set()
    sched_done = set()
    last_poll = 0.0
    # 시각 예약은 '지난번 확인 ~ 지금' 사이에 그 시각이 있었으면 쏜다. 처음엔 오늘 0시부터 본다 —
    # 허브가 꺼져 있었거나(로그인 전·재시작) PC 가 잠들어 있던 동안 놓친 오늘 예약을 한 번 따라잡는다.
    # 화면에서 시각을 이미 지난 시각으로 바꾸거나 예약을 막 켠 경우는 구간 밖이라 바로 돌지 않는다.
    sched_prev = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    while True:
        batch = []
        try:
            batch.append(win_events.get(timeout=0.5))
            while True:
                batch.append(win_events.get_nowait())
        except queue.Empty:
            pass
        try:
            new_wins = []
            for hwnd, _kind in batch:
                info = window_info(hwnd)
                if info and seen_titles.get(hwnd) != info[0]:
                    seen_titles[hwnd] = info[0]
                    new_wins.append((hwnd, info[0], info[1]))
            if len(seen_titles) > 5000:
                seen_titles.clear()

            active = [m for m in discover() if state['enabled'].get(m['id']) and m['triggers']]
            polling = time.time() - last_poll >= 0.5
            new_procs, cur = [], {}
            if polling:
                last_poll = time.time()
                cur = pl.snapshot()
                new_procs = [(pid, v[1]) for pid, v in cur.items() if pid not in prev_procs or prev_procs[pid][1] != v[1]]
                prev_procs = cur
            elif new_wins and any(t.get('type') == 'window' for m in active for t in m['triggers']):
                cur = pl.snapshot()            # 창 소유 프로세스 이름을 알아야 할 때만
            now = datetime.datetime.now()
            now_ts = now.timestamp()
            sched_from = sched_prev
            if polling:
                sched_prev = now_ts
            if not active:
                continue
            for m in active:
                for idx, trg in enumerate(m['triggers']):
                    kind = trg.get('type')
                    if kind == 'process':
                        want = str(trg.get('name', '')).lower()
                        for pid, name in new_procs:
                            if want and name.lower() == want:
                                fire(m, {'kind': 'process', 'detail': name, 'name': name, 'pid': pid})
                    elif kind == 'window':
                        for h, title, pid in new_wins:
                            if (m['id'], h) in fired_hwnd or not re.search(trg.get('title', '$^'), title, re.I):
                                continue
                            pname = cur.get(pid, (0, ''))[1]
                            if trg.get('process') and pname.lower() != str(trg['process']).lower():
                                continue
                            fired_hwnd.add((m['id'], h))
                            fire(m, {'kind': 'window', 'detail': title, 'title': title, 'hwnd': h, 'pid': pid, 'process': pname})
                    elif kind == 'schedule' and polling:
                        key = (m['id'], idx)
                        if 'every' in trg:
                            sec = parse_every(trg['every'])
                            if sec:
                                skey = (m['id'], trg['every'])
                                last = every_base(m['id'], trg['every'])
                                if time.time() - last >= sec:
                                    SCHED_LAST[skey] = time.time()
                                    fire(m, {'kind': 'schedule', 'detail': '매 %s' % trg['every']})
                        elif 'at' in trg:
                            at_ts = at_due(trg, sched_from, now)
                            stamp = (m['id'], now.date(), trg['at'])
                            if at_ts is not None and stamp not in sched_done:
                                sched_done.add(stamp)
                                if not ran_since(m['id'], at_ts):
                                    late = now_ts - at_ts > 120
                                    fire(m, {'kind': 'schedule', 'detail': trg['at'] + (
                                        ' — 놓친 예약을 %s 에 따라잡음' % now.strftime('%H:%M') if late else '')})
            if len(fired_hwnd) > 5000:
                fired_hwnd.clear()
        except Exception as e:  # 감시 루프는 죽지 않는다
            print('trigger_loop 오류:', e, file=sys.stderr)
            time.sleep(0.5)


# ---------------------------------------------------------------- 상시 매크로 (service)

def service_loop():
    """켜 둔 상시 매크로(META["service"]=True)가 죽어 있으면 다시 살린다. 연달아 바로 죽으면 간격을 늘린다(최대 60초)."""
    retry_at = {}
    delay = {}
    while True:
        time.sleep(3)
        try:
            for m in discover():
                if not (m['service'] and state['enabled'].get(m['id'])):
                    continue
                if running_run(m['id']) or time.time() < retry_at.get(m['id'], 0):
                    continue
                prev = next((r for r in reversed(runs) if r.macro == m['id']), None)
                if prev and prev.ended and prev.ended - prev.started < 20:
                    delay[m['id']] = min(60, delay.get(m['id'], 3) * 2)
                else:
                    delay[m['id']] = 3
                run, err = run_macro(m['id'], None, {'kind': 'service', 'detail': '상시 실행'})
                retry_at[m['id']] = time.time() + delay[m['id']]
                if err:
                    broadcast({'t': 'note', 'text': '%s: %s' % (m['name'], err)})
        except Exception as e:
            print('service_loop 오류:', e, file=sys.stderr)


# ---------------------------------------------------------------- 녹화 · 새 매크로

TEMPLATE_WEB = '''# -*- coding: utf-8 -*-
META = {
    "name": "%(name)s",
    "desc": "",
    "kind": "ctx",
    "target": "web",
    "motion": "web",     # 펫이 보일 일의 모습: web · desktop · write · mail · search (ctx.motion() 으로 도중에 바꿀 수 있다)
    "params": {},
    "triggers": [],      # 예: {"type": "schedule", "at": "09:00", "days": "mon-fri"}
    "timeout": 300,
}


def run(ctx):
    page = ctx.page
    page.goto("https://example.com")
    ctx.log("제목:", page.title())
'''

TEMPLATE_DESKTOP = '''# -*- coding: utf-8 -*-
META = {
    "name": "%(name)s",
    "desc": "",
    "kind": "ctx",
    "target": "desktop",
    "motion": "desktop", # 펫이 보일 일의 모습: web · desktop · write · mail · search (ctx.motion() 으로 도중에 바꿀 수 있다)
    "params": {},
    "triggers": [],      # 예: {"type": "window", "title": "접속", "process": "notepad.exe"}
    "timeout": 120,
}


def run(ctx):
    win = ctx.window(r"창 제목 일부")
    ctx.log("찾은 창:", win.window_text())
    # 컨트롤 조작은 허브 화면의 '요소 찍기' 가 만들어 주는 코드를 붙여 넣는다.
'''


def safe_name(text):
    return re.sub(r'[^\w\-]+', '_', (text or '').strip(), flags=re.UNICODE).strip('_')[:40]


def new_macro(name, kind):
    stem = safe_name(name)
    if not stem:
        return None, '이름을 입력하세요'
    os.makedirs(DIR_LOCAL, exist_ok=True)
    path = os.path.join(DIR_LOCAL, stem + '.py')
    if os.path.exists(path):
        return None, '같은 이름이 이미 있습니다'
    with open(path, 'w', encoding='utf-8') as f:
        f.write((TEMPLATE_DESKTOP if kind == 'desktop' else TEMPLATE_WEB) % {'name': name.strip()})
    return 'local/' + stem, None


rec = {'proc': None}


def record_web(url, name):
    stem = safe_name(name)
    if not stem or not url:
        return '이름과 주소를 입력하세요'
    if rec['proc'] and rec['proc'].poll() is None:
        return '이미 녹화 창이 열려 있습니다'
    os.makedirs(DIR_LOCAL, exist_ok=True)
    dest = os.path.join(DIR_LOCAL, stem + '.py')
    if os.path.exists(dest):
        return '같은 이름이 이미 있습니다'
    tmp = os.path.join(HERE, '.codegen-%s.py' % stem)
    try:
        rec['proc'] = subprocess.Popen([PYTHON, '-m', 'playwright', 'codegen', '--channel', 'chrome', '-o', tmp, url],
                                       cwd=HERE, creationflags=NO_WINDOW)
    except OSError as e:
        return '녹화 시작 실패: %s' % e

    def finish():
        rec['proc'].wait()
        try:
            code = open(tmp, encoding='utf-8').read() if os.path.exists(tmp) else ''
        except OSError:
            code = ''
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        if code.strip():
            meta = {'name': name.strip(), 'desc': '녹화 %s' % datetime.date.today(), 'kind': 'script',
                    'target': 'web', 'triggers': [], 'timeout': 300}
            with open(dest, 'w', encoding='utf-8') as f:
                f.write('# -*- coding: utf-8 -*-\nMETA = %r\n\n%s' % (meta, code))
            broadcast({'t': 'note', 'text': '녹화 저장: %s' % os.path.basename(dest)})
        else:
            broadcast({'t': 'note', 'text': '녹화한 내용이 없어 저장하지 않았습니다'})
        broadcast({'t': 'macros'})

    threading.Thread(target=finish, daemon=True).start()
    return None


# ---------------------------------------------------------------- 화면 펫 (Electron)

PET_DIR = os.path.join(HERE, 'pet')
PET_EXE = os.path.join(PET_DIR, 'node_modules', 'electron', 'dist', 'electron.exe')


def pet_installed():
    return os.path.exists(PET_EXE)


def pet_pids():
    """실행 중인 펫(Electron) 프로세스 — 실행 파일 경로가 이 폴더의 pet 안에 있는 것만 센다(다른 Electron 앱은 건드리지 않는다)."""
    key = os.path.join('macro-hub', 'pet', 'node_modules', 'electron').lower()
    window = os.path.join('macro-hub', 'shell').lower()      # 허브 창(shell\)도 같은 Electron 을 쓴다 — 펫으로 치지 않는다
    out = []
    for pid, (_ppid, name) in pl.snapshot().items():
        cmd = (pl.command_line(pid) or '').lower()
        if name.lower() == 'electron.exe' and key in cmd and window not in cmd:
            out.append(pid)
    return out


def start_pet():
    if not pet_installed():
        return False
    if not pet_pids():
        subprocess.Popen([PET_EXE, '.'], cwd=PET_DIR, creationflags=NO_WINDOW | 0x00000008)     # DETACHED_PROCESS
    return True


def stop_pet():
    for pid in pet_pids():
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW)


def set_pet(on):
    """화면 펫 켜기/끄기 — 켜 둔 상태를 기억해, 다음에 허브가 시작할 때도 따라 켠다. 트레이·웹 화면·펫 메뉴가 모두 이걸 쓴다."""
    if on and not pet_installed():
        return False
    state['pet'] = bool(on)
    save_state()
    if on:
        start_pet()
    else:
        stop_pet()
    broadcast({'t': 'pet', 'on': bool(on)})
    return True


# ---------------------------------------------------------------- HTTP

LAST_RUN = {}                        # 매크로 id → 허브가 시작하기 전 마지막 실행(runs.jsonl 에서). 다시 켜도 '마지막 실행'이 보이게


def load_last_runs(keep=2000, limit=2 * 1024 * 1024):
    """runs.jsonl 에서 매크로별 마지막 실행을 읽는다. 파일이 limit 를 넘으면 최근 keep 건만 남긴다
    (예약 매크로가 10분마다 한 줄씩 쌓으니 정리하지 않으면 계속 커진다)."""
    try:
        with open(F_RUNS, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
    except OSError:
        return
    for ln in lines:
        try:
            r = json.loads(ln)
            LAST_RUN[r['macro']] = {k: v for k, v in r.items() if k != 'tail'}
        except (ValueError, KeyError, TypeError):
            continue
    try:
        if os.path.getsize(F_RUNS) > limit:
            with open(F_RUNS, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines[-keep:]) + '\n')
    except OSError:
        pass


def macro_view(m):
    r = running_run(m['id'])
    last = next((x for x in reversed(runs) if x.macro == m['id'] and not x.tool and x.status != 'running'), None)
    d = {k: v for k, v in m.items() if k != 'path'}
    d.update(enabled=bool(state['enabled'].get(m['id'])), running=r.id if r else None,
             last=last.summary() if last else LAST_RUN.get(m['id']),
             motion=r.motion if r else d['motion'], motion_until=r.motion_until if r else None,
             motion_default=r.motion_default if r else None)
    return d


class Handler(BaseHTTPRequestHandler):
    server_version = 'macrohub'
    allowed_hosts = frozenset()

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        return not self.allowed_hosts or self.headers.get('Host', '') in self.allowed_hosts

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b'forbidden', 'text/plain')
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == '/':
            try:
                html = render_page(WEB)
            except OSError:
                return self._send(500, b'web/index.html missing', 'text/plain')
            return self._send(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        if u.path == '/ops':                          # 운영 화면 — 예약 작업·상시 서비스·기능 상태·설정·에이전트
            try:
                html = render_page(os.path.join(WEB_DIR, 'ops.html'))
            except OSError:
                return self._send(500, b'web/ops.html missing', 'text/plain')
            return self._send(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        if u.path == '/pet':                          # 데스크톱 펫(Electron)이 불러가는 투명 배경 페이지
            try:
                html = render_page(os.path.join(WEB_DIR, 'pet.html'))
            except OSError:
                return self._send(500, b'web/pet.html missing', 'text/plain')
            return self._send(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        if u.path == '/api/skins':                    # web\skins\<이름>\skin.json 이 있는 폴더 목록
            out = []
            if os.path.isdir(SKIN_DIR):
                for name in sorted(os.listdir(SKIN_DIR)):
                    mf = os.path.join(SKIN_DIR, name, 'skin.json')
                    if re.fullmatch(r'[\w\-]+', name) and not name.startswith('_') and os.path.isfile(mf):
                        try:
                            with open(mf, encoding='utf-8-sig') as f:
                                out.append({'id': name, 'name': json.load(f).get('name', name)})
                        except (OSError, ValueError):
                            out.append({'id': name, 'name': name + ' (skin.json 오류)'})
            return self._send(200, out)
        m = re.fullmatch(r'/skin/([\w\-]+)/([\w\-.]+\.(json|png|apng|gif|webp|jpg|jpeg|svg|mp4|webm))', u.path)
        if m:                                         # 스킨 파일: 스킨 폴더 바로 아래 것만(경로 탈출 불가)
            path = os.path.join(SKIN_DIR, m.group(1), m.group(2))
            if not os.path.isfile(path):
                return self._send(404, b'not found', 'text/plain')
            with open(path, 'rb') as f:
                return self._send(200, f.read(), STATIC_TYPES[m.group(3)])
        if u.path.startswith('/static/'):             # web\ 바로 아래 파일만 — 하위 폴더·경로 탈출 불가
            name = u.path[len('/static/'):]
            m = re.fullmatch(r'[\w\-]+\.(css|js|svg|png|webp|gif|mp4)', name)
            path = os.path.join(WEB_DIR, name) if m else ''
            if not m or not os.path.isfile(path):
                return self._send(404, b'not found', 'text/plain')
            with open(path, 'rb') as f:
                return self._send(200, f.read(), STATIC_TYPES[m.group(1)])
        if u.path == '/favicon.ico':
            return self._send(204, b'', 'image/x-icon')
        if u.path == '/api/macros':
            return self._send(200, [macro_view(m) for m in discover()])
        if u.path == '/api/runs':
            with lock:
                items = [r.summary() for r in runs if not r.tool][-100:]
            return self._send(200, items[::-1])
        if u.path == '/api/run':
            r = runs_by_id.get(int(q.get('id', ['0'])[0] or 0))
            if not r:
                return self._send(404, {'error': 'no such run'})
            return self._send(200, dict(r.summary(), lines=list(r.lines)))
        if u.path == '/api/skin':
            return self._send(200, {'skin': state.get('skin')})
        if u.path == '/api/theme':                    # 허브 전용 창(shell/main.js)이 창 테두리·배경색을 맞추려고 묻는다
            return self._send(200, {'mode': ui_mode()})
        if u.path == '/api/schedule':
            return self._send(200, schedule_view())
        if u.path.startswith('/api/ops/'):            # 운영 화면 — 기능 상태·설정·에이전트(읽기 전용)
            import ops
            what = u.path[len('/api/ops/'):]
            try:
                if what == 'features':
                    return self._send(200, ops.features_status())
                if what == 'settings':
                    return self._send(200, ops.settings_status())
                if what == 'agents':
                    return self._send(200, ops.agent_view(verify=q.get('verify', ['0'])[0] == '1'))
            except Exception as e:
                return self._send(500, {'error': '%s: %s' % (type(e).__name__, e)})
            return self._send(404, {'error': 'no such ops view'})
        if u.path == '/api/pet':
            return self._send(200, {'on': bool(pet_pids()), 'installed': pet_installed(), 'remembered': bool(state.get('pet'))})
        if u.path == '/api/info':
            return self._send(200, {'python': PYTHON, 'venv': PYTHON == VENV_PY, 'local_dir': DIR_LOCAL})
        if u.path == '/events':
            return self._sse()
        self._send(404, b'not found', 'text/plain')

    def do_POST(self):
        if not self._host_ok() or self.headers.get('X-Hub-Token') != TOKEN:
            return self._send(403, {'error': 'forbidden'})
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self._send(403, {'error': 'bad origin'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, {'error': 'bad json'})
        path = urlparse(self.path).path

        if path == '/api/run':
            run, err = run_macro(body.get('id', ''), body.get('params'), {'kind': 'manual'})
            return self._send(200 if run else 409, {'run': run.id} if run else {'error': err})
        if path == '/api/stop':
            return self._send(200, {'ok': stop_run(int(body.get('run', 0)))})
        if path == '/api/enable':
            if not set_enabled(body.get('id', ''), bool(body.get('enabled'))):
                return self._send(404, {'error': 'no such macro'})
            return self._send(200, {'ok': True})
        if path == '/api/schedule':                   # 예약 시각 바꾸기 {"id", "schedule": [...]} · 되돌리기 {"id", "reset": true}
            m = find_macro(body.get('id', ''))
            if not m or m['service']:
                return self._send(404, {'error': '예약 매크로가 아닙니다'})
            ov = state.setdefault('schedule', {})
            if body.get('reset'):
                ov.pop(m['id'], None)
            else:
                items, err = clean_schedule(body.get('schedule'))
                if err:
                    return self._send(400, {'error': err})
                ov[m['id']] = items
            save_state()
            broadcast({'t': 'macros'})
            return self._send(200, {'ok': True})
        if path == '/api/service':                    # 운영 화면(/ops): {"id", "action": start|stop|restart|run}
            ok, msg = service_action(body.get('id', ''), body.get('action', ''))
            return self._send(200 if ok else 400, {'ok': ok, 'message': msg} if ok else {'error': msg})
        if path == '/api/new':
            mid, err = new_macro(body.get('name', ''), body.get('kind', 'web'))
            if err:
                return self._send(400, {'error': err})
            broadcast({'t': 'macros'})
            return self._send(200, {'id': mid})
        if path == '/api/record/web':
            err = record_web(body.get('url', '').strip(), body.get('name', ''))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True})
        if path in ('/api/pick', '/api/inspect'):
            tool = 'pick' if path == '/api/pick' else 'inspect'
            title = '요소 찍기' if tool == 'pick' else '창·컨트롤 구조 보기'
            run, err = start_run('__%s__' % tool, {'title': body.get('title', '')}, {'kind': 'tool'},
                                 os.path.join(DIR_BUILTIN, 'pick.py' if tool == 'pick' else 'inspect_tree.py'),
                                 title, tool=True, timeout=120)
            return self._send(200 if run else 409, {'run': run.id} if run else {'error': err})
        if path == '/api/skin':                       # 펫과 허브 화면이 같이 쓰는 모습(스킨) — 허브가 한 곳에서 기억한다
            sid = body.get('skin') or None
            if sid is not None and not (re.fullmatch(r'[\w\-]+', str(sid)) and os.path.isfile(os.path.join(SKIN_DIR, str(sid), 'skin.json'))):
                return self._send(404, {'error': '없는 스킨입니다'})
            state['skin'] = sid
            save_state()
            broadcast({'t': 'skin', 'skin': sid})
            return self._send(200, {'ok': True, 'skin': sid})
        if path == '/api/theme':                      # 화면 모드 — 허브 화면·운영 화면·전용 창이 같이 따른다
            mode = body.get('mode')
            if mode not in UI_MODES:
                return self._send(400, {'error': '모드는 auto · light · dark 중 하나입니다'})
            state['theme'] = mode
            save_state()
            broadcast({'t': 'theme', 'mode': mode})
            return self._send(200, {'ok': True, 'mode': mode})
        if path == '/api/pet':
            ok = set_pet(bool(body.get('on')))
            return self._send(200 if ok else 409, {'ok': ok, 'on': bool(pet_pids())} if ok else {'error': 'pet 폴더에서 npm install 을 먼저 실행하세요'})
        if path == '/api/open':
            if body.get('which') == 'mail_settings':        # 운영 화면 ⚙ 설정 → 메일·계정 설정 창(setup_gui.py)
                pyw = os.path.join(os.path.dirname(PYTHON), 'pythonw.exe')
                gui = os.path.normpath(os.path.join(HERE, '..', '..', 'setup_gui.py'))
                subprocess.Popen([pyw if os.path.isfile(pyw) else PYTHON, gui], cwd=os.path.dirname(gui),
                                 creationflags=0x00000008)
                return self._send(200, {'ok': True})
            os.makedirs(DIR_LOCAL, exist_ok=True)
            os.startfile(DIR_LOCAL if body.get('which') == 'local' else DIR_EXAMPLE)
            return self._send(200, {'ok': True})
        self._send(404, {'error': 'not found'})

    def _sse(self):
        q = queue.Queue(maxsize=4000)
        with lock:
            subs.append(q)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b': connected\n\n')
            self.wfile.flush()
            while True:
                try:
                    self.wfile.write(('data: ' + q.get(timeout=15) + '\n\n').encode('utf-8'))
                except queue.Empty:
                    self.wfile.write(b': ping\n\n')
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with lock:
                if q in subs:
                    subs.remove(q)


def shutdown_children():
    for r in list(runs):
        if r.status == 'running' and r.proc:
            kill_tree(r.proc)
    if rec['proc'] and rec['proc'].poll() is None:
        kill_tree(rec['proc'])


def start_services(host='127.0.0.1', port=8630):
    """상태를 읽고 감시 스레드(창 이벤트·트리거·상시 매크로)를 띄운 뒤 HTTP 서버 객체를 돌려준다(serve_forever 는 부르는 쪽이)."""
    load_state()
    load_last_runs()
    os.makedirs(DIR_LOCAL, exist_ok=True)
    atexit.register(shutdown_children)

    def on_window(hwnd, kind):
        try:
            win_events.put_nowait((hwnd, kind))
        except queue.Full:
            pass

    try:
        winevents.WindowEvents(on_window).start()
    except OSError as e:
        print('창 이벤트 훅 실패 — 창 트리거가 동작하지 않습니다:', e, file=sys.stderr)
    threading.Thread(target=trigger_loop, daemon=True).start()
    threading.Thread(target=service_loop, daemon=True).start()

    if host in ('127.0.0.1', 'localhost'):
        Handler.allowed_hosts = frozenset(['127.0.0.1:%d' % port, 'localhost:%d' % port])
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser(description='매크로 허브 (콘솔 모드 — 트레이 앱은 app.py)')
    ap.add_argument('--port', type=int, default=8630)
    ap.add_argument('--host', default='127.0.0.1', help='기본은 이 PC 에서만. 바꾸지 않는 것을 권한다')
    ap.add_argument('--open', action='store_true')
    args = ap.parse_args()

    srv = start_services(args.host, args.port)
    url = 'http://127.0.0.1:%d/' % args.port
    print('매크로 허브 —', url, '(Ctrl+C 로 종료)')
    if PYTHON != VENV_PY:
        print('⚠ .venv 가 없어 시스템 파이썬으로 실행합니다 — setup.bat 을 먼저 실행하세요', file=sys.stderr)
    if sys.stdout:
        sys.stdout.flush()
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
