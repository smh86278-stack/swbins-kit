# -*- coding: utf-8 -*-
"""업무 자동화 키트의 공통 바탕 — 설정 파일 · 메일(보내기·메일함) · 비밀번호 암호화 · 예약 시각 판정 · 상태 파일.

어느 회사에서나 쓰도록 회사마다 다른 값은 전부 저장소 맨 위의 config.local.json 한 곳에 둔다
(견본은 config.example.json, 처음 설정은 `python setup.py`). 이 모듈은 표준 라이브러리만 쓴다 —
허브(macrohub.py·alertmail.py)와 허브 매크로(macros\\*.py), 메일 게이트웨이가 함께 import 한다.

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


def save_config(cfg):
    tmp = F_CONFIG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, F_CONFIG)


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
        raise RuntimeError('비밀번호를 풀 수 없습니다 — 다른 사용자·PC 에서 만든 설정이면 setup.py 를 다시 실행하세요')
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
    return (not lack), ('설정에 없는 값: %s — python setup.py 로 채우세요' % ', '.join(lack) if lack else '')


def password(m=None):
    m = m or mail_config()
    if not m.get('password_enc'):
        raise RuntimeError('메일 비밀번호가 설정되지 않았습니다 — python setup.py')
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


def append_inbox(subject, body, folder='INBOX', m=None):
    """내 메일함에 직접 넣는다(보내지 않음) — 자기에게 보낸 메일을 규칙이 딴 폴더로 치우는 서버에서 쓴다."""
    m = m or mail_config()
    msg = build_message(m['user'], m['user'], subject, body)
    conn = imap_connect(m)
    try:
        conn.append(folder, '', imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def alert(subject, body, m=None):
    """알림 메일 — mail.alert_via 가 'append' 면 내 INBOX 에 넣고, 아니면 alert_to(없으면 내 주소)로 보낸다."""
    m = m or mail_config()
    ok, why = mail_ready(m)
    if not ok:
        raise RuntimeError(why)
    name = company_name()
    if name and not subject.startswith('['):
        subject = '[%s] %s' % (name, subject)
    if m.get('alert_via') == 'append':
        append_inbox(subject, body, m=m)
    else:
        send_mail(m.get('alert_to') or m['user'], subject, body, m=m)


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
