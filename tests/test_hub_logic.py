# -*- coding: utf-8 -*-
"""자동화 허브의 예약·감시 규칙 — 2026-10-06 에 작업 스케줄러를 대신하면서 생긴 로직의 회귀 테스트.

    python -m unittest discover -s tests

- 예약 시각 검사(clean_schedule · valid_days)와 다음 실행 시각(next_fire)
- 놓친 시각 예약 따라잡기(at_due) — '지난번 확인 ~ 지금' 사이에 온 시각만 쏜다
- 바깥 프로그램 넘겨받기 규칙(extsvc._matches) — 띄우는 중간 프로세스는 세지 않는다
허브를 띄우지 않는다(함수만 부른다). 표준 라이브러리만으로 돈다.
"""
import datetime
import json
import os
import sys
import unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import alertmail    # noqa: E402
import extsvc       # noqa: E402
import macrohub     # noqa: E402

DT = datetime.datetime
TUE = DT(2026, 10, 6, 12, 0)                  # 화요일 정오


class CleanSchedule(unittest.TestCase):
    def test_accepts(self):
        self.assertEqual(macrohub.clean_schedule([{'every': '10m'}])[0], [{'type': 'schedule', 'every': '10m'}])
        self.assertEqual(macrohub.clean_schedule([{'at': '09:30'}])[0], [{'type': 'schedule', 'at': '09:30', 'days': 'daily'}])
        self.assertEqual(macrohub.clean_schedule([{'at': '18:00', 'days': 'TUE'}])[0][0]['days'], 'tue')

    def test_removed_theme_reads_as_basic(self):
        macrohub.state['look'] = {'theme': 'mint', 'hero': 'big'}       # 2026-10 에 없앤 테마·잘못된 값 — 기본으로
        self.assertEqual((macrohub.look()['theme'], macrohub.look()['hero']), ('basic', 'hide'))

    def test_rejects(self):
        for bad in ([], [{}], [{'every': '30s'}], [{'every': 'x'}], [{'at': '9:30'}], [{'at': '24:00'}],
                    [{'at': '09:30', 'days': 'tuz'}], [{'at': '09:30', 'days': 'mon-'}], 'nope'):
            with self.subTest(bad=bad):
                items, err = macrohub.clean_schedule(bad)
                self.assertIsNone(items)
                self.assertTrue(err)

    def test_valid_days(self):
        for ok in ('daily', '*', 'mon-fri', 'sat,sun', 'tue', ''):     # 빈 값은 '매일'(days_match 와 같은 규칙)
            self.assertTrue(macrohub.valid_days(ok), ok)
        for bad in ('mon-', ',', 'monday'):
            self.assertFalse(macrohub.valid_days(bad), bad)


class NextFire(unittest.TestCase):
    def test_at_today_and_next_week(self):
        m = {'id': 't'}
        now = TUE.timestamp()
        self.assertEqual(macrohub.next_fire(m, {'at': '18:00', 'days': 'tue'}, now), DT(2026, 10, 6, 18, 0).timestamp())
        self.assertEqual(macrohub.next_fire(m, {'at': '09:30', 'days': 'tue'}, now), DT(2026, 10, 13, 9, 30).timestamp())
        self.assertEqual(macrohub.next_fire(m, {'at': '09:30', 'days': 'mon-fri'}, now), DT(2026, 10, 7, 9, 30).timestamp())

    def test_every_counts_from_last(self):
        m = {'id': 'every-test'}
        macrohub.SCHED_LAST[('every-test', '10m')] = TUE.timestamp() - 120
        self.assertEqual(macrohub.next_fire(m, {'every': '10m'}, TUE.timestamp()), TUE.timestamp() + 480)


    def test_every_survives_restart(self):
        # 허브를 다시 켜도 '10분마다' 는 마지막 실행(runs.jsonl → LAST_RUN)부터 센다
        m = {'id': 'every-restart'}
        last = macrohub.HUB_BOOT - 300
        macrohub.LAST_RUN['every-restart'] = {'started': int(last * 1000)}
        try:
            self.assertAlmostEqual(macrohub.next_fire(m, {'every': '10m'}, last + 1), last + 600, places=0)
        finally:
            macrohub.LAST_RUN.pop('every-restart', None)
            macrohub.SCHED_LAST.pop(('every-restart', '10m'), None)


