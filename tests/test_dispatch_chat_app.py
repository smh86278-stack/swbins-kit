# -*- coding: utf-8 -*-
"""tools/dispatch-chat/chat.py(디스패치 대화 앱) 시험 — 메일 서버·게이트웨이 없이 돈다.  python -X utf8 -m unittest tests.test_dispatch_chat_app

진행 상황 카드: 워커가 돌리는 작업의 Claude 세션 기록(~/.claude/projects/<작업 폴더>/<세션>.jsonl)을 찾아 단계로 푸는지 본다.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "dispatch-chat"))
import chat  # noqa: E402
import chat_runner as runner  # noqa: E402


def ev(typ, content, ts="2026-10-12T01:00:10.000Z", **kw):
    return json.dumps(dict({"type": typ, "isSidechain": False, "timestamp": ts, "message": {"content": content}}, **kw),
                      ensure_ascii=False)


SINCE = chat._ts("2026-10-12T01:00:00.000Z")
LINES = [
    ev("user", "지난번 지시", ts="2026-10-11T09:00:00.000Z"),                       # 이어받은 세션의 지난 대화 — 빼야 한다
    ev("assistant", [{"type": "tool_use", "id": "old", "name": "Bash", "input": {"command": "ls"}}], ts="2026-10-11T09:00:01.000Z"),
    ev("user", "로그인 오류 고쳐 줘\n"),
    ev("assistant", [{"type": "text", "text": "살펴보겠습니다"},
                     {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status", "description": "작업 트리 보기"}}]),
    ev("assistant", [{"type": "tool_use", "id": "t2", "name": "Read", "input": {}}], isSidechain=True),   # 하위 에이전트 안쪽
    ev("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
    ev("assistant", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "C:/a.py"}}]),
    ev("user", [{"type": "tool_result", "tool_use_id": "t3", "is_error": True, "content": "x"}]),
    ev("assistant", [{"type": "tool_use", "id": "t4", "name": "TodoWrite", "input": {"todos": [
        {"content": "a", "status": "completed"}, {"content": "b", "activeForm": "b 하는 중", "status": "in_progress"}]}}]),
    '{"type":"assis',                                                                  # 아직 다 안 쓰인 줄
]


class Progress(unittest.TestCase):
    def test_steps(self):
        steps = chat.parse_progress(LINES, SINCE)
        self.assertEqual([(x["kind"], x.get("name"), x["text"], x.get("state")) for x in steps], [
            ("text", None, "살펴보겠습니다", None),
            ("tool", "Bash", "작업 트리 보기", "ok"),
            ("tool", "Edit", "C:/a.py", "err"),
            ("tool", "TodoWrite", "할 일 1/2 — b 하는 중", "run"),
        ])
        self.assertEqual(steps[1]["detail"], "command: git status\ndescription: 작업 트리 보기")   # 자세히: 넘긴 입력 전부
        self.assertEqual(steps[1]["result"], "ok")
        self.assertEqual(steps[2]["result"], "x")
        self.assertEqual(steps[3]["detail"], "✓ a\n▶ b")

    def test_detail_edit_and_clip(self):
        self.assertEqual(chat.tool_detail("Edit", {"file_path": "a.py", "old_string": "x = 1", "new_string": "x = 2\ny = 3"}),
                         "a.py\n- x = 1\n+ x = 2\n+ y = 3")
        self.assertEqual(chat.tool_detail("Bash", {"command": "ls"}), "ls")
        long = "가" * 2500
        self.assertTrue(chat.result_text([{"type": "text", "text": long}]).endswith("… (500자 더)"))

    def test_first_instruction_follows_its_job(self):
        """게이트웨이는 번호를 회신할 때 붙인다 — 번호가 없는 동안에도 접수된 작업(mail_msgid)으로 '작업 중' 과 작업 id 가 붙어야 진행 카드가 뜬다."""
        m = {"id": "<m1@x>", "thread": None, "ts": 1.0, "bot": False, "mode": "read", "tag": "#c", "text": "일 해 줘", "rest": "", "refs": []}
        t = chat.build_threads([dict(m)])[0]
        self.assertEqual((t["key"], t["status"], t["job"]), ("m:<m1@x>", "sent", ""))
        t = chat.build_threads([dict(m)], {}, {"<m1@x>": {"id": "j1", "status": "running", "thread": None}})[0]
        self.assertEqual((t["key"], t["no"], t["status"], t["job"]), ("m:<m1@x>", None, "running", "j1"))
        t = chat.build_threads([dict(m)], {25: {"id": "j1", "status": "done", "thread": 25}}, {"<m1@x>": {"id": "j1", "status": "done", "thread": 25}})[0]
        self.assertEqual((t["key"], t["no"], t["status"], t["job"]), ("T25", 25, "sent", "j1"))   # 번호를 받았고, 회신 전이라 '보냄'

    def test_progress_mail_is_not_an_answer(self):
        """진행 메일(X-Dispatch-Kind: progress)은 말풍선·답이 아니다 — 완료·번호·안 읽음에 안 세고, 회색 한 줄(progress)로만. 최종 답이 오면 사라진다."""
        me = {"id": "<m1@x>", "thread": None, "ts": 1.0, "bot": False, "mode": "read", "tag": "#c", "text": "일 해 줘", "rest": "", "refs": []}
        pr = {"id": "<p1@x>", "thread": None, "ts": 200.0, "bot": True, "kind": "progress", "status": "running", "mode": "read", "tag": "#c",
              "text": "진행 중 · 3분째 — 테스트 돌리기", "foot": "", "rest": "", "refs": ["<m1@x>"], "ask": None}
        t = chat.build_threads([dict(me), dict(pr)])[0]
        self.assertEqual((t["key"], len(t["msgs"]), t["status"], t["last_bot"], t["ts"]), ("m:<m1@x>", 1, "running", False, 1.0))
        self.assertEqual(t["progress"], "진행 중 · 3분째 — 테스트 돌리기")
        rep = dict(pr, id="<r1@x>", ts=300.0, kind="reply", status="done", thread=4, text="끝")
        t = chat.build_threads([dict(me), dict(pr), rep])[0]
        self.assertEqual((t["key"], len(t["msgs"]), t["status"], t["progress"]), ("T4", 2, "done", ""))
        pr2 = dict(pr, thread=4)                                  # 이어 말한 일의 진행 메일엔 번호가 붙어 온다 — 그래도 답이 아니다
        t = chat.build_threads([dict(me), rep, dict(pr2, ts=400.0, refs=["<m2@x>"]),
                                dict(me, id="<m2@x>", ts=350.0, thread=4, text="더 해 줘")])[0]
        self.assertEqual((len(t["msgs"]), t["status"], t["progress"], t["last_bot"]), (3, "running", pr["text"], False))

    def test_closed_question_leaves_waiting(self):
        """답 기한이 지나 닫힌 질문(kind 'closed', 선택지 없음)이 오면 '답할 것' 에서 빠진다."""
        me = {"id": "<m1@x>", "thread": 4, "ts": 1.0, "bot": False, "mode": "read", "tag": "#c", "text": "일 해 줘", "rest": "", "refs": []}
        rep = {"id": "<r1@x>", "thread": 4, "ts": 2.0, "bot": True, "kind": "reply", "status": "done", "mode": "read", "tag": "#c",
               "text": "어느 쪽?", "foot": "", "rest": "", "refs": ["<m1@x>"], "ask": {"question": "어느 쪽?", "options": ["A", "B"]}}
        self.assertEqual(chat.build_threads([dict(me), dict(rep)])[0]["status"], "ask")
        closed = dict(rep, id="<c1@x>", ts=3.0, kind="closed", text="답을 기다리던 질문을 24시간이 지나 닫았습니다.", ask=None)
        t = chat.build_threads([dict(me), dict(rep), closed])[0]
        self.assertEqual((t["status"], t["ask"], len(t["msgs"])), ("done", None, 3))

    def test_find_transcript_by_prompt(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        d = os.path.join(tmp, "C--work-dir")
        os.makedirs(d)
        with open(os.path.join(d, "other.jsonl"), "w", encoding="utf-8") as f:     # 같은 폴더의 다른 세션(사람이 직접 쓰던 것)
            f.write(ev("user", "딴 일") + "\n")
        with open(os.path.join(d, "mine.jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(LINES) + "\n")
        old = chat.CLAUDE_PROJECTS
        chat.CLAUDE_PROJECTS = tmp
        self.addCleanup(setattr, chat, "CLAUDE_PROJECTS", old)
        job = {"id": "j1", "workdir": "C:\\work-dir", "prompt": "로그인 오류 고쳐 줘\n"}
        # 기준 시각은 기록 안의 시각(SINCE)으로 — 지금 시각으로 두면 기록이 쓰인 날이 지나면 못 찾는다
        self.assertEqual(os.path.basename(chat.find_transcript(job, SINCE)), "mine.jsonl")


if __name__ == "__main__":
    unittest.main()


class LocalMarks(unittest.TestCase):
    """🔥 급건 · 📝 저장해 두는 답 — 이 PC 의 LOCALDATA 에만 남는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("LOCALDATA", "URGENT_PATH", "SNIPPETS_PATH"):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
        chat.LOCALDATA = self.tmp
        chat.URGENT_PATH = os.path.join(self.tmp, "urgent.json")
        chat.SNIPPETS_PATH = os.path.join(self.tmp, "snippets.json")

    def test_urgent(self):
        self.assertEqual(chat.load_urgent(), set())
        chat.set_urgent("T3", True)
        chat.set_urgent("T5", True)
        chat.set_urgent("T3", False)
        self.assertEqual(chat.load_urgent(), {"T5"})
        with self.assertRaises(ValueError):
            chat.set_urgent("", True)

    def test_snippets(self):
        self.assertEqual(chat.load_snippets(), chat.DEFAULT_SNIPPETS)          # 처음엔 기본 몇 개
        got = chat.edit_snippets({"add": "로그 먼저 보여 줘"})["snippets"]
        self.assertEqual(got[0], "로그 먼저 보여 줘")
        got = chat.edit_snippets({"add": chat.DEFAULT_SNIPPETS[1]})["snippets"]  # 같은 글은 맨 앞으로 하나만
        self.assertEqual(got[0], chat.DEFAULT_SNIPPETS[1])
        self.assertEqual(got.count(chat.DEFAULT_SNIPPETS[1]), 1)
        got = chat.edit_snippets({"remove": "로그 먼저 보여 줘"})["snippets"]
        self.assertNotIn("로그 먼저 보여 줘", got)
        self.assertEqual(chat.load_snippets(), got)
        with self.assertRaises(ValueError):
            chat.edit_snippets({"add": "x" * 2001})

    def test_kit_folders_and_default(self):
        """키트 설정을 따를 때 — 기본 폴더와 같은 곳·같은 경로의 두 번째 키는 칩에서 빼고, 기본 폴더 칩에 그 이름을 붙인다."""
        for name in ("OWN_CFG", "KIT_CFG"):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
        chat.OWN_CFG = os.path.join(self.tmp, "own.json")
        chat.KIT_CFG = os.path.join(self.tmp, "config.local.json")
        chat.write_json(chat.KIT_CFG, {"mail": {"user": "me@x.test"},
                                       "dispatch": {"default_workdir": r"C:\work\main",
                                                    "workdir_keys": {"main": r"C:\work\main", "tools": r"C:\work\tools",
                                                                     "tools2": "C:\\work\\tools\\", "docs": r"C:\work\docs"}}})
        cfg, src = chat.load_cfg()
        self.assertEqual((src, cfg["workdir_keys"]), ("kit", ["tools", "docs", "hub"]))
        self.assertEqual(chat.default_folder(cfg, False), ("main", r"C:\work\main"))
        self.assertEqual(chat.default_folder(dict(cfg, run_workdir=r"D:\proj\shop"), True), ("shop", r"D:\proj\shop"))
        self.assertEqual(chat.DEFAULTS["workdir_keys"], [])                     # 코드 기본값엔 이 PC 폴더 이름이 없다

    def test_instruction_word(self):
        """지시 메일 본문 끝 [k:단어] — 앱 설정 key_word, 없으면 게이트웨이가 모든 지시에 단어를 요구할 때만 그 단어."""
        for name in ("OWN_CFG", "KIT_CFG"):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
        chat.OWN_CFG = os.path.join(self.tmp, "own.json")
        chat.KIT_CFG = os.path.join(self.tmp, "config.local.json")
        d = {"keyed_senders": {"me@x.test": "phoneword1"}}
        chat.write_json(chat.KIT_CFG, {"mail": {"user": "Me@X.test"}, "dispatch": d})
        cfg, src = chat.load_cfg()
        self.assertEqual(chat.instruction_word(cfg, src), "")                    # 요구하지 않으면 붙이지 않는다
        chat.write_json(chat.KIT_CFG, {"mail": {"user": "Me@X.test"}, "dispatch": dict(d, require_word_all=True)})
        self.assertEqual(chat.instruction_word(cfg, src), "phoneword1")
        chat.write_json(chat.KIT_CFG, {"mail": {"user": "Me@X.test"}, "dispatch": dict(d, require_word_all=True, company_word="corpword9")})
        self.assertEqual(chat.instruction_word(cfg, src), "corpword9")
        self.assertEqual(chat.instruction_word(dict(cfg, key_word="own123"), src), "own123")

    def test_save_kit_folders(self):
        """⚙ 작업 폴더 — 키트 설정의 dispatch 에 기본 폴더·키=폴더를 저장(다른 키·BOM 유지). 기본 폴더를 바꾸면 회사 모드 폴더는 옛 기본 폴더로 박는다."""
        for name in ("OWN_CFG", "KIT_CFG", "LOG_PATH"):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
        chat.OWN_CFG = os.path.join(self.tmp, "own.json")
        chat.KIT_CFG = os.path.join(self.tmp, "config.local.json")
        chat.LOG_PATH = os.path.join(self.tmp, "chat.log")
        main, web = os.path.join(self.tmp, "main"), os.path.join(self.tmp, "web")
        os.makedirs(main), os.makedirs(web)
        with open(chat.KIT_CFG, "wb") as f:
            f.write(b"\xef\xbb\xbf" + json.dumps({"mail": {"user": "me@x.test"}, "monitors": [1],
                                                   "dispatch": {"enabled": True, "default_workdir": main, "workdir_keys": {"main": main}}}).encode())
        self.assertEqual(chat.folders_info()["workdir"], main)
        r = chat.save_gateway_folders({"workdir": main, "dirs": "main=%s\nweb=%s" % (main, web)})
        self.assertEqual((r["dirs"].splitlines(), r["note"]), (["main=" + main, "web=" + web], ""))
        with open(chat.KIT_CFG, "rb") as f:
            self.assertTrue(f.read().startswith(b"\xef\xbb\xbf"))
        r = chat.save_gateway_folders({"workdir": web, "dirs": "main=" + main})
        self.assertIn("회사 모드", r["note"])
        full = chat.read_json(chat.KIT_CFG)
        d = full["dispatch"]
        self.assertEqual((d["default_workdir"], d["company_workdirs"], d["enabled"]), (web, [main], True))
        self.assertEqual((full["mail"]["user"], full["monitors"]), ("me@x.test", [1]))
        with self.assertRaises(ValueError):
            chat.save_gateway_folders({"workdir": os.path.join(self.tmp, "없는폴더"), "dirs": ""})
        with self.assertRaises(ValueError):
            chat.save_gateway_folders({"workdir": main, "dirs": "잘못된 줄"})
        # %USERPROFILE%·~ 로 적은 폴더 — 풀어서 있는지 보고, 저장은 적힌 그대로(키트 게이트웨이가 kit.expand 로 푼다)
        with mock.patch.dict(os.environ, {"KITTEST_HOME": self.tmp}):
            r = chat.save_gateway_folders({"workdir": "%KITTEST_HOME%\\main", "dirs": "web=%KITTEST_HOME%\\web"})
            d = chat.read_json(chat.KIT_CFG)["dispatch"]
            self.assertEqual((d["default_workdir"], d["workdir_keys"]), ("%KITTEST_HOME%\\main", {"web": "%KITTEST_HOME%\\web"}))
            self.assertEqual(r["workdir"], main)                              # 화면엔 푼 경로

    def test_issue_key_with_underscore(self):
        """직접 실행도 입력칸·키트 게이트웨이와 같은 이슈 키 모양(밑줄 · 한 글자 프로젝트)을 이슈 지시로 알아본다."""
        self.assertEqual(runner.jira_key_of("/jira AB_C-7", {}), ("AB_C-7", ""))
        self.assertEqual(runner.jira_key_of("/issue X-7", {"issue_command": "/issue"}), ("X-7", ""))
        # 본문 어느 줄이든 — 나머지 말은 덧붙인 요청, 키는 대문자로. 줄 앞이 아니면 이슈 지시가 아니다
        self.assertEqual(runner.jira_key_of("봐줘\n/issue x-8 급함", {"issue_command": "/issue"}), ("X-8", "봐줘\n급함"))
        self.assertIsNone(runner.jira_key_of("어제 /jira AB-1 돌린 것", {}))

    def test_clear_all(self):
        """🧹 전체 지우기 — 끝난 대화만 목록에서 빠지고, 일하는 중인 대화는 남고, 새 글이 오면 다시 보이고, 되돌릴 수 있다."""
        for name in ("CLEARED_PATH", "HIDDEN_PATH", "LOG_PATH", "local_jobs"):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
        chat.CLEARED_PATH = os.path.join(self.tmp, "cleared.json")
        chat.HIDDEN_PATH = os.path.join(self.tmp, "hidden.json")
        chat.LOG_PATH = os.path.join(self.tmp, "chat.log")
        chat.local_jobs = lambda: ({}, {})
        old_msgs, old_echo = chat.BOX.msgs, chat.BOX.echo
        self.addCleanup(setattr, chat.BOX, "msgs", old_msgs)
        self.addCleanup(setattr, chat.BOX, "echo", old_echo)
        now = time.time()
        me = {"thread": None, "bot": False, "mode": "read", "tag": "#c", "rest": "", "refs": []}
        done_q = dict(me, id="<a@x>", ts=now - 100, text="끝난 일")
        done_a = {"id": "<b@x>", "thread": 1, "ts": now - 90, "bot": True, "kind": "reply", "status": "done", "mode": "read", "tag": "#c",
                  "text": "끝", "foot": "", "rest": "", "refs": ["<a@x>"], "ask": None}
        waiting = dict(me, id="<c@x>", ts=now - 80, text="아직 안 끝난 일")           # 답이 아직 없다 — 'sent' 라 남는다
        chat.BOX.msgs = {m["id"]: m for m in (done_q, done_a, waiting)}
        chat.BOX.echo = []
        self.assertEqual(len(chat.BOX.threads()), 2)
        self.assertEqual(chat.clear_threads()["left"], 1)
        self.assertEqual([t["key"] for t in chat.BOX.threads()], ["m:<c@x>"])
        more = dict(me, id="<d@x>", thread=1, ts=time.time() + 5, text="이어서 더 해 줘")   # 지운 대화에 새 글 — 다시 보인다
        chat.BOX.msgs[more["id"]] = more
        self.assertEqual(sorted(t["key"] for t in chat.BOX.threads()), ["T1", "m:<c@x>"])
        del chat.BOX.msgs[more["id"]]
        chat.clear_threads(undo=True)
        self.assertEqual(len(chat.BOX.threads()), 2)
