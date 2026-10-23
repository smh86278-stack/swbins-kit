# -*- coding: utf-8 -*-
"""자동화 한 개를 실행하는 자식 프로세스 — macrohub.py 가 띄운다.

    .venv\\Scripts\\python.exe runner.py <자동화.py>
    .venv\\Scripts\\python.exe runner.py --test <자동화.py> [이름=값 ...]     시험 실행 — AUTHORING.md

환경변수 MACROHUB_CTX(JSON): {"params": {...}, "trigger": {...}, "macro": "id"}
표준출력은 그대로 허브 화면의 실시간 로그가 된다. 종료 코드 0 = 성공.

시험 실행(--test): 허브 없이 이 파일 하나를 돌려 본다 — Claude 가 자동화를 만들거나 고친 뒤 스스로 확인하는 길.
허브와 같은 자동화 id(내 자동화면 local/<이름>)라 로그인 프로필·데이터 폴더도 같다. params 는 META 기본값 위에 이름=값.
ctx.dry_run 이 참이라 ctx.for_real('메일 보내기') 로 감싼 되돌릴 수 없는 동작은 건너뛴다. 제한 시간(META timeout,
최대 600초)이 지나면 멈춘다. 마지막 줄이 '🧪 시험 결과: 성공|실패' 이고 종료 코드도 같다.

자동화 종류(META["kind"])
  ctx      (기본) 모듈에 run(ctx) 가 있다. ctx 로 브라우저·창·비밀값·로그를 쓴다.
  script   녹화기(playwright codegen)가 만든 단독 스크립트. 그냥 실행한다.

  chain    🔗 묶음 — META["chain"] 의 자동화 id 를 순서대로 하나씩 이 파일(runner.py)로 돌린다(run_chain).
           앞이 실패하면 멈추고, META["keep_going"] 이 참이면 실패해도 다음으로. 하나라도 실패하면 묶음도 실패.

실패한 순간 화면(📸): 자동화가 오류로 끝나면 웹은 열려 있던 Chrome 화면을, 데스크톱(target desktop)은 전체 화면을
data.local\\failshots\\<자동화>-<시각>.png 로 남기고 '@@failshot <경로>' 줄을 낸다 — 허브가 실행 기록·실패 알림 메일에 붙인다.

일의 종류(META["motion"]) — 펫 고양이가 일하는 동안 보일 모습. 없으면 target(web·desktop)을 따른다.
  web 웹 페이지 · desktop 창 조작 · write 입력 · mail 메일 · search 찾기
  실행 중에 ctx.motion("mail") 로 바꿀 수 있다. 상시 자동화는 평소엔 지켜보기만 하다가
  ctx.motion("write", hold=3) 처럼 잠깐 일하는 모습을 보일 수 있다.
"""
import ast
import json
import os
import re
import runpy
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.environ.get('MACROHUB_SECRETS') or os.path.join(HERE, 'secrets.local.json')   # 환경변수는 시험용


SECRET_VALUES = []                       # ctx.secret 으로 읽은 값 — 출력(print·예외)에서 가린다


class _Masked:
    """stdout·stderr 를 감싸 ctx.secret 으로 읽은 값이 로그로 새지 않게 한다(허브가 줄마다 패턴으로 한 번 더 가린다)."""
    def __init__(self, stream):
        self._s = stream

    def write(self, text):
        for v in SECRET_VALUES:
            text = text.replace(v, '●●●')
        return self._s.write(text)

    def __getattr__(self, name):
        return getattr(self._s, name)


def say(msg):
    print(msg, flush=True)


