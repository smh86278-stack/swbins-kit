# -*- coding: utf-8 -*-
"""공개 도움말·개발자 안내(docs/index.html)를 코드에서 만든다 — 손으로 고치지 말고 이것을 다시 돌린다.

    python docs/build_docs.py          docs/index.html 다시 쓰기
    python docs/build_docs.py --check  지금 코드와 어긋났으면 1 (tests/test_docs.py 가 쓴다)

재료(코드가 바뀌면 문서도 따라 바뀐다)
  - config.example.json   기능(갈래)마다 견본 값과 "_…설명" 문구
  - 자동화·도구 파일의 맨 위 설명(docstring) — ast 로 읽기만 하고 실행하지 않는다
  - tools/macro-hub/runner.py 의 Ctx 메서드 설명 — 자동화가 쓰는 ctx 도구 목록
  - tools/macro-hub/kit.py 의 CHANNEL_TYPES · channel_payload — 알림 출구가 보내는 JSON
회사 이름·주소·계정은 넣지 않는다(키트 규칙). 표준 라이브러리만.
"""
import ast
import html
import io
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')
OUT = os.path.join(ROOT, 'docs', 'index.html')

# 갈래 → (보이는 이름, 설명을 더 읽을 파일). 순서가 곧 문서 순서다.
SECTIONS = [
    ('company', '회사', None),
    ('mail', '메일 계정 · 알림 메일', None),
    ('notify', '알림 출구(슬랙·Teams·웹훅)', None),
    ('scheduled_mails', '정기 메일', 'tools/macro-hub/macros/job_scheduled_mail.py'),
    ('tidy', '폴더 정리', 'tools/macro-hub/macros/job_tidy.py'),
    ('monitors', '사이트·서버 감시', 'tools/macro-hub/macros/job_monitors.py'),
    ('pc_watch', 'PC 디스크 감시', 'tools/macro-hub/macros/job_pc_watch.py'),
    ('backups', '폴더 백업', 'tools/macro-hub/macros/job_backup.py'),
    ('cred_watch', '로그인·키 만료 예고', 'tools/macro-hub/macros/job_cred_watch.py'),
    ('morning_brief', '아침 브리핑', 'tools/macro-hub/macros/job_morning_brief.py'),
    ('market_notice', '마켓 장애 공지 감시', 'tools/macro-hub/macros/job_market_notice.py'),
    ('category_watch', '카테고리·정보고시 변경 감시', 'tools/macro-hub/macros/job_category_watch.py'),
    ('rate_limits', 'API 호출 한도 조절 · 미터기', 'tools/macro-hub/ratelimit.py'),
    ('links', '바로가기', None),
    ('dispatch', '디스패치(메일 → Claude Code, 고급)', 'mail-gateway.py'),
    ('jira', 'Jira 새 이슈 감시(고급)', 'jira-watch.py'),
    ('ai_share', 'AI 공유 위키 · 주간 보고 초안', 'tools/ai-share-agent/agent.py'),
]
FIXED = {
    'company': '회사 이름 — 알림 메일 제목 앞에 [이름] 으로 붙는다. 비워도 된다.',
    'mail': '알림·감시 메일을 보내고 받는 계정. 비밀번호는 이 PC·이 Windows 사용자만 풀 수 있게 암호화한 password_enc 로만 저장된다 '
            '— 「메일·계정 설정」 창(setup_gui.py) 이나 python setup.py 로 넣는다. alert_via 가 append 면 보내지 않고 내 받은편지함에 넣는다.',
    'links': '허브 트레이 메뉴에 띄울 사내 사이트 바로가기 [{"name", "url"}].',
}
HUB_API = [
    ('GET', '/api/macros', '자동화 목록(켜짐·트리거·마지막 실행)'),
    ('GET', '/api/runs', '최근 실행 기록'),
    ('GET', '/api/run?id=', '실행 하나의 로그'),
    ('GET', '/api/schedule', '예약 작업과 다음 실행 시각'),
    ('GET', '/api/audit', '변경 이력(누가·어디서·언제) — 새것 먼저'),
    ('GET', '/api/ops/features', '기능 상태(각 기능이 마지막에 남긴 결과)'),
    ('POST', '/api/run', '{"id", "params"} 지금 실행'),
    ('POST', '/api/stop', '{"run"} 실행 멈추기'),
    ('POST', '/api/enable', '{"id", "enabled"} 켜고 끄기'),
    ('POST', '/api/schedule', '{"id", "schedule": [...]} 예약 시각 바꾸기 · {"id", "reset": true} 되돌리기'),
    ('POST', '/api/service', '{"id", "action": "start|stop|restart|run"}'),
    ('POST', '/api/ask', '{"text"} 「말로 부탁하기」 — 디스패치 대화(8620)에 쓰기 지시로 바로 보낸다(대화가 켜져 있을 때)'),
    ('POST', '/api/fix', '{"id", "send"} 🩹 고쳐 달라기 — 실패한 내 자동화(macros.local) 실행의 이름·파일·로그 끝 40줄로 부탁 글을 만든다. '
                         'send 면 /api/ask 처럼 대화로 보내고, 아니면 글만 돌려준다'),
]


