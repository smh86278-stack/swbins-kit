# -*- coding: utf-8 -*-
"""실패 알림 메일 — 예약 작업(job_*)·상시 서비스(svc_*)가 실패하면 나에게 알림 메일을 보낸다.

    macrohub._watch() 가 실행이 끝날 때마다 on_run_end(rec, settings) 를 부른다(별도 스레드).

- 보내는 것: 상태가 fail · timeout 이고, 내가 직접 누른 실행(manual)·도구 실행이 아닌 것.
  직접 누른 건 허브 화면에서 바로 보이니 메일까지 보내지 않는다.
- 같은 자동화는 cooldown_min(기본 60분) 안에 한 번만 — 죽고 다시 뜨기를 되풀이하는 서비스가 메일을 쏟지 않게.
  마지막으로 보낸 시각은 data.local\alertmail.json 에 남겨 허브를 다시 켜도 이어진다.
- 보내는 길은 kit.alert() 하나 — config.local.json 의 mail.alert_via 가 'smtp' 면 alert_to(없으면 내 주소)로 발송,
  'append' 면 내 INBOX 에 직접 넣는다(자기에게 보낸 메일을 딴 폴더로 치우는 서버용). 계정은 `python setup.py` 로 채운다.
- config "notify" 의 출구(슬랙·Teams·디스코드·구글 챗·웹훅)가 있으면 그쪽으로도 같이 간다(kit.alert).
- 메일도 출구도 아직 없으면(kit.alert_ready() 가 False) 조용히 건너뛴다 — 로그에 한 번만 남기고 예외를 내지 않는다.
- 디스패치(dispatch.enabled)가 켜져 있으면 메일에 「🔍 원인 봐 줘」 단추(HTML)를 단다 — 누르면 '#c 실패 원인 봐 줘' 읽기 지시가
  채워진 메일 작성 화면이 열리고, 보내기만 누르면 게이트웨이가 받아 원인만 찾는다(고치지 않음 — 고치기는 허브 화면의 🩹 고쳐 달라기).
  키트 폴더를 가리키는 workdir_keys 가 있으면 '@그 키' 로, 암호 단어는 게이트웨이 회신 단추처럼 본문 마지막 줄에(word_for_reply).
- 설정: state.local.json 의 "alert": {"on": true, "cooldown_min": 60}. 없으면 켜짐·60분.
  허브 트레이 ⚙ 설정 → '실패 알림 메일' 로 켜고 끈다.
- 표준 라이브러리만 쓴다(허브와 같은 규칙).
"""
import datetime
import html
import importlib.util
import json
import os
import sys
import threading
import time
from urllib.parse import quote

import kit

HERE = os.path.dirname(os.path.abspath(__file__))
F_SENT = os.path.join(HERE, 'data.local', 'alertmail.json')
F_LOG = os.path.join(HERE, 'data.local', 'alertmail.log')

ALERT_STATUS = ('fail', 'timeout')
DEFAULT_COOLDOWN_MIN = 60
TAIL_LINES = 30
ASK_TAIL = 15          # 「원인 봐 줘」 지시에 담을 로그 끝 줄 수 — mailto 주소가 너무 길면 메일 앱이 자른다
ASK_LINE_MAX = 200
GATEWAY = os.path.join(kit.ROOT, 'mail-gateway.py')

_lock = threading.Lock()


