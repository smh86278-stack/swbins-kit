# -*- coding: utf-8 -*-
"""
디스패치 대화 — 메일을 메신저처럼 보는 PC 화면. 윈도우·맥.

일을 맡기고 답을 받는 통로는 메일이다(게이트웨이 PC 의 mail-gateway.py 가 지시 메일을 받아 Claude 를 돌리고 회신한다).
이 앱은 그 메일함을 IMAP 으로 읽어 대화 번호 [T12] 별 대화방으로 묶어 말풍선으로 보여 주고, 입력한 말을 메일로 보낸다.
PC 끼리 직접 연결할 필요가 없다 — 메일 서버만 닿으면 어느 PC 에서든 같은 대화를 본다.

    python chat.py              서버를 띄우고 앱 창(Edge, 맥은 Edge·크롬)으로 연다(이미 떠 있으면 창만 연다)
    python chat.py --serve      창 없이 서버만(이 PC 에서는 자동화 허브의 svc_dispatch_chat 이 이렇게 띄운다)
    DispatchChat.exe / .app     build.py 로 만든다 — 처음 열면 메일 계정을 묻는다. 맥은 DispatchChat.command 더블클릭도 된다

표준 라이브러리만 쓴다(PyInstaller 로 exe 한 파일 — 그래서 kit.py 를 import 하지 않는다. DPAPI 는 kit.py 와 같은 방식이라
키트 설정의 password_enc 를 그대로 푼다).

- 화면은 127.0.0.1 에만 연다. 보내기 같은 POST 는 띄울 때마다 새로 만드는 토큰이 있어야 한다(화면에만 심는다).
- 메일: IMAP·SMTP 가 되는 메일이면 어디든. 회사 밖 메일은 암호 단어(key_word)를 본문 마지막 줄 [k:단어] 로 붙인다 —
  게이트웨이가 그 주소·단어(dispatch.keyed_senders)를 알아야 지시로 받는다.
- 계정(load_cfg): 이 PC 의 앱 설정(윈도우 %APPDATA%\\DispatchChat\\config.json · 맥 ~/Library/Application Support/DispatchChat)에
  계정이 있으면 그것 → 없고 이 키트 저장소 안에서 돌면 키트 공통 설정(저장소 맨 위 config.local.json 의 mail · dispatch, 출처 'kit')
  → 기본값. 비밀번호는 윈도우 DPAPI · 맥 키체인에 둔다.
- 키트 설정을 쓰는 이 PC 가 곧 게이트웨이 PC 다 — 진행 상황은 키트 작업 인박스(inbox/jobs)의 Claude 세션 기록(~/.claude/projects)을
  2초마다 읽어 단계로 보여 주고, ⚙ 「작업 폴더 (게이트웨이)」 칸은 config.local.json 의 dispatch.default_workdir · workdir_keys 를 고친다.
- 봇 메일은 게이트웨이가 붙이는 X-Dispatch-* 헤더로 알아본다(선택지는 X-Dispatch-Ask). 표식 이전의 옛 회신은 꼬리말로 짐작한다.
- 이 PC 에서 직접 실행(chat_runner.py, 설정 화면 스위치 — 기본 꺼짐): 켜면 게이트웨이 없이 이 앱이 내 메일함의 지시를 받아
  이 PC 의 Claude Code(claude -p)로 돌리고 같은 형식으로 회신한다. 게이트웨이 PC(키트 설정 사용 · 키트 게이트웨이 켜짐)에서는 켜지지 않는다.
- Jira 새 티켓 감시(jira_watch.py, 설정 화면 스위치 — 기본 꺼짐): 직접 실행 PC 에서 내게 배정된 새 티켓을 1분마다 보고, 자리비움이
  켜져 있으면 '/jira 키' 작업을 이 앱의 큐에 넣는다. 꺼져 있으면 처리됨으로만 적는다. 게이트웨이 PC 에서는 키트의
  jira-watch.py(config.local.json 의 jira 갈래)가 같은 일을 하므로 이 감시는 켜지지 않는다.
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
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import parse_qs, urlparse

import chat_runner

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
if IS_WIN:
    from ctypes import wintypes

FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))     # ui.html 이 있는 곳(exe 면 풀린 임시 폴더)
# 펫(허브와 같은 강아지·고양이 코드) — exe 면 같이 묶인 pet\, 소스로 돌면 허브의 ..\macro-hub\web\. 인형 그림(skins\plush)이
# 없으면 화면에 펫 칸이 뜨지 않는다(PetSkin.load 가 null)
SRC = os.path.dirname(os.path.abspath(__file__))


def _pet_dir():
    """펫 코드·그림이 있는 곳. exe 면 같이 묶인 pet\(그림은 skin\plush). 소스로 돌 땐 허브의 ..\macro-hub\web(그림 skins\plush)."""
    if FROZEN:
        return os.path.join(RES, "pet"), "skin"
    for rel, skin in (("../macro-hub/web", "skins"), ("../pet", "skin")):
        d = os.path.normpath(os.path.join(SRC, rel))
        if os.path.isfile(os.path.join(d, "pets.js")):
            return d, skin
    return os.path.normpath(os.path.join(SRC, "../macro-hub/web")), "skins"


PET_WEB, PET_SKIN = _pet_dir()
PET_FILES = {"pets.js": "text/javascript; charset=utf-8", "petwarp.js": "text/javascript; charset=utf-8", "pets.css": "text/css; charset=utf-8"}
PET_TYPES = {"webp": "image/webp", "png": "image/png", "json": "application/json; charset=utf-8"}
HUB_SKIN = "http://127.0.0.1:%d/api/skin" % int(os.environ.get("KIT_HUB_PORT") or 8630)   # 이 PC 에 키트 허브가 있으면 고른 품종을 따른다

# 키트 저장소 안(tools\dispatch-chat)에서 돌면 키트 공통 설정·작업 인박스가 저장소 맨 위에 있다. exe 는 저장소 밖에서 도는 것으로 본다.
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
KIT_HERE = not FROZEN and os.path.isfile(os.path.join(REPO_ROOT, "mail-gateway.py"))
KIT_CFG = os.path.join(REPO_ROOT, "config.local.json") if KIT_HERE else ""
INBOX = os.path.join(REPO_ROOT, "inbox") if KIT_HERE else ""
JOBS_DIR = os.path.join(INBOX, "jobs") if INBOX else ""
KIT_DEFAULT_WORKDIR = r"%USERPROFILE%\Documents"          # mail-gateway.py DEFAULT_CFG 의 default_workdir 와 같게
KIT_ISSUE_COMMAND = "/issue"                               # mail-gateway.py DEFAULT_CFG 의 issue_command 와 같게
# Claude Code 가 세션마다 남기는 기록(한 일을 한 줄씩 바로 쓴다) — 워커가 돌리는 작업의 진행 상황을 여기서 읽는다
CLAUDE_PROJECTS = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"), "projects")
if IS_WIN:
    APPDATA = os.path.join(os.environ.get("APPDATA") or HERE, "DispatchChat")
    LOCALDATA = os.path.join(os.environ.get("LOCALAPPDATA") or HERE, "DispatchChat")
else:                                                      # 맥(리눅스도) — 설정·로그를 한 폴더에
    APPDATA = LOCALDATA = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "DispatchChat") if IS_MAC \
        else os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "DispatchChat")
OWN_CFG = os.path.join(APPDATA, "config.json")
LOG_PATH = os.path.join(LOCALDATA, "chat.log")
HIDDEN_PATH = os.path.join(LOCALDATA, "hidden.json")      # 화면에서 지운 대화(키 목록) — 메일은 그대로, 이 PC 목록에서만 숨긴다
CLEARED_PATH = os.path.join(LOCALDATA, "cleared.json")    # 전체 지우기 시각 — 그 전에 끝난 대화를 숨긴다(새 글이 오면 다시 보임)
URGENT_PATH = os.path.join(LOCALDATA, "urgent.json")      # 🔥 급건 표시한 대화(키 목록) — 목록 맨 위
SNIPPETS_PATH = os.path.join(LOCALDATA, "snippets.json")  # 📝 저장해 두는 답(글 목록) — 없으면 기본 몇 개
KEY_RE = re.compile(r"\s*\[k:[^\]\s]{1,64}\]\s*$")       # 폰이 제목 끝에 붙이는 암호 단어 — 화면에는 안 보인다
BODY_KEY_RE = re.compile(r"^[ \t]*\[k:[^\]\s]{1,64}\][ \t\r]*$", re.M)   # 폰(Gmail) 페이지는 본문 마지막 줄에 붙인다
PORT = int(os.environ.get("DISPATCH_CHAT_PORT") or 8620)   # 그 PC 에서 8620 이 이미 쓰이면 바꿔 띄운다

# 회사 값 — 이 코드는 어느 회사든 같고, 회사마다 다른 것(메일 서버·Jira 접두어·설정 화면 프리셋)만 옆의 company.json 에 둔다.
# 저장소에는 견본(company.example.json)만 있다 — 복사해 채우면(git 제외) 설정 화면이 그 값으로 시작하고 exe 에도 같이 묶인다.
def read_json_quiet(path):
    """있으면 JSON, 없거나 깨졌으면 None(로그 없이 — 모듈을 읽는 중에도 부른다)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


