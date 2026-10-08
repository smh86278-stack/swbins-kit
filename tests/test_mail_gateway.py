# -*- coding: utf-8 -*-
"""mail-gateway.py 의 순수 함수 회귀 테스트 (IMAP·SMTP 없이 돈다).

실행:  python -m unittest discover -s tests -v      (저장소 루트에서)

각 테스트 이름 옆에 적은 것은 실제로 겪은 사고다. 주석에만 남아 있던 것을 고정해 둔다.
"""
import email
import email.policy
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("mail_gateway", os.path.join(ROOT, "mail-gateway.py"))
mg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mg)
# log() 가 실제 inbox\mail-gateway.log 에 쓰지 않게 돌려놓는다
mg.LOG_PATH = os.path.join(tempfile.gettempdir(), "mail-gateway-test.log")

CFG = {
    "tags": ["#c", "c"], "tag": "#c",
    "write_tags": ["#cw", "cw"],
    "default_workdir": r"C:\default",
    "workdir_keys": {"docs": r"C:\work\docs", "notes": r"C:\work\notes"},
    "max_prompt_chars": 4000,
}


class StripReplyPrefix(unittest.TestCase):
    def test_nested(self):
        self.assertEqual(mg.strip_reply_prefix("Re: Re: #c 확인"), "#c 확인")

    def test_korean_and_forward(self):
        self.assertEqual(mg.strip_reply_prefix("회신: #c 확인"), "#c 확인")

    def test_untouched(self):
        self.assertEqual(mg.strip_reply_prefix("#c 확인"), "#c 확인")

    def test_subject_key(self):
        # 폰 페이지가 제목 끝에 붙이는 암호 단어 — 떼어 내고, 주소·단어가 둘 다 맞아야 통과
        self.assertEqual(mg.split_subject_key("#c 확인해줘 [k:abc123]"), ("#c 확인해줘", "abc123"))
        self.assertEqual(mg.split_subject_key("#c [k:x] 중간에 있으면 아님"), ("#c [k:x] 중간에 있으면 아님", None))
        cfg = {"keyed_senders": {"Me@iCloud.test": "abc123"}}
        self.assertTrue(mg.key_sender_ok(cfg, "me@icloud.test", "abc123"))
        self.assertFalse(mg.key_sender_ok(cfg, "me@icloud.test", "wrong"))
        self.assertFalse(mg.key_sender_ok(cfg, "me@icloud.test", None))
        self.assertFalse(mg.key_sender_ok(cfg, "other@icloud.test", "abc123"))
        self.assertFalse(mg.key_sender_ok({"keyed_senders": {"me@icloud.test": ""}}, "me@icloud.test", ""))

    def test_mailto_adds_key_for_phone(self):
        # 폰(개인 주소)에서 온 지시의 회신 단추에는 암호 단어가 붙고, 회사 주소 지시에는 안 붙는다
        cfg = {"user": "me@company.test", "keyed_senders": {"me@icloud.test": "abc123"}}
        phone = {"mail_subject": "#c [T3] 확인", "mail_from": "me@icloud.test"}
        corp = {"mail_subject": "#c [T3] 확인", "mail_from": "me@company.test"}
        self.assertIn(mg.quote(" [k:abc123]"), mg.mailto(cfg, phone, "1"))
        self.assertNotIn("k%3A", mg.mailto(cfg, corp, "1"))


class MatchTag(unittest.TestCase):
    def test_tuple_is_truthy_even_when_no_match(self):
        # (None, None) 은 튜플이라 참이다. 튜플 자체로 판정하면 모든 메일이 통과한다 — 반드시 [0] 을 볼 것.
        self.assertEqual(mg.match_tag("점심 뭐 먹지", CFG), (None, None))
        self.assertTrue(bool((None, None)))

    def test_requires_whitespace_after_tag(self):
        self.assertEqual(mg.match_tag("check list", CFG), (None, None))
        self.assertEqual(mg.match_tag("c 확인해줘", CFG), ("c", "read"))

    def test_longer_tag_wins(self):
        # 'cw ...' 가 'c' 로 잘못 잡히면 쓰기 지시가 읽기로 떨어진다
        self.assertEqual(mg.match_tag("cw 고쳐줘", CFG), ("cw", "write"))
        self.assertEqual(mg.match_tag("#cw 고쳐줘", CFG), ("#cw", "write"))

    def test_bare_tag(self):
        self.assertEqual(mg.match_tag("#c", CFG), ("#c", "read"))


class BuildInstruction(unittest.TestCase):
    def test_default_workdir(self):
        prompt, wd, label, mode = mg.build_instruction("#c 보고서 확인", "", CFG)
        self.assertEqual((prompt, wd, label, mode), ("보고서 확인", r"C:\default", "default", "read"))

    def test_workdir_key(self):
        prompt, wd, label, _ = mg.build_instruction("#c @docs 로그 확인", "", CFG)
        self.assertEqual((prompt, wd, label), ("로그 확인", r"C:\work\docs", "docs"))

    def test_unknown_key_stays_in_prompt(self):
        # "@media 쿼리 찾아줘" 의 @media 는 지시의 일부다
        prompt, wd, _, _ = mg.build_instruction("#c @media 쿼리 찾아줘", "", CFG)
        self.assertEqual(prompt, "@media 쿼리 찾아줘")
        self.assertEqual(wd, r"C:\default")

    def test_untagged_subject_gives_empty_prompt(self):
        # 태그 없는 제목의 앞글자를 임의로 떼면 회신 메일이 지시로 재실행된다
        self.assertEqual(mg.build_instruction("Re: 결과입니다", "본문", CFG)[0], "")

    def test_body_appended_and_signature_cut(self):
        prompt, *_ = mg.build_instruction("#c 요약", "본문 내용\n\n-- \n서명", CFG)
        self.assertTrue(prompt.startswith("요약\n\n본문 내용"))
        self.assertNotIn("서명", prompt)

    def test_write_mode(self):
        self.assertEqual(mg.build_instruction("cw 고쳐줘", "", CFG)[3], "write")

    def test_prompt_length_capped(self):
        cfg = dict(CFG, max_prompt_chars=10)
        self.assertLessEqual(len(mg.build_instruction("#c " + "가" * 100, "", cfg)[0]), 10)


