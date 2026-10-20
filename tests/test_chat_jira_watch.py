# -*- coding: utf-8 -*-
"""tools/dispatch-chat/jira_watch.py(대화 앱의 Jira 새 티켓 감시) 시험 — 진짜 Jira·메일·claude 없이 돈다.

Jira 조회(http_get_json)는 가짜 응답으로 바꿔 끼우고, 작업은 임시 폴더(실행기 큐)에만 쓴다.
처음 켜기(seed) · 자리비움 꺼짐(처리됨으로만) · 자리비움 켜짐(이 PC 에서 직접 실행 큐) · 게이트웨이 PC(키트)에선 막힘 · 로그를 본다.
(키트 저장소 맨 위 jira-watch.py 의 시험은 test_jira_watch.py)
"""
import email
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "dispatch-chat"))
import chat  # noqa: E402
import chat_runner as runner  # noqa: E402
import jira_watch as jw  # noqa: E402
from test_chat_runner import FAKE_CLAUDE, FakeIMAP, ME, add, mail  # noqa: E402

URL = "https://jira.example.com"


def issue(n, summary=None, account="", link=""):
    desc = ("*발생환경*\n* 계정 : %s\n" % account) if account else "내용"
    links = [{"outwardIssue": {"fields": {"summary": link}}}] if link else []
    return {"key": "PROJ-%d" % n, "fields": {"summary": summary or "티켓 %d" % n, "created": "2026-10-14T09:00:00.000+0900",
                                             "status": {"name": "접수"}, "reporter": {"name": "u", "displayName": "사람"},
                                             "description": desc, "issuelinks": links}}


class FakeJira:
    def __init__(self):
        self.issues, self.calls, self.fail = [], [], None

    def __call__(self, url, token, ca=None):
        self.calls.append((url, token))
        if self.fail:
            raise self.fail
        return {"issues": list(self.issues)}


class JiraWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(os.path.join(self.work, ".claude", "skills", "jira"))
        open(os.path.join(self.work, ".claude", "skills", "jira", "SKILL.md"), "w").close()
        self.box = {"mails": [], "appended": [], "uid": 0}
        fake = os.path.join(self.tmp, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_CLAUDE)
        for k in ("FAKE_CLAUDE_LOG", "FAKE_CLAUDE_CHILD", "FAKE_CLAUDE_FAILED"):
            self.addCleanup(os.environ.pop, k, None)
            os.environ[k] = os.path.join(self.tmp, k.lower())
        for name, val in (("OWN_CFG", os.path.join(self.tmp, "config.json")), ("LOG_PATH", os.path.join(self.tmp, "chat.log")),
                          ("LOCALDATA", self.tmp), ("INBOX", ""), ("KIT_CFG", ""), ("KIT_HERE", False), ("JOBS_DIR", ""),
                          ("imap_connect", lambda cfg, pw: FakeIMAP(self.box)), ("password", lambda cfg: "pw")):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
            setattr(chat, name, val)
        # 회사 값(company.json)이 섞이지 않게 — 제외 규칙은 이 시험의 설정에서만
        d = mock.patch.dict(chat.DEFAULTS, {"run_jira_url": "", "jira_watch_exclude_account": "", "jira_watch_exclude_linked": ""})
        d.start()
        self.addCleanup(d.stop)
        chat.write_json(chat.OWN_CFG, {"user": ME, "password_enc": "x", "imap_host": "imap.example.com",
                                       "run_jira_url": URL, "jira_prefix": "PROJ-",
                                       "jira_watch_exclude_account": "(?i)qc", "jira_watch_exclude_linked": "외부 요청"})
        self.r = runner.Runner(chat, root=os.path.join(self.tmp, "runner"))
        self.gw = ""
        self.r.gateway_here = lambda: self.gw
        self.r.claude_cmd = lambda: [sys.executable, fake]
        self.w = self.r.jira
        self.jira = FakeJira()
        p = mock.patch.object(jw, "http_get_json", self.jira)
        p.start()
        self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {"JIRA_TOKEN": "tok-env"})
        e.start()
        self.addCleanup(e.stop)

    # ---------- 도움

    def own(self, **kw):
        own = chat.read_json(chat.OWN_CFG)
        own.update(kw)
        chat.write_json(chat.OWN_CFG, own)

    def poll(self):
        cfg, src = chat.load_cfg()
        return self.w.poll(cfg, src)

    def run_here(self):
        """이 PC 에서 직접 실행을 켠다 — 자리비움 중 새 티켓이 들어갈 곳(실행기 큐)."""
        self.r.configure({"enabled": True, "workdir": self.work})
        time.sleep(0.01)
        return self.r.jobs_dir

    def here_jobs(self):
        return [j for j in self.r.iter_jobs()] if os.path.isdir(self.r.jobs_dir) else []

    def log_text(self):
        try:
            with open(chat.LOG_PATH, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def enable(self, **extra):
        return self.w.configure(dict({"enabled": True}, **extra))

    # ---------- 규칙 · 조회

    def test_rules_and_jql(self):
        cfg, _ = chat.load_cfg()
        rules = jw.rules_of(cfg)
        self.assertEqual((rules["project"], rules["assignee"], rules["days"], rules["max"]), ("PROJ", "", 3, 3))
        jql = jw.build_jql(rules, today=datetime(2026, 10, 14))
        self.assertEqual(jql, 'project = "PROJ" AND assignee = currentUser() AND created >= "2026-10-11" ORDER BY created ASC')
        rules.update(assignee="someone", project="")
        self.assertEqual(jw.build_jql(rules, today=datetime(2026, 10, 14)),
                         'assignee = "someone" AND created >= "2026-10-11" ORDER BY created ASC')
        self.assertEqual(jw.rules_of({"jira_watch_ignore": "PROJ-34097, 34102"})["ignore"], ["34097", "34102"])

    def test_code_defaults_have_no_company_rules(self):
        """회사 전용 제외 규칙은 company.json 에만 — 코드 기본값은 비어 있다(상용 배포판은 어느 회사든 쓴다)."""
        with open(chat.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"jira_watch_exclude_account": "", "jira_watch_exclude_linked": ""', src)
        self.assertNotIn("qc", src.split("DEFAULTS = {", 1)[1].split("}", 1)[0].lower())

    def test_skip_reasons(self):
        rules = {"exclude_account": "(?i)qc", "exclude_linked": "외부 요청"}
        self.jira.issues = [issue(1, account="teamqc01"), issue(2, link="거래처 외부 요청 - A"), issue(3, account="user01")]
        got = jw.jira_search(URL, "t", "jql")
        self.assertEqual([jw.skip_reason(i, rules) for i in got], ["제외(계정)", "제외(연결 이슈)", None])
        self.assertEqual(got[0]["account"], "teamqc01")
        self.assertIn("/rest/api/2/search?", self.jira.calls[0][0])

    # ---------- 처음 켜기 · 자리비움 꺼짐

    def test_first_poll_only_seeds(self):
        self.jira.issues = [issue(1), issue(2)]
        self.run_here()
        self.enable(away=True)
        r = self.w.tick()
        self.assertEqual(r["seeded"], ["PROJ-1", "PROJ-2"])
        self.assertEqual(self.here_jobs(), [])                             # 자리비움이 켜져 있어도 처음 본 건은 실행하지 않는다
        self.assertEqual(self.jira.calls[0][1], "tok-env")                 # 토큰이 없으면 환경변수 JIRA_TOKEN
        self.jira.issues.append(issue(3))
        self.w.force = True
        r = self.w.tick()
        self.assertEqual(r["queued"], ["PROJ-3"])

    def test_away_off_records_without_running(self):
        self.run_here()
        self.enable()
        self.w.tick()                                                      # seed(빈 것)
        self.jira.issues = [issue(5, "주문 수집 오류"), issue(6, account="qcuser")]
        r = self.poll()
        self.assertEqual((r["queued"], r["away_skipped"], r["qc_skipped"]), ([], ["PROJ-5"], 1))
        self.assertEqual(self.here_jobs(), [])
        s = self.w.summary()
        self.assertEqual([n["key"] for n in s["note"]], ["PROJ-5"])         # 화면에 '새 티켓 N건 — 직접 처리' 알림만
        # 나중에 자리비움을 켜도 몰려 실행되지 않는다
        self.w.configure({"away": True})
        r = self.poll()
        self.assertEqual(r["queued"], [])
        self.assertEqual(self.here_jobs(), [])
        self.w.configure({"dismiss": True})
        self.assertEqual(self.w.summary()["note"], [])

    # ---------- 자리비움 켜짐 · 게이트웨이 PC 에선 막힘

    def test_blocked_on_kit_gateway_pc(self):
        """게이트웨이 PC(키트 설정의 계정 · 키트 게이트웨이 켜짐)에선 키트 jira-watch.py 가 맡는다 — 켜지 않고, 켜져 있던 것도 돌지 않는다."""
        self.enable(away=True)                                             # 직접 실행 PC 에서 켜 둔 설정
        self.gw = os.path.join(self.tmp, "kit")                            # 이 저장소의 키트 게이트웨이가 켜짐
        self.jira.issues = [issue(1)]
        self.w.force = True
        self.assertIsNone(self.w.tick())
        self.assertEqual(self.jira.calls, [])                              # Jira 를 보지도 않는다
        info = self.w.info()
        self.assertIn("jira-watch.py", info["blocked"])
        self.assertEqual(info["where"], "")
        self.assertEqual(self.w.summary(), {"on": False, "away": False, "blocked": info["blocked"]})
        with self.assertRaises(ValueError):
            self.w.configure({"enabled": True})
        with self.assertRaises(ValueError):
            self.w.configure({"away": True})
        self.w.configure({"enabled": False, "away": False})               # 끄는 것은 된다
        # 키트 설정의 계정을 쓰는 메신저(출처 kit)도 같다
        self.gw = ""
        kit_cfg = os.path.join(self.tmp, "config.local.json")
        chat.write_json(kit_cfg, {"mail": {"user": ME, "password_enc": "x", "imap_host": "imap.example.com"}, "dispatch": {}})
        chat.write_json(chat.OWN_CFG, {"run_jira_url": URL})
        with mock.patch.object(chat, "KIT_CFG", kit_cfg):
            cfg, src = chat.load_cfg()
            self.assertEqual(src, "kit")
            self.assertTrue(self.w.blocked(cfg, src))
            with self.assertRaises(ValueError):
                self.enable()

    def test_away_on_here_runs_in_messenger_queue(self):
        self.r.configure({"enabled": True, "workdir": self.work})          # 이 PC 에서 직접 실행
        time.sleep(0.01)
        self.enable(away=True)
        self.w.tick()
        self.jira.issues = [issue(21, "재고 연동 확인")]
        r = self.poll()
        self.assertEqual(r["queued"], ["PROJ-21"])
        j = self.r.iter_jobs()[0]
        self.assertEqual((j["status"], j["mode"], j["prompt"].split("\n")[0], j["workdir"]), ("queued", "write", "/jira PROJ-21", self.work))
        # 자리비움 — 분석·수정안까지만: 파일 도구 없이·git 바꾸기 막고, 사람이 답하면 평소 권한(after_*)으로
        self.assertIn(jw.AWAY_NOTE, j["prompt"])
        self.assertEqual(j["allowed_tools"], [t for t in runner.JIRA_TOOLS if t not in ("Write", "Edit")])
        self.assertEqual(j["disallowed_tools"], runner.JIRA_DENY + jw.AWAY_DENY)
        self.assertIn("Bash(git push:*)", j["disallowed_tools"])
        self.assertEqual((j["after_tools"], j["after_disallowed"]), (runner.JIRA_TOOLS, runner.JIRA_DENY))
        self.assertTrue(j["mail_subject"].startswith("#cw [Jira 자동화] PROJ-21"))
        # 실행 → 회신(접수 신호·확인 없이). 답장으로 이어 말하면 같은 대화로 이어진다
        while self.r.run_next():
            pass
        self.assertEqual([m for m in self.box["appended"] if b"X-Dispatch-Kind: ack" in m[1]], [])
        self.assertEqual([m for m in self.box["appended"] if b"X-Dispatch-Kind: confirm" in m[1]], [])
        raw = self.box["appended"][-1][1]
        rep = chat.parse_message(raw, chat.load_cfg()[0])
        self.assertEqual((rep["bot"], rep["thread"], rep["status"]), (True, 1, "done"))
        subj = chat.decode_hdr(email.message_from_bytes(raw).get("Subject"))
        self.assertTrue(subj.startswith("Re: #cw [T1] [Jira 자동화] PROJ-21"), subj)   # 답장하면 쓰기 지시로 같은 대화가 이어진다
        with open(os.environ["FAKE_CLAUDE_LOG"], encoding="utf-8") as f:
            call = json.loads(f.readline())
        self.assertIn("--disallowedTools", call["args"])
        self.assertEqual(os.path.normcase(call["cwd"]), os.path.normcase(self.work))
        # 돌아온 사람이 답하면 — 그때부터 평소 Jira 권한(파일 도구 · git 허용)으로 이어 간다
        add(self.box, mail(subj, "1 적용해 줘", reply_to=email.message_from_bytes(raw)["Message-ID"])[0])
        self.r.cycle()
        (nxt,) = [x for x in self.r.iter_jobs() if x.get("resume_id")]
        self.assertEqual((nxt["allowed_tools"], nxt["disallowed_tools"]), (runner.JIRA_TOOLS, runner.JIRA_DENY))
        self.assertFalse(nxt.get("away"))

    def test_cost_limit_stops_queueing(self):
        """하루 비용 한도에 닿으면 자리비움이어도 넣지 않고 처리됨으로만 + 이유 알림 — 이 PC 의 작업 큐·설정으로 센다."""
        jobs = self.run_here()
        today = datetime.now().strftime("%Y-%m-%d")
        os.makedirs(jobs, exist_ok=True)
        chat.write_json(os.path.join(jobs, "old.json"), {"id": "old", "created_at": today + " 08:00:00", "cost_usd": 1.2, "status": "done"})
        self.own(daily_cost_usd=1)
        self.enable(away=True)
        self.w.tick()
        self.jira.issues = [issue(40), issue(41)]
        r = self.poll()
        self.assertEqual((r["queued"], r["cost_skipped"]), ([], ["PROJ-40", "PROJ-41"]))
        self.assertEqual([j["id"] for j in self.here_jobs()], ["old"])
        info = self.w.info()
        self.assertEqual([(n["key"], n.get("why")) for n in info["note"]], [("PROJ-40", "비용 한도"), ("PROJ-41", "비용 한도")])
        self.assertIn("하루 한도($1.00)", self.log_text())
        self.assertEqual(self.poll()["cost_skipped"], [])                  # 같은 티켓을 다음에 다시 넣지 않는다

    def test_away_on_without_target_keeps_tickets(self):
        """직접 실행이 꺼져 있으면 실패로 적고 티켓은 처리됨으로 넣지 않는다(실행할 곳이 생기면 그때)."""
        self.enable(away=True)
        self.w.tick()
        self.jira.issues = [issue(30)]
        self.w.force = True
        self.assertIsNone(self.w.tick())
        info = self.w.info()
        self.assertIn("작업을 넣을 곳이 없습니다", info["error"])
        self.assertNotIn("PROJ-30", self.w.state()["processed"])
        self.assertEqual(self.w.summary()["error"], info["error"])

    def test_ignore_keys_and_dry_run(self):
        self.run_here()
        self.enable(away=True, ignore="34001")
        self.w.tick()
        self.jira.issues = [{**issue(1), "key": "PROJ-34001"}, issue(2)]
        cfg, src = chat.load_cfg()
        r = self.w.poll(cfg, src, dry=True)
        self.assertEqual(r["fresh"], ["PROJ-2"])
        self.assertEqual(self.here_jobs(), [])
        self.assertNotIn("PROJ-2", self.w.state()["processed"])          # dry-run 은 아무것도 바꾸지 않는다
        self.assertEqual(self.poll()["queued"], ["PROJ-2"])

    # ---------- 켜기 · 로그

    def test_enable_needs_url_and_token(self):
        self.own(run_jira_url="")
        with mock.patch.dict(os.environ, {"JIRA_TOKEN": ""}):
            with self.assertRaises(ValueError):
                self.enable()
            self.own(run_jira_url=URL)
            with self.assertRaises(ValueError):
                self.enable()
        self.assertTrue(self.enable()["enabled"])

    def test_away_toggle_is_logged(self):
        self.enable()
        self.w.configure({"away": True})
        self.w.configure({"away": True})                                   # 같은 값은 다시 적지 않는다
        self.w.configure({"away": False})
        log = self.log_text()
        self.assertEqual(log.count("자리비움 켬"), 1)
        self.assertEqual(log.count("자리비움 끔"), 1)
        self.assertFalse(chat.read_json(chat.OWN_CFG)["jira_away"])

    def test_error_is_recorded_once_and_retried(self):
        self.enable()
        self.jira.fail = OSError("연결 끊김")
        self.assertIsNone(self.w.tick())
        self.w.force = True
        self.assertIsNone(self.w.tick())
        self.assertIn("연결 끊김", self.w.info()["error"])
        self.assertEqual(self.log_text().count("확인 실패"), 1)
        self.jira.fail = None
        self.w.force = True
        self.assertIsNotNone(self.w.tick())
        self.assertEqual(self.w.info()["error"], "")

    def test_off_does_nothing(self):
        self.assertIsNone(self.w.tick())
        self.assertEqual(self.jira.calls, [])
        self.assertFalse(self.w.summary()["on"])


if __name__ == "__main__":
    unittest.main()
