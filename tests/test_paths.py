# -*- coding: utf-8 -*-
"""설정·코드가 가정하는 경로가 실제로 있는지.

폴더 이름을 바꿀 때 코드 기본값만 고치고 config.local.json 을 놓치면, 로컬 값이 기본값을 덮어써서
기능이 "폴더가 없습니다"로 조용히 실패한다. JSON 안 경로의 '\\t' 가 탭으로 들어가는 실수도 이 검사가 잡는다.

    python -m unittest discover -s tests
"""
import json
import os
import sys
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')


def load(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8-sig') as f:
        return json.load(f)


def expand(p):
    return os.path.normpath(os.path.expanduser(os.path.expandvars(str(p))))


class ConfigExample(unittest.TestCase):
    """config.example.json — setup.py 가 config.local.json 으로 복사하는 견본."""

    def test_parses_and_has_sections(self):
        cfg = load('config.example.json')
        for key in ('company', 'mail', 'links', 'scheduled_mails', 'monitors', 'backups', 'pc_watch', 'tidy'):
            with self.subTest(key):
                self.assertIn(key, cfg)

    def test_no_real_password(self):
        self.assertEqual(load('config.example.json')['mail'].get('password_enc'), '')

    def test_links_shape(self):
        for x in load('config.example.json').get('links') or []:
            with self.subTest(x):
                self.assertTrue(x.get('label'))
                self.assertTrue(str(x.get('url', '')).startswith(('http://', 'https://')))


class ServicesJson(unittest.TestCase):
    """services.json(선택) — 매크로 허브 트레이가 읽는 서버·도구 목록. 없으면 건너뛴다."""

    def setUp(self):
        if not os.path.isfile(os.path.join(ROOT, 'services.json')):
            self.skipTest('services.json 이 없음(선택 파일)')

    def test_dirs_and_start_files_exist(self):
        cfg = load('services.json')
        for item in (cfg.get('services') or []) + (cfg.get('watchers') or []):
            with self.subTest(item.get('key')):
                if item.get('dir'):
                    self.assertTrue(os.path.isdir(item['dir']), item['dir'])
                if item.get('start'):
                    self.assertTrue(os.path.isfile(item['start']), item['start'])
                for c in item.get('commands') or []:
                    f = c['file'] if os.path.isabs(c['file']) else os.path.join(item['dir'], c['file'])
                    self.assertTrue(os.path.isfile(f), f)

    def test_hub_ids_are_real_macros(self):
        cfg = load('services.json')
        for item in (cfg.get('services') or []) + (cfg.get('watchers') or []):
            if item.get('hub'):
                with self.subTest(item.get('key')):
                    self.assertTrue(os.path.isfile(os.path.join(HUB, 'macros', item['hub'] + '.py')), item['hub'])


class CodeAssumedPaths(unittest.TestCase):
    def test_paths(self):
        for label, rel in [
            ('설정 견본(kit.F_EXAMPLE · setup.py)', 'config.example.json'),
            ('처음 설정 마법사', 'setup.py'),
            ('키트 공통 바탕', 'tools/macro-hub/kit.py'),
            ('프로세스 스냅샷(macrohub · runner · extsvc 가 불러 씀)', 'tools/proc-live/proc-live.py'),
            ('운영 화면', 'tools/macro-hub/web/ops.html'),
        ]:
            with self.subTest(label):
                self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)


class LocalConfigPaths(unittest.TestCase):
    """이 PC 의 config.local.json(gitignore)이 가리키는 폴더. 파일이 없는 PC 에서는 건너뛴다."""

    def setUp(self):
        if not os.path.isfile(os.path.join(ROOT, 'config.local.json')):
            self.skipTest('config.local.json 이 이 PC 에 없음')
        self.cfg = load('config.local.json')

    def test_dispatch_workdirs(self):
        d = self.cfg.get('dispatch') or {}
        if not d.get('enabled'):
            self.skipTest('디스패치 꺼짐')
        paths = {'workdir_keys.' + k: v for k, v in (d.get('workdir_keys') or {}).items()}
        if d.get('default_workdir'):
            paths['default_workdir'] = d['default_workdir']
        for name, p in paths.items():
            with self.subTest(name):
                self.assertTrue(os.path.isdir(expand(p)), p)

    def test_no_tab_in_paths(self):
        # JSON 에 "C:\temp" 처럼 \t 를 그대로 쓰면 탭이 된다
        def walk(v, where):
            if isinstance(v, dict):
                for k, x in v.items():
                    walk(x, where + '.' + str(k))
            elif isinstance(v, list):
                for i, x in enumerate(v):
                    walk(x, '%s[%d]' % (where, i))
            elif isinstance(v, str):
                self.assertNotIn('\t', v, where)
        walk(self.cfg, 'config')


class HubServiceMacros(unittest.TestCase):
    """macros\\svc_* — extsvc 로 지키는 상주형은 owns 가 있어야 끄고 넘겨받을 수 있다."""

    def test_svc_macros_have_owns(self):
        sys.path.insert(0, HUB)
        try:
            import runner
        finally:
            sys.path.remove(HUB)
        d = os.path.join(HUB, 'macros')
        files = [f for f in os.listdir(d) if f.startswith('svc_') and f.endswith('.py')]
        if not files:
            self.skipTest('svc_* 매크로가 없음')
        for f in files:
            with self.subTest(f):
                meta = runner.read_meta(os.path.join(d, f))
                self.assertTrue(meta.get('service'), f)
                self.assertTrue(meta.get('owns'), f)


if __name__ == '__main__':
    unittest.main()
