# -*- coding: utf-8 -*-
"""감시·백업 매크로(job_monitors · job_pc_watch · job_backup)의 판단 로직 회귀 테스트.

    python -X utf8 -m unittest tests.test_features_b -v

네트워크·실제 robocopy 없이 돈다 — 확인 함수와 robocopy 실행기는 가짜를 끼우고, 폴더는 임시 폴더만 쓴다.
"""
import datetime
import importlib.util
import os
import shutil
import ssl
import sys
import tempfile
import unittest
import urllib.error

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HUB, 'macros', name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mon = _load('job_monitors')
pcw = _load('job_pc_watch')
bak = _load('job_backup')

GB = 1024 ** 3
T0 = 1_800_000_000.0


# ---------------------------------------------------------------- 감시

class NextState(unittest.TestCase):
    def test_down_only_after_fail_after(self):
        st, ev = mon.next_state({}, False, T0, 2)
        self.assertEqual((st['fails'], st['down'], ev), (1, False, None))
        st, ev = mon.next_state(st, False, T0 + 300, 2)
        self.assertEqual((st['fails'], st['down'], ev), (2, True, 'down'))
        self.assertEqual(st['since'], T0)               # 처음 실패한 때부터
        st, ev = mon.next_state(st, False, T0 + 600, 2)
        self.assertEqual((st['down'], ev), (True, None))  # 내려간 동안은 다시 알리지 않는다

    def test_recovery_reports_downtime(self):
        st, _ = mon.next_state({}, False, T0, 1)
        st, ev = mon.next_state(st, True, T0 + 3900, 1)
        self.assertEqual(ev, 'up')
        self.assertEqual(st['downtime'], 3900)
        self.assertEqual((st['fails'], st['down'], st['since']), (0, False, None))

    def test_blip_is_silent(self):
        st, ev = mon.next_state({}, False, T0, 3)
        st, ev2 = mon.next_state(st, True, T0 + 60, 3)
        self.assertEqual((ev, ev2, st['fails']), (None, None, 0))


class Cert(unittest.TestCase):
    def test_days_left(self):
        exp = ssl.cert_time_to_seconds('Jun  1 12:00:00 2027 GMT')
        self.assertEqual(mon.cert_days_left('Jun  1 12:00:00 2027 GMT', exp - 10 * 86400 - 5), 10)
        self.assertEqual(mon.cert_days_left('Jun  1 12:00:00 2027 GMT', exp - 3600), 0)
        self.assertEqual(mon.cert_days_left('Jun  1 12:00:00 2027 GMT', exp + 86400), -1)

    def test_alert_rules(self):
        send, st = mon.cert_alert(30, 14, {}, T0)
        self.assertEqual((send, st), (False, {}))
        send, st = mon.cert_alert(14, 14, {}, T0)
        self.assertTrue(send)
        send, st = mon.cert_alert(13, 14, st, T0 + 86400)
        self.assertFalse(send)                          # 한 번만
        send, st = mon.cert_alert(3, 14, st, T0 + 11 * 86400)
        self.assertTrue(send)                           # D-3 에서 한 번 더
        send, st = mon.cert_alert(2, 14, st, T0 + 12 * 86400)
        self.assertFalse(send)
        send, st = mon.cert_alert(90, 14, st, T0 + 13 * 86400)
        self.assertEqual((send, st), (False, {}))       # 갱신되면 비운다

    def test_alert_at_most_daily(self):
        send, st = mon.cert_alert(5, 14, {}, T0)
        self.assertTrue(send)
        send, st = mon.cert_alert(3, 14, st, T0 + 3600)
        self.assertFalse(send)                          # 하루 안에는 다시 안 보낸다
        send, st = mon.cert_alert(2, 14, st, T0 + 86400)
        self.assertTrue(send)

    def test_first_alert_inside_urgent_counts(self):
        send, st = mon.cert_alert(2, 14, {}, T0)
        self.assertTrue(send and st['urgent_sent'])
        send, st = mon.cert_alert(1, 14, st, T0 + 2 * 86400)
        self.assertFalse(send)


class _Resp:
    def __init__(self, status):
        self.status = status

    def close(self):
        pass


