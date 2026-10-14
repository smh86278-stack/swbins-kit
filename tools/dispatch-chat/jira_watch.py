# -*- coding: utf-8 -*-
"""
Jira 새 티켓 감시 — 디스패치 대화 앱 안의 기능(설정 화면 스위치, 기본 꺼짐).

내게 배정된 새 Jira 접수건을 1분마다 확인한다.
- 자리비움 켜짐 → 새 티켓마다 '/jira 키' 작업을 하나씩 넣어 자동으로 처리시킨다(쓰기 모드, Jira 도구 · 밖으로 내보내는 명령은 거부).
  작업은 이 메신저의 작업 큐(설정 '이 PC 에서 직접 실행' 이 켜진 PC)에 '#cw /jira 키' 와 같은 작업으로 넣는다.
- 게이트웨이 PC(키트 공통 설정의 계정을 쓰거나 이 저장소의 키트 게이트웨이가 켜진 PC)에서는 켜지지 않는다 — 그 PC 에선 키트의
  jira-watch.py(config.local.json 의 jira 갈래)가 새 이슈를 묻고 처리한다. 두 감시가 같이 돌면 같은 이슈가 두 번 처리된다.
- 자리비움 꺼짐 → 실행하지도 묻지도 않고 '처리됨'으로만 적는다(나중에 켰을 때 몰려 실행되지 않게).
  대신 화면에 '새 티켓 N건 — 자리비움 꺼짐이라 직접 처리' 를 작게 띄운다.
- 처음 켤 때는 지금 있는 티켓을 '본 것'으로만 적는다(seed).

설정(메신저 설정 파일): jira_watch(켜짐) · jira_away(자리비움) · jira_watch_project · jira_watch_assignee · jira_watch_days ·
jira_watch_max · jira_watch_exclude_account · jira_watch_exclude_linked · jira_watch_ignore.
Jira 주소·토큰·작업 폴더·스킬은 직접 실행의 Jira 칸(run_jira_url · run_jira_token_enc · run_jira_dir · run_jira_skill)을 같이 쓴다.
토큰이 없으면 환경변수 JIRA_TOKEN. 회사마다 다른 제외 규칙은 company.json 에 둔다(코드 기본값은 비어 있다).

상태: 실행기 폴더(runner/)의 jira-watch.json — 처리한 티켓 · 마지막 결과 · 화면 알림. 표준 라이브러리만 쓴다.
"""
import json
import os
import random
import re
import ssl
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

ACCOUNT_RE = re.compile(r"\*?\s*계정\s*\*?\s*:\s*\*?\s*([A-Za-z0-9_.\-]+)")
PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
ASSIGNEE_RE = re.compile(r"^[\w.@-]{1,64}$")
KEY_NUM_RE = re.compile(r"\d+")
PROCESSED_KEEP = 2000
NOTE_KEEP = 20
RECENT_KEEP = 15
MIN_INTERVAL = 30


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-%04x" % random.randrange(0x10000)


# ----------------------------------------------------------------- 규칙 · Jira 조회(옛 폴러와 같은 정책)

def rules_of(cfg):
    """설정 → 감시 규칙. 프로젝트는 비우면 Jira 키 앞부분(PROJ- → PROJ), 담당자는 비우면 토큰 주인(currentUser())."""
    def num(k, d, lo, hi):
        try:
            return max(lo, min(hi, int(cfg.get(k) or d)))
        except (TypeError, ValueError):
            return d
    ignore = cfg.get("jira_watch_ignore") or []
    if isinstance(ignore, str):
        ignore = re.split(r"[\s,]+", ignore)
    return {
        "project": str(cfg.get("jira_watch_project") or str(cfg.get("jira_prefix") or "").strip().rstrip("-")).strip().upper(),
        "assignee": str(cfg.get("jira_watch_assignee") or "").strip(),
        "days": num("jira_watch_days", 3, 1, 30),
        "max": num("jira_watch_max", 3, 1, 10),
        "interval": num("jira_watch_sec", 60, MIN_INTERVAL, 3600),
        "exclude_account": str(cfg.get("jira_watch_exclude_account") or ""),
        "exclude_linked": str(cfg.get("jira_watch_exclude_linked") or ""),
        "ignore": sorted({m for k in ignore for m in KEY_NUM_RE.findall(str(k))}),
    }


