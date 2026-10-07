# -*- coding: utf-8 -*-
"""키트 공통 바탕(tools\\macro-hub\\kit.py) — 예약 시각 판정 · 자리표시 · 메일 준비 · DPAPI 왕복.

    python -X utf8 -m unittest tests.test_kit -v

네트워크·메일 서버에 붙지 않는다(메일은 보내지 않는다). 설정 파일도 읽거나 쓰지 않는다.
"""
import datetime
import os
import sys
import unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import kit  # noqa: E402

DT = datetime.datetime
D = datetime.date
TUE = DT(2026, 10, 6, 12, 0)                  # 화요일 정오


class DaysMatch(unittest.TestCase):
    def test_daily(self):
        for days in ('daily', '*', '', None, 'DAILY'):
            with self.subTest(days=days):
                self.assertTrue(kit.days_match(days, D(2026, 10, 4)))

    def test_weekday_ranges(self):
        self.assertTrue(kit.days_match('mon-fri', D(2026, 10, 6)))       # 화
        self.assertFalse(kit.days_match('mon-fri', D(2026, 10, 4)))      # 일
        self.assertTrue(kit.days_match('sat,sun', D(2026, 10, 4)))
        self.assertTrue(kit.days_match('tue', D(2026, 10, 6)))
        self.assertFalse(kit.days_match('wed', D(2026, 10, 6)))
        self.assertTrue(kit.days_match('fri-mon', D(2026, 10, 4)))       # 넘어가는 범위(금~월)의 일요일
        self.assertFalse(kit.days_match('fri-mon', D(2026, 10, 7)))      # 수

    def test_month_days_and_last(self):
        self.assertTrue(kit.days_match('1,15', D(2026, 10, 15)))
        self.assertFalse(kit.days_match('1,15', D(2026, 10, 14)))
        self.assertTrue(kit.days_match('last', D(2026, 10, 31)))
        self.assertTrue(kit.days_match('last', D(2028, 2, 29)))         # 윤년
        self.assertFalse(kit.days_match('last', D(2026, 10, 30)))
        self.assertFalse(kit.days_match('nope', D(2026, 10, 6)))


class Due(unittest.TestCase):
    ITEM = {'at': '09:00', 'days': 'mon-fri'}

    def test_after_slot_not_yet_run(self):
        self.assertTrue(kit.due(self.ITEM, None, DT(2026, 10, 6, 9, 0)))
        self.assertTrue(kit.due(self.ITEM, None, DT(2026, 10, 6, 11, 59)))

    def test_before_slot(self):
        self.assertFalse(kit.due(self.ITEM, None, DT(2026, 10, 6, 8, 59)))

    def test_already_ran_today(self):
        ran = DT(2026, 10, 6, 9, 1).timestamp()
        self.assertFalse(kit.due(self.ITEM, ran, DT(2026, 10, 6, 10, 0)))
        yesterday = DT(2026, 10, 5, 9, 1).timestamp()
        self.assertTrue(kit.due(self.ITEM, yesterday, DT(2026, 10, 6, 10, 0)))

    def test_grace_window(self):
        self.assertFalse(kit.due(self.ITEM, None, DT(2026, 10, 6, 12, 1)))           # 180분 넘음 — 몰아서 돌지 않는다
        self.assertTrue(kit.due(self.ITEM, None, DT(2026, 10, 6, 12, 1), grace_min=300))

    def test_wrong_day_and_bad_time(self):
        self.assertFalse(kit.due(self.ITEM, None, DT(2026, 10, 4, 10, 0)))           # 일요일
        for bad in ({'at': ''}, {'at': 'x'}, {}, {'at': '25'}):
            with self.subTest(bad=bad):
                self.assertFalse(kit.due(bad, None, TUE))


class EveryDue(unittest.TestCase):
    def test_every(self):
        self.assertTrue(kit.every_due(10, None, 1000))
        self.assertFalse(kit.every_due(10, 1000, 1000 + 599))
        self.assertTrue(kit.every_due(10, 1000, 1000 + 600))
        self.assertTrue(kit.every_due('5', 0, 300))


class Render(unittest.TestCase):
    def setUp(self):
        self._orig = kit.company_name
        kit.company_name = lambda cfg=None: '테스트상사'

    def tearDown(self):
        kit.company_name = self._orig

    def test_placeholders(self):
        out = kit.render('[{company}] {date} {yyyy}/{mm}/{dd} 전월 {prev_month} 이달 {month} {week}주차', DT(2026, 1, 5, 9, 0))
        self.assertEqual(out, '[테스트상사] 2026-01-05 2026/01/05 전월 2025-12 이달 2026-01 2주차')

    def test_unknown_and_empty(self):
        self.assertEqual(kit.render('{nope} 그대로', TUE), '{nope} 그대로')
        self.assertEqual(kit.render(None, TUE), '')


class MailReady(unittest.TestCase):
    FULL = dict(kit.MAIL_DEFAULTS, user='me@example.com', password_enc='xxx', smtp_host='smtp.example.com')

    def test_ready(self):
        ok, why = kit.mail_ready(self.FULL)
        self.assertTrue(ok)
        self.assertEqual(why, '')

    def test_imap_only_is_enough(self):
        self.assertTrue(kit.mail_ready(dict(self.FULL, smtp_host='', imap_host='imap.example.com'))[0])

    def test_missing(self):
        for key in ('user', 'password_enc', 'smtp_host'):
            with self.subTest(key=key):
                ok, why = kit.mail_ready(dict(self.FULL, **{key: ''}))
                self.assertFalse(ok)
                self.assertIn('메일·계정 설정', why)

    def test_alert_refuses_when_not_ready(self):
        with self.assertRaises(RuntimeError):
            kit.alert('제목', '본문', m=dict(self.FULL, user=''))


@unittest.skipUnless(sys.platform == 'win32', 'DPAPI 는 Windows 전용')
class Protect(unittest.TestCase):
    def test_roundtrip(self):
        for text in ('p@ss-word!', '한글 비밀번호 123', ''):
            with self.subTest(text=text):
                enc = kit.protect(text)
                self.assertNotIn(text or '\0', enc)
                self.assertEqual(kit.unprotect(enc), text)

    def test_garbage_fails(self):
        with self.assertRaises(Exception):
            kit.unprotect('AAAA')


if __name__ == '__main__':
    unittest.main()


class SetupSamples(unittest.TestCase):
    def test_strip_samples_drops_example_targets(self):
        sys.path.insert(0, os.path.normpath(os.path.join(HUB, "..", "..")))
        import setup
        cfg = {'links': [{'label': 'x', 'url': 'https://portal.example.com/'}, {'label': 'y', 'url': 'https://corp.kr/'}],
               'monitors': {'targets': [{'name': 'db', 'host': '10.0.0.10', 'port': 1}, {'name': 'web', 'url': 'https://corp.kr/'}]},
               'backups': [{'name': 'b', 'enabled': False}]}
        out = setup.strip_samples(cfg)
        self.assertEqual([x['label'] for x in out['links']], ['y'])
        self.assertEqual([x['name'] for x in out['monitors']['targets']], ['web'])
        self.assertEqual(out['backups'], cfg['backups'])
