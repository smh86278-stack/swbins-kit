# -*- coding: utf-8 -*-
"""업무 자동화 키트의 공통 바탕 — 설정 파일 · 메일(보내기·메일함) · 비밀번호 암호화 · 예약 시각 판정 · 상태 파일.

어느 회사에서나 쓰도록 회사마다 다른 값은 전부 저장소 맨 위의 config.local.json 한 곳에 둔다
(견본은 config.example.json, 처음 설정은 「메일·계정 설정」 창 setup_gui.py — 명령 창이면 `python setup.py`). 이 모듈은 표준 라이브러리만 쓴다 —
허브(macrohub.py·alertmail.py)와 허브 자동화(macros\\*.py), 메일 게이트웨이가 함께 import 한다.

    import kit
    cfg = kit.load_config()
    kit.send_mail(['a@corp.com'], '제목', '본문')           # SMTP 발송
    kit.append_inbox('제목', '본문')                        # 내 INBOX 에 바로 넣기(IMAP APPEND)
    kit.alert('제목', '본문')                               # 알림 — mail.alert_via 에 따라 위 둘 중 하나
    if kit.due({'at': '09:00', 'days': 'mon-fri'}, last_run, now): ...

비밀번호는 Windows DPAPI 로 이 PC·이 사용자에 묶어 암호화한 값(password_enc)만 파일에 남는다.
"""
import base64
import ctypes
import datetime
import imaplib
import json
import mimetypes
import os
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
F_CONFIG = os.path.join(ROOT, 'config.local.json')
F_EXAMPLE = os.path.join(ROOT, 'config.example.json')
DATA = os.path.join(HERE, 'data.local')

MAIL_DEFAULTS = {
    'user': '',               # 내 메일 주소 (보내는 사람 · 알림 받는 기본 주소)
    'login_user': '',         # 서버 로그인 ID — 비면 user. 아이디만 받는 서버가 있다
    'password_enc': '',       # DPAPI 로 암호화한 비밀번호 (setup.py 가 채운다)
    'imap_host': '', 'imap_port': 993, 'imap_mode': 'ssl',          # ssl | starttls | plain
    'smtp_host': '', 'smtp_port': 587, 'smtp_mode': 'starttls',     # ssl | starttls | plain
    'alert_to': '',           # 알림 받을 주소 — 비면 user
    'alert_via': 'smtp',      # smtp = 발송 · append = 내 INBOX 에 직접 넣기(자기에게 보낸 메일을 딴 폴더로 치우는 서버용)
    'ca_bundle': '',          # 사내 TLS 검사 프록시가 있으면 그 루트 인증서(.pem) 경로
}


# ---------------------------------------------------------------- 설정

def _read(path):
    try:
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_config():
    """config.local.json — 없으면 빈 설정({}). mail 은 기본값을 채워서 돌려준다."""
    cfg = _read(F_CONFIG)
    cfg['mail'] = dict(MAIL_DEFAULTS, **(cfg.get('mail') or {}))
    return cfg


def save_config(cfg, via=None):
    """설정 저장. 바뀐 갈래·키 이름을 변경 이력에 남긴다(값은 남기지 않는다 — 비밀번호·토큰이 섞여 있다).
    via 를 안 주면 저장한 프로그램 이름(setup_gui.py 등)."""
    before = _read(F_CONFIG)
    tmp = F_CONFIG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, F_CONFIG)
    changed = config_changes(before, cfg)
    if changed:
        audit('설정 바꿈', detail=changed, via=via or os.path.basename(sys.argv[0] or '') or 'kit')


def config_changes(before, after):
    """두 설정의 차이를 이름만으로 — 'mail(password_enc) · monitors'. 같으면 ''.
    갈래가 dict 면 바뀐 하위 키 이름까지, 목록·값이면 갈래 이름만. '_' 로 시작하는 설명 키는 뺀다."""
    out = []
    for k in sorted(set(before) | set(after)):
        if k.startswith('_'):
            continue
        a, b = before.get(k), after.get(k)
        if a == b:
            continue
        if a is None or b is None:
            out.append('%s(%s)' % (k, '새로' if a is None else '지움'))
        elif isinstance(a, dict) and isinstance(b, dict):
            sub = sorted(x for x in set(a) | set(b) if not x.startswith('_') and a.get(x) != b.get(x))
            out.append('%s(%s)' % (k, ', '.join(sub)) if sub else k)
        else:
            out.append(k)
    return ' · '.join(out)