def doc_of(rel):
    """파일 맨 위 설명 — 실행하지 않고 ast 로만."""
    path = os.path.join(ROOT, rel)
    try:
        with open(path, encoding='utf-8') as f:
            return ast.get_docstring(ast.parse(f.read())) or ''
    except (OSError, SyntaxError):
        return ''


def ctx_methods():
    """runner.Ctx 의 공개 메서드·속성과 설명 첫 문단."""
    with open(os.path.join(HUB, 'runner.py'), encoding='utf-8') as f:
        tree = ast.parse(f.read())
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'Ctx':
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and not fn.name.startswith('_') and fn.name != 'close':
                    prop = any(isinstance(d, ast.Name) and d.id == 'property' for d in fn.decorator_list)
                    args = [a.arg for a in fn.args.args[1:]] + (['*' + fn.args.vararg.arg] if fn.args.vararg else [])
                    sig = 'ctx.%s' % fn.name if prop else 'ctx.%s(%s)' % (fn.name, ', '.join(args))
                    out.append((sig, (ast.get_docstring(fn) or '').split('\n\n')[0].replace('\n', ' ')))
    return out


def channel_info():
    """kit.py 를 import 해서 출구 종류와 일반 웹훅 JSON 견본을 얻는다(kit 은 표준 라이브러리만이라 안전하다)."""
    sys.path.insert(0, HUB)
    import kit
    sample = kit.channel_payload('webhook', '[감시] 홈페이지 접속 안 됨', '홈페이지(https://example.com)에 접속할 수 없습니다.', now=1791900000)
    sample['source'] = '예시상사'
    return kit.CHANNEL_TYPES, json.dumps(sample, ensure_ascii=False, indent=2)


def e(s):
    return html.escape(str(s), quote=True)


def section_html(key, title, src, conf):
    v = conf.get(key)
    texts = []
    if key in FIXED:
        texts.append(FIXED[key])
    if isinstance(v, dict):
        texts += [str(x) for k, x in v.items() if k.startswith('_') and isinstance(x, str)]
    sample = {k: x for k, x in v.items() if not k.startswith('_')} if isinstance(v, dict) else v
    parts = ['<section id="cfg-%s"><h3>%s <code>%s</code></h3>' % (e(key), e(title), e(key))]
    parts += ['<p>%s</p>' % e(t) for t in texts]
    d = doc_of(src) if src else ''
    if d:
        parts.append('<details><summary>자세한 동작 (%s)</summary><pre>%s</pre></details>' % (e(src), e(d)))
    if sample not in (None, {}, []):
        parts.append('<details><summary>설정 견본</summary><pre>%s</pre></details>' % e(json.dumps({key: sample}, ensure_ascii=False, indent=2)))
    parts.append('</section>')
    return '\n'.join(parts)


