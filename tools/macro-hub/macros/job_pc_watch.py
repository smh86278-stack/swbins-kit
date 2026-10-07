# -*- coding: utf-8 -*-
"""이 PC 디스크 남은 공간 감시 — config 의 "pc_watch" 갈래.

    "pc_watch": {"every_min": 30, "drives": ["C:"], "disk_free_min_gb": 10, "disk_free_min_pct": 10}

허브는 1분마다 깨우고, 실제 확인은 every_min 분마다 한다(손으로 '실행' 하면 바로).
남은 공간이 GB 기준이나 % 기준 **어느 하나라도** 밑으로 내려가면 '부족' — 부족해질 때 한 번, 풀렸을 때 한 번만 메일을 보낸다.
기준을 0 이나 비워 두면 그 기준은 보지 않는다. 없는 드라이브(빠진 USB 등)는 상태에만 적고 넘어간다.
"""
import os
import shutil
import time

import kit

FEATURE = 'pc_watch'
GB = 1024 ** 3

META = {
    "name": "PC 디스크 감시",
    "desc": "config 의 pc_watch 드라이브 남은 공간을 every_min 분마다 보고, 기준 밑으로 내려가면/풀리면 메일로 알린다.",
    "kind": "ctx",
    "target": "desktop",
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 120,
    "cooldown": 30,
}


# ---------------------------------------------------------------- 순수 로직 (테스트 대상)

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def low_disk(total, free, min_gb, min_pct):
    """남은 공간이 기준 밑인가. 기준이 0·없음이면 그 기준은 끈 것."""
    min_gb, min_pct = _num(min_gb), _num(min_pct)
    if min_gb > 0 and free < min_gb * GB:
        return True
    if min_pct > 0 and total > 0 and free * 100.0 / total < min_pct:
        return True
    return False


def transition(prev_low, now_low):
    """→ 'low'(방금 부족해짐) · 'ok'(방금 풀림) · None."""
    if now_low and not prev_low:
        return 'low'
    if prev_low and not now_low:
        return 'ok'
    return None


def norm_drive(d):
    """'C' · 'C:' · 'c:\\' → 'C:\\'. 드라이브 글자가 아니면(마운트 폴더 등) 그대로."""
    d = str(d or '').strip()
    if len(d) <= 3 and d[:1].isalpha() and d[1:2] in (':', '') and d[2:] in ('', '\\', '/'):
        return d[0].upper() + ':\\'
    return d


def describe(total, free):
    return '남은 공간 %.1f GB / %.1f GB (%.0f%%)' % (free / GB, total / GB, free * 100.0 / total if total else 0)


def evaluate(conf, state, usage, now):
    """드라이브별 사용량으로 상태를 넘기고 알릴 것을 고른다(파일 없음).
    usage(드라이브) → (total, used, free), 없으면 OSError. → (새 상태, 상태 항목, 알림 [(제목, 본문)])."""
    min_gb, min_pct = conf.get('disk_free_min_gb'), conf.get('disk_free_min_pct')
    rule = ' · '.join(x for x in (('%sGB' % min_gb) if _num(min_gb) > 0 else '',
                                   ('%s%%' % min_pct) if _num(min_pct) > 0 else '') if x) or '기준 없음'
    drives = state.get('drives') or {}
    new, items, alerts = {}, [], []
    for raw in conf.get('drives') or []:
        d = norm_drive(raw)
        prev = drives.get(d) or {}
        try:
            total, _used, free = usage(d)
        except OSError as e:
            new[d] = prev                       # 잠깐 빠진 드라이브 때문에 '풀림' 알림이 가지 않게 그대로 둔다
            items.append({'name': d, 'ok': None, 'text': '드라이브를 찾을 수 없음 (%s)' % (e.strerror or e)})
            continue
        low = low_disk(total, free, min_gb, min_pct)
        ev = transition(bool(prev.get('low')), low)
        st = {'low': low, 'since': (prev.get('since') if prev.get('low') else now) if low else None,
              'free_gb': round(free / GB, 1), 'pct': round(free * 100.0 / total, 1) if total else 0}
        text = describe(total, free)
        if ev == 'low':
            alerts.append(('[PC] %s 디스크 공간 부족' % d,
                           '%s 드라이브 %s 입니다 (기준: %s 밑이면 부족).\n\n'
                           '휴지통·다운로드·임시 파일을 정리해 주세요. 풀리면 다시 알려 드립니다.' % (d, text, rule)))
        elif ev == 'ok':
            alerts.append(('[PC] %s 디스크 공간 회복' % d, '%s 드라이브 %s 로 기준(%s)을 넘었습니다.' % (d, text, rule)))
        new[d] = st
        items.append({'name': d, 'ok': not low, 'text': text + (' — 부족' if low else '')})
    return {'drives': new}, items, alerts


# ---------------------------------------------------------------- 한 번 돌기

def run(ctx):
    conf = kit.section(FEATURE, {})
    if not isinstance(conf, dict) or not conf.get('drives'):
        ctx.log('감시할 드라이브가 없습니다 — config.local.json 의 "pc_watch" → "drives" 에 넣으세요(예: ["C:"]).')
        kit.write_status(FEATURE, [], note='드라이브 없음')
        return
    f_state = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(f_state, {}) or {}
    manual = (ctx.trigger or {}).get('kind') == 'manual'
    if not manual and not kit.every_due(conf.get('every_min') or 30, state.get('last_run')):
        return
    now = time.time()
    new_state, items, alerts = evaluate(conf, state, shutil.disk_usage, now)
    new_state['last_run'] = now
    kit.write_json(f_state, new_state)
    kit.write_status(FEATURE, items, note='%d분마다 확인' % int(conf.get('every_min') or 30))
    for i in items:
        ctx.log('%s %s — %s' % ({True: '○', False: '✖', None: '△'}[i['ok']], i['name'], i['text']))
    for subject, body in alerts:
        ctx.log('알림:', subject)
        try:
            kit.alert(subject, body)
        except Exception as e:      # 메일이 안 나가도 트레이 풍선으로라도 알린다
            ctx.log('알림 메일 실패:', e)
            ctx.notify(subject, '메일 실패(%s) — %s' % (e, body.splitlines()[0]), 'warning')
