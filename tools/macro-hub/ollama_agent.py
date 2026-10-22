# -*- coding: utf-8 -*-
"""로컬 AI(Ollama)로 🛠 말로 부탁하기 · 🩹 고쳐 달라기 — 표준 라이브러리만.

로컬 모델은 Claude·Codex 처럼 스스로 파일을 읽고 명령을 돌리지 못한다. 그래서 이 스크립트가 손발이 된다.
  1. 안내서(AUTHORING.md)와 부탁 글에 나온 내 자동화 파일 내용을 모델에게 같이 준다.
  2. 모델은 파일을 아래 모양으로 돌려준다 — 이 스크립트가 macros.local 안의 .py 만 쓴다(그 밖은 무시).
        === FILE: macros.local/<이름>.py ===
        (코드 전체)
        === END ===
  3. ai.ollama_test 가 켜져 있으면 runner.py --test 로 시험하고, 실패하면 로그를 보여 주고 다시(최대 3번).
     꺼져 있으면(기본) 쓰기까지만 — 모델이 만든 코드를 묻지 않고 돌리지 않는다. 시험은 카드의 🧪 시험으로.
  4. 고친 파일의 원래 내용은 data.local\\ai-backup\\ 에 남긴다.
허브(macrohub.start_ai_run)가 띄우고, 부탁 글은 표준 입력으로 받는다. 출력은 그대로 실행 기록 로그가 된다.

    python ollama_agent.py --model qwen3:8b [--url http://127.0.0.1:11434] [--test]  < 부탁글
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, 'macros.local')
BACKUP = os.path.join(HERE, 'data.local', 'ai-backup')
AUTHORING = os.path.join(HERE, 'AUTHORING.md')
TRIES = 3
TEST_TIMEOUT = 300
FILE_RE = re.compile(r'^=== FILE: (?P<path>[^\r\n]+?) ===[ \t]*\r?\n(?P<body>.*?)^=== END ===', re.M | re.S)
THINK_RE = re.compile(r'<think>.*?</think>', re.S)
MENTION_RE = re.compile(r'macros\.local[\\/][\w\-. ]+?\.py', re.I)

SYSTEM = """너는 Windows 업무 자동화 허브의 파이썬 자동화를 만드는 도우미다. 아래 안내서를 따른다.
너는 파일을 직접 쓰거나 명령을 돌릴 수 없다. 만들거나 고친 파일은 반드시 이 모양으로 **전체 내용**을 돌려준다:
=== FILE: macros.local/<영문_소문자_이름>.py ===
(파일 전체 코드 — 마크다운 ``` 울타리 없이)
=== END ===
- 파일은 macros.local 폴더의 .py 만. 다른 곳은 쓰지 않는다.
- 되돌릴 수 없는 동작(메일 보내기·제출·삭제)은 ctx.for_real(...) 로 감싼다. 비밀번호는 ctx.secret('이름') 으로.
- 파일 블록 다음에 사용자에게 할 말을 쉬운 한국어로 3~6줄: 무엇을 만들었는지, 처음 한 번 사람이 할 일(로그인·비밀값), 시험하는 법.

--- 안내서(AUTHORING.md) ---
"""


def log(*a):
    print(*a, flush=True)


def chat(url, model, messages, timeout=1800):
    """Ollama /api/chat 을 스트림으로 — 답 전체를 돌려주고, 쓰는 동안 몇 초마다 진행을 알린다."""
    body = {'model': model, 'messages': messages, 'stream': True,
            'options': {'temperature': 0.2, 'num_ctx': 16384}}
    req = urllib.request.Request(url.rstrip('/') + '/api/chat', data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    parts, last = [], time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for line in r:
                if not line.strip():
                    continue
                d = json.loads(line.decode('utf-8'))
                if d.get('error'):
                    raise RuntimeError(d['error'])
                parts.append((d.get('message') or {}).get('content') or '')
                if time.time() - last > 5:
                    last = time.time()
                    log('  … 쓰는 중 (%d자)' % sum(len(p) for p in parts))
                if d.get('done'):
                    break
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf-8', 'replace')[:300]
        if e.code == 404:
            raise RuntimeError('모델 %s 이 없습니다 — 명령 창에서 ollama pull %s (%s)' % (model, model, msg))
        raise RuntimeError('Ollama 오류 %s: %s' % (e.code, msg))
    except urllib.error.URLError as e:
        raise RuntimeError('Ollama 에 연결하지 못했습니다(%s) — Ollama 를 설치하고 켜 두세요: https://ollama.com' % e.reason)
    return THINK_RE.sub('', ''.join(parts)).strip()


def safe_target(rel):
    """모델이 적은 경로 → macros.local 안의 .py 절대 경로. 밖이면 None."""
    rel = rel.strip().strip('`"\'').replace('\\', '/')
    name = rel.split('/', 1)[1] if rel.lower().startswith('macros.local/') else rel
    if '/' in name or not re.fullmatch(r'[\w\-.]+\.py', name) or name.startswith('.'):
        return None
    path = os.path.realpath(os.path.join(LOCAL, name))
    return path if os.path.dirname(path) == os.path.realpath(LOCAL) else None


def parse_files(answer):
    out = []
    for m in FILE_RE.finditer(answer):
        body = m.group('body')
        body = re.sub(r'^```[\w]*\r?\n', '', body)
        body = re.sub(r'\r?\n```[ \t]*\r?\n?$', '\n', body)
        out.append((m.group('path'), body.rstrip() + '\n'))
    return out


def write_files(files):
    written = []
    for rel, body in files:
        path = safe_target(rel)
        if not path:
            log('⚠ 쓰지 않음(내 자동화 폴더 밖): %s' % rel)
            continue
        os.makedirs(LOCAL, exist_ok=True)
        if os.path.isfile(path):
            os.makedirs(BACKUP, exist_ok=True)
            bak = os.path.join(BACKUP, '%s.%s' % (os.path.basename(path), time.strftime('%Y%m%d-%H%M%S')))
            shutil.copy2(path, bak)
            log('  원래 파일은 %s 에 남겼습니다' % bak)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
        log('✔ 썼습니다: %s' % path)
        written.append(path)
    return written


def mentioned(prompt):
    """부탁 글에 나온 내 자동화 파일 — 고쳐 달라기는 그 파일 내용을 모델에게 같이 준다."""
    seen, out = set(), []
    for m in MENTION_RE.finditer(prompt):
        path = safe_target(m.group(0).replace('\\', '/'))
        if path and path not in seen and os.path.isfile(path):
            seen.add(path)
            with open(path, encoding='utf-8', errors='replace') as f:
                out.append((path, f.read()))
    return out


def run_test(python, path):
    try:
        p = subprocess.run([python, '-u', os.path.join(HERE, 'runner.py'), '--test', path], cwd=HERE,
                           capture_output=True, timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, '시험이 %d초 안에 끝나지 않았습니다' % TEST_TIMEOUT
    out = (p.stdout + p.stderr).decode('utf-8', 'replace')
    return p.returncode == 0, out[-3000:]


def strip_files(answer):
    return FILE_RE.sub('', answer).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='qwen3:8b')
    ap.add_argument('--url', default='http://127.0.0.1:11434')
    ap.add_argument('--test', action='store_true', help='만든 파일을 runner.py --test 로 시험하고 실패하면 다시(최대 3번)')
    ap.add_argument('--python', default=sys.executable)
    a = ap.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    prompt = sys.stdin.buffer.read().decode('utf-8', 'replace').strip()
    if not prompt:
        log('부탁 글이 비어 있습니다')
        return 2
    try:
        with open(AUTHORING, encoding='utf-8') as f:
            guide = f.read()
    except OSError:
        guide = '(안내서를 찾지 못함)'
    user = prompt
    for path, body in mentioned(prompt):
        user += '\n\n--- 지금 파일 내용: macros.local/%s ---\n%s' % (os.path.basename(path), body)
    messages = [{'role': 'system', 'content': SYSTEM + guide}, {'role': 'user', 'content': user}]
    log('▶ 로컬 AI(%s)에게 맡깁니다 — PC 사양에 따라 몇 분 걸릴 수 있습니다' % a.model)
    for n in range(1, TRIES + 1):
        try:
            answer = chat(a.url, a.model, messages)
        except RuntimeError as e:
            log('✖ %s' % e)
            return 1
        files = parse_files(answer)
        if not files:
            log('⚠ 모델이 파일을 돌려주지 않았습니다. 받은 답:')
            log(answer[:2000])
            if n == TRIES:
                return 1
            messages += [{'role': 'assistant', 'content': answer},
                         {'role': 'user', 'content': '파일을 "=== FILE: macros.local/<이름>.py ===" … "=== END ===" 모양으로 전체 내용을 다시 줘.'}]
            continue
        written = write_files(files)
        if not written:
            return 1
        if not a.test:
            log('')
            log(strip_files(answer) or '만들었습니다.')
            log('')
            log('ℹ 로컬 AI 는 만든 코드를 직접 돌려 보지 않습니다 — 카드의 🧪 시험으로 확인하세요(설정 ai.ollama_test 를 켜면 허브가 시험까지)')
            return 0
        fails = []
        for path in written:
            ok, out = run_test(a.python, path)
            log('%s 시험 %s' % ('✔' if ok else '✖', os.path.basename(path)))
            if not ok:
                fails.append('%s 시험 실패:\n%s' % (os.path.basename(path), out))
        if not fails:
            log('')
            log(strip_files(answer) or '만들고 시험까지 마쳤습니다.')
            return 0
        if n == TRIES:
            log('✖ %d번 고쳐도 시험이 통과하지 않았습니다. 마지막 로그:' % TRIES)
            log('\n'.join(fails)[-2000:])
            return 1
        log('↻ 시험 실패 — 로그를 보여 주고 다시 고치게 합니다 (%d/%d)' % (n + 1, TRIES))
        messages += [{'role': 'assistant', 'content': answer},
                     {'role': 'user', 'content': '\n\n'.join(fails) + '\n\n원인을 고쳐 파일 전체를 같은 모양으로 다시 줘.'}]
    return 1


if __name__ == '__main__':
    sys.exit(main())
