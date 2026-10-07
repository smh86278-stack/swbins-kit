# -*- coding: utf-8 -*-
"""메일·계정 설정 창(setup_gui.py)의 입력 → 설정 변환. 창은 띄우지 않는다(순수 함수만)."""
import os
import sys
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, ROOT)
import setup_gui  # noqa: E402

FAKE_PROTECT = lambda pw: 'ENC(%s)' % pw


def base(**kw):
    v = {'company': '테스트', 'preset': 'Gmail / Google Workspace', 'user': 'me@corp.kr', 'login_user': '',
         'password': 'pw', 'alert_to': '', 'alert_via': 'smtp', 'advanced': False,
         'imap_host': '', 'imap_port': '993', 'imap_mode': 'ssl', 'smtp_host': '', 'smtp_port': '587',
         'smtp_mode': 'starttls', 'ca_bundle': ''}
    v.update(kw)
    return v


class Collect(unittest.TestCase):
    def test_preset_fills_servers_and_encrypts(self):
        cfg, errors, notes = setup_gui.collect(base(), {}, protect=FAKE_PROTECT)
        self.assertEqual(errors, [])
        m = cfg['mail']
        self.assertEqual((m['imap_host'], m['smtp_host'], m['smtp_port']), ('imap.gmail.com', 'smtp.gmail.com', 587))
        self.assertEqual(m['password_enc'], 'ENC(pw)')
        self.assertEqual(cfg['company']['name'], '테스트')
        self.assertNotIn('password', m)

    def test_keeps_saved_password_when_blank(self):
        cfg, errors, _ = setup_gui.collect(base(password=''), {'mail': {'password_enc': 'OLD'}}, protect=FAKE_PROTECT)
        self.assertEqual(errors, [])
        self.assertEqual(cfg['mail']['password_enc'], 'OLD')

    def test_errors(self):
        _, errors, _ = setup_gui.collect(base(user='nope', password=''), {}, protect=FAKE_PROTECT)
        self.assertEqual(len(errors), 2)            # 주소 · 비밀번호
        _, errors, _ = setup_gui.collect(base(preset=setup_gui.CUSTOM, advanced=True), {}, protect=FAKE_PROTECT)
        self.assertTrue(any('서버' in e for e in errors))
        _, errors, _ = setup_gui.collect(base(preset=setup_gui.CUSTOM, advanced=True, smtp_host='smtp.corp.kr',
                                              smtp_port='99999'), {}, protect=FAKE_PROTECT)
        self.assertTrue(any('포트' in e for e in errors))

    def test_custom_servers_and_alert_fallback(self):
        cfg, errors, notes = setup_gui.collect(base(preset=setup_gui.CUSTOM, advanced=True, imap_host='mail.corp.kr',
                                                    imap_port='143', imap_mode='starttls', alert_via='smtp'),
                                               {}, protect=FAKE_PROTECT)
        self.assertEqual(errors, [])
        self.assertEqual((cfg['mail']['imap_host'], cfg['mail']['imap_port']), ('mail.corp.kr', 143))
        self.assertEqual(cfg['mail']['alert_via'], 'append')     # SMTP 가 없으니 받은편지함에 넣기로
        self.assertTrue(notes)

    def test_initial_values_hide_samples_and_detect_preset(self):
        v = setup_gui.initial_values({'company': {'name': '우리회사'},
                                      'mail': {'user': 'me@example.com', 'imap_host': 'imap.naver.com', 'password_enc': 'x'}})
        self.assertEqual((v['company'], v['user'], v['preset'], v['has_password'], v['password']),
                         ('', '', '네이버 메일', True, ''))
        self.assertEqual(setup_gui.initial_values({'mail': {'smtp_host': 'smtp.corp.kr'}})['preset'], setup_gui.CUSTOM)

    def test_friendly_error_hints(self):
        self.assertIn('앱 비밀번호', setup_gui.friendly_error(Exception('535 Authentication failed')))
        self.assertIn('방화벽', setup_gui.friendly_error(OSError('[Errno 11001] getaddrinfo failed')))


if __name__ == '__main__':
    unittest.main()