class FindResumeTarget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = mg.JOBS
        mg.JOBS = self.tmp

    def tearDown(self):
        mg.JOBS = self._old

    def _job(self, name, **kw):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as f:
            json.dump(kw, f)

    def _head(self, **headers):
        raw = "".join("%s: %s\r\n" % kv for kv in headers.items()) + "\r\n"
        return email.message_from_string(raw)

    def test_reply_to_our_reply_resumes_session(self):
        self._job("a.json", source="mail", session_id="S1", reply_msgid="<r1@x>", mail_msgid="<m1@x>",
                  workdir=r"C:\w", workdir_label="docs")
        got = mg.find_resume_target(self._head(**{"In-Reply-To": "<r1@x>"}))
        self.assertEqual(got, ("S1", r"C:\w", "docs", []))

    def test_references_chain(self):
        self._job("a.json", source="mail", session_id="S2", mail_msgid="<m2@x>")
        got = mg.find_resume_target(self._head(References="<old@x> <m2@x>"))
        self.assertEqual(got[0], "S2")

    def test_unrelated_or_web_job_is_ignored(self):
        self._job("a.json", source="web", session_id="S3", reply_msgid="<r3@x>")
        self.assertIsNone(mg.find_resume_target(self._head(**{"In-Reply-To": "<r3@x>"})))
        self.assertIsNone(mg.find_resume_target(self._head(**{"In-Reply-To": "<none@x>"})))

    def test_no_reference_headers(self):
        self.assertIsNone(mg.find_resume_target(self._head(Subject="x")))

    def test_resumed_job_inherits_disallowed_tools(self):
        # 이어받는 순간 첫 잡의 네트워크 명령 차단(이슈 처리 등)이 사라지면 안 된다
        self._job("a.json", source="mail", session_id="S9", mail_msgid="<m9@x>",
                  disallowed_tools=["Bash(curl:*)", "Bash(rtk curl:*)"])
        got = mg.find_resume_target(self._head(**{"In-Reply-To": "<m9@x>"}))
        self.assertEqual(got[3], ["Bash(curl:*)", "Bash(rtk curl:*)"])
        job = mg.new_job("이어서", r"C:\w", "docs", "<n@x>", "cw 이어서", "me@example.com", "write",
                         {"write_tools": ["Read", "Bash"]}, resume_id=got[0], disallowed_tools=got[3])
        self.assertEqual(job["disallowed_tools"], ["Bash(curl:*)", "Bash(rtk curl:*)"])


class AuthResults(unittest.TestCase):
    def _h(self, *values):
        raw = "".join("Authentication-Results: %s\r\n" % v for v in values) + "\r\n"
        return email.message_from_string(raw)

    def test_missing_header(self):
        self.assertEqual(mg.auth_results_summary(self._h())[0], False)

    def test_dkim_pass(self):
        self.assertTrue(mg.auth_results_summary(self._h("mx.example; dkim=pass header.d=example.com"))[0])

    def test_spf_pass_in_second_header(self):
        self.assertTrue(mg.auth_results_summary(self._h("mx; dkim=none", "mx; spf=pass smtp.mailfrom=a@b"))[0])

    def test_fail_is_not_pass(self):
        self.assertFalse(mg.auth_results_summary(self._h("mx; dkim=fail; spf=softfail"))[0])


class ConfirmAnswer(unittest.TestCase):
    def test_yes_variants(self):
        for t in ("1", "확인", "실행", "OK", "yes", " 1 ", "1.", "확인!", "네\n\n> 원문 인용"):
            self.assertEqual(mg.parse_confirm_answer(t), "yes", t)

    def test_no_variants(self):
        for t in ("2", "취소", "no", "아니오"):
            self.assertEqual(mg.parse_confirm_answer(t), "no", t)

    def test_ambiguous_is_none(self):
        # 애매하면 실행도 취소도 하지 않는다 — 폰 오타로 쓰기 권한이 열리면 안 된다
        for t in ("", "\n\n", "글쎄", "1번 말고 다른 방법", "> 인용만 있음", "12"):
            self.assertIsNone(mg.parse_confirm_answer(t), repr(t))

    def test_only_first_meaningful_line_counts(self):
        self.assertEqual(mg.parse_confirm_answer("> 인용\n\n1\n취소"), "yes")
        self.assertIsNone(mg.parse_confirm_answer("음 그런데\n1"))


class WriteConfirmFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = mg.JOBS
        mg.JOBS = self.tmp
        self.cfg = dict(CFG, user="me@example.com", write_tools=["Read", "Bash"], confirm_ttl_min=60)

    def tearDown(self):
        mg.JOBS = self._old

    def _job(self, **kw):
        return mg.new_job("고쳐줘", r"C:\w", "docs", "<orig@x>", "cw 고쳐줘", "me@example.com",
                          "write", self.cfg, **kw)

    def _head(self, **headers):
        raw = "".join("%s: %s\r\n" % kv for kv in headers.items()) + "\r\n"
        return email.message_from_string(raw)

    def _path(self, job):
        return os.path.join(self.tmp, job["id"] + ".json")

    def test_confirm_job_waits_and_worker_will_not_pick_it(self):
        job = self._job(confirm=True)
        self.assertEqual(job["status"], "awaiting_confirm")   # 워커는 'queued' 만 집는다
        self.assertFalse(job["confirm_sent"])

    def test_without_confirm_is_queued_as_before(self):
        self.assertEqual(self._job()["status"], "queued")

    def test_confirm_message_threads_and_reply_is_recognised(self):
        job = self._job(confirm=True)
        cmsg, cmid = mg.build_confirm_message(self.cfg, job)
        self.assertEqual(cmsg["In-Reply-To"], "<orig@x>")
        self.assertTrue(cmsg["Subject"].startswith("Re: cw"))
        self.assertIn("고쳐줘", cmsg.get_body(("plain",)).get_content())
        job["confirm_sent"], job["confirm_msgid"] = True, cmid
        mg.write_json(self._path(job), job)
        found = mg.find_pending_confirm(self._head(**{"In-Reply-To": cmid}))
        self.assertIsNotNone(found)
        self.assertEqual(found[1]["id"], job["id"])
        # 우리가 보낸 확인 메일 자체는 새 지시로 오인하지 않는다(무한 핑퐁 방지)
        self.assertIn(cmid, mg.load_own_reply_ids())

    def test_unrelated_reply_is_not_a_confirmation(self):
        job = self._job(confirm=True)
        job["confirm_sent"], job["confirm_msgid"] = True, "<c1@x>"
        mg.write_json(self._path(job), job)
        self.assertIsNone(mg.find_pending_confirm(self._head(**{"In-Reply-To": "<other@x>"})))
        self.assertIsNone(mg.find_pending_confirm(self._head(Subject="x")))

    def test_already_decided_job_ignores_late_reply(self):
        job = self._job(confirm=True)
        job.update(status="canceled", confirm_sent=True, confirm_msgid="<c2@x>")
        mg.write_json(self._path(job), job)
        self.assertIsNone(mg.find_pending_confirm(self._head(**{"In-Reply-To": "<c2@x>"})))

    def test_expired_confirmation_is_canceled(self):
        job = self._job(confirm=True)
        job["created_at"] = (mg.datetime.now() - mg.timedelta(minutes=61)).strftime("%Y-%m-%d %H:%M:%S")
        mg.write_json(self._path(job), job)
        fresh = self._job(confirm=True)
        mg.expire_confirms(self.cfg)
        self.assertEqual(mg.read_json(self._path(job))["status"], "canceled")
        self.assertEqual(mg.read_json(self._path(fresh))["status"], "awaiting_confirm")


