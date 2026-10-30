# -*- coding: utf-8 -*-
"""화면 펫 덧붙임(2026-10-30) — 소품·계절 설정(macrohub.petx · clean_petx) · 키우기 규칙(petgrow).

    python -m unittest discover -s tests

허브를 띄우지 않는다(함수만 부른다). 표준 라이브러리만으로 돈다.
"""
import datetime
import os
import sys
import unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import macrohub     # noqa: E402
import petgrow      # noqa: E402


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
        self.assertEqual(macrohub.petx(), {'season': True, 'grow': True, 'acc': {'dog': 'none', 'cat': 'none'}})

    def test_clean_keeps_missing_keys(self):
        macrohub.state['petx'] = {'season': False, 'acc': {'dog': 'crown'}}
        px, err = macrohub.clean_petx({'acc': {'cat': 'ribbon'}})
        self.assertIsNone(err)
        self.assertEqual(px, {'season': False, 'grow': True, 'acc': {'dog': 'crown', 'cat': 'ribbon'}})

    def test_rejects_unknown_accessory_and_ignores_unknown_kind(self):
        self.assertIsNone(macrohub.clean_petx({'acc': {'dog': '<svg>'}})[0])
        px, err = macrohub.clean_petx({'acc': {'bird': 'crown'}, 'season': 0})
        self.assertIsNone(err)
        self.assertEqual(px, {'season': False, 'grow': True, 'acc': {'dog': 'none', 'cat': 'none'}})

    def test_old_bad_values_fall_back(self):
        macrohub.state['petx'] = {'acc': {'dog': 'gone', 'cat': 'glasses'}}
        self.assertEqual(macrohub.petx()['acc'], {'dog': 'none', 'cat': 'glasses'})

    def test_names_match_web(self):
        """허브의 소품 이름이 web/pets.js PetAcc.LIST 와 같아야 화면에서 고른 값이 통과한다."""
        with open(os.path.join(HUB, 'web', 'pets.js'), encoding='utf-8') as f:
            js = f.read()
        for acc in macrohub.PET_ACCS[1:]:
            self.assertIn("['%s', " % acc, js)


D = datetime.datetime
FRI = D(2026, 10, 30, 10, 0)


def run(macro, status='ok', trigger='manual', detail='', tool=False):
    return {'macro': macro, 'status': status, 'trigger': trigger, 'detail': detail, 'tool': tool, 'name': macro}