CSS = """
:root{--bg:#f7f4fc;--panel:#fff;--text:#2f2b45;--muted:#6f6990;--line:#e6dff3;--accent:#7a60e6;--code:#f1edfa}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#1a1826;--panel:#232033;--text:#ece8fa;--muted:#a59fbe;--line:#363150;--accent:#b0a0ff;--code:#2c2840}}
:root[data-theme="dark"]{--bg:#1a1826;--panel:#232033;--text:#ece8fa;--muted:#a59fbe;--line:#363150;--accent:#b0a0ff;--code:#2c2840}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 "Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:24px 16px 64px}
header{padding:28px 0 8px}
h1{font-size:26px;margin:0 0 6px}h2{font-size:20px;margin:36px 0 10px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:16px;margin:22px 0 6px}h3 code{font-size:12px;color:var(--muted);font-weight:600}
p,li{color:var(--text)}.lead{color:var(--muted)}
a{color:var(--accent)}
nav.toc{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}
nav.toc a{border:1px solid var(--line);background:var(--panel);border-radius:99px;padding:2px 12px;text-decoration:none;font-size:13px}
code{background:var(--code);border-radius:5px;padding:0 4px;font:13px ui-monospace,Consolas,monospace}
pre{background:var(--code);border:1px solid var(--line);border-radius:10px;padding:10px 12px;overflow:auto;font:12.5px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
details{margin:6px 0}summary{cursor:pointer;color:var(--muted);font-size:13.5px}
table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:700;white-space:nowrap}
td code{white-space:nowrap}
.note{border-left:3px solid var(--accent);background:var(--panel);padding:8px 12px;border-radius:0 10px 10px 0;margin:10px 0}
footer{margin-top:40px;color:var(--muted);font-size:13px}
"""

VERIFY_PY = '''import hashlib, hmac

def verify(secret: str, body: bytes, header: str) -> bool:
    """X-Kit-Signature: sha256=<hex> 를 확인한다. body 는 받은 그대로의 바이트."""
    want = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header or "")'''

VERIFY_JS = '''const crypto = require("crypto");

function verify(secret, rawBody, header) {          // rawBody: 받은 그대로의 Buffer
  const want = "sha256=" + crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
  return header && want.length === header.length && crypto.timingSafeEqual(Buffer.from(want), Buffer.from(header));
}'''

MACRO_SAMPLE = '''# macros.local/job_my_report.py — 허브가 이 폴더를 읽어 목록에 띄운다(처음엔 꺼져 있음)
import kit

META = {
    "name": "내 보고서 확인 (평일 09:10)",
    "desc": "보고서 폴더에 오늘 파일이 있는지 보고 없으면 알린다.",
    "kind": "ctx",
    "target": "desktop",
    "triggers": [{"type": "schedule", "at": "09:10", "days": "mon-fri"}],
    "timeout": 120,
}


def run(ctx):
    import datetime, os
    folder = kit.expand(r"%USERPROFILE%\\Documents\\reports")
    today = datetime.date.today().strftime("%Y%m%d")
    if not any(today in n for n in os.listdir(folder)):
        kit.alert("[보고서] 오늘 파일 없음", "%s 에 %s 파일이 없습니다." % (folder, today))   # 메일 + 알림 출구
        ctx.notify("보고서", "오늘 파일이 없습니다", "warning")                        # 트레이 풍선
    ctx.log("확인 끝")'''


