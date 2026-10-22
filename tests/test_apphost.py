# -*- coding: utf-8 -*-
"""✨ 나만의 앱 실행 환경(tools\\macro-hub\\apphost.py) — 앱 목록·권한·격리(Host·X-App·Origin)·앱 전용 DB.

    python -m unittest discover -s tests

임시 폴더에 앱을 만들고 port 0 으로 서버를 띄워 진짜 HTTP 로 부른다. Host 머리글로 '<id>.localhost:<port>' 를 흉내 낸다.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import apphost    # noqa: E402


def make_app(base, app_id, manifest, files=None):
    d = os.path.join(base, app_id)
    os.makedirs(d, exist_ok=True)
    if manifest is not None:
        with open(os.path.join(d, 'app.json'), 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False)
    for rel, body in (files if files is not None else {'index.html': '<h1>hi</h1>'}).items():
        p = os.path.join(d, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(body)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.builtin = os.path.join(self.tmp, 'apps')
        self.local = os.path.join(self.tmp, 'apps.local')
        for name, val in (('DIR_BUILTIN', self.builtin), ('DIR_LOCAL', self.local),
                          ('STATE', os.path.join(self.tmp, 'data.local', 'apps.json')),
                          ('DATA', os.path.join(self.tmp, 'data.local', 'apps'))):
            p = mock.patch.object(apphost, name, val)
            p.start()
            self.addCleanup(p.stop)


class Listing(Base):
    def test_discover_and_manifest(self):
        make_app(self.builtin, 'sample', {'name': '견본', 'permissions': ['db', 'nope']})
        make_app(self.local, 'mine', {'name': '내 앱', 'kind': 'weird', 'permissions': 'db'})
        make_app(self.local, 'Bad_Name', {'name': 'x'})               # 호스트 이름에 못 쓰는 id 는 건너뜀
        make_app(self.local, 'noindex', {'name': 'y'}, files={})
        apps = apphost.discover()
        self.assertEqual(sorted(apps), ['mine', 'noindex', 'sample'])
        self.assertEqual(apps['sample']['permissions'], ['db'])       # 모르는 권한은 버림
        self.assertTrue(apps['sample']['builtin'])
        self.assertEqual((apps['mine']['kind'], apps['mine']['permissions']), ('app', []))
        self.assertIn('index.html', apps['noindex']['error'])

    def test_local_wins_same_id(self):
        make_app(self.builtin, 'same', {'name': '견본'})
        make_app(self.local, 'same', {'name': '내 것'})
        self.assertEqual(apphost.find('same')['name'], '내 것')

    def test_approve(self):
        make_app(self.local, 'a', {'permissions': ['db', 'ai']})
        self.assertEqual(apphost.approve('a', ['ai', 'db']), ['db', 'ai'])
        with self.assertRaises(ValueError):
            apphost.approve('a', ['run'])                              # 요청하지 않은 권한
        with self.assertRaises(ValueError):
            apphost.approve('zzz', [])
        make_app(self.local, 'a', {'permissions': ['ai']})            # 앱이 db 를 빼면 옛 허락도 안 쓴다
        self.assertEqual(apphost.approved('a'), ['ai'])
        v = apphost.list_view(8631)[0]
        self.assertEqual((v['url'], v['ready'], v['pending']), ('http://a.localhost:8631/', [], []))


class Server(Base):
    def setUp(self):
        super().setUp()
        self.srv = apphost.make_server(0, hub_port=8630)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        make_app(self.local, 'notes', {'name': '메모', 'permissions': ['db', 'ai']},
                 {'index.html': '<h1>notes</h1>', 'src/main.js': 'ok()', '.history/old.js': 'x', 'data/x.txt': 'x',
                  'secret.py': 'x'})
        make_app(self.local, 'other', {'permissions': ['db']})

    def req(self, path, app='notes', method='GET', body=None, headers=None, host=None):
        h = {'Host': host or '%s.localhost:%d' % (app, self.port)}
        if method == 'POST':
            h.update({'Content-Type': 'application/json', 'X-App': '1'})
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        data = json.dumps(body or {}).encode() if method == 'POST' else None
        r = urllib.request.Request('http://127.0.0.1:%d%s' % (self.port, path), data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def db(self, sql, params=None, app='notes', **kw):
        code, body, _ = self.req('/_api/db', app, 'POST', {'sql': sql, 'params': params or []}, **kw)
        return code, json.loads(body)

    def test_host_check(self):
        self.assertEqual(self.req('/', host='127.0.0.1:%d' % self.port)[0], 403)
        self.assertEqual(self.req('/', host='notes.localhost:1')[0], 403)          # 포트가 다르면
        self.assertEqual(self.req('/', host='notes.evil.example:%d' % self.port)[0], 403)
        self.assertEqual(self.req('/', host='nope.localhost:%d' % self.port)[0], 403)

    def test_static_files(self):
        code, body, h = self.req('/')
        self.assertEqual((code, body), (200, b'<h1>notes</h1>'))
        self.assertIn("connect-src 'self'", h['Content-Security-Policy'])         # 바깥 주소로 못 보낸다
        self.assertIn('http://127.0.0.1:8630', h['Content-Security-Policy'])      # 허브만 품을 수 있다
        self.assertEqual(self.req('/src/main.js')[0], 200)
        self.assertIn(b'window.app', self.req('/_app.js')[1])
        for bad in ('/.history/old.js', '/data/x.txt', '/secret.py', '/../other/index.html', '/%2e%2e/other/index.html',
                    '/src/../../other/index.html', '/app.json/x'):
            self.assertEqual(self.req(bad)[0], 404, bad)

    def test_api_guards(self):
        self.assertEqual(self.req('/_api/db', method='POST', headers={'X-App': None})[0], 403)          # 머리글 없음
        self.assertEqual(self.req('/_api/db', method='POST', headers={'Origin': 'http://evil.example'})[0], 403)
        own = 'http://notes.localhost:%d' % self.port
        self.assertEqual(self.db('SELECT 1 AS x', headers={'Origin': own})[0], 403)  # 아직 허락 안 함
        self.assertEqual(self.req('/_api/run', method='POST')[0], 403)            # app.json 에 없는 권한
        self.assertEqual(self.req('/_api/zzz', method='POST')[0], 404)
        self.assertEqual(self.req('/_api/db')[0], 405)
        code, body, _ = self.req('/_api/info', method='POST')
        self.assertEqual((code, json.loads(body)['approved']), (200, []))

    def test_db_isolated_per_app(self):
        apphost.approve('notes', ['db', 'ai'])
        apphost.approve('other', ['db'])
        code, _, _ = self.req('/_api/db', method='POST', body={'script': 'CREATE TABLE t (v TEXT); INSERT INTO t VALUES (1);'})
        self.assertEqual(code, 200)
        self.assertEqual(self.db('INSERT INTO t VALUES (?)', ['메모'])[1]['changes'], 1)
        self.assertEqual(self.db('SELECT v FROM t ORDER BY rowid')[1]['rows'], [{'v': '1'}, {'v': '메모'}])
        code, d = self.db('SELECT * FROM t', app='other')                      # 다른 앱은 자기 DB — 그런 테이블 없음
        self.assertEqual(code, 400)
        self.assertIn('no such table', d['error'])
        path = os.path.join(apphost.DATA, 'other', 'app.db').replace('\\', '/')
        code, d = self.db("ATTACH DATABASE '%s' AS o" % path)
        self.assertEqual(code, 400)                                              # 다른 파일 붙이기 막힘
        self.assertEqual(self.req('/_api/ai', method='POST')[0], 501)            # 허락했어도 아직 준비 중

    def test_body_limits(self):
        apphost.approve('notes', ['db'])
        self.assertEqual(self.db('')[0], 400)
        code, _, _ = self.req('/_api/db', method='POST', body={'sql': 'SELECT 1', 'params': 'x'})
        self.assertEqual(code, 400)


if __name__ == '__main__':
    unittest.main()
