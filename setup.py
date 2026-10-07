# -*- coding: utf-8 -*-
"""업무 자동화 키트 — 처음 설정 마법사.

    python setup.py            묻는 대로 답하면 config.local.json 을 만들고 메일 계정을 채운다
    python setup.py --test     알림 메일 시험만 (설정대로 실제로 한 통 보낸다)
    python setup.py --show     지금 설정 보기 (비밀번호는 가린다)

- config.local.json 이 없으면 config.example.json 을 복사해 시작한다. 이 파일은 git 에 넣지 않는다.
- 비밀번호는 Windows DPAPI 로 이 PC·이 Windows 사용자에 묶어 암호화한 값(password_enc)만 저장한다.
  다른 PC·다른 계정에서는 풀 수 없으니, PC 를 옮기면 여기서 다시 넣는다.
- 표준 라이브러리만 쓴다(Python 3.10+).
"""
import argparse
import copy
import getpass
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'macro-hub'))
import kit  # noqa: E402

# 메일 서버 미리 채움 — 이름, IMAP(host, port, mode), SMTP(host, port, mode), 안내
PRESETS = [
    ('Gmail / Google Workspace', ('imap.gmail.com', 993, 'ssl'), ('smtp.gmail.com', 587, 'starttls'),
     '2단계 인증을 켠 뒤 "앱 비밀번호"(16자리)를 만들어 비밀번호 자리에 넣으세요. Gmail 설정에서 IMAP 사용도 켜야 합니다.'),
    ('Microsoft 365 / Outlook', ('outlook.office365.com', 993, 'ssl'), ('smtp.office365.com', 587, 'starttls'),
     '회사 관리자가 IMAP·SMTP 기본 인증(아이디·비밀번호 로그인)을 막아 두었으면 로그인이 안 됩니다 — 확인 필요. '
     '보내기만 안 되면 알림 방식을 append(내 INBOX 에 넣기)로 바꿔 보세요.'),
    ('네이버 메일', ('imap.naver.com', 993, 'ssl'), ('smtp.naver.com', 587, 'starttls'),
     '네이버 메일 환경설정 → POP3/IMAP 설정에서 IMAP/SMTP 사용을 켜야 합니다. 2단계 인증이면 애플리케이션 비밀번호를 쓰세요.'),
    ('다음/카카오 메일 (확인 필요)', ('imap.daum.net', 993, 'ssl'), ('smtp.daum.net', 465, 'ssl'),
     '메일 환경설정에서 IMAP/SMTP 사용을 켜야 합니다. 서버 주소·포트는 메일 도움말에서 한 번 확인하세요.'),
    ('네이버 웍스 (확인 필요)', ('imap.worksmobile.com', 993, 'ssl'), ('smtp.worksmobile.com', 587, 'starttls'),
     '관리자가 외부 메일 프로그램(IMAP/SMTP) 사용을 허용해야 합니다. 서버 주소·포트는 관리자 안내로 확인하세요.'),
]
MODES = ('ssl', 'starttls', 'plain')


# ---------------------------------------------------------------- 입력 도우미

def ask(prompt, default='', allow_empty=True):
    tip = ' [%s]' % default if default not in ('', None) else ''
    while True:
        try:
            v = input('%s%s: ' % (prompt, tip)).strip()
        except EOFError:
            v = ''
        if not v:
            v = '' if default is None else str(default)
        if v or allow_empty:
            return v
        print('  값을 넣어 주세요.')


def ask_int(prompt, default):
    while True:
        v = ask(prompt, default)
        try:
            n = int(v)
            if 0 < n < 65536:
                return n
        except ValueError:
            pass
        print('  1~65535 사이의 숫자를 넣어 주세요.')


def ask_choice(prompt, choices, default):
    while True:
        v = ask('%s (%s)' % (prompt, ' / '.join(choices)), default).lower()
        if v in choices:
            return v
        print('  다음 중 하나: %s' % ', '.join(choices))


def yes(prompt, default=True):
    v = ask('%s (y/n)' % prompt, 'y' if default else 'n').lower()
    return v.startswith('y') or v in ('네', '예', 'ㅇ')


# ---------------------------------------------------------------- 설정 파일

def ensure_config():
    """config.local.json 이 없으면 견본을 복사한다. 돌려주는 값: 새로 만들었는가."""
    if os.path.isfile(kit.F_CONFIG):
        return False
    if os.path.isfile(kit.F_EXAMPLE):
        shutil.copyfile(kit.F_EXAMPLE, kit.F_CONFIG)
        kit.save_config(strip_samples(kit._read(kit.F_CONFIG)))
    else:
        kit.save_config({})
    return True


SAMPLE_MARKS = ('example.com', '10.0.0.')


def _is_sample(item):
    text = json.dumps(item, ensure_ascii=False)
    return any(mark in text for mark in SAMPLE_MARKS)


