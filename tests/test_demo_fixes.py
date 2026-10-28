# -*- coding: utf-8 -*-
"""데모 녹화(2026-10-23)에서 찾은 버그 — 갤러리 견본 기본값 · 겹쳐 돌리기 거절 · 묶음 단계의 마지막 실행 · 로그 경로 줄이기.

진짜 사이트·브라우저·메일 없이. 묶음은 runner 의 '@@step' 줄을 가짜 프로세스 출력으로 흘려 허브(_pump)가 읽게 한다.
"""
import collections
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from unittest import mock

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
import hubutil   # noqa: E402
import macrohub  # noqa: E402
import runner    # noqa: E402

# example.com 의 지금 모습(2026-10 확인) — <h1> 이 없어져 견본 기본값 'h1' 이 30초 기다리다 시간 초과로 실패했다
EXAMPLE_COM = ('<!doctype html><html lang=en><head><meta charset=utf-8><title>Example Domain</title></head>'
               '<body><p>This domain is for use in documentation examples without needing permission. '
               'This is not a service; avoid relying on it for testing and monitoring purposes.</p>'
               '<script src=/s.js></script></body></html>')


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = collections.Counter()

    def handle_starttag(self, tag, attrs):
        self.tags[tag] += 1


def load_gallery(name):
    spec = importlib.util.spec_from_file_location('g_' + name, os.path.join(HUB, 'gallery', name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeLocator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    @property
    def first(self):
        return self

    def wait_for(self, state=None, timeout=None):
        self.page.waits.append(timeout)
        if self.sel not in self.page.tags:
            raise TimeoutError('Timeout %sms exceeded' % timeout)

    def inner_text(self):
        return self.page.texts.get(self.sel, '')


class FakePage:
    def __init__(self, html, texts):
        p = _Tags()
        p.feed(html)
        self.tags = set(p.tags)
        self.texts = texts
        self.waits = []
        self.went = None

    def goto(self, url):
        self.went = url

    def locator(self, sel):
        return FakeLocator(self, sel)


class FakeCtx:
    def __init__(self, page, params, data_dir):
        self.page, self.params, self.data_dir = page, params, data_dir
        self.logs, self.notes = [], []

    def param(self, k, d=''):
        return str(self.params.get(k, d))

    def log(self, *a):
        self.logs.append(' '.join(map(str, a)))

    def notify(self, *a, **k):
        self.notes.append(a)

    def for_real(self, what):
        return False


class PageWatchDefaults(unittest.TestCase):
    def setUp(self):
        self.mod = load_gallery('page_change_watch')
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_default_selector_exists_on_example_com(self):
        params = self.mod.META['params']
        self.assertEqual(params['url'], 'https://example.com')
        sel = params['selector']
        self.assertRegex(sel, r'^[a-z][a-z0-9]*$', '기본 selector 는 태그 이름 하나로(오프라인으로 확인할 수 있게)')
        p = _Tags()
        p.feed(EXAMPLE_COM)
        self.assertTrue(p.tags[sel], '%s 가 example.com 에 없습니다' % sel)
        self.assertNotIn('h1', p.tags)                                     # 옛 기본값이 실패한 까닭

    def test_default_run_reads_text(self):
        page = FakePage(EXAMPLE_COM, {'p': 'This domain is for use in documentation examples'})
        ctx = FakeCtx(page, dict(self.mod.META['params']), self.tmp)
        self.mod.run(ctx)
        self.assertEqual(page.went, 'https://example.com')
        self.assertIn('지금: This domain', ctx.logs[0])

    def test_missing_selector_fails_fast_with_plain_words(self):
        page = FakePage(EXAMPLE_COM, {})
        ctx = FakeCtx(page, dict(self.mod.META['params'], selector='h1'), self.tmp)
        with self.assertRaises(RuntimeError) as cm:
            self.mod.run(ctx)
        self.assertIn("selector 'h1'", str(cm.exception))
        self.assertLessEqual(page.waits[0], 10000)                         # 30초(web_timeout) 대신 짧게


class ProfileLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_second_lock_refused_until_first_closed(self):
        a = runner.lock_profile(self.tmp, 'local/w')
        try:
            with self.assertRaises(runner.AlreadyRunning) as cm:
                runner.lock_profile(self.tmp, 'local/w')
            self.assertIn('이미 실행 중입니다', str(cm.exception))
            self.assertIn('local/w', str(cm.exception))
        finally:
            a.close()
        runner.lock_profile(self.tmp, 'local/w').close()                  # 풀린 뒤에는 다시 된다

    def test_ctx_close_releases(self):
        ctx = runner.Ctx({'macro': 'x'}, {})
        ctx._profile_lock = runner.lock_profile(self.tmp)
        ctx.close()
        self.assertIsNone(ctx._profile_lock)
        runner.lock_profile(self.tmp).close()

    def test_profile_busy_error(self):
        class TargetClosedError(Exception):
            pass
        self.assertTrue(runner.profile_busy_error(TargetClosedError('x')))
        self.assertTrue(runner.profile_busy_error(RuntimeError('Target page, context or browser has been closed')))
        self.assertFalse(runner.profile_busy_error(RuntimeError('net::ERR_NAME_NOT_RESOLVED')))

    def test_runner_refuses_overlap_in_one_line(self):
        """같은 자동화가 이미 프로필을 잡고 있으면 Chrome 을 띄우기 전에 멈춘다 — 긴 오류·실패 화면 없이 한 줄."""
        stem = 'zz_overlap_test_%d' % os.getpid()
        profile = os.path.join(HUB, 'profiles', stem)
        if not os.path.isdir(os.path.dirname(profile)):                    # 원래 없던 profiles 폴더면 끝나고 지운다
            self.addCleanup(lambda: os.listdir(os.path.dirname(profile)) or os.rmdir(os.path.dirname(profile)))
        os.makedirs(profile, exist_ok=True)
        self.addCleanup(shutil.rmtree, profile, True)
        path = os.path.join(self.tmp, stem + '.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write("META = {'name': '겹침', 'target': 'web'}\n\ndef run(ctx):\n    ctx.page\n")
        held = runner.lock_profile(profile, stem)
        try:
            r = subprocess.run([sys.executable, os.path.join(HUB, 'runner.py'), '--test', path], capture_output=True,
                               timeout=60, cwd=HUB, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        finally:
            held.close()
        out = r.stdout.decode('utf-8', 'replace')
        self.assertEqual(r.returncode, 1, out)
        self.assertIn('✖ 이미 실행 중입니다', out)
        self.assertNotIn('Traceback', out)
        self.assertNotIn('@@failshot', out)


class ShortPaths(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', '윈도우 경로')
    def test_python_and_kit_paths(self):
        py = r'C:\Tools\proj\.venv\Scripts\python.exe'
        root = r'D:\WorkKit'
        home = r'C:\Users\someone'
        line = ('  File "C:\\Tools\\proj\\.venv\\Lib\\site-packages\\playwright\\_impl\\_page.py", line 9, in goto | '
                '"D:\\WorkKit\\tools\\macro-hub\\macros.local\\a.py", line 3 | c:\\tools\\proj\\.venv\\scripts\\python.exe -u x | '
                'C:\\Users\\someone\\Desktop\\b.csv | D:/WorkKit/tools/macro-hub/runner.py')
        got = hubutil.short_paths(line, py, root, home)
        self.assertIn(r'"<python>\Lib\site-packages\playwright\_impl\_page.py", line 9', got)
        self.assertIn(r'"tools\macro-hub\macros.local\a.py", line 3', got)
        self.assertIn('python -u x', got)
        self.assertIn(r'%USERPROFILE%\Desktop\b.csv', got)
        self.assertIn('tools/macro-hub/runner.py', got)
        for gone in ('.venv', 'WorkKit', 'someone', 'Tools'):
            self.assertNotIn(gone, got)

    @unittest.skipUnless(os.name == 'nt', '윈도우 경로')
    def test_embedded_runtime_and_plain_text(self):
        py = r'D:\WorkKit\runtime\python.exe'
        got = hubutil.short_paths(r'D:\WorkKit\runtime\Lib\x.py · D:\WorkKit\tools\a.py', py, r'D:\WorkKit', r'C:\Users\u')
        self.assertEqual(got, r'<python>\Lib\x.py · tools\a.py')
        self.assertEqual(hubutil.short_paths('그냥 글 C: 드라이브', py, r'D:\WorkKit', r'C:\Users\u'), '그냥 글 C: 드라이브')

    def test_pump_shortens(self):
        class P:
            stdout = io.BytesIO(('File "%s", line 1\n' % os.path.join(HUB, 'runner.py')).encode('utf-8'))
        run = macrohub.Run('local/x', 'x', {'kind': 'manual'})
        run.proc = P()
        with mock.patch.object(macrohub, 'broadcast', lambda *a: None):
            macrohub._pump(run)
        self.assertEqual(list(run.lines), ['File "%s", line 1' % os.path.join('tools', 'macro-hub', 'runner.py')])


class ChainSteps(unittest.TestCase):
    """묶음 단계 — 실행 중으로 보이고(겹쳐 돌리기 거절), 끝나면 그 자동화의 마지막 실행으로 남는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f_runs = os.path.join(self.tmp, 'runs.jsonl')
        macros = {'local/web': {'id': 'local/web', 'name': '웹 확인', 'chain': None, 'kind': 'ctx', 'params': {},
                                'local': True, 'service': False, 'path': 'x', 'timeout': 60, 'motion': 'web'},
                  'local/c': {'id': 'local/c', 'name': '아침 묶음', 'chain': ['local/web'], 'kind': 'chain', 'params': {},
                              'local': True, 'service': False, 'path': 'c', 'timeout': 60, 'motion': 'web'}}
        for target, attr, val in ((macrohub, 'runs', collections.deque(maxlen=300)), (macrohub, 'runs_by_id', {}),
                                  (macrohub, 'F_RUNS', self.f_runs), (macrohub, 'broadcast', lambda *a, **k: None),
                                  (macrohub, 'find_macro', macros.get), (macrohub, 'state', {'enabled': {}}),
                                  (macrohub, '_alert_mail', lambda rec: self.fail('단계는 실패 알림 메일을 따로 보내지 않는다'))):
            p = mock.patch.object(target, attr, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(macrohub.LAST_RUN, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def chain_run(self):
        run = macrohub.Run('local/c', '아침 묶음', {'kind': 'schedule'})
        macrohub.runs.append(run)
        macrohub.runs_by_id[run.id] = run
        return run

    def feed(self, run, text):
        class P:
            stdout = io.BytesIO(text.encode('utf-8'))
        run.proc = P()
        macrohub._pump(run)

    def test_step_is_running_then_last_run(self):
        run = self.chain_run()
        start = runner.STEP_PREFIX + json.dumps({'id': 'local/web', 'state': 'start', 'name': '웹 확인', 'i': 1, 'n': 1})
        self.feed(run, '🔗 [1/1] 웹 확인 시작\n%s\n   ▶ 웹 확인 시작\n   일하는 중\n' % start)
        step = macrohub.running_run('local/web')
        self.assertIsNotNone(step)
        self.assertIs(step.parent, run)
        self.assertEqual(list(step.lines), ['▶ 웹 확인 시작', '일하는 중'])
        self.assertNotIn(start, list(run.lines))                            # '@@step' 줄은 로그에 안 남는다
        r, err = macrohub.start_run('local/web', path='x')                  # 겹쳐 돌리기 → 알아듣는 말로 거절
        self.assertIsNone(r)
        self.assertIn('이미 실행 중입니다', err)
        self.assertIn('아침 묶음', err)
        self.assertIn('이미 실행 중', macrohub.run_macro('local/web')[1])

        end = runner.STEP_PREFIX + json.dumps({'id': 'local/web', 'state': 'end', 'status': 'ok', 'code': 0})
        self.feed(run, '%s\n✔ [1/1] 웹 확인 성공\n' % end)
        self.assertIsNone(macrohub.running_run('local/web'))
        self.assertEqual(step.status, 'ok')
        view = macrohub.macro_view(macrohub.find_macro('local/web'))
        self.assertEqual(view['last']['status'], 'ok')                      # 「아직 안 돎」이 아니다
        self.assertEqual(view['last']['trigger'], 'chain')
        self.assertIn('아침 묶음', view['last']['detail'])
        with open(self.f_runs, encoding='utf-8') as f:
            rec = json.loads(f.read().splitlines()[-1])
        self.assertEqual((rec['macro'], rec['status']), ('local/web', 'ok'))  # 허브를 다시 켜도 남게
        self.assertEqual(macrohub.LAST_RUN['local/web']['status'], 'ok')

    def test_chain_refused_while_step_runs_alone(self):
        alone = macrohub.Run('local/web', '웹 확인', {'kind': 'manual'})
        macrohub.runs.append(alone)
        r, err = macrohub.run_macro('local/c', None, {'kind': 'manual'})
        self.assertIsNone(r)
        self.assertIn('웹 확인', err)
        self.assertIn('이미 실행 중', err)

    def test_stop_step_stops_chain_and_closes_step(self):
        run = self.chain_run()
        start = runner.STEP_PREFIX + json.dumps({'id': 'local/web', 'state': 'start', 'i': 1, 'n': 1})
        self.feed(run, start + '\n')
        step = macrohub.running_run('local/web')
        killed = []
        with mock.patch.object(macrohub, 'kill_tree', lambda p: killed.append(p)):
            self.assertTrue(macrohub.stop_run(step.id))
        self.assertEqual(killed, [run.proc])
        self.assertTrue(run.stopping)

        class Done:
            stdout = io.BytesIO(b'')

            def wait(self, timeout=None):
                return 1
        run.proc = Done()
        macrohub._watch(run, 5)
        self.assertEqual((run.status, step.status), ('stopped', 'stopped'))
        self.assertIsNone(macrohub.running_run('local/web'))

    def test_runner_emits_step_marks(self):
        tmp = os.path.join(self.tmp, 'm')
        os.makedirs(tmp)
        path = os.path.join(tmp, 'ok1.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write("META = {'name': '첫째'}\n\ndef run(ctx):\n    ctx.log('hi')\n")
        ctx = runner.Ctx({'macro': 'local/c', 'trigger': {'kind': 'manual'}}, {})
        buf = io.StringIO()
        with mock.patch.object(runner, 'macro_path', lambda mid: path), contextlib.redirect_stdout(buf):
            self.assertTrue(runner.run_chain(ctx, {'chain': ['local/ok1']}))
        marks = [json.loads(ln[len(runner.STEP_PREFIX):]) for ln in buf.getvalue().splitlines() if ln.startswith(runner.STEP_PREFIX)]
        self.assertEqual([(m['id'], m['state']) for m in marks], [('local/ok1', 'start'), ('local/ok1', 'end')])
        self.assertEqual((marks[1]['status'], marks[1]['code']), ('ok', 0))


if __name__ == '__main__':
    unittest.main()