class Ctx:
    """자동화에 넘기는 도구 모음."""

    def __init__(self, raw, meta):
        self.macro = raw.get('macro', '')
        self.params = raw.get('params') or {}
        self.trigger = raw.get('trigger') or {'kind': 'manual'}
        self.meta = meta
        self.dry_run = bool(raw.get('dry_run'))   # 시험 실행(--test) — for_real() 로 감싼 동작을 건너뛴다
        self.chain_params = raw.get('chain_params') or {}   # 🔗 묶음 — 허브 카드에서 기억한 단계별 입력값 {자동화 id: {...}}
        self._pw = None
        self._browser_ctx = None

    # --- 기본
    def log(self, *parts):
        say(' '.join(str(p) for p in parts))

    def for_real(self, what):
        """되돌릴 수 없는 동작(메일 보내기·제출·삭제·결제 등) 앞에 — 평소엔 True, 시험 실행이면 로그만 남기고 False.
            if ctx.for_real('주문 확정 메일 보내기'):
                send(...)"""
        if self.dry_run:
            say('🧪 시험이라 건너뜀: %s' % what)
            return False
        return True

    def sleep(self, sec):
        time.sleep(sec)

    def notify(self, title, text='', level='info'):
        """허브 알림 — 트레이 풍선과 웹 화면 토스트로 뜨고, 로그에도 남는다. level: info | warning | error"""
        say('@@notify ' + json.dumps({'title': title, 'text': text, 'level': level}, ensure_ascii=False))

    def motion(self, kind=None, hold=None):
        """펫 고양이가 보일 일의 모습을 바꾼다 — web | desktop | write | mail | search, None 이면 META 기본으로.
        hold(초)를 주면 그 시간만 보이고 저절로 돌아간다(상시 자동화가 잠깐 일할 때)."""
        say('@@motion ' + json.dumps({'motion': kind, 'hold': hold}))

    @property
    def data_dir(self):
        """이 자동화 전용 데이터 폴더(data.local\\<자동화 id>) — 자격증명·설정·상태. git 에 들어가지 않는다."""
        safe = re.sub(r'[^\w\-]+', '_', self.macro or 'default')
        path = os.path.join(HERE, 'data.local', safe)
        os.makedirs(path, exist_ok=True)
        return path

    def pids(self, process_name):
        """이름(예: 'notepad.exe')이 같은 실행 중 프로세스의 PID 집합."""
        import importlib.util
        if not hasattr(Ctx, '_pl'):
            spec = importlib.util.spec_from_file_location('proc_live', os.path.join(HERE, '..', 'proc-live', 'proc-live.py'))
            Ctx._pl = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(Ctx._pl)
        want = process_name.lower()
        return {pid for pid, (_, name) in Ctx._pl.snapshot().items() if name.lower() == want}

    def secret(self, key):
        """secrets.local.json 의 값. 계정·비밀번호는 자동화 파일에 쓰지 말고 여기에 둔다.
        값은 DPAPI 로 암호화돼 있다('dpapi:…', hubutil) — 여기서 풀어 준다. 평문이 남아 있으면 먼저 암호화해 둔다."""
        import hubutil
        try:
            try:
                hubutil.encrypt_secrets_file(SECRETS)
            except OSError:
                pass                             # 못 바꿔 써도(잠김 등) 읽기는 한다
            with open(SECRETS, encoding='utf-8-sig') as f:
                v = hubutil.open_secret(json.load(f)[key])
            if isinstance(v, str) and len(v) >= 4 and v not in SECRET_VALUES:
                SECRET_VALUES.append(v)
            return v
        except FileNotFoundError:
            raise RuntimeError('secrets.local.json 이 없습니다 (secrets.example.json 참고)')
        except KeyError:
            raise RuntimeError("secrets.local.json 에 '%s' 가 없습니다" % key)

    def param(self, key, default=''):
        """입력값(META params — 허브 카드의 칸) 하나를 글자로. 녹화로 만든 자동화의 입력값은 param("칸 이름") 으로 바뀌어 있어
        카드에서 값만 바꿔 돌릴 수 있다(비밀번호는 계속 secret)."""
        v = self.params.get(key, default)
        return '' if v is None else str(v)

    # --- 웹 (Playwright)
    @property
    def page(self):
        """Chrome 한 창. 로그인 상태는 자동화별 프로필(profiles\\<id>)에 남는다."""
        if self._browser_ctx is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            safe = re.sub(r'[^\w\-]+', '_', self.macro or 'default')
            profile = os.path.join(HERE, 'profiles', safe)
            os.makedirs(profile, exist_ok=True)
            headless = bool(self.meta.get('headless', False))
            # 창이 보이면 창 크기를 그대로 쓰고(no_viewport), headless 면 화면 크기를 정해 준다 —
            # headless 에 no_viewport 를 주면 화면 크기가 없어 모든 요소가 '안 보임'이 된다(wait_for_selector 가 늘 시간 초과).
            size = {'no_viewport': True} if not headless else {'viewport': {'width': 1280, 'height': 900}}
            self._browser_ctx = self._pw.chromium.launch_persistent_context(
                profile, channel=self.meta.get('channel', 'chrome'), headless=headless, **size)
            self._browser_ctx.set_default_timeout(int(self.meta.get('web_timeout', 30)) * 1000)
        pages = self._browser_ctx.pages
        return pages[0] if pages else self._browser_ctx.new_page()

    @property
    def browser_context(self):
        self.page
        return self._browser_ctx

    # --- 데스크톱 (pywinauto / UI Automation)
    def start(self, command):
        """프로그램을 실행한다(기다리지 않는다). 창은 window() 로 잡는다."""
        import subprocess
        return subprocess.Popen(command, shell=isinstance(command, str))

    def window_handles(self, backend='uia'):
        """지금 열려 있는 최상위 창 핸들 집합. 프로그램을 띄우기 전에 떠 두면 window(exclude=) 로 '새 창'만 잡을 수 있다."""
        from pywinauto import Desktop
        return {w.handle for w in Desktop(backend=backend).windows()}

    def window(self, title_re, timeout=30, backend='uia', exclude=None):
        """제목(정규식)이 맞는 최상위 창이 뜰 때까지 기다렸다가 pywinauto 창(WindowSpecification)을 돌려준다.

        이미 열려 있던 사용자의 창을 잘못 잡지 않으려면, 프로그램을 띄우기 전의 window_handles() 를
        exclude 로 넘긴다.
        """
        from pywinauto import Desktop
        desk = Desktop(backend=backend)
        skip = set(exclude or ())
        end = time.time() + timeout
        while time.time() < end:
            for w in desk.windows():
                try:
                    if w.handle not in skip and re.search(title_re, w.window_text() or '', re.I):
                        return desk.window(handle=w.handle)
                except Exception:
                    continue
            time.sleep(0.3)
        raise TimeoutError("창을 찾지 못했습니다: %s (%s초)" % (title_re, timeout))

    def click(self, ctrl):
        """버튼 누르기 — 마우스를 쓰지 않는 UIA invoke 를 먼저 시도하고, 안 되는 컨트롤만 실제 클릭으로 대신한다.

        실제 클릭으로 넘어가면 그 순간 마우스가 움직이므로 로그에 남긴다.
        META 에 "no_mouse": True 를 주면 대신하지 않고 오류로 멈춘다(내 작업을 방해하면 안 되는 자동화용).
        """
        w = ctrl.wrapper_object() if hasattr(ctrl, 'wrapper_object') else ctrl
        try:
            w.invoke()
        except Exception:
            if self.meta.get('no_mouse'):
                raise RuntimeError('마우스 없이는 누를 수 없는 컨트롤입니다: %s' % w.window_text())
            self.log('⚠ invoke 불가 → 실제 클릭(마우스 이동):', w.window_text() or w.element_info.control_type)
            w.click_input()

    def set_text(self, ctrl, text):
        """입력칸에 값 넣기 — 포커스·키보드 없이 UIA 값 패턴으로 넣고, 안 되면 타이핑(키보드 사용)으로 대신한다."""
        w = ctrl.wrapper_object() if hasattr(ctrl, 'wrapper_object') else ctrl
        try:
            w.iface_value.SetValue(text)
        except Exception:
            if self.meta.get('no_mouse'):
                raise RuntimeError('키보드 없이는 입력할 수 없는 컨트롤입니다: %s' % w.window_text())
            self.log('⚠ 값 패턴 불가 → 실제 타이핑(키보드 사용)')
            w.set_focus()
            w.type_keys(text, with_spaces=True)

    def close(self):
        try:
            if self._browser_ctx:
                self._browser_ctx.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def read_meta(path):
    try:
        tree = ast.parse(open(path, encoding='utf-8-sig').read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'META' for t in node.targets):
                return ast.literal_eval(node.value)
    except Exception:
        pass
    return {}


TEST_TIMEOUT_MAX = 600

# ---------------------------------------------------------------- 📸 실패한 순간 화면

FAILSHOT_DIR = os.path.join(HERE, 'data.local', 'failshots')
FAILSHOT_KEEP = 60                       # 오래된 것부터 지운다 — 10분마다 실패하는 자동화가 폴더를 채우지 않게
FAILSHOT_PREFIX = '@@failshot '


def failshot_path(macro, now=None):
    safe = re.sub(r'[^\w\-]+', '_', macro or 'default')
    os.makedirs(FAILSHOT_DIR, exist_ok=True)
    return os.path.join(FAILSHOT_DIR, '%s-%s.png' % (safe, time.strftime('%Y%m%d-%H%M%S', time.localtime(now))))


def prune_failshots(keep=FAILSHOT_KEEP, folder=None):
    folder = folder or FAILSHOT_DIR
    try:
        files = sorted((os.path.join(folder, n) for n in os.listdir(folder) if n.endswith('.png')), key=os.path.getmtime)
    except OSError:
        return
    for p in files[:-keep] if keep else files:
        try:
            os.remove(p)
        except OSError:
            pass


def grab_screen(path):
    """전체 화면(모니터 모두)을 png 로 — pillow 가 없으면 예외(부르는 쪽이 건너뛴다)."""
    from PIL import ImageGrab
    ImageGrab.grab(all_screens=True).save(path)


