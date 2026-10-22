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


class FakeOllama:
    """/api/tags · /api/chat(스트림) 만 흉내 내는 가짜 Ollama — answers 를 차례로 답한다."""
    def __init__(self, answers, models=('qwen3:8b',)):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        me = self
        self.answers, self.asked = list(answers), []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({'models': [{'name': m} for m in models]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                me.asked.append(req)
                if req['model'] not in models:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b'{"error":"model not found"}')
                    return
                text = me.answers.pop(0)
                self.send_response(200)
                self.end_headers()
                half = len(text) // 2
                for part in (text[:half], text[half:]):
                    self.wfile.write(json.dumps({'message': {'content': part}, 'done': False}).encode() + b'\n')
                self.wfile.write(b'{"message":{"content":""},"done":true}\n')

        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = 'http://127.0.0.1:%d' % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


GOOD = ('<think>생각</think>=== FILE: macros.local/notice_check.py ===\n```python\nMETA = {"name": "공지 확인"}\n\n'
        'def run(ctx):\n    ctx.log("ok")\n```\n=== END ===\n공지 확인 자동화를 만들었어요.')


class Ollama(unittest.TestCase):
    def setUp(self):
        import ollama_agent
        self.oa = ollama_agent
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.local = os.path.join(self.tmp, 'macros.local')
        for name, val in (('LOCAL', self.local), ('BACKUP', os.path.join(self.tmp, 'bak'))):
            p = mock.patch.object(ollama_agent, name, val)
            p.start()
            self.addCleanup(p.stop)

    def serve(self, answers, **kw):
        srv = FakeOllama(answers, **kw)
        self.addCleanup(srv.close)
        return srv

    def run_agent(self, srv, prompt, *extra):
        import io
        out = io.StringIO()
        stdin = mock.Mock(buffer=io.BytesIO(prompt.encode('utf-8')))
        with mock.patch.object(sys, 'stdin', stdin), mock.patch.object(sys, 'stdout', out), \
                mock.patch.object(sys, 'argv', ['ollama_agent.py', '--url', srv.url] + list(extra)):
            code = self.oa.main()
        return code, out.getvalue()

    def test_settings_and_status(self):
        s = aicli.settings({'ai': {'engine': 'ollama', 'ollama_url': 'http://x:1/', 'ollama_test': 'yes'}})
        self.assertEqual((s['engine'], s['ollama_url'], s['ollama_test']), ('ollama', 'http://x:1', False))   # true 만 켠다
        srv = self.serve([])
        with mock.patch.object(aicli, 'settings', lambda cfg=None: {'engine': 'ollama', 'model': '', 'gemini_approval': 'auto_edit',
                                                                 'ollama_url': srv.url, 'ollama_test': False}):
            row = [e for e in aicli.status()['engines'] if e['id'] == 'ollama'][0]
        self.assertTrue(row['installed'])
        self.assertEqual(row['models'], ['qwen3:8b'])
        with mock.patch.object(aicli, 'settings', lambda cfg=None: {'engine': 'ollama', 'model': 'gemma3:4b', 'gemini_approval': 'auto_edit',
                                                                 'ollama_url': srv.url, 'ollama_test': False}):
            row = [e for e in aicli.status()['engines'] if e['id'] == 'ollama'][0]
        self.assertFalse(row['installed'])
        self.assertEqual(row['install'], '명령 창에서 ollama pull gemma3:4b')

    def test_agent_cmd(self):
        srv = self.serve([])
        s = {'engine': 'ollama', 'model': '', 'gemini_approval': 'auto_edit', 'ollama_url': srv.url, 'ollama_test': False}
        argv, shell, note = aicli.agent_cmd('ollama', r'C:\hub', s)
        self.assertFalse(shell)
        self.assertTrue(argv[2].endswith('ollama_agent.py'))
        self.assertEqual(argv[argv.index('--model') + 1], 'qwen3:8b')
        self.assertNotIn('--test', argv)
        self.assertIn('🧪', note)
        s['ollama_test'] = True
        self.assertIn('--test', aicli.agent_cmd('ollama', r'C:\hub', s)[0])
        s['ollama_url'] = 'http://127.0.0.1:9'          # 꺼져 있음
        with self.assertRaises(RuntimeError):
            aicli.agent_cmd('ollama', r'C:\hub', s)

    def test_safe_target(self):
        ok = self.oa.safe_target('macros.local/a_b.py')
        self.assertEqual(ok, os.path.realpath(os.path.join(self.local, 'a_b.py')))
        for bad in ('../macrohub.py', 'macros.local/../x.py', 'macros/job_x.py', 'macros.local/a.txt', 'C:/x.py', '.hidden.py'):
            self.assertIsNone(self.oa.safe_target(bad), bad)

    def test_writes_file_without_test(self):
        srv = self.serve([GOOD])
        code, out = self.run_agent(srv, '자동화 만들어줘 — 공지 확인')
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.local, 'notice_check.py'), encoding='utf-8') as f:
            body = f.read()
        self.assertTrue(body.startswith('META = '))         # 울타리·think 는 빠진다
        self.assertNotIn('```', body)
        self.assertIn('공지 확인 자동화를 만들었어요', out)
        self.assertIn('🧪', out)
        self.assertIn('--- 안내서(AUTHORING.md) ---', srv.asked[0]['messages'][0]['content'])   # 안내서를 같이 줬다

    def test_fix_includes_file_and_backs_up(self):
        os.makedirs(self.local)
        with open(os.path.join(self.local, 'notice_check.py'), 'w', encoding='utf-8') as f:
            f.write('OLD = 1\n')
        srv = self.serve([GOOD])
        code, out = self.run_agent(srv, '실패했어 — 고쳐줘.\n파일: C:\\kit\\macros.local\\notice_check.py')
        self.assertEqual(code, 0, out)
        self.assertIn('OLD = 1', srv.asked[0]['messages'][1]['content'])      # 지금 파일 내용을 같이 줬다
        baks = os.listdir(os.path.join(self.tmp, 'bak'))
        self.assertEqual(len(baks), 1)

    def test_refuses_outside_and_retries_without_files(self):
        bad = '=== FILE: ../macrohub.py ===\nx\n=== END ==='
        srv = self.serve(['그냥 말만', bad])
        code, out = self.run_agent(srv, '만들어줘')
        self.assertEqual(code, 1)
        self.assertIn('쓰지 않음', out)
        self.assertEqual(len(srv.asked), 2)                  # 파일이 없으면 한 번 더 달라고 했다
        self.assertFalse(os.path.isdir(self.local) and os.listdir(self.local))

    def test_test_loop_retries_until_pass(self):
        srv = self.serve([GOOD, GOOD])
        results = iter([(False, 'Traceback: boom'), (True, 'ok')])
        with mock.patch.object(self.oa, 'run_test', lambda py, p: next(results)):
            code, out = self.run_agent(srv, '만들어줘', '--test')
        self.assertEqual(code, 0, out)
        self.assertIn('시험 실패', out)
        self.assertIn('Traceback: boom', srv.asked[1]['messages'][-1]['content'])

    def test_missing_model_message(self):
        srv = self.serve([GOOD])
        code, out = self.run_agent(srv, '만들어줘', '--model', 'nope:1b')
        self.assertEqual(code, 1)
        self.assertIn('ollama pull nope:1b', out)

    def test_text(self):
        srv = self.serve(['<think>x</think>요약 끝'])
        with mock.patch.object(aicli, 'settings', lambda cfg=None: {'ollama_url': srv.url}):
            self.assertEqual(aicli.text('요약해', 'ollama'), '요약 끝')


if __name__ == '__main__':
    unittest.main()
