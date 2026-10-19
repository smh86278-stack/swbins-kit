# -*- coding: utf-8 -*-
"""로그인·키 만료 예고 — 끊긴 뒤가 아니라 끊기기 전에 알린다. config 의 "cred_watch" 갈래.

    "cred_watch": {"every_min": 60, "warn_days": 7, "claude": true, "mail": true, "jira": true,
                   "keys": [{"name": "쇼핑몰 API 키", "expires": "2027-03-31", "fix": "판매자 센터에서 재발급"}]}

- 만료일이 있는 것은 warn_days 일 전부터 '곧 만료', 하루 안·지난 것은 '위험'.
    claude  Claude Code 로그인(디스패치·주간 보고 초안이 무인 실행에 쓴다) — 로그인 파일의 만료 시각
    jira    jira 갈래의 토큰 — Server/Data Center 는 서버가 알려 주는 개인 액세스 토큰 만료일,
            Cloud 는 만료일을 물을 수 없어 로그인만 확인한다(만료일은 keys 에 적어 두면 된다)
    keys    사람이 적어 둔 키·인증서·계약의 만료일(쇼핑몰·마켓 API 키처럼 몇 달마다 바꾸는 것)
- 만료일이 없는 메일 비밀번호는 로그인해 보고 인증이 거부되면 바로 '위험'(시간 초과 같은 연결 오류는 참고만).
알림: 상태가 나빠지면 바로, 계속 나쁘면 하루 한 번(9시 이후) — 메일(kit.alert), 메일이 안 되면 트레이 풍선.
비밀값은 읽어 내보내지 않는다 — 만료 시각·상태만 남긴다.
"""
import base64
import datetime
import imaplib
import json
import os
import re
import time
import urllib.error
import urllib.request

import kit
import ops

FEATURE = 'cred_watch'
REMIND_HOUR = 9
DAY = 86400
AUTH_RE = re.compile(r'AUTHENTICATIONFAILED|LOGIN failed|Invalid credentials|authenticat\w* fail|'
                     r'Username and Password not accepted|Application-specific password|CryptUnprotect|DPAPI|'
                     r'로그인 실패|인증 실패|비밀번호', re.I)

META = {
    "name": "로그인·키 만료 예고",
    "desc": "config 의 cred_watch — Claude Code 로그인·Jira 토큰·적어 둔 키의 만료를 warn_days 일 전부터, 메일 로그인 실패는 바로 알린다.",
    "kind": "ctx",
    "target": "desktop",
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 120,
    "cooldown": 30,
}


# ---------------------------------------------------------------- 순수 로직 (테스트 대상)

def by_days(until, now, warn_days):
    """만료 시각(초) → (level, 문구). level: ok · warn(warn_days 안) · bad(하루 안·지남)."""
    left = (until - now) / float(DAY)
    stamp = datetime.datetime.fromtimestamp(until).strftime('%Y-%m-%d %H:%M')
    if left <= 0:
        return 'bad', '%s 만료됨' % stamp
    if left <= 1:
        return 'bad', '%s 만료 · %d시간 남음' % (stamp, max(1, int(left * 24)))
    return ('warn' if left <= warn_days else 'ok'), '%s 만료 · %d일 남음' % (stamp, int(left))


def parse_expires(v):
    """'2027-03-31' · '2027-03-31 18:00' → 초. 날짜만이면 그날 끝(23:59:59). 못 읽으면 None."""
    s = str(v or '').strip()
    for fmt, end in (('%Y-%m-%d %H:%M', False), ('%Y-%m-%d', True)):
        try:
            d = datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
        return (d + datetime.timedelta(days=1, seconds=-1) if end else d).timestamp()
    return None


def pat_time(v):
    """Jira 의 '2026-12-01T10:00:00.000+0900' → 초."""
    if not v:
        return None
    try:
        return datetime.datetime.strptime(re.sub(r'\.\d+', '', str(v)), '%Y-%m-%dT%H:%M:%S%z').timestamp()
    except ValueError:
        return None


def pat_pick(tokens):
    """토큰 목록 중 방금 이 요청에 쓰인 것(lastAccessedAt 이 가장 늦은 것) → (이름, 만료 초 | None). 없으면 None."""
    toks = [t for t in tokens or [] if isinstance(t, dict)]
    if not toks:
        return None
    t = max(toks, key=lambda x: pat_time(x.get('lastAccessedAt')) or 0)
    return str(t.get('name') or ''), pat_time(t.get('expiringAt'))


def error_item(name, fix, err, auth=None):
    """로그인 시도가 실패했을 때 — 인증 거부면 bad, 그 밖(시간 초과·주소 오류)은 참고만."""
    msg = str(err)[:150] or type(err).__name__
    if auth if auth is not None else bool(AUTH_RE.search(msg)):
        return {'id': name, 'name': name, 'level': 'bad', 'text': '로그인 거부 — ' + msg, 'fix': fix}
    return {'id': name, 'name': name, 'level': 'info', 'text': '연결 오류(로그인 문제는 아닌 것 같습니다) — ' + msg, 'fix': fix}


