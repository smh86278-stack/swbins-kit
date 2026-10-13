# -*- coding: utf-8 -*-
"""호출 한도 조절 큐(ratelimit)·미터기(job_rate_meter) — 시계·잠자기를 가짜로, 네트워크 없음."""
import email.message
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
import ratelimit  # noqa: E402

spec = importlib.util.spec_from_file_location('job_rate_meter', os.path.join(HUB, 'macros', 'job_rate_meter.py'))
meter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meter)


class Clock:
    def __init__(self, t=1000.0):
        self.t, self.slept = t, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 2))
        self.t += s


def hdrs(**kw):
    m = email.message.Message()
    for k, v in kw.items():
        m[k.replace('_', '-')] = str(v)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.c = Clock()

    def lim(self, limit=3, window=10):
        return ratelimit.Limiter('mall', limit, window, state_dir=self.tmp, clock=self.c, sleep=self.c.sleep)


class Window(Base):
    def test_waits_for_oldest_call_to_leave(self):
        a = self.lim()
        for _ in range(3):
            self.assertEqual(a.acquire(), 0)
        self.c.t += 4
        self.assertAlmostEqual(a.try_acquire(), 6.0)                 # 첫 호출(1000) + 10초 창 - 지금(1004)
        waited = a.acquire()
        self.assertAlmostEqual(waited, 6.0, places=2)
        self.assertEqual(a.usage()['used'], 1)                       # 같은 때 한 세 번은 창을 벗어나고 새 한 번만

    def test_two_tools_share_one_budget(self):
        a, b = self.lim(), self.lim()                                # 같은 이름 = 같은 파일
        a.acquire(), b.acquire(), a.acquire()
        self.assertGreater(b.try_acquire(), 0)
        self.assertEqual(b.usage()['used'], 3)

    def test_timeout(self):
        a = self.lim(limit=1)
        a.acquire()
        with self.assertRaises(TimeoutError):
            a.acquire(timeout=1)

    def test_bad_name(self):
        with self.assertRaises(ValueError):
            ratelimit.Limiter('../x', 1, 1, state_dir=self.tmp)


class Learn(Base):
    def test_headers(self):
        h = hdrs(X_RateLimit_Remaining=0, X_RateLimit_Reset=5, X_RateLimit_Limit=100)
        self.assertEqual(ratelimit.header_hints(h, now=0), {'remaining': 0, 'reset_in': 5, 'limit': 100})
        self.assertEqual(ratelimit.retry_after(hdrs(Retry_After=7)), 7)
        self.assertIsNone(ratelimit.retry_after(hdrs()))

    def test_server_says_zero_left(self):
        a = self.lim(limit=100)
        a.observe(hdrs(X_RateLimit_Remaining=0, X_RateLimit_Reset=5), 200)
        self.assertAlmostEqual(a.try_acquire(), 5.0)                 # 내 창은 비었어도 서버가 0 이라 했다

    def test_429_cools_everyone(self):
        a, b = self.lim(limit=100), self.lim(limit=100)
        self.assertEqual(a.observe(hdrs(Retry_After=12), 429), 12)
        self.assertAlmostEqual(b.try_acquire(), 12.0)
        self.assertEqual(a.usage()['throttled'], 1)
        self.assertEqual(a.observe(hdrs(), 429, attempt=3), 8)      # Retry-After 없으면 2^attempt

    def test_guarded_urlopen_retries_429(self):
        a = self.lim(limit=100)
        calls = []

        class Ok:
            status, headers = 200, hdrs(X_RateLimit_Remaining=50)

        def opener(req):
            calls.append(req)
            if len(calls) < 3:
                raise urllib.error.HTTPError('https://x', 429, 'Too Many', hdrs(Retry_After=2), None)
            return Ok()
        resp = ratelimit.guarded_urlopen(a, 'REQ', opener=opener)
        self.assertEqual(resp.status, 200)
        self.assertEqual(len(calls), 3)
        self.assertIn(2, self.c.slept)

    def test_guarded_urlopen_gives_up(self):
        a = self.lim(limit=100)

        def opener(req):
            raise urllib.error.HTTPError('https://x', 429, 'Too Many', hdrs(Retry_After=1), None)
        with self.assertRaises(urllib.error.HTTPError):
            ratelimit.guarded_urlopen(a, 'REQ', retries=2, opener=opener)

    def test_other_errors_not_retried(self):
        a = self.lim(limit=100)
        n = []

        def opener(req):
            n.append(1)
            raise urllib.error.HTTPError('https://x', 400, 'Bad', hdrs(), None)
        with self.assertRaises(urllib.error.HTTPError):
            ratelimit.guarded_urlopen(a, 'REQ', opener=opener)
        self.assertEqual(len(n), 1)


class Meter(Base):
    def test_all_usage_and_alerts(self):
        a = self.lim(limit=10)
        for _ in range(9):
            a.acquire()
        us = ratelimit.all_usage(state_dir=self.tmp, clock=self.c, cfg={'rate_limits': {'mall': {'limit': 10, 'window_sec': 10}, 'other': {'limit': 5}}})
        self.assertEqual([(u['name'], u['used']) for u in us], [('mall', 9), ('other', 0)])
        items, alerts, now = meter.evaluate(us, {}, 80)
        self.assertEqual(now, {'mall': 'high', 'other': 'ok'})
        self.assertEqual([s for s, _ in alerts], ['[호출 한도] mall 거의 참'])
        self.assertIsNone(items[0]['ok'])
        self.assertEqual(meter.evaluate(us, now, 80)[1], [])         # 그대로면 다시 안 알림
        a.observe(hdrs(Retry_After=30), 429)
        us = ratelimit.all_usage(state_dir=self.tmp, clock=self.c)
        items, alerts, now2 = meter.evaluate(us, now, 80)
        self.assertEqual(alerts[0][0], '[호출 한도] mall 막힘(429)')
        self.c.t += 100
        items, alerts, _ = meter.evaluate(ratelimit.all_usage(state_dir=self.tmp, clock=self.c), now2, 80)
        self.assertEqual(alerts[0][0], '[호출 한도] mall 풀림')


if __name__ == '__main__':
    unittest.main()
