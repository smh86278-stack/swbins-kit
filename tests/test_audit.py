# -*- coding: utf-8 -*-
"""변경 이력(kit.audit · save_config · 허브 켜고 끄기) — 허브를 띄우지 않고, 진짜 설정 파일을 건드리지 않는다."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
import kit  # noqa: E402
import macrohub  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, val in (('DATA', os.path.join(self.tmp, 'data')), ('F_CONFIG', os.path.join(self.tmp, 'config.local.json'))):
            self.addCleanup(setattr, kit, name, getattr(kit, name))
            setattr(kit, name, val)


class KitAudit(Base):
    def test_config_changes_names_only(self):
        a = {'_설명': 'x', 'mail': {'user': 'me@example.com', 'password_enc': 'OLD'}, 'monitors': [1], 'tidy': []}
        b = {'_설명': 'y', 'mail': {'user': 'me@example.com', 'password_enc': 'NEW'}, 'monitors': [1, 2], 'jira': {}}
        self.assertEqual(kit.config_changes(a, b), 'jira(새로) · mail(password_enc) · monitors · tidy(지움)')
        self.assertEqual(kit.config_changes(a, dict(a)), '')

    def test_save_config_logs_without_values(self):
        kit.save_config({'mail': {'password_enc': 'SECRET-OLD'}})
        kit.save_config({'mail': {'password_enc': 'SECRET-NEW'}}, via='setup_gui.py')
        kit.save_config({'mail': {'password_enc': 'SECRET-NEW'}})              # 그대로 — 안 남긴다
        items = kit.audit_tail()
        self.assertEqual([(i['action'], i['detail'], ) for i in items][0], ('설정 바꿈', 'mail(password_enc)'))
        self.assertEqual(items[0]['via'], 'setup_gui.py')
        self.assertEqual(len(items), 2)
        with open(kit.audit_path(), encoding='utf-8') as f:
            self.assertNotIn('SECRET', f.read())

    def test_rotation(self):
        with mock.patch.object(kit, 'AUDIT_MAX', 200):
            for i in range(6):
                kit.audit('지금 실행', 'job_x', 'n%d' % i)
        self.assertTrue(os.path.exists(kit.audit_path().replace('.jsonl', '.1.jsonl')))
        self.assertEqual([i['detail'] for i in kit.audit_tail(4)], ['n5', 'n4', 'n3', 'n2'])


class HubAudit(Base):
    def setUp(self):
        super().setUp()
        svc = {'id': 'svc_x', 'name': '서비스 X', 'service': True, 'triggers': [], 'owns': None}
        job = {'id': 'job_y', 'name': '작업 Y', 'service': False, 'triggers': [{'type': 'schedule', 'every': '1h'}]}
        macros = {m['id']: m for m in (svc, job)}
        for name, val in (('save_state', lambda: None), ('broadcast', lambda msg: None), ('find_macro', macros.get),
                          ('running_run', lambda mid: None), ('stop_owned', lambda m: [])):
            self.addCleanup(setattr, macrohub, name, getattr(macrohub, name))
            setattr(macrohub, name, val)
        self.addCleanup(macrohub.state.__setitem__, 'enabled', dict(macrohub.state.get('enabled') or {}))
        macrohub.state['enabled'] = {}
        macrohub.set_via(None)

    def test_enable_restart_run(self):
        macrohub.set_via('트레이')
        macrohub.set_enabled('svc_x', True)
        macrohub.set_enabled('svc_x', True)
        macrohub.set_via('화면 /ops')
        macrohub.service_action('svc_x', 'restart')
        with mock.patch.object(macrohub, 'run_macro', return_value=(object(), None)):
            macrohub.service_action('job_y', 'run')
        got = [(i['action'], i['via'], i['name']) for i in kit.audit_tail()]
        self.assertEqual(got, [('지금 실행', '화면 /ops', '작업 Y'), ('다시 띄움', '화면 /ops', '서비스 X'),
                               ('켬 (상시 서비스)', '트레이', '서비스 X')])

    def test_sched_text(self):
        self.assertEqual(macrohub.sched_text([{'type': 'schedule', 'at': '09:30', 'days': 'mon-fri'},
                                              {'type': 'schedule', 'every': '1h'}]), '09:30 mon-fri · 매 1h')


class JobAudit(unittest.TestCase):
    """지시 실행 기록 — 게이트웨이 audit_jobs 가 끝난 잡을 한 줄씩 덧붙이고(한 번만), /ops 가 읽어 CSV 로 내보낸다."""

    def setUp(self):
        import importlib.util
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        spec = importlib.util.spec_from_file_location('mail_gateway_audit', os.path.join(HUB, '..', '..', 'mail-gateway.py'))
        self.mg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mg)
        self.mg.JOBS = os.path.join(self.tmp, 'jobs')
        os.makedirs(self.mg.JOBS)
        self.mg.JOB_AUDIT_PATH = os.path.join(self.tmp, 'job-audit.jsonl')
        self.mg.AUDITED_PATH = os.path.join(self.tmp, 'audited.json')
        self.cfg = {'allowed_senders': ['me@company.test'], 'keyed_senders': {'me@gmail.test': 'word'}}

    def job(self, jid, **kw):
        j = dict({'id': jid, 'status': 'done', 'source': 'mail', 'mail_from': 'me@company.test', 'workdir': r'C:\w',
                  'workdir_label': 'work', 'mode': 'write', 'prompt': '로그인 오류\n고쳐 줘', 'allowed_tools': ['Read', 'Edit'],
                  'denials': [{'tool_name': 'Bash'}], 'cost_usd': 0.12, 'duration_ms': 45300,
                  'created_at': '2026-10-14 09:00:00', 'finished_at': '2026-10-14 09:01:00'}, **kw)
        self.mg.write_json(os.path.join(self.mg.JOBS, jid + '.json'), j)

    def test_rows_once_and_csv(self):
        import ops
        self.job('20261014-090000-aaaa')
        self.job('20261014-090100-bbbb', mail_from='me@gmail.test', status='error', error='정책', policy_denied=True)
        self.job('20261014-090200-cccc', source='jira-mail', mail_from=None, jira_key='PROJ-1', status='running')
        self.assertEqual(self.mg.audit_jobs(self.cfg), 2)                  # 돌고 있는 잡은 아직
        self.assertEqual(self.mg.audit_jobs(self.cfg), 0)                  # 한 번만
        self.job('20261014-090200-cccc', source='jira-mail', mail_from=None, jira_key='PROJ-1')
        self.assertEqual(self.mg.audit_jobs(self.cfg), 1)
        rows = ops.job_audit(10, path=self.mg.JOB_AUDIT_PATH)
        self.assertEqual([r['via'] for r in rows], ['auto', 'phone', 'company'])   # 새것 먼저
        first = rows[-1]
        self.assertEqual((first['prompt'], first['denied'], first['duration_s']), ('로그인 오류 고쳐 줘', ['Bash'], 45.3))
        self.assertTrue(rows[1]['policy_denied'])
        self.assertEqual(len(ops.job_audit(10, 'proj-1', path=self.mg.JOB_AUDIT_PATH)), 1)   # 찾기
        csv_text = ops.job_audit_csv(path=self.mg.JOB_AUDIT_PATH).decode('utf-8')
        self.assertTrue(csv_text.startswith('\ufeff끝난 시각,'))            # 엑셀이 한글을 바로 읽게 BOM
        self.assertIn('Read Edit', csv_text)
        self.assertEqual(len(csv_text.strip().splitlines()), 4)              # 머리 + 3건


if __name__ == '__main__':
    unittest.main()
