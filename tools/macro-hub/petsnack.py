"""화면 펫 간식 — 자동화 말고 두 갈래를 더 찾는다. 바깥 호출·AI 호출 없음.

- AI 커밋: 내 커밋 중 Claude 와 함께 쓴 것(메시지 끝 'Co-Authored-By: Claude …'). git log 만 — AI 작업 회고(ai_share)가 보는 레포 + 허브 레포.
- 좋은 프롬프트: Claude Code 세션(~/.claude/projects/*/*.jsonl)의 첫 프롬프트가 회고 규칙 점검(prompt_rules)을 💡 없이 통과.
  대화 기록은 앞부분(사람이 친 프롬프트 두 개)까지만 읽고, 한 번 본 세션은 다시 안 읽는다. claude -p(sdk) 세션은 사람이 친 게 아니라 뺀다.
세는 규칙(한도·중복·7일)은 petgrow.on_extra. 여기는 찾기만.
"""
import datetime
import glob
import importlib.util
import json
import os
import re
import subprocess
from contextlib import nullcontext

import plat

AI_TRAILER_RE = re.compile(r'(?im)^[ \t]*co-authored-by:[^\n]*\b(?:claude|anthropic)\b')
LOG_FMT = '%x1e%H%x00%at%x00%ae%x00%an%x00%s%x00%B'
SETTLE = 30 * 60              # 프롬프트가 하나뿐인 세션은 이만큼 조용해야 판정(바로 다음에 고쳐 말할 수 있어서)


def is_ai_commit(body):
    """커밋 메시지에 Claude 공동작성 꼬리말이 있나(줄 맨 앞 Co-Authored-By: … Claude/Anthropic)."""
    return bool(AI_TRAILER_RE.search(body or ''))


def parse_log(text):
    """git log --format=LOG_FMT 출력 → [{sha, at, email, name, subject, body}]."""
    out = []
    for rec in (text or '').split('\x1e'):
        parts = rec.strip('\n').split('\x00', 5)
        if len(parts) < 6 or not parts[0]:
            continue
        sha, at, email, name, subject, body = parts
        try:
            at = int(at)
        except ValueError:
            continue
        out.append({'sha': sha.strip(), 'at': at, 'email': email.strip(), 'name': name.strip(),
                    'subject': subject.strip(), 'body': body})
    return out


def _git(args, cwd, timeout=30):
    r = subprocess.run(['git', '-c', 'i18n.logOutputEncoding=utf-8', *args], cwd=cwd, capture_output=True,
                       timeout=timeout, **plat.bg())
    return r.stdout.decode('utf-8', 'replace') if r.returncode == 0 else ''


def my_authors(repo, extra=()):
    """내 git 이름·이메일(소문자) — 그 레포의 user.name·user.email(없으면 전역) + 설정의 이름."""
    names = {str(x).strip().lower() for x in extra if str(x).strip()}
    for key in ('user.name', 'user.email'):
        try:
            v = _git(['config', key], repo, 10).strip()
        except (OSError, subprocess.SubprocessError):
            v = ''
        if v:
            names.add(v.lower())
    return names


def ai_commits(log_text, authors):
    """git log 출력에서 내(authors) Claude 공동작성 커밋만. authors 가 비면 아무것도 안 센다(누구 것인지 모르니)."""
    return [c for c in parse_log(log_text)
            if authors and (c['email'].lower() in authors or c['name'].lower() in authors) and is_ai_commit(c['body'])]


def commit_keys(c):
    """같은 커밋을 가리키는 키 — 해시, 그리고 체리픽·리베이스로 해시만 바뀐 것(작성 시각+제목)."""
    return [c['sha'], 'p:%d|%s' % (c['at'], c['subject'][:120])]


def repo_commits(repo, since, authors, git=_git):
    """repo 에서 since(datetime) 뒤 내 AI 커밋. git 이 없거나 레포가 아니면 []."""
    try:
        text = git(['log', '--all', '--no-merges', '--since=' + since.strftime('%Y-%m-%d %H:%M:%S'),
                    '--format=' + LOG_FMT], repo)
    except (OSError, subprocess.SubprocessError):
        return []
    return ai_commits(text, authors)


def submodule_repos(root):
    """root(.gitmodules 가 있는 상위 레포)의 서브모듈 경로 중 git 레포인 것 — 회고 collect_git 과 같은 목록."""
    try:
        with open(os.path.join(root, '.gitmodules'), encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return []
    out = []
    for m in re.finditer(r'^\s*path\s*=\s*(.+)$', text, re.M):
        p = os.path.join(root, m.group(1).strip())
        if os.path.exists(os.path.join(p, '.git')):
            out.append(os.path.normpath(p))
    return out


def git_top(path):
    """path 를 품은 git 레포 맨 위(없으면 None)."""
    d = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(d, '.git')):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


