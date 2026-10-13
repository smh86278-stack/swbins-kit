# -*- coding: utf-8 -*-
"""로그인·키 만료 예고(job_cred_watch)의 판단 로직 — 진짜 로그인 파일·메일·Jira 에 닿지 않는다."""
import datetime
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
spec = importlib.util.spec_from_file_location('job_cred_watch', os.path.join(HUB, 'macros', 'job_cred_watch.py'))
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)

NOW = datetime.datetime(2026, 10, 14, 10, 0).timestamp()
DAY = 86400


class Logic(unittest.TestCase):
    def test_by_days(self):
        for days, level in ((30, 'ok'), (7, 'warn'), (0.5, 'bad'), (-2, 'bad')):
            with self.subTest(days=days):
                self.assertEqual(cw.by_days(NOW + days * DAY, NOW, 7)[0], level)

    def test_parse_expires(self):
        self.assertEqual(cw.parse_expires('2026-10-14'), datetime.datetime(2026, 10, 14, 23, 59, 59).timestamp())
        self.assertEqual(cw.parse_expires('2026-10-14 18:00'), datetime.datetime(2026, 10, 14, 18, 0).timestamp())
        self.assertIsNone(cw.parse_expires('내년 봄'))

    def test_keys(self):
        items = cw.key_items([{'name': 'A', 'expires': '2026-10-18'}, {'name': 'B', 'expires': '??'}, {'expires': '2026-10-18'}], NOW, 7)
        self.assertEqual([(i['name'], i['level']) for i in items], [('A', 'warn'), ('B', 'unknown')])

    def test_pat_pick_uses_token_in_use(self):
        toks = [{'name': 'old', 'expiringAt': '2026-10-20T10:00:00.000+0900', 'lastAccessedAt': '2026-09-01T10:00:00.000+0900'},
                {'name': 'kit', 'expiringAt': None, 'lastAccessedAt': '2026-10-14T10:00:00.000+0900'}]
        self.assertEqual(cw.pat_pick(toks), ('kit', None))
        self.assertIsNone(cw.pat_pick([]))

    def test_error_item_auth_vs_network(self):
        self.assertEqual(cw.error_item('m', 'f', "b'[AUTHENTICATIONFAILED] Invalid credentials'")['level'], 'bad')
        self.assertEqual(cw.error_item('m', 'f', TimeoutError('timed out'))['level'], 'info')

    def test_due_items(self):
        warn = [{'id': 'claude', 'level': 'warn'}]
        early = datetime.datetime(2026, 10, 14, 3, 0).timestamp()
        due, sent = cw.due_items(warn, {}, early)
        self.assertEqual(len(due), 1)                                     # 새로 나빠짐 — 바로
        self.assertEqual(cw.due_items(warn, sent, early + 3600)[0], [])    # 같은 날 — 다시 안 알림
        nxt = datetime.datetime(2026, 10, 15, 3, 0).timestamp()
        self.assertEqual(cw.due_items(warn, sent, nxt)[0], [])            # 다음 날 9시 전 — 기다림
        self.assertEqual(len(cw.due_items(warn, sent, nxt + 7 * 3600)[0]), 1)
        self.assertEqual(cw.due_items([{'id': 'claude', 'level': 'ok'}], sent, early)[1], {})

    def test_to_status(self):
        st = cw.to_status([{'name': 'a', 'level': 'ok', 'text': 't'}, {'name': 'b', 'level': 'bad', 'text': 't'},
                           {'name': 'c', 'level': 'info', 'text': 't'}])
        self.assertEqual([s['ok'] for s in st], [True, False, None])


class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_claude_reads_only_expiry(self):
        os.makedirs(os.path.join(self.tmp, '.claude'))
        with mock.patch.object(cw.ops, 'claude_home', return_value=os.path.join(self.tmp, '.claude')):
            self.assertIsNone(cw.check_claude(NOW, 7))                    # 로그인 파일 없음 — 항목 없음
            with open(os.path.join(self.tmp, '.claude', '.credentials.json'), 'w') as f:
                json.dump({'claudeAiOauth': {'accessToken': 'SECRET-TOKEN', 'refreshTokenExpiresAt': (NOW + 3 * DAY) * 1000}}, f)
            it = cw.check_claude(NOW, 7)
        self.assertEqual(it['level'], 'warn')
        self.assertNotIn('SECRET-TOKEN', json.dumps(it))

    def _resp(self, data):
        r = mock.MagicMock()
        r.__enter__.return_value = io.BytesIO(json.dumps(data).encode())
        return r

    def _jira(self, auth, opener):
        full = {'jira': {'base_url': 'https://jira.example.com/', 'auth': auth, 'email': 'me@example.com', 'token_enc': 'x'}, 'mail': {}}
        with mock.patch.object(cw.kit, 'unprotect', return_value='tok'):
            return cw.check_jira(full, NOW, 7, opener=opener)

    def test_jira_server_expiry(self):
        seen = []

        def opener(req):
            seen.append((req.full_url, req.get_header('Authorization')))
            return self._resp([{'name': 'kit', 'expiringAt': '2026-10-16T10:00:00.000+0900', 'lastAccessedAt': '2026-10-14T10:00:00.000+0900'}])
        it = self._jira('server', opener)
        self.assertEqual(seen, [('https://jira.example.com/rest/pat/latest/tokens', 'Bearer tok')])
        self.assertEqual(it['level'], 'warn')

    def test_jira_server_old_version_falls_back_to_login(self):
        urls = []

        def opener(req):
            urls.append(req.full_url)
            if 'pat' in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 404, 'nf', {}, None)
            return self._resp({'name': 'me'})
        it = self._jira('server', opener)
        self.assertEqual(urls[-1], 'https://jira.example.com/rest/api/2/myself')
        self.assertEqual(it['level'], 'ok')

    def test_jira_rejected_is_bad(self):
        def opener(req):
            raise urllib.error.HTTPError(req.full_url, 401, 'no', {}, None)
        self.assertEqual(self._jira('cloud', opener)['level'], 'bad')

    def test_jira_not_set_up_is_skipped(self):
        self.assertIsNone(cw.check_jira({'jira': {'base_url': ''}}, NOW, 7))

    def test_mail_rejected_vs_unreachable(self):
        m = {'user': 'me@example.com', 'password_enc': 'x', 'imap_host': 'imap.example.com'}
        with mock.patch.object(cw.kit, 'mail_config', return_value=m), mock.patch.object(cw.kit, 'mail_ready', return_value=(True, '')):
            with mock.patch.object(cw.kit, 'imap_connect', side_effect=cw.imaplib.IMAP4.error('LOGIN failed')):
                self.assertEqual(cw.check_mail()['level'], 'bad')
            with mock.patch.object(cw.kit, 'imap_connect', side_effect=TimeoutError('timed out')):
                self.assertEqual(cw.check_mail()['level'], 'info')
            with mock.patch.object(cw.kit, 'imap_connect', return_value=mock.MagicMock()):
                self.assertEqual(cw.check_mail()['level'], 'ok')


if __name__ == '__main__':
    unittest.main()