def _pages_of(objs):
    """Browser·BrowserContext·Page 섞인 목록 → 열린 Page 들(나중 것이 뒤에)."""
    out = []
    for o in objs:
        try:
            if hasattr(o, 'screenshot'):
                out.append(o)
            elif hasattr(o, 'contexts'):
                for c in o.contexts:
                    out.extend(c.pages)
            elif hasattr(o, 'pages'):
                out.extend(o.pages)
        except Exception:
            continue
    return out


def capture_failure(macro, meta, browsers=(), grab=None):
    """실패한 순간 화면을 남긴다 — 열린 웹 페이지가 있으면 그 화면(마지막 탭부터), 없고 데스크톱 자동화면 전체 화면.
    남긴 경로(없으면 None). 사람이 읽는 줄과 허브가 읽는 '@@failshot' 줄을 낸다. 캡처 실패는 조용히 넘긴다."""
    path = failshot_path(macro)
    done = False
    for page in reversed(_pages_of(browsers)):
        try:
            page.screenshot(path=path, timeout=5000)
            done = True
            break
        except Exception:
            continue
    if not done and (meta.get('target') == 'desktop' or meta.get('failshot') == 'screen'):
        try:
            (grab or grab_screen)(path)
            done = os.path.isfile(path)
        except Exception:
            done = False
    if not done:
        return None
    prune_failshots()
    say('📸 실패한 순간 화면을 남겼습니다: %s' % os.path.relpath(path, HERE))
    say(FAILSHOT_PREFIX + path)
    return path


_SHOT = {'path': None}


def track_playwright(macro, meta, seen):
    """녹화 스크립트(kind script)는 브라우저를 스스로 열고, 오류가 나면 with sync_playwright() 를 빠져나가며 닫아 버린다 —
    닫히기 직전에 화면을 찍으려고 sync_playwright 를 감싼다. 연 브라우저는 seen 에 모은다. playwright 가 없으면 아무것도 안 한다."""
    try:
        import playwright.sync_api as sa
    except Exception:
        return
    orig = sa.sync_playwright

    def watch(pw):
        for name in ('chromium', 'firefox', 'webkit'):
            bt = getattr(pw, name, None)
            for fn in ('launch', 'launch_persistent_context', 'connect_over_cdp'):
                real = getattr(bt, fn, None)
                if real is None:
                    continue

                def wrap(*a, _real=real, **k):
                    obj = _real(*a, **k)
                    seen.append(obj)
                    return obj
                try:
                    setattr(bt, fn, wrap)
                except Exception:
                    pass
        return pw

    class _Watched:
        def __init__(self):
            self._cm = orig()

        def __enter__(self):
            return watch(self._cm.__enter__())

        def __exit__(self, et, ev, tb):
            if et is not None and not issubclass(et, (SystemExit, KeyboardInterrupt)) and not _SHOT['path']:
                _SHOT['path'] = capture_failure(macro, meta, seen)
            return self._cm.__exit__(et, ev, tb)

        def start(self):
            return watch(self._cm.start())

    sa.sync_playwright = _Watched


