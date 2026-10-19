# -*- coding: utf-8 -*-
"""허브 보안 — 비밀값 가리기·클릭재킹 헤더·토큰 요구 GET·CSV 수식·웹훅/Jira 주소·새 자동화 이름·녹화 주소.
진짜 허브 포트·메일·웹훅에 닿지 않는다(임시 포트에 Handler 를 띄운다)."""
import ast
import http.server
import io
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
sys.path.insert(0, os.path.join(HUB, 'macros'))
import hubutil     # noqa: E402
import kit         # noqa: E402
import macrohub    # noqa: E402
import ops         # noqa: E402


class Redact(unittest.TestCase):
    def test_patterns_and_values(self):
        r = hubutil.redact
        self.assertEqual(r('login password=hunter22 ok'), 'login password=●●● ok')
        self.assertEqual(r('Authorization: Basic YWJjOmRlZg=='), 'Authorization: ●●●')
        self.assertEqual(r('curl -H "Bearer abc.def-123"'), 'curl -H "Bearer ●●●"')
        self.assertEqual(r('{"token": "xyz123"}'), '{"token": "●●●"}')
        self.assertEqual(r('https://me:pw123@x.com/a'), 'https://me:●●●@x.com/a')
        self.assertEqual(r('읽은 값 s3cr3tvalue 끝', ['s3cr3tvalue']), '읽은 값 ●●● 끝')
        self.assertEqual(r('주문 3건 저장 완료'), '주문 3건 저장 완료')

    def test_runner_masks_secret_values(self):
        import runner
        buf = io.StringIO()
        runner.SECRET_VALUES.append('topsecret99')
        try:
            runner._Masked(buf).write('pw is topsecret99\n')
        finally:
            runner.SECRET_VALUES.remove('topsecret99')
        self.assertEqual(buf.getvalue(), 'pw is ●●●\n')


class Urls(unittest.TestCase):
    def test_webhook_url_by_hostname(self):
        ok = ['https://hooks.slack.com/x', 'http://127.0.0.1:9/x', 'http://localhost/x']
        bad = ['http://127.0.0.1.evil.example/', 'http://localhost@evil.example/', 'http://user@localhost/',
               'ftp://x', 'http://10.0.0.1/', '', 'https://']
        self.assertEqual([kit.url_ok(u) for u in ok], [True] * len(ok))
        self.assertEqual([kit.url_ok(u) for u in bad], [False] * len(bad))
        self.assertFalse(kit.url_ok('http://localhost/x', local_http=False))

    def test_jira_http_is_refused(self):
        import job_cred_watch as J
        called = []
        full = {'jira': {'base_url': 'http://jira.example', 'token_enc': kit.protect('tok')}}
        it = J.check_jira(full, 0, 7, opener=lambda req: called.append(req))
        self.assertEqual(it['level'], 'bad')
        self.assertEqual(called, [])                                  # 토큰을 평문 http 로 보내지 않았다

    def test_csv_cell(self):
        self.assertEqual([ops.csv_cell(x) for x in ['=1+1', '@a', 'ok']], ["'=1+1", "'@a", 'ok'])


class Handlers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), macrohub.Handler)
        cls.port = cls.srv.server_address[1]
        cls.old_hosts = macrohub.Handler.allowed_hosts
        macrohub.Handler.allowed_hosts = frozenset(['127.0.0.1:%d' % cls.port])
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        macrohub.Handler.allowed_hosts = cls.old_hosts

    def get(self, path):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (self.port, path), timeout=10) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)

    def test_frame_headers(self):
        code, h = self.get('/api/hidden')
        self.assertEqual(code, 200)
        self.assertEqual(h.get('X-Frame-Options'), 'DENY')
        self.assertIn("frame-ancestors 'none'", h.get('Content-Security-Policy', ''))

    def test_agents_verify_needs_token(self):
        self.assertEqual(self.get('/api/ops/agents?verify=1')[0], 403)


class NewMacroAndRecord(unittest.TestCase):
    def test_name_cannot_inject_code(self):
        tmp = tempfile.mkdtemp()
        old = macrohub.DIR_LOCAL
        macrohub.DIR_LOCAL = tmp
        self.addCleanup(setattr, macrohub, 'DIR_LOCAL', old)
        mid, err = macrohub.new_macro('a",\n    "x": __import__("os").system("calc"),\n#', 'web')
        self.assertIsNone(err)
        src = open(os.path.join(tmp, mid.split('/', 1)[1] + '.py'), encoding='utf-8').read()
        calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == 'system']
        self.assertEqual(calls, [])

    def test_record_url_must_be_web(self):
        self.assertIn('http', macrohub.record_web('--help', '녹화 시험'))


if __name__ == '__main__':
    unittest.main()
