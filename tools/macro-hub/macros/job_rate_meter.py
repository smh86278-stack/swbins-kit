# -*- coding: utf-8 -*-
"""마켓 API 호출 한도 미터기 — ratelimit.Limiter 를 쓰는 도구들의 사용량을 운영 화면에 보이고, 위험하면 알린다.
config 의 "rate_limits" 갈래(한도)와 data.local/rate_limits/ 의 상태 파일을 읽는다.

    "rate_limits": {"_warn_pct": 80, "cafe24": {"limit": 3000, "window_sec": 600}}

- 창 안 사용량이 _warn_pct(기본 80)% 이상이면 '거의 참', 429·503 으로 쉬는 중이면 '막힘' — 그렇게 될 때 한 번 알리고
  풀리면 한 번 더. 호출을 하지는 않는다(보기만).
"""
import os
import time

import kit
import ratelimit

FEATURE = 'rate_limits'

META = {
    "name": "API 호출 한도 미터기",
    "desc": "ratelimit 을 쓰는 도구들의 마켓 API 호출 한도 사용량을 운영 화면에 보이고, 거의 차거나 429 로 막히면 알린다.",
    "kind": "ctx",
    "target": "web",
    "triggers": [{"type": "schedule", "every": "5m"}],
    "timeout": 60,
    "cooldown": 30,
}


def level_of(u, warn_pct):
    if u['cooling'] > 0:
        return 'blocked'
    if u['pct'] >= warn_pct:
        return 'high'
    return 'ok'


def evaluate(usages, prev, warn_pct):
    """→ (상태 화면 항목, 알림 [(제목, 본문)], 새 기록 {이름: level})."""
    items, alerts, now = [], [], {}
    for u in usages:
        lv = level_of(u, warn_pct)
        now[u['name']] = lv
        mins = u['window_sec'] / 60.0
        text = '%d / %d (%.0f%%) · %g분 창 · 누적 %d회' % (u['used'], u['limit'], u['pct'], mins, u['total'])
        if u['throttled']:
            text += ' · 최근 막힘 %d번' % u['throttled']
        if lv == 'blocked':
            text += ' — 쉬는 중 %.0f초' % u['cooling']
        items.append({'name': u['name'], 'ok': {'ok': True, 'high': None, 'blocked': False}[lv], 'text': text})
        was = prev.get(u['name'], 'ok')
        if lv != was and lv != 'ok':
            alerts.append(('[호출 한도] %s %s' % (u['name'], '막힘(429)' if lv == 'blocked' else '거의 참'),
                           '%s 호출 한도: %s\n\n도구들이 알아서 기다렸다 다시 보내지만, 계속되면 호출 간격·건수를 줄이세요.' % (u['name'], text)))
        elif lv == 'ok' and was != 'ok':
            alerts.append(('[호출 한도] %s 풀림' % u['name'], '%s 호출 한도: %s' % (u['name'], text)))
    return items, alerts, now


def run(ctx):
    cfg = kit.load_config()
    conf = cfg.get('rate_limits') or {}
    warn = float(conf.get('_warn_pct') or 80) if isinstance(conf, dict) else 80.0
    usages = ratelimit.all_usage(cfg=cfg)
    if not usages:
        kit.write_status(FEATURE, [], note='한도를 쓰는 도구가 아직 없음')
        return
    f_state = os.path.join(kit.data_dir(FEATURE), 'meter.json')
    prev = kit.read_json(f_state, {}) or {}
    items, alerts, now = evaluate(usages, prev, warn)
    kit.write_json(f_state, now)
    kit.write_status(FEATURE, items, note='%g%% 넘으면 알림 · %s' % (warn, time.strftime('%H:%M')))
    for i in items:
        ctx.log('%s %s — %s' % ({True: '○', False: '✖', None: '△'}[i['ok']], i['name'], i['text']))
    for subject, body in alerts:
        try:
            kit.alert(subject, body)
        except Exception as e:
            ctx.notify(subject, '알림 실패(%s)' % e, 'warning')