def build_jql(rules, today=None):
    since = ((today or datetime.now()) - timedelta(days=rules["days"])).strftime("%Y-%m-%d")
    who = rules["assignee"] or "currentUser()"
    if not who.endswith("()"):
        who = '"%s"' % who
    parts = (['project = "%s"' % rules["project"]] if rules["project"] else []) + \
        ["assignee = %s" % who, 'created >= "%s"' % since]
    return " AND ".join(parts) + " ORDER BY created ASC"


def ssl_ctx(ca=None):
    ctx = ssl.create_default_context()
    try:
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    except Exception:
        pass
    if ca and os.path.isfile(ca):                     # 사내 TLS 검사 프록시의 루트 인증서(설정 ca_bundle) — 없으면 기본
        try:
            ctx.load_verify_locations(ca)
        except Exception:
            pass
    return ctx


def http_get_json(url, token, ca=None):
    """Jira REST 읽기 한 번(시험에서는 이것만 바꿔 끼운다)."""
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60, context=ssl_ctx(ca)) as r:
        return json.loads(r.read().decode("utf-8"))


def jira_search(base, token, jql, ca=None):
    qs = urllib.parse.urlencode({"jql": jql, "fields": "key,summary,created,status,reporter,description,issuelinks",
                                 "maxResults": "200"})
    data = http_get_json(base.rstrip("/") + "/rest/api/2/search?" + qs, token, ca)
    out = []
    for it in data.get("issues") or []:
        f = it.get("fields") or {}
        rep = f.get("reporter") or {}
        out.append({
            "key": it["key"], "num": it["key"].split("-")[-1],
            "created": (f.get("created") or "")[:10],
            "status": (f.get("status") or {}).get("name", ""),
            "summary": (f.get("summary") or "").strip(),
            "reporter": rep.get("name", ""), "reporter_name": rep.get("displayName", ""),
            "account": account_of(f.get("description") or ""),
            "links": linked_titles(f.get("issuelinks")),
        })
    return out


def linked_titles(issuelinks):
    out = []
    for link in issuelinks or []:
        other = link.get("outwardIssue") or link.get("inwardIssue") or {}
        title = ((other.get("fields") or {}).get("summary") or "").strip()
        if title:
            out.append(title)
    return out


def account_of(description):
    m = ACCOUNT_RE.search(description or "")
    return m.group(1) if m else ""


def skip_reason(issue, rules):
    """자동화 대상에서 뺄 이유. 처리해야 할 건이면 None."""
    apat = rules.get("exclude_account")
    if apat and issue.get("account") and re.search(apat, issue["account"]):
        return "제외(계정)"
    lpat = rules.get("exclude_linked")
    if lpat:
        for title in issue.get("links") or []:
            if re.search(lpat, title):
                return "제외(연결 이슈)"
    return None


# ----------------------------------------------------------------- 감시

