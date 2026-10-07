# -*- coding: utf-8 -*-
"""정기 예약 메일(job_scheduled_mail) · 폴더 정리(job_tidy) 매크로의 회귀 테스트.

    python -X utf8 -m unittest tests.test_features_a -v

허브를 띄우지 않고 매크로 모듈의 함수만 부른다. 메일은 kit.send_mail 을 바꿔치기해 실제로 보내지 않고,
파일은 임시 폴더에서만 옮긴다. 표준 라이브러리만으로 돈다.
"""
import datetime
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
import kit  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HUB, 'macros', name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = load('job_scheduled_mail')
tidy = load('job_tidy')

DT = datetime.datetime
MON_0905 = DT(2026, 10, 5, 9, 5)              # 월요일 09:05


class ScheduledMail(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._orig = kit.send_mail
        kit.send_mail = lambda to, subject, body, cc=None, bcc=None, attachments=None, **kw: \
            self.sent.append({'to': to, 'subject': subject, 'body': body, 'cc': cc, 'bcc': bcc,
                              'attachments': attachments})
        self.tmp = tempfile.mkdtemp()
        self.saves = []

    def tearDown(self):
        kit.send_mail = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, state):
        self.saves.append({k: dict(v) for k, v in state.items()})

    def item(self, **kw):
        it = {'name': '주간 보고', 'at': '09:00', 'days': 'mon', 'to': ['team@example.com'],
              'subject': '보고 {date}', 'body': '{prev_month} 실적', 'attachments': []}
        it.update(kw)
        return it

    def test_pick_due(self):
        items = [self.item(), self.item(name='꺼짐', enabled=False), self.item(name='화요일', days='tue'),
                 self.item(name='아직', at='10:00')]
        self.assertEqual([k for k, _ in sm.pick_due(items, {}, MON_0905)], ['주간 보고'])

    def test_sends_once_and_renders(self):
        items, state = [self.item()], {}
        self.assertEqual(sm.send_due(items, state, MON_0905, self.save, log=lambda *_: None), [])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['subject'], '보고 2026-10-05')
        self.assertEqual(self.sent[0]['body'], '2026-09 실적')
        self.assertTrue(self.saves and self.saves[-1]['주간 보고']['last_ok'])
        # 1분 뒤에 다시 돌아도 또 보내지 않는다
        sm.send_due(items, state, MON_0905 + datetime.timedelta(minutes=1), self.save, log=lambda *_: None)
        self.assertEqual(len(self.sent), 1)
        # 다음 주 월요일엔 다시 보낸다
        sm.send_due(items, state, MON_0905 + datetime.timedelta(days=7), self.save, log=lambda *_: None)
        self.assertEqual(len(self.sent), 2)

    def test_state_saved_right_after_each_send(self):
        items = [self.item(name='A'), self.item(name='B')]
        sm.send_due(items, {}, MON_0905, self.save, log=lambda *_: None)
        self.assertEqual(len(self.saves), 2)
        self.assertIn('A', self.saves[0])
        self.assertNotIn('B', self.saves[0])

    def test_missing_attachment_fails_only_that_item(self):
        ok_file = os.path.join(self.tmp, 'r-2026-09.txt')
        open(ok_file, 'w').close()
        items = [self.item(name='없음', attachments=[os.path.join(self.tmp, 'nope.xlsx')]),
                 self.item(name='있음', attachments=[os.path.join(self.tmp, 'r-{prev_month}.txt')])]
        state = {}
        errs = sm.send_due(items, state, MON_0905, self.save, log=lambda *_: None)
        self.assertEqual(len(errs), 1)
        self.assertIn('없음', errs[0])
        self.assertEqual([m['attachments'] for m in self.sent], [[ok_file]])
        self.assertIsNone(state['없음'].get('last_run'))
        self.assertFalse(state['없음']['last_ok'])
        # 실패한 항목은 RETRY_MIN 분 동안 쉬었다가 다시 시도한다
        self.assertEqual(sm.pick_due(items, state, MON_0905 + datetime.timedelta(minutes=3)), [])
        later = sm.pick_due(items, state, MON_0905 + datetime.timedelta(minutes=sm.RETRY_MIN + 1))
        self.assertEqual([k for k, _ in later], ['없음'])

    def test_send_error_recorded(self):
        def boom(*a, **k):
            raise OSError('smtp down')
        kit.send_mail = boom
        state = {}
        errs = sm.send_due([self.item()], state, MON_0905, self.save, log=lambda *_: None)
        self.assertEqual(len(errs), 1)
        self.assertIn('smtp down', state['주간 보고']['last_err'])
        rows = sm.status_items([self.item()], state)
        self.assertFalse(rows[0]['ok'])

    def test_no_recipient(self):
        errs = sm.send_due([self.item(to=[])], {}, MON_0905, self.save, log=lambda *_: None)
        self.assertEqual(len(errs), 1)
        self.assertEqual(self.sent, [])


