# -*- coding: utf-8 -*-
"""메일·계정 설정 창 — setup.py(검은 명령 창 마법사)와 같은 일을 보통 창 화면으로 한다. 표준 라이브러리(tkinter)만 쓴다.

    pythonw setup_gui.py          (시작 메뉴 「메일·계정 설정」 · 허브 트레이 ⚙ 설정 → 메일·계정 설정 · 처음 설치 직후)

- 회사 이름 · 메일 서비스(미리 채움: setup.PRESETS) · 메일 주소 · 비밀번호 · 알림 받을 곳을 한 화면에서.
  서버 주소·포트는 '직접 입력'을 고르거나 「서버 직접 설정」을 펼칠 때만 보인다.
- 비밀번호는 저장할 때 kit.protect(DPAPI)로 암호화해 config.local.json 에 password_enc 로만 남는다. 이미 있으면 비워 두면 그대로.
- 「시험 메일 보내기」는 먼저 저장하고 kit.alert 로 한 통 보낸다.
- 입력 → 설정 변환(collect)은 창과 떼어 둔 순수 함수다 — tests\\test_setup_gui.py 가 창 없이 검사한다.
"""
import copy
import os
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools', 'macro-hub'))
import kit  # noqa: E402
import setup  # noqa: E402  (PRESETS · MODES · ensure_config · looks_sample 재사용)

CUSTOM = '직접 입력'
VIA = (('smtp', '메일로 보내기 (보통 이것)'), ('append', '내 받은편지함에 바로 넣기 — 나에게 보낸 메일을 서버가 딴 폴더로 치우는 경우'))


# ---------------------------------------------------------------- 입력 ↔ 설정 (창 없이 검사할 수 있는 부분)

def preset_names():
    return [p[0] for p in setup.PRESETS] + [CUSTOM]


def preset_of(m):
    """지금 설정의 IMAP/SMTP 서버가 미리 채움 중 하나와 같으면 그 이름, 서버가 있으면 '직접 입력', 없으면 첫 번째."""
    ih, sh = (m.get('imap_host') or '').lower(), (m.get('smtp_host') or '').lower()
    if setup.looks_sample(ih) or setup.looks_sample(sh):
        ih = sh = ''
    for name, (pih, _, _), (psh, _, _), _note in setup.PRESETS:
        if (ih and ih == pih) or (sh and sh == psh):
            return name
    return CUSTOM if (ih or sh) else setup.PRESETS[0][0]


def preset_servers(name):
    for pname, imap, smtp, note in setup.PRESETS:
        if pname == name:
            return {'imap_host': imap[0], 'imap_port': imap[1], 'imap_mode': imap[2],
                    'smtp_host': smtp[0], 'smtp_port': smtp[1], 'smtp_mode': smtp[2]}, note
    return None, '회사 메일 관리자에게 받은 값을 넣으세요. 보통 IMAP 993 · ssl, SMTP 587 · starttls 또는 465 · ssl 입니다.'


def initial_values(cfg):
    """설정 → 창에 채울 값. 견본 값(example.com · 우리회사)은 비워서 보여 준다."""
    m = kit.mail_config(cfg)
    clean = lambda v: '' if setup.looks_sample(v) else ('' if v is None else str(v))
    return {
        'company': clean((cfg.get('company') or {}).get('name')),
        'preset': preset_of(m),
        'user': clean(m.get('user')), 'login_user': clean(m.get('login_user')),
        'password': '', 'has_password': bool(m.get('password_enc')),
        'alert_to': clean(m.get('alert_to')), 'alert_via': m.get('alert_via') or 'smtp',
        'imap_host': clean(m.get('imap_host')), 'imap_port': str(m.get('imap_port') or 993), 'imap_mode': m.get('imap_mode') or 'ssl',
        'smtp_host': clean(m.get('smtp_host')), 'smtp_port': str(m.get('smtp_port') or 587), 'smtp_mode': m.get('smtp_mode') or 'starttls',
        'ca_bundle': m.get('ca_bundle') or '',
    }


