# -*- coding: utf-8 -*-
"""
디스패치 대화 — 메일을 메신저처럼 보는 PC 화면.

일을 맡기고 답을 받는 통로는 여전히 메일이다(메일 게이트웨이 mail-gateway.py 가 지시 메일을 받아 Claude 를 돌리고 회신한다).
이 앱은 그 메일함을 IMAP 으로 읽어 대화 번호 [T12] 별 대화방으로 묶어 말풍선으로 보여 주고, 입력한 말을 메일로 보낸다.
PC 끼리 직접 연결할 필요가 없다 — 메일 서버만 닿으면 어느 PC 에서든 같은 대화를 본다.

    python chat.py              서버를 띄우고 Edge 앱 창으로 연다(이미 떠 있으면 창만 연다)
    python chat.py --serve      창 없이 서버만(이 PC 에서는 매크로 허브의 svc_dispatch_chat 이 이렇게 띄운다)
    DispatchChat.exe            다른 PC 용(build.py 로 만든다) — 처음 열면 메일 계정을 묻는다

- 화면은 127.0.0.1 에만 연다. 보내기 같은 POST 는 띄울 때마다 새로 만드는 토큰이 있어야 한다(화면에만 심는다).
- 계정: 이 저장소 안에서 돌면 키트 공통 설정(저장소 맨 위 config.local.json 의 mail · dispatch 갈래, 비밀번호 DPAPI)을
  그대로 읽는다. 아니면(다른 PC) %APPDATA%\\DispatchChat\\config.json — 비밀번호는 그 PC 사용자의 DPAPI 로 암호화해 둔다.
- 봇 메일은 게이트웨이가 붙이는 X-Dispatch-* 헤더로 알아본다(선택지는 X-Dispatch-Ask). 표식 이전의 옛 회신은 꼬리말로 짐작한다.
- 표준 라이브러리만 쓴다(PyInstaller 로 exe 한 파일 — 그래서 kit.py 를 import 하지 않는다).
  DPAPI·IMAP 폴더 이름 풀기는 kit.py · mail-gateway.py 와 같은 코드를 옮겨 왔다.
"""
import base64
import ctypes
import email
import email.header
import email.policy
import email.utils
import http.server
import imaplib
import json
import os
import re
import secrets
import smtplib
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from ctypes import wintypes
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import parse_qs, urlparse

FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))     # ui.html 이 있는 곳(exe 면 풀린 임시 폴더)
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
KIT_CFG = os.path.join(REPO_ROOT, "config.local.json")                         # 이 저장소 안에서 돌 때만 있다
JOBS_DIR = os.path.join(REPO_ROOT, "inbox", "jobs")
APPDATA = os.path.join(os.environ.get("APPDATA") or HERE, "DispatchChat")
LOCALDATA = os.path.join(os.environ.get("LOCALAPPDATA") or HERE, "DispatchChat")
OWN_CFG = os.path.join(APPDATA, "config.json")
LOG_PATH = os.path.join(LOCALDATA, "chat.log")
PORT = int(os.environ.get("DISPATCH_CHAT_PORT") or 8620)   # 그 PC 에서 8620 이 이미 쓰이면 바꿔 띄운다

# 회사마다 다른 값(서버·주소·폴더)은 기본값에 두지 않는다 — 키트 설정이나 처음 화면에서 넣는다.
DEFAULTS = {
    "user": "", "login_user": "", "password_enc": "",
    "imap_host": "", "imap_port": 993, "imap_mode": "ssl",
    "smtp_host": "", "smtp_port": 587, "smtp_mode": "starttls",
    "ca_bundle": "",          # 사내 TLS 검사 프록시가 있으면 그 루트 인증서(.pem) 경로
    # 보내는 방법: smtp = 실제 발송(내게 보내기). append = 받은편지함에 바로 써 넣기(발송이 막혔거나,
    # 자기에게 보낸 메일을 메일 규칙이 딴 폴더로 옮기는 서버에서)
    "send_mode": "smtp",
    # 게이트웨이와 같은 폴더를 본다. 자기에게 보낸 메일이 딴 폴더로 가는 서버면 그 폴더도 넣는다(dispatch.folders)
    "folders": ["INBOX"],
    "tags": ["#c", "c"], "write_tags": ["#cw", "cw"],
    "workdir_keys": [],
    # 이슈 처리 칸 — issue_prefix(예: "PROJ-")를 넣어야 보인다. 보내는 제목은 '#cw <issue_command> PROJ-123'
    "issue_prefix": "",
    "issue_command": "/issue",
    "lookback_days": 14,
    "poll_sec": 20,
}

