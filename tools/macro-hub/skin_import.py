# -*- coding: utf-8 -*-
"""외부에서 받은 캐릭터 스프라이트 팩(PNG 시퀀스가 든 zip 또는 폴더)을 펫 스킨으로 바꾼다.

    python skin_import.py CatnDog.zip --name catdog          변환해서 web\\skins\\catdog 에 만든다
    python skin_import.py 풀어둔폴더 --list                   무엇을 찾았는지만 본다(아무것도 만들지 않음)
    python skin_import.py CatnDog.zip --name catdog --fps 10 --max-width 300 --force

하는 일
  1. PNG 를 모두 찾아 '캐릭터(cat/dog)'와 '동작 이름(Idle, Walk, Jump…)', '프레임 번호'를 파일 경로에서 읽는다.
     (예: cat\\Idle (3).png · Dog_Walk_07.png · dog/run1.png)
  2. 캐릭터마다 모든 프레임의 투명 여백을 같은 크기로 잘라 낸다(동작이 바뀌어도 크기·바닥선이 안 흔들리게) → 폭을 --max-width 로 줄인다.
  3. 동작을 펫 상태에 맞춘다(없으면 기본 표정에 효과를 입혀 대신한다) → skin.json 작성.
  4. 펫 우클릭 → 모습(스킨) 에서 고르면 바로 적용된다.

사용 조건(라이선스)은 팩마다 다르다 — 만든 폴더의 LICENSE.txt 에 출처와 조건을 꼭 적어 두자.
"""
import argparse
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SKINS = os.path.join(HERE, 'web', 'skins')
FRAME_RE = re.compile(r'^(?P<name>.*?)[\s_\-.]*\(?(?P<idx>\d+)\)?$')
MAX_FRAMES = 3000

# 펫 상태 ← 팩의 동작 이름(앞에 있을수록 우선). 정확히 같은 이름을 먼저, 없으면 이름에 포함된 것을 찾는다.
PICK = {
    'dog': {'alert': ['idle', 'stand', 'sitting', 'sit', 'wait'],
            'bark': ['bark', 'meow', 'attack', 'victory', 'dance', 'jump', 'happy', 'run'],
            'worried': ['hurt', 'sad', 'scared', 'itch', 'ko', 'knockout', 'fall', 'cry'],
            'sleep': ['sleeping1', 'sleep', 'rest', 'laying', 'lie', 'lay', 'nap', 'crouch']},
    'cat': {'idle': ['idle', 'stand', 'sitting', 'sit', 'wait'],
            'work': ['walk', 'type', 'work', 'run'],
            'happy': ['stretching', 'victory', 'dance', 'meow', 'jump', 'happy', 'run', 'walk'],
            'sad': ['sleeping2', 'hurt', 'sad', 'scared', 'itch', 'laying', 'ko', 'knockout', 'fall', 'cry']},
}
# 못 찾았을 때 기본 표정에 효과를 입혀 대신하는 방법
FALLBACK = {
    ('dog', 'sleep'): {'from': 'alert', 'filter': 'brightness(.72) saturate(.7)', 'fps': 3},
    ('dog', 'worried'): {'from': 'alert', 'filter': 'saturate(.65) brightness(.92)', 'fps': 5},
    ('dog', 'bark'): {'from': 'alert', 'fps': 16},
    ('cat', 'work'): {'from': 'idle', 'fps': 14},
    ('cat', 'happy'): {'from': 'idle', 'fps': 16},
    ('cat', 'sad'): {'from': 'idle', 'filter': 'saturate(.65) brightness(.92)', 'fps': 5},
}
# 고양이 '일하는 중' 을 일의 종류(motion)별로 조금씩 다르게 — 같은 동작에 효과만 바꾼다. 없는 종류(web·desktop)는 그냥 work
MOTION_VARIANTS = {
    'work:write': {'from': 'work', 'fps': 20},                 # 입력: 빠르게
    'work:mail': {'from': 'work', 'fps': 16},                  # 메일: 조금 빠르게
    'work:search': {'from': 'work', 'flip': True, 'fps': 9},   # 찾기: 반대쪽을 보며 천천히
}
SLOW = {'idle', 'stand', 'sit', 'sitting', 'wait', 'sleep', 'sleeping1', 'sleeping2', 'rest', 'laying', 'crouch'}      # 느긋한 동작은 fps 를 낮춘다