def collect(values, cfg, protect=kit.protect):
    """창의 값 → 새 설정. 돌려주는 값: (새 설정, 오류 목록, 알림 목록). 오류가 있으면 저장하지 않는다."""
    cfg = copy.deepcopy(cfg)
    m = kit.mail_config(cfg)
    errors, notes = [], []
    v = {k: (x.strip() if isinstance(x, str) else x) for k, x in values.items()}
    cfg.setdefault('company', {})['name'] = v.get('company', '')
    user = v.get('user', '')
    if '@' not in user or user.startswith('@') or user.endswith('@'):
        errors.append('메일 주소를 넣어 주세요 (예: me@company.com)')
    m['user'], m['login_user'] = user, v.get('login_user', '')
    servers, _ = preset_servers(v.get('preset'))
    if servers and not v.get('advanced'):
        m.update(servers)
    else:
        for side, default_port in (('imap', 993), ('smtp', 587)):
            host = v.get(side + '_host', '')
            m[side + '_host'] = host
            if host:
                try:
                    port = int(v.get(side + '_port') or default_port)
                    if not 0 < port < 65536:
                        raise ValueError
                    m[side + '_port'] = port
                except ValueError:
                    errors.append('%s 포트는 1~65535 숫자여야 합니다' % side.upper())
                mode = v.get(side + '_mode') or ('ssl' if side == 'imap' else 'starttls')
                if mode not in setup.MODES:
                    errors.append('%s 방식은 ssl · starttls · plain 중 하나입니다' % side.upper())
                m[side + '_mode'] = mode
        if not (m.get('imap_host') or m.get('smtp_host')):
            errors.append('보내는 서버(SMTP)나 받는 서버(IMAP) 중 하나는 있어야 합니다')
    m['ca_bundle'] = v.get('ca_bundle', '')
    if m['ca_bundle'] and not os.path.isfile(kit.expand(m['ca_bundle'])):
        notes.append('인증서 파일이 없습니다 — 그래도 적어 둡니다: %s' % m['ca_bundle'])
    pw = values.get('password') or ''
    if pw:
        m['password_enc'] = protect(pw)
    elif not m.get('password_enc'):
        errors.append('메일 비밀번호를 넣어 주세요')
    m['alert_to'] = v.get('alert_to', '')
    via = v.get('alert_via') or 'smtp'
    if via == 'smtp' and not m.get('smtp_host'):
        via = 'append'
        notes.append('보내는 서버(SMTP)가 없어 알림은 받은편지함에 바로 넣습니다')
    if via == 'append' and not m.get('imap_host'):
        via = 'smtp'
        notes.append('받는 서버(IMAP)가 없어 알림은 메일로 보냅니다')
    m['alert_via'] = via
    cfg['mail'] = m
    return cfg, errors, notes


def friendly_error(e):
    text = '%s: %s' % (type(e).__name__, e)
    low = text.lower()
    hints = []
    if 'authentication' in low or 'login' in low or '535' in low or 'auth' in low:
        hints.append('비밀번호가 맞는지, 2단계 인증을 쓰면 "앱 비밀번호"를 넣었는지 확인하세요.')
    if 'certificate' in low or 'ssl' in low:
        hints.append('방식(ssl/starttls)과 포트가 맞는지 확인하세요. 회사에 보안 프록시가 있으면 「서버 직접 설정」의 인증서 파일이 필요할 수 있습니다.')
    if 'getaddrinfo' in low or 'timed out' in low or 'refused' in low or '10060' in low or '10061' in low:
        hints.append('서버 주소·포트를 확인하세요. 회사 방화벽이 메일 포트를 막고 있을 수도 있습니다.')
    if not hints:
        hints.append('서버 주소·포트·방식, 비밀번호, 메일 서비스의 IMAP/SMTP 사용 설정을 확인하세요.')
    return text + '\n\n' + '\n'.join(hints)


# ---------------------------------------------------------------- 창

