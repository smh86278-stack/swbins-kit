# -*- coding: utf-8 -*-
"""자동화 허브 — 회사 업무 화면 처리를 자동화로 돌리는 실시간 프로그램 (본인 전용, Windows).

    python macrohub.py                http://127.0.0.1:8630/
    python macrohub.py --port 8700 --open

하는 일
  - macros\\ (예제, git 에 들어감) · macros.local\\ (실제 업무 자동화, git 제외) 의 *.py 를 목록으로 보여 준다.
  - 자동화를 웹 화면 버튼으로 실행하고, 로그를 실시간으로 본다. 중지 버튼으로 프로세스 트리째 끈다.
  - 자동 실행 트리거: 프로세스가 뜰 때 · 창이 나타날 때 · 시간 예약. 자동화별로 켜야만 동작한다(기본 꺼짐).
  - 녹화: 웹은 playwright codegen, 데스크톱은 '요소 찍기'(마우스 아래 컨트롤 → 코드 조각).

자동화는 .venv 의 파이썬(runner.py)에서 별도 프로세스로 돈다 — 허브는 표준 라이브러리만 쓴다.
계정·비밀번호는 secrets.local.json 에 두고 자동화에서는 ctx.secret('키') 로 읽는다.
허브 화면은 이 PC(127.0.0.1)에서만 열리고, 실행 요청에는 토큰을 요구한다.
"""
import argparse
import ast
import atexit
import base64
import binascii
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
from urllib.parse import parse_qs, quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DIR_EXAMPLE = os.path.join(HERE, 'macros')
DIR_LOCAL = os.path.join(HERE, 'macros.local')
DIR_BUILTIN = os.path.join(HERE, 'builtin')
F_STATE = os.path.join(HERE, 'state.local.json')
F_RUNS = os.path.join(HERE, 'runs.jsonl')
RUNNER = os.path.join(HERE, 'runner.py')
EXPORTS = os.path.join(HERE, 'data.local', 'exports')     # ✨ 앱 exe 내보내기
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
DEFAULT_SKIN = 'plush'                        # 기본 모습(인형 강아지·고양이). 저장소에 들어 있다 — web/pets.js 의 PetSkin.DEFAULT 와 같게

TOKEN = secrets.token_urlsafe(24)
NO_WINDOW = 0x08000000

# 프로세스 스냅샷은 proc-live 와 같은 코드를 쓴다
_spec = importlib.util.spec_from_file_location('proc_live', os.path.join(HERE, '..', 'proc-live', 'proc-live.py'))
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)

sys.path.insert(0, HERE)
import alertmail  # noqa: E402
import hubutil  # noqa: E402  (redact — 로그 줄의 비밀값 가리기)
import apphost  # noqa: E402  (✨ 나만의 앱 — 8631, 앱마다 다른 출처)
import apphistory  # noqa: E402  (✨ 앱 버전·되돌리기)
import apppack  # noqa: E402  (✨ 앱 내보내기·가져오기 — zip · HTML 한 장 · exe)
import aicli  # noqa: E402  (AI 고르기 — Claude Code · Codex · Gemini CLI)
import kit  # noqa: E402  (변경 이력 kit.audit)
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


# 화면 꾸미기 — 색 테마·내 강조색·화면 펫 무대·촘촘하게. 허브가 state['look'] 에 기억하고 페이지를 줄 때 <html> 속성으로 심는다.
# 색은 theme.css 의 :root[data-theme=…], 내 색은 inline --accent·--accent2, 펫 무대는 index.html 의 [data-hero].
# basic(기본) · navy(진한 사이드바) · pastel(예전 모양). 2026-10 에 없앤 mint·mono·sunset 은 기본으로 읽는다. 펫 무대는 기본 숨김.
# cols·swap 은 예전 두 칸 배치용 — 지금 화면은 쓰지 않지만 저장된 값과 API 는 그대로 받는다.
LOOK_THEMES = ('basic', 'navy', 'pastel')
LOOK_DEFAULT = {'theme': 'basic', 'accent': '', 'accent2': '', 'hero': 'hide', 'cols': '2', 'swap': False, 'dense': False}
LOOK_CHOICES = {'theme': LOOK_THEMES, 'hero': ('show', 'small', 'hide'), 'cols': ('2', '1')}
HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


def look():
    lk = dict(LOOK_DEFAULT, **{k: v for k, v in (state.get('look') or {}).items() if k in LOOK_DEFAULT})
    for k, choices in LOOK_CHOICES.items():      # 없어진 테마 등 예전 값 — 기본으로
        if lk[k] not in choices:
            lk[k] = LOOK_DEFAULT[k]
    return lk


def clean_look(body):
    """POST /api/look 의 값 검사 — (새 look, 오류). 빠진 키는 지금 값 그대로."""
    cur = look()
    for k, v in (body or {}).items():
        if k not in LOOK_DEFAULT:
            continue
        if k in LOOK_CHOICES:
            if v not in LOOK_CHOICES[k]:
                return None, '%s 는 %s 중 하나입니다' % (k, ' · '.join(LOOK_CHOICES[k]))
        elif k in ('accent', 'accent2'):
            if v and not HEX_COLOR.match(str(v)):
                return None, '색은 #rrggbb 형식입니다'
            v = (v or '').lower()
        else:
            v = bool(v)
        cur[k] = v
    return cur, None


def look_attrs(lk=None):
    """<html> 에 붙일 속성 — data-theme·배치 + 내 색이면 style 의 --accent 한 쌍(다크는 조금 밝게)."""
    lk = lk or look()
    attrs = 'data-theme="%s" data-hero="%s" data-cols="%s" data-swap="%d" data-dense="%d"' % (
        lk['theme'], lk['hero'], lk['cols'], lk['swap'], lk['dense'])
    css = []
    for var, c in (('--accent', lk['accent']), ('--accent2', lk['accent2'])):
        if c:
            css.append('%s:light-dark(%s,color-mix(in srgb,%s 72%%,white))' % (var, c, c))
    if lk['accent']:
        c = lk['accent']
        css.append('--accentsoft:light-dark(color-mix(in srgb,%s 12%%,white),color-mix(in srgb,%s 22%%,#18191c))' % (c, c))
    return attrs + (' style="%s"' % ';'.join(css) if css else '')


def render_page(path):
    """화면 HTML — 실행 토큰·화면 모드·꾸미기를 심는다(<html data-mode="__MODE__">). 요청마다 읽으니 고치면 새로고침만으로 보인다."""
    with open(path, encoding='utf-8') as f:
        page = f.read().replace('__TOKEN__', TOKEN)
    return page.replace('data-mode="__MODE__"', 'data-mode="%s" %s' % (ui_mode(), look_attrs())).replace('__MODE__', ui_mode())


