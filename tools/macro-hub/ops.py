# -*- coding: utf-8 -*-
"""운영 화면(/ops)의 '현황' 데이터 — 화면은 macrohub 가 그린다(web\ops.html).

    import ops
    ops.features_status()      기능별 상태(정기 메일·폴더 정리·감시·PC 점검·백업) — kit.read_status
    ops.settings_status()      메일 설정 준비 여부 · 설정 파일 위치(보기 전용)
    ops.agent_board()          Claude 디스패치 보드(보기 전용)
    ops.agent_verify()         공식 CLI(claude agents --json)로 대조 — 약 4초
    ops.agent_view(verify)     보드 + 화면에 바로 쓰는 값(배지·몇 분 전)

함수는 모두 JSON 으로 바로 내보낼 수 있는 dict 를 돌려준다. 파일 읽기뿐이라 수 ms.

  - 상태 파일은 BOM 이 붙어 있어도 읽는다.
  - 대화형 세션 생존 확인을 PowerShell(Get-Process) 대신 OpenProcess 로 한다 — 1초 → 수 ms.
  - 이 PC 에서만 허용하는 검사는 웹 쪽 일이다 — 허브는 127.0.0.1 에만 열리고 실행 요청에 토큰을 요구한다.
"""
import ctypes
import datetime
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))          # 저장소 맨 위
NO_WINDOW = 0x08000000
KST = datetime.timezone(datetime.timedelta(hours=9))             # 시간대 없는 시각은 한국 시간으로 본다

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import extsvc  # noqa: E402  (system_python · fresh_env 재사용)


# ---------------------------------------------------------------- 공통 도우미

def _read_json(path):
    """JSON 파일을 dict/list 로. 없거나 깨졌으면 None (PHP 의 json_decode(@file_get_contents) 와 같은 자리)."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError):
        return None


def _php_int(v):
    """PHP 의 (int) 캐스트 흉내 — '12abc' → 12, 'abc' → 0, 3.9 → 3, None → 0."""
    if v is None or v is False:
        return 0
    if v is True:
        return 1
    if isinstance(v, (int, float)):
        try:
            return int(v)
        except (OverflowError, ValueError):
            return 0
    m = re.match(r'\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)', str(v))
    if not m:
        return 0
    try:
        return int(float(m.group(1)))
    except (OverflowError, ValueError):
        return 0


def _empty(v):
    """PHP empty() — None · '' · '0' · 0 · [] · {} · False 는 비었다."""
    return v is None or v is False or v == '' or v == '0' or v == 0 or v == [] or v == {}


def _strtotime(s):
    """ISO 시각 문자열 → 유닉스 초. 시간대가 없으면 KST 로 본다(PHP 설정과 같다). 못 읽으면 None."""
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith('Z') or t.endswith('z'):
        t = t[:-1] + '+00:00'
    # 3.10 의 fromisoformat 은 소수 자릿수가 3·6 이 아니면 못 읽는다 — 6자리로 맞춘다
    t = re.sub(r'\.(\d+)', lambda m: '.' + (m.group(1) + '000000')[:6], t, count=1)
    try:
        dt = datetime.datetime.fromisoformat(t.replace(' ', 'T', 1) if 'T' not in t else t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return int(dt.timestamp())


def _round_half_up(x):
    """PHP round() 는 .5 를 0 에서 먼 쪽으로 올린다(파이썬 round 는 짝수 쪽)."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def strimwidth(s, width, marker='…'):
    """PHP mb_strimwidth(s, 0, width, '…') — 한글 등 전각은 폭 2 로 센다. 화면용."""
    s = '' if s is None else str(s)

    def w(ch):
        return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1

    if sum(w(c) for c in s) <= width:
        return s
    limit = width - sum(w(c) for c in marker)
    out, used = [], 0
    for c in s:
        if used + w(c) > limit:
            break
        out.append(c)
        used += w(c)
    return ''.join(out) + marker


