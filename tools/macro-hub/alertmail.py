# -*- coding: utf-8 -*-
"""실패 알림 메일 — 예약 작업(job_*)·상시 서비스(svc_*)가 실패하면 나에게 알림 메일을 보낸다.

    macrohub._watch() 가 실행이 끝날 때마다 on_run_end(rec, settings) 를 부른다(별도 스레드).

- 보내는 것: 상태가 fail · timeout 이고, 내가 직접 누른 실행(manual)·도구 실행이 아닌 것.
  직접 누른 건 허브 화면에서 바로 보이니 메일까지 보내지 않는다.
- 같은 매크로는 cooldown_min(기본 60분) 안에 한 번만 — 죽고 다시 뜨기를 되풀이하는 서비스가 메일을 쏟지 않게.
  마지막으로 보낸 시각은 data.local\alertmail.json 에 남겨 허브를 다시 켜도 이어진다.
- 보내는 길은 kit.alert() 하나 — config.local.json 의 mail.alert_via 가 'smtp' 면 alert_to(없으면 내 주소)로 발송,
  'append' 면 내 INBOX 에 직접 넣는다(자기에게 보낸 메일을 딴 폴더로 치우는 서버용). 계정은 `python setup.py` 로 채운다.
- 메일 설정이 아직 없으면(kit.mail_ready() 가 False) 조용히 건너뛴다 — 로그에 한 번만 남기고 예외를 내지 않는다.
- 설정: state.local.json 의 "alert": {"on": true, "cooldown_min": 60}. 없으면 켜짐·60분.
  허브 트레이 ⚙ 설정 → '실패 알림 메일' 로 켜고 끈다.
- 표준 라이브러리만 쓴다(허브와 같은 규칙).
"""
import datetime
import json
import os
import threading
import time

import kit

HERE = os.path.dirname(os.path.abspath(__file__))
F_SENT = os.path.join(HERE, 'data.local', 'alertmail.json')
F_LOG = os.path.join(HERE, 'data.local', 'alertmail.log')

ALERT_STATUS = ('fail', 'timeout')
DEFAULT_COOLDOWN_MIN = 60
TAIL_LINES = 30

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
    """이 실행 결과로 알림을 보낼지. sent 는 {매크로 id: 마지막으로 보낸 시각(초)}."""
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
    subject = '[매크로 허브] %s %s — %s' % (kind, '제한 시간 초과' if timeout else '실패', name)
    lines = [
        '%s「%s」가 %s했습니다.' % (kind, name, '제한 시간을 넘겨 중지' if timeout else '실패'),
        '',
        '매크로   %s' % rec.get('macro'),
        '계기     %s%s' % (rec.get('trigger'), (' · ' + rec['detail']) if rec.get('detail') else ''),
        '시작     %s' % _clock(rec.get('started')),
        '끝       %s' % _clock(rec.get('ended')),
        '종료 코드 %s' % rec.get('code'),
    ]
    tail = [str(x) for x in (rec.get('tail') or [])][-TAIL_LINES:]
    if tail:
        lines += ['', '── 마지막 로그 %d줄 ──' % len(tail)] + tail
    lines += ['', '자세한 로그·다시 실행: http://127.0.0.1:8610/  (이 PC 에서만)',
              '같은 매크로는 %d분 안에 다시 알리지 않습니다. 끄기: 허브 트레이 ⚙ 설정 → 실패 알림 메일' % settings['cooldown_min']]
    return subject, '\n'.join(lines)


def deliver(subject, body):
    """알림 메일을 보낸다(kit.alert — mail.alert_via 에 따라 발송 또는 INBOX 에 넣기). 실패하면 예외."""
    kit.alert(subject, body)


_unready_logged = False


def _mail_ready():
    """(준비됨?, 설명). 설정을 읽다 실패해도 준비 안 됨으로 본다."""
    try:
        return kit.mail_ready()
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
    with _lock:                                   # 같은 매크로가 거의 동시에 두 번 끝나도 한 번만
        sent = _read_sent()
        if not should_alert(rec, sent, now, settings):
            return False
        sent[rec.get('macro')] = now              # 먼저 적는다 — 메일 서버가 죽어 있을 때 3초마다 재시도하지 않게
        _write_sent(sent)
    subject, body = compose(rec, settings)
    try:
        send(subject, body)
    except Exception as e:
        _log('보내지 못함 %s: %s' % (rec.get('macro'), e))
        raise
    _log('보냄 %s (%s)' % (rec.get('macro'), rec.get('status')))
    return True
