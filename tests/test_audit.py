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


if __name__ == '__main__':
    unittest.main()