class AtDue(unittest.TestCase):
    """놓친 예약 따라잡기 — 허브가 뜰 때 sched_from 은 오늘 0시, 그 뒤로는 직전 확인 시각이다."""

    def test_catch_up_on_start(self):
        midnight = TUE.replace(hour=0, minute=0).timestamp()
        self.assertEqual(macrohub.at_due({'at': '09:30'}, midnight, TUE), DT(2026, 10, 6, 9, 30).timestamp())

    def test_not_yet(self):
        midnight = TUE.replace(hour=0, minute=0).timestamp()
        self.assertIsNone(macrohub.at_due({'at': '18:00'}, midnight, TUE))

    def test_edit_to_past_time_does_not_fire(self):
        # 화면에서 이미 지난 시각으로 바꾼 경우 — 직전 확인이 1초 전이라 구간 밖
        self.assertIsNone(macrohub.at_due({'at': '09:30'}, TUE.timestamp() - 1, TUE))

    def test_normal_tick(self):
        at = DT(2026, 10, 6, 18, 0)
        self.assertEqual(macrohub.at_due({'at': '18:00'}, at.timestamp() - 0.5, at.replace(second=0, microsecond=300000)),
                         at.timestamp())

    def test_wrong_day(self):
        midnight = TUE.replace(hour=0, minute=0).timestamp()
        self.assertIsNone(macrohub.at_due({'at': '09:30', 'days': 'mon'}, midnight, TUE))


class ExtsvcMatch(unittest.TestCase):
    spec = {'name': ['python.exe', 'pythonw.exe'], 'has': ['C:\\work-kit\\mail-gateway.py']}

    def test_matches_real_process(self):
        self.assertTrue(extsvc._matches(self.spec, 'pythonw.exe', '"C:\\py\\pythonw.exe" "C:\\work-kit\\mail-gateway.py"'))

    def test_case_insensitive(self):
        self.assertTrue(extsvc._matches(self.spec, 'PythonW.exe', 'pythonw c:\\WORK-KIT\\MAIL-GATEWAY.PY'))

    def test_other_name_or_args(self):
        self.assertFalse(extsvc._matches(self.spec, 'notepad.exe', 'notepad C:\\work-kit\\mail-gateway.py'))
        self.assertFalse(extsvc._matches(self.spec, 'python.exe', 'python C:\\work-kit\\mail-sorter.py'))

    def test_launcher_is_not_the_service(self):
        # 띄우는 중간 프로세스는 커맨드라인에 같은 경로를 품지만 세지 않는다
        cmd = 'python -c "..." "{\\"cmd\\": [\\"C:\\\\work-kit\\\\mail-gateway.py\\"]}" ' + extsvc.LAUNCH_MARK
        self.assertFalse(extsvc._matches(self.spec, 'python.exe', cmd + ' C:\\work-kit\\mail-gateway.py'))

    def test_port_space_guard(self):
        # '0.0.0.0:80 ' 처럼 포트 뒤 공백으로 8000 등과 구분한다
        spec = {'name': ['php.exe'], 'has': ['0.0.0.0:80 ']}
        self.assertTrue(extsvc._matches(spec, 'php.exe', 'php.exe -S 0.0.0.0:80 -t public'))
        self.assertFalse(extsvc._matches(spec, 'php.exe', 'php.exe -S 0.0.0.0:8000 -t public'))


class RunOnceTimeout(unittest.TestCase):
    """예약 실행형이 멈추면 timeout 에 끊겨야 한다(예전엔 출력을 다 읽은 뒤에 기다려 영영 안 끝났다)."""

    class Ctx:
        def __init__(self):
            self.lines = []

        def log(self, s):
            self.lines.append(s)

    def test_hung_program_is_killed(self):
        ctx, t0 = self.Ctx(), datetime.datetime.now()
        with self.assertRaises(RuntimeError):
            extsvc.run_once(ctx, [sys.executable, '-c', 'import time; print("hi", flush=True); time.sleep(60)'], timeout=2)
        self.assertLess((datetime.datetime.now() - t0).total_seconds(), 20)
        self.assertIn('hi', ctx.lines)

    def test_normal_exit_logs_output(self):
        ctx = self.Ctx()
        extsvc.run_once(ctx, [sys.executable, '-c', 'print("done")'], timeout=30)
        self.assertIn('done', ctx.lines)


