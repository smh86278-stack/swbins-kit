# -*- coding: utf-8 -*-
"""허브 MCP 서버(tools/macro-hub/mcp_server.py) · 아침 브리핑 · setup.py --mcp — 진짜 허브·메일·claude 에 닿지 않는다."""
import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')
sys.path.insert(0, HUB)
sys.path.insert(0, os.path.join(HUB, 'macros'))
sys.path.insert(0, ROOT)
import mcp_server as M     # noqa: E402
import job_morning_brief as J     # noqa: E402
import setup     # noqa: E402

NOW_MS = int(time.time() * 1000)


class McpServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        old = (M.F_RUNS, M.JOBS, M.JOB_AUDIT, M.hub_get)
        self.addCleanup(lambda: setattr(M, 'F_RUNS', old[0]) or setattr(M, 'JOBS', old[1])
                        or setattr(M, 'JOB_AUDIT', old[2]) or setattr(M, 'hub_get', old[3]))
        M.F_RUNS = os.path.join(self.tmp, 'runs.jsonl')
        M.JOBS = os.path.join(self.tmp, 'jobs')
        M.JOB_AUDIT = os.path.join(self.tmp, 'job-audit.jsonl')
        os.makedirs(M.JOBS)
        rows = [
            {'id': 1, 'macro': 'job_a', 'name': '정기 메일', 'status': 'ok', 'started': NOW_MS - 3600e3, 'tail': ['ok']},
            {'id': 2, 'macro': 'local/b', 'name': '공지 감시', 'status': 'fail', 'started': NOW_MS - 7200e3, 'tail': ['오류: 요소 없음']},
            {'id': 3, 'macro': 'local/b', 'name': '공지 감시', 'status': 'fail', 'started': NOW_MS - 50 * 3600e3, 'tail': ['옛 실패']},
            {'id': 4, 'macro': '__pick__', 'name': '요소 찍기', 'status': 'fail', 'started': NOW_MS, 'tool': True},
        ]
        with open(M.F_RUNS, 'w', encoding='utf-8') as f:
            f.write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in sorted(rows, key=lambda r: r['started'])))
        M.hub_get = self.fake_hub

    def fake_hub(self, path, timeout=5):
        if path == '/api/macros':
            return [{'id': 'svc_x', 'name': '디스패치 대화', 'service': True, 'enabled': True, 'running': {'id': 9}},
                    {'id': 'svc_y', 'name': '워커', 'service': True, 'enabled': True, 'running': None}]
        if path == '/api/ops/features':
            return {'features': [
                {'feature': 'cred_watch', 'label': '로그인·키 만료 예고', 'configured': True, 'ago': '3분 전', 'note': '',
                 'items': [{'name': 'Claude 로그인', 'ok': False, 'text': '곧 만료 — 3일 남음'}, {'name': '메일', 'ok': True, 'text': '정상'}]},
                {'feature': 'tidy', 'label': '폴더 정리', 'configured': False, 'items': []}]}
        if path.startswith('/api/run?'):
            raise LookupError('허브 답: 404')
        raise AssertionError(path)

    def test_protocol_read_only(self):
        init, note, lst, bad = [M.handle(m) for m in (
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'hub_run', 'arguments': {}}})]
        self.assertEqual(init['result']['protocolVersion'], '2025-03-26')
        self.assertIsNone(note)
        names = [t['name'] for t in lst['result']['tools']]
        self.assertIn('hub_features', names)
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in lst['result']['tools']))
        self.assertFalse([n for n in names if any(w in n for w in ('start', 'stop', 'set', 'secret'))])
        self.assertEqual(bad['error']['code'], -32602)

    def test_history_log_features(self):
        self.assertEqual([r['id'] for r in M.history(24)], [1, 2])
        self.assertEqual([r['id'] for r in M.history(0, 'fail')], [2, 3])
        self.assertIn('오류: 요소 없음', M.tool_run_log({'id': 2}))
        self.assertIn('켜져 있는데 안 돎', M.tool_status({}))
        bad = M.tool_features({'bad_only': True})
        self.assertIn('✖ Claude 로그인', bad)
        self.assertNotIn('○ 메일', bad)
        self.assertNotIn('폴더 정리', M.tool_features({}))                  # 설정 안 된 기능은 뺀다

    def test_brief(self):
        subject, body = M.brief()
        self.assertFalse(subject.startswith('['))                          # kit.alert 가 [회사 이름] 을 붙인다
        self.assertIn('볼 것 2건', subject)                                 # 자동화 실패 1 + 기능 ✖ 1
        for want in ('성공 1 · 실패 1', '안 도는 것: 워커', '✖ 로그인·키 만료 예고 · Claude 로그인'):
            self.assertIn(want, body)

        def down(path, timeout=5):
            raise M.HubDown('꺼짐')
        M.hub_get = down
        _s, body = M.brief()
        self.assertIn('허브 응답 없음', body)
        self.assertIn('성공 1 · 실패 1', body)


class MorningBriefJob(unittest.TestCase):
    def test_settings_and_due(self):
        self.assertEqual(J.settings({}), {'enabled': False, 'at': '08:30', 'days': 'mon-fri'})
        w = J.settings({'morning_brief': {'enabled': True, 'at': '08:30', 'days': ['mon', 'tue']}})
        self.assertEqual(w['days'], 'mon,tue')
        mon = datetime.datetime(2026, 10, 19, 8, 40)                       # 월요일 08:40
        self.assertTrue(J.is_due(w, {}, mon))
        self.assertFalse(J.is_due(w, {'last_run': mon.timestamp()}, mon))   # 오늘 이미 보냄
        self.assertFalse(J.is_due(w, {}, mon.replace(hour=8, minute=0)))   # 아직 시각 전
        self.assertFalse(J.is_due(w, {'last_fail': mon.timestamp() - 60}, mon))   # 방금 실패 — 30분 뒤 다시


class SetupMcp(unittest.TestCase):
    def test_add_mcp_tool(self):
        cfg = {}
        self.assertTrue(setup.add_mcp_tool(cfg))
        d = cfg['dispatch']
        self.assertEqual(d['extra_tools'], ['mcp__hub'])
        self.assertEqual(d['read_tools'], setup.READ_DEFAULT + ['mcp__hub'])   # 안 적어 뒀으면 기본 목록에 더해 적는다
        self.assertEqual(d['write_tools'], setup.WRITE_DEFAULT + ['mcp__hub'])
        self.assertFalse(setup.add_mcp_tool(cfg))                            # 두 번째는 그대로

    def test_register_without_claude(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):                              # 콘솔 인코딩과 상관없이
            self.assertEqual(setup.mcp_register(which=lambda _n: None), 1)
        self.assertIn('claude', out.getvalue())


if __name__ == '__main__':
    unittest.main()
