# -*- coding: utf-8 -*-
"""✨ 나만의 앱 버전 — 고칠 때마다 앱 폴더를 통째로 남기고, 되돌리고, 바뀐 곳을 본다. 표준 라이브러리만.

버전은 앱 폴더의 .history\\ 에 zip 하나씩(<시각>-<번호>.zip) + index.json(목록·설명).
점으로 시작하는 폴더(.history·.check)는 담지 않는다. 앱 데이터(data.local\\apps\\<id>)는 버전과 따로다 —
되돌려도 사람이 넣은 데이터는 그대로다(DB 구조가 바뀌는 고치기라면 앱이 CREATE TABLE IF NOT EXISTS 로 견딘다).
허브가 남기는 때: AI 에게 설계서·만들기·고치기를 맡기기 **전**, 허브가 직접 돌린 AI 가 끝난 **뒤**, 설계서를 사람이 저장하기 전,
되돌리기 전(되돌리기도 되돌릴 수 있게), 「지금 저장」. 같은 내용이면 새로 남기지 않는다. 오래된 것부터 지워 KEEP 개까지.
"""
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import zipfile

KEEP = 30                  # 앱마다 남길 버전 수(설정 apps.history_keep)
DIFF_MAX = 200_000         # 바뀐 곳을 보여 줄 파일 크기 상한(글자)
TEXT_EXTS = ('.html', '.js', '.mjs', '.css', '.json', '.md', '.svg', '.txt')
_lock = threading.Lock()


def _hist(app_dir):
    return os.path.join(app_dir, '.history')


def _index_path(app_dir):
    return os.path.join(_hist(app_dir), 'index.json')


def _read_index(app_dir):
    try:
        with open(_index_path(app_dir), encoding='utf-8') as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _write_index(app_dir, items):
    os.makedirs(_hist(app_dir), exist_ok=True)
    tmp = _index_path(app_dir) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _index_path(app_dir))


def files(app_dir):
    """앱 폴더의 파일 {상대 경로(/): 내용 bytes} — 점으로 시작하는 폴더·파일은 빼고."""
    out = {}
    for root, dirs, names in os.walk(app_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for name in sorted(names):
            if name.startswith('.'):
                continue
            path = os.path.join(root, name)
            with open(path, 'rb') as f:
                out[os.path.relpath(path, app_dir).replace(os.sep, '/')] = f.read()
    return out


def _digest(fs):
    h = hashlib.sha256()
    for rel in sorted(fs):
        h.update(rel.encode('utf-8') + b'\0' + hashlib.sha256(fs[rel]).digest())
    return h.hexdigest()[:16]


def _zip_files(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist() if not n.endswith('/')}


def history(app_dir):
    """버전 목록 — 새것 먼저 [{id, at, label, files, size}]."""
    return [v for v in reversed(_read_index(app_dir)) if os.path.isfile(os.path.join(_hist(app_dir), v['id'] + '.zip'))]


def snapshot(app_dir, label, keep=KEEP):
    """지금 앱 폴더를 버전으로 남긴다 — 남긴 버전(dict), 마지막 버전과 같으면 None."""
    with _lock:
        fs = files(app_dir)
        digest = _digest(fs)
        items = _read_index(app_dir)
        if items and items[-1].get('digest') == digest:
            return None
        os.makedirs(_hist(app_dir), exist_ok=True)
        seq = (int(items[-1]['id'][-3:]) + 1) % 1000 if items else 0   # 같은 초에 여러 번 남겨도(정리 뒤에도) 겹치지 않게
        stamp = time.strftime('%Y%m%d-%H%M%S')
        while os.path.exists(os.path.join(_hist(app_dir), '%s-%03d.zip' % (stamp, seq))):
            seq = (seq + 1) % 1000
        vid = '%s-%03d' % (stamp, seq)
        with zipfile.ZipFile(os.path.join(_hist(app_dir), vid + '.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
            for rel, data in fs.items():
                z.writestr(rel, data)
        v = {'id': vid, 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'label': str(label or '')[:80],
             'files': len(fs), 'size': sum(len(d) for d in fs.values()), 'digest': digest}
        items.append(v)
        while len(items) > max(1, int(keep or KEEP)):
            old = items.pop(0)
            try:
                os.remove(os.path.join(_hist(app_dir), old['id'] + '.zip'))
            except OSError:
                pass
        _write_index(app_dir, items)
        return v


def _find(app_dir, vid):
    if not re.fullmatch(r'\d{8}-\d{6}-\d{3}', vid or ''):
        raise ValueError('잘못된 버전입니다')
    path = os.path.join(_hist(app_dir), vid + '.zip')
    if not os.path.isfile(path):
        raise ValueError('없는 버전입니다: %s' % vid)
    return path


def restore(app_dir, vid, keep=KEEP):
    """그 버전으로 되돌린다 — 되돌리기 전 지금 모습을 먼저 버전으로 남긴다. (남긴 버전|None, 되돌린 파일 수)."""
    path = _find(app_dir, vid)
    saved = snapshot(app_dir, '되돌리기 전 (→ %s)' % vid, keep)
    with _lock:
        fs = _zip_files(path)
        for entry in os.listdir(app_dir):
            if entry.startswith('.'):
                continue
            p = os.path.join(app_dir, entry)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        root = os.path.realpath(app_dir)
        for rel, data in fs.items():
            dst = os.path.realpath(os.path.join(root, *rel.split('/')))
            if not dst.startswith(root + os.sep):
                continue                                    # zip 안 경로 탈출 막기
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(data)
    return saved, len(fs)


def _text(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def diff(app_dir, vid, against=None):
    """그 버전 → 지금(against 가 버전이면 그 버전)으로 바뀐 곳.
    {added, removed, changed: [{path, plus, minus, diff}]} — diff 는 통합 형식(글자 파일만, 너무 크면 생략)."""
    old = _zip_files(_find(app_dir, vid))
    new = _zip_files(_find(app_dir, against)) if against else files(app_dir)
    out = {'from': vid, 'to': against or '지금', 'added': sorted(set(new) - set(old)), 'removed': sorted(set(old) - set(new)),
           'changed': []}
    for rel in sorted(set(old) & set(new)):
        if old[rel] == new[rel]:
            continue
        a, b = _text(old[rel]), _text(new[rel])
        item = {'path': rel, 'plus': 0, 'minus': 0, 'diff': ''}
        if a is None or b is None or not rel.lower().endswith(TEXT_EXTS):
            item['diff'] = '(글자 파일이 아니라 내용 비교는 생략 — %d → %d 바이트)' % (len(old[rel]), len(new[rel]))
        elif len(a) + len(b) > DIFF_MAX:
            item['diff'] = '(파일이 커서 내용 비교는 생략)'
        else:
            lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), 'before/' + rel, 'after/' + rel, n=2, lineterm=''))
            item['plus'] = sum(1 for ln in lines if ln.startswith('+') and not ln.startswith('+++'))
            item['minus'] = sum(1 for ln in lines if ln.startswith('-') and not ln.startswith('---'))
            item['diff'] = '\n'.join(lines)
        out['changed'].append(item)
    return out


def export_zip(app_dir, vid=None):
    """버전(없으면 지금)을 zip bytes 로 — 3e 내보내기에서 쓴다."""
    fs = _zip_files(_find(app_dir, vid)) if vid else files(app_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel, data in fs.items():
            z.writestr(rel, data)
    return buf.getvalue()