class HideUnused(unittest.TestCase):
    """안 쓰는 것 숨기기 — 꺼진 자동화·도구 칸만, 지우지도 끄지도 않고 state 'hidden' 에만 적는다(변경 이력에 남김)."""

    def setUp(self):
        from unittest import mock
        self.log = []
        macros = {'job_x': {'id': 'job_x', 'name': 'x'}, 'svc_y': {'id': 'svc_y', 'name': 'y'}}
        for name, val in (('state', {'enabled': {'svc_y': True}}), ('save_state', lambda: None), ('broadcast', lambda *a: None),
                          ('audit', lambda action, target='', detail='': self.log.append((action, target))),
                          ('find_macro', macros.get)):
            p = mock.patch.object(macrohub, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_hide_and_show(self):
        self.assertIsNone(macrohub.set_hidden('job_x', True))
        self.assertIsNone(macrohub.set_hidden('tool:record', True))         # 허브 화면 도구 칸도 숨길 수 있다
        self.assertEqual(macrohub.hidden_ids(), {'job_x', 'tool:record'})
        self.assertIsNone(macrohub.set_hidden('job_x', True))               # 같은 값은 다시 적지 않는다
        self.assertIsNone(macrohub.set_hidden('job_x', False))
        self.assertEqual(macrohub.state['hidden'], ['tool:record'])
        self.assertEqual(self.log, [('숨김', 'job_x'), ('숨김', 'tool:record'), ('다시 보임', 'job_x')])

    def test_enabled_or_unknown_cannot_hide(self):
        self.assertIn('켜져 있는', macrohub.set_hidden('svc_y', True))
        self.assertEqual(macrohub.set_hidden('nope', True), '없는 자동화입니다')
        self.assertEqual(macrohub.hidden_ids(), set())


class DeleteMacro(unittest.TestCase):
    """내 자동화 지우기 — macros.local 의 꺼진 것만, 파일은 data.local\\deleted 로 옮기고 되살릴 수 있다."""

    def setUp(self):
        import shutil
        import tempfile
        from unittest import mock
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.local = os.path.join(tmp, 'macros.local')
        os.makedirs(self.local)
        self.path = os.path.join(self.local, 'my_job.py')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('x = 1\n')
        self.log = []
        self.running = set()
        macros = {'local/my_job': {'id': 'local/my_job', 'name': 'my', 'path': self.path, 'local': True},
                  'local/on_job': {'id': 'local/on_job', 'name': 'on', 'path': self.path, 'local': True},
                  'job_example': {'id': 'job_example', 'name': 'ex', 'path': self.path, 'local': False}}
        state = {'enabled': {'local/on_job': True, 'local/my_job': False}, 'hidden': ['local/my_job'],
                 'schedule': {'local/my_job': [{'type': 'schedule', 'at': '09:00'}]}}
        for name, val in (('state', state), ('save_state', lambda: None), ('broadcast', lambda *a: None),
                          ('audit', lambda action, target='', detail='': self.log.append((action, target))),
                          ('find_macro', macros.get), ('running_run', lambda mid: mid in self.running),
                          ('DIR_LOCAL', self.local), ('DIR_DELETED', os.path.join(tmp, 'deleted'))):
            p = mock.patch.object(macrohub, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_delete_then_restore(self):
        fname, err = macrohub.delete_macro('local/my_job')
        self.assertIsNone(err)
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.exists(os.path.join(macrohub.DIR_DELETED, fname)))
        self.assertNotIn('local/my_job', macrohub.state['enabled'])        # 켜짐·숨김·예약 기록도 같이 지운다
        self.assertEqual(macrohub.state['hidden'], [])
        self.assertEqual(macrohub.state['schedule'], {})
        self.assertEqual([d['name'] for d in macrohub.deleted_macros()], ['my_job'])
        mid, err = macrohub.restore_macro(fname)
        self.assertEqual((mid, err), ('local/my_job', None))
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(macrohub.deleted_macros(), [])
        self.assertEqual([a for a, _ in self.log], ['자동화 지움', '자동화 되살림'])

    def test_refuses(self):
        self.assertIn('예제', macrohub.delete_macro('job_example')[1])
        self.assertIn('켜져 있는', macrohub.delete_macro('local/on_job')[1])
        self.running.add('local/my_job')
        self.assertIn('실행 중', macrohub.delete_macro('local/my_job')[1])
        self.assertEqual(macrohub.delete_macro('nope')[1], '없는 자동화입니다')
        self.assertTrue(os.path.exists(self.path))

    def test_restore_only_listed_and_no_overwrite(self):
        self.assertEqual(macrohub.restore_macro('..\\..\\x.py')[1], '지운 목록에 없습니다')   # 경로 조작은 목록에 없다
        fname, _ = macrohub.delete_macro('local/my_job')
        with open(self.path, 'w', encoding='utf-8') as f:                                    # 그 사이 같은 이름을 새로 만들었다
            f.write('y = 2\n')
        self.assertIn('이미 있습니다', macrohub.restore_macro(fname)[1])
        with open(self.path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'y = 2\n')


class AgentDismiss(unittest.TestCase):
    """/ops 에이전트 — 끝난 작업 「치우기」·「치운 것 되돌리기」(상태 파일은 건드리지 않고 목록 파일에만)."""

    def setUp(self):
        import tempfile
        from unittest import mock
        import ops
        self.ops = ops
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, tmp, True)
        p = mock.patch.object(ops, 'AGENT_DISMISSED', os.path.join(tmp, 'sub', 'agents-dismissed.json'))
        p.start()
        self.addCleanup(p.stop)

    def test_dismiss_and_undo(self):
        self.assertEqual(self.ops.agents_dismissed(), set())
        self.assertEqual(self.ops.agent_dismiss('a1b2')['dismissed'], 1)
        self.assertEqual(self.ops.agent_dismiss('c3-d4')['dismissed'], 2)
        self.assertEqual(self.ops.agents_dismissed(), {'a1b2', 'c3-d4'})
        with self.assertRaises(ValueError):
            self.ops.agent_dismiss('../x')
        self.assertEqual(self.ops.agent_dismiss(undo=True)['dismissed'], 0)
        self.assertEqual(self.ops.agents_dismissed(), set())

    def test_default_path_is_kit_data(self):
        import kit
        from unittest import mock
        with mock.patch.object(self.ops, 'AGENT_DISMISSED', ''):
            self.assertEqual(self.ops._dismissed_path(), os.path.join(kit.DATA, 'agents-dismissed.json'))