COMPANY = read_json_quiet(os.path.join(RES, "company.json")) or {}

DEFAULTS = {
    "user": "", "login_user": "", "password_enc": "",
    "imap_host": "", "imap_port": 993, "imap_mode": "ssl",                 # 서버는 설정 화면에서 — 메일 주소를 넣으면 알려진 곳은 채워진다
    "smtp_host": "", "smtp_port": 587, "smtp_mode": "starttls",
    "ca_bundle": "",          # 사내 TLS 검사 프록시가 있으면 그 루트 인증서(.pem) 경로
    # 보내는 방법: smtp = 실제 발송(내게 보내기). append = 받은편지함에 바로 써 넣기(발송이 막혔거나,
    # 자기에게 보낸 메일을 메일 규칙이 딴 폴더로 옮기는 서버에서)
    "send_mode": "smtp",
    # 게이트웨이와 같은 폴더를 본다. 자기에게 보낸 메일이 딴 폴더로 가는 서버면 그 폴더도 넣는다(dispatch.folders)
    "folders": ["INBOX"],
    "tags": ["#c", "c"], "write_tags": ["#cw", "cw"],
    "workdir_keys": [],                                                   # 지시에 @키 로 고를 폴더 이름(게이트웨이 PC 면 그 설정에서)
    # 이슈 칸 — 키 앞부분(예: "PROJ-"). 키트 설정이면 dispatch.issue_prefix 를 여기로 옮겨 쓴다
    "jira_prefix": "",
    # 이슈 처리 명령 — 보내는 제목은 '#cw <명령> PROJ-123'. 비면 '/jira'(이 PC 에서 직접 실행이 알아보는 명령).
    # 키트 게이트웨이로 보낼 땐 dispatch.issue_command(기본 '/issue') 와 같아야 게이트웨이가 이슈 명령으로 돌린다
    "issue_command": "",
    "run_jira_url": "",                                                     # 직접 실행 Jira 처리 — 회사 값 jira_url 이 있으면 그것(각자 토큰만 넣게)
    # Jira 새 티켓 감시(jira_watch.py) 제외 규칙 — 회사마다 다르니 코드 기본값은 비우고 company.json 에 둔다
    "jira_watch_exclude_account": "", "jira_watch_exclude_linked": "",
    "lookback_days": 14,
    "poll_sec": 20,
}
DEFAULTS.update({k: COMPANY[k] for k in ("imap_host", "imap_port", "imap_mode", "smtp_host", "smtp_port", "smtp_mode", "jira_prefix",
                                         "jira_watch_exclude_account", "jira_watch_exclude_linked")
                 if COMPANY.get(k) not in (None, "")})
if COMPANY.get("jira_url"):
    DEFAULTS["run_jira_url"] = str(COMPANY["jira_url"]).rstrip("/")

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
        with open(path, encoding="utf-8-sig") as f:              # 메모장·PowerShell 이 붙인 BOM 도 읽는다
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ----------------------------------------------------------------- 비밀번호 보관
# 윈도우는 DPAPI(그 PC 사용자만 풀 수 있다, mail-gateway.py 와 같은 코드), 맥은 키체인(설정 파일엔 표식만 남는다).

KEYCHAIN_MARK = "keychain"
KEYCHAIN_SERVICE = "DispatchChat"


def protect_secret(text, account="mail"):
    """account — 키체인 항목 이름(메일 비밀번호 'mail', Jira 토큰 'jira'). 표식은 'keychain' / 'keychain:jira'."""
    if IS_WIN:
        return dpapi_protect(text)
    if IS_MAC:
        r = subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account, "-w", text],
                           capture_output=True, text=True)
        if r.returncode:
            raise OSError("키체인에 넣지 못했습니다 — %s" % (r.stderr or r.stdout).strip())
        return KEYCHAIN_MARK if account == "mail" else "%s:%s" % (KEYCHAIN_MARK, account)
    raise OSError("비밀번호를 안전하게 둘 곳이 없습니다(윈도우·맥만 됩니다)")