for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(LOCALDATA, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except Exception:
            pass


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ----------------------------------------------------------------- DPAPI (mail-gateway.py 와 같은 코드)

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def dpapi_protect(text):
    blob_in, _keep = _blob(text.encode("utf-8"))
    blob_out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob_in), "DispatchChat", None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptProtectData 실패")
    try:
        return base64.b64encode(ctypes.string_at(blob_out.pbData, blob_out.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def dpapi_unprotect(b64):
    blob_in, _keep = _blob(base64.b64decode(b64))
    blob_out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptUnprotectData 실패 — 다른 사용자/PC 에서 만든 설정입니다. 계정을 다시 넣어 주세요.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


# ----------------------------------------------------------------- 설정

def read_kit_cfg():
    """키트 공통 설정(config.local.json)에서 이 앱이 쓰는 값만. 없거나 메일 주소가 없으면 None."""
    full = read_json(KIT_CFG)
    if not isinstance(full, dict):
        return None
    mail = full.get("mail") if isinstance(full.get("mail"), dict) else {}
    d = full.get("dispatch") if isinstance(full.get("dispatch"), dict) else {}
    if not mail.get("user"):
        return None
    out = {}
    for k in ("user", "login_user", "password_enc", "imap_host", "imap_port", "imap_mode",
              "smtp_host", "smtp_port", "smtp_mode", "ca_bundle"):
        if mail.get(k) not in (None, ""):
            out[k] = mail[k]
    for k in ("folders", "tags", "write_tags", "issue_prefix", "issue_command", "lookback_days", "poll_sec"):
        if d.get(k) not in (None, ""):
            out[k] = d[k]
    if isinstance(d.get("workdir_keys"), dict):
        out["workdir_keys"] = [str(k) for k in d["workdir_keys"]]
    # 게이트웨이가 회신을 INBOX 에 써 넣는 곳(reply_mode=append)이면 지시도 같은 방법으로 넣는다
    mode = d.get("chat_send_mode") or d.get("reply_mode")
    if mode in ("smtp", "append"):
        out["send_mode"] = mode
    return out


def load_cfg():
    """(설정, 출처). 이 PC 의 앱 설정에 계정이 있으면 그것을, 아니면(이 저장소 안이면) 키트 공통 설정을 쓴다."""
    cfg = dict(DEFAULTS)
    own = read_json(OWN_CFG) or {}
    kc = read_kit_cfg() if not own.get("user") else None
    src = "own"
    if kc:
        src = "kit"
        cfg.update(kc)
    cfg.update({k: v for k, v in own.items() if v not in (None, "")})
    return cfg, src


def password(cfg):
    return dpapi_unprotect(cfg["password_enc"]) if cfg.get("password_enc") else ""


# ----------------------------------------------------------------- 메일 연결

def imap_utf7_decode(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "&":
            j = s.find("-", i)
            if j < 0:
                out.append(s[i:])
                break
            if j == i + 1:
                out.append("&")
            else:
                chunk = s[i + 1:j].replace(",", "/")
                try:
                    out.append(base64.b64decode(chunk + "=" * ((4 - len(chunk) % 4) % 4)).decode("utf-16-be"))
                except Exception:
                    out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def resolve_folders(m, wanted):
    typ, boxes = m.list()
    actual = []
    for b in (boxes or []):
        mt = re.search(r'"([^"]*)"\s*$', b.decode("utf-8", "replace"))
        if mt and mt.group(1) not in (".", ""):
            actual.append(mt.group(1))
    out = []
    for w in wanted:
        for a in actual:
            if a == w or a.lower() == w.lower() or imap_utf7_decode(a).lower() == w.lower():
                if a not in out:
                    out.append(a)
                break
    return out or ["INBOX"]


def login_id(cfg):
    return cfg.get("login_user") or cfg["user"]


def ssl_context(cfg):
    ctx = ssl.create_default_context()
    ca = str(cfg.get("ca_bundle") or "").strip()
    if ca and os.path.exists(os.path.expandvars(ca)):
        ctx.load_verify_locations(os.path.expandvars(ca))
    return ctx


def imap_connect(cfg, pw):
    if not cfg.get("imap_host"):
        raise ValueError("IMAP 서버 주소가 설정되지 않았습니다")
    ctx = ssl_context(cfg)
    if cfg.get("imap_mode", "ssl") == "ssl":
        m = imaplib.IMAP4_SSL(cfg["imap_host"], int(cfg["imap_port"]), ssl_context=ctx, timeout=20)
    else:
        m = imaplib.IMAP4(cfg["imap_host"], int(cfg["imap_port"]), timeout=20)
        if cfg.get("imap_mode") == "starttls":
            m.starttls(ctx)
    m.login(login_id(cfg), pw)
    return m


def smtp_send(cfg, pw, msg):
    if not cfg.get("smtp_host"):
        raise ValueError("SMTP 서버 주소가 설정되지 않았습니다 — 보내는 방법을 'append' 로 두거나 서버를 넣어 주세요")
    ctx = ssl_context(cfg)
    if cfg.get("smtp_mode") == "ssl":
        s = smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)
        s.ehlo()
        if cfg.get("smtp_mode", "starttls") == "starttls":
            s.starttls(context=ctx)
            s.ehlo()
    try:
        s.login(login_id(cfg), pw)
        s.send_message(msg)
    finally:
        try:
            s.quit()
        except Exception:
            pass


# ----------------------------------------------------------------- 메일 → 대화

THREAD_RE = re.compile(r"\[T(\d{1,6})\]")
REPLY_PREFIX_RE = re.compile(r"(?i)^\s*(re|fw|fwd|회신|답장)\s*[:：]\s*")
# 서명·인용 머리줄(아이폰 '2026. 10. 6. 오후 4:12, 이름 <a@b> 작성:' 포함) — mail-gateway.SIG_RE 와 같은 규칙
SIG_RE = re.compile(
    r"(?m)^\s*(--\s*$|보낸 사람:|보낸사람:|From:|-----Original Message-----|iPhone에서 보냄|내 iPhone에서 보냄|"
    r"Sent from my |Get Outlook for |\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\..*작성:\s*$|On .+ wrote:\s*$)")
ASK_SPLIT = "─" * 16


def decode_hdr(raw):
    if not raw:
        return ""
    out = []
    for part, cs in email.header.decode_header(str(raw)):
        out.append(part.decode(cs or "utf-8", "replace") if isinstance(part, bytes) else part)
    return "".join(out).replace("\r", "").replace("\n", " ").strip()


def strip_re(subject):
    s = subject
    for _ in range(5):
        n = REPLY_PREFIX_RE.sub("", s)
        if n == s:
            break
        s = n
    return s.strip()


def match_tag(subject, cfg):
    cands = [(t, "write") for t in cfg.get("write_tags") or []] + [(t, "read") for t in cfg.get("tags") or []]
    for t, mode in sorted(cands, key=lambda x: len(x[0]), reverse=True):
        if subject == t or (subject.startswith(t) and subject[len(t):len(t) + 1].isspace()):
            return t, mode
    return None, None


def plain_body(msg):
    def payload(part):
        try:
            data = part.get_payload(decode=True) or b""
            return data.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            return ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                return payload(part)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return re.sub(r"<[^>]+>", " ", payload(part))
        return ""
    return payload(msg)


def said_text(body):
    """사람이 쓴 메일에서 새로 쓴 부분만(서명·인용 아래, '>' 줄 버림)."""
    body = (body or "").replace("\r", "")
    cut = SIG_RE.search(body)
    if cut:
        body = body[:cut.start()]
    return "\n".join(l for l in body.splitlines() if not l.lstrip().startswith(">")).strip()


def bot_parts(body):
    """봇 회신 글자 본문 → (본문, 꼬리말). 맨 위 ☐ 선택지 줄은 X-Dispatch-Ask 로 따로 받으므로 뗀다."""
    body = (body or "").replace("\r", "")
    if ASK_SPLIT in body:
        body = body.split(ASK_SPLIT, 1)[1]
    i = body.rfind("\n--\n")
    text, foot = (body[:i], body[i + 4:]) if i >= 0 else (body, "")
    return text.strip(), foot.strip()


def parse_message(raw, cfg):
    """메일 원문 → 대화 메시지 dict. 지시 태그로 시작하지 않는 메일이면 None."""
    msg = email.message_from_bytes(raw)
    subject = decode_hdr(msg.get("Subject"))
    clean = strip_re(subject)
    tag, mode = match_tag(clean, cfg)
    if not tag:
        return None
    try:
        ts = email.utils.parsedate_to_datetime(msg.get("Date")).timestamp()
    except Exception:
        ts = time.time()
    refs = re.findall(r"<[^<>]+>", " ".join(str(msg.get(h) or "") for h in ("In-Reply-To", "References")))
    body = plain_body(msg)
    tm = THREAD_RE.search(clean)
    th = decode_hdr(msg.get("X-Dispatch-Thread"))
    thread = int(th if th.isdigit() else (tm.group(1) if tm else 0)) or None
    rest = THREAD_RE.sub("", clean[len(tag):]).strip()
    is_bot = msg.get("X-Dispatch") == "bot" or (
        subject.lower().startswith("re:") and "\n--\n" in body.replace("\r", "") and "작업 폴더 " in body)
    m = {"id": (msg.get("Message-ID") or "").strip(), "ts": ts, "subject": clean, "rest": rest, "mode": mode, "tag": tag,
         "thread": thread, "refs": refs, "bot": is_bot}
    if is_bot:
        m["kind"] = msg.get("X-Dispatch-Kind") or ("confirm" if "실행 전에 확인합니다" in body else "reply")
        m["status"] = msg.get("X-Dispatch-Status") or ""
        m["text"], m["foot"] = bot_parts(body)
        ask = None
        if msg.get("X-Dispatch-Ask"):
            try:
                # 긴 헤더는 메일 규칙대로 =?utf-8?q?…?= 로 접혀 오므로 먼저 푼다
                ask = json.loads(base64.b64decode(re.sub(r"\s+", "", decode_hdr(msg["X-Dispatch-Ask"]))).decode("utf-8"))
            except Exception:
                ask = None
        m["ask"] = ask
    else:
        said = said_text(body)
        is_reply = subject.lower().startswith("re:") or tm is not None
        # 첫 지시는 제목+본문이 지시문이고, 이어지는 말은 본문이 곧 말이다(비면 제목)
        m["text"] = said if (is_reply and said) else "\n".join(x for x in (rest, said) if x).strip()
    return m


def build_threads(msgs, jobs=None):
    """메시지들을 대화방으로 묶는다. 번호가 아직 없는 첫 지시는 그 지시에 답한 봇 메일(In-Reply-To)로 번호를 찾는다."""
    by_id = {m["id"]: m for m in msgs if m["id"]}
    for m in msgs:                               # 봇 회신이 가리키는 원본 지시에 번호를 물려준다
        if m["thread"]:
            for r in m["refs"]:
                o = by_id.get(r)
                if o and not o["thread"]:
                    o["thread"] = m["thread"]
    threads = {}
    for m in sorted(msgs, key=lambda x: x["ts"]):
        key = "T%d" % m["thread"] if m["thread"] else "m:" + (m["id"] or str(m["ts"]))
        if not m["thread"] and m["bot"]:
            continue                             # 번호 없는 옛 봇 메일은 붙일 곳이 없다
        t = threads.setdefault(key, {"key": key, "no": m["thread"], "msgs": [], "mode": m["mode"], "tag": m["tag"], "title": ""})
        t["msgs"].append(m)
        if m["mode"] == "write":
            t["mode"], t["tag"] = "write", m["tag"]
    out = []
    for t in threads.values():
        first = next((m for m in t["msgs"] if not m["bot"]), None)
        title = (first["text"].split("\n", 1)[0] if first else "") or (t["msgs"][0]["rest"] if t["msgs"] else "")
        title = re.sub(r"^@\w+\s+", "", title)          # 제목에선 작업 폴더 표시(@docs)를 뺀다
        t["title"] = title[:80] or "(제목 없음)"
        last = t["msgs"][-1]
        if last["bot"]:
            if last.get("kind") == "confirm":
                st = "confirm"
            elif last.get("status") == "error":
                st = "error"
            elif last.get("ask"):
                st = "ask"
            else:
                st = "done"
        else:
            st = "sent"
        job = (jobs or {}).get(t["no"]) if t["no"] else None
        if job in ("queued", "running"):
            st = job
        t["status"] = st
        t["ts"] = last["ts"]
        t["ask"] = last.get("ask") if last["bot"] else None
        t["last"] = (last["text"] or "").split("\n", 1)[0][:90]
        t["last_bot"] = last["bot"]
        t["reply_to"] = next((m["id"] for m in reversed(t["msgs"]) if m["bot"] and m["id"]), "")
        out.append(t)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def local_jobs():
    """이 PC 에서 돌면 작업 인박스로 '대기·실행 중' 을 덧붙인다(다른 PC 에선 없다)."""
    out = {}
    try:
        names = sorted(os.listdir(JOBS_DIR), reverse=True)[:80]
    except OSError:
        return out
    for fn in names:
        j = read_json(os.path.join(JOBS_DIR, fn)) if fn.endswith(".json") else None
        if j and j.get("thread") and j["thread"] not in out:
            out[j["thread"]] = j.get("status")
    return out


# ----------------------------------------------------------------- 메일함 감시

class Box:
    def __init__(self):
        self.lock = threading.Lock()
        self.msgs = {}            # Message-ID(또는 폴더#uid) → 메시지
        self.seen = {}            # (폴더, uidvalidity) → 이미 본 uid 집합
        self.echo = []            # 보냈지만 아직 메일함에서 못 본 내 말(바로 화면에 보이게)
        self.error = ""
        self.polled = 0.0
        self.wake = threading.Event()
        self.version = 0

    def poll(self):
        cfg, _src = load_cfg()
        if not cfg.get("user") or not cfg.get("password_enc"):
            self.error = "setup"
            return
        pw = password(cfg)
        since = (datetime.now() - timedelta(days=int(cfg.get("lookback_days", 14)))).strftime("%d-%b-%Y")
        m = imap_connect(cfg, pw)
        changed = False
        try:
            for box in resolve_folders(m, cfg.get("folders") or ["INBOX"]):
                typ, _ = m.select('"%s"' % box, readonly=True)
                if typ != "OK":
                    continue
                uv = (m.untagged_responses.get("UIDVALIDITY") or [b"0"])[0]
                seen = self.seen.setdefault((box, uv), set())
                typ, data = m.uid("SEARCH", "SINCE", since)
                if typ != "OK" or not data or not data[0]:
                    continue
                new = [u.decode() for u in data[0].split() if u.decode() not in seen]
                for i in range(0, len(new), 50):
                    chunk = new[i:i + 50]
                    typ, hdrs = m.uid("FETCH", ",".join(chunk), "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
                    want = []
                    for item in hdrs or []:
                        if not isinstance(item, tuple):
                            continue
                        mu = re.search(rb"UID (\d+)", item[0])
                        subj = strip_re(decode_hdr(email.message_from_bytes(item[1]).get("Subject")))
                        if mu and match_tag(subj, cfg)[0]:
                            want.append(mu.group(1).decode())
                    for u in want:
                        typ, full = m.uid("FETCH", u, "(BODY.PEEK[])")
                        if typ == "OK" and full and isinstance(full[0], tuple):
                            pm = parse_message(full[0][1], cfg)
                            if pm:
                                with self.lock:
                                    self.msgs[pm["id"] or "%s#%s" % (box, u)] = pm
                                    self.echo = [e for e in self.echo if e["id"] != pm["id"]]
                                changed = True
                    seen.update(chunk)
        finally:
            try:
                m.logout()
            except Exception:
                pass
        self.error = ""
        self.polled = time.time()
        if changed:
            self.version += 1

    def loop(self):
        while True:
            try:
                self.poll()
            except Exception as e:
                self.error = "%s" % e
                log("메일함 읽기 실패 — %s" % e)
            cfg, _ = load_cfg()
            self.wake.wait(max(5, int(cfg.get("poll_sec", 20))))
            self.wake.clear()

    def threads(self):
        with self.lock:
            msgs = [dict(m) for m in self.msgs.values()] + [dict(e) for e in self.echo]
        return build_threads(msgs, local_jobs())


BOX = Box()


def compose(cfg, data, threads):
    """화면에서 온 말 → (제목, 본문, In-Reply-To, 화면용 메시지)."""
    text = (data.get("text") or "").strip()
    picks = [int(x) for x in data.get("picks") or [] if str(x).isdigit()]
    key = data.get("key") or ""
    tag_read = (cfg.get("tags") or ["#c"])[0]
    tag_write = (cfg.get("write_tags") or ["#cw"])[0]
    if key:                                         # 이어서 말하기 / 선택지 답
        t = next((x for x in threads if x["key"] == key), None)
        if not t or not t["no"]:
            raise ValueError("아직 번호가 없는 대화입니다 — 첫 회신이 오면 이어서 말할 수 있습니다")
        if data.get("stop"):
            body = "멈춤"
        else:
            body = (",".join(str(p) for p in sorted(set(picks))) + (" " if picks and text else "") + text).strip()
        if not body:
            raise ValueError("보낼 말이 없습니다")
        subject = "Re: %s [T%d] %s" % (t["tag"] or tag_read, t["no"], t["title"])[:160]
        shown = "멈춤" if data.get("stop") else ((("☑ " + " ☑ ".join(str(p) for p in sorted(set(picks)))) if picks else "") +
                                                 ("\n" if picks and text else "") + text)
        return subject, body, t.get("reply_to") or "", {"thread": t["no"], "mode": t["mode"], "tag": t["tag"], "text": shown}
    issue = (data.get("issue") or "").strip()
    if issue:                                       # 이슈 처리 시작 — issue_prefix 가 있어야 켜진다
        prefix = (cfg.get("issue_prefix") or "").strip()
        command = (cfg.get("issue_command") or "").strip()
        if not prefix or not command:
            raise ValueError("이슈 처리 칸이 꺼져 있습니다 — 설정에 이슈 키 앞부분(issue_prefix)을 넣어 주세요")
        k = issue.upper() if re.match(r"^[A-Za-z]", issue) else prefix + issue
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", k):
            raise ValueError("이슈 키 형식이 아닙니다 (예: %s123)" % prefix)
        subject = "%s %s %s" % (tag_write, command, k)
        return subject, "", "", {"thread": None, "mode": "write", "tag": tag_write, "text": "이슈 %s 처리 시작" % k}
    if not text:
        raise ValueError("보낼 말이 없습니다")
    mode = "write" if data.get("mode") == "write" else "read"
    tag = tag_write if mode == "write" else tag_read
    folder = (data.get("folder") or "").strip().lstrip("@")
    first, _, rest = text.partition("\n")
    head = tag + (" @" + folder if folder else "")
    subject = "%s %s" % (head, first.strip()[:120])
    body = ((first.strip() + "\n") if len(first.strip()) > 120 else "") + rest.strip()
    return subject, body, "", {"thread": None, "mode": mode, "tag": tag, "text": text}


def send(data):
    cfg, _ = load_cfg()
    subject, body, reply_to, shown = compose(cfg, data, BOX.threads())
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["user"], cfg["user"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    mid = email.utils.make_msgid(domain=cfg["user"].split("@", 1)[-1] if "@" in cfg["user"] else None)
    msg["Message-ID"] = mid
    msg["X-Dispatch-Client"] = "chat"
    if reply_to:
        msg["In-Reply-To"] = msg["References"] = reply_to
    msg.set_content(body or " ")
    pw = password(cfg)
    if cfg.get("send_mode") == "append":
        m = imap_connect(cfg, pw)
        try:
            m.append("INBOX", "", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        finally:
            m.logout()
    else:
        smtp_send(cfg, pw, msg)
    echo = dict(shown, id=mid, ts=time.time(), subject=subject, rest="", refs=[reply_to] if reply_to else [], bot=False, pending=True)
    with BOX.lock:
        BOX.echo.append(echo)
    BOX.version += 1
    log("보냄 %s" % subject[:80])
    threading.Timer(3, BOX.wake.set).start()       # 게이트웨이가 받아 회신하면 곧 보이게
    return {"ok": True, "subject": subject}


# ----------------------------------------------------------------- 화면 서버

TOKEN = secrets.token_urlsafe(24)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json; charset=utf-8"):
        data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):                             # DNS 리바인딩 막기 — 이 PC 주소로 온 요청만
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        if u.path == "/":
            with open(os.path.join(RES, "ui.html"), encoding="utf-8") as f:
                html = f.read().replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if u.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if u.path == "/api/state":
            cfg, src = load_cfg()
            return self._send(200, {
                "user": cfg.get("user"), "source": src, "error": BOX.error, "polled": BOX.polled, "version": BOX.version,
                "folders": cfg.get("workdir_keys") or [], "issue_prefix": cfg.get("issue_prefix") or "",
                "issue_command": cfg.get("issue_command") or "",
                "threads": [{k: t[k] for k in ("key", "no", "title", "mode", "status", "ts", "last", "last_bot")} for t in BOX.threads()],
            })
        if u.path == "/api/thread":
            key = (parse_qs(u.query).get("key") or [""])[0]
            t = next((x for x in BOX.threads() if x["key"] == key), None)
            if not t:
                return self._send(404, {"error": "없는 대화"})
            return self._send(200, t)
        if u.path == "/api/setup":
            cfg, src = load_cfg()
            return self._send(200, {k: cfg.get(k) for k in ("user", "login_user", "imap_host", "imap_port", "smtp_host", "smtp_port",
                                                           "send_mode", "issue_prefix", "issue_command")}
                              | {"source": src, "has_password": bool(cfg.get("password_enc"))})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self._send(403, {"error": "forbidden"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            return self._send(400, {"error": "잘못된 요청"})
        u = urlparse(self.path)
        try:
            if u.path == "/api/send":
                return self._send(200, send(data))
            if u.path == "/api/refresh":
                BOX.wake.set()
                return self._send(200, {"ok": True})
            if u.path == "/api/setup":
                return self._send(200, save_setup(data))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            log("요청 실패 %s — %s" % (u.path, traceback.format_exc(limit=3)))
            return self._send(500, {"error": "%s" % e})
        return self._send(404, {"error": "not found"})


def save_setup(data):
    """다른 PC 에서 처음 열 때 넣는 메일 계정. 연결을 먼저 확인하고, 되면 비밀번호를 DPAPI 로 감춰 저장한다."""
    own = read_json(OWN_CFG) or {}
    for k in ("user", "login_user", "imap_host", "smtp_host", "send_mode", "issue_prefix", "issue_command"):
        if k in data:
            own[k] = str(data[k]).strip()
    for k in ("imap_port", "smtp_port"):
        if str(data.get(k) or "").isdigit():
            own[k] = int(data[k])
    if not own.get("user") or "@" not in own["user"]:
        raise ValueError("메일 주소를 넣어 주세요")
    if not own.get("imap_host"):
        raise ValueError("IMAP 서버 주소를 넣어 주세요 (예: imap.example.com)")
    trial = dict(DEFAULTS, **own)
    pw = data.get("password") or ""
    if pw:
        imap_connect(trial, pw).logout()             # 틀리면 여기서 예외 — 저장하지 않는다
        own["password_enc"] = dpapi_protect(pw)
    elif not own.get("password_enc"):
        raise ValueError("비밀번호를 넣어 주세요")
    write_json(OWN_CFG, own)
    BOX.seen.clear()
    BOX.wake.set()
    return {"ok": True}


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def port_in_use():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def open_window():
    url = "http://127.0.0.1:%d/" % PORT
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        exe = os.path.join(base or "", "Microsoft", "Edge", "Application", "msedge.exe")
        if base and os.path.isfile(exe):
            # 따로 둔 프로필이라 평소 Edge 창과 섞이지 않고, 창 크기도 따로 기억한다
            subprocess.Popen([exe, "--app=" + url, "--user-data-dir=" + os.path.join(LOCALDATA, "edge"), "--window-size=1100,760"])
            return
    webbrowser.open(url)


def main():
    serve_only = "--serve" in sys.argv
    if port_in_use():
        if not serve_only:
            open_window()                            # 이미 떠 있다 — 창만 연다
        return 0
    srv = Server(("127.0.0.1", PORT), Handler)
    threading.Thread(target=BOX.loop, daemon=True).start()
    log("디스패치 대화 시작 — http://127.0.0.1:%d/" % PORT)
    if not serve_only:
        threading.Timer(0.8, open_window).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
