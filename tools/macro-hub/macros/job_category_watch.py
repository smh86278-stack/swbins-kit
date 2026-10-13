# -*- coding: utf-8 -*-
"""마켓 카테고리·정보고시 변경 감시 — 마켓 스키마가 바뀌면 깨진 매핑 목록을 알린다. config 의 "category_watch" 갈래.

    "category_watch": {
      "every_min": 1440,
      "markets": [
        {"name": "내려받은 목록", "type": "file", "path": "%USERPROFILE%\\shop\\categories.csv",
         "code": "카테고리코드", "label": "카테고리명", "notice": "정보고시"},
        {"name": "쿠팡", "type": "json_url", "auth": "coupang", "access_key_enc": "…", "secret_key_enc": "…",
         "url": "https://api-gateway.coupang.com/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
         "items": "data", "children": "child", "code": "displayItemCategoryCode", "label": "name", "status": "status"}
      ],
      "mappings": [{"name": "내 상품 매핑", "market": "쿠팡", "path": "%USERPROFILE%\\shop\\mapping.csv",
                    "code": "쿠팡카테고리", "key": "상품코드"}]
    }

마켓(markets) — 카테고리 목록을 가져오는 길. type:
    file      판매자 센터에서 내려받은 CSV(UTF-8·CP949) 또는 JSON — code·label·notice 는 열 이름(JSON 이면 키 경로)
    json_url  JSON 주소 — items(목록 위치)·children(하위 목록 키, 나무 구조면)·code·label·notice·status 키 경로.
              auth 가 "coupang" 이면 쿠팡 OpenAPI HMAC 서명(access_key_enc·secret_key_enc — python setup.py 로 암호화해 넣을 것)
  나무 구조면 이름을 '상위 > 하위' 로 이어 붙이고, 하위가 없는 것만 '등록 가능(말단)' 으로 본다.
  status 키가 있고 값이 ACTIVE/사용 이 아니면 없어진 것으로 친다.
변경 — 지난 스냅숏과 비교해 생김 · 없어짐 · 이름 바뀜 · 정보고시 바뀜 · 말단이 아니게 됨(하위가 생겨 그 코드로 등록 불가).
  처음 한 번은 스냅숏만 남긴다. 바뀐 것이 있으면 메일 한 통(건수 + 깨진 매핑 50건까지), 전체는 data.local/category_watch/ 의 CSV.
매핑(mappings) — 내 상품 → 마켓 카테고리 코드 CSV. 그 코드가 없어졌거나·말단이 아니거나·이번에 정보고시가 바뀌었으면 '깨짐'.
판매자용 연동 보조 도구라 밖에 팔기 전에 겸업 규정을 확인할 것(키트 README).
"""
import csv
import datetime
import hashlib
import hmac
import io
import json
import os
import time
import urllib.parse
import urllib.request

import kit

FEATURE = 'category_watch'
ACTIVE = ('', 'ACTIVE', 'USE', 'Y', 'TRUE', '사용', '활성')
SHOW_BROKEN = 50

META = {
    "name": "마켓 카테고리·정보고시 변경 감시",
    "desc": "config 의 category_watch — 마켓 카테고리 목록(내려받은 파일·JSON·쿠팡 API)의 스냅숏을 비교해 바뀐 것과 깨진 매핑을 알린다.",
    "kind": "ctx",
    "target": "web",
    "triggers": [{"type": "schedule", "every": "10m"}],
    "timeout": 900,
    "cooldown": 30,
}


# ---------------------------------------------------------------- 순수 로직 (테스트 대상)

def get_path(d, path):
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