def section(name, default=None, cfg=None):
    """설정의 한 갈래(예: 'monitors'). 없으면 default."""
    cfg = cfg if cfg is not None else load_config()
    v = cfg.get(name)
    return default if v is None else v


def company_name(cfg=None):
    return str(((cfg or load_config()).get('company') or {}).get('name') or '').strip()


# ---------------------------------------------------------------- DPAPI

class _Blob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def protect(text):
    """이 PC·이 Windows 사용자에 묶어 암호화한다(base64). 다른 계정·PC 에서는 풀 수 없다."""
    src, _keep = _blob(text.encode('utf-8'))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise RuntimeError('CryptProtectData 실패')
    raw = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return base64.b64encode(raw).decode('ascii')


def unprotect(b64):
    src, _keep = _blob(base64.b64decode(b64))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise RuntimeError('비밀번호를 풀 수 없습니다 — 다른 사용자·PC 에서 만든 설정이면 「메일·계정 설정」에서 비밀번호를 다시 넣으세요')
    raw = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return raw.decode('utf-8')


# ---------------------------------------------------------------- 메일

def mail_config(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    return dict(MAIL_DEFAULTS, **(cfg.get('mail') or {}))


def mail_ready(m=None):
    """(준비됨?, 모자란 것 설명)."""
    m = m or mail_config()
    lack = [k for k in ('user', 'password_enc') if not m.get(k)]
    if not (m.get('smtp_host') or m.get('imap_host')):
        lack.append('smtp_host/imap_host')
    return (not lack), ('설정에 없는 값: %s — 「메일·계정 설정」(setup_gui.py)에서 채우세요' % ', '.join(lack) if lack else '')


def password(m=None):
    m = m or mail_config()
    if not m.get('password_enc'):
        raise RuntimeError('메일 비밀번호가 설정되지 않았습니다 — 「메일·계정 설정」(setup_gui.py)')
    return unprotect(m['password_enc'])


def ssl_context(m=None):
    m = m or mail_config()
    ctx = ssl.create_default_context()
    ca = (m.get('ca_bundle') or '').strip()
    if ca and os.path.exists(ca):
        ctx.load_verify_locations(ca)
    return ctx


def login_id(m):
    return m.get('login_user') or m['user']


def imap_connect(m=None, pw=None):
    m = m or mail_config()
    ctx = ssl_context(m)
    host, port, mode = m['imap_host'], int(m['imap_port']), m.get('imap_mode', 'ssl')
    if mode == 'ssl':
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=20)
    else:
        conn = imaplib.IMAP4(host, port, timeout=20)
        if mode == 'starttls':
            conn.starttls(ctx)
    conn.login(login_id(m), pw if pw is not None else password(m))
    return conn


def smtp_connect(m=None, pw=None):
    m = m or mail_config()
    ctx = ssl_context(m)
    host, port, mode = m['smtp_host'], int(m['smtp_port']), m.get('smtp_mode', 'starttls')
    if mode == 'ssl':
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        s.ehlo()
        if mode == 'starttls':
            s.starttls(context=ctx)
            s.ehlo()
    s.login(login_id(m), pw if pw is not None else password(m))
    return s


def _as_list(v):
    if not v:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.replace(';', ',').split(',') if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def build_message(sender, to, subject, body, cc=None, attachments=None, html=None):
    msg = EmailMessage()
    msg['From'] = sender
    if to:
        msg['To'] = ', '.join(_as_list(to))
    if cc:
        msg['Cc'] = ', '.join(_as_list(cc))
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid()
    msg.set_content(body or '')
    if html:
        msg.add_alternative(html, subtype='html')
    for path in attachments or []:
        ctype, _ = mimetypes.guess_type(path)
        main, sub = (ctype or 'application/octet-stream').split('/', 1)
        with open(path, 'rb') as f:
            msg.add_attachment(f.read(), maintype=main, subtype=sub, filename=os.path.basename(path))
    return msg


def send_mail(to, subject, body, cc=None, bcc=None, attachments=None, html=None, m=None):
    """SMTP 로 보낸다. 실패하면 예외."""
    m = m or mail_config()
    msg = build_message(m['user'], to, subject, body, cc, attachments, html)
    rcpt = _as_list(to) + _as_list(cc) + _as_list(bcc)
    if not rcpt:
        raise ValueError('받는 사람이 없습니다')
    s = smtp_connect(m)
    try:
        s.send_message(msg, to_addrs=rcpt)
    finally:
        try:
            s.quit()
        except Exception:
            pass
    return msg['Message-ID']


