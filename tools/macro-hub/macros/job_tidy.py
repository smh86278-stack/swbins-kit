# -*- coding: utf-8 -*-
"""폴더 정리 — 오래된 파일을 보관 폴더(archive_to\\YYYY-MM\\)로 옮긴다. 절대 지우지 않는다.

항목(config.local.json 의 tidy): {name, folder, older_than_days, archive_to, at, days, enabled}
- 폴더 바로 아래의 '파일'만 옮긴다(하위 폴더·보관 폴더 자체는 그대로). YYYY-MM 은 파일의 수정 시각 기준.
- 같은 이름이 있으면 '이름 (2).확장자' 처럼 번호를 붙인다 — 덮어쓰지 않는다.
- 숨김·시스템 파일, desktop.ini, Office 잠금 파일(~$*)은 건드리지 않는다.
- 드라이브 맨 위·C:\\Windows·Program Files·사용자 폴더 맨 위는 실수 한 번이 크게 번지므로 거절한다.
- 매개변수 {"dry_run": true} 면 옮길 목록만 보여 준다(예약과 상관없이 모든 켜진 항목). 손으로 '지금 실행'하면
  예약 시각을 기다리지 않고 모든 켜진 항목을 정리한다.
"""
import datetime
import os
import shutil
import stat
import time

import kit

FEATURE = 'tidy'
SKIP_NAMES = {'desktop.ini', 'thumbs.db'}

META = {
    "name": "폴더 정리 (오래된 파일 보관)",
    "desc": "설정(tidy)의 폴더에서 오래된 파일을 보관 폴더\\YYYY-MM 으로 옮긴다. 지우지 않는다. dry_run 이면 목록만.",
    "kind": "ctx",
    "target": "desktop",
    "motion": "desktop",
    "params": {"dry_run": False},
    "triggers": [{"type": "schedule", "every": "5m"}],
    "timeout": 1800,
    "cooldown": 30,
}


def flag(v):
    """허브 화면에서 온 매개변수는 문자열일 수 있다 — 'true'·'1'·'예' 도 참으로."""
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes', 'y', 'on', '예', '네')
    return bool(v)


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p))).rstrip('\\/')


def _under(path, base):
    return path == base or path.startswith(base + os.sep)


def refuse_reason(folder, env=None):
    """정리하면 안 되는 폴더면 이유를, 괜찮으면 '' 를 돌려준다."""
    env = os.environ if env is None else env
    p = _norm(folder)
    drive, rest = os.path.splitdrive(p)
    if not rest.strip('\\/'):
        return '드라이브 맨 위(%s)는 정리하지 않습니다' % folder
    windir = env.get('SystemRoot') or env.get('WINDIR') or r'C:\Windows'
    for key, label in ((windir, 'Windows 폴더'),
                       (env.get('ProgramFiles') or r'C:\Program Files', 'Program Files'),
                       (env.get('ProgramFiles(x86)') or r'C:\Program Files (x86)', 'Program Files (x86)'),
                       (env.get('ProgramData') or r'C:\ProgramData', 'ProgramData')):
        if _under(p, _norm(key)):
            return '%s 아래는 정리하지 않습니다: %s' % (label, folder)
    home = env.get('USERPROFILE')
    if home and p == _norm(home):
        return '사용자 폴더 맨 위(%s)는 정리하지 않습니다 — 그 아래 폴더(다운로드 등)를 지정하세요' % folder
    return ''


def _skip(entry):
    name = entry.name
    if name.lower() in SKIP_NAMES or name.startswith('~$'):
        return True
    attrs = getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0)
    return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM)) if attrs else False


def _free_name(dst_dir, name, taken):
    """dst_dir 안에서 겹치지 않는 경로 — 'a.txt' → 'a (2).txt' → 'a (3).txt'."""
    base, ext = os.path.splitext(name)
    cand, n = os.path.join(dst_dir, name), 2
    while os.path.exists(cand) or os.path.normcase(cand) in taken:
        cand = os.path.join(dst_dir, '%s (%d)%s' % (base, n, ext))
        n += 1
    return cand


