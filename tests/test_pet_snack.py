# -*- coding: utf-8 -*-
"""화면 펫 간식 더 — AI 커밋(Co-Authored-By: Claude) · 좋은 첫 프롬프트(회고 규칙 💡 없음).
가짜 git 출력·가짜 대화 기록(임시 폴더)만 쓴다 — git·허브·AI 를 부르지 않는다.

    python -m unittest discover -s tests
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.normpath(os.path.join(HERE, '..', 'tools', 'macro-hub'))
RULES = os.path.normpath(os.path.join(HERE, '..', 'tools', 'ai-share-agent', 'prompt_rules.py'))
sys.path.insert(0, HUB)
import petgrow      # noqa: E402
import petsnack     # noqa: E402

NOW = datetime.datetime(2026, 10, 30, 15, 0)
ME = {'me@example.com', 'me'}
GOOD = 'tools/macro-hub/petgrow.py 의 하루 한도 계산을 고쳐줘. 같은 날 두 번 성공해도 1개만 늘면 완료, 기존 테스트는 그대로 통과해야 해'
SHORT = '응 진행해'
NO_TARGET = '주문 수집이 가끔 두 번 되는 문제가 있는데 원인 찾아서 고쳐줘'


def commit(sha, when, body, email='me@example.com', name='me', subject=None):
    subject = subject or body.splitlines()[0]
    return '\x1e%s\x00%d\x00%s\x00%s\x00%s\x00%s\n' % (sha, int(when.timestamp()), email, name, subject, body)


def fake_git(text):
    return lambda args, cwd: text


AI = '\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n'


class Trailer(unittest.TestCase):
    def test_detects_claude_trailer(self):
        self.assertTrue(petsnack.is_ai_commit('고침' + AI))
        self.assertTrue(petsnack.is_ai_commit('fix\n\nco-authored-by: Claude <noreply@anthropic.com>'))
        self.assertTrue(petsnack.is_ai_commit('fix\n\nCo-Authored-By: Bot <noreply@anthropic.com>'))

    def test_ignores_other_coauthors_and_mentions(self):
        self.assertFalse(petsnack.is_ai_commit('fix\n\nCo-Authored-By: 홍길동 <hong@example.com>'))
        self.assertFalse(petsnack.is_ai_commit('Claude 화면 고침 — Co-Authored-By 꼬리말 설명'))   # 줄 맨 앞이 아님
        self.assertFalse(petsnack.is_ai_commit(''))

    def test_only_my_commits(self):
        text = (commit('a1', NOW, 'mine' + AI) + commit('b2', NOW, 'theirs' + AI, email='x@example.com', name='x')
                + commit('c3', NOW, 'mine no ai'))
        self.assertEqual([c['sha'] for c in petsnack.ai_commits(text, ME)], ['a1'])
        self.assertEqual(petsnack.ai_commits(text, set()), [])                    # 누구 것인지 모르면 안 센다

    def test_parse_multiline_body(self):
        cs = petsnack.parse_log(commit('a1', NOW, '제목\n\n본문 1\n본문 2' + AI))
        self.assertEqual(cs[0]['subject'], '제목')
        self.assertIn('본문 2', cs[0]['body'])


class AiCommits(unittest.TestCase):
    def setUp(self):
        self.g = petgrow.blank()
        self.logs = []

    def run_check(self, text, now=NOW, repos=('r',)):
        return petsnack.check_ai(self.g, list(repos), ME, now, petgrow.on_extra, git=fake_git(text), log=self.logs.append)

    def test_daily_cap(self):
        text = ''.join(commit('s%d' % i, NOW - datetime.timedelta(minutes=i), 'c%d' % i + AI) for i in range(8))
        self.assertEqual(self.run_check(text)[0], petgrow.EXTRA_CAP['ai'])
        self.assertEqual(petgrow.view(self.g)['src'], {'auto': 0, 'ai': 5, 'prompt': 0})

    def test_dedupe_same_hash_and_cherry_pick(self):
        c = commit('s1', NOW, 'c1' + AI)
        same_pick = commit('s1-picked', NOW, 'c1' + AI)                      # 체리픽 — 해시만 다르고 시각·제목 같음
        self.assertEqual(self.run_check(c + same_pick)[0], 1)
        self.assertEqual(self.run_check(c, now=NOW + datetime.timedelta(minutes=10))[0], 0)   # 두 번째 둘러보기
        self.assertEqual(self.run_check(c, repos=('r1', 'r2'))[0], 0)       # 레포 두 곳에서 같은 커밋

    def test_seed_window_and_log(self):
        text = (commit('old', NOW - datetime.timedelta(days=9), 'old' + AI)
                + commit('d3', NOW - datetime.timedelta(days=3), 'd3' + AI)
                + commit('d1', NOW - datetime.timedelta(days=1), 'd1' + AI))
        self.assertEqual(self.run_check(text)[0], 2)                          # 7일보다 오래된 것은 안 셈
        self.assertEqual(self.g['seed_log']['ai']['snacks'], 2)
        self.assertTrue(self.logs and '2개' in self.logs[0])
        self.assertEqual(self.g['snacks'], 2)
        self.assertEqual(self.run_check(text, now=NOW + datetime.timedelta(minutes=10))[0], 0)
        self.assertEqual(len(self.logs), 1)                                   # 채움 로그는 처음 한 번만

    def test_cap_counts_by_commit_day(self):
        y = NOW - datetime.timedelta(days=1)
        text = ''.join(commit('y%d' % i, y - datetime.timedelta(minutes=i), 'y%d' % i + AI) for i in range(6)) + commit('t1', NOW, 't1' + AI)
        self.assertEqual(self.run_check(text)[0], 6)                           # 어제 5 + 오늘 1

    def test_pause_moves_window_only_after_first(self):
        petsnack.pause(self.g, 'ai', NOW)
        self.assertNotIn('ai', self.g['xcheck'])                              # 처음 켜기 전에 꺼 두었으면 나중에 7일 채움
        self.run_check('')
        petsnack.pause(self.g, 'ai', NOW + datetime.timedelta(days=3))
        self.assertEqual(self.g['xcheck']['ai'], (NOW + datetime.timedelta(days=3)).timestamp())

    def test_prune(self):
        self.run_check(commit('d3', NOW - datetime.timedelta(days=3), 'd3' + AI))
        petgrow.prune_extra(self.g, NOW + datetime.timedelta(days=20))
        self.assertEqual(self.g['xseen']['ai'], {})
        self.assertEqual(self.g['xday']['ai'], {})
        self.assertEqual(self.g['src']['ai'], 1)                               # 받은 간식은 그대로


class GoodPromptRule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = petsnack.load_rules(RULES)

    def test_rules_loaded_from_ai_share(self):
        self.assertIsNotNone(self.rules)

    def test_good_vs_hint(self):
        self.assertTrue(self.rules.good_first(GOOD))
        self.assertFalse(self.rules.good_first(NO_TARGET))                     # 💡 대상 없음
        self.assertFalse(self.rules.good_first(GOOD, next_text='아니 그거 말고 다른 파일'))   # 💡 다음에 고쳐 말함

    def test_skipped_prompts_not_rewarded(self):
        for t in (SHORT, '/commit', '이거 왜 안 되지?', '고쳐줘', ''):
            self.assertFalse(self.rules.good_first(t), t)


class Prompts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proj = os.path.join(self.tmp, 'C--work')
        os.makedirs(self.proj)
        self.rules = petsnack.load_rules(RULES)
        self.g = petgrow.blank()

    def session(self, sid, prompts, when=NOW, entry='cli', age=3600):
        def dumps(o, **kw):                                                     # Claude Code 기록처럼 공백 없이
            return json.dumps(o, separators=(',', ':'), **kw)
        path = os.path.join(self.proj, sid + '.jsonl')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(dumps({'type': 'summary', 'summary': 'x'}) + '\n')
            f.write(dumps({'type': 'user', 'isMeta': True, 'message': {'content': '<command-name>/clear</command-name>'}}) + '\n')
            for i, p in enumerate(prompts):
                ts = (when + datetime.timedelta(minutes=i)).astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
                f.write(dumps({'type': 'user', 'entrypoint': entry, 'timestamp': ts,
                                    'message': {'role': 'user', 'content': p}}, ensure_ascii=False) + '\n')
                f.write(dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}}) + '\n')
        t = (NOW - datetime.timedelta(seconds=age)).timestamp() if when >= NOW - datetime.timedelta(days=1) else when.timestamp()
        os.utime(path, (t, t))
        return path

    def check(self, now=NOW):
        return petsnack.check_prompts(self.g, [self.proj], self.rules, now, petgrow.on_extra, petgrow.mark, log=lambda m: None)

    def test_good_first_prompt_counts_once(self):
        self.session('s-good', [GOOD, '좋아 커밋해'])
        self.session('s-bad', [NO_TARGET, '응'])
        self.session('s-short', [SHORT, GOOD])                                  # 첫 프롬프트만 본다
        self.assertEqual(self.check()[0], 1)
        self.assertEqual(set(self.g['xseen']['prompt']), {'s-good', 's-bad', 's-short'})
        self.assertEqual(self.check(NOW + datetime.timedelta(minutes=10))[0], 0)

    def test_sdk_sessions_ignored(self):
        self.session('s-sdk', [GOOD, '응'], entry='sdk-cli')
        self.assertEqual(self.check()[0], 0)

    def test_single_prompt_waits_to_settle(self):
        self.session('s-new', [GOOD], age=60)
        self.assertEqual(self.check()[0], 0)
        self.assertNotIn('s-new', self.g['xseen'].get('prompt', {}))            # 아직 판정 안 함
        self.assertEqual(self.check(NOW + datetime.timedelta(hours=1))[0], 1)

    def test_cap_and_seed_window(self):
        for i in range(5):
            self.session('s%d' % i, [GOOD + ' %d' % i, '응'])
        self.session('s-old', [GOOD, '응'], when=NOW - datetime.timedelta(days=9))
        self.assertEqual(self.check()[0], petgrow.EXTRA_CAP['prompt'])
        self.assertEqual(self.g['seed_log']['prompt']['snacks'], 3)
        self.assertEqual(petgrow.view(self.g)['src']['prompt'], 3)

    def test_head_reads_only_human_prompts(self):
        path = self.session('s-h', ['<system-reminder>x</system-reminder>' + GOOD, '두 번째', '세 번째'])
        h = petsnack.session_head(path, self.rules.clean_text)
        self.assertEqual((h['first'], h['next'], h['sdk']), (GOOD, '두 번째', False))


class Merge(unittest.TestCase):
    def test_view_breakdown_with_automation(self):
        g = petgrow.blank()
        petgrow.on_run(g, {'macro': 'm', 'status': 'ok', 'trigger': 'manual'}, now=NOW)
        petgrow.on_extra(g, 'ai', ['x'], NOW, NOW)
        petgrow.on_extra(g, 'prompt', ['s'], NOW, NOW)
        v = petgrow.view(g)
        self.assertEqual((v['snacks'], v['src']), (3, {'auto': 1, 'ai': 1, 'prompt': 1}))
        self.assertEqual(v['week']['snacks'], 3)

    def test_old_state_file_loads(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, 'g.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'snacks': 12, 'seeded': True}, f)
        g = petgrow.load(p)
        self.assertEqual(petgrow.view(g)['src'], {'auto': 12, 'ai': 0, 'prompt': 0})
        self.assertEqual(petgrow.on_extra(g, 'ai', ['x'], NOW, NOW), (1, False))


class KitSources(unittest.TestCase):
    """키트: ai_share 가 꺼져 있으면 허브 레포만, 켜져 있으면 ai_share.repos + 허브 레포. 대화 기록은 언제나 읽는다."""
    def setUp(self):
        import kit
        import macrohub
        self.kit, self.mh = kit, macrohub
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, 'work', '.git'))
        saved = kit.section
        self.addCleanup(setattr, kit, 'section', saved)
        self.addCleanup(setattr, petsnack, 'my_authors', petsnack.my_authors)
        petsnack.my_authors = lambda repo, extra=(): {'me'}

    def sources(self, cfg):
        self.kit.section = lambda name, default=None: cfg if name == 'ai_share' else default
        return self.mh.snack_sources()

    def test_disabled_uses_hub_repo_only(self):
        repos, authors, dirs = self.sources({'enabled': False, 'repos': [os.path.join(self.tmp, 'work')]})
        self.assertEqual(repos, [petsnack.git_top(HUB)] if petsnack.git_top(HUB) else [])
        self.assertIsInstance(dirs, list)

    def test_enabled_adds_configured_repos(self):
        repos, _, _ = self.sources({'enabled': True, 'repos': [os.path.join(self.tmp, 'work'), os.path.join(self.tmp, 'nope')]})
        self.assertEqual(repos[0], os.path.normpath(os.path.join(self.tmp, 'work')))
        self.assertNotIn(os.path.normpath(os.path.join(self.tmp, 'nope')), repos)

    def test_tracker_key_counts_as_target(self):
        import re
        rules = petsnack.load_rules(RULES)
        t = 'PROJ_X 9917 에서 저장 버튼이 두 번 눌리는 문제를 고쳐줘. 한 번만 저장되면 완료, 기존 테스트는 그대로 통과해야 해'
        self.assertTrue(rules.good_first('ABC-123 ' + t))
        self.assertTrue(rules.good_first('#77 ' + t.replace('PROJ_X 9917 에서 ', '')))
        plain = '주문 저장이 가끔 두 번씩 되는 문제를 고쳐줘. 한 번만 저장되면 완료, 기존 테스트는 그대로 통과해야 해'
        self.assertFalse(rules.good_first('Q9917 ' + plain))
        self.assertTrue(rules.good_first('Q9917 ' + plain, key_re=re.compile(r'Q\d{4}')))


if __name__ == '__main__':
    unittest.main()
