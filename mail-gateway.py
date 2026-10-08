# -*- coding: utf-8 -*-
"""
메일 게이트웨이 — 휴대폰(또는 어느 PC)에서 보낸 지시 메일을 작업 인박스 큐에 넣고, 결과를 회신한다.

폰↔PC 직접 연결은 사내 방화벽·망분리로 막혀 있는 일이 많다. 그래서 양쪽 모두 닿는
회사 메일(IMAP/SMTP)을 통로로 쓴다. 내용이 회사 메일 밖으로 나가지 않는다는 것이 이 방식을 고른 이유다.

흐름:
    감시 폴더의 [제목이 태그로 시작하는] 메일 발견
      → 발신자가 허용 목록(dispatch.allowed_senders)인지 확인 — 목록이 비면 전부 무시
      → inbox/jobs/<id>.json 생성 (source=mail)   ← inbox-worker.ps1 이 집어 claude -p 로 실행한다
      → 메일을 읽음(\\Seen) 처리
    워커가 done/error 로 바꾼 메일발 작업 발견
      → 원본에 회신(In-Reply-To 로 스레드 유지, 답장에도 Message-ID 를 남긴다)
      → replied=true 로 표시

들어온 메일이 예전 답장에 대한 재답장(In-Reply-To/References 로 알 수 있다)이면
그 잡의 session_id 를 찾아 새 잡에 resume_id 로 실어 보낸다 — inbox-worker.ps1 이
이 값을 보면 새 세션 대신 claude -p --resume <id> 로 이어서 돌린다. 폰 메일 앱이
답장 제목에 붙이는 'Re:' 는 자동으로 벗겨 태그 매칭을 그대로 통과시킨다.

설정은 저장소 맨 위 config.local.json 한 곳이다(견본 config.example.json, 처음 설정은 python setup.py).
  mail      메일 계정·서버 — 비밀번호는 DPAPI 로 암호화된 값(password_enc)만 파일에 남는다
  dispatch  이 기능의 동작(enabled · tags · write_tags · folders · allowed_senders · default_workdir ·
            workdir_keys · reply_mode · issue_prefix …). enabled 가 false 면 아무것도 하지 않는다.
접속·복호화는 tools\\macro-hub\\kit.py 의 공통 코드를 쓴다.

실행(claude 호출)은 inbox-worker.ps1 이 담당한다. 여기서는 큐에 넣고 회신만 한다.

사용법:
    python setup.py                    계정·비밀번호 설정 (저장소 맨 위 설정 마법사)
    python mail-gateway.py --setup     위와 같다(설정 마법사로 넘긴다)
    python mail-gateway.py --setup-gmail  폰 지시를 Gmail 에서 직접 읽기(Gmail 주소·앱 비밀번호 입력 창)
    python mail-gateway.py --test      연결만 확인
    python mail-gateway.py --seed      지금 있는 지시 메일을 실행하지 않고 '처리됨'으로만 기록 (처음 켤 때)
    python mail-gateway.py --once      한 번만 돌고 종료 (진단용)
    python mail-gateway.py             상주
"""
import base64
import ctypes
import email
import email.header
import email.utils
import hmac
import imaplib
import json
import os
import random
import re
import subprocess
import sys
import time
from html import escape as html_escape
from urllib.parse import quote
from datetime import datetime, timedelta
from email.message import EmailMessage

# 한국어 Windows 콘솔은 CP949 라 '—' 같은 문자에서 UnicodeEncodeError 가 난다.
# pythonw 로 띄우면 stdout 이 아예 없으므로 존재 여부를 확인하고 바꾼다.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None:
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools", "macro-hub"))
import kit  # noqa: E402  — 설정·DPAPI·IMAP/SMTP 공통 코드

INBOX = os.path.join(HERE, "inbox")
JOBS = os.path.join(INBOX, "jobs")
ATTACH = os.path.join(INBOX, "attachments")           # 폰이 지시와 함께 보낸 사진(잡마다 폴더 하나, 7일 지나면 지운다)
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
MAX_IMAGES, MAX_IMAGE_BYTES = 5, 10 * 1024 * 1024
STATE_PATH = os.path.join(INBOX, "mail-state.json")
PAUSE_PATH = os.path.join(INBOX, "mail-paused.flag")
NOTIFY_PATH = os.path.join(INBOX, "mail-notify.jsonl")
LOG_PATH = os.path.join(INBOX, "mail-gateway.log")
# 처리한 메일의 Message-ID 기록.
# "안 읽음"을 기준으로 삼으면, 폰에서 알림을 보고 메일을 열어본 순간 읽음이 되어
# 그 지시가 영영 실행되지 않는다. 그래서 읽음 여부와 무관하게 이 기록으로 판단한다.
SEEN_PATH = os.path.join(INBOX, "mail-seen.json")

# 메일 스레드로 이어받을 수 있는 잡의 출처. 다른 자동화가 메일로 첫 잡을 내보내게 하려면 여기에 출처를 더한다
# (inbox-worker.ps1 의 같은 목록도 함께).
MAIL_SOURCES = ("mail",)

# config.local.json 의 dispatch 갈래가 이 위에 덮인다. 회사마다 다른 값(서버·주소·폴더)은 여기에 두지 않는다.
DEFAULT_CFG = {
    "enabled": False,
    # 지시로 인식할 제목 접두어. 여러 개를 허용한다 —
    # 폰 키보드에서 '#' 은 기호 전환이 필요해 빠뜨리기 쉽다.
    # 접두어 뒤에는 공백이 와야 하므로 'check ...' 같은 제목이 잘못 걸리지 않는다.
    "tags": ["#c", "c"],
    # 쓰기까지 허용하는 접두어. 평소에는 읽기 전용으로 두고 필요할 때만 이쪽을 쓴다.
    # 메일 한 통으로 소스가 바뀔 수 있으므로 태그를 나눠 두는 것이다.
    "write_tags": ["#cw", "cw"],
    # 쓰기 태그로 온 지시에 줄 도구. 읽기 태그는 이 값을 비워 두고
    # 워커가 dispatch.read_tools(읽기 전용 기본 목록)를 쓰게 한다.
    "write_tools": ["Read", "Glob", "Grep", "Edit", "Write", "NotebookEdit", "Bash"],
    # 쓰기 태그(cw)로 온 '새' 지시는 바로 실행하지 않고 확인 메일을 한 번 보낸다. '1'(또는 '확인')로 답장해야
    # 실행되고, confirm_ttl_min 분 안에 답이 없으면 취소된다. 폰 키보드에서 접두어를 잘못 붙여 수정·실행 권한이
    # 열리는 사고를 막으려는 것이다. 이어받기(이전 잡에 대한 답장)는 이미 확인된 대화라 묻지 않는다.
    "confirm_write": True,
    "confirm_ttl_min": 60,
    # 감시할 폴더. 사람이 읽는 이름으로 적으면 서버의 modified UTF-7 이름과 알아서 맞춘다.
    # 자기에게 보낸 메일을 메일 규칙이 딴 폴더로 옮기는 서버라면 그 폴더도 넣는다
    # (예: ["INBOX", "Inbox.내게쓴메일"] — 폴더 이름은 회사 메일 서버마다 다르다).
    "folders": ["INBOX"],
    # 비어 있으면 모든 메일을 무시한다(지시를 보낼 내 주소를 넣는다).
    "allowed_senders": [],
    # From 헤더는 위조할 수 있다. True 면 서버가 붙인 Authentication-Results 에
    # dkim=pass 또는 spf=pass 가 있는 메일만 받는다. 켜기 전에 로그의 '[인증]' 줄로
    # 이 서버가 그 헤더를 실제로 붙이는지 확인할 것(안 붙이면 전부 막힌다).
    "require_auth_results": False,
    # 스팸함도 볼 때 그 폴더 이름(예: ["Spam"] — 서버마다 다르다). 회사 메일이 폰(개인 메일)에서 온 지시를 스팸으로
    # 돌리는 경우에 쓴다. 여기서는 암호 단어(keyed_senders)가 맞는 메일만 받는다 — 회사 주소를 사칭한 메일이
    # 흔히 떨어지는 곳이라 allowed_senders 주소라도 믿지 않는다. 빈 목록이면 보지 않는다.
    "junk_folders": [],
    # allowed_senders 밖의 개인 주소(폰 기본 메일 iCloud·Gmail 등)라도 그 주소의 암호 단어 '[k:단어]' 가
    # 제목 끝이나 본문 한 줄로 붙어 있으면 받는다(폰 페이지가 설정의 암호 단어를 자동으로 붙인다).
    # 예: {"me@example.com": "단어"} — config.local.json(git 제외)에만 둔다. 이 주소에서 온 지시의 회신은 그 주소로도 보낸다.
    "keyed_senders": {},
    # 암호 단어 주소에서 온 지시의 회신·접수 신호를 다른 주소로 받고 싶을 때. 예: {"me@icloud.example": "me@gmail.example"}
    # (새 지시는 폰 메일 앱으로 보내고 답은 폰 페이지(Gmail)로 받는 식)
    "phone_reply_to": {},
    # 폰(Gmail) 지시를 회사 메일을 거치지 않고 Gmail 받은편지함에서 직접 읽는다 — 회사 스팸 장비가 외부 Gmail(API) 로
    # 보낸 새 지시를 몇 분씩 붙잡는 경우가 있어서다(본문·서명·첨부를 바꿔도 소용없었다). 폰 페이지가 지시를 '나에게'
    # 보내면 여기서 받는다. 이 주소 자신이 보낸 메일 + 암호 단어가 맞을 때만. 받은 지시는 PC 메신저가 보도록
    # 회사 INBOX 에 사본(X-Dispatch-Mirror)을 넣는다. 'python mail-gateway.py --setup-gmail' 로 채운다.
    # 예: {"user": "me@gmail.example", "password_enc": "<앱 비밀번호, kit.protect>"} — 비면 끈다.
    "gmail": {},
    "default_workdir": r"%USERPROFILE%\Documents",
    # 제목의 '@키' 로 고르는 작업 폴더. 예(JSON): {"docs": "D:\\work\\docs"} → '#c @docs 요약해줘'
    "workdir_keys": {},
    # 결과를 돌려주는 방법.
    #   smtp   = 실제로 발송한다 (기본)
    #   append = IMAP 으로 받은편지함(INBOX)에 직접 써 넣는다 — 자기 자신에게 보낸 메일을 메일 규칙이
    #            다른 폴더로 옮겨 INBOX 에서 사라진 것처럼 보이는 서버, SMTP 발송이 막힌 곳에서 쓴다.
    "reply_mode": "smtp",
    # 이슈 처리 명령 — issue_prefix(예: "PROJ-")를 넣어야 켜진다. '#cw /issue PROJ-123' 처럼 오면
    # issue_tools · issue_disallowed_tools 로 돈다(비면 쓰기 도구 그대로). issue_command 는 그 이슈를 처리할
    # Claude Code 스킬(슬래시 명령) 이름이다 — 그런 스킬이 작업 폴더에 있어야 의미가 있다.
    "issue_prefix": "",
    "issue_command": "/issue",
    "issue_tools": [],
    "issue_disallowed_tools": [],
    "poll_sec": 20,
    "max_prompt_chars": 4000,
    "lookback_days": 2,      # 이 기간 안의 메일만 훑는다(과거를 건드리지 않기 위해)
    "max_per_cycle": 3,      # 한 번에 접수할 최대 건수(실수로 무더기 실행되는 것 방지)
}