def plan_moves(folder, older_than_days, archive_to, now=None):
    """옮길 (원본, 대상) 목록. 폴더 바로 아래의 오래된 파일만, 이름이 겹치면 번호를 붙인다."""
    now = now or datetime.datetime.now()
    limit = now.timestamp() - float(older_than_days) * 86400
    archive = _norm(archive_to)
    taken, out = set(), []
    with os.scandir(folder) as it:
        entries = sorted(it, key=lambda e: e.name.lower())
    for e in entries:
        if _norm(e.path) == archive or not e.is_file(follow_symlinks=False) or _skip(e):
            continue
        mtime = e.stat(follow_symlinks=False).st_mtime
        if mtime >= limit:
            continue
        sub = os.path.join(archive_to, datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m'))
        dst = _free_name(sub, e.name, taken)
        taken.add(os.path.normcase(dst))
        out.append((e.path, dst))
    return out


def tidy_item(item, now, dry_run=False, log=print, env=None):
    """한 항목을 정리한다. (옮긴 수, 오류 목록). 폴더 자체가 문제면 예외."""
    folder = kit.expand(item.get('folder') or '')
    archive = kit.expand(item.get('archive_to') or os.path.join(folder, '_보관'))
    if not item.get('folder'):
        raise ValueError('folder 가 비었습니다')
    why = refuse_reason(folder, env)
    if why:
        raise ValueError(why)
    if not os.path.isdir(folder):
        raise FileNotFoundError('폴더가 없습니다: %s' % folder)
    if _norm(archive) == _norm(folder):
        raise ValueError('archive_to 가 정리할 폴더와 같습니다: %s' % archive)
    days = item.get('older_than_days', 30)
    try:
        days = float(days)
    except (TypeError, ValueError):
        raise ValueError('older_than_days 가 숫자가 아닙니다: %r' % days)
    moves = plan_moves(folder, days, archive, now)
    if dry_run:
        for src, dst in moves:
            log('  (미리보기) %s → %s' % (os.path.basename(src), os.path.relpath(dst, archive)))
        return len(moves), []
    done, errors = 0, []
    for src, dst in moves:
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):               # 계획 뒤에 누가 같은 이름을 만들었으면 다시 고른다
                dst = _free_name(os.path.dirname(dst), os.path.basename(src), set())
            shutil.move(src, dst)
            done += 1
        except OSError as e:                      # 열려 있는 파일 등 — 이 파일만 건너뛴다
            errors.append('%s: %s' % (os.path.basename(src), e.strerror or e))
    return done, errors


def run(ctx):
    items = kit.section('tidy') or []
    if not items:
        ctx.log('폴더 정리: 설정에 없음 (config.local.json 의 tidy)')
        kit.write_status(FEATURE, [], note='설정에 없음')
        return
    dry = flag(ctx.params.get('dry_run'))
    manual = (ctx.trigger or {}).get('kind') == 'manual'
    path = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(path, {}) or {}
    now = datetime.datetime.now()
    errors = []
    for it in items:
        if not isinstance(it, dict) or it.get('enabled') is False:
            continue
        key = str(it.get('name') or it.get('folder') or '?')
        st = state.setdefault(key, {})
        if not (dry or manual or kit.due(it, st.get('last_run'), now)):
            continue
        ctx.motion('desktop', hold=3)
        try:
            n, errs = tidy_item(it, now, dry_run=dry, log=ctx.log)
        except Exception as e:
            msg = '%s: %s' % (type(e).__name__, e)
            errors.append('%s — %s' % (key, msg))
            ctx.log('✖ %s: %s' % (key, msg))
            if not dry:
                st.update(last_run=now.timestamp(), last_ok=False, last_err=msg)
            continue
        if dry:
            ctx.log('%s: 옮길 파일 %d개 (미리보기 — 아무것도 옮기지 않음)' % (key, n))
            continue
        # 실패해도 시각은 적는다 — 열린 파일 하나 때문에 매번 다시 돌지 않게(다음 예약 때 다시 시도된다)
        st.update(last_run=now.timestamp(), last_ok=not errs, last_moved=n,
                  last_err=('%d개 못 옮김: %s' % (len(errs), '; '.join(errs[:5]))) if errs else '')
        ctx.log('%s: %d개 보관%s' % (key, n, ' · ' + st['last_err'] if errs else ''))
        if errs:
            errors.append('%s — %s' % (key, st['last_err']))
    if not dry:
        kit.write_json(path, state)
    kit.write_status(FEATURE, status_items(items, state),
                     note=('미리보기 ' if dry else '확인 ') + time.strftime('%H:%M'))
    if errors:
        raise RuntimeError('폴더 정리 %d건 실패:\n%s' % (len(errors), '\n'.join(errors)))


def status_items(items, state):
    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        key = str(it.get('name') or it.get('folder') or '?')
        st = state.get(key) or {}
        when = '%s %s' % (it.get('days') or 'daily', it.get('at', '?'))
        if it.get('enabled') is False:
            rows.append({'name': key, 'ok': None, 'text': '꺼짐 · %s' % when})
            continue
        last = st.get('last_run')
        text = '%s · 마지막 %s' % (when, datetime.datetime.fromtimestamp(last).strftime('%Y-%m-%d %H:%M') if last else '없음')
        if last and st.get('last_moved') is not None:
            text += ' (%d개 보관)' % st['last_moved']
        if st.get('last_ok') is False:
            rows.append({'name': key, 'ok': False, 'text': '%s · %s' % (text, st.get('last_err', ''))})
        else:
            rows.append({'name': key, 'ok': True if last else None, 'text': text})
    return rows