class FakeImap:
    """poll_once / send_replies 가 쓰는 IMAP 메서드만 흉내 낸다."""

    def __init__(self, mails, appended, by_box=None):
        self.mails = mails            # {uid(str): 원문 bytes}
        self.appended = appended      # append() 로 들어온 메일 원문 bytes 목록
        self.by_box = by_box          # {폴더: {uid: 원문}} — 폴더마다 다른 메일이 필요한 시험만
        self.cur = mails

    def select(self, box):
        if self.by_box is not None:
            self.cur = self.by_box.get(box.strip('"'), {})
        return "OK", [b""]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            return "OK", [" ".join(self.cur).encode()]
        if cmd == "FETCH":
            raw = self.cur[args[0]]
            if "HEADER" in args[1]:
                raw = raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
            return "OK", [(b"1", raw)]
        return "OK", [b""]            # STORE

    def append(self, box, flags, date, data):
        self.appended.append(data)

    def close(self):
        pass

    def logout(self):
        pass


class PollOnceConfirmFlow(unittest.TestCase):
    """실제 poll_once → send_replies → poll_once 를 가짜 IMAP 으로 끝까지 돌린다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.jobs = os.path.join(self.tmp, "jobs")
        os.makedirs(self.jobs)
        self.workdir = os.path.join(self.tmp, "work")
        os.makedirs(self.workdir)
        self._saved = {k: getattr(mg, k) for k in ("JOBS", "SEEN_PATH", "LOG_PATH", "NOTIFY_PATH", "THREAD_SEQ_PATH",
                                                    "imap_connect", "resolve_folders", "notify", "EARLY_STOP_PATH", "ATTACH")}
        mg.JOBS = self.jobs
        mg.EARLY_STOP_PATH = os.path.join(self.tmp, "early-stops.json")
        mg.ATTACH = os.path.join(self.tmp, "attachments")
        mg.THREAD_SEQ_PATH = os.path.join(self.tmp, "thread-seq.json")
        mg.SEEN_PATH = os.path.join(self.tmp, "seen.json")
        mg.LOG_PATH = os.path.join(self.tmp, "gw.log")
        mg.NOTIFY_PATH = os.path.join(self.tmp, "notify.jsonl")
        mg.notify = lambda *a, **k: None
        self.mails, self.appended = {}, []
        mg.imap_connect = lambda cfg, pw: FakeImap(self.mails, self.appended)
        mg.resolve_folders = lambda m, folders: ["INBOX"]
        self.cfg = {
            "user": "me@example.com", "allowed_senders": ["me@example.com"],
            "tags": ["#c", "c"], "tag": "#c", "write_tags": ["#cw", "cw"],
            "write_tools": ["Read", "Bash"], "folders": ["INBOX"],
            "default_workdir": self.workdir, "workdir_keys": {}, "max_prompt_chars": 4000,
            "lookback_days": 2, "max_per_cycle": 5, "reply_mode": "append",
            "confirm_write": True, "confirm_ttl_min": 60, "require_auth_results": False,
        }

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(mg, k, v)

    def _mail(self, uid, subject, body, msgid, in_reply_to=None):
        m = email.message.EmailMessage()
        m["Subject"], m["From"], m["To"], m["Message-ID"] = subject, "me@example.com", "me@example.com", msgid
        if in_reply_to:
            m["In-Reply-To"] = in_reply_to
        m.set_content(body)
        self.mails[uid] = m.as_bytes().replace(b"\n", b"\r\n") if b"\r\n" not in m.as_bytes() else m.as_bytes()

    def _jobs(self):
        out = []
        for fn in os.listdir(self.jobs):
            if fn.endswith(".json"):
                out.append(mg.read_json(os.path.join(self.jobs, fn)))
        return out

    def _send_confirm(self):
        mg.send_replies(self.cfg, "pw")
        confirm = email.message_from_bytes(self.appended[-1])
        return confirm["Message-ID"]

    def test_write_instruction_waits_then_runs_after_yes(self):
        self._mail("1", "cw 파일 고쳐줘", "본문", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        self.assertEqual(job["status"], "awaiting_confirm")     # 아직 실행 대기열에 없다

        cmid = self._send_confirm()                              # 확인 메일이 나간다
        self.assertEqual(self._jobs()[0]["confirm_msgid"], cmid)

        self._mail("2", "Re: Re: cw 파일 고쳐줘", "1\n\n> 원문", "<m2@x>", in_reply_to=cmid)
        mg.poll_once(self.cfg, "pw")
        jobs = self._jobs()
        self.assertEqual(len(jobs), 1)                           # 답장이 새 지시로 오인되지 않았다
        self.assertEqual(jobs[0]["status"], "queued")
        self.assertIn("confirmed_at", jobs[0])

    def test_no_reply_cancels(self):
        self._mail("1", "cw 파일 고쳐줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        cmid = self._send_confirm()
        self._mail("2", "Re: cw 파일 고쳐줘", "취소", "<m2@x>", in_reply_to=cmid)
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(self._jobs()[0]["status"], "canceled")

    def test_garbled_reply_keeps_waiting(self):
        self._mail("1", "cw 파일 고쳐줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        cmid = self._send_confirm()
        self._mail("2", "Re: cw 파일 고쳐줘", "글쎄요", "<m2@x>", in_reply_to=cmid)
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(self._jobs()[0]["status"], "awaiting_confirm")

    def test_read_instruction_is_not_asked(self):
        self._mail("1", "#c 상태 알려줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(self._jobs()[0]["status"], "queued")
        self.assertEqual(self.appended, [])                       # 확인 메일도 안 나간다

    def test_confirm_can_be_turned_off(self):
        self.cfg["confirm_write"] = False
        self._mail("1", "cw 파일 고쳐줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(self._jobs()[0]["status"], "queued")

    def test_confirm_mail_itself_is_not_treated_as_instruction(self):
        self._mail("1", "cw 파일 고쳐줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self._send_confirm()
        # 확인 메일이 INBOX 에 들어온 것처럼 다음 폴링에서 보이게 한다
        self.mails["9"] = self.appended[-1]
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(len(self._jobs()), 1)


    def test_stop_running_job_leaves_stop_file(self):
        # 폰 대화방 '멈춤' — 돌고 있는 일에 대한 '멈춤' 은 새 잡이 아니라 워커에게 끊으라는 표시(jobs\<id>.stop)
        self._mail("1", "#c 오래 걸리는 일", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        job["status"] = "running"
        mg.write_json(os.path.join(self.jobs, job["id"] + ".json"), job)
        self._mail("2", "Re: #c 오래 걸리는 일", "멈춤\n\n나의 iPhone에서 보냄", "<m2@x>", in_reply_to="<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(len(self._jobs()), 1)                   # 새 잡을 만들지 않았다
        self.assertTrue(os.path.exists(os.path.join(self.jobs, job["id"] + ".stop")))

    def test_stop_before_instruction_arrives(self):
        # 2026-10-08 실측: 메일 도착 순서가 뒤바뀌어 '멈춤' 이 지시보다 먼저 왔다 → 멈춤이 새 지시로 돌고 진짜 지시는 끝까지 돌았다.
        # 이제 먼저 온 멈춤은 잡을 만들지 않고, 나중에 온 그 지시는 실행하지 않은 채 '멈췄습니다' 로 끝난다.
        self._mail("1", "Re: #c 멈춤", "멈춤", "<s1@x>", in_reply_to="<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(self._jobs(), [])
        self._mail("2", "#c 오래 걸리는 일", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        self.assertEqual(job["status"], "done")                   # 워커가 집지 않는다
        self.assertEqual(job["result"], mg.STOPPED_BEFORE_START)
        self.assertNotIn("<m1@x>", mg.early_stops())             # 한 번 쓰면 지운다

    def test_stop_after_done_continues_session(self):
        # 끝난 일에 대한 '멈춤' 은 예전처럼 그 세션에 이어 붙는다(정리하고 보고)
        self._mail("1", "#c 일", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        job.update(status="done", session_id="s1", replied=True)
        mg.write_json(os.path.join(self.jobs, job["id"] + ".json"), job)
        self._mail("2", "Re: #c 일", "멈춤", "<m2@x>", in_reply_to="<m1@x>")
        mg.poll_once(self.cfg, "pw")
        jobs = self._jobs()
        self.assertEqual(len(jobs), 2)
        self.assertFalse(any(fn.endswith(".stop") for fn in os.listdir(self.jobs)))
        self.assertIn("s1", [j.get("resume_id") for j in jobs])


    def test_photos_are_saved_and_listed_in_prompt(self):
        # 폰 대화방 📎 — 사진은 잡마다 폴더에 저장하고 지시문 끝에 경로를 적는다. 사진이 아닌 첨부는 버린다.
        m = email.message.EmailMessage()
        m["Subject"], m["From"], m["To"], m["Message-ID"] = "#c 이 화면 오류 봐줘", "me@example.com", "me@example.com", "<p1@x>"
        m.set_content("빨간 글씨 부분")
        m.add_attachment(b"\xff\xd8jpegdata", maintype="image", subtype="jpeg", filename="../../evil.jpg")
        m.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="doc.pdf")
        self.mails["1"] = m.as_bytes().replace(b"\n", b"\r\n") if b"\r\n" not in m.as_bytes() else m.as_bytes()
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        folder = job["attach_dir"]
        self.assertTrue(folder.startswith(mg.ATTACH))
        self.assertEqual(os.listdir(folder), ["photo1.jpg"])               # 보낸 쪽 파일 이름은 쓰지 않는다
        with open(os.path.join(folder, "photo1.jpg"), "rb") as f:
            self.assertEqual(f.read(), b"\xff\xd8jpegdata")
        self.assertIn("[첨부 사진 1장", job["prompt"])
        self.assertIn(os.path.join(folder, "photo1.jpg"), job["prompt"])
        self.assertIn("빨간 글씨 부분", job["prompt"])

    def test_no_photos_no_attach_dir(self):
        self._mail("1", "#c 그냥 지시", "", "<p2@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        self.assertNotIn("attach_dir", job)

    def _phone(self, uid, subject, body, msgid, in_reply_to=None):
        m = email.message.EmailMessage()
        m["Subject"], m["From"], m["To"], m["Message-ID"] = subject, "me@gmail.test", "me@example.com", msgid
        if in_reply_to:
            m["In-Reply-To"] = in_reply_to
        m.set_content(body)
        self.mails[uid] = m.as_bytes().replace(b"\n", b"\r\n") if b"\r\n" not in m.as_bytes() else m.as_bytes()

    def test_key_in_body_line(self):
        # 2026-10-08: 폰(Gmail) 새 지시가 회사 스팸 장비에 1~10분 붙잡혔다 → 암호 단어를 제목 대신 본문 마지막 줄로.
        # 받기는 하되 Claude 에게 넘기는 지시문에는 들어가지 않아야 한다.
        self.cfg["keyed_senders"] = {"me@gmail.test": "word"}
        self._phone("1", "#c 로그 봐줘", "에러 위주로\n\n[k:word]", "<k1@x>")
        self._phone("2", "#c 단어 틀림", "아무거나\n\n[k:nope]", "<k2@x>")
        self._phone("3", "#c 단어 없음", "그냥", "<k3@x>")
        mg.poll_once(self.cfg, "pw")
        jobs = self._jobs()
        self.assertEqual([j["mail_msgid"] for j in jobs], ["<k1@x>"])
        self.assertIn("에러 위주로", jobs[0]["prompt"])
        self.assertNotIn("word", jobs[0]["prompt"])

    def test_stop_with_key_in_body(self):
        self.cfg["keyed_senders"] = {"me@gmail.test": "word"}
        self._phone("1", "#c 오래 걸리는 일", "[k:word]", "<k4@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        job["status"] = "running"
        mg.write_json(os.path.join(self.jobs, job["id"] + ".json"), job)
        self._phone("2", "Re: #c 멈춤", "멈춤\n\n[k:word]", "<k5@x>", in_reply_to="<k4@x>")
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(len(self._jobs()), 1)
        self.assertTrue(os.path.exists(os.path.join(self.jobs, job["id"] + ".stop")))

    def test_junk_folder_takes_only_keyed_mail(self):
        # 2026-10-08: 폰(Gmail) 지시가 가끔 회사 스팸함으로 떨어진다 → 스팸함도 보되, 암호 단어가 맞는 메일만.
        # 회사 주소(allowed_senders)를 사칭한 메일이 흔히 떨어지는 곳이라 그 주소라도 믿지 않는다.
        def raw(subject, sender, msgid):
            m = email.message.EmailMessage()
            m["Subject"], m["From"], m["To"], m["Message-ID"] = subject, sender, "me@example.com", msgid
            m.set_content("")
            return m.as_bytes().replace(b"\n", b"\r\n")
        spam = {"1": raw("#c 스팸에 빠진 지시 [k:word]", "me@gmail.test", "<j1@x>"),
                "2": raw("#c 회사 주소 사칭", "me@example.com", "<j2@x>"),
                "3": raw("#c 단어 틀림 [k:nope]", "me@gmail.test", "<j3@x>")}
        mg.imap_connect = lambda cfg, pw: FakeImap({}, self.appended, by_box={"INBOX": {}, "Spam": spam})
        mg.resolve_folders = lambda m, folders: ["Spam"] if folders == ["Spam"] else ["INBOX"]
        self.cfg.update(junk_folders=["Spam"], keyed_senders={"me@gmail.test": "word"})
        mg.poll_once(self.cfg, "pw")
        jobs = self._jobs()
        self.assertEqual([j["mail_msgid"] for j in jobs], ["<j1@x>"])

    def test_gmail_inbox_direct(self):
        # 2026-10-08: 회사 스팸 장비가 Gmail 새 지시를 붙잡아 → 폰이 '나에게' 보내고 PC 가 Gmail 받은편지함을 직접 읽는다.
        # 그 주소 자신 + 암호 단어만 지시. 같은 제목으로 오는 우리 회신(회사 주소)은 지시가 아니다.
        def raw(subject, sender, msgid, body):
            m = email.message.EmailMessage()
            m["Subject"], m["From"], m["To"], m["Message-ID"] = subject, sender, "me@gmail.test", msgid
            m.set_content(body)
            return m.as_bytes().replace(b"\n", b"\r\n")
        gbox = {"1": raw("#c 지금 시각", "me@gmail.test", "<g1@x>", "[k:word]"),
                "2": raw("Re: #c [T3] 회신", "me@example.com", "<g2@x>", "답입니다"),
                "3": raw("#c 단어 없음", "me@gmail.test", "<g3@x>", "그냥"),
                "4": raw("#c 남이 보냄", "other@gmail.test", "<g4@x>", "[k:word]")}
        company = {}
        mg.imap_connect = lambda cfg, pw: FakeImap(gbox if cfg.get("imap_host") == "imap.gmail.com" else company, self.appended)
        self.cfg["keyed_senders"] = {"me@gmail.test": "word", "other@gmail.test": "word"}
        acct = {"user": "me@gmail.test", "conn": dict(mg.GMAIL_IMAP, user="me@gmail.test"), "password": "app", "folders": ["INBOX"]}
        mg.poll_once(self.cfg, "pw", acct=acct)
        self.assertEqual([j["mail_msgid"] for j in self._jobs()], ["<g1@x>"])
        # 받은 지시는 PC 메신저용 사본으로 회사 INBOX 에 — 표시 머리글을 달고
        mirrored = [a for a in self.appended if b"<g1@x>" in a]
        self.assertEqual(len(mirrored), 1)
        self.assertTrue(mirrored[0].startswith(b"X-Dispatch-Mirror: gmail\r\n"))
        # 회사 쪽 폴링은 그 사본을 다시 지시로 받지 않는다(처리 기록을 지워도)
        company["9"] = mirrored[0]
        os.remove(mg.SEEN_PATH)
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(len(self._jobs()), 1)


class SeenSet(unittest.TestCase):
    def test_recent_survives_trimming(self):
        # Message-ID 는 사전순이 시간순이 아니다. 예전엔 sorted()[-800:] 로 잘라 최근 처리분이 지워졌다.
        s = mg.SeenSet()
        for i in range(900):
            s.add("<%04d>" % (899 - i))
        kept = s.recent(mg.SEEN_KEEP)
        self.assertEqual(len(kept), mg.SEEN_KEEP)
        self.assertIn("<0000>", kept)
        self.assertNotIn("<0899>", kept)

    def test_legacy_list_format(self):
        s = mg.SeenSet(["<a>", "<b>"])
        self.assertIn("<a>", s)
        self.assertEqual(s.recent(10), ["<a>", "<b>"])


class ChatParsing(unittest.TestCase):
    """메일 대화 모드 — ```choices 블록 · 번호 답 · 스레드 표식."""
    ASK = {"question": "범위?", "multi": True, "options": ["주문", "클레임", "테스트"]}

    def test_parse_choices(self):
        body, ask = mg.parse_choices('원인 찾음\n\n```choices\n{"question": "범위?", "multi": true, "options": ["a", "b"]}\n```\n')
        self.assertEqual(body, "원인 찾음")
        self.assertEqual(ask, {"question": "범위?", "multi": True, "options": ["a", "b"]})

    def test_parse_choices_absent_or_broken(self):
        self.assertEqual(mg.parse_choices("그냥 결과"), ("그냥 결과", None))
        self.assertIsNone(mg.parse_choices("x\n```choices\n{깨짐\n```")[1])
        self.assertIsNone(mg.parse_choices('```choices\n{"question": "", "options": ["a"]}\n```')[1])

    def test_parse_answer_numbers(self):
        self.assertEqual(mg.parse_answer("1,3", self.ASK), "사용자 답(번호 선택): ☑ 1. 주문 / ☑ 3. 테스트")
        self.assertTrue(mg.parse_answer("1 3", self.ASK).startswith("사용자 답(번호 선택): ☑ 1. 주문 / ☑ 3."))
        self.assertTrue(mg.parse_answer("2번", self.ASK).endswith("☑ 2. 클레임"))
        self.assertIn("덧붙인 말: 이렇게 해줘", mg.parse_answer("2 이렇게 해줘", self.ASK))

    def test_parse_answer_not_a_choice(self):
        self.assertIsNone(mg.parse_answer("4", self.ASK))               # 선택지 밖
        self.assertIsNone(mg.parse_answer("3개 파일 더 봐줘", self.ASK))  # 숫자로 시작하는 그냥 말
        self.assertIsNone(mg.parse_answer("1", None))                   # 질문이 없었다

    def test_single_choice_warns_on_many(self):
        ask = dict(self.ASK, multi=False)
        self.assertIn("한 개만 고르는 질문", mg.parse_answer("1,2", ask))

    def test_subject_with_thread(self):
        cfg = {"tags": ["#c", "c"], "write_tags": ["#cw", "cw"]}
        self.assertEqual(mg.subject_with_thread("#c 상태 알려줘", 5, cfg), "#c [T5] 상태 알려줘")
        self.assertEqual(mg.subject_with_thread("cw [자동화] S-1 제목", 7, cfg), "cw [T7] [자동화] S-1 제목")
        self.assertEqual(mg.subject_with_thread("#c [T5] 상태", 9, cfg), "#c [T5] 상태")   # 이미 있으면 그대로

    def test_instruction_drops_thread_mark(self):
        cfg = {"tags": ["#c"], "tag": "#c", "write_tags": [], "default_workdir": "C:\\w", "workdir_keys": {}, "max_prompt_chars": 4000}
        self.assertEqual(mg.build_instruction("#c [T3] 상태 알려줘", "", cfg)[0], "상태 알려줘")

    def test_reply_text_cuts_iphone_quote(self):
        body = "1,3\n\n2026. 10. 6. 오후 4:12, 나 <me@x> 작성:\n> 이전 내용\n"
        self.assertEqual(mg.reply_text(body), "1,3")


class ChatFlow(unittest.TestCase):
    """가짜 IMAP 으로: 질문이 든 결과 → 체크박스 회신 → mailto 로 쓴 번호 답(In-Reply-To 없음) → 같은 세션 이어받기."""
    SID = "11111111-2222-3333-4444-555555555555"
    # 준비·도우미만 빌린다(상속하면 확인 흐름 테스트가 두 번 돈다)
    setUp, tearDown = PollOnceConfirmFlow.setUp, PollOnceConfirmFlow.tearDown
    _mail, _jobs = PollOnceConfirmFlow._mail, PollOnceConfirmFlow._jobs

    def _finish(self, result):
        (path,) = [os.path.join(self.jobs, f) for f in os.listdir(self.jobs)]
        j = mg.read_json(path)
        j.update(status="done", session_id=self.SID, result=result)
        mg.write_json(path, j)

    def test_choices_then_numbered_answer_resumes(self):
        self._mail("1", "#c 34097 원인 봐줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self.assertTrue(self._jobs()[0]["chat"])
        self._finish('원인 찾음\n```choices\n{"question": "범위?", "multi": true, "options": ["주문", "클레임"]}\n```')
        mg.send_replies(self.cfg, "pw")
        reply = email.message_from_bytes(self.appended[-1], policy=email.policy.default)
        self.assertIn("[T1]", reply["Subject"])
        plain = reply.get_body(("plain",)).get_content()
        html = reply.get_body(("html",)).get_content()
        self.assertIn("☐ 1. 주문", plain)
        self.assertNotIn("```choices", plain)
        self.assertIn("mailto:me@example.com?subject=", html)
        self.assertEqual(self._jobs()[0]["ask"]["options"], ["주문", "클레임"])

        # 폰의 '한 번에 답장' 링크로 쓴 메일 — In-Reply-To 가 없고 제목 표식만 있다
        self._mail("2", "Re: #c [T1] 34097 원인 봐줘", "1,2\n\n2026. 10. 6. 오후 4:12, 나 <me@x> 작성:\n> 원인 찾음", "<m2@x>")
        mg.poll_once(self.cfg, "pw")
        new = [j for j in self._jobs() if j["status"] == "queued"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["resume_id"], self.SID)
        self.assertEqual(new[0]["thread"], 1)
        self.assertEqual(new[0]["prompt"], "사용자 답(번호 선택): ☑ 1. 주문 / ☑ 2. 클레임")

    def test_free_text_answer_passes_through(self):
        self._mail("1", "#c 상태", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self._finish("끝")
        mg.send_replies(self.cfg, "pw")
        self._mail("2", "#c [T1] 상태", "로그도 같이 봐줘", "<m2@x>")
        mg.poll_once(self.cfg, "pw")
        (new,) = [j for j in self._jobs() if j["status"] == "queued"]
        self.assertEqual(new["prompt"], "로그도 같이 봐줘")

    def test_confirm_by_thread_mark(self):
        self._mail("1", "cw 파일 고쳐줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        mg.send_replies(self.cfg, "pw")
        confirm = email.message_from_bytes(self.appended[-1], policy=email.policy.default)
        self.assertIn("[T1]", confirm["Subject"])
        self.assertIn("mailto:", confirm.get_body(("html",)).get_content())
        self._mail("2", "Re: cw [T1] 파일 고쳐줘", "1", "<m2@x>")     # mailto 답장 — In-Reply-To 없음
        mg.poll_once(self.cfg, "pw")
        jobs = self._jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "queued")

    def test_thread_keeps_write_mode_and_tools(self):
        self.cfg["confirm_write"] = False
        self._mail("1", "cw 파일 고쳐줘", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        self._finish("고쳤음")
        mg.send_replies(self.cfg, "pw")
        self._mail("2", "Re: #c [T1] 답", "테스트도", "<m2@x>")      # 폰 '답하기' 는 읽기 태그로 온다
        mg.poll_once(self.cfg, "pw")
        (new,) = [j for j in self._jobs() if j["status"] == "queued"]
        self.assertEqual(new["mode"], "write")
        self.assertEqual(new["allowed_tools"], ["Read", "Bash"])

    def test_issue_command_uses_issue_tools(self):
        self.cfg.update(issue_prefix="PROJ-", issue_command="/issue",
                        issue_tools=["Read", "mcp__tracker__get_issue"], issue_disallowed_tools=["Bash(curl:*)"])
        self._mail("1", "#cw /issue PROJ-34097", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        self.assertEqual(job["prompt"], "/issue PROJ-34097")
        self.assertEqual(job["allowed_tools"], ["Read", "mcp__tracker__get_issue"])
        self.assertEqual(job["disallowed_tools"], ["Bash(curl:*)"])
        self.assertEqual(job["status"], "awaiting_confirm")      # 쓰기 지시라 확인은 그대로 받는다

    def test_issue_command_off_without_prefix(self):
        # issue_prefix 가 비면 이슈 기능은 꺼져 있다 — 평범한 쓰기 지시(write_tools)로 돈다
        self.cfg.update(issue_prefix="", issue_tools=["Read", "mcp__tracker__get_issue"])
        self._mail("1", "#cw /issue PROJ-1", "", "<m1@x>")
        mg.poll_once(self.cfg, "pw")
        (job,) = self._jobs()
        self.assertEqual(job["allowed_tools"], ["Read", "Bash"])
        self.assertNotIn("disallowed_tools", job)


class Security(unittest.TestCase):
    """허용 목록이 비면 메일함에 접속하지도 않는다. 목록 밖 발신자는 무시한다."""
    setUp, tearDown = PollOnceConfirmFlow.setUp, PollOnceConfirmFlow.tearDown
    _mail, _jobs = PollOnceConfirmFlow._mail, PollOnceConfirmFlow._jobs

    def test_empty_allowed_senders_ignores_everything(self):
        self.cfg["allowed_senders"] = []
        self._mail("1", "#c 상태 알려줘", "", "<m1@x>")
        mg.imap_connect = lambda cfg, pw: self.fail("허용 목록이 비었는데 접속했다")
        self.assertEqual(mg.poll_once(self.cfg, "pw"), 0)
        self.assertEqual(self._jobs(), [])

    def test_stranger_is_ignored(self):
        self.cfg["allowed_senders"] = ["boss@example.com"]
        self._mail("1", "#c 상태 알려줘", "", "<m1@x>")          # me@example.com 이 보냈다
        mg.poll_once(self.cfg, "pw")
        self.assertEqual(self._jobs(), [])


class Config(unittest.TestCase):
    """config.local.json(mail · dispatch) → 게이트웨이 설정."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = (mg.kit.F_CONFIG, mg.STATE_PATH, mg.LOG_PATH, mg.INBOX)
        mg.kit.F_CONFIG = os.path.join(self.tmp, "config.local.json")
        mg.STATE_PATH = os.path.join(self.tmp, "mail-state.json")
        mg.LOG_PATH = os.path.join(self.tmp, "gw.log")
        mg.INBOX = self.tmp

    def tearDown(self):
        mg.kit.F_CONFIG, mg.STATE_PATH, mg.LOG_PATH, mg.INBOX = self._saved

    def _write(self, obj):
        with open(mg.kit.F_CONFIG, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def test_neutral_defaults_without_config(self):
        cfg = mg.load_cfg()
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["folders"], ["INBOX"])
        self.assertEqual(cfg["allowed_senders"], [])
        self.assertEqual(cfg["workdir_keys"], {})
        self.assertEqual(cfg["reply_mode"], "smtp")
        self.assertEqual(cfg["imap_host"], "")                    # 회사 서버를 기본값으로 두지 않는다
        self.assertEqual(cfg["tag"], "#c")

    def test_merges_mail_and_dispatch(self):
        os.environ["KIT_TEST_DIR"] = self.tmp
        self._write({
            "mail": {"user": "me@example.com", "imap_host": "imap.example.com", "password_enc": "x"},
            "dispatch": {"_설명": "무시", "enabled": True, "allowed_senders": [" me@example.com "],
                         "default_workdir": "%KIT_TEST_DIR%\\work", "workdir_keys": {"docs": "%KIT_TEST_DIR%\\docs"},
                         "folders": ["INBOX", "Sent-to-self"], "reply_mode": "append", "tags": ["!a"],
                         "user": "other@example.com"},
        })
        cfg = mg.load_cfg()
        self.assertTrue(cfg["enabled"])
        self.assertNotIn("_설명", cfg)
        self.assertEqual(cfg["user"], "me@example.com")           # 계정은 mail 갈래가 정본
        self.assertEqual(cfg["imap_host"], "imap.example.com")
        self.assertEqual(cfg["allowed_senders"], ["me@example.com"])
        self.assertEqual(cfg["default_workdir"], os.path.join(self.tmp, "work"))
        self.assertEqual(cfg["workdir_keys"], {"docs": os.path.join(self.tmp, "docs")})
        self.assertEqual(cfg["folders"], ["INBOX", "Sent-to-self"])
        self.assertEqual((cfg["reply_mode"], cfg["tag"]), ("append", "!a"))

    def test_disabled_main_exits_without_connecting(self):
        self._write({"mail": {"user": "me@example.com", "password_enc": "x"}, "dispatch": {"enabled": False}})
        saved_argv, saved_conn = mg.sys.argv, mg.imap_connect
        mg.sys.argv = ["mail-gateway.py", "--once"]
        mg.imap_connect = lambda cfg, pw: self.fail("꺼져 있는데 접속했다")
        try:
            self.assertEqual(mg.main(), 0)
        finally:
            mg.sys.argv, mg.imap_connect = saved_argv, saved_conn
        self.assertEqual(mg.read_json(mg.STATE_PATH)["state"], "disabled")

    def test_issue_prompt_needs_prefix(self):
        self.assertFalse(mg.is_issue_prompt("/issue PROJ-1", {"issue_command": "/issue"}))
        on = {"issue_prefix": "PROJ-", "issue_command": "/issue"}
        self.assertTrue(mg.is_issue_prompt("/issue PROJ-1", on))
        self.assertFalse(mg.is_issue_prompt("/issue PROJ-1 그리고 rm -rf", on))
        self.assertFalse(mg.is_issue_prompt("/issuex PROJ-1", on))



class SendAcks(unittest.TestCase):
    """폰 지시 접수 신호(폰 페이지의 읽음 '1'). 2026-10-08 Gmail 지시가 회사 스팸에 10분 갇혀 있는 동안
    폰은 'PC 가 일하는 중' 으로 보였다 — 접수 신호가 있어야 못 받은 것과 일하는 중이 갈린다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = (mg.JOBS, mg.ACKED_PATH, mg.smtp_connect)
        mg.JOBS, mg.ACKED_PATH = self.tmp, os.path.join(tempfile.mkdtemp(), "acked.json")
        self.sent = []
        test = self

        class FakeSmtp:
            def send_message(self, msg, to_addrs=None):
                test.sent.append((msg, to_addrs))

            def quit(self):
                pass
        mg.smtp_connect = lambda cfg, pw: FakeSmtp()
        self.cfg = dict(CFG, user="me@company.test", keyed_senders={"me@gmail.test": "word"})

    def tearDown(self):
        mg.JOBS, mg.ACKED_PATH, mg.smtp_connect = self._old

    def job(self, jid, sender, created="now", **kw):
        if created == "now":
            created = mg.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        j = dict({"id": jid, "source": "mail", "mail_from": sender, "mail_msgid": "<%s@gmail>" % jid,
                  "mail_subject": "#c 시험", "status": "queued", "created_at": created}, **kw)
        mg.write_json(os.path.join(self.tmp, jid + ".json"), j)
        return j

    def test_phone_job_gets_one_ack(self):
        self.job("20261008-090000-aaaa", "me@gmail.test")
        self.assertEqual(mg.send_acks(self.cfg, "pw"), 1)
        msg, to = self.sent[0]
        self.assertEqual(to, ["me@gmail.test"])
        self.assertEqual(msg["X-Dispatch-Kind"], "ack")
        self.assertEqual(msg["In-Reply-To"], "<20261008-090000-aaaa@gmail>")
        self.assertEqual(mg.send_acks(self.cfg, "pw"), 0)           # 두 번 보내지 않는다

    def test_phone_reply_to_redirects(self):
        # 새 지시는 아이폰 메일 앱(iCloud)으로 보내고 답은 폰 대화방(Gmail)으로 받는다 — 회사 스팸이 Gmail 새 지시만 붙잡아서
        self.cfg["keyed_senders"] = {"me@icloud.test": "word", "me@gmail.test": "word"}
        self.cfg["phone_reply_to"] = {"ME@icloud.test": "me@gmail.test"}
        self.job("20261008-090000-ffff", "me@icloud.test")
        self.assertEqual(mg.send_acks(self.cfg, "pw"), 1)
        self.assertEqual(self.sent[0][1], ["me@gmail.test"])
        self.assertEqual(mg.phone_to(self.cfg, "me@gmail.test"), "me@gmail.test")   # 바꾸지 않은 주소는 그대로
        self.assertEqual(mg.phone_to(self.cfg, "me@company.test"), "")              # 폰 주소가 아니면 안 보낸다

    def test_job_file_untouched(self):
        # 워커가 돌면서 같은 잡 파일을 고쳐 쓴다 — 여기서 쓰면 서로 덮어쓴다
        self.job("20261008-090000-bbbb", "me@gmail.test")
        path = os.path.join(self.tmp, "20261008-090000-bbbb.json")
        before = open(path, encoding="utf-8").read()
        mg.send_acks(self.cfg, "pw")
        self.assertEqual(open(path, encoding="utf-8").read(), before)

    def test_skips_company_sender_old_and_replied(self):
        self.job("20261008-090000-cccc", "me@company.test")
        self.job("20261008-090000-dddd", "me@gmail.test", created="2026-10-01 09:00:00")
        self.job("20261008-090000-eeee", "me@gmail.test", replied=True)
        self.assertEqual(mg.send_acks(self.cfg, "pw"), 0)
        self.assertEqual(self.sent, [])

    def test_smtp_reply_goes_to_phone_and_me(self):
        # 키트 기본 reply_mode=smtp — 폰 지시의 회신은 폰 주소(phone_reply_to 반영)와 내 주소(대화 앱이 읽는 메일함)로
        self.cfg["keyed_senders"] = {"me@icloud.test": "word", "me@gmail.test": "word"}
        self.cfg["phone_reply_to"] = {"me@icloud.test": "me@gmail.test"}
        self.assertEqual(mg.smtp_rcpts(self.cfg, {"mail_from": "me@icloud.test"}), ["me@gmail.test", "me@company.test"])
        self.assertEqual(mg.smtp_rcpts(self.cfg, {"mail_from": "me@gmail.test"}), ["me@gmail.test", "me@company.test"])
        self.assertIsNone(mg.smtp_rcpts(self.cfg, {"mail_from": "me@company.test"}))   # 회사 주소 지시는 메일 To 그대로


class GmailSetup(unittest.TestCase):
    """--setup-gmail 이 쓰는 dispatch.gmail 저장 · 읽기."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = (mg.kit.F_CONFIG, mg.kit.unprotect)
        mg.kit.F_CONFIG = os.path.join(self.tmp, "config.local.json")
        mg.kit.unprotect = lambda b64: "app-" + b64

    def tearDown(self):
        mg.kit.F_CONFIG, mg.kit.unprotect = self._saved

    def test_save_gmail_keeps_other_settings(self):
        with open(mg.kit.F_CONFIG, "w", encoding="utf-8") as f:
            json.dump({"mail": {"user": "me@example.com"}, "dispatch": {"enabled": True, "keyed_senders": {"me@gmail.test": "w"}}}, f)
        mg.save_gmail({"user": "me@gmail.test", "password_enc": "enc"})
        with open(mg.kit.F_CONFIG, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["mail"], {"user": "me@example.com"})          # 기본값을 채워 쓰지 않는다
        self.assertTrue(saved["dispatch"]["enabled"])
        self.assertEqual(saved["dispatch"]["gmail"]["user"], "me@gmail.test")
        acct = mg.gmail_account(mg.load_cfg())
        self.assertEqual((acct["user"], acct["password"], acct["conn"]["imap_host"]), ("me@gmail.test", "app-enc", "imap.gmail.com"))

    def test_off_when_empty(self):
        self.assertIsNone(mg.gmail_account({"gmail": {}}))
        self.assertIsNone(mg.gmail_account({"gmail": {"user": "me@gmail.test"}}))   # 비밀번호 없으면 끈 것


if __name__ == "__main__":
    unittest.main()
