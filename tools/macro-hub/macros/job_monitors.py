# -*- coding: utf-8 -*-
"""사이트·서버 살아 있나 감시 — config 의 "monitors" 갈래.

    "monitors": {"every_min": 5, "fail_after": 2, "cert_warn_days": 14,
                 "targets": [{"name": "홈페이지", "url": "https://..."}, {"name": "DB", "host": "10.0.0.10", "port": 5432}]}

허브는 1분마다 깨우고, 실제 확인은 every_min 분마다 한다(손으로 '실행' 하면 바로).
- URL: HEAD 로 묻고 안 되면 GET 으로 다시(HEAD 를 거절하는 서버가 많다). 응답 코드 400 미만이면 정상, 리다이렉트는 따라간다.
- host+port: TCP 연결만 해 본다.
- 한 번 실패로는 알리지 않는다 — fail_after 번 내리 실패해야 '접속 안 됨'(잠깐 끊긴 걸로 메일 폭탄이 되지 않게).
  내려가면 한 번, 돌아오면 한 번만 메일을 보낸다(얼마나 끊겼는지 함께).
- https 는 서버 인증서 만료일도 읽어 cert_warn_days 일 안으로 들어오면 알린다(하루 한 번까지, D-3 안쪽에서 한 번 더).
대상이 죽어 있는 것은 이 매크로의 실패가 아니다 — 예외를 던지지 않는다(허브 실패 알림과 겹치지 않게).
설정이 잘못된 대상만 상태를 남긴 뒤 마지막에 예외로 알린다.
"""
import concurrent.futures
import datetime
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import kit

FEATURE = 'monitors'
URGENT_DAYS = 3            # 인증서가 이만큼 남으면 한 번 더 알린다

META = {
    "name": "사이트·서버 감시",
    "desc": "config 의 monitors 대상(URL · host:port)을 every_min 분마다 확인하고, 내려가면/돌아오면/인증서가 곧 끝나면 메일로 알린다.",
    "kind": "ctx",
    "target": "web",
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 600,
    "cooldown": 30,
}


# ---------------------------------------------------------------- 순수 로직 (테스트 대상)

def next_state(prev, ok, now, fail_after):
    """대상 하나의 상태 전이 → (새 상태, 사건). 사건은 None · 'down' · 'up'.
    상태 {'fails': 내리 실패 수, 'down': 알린 상태인가, 'first_fail': 이번 실패가 시작된 때, 'since': 내려간 때}."""
    prev = dict(prev or {})
    fail_after = max(1, int(fail_after or 1))
    st = {'fails': int(prev.get('fails') or 0), 'down': bool(prev.get('down')),
          'first_fail': prev.get('first_fail'), 'since': prev.get('since')}
    if ok:
        event = 'up' if st['down'] else None
        if event:
            st['downtime'] = now - (st['since'] or now)
        return dict(st, fails=0, down=False, first_fail=None, since=None), event
    if st['fails'] == 0 or not st['first_fail']:
        st['first_fail'] = now
    st['fails'] += 1
    if not st['down'] and st['fails'] >= fail_after:
        st['down'] = True
        st['since'] = st['first_fail']        # 처음 실패한 때부터 끊긴 것으로 본다
        return st, 'down'
    return st, None


def cert_days_left(not_after, now):
    """getpeercert()['notAfter'] ('Jun  1 12:00:00 2027 GMT') → 남은 날 수(내림). now 는 초."""
    return int((ssl.cert_time_to_seconds(not_after) - now) // 86400)


def cert_alert(days_left, warn_days, prev, now):
    """인증서 알림을 보낼 차례인가 → (보낼까, 새 상태). 상태 {'alerted_at', 'urgent_sent'}.
    처음 경고 구간에 들어오면 한 번, D-3 안쪽에서 한 번 더 — 어느 쪽이든 하루 한 번을 넘지 않는다.
    경고 구간 밖(갱신됨)이면 상태를 비운다."""
    if days_left is None or days_left > warn_days:
        return False, {}
    st = dict(prev or {})
    last = st.get('alerted_at')
    recent = isinstance(last, (int, float)) and now - last < 86400
    want = (not last) or (days_left <= URGENT_DAYS and not st.get('urgent_sent'))
    if not want or recent:
        return False, st
    st['alerted_at'] = now
    if days_left <= URGENT_DAYS:
        st['urgent_sent'] = True
    return True, st


def target_key(t):
    return str(t.get('name') or t.get('url') or '%s:%s' % (t.get('host'), t.get('port')))


def target_kind(t):
    """'url' · 'tcp' · None(설정 오류)."""
    if str(t.get('url') or '').lower().startswith(('http://', 'https://')):
        return 'url'
    if t.get('host') and str(t.get('port') or '').isdigit():
        return 'tcp'
    return None


def fmt_time(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def fmt_duration(sec):
    sec = int(max(0, sec))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = (['%d일' % d] if d else []) + (['%d시간' % h] if h else []) + ['%d분' % m]
    return ' '.join(parts if (d or h or m) else ['1분 미만'])


# ---------------------------------------------------------------- 실제 확인 (테스트에서는 바꿔 끼운다)

def _opener(sslctx):
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=sslctx))


