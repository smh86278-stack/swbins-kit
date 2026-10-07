# -*- coding: utf-8 -*-
"""디스패치 대화(tools\\dispatch-chat\\chat.py) — 메일을 메신저처럼 보는 PC 화면 서버, 127.0.0.1:8620.

허브의 '💬 대화' 가 이 주소를 연다. 다른 PC 는 허브 없이 DispatchChat.exe 하나로 같은 대화를 본다.
'메일로 일 맡기기'(config.local.json 의 dispatch.enabled)가 꺼져 있으면 띄우지 않고 기다리기만 한다.
공통 동작은 extsvc.py 맨 위 설명."""
import os

import extsvc
import kit

ROOT = extsvc.ROOT
PORT = int(os.environ.get('DISPATCH_CHAT_PORT') or 8620)

# META 는 허브가 ast.literal_eval 로 읽으므로 글자 그대로여야 한다(설치 경로를 넣을 수 없다).
# 그래서 띄울 때 '--kit-service' 표식을 붙이고 그 표식으로 이 키트가 띄운 프로세스만 알아본다
# (같은 PC 의 다른 저장소에서 도는 같은 이름의 프로그램을 건드리지 않게).
META = {
    "name": "디스패치 대화 (8620)",
    "desc": "디스패치 대화(tools\\dispatch-chat) — 메일함의 지시·회신을 [T번호] 대화로 묶어 보여 주고, 입력한 말을 메일로 보낸다. dispatch.enabled 가 켜져 있어야 돈다.",
    "kind": "ctx",
    "target": "desktop",
    "motion": "mail",
    "service": True,
    "owns": [{"name": ["python.exe", "pythonw.exe"], "has": ["chat.py", "--serve", "--kit-service"]}],
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
    d = os.path.join(ROOT, 'tools', 'dispatch-chat')
    log = os.path.join(os.environ.get('LOCALAPPDATA', d), 'DispatchChat', 'chat.log')
    extsvc.supervise(ctx, [extsvc.system_python(), os.path.join(d, 'chat.py'), '--serve', '--kit-service'], META['owns'], cwd=d,
                     port=PORT, tail=log)