def build():
    with open(os.path.join(ROOT, 'config.example.json'), encoding='utf-8') as f:
        conf = json.load(f)
    types, sample = channel_info()
    feats = [(k, t) for k, t, _ in SECTIONS]
    toc = ''.join('<a href="#%s">%s</a>' % (a, t) for a, t in (
        ('start', '시작하기'), ('features', '기능'), ('config', '기능별 설정'), ('notify', '알림 받는 쪽'),
        ('macro', '자동화 만들기'), ('api', '허브 API'), ('trouble', '문제 해결')))
    body = []
    body.append('<header><h1>업무 자동화 키트 — 도움말</h1>'
                '<p class="lead">어느 회사에서나 쓰는 Windows 업무 자동화 키트. 트레이에 상주하는 <b>자동화 허브</b>가 예약 작업·감시·알림을 맡고, '
                '회사마다 다른 값은 <code>config.local.json</code> 한 곳에 둔다.</p>'
                '<nav class="toc">%s</nav></header>' % toc)
    body.append('<h2 id="start">시작하기</h2><ol>'
                '<li>설치 파일(<code>WorkKitSetup-…exe</code>)을 실행하거나, 저장소를 받아 <code>python setup.py</code> — 처음 설정(회사 이름·메일 계정·알림 받는 곳).</li>'
                '<li>허브를 띄운다(트레이 아이콘). 화면은 이 PC 에서만 열린다: <code>http://127.0.0.1:8630/</code></li>'
                '<li>운영 화면 <code>/ops</code> 의 「⏰ 예약 작업」에서 쓸 기능을 켜고, 대상은 <code>config.local.json</code> 에 적는다(아래 견본).</li>'
                '<li>슬랙·Teams 로도 받으려면 <code>python setup.py --webhook</code>. 알림 시험은 <code>python setup.py --test</code>.</li></ol>'
                '<div class="note">비밀번호·토큰·웹훅 주소는 Windows DPAPI 로 이 PC·이 사용자에 묶어 암호화한 값만 파일에 남는다. '
                '허브는 <code>127.0.0.1</code> 에만 열린다 — 다른 PC 에서 들어올 수 없다.</div>')
    body.append('<h2 id="features">기능</h2><table><tr><th>기능</th><th>설정 갈래</th></tr>%s</table>'
                % ''.join('<tr><td><a href="#cfg-%s">%s</a></td><td><code>%s</code></td></tr>' % (e(k), e(t), e(k))
                          for k, t in feats if k in conf))
    body.append('<h2 id="config">기능별 설정</h2><p>모두 저장소 맨 위 <code>config.local.json</code> 에 적는다(견본 <code>config.example.json</code>). '
                '"_" 로 시작하는 키는 설명이라 지워도 된다.</p>')
    body += [section_html(k, t, src, conf) for k, t, src in SECTIONS if k in conf]
    body.append('<h2 id="notify">알림 받는 쪽 (웹훅)</h2>'
                '<p>모든 알림(실패 알림·감시·로그인·키·마켓 공지·카테고리)은 메일과 함께 <code>notify.channels</code> 의 출구로도 간다. '
                '출구 종류: %s. 주소는 <code>python setup.py --webhook</code> 으로 넣고, https 만 받는다.</p>'
                '<h3>일반 웹훅 <code>type: webhook</code> 이 보내는 JSON</h3><pre>%s</pre>'
                '<p>서명 비밀을 넣었으면 머리글 <code>X-Kit-Signature: sha256=&lt;HMAC-SHA256(비밀, 본문)&gt;</code> 이 붙는다. 받는 쪽에서 본문 바이트 그대로 확인한다.</p>'
                '<details open><summary>Python</summary><pre>%s</pre></details><details><summary>Node.js</summary><pre>%s</pre></details>'
                '<p>보낸 기록(성공·실패·HTTP 코드)은 운영 화면 「📊 기능 상태」 → 알림 출구 · 보낸 기록. 주소는 기록에 남지 않는다.</p>'
                % (', '.join('<code>%s</code>' % t for t in types), e(sample), e(VERIFY_PY), e(VERIFY_JS)))
    body.append('<h2 id="macro">자동화 만들기</h2>'
                '<p>허브 창 왼쪽 아이콘 줄의 <b>🛠 만들기</b>(<code>/?view=make</code>, 「나만의 자동화 만들기」)에서 시작한다 — '
                '<b>🎬 보여 주기</b>(웹 주소·이름을 넣고 녹화 시작, Chrome 에서 평소처럼 한 번 해 보이면 그대로 따라 한다) · '
                '<b>💬 말로 부탁하기</b>(할 일·언제를 적으면 디스패치 대화가 켜져 있을 때 Claude 에게 바로 보낸다. 꺼져 있으면 부탁 글만 복사 — Claude Code 에 붙여 넣는다. '
                '여러 가지 일을 한 번에 적어도 일마다 자동화가 따로 생긴다 — 한 일 안의 조건은 하나로). '
                '빈 자동화 파일(템플릿)·요소 찍기·구조 보기·폴더 열기는 <b>🧰 고급 도구</b>에 접혀 있다.</p>'
                '<p><code>tools/macro-hub/macros.local/</code> 에 파이썬 파일 하나를 두면 허브 목록에 뜬다(이 폴더는 git 에 들어가지 않는다). '
                '<code>META</code> 로 이름·트리거를, <code>run(ctx)</code> 로 할 일을 적는다. 결과를 운영 화면에 남기려면 <code>kit.write_status(이름, items)</code>.</p>'
                '<pre>%s</pre>'
                '<h3>META</h3><table><tr><th>키</th><th>뜻</th></tr>'
                '<tr><td><code>name</code> · <code>desc</code></td><td>목록에 보일 이름·설명</td></tr>'
                '<tr><td><code>kind</code></td><td><code>ctx</code>(run(ctx) 를 부른다) · <code>script</code>(녹화기가 만든 단독 스크립트)</td></tr>'
                '<tr><td><code>target</code> · <code>motion</code></td><td><code>web</code> · <code>desktop</code> — 펫이 보일 일의 모습(write·mail·search 도)</td></tr>'
                '<tr><td><code>triggers</code></td><td><code>{"type":"schedule","at":"09:30","days":"mon-fri"}</code> · <code>{"type":"schedule","every":"10m"}</code> · 창·프로세스가 뜰 때</td></tr>'
                '<tr><td><code>timeout</code> · <code>cooldown</code></td><td>제한 시간(초) · 다시 돌기까지 쉬는 시간(초)</td></tr>'
                '<tr><td><code>no_mouse</code></td><td>참이면 마우스·키보드를 쓰는 대체 동작을 하지 않고 멈춘다(내 작업을 방해하면 안 되는 자동화)</td></tr></table>'
                '<h3>ctx 도구</h3><table><tr><th>도구</th><th>설명</th></tr>%s</table>'
                % (e(MACRO_SAMPLE), ''.join('<tr><td><code>%s</code></td><td>%s</td></tr>' % (e(s), e(d)) for s, d in ctx_methods())))
    body.append('<h2 id="api">허브 API (이 PC 에서만)</h2>'
                '<p><code>http://127.0.0.1:8630</code>. 읽기(GET)는 그냥, 바꾸는 요청(POST)은 머리글 <code>X-Hub-Token</code> 이 필요하다 — '
                '토큰은 허브가 켤 때마다 새로 만들어 허브 화면에만 심고 파일로 남기지 않는다. 그래서 밖의 프로그램이 허브를 조종할 수는 없다.</p>'
                '<table><tr><th></th><th>주소</th><th>하는 일</th></tr>%s</table>'
                % ''.join('<tr><td>%s</td><td><code>%s</code></td><td>%s</td></tr>' % (m, e(p), e(d)) for m, p, d in HUB_API))
    body.append('<h2 id="trouble">문제 해결</h2><ul>'
                '<li><b>알림 메일이 안 온다</b> — <code>python setup.py --test</code>. 스팸함도 본다. 회사 메일이 자기에게 보낸 메일을 딴 폴더로 치우면 <code>mail.alert_via</code> 를 <code>append</code> 로.</li>'
                '<li><b>사내망에서 https 오류</b> — 회사 TLS 검사 장비의 루트 인증서(.pem)를 <code>mail.ca_bundle</code> 에.</li>'
                '<li><b>기능이 안 돈다</b> — 운영 화면 「⏰ 예약 작업」에서 켜져 있는지, 「📊 기능 상태」의 마지막 결과·오류를 본다. 허브가 꺼져 있던 동안 놓친 실행은 따라잡지 않는다.</li>'
                '<li><b>누가 무엇을 바꿨나</b> — 운영 화면 「📜 변경 이력」(켜고 끄기·예약 시각·설정 변경 — 값은 남기지 않음).</li>'
                '<li><b>마켓 공지가 안 읽힌다</b> — 그 사이트 robots.txt 가 자동 수집을 막으면 읽지 않는다(끄는 설정 없음). 로그인 뒤에 있는 공지는 넣을 수 없다.</li></ul>')
    body.append('<footer>이 문서는 <code>docs/build_docs.py</code> 가 코드(config.example.json·자동화 설명·runner.py)에서 만든다 — 직접 고치지 말 것.</footer>')
    return ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>업무 자동화 키트 도움말</title>\n<style>%s</style>\n</head>\n<body>\n<div class="wrap">\n%s\n</div>\n</body>\n</html>\n'
            % (CSS, '\n'.join(body)))


def main(argv):
    text = build()
    if '--check' in argv:
        try:
            with open(OUT, encoding='utf-8', newline='') as f:
                cur = f.read()
        except OSError:
            cur = ''
        if cur.replace('\r\n', '\n') != text:
            print('docs/index.html 이 코드와 어긋났습니다 — python docs/build_docs.py')
            return 1
        print('docs/index.html 최신')
        return 0
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('썼습니다: %s (%d KB)' % (OUT, len(text.encode('utf-8')) // 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
