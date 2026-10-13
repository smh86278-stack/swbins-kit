# -*- coding: utf-8 -*-
"""AI 공유 위키(tools\\ai-share-agent\\agent.py serve) — 내 이슈·커밋을 모아 보는 화면 서버, 127.0.0.1:<ai_share.port>(기본 8640).

허브 화면의 '📚 AI 위키' 가 이 주소를 연다. config.local.json 의 ai_share.enabled 가 꺼져 있으면 띄우지 않고 기다리기만 한다.
주간 업무 보고 초안의 예약 실행은 이 서버가 아니라 job_weekly_report 가 맡는다. 공통 동작은 extsvc.py 맨 위 설명."""
import os

import extsvc
import kit

ROOT = extsvc.ROOT

# META 는 허브가 ast.literal_eval 로 읽으므로 글자 그대로여야 한다(설치 경로를 넣을 수 없다).
# 그래서 띄울 때 '--kit-service' 표식을 붙이고 그 표식으로 이 키트가 띄운 프로세스만 알아본다
# (같은 PC 의 다른 저장소에서 도는 같은 이름의 프로그램을 건드리지 않게).
META = {
    "name": "AI 공유 위키 (8640)",
    "desc": "AI 공유 위키(tools\\ai-share-agent) — 이슈 출처(Jira·GitHub·GitLab·없음)와 git 커밋을 모아 보는 화면. 주간 보고 초안·발표 준비도 여기서. ai_share.enabled 가 켜져 있어야 돈다.",
    "kind": "ctx",
    "target": "desktop",
    "motion": "write",
    "service": True,
    "owns": [{"name": ["python.exe", "pythonw.exe"], "has": ["ai-share-agent", "agent.py", "serve", "--kit-service"]}],
}


def settings(cfg=None):
    a = (cfg if cfg is not None else kit.load_config()).get('ai_share') or {}
    try:
        port = int(a.get('port') or 8640)
    except (TypeError, ValueError):
        port = 8640
    return bool(a.get('enabled')), port


def wait_enabled(ctx, every=60):
    """ai_share.enabled 가 켜질 때까지 기다린다(꺼진 동안 아무것도 띄우지 않는다)."""
    said = False
    while not settings()[0]:
        if not said:
            ctx.log('AI 공유 위키(ai_share.enabled)가 꺼져 있어 기다립니다 — config.local.json 에서 켜면 띄웁니다')
            said = True
        ctx.sleep(every)


def run(ctx):
    wait_enabled(ctx)
    port = settings()[1]
    d = os.path.join(ROOT, 'tools', 'ai-share-agent')
    log = os.path.join(kit.DATA, 'ai_share', 'serve.log')
    extsvc.supervise(ctx, [extsvc.system_python(), os.path.join(d, 'agent.py'), 'serve', '--no-browser',
                           '--port', str(port), '--kit-service'], META['owns'], cwd=d, log=log, port=port, tail=log)