def unprotect_secret(enc):
    if enc == KEYCHAIN_MARK or enc.startswith(KEYCHAIN_MARK + ":"):
        account = enc.partition(":")[2] or "mail"
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                           capture_output=True, text=True)
        if r.returncode:
            raise OSError("키체인에서 비밀번호를 찾지 못했습니다 — 계정을 다시 넣어 주세요.")
        return r.stdout.rstrip("\n")
    if not IS_WIN:
        raise OSError("윈도우에서 만든 설정입니다 — 이 PC 에서 계정을 다시 넣어 주세요.")
    return dpapi_unprotect(enc)


if IS_WIN:
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

def expand(path):
    """%USERPROFILE% · ~ 를 푼다(kit.expand 와 같다 — 맥은 %이름% 도 풀고 \\ 를 / 로). 빈 값은 ""."""
    if not path:
        return ""
    path = str(path)
    if os.name != "nt":
        path = path.replace("%USERPROFILE%", "~").replace("%HOMEPATH%", "~")
        path = re.sub(r"%(\w+)%", lambda m: os.environ.get(m.group(1), m.group(0)), path).replace("\\", "/")
    return os.path.normpath(os.path.expanduser(os.path.expandvars(path)))


def read_kit_full():
    """키트 공통 설정(config.local.json) 전체. 키트 저장소 밖이거나 없으면 None."""
    full = read_json(KIT_CFG) if KIT_CFG else None
    return full if isinstance(full, dict) else None


def kit_dispatch(full=None):
    full = full if full is not None else (read_kit_full() or {})
    d = full.get("dispatch")
    return d if isinstance(d, dict) else {}


def kit_gateway_on():
    """이 PC 에서 키트 메일 게이트웨이가 켜져 있는가(키트 저장소 안 + dispatch.enabled). 허브가 그때만 게이트웨이를 띄운다."""
    return bool(KIT_HERE and kit_dispatch().get("enabled"))


def read_kit_cfg():
    """키트 공통 설정(config.local.json)에서 이 앱이 쓰는 값만 — mail 갈래(계정·서버)와 dispatch 갈래(폴더·태그·작업 폴더·이슈).
    메일 주소가 없으면 None. 게이트웨이(mail-gateway.py load_cfg)와 같은 기본값으로 읽는다."""
    full = read_kit_full()
    if not full:
        return None
    mail = full.get("mail") if isinstance(full.get("mail"), dict) else {}
    d = kit_dispatch(full)
    if not mail.get("user"):
        return None
    out = {}
    for k in ("user", "login_user", "password_enc", "imap_host", "imap_port", "imap_mode",
              "smtp_host", "smtp_port", "smtp_mode", "ca_bundle"):
        if mail.get(k) not in (None, ""):
            out[k] = mail[k]
    for k in ("folders", "tags", "write_tags", "lookback_days", "poll_sec"):
        if d.get(k) not in (None, ""):
            out[k] = d[k]
    # 이슈 — 키트는 범용 이름(dispatch.issue_prefix · issue_command)이고, 이 앱의 이슈 칸은 jira_prefix 로 읽는다
    out["jira_prefix"] = str(d.get("issue_prefix") or "").strip()
    out["issue_command"] = str(d.get("issue_command") or "").strip() or KIT_ISSUE_COMMAND
    # 기본 폴더(default_workdir)와 같은 곳·이미 나온 곳을 가리키는 키는 칩에서 뺀다 — 기본 폴더 칩에 그 이름을 붙인다
    home_raw = d.get("default_workdir") or KIT_DEFAULT_WORKDIR
    norm = lambda p: os.path.normcase(expand(p)).rstrip("\\/")
    home, seen, keys = norm(home_raw), set(), []
    wk = dict(d.get("workdir_keys") if isinstance(d.get("workdir_keys"), dict) else {})
    wk.setdefault("hub", os.path.join(REPO_ROOT, "tools", "macro-hub"))   # 게이트웨이 load_cfg 와 같게 — 허브 폴더 '@hub' 는 기본으로
    for k, p in wk.items():
        if not p:
            continue
        if norm(p) == home:
            out.setdefault("default_label", str(k))
        elif norm(p) not in seen:
            seen.add(norm(p))
            keys.append(str(k))
    out["workdir_keys"] = keys
    out["default_path"] = expand(home_raw)
    # 게이트웨이가 회신을 INBOX 에 써 넣는 곳(reply_mode=append)이면 지시도 같은 방법으로 넣는다
    mode = d.get("chat_send_mode") or d.get("reply_mode")
    if mode in ("smtp", "append"):
        out["send_mode"] = mode
    return out


def load_cfg():
    """(설정, 출처). 이 PC 의 앱 설정에 계정이 있으면 그것(출처 'own'), 아니면 이 키트 저장소 안에서 돌 때 키트 공통 설정
    (출처 'kit' — 이 PC 가 게이트웨이 PC 다), 둘 다 없으면 기본값('own'). 앱 설정의 다른 값(스위치·폴더)은 늘 위에 얹는다."""
    cfg = dict(DEFAULTS)
    own = read_json(OWN_CFG) or {}
    kc = read_kit_cfg() if not own.get("user") else None
    src = "own"
    if kc:
        src = "kit"
        cfg.update(kc)
    cfg.update({k: v for k, v in own.items() if v not in (None, "")})
    return cfg, src


def folders_info():
    """⚙ 작업 폴더 칸 — 키트 설정을 따르는 메신저(게이트웨이 PC)면 dispatch 의 기본 폴더·키=폴더(고칠 수 있음).
    아니면 직접 실행 칸을 쓴다."""
    _cfg, src = load_cfg()
    if src != "kit" or not KIT_CFG:
        return {"mode": "own"}
    d = kit_dispatch()
    keys = d.get("workdir_keys") if isinstance(d.get("workdir_keys"), dict) else {}
    return {"mode": "gateway", "workdir": expand(d.get("default_workdir") or KIT_DEFAULT_WORKDIR), "file": KIT_CFG,
            "dirs": "\n".join("%s=%s" % kv for kv in keys.items()),
            "company": d.get("company_workdirs")}


def has_vars(path):
    return "%" in path or path.startswith("~")


def parse_kit_dirs(text):
    """'키=폴더' 줄들 → {키: 폴더}. chat_runner.parse_dirs 와 같은 규칙이지만 키트 설정답게 %USERPROFILE%·~ 를 풀어서
    있는지 보고, 저장은 적힌 그대로 한다(키트 게이트웨이가 kit.expand 로 푼다)."""
    out = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        k, sep, v = line.partition("=")
        k, v = k.strip().lstrip("@"), v.strip()
        if not sep or not re.fullmatch(r"\w{1,32}", k) or not v:
            raise ValueError("작업 폴더 목록은 한 줄에 '키=폴더' 로 적어 주세요: %s" % line)
        if not os.path.isdir(expand(v)):
            raise ValueError("작업 폴더가 없습니다: %s" % v)
        out[k] = v if has_vars(v) else os.path.abspath(v)
    return out


