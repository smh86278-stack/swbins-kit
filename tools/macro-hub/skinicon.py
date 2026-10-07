# -*- coding: utf-8 -*-
"""스킨 그림으로 트레이 아이콘 만들기 — 강아지(감시견) 상태 그림의 첫 장에서 얼굴 쪽을 잘라 쓴다.

    face_icon(skin_dir, kind, size)   kind: ok | warn | idle  →  PIL 이미지(size², 상태 점 없음) 또는 None(못 만들면 기본 그림)

상태 ← 스킨 상태: ok=alert · warn=worried · idle=sleep (없으면 alert 에 효과). 영상(webm·mp4)만 있는 스킨은 None.
"""
import json
import os
import re

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageOps

STATE = {'ok': 'alert', 'warn': 'worried', 'idle': 'sleep'}
# 스킨에 그 상태가 없으면 기본 표정에 이 효과를 입힌다(펫 화면의 대체 규칙과 같은 느낌)
FALLBACK_FILTER = {'warn': 'saturate(.65) brightness(.92)', 'idle': 'brightness(.72) saturate(.7)'}
_cache = {}


def _resolve(table, key, depth=0):
    """skin.json 의 상태 값 → {'file' 또는 'frames', 효과...}. from 을 따라간다."""
    v = table.get(key)
    if not v or depth > 4:
        return None
    o = {'file': v} if isinstance(v, str) else dict(v)
    if o.get('from') and o['from'] != key:
        base = _resolve(table, o['from'], depth + 1)
        if not base:
            return None
        base = dict(base)
        base.update({k: x for k, x in o.items() if k != 'from'})
        return base
    return o if (o.get('file') or o.get('frames')) else None


def _filter(img, css):
    """CSS filter 중 brightness · saturate · grayscale 만 흉내 낸다(아이콘에는 이 정도면 충분)."""
    for name, val in re.findall(r'(brightness|saturate|grayscale)\(\s*([\d.]+)\s*\)', css or ''):
        v = float(val)
        rgb, a = img.convert('RGB'), img.getchannel('A')
        if name == 'brightness':
            rgb = ImageEnhance.Brightness(rgb).enhance(v)
        elif name == 'saturate':
            rgb = ImageEnhance.Color(rgb).enhance(v)
        else:
            rgb = ImageEnhance.Color(rgb).enhance(max(0.0, 1 - v))
        img = rgb.convert('RGBA')
        img.putalpha(a)
    return img


def _face(img):
    """몸 전체 그림에서 얼굴 쪽 정사각형을 고른다 — 가장 위(귀·머리)에서 몸 높이의 25% 까지 칠해진 곳을 중심으로.
    옆모습(머리가 한쪽 끝)이어도 맨 위 띠에는 머리만 걸리므로 그쪽으로 맞춰진다."""
    alpha = img.getchannel('A').point(lambda p: 255 if p > 40 else 0)
    box = alpha.getbbox()
    if not box:
        return None
    x0, y0, x1, y1 = box
    h = y1 - y0
    band = alpha.crop((x0, y0, x1, y0 + max(1, int(h * 0.25)))).getbbox()
    bx0, bx1 = (x0 + band[0], x0 + band[2]) if band else (x0, x1)
    side = int(min(max((bx1 - bx0) * 1.45, h * 0.6), max(x1 - x0, h)))
    cx = (bx0 + bx1) // 2
    top = y0 - int(side * 0.03)
    sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    sq.paste(img.crop((cx - side // 2, top, cx - side // 2 + side, top + side)), (0, 0))
    return sq


def _badge(face, size, pixel):
    """밝은 원 위에 얼굴 — 어두운 작업 표시줄에서도 검은 캐릭터가 보이게. 4배로 그려 줄인다."""
    S = size * 4
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    disc = Image.new('L', (S, S), 0)
    ImageDraw.Draw(disc).ellipse((2, 2, S - 3, S - 3), fill=255)
    img.paste((241, 236, 255, 255), (0, 0), disc)   # 파스텔 라일락 원(app.py BADGE 와 같은 색)
    inner = int(S * 0.84)
    f = face.resize((inner, inner), Image.NEAREST if pixel else Image.LANCZOS)
    layer = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    layer.paste(f, ((S - inner) // 2, int(S * 0.1)), f)          # 귀가 원 안에 들게 조금 내리고, 원 밖으로 나간 몸은 잘라 낸다
    a = ImageChops.multiply(layer.getchannel('A'), disc)
    layer.putalpha(a)
    img.alpha_composite(layer)
    ImageDraw.Draw(img).ellipse((2, 2, S - 3, S - 3), outline=(138, 114, 238, 255), width=max(2, S // 32))
    return img.resize((size, size), Image.LANCZOS)


def face_icon(skin_dir, kind, size=64):
    mf = os.path.join(skin_dir, 'skin.json')
    try:
        key = (skin_dir, kind, size, os.path.getmtime(mf))
    except OSError:
        return None
    if key in _cache:
        return _cache[key]
    out = None
    try:
        table = (json.load(open(mf, encoding='utf-8-sig')) or {}).get('dog') or {}
        spec = _resolve(table, STATE[kind])
        if not spec and kind in FALLBACK_FILTER:
            spec = _resolve(table, 'alert')
            if spec:
                spec = dict(spec, filter=FALLBACK_FILTER[kind])
        frames = (spec or {}).get('frames') or []
        # 평소 모습은 첫 장, 걱정·잠은 동작이 무르익은 가운데 장(쓰러지기·웅크리기 같은 동작은 첫 장이 그냥 서 있다)
        f = (spec or {}).get('file') or (frames[0 if kind == 'ok' else len(frames) // 2] if frames else None)
        if f and not re.search(r'\.(mp4|webm)$', f, re.I) and os.path.basename(f) == f:
            img = Image.open(os.path.join(skin_dir, f))
            img.seek(0)                                   # GIF·APNG·WebP 는 첫 장
            img = img.convert('RGBA')
            if spec.get('flip'):
                img = ImageOps.mirror(img)
            img = _filter(img, spec.get('filter'))
            face = _face(img)
            if face:
                out = _badge(face, size, spec.get('pixel'))
    except Exception:
        out = None
    _cache[key] = out
    return out
