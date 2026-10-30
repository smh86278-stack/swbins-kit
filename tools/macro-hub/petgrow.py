"""화면 펫 키우기 — 자동화가 일을 덜어 줄 때마다 펫이 받는 '간식'을 센다.

규칙(부풀리기 어렵게):
- 간식 +1: 자동화가 성공하면 — 같은 자동화는 하루 한 번만. 시험(🧪)·도구·상시 서비스·'매 N분/시간' 되풀이 예약(폴러)은 세지 않는다.
- 고침 +2: 실패(또는 시간 초과)했던 자동화가 다음에 성공하면 — 같은 자동화는 하루 한 번만.
- 새 자동화 +3: 내 자동화(macros.local)가 새로 생기면 — 하루 두 개까지.
- AI 커밋 +1: Claude 와 함께 끝낸 커밋(Co-Authored-By: Claude) — 커밋마다 한 번, 하루 다섯 개까지(petsnack.py 가 찾는다).
- 좋은 프롬프트 +1: Claude Code 세션 첫 프롬프트가 규칙 점검을 💡 없이 통과 — 세션마다 한 번, 하루 세 개까지.
  이 둘은 그 일이 있던 날짜로 하루 한도를 세고, SEED_DAYS(7일)보다 오래된 일은 세지 않는다(처음 켤 때 한꺼번에 뛰지 않게).
레벨은 간식 누적으로 정해지고(LEVELS), 레벨마다 소품이 하나씩 풀린다(UNLOCK — web/pets.js PetAcc.LIST 와 같은 이름).
기록은 data.local/pet-grow.json(git 밖). 처음 만들 때 runs.jsonl 의 지난 기록으로 한 번 채운다(seed).
"""
import datetime
import json
import os

LEVELS = (0, 5, 15, 30, 50, 80, 120, 170, 230, 300)       # Lv1 부터 — 그 레벨이 되는 간식 수
UNLOCK = {'ribbon': 1, 'scarf': 2, 'glasses': 3, 'beret': 4, 'bowtie': 5, 'crown': 6}
FIX_BONUS = 2
NEW_BONUS = 3
NEW_PER_DAY = 2
BAD = ('fail', 'timeout')
EXTRA_CAP = {'ai': 5, 'prompt': 3}                       # 하루 한도 — AI 커밋 · 좋은 프롬프트
SEED_DAYS = 7                                            # 이보다 오래된 커밋·세션은 세지 않는다
KEEP_DAYS = 14                                           # 본 커밋·세션 기억은 이만큼만(그 전 것은 어차피 안 센다)


def blank():
    return {'snacks': 0, 'day': '', 'paid': [], 'fixed': [], 'made': 0, 'last': {}, 'known': None,
            'week': {'id': '', 'snacks': 0, 'fixes': 0}, 'prev_week': None, 'seeded': False,
            'src': {'ai': 0, 'prompt': 0}, 'xseen': {}, 'xday': {}, 'xcheck': {}, 'seed_log': {}}


def level(snacks):
    return sum(1 for t in LEVELS if snacks >= t)


def view(g):
    """화면에 줄 것 — {snacks, level, floor, next, week, prev_week, src}. next 는 다음 레벨 간식 수(끝이면 None).
    src = 어디서 받았나 {auto: 자동화, ai: AI 커밋, prompt: 좋은 프롬프트}."""
    s = g.get('snacks', 0)
    lv = level(s)
    src = g.get('src') or {}
    ai, pr = int(src.get('ai', 0)), int(src.get('prompt', 0))
    return {'snacks': s, 'level': lv, 'floor': LEVELS[lv - 1], 'next': LEVELS[lv] if lv < len(LEVELS) else None,
            'week': dict(g.get('week') or {}), 'prev_week': g.get('prev_week'),
            'src': {'auto': max(0, s - ai - pr), 'ai': ai, 'prompt': pr}}


def _week_id(d):
    y, w, _ = d.isocalendar()
    return '%d-W%02d' % (y, w)


def _roll(g, now):
    """날·주가 바뀌었으면 하루 한도와 주간 집계를 새로."""
    day = now.strftime('%Y-%m-%d')
    if g.get('day') != day:
        g['day'], g['paid'], g['fixed'], g['made'] = day, [], [], 0
    wk = _week_id(now)
    if (g.get('week') or {}).get('id') != wk:
        old = g.get('week') or {}
        if old.get('id'):
            g['prev_week'] = old
        g['week'] = {'id': wk, 'snacks': 0, 'fixes': 0}


def _add(g, n, week=True):
    before = level(g['snacks'])
    g['snacks'] += n
    if week:
        g['week']['snacks'] += n
    return level(g['snacks']) > before


