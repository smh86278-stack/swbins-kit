# -*- coding: utf-8 -*-
"""매크로 허브의 예약·감시 규칙 — 2026-10-06 에 작업 스케줄러를 대신하면서 생긴 로직의 회귀 테스트.

    python -m unittest discover -s tests

- 예약 시각 검사(clean_schedule · valid_days)와 다음 실행 시각(next_fire)
- 놓친 시각 예약 따라잡기(at_due) — '지난번 확인 ~ 지금' 사이에 온 시각만 쏜다
- 바깥 프로그램 넘겨받기 규칙(extsvc._matches) — 띄우는 중간 프로세스는 세지 않는다
허브를 띄우지 않는다(함수만 부른다). 표준 라이브러리만으로 돈다.
"""
import datetime
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
                self.assertIn('<html lang="ko" data-mode="dark">', html)
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
        self.assertTrue(ok(self.FAIL, {'job_y': 1000}, 1001, self.ON))     # 다른 매크로는 따로 센다

    def test_compose(self):
        subject, body = alertmail.compose(self.FAIL, self.ON)
        self.assertIn('예약 작업 실패', subject)
        self.assertIn('점검', subject)
        self.assertIn('boom', body)
        self.assertNotIn('#c', subject)             # 게이트웨이 지시 태그로 읽히면 안 된다

    def test_on_run_end_sends_once(self):
        sent_mail = []
        tmp = os.path.join(os.environ.get('TEMP', '.'), 'alertmail-test-%d.json' % os.getpid())
        orig = alertmail.F_SENT, alertmail.F_LOG
        alertmail.F_SENT, alertmail.F_LOG = tmp, tmp + '.log'
        try:
            send = lambda s, b: sent_mail.append(s)
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
            send = lambda s, b: sent_mail.append(s)
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


if __name__ == '__main__':
    unittest.main()