class TidyRefuse(unittest.TestCase):
    ENV = {'SystemRoot': r'C:\Windows', 'ProgramFiles': r'C:\Program Files',
           'ProgramFiles(x86)': r'C:\Program Files (x86)', 'ProgramData': r'C:\ProgramData',
           'USERPROFILE': r'C:\Users\kim'}

    def test_refuses(self):
        for bad in ('C:\\', 'D:', 'c:/', r'C:\Windows', r'C:\windows\System32', r'C:\Program Files\App',
                    r'C:\Program Files (x86)', r'C:\Users\kim', 'C:\\Users\\kim\\', r'\\server\share'):
            with self.subTest(bad=bad):
                self.assertTrue(tidy.refuse_reason(bad, self.ENV))

    def test_allows(self):
        for good in (r'C:\Users\kim\Downloads', r'D:\Work\inbox', r'C:\Windows2', r'C:\Users\kimchi'):
            with self.subTest(good=good):
                self.assertEqual(tidy.refuse_reason(good, self.ENV), '')

    def test_tidy_item_raises_on_refused(self):
        with self.assertRaises(ValueError):
            tidy.tidy_item({'folder': 'C:\\', 'older_than_days': 1}, DT.now(), env=self.ENV)


class TidyMoves(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.folder = os.path.join(self.root, 'Downloads')
        self.archive = os.path.join(self.folder, '_보관')
        os.makedirs(os.path.join(self.folder, 'sub'))
        self.now = DT(2026, 10, 7, 12, 0)
        self.old = DT(2026, 8, 15, 10, 0).timestamp()
        self.new = DT(2026, 10, 1, 10, 0).timestamp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def mk(self, rel, mtime):
        p = os.path.join(self.folder, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(rel)
        os.utime(p, (mtime, mtime))
        return p

    def test_plan(self):
        self.mk('옛날.txt', self.old)
        self.mk('새것.txt', self.new)
        self.mk('desktop.ini', self.old)
        self.mk('~$잠금.docx', self.old)
        self.mk(os.path.join('sub', '안쪽.txt'), self.old)
        os.utime(os.path.join(self.folder, 'sub'), (self.old, self.old))
        plan = tidy.plan_moves(self.folder, 30, self.archive, self.now)
        self.assertEqual(plan, [(os.path.join(self.folder, '옛날.txt'),
                                 os.path.join(self.archive, '2026-08', '옛날.txt'))])

    def test_name_clash(self):
        os.makedirs(os.path.join(self.archive, '2026-08'))
        open(os.path.join(self.archive, '2026-08', 'a.txt'), 'w').close()
        open(os.path.join(self.archive, '2026-08', 'a (2).txt'), 'w').close()
        self.mk('a.txt', self.old)
        plan = tidy.plan_moves(self.folder, 30, self.archive, self.now)
        self.assertEqual(os.path.basename(plan[0][1]), 'a (3).txt')

    def test_dry_run_moves_nothing(self):
        src = self.mk('옛날.txt', self.old)
        n, errs = tidy.tidy_item({'folder': self.folder, 'older_than_days': 30, 'archive_to': self.archive},
                                 self.now, dry_run=True, log=lambda *_: None)
        self.assertEqual((n, errs), (1, []))
        self.assertTrue(os.path.exists(src))
        self.assertFalse(os.path.exists(self.archive))

    def test_moves_by_mtime_month_and_keeps_new(self):
        self.mk('옛날.txt', self.old)
        self.mk('칠월.txt', DT(2026, 7, 3).timestamp())
        new = self.mk('새것.txt', self.new)
        n, errs = tidy.tidy_item({'folder': self.folder, 'older_than_days': 30, 'archive_to': self.archive},
                                 self.now, log=lambda *_: None)
        self.assertEqual((n, errs), (2, []))
        self.assertTrue(os.path.exists(os.path.join(self.archive, '2026-08', '옛날.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.archive, '2026-07', '칠월.txt')))
        self.assertTrue(os.path.exists(new))
        # 다시 돌려도 보관 폴더 자체나 그 안의 파일은 건드리지 않는다
        n, errs = tidy.tidy_item({'folder': self.folder, 'older_than_days': 30, 'archive_to': self.archive},
                                 self.now, log=lambda *_: None)
        self.assertEqual(n, 0)

    def test_bad_settings(self):
        with self.assertRaises(FileNotFoundError):
            tidy.tidy_item({'folder': os.path.join(self.root, 'none'), 'older_than_days': 1}, self.now)
        with self.assertRaises(ValueError):
            tidy.tidy_item({'folder': self.folder, 'archive_to': self.folder, 'older_than_days': 1}, self.now)
        with self.assertRaises(ValueError):
            tidy.tidy_item({'folder': self.folder, 'older_than_days': 'x'}, self.now)

    def test_flag(self):
        self.assertTrue(tidy.flag('true'))
        self.assertTrue(tidy.flag(True))
        self.assertFalse(tidy.flag('false'))
        self.assertFalse(tidy.flag(None))


class RunEntry(unittest.TestCase):
    """설정이 비었을 때 run(ctx) 는 조용히 끝나고 상태 파일만 남긴다."""

    class Ctx:
        params, trigger = {}, {'kind': 'schedule'}

        def __init__(self):
            self.lines = []

        def log(self, *p):
            self.lines.append(' '.join(map(str, p)))

        def motion(self, *a, **k):
            pass

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._sec, self._data = kit.section, kit.DATA
        kit.section = lambda name, default=None, cfg=None: default
        kit.DATA = self.tmp

    def tearDown(self):
        kit.section, kit.DATA = self._sec, self._data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_sections(self):
        for mod, feat in ((sm, 'scheduled_mail'), (tidy, 'tidy')):
            with self.subTest(feat=feat):
                ctx = self.Ctx()
                mod.run(ctx)
                self.assertIn('설정에 없음', ctx.lines[0])
                self.assertEqual(kit.read_status(feat)['note'], '설정에 없음')


if __name__ == '__main__':
    unittest.main()