def eligible(run, service=False):
    """간식을 셀 실행인가 — run 은 Run.summary() 꼴 dict."""
    if service or run.get('tool') or str(run.get('macro', '')).startswith('__'):
        return False
    trig = run.get('trigger')
    if trig in ('test', 'service', 'chain'):                       # 일 순서의 단계는 일 순서 하나로만 센다
        return False
    if trig == 'schedule' and str(run.get('detail', '')).startswith('매 '):   # '매 10m' 같은 되풀이 예약 = 폴러
        return False
    return True


def on_run(g, run, service=False, now=None):
    """끝난 실행 하나 → (얻은 간식, 레벨이 올랐나, 고쳤나). g 를 바꾼다."""
    now = now or datetime.datetime.now()
    _roll(g, now)
    if not eligible(run, service):
        return 0, False, False
    mid, st = run.get('macro'), run.get('status')
    prev = g['last'].get(mid)
    if st in BAD or st == 'ok':
        g['last'][mid] = st
    if st != 'ok':
        return 0, False, False
    gained, fixed = 0, False
    if mid not in g['paid']:
        g['paid'].append(mid)
        gained += 1
    if prev in BAD and mid not in g['fixed']:
        g['fixed'].append(mid)
        g['week']['fixes'] += 1
        gained += FIX_BONUS
        fixed = True
    up = _add(g, gained) if gained else False
    return gained, up, fixed


def on_macros(g, ids, now=None):
    """지금 있는 내 자동화 id 목록 → (얻은 간식, 레벨이 올랐나). 처음 보는 목록은 기준으로만 삼는다."""
    now = now or datetime.datetime.now()
    _roll(g, now)
    ids = set(ids)
    if g.get('known') is None:
        g['known'] = sorted(ids)
        return 0, False
    new = ids - set(g['known'])
    g['known'] = sorted(set(g['known']) | ids)
    n = min(len(new), max(0, NEW_PER_DAY - g['made']))
    if not n:
        return 0, False
    g['made'] += n
    return n * NEW_BONUS, _add(g, n * NEW_BONUS)


def seed(g, records, service_ids=()):
    """runs.jsonl 의 지난 기록(시간 순)으로 한 번 채운다 — 처음 켰을 때 0 에서 시작하지 않게."""
    for r in sorted(records, key=lambda x: x.get('started') or 0):
        try:
            when = datetime.datetime.fromtimestamp((r.get('ended') or r.get('started')) / 1000)
        except (TypeError, ValueError, OSError):
            continue
        on_run(g, r, r.get('macro') in service_ids, when)
    g['seeded'] = True
    return g


def on_extra(g, src, keys, when, now=None):
    """AI 커밋·좋은 프롬프트 한 건 → (얻은 간식, 레벨이 올랐나). g 를 바꾼다.
    src = 'ai' | 'prompt', keys = 이 일을 가리키는 키들(커밋 해시·같은 커밋의 다른 모양, 세션 id) — 하나라도 본 적 있으면 안 센다.
    when = 그 일이 있던 시각 — 그날 한도(EXTRA_CAP)로 세고, SEED_DAYS 보다 오래됐으면 기억만 한다."""
    now = now or datetime.datetime.now()
    _roll(g, now)
    keys = [k for k in (keys if isinstance(keys, (list, tuple)) else [keys]) if k]
    seen = g.setdefault('xseen', {}).setdefault(src, {})
    if not keys or any(k in seen for k in keys):
        return 0, False
    day = when.strftime('%Y-%m-%d')
    for k in keys:
        seen[k] = day
    if (now - when).total_seconds() > SEED_DAYS * 86400:
        return 0, False
    days = g.setdefault('xday', {}).setdefault(src, {})
    if days.get(day, 0) >= EXTRA_CAP[src]:
        return 0, False
    days[day] = days.get(day, 0) + 1
    srcs = g.setdefault('src', {'ai': 0, 'prompt': 0})
    srcs[src] = srcs.get(src, 0) + 1
    return 1, _add(g, 1, _week_id(when) == g['week']['id'])


def mark(g, src, key, when):
    """간식 없이 '봤다'만 기억(규칙에 걸린 프롬프트 세션 — 다시 안 읽게)."""
    g.setdefault('xseen', {}).setdefault(src, {})[key] = when.strftime('%Y-%m-%d')


def prune_extra(g, now=None):
    """KEEP_DAYS 보다 오래된 본 커밋·세션·날짜별 수를 지운다(기록 파일이 자라지 않게)."""
    now = now or datetime.datetime.now()
    cut = (now - datetime.timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d')
    for name in ('xseen', 'xday'):
        for src, d in (g.get(name) or {}).items():
            for k in [k for k, v in d.items() if (v if name == 'xseen' else k) < cut]:
                del d[k]


def load(path):
    try:
        with open(path, encoding='utf-8') as f:
            g = dict(blank(), **json.load(f))
        g['src'] = dict({'ai': 0, 'prompt': 0}, **(g.get('src') or {}))
    except (OSError, ValueError):
        g = blank()
    return g


def save(path, g):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(g, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass
