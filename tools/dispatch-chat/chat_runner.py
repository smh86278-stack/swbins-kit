# -*- coding: utf-8 -*-
"""
이 PC 에서 직접 실행 — 디스패치 대화 앱 안에 넣은 '받기 + 실행'. 설정 화면(⚙)의 스위치로 켜고, 기본은 꺼져 있다.

켜면 메신저가 내 메일함에 들어온 지시(#c 읽기 · #cw 쓰기 — 메일 게이트웨이가 알아보는 형식 그대로)를
이 PC 의 Claude Code(claude -p)로 실행하고, 답을 같은 메일함에 넣는다(IMAP 으로 받은편지함에 써 넣기).
답은 게이트웨이 회신과 같은 제목('Re: #c [T12] …')·머리글(X-Dispatch-*)·선택지(```choices) 형식이라
PC 화면·폰 페이지가 그대로 보여 준다. 게이트웨이(mail-gateway.py) + 워커(inbox-worker.ps1) 가 하던 일을
파이썬 하나로 한다 — 윈도우·맥, PowerShell 없이.

안전
- 지시는 그 계정 자신의 주소에서 온 것만. 설정에 암호 단어가 있으면 제목 끝/본문 줄 [k:단어] 가 맞아야 한다(compare_digest).
  남이 보낸 메일은 실행하지 않는다. 서버가 붙인 발신 인증(Authentication-Results)이 실패면 그것도 버린다.
- 스위치를 켠 시각 이후에 메일함에 들어온 메일만. 처리한 메일은 상태 파일(state.json)에 적어 두 번 돌리지 않는다.
- 게이트웨이 PC(메신저가 키트 공통 설정의 계정을 쓰는 중이거나, 이 키트 저장소의 메일 게이트웨이가 켜진 PC)에서는 켜지지 않는다.
  켠 뒤 메일함에 다른 실행기(게이트웨이 등)의 회신이 보이면 스스로 끈다 — 같은 지시를 두 군데서 실행하지 않게.
- 쓰기(#cw) 새 지시는 실행 전에 확인을 한 번 묻는다(게이트웨이와 같다). 읽기 지시는 읽기 도구만.
- claude 와 그 자식 프로세스는 한 묶음으로 끊는다(윈도우 작업 개체 · 맥 프로세스 그룹). 메신저가 꺼지면 같이 끝난다(윈도우).

상태: 앱 데이터 폴더의 runner/ — state.json(처리한 메일·대화 번호·먼저 온 멈춤), jobs/(작업 파일, 게이트웨이 inbox/jobs 와
같은 모양이라 진행 카드가 그대로 읽는다), attachments/(폰이 보낸 사진, 7일 뒤 지움), logs/(실행 중 임시 파일).
"""
import base64
import email
import email.utils
import hmac
import imaplib
import json
import os
import random
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from html import escape as html_escape
from urllib.parse import quote

import jira_watch

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# 읽기 지시(#c)는 읽기 도구만, 쓰기 지시(#cw)는 고치기·명령까지 — 게이트웨이·워커 기본값과 같다(브라우저는 설정에서 켤 때만)
READ_TOOLS = ["Read", "Glob", "Grep", "Bash(git log:*)", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git show:*)"]
WRITE_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "NotebookEdit", "Bash", "Skill", "WebFetch", "WebSearch"]
# claude -p 는 --permission-mode dontAsk 로 돌린다 — 그래야 위 목록이 상한이 된다. 전역 설정이 auto 모드면 목록 밖 도구도
# 통과한다(2026-10-14 실측). 읽기 지시가 '/' 로 시작하면 슬래시 명령으로 펼치지 않는다 — 스킬의 allowed-tools 가
# 목록을 넘어 Write·Bash 를 연다(거부 목록 말고는 못 막는다). Skill 이 있는 잡(쓰기·Jira)만 슬래시 명령을 그대로 둔다.
SLASH_GUARD = "메일 지시: "

# 전용 브라우저(설정 run_browser, 기본 꺼짐) — 쓰기 지시에 Playwright MCP. 워커와 같은 이름(mcp__browser__*)·같은 판
BROWSER_TOOL = "mcp__browser"
PLAYWRIGHT_MCP = "@playwright/mcp@0.0.83"
BROWSER_CDP = "http://127.0.0.1:9333"   # 로그인 창(이 포트로 연다)이 떠 있으면 새로 띄우지 않고 거기 붙는다

# Jira 처리(설정 run_jira, 기본 꺼짐) — '#cw /jira 키' 를 Jira 도구·거부 목록으로, 설정의 스킬(run_jira_skill)에 넘긴다.
# 거부 목록은 밖으로 내보내는 명령(앞부분 일치라 python -c 같은 우회까지 막지는 못한다). rtk 훅이 'rtk <명령>' 으로 바꿔 쓰므로 둘 다.
# 스킬이 curl 로 Jira REST 를 부르면 설정 run_jira_allow_net 으로 거부 목록을 뺀다.
# Skill·Agent — 스킬이 다음 스킬로 이어 가거나 하위 에이전트에 조사를 맡길 수 있게
JIRA_PROMPT_RE = re.compile(r"^/jira\s+([A-Z][A-Z0-9_]*-\d+)\s*$")   # 키트 게이트웨이 ISSUE_KEY_RE·입력칸과 같은 이슈 키 모양
SKILL_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,63}$")
JIRA_TOOLS = ["Read", "Write", "Bash", "Glob", "Grep", "Edit", "Skill", "Agent",
              "mcp__jira__jira_get_issue", "mcp__jira__jira_search", "mcp__jira__jira_get_transitions"]
JIRA_DENY = ["Bash(%s%s:*)" % (p, c) for c in ("curl", "wget", "Invoke-WebRequest", "Invoke-RestMethod", "iwr", "irm",
                                               "nc", "ncat", "ssh", "scp", "sftp", "ftp", "telnet") for p in ("", "rtk ")] \
    + ["Bash(rtk proxy:*)"]
JIRA_MCP_ARGS = ["mcp-atlassian@0.23.1", "--transport", "stdio", "--read-only"]
JIRA_NO_SKILL = ("Jira 이슈 %s 를 처리해 줘. mcp__jira__jira_get_issue 로 이슈(설명·댓글)를 읽고 무엇을 해야 하는지 정리한 뒤, "
                 "이 폴더의 코드에서 고칠 곳을 찾아. 고치기 전에 방향을 choices 로 물어봐.")   # 작업 폴더에 jira 스킬이 없을 때
TOOL_RE = re.compile(r"^[A-Za-z0-9_]+(\([^\"'`\r\n]*\))?$")      # 명령줄에 붙이기 전에 거른다(워커 Test-JobInputs 와 같은 규칙)
SESSION_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
TIMEOUT_SEC = 900
MAX_PROMPT = 4000
MAX_PER_CYCLE = 3                 # 한 바퀴에 받는 지시 수(실수로 무더기 실행되는 것 막기)
LOOKBACK_DAYS = 2
CONFIRM_TTL_MIN = 60
KEEP_JOBS = 200
SEEN_KEEP = 800
ACK_MAX_AGE = 1800
PROGRESS_AFTER_MIN = 3            # 폰·메일 앱 지시가 이 분(分)보다 오래 돌면 진행 메일 1통(설정 progress_after_min, 0 이면 끔)
ASK_TTL_HOURS = 24                # 선택지로 물은 뒤 답 없이 이 시간이 지나면 질문을 닫고 알림 1통(설정 ask_ttl_hours, 0 이면 끔)
ASK_CLOSE_SILENT_DAYS = 7         # 이보다 오래된 질문은 알리지 않는다(처음 켤 때 몰아 보내지 않게)
REPLY_TRIES = 3
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
MAX_IMAGES, MAX_IMAGE_BYTES = 5, 10 * 1024 * 1024

THREAD_RE = re.compile(r"\[T(\d{1,6})\]")
SUBJECT_KEY_RE = re.compile(r"\s*\[k:([^\]\s]{1,64})\]\s*$")
BODY_KEY_RE = re.compile(r"^[ \t]*\[k:([^\]\s]{1,64})\][ \t\r]*$", re.M)
CHOICES_RE = re.compile(r"```choices[ \t]*\n(.*?)\n?```\s*$", re.S)
STOP_WORDS = {"멈춤", "그만", "stop"}
RETRY_WORDS = {"다시 실행", "다시실행", "재실행", "retry"}   # 실패한 대화의 지시를 그대로 다시(🔁 단추가 보내는 말) — 게이트웨이와 같게
# 돌고 있는 일에 폰·메일 앱이 '진행?' — 새 작업 없이 지금 하는 일 한 줄(progress_text)을 바로 보낸다. 끝난 일이면 평소처럼 세션에 묻는다.
# 게이트웨이(mail-gateway.py PROGRESS_WORDS·is_progress_ask)와 같은 말
PROGRESS_WORDS = {"진행", "진행상황", "진행 상황", "어디까지", "어디까지 했어", "지금 뭐 해", "뭐 해", "뭐해", "상태", "status", "progress"}
PROGRESS_ASK_TTL = 600            # '진행?' 이 이 초보다 묵으면(그사이 못 보냈으면) 버린다


def is_progress_ask(said):
    t = re.sub(r"\s+", " ", (said or "").strip().lower()).rstrip("?？!. ")
    return t in PROGRESS_WORDS
CONFIRM_YES = {"1", "확인", "실행", "ok", "yes", "y", "네", "예", "go"}
CONFIRM_NO = {"2", "취소", "no", "n", "아니오", "아니요", "x", "stop", "멈춤", "그만"}
STOPPED_BEFORE_START = "멈췄습니다 — 시작하기 전에 멈춤 요청을 받아 실행하지 않았습니다."
STOPPED_MIDWAY = "멈췄습니다 — 멈춤을 받아 하던 일을 중간에 끊었습니다. 이어서 하려면 다시 말해 주세요."
NO_CLAUDE = ("Claude Code(claude)를 찾지 못했습니다 — 이 PC 에 Claude Code 를 설치하고 한 번 로그인한 뒤"
             "(터미널에서 claude 실행) 메신저를 다시 여세요.")
ASK_SPLIT = "─" * 16


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------- 메일 해석(게이트웨이와 같은 규칙)

def split_subject_key(subject):
    """제목 끝의 암호 단어 '[k:단어]' 를 떼어 (나머지 제목, 단어 또는 None)."""
    m = SUBJECT_KEY_RE.search(subject or "")
    return (subject[:m.start()].rstrip(), m.group(1)) if m else (subject, None)


def jira_key_of(prompt, cfg):
    """'/jira 키' — 또는 설정의 이슈 명령(issue_command, 예: '/issue')으로 온 이슈 처리 지시면 그 키, 아니면 None."""
    mj = JIRA_PROMPT_RE.match(prompt or "")
    if mj:
        return mj.group(1)
    cmd = str(cfg.get("issue_command") or "").strip()
    if cmd and cmd != "/jira" and re.fullmatch(r"/[\w.-]{1,64}", cmd):
        m = re.match(r"^%s\s+([A-Z][A-Z0-9_]*-\d+)\s*$" % re.escape(cmd), prompt or "")
        return m.group(1) if m else None
    return None