def save_state():
    try:
        with open(F_STATE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


# ---------------------------------------------------------------- 자동화 목록

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
    """자동화 목록. 예약 시각을 허브 화면에서 바꿨으면(state['schedule']) 그 값을 덧씌운다 —
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
            'steps': [str(s) for s in meta.get('steps') or [] if str(s).strip()],   # 쉬운 말 단계 — 카드에 보여 준다
            'kind': meta.get('kind', 'ctx'), 'target': meta.get('target', ''),
            'params': meta.get('params') or {}, 'triggers': meta.get('triggers') or [],
            'service': bool(meta.get('service')),
            'motion': default_motion(meta),
            'owns': meta.get('owns') or [],
            'chain': [str(s if isinstance(s, str) else (s or {}).get('id')) for s in meta.get('chain') or []
                      if not runner.is_ai_step(s)] if meta.get('kind') == 'chain' else [],   # 자동화 단계 id 만(🤖 AI 단계 빼고)
            'chain_raw': list(meta.get('chain') or []) if meta.get('kind') == 'chain' else [],
            'mode': runner.chain_mode(meta) if meta.get('kind') == 'chain' else '',
            'keep_going': bool(meta.get('keep_going')),
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
        self.motion_default = None       # 일반 자동화는 META 의 일 종류, 상시 자동화는 None(평소엔 지켜보기만)
        self.motion = None
        self.motion_until = None         # ctx.motion(hold=) 로 잠깐만 보일 때 끝나는 시각(ms)
        self.shot = None                 # 📸 실패한 순간 화면(data.local\failshots\*.png) — runner 의 '@@failshot' 줄
        self.parent = None               # 🔗 묶음 단계로 돈 실행이면 그 묶음의 Run (proc 은 묶음 것)
        self.step = None                 # 🔗 묶음이면 지금 도는 단계의 Run
        self.confirm = None              # 🙋 묶음이 사람 확인을 기다리는 중이면 {token, name, text} — runner 의 '@@confirm' 줄

    def summary(self):
        # 📸 화면 파일은 오래되면 지워진다(60장 넘으면 정리) — 없는 파일을 가리키면 깨진 그림 대신 표시하지 않는다
        shot = self.shot if self.shot and os.path.isfile(self.shot) else None
        wait = self.confirm if self.confirm and self.status == 'running' else None
        return {'id': self.id, 'macro': self.macro, 'name': self.name, 'trigger': self.trigger.get('kind', 'manual'),
                'detail': self.trigger.get('detail', ''), 'started': int(self.started * 1000),
                'ended': int(self.ended * 1000) if self.ended else None,
                'status': self.status, 'code': self.code, 'tool': self.tool,
                'shot': os.path.basename(shot) if shot else None,
                'confirm': {'name': wait['name'], 'text': wait['text']} if wait else None}


runs = deque(maxlen=300)
runs_by_id = {}
last_fire = {}


def running_run(macro_id):
    with lock:
        return next((r for r in runs if r.macro == macro_id and r.status == 'running'), None)


def busy_text(r):
    """겹쳐 돌리려 할 때의 거절 말 — 묶음 단계로 도는 중이면 어느 묶음인지."""
    if r.parent:
        return '이미 실행 중입니다 — 일 순서 「%s」의 단계로 도는 중이에요. 끝난 뒤 다시 돌리세요' % r.parent.name
    return '이미 실행 중입니다'


def kill_tree(proc):
    try:
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW)
    except OSError:
        pass


def start_run(macro_id, params=None, trigger=None, path=None, name=None, tool=False, timeout=600, motion=None, extra=None):
    trigger = trigger or {'kind': 'manual'}
    busy = running_run(macro_id)
    if busy and not tool:
        return None, busy_text(busy)
    run = Run(macro_id, name or macro_id, trigger, tool)
    run.motion = run.motion_default = motion
    ctx = dict(extra or {}, macro=macro_id, params=params or {}, trigger=trigger)
    if trigger.get('kind') == 'test':
        ctx['dry_run'] = True                    # 시험 실행 — ctx.for_real() 로 감싼 동작은 건너뛴다(runner.py --test 와 같게)
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONUNBUFFERED='1',
               MACROHUB_CTX=json.dumps(ctx, ensure_ascii=False))
    try:
        run.proc = subprocess.Popen([PYTHON, '-u', RUNNER, path], cwd=HERE, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    except OSError as e:
        return None, '실행 실패: %s' % e
    with lock:
        runs.append(run)
        runs_by_id[run.id] = run
    broadcast({'t': 'run', 'run': run.summary()})
    run.pump = threading.Thread(target=_pump, args=(run,), daemon=True)
    run.pump.start()
    threading.Thread(target=_watch, args=(run, timeout), daemon=True).start()
    return run, None


AI_TIMEOUT = 1800     # 말로 부탁하기·고쳐 달라기를 Codex·Gemini 로 직접 돌릴 때 — 만들고 시험하고 고치기(최대 3번)에 넉넉히


def start_ai_run(what, prompt, app_id=None, check=True):
    """🛠 말로 부탁하기 · 🩹 고쳐 달라기 · ✨ 앱 만들기를 고른 AI(codex·gemini·ollama)로 허브 폴더에서 직접 돌린다 — 진행은 실행 기록·로그로 본다.
    도구 실행(tool)이라 실행 기록 파일·실패 알림 메일에는 넣지 않는다. 프롬프트는 표준 입력으로.
    app_id 가 있으면 로컬 AI 는 그 앱 폴더만 고치고, 스스로 검사를 못 돌리는 AI 가 끝나면 허브가 🔍 검사를 이어 돌린다.
    Codex 는 샌드박스(허브 폴더 안만 쓰기)라 크롬이 임시 폴더에 못 써 검사가 막힐 수 있어 늘 허브가 한 번 더 검사한다."""
    s = aicli.settings()
    argv, shell, note = aicli.agent_cmd(s['engine'], HERE, s)
    if app_id and s['engine'] == 'ollama':
        argv += ['--app', app_id] + ([] if check else ['--only', 'spec.md'])
    run = Run('ai:' + what, '%s — %s' % (what, aicli.NAMES[s['engine']]), {'kind': 'ai'}, tool=True)
    if app_id:
        hub_checks = check and (s['engine'] == 'codex' or (s['engine'] == 'gemini' and s['gemini_approval'] != 'yolo')
                                or (s['engine'] == 'ollama' and not s['ollama_test']))

        def after():
            app_snapshot(app_id, '%s 뒤 (%s)' % (what, run.status))     # 실패·멈춤이어도 무엇을 바꿨는지 남긴다
            if hub_checks and run.status == 'ok':
                start_app_check(app_id)
        run.after = after
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}
    try:
        run.proc = subprocess.Popen(argv, cwd=HERE, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW, shell=shell)
    except OSError as e:
        raise RuntimeError('%s 를 띄우지 못했습니다: %s' % (aicli.NAMES[s['engine']], e))
    if note:
        run.lines.append('ℹ ' + note)

    def feed():
        try:
            run.proc.stdin.write(aicli.agent_prompt(s['engine'], prompt, s).encode('utf-8'))
            run.proc.stdin.close()
        except OSError:
            pass
    with lock:
        runs.append(run)
        runs_by_id[run.id] = run
    broadcast({'t': 'run', 'run': run.summary()})
    threading.Thread(target=feed, daemon=True).start()
    threading.Thread(target=_pump, args=(run,), daemon=True).start()
    threading.Thread(target=_watch, args=(run, AI_TIMEOUT), daemon=True).start()
    audit('AI 에게 맡김', what, aicli.NAMES[s['engine']])
    return run


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


def _step_start(run, info):
    """🔗 묶음이 단계를 시작했다 — 그 자동화도 '실행 중'으로 보이게(겹쳐 돌리기 거절·카드의 실행 중 표시) 단계 Run 을 만든다."""
    _step_end(run, {'status': 'stopped'})            # 끝 줄을 못 받은 앞 단계가 남아 있으면 닫는다
    sid = info.get('id')
    if not isinstance(sid, str) or not runner.CHAIN_ID.match(sid):
        return
    m = find_macro(sid)
    test = run.trigger.get('kind') == 'test'
    step = Run(sid, (m or {}).get('name') or info.get('name') or sid,
               {'kind': 'test' if test else 'chain', 'detail': '일 순서 「%s」 %s/%s 단계' % (run.name, info.get('i', '?'), info.get('n', '?')),
                'chain': run.macro})
    step.parent = run
    run.step = step
    with lock:
        runs.append(step)
        runs_by_id[step.id] = step
    broadcast({'t': 'run', 'run': step.summary()})


def _step_end(run, info):
    """🔗 단계가 끝났다 — 결과를 그 자동화의 마지막 실행으로 남긴다(runs.jsonl 에도. 실패 알림 메일은 묶음 쪽이 보낸다)."""
    step = run.step
    if not step:
        return
    run.step = None
    step.ended = time.time()
    step.code = info.get('code')
    st = info.get('status')
    step.status = st if st in ('ok', 'fail', 'timeout', 'stopped') else 'fail'
    _record(step, alert=False)
    broadcast({'t': 'run', 'run': step.summary()})


def _pump(run):
    for raw in iter(run.proc.stdout.readline, b''):
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        if line.startswith(MOTION_PREFIX):
            _set_motion(run, line[len(MOTION_PREFIX):])
            continue
        if line.startswith(runner.STEP_PREFIX):          # 🔗 묶음 단계 시작·끝 — 로그에는 안 남긴다(사람이 읽는 줄은 runner 가 따로 냈다)
            try:
                info = json.loads(line[len(runner.STEP_PREFIX):])
            except ValueError:
                continue
            if isinstance(info, dict):
                (_step_start if info.get('state') == 'start' else _step_end)(run, info)
            continue
        if line.startswith(runner.FAILSHOT_PREFIX):     # 📸 — runner 가 사람이 읽는 줄은 따로 냈다
            shot = failshot_file(os.path.basename(line[len(runner.FAILSHOT_PREFIX):].strip()))
            if shot:
                run.shot = shot
                if run.step:
                    run.step.shot = shot
            continue
        if line.startswith(runner.CONFIRM_PREFIX):     # 🙋 묶음이 사람 확인을 기다린다 — 실행 카드에 「계속」·「멈춤」, 알림도
            try:
                c = json.loads(line[len(runner.CONFIRM_PREFIX):])
                run.confirm = {'token': str(c['token']), 'name': str(c.get('name') or ''),
                               'text': hubutil.redact(str(c.get('text') or ''))}
            except (ValueError, KeyError, TypeError):
                continue
            broadcast({'t': 'run', 'run': run.summary()})
            broadcast({'t': 'notify', 'title': '🙋 확인해 주세요 — %s' % run.name,
                       'text': '「%s」 결과를 보고 계속할지 골라 주세요' % run.confirm['name'], 'level': 'warning', 'macro': run.name})
            continue
        if line.startswith(runner.RESULT_PREFIX):      # ctx.result() — 묶음 밖에서 돌면 사람이 읽는 줄로만
            try:
                line = '📋 결과: ' + str(json.loads(line[len(runner.RESULT_PREFIX):]).get('text', ''))
            except (ValueError, AttributeError):
                continue
        if line.startswith(NOTIFY_PREFIX):          # ctx.notify() — 알림으로 바꾸고 로그에는 사람이 읽는 형태로 남긴다
            try:
                n = json.loads(line[len(NOTIFY_PREFIX):])
                line = '🔔 %s — %s' % (n.get('title', ''), n.get('text', ''))
                broadcast({'t': 'notify', 'title': n.get('title', ''), 'text': n.get('text', ''),
                           'level': n.get('level', 'info'), 'macro': run.name})
            except ValueError:
                pass
        line = hubutil.redact(line)                 # 비밀값 가리기 — 화면·runs.jsonl·실패 알림·웹훅·고쳐 달라기 모두 이 줄을 쓴다
        line = hubutil.short_paths(line, PYTHON)    # 이 PC 의 파이썬·키트 폴더 절대 경로 줄이기(파일 이름·줄 번호는 그대로)
        run.lines.append(line)
        broadcast({'t': 'log', 'run': run.id, 'line': line})
        if run.step:                                # 묶음 단계 로그는 단계 실행 기록에도(들여쓰기 빼고)
            sl = line[3:] if line.startswith('   ') else line
            run.step.lines.append(sl)
            broadcast({'t': 'log', 'run': run.step.id, 'line': sl})


def _watch(run, timeout):
    try:
        run.code = run.proc.wait(timeout=timeout or None)
    except subprocess.TimeoutExpired:
        run.lines.append('⏱ 제한 시간(%d초)을 넘겨 중지합니다' % timeout)
        broadcast({'t': 'log', 'run': run.id, 'line': run.lines[-1]})
        run.status = 'timeout'
        kill_tree(run.proc)
        run.code = run.proc.wait()
    if getattr(run, 'pump', None):               # 마지막 줄(📸 '@@failshot' 등)까지 읽은 뒤에 기록·알림을 남긴다
        run.pump.join(timeout=3)
    run.ended = time.time()
    run.confirm = None
    if run.status == 'running':
        run.status = 'stopped' if run.stopping else ('ok' if run.code == 0 else 'fail')
    if run.step:                                 # 묶음이 단계 도중에 멈춤·시간 초과로 끝났다 — 그 단계도 같이 닫는다
        _step_end(run, {'status': 'timeout' if run.status == 'timeout' else 'stopped', 'code': run.code})
    if getattr(run, 'after', None):              # 끝난 뒤 이어서 할 일(예: 앱을 만든 AI 가 스스로 검사 못 하면 허브가 검사)
        threading.Thread(target=run.after, daemon=True).start()
    _record(run)
    broadcast({'t': 'run', 'run': run.summary()})


def answer_confirm(run_id, ok):
    """🙋 묶음 확인에 답한다 — runner 가 기다리는 data.local\\confirm\\<토큰>.json 에 {"ok"} 를 쓴다. 오류 글 또는 None."""
    run = runs_by_id.get(run_id)
    c = run.confirm if run and run.status == 'running' else None
    path = runner.confirm_file(c['token']) if c else None
    if not path:
        return '확인을 기다리는 실행이 아닙니다 (이미 답했거나 끝났습니다)'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'ok': bool(ok)}, f)
    os.replace(tmp, path)                        # runner 가 반쯤 쓴 파일을 읽지 않게
    run.confirm = None
    audit('일 순서 확인', run.macro, '%s — %s' % (c['name'], '계속' if ok else '멈춤'))
    broadcast({'t': 'run', 'run': run.summary()})
    return None


def _record(run, alert=True):
    """끝난 실행을 runs.jsonl 에 남기고(허브를 다시 켜도 '마지막 실행'이 보이게) 실패면 알림 메일. 시험·도구 실행은 빼고."""
    if run.trigger.get('kind') == 'test':        # 시험 실행은 실행 기록·실패 알림 메일에 넣지 않는다 — 화면 로그로만 본다
        ok = run.status == 'ok'
        run.lines.append('🧪 시험 결과: %s' % ('성공' if ok else '실패 — 위 로그를 보고 고치세요'))
        broadcast({'t': 'log', 'run': run.id, 'line': run.lines[-1]})
    elif not run.tool:
        rec = dict(run.summary(), tail=list(run.lines)[-30:])
        if run.shot:
            rec['shot_file'] = run.shot              # 실패 알림 메일이 붙인다(alertmail.deliver)
        try:
            with open(F_RUNS, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        except OSError:
            pass
        LAST_RUN[run.macro] = {k: v for k, v in rec.items() if k != 'tail'}
        if alert and run.status in alertmail.ALERT_STATUS:
            threading.Thread(target=_alert_mail, args=(rec,), daemon=True).start()


FAILSHOT_NAME = re.compile(r'^[\w\-]+\.png$')


def failshot_file(name):
    """📸 파일 이름 → data.local\\failshots 바로 아래의 실제 경로(없거나 이상한 이름이면 None — 경로 탈출 막기)."""
    if not isinstance(name, str) or not FAILSHOT_NAME.match(name):
        return None
    path = os.path.join(runner.FAILSHOT_DIR, name)
    return path if os.path.isfile(path) else None


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
    if run and run.parent and run.status == 'running':
        run = run.parent                         # 🔗 묶음 단계는 따로 끌 프로세스가 없다 — 묶음째 멈춘다
    if not run or run.status != 'running' or not run.proc:
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


_via = threading.local()


def set_via(where):
    """이 스레드에서 일어나는 변경의 출처(변경 이력의 '어디서') — HTTP 는 '화면 /ops', 트레이는 '트레이'. 안 정하면 '허브'."""
    _via.v = where


def audit(action, target='', detail=''):
    m = find_macro(target) if target else None
    kit.audit(action, target, detail, via=getattr(_via, 'v', None) or '허브', name=(m or {}).get('name') or '')
    broadcast({'t': 'audit'})


def sched_text(triggers):
    """예약 트리거 → '09:30 daily · 매 1h' (변경 이력용)."""
    out = []
    for t in triggers or []:
        if t.get('type') != 'schedule':
            continue
        out.append(('매 %s' % t['every']) if t.get('every') else '%s %s' % (t.get('at', '?'), t.get('days') or 'daily'))
    return ' · '.join(out) or '없음'


def set_enabled(mid, on):
    """상시 자동화·예약 자동화 켜기/끄기. 상시 자동화를 끄면 지키던 바깥 프로그램까지 멈춘다."""
    m = find_macro(mid)
    if not m:
        return False
    was = bool(state['enabled'].get(mid))
    state['enabled'][mid] = bool(on)
    save_state()
    if was != bool(on):
        audit(('켬' if on else '끔') + (' (상시 서비스)' if m['service'] else ' (예약 작업)'), mid)
    if not on and m['service']:
        r = running_run(mid)
        if r:
            stop_run(r.id)
        stop_owned(m)
    broadcast({'t': 'macros'})
    return True


HIDE_TOOLS = ('tool:new', 'tool:record', 'tool:desktop')   # 허브 화면 '만들기 · 녹화 · 도구' 칸 — 자동화처럼 숨길 수 있다


def hidden_ids():
    return set(state.get('hidden') or [])


def set_hidden(mid, on):
    """안 쓰는 자동화·도구를 허브·운영 화면 목록에서 숨기기/다시 보이기 — 지우지도 끄지도 않는다(state.local.json 'hidden').
    켜져 있는(돌고 있는) 상시·예약 자동화는 숨기지 않는다 — 돌면서 안 보이면 헷갈린다. 돌려주는 값: 오류 문구 또는 None"""
    m = find_macro(mid) if mid not in HIDE_TOOLS else None
    if not m and mid not in HIDE_TOOLS:
        return '없는 자동화입니다'
    if on and m and state['enabled'].get(mid):
        return '켜져 있는 것은 숨길 수 없습니다 — 먼저 끄세요'
    ids = hidden_ids()
    if on == (mid in ids):
        return None
    ids = ids | {mid} if on else ids - {mid}
    state['hidden'] = sorted(ids)
    save_state()
    audit('숨김' if on else '다시 보임', mid)
    broadcast({'t': 'macros'})
    return None


DIR_DELETED = os.path.join(HERE, 'data.local', 'deleted')   # 지운 내 자동화 — 되살릴 수 있게 여기로 옮긴다


def delete_macro(mid):
    """내 자동화(macros.local) 지우기 — 파일을 data.local\\deleted\\<이름>-<시각>.py 로 옮기고 켜짐·숨김·예약 기록을 지운다.
    키트 예제·꺼지지 않은 것·도는 중인 것은 지우지 않는다. 돌려주는 값: (옮긴 파일 이름, 오류 문구)"""
    m = find_macro(mid)
    if not m:
        return None, '없는 자동화입니다'
    if not m.get('local'):
        return None, '내 자동화만 지울 수 있습니다 — 예제는 숨기기를 쓰세요'
    if state['enabled'].get(mid):
        return None, '켜져 있는 것은 지울 수 없습니다 — 먼저 끄세요'
    if running_run(mid):
        return None, '실행 중에는 지울 수 없습니다'
    stem = os.path.splitext(os.path.basename(m['path']))[0]
    fname = '%s-%s.py' % (stem, time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(DIR_DELETED, exist_ok=True)
    try:
        os.replace(m['path'], os.path.join(DIR_DELETED, fname))
    except OSError as e:
        return None, '지우지 못했습니다: %s' % e
    state['enabled'].pop(mid, None)
    (state.get('schedule') or {}).pop(mid, None)
    (state.get('params') or {}).pop(mid, None)
    if mid in hidden_ids():
        state['hidden'] = sorted(hidden_ids() - {mid})
    save_state()
    audit('자동화 지움', mid, '「%s」 → data.local\\deleted\\%s' % (m['name'], fname))   # 파일을 옮긴 뒤라 이름을 못 찾으니 여기 적는다
    broadcast({'t': 'macros'})
    return fname, None


def deleted_macros():
    """지운 내 자동화 목록 — 새것 먼저 [{"file", "name", "when"}]"""
    try:
        names = [n for n in os.listdir(DIR_DELETED) if n.endswith('.py')]
    except OSError:
        return []
    out = []
    for n in names:
        mt = re.match(r'^(.*)-(\d{8}-\d{6})\.py$', n)
        meta = runner.read_meta(os.path.join(DIR_DELETED, n)) or {}
        out.append({'file': n, 'name': mt.group(1) if mt else n[:-3], 'title': meta.get('name') or '',
                    'when': time.strftime('%Y-%m-%d %H:%M', time.strptime(mt.group(2), '%Y%m%d-%H%M%S')) if mt else ''})
    return sorted(out, key=lambda d: d['file'][-18:], reverse=True)


def restore_macro(fname):
    """지운 자동화 되살리기 — 원래 이름으로 macros.local 에 돌려놓는다(꺼진 채). 돌려주는 값: (자동화 id, 오류 문구)"""
    item = next((d for d in deleted_macros() if d['file'] == fname), None)   # 목록에 있는 이름만 — 경로 조작 막기
    if not item:
        return None, '지운 목록에 없습니다'
    dest = os.path.join(DIR_LOCAL, item['name'] + '.py')
    if os.path.exists(dest):
        return None, '같은 이름의 자동화가 이미 있습니다 — 그것을 먼저 지우거나 이름을 바꾸세요'
    os.makedirs(DIR_LOCAL, exist_ok=True)
    try:
        os.replace(os.path.join(DIR_DELETED, fname), dest)
    except OSError as e:
        return None, '되살리지 못했습니다: %s' % e
    mid = 'local/' + item['name']
    audit('자동화 되살림', mid, '← data.local\\deleted\\' + fname)
    broadcast({'t': 'macros'})
    return mid, None


def service_action(mid, action):
    """운영 화면·트레이의 시작/중지/재시작/지금 실행. 돌려주는 값: (ok, 안내 문구)"""
    m = find_macro(mid)
    if not m:
        return False, '허브에 없는 자동화: %s' % mid
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
            audit('다시 띄움', mid, ('끈 PID %s' % ', '.join(map(str, killed))) if killed else '')
            return True, '%s — 다시 띄웁니다%s' % (m['name'], ' (끈 PID %s)' % ', '.join(map(str, killed)) if killed else '')
        action = 'run'
    if action == 'run':
        if m['service']:
            return service_action(mid, 'restart')
        run, err = run_macro(mid, None, {'kind': 'manual', 'detail': '지금 실행'})
        audit('지금 실행', mid, '' if run else '실패: %s' % err)
        return (True, '%s — 실행했습니다' % m['name']) if run else (False, err)
    return False, '알 수 없는 동작: %s' % action


def run_macro(macro_id, params=None, trigger=None):
    m = find_macro(macro_id)
    if not m:
        return None, '자동화를 찾을 수 없습니다'
    if (trigger or {}).get('kind') == 'test' and (not m['local'] or m['service']):
        # 기본 자동화는 for_real 로 감싸지 않아 시험이어도 진짜 메일·서버에 닿는다
        return None, '시험 실행은 내 자동화(상시 자동화 제외)만 됩니다'
    merged = {k: v for k, v in m['params'].items()}
    merged.update(saved_params(m))                   # 카드에서 💾 기억한 값 — 예약 실행도 이 값으로
    merged.update({k: v for k, v in (params or {}).items() if k in m['params'] or not m['params']})
    name = m['name'] + (' 🧪시험' if (trigger or {}).get('kind') == 'test' else '')
    extra = None
    if m['kind'] == 'chain':                         # 🔗 묶음 — 단계마다 기억한 값을 runner 에 넘긴다(runner 는 state 를 읽지 않는다)
        for sid in m['chain']:                       # 단계가 이미 따로 돌고 있으면 그 단계에서 프로필 잠금으로 깨진다 — 미리 거절
            busy = running_run(sid)
            if busy and running_run(m['id']) is None:
                return None, '단계 「%s」가 이미 실행 중이라 일 순서를 시작하지 않았습니다 — 끝난 뒤 다시 돌리세요' % busy.name
        extra = {'chain_params': {sid: saved_params(find_macro(sid)) for sid in m['chain'] if find_macro(sid)}}
    return start_run(m['id'], merged, trigger, m['path'], name, timeout=m['timeout'],
                     motion=None if m['service'] else m['motion'], extra=extra)


def saved_params(m):
    """카드에서 기억한 입력값(state['params'][id]) — META params 에 있는 칸만."""
    if not m:
        return {}
    keep = (state.get('params') or {}).get(m['id']) or {}
    return {k: v for k, v in keep.items() if k in m['params']}


def _like(default, text):
    """칸 글자를 기본값과 같은 꼴로 — 숫자·참거짓 기본값이면 그 꼴로 읽고, 아니면 글자 그대로."""
    if isinstance(default, str) or not isinstance(text, str):
        return text
    try:
        v = json.loads(text)
    except ValueError:
        return text
    return v if isinstance(v, type(default)) or (isinstance(default, (int, float)) and isinstance(v, (int, float))) else text


def save_params(mid, values):
    """💾 이 값 기억 — 카드의 입력값을 state['params'] 에 남긴다. 기본값과 같은 칸은 빼고, 다 같으면 지운다. (기억한 값, 오류)"""
    m = find_macro(mid)
    if not m:
        return None, '없는 자동화입니다'
    if not m['params']:
        return None, '바꿀 칸이 없는 자동화입니다'
    if not isinstance(values, dict):
        return None, 'params 는 {이름: 값} 이어야 합니다'
    keep = {}
    for k, v in values.items():
        if k in m['params']:
            v = _like(m['params'][k], v)
            if v != m['params'][k]:
                keep[k] = v
    allp = state.setdefault('params', {})
    if keep:
        allp[mid] = keep
    else:
        allp.pop(mid, None)
    save_state()
    audit('입력값 기억' if keep else '입력값 기본으로', mid, ', '.join(sorted(keep)))
    broadcast({'t': 'macros'})
    return keep, None


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
SCHED_LAST = {}                      # (자동화 id, 'every' 값) → 마지막으로 쏜 시각. 간격을 바꾸면 새로 센다


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
    """예약 화면용 — 예약 트리거가 있는 자동화(상시 자동화 제외)."""
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
                    'running': v['running'], 'last': v['last'], 'schedule': sched, 'hidden': v['hidden'], 'local': m['local'],
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
    """이 자동화가 ts(epoch 초) 이후에 시작된 적이 있나 — 지금 허브의 실행 + 허브가 뜨기 전 기록(runs.jsonl)."""
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


# ---------------------------------------------------------------- 상시 자동화 (service)

def service_loop():
    """켜 둔 상시 자동화(META["service"]=True)가 죽어 있으면 다시 살린다. 연달아 바로 죽으면 간격을 늘린다(최대 60초)."""
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


# ---------------------------------------------------------------- 녹화 · 새 자동화

TEMPLATE_WEB = '''# -*- coding: utf-8 -*-
META = {
    "name": %(name)s,
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
    "name": %(name)s,
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
        # 이름은 파이썬 문자열 리터럴로 넣는다 — 따옴표·줄바꿈이 든 이름이 만들어지는 .py 에 코드로 끼어들지 않게
        f.write((TEMPLATE_DESKTOP if kind == 'desktop' else TEMPLATE_WEB) % {'name': json.dumps(name.strip(), ensure_ascii=False)})
    return 'local/' + stem, None


rec = {'proc': None}


CHAT_URL = 'http://127.0.0.1:%d' % int(os.environ.get('DISPATCH_CHAT_PORT') or 8620)   # 디스패치 대화(tools\dispatch-chat) — 같은 환경변수로 포트를 바꾼다


AUTHORING = os.path.join(HERE, 'AUTHORING.md')   # Claude 가 자동화를 만들고·시험하고·고칠 때 따르는 안내서


def test_python():
    """시험 실행(runner.py --test)에 쓸 파이썬 — 허브를 돌리는 그 파이썬(트레이는 pythonw 라 콘솔판 python 으로)."""
    exe = sys.executable or 'python'
    con = os.path.join(os.path.dirname(exe), 'python.exe')
    return con if os.path.basename(exe).lower() == 'pythonw.exe' and os.path.isfile(con) else exe


def build_steps():
    """말로 부탁하기·고쳐 달라기 공통 — 안내서·시험 명령·'만들기 → 시험 → 고치기(최대 3번) → 쉬운 말 보고'."""
    return ('먼저 %s 를 읽고 그 순서대로 해 줘 — 만들기 → 시험 실행으로 확인 → 실패하면 고쳐서 다시(최대 3번) → 쉬운 말로 보고.\n'
            '시험 실행: cd "%s" 한 뒤 "%s" runner.py --test macros.local\\<파일>.py\n'
            '(되돌릴 수 없는 동작 — 메일 보내기·제출·삭제 — 은 ctx.for_real(...) 로 감싸 시험 때는 건너뛰게. 비밀번호는 ctx.secret 으로, 값은 내가 넣을게)'
            % (AUTHORING, HERE, test_python()))


def ask_prompt(what, when=''):
    """🛠 「말로 부탁하기」 부탁 글 — 화면이 아니라 허브가 만든다(안내서·시험 파이썬 경로를 정확히 넣으려고)."""
    what = (what or '').strip()
    if not what:
        raise ValueError('무엇을 해 줄지 적어 주세요')
    return ('자동화 허브에 자동화 만들어줘 — %s%s\n'
            '(여러 가지 일을 적었으면 일마다 자동화를 따로 만들어 줘 — 한 일 안의 조건 분기는 하나로)\n%s'
            % (what, ('\n언제: %s 자동 실행' % when.strip()) if (when or '').strip() else '', build_steps()))


def chat_mismatch(state):
    """그 포트의 대화 앱이 이 키트의 메일함으로 보내는가 — 아니면 이유(보내지 않는다), 맞으면 ''.
    같은 PC 에 다른 메신저(다른 계정·다른 게이트웨이)가 8620 을 쓰고 있으면 부탁이 그쪽 게이트웨이의 기본 작업 폴더에서
    돌아 버린다(2026-10-23 실측: 키트 앱 만들기 부탁이 남의 메신저로 갈 뻔했다). 키트 게이트웨이가 읽는 mail.user 와 대화 앱의 계정이 같아야 한다."""
    mine = str((kit.section('mail', {}) or {}).get('user') or '').strip().lower()
    theirs = str(state.get('user') or '').strip().lower()
    if not mine:
        return '키트 메일 계정(mail.user)이 없어 디스패치로 보낼 수 없습니다 — 설정을 마치거나 AI 를 Codex·Gemini·Ollama 로 고르세요'
    if theirs != mine:
        return ('%s 의 대화 앱이 이 키트 계정(%s)이 아니라 %s 로 보냅니다 — 다른 메신저가 그 포트를 쓰고 있어요. '
                '키트 대화는 환경변수 DISPATCH_CHAT_PORT 로 다른 포트에 띄우세요' % (CHAT_URL, mine, theirs or '(설정 없음)'))
    return ''


def ask_chat(text):
    """🛠 만들기 「말로 부탁하기」 — 부탁 글을 디스패치 대화로 바로 보낸다(쓰기 지시, 작업 폴더 hub 가 있으면 거기).
    대화 앱 POST 는 시작할 때마다 새로 만드는 토큰을 화면(GET /)에만 심어 둔다 — 같은 PC 의 허브가 그 화면을 읽어 토큰을 얻는다.
    다른 웹 페이지는 교차 출처라 화면을 못 읽으니 막힌 그대로다. 허브 /api/ask 도 허브 토큰이 있어야 한다."""
    import urllib.error
    import urllib.request
    text = (text or '').strip()
    if not text:
        raise ValueError('무엇을 해 줄지 적어 주세요')
    try:
        with urllib.request.urlopen(CHAT_URL + '/', timeout=3) as r:
            page = r.read().decode('utf-8', 'replace')
        with urllib.request.urlopen(CHAT_URL + '/api/state', timeout=3) as r:
            state = json.loads(r.read().decode('utf-8'))
    except OSError:
        raise RuntimeError('디스패치 대화가 꺼져 있습니다 — 설정 dispatch.enabled 를 켜고 허브를 다시 시작하세요')
    why = chat_mismatch(state)
    if why:
        raise RuntimeError(why)
    folders = state.get('folders') or []
    m = re.search(r"const TOKEN = '([^']+)'", page)
    if not m:
        raise RuntimeError('대화 화면에서 접속 토큰을 찾지 못했습니다')
    data = {'text': text, 'mode': 'write', 'folder': 'hub' if 'hub' in folders else ''}
    req = urllib.request.Request(CHAT_URL + '/api/send', data=json.dumps(data, ensure_ascii=False).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Token': m.group(1)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError('대화 앱이 받지 않았습니다: %s' % (e.read().decode('utf-8', 'replace')[:200] or e.code))
    except OSError as e:
        raise RuntimeError('대화 앱으로 보내지 못했습니다: %s' % e)
    if not res.get('ok'):
        raise RuntimeError(res.get('error') or '대화 앱이 보내지 못했습니다')
    audit('말로 부탁하기 보냄', '', text.splitlines()[0][:80])
    return {'ok': True, 'subject': res.get('subject', '')}


FIX_TAIL = 40      # 🩹 고쳐 달라기에 붙일 로그 끝 줄 수


def fix_text(run_id):
    """🩹 고쳐 달라기 — 실패한 실행 하나를 Claude 에게 넘길 부탁 글(자동화 이름·파일·결과·로그 끝).
    녹화로 만든 자동화는 사이트 화면이 바뀌면 요소를 못 찾아 깨진다 — 그 실패를 그대로 넘겨 고치게 한다.
    내 자동화(macros.local)만 — 키트가 준 예제는 업데이트로 덮이니 고치지 않는다."""
    try:
        r = runs_by_id.get(int(run_id or 0))
    except (TypeError, ValueError):
        r = None
    if not r:
        raise ValueError('없는 실행입니다')
    if r.status not in ('fail', 'timeout'):
        raise ValueError('실패한 실행만 고쳐 달랄 수 있습니다')
    m = find_macro(r.macro)
    if not m or not m.get('local'):
        raise ValueError('내 자동화(내 자동화 폴더의 파일)만 고쳐 달랄 수 있습니다')
    tail = [str(x) for x in list(r.lines)[-FIX_TAIL:]]
    when = time.strftime('%Y-%m-%d %H:%M', time.localtime(r.started))
    return ('자동화 허브의 자동화가 실패했어 — 원인을 찾아 고쳐줘.\n'
            '자동화: %s\n파일: %s\n결과: %s (%s 실행%s)\n'
            '로그 끝 %d줄:\n%s\n%s'
            '(사이트 화면이 바뀌어 요소를 못 찾은 거면 그 화면을 열어 보고 선택자를 고쳐 줘. 이 파일 말고는 고치지 마. '
            '로그인 만료·네트워크처럼 코드 밖 문제면 고치지 말고 그렇다고 알려 줘)\n%s'
            % (m['name'], m['path'], '시간 초과' if r.status == 'timeout' else '오류', when,
               ', 종료 코드 %s' % r.code if r.code not in (None, 0) else '', len(tail), '\n'.join(tail) or '(로그 없음)',
               ('실패한 순간 화면: %s — 먼저 열어 봐 줘\n' % r.shot) if r.shot else '',
               build_steps()))


APP_AUTHORING = os.path.join(HERE, 'APP_AUTHORING.md')


def app_check_cmd(app_id):
    return '"%s" appcheck.py %s' % (test_python(), app_id)


def app_prompt(step, app, what=''):
    """✨ 나만의 앱 부탁 글 — step: spec(설계서만) · build(설계서대로 만들기) · change(말로 고치기·기능 추가)."""
    rel = 'apps.local\\%s' % app['id']
    head = ('먼저 %s 를 읽고 따라 줘. 대상은 나만의 앱 「%s」 — 폴더 %s\\%s (주소 %s). 이 폴더 밖은 고치지 마.\n'
            % (APP_AUTHORING, app['name'], HERE, rel, apphost.url(app['id'], APPS_PORT)))
    check = ('검사: cd "%s" 한 뒤 %s — 실패하면 고쳐서 다시(최대 3번), 스크린샷 %s\\.check\\check.png 도 봐 줘.\n'
             '마지막에 쉬운 말로 보고 — 무엇을 만들었나 · 쓰는 법 · 허브에서 허락할 권한 · 검사 결과 · 남은 한계.'
             % (HERE, app_check_cmd(app['id']), rel))
    if step == 'spec':
        return (head + '나만의 앱 설계서를 써 줘 — %s\\spec.md 만 고치고 코드는 아직 건드리지 마.\n'
                '안내서의 설계서 형식(목적·화면·데이터·동작·완료 기준)대로, 지금 폴더의 템플릿 구조를 살려서.\n'
                '부탁: %s\n다 쓰면 설계서 요점을 5줄로 알려 주고 멈춰 — 내가 확인한 뒤 「만들기」를 누른다.'
                % (rel, (what or '').strip() or '(부탁 없음 — app.json 의 이름·설명을 보고)'))
    if step == 'build':
        return (head + '%s\\spec.md 설계서대로 앱을 만들어 줘. 기능별로 파일을 나누고, tests\\smoke.json 을 완료 기준에 맞춰 고쳐.\n%s'
                % (rel, check))
    if step == 'change':
        if not (what or '').strip():
            raise ValueError('무엇을 바꿀지 적어 주세요')
        return (head + '이 앱을 이렇게 바꿔 줘: %s\nspec.md 도 바뀐 내용에 맞게 고치고, tests\\smoke.json 에 새 동작 확인을 더해.\n%s'
                % (what.strip(), check))
    raise ValueError('모르는 단계입니다: %s' % step)


def start_app_check(app_id):
    """🔍 앱 검사를 도구 실행으로 — 진짜 브라우저로 열어 오류·시나리오·스크린샷(appcheck.py)."""
    app = apphost.find(app_id)
    if not app:
        raise ValueError('없는 앱입니다')
    run = Run('app-check:' + app_id, '🔍 앱 검사 — %s' % app['name'], {'kind': 'tool'}, tool=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    run.proc = subprocess.Popen([test_python(), '-u', os.path.join(HERE, 'appcheck.py'), app_id], cwd=HERE, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    with lock:
        runs.append(run)
        runs_by_id[run.id] = run
    broadcast({'t': 'run', 'run': run.summary()})
    threading.Thread(target=_pump, args=(run,), daemon=True).start()
    threading.Thread(target=_watch, args=(run, 180), daemon=True).start()
    return run


def app_snapshot(app_id, label):
    """앱 폴더를 버전으로 남긴다(apphistory) — 같은 내용이면 건너뛴다. 남긴 버전|None. 견본 앱은 남기지 않는다."""
    app = apphost.find(app_id)
    if not app or app['builtin']:
        return None
    keep = (kit.section('apps', {}) or {}).get('history_keep') or apphistory.KEEP
    try:
        return apphistory.snapshot(app['dir'], label, keep)
    except OSError as e:
        print('앱 버전을 남기지 못했습니다:', app_id, e, file=sys.stderr)
        return None


def app_ai(step, app_id, what=''):
    """설계서 쓰기·만들기·말로 고치기를 고른 AI 로 — claude 는 디스패치 대화, 나머지는 허브가 직접.
    맡기기 전에 지금 모습을 버전으로 남긴다(되돌리기용)."""
    app = apphost.find(app_id)
    if not app:
        raise ValueError('없는 앱입니다')
    if app['builtin']:
        raise ValueError('견본 앱은 고치지 않습니다 — 새 앱을 만드세요')
    text = app_prompt(step, app, what)
    label = {'spec': '앱 설계서', 'build': '앱 만들기', 'change': '앱 고치기'}[step]
    app_snapshot(app_id, '%s 전%s' % (label, (' — ' + what.strip()[:40]) if (what or '').strip() else ''))
    engine = aicli.settings()['engine']
    if engine == 'codex' and step != 'spec':
        text += ('\n(샌드박스 때문에 검사 명령이 브라우저를 못 띄우면 그 실패는 코드 문제가 아니니 고치려 하지 말고 넘어가 — '
                 '끝나면 허브가 검사를 한 번 더 돌린다)')
    if engine != 'claude':
        return {'ok': True, 'run': start_ai_run('%s · %s' % (label, app['name']), text, app_id, check=step != 'spec').id, 'text': text}
    return dict(ask_chat(text), text=text)


SECRET_FIELD = re.compile(r'(?i)passw|passwd|pwd|\bpw\b|비밀번호|비번|암호|패스워드')
FILL_LINE = re.compile(r'^(?P<pre>.*\.(?:fill|type|press_sequentially)\()(?P<lit>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')(?P<post>.*)$')


def secretize_recording(code, stem):
    """녹화 코드에서 비밀번호 칸에 넣은 값을 빼낸다 — (바꾼 코드, {키: 값}).
    codegen 은 입력한 값을 .fill("…") 그대로 적는다. 칸을 가리키는 말(password·비밀번호…)이 그 줄에 있으면
    값을 secret("<이름>_비밀번호") 로 바꾼다. 같은 값은 같은 키, 다른 값은 _2·_3."""
    found, out = {}, []
    for line in code.split('\n'):
        m = FILL_LINE.match(line)
        if m and SECRET_FIELD.search(m.group('pre')):
            try:
                val = ast.literal_eval(m.group('lit'))
            except (ValueError, SyntaxError):
                val = ''
            if isinstance(val, str) and val:
                key = next((k for k, v in found.items() if v == val), None)
                if not key:
                    key = '%s_비밀번호' % stem + ('_%d' % (len(found) + 1) if found else '')
                    found[key] = val
                line = '%ssecret(%r)%s' % (m.group('pre'), key, m.group('post'))
        out.append(line)
    return '\n'.join(out), found


FIELD_NAME = (re.compile(r'get_by_(?:label|placeholder|title|alt_text|text)\(\s*(["\'])(.+?)\1'),
              re.compile(r'\bname\s*=\s*(["\'])(.+?)\1'),
              re.compile(r'locator\(\s*(["\'])(?:#|\.|\[name=["\']?)([\w\-]+)'))


def paramize_recording(code):
    """녹화 코드의 입력값을 카드에서 바꿀 수 있는 칸으로 — (바꾼 코드, {칸 이름: 녹화한 값}).
    비밀번호 칸은 secretize_recording 이 먼저 secret(...) 으로 바꿔 두니 여기서는 남은 .fill("…") 만 본다.
    칸 이름은 그 줄의 이름표(get_by_label·placeholder·role name·#id), 못 찾으면 '입력'. 같은 이름에 다른 값이면 _2·_3."""
    params, out = {}, []
    for line in code.split('\n'):
        m = FILL_LINE.match(line)
        if m:
            try:
                val = ast.literal_eval(m.group('lit'))
            except (ValueError, SyntaxError):
                val = None
            if isinstance(val, str) and val:
                label = next((mt.group(2) for mt in (p.search(m.group('pre')) for p in FIELD_NAME) if mt), '')
                base = safe_name(label)[:24] or '입력'
                key = next((k for k, v in params.items() if v == val and re.sub(r'_\d+$', '', k) == base), None)
                if not key:
                    key, n = base, 1
                    while key in params:
                        n += 1
                        key = '%s_%d' % (base, n)
                    params[key] = val
                line = '%sparam(%r)%s' % (m.group('pre'), key, m.group('post'))
        out.append(line)
    return '\n'.join(out), params


# ---------------------------------------------------------------- 📚 자동화 갤러리 · 🔗 묶음

DIR_GALLERY = os.path.join(HERE, 'gallery')      # 견본 자동화 — 키트에 들어 있다. 「내 자동화로 복사」로 macros.local 에 사본을 만든다


def gallery_list():
    """갤러리 견본 목록 [{"file", "name", "desc", "steps", "params", "secrets", "hint", "target", "triggers"}]."""
    out = []
    for path, _ in _scan(DIR_GALLERY, False):
        meta = runner.read_meta(path)
        if not meta:
            continue
        out.append({'file': os.path.splitext(os.path.basename(path))[0], 'name': meta.get('name') or '',
                    'desc': meta.get('desc', ''), 'steps': [str(s) for s in meta.get('steps') or []],
                    'params': meta.get('params') or {}, 'secrets': [str(s) for s in meta.get('secrets') or []],
                    'hint': meta.get('hint', ''), 'target': meta.get('target', ''), 'triggers': meta.get('triggers') or [],
                    'icon': meta.get('icon', '')})
    return out


def copy_gallery(fname):
    """견본 하나를 내 자동화로 복사(꺼진 채) — 이름이 겹치면 <이름>_2.py · 화면 이름에 (2). (자동화 id, 오류)"""
    item = next((g for g in gallery_list() if g['file'] == fname), None)   # 목록에 있는 이름만 — 경로 조작 막기
    if not item:
        return None, '갤러리에 없는 견본입니다'
    with open(os.path.join(DIR_GALLERY, fname + '.py'), encoding='utf-8') as f:
        code = f.read()
    os.makedirs(DIR_LOCAL, exist_ok=True)
    stem, n = fname, 1
    while os.path.exists(os.path.join(DIR_LOCAL, stem + '.py')):
        n += 1
        stem = '%s_%d' % (fname, n)
    if n > 1 and item['name']:
        old = '"name": %s' % json.dumps(item['name'], ensure_ascii=False)
        code = code.replace(old, '"name": %s' % json.dumps('%s (%d)' % (item['name'], n), ensure_ascii=False), 1)
    with open(os.path.join(DIR_LOCAL, stem + '.py'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(code)
    mid = 'local/' + stem
    audit('갤러리에서 복사', mid, '📚 ' + fname)
    broadcast({'t': 'macros'})
    return mid, None


CHAIN_MAX = 20


AI_ORDER_MAX = 4000


def new_chain(name, steps, keep_going=False, at='', days='daily', mode='ai'):
    """🔗 묶음 만들기 — macros.local\\<이름>.py 에 META 만 있는 파일(kind chain). 단계는 지금 있는 자동화(상시·묶음 제외)
    또는 🤖 AI 단계 {"ai": "지시", "engine": ""}(앞 단계 결과를 자료로 묻는다 — runner.run_chain).
    mode 🙋 = step(단계마다 확인) · ai(AI 답만 확인) · auto(자동). at 이 있으면 예약(⏰)도 건다 — 켜는 건 사람이 「자동 실행」으로. (자동화 id, 오류)"""
    import aicli
    stem = safe_name(name)
    if not stem:
        return None, '일 순서 이름을 입력하세요'
    if not isinstance(steps, list) or len(steps) < 2:
        return None, '단계를 둘 이상 넣으세요'
    if len(steps) > CHAIN_MAX:
        return None, '일 순서 하나에는 %d개까지 넣을 수 있습니다' % CHAIN_MAX
    if mode not in runner.CHAIN_MODES:
        return None, '모드는 %s 중 하나입니다' % ' · '.join(runner.CHAIN_MODES)
    found = []                                       # (보이는 이름, META chain 항목, 제한 시간)
    for sid in steps:
        if runner.is_ai_step(sid):
            order = str(sid.get('ai') or '').strip()
            engine = str(sid.get('engine') or '').strip()
            if not order:
                return None, 'AI 단계의 지시를 입력하세요'
            if len(order) > AI_ORDER_MAX:
                return None, 'AI 지시는 %d자까지입니다' % AI_ORDER_MAX
            if engine and engine not in aicli.ENGINES:
                return None, '없는 AI 입니다: %s' % engine
            item = {'ai': order, 'engine': engine}
            found.append(('🤖 ' + runner.ai_step_name(item), item, runner.AI_TIMEOUT))
            continue
        m = find_macro(str(sid))
        if not m:
            return None, '없는 자동화입니다: %s' % sid
        if m['service'] or m['kind'] == 'chain':
            return None, '상시 자동화·일 순서는 넣을 수 없습니다: %s' % m['name']
        found.append((m['name'], m['id'], m['timeout'] or 600))
    triggers = []
    if (at or '').strip():
        triggers, err = clean_schedule([{'at': at, 'days': days or 'daily'}])
        if err:
            return None, err
    path = os.path.join(DIR_LOCAL, stem + '.py')
    if os.path.exists(path):
        return None, '같은 이름이 이미 있습니다'
    keep = bool(keep_going)
    asks = sum(1 for i, (_, item, _) in enumerate(found, 1)    # 🙋 확인으로 멈출 수 있는 곳 — 그만큼 제한 시간을 늘린다
               if i < len(found) and (mode == 'step' or (mode == 'ai' and not isinstance(item, str))))
    meta = {
        'name': name.strip(),
        'desc': '단계 %d개를 순서대로 — %s · %s' % (len(found), '하나가 실패해도 끝까지' if keep else '앞이 실패하면 멈춤',
                                             runner.CHAIN_MODES[mode]),
        'kind': 'chain',
        'steps': [n for n, _, _ in found],
        'chain': [item for _, item, _ in found],
        'keep_going': keep,
        'mode': mode,
        'triggers': triggers,
        'timeout': min(6 * 3600, sum(t for _, _, t in found) + 30 * len(found) + runner.CONFIRM_WAIT * asks),
    }
    import pprint
    os.makedirs(DIR_LOCAL, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# -*- coding: utf-8 -*-\n# 🔗 일 순서 — 허브 🛠 만들기에서 만든 파일. chain 의 자동화를 순서대로 돌린다(runner.run_chain).\n'
                '# 순서·「실패해도 계속」(keep_going)은 여기서 고쳐도 된다.\nMETA = %s\n'
                % pprint.pformat(meta, sort_dicts=False, width=110))
    mid = 'local/' + stem
    audit('일 순서 만듦', mid, ' → '.join(meta['steps']))
    broadcast({'t': 'macros'})
    return mid, None


def save_secrets(values):
    """secrets.local.json 에 키를 더한다(있는 키는 덮어씀) — 값은 DPAPI 로 암호화해서. 이 PC 에만 있는 파일 — git 에서 빠져 있다."""
    try:
        with open(runner.SECRETS, encoding='utf-8-sig') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    data.update({k: hubutil.seal(v) for k, v in values.items()})
    hubutil.write_secrets(runner.SECRETS, data)


def record_web(url, name):
    stem = safe_name(name)
    if not stem or not url:
        return '이름과 주소를 입력하세요'
    if not re.match(r'^https?://\S+$', url.strip()):     # '-' 로 시작하면 codegen 옵션으로 읽힌다 — 웹 주소만
        return '주소는 http:// 또는 https:// 로 시작해야 합니다'
    url = url.strip()
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
            code, found = secretize_recording(code, stem)
            moved = ''
            if found:
                try:
                    save_secrets(found)
                    moved = ' — 비밀번호 %d개는 파일에 쓰지 않고 secrets.local.json 으로 옮겼습니다(%s)' % (len(found), ', '.join(found))
                except (OSError, ValueError) as e:      # 못 옮기면 값 없이 저장 — 키만 남기고 사람이 넣는다
                    moved = ' — 비밀번호를 secrets.local.json 에 넣지 못했습니다(%s). %s 키에 직접 넣으세요' % (e, ', '.join(found))
            code, fields = paramize_recording(code)      # 입력값 → 카드에서 바꿔 돌릴 칸(param("…"))
            meta = {'name': name.strip(), 'desc': '녹화 %s' % datetime.date.today(), 'kind': 'script',
                    'target': 'web', 'params': fields, 'triggers': [], 'timeout': 300}
            with open(dest, 'w', encoding='utf-8') as f:
                f.write('# -*- coding: utf-8 -*-\nMETA = %r\n\n%s' % (meta, code))
            if fields:
                moved += ' — 입력한 값 %d개(%s)는 카드에서 바꿔 돌릴 수 있는 칸이 됐습니다' % (len(fields), ', '.join(fields))
            broadcast({'t': 'note', 'text': '녹화 저장: %s%s' % (os.path.basename(dest), moved)})
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

LAST_RUN = {}                        # 자동화 id → 허브가 시작하기 전 마지막 실행(runs.jsonl 에서). 다시 켜도 '마지막 실행'이 보이게


def load_last_runs(keep=2000, limit=2 * 1024 * 1024):
    """runs.jsonl 에서 자동화별 마지막 실행을 읽는다. 파일이 limit 를 넘으면 최근 keep 건만 남긴다
    (예약 자동화가 10분마다 한 줄씩 쌓으니 정리하지 않으면 계속 커진다)."""
    try:
        with open(F_RUNS, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
    except OSError:
        return
    for ln in lines:
        try:
            r = json.loads(ln)
            last = {k: v for k, v in r.items() if k != 'tail'}
            if last.get('shot') and not failshot_file(last['shot']):     # 📸 정리돼 지워진 화면 — 가리키지 않는다
                last['shot'] = None
                last.pop('shot_file', None)
            LAST_RUN[r['macro']] = last
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
    last = next((x for x in reversed(runs) if x.macro == m['id'] and not x.tool and x.status != 'running'
                 and x.trigger.get('kind') != 'test'), None)
    d = {k: v for k, v in m.items() if k != 'path'}
    saved = dict(LAST_RUN.get(m['id']) or {}) or None
    if saved:
        saved.pop('shot_file', None)                 # 화면에는 이 PC 의 절대 경로를 보내지 않는다(파일 이름 shot 이면 된다)
    if saved and saved.get('shot') and not failshot_file(saved['shot']):   # 그 사이 정리로 지워진 화면
        saved['shot'] = None
    d.update(enabled=bool(state['enabled'].get(m['id'])), running=r.id if r else None, hidden=m['id'] in hidden_ids(),
             last=last.summary() if last else saved,
             motion=r.motion if r else d['motion'], motion_until=r.motion_until if r else None,
             motion_default=r.motion_default if r else None, saved_params=saved_params(m))
    raw = m.get('chain_raw') or m['chain']
    if raw:                                          # 🔗 묶음 — 단계 이름(없어진 자동화는 id 그대로, 🤖 AI 단계는 지시 첫머리)
        d['chain_names'] = [('🤖 ' + runner.ai_step_name(s)) if runner.is_ai_step(s) else
                            (find_macro(str(s if isinstance(s, str) else (s or {}).get('id'))) or {}).get('name') or str(s)
                            for s in raw]
    return d


class Handler(BaseHTTPRequestHandler):
    server_version = 'macrohub'
    allowed_hosts = frozenset()

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8', csp=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        # 다른 웹 페이지가 허브 화면을 투명 iframe 으로 덮어 '지금 실행' 등을 누르게 하는 클릭재킹 막기 —
        # 허브 화면은 브라우저 탭·허브 창(Electron, 최상위)으로만 열린다
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'" + ('; ' + csp if csp else ''))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self):
        """GET 이라도 부작용(외부 조회·프로세스 실행)이 있는 것은 POST 와 같은 토큰을 요구한다."""
        return self.headers.get('X-Hub-Token') == TOKEN

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
            with open(path, 'rb') as f:              # svg 는 허브와 같은 출처에서 스크립트가 돌 수 있다 — 남이 만든 스킨이면 토큰을 훔친다
                return self._send(200, f.read(), STATIC_TYPES[m.group(3)], csp='sandbox' if m.group(3) == 'svg' else None)
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
        if u.path == '/api/apps':                     # ✨ 나만의 앱 목록 — 권한·허락·주소 + 새 앱 템플릿
            apps = apphost.list_view(APPS_PORT) if APPS_PORT else []
            for a in apps:
                shot = os.path.join(apphost.find(a['id'])['dir'], '.check', 'check.png')
                a['shot'] = int(os.path.getmtime(shot)) if os.path.isfile(shot) else None
            return self._send(200, {'port': APPS_PORT, 'apps': apps, 'templates': apphost.templates()})
        if u.path == '/api/apps/spec':                # 설계서 읽기 ?id=
            app = apphost.find((q.get('id') or [''])[0])
            if not app:
                return self._send(404, {'error': '없는 앱입니다'})
            try:
                with open(os.path.join(app['dir'], 'spec.md'), encoding='utf-8') as f:
                    return self._send(200, {'text': f.read()})
            except OSError:
                return self._send(200, {'text': ''})
        if u.path in ('/api/apps/history', '/api/apps/diff'):   # 🕘 버전 목록 ?id= · 바뀐 곳 ?id=&v=[&to=]
            app = apphost.find((q.get('id') or [''])[0])
            if not app:
                return self._send(404, {'error': '없는 앱입니다'})
            if u.path == '/api/apps/history':
                return self._send(200, {'versions': apphistory.history(app['dir'])})
            try:
                return self._send(200, apphistory.diff(app['dir'], (q.get('v') or [''])[0], (q.get('to') or [None])[0]))
            except ValueError as e:
                return self._send(400, {'error': str(e)})
        if u.path == '/api/apps/export':              # 📦 내보내기 받기 ?id=&fmt=zip|html — 브라우저가 파일로 받는다
            app = apphost.find((q.get('id') or [''])[0])
            if not app:
                return self._send(404, {'error': '없는 앱입니다'})
            try:
                if (q.get('fmt') or ['zip'])[0] == 'html':
                    name, data = apppack.export_html(app)
                    data, ctype = data.encode('utf-8'), 'text/html; charset=utf-8'
                else:
                    name, data = apppack.export_zip(app)
                    ctype = 'application/zip'
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            audit('앱 내보냄', app['id'], name)
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''%s" % quote(name))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', 'sandbox')   # 받은 HTML 이 허브 출처에서 돌지 않게
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == '/api/apps/shot':                # 마지막 🔍 검사 스크린샷 ?id=
            app = apphost.find((q.get('id') or [''])[0])
            shot = os.path.join(app['dir'], '.check', 'check.png') if app else ''
            if not shot or not os.path.isfile(shot):
                return self._send(404, b'not found', 'text/plain')
            with open(shot, 'rb') as f:
                return self._send(200, f.read(), 'image/png')
        if u.path == '/api/deleted':                  # 지운 내 자동화(되살리기용)
            return self._send(200, deleted_macros())
        if u.path == '/api/gallery':                  # 📚 견본 자동화 목록
            return self._send(200, gallery_list())
        if u.path == '/api/failshot':                 # 📸 실패한 순간 화면 ?file=<이름>.png — failshots 바로 아래 것만
            shot = failshot_file((q.get('file') or [''])[0])
            if not shot:
                return self._send(404, b'not found', 'text/plain')
            with open(shot, 'rb') as f:
                return self._send(200, f.read(), 'image/png')
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
            return self._send(200, {'skin': state.get('skin') or DEFAULT_SKIN, 'breed': state.get('breed') or {}})
        if u.path == '/api/theme':                    # 허브 전용 창(shell/main.js)이 창 테두리·배경색을 맞추려고 묻는다
            return self._send(200, {'mode': ui_mode()})
        if u.path == '/api/ping':                     # 화면이 실시간 연결을 다시 붙일 때 — 토큰이 옛것(허브가 다시 뜸)이면 403 → 화면이 새로 고친다
            return self._send(200, {'ok': True}) if self._token_ok() else self._send(403, {'error': 'forbidden'})
        if u.path == '/api/ai':                       # AI 고르기 — 고른 엔진 · 엔진마다 깔렸는지 · 설치 명령
            return self._send(200, aicli.status())
        if u.path == '/api/look':                     # 꾸미기 — 지금 값 · 고를 수 있는 것
            return self._send(200, {'look': look(), 'attrs': look_attrs(), 'themes': LOOK_THEMES})
        if u.path == '/api/schedule':
            return self._send(200, schedule_view())
        if u.path == '/api/audit':                    # 변경 이력 — 새것 먼저
            try:
                limit = max(1, min(2000, int(q.get('limit', ['300'])[0])))
            except ValueError:
                limit = 300
            return self._send(200, {'items': kit.audit_tail(limit), 'file': kit.audit_path()})
        if u.path.startswith('/api/ops/'):            # 운영 화면 — 기능 상태·설정·에이전트(읽기 전용)
            import ops
            what = u.path[len('/api/ops/'):]
            try:
                if what == 'features':
                    return self._send(200, ops.features_status())
                if what == 'settings':
                    return self._send(200, ops.settings_status())
                if what == 'agents':                  # verify=1 은 claude 를 실행한다 — 다른 웹 페이지가 <img src> 로 쌓지 못하게 토큰
                    verify = q.get('verify', ['0'])[0] == '1'
                    if verify and not self._token_ok():
                        return self._send(403, {'error': 'forbidden'})
                    return self._send(200, ops.agent_view(verify=verify))
                if what in ('jobaudit', 'jobaudit.csv'):   # 지시 실행 기록(감사) — 화면 · CSV 내려받기
                    text = q.get('q', [''])[0]
                    if what == 'jobaudit.csv':
                        return self._send(200, ops.job_audit_csv(text), 'text/csv; charset=utf-8')
                    try:
                        limit = max(1, min(5000, int(q.get('limit', ['300'])[0])))
                    except ValueError:
                        limit = 300
                    return self._send(200, {'items': ops.job_audit(limit, text), 'file': ops.JOB_AUDIT})
            except Exception as e:
                return self._send(500, {'error': '%s: %s' % (type(e).__name__, e)})
            return self._send(404, {'error': 'no such ops view'})
        if u.path == '/api/hidden':                   # 숨긴 자동화·도구 id 목록(도구 칸은 이걸로 그린다)
            return self._send(200, {'hidden': sorted(hidden_ids())})
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
        set_via('화면 ' + (urlparse(self.headers.get('Referer') or '').path or '?'))   # 변경 이력의 '어디서'

        if path == '/api/run':
            run, err = run_macro(body.get('id', ''), body.get('params'), {'kind': 'manual'})
            audit('지금 실행', body.get('id', ''), '' if run else '실패: %s' % err)
            return self._send(200 if run else 409, {'run': run.id} if run else {'error': err})
        if path == '/api/test':                       # 🧪 시험 실행 {"id", "params"} — 내 자동화만, for_real 동작은 건너뜀
            run, err = run_macro(body.get('id', ''), body.get('params'), {'kind': 'test'})
            return self._send(200 if run else 409, {'run': run.id} if run else {'error': err})
        if path == '/api/stop':
            return self._send(200, {'ok': stop_run(int(body.get('run', 0)))})
        if path == '/api/chain/confirm':              # 🙋 묶음 확인 답 {"run", "ok"} — 계속(true)·멈춤(false)
            err = answer_confirm(int(body.get('run', 0) or 0), body.get('ok') is True)
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True})
        if path == '/api/apps/approve':               # ✨ 앱 권한 허락·거두기 {"id", "perms": [...]} — 빈 목록이면 모두 거둠
            perms = body.get('perms')
            try:
                if not isinstance(perms, list):
                    raise ValueError('perms 는 목록이어야 합니다')
                ok = apphost.approve(str(body.get('id') or ''), [str(p) for p in perms])
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            audit('앱 권한', str(body.get('id') or ''), ', '.join(ok) or '모두 거둠')
            return self._send(200, {'ok': True, 'approved': ok})
        if path == '/api/apps/new':                   # 새 앱 {"id", "name", "template", "what"} — what 이 있으면 설계서 쓰기까지
            try:
                app = apphost.create_app(str(body.get('id') or ''), str(body.get('name') or ''),
                                         str(body.get('template') or 'blank'), str(body.get('what') or ''))
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            except OSError as e:
                return self._send(500, {'error': '앱 폴더를 만들지 못했습니다: %s' % e})
            audit('앱 만듦', app['id'], str(body.get('template') or 'blank'))
            res = {'ok': True, 'id': app['id']}
            if str(body.get('what') or '').strip():
                try:
                    res['ai'] = app_ai('spec', app['id'], str(body['what']))
                except Exception as e:
                    res['ai_error'] = str(e)
            return self._send(200, res)
        if path == '/api/apps/ai':                    # {"id", "step": spec|build|change, "what"} — 고른 AI 에게
            try:
                return self._send(200, app_ai(str(body.get('step') or ''), str(body.get('id') or ''), str(body.get('what') or '')))
            except (ValueError, KeyError) as e:
                return self._send(400, {'error': str(e)})
            except Exception as e:
                return self._send(502, {'error': str(e)})
        if path == '/api/apps/spec':                  # 설계서 저장 {"id", "text"} — 사람이 고친 것
            app = apphost.find(str(body.get('id') or ''))
            if not app or app['builtin']:
                return self._send(400, {'error': '내 앱만 고칠 수 있습니다'})
            app_snapshot(app['id'], '설계서 직접 고치기 전')
            with open(os.path.join(app['dir'], 'spec.md'), 'w', encoding='utf-8', newline='\n') as f:
                f.write(str(body.get('text') or ''))
            return self._send(200, {'ok': True})
        if path == '/api/apps/snapshot':              # 🕘 지금 저장 {"id", "label"}
            v = app_snapshot(str(body.get('id') or ''), str(body.get('label') or '').strip() or '직접 저장')
            return self._send(200, {'ok': True, 'version': v})
        if path == '/api/apps/restore':               # 🕘 되돌리기 {"id", "v"} — 되돌리기 전 모습도 버전으로 남는다
            app = apphost.find(str(body.get('id') or ''))
            if not app or app['builtin']:
                return self._send(400, {'error': '내 앱만 되돌릴 수 있습니다'})
            try:
                saved, n = apphistory.restore(app['dir'], str(body.get('v') or ''),
                                              (kit.section('apps', {}) or {}).get('history_keep') or apphistory.KEEP)
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            audit('앱 되돌림', app['id'], str(body.get('v')))
            return self._send(200, {'ok': True, 'files': n, 'saved': saved})
        if path == '/api/apps/exe':                   # 📦 exe 만들기 {"id"} — data.local\exports 에 만들고 폴더를 연다
            app = apphost.find(str(body.get('id') or ''))
            if not app:
                return self._send(400, {'error': '없는 앱입니다'})
            try:
                out = apppack.export_exe(app, EXPORTS)
            except (ValueError, RuntimeError, OSError) as e:
                return self._send(400, {'error': str(e)})
            audit('앱 exe 만듦', app['id'], os.path.basename(out))
            try:
                subprocess.Popen(['explorer', '/select,', out])
            except OSError:
                pass
            return self._send(200, {'ok': True, 'path': out})
        if path == '/api/apps/import':                # 📥 zip 가져오기 {"id", "name", "data": base64}
            try:
                app = apppack.import_zip(base64.b64decode(str(body.get('data') or '')), str(body.get('id') or ''),
                                         str(body.get('name') or ''))
            except (ValueError, binascii.Error) as e:
                return self._send(400, {'error': str(e)})
            app_snapshot(app['id'], '가져옴')
            audit('앱 가져옴', app['id'])
            return self._send(200, {'ok': True, 'id': app['id'], 'permissions': app['permissions']})
        if path == '/api/apps/check':                 # 🔍 검사 {"id"}
            try:
                return self._send(200, {'ok': True, 'run': start_app_check(str(body.get('id') or '')).id})
            except ValueError as e:
                return self._send(400, {'error': str(e)})
        if path == '/api/enable':
            if not set_enabled(body.get('id', ''), bool(body.get('enabled'))):
                return self._send(404, {'error': 'no such macro'})
            return self._send(200, {'ok': True})
        if path == '/api/hide':                       # 안 쓰는 것 숨기기 {"id", "hidden": true|false}
            err = set_hidden(str(body.get('id', '')), bool(body.get('hidden')))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True, 'hidden': sorted(hidden_ids())})
        if path == '/api/delete':                     # 내 자동화 지우기 {"id"} — data.local\deleted 로 옮긴다
            fname, err = delete_macro(str(body.get('id', '')))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True, 'file': fname})
        if path == '/api/undelete':                   # 지운 자동화 되살리기 {"file"}
            mid, err = restore_macro(str(body.get('file', '')))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True, 'id': mid})
        if path == '/api/ops/agents/dismiss':         # 끝난 백그라운드 에이전트 치우기 {"id"} · 되돌리기 {"undo": true}
            import ops
            try:
                return self._send(200, ops.agent_dismiss(body.get('id', ''), bool(body.get('undo'))))
            except ValueError as e:
                return self._send(400, {'error': str(e)})
        if path == '/api/schedule':                   # 예약 시각 바꾸기 {"id", "schedule": [...]} · 되돌리기 {"id", "reset": true}
            m = find_macro(body.get('id', ''))
            if not m or m['service']:
                return self._send(404, {'error': '예약 자동화가 아닙니다'})
            ov = state.setdefault('schedule', {})
            before = sched_text(m['triggers'])
            if body.get('reset'):
                ov.pop(m['id'], None)
            else:
                items, err = clean_schedule(body.get('schedule'))
                if err:
                    return self._send(400, {'error': err})
                ov[m['id']] = items
            save_state()
            audit('예약 시각 ' + ('기본값으로' if body.get('reset') else '바꿈'), m['id'],
                  '%s → %s' % (before, sched_text((find_macro(m['id']) or m)['triggers'])))
            broadcast({'t': 'macros'})
            return self._send(200, {'ok': True})
        if path == '/api/service':                    # 운영 화면(/ops): {"id", "action": start|stop|restart|run}
            ok, msg = service_action(body.get('id', ''), body.get('action', ''))
            return self._send(200 if ok else 400, {'ok': ok, 'message': msg} if ok else {'error': msg})
        if path == '/api/gallery/copy':               # 📚 견본을 내 자동화로 {"file"} — 꺼진 채, 이름이 겹치면 _2
            mid, err = copy_gallery(str(body.get('file') or ''))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True, 'id': mid})
        if path == '/api/chain/new':                  # 🔗 묶음 만들기 {"name", "steps": [id | {"ai","engine"}…], "keep_going", "at", "days", "mode"}
            mid, err = new_chain(str(body.get('name') or ''), body.get('steps'), bool(body.get('keep_going')),
                                 str(body.get('at') or ''), str(body.get('days') or 'daily'), str(body.get('mode') or 'ai'))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True, 'id': mid})
        if path == '/api/params':                     # 💾 카드 입력값 기억 {"id", "params"} — 예약 실행·묶음도 이 값으로
            keep, err = save_params(str(body.get('id') or ''), body.get('params'))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True, 'saved': keep})
        if path == '/api/new':
            mid, err = new_macro(body.get('name', ''), body.get('kind', 'web'))
            if err:
                return self._send(400, {'error': err})
            audit('자동화 만듦', mid)
            broadcast({'t': 'macros'})
            return self._send(200, {'id': mid})
        if path == '/api/record/web':
            err = record_web(body.get('url', '').strip(), body.get('name', ''))
            return self._send(400 if err else 200, {'error': err} if err else {'ok': True})
        if path == '/api/ask':                        # 🛠 만들기 「말로 부탁하기」 {"what", "when", "send"} — send 면 디스패치 대화(8620)로, 아니면 부탁 글만
            try:
                text = ask_prompt(body.get('what'), body.get('when')) if 'what' in body else str(body.get('text') or '')
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            if 'what' in body and not body.get('send'):
                return self._send(200, {'text': text})
            try:
                if aicli.settings()['engine'] != 'claude':   # Codex·Gemini — 허브가 직접 돌리고 로그로 보여 준다
                    return self._send(200, {'ok': True, 'run': start_ai_run('말로 부탁하기', text).id, 'text': text})
                return self._send(200, dict(ask_chat(text), text=text))
            except Exception as e:
                return self._send(502, {'error': str(e), 'text': text})
        if path == '/api/fix':                        # 🩹 고쳐 달라기 {"id", "send"} — send 면 대화로 보내고, 아니면 부탁 글만
            try:
                text = fix_text(body.get('id'))
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            if not body.get('send'):
                return self._send(200, {'text': text})
            try:
                if aicli.settings()['engine'] != 'claude':
                    return self._send(200, {'ok': True, 'run': start_ai_run('고쳐 달라기', text).id, 'text': text})
                return self._send(200, dict(ask_chat(text), text=text))
            except Exception as e:
                return self._send(502, {'error': str(e), 'text': text})
        if path == '/api/ai':                         # AI 고르기 {"engine": "claude"|"codex"|"gemini"|"ollama"} — config.local.json ai.engine
            try:
                aicli.set_engine(str(body.get('engine') or ''), via='허브 화면')
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            return self._send(200, aicli.status())
        if path in ('/api/pick', '/api/inspect'):
            tool = 'pick' if path == '/api/pick' else 'inspect'
            title = '요소 찍기' if tool == 'pick' else '창·컨트롤 구조 보기'
            run, err = start_run('__%s__' % tool, {'title': body.get('title', '')}, {'kind': 'tool'},
                                 os.path.join(DIR_BUILTIN, 'pick.py' if tool == 'pick' else 'inspect_tree.py'),
                                 title, tool=True, timeout=120)
            return self._send(200 if run else 409, {'run': run.id} if run else {'error': err})
        if path == '/api/skin':                       # 펫과 허브 화면이 같이 쓰는 모습(스킨) — 허브가 한 곳에서 기억한다
            sid = (body.get('skin') if 'skin' in body else state.get('skin')) or DEFAULT_SKIN   # 옛 '기본 그림'(없음)은 없앴다 — 비우면 기본 스킨
            if not (re.fullmatch(r'[\w\-]+', str(sid)) and os.path.isfile(os.path.join(SKIN_DIR, str(sid), 'skin.json'))):
                return self._send(404, {'error': '없는 스킨입니다'})
            breed = dict(state.get('breed') or {})    # 품종(강아지·고양이 따로) — {"breed": {"dog": "corgi"}} 처럼 바꿀 쪽만 보내도 된다
            for kind, bid in (body.get('breed') or {}).items():
                if kind in ('dog', 'cat') and isinstance(bid, str) and re.fullmatch(r'[\w\-]+', bid):
                    breed[kind] = bid
            state['skin'] = sid
            state['breed'] = breed
            save_state()
            broadcast({'t': 'skin', 'skin': sid, 'breed': breed})
            return self._send(200, {'ok': True, 'skin': sid, 'breed': breed})
        if path == '/api/theme':                      # 화면 모드 — 허브 화면·운영 화면·전용 창이 같이 따른다
            mode = body.get('mode')
            if mode not in UI_MODES:
                return self._send(400, {'error': '모드는 auto · light · dark 중 하나입니다'})
            state['theme'] = mode
            save_state()
            broadcast({'t': 'theme', 'mode': mode})
            return self._send(200, {'ok': True, 'mode': mode})
        if path == '/api/look':                       # 꾸미기 {"theme"|"accent"|"accent2"|"hero"|"cols"|"swap"|"dense"} — 빠진 키는 그대로
            lk, err = clean_look(body)
            if err:
                return self._send(400, {'error': err})
            state['look'] = lk
            save_state()
            broadcast({'t': 'look', 'look': lk, 'attrs': look_attrs(lk)})
            return self._send(200, {'ok': True, 'look': lk, 'attrs': look_attrs(lk)})
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