def _s(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return '' if v is None else str(v).strip()


def flatten(nodes, spec, parent=''):
    """나무(또는 평평한 목록) → {코드: {'label': '상위 > 하위', 'notice': 문자열, 'leaf': bool}}.
    spec: code·label·notice·status·children 키 경로. status 가 ACTIVE 류가 아니면 뺀다."""
    out = {}
    if isinstance(nodes, dict):
        nodes = [nodes]
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        label = _s(get_path(n, spec.get('label') or 'name'))
        full = '%s > %s' % (parent, label) if parent and label else (label or parent)
        kids = get_path(n, spec['children']) if spec.get('children') else None
        kids = kids if isinstance(kids, list) else ([kids] if isinstance(kids, dict) else [])
        code = _s(get_path(n, spec.get('code') or 'code'))
        status = _s(get_path(n, spec['status'])).upper() if spec.get('status') else ''
        if code and status in ACTIVE:
            out[code] = {'label': full, 'notice': _s(get_path(n, spec['notice'])) if spec.get('notice') else '',
                         'leaf': not kids}
        if kids:
            out.update(flatten(kids, spec, full))
    return out


def rows_to_snapshot(rows, spec):
    """CSV 행(dict) → 스냅숏. 평평한 목록이라 모두 말단으로 본다(열 'leaf' 가 있으면 그 값)."""
    out = {}
    for r in rows:
        code = _s(r.get(spec.get('code') or 'code'))
        if not code:
            continue
        leaf = _s(r.get('leaf')).upper()
        out[code] = {'label': _s(r.get(spec.get('label') or 'name')), 'notice': _s(r.get(spec['notice'])) if spec.get('notice') else '',
                     'leaf': leaf not in ('N', 'FALSE', '0', '아니오')}
    return out


def diff(old, new):
    """→ {'added', 'removed', 'renamed', 'notice', 'not_leaf'} 각 [(코드, 설명)]."""
    d = {'added': [], 'removed': [], 'renamed': [], 'notice': [], 'not_leaf': []}
    for c in sorted(set(new) - set(old)):
        d['added'].append((c, new[c]['label']))
    for c in sorted(set(old) - set(new)):
        d['removed'].append((c, old[c]['label']))
    for c in sorted(set(old) & set(new)):
        o, n = old[c], new[c]
        if o['label'] != n['label']:
            d['renamed'].append((c, '%s → %s' % (o['label'], n['label'])))
        if o.get('notice', '') != n.get('notice', ''):
            d['notice'].append((c, n['label']))
        if o.get('leaf', True) and not n.get('leaf', True):
            d['not_leaf'].append((c, n['label']))
    return d


DIFF_NAMES = (('removed', '없어짐'), ('not_leaf', '하위가 생겨 등록 불가'), ('renamed', '이름 바뀜'),
              ('notice', '정보고시 바뀜'), ('added', '새로 생김'))


def diff_count(d):
    return sum(len(v) for v in d.values())


def broken(mapping_rows, spec, snap, changed_notice=()):
    """매핑 행 중 깨진 것 → [(내 키, 코드, 이유)]."""
    changed = set(changed_notice)
    out = []
    for r in mapping_rows:
        code = _s(r.get(spec.get('code') or 'code'))
        key = _s(r.get(spec.get('key') or '')) if spec.get('key') else ''
        if not code:
            continue
        c = snap.get(code)
        if c is None:
            out.append((key, code, '마켓에 없는 카테고리'))
        elif not c.get('leaf', True):
            out.append((key, code, '말단이 아님(하위 카테고리로 옮겨야 등록 가능) — %s' % c['label']))
        elif code in changed:
            out.append((key, code, '정보고시가 바뀜 — 상품 정보고시 다시 확인 — %s' % c['label']))
    return out


def coupang_auth(method, url, access_key, secret_key, now=None):
    """쿠팡 OpenAPI Authorization 머리글(CEA HmacSHA256). 서명 문자열 = signed-date + method + path + query."""
    p = urllib.parse.urlsplit(url)
    signed = time.strftime('%y%m%dT%H%M%SZ', time.gmtime(now if now is not None else time.time()))
    msg = signed + method.upper() + p.path + p.query
    sig = hmac.new(secret_key.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()
    return 'CEA algorithm=HmacSHA256, access-key=%s, signed-date=%s, signature=%s' % (access_key, signed, sig)


# ---------------------------------------------------------------- 읽어 오기

def read_csv_rows(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp949'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode('utf-8', 'replace')
    return list(csv.DictReader(io.StringIO(text)))


def load_market(m, sslctx=None, opener=None):
    kind = (m.get('type') or 'file').lower()
    if kind == 'file':
        path = kit.expand(m.get('path') or '')
        if path.lower().endswith('.json'):
            with open(path, encoding='utf-8-sig') as f:
                data = json.load(f)
            return flatten(get_path(data, m['items']) if m.get('items') else data, m)
        return rows_to_snapshot(read_csv_rows(path), m)
    if kind == 'json_url':
        url = str(m.get('url') or '')
        if not url.startswith('https://'):
            raise ValueError('json_url 은 https 주소여야 합니다')
        headers = {'Accept': 'application/json', 'User-Agent': 'work-automation-kit/category-watch'}
        if (m.get('auth') or '').lower() == 'coupang':
            headers['Authorization'] = coupang_auth('GET', url, kit.unprotect(m['access_key_enc']), kit.unprotect(m['secret_key_enc']))
            headers['X-Requested-By'] = kit.unprotect(m['access_key_enc'])
        req = urllib.request.Request(url, headers=headers)
        opener = opener or (lambda r: urllib.request.urlopen(r, timeout=60, context=sslctx))
        with opener(req) as r:
            data = json.loads(r.read().decode('utf-8'))
        return flatten(get_path(data, m['items']) if m.get('items') else data, m)
    raise ValueError('type 은 file · json_url 중 하나: %s' % kind)


def write_report(path, market, d, broken_rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['마켓', '구분', '코드', '내용'])
        for k, name in DIFF_NAMES:
            for code, text in d[k]:
                w.writerow([market, name, code, text])
        for key, code, why in broken_rows:
            w.writerow([market, '깨진 매핑', code, '%s — %s' % (key, why) if key else why])


# ---------------------------------------------------------------- 한 번 돌기

def evaluate_market(name, old, new, mappings):
    """한 마켓 — (바뀐 것, 깨진 매핑 [(매핑 이름, 키, 코드, 이유)], 상태 문구, 처음인가)."""
    if old is None:
        return None, [], '처음 스냅숏 %d개 — 다음부터 비교' % len(new), True
    d = diff(old, new)
    notice_codes = [c for c, _ in d['notice']]
    bad = []
    for mp, rows in mappings:
        bad += [(mp.get('name') or mp.get('path'), k, c, why) for k, c, why in broken(rows, mp, new, notice_codes)]
    parts = ['%s %d' % (label, len(d[k])) for k, label in DIFF_NAMES if d[k]]
    text = ('바뀜 — ' + ' · '.join(parts)) if parts else '변경 없음'
    return d, bad, text + (' · 깨진 매핑 %d' % len(bad) if bad else '') + ' (카테고리 %d개)' % len(new), False


def run(ctx):
    conf = kit.section(FEATURE, {})
    if not isinstance(conf, dict) or not conf.get('markets'):
        ctx.log('볼 마켓이 없습니다 — config.local.json 의 "category_watch" → "markets" 에 넣으세요.')
        kit.write_status(FEATURE, [], note='설정 없음')
        return
    ddir = kit.data_dir(FEATURE)
    f_state = os.path.join(ddir, 'state.json')
    state = kit.read_json(f_state, {}) or {}
    manual = (ctx.trigger or {}).get('kind') == 'manual'
    every = max(60, int(conf.get('every_min') or 1440))
    if not manual and not kit.every_due(every, state.get('last_run')):
        return
    sslctx = kit.ssl_context()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    items, alerts = [], []
    for m in conf['markets']:
        name = str(m.get('name') or m.get('type'))
        f_snap = os.path.join(ddir, 'snap-%s.json' % hashlib.sha1(name.encode('utf-8')).hexdigest()[:10])
        try:
            new = load_market(m, sslctx)
        except Exception as e:
            items.append({'name': name, 'ok': None, 'text': '목록을 못 가져옴 — %s' % str(e)[:150]})
            ctx.log('목록 실패 %s — %s' % (name, e))
            continue
        if not new:
            items.append({'name': name, 'ok': None, 'text': '카테고리가 0개 — 열 이름·키 경로(code·label·items)를 확인하세요'})
            continue
        maps = []
        for mp in conf.get('mappings') or []:
            if mp.get('market') == name:
                try:
                    maps.append((mp, read_csv_rows(kit.expand(mp['path']))))
                except Exception as e:
                    items.append({'name': '%s 매핑 · %s' % (name, mp.get('name')), 'ok': None, 'text': '매핑 파일을 못 읽음 — %s' % e})
        old = kit.read_json(f_snap, None)
        d, bad, text, first = evaluate_market(name, old, new, maps)
        kit.write_json(f_snap, new)
        changed = d is not None and diff_count(d) > 0
        items.append({'name': name, 'ok': True if first or not (changed or bad) else False if bad else None, 'text': text})
        if changed or bad:
            rpt = os.path.join(ddir, 'report-%s-%s.csv' % (stamp, hashlib.sha1(name.encode('utf-8')).hexdigest()[:6]))
            write_report(rpt, name, d or diff(new, new), [(k, c, '%s: %s' % (mn, why)) for mn, k, c, why in bad])
            lines = ['%s 카테고리 목록이 바뀌었습니다 — %s' % (name, text), '']
            for k, label in DIFF_NAMES:
                for code, t in (d or {}).get(k, [])[:10]:
                    lines.append('  [%s] %s %s' % (label, code, t))
            if bad:
                lines += ['', '깨진 매핑 %d건%s:' % (len(bad), ' (앞 %d건)' % SHOW_BROKEN if len(bad) > SHOW_BROKEN else '')]
                lines += ['  %s · %s · %s — %s' % (mn, k or '-', c, why) for mn, k, c, why in bad[:SHOW_BROKEN]]
            lines += ['', '전체 목록(CSV): %s' % rpt]
            alerts.append(('[카테고리] %s — %s' % (name, '깨진 매핑 %d건' % len(bad) if bad else '목록 바뀜'), '\n'.join(lines)))
    state['last_run'] = time.time()
    kit.write_json(f_state, state)
    kit.write_status(FEATURE, items, note='%d분마다' % every)
    for i in items:
        ctx.log('%s %s — %s' % ({True: '○', False: '✖', None: '△'}[i['ok']], i['name'], i['text']))
    for subject, body in alerts:
        ctx.log('알림:', subject)
        try:
            kit.alert(subject, body)
        except Exception as e:
            ctx.log('알림 실패:', e)
            ctx.notify(subject, '알림 실패(%s) — %s' % (e, body.splitlines()[0]), 'warning')
