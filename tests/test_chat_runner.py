# -*- coding: utf-8 -*-
"""tools/dispatch-chat/chat_runner.py(이 PC 에서 직접 실행) 시험 — 진짜 메일 서버·claude 없이 돈다.  python -X utf8 -m unittest tests.test_chat_runner

가짜 IMAP(메모리 메일함)과 가짜 claude(파이썬 스크립트 — 받은 인자·폴더·지시문을 적고 JSON 결과를 낸다)로
받기 → 실행 → 회신, 이어서 하기(--resume), 선택지 답, 쓰기 확인, 멈춤(자식 프로세스까지), 접수 신호, 막힘을 본다.
"""
import email
import email.policy
import email.utils
import imaplib
import json
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from email.message import EmailMessage
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "dispatch-chat"))
import chat  # noqa: E402
import chat_runner as runner  # noqa: E402

ME = "me@example.com"
SESSION = "11111111-2222-3333-4444-555555555555"

FAKE_CLAUDE = textwrap.dedent(r'''
    import json, os, subprocess, sys, time
    prompt = sys.stdin.buffer.read().decode("utf-8")
    mcp = None
    if "--mcp-config" in sys.argv:                 # 작업이 끝나면 지워지는 파일이라 실행 중에 읽어 둔다
        with open(sys.argv[sys.argv.index("--mcp-config") + 1], encoding="utf-8") as f:
            mcp = json.load(f)
    with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt, "mcp": mcp}, ensure_ascii=False) + "\n")
    if "SLEEP" in prompt:                          # 오래 걸리는 일 — 자식(손자) 프로세스도 하나 띄워 둔다
        c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        with open(os.environ["FAKE_CLAUDE_CHILD"], "w") as f:
            f.write(str(c.pid))
        time.sleep(60)
    if "FAIL" in prompt and not os.path.exists(os.environ["FAKE_CLAUDE_FAILED"]):   # 처음 한 번만 결과 없이 죽는다(세션도 없음)
        open(os.environ["FAKE_CLAUDE_FAILED"], "w").close()
        sys.exit(3)
    result = "끝냈습니다"
    if "ASK" in prompt:
        result += '\n\n```choices\n{"question": "다음은?", "multi": false, "options": ["더 보기", "여기서 멈춤"]}\n```'
    print(json.dumps({"type": "result", "is_error": False, "result": result, "session_id": "%s",
                      "total_cost_usd": 0.01, "duration_ms": 1200, "permission_denials": []}))
''' % SESSION)


class FakeIMAP:
    """메모리 메일함 하나(INBOX). 메일은 [uid, 원문, 들어온 시각]."""

    def __init__(self, box):
        self.box = box
        self.untagged_responses = {}

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

    def select(self, name, readonly=False):
        self.untagged_responses = {"UIDVALIDITY": [b"7"]}
        return "OK", [str(len(self.box["mails"])).encode()]

    def uid(self, cmd, *args):
        mails = self.box["mails"]
        if cmd == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u, _, _ in mails)]
        want, what, out = set(args[0].split(",")), args[1], []
        for u, raw, at in mails:
            if str(u) not in want:
                continue
            if "HEADER.FIELDS" in what:
                head = raw.split(b"\n\n", 1)[0]
                out += [(b'%d (UID %d INTERNALDATE %s BODY[HEADER.FIELDS (SUBJECT)] {%d}' % (
                    u, u, imaplib.Time2Internaldate(at).encode(), len(head)), head), b")"]
            else:
                out += [(b"%d (UID %d BODY[] {%d}" % (u, u, len(raw)), raw), b")"]
        return "OK", out

    def append(self, mailbox, flags, date, raw):
        self.box["appended"].append((flags, raw))
        add(self.box, raw)
        return "OK", [b"APPEND completed"]

    def logout(self):
        pass


def add(box, raw, at=None):
    box["uid"] += 1
    box["mails"].append([box["uid"], raw, at or time.time()])


def mail(subject, body="", sender=ME, msgid=None, reply_to=None, headers=None):
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, sender, ME
    m["Date"] = email.utils.formatdate(localtime=True)
    m["Message-ID"] = msgid or email.utils.make_msgid(domain="example.com")
    if reply_to:
        m["In-Reply-To"] = m["References"] = reply_to
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body or " ")
    return m.as_bytes(), m["Message-ID"]


