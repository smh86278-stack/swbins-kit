# -*- coding: utf-8 -*-
"""🔗 메일로 일 순서 부르기 — mail-gateway.py 의 '#c 일 순서 <이름>' (2026-10-26). 허브·IMAP 없이 가짜로 돈다."""
import importlib.util
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("mail_gateway_chain_kit", os.path.join(ROOT, "mail-gateway.py"))
mg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mg)
mg.LOG_PATH = os.path.join(tempfile.gettempdir(), "mail-gateway-test.log")

CFG = {"tags": ["#c", "c"], "tag": "#c", "write_tags": ["#cw", "cw"], "default_workdir": r"C:\default",
       "workdir_keys": {}, "max_prompt_chars": 4000, "user": "me@daou.co.kr"}
CHAINS = [{"id": "local/a", "name": "아침 업무", "kind": "chain"}, {"id": "local/b", "name": "저녁 정리", "kind": "chain"},
          {"id": "local/c", "name": "아침 메일", "kind": "chain"}, {"id": "local/x", "name": "그냥 자동화", "kind": "ctx"}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for attr, val in (("JOBS", self.tmp), ("next_thread_no", lambda: 7)):
            p = mock.patch.object(mg, attr, val)
            p.start()
            self.addCleanup(p.stop)
        self.posts = []
        self.runs = {}

    def fake_get(self, cfg, path, timeout=5):
        if path == "/api/macros":
            return CHAINS
        if path.startswith("/api/run?id="):
            rid = path.split("=", 1)[1]
            if rid not in self.runs:
                raise urllib.error.HTTPError(path, 404, "no", {}, None)
            return self.runs[rid]
        raise AssertionError(path)

    def fake_post(self, cfg, path, body, timeout=10):
        self.posts.append((path, body))
        return {"run": 555} if path == "/api/run" else {"ok": True}

    def hub(self):
        return mock.patch.multiple(mg, hub_get=self.fake_get, hub_post=self.fake_post)


class Parse(unittest.TestCase):
    def test_command(self):
        self.assertEqual(mg.hub_chain_command("#c 일 순서 아침 업무", CFG), "아침 업무")
        self.assertEqual(mg.hub_chain_command("#cw 일순서 저녁", CFG), "저녁")
        self.assertEqual(mg.hub_chain_command("#c 일 순서", CFG), "")                 # 목록
        self.assertIsNone(mg.hub_chain_command("#c 일 순서를 만들어줘", CFG))         # 일 순서 이야기 — 평소 지시
        self.assertIsNone(mg.hub_chain_command("#c 오늘 일 순서 아침", CFG))
        self.assertIsNone(mg.hub_chain_command("안녕", CFG))

    def test_pick_chain(self):
        chains = [c for c in CHAINS if c["kind"] == "chain"]
        self.assertEqual(mg.pick_chain(chains, "저녁 정리")[0]["id"], "local/b")
        self.assertEqual(mg.pick_chain(chains, "저녁")[0]["id"], "local/b")        # 들어간 것이 하나뿐
        self.assertIn("여러 개", mg.pick_chain(chains, "아침")[1])
        self.assertIn("지금 있는 일 순서: 아침 업무 · 저녁 정리 · 아침 메일", mg.pick_chain(chains, "점심")[1])

    def test_answer(self):
        for t, want in (("1", "yes"), ("계속", "yes"), ("2", "no"), ("멈춤", "no"), ("> 인용\n\n계속.", "yes"), ("글쎄", None), ("", None)):
            with self.subTest(t=t):
                self.assertEqual(mg.parse_hub_answer(t), want)


class Start(Base):
    def test_starts_hubrun_job(self):
        with self.hub():
            job = mg.start_hub_chain("아침 업무", "<m1@x>", "#c 일 순서 아침 업무", "me@daou.co.kr", CFG)
        self.assertEqual(job["status"], "hubrun")
        self.assertEqual((job["hub_run"], job["hub_chain"], job["hub_name"]), (555, "local/a", "아침 업무"))
        self.assertEqual(self.posts, [("/api/run", {"id": "local/a"})])
        self.assertEqual(mg.read_json(os.path.join(self.tmp, job["id"] + ".json"))["status"], "hubrun")

    def test_list_missing_and_hub_down(self):
        with self.hub():
            listed = mg.start_hub_chain("", "<m2@x>", "#c 일 순서", "me@daou.co.kr", CFG)
            missing = mg.start_hub_chain("점심", "<m3@x>", "#c 일 순서 점심", "me@daou.co.kr", CFG)
        self.assertEqual(listed["status"], "done")
        self.assertIn("아침 업무 · 저녁 정리 · 아침 메일", listed["result"])
        self.assertNotIn("그냥 자동화", listed["result"])                          # 일 순서만
        self.assertEqual(missing["status"], "error")
        self.assertIn("「점심」 일 순서가 없습니다", missing["error"])
        self.assertEqual(self.posts, [])
        with mock.patch.object(mg, "hub_get", mock.Mock(side_effect=OSError("refused"))):
            down = mg.start_hub_chain("아침 업무", "<m4@x>", "#c 일 순서 아침 업무", "me@daou.co.kr", CFG)
        self.assertEqual(down["status"], "error")
        self.assertIn("허브(8630)가 꺼져", down["error"])


class FakeImap:
    def __init__(self):
        self.appended = []

    def append(self, box, flags, date, raw):
        self.appended.append(raw)

    def logout(self):
        pass


class Pump(Base):
    def start(self):
        with self.hub():
            return mg.start_hub_chain("아침 업무", "<m1@x>", "#c 일 순서 아침 업무", "me@daou.co.kr", CFG)

    def pump(self, imap):
        with self.hub(), mock.patch.object(mg, "imap_connect", lambda cfg, pw: imap):
            return mg.pump_hub_runs(CFG, "pw")

    def job(self, j):
        return mg.read_json(os.path.join(self.tmp, j["id"] + ".json"))

    def test_confirm_mail_once_then_answer_then_result(self):
        j = self.start()
        imap = FakeImap()
        self.runs["555"] = {"status": "running", "confirm": None, "lines": []}
        self.assertEqual(self.pump(imap), 0)
        self.runs["555"]["confirm"] = {"name": "분류 담당", "text": "- 급함: 로그인 안 됨"}
        self.assertEqual(self.pump(imap), 1)
        self.assertEqual(self.pump(imap), 0)                                          # 같은 확인은 한 번만
        raw = imap.appended[0].decode("utf-8", "replace")
        self.assertIn("X-Dispatch-Kind: confirm", raw)
        cur = self.job(j)
        self.assertTrue(cur["hub_wait"])
        self.assertEqual(cur["thread"], 7)
        # 자기 확인 메일(INBOX 에 append)을 다음 폴링에서 새 지시로 받지 않게 — 2026-10-26 실전에서 그렇게 받았다
        self.assertIn(cur["hub_confirm_msgid"], mg.load_own_reply_ids())
        # 그 확인 메일에 대한 답장으로 찾고, 계속을 허브에 전한다
        head = {"In-Reply-To": cur["hub_confirm_msgid"]}
        path, found = mg.find_hub_run(head, None, None)
        self.assertEqual(found["id"], j["id"])
        self.assertEqual(mg.find_hub_run({}, 7, None)[1]["id"], j["id"])            # 대화 번호로도
        self.assertIsNone(mg.find_hub_run({}, 7, lambda _j: False))                  # 믿을 수 없는 대화면 아님
        with self.hub():
            self.assertIn("계속", mg.hub_answer(CFG, path, found, True))
        self.assertEqual(self.posts[-1], ("/api/chain/confirm", {"run": 555, "ok": True}))
        self.assertFalse(self.job(j)["hub_wait"])
        # 단계마다 확인 — 다음 확인은 다시 메일
        self.runs["555"]["confirm"] = {"name": "둘째", "text": "다음"}
        self.assertEqual(self.pump(imap), 1)
        # 끝 — 결과를 잡에 적어 send_replies 가 회신하게
        self.runs["555"] = {"status": "ok", "confirm": None,
                            "lines": ["▶ 아침 업무 시작", "@@step {}", "🔗 일 순서 결과: 3개 중 성공 3 · 실패 0"]}
        self.pump(imap)
        cur = self.job(j)
        self.assertEqual(cur["status"], "done")
        self.assertIn("🔗 일 순서 「아침 업무」 — 끝까지 돌았습니다", cur["result"])
        self.assertNotIn("@@step", cur["result"])
        self.assertIsNone(mg.find_hub_run(head, None, None))                          # 끝난 일은 답을 받지 않는다

    def test_stop_while_running_and_failures(self):
        j = self.start()
        self.runs["555"] = {"status": "running", "confirm": None, "lines": []}
        with self.hub():
            mg.hub_answer(CFG, os.path.join(self.tmp, j["id"] + ".json"), j, False)
        self.assertEqual(self.posts[-1], ("/api/stop", {"run": 555}))               # 확인 대기가 아니면 멈춤 = 중지
        self.runs["555"] = {"status": "fail", "lines": ["✖ [2/3] 실패"]}
        self.pump(FakeImap())
        cur = self.job(j)
        self.assertEqual(cur["status"], "error")
        self.assertIn("실패했습니다", cur["error"])
        j2 = self.start()
        self.runs.clear()                                                            # 허브가 다시 떠서 실행 기록이 없다
        self.pump(FakeImap())
        self.assertIn("결과를 알 수 없습니다", self.job(j2)["error"])


if __name__ == "__main__":
    unittest.main()
