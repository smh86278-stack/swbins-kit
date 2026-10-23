# -*- coding: utf-8 -*-
"""5차 4번 나만의 자동화 강화 — 📚 갤러리 · 녹화 입력값 칸(param) · 📸 실패 화면 · 🔗 묶음.

허브를 띄우지 않고 진짜 사이트·메일·화면 캡처 없이 — 캡처는 가짜 page·grab, 메일은 kit.alert 를 바꿔 끼운다.
묶음은 runner.py 자식 프로세스를 진짜로 띄우되 단계 자동화는 임시 폴더의 작은 ctx 파일이다.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
import alertmail  # noqa: E402
import kit        # noqa: E402
import macrohub   # noqa: E402
import runner     # noqa: E402


class Base(unittest.TestCase):
    """허브 상태 파일·변경 이력·화면 알림을 건드리지 않게 — 내 자동화 폴더는 임시 폴더로."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.local = os.path.join(self.tmp, 'macros.local')
        os.makedirs(self.local)
        st = {'enabled': {}}
        for target, attr, val in ((macrohub, 'DIR_LOCAL', self.local), (macrohub, 'state', st),
                                  (macrohub, 'save_state', lambda: None), (macrohub, 'audit', lambda *a, **k: None),
                                  (macrohub, 'broadcast', lambda *a, **k: None)):
            p = mock.patch.object(target, attr, val)
            p.start()
            self.addCleanup(p.stop)
        macrohub._cache['sig'] = None
        self.addCleanup(macrohub._cache.update, sig=None)

    def write(self, name, meta, body='def run(ctx):\n    ctx.log("ok")\n', where=None):
        path = os.path.join(where or self.local, name + '.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('# -*- coding: utf-8 -*-\nMETA = %r\n\n%s' % (meta, body))
        return path


class Paramize(unittest.TestCase):
    CODE = '\n'.join([
        '    page.get_by_label("검색어").fill("사과")',
        '    page.get_by_placeholder("이메일").fill("a@example.com")',
        '    page.get_by_role("textbox", name="수량").fill("3")',
        '    page.locator("#memo").fill("메모")',
        '    page.get_by_label("검색어").fill("배")',
        '    page.get_by_label("검색어").fill("사과")',
        '    page.get_by_label("비밀번호").fill("pw1234")',
        '    page.locator("div").first.fill("x")',
        '    page.get_by_label("검색어").press("Enter")',
        '    page.get_by_label("빈칸").fill("")',
    ])

    def test_fields_become_params_secrets_stay_secret(self):
        code, found = macrohub.secretize_recording(self.CODE, 'rec')
        code, params = macrohub.paramize_recording(code)
        self.assertEqual(found, {'rec_비밀번호': 'pw1234'})
        self.assertEqual(params, {'검색어': '사과', '이메일': 'a@example.com', '수량': '3', 'memo': '메모', '검색어_2': '배', '입력': 'x'})
        self.assertEqual(code.count("param('검색어')"), 2)                     # 같은 칸·같은 값은 한 칸
        self.assertIn("fill(secret('rec_비밀번호'))", code)                     # 비밀번호는 칸이 아니라 secret
        self.assertNotIn('pw1234', code)
        self.assertNotIn('"사과"', code)
        self.assertIn('.press("Enter")', code)
        self.assertIn('fill("")', code)

    def test_ctx_param_and_script_gets_param(self):
        ctx = runner.Ctx({'params': {'n': 3, 'none': None}}, {})
        self.assertEqual(ctx.param('n'), '3')
        self.assertEqual(ctx.param('none'), '')
        self.assertEqual(ctx.param('missing', 'd'), 'd')
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, 'rec_script.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write("META = {'name': '녹화', 'kind': 'script', 'params': {'검색어': '사과'}}\nprint('값=' + param('검색어'))\n")
        env = dict(os.environ, PYTHONIOENCODING='utf-8', MACROHUB_CTX=json.dumps({'macro': 'x', 'params': {'검색어': '배'}}))
        r = subprocess.run([sys.executable, os.path.join(HUB, 'runner.py'), path], capture_output=True, env=env, timeout=60, cwd=HUB)
        self.assertEqual(r.returncode, 0, r.stdout.decode('utf-8', 'replace'))
        self.assertIn('값=배', r.stdout.decode('utf-8', 'replace'))


class Gallery(Base):
    def test_list_has_samples_with_steps_and_params(self):
        items = macrohub.gallery_list()
        self.assertGreaterEqual(len(items), 3)
        for g in items:
            with self.subTest(g['file']):
                self.assertTrue(g['name'] and g['desc'] and g['steps'])
                self.assertTrue(g['params'])
                self.assertEqual(g['triggers'] == [] or all(t.get('type') == 'schedule' for t in g['triggers']), True)
        self.assertIn('site_login_check', [g['file'] for g in items])

    def test_samples_have_no_real_addresses(self):
        import re
        for fn in os.listdir(macrohub.DIR_GALLERY):
            if fn.endswith('.py'):
                text = open(os.path.join(macrohub.DIR_GALLERY, fn), encoding='utf-8').read()
                for host in re.findall(r'https?://([\w.-]+)', text):
                    self.assertTrue(host == 'example.com' or host.endswith('.example.com'), (fn, host))

    def test_copy_twice_gets_suffix_and_name(self):
        mid, err = macrohub.copy_gallery('checkin_reminder')
        self.assertIsNone(err)
        self.assertEqual(mid, 'local/checkin_reminder')
        mid2, err = macrohub.copy_gallery('checkin_reminder')
        self.assertEqual(mid2, 'local/checkin_reminder_2')
        meta2 = runner.read_meta(os.path.join(self.local, 'checkin_reminder_2.py'))
        self.assertEqual(meta2['name'], '출근 체크 알림 (2)')
        self.assertEqual(runner.read_meta(os.path.join(self.local, 'checkin_reminder.py'))['name'], '출근 체크 알림')
        m = macrohub.find_macro('local/checkin_reminder_2')
        self.assertTrue(m and m['local'])
        self.assertFalse(macrohub.state['enabled'].get(mid2))             # 꺼진 채

    def test_copy_rejects_unknown_and_paths(self):
        for bad in ('', 'nope', '../runner', '..\\macrohub', 'job_backup'):
            with self.subTest(bad=bad):
                self.assertEqual(macrohub.copy_gallery(bad)[0], None)

    def test_checkin_runs_in_test_mode(self):
        path = os.path.join(macrohub.DIR_GALLERY, 'checkin_reminder.py')
        r = subprocess.run([sys.executable, os.path.join(HUB, 'runner.py'), '--test', path, 'url=', 'mail=yes'],
                           capture_output=True, timeout=60, cwd=HUB, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        out = r.stdout.decode('utf-8', 'replace')
        self.assertEqual(r.returncode, 0, out)
        self.assertIn('@@notify', out)
        self.assertIn('🧪 시험이라 건너뜀: 알림 메일 보내기', out)

    def test_csv_tidy_test_mode_counts_without_writing(self):
        folder = os.path.join(self.tmp, 'csv')
        os.makedirs(folder)
        with open(os.path.join(folder, 'a.csv'), 'w', encoding='cp949', newline='') as f:
            f.write(' 이름 , 값 \r\n사과,1\r\n\r\n사과,1\r\n배 ,2\r\n')
        path = os.path.join(macrohub.DIR_GALLERY, 'csv_tidy.py')
        r = subprocess.run([sys.executable, os.path.join(HUB, 'runner.py'), '--test', path, 'folder=' + folder, 'days=0'],
                           capture_output=True, timeout=60, cwd=HUB, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        out = r.stdout.decode('utf-8', 'replace')
        self.assertEqual(r.returncode, 0, out)
        self.assertIn('a.csv — 3줄 남김 · 빈 줄 1 · 같은 줄 1', out)
        self.assertFalse(os.path.exists(os.path.join(folder, 'a_정리.csv')))   # 시험이면 저장하지 않는다

    def test_csv_tidy_functions(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('g_csv', os.path.join(macrohub.DIR_GALLERY, 'csv_tidy.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows, empty, dup = mod.tidy([[' a ', 'b', ''], ['', ' '], ['a', 'b'], ['c']], dedupe=True)
        self.assertEqual((rows, empty, dup), ([['a', 'b'], ['c']], 1, 1))
        self.assertEqual(mod.tidy([['a'], ['a']], dedupe=False)[0], [['a'], ['a']])


class Params(Base):
    def setUp(self):
        super().setUp()
        self.write('p', {'name': '칸', 'params': {'url': 'https://example.com', 'n': 1}})

    def test_save_typed_and_drop_defaults(self):
        keep, err = macrohub.save_params('local/p', {'url': 'https://example.com/x', 'n': '1', 'bad': 'z'})
        self.assertIsNone(err)
        self.assertEqual(keep, {'url': 'https://example.com/x'})          # n 은 기본값과 같아 뺀다, 없는 칸은 버린다
        keep, _ = macrohub.save_params('local/p', {'n': '5'})
        self.assertEqual(keep, {'n': 5})                                  # 숫자 기본값이면 숫자로
        self.assertEqual(macrohub.save_params('local/p', {})[0], {})
        self.assertNotIn('local/p', macrohub.state.get('params') or {})
        self.assertTrue(macrohub.save_params('local/none', {})[1])

    def test_run_uses_saved_then_passed(self):
        macrohub.save_params('local/p', {'url': 'https://example.com/saved'})
        with mock.patch.object(macrohub, 'start_run', lambda *a, **k: (a, k)):
            args, kw = macrohub.run_macro('local/p', {'n': '9'}, {'kind': 'manual'})
        self.assertEqual(args[1], {'url': 'https://example.com/saved', 'n': '9'})
        self.assertIsNone(kw['extra'])


class Chain(Base):
    def setUp(self):
        super().setUp()
        self.write('a', {'name': '하나', 'params': {'n': 1}, 'timeout': 60})
        self.write('b', {'name': '둘', 'timeout': 30})
        self.write('svc', {'name': '상시', 'service': True})

    def test_new_chain_file_and_schedule(self):
        mid, err = macrohub.new_chain('아침 묶음', ['local/a', 'local/b'], keep_going=True, at='09:10', days='mon-fri')
        self.assertIsNone(err)
        meta = runner.read_meta(os.path.join(self.local, '아침_묶음.py'))
        self.assertEqual(meta['kind'], 'chain')
        self.assertEqual(meta['chain'], ['local/a', 'local/b'])
        self.assertEqual(meta['steps'], ['하나', '둘'])
        self.assertTrue(meta['keep_going'])
        self.assertEqual(meta['triggers'], [{'type': 'schedule', 'at': '09:10', 'days': 'mon-fri'}])
        self.assertEqual(meta['timeout'], 60 + 30 + 60)
        m = macrohub.find_macro(mid)
        self.assertEqual(m['chain'], ['local/a', 'local/b'])
        self.assertIn(mid, [s['id'] for s in macrohub.schedule_view()])     # ⏰ 예약 화면에 같이 뜬다
        view = macrohub.macro_view(m)
        self.assertEqual(view['chain_names'], ['하나', '둘'])

    def test_new_chain_rejects(self):
        for args in (('', ['local/a', 'local/b']), ('x', ['local/a']), ('x', ['local/a', 'local/zz']),
                     ('x', ['local/a', 'local/svc']), ('x', 'local/a'), ('x', ['local/a', 'local/b'] * 11)):
            with self.subTest(args=args):
                self.assertIsNone(macrohub.new_chain(*args)[0])
        self.assertTrue(macrohub.new_chain('x', ['local/a', 'local/b'], at='25:00')[1])
        macrohub.new_chain('c1', ['local/a', 'local/b'])
        self.assertIn('묶음', macrohub.new_chain('x2', ['local/a', 'local/c1'])[1])   # 묶음 안에 묶음 금지
        self.assertTrue(macrohub.new_chain('c1', ['local/a', 'local/b'])[1])          # 같은 이름

    def test_run_macro_passes_saved_step_params(self):
        mid, _ = macrohub.new_chain('c', ['local/a', 'local/b'])
        macrohub.save_params('local/a', {'n': '7'})
        with mock.patch.object(macrohub, 'start_run', lambda *a, **k: (a, k)):
            args, kw = macrohub.run_macro(mid, None, {'kind': 'schedule'})
        self.assertEqual(kw['extra'], {'chain_params': {'local/a': {'n': 7}, 'local/b': {}}})


STEP = '''def run(ctx):
    ctx.log("step=%s n=%s dry=%s chain=%s" % (ctx.macro, ctx.params.get("n"), ctx.dry_run, ctx.trigger.get("chain")))
    if ctx.params.get("boom"):
        raise RuntimeError("일부러 실패")
'''


class RunChain(Base):
    def setUp(self):
        super().setUp()
        self.paths = {
            'local/ok1': self.write('ok1', {'name': '첫째', 'params': {'n': 1}}, STEP),
            'local/bad': self.write('bad', {'name': '둘째', 'params': {'boom': 1}}, STEP),
            'local/ok3': self.write('ok3', {'name': '셋째'}, STEP),
            'example_x': self.write('example_x', {'name': '예제'}, STEP),
        }
        p = mock.patch.object(runner, 'macro_path', lambda mid: self.paths.get(mid))
        p.start()
        self.addCleanup(p.stop)

    def chain(self, steps, keep=False, dry=False, chain_params=None):
        ctx = runner.Ctx({'macro': 'local/c', 'trigger': {'kind': 'manual'}, 'dry_run': dry,
                          'chain_params': chain_params or {}}, {})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = runner.run_chain(ctx, {'chain': steps, 'keep_going': keep})
        return ok, buf.getvalue()

    def test_all_ok_in_order_with_saved_params(self):
        ok, out = self.chain(['local/ok1', 'local/ok3'], chain_params={'local/ok1': {'n': 7, 'zz': 1}})
        self.assertTrue(ok, out)
        self.assertLess(out.index('step=local/ok1 n=7'), out.index('step=local/ok3'))
        self.assertIn('chain=local/c', out)
        self.assertIn('묶음 결과: 2개 중 성공 2 · 실패 0', out)

    def test_stops_on_failure(self):
        ok, out = self.chain(['local/ok1', 'local/bad', 'local/ok3'])
        self.assertFalse(ok)
        self.assertIn('✖ [2/3] 둘째 실패', out)
        self.assertIn('나머지 1개는 돌리지 않습니다', out)
        self.assertNotIn('step=local/ok3', out)

    def test_keep_going(self):
        ok, out = self.chain(['local/ok1', 'local/bad', 'local/ok3'], keep=True)
        self.assertFalse(ok)                                               # 하나라도 실패하면 묶음도 실패
        self.assertIn('step=local/ok3', out)
        self.assertIn('3개 중 성공 2 · 실패 1', out)

    def test_dry_run_skips_kit_examples_and_passes_dry(self):
        ok, out = self.chain(['local/ok1', 'example_x'], dry=True)
        self.assertTrue(ok, out)
        self.assertIn('dry=True', out)
        self.assertIn('🧪 시험이라 건너뜀: [2/2] 기본 자동화 「예제」', out)
        self.assertNotIn('step=example_x', out)

    def test_missing_step(self):
        ok, out = self.chain(['local/ok1', 'local/gone'], keep=True)
        self.assertFalse(ok)
        self.assertIn('없는 자동화입니다', out)



class MacroPath(unittest.TestCase):
    def test_macro_path_rules(self):
        self.assertTrue(runner.macro_path('local/x').endswith(os.path.join('macros.local', 'x.py')))
        self.assertTrue(runner.macro_path('example_web').endswith(os.path.join('macros', 'example_web.py')))
        for bad in ('../x', 'local/../x', 'a b', '', None, 'local\\x'):
            self.assertIsNone(runner.macro_path(bad), bad)


class FakePage:
    def __init__(self, fail=False):
        self.fail = fail
        self.shots = []

    def screenshot(self, path, timeout=None):
        if self.fail:
            raise RuntimeError('closed')
        with open(path, 'wb') as f:
            f.write(b'\x89PNG fake')
        self.shots.append(path)


class FakeContext:
    def __init__(self, pages):
        self.pages = pages


class FailShot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(runner, 'FAILSHOT_DIR', self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def cap(self, *a, **k):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            path = runner.capture_failure(*a, **k)
        return path, buf.getvalue()

    def test_web_page_last_tab_first(self):
        first, last = FakePage(), FakePage()
        path, out = self.cap('local/x', {'target': 'web'}, [FakeContext([first, last])])
        self.assertTrue(path and os.path.isfile(path))
        self.assertEqual(last.shots, [path])
        self.assertEqual(first.shots, [])
        self.assertTrue(os.path.basename(path).startswith('local_x-'))
        self.assertIn(runner.FAILSHOT_PREFIX + path, out)
        self.assertIn('📸', out)

    def test_dead_page_falls_back_to_earlier(self):
        good = FakePage()
        path, _ = self.cap('m', {'target': 'web'}, [FakeContext([good, FakePage(fail=True)])])
        self.assertEqual(good.shots, [path])

    def test_desktop_grabs_screen_web_without_page_skips(self):
        def grab(p):
            with open(p, 'wb') as f:
                f.write(b'png')
        path, out = self.cap('d', {'target': 'desktop'}, [], grab=grab)
        self.assertTrue(path and os.path.isfile(path))
        self.assertEqual(self.cap('w', {'target': 'web'}, [], grab=grab), (None, ''))

    def test_grab_failure_is_quiet(self):
        def grab(p):
            raise OSError('no screen')
        self.assertEqual(self.cap('d', {'target': 'desktop'}, [], grab=grab), (None, ''))

    def test_prune_keeps_newest(self):
        for i in range(5):
            p = os.path.join(self.tmp, 'm-%d.png' % i)
            open(p, 'wb').close()
            os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
        runner.prune_failshots(keep=2, folder=self.tmp)
        self.assertEqual(sorted(os.listdir(self.tmp)), ['m-3.png', 'm-4.png'])

    def test_hub_reads_failshot_line(self):
        shot = os.path.join(self.tmp, 'local_x-20261023-090000.png')
        open(shot, 'wb').close()

        class P:
            stdout = io.BytesIO(('줄 하나\n%s%s\n끝\n' % (runner.FAILSHOT_PREFIX, shot)).encode('utf-8'))
        run = macrohub.Run('local/x', 'x', {'kind': 'schedule'})
        run.proc = P()
        with mock.patch.object(macrohub, 'broadcast', lambda *a: None):
            macrohub._pump(run)
        self.assertEqual(run.shot, shot)
        self.assertEqual(list(run.lines), ['줄 하나', '끝'])                # '@@failshot' 줄은 로그에 안 남는다
        self.assertEqual(run.summary()['shot'], os.path.basename(shot))

    def test_failshot_file_guards(self):
        name = 'ok-1.png'
        open(os.path.join(self.tmp, name), 'wb').close()
        self.assertEqual(macrohub.failshot_file(name), os.path.join(self.tmp, name))
        for bad in ('../x.png', '..\\x.png', 'x.jpg', 'missing.png', '', None, 'a/b.png'):
            self.assertIsNone(macrohub.failshot_file(bad), bad)

    def test_runner_web_failure_without_browser_has_no_shot(self):
        path = os.path.join(self.tmp, 'boom.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write("META = {'name': '터짐', 'target': 'web'}\n\ndef run(ctx):\n    raise RuntimeError('x')\n")
        r = subprocess.run([sys.executable, os.path.join(HUB, 'runner.py'), '--test', path], capture_output=True,
                           timeout=60, cwd=HUB, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        out = r.stdout.decode('utf-8', 'replace')
        self.assertEqual(r.returncode, 1)
        self.assertIn('✖ 실패', out)
        self.assertNotIn('@@failshot', out)


class AlertAttach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.shot = os.path.join(self.tmp, 'x.png')
        with open(self.shot, 'wb') as f:
            f.write(b'\x89PNG')

    def test_deliver_attaches_shot(self):
        got = {}
        rec = {'macro': 'local/x', 'name': 'x', 'status': 'fail', 'trigger': 'schedule', 'shot_file': self.shot}
        with mock.patch.object(kit, 'alert', lambda s, b, **k: got.update(k, body=b)), \
                mock.patch.object(alertmail, 'ask_html', lambda rec, body: None):
            subject, body = alertmail.compose(rec, alertmail.settings_of({}))
            alertmail.deliver(subject, body, rec)
        self.assertEqual(got['attachments'], [self.shot])
        self.assertIn('📸 실패한 순간 화면을 붙였습니다 — x.png', got['body'])

    def test_no_or_missing_shot(self):
        got = {}
        with mock.patch.object(kit, 'alert', lambda s, b, **k: got.update(k)), \
                mock.patch.object(alertmail, 'ask_html', lambda rec, body: None):
            alertmail.deliver('s', 'b', {'shot_file': os.path.join(self.tmp, 'gone.png')})
        self.assertIsNone(got['attachments'])
        self.assertIsNone(alertmail.shot_of(None))

    def test_kit_alert_passes_attachments_to_mail(self):
        got = {}
        m = {'user': 'me@example.com', 'alert_via': 'smtp'}
        with mock.patch.object(kit, 'mail_ready', lambda m=None: (True, '')), \
                mock.patch.object(kit, 'section', lambda name, default=None, cfg=None: default), \
                mock.patch.object(kit, 'company_name', lambda cfg=None: ''), \
                mock.patch.object(kit, '_notify_log', lambda *a, **k: None), \
                mock.patch.object(kit, 'send_mail', lambda to, s, b, **k: got.update(k)):
            kit.alert('제목', '본문', m=m, channels=[], attachments=[self.shot])
        self.assertEqual(got['attachments'], [self.shot])
        msg = kit.build_message('me@example.com', 'me@example.com', 's', 'b', attachments=[self.shot], html='<b>b</b>')
        names = [p.get_filename() for p in msg.iter_attachments()]
        self.assertEqual(names, ['x.png'])


if __name__ == '__main__':
    unittest.main()