APPS_PORT = None    # ✨ 나만의 앱 서버가 뜬 포트(못 떴으면 None)


def start_apphost(hub_port):
    """✨ 나만의 앱 — 허브와 다른 포트, 앱마다 <id>.localhost 출처(apphost.py). 설정 apps.enabled=false 면 안 띄운다."""
    global APPS_PORT
    cfg = kit.section('apps', {}) or {}
    if cfg.get('enabled') is False:
        return
    port = int(cfg.get('port') or apphost.PORT)
    try:
        srv = apphost.make_server(port, hub_port)
    except OSError as e:
        print('나만의 앱 서버(%d)를 띄우지 못했습니다:' % port, e, file=sys.stderr)
        return
    APPS_PORT = port
    apphost.HOOKS.update(ai=_app_ai, run=_app_run, run_status=_app_run_status, notify=_app_notify)
    limits = cfg.get('limits')
    if isinstance(limits, dict):
        apphost.LIMITS.update({k: int(v) for k, v in limits.items() if k in apphost.LIMITS and str(v).isdigit()})
    threading.Thread(target=srv.serve_forever, daemon=True).start()


APP_AI_TIMEOUT = 240
APP_RUNS = {}          # 앱 id → 그 앱이 시작한 실행 id 들(다른 실행은 못 엿보게)


