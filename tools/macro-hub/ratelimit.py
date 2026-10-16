# -*- coding: utf-8 -*-
"""마켓 API 호출 한도 지키기 — 여러 프로그램이 같은 한도를 나눠 쓰는 조절 큐 + 미터기. 표준 라이브러리만.

    import ratelimit
    lim = ratelimit.Limiter('cafe24', limit=3000, window_sec=600)       # 10분 3,000회
    with ratelimit.guarded_urlopen(lim, req) as r:                       # 차례를 기다렸다가 보내고, 429 면 쉬었다 다시
        data = r.read()
    lim.acquire()   # 직접 부를 때 — 자리가 날 때까지 기다린다(돌려주는 값: 기다린 초)
    lim.observe(resp.headers, resp.status)                               # 응답 머리글로 남은 횟수·쉬는 시간 배우기

한도는 config "rate_limits" 갈래에 둘 수 있다 — {"cafe24": {"limit": 3000, "window_sec": 600}} → ratelimit.from_config('cafe24').
- 같은 이름의 Limiter 는 data.local/rate_limits/<이름>.json 을 같이 쓴다(파일 잠금) — 자동화·도구·게이트웨이가 따로 돌아도
  한도를 함께 센다. 창은 미끄러지는 창(window_sec 안의 호출 시각 목록).
- 응답 머리글: Retry-After(초·날짜), X-RateLimit-Remaining/-Limit/-Reset 류(대소문자·접두어 상관없이 'remaining'·'reset' 을
  찾는다), 429·503 이면 Retry-After(없으면 지수 대기)만큼 이 이름 전체가 쉰다.
- 미터기: usage() → 창 안 사용량·한도·비율·쉬는 중인지·최근 429. 자동화 job_rate_meter 가 운영 화면 「📊 기능 상태」와 알림에 쓴다.
"""
import email.utils
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, 'data.local', 'rate_limits')
KEEP_EVENTS = 50


class _FileLock:
    """같은 PC 의 여러 프로세스가 한 상태 파일을 번갈아 쓰게 — 잠금 파일을 만들어(O_EXCL) 잡는다."""

    def __init__(self, path, timeout=30, stale=60):
        self.path, self.timeout, self.stale = path + '.lock', timeout, stale

    def __enter__(self):
        end = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:                                       # 잡은 채 죽은 프로세스의 잠금은 stale 초 뒤 치운다
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.time() > end:
                    raise TimeoutError('호출 한도 잠금을 잡지 못했습니다: %s' % self.path)
                time.sleep(0.02)

    def __exit__(self, *a):
        try:
            os.remove(self.path)
        except OSError:
            pass


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def retry_after(headers, now=None):
    """Retry-After(초 또는 HTTP 날짜) → 기다릴 초. 없으면 None."""
    v = (headers or {}).get('Retry-After') if hasattr(headers, 'get') else None
    if v is None:
        return None
    n = _num(v)
    if n is not None:
        return max(0.0, n)
    try:
        return max(0.0, email.utils.parsedate_to_datetime(v).timestamp() - (now if now is not None else time.time()))
    except (TypeError, ValueError):
        return None


def header_hints(headers, now=None):
    """한도 머리글 → {'remaining', 'limit', 'reset_in'} (있는 것만). 이름은 대소문자·접두어 상관없이 찾는다."""
    out = {}
    items = headers.items() if hasattr(headers, 'items') else []
    for k, v in items:
        kl = k.lower()
        if 'ratelimit' not in kl.replace('-', '').replace('_', '') and 'rate-limit' not in kl:
            continue
        n = _num(v)
        if n is None:
            continue
        if 'remaining' in kl:
            out['remaining'] = n
        elif 'reset' in kl:
            now = now if now is not None else time.time()
            out['reset_in'] = n - now if n > 10 ** 9 else n        # 유닉스 시각이면 남은 초로
        elif kl.endswith('limit') or 'limit-limit' in kl or 'capacity' in kl:
            out['limit'] = n
    return out


