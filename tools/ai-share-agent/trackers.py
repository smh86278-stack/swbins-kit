# -*- coding: utf-8 -*-
"""이슈 출처(tracker) 어댑터 — AI 작업 회고(agent.py)가 이슈 도구를 모르고 일하게 해 주는 층.

ai_share.tracker.type 으로 고른다:  jira · github · gitlab · none(이슈 도구 없음 — 커밋·브랜치의 키로만 묶는다)

모든 어댑터는 같은 모양을 돌려준다.
    whoami()                          -> {"id", "name", "display"}            토큰 주인(나)
    resolve_users(names)              -> {입력이름: {"id", "display"}}         팀원 이름 → 출처의 사용자 아이디
    fetch_issues(since, until, ids)   -> [{"key", "title", "status", "type", "created", "updated", "resolved",
                                           "labels", "assignee": {"id", "display"}, "url",
                                           "comments": [{"author_id", "created", "body"}]}]
    fetch_meta(keys)                  -> {키: 위 모양(댓글 없음)}               내 담당 밖 이슈의 제목·상태(지원하는 출처만)
    find_keys(text) · key_from_number(n) · display(key) · issue_url(key) · js_key_re

네트워크는 fetch(url, headers) -> JSON 하나로만 나간다 — 테스트에서 가짜로 바꿔 끼운다.
토큰은 kit.protect(DPAPI)로 암호화한 *_enc 로만 저장한다. Jira 는 키트의 jira 갈래(setup.py --jira)를 그대로 쓴다.
"""
import base64
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.normpath(os.path.join(HERE, "..", "macro-hub"))
if KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)
import kit  # noqa: E402  — 설정·DPAPI·TLS 공통 코드

DEFAULT_KEY_RE = r"[A-Z][A-Z0-9]+-\d+"
TIMEOUT = 60


# ---------------------------------------------------------------- 공통