def thread_of(subject):
    m = THREAD_RE.search(subject or "")
    return int(m.group(1)) if m else None


def refs_of(head):
    return re.findall(r"<[^<>]+>", " ".join(str(head.get(h) or "") for h in ("In-Reply-To", "References")))


def parse_choices(text):
    """결과 끝의 ```choices 블록을 떼어 (본문, ask). 없거나 깨졌으면 (원문, None)."""
    t = (text or "").rstrip()
    m = CHOICES_RE.search(t)
    if not m:
        return text or "", None
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return text or "", None
    if not isinstance(d, dict):
        return text or "", None
    opts = [str(o).strip() for o in (d.get("options") or []) if str(o).strip()][:4]
    q = str(d.get("question") or "").strip()
    if not q or not opts:
        return text or "", None
    return t[:m.start()].rstrip(), {"question": q, "multi": bool(d.get("multi")), "options": opts}


def parse_answer(text, ask):
    """번호 답('1,3' · '2번' · '1 3' · '4 이건 이렇게')을 선택지 내용으로 푼다. 번호 답이 아니면 None."""
    if not ask or not text:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    first, more = lines[0], lines[1:]
    if re.fullmatch(r"[1-9](\s+[1-9])+", first):
        nums, rest = first.split(), ""
    else:
        m = re.match(r"^([1-9](?:\s*[,，/·]\s*[1-9])*)\s*(?:번)?(?:[.:)]\s*|\s+|$)(.*)$", first)
        if not m:
            return None
        nums, rest = re.findall(r"[1-9]", m.group(1)), m.group(2)
    picked = []
    for x in nums:
        i = int(x)
        if i > len(ask["options"]):
            return None
        if i not in picked:
            picked.append(i)
    out = "사용자 답(번호 선택): " + " / ".join("☑ %d. %s" % (i, ask["options"][i - 1]) for i in picked)
    if not ask.get("multi") and len(picked) > 1:
        out += "\n(한 개만 고르는 질문이었지만 여러 개를 골랐다)"
    extra = "\n".join([rest] + more).strip()
    if extra:
        out += "\n덧붙인 말: " + extra
    return out


def parse_confirm_answer(text):
    """확인 답의 첫 '내용 있는 줄'만 보고 'yes' / 'no' / None(애매 — 다시 답하기를 기다린다)."""
    for line in (text or "").splitlines():
        t = line.strip()
        if not t or t.startswith(">"):
            continue
        t = re.sub(r"[\s.!。]+$", "", t).lower()
        return "yes" if t in CONFIRM_YES else ("no" if t in CONFIRM_NO else None)
    return None


def auth_failed(head):
    """서버가 붙인 발신 인증 결과가 '실패'면 True — 내 주소를 사칭한 메일 거르기. 결과가 없으면 False(막지 않는다).
    이 값으로는 막기만 하고 받아 주지는 않으므로, 가짜 머리글을 붙여도 문이 넓어지지 않는다."""
    vals = " | ".join(str(v) for v in (head.get_all("Authentication-Results") or []))
    if not vals:
        return False
    if re.search(r"\bdmarc\s*=\s*fail\b", vals, re.I):
        return True
    if re.search(r"\bdkim\s*=\s*pass\b", vals, re.I):
        return False
    return bool(re.search(r"\bspf\s*=\s*(fail|softfail)\b", vals, re.I))


def ask_lines(ask):
    if not ask:
        return []
    lines = ["❓ %s%s" % (ask["question"], " (여러 개 가능)" if ask.get("multi") else "")]
    lines += ["  ☐ %d. %s" % (i, o) for i, o in enumerate(ask["options"], 1)]
    lines.append("  → 번호로 답장하세요 (예: %s). 하고 싶은 말을 그대로 써도 되고, \"멈춤\" 이면 멈춥니다."
                 % ('"1,3"' if ask.get("multi") else '"1"'))
    return lines


_PILL = ("display:inline-block;margin:3px 4px 3px 0;padding:7px 13px;border-radius:999px;text-decoration:none;"
         "font-weight:700;font-size:14px;background:#eee9ff;color:#5b45c9;border:1px solid #d9cffb")


def reply_subject(job):
    subj = job.get("mail_subject") or "지시"
    return subj if subj.lower().startswith("re:") else "Re: " + subj


def mailto(cfg, job, body):
    """'한 번에 답장' 링크 — 제목(태그·대화 번호)과 본문이 채워진 메일 작성 화면. 암호 단어를 쓰면 제목 끝에 붙인다."""
    subject = reply_subject(job)
    word = str(cfg.get("key_word") or "").strip()
    if word:
        subject += " [k:%s]" % word
    return "mailto:%s?subject=%s&body=%s" % (cfg.get("user") or "", quote(subject), quote(body))


def reply_html(cfg, job, ask, text, footer):
    """폰 메일 앱에서 누를 수 있는 답장 단추가 달린 HTML 본문(글자 본문과 같은 내용)."""
    parts = ['<div style="font-family:-apple-system,\'Segoe UI\',\'Malgun Gothic\',sans-serif;font-size:15px;line-height:1.5;color:#2f2b45">']
    if ask:
        parts.append('<div style="background:#f7f4fc;border:1px solid #ebe4f6;border-radius:14px;padding:10px 12px;margin-bottom:12px">')
        parts.append('<div style="font-weight:800;margin-bottom:6px">❓ %s%s</div>' % (
            html_escape(ask["question"]), " <span style='color:#8781a0;font-weight:600'>(여러 개 가능)</span>" if ask.get("multi") else ""))
        for i, o in enumerate(ask["options"], 1):
            parts.append('<a href="%s" style="%s">%d. %s</a><br>' % (html_escape(mailto(cfg, job, str(i))), _PILL, i, html_escape(o)))
        if ask.get("multi"):
            parts.append('<a href="%s" style="%s">여러 개 고르기…</a>' % (html_escape(mailto(cfg, job, "1,2")), _PILL))
        parts.append('<a href="%s" style="%s;background:#fff;color:#8781a0">멈춤</a>' % (html_escape(mailto(cfg, job, "멈춤")), _PILL))
        parts.append('<div style="color:#8781a0;font-size:12px;margin-top:6px">단추를 누르면 답장이 채워진 채 열립니다 — 보내기만 누르세요.'
                     '%s</div></div>' % (" 여러 개는 \"1,3\" 처럼 고쳐 보내세요." if ask.get("multi") else ""))
    parts.append('<div style="white-space:pre-wrap">%s</div>' % html_escape(text))
    parts.append('<div style="color:#8781a0;font-size:12px;margin-top:12px;white-space:pre-wrap">%s</div>' % html_escape(footer))
    parts.append('</div>')
    return "".join(parts)


def reply_footer(job):
    secs = int((job.get("duration_ms") or 0) / 1000)
    lines = ["%s작업 폴더 %s · %d초 · $%.3f%s%s · 이 PC 에서 실행" % (
        ("[T%s] · " % job["thread"]) if job.get("thread") else "", job.get("workdir") or "", secs, job.get("cost_usd") or 0,
        " · 수정 허용 모드" if job.get("mode") == "write" else "", " · 이어서 실행" if job.get("resume_id") else "")]
    if job.get("session_id"):
        lines.append("PC에서 이어서: cd %s && claude --resume %s" % (job.get("workdir") or "", job["session_id"]))
    return "\n".join(lines)


def reply_body(job):
    """(ask, 본문) — 끝난 일의 결과(선택지 블록은 뗀다) 또는 실패 사유."""
    body, ask = parse_choices(job.get("result") or "")
    if job.get("status") != "done":
        ask = None
        lines = ["실행에 실패했습니다.", "", job.get("error") or ""] + (["", job["result"]] if job.get("result") else [])
    else:
        lines = [body]
    denied = sorted({d.get("tool_name", "?") for d in (job.get("denials") or []) if isinstance(d, dict)})
    if denied:
        lines += ["", "--", "차단된 도구: %s (허용 범위 밖이라 실행되지 않았습니다)" % ", ".join(denied)]
    return ask, "\n".join(lines)