def save_gateway_folders(data):
    """키트 설정(config.local.json)의 dispatch.default_workdir · workdir_keys 를 고친다(다른 키는 그대로) —
    게이트웨이는 폴링마다 설정을 다시 읽어 바로 따른다.
    회사 모드(company_workdirs)를 따로 안 정했으면 기본 폴더를 따라가므로, 기본 폴더를 바꿀 때 옛 기본 폴더를 회사 폴더로 박아 둔다
    (폰으로 회사 소스가 나가지 않게 막던 폴더가 조용히 바뀌지 않게)."""
    if load_cfg()[1] != "kit" or not KIT_CFG:
        raise ValueError("키트 설정을 따르는 메신저가 아닙니다 — 아래 '이 PC 에서 직접 실행' 칸에서 폴더를 정하세요.")
    wd = str(data.get("workdir") or "").strip()
    if not wd or not os.path.isdir(expand(wd)):
        raise ValueError("기본 폴더가 없습니다: %s" % (wd or "(비어 있음)"))
    dirs = parse_kit_dirs(data.get("dirs"))
    with open(KIT_CFG, "rb") as f:
        raw = f.read()
    full = json.loads(raw.decode("utf-8-sig"))
    before = json.loads(json.dumps(full))
    d = dict(kit_dispatch(full))
    # %USERPROFILE%·~ 로 적었으면 그대로 둔다(키트 설정은 PC 를 옮겨도 통하게 — 게이트웨이가 kit.expand 로 푼다)
    old, new = d.get("default_workdir") or KIT_DEFAULT_WORKDIR, (wd if has_vars(wd) else os.path.abspath(wd))
    same = lambda a, b: os.path.normcase(expand(a)) == os.path.normcase(expand(b))
    note = ""
    if not same(old, new) and d.get("company_workdirs") is None:
        d["company_workdirs"] = [old]
        note = "회사 모드 폴더는 옛 기본 폴더(%s) 그대로 둡니다." % old
    d["default_workdir"], d["workdir_keys"] = new, dirs
    full["dispatch"] = d
    txt = json.dumps(full, ensure_ascii=False, indent=2)                 # kit.save_config 와 같은 모양
    tmp = KIT_CFG + ".tmp"
    with open(tmp, "wb") as f:
        f.write((b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b"") + txt.encode("utf-8"))
    os.replace(tmp, KIT_CFG)
    kit_audit(before, full)
    log("[폴더] 게이트웨이 작업 폴더를 바꿨습니다 — 기본 %s · 키 %s%s" % (new, ", ".join(dirs) or "없음", " · " + note if note else ""))
    return dict(folders_info(), note=note)


def kit_audit(before, after):
    """키트 설정을 고쳤으면 허브 「변경 이력」에 남긴다(kit.save_config 처럼 바뀐 키 이름만). 진짜 키트 설정일 때만 —
    시험이 임시 파일로 바꿔 끼운 때는 남기지 않는다."""
    if not KIT_HERE or os.path.normcase(KIT_CFG) != os.path.normcase(os.path.join(REPO_ROOT, "config.local.json")):
        return
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "tools", "macro-hub"))
        import kit
        changed = kit.config_changes(before, after)
        if changed:
            kit.audit("설정 바꿈", detail=changed, via="dispatch-chat")
    except Exception as e:
        log("변경 이력을 남기지 못했습니다 — %s" % e)


def default_folder(cfg, active):
    """(이름, 경로) — 폴더를 고르지 않은 지시가 도는 곳. 직접 실행 중이면 그 기본 작업 폴더, 게이트웨이면 default_workdir."""
    path = (cfg.get("run_workdir") if active else cfg.get("default_path")) or ""
    label = "" if active else (cfg.get("default_label") or "")
    return label or re.split(r"[\\/]", str(path).rstrip("\\/"))[-1], path


def password(cfg):
    return unprotect_secret(cfg["password_enc"]) if cfg.get("password_enc") else ""


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
    r"(?m)^\s*(--\s*$|보낸 사람:|보낸사람:|From:|-----Original Message-----|iPhone에서 보냄|내 iPhone에서 보냄|나의 iPhone에서 보냄|"
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
    clean = KEY_RE.sub("", strip_re(subject))
    tag, mode = match_tag(clean, cfg)
    if not tag:
        return None
    try:
        ts = email.utils.parsedate_to_datetime(msg.get("Date")).timestamp()
    except Exception:
        ts = time.time()
    refs = re.findall(r"<[^<>]+>", " ".join(str(msg.get(h) or "") for h in ("In-Reply-To", "References")))
    body = BODY_KEY_RE.sub("", plain_body(msg))
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