def alive(pid):
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259                           # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                                   # 끝났지만 부모가 거두지 않은 좀비는 죽은 것으로 친다
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.work)
        self.box = {"mails": [], "appended": [], "uid": 0}
        self.calls = os.path.join(self.tmp, "calls.jsonl")
        fake = os.path.join(self.tmp, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_CLAUDE)
        os.environ["FAKE_CLAUDE_LOG"] = self.calls
        os.environ["FAKE_CLAUDE_CHILD"] = os.path.join(self.tmp, "child.pid")
        os.environ["FAKE_CLAUDE_FAILED"] = os.path.join(self.tmp, "failed-once")
        # 이 PC 의 진짜 설정·메일·게이트웨이와 닿지 않게 모두 바꿔 둔다
        for name, val in (("OWN_CFG", os.path.join(self.tmp, "config.json")), ("LOG_PATH", os.path.join(self.tmp, "chat.log")),
                          ("LOCALDATA", self.tmp), ("INBOX", ""), ("KIT_CFG", ""), ("KIT_HERE", False), ("JOBS_DIR", ""),
                          ("imap_connect", lambda cfg, pw: FakeIMAP(self.box)), ("password", lambda cfg: "pw")):
            self.addCleanup(setattr, chat, name, getattr(chat, name))
            setattr(chat, name, val)
        chat.write_json(chat.OWN_CFG, {"user": ME, "password_enc": "x", "imap_host": "imap.example.com"})
        self.r = runner.Runner(chat, root=os.path.join(self.tmp, "runner"))
        self.r.gateway_here = lambda: ""
        self.r.claude_cmd = lambda: [sys.executable, fake]
        self.addCleanup(setattr, chat, "RUNNER", chat.RUNNER)
        chat.RUNNER = self.r

    def turn_on(self, **extra):
        info = self.r.configure({"enabled": True, "workdir": self.work})
        self.assertTrue(info["enabled"])
        if extra:
            own = chat.read_json(chat.OWN_CFG)
            own.update(extra)
            chat.write_json(chat.OWN_CFG, own)
        time.sleep(0.01)

    def calls_made(self):
        try:
            with open(self.calls, encoding="utf-8") as f:
                return [json.loads(l) for l in f if l.strip()]
        except OSError:
            return []

    def replies(self, kind=None):
        out = [email.message_from_bytes(raw, policy=email.policy.default) for _f, raw in self.box["appended"]]
        return [m for m in out if kind is None or m["X-Dispatch-Kind"] == kind]

    def step(self):
        """메일함 한 바퀴 + 대기 작업 모두 실행(+회신)."""
        self.r.cycle()
        while self.r.run_next():
            pass

    # ---------- 받기 · 실행 · 회신

    def test_read_instruction_slash_is_not_expanded_as_skill(self):
        """읽기 지시가 '/스킬' 로 시작하면 슬래시 명령으로 펼치지 않는다 — 스킬 allowed-tools 가 쓰기를 열기 때문."""
        self.turn_on()
        add(self.box, mail("#c /연동분석 몰A", "")[0])
        self.step()
        self.assertEqual([c["prompt"] for c in self.calls_made()], [runner.SLASH_GUARD + "/연동분석 몰A"])
        self.assertIn("Skill", runner.WRITE_TOOLS)                       # 쓰기 지시는 Skill 이 있어 슬래시 명령을 그대로 둔다

    def test_runs_own_instruction_and_replies_like_gateway(self):
        self.turn_on()
        raw, mid = mail("#c 로그 봐 줘 ASK", "자세히", headers={"X-Dispatch-Client": "chat"})
        add(self.box, raw)
        self.step()
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        args = calls[0]["args"]
        self.assertEqual(os.path.normcase(calls[0]["cwd"]), os.path.normcase(self.work))
        self.assertEqual(calls[0]["prompt"], "로그 봐 줘 ASK\n\n자세히")
        self.assertIn("-p", args)
        self.assertEqual(args[args.index("--allowedTools") + 1:args.index("--allowedTools") + 4], ["Read", "Glob", "Grep"])
        self.assertNotIn("Edit", args)                                   # 읽기 지시는 읽기 도구만
        self.assertEqual(args[args.index("--permission-mode") + 1], "dontAsk")   # 허용 목록이 상한이 되게
        self.assertIn("Bash(rtk git log:*)", args)                        # rtk 훅이 다시 쓴 명령도 허용
        self.assertTrue(args[args.index("--append-system-prompt-file") + 1].endswith("chat-protocol.md"))
        self.assertEqual(self.replies("ack"), [])                         # 이 앱에서 보낸 지시엔 접수 신호가 없다
        rep = self.replies("reply")[0]
        self.assertEqual(rep["X-Dispatch"], "bot")
        self.assertEqual(rep["X-Dispatch-Thread"], "1")
        self.assertEqual(rep["In-Reply-To"], mid)
        self.assertTrue(str(rep["Subject"]).startswith("Re: #c [T1] 로그 봐 줘"))
        cfg, _ = chat.load_cfg()
        pm = chat.parse_message(rep.as_bytes(), cfg)                      # 기존 화면이 읽는 그대로
        self.assertEqual((pm["bot"], pm["thread"], pm["status"], pm["text"]), (True, 1, "done", "끝냈습니다"))
        self.assertEqual(pm["ask"]["options"], ["더 보기", "여기서 멈춤"])
        self.assertIn("이 PC 에서 실행", pm["foot"])
        # 두 번 실행하지 않는다 — 다시 돌아도, 메신저를 다시 켜도(새 Runner, 같은 상태 파일)
        self.step()
        r2 = runner.Runner(chat, root=self.r.root)
        r2.gateway_here, r2.claude_cmd = self.r.gateway_here, self.r.claude_cmd
        r2.cycle()
        self.assertFalse(r2.run_next())
        self.assertEqual(len(self.calls_made()), 1)

    def test_ignores_others_old_and_wrong_key(self):
        add(self.box, mail("#c 켜기 전에 온 지시")[0], at=time.time() - 60)
        self.turn_on(key_word="sesame")
        add(self.box, mail("#c 남이 보낸 지시 [k:sesame]", sender="evil@example.net")[0])
        add(self.box, mail("#c 단어 없음")[0])
        add(self.box, mail("#c 단어 틀림 [k:wrong]")[0])
        add(self.box, mail("#c 위조 [k:sesame]", headers={"Authentication-Results": "mx; dmarc=fail; spf=fail"})[0])
        add(self.box, mail("#c 일반 메일 아님", headers={"X-Dispatch-Mirror": "gmail"})[0])
        add(self.box, mail("회의 일정 [k:sesame]")[0])
        self.step()
        self.assertEqual(self.calls_made(), [])
        add(self.box, mail("#c 본문 단어 맞음", "할 일\n\n[k:sesame]")[0])
        self.step()
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["prompt"], "본문 단어 맞음\n\n할 일")         # 암호 단어 줄은 지시문에 안 들어간다

    def test_off_does_nothing(self):
        add(self.box, mail("#c 꺼져 있을 때")[0])
        self.step()
        self.assertEqual((self.calls_made(), self.box["appended"]), ([], []))

    # ---------- 이어서 · 선택지 · 쓰기 확인

    def test_resume_with_choice_answer(self):
        self.turn_on()
        add(self.box, mail("#c 조사 ASK")[0])
        self.step()
        rep = self.replies("reply")[0]
        add(self.box, mail("Re: #c [T1] 조사 ASK", "1\n\n2026. 10. 12. 오전 9:00, 나 <me@example.com> 작성:\n> 이전",
                           reply_to=rep["Message-ID"])[0])
        self.step()
        calls = self.calls_made()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["args"][calls[1]["args"].index("--resume") + 1], SESSION)
        self.assertEqual(calls[1]["prompt"], "사용자 답(번호 선택): ☑ 1. 더 보기")
        rep2 = self.replies("reply")[1]
        self.assertEqual(rep2["X-Dispatch-Thread"], "1")
        self.assertIn("이어서 실행", rep2.get_body(("plain",)).get_content())

    def test_retry_failed_instruction(self):
        self.turn_on()
        add(self.box, mail("#c 조사 FAIL", "자세히")[0])
        self.step()
        rep = self.replies("reply")[0]
        self.assertEqual((rep["X-Dispatch-Status"], rep["X-Dispatch-Thread"]), ("error", "1"))
        # 🔁 다시 실행 — 세션 없이 실패했어도 같은 대화 번호로, 처음 지시 그대로 다시 돈다
        add(self.box, mail("Re: #c [T1] 조사 FAIL", "다시 실행", reply_to=rep["Message-ID"])[0])
        self.step()
        calls = self.calls_made()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["prompt"], calls[0]["prompt"])
        self.assertNotIn("--resume", calls[1]["args"])
        rep2 = self.replies("reply")[1]
        self.assertEqual((rep2["X-Dispatch-Status"], rep2["X-Dispatch-Thread"]), ("done", "1"))
        self.assertEqual(sum(1 for j in self.r.iter_jobs() if j.get("retry_of")), 1)   # id 가 같은 초면 순서는 무작위
        # 잘 끝난 대화의 '다시 실행' 은 평범한 이어 말하기
        add(self.box, mail("Re: #c [T1] 조사 FAIL", "다시 실행", reply_to=rep2["Message-ID"])[0])
        self.step()
        calls = self.calls_made()
        self.assertEqual((calls[2]["prompt"], calls[2]["args"][calls[2]["args"].index("--resume") + 1]), ("다시 실행", SESSION))

    def test_write_asks_first(self):
        self.turn_on()
        add(self.box, mail("#cw 파일 고쳐 줘")[0])
        self.step()
        self.assertEqual(self.calls_made(), [])
        conf = self.replies("confirm")[0]
        self.assertEqual(conf["X-Dispatch-Thread"], "1")
        cfg, _ = chat.load_cfg()
        self.assertEqual(chat.parse_message(conf.as_bytes(), cfg)["ask"]["options"], ["실행", "취소"])
        add(self.box, mail("Re: #cw [T1] 파일 고쳐 줘", "1", reply_to=conf["Message-ID"])[0])     # 화면의 '실행' 고르기와 같은 답
        self.step()
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        self.assertIn("Edit", calls[0]["args"])
        self.assertEqual(self.replies("reply")[0]["X-Dispatch-Thread"], "1")

    # ---------- 전용 브라우저 · Jira (설정에서 켤 때만)

    def run_write(self, subject):
        """쓰기 지시 하나를 확인 답까지 해서 돌리고 그 claude 호출을 돌려준다."""
        n = len(self.replies("confirm"))
        add(self.box, mail(subject)[0])
        self.step()
        conf = self.replies("confirm")[n]
        add(self.box, mail("Re: " + subject, "1", reply_to=conf["Message-ID"])[0])
        self.step()
        return self.calls_made()[-1]

    def fake_tools(self, npx=True, browser=True, uvx=True):
        have = {"npx": npx, "uvx": uvx}
        for name, val in (("find_tool", lambda n: "/bin/" + n if have.get(n) else ""),
                          ("find_browser", lambda: ("/bin/chrome", "chrome") if browser else ("", "")),
                          ("cdp_live", lambda: False)):
            self.addCleanup(setattr, runner, name, getattr(runner, name))
            setattr(runner, name, val)

    def test_browser_off_by_default(self):
        self.turn_on()
        args = self.run_write("#cw 사이트 열어 줘")["args"]
        self.assertNotIn("mcp__browser", args)
        self.assertNotIn("--mcp-config", args)
        self.assertFalse(self.r.info()["browser"])

    def test_browser_on_adds_playwright_to_write_only(self):
        self.fake_tools()
        self.turn_on()
        self.r.configure({"enabled": True, "browser": True})
        call = self.run_write("#cw 사이트 열어 줘")
        args = call["args"]
        self.assertIn("mcp__browser", args[args.index("--allowedTools") + 1:])
        self.assertLess(args.index("--mcp-config"), args.index("-p"))        # 여러 값을 받는 --allowedTools 뒤에 섞이지 않게
        srv = call["mcp"]["mcpServers"]["browser"]
        self.assertIn(runner.PLAYWRIGHT_MCP, srv["args"])
        self.assertEqual(list(call["mcp"]["mcpServers"]), ["browser"])
        pw = srv["args"][srv["args"].index("--config") + 1]
        self.assertFalse(os.path.exists(pw))                                 # 끝나면 임시 파일을 지운다
        self.assertEqual(os.listdir(os.path.join(self.r.root, "logs")), [])
        add(self.box, mail("#c 읽기만")[0])                                   # 읽기 지시엔 붙지 않는다
        self.step()
        self.assertNotIn("--mcp-config", self.calls_made()[-1]["args"])
        runner.cdp_live = lambda: True                                       # 로그인 창이 떠 있으면 거기 붙는다
        srv = self.run_write("#cw 또 열어 줘")["mcp"]["mcpServers"]["browser"]
        self.assertEqual(srv["args"][srv["args"].index("--cdp-endpoint") + 1], runner.BROWSER_CDP)

    def test_browser_needs_npx_and_chrome(self):
        self.fake_tools(npx=False)
        self.turn_on()
        with self.assertRaises(ValueError):
            self.r.configure({"enabled": True, "browser": True})
        self.fake_tools(browser=False)
        with self.assertRaises(ValueError):
            self.r.configure({"enabled": True, "browser": True})
        self.assertFalse(self.r.info()["browser"])

    def test_jira_on_uses_jira_tools_deny_list_and_mcp(self):
        self.fake_tools()
        self.addCleanup(setattr, chat, "protect_secret", chat.protect_secret)
        self.addCleanup(setattr, chat, "unprotect_secret", chat.unprotect_secret)
        chat.protect_secret = lambda text, account="mail": "enc:" + text
        chat.unprotect_secret = lambda enc: enc[4:]
        home = os.path.join(self.tmp, "home")                                  # 이 PC 사용자 폴더의 진짜 jira 스킬을 보지 않게
        env = mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home})
        env.start()
        self.addCleanup(env.stop)
        self.turn_on()
        with self.assertRaises(ValueError):                                   # 토큰을 넣으면 주소가 있어야 한다
            self.r.configure({"enabled": True, "jira": True, "jira_token": "tok"})
        self.r.configure({"enabled": True, "jira": True, "jira_url": "https://jira.example.com/", "jira_token": "tok", "browser": True})
        self.assertTrue(self.r.info()["has_jira_token"])
        call = self.run_write("#cw /jira ABC-12")
        args = call["args"]
        allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
        self.assertEqual(allowed, runner.JIRA_TOOLS)                          # 브라우저를 켜 둬도 Jira 지시엔 안 붙는다
        self.assertIn("Bash(rtk curl:*)", args[args.index("--disallowedTools") + 1:])
        self.assertEqual(call["mcp"]["mcpServers"]["jira"]["env"],
                         {"JIRA_URL": "https://jira.example.com", "JIRA_PERSONAL_TOKEN": "tok"})
        self.assertIn("ABC-12", call["prompt"])                               # 작업 폴더에 jira 스킬이 없다 → 풀어 쓴 지시
        self.assertNotIn("/jira", call["prompt"])
        os.makedirs(os.path.join(self.work, ".claude", "skills", "jira"))
        open(os.path.join(self.work, ".claude", "skills", "jira", "SKILL.md"), "w").close()
        self.assertEqual(self.run_write("#cw /jira ABC-13")["prompt"], "/jira ABC-13")
        self.r.configure({"enabled": True, "jira_token_clear": True})        # 토큰이 없으면 이 PC 의 jira MCP 를 쓴다(붙이지 않음)
        call = self.run_write("#cw /jira ABC-14")
        self.assertNotIn("jira", (call["mcp"] or {}).get("mcpServers", {}))
        self.assertIn("mcp__jira__jira_get_issue", call["args"])

    def test_jira_other_skill_and_allow_net(self):
        """스킬 이름이 다르고(issue-task) 그 스킬이 curl 로 Jira REST 를 부르는 팀."""
        self.turn_on()
        home = os.path.join(self.tmp, "home")
        env = mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home})
        env.start()
        self.addCleanup(env.stop)
        os.makedirs(os.path.join(self.work, ".claude", "skills", "issue-task"))
        open(os.path.join(self.work, ".claude", "skills", "issue-task", "SKILL.md"), "w").close()
        with self.assertRaises(ValueError):
            self.r.configure({"enabled": True, "jira_skill": "task input; rm"})
        self.r.configure({"enabled": True, "jira": True, "jira_skill": "/issue-task", "jira_allow_net": True})
        self.assertEqual(self.r.info()["jira_skill"], "issue-task")
        call = self.run_write("#cw /jira PROJ-33175")
        self.assertEqual(call["prompt"], "/issue-task PROJ-33175")
        self.assertNotIn("--disallowedTools", call["args"])                   # curl 허용
        self.assertIn("Skill", call["args"])                                  # 다음 스킬로 이어 가기
        self.r.configure({"enabled": True, "jira_allow_net": False})
        call = self.run_write("#cw /jira PROJ-33176")
        self.assertIn("Bash(curl:*)", call["args"][call["args"].index("--disallowedTools") + 1:])

    def test_jira_url_from_company_and_mac_paths(self):
        with mock.patch.dict(chat.DEFAULTS, {"run_jira_url": "https://jira.example.com"}):     # company.json 의 jira_url
            self.assertEqual(self.r.info()["jira_url"], "https://jira.example.com")
            self.r.configure({"enabled": False, "jira_url": "https://jira.other.com"})       # 각자 바꾸면 그것
            self.assertEqual(self.r.info()["jira_url"], "https://jira.other.com")
        home = os.path.join(self.tmp, "home")
        for v in ("v9.11.2", "v20.10.0", "v18.19.1"):
            os.makedirs(os.path.join(home, ".nvm", "versions", "node", v, "bin"))
        with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
            nvm = [d for d in runner.mac_bin_dirs() if ".nvm" in d]
        self.assertIn("v20.10.0", nvm[0])                                     # nvm 은 가장 새 판부터

    def test_jira_off_is_plain_write(self):
        self.turn_on()
        args = self.run_write("#cw /jira ABC-12")["args"]
        self.assertNotIn("--disallowedTools", args)
        self.assertNotIn("mcp__jira__jira_get_issue", args)

    # ---------- 멈춤 · 접수 신호

    def test_stop_kills_tree_and_ack(self):
        self.turn_on()
        raw, mid = mail("#c 오래 걸리는 일 SLEEP")                      # 폰·메일 앱에서 온 지시(X-Dispatch-Client 없음)
        add(self.box, raw)
        self.r.cycle()
        acks = self.replies("ack")
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0]["In-Reply-To"], mid)
        self.assertIn("Seen", self.box["appended"][0][0])
        worker = threading.Thread(target=self.r.run_next)
        worker.start()
        child_pid = os.environ["FAKE_CLAUDE_CHILD"]
        for _ in range(100):
            if os.path.isfile(child_pid) and os.path.getsize(child_pid):
                break
            time.sleep(0.1)
        with open(child_pid) as f:
            pid = int(f.read())
        self.assertTrue(alive(pid))
        add(self.box, mail("Re: #c 오래 걸리는 일 SLEEP", "멈춤", reply_to=mid)[0])
        t0 = time.time()
        self.r.cycle()
        worker.join(30)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.time() - t0, 20)
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.1)
        self.assertFalse(alive(pid), "claude 의 자식 프로세스도 끝나야 한다")
        rep = self.replies("reply")[0]
        self.assertIn("멈췄습니다", rep.get_body(("plain",)).get_content())
        # 화면: 접수 신호는 말풍선이 아니고, 회신 전이면 '대기' 로 보인다
        cfg, _ = chat.load_cfg()
        msgs = [chat.parse_message(raw, cfg), chat.parse_message(acks[0].as_bytes(), cfg)]
        t = chat.build_threads(msgs)[0]
        self.assertEqual((len(t["msgs"]), t["status"]), (1, "queued"))

    def test_stop_before_instruction(self):
        self.turn_on()
        raw, mid = mail("#c 늦게 도착한 지시")
        add(self.box, mail("Re: #c 늦게 도착한 지시", "멈춤", reply_to=mid)[0])
        self.step()
        add(self.box, raw)
        self.step()
        self.assertEqual(self.calls_made(), [])
        self.assertIn("시작하기 전에", self.replies("reply")[0].get_body(("plain",)).get_content())

    def test_daily_cost_limit_blocks_new_instruction(self):
        """하루 비용 한도(daily_cost_usd)에 닿으면 새 지시는 실행하지 않고 이유만 회신 — 0 이면 없음."""
        self.turn_on(daily_cost_usd=1)
        self.r.write_job({"id": "20261014-080000-aaaa", "created_at": runner.now_text(), "status": "done", "replied": True,
                          "cost_usd": 1.25, "workdir": self.work, "mail_subject": "#c 앞선 일"})
        self.assertEqual(runner.spent_today(self.r.jobs_dir), 1.25)
        add(self.box, mail("#c 오늘 일 하나 더", "")[0])
        self.step()
        self.assertEqual(self.calls_made(), [])                                  # claude 를 부르지 않았다
        rep = self.replies("reply")[-1]
        self.assertEqual(rep["X-Dispatch-Status"], "error")
        self.assertIn("하루 한도($1.00)", rep.get_body(("plain",)).get_content())
        self.assertEqual(self.r.info()["cost"], 1.0)
        with self.assertRaises(ValueError):
            self.r.configure({"cost": "다섯"})

    def test_unanswered_question_closes_once(self):
        """선택지로 물은 뒤 하루 넘게 답이 없으면 질문을 닫는 알림 1통(선택지 없음) — 답이 와서 다음 작업이 있거나 일주일 넘은 것은 빼고."""
        self.turn_on()
        ago = lambda h: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - h * 3600))
        ask = {"question": "어느 쪽?", "multi": False, "options": ["A", "B"]}
        base = {"source": "mail", "status": "done", "replied": True, "workdir": self.work, "prompt": "일", "mail_subject": "#c 일",
                "ask": ask, "acked": True}
        self.r.write_job(dict(base, id="20261013-01-a", thread=1, mail_msgid="<a@x>", finished_at=ago(25)))   # 닫힌다
        self.r.write_job(dict(base, id="20261013-02-b", thread=2, mail_msgid="<b@x>", finished_at=ago(26)))   # 답이 왔다 ↓
        self.r.write_job(dict(base, id="20261013-03-c", thread=2, mail_msgid="<c@x>", finished_at=ago(25), ask=None))
        self.r.write_job(dict(base, id="20261013-04-d", thread=3, mail_msgid="<d@x>", finished_at=ago(5)))    # 아직
        self.r.write_job(dict(base, id="20261001-05-e", thread=4, mail_msgid="<e@x>", finished_at=ago(24 * 9)))  # 너무 오래됨
        cfg, _ = chat.load_cfg()
        # 처음 켤 때 — 이미 기한이 지난 질문은 알림 없이 닫힌 것으로만(업데이트 직후 몰아 보내지 않게)
        self.r.send_out(cfg)
        self.assertEqual(self.replies("closed"), [])
        self.assertTrue(self.r.read_job("20261013-01-a").get("ask_closed"))
        # 그 뒤로는 기한이 지나면 알린다
        self.r.update_job("20261013-01-a", ask_closed=False)
        self.r.send_out(cfg)
        closed = self.replies("closed")
        self.assertEqual([m["In-Reply-To"] for m in closed], ["<a@x>"])
        self.assertIsNone(closed[0]["X-Dispatch-Ask"])
        self.assertIn("[T1]", closed[0].get_content())
        self.r.send_out(cfg)
        self.assertEqual(len(self.replies("closed")), 1)                       # 한 번만
        self.assertEqual(self.r.due_asks(dict(cfg, ask_ttl_hours=0))[1], [])

    def test_progress_mail_once_for_long_phone_job(self):
        """몇 분 넘게 도는 폰·메일 앱 지시에 진행 메일 1통(읽음 표시로) — 게이트웨이 send_progress 와 같은 형식. 답으로 안 센다."""
        self.turn_on()
        self.addCleanup(setattr, chat, "CLAUDE_PROJECTS", chat.CLAUDE_PROJECTS)
        chat.CLAUDE_PROJECTS = os.path.join(self.tmp, "projects")                # 세션 기록 없음 → '진행 중 · N분째' 만
        ago = lambda m: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - m * 60))
        base = {"source": "mail", "status": "running", "workdir": self.work, "prompt": "오래 걸리는 일", "acked": True,
                "mail_subject": "#c 오래 걸리는 일", "created_at": ago(5), "started_at": ago(5)}
        self.r.write_job(dict(base, id="j-phone", mail_msgid="<p@x>"))
        self.r.write_job(dict(base, id="j-chat", mail_msgid="<c@x>", client="chat"))          # 이 앱에서 보낸 지시 — 진행 카드가 있다
        self.r.write_job(dict(base, id="j-young", mail_msgid="<y@x>", started_at=ago(1)))     # 아직 3분 전
        self.r.write_job(dict(base, id="j-done", mail_msgid="<d@x>", status="done"))          # 회신 전에 끝남
        cfg, _ = chat.load_cfg()
        self.r.send_out(cfg)
        prog = self.replies("progress")
        self.assertEqual(len(prog), 1)
        self.assertEqual(prog[0]["In-Reply-To"], "<p@x>")
        self.assertEqual(prog[0]["Subject"], "Re: #c 오래 걸리는 일")
        self.assertEqual(prog[0]["X-Dispatch-Runner"], cfg["run_id"])
        self.assertEqual(prog[0].get_content().strip(), "진행 중 · 5분째")
        flags = [f for f, raw in self.box["appended"] if b"X-Dispatch-Kind: progress" in raw]
        self.assertEqual(len(flags), 1)
        self.assertIn("Seen", flags[0])                                       # 안 읽음으로 쌓이지 않게
        self.r.send_out(cfg)
        self.r.cleaned = True                                                 # (손으로 만든 running 작업을 고아로 치우지 않게)
        self.r.cycle()                                                        # 자기 진행 메일을 '다른 실행기' 로 보지 않는다
        self.assertEqual(len(self.replies("progress")), 1)                    # 잡당 딱 1통
        self.assertTrue(self.r.info()["enabled"])
        cfg["progress_after_min"] = 0                                         # 0 이면 끈다
        self.r.write_job(dict(base, id="j-off", mail_msgid="<o@x>"))
        self.r.send_out(cfg)
        self.assertEqual(len(self.replies("progress")), 1)
        # 화면: 진행 메일은 답이 아니다 — 내 말 하나 + '작업 중' + 회색 한 줄
        raw, _ = mail("#c 오래 걸리는 일", msgid="<p@x>")
        msgs = [chat.parse_message(raw, cfg), chat.parse_message(prog[0].as_bytes(), cfg)]
        t = chat.build_threads(msgs)[0]
        self.assertEqual((len(t["msgs"]), t["status"], t["progress"]), (1, "running", "진행 중 · 5분째"))

    def test_progress_ask_answers_right_away(self):
        """돌고 있는 폰·메일 앱 지시에 '진행?' — 새 작업 없이 진행 한 줄을 바로(3분 기다리지 않는다). 시작 전이면 앞에 몇 개.
        PC 대화 앱(client=chat)의 '진행?' 은 평소대로 이어 말하기, '멈춤' 은 그대로 멈춤."""
        self.turn_on()
        self.r.cleaned = True                                                 # (손으로 만든 running 작업을 고아로 치우지 않게)
        self.addCleanup(setattr, chat, "CLAUDE_PROJECTS", chat.CLAUDE_PROJECTS)
        chat.CLAUDE_PROJECTS = os.path.join(self.tmp, "projects")
        ago = lambda m: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - m * 60))
        base = {"source": "mail", "workdir": self.work, "prompt": "오래 걸리는 일", "acked": True, "session_id": "s-1",
                "mail_subject": "#c [T5] 오래 걸리는 일", "created_at": ago(1)}
        self.r.write_job(dict(base, id="20261016-01-run", status="running", thread=5, mail_msgid="<r@x>", started_at=ago(1)))
        self.r.write_job(dict(base, id="20261016-02-wait", status="queued", thread=6, mail_msgid="<w@x>",
                              mail_subject="#c [T6] 다음 일"))
        add(self.box, mail("Re: #c [T5] 오래 걸리는 일", "진행?", reply_to="<r@x>")[0])
        add(self.box, mail("Re: #c [T6] 다음 일", "지금 뭐 해", reply_to="<w@x>")[0])
        self.r.cycle()
        prog = sorted(self.replies("progress"), key=lambda m: m["In-Reply-To"])
        self.assertEqual([(m["In-Reply-To"], m.get_content().strip()) for m in prog],
                         [("<r@x>", "진행 중 · 1분째"), ("<w@x>", "아직 시작 전 · 앞에 1개")])
        self.assertEqual(len(self.r.iter_jobs()), 2)                         # 새 작업을 만들지 않았다
        self.assertIsNone(self.r.read_job("20261016-01-run").get("progress_ask"))
        self.r.cycle()
        self.assertEqual(len(self.replies("progress")), 2)                   # 한 번 묻고 한 번 답
        # PC 대화 앱에서 보낸 '진행?' 은 평소대로(이어 말하기 작업), '멈춤' 은 멈춤 요청 — 진행 물음과 안 섞인다
        add(self.box, mail("Re: #c [T5] 오래 걸리는 일", "멈춤", reply_to="<r@x>")[0])
        add(self.box, mail("Re: #c [T5] 오래 걸리는 일", "진행", reply_to="<r@x>", headers={"X-Dispatch-Client": "chat"})[0])
        self.r.cycle()
        self.assertEqual(len(self.replies("progress")), 2)
        self.assertTrue(self.r.read_job("20261016-01-run").get("stop_requested"))
        self.assertEqual(len(self.r.iter_jobs()), 3)
        # 묵은 물음(10분 넘음)은 답하지 않고 버린다
        self.r.update_job("20261016-01-run", progress_ask=time.time() - 900)
        cfg, _ = chat.load_cfg()
        self.r.send_out(cfg)
        self.assertEqual(len(self.replies("progress")), 2)
        self.assertIsNone(self.r.read_job("20261016-01-run").get("progress_ask"))

    def test_progress_words(self):
        for w in ("진행", "진행?", " 진행 상황 ", "지금 뭐 해?", "Status"):
            self.assertTrue(runner.is_progress_ask(w), w)
        for w in ("진행해", "진행해 줘", "1", "로그 진행 상황도 봐줘"):
            self.assertFalse(runner.is_progress_ask(w), w)

    # ---------- 막힘 · 겹침

    def test_blocked_on_gateway_pc(self):
        self.r.gateway_here = lambda: r"C:\gw"
        with self.assertRaises(ValueError):
            self.r.configure({"enabled": True, "workdir": self.work})
        own = chat.read_json(chat.OWN_CFG)
        own.update(run_here=True, run_since=time.time() - 5, run_workdir=self.work)      # 설정 파일을 손으로 켜 둬도
        chat.write_json(chat.OWN_CFG, own)
        add(self.box, mail("#c 게이트웨이 PC 에서")[0])
        self.step()
        self.assertEqual((self.calls_made(), self.box["appended"]), ([], []))
        self.assertIn("게이트웨이", self.r.summary()["error"])

    def test_gateway_account_and_no_claude(self):
        self.assertIn("게이트웨이", self.r.blocked({"user": ME, "password_enc": "x"}, "kit"))
        self.r.claude_cmd = lambda: None
        with self.assertRaises(ValueError) as e:
            self.r.configure({"enabled": True, "workdir": self.work})
        self.assertIn("Claude Code", str(e.exception))
        self.assertFalse(self.r.info()["enabled"])

    def test_other_executor_turns_off(self):
        self.turn_on()
        raw, mid = mail("Re: #c [T9] 남의 회신", "게이트웨이가 답함", headers={"X-Dispatch": "bot", "X-Dispatch-Thread": "9"})
        add(self.box, raw)
        add(self.box, mail("#c 이건 실행되면 안 됨")[0])
        self.step()
        self.assertEqual(self.calls_made(), [])
        info = self.r.info()
        self.assertFalse(info["enabled"])
        self.assertIn("다른 PC", info["notice"])

    def test_parse_dirs(self):
        self.assertEqual(runner.parse_dirs("web = %s\n\n" % self.work), {"web": os.path.abspath(self.work)})
        with self.assertRaises(ValueError):
            runner.parse_dirs("그냥 폴더")
        with self.assertRaises(ValueError):
            runner.parse_dirs("x=%s" % os.path.join(self.tmp, "없음"))


if __name__ == "__main__":
    unittest.main()