def settings_of(raw):
    """state['alert'] 를 읽기 좋은 꼴로 — 없거나 이상한 값이면 켜짐·60분."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        cooldown = max(1, int(raw.get('cooldown_min', DEFAULT_COOLDOWN_MIN)))
    except (TypeError, ValueError):
        cooldown = DEFAULT_COOLDOWN_MIN
    return {'on': raw.get('on', True) is not False, 'cooldown_min': cooldown}


def should_alert(rec, sent, now, settings):
    """이 실행 결과로 알림을 보낼지. sent 는 {자동화 id: 마지막으로 보낸 시각(초)}."""
    if not settings['on'] or rec.get('tool'):
        return False
    if rec.get('status') not in ALERT_STATUS or rec.get('trigger', 'manual') == 'manual':
        return False
    last = sent.get(rec.get('macro'))
    return not (isinstance(last, (int, float)) and now - last < settings['cooldown_min'] * 60)


def _clock(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S') if ms else '-'


def compose(rec, settings):
    """(제목, 본문). 본문에는 실행 정보와 마지막 로그 몇 줄을 담는다."""
    kind = {'service': '상시 서비스', 'schedule': '예약 작업'}.get(rec.get('trigger'), '자동 실행')
    timeout = rec.get('status') == 'timeout'
    name = rec.get('name') or rec.get('macro')
    subject = '[자동화 허브] %s %s — %s' % (kind, '제한 시간 초과' if timeout else '실패', name)
    lines = [
        '%s「%s」가 %s했습니다.' % (kind, name, '제한 시간을 넘겨 중지' if timeout else '실패'),
        '',
        '자동화   %s' % rec.get('macro'),
        '계기     %s%s' % (rec.get('trigger'), (' · ' + rec['detail']) if rec.get('detail') else ''),
        '시작     %s' % _clock(rec.get('started')),
        '끝       %s' % _clock(rec.get('ended')),
        '종료 코드 %s' % rec.get('code'),
    ]
    tail = [str(x) for x in (rec.get('tail') or [])][-TAIL_LINES:]
    if tail:
        lines += ['', '── 마지막 로그 %d줄 ──' % len(tail)] + tail
    lines += ['', '자세한 로그·다시 실행: http://127.0.0.1:8630/  (이 PC 에서만)',
              '같은 자동화는 %d분 안에 다시 알리지 않습니다. 끄기: 허브 트레이 ⚙ 설정 → 실패 알림 메일' % settings['cooldown_min']]
    return subject, '\n'.join(lines)


def ask_text(rec, tag='#c', folder_key=None):
    """「🔍 원인 봐 줘」 단추가 채울 (제목, 본문) — 게이트웨이 읽기 지시. 원인만 찾게 한다."""
    timeout = rec.get('status') == 'timeout'
    name = rec.get('name') or rec.get('macro')
    tail = [str(x)[:ASK_LINE_MAX] for x in (rec.get('tail') or [])][-ASK_TAIL:]
    subject = '%s %s실패 원인 봐 줘 — %s' % (tag, ('@%s ' % folder_key) if folder_key else '', name)
    body = '\n'.join([
        '자동화 허브의 자동화가 실패했어 — 원인만 찾아 줘(고치지는 말고).',
        '자동화: %s (%s)' % (name, rec.get('macro')),
        '결과: %s · 시작 %s · 종료 코드 %s' % ('제한 시간 초과' if timeout else '오류', _clock(rec.get('started')), rec.get('code')),
        '자동화 파일은 %s 나 %s 의 %s.py, 지난 실행 기록은 %s.' % (os.path.join(kit.HERE, 'macros'), os.path.join(kit.HERE, 'macros.local'),
                                                            rec.get('macro'), os.path.join(kit.HERE, 'runs.jsonl')),
        '',
        '로그 끝 %d줄:' % len(tail),
    ] + (tail or ['(로그 없음)']) + [
        '',
        '원인과 고칠 방법을 짧게 알려 줘. 로그인 만료·네트워크·메일 서버처럼 코드 밖 문제면 그렇다고 말해 줘.',
    ])
    return subject, body


def ask_mailto(to, subject, body, word=None):
    """메일 작성 화면을 여는 mailto 주소. 암호 단어는 본문 마지막 줄에 — 제목에 붙이면 스팸 장비가 의심한다(게이트웨이 mailto 와 같게)."""
    if word:
        body = body.rstrip() + '\n\n[k:%s]' % word
    return 'mailto:%s?subject=%s&body=%s' % (to, quote(subject), quote(body))


def compose_html(body, href):
    """글자 본문 + 맨 위 「🔍 원인 봐 줘」 단추."""
    return ('<div style="font-family:-apple-system,\'Segoe UI\',\'Malgun Gothic\',sans-serif;font-size:14px;line-height:1.5;color:#2f2b45">'
            '<a href="%s" style="display:inline-block;padding:8px 14px;margin:2px 0 6px;border-radius:999px;text-decoration:none;'
            'font-weight:700;background:#eee9ff;color:#5b45c9;border:1px solid #d9cffb">🔍 원인 봐 줘</a>'
            '<div style="color:#8781a0;font-size:12px;margin-bottom:12px">누르면 원인을 묻는 지시가 채워진 메일이 열립니다 — 보내기만 누르세요. '
            'Claude 가 이 PC 에서 로그와 파일을 읽고 원인만 답합니다(고치지는 않음).</div>'
            '<div style="white-space:pre-wrap">%s</div></div>') % (html.escape(href, quote=True), html.escape(body))


def _load_gateway():
    spec = importlib.util.spec_from_file_location('mail_gateway_for_alert', GATEWAY)
    mg = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ['mail-gateway']
    try:
        spec.loader.exec_module(mg)
    finally:
        sys.argv = argv
    return mg


def _same_dir(a, b):
    return os.path.normcase(os.path.normpath(a or '')) == os.path.normcase(os.path.normpath(b or ''))


def ask_html(rec, body, mg=None):
    """「🔍 원인 봐 줘」 단추가 달린 HTML 본문 — 디스패치가 꺼져 있거나 설정을 못 읽으면 None(글자 메일만 간다)."""
    try:
        mg = mg or _load_gateway()
        cfg = mg.load_cfg()
    except Exception:
        return None
    if not cfg.get('enabled') or not cfg.get('user'):
        return None
    key = next((k for k, v in (cfg.get('workdir_keys') or {}).items() if _same_dir(v, kit.ROOT) or _same_dir(v, kit.HERE)), None)
    subject, text = ask_text(rec, cfg.get('tag') or '#c', key)
    sender = cfg['user'] if cfg.get('alert_via') == 'append' else (kit._as_list(cfg.get('alert_to')) or [cfg['user']])[0]
    return compose_html(body, ask_mailto(cfg['user'], subject, text, mg.word_for_reply(cfg, sender)))


def deliver(subject, body, rec=None):
    """알림 메일을 보낸다(kit.alert — mail.alert_via 에 따라 발송 또는 INBOX 에 넣기). 실패하면 예외."""
    kit.alert(subject, body, html=ask_html(rec, body) if rec else None)


_unready_logged = False


def _mail_ready():
    """(보낼 곳이 있나, 설명) — 메일 또는 notify 출구(슬랙·Teams 등). 설정을 읽다 실패해도 준비 안 됨으로 본다."""
    try:
        return kit.alert_ready()
    except Exception as e:
        return False, str(e)


def _read_sent():
    try:
        with open(F_SENT, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_sent(sent):
    try:
        os.makedirs(os.path.dirname(F_SENT), exist_ok=True)
        with open(F_SENT, 'w', encoding='utf-8') as f:
            json.dump(sent, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _log(text):
    try:
        os.makedirs(os.path.dirname(F_LOG), exist_ok=True)
        if os.path.exists(F_LOG) and os.path.getsize(F_LOG) > 512 * 1024:
            os.replace(F_LOG, F_LOG + '.1')
        with open(F_LOG, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), text))
    except OSError:
        pass


def on_run_end(rec, raw_settings, send=deliver, ready=_mail_ready):
    """실행이 끝났을 때. 보냈으면 True, 안 보냈으면 False. 보내다 실패하면 예외(호출부가 알림으로 바꾼다).
    메일 설정이 아직 없으면 예외 없이 False — 로그에는 허브가 켜져 있는 동안 한 번만 남긴다."""
    global _unready_logged
    settings = settings_of(raw_settings)
    now = time.time()
    if not settings['on'] or not should_alert(rec, {}, now, settings):
        return False
    ok, why = ready()
    if not ok:
        if not _unready_logged:
            _unready_logged = True
            _log('메일 설정이 없어 알림을 건너뜀(%s) — %s' % (rec.get('macro'), why))
        return False
    with _lock:                                   # 같은 자동화가 거의 동시에 두 번 끝나도 한 번만
        sent = _read_sent()
        if not should_alert(rec, sent, now, settings):
            return False
        sent[rec.get('macro')] = now              # 먼저 적는다 — 메일 서버가 죽어 있을 때 3초마다 재시도하지 않게
        _write_sent(sent)
    subject, body = compose(rec, settings)
    try:
        send(subject, body, rec)
    except Exception as e:
        _log('보내지 못함 %s: %s' % (rec.get('macro'), e))
        raise
    _log('보냄 %s (%s)' % (rec.get('macro'), rec.get('status')))
    return True
