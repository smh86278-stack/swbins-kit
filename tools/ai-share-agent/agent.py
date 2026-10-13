#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 공유 위키 — 내 작업 흔적(이슈 출처 + git 커밋 + 선택 기능)을 모아 주간 업무 보고 초안과 업무 공유 발표 준비 자료를 만든다.

  weekly    : 이번 주(월요일~오늘)를 모아 주간 보고 초안을 쓰게 하고(claude CLI 또는 ollama)
              <wiki_dir>\\reports\\YYYYMMDD_주간보고.md 로 저장한 뒤 메일로 보낸다(--no-mail 이면 파일만).
              LLM 이 실패해도 모은 원자료(이슈·커밋 목록)를 대신 보낸다. 허브의 job_weekly_report 가 정한 요일·시각에 부른다.
  collect   : 기간 안의 이슈·커밋·(선택) MR·하네스 기록을 이슈 키로 묶어 wiki\\tickets\\<part>\\<키>.md + INDEX.md 로 쌓는다(LLM 없음).
  present   : wiki 로 업무 공유 발표 준비 자료를 만든다(claude -p — 사용량 큼, --engine ollama 는 맛보기).
  run       : collect 후 present.
  serve     : 이 PC 에서만 열리는 웹 화면(127.0.0.1) — 위키 보기·발표 선택·수집·주간 보고 초안.
  set-token : 이슈 출처 토큰을 DPAPI 로 암호화해 config.local.json 에 넣는다(--gitlab = MR 리뷰용, --other = 다른 파트 clone 용).

사용:
  python agent.py weekly [--since YYYY-MM-DD --until YYYY-MM-DD] [--no-mail]
  python agent.py collect --since 2026-07-01
  python agent.py present [--engine ollama]
  python agent.py serve [--port 8640] [--no-browser]
  python agent.py set-token [--gitlab | --other]