def key_items(keys, now, warn_days):
    out = []
    for k in keys or []:
        if not isinstance(k, dict) or not k.get('name'):
            continue
        name, fix = str(k['name']), str(k.get('fix') or '만든 곳에서 다시 발급')
        until = parse_expires(k.get('expires'))
        if until is None:
            out.append({'id': 'key:' + name, 'name': name, 'level': 'unknown', 'fix': fix,
                        'text': '만료일을 읽지 못했습니다 — "expires": "2027-03-31" 형식으로'})
            continue
        level, text = by_days(until, now, warn_days)
        out.append({'id': 'key:' + name, 'name': name, 'level': level, 'text': text, 'fix': fix})
    return out


def due_items(items, sent, now):
    """알릴 항목과 새 기록. 상태가 바뀌면 바로, 그대로면 하루 한 번(REMIND_HOUR 이후). 나아지면 기록을 지운다."""
    t = datetime.datetime.fromtimestamp(now)
    today = t.strftime('%Y-%m-%d')
    sent, due = dict(sent or {}), []
    for it in items:
        if it['level'] not in ('warn', 'bad'):
            sent.pop(it['id'], None)
            continue
        prev = sent.get(it['id']) or {}
        if prev.get('level') != it['level'] or (prev.get('day') != today and t.hour >= REMIND_HOUR):
            due.append(it)
            sent[it['id']] = {'level': it['level'], 'day': today}
    return due, sent


def to_status(items):
    """운영 화면 '기능 상태' 줄 — ok 는 ○, 곧 만료·위험은 ✖, 참고·모름은 △."""
    mark = {'ok': True, 'warn': False, 'bad': False}
    label = {'warn': '곧 만료 — ', 'bad': '위험 — ', 'info': '참고 — ', 'unknown': ''}
    return [{'name': it['name'], 'ok': mark.get(it['level']), 'text': label.get(it['level'], '') + it['text']} for it in items]


# ---------------------------------------------------------------- 확인 (파일·네트워크)

def check_claude(now, warn_days):
    """Claude Code 로그인 파일의 만료 시각. 파일이 없으면(이 PC 에서 안 씀·API 키) 항목을 만들지 않는다."""
    path = os.path.join(ops.claude_home(), '.credentials.json')
    if not os.path.exists(path):
        return None
    item = {'id': 'claude', 'name': 'Claude Code 로그인', 'fix': '터미널에서 claude 실행 → /login'}
    d = kit.read_json(path, {}) or {}
    o = d.get('claudeAiOauth') if isinstance(d, dict) else None
    exp = o.get('refreshTokenExpiresAt') if isinstance(o, dict) else None
    if not isinstance(exp, (int, float)) or exp <= 0:
        return dict(item, level='unknown', text='로그인 파일에 만료 시각이 없습니다')
    level, text = by_days(exp / 1000.0, now, warn_days)
    return dict(item, level=level, text='로그인 유지 기한 ' + text)


def check_mail():
    m = kit.mail_config()
    ok, why = kit.mail_ready(m)
    name, fix = '메일 계정 (%s)' % (m.get('user') or '-'), '「메일·계정 설정」(setup_gui.py)에서 비밀번호 다시 넣기'
    if not ok:
        return {'id': 'mail', 'name': name, 'level': 'unknown', 'text': why, 'fix': fix}
    if not m.get('imap_host'):
        return {'id': 'mail', 'name': name, 'level': 'unknown', 'text': 'imap_host 가 없어 로그인을 확인할 수 없습니다', 'fix': fix}
    try:
        conn = kit.imap_connect(m)
        try:
            conn.logout()
        except Exception:
            pass
    except imaplib.IMAP4.error as e:                  # 서버가 로그인을 거부했다
        return dict(error_item(name, fix, e, auth=True), id='mail')
    except Exception as e:
        return dict(error_item(name, fix, e), id='mail')
    return {'id': 'mail', 'name': name, 'level': 'ok', 'text': '로그인 정상', 'fix': fix}