def run():
    import tkinter as tk
    from tkinter import messagebox, ttk

    setup.ensure_config()
    cfg = kit._read(kit.F_CONFIG)
    init = initial_values(cfg)

    root = tk.Tk()
    root.title('메일·계정 설정 — 업무 자동화 키트')
    root.resizable(False, False)
    try:
        root.iconbitmap(os.path.join(ROOT, 'tools', 'macro-hub', 'web', 'app.ico'))
    except tk.TclError:
        pass
    font = ('Malgun Gothic', 10)
    root.option_add('*Font', font)
    style = ttk.Style(root)
    style.configure('Hint.TLabel', foreground='#666', font=('Malgun Gothic', 9))
    style.configure('Title.TLabel', font=('Malgun Gothic', 14, 'bold'))

    var = {k: tk.StringVar(value=v) for k, v in init.items() if isinstance(v, str)}
    advanced = tk.BooleanVar(value=init['preset'] == CUSTOM)
    frm = ttk.Frame(root, padding=16)
    frm.grid(sticky='nsew')
    row = [0]

    def line(label, widget, hint=None):
        ttk.Label(frm, text=label).grid(row=row[0], column=0, sticky='w', pady=3, padx=(0, 10))
        widget.grid(row=row[0], column=1, sticky='we', pady=3)
        row[0] += 1
        if hint:
            ttk.Label(frm, text=hint, style='Hint.TLabel', wraplength=380, justify='left').grid(
                row=row[0], column=1, sticky='w')
            row[0] += 1

    ttk.Label(frm, text='메일·계정 설정', style='Title.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
    ttk.Label(frm, text='실패 알림·감시 알림·정기 메일을 보낼 메일 계정을 정합니다.', style='Hint.TLabel').grid(
        row=1, column=0, columnspan=2, sticky='w', pady=(0, 10))
    row[0] = 2
    line('회사 이름', ttk.Entry(frm, textvariable=var['company'], width=44), '알림 메일 제목 앞에 [이름] 으로 붙습니다. 비워도 됩니다.')
    preset_box = ttk.Combobox(frm, textvariable=var['preset'], values=preset_names(), state='readonly', width=42)
    line('메일 서비스', preset_box)
    note = ttk.Label(frm, text='', style='Hint.TLabel', wraplength=380, justify='left')
    note.grid(row=row[0], column=1, sticky='w')
    row[0] += 1
    line('메일 주소', ttk.Entry(frm, textvariable=var['user'], width=44))
    line('로그인 ID', ttk.Entry(frm, textvariable=var['login_user'], width=44), '메일 주소와 다를 때만 (아이디만 받는 서버).')
    line('비밀번호', ttk.Entry(frm, textvariable=var['password'], show='•', width=44),
         '이미 저장돼 있습니다 — 바꿀 때만 넣으세요.' if init['has_password'] else
         '이 PC·이 Windows 사용자만 풀 수 있게 암호화해 저장합니다.')
    line('알림 받을 주소', ttk.Entry(frm, textvariable=var['alert_to'], width=44), '비우면 내 메일 주소로 받습니다.')
    ttk.Label(frm, text='알림 방법').grid(row=row[0], column=0, sticky='nw', pady=3)
    vias = ttk.Frame(frm)
    vias.grid(row=row[0], column=1, sticky='w', pady=3)
    for value, text in VIA:
        ttk.Radiobutton(vias, text=text, value=value, variable=var['alert_via']).pack(anchor='w')
    row[0] += 1

    ttk.Checkbutton(frm, text='서버 직접 설정', variable=advanced, command=lambda: toggle()).grid(
        row=row[0], column=0, columnspan=2, sticky='w', pady=(8, 2))
    row[0] += 1
    adv = ttk.LabelFrame(frm, text='서버', padding=10)
    adv_row = row[0]
    row[0] += 1
    for i, (side, title) in enumerate((('imap', '받는 서버 (IMAP)'), ('smtp', '보내는 서버 (SMTP)'))):
        ttk.Label(adv, text=title).grid(row=i, column=0, sticky='w', padx=(0, 8), pady=2)
        ttk.Entry(adv, textvariable=var[side + '_host'], width=26).grid(row=i, column=1, pady=2)
        ttk.Entry(adv, textvariable=var[side + '_port'], width=6).grid(row=i, column=2, padx=4, pady=2)
        ttk.Combobox(adv, textvariable=var[side + '_mode'], values=setup.MODES, state='readonly', width=9).grid(row=i, column=3, pady=2)
    ttk.Label(adv, text='보안 프록시 인증서').grid(row=2, column=0, sticky='w', pady=(6, 2))
    ttk.Entry(adv, textvariable=var['ca_bundle'], width=40).grid(row=2, column=1, columnspan=3, sticky='we', pady=(6, 2))
    ttk.Label(adv, text='대부분 필요 없습니다 — 회사가 HTTPS 를 검사하는 프록시를 쓸 때만 그 루트 인증서(.pem) 경로.',
              style='Hint.TLabel', wraplength=380).grid(row=3, column=1, columnspan=3, sticky='w')

    status = tk.StringVar(value='설정 파일: %s' % kit.F_CONFIG)
    ttk.Label(frm, textvariable=status, style='Hint.TLabel', wraplength=440).grid(row=row[0] + 1, column=0, columnspan=2, sticky='w', pady=(10, 4))
    btns = ttk.Frame(frm)
    btns.grid(row=row[0] + 2, column=0, columnspan=2, sticky='e')
    b_test = ttk.Button(btns, text='시험 메일 보내기')
    b_save = ttk.Button(btns, text='저장')
    b_close = ttk.Button(btns, text='닫기')
    b_test.pack(side='left', padx=4)
    b_save.pack(side='left', padx=4)
    b_close.pack(side='left', padx=(4, 0))
    saved = {'snap': None}

    def snapshot():
        return {k: x.get() for k, x in var.items()}, advanced.get()

    def toggle():
        if advanced.get():
            adv.grid(row=adv_row, column=0, columnspan=2, sticky='we', pady=(2, 4))
        else:
            adv.grid_remove()

    def on_preset(_=None):
        servers, text = preset_servers(var['preset'].get())
        note.configure(text=text)
        if servers:
            for k, x in servers.items():
                var[k].set(str(x))
        else:
            advanced.set(True)
        toggle()

    def values():
        v = {k: x.get() for k, x in var.items()}
        v['advanced'] = advanced.get()
        return v

    def save(quiet=False):
        nonlocal cfg
        new, errors, notes = collect(values(), cfg)
        if errors:
            messagebox.showwarning('메일·계정 설정', '\n'.join(errors), parent=root)
            return False
        try:
            kit.save_config(new)
        except OSError as e:
            messagebox.showerror('메일·계정 설정', '저장하지 못했습니다: %s' % e, parent=root)
            return False
        cfg = new
        var['password'].set('')
        var['alert_via'].set(new['mail']['alert_via'])
        saved['snap'] = snapshot()
        status.set('저장했습니다.' + (' ' + ' · '.join(notes) if notes else ''))
        if not quiet and notes:
            messagebox.showinfo('메일·계정 설정', '\n'.join(notes), parent=root)
        return True

    def test():
        if not save(quiet=True):
            return
        m = kit.mail_config(cfg)
        target = '내 받은편지함' if m.get('alert_via') == 'append' else (m.get('alert_to') or m['user'])
        status.set('시험 메일을 보내는 중… → %s' % target)
        for b in (b_test, b_save):
            b.configure(state='disabled')

        def work():
            try:
                kit.alert('알림 시험 — 업무 자동화 키트',
                          '이 메일이 보이면 매크로 허브의 실패 알림·감시 알림이 여기로 옵니다.\n\n설정 파일: %s' % kit.F_CONFIG)
                err = None
            except Exception as e:      # 서버마다 예외 종류가 달라 그대로 보여 준다
                err = e

            def done():
                for b in (b_test, b_save):
                    b.configure(state='normal')
                if err is None:
                    status.set('보냈습니다 → %s. 메일함(스팸함도)을 확인하세요.' % target)
                    messagebox.showinfo('메일·계정 설정', '시험 메일을 보냈습니다 → %s\n메일함(스팸함도)을 확인하세요.' % target, parent=root)
                else:
                    status.set('보내지 못했습니다.')
                    messagebox.showerror('메일·계정 설정', friendly_error(err), parent=root)
            root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def close():
        if saved['snap'] != snapshot() and messagebox.askyesno('메일·계정 설정', '저장하지 않은 내용이 있습니다. 저장할까요?', parent=root):
            if not save():
                return
        root.destroy()

    b_save.configure(command=save)
    b_test.configure(command=test)
    b_close.configure(command=close)
    root.protocol('WM_DELETE_WINDOW', close)
    preset_box.bind('<<ComboboxSelected>>', on_preset)
    servers, text = preset_servers(var['preset'].get())
    note.configure(text=text)
    if servers and not var['imap_host'].get() and not var['smtp_host'].get():
        for k, x in servers.items():        # 처음 설정 — 고른 서비스 값을 미리 채워 '서버 직접 설정'을 펼쳐도 비어 있지 않게
            var[k].set(str(x))
    toggle()
    saved['snap'] = snapshot()
    root.mainloop()


if __name__ == '__main__':
    run()
