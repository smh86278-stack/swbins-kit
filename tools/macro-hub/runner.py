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
        # 녹화 스크립트(kind script)는 ctx 가 없다 — 녹화 저장 때 비밀번호를 secret("키") 로 바꿔 두니 그 함수를 넣어 준다
        ns = runpy.run_path(path, init_globals={'secret': ctx.secret}, run_name='macro')
        if meta.get('kind', 'ctx') == 'ctx':
            if 'run' not in ns:
                raise RuntimeError('자동화에 run(ctx) 함수가 없습니다')
            ns['run'](ctx)
        say('■ 끝 (%.1f초)' % (time.time() - started))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    except BaseException:
        say(traceback.format_exc().rstrip())
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
