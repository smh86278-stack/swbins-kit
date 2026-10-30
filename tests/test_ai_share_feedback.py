# -*- coding: utf-8 -*-
"""AI 작업 회고(tools/ai-share-agent) 내 프롬프트 피드백 — 규칙 점검 · ✨ AI 피드백 캐시.
AI 를 실제로 부르지 않는다(가짜 함수), 임시 폴더만 쓴다.

    python -X utf8 -m unittest tests.test_ai_share_feedback -v
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')
TOOL = os.path.join(ROOT, 'tools', 'ai-share-agent')
sys.path.insert(0, HUB)
sys.path.insert(0, TOOL)

spec = importlib.util.spec_from_file_location('ai_share_agent_feedback', os.path.join(TOOL, 'agent.py'))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def codes(hints, kind='tip'):
    return [h['code'] for h in hints if h['kind'] == kind]


class Base(unittest.TestCase):
    """임시 wiki 로 설정을 바꿔 끼운다 — 실제 config.local.json·data.local 을 건드리지 않는다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(agent.configure)
        full = {'ai_share': {'wiki_dir': str(self.tmp / 'wiki')}}
        agent.configure(agent.load_cfg(full), full, None, 'tok')


class Rules(Base):
    def test_vague_first_prompt(self):
        self.assertIn('vague', codes(agent.prompt_hints('이거 고쳐줘', first=True)))

    def test_short_followup_is_fine(self):
        # 대화 중간의 짧은 말은 앞 맥락이 있어 문제 아님
        self.assertEqual(agent.prompt_hints('이거 고쳐줘', first=False), [])
        self.assertEqual(agent.prompt_hints('응 진행해', first=True), [])

    def test_no_target(self):
        self.assertIn('target', codes(agent.prompt_hints('주문 가져오기가 가끔 두 번 되는 문제가 있는데 원인 찾아서 고쳐줘', first=True)))

    def test_target_present(self):
        h = agent.prompt_hints('ABC-123 src/orders/import.py 에서 주문 가져오기가 두 번 되는 문제 고쳐줘. '
                               '같은 주문은 1건만 저장되면 완료', first=True)
        self.assertEqual(codes(h), [])
        self.assertIn('target', codes(h, 'good'))
        self.assertIn('criteria', codes(h, 'good'))

    def test_issue_key_alone_is_target(self):
        # 파일 이름 없이 이슈 키만 있어도 대상이 있는 것 — 흔한 키 모양(ABC-123 · #123)
        for t in ('ABC-77 주문 가져오기가 두 번 되는 문제 원인 찾아서 고쳐줘', '#77 주문 가져오기가 두 번 되는 문제 원인 찾아서 고쳐줘'):
            self.assertNotIn('target', codes(agent.prompt_hints(t, first=True)), t)

    def test_no_criteria(self):
        h = agent.prompt_hints('order_list.php 의 내보내기 버튼 로직을 새 API 로 바꿔서 다시 구현해줘 부탁해', first=True)
        self.assertIn('criteria', codes(h))

    def test_many_asks(self):
        h = agent.prompt_hints('버튼 문구 바꿔줘 그리고 저장 오류도 고쳐줘 테스트도 추가해줘', first=False)
        self.assertIn('many', codes(h))
        numbered = '할 일 정리\n1. 저장 버튼 문구 바꿔줘\n2. 저장할 때 나는 오류 고쳐줘\n3. 테스트 추가해줘'
        self.assertNotIn('many', codes(agent.prompt_hints(numbered)))
        self.assertIn('steps', codes(agent.prompt_hints(numbered), 'good'))

    def test_scope(self):
        self.assertIn('scope', codes(agent.prompt_hints('tools/ai-share-agent/agent.py 전부 리팩터해줘', first=True)))
        self.assertNotIn('scope', codes(agent.prompt_hints('tools/ai-share-agent/agent.py 전부 리팩터해줘. 함수 이름은 그대로 유지', first=True)))

    def test_correction_next(self):
        h = agent.prompt_hints('목록에 날짜 칸 추가해줘', next_text='아니 수정일 말고 등록일')
        self.assertIn('redo', codes(h))
        self.assertNotIn('redo', codes(agent.prompt_hints('목록에 날짜 칸 추가해줘', next_text='좋아 커밋해줘')))

    def test_slash_command_skipped(self):
        self.assertEqual(agent.prompt_hints('/code-review high', first=True), [])

    def test_annotate(self):
        sess = [{'prompts': [{'date': '2026-10-30', 'text': '이거 고쳐줘'}, {'date': '2026-10-30', 'text': '아니 그거 말고'}]}]
        out = agent.annotate_sessions(sess, fb={})
        p = out[0]['prompts'][0]
        self.assertEqual(p['id'], agent.prompt_id('이거 고쳐줘'))
        self.assertIn('redo', codes(p['hints']))
        self.assertIsNone(p['ai'])