설정은 config.local.json 의 ai_share 갈래(견본·설명은 config.example.json). 이슈 도구는 ai_share.tracker.type 으로
jira · github · gitlab · none 중 고른다(trackers.py). 외부 과금 없음 — LLM 단계는 로그인된 claude CLI(구독) 또는 로컬 ollama.
"""
import argparse
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

for _name in ("stdout", "stderr"):                 # pythonw 로 뜨면 콘솔이 없어 None 이다
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
    try:
        getattr(sys, _name).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR.parent / "macro-hub"))
import kit       # noqa: E402  — 설정·DPAPI·메일·상태 파일 공통 코드
import trackers  # noqa: E402  — 이슈 출처 어댑터

FEATURE_WEEKLY = "weekly_report"
WEEKLY_NAME = "주간보고"

# config.local.json 의 ai_share 갈래가 이 위에 덮인다(갈래 안 묶음은 한 단계 더 깊게 덮는다).
DEFAULT_CFG = {
    "enabled": False,
    "port": 8640,
    "workspace_root": "",          # 내 작업 폴더(하네스 레포·여러 레포의 부모 레포) — .gitmodules 가 있으면 그 서브모듈들이 레포 목록
    "repos": [],                   # 커밋을 볼 git 레포 경로 목록 — 비면 workspace_root 에서 찾는다
    "part": "main",                # 내 파트 이름 — wiki\tickets\<part>\
    "wiki_dir": "",                # 비면 tools\macro-hub\data.local\ai_share\wiki
    "report_name": "업무공유_준비",  # 발표 준비 자료 파일 이름 — reports\YYYYMMDD_<report_name>.md
    "default_days": 90,            # 기간을 안 주면 오늘부터 이만큼 전부터
    "rec_days": 14,                # ⭐ 추천 대상 = 최근 이 일수 안에 움직인 내 이슈
    "my_authors": [],              # 내 git author 이름 — 비면 토큰 주인·git user.name·이메일 아이디로 자동
    "team": [],                    # 팀원 이름(이슈 도구에 보이는 이름·아이디) — 나는 자동으로 빠진다
    "aliases": {},                 # git author → 표시 이름
    "comment_prefixes": [],        # 이 머리말로 시작하는 담당자 댓글만 — 빈 목록 = 담당자 본인 댓글 모두
    "exclude_types": [],           # 추천·발표 후보에서 뺄 이슈 유형
    "branch_ticket_re": "",        # 브랜치 이름에서 키(또는 번호)를 뽑는 정규식 — 비면 키 정규식만
    "prompt_file": "",             # 발표 준비 프롬프트를 바꿀 때 — 비면 prompt_present.md
    "history_file": "",            # 지난 발표 주제 목록(마크다운) — 비면 wiki\share_history.md 가 있으면 그것
    "transcripts_dir": "",         # Claude Code 대화 기록 폴더 — 비면 ~/.claude/projects/<레포 경로>
    "tracker": {"type": "none", "key_regex": ""},
    "gitlab": {"api_url": "", "token_enc": ""},
    "review_bot": {"name": "", "issue_heading": ""},
    "tag": {"label": "", "regex": "", "ignore": []},
    "harness": {"enabled": False, "tasks_dir": "docs/tasks", "tickets_dir": "docs/tickets",
                "patterns_dir": "docs/patterns", "decisions_file": "docs/decisions.md"},
    "other": {"part": "", "repo_url": "", "branch": "main", "team": [], "token_enc": ""},
    "weekly_report": {"enabled": False, "days": "fri", "at": "16:00", "to": [], "engine": "claude", "model": "",
                      "prompt_file": "", "subject": "[주간 보고 초안] {since} ~ {until}"},
}
NESTED = ("tracker", "gitlab", "review_bot", "tag", "harness", "other", "weekly_report")

# 설정에서 채우는 값 — configure() 가 다시 채운다(웹 화면에서 설정을 고치면 다시 부른다)
FULL, CFG, TR = {}, {}, None
ROOT = None
WIKI = REPORTS = PRIVATE = SELECT_FILE = MR_CACHE = OTHER_CLONE = None
MY_PART, OTHER, OTHER_PART, OTHER_URL = "main", {}, "", ""
HARNESS, TAG, BOT = {}, {}, {}
EXCLUDE_TYPES, COMMENT_PREFIXES, REC_DAYS, BRANCH_RE = set(), (), 14, None
FETCH = None                                                  # 테스트가 바꿔 끼우는 HTTP(fetch(url, headers) -> JSON)
MY_AUTHORS = set()                                            # 내 git author 이름
ALIASES = {}                                                  # git author → 표시 이름
TEAM = {}                                                     # 표시 이름 → {"id": 출처 아이디, "authors": git author 후보}
ME = {"id": "", "name": "", "display": ""}                    # 토큰 주인 (collect 가 채운다)


def _public(d):
    return {k: v for k, v in d.items() if not str(k).startswith("_")} if isinstance(d, dict) else {}


def load_cfg(full=None):
    """ai_share 설정 = 기본값 ← config.local.json 의 ai_share."""
    full = full if full is not None else kit.load_config()
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    for k, v in _public(full.get("ai_share")).items():
        if k in NESTED and isinstance(v, dict):
            cfg[k].update(_public(v))
        else:
            cfg[k] = v
    return cfg


def _path(v):
    v = str(v or "").strip()
    return Path(kit.expand(v)) if v else None


def configure(cfg=None, full=None, fetch=None, token=None):
    """설정을 모듈 상태로 펼친다. 테스트는 cfg·full·fetch·token 을 넘겨 네트워크·실제 설정 없이 돈다."""
    global FULL, CFG, TR, ROOT, WIKI, REPORTS, PRIVATE, SELECT_FILE, MR_CACHE, OTHER_CLONE
    global MY_PART, OTHER, OTHER_PART, OTHER_URL, HARNESS, TAG, BOT, EXCLUDE_TYPES, COMMENT_PREFIXES, REC_DAYS, BRANCH_RE, FETCH
    FULL = full if full is not None else kit.load_config()
    CFG = cfg if cfg is not None else load_cfg(FULL)
    FETCH = fetch
    TR = trackers.make(CFG["tracker"], FULL, fetch, token)
    root = _path(CFG.get("workspace_root"))
    ROOT = root if root and root.is_dir() else None
    WIKI = _path(CFG.get("wiki_dir")) or Path(kit.DATA) / "ai_share" / "wiki"
    REPORTS = WIKI / "reports"
    PRIVATE = WIKI / "_private"
    SELECT_FILE = WIKI / "select.txt"
    MR_CACHE = WIKI / "_cache" / "gitlab_mr.json"
    MY_PART = str(CFG.get("part") or "main").strip() or "main"
    OTHER = dict(CFG.get("other") or {})
    OTHER_URL = str(OTHER.get("repo_url") or "").strip()
    OTHER_PART = str(OTHER.get("part") or "").strip() if OTHER_URL else ""
    OTHER_CLONE = WIKI / "_src" / (OTHER_URL.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "other")
    HARNESS = dict(CFG.get("harness") or {})
    TAG = dict(CFG.get("tag") or {})
    BOT = dict(CFG.get("review_bot") or {})
    EXCLUDE_TYPES = set(CFG.get("exclude_types") or [])
    COMMENT_PREFIXES = tuple(str(x) for x in (CFG.get("comment_prefixes") or []) if str(x))
    REC_DAYS = int(CFG.get("rec_days") or 14)
    try:
        BRANCH_RE = re.compile(CFG["branch_ticket_re"]) if CFG.get("branch_ticket_re") else None
    except re.error as e:
        log(f"branch_ticket_re 가 잘못된 정규식이라 쓰지 않습니다: {e}")
        BRANCH_RE = None
    MY_AUTHORS.clear()
    MY_AUTHORS.update(str(a) for a in CFG.get("my_authors") or [] if str(a).strip())
    ALIASES.clear()
    ALIASES.update({str(k): str(v) for k, v in (CFG.get("aliases") or {}).items()})
    TEAM.clear()
    ME.update(id="", name="", display="")
    _ADDED_BY.clear()


def resource(name):
    return APP_DIR / name


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 민감 값 가리기
MASK_KEY_RE = re.compile(
    r"(?i)(password|passwd|\bpw\b|secret|token|api[_-]?key|private[_ ]key|authorization|"
    r"login[_-]?id|user[_-]?id|\bid\b|계정|아이디|비밀번호|패스워드|비번)"
)
# key: value 의 value 가 공백 없는 리터럴(6자 이상)일 때만 가린다 — 서술문·코드식($x, 함수 호출)은 남긴다
LITERAL_RE = re.compile(r"[\"'`]?[A-Za-z0-9_\-.+/=@]{6,}[\"'`]?[,;]?")
INLINE_SECRET_RE = re.compile(
    r"(?i)(\b(?:Bearer|Basic)\s+)[A-Za-z0-9._~+/=-]{8,}"
    r"|\b(?:glpat|ghp|gho|github_pat)[-_][A-Za-z0-9_-]{10,}"
    r"|\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_.-]+"
    r"|([?&](?:password|passwd|pw|token|access_token|api_?key|secret|client_secret)=)[^&\s\"'`]+"
    r"|(\b(?:id|pw|login[_-]?id)\s*[:=]\s*)[A-Za-z0-9_.@!#-]{6,}"
)
# 서술 속 계정 ID: "운영 계정(`xxx`)", "아이디 `xxx`" — 대문자 컬럼명·코드값과 $변수는 식별자라 남긴다
INLINE_ACCOUNT_RE = re.compile(
    r"(?i)((?:계정|아이디|비밀번호|login[_-]?id|user[_-]?id|(?-i:\bID\b))[^`\n]{0,8}`)(?-i:(?![A-Z0-9_]+`))(?!\$)[^`\s]{4,}(`)")
# 영문+숫자+특수문자가 섞인 백틱 값은 비밀번호로 본다. 어노테이션(@Slf4j)·경로·호출식은 제외
PASSWORDY_RE = re.compile(r"`(?!@)(?=[^`\s]*[A-Za-z])(?=[^`\s]*\d)(?=[^`\s]*[!#%^&*])[^`\s$/.()]{6,40}`")


def mask(text):
    """민감 값만 가린다. 원본 위치는 이슈 키·경로로 남는다. 휴리스틱이라 완전하지 않다."""
    out, in_pem = [], False
    for line in (text or "").splitlines():
        if "-----BEGIN" in line:
            in_pem = True
        if in_pem:
            in_pem = "-----END" not in line
            out.append("[masked block]")
            continue
        line = INLINE_SECRET_RE.sub(lambda m: (m.group(1) or m.group(2) or m.group(3) or "") + "[masked]", line)
        line = INLINE_ACCOUNT_RE.sub(r"\1[masked]\2", line)
        line = PASSWORDY_RE.sub("`[masked]`", line)
        m = re.match(r"^(.*?)([:=])(.*)$", line)
        if m:
            key = m.group(1).strip(" \t-*>|#`\"'")
            value = m.group(3).strip()
            if len(key) <= 40 and MASK_KEY_RE.search(key) and LITERAL_RE.fullmatch(value) \
                    and "[masked]" not in value:
                line = f"{m.group(1)}{m.group(2)} [masked]"
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- 이슈 키
FOLDER_KEY_RE = re.compile(r"^(?:[a-z]+-)+(\d{3,7})(?:-|$)")   # 키 없는 폴더 이름: myapp-1234 · proj-1234-login-fix


def keys_in(text):
    return TR.find_keys(text or "")


def branch_keys(branch):
    """브랜치 이름의 키 — 키 정규식으로 찾고, branch_ticket_re 가 있으면 그 결과(키 또는 번호)도 더한다."""
    keys = set(keys_in(branch))
    if BRANCH_RE and branch:
        for m in BRANCH_RE.finditer(branch):
            g = m.group(1) if BRANCH_RE.groups else m.group(0)
            got = keys_in(g)
            if got:
                keys |= got
            elif str(g).isdigit():
                k = TR.key_from_number(g)
                if k:
                    keys.add(k)
    return keys


def slug(key):
    """파일 이름에 쓸 수 있게 — 'owner/name#12' → 'owner~name-12'. 진짜 키는 문서 머리(ticket:)에 있다."""
    return re.sub(r"[^A-Za-z0-9._-]", lambda m: {"/": "~", "#": "-"}.get(m.group(0), "_"), key)[:150]


KEY_OK_RE = re.compile(r"[\w.\-/#~]{1,160}")


def key_ok(key):
    return bool(KEY_OK_RE.fullmatch(key or "")) and ".." not in key


# ---------------------------------------------------------------- 이슈 출처
def collect_issues(since, until):
    """출처 어댑터로 나·팀원 이슈를 받는다. 담당자 본인(나·그 이슈 담당자)의 댓글만 남긴다."""
    if TR.type == "none":
        detect_me()
        resolve_team({})
        return []
    ok, why = TR.ready()
    if not ok:
        raise RuntimeError(why)
    me = TR.whoami()
    ME.update(id=me.get("id") or "", name=me.get("name") or "", display=me.get("display") or me.get("name") or "")
    names = [str(n).strip() for n in CFG.get("team") or [] if str(n).strip()]
    resolve_team(TR.resolve_users([n for n in names if n not in (ME["name"], ME["display"])]))
    raw = TR.fetch_issues(since, until, [ME["id"]] + [t["id"] for t in TEAM.values() if t.get("id")])
    issues = []
    for it in raw:
        a = it.get("assignee") or {}
        my_comments = []
        for c in it.get("comments") or []:
            body = c.get("body") or ""
            if c.get("author_id") in (ME["id"], a.get("id")) and (not COMMENT_PREFIXES or body.startswith(COMMENT_PREFIXES)):
                my_comments.append({"created": c.get("created") or "", "body": mask(body)})
        issues.append({"key": it["key"], "title": it.get("title") or "", "status": it.get("status") or "",
                       "type": it.get("type") or "", "created": it.get("created") or "", "updated": it.get("updated") or "",
                       "resolved": it.get("resolved") or "", "labels": list(it.get("labels") or []),
                       "assignee": a.get("display") or a.get("id") or "", "url": it.get("url") or TR.issue_url(it["key"]),
                       "mine": bool(ME["id"]) and a.get("id") == ME["id"], "my_comments": my_comments})
    n_me = sum(1 for i in issues if i["mine"])
    log(f"{TR.label}: {len(issues)}건 (나 {n_me}" + (f", 팀원 {len(issues) - n_me}" if TEAM else "") + ")")
    return issues


def resolve_team(found):
    """팀원 이름 → 출처 아이디·git author 후보. 출처가 없으면(none) 적은 이름 자체를 git author 로 본다."""
    TEAM.clear()
    for n in CFG.get("team") or []:
        n = str(n).strip()
        if not n or n in (ME.get("name"), ME.get("display")) or n in MY_AUTHORS:
            continue
        u = found.get(n)
        if TR.type != "none" and not u:
            log(f"팀원 '{n}' — {TR.label} 사용자를 못 찾음, git 이름으로만 씁니다")
        u = u or {"id": "", "display": n}
        if u.get("id") and u["id"] == ME.get("id"):
            continue
        cands = {n, u.get("id") or "", u.get("display") or ""}
        TEAM[u.get("display") or n] = {"id": u.get("id") or "",
                                      "authors": {a for a in cands if a and re.fullmatch(r"[\w.\- 가-힣]+", a)}}
    if TEAM:
        log("팀원: " + ", ".join(f"{d}({t['id'] or '-'})" for d, t in TEAM.items()))


def team_authors():
    return {a for t in TEAM.values() for a in t["authors"]}


def author_display(a):
    """git author·출처 아이디 → 표시 이름 (별칭·나·팀원). 모르면 그대로."""
    if a in ALIASES:
        return ALIASES[a]
    if a in MY_AUTHORS or (a and a in (ME.get("id"), ME.get("name"))):
        return ME.get("display") or a
    return next((d for d, t in TEAM.items() if a in t["authors"]), a)


# ---------------------------------------------------------------- git
def git_lines(repo, *args):
    r = subprocess.run(["git", "-c", "i18n.logOutputEncoding=utf-8", "-c", "core.quotepath=off", *args],
                       cwd=repo, capture_output=True)
    return r.stdout.decode("utf-8", errors="replace").splitlines()


def submodule_paths(root):
    try:
        text = (root / ".gitmodules").read_text(encoding="utf-8")
    except OSError:
        return []
    return [m.group(1).strip() for m in re.finditer(r"^\s*path\s*=\s*(.+)$", text, re.M)]


def repo_list():
    """[(이름, 경로)] — repos 가 있으면 그것, 비면 workspace_root 의 .gitmodules, 그것도 없으면 workspace_root 자체가 git 레포면 그것 하나."""
    out = []
    for p in CFG.get("repos") or []:
        path = _path(p)
        if path and (path / ".git").exists():
            out.append((path.name, path))
        else:
            log(f"git 레포가 아니어서 건너뜀: {p}")
    if out or CFG.get("repos") or not ROOT:
        return out
    out = [(rel, ROOT / rel) for rel in submodule_paths(ROOT) if (ROOT / rel / ".git").exists()]
    if not out and (ROOT / ".git").exists():
        out = [(ROOT.name, ROOT)]
    return out


def detect_me():
    """내 git author 이름 — my_authors 가 비어 있으면 토큰 주인과 git 설정에서 알아낸다."""
    if MY_AUTHORS:
        if not ME.get("display"):
            ME["display"] = sorted(MY_AUTHORS)[0]
        return
    names = {ME.get("name"), ME.get("display")}
    where = ROOT or next((p for _, p in repo_list()), None)
    for key in ("user.name", "user.email"):
        r = subprocess.run(["git", "config", key], cwd=where, capture_output=True)
        v = r.stdout.decode("utf-8", "replace").strip()
        names.add(v.split("@", 1)[0] if key == "user.email" else v)
        if key == "user.name" and v and not ME.get("display"):
            ME["display"] = v
    # git --author 정규식에 그대로 넘기므로 이름 문자만 남긴다
    MY_AUTHORS.update(n for n in names if n and re.fullmatch(r"[\w.\- 가-힣]+", n))
    log(f"내 이름 자동 판별: {', '.join(sorted(MY_AUTHORS)) or '(못 찾음 — ai_share.my_authors 를 채우세요)'}")


def collect_git(since, until):
    authors = sorted(MY_AUTHORS | team_authors())
    repos = repo_list()
    if not authors:
        log("내 git 이름을 몰라 커밋은 건너뜀 — ai_share.my_authors 를 채우세요")
        return []
    if not repos:
        log("볼 git 레포가 없음 — ai_share.repos 나 workspace_root 를 채우세요")
    commits = []
    for name, repo in repos:
        lines = git_lines(repo, "log", "--all", "--no-merges", f"--since={since} 00:00", f"--until={until} 23:59",
                          *[f"--author={a}" for a in authors], "--date=short",
                          "--format=%h%x1f%ad%x1f%an%x1f%(trailers:key=Co-Authored-By,valueonly,separator=%x2C)%x1f%s")
        seen = set()
        for line in reversed(lines):                   # 오래된 것부터 — 같은 날이면 '처음 나온 커밋'이 앞에 오게
            parts = line.split("\x1f", 4)
            if len(parts) < 5:
                continue
            sha, date, author, coauth, subject = parts
            if (author, subject) in seen:              # 브랜치 사이 체리픽 중복 제거
                continue
            seen.add((author, subject))
            commits.append({"repo": name, "sha": sha, "date": date, "subject": subject,
                            "author": author_display(author), "mine": author in MY_AUTHORS,
                            "ai": bool(re.search(r"(?i)claude|anthropic", coauth)),   # Claude Code 공동작성 커밋
                            "tickets": sorted(keys_in(subject))})
    log(f"git: {len(commits)}커밋 ({len(repos)}레포)")
    return commits


# ---------------------------------------------------------------- GitLab MR · AI 리뷰 (선택)
MR_CACHE_V = 3                                                # 요약 방식을 바꾸면 올린다 → 전부 다시 받음


def gitlab_conf():
    """(API 주소, 토큰) — 이슈 출처가 gitlab 이면 그 토큰, 아니면 ai_share.gitlab."""
    if TR.type == "gitlab":
        return TR.api_url, TR.token()
    g = CFG.get("gitlab") or {}
    tok = g.get("token_enc") or ""
    return str(g.get("api_url") or "").rstrip("/"), (kit.unprotect(tok) if tok else "")


def gitlab_get(base, token, path, params=None):
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"PRIVATE-TOKEN": token, "Accept": "application/json"}
    if FETCH:
        return FETCH(url, headers)
    return trackers.http_get_json(url, headers, (FULL.get("mail") or {}).get("ca_bundle") or "")


def bot_issues(body):
    """AI 리뷰 봇 리포트에서 review_bot.issue_heading 칸의 실제 지적만 뽑는다('없음'·none 으로 시작하는 칸은 뺀다).
    칸 = 굵은 줄(**…**)이나 # 제목 줄로 시작해 다음 그런 줄까지."""
    head = str(BOT.get("issue_heading") or "").strip()
    if not head:
        return []
    out, cur = [], None
    empty = re.compile(r"(?i)^(없음|none|n/?a|-)\b")

    def close():
        if cur and not empty.match(cur[0]):
            out.append(" ".join(cur))
    for line in (body or "").splitlines():
        t = line.strip()
        if (t.startswith("**") and t.endswith("**") and len(t) > 4) or t.startswith("#"):
            close()
            cur = [] if head.lower() in t.lower() else None
        elif cur is not None and t:
            cur.append(re.sub(r"^[-*]\s+", "", t))
    close()
    return [mask(x[:240] + ("…" if len(x) > 240 else "")) for x in out]