# ----------------------------------------------------------------- 공통

def log(msg: str) -> None:
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        if os.path.isfile(LOG_PATH) and os.path.getsize(LOG_PATH) > 1024 * 1024:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                keep = f.readlines()[-2000:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(keep)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def write_json(path: str, obj) -> None:
    """워커(PowerShell)·대화 앱이 함께 읽으므로 BOM 없는 UTF-8 로 쓴다."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _public(d) -> dict:
    """'_' 로 시작하는 키는 설명이라 뺀다."""
    return {k: v for k, v in (d or {}).items() if not str(k).startswith("_")}


def load_cfg() -> dict:
    """게이트웨이 설정 = 중립 기본값 ← config.local.json 의 dispatch ← mail(계정·서버).

    한 dict 로 합쳐 두면 kit.imap_connect/smtp_connect 에 그대로 넘길 수 있다(imap_host·user·ca_bundle 등).
    작업 폴더는 %USERPROFILE% · ~ 를 풀어 둔다.
    """
    full = kit.load_config()
    cfg = dict(DEFAULT_CFG)
    cfg.update(_public(full.get("dispatch")))
    cfg.update(kit.mail_config(full))          # 계정 값은 mail 갈래가 정본이다
    cfg["default_workdir"] = kit.expand(cfg.get("default_workdir") or DEFAULT_CFG["default_workdir"])
    keys = cfg.get("workdir_keys")
    cfg["workdir_keys"] = {str(k): kit.expand(v) for k, v in keys.items() if v} if isinstance(keys, dict) else {}
    cfg["folders"] = list(cfg.get("folders") or ["INBOX"])
    cfg["allowed_senders"] = [str(a).strip() for a in (cfg.get("allowed_senders") or []) if str(a).strip()]
    cfg["tag"] = cfg.get("tag") or (cfg.get("tags") or ["#c"])[0]   # 회신·안내 문구에 쓰는 대표 태그
    return cfg


def set_state(state: str, detail: str) -> None:
    write_json(STATE_PATH, {
        "state": state,
        "detail": detail,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def notify(title: str, text: str, level: str = "Info") -> None:
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": level, "title": title, "text": text,
    }
    try:
        with open(NOTIFY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def single_instance(name: str = "WorkKitMailGateway"):
    """허브가 죽은 프로세스를 다시 띄우므로 중복 방지가 필요하다."""
    h = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\" + name)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return h


# ----------------------------------------------------------------- 메일 파싱

def decode_hdr(raw) -> str:
    if not raw:
        return ""
    out = []
    for part, enc in email.header.decode_header(raw):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", "replace"))
            except LookupError:
                out.append(part.decode("utf-8", "replace"))
        else:
            out.append(part)
    return "".join(out).strip()


def save_images(msg, key: str) -> tuple:
    """메일에 붙은 사진을 inbox/attachments/<key>/ 에 저장하고 (폴더, [경로]) — 없으면 ("", []).
    사진(jpeg·png·gif·webp)만, 최대 5장·장당 10MB. 파일 이름은 우리가 짓는다(보낸 쪽 이름을 경로로 쓰지 않는다)."""
    if not msg.is_multipart():
        return "", []
    paths, folder = [], os.path.join(ATTACH, key)
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


_LAST_PRUNE = [0.0]


def prune_attachments(days: int = 7) -> None:
    """오래된 사진 폴더를 지운다(한 시간에 한 번만 본다)."""
    if time.time() - _LAST_PRUNE[0] < 3600 or not os.path.isdir(ATTACH):
        return
    _LAST_PRUNE[0] = time.time()
    cut = time.time() - days * 86400
    for name in os.listdir(ATTACH):
        d = os.path.join(ATTACH, name)
        try:
            if os.path.isdir(d) and os.path.getmtime(d) < cut:
                for fn in os.listdir(d):
                    os.remove(os.path.join(d, fn))
                os.rmdir(d)
        except OSError:
            pass


# 폰(Gmail) 페이지는 암호 단어를 제목 대신 본문 마지막 줄 '[k:단어]' 로 보낸다 — 제목의 알 수 없는 영숫자 조각이
# 회사 스팸 장비의 의심을 살 수 있어서다. 지시문에는 넣지 않는다.
BODY_KEY_RE = re.compile(r"^[ \t]*\[k:([^\]\s]{1,64})\][ \t\r]*$", re.M)


def body_key(msg):
    """본문 줄 '[k:단어]' 의 단어(없으면 None)."""
    mt = BODY_KEY_RE.search(_plain_body_raw(msg))
    return mt.group(1) if mt else None


def plain_body(msg) -> str:
    """text/plain 우선(없으면 HTML 에서 태그를 걷어낸다). 본문의 암호 단어 줄은 뗀다."""
    return BODY_KEY_RE.sub("", _plain_body_raw(msg))


def _plain_body_raw(msg) -> str:
    """text/plain 우선. 없으면 HTML 에서 태그를 걷어낸다."""
    def payload(part):
        try:
            data = part.get_payload(decode=True) or b""
            cs = part.get_content_charset() or "utf-8"
            return data.decode(cs, "replace")
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
    if msg.get_content_type() == "text/html":
        return re.sub(r"<[^>]+>", " ", payload(msg))
    return payload(msg)


# 폰 메일 서명·인용은 지시가 아니므로 잘라낸다
SIG_RE = re.compile(
    r"(?m)^\s*(--\s*$|보낸 사람:|보낸사람:|From:|-----Original Message-----|"
    r"iPhone에서 보냄|내 iPhone에서 보냄|나의 iPhone에서 보냄|Sent from my |Get Outlook for |"
    # 아이폰 메일 답장의 인용 머리줄 '2026. 10. 6. 오후 4:12, 이름 <a@b> 작성:' · 'On … wrote:'
    r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\..*작성:\s*$|On .+ wrote:\s*$)"
)

# 폰 메일 앱이 답장할 때 제목 앞에 붙이는 접두어. 이걸 안 벗기면 "Re: #c ..." 가
# 태그로 시작하지 않아 match_tag 에서 걸러져 답장이 지시로 인식되지 않는다.
REPLY_PREFIX_RE = re.compile(r"(?i)^\s*(re|fw|fwd|회신|답장)\s*[:：]\s*")


SUBJECT_KEY_RE = re.compile(r"\s*\[k:([^\]\s]{1,64})\]\s*$")


def split_subject_key(subject: str):
    """제목 끝의 암호 단어 '[k:단어]' 를 떼어 (나머지 제목, 단어 또는 None)."""
    m = SUBJECT_KEY_RE.search(subject or "")
    if not m:
        return subject, None
    return subject[:m.start()].rstrip(), m.group(1)


def keyed_word(cfg: dict, sender):
    """keyed_senders 에 있는 주소면 그 암호 단어, 아니면 None."""
    keyed = {a.lower(): str(k) for a, k in (cfg.get("keyed_senders") or {}).items() if k}
    return keyed.get((sender or "").lower())


def key_sender_ok(cfg: dict, sender: str, key) -> bool:
    """keyed_senders 에 있는 주소이고 암호 단어가 맞으면 True (시간차 비교를 막으려고 compare_digest)."""
    want = keyed_word(cfg, sender)
    return bool(want and key and hmac.compare_digest(key.encode("utf-8"), want.encode("utf-8")))


def strip_reply_prefix(subject: str) -> str:
    """중첩된 'Re: Re: ...' 도 다 벗긴다."""
    s = subject
    for _ in range(5):
        new = REPLY_PREFIX_RE.sub("", s)
        if new == s:
            break
        s = new
    return s.strip()


def match_tag(subject: str, cfg: dict):
    """
    제목이 지시 접두어로 시작하면 (접두어, 모드)를 돌려준다. 아니면 (None, None).
    모드는 'read'(읽기 전용) 또는 'write'(수정·실행 허용).

    접두어 뒤에는 공백이 있어야 한다 — 'c 확인해줘'는 지시, 'check list'는 아니다.
    긴 접두어를 먼저 본다 — 'cw ...'가 'c'로 잘못 잡히면 안 된다.
    """
    cands = []
    for t in (cfg.get("write_tags") or []):
        cands.append((t, "write"))
    for t in (cfg.get("tags") or [cfg.get("tag", "#c")]):
        cands.append((t, "read"))

    for t, mode in sorted(cands, key=lambda x: len(x[0]), reverse=True):
        if subject == t:
            return t, mode
        if subject.startswith(t) and subject[len(t):len(t) + 1].isspace():
            return t, mode
    return None, None


def build_instruction(subject: str, body: str, cfg: dict):
    """
    "#c 회의록 요약해줘"          -> 기본 폴더(dispatch.default_workdir)
    "#c @docs 지난주 보고서 확인"  -> workdir_keys 의 docs 폴더
    본문이 있으면 뒤에 이어 붙인다.
    """
    tag, mode = match_tag(subject, cfg)
    if not tag:
        # 태그 없는 제목이 여기까지 오면 호출부의 필터가 깨진 것이다.
        # 임의로 앞글자를 떼면 엉뚱한 지시가 만들어지므로(실제로 그렇게 회신 메일이 재실행됐다)
        # 빈 지시를 돌려주어 호출부가 건너뛰게 한다.
        return "", cfg["default_workdir"], "default", "read"
    text = THREAD_RE.sub("", subject[len(tag):]).strip()

    workdir = cfg["default_workdir"]
    label = "default"
    m = re.match(r"^@(\w+)\s*", text)
    if m:
        key = m.group(1)
        mapped = cfg.get("workdir_keys", {}).get(key)
        if mapped:
            workdir, label = mapped, key
            text = text[m.end():].strip()
        else:
            # 등록된 키가 아니면 지시의 일부다(예: "@media 쿼리 찾아줘"). 지우지 않는다.
            log("등록되지 않은 폴더 키 '@%s' — 지시문으로 그대로 둡니다" % key)

    if body:
        cut = SIG_RE.search(body)
        if cut:
            body = body[: cut.start()]
        body = body.strip()

    prompt = (text + "\n\n" + body).strip() if body else text
    return prompt[: int(cfg["max_prompt_chars"])].strip(), workdir, label, mode


def new_job(prompt, workdir, label, msg_id, subject, sender, mode="read", cfg=None, resume_id=None,
            confirm=False, disallowed_tools=None, thread=None, allowed_tools=None, stopped=False,
            attach_dir="") -> dict:
    os.makedirs(JOBS, exist_ok=True)
    # id 규칙(yyyymmdd-HHMMSS-4hex) — 파일 이름 순서가 곧 접수 순서다(워커가 이름순으로 집는다)
    jid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-%04x" % random.randrange(0x10000)
    job = {
        "id": jid,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prompt": prompt,
        "workdir": workdir,
        "workdir_label": label,
        "status": "queued",
        "started_at": None, "finished_at": None,
        "result": None, "error": None,
        "denials": [], "cost_usd": None, "duration_ms": None,
        "source_ip": "mail", "source": "mail",
        "mail_msgid": msg_id, "mail_subject": subject, "mail_from": sender,
        "replied": False,
        "mode": mode,
        # 메일 대화 모드 — 워커가 chat-protocol.md 를 덧붙여, 사람에게 물을 자리에서 ```choices 블록을 쓰게 한다
        "chat": True,
    }
    if thread:
        job["thread"] = thread
    if attach_dir:
        # 워커가 claude 에 --add-dir 로 넘겨 이 폴더의 사진을 Read 로 열 수 있게 한다(작업 폴더 밖이라)
        job["attach_dir"] = attach_dir
    # 쓰기 태그로 온 지시에만 도구를 넓혀 준다. 읽기 지시는 이 값을 넣지 않아
    # 워커가 config.local.json 의 읽기 전용 기본값을 그대로 쓴다.
    if mode == "write" and cfg:
        tools = cfg.get("write_tools")
        if tools:
            job["allowed_tools"] = list(tools)
        # 이슈 처리 명령('#cw /issue PROJ-123' — 폰 디스패치 페이지·대화 앱의 '이슈' 칸)은 issue_tools ·
        # issue_disallowed_tools 로 돈다(이슈 조회 도구가 필요하고, 무인 실행이라 밖으로 내보내는 명령은 막아 둘 수 있다).
        # issue_prefix 가 비어 있으면 이 기능은 꺼져 있고 평범한 쓰기 지시로 돈다.
        if is_issue_prompt(prompt, cfg):
            if cfg.get("issue_tools"):
                job["allowed_tools"] = list(cfg["issue_tools"])
            if cfg.get("issue_disallowed_tools") and not disallowed_tools:
                disallowed_tools = list(cfg["issue_disallowed_tools"])
    if allowed_tools:
        # 이어받는 잡은 원래 잡의 도구 목록을 그대로 물려받는다(대화의 권한은 처음 확인한 그대로)
        job["allowed_tools"] = list(allowed_tools)
    if resume_id:
        # inbox-worker.ps1 이 이 값을 보면 새 세션 대신 claude -p --resume <id> 로 돌린다.
        job["resume_id"] = resume_id
    if disallowed_tools:
        # 이어받는 잡은 원래 잡의 거부 목록을 그대로 물려받는다(안 그러면 이어받는 순간 제한이 사라진다)
        job["disallowed_tools"] = list(disallowed_tools)
    if stopped:
        # 먼저 온 '멈춤' 이 가리킨 지시 — 처음부터 끝난 잡으로 써서 워커가 집지 않고, 게이트웨이가 '멈췄습니다' 를 회신한다
        job["status"] = "done"
        job["result"] = STOPPED_BEFORE_START
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elif confirm:
        # 워커는 queued 만 집으므로 확인 답장이 와서 queued 로 바뀔 때까지 실행되지 않는다.
        job["status"] = "awaiting_confirm"
        job["confirm_sent"] = False
    write_json(os.path.join(JOBS, jid + ".json"), job)
    return job


CONFIRM_YES = {"1", "확인", "실행", "ok", "yes", "y", "네", "예", "go"}
CONFIRM_NO = {"2", "취소", "no", "n", "아니오", "아니요", "x", "stop", "멈춤", "그만"}


def parse_confirm_answer(text: str):
    """확인 메일에 대한 답장 본문에서 첫 '내용 있는 줄'만 보고 'yes' / 'no' / None 을 돌려준다.

    인용(>)·빈 줄은 건너뛴다. 애매하면 None — 실행하지도 취소하지도 않고 다시 답하기를 기다린다.
    """
    for line in (text or "").splitlines():
        t = line.strip()
        if not t or t.startswith(">"):
            continue
        t = re.sub(r"[\s.!。]+$", "", t).lower()
        if t in CONFIRM_YES:
            return "yes"
        if t in CONFIRM_NO:
            return "no"
        return None
    return None


def find_pending_confirm(head, thread=None):
    """들어온 메일이 우리가 보낸 확인 메일에 대한 답장이면 (경로, 잡)을 돌려준다.
    thread 가 오면 제목 표식 [T12] 가 같은 확인 대기 잡도 답장으로 본다."""
    if thread is not None:
        for path, j in iter_jobs():
            if j.get("status") == "awaiting_confirm" and j.get("thread") == thread:
                return path, j
    refs = []
    for h in ("In-Reply-To", "References"):
        v = head.get(h)
        if v:
            refs += re.findall(r"<[^<>]+>", str(v))
    refset = set(refs)
    if not refset:
        return None
    try:
        names = sorted(os.listdir(JOBS), reverse=True)
    except Exception:
        return None
    for fn in names:
        if not fn.endswith(".json"):
            continue
        path = os.path.join(JOBS, fn)
        j = read_json(path)
        if j and j.get("status") == "awaiting_confirm" and j.get("confirm_msgid") in refset:
            return path, j
    return None


def expire_confirms(cfg: dict) -> None:
    """확인 답장이 제한 시간 안에 오지 않은 잡을 취소한다."""
    ttl = int(cfg.get("confirm_ttl_min", 60))
    try:
        names = os.listdir(JOBS)
    except Exception:
        return
    now = datetime.now()
    for fn in names:
        if not fn.endswith(".json"):
            continue
        path = os.path.join(JOBS, fn)
        j = read_json(path)
        if not j or j.get("status") != "awaiting_confirm":
            continue
        try:
            born = datetime.strptime(j.get("created_at", ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if now - born > timedelta(minutes=ttl):
            j["status"] = "canceled"
            j["error"] = "확인 답장이 %d분 안에 오지 않아 취소했습니다." % ttl
            j["finished_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            write_json(path, j)
            log("확인 시간 초과로 취소 %s" % j.get("id"))


def load_own_reply_ids() -> set:
    """우리가 append 로 넣은 회신들의 Message-ID 모음.

    reply_mode=append 는 INBOX 에 직접 써 넣으므로, 그 회신도 다음 폴링에서
    '새 메일'로 보인다. 답장 제목은 'Re: <태그> ...'인데 strip_reply_prefix 가
    Re: 를 벗겨 태그 매칭을 통과시키고 발신자(cfg["user"])도 대개 allowed_senders에
    있어, 자기 회신에 자기가 또 답장하는 무한 핑퐁이 된다(실제로 겪었다 — 2026-09-08).
    """
    ids = set()
    try:
        names = os.listdir(JOBS)
    except Exception:
        return ids
    for fn in names:
        if not fn.endswith(".json"):
            continue
        j = read_json(os.path.join(JOBS, fn))
        if j:
            # 확인 메일도 INBOX 에 직접 넣으므로 자기 메일을 새 지시로 오인하지 않게 함께 모은다
            for k in ("reply_msgid", "confirm_msgid"):
                if j.get(k):
                    ids.add(j[k])
    return ids


def find_resume_target(head):
    """
    들어온 메일의 In-Reply-To/References 가 예전에 우리가 보낸 답장(또는 원본 지시)을
    가리키면, 그 잡의 session_id 를 돌려준다 — 이어서 실행하기 위해서다.

    세션은 작업 폴더에 묶여 있으므로 workdir/label 도 함께 돌려주어 그대로 맞춘다.
    """
    j = find_resume_job(head)
    if not j:
        return None
    return j["session_id"], j.get("workdir"), j.get("workdir_label"), j.get("disallowed_tools") or []


def find_live_job(head, thread_no=None):
    """아직 끝나지 않은(대기·실행 중) 메일 잡 중 이 메일이 가리키는 것 — 대화 번호가 같거나, 답장 대상이 그 지시."""
    refs = set()
    for h in ("In-Reply-To", "References"):
        refs.update(re.findall(r"<[^<>]+>", str(head.get(h) or "")))
    for _path, j in iter_jobs():
        if not isinstance(j, dict) or j.get("source") not in MAIL_SOURCES or j.get("status") not in ("queued", "running"):
            continue
        if (thread_no is not None and j.get("thread") == thread_no) or (j.get("mail_msgid") and j["mail_msgid"] in refs):
            return j
    return None


def find_resume_job(head):
    """find_resume_target 과 같은 규칙으로 찾은 잡 자체(선택지 ask·스레드 번호가 필요해서)."""
    refs = []
    for h in ("In-Reply-To", "References"):
        v = head.get(h)
        if v:
            refs += re.findall(r"<[^<>]+>", str(v))
    if not refs:
        return None
    refset = set(refs)

    try:
        names = sorted(os.listdir(JOBS), reverse=True)
    except Exception:
        return None
    for fn in names:
        if not fn.endswith(".json"):
            continue
        j = read_json(os.path.join(JOBS, fn))
        # MAIL_SOURCES 의 잡(폰·대화 앱에서 보낸 지시)만 메일 스레드로 이어받는다.
        if not j or j.get("source") not in MAIL_SOURCES or not j.get("session_id"):
            continue
        candidates = {x for x in (j.get("reply_msgid"), j.get("mail_msgid")) if x}
        if candidates & refset:
            return j
    return None


# ----------------------------------------------------------------- 대화(스레드 · 선택지)
# 메일을 메신저처럼 쓴다. 일마다 스레드 번호를 제목에 [T12] 로 박아 두고, 그 표식이 붙은 메일은
# — 답장이든, 폰 보내기 페이지·'한 번에 답장' 링크(mailto)로 새로 쓴 메일이든 — 같은 Claude 세션으로 잇는다.
# mailto 로 쓴 메일엔 In-Reply-To 가 없으므로 제목 표식을 먼저 본다.
# Claude 가 결과 끝에 ```choices 블록을 남기면(chat-protocol.md) ☐ 선택지로 보여 주고,
# "1,3" 같은 번호 답은 선택지 내용으로 풀어 넘긴다.
THREAD_SEQ_PATH = os.path.join(INBOX, "thread-seq.json")
THREAD_RE = re.compile(r"\[T(\d{1,6})\]")
CHOICES_RE = re.compile(r"```choices[ \t]*\n(.*?)\n?```\s*$", re.S)
STOP_WORDS = {"멈춤", "그만", "stop"}
ISSUE_KEY_RE = r"[A-Z][A-Z0-9_]*-\d+"
ACKED_PATH = os.path.join(INBOX, "acked.json")            # 접수 신호를 보낸 잡 id(send_acks)
EARLY_STOP_PATH = os.path.join(INBOX, "early-stops.json")  # 지시보다 먼저 도착한 '멈춤' 이 가리키는 Message-ID → 받은 시각
STOPPED_BEFORE_START = "멈췄습니다 — 시작하기 전에 멈춤 요청을 받아 실행하지 않았습니다."


def early_stops() -> dict:
    """지시보다 먼저 온 멈춤 기록(하루 지난 것은 버린다)."""
    got = read_json(EARLY_STOP_PATH) or {}
    now = time.time()
    return {k: v for k, v in got.items() if isinstance(v, (int, float)) and now - v < 86400} if isinstance(got, dict) else {}



def is_issue_prompt(prompt, cfg) -> bool:
    """'/issue PROJ-123' 처럼 이슈 처리 명령 하나뿐인 지시인가. issue_prefix 가 비어 있으면 늘 False(기능 꺼짐)."""
    cfg = cfg or {}
    cmd = str(cfg.get("issue_command") or "").strip()
    if not str(cfg.get("issue_prefix") or "").strip() or not cmd:
        return False
    return re.match(r"^%s\s+%s\s*$" % (re.escape(cmd), ISSUE_KEY_RE), prompt or "") is not None


def iter_jobs():
    """잡 파일을 최신순으로 (경로, 잡)."""
    try:
        names = sorted(os.listdir(JOBS), reverse=True)
    except Exception:
        return
    for fn in names:
        if fn.endswith(".json"):
            path = os.path.join(JOBS, fn)
            j = read_json(path)
            if j:
                yield path, j


def thread_of(subject):
    m = THREAD_RE.search(subject or "")
    return int(m.group(1)) if m else None


def next_thread_no() -> int:
    seq = read_json(THREAD_SEQ_PATH) or {}
    n = int(seq.get("last", 0)) + 1
    write_json(THREAD_SEQ_PATH, {"last": n})
    return n


def subject_with_thread(subject: str, n: int, cfg: dict) -> str:
    """'#c 34097 원인' → '#c [T12] 34097 원인'. 태그 바로 뒤에 넣어야 답장 제목도 태그로 시작한다."""
    subject = subject or ""
    if thread_of(subject) is not None:
        return subject
    tag, _ = match_tag(subject, cfg)
    if tag:
        rest = subject[len(tag):].strip()
        return ("%s [T%d] %s" % (tag, n, rest)).rstrip()
    return ("[T%d] %s" % (n, subject)).rstrip()


def ensure_thread(job: dict, cfg: dict) -> int:
    """회신하기 전에 스레드 번호를 정해 제목에 박는다(다른 자동화가 만든 첫 잡도 여기서 번호를 받는다)."""
    n = job.get("thread") or thread_of(job.get("mail_subject")) or next_thread_no()
    job["thread"] = n
    job["mail_subject"] = subject_with_thread(job.get("mail_subject") or cfg.get("tag", "#c"), n, cfg)
    return n


def find_thread_job(n):
    """스레드 n 의 가장 최근 잡 중 이어받을 세션이 있는 것."""
    for _path, j in iter_jobs():
        if j.get("thread") == n and j.get("source") in MAIL_SOURCES and j.get("session_id"):
            return j
    return None


def parse_choices(text):
    """결과 끝의 ```choices 블록을 떼어 (본문, ask). 블록이 없거나 깨졌으면 (원문, None)."""
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


def reply_text(body: str) -> str:
    """답장 본문에서 사람이 새로 쓴 부분만 — 서명·인용 머리줄 아래와 '>' 인용 줄을 버린다."""
    body = body or ""
    cut = SIG_RE.search(body)
    if cut:
        body = body[: cut.start()]
    return "\n".join(l for l in body.splitlines() if not l.lstrip().startswith(">")).strip()


def parse_answer(text: str, ask):
    """번호 답('1,3' · '2번' · '1 3' · '4 이건 이렇게')을 선택지 내용으로 푼다. 번호 답이 아니면 None."""
    if not ask or not text:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    first, more = lines[0], lines[1:]
    if re.fullmatch(r"[1-9](\s+[1-9])+", first):          # '1 3'
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


def mark_bot(msg, job: dict, ask=None, kind="reply") -> None:
    """PC 대화 앱(tools\dispatch-chat)이 메일함을 대화로 묶을 때 읽는 보이지 않는 표식.
    봇이 보낸 것 · 대화 번호 · 상태 · 선택지(JSON, base64)."""
    msg["X-Dispatch"] = "bot"
    msg["X-Dispatch-Kind"] = kind
    if job.get("thread"):
        msg["X-Dispatch-Thread"] = str(job["thread"])
    msg["X-Dispatch-Status"] = str(job.get("status") or "")
    if ask:
        msg["X-Dispatch-Ask"] = base64.b64encode(json.dumps(ask, ensure_ascii=False).encode("utf-8")).decode("ascii")


def reply_subject(job: dict) -> str:
    subj = job.get("mail_subject") or "지시"
    return subj if subj.lower().startswith("re:") else "Re: " + subj


def mailto(cfg: dict, job: dict, body: str) -> str:
    """'한 번에 답장' 링크 — 누르면 제목(태그·스레드 표식)과 본문이 채워진 메일 작성 화면이 열린다.
    폰(개인 주소, keyed_senders)이 보낸 지시면 제목 끝에 그 암호 단어를 붙여 폰 메일 앱에서 단추만 눌러도 받아지게 한다."""
    subject = reply_subject(job)
    word = keyed_word(cfg, job.get("mail_from"))
    if word:
        subject += " [k:%s]" % word
    return "mailto:%s?subject=%s&body=%s" % (cfg.get("user") or "", quote(subject), quote(body))


def phone_to(cfg: dict, sender) -> str:
    """폰(개인 주소) 지시의 회신·접수 신호를 받을 주소. 암호 단어 주소가 아니면 "".
    phone_reply_to 로 바꿀 수 있다 — 새 지시는 폰 메일 앱으로 보내고 답은 폰 대화방(Gmail)으로 받는 식.
    예: {"me@icloud.example": "me@gmail.example"}"""
    sender = (sender or "").strip()
    if not keyed_word(cfg, sender):
        return ""
    alias = {a.lower(): b for a, b in (cfg.get("phone_reply_to") or {}).items() if b}
    return alias.get(sender.lower(), sender)


def smtp_rcpts(cfg: dict, job: dict):
    """reply_mode=smtp 의 받는 사람. 폰(암호 단어 주소) 지시면 폰 주소(phone_reply_to 반영) + 내 주소(PC 메신저가 읽는
    회사 메일함) — 아니면 None(메일의 To 그대로)."""
    to = phone_to(cfg, job.get("mail_from"))
    return [to, cfg["user"]] if to and to.lower() != (cfg.get("user") or "").lower() else None


def copy_to_phone(cfg: dict, password: str, job: dict, msg, smtp_box: list) -> None:
    """폰(개인 주소)에서 온 지시는 회신을 그 주소로도 보낸다 — 회사 메일함(append)만으로는 폰 메일 앱에 안 보인다.
    smtp_box 는 [연결] 한 칸짜리 목록(한 번 연결해서 여러 통 보내고 send_replies 끝에서 닫는다)."""
    to = phone_to(cfg, job.get("mail_from"))
    if not to:
        return
    try:
        if not smtp_box:
            smtp_box.append(smtp_connect(cfg, password))
        smtp_box[0].send_message(msg, to_addrs=[to])
        log("폰으로도 회신 %s → %s" % (job.get("id"), to))
    except Exception as e:
        log("폰 회신 실패 %s — %s" % (job.get("id"), e))


def ask_lines(ask) -> list:
    if not ask:
        return []
    head = "❓ %s%s" % (ask["question"], " (여러 개 가능)" if ask.get("multi") else "")
    lines = [head] + ["  ☐ %d. %s" % (i, o) for i, o in enumerate(ask["options"], 1)]
    ex = '"1,3"' if ask.get("multi") else '"1"'
    lines.append("  → 번호로 답장하세요 (예: %s). 하고 싶은 말을 그대로 써도 되고, \"멈춤\" 이면 멈춥니다." % ex)
    return lines


_PILL = ("display:inline-block;margin:3px 4px 3px 0;padding:7px 13px;border-radius:999px;text-decoration:none;"
         "font-weight:700;font-size:14px;background:#eee9ff;color:#5b45c9;border:1px solid #d9cffb")


def reply_html(cfg: dict, job: dict, ask, text: str, footer: str) -> str:
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


# ----------------------------------------------------------------- IMAP / SMTP

def imap_utf7_decode(s: str) -> str:
    """IMAP 의 modified UTF-7 폴더명을 사람이 읽는 문자열로 (& 가 shift, , 가 / 자리)."""
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
                pad = "=" * ((4 - len(chunk) % 4) % 4)
                try:
                    out.append(base64.b64decode(chunk + pad).decode("utf-16-be"))
                except Exception:
                    out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


_FOLDER_RE = re.compile(r'"([^"]*)"\s*$')


def resolve_folders(m, wanted):
    """설정에 적힌 폴더 이름을 서버의 실제 폴더명으로 맞춘다(대소문자·인코딩 무시)."""
    typ, boxes = m.list()
    actual = []
    for b in (boxes or []):
        line = b.decode("utf-8", "replace")
        mt = _FOLDER_RE.search(line)
        if mt and mt.group(1) not in (".", ""):
            actual.append(mt.group(1))

    resolved, missing = [], []
    for w in wanted:
        hit = None
        for a in actual:
            if a == w or a.lower() == w.lower() or imap_utf7_decode(a).lower() == w.lower():
                hit = a
                break
        if hit:
            if hit not in resolved:
                resolved.append(hit)
        else:
            missing.append(w)
    if missing:
        log("서버에 없는 폴더는 건너뜁니다: %s" % ", ".join(missing))
    return resolved or ["INBOX"]


def imap_connect(cfg: dict, password: str):
    """kit 의 공통 접속(ssl/starttls/plain · 사내 CA 번들 · login_user)을 그대로 쓴다."""
    return kit.imap_connect(cfg, password)


def smtp_connect(cfg: dict, password: str):
    return kit.smtp_connect(cfg, password)


SEEN_KEEP = 800
ERROR_NOTIFY_AFTER = 5   # 폴링이 연속 이만큼 실패하면(약 100초) 한 번 알린다


class SeenSet:
    """처리한 메일 키 집합 — 넣은 순서를 기억한다.

    예전에는 set 을 sorted()[-800:] 로 잘라 저장했는데, Message-ID 는 문자열 순서가 시간 순서가
    아니라서 800건을 넘기면 오래된 것이 아니라 '사전순으로 뒤쪽'이 남았다. 최근 처리분이 지워지면
    lookback 기간(기본 2일) 안의 지시 메일이 다시 실행될 수 있다.
    """

    def __init__(self, keys=()):
        self._d = dict.fromkeys(keys)

    def add(self, key) -> None:
        self._d.pop(key, None)   # 다시 만난 키는 '최근'으로 옮긴다
        self._d[key] = None

    def __contains__(self, key) -> bool:
        return key in self._d

    def __len__(self) -> int:
        return len(self._d)

    def recent(self, n: int) -> list:
        return list(self._d)[-n:]


def load_processed() -> SeenSet:
    got = read_json(SEEN_PATH)
    return SeenSet(got if isinstance(got, list) else ())


def save_processed(ids: SeenSet) -> None:
    # 무한정 쌓이지 않게 최근 것만 남긴다(파일은 예전과 같은 문자열 리스트 형식)
    write_json(SEEN_PATH, ids.recent(SEEN_KEEP))


_WARNED_NO_ALLOWED = False


def auth_results_summary(head) -> tuple:
    """Authentication-Results 헤더에서 (통과 여부, 요약)을 뽑는다.

    dkim=pass 또는 spf=pass 가 하나라도 있으면 통과. 헤더가 여러 개일 수 있어 모두 본다.
    """
    values = [decode_hdr(v) for v in (head.get_all("Authentication-Results") or [])]
    if not values:
        return False, "(헤더 없음)"
    joined = " | ".join(" ".join(v.split()) for v in values)
    ok = bool(re.search(r"\b(dkim|spf)\s*=\s*pass\b", joined, re.IGNORECASE))
    return ok, joined[:200]


GMAIL_IMAP = {"imap_host": "imap.gmail.com", "imap_port": 993, "imap_mode": "ssl"}


def gmail_account(cfg: dict):
    """cfg["gmail"] 이 켜져 있으면 poll_once 에 넘길 계정 정보, 아니면 None."""
    g = cfg.get("gmail") or {}
    user = (g.get("user") or "").strip().lower()
    if not user or not g.get("password_enc"):
        return None
    conn = dict(GMAIL_IMAP, user=user, login_user="")
    conn.update({k: g[k] for k in GMAIL_IMAP if g.get(k)})
    return {"user": user, "conn": conn, "password": kit.unprotect(g["password_enc"]),
            "folders": g.get("folders") or ["INBOX"]}


def mirror_to_company(cfg: dict, password: str, raws: list) -> None:
    """Gmail 에서 받은 지시의 사본을 회사 INBOX 에 넣는다 — PC 메신저는 회사 메일함으로 대화를 그린다.
    회사 쪽 폴링은 X-Dispatch-Mirror 를 보고 건너뛴다(같은 Message-ID 라 처리 기록으로도 걸러진다)."""
    try:
        m = imap_connect(cfg, password)
        try:
            for raw in raws:
                m.append("INBOX", "(\\Seen)", imaplib.Time2Internaldate(time.time()), b"X-Dispatch-Mirror: gmail\r\n" + raw)
        finally:
            m.logout()
    except Exception as e:
        log("회사 메일함에 지시 사본 넣기 실패 — %s" % e)


def poll_once(cfg: dict, password: str, seed_only: bool = False, acct=None) -> int:
    """
    seed_only=True 면 실행하지 않고 지금 매칭되는 메일을 '처리됨'으로만 기록한다.
    (처음 붙일 때 과거 메일이 무더기로 실행되는 것을 막는 용도)
    acct 가 있으면(gmail_account) 회사 메일 대신 그 Gmail 받은편지함을 본다 — 그 주소 자신이 보낸 메일만,
    암호 단어가 맞을 때만 받고, 받은 메일은 회사 INBOX 에 사본을 넣는다.
    """
    allowed = [a.strip().lower() for a in (cfg.get("allowed_senders") or []) if a.strip()]
    if not allowed:
        # 목록이 비었다고 검사를 건너뛰면 아무나 지시를 넣을 수 있다 — 비면 전부 거부한다.
        # (setup.py 가 내 주소를 채워 준다. 설정 파일을 손으로 만들었을 때를 막는 안전장치.)
        global _WARNED_NO_ALLOWED
        if not _WARNED_NO_ALLOWED:
            log("dispatch.allowed_senders 가 비어 있어 모든 메일을 무시합니다. "
                "config.local.json 에 지시를 보낼 주소를 넣거나 python setup.py 를 다시 실행하세요.")
            _WARNED_NO_ALLOWED = True
        return 0
    expire_confirms(cfg)
    prune_attachments()
    processed = load_processed()
    since_days = int(cfg.get("lookback_days", 2))
    since = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    max_per_cycle = int(cfg.get("max_per_cycle", 3))
    own_reply_ids = load_own_reply_ids()
    n = 0
    mirrors = []                                   # Gmail 에서 받은 메일 원본 — 끝나고 회사 INBOX 에 사본으로
    m = imap_connect(acct["conn"], acct["password"]) if acct else imap_connect(cfg, password)
    try:
        junk = [] if acct else (cfg.get("junk_folders") or [])
        junk_boxes = [b for b in resolve_folders(m, junk) if b != "INBOX" or "INBOX" in junk] if junk else []
        boxes = resolve_folders(m, acct["folders"] if acct else (cfg.get("folders") or ["INBOX"]))
        for box in boxes + [b for b in junk_boxes if b not in boxes]:
            in_junk = box in junk_boxes
            typ, _ = m.select('"%s"' % box)
            if typ != "OK":
                log("폴더를 열지 못했습니다: %s" % box)
                continue
            # 읽음 여부가 아니라 '처리 기록'으로 판단한다. 최근 것만 훑어 과거를 건드리지 않는다.
            #
            # ⚠️ 반드시 UID 를 써야 한다. 시퀀스 번호(m.search/m.fetch)는 메일이 들어오고 나갈 때마다
            #    재배치되므로, Message-ID 없는 메일이 매번 다른 키로 보여 무한 재처리된다(실제로 겪음).
            typ, data = m.uid("SEARCH", "SINCE", since)
            if typ != "OK" or not data or not data[0]:
                continue
            for uid in data[0].split():
                # seed 는 실행하지 않고 기록만 하므로 건수 제한을 두지 않는다
                if not seed_only and n >= max_per_cycle:
                    break
                uid_s = uid.decode() if isinstance(uid, bytes) else str(uid)
                # 태그 확인 전에는 읽음 처리하지 않도록 PEEK 으로 헤더만 본다
                typ, hdr = m.uid("FETCH", uid_s, "(BODY.PEEK[HEADER])")
                if typ != "OK" or not hdr or not hdr[0]:
                    continue
                head = email.message_from_bytes(hdr[0][1])
                subject = decode_hdr(head.get("Subject"))
                # 폰이 답장하며 붙인 'Re:' 등을 벗겨야 태그 매칭이 된다(안 그러면
                # 답장이 그냥 무시되어 대화가 이어지지 않는다).
                clean_subject = strip_reply_prefix(subject)
                clean_subject, subject_key = split_subject_key(clean_subject)   # 폰(개인 메일)이 붙인 암호 단어는 떼어 둔다
                # match_tag 는 (태그, 모드) 튜플을 준다. 튜플 자체로 판정하면
                # (None, None) 도 참이라 모든 메일이 통과해 버린다 — 반드시 태그를 꺼내 확인할 것.
                tag_hit, _mode_hit = match_tag(clean_subject, cfg)
                if not tag_hit:
                    continue

                msgid = (head.get("Message-ID") or "").strip()
                if msgid and msgid in own_reply_ids:
                    # 우리가 append 로 넣은 회신 자신이다 — 새 지시로 오인해 되돌려 답장하면
                    # 무한 핑퐁이 된다. load_own_reply_ids() 참고.
                    processed.add(msgid)
                    continue
                # Message-ID 가 있으면 그것이 가장 안전하다(폴더를 옮겨도 같은 값).
                # 없으면 폴더+UID 로 대신한다.
                key = msgid or ("%s%s#uid%s" % ("gmail:" if acct else "", box, uid_s))
                if key in processed:
                    continue

                sender = email.utils.parseaddr(head.get("From", ""))[1].lower()
                if acct and sender != acct["user"]:
                    # Gmail 받은편지함엔 우리 회신·접수 신호(회사 주소)도 같은 제목으로 온다 — 나에게 보낸 것만 지시다
                    processed.add(key)
                    continue
                if not acct and head.get("X-Dispatch-Mirror"):
                    processed.add(key)                 # Gmail 에서 이미 받은 지시의 사본(mirror_to_company)
                    continue
                if sender not in allowed or in_junk or acct:
                    if not subject_key and sender in {a.lower() for a in (cfg.get("keyed_senders") or {})}:
                        typ, full = m.uid("FETCH", uid_s, "(BODY.PEEK[])")   # 암호 단어가 본문에 있을 수 있다
                        if typ == "OK" and full and full[0]:
                            subject_key = body_key(email.message_from_bytes(full[0][1]))
                    if key_sender_ok(cfg, sender, subject_key):
                        log("암호 단어로 확인한 발신자: %s%s" % (sender, " (스팸함에서 꺼냄)" if in_junk else ""))
                    else:
                        why = " (암호 단어가 없거나 틀림)" if sender in {a.lower() for a in (cfg.get("keyed_senders") or {})} else ""
                        log("허용되지 않은 발신자라 무시합니다: %s%s" % (sender, why))
                        processed.add(key)
                        continue

                auth_ok, auth_note = auth_results_summary(head)
                log("[인증] %s → %s : %s" % (sender, "통과" if auth_ok else "미확인", auth_note))
                if cfg.get("require_auth_results") and not auth_ok:
                    log("발신 인증(DKIM/SPF)을 확인하지 못해 무시합니다: %s" % sender)
                    processed.add(key)
                    continue

                if seed_only:
                    processed.add(key)
                    n += 1
                    continue

                typ, full = m.uid("FETCH", uid_s, "(BODY.PEEK[])")
                if typ != "OK" or not full or not full[0]:
                    continue
                msg = email.message_from_bytes(full[0][1])
                if acct:
                    mirrors.append(full[0][1])         # 받은 것은 무엇이든(지시·답·멈춤) PC 메신저에도 보이게

                # 우리가 보낸 확인 메일에 대한 답장이면 새 지시가 아니라 승인/취소로 처리한다.
                thread_no = thread_of(clean_subject)
                pending = find_pending_confirm(head, thread_no)
                if pending:
                    ppath, pjob = pending
                    answer = parse_confirm_answer(plain_body(msg))
                    processed.add(key)
                    save_processed(processed)
                    m.uid("STORE", uid_s, "+FLAGS", "\\Seen")
                    if answer == "yes":
                        pjob["status"] = "queued"
                        pjob["confirmed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        write_json(ppath, pjob)
                        n += 1
                        log("쓰기 지시 확인됨 %s — 실행 대기열에 넣습니다" % pjob["id"])
                    elif answer == "no":
                        pjob["status"] = "canceled"
                        pjob["error"] = "확인 답장으로 취소했습니다."
                        pjob["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        write_json(ppath, pjob)
                        log("쓰기 지시 취소됨 %s" % pjob["id"])
                    else:
                        log("확인 답장을 알아듣지 못했습니다(1=실행, 2=취소) %s" % pjob["id"])
                    continue

                # 돌고 있는(대기 중인) 일을 멈추라는 말이면 새 잡을 만들지 않고 워커에 멈춤 표시(jobs\<id>.stop)만 남긴다.
                # 폰 대화방의 '멈춤' 단추는 그 지시에 대한 답장으로 '멈춤' 한 마디를 보낸다. 끝난 일에 대한 '멈춤' 은
                # 지금처럼 그 세션에 '정리하고 보고해' 로 이어진다.
                if reply_text(plain_body(msg)).strip().lower() in STOP_WORDS:
                    live = find_live_job(head, thread_no)
                    if live:
                        processed.add(key)
                        save_processed(processed)
                        m.uid("STORE", uid_s, "+FLAGS", "\\Seen")
                        open(os.path.join(JOBS, live["id"] + ".stop"), "w").close()
                        log("멈춤 요청 %s (%s)" % (live["id"], live.get("status")))
                        continue
                    if not find_resume_job(head) and not (thread_no is not None and find_thread_job(thread_no)):
                        # 멈출 일이 없다 — 대개 메일 도착 순서가 뒤바뀌어 지시보다 '멈춤' 이 먼저 온 것(그대로 두면
                        # 멈춤이 새 지시로 돌고 진짜 지시는 끝까지 돈다). 새 잡을 만들지 않고, 가리키는 지시를 기억해 둔다.
                        refs = re.findall(r"<[^<>]+>", " ".join(str(head.get(h) or "") for h in ("In-Reply-To", "References")))
                        if refs:
                            stops = early_stops()
                            stops.update({r: time.time() for r in refs})
                            write_json(EARLY_STOP_PATH, stops)
                        processed.add(key)
                        save_processed(processed)
                        m.uid("STORE", uid_s, "+FLAGS", "\\Seen")
                        log("멈춤 요청 — 멈출 일이 아직 없음(지시보다 먼저 옴). 그 지시가 오면 실행하지 않습니다: %s" % (", ".join(refs) or "대상 없음"))
                        continue

                prompt, workdir, label, mode = build_instruction(clean_subject, plain_body(msg), cfg)

                if not prompt:
                    log("지시 내용이 비어 있어 건너뜁니다: %s" % subject)
                    processed.add(key)
                    continue

                # 이전 잡에 대한 답장이면 그 세션을 이어받는다. 세션은 작업 폴더에
                # 묶여 있으므로 워크폴더도 그때 그대로 맞춘다(제목의 @키보다 우선한다).
                # 이어받을 잡: 제목의 스레드 표식([T12])이 먼저, 없으면 In-Reply-To/References.
                resume_id = None
                denied = []
                prev = (find_thread_job(thread_no) if thread_no is not None else None) or find_resume_job(head)
                if prev:
                    resume_id, denied = prev["session_id"], prev.get("disallowed_tools") or []
                    thread_no = prev.get("thread") or thread_no
                    # 대화는 처음 권한(읽기/수정)을 그대로 잇는다 — 수정 대화에 '#c' 로 답해도 읽기 전용으로 떨어지지 않게
                    mode = prev.get("mode") or mode
                    if prev.get("workdir"):
                        workdir, label = prev["workdir"], (prev.get("workdir_label") or label)
                    # 이어지는 말은 답장 본문만(제목을 매번 다시 붙이지 않는다). 번호 답이면 선택지 내용으로 푼다.
                    said = reply_text(plain_body(msg))
                    if said.strip().lower() in STOP_WORDS:
                        said = "멈춤"
                    prompt = (parse_answer(said, prev.get("ask")) or said or prompt)[: int(cfg["max_prompt_chars"])]

                if not os.path.isdir(workdir):
                    log("작업 폴더가 없습니다: %s" % workdir)
                    processed.add(key)
                    continue

                # 폰이 붙인 사진 — 저장하고 지시문 끝에 경로를 적어 Claude 가 Read 로 열어 보게 한다
                attach_dir, photos = save_images(msg, datetime.now().strftime("%Y%m%d-%H%M%S-") + "%04x" % random.randrange(0x10000))
                if photos:
                    prompt = (prompt + "\n\n[첨부 사진 %d장 — Read 도구로 열어 보고 지시에 맞게 쓸 것]\n" % len(photos)
                              + "\n".join("- " + p for p in photos))
                    log("첨부 사진 %d장 → %s" % (len(photos), attach_dir))

                # 실행 전에 먼저 기록한다. 중간에 죽어도 같은 지시가 다시 돌지 않게 하는 편이
                # 안전하다(특히 쓰기 모드에서 재실행은 위험하다).
                processed.add(key)
                save_processed(processed)
                stops = early_stops()
                stopped = bool(msgid and msgid in stops)          # 이 지시를 가리키는 멈춤이 먼저 와 있었다
                needs_confirm = mode == "write" and not resume_id and bool(cfg.get("confirm_write", True)) and not stopped
                job = new_job(prompt, workdir, label, msgid, clean_subject, sender, mode, cfg,
                              resume_id=resume_id, confirm=needs_confirm, disallowed_tools=denied,
                              thread=thread_no if resume_id else None,
                              allowed_tools=(prev or {}).get("allowed_tools") if resume_id else None,
                              stopped=stopped, attach_dir=attach_dir)
                if stopped:
                    stops.pop(msgid, None)
                    write_json(EARLY_STOP_PATH, stops)
                    log("먼저 온 멈춤에 따라 실행하지 않음 %s" % job["id"])
                m.uid("STORE", uid_s, "+FLAGS", "\\Seen")   # 읽음 표시는 사람이 보기 편하라고
                n += 1
                tail = (" · 이어서 세션 %s" % resume_id) if resume_id else ""
                if needs_confirm:
                    tail += " · 확인 답장 대기"
                log("지시 접수 %s [%s/%s]%s — %s" % (job["id"], box, mode, tail, prompt[:55].replace("\n", " ")))
    finally:
        save_processed(processed)
        try:
            m.close()
        except Exception:
            pass
        try:
            m.logout()
        except Exception:
            pass
        if mirrors:
            mirror_to_company(cfg, password, mirrors)
    return n


_GMAIL_ERR = [""]


def poll_gmail(cfg: dict, password: str, seed_only: bool = False) -> int:
    """Gmail 받은편지함 폴링. 꺼져 있으면 0. 실패해도 회사 메일 폴링은 계속 돌게 여기서 삼키고, 같은 오류는 한 번만 적는다."""
    try:
        ga = gmail_account(cfg)
        if not ga:
            return 0
        n = poll_once(cfg, password, seed_only=seed_only, acct=ga)
        if _GMAIL_ERR[0]:
            log("Gmail 폴링 복구")
            _GMAIL_ERR[0] = ""
        return n
    except Exception as e:
        if str(e) != _GMAIL_ERR[0]:
            log("Gmail 폴링 오류 — %s" % e)
            _GMAIL_ERR[0] = str(e)
        return 0


def reply_parts(job: dict):
    """(ask, 본문, 꼬리) — 글자 본문과 HTML 본문이 같은 재료를 쓴다."""
    body, ask = parse_choices(job.get("result") or "")
    if job["status"] != "done":
        ask = None
    text = format_reply(dict(job, result=body), footer=False)
    return ask, text, reply_footer(job)


def reply_footer(job: dict) -> str:
    secs = int((job.get("duration_ms") or 0) / 1000)
    cost = job.get("cost_usd") or 0
    # 쓰기 권한으로 돌았다는 사실은 눈에 띄어야 한다
    mode_note = " · 수정 허용 모드" if job.get("mode") == "write" else ""
    resume_note = " · 이어서 실행" if job.get("resume_id") else ""
    lines = ["%s작업 폴더 %s · %d초 · $%.3f%s%s" % (
        ("[T%s] · " % job["thread"]) if job.get("thread") else "", job["workdir"], secs, cost, mode_note, resume_note)]
    # 이 대화를 PC 에서 그대로 이어받을 수 있게 안내한다(맥락을 다시 설명하지 않아도 된다)
    if job.get("session_id"):
        lines.append("PC에서 이어서: cd %s && claude --resume %s" % (job["workdir"], job["session_id"]))
    return "\n".join(lines)


def format_reply(job: dict, footer: bool = True) -> str:
    lines = []
    if job["status"] == "done":
        lines.append(job.get("result") or "")
    else:
        lines.append("실행에 실패했습니다.")
        lines.append("")
        lines.append(job.get("error") or "")
        if job.get("result"):
            lines.append("")
            lines.append(job["result"])

    denied = sorted({d.get("tool_name", "?") for d in (job.get("denials") or []) if isinstance(d, dict)})
    if denied:
        lines += ["", "--", "차단된 도구: %s (읽기 전용이라 실행되지 않았습니다)" % ", ".join(denied)]

    if footer:
        lines += ["", "--", reply_footer(job)]
    return "\n".join(lines)


def build_reply_message(cfg: dict, job: dict):
    """반환값 (msg, reply_msgid). reply_msgid 는 job 에 남겨 다음 답장이 이 메일을
    가리킬 때(스레드가 이어질 때) 세션을 다시 찾아 이어붙일 수 있게 한다."""
    msg = EmailMessage()
    msg["Subject"] = reply_subject(job)
    msg["From"] = cfg["user"]
    msg["To"] = job.get("mail_from") or cfg["user"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    domain = cfg["user"].split("@", 1)[-1] if "@" in (cfg.get("user") or "") else None
    rmid = email.utils.make_msgid(domain=domain)
    msg["Message-ID"] = rmid
    if job.get("mail_msgid"):
        # 폰 메일 앱에서 원본과 한 스레드로 묶이게 한다
        msg["In-Reply-To"] = job["mail_msgid"]
        msg["References"] = job["mail_msgid"]
    ask, text, footer = reply_parts(job)
    mark_bot(msg, job, ask)
    plain = ask_lines(ask) + (["", "─" * 16, ""] if ask else []) + [text, "", "--", footer]
    msg.set_content("\n".join(plain))
    msg.add_alternative(reply_html(cfg, job, ask, text, footer), subtype="html")
    return msg, rmid


def build_confirm_message(cfg: dict, job: dict):
    """쓰기 지시를 실행하기 전에 보내는 확인 메일. 반환값 (msg, msgid).

    제목은 원본에 Re: 만 붙여 같은 스레드로 보이게 하고(그래야 폰에서 그냥 답장하면 된다),
    msgid 는 job 의 confirm_msgid 로 남겨 그 메일에 대한 답장을 승인/취소로 알아본다.
    """
    msg = EmailMessage()
    msg["Subject"] = reply_subject(job)
    msg["From"] = cfg["user"]
    msg["To"] = job.get("mail_from") or cfg["user"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    domain = cfg["user"].split("@", 1)[-1] if "@" in (cfg.get("user") or "") else None
    mid = email.utils.make_msgid(domain=domain)
    msg["Message-ID"] = mid
    if job.get("mail_msgid"):
        msg["In-Reply-To"] = job["mail_msgid"]
        msg["References"] = job["mail_msgid"]
    ttl = int(cfg.get("confirm_ttl_min", 60))
    prompt = (job.get("prompt") or "")
    shown = prompt if len(prompt) <= 600 else prompt[:600] + "…"
    text = "\n".join([
        "수정·실행이 허용되는 지시(쓰기 모드)라 실행 전에 확인합니다.",
        "",
        "작업 폴더: %s" % job.get("workdir"),
        "허용 도구: %s" % ", ".join(job.get("allowed_tools") or []),
        "",
        "지시:",
        shown,
        "",
        "-- 이 메일에 답장하세요",
        "  1  (또는 '확인')  →  실행",
        "  2  (또는 '취소')  →  취소",
        "%d분 안에 답이 없으면 자동으로 취소됩니다." % ttl,
        "내가 보낸 지시가 아니라면 답하지 말고 두세요(자동 취소됩니다).",
    ])
    msg.set_content(text)
    ask = {"question": "실행할까요?", "multi": False, "options": ["실행", "취소"]}
    mark_bot(msg, job, ask, kind="confirm")
    msg.add_alternative(reply_html(cfg, job, ask, text, "[T%s]" % job.get("thread", "?")), subtype="html")
    return msg, mid


def build_ack_message(cfg: dict, job: dict):
    """폰(개인 주소)에서 온 지시를 받았다는 짧은 신호. 폰 페이지가 이걸 보고 말풍선의 '1' 을 지운다
    (카톡 읽음 표시) — 스팸 격리 등으로 PC 가 아직 못 받은 것과 일하는 중을 가른다. 말풍선으로는 안 보인다."""
    msg = EmailMessage()
    msg["Subject"] = reply_subject(job)
    msg["From"] = cfg["user"]
    msg["To"] = job["mail_from"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    domain = cfg["user"].split("@", 1)[-1] if "@" in (cfg.get("user") or "") else None
    msg["Message-ID"] = email.utils.make_msgid(domain=domain)
    if job.get("mail_msgid"):
        msg["In-Reply-To"] = job["mail_msgid"]
        msg["References"] = job["mail_msgid"]
    msg.set_content("PC 가 지시를 받았습니다. 끝나면 답을 보냅니다.")
    mark_bot(msg, job, kind="ack")
    return msg


def send_acks(cfg: dict, password: str) -> int:
    """폰에서 온 새 잡에 접수 신호를 한 번 보낸다(회사 메일함에는 넣지 않는다). 30분 넘은 잡·이미 회신한 잡은 건너뛴다.
    보냈다는 기록은 잡 파일이 아니라 acked.json 에 둔다 — 잡 파일은 워커가 돌면서 고쳐 쓰므로 여기서 쓰면 서로 덮어쓴다."""
    if not os.path.isdir(JOBS):
        return 0
    acked = set(read_json(ACKED_PATH) or [])
    smtp_box, n, before = [], 0, len(acked)
    try:
        for path, job in iter_jobs():
            if not isinstance(job, dict) or job.get("source") != "mail" or job.get("id") in acked or job.get("replied") or not keyed_word(cfg, job.get("mail_from")):
                continue
            try:
                age = (datetime.now() - datetime.strptime(job.get("created_at") or "", "%Y-%m-%d %H:%M:%S")).total_seconds()
            except ValueError:
                age = 1e9
            acked.add(job["id"])                      # 실패해도 다시 보내지 않는다(회신이 어차피 간다)
            if age > 1800:
                continue
            try:
                if not smtp_box:
                    smtp_box.append(smtp_connect(cfg, password))
                to = phone_to(cfg, job["mail_from"])
                smtp_box[0].send_message(build_ack_message(cfg, job), to_addrs=[to])
                n += 1
                log("접수 신호 %s → %s" % (job["id"], to))
            except Exception as e:
                log("접수 신호 실패 %s — %s" % (job["id"], e))
    finally:
        for s in smtp_box:
            try:
                s.quit()
            except Exception:
                pass
        if len(acked) != before:
            write_json(ACKED_PATH, sorted(acked)[-500:])
    return n


def send_replies(cfg: dict, password: str) -> int:
    if not os.path.isdir(JOBS):
        return 0
    pending = []
    for fn in sorted(os.listdir(JOBS)):
        if not fn.endswith(".json"):
            continue
        job = read_json(os.path.join(JOBS, fn))
        # 확인 메일을 아직 안 보낸 쓰기 지시
        if job and job.get("source") == "mail" and job.get("status") == "awaiting_confirm" \
                and not job.get("confirm_sent"):
            pending.append((os.path.join(JOBS, fn), job))
            continue
        # MAIL_SOURCES 에 더한 다른 자동화의 첫 잡도 여기서 메일로 내보낸다.
        # 그 이후 답장은 find_resume_target 을 거쳐 source="mail" 로 새로 생성된다.
        if not job or job.get("source") not in MAIL_SOURCES or job.get("replied"):
            continue
        if job.get("status") not in ("done", "error"):
            continue
        pending.append((os.path.join(JOBS, fn), job))
    if not pending:
        return 0

    n = 0
    mode = "append" if cfg.get("reply_mode") == "append" else "smtp"
    conn = imap_connect(cfg, password) if mode == "append" else smtp_connect(cfg, password)
    phone_smtp = []                                    # 폰(개인 주소)으로 보낼 회신용 SMTP — 필요할 때만 연결
    try:
        for path, job in pending:
            if job.get("status") == "awaiting_confirm":
                # 확인 메일 발송. 실패하면 사람이 답할 방법이 없으므로 잡을 실패로 끝낸다(무한 재시도 방지).
                try:
                    ensure_thread(job, cfg)
                    cmsg, cmid = build_confirm_message(cfg, job)
                    if mode == "append":
                        conn.append("INBOX", "", imaplib.Time2Internaldate(time.time()), cmsg.as_bytes())
                        copy_to_phone(cfg, password, job, cmsg, phone_smtp)
                    else:
                        conn.send_message(cmsg, to_addrs=smtp_rcpts(cfg, job))
                    job["confirm_sent"] = True
                    job["confirm_msgid"] = cmid
                    write_json(path, job)
                    n += 1
                    log("확인 메일 전달 %s (%s)" % (job["id"], mode))
                    notify("메일 인박스 · 확인 필요", "쓰기 지시 실행 확인 메일을 보냈습니다.", "Info")
                except Exception as e:
                    log("확인 메일 실패 %s — %s" % (job["id"], e))
                    job["status"] = "error"
                    job["error"] = "확인 메일을 보내지 못해 실행하지 않았습니다: %s" % e
                    job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    job["replied"] = True
                    write_json(path, job)
                continue
            try:
                ensure_thread(job, cfg)
                # 번호 답을 풀 수 있게 이번 질문(선택지)을 잡에 남긴다 — 다음 답장이 이 잡을 이어받는다
                job["ask"] = parse_choices(job.get("result") or "")[1] if job.get("status") == "done" else None
                msg, rmid = build_reply_message(cfg, job)
                if mode == "append":
                    # INBOX 에 직접 넣는다. 발송하면 메일 규칙에 걸려 다른 폴더로 옮겨지므로
                    # 이쪽이 결과를 확실히 보여준다. 폰에서는 똑같이 새 메일로 보인다.
                    conn.append("INBOX", "", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                    copy_to_phone(cfg, password, job, msg, phone_smtp)
                else:
                    conn.send_message(msg, to_addrs=smtp_rcpts(cfg, job))

                job["replied"] = True
                job["reply_msgid"] = rmid
                write_json(path, job)
                n += 1
                log("회신 전달 %s (%s, %s)" % (job["id"], job["status"], mode))
                head = (job.get("result") or job.get("error") or "")[:90]
                notify("메일 인박스 · 회신", head, "Info" if job["status"] == "done" else "Warning")
            except Exception as e:
                log("회신 실패 %s — %s" % (job["id"], e))
                # 계속 재시도해도 소용없는 경우가 많아 한 번만 시도한다
                job["replied"] = True
                job["error"] = ((job.get("error") or "") + " / 회신 실패: %s" % e).strip(" /")
                write_json(path, job)
    finally:
        try:
            conn.logout() if mode == "append" else conn.quit()
        except Exception:
            pass
        for s in phone_smtp:
            try:
                s.quit()
            except Exception:
                pass
    return n


# ----------------------------------------------------------------- 명령

def cmd_setup() -> int:
    """메일 계정·비밀번호는 저장소 맨 위 설정 마법사(setup.py)가 config.local.json 에 넣는다 — 그쪽으로 넘긴다."""
    wizard = os.path.join(HERE, "setup.py")
    if os.path.isfile(wizard):
        print("설정 마법사(setup.py)를 엽니다 — 메일 계정과 '메일로 일 맡기기(dispatch)' 를 거기서 채웁니다.\n")
        return subprocess.call([sys.executable, wizard], cwd=HERE)
    print("설정 마법사(setup.py)가 없습니다. config.example.json 을 config.local.json 으로 복사해 mail · dispatch 를 채우세요.")
    print("비밀번호는 평문으로 넣지 않습니다 — kit.protect() 로 암호화한 값을 mail.password_enc 에 넣습니다.")
    return 1


def save_gmail(value: dict) -> None:
    """config.local.json 의 dispatch.gmail 만 바꾼다(다른 값은 파일 그대로 — 기본값을 채워 쓰지 않는다)."""
    full = kit._read(kit.F_CONFIG)
    full["dispatch"] = dict(full.get("dispatch") or {}, gmail=value)
    kit.save_config(full)


def cmd_setup_gmail() -> int:
    """
    폰 지시를 Gmail 에서 직접 읽도록 Gmail 주소와 앱 비밀번호를 받는다(입력 창 — 터미널·기록에 안 남는다).
    앱 비밀번호: Google 계정 > 보안 > 2단계 인증을 켠 뒤 '앱 비밀번호'에서 만든 16자리.
    그 주소는 keyed_senders(암호 단어 주소)에 있어야 한다. 저장하면 지금 있는 메일은 실행하지 않고 처리됨으로 기록한다.
    """
    import tkinter as tk
    from tkinter import ttk

    cfg = load_cfg()
    g = dict(cfg.get("gmail") or {})
    keyed = list(cfg.get("keyed_senders") or {})

    root = tk.Tk()
    root.title("메일 게이트웨이 — Gmail 직접 읽기")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    frm = ttk.Frame(root, padding=16)
    frm.grid(sticky="nsew")
    ttk.Label(frm, text="폰이 '나에게' 보낸 지시를 Gmail 에서 바로 읽습니다(회사 스팸 장비를 거치지 않음).\n"
                        "비밀번호는 Google 계정의 '앱 비밀번호'(16자리)를 넣으세요. 비우면 이 기능을 끕니다.",
              justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
    ttk.Label(frm, text="Gmail 주소").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
    e_user = ttk.Entry(frm, width=34)
    e_user.insert(0, g.get("user") or (keyed[0] if keyed else ""))
    e_user.grid(row=1, column=1, pady=4)
    ttk.Label(frm, text="앱 비밀번호").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)
    e_pw = ttk.Entry(frm, width=34, show="*")
    e_pw.grid(row=2, column=1, pady=4)
    e_pw.focus()
    status = ttk.Label(frm, text="", foreground="#555")
    status.grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))
    btns = ttk.Frame(frm)
    btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(14, 0))
    state = {"ok": False}

    def say(msg, color="#555"):
        status.configure(text=msg, foreground=color)
        root.update()

    def on_ok():
        user = e_user.get().strip().lower()
        pw = e_pw.get().replace(" ", "")              # Google 은 'abcd efgh ijkl mnop' 처럼 띄어 보여 준다
        if not pw:
            cfg["gmail"] = {}
            save_gmail({})
            log("Gmail 직접 읽기를 껐습니다")
            say("껐습니다. 창을 닫습니다.", "#070")
            state["ok"] = True
            root.after(900, root.destroy)
            return
        if user not in {a.lower() for a in (cfg.get("keyed_senders") or {})}:
            say("이 주소는 암호 단어 주소(dispatch.keyed_senders)가 아닙니다 — config.local.json 에 먼저 넣으세요.", "#c00")
            return
        b_ok.configure(state="disabled")
        try:
            say("Gmail IMAP 로그인 확인 중...")
            m = imap_connect(dict(GMAIL_IMAP, user=user, login_user=""), pw)
            m.select("INBOX")
            m.logout()
            cfg["gmail"] = dict(g, user=user, password_enc=kit.protect(pw))
            save_gmail(cfg["gmail"])
            say("과거 메일을 처리됨으로 기록하는 중...")
            n = poll_gmail(cfg, get_password(cfg), seed_only=True)
            log("Gmail 직접 읽기를 켰습니다: %s (과거 메일 %d건 처리됨으로 기록)" % (user, n))
            state["ok"] = True
            say("저장했습니다. 창을 닫습니다.", "#070")
            root.after(900, root.destroy)
        except Exception as ex:
            log("Gmail 설정 실패 [%s] %s" % (type(ex).__name__, ex))
            say("실패: %s" % str(ex)[:90], "#c00")
            b_ok.configure(state="normal")

    b_ok = ttk.Button(btns, text="확인", command=on_ok)
    b_ok.grid(row=0, column=0, padx=(0, 6))
    ttk.Button(btns, text="취소", command=root.destroy).grid(row=0, column=1)
    root.bind("<Return>", lambda _e: on_ok())
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 3))
    root.mainloop()
    return 0 if state["ok"] else 1


def get_password(cfg: dict) -> str:
    if not cfg.get("password_enc"):
        raise RuntimeError("메일 비밀번호가 설정되지 않았습니다 — python setup.py")
    return kit.password(cfg)


def cmd_test() -> int:
    cfg = load_cfg()
    pw = get_password(cfg)
    m = imap_connect(cfg, pw)
    m.select("INBOX")
    typ, data = m.search(None, "UNSEEN")
    cnt = len(data[0].split()) if data and data[0] else 0
    print("IMAP OK — 안 읽은 메일 %d건, 태그 '%s'" % (cnt, cfg["tag"]))
    m.logout()
    print("  켜짐(dispatch.enabled): %s" % ("예" if cfg.get("enabled") else "아니오 — 켜야 지시를 받습니다"))
    print("  허용 발신자: %s" % (", ".join(cfg["allowed_senders"]) or "(비어 있음 — 모든 메일을 무시합니다)"))
    print("  감시 폴더: %s · 회신 방법: %s · 기본 작업 폴더: %s"
          % (", ".join(cfg["folders"]), cfg.get("reply_mode"), cfg["default_workdir"]))
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--setup-gmail" in args:
        return cmd_setup_gmail()
    if "--setup" in args or "--setup-gui" in args:
        return cmd_setup()
    if "--test" in args:
        return cmd_test()
    if "--seed" in args:
        # 지금 조건에 맞는 메일을 실행하지 않고 '처리됨'으로만 기록한다.
        cfg = load_cfg()
        n = poll_once(cfg, get_password(cfg), seed_only=True) + poll_gmail(cfg, get_password(cfg), seed_only=True)
        print("기존 메일 %d건을 처리됨으로 기록했습니다(실행하지 않음)." % n)
        return 0

    once = "--once" in args
    os.makedirs(INBOX, exist_ok=True)
    cfg = load_cfg()
    if not cfg.get("enabled"):
        # 꺼져 있으면 메일함에 접속하지도 않는다. 허브 서비스 매크로도 켜질 때까지 이 프로그램을 띄우지 않는다.
        log("메일로 일 맡기기(dispatch.enabled)가 꺼져 있어 아무것도 하지 않고 끝냅니다.")
        set_state("disabled", "꺼짐 (config.local.json 의 dispatch.enabled)")
        return 0

    handle = single_instance()
    if handle is None:
        log("이미 실행 중이라 종료합니다.")
        return 0

    log("메일 게이트웨이 시작")
    try:
        pw = get_password(cfg)
    except Exception as e:
        log(str(e))
        set_state("waiting", "설정 필요 (python setup.py)")
        return 1

    last_state = 0.0
    fail_streak = 0
    error_notified = False
    while True:
        try:
            cfg = load_cfg()
            if not cfg.get("enabled"):
                # 도는 중에 꺼졌으면 끝내지 않고 쉰다 — 끝내면 허브가 '금방 죽었다'며 다시 띄우기를 되풀이한다.
                if time.time() - last_state >= 30:
                    set_state("disabled", "꺼짐 (config.local.json 의 dispatch.enabled)")
                    last_state = time.time()
            elif os.path.isfile(PAUSE_PATH):
                if time.time() - last_state >= 30:
                    set_state("paused", "일시정지 중")
                    last_state = time.time()
            else:
                got = poll_once(cfg, pw) + poll_gmail(cfg, pw)
                send_acks(cfg, pw)
                sent = send_replies(cfg, pw)
                if time.time() - last_state >= 30 or got or sent:
                    set_state("idle", "감시 중 (태그 %s)" % cfg["tag"])
                    last_state = time.time()
        except Exception as e:
            log("폴링 오류 — %s" % e)
            set_state("error", str(e)[:120])
            last_state = time.time()
            # 같은 오류가 이어질 때 한 번만 알린다(20초마다 알리면 풍선이 쏟아진다).
            # 비밀번호 만료·IMAP 장애가 로그에만 남아 조용히 지나가던 것을 막는다.
            fail_streak += 1
            if fail_streak == ERROR_NOTIFY_AFTER:
                notify("메일 게이트웨이 · 오류", "폴링이 계속 실패합니다: %s" % str(e)[:80], "Warning")
                error_notified = True
        else:
            if error_notified:
                notify("메일 게이트웨이 · 복구", "폴링이 다시 정상입니다.", "Info")
                error_notified = False
            fail_streak = 0

        if once:
            break
        time.sleep(max(5, int(cfg.get("poll_sec", 20))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
