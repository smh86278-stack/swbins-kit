# -*- coding: utf-8 -*-
"""✨ 앱 내보내기·가져오기(tools\\macro-hub\\apppack.py) — zip 왕복·가져오기 막기·HTML 한 장·exe(csc).

    python -m unittest discover -s tests

HTML 한 장은 진짜 브라우저로 file:// 에서 열어 본다(KIT_BROWSER_TESTS=0 이면 건너뜀).
"""
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import apphost    # noqa: E402
import apppack    # noqa: E402


def zbytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, val in (('DIR_BUILTIN', os.path.join(self.tmp, 'apps')), ('DIR_LOCAL', os.path.join(self.tmp, 'apps.local')),
                          ('STATE', os.path.join(self.tmp, 'apps.json')), ('DATA', os.path.join(self.tmp, 'data'))):
            p = mock.patch.object(apphost, name, val)
            p.start()
            self.addCleanup(p.stop)


class Zip(Base):
    def test_roundtrip(self):
        app = apphost.create_app('crm', '거래처', 'crud')
        os.makedirs(os.path.join(app['dir'], '.history'))
        name, data = apppack.export_zip(app)
        self.assertEqual(name, 'crm-0.1.0.zip')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertNotIn('.history/', ' '.join(z.namelist()))
        got = apppack.import_zip(data, 'crm-copy', '거래처 복사')
        self.assertEqual((got['name'], got['permissions']), ('거래처 복사', ['db']))
        self.assertTrue(os.path.isfile(os.path.join(got['dir'], 'src', 'db.js')))
        self.assertEqual(apphost.approved('crm-copy'), [])                 # 권한은 다시 허락해야

    def test_strips_wrapping_folder_and_guards(self):
        ok = {'myapp/app.json': json.dumps({'name': 'x'}), 'myapp/index.html': '<h1>x</h1>', 'myapp/src/a.js': 'a()',
              'myapp/.history/old.zip': 'x', 'myapp/../evil.html': 'x'}
        app = apppack.import_zip(zbytes(ok), 'wrapped')
        self.assertTrue(os.path.isfile(os.path.join(app['dir'], 'src', 'a.js')))
        self.assertFalse(os.path.exists(os.path.join(app['dir'], '.history')))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'apps.local', 'evil.html')))
        for bad, files in (('not zip', None), ('exe 들어 있음', {'app.json': '{}', 'index.html': 'x', 'run.exe': 'MZ'}),
                           ('app.json 없음', {'index.html': 'x'})):
            with self.assertRaises(ValueError, msg=bad):
                apppack.import_zip(b'nope' if files is None else zbytes(files), 'zz-' + str(len(bad)))
        with self.assertRaises(ValueError):
            apppack.import_zip(zbytes(ok), 'wrapped')                         # 이미 있는 이름
        with mock.patch.object(apppack, 'IMPORT_MAX', 10), self.assertRaises(ValueError):
            apppack.import_zip(zbytes({'app.json': '{}', 'index.html': 'x' * 50}), 'big')


class Html(Base):
    def test_bundle_shape(self):
        app = apphost.create_app('crm', '거래처', 'crud')
        name, html = apppack.export_html(app)
        self.assertEqual(name, 'crm-0.1.0.html')
        self.assertIn('<script type="importmap">', html)
        imports = json.loads(html.split('<script type="importmap">', 1)[1].split('</script>', 1)[0])['imports']
        self.assertEqual(sorted(imports), ['app:///_lib/preact-htm.js', 'app:///src/db.js', 'app:///src/main.js'])
        self.assertTrue(all(v.startswith('data:text/javascript;base64,') for v in imports.values()))
        self.assertNotIn('src="/_app.js"', html)
        self.assertNotIn('href="/_lib/', html)                                # css 는 안에 넣었다
        self.assertIn('window.__SQL_WASM__', html)                           # db 권한 → sql.js 포함
        tool = apphost.create_app('tool', '도구', 'tool')
        self.assertNotIn('__SQL_WASM__', apppack.export_html(tool)[1])        # db 없으면 안 넣는다(가볍게)

    def test_missing_file_is_error(self):
        app = apphost.create_app('crm', '거래처', 'crud')
        os.remove(os.path.join(app['dir'], 'src', 'db.js'))
        with self.assertRaises(ValueError) as c:
            apppack.export_html(app)
        self.assertIn('src/db.js', str(c.exception))

    def test_resolve(self):
        self.assertEqual(apppack._resolve('src/scenes/play.js', '../score.js'), 'src/score.js')
        self.assertEqual(apppack._resolve('src/main.js', '/_lib/preact-htm.js'), '_lib/preact-htm.js')
        self.assertIsNone(apppack._resolve('src/main.js', 'https://esm.sh/x'))
        self.assertIsNone(apppack._resolve('index.html', '../../x.js'))

    @unittest.skipUnless(os.environ.get('KIT_BROWSER_TESTS', '1') == '1', 'KIT_BROWSER_TESTS=0')
    def test_works_from_file_and_keeps_data(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('playwright 없음')
        app = apphost.create_app('crm', '거래처', 'crud')
        path = os.path.join(self.tmp, 'crm.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(apppack.export_html(app)[1])
        with sync_playwright() as p:
            try:
                b = p.chromium.launch(channel='chrome')
            except Exception:
                self.skipTest('크롬 없음')
            pg = b.new_page()
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.goto(pathlib.Path(path).as_uri())
            pg.fill('#title', '오프라인 항목')
            pg.click('#save')
            pg.get_by_text('오프라인 항목').first.wait_for(timeout=5000)
            pg.wait_for_timeout(400)                                          # IndexedDB 저장(150ms 미룸) 기다림
            pg.reload()
            pg.get_by_text('오프라인 항목').first.wait_for(timeout=5000)        # 다시 열어도 남는다
            self.assertEqual(errs, [])
            b.close()


@unittest.skipUnless(apppack.csc_path(), 'csc.exe 없음')
class Exe(Base):
    def test_builds_exe_with_html_inside(self):
        app = apphost.create_app('tool', '도구 "따옴표"', 'tool')
        out = apppack.export_exe(app, os.path.join(self.tmp, 'out'))
        self.assertTrue(out.endswith('tool.exe'))
        with open(out, 'rb') as f:
            data = f.read()
        self.assertEqual(data[:2], b'MZ')
        self.assertIn(b'importmap', data)                                     # HTML 이 안에 들었다


if __name__ == '__main__':
    unittest.main()