def _app_ai(prompt, system, app):
    """✨ 앱의 app.ai — 고른 AI 에게 글만(도구 없이). 이 PC 사용자 본인의 로그인·키·Ollama 로."""
    s = aicli.settings()
    out = aicli.text(prompt, s['engine'], s['model'], timeout=APP_AI_TIMEOUT, system=system)
    return {'text': (out or '').strip(), 'engine': aicli.NAMES[s['engine']]}


def _app_run_view(run):
    return {'run': run.id, 'status': run.status, 'code': run.code, 'ended': bool(run.ended),
            'lines': [str(x) for x in list(run.lines)[-30:]]}


def _app_run(macro, params, app, wait=0):
    """✨ 앱의 app.run — app.json macros 에 적고 사람이 허락한 내 자동화만(apphost 가 확인). wait 초까지 끝나기를 기다린다."""
    run, err = run_macro(macro, params, {'kind': 'app', 'detail': '앱 「%s」' % app['name']})
    if not run:
        raise ValueError(err)
    APP_RUNS.setdefault(app['id'], set()).add(run.id)
    deadline = time.time() + wait
    while not run.ended and time.time() < deadline:
        time.sleep(0.2)
    return _app_run_view(run)


def _app_run_status(run_id, app):
    if run_id not in APP_RUNS.get(app['id'], ()):
        raise ValueError('이 앱이 시작한 실행이 아닙니다')
    run = runs_by_id.get(run_id)
    if not run:
        raise ValueError('실행 기록이 지워졌습니다')
    return _app_run_view(run)


