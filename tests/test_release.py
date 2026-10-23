# -*- coding: utf-8 -*-
"""installer/release.py — GitHub 에 닿지 않는 부분만(인자·VERSION·커밋 안 한 변경·태그 중복 검사, 저장소 이름)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'installer'))
import release  # noqa: E402


class ReleaseCheck(unittest.TestCase):
    def setUp(self):
        self.real = release.git
        self.addCleanup(setattr, release, 'git', self.real)

    def fake_git(self, status='', tags=''):
        def g(*a, **k):
            return status if a[0] == 'status' else tags if a[0] == 'tag' else ''
        release.git = g

    def version(self, v):
        return mock.patch('builtins.open', mock.mock_open(read_data=v + '\n'))

    def test_bad_tag(self):
        for tag in ('', '0.3.2', 'v0.3', 'v0.3.2-rc1'):
            with self.assertRaises(SystemExit):
                release.check(tag)

    def test_version_must_match(self):
        self.fake_git()
        with self.version('0.3.1'), self.assertRaises(SystemExit) as cm:
            release.check('v0.3.2')
        self.assertIn('VERSION', str(cm.exception))
        with self.version('0.3.2'):
            self.assertEqual(release.check('v0.3.2'), '0.3.2')

    def test_stops_on_uncommitted_change_or_existing_tag(self):
        self.fake_git(status=' M README.md\n')
        with self.version('0.3.2'), self.assertRaises(SystemExit) as cm:
            release.check('v0.3.2')
        self.assertIn('커밋', str(cm.exception))
        self.fake_git(tags='v0.3.2\n')
        with self.version('0.3.2'), self.assertRaises(SystemExit) as cm:
            release.check('v0.3.2')
        self.assertIn('태그', str(cm.exception))

    def test_repo_name(self):
        for url in ('https://github.com/me/swbins-kit.git', 'https://me@github.com/me/swbins-kit', 'git@github.com:me/swbins-kit.git'):
            release.git = lambda *a, u=url, **k: u + '\n'
            self.assertEqual(release.repo_name(), 'me/swbins-kit')
        release.git = lambda *a, **k: 'https://example.com/x.git\n'
        with self.assertRaises(SystemExit):
            release.repo_name()


if __name__ == '__main__':
    unittest.main()
