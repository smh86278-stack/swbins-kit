# -*- coding: utf-8 -*-
"""tools/dispatch-chat/chat.py — 메일을 대화로 묶는 규칙의 회귀 테스트(메일 서버 없이 돈다).

게이트웨이(mail-gateway.py)가 실제로 만드는 회신 메일을 그대로 먹여, 대화 앱이 봇 말·선택지·대화 번호를 알아보는지 본다.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from email.message import EmailMessage

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools", "dispatch-chat"))
import chat  # noqa: E402

_spec = importlib.util.spec_from_file_location("mail_gateway_for_chat", os.path.join(ROOT, "mail-gateway.py"))
mg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mg)
mg.LOG_PATH = os.path.join(tempfile.gettempdir(), "mail-gateway-test.log")

CFG = dict(chat.DEFAULTS, user="me@example.com")
GW = {"user": "me@example.com", "tags": ["#c", "c"], "write_tags": ["#cw", "cw"]}


def mail(subject, body, mid, reply_to=None, date="Tue, 06 Oct 2026 16:00:00 +0900"):
    m = EmailMessage()
    m["Subject"], m["From"], m["To"], m["Message-ID"] = subject, "me@example.com", "me@example.com", mid
    m["Date"] = date
    if reply_to:
        m["In-Reply-To"] = reply_to
    m.set_content(body)
    return m.as_bytes()


def bot(job):
    msg, _ = mg.build_reply_message(GW, job)
    msg.replace_header("Date", "Tue, 06 Oct 2026 16:05:00 +0900")
    return msg.as_bytes()


JOB = {"status": "done", "thread": 12, "workdir": "C:\\w", "mode": "read", "duration_ms": 1000, "cost_usd": 0.01,
       "session_id": "s", "mail_subject": "#c [T12] 34097 원인 봐줘", "mail_msgid": "<m1@x>",
       "result": '원인 찾음\n```choices\n{"question": "범위?", "multi": true, "options": ["주문", "클레임"]}\n```'}


class ParseMessage(unittest.TestCase):
    def test_bot_reply_from_gateway(self):
        m = chat.parse_message(bot(JOB), CFG)
        self.assertTrue(m["bot"])
        self.assertEqual(m["thread"], 12)
        self.assertEqual(m["ask"], {"question": "범위?", "multi": True, "options": ["주문", "클레임"]})
        self.assertEqual(m["text"], "원인 찾음")                 # 맨 위 ☐ 선택지 줄은 떼고 본문만
        self.assertIn("[T12]", m["foot"])

    def test_first_instruction(self):
        m = chat.parse_message(mail("#c 34097 원인 봐줘", "주문 수집 쪽", "<m1@x>"), CFG)
        self.assertFalse(m["bot"])
        self.assertIsNone(m["thread"])
        self.assertEqual(m["text"], "34097 원인 봐줘\n주문 수집 쪽")

    def test_reply_is_body_only_without_quote(self):
        body = "1,2 빨리\n\n2026. 10. 6. 오후 4:12, 나 <me@example.com> 작성:\n> 원인 찾음"
        m = chat.parse_message(mail("Re: #c [T12] 34097 원인 봐줘", body, "<m2@x>"), CFG)
        self.assertEqual((m["thread"], m["text"]), (12, "1,2 빨리"))

    def test_untagged_mail_is_ignored(self):
        self.assertIsNone(chat.parse_message(mail("점심 메뉴", "", "<z@x>"), CFG))


class BuildThreads(unittest.TestCase):
    def test_first_instruction_joins_numbered_thread(self):
        msgs = [chat.parse_message(mail("#c 34097 원인 봐줘", "", "<m1@x>"), CFG), chat.parse_message(bot(JOB), CFG)]
        (t,) = chat.build_threads(msgs)
        self.assertEqual((t["key"], t["no"], t["status"]), ("T12", 12, "ask"))
        self.assertEqual(t["title"], "34097 원인 봐줘")
        self.assertEqual(t["reply_to"], [m for m in msgs if m["bot"]][0]["id"])

    def test_status_and_local_jobs(self):
        msgs = [chat.parse_message(bot(dict(JOB, result="끝")), CFG),
                chat.parse_message(mail("Re: #c [T12] x", "더 봐줘", "<m3@x>", date="Tue, 06 Oct 2026 16:10:00 +0900"), CFG)]
        self.assertEqual(chat.build_threads(msgs)[0]["status"], "sent")
        self.assertEqual(chat.build_threads(msgs, {12: "running"})[0]["status"], "running")

    def test_bot_only_thread_title_drops_folder_key(self):
        j = dict(JOB, mail_subject="cw [T3] @docs 보고서 요약", thread=3, mode="write", result="봤음", mail_msgid=None)
        (t,) = chat.build_threads([chat.parse_message(bot(j), CFG)])
        self.assertEqual((t["title"], t["mode"]), ("보고서 요약", "write"))


class Compose(unittest.TestCase):
    T = [{"key": "T12", "no": 12, "tag": "#cw", "mode": "write", "title": "파일 고쳐줘", "reply_to": "<b@x>"}]

    def test_answer_with_picks(self):
        subj, body, rt, shown = chat.compose(CFG, {"key": "T12", "picks": [3, 1], "text": "빨리"}, self.T)
        self.assertEqual((subj, body, rt), ("Re: #cw [T12] 파일 고쳐줘", "1,3 빨리", "<b@x>"))
        self.assertEqual(shown["text"], "☑ 1 ☑ 3\n빨리")

    def test_stop(self):
        self.assertEqual(chat.compose(CFG, {"key": "T12", "stop": True}, self.T)[1], "멈춤")

    def test_new_instruction(self):
        self.assertEqual(chat.compose(CFG, {"text": "로그 봐줘\n어제 것", "mode": "write", "folder": "docs"}, [])[:2],
                         ("#cw @docs 로그 봐줘", "어제 것"))

    def test_issue_needs_prefix(self):
        with self.assertRaises(ValueError):                 # 기본값엔 이슈 키 앞부분이 없다 — 이슈 칸은 꺼져 있다
            chat.compose(CFG, {"issue": "34097"}, [])
        cfg = dict(CFG, issue_prefix="PROJ-", issue_command="/issue")
        self.assertEqual(chat.compose(cfg, {"issue": "34097"}, [])[0], "#cw /issue PROJ-34097")
        self.assertEqual(chat.compose(cfg, {"issue": "abc-9"}, [])[0], "#cw /issue ABC-9")
        with self.assertRaises(ValueError):
            chat.compose(cfg, {"issue": "abc 9; 지워줘"}, [])
        # 게이트웨이가 같은 제목을 이슈 명령으로 알아본다
        subj = chat.compose(cfg, {"issue": "7"}, [])[0]
        prompt = mg.build_instruction(subj, "", dict(GW, default_workdir="C:\\w", workdir_keys={}, max_prompt_chars=4000))[0]
        self.assertTrue(mg.is_issue_prompt(prompt, cfg))

    def test_gateway_reads_what_chat_sends(self):
        # 대화 앱이 만든 제목을 게이트웨이가 같은 대화(스레드)·지시로 알아보는지
        subj = chat.compose(CFG, {"key": "T12", "picks": [1]}, self.T)[0]
        self.assertEqual(mg.thread_of(mg.strip_reply_prefix(subj)), 12)
        self.assertEqual(mg.match_tag(mg.strip_reply_prefix(subj), GW)[1], "write")


class Config(unittest.TestCase):
    """기본값은 회사 중립 · 이 저장소 안이면 키트 설정(config.local.json)의 mail · dispatch 를 읽는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = (chat.KIT_CFG, chat.OWN_CFG)
        chat.KIT_CFG = os.path.join(self.tmp, "config.local.json")
        chat.OWN_CFG = os.path.join(self.tmp, "own", "config.json")

    def tearDown(self):
        chat.KIT_CFG, chat.OWN_CFG = self._saved

    def test_neutral_defaults(self):
        cfg, src = chat.load_cfg()
        self.assertEqual(src, "own")
        self.assertEqual((cfg["imap_host"], cfg["smtp_host"], cfg["issue_prefix"]), ("", "", ""))
        self.assertEqual((cfg["folders"], cfg["workdir_keys"]), (["INBOX"], []))

    def test_reads_kit_config(self):
        with open(chat.KIT_CFG, "w", encoding="utf-8") as f:
            json.dump({"mail": {"user": "me@example.com", "imap_host": "imap.example.com", "password_enc": "x"},
                       "dispatch": {"folders": ["INBOX", "Sent-to-self"], "workdir_keys": {"docs": "D:\\docs"},
                                    "issue_prefix": "PROJ-", "reply_mode": "append"}}, f)
        cfg, src = chat.load_cfg()
        self.assertEqual(src, "kit")
        self.assertEqual((cfg["user"], cfg["imap_host"]), ("me@example.com", "imap.example.com"))
        self.assertEqual(cfg["folders"], ["INBOX", "Sent-to-self"])
        self.assertEqual(cfg["workdir_keys"], ["docs"])
        self.assertEqual((cfg["issue_prefix"], cfg["send_mode"]), ("PROJ-", "append"))

    def test_own_account_wins(self):
        with open(chat.KIT_CFG, "w", encoding="utf-8") as f:
            json.dump({"mail": {"user": "me@example.com"}}, f)
        chat.write_json(chat.OWN_CFG, {"user": "other@example.com", "imap_host": "imap.example.org"})
        cfg, src = chat.load_cfg()
        self.assertEqual((src, cfg["user"]), ("own", "other@example.com"))


if __name__ == "__main__":
    unittest.main()
