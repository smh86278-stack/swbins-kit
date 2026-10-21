# -*- coding: utf-8 -*-
"""AI 고르기 — Claude Code · Codex(ChatGPT) · Gemini CLI. 표준 라이브러리만.

설정 config.local.json 의 "ai":
    {"engine": "claude" | "codex" | "gemini", "model": "", "gemini_approval": "auto_edit" | "yolo"}

AI 를 쓰는 곳은 두 가지다.
- 글만 쓰는 일(주간 보고 초안·발표 자료) → text(prompt) 가 답 글만 돌려받는다. 파일·명령은 못 건드리게 띄운다.
- 일을 하는 일(🛠 말로 부탁하기 · 🩹 고쳐 달라기) → agent_cmd() 로 허브가 그 폴더에서 직접 띄운다.
  claude 는 지금까지처럼 디스패치 대화(권한 묻기·허용 도구 목록·자리비움)를 거친다 — 그 안전장치가 Claude 방식에
  맞춰져 있어서다. 메일·대화로 일 맡기기는 그래서 Claude 전용으로 남는다.
  codex  : codex exec --cd <폴더> --sandbox workspace-write — 그 폴더 안에서만 쓰고, 시험 실행(runner.py --test)의
           웹 자동화가 돌게 네트워크는 연다. 프롬프트는 표준 입력으로(따옴표·줄바꿈이 명령줄에서 깨지지 않게).
  gemini : gemini -p --approval-mode auto_edit — 파일 고치기만 저절로, 명령 실행(시험)은 못 한다. 'yolo' 로 바꾸면
           명령도 묻지 않고 돈다(샌드박스 없음 — 이 PC 를 믿을 때만). 프롬프트는 표준 입력으로(-p 뒤에 덧붙는다 — -p 문구는 영문, cmd.exe 를 거쳐도 깨지지 않게).
명령줄 옵션은 codex-cli 0.63 의 `codex exec --help`, Gemini CLI 문서 docs/cli/cli-reference.md(2026-10) 기준.
"""
import os
import shutil
import subprocess
import tempfile

import kit

ENGINES = ('claude', 'codex', 'gemini')
NAMES = {'claude': 'Claude Code', 'codex': 'Codex (ChatGPT)', 'gemini': 'Gemini CLI'}
INSTALL = {'claude': 'npm install -g @anthropic-ai/claude-code',
           'codex': 'npm install -g @openai/codex  (그다음 codex login)',
           'gemini': 'npm install -g @google/gemini-cli  (그다음 gemini 한 번 실행해 로그인)'}
GEMINI_APPROVALS = ('auto_edit', 'yolo')


def settings(cfg=None):
    s = dict(kit.section('ai', {}, cfg) or {})
    engine = s.get('engine') if s.get('engine') in ENGINES else 'claude'
    approval = s.get('gemini_approval') if s.get('gemini_approval') in GEMINI_APPROVALS else 'auto_edit'
    return {'engine': engine, 'model': str(s.get('model') or '').strip(), 'gemini_approval': approval}


def set_engine(engine, via='허브'):
    """허브 화면에서 고른 엔진을 config.local.json 의 ai.engine 에 저장한다(다른 설정은 그대로)."""
    if engine not in ENGINES:
        raise ValueError('엔진은 %s 중 하나입니다' % ' · '.join(ENGINES))
    cfg = kit._read(kit.F_CONFIG)               # 기본값을 채우지 않은 원래 파일 — 기본값까지 써 넣지 않게
    ai = dict(cfg.get('ai') or {})
    ai['engine'] = engine
    cfg['ai'] = ai
    kit.save_config(cfg, via=via)
    return settings(cfg)


def exe(engine):
    """설치된 실행 파일 경로(없으면 None). npm 으로 깔면 codex.cmd 처럼 .cmd 다."""
    return shutil.which(engine)


def status(cfg=None):
    """허브 화면용 — 고른 엔진과 엔진마다 깔렸는지."""
    s = settings(cfg)
    return dict(s, name=NAMES[s['engine']],
                engines=[{'id': e, 'name': NAMES[e], 'installed': bool(exe(e)), 'install': INSTALL[e]} for e in ENGINES])