class JiraWatch:
    def __init__(self, runner):
        self.R = runner
        self.C = runner.C
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.force = False
        self.last_try = 0.0
        self.busy = False
        self.started = False
        self._logged_err = ""

    @property
    def path(self):
        return os.path.join(self.R.root, "jira-watch.json")

    # ---------- 상태 파일

    def state(self):
        st = self.C.read_json(self.path)
        st = st if isinstance(st, dict) else {}
        st.setdefault("processed", [])
        st.setdefault("note", [])
        st.setdefault("recent", [])
        return st

    def save(self, st):
        with self.lock:
            st["processed"] = list(dict.fromkeys(st.get("processed") or []))[-PROCESSED_KEEP:]
            st["note"] = (st.get("note") or [])[-NOTE_KEEP:]
            st["recent"] = (st.get("recent") or [])[-RECENT_KEEP:]
            self.C.write_json(self.path, st)

    # ---------- 어디에 넣나 · 무엇으로 조회하나

    def blocked(self, cfg, src):
        """켤 수 없는 이유(없으면 ""). 게이트웨이 PC(키트 설정의 계정을 쓰거나 이 저장소의 키트 게이트웨이가 켜진 PC)에선
        키트의 jira-watch.py(config.local.json 의 jira 갈래, 허브 svc_jira_watch)가 새 이슈를 맡는다 — 이 감시까지 돌면 같은 이슈가
        두 번 처리되고, 여기서 넣은 작업은 키트 게이트웨이가 회신하지 않는 모양이라 켜지 않는다."""
        if src == "kit" or self.R.gateway_here():
            return ("이 PC 는 키트 메일 게이트웨이 PC 입니다 — Jira 새 이슈 감시는 키트의 jira-watch.py(config.local.json 의 jira 갈래, "
                    "허브 「상시 서비스」의 Jira 감시)가 맡습니다. 같은 이슈가 두 번 처리되지 않게 여기서는 켤 수 없습니다.")
        return ""

    def target(self, cfg, src):
        """('here'|'', 작업 폴더). 이 PC 에서 직접 실행이 켜져 있어야 넣을 곳이 있다(게이트웨이 PC 에선 blocked)."""
        if self.blocked(cfg, src):
            return "", ""
        if cfg.get("run_here") and not self.R.blocked(cfg, src):
            return "here", self.R.jobs_dir
        return "", ""

    def token(self, cfg):
        enc = cfg.get("run_jira_token_enc")
        if enc:
            try:
                return self.C.unprotect_secret(enc), "saved"
            except Exception:
                pass
        env = os.environ.get("JIRA_TOKEN", "").strip()
        return (env, "env") if env else ("", "")

    def ca_bundle(self, cfg):
        """사내 TLS 검사 프록시의 루트 인증서(.pem) — 메일과 같은 설정(ca_bundle). 없으면 ""(기본 인증서)."""
        return os.path.expandvars(str(cfg.get("ca_bundle") or "").strip())

    # ---------- 작업 넣기

    def cost_block(self, cfg, where, jobs):
        """하루 비용 한도에 닿았으면 이유(''이면 넣어도 됨). 이 PC 의 작업 큐와 메신저 설정(daily_cost_usd)으로 센다."""
        from chat_runner import cost_limit, spent_today
        limit = cost_limit(cfg)
        if limit <= 0:
            return ""
        spent = spent_today(jobs or self.R.jobs_dir)
        return "오늘 쓴 비용($%.2f)이 하루 한도($%.2f)에 닿아" % (spent, limit) if spent >= limit else ""

    def queue_here(self, issue, cfg):
        """이 메신저의 작업 큐에 — '#cw /jira 키' 를 받았을 때와 같은 도구·거부 목록·스킬. 확인을 묻지 않고 바로 대기(자리비움 중이라)."""
        R = self.R
        prompt, wd, label, tools, denied = R.jira_parts(cfg, issue["key"], cfg.get("run_workdir") or "", "default")
        tag = (cfg.get("write_tags") or ["#cw"])[0]
        job = {"id": new_id(), "created_at": now_text(), "prompt": prompt, "workdir": wd, "workdir_label": label,
               "status": "queued", "started_at": None, "finished_at": None, "result": None, "error": None,
               "denials": [], "cost_usd": None, "duration_ms": None, "source": "jira-watch", "runner": "chat",
               "mail_msgid": None, "mail_subject": ("%s [Jira 자동화] %s %s" % (tag, issue["key"], issue["summary"]))[:180],
               "mail_from": None, "replied": False, "mode": "write", "chat": True,
               "client": "jira", "acked": True,             # 지시 메일이 없다 — 접수 신호 없이 회신만 간다
               "allowed_tools": list(tools), "jira_key": issue["key"], "jira_summary": issue["summary"]}
        if denied:
            job["disallowed_tools"] = list(denied)
        if not os.path.isdir(wd or ""):
            job.update(status="error", error="작업 폴더를 찾을 수 없습니다: %s — ⚙ 설정에서 Jira 작업 폴더를 확인하세요." % wd,
                       finished_at=now_text())
        R.write_job(job)
        R.kick.set()
        return job

    # ---------- 한 번 확인

    def poll(self, cfg, src, dry=False):
        """Jira 를 한 번 조회해 새 티켓을 처리한다. dry 면 아무것도 바꾸지 않고 대상만 돌려준다."""
        C = self.C
        url = str(cfg.get("run_jira_url") or "").strip()
        token, _how = self.token(cfg)
        if not url:
            raise ValueError("Jira 주소가 없습니다 — ⚙ 설정의 Jira 주소를 넣어 주세요.")
        if not token:
            raise ValueError("Jira 토큰이 없습니다 — ⚙ 설정에 개인 토큰을 넣거나 환경변수 JIRA_TOKEN 을 두세요.")
        rules = rules_of(cfg)
        issues = jira_search(url, token, build_jql(rules), self.ca_bundle(cfg))
        reasons = {i["key"]: skip_reason(i, rules) for i in issues}
        tally = {}
        for r in reasons.values():
            if r:
                tally[r] = tally.get(r, 0) + 1
        why = " · ".join("%s %d" % kv for kv in sorted(tally.items())) or "없음"
        st = self.state()
        processed = set(st["processed"])
        ignore = set(rules["ignore"])
        fresh = [i for i in issues if not reasons[i["key"]] and i["key"] not in processed and i["num"] not in ignore]
        res = {"ts": now_text(), "scanned": len(issues), "qc_skipped": sum(tally.values()), "skipped": tally,
               "queued": [], "away_skipped": [], "cost_skipped": [], "seeded": [], "dry": bool(dry)}
        if dry:
            res["fresh"] = [i["key"] for i in fresh]
            res["candidates"] = [i["key"] for i in issues if not reasons[i["key"]]]
            return res

        def mark(keys):
            st["processed"] = list(st["processed"]) + [k for k in keys if k not in processed]
            processed.update(keys)
            self.save(st)

        if not st.get("seeded"):
            # 처음 — 지금 있는 티켓은 실행 없이 본 것으로만
            st["seeded"] = now_text()
            mark([i["key"] for i in fresh])
            res["seeded"] = [i["key"] for i in fresh]
            C.log("[Jira 감시] 처음 확인 %d건 (제외 %d — %s) — %d건을 실행 없이 본 것으로 적었습니다"
                  % (len(issues), res["qc_skipped"], why, len(fresh)))
        elif not fresh:
            pass
        elif not cfg.get("jira_away"):
            # 자리비움 꺼짐 — 실행도 묻지도 않는다. 나중에 켰을 때 몰려 돌지 않게 처리됨으로만 적고, 화면에 작게 알린다
            mark([i["key"] for i in fresh])
            res["away_skipped"] = [i["key"] for i in fresh]
            stamp = now_text()
            st["note"] = list(st["note"]) + [{"key": i["key"], "summary": i["summary"][:80], "ts": stamp} for i in fresh]
            st["recent"] = list(st["recent"]) + [{"key": i["key"], "summary": i["summary"][:80], "ts": stamp, "act": "skip"} for i in fresh]
            C.log("[Jira 감시] 새 티켓 %d건 — 자리비움 꺼짐이라 실행하지 않고 처리됨으로 적었습니다: %s"
                  % (len(fresh), ", ".join(res["away_skipped"])))
        else:
            where, jobs = self.target(cfg, src)
            if not where:
                raise ValueError("자리비움 중인데 작업을 넣을 곳이 없습니다 — ⚙ 설정에서 '이 PC 에서 직접 실행' 을 켜 주세요.")
            why = self.cost_block(cfg, where, jobs)
            if why:
                # 하루 비용 한도 — 넣지 않고 처리됨으로만(내일 몰려 돌지 않게), 화면에 이유와 함께 알린다
                mark([i["key"] for i in fresh])
                res["cost_skipped"] = [i["key"] for i in fresh]
                stamp = now_text()
                st["note"] = list(st["note"]) + [{"key": i["key"], "summary": i["summary"][:80], "ts": stamp, "why": "비용 한도"}
                                                 for i in fresh]
                st["recent"] = list(st["recent"]) + [{"key": i["key"], "summary": i["summary"][:80], "ts": stamp, "act": "cost"}
                                                     for i in fresh]
                C.log("[Jira 감시] 새 티켓 %d건 — %s 처리됨으로만 적었습니다: %s" % (len(fresh), why, ", ".join(res["cost_skipped"])))
                fresh = []
            for i in fresh[:rules["max"]]:
                mark([i["key"]])                          # 넣기 전에 먼저 적는다 — 중간에 죽어도 같은 티켓이 두 번 들어가지 않게
                job = self.queue_here(i, cfg)
                res["queued"].append(i["key"])
                st["recent"] = list(st["recent"]) + [{"key": i["key"], "summary": i["summary"][:80], "ts": now_text(),
                                                      "act": "queued", "job": job["id"], "where": where}]
                C.log("[Jira 감시] 자리비움 중 — %s 자동 처리 작업을 넣었습니다(%s, 작업 %s)"
                      % (i["key"], "이 PC", job["id"]))
        st["last"] = res
        st["last_ok"] = res["ts"]
        st["error"] = ""
        self.save(st)
        return res

    def tick(self):
        """주기마다 — 켜져 있고 때가 됐으면 한 번 확인. 실패는 상태에 적고(같은 오류는 로그에 한 번만) 다음 주기에 다시."""
        cfg, src = self.C.load_cfg()
        if not cfg.get("jira_watch") or self.blocked(cfg, src):
            return None
        if not self.force and time.time() - self.last_try < rules_of(cfg)["interval"]:
            return None
        self.force = False
        self.last_try = time.time()
        self.busy = True
        try:
            res = self.poll(cfg, src)
            self._logged_err = ""
            return res
        except Exception as e:
            msg = str(e)[:300] or e.__class__.__name__
            st = self.state()
            st["error"] = msg
            st["error_at"] = now_text()
            self.save(st)
            if msg != self._logged_err:
                self._logged_err = msg
                self.C.log("[Jira 감시] 확인 실패 — %s" % (msg if isinstance(e, ValueError) else traceback.format_exc(limit=2)))
            return None
        finally:
            self.busy = False

    def loop(self):
        while True:
            try:
                self.tick()
            except Exception:
                self.C.log("[Jira 감시] 실패 — %s" % traceback.format_exc(limit=3))
            self.wake.wait(5)
            self.wake.clear()

    def start(self):
        if not self.started:
            self.started = True
            threading.Thread(target=self.loop, daemon=True, name="jira-watch").start()

    # ---------- 설정 · 화면

    def configure(self, data):
        C = self.C
        own = C.read_json(C.OWN_CFG) or {}
        cfg, src = C.load_cfg()
        why = self.blocked(cfg, src)
        if why and (data.get("enabled") or data.get("away") or data.get("check_now")):
            raise ValueError(why)
        if "project" in data:
            p = str(data.get("project") or "").strip().upper().rstrip("-")
            if p and not PROJECT_RE.match(p):
                raise ValueError("Jira 프로젝트는 영문 대문자·숫자로 넣어 주세요(예: PROJ): %s" % p)
            own["jira_watch_project"] = p
        if "assignee" in data:
            a = str(data.get("assignee") or "").strip()
            if a and a != "currentUser()" and not ASSIGNEE_RE.match(a):
                raise ValueError("담당자는 Jira 사용자 이름으로 넣어 주세요(비우면 토큰 주인): %s" % a)
            own["jira_watch_assignee"] = "" if a == "currentUser()" else a
        for k, key, lo, hi in (("days", "jira_watch_days", 1, 30), ("max", "jira_watch_max", 1, 10)):
            if k in data and str(data.get(k) or "").strip():
                try:
                    v = int(data[k])
                except (TypeError, ValueError):
                    raise ValueError("숫자로 넣어 주세요: %s" % data[k])
                own[key] = max(lo, min(hi, v))
        for k, key in (("exclude_account", "jira_watch_exclude_account"), ("exclude_linked", "jira_watch_exclude_linked")):
            if k in data:
                pat = str(data.get(k) or "").strip()
                try:
                    re.compile(pat)
                except re.error as e:
                    raise ValueError("제외 규칙(정규식)이 올바르지 않습니다: %s — %s" % (pat, e))
                own[key] = pat
        if "ignore" in data:
            raw = data.get("ignore")
            items = raw if isinstance(raw, list) else re.split(r"[\s,]+", str(raw or ""))
            own["jira_watch_ignore"] = [str(x).strip() for x in items if str(x).strip()]
        if "away" in data:
            want = bool(data.get("away"))
            if want != bool(own.get("jira_away")):
                own["jira_away"] = want
                C.log("[Jira 감시] 자리비움 %s (화면에서)" % ("켬 — 새 티켓을 자동으로 처리합니다" if want
                                                         else "끔 — 새 티켓은 처리됨으로만 적고 실행하지 않습니다"))
        if "enabled" in data:
            want = bool(data.get("enabled"))
            if want and not own.get("jira_watch"):
                trial = dict(cfg, **own)
                if not str(trial.get("run_jira_url") or "").strip():
                    raise ValueError("Jira 주소를 먼저 넣어 주세요(위 'Jira 처리' 칸).")
                if not self.token(trial)[0]:
                    raise ValueError("Jira 토큰이 없습니다 — 위 'Jira 처리' 칸에 개인 토큰을 넣거나 환경변수 JIRA_TOKEN 을 두세요.")
                own["jira_watch"] = True
                self.force = True
                C.log("[Jira 감시] 켰습니다 — 1분마다 내게 배정된 새 티켓을 봅니다(자리비움 %s)" % ("켜짐" if own.get("jira_away") else "꺼짐"))
            elif not want and own.get("jira_watch"):
                own["jira_watch"] = False
                C.log("[Jira 감시] 껐습니다")
        C.write_json(C.OWN_CFG, own)
        if data.get("dismiss"):
            st = self.state()
            st["note"] = []
            self.save(st)
        if data.get("check_now"):
            self.force = True
        self.wake.set()
        return self.info()

    def summary(self):
        """대화 목록 위 자리비움 줄(/api/state)."""
        cfg, src = self.C.load_cfg()
        why = self.blocked(cfg, src)
        if why:
            return {"on": False, "away": False, "blocked": why}
        if not cfg.get("jira_watch"):
            return {"on": False, "away": bool(cfg.get("jira_away"))}
        st = self.state()
        return {"on": True, "away": bool(cfg.get("jira_away")), "error": st.get("error") or "",
                "last_ok": st.get("last_ok") or "", "note": st.get("note") or []}

    def info(self):
        cfg, src = self.C.load_cfg()
        st = self.state()
        rules = rules_of(cfg)
        where, jobs = self.target(cfg, src)
        _tok, how = self.token(cfg)
        return {"enabled": bool(cfg.get("jira_watch")), "away": bool(cfg.get("jira_away")), "blocked": self.blocked(cfg, src),
                "project": cfg.get("jira_watch_project") or "", "project_default": rules["project"],
                "assignee": cfg.get("jira_watch_assignee") or "", "days": rules["days"], "max": rules["max"],
                "exclude_account": rules["exclude_account"], "exclude_linked": rules["exclude_linked"],
                "ignore": ", ".join(str(x) for x in (cfg.get("jira_watch_ignore") or [])),
                "url": cfg.get("run_jira_url") or "", "token": how, "where": where, "jobs_dir": jobs,
                "jql": build_jql(rules), "busy": self.busy,
                "last": st.get("last") or {}, "last_ok": st.get("last_ok") or "", "error": st.get("error") or "",
                "seeded": st.get("seeded") or "", "imported": st.get("imported") or {},
                "processed": len(st.get("processed") or []), "recent": list(reversed(st.get("recent") or [])),
                "note": st.get("note") or []}