class Growth(unittest.TestCase):
    """키우기 규칙(petgrow.py) — 하루 한 번·폴러·서비스 제외·고침 보너스·새 자동화·레벨."""

    def setUp(self):
        self.g = petgrow.blank()

    def test_one_snack_per_macro_per_day(self):
        self.assertEqual(petgrow.on_run(self.g, run('a'), now=FRI)[0], 1)
        self.assertEqual(petgrow.on_run(self.g, run('a'), now=FRI)[0], 0)
        self.assertEqual(petgrow.on_run(self.g, run('b'), now=FRI)[0], 1)
        self.assertEqual(petgrow.on_run(self.g, run('a'), now=FRI + datetime.timedelta(days=1))[0], 1)
        self.assertEqual(self.g['snacks'], 3)

    def test_ignored_runs(self):
        for r, svc in ((run('t', trigger='test'), False), (run('s', trigger='service'), False), (run('x'), True),
                       (run('p', trigger='schedule', detail='매 1h'), False), (run('c', trigger='chain'), False), (run('__pick__', tool=True), False)):
            self.assertEqual(petgrow.on_run(self.g, r, svc, FRI)[0], 0, r)
        self.assertEqual(petgrow.on_run(self.g, run('m', trigger='schedule', detail='09:30'), now=FRI)[0], 1)   # 시각 예약은 센다
        self.assertEqual(petgrow.on_run(self.g, run('f', status='fail'), now=FRI)[0], 0)

    def test_fix_bonus_once_a_day(self):
        petgrow.on_run(self.g, run('a', 'fail'), now=FRI)
        gained, _, fixed = petgrow.on_run(self.g, run('a'), now=FRI)
        self.assertEqual((gained, fixed), (1 + petgrow.FIX_BONUS, True))
        petgrow.on_run(self.g, run('a', 'timeout'), now=FRI)
        self.assertEqual(petgrow.on_run(self.g, run('a'), now=FRI)[0], 0)      # 같은 날 두 번째 고침은 없다
        self.assertEqual(self.g['week']['fixes'], 1)

    def test_stopped_does_not_hide_failure(self):
        petgrow.on_run(self.g, run('a', 'fail'), now=FRI)
        petgrow.on_run(self.g, run('a', 'stopped'), now=FRI)
        self.assertTrue(petgrow.on_run(self.g, run('a'), now=FRI)[2])

    def test_new_macros(self):
        self.assertEqual(petgrow.on_macros(self.g, ['local/a'], FRI)[0], 0)    # 처음 본 목록은 기준만
        self.assertEqual(petgrow.on_macros(self.g, ['local/a', 'local/b', 'local/c', 'local/d'], FRI)[0], 2 * petgrow.NEW_BONUS)
        self.assertEqual(petgrow.on_macros(self.g, ['local/a', 'local/e'], FRI)[0], 0)   # 하루 두 개까지
        self.assertEqual(petgrow.on_macros(self.g, ['local/f'], FRI + datetime.timedelta(days=1))[0], petgrow.NEW_BONUS)

    def test_levels(self):
        self.assertEqual([petgrow.level(n) for n in (0, 4, 5, 14, 15, 299, 300, 9999)], [1, 1, 2, 2, 3, 9, 10, 10])
        v = petgrow.view(dict(petgrow.blank(), snacks=37))
        self.assertEqual((v['level'], v['floor'], v['next']), (4, 30, 50))
        self.assertIsNone(petgrow.view(dict(petgrow.blank(), snacks=500))['next'])
        self.assertEqual(sorted(petgrow.UNLOCK), sorted(macrohub.PET_ACCS[1:]))
        self.assertEqual(petgrow.UNLOCK['ribbon'], 1)

    def test_levelup_flag_and_week_roll(self):
        self.g['snacks'] = 4
        self.assertTrue(petgrow.on_run(self.g, run('a'), now=FRI)[1])
        petgrow.on_run(self.g, run('a'), now=FRI + datetime.timedelta(days=3))      # 다음 주 월요일
        self.assertEqual(self.g['prev_week']['snacks'], 1)
        self.assertEqual(self.g['week']['snacks'], 1)

    def test_seed_replays_history(self):
        recs = [dict(run('a', 'fail'), started=1793260000000), dict(run('a'), started=1793261000000),
                dict(run('svc', trigger='service'), started=1793262000000)]
        petgrow.seed(self.g, recs, {'svc'})
        self.assertEqual(self.g['snacks'], 1 + petgrow.FIX_BONUS)
        self.assertTrue(self.g['seeded'])

    def test_locked_accessory_rejected_until_level(self):
        saved = macrohub.GROW
        self.addCleanup(setattr, macrohub, 'GROW', saved)
        macrohub.state.pop('petx', None)
        macrohub.GROW = dict(petgrow.blank(), snacks=0)
        self.assertIsNone(macrohub.clean_petx({'acc': {'dog': 'crown'}})[0])
        self.assertEqual(macrohub.clean_petx({'acc': {'dog': 'ribbon'}})[0]['acc']['dog'], 'ribbon')
        self.assertEqual(macrohub.clean_petx({'grow': False, 'acc': {'dog': 'crown'}})[0]['acc']['dog'], 'crown')   # 키우기를 끄면 다 풀림
        macrohub.GROW['snacks'] = 80
        self.assertEqual(macrohub.clean_petx({'acc': {'cat': 'crown'}})[0]['acc']['cat'], 'crown')


if __name__ == '__main__':
    unittest.main()
