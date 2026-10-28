# -*- coding: utf-8 -*-
"""명령 안전장치 훅(bash-guard.js) — node 로 진짜 훅을 돌려 본다. node 가 없으면 건너뛴다.

    python -m unittest tests.test_bash_guard
"""
import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "dispatch-chat")
GUARD = os.path.join(HERE, "bash-guard.js")
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node 가 없다")
class BashGuard(unittest.TestCase):
    def run_guard(self, payload):
        p = subprocess.run([NODE, GUARD], input=payload, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout.decode("utf-8").strip()
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"

    def cmd(self, c):
        return self.run_guard(json.dumps({"tool_name": "Bash", "tool_input": {"command": c}}).encode("utf-8"))

    def test_read_commands_pass(self):
        for c in ("git log -5 --oneline", "rtk git status", "git diff HEAD~1", "git show abc123 --stat",
                  "git --no-pager log -3", "git log --format=%H -n 3", "git show HEAD:README.md"):
            self.assertEqual(self.cmd(c), "allow", c)

    def test_write_or_exec_blocked(self):
        """2026-10-19 보안 점검 — git log --output 으로 .git/config 를 써서 fsmonitor 명령을 돌릴 수 있었다."""
        for c in ("git log -1 --format=x --output=.git/config", "git -c core.fsmonitor=calc status",
                  "git diff --no-index a b", "git diff --ext-diff", "git log --textconv", "git -C ../other log",
                  "git log && del x", "git log > out.txt", "git log $(whoami)", "git status; calc", "git log | tee x",
                  "git log\ncalc"):
            self.assertEqual(self.cmd(c), "deny", c)

    def tool(self, name, **inp):
        return self.run_guard(json.dumps({"tool_name": name, "tool_input": inp}).encode("utf-8"))

    def test_plain_reads_pass(self):
        for p in (r"C:\work\README.md", r"C:\work\services.json", "src/app.py",
                  r"C:\work\tools\ca-bundle.pem", r"C:\Users\me\Downloads\report.xlsx"):
            self.assertEqual(self.tool("Read", file_path=p), "allow", p)
        self.assertEqual(self.tool("Grep", pattern="TODO", path=r"C:\work\tools"), "allow")
        self.assertEqual(self.tool("Glob", pattern="**/*.py"), "allow")

    def test_secret_reads_blocked(self):
        """2026-10-28 — 10-19 점검의 남은 낮은 항목: Read 에 경로 제한이 없어 비밀 파일을 읽어 답장에 실을 수 있었다."""
        for p in (r"C:\work\inbox\mail.local.json", r"C:\work\.keys\app.local.key",
                  r"C:\Users\me\.ssh\id_ed25519", r"C:\Users\me\.claude\.credentials.json",
                  r"C:\Users\me\AppData\Local\Google\Chrome\User Data\Default\Login Data",
                  r"C:\Users\me\AppData\Local\DnC\pw-profile\Profile 1\Cookies",
                  r"C:\work\data.local\otp\creds.json",
                  r"C:\work\tools\macro-hub\secrets.local.json", "/Users/me/.aws/credentials", ".env"):
            self.assertEqual(self.tool("Read", file_path=p), "deny", p)
        self.assertEqual(self.tool("Grep", pattern="password", path=r"C:\Users\me\.ssh"), "deny")
        self.assertEqual(self.tool("Glob", pattern=r"C:/Users/me/.ssh/*"), "deny")

    def test_too_wide_search_blocked(self):
        for p in ("C:\\", r"C:\Users\me", r"C:\Users\me\AppData\Roaming", "/Users/me"):
            self.assertEqual(self.tool("Grep", pattern="password", path=p), "deny", p)
        self.assertEqual(self.tool("Glob", pattern=r"C:\Users\me\**\*.json"), "deny")

    def test_other_tools_and_broken_input(self):
        self.assertEqual(self.run_guard(json.dumps({"tool_name": "Read", "tool_input": {}}).encode()), "allow")
        self.assertEqual(self.run_guard(b"not json"), "deny")          # fail-closed
        self.assertEqual(self.run_guard(b"null"), "deny")


if __name__ == "__main__":
    unittest.main()