def _shell(path):
    # .cmd(npm 설치)는 cmd.exe 를 거쳐야 뜬다. 인자는 단순한 것만 넘기고 프롬프트는 표준 입력으로.
    return os.name == 'nt' and not str(path).lower().endswith('.exe')


def _model(args, model):
    return args + (['-m', model] if model else [])


def agent_cmd(engine, workdir, s=None):
    """일을 하는 AI 를 workdir 에서 띄울 명령 — (argv, shell, 알릴 말). 프롬프트는 표준 입력으로 넘긴다."""
    s = s or settings()
    path = exe(engine)
    if engine not in ('codex', 'gemini'):
        raise ValueError('허브가 직접 띄우는 엔진은 codex · gemini 입니다 (claude 는 디스패치 대화로)')
    if not path:
        raise RuntimeError('%s 가 이 PC 에 없습니다 — %s' % (NAMES[engine], INSTALL[engine]))
    if engine == 'codex':
        argv = _model([path, 'exec', '--cd', workdir, '--sandbox', 'workspace-write',
                       '-c', 'sandbox_workspace_write.network_access=true',
                       '--skip-git-repo-check', '--color', 'never'], s['model']) + ['-']
        note = ''
    else:
        argv = _model([path, '-p', 'Follow the request given on standard input.', '--approval-mode', s['gemini_approval'],
                       '-o', 'text'], s['model'])
        note = ('' if s['gemini_approval'] == 'yolo' else
                'Gemini 는 지금 파일 고치기만 합니다(설정 ai.gemini_approval = auto_edit) — 시험은 카드의 🧪 시험으로 해 주세요')
    return argv, _shell(path), note


def agent_prompt(engine, text, s=None):
    """엔진마다 덧붙일 말 — Gemini 가 명령을 못 돌리는 설정이면 시험 대신 보고하게."""
    s = s or settings()
    if engine == 'gemini' and s['gemini_approval'] != 'yolo':
        return text + ('\n(이 환경에서는 명령을 실행할 수 없어 — 시험 실행은 건너뛰고, 만든 파일과 '
                       '내가 허브 카드의 🧪 시험으로 확인할 점을 쉬운 말로 알려 줘)')
    return text


def text(prompt, engine, model='', timeout=1800):
    """글만 쓰는 일 — 답 글을 돌려준다. 실패하면 RuntimeError. claude 는 부르는 쪽(agent.run_claude)이 따로 한다."""
    path = exe(engine)
    if engine not in ('codex', 'gemini'):
        raise ValueError('text() 는 codex · gemini 용입니다')
    if not path:
        raise RuntimeError('%s 가 이 PC 에 없습니다 — %s' % (NAMES[engine], INSTALL[engine]))
    cwd = tempfile.mkdtemp(prefix='ai-text-')          # 프로젝트 파일·설정이 자료에 섞이지 않게 빈 폴더에서
    out_file = os.path.join(cwd, 'answer.md')
    if engine == 'codex':
        argv = _model([path, 'exec', '--cd', cwd, '--sandbox', 'read-only', '--skip-git-repo-check',
                       '--color', 'never', '-o', out_file], model) + ['-']
    else:
        argv = _model([path, '-p', 'Follow the instructions given on standard input and reply with the text only.', '-o', 'text'], model)
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}
    try:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=cwd, env=env, shell=_shell(path))
        try:
            out, err = p.communicate(prompt.encode('utf-8'), timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True) if os.name == 'nt' else p.kill()
            raise RuntimeError('%s 가 %d분 안에 끝나지 않아 껐습니다' % (NAMES[engine], timeout // 60))
        if p.returncode != 0:
            raise RuntimeError('%s 실행 실패 (rc=%s): %s' % (NAMES[engine], p.returncode,
                                                         (err or out).decode('utf-8', 'replace')[:800]))
        if engine == 'codex' and os.path.isfile(out_file):
            with open(out_file, encoding='utf-8', errors='replace') as f:
                return f.read()
        return out.decode('utf-8', 'replace')
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
