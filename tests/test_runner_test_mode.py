# -*- coding: utf-8 -*-
"""자동화 시험 실행(runner.py --test)과 「말로 부탁하기」·「🩹 고쳐 달라기」 부탁 글 — Claude 가 만들고·시험하고·고치는 루프.

- --test: 허브와 같은 id(내 자동화 폴더면 local/<이름>) · META params 기본값 위에 이름=값 · 마지막 줄 '🧪 시험 결과'
- ctx.for_real(): 시험이면 건너뛰고 로그만, 평소엔 그대로
- 시험 제한 시간(META timeout)이 지나면 멈춘다
- 부탁 글에 작성 안내서(AUTHORING.md)·시험 명령이 들어간다
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
import macrohub   # noqa: E402
import runner     # noqa: E402

MACRO = '''# -*- coding: utf-8 -*-
META = {"name": "시험용", "kind": "ctx", "params": {"n": 1, "who": "a"}, "timeout": %(timeout)s}


def run(ctx):
    ctx.log("macro=%%s params=%%s dry=%%s" %% (ctx.macro, sorted(ctx.params.items()), ctx.dry_run))
    if ctx.for_real("메일 보내기"):
        ctx.log("보냈음")
    if ctx.params.get("boom"):
        raise RuntimeError("일부러 실패")
    if ctx.params.get("hang"):
        import time
        time.sleep(30)
'''


class TestMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, timeout=60, where=None):
        path = os.path.join(where or self.tmp, 'zz_runner_test_mode.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(MACRO % {'timeout': timeout})
        return path

    def _run(self, path, *pairs, test=True):
        cmd = [sys.executable, os.path.join(HUB, 'runner.py')] + (['--test'] if test else []) + [path] + list(pairs)
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.pop('MACROHUB_CTX', None)
        r = subprocess.run(cmd, capture_output=True, timeout=60, env=env, cwd=HUB)
        return r.returncode, r.stdout.decode('utf-8', 'replace')

    def test_success_skips_for_real_and_merges_params(self):
        code, out = self._run(self._write(), 'n=5', 'who=나')
        self.assertEqual(code, 0, out)
        self.assertIn("params=[('n', 5), ('who', '나')] dry=True", out)
        self.assertIn('🧪 시험이라 건너뜀: 메일 보내기', out)
        self.assertNotIn('보냈음', out)
        self.assertIn('🧪 시험 결과: 성공', out.strip().splitlines()[-1])

    def test_failure_reports_and_exit_code(self):
        code, out = self._run(self._write(), 'boom=true')
        self.assertEqual(code, 1)
        self.assertIn('일부러 실패', out)
        self.assertIn('🧪 시험 결과: 실패', out.strip().splitlines()[-1])

    def test_timeout_stops(self):
        code, out = self._run(self._write(timeout=2), 'hang=true')
        self.assertEqual(code, 1)
        self.assertIn('시험 시간 초과', out)
        self.assertIn('🧪 시험 결과: 실패', out)

    def test_normal_run_is_not_dry(self):
        code, out = self._run(self._write(), test=False)
        self.assertEqual(code, 0, out)
        self.assertIn('보냈음', out)
        self.assertNotIn('🧪', out)

    def test_bad_pair(self):
        code, out = self._run(self._write(), 'oops')
        self.assertNotEqual(code, 0)

    def test_same_id_as_hub_for_own_macro(self):
        local = os.path.join(HUB, 'macros.local')
        meta = {'params': {'a': 1}}
        raw = runner.test_ctx(os.path.join(local, 'order.py'), ['a=2', 'b="x y"'], meta)
        self.assertEqual(raw, {'macro': 'local/order', 'params': {'a': 2, 'b': 'x y'}, 'trigger': {'kind': 'test'}, 'dry_run': True,
                               'no_hub': True})
        self.assertEqual(runner.test_ctx(os.path.join(self.tmp, 'x.py'), [], {})['macro'], 'x')
        self.assertEqual(meta, {'params': {'a': 1}})                    # META 를 고치지 않는다


class Prompts(unittest.TestCase):
    def test_ask_prompt_has_guide_and_test_command(self):
        text = macrohub.ask_prompt('공지 첫 글이 바뀌면 알려 줘', '30분마다')
        self.assertTrue(text.startswith('자동화 허브에 자동화 만들어줘 — 공지 첫 글이 바뀌면 알려 줘\n언제: 30분마다 자동 실행'))
        self.assertIn(os.path.join(HUB, 'AUTHORING.md'), text)
        self.assertIn('runner.py --test macros.local\\', text)
        self.assertIn('최대 3번', text)
        self.assertIn('ctx.for_real', text)
        self.assertNotIn('언제:', macrohub.ask_prompt('x'))
        with self.assertRaises(ValueError):
            macrohub.ask_prompt('  ')

    def test_guide_exists_and_matches_runner(self):
        with open(macrohub.AUTHORING, encoding='utf-8') as f:
            guide = f.read()
        for word in ('runner.py --test', 'ctx.for_real', 'macros.local', '최대 3번', 'secrets.local.json', '🧪 시험 결과'):
            self.assertIn(word, guide)

    def test_test_python_is_console(self):
        self.assertNotEqual(os.path.basename(macrohub.test_python()).lower(), 'pythonw.exe')


if __name__ == '__main__':
    unittest.main()