def strip_samples(cfg):
    """견본의 예시 항목(example.com · 10.0.0.x)은 실제 설정에 옮기지 않는다 —
    감시를 켜는 순간 가짜 주소를 감시하거나, 바로가기에 없는 사이트가 뜨지 않게.
    꺼 둔(enabled: false) 정기 메일·백업·정리 견본은 고쳐 쓰라고 남긴다."""
    cfg = copy.deepcopy(cfg)
    cfg['links'] = [x for x in cfg.get('links') or [] if not _is_sample(x)]
    mon = cfg.get('monitors')
    if isinstance(mon, dict):
        mon['targets'] = [x for x in mon.get('targets') or [] if not _is_sample(x)]
    return cfg


def looks_sample(v):
    return 'example.com' in str(v or '') or str(v or '') == '우리회사'


def masked(cfg):
    c = copy.deepcopy(cfg)
    m = c.get('mail') or {}
    if m.get('password_enc'):
        m['password_enc'] = '(암호화돼 있음 — %d자)' % len(m['password_enc'])
    return c


# ---------------------------------------------------------------- 단계

def step_company(cfg):
    print('\n[1/4] 회사')
    cur = (cfg.get('company') or {}).get('name', '')
    name = ask('회사 이름 (알림 메일 제목 앞에 [이름] 으로 붙습니다, 비워도 됨)', '' if looks_sample(cur) else cur)
    cfg.setdefault('company', {})['name'] = name


def step_account(m):
    print('\n[2/4] 메일 계정')
    m['user'] = ask('내 메일 주소', '' if looks_sample(m.get('user')) else m.get('user'), allow_empty=False)
    print('  서버 로그인 ID 가 메일 주소와 다르면 넣으세요(아이디만 받는 서버). 같으면 Enter.')
    m['login_user'] = ask('로그인 ID', m.get('login_user') or '')


def step_servers(m):
    print('\n[3/4] 메일 서버')
    for i, p in enumerate(PRESETS, 1):
        print('  %d) %s' % (i, p[0]))
    print('  %d) 직접 입력' % (len(PRESETS) + 1))
    keep = bool(m.get('imap_host') or m.get('smtp_host')) and not looks_sample(m.get('imap_host'))
    if keep:
        print('  0) 지금 값 그대로 (IMAP %s:%s · SMTP %s:%s)' % (m.get('imap_host'), m.get('imap_port'),
                                                          m.get('smtp_host'), m.get('smtp_port')))
    while True:
        v = ask('번호', '0' if keep else '1')
        if v.isdigit() and (keep or v != '0') and 0 <= int(v) <= len(PRESETS) + 1:
            n = int(v)
            break
        print('  목록의 번호를 넣어 주세요.')
    if n == 0:
        return
    if n <= len(PRESETS):
        name, (ih, ip, im), (sh, sp, sm), note = PRESETS[n - 1]
        m.update(imap_host=ih, imap_port=ip, imap_mode=im, smtp_host=sh, smtp_port=sp, smtp_mode=sm)
        print('  %s 값을 넣었습니다 — IMAP %s:%d (%s) · SMTP %s:%d (%s)' % (name, ih, ip, im, sh, sp, sm))
        print('  ※ ' + note)
        if not yes('이대로 쓸까요? (n 이면 하나씩 고칩니다)'):
            n = len(PRESETS) + 1
    if n == len(PRESETS) + 1:
        print('  회사 메일 관리자에게 받은 값을 넣으세요. 보통 IMAP 993/ssl, SMTP 587/starttls 또는 465/ssl 입니다.')
        m['imap_host'] = ask('IMAP 서버 (받기 — 메일함 정리·append 알림용, 없으면 비움)', '' if looks_sample(m.get('imap_host')) else m.get('imap_host'))
        if m['imap_host']:
            m['imap_port'] = ask_int('IMAP 포트', m.get('imap_port') or 993)
            m['imap_mode'] = ask_choice('IMAP 방식', MODES, m.get('imap_mode') or 'ssl')
        m['smtp_host'] = ask('SMTP 서버 (보내기 — 정기 메일·알림 발송용, 없으면 비움)', '' if looks_sample(m.get('smtp_host')) else m.get('smtp_host'))
        if m['smtp_host']:
            m['smtp_port'] = ask_int('SMTP 포트', m.get('smtp_port') or 587)
            m['smtp_mode'] = ask_choice('SMTP 방식', MODES, m.get('smtp_mode') or 'starttls')
    ca = ask('회사 TLS 검사 프록시 루트 인증서(.pem) 경로 — 대부분 필요 없음, Enter', m.get('ca_bundle') or '')
    if ca and not os.path.isfile(kit.expand(ca)):
        print('  ⚠ 파일이 없습니다 — 그래도 적어 둡니다: %s' % ca)
    m['ca_bundle'] = ca


def step_password(m):
    have = bool(m.get('password_enc'))
    if have and not yes('비밀번호가 이미 저장돼 있습니다. 바꿀까요?', False):
        return
    while True:
        pw = getpass.getpass('메일 비밀번호 (화면에 보이지 않습니다): ')
        if not pw:
            if have:
                return
            print('  비밀번호를 넣어 주세요.')
            continue
        if getpass.getpass('한 번 더: ') != pw:
            print('  두 번 넣은 값이 다릅니다.')
            continue
        m['password_enc'] = kit.protect(pw)
        print('  이 PC·이 Windows 사용자만 풀 수 있게 암호화해 저장합니다.')
        return


