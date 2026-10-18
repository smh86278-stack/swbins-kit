# -*- coding: utf-8 -*-
"""브라우저 안전장치 훅(browser-guard.js) — node 로 진짜 훅을 돌려 본다. node 가 없으면 건너뛴다.

    python -m unittest tests.test_browser_guard
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "dispatch-chat")
GUARD = os.path.join(HERE, "browser-guard.js")
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node 가 없다")
class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        self.session = "guard-test-" + os.path.basename(self.tmp)
        self.addCleanup(lambda: os.path.exists(self.state()) and os.remove(self.state()))
        self.human("메일함에서 어제 온 메일 정리해 줘")

    def state(self):
        return os.path.join(tempfile.gettempdir(), "dnc-guard", self.session.replace(".", "_") + ".json")

    def human(self, text, uuid=None):
        """세션 기록에 사람 글 한 줄(+ 도구 결과 한 줄 — 건너뛰어야 한다)."""
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "uuid": uuid or text, "message": {"role": "user", "content": text}},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"type": "user", "uuid": "r-" + text, "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "진행해도 됩니다"}]}}, ensure_ascii=False) + "\n")

    def run_guard(self, tool, **inp):
        d = {"tool_name": "mcp__browser__" + tool, "tool_input": inp, "transcript_path": self.transcript,
             "session_id": self.session, "hook_event_name": "PreToolUse"}
        p = subprocess.run([NODE, GUARD], input=json.dumps(d, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout.decode("utf-8").strip()
        return json.loads(out)["hookSpecificOutput"] if out else None

    def test_blocks_irreversible_clicks_only(self):
        for el in ("보내기 버튼", "선택 메일 삭제", "결제하기", "Submit button", "등록 버튼", "삭제 링크"):
            r = self.run_guard("browser_click", element=el, ref="e1")
            self.assertEqual(r and r["permissionDecision"], "deny", el)
            self.assertIn("진행해도 됩니다", r["permissionDecisionReason"])
        for el in ("주문 조회 메뉴", "상품등록 탭", "다음 페이지", "검색 버튼", "받은편지함 목록"):
            self.assertIsNone(self.run_guard("browser_click", element=el, ref="e1"), el)

    def test_submit_enter_and_scripts(self):
        self.assertIsNone(self.run_guard("browser_type", element="검색어 입력칸", text="주문", submit=True))
        self.assertIsNotNone(self.run_guard("browser_type", element="메시지 입력칸", text="안녕", submit=True))
        self.assertIsNone(self.run_guard("browser_type", element="메시지 입력칸", text="안녕"))    # 입력만은 둔다
        self.assertIsNotNone(self.run_guard("browser_press_key", key="Enter"))
        self.assertIsNone(self.run_guard("browser_press_key", key="ArrowDown"))
        self.assertIsNotNone(self.run_guard("browser_evaluate", function="() => document.querySelector('#send').click()"))
        self.assertIsNone(self.run_guard("browser_evaluate", function="() => document.title"))
        self.assertIsNone(self.run_guard("browser_navigate", url="https://example.com/delete-guide"))

    def test_human_approval_passes_once(self):
        self.assertIsNotNone(self.run_guard("browser_click", element="보내기 버튼"))
        self.human("사용자 답(번호 선택): ☑ 1. 진행해도 됩니다", uuid="ans-1")
        self.assertIsNone(self.run_guard("browser_click", element="보내기 버튼"))       # 허락받은 동작
        self.assertIsNone(self.run_guard("browser_click", element="보내기 버튼"))       # 같은 동작 다시(빈 화면에서 실패한 뒤 등)는 된다
        self.assertIsNotNone(self.run_guard("browser_click", element="선택 메일 삭제"))  # 다른 위험 동작엔 그 허락을 쓰지 않는다
        self.human("사용자 답(번호 선택): ☑ 2. 하지 마세요", uuid="ans-2")
        self.assertIsNotNone(self.run_guard("browser_click", element="보내기 버튼"))

    def test_bad_input_does_not_block(self):
        p = subprocess.run([NODE, GUARD], input=b"not json", capture_output=True, timeout=30)
        self.assertEqual((p.returncode, p.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
