# -*- coding: utf-8 -*-
"""허브 창 「회고」 탭 — 허브 /retro 가 AI 작업 회고(ai_share) 설정에 따라 넘기거나 안내한다(macrohub.retro_page).

    python -m unittest discover -s tests

허브를 띄우지 않는다(함수만 부른다). 표준 라이브러리만으로 돈다.
"""
import os
import sys
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')
sys.path.insert(0, HUB)
import macrohub     # noqa: E402


class RetroTab(unittest.TestCase):
    def setUp(self):
        saved = (macrohub.kit.section, macrohub.retro_up)
        self.addCleanup(lambda: (setattr(macrohub.kit, 'section', saved[0]), setattr(macrohub, 'retro_up', saved[1])))

    def conf(self, a):
        macrohub.kit.section = lambda name, default=None, cfg=None: a if name == 'ai_share' else (default or {})

    def test_off_shows_how_to_enable(self):
        self.conf({})
        st, to, body, refresh = macrohub.retro_page()
        self.assertEqual((st, to, refresh), ('off', None, 0))
        self.assertIn('ai_share.enabled', body)

    def test_up_redirects_to_configured_port(self):
        self.conf({'enabled': True, 'port': 8650})
        macrohub.retro_up = lambda url, timeout=0.4: url == 'http://127.0.0.1:8650'
        self.assertEqual(macrohub.retro_page()[:2], ('up', 'http://127.0.0.1:8650/'))

    def test_starting_waits(self):
        self.conf({'enabled': True})
        macrohub.retro_up = lambda url, timeout=0.4: False
        st, to, _body, refresh = macrohub.retro_page()
        self.assertEqual((st, to), ('starting', None))
        self.assertGreater(refresh, 0)

    def test_shell_and_rail_know_the_tab(self):
        with open(os.path.join(HUB, 'shell', 'main.js'), encoding='utf-8') as f:
            js = f.read()
        with open(os.path.join(HUB, 'shell', 'rail.html'), encoding='utf-8') as f:
            rail = f.read()
        self.assertIn("retro: HUB + '/retro'", js)
        self.assertIn("'retro']", js)                      # MOVABLE
        self.assertIn('data-tab="retro"', rail)
        self.assertNotIn('spawn(', js)                     # 회고 서버는 허브 상시 서비스가 띄운다


if __name__ == '__main__':
    unittest.main()