def step_alert(m):
    print('\n[4/4] 알림 메일 (허브 작업이 실패했을 때 · 감시 대상이 죽었을 때)')
    m['alert_to'] = ask('알림 받을 주소 (비우면 내 주소)', m.get('alert_to') or '')
    print('  smtp   = 메일로 보낸다 (보통 이것)')
    print('  append = 보내지 않고 내 받은편지함(INBOX)에 직접 넣는다 — 나에게 보낸 메일을 서버가 딴 폴더로 치우는 경우')
    default = m.get('alert_via') or ('smtp' if m.get('smtp_host') else 'append')
    via = ask_choice('알림 방식', ('smtp', 'append'), default)
    if via == 'smtp' and not m.get('smtp_host'):
        print('  ⚠ SMTP 서버가 없어 append 로 둡니다.')
        via = 'append'
    if via == 'append' and not m.get('imap_host'):
        print('  ⚠ IMAP 서버가 없어 append 를 쓸 수 없습니다 — smtp 로 둡니다.')
        via = 'smtp'
    m['alert_via'] = via


# ---------------------------------------------------------------- 명령

def send_test():
    m = kit.mail_config()
    ok, why = kit.mail_ready(m)
    if not ok:
        print('메일 설정이 아직 모자랍니다 — %s' % why)
        return 1
    target = '내 받은편지함(INBOX)' if m.get('alert_via') == 'append' else (m.get('alert_to') or m['user'])
    print('알림 시험 메일을 보냅니다 → %s ...' % target)
    try:
        kit.alert('알림 시험 — 업무 자동화 키트',
                  '이 메일이 보이면 매크로 허브의 실패 알림·감시 알림이 이 주소로 옵니다.\n\n'
                  '설정 파일: %s\n다시 설정: python setup.py' % kit.F_CONFIG)
    except Exception as e:
        print('실패: %s: %s' % (type(e).__name__, e))
        print('서버 주소·포트·방식(ssl/starttls), 앱 비밀번호, 메일 서비스의 IMAP/SMTP 사용 설정을 확인하세요.')
        return 1
    print('보냈습니다. 메일함을 확인하세요(스팸함도).')
    return 0


def show():
    if not os.path.isfile(kit.F_CONFIG):
        print('설정 파일이 아직 없습니다 — python setup.py')
        return 1
    print('설정 파일: %s\n' % kit.F_CONFIG)
    print(json.dumps(masked(kit.load_config()), ensure_ascii=False, indent=2))
    ok, why = kit.mail_ready()
    print('\n메일: %s' % ('준비됨' if ok else '설정 필요 — ' + why))
    return 0


def wizard():
    print('=' * 60)
    print(' 업무 자동화 키트 — 처음 설정')
    print(' Enter 를 누르면 [ ] 안의 값을 그대로 씁니다. 그만두려면 Ctrl+C.')
    print('=' * 60)
    if ensure_config():
        print('config.local.json 을 견본에서 만들었습니다: %s' % kit.F_CONFIG)
    else:
        print('지금 설정을 고칩니다: %s' % kit.F_CONFIG)
    cfg = kit.load_config()
    m = cfg['mail']
    step_company(cfg)
    step_account(m)
    step_servers(m)
    step_password(m)
    step_alert(m)
    cfg['mail'] = m
    kit.save_config(cfg)
    ok, why = kit.mail_ready(m)
    print('\n저장했습니다: %s' % kit.F_CONFIG)
    print('메일: %s' % ('준비됨' if ok else '아직 모자람 — ' + why))
    if ok and yes('\n지금 알림 시험 메일을 한 통 보내 볼까요?'):
        send_test()
    print('\n다음 단계')
    print('  1) tools\\macro-hub\\setup.bat        — 허브 실행 환경 만들기(처음 한 번)')
    print('  2) tools\\macro-hub\\start_app.bat    — 매크로 허브 시작(트레이에 강아지 아이콘)')
    print('  3) http://127.0.0.1:8630/ops         — ⏰ 예약 작업에서 쓸 기능을 켜고, 대상은 config.local.json 에 적습니다')
    print('  설정 보기: python setup.py --show · 알림 시험: python setup.py --test')
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description='업무 자동화 키트 — 처음 설정')
    ap.add_argument('--test', action='store_true', help='알림 시험 메일만 보낸다')
    ap.add_argument('--show', action='store_true', help='지금 설정을 보여 준다(비밀번호는 가림)')
    a = ap.parse_args(argv)
    if a.show:
        return show()
    if a.test:
        return send_test()
    try:
        return wizard()
    except KeyboardInterrupt:
        print('\n그만뒀습니다. 저장하지 않은 값은 버려졌습니다.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
