# -*- coding: utf-8 -*-
"""화면 펫 덧붙임(2026-10-30) — 소품·계절 설정(macrohub.petx · clean_petx).

    python -m unittest discover -s tests

허브를 띄우지 않는다(함수만 부른다). 표준 라이브러리만으로 돈다.
"""
import os
import sys
import unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import macrohub     # noqa: E402


class PetExtras(unittest.TestCase):
    def setUp(self):
        self.saved = macrohub.state.get('petx')
        macrohub.state.pop('petx', None)
        self.addCleanup(self.restore)

    def restore(self):
        if self.saved is None:
            macrohub.state.pop('petx', None)
        else:
            macrohub.state['petx'] = self.saved

    def test_default_is_season_on_no_accessory(self):
        self.assertEqual(macrohub.petx(), {'season': True, 'acc': {'dog': 'none', 'cat': 'none'}})

    def test_clean_keeps_missing_keys(self):
        macrohub.state['petx'] = {'season': False, 'acc': {'dog': 'crown'}}
        px, err = macrohub.clean_petx({'acc': {'cat': 'ribbon'}})
        self.assertIsNone(err)
        self.assertEqual(px, {'season': False, 'acc': {'dog': 'crown', 'cat': 'ribbon'}})

    def test_rejects_unknown_accessory_and_ignores_unknown_kind(self):
        self.assertIsNone(macrohub.clean_petx({'acc': {'dog': '<svg>'}})[0])
        px, err = macrohub.clean_petx({'acc': {'bird': 'crown'}, 'season': 0})
        self.assertIsNone(err)
        self.assertEqual(px, {'season': False, 'acc': {'dog': 'none', 'cat': 'none'}})

    def test_old_bad_values_fall_back(self):
        macrohub.state['petx'] = {'acc': {'dog': 'gone', 'cat': 'glasses'}}
        self.assertEqual(macrohub.petx()['acc'], {'dog': 'none', 'cat': 'glasses'})

    def test_names_match_web(self):
        """허브의 소품 이름이 web/pets.js PetAcc.LIST 와 같아야 화면에서 고른 값이 통과한다."""
        with open(os.path.join(HUB, 'web', 'pets.js'), encoding='utf-8') as f:
            js = f.read()
        for acc in macrohub.PET_ACCS[1:]:
            self.assertIn("['%s', " % acc, js)


if __name__ == '__main__':
    unittest.main()
