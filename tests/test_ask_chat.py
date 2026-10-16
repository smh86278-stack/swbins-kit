# -*- coding: utf-8 -*-
"""🛠 만들기 「말로 부탁하기」(macrohub.ask_chat) — 가짜 디스패치 대화를 띄워 시험한다. 진짜 대화 앱·메일에 닿지 않는다.

- 대화 화면(GET /)에서 토큰을 읽어 X-Token 으로 /api/send 에 보낸다
- 쓰기 지시(mode=write), 작업 폴더 hub 가 있으면 그것
- 대화 앱이 꺼져 있거나 빈 글이면 알아듣는 오류
"""
import http.server
import json
import os
import sys
import threading
import unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import macrohub     # noqa: E402

TOKEN = 'tok-123'


class FakeChat(http.server.BaseHTTPRequestHandler):
    sent = []
    folders = ['hub', 'docs']

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/api/state':
            return self._json(200, {'threads': [], 'folders': self.folders})
        page = ("<script>\nconst TOKEN = '%s';\n</script>" % TOKEN).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Length', str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        if self.headers.get('X-Token') != TOKEN:
            return self._json(403, {'error': 'forbidden'})
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
        FakeChat.sent.append(body)
        return self._json(200, {'ok': True, 'subject': '#cw ' + body['text'].splitlines()[0]})


class AskChat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeChat)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.old = (macrohub.CHAT_URL, macrohub.audit)
        macrohub.CHAT_URL = 'http://127.0.0.1:%d' % cls.srv.server_address[1]
        macrohub.audit = lambda *a, **k: None

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        macrohub.CHAT_URL, macrohub.audit = cls.old

    def setUp(self):
        FakeChat.sent.clear()
        FakeChat.folders = ['hub', 'docs']

    def test_sends_write_to_hub_folder(self):
        res = macrohub.ask_chat('자동화 허브에 자동화 만들어줘 — 공지 확인\n언제: 30분마다')
        self.assertTrue(res['ok'])
        self.assertEqual(FakeChat.sent, [{'text': '자동화 허브에 자동화 만들어줘 — 공지 확인\n언제: 30분마다', 'mode': 'write', 'folder': 'hub'}])

    def test_default_folder_when_no_hub(self):
        FakeChat.folders = ['docs']
        macrohub.ask_chat('부탁')
        self.assertEqual(FakeChat.sent[0]['folder'], '')

    def test_empty_text(self):
        with self.assertRaises(ValueError):
            macrohub.ask_chat('   ')
        self.assertEqual(FakeChat.sent, [])

    def test_chat_off(self):
        url = macrohub.CHAT_URL
        macrohub.CHAT_URL = 'http://127.0.0.1:9'          # 아무도 안 듣는 포트
        try:
            with self.assertRaises(RuntimeError) as cm:
                macrohub.ask_chat('부탁')
            self.assertIn('꺼져 있습니다', str(cm.exception))
        finally:
            macrohub.CHAT_URL = url


if __name__ == '__main__':
    unittest.main()