def http_get_json(url, headers, ca_bundle=""):
    """GET → JSON. 401/403 은 토큰 문제로 알려 준다."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=kit.ssl_context({"ca_bundle": ca_bundle or ""})) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("인증 거부(HTTP %d) — 토큰·권한을 확인하세요: %s" % (e.code, url.split("?")[0]))
        if e.code == 404:
            raise LookupError("없음(HTTP 404): %s" % url.split("?")[0])
        raise RuntimeError("응답 오류 HTTP %d: %s" % (e.code, url.split("?")[0]))


def day(v):
    return str(v or "")[:10]


def _quote(v):
    return urllib.parse.quote(str(v), safe="")


class Tracker:
    """이슈 도구 없음(none) — 기본 동작. 다른 어댑터가 이것을 이어받는다."""
    type = "none"
    label = ""                          # 화면에 보일 이름 (Jira·GitHub·GitLab)

    def __init__(self, tcfg=None, full=None, fetch=None, token=None):
        self.cfg = dict(tcfg or {})
        self.full = full if full is not None else {}
        self._fetch = fetch
        self._token = token
        try:
            self.key_re = re.compile(self.cfg.get("key_regex") or DEFAULT_KEY_RE)
        except re.error:                           # 잘못 적은 정규식이면 기본값으로(수집 전체를 죽이지 않게)
            self.key_re = re.compile(DEFAULT_KEY_RE)

    # --- 네트워크
    def token(self):
        if self._token is None:
            enc = self.cfg.get("token_enc") or ""
            self._token = kit.unprotect(enc) if enc else ""
        return self._token

    def ca_bundle(self):
        return self.cfg.get("ca_bundle") or (self.full.get("mail") or {}).get("ca_bundle") or ""

    def headers(self):
        return {"Accept": "application/json"}

    def get(self, url):
        h = self.headers()
        return self._fetch(url, h) if self._fetch else http_get_json(url, h, self.ca_bundle())

    # --- 준비
    def ready(self):
        """(준비됨?, 모자란 것)."""
        return True, ""

    # --- 키
    @property
    def js_key_re(self):
        """화면(web.html)이 본문 속 키를 링크로 바꿀 때 쓰는 정규식(JS 문법)."""
        return self.key_re.pattern

    def find_keys(self, text):
        return set(self.key_re.findall(text or "")) if not self.key_re.groups else \
            {m.group(0) for m in self.key_re.finditer(text or "")}

    def key_from_number(self, n):
        """브랜치 규칙이 숫자만 뽑았을 때 키로 만든다 — 모르면 None."""
        return None

    def display(self, key):
        return key

    def issue_url(self, key):
        return ""

    # --- 자료
    def whoami(self):
        return {"id": "", "name": "", "display": ""}

    def resolve_users(self, names):
        return {}

    def fetch_issues(self, since, until, user_ids):
        return []

    def fetch_meta(self, keys):
        return {}


# ---------------------------------------------------------------- Jira

_JW = []


def jira_watch():
    """키트의 jira-watch.py — Jira 설정 정리·인증 머리글·ADF 글자 뽑기를 같이 쓴다."""
    if not _JW:
        spec = importlib.util.spec_from_file_location("kit_jira_watch", os.path.join(kit.ROOT, "jira-watch.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _JW.append(mod)
    return _JW[0]


class JiraTracker(Tracker):
    """Jira Server/Data Center(Bearer PAT, /rest/api/2) · Cloud(Basic 이메일:토큰, accountId, /rest/api/3/search/jql).
    접속 값은 키트의 jira 갈래(base_url·auth·email·token_enc·ca_bundle)를 그대로 쓴다 — 새로 받지 않는다."""
    type = "jira"
    label = "Jira"
    FIELDS = "summary,status,issuetype,created,updated,resolutiondate,labels,assignee,comment"

    def __init__(self, tcfg=None, full=None, fetch=None, token=None):
        super().__init__(tcfg, full, fetch, token)
        self.jira = jira_watch().load_cfg(self.full)
        keys = [re.escape(str(k).strip()) for k in (self.cfg.get("jira_project_keys") or []) if str(k).strip()]
        self.project_keys = [str(k).strip() for k in (self.cfg.get("jira_project_keys") or []) if str(k).strip()]
        if keys and not self.cfg.get("key_regex"):
            self.key_re = re.compile(r"\b(?:%s)-\d+\b" % "|".join(keys))

    @property
    def cloud(self):
        return self.jira.get("auth") != "server"

    @property
    def base(self):
        return self.jira.get("base_url") or ""

    def token(self):
        if self._token is None:
            enc = self.jira.get("token_enc") or ""
            self._token = kit.unprotect(enc) if enc else ""
        return self._token

    def ca_bundle(self):
        return self.jira.get("ca_bundle") or ""

    def headers(self):
        return {"Authorization": jira_watch().auth_header(self.jira, self.token()), "Accept": "application/json"}

    def ready(self):
        ok, why = jira_watch().ready(self.jira)
        return ok, why

    def key_from_number(self, n):
        return "%s-%s" % (self.project_keys[0], n) if len(self.project_keys) == 1 else None

    def issue_url(self, key):
        return "%s/browse/%s" % (self.base, key) if self.base else ""

    def api(self, path, params=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return self.get(url)

    def whoami(self):
        me = self.api("/rest/api/3/myself" if self.cloud else "/rest/api/2/myself")
        if self.cloud:
            mail = str(me.get("emailAddress") or "")
            return {"id": me.get("accountId") or "", "name": mail.split("@")[0] or me.get("displayName") or "",
                    "display": me.get("displayName") or ""}
        return {"id": me.get("name") or "", "name": me.get("name") or "", "display": me.get("displayName") or me.get("name") or ""}

    def resolve_users(self, names):
        out = {}
        for n in names:
            try:
                if self.cloud:
                    users = self.api("/rest/api/3/user/search", {"query": n, "maxResults": 5})
                else:
                    users = self.api("/rest/api/2/user/search", {"username": n, "maxResults": 5})
            except Exception:
                continue
            for u in users or []:
                uid = u.get("accountId") if self.cloud else u.get("name")
                if uid and n in (u.get("displayName"), u.get("name"), u.get("emailAddress"),
                                 str(u.get("emailAddress") or "").split("@")[0]):
                    out[n] = {"id": uid, "display": u.get("displayName") or n}
                    break
        return out

    def jql(self, since, until, user_ids):
        who = ", ".join('"%s"' % str(u).replace('"', "") for u in user_ids if u)
        return 'assignee in (%s) AND updated >= "%s" AND updated <= "%s 23:59" ORDER BY updated DESC' % (who, since, until)

    def search(self, jql, fields, page_size=100):
        """검색 결과를 끝까지 넘긴다 — Server 는 startAt, Cloud 는 nextPageToken."""
        out, start, token = [], 0, None
        while True:
            if self.cloud:
                params = {"jql": jql, "fields": fields, "maxResults": page_size}
                if token:
                    params["nextPageToken"] = token
                page = self.api("/rest/api/3/search/jql", params)
            else:
                page = self.api("/rest/api/2/search", {"jql": jql, "fields": fields, "startAt": start,
                                                       "maxResults": page_size, "validateQuery": "warn"})
            got = [x for x in (page or {}).get("issues") or [] if isinstance(x, dict)]
            out += got
            if self.cloud:
                token = page.get("nextPageToken")
                if not token or page.get("isLast") or not got:
                    return out
            else:
                start += len(got)
                if not got or start >= int(page.get("total") or 0):
                    return out

    def normalize(self, it, with_comments=True):
        f = it.get("fields") or {}
        a = f.get("assignee") or {}
        uid = (lambda u: (u or {}).get("accountId") if self.cloud else (u or {}).get("name"))
        comments = []
        if with_comments:
            for c in ((f.get("comment") or {}).get("comments") or []):
                comments.append({"author_id": uid(c.get("author")) or "", "created": day(c.get("created")),
                                 "body": jira_watch().adf_text(c.get("body")).strip()})
        return {"key": it["key"], "title": str(f.get("summary") or ""),
                "status": (f.get("status") or {}).get("name") or "", "type": (f.get("issuetype") or {}).get("name") or "",
                "created": day(f.get("created")), "updated": day(f.get("updated")), "resolved": day(f.get("resolutiondate")),
                "labels": list(f.get("labels") or []), "assignee": {"id": uid(a) or "", "display": a.get("displayName") or ""},
                "url": self.issue_url(it["key"]), "comments": comments}

    def fetch_issues(self, since, until, user_ids):
        ids = [u for u in user_ids if u]
        if not ids:
            return []
        return [self.normalize(x) for x in self.search(self.jql(since, until, ids), self.FIELDS) if x.get("key")]

    def fetch_meta(self, keys):
        keys, meta = sorted(keys), {}
        for i in range(0, len(keys), 50):
            jql = "key in (%s)" % ",".join(keys[i:i + 50])
            try:
                got = self.search(jql, "summary,status,issuetype,created,updated,resolutiondate,labels,assignee", 50)
            except Exception:                 # 메타 보강 실패는 수집 실패가 아니다(지워진 키가 섞이면 Cloud 는 400)
                continue
            for x in got:
                if x.get("key"):
                    meta[x["key"]] = self.normalize(x, with_comments=False)
        return meta


# ---------------------------------------------------------------- GitHub · GitLab 공통 (레포#번호)

class RepoTracker(Tracker):
    """키 = '레포#번호'. 커밋·브랜치의 '#123' 은 레포가 하나일 때만 그 레포로 붙인다."""
    REPOS_KEY = "repos"

    def __init__(self, tcfg=None, full=None, fetch=None, token=None):
        super().__init__(tcfg, full, fetch, token)
        self.repos = [str(r).strip().strip("/") for r in (self.cfg.get(self.REPOS_KEY) or []) if str(r).strip()]
        self.key_re = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)+[\w.-]+)?#(\d+)\b")

    @property
    def js_key_re(self):
        return r"(?:[\w.-]+/)+[\w.-]+#\d+"

    def canon(self, repo):
        for r in self.repos:
            if r.lower() == str(repo).lower():
                return r
        return None

    def find_keys(self, text):
        out = set()
        for m in self.key_re.finditer(text or ""):
            if m.group(1):
                r = self.canon(m.group(1))
                if r:
                    out.add("%s#%s" % (r, m.group(2)))
            elif len(self.repos) == 1:
                out.add("%s#%s" % (self.repos[0], m.group(2)))
        return out

    def key_from_number(self, n):
        return "%s#%s" % (self.repos[0], n) if len(self.repos) == 1 else None

    def display(self, key):
        repo, _, n = key.rpartition("#")
        return "%s#%s" % (repo.rsplit("/", 1)[-1], n) if repo else key

    def type_of(self, labels, fallback="issue"):
        """유형 = type_labels 에 든 라벨 중 처음 것, 없으면 fallback."""
        want = [str(x) for x in (self.cfg.get("type_labels") or [])]
        for w in want:
            if w in labels:
                return w
        return fallback

    def ready(self):
        lack = []
        if not self.repos:
            lack.append("tracker.%s" % self.REPOS_KEY)
        if not self.cfg.get("token_enc") and self._token is None:
            lack.append("tracker.token_enc (python agent.py set-token)")
        if self.type == "gitlab" and not self.cfg.get("api_url"):
            lack.append("tracker.api_url")
        return (not lack), ("ai_share 설정에 없는 값: %s" % ", ".join(lack) if lack else "")


class GitHubTracker(RepoTracker):
    """GitHub(·Enterprise) — /search/issues 로 레포·담당자·기간을 찾고(PR 제외), 댓글은 이슈의 comments_url."""
    type = "github"
    label = "GitHub"
    PER_PAGE = 100

    @property
    def api_url(self):
        return str(self.cfg.get("api_url") or "https://api.github.com").rstrip("/")

    @property
    def web_url(self):
        if self.cfg.get("web_url"):
            return str(self.cfg["web_url"]).rstrip("/")
        a = self.api_url
        if a == "https://api.github.com":
            return "https://github.com"
        return re.sub(r"/api/v3$", "", a)

    def headers(self):
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token():
            h["Authorization"] = "Bearer " + self.token()
        return h

    def issue_url(self, key):
        repo, _, n = key.rpartition("#")
        return "%s/%s/issues/%s" % (self.web_url, repo, n) if repo else ""

    def whoami(self):
        u = self.get(self.api_url + "/user")
        return {"id": u.get("login") or "", "name": u.get("login") or "", "display": u.get("name") or u.get("login") or ""}

    def resolve_users(self, names):
        out = {}
        for n in names:
            try:
                u = self.get(self.api_url + "/users/" + _quote(n))
            except Exception:
                continue
            if u.get("login"):
                out[n] = {"id": u["login"], "display": u.get("name") or u["login"]}
        return out

    def search_query(self, repo, user, since, until):
        return "repo:%s is:issue assignee:%s updated:%s..%s" % (repo, user, since, until)

    def fetch_issues(self, since, until, user_ids):
        found = {}
        for repo in self.repos:
            for user in [u for u in user_ids if u]:
                q = self.search_query(repo, user, since, until)
                page = 1
                while True:
                    url = "%s/search/issues?%s" % (self.api_url, urllib.parse.urlencode(
                        {"q": q, "per_page": self.PER_PAGE, "page": page, "sort": "updated", "order": "desc"}))
                    data = self.get(url) or {}
                    items = data.get("items") or []
                    for it in items:
                        if it.get("pull_request"):          # 검색은 PR 도 이슈로 돌려준다 — 뺀다
                            continue
                        key = "%s#%s" % (repo, it.get("number"))
                        if key not in found:
                            found[key] = self.normalize(repo, it, user)
                    total = int(data.get("total_count") or 0)
                    if len(items) < self.PER_PAGE or page * self.PER_PAGE >= min(total, 1000):
                        break                               # 검색 API 는 1000건까지만 준다
                    page += 1
        return list(found.values())

    def normalize(self, repo, it, user):
        labels = [(x.get("name") if isinstance(x, dict) else str(x)) for x in it.get("labels") or []]
        people = [a for a in (it.get("assignees") or []) if isinstance(a, dict)] or \
            ([it["assignee"]] if isinstance(it.get("assignee"), dict) else [])
        a = next((p for p in people if p.get("login") == user), people[0] if people else {})
        return {"key": "%s#%s" % (repo, it.get("number")), "title": str(it.get("title") or ""),
                "status": str(it.get("state") or ""), "type": self.type_of(labels),
                "created": day(it.get("created_at")), "updated": day(it.get("updated_at")), "resolved": day(it.get("closed_at")),
                "labels": labels, "assignee": {"id": a.get("login") or "", "display": a.get("login") or ""},
                "url": it.get("html_url") or "", "comments": self.comments(it)}

    def comments(self, it):
        if not int(it.get("comments") or 0) or not it.get("comments_url"):
            return []
        out, page = [], 1
        while True:
            got = self.get("%s?%s" % (it["comments_url"], urllib.parse.urlencode({"per_page": 100, "page": page}))) or []
            for c in got:
                out.append({"author_id": (c.get("user") or {}).get("login") or "", "created": day(c.get("created_at")),
                            "body": str(c.get("body") or "")})
            if len(got) < 100:
                return out
            page += 1


class GitLabTracker(RepoTracker):
    """GitLab — /projects/:id/issues(담당자·기간) 페이지 넘김, 댓글은 notes(system 노트 제외)."""
    type = "gitlab"
    label = "GitLab"
    REPOS_KEY = "projects"
    PER_PAGE = 100

    @property
    def api_url(self):
        return str(self.cfg.get("api_url") or "").rstrip("/")

    @property
    def web_url(self):
        return str(self.cfg.get("web_url") or re.sub(r"/api/v4$", "", self.api_url)).rstrip("/")

    def headers(self):
        h = {"Accept": "application/json"}
        if self.token():
            h["PRIVATE-TOKEN"] = self.token()
        return h

    def issue_url(self, key):
        proj, _, n = key.rpartition("#")
        return "%s/%s/-/issues/%s" % (self.web_url, proj, n) if proj and self.web_url else ""

    def whoami(self):
        u = self.get(self.api_url + "/user")
        return {"id": u.get("username") or "", "name": u.get("username") or "", "display": u.get("name") or u.get("username") or ""}

    def resolve_users(self, names):
        out = {}
        for n in names:
            try:
                got = self.get(self.api_url + "/users?" + urllib.parse.urlencode({"username": n})) or []
                if not got:
                    got = [u for u in (self.get(self.api_url + "/users?" + urllib.parse.urlencode({"search": n})) or [])
                           if n in (u.get("name"), u.get("username"))]
            except Exception:
                continue
            if got and got[0].get("username"):
                out[n] = {"id": got[0]["username"], "display": got[0].get("name") or got[0]["username"]}
        return out

    def pages(self, path, params):
        out, page = [], 1
        while True:
            q = dict(params, per_page=self.PER_PAGE, page=page)
            got = self.get("%s%s?%s" % (self.api_url, path, urllib.parse.urlencode(q))) or []
            out += got
            if len(got) < self.PER_PAGE:
                return out
            page += 1

    def fetch_issues(self, since, until, user_ids):
        found = {}
        for proj in self.repos:
            for user in [u for u in user_ids if u]:
                got = self.pages("/projects/%s/issues" % _quote(proj), {
                    "assignee_username": user, "scope": "all",
                    "updated_after": "%sT00:00:00Z" % since, "updated_before": "%sT23:59:59Z" % until})
                for it in got:
                    key = "%s#%s" % (proj, it.get("iid"))
                    if key not in found:
                        found[key] = self.normalize(proj, it, user)
        return list(found.values())

    def normalize(self, proj, it, user):
        labels = [str(x) for x in it.get("labels") or []]
        people = [a for a in (it.get("assignees") or []) if isinstance(a, dict)] or \
            ([it["assignee"]] if isinstance(it.get("assignee"), dict) else [])
        a = next((p for p in people if p.get("username") == user), people[0] if people else {})
        return {"key": "%s#%s" % (proj, it.get("iid")), "title": str(it.get("title") or ""),
                "status": str(it.get("state") or ""), "type": self.type_of(labels, str(it.get("issue_type") or "issue")),
                "created": day(it.get("created_at")), "updated": day(it.get("updated_at")), "resolved": day(it.get("closed_at")),
                "labels": labels, "assignee": {"id": a.get("username") or "", "display": a.get("name") or a.get("username") or ""},
                "url": it.get("web_url") or "", "comments": self.notes(proj, it)}

    def notes(self, proj, it):
        if not int(it.get("user_notes_count") or 0):
            return []
        got = self.pages("/projects/%s/issues/%s/notes" % (_quote(proj), it.get("iid")), {"sort": "asc"})
        return [{"author_id": (n.get("author") or {}).get("username") or "", "created": day(n.get("created_at")),
                 "body": str(n.get("body") or "")} for n in got if not n.get("system")]


# ---------------------------------------------------------------- 고르기

TYPES = {"none": Tracker, "jira": JiraTracker, "github": GitHubTracker, "gitlab": GitLabTracker}


def make(tcfg, full=None, fetch=None, token=None):
    """ai_share.tracker 갈래 → 어댑터. 모르는 type 이면 none."""
    tcfg = tcfg or {}
    kind = str(tcfg.get("type") or "none").strip().lower()
    return TYPES.get(kind, Tracker)(tcfg, full, fetch, token)


def basic_header(user, token):
    return "Basic " + base64.b64encode(("%s:%s" % (user, token)).encode("utf-8")).decode("ascii")
