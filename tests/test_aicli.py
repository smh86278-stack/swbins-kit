# -*- coding: utf-8 -*-
"""AI 고르기(tools\\macro-hub\\aicli.py) — 엔진별 명령 모양·설정·가짜 명령줄 도구로 글 받기·허브 직접 실행.

    python -m unittest discover -s tests

진짜 codex·gemini 는 부르지 않는다 — 같은 방식(.cmd · 표준 입력 · -o 파일)으로 불리는 가짜 도구를 임시 폴더에 만든다.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, os.path.normpath(HUB))
import aicli      # noqa: E402
import kit        # noqa: E402

FAKE = r'''import sys
sys.stdout.reconfigure(encoding="utf-8")
args = sys.argv[1:]
data = sys.stdin.buffer.read().decode("utf-8")
if "-o" in args:
    open(args[args.index("-o") + 1], "w", encoding="utf-8").write("ANSWER:" + data)
print("ARGS " + " ".join(args[:2]))
print("GOT " + data.splitlines()[0])
'''


def fake_tool(tmp, name):
    """name.cmd → python fake.py — npm 으로 깐 codex.cmd 처럼 .cmd 로 불린다."""
    py = os.path.join(tmp, 'fake_ai.py')
    with open(py, 'w', encoding='utf-8') as f:
        f.write(FAKE)
    cmd = os.path.join(tmp, name + '.cmd')
    with open(cmd, 'w', encoding='ascii') as f:
        f.write('@"%s" "%s" %%*\r\n' % (sys.executable, py))
    return cmd


class Settings(unittest.TestCase):
    def test_defaults_and_bad_values(self):
        self.assertEqual(aicli.settings({})['engine'], 'claude')
        s = aicli.settings({'ai': {'engine': 'gpt', 'gemini_approval': 'all'}})
        self.assertEqual((s['engine'], s['gemini_approval']), ('claude', 'auto_edit'))
        self.assertEqual(aicli.settings({'ai': {'engine': 'codex', 'model': ' o4 '}})['model'], 'o4')

    def test_set_engine_keeps_other_settings(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        f = os.path.join(tmp, 'config.local.json')
        with open(f, 'w', encoding='utf-8') as fp:
            json.dump({'company': {'name': 'X'}, 'ai': {'model': 'm1'}}, fp)
        with mock.patch.object(kit, 'F_CONFIG', f), mock.patch.object(kit, 'audit', lambda *a, **k: None):
            self.assertEqual(aicli.set_engine('codex')['engine'], 'codex')
            with self.assertRaises(ValueError):
                aicli.set_engine('gpt')
        with open(f, encoding='utf-8') as fp:
            cfg = json.load(fp)
        self.assertEqual(cfg['ai'], {'model': 'm1', 'engine': 'codex'})
        self.assertNotIn('mail', cfg)                     # 기본값을 써 넣지 않는다


class AgentCmd(unittest.TestCase):
    def test_codex_sandboxed_in_workdir(self):
        with mock.patch.object(aicli, 'exe', lambda e: r'C:\npm\codex.cmd'):
            argv, shell, note = aicli.agent_cmd('codex', r'C:\hub', {'engine': 'codex', 'model': '', 'gemini_approval': 'auto_edit'})
        self.assertEqual(argv[1], 'exec')
        self.assertEqual(argv[argv.index('--cd') + 1], r'C:\hub')
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'workspace-write')   # 그 폴더 안에서만 쓴다
        self.assertIn('sandbox_workspace_write.network_access=true', argv)       # 웹 자동화 시험이 돌게
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', argv)
        self.assertEqual(argv[-1], '-')                                          # 프롬프트는 표준 입력
        self.assertEqual((shell, note), (os.name == 'nt', ''))

    def test_gemini_approval_and_note(self):
        with mock.patch.object(aicli, 'exe', lambda e: r'C:\npm\gemini.cmd'):
            s = {'engine': 'gemini', 'model': 'flash', 'gemini_approval': 'auto_edit'}
            argv, _, note = aicli.agent_cmd('gemini', r'C:\hub', s)
            self.assertEqual(argv[argv.index('--approval-mode') + 1], 'auto_edit')
            self.assertEqual(argv[argv.index('-m') + 1], 'flash')
            self.assertIn('🧪', note)
            self.assertIn('명령을 실행할 수 없어', aicli.agent_prompt('gemini', '부탁', s))
            s['gemini_approval'] = 'yolo'
            self.assertEqual(aicli.agent_cmd('gemini', r'C:\hub', s)[2], '')
            self.assertEqual(aicli.agent_prompt('gemini', '부탁', s), '부탁')

    def test_refuses(self):
        with self.assertRaises(ValueError):
            aicli.agent_cmd('claude', r'C:\hub')
        with mock.patch.object(aicli, 'exe', lambda e: None):
            with self.assertRaises(RuntimeError) as c:
                aicli.agent_cmd('codex', r'C:\hub', aicli.settings({}))
            self.assertIn('npm install -g @openai/codex', str(c.exception))


@unittest.skipUnless(os.name == 'nt', '가짜 .cmd 도구는 윈도우 전용')
class FakeTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_text_codex_reads_last_message_file(self):
        cmd = fake_tool(self.tmp, 'codex')
        with mock.patch.object(aicli, 'exe', lambda e: cmd):
            out = aicli.text('주간 보고 써 줘\n자료…', 'codex')
        self.assertEqual(out, 'ANSWER:주간 보고 써 줘\n자료…')       # -o 파일의 마지막 답

    def test_text_gemini_reads_stdout(self):
        cmd = fake_tool(self.tmp, 'gemini')
        with mock.patch.object(aicli, 'exe', lambda e: cmd):
            out = aicli.text('한 줄 요약', 'gemini')
        self.assertIn('GOT 한 줄 요약', out)

    def test_hub_runs_ai_directly(self):
        import macrohub
        cmd = fake_tool(self.tmp, 'codex')
        with mock.patch.object(aicli, 'exe', lambda e: cmd), \
                mock.patch.object(aicli, 'settings', lambda cfg=None: {'engine': 'codex', 'model': '', 'gemini_approval': 'auto_edit'}), \
                mock.patch.object(macrohub, 'broadcast', lambda *a: None), \
                mock.patch.object(macrohub, 'audit', lambda *a, **k: None):
            run = macrohub.start_ai_run('말로 부탁하기', '자동화 허브에 자동화 만들어줘 — 공지 확인')
            for _ in range(100):
                if run.ended:
                    break
                time.sleep(0.1)
        text = '\n'.join(run.lines)
        self.assertEqual(run.status, 'ok', text)
        self.assertTrue(run.tool)                                          # 실행 기록 파일·실패 알림엔 안 넣는다
        self.assertIn('ARGS exec --cd', text)
        self.assertIn('GOT 자동화 허브에 자동화 만들어줘 — 공지 확인', text)   # 프롬프트가 표준 입력으로 갔다
        self.assertIn('Codex', run.name)


if __name__ == '__main__':
    unittest.main()