def append_inbox(subject, body, folder='INBOX', m=None, html=None, attachments=None):
    """내 메일함에 직접 넣는다(보내지 않음) — 자기에게 보낸 메일을 규칙이 딴 폴더로 치우는 서버에서 쓴다. html 이면 HTML 본문도 단다."""
    m = m or mail_config()
    msg = build_message(m['user'], m['user'], subject, body, html=html, attachments=attachments)
    conn = imap_connect(m)
    try:
        conn.append(folder, '', imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def alert(subject, body, m=None, channels=None, post=None, html=None, attachments=None):
    """알림 — 메일(mail.alert_via 가 'append' 면 내 INBOX, 아니면 alert_to/내 주소로 발송)과 config "notify" 의 출구
    (슬랙·Teams·디스코드·구글 챗·웹훅)로 같이 보낸다. 하나라도 가면 성공, 다 실패하면 마지막 예외.
    메일도 출구도 준비 안 됐으면 RuntimeError. 보낸 기록은 data.local/notify/sent.jsonl.
    channels·post 는 시험용(안 주면 설정의 출구 · urllib). html·attachments(파일 경로 목록)는 메일에만 붙는다(출구에는 글자 본문)."""
    m = m or mail_config()
    conf = section('notify', {}) or {}
    conf = conf if isinstance(conf, dict) else {}
    chans = [c for c in (channels if channels is not None else conf.get('channels') or [])
             if isinstance(c, dict) and c.get('on', True) is not False and (c.get('url_enc') or c.get('url'))]
    ok, why = mail_ready(m)
    use_mail = ok and conf.get('mail', True) is not False
    if not use_mail and not chans:
        raise RuntimeError(why or '알림 출구가 없습니다 — 메일 설정 또는 notify.channels')
    name = company_name()
    if name and not subject.startswith('['):
        subject = '[%s] %s' % (name, subject)
    sent, last_err = 0, None
    if use_mail:
        try:
            if m.get('alert_via') == 'append':
                append_inbox(subject, body, m=m, html=html, attachments=attachments)
            else:
                send_mail(m.get('alert_to') or m['user'], subject, body, html=html, m=m, attachments=attachments)
            sent += 1
            _notify_log('메일', 'mail', subject, True)
        except Exception as e:
            last_err = e
            _notify_log('메일', 'mail', subject, False, e)
    for c in chans:
        cname = str(c.get('name') or c.get('type') or 'webhook')
        try:
            code = post_channel(c, subject, body, post=post)
            sent += 1
            _notify_log(cname, c.get('type'), subject, True, code=code)
        except Exception as e:
            last_err = e
            _notify_log(cname, c.get('type'), subject, False, e)
    if not sent and last_err is not None:
        raise last_err
    return sent


def alert_ready(m=None):
    """(알림을 보낼 곳이 있나, 설명) — 메일이 준비됐거나 켜진 출구가 하나라도 있으면 True."""
    ok, why = mail_ready(m)
    conf = section('notify', {}) or {}
    conf = conf if isinstance(conf, dict) else {}
    chans = [c for c in conf.get('channels') or [] if isinstance(c, dict) and c.get('on', True) is not False
             and (c.get('url_enc') or c.get('url'))]
    return (ok and conf.get('mail', True) is not False) or bool(chans), why


# ---------------------------------------------------------------- 알림 출구(웹훅) · 보낸 기록
# 웹훅 주소는 그 자체가 비밀번호다(아는 사람 누구나 그 방에 글을 쓴다) — url_enc(kit.protect) 로 저장하고
# 기록·화면·오류 문구에 주소를 남기지 않는다. 등록은 python setup.py --webhook.

CHANNEL_TYPES = ('slack', 'teams', 'discord', 'google_chat', 'webhook')
CHANNEL_TEXT_MAX = 3500


def channel_payload(kind, subject, body, now=None):
    """출구 종류별 JSON 본문."""
    text = body if len(body) <= CHANNEL_TEXT_MAX else body[:CHANNEL_TEXT_MAX] + '\n… (잘림)'
    if kind == 'slack':
        return {'text': '*%s*\n%s' % (subject, text)}
    if kind == 'google_chat':
        return {'text': '*%s*\n%s' % (subject, text)}
    if kind == 'discord':
        return {'content': ('**%s**\n%s' % (subject, text))[:2000]}
    if kind == 'teams':                                   # Teams 'Workflows' 웹훅(옛 Office 365 커넥터를 대신한다) — 적응형 카드
        return {'type': 'message', 'attachments': [{
            'contentType': 'application/vnd.microsoft.card.adaptive', 'contentUrl': None,
            'content': {'$schema': 'http://adaptivecards.io/schemas/adaptive-card.json', 'type': 'AdaptiveCard', 'version': '1.4',
                        'body': [{'type': 'TextBlock', 'text': subject, 'weight': 'Bolder', 'wrap': True},
                                 {'type': 'TextBlock', 'text': text, 'wrap': True}]}}]}
    return {'subject': subject, 'body': text, 'ts': int(now if now is not None else time.time()),
            'source': company_name() or 'work-automation-kit'}


def url_ok(url, local_http=True):
    """https 주소이거나(local_http 면) 이 PC(127.0.0.1·localhost)의 http 주소인가. 앞부분 글자 비교가 아니라 실제 호스트 이름으로 —
    'http://127.0.0.1.evil.example/'·'http://localhost@evil.example/' 같은 바깥 주소가 http(평문)로 새지 않게."""
    import urllib.parse
    try:
        u = urllib.parse.urlsplit(str(url or '').strip())
        host = (u.hostname or '').lower()
    except ValueError:
        return False
    if u.scheme == 'https' and host:
        return True
    return local_http and u.scheme == 'http' and host in ('127.0.0.1', 'localhost') and not u.username


def post_channel(c, subject, body, post=None):
    """출구 하나로 보낸다 → HTTP 상태 코드. 실패하면 예외(주소는 문구에 넣지 않는다)."""
    import hashlib
    import hmac
    import urllib.error
    import urllib.request
    kind = str(c.get('type') or 'webhook').lower()
    if kind not in CHANNEL_TYPES:
        raise ValueError('출구 type 은 %s 중 하나: %s' % (' · '.join(CHANNEL_TYPES), kind))
    url = unprotect(c['url_enc']) if c.get('url_enc') else str(c.get('url') or '')
    if not url_ok(url):
        raise ValueError('웹훅 주소는 https 여야 합니다')
    data = json.dumps(channel_payload(kind, subject, body), ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'work-automation-kit/notify'}
    if kind == 'webhook' and c.get('secret_enc'):         # 받는 쪽이 진짜 키트에서 온 것인지 확인할 수 있게
        headers['X-Kit-Signature'] = 'sha256=' + hmac.new(unprotect(c['secret_enc']).encode('utf-8'), data, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    if post is not None:
        return post(req)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as r:
            return r.status
    except urllib.error.HTTPError as e:
        raise RuntimeError('HTTP %d %s' % (e.code, e.reason)) from None
    except urllib.error.URLError as e:
        raise RuntimeError('연결 실패 — %s' % (e.reason,)) from None


NOTIFY_KEEP = 20                                          # 화면(기능 상태)에 보일 최근 보낸 기록 수


def _notify_log(channel, kind, subject, ok, err=None, code=None):
    rec = {'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'channel': channel, 'type': kind or '',
           'subject': str(subject)[:200], 'ok': bool(ok)}
    if code is not None:
        rec['code'] = code
    if err is not None:
        rec['error'] = ('%s: %s' % (type(err).__name__, err))[:200]
    path = os.path.join(DATA, 'notify', 'sent.jsonl')
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
            os.replace(path, path.replace('.jsonl', '.1.jsonl'))
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        recent = notify_log_tail(NOTIFY_KEEP)
        write_status('notify', [{'name': '%s · %s' % (r['ts'][5:16], r['channel']), 'ok': r['ok'],
                                 'text': r['subject'] + ('' if r['ok'] else ' — 실패: ' + r.get('error', ''))} for r in recent],
                     note='최근 보낸 알림 %d건' % len(recent))
    except OSError:
        pass


def notify_log_tail(limit=50):
    path = os.path.join(DATA, 'notify', 'sent.jsonl')
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------- 예약 시각

DAY_NAMES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def days_match(days, d):
    """'daily' · '*' · '' · 'mon-fri' · 'sat,sun' · 'tue' · '1,15'(매달 1일·15일) · 'last'(말일)."""
    days = str(days or 'daily').strip().lower()
    if days in ('daily', '*', ''):
        return True
    wd = d.weekday()
    for part in days.split(','):
        part = part.strip()
        if part == 'last':
            if (d + datetime.timedelta(days=1)).month != d.month:
                return True
        elif part.isdigit():
            if int(part) == d.day:
                return True
        elif '-' in part:
            a, b = part.split('-', 1)
            if a in DAY_NAMES and b in DAY_NAMES:
                ia, ib = DAY_NAMES.index(a), DAY_NAMES.index(b)
                if (ia <= wd <= ib) if ia <= ib else (wd >= ia or wd <= ib):
                    return True
        elif part in DAY_NAMES and DAY_NAMES.index(part) == wd:
            return True
    return False


def _hm(at):
    h, mi = str(at).strip().split(':')
    return int(h), int(mi)


def due(item, last_run, now=None, grace_min=180):
    """item {'at': 'HH:MM', 'days': ...} 이 지금 돌 차례인가.
    오늘이 맞는 요일이고, 오늘 그 시각이 지났고(grace_min 분 안 — PC 가 늦게 켜져도 따라잡되 한밤중에 몰아 돌지 않게),
    오늘 그 시각 이후로 아직 안 돌았으면 True. last_run 은 마지막 실행 시각(초) 또는 None."""
    now = now or datetime.datetime.now()
    try:
        h, mi = _hm(item.get('at', ''))
    except (ValueError, AttributeError):
        return False
    if not days_match(item.get('days'), now.date()):
        return False
    slot = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if now < slot or (now - slot).total_seconds() > grace_min * 60:
        return False
    return not (isinstance(last_run, (int, float)) and last_run >= slot.timestamp())


def every_due(every_min, last_run, now_ts=None):
    """간격 실행 — 마지막 실행 뒤 every_min 분이 지났으면 True."""
    now_ts = now_ts if now_ts is not None else time.time()
    return not (isinstance(last_run, (int, float)) and now_ts - last_run < float(every_min) * 60)


# ---------------------------------------------------------------- 기능별 데이터 · 상태

def data_dir(feature):
    p = os.path.join(DATA, feature)
    os.makedirs(p, exist_ok=True)
    return p


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_status(feature, items, note=''):
    """운영 화면(/ops) '기능 상태' 탭이 읽는 상태 파일. items = [{'name', 'ok': True/False/None, 'text'}]."""
    write_json(os.path.join(data_dir(feature), 'status.json'),
               {'feature': feature, 'updated': int(time.time()), 'note': note, 'items': items})


# ---------------------------------------------------------------- 변경 이력(감사 기록)
# 누가(Windows 사용자)·어디서(화면 주소 · 트레이 · 설정 프로그램)·언제·무엇을. 덧붙이기만 하고, 비밀값은 적지 않는다.
# 허브(켜고 끄기·다시 띄우기·지금 실행·예약 시각·자동화 만듦)와 save_config(설정 바꿈)가 쓴다. 운영 화면 「📜 변경 이력」.

AUDIT_MAX = 2 * 1024 * 1024


def audit_path():
    return os.path.join(DATA, 'audit.jsonl')


def audit(action, target='', detail='', via=None, name=''):
    rec = {'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
           'user': os.environ.get('USERNAME') or os.environ.get('USER') or '',
           'via': via or 'kit', 'action': action, 'target': target, 'name': name, 'detail': str(detail or '')[:300]}
    path = audit_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > AUDIT_MAX:     # 넘으면 한 번 넘기고 새로 — 둘 다 읽는다
            os.replace(path, path.replace('.jsonl', '.1.jsonl'))
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except OSError:
        pass
    return rec


def audit_tail(limit=300):
    """최근 이력(새것 먼저)."""
    out = []
    for path in (audit_path(), audit_path().replace('.jsonl', '.1.jsonl')):
        try:
            with open(path, encoding='utf-8') as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
            if len(out) >= limit:
                return out
    return out


def read_status(feature):
    return read_json(os.path.join(DATA, feature, 'status.json'), None)


def expand(path):
    """%USERPROFILE% · ~ 를 풀어 준다."""
    return os.path.normpath(os.path.expanduser(os.path.expandvars(str(path))))


def render(text, now=None):
    """정기 메일 제목·본문의 자리표시 — {date} 2026-10-07 · {yyyy} {mm} {dd} · {prev_month} 2026-09 · {week} 41 · {company}."""
    now = now or datetime.datetime.now()
    first = now.replace(day=1)
    prev = first - datetime.timedelta(days=1)
    vals = {'date': now.strftime('%Y-%m-%d'), 'yyyy': now.strftime('%Y'), 'mm': now.strftime('%m'),
            'dd': now.strftime('%d'), 'prev_month': prev.strftime('%Y-%m'), 'month': now.strftime('%Y-%m'),
            'week': str(now.isocalendar()[1]), 'company': company_name()}
    out = str(text or '')
    for k, v in vals.items():
        out = out.replace('{%s}' % k, v)
    return out
