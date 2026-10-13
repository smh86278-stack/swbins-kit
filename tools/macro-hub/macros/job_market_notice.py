# -*- coding: utf-8 -*-
"""'우리 문제냐 마켓 문제냐' — 마켓·결제·택배의 공개 장애·점검 공지를 모으고, 내 실패 기록과 시간을 맞춰 본다.
config 의 "market_notice" 갈래.

    "market_notice": {
      "every_min": 30, "keywords": ["장애", "점검", "지연", "오류", "중단"], "window_min": 120,
      "sources": [{"name": "예시 몰", "type": "rss", "url": "https://.../rss"},
                  {"name": "예시 결제", "type": "statuspage", "url": "https://status.example.com"},
                  {"name": "예시 공지", "type": "html", "url": "https://.../notice",
                   "item": "<a href=\\"(?P<link>[^\\"]+)\\"[^>]*>(?P<title>[^<]+)</a>.*?(?P<date>\\\\d{4}\\\\.\\\\d{2}\\\\.\\\\d{2})"}],
      "failures": [{"name": "주문 수집 실패", "path": "C:\\\\shop\\\\logs\\\\*.log", "match": "주문수집.*(실패|ERROR)",
                    "spike_min": 5, "spike_ratio": 3}]
    }

공지(sources) — 로그인 없이 공개로 읽히는 것만. 그 사이트 robots.txt 가 막으면 읽지 않는다(끄는 설정 없음). type:
    rss         RSS 2.0 · Atom
    statuspage  statuspage.io 형식 상태 페이지(주소 뒤에 /history.rss 를 붙여 읽는다 — /api/ 는 robots.txt 로 막힌 곳이 많다)
    html        정적 HTML 목록 — item 정규식의 이름 붙은 묶음 title(필수)·link·date·tag(제목 밖 분류 칸)로 항목을 뽑는다
    json        JSON 목록 — items(목록 위치)·title·date·link·tag·emergency 키 경로(점으로 이음, 예 "category.categoryName")
  제목에 keywords 중 하나가 있어야 장애·점검 공지로 본다(statuspage 와 emergency 가 참인 것은 전부 장애).
  출처마다 "keywords" 로 바꿀 수 있다.
  처음 읽을 때 이미 있던 공지는 '본 것'으로만 남기고 알리지 않는다. 그 뒤 새로 뜬 것은 한 건씩 메일로 알린다.
실패(failures) — 내 프로그램의 로그. match 정규식에 맞는 줄이 실패 한 건, 줄의 시각은 time 정규식(기본: 줄 안의
  2026-10-14 09:30[:00] · 2026.10.14 09:30 꼴)으로 읽는다. 파일마다 끝 2MB 만 본다.
  지난 1시간 실패가 spike_min 건 이상이고 그 전 24시간의 시간당 평균의 spike_ratio 배 이상이면 '급증' — 그때
  앞뒤 window_min 분 안의 마켓 공지를 붙여 "마켓 쪽일 가능성 / 우리 쪽일 가능성" 으로 알린다. 급증이 풀리면 한 번 더.
"""
import datetime
import glob
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import kit

FEATURE = 'market_notice'
DEFAULT_KEYWORDS = ['장애', '점검', '지연', '오류', '중단', '불안정', '복구', '긴급']
UA = 'work-automation-kit/market-notice (+public notices only)'     # HTTP 머리글이라 ASCII 만
KEEP_NOTICES = 300
TAIL_BYTES = 2 * 1024 * 1024
HOUR = 3600

META = {
    "name": "마켓 장애 공지 감시",
    "desc": "config 의 market_notice — 마켓·결제·택배의 공개 장애·점검 공지가 새로 뜨면 알리고, 내 실패 로그가 급증하면 같은 시간대 공지와 맞춰 '마켓 쪽이냐 우리 쪽이냐' 를 알린다.",
    "kind": "ctx",
    "target": "web",
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 300,
    "cooldown": 30,
}


# ---------------------------------------------------------------- 시각

DATE_RES = (
    (re.compile(r'(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?'), 'ymdhms'),
    (re.compile(r'(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})'), 'ymd'),     # '2026. 10. 08' 도
    (re.compile(r'(?<!\d)(\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)'), 'yymd'),
)