class Cache(Base):
    def setUp(self):
        super().setUp()
        agent.PRIVATE.mkdir(parents=True, exist_ok=True)
        self.texts = ['이거 고쳐줘', 'ABC-1 order.php 고쳐줘 password=hunter2secret']
        (agent.PRIVATE / 'prompts.json').write_text(json.dumps(
            {'ABC-1': [{'prompts': [{'date': '2026-10-30', 'text': t} for t in self.texts]}]},
            ensure_ascii=False), encoding='utf-8')
        self.ids = [agent.prompt_id(t) for t in self.texts]
        self.calls = []

    def fake_ai(self, prompt, system):
        self.calls.append(prompt)
        items = json.loads(prompt[prompt.index('['):])
        return ('```json\n' + json.dumps([{'id': it['id'], 'score': 9, 'good': '좋음', 'improve': '대상을 적자',
                                          'rewrite': '고친 예'} for it in items] + [{'id': 'zzzz', 'score': 3}],
                                         ensure_ascii=False) + '\n```', '가짜 AI')

    def test_cache_lives_in_private(self):
        self.assertEqual(agent.feedback_file(), agent.PRIVATE / 'prompt_feedback.json')

    def test_runs_once_and_caches(self):
        n = agent.run_feedback(self.ids + ['ffffffffffffffff'], ai=self.fake_ai)
        self.assertEqual(n, 2)
        fb = agent.load_feedback()
        self.assertEqual(set(fb), set(self.ids))                 # 받은 id 아닌 'zzzz' 는 버림
        self.assertEqual(fb[self.ids[0]]['score'], 5)            # 1~5 로 자름
        self.assertEqual(fb[self.ids[0]]['engine'], '가짜 AI')
        self.assertNotIn('hunter2secret', self.calls[0])         # 보내기 전에 가린다
        # 다시 눌러도 캐시에 있으면 AI 를 부르지 않는다
        self.assertEqual(agent.run_feedback(self.ids, ai=self.fake_ai), 0)
        self.assertEqual(len(self.calls), 1)
        sess = json.loads((agent.PRIVATE / 'prompts.json').read_text(encoding='utf-8'))['ABC-1']
        self.assertEqual(agent.annotate_sessions(sess)[0]['prompts'][0]['ai']['score'], 5)

    def test_cap(self):
        many = {'ABC-2': [{'prompts': [{'date': '2026-10-30', 'text': f'프롬프트 {i}'} for i in range(30)]}]}
        (agent.PRIVATE / 'prompts.json').write_text(json.dumps(many, ensure_ascii=False), encoding='utf-8')
        ids = [agent.prompt_id(f'프롬프트 {i}') for i in range(30)]
        self.assertEqual(agent.run_feedback(ids, ai=self.fake_ai), agent.FB_MAX)

    def test_bad_answer(self):
        with self.assertRaises(ValueError):
            agent.run_feedback(self.ids, ai=lambda p, s: ('JSON 이 아닌 답', 'x'))
        self.assertEqual(agent.load_feedback(), {})

    def test_ai_text_uses_hub_choice(self):
        # 허브 「AI 고르기」(aicli) 에서 고른 엔진으로 — 실제 실행은 가짜로 막는다
        import aicli
        with mock.patch.object(aicli, 'settings', return_value={'engine': 'gemini', 'model': ''}), \
                mock.patch.object(aicli, 'text', return_value='[]') as text:
            out, name = agent.ai_text('글', '지시')
        self.assertEqual((out, name), ('[]', aicli.NAMES['gemini']))
        self.assertEqual(text.call_args[0][1], 'gemini')
        self.assertEqual(text.call_args[0][4], '지시')


if __name__ == '__main__':
    unittest.main()