def build_threads(msgs, jobs=None, by_mid=None):
    """메시지들을 대화방으로 묶는다. 번호가 아직 없는 첫 지시는 그 지시에 답한 봇 메일(In-Reply-To)로 번호를 찾는다.
    게이트웨이 PC 에선 접수된 작업도 본다 — jobs: 번호 → {id, status}, by_mid: 지시 메일 Message-ID → {id, status, thread}.
    게이트웨이는 번호를 회신할 때 붙이므로 첫 지시는 일하는 내내 번호가 없다 — 그래도 작업 id 로 '작업 중'·진행 카드가 붙는다."""
    # 접수 신호(X-Dispatch-Kind: ack — PC 가 지시를 받았다는 표시)는 말풍선이 아니다. 가리키는 내 말을 '대기' 로만 바꾼다
    # 진행 메일(progress — 몇 분 넘게 걸리는 일의 중간 한 줄)도 답이 아니다(완료·번호·안 읽음에 안 셈). 가리키는 내 말을 '작업 중' 으로 두고
    # 그 한 줄만 대화에 붙인다(t["progress"]) — 최종 답이 오면 마지막 말이 봇 답이 되어 사라진다
    signal = ("ack", "progress")
    acked = {r for m in msgs if m.get("bot") and m.get("kind") in signal for r in m.get("refs") or []}
    progress = {}
    for m in sorted((m for m in msgs if m.get("bot") and m.get("kind") == "progress"), key=lambda x: x["ts"]):
        for r in m.get("refs") or []:
            progress[r] = m
    msgs = [m for m in msgs if not (m.get("bot") and m.get("kind") in signal)]
    by_id = {m["id"]: m for m in msgs if m["id"]}
    jobs, by_mid = jobs or {}, by_mid or {}
    for m in msgs:
        j = by_mid.get(m["id"])
        if j and j.get("thread") and not m["thread"]:
            m["thread"] = j["thread"]
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
        title = re.sub(r"^@\w+\s+", "", title)          # 제목에선 작업 폴더 표시(@hub)를 뺀다
        t["title"] = re.sub(r"^\[Jira 자동화\]\s*", "Jira · ", title)[:80] or "(제목 없음)"
        last = t["msgs"][-1]
        pm = None if last["bot"] or not last["id"] else progress.get(last["id"])
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
            st = "running" if pm else "queued" if last["id"] and last["id"] in acked else "sent"
        job = jobs.get(t["no"]) if t["no"] else None
        if not job:                              # 번호가 아직 없는 첫 지시 — 그 메일로 접수된 작업
            job = next((by_mid[m["id"]] for m in t["msgs"] if not m["bot"] and m["id"] in by_mid), None)
        if isinstance(job, str):                 # 옛 호출 방식(번호 → 상태 문자열)도 받는다
            job = {"status": job}
        if job and job.get("status") in ("queued", "running"):
            st = job["status"]
        t["job"] = (job or {}).get("id") or ""
        t["status"] = st
        t["progress"] = (pm.get("text") or "").split("\n", 1)[0][:160] if pm and st in ("sent", "queued", "running") else ""
        t["ts"] = last["ts"]
        t["ask"] = last.get("ask") if last["bot"] else None
        t["last"] = (last["text"] or "").split("\n", 1)[0][:90]
        t["last_bot"] = last["bot"]
        t["reply_to"] = next((m["id"] for m in reversed(t["msgs"]) if m["bot"] and m["id"]), "")
        out.append(t)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def jobs_dir():
    """진행 상황을 읽을 작업 폴더 — '이 PC 에서 직접 실행' 이 켜져 있으면 그 작업 폴더, 키트 저장소 안이면 키트 inbox/jobs, 아니면 "".
    (직접 실행은 키트 게이트웨이가 켜진 PC 에선 막혀 있다 — 둘 다인 때는 게이트웨이를 끈 키트 저장소에서 직접 실행할 때뿐)"""
    if RUNNER.on():
        return RUNNER.jobs_dir
    return JOBS_DIR if JOBS_DIR and os.path.isdir(JOBS_DIR) else ""


def local_jobs():
    """이 PC 에서 돌면 작업 인박스(최근 80개)를 읽어 (번호 → 작업, 지시 메일 Message-ID → 작업)을 돌려준다.
    작업은 {id, status, thread} 만. 다른 PC 에선 둘 다 빈 것."""
    by_no, by_mid = {}, {}
    jd = jobs_dir()
    try:
        names = sorted(os.listdir(jd), reverse=True)[:80] if jd else []
    except OSError:
        return by_no, by_mid
    for fn in names:
        j = read_json(os.path.join(jd, fn)) if fn.endswith(".json") else None
        if not j or not j.get("id"):
            continue
        brief = {"id": j["id"], "status": j.get("status"), "thread": j.get("thread")}
        if j.get("thread"):
            by_no.setdefault(j["thread"], brief)
        if j.get("mail_msgid"):
            by_mid.setdefault(j["mail_msgid"], brief)
    return by_no, by_mid


def tool_line(name, inp):
    """도구 호출 한 줄 요약 — Bash 는 설명(없으면 명령), 파일 도구는 경로, 할 일 목록은 지금 하는 항목."""
    inp = inp if isinstance(inp, dict) else {}
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        now = next((t for t in todos if isinstance(t, dict) and t.get("status") == "in_progress"), None)
        done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
        return "할 일 %d/%d%s" % (done, len(todos), (" — " + str(now.get("activeForm") or now.get("content") or "")) if now else "")
    for k in ("description", "command", "file_path", "notebook_path", "pattern", "url", "query", "skill", "prompt", "path"):
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return re.sub(r"\s+", " ", v.strip())[:160]
    return ""


DETAIL_MAX = 2000                                     # 자세히 보기 한 칸의 글자 수 — 2초마다 다시 받으니 너무 크게 두지 않는다


def _clip(text, n=DETAIL_MAX):
    text = str(text or "")
    return text if len(text) <= n else text[:n] + "\n… (%d자 더)" % (len(text) - n)