def parse_when(s):
    """'2026-10-14 09:30' · '2026.10.14' · '26.10.14' · RFC 822(RSS) · ISO 8601 → 초. 못 읽으면 None."""
    s = str(s or '').strip()
    if not s:
        return None
    try:                                                     # RSS pubDate (Tue, 14 Oct 2026 09:30:00 +0900)
        import email.utils
        d = email.utils.parsedate_to_datetime(s)
        if d is not None:
            return d.timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:                                                     # ISO 8601 (2026-10-14T09:30:00+09:00 · Z)
        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except ValueError:
        pass
    for rx, kind in DATE_RES:
        m = rx.search(s)
        if not m:
            continue
        g = [int(x) if x else 0 for x in m.groups()]
        try:
            if kind == 'ymdhms':
                return datetime.datetime(g[0], g[1], g[2], g[3], g[4], g[5]).timestamp()
            if kind == 'ymd':
                return datetime.datetime(g[0], g[1], g[2]).timestamp()
            return datetime.datetime(2000 + g[0], g[1], g[2]).timestamp()
        except ValueError:
            return None
    return None


def fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%m-%d %H:%M') if ts else '날짜 모름'


# ---------------------------------------------------------------- 공지 읽기 (순수)

def _text(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None and (x.text or '').strip():
            return x.text.strip()
    return ''


def parse_rss(xml_text):
    """RSS 2.0 · Atom → [{title, link, ts}]."""
    root = ET.fromstring(xml_text)
    atom = '{http://www.w3.org/2005/Atom}'
    out = []
    for it in root.iter('item'):
        out.append({'title': _text(it, 'title'), 'link': _text(it, 'link'),
                    'ts': parse_when(_text(it, 'pubDate', '{http://purl.org/dc/elements/1.1/}date'))})
    for it in root.iter(atom + 'entry'):
        link = it.find(atom + 'link')
        out.append({'title': _text(it, atom + 'title'), 'link': link.get('href', '') if link is not None else '',
                    'ts': parse_when(_text(it, atom + 'published', atom + 'updated'))})
    return [x for x in out if x['title']]


def _clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', str(s or '')))).strip()


def parse_html(text, item_re, base_url=''):
    """정적 HTML 목록 → [{title, link, ts}]. item_re 의 이름 붙은 묶음 title(필수)·link·date·tag.
    tag(분류 칸 — 카페24 의 [긴급] 처럼 제목 밖에 있는 것)는 제목 앞에 붙여 키워드로 거를 수 있게 한다."""
    rx = re.compile(item_re, re.S | re.I)
    if 'title' not in rx.groupindex:
        raise ValueError('item 정규식에 (?P<title>…) 묶음이 있어야 합니다')
    out = []
    for m in rx.finditer(text):
        g = m.groupdict()
        title = _clean(g.get('title'))
        if not title:
            continue
        tag = _clean(g.get('tag'))
        if tag and tag not in title:
            title = '%s %s' % (tag, title)
        link = html.unescape(g.get('link') or '').strip()
        out.append({'title': title, 'link': urllib.parse.urljoin(base_url, link) if link else '', 'ts': parse_when(g.get('date'))})
    return out


def get_path(d, path):
    """'category.categoryName' 처럼 점으로 이은 키를 따라간다. 없으면 None."""
    for k in str(path or '').split('.'):
        if not k:
            continue
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and k.isdigit() and int(k) < len(d):
            d = d[int(k)]
        else:
            return None
    return d


def parse_json(data, src):
    """JSON 공지 목록 → [{title, link, ts}]. src 의 items(목록 위치)·title·date·link·tag·emergency 는 키 경로.
    emergency 값이 참이면 키워드와 상관없이 장애로 본다."""
    items = get_path(data, src.get('items')) if src.get('items') else data
    if not isinstance(items, list):
        raise ValueError('items 경로에 목록이 없습니다: %s' % src.get('items'))
    out = []
    for it in items:
        title = _clean(get_path(it, src.get('title') or 'title'))
        if not title:
            continue
        tag = _clean(get_path(it, src['tag'])) if src.get('tag') else ''
        if tag and tag not in title:
            title = '[%s] %s' % (tag, title) if not tag.startswith('[') else '%s %s' % (tag, title)
        x = {'title': title, 'link': str(get_path(it, src.get('link') or 'link') or ''),
             'ts': parse_when(get_path(it, src.get('date') or 'date'))}
        if src.get('emergency') and get_path(it, src['emergency']):
            x['incident'] = True
        out.append(x)
    return out


def is_incident(item, keywords):
    if item.get('incident'):
        return True
    t = item.get('title') or ''
    return any(k and k in t for k in keywords)


def notice_id(source, item):
    raw = '%s|%s|%s' % (source, item.get('link') or '', item.get('title') or '')
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def pick_new(source, items, keywords, seen, first):
    """→ (새 장애 공지, 새 seen 목록). first(처음 읽음)면 전부 본 것으로만."""
    seen = list(seen or [])
    known = set(seen)
    new = []
    for it in items:
        if not is_incident(it, keywords):
            continue
        nid = notice_id(source, it)
        if nid in known:
            continue
        known.add(nid)
        seen.append(nid)
        if not first:
            new.append(dict(it, id=nid, source=source))
    return new, seen[-500:]


# ---------------------------------------------------------------- 실패 세기 (순수)

DEFAULT_TIME_RE = r'(\d{4}[-./]\d{1,2}[-./]\d{1,2}[ T]+\d{1,2}:\d{2}(?::\d{2})?)'


def failure_times(lines, match, time_re=None):
    """match 에 맞는 줄의 시각들(초). 시각을 못 읽은 줄은 뺀다."""
    mrx = re.compile(match)
    trx = re.compile(time_re or DEFAULT_TIME_RE)
    out = []
    for line in lines:
        if not mrx.search(line):
            continue
        t = trx.search(line)
        ts = parse_when(t.group(1) if t and t.groups() else (t.group(0) if t else ''))
        if ts:
            out.append(ts)
    return out


def spike_check(times, now, spike_min=5, spike_ratio=3.0):
    """→ (지난 1시간 건수, 그 전 24시간 시간당 평균, 급증?)."""
    last = sum(1 for t in times if now - HOUR < t <= now)
    base = sum(1 for t in times if now - 25 * HOUR < t <= now - HOUR) / 24.0
    spike = last >= max(1, int(spike_min)) and last >= float(spike_ratio) * max(base, 0.5)
    return last, base, spike


def notices_near(notices, start, end):
    """[start, end] 사이에 올라온(날짜만 있는 공지는 그날이 겹치면) 공지."""
    out = []
    for n in notices:
        ts = n.get('ts') or n.get('seen_at')
        if not ts:
            continue
        day_only = datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S') == '00:00:00'
        lo, hi = (ts, ts + 86400) if day_only else (ts, ts)
        if hi >= start and lo <= end:
            out.append(n)
    return out


def verdict(near):
    if near:
        return ('마켓 쪽일 가능성이 있습니다 — 같은 시간대에 공지가 %d건 있습니다:\n' % len(near) +
                '\n'.join('  · [%s] %s (%s) %s' % (n['source'], n['title'], fmt(n.get('ts')), n.get('link') or '') for n in near[:8]))
    return '같은 시간대에 모은 마켓 공지가 없습니다 — 우리 쪽(설정·인증·프로그램) 원인일 가능성을 먼저 보세요.'


# ---------------------------------------------------------------- 읽어 오기 (네트워크·파일)

def fetch(url, sslctx=None, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout, context=sslctx) as r:
        raw = r.read(3 * 1024 * 1024)
        cs = r.headers.get_content_charset() or ''
    if not cs:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096])
        cs = m.group(1).decode('ascii') if m else 'utf-8'
    if cs.lower().replace('_', '-') in ('euc-kr', 'ks-c-5601-1987', 'ksc5601', 'x-windows-949'):
        cs = 'cp949'                                         # EUC-KR 보다 넓다(옛 한국 사이트의 확장 한글)
    return raw.decode(cs, 'replace')