class UiMode(unittest.TestCase):
    """화면 모드(자동·라이트·다크) — 허브가 기억한 값을 페이지 <html data-mode> 에 심는다."""
    def setUp(self):
        self._old = macrohub.state.get('theme')

    def tearDown(self):
        macrohub.state['theme'] = self._old

    def test_unknown_is_auto(self):
        for v in (None, '', 'purple', 1):
            with self.subTest(v=v):
                macrohub.state['theme'] = v
                self.assertEqual(macrohub.ui_mode(), 'auto')

    def test_pages_get_mode_and_token(self):
        macrohub.state['theme'] = 'dark'
        for page in ('index.html', 'ops.html'):
            with self.subTest(page=page):
                html = macrohub.render_page(os.path.join(HUB, 'web', page))
                self.assertIn('<html lang="ko" data-mode="dark" data-theme="', html)   # 꾸미기 속성이 뒤에 붙는다
                self.assertNotIn('__MODE__', html)
                self.assertNotIn('__TOKEN__', html)


class AlertMail(unittest.TestCase):
    """실패 알림 메일 — 누가 언제 메일을 받는지(alertmail.should_alert)와 쿨다운. 메일은 실제로 보내지 않는다."""
    ON = alertmail.settings_of(None)
    FAIL = {'macro': 'job_x', 'name': '점검', 'trigger': 'schedule', 'status': 'fail', 'code': 1,
            'started': 1, 'ended': 2, 'tool': False, 'tail': ['Traceback', 'boom']}

    def test_defaults(self):
        self.assertEqual(self.ON, {'on': True, 'cooldown_min': 60})
        self.assertEqual(alertmail.settings_of({'on': False, 'cooldown_min': 'x'}), {'on': False, 'cooldown_min': 60})

    def test_who_gets_mail(self):
        ok = alertmail.should_alert
        self.assertTrue(ok(self.FAIL, {}, 1000, self.ON))
        self.assertTrue(ok(dict(self.FAIL, status='timeout', trigger='service'), {}, 1000, self.ON))
        for rec in (dict(self.FAIL, status='ok'), dict(self.FAIL, status='stopped'),
                    dict(self.FAIL, trigger='manual'), dict(self.FAIL, tool=True)):
            with self.subTest(rec=rec):
                self.assertFalse(ok(rec, {}, 1000, self.ON))
        self.assertFalse(ok(self.FAIL, {}, 1000, {'on': False, 'cooldown_min': 60}))

    def test_cooldown(self):
        ok = alertmail.should_alert
        self.assertFalse(ok(self.FAIL, {'job_x': 1000}, 1000 + 59 * 60, self.ON))
        self.assertTrue(ok(self.FAIL, {'job_x': 1000}, 1000 + 60 * 60, self.ON))
        self.assertTrue(ok(self.FAIL, {'job_y': 1000}, 1001, self.ON))     # 다른 자동화는 따로 센다

    def test_compose(self):
        subject, body = alertmail.compose(self.FAIL, self.ON)
        self.assertIn('예약 작업 실패', subject)
        self.assertIn('점검', subject)
        self.assertIn('boom', body)
        self.assertNotIn('#c', subject)             # 게이트웨이 지시 태그로 읽히면 안 된다

    def test_ask_button(self):
        # 「🔍 원인 봐 줘」 — 읽기 지시, 로그 끝 15줄, 암호 단어는 본문 마지막 줄
        subject, body = alertmail.ask_text(dict(self.FAIL, tail=['x' * 500] + ['line%d' % i for i in range(30)]), '#c', 'kit')
        self.assertTrue(subject.startswith('#c @kit '))
        self.assertTrue(alertmail.ask_text(self.FAIL)[0].startswith('#c 실패 원인'))      # 키트 폴더 키가 없으면 @ 없이
        self.assertIn('line29', body)
        self.assertNotIn('line14', body)
        href = alertmail.ask_mailto('me@example.com', subject, body, 'w0rd')
        self.assertTrue(href.endswith('%0A%0A%5Bk%3Aw0rd%5D'))
        self.assertIn('&lt;b&gt;', alertmail.compose_html('<b>로그</b>', href))

    def test_ask_html_only_when_dispatch_on(self):
        class FakeGw:
            def __init__(self, cfg):
                self.cfg = cfg
            def load_cfg(self):
                return self.cfg
            def word_for_reply(self, cfg, sender):
                return 'w0rd' if sender == 'me@example.com' else None
        base = {'user': 'me@example.com', 'tag': '#c', 'workdir_keys': {'kit': alertmail.kit.ROOT}, 'alert_via': 'append'}
        self.assertIsNone(alertmail.ask_html(self.FAIL, '본문', FakeGw(dict(base, enabled=False))))
        page = alertmail.ask_html(self.FAIL, '본문', FakeGw(dict(base, enabled=True)))
        self.assertIn('🔍 원인 봐 줘', page)
        self.assertIn('%23c%20%40kit', page)
        self.assertIn('%5Bk%3Aw0rd%5D', page)

    def test_gateway_reads_ask_as_read_instruction(self):
        mg = alertmail._load_gateway()
        cfg = dict(mg.DEFAULT_CFG, workdir_keys={'kit': 'C:\kit'}, default_workdir='C:\other')
        subject, body = alertmail.ask_text(self.FAIL, '#c', 'kit')
        prompt, workdir, label, mode = mg.build_instruction(subject, body, cfg)
        self.assertEqual((mode, workdir, label), ('read', 'C:\kit', 'kit'))
        self.assertIn('원인만 찾아 줘', prompt)

    def test_on_run_end_sends_once(self):
        sent_mail = []
        tmp = os.path.join(os.environ.get('TEMP', '.'), 'alertmail-test-%d.json' % os.getpid())
        orig = alertmail.F_SENT, alertmail.F_LOG
        alertmail.F_SENT, alertmail.F_LOG = tmp, tmp + '.log'
        try:
            send = lambda s, b, rec: sent_mail.append(s)
            ready = lambda: (True, '')
            self.assertTrue(alertmail.on_run_end(self.FAIL, None, send=send, ready=ready))
            self.assertFalse(alertmail.on_run_end(self.FAIL, None, send=send, ready=ready))   # 쿨다운
            self.assertEqual(len(sent_mail), 1)
        finally:
            alertmail.F_SENT, alertmail.F_LOG = orig
            for f in (tmp, tmp + '.log'):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def test_skips_quietly_when_mail_not_ready(self):
        # 메일 설정이 없으면(kit.mail_ready False) 예외 없이 건너뛰고, 로그는 한 번만 남긴다
        sent_mail = []
        tmp = os.path.join(os.environ.get('TEMP', '.'), 'alertmail-skip-%d.json' % os.getpid())
        orig = alertmail.F_SENT, alertmail.F_LOG, alertmail.kit.mail_ready, alertmail._unready_logged
        alertmail.F_SENT, alertmail.F_LOG = tmp, tmp + '.log'
        alertmail.kit.mail_ready = lambda m=None: (False, '설정에 없는 값: user')
        alertmail._unready_logged = False
        try:
            send = lambda s, b, rec: sent_mail.append(s)
            self.assertFalse(alertmail.on_run_end(self.FAIL, None, send=send))
            self.assertFalse(alertmail.on_run_end(dict(self.FAIL, macro='job_y'), None, send=send))
            self.assertEqual(sent_mail, [])
            self.assertFalse(os.path.exists(tmp))       # 보낸 기록도 남기지 않는다 — 설정을 채우면 바로 알린다
            with open(tmp + '.log', encoding='utf-8') as f:
                self.assertEqual(len(f.read().splitlines()), 1)
        finally:
            alertmail.F_SENT, alertmail.F_LOG, alertmail.kit.mail_ready, alertmail._unready_logged = orig
            for f in (tmp, tmp + '.log'):
                try:
                    os.remove(f)
                except OSError:
                    pass


