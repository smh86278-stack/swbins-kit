# -*- coding: utf-8 -*-
"""주간 업무 보고 초안 — ai_share.weekly_report 의 요일·시각에 이번 주(월요일~오늘)를 모아 초안을 쓰고 메일로 보낸다.

실제 일은 tools\\ai-share-agent\\agent.py weekly 가 한다(수집 → claude CLI/ollama 초안 → reports\\YYYYMMDD_주간보고.md → 메일).
  - LLM 이 실패해도 원자료(이슈·커밋 목록)를 대신 보낸다. 메일 설정이 안 돼 있으면 파일만 남기고 「📊 기능 상태」에 이유를 적는다.
  - 결과 상태는 agent.py 가 kit.write_status('weekly_report', …) 로 남긴다.
  - 돌고 나면 바로 마지막 실행을 기록한다 — 같은 날 두 번 보내지 않게. 실행이 실패하면 RETRY_MIN 분 뒤 다시(시각에서 3시간 안).
"""
import datetime
import os
import time

import extsvc
import kit

FEATURE = 'weekly_report'
RETRY_MIN = 30
AGENT = os.path.join(extsvc.ROOT, 'tools', 'ai-share-agent', 'agent.py')

META = {
    "name": "주간 업무 보고 초안",
    "desc": "이번 주 이슈·커밋을 모아 LLM(claude CLI·ollama)으로 주간 보고 초안을 쓰고 메일로 보낸다. 설정 ai_share.weekly_report (기본 꺼짐).",
    "kind": "ctx",
    "target": "desktop",
    "motion": "write",
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 2400,
    "cooldown": 20,
}


def settings(cfg=None):
    """{'enabled', 'at', 'days'} — days 는 키트 표기('fri' · 'mon-fri' · 'mon,thu'). 목록으로 적어도 받는다."""
    w = (((cfg if cfg is not None else kit.load_config()).get('ai_share') or {}).get('weekly_report')) or {}
    days = w.get('days') or 'fri'
    if isinstance(days, (list, tuple)):
        days = ','.join(str(x).strip() for x in days if str(x).strip()) or 'fri'
    return {'enabled': bool(w.get('enabled')), 'at': str(w.get('at') or '16:00'), 'days': str(days)}


def is_due(w, state, now):
    if not w['enabled'] or not kit.due(w, state.get('last_run'), now):
        return False
    fail = state.get('last_fail')
    return not (isinstance(fail, (int, float)) and now.timestamp() - fail < RETRY_MIN * 60)


def run(ctx):
    w = settings()
    when = '%s %s' % (w['days'], w['at'])
    if not w['enabled']:
        if kit.read_status(FEATURE) is None:
            kit.write_status(FEATURE, [{'name': '주간 업무 보고 초안', 'ok': None, 'text': '꺼짐 · %s' % when}],
                             note='ai_share.weekly_report.enabled 를 켜면 돈다')
        return
    path = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(path, {}) or {}
    now = datetime.datetime.now()
    if not is_due(w, state, now):
        return
    try:
        extsvc.run_once(ctx, [extsvc.system_python(windowed=False), AGENT, 'weekly', '--kit-job'],
                        cwd=os.path.dirname(AGENT), timeout=META['timeout'] - 60)
    except BaseException as e:
        state.update(last_fail=now.timestamp())
        kit.write_json(path, state)
        kit.write_status(FEATURE, [{'name': '주간 업무 보고 초안', 'ok': False,
                                    'text': '%s · 실행 실패: %s' % (when, e)}], note='확인 %s' % time.strftime('%H:%M'))
        raise RuntimeError('주간 업무 보고 초안 실행 실패: %s' % e)
    state.update(last_run=now.timestamp(), last_fail=None)
    kit.write_json(path, state)
    ctx.log('주간 업무 보고 초안 — 끝 (결과는 「📊 기능 상태」)')