# ----------------------------------------------------------------- 프로세스 묶음(자식까지 끊기)

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class _BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _ExtLimit(ctypes.Structure):
        _fields_ = [("Basic", _BasicLimit), ("Io", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _K32 = ctypes.WinDLL("kernel32", use_last_error=True)      # chat.py 의 windll.kernel32 설정과 섞이지 않게 따로
    _K32.CreateJobObjectW.restype = wintypes.HANDLE
    _K32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _K32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _K32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _K32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _K32.CloseHandle.argtypes = [wintypes.HANDLE]
    JOB_KILL_ON_CLOSE = 0x2000
    CREATE_NO_WINDOW = 0x08000000


class ProcTree:
    """claude 와 그 자식(node·도구 명령)을 한 묶음으로. 윈도우는 작업 개체(닫히면 같이 끝난다 — 메신저가 죽어도 남지 않는다),
    맥·리눅스는 새 프로세스 그룹(start_new_session)."""

    def __init__(self, p):
        self.p, self.job = p, None
        if IS_WIN:
            try:
                job = _K32.CreateJobObjectW(None, None)
                info = _ExtLimit()
                info.Basic.LimitFlags = JOB_KILL_ON_CLOSE
                if job and _K32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
                        and _K32.AssignProcessToJobObject(job, int(p._handle)):
                    self.job = job
                elif job:
                    _K32.CloseHandle(job)
            except Exception:
                self.job = None

    def kill(self):
        p = self.p
        if IS_WIN:
            if self.job:
                _K32.TerminateJobObject(self.job, 1)
            elif p.poll() is None:
                # 작업 개체에 못 넣은 경우만 — claude 의 PID 아래 나무만 끝낸다(워커 Stop-ProcessTree 와 같은 방법)
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except (OSError, ProcessLookupError):
                    break
                try:
                    p.wait(3)
                    break
                except subprocess.TimeoutExpired:
                    continue
        try:
            if p.poll() is None:
                p.kill()
            p.wait(5)
        except Exception:
            pass

    def close(self):
        if IS_WIN and self.job:
            _K32.CloseHandle(self.job)
            self.job = None


# ----------------------------------------------------------------- 실행기

def _items(data):
    """imaplib FETCH 응답 → [[머리 bytes, 본문 bytes]]. 리터럴 뒤에 오는 조각(b' INTERNALDATE … )')도 머리에 붙인다."""
    out = []
    for it in data or []:
        if isinstance(it, tuple) and len(it) >= 2:
            out.append([it[0], it[1]])
        elif isinstance(it, bytes) and out:
            out[-1][0] += b" " + it
    return out


def _idate(head_b, msg=None):
    """메일함에 들어온 시각(INTERNALDATE, epoch). 서버가 안 주면 Date 머리글."""
    t = imaplib.Internaldate2tuple(head_b) if b"INTERNALDATE" in head_b else None
    if t:
        return time.mktime(t)
    try:
        return email.utils.parsedate_to_datetime(msg.get("Date")).timestamp() if msg is not None else None
    except Exception:
        return None


class Runner:
    def __init__(self, chat, root=None):
        self.C = chat
        self.root = root or os.path.join(chat.LOCALDATA, "runner")
        self.lock = threading.RLock()            # 작업 파일·상태 파일 고치기
        self.send_lock = threading.Lock()        # 메일함에 써 넣기
        self.wake = threading.Event()            # 메일함 다시 읽기
        self.kick = threading.Event()            # 대기 작업 집기
        self.stop_req = set()
        self.current = ""
        self.error = ""
        self.polled = 0.0
        self.max_thread = 0
        self.uid_done = {}
        self.st = None
        self.cleaned = False
        self._claude = (0.0, None)
        self.started = False
        self.jira = jira_watch.JiraWatch(self)   # Jira 새 티켓 감시(설정 jira_watch, 기본 꺼짐) — 직접 실행 PC 에서만(게이트웨이 PC 는 키트 jira-watch.py)

    @property
    def jobs_dir(self):
        return os.path.join(self.root, "jobs")

    # ---------- 막힘 · 설정

    def gateway_here(self):
        """이 PC 가 게이트웨이 PC 인지 — 키트 저장소 안에서 돌고 키트 메일 게이트웨이가 켜져 있으면(dispatch.enabled) 그 저장소 경로."""
        C = self.C
        return C.REPO_ROOT if C.kit_gateway_on() else ""

    def blocked(self, cfg, src):
        """켤 수 없는 이유(없으면 "")."""
        if src == "kit":
            return ("키트 공통 설정(config.local.json)의 계정을 쓰고 있습니다 — 이 PC 는 게이트웨이 PC 라 일은 메일 게이트웨이가 합니다. "
                    "두 번 실행되지 않게 여기서는 켤 수 없습니다.")
        gw = self.gateway_here()
        if gw:
            return "이 PC 에 키트 메일 게이트웨이(%s)가 켜져 있습니다 — 게이트웨이와 겹쳐 같은 지시가 두 번 실행될 수 있어 켤 수 없습니다." % gw
        if not cfg.get("user") or not cfg.get("password_enc"):
            return "메일 계정을 먼저 넣어 주세요."
        return ""

    def claude_cmd(self):
        """claude 실행 명령(목록). 없으면 None. 30초 동안 기억한다."""
        at, got = self._claude
        if time.time() - at < 30:
            return got
        path = shutil.which("claude")
        if not path and not IS_WIN:
            # 맥에서 Finder 로 띄운 앱은 PATH 가 짧다 — 설치 프로그램이 두는 흔한 자리를 본다
            home = os.path.expanduser("~")
            for c in (os.path.join(home, ".local", "bin", "claude"), os.path.join(home, ".claude", "local", "claude"),
                      "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
                if os.path.isfile(c) and os.access(c, os.X_OK):
                    path = c
                    break
        got = [path] if path else None
        self._claude = (time.time(), got)
        return got

    def on(self):
        """켜져 있고 막히지 않았는지(진행 카드·상태 표시용 — claude 유무는 보지 않는다)."""
        cfg, src = self.C.load_cfg()
        return bool(cfg.get("run_here")) and not self.blocked(cfg, src)

    def summary(self):
        cfg, src = self.C.load_cfg()
        on = bool(cfg.get("run_here"))
        why = self.blocked(cfg, src) if on else ""
        return {"on": on, "active": on and not why and bool(self.claude_cmd()), "busy": self.current,
                "error": self.error or why, "notice": cfg.get("run_conflict") or ""}

    def info(self):
        cfg, src = self.C.load_cfg()
        claude = self.claude_cmd()
        return {"enabled": bool(cfg.get("run_here")), "since": cfg.get("run_since") or 0,
                "workdir": cfg.get("run_workdir") or "", "home": os.path.expanduser("~"),
                "dirs": "\n".join("%s=%s" % kv for kv in (cfg.get("run_dirs") or {}).items()),
                "claude": claude[-1] if claude else "", "blocked": self.blocked(cfg, src),
                "notice": cfg.get("run_conflict") or "", "error": self.error, "busy": self.current,
                "has_key": bool(str(cfg.get("key_word") or "").strip()),
                "browser": bool(cfg.get("run_browser")), "browser_path": find_browser()[0], "npx": bool(find_tool("npx")),
                "jira": bool(cfg.get("run_jira")), "jira_url": cfg.get("run_jira_url") or "",
                "jira_dir": cfg.get("run_jira_dir") or "", "has_jira_token": bool(cfg.get("run_jira_token_enc")),
                "jira_skill": cfg.get("run_jira_skill") or "", "jira_allow_net": bool(cfg.get("run_jira_allow_net")),
                "cost": cost_limit(cfg), "spent": spent_today(self.jobs_dir)}

    def configure(self, data):
        """설정 화면의 스위치·작업 폴더. 켜는 순간을 run_since 로 남긴다 — 그 전에 온 메일은 실행하지 않는다."""
        C = self.C
        own = C.read_json(C.OWN_CFG) or {}
        cfg, src = C.load_cfg()
        if "workdir" in data:
            wd = str(data.get("workdir") or "").strip()
            if wd and not os.path.isdir(wd):
                raise ValueError("작업 폴더가 없습니다: %s" % wd)
            own["run_workdir"] = os.path.abspath(wd) if wd else ""
        if "dirs" in data:
            own["run_dirs"] = parse_dirs(data.get("dirs"))
        self.configure_extras(own, data)
        want = bool(data.get("enabled"))
        if want and not own.get("run_here"):
            why = self.blocked(cfg, src) or ("" if self.claude_cmd() else NO_CLAUDE)
            if why:
                raise ValueError(why)
            if not own.get("run_workdir"):
                raise ValueError("기본 작업 폴더를 넣어 주세요 — 지시를 그 폴더에서 실행합니다.")
            own.update(run_here=True, run_since=time.time(), run_id=own.get("run_id") or secrets.token_hex(8))
            own.pop("run_conflict", None)
            C.log("[실행] 이 PC 에서 직접 실행을 켰습니다 — 지금 이후에 온 지시만 실행합니다")
        elif not want:
            if own.get("run_here"):
                C.log("[실행] 이 PC 에서 직접 실행을 껐습니다")
                self.cancel_unfinished("이 PC 에서 직접 실행을 꺼서 멈췄습니다.")
            own["run_here"] = False
            own.pop("run_conflict", None)
        C.write_json(C.OWN_CFG, own)
        self.error = ""
        self.wake.set()
        self.kick.set()
        return self.info()

    def configure_extras(self, own, data):
        """브라우저·Jira 스위치와 Jira 값, 하루 비용 한도. 켤 때 필요한 것이 없으면 이유와 함께 막는다."""
        if "cost" in data:
            raw = str(data.get("cost") or "").strip()
            try:
                own["daily_cost_usd"] = max(0.0, float(raw)) if raw else 0.0
            except ValueError:
                raise ValueError("하루 비용 한도는 숫자(달러)로 넣어 주세요 — 0 이면 없음: %s" % raw)
        if "jira_url" in data:
            url = str(data.get("jira_url") or "").strip().rstrip("/")
            if url and not re.match(r"^https?://[^\s/]+", url):
                raise ValueError("Jira 주소는 https:// 로 시작하게 넣어 주세요: %s" % url)
            own["run_jira_url"] = url
        if str(data.get("jira_token") or "").strip():                   # 비어 있으면 그대로 둔다(바꿀 때만 넣는다)
            own["run_jira_token_enc"] = self.C.protect_secret(str(data["jira_token"]).strip(), "jira")
        if data.get("jira_token_clear"):
            own.pop("run_jira_token_enc", None)
        if "jira_dir" in data:
            jd = str(data.get("jira_dir") or "").strip()
            if jd and not os.path.isdir(jd):
                raise ValueError("Jira 작업 폴더가 없습니다: %s" % jd)
            own["run_jira_dir"] = os.path.abspath(jd) if jd else ""
        if "jira_skill" in data:
            sk = str(data.get("jira_skill") or "").strip().lstrip("/")
            if sk and not SKILL_RE.match(sk):
                raise ValueError("Jira 스킬 이름은 영문·숫자·-·_ 로 넣어 주세요(예: jira, issue-task): %s" % sk)
            own["run_jira_skill"] = sk
        if "jira_allow_net" in data:
            own["run_jira_allow_net"] = bool(data.get("jira_allow_net"))
        if "browser" in data:
            want = bool(data.get("browser"))
            if want and not own.get("run_browser"):
                if not find_tool("npx"):
                    raise ValueError("npx(Node.js)를 찾지 못했습니다 — Node.js 를 설치한 뒤 메신저를 다시 여세요. 전용 브라우저(Playwright)를 npx 로 띄웁니다.")
                if not find_browser()[0]:
                    raise ValueError("Chrome 을 찾지 못했습니다 — Chrome 을 설치하세요(윈도우는 Edge 도 됩니다).")
            own["run_browser"] = want
        if "jira" in data:
            want = bool(data.get("jira"))
            if want and own.get("run_jira_token_enc"):
                if not own.get("run_jira_url"):
                    raise ValueError("Jira 주소를 넣어 주세요 — 토큰을 넣으면 그 주소로 Jira 도구(mcp-atlassian)를 띄웁니다.")
                if not find_tool("uvx"):
                    raise ValueError("uvx(uv)를 찾지 못했습니다 — uv 를 설치하거나, 토큰을 비우고 이 PC 의 Claude Code 에 이미 있는 jira MCP 를 쓰세요.")
            own["run_jira"] = want

    def cost_block(self, cfg):
        """이 PC 에서 직접 실행 — 하루 비용 한도(설정 daily_cost_usd, 0 이면 없음)에 닿았으면 사람이 읽을 이유, 아니면 ''."""
        limit = cost_limit(cfg)
        if limit <= 0:
            return ""
        spent = spent_today(self.jobs_dir)
        return COST_BLOCKED % (spent, limit) if spent >= limit else ""

    def jira_parts(self, cfg, key, workdir, label):
        """'/jira 키' 작업의 (지시문, 폴더, 폴더 이름, 도구, 거부 목록) — 메일 지시(#cw /jira 키)와 Jira 새 티켓 감시가 같이 쓴다."""
        tools, denied = JIRA_TOOLS, ([] if cfg.get("run_jira_allow_net") else JIRA_DENY)
        if cfg.get("run_jira_dir"):
            workdir, label = cfg["run_jira_dir"], "jira"
        skill = cfg.get("run_jira_skill") or "jira"
        prompt = "/%s %s" % (skill, key) if has_skill(workdir, skill) else JIRA_NO_SKILL % key
        return prompt, workdir, label, tools, denied

    def browser_login(self):
        """전용 브라우저 프로필로 창을 연다 — 사람이 한 번 로그인해 두면 지시가 그 로그인 그대로 쓴다(게이트웨이 browser-login.bat)."""
        if cdp_live():
            return {"ok": True, "already": True}
        path, _ch = find_browser()
        if not path:
            raise ValueError("Chrome 을 찾지 못했습니다 — Chrome 을 설치하세요(윈도우는 Edge 도 됩니다).")
        profile = os.path.join(self.root, "browser", "profile")
        os.makedirs(profile, exist_ok=True)
        port = BROWSER_CDP.rsplit(":", 1)[1]
        kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}   # 메신저와 따로 산다
        subprocess.Popen([path, "--user-data-dir=" + profile, "--remote-debugging-port=" + port,
                          "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        self.C.log("[실행] 전용 브라우저 로그인 창을 열었습니다")
        return {"ok": True, "already": False}

    def mcp_config(self, job, cfg, base):
        """이 작업에 붙일 MCP 서버(--mcp-config 파일, 없으면 ""). 허용 도구에 그 서버가 있고 설정이 켜져 있을 때만.
        base — 임시 파일 앞부분(작업이 끝나면 지운다. Jira 토큰이 들어간다)."""
        tools, servers = job.get("allowed_tools") or [], {}
        npx = ["cmd", "/c", "npx"] if IS_WIN else ["npx"]                # 윈도우 claude 는 npx 를 cmd 로 감싸야 띄운다
        if cfg.get("run_browser") and any(t.startswith(BROWSER_TOOL) for t in tools):
            out = os.path.join(self.root, "browser", "output")
            os.makedirs(out, exist_ok=True)
            if cdp_live():                                               # 로그인 창이 떠 있다 — 같은 프로필이라 새로 못 띄운다
                where = ["--cdp-endpoint", BROWSER_CDP]
            else:
                profile = os.path.join(self.root, "browser", "profile")
                os.makedirs(profile, exist_ok=True)
                pw = {"browser": {"browserName": "chromium", "userDataDir": profile,
                                  "launchOptions": {"channel": find_browser()[1] or "chrome"}}}
                self.C.write_json(base + ".pw.json", pw)
                where = ["--config", base + ".pw.json"]
            servers["browser"] = {"type": "stdio", "command": npx[0],
                                  "args": npx[1:] + ["-y", PLAYWRIGHT_MCP] + where + ["--output-dir", out]}
        if cfg.get("run_jira") and cfg.get("run_jira_token_enc") and any(t.startswith("mcp__jira__") for t in tools):
            servers["jira"] = {"type": "stdio", "command": "uvx", "args": list(JIRA_MCP_ARGS),
                               "env": {"JIRA_URL": cfg.get("run_jira_url") or "",
                                       "JIRA_PERSONAL_TOKEN": self.C.unprotect_secret(cfg["run_jira_token_enc"])}}
        if not servers:
            return ""
        self.C.write_json(base + ".mcp.json", {"mcpServers": servers})
        return base + ".mcp.json"

    def conflict(self, reason):
        """메일함에 다른 실행기의 회신이 보인다 — 스스로 끄고 이유를 남긴다."""
        C = self.C
        own = C.read_json(C.OWN_CFG) or {}
        own["run_here"] = False
        own["run_conflict"] = reason
        C.write_json(C.OWN_CFG, own)
        self.cancel_unfinished("다른 PC(게이트웨이)가 같은 메일함에서 일하고 있어 여기서는 멈췄습니다.")
        C.log("[실행] 껐습니다 — %s" % reason)

    # ---------- 상태 · 작업 파일

    def state(self):
        with self.lock:
            if self.st is None:
                got = self.C.read_json(os.path.join(self.root, "state.json")) or {}
                self.st = {"seen": dict.fromkeys(got.get("seen") or []), "seq": int(got.get("seq") or 0),
                           "early_stops": dict(got.get("early_stops") or {})}
            return self.st

    def save_state(self):
        with self.lock:
            st = self.state()
            now = time.time()
            st["early_stops"] = {k: v for k, v in st["early_stops"].items() if isinstance(v, (int, float)) and now - v < 86400}
            seen = list(st["seen"])[-SEEN_KEEP:]
            st["seen"] = dict.fromkeys(seen)
            self.C.write_json(os.path.join(self.root, "state.json"),
                              {"seen": seen, "seq": st["seq"], "early_stops": st["early_stops"]})

    def iter_jobs(self, newest=True):
        try:
            names = sorted((n for n in os.listdir(self.jobs_dir) if n.endswith(".json")), reverse=newest)
        except OSError:
            return []
        out = []
        for n in names:
            j = self.C.read_json(os.path.join(self.jobs_dir, n))
            if isinstance(j, dict) and j.get("id"):
                out.append(j)
        return out

    def read_job(self, jid):
        return self.C.read_json(os.path.join(self.jobs_dir, "%s.json" % jid))

    def write_job(self, job):
        with self.lock:
            self.C.write_json(os.path.join(self.jobs_dir, "%s.json" % job["id"]), job)

    def update_job(self, jid, keep_canceled=False, **kw):
        """작업 파일 고치기(읽고 바로 쓴다). keep_canceled 면 그사이 취소된 작업은 상태를 그대로 둔다."""
        with self.lock:
            j = self.read_job(jid)
            if not j:
                return None
            if keep_canceled and j.get("status") == "canceled":
                kw = {k: v for k, v in kw.items() if k in ("duration_ms", "session_id", "cost_usd")}
            j.update(kw)
            self.write_job(j)
            return j

    def cancel_unfinished(self, why):
        with self.lock:
            for j in self.iter_jobs():
                if j.get("status") in ("queued", "running", "awaiting_confirm"):
                    if j.get("status") == "running":
                        self.stop_req.add(j["id"])
                    j.update(status="canceled", error=why, finished_at=now_text(), replied=True)
                    self.write_job(j)

    def clean_orphans(self):
        """앞서 메신저가 일하는 도중 꺼졌으면 그 작업이 running 으로 남는다 — 실패로 돌려 회신한다."""
        for j in self.iter_jobs():
            if j.get("status") == "running":
                self.update_job(j["id"], status="error", finished_at=now_text(),
                                error="메신저가 다시 시작되어 실행 중이던 작업이 중단됐습니다. 필요하면 다시 보내세요.")
                self.C.log("[실행] 중단된 작업 정리 %s" % j["id"])

    def prune(self):
        jobs = self.iter_jobs()
        for j in jobs[KEEP_JOBS:]:
            if j.get("status") in ("done", "error", "canceled") and j.get("replied"):
                try:
                    os.remove(os.path.join(self.jobs_dir, "%s.json" % j["id"]))
                except OSError:
                    pass
        base, cut = os.path.join(self.root, "attachments"), time.time() - 7 * 86400
        try:
            for name in os.listdir(base):
                d = os.path.join(base, name)
                if os.path.isdir(d) and os.path.getmtime(d) < cut:
                    shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

    def expire_confirms(self):
        for j in self.iter_jobs():
            if j.get("status") != "awaiting_confirm":
                continue
            try:
                born = datetime.strptime(j.get("created_at") or "", "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                continue
            if time.time() - born > CONFIRM_TTL_MIN * 60:
                self.update_job(j["id"], status="canceled", finished_at=now_text(),
                                error="확인 답장이 %d분 안에 오지 않아 취소했습니다." % CONFIRM_TTL_MIN)

    def own_ids(self):
        ids = set()
        for j in self.iter_jobs():
            ids.update(j[k] for k in ("reply_msgid", "confirm_msgid", "ack_msgid", "progress_msgid", "asked_msgid") if j.get(k))
        return ids

    def next_seq(self):
        """새 대화 번호 — 이 PC 가 매긴 것 · 메일함에서 본 가장 큰 번호보다 하나 크게(예전 게이트웨이 대화와 겹치지 않게)."""
        with self.lock:
            st = self.state()
            seen_box = 0
            try:
                with self.C.BOX.lock:
                    seen_box = max([m.get("thread") or 0 for m in self.C.BOX.msgs.values()] + [0])
            except Exception:
                pass
            st["seq"] = max(st["seq"], self.max_thread, seen_box) + 1
            self.save_state()
            return st["seq"]

    def ensure_thread(self, job, cfg):
        n = job.get("thread") or thread_of(job.get("mail_subject")) or self.next_seq()
        job["thread"] = n
        subject = job.get("mail_subject") or (cfg.get("tags") or ["#c"])[0]
        if thread_of(subject) is None:
            tag, _ = self.C.match_tag(subject, cfg)
            subject = ("%s [T%d] %s" % (tag, n, subject[len(tag):].strip())).rstrip() if tag else ("[T%d] %s" % (n, subject)).rstrip()
        job["mail_subject"] = subject
        return n

    # ---------- 지시 찾기

    def find_resume_job(self, thread_no, refs):
        """이어받을 작업(세션이 있는 것) — 대화 번호가 먼저, 없으면 답장 대상(In-Reply-To/References)."""
        jobs = self.iter_jobs()
        if thread_no is not None:
            for j in jobs:
                if j.get("thread") == thread_no and j.get("session_id"):
                    return j
        refset = set(refs)
        for j in jobs:
            if j.get("session_id") and {x for x in (j.get("reply_msgid"), j.get("mail_msgid")) if x} & refset:
                return j
        return None

    def find_failed_job(self, thread_no, refs):
        """이 말이 가리키는 대화의 가장 최근 작업이 실패(error)했으면 그 작업 — '다시 실행' 으로 같은 지시를 다시 돌린다.
        가장 최근 작업이 실패가 아니면 None(이미 다시 돌렸거나 잘 끝남 — 그때 '다시 실행' 은 평범한 이어 말하기)."""
        refset = set(refs)
        hits = [j for j in self.iter_jobs() if (thread_no is not None and j.get("thread") == thread_no) or
                ({x for x in (j.get("reply_msgid"), j.get("mail_msgid")) if x} & refset)]
        retried = {j.get("retry_of") for j in hits}      # 작업 id 는 초 단위라 같은 초의 다시 실행이 실패보다 뒤로 정렬될 수 있다
        for j in hits:
            if j["id"] not in retried:
                return j if j.get("status") == "error" else None
        return None

    def find_live_job(self, thread_no, refs):
        refset = set(refs)
        for j in self.iter_jobs():
            if j.get("status") in ("queued", "running") and \
                    ((thread_no is not None and j.get("thread") == thread_no) or (j.get("mail_msgid") in refset)):
                return j
        return None

    def find_pending_confirm(self, thread_no, refs):
        refset = set(refs)
        for j in self.iter_jobs():
            if j.get("status") == "awaiting_confirm" and \
                    ((thread_no is not None and j.get("thread") == thread_no) or (j.get("confirm_msgid") in refset)):
                return j
        return None

    def build_instruction(self, subject, body, cfg):
        """'#c @key 할 일' → (지시문, 작업 폴더, 폴더 이름, 모드). @key 는 설정의 작업 폴더 목록."""
        tag, mode = self.C.match_tag(subject, cfg)
        workdir, label = cfg.get("run_workdir") or "", "default"
        if not tag:
            return "", workdir, label, "read"
        text = THREAD_RE.sub("", subject[len(tag):]).strip()
        m = re.match(r"^@(\w+)\s*", text)
        if m and (cfg.get("run_dirs") or {}).get(m.group(1)):
            workdir, label = cfg["run_dirs"][m.group(1)], m.group(1)
            text = text[m.end():].strip()
        said = self.C.said_text(body)
        prompt = (text + "\n\n" + said).strip() if said else text
        return prompt[:MAX_PROMPT].strip(), workdir, label, mode

    def save_images(self, msg, key):
        if not msg.is_multipart():
            return "", []
        folder, paths = os.path.join(self.root, "attachments", key), []
        for part in msg.walk():
            ext = IMAGE_TYPES.get(part.get_content_type())
            if not ext or len(paths) >= MAX_IMAGES:
                continue
            data = part.get_payload(decode=True) or b""
            if not data or len(data) > MAX_IMAGE_BYTES:
                continue
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "photo%d%s" % (len(paths) + 1, ext))
            with open(path, "wb") as f:
                f.write(data)
            paths.append(path)
        return (folder if paths else ""), paths

    # ---------- 메일함 읽기

    def cycle(self):
        """한 바퀴 — 켜져 있고 막히지 않았으면 새 지시를 받고, 확인·접수 신호·회신을 메일함에 넣는다."""
        cfg, src = self.C.load_cfg()
        if not cfg.get("run_here"):
            self.error = ""
            return 0
        why = self.blocked(cfg, src) or ("" if self.claude_cmd() else NO_CLAUDE)
        if why:
            self.error = why
            return 0
        if not self.cleaned:
            self.clean_orphans()
            self.cleaned = True
        pw = self.C.password(cfg)
        self.expire_confirms()
        got = self.poll_mail(cfg, pw)
        if not self.C.load_cfg()[0].get("run_here"):
            return got                                 # 다른 실행기가 보여 꺼졌다
        self.send_out(cfg, pw)
        self.error = ""
        self.polled = time.time()
        if got:
            self.kick.set()
        return got

    def poll_mail(self, cfg, pw):
        C = self.C
        me = (cfg.get("user") or "").strip().lower()
        since_ts = float(cfg.get("run_since") or 0)
        if not me or not since_ts:
            return 0
        since_ts = float(int(since_ts))                # 메일함 시각(INTERNALDATE)은 초 단위 — 켠 그 초에 온 메일도 받는다
        my_id = str(cfg.get("run_id") or "")
        st = self.state()
        own = self.own_ids()
        start = max(since_ts, time.time() - LOOKBACK_DAYS * 86400) - 86400
        since = datetime.fromtimestamp(start).strftime("%d-%b-%Y")
        n = 0
        m = C.imap_connect(cfg, pw)
        try:
            for box in C.resolve_folders(m, cfg.get("folders") or ["INBOX"]):
                typ, _ = m.select('"%s"' % box, readonly=True)
                if typ != "OK":
                    continue
                uv = (m.untagged_responses.get("UIDVALIDITY") or [b"0"])[0]
                done = self.uid_done.setdefault((box, uv), set())
                typ, data = m.uid("SEARCH", "SINCE", since)
                if typ != "OK" or not data or not data[0]:
                    continue
                new = [u.decode() for u in data[0].split() if u.decode() not in done]
                for i in range(0, len(new), 50):
                    typ, hdrs = m.uid("FETCH", ",".join(new[i:i + 50]),
                                      "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID DATE X-DISPATCH X-DISPATCH-RUNNER X-DISPATCH-MIRROR)])")
                    cands = []
                    for head_b, body_b in _items(hdrs):
                        mu = re.search(rb"UID (\d+)", head_b)
                        if not mu:
                            continue
                        uid = mu.group(1).decode()
                        h = email.message_from_bytes(body_b)
                        subj = split_subject_key(C.strip_re(C.decode_hdr(h.get("Subject"))))[0]
                        tn = thread_of(subj)
                        if tn:
                            self.max_thread = max(self.max_thread, tn)
                        mid = (h.get("Message-ID") or "").strip()
                        key = mid or "%s#uid%s" % (box, uid)
                        if not C.match_tag(subj, cfg)[0] or key in st["seen"]:
                            done.add(uid)
                            continue
                        idate = _idate(head_b, h)
                        if h.get("X-Dispatch"):
                            # 봇 메일 — 켠 뒤에 들어온 남의(이 실행기가 아닌) 회신이면 다른 실행기가 같은 메일함을 쓰고 있다
                            if idate and idate >= since_ts and str(h.get("X-Dispatch-Runner") or "") != my_id and mid not in own:
                                self.conflict("이 메일함에 다른 PC(메일 게이트웨이 등)의 회신이 들어옵니다 — 같은 지시가 두 번 "
                                              "실행되지 않게 이 PC 에서 직접 실행을 껐습니다. 그쪽을 끈 뒤 다시 켜세요.")
                                return n
                        elif not h.get("X-Dispatch-Mirror") and mid not in own and idate is not None and idate >= since_ts:
                            cands.append((uid, key))
                            continue
                        with self.lock:
                            st["seen"][key] = None
                        done.add(uid)
                    for uid, key in cands:
                        if n >= MAX_PER_CYCLE:
                            break                      # 나머지는 다음 바퀴에(처리 기록에 넣지 않는다)
                        typ, full = m.uid("FETCH", uid, "(BODY.PEEK[])")
                        items = _items(full)
                        if typ != "OK" or not items:
                            continue
                        try:
                            made = self.take(cfg, me, items[0][1], key)
                        except Exception:
                            C.log("[실행] 지시 처리 실패 — %s" % traceback.format_exc(limit=3))
                            made = False
                        with self.lock:
                            st["seen"][key] = None
                        done.add(uid)
                        n += 1 if made else 0
        finally:
            self.save_state()
            try:
                m.logout()
            except Exception:
                pass
        return n

    def take(self, cfg, me, raw, key):
        """지시 메일 한 통 → 작업(또는 확인 답·멈춤 처리). 작업을 만들었으면 True."""
        C = self.C
        msg = email.message_from_bytes(raw)
        subject = C.decode_hdr(msg.get("Subject"))
        clean, skey = split_subject_key(C.strip_re(subject))
        sender = email.utils.parseaddr(msg.get("From", ""))[1].strip().lower()
        if sender != me:
            C.log("[실행] 내 주소가 아닌 메일이라 무시합니다: %s" % sender)
            return False
        word = str(cfg.get("key_word") or "").strip()
        if word:
            got = skey
            if not got:
                mk = BODY_KEY_RE.search(C.plain_body(msg) or "")
                got = mk.group(1) if mk else None
            if not (got and hmac.compare_digest(got.encode("utf-8"), word.encode("utf-8"))):
                C.log("[실행] 암호 단어가 없거나 틀려 무시합니다: %s" % clean[:60])
                return False
        if auth_failed(msg):
            C.log("[실행] 발신 인증 실패라 무시합니다: %s" % clean[:60])
            return False
        body = C.BODY_KEY_RE.sub("", C.plain_body(msg) or "")
        said = C.said_text(body)
        thread_no, refs = thread_of(clean), refs_of(msg)
        msgid = (msg.get("Message-ID") or "").strip()
        st = self.state()

        pend = self.find_pending_confirm(thread_no, refs)
        if pend:                                     # 쓰기 지시 확인에 대한 답
            ans = parse_confirm_answer(body)
            if ans == "yes":
                self.update_job(pend["id"], status="queued", confirmed_at=now_text())
                C.log("[실행] 쓰기 지시 확인됨 %s" % pend["id"])
            elif ans == "no":
                self.update_job(pend["id"], status="canceled", error="확인 답장으로 취소했습니다.", finished_at=now_text())
                C.log("[실행] 쓰기 지시 취소됨 %s" % pend["id"])
            else:
                C.log("[실행] 확인 답을 알아듣지 못했습니다(1=실행, 2=취소) %s" % pend["id"])
            return False

        if said.strip().lower() in STOP_WORDS:
            live = self.find_live_job(thread_no, refs)
            if live:
                self.stop_req.add(live["id"])
                self.update_job(live["id"], stop_requested=True)
                C.log("[실행] 멈춤 요청 %s (%s)" % (live["id"], live.get("status")))
                return False
            if not self.find_resume_job(thread_no, refs):
                # 멈출 일이 없다 — 대개 지시보다 '멈춤' 이 먼저 도착한 것. 가리키는 지시를 기억해 두고 그 지시는 실행하지 않는다
                with self.lock:
                    st["early_stops"].update({r: time.time() for r in refs})
                C.log("[실행] 멈춤 — 멈출 일이 아직 없음(지시보다 먼저 옴): %s" % (", ".join(refs) or "대상 없음"))
                return False

        # 돌고 있는(대기 중인) 일에 폰·메일 앱이 '진행?' — 작업에 물음만 적고 send_out 이 바로 진행 한 줄을 넣는다.
        # PC 대화 앱(client=chat)은 진행 카드가 있어 평소대로(끝난 일에 대한 '진행?' 도 평소대로 세션에 묻는다)
        if str(msg.get("X-Dispatch-Client") or "") != "chat" and is_progress_ask(said):
            live = self.find_live_job(thread_no, refs)
            if live:
                self.update_job(live["id"], progress_ask=time.time())
                C.log("[실행] 진행 물음 %s (%s)" % (live["id"], live.get("status")))
                return False

        if said.strip().lower() in RETRY_WORDS:
            # 실패한 대화에 '다시 실행'(🔁 단추) — 그 지시를 같은 대화 번호·폴더·권한으로 그대로 다시 돌린다.
            # 시간 초과처럼 세션 없이 실패한 대화는 이어받을 세션이 없어, 그냥 답하면 새 지시로 갈라졌다.
            # 처음 실행 때 쓰기 확인을 이미 거쳤으므로 다시 묻지 않는다.
            failed = self.find_failed_job(thread_no, refs)
            if failed:
                with self.lock:
                    st["seen"][key] = None
                self.save_state()
                jid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-%04x" % random.randrange(0x10000)
                job = {k: failed.get(k) for k in ("prompt", "workdir", "workdir_label", "mode", "allowed_tools",
                                                    "disallowed_tools", "resume_id", "attach_dir", "chat") if failed.get(k)}
                job.update(id=jid, created_at=now_text(), status="queued", started_at=None, finished_at=None, result=None,
                           error=None, denials=[], cost_usd=None, duration_ms=None, source="mail", runner="chat",
                           mail_msgid=msgid, mail_subject=failed.get("mail_subject") or clean, mail_from=sender, replied=False,
                           client=str(msg.get("X-Dispatch-Client") or ""), retry_of=failed["id"])
                if failed.get("thread") or thread_no:
                    job["thread"] = failed.get("thread") or thread_no
                blocked = self.cost_block(cfg)
                if blocked:
                    job.update(status="error", error=blocked, policy_denied=True, finished_at=now_text())
                self.write_job(job)
                C.log("[실행] 다시 실행 %s ← 실패한 %s" % (jid, failed["id"]))
                return True

        prompt, workdir, label, mode = self.build_instruction(clean, body, cfg)
        if not prompt:
            return False
        prev = self.find_resume_job(thread_no, refs)
        resume_id, denied, tools = None, [], None
        if prev:
            resume_id, denied = prev.get("session_id"), prev.get("disallowed_tools") or []
            thread_no = prev.get("thread") or thread_no
            mode = prev.get("mode") or mode           # 대화는 처음 권한 그대로(수정 대화에 #c 로 답해도 읽기로 떨어지지 않게)
            tools = prev.get("allowed_tools")
            if prev.get("workdir"):
                workdir, label = prev["workdir"], prev.get("workdir_label") or label
            if said.strip().lower() in STOP_WORDS:
                said = "멈춤"
            prompt = (parse_answer(said, prev.get("ask")) or said or prompt)[:MAX_PROMPT]
        elif mode == "write":                         # 새 쓰기 지시 — 설정에서 켠 것만 더한다(이어서 하기는 처음 도구 그대로)
            jkey = jira_key_of(prompt, cfg)
            if jkey and cfg.get("run_jira"):
                prompt, workdir, label, tools, denied = self.jira_parts(cfg, jkey, workdir, label)
            elif cfg.get("run_browser"):
                tools = WRITE_TOOLS + [BROWSER_TOOL]
        with self.lock:
            stopped = bool(msgid and msgid in st["early_stops"])
            st["early_stops"].pop(msgid, None)
            st["seen"][key] = None                   # 실행 전에 먼저 기록 — 도중에 꺼져도 같은 지시가 다시 돌지 않게
        self.save_state()

        jid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-%04x" % random.randrange(0x10000)
        attach_dir, photos = self.save_images(msg, jid)
        if photos:
            prompt += "\n\n[첨부 사진 %d장 — Read 도구로 열어 보고 지시에 맞게 쓸 것]\n" % len(photos) + "\n".join("- " + p for p in photos)
        job = {"id": jid, "created_at": now_text(), "prompt": prompt, "workdir": workdir, "workdir_label": label,
               "status": "queued", "started_at": None, "finished_at": None, "result": None, "error": None,
               "denials": [], "cost_usd": None, "duration_ms": None, "source": "mail", "runner": "chat",
               "mail_msgid": msgid, "mail_subject": clean, "mail_from": sender, "replied": False, "mode": mode,
               "chat": True, "client": str(msg.get("X-Dispatch-Client") or ""),
               "allowed_tools": list(tools or (WRITE_TOOLS if mode == "write" else READ_TOOLS))}
        if resume_id:
            job.update(resume_id=resume_id, thread=thread_no)
        elif thread_no:
            job["thread"] = thread_no
        if denied:
            job["disallowed_tools"] = list(denied)
        if attach_dir:
            job["attach_dir"] = attach_dir
        blocked = "" if stopped or prompt.strip() in STOP_WORDS | {"멈춤"} else self.cost_block(cfg)
        if not os.path.isdir(workdir or ""):
            job.update(status="error", error="작업 폴더를 찾을 수 없습니다: %s — ⚙ 설정에서 작업 폴더를 확인하세요." % workdir,
                       finished_at=now_text())
        elif stopped:
            job.update(status="done", result=STOPPED_BEFORE_START, finished_at=now_text())
        elif blocked:                                 # 하루 비용 한도 — 실행하지 않고 이유만 회신('멈춤' 은 막지 않는다)
            job.update(status="error", error=blocked, policy_denied=True, finished_at=now_text())
            C.log("[실행] 비용 한도로 막음 %s" % jid)
        elif mode == "write" and not resume_id:
            job.update(status="awaiting_confirm", confirm_sent=False)
        self.write_job(job)
        C.log("[실행] 지시 접수 %s [%s%s] %s" % (jid, mode, " · 이어서" if resume_id else "", prompt[:50].replace("\n", " ")))
        return True

    # ---------- 메일함에 써 넣기(확인 · 접수 신호 · 회신)

    def _new_msg(self, cfg, job, kind, ask=None):
        msg = EmailMessage()
        msg["Subject"] = reply_subject(job)
        msg["From"] = msg["To"] = cfg["user"]
        msg["Date"] = email.utils.formatdate(localtime=True)
        mid = email.utils.make_msgid(domain=cfg["user"].split("@", 1)[-1] if "@" in cfg["user"] else None)
        msg["Message-ID"] = mid
        if job.get("mail_msgid"):
            msg["In-Reply-To"] = msg["References"] = job["mail_msgid"]
        msg["X-Dispatch"] = "bot"
        msg["X-Dispatch-Kind"] = kind
        if job.get("thread"):
            msg["X-Dispatch-Thread"] = str(job["thread"])
        msg["X-Dispatch-Status"] = str(job.get("status") or "")
        msg["X-Dispatch-Runner"] = str(cfg.get("run_id") or "")
        if ask:
            msg["X-Dispatch-Ask"] = base64.b64encode(json.dumps(ask, ensure_ascii=False).encode("utf-8")).decode("ascii")
        return msg, mid

    def confirm_message(self, cfg, job):
        prompt = job.get("prompt") or ""
        text = "\n".join(["수정·실행이 허용되는 지시(쓰기 모드)라 실행 전에 확인합니다.", "",
                          "작업 폴더: %s" % job.get("workdir"), "허용 도구: %s" % ", ".join(job.get("allowed_tools") or []), "",
                          "지시:", prompt if len(prompt) <= 600 else prompt[:600] + "…", "",
                          "-- 이 메일에 답장하세요", "  1  (또는 '확인')  →  실행", "  2  (또는 '취소')  →  취소",
                          "%d분 안에 답이 없으면 자동으로 취소됩니다." % CONFIRM_TTL_MIN,
                          "내가 보낸 지시가 아니라면 답하지 말고 두세요(자동 취소됩니다)."])
        ask = {"question": "실행할까요?", "multi": False, "options": ["실행", "취소"]}
        msg, mid = self._new_msg(cfg, job, "confirm", ask)
        msg.set_content(text)
        msg.add_alternative(reply_html(cfg, job, ask, text, "[T%s] · 이 PC 에서 실행" % job.get("thread", "?")), subtype="html")
        return msg, mid

    def ack_message(self, cfg, job):
        msg, mid = self._new_msg(cfg, job, "ack")
        msg.set_content("PC 가 지시를 받았습니다. 끝나면 답을 보냅니다.")
        return msg, mid

    def progress_message(self, cfg, job, text):
        """오래 걸리는 일의 중간 한 줄(잡당 1통). 화면들은 말풍선이 아니라 작은 상태 줄로 보이고 답으로 세지 않는다."""
        msg, mid = self._new_msg(cfg, job, "progress")
        msg.set_content(text)
        return msg, mid

    def progress_text(self, job, now=None):
        """돌고 있는 작업의 진행 한 줄 — 세션 기록(메신저 진행 카드와 같은 것)에서. 못 찾으면 '진행 중 · N분째'."""
        C, now = self.C, time.time() if now is None else now
        start = now - self._run_age(job, now)
        lines = []
        try:
            path = C.find_transcript(job, start - 5)
            if path:
                lines = C._read_lines(path)
        except Exception:
            lines = []
        return progress_line(lines, start - 5, max(0, int(self._run_age(job, now) // 60)))

    def asked_progress_text(self, job, now=None):
        """'진행?' 에 답할 한 줄 — 아직 시작 전이면 앞에 몇 개가 있는지(게이트웨이 asked_progress_text 와 같은 글)."""
        if job.get("status") == "queued":
            ahead = sum(1 for j in self.iter_jobs() if j.get("id") != job.get("id") and
                        (j.get("status") == "running" or (j.get("status") == "queued" and str(j.get("id")) < str(job.get("id")))))
            return "아직 시작 전 · 앞에 %d개" % ahead if ahead else "곧 시작합니다"
        return self.progress_text(job, now)

    def reply_message(self, cfg, job):
        ask, text = reply_body(job)
        footer = reply_footer(job)
        msg, mid = self._new_msg(cfg, job, "reply", ask)
        msg.set_content("\n".join(ask_lines(ask) + (["", ASK_SPLIT, ""] if ask else []) + [text, "", "--", footer]))
        msg.add_alternative(reply_html(cfg, job, ask, text, footer), subtype="html")
        return msg, mid

    def ask_closed_message(self, cfg, job, hours):
        """답 기한이 지나 질문을 닫았다는 알림(선택지 없음 — '답할 것' 에서 빠진다). 게이트웨이 expire_asks 와 같은 모양."""
        msg, mid = self._new_msg(cfg, job, "closed")
        msg.set_content("답을 기다리던 질문을 %d시간이 지나 닫았습니다.\n늦게 답해도 이 대화는 그대로 이어집니다(번호로 답해도 됩니다). "
                        "더 할 일이 없으면 그냥 두세요.\n\n--\n%s" % (int(hours), reply_footer(job)))
        return msg, mid

    def due_asks(self, cfg, now=None):
        """선택지로 물은 회신 중 ask_ttl_hours 가 지나도록 답이 없는 것(대화의 가장 최근 작업만, 일주일 넘은 것은 빼고)."""
        try:
            hours = float(cfg.get("ask_ttl_hours", ASK_TTL_HOURS) or 0)
        except (TypeError, ValueError):
            hours = ASK_TTL_HOURS
        if hours <= 0:
            return hours, []
        now = time.time() if now is None else now
        seen, out = set(), []
        for j in self.iter_jobs(newest=True):
            th = j.get("thread")
            newest = th is None or th not in seen
            if th is not None:
                seen.add(th)
            if not newest or j.get("ask_closed") or j.get("status") != "done" or not j.get("replied") or not j.get("ask"):
                continue
            try:
                age = now - datetime.strptime(j.get("finished_at") or "", "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                continue
            if hours * 3600 <= age < ASK_CLOSE_SILENT_DAYS * 86400:
                out.append(j)
        flag = os.path.join(self.root, "ask-seeded.json")
        if not os.path.exists(flag):                      # 처음 켤 때(이 기능이 생기기 전 질문들) — 알림 없이 닫힌 것으로만
            for j in out:
                self.update_job(j["id"], ask_closed=True)
            self.C.write_json(flag, {"at": now_text(), "closed": [j["id"] for j in out]})
            return hours, []
        return hours, out

    def send_out(self, cfg, pw=None):
        """확인 메일 · 접수 신호와 진행 메일(폰·메일 앱에서 온 지시에만, 읽음 표시로) · 회신을 받은편지함에 써 넣는다. 써 넣은 건 수."""
        C = self.C
        try:
            after = float(cfg.get("progress_after_min", PROGRESS_AFTER_MIN) or 0)
        except (TypeError, ValueError):
            after = PROGRESS_AFTER_MIN
        with self.send_lock:
            conn, n = [], 0

            def put(msg, flags=""):
                if not conn:
                    conn.append(C.imap_connect(cfg, pw if pw is not None else C.password(cfg)))
                typ, _ = conn[0].append("INBOX", flags, imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                if typ != "OK":
                    raise OSError("메일함에 넣지 못했습니다(%s)" % typ)

            def numbered(j):
                """회신·확인 전에 대화 번호를 정해 제목에 박고 바로 적어 둔다(넣기에 실패해도 번호가 바뀌지 않게)."""
                with self.lock:
                    if not j.get("thread") or thread_of(j.get("mail_subject")) is None:
                        self.ensure_thread(j, cfg)
                        self.update_job(j["id"], thread=j["thread"], mail_subject=j["mail_subject"])

            try:
                for j in self.iter_jobs(newest=False):
                    st = j.get("status")
                    if st in ("queued", "running") and j.get("progress_ask"):
                        # 폰·메일 앱의 '진행?'(take 가 적어 둠) — 바로 진행 한 줄. 묵은 물음은 버린다, 실패해도 다시 안 보낸다
                        ask_msg = None
                        with self.lock:
                            fresh = self.read_job(j["id"]) or {}
                            asked = fresh.get("progress_ask")
                            if asked and fresh.get("status") in ("queued", "running") and not fresh.get("replied"):
                                fresh_enough = time.time() - float(asked) <= PROGRESS_ASK_TTL
                                if fresh_enough:
                                    ask_msg, mid = self.progress_message(cfg, fresh, self.asked_progress_text(fresh))
                                self.update_job(j["id"], progress_ask=None, **({"asked_msgid": mid} if fresh_enough else {}))
                        if ask_msg is not None:
                            try:
                                put(ask_msg, "(\\Seen)")
                                n += 1
                                C.log("[실행] 진행 답 %s" % j["id"])
                            except Exception as e:
                                C.log("[실행] 진행 답 실패 %s — %s" % (j["id"], e))
                                conn.clear()
                    if st in ("queued", "running") and not j.get("acked") and not j.get("replied") \
                            and j.get("client") != "chat" and self._age(j) < ACK_MAX_AGE:
                        # 폰·메일 앱에서 온 지시에 '받았다' 신호(말풍선으로는 안 보인다). 실패해도 다시 보내지 않는다 — 회신이 어차피 간다
                        msg, mid = self.ack_message(cfg, j)
                        self.update_job(j["id"], acked=True, ack_msgid=mid)
                        try:
                            put(msg, "(\\Seen)")
                            n += 1
                        except Exception as e:
                            C.log("[실행] 접수 신호 실패 %s — %s" % (j["id"], e))
                            conn.clear()
                        continue
                    if st == "running" and after > 0 and not j.get("progressed") and not j.get("replied") \
                            and j.get("client") != "chat" and self._run_age(j) >= after * 60:
                        # 몇 분 넘게 도는 폰·메일 앱 지시에 중간 한 줄 — 잡당 1통, 실패해도 다시 안 보낸다(게이트웨이 send_progress 와 같은 규칙)
                        with self.lock:
                            fresh = self.read_job(j["id"]) or {}
                            if fresh.get("status") != "running" or fresh.get("replied") or fresh.get("progressed"):
                                continue
                            msg, mid = self.progress_message(cfg, fresh, self.progress_text(fresh))
                            self.update_job(j["id"], progressed=True, progress_msgid=mid)
                        try:
                            put(msg, "(\\Seen)")
                            n += 1
                        except Exception as e:
                            C.log("[실행] 진행 메일 실패 %s — %s" % (j["id"], e))
                            conn.clear()
                        continue
                    try:
                        if st == "awaiting_confirm" and not j.get("confirm_sent"):
                            numbered(j)
                            msg, mid = self.confirm_message(cfg, j)
                            put(msg)
                            self.update_job(j["id"], confirm_sent=True, confirm_msgid=mid)
                            n += 1
                        elif st in ("done", "error") and not j.get("replied"):
                            numbered(j)
                            j["ask"] = parse_choices(j.get("result") or "")[1] if st == "done" else None
                            msg, mid = self.reply_message(cfg, j)
                            put(msg)
                            self.update_job(j["id"], ask=j["ask"], replied=True, reply_msgid=mid)
                            n += 1
                            C.log("[실행] 회신 %s (%s)" % (j["id"], st))
                    except Exception as e:
                        tries = int(j.get("send_tries") or 0) + 1
                        C.log("[실행] 메일함에 넣기 실패 %s (%d번째) — %s" % (j["id"], tries, e))
                        if tries >= REPLY_TRIES:
                            if st == "awaiting_confirm":
                                self.update_job(j["id"], status="error", replied=True, send_tries=tries, finished_at=now_text(),
                                                error="확인 메일을 넣지 못해 실행하지 않았습니다: %s" % e)
                            else:
                                self.update_job(j["id"], replied=True, send_tries=tries)
                        else:
                            self.update_job(j["id"], send_tries=tries)
                        while conn:                    # 끊긴 연결일 수 있다 — 다음 건은 새로 연결
                            try:
                                conn.pop().logout()
                            except Exception:
                                pass
                hours, due = self.due_asks(cfg)
                for j in due:                          # 답 없는 질문 닫기 — 잡당 1통, 실패해도 다시 안 보낸다
                    self.update_job(j["id"], ask_closed=True)
                    try:
                        put(self.ask_closed_message(cfg, j, hours)[0])
                        n += 1
                        C.log("[실행] 질문 닫음 %s (답 기한 %d시간 지남)" % (j["id"], int(hours)))
                    except Exception as e:
                        C.log("[실행] 질문 닫기 알림 실패 %s — %s" % (j["id"], e))
                        conn.clear()
            finally:
                for c in conn:
                    try:
                        c.logout()
                    except Exception:
                        pass
        if n:
            try:
                C.BOX.wake.set()
            except Exception:
                pass
        return n

    @staticmethod
    def _age(job):
        try:
            return time.time() - datetime.strptime(job.get("created_at") or "", "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return 1e9

    @staticmethod
    def _run_age(job, now=None):
        """실행을 시작한 지 몇 초(시작 시각이 없으면 0)."""
        try:
            start = datetime.strptime(job.get("started_at") or "", "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return 0.0
        return max(0.0, (time.time() if now is None else now) - start)

    # ---------- 실행

    def next_queued(self):
        return next((j for j in self.iter_jobs(newest=False) if j.get("status") == "queued"), None)

    def run_next(self):
        """대기 작업 하나를 실행한다(있으면 True). 켜져 있지 않거나 막혀 있으면 아무것도 안 한다."""
        cfg, src = self.C.load_cfg()
        if not cfg.get("run_here") or self.blocked(cfg, src):
            return False
        j = self.next_queued()
        if not j:
            return False
        self.run_job(j, cfg)
        self.prune()
        try:
            self.send_out(cfg)
        except Exception as e:
            self.C.log("[실행] 회신 실패 — %s" % e)
        return True

    def run_job(self, job, cfg):
        C, jid = self.C, job["id"]
        if job.get("stop_requested") or jid in self.stop_req:
            self.stop_req.discard(jid)
            self.update_job(jid, status="done", result=STOPPED_BEFORE_START, finished_at=now_text())
            return
        tools = [str(t) for t in job.get("allowed_tools") or READ_TOOLS]
        deny = [str(t) for t in job.get("disallowed_tools") or []]
        bad = next((t for t in tools + deny if not TOOL_RE.match(t)), None)
        claude = self.claude_cmd()
        why = ("허용되지 않는 도구 표기입니다: %s" % bad if bad else
               "이어받을 세션 번호 형식이 올바르지 않습니다." if job.get("resume_id") and not SESSION_RE.match(str(job["resume_id"])) else
               "작업 폴더를 찾을 수 없습니다: %s" % job.get("workdir") if not os.path.isdir(job.get("workdir") or "") else
               NO_CLAUDE if not claude else "")
        if why:
            self.update_job(jid, status="error", error=why, finished_at=now_text())
            return
        logs = os.path.join(self.root, "logs")
        os.makedirs(logs, exist_ok=True)
        pf, of, ef = (os.path.join(logs, "%s.%s" % (jid, x)) for x in ("prompt.txt", "out.json", "err.txt"))
        args = list(claude) + ["-p"]
        if job.get("resume_id"):
            args += ["--resume", str(job["resume_id"])]
        if job.get("attach_dir") and os.path.isdir(job["attach_dir"]):
            args += ["--add-dir", job["attach_dir"]]
        # rtk 훅이 Bash 명령을 'rtk <명령>' 으로 다시 쓰므로 Bash(…) 허용 규칙마다 rtk 접두 짝을 더한다
        tools = tools + ["Bash(rtk %s" % t[5:] for t in tools if t.startswith("Bash(") and not t.startswith("Bash(rtk ")]
        args += ["--output-format", "json", "--permission-mode", "dontAsk", "--allowedTools"] + tools
        if deny:
            args += ["--disallowedTools"] + deny
        proto = os.path.join(C.RES, "chat-protocol.md")
        if job.get("chat") and os.path.isfile(proto):
            args += ["--append-system-prompt-file", proto]   # 사람에게 물을 자리에서 ```choices 블록을 쓰게 하는 규칙
        self.update_job(jid, status="running", started_at=now_text())
        self.current = jid
        C.log("[실행] 시작 %s (폴더 %s%s)" % (jid, job.get("workdir"), ", 세션 %s 이어받기" % job["resume_id"] if job.get("resume_id") else ""))
        t0, tree, stopped, finished = time.time(), None, False, False
        try:
            prompt = str(job.get("prompt") or "")
            if prompt.lstrip().startswith("/") and "Skill" not in tools:
                prompt = SLASH_GUARD + prompt
            with open(pf, "wb") as f:                     # 줄바꿈을 바꾸지 않고 그대로(stdin 으로 넘긴다)
                f.write(prompt.encode("utf-8"))
            mcp = self.mcp_config(job, cfg, os.path.join(logs, jid))
            if mcp:
                at = args.index("-p")
                args[at:at] = ["--mcp-config", mcp]          # -p 앞에(--allowedTools 처럼 여러 값을 받는 옵션 뒤에 두지 않는다)
            env = dict(os.environ)
            if not IS_WIN:                                   # Finder 로 띄운 앱은 PATH 가 짧다 — claude(node) 가 돌 수 있게
                extra = [os.path.dirname(args[0])] + [os.path.dirname(find_tool(t)) for t in ("npx", "uvx")] + \
                    ["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin")]   # MCP 서버(npx·uvx)와 그것이 부르는 node 도
                env["PATH"] = os.pathsep.join([p for p in extra if p] + [env.get("PATH") or "/usr/bin:/bin"])
            with open(pf, "rb") as fin, open(of, "wb") as fout, open(ef, "wb") as ferr:
                kw = {"creationflags": CREATE_NO_WINDOW} if IS_WIN else {"start_new_session": True}
                p = subprocess.Popen(args, stdin=fin, stdout=fout, stderr=ferr, cwd=job["workdir"], env=env, **kw)
                tree = ProcTree(p)
                deadline = t0 + int(cfg.get("run_timeout_sec") or TIMEOUT_SEC)
                while True:
                    try:
                        p.wait(1)
                        finished = True
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if jid in self.stop_req:
                        stopped = True
                        break
                    if time.time() >= deadline:
                        break
                if not finished:
                    tree.kill()
            ms = int((time.time() - t0) * 1000)
            if stopped:
                self.stop_req.discard(jid)
                self.update_job(jid, keep_canceled=True, status="done", result=STOPPED_MIDWAY, duration_ms=ms, finished_at=now_text())
                C.log("[실행] 멈춤 %s (%d초에 끊음)" % (jid, ms // 1000))
                return
            if not finished:
                self.update_job(jid, keep_canceled=True, status="error", duration_ms=ms, finished_at=now_text(),
                                error="제한 시간(%d초)을 넘겨 중단했습니다." % int(cfg.get("run_timeout_sec") or TIMEOUT_SEC))
                C.log("[실행] 시간 초과 %s" % jid)
                return
            res = read_result(of)
            if not res:
                err = ""
                try:
                    with open(ef, "rb") as f:
                        err = f.read().decode("utf-8", "replace").strip()
                except OSError:
                    pass
                self.update_job(jid, keep_canceled=True, status="error", duration_ms=ms, finished_at=now_text(),
                                error=err[-2000:] or "실행 결과를 읽지 못했습니다.")
                C.log("[실행] 실패 %s — 결과를 읽지 못함" % jid)
                return
            ok = not res.get("is_error")
            self.update_job(jid, keep_canceled=True, status="done" if ok else "error", result=str(res.get("result") or ""),
                            cost_usd=res.get("total_cost_usd"), duration_ms=res.get("duration_ms") or ms,
                            denials=list(res.get("permission_denials") or []), session_id=str(res.get("session_id") or ""),
                            finished_at=now_text(), **({} if ok else {"error": "실행 중 오류가 발생했습니다."}))
            C.log("[실행] %s %s (%d초)" % ("완료" if ok else "오류 응답", jid, ms // 1000))
        except Exception as e:
            self.update_job(jid, keep_canceled=True, status="error", error="%s" % e, finished_at=now_text(),
                            duration_ms=int((time.time() - t0) * 1000))
            C.log("[실행] 예외 %s — %s" % (jid, traceback.format_exc(limit=3)))
        finally:
            self.current = ""
            if tree:
                tree.close()
            for f in (pf, of, ef, os.path.join(logs, jid + ".mcp.json"), os.path.join(logs, jid + ".pw.json")):
                try:
                    os.remove(f)
                except OSError:
                    pass

    # ---------- 돌리기

    def start(self):
        if self.started:
            return
        self.started = True
        threading.Thread(target=self._poll_loop, daemon=True, name="runner-poll").start()
        threading.Thread(target=self._work_loop, daemon=True, name="runner-work").start()
        self.jira.start()                        # 꺼져 있으면 설정만 가끔 본다

    def _poll_loop(self):
        while True:
            try:
                self.cycle()
            except Exception as e:
                self.error = "메일함 확인 실패 — %s" % e
                self.C.log("[실행] 한 바퀴 실패 — %s" % e)
            cfg, _ = self.C.load_cfg()
            self.wake.wait(max(5, int(cfg.get("poll_sec", 20))) if cfg.get("run_here") else 30)
            self.wake.clear()

    def _work_loop(self):
        while True:
            self.kick.wait(3)
            self.kick.clear()
            try:
                if self.run_next():
                    self.kick.set()
            except Exception:
                self.C.log("[실행] 작업 실패 — %s" % traceback.format_exc(limit=3))


def _iso_epoch(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _progress_tool(name, inp):
    for k in ("description", "command", "file_path", "notebook_path", "pattern", "url", "query", "skill", "prompt", "path"):
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v if k == "description" else "%s %s" % (name, v)
    return str(name or "")


def progress_line(lines, since, minutes):
    """세션 기록 줄들 → '진행 중 · N분째 — <지금 하는 일> · 할 일 a/b' (진행 메일 본문).
    게이트웨이(mail-gateway.py progress_line)와 같은 규칙 — 한쪽을 고치면 같이 고친다."""
    now, todos = "", None
    for ln in lines or []:
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant" or ev.get("isSidechain") or ev.get("parent_tool_use_id"):
            continue
        if since and _iso_epoch(ev.get("timestamp")) < since:
            continue
        content = (ev.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and (c.get("text") or "").strip():
                now = next(l for l in c["text"].splitlines() if l.strip())
            elif c.get("type") == "tool_use":
                inp = c.get("input") if isinstance(c.get("input"), dict) else {}
                if c.get("name") == "TodoWrite":
                    todos = [t for t in inp.get("todos") or [] if isinstance(t, dict)]
                    cur = next((t for t in todos if t.get("status") == "in_progress"), None)
                    if cur:
                        now = str(cur.get("activeForm") or cur.get("content") or "")
                else:
                    now = _progress_tool(c.get("name"), inp)
    now = re.sub(r"\s+", " ", re.sub(r"\*\*|`", "", now)).strip().lstrip("#-*• ").strip()
    if len(now) > 80:
        now = now[:79] + "…"
    line = "진행 중 · %d분째" % minutes
    if now:
        line += " — " + now
    if todos:
        line += " · 할 일 %d/%d" % (sum(1 for t in todos if t.get("status") == "completed"), len(todos))
    return line


def read_result(path):
    """claude -p --output-format json 의 결과(한 덩어리 JSON, 아니면 마지막 JSON 줄)."""
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace").strip()
    except OSError:
        return None
    if not text:
        return None
    for cand in [text] + list(reversed(text.splitlines())):
        try:
            d = json.loads(cand)
        except ValueError:
            continue
        if isinstance(d, dict) and ("result" in d or "is_error" in d):
            return d
    return None


def spent_today(jobs_dir, audit_path="", sender="", now=None):
    """오늘(이 PC 날짜) 받은 작업들의 cost_usd 합 — 작업 파일 + (게이트웨이면) 지시 실행 기록. 게이트웨이 spent_today 와 같은 셈.
    sender 가 있으면 그 주소만."""
    day = (now or datetime.now()).strftime("%Y-%m-%d")
    who = (sender or "").strip().lower()
    seen, total = set(), 0.0

    def add(jid, created, frm, cost):
        nonlocal total
        if jid in seen:
            return
        seen.add(jid)
        if str(created or "")[:10] == day and (not who or str(frm or "").strip().lower() == who) \
                and isinstance(cost, (int, float)):
            total += float(cost)
    try:
        names = [n for n in os.listdir(jobs_dir) if n.endswith(".json")] if jobs_dir else []
    except OSError:
        names = []
    for n in names:
        try:
            with open(os.path.join(jobs_dir, n), encoding="utf-8-sig") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(j, dict) and j.get("id"):
            add(j["id"], j.get("created_at"), j.get("mail_from"), j.get("cost_usd"))
    try:
        with open(audit_path, encoding="utf-8") as f:
            for line in f:
                if day not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("id"):
                    add(r["id"], r.get("created"), r.get("from"), r.get("cost_usd"))
    except (OSError, TypeError):
        pass
    return round(total, 4)


def cost_limit(cfg, key="daily_cost_usd"):
    try:
        return max(0.0, float(cfg.get(key) or 0))
    except (TypeError, ValueError):
        return 0.0


COST_BLOCKED = ("오늘 쓴 비용($%.2f)이 하루 한도($%.2f)에 닿아 새 지시를 실행하지 않았습니다 — 내일 다시 보내거나 "
                "⚙ 설정의 하루 비용 한도를 올리세요.")


def parse_dirs(text):
    """'키=폴더' 줄들 → {키: 폴더}. 지시 제목의 @키 로 그 폴더에서 실행한다."""
    if isinstance(text, dict):
        text = "\n".join("%s=%s" % kv for kv in text.items())
    out = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        k, sep, v = line.partition("=")
        k, v = k.strip().lstrip("@"), v.strip()
        if not sep or not re.fullmatch(r"\w{1,32}", k) or not v:
            raise ValueError("작업 폴더 목록은 한 줄에 '키=폴더' 로 적어 주세요: %s" % line)
        if not os.path.isdir(v):
            raise ValueError("작업 폴더가 없습니다: %s" % v)
        out[k] = os.path.abspath(v)
    return out


def mac_bin_dirs():
    """맥에서 Finder 로 띄운 앱은 PATH 가 짧다 — Node(npx)·uv(uvx)가 흔히 깔리는 자리(homebrew · nvm 최신 · volta · cargo · ~/.local/bin)."""
    home = os.path.expanduser("~")
    nvm = os.path.join(home, ".nvm", "versions", "node")
    try:
        nvm_bins = [os.path.join(nvm, v, "bin") for v in sorted(os.listdir(nvm), key=_version_key, reverse=True)]
    except OSError:
        nvm_bins = []
    return ["/opt/homebrew/bin", "/usr/local/bin", os.path.join(home, ".local", "bin")] + nvm_bins + \
        [os.path.join(home, ".volta", "bin"), os.path.join(home, ".cargo", "bin")]


def _version_key(v):
    return [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", v)]


def find_tool(name):
    """PATH 에서 실행 파일을 찾는다(윈도우는 npx.cmd 도). 맥·리눅스는 흔한 설치 자리도 본다."""
    path = shutil.which(name)
    if not path and not IS_WIN:
        path = shutil.which(name, path=os.pathsep.join(mac_bin_dirs()))
    return path or ""


def find_browser():
    """전용 브라우저로 쓸 것 → (실행 파일, Playwright channel). Chrome, 없으면(윈도우) Edge. 둘 다 없으면 ("", "")."""
    if IS_WIN:
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        cands = [(os.path.join(r, "Google", "Chrome", "Application", "chrome.exe"), "chrome") for r in roots if r] + \
                [(os.path.join(r, "Microsoft", "Edge", "Application", "msedge.exe"), "msedge") for r in roots if r]
    elif IS_MAC:
        apps = [(os.path.join("Google Chrome.app", "Contents", "MacOS", "Google Chrome"), "chrome"),
                (os.path.join("Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge"), "msedge")]
        cands = [(os.path.join(root, app), ch) for app, ch in apps for root in ("/Applications", os.path.expanduser("~/Applications"))]
    else:
        cands = [(shutil.which("google-chrome") or "", "chrome")]
    return next(((p, ch) for p, ch in cands if p and os.path.isfile(p)), ("", ""))


def cdp_live():
    """로그인 창(원격 디버깅 포트)이 떠 있는지."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # 회사 프록시를 타지 않게
        with opener.open(BROWSER_CDP + "/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def has_skill(workdir, name):
    """작업 폴더(.claude) 나 사용자 폴더(~/.claude)에 그 이름의 스킬·명령이 있는지 — '/jira 키' 를 그대로 넘길 수 있는지."""
    for base in (os.path.join(workdir or "", ".claude"), os.path.join(os.path.expanduser("~"), ".claude")):
        if os.path.isfile(os.path.join(base, "skills", name, "SKILL.md")) or os.path.isfile(os.path.join(base, "commands", name + ".md")):
            return True
    return False