def check_jira(full, now, warn_days, opener=None):
    """jira 갈래가 채워져 있을 때만. Server/DC 는 /rest/pat/latest/tokens 의 만료일, Cloud 는 /myself 로 로그인만."""
    j = full.get('jira') if isinstance(full.get('jira'), dict) else {}
    base = str(j.get('base_url') or '').strip().rstrip('/')
    if not base or not j.get('token_enc'):
        return None
    server = str(j.get('auth') or '').strip().lower() in ('server', 'datacenter', 'dc', 'pat', 'bearer')
    name, fix = 'Jira 토큰', 'Jira 에서 토큰을 새로 만들어 python setup.py --jira 로 다시 넣기'
    if not kit.url_ok(base, local_http=False):          # http 면 토큰이 평문으로 나간다 — 묻지 않는다
        return {'id': 'jira', 'name': name, 'level': 'bad', 'text': 'Jira 주소가 https 가 아니라 토큰을 보내지 않았습니다: %s' % base,
                'fix': 'config 의 jira.base_url 을 https:// 주소로'}
    try:
        token = kit.unprotect(j['token_enc'])
    except Exception as e:
        return {'id': 'jira', 'name': name, 'level': 'bad', 'text': '저장된 토큰을 풀지 못했습니다(다른 PC·사용자에서 넣은 것) — %s' % e, 'fix': fix}
    if server:
        auth = 'Bearer ' + token
    else:
        auth = 'Basic ' + base64.b64encode(('%s:%s' % (j.get('email') or '', token)).encode('utf-8')).decode('ascii')
    ctx = kit.ssl_context(dict(kit.mail_config(full), ca_bundle=j.get('ca_bundle') or (full.get('mail') or {}).get('ca_bundle') or ''))
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=20, context=ctx))

    def get(path):
        req = urllib.request.Request(base + path, headers={'Authorization': auth, 'Accept': 'application/json'})
        with opener(req) as r:
            return json.loads(r.read().decode('utf-8'))

    try:
        if server:
            try:
                data = get('/rest/pat/latest/tokens')
                picked = pat_pick(data if isinstance(data, list) else (data or {}).get('tokens') if isinstance(data, dict) else [])
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise
                picked = None                          # 만료일 조회를 지원하지 않는 버전 — 로그인만 본다
            if picked and picked[1]:
                level, text = by_days(picked[1], now, warn_days)
                return {'id': 'jira', 'name': name, 'level': level, 'text': text + (' (%s)' % picked[0] if picked[0] else ''), 'fix': fix}
            if picked:
                return {'id': 'jira', 'name': name, 'level': 'ok', 'text': '만료일 없는 토큰' + (' (%s)' % picked[0] if picked[0] else ''), 'fix': fix}
        get('/rest/api/2/myself')
        return {'id': 'jira', 'name': name, 'level': 'ok', 'fix': fix,
                'text': '로그인 정상 — 이 Jira 는 토큰 만료일을 알려 주지 않습니다. 만든 날 정한 만료일을 keys 에 적어 두세요'}
    except urllib.error.HTTPError as e:
        return dict(error_item(name, fix, 'HTTP %d' % e.code, auth=e.code == 401), id='jira')
    except Exception as e:
        return dict(error_item(name, fix, e, auth=False), id='jira')


def collect(conf, full, now):
    warn = float(conf.get('warn_days') or 7)
    items = []
    if conf.get('claude', True):
        items.append(check_claude(now, warn))
    if conf.get('mail', True):
        items.append(check_mail())
    if conf.get('jira', True):
        items.append(check_jira(full, now, warn))
    items += key_items(conf.get('keys'), now, warn)
    return [it for it in items if it]


# ---------------------------------------------------------------- 한 번 돌기

def run(ctx):
    full = kit.load_config()
    conf = kit.section(FEATURE, {}, cfg=full)
    conf = conf if isinstance(conf, dict) else {}
    f_state = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(f_state, {}) or {}
    manual = (ctx.trigger or {}).get('kind') == 'manual'
    if not manual and not kit.every_due(conf.get('every_min') or 60, state.get('last_run')):
        return
    now = time.time()
    items = collect(conf, full, now)
    due, sent = due_items(items, state.get('sent'), now)
    kit.write_json(f_state, {'last_run': now, 'sent': sent})
    kit.write_status(FEATURE, to_status(items), note='%d분마다 · %g일 전부터 예고' % (int(conf.get('every_min') or 60), float(conf.get('warn_days') or 7)))
    for it in items:
        ctx.log('[%s] %s — %s' % (it['level'], it['name'], it['text']))
    if not due:
        return
    subject = '[로그인·키] %s' % (due[0]['name'] if len(due) == 1 else '%d건 확인 필요' % len(due))
    body = '\n\n'.join('%s %s\n  %s\n  다시 넣기: %s' % ('⛔' if it['level'] == 'bad' else '⏳', it['name'], it['text'], it['fix'])
                       for it in due)
    try:
        kit.alert(subject, body)
        ctx.log('알림 메일:', subject)
    except Exception as e:                            # 메일 계정 자체가 끊긴 경우 — 트레이 풍선으로라도
        ctx.log('알림 메일 실패:', e)
        ctx.notify(subject, body.splitlines()[0] + ' (메일 실패: %s)' % e, 'warning')
