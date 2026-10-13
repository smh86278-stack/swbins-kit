# -*- coding: utf-8 -*-
"""알림 출구(kit.alert · post_channel · 보낸 기록 · setup.py --webhook) — 메일·웹훅을 실제로 보내지 않는다."""
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')
sys.path.insert(0, HUB)
sys.path.insert(0, ROOT)
import kit  # noqa: E402
import setup  # noqa: E402

FULL = dict(kit.MAIL_DEFAULTS, user='me@example.com', password_enc='xxx', smtp_host='smtp.example.com')


class Fake:
    """post= 로 넘기는 가짜 전송 — 받은 요청을 모아 두고 status 를 돌려준다(예외를 줄 수도)."""

    def __init__(self, fail=None):
        self.reqs, self.fail = [], fail

    def __call__(self, req):
        self.reqs.append(req)
        if self.fail:
            raise self.fail
        return 200


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, val in (('DATA', os.path.join(self.tmp, 'data')), ('F_CONFIG', os.path.join(self.tmp, 'config.local.json')),
                          ('unprotect', lambda b: b[4:] if b.startswith('enc:') else b), ('company_name', lambda cfg=None: '')):
            self.addCleanup(setattr, kit, name, getattr(kit, name))
            setattr(kit, name, val)


class Payload(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(kit.channel_payload('slack', 'S', 'B'), {'text': '*S*\nB'})
        self.assertEqual(kit.channel_payload('discord', 'S', 'B'), {'content': '**S**\nB'})
        card = kit.channel_payload('teams', 'S', 'B')['attachments'][0]
        self.assertEqual(card['contentType'], 'application/vnd.microsoft.card.adaptive')
        self.assertEqual([b['text'] for b in card['content']['body']], ['S', 'B'])
        w = kit.channel_payload('webhook', 'S', 'B', now=5)
        self.assertEqual((w['subject'], w['body'], w['ts']), ('S', 'B', 5))
        self.assertIn('잘림', kit.channel_payload('slack', 'S', 'x' * 5000)['text'])


class Post(Base):
    def test_post_slack_and_signed_webhook(self):
        f = Fake()
        kit.post_channel({'type': 'slack', 'url_enc': 'enc:https://hooks.example.com/a'}, 'S', 'B', post=f)
        self.assertEqual(f.reqs[0].full_url, 'https://hooks.example.com/a')
        self.assertEqual(json.loads(f.reqs[0].data), {'text': '*S*\nB'})
        kit.post_channel({'type': 'webhook', 'url_enc': 'enc:https://example.com/h', 'secret_enc': 'enc:k'}, 'S', 'B', post=f)
        r = f.reqs[1]
        self.assertEqual(r.get_header('X-kit-signature'), 'sha256=' + hmac.new(b'k', r.data, hashlib.sha256).hexdigest())

    def test_rejects_plain_http_and_unknown(self):
        with self.assertRaises(ValueError):
            kit.post_channel({'type': 'slack', 'url': 'http://example.com/a'}, 'S', 'B', post=Fake())
        with self.assertRaises(ValueError):
            kit.post_channel({'type': 'kakao', 'url': 'https://example.com/a'}, 'S', 'B', post=Fake())


class Alert(Base):
    CH = [{'name': '팀 슬랙', 'type': 'slack', 'url_enc': 'enc:https://hooks.example.com/SECRET'}]

    def test_channel_only_when_mail_not_ready(self):
        f = Fake()
        self.assertEqual(kit.alert('제목', '본문', m=dict(FULL, user=''), channels=self.CH, post=f), 1)
        log = kit.notify_log_tail()
        self.assertEqual([(r['channel'], r['ok']) for r in log], [('팀 슬랙', True)])
        with open(os.path.join(kit.DATA, 'notify', 'sent.jsonl'), encoding='utf-8') as fh:
            self.assertNotIn('SECRET', fh.read())                         # 주소는 기록에 안 남는다
        st = kit.read_status('notify')
        self.assertEqual(st['items'][0]['ok'], True)

    def test_mail_and_channel_one_fails(self):
        with mock.patch.object(kit, 'send_mail') as sm:
            n = kit.alert('제목', '본문', m=FULL, channels=self.CH, post=Fake(fail=RuntimeError('HTTP 404 Not Found')))
        self.assertEqual(n, 1)                                            # 메일은 갔다 — 예외 없음
        sm.assert_called_once()
        self.assertEqual([(r['channel'], r['ok']) for r in kit.notify_log_tail()], [('팀 슬랙', False), ('메일', True)])

    def test_all_fail_raises(self):
        with self.assertRaises(RuntimeError):
            kit.alert('제목', '본문', m=dict(FULL, user=''), channels=self.CH, post=Fake(fail=RuntimeError('HTTP 500')))

    def test_nothing_configured_raises(self):
        with self.assertRaises(RuntimeError):
            kit.alert('제목', '본문', m=dict(FULL, user=''), channels=[])

    def test_off_channel_skipped(self):
        with self.assertRaises(RuntimeError):
            kit.alert('제목', '본문', m=dict(FULL, user=''), channels=[dict(self.CH[0], on=False)])

    def test_alert_ready(self):
        kit.save_config({'notify': {'channels': self.CH}})
        self.assertTrue(kit.alert_ready(dict(FULL, user=''))[0])
        kit.save_config({'notify': {'channels': []}})
        self.assertFalse(kit.alert_ready(dict(FULL, user=''))[0])
        kit.save_config({'notify': {'mail': False}})
        self.assertFalse(kit.alert_ready(FULL)[0])


class Wizard(Base):
    def test_step_webhook_encrypts_and_replaces_same_name(self):
        cfg = {}
        answers = iter(['slack', '팀 슬랙'])
        with mock.patch.object(setup, 'ask_choice', side_effect=lambda *a, **k: next(answers)), \
                mock.patch.object(setup, 'ask', side_effect=lambda *a, **k: next(answers)):
            setup.step_webhook(cfg, protect=lambda s: 'enc:' + s, secret=lambda p: 'https://hooks.example.com/x')
        answers = iter(['slack', '팀 슬랙'])
        with mock.patch.object(setup, 'ask_choice', side_effect=lambda *a, **k: next(answers)), \
                mock.patch.object(setup, 'ask', side_effect=lambda *a, **k: next(answers)):
            setup.step_webhook(cfg, protect=lambda s: 'enc:' + s, secret=lambda p: 'https://hooks.example.com/y')
        ch = cfg['notify']['channels']
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]['url_enc'], 'enc:https://hooks.example.com/y')
        self.assertNotIn('url', ch[0])
        self.assertNotIn('hooks.example.com', json.dumps(setup.masked(cfg)))


if __name__ == '__main__':
    unittest.main()