def source_url(src):
    """실제로 읽는 주소 — statuspage 는 /history.rss(여러 상태 페이지가 robots.txt 로 /api/ 를 막는다)."""
    url = str(src.get('url') or '').strip()
    if (src.get('type') or 'rss').lower() == 'statuspage':
        return url.rstrip('/') + '/history.rss'
    return url


def robots_allowed(url, get):
    """그 사이트 robots.txt 가 이 주소를 막는지. robots.txt 가 없거나 못 읽으면 허용으로 본다."""
    import urllib.robotparser
    p = urllib.parse.urlsplit(url)
    try:
        text = get('%s://%s/robots.txt' % (p.scheme, p.netloc))
    except Exception:
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return rp.can_fetch(UA, url)


def read_source(src, sslctx=None, get=None):
    get = get or (lambda u: fetch(u, sslctx))
    kind, url = (src.get('type') or 'rss').lower(), source_url(src)
    if not url.startswith(('http://', 'https://')):
        raise ValueError('url 이 http(s) 주소가 아닙니다')
    if kind not in ('rss', 'statuspage', 'html', 'json'):
        raise ValueError('type 은 rss · statuspage · html · json 중 하나: %s' % kind)
    if kind == 'html' and not src.get('item'):
        raise ValueError('html 출처는 item 정규식이 있어야 합니다')
    if not robots_allowed(url, get):                         # 끄는 설정은 두지 않는다
        raise PermissionError('그 사이트 robots.txt 가 자동 수집을 막아 읽지 않습니다')
    if kind == 'rss':
        return parse_rss(get(url))
    if kind == 'statuspage':                                 # 상태 페이지는 올라오는 것이 전부 장애·점검이다
        return [dict(x, incident=True) for x in parse_rss(get(url))]
    if kind == 'json':
        return parse_json(json.loads(get(url)), src)
    return parse_html(get(url), src['item'], url)


