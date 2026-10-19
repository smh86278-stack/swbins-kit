# -*- coding: utf-8 -*-
"""자동화 허브 MCP 서버(stdio, 읽기 전용) — Claude(Claude Code·디스패치 지시)가 허브 상태를 도구로 바로 묻게 한다.

    python setup.py --mcp      (한 번 — claude mcp add --scope user hub -- <이 파이썬> <이 파일> 을 해 준다)

"어제 뭐 실패했어?" "기능 상태 어때?" "대화 앱 살아 있어?" 에 로그를 뒤지지 않고 정리된 값으로 답하게 한다.
Claude Desktop·Cursor 같은 다른 MCP 클라이언트도 같은 명령(python mcp_server.py)으로 붙는다.
- **읽기만** 한다: 허브 GET API(127.0.0.1:8610)와 기록 파일(runs.jsonl · inbox/job-audit.jsonl · inbox/jobs)만 본다.
  자동화 실행·끄기·설정 바꾸기는 없다 — 허브 POST 는 시작할 때마다 새로 만드는 토큰을 화면에만 심는 원칙이라 여기서 열지 않는다.
- 비밀값·메일 내용은 내주지 않는다.
- 표준 라이브러리만 쓴다(mcp 패키지 없이 JSON-RPC 를 줄 단위로) — 아무 파이썬으로 돈다.
- 디스패치 지시(메일·대화)에서 쓰려면 config dispatch.extra_tools 에 "mcp__hub" 를 넣고 read_tools·write_tools 에도 넣는다.
아침 브리핑(macros\\job_morning_brief.py)도 여기 데이터 함수를 같이 쓴다.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
HUB = 'http://127.0.0.1:%d' % int(os.environ.get('MACROHUB_PORT') or 8610)
F_RUNS = os.path.join(HERE, 'runs.jsonl')
JOBS = os.path.join(ROOT, 'inbox', 'jobs')
JOB_AUDIT = os.path.join(ROOT, 'inbox', 'job-audit.jsonl')
NAME, VERSION = 'workkit-hub', '1.0'
STATUS = {'ok': '성공', 'fail': '실패', 'timeout': '시간 초과', 'running': '실행 중', 'stopped': '멈춤'}
MARK = {True: '○', False: '✖', None: '△'}
WEEKDAY = '월화수목금토일'


class HubDown(Exception):
    pass


def hub_get(path, timeout=5):
    try:
        with urllib.request.urlopen(HUB + path, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:               # 허브는 떠 있다 — 그런 것이 없음(404 등)
        raise LookupError('허브 답: %s' % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise HubDown('자동화 허브(%s)가 응답하지 않습니다 — 꺼져 있거나 다시 뜨는 중: %s' % (HUB, e))


def hm(ms):
    return time.strftime('%m-%d %H:%M', time.localtime(ms / 1000)) if ms else '-'


# ---------------------------------------------------------------- 데이터(아침 브리핑도 쓴다)

def history(hours=24, status='', name='', limit=50):
    """끝난 실행 기록(runs.jsonl — 허브를 다시 켜도 남는다). 새것 먼저, 도구 실행(요소 찍기 등)은 뺀다."""
    since = (time.time() - max(0.0, float(hours or 0)) * 3600) * 1000 if hours else 0
    want = {'fail': ('fail', 'timeout')}.get(status, (status,) if status else None)
    out, seen = [], set()
    try:
        with open(F_RUNS, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        lines = []
    for ln in reversed(lines):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get('tool') or r.get('id') in seen:
            continue
        if since and (r.get('started') or 0) < since:
            break
        seen.add(r.get('id'))
        if want and r.get('status') not in want:
            continue
        if name and name not in (r.get('name') or '') and name not in (r.get('macro') or ''):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def automations():
    """자동화 목록과 상태 — 상시 서비스가 살아 있는지, 켜져 있는지."""
    return hub_get('/api/macros')


def features():
    """「📊 기능 상태」 — 기능마다 마지막으로 남긴 항목(ok True ○ · False ✖ · None △). 로그인·키 만료 예고도 여기 있다."""
    return hub_get('/api/ops/features').get('features') or []


def instructions(hours=24, text=''):
    """메일·대화로 맡긴 일(게이트웨이 지시 실행 기록 inbox/job-audit.jsonl) — 새것 먼저."""
    since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - float(hours or 0) * 3600)) if hours else ''
    rows = []
    try:
        with open(JOB_AUDIT, encoding='utf-8', errors='replace') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and (r.get('finished') or r.get('created') or '') >= since:
                    if not text or text.lower() in json.dumps(r, ensure_ascii=False).lower():
                        rows.append(r)
    except OSError:
        pass
    return rows[::-1]


def pending_asks(days=7):
    """답을 기다리는 질문 — 선택지로 물었는데(ask) 닫히지 않았고(ask_closed) 그 대화의 마지막 작업인 것."""
    since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - days * 86400))
    jobs = []
    for fn in os.listdir(JOBS) if os.path.isdir(JOBS) else []:
        if fn.endswith('.json'):
            try:
                with open(os.path.join(JOBS, fn), encoding='utf-8-sig') as f:
                    jobs.append(json.load(f))
            except (OSError, ValueError):
                continue
    last = {}
    for j in sorted(jobs, key=lambda j: j.get('created_at') or ''):
        if j.get('thread'):
            last[j['thread']] = j
    return [j for j in last.values() if j.get('ask') and not j.get('ask_closed') and j.get('status') == 'done'
            and (j.get('finished_at') or '') >= since]


# ---------------------------------------------------------------- 도구(글로 답한다)

def fmt_run(r, with_tail=0):
    line = '[%s] %s · %s · %s%s (id %s)' % (
        hm(r.get('started')), r.get('name') or r.get('macro'), STATUS.get(r.get('status'), r.get('status')),
        r.get('trigger') or '', (' · ' + r['detail']) if r.get('detail') else '', r.get('id'))
    tail = (r.get('tail') or [])[-with_tail:] if with_tail else []
    return line + ''.join('\n    ' + str(t) for t in tail)


def tool_status(_args):
    items = [m for m in automations() if not m.get('hidden')]
    svc = [m for m in items if m.get('service')]
    lines = ['상시 서비스 %d개:' % len(svc)]
    for m in svc:
        state = '도는 중' if m.get('running') else ('꺼짐' if not m.get('enabled') else '켜져 있는데 안 돎(시작 중이거나 죽음)')
        lines.append('- %s: %s' % (m['name'], state))
    fails = history(24, 'fail', limit=10)
    lines.append('최근 24시간 실패 %d건%s' % (len(fails), ':' if fails else ''))
    lines += ['- ' + fmt_run(r) for r in fails]
    return '\n'.join(lines)


def tool_runs(args):
    rows = history(args.get('hours', 24), args.get('status', ''), args.get('name', ''), int(args.get('limit') or 30))
    if not rows:
        return '조건에 맞는 실행이 없습니다.'
    return '\n'.join(fmt_run(r) for r in rows)


def tool_run_log(args):
    rid = int(args.get('id') or 0)
    try:                                              # 이번 허브가 돌린 실행이면 로그 전체가 있다
        live = hub_get('/api/run?id=%d' % rid)
        return fmt_run(dict(live, tail=live.get('lines')), with_tail=200)
    except (HubDown, LookupError):                    # 허브가 꺼졌거나 다시 켜기 전 실행 — 기록 파일의 끝부분으로
        pass
    r = next((x for x in history(0, limit=100000) if x.get('id') == rid), None)
    if not r:
        return '그 id 의 실행 기록이 없습니다(기록은 최근 것만 남는다).'
    return fmt_run(r, with_tail=200) + '\n(허브를 다시 켜기 전 실행이라 로그는 끝부분만 남아 있다)'


def tool_features(args):
    lines = []
    for f in features():
        if not f.get('configured'):
            continue
        items = f.get('items') or []
        if args.get('bad_only'):
            items = [i for i in items if i.get('ok') is False]
            if not items:
                continue
        lines.append('%s (%s%s)' % (f['label'], f.get('ago') or '', (' · ' + f['note']) if f.get('note') else ''))
        lines += ['  %s %s — %s' % (MARK.get(i.get('ok'), '△'), i.get('name'), i.get('text')) for i in items]
    return '\n'.join(lines) or ('✖ 인 항목이 없습니다.' if args.get('bad_only') else '설정된 기능이 없습니다.')


def tool_changes(args):
    items = hub_get('/api/audit?limit=%d' % int(args.get('limit') or 20)).get('items') or []
    return '\n'.join('- %s · %s(%s) · %s · %s%s' % (i.get('ts', ''), i.get('user', ''), i.get('via', ''), i.get('action', ''),
                                                  i.get('name') or i.get('target') or '', (' — ' + i['detail']) if i.get('detail') else '')
                     for i in items) or '변경 이력이 없습니다.'


def tool_instructions(args):
    rows = instructions(args.get('hours', 24), args.get('text', ''))[:int(args.get('limit') or 20)]
    if not rows:
        return '조건에 맞는 지시가 없습니다.'
    return '\n'.join('- %s · [T%s] @%s · %s · %s · $%.2f%s\n    %s' % (
        r.get('created', ''), r.get('thread') or '-', r.get('label') or '', r.get('mode', ''), r.get('status', ''),
        r.get('cost_usd') or 0, (' · ' + r['error'][:80]) if r.get('error') else '',
        ' '.join(str(r.get('prompt') or '').split())[:120]) for r in rows)


def brief(now=None):
    """아침 한 통 브리핑 (제목, 본문) — 어제 자동화·맡긴 일·답 기다리는 질문·서비스·기능 상태(✖).
    LLM 없이 기록에서 바로 만든다(매일 같은 모양, 사용량 0). 허브가 꺼져 있으면 그 칸만 '허브 응답 없음'.
    제목은 [ 로 시작하지 않는다 — kit.alert 가 앞에 [회사 이름] 을 붙인다."""
    now = now or time.time()
    t = time.localtime(now)
    lines = []

    def section(title, fn):
        try:
            body = fn()
        except HubDown:
            body = ['허브 응답 없음 — 꺼져 있거나 다시 뜨는 중']
        lines.append('■ ' + title)
        lines.extend('  ' + b for b in body)
        lines.append('')

    runs = history(24)
    fails = [r for r in runs if r.get('status') in ('fail', 'timeout')]
    section('어제 자동화 (24시간)', lambda: ['성공 %d · 실패 %d' % (sum(r.get('status') == 'ok' for r in runs), len(fails))]
            + ['- ' + fmt_run(r) for r in fails[:5]])
    jobs = instructions(24)
    bad = [r for r in jobs if r.get('status') != 'done' or r.get('error')]
    section('맡긴 일 (24시간)', lambda: ['%d건 · $%.2f%s' % (len(jobs), sum(r.get('cost_usd') or 0 for r in jobs),
                                                           ' · 실패 %d' % len(bad) if bad else '')]
            + ['- [T%s] %s — %s' % (r.get('thread') or '-', ' '.join(str(r.get('prompt') or '').split())[:50], r.get('error') or r.get('status'))
               for r in bad[:5]])
    asks = pending_asks()
    section('답 기다리는 질문', lambda: (['%d건 — 대화 앱이나 메일에서 번호로 답하세요' % len(asks)] if asks else ['없음'])
            + ['- [T%s] %s' % (j.get('thread'), (j.get('ask') or {}).get('question', '')[:60]) for j in asks[:5]])

    def services():
        svc = [m for m in automations() if m.get('service') and m.get('enabled') and not m.get('hidden')]
        down = [m['name'] for m in svc if not m.get('running')]
        return (['상시 %d개 모두 도는 중' % len(svc)] if svc else ['켜 둔 상시 서비스 없음']) if not down else ['안 도는 것: ' + ', '.join(down)]
    section('상시 서비스', services)
    xs = []

    def feature_bad():
        for f in features():
            xs.extend('✖ %s · %s — %s' % (f['label'], i.get('name'), i.get('text')) for i in f.get('items') or [] if i.get('ok') is False)
        return xs[:8] or ['✖ 없음 — 모두 정상']
    section('기능 상태(로그인·키 만료 예고·감시 등)', feature_bad)

    warn = len(fails) + len(bad) + len(asks) + len(xs)
    subject = '아침 브리핑 %d/%d(%s)%s' % (t.tm_mon, t.tm_mday, WEEKDAY[t.tm_wday],
                                       ' — 볼 것 %d건' % warn if warn else ' — 이상 없음')
    return subject, '\n'.join(lines).rstrip() + '\n\n전체: http://127.0.0.1:8610/ops (이 PC 에서)'


def tool_brief(_args):
    subject, body = brief()
    return subject + '\n\n' + body


TOOLS = [
    ('hub_status', '허브 한눈에 — 상시 서비스(대화 앱·워커·게이트웨이 등)가 도는지, 최근 24시간 실패한 실행.', {}, tool_status),
    ('hub_runs', '자동화 실행 기록(허브를 다시 켜도 남는 runs.jsonl). "어제 뭐 실패했어?" 같은 질문에.',
     {'hours': {'type': 'number', 'description': '최근 몇 시간(기본 24, 0 이면 전부)'},
      'status': {'type': 'string', 'enum': ['', 'ok', 'fail'], 'description': 'fail 은 실패·시간 초과'},
      'name': {'type': 'string', 'description': '자동화 이름이나 id 일부'},
      'limit': {'type': 'integer', 'description': '최대 건수(기본 30)'}}, tool_runs),
    ('hub_run_log', '실행 하나의 로그 — hub_runs 가 준 id 로.', {'id': {'type': 'integer'}}, tool_run_log),
    ('hub_features', '「📊 기능 상태」 — 정기 메일·감시·백업·로그인·키 만료 예고 등 기능마다 ○ ✖ △. 값(비밀)은 없다.',
     {'bad_only': {'type': 'boolean', 'description': '✖ 인 것만'}}, tool_features),
    ('hub_changes', '변경 이력 — 누가 언제 서비스를 켜고 끄고 설정을 바꿨나.', {'limit': {'type': 'integer'}}, tool_changes),
    ('hub_instructions', '메일·대화로 맡긴 일 기록 — 언제·어느 폴더·결과·비용·지시 앞부분.',
     {'hours': {'type': 'number', 'description': '최근 몇 시간(기본 24, 0 이면 전부)'},
      'text': {'type': 'string', 'description': '이 글자가 든 것만'}, 'limit': {'type': 'integer'}}, tool_instructions),
    ('hub_brief', '아침 브리핑 미리 보기 — 어제 자동화·맡긴 일·답 기다리는 질문·서비스·기능 상태(✖)를 한 번에.', {}, tool_brief),
]


# ---------------------------------------------------------------- MCP(JSON-RPC, 줄 단위)

def handle(msg):
    method, mid = msg.get('method'), msg.get('id')
    if mid is None:                                   # 알림(notifications/initialized 등) — 답하지 않는다
        return None
    if method == 'initialize':
        ver = (msg.get('params') or {}).get('protocolVersion') or '2025-06-18'
        result = {'protocolVersion': ver, 'capabilities': {'tools': {}}, 'serverInfo': {'name': NAME, 'version': VERSION},
                  'instructions': '자동화 허브 상태를 읽기만 하는 도구. 실행·끄기는 못 한다 — 그건 허브 화면(/ops)에서.'}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [{'name': n, 'description': d, 'inputSchema': {'type': 'object', 'properties': p},
                             'annotations': {'readOnlyHint': True}} for n, d, p, _f in TOOLS]}
    elif method == 'tools/call':
        p = msg.get('params') or {}
        fn = next((f for n, _d, _p, f in TOOLS if n == p.get('name')), None)
        if not fn:
            return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32602, 'message': '없는 도구: %s' % p.get('name')}}
        try:
            result = {'content': [{'type': 'text', 'text': fn(p.get('arguments') or {})}]}
        except Exception as e:                        # 허브가 꺼짐 등 — 도구 오류로 알린다(연결은 유지)
            result = {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}
    else:
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': '모르는 요청: %s' % method}}
    return {'jsonrpc': '2.0', 'id': mid, 'result': result}


def main():
    stdin = open(sys.stdin.fileno(), encoding='utf-8', errors='replace', closefd=False)
    out = open(sys.stdout.fileno(), 'w', encoding='utf-8', newline='\n', closefd=False)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + '\n')
            out.flush()


if __name__ == '__main__':
    main()
