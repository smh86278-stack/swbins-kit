# -*- coding: utf-8 -*-
"""폴더 백업 — config 의 "backups" 갈래(목록).

    "backups": [{"name": "문서 백업", "source": "%USERPROFILE%\\Documents", "dest": "D:\\Backup\\Documents",
                 "at": "12:30", "days": "mon-fri", "keep": 7, "exclude": ["*.tmp", "~$*"], "enabled": true}]

허브가 1분마다 깨우면 at/days 가 된 항목만 돈다(손으로 '실행' 하면 켜진 항목 모두 — only 로 하나만 고를 수 있다).
돌 때마다 dest\\YYYY-MM-DD_HHMM 날짜 폴더를 새로 만들어 robocopy 로 통째로 복사한다(날짜별 스냅숏).
성공하면 keep 개보다 오래된 스냅숏을 지운다 — **dest 바로 아래, 이름이 정확히 날짜 모양인 폴더만** 지운다.
다른 것은 절대 건드리지 않는다. dest 가 source 안에 있으면(복사가 끝없이 자기 자신을 품는다) 거절한다.
실패한 스냅숏은 '_실패' 를 붙여 남겨 둔다 — 날짜 모양이 아니게 되므로 정리 대상이 아니고, 무엇이 빠졌는지 볼 수 있다.
하나라도 실패하면 상태를 남긴 뒤 마지막에 예외를 던진다(허브가 실패 알림 메일을 보낸다).
params {"dry_run": true} 면 robocopy /L(목록만) 로 돌리고 지우지도, 실행 기록을 남기지도 않는다.
"""
import datetime
import os
import re
import shutil
import stat
import subprocess
import sys
import time

import kit

FEATURE = 'backups'
SNAP_FMT = '%Y-%m-%d_%H%M'
SNAP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{4}$')
FAILED_SUFFIX = '_실패'

META = {
    "name": "폴더 백업",
    "desc": "config 의 backups 항목을 정한 시각에 dest\\날짜 폴더로 robocopy 복사하고, keep 개를 넘는 오래된 스냅숏을 지운다.",
    "kind": "ctx",
    "target": "desktop",
    "params": {"dry_run": False, "only": ""},
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 14400,          # 4시간 — 큰 폴더 첫 백업도 끝나게
    "cooldown": 30,
}


# ---------------------------------------------------------------- 순수 로직 (테스트 대상)

def robocopy_ok(code):
    """robocopy 종료 코드 0~7 은 성공(복사함·추가 파일 있음 등), 8 이상은 실패."""
    return isinstance(code, int) and 0 <= code < 8


def prune_plan(names, keep, current=None):
    """지울 스냅숏 이름 목록 — 날짜 모양 이름만 세고, 새것 keep 개를 남긴다. keep 이 0 이하면 지우지 않는다.
    방금 만든 current 는 무엇이 와도 지우지 않는다."""
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        return []
    if keep <= 0:
        return []
    snaps = sorted(n for n in names if SNAP_RE.match(n))
    old = snaps[:-keep] if len(snaps) > keep else []
    return [n for n in old if n != current]


def _norm(p):
    return os.path.normcase(os.path.abspath(kit.expand(p)))


def inside(child, parent):
    """child 가 parent 와 같거나 그 안에 있는가."""
    c, p = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:              # 드라이브가 다르면
        return False


def check_paths(source, dest):
    """복사해도 되는가 → 문제 설명('' 이면 괜찮음)."""
    if not source or not dest:
        return 'source 와 dest 를 모두 적어야 합니다'
    if not os.path.isdir(kit.expand(source)):
        return '원본 폴더가 없습니다: %s' % kit.expand(source)
    if inside(dest, source):
        return '백업 폴더(dest)가 원본(source) 안에 있습니다 — 복사가 자기 자신을 품게 되어 거절합니다'
    if inside(source, dest):
        return '원본(source)이 백업 폴더(dest) 안에 있습니다 — 정리하다 원본을 지울 수 있어 거절합니다'
    return ''


def robocopy_args(source, snapshot, exclude=None, dry_run=False):
    args = ['robocopy', kit.expand(source), snapshot, '/E', '/R:1', '/W:1', '/NP', '/NFL', '/NDL']
    ex = [str(x) for x in (exclude or []) if str(x).strip()]
    if ex:
        args += ['/XF'] + ex
    if dry_run:
        args.append('/L')
    return args


def summary_tail(output, n=8):
    lines = [ln.rstrip() for ln in (output or '').splitlines() if ln.strip() and not set(ln.strip()) <= set('-=')]
    return '\n'.join(lines[-n:])


def truthy(v):
    return v is True or str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'on', '예')


# ---------------------------------------------------------------- 실제 작업 (테스트에서는 바꿔 끼운다)

def run_robocopy(args):
    """→ (종료 코드, 출력). robocopy 는 콘솔 코드페이지(OEM)로 찍는다."""
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return p.returncode, p.stdout.decode('oem' if os.name == 'nt' else 'utf-8', errors='replace')


def _on_rm_error(func, path, _exc):
    # 읽기 전용 파일은 속성을 풀고 다시 지운다
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _is_link(p):
    return os.path.islink(p) or (hasattr(os.path, 'isjunction') and os.path.isjunction(p))


