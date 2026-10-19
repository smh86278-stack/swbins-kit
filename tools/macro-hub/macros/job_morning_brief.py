# -*- coding: utf-8 -*-
"""아침 한 통 브리핑 — config "morning_brief" 의 요일·시각에 어제 자동화(성공·실패)·메일/대화로 맡긴 일·답 기다리는 질문·
상시 서비스·「📊 기능 상태」의 ✖ 를 한 통에 모아 알림(kit.alert — 메일 + 슬랙·Teams 등 출구)으로 보낸다.

    "morning_brief": {"enabled": false, "at": "08:30", "days": "mon-fri"}

내용은 mcp_server.brief() — 허브 MCP 도구 hub_brief 와 같은 것. LLM 없이 기록에서 바로 만든다(매일 같은 모양, 사용량 0).
돌고 나면 바로 마지막 실행을 기록한다 — 같은 날 두 번 보내지 않게. 알림이 실패하면 RETRY_MIN 분 뒤 다시(시각에서 3시간 안).
"""
import datetime
import os
import time

import kit
import mcp_server

FEATURE = 'morning_brief'
RETRY_MIN = 30

META = {
    "name": "아침 브리핑",
    "desc": "어제 자동화·맡긴 일·답 기다리는 질문·서비스·기능 상태(✖)를 한 통으로 알림. 설정 morning_brief (기본 꺼짐).",
    "kind": "ctx",
    "target": "desktop",
    "motion": "mail",
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 120,
    "cooldown": 20,
}


def settings(cfg=None):
    """{'enabled', 'at', 'days'} — days 는 키트 표기('mon-fri' · 'mon,thu'). 목록으로 적어도 받는다."""
    w = (cfg if cfg is not None else kit.load_config()).get(FEATURE) or {}
    days = w.get('days') or 'mon-fri'
    if isinstance(days, (list, tuple)):
        days = ','.join(str(x).strip() for x in days if str(x).strip()) or 'mon-fri'
    return {'enabled': bool(w.get('enabled')), 'at': str(w.get('at') or '08:30'), 'days': str(days)}


def is_due(w, state, now):
    if not w['enabled'] or not kit.due(w, state.get('last_run'), now):
        return False
    fail = state.get('last_fail')
    return not (isinstance(fail, (int, float)) and now.timestamp() - fail < RETRY_MIN * 60)


def run(ctx):
    w = settings()
    when = '%s %s' % (w['days'], w['at'])
    manual = (ctx.trigger or {}).get('kind') == 'manual'      # 허브에서 「지금 실행」 — 꺼져 있어도 한 통(미리 보기)
    if not w['enabled'] and not manual:
        if kit.read_status(FEATURE) is None:
            kit.write_status(FEATURE, [{'name': '아침 브리핑', 'ok': None, 'text': '꺼짐 · %s' % when}],
                             note='morning_brief.enabled 를 켜면 돈다')
        return
    path = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(path, {}) or {}
    now = datetime.datetime.now()
    if not manual and not is_due(w, state, now):
        return
    subject, body = mcp_server.brief()
    for ln in body.splitlines():
        ctx.log(ln)
    try:
        kit.alert(subject, body)
    except Exception as e:
        state.update(last_fail=now.timestamp())
        kit.write_json(path, state)
        kit.write_status(FEATURE, [{'name': '아침 브리핑', 'ok': False, 'text': '%s · 알림 실패: %s' % (when, e)}],
                         note='확인 %s' % time.strftime('%H:%M'))
        ctx.notify('☀ ' + subject, '알림을 못 보냈습니다: %s' % e, 'warning')
        raise RuntimeError('아침 브리핑 알림 실패: %s' % e)
    if not manual:
        state.update(last_run=now.timestamp(), last_fail=None)
        kit.write_json(path, state)
    kit.write_status(FEATURE, [{'name': '아침 브리핑', 'ok': True, 'text': '%s · 보냄: %s' % (when, subject)}],
                     note='마지막 %s' % time.strftime('%m-%d %H:%M'))
    ctx.log('보냄 — ' + subject)