def detect_char(parts):
    """경로 조각(폴더·파일명)에서 cat/dog 를 읽는다. 깊은 곳부터 보고, 'catndog' 처럼 둘 다 든 조각은 건너뛴다."""
    for part in reversed(parts):
        p = part.lower()
        d, c = 'dog' in p, 'cat' in p
        if d and not c:
            return 'dog'
        if c and not d:
            return 'cat'
    return None


def collect(src):
    """[(경로 조각 목록, 읽는 함수)] — zip 이든 폴더든 같은 모양으로."""
    items = []
    if os.path.isdir(src):
        for root, _dirs, files in os.walk(src):
            for fn in files:
                if fn.lower().endswith('.png'):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, src).replace('\\', '/')
                    items.append((rel, (lambda p=full: open(p, 'rb').read())))
    else:
        z = zipfile.ZipFile(src)
        for info in z.infolist():
            n = info.filename
            if n.lower().endswith('.png') and not n.startswith('__MACOSX') and '/._' not in n and info.file_size < 50 * 1024 * 1024:
                items.append((n, (lambda i=info: z.read(i))))
    return items


def slice_sheets(items, frame=None):
    """가로로 이어 붙인 스프라이트 시트(PNG 한 장 = 동작 하나)를 정사각 프레임으로 잘라 시퀀스처럼 바꾼다.
    프레임 한 변은 시트 높이(또는 --frame). 폭이 그 배수가 아니면 시트가 아니라고 보고 건너뛴다."""
    out = []
    for rel, reader in items:
        im = Image.open(io.BytesIO(reader())).convert('RGBA')
        h = frame or im.size[1]
        if im.size[0] < h or im.size[0] % h:
            print('  (시트가 아님 — 건너뜀) %s %s' % (rel, im.size))
            continue
        for i in range(im.size[0] // h):
            buf = io.BytesIO()
            im.crop((i * h, 0, (i + 1) * h, im.size[1])).save(buf, 'PNG')
            out.append(('%s_%02d.png' % (rel[:-4], i), (lambda b=buf.getvalue(): b)))
    return out


def parse(items):
    """{char: {anim: [(idx, 경로, 읽는함수)]}}"""
    groups = defaultdict(lambda: defaultdict(list))
    for rel, reader in items:
        parts = [p for p in rel.replace('\\', '/').split('/') if p]
        stem = os.path.splitext(parts[-1])[0]
        char = detect_char(parts[:-1] + [stem]) or 'pet'
        m = FRAME_RE.match(stem)
        name, idx = (m.group('name'), int(m.group('idx'))) if m else (stem, 0)
        name = re.sub(r'(?i)^(cat|dog)[\s_\-.]*\d*[\s_\-.]*', '', name)
        if not name:                                            # 'cat/1.png' 처럼 이름이 번호뿐이면 폴더 이름을 동작으로 본다
            name = parts[-2] if len(parts) > 1 else 'idle'
        anim = re.sub(r'[^a-z0-9]', '', name.lower()) or 'idle'
        groups[char][anim].append((idx, rel, reader))
    for char in groups:
        for anim in groups[char]:
            groups[char][anim].sort(key=lambda t: (t[0], t[1]))
    return groups


def pick(anims, wanted):
    """wanted 의 앞 키워드부터 차례로: 같은 이름이 있으면 그것, 없으면 이름에 그 키워드가 든 것(예: victory → victorydance)."""
    for w in wanted:
        if w in anims:
            return w
        for a in sorted(anims):
            if w in a:
                return a
    return None


def report(groups):
    for char in sorted(groups):
        print('\n[%s]' % char)
        for anim in sorted(groups[char]):
            fr = groups[char][anim]
            print('  %-12s %3d 프레임   예: %s' % (anim, len(fr), fr[0][1]))


def build(groups, out_dir, name, max_width, fps, flip, pixel=False, title=None):
    os.makedirs(out_dir, exist_ok=True)
    chars = {c: a for c, a in groups.items() if c in ('cat', 'dog')}
    if not chars and 'pet' in groups:                           # 캐릭터가 하나뿐인 팩: 둘 다 같은 캐릭터를 쓴다
        chars = {'cat': groups['pet'], 'dog': groups['pet']}
        print('※ cat/dog 구분을 못 찾아 같은 캐릭터를 강아지·고양이 둘 다에 씁니다.')
    elif len(chars) == 1:
        only = next(iter(chars))
        other = 'dog' if only == 'cat' else 'cat'
        chars[other] = chars[only]
        print('※ %s 만 있어서 %s 에도 같은 캐릭터를 씁니다.' % (only, other))
    total = sum(len(f) for a in chars.values() for f in a.values())
    if total > MAX_FRAMES:
        raise SystemExit('프레임이 너무 많습니다(%d > %d). 폴더를 줄여서 다시 시도하세요.' % (total, MAX_FRAMES))

    skin = {'name': title or name, 'dog': {}, 'cat': {}}
    used_by_src = defaultdict(set)                              # 같은 원본을 두 역할이 나눠 쓰면 두 역할이 쓰는 동작의 합집합을 내보낸다
    for role in ('dog', 'cat'):
        used_by_src[id(chars[role])] |= {pick(set(chars[role]), wanted) for wanted in PICK[role].values()} - {None}
    written = {}                                                # (원본 그룹 id, anim) → 만든 파일 목록
    for char in ('dog', 'cat'):
        # 펫 상태에 실제로 연결되는 동작만 쓴다 — 안 쓰는 동작(Dead·Slide 처럼 넓게 눕는 자세)이 여백·크기를 좌우하지 않게 하고 파일도 줄인다
        used = used_by_src[id(chars[char])]
        anims = {a: f for a, f in chars[char].items() if a in used} or chars[char]
        key = id(chars[char])
        # 1) 이 캐릭터의 모든 프레임에 공통인 투명 여백(합집합)을 구한다
        images, box = {}, None
        for anim, frames in anims.items():
            for idx, rel, reader in frames:
                im = Image.open(io.BytesIO(reader())).convert('RGBA')
                if max(im.size) > 8000:
                    raise SystemExit('이미지가 너무 큽니다: ' + rel)
                images[(anim, idx, rel)] = im
                bb = im.getchannel('A').getbbox()
                if bb:
                    box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
        if box is None:
            raise SystemExit('%s: 보이는 픽셀이 없습니다' % char)
        w = box[2] - box[0]
        if pixel:                                               # 도트 그림: 정수 배로만 키워(NEAREST) 칸이 번지지 않게 한다
            up = max(1, int(max_width // w))
            scale = 1.0
            size = (w * up, (box[3] - box[1]) * up)
        else:
            up = 1
            scale = min(1.0, max_width / float(w))
            size = (max(1, round(w * scale)), max(1, round((box[3] - box[1]) * scale)))
        # 2) 같은 원본을 쓰는 다른 캐릭터(한 캐릭터 팩)는 한 번만 만든다
        if key in {k for k, _ in written}:
            names = written[(key, 'files')]
        else:
            names = {}
            for anim, frames in anims.items():
                files = []
                for n, (idx, rel, reader) in enumerate(frames):
                    im = images[(anim, idx, rel)].crop(box)
                    if pixel and up > 1:
                        im = im.resize(size, Image.NEAREST)
                    elif scale < 1.0:
                        im = im.resize(size, Image.LANCZOS)
                    if flip:
                        im = im.transpose(Image.FLIP_LEFT_RIGHT)
                    fn = '%s_%s_%02d.png' % (char, anim, n)
                    im.save(os.path.join(out_dir, fn), optimize=True)
                    files.append(fn)
                names[anim] = files
            written[(key, 'files')] = names
            written[(key, 'char')] = char
        # 3) 상태 ← 동작 연결
        prefix = written[(key, 'char')]
        for state, wanted in PICK[char].items():
            a = pick(set(names), wanted)
            if a:
                # 같은 원본을 두 캐릭터가 쓸 때 파일 이름의 접두사가 다르므로 만든 이름 그대로 쓴다
                skin[char][state] = {'frames': names[a], 'fps': 8 if a in SLOW else fps}
                if pixel:
                    skin[char][state]['pixel'] = True
            elif (char, state) in FALLBACK:
                skin[char][state] = dict(FALLBACK[(char, state)])
        if char == 'cat' and 'work' in skin[char]:
            for k, v in MOTION_VARIANTS.items():
                skin[char].setdefault(k, dict(v))
        print('%s: 상태 연결 → %s' % (char, ', '.join(
            '%s=%s' % (s, ('동작 ' + pick(set(names), PICK[char][s])) if pick(set(names), PICK[char][s]) else '기본 표정+효과')
            for s in PICK[char])))
    with open(os.path.join(out_dir, 'skin.json'), 'w', encoding='utf-8') as f:
        json.dump(skin, f, ensure_ascii=False, indent=1)
    lic = os.path.join(out_dir, 'LICENSE.txt')
    if not os.path.exists(lic):                                 # 이미 적어 둔 출처·조건은 덮어쓰지 않는다
      with open(lic, 'w', encoding='utf-8') as f:
        f.write('출처: (여기에 받은 곳의 주소와 만든 사람을 적으세요)\n라이선스: (CC0 / CC BY 등 — 표기 의무가 있으면 반드시 지키세요)\n'
                '가져온 날짜: %s\n이 폴더는 git 에 올라가지 않습니다.\n' % __import__('datetime').date.today())
    return skin


def main():
    ap = argparse.ArgumentParser(description='스프라이트 팩(PNG 시퀀스)을 펫 스킨으로 변환')
    ap.add_argument('src', help='zip 파일 또는 풀어 둔 폴더')
    ap.add_argument('--name', help='스킨 폴더 이름(영문·숫자·-_)')
    ap.add_argument('--list', action='store_true', help='찾은 캐릭터·동작만 보여 주고 끝낸다')
    ap.add_argument('--fps', type=int, default=12)
    ap.add_argument('--max-width', type=int, default=360)
    ap.add_argument('--flip', action='store_true', help='좌우 반전(원본이 왼쪽을 보고 있을 때)')
    ap.add_argument('--force', action='store_true', help='같은 이름 폴더가 있으면 덮어쓴다')
    ap.add_argument('--sheet', action='store_true', help='PNG 한 장이 가로로 이어 붙인 스프라이트 시트일 때(동작 하나 = 파일 하나)')
    ap.add_argument('--frame', type=int, help='시트의 프레임 한 변(px). 생략하면 시트 높이')
    ap.add_argument('--cat-variant', help='고양이 역할에 쓸 변형(경로에 들어 있는 글자. 예: cat-3)')
    ap.add_argument('--dog-variant', help='강아지 역할에 쓸 변형(예: cat-2 — 같은 팩의 다른 고양이를 써도 된다)')
    ap.add_argument('--pixel', action='store_true', help='도트 그림: 정수 배로 선명하게 키우고 화면에서도 번지지 않게 표시')
    ap.add_argument('--title', help='펫 메뉴에 보일 이름(출처 표기 의무가 있으면 여기에도 적자)')
    args = ap.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if not os.path.exists(args.src):
        raise SystemExit('없는 경로: ' + args.src)
    items = collect(args.src)
    if args.sheet:
        items = slice_sheets(items, args.frame)
    if args.cat_variant or args.dog_variant:
        groups = {}
        for role, v in (('cat', args.cat_variant), ('dog', args.dog_variant)):
            if not v:
                continue
            g = parse([i for i in items if v.lower() in i[0].lower()])
            found = g.get(role) or g.get('cat') or g.get('dog') or g.get('pet')
            if not found:
                raise SystemExit('변형 "%s" 에 해당하는 이미지가 없습니다.' % v)
            groups[role] = found
    else:
        groups = parse(items)
    if not groups:
        raise SystemExit('PNG 를 찾지 못했습니다. 폴더 구조를 확인하세요.')
    report(groups)
    if args.list:
        return
    if not args.name or not re.fullmatch(r'[\w\-]+', args.name):
        raise SystemExit('--name 에 영문·숫자·-_ 로 된 스킨 이름을 주세요.')
    out = os.path.join(SKINS, args.name)
    if os.path.exists(out) and not args.force:
        raise SystemExit('이미 있는 스킨입니다: %s  (덮어쓰려면 --force)' % out)
    if os.path.isdir(out):                                      # 덮어쓸 때 옛 변환 결과(PNG·skin.json)를 먼저 지운다 — 안 그러면 안 쓰는 파일이 남는다. LICENSE.txt 는 보존
        for fn in os.listdir(out):
            if fn.lower().endswith('.png') or fn == 'skin.json':
                os.remove(os.path.join(out, fn))
    skin = build(groups, out, args.name, args.max_width, args.fps, args.flip, args.pixel, args.title)
    n = len([f for f in os.listdir(out) if f.endswith('.png')])
    print('\n완료: %s  (PNG %d개)\n펫 우클릭 → 모습(스킨) → "%s" 를 고르세요.' % (out, n, args.name))
    print('※ LICENSE.txt 에 출처와 사용 조건을 적어 두세요.')


if __name__ == '__main__':
    main()