class Checks(unittest.TestCase):
    def test_head_then_get(self):
        seen = []

        def fake(req, timeout):
            seen.append(req.get_method())
            if req.get_method() == 'HEAD':
                raise urllib.error.HTTPError(req.full_url, 405, 'Method Not Allowed', {}, None)
            return _Resp(200)
        ok, err, code = mon.check_url('https://x.test/', urlopen=fake)
        self.assertEqual((ok, code, seen), (True, 200, ['HEAD', 'GET']))

    def test_head_ok(self):
        ok, _, code = mon.check_url('http://x.test/', urlopen=lambda req, timeout: _Resp(204))
        self.assertTrue(ok)

    def test_url_down(self):
        def fake(req, timeout):
            raise urllib.error.URLError('connection refused')
        ok, err, _ = mon.check_url('http://x.test/', urlopen=fake)
        self.assertFalse(ok)
        self.assertIn('refused', err)

    def test_http_500(self):
        ok, err, code = mon.check_url('http://x.test/', urlopen=lambda req, timeout: _Resp(503))
        self.assertEqual((ok, code), (False, 503))
        self.assertIn('503', err)

    def test_tcp(self):
        class S:
            def close(self):
                pass
        self.assertEqual(mon.check_tcp('h', 5432, connect=lambda a, timeout: S()), (True, ''))

        def refuse(a, timeout):
            raise ConnectionRefusedError('refused')
        ok, err = mon.check_tcp('h', 5432, connect=refuse)
        self.assertFalse(ok)
        self.assertIn('ConnectionRefusedError', err)

    def test_probe_reads_cert_for_https(self):
        deps = {'check_url': lambda u, c: (True, '', 200), 'read_cert': lambda u, c: 'Jun  1 12:00:00 2027 GMT'}
        r = mon.probe({'name': 'a', 'url': 'https://a.test/'}, None, deps)
        self.assertEqual((r['ok'], r['not_after']), (True, 'Jun  1 12:00:00 2027 GMT'))
        r = mon.probe({'name': 'a', 'url': 'http://a.test/'}, None, deps)
        self.assertIsNone(r['not_after'])

    def test_target_kind(self):
        self.assertEqual(mon.target_kind({'url': 'https://a'}), 'url')
        self.assertEqual(mon.target_kind({'host': 'h', 'port': 22}), 'tcp')
        self.assertIsNone(mon.target_kind({'url': 'ftp://a'}))
        self.assertIsNone(mon.target_kind({'host': 'h'}))


class Evaluate(unittest.TestCase):
    CONF = {'fail_after': 2, 'cert_warn_days': 14,
            'targets': [{'name': '웹', 'url': 'https://a.test/'}, {'name': 'DB', 'host': 'h', 'port': 5432}]}

    def test_flow(self):
        up = {'웹': {'ok': True, 'ms': 12}, 'DB': {'ok': True, 'ms': 3}}
        down = {'웹': {'ok': False, 'error': 'timed out'}, 'DB': {'ok': True}}
        st, items, alerts, bad = mon.evaluate(self.CONF, {}, up, T0)
        self.assertEqual((alerts, bad), ([], []))
        self.assertTrue(all(i['ok'] is True for i in items))
        st, items, alerts, _ = mon.evaluate(self.CONF, st, down, T0 + 60)
        self.assertEqual(alerts, [])
        self.assertIsNone(items[0]['ok'])               # 한 번 실패는 '확인 실패 1/2'
        st, items, alerts, _ = mon.evaluate(self.CONF, st, down, T0 + 120)
        self.assertEqual(len(alerts), 1)
        self.assertIn('접속 안 됨', alerts[0][0])
        self.assertIn('timed out', alerts[0][1])
        self.assertFalse(items[0]['ok'])
        st, items, alerts, _ = mon.evaluate(self.CONF, st, down, T0 + 180)
        self.assertEqual(alerts, [])
        st, items, alerts, _ = mon.evaluate(self.CONF, st, up, T0 + 3720)
        self.assertEqual(len(alerts), 1)
        self.assertIn('복구', alerts[0][0])
        self.assertIn('1시간 1분', alerts[0][1])

    def test_cert_text_and_alert(self):
        exp = T0 + 10 * 86400 + 100
        not_after = datetime.datetime.fromtimestamp(exp, datetime.timezone.utc).strftime('%b %d %H:%M:%S %Y GMT')
        res = {'웹': {'ok': True, 'not_after': not_after}, 'DB': {'ok': True}}
        st, items, alerts, _ = mon.evaluate(self.CONF, {}, res, T0)
        self.assertIn('인증서 D-10', items[0]['text'])
        self.assertIsNone(items[0]['ok'])
        self.assertEqual(len(alerts), 1)
        st, items, alerts, _ = mon.evaluate(self.CONF, st, res, T0 + 300)
        self.assertEqual(alerts, [])

    def test_bad_target(self):
        conf = {'targets': [{'name': '이상함', 'host': 'h'}]}
        _, items, _, bad = mon.evaluate(conf, {}, {}, T0)
        self.assertEqual(bad, ['이상함'])
        self.assertFalse(items[0]['ok'])

    def test_duration(self):
        self.assertEqual(mon.fmt_duration(30), '1분 미만')
        self.assertEqual(mon.fmt_duration(90061), '1일 1시간 1분')


