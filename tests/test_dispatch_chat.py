# -*- coding: utf-8 -*-
"""tools/dispatch-chat/chat.py — 메일을 대화로 묶는 규칙과 키트 설정 출처의 회귀 테스트(메일 서버 없이 돈다).

게이트웨이(mail-gateway.py)가 실제로 만드는 회신 메일을 그대로 먹여, 대화 앱이 봇 말·선택지·대화 번호를 알아보는지 본다.
키트 모드(config.local.json 의 mail · dispatch) — 계정·폴더·이슈 이름 옮기기, 직접 실행·Jira 감시 막힘, 작업 폴더 저장.
(대화 앱의 나머지 시험: test_dispatch_chat_app · test_chat_runner · test_chat_jira_watch)
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from email.message import EmailMessage
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools", "dispatch-chat"))
import chat  # noqa: E402
import chat_runner  # noqa: E402

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
        with self.assertRaises(ValueError):                 # 기본값엔 이슈 키 앞부분이 없다 — 번호만으로는 키가 안 된다
            chat.compose(CFG, {"jira": "34097"}, [])
        cfg = dict(CFG, jira_prefix="PROJ-", issue_command="/issue")
        self.assertEqual(chat.compose(cfg, {"jira": "34097"}, [])[0], "#cw /issue PROJ-34097")
        self.assertEqual(chat.compose(cfg, {"jira": "abc-9"}, [])[0], "#cw /issue ABC-9")
        self.assertEqual(chat.compose(dict(cfg, issue_command=""), {"jira": "7"}, [])[0], "#cw /jira PROJ-7")   # 직접 실행 PC 기본
        with self.assertRaises(ValueError):
            chat.compose(cfg, {"jira": "abc 9; 지워줘"}, [])
        # 게이트웨이가 같은 제목을 이슈 명령으로 알아본다(키트 이름: dispatch.issue_prefix · issue_command)
        subj = chat.compose(cfg, {"jira": "7"}, [])[0]
        gw = dict(GW, default_workdir="C:\\w", workdir_keys={}, max_prompt_chars=4000, issue_prefix="PROJ-", issue_command="/issue")
        prompt = mg.build_instruction(subj, "", gw)[0]
        self.assertTrue(mg.is_issue_prompt(prompt, gw))

    def test_gateway_reads_what_chat_sends(self):
        # 대화 앱이 만든 제목을 게이트웨이가 같은 대화(스레드)·지시로 알아보는지
        subj = chat.compose(CFG, {"key": "T12", "picks": [1]}, self.T)[0]
        self.assertEqual(mg.thread_of(mg.strip_reply_prefix(subj)), 12)
        self.assertEqual(mg.match_tag(mg.strip_reply_prefix(subj), GW)[1], "write")


class Config(unittest.TestCase):
    """기본값은 회사 중립 · 이 저장소 안이면 키트 설정(config.local.json)의 mail · dispatch 를 읽는다(출처 'kit' = 게이트웨이 PC)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, val in (("KIT_CFG", os.path.join(self.tmp, "config.local.json")), ("OWN_CFG", os.path.join(self.tmp, "own", "config.json")),
                          ("LOG_PATH", os.path.join(self.tmp, "chat.log")), ("KIT_HERE", False)):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
            setattr(chat, name, val)

    def kit(self, mail=None, dispatch=None):
        chat.write_json(chat.KIT_CFG, {"mail": dict({"user": "me@example.com", "imap_host": "imap.example.com", "password_enc": "x"}, **(mail or {})),
                                       "dispatch": dispatch or {}, "monitors": [{"name": "keep"}]})

    def test_neutral_defaults(self):
        os.remove(chat.KIT_CFG) if os.path.exists(chat.KIT_CFG) else None
        cfg, src = chat.load_cfg()
        self.assertEqual(src, "own")
        self.assertEqual((cfg["imap_host"], cfg["smtp_host"], cfg["jira_prefix"], cfg["issue_command"]), ("", "", "", ""))
        self.assertEqual((cfg["folders"], cfg["workdir_keys"]), (["INBOX"], []))

    def test_reads_kit_config(self):
        self.kit(dispatch={"folders": ["INBOX", "Sent-to-self"], "workdir_keys": {"docs": "D:\\docs"},
                           "issue_prefix": "PROJ-", "reply_mode": "append"})
        cfg, src = chat.load_cfg()
        self.assertEqual(src, "kit")
        self.assertEqual((cfg["user"], cfg["imap_host"], cfg["password_enc"]), ("me@example.com", "imap.example.com", "x"))
        self.assertEqual(cfg["folders"], ["INBOX", "Sent-to-self"])
        self.assertEqual(cfg["workdir_keys"], ["docs", "hub"])       # 허브 폴더는 기본으로
        # 키트의 범용 이름 → 이 앱의 이슈 칸. 명령이 없으면 게이트웨이 기본값(/issue)
        self.assertEqual((cfg["jira_prefix"], cfg["issue_command"], cfg["send_mode"]), ("PROJ-", "/issue", "append"))
        # 기본 폴더 — 게이트웨이와 같은 기본값(%USERPROFILE%\Documents)을 풀어서
        self.assertEqual(chat.default_folder(cfg, False), ("Documents", chat.expand(r"%USERPROFILE%\Documents")))

    def test_own_account_wins(self):
        self.kit()
        chat.write_json(chat.OWN_CFG, {"user": "other@example.com", "imap_host": "imap.example.org"})
        cfg, src = chat.load_cfg()
        self.assertEqual((src, cfg["user"]), ("own", "other@example.com"))
        self.assertEqual(chat.folders_info(), {"mode": "own"})
        with self.assertRaises(ValueError):
            chat.save_gateway_folders({"workdir": self.tmp, "dirs": ""})

    def test_kit_mode_is_gateway_pc(self):
        """키트 모드 — 계정·폴더·기본 폴더는 config.local.json 에서, 직접 실행·Jira 감시는 막히고, ⚙ 작업 폴더는 dispatch 갈래에 저장한다."""
        main, web = os.path.join(self.tmp, "main"), os.path.join(self.tmp, "web")
        os.makedirs(main), os.makedirs(web)
        self.kit(dispatch={"enabled": True, "default_workdir": main, "workdir_keys": {"home": main, "web": web},
                           "issue_prefix": "PROJ-", "issue_command": "/task", "keyed_senders": {"p@example.com": "w"}})
        cfg, src = chat.load_cfg()
        self.assertEqual(src, "kit")
        self.assertEqual(cfg["workdir_keys"], ["web", "hub"])                       # 기본 폴더와 같은 키는 칩에서 빼고
        self.assertEqual(chat.default_folder(cfg, False), ("home", main))    # 기본 폴더 칩에 그 이름
        self.assertEqual(chat.compose(cfg, {"jira": "5"}, [])[0], "#cw /task PROJ-5")
        r = chat_runner.Runner(chat, root=os.path.join(self.tmp, "runner"))
        r.claude_cmd = lambda: ["claude"]
        self.assertIn("키트", r.blocked(cfg, src))
        with self.assertRaises(ValueError):
            r.configure({"enabled": True, "workdir": main})
        self.assertFalse(r.on())
        self.assertIn("jira-watch.py", r.jira.blocked(cfg, src))
        with self.assertRaises(ValueError):
            r.jira.configure({"enabled": True})
        info = chat.folders_info()
        self.assertEqual((info["mode"], info["workdir"], info["file"]), ("gateway", main, chat.KIT_CFG))
        out = chat.save_gateway_folders({"workdir": web, "dirs": "home=%s\nweb=%s" % (main, web)})
        self.assertIn("회사 모드", out["note"])
        full = chat.read_json(chat.KIT_CFG)
        d = full["dispatch"]
        self.assertEqual((d["default_workdir"], d["company_workdirs"], d["workdir_keys"]), (web, [main], {"home": main, "web": web}))
        self.assertEqual((d["enabled"], d["issue_prefix"], d["keyed_senders"]), (True, "PROJ-", {"p@example.com": "w"}))   # 다른 키는 그대로
        self.assertEqual((full["mail"]["user"], full["monitors"]), ("me@example.com", [{"name": "keep"}]))
        # 키트 게이트웨이도 고친 값을 그대로 읽는다(폴링마다 load_cfg)
        with mock.patch.object(mg.kit, "F_CONFIG", chat.KIT_CFG):
            g = mg.load_cfg()
        self.assertEqual((g["default_workdir"], g["workdir_keys"]["web"]), (os.path.normpath(web), os.path.normpath(web)))
        self.assertEqual(mg.company_dirs(g), [os.path.normcase(os.path.abspath(main)).rstrip("\\/")])

    def test_runner_blocked_when_kit_gateway_on(self):
        """이 PC 앱 설정(own)으로 돌아도, 이 저장소의 키트 게이트웨이가 켜져 있으면(dispatch.enabled) 직접 실행은 켜지지 않는다."""
        self.kit(dispatch={"enabled": True})
        chat.write_json(chat.OWN_CFG, {"user": "other@example.com", "password_enc": "x", "imap_host": "imap.example.org"})
        chat.KIT_HERE = True
        cfg, src = chat.load_cfg()
        r = chat_runner.Runner(chat, root=os.path.join(self.tmp, "runner"))
        self.assertEqual(src, "own")
        self.assertIn("게이트웨이", r.blocked(cfg, src))
        self.kit(dispatch={"enabled": False})
        self.assertEqual(r.blocked(cfg, src), "")

    @unittest.skipUnless(sys.platform == "win32", "DPAPI 는 윈도우만")
    def test_kit_password_enc_decodes(self):
        """키트(kit.protect)가 암호화한 password_enc 를 이 앱이 그대로 푼다 — 같은 DPAPI(엔트로피 없음, base64)."""
        self.assertEqual(chat.unprotect_secret(mg.kit.protect("pw-한글")), "pw-한글")
        self.assertEqual(mg.kit.unprotect(chat.protect_secret("pw2")), "pw2")


if __name__ == "__main__":
    unittest.main()
