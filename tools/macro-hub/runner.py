# -*- coding: utf-8 -*-
"""매크로 한 개를 실행하는 자식 프로세스 — macrohub.py 가 띄운다.

    .venv\\Scripts\\python.exe runner.py <매크로.py>

환경변수 MACROHUB_CTX(JSON): {"params": {...}, "trigger": {...}, "macro": "id"}
표준출력은 그대로 허브 화면의 실시간 로그가 된다. 종료 코드 0 = 성공.

매크로 종류(META["kind"])
  ctx      (기본) 모듈에 run(ctx) 가 있다. ctx 로 브라우저·창·비밀값·로그를 쓴다.
  script   녹화기(playwright codegen)가 만든 단독 스크립트. 그냥 실행한다.

일의 종류(META["motion"]) — 펫 고양이가 일하는 동안 보일 모습. 없으면 target(web·desktop)을 따른다.
  web 웹 페이지 · desktop 창 조작 · write 입력 · mail 메일 · search 찾기
  실행 중에 ctx.motion("mail") 로 바꿀 수 있다. 상시 매크로는 평소엔 지켜보기만 하다가
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
SECRETS = os.path.join(HERE, 'secrets.local.json')


def say(msg):
    print(msg, flush=True)


class Ctx:
    """매크로에 넘기는 도구 모음."""

    def __init__(self, raw, meta):
        self.macro = raw.get('macro', '')
        self.params = raw.get('params') or {}
        self.trigger = raw.get('trigger') or {'kind': 'manual'}
        self.meta = meta
        self._pw = None
        self._browser_ctx = None

    # --- 기본
    def log(self, *parts):
        say(' '.join(str(p) for p in parts))

    def sleep(self, sec):
        time.sleep(sec)

    def notify(self, title, text='', level='info'):
        """허브 알림 — 트레이 풍선과 웹 화면 토스트로 뜨고, 로그에도 남는다. level: info | warning | error"""
        say('@@notify ' + json.dumps({'title': title, 'text': text, 'level': level}, ensure_ascii=False))

    def motion(self, kind=None, hold=None):
        """펫 고양이가 보일 일의 모습을 바꾼다 — web | desktop | write | mail | search, None 이면 META 기본으로.
        hold(초)를 주면 그 시간만 보이고 저절로 돌아간다(상시 매크로가 잠깐 일할 때)."""
        say('@@motion ' + json.dumps({'motion': kind, 'hold': hold}))

    @property
    def data_dir(self):
        """이 매크로 전용 데이터 폴더(data.local\\<매크로 id>) — 자격증명·설정·상태. git 에 들어가지 않는다."""
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
        """secrets.local.json 의 값. 계정·비밀번호는 매크로 파일에 쓰지 말고 여기에 둔다."""
        try:
            with open(SECRETS, encoding='utf-8-sig') as f:
                return json.load(f)[key]
        except FileNotFoundError:
            raise RuntimeError('secrets.local.json 이 없습니다 (secrets.example.json 참고)')
        except KeyError:
            raise RuntimeError("secrets.local.json 에 '%s' 가 없습니다" % key)

    # --- 웹 (Playwright)
    @property
    def page(self):
        """Chrome 한 창. 로그인 상태는 매크로별 프로필(profiles\\<id>)에 남는다."""
        if self._browser_ctx is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            safe = re.sub(r'[^\w\-]+', '_', self.macro or 'default')
            profile = os.path.join(HERE, 'profiles', safe)
            os.makedirs(profile, exist_ok=True)
            self._browser_ctx = self._pw.chromium.launch_persistent_context(
                profile, channel=self.meta.get('channel', 'chrome'),
                headless=bool(self.meta.get('headless', False)), no_viewport=True)
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
        META 에 "no_mouse": True 를 주면 대신하지 않고 오류로 멈춘다(내 작업을 방해하면 안 되는 매크로용).
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


def main():
    path = os.path.abspath(sys.argv[1])
    raw = json.loads(os.environ.get('MACROHUB_CTX') or '{}')
    meta = read_meta(path)
    ctx = Ctx(raw, meta)
    started = time.time()
    code = 0
    try:
        say('▶ %s 시작 (%s)' % (meta.get('name') or os.path.basename(path), ctx.trigger.get('kind', 'manual')))
        ns = runpy.run_path(path, run_name='macro')
        if meta.get('kind', 'ctx') == 'ctx':
            if 'run' not in ns:
                raise RuntimeError('매크로에 run(ctx) 함수가 없습니다')
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
    sys.exit(code)


if __name__ == '__main__':
    main()