class TestRunButton(unittest.TestCase):
    """🧪 시험 실행 — 내 자동화만, for_real 동작은 건너뛰고, 실행 기록·마지막 결과에 남지 않는다. META steps 는 카드로 간다."""

    def setUp(self):
        import shutil
        import tempfile
        from unittest import mock
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.local, ex = os.path.join(tmp, 'macros.local'), os.path.join(tmp, 'macros')
        os.makedirs(self.local)
        os.makedirs(ex)
        self.path = os.path.join(self.local, 'mail_job.py')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('META = {"name": "메일 보내기", "steps": ["표 읽기", "  ", "메일 보내기"]}\n\n'
                    'def run(ctx):\n'
                    '    ctx.log("dry=%s" % ctx.dry_run)\n'
                    '    if ctx.for_real("메일 보내기"):\n'
                    '        ctx.log("SENT")\n')
        self.runs_file = os.path.join(tmp, 'runs.jsonl')
        for name, val in (('broadcast', lambda *a: None), ('F_RUNS', self.runs_file),
                          ('DIR_LOCAL', self.local), ('DIR_EXAMPLE', ex), ('_cache', {'sig': None, 'items': []}),
                          ('state', {'enabled': {}, 'hidden': []})):
            p = mock.patch.object(macrohub, name, val)
            p.start()
            self.addCleanup(p.stop)

    def wait(self, run):
        import time
        for _ in range(300):
            if run.ended:
                return
            time.sleep(0.1)
        self.fail('시험 실행이 끝나지 않음')

    def test_steps_from_meta(self):
        m = macrohub.find_macro('local/mail_job')
        self.assertEqual(m['steps'], ['표 읽기', '메일 보내기'])               # 빈 단계는 뺀다

    def test_test_run_skips_for_real(self):
        run, err = macrohub.run_macro('local/mail_job', {}, {'kind': 'test'})
        self.assertIsNone(err)
        self.wait(run)
        text = '\n'.join(run.lines)
        self.assertEqual(run.status, 'ok', text)
        self.assertIn('dry=True', text)
        self.assertIn('🧪 시험이라 건너뜀: 메일 보내기', text)
        self.assertNotIn('SENT', text)
        self.assertIn('🧪 시험 결과: 성공', run.lines[-1])
        self.assertIn('시험', run.name)
        self.assertFalse(os.path.exists(self.runs_file))                      # 실행 기록·실패 알림에 넣지 않는다
        self.assertIsNone(macrohub.macro_view(macrohub.find_macro('local/mail_job'))['last'])

    def test_recording_secret_runs(self):
        """녹화 스크립트(kind script)에서 secret() 을 쓸 수 있다 — 값은 로그에서 가려진다."""
        from unittest import mock
        sec = os.path.join(os.path.dirname(self.local), 'secrets.local.json')
        with open(sec, 'w', encoding='utf-8') as f:
            json.dump({'rec_비밀번호': 'pa55word'}, f)
        path = os.path.join(self.local, 'rec.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('META = {"name": "rec", "kind": "script"}\nprint("pw=" + secret("rec_비밀번호"))\n')
        with mock.patch.dict(os.environ, {'MACROHUB_SECRETS': sec}):
            run, err = macrohub.run_macro('local/rec', {}, {'kind': 'test'})
            self.assertIsNone(err)
            self.wait(run)
        text = '\n'.join(run.lines)
        self.assertEqual(run.status, 'ok', text)
        self.assertIn('pw=●●●', text)
        self.assertNotIn('pa55word', text)

    def test_refuses_builtin(self):
        with open(os.path.join(macrohub.DIR_EXAMPLE, 'job_x.py'), 'w', encoding='utf-8') as f:
            f.write('META = {"name": "x"}\n\ndef run(ctx):\n    pass\n')
        run, err = macrohub.run_macro('job_x', {}, {'kind': 'test'})
        self.assertIsNone(run)
        self.assertIn('내 자동화', err)


class LookCustom(unittest.TestCase):
    """🎨 꾸미기 — 색 테마·내 강조색·배치 값 검사와 <html> 속성."""

    def setUp(self):
        from unittest import mock
        p = mock.patch.object(macrohub, 'state', {'enabled': {}})
        p.start()
        self.addCleanup(p.stop)

    def test_default_and_attrs(self):
        self.assertEqual(macrohub.look()['theme'], 'basic')
        a = macrohub.look_attrs()
        self.assertIn('data-theme="basic"', a)
        self.assertIn('data-hero="hide"', a)                            # 화면 펫 무대는 기본 숨김
        self.assertNotIn('style=', a)                                  # 내 색이 없으면 style 도 없다

    def test_clean_and_custom_color(self):
        lk, err = macrohub.clean_look({'theme': 'navy', 'accent': '#AA3366', 'swap': 1, 'zzz': 'x'})
        self.assertIsNone(err)
        self.assertEqual((lk['theme'], lk['accent'], lk['swap'], lk['cols']), ('navy', '#aa3366', True, '2'))
        self.assertNotIn('zzz', lk)
        a = macrohub.look_attrs(lk)
        self.assertIn('data-swap="1"', a)
        self.assertIn('--accent:light-dark(#aa3366,', a)
        self.assertIn('--accentsoft:', a)

    def test_removed_theme_reads_as_basic(self):
        macrohub.state['look'] = {'theme': 'mint', 'hero': 'big'}       # 2026-10 에 없앤 테마·잘못된 값 — 기본으로
        self.assertEqual((macrohub.look()['theme'], macrohub.look()['hero']), ('basic', 'hide'))

    def test_rejects(self):
        for bad in ({'theme': 'neon'}, {'hero': 'big'}, {'cols': '3'}, {'accent': 'red'},
                    {'accent': '#12345'}, {'accent2': '" onload="x'}):
            with self.subTest(bad=bad):
                self.assertIsNone(macrohub.clean_look(bad)[0])

    def test_render_page_injects(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write('<html lang="ko" data-mode="__MODE__"><script>const TOKEN=\'__TOKEN__\'</script>')
        self.addCleanup(os.remove, f.name)
        macrohub.state['look'] = {'theme': 'pastel', 'hero': 'show'}
        page = macrohub.render_page(f.name)
        self.assertIn('data-theme="pastel"', page)                     # 예전 모양
        self.assertIn('data-hero="show"', page)
        self.assertNotIn('__MODE__', page)


class SecretizeRecording(unittest.TestCase):
    """녹화 저장 — 비밀번호 칸에 넣은 값은 파일에 남기지 않고 secret("키") 로, 값은 secrets.local.json 으로."""

    CODE = ('    page.get_by_label("아이디").fill("smith")\n'
            '    page.get_by_label("비밀번호").fill("s3cr\\"et")\n'
            '    page.locator("#userPwd").press("Enter")\n'
            '    page.get_by_role("textbox", name="Password").fill("s3cr\\"et")\n'
            '    page.locator("input[name=\'pw\']").fill(\'other\')\n'
            '    page.get_by_placeholder("암호").fill("")\n')

    def test_moves_password_values(self):
        code, found = macrohub.secretize_recording(self.CODE, 'login')
        self.assertEqual(found, {'login_비밀번호': 's3cr"et', 'login_비밀번호_2': 'other'})   # 같은 값은 한 키
        self.assertIn('fill("smith")', code)                              # 아이디는 그대로
        self.assertNotIn('s3cr', code)
        self.assertNotIn('other', code)
        self.assertEqual(code.count("secret('login_비밀번호')"), 2)
        self.assertIn("fill(secret('login_비밀번호_2'))", code)
        self.assertIn('.press("Enter")', code)                            # fill 이 아닌 줄은 그대로
        self.assertIn('fill("")', code)                                   # 빈 값은 옮길 것이 없다

    def test_save_secrets_keeps_others(self):
        import shutil
        import tempfile
        from unittest import mock
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        sec = os.path.join(tmp, 'secrets.local.json')
        with mock.patch.object(macrohub.runner, 'SECRETS', sec):
            macrohub.save_secrets({'a': '1'})                             # 없으면 새로 만든다
            macrohub.save_secrets({'b': '비번'})
        with open(sec, encoding='utf-8') as f:
            data = json.load(f)
        self.assertTrue(all(v.startswith('dpapi:') for v in data.values()))     # 녹화에서 옮긴 값도 암호화해서
        self.assertEqual({k: macrohub.hubutil.open_secret(v) for k, v in data.items()}, {'a': '1', 'b': '비번'})

    def test_encrypt_file_in_place(self):
        """사람이 평문으로 넣어 둔 값은 그 자리에서 DPAPI 로 — 설명(_)·빈 값·이미 암호화된 값은 그대로."""
        import shutil
        import tempfile
        hu = macrohub.hubutil
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        sec = os.path.join(tmp, 'secrets.local.json')
        sealed = hu.seal('old')
        with open(sec, 'w', encoding='utf-8') as f:
            json.dump({'_comment': '설명', 'id': 'me', 'pw': 'p@ss"w', 'empty': '', 'done': sealed}, f)
        self.assertEqual(hu.encrypt_secrets_file(sec), 2)
        self.assertEqual(hu.encrypt_secrets_file(sec), 0)                        # 두 번째는 할 것 없음
        with open(sec, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual((data['_comment'], data['empty'], data['done']), ('설명', '', sealed))
        self.assertNotIn('p@ss', json.dumps(data))
        self.assertEqual([hu.open_secret(data[k]) for k in ('id', 'pw', 'done')], ['me', 'p@ss"w', 'old'])
        self.assertEqual(hu.encrypt_secrets_file(os.path.join(tmp, 'none.json')), 0)


if __name__ == '__main__':
    unittest.main()