def tail_lines(path, limit=TAIL_BYTES):
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        raw = f.read()
    for enc in ('utf-8', 'cp949'):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace').splitlines()


def read_failures(fs, now):
    times = []
    for path in sorted(glob.glob(kit.expand(fs['path'])))[-20:]:
        if os.path.getmtime(path) < now - 26 * HOUR:
            continue
        times += failure_times(tail_lines(path), fs['match'], fs.get('time'))
    return times


# ---------------------------------------------------------------- 한 번 돌기

def evaluate(conf, state, fetched, fail_times, now):
    """읽은 공지·실패 시각으로 상태를 넘기고 알릴 것을 고른다(파일·네트워크 없음).
    fetched: 출처 이름 → 항목 목록 | Exception. fail_times: 실패 이름 → 시각 목록 | Exception.
    → (새 상태, 상태 화면 항목, 알림 [(제목, 본문)])."""
    kw_all = conf.get('keywords') or DEFAULT_KEYWORDS
    window = float(conf.get('window_min') or 120) * 60
    seen = dict(state.get('seen') or {})
    notices = list(state.get('notices') or [])
    items, alerts = [], []
    for src in conf.get('sources') or []:
        name = str(src.get('name') or src.get('url') or '?')
        got = fetched.get(name)
        if isinstance(got, Exception) or got is None:
            items.append({'name': '공지 · ' + name, 'ok': None, 'text': '읽지 못함 — %s' % (got or '결과 없음')})
            continue
        first = name not in seen
        new, seen[name] = pick_new(name, got, src.get('keywords') or kw_all, seen.get(name), first)
        for n in new:
            n['seen_at'] = now
            notices.append(n)
            alerts.append(('[마켓 공지] %s — %s' % (name, n['title'][:60]),
                           '%s 에 장애·점검 공지가 올라왔습니다.\n\n%s\n올린 때: %s\n%s\n\n'
                           '이 시간대에 주문 수집·전송 실패가 늘면 이 공지 때문일 수 있습니다.'
                           % (name, n['title'], fmt(n.get('ts')), n.get('link') or '')))
        inc = [x for x in got if is_incident(x, src.get('keywords') or kw_all)]
        latest = max(inc, key=lambda x: x.get('ts') or 0) if inc else None
        items.append({'name': '공지 · ' + name, 'ok': True,
                      'text': ('처음 읽음 — 이미 있던 공지 %d건은 알리지 않음' % len(inc)) if first else
                              ('최근 장애·점검 공지: %s (%s)' % (latest['title'][:50], fmt(latest.get('ts'))) if latest else '장애·점검 공지 없음')})
    notices = notices[-KEEP_NOTICES:]

    spikes = dict(state.get('spikes') or {})
    for fs in conf.get('failures') or []:
        name = str(fs.get('name') or fs.get('path') or '?')
        times = fail_times.get(name)
        if isinstance(times, Exception) or times is None:
            items.append({'name': '실패 · ' + name, 'ok': None, 'text': '로그를 읽지 못함 — %s' % (times or '결과 없음')})
            continue
        last, base, spike = spike_check(times, now, fs.get('spike_min') or 5, fs.get('spike_ratio') or 3)
        prev = spikes.get(name) or {}
        if spike and not prev.get('on'):
            near = notices_near(notices, now - HOUR - window, now + window)
            alerts.append(('[실패 급증] %s — 1시간 %d건 (평소 %.1f건)' % (name, last, base),
                           '%s 실패가 지난 1시간 %d건입니다(그 전 24시간 평균 시간당 %.1f건).\n\n%s'
                           % (name, last, base, verdict(near))))
            spikes[name] = {'on': True, 'since': now}
        elif not spike and prev.get('on'):
            alerts.append(('[실패 급증 풀림] %s' % name, '%s 실패가 지난 1시간 %d건으로 돌아왔습니다(%s 부터 급증).'
                           % (name, last, fmt(prev.get('since')))))
            spikes[name] = {'on': False}
        items.append({'name': '실패 · ' + name, 'ok': not spike,
                      'text': '지난 1시간 %d건 · 평소 시간당 %.1f건%s' % (last, base, ' — 급증' if spike else '')})
    return {'seen': seen, 'notices': notices, 'spikes': spikes}, items, alerts