def ago_text(ts, now=None):
    """'3분 전' 처럼 상대 시각. 1분 안쪽은 '방금'."""
    if not ts:
        return '기록 없음'
    d = int((now if now is not None else time.time()) - int(ts))
    if d < 60:
        return '방금'
    if d < 3600:
        return '%d분 전' % (d // 60)
    if d < 86400:
        return '%d시간 전' % (d // 3600)
    return '%d일 전' % (d // 86400)


# ---------------------------------------------------------------- 기능 상태 · 설정

# '📊 기능 상태' 탭에 보이는 기능 — 각 매크로(macros\job_*.py)가 kit.write_status(기능, items) 로 남긴 상태 파일을 읽는다.
FEATURES = (
    ('scheduled_mail', '정기 메일'),
    ('tidy', '폴더 정리'),
    ('monitors', '사이트·서버 감시'),
    ('pc_watch', 'PC 디스크 감시'),
    ('backups', '폴더 백업'),
)


def _clean_item(it):
    if not isinstance(it, dict):
        return None
    ok = it.get('ok')
    return {'name': str(it.get('name') or ''), 'ok': ok if ok in (True, False) else None,
            'text': str(it.get('text') or '')}


def features_status(now=None):
    """기능별 상태 — [{feature, label, configured, updated, ago, note, items:[{name, ok, text}]}].
    상태 파일이 아직 없으면(한 번도 안 돌았거나 설정 안 됨) configured False · items []."""
    import kit
    now = now or time.time()
    out = []
    for feature, label in FEATURES:
        try:
            st = kit.read_status(feature)
        except Exception:
            st = None
        if not isinstance(st, dict):
            out.append({'feature': feature, 'label': label, 'configured': False, 'updated': None, 'ago': '',
                        'note': '', 'items': []})
            continue
        upd = st.get('updated') if isinstance(st.get('updated'), (int, float)) else None
        items = [x for x in (_clean_item(i) for i in (st.get('items') or []) if isinstance(st.get('items'), list)) if x]
        out.append({'feature': feature, 'label': label, 'configured': True, 'updated': upd,
                    'ago': ago_text(upd, now) if upd else '', 'note': str(st.get('note') or ''), 'items': items})
    return {'features': out}


def settings_status():
    """⚙ 설정(보기 전용) — 메일 준비 여부와 설정 파일 위치. 바꾸는 건 `python setup.py`."""
    import kit
    try:
        ready, why = kit.mail_ready()
    except Exception as e:
        ready, why = False, '%s: %s' % (type(e).__name__, e)
    try:
        company = kit.company_name()
    except Exception:
        company = ''
    return {'mailReady': bool(ready), 'mailWhy': why, 'company': company,
            'configPath': kit.F_CONFIG, 'configExists': os.path.isfile(kit.F_CONFIG),
            'setup': 'python "%s"' % os.path.join(ROOT, 'setup.py')}


# ---------------------------------------------------------------- Claude 디스패치 보드
#
# 공식 조회 명령은 `claude agents --json` 이지만 호출마다 약 4초가 걸린다. 그래서 평소에는 CLI 가 읽는 것과
# 같은 상태 파일을 직접 읽고(수 ms), CLI 호출은 사람이 'CLI 로 대조' 를 눌렀을 때만 한다(agent_verify).
#
#   ~/.claude/sessions/<pid>.json     대화형 세션 (이름 · busy/idle · cwd)
#   ~/.claude/daemon/roster.json      살아있는 백그라운드 워커 (pid · sessionId)
#   ~/.claude/jobs/<short>/state.json 백그라운드 잡 상태 · 진행 문구 · 막힌 이유 · 결과
#
# 내부 파일이라 Claude Code 가 올라가면 형식이 바뀔 수 있다. 그래서 파일이 없거나 파싱이 안 되면
# 조용히 빈 목록을 주지 않고 problems 에 담아 화면에 드러낸다. 여기서 잡을 띄우거나 지시를 넣지 않는다 — 보기 전용.

AGENT_DONE_KEEP_DAYS = 7          # 완료(done) 잡을 보드에 며칠까지 남길지. 넘긴 done 은 목록에서 접는다.


def claude_home():
    home = os.environ.get('USERPROFILE') or os.environ.get('HOME') or ''
    return home.rstrip('\\/') + os.sep + '.claude'


def claude_cli():
    """claude 실행 파일 — 네이티브 설치(~/.local/bin) 먼저, 없으면 npm 전역. 못 찾으면 None."""
    home = os.environ.get('USERPROFILE') or ''
    appdata = os.environ.get('APPDATA') or ''
    for c in (home + '\\.local\\bin\\claude.exe', appdata + '\\npm\\claude.cmd'):
        if c and os.path.exists(c):
            return c
    return None


def _pids_alive(pids):
    """살아있는 pid 집합. 접근 거부도 '있다'로 센다(PHP 는 Get-Process -Id 로 봤다)."""
    alive = set()
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    for pid in pids:
        h = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            if ctypes.get_last_error() == 5:                   # ERROR_ACCESS_DENIED — 있긴 하다
                alive.add(pid)
            continue
        code = ctypes.c_uint32()
        try:
            if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259:   # STILL_ACTIVE
                alive.add(pid)
        finally:
            k32.CloseHandle(h)
    return alive


def agent_board():
    """백그라운드 에이전트와 열려 있는 대화형 세션을 한 목록으로.

    {at(지금, 유닉스 초),
     items: [{id, kind('interactive'|'background'), name, sessionId, cwd, pid, startedAt, updatedAt(유닉스 초),
              state(interactive: busy|idle · background: working|blocked|done|idle), detail, needs, result,
              tokens, intent, alive(interactive: pid 생존 · background: 워커 살아있음)}]
            — 손봐야 할 것이 앞(작업 중 세션 → 작업 중/막힌 잡 → 대기 세션 → 완료 잡 → 닫힌 세션), 같은 묶음은 최근 갱신 순,
     summary: {busy, idle, working, blocked, done, closed, hiddenDone},
     hiddenDone(접은 오래된 완료 잡 수), doneKeepDays, problems:[읽지 못한 파일 등], cli(claude 실행 파일 | None)}
    """
    root = claude_home()
    problems, items = [], []

    def read_json(path):
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except OSError:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw.decode('utf-8-sig'))
        except (UnicodeDecodeError, ValueError):
            problems.append('%s/%s 를 읽지 못했습니다(형식 변경?)'
                            % (os.path.basename(os.path.dirname(path)), os.path.basename(path)))
            return None

    def listdir(d, pattern):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return []
        return [os.path.join(d, n) for n in names if re.fullmatch(pattern, n, re.I)]

    # 1) 대화형 세션
    sess_dir = root + '\\sessions'
    if not os.path.isdir(sess_dir):
        problems.append('sessions 폴더가 없습니다 — Claude Code 버전이 올라가 위치가 바뀐 것 같습니다.')
    for f in listdir(sess_dir, r'.*\.json'):
        if not os.path.isfile(f):
            continue
        s = read_json(f)
        if not isinstance(s, dict) or _empty(s.get('sessionId')):
            continue
        items.append({
            'id': str(s['pid']) if s.get('pid') is not None else os.path.basename(f)[:-5],
            'kind': 'interactive',
            'name': s['name'] if s.get('name') is not None else '(이름 없음)',
            'sessionId': s['sessionId'],
            'cwd': s['cwd'] if s.get('cwd') is not None else '',
            'pid': _php_int(s['pid']) if s.get('pid') is not None else None,
            'startedAt': _round_half_up(float(s['startedAt']) / 1000) if isinstance(s.get('startedAt'), (int, float)) else None,
            'updatedAt': _round_half_up(float(s['updatedAt']) / 1000) if isinstance(s.get('updatedAt'), (int, float)) else None,
            'state': s.get('status'),                           # busy | idle
            'detail': None, 'needs': None, 'result': None, 'tokens': None, 'intent': None,
            'alive': None,                                     # pid 확인 후 채운다
        })

    # 2) 살아있는 백그라운드 워커 — short id 로 잡 상태와 이어 붙인다
    roster = read_json(root + '\\daemon\\roster.json')
    live = {}
    if isinstance(roster, dict) and isinstance(roster.get('workers'), dict):
        for short, w in roster['workers'].items():
            live[str(short)] = _php_int(w['pid']) if isinstance(w, dict) and w.get('pid') is not None else None

    # 3) 백그라운드 잡. 끝난 잡의 상태 파일은 지워지지 않고 쌓이므로 done 은 최근 것만 남긴다.
    #    살아있는 워커는 done 으로 보여도 감추지 않는다 — 막 끝나 정리 전일 수 있다.
    now = int(time.time())
    hidden_done = 0
    jobs_dir = root + '\\jobs'
    try:
        job_names = sorted(os.listdir(jobs_dir))
    except OSError:
        job_names = []
    for short in job_names:
        f = os.path.join(jobs_dir, short, 'state.json')
        if not os.path.isfile(f):
            continue
        j = read_json(f)
        if not isinstance(j, dict) or not j:
            continue
        upd = _strtotime(j.get('updatedAt')) if not _empty(j.get('updatedAt')) else None
        st = j.get('state')
        if st == 'done' and short not in live and upd and now - upd > AGENT_DONE_KEEP_DAYS * 86400:
            hidden_done += 1
            continue
        out = j.get('output')
        items.append({
            'id': short,
            'kind': 'background',
            'name': j['name'] if not _empty(j.get('name')) else short,
            'sessionId': j['sessionId'] if j.get('sessionId') is not None else '',
            'cwd': j['cwd'] if j.get('cwd') is not None else '',
            'pid': live.get(short),
            'startedAt': _strtotime(j.get('createdAt')) if not _empty(j.get('createdAt')) else None,
            'updatedAt': upd,
            'state': st,                                       # working | blocked | done | idle
            'detail': j.get('detail'),
            'needs': j.get('needs'),
            'result': out.get('result') if isinstance(out, dict) else None,
            'tokens': _php_int(j['tokens']) if j.get('tokens') is not None else None,
            'intent': j.get('intent'),
            'alive': short in live,
        })

    # 4) 프로세스 생존 확인. 대기(idle) 세션은 상태 파일을 자주 갱신하지 않아 '파일이 오래됐다'로는
    #    끝난 세션을 가려낼 수 없다.
    pids = {it['pid'] for it in items if it['kind'] == 'interactive' and it['pid']}
    if pids:
        alive = _pids_alive(pids)
        for it in items:
            if it['kind'] == 'interactive' and it['pid']:
                it['alive'] = it['pid'] in alive

    # 5) 끝난 것은 뒤로, 손봐야 할 것은 앞으로. 같은 묶음 안에서는 최근 갱신 순.
    def rank(it):
        if it['kind'] == 'interactive':
            if it['alive'] is False:
                return 4                                       # 이미 닫힌 세션
            return 0 if it['state'] == 'busy' else 2
        if it['state'] in ('working', 'blocked'):              # 막힘도 손봐야 하니 위로
            return 1
        return 3                                               # done · idle
    items.sort(key=lambda it: (rank(it), -_php_int(it['updatedAt'])))

    # 6) 요약 — 배지용
    sm = {'busy': 0, 'idle': 0, 'working': 0, 'blocked': 0, 'done': 0, 'closed': 0, 'hiddenDone': hidden_done}
    for it in items:
        if it['kind'] == 'interactive':
            if it['alive'] is False:
                sm['closed'] += 1
            elif it['state'] == 'busy':
                sm['busy'] += 1
            else:
                sm['idle'] += 1
        else:
            if it['state'] == 'working':
                sm['working'] += 1
            elif it['state'] == 'blocked':
                sm['blocked'] += 1
            else:
                sm['done'] += 1

    return {
        'at': now,
        'items': items,
        'summary': sm,
        'hiddenDone': hidden_done,
        'doneKeepDays': AGENT_DONE_KEEP_DAYS,
        'problems': problems,
        'cli': claude_cli(),
    }


def agent_verify(timeout=60):
    """공식 명령(claude agents --json --all)으로 대조. 약 4초 — 사람이 눌렀을 때만 부른다.
    {ok, count(CLI 가 센 건수), names:['이름 · 상태', …], error(실패 이유 | None)}"""
    cli = claude_cli()
    if not cli:
        return {'ok': False, 'count': 0, 'names': [], 'error': 'claude 실행 파일을 찾지 못했습니다.'}
    try:
        r = subprocess.run([cli, 'agents', '--json', '--all'], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                           env=extsvc.fresh_env(), creationflags=NO_WINDOW)
        out = r.stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.TimeoutExpired):
        out = ''
    try:
        j = json.loads(out)
    except ValueError:
        j = None
    if isinstance(j, dict):
        j = list(j.values())
    if not isinstance(j, list):
        return {'ok': False, 'count': 0, 'names': [], 'error': 'CLI 응답을 해석하지 못했습니다.'}
    names = []
    for s in j:
        s = s if isinstance(s, dict) else {}
        state = s.get('state') if s.get('state') is not None else s.get('status')
        names.append('%s · %s' % (s.get('name') if s.get('name') is not None else '?',
                                  state if state is not None else '?'))
    return {'ok': True, 'count': len(j), 'names': names, 'error': None}


def agent_state_label(it):
    """상태 → (배지 클래스 'up'|'down'|'idle'|'none', 사람이 읽는 말)."""
    if it['kind'] == 'interactive':
        if it['alive'] is False:
            return 'none', '닫힌 세션'
        return ('up', '작업 중') if it['state'] == 'busy' else ('idle', '대기')
    st = it['state']
    if st == 'working':
        return 'up', '작업 중'
    if st == 'blocked':
        return 'down', '막힘'
    if st == 'done':
        return 'none', '완료'
    return 'none', '' if st is None else str(st)


def agent_view(verify=False, board=None):
    """디스패치 보드 화면에 바로 쓰는 값.

    agent_board() 의 모든 키 + 아래. items 의 각 항목에는 화면용 키를 덧붙인 사본이 들어간다.
      background / interactive : 종류별로 나눈 items (순서 유지)
        항목 추가 키 — badge(배지 클래스), label, updatedAgo, startedAgo('3분 전'),
                       intentShort(160폭) · detailShort · resultShort(200폭), orphan(막혔는데 워커 없음 → 이어받아야 함),
                       resume('claude --resume <sessionId>'), shortSession(sessionId 앞 8자)
      tally  : {active(작업 중 = busy+working), idle, blocked, done, closed, hiddenDone}
      verify : verify=True 일 때만 — agent_verify() 결과 + mismatch(CLI 건수 ≠ 화면 건수)
    화면은 30초마다 새로 읽되, 대조 결과를 보는 중에는 새로고침하지 않는 게 옛 동작이다.
    """
    b = dict(board or agent_board())
    now = b['at']
    view = []
    for it in b['items']:
        v = dict(it)
        v['badge'], v['label'] = agent_state_label(it)
        v['updatedAgo'] = ago_text(it['updatedAt'], now)
        v['startedAgo'] = ago_text(it['startedAt'], now)
        v['intentShort'] = strimwidth(it['intent'], 160) if it['intent'] else None
        v['detailShort'] = strimwidth(it['detail'], 200) if it['detail'] else None
        v['resultShort'] = strimwidth(it['result'], 200) if it['result'] else None
        v['orphan'] = it['kind'] == 'background' and it['state'] == 'blocked' and not it['alive']
        v['resume'] = 'claude --resume %s' % it['sessionId']
        v['shortSession'] = str(it['sessionId'])[:8]
        view.append(v)
    b['items'] = view
    b['background'] = [v for v in view if v['kind'] == 'background']
    b['interactive'] = [v for v in view if v['kind'] == 'interactive']
    sm = b['summary']
    b['tally'] = {'active': sm['busy'] + sm['working'], 'idle': sm['idle'], 'blocked': sm['blocked'],
                  'done': sm['done'], 'closed': sm['closed'], 'hiddenDone': sm['hiddenDone']}
    if verify:
        vr = agent_verify()
        vr['mismatch'] = bool(vr['ok']) and vr['count'] != len(view)
        b['verify'] = vr
    return b


if __name__ == '__main__':
    # 확인용: python ops.py features|settings|agents|verify|view
    what = sys.argv[1] if len(sys.argv) > 1 else 'features'
    fn = {'features': features_status, 'settings': settings_status, 'agents': agent_board, 'verify': agent_verify,
          'view': agent_view}[what]
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(fn(), ensure_ascii=False, indent=1))