class Limiter:
    def __init__(self, name, limit, window_sec, state_dir=None, clock=time.time, sleep=time.sleep):
        if not re.fullmatch(r'[\w\-.]+', str(name)):
            raise ValueError('한도 이름은 영문·숫자·_-. 만: %r' % name)
        if int(limit) < 1 or float(window_sec) <= 0:
            raise ValueError('limit 은 1 이상, window_sec 은 0 보다 커야 합니다')
        self.name, self.limit, self.window = str(name), int(limit), float(window_sec)
        self.dir = state_dir or STATE_DIR
        self.path = os.path.join(self.dir, self.name + '.json')
        self.clock, self.sleep = clock, sleep

    # ---- 상태 파일
    def _load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                st = json.load(f)
            return st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, st):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + '.%d.tmp' % os.getpid()
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(st, f)
        os.replace(tmp, self.path)

    def _trim(self, st, now):
        st['calls'] = [t for t in st.get('calls') or [] if now - t < self.window]
        st['limit'], st['window_sec'] = self.limit, self.window
        return st

    # ---- 차례 잡기
    def try_acquire(self):
        """자리가 있으면 한 번 쓰고 0, 없으면 기다려야 할 초."""
        os.makedirs(self.dir, exist_ok=True)
        with _FileLock(self.path):
            now = self.clock()
            st = self._trim(self._load(), now)
            cool = (st.get('cooldown_until') or 0) - now
            if cool > 0:
                return cool
            reset_at = st.get('server_reset_at') or 0
            if st.get('server_remaining') is not None and now < reset_at and st['server_remaining'] <= 0:
                return max(0.01, reset_at - now)                     # 서버가 0 남았다고 했다 — 서버의 초기화 시각까지
            if len(st['calls']) >= self.limit:
                return max(0.01, st['calls'][0] + self.window - now)  # 내 창이 찼다 — 가장 오래된 호출이 창을 벗어날 때까지
            st['calls'].append(now)
            if st.get('server_remaining') is not None and now < reset_at:
                st['server_remaining'] = max(0, st['server_remaining'] - 1)
            st['total'] = int(st.get('total') or 0) + 1
            self._save(st)
            return 0.0

    def acquire(self, timeout=None):
        """자리가 날 때까지 기다린다 → 기다린 초. timeout 을 넘기면 TimeoutError."""
        start = self.clock()
        while True:
            wait = self.try_acquire()
            if wait <= 0:
                return self.clock() - start
            if timeout is not None and self.clock() - start + wait > timeout:
                raise TimeoutError('%s 호출 한도 — %.1f초를 더 기다려야 합니다' % (self.name, wait))
            self.sleep(min(wait, 5.0))

    # ---- 응답에서 배우기
    def observe(self, headers=None, status=None, attempt=0):
        """응답 머리글·상태로 남은 횟수와 쉬는 시간을 배운다 → 이 이름 전체가 쉴 초(없으면 0)."""
        now = self.clock()
        hints = header_hints(headers or {}, now)
        wait = 0.0
        if status in (429, 503):
            wait = retry_after(headers or {}, now)
            if wait is None:
                wait = min(60.0, 2.0 ** max(0, attempt))               # 1·2·4·8… 초, 60초까지
        with _FileLock(self.path):
            st = self._trim(self._load(), now)
            if 'remaining' in hints:
                st['server_remaining'] = int(hints['remaining'])
                st['server_reset_at'] = now + (hints.get('reset_in') if hints.get('reset_in') is not None else self.window)
            if hints.get('limit'):
                st['server_limit'] = int(hints['limit'])
            if wait:
                st['cooldown_until'] = max(st.get('cooldown_until') or 0, now + wait)
                ev = st.setdefault('events', [])
                ev.append({'ts': now, 'status': status, 'wait': round(wait, 1)})
                st['events'] = ev[-KEEP_EVENTS:]
            self._save(st)
        return wait

    # ---- 미터기
    def usage(self):
        now = self.clock()
        st = self._trim(self._load(), now)
        used = len(st['calls'])
        recent = [e for e in st.get('events') or [] if now - e.get('ts', 0) < self.window]
        return {'name': self.name, 'used': used, 'limit': self.limit, 'window_sec': self.window,
                'pct': round(100.0 * used / self.limit, 1), 'cooling': max(0.0, (st.get('cooldown_until') or 0) - now),
                'throttled': len(recent), 'server_remaining': st.get('server_remaining'), 'total': int(st.get('total') or 0)}


def from_config(name, cfg=None, **kw):
    """config "rate_limits" 의 한 줄로 Limiter."""
    if cfg is None:
        import kit
        cfg = kit.load_config()
    c = (cfg.get('rate_limits') or {}).get(name)
    if not isinstance(c, dict):
        raise KeyError('config rate_limits 에 %s 가 없습니다' % name)
    return Limiter(name, c['limit'], c.get('window_sec') or 60, **kw)


def guarded_urlopen(lim, req, retries=3, timeout=30, opener=None, **kw):
    """차례를 기다렸다가 보내고, 응답 머리글로 배우고, 429·503 이면 쉬었다가 retries 번까지 다시. 응답 객체를 돌려준다."""
    opener = opener or (lambda r: urllib.request.urlopen(r, timeout=timeout, **kw))
    attempt = 0
    while True:
        lim.acquire()
        try:
            resp = opener(req)
        except urllib.error.HTTPError as e:
            wait = lim.observe(e.headers, e.code, attempt)
            if e.code in (429, 503) and attempt < retries:
                attempt += 1
                lim.sleep(min(wait, 120))
                continue
            raise
        lim.observe(getattr(resp, 'headers', None), getattr(resp, 'status', 200))
        return resp


def all_usage(state_dir=None, cfg=None, clock=time.time):
    """설정에 있는 한도와, 상태 파일만 있는 것까지 모두의 usage."""
    d = state_dir or STATE_DIR
    conf = (cfg or {}).get('rate_limits') or {}
    names = set(conf)
    try:
        names |= {f[:-5] for f in os.listdir(d) if f.endswith('.json')}
    except OSError:
        pass
    out = []
    for n in sorted(names):
        c = conf.get(n) if isinstance(conf.get(n), dict) else None
        if c is None:
            try:
                with open(os.path.join(d, n + '.json'), encoding='utf-8') as f:
                    st = json.load(f)
                c = {'limit': st.get('limit') or 1, 'window_sec': st.get('window_sec') or 60}
            except (OSError, ValueError):
                continue
        try:
            out.append(Limiter(n, c['limit'], c.get('window_sec') or 60, state_dir=d, clock=clock).usage())
        except (ValueError, KeyError):
            continue
    return out