def _app_notify(title, text, app):
    """✨ 앱의 app.notify — 허브 알림 출구(메일·슬랙…)로. 누가 보냈는지 제목·본문에 붙인다."""
    return kit.alert('✨ %s — %s' % (app['name'], title), '%s\n\n(나만의 앱 「%s」 이 보낸 알림)' % (text, app['name']))


def start_services(host='127.0.0.1', port=8630):
    """상태를 읽고 감시 스레드(창 이벤트·트리거·상시 자동화)를 띄운 뒤 HTTP 서버 객체를 돌려준다(serve_forever 는 부르는 쪽이)."""
    load_state()
    try:
        hubutil.encrypt_secrets_file(runner.SECRETS)   # 사람이 평문으로 넣어 둔 비밀값은 바로 암호화(DPAPI)
    except OSError:
        pass
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

    start_apphost(port)

    if host in ('127.0.0.1', 'localhost'):
        Handler.allowed_hosts = frozenset(['127.0.0.1:%d' % port, 'localhost:%d' % port])
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser(description='자동화 허브 (콘솔 모드 — 트레이 앱은 app.py)')
    ap.add_argument('--port', type=int, default=8630)
    ap.add_argument('--host', default='127.0.0.1', help='기본은 이 PC 에서만. 바꾸지 않는 것을 권한다')
    ap.add_argument('--open', action='store_true')
    args = ap.parse_args()

    srv = start_services(args.host, args.port)
    url = 'http://127.0.0.1:%d/' % args.port
    print('자동화 허브 —', url, '(Ctrl+C 로 종료)')
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