def collect_mrs(since, until):
    """내가 올린 GitLab MR — 이슈 키(제목·설명·브랜치)로 묶는다. review_bot.name 이 있으면 그 봇 리뷰의 지적을 센다.
    GitLab 주소·토큰이 없으면 건너뛴다. 팀원 MR 은 받지 않는다(코멘트 조회가 무겁다)."""
    base, token = gitlab_conf()
    if not (base and token):
        return []
    try:
        user = (gitlab_get(base, token, "/user") or {}).get("username") or ""
    except Exception as e:
        log(f"GitLab 사용자 확인 실패 — MR 건너뜀: {e}")
        return []
    mrs, page = [], 1
    while user:
        try:
            batch = gitlab_get(base, token, "/merge_requests", {
                "author_username": user, "scope": "all", "created_after": f"{since}T00:00:00Z",
                "created_before": f"{until}T23:59:59Z", "per_page": 100, "page": page}) or []
        except Exception as e:                       # MR 이 안 와도 수집 전체를 멈추지 않는다
            log(f"GitLab MR 조회 실패: {e}")
            break
        for m in batch:
            text = (m.get("title") or "") + " " + (m.get("description") or "")[:3000]
            keys = keys_in(text) | branch_keys(m.get("source_branch") or "")
            mrs.append({"id": f"{m['project_id']}:{m['iid']}", "project_id": m["project_id"], "iid": m["iid"],
                        "ref": (m.get("references") or {}).get("full") or f"!{m['iid']}", "url": m.get("web_url") or "",
                        "title": m.get("title") or "", "state": m.get("state") or "", "created": (m.get("created_at") or "")[:10],
                        "merged": (m.get("merged_at") or "")[:10], "updated_at": m.get("updated_at") or "",
                        "target": m.get("target_branch") or "", "user": user,
                        "author": ME.get("display") or user, "mine": True, "tickets": sorted(keys)})
        if len(batch) < 100:
            break
        page += 1
    bot = str(BOT.get("name") or "").strip()
    if bot and mrs:
        try:
            cache = json.loads(MR_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        todo = [m for m in mrs if (cache.get(m["id"], {}).get("updated_at"), cache.get(m["id"], {}).get("v"))
                != (m["updated_at"], MR_CACHE_V)]

        def notes_of(m):
            try:
                notes = gitlab_get(base, token, f"/projects/{m['project_id']}/merge_requests/{m['iid']}/notes",
                                   {"per_page": 100, "sort": "asc"}) or []
            except Exception:
                return m["id"], None
            by_bot = [n for n in notes if not n.get("system") and (n.get("author") or {}).get("username") == bot]
            human = [n for n in notes if not n.get("system") and (n.get("author") or {}).get("username") not in (bot, m["user"])]
            found = [x for n in by_bot for x in bot_issues(n.get("body") or "")]
            return m["id"], {"updated_at": m["updated_at"], "v": MR_CACHE_V, "bot_reviews": len(by_bot),
                             "bot_issues": found[:5], "bot_issue_count": len(found), "human_notes": len(human)}

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            for key, val in ex.map(notes_of, todo):
                if val:
                    cache[key] = val
        MR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        live = {m["id"] for m in mrs}
        MR_CACHE.write_text(json.dumps({k: v for k, v in cache.items() if k in live}, ensure_ascii=False), encoding="utf-8")
        for m in mrs:
            m.update({k: v for k, v in cache.get(m["id"], {}).items() if k != "updated_at"})
    n_bot = sum(1 for m in mrs if m.get("bot_issue_count"))
    log(f"GitLab MR: {len(mrs)}건" + (f" · AI 리뷰 지적 있는 MR {n_bot}" if bot else ""))
    return mrs


def ai_stats(commits, mrs):
    """사람별 Claude 공동작성 커밋 비율·AI 리뷰 지적 MR 수. 화면 카드용(발표 프롬프트에는 내 것만)."""
    st = {}
    for c in commits:
        a = st.setdefault(c["author"], {"commits": 0, "ai": 0, "mrs": 0, "bot_mrs": 0})
        a["commits"] += 1
        a["ai"] += bool(c.get("ai"))
    for m in mrs:
        a = st.setdefault(m["author"], {"commits": 0, "ai": 0, "mrs": 0, "bot_mrs": 0})
        a["mrs"] += 1
        a["bot_mrs"] += bool(m.get("bot_issue_count"))
    return st


# ---------------------------------------------------------------- 다른 파트 레포 (선택, 하네스 기록 참고용)
def sync_other():
    """다른 파트 레포를 wiki\\_src 에 clone(있으면 pull). 서브모듈은 받지 않는다.
    토큰은 환경변수 git config(http.extraHeader)로만 넘겨 .git/config·명령줄에 남지 않는다."""
    if not OTHER_URL:
        return False
    name, branch = OTHER_CLONE.name, OTHER.get("branch") or "main"
    tok = ""
    try:
        tok = kit.unprotect(OTHER["token_enc"]) if OTHER.get("token_enc") else gitlab_conf()[1]
    except Exception as e:
        log(f"다른 파트 토큰을 못 풂({e}) — 토큰 없이 시도")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    basic = ""
    if tok:
        user = "x-access-token" if "github" in OTHER_URL.lower() else "oauth2"
        basic = trackers.basic_header(user, tok)
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.extraHeader", GIT_CONFIG_VALUE_0=f"Authorization: {basic}")
    if (OTHER_CLONE / ".git").exists():
        cmd, cwd = ["git", "pull", "--ff-only", "--no-recurse-submodules", "origin", branch], OTHER_CLONE
    else:
        OTHER_CLONE.parent.mkdir(parents=True, exist_ok=True)
        cmd, cwd = ["git", "clone", "--single-branch", "--branch", branch, "--no-recurse-submodules",
                    OTHER_URL, str(OTHER_CLONE)], OTHER_CLONE.parent
    try:                                              # 네트워크가 멈추면 수집이 영영 안 끝나고 잠금도 안 풀린다
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        log(f"{name} 동기화가 5분 넘게 안 끝나 건너뜀 — 기존 clone 으로 진행")
        return OTHER_CLONE.exists()
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace")
        for s in (tok, basic):
            if s:
                err = err.replace(s, "***")
        log(f"{name} 동기화 실패 — 기존 clone 으로 진행: {err.strip()[:300]}")
    else:
        log(f"{name}: {cmd[1]} 완료")
    return OTHER_CLONE.exists()


# ---------------------------------------------------------------- 하네스 기록 (선택)
def read(p, limit=None):
    try:
        t = Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return t if limit is None else t[:limit]


def hdirs():
    return [str(HARNESS.get(k) or "").strip("/\\") for k in ("tasks_dir", "tickets_dir", "patterns_dir", "decisions_file")
            if HARNESS.get(k)]


def docs_authors(repo, since, until):
    """작성자별 하네스 폴더 커밋 수(기간 내, 전체)."""
    def count(*extra):
        c = {}
        for name in git_lines(repo, "log", "--no-merges", "--format=%an", *extra, "--", *hdirs()):
            name = author_display(name)
            c[name] = c.get(name, 0) + 1
        return c
    period, total = count(f"--since={since} 00:00", f"--until={until} 23:59"), count()
    return sorted(((n, period.get(n, 0), t) for n, t in total.items()), key=lambda x: (-x[1], -x[2]))


def folder_dates(repo, sub):
    """git 이력 기준 폴더별 마지막 변경일. clone 직후엔 mtime 이 전부 오늘이라 쓸 수 없다."""
    dates, cur = {}, None
    for line in git_lines(repo, "log", "--no-merges", "--date=short", "--format=@@%ad", "--name-only", "--", sub):
        if line.startswith("@@"):
            cur = line[2:]
        elif line.startswith(sub + "/") and cur:
            dates.setdefault(line[len(sub) + 1:].split("/", 1)[0], cur)
    return dates


def folder_keys(name):
    keys = set(keys_in(name))
    m = FOLDER_KEY_RE.match(name)
    if m:
        k = TR.key_from_number(m.group(1))
        if k:
            keys.add(k)
    return keys


def task_records(root, part, since, until):
    """tasks_dir 의 작업 폴더(state.md · grilling/index.md · review/index.md). 날짜는 git 이력, 미추적 폴더는 mtime."""
    sub = str(HARNESS.get("tasks_dir") or "").strip("/\\")
    tasks = root / sub if sub else None
    if not tasks or not tasks.is_dir():
        return []
    gdates = folder_dates(root, sub)
    records = []
    for folder in sorted(tasks.iterdir()):
        if not folder.is_dir():
            continue
        state = read(folder / "state.md", 2000)
        grilling = read(folder / "grilling" / "index.md")
        review = read(folder / "review" / "index.md", 4000)
        if not (state or grilling or review):
            continue
        date = gdates.get(folder.name, "")
        if not date and part == MY_PART:
            files = [p.stat().st_mtime for p in folder.rglob("*") if p.is_file()]
            date = dt.date.fromtimestamp(max(files)).isoformat() if files else ""
        if not (since <= date <= until):
            continue
        rel = folder.relative_to(root).as_posix()
        records.append({"kind": "task", "part": part, "path": rel if part == MY_PART else f"{root.name}/{rel}", "date": date,
                        "tickets": sorted(folder_keys(folder.name)),
                        "state": state.strip(), "grilling": mask(grilling), "review": mask(review)})
    return records


_ADDED_BY = {}


def owners_of(root, path):
    """하네스 기록(폴더·파일)을 처음 git 에 추가한 사람들. 미추적(로컬 전용)이면 빈 집합."""
    if root not in _ADDED_BY:
        added, cur = {}, None
        subs = [str(HARNESS.get(k) or "").strip("/\\") for k in ("tasks_dir", "tickets_dir") if HARNESS.get(k)]
        for line in git_lines(root, "log", "--diff-filter=AR", "--format=@@%an", "--name-only", "--", *subs):
            if line.startswith("@@"):
                cur = line[2:]
            elif line.strip():
                added[line.strip()] = cur              # log 는 최신순 → 마지막에 덮어쓴 값이 최초 추가자
        _ADDED_BY[root] = added
    return {a for f, a in _ADDED_BY[root].items() if f == path or f.startswith(path + "/")}


def record_owner(path):
    """내 파트 기록의 주인 — "me" / "team" / None(팀 밖 사람 것 → 뺀다). 미추적 = 내 로컬에서만 만든 것."""
    owners = owners_of(ROOT, path)
    if not owners or owners & MY_AUTHORS:
        return "me"
    return "team" if owners & team_authors() else None


def collect_docs(since, until, workspaces):
    """workspaces = [(root, part), ...] — 첫 번째가 내 파트. harness 가 꺼져 있으면 리포트 폴더만 본다."""
    records = []
    if HARNESS.get("enabled"):
        for root, part in workspaces:
            records += task_records(root, part, since, until)
            sub = str(HARNESS.get("tickets_dir") or "").strip("/\\")
            for md in sorted((root / sub).rglob("*.md")) if sub and (root / sub).is_dir() else []:
                text = read(md)
                m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
                date = m.group(1) if m else dt.date.fromtimestamp(md.stat().st_mtime).isoformat()
                if not (since <= date <= until):
                    continue
                rel = md.relative_to(root).as_posix()
                records.append({"kind": "ticket-doc", "part": part, "date": date,
                                "path": rel if part == MY_PART else f"{root.name}/{rel}",
                                "tickets": sorted(folder_keys(md.stem)), "body": mask(text)})
    for md in sorted(REPORTS.glob("*.md")) if REPORTS.is_dir() else []:
        m = re.match(r"(\d{4})(\d{2})(\d{2})_", md.name)
        rn = str(CFG.get("report_name") or "")
        if not m or (rn and rn in md.name) or WEEKLY_NAME in md.name:   # 이 도구가 만든 자료는 다시 먹지 않는다
            continue
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if since <= date <= until:
            records.append({"kind": "report", "part": MY_PART, "path": md.name, "date": date,
                            "tickets": sorted(keys_in(md.name)), "title": md.stem})
    harness_on = HARNESS.get("enabled") and ROOT is not None
    for r in records:
        r["mine"] = r["part"] == MY_PART and (r["kind"] == "report" or not harness_on or record_owner(r["path"]) == "me")
    if harness_on:
        records = [r for r in records if r["part"] != MY_PART or r["kind"] == "report" or record_owner(r["path"])]
    roots = {part: root for root, part in workspaces}
    for r in records:                                   # 누구 기록인지 — 처음 커밋한 사람, 미추적이면 나
        rel = r["path"] if r["part"] == MY_PART else r["path"].split("/", 1)[-1]
        owners = set() if r["kind"] == "report" or not harness_on else owners_of(roots[r["part"]], rel)
        r["author"] = (", ".join(sorted({author_display(o) for o in owners}))
                       or (ME.get("display") or ME.get("name") if r["part"] == MY_PART else ""))
    patterns, decisions, authors = {}, {}, {}
    if HARNESS.get("enabled"):
        for root, part in workspaces:
            pdir = str(HARNESS.get("patterns_dir") or "").strip("/\\")
            patterns[part] = sorted(p.stem for p in (root / pdir).glob("*.md")) if pdir else []
            dfile = str(HARNESS.get("decisions_file") or "").strip("/\\")
            decisions[part] = re.findall(r"^## (.+)$", read(root / dfile), re.M) if dfile else []
            authors[part] = docs_authors(root, since, until)
        log(f"하네스: 기록 {len(records)}건 ("
            + ", ".join(f"{p} {sum(1 for r in records if r['part'] == p)}" for _, p in workspaces)
            + "), patterns " + ", ".join(f"{p} {len(v)}" for p, v in patterns.items()))
    return records, patterns, decisions, authors


# ---------------------------------------------------------------- 선택 (select.txt)
SELECT_STATES = ("발표고정", "발표제외", "비공개")
SELECT_HEADER = """# 이슈 선택 — 한 줄에 하나: <이슈키>  <발표고정|발표제외|비공개>  # 메모
# 안 적은 이슈 = 기록에 포함, 발표 사례는 ⭐추천 우선 + LLM 판단. collect 가 이 파일을 지우지 않는다.
# 비공개 = 내 PC 기록에만 남기고 발표 프롬프트에서 제외. 웹 화면(agent.py serve)에서도 고칠 수 있다.
"""


def load_select():
    sel = {}
    try:
        text = SELECT_FILE.read_text(encoding="utf-8")
    except OSError:
        return sel
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        parts = line.split(None, 2)                     # 키에 '#' 이 들 수 있어(레포#번호) 메모는 공백 뒤 '#' 부터
        if len(parts) >= 2 and key_ok(parts[0]) and parts[1] in SELECT_STATES:
            rest = parts[2].strip() if len(parts) > 2 else ""
            sel[parts[0]] = {"state": parts[1], "memo": rest[1:].strip() if rest.startswith("#") else ""}
    return sel


def save_select(sel):
    lines = []
    for k, v in sorted(sel.items()):
        memo = " ".join(v.get("memo", "").split())      # 줄바꿈 제거 — 한 줄 한 이슈
        lines.append(f"{k}  {v['state']}" + (f"  # {memo}" if memo else ""))
    SELECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SELECT_FILE.with_suffix(".tmp")
    tmp.write_text(SELECT_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, SELECT_FILE)


# ---------------------------------------------------------------- 조립
def tag_of(title):
    """제목에서 꼬리표(tag) — tag.label 이 비면 끔. regex 는 첫 묶음(없으면 전체), 기본은 [대괄호] 안. ignore 에 든 값은 건너뛴다."""
    if not TAG.get("label"):
        return ""
    ignore = {str(x).strip() for x in TAG.get("ignore") or []}
    for m in re.finditer(TAG.get("regex") or r"\[([^\]]+)\]", title or ""):
        v = (m.group(1) if m.re.groups else m.group(0)) or ""
        v = v.strip()
        if v and v not in ignore:
            return v
    return ""


def demote(md, by=2):
    """끼워 넣는 문서의 제목을 by 단계 내려 위키 섹션 아래로 들어가게 한다."""
    out, fence = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            line = re.sub(r"^(#{1,6}) ", lambda m: "#" * min(6, len(m.group(1)) + by) + " ", line)
        out.append(line)
    return "\n".join(out)


UNKNOWN = "(이슈 미조회)"


def stub(key, date):
    return {"key": key, "title": UNKNOWN, "status": "", "type": "", "created": date, "updated": date,
            "resolved": "", "labels": [], "my_comments": [], "commits": [], "records": [], "url": TR.issue_url(key)}


def owner_of(part, t):
    """이슈 주인 — 내 파트는 현재 담당자가 나·팀원이면 그 사람, 팀 밖이면 실제로 커밋·기록을 남긴 팀원.
    다른 파트는 그 하네스 기록을 처음 커밋한 사람."""
    if part == MY_PART:
        team = set(TEAM) | {ME.get("display")}
        if t.get("assignee") in team:
            return t["assignee"]
        who = {c.get("author", "") for c in t["commits"]} | {r.get("author", "") for r in t["records"]}
        return ", ".join(sorted(w for w in who if w in team)) or t.get("assignee") or ME.get("display") or ""
    return ", ".join(sorted({a for r in t["records"] for a in r.get("author", "").split(", ") if a}))


REVERT_RE = re.compile(r"(?i)\brevert|원복|되돌")


def recommend_score(t, harness, until_d):
    """발표 사례 추천 점수(LLM 없음). 판단 과정이 남은 것·되돌림·규모 큰 것·최근 것을 위로.
    하네스·AI 리뷰가 꺼져 있으면 그 점수는 그냥 0 이다."""
    score, why = 0, []
    if harness == "grilling":
        score += 3; why.append("grilling")
    elif harness == "doc":
        score += 1; why.append("하네스 문서")
    if any(r.get("review") for r in t["records"]):
        score += 1; why.append("리뷰")
    if any(REVERT_RE.search(c["subject"]) for c in t["commits"]):
        score += 2; why.append("되돌림(교훈)")
    if len({c["repo"] for c in t["commits"]}) >= 2:
        score += 1; why.append("여러 레포")
    if len(t["commits"]) >= 3:
        score += 1; why.append(f"커밋 {len(t['commits'])}")
    if t.get("my_comments"):
        score += 1; why.append("이슈 댓글")
    if BOT.get("name") and any(m.get("bot_issue_count") for m in t.get("mrs", [])):
        score += 1; why.append("AI 리뷰 지적")
    age = (until_d - dt.date.fromisoformat(t["updated"])).days if t.get("updated") else 999
    if age <= 7:
        score += 2; why.append("이번 주")
    elif age <= 14:
        score += 1; why.append("지난주")
    return score, " · ".join(why)


def index_columns():
    return (["part", "ticket", "updated"] + ([TAG["label"]] if TAG.get("label") else []) + ["status", "commits"]
            + (["harness"] if HARNESS.get("enabled") else []) + ["선택", "title"])


def group_tickets(issues, commits, records, mrs, meta):
    """(part, key) → 이슈 한 건. 내 이슈·커밋·MR 은 MY_PART, 다른 파트 레포 기록은 그 파트."""
    by_key = {(MY_PART, i["key"]): dict(i, commits=[], records=[]) for i in issues}
    for c in commits:
        for k in c["tickets"]:
            by_key.setdefault((MY_PART, k), stub(k, c["date"]))["commits"].append(c)
    for r in records:
        for k in r["tickets"]:
            by_key.setdefault((r["part"], k), stub(k, r["date"]))["records"].append(r)
    for m in mrs:
        for k in m["tickets"]:
            by_key.setdefault((MY_PART, k), stub(k, m["created"])).setdefault("mrs", []).append(m)
    for (part, k), t in by_key.items():
        t.setdefault("mrs", [])
        if t["title"] == UNKNOWN and k in meta:          # 담당 밖 이슈는 제목·상태만 보강 (댓글은 안 가져옴)
            t.update({f: v for f, v in meta[k].items() if f not in ("key", "comments", "assignee")})
            t["assignee"] = (meta[k].get("assignee") or {}).get("display", "")
        if t["title"] == UNKNOWN:                        # 출처에 없으면(none 출처 포함) 그 키가 처음 나온 커밋·MR 제목
            first = sorted(t["commits"], key=lambda c: c["date"])
            t["title"] = (first[0]["subject"] if first else (t["mrs"][0]["title"] if t["mrs"] else UNKNOWN))
    return by_key


def build_wiki(since, until, issues, commits, records, patterns, decisions, authors, meta, mrs=(), stats=None):
    tdir = WIKI / "tickets"
    if tdir.exists():                               # 생성물만 있는 폴더 — 기간이 바뀌면 빠진 이슈가 남지 않게 비운다
        shutil.rmtree(tdir)
    (WIKI / "_raw").mkdir(parents=True, exist_ok=True)
    by_key = group_tickets(issues, commits, records, mrs, meta)
    sel = load_select()
    rows = []
    me_st = (stats or {}).get(ME.get("display") or ME.get("name", ""))
    until_d = dt.date.fromisoformat(until)
    ordered = sorted(by_key.items(), key=lambda kv: kv[1]["updated"], reverse=True)
    ordered.sort(key=lambda kv: kv[0][0] != MY_PART)  # 내 파트 먼저, 파트 안에서는 updated 최신순 (stable sort)
    cols = index_columns()
    for (part, k), t in ordered:
        has_grilling = any(r.get("grilling") for r in t["records"])
        harness = "grilling" if has_grilling else ("doc" if any(r["kind"] != "report" for r in t["records"]) else "none")
        mine = part == MY_PART and bool(t.get("mine") or any(c.get("mine") for c in t["commits"])
                                         or any(r.get("mine") for r in t["records"])
                                         or any(m.get("mine") for m in t["mrs"]))
        score, why = (recommend_score(t, harness, until_d)            # 추천은 내 것만, 제외 유형은 빼고
                      if mine and t.get("type") not in EXCLUDE_TYPES else (0, ""))
        tag = tag_of(t["title"])
        url = t.get("url") or TR.issue_url(k)
        lines = ["---", f"ticket: {k}", f"display: {TR.display(k)}", f"part: {part}", f"title: {t['title']}",
                 f"status: {t['status']}", f"type: {t['type']}", f"tag: {tag}", f"created: {t['created']}",
                 f"updated: {t['updated']}", f"resolved: {t['resolved']}", f"labels: {', '.join(t['labels'])}",
                 f"owner: {owner_of(part, t)}", f"mine: {'Y' if mine else ''}",
                 f"repos: {', '.join(sorted({c['repo'] for c in t['commits']}))}",
                 f"commits: {len(t['commits'])}", f"ai_commits: {sum(1 for c in t['commits'] if c.get('ai'))}",
                 f"mrs: {len(t['mrs'])}", f"bot_issues: {sum(m.get('bot_issue_count', 0) for m in t['mrs'])}",
                 f"harness: {harness}", f"score: {score}", f"why: {why}",
                 f"select: {sel.get(k, {}).get('state', '')}", f"source: {url}", "---", "",
                 f"# {TR.display(k)} — {t['title']}", ""]
        if part != MY_PART:
            lines += [f"> {part.upper()} 파트 하네스 기록 (발표자 본인 작업 아님)", ""]
        elif not mine:
            lines += [f"> 팀원 {owner_of(part, t)} 작업 (발표자 본인 작업 아님)", ""]
        if t["commits"]:
            lines.append("## 커밋")
            for c in sorted(t["commits"], key=lambda c: c["date"]):
                lines.append(f"- {c['date']} `{c['repo']}` {c['sha']} {c['subject']}"
                             + ("" if c.get("mine", True) else f" — {c.get('author', '')}"))
            lines.append("")
        if t["mrs"]:
            lines.append("## MR" + (" · AI 리뷰" if BOT.get("name") else ""))
            for m in sorted(t["mrs"], key=lambda m: m["created"]):
                tail = []
                if m.get("bot_reviews"):
                    tail.append(f"AI 리뷰 {m['bot_reviews']}회 · 지적 {m.get('bot_issue_count', 0)}건")
                if m.get("human_notes"):
                    tail.append(f"사람 코멘트 {m['human_notes']}")
                lines.append(f"- {m['created']} `{m['ref']}` → {m['target']} [{m['state']}] {m['title']}"
                             + (f" ({' · '.join(tail)})" if tail else ""))
                for x in m.get("bot_issues", [])[:3]:
                    lines.append(f"  - ⚠️ {x}")
            lines.append("")
        if t["my_comments"]:
            lines.append("## 이슈에 남긴 댓글")
            for c in t["my_comments"]:
                lines += [f"### {c['created']}", c["body"], ""]
        for r in t["records"]:
            lines.append(f"## 하네스 기록 — `{r['path']}` ({r['date']}{' · ' + r['author'] if r.get('author') else ''})")
            if r["kind"] == "task":
                if r["state"]:
                    lines += ["```", r["state"], "```"]
                if r["grilling"]:
                    lines += ["### grilling (판단 과정)", demote(r["grilling"])]
                if r["review"]:
                    lines += ["### review", demote(r["review"])]
            elif r["kind"] == "ticket-doc":
                lines.append(demote(r["body"]))
            else:
                lines.append(f"- 리포트: {r['title']}")
            lines.append("")
        (tdir / part).mkdir(parents=True, exist_ok=True)
        (tdir / part / f"{slug(k)}.md").write_text("\n".join(lines), encoding="utf-8")
        val = {"part": part, "ticket": k, "updated": t["updated"], "status": t["status"], "commits": str(len(t["commits"])),
               "harness": "" if harness == "none" else harness, "선택": sel.get(k, {}).get("state", ""),
               "title": t["title"][:60].replace("|", "/")}
        if TAG.get("label"):
            val[TAG["label"]] = tag.replace("|", "/")
        rows.append("| " + " | ".join(val[c] for c in cols) + " |")

    reports = [r for r in records if r["kind"] == "report"]
    n_part = {}
    for part, _ in by_key:
        n_part[part] = n_part.get(part, 0) + 1
    index = [
        f"# AI 작업 회고 INDEX — {since} ~ {until}", "",
        f"생성: {dt.datetime.now():%Y-%m-%d %H:%M} / 이슈 {len(by_key)}건 ("
        + ", ".join(f"{p} {n}" for p, n in n_part.items())
        + f") · 커밋 {len(commits)}건"
        + (f" · 하네스 기록 {sum(1 for r in records if r['kind'] != 'report')}건" if HARNESS.get("enabled") else "")
        + f" · 리포트 {len(reports)}건", "",
        "## 티켓", "",
        "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols),
        *rows, "",
        "## 리포트 (내 reports 폴더)", "",
        *[f"- {r['date']} {r['title']}" for r in reports], "",
        "## 내 AI 활용", "",
        *([f"- Claude 공동작성 커밋 {me_st['ai']}/{me_st['commits']} ({me_st['ai'] * 100 // max(me_st['commits'], 1)}%)"]
          + ([f"- 내 MR {me_st['mrs']}건 중 AI 리뷰가 지적한 MR {me_st['bot_mrs']}건"] if BOT.get("name") else []) + [""]
          if me_st else ["- (집계 없음)", ""]),
    ]
    if HARNESS.get("enabled"):
        index += ["## 파트별 하네스 사용 (작성자별 하네스 폴더 커밋 수)", "",
                  f"| part | 작성자 | {since}~{until} | 전체 |", "|---|---|---|---|",
                  *[f"| {p} | {n} | {a} | {tot} |" for p, lst in authors.items() for n, a, tot in lst], "",
                  "## 하네스 지식 자산", ""]
        for p, ps in patterns.items():
            if ps:
                index += [f"- {p} patterns {len(ps)}개: " + ", ".join(ps), ""]
        for p, ds in decisions.items():
            if ds:
                index += [f"- {p} decisions {len(ds)}건:", *[f"  - {d}" for d in ds], ""]
    (WIKI / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    raw = {"since": since, "until": until, "issues": issues, "commits": commits, "records": records,
           "patterns": patterns, "decisions": decisions, "authors": authors}
    (WIKI / "_raw" / f"collect-{dt.date.today():%Y%m%d}.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"wiki: {WIKI / 'INDEX.md'} (이슈 {len(by_key)}건 — " + ", ".join(f"{p} {n}" for p, n in n_part.items()) + ")")


# ---------------------------------------------------------------- present (업무 공유 발표 준비, 선택)
REC_N, REC_MIN = 10, 4                                  # 웹 화면(web.html)과 같은 값 — ⭐ 추천 = 4점 이상 상위 10건


def front_matter(text):
    fm = {}
    if text.startswith("---"):
        for line in text.split("\n---", 1)[0].splitlines()[1:]:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def ticket_docs(part):
    """[(키, 경로, 머리 값)] — 파일 이름은 slug 라 진짜 키는 머리(ticket:)에서."""
    out = []
    for p in sorted((WIKI / "tickets" / part).glob("*.md")):
        fm = front_matter(p.read_text(encoding="utf-8"))
        out.append((fm.get("ticket") or p.stem, p, fm))
    return out


def recommended(sel):
    """⭐ 추천 이슈 키. 발표제외·비공개는 빼고 점수 → 최신순 상위 REC_N."""
    cut = (dt.date.fromisoformat(wiki_period()["until"]) - dt.timedelta(days=REC_DAYS)).isoformat()
    cands = []
    for k, p, fm in ticket_docs(MY_PART):
        if sel.get(k, {}).get("state") in ("발표제외", "비공개"):
            continue
        if int(fm.get("score") or 0) >= REC_MIN and fm.get("updated", "") >= cut:
            cands.append((int(fm["score"]), fm.get("updated", ""), k))
    cands.sort(reverse=True)
    return {k for *_, k in cands[:REC_N]}


def team_only_keys():
    """발표 자료에 넣지 않는 내 파트 이슈 — 팀원만 한 것, 제외 유형."""
    return {k for k, p, fm in ticket_docs(MY_PART) if fm.get("mine") != "Y" or fm.get("type") in EXCLUDE_TYPES}


def pick_docs(part, budget, sel, rec=frozenset(), skip=frozenset()):
    """발표고정 > ⭐추천 > grilling > doc > 기록 없음 순, 같은 순위면 최신 수정순으로 budget 글자까지."""
    docs = []
    for k, p, fm in ticket_docs(part):
        state = sel.get(k, {}).get("state", "")
        if state in ("비공개", "발표제외") or k in skip:
            continue
        text = re.sub(r"^select: .*$", f"select: {state}\nrecommend: {'Y' if k in rec else ''}",
                      p.read_text(encoding="utf-8"), count=1, flags=re.M)
        rank = (-2 if state == "발표고정" else -1 if k in rec else 0 if "harness: grilling" in text
                else 1 if "harness: doc" in text else 2)
        docs.append((rank, p.stat().st_mtime, text))
    docs.sort(key=lambda d: (d[0], -d[1]))
    body, used = [], 0
    for _, _, text in docs:
        if used + len(text) > budget:
            break
        body.append(text)
        used += len(text)
    return body, used, len(docs)


def _index_table(index, fn):
    """INDEX 의 '## 티켓' 표 줄마다 fn(칸 목록, 머리 이름들) → 고친 칸 목록 또는 None(줄 빼기)."""
    out, head, in_tab = [], None, False
    for line in index.splitlines():
        if line.startswith("## "):
            in_tab, head = line.strip() == "## 티켓", None
        elif in_tab and line.startswith("|"):
            cells = line.split("|")
            if head is None:
                head = [c.strip() for c in cells]
            elif not set(line) <= set("|-: "):
                cells = fn(cells, head)
                if cells is None:
                    continue
                line = "|".join(cells)
        out.append(line)
    return "\n".join(out)


def apply_select(index, sel, drop=frozenset()):
    """INDEX 선택 열을 지금 select.txt 로 고치고, 비공개·drop(팀원만 한 내 파트 이슈) 행은 뺀다."""
    def fix(cells, head):
        key, part = cells[head.index("ticket")].strip(), cells[head.index("part")].strip()
        state = sel.get(key, {}).get("state", "")
        if state == "비공개" or (part == MY_PART and key in drop):
            return None
        cells[head.index("선택")] = f" {state} "
        return cells
    return _index_table(index, fix)


def compact_index(index):
    """작은 모델용: 표에서 하네스 기록이 있는 내 파트 행만(하네스가 꺼져 있으면 내 파트 행만) 남긴다."""
    def keep(cells, head):
        if cells[head.index("part")].strip() != MY_PART:
            return None
        if "harness" in head and not cells[head.index("harness")].strip():
            return None
        return cells
    return _index_table(index, keep)


def prompt_template(path_value, default_name):
    p = _path(path_value)
    if p and p.is_file():
        return p.read_text(encoding="utf-8")
    return resource(default_name).read_text(encoding="utf-8")


def build_prompt(max_chars, compact=False):
    """내 파트 이슈를 예산 75% 까지 먼저 채우고, 다른 파트 기록은 남은 예산으로 별도 블록에 넣는다."""
    template = prompt_template(CFG.get("prompt_file"), "prompt_present.md")
    template = (template.replace("{{MINE}}", MY_PART).replace("{{OTHER}}", OTHER_PART or "다른 파트")
                .replace("{{COMPANY}}", kit.company_name(FULL) or "우리 회사"))
    sel = load_select()
    team_only = team_only_keys()
    index = apply_select((WIKI / "INDEX.md").read_text(encoding="utf-8"), sel, team_only)
    if compact:
        index = compact_index(index)
    budget = max_chars - len(template) - len(index)
    rec = recommended(sel)
    mine, used, n_mine = pick_docs(MY_PART, int(budget * 0.75), sel, rec, team_only)
    other, _, n_other = ([], 0, 0) if not OTHER_PART else pick_docs(OTHER_PART, budget - used, sel)
    hist = read(_path(CFG.get("history_file")) or (WIKI / "share_history.md"))   # 지난 발표 주제 — 겹치는 주제를 피한다
    sep = "\n\n---\n\n"
    prompt = (template.replace("{{INDEX}}", index)
              .replace("{{TICKETS}}", sep.join(mine) or "(없음)")
              .replace("{{OTHER_TICKETS}}", sep.join(other) or "(없음)")
              .replace("{{HISTORY}}", hist or "(없음)"))
    return prompt, f"{MY_PART} {len(mine)}/{n_mine} (⭐추천 {len(rec)}), {OTHER_PART or '-'} {len(other)}/{n_other}"


def run_claude(prompt, timeout=1800):
    """구독 로그인으로 도는 헤드리스 호출. 도구 없이 프롬프트만으로 쓰게 한다.
    cwd 를 임시 폴더로 둬 프로젝트 CLAUDE.md·MCP 가 자료에 섞이지 않게 한다."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}   # 세션 안에서 호출돼도 중첩 차단 회피
    exe = shutil.which("claude") or "claude"
    cmd = [exe, "-p", "--output-format", "text", "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
    # npm 설치(claude.cmd)만 셸이 필요하다. 셸을 거치면 시간 초과 때 cmd.exe 만 죽고 claude 가 남아
    # 출력 통로를 붙잡아 영영 안 끝난다 — 그래서 끝낼 때는 프로세스 트리째 끈다
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         cwd=tempfile.gettempdir(), env=env, shell=(os.name == "nt" and not exe.lower().endswith(".exe")))
    try:
        out, err = p.communicate(prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(p)
        raise RuntimeError(f"claude 가 {timeout // 60}분 안에 끝나지 않아 껐습니다")
    if p.returncode != 0:
        raise RuntimeError(f"claude 실행 실패 (rc={p.returncode}): {err.decode('utf-8', 'replace')[:1000]}"
                           f" {out.decode('utf-8', 'replace')[:1000]}")
    return out.decode("utf-8", errors="replace")


def kill_tree(p):
    """자식까지 끈다(윈도우는 taskkill /T). 끈 뒤 남은 출력은 짧게만 기다린다."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=30)
    else:
        p.kill()
    try:
        p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_ollama(prompt, model, num_ctx=32768):
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps({"model": model or "qwen2.5:7b", "prompt": prompt, "stream": False,
                         "options": {"num_ctx": num_ctx, "temperature": 0.2}}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.loads(r.read().decode("utf-8"))["response"]


def run_llm(prompt, engine="claude", model=""):
    return run_ollama(prompt, model) if engine == "ollama" else run_claude(prompt)


def present(engine, model):
    if not (WIKI / "INDEX.md").exists():
        raise SystemExit("wiki 가 없습니다. 먼저 collect 를 실행하세요.")
    max_chars = 40_000 if engine == "ollama" else 300_000
    prompt, used = build_prompt(max_chars, compact=(engine == "ollama"))
    stamp = f"{dt.date.today():%Y%m%d}"
    (WIKI / "_raw").mkdir(parents=True, exist_ok=True)
    (WIKI / "_raw" / f"present-prompt-{stamp}-{engine}.md").write_text(prompt, encoding="utf-8")
    log(f"present[{engine}]: 이슈 문서 {used}건 투입, {len(prompt):,}자")
    out = run_llm(prompt, engine, model)
    REPORTS.mkdir(parents=True, exist_ok=True)
    target = REPORTS / f"{stamp}_{CFG.get('report_name') or '업무공유_준비'}{'_ollama맛보기' if engine == 'ollama' else ''}.md"
    target.write_text(out, encoding="utf-8")
    log(f"발표 자료: {target}")
    return target


# ---------------------------------------------------------------- 내 프롬프트 (로컬 전용)
# _private/ 는 웹 화면에서만 읽고, 기록 문서·발표 프롬프트·주간 보고에는 절대 안 들어간다
PASTE_RE = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content[^>]*>", re.S)
TAG_BLOCK_RE = re.compile(r"<(system-reminder|local-command-stdout|local-command-caveat)>.*?</\1>", re.S)


def transcripts_dirs():
    """Claude Code 대화 기록 폴더들 — ~/.claude/projects/<레포 경로를 - 로 바꾼 이름>."""
    if CFG.get("transcripts_dir"):
        return [_path(CFG["transcripts_dir"])]
    roots = ([ROOT] if ROOT else []) + [p for _, p in repo_list()]
    out = []
    for r in roots:
        d = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(r))
        if d not in out:
            out.append(d)
    return out


def clean_prompt(text):
    """사람이 친 프롬프트만 남긴다. 붙여 넣은 원문은 길이만, 슬래시 명령은 '/이름 인자' 한 줄로."""
    text = PASTE_RE.sub(lambda m: f"[붙여넣은 내용 {len(m.group(1))}자]", text)
    text = TAG_BLOCK_RE.sub("", text)
    cmd = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
    if cmd:
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        text = f"{cmd.group(1).strip()} {args.group(1).strip() if args else ''}"
    text = re.sub(r"<[^>\n]{1,40}>", "", text).strip()
    return mask(text[:500] + ("…" if len(text) > 500 else ""))


def collect_prompts(since, until):
    """세션마다 내가 직접 친 프롬프트를 모아 이슈 키로 묶는다. 키는 세션 앞부분 프롬프트·세션 제목·브랜치에서 찾는다."""
    out, n_sess = {}, 0
    for d in transcripts_dirs():
        if not d or not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            if dt.date.fromtimestamp(f.stat().st_mtime).isoformat() < since:
                continue
            title, branch, prompts = "", "", []
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        if '"type":"ai-title"' in line:
                            title = json.loads(line).get("aiTitle", "") or title
                            continue
                        if '"type":"user"' not in line or '"promptSource":"system"' in line:
                            continue
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    content = rec.get("message", {}).get("content")
                    if rec.get("isMeta") or rec.get("isSidechain") or not isinstance(content, str):
                        continue                             # 도구 결과·서브에이전트·시스템 주입은 사람이 친 게 아니다
                    branch = rec.get("gitBranch") or branch
                    p = clean_prompt(content)
                    if p:
                        prompts.append((rec.get("timestamp", "")[:10], p))
            if not prompts or not (since <= prompts[0][0] <= until):
                continue
            head = " ".join(p for _, p in prompts[:2]) + " " + title
            keys = keys_in(head) | branch_keys(branch)
            if not keys:
                continue
            n_sess += 1
            sess = {"session": f.stem[:8], "date": prompts[0][0], "title": title, "branch": branch,
                    "prompts": [{"date": t, "text": p} for t, p in prompts[:30]]}
            for k in keys:
                out.setdefault(k, []).append(sess)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    (PRIVATE / "prompts.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log(f"내 프롬프트(로컬 전용): 세션 {n_sess}개 → 이슈 {len(out)}건")


# ---------------------------------------------------------------- collect
def gather(since, until, other=True):
    """수집만 — 위키를 쓰지 않는다(주간 보고도 이것을 쓴다). 이슈 출처가 실패해도 git 쪽은 계속 모은다."""
    errors = []
    try:
        issues = collect_issues(since, until)
    except Exception as e:
        errors.append(f"{TR.label or '이슈 출처'}: {e}")
        log(f"{TR.label or '이슈 출처'} 조회 실패 — git 만으로 계속합니다: {e}")
        issues = []
    detect_me()
    commits = collect_git(since, until)
    workspaces = ([(ROOT, MY_PART)] if ROOT else [])
    if other and HARNESS.get("enabled") and OTHER_PART and sync_other():
        workspaces.append((OTHER_CLONE, OTHER_PART))
    records, patterns, decisions, authors = collect_docs(since, until, workspaces)
    mrs = collect_mrs(since, until)
    meta = {}
    extra = {k for x in commits + records + mrs for k in x["tickets"]} - {i["key"] for i in issues}
    if extra and TR.type != "none":
        try:
            meta = TR.fetch_meta(extra)
            log(f"{TR.label} 메타: {len(meta)}/{len(extra)}건 보강")
        except Exception as e:
            log(f"{TR.label} 메타 조회 실패({e}) — 제목 없이 진행")
    return {"since": since, "until": until, "issues": issues, "commits": commits, "records": records,
            "patterns": patterns, "decisions": decisions, "authors": authors, "mrs": mrs, "meta": meta,
            "stats": ai_stats(commits, mrs), "errors": errors}


def collect(since, until):
    t0 = dt.datetime.now()
    d = gather(since, until)
    (WIKI / "_raw").mkdir(parents=True, exist_ok=True)
    (WIKI / "_raw" / "me.json").write_text(json.dumps(dict(ME, authors=sorted(MY_AUTHORS), team=list(TEAM)),
                                                      ensure_ascii=False), encoding="utf-8")
    (WIKI / "_raw" / "stats.json").write_text(json.dumps(d["stats"], ensure_ascii=False), encoding="utf-8")
    build_wiki(since, until, d["issues"], d["commits"], d["records"], d["patterns"], d["decisions"], d["authors"],
               d["meta"], d["mrs"], d["stats"])
    collect_prompts(since, until)
    log(f"collect 소요 {(dt.datetime.now() - t0).total_seconds():.0f}초")
    return d


# ---------------------------------------------------------------- 주간 업무 보고 초안
def week_range(today=None):
    """이번 주 = 월요일 ~ 오늘."""
    today = today or dt.date.today()
    return (today - dt.timedelta(days=today.weekday())).isoformat(), today.isoformat()


def weekly_material(d):
    """주간 보고 원자료(마크다운, 내 것만) — LLM 에 넣고, LLM 이 실패하면 그대로 메일 본문이 된다."""
    since, until = d["since"], d["until"]
    issues = {i["key"]: i for i in d["issues"] if i.get("mine")}
    commits = [c for c in d["commits"] if c.get("mine")]
    mrs = [m for m in d["mrs"] if m.get("mine")]
    meta = d.get("meta") or {}
    lines = [f"기간: {since} ~ {until}", f"나: {ME.get('display') or ME.get('name') or '(이름 모름)'}", ""]
    if d.get("errors"):
        lines += [f"> 수집 경고: {e}" for e in d["errors"]] + [""]
    if TR.type != "none":
        lines.append(f"## 내 담당 이슈 — 이번 기간에 움직인 것 ({len(issues)}건)")
        for i in sorted(issues.values(), key=lambda i: i["updated"], reverse=True):
            extra = f" · 해결 {i['resolved']}" if i.get("resolved") else ""
            lines.append(f"- {TR.display(i['key'])} {i['title']} — 상태 {i['status'] or '?'} · 수정 {i['updated']}{extra}"
                         + (f" · {i['url']}" if i.get("url") else ""))
            for c in i.get("my_comments") or []:
                if since <= c["created"] <= until:
                    first = " ".join(c["body"].split())[:200]
                    lines.append(f"  - 댓글 {c['created']}: {first}")
        lines.append("")
    by = {}
    for c in commits:
        for k in c["tickets"] or [""]:
            by.setdefault(k, []).append(c)
    lines.append(f"## 내 커밋 ({len(commits)}개)")
    for k in sorted(by, key=lambda k: (k == "", k)):
        if k:
            title = (issues.get(k) or meta.get(k) or {}).get("title") or sorted(by[k], key=lambda c: c["date"])[0]["subject"]
            url = (issues.get(k) or meta.get(k) or {}).get("url") or TR.issue_url(k)
            lines.append(f"### {TR.display(k)} {title}" + (f" ({url})" if url else ""))
        else:
            lines.append("### 이슈 키 없는 커밋")
        for c in sorted(by[k], key=lambda c: c["date"]):
            lines.append(f"- {c['date']} `{c['repo']}` {c['sha']} {c['subject']}" + (" (AI 공동작성)" if c.get("ai") else ""))
    if not commits:
        lines.append("- (없음)")
    lines.append("")
    if mrs:
        lines.append(f"## 내 MR ({len(mrs)}건)")
        for m in mrs:
            lines.append(f"- {m['created']} {m['ref']} [{m['state']}] {m['title']}" + (f" · {m['url']}" if m.get("url") else ""))
        lines.append("")
    n_ai = sum(1 for c in commits if c.get("ai"))
    lines.append(f"AI 활용: Claude 공동작성 커밋 {n_ai}/{len(commits)} ({n_ai * 100 // max(len(commits), 1)}%)")
    return "\n".join(lines)


def weekly_prompt(material, since, until):
    w = CFG.get("weekly_report") or {}
    t = prompt_template(w.get("prompt_file"), "prompt_weekly.md")
    return (t.replace("{{SINCE}}", since).replace("{{UNTIL}}", until)
            .replace("{{NAME}}", ME.get("display") or ME.get("name") or "")
            .replace("{{COMPANY}}", kit.company_name(FULL) or "")
            .replace("{{MATERIAL}}", material))


def weekly_recipients():
    """weekly_report.to — 비면 키트 메일 설정의 내 주소(초안을 내가 먼저 보고 고쳐 쓰게), 그것도 비면 알림 주소."""
    to = kit._as_list((CFG.get("weekly_report") or {}).get("to"))
    if to:
        return to
    m = kit.mail_config(FULL)
    return kit._as_list(m.get("user") or m.get("alert_to"))


def weekly_subject(since, until):
    s = str((CFG.get("weekly_report") or {}).get("subject") or DEFAULT_CFG["weekly_report"]["subject"])
    return kit.render(s.replace("{since}", since).replace("{until}", until))


def weekly_status(ok, text, note=""):
    try:
        kit.write_status(FEATURE_WEEKLY, [{"name": "주간 업무 보고 초안", "ok": ok, "text": text}], note)
    except Exception:
        pass


def send_report(path, since, until, mailer=None, ready=None):
    """보고 파일을 메일로. (보냈나, 이유)."""
    ok, why = (ready or (lambda: kit.mail_ready(kit.mail_config(FULL))))()
    if not ok:
        return False, "메일 설정 필요 — " + why
    to = weekly_recipients()
    if not to:
        return False, "받는 사람이 없습니다 — ai_share.weekly_report.to 나 mail.user"
    try:
        (mailer or kit.send_mail)(to, weekly_subject(since, until), Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"메일 보내기 실패: {e}"
    return True, "→ " + ", ".join(to)


def weekly(since=None, until=None, send=True, gather_fn=None, llm=None, mailer=None, ready=None, today=None):
    """이번 주 수집 → 초안 → reports\\YYYYMMDD_주간보고.md → (send) 메일. LLM 이 실패하면 원자료를 대신 쓴다.
    반환 {"path", "text", "llm_ok", "sent", "why"} — why 는 사람이 읽을 결과 설명."""
    today = today or dt.date.today()
    d_since, d_until = week_range(today)
    since, until = since or d_since, until or d_until
    w = CFG.get("weekly_report") or {}
    try:
        d = (gather_fn or gather)(since, until, other=False)
        material = weekly_material(d)
    except Exception as e:                              # 수집 전체가 죽어도 빈손으로 끝내지 않는다
        material = f"기간: {since} ~ {until}\n\n> 수집 실패: {e}"
    llm_ok, notes = True, []
    try:
        text = (llm or run_llm)(weekly_prompt(material, since, until), w.get("engine") or "claude", w.get("model") or "")
        if not str(text or "").strip():
            raise RuntimeError("빈 응답")
    except (Exception, SystemExit) as e:
        llm_ok = False
        notes.append(f"초안 생성 실패 — 원자료만 보냅니다: {str(e)[:300]}")
        text = f"# 주간 업무 보고 원자료 — {since} ~ {until}\n\n> {notes[-1]}\n\n{material}\n"
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{today:%Y%m%d}_{WEEKLY_NAME}.md"
    path.write_text(text, encoding="utf-8")
    log(f"주간 보고 {'초안' if llm_ok else '원자료'}: {path}")
    sent = False
    if send:
        sent, why = send_report(path, since, until, mailer, ready)
        notes.append(("메일 " + why) if sent else why)
        log(notes[-1])
    else:
        notes.append("메일은 보내지 않음(파일만)")
    ok = llm_ok and (sent or not send)
    weekly_status(ok, f"{since} ~ {until} · {path.name} · " + " · ".join(notes), "LLM " + str(w.get("engine") or "claude"))
    return {"path": str(path), "name": path.name, "text": text, "llm_ok": llm_ok, "sent": sent, "why": " · ".join(notes)}


# ---------------------------------------------------------------- serve (로컬 웹 화면)
def list_tickets():
    sel, out = load_select(), []
    for p in sorted((WIKI / "tickets").glob("*/*.md")):
        fm = front_matter(p.read_text(encoding="utf-8"))
        key = fm.get("ticket") or p.stem
        s = sel.get(key, {})
        out.append({"part": p.parent.name, "key": key, "disp": fm.get("display") or key, "url": fm.get("source", ""),
                    "title": fm.get("title", ""), "tag": fm.get("tag", ""),
                    "status": fm.get("status", ""), "type": fm.get("type", ""), "updated": fm.get("updated", ""),
                    "commits": int(fm.get("commits") or 0), "harness": fm.get("harness", ""),
                    "repos": fm.get("repos", ""), "owner": fm.get("owner", ""),
                    "score": int(fm.get("score") or 0), "why": fm.get("why", ""), "mine": fm.get("mine") == "Y",
                    "ai_commits": int(fm.get("ai_commits") or 0), "mrs": int(fm.get("mrs") or 0),
                    "bot_issues": int(fm.get("bot_issues") or 0),
                    "select": s.get("state", ""), "memo": s.get("memo", "")})
    return out


NAME_RE = re.compile(r"[\w.\- 가-힣@]{1,40}")


def team_settings():
    return {"part": MY_PART, "team": list(CFG.get("team") or []),
            "other_part": OTHER_PART, "other_team": list(OTHER.get("team") or []),
            "aliases": dict(CFG.get("aliases") or {}), "file": kit.F_CONFIG, "tracker": TR.label}


def save_team_settings(body):
    """웹 화면에서 고친 팀 명단·별칭을 config.local.json 의 ai_share 에 쓴다. 다음 수집부터 적용된다."""
    def names(v):
        out = [str(x).strip() for x in (v or []) if str(x).strip()]
        if len(out) > 50 or not all(NAME_RE.fullmatch(x) for x in out):
            raise ValueError("이름은 한글·영문·숫자·공백·.-@ 만, 40자 이내, 50명까지")
        return list(dict.fromkeys(out))
    team, other_team = names(body.get("team")), names(body.get("other_team"))
    aliases = {str(k).strip(): str(v).strip() for k, v in (body.get("aliases") or {}).items() if str(k).strip()}
    if not all(NAME_RE.fullmatch(k) and NAME_RE.fullmatch(v) for k, v in aliases.items()):
        raise ValueError("별칭은 'git 이름=표시 이름' — 한글·영문·숫자·공백·.-@ 만, 40자 이내")
    full = kit.load_config()
    a = full.setdefault("ai_share", {})
    a["team"] = team
    a["aliases"] = aliases
    if isinstance(a.get("other"), dict) and OTHER_PART:
        a["other"]["team"] = other_team
    kit.save_config(full)
    configure()                                         # 이 서버에서 바로 다시 수집해도 새 명단으로


def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wiki_period():
    try:
        m = re.search(r"— (\S+) ~ (\S+)", (WIKI / "INDEX.md").read_text(encoding="utf-8").splitlines()[0])
        return {"since": m.group(1), "until": m.group(2)}
    except (OSError, IndexError, AttributeError):
        today = dt.date.today()
        return {"since": (today - dt.timedelta(days=int(CFG.get("default_days") or 90))).isoformat(), "until": today.isoformat()}


def report_files():
    """최신 날짜 먼저, 같은 날이면 주간 보고 → 발표 자료 → ollama 맛보기 순."""
    names = [p.name for p in REPORTS.glob("*.md")] if REPORTS.is_dir() else []
    rn = str(CFG.get("report_name") or "")
    names = [n for n in names if WEEKLY_NAME in n or (rn and rn in n)]
    return sorted(names, key=lambda n: (-int(n[:8]) if n[:8].isdigit() else 0, WEEKLY_NAME not in n, "ollama" in n))


def features():
    """화면이 켜고 끌 칸 — 선택 기능이 꺼져 있으면 그 열·카드·필터를 숨긴다."""
    return {"tracker": TR.type, "tracker_label": TR.label, "key_re": TR.js_key_re, "tag": TAG.get("label") or "",
            "review": bool(BOT.get("name")), "harness": bool(HARNESS.get("enabled")), "other": OTHER_PART,
            "weekly_engine": (CFG.get("weekly_report") or {}).get("engine") or "claude"}


def serve(port, open_browser=True):
    """127.0.0.1 에서만 연다. 쓰기 요청은 커스텀 헤더를 요구해 다른 사이트가 보내는 요청(CSRF)을 막는다."""
    import http.server
    import threading
    import webbrowser
    lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False)
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if u.path == "/":
                return self.reply(200, resource("web.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/tickets":
                return self.reply(200, {"tickets": list_tickets(), "period": wiki_period(), "week": dict(zip(("since", "until"), week_range())),
                                        "reports": report_files(), "mine": MY_PART, "other": OTHER_PART,
                                        "me": read_json(WIKI / "_raw" / "me.json"), "features": features(),
                                        "stats": read_json(WIKI / "_raw" / "stats.json"), "rec_days": REC_DAYS})
            if u.path == "/api/team":
                return self.reply(200, team_settings())
            if u.path == "/api/prompts":                     # 내 프롬프트 — 이 PC 화면에서만
                allp = read_json(PRIVATE / "prompts.json")
                return self.reply(200, {"sessions": allp.get(q.get("key", ""), [])})
            if u.path == "/api/doc":
                kind = q.get("kind")
                if kind == "ticket" and q.get("part") in (MY_PART, OTHER_PART) and key_ok(q.get("key", "")):
                    path = WIKI / "tickets" / q["part"] / f"{slug(q['key'])}.md"
                elif kind == "index":
                    path = WIKI / "INDEX.md"
                elif kind == "report" and q.get("name") in report_files():
                    path = REPORTS / q["name"]
                else:
                    return self.reply(400, {"error": "bad request"})
                if not path.exists():
                    return self.reply(404, {"error": "없음"})
                return self.reply(200, {"text": path.read_text(encoding="utf-8")})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if self.headers.get("X-AI-Share") != "1":
                return self.reply(403, {"error": "forbidden"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self.reply(400, {"error": "bad json"})
            u = urllib.parse.urlparse(self.path).path
            if u == "/api/team":
                try:
                    with lock:
                        save_team_settings(body)
                except ValueError as e:
                    return self.reply(400, {"error": str(e)})
                return self.reply(200, {"ok": True, **team_settings()})
            if u == "/api/select":
                key, state, memo = body.get("key", ""), body.get("state", ""), body.get("memo", "")
                if not key_ok(key) or state not in ("",) + SELECT_STATES:
                    return self.reply(400, {"error": "bad select"})
                with lock:
                    sel = load_select()
                    if state:
                        sel[key] = {"state": state, "memo": memo}
                    else:
                        sel.pop(key, None)
                    save_select(sel)
                return self.reply(200, {"ok": True})
            if u in ("/api/collect", "/api/weekly", "/api/weekly/send"):
                since, until = body.get("since", ""), body.get("until", "")
                if u != "/api/weekly/send" and not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", since) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", until)):
                    return self.reply(400, {"error": "날짜 형식 YYYY-MM-DD"})
                if not lock.acquire(blocking=False):
                    return self.reply(409, {"error": "이미 다른 작업 중"})
                buf, res = io.StringIO(), {}
                try:
                    with contextlib.redirect_stdout(buf):
                        configure()                          # config.local.json 을 고쳤으면 다시 띄우지 않아도 반영
                        if u == "/api/collect":
                            collect(since, until)
                        elif u == "/api/weekly":
                            res = weekly(since, until, send=False)
                        else:
                            name = body.get("name", "")
                            if name not in report_files() or WEEKLY_NAME not in name:
                                raise ValueError("보낼 주간 보고 파일을 고르세요")
                            sent, why = send_report(REPORTS / name, since or week_range()[0], until or week_range()[1])
                            res = {"sent": sent, "why": why}
                            weekly_status(sent, f"{name} · {why}", "웹 화면에서 보냄")
                    ok = res.get("sent", True) if u == "/api/weekly/send" else True
                except (Exception, SystemExit) as e:
                    buf.write(f"\n실패: {e}")
                    ok = False
                finally:
                    lock.release()
                return self.reply(200 if ok else 500, {"ok": ok, "log": buf.getvalue(), **res})
            self.reply(404, {"error": "not found"})

    class Server(http.server.ThreadingHTTPServer):
        allow_reuse_address = os.name != "nt"          # 윈도우 SO_REUSEADDR 은 같은 포트 중복 실행을 허용해 버린다

    url = f"http://127.0.0.1:{port}/"
    try:
        srv = Server(("127.0.0.1", port), Handler)
    except OSError:                                   # 이미 떠 있으면(두 번 실행) 그 화면만 연다
        log(f"이미 실행 중 — {url}")
        if open_browser:
            webbrowser.open(url)
        return 1
    log(f"웹 화면: {url}  (끄려면 Ctrl+C)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


# ---------------------------------------------------------------- 토큰 넣기
def set_token(which="tracker", secret=None, protect=None, full=None, save=None):
    """토큰을 DPAPI 로 암호화해 ai_share 갈래에 넣는다. which = tracker · gitlab · other."""
    import getpass
    secret, protect = secret or getpass.getpass, protect or kit.protect
    full = full if full is not None else kit.load_config()
    a = full.setdefault("ai_share", {})
    kind = str((a.get("tracker") or {}).get("type") or "none").strip().lower()
    if which == "tracker":
        if kind == "jira":
            print("Jira 는 키트의 jira 갈래(주소·인증·토큰)를 같이 씁니다 — python setup.py --jira 로 넣으세요.\n"
                  "  (마지막에 'Jira 새 이슈 감시를 켤까요?' 는 아니요로 둬도 됩니다)")
            return 1
        if kind not in ("github", "gitlab"):
            print("ai_share.tracker.type 이 %s 이라 토큰이 필요 없습니다 (github · gitlab 만)." % kind)
            return 1
        target, label = a.setdefault("tracker", {}), kind
    elif which == "gitlab":
        if kind == "gitlab":
            print("이슈 출처가 gitlab 이라 MR 리뷰도 그 토큰을 씁니다 — python agent.py set-token 으로 넣으세요.")
            return 1
        target, label = a.setdefault("gitlab", {}), "GitLab(MR 리뷰)"
    else:
        target, label = a.setdefault("other", {}), "다른 파트 레포 clone"
    tok = secret("%s 토큰 (화면에 보이지 않습니다): " % label).strip()
    if not tok:
        print("취소했습니다.")
        return 1
    target["token_enc"] = protect(tok)
    (save or kit.save_config)(full)
    print("이 PC·이 Windows 사용자만 풀 수 있게 암호화해 저장했습니다: %s" % kit.F_CONFIG)
    return 0


# ---------------------------------------------------------------- main
configure()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="serve",
                    choices=["weekly", "collect", "present", "run", "serve", "set-token"])
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--engine", choices=["claude", "ollama"], default="claude")
    ap.add_argument("--model", default="qwen2.5:7b", help="ollama 모델 (맛보기용)")
    ap.add_argument("--port", type=int, help="serve 포트 (기본 ai_share.port)")
    ap.add_argument("--no-browser", action="store_true", help="serve 때 브라우저를 자동으로 열지 않는다")
    ap.add_argument("--no-mail", action="store_true", help="weekly 때 메일을 보내지 않고 파일만")
    ap.add_argument("--gitlab", action="store_true", help="set-token: MR 리뷰용 GitLab 토큰")
    ap.add_argument("--other", action="store_true", help="set-token: 다른 파트 레포 clone 토큰")
    ap.add_argument("--kit-service", action="store_true", help=argparse.SUPPRESS)   # 허브가 띄운 프로세스 표식
    ap.add_argument("--kit-job", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.cmd == "set-token":
        return set_token("gitlab" if a.gitlab else "other" if a.other else "tracker")
    if a.cmd == "serve":
        return serve(a.port or int(CFG.get("port") or 8640), open_browser=not a.no_browser)
    if a.cmd == "weekly":
        res = weekly(a.since, a.until, send=not a.no_mail)
        print(res["why"])
        return 0
    since = a.since or (dt.date.today() - dt.timedelta(days=int(CFG.get("default_days") or 90))).isoformat()
    until = a.until or dt.date.today().isoformat()
    if a.cmd in ("collect", "run"):
        collect(since, until)
    if a.cmd in ("present", "run"):
        present(a.engine, a.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
