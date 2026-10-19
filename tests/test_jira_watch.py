# -*- coding: utf-8 -*-
"""Jira 새 이슈 감시(jira-watch.py)와 게이트웨이의 확인 흐름 회귀 테스트.

    python -X utf8 -m unittest tests.test_jira_watch -v

Jira 는 가짜 응답(fetch 바꿔 끼우기), 메일은 가짜 IMAP 으로 돈다 — 네트워크·실제 메일·허브 없음.
"""
import base64
import email
import email.message
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')
sys.path.insert(0, HUB)
sys.path.insert(0, ROOT)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


jw = _load('jira_watch', os.path.join(ROOT, 'jira-watch.py'))
mg = _load('mail_gateway_for_jira', os.path.join(ROOT, 'mail-gateway.py'))
svc = _load('svc_jira_watch', os.path.join(HUB, 'macros', 'svc_jira_watch.py'))
import setup  # noqa: E402

mg.LOG_PATH = os.path.join(tempfile.gettempdir(), 'mail-gateway-jira-test.log')


def cloud_issue(key, summary, created, desc='설명'):
    """Jira Cloud v3 모양 — 설명이 ADF(JSON 문서)."""
    return {'key': key, 'fields': {
        'summary': summary, 'created': created,
        'description': {'type': 'doc', 'version': 1, 'content': [
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': desc}]}]},
        'status': {'name': 'To Do'}, 'issuetype': {'name': 'Task'}, 'priority': {'name': 'Medium'},
        'reporter': {'displayName': '보고자'}}}


def server_issue(key, summary, created, desc='설명'):
    """Server/Data Center v2 모양 — 설명이 문자열."""
    return {'key': key, 'fields': {'summary': summary, 'created': created, 'description': desc,
                                   'status': {'name': 'Open'}, 'issuetype': {'name': 'Bug'}}}


class FakeJira:
    def __init__(self, issues):
        self.issues = list(issues)
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        return {'issues': list(self.issues), 'isLast': True}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.jobs = os.path.join(self.tmp, 'jobs')
        self.work = os.path.join(self.tmp, 'work')
        os.makedirs(self.work)
        names = ('JOBS', 'DATA', 'SEEN_PATH', 'LOG_PATH', 'NOTIFY_PATH', 'STATE_PATH', 'status', 'notify')
        self._saved = {k: getattr(jw, k) for k in names}
        jw.JOBS = self.jobs
        jw.DATA = os.path.join(self.tmp, 'data')
        jw.SEEN_PATH = os.path.join(jw.DATA, 'seen.json')
        jw.LOG_PATH = os.path.join(jw.DATA, 'jira-watch.log')
        jw.NOTIFY_PATH = os.path.join(jw.DATA, 'notify.jsonl')
        jw.STATE_PATH = os.path.join(jw.DATA, 'state.json')
        self.statuses, self.notes = [], []
        jw.status = lambda ok, text, note='': self.statuses.append((ok, text))
        jw.notify = lambda title, text, level='Info': self.notes.append((title, text, level))
        self.cfg = jw.load_cfg({
            'jira': {'enabled': True, 'base_url': 'https://your-team.atlassian.net/', 'auth': 'cloud',
                     'email': 'me@example.com', 'token_enc': 'x', 'ask_ttl_min': 1440, 'max_per_cycle': 3,
                     'workdir': self.work},
            'dispatch': {'enabled': True, 'write_tags': ['#cw', 'cw'], 'write_tools': ['Read', 'Edit', 'Bash']},
        })

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(jw, k, v)

    def jobs_now(self):
        if not os.path.isdir(self.jobs):
            return []
        return [jw.read_json(os.path.join(self.jobs, f)) for f in sorted(os.listdir(self.jobs)) if f.endswith('.json')]


class Config(Base):
    def test_defaults_are_off_and_inherit_dispatch(self):
        cfg = jw.load_cfg({})
        self.assertFalse(cfg['enabled'])
        self.assertFalse(cfg['dispatch_enabled'])
        self.assertEqual(cfg['jql'], 'assignee = currentUser() AND resolution = Unresolved AND created >= -3d')
        self.assertEqual((cfg['ask_ttl_min'], cfg['max_per_cycle']), (1440, 3))
        self.assertEqual(cfg['write_tag'], '#cw')
        self.assertIn('Bash(curl:*)', cfg['disallowed_tools'])
        self.assertFalse(jw.ready(cfg)[0])
        # 작업 폴더·도구는 디스패치에서 물려받는다
        self.assertEqual(self.cfg['tools'], ['Read', 'Edit', 'Bash'])
        self.assertEqual(self.cfg['base_url'], 'https://your-team.atlassian.net')

    def test_example_config_has_jira_section_off(self):
        with open(os.path.join(ROOT, 'config.example.json'), encoding='utf-8-sig') as f:
            j = json.load(f)['jira']
        self.assertFalse(j['enabled'])
        self.assertEqual(j['token_enc'], '')
        for k in ('base_url', 'auth', 'email', 'jql', 'poll_interval_sec', 'ask_ttl_min', 'max_per_cycle', 'workdir', 'prompt'):
            self.assertIn(k, j)

    def test_ready_needs_email_only_for_cloud(self):
        base = {'jira': {'base_url': 'https://jira.example.com', 'token_enc': 'x'}}
        self.assertFalse(jw.ready(jw.load_cfg(base))[0])                     # cloud 기본 — email 없음
        base['jira']['auth'] = 'server'
        self.assertTrue(jw.ready(jw.load_cfg(base))[0])


class Search(Base):
    def test_cloud_basic_auth_and_new_endpoint(self):
        fake = FakeJira([cloud_issue('AB-2', '둘째', '2026-10-12T10:00:00.000+0900'),
                         cloud_issue('AB-1', '첫째', '2026-10-11T10:00:00.000+0900', desc='본문 첫 줄')])
        got = jw.search(self.cfg, 'tok', fetch=fake)
        url, headers = fake.calls[0]
        self.assertIn('/rest/api/3/search/jql?', url)
        self.assertIn('ORDER+BY+created+DESC', url)
        self.assertEqual(headers['Authorization'], 'Basic ' + base64.b64encode(b'me@example.com:tok').decode())
        self.assertEqual([i['key'] for i in got], ['AB-1', 'AB-2'])          # 오래된 것 먼저
        self.assertEqual(got[0]['description'], '본문 첫 줄')                  # ADF → 글자
        self.assertEqual(got[0]['url'], 'https://your-team.atlassian.net/browse/AB-1')

    def test_server_bearer_and_v2_endpoint(self):
        cfg = jw.load_cfg({'jira': {'base_url': 'https://jira.example.com', 'auth': 'server', 'token_enc': 'x',
                                    'jql': 'project = X ORDER BY key ASC'}})
        fake = FakeJira([server_issue('X-9', '버그', '2026-10-12T09:00:00.000+0900', desc='문자열 설명')])
        got = jw.search(cfg, 'pat', fetch=fake)
        url, headers = fake.calls[0]
        self.assertIn('/rest/api/2/search?', url)
        self.assertNotIn('created+DESC', url)                                # 사용자가 정한 ORDER BY 를 지킨다
        self.assertEqual(headers['Authorization'], 'Bearer pat')
        self.assertEqual(got[0]['description'], '문자열 설명')


class PollAndSeed(Base):
    def test_first_run_seeds_without_asking(self):
        fake = FakeJira([cloud_issue('AB-1', '옛 이슈', '2026-10-10T10:00:00.000+0900'),
                         cloud_issue('AB-2', '옛 이슈2', '2026-10-11T10:00:00.000+0900')])
        out = jw.poll(self.cfg, 'tok', fetch=fake)
        self.assertEqual((out['seeded'], out['asked']), (2, []))
        self.assertEqual(self.jobs_now(), [])                               # 과거 이슈가 무더기로 뜨지 않는다
        # 다음 차례에 새 이슈 하나만 묻는다
        fake.issues.append(cloud_issue('AB-3', '새 이슈', '2026-10-12T10:00:00.000+0900'))
        out = jw.poll(self.cfg, 'tok', fetch=fake)
        self.assertEqual(out['asked'], ['AB-3'])
        self.assertEqual([j['jira_key'] for j in self.jobs_now()], ['AB-3'])
        # 같은 이슈를 두 번 묻지 않는다
        self.assertEqual(jw.poll(self.cfg, 'tok', fetch=fake)['asked'], [])
        self.assertEqual(len(self.jobs_now()), 1)
        self.assertTrue(self.notes)

    def test_max_per_cycle_and_rest_next_time(self):
        fake = FakeJira([])
        jw.poll(self.cfg, 'tok', fetch=fake)                                # seed(빈 목록)
        fake.issues = [cloud_issue('AB-%d' % n, 's%d' % n, '2026-10-12T10:0%d:00.000+0900' % n) for n in range(1, 6)]
        out = jw.poll(self.cfg, 'tok', fetch=fake)
        self.assertEqual((out['asked'], out['pending']), (['AB-1', 'AB-2', 'AB-3'], 2))
        self.assertEqual(jw.poll(self.cfg, 'tok', fetch=fake)['asked'], ['AB-4', 'AB-5'])

    def test_changing_jql_reseeds(self):
        fake = FakeJira([cloud_issue('AB-1', 'a', '2026-10-12T10:00:00.000+0900')])
        jw.poll(self.cfg, 'tok', fetch=fake)
        fake.issues.append(cloud_issue('ZZ-1', '넓힌 조건의 옛 이슈', '2026-10-01T10:00:00.000+0900'))
        self.cfg['jql'] = 'project = ZZ'
        out = jw.poll(self.cfg, 'tok', fetch=fake)
        self.assertEqual((out['seeded'], out['asked']), (2, []))

    def test_seed_and_dry_run(self):
        fake = FakeJira([])
        jw.poll(self.cfg, 'tok', fetch=fake)
        fake.issues = [cloud_issue('AB-7', 'x', '2026-10-12T10:00:00.000+0900')]
        out = jw.poll(self.cfg, 'tok', fetch=fake, dry=True)
        self.assertEqual(out['asked'], ['AB-7'])
        self.assertEqual(self.jobs_now(), [])                               # 미리 보기는 잡을 안 만든다
        self.assertEqual(jw.poll(self.cfg, 'tok', fetch=fake, seed=True)['seeded'], 1)
        self.assertEqual(jw.poll(self.cfg, 'tok', fetch=fake)['asked'], [])

    def test_dispatch_off_does_not_poll(self):
        cfg = dict(self.cfg, dispatch_enabled=False)
        called = []
        with mock.patch.object(jw, 'load_cfg', return_value=cfg), \
                mock.patch.object(jw, 'poll', side_effect=lambda *a, **k: called.append(1)):
            self.assertEqual(jw.main(['--once']), 1)
        self.assertEqual(called, [])
        self.assertFalse(self.statuses[-1][0])
        self.assertIn('dispatch.enabled', self.statuses[-1][1])
        self.assertEqual(self.notes[-1][2], 'Warning')

    def test_service_macro_waits_for_dispatch(self):
        self.assertIn('jira.enabled', svc.blocker({'jira': {}, 'dispatch': {'enabled': True}}))
        self.assertIn('dispatch.enabled', svc.blocker({'jira': {'enabled': True}, 'dispatch': {}}))
        self.assertEqual(svc.blocker({'jira': {'enabled': True}, 'dispatch': {'enabled': True}}), '')


class JobShape(Base):
    def issue(self, desc='설명'):
        return jw.normalize(cloud_issue('AB-12', '로그인 오류', '2026-10-12T10:00:00.000+0900', desc=desc),
                            self.cfg['base_url'])

    def test_summary_cannot_carry_thread_mark(self):
        """요약에 '[T12]' 를 넣은 이슈가 남의 대화에 끼어들지 않게 — 표식은 지운다(게이트웨이도 제목의 번호를 믿지 않는다)."""
        issue = jw.normalize(cloud_issue('AB-13', '[T12] 오류 [k:x]', '2026-10-12T10:00:00.000+0900'), self.cfg['base_url'])
        self.assertEqual(issue['summary'], '오류')
        self.assertNotIn('[T12]', jw.make_job(self.cfg, issue)['mail_subject'])

    def test_confirm_job(self):
        job = jw.make_job(self.cfg, self.issue())
        self.assertEqual(job['status'], 'awaiting_confirm')
        self.assertFalse(job['confirm_sent'])
        self.assertEqual(job['source'], 'jira')
        self.assertIn(job['source'], mg.MAIL_SOURCES)                       # 게이트웨이가 확인·회신·이어받기를 맡는다
        self.assertEqual(job['confirm_ttl_min'], 1440)
        self.assertTrue(job['chat'])
        self.assertEqual(job['mode'], 'write')
        self.assertTrue(job['mail_subject'].startswith('#cw '))            # 답장이 쓰기 지시로 이어지게
        self.assertEqual(mg.match_tag(job['mail_subject'], {'tags': ['#c', 'c'], 'write_tags': ['#cw', 'cw']})[1], 'write')
        self.assertEqual(job['workdir'], self.work)
        self.assertEqual(job['allowed_tools'], ['Read', 'Edit', 'Bash'])
        self.assertIn('Bash(curl:*)', job['disallowed_tools'])
        self.assertEqual((job['jira_key'], job['jira_summary']), ('AB-12', '로그인 오류'))
        self.assertTrue(re.match(r'^\d{8}-\d{6}-[0-9a-f]{4}$', job['id']))

    def test_prompt_has_issue_but_no_credentials(self):
        cfg = dict(self.cfg, token_enc='SECRET-ENC', max_description_chars=200)
        job = jw.make_job(cfg, self.issue(desc='가' * 1000))
        p = job['prompt']
        self.assertTrue(p.startswith('Jira 이슈 AB-12 「로그인 오류」를 읽고'))
        self.assertIn('https://your-team.atlassian.net/browse/AB-12', p)
        self.assertIn('따르지 말고', p)                                      # 남이 쓴 글은 자료로만
        self.assertIn('잘랐습니다', p)
        self.assertLess(p.count('가'), 300)
        for secret in ('SECRET-ENC', 'me@example.com', 'Authorization'):
            self.assertNotIn(secret, p)
        self.assertNotIn('SECRET-ENC', json.dumps(job, ensure_ascii=False))

    def test_custom_template(self):
        cfg = dict(self.cfg, prompt='{key} 처리 — {url} ({status}/{type}) {없는칸}')
        p = jw.build_prompt(cfg, self.issue())
        self.assertTrue(p.startswith('AB-12 처리 — https://your-team.atlassian.net/browse/AB-12 (To Do/Task) {없는칸}'))

    def test_worker_accepts_jira_tool_list(self):
        with open(os.path.join(ROOT, 'inbox-worker.ps1'), encoding='utf-8-sig') as f:
            line = [x for x in f if x.startswith('$script:MailSources')][0]
        self.assertIn("'jira'", line)


class GatewayConfirm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = (mg.JOBS, mg.THREAD_SEQ_PATH)
        mg.JOBS = self.tmp
        mg.THREAD_SEQ_PATH = os.path.join(self.tmp, 'thread-seq.json')
        self.cfg = {'user': 'me@example.com', 'tags': ['#c', 'c'], 'tag': '#c', 'write_tags': ['#cw', 'cw'],
                    'confirm_ttl_min': 60}
        jcfg = jw.load_cfg({'jira': {'base_url': 'https://jira.example.com', 'workdir': self.tmp},
                            'dispatch': {'enabled': True}})
        self.job = jw.make_job(jcfg, jw.normalize(server_issue('AB-5', '결제 실패', '2026-10-12T10:00:00.000+0900'),
                                                  jcfg['base_url']))

    def tearDown(self):
        mg.JOBS, mg.THREAD_SEQ_PATH = self._old

    def test_ticket_question(self):
        mg.ensure_thread(self.job, self.cfg)
        msg, mid = mg.build_confirm_message(self.cfg, self.job)
        text = msg.get_body(('plain',)).get_content()
        self.assertIn('새 Jira 이슈', text)
        self.assertIn('AB-5 결제 실패', text)
        self.assertIn('https://jira.example.com/browse/AB-5', text)
        self.assertIn('지금 처리', text)
        self.assertIn('내가 직접', text)
        self.assertIn('24시간 안에 답이 없으면 건너뜁니다', text)
        self.assertTrue(msg['Subject'].startswith('Re: #cw [T1] [Jira] AB-5'))
        self.assertEqual(msg['X-Dispatch-Kind'], 'confirm')
        ask = json.loads(base64.b64decode(msg['X-Dispatch-Ask']).decode('utf-8'))
        self.assertEqual(ask['options'], ['지금 처리', '내가 직접'])

    def test_answers(self):
        for t in ('1', '지금 처리', '처리'):
            self.assertEqual(mg.parse_confirm_answer(t), 'yes', t)
        for t in ('2', '내가 직접', '직접', '건너뜀'):
            self.assertEqual(mg.parse_confirm_answer(t), 'no', t)

    def test_ttl_per_job(self):
        self.assertEqual(mg.confirm_ttl(self.cfg, self.job), 1440)
        self.assertEqual(mg.confirm_ttl(self.cfg, {}), 60)
        self.assertEqual(mg.confirm_ttl(self.cfg, {'confirm_ttl_min': 'x'}), 60)
        self.assertEqual((mg.ttl_text(60), mg.ttl_text(1440), mg.ttl_text(90)), ('1시간', '24시간', '90분'))
        two_h = (datetime.now() - timedelta(minutes=120)).strftime('%Y-%m-%d %H:%M:%S')
        day = (datetime.now() - timedelta(minutes=1441)).strftime('%Y-%m-%d %H:%M:%S')
        jira_2h = dict(self.job, id='a', created_at=two_h)
        jira_day = dict(self.job, id='b', created_at=day)
        mail_2h = {'id': 'c', 'status': 'awaiting_confirm', 'created_at': two_h, 'source': 'mail'}
        for j in (jira_2h, jira_day, mail_2h):
            mg.write_json(os.path.join(self.tmp, j['id'] + '.json'), j)
        mg.expire_confirms(self.cfg)
        st = {k: mg.read_json(os.path.join(self.tmp, k + '.json')) for k in 'abc'}
        self.assertEqual(st['a']['status'], 'awaiting_confirm')               # 하루 안 — 아직 기다린다
        self.assertEqual(st['b']['status'], 'canceled')
        self.assertIn('24시간', st['b']['error'])
        self.assertEqual(st['c']['status'], 'canceled')                       # 메일 쓰기 지시는 그대로 60분


class FakeImap:
    def __init__(self, mails, appended):
        self.mails, self.appended = mails, appended

    def select(self, box):
        return 'OK', [b'']

    def uid(self, cmd, *args):
        if cmd == 'SEARCH':
            return 'OK', [' '.join(self.mails).encode()]
        if cmd == 'FETCH':
            raw = self.mails[args[0]]
            if 'HEADER' in args[1]:
                raw = raw.split(b'\r\n\r\n', 1)[0] + b'\r\n\r\n'
            return 'OK', [(b'1', raw)]
        return 'OK', [b'']

    def append(self, box, flags, date, data):
        self.appended.append(data)

    def close(self):
        pass

    def logout(self):
        pass


class EndToEnd(Base):
    """감시가 남긴 잡 → 게이트웨이 확인 메일 → 대화 앱의 답 → queued (가짜 Jira·가짜 IMAP)."""

    def setUp(self):
        super().setUp()
        os.makedirs(self.jobs)
        names = ('JOBS', 'SEEN_PATH', 'LOG_PATH', 'NOTIFY_PATH', 'THREAD_SEQ_PATH', 'imap_connect', 'resolve_folders',
                 'notify', 'EARLY_STOP_PATH', 'ATTACH', 'REJECTED_PATH')
        self._mg = {k: getattr(mg, k) for k in names}
        mg.JOBS = self.jobs
        mg.REJECTED_PATH = os.path.join(self.tmp, 'mail-rejected.json')
        mg.EARLY_STOP_PATH = os.path.join(self.tmp, 'early-stops.json')
        mg.ATTACH = os.path.join(self.tmp, 'attachments')
        mg.THREAD_SEQ_PATH = os.path.join(self.tmp, 'thread-seq.json')
        mg.SEEN_PATH = os.path.join(self.tmp, 'mail-seen.json')
        mg.LOG_PATH = os.path.join(self.tmp, 'gw.log')
        mg.NOTIFY_PATH = os.path.join(self.tmp, 'gw-notify.jsonl')
        mg.notify = lambda *a, **k: None
        self.mails, self.appended = {}, []
        mg.imap_connect = lambda cfg, pw: FakeImap(self.mails, self.appended)
        mg.resolve_folders = lambda m, folders: ['INBOX']
        self.gw = {'user': 'me@example.com', 'allowed_senders': ['me@example.com'], 'tags': ['#c', 'c'], 'tag': '#c',
                   'write_tags': ['#cw', 'cw'], 'write_tools': ['Read', 'Bash'], 'folders': ['INBOX'],
                   'default_workdir': self.work, 'workdir_keys': {}, 'max_prompt_chars': 4000, 'lookback_days': 2,
                   'max_per_cycle': 5, 'reply_mode': 'append', 'confirm_write': True, 'confirm_ttl_min': 60,
                   'require_auth_results': False}
        fake = FakeJira([])
        jw.poll(self.cfg, 'tok', fetch=fake)                                  # seed
        fake.issues = [cloud_issue('AB-9', '새 기능', '2026-10-12T10:00:00.000+0900')]
        jw.poll(self.cfg, 'tok', fetch=fake)

    def tearDown(self):
        for k, v in self._mg.items():
            setattr(mg, k, v)
        super().tearDown()

    def reply(self, uid, body):
        confirm = email.message_from_bytes(self.appended[-1])
        m = email.message.EmailMessage()
        m['Subject'] = 'Re: ' + confirm['Subject'].replace('Re: ', '', 1)
        m['From'], m['To'], m['Message-ID'] = 'me@example.com', 'me@example.com', '<r%s@x>' % uid
        m['In-Reply-To'] = confirm['Message-ID']
        m.set_content(body)
        raw = m.as_bytes()
        self.mails[uid] = raw if b'\r\n' in raw else raw.replace(b'\n', b'\r\n')

    def test_now_then_queued(self):
        self.assertEqual(mg.send_replies(self.gw, 'pw'), 1)                   # 확인 메일(대화 앱 질문)이 나간다
        (job,) = self.jobs_now()
        self.assertTrue(job['confirm_sent'])
        confirm = email.message_from_bytes(self.appended[-1])
        self.assertIn('AB-9', confirm['Subject'])
        self.reply('1', '1')
        mg.poll_once(self.gw, 'pw')
        jobs = self.jobs_now()
        self.assertEqual(len(jobs), 1)                                        # 답이 새 지시로 오인되지 않았다
        self.assertEqual(jobs[0]['status'], 'queued')

    def test_do_it_myself_cancels(self):
        mg.send_replies(self.gw, 'pw')
        self.reply('1', '내가 직접')
        mg.poll_once(self.gw, 'pw')
        self.assertEqual(self.jobs_now()[0]['status'], 'canceled')


class SetupJira(unittest.TestCase):
    def test_cloud_token_is_encrypted(self):
        cfg = {'mail': {'user': 'me@corp.test'}, 'dispatch': {'enabled': True}}
        answers = iter(['https://your-team.atlassian.net/', '', '', '', 'y'])   # 주소 · 방식(기본 cloud) · 이메일(기본) · 폴더 · 켜기
        with mock.patch('builtins.input', lambda prompt='': next(answers)), mock.patch('builtins.print'):
            j = setup.step_jira(cfg, protect=lambda t: 'ENC(%s)' % t, secret=lambda p: 'raw-token')
        self.assertEqual(j['base_url'], 'https://your-team.atlassian.net')
        self.assertEqual(j['auth'], 'cloud')
        self.assertEqual(j['email'], 'me@corp.test')         # 메일 주소를 기본값으로
        self.assertEqual(j['token_enc'], 'ENC(raw-token)')
        self.assertTrue(j['enabled'])
        self.assertNotIn('raw-token', json.dumps({k: v for k, v in j.items() if k != 'token_enc'}))
        self.assertIn('암호화돼 있음', setup.masked(cfg)['jira']['token_enc'])

    def test_server_has_no_email(self):
        cfg = {}
        answers = iter(['https://jira.example.com', '', '', 'n'])            # 방식 기본값이 server(atlassian.net 아님)
        with mock.patch('builtins.input', lambda prompt='': next(answers)), mock.patch('builtins.print'):
            j = setup.step_jira(cfg, protect=lambda t: 'ENC(%s)' % t, secret=lambda p: 'pat')
        self.assertEqual(j['auth'], 'server')
        self.assertNotIn('email', j)
        self.assertFalse(j['enabled'])


if __name__ == '__main__':
    unittest.main()