def tool_detail(name, inp):
    """도구에 넘긴 전체 입력 — 고친 내용은 -/+ 줄로, 나머지는 값 그대로(긴 건 자른다)."""
    inp = inp if isinstance(inp, dict) else {}
    if name in ("Edit", "MultiEdit") and ("old_string" in inp or "new_string" in inp):
        old, new = str(inp.get("old_string") or ""), str(inp.get("new_string") or "")
        return _clip("%s\n%s\n%s" % (inp.get("file_path") or "", "\n".join("- " + l for l in old.splitlines()),
                                      "\n".join("+ " + l for l in new.splitlines())))
    if name == "Write":
        return _clip("%s\n%s" % (inp.get("file_path") or "", inp.get("content") or ""))
    if name == "TodoWrite":
        marks = {"completed": "✓", "in_progress": "▶", "pending": "·"}
        return _clip("\n".join("%s %s" % (marks.get(t.get("status"), "·"), t.get("content") or "")
                               for t in inp.get("todos") or [] if isinstance(t, dict)))
    if len(inp) == 1 and isinstance(next(iter(inp.values())), str):
        return _clip(next(iter(inp.values())))
    return _clip("\n".join("%s: %s" % (k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in inp.items()))


def result_text(content):
    """tool_result 의 내용 — 문자열이거나 {type:text} 조각 목록."""
    if isinstance(content, list):
        content = "\n".join(str(x.get("text") or "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return _clip(content)


def _ts(iso):
    """세션 기록의 시각(UTC, ...Z) → epoch 초."""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_progress(lines, since=0.0):
    """Claude 세션 기록(.jsonl) 줄들 → 화면에 띄울 단계 목록.
    since 보다 앞선 줄(이어받은 세션의 지난 대화)과 하위 에이전트 안쪽 말은 뺀다(본 흐름만)."""
    steps, by_id = [], {}
    for ln in lines:
        try:
            ev = json.loads(ln)
        except ValueError:
            continue                                  # 아직 다 안 쓰인 마지막 줄
        if not isinstance(ev, dict) or ev.get("isSidechain") or ev.get("parent_tool_use_id"):
            continue
        typ = ev.get("type")
        if typ not in ("assistant", "user") or (since and _ts(ev.get("timestamp")) < since):
            continue
        content = (ev.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if typ == "assistant" and c.get("type") == "text" and (c.get("text") or "").strip():
                full = c["text"].strip()
                steps.append({"kind": "text", "text": full[:400], "detail": _clip(full) if len(full) > 400 else ""})
            elif typ == "assistant" and c.get("type") == "tool_use":
                by_id[c.get("id")] = len(steps)
                steps.append({"kind": "tool", "name": c.get("name") or "?", "text": tool_line(c.get("name"), c.get("input")),
                              "state": "run", "detail": tool_detail(c.get("name"), c.get("input")), "result": ""})
            elif typ == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                st = steps[by_id[c["tool_use_id"]]]
                st["state"] = "err" if c.get("is_error") else "ok"
                st["result"] = result_text(c.get("content"))
    return steps


def _first_prompt(lines, since):
    """그 세션에서 since 이후 처음 들어온 사람 말(워커가 넘긴 지시문)."""
    for ln in lines:
        if '"type":"user"' not in ln.replace(" ", ""):
            continue
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if ev.get("type") == "user" and not ev.get("isSidechain") and _ts(ev.get("timestamp")) >= since:
            c = (ev.get("message") or {}).get("content")
            if isinstance(c, list):
                c = "".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            if isinstance(c, str) and c.strip():
                return c
    return ""


_TRANSCRIPT = {}                                      # 작업 id → 찾아 둔 세션 기록 파일


def _read_lines(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "replace").splitlines()


def find_transcript(job, since):
    """워커가 돌리는 작업의 세션 기록. 작업 폴더의 기록 중 시작 뒤에 바뀐 것에서, 첫 사람 말이 그 지시문인 것을 고른다."""
    if job["id"] in _TRANSCRIPT:
        return _TRANSCRIPT[job["id"]]
    d = os.path.join(CLAUDE_PROJECTS, re.sub(r"[^A-Za-z0-9]", "-", str(job.get("workdir") or "")))
    want = re.sub(r"\s+", " ", str(job.get("prompt") or "")).strip()[:60]
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]
    except OSError:
        return ""
    files = sorted((f for f in files if os.path.getmtime(f) >= since), key=os.path.getmtime, reverse=True)[:12]
    if job.get("resume_id"):                          # 이어받은 세션이면 그 파일부터 본다
        files.sort(key=lambda f: os.path.basename(f) != "%s.jsonl" % job["resume_id"])
    for f in files:
        try:
            got = re.sub(r"\s+", " ", _first_prompt(_read_lines(f), since)).strip()
        except OSError:
            continue
        if want and got.startswith(want):
            _TRANSCRIPT[job["id"]] = f
            return f
    return ""


def job_progress(job_id):
    """작업 하나의 진행 상황(이 PC 에 게이트웨이 인박스가 있거나 이 PC 에서 직접 실행할 때만). 작업 파일 이름이 곧 id 다."""
    jd = jobs_dir()
    if not jd or not re.fullmatch(r"[\w\-]{1,80}", str(job_id or "")):
        return None
    job = read_json(os.path.join(jd, "%s.json" % job_id))
    if not job or not job.get("id"):
        return None
    try:
        since = datetime.strptime(job.get("started_at") or "", "%Y-%m-%d %H:%M:%S").timestamp() - 5
    except ValueError:
        return None
    path, steps, mtime = find_transcript(job, since), [], 0
    if path:
        try:
            steps, mtime = parse_progress(_read_lines(path), since), os.path.getmtime(path)
        except OSError:
            pass
    return {"id": job["id"], "status": job.get("status"), "started_at": job.get("started_at") or "",
            "count": len(steps), "steps": steps[-40:], "updated": mtime, "now": time.time()}


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
        hidden, urgent, cleared = load_hidden(), load_urgent(), load_cleared()
        out = []
        for t in build_threads(msgs, *local_jobs()):
            if t["key"] in hidden:
                continue
            if cleared and (t.get("ts") or 0) <= cleared and not kept_on_clear(t, cleared):
                continue
            t["urgent"] = t["key"] in urgent
            out.append(t)
        return out


def load_hidden():
    try:
        with open(HIDDEN_PATH, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def hide_thread(key):
    """대화 지우기 — 메일은 지우지 않고 이 PC 화면 목록에서만 뺀다(되살리려면 hidden.json 에서 그 줄을 지운다)."""
    key = str(key or "").strip()
    if not key:
        raise ValueError("지울 대화가 없습니다")
    keys = load_hidden()
    keys.add(key)
    os.makedirs(LOCALDATA, exist_ok=True)
    with open(HIDDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, ensure_ascii=False, indent=1)
    return {"ok": True, "hidden": len(keys)}


ACTIVE_STATUSES = ("sent", "queued", "running", "confirm")   # 전체 지우기에서 남기는 대화 — 일하는 중이거나 내 확인을 기다린다
WORKING_STATUSES = ("queued", "running")                     # 이건 언제나 남긴다
STALE_SEC = 6 * 3600   # 보냄·확인 기다림도 지우기 6시간 전보다 오래됐으면 같이 지운다 — 시험하다 남은 옛 대화가 안 지워져 '지우기가 안 된다'(2026-10-22 사용자)


def kept_on_clear(t, cleared):
    status = t.get("status")
    if status in WORKING_STATUSES:
        return True
    return status in ACTIVE_STATUSES and (t.get("ts") or 0) > cleared - STALE_SEC


def load_cleared():
    try:
        with open(CLEARED_PATH, encoding="utf-8") as f:
            return float((json.load(f) or {}).get("before") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0


def clear_threads(undo=False):
    """대화 전체 지우기 — 지금 시각 이전에 마지막 글이 있는 대화를 이 PC 목록에서 뺀다(메일은 그대로).
    일하는 중·확인 기다리는 대화는 남기고, 지운 대화에 새 글이 오면 다시 보인다. undo 면 지우기 전으로 되돌린다."""
    os.makedirs(LOCALDATA, exist_ok=True)
    if undo:
        prev = None
        try:
            with open(CLEARED_PATH, encoding="utf-8") as f:
                prev = (json.load(f) or {}).get("prev")
        except (OSError, ValueError, AttributeError):
            pass
        state = {"before": float(prev or 0)}
    else:
        n = len(BOX.threads())
        state = {"before": time.time(), "prev": load_cleared() or None}
    with open(CLEARED_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)
    log("대화 전체 지우기%s" % (" — 되돌림" if undo else " (%d개, 메일은 그대로)" % n))
    return {"ok": True, "left": len(BOX.threads())}


# 급건 표시와 저장해 두는 답 — 대화 지우기처럼 이 PC 에만 남긴다(메일·다른 PC 와 나누지 않는다)
def _read_local(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_local(path, data):
    os.makedirs(LOCALDATA, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_urgent():
    got = _read_local(URGENT_PATH, [])
    return set(got) if isinstance(got, list) else set()


def set_urgent(key, on):
    """🔥 급건 표시 — 목록 맨 위에 고정하고 눈에 띄게 보인다."""
    key = str(key or "").strip()
    if not key:
        raise ValueError("대화가 없습니다")
    keys = load_urgent()
    (keys.add if on else keys.discard)(key)
    _write_local(URGENT_PATH, sorted(keys))
    BOX.version += 1
    return {"ok": True, "urgent": bool(on)}


DEFAULT_SNIPPETS = ["진행 상황을 짧게 알려 줘", "여기까지 한 것을 정리해서 보고해 줘",
                    "추천한 것으로 진행해 줘", "고친 다음 테스트까지 돌려서 결과 알려 줘"]
SNIPPET_MAX = 40


def load_snippets():
    got = _read_local(SNIPPETS_PATH, None)
    return [str(x) for x in got if str(x).strip()] if isinstance(got, list) else list(DEFAULT_SNIPPETS)


def edit_snippets(data):
    """📝 저장해 두는 답 — {"add": 글} 이면 맨 앞에 넣고(같은 글은 하나만), {"remove": 글} 이면 뺀다."""
    items = load_snippets()
    add = str(data.get("add") or "").strip()
    rem = str(data.get("remove") or "").strip()
    if add:
        if len(add) > 2000:
            raise ValueError("저장할 글이 너무 깁니다(2000자까지)")
        items = [add] + [x for x in items if x != add]
    if rem:
        items = [x for x in items if x != rem]
    items = items[:SNIPPET_MAX]
    _write_local(SNIPPETS_PATH, items)
    return {"ok": True, "snippets": items}


BOX = Box()
RUNNER = chat_runner.Runner(sys.modules[__name__])          # 이 PC 에서 직접 실행(기본 꺼짐) — main() 에서 돌리기 시작한다


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
        elif data.get("retry"):                     # 🔁 실패한 지시를 그대로 다시 — 받는 쪽(게이트웨이·직접 실행)이 RETRY_WORDS 로 알아본다
            body = "다시 실행"
        else:
            body = (",".join(str(p) for p in sorted(set(picks))) + (" " if picks and text else "") + text).strip()
        if not body:
            raise ValueError("보낼 말이 없습니다")
        subject = "Re: %s [T%d] %s" % (t["tag"] or tag_read, t["no"], t["title"])[:160]
        shown = "멈춤" if data.get("stop") else "🔁 다시 실행" if data.get("retry") else ((("☑ " + " ☑ ".join(str(p) for p in sorted(set(picks)))) if picks else "") +
                                                 ("\n" if picks and text else "") + text)
        return subject, body, t.get("reply_to") or "", {"thread": t["no"], "mode": t["mode"], "tag": t["tag"], "text": shown}
    jira = (data.get("jira") or "").strip()
    if jira:                                        # 이슈(Jira) 처리 시작 — 명령은 issue_command(키트 게이트웨이면 dispatch.issue_command)
        prefix = (cfg.get("jira_prefix") or "").strip()
        k = jira.upper() if re.match(r"^[A-Za-z]", jira) else prefix + jira
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", k):
            raise ValueError("이슈 키 형식이 아닙니다 (예: %s123)" % (prefix or "PROJ-"))
        command = (cfg.get("issue_command") or "").strip() or "/jira"
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


def instruction_word(cfg, src):
    """지시·답 메일 본문 끝에 붙일 암호 단어. 이 앱 설정의 key_word(회사 밖 메일), 없으면 — 키트 설정을 따르는
    대화 앱(게이트웨이 PC)이고 게이트웨이가 모든 지시에 단어를 요구하면(dispatch.require_word_all) — dispatch.company_word,
    그다음 dispatch.keyed_senders 의 내 주소 단어. 요구하지 않으면 붙이지 않는다(단어가 지시문에 섞여 기록에 남지 않게)."""
    key = str(cfg.get("key_word") or "").strip()
    if key or src != "kit" or not KIT_CFG:
        return key
    d = kit_dispatch()
    if not d.get("require_word_all"):
        return ""
    me = str(cfg.get("user") or "").strip().lower()
    ks = {str(a).strip().lower(): str(w).strip() for a, w in (d.get("keyed_senders") or {}).items()}
    return str(d.get("company_word") or "").strip() or ks.get(me, "")


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
    key = instruction_word(cfg, _)
    if key:                                        # 게이트웨이는 본문 마지막 줄 [k:단어] 가 맞아야 받는다(화면에서는 뗀다)
        body = (body or "").rstrip() + "\n\n[k:%s]" % key
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
    threading.Timer(4, RUNNER.wake.set).start()    # 이 PC 에서 직접 실행 중이면 곧 받아 간다
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
        # 클릭재킹 막기 — 다른 웹 페이지가 대화 화면을 투명 iframe 으로 덮어 보내기를 누르게 하지 못하게
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
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
        if u.path.startswith("/pet/") and u.path[5:] in PET_FILES:                 # 펫 코드(허브 web\ 과 같은 파일)
            p = os.path.join(PET_WEB, u.path[5:])
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    return self._send(200, f.read(), PET_FILES[u.path[5:]])
            return self._send(404, {"error": "no pet"})
        m = re.fullmatch(r"/skin/plush/([\w\-]+\.(webp|png|json))", u.path)     # 펫 그림(인형 스킨만)
        if m:
            p = os.path.join(PET_WEB, PET_SKIN, "plush", m.group(1))
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    return self._send(200, f.read(), PET_TYPES[m.group(2)])
            return self._send(404, {"error": "no pet"})
        if u.path == "/api/pet":                                                    # 고른 품종·소품 — 허브가 없으면 기본(첫 번째 품종·계절 소품)
            try:
                import urllib.request
                with urllib.request.urlopen(HUB_SKIN, timeout=0.6) as r:
                    j = json.loads(r.read().decode("utf-8"))
                return self._send(200, {"breed": (j.get("breed") or {}) if j.get("skin") == "plush" else {}, "petx": j.get("petx")})
            except Exception:
                return self._send(200, {"breed": {}})
        if u.path == "/api/state":
            cfg, src = load_cfg()
            run = RUNNER.summary()
            return self._send(200, {
                "user": cfg.get("user"), "source": src, "error": BOX.error, "polled": BOX.polled, "version": BOX.version,
                "local": bool(jobs_dir()), "runner": run, "jira_watch": RUNNER.jira.summary(),
                "folders": list((cfg.get("run_dirs") or {}).keys()) if run["active"] else (cfg.get("workdir_keys") or []),
                "default_folder": dict(zip(("label", "path"), default_folder(cfg, run["active"]))),
                "jira_prefix": cfg.get("jira_prefix") or "",
                "issue_command": (cfg.get("issue_command") or "").strip() or "/jira",
                "support_email": str(COMPANY.get("support_email") or "").strip(),    # 실패 카드의 ✉ 문의 — 없으면 기록 복사만
                "threads": [{k: t[k] for k in ("key", "no", "title", "mode", "status", "ts", "last", "last_bot", "progress", "urgent")} for t in BOX.threads()],
            })
        if u.path == "/api/thread":
            key = (parse_qs(u.query).get("key") or [""])[0]
            t = next((x for x in BOX.threads() if x["key"] == key), None)
            if not t:
                return self._send(404, {"error": "없는 대화"})
            return self._send(200, t)
        if u.path == "/api/progress":                                               # 일하는 중인 대화의 실시간 진행(게이트웨이 PC 만)
            job_id = (parse_qs(u.query).get("job") or [""])[0]
            return self._send(200, {"progress": job_progress(job_id), "local": bool(jobs_dir())})
        if u.path == "/api/runner":                                                 # 이 PC 에서 직접 실행 — 스위치 상태
            return self._send(200, RUNNER.info())
        if u.path == "/api/jira-watch":                                             # Jira 새 티켓 감시 — 설정·마지막 결과
            return self._send(200, RUNNER.jira.info())
        if u.path == "/api/snippets":
            return self._send(200, {"snippets": load_snippets()})
        if u.path == "/api/folders":                                                # ⚙ 작업 폴더(게이트웨이 설정을 따를 때)
            return self._send(200, folders_info())
        if u.path == "/api/setup":
            cfg, src = load_cfg()
            return self._send(200, {k: cfg.get(k) for k in ("user", "login_user", "imap_host", "imap_port", "smtp_host", "smtp_port",
                                                           "send_mode", "jira_prefix", "issue_command")}
                              # 암호 단어는 비밀번호처럼 — 있는지만(토큰 없는 GET 이라 이 PC 의 아무 프로그램이나 읽을 수 있다)
                              | {"source": src, "has_password": bool(cfg.get("password_enc")), "has_key_word": bool(cfg.get("key_word")),
                                 "presets": COMPANY.get("presets") or []})
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
            if u.path == "/api/hide":
                return self._send(200, hide_thread(data.get("key")))
            if u.path == "/api/clear":                                              # 대화 전체 지우기 {undo}
                return self._send(200, clear_threads(bool(data.get("undo"))))
            if u.path == "/api/urgent":                                             # 🔥 급건 표시 {key, on}
                return self._send(200, set_urgent(data.get("key"), bool(data.get("on"))))
            if u.path == "/api/snippets":                                           # 📝 저장해 두는 답 {add} · {remove}
                return self._send(200, edit_snippets(data))
            if u.path == "/api/refresh":
                BOX.wake.set()
                return self._send(200, {"ok": True})
            if u.path == "/api/setup":
                return self._send(200, save_setup(data))
            if u.path == "/api/runner":
                return self._send(200, RUNNER.configure(data))
            if u.path == "/api/folders":                                            # {workdir, dirs} — 게이트웨이 설정에 저장
                return self._send(200, save_gateway_folders(data))
            if u.path == "/api/jira-watch":                                      # {enabled, away, 규칙…, check_now, dismiss}
                return self._send(200, RUNNER.jira.configure(data))
            if u.path == "/api/browser-login":                                      # 직접 실행 — 전용 브라우저에 로그인해 두기
                return self._send(200, RUNNER.browser_login())
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            log("요청 실패 %s — %s" % (u.path, traceback.format_exc(limit=3)))
            return self._send(500, {"error": "%s" % e})
        return self._send(404, {"error": "not found"})


def save_setup(data):
    """다른 PC 에서 처음 열 때 넣는 메일 계정. 연결을 먼저 확인하고, 되면 비밀번호를 감춰(윈도우 DPAPI · 맥 키체인) 저장한다."""
    own = read_json(OWN_CFG) or {}
    for k in ("user", "login_user", "imap_host", "smtp_host", "send_mode", "jira_prefix", "issue_command"):
        if k in data:
            own[k] = str(data[k]).strip()
    # 암호 단어 — 화면은 원문을 받지 않으니(has_key_word) 비워 두면 그대로, '-' 하나면 지운다
    kw = str(data.get("key_word") or "").strip()
    if kw == "-":
        own.pop("key_word", None)
    elif kw:
        own["key_word"] = kw
    for k in ("imap_port", "smtp_port"):
        if str(data.get(k) or "").isdigit():
            own[k] = int(data[k])
    if not own.get("user") or "@" not in own["user"]:
        raise ValueError("메일 주소를 넣어 주세요")
    if own.get("key_word") and not re.fullmatch(r"[^\]\s]{1,64}", own["key_word"]):
        raise ValueError("암호 단어에는 빈칸과 ] 를 쓸 수 없습니다")
    # 어느 메일이든 표준 IMAP·SMTP — 포트로 암호화 방식을 정한다(465 는 처음부터 SSL, 그 밖은 STARTTLS)
    own["smtp_mode"] = "ssl" if int(own.get("smtp_port") or 0) == 465 else "starttls"
    own["imap_mode"] = "ssl" if int(own.get("imap_port") or 993) == 993 else "starttls"
    trial = dict(DEFAULTS, **own)
    pw = data.get("password") or ""
    if pw:
        imap_connect(trial, pw).logout()             # 틀리면 여기서 예외 — 저장하지 않는다
        own["password_enc"] = protect_secret(pw)
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
    if IS_WIN:
        cands = [os.path.join(b, "Microsoft", "Edge", "Application", "msedge.exe")
                 for b in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")) if b]
    elif IS_MAC:                                         # 맥은 Edge 가 없으면 크롬으로 같은 앱 창을 연다
        cands = [os.path.join(r, "%s.app" % n, "Contents", "MacOS", n) for n in ("Microsoft Edge", "Google Chrome")
                 for r in ("/Applications", os.path.expanduser("~/Applications"))]
    else:
        cands = []
    exe = next((c for c in cands if os.path.isfile(c)), None)
    if exe:
        # 따로 둔 프로필이라 평소 브라우저 창과 섞이지 않고, 창 크기도 따로 기억한다
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
    RUNNER.start()                                   # 꺼져 있으면 아무것도 하지 않는다(설정만 가끔 본다)
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