# ---------------------------------------------------------------- 🔗 묶음

CHAIN_ID = re.compile(r'^(local/)?[\w\-]+$')


def macro_path(mid):
    """자동화 id → 파일 경로(내 자동화면 macros.local, 아니면 macros). 이상한 id 면 None."""
    if not isinstance(mid, str) or not CHAIN_ID.match(mid):
        return None
    if mid.startswith('local/'):
        return os.path.join(HERE, 'macros.local', mid[len('local/'):] + '.py')
    return os.path.join(HERE, 'macros', mid + '.py')


def _kill_tree(proc):
    try:
        import subprocess
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, creationflags=0x08000000)
    except OSError:
        proc.kill()


def run_chain(ctx, meta, popen=None):
    """🔗 묶음 — META chain 의 자동화를 하나씩 runner.py 자식으로 돌린다. 성공(실패 없음)이면 True.
    단계 로그는 들여 써서 그대로 흘리고, '@@' 줄(알림·펫·📸)은 허브가 읽게 그대로 둔다.
    시험 실행이면 단계도 시험으로 — 키트 기본 자동화(for_real 로 감싸지 않음)는 건너뛴다."""
    import subprocess
    popen = popen or subprocess.Popen
    steps = list(meta.get('chain') or [])
    keep = bool(meta.get('keep_going'))
    if not steps:
        raise RuntimeError('묶음에 자동화가 없습니다 (META chain)')
    ok_n = fail_n = skip_n = 0
    total = len(steps)
    for i, step in enumerate(steps, 1):
        sid = step if isinstance(step, str) else (step or {}).get('id')
        over = {} if isinstance(step, str) else dict((step or {}).get('params') or {})
        path = macro_path(sid)
        smeta = read_meta(path) if path and os.path.isfile(path) else None
        name = (smeta or {}).get('name') or sid
        why = ('없는 자동화입니다' if smeta is None else
               '묶음 안에 묶음은 넣을 수 없습니다' if smeta.get('kind') == 'chain' else
               '상시 자동화는 묶을 수 없습니다' if smeta.get('service') else None)
        if why:
            say('✖ [%d/%d] %s — %s' % (i, total, name, why))
            fail_n += 1
        elif ctx.dry_run and not str(sid).startswith('local/'):
            say('🧪 시험이라 건너뜀: [%d/%d] 기본 자동화 「%s」 (진짜로 보내는 동작을 막아 두지 않았습니다)' % (i, total, name))
            skip_n += 1
            continue
        else:
            say('🔗 [%d/%d] %s 시작' % (i, total, name))
            params = dict(smeta.get('params') or {})
            params.update({k: v for k, v in (ctx.chain_params.get(sid) or {}).items() if k in params})
            params.update(over)
            sub = {'macro': sid, 'params': params, 'trigger': dict(ctx.trigger, chain=ctx.macro), 'dry_run': ctx.dry_run}
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONUNBUFFERED='1',
                       MACROHUB_CTX=json.dumps(sub, ensure_ascii=False))
            limit = int(smeta.get('timeout') or 600)
            proc = popen([sys.executable, '-u', os.path.abspath(__file__), path], cwd=HERE, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            import threading
            timer = threading.Timer(limit, _kill_tree, args=(proc,))
            timer.daemon = True
            timer.start()
            for raw in iter(proc.stdout.readline, b''):
                line = raw.decode('utf-8', 'replace').rstrip('\r\n')
                say(line if line.startswith('@@') else '   ' + line)
            code = proc.wait()
            proc.stdout.close()
            late = not timer.is_alive() and code != 0
            timer.cancel()
            if code == 0:
                say('✔ [%d/%d] %s 성공' % (i, total, name))
                ok_n += 1
                continue
            say('✖ [%d/%d] %s %s' % (i, total, name, '시간 초과 (%d초)' % limit if late else '실패 (종료 코드 %s)' % code))
            fail_n += 1
        if not keep and i < total:
            say('⏹ 앞 단계가 실패해 나머지 %d개는 돌리지 않습니다 (「실패해도 계속」이 꺼져 있음)' % (total - i))
            break
    say('🔗 묶음 결과: %d개 중 성공 %d · 실패 %d%s' % (total, ok_n, fail_n, ' · 건너뜀 %d' % skip_n if skip_n else ''))
    return fail_n == 0


def _value(text):
    """이름=값 의 값 — 숫자·true/false·JSON 이면 그 값, 아니면 글자 그대로."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def test_ctx(path, pairs, meta):
    """--test 의 MACROHUB_CTX — 허브와 같은 id(내 자동화 폴더면 local/<이름>), META params 기본값 위에 이름=값."""
    stem = os.path.splitext(os.path.basename(path))[0]
    local = os.path.normcase(os.path.dirname(path)) == os.path.normcase(os.path.join(HERE, 'macros.local'))
    params = dict(meta.get('params') or {})
    for p in pairs:
        if '=' not in p:
            raise SystemExit('시험 인자는 이름=값 으로 주세요: %s' % p)
        k, v = p.split('=', 1)
        params[k.strip()] = _value(v.strip())
    return {'macro': ('local/' if local else '') + stem, 'params': params, 'trigger': {'kind': 'test'}, 'dry_run': True}


def main():
    test = len(sys.argv) > 1 and sys.argv[1] == '--test'
    args = sys.argv[2:] if test else sys.argv[1:]
    if not args:
        raise SystemExit('사용법: runner.py [--test] <자동화.py> [이름=값 ...]')
    path = os.path.abspath(args[0])
    meta = read_meta(path)
    raw = test_ctx(path, args[1:], meta) if test else json.loads(os.environ.get('MACROHUB_CTX') or '{}')
    ctx = Ctx(raw, meta)
    started = time.time()
    code = 0
    if test:
        import threading
        limit = min(int(meta.get('timeout') or 300), TEST_TIMEOUT_MAX)

        def _too_long():
            say('✖ 시험 시간 초과 (%d초) — 기다리는 요소·창이 안 나타났거나 끝나지 않는 반복일 수 있습니다' % limit)
            say('🧪 시험 결과: 실패')
            sys.stdout.flush()
            os._exit(1)
        t = threading.Timer(limit, _too_long)
        t.daemon = True
        t.start()
    try:
        say('▶ %s 시작 (%s)' % (meta.get('name') or os.path.basename(path), ctx.trigger.get('kind', 'manual')))
        kind = meta.get('kind', 'ctx')
        if kind == 'chain':
            if not run_chain(ctx, meta):
                raise SystemExit(1)
        else:
            if kind == 'script':
                track_playwright(ctx.macro, meta, [])
            # 녹화 스크립트(kind script)는 ctx 가 없다 — 녹화 저장 때 비밀번호를 secret("키"), 입력값을 param("칸") 으로 바꿔 두니 그 함수를 넣어 준다
            ns = runpy.run_path(path, init_globals={'secret': ctx.secret, 'param': ctx.param}, run_name='macro')
            if kind == 'ctx':
                if 'run' not in ns:
                    raise RuntimeError('자동화에 run(ctx) 함수가 없습니다')
                ns['run'](ctx)
        say('■ 끝 (%.1f초)' % (time.time() - started))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code and meta.get('kind') == 'chain':
            say('✖ 실패 (%.1f초)' % (time.time() - started))
    except BaseException:
        say(traceback.format_exc().rstrip())
        if not _SHOT['path']:
            _SHOT['path'] = capture_failure(ctx.macro, meta, [ctx._browser_ctx] if ctx._browser_ctx else [])
        say('✖ 실패 (%.1f초)' % (time.time() - started))
        code = 1
    finally:
        ctx.close()
    if test:
        say('🧪 시험 결과: %s (%.1f초)' % ('성공' if code == 0 else '실패', time.time() - started))
    sys.exit(code)


if __name__ == '__main__':
    # 자동화를 돌리는 이 프로세스에서만 감싼다 — 허브(macrohub)도 read_meta 때문에 이 파일을 import 하는데,
    # 트레이(pythonw)는 stdout 이 None 이라 감싸면 print 가 오류가 난다
    sys.stdout, sys.stderr = _Masked(sys.stdout), _Masked(sys.stderr)
    main()
