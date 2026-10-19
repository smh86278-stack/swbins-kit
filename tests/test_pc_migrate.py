# -*- coding: utf-8 -*-
"""tools/pc-migrate — 가짜 ~\\.claude · 키트 · git 저장소로 실제 묶고(pack.ps1 -NoEncrypt) 풀어(restore.ps1) 본다.

진짜 사용자 폴더·환경변수·레지스트리는 건드리지 않는다(-ClaudeDir · -ClaudeJson · -KitDir 로 임시 폴더만).
Windows PowerShell 과 git 이 없으면 건너뛴다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TOOL = os.path.join(ROOT, 'tools', 'pc-migrate')
PS = shutil.which('powershell')
GIT = shutil.which('git')


def ps(script, *args):
    r = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', os.path.join(TOOL, script), *args],
                       capture_output=True, timeout=180)
    out = (r.stdout + r.stderr).decode('utf-8', 'replace') + (r.stdout + r.stderr).decode('cp949', 'replace')
    return r.returncode, out


def git(cwd, *args):
    subprocess.run([GIT, '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args], cwd=cwd, check=True, capture_output=True)


def write(path, text=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


@unittest.skipUnless(sys.platform == 'win32' and PS and GIT, 'Windows PowerShell 과 git 이 필요')
class PcMigrate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pcmig-')
        t = self.tmp
        # 가짜 Claude Code
        self.claude = os.path.join(t, 'claude')
        write(os.path.join(self.claude, 'projects', 'C--work-app', 's1.jsonl'), '{}\n')
        write(os.path.join(self.claude, 'projects', 'C--work-app', 'memory', 'MEMORY.md'), '- x\n')
        write(os.path.join(self.claude, 'projects', 'C--Users-u-AppData-Local-Temp-x', 's2.jsonl'), '{}\n')
        write(os.path.join(self.claude, 'CLAUDE.md'), '# 지침\n')
        write(os.path.join(self.claude, '.credentials.json'), '{"secret": 1}')
        self.claude_json = os.path.join(t, 'claude.json')
        write(self.claude_json, json.dumps({'mcpServers': {'demo': {'command': 'x'}}, 'other': 1}))
        # 가짜 git 저장소
        self.repo = os.path.join(t, 'repo')
        os.makedirs(self.repo)
        git(self.repo, 'init', '-q', '-b', 'main')
        write(os.path.join(self.repo, '.gitignore'), '.env\nnode_modules/\n*.log\n')
        write(os.path.join(self.repo, 'a.txt'), 'one\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'first')
        write(os.path.join(self.repo, 'a.txt'), 'one\ntwo\n')                    # 수정분 → patch
        write(os.path.join(self.repo, 'docs', '메모.md'), '작업 메모\n')        # 새 폴더 → files
        write(os.path.join(self.repo, '.env'), 'TOKEN=abc\n')                   # 제외 파일 → files
        write(os.path.join(self.repo, 'node_modules', 'x.js'), '')              # 다시 만들 것 → 뺌
        write(os.path.join(self.repo, 'crash.log'), '')                         # 로그 → 뺌
        os.makedirs(os.path.join(self.repo, 'inner', '.git'))                   # 안에 든 저장소 → 뺌
        write(os.path.join(self.repo, 'inner', 'z.txt'), '')
        # 가짜 키트
        self.kit = os.path.join(t, 'kit')
        write(os.path.join(self.kit, 'config.local.json'), json.dumps({'migrate': {'repos': [self.repo], 'env_vars': ['PCMIG_TEST_NOT_SET']}}))
        write(os.path.join(self.kit, 'tools', 'macro-hub', 'macros.local', 'my_job.py'), 'x = 1\n')
        self.out = os.path.join(t, 'out')

    def tearDown(self):
        subprocess.run(['cmd', '/c', 'rd', '/s', '/q', self.tmp], capture_output=True)

    def pack(self, *extra):
        return ps('pack.ps1', '-NoEncrypt', '-OutDir', self.out, '-ClaudeDir', self.claude, '-ClaudeJson', self.claude_json,
                  '-KitDir', self.kit, *extra)

    def test_dry_run_makes_nothing(self):
        code, out = self.pack('-DryRun')
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.out))
        self.assertIn('C--work-app', out)
        self.assertNotIn('AppData-Local-Temp', out.split('출력')[-1] if '출력' in out else out)

    def test_pack_then_restore(self):
        code, out = self.pack()
        self.assertEqual(code, 0, out)
        o = self.out
        has = lambda *p: os.path.exists(os.path.join(o, *p))
        # Claude Code — 임시 폴더·로그인 정보는 빠진다
        self.assertTrue(has('claude', 'projects', 'C--work-app', 's1.jsonl'))
        self.assertTrue(has('claude', 'projects', 'C--work-app', 'memory', 'MEMORY.md'))
        self.assertFalse(has('claude', 'projects', 'C--Users-u-AppData-Local-Temp-x'))
        self.assertFalse(has('claude', '.credentials.json'))
        with open(os.path.join(o, 'mcpServers.json'), encoding='utf-8-sig') as f:
            self.assertEqual(list(json.load(f)), ['demo'])
        # 키트
        self.assertTrue(has('kit-local', 'config.local.json'))
        self.assertTrue(has('kit-local', 'tools', 'macro-hub', 'macros.local', 'my_job.py'))
        # 저장소 작업물
        files = os.path.join('repos', 'repo', 'files')
        self.assertTrue(has(files, 'docs', '메모.md'))
        self.assertTrue(has(files, '.env'))
        self.assertFalse(has(files, 'node_modules'))
        self.assertFalse(has(files, 'crash.log'))
        self.assertFalse(has(files, 'inner'))
        self.assertTrue(has('repos', 'repo', 'changes', '_root.patch'))
        self.assertTrue(has('repos', 'repo', 'bundles', '_root.bundle'))   # 원격이 없으니 main 이 "원격에 없는 브랜치"
        # 암호 없이 만들면 환경변수 값은 담지 않는다
        self.assertFalse(has('env-vars.txt'))
        self.assertTrue(has('restore.ps1'))

        # 수정분 patch 는 원래 저장소에 그대로 되돌려 맞는다
        r = subprocess.run([GIT, 'apply', '--check', '-R', os.path.join(o, 'repos', 'repo', 'changes', '_root.patch')],
                           cwd=self.repo, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)

        # 새 PC 흉내 — 키트 설정 하나는 이미 있다
        new_claude = os.path.join(self.tmp, 'new-claude')
        new_kit = os.path.join(self.tmp, 'new-kit')
        write(os.path.join(new_kit, 'config.local.json'), '{"new": true}')
        args = ('-Source', o, '-ClaudeDir', new_claude, '-ClaudeJson', os.path.join(self.tmp, 'nope.json'), '-KitDir', new_kit)
        code, out = ps('restore.ps1', '-DryRun', *args)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(new_claude, 'projects')))
        code, out = ps('restore.ps1', *args)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(os.path.join(new_claude, 'projects', 'C--work-app', 's1.jsonl')))
        self.assertTrue(os.path.exists(os.path.join(new_kit, 'tools', 'macro-hub', 'macros.local', 'my_job.py')))
        with open(os.path.join(new_kit, 'config.local.json'), encoding='utf-8') as f:
            self.assertEqual(f.read(), '{"new": true}')                      # 이미 있던 것은 안 덮는다
        self.assertTrue(os.path.exists(os.path.join(new_kit, 'config.local.json.imported')))
        self.assertIn('apply', out)
        self.assertIn('fetch', out)

    def test_project_map_renames(self):
        self.assertEqual(self.pack()[0], 0)
        new_claude = os.path.join(self.tmp, 'new-claude')
        code, out = ps('restore.ps1', '-Source', self.out, '-ClaudeDir', new_claude, '-KitDir', os.path.join(self.tmp, 'none'),
                       '-ClaudeJson', os.path.join(self.tmp, 'nope.json'), '-ProjectMap', 'C--work-app=D--src-app')
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(os.path.join(new_claude, 'projects', 'D--src-app', 's1.jsonl')))


if __name__ == '__main__':
    unittest.main()