def check_url(url, sslctx=None, timeout=10, urlopen=None):
    """→ (정상?, 오류 글, 응답 코드). HEAD 가 안 되면 GET 으로 한 번 더."""
    if urlopen is None:
        urlopen = _opener(sslctx).open
    err = ''
    code = None
    for method in ('HEAD', 'GET'):
        req = urllib.request.Request(url, method=method, headers={'User-Agent': 'work-automation-kit/monitor'})
        try:
            resp = urlopen(req, timeout=timeout)
            try:
                code = getattr(resp, 'status', None) or resp.getcode()
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            if code < 400:
                return True, '', code
            err = 'HTTP %s' % code
        except urllib.error.HTTPError as e:
            code, err = e.code, 'HTTP %s %s' % (e.code, e.reason or '')
        except urllib.error.URLError as e:
            err = str(e.reason or e)
        except (OSError, ValueError, ssl.SSLError) as e:
            err = '%s: %s' % (type(e).__name__, e)
    return False, err.strip(), code


def check_tcp(host, port, timeout=10, connect=None):
    connect = connect or socket.create_connection
    try:
        s = connect((host, int(port)), timeout=timeout)
        try:
            s.close()
        except Exception:
            pass
        return True, ''
    except OSError as e:
        return False, '%s: %s' % (type(e).__name__, e)


def read_cert_not_after(url, sslctx=None, timeout=10, connect=None):
    """https 서버 인증서의 notAfter. 못 읽으면 None(접속 확인 쪽에서 이미 실패로 잡힌다)."""
    u = urllib.parse.urlsplit(url)
    host, port = u.hostname, u.port or 443
    connect = connect or socket.create_connection
    try:
        raw = connect((host, port), timeout=timeout)
        with (sslctx or ssl.create_default_context()).wrap_socket(raw, server_hostname=host) as s:
            return (s.getpeercert() or {}).get('notAfter')
    except (OSError, ValueError, ssl.SSLError):
        return None


def probe(t, sslctx=None, deps=None):
    """대상 하나 확인 → {'ok', 'error', 'ms', 'not_after'}."""
    deps = deps or {}
    kind = target_kind(t)
    started = time.time()
    out = {'ok': False, 'error': '', 'ms': 0, 'not_after': None}
    if kind == 'url':
        ok, err, _code = deps.get('check_url', check_url)(t['url'], sslctx)
        out.update(ok=ok, error=err)
        if ok and t['url'].lower().startswith('https://'):
            out['not_after'] = deps.get('read_cert', read_cert_not_after)(t['url'], sslctx)
    elif kind == 'tcp':
        ok, err = deps.get('check_tcp', check_tcp)(t['host'], t['port'])
        out.update(ok=ok, error=err)
    out['ms'] = int((time.time() - started) * 1000)
    return out


# ---------------------------------------------------------------- 한 번 돌기

