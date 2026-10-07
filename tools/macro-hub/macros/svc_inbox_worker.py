# -*- coding: utf-8 -*-
"""작업 인박스 워커(inbox-worker.ps1) — inbox\\jobs 의 지시를 claude -p 로 하나씩 실행한다.
허브를 꺼도 워커(와 돌던 claude 작업)는 계속 돈다. 허브에서 상시 실행을 끄면 그때 멈춘다(작업 중이면 그 작업도).

'메일로 일 맡기기'(config.local.json 의 dispatch.enabled)가 꺼져 있으면 워커를 띄우지 않고 기다리기만 한다.
공통 동작은 extsvc.py 맨 위 설명."""
import os

import extsvc
import kit

ROOT = extsvc.ROOT

# META 는 허브가 ast.literal_eval 로 읽으므로 글자 그대로여야 한다(설치 경로를 넣을 수 없다).
# 그래서 띄울 때 '-KitService' 표식을 붙이고 그 표식으로 이 키트가 띄운 프로세스만 알아본다
# (같은 PC 의 다른 저장소에서 도는 같은 이름의 프로그램을 건드리지 않게).
META = {
    "name": "작업 인박스 워커",
    "desc": "작업 인박스 워커(inbox-worker.ps1) — inbox\\jobs 의 지시를 claude -p 로 하나씩 실행한다. dispatch.enabled 가 켜져 있어야 돈다.",
    "kind": "ctx",
    "target": "desktop",
    "motion": "write",
    "service": True,
    "owns": [{"name": ["powershell.exe"], "has": ["inbox-worker.ps1", "-KitService"]}],
}


def wait_enabled(ctx, every=60):
    """dispatch.enabled 가 켜질 때까지 기다린다(꺼진 동안 아무것도 띄우지 않는다)."""
    said = False
    while not (kit.load_config().get('dispatch') or {}).get('enabled'):
        if not said:
            ctx.log('메일로 일 맡기기(dispatch.enabled)가 꺼져 있어 기다립니다 — config.local.json 에서 켜면 띄웁니다')
            said = True
        ctx.sleep(every)


def run(ctx):
    wait_enabled(ctx)
    inbox = os.path.join(ROOT, 'inbox')
    extsvc.supervise(ctx, ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                           '-File', os.path.join(ROOT, 'inbox-worker.ps1'), '-KitService'], META['owns'], cwd=ROOT,
                     notify=os.path.join(inbox, 'notify.jsonl'), tail=os.path.join(inbox, 'worker.log'),
                     state=os.path.join(inbox, 'state.json'), busy={'busy': 'write'})