def prune(dest, keep, current=None):
    """dest 바로 아래 날짜 모양 폴더 중 오래된 것을 지운다 → 지운 이름 목록. 링크·정션·파일은 건드리지 않는다."""
    try:
        names = [n for n in os.listdir(dest)
                 if os.path.isdir(os.path.join(dest, n)) and not _is_link(os.path.join(dest, n))]
    except OSError:
        return []
    gone = []
    for n in prune_plan(names, keep, current):
        p = os.path.join(dest, n)
        if os.path.dirname(os.path.abspath(p)) != os.path.abspath(dest) or not SNAP_RE.match(n):
            continue        # 한 번 더 — dest 바로 아래 날짜 폴더가 아니면 절대 지우지 않는다
        if sys.version_info >= (3, 12):
            shutil.rmtree(p, onexc=_on_rm_error)
        else:
            shutil.rmtree(p, onerror=_on_rm_error)
        if not os.path.exists(p):
            gone.append(n)
    return gone


def backup_one(item, now, dry_run=False, runner=None):
    """항목 하나 → {'ok', 'text', 'snapshot', 'pruned'}."""
    runner = runner or run_robocopy
    source, dest = item.get('source'), item.get('dest')
    why = check_paths(source, dest)
    if why:
        return {'ok': False, 'text': why, 'snapshot': '', 'pruned': []}
    dest = kit.expand(dest)
    name = now.strftime(SNAP_FMT)
    snapshot = os.path.join(dest, name)
    if not dry_run:
        os.makedirs(snapshot, exist_ok=True)
    code, out = runner(robocopy_args(source, snapshot, item.get('exclude'), dry_run))
    tail = summary_tail(out)
    if not robocopy_ok(code):
        text = 'robocopy 실패 (코드 %s)' % code
        if not dry_run and os.path.isdir(snapshot):
            failed = snapshot + FAILED_SUFFIX
            try:
                if not os.path.exists(failed):
                    os.rename(snapshot, failed)
                    text += ' — 덜 된 복사본: %s' % failed
            except OSError:
                pass
        return {'ok': False, 'text': text + ('\n' + tail if tail else ''), 'snapshot': snapshot, 'pruned': []}
    pruned = [] if dry_run else prune(dest, item.get('keep'), current=name)
    text = '%s%s (코드 %s)' % ('[미리보기] ' if dry_run else '', snapshot, code)
    if pruned:
        text += ' · 오래된 스냅숏 %d개 지움' % len(pruned)
    return {'ok': True, 'text': text + ('\n' + tail if tail else ''), 'snapshot': snapshot, 'pruned': pruned}


# ---------------------------------------------------------------- 한 번 돌기

def run(ctx):
    items = kit.section(FEATURE, [])
    if not isinstance(items, list) or not items:
        ctx.log('백업 항목이 없습니다 — config.local.json 의 "backups" 목록에 넣으세요.')
        kit.write_status(FEATURE, [], note='항목 없음')
        return
    f_state = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(f_state, {}) or {}
    manual = (ctx.trigger or {}).get('kind') == 'manual'
    dry_run = truthy((ctx.params or {}).get('dry_run'))
    only = str((ctx.params or {}).get('only') or '').strip()
    now = datetime.datetime.now()

    failed, status, ran = [], [], False
    for item in items:
        if not isinstance(item, dict) or not item.get('name'):
            failed.append(repr(item)[:40])
            status.append({'name': '(이름 없음)', 'ok': False, 'text': '설정 오류 — name 이 필요합니다'})
            continue
        name = str(item['name'])
        st = state.get(name) or {}
        when = '%s %s' % (item.get('at') or '?', item.get('days') or 'daily')
        enabled = item.get('enabled', True) is not False
        if manual:
            go = enabled and (not only or only == name)
        else:
            go = enabled and kit.due(item, st.get('last_run'), now)
        if go:
            ran = True
            ctx.log('▶ %s%s: %s → %s' % ('[미리보기] ' if dry_run else '', name, item.get('source'), item.get('dest')))
            try:
                r = backup_one(item, now, dry_run)
            except Exception as e:      # 한 항목이 터져도 나머지는 돈다
                r = {'ok': False, 'text': '%s: %s' % (type(e).__name__, e)}
            ctx.log(('○ ' if r['ok'] else '✖ ') + r['text'])
            if not r['ok']:
                failed.append(name)
            if not dry_run:
                st = {'last_run': time.time(), 'ok': r['ok'], 'text': r['text'].splitlines()[0],
                      'at': now.strftime('%Y-%m-%d %H:%M')}
                state[name] = st
        if not enabled:
            status.append({'name': name, 'ok': None, 'text': '꺼짐 (enabled: false) · %s' % when})
        elif st.get('at'):
            status.append({'name': name, 'ok': bool(st.get('ok')),
                           'text': '%s %s — %s · 예약 %s' % (st['at'], '성공' if st.get('ok') else '실패', st.get('text', ''), when)})
        else:
            status.append({'name': name, 'ok': None, 'text': '아직 안 돌았음 · 예약 %s' % when})

    if not ran and not failed:
        if manual:
            ctx.log('돌릴 항목이 없습니다 — 켜진(enabled) 항목이 없거나 only 이름이 맞지 않습니다.')
        return              # 돌 차례가 아니었다 — 상태 파일도 그대로 둔다
    if not dry_run:
        kit.write_json(f_state, state)
    kit.write_status(FEATURE, status, note='실패: %s' % ', '.join(failed) if failed else '')
    if failed:
        raise RuntimeError('백업 실패 항목: %s — 상태 화면과 로그를 보세요' % ', '.join(failed))