def evaluate(conf, state, results, now):
    """확인 결과로 상태를 넘기고 알릴 것을 고른다(파일·네트워크 없음).
    → (새 상태, 상태 화면 항목, 알림 [(제목, 본문)], 설정 오류 목록)."""
    fail_after = int(conf.get('fail_after') or 2)
    warn_days = int(conf.get('cert_warn_days') or 14)
    targets = state.get('targets') or {}
    new_targets, items, alerts, bad = {}, [], [], []
    for t in conf.get('targets') or []:
        if not isinstance(t, dict):
            bad.append(repr(t))
            continue
        key = target_key(t)
        where = t.get('url') or '%s:%s' % (t.get('host'), t.get('port'))
        if target_kind(t) is None:
            bad.append(key)
            items.append({'name': key, 'ok': False, 'text': '설정 오류 — url(http/https) 이나 host+port 가 필요합니다'})
            continue
        r = results.get(key) or {'ok': False, 'error': '확인 결과 없음'}
        prev = targets.get(key) or {}
        st, event = next_state(prev, r['ok'], now, fail_after)
        st['error'] = r.get('error') or ''
        if event == 'down':
            alerts.append(('[감시] %s 접속 안 됨' % key,
                           '%s (%s) 에 접속할 수 없습니다.\n\n오류: %s\n언제부터: %s (내리 %d번 실패)\n\n'
                           '돌아오면 다시 알려 드립니다.' % (key, where, st['error'] or '-', fmt_time(st['since']), st['fails'])))
        elif event == 'up':
            alerts.append(('[감시] %s 복구' % key,
                           '%s (%s) 에 다시 접속됩니다.\n\n끊긴 시간: %s (%s 부터)' %
                           (key, where, fmt_duration(st.pop('downtime', 0)), fmt_time(prev.get('since') or now))))
        st.pop('downtime', None)

        # 인증서
        days = None
        if r.get('not_after'):
            try:
                days = cert_days_left(r['not_after'], now)
            except ValueError:
                days = None
        send, st['cert'] = cert_alert(days, warn_days, prev.get('cert'), now) if days is not None \
            else (False, prev.get('cert') or {})
        if send:
            alerts.append(('[감시] %s 인증서 만료 D-%d' % (key, days),
                           '%s 의 서버 인증서가 %d일 뒤 끝납니다.\n\n만료: %s\n주소: %s\n\n갱신하지 않으면 접속 시 보안 경고가 뜹니다.'
                           % (key, days, r['not_after'], where)))
        if days is not None:
            st['cert_days'] = days
        new_targets[key] = st

        cert_txt = (' · 인증서 D-%d' % days) if days is not None else ''
        if st['down']:
            items.append({'name': key, 'ok': False,
                          'text': '접속 안 됨 (%s 부터) — %s' % (fmt_time(st['since']), st['error'] or '-')})
        elif not r['ok']:
            items.append({'name': key, 'ok': None,
                          'text': '확인 실패 %d/%d — %s' % (st['fails'], fail_after, st['error'] or '-')})
        else:
            warn = days is not None and days <= warn_days
            items.append({'name': key, 'ok': None if warn else True,
                          'text': '정상 (%dms)%s' % (r.get('ms') or 0, cert_txt)})
    return {'targets': new_targets}, items, alerts, bad


def send_alerts(ctx, alerts, alert_fn=None):
    alert_fn = alert_fn or kit.alert
    for subject, body in alerts:
        ctx.log('알림:', subject)
        try:
            alert_fn(subject, body)
        except Exception as e:      # 메일이 안 나가도 감시는 계속한다 — 트레이 풍선으로라도 알린다
            ctx.log('알림 메일 실패:', e)
            ctx.notify(subject, '메일 실패(%s) — %s' % (e, body.splitlines()[0]), 'warning')


def run(ctx):
    conf = kit.section(FEATURE, {})
    if not isinstance(conf, dict) or not conf.get('targets'):
        ctx.log('감시할 대상이 없습니다 — config.local.json 의 "monitors" → "targets" 에 넣으세요.')
        kit.write_status(FEATURE, [], note='대상 없음')
        return
    f_state = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(f_state, {}) or {}
    manual = (ctx.trigger or {}).get('kind') == 'manual'
    if not manual and not kit.every_due(conf.get('every_min') or 5, state.get('last_run')):
        return
    now = time.time()
    sslctx = kit.ssl_context()
    todo = [t for t in conf['targets'] if isinstance(t, dict) and target_kind(t)]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(todo)))) as pool:
        futs = {target_key(t): pool.submit(probe, t, sslctx) for t in todo}
        for key, fut in futs.items():
            results[key] = fut.result()
    new_state, items, alerts, bad = evaluate(conf, state, results, now)
    new_state['last_run'] = now
    kit.write_json(f_state, new_state)
    up = sum(1 for i in items if i['ok'] is True)
    kit.write_status(FEATURE, items, note='%d곳 중 %d곳 정상 · %d분마다' % (len(items), up, int(conf.get('every_min') or 5)))
    for i in items:
        ctx.log('%s %s — %s' % ({True: '○', False: '✖', None: '△'}[i['ok']], i['name'], i['text']))
    send_alerts(ctx, alerts)
    if bad:
        raise ValueError('monitors 설정이 잘못된 대상: %s' % ', '.join(bad))