# ---------------------------------------------------------------- PC 디스크

class Disk(unittest.TestCase):
    def test_low_disk(self):
        self.assertTrue(pcw.low_disk(100 * GB, 5 * GB, 10, 0))
        self.assertFalse(pcw.low_disk(100 * GB, 50 * GB, 10, 10))
        self.assertTrue(pcw.low_disk(1000 * GB, 50 * GB, 10, 10))     # GB 는 넉넉해도 % 가 모자라면
        self.assertFalse(pcw.low_disk(100 * GB, 1 * GB, 0, None))      # 기준 끔
        self.assertFalse(pcw.low_disk(0, 0, 0, 10))

    def test_norm_drive(self):
        for d in ('C', 'c:', 'C:\\', 'c:/'):
            self.assertEqual(pcw.norm_drive(d), 'C:\\')
        self.assertEqual(pcw.norm_drive('D:\\Mount\\X'), 'D:\\Mount\\X')

    def test_transitions_and_missing(self):
        conf = {'drives': ['C:', 'Z:'], 'disk_free_min_gb': 10, 'disk_free_min_pct': 10}
        free = {'v': 50 * GB}

        def usage(d):
            if d == 'Z:\\':
                raise FileNotFoundError(2, '지정된 경로를 찾을 수 없습니다')
            return 100 * GB, 100 * GB - free['v'], free['v']
        st, items, alerts = pcw.evaluate(conf, {}, usage, T0)
        self.assertEqual(alerts, [])
        self.assertEqual([i['ok'] for i in items], [True, None])
        self.assertIn('찾을 수 없음', items[1]['text'])
        self.assertIn('50.0 GB', items[0]['text'])
        free['v'] = 5 * GB
        st, items, alerts = pcw.evaluate(conf, st, usage, T0 + 60)
        self.assertEqual(len(alerts), 1)
        self.assertIn('부족', alerts[0][0])
        st, items, alerts = pcw.evaluate(conf, st, usage, T0 + 120)
        self.assertEqual(alerts, [])
        self.assertEqual(st['drives']['C:\\']['since'], T0 + 60)
        free['v'] = 40 * GB
        st, items, alerts = pcw.evaluate(conf, st, usage, T0 + 180)
        self.assertEqual(len(alerts), 1)
        self.assertIn('회복', alerts[0][0])


# ---------------------------------------------------------------- 백업

class BackupLogic(unittest.TestCase):
    def test_robocopy_ok(self):
        for c in range(8):
            self.assertTrue(bak.robocopy_ok(c))
        for c in (8, 9, 16, -1, None):
            self.assertFalse(bak.robocopy_ok(c))

    def test_prune_plan(self):
        names = ['2026-10-01_1230', '2026-10-03_1230', '2026-10-02_1230', 'notes', '2026-10-01_1230_실패',
                 '2026-1-01_1230', '2026-10-04_1230']
        self.assertEqual(bak.prune_plan(names, 2), ['2026-10-01_1230', '2026-10-02_1230'])
        self.assertEqual(bak.prune_plan(names, 10), [])
        self.assertEqual(bak.prune_plan(names, 0), [])
        self.assertEqual(bak.prune_plan(names, None), [])
        self.assertEqual(bak.prune_plan(['2026-10-05_0000', '2026-10-04_0000'], 1, current='2026-10-04_0000'), [])

    def test_args(self):
        a = bak.robocopy_args('C:\\src', 'D:\\b\\2026-10-07_1230', ['*.tmp', ''], dry_run=True)
        self.assertEqual(a[:3], ['robocopy', 'C:\\src', 'D:\\b\\2026-10-07_1230'])
        self.assertEqual(a[a.index('/XF') + 1:], ['*.tmp', '/L'])
        self.assertNotIn('/XF', bak.robocopy_args('C:\\s', 'D:\\d'))

    def test_truthy(self):
        self.assertTrue(bak.truthy('true') and bak.truthy(True) and bak.truthy('1'))
        self.assertFalse(bak.truthy('') or bak.truthy(False) or bak.truthy('false'))


class BackupFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, 'src')
        self.dest = os.path.join(self.tmp, 'dest')
        os.makedirs(self.src)
        with open(os.path.join(self.src, 'a.txt'), 'w') as f:
            f.write('x')
        os.makedirs(self.dest)
        for n in ('2026-10-01_1230', '2026-10-02_1230', '2026-10-03_1230', '내 파일들', '2026-10-01_1230_실패'):
            os.makedirs(os.path.join(self.dest, n))
        open(os.path.join(self.dest, '2026-09-30_1230'), 'w').close()      # 날짜 이름의 '파일'은 건드리지 않는다
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def runner(self, code):
        def fake(args):
            self.calls.append(args)
            if '/L' not in args:
                shutil.copytree(args[1], args[2], dirs_exist_ok=True)
            return code, '------\n   총계   복사함\n파일 :  1  1\n------\n'
        return fake

    def item(self, **kw):
        return dict({'name': 't', 'source': self.src, 'dest': self.dest, 'keep': 2}, **kw)

    def test_success_and_prune(self):
        now = datetime.datetime(2026, 10, 7, 12, 30)
        r = bak.backup_one(self.item(), now, runner=self.runner(1))
        self.assertTrue(r['ok'], r['text'])
        self.assertTrue(os.path.isfile(os.path.join(self.dest, '2026-10-07_1230', 'a.txt')))
        self.assertEqual(sorted(r['pruned']), ['2026-10-01_1230', '2026-10-02_1230'])
        left = sorted(os.listdir(self.dest))
        self.assertEqual(left, ['2026-09-30_1230', '2026-10-01_1230_실패', '2026-10-03_1230', '2026-10-07_1230', '내 파일들'])
        self.assertIn('총계', r['text'])

    def test_failure_keeps_everything(self):
        now = datetime.datetime(2026, 10, 7, 12, 30)
        r = bak.backup_one(self.item(), now, runner=self.runner(8))
        self.assertFalse(r['ok'])
        self.assertIn('코드 8', r['text'])
        names = os.listdir(self.dest)
        self.assertIn('2026-10-07_1230_실패', names)
        self.assertIn('2026-10-01_1230', names)              # 실패하면 정리하지 않는다

    def test_dry_run(self):
        now = datetime.datetime(2026, 10, 7, 12, 30)
        before = sorted(os.listdir(self.dest))
        r = bak.backup_one(self.item(), now, dry_run=True, runner=self.runner(0))
        self.assertTrue(r['ok'])
        self.assertIn('/L', self.calls[0])
        self.assertEqual(sorted(os.listdir(self.dest)), before)

    def test_refuse(self):
        now = datetime.datetime(2026, 10, 7, 12, 30)
        r = bak.backup_one(self.item(dest=os.path.join(self.src, 'bk')), now, runner=self.runner(0))
        self.assertFalse(r['ok'])
        self.assertIn('원본(source) 안', r['text'])
        r = bak.backup_one(self.item(source=os.path.join(self.dest, '내 파일들'), dest=self.dest), now,
                           runner=self.runner(0))
        self.assertFalse(r['ok'])
        r = bak.backup_one(self.item(source=os.path.join(self.tmp, 'nope')), now, runner=self.runner(0))
        self.assertFalse(r['ok'])
        self.assertIn('없습니다', r['text'])
        self.assertEqual(self.calls, [])

    def test_inside(self):
        self.assertTrue(bak.inside(os.path.join(self.src, 'x'), self.src))
        self.assertFalse(bak.inside(self.src + '2', self.src))   # 이름 앞부분만 같은 형제 폴더


if __name__ == '__main__':
    unittest.main()
