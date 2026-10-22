# -*- coding: utf-8 -*-
"""✨ 앱 버전(tools\\macro-hub\\apphistory.py) — 남기기·같은 내용 건너뛰기·개수 정리·되돌리기·바뀐 곳·zip 경로 탈출.

    python -m unittest discover -s tests
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import apphistory    # noqa: E402


def write(base, rel, text):
    p = os.path.join(base, *rel.split('/'))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def read(base, rel):
    with open(os.path.join(base, *rel.split('/')), encoding='utf-8') as f:
        return f.read()


class History(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.app, True)
        write(self.app, 'index.html', '<h1>v1</h1>\n')
        write(self.app, 'src/main.js', 'a()\nb()\n')
        write(self.app, '.check/check.png', 'png')

    def test_snapshot_skips_same_and_dot_dirs(self):
        v1 = apphistory.snapshot(self.app, '처음')
        self.assertEqual((v1['label'], v1['files']), ('처음', 2))          # .check 는 안 담는다
        self.assertIsNone(apphistory.snapshot(self.app, '같음'))             # 바뀐 게 없으면 건너뜀
        write(self.app, 'src/main.js', 'a()\nc()\n')
        v2 = apphistory.snapshot(self.app, '고친 뒤')
        self.assertEqual([v['id'] for v in apphistory.history(self.app)], [v2['id'], v1['id']])   # 새것 먼저
        with zipfile.ZipFile(os.path.join(self.app, '.history', v2['id'] + '.zip')) as z:
            self.assertEqual(sorted(z.namelist()), ['index.html', 'src/main.js'])

    def test_keep_prunes_oldest(self):
        ids = []
        for i in range(5):
            write(self.app, 'index.html', 'v%d' % i)
            ids.append(apphistory.snapshot(self.app, str(i), keep=3)['id'])
        self.assertEqual([v['id'] for v in apphistory.history(self.app)], ids[:1:-1])
        self.assertFalse(os.path.exists(os.path.join(self.app, '.history', ids[0] + '.zip')))

    def test_restore_and_undo_restore(self):
        v1 = apphistory.snapshot(self.app, '처음')
        write(self.app, 'src/main.js', 'broken(\n')
        write(self.app, 'src/extra.js', 'x')
        saved, n = apphistory.restore(self.app, v1['id'])
        self.assertEqual(n, 2)
        self.assertEqual(read(self.app, 'src/main.js'), 'a()\nb()\n')
        self.assertFalse(os.path.exists(os.path.join(self.app, 'src', 'extra.js')))     # 그 버전에 없던 파일은 없어진다
        self.assertTrue(os.path.isfile(os.path.join(self.app, '.check', 'check.png')))   # 점 폴더는 그대로
        self.assertIn('되돌리기 전', saved['label'])
        apphistory.restore(self.app, saved['id'])                                         # 되돌리기도 되돌린다
        self.assertEqual(read(self.app, 'src/main.js'), 'broken(\n')
        self.assertTrue(os.path.isfile(os.path.join(self.app, 'src', 'extra.js')))

    def test_diff(self):
        v1 = apphistory.snapshot(self.app, '처음')
        write(self.app, 'src/main.js', 'a()\nc()\nd()\n')
        write(self.app, 'style.css', 'body{}')
        os.remove(os.path.join(self.app, 'index.html'))
        d = apphistory.diff(self.app, v1['id'])
        self.assertEqual((d['added'], d['removed']), (['style.css'], ['index.html']))
        c = d['changed'][0]
        self.assertEqual((c['path'], c['plus'], c['minus']), ('src/main.js', 2, 1))
        self.assertIn('-b()', c['diff'])
        self.assertIn('+d()', c['diff'])
        v2 = apphistory.snapshot(self.app, '둘째')
        self.assertEqual(apphistory.diff(self.app, v1['id'], v2['id'])['to'], v2['id'])   # 버전끼리도

    def test_bad_versions(self):
        for bad in ('', '../x', '20261022-120000-000'):
            with self.assertRaises(ValueError):
                apphistory.restore(self.app, bad)

    def test_restore_ignores_zip_escape(self):
        os.makedirs(os.path.join(self.app, '.history'))
        vid = '20261022-120000-001'
        with zipfile.ZipFile(os.path.join(self.app, '.history', vid + '.zip'), 'w') as z:
            z.writestr('index.html', 'ok')
            z.writestr('../escaped.txt', 'nope')
        apphistory._write_index(self.app, [{'id': vid, 'at': '', 'label': '', 'files': 2, 'size': 0, 'digest': 'x'}])
        apphistory.restore(self.app, vid)
        self.assertEqual(read(self.app, 'index.html'), 'ok')
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.app), 'escaped.txt')))

    def test_export_zip(self):
        data = apphistory.export_zip(self.app)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(sorted(z.namelist()), ['index.html', 'src/main.js'])


if __name__ == '__main__':
    unittest.main()
