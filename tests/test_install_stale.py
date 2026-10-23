# -*- coding: utf-8 -*-
"""installer/install_main.py — 업데이트할 때 지난 버전에만 있던 키트 파일 지우기(remove_stale)·목록 기억(installed_files).
설치 프로그램 전체(바로가기·레지스트리)는 돌리지 않는다 — 임시 폴더 안 파일만."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'installer'))
import install_main as im  # noqa: E402


def touch(root, rel, text='x'):
    p = os.path.join(root, *rel.split('/'))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)
    return p


class RemoveStale(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def exists(self, rel):
        return os.path.exists(os.path.join(self.root, *rel.split('/')))

    def test_removes_only_files_dropped_by_new_version(self):
        old = ['README.md', 'send-file.py', 'tools/old-tool/a.py', 'tools/old-tool/b.py', 'tools/macro-hub/app.py']
        new = ['README.md', 'tools/macro-hub/app.py']
        for rel in old:
            touch(self.root, rel)
        touch(self.root, 'tools/old-tool/my-notes.txt')            # 사용자가 넣은 파일 — 목록에 없으니 그대로
        gone = im.remove_stale(self.root, old, new)
        self.assertEqual(sorted(gone), ['send-file.py', 'tools/old-tool/a.py', 'tools/old-tool/b.py'])
        self.assertFalse(self.exists('send-file.py'))
        self.assertTrue(self.exists('tools/old-tool/my-notes.txt'))  # 폴더도 비지 않았으니 남는다
        self.assertTrue(self.exists('README.md') and self.exists('tools/macro-hub/app.py'))

    def test_empty_folders_are_cleaned_up(self):
        old = ['tools/gone/sub/x.py', 'keep.txt']
        for rel in old:
            touch(self.root, rel)
        im.remove_stale(self.root, old, ['keep.txt'])
        self.assertFalse(self.exists('tools/gone'))
        self.assertFalse(self.exists('tools'))                       # tools 도 비었으니 지워진다
        self.assertTrue(self.exists('keep.txt'))

    def test_user_data_and_runtime_are_never_removed(self):
        old = ['config.local.json', 'tools/macro-hub/macros.local/mine.py', 'tools/macro-hub/data.local/app.log',
               'tools/macro-hub/state.local.json', 'install.json', 'runtime/python.exe', 'inbox/a.json']
        for rel in old:
            touch(self.root, rel)
        self.assertEqual(im.remove_stale(self.root, old, []), [])
        for rel in old:
            self.assertTrue(self.exists(rel), rel)

    def test_paths_outside_target_are_ignored(self):
        outside = touch(os.path.dirname(self.root), os.path.basename(self.root) + '-outside.txt')
        self.addCleanup(lambda: os.path.exists(outside) and os.remove(outside))
        bad = ['../' + os.path.basename(outside), '/etc/passwd', 'C:/Windows/win.ini', 'a/../../x']
        self.assertEqual(im.remove_stale(self.root, bad, []), [])
        self.assertTrue(os.path.exists(outside))

    def test_no_old_list_removes_nothing(self):
        touch(self.root, 'send-file.py')
        self.assertEqual(im.remove_stale(self.root, None, []), [])
        self.assertTrue(self.exists('send-file.py'))

    def test_installed_files_and_kit_files(self):
        self.assertIsNone(im.installed_files(self.root))             # install.json 없음
        with open(os.path.join(self.root, 'install.json'), 'w', encoding='utf-8') as f:
            json.dump({'version': '0.3.1'}, f)
        self.assertIsNone(im.installed_files(self.root))             # 옛 설치 — 목록 없음
        with open(os.path.join(self.root, 'install.json'), 'w', encoding='utf-8') as f:
            json.dump({'version': '0.3.2', 'files': ['README.md']}, f)
        self.assertEqual(im.installed_files(self.root), ['README.md'])
        self.assertEqual(im.kit_files(['runtime/python.exe', 'tools/', 'tools/a.py', 'README.md']), ['README.md', 'tools/a.py'])


if __name__ == '__main__':
    unittest.main()
