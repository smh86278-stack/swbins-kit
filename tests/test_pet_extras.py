# -*- coding: utf-8 -*-
"""화면 펫 덧붙임(2026-10-30) — 소품·계절 설정(macrohub.petx · clean_petx) · 키우기 규칙(petgrow).

    python -m unittest discover -s tests

허브를 띄우지 않는다(함수만 부른다). 표준 라이브러리만으로 돈다.
"""
import datetime
import json
import os
import shutil
import subprocess
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
        self.assertEqual(macrohub.petx(), {'season': True, 'grow': True, 'snack_ai': True, 'snack_prompt': True, 'bubble': True, 'quiet': 'none', 'acc': {'dog': 'none', 'cat': 'none'}})

    def test_clean_keeps_missing_keys(self):
        macrohub.state['petx'] = {'season': False, 'acc': {'dog': 'crown'}}
        px, err = macrohub.clean_petx({'acc': {'cat': 'ribbon'}})
        self.assertIsNone(err)
        self.assertEqual(px, {'season': False, 'grow': True, 'snack_ai': True, 'snack_prompt': True, 'bubble': True, 'quiet': 'none', 'acc': {'dog': 'crown', 'cat': 'ribbon'}})

    def test_rejects_unknown_accessory_and_ignores_unknown_kind(self):
        self.assertIsNone(macrohub.clean_petx({'acc': {'dog': '<svg>'}})[0])
        px, err = macrohub.clean_petx({'acc': {'bird': 'crown'}, 'season': 0})
        self.assertIsNone(err)
        self.assertEqual(px, {'season': False, 'grow': True, 'snack_ai': True, 'snack_prompt': True, 'bubble': True, 'quiet': 'none', 'acc': {'dog': 'none', 'cat': 'none'}})

    def test_old_bad_values_fall_back(self):
        macrohub.state['petx'] = {'acc': {'dog': 'gone', 'cat': 'glasses'}}
        self.assertEqual(macrohub.petx()['acc'], {'dog': 'none', 'cat': 'glasses'})

    def test_bubble_and_quiet(self):
        px, err = macrohub.clean_petx({'bubble': False, 'quiet': 'night'})
        self.assertIsNone(err)
        self.assertEqual((px['bubble'], px['quiet']), (False, 'night'))
        self.assertIsNone(macrohub.clean_petx({'quiet': '3am'})[0])
        macrohub.state['petx'] = {'quiet': 'weird'}
        self.assertEqual(macrohub.petx()['quiet'], 'none')

    def test_retro_url_follows_config(self):
        """프롬프트 팁은 AI 작업 회고(ai_share)가 켜져 있을 때만 그 포트로 묻는다."""
        saved = macrohub.kit.section
        self.addCleanup(setattr, macrohub.kit, 'section', saved)
        macrohub.kit.section = lambda name, default=None, cfg=None: {}
        self.assertIsNone(macrohub.retro_url())
        macrohub.kit.section = lambda name, default=None, cfg=None: {'enabled': True, 'port': '8650'}
        self.assertEqual(macrohub.retro_url(), 'http://127.0.0.1:8650')

    def test_petnote_quiet_when_outside_is_down(self):
        """메신저·회고가 꺼져 있으면 ask=None · tip=None 으로 조용히(예외 없이)."""
        saved = (macrohub.kit.section, macrohub._get_json, macrohub.schedule_view, dict(macrohub.NOTE_TIP))
        def restore():
            macrohub.kit.section, macrohub._get_json, macrohub.schedule_view = saved[:3]
            macrohub.NOTE_TIP.update(saved[3])
        self.addCleanup(restore)
        macrohub.kit.section = lambda name, default=None, cfg=None: {}
        def down(*_a, **_k):
            raise OSError('down')
        macrohub._get_json = down
        macrohub.schedule_view = lambda: []
        macrohub.NOTE_TIP.update(at=9e18, text=None, busy=False)      # 팁 새로 고침 스레드는 띄우지 않는다
        j = macrohub.petnote()
        self.assertEqual((j['sched'], j['ask'], j['tip'], j['retro']), ([], None, None, None))
        self.assertTrue(j['chat'].startswith('http://127.0.0.1:'))

    def test_names_match_web(self):
        """허브의 소품 이름이 web/pets.js PetAcc.LIST 와 같아야 화면에서 고른 값이 통과한다."""
        with open(os.path.join(HUB, 'web', 'pets.js'), encoding='utf-8') as f:
            js = f.read()
        for acc in macrohub.PET_ACCS[1:]:
            self.assertIn("['%s', " % acc, js)


NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'node 가 없으면 건너뜀(계절 고르기는 web/pets.js 안에 있다)')
class Seasons(unittest.TestCase):
    """계절 고르기(web/pets.js PetAcc.seasonOf)를 node 로 직접 돌린다 — 음력 창 > 날짜 창 > 달 기본."""

    @classmethod
    def ask(cls, dates):
        js = ("globalThis.window=globalThis;globalThis.location={search:''};require(process.argv[1]);"
              "const P=window.PetAcc,out={};for(const s of JSON.parse(require('fs').readFileSync(0,'utf8'))){const [y,m,d]=s.split('-');"
              "const id=P.seasonOf(new Date(+y,m-1,+d,12));out[s]=id?[id,P.SEASONS[id].dog,P.SEASONS[id].cat]:null}"
              "console.log(JSON.stringify(out))")
        r = subprocess.run([NODE, '-e', js, os.path.join(HUB, 'web', 'pets.js')], input=json.dumps(dates),     # 날짜는 stdin 으로(명령줄 길이)
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)

    def check(self, table):
        got = self.ask(list(table))
        self.assertEqual({k: v[0] for k, v in got.items()}, table)

    def test_every_day_has_a_season_with_accessories(self):
        day, end, dates = datetime.date(2026, 1, 1), datetime.date(2033, 12, 31), []
        while day <= end:
            dates.append(day.isoformat())
            day += datetime.timedelta(days=1)
        with open(os.path.join(HUB, 'web', 'pets.js'), encoding='utf-8') as f:
            js = f.read()
        for d, v in self.ask(dates).items():
            self.assertIsNotNone(v, d)
            for acc in v[1:]:
                self.assertRegex(js, r'\n    %s: \(g, at\)' % acc, (d, acc))      # 소품 그림(ART)이 있어야 한다

    def test_month_defaults(self):
        self.check({'2026-01-10': 'newyear', '2026-02-02': 'winter', '2026-02-28': 'winter', '2026-03-01': 'sprout',
                    '2026-03-27': 'sprout', '2026-04-13': 'shower', '2026-05-20': 'may', '2026-06-15': 'jangma',
                    '2026-07-15': 'summer', '2026-08-15': 'august', '2026-09-01': 'dragonfly', '2026-10-01': 'autumn',
                    '2026-11-01': 'november', '2026-11-30': 'november'})

    def test_date_windows_edges(self):
        self.check({'2026-02-06': 'winter', '2027-02-14': 'valentine', '2026-02-20': 'winter',
                    '2026-03-28': 'spring', '2026-04-12': 'spring', '2026-05-02': 'may', '2026-05-03': 'children',
                    '2026-05-06': 'children', '2026-05-07': 'may', '2026-10-23': 'autumn', '2026-10-24': 'halloween',
                    '2026-10-31': 'halloween', '2026-11-09': 'november', '2026-11-11': 'pepero', '2026-11-13': 'november',
                    '2026-12-01': 'xmas', '2026-12-26': 'xmas', '2026-12-27': 'newyear'})

    def test_year_boundary(self):
        self.check({'2026-12-31': 'newyear', '2027-01-01': 'newyear', '2027-01-31': 'newyear', '2032-12-31': 'newyear'})

    def test_lunar_windows_and_priority(self):
        self.check({
            # 설날 ±2 — 2026 은 2/17(밸런타인 2/7~15 와 겹치는 2/15 는 설이 이긴다)
            '2026-02-14': 'valentine', '2026-02-15': 'seollal', '2026-02-19': 'seollal', '2026-02-20': 'winter',
            '2027-02-05': 'seollal', '2027-02-09': 'seollal', '2027-02-10': 'valentine',
            '2028-01-25': 'seollal', '2028-01-29': 'seollal', '2028-01-24': 'newyear',     # 1월 설은 새해를 이긴다
            '2031-01-21': 'seollal', '2032-02-13': 'seollal',
            # 추석 ±3 — 2028·2031 은 10월(단풍 달 기본을 이긴다)
            '2026-09-22': 'chuseok', '2026-09-28': 'chuseok', '2026-09-29': 'dragonfly', '2026-09-21': 'dragonfly',
            '2028-10-06': 'chuseok', '2028-10-07': 'autumn', '2031-09-28': 'chuseok', '2032-09-22': 'chuseok',
            # 표가 끝난 해는 설·추석 창 없이 달 기본
            '2033-01-31': 'newyear', '2033-09-10': 'dragonfly'})


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
