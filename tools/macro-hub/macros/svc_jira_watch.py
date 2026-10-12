# -*- coding: utf-8 -*-
"""Jira 새 이슈 감시(jira-watch.py) — 조건(JQL)에 맞는 새 Jira 이슈를 디스패치 대화 앱으로 "지금 처리할까요?" 묻는다.

config.local.json 의 jira.enabled 가 꺼져 있으면 띄우지 않고 기다리기만 한다. 켜져 있어도 디스패치(dispatch.enabled)가
꺼져 있으면 물을 길이 없으므로 띄우지 않고 경고를 남긴다 — 둘 다 켜지면 1분 안에 띄운다. 공통 동작은 extsvc.py 맨 위 설명."""
import os

import extsvc
import kit

ROOT = extsvc.ROOT

# META 는 허브가 ast.literal_eval 로 읽으므로 글자 그대로여야 한다(설치 경로를 넣을 수 없다).
# 그래서 띄울 때 '--kit-service' 표식을 붙이고 그 표식으로 이 키트가 띄운 프로세스만 알아본다.
META = {
    "name": "Jira 새 이슈 감시",
    "desc": "Jira 새 이슈 감시(jira-watch.py) — 새 이슈를 대화 앱으로 '지금 처리 / 내가 직접' 묻고, 고르면 Claude Code 가 처리한다. jira.enabled 와 dispatch.enabled 가 둘 다 켜져 있어야 돈다.",
    "kind": "ctx",
    "target": "desktop",
    "motion": "mail",
    "service": True,
    "owns": [{"name": ["python.exe", "pythonw.exe"], "has": ["jira-watch.py", "--kit-service"]}],
}


def blocker(cfg):
    """지금 띄우면 안 되는 이유(없으면 '')."""
    if not (cfg.get('jira') or {}).get('enabled'):
        return 'Jira 새 이슈 감시(jira.enabled)가 꺼져 있어 기다립니다 — config.local.json 에서 켜면 띄웁니다'
    if not (cfg.get('dispatch') or {}).get('enabled'):
        return ('⚠ jira.enabled 는 켜져 있지만 디스패치(dispatch.enabled)가 꺼져 있어 띄우지 않습니다 — '
                '새 이슈를 대화 앱으로 물을 길이 없습니다. 디스패치를 켜면 띄웁니다')
    return ''


def wait_enabled(ctx, every=60):
    said = ''
    while True:
        why = blocker(kit.load_config())
        if not why:
            return
        if why != said:
            ctx.log(why)
            said = why
        ctx.sleep(every)


def run(ctx):
    wait_enabled(ctx)
    data = os.path.join(kit.DATA, 'jira')
    extsvc.supervise(ctx, [extsvc.system_python(), os.path.join(ROOT, 'jira-watch.py'), '--kit-service'], META['owns'], cwd=ROOT,
                     notify=os.path.join(data, 'notify.jsonl'), tail=os.path.join(data, 'jira-watch.log'))