# ---------------------------------------------------------------- 프롬프트
def load_rules(path):
    """AI 작업 회고의 prompt_rules.py 를 읽는다(규칙을 두 벌로 두지 않게). 없으면 None — 좋은 프롬프트는 안 센다."""
    try:
        spec = importlib.util.spec_from_file_location('prompt_rules_for_pet', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod if hasattr(mod, 'good_first') else None
    except (OSError, ImportError, SyntaxError, AttributeError):
        return None


def default_dirs(home=None):
    """Claude Code 대화 기록 폴더들 — ~/.claude/projects/* (임시 폴더에서 연 세션은 뺀다)."""
    base = os.path.join(home or os.path.expanduser('~'), '.claude', 'projects')
    return [d for d in glob.glob(os.path.join(base, '*')) if os.path.isdir(d) and '-AppData-Local-Temp' not in os.path.basename(d)]


def _when(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace('Z', '+00:00')).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def session_head(path, clean):
    """대화 기록 앞부분 → {first, next, when, sdk}. 사람이 친 프롬프트 두 개를 찾으면 멈춘다(회고 collect_prompts 와 같은 거르기)."""
    out = {'first': '', 'next': '', 'when': None, 'sdk': False}
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if '"type":"user"' not in line or '"promptSource":"system"' in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if str(rec.get('entrypoint') or '').startswith('sdk'):
                    out['sdk'] = True
                    return out
                content = (rec.get('message') or {}).get('content')
                if rec.get('isMeta') or rec.get('isSidechain') or not isinstance(content, str):
                    continue
                p = clean(content)
                if not p:
                    continue
                if not out['first']:
                    out['first'], out['when'] = p, _when(rec.get('timestamp', ''))
                else:
                    out['next'] = p
                    return out
    except OSError:
        pass
    return out


def judge_sessions(dirs, since_ts, seen, rules, now_ts, settle=SETTLE):
    """since_ts 뒤에 바뀐 세션 중 아직 안 본 것 → [(세션 id, 좋은가, 첫 프롬프트 시각)].
    프롬프트가 하나뿐이고 settle 안에 바뀐 세션은 다음에(고쳐 말할 수 있어서). 사람이 친 게 없거나 sdk 면 좋은가=False."""
    out = []
    for d in dirs:
        for f in glob.glob(os.path.join(d, '*.jsonl')):
            sid = os.path.splitext(os.path.basename(f))[0]
            if sid in seen:
                continue
            try:
                mt = os.path.getmtime(f)
            except OSError:
                continue
            if mt < since_ts:
                continue
            h = session_head(f, rules.clean_text)
            if not h['sdk'] and h['first'] and not h['next'] and now_ts - mt < settle:
                continue
            good = bool(not h['sdk'] and h['first'] and h['when'] and rules.good_first(h['first'], h['next']))
            out.append((sid, good, h['when'] or datetime.datetime.fromtimestamp(mt)))
    return out


# ---------------------------------------------------------------- 한 번 둘러보기 (허브가 10분마다)
def check_ai(g, repos, authors, now, on_extra, git=_git, log=print, guard=None):
    """repos 의 내 AI 커밋을 세어 g 에 더한다 → (얻은 간식, 레벨이 올랐나). 처음이면 지난 SEED_DAYS 일로 채우고 로그를 남긴다.
    guard = g 를 바꾸는 동안만 잡을 잠금(git 을 도는 동안은 안 잡는다)."""
    from petgrow import SEED_DAYS
    xc = g.setdefault('xcheck', {})
    first = 'ai' not in xc
    floor = now - datetime.timedelta(days=SEED_DAYS)
    since = floor if first else max(floor, datetime.datetime.fromtimestamp(xc['ai']) - datetime.timedelta(days=1))
    found = [c for repo in repos for c in repo_commits(repo, since, authors, git)]
    gained, up = 0, False
    with guard or nullcontext():
        for c in sorted(found, key=lambda c: c['at']):
            n, u = on_extra(g, 'ai', commit_keys(c), datetime.datetime.fromtimestamp(c['at']), now)
            gained, up = gained + n, up or u
        xc['ai'] = now.timestamp()
    if first:
        g.setdefault('seed_log', {})['ai'] = {'at': now.strftime('%Y-%m-%d %H:%M'), 'snacks': gained, 'repos': len(repos)}
        log('펫 간식: AI 커밋 처음 채움 — 지난 %d일 %d개(레포 %d)' % (SEED_DAYS, gained, len(repos)))
    return gained, up


def check_prompts(g, dirs, rules, now, on_extra, mark, log=print, guard=None):
    """좋은 프롬프트를 세어 g 에 더한다 → (얻은 간식, 레벨이 올랐나). 판정한 세션은 좋든 아니든 기억해 다시 안 읽는다."""
    from petgrow import SEED_DAYS
    xc = g.setdefault('xcheck', {})
    first = 'prompt' not in xc
    floor = now - datetime.timedelta(days=SEED_DAYS)
    since = floor if first else max(floor, datetime.datetime.fromtimestamp(xc['prompt']) - datetime.timedelta(hours=1))
    seen = (g.get('xseen') or {}).get('prompt') or {}
    found = sorted(judge_sessions(dirs, since.timestamp(), dict(seen), rules, now.timestamp()), key=lambda x: x[2])
    gained, up = 0, False
    with guard or nullcontext():
        for sid, good, when in found:
            if good:
                n, u = on_extra(g, 'prompt', [sid], when, now)
                gained, up = gained + n, up or u
            else:
                mark(g, 'prompt', sid, when)
        xc['prompt'] = now.timestamp()
    if first:
        g.setdefault('seed_log', {})['prompt'] = {'at': now.strftime('%Y-%m-%d %H:%M'), 'snacks': gained, 'dirs': len(dirs)}
        log('펫 간식: 좋은 프롬프트 처음 채움 — 지난 %d일 %d개(폴더 %d)' % (SEED_DAYS, gained, len(dirs)))
    return gained, up


def pause(g, src, now):
    """그 갈래를 꺼 둔 동안 — 이미 센 적이 있으면 기준 시각만 옮겨, 다시 켰을 때 꺼 둔 동안 것을 한꺼번에 세지 않게."""
    xc = g.setdefault('xcheck', {})
    if src in xc:
        xc[src] = now.timestamp()
