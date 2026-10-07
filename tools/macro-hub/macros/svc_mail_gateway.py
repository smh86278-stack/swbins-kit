# -*- coding: utf-8 -*-
"""메일 게이트웨이(mail-gateway.py) — 태그 단 메일을 인박스 작업으로 넣고 결과를 답장한다.

'메일로 일 맡기기'(config.local.json 의 dispatch.enabled)가 꺼져 있으면 게이트웨이를 띄우지 않고 기다리기만 한다 —
켜면 1분 안에 띄운다. 공통 동작은 extsvc.py 맨 위 설명."""
import os

import extsvc
import kit

ROOT = extsvc.ROOT

# META 는 허브가 ast.literal_eval 로 읽으므로 글자 그대로여야 한다(설치 경로를 넣을 수 없다).
# 그래서 띄울 때 '--kit-service' 표식을 붙이고 그 표식으로 이 키트가 띄운 프로세스만 알아본다
# (같은 PC 의 다른 저장소에서 도는 같은 이름의 프로그램을 건드리지 않게).
META = {
    "name": "메일 게이트웨이",
    "desc": "메일 게이트웨이(mail-gateway.py) — 태그 단 메일을 인박스 작업으로 넣고 결과를 답장한다. dispatch.enabled 가 켜져 있어야 돈다.",
    "kind": "ctx",
    "target": "desktop",
    "motion": "mail",
    "service": True,
    "owns": [{"name": ["python.exe", "pythonw.exe"], "has": ["mail-gateway.py", "--kit-service"]}],
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
    extsvc.supervise(ctx, [extsvc.system_python(), os.path.join(ROOT, 'mail-gateway.py'), '--kit-service'], META['owns'], cwd=ROOT,
                     notify=os.path.join(inbox, 'mail-notify.jsonl'), tail=os.path.join(inbox, 'mail-gateway.log'))