def run(ctx):
    conf = kit.section(FEATURE, {})
    if not isinstance(conf, dict) or not (conf.get('sources') or conf.get('failures')):
        ctx.log('볼 공지·로그가 없습니다 — config.local.json 의 "market_notice" → "sources"·"failures" 에 넣으세요.')
        kit.write_status(FEATURE, [], note='설정 없음')
        return
    f_state = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(f_state, {}) or {}
    manual = (ctx.trigger or {}).get('kind') == 'manual'
    every = max(15, int(conf.get('every_min') or 30))               # 남의 서버를 너무 자주 두드리지 않는다
    if not manual and not kit.every_due(every, state.get('last_run')):
        return
    now = time.time()
    sslctx = kit.ssl_context()
    fetched, fail_times = {}, {}
    for src in conf.get('sources') or []:
        name = str(src.get('name') or src.get('url') or '?')
        try:
            fetched[name] = read_source(src, sslctx)
        except Exception as e:
            fetched[name] = e
            ctx.log('공지 읽기 실패 %s — %s' % (name, e))
    for fs in conf.get('failures') or []:
        name = str(fs.get('name') or fs.get('path') or '?')
        try:
            fail_times[name] = read_failures(fs, now)
        except Exception as e:
            fail_times[name] = e
            ctx.log('로그 읽기 실패 %s — %s' % (name, e))
    new_state, items, alerts = evaluate(conf, state, fetched, fail_times, now)
    new_state['last_run'] = now
    kit.write_json(f_state, new_state)
    kit.write_status(FEATURE, items, note='%d분마다 · 모은 공지 %d건' % (every, len(new_state['notices'])))
    for i in items:
        ctx.log('%s %s — %s' % ({True: '○', False: '✖', None: '△'}[i['ok']], i['name'], i['text']))
    for subject, body in alerts:
        ctx.log('알림:', subject)
        try:
            kit.alert(subject, body)
        except Exception as e:
            ctx.log('알림 메일 실패:', e)
            ctx.notify(subject, '메일 실패(%s) — %s' % (e, body.splitlines()[0]), 'warning')
