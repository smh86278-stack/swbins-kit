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

    def __init__(self, mails, appended):
        self.mails = mails            # {uid(str): 원문 bytes}
        self.appended = appended      # append() 로 들어온 메일 원문 bytes 목록

    def select(self, box):
        return "OK", [b""]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            return "OK", [" ".join(self.mails).encode()]
        if cmd == "FETCH":
            raw = self.mails[args[0]]
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
                                                    "imap_connect", "resolve_folders", "notify")}
        mg.JOBS = self.jobs
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


if __name__ == "__main__":
    unittest.main()
