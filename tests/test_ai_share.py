# -*- coding: utf-8 -*-
"""AI 공유 위키(tools/ai-share-agent) — 설정·이슈 출처 어댑터·선택 기능·주간 보고 초안의 회귀 테스트.

    python -X utf8 -m unittest tests.test_ai_share -v

네트워크 없음(가짜 fetch), LLM·메일 없음(가짜 함수), 허브 없음. git 은 임시 폴더에 만든 작은 레포로만 쓴다.
"""
import base64
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HUB = os.path.join(ROOT, 'tools', 'macro-hub')
TOOL = os.path.join(ROOT, 'tools', 'ai-share-agent')
sys.path.insert(0, HUB)
sys.path.insert(0, TOOL)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ag = _load('ai_share_agent', os.path.join(TOOL, 'agent.py'))
tr = ag.trackers
svc = _load('svc_ai_share', os.path.join(HUB, 'macros', 'svc_ai_share.py'))
job = _load('job_weekly_report', os.path.join(HUB, 'macros', 'job_weekly_report.py'))


def qs(url):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}


class Fake:
    """fetch(url, headers) 가짜 — routes 의 (경로 조각, 판정) → 응답. 부른 기록을 남긴다."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        for part, resp in self.routes:
            if part in url:
                return resp(url) if callable(resp) else resp
        raise AssertionError('예상하지 못한 주소: ' + url)


class Base(unittest.TestCase):
    """임시 wiki 로 설정을 바꿔 끼운다 — 실제 config.local.json·data.local 을 건드리지 않는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(ag.configure)
        p = mock.patch.object(ag.kit, 'write_status')
        self.status = p.start()
        self.addCleanup(p.stop)

    def conf(self, ai=None, full=None, fetch=None, token='tok'):
        full = dict(full or {})
        a = dict(ai or {})
        a.setdefault('wiki_dir', os.path.join(self.tmp, 'wiki'))
        full['ai_share'] = a
        ag.configure(ag.load_cfg(full), full, fetch, token)
        return ag


# ---------------------------------------------------------------- 설정

class Config(Base):
    def test_defaults(self):
        cfg = ag.load_cfg({})
        self.assertFalse(cfg['enabled'])
        self.assertEqual(cfg['port'], 8640)
        self.assertEqual(cfg['tracker']['type'], 'none')
        self.assertEqual(cfg['part'], 'main')
        self.assertEqual(cfg['comment_prefixes'], [])
        self.assertEqual(cfg['exclude_types'], [])
        self.assertFalse(cfg['harness']['enabled'])
        self.assertEqual(cfg['weekly_report']['days'], 'fri')

    def test_override_merges_nested_and_ignores_notes(self):
        cfg = ag.load_cfg({'ai_share': {'port': 9000, '_설명': 'x', 'harness': {'enabled': True},
                                        'tracker': {'type': 'github', '_예': 1}}})
        self.assertEqual(cfg['port'], 9000)
        self.assertNotIn('_설명', cfg)
        self.assertTrue(cfg['harness']['enabled'])
        self.assertEqual(cfg['harness']['tasks_dir'], 'docs/tasks')     # 안 적은 값은 기본값 유지
        self.assertEqual(cfg['tracker'], {'type': 'github', 'key_regex': ''})

    def test_default_wiki_under_kit_data(self):
        ag.configure(ag.load_cfg({}), {})
        self.assertEqual(ag.WIKI, Path(ag.kit.DATA) / 'ai_share' / 'wiki')

    def test_example_config_has_section(self):
        with open(os.path.join(ROOT, 'config.example.json'), encoding='utf-8-sig') as f:
            a = json.load(f)['ai_share']
        self.assertFalse(a['enabled'])
        self.assertEqual(a['tracker']['type'], 'none')
        self.assertFalse(a['weekly_report']['enabled'])
        for k in ('_tracker_jira_예', '_tracker_github_예', '_tracker_gitlab_예', '_설명'):
            self.assertIn(k, a)

    def test_bad_branch_regex_does_not_crash(self):
        self.conf({'branch_ticket_re': '(['})
        self.assertIsNone(ag.BRANCH_RE)


# ---------------------------------------------------------------- 키 · 가리기

class Keys(Base):
    def test_none_default_and_custom(self):
        self.assertEqual(tr.make({}).find_keys('fix PROJ-12 and AB-3, not ab-1'), {'PROJ-12', 'AB-3'})
        self.assertEqual(tr.make({'key_regex': r'T\d+'}).find_keys('T12 · PROJ-1'), {'T12'})
        self.assertEqual(tr.make({'key_regex': '(['}).find_keys('PROJ-1'), {'PROJ-1'})   # 잘못된 정규식 → 기본값

    def test_jira_project_keys(self):
        t = tr.make({'type': 'jira', 'jira_project_keys': ['PROJ']}, {'jira': {}})
        self.assertEqual(t.find_keys('PROJ-1 OTHER-2 XPROJ-3'), {'PROJ-1'})
        self.assertEqual(t.key_from_number('77'), 'PROJ-77')
        t2 = tr.make({'type': 'jira'}, {'jira': {}})
        self.assertEqual(t2.find_keys('A1-2 AB-3 B-4'), {'A1-2', 'AB-3'})

    def test_github_keys(self):
        one = tr.make({'type': 'github', 'repos': ['org/app']})
        self.assertEqual(one.find_keys('fix #12, see org/app#3 and other/x#9'), {'org/app#12', 'org/app#3'})
        self.assertEqual(one.display('org/app#12'), 'app#12')
        self.assertEqual(one.issue_url('org/app#12'), 'https://github.com/org/app/issues/12')
        two = tr.make({'type': 'github', 'repos': ['org/app', 'org/lib']})
        self.assertEqual(two.find_keys('fix #12 · Org/Lib#4'), {'org/lib#4'})   # 레포가 둘이면 맨 #번호는 못 붙인다
        ghe = tr.make({'type': 'github', 'repos': ['a/b'], 'api_url': 'https://git.example.com/api/v3'})
        self.assertEqual(ghe.issue_url('a/b#1'), 'https://git.example.com/a/b/issues/1')

    def test_gitlab_keys(self):
        t = tr.make({'type': 'gitlab', 'projects': ['grp/sub/app'], 'api_url': 'https://gitlab.example.com/api/v4'})
        self.assertEqual(t.find_keys('closes #5 · grp/sub/app#6'), {'grp/sub/app#5', 'grp/sub/app#6'})
        self.assertEqual(t.display('grp/sub/app#5'), 'app#5')
        self.assertEqual(t.issue_url('grp/sub/app#5'), 'https://gitlab.example.com/grp/sub/app/-/issues/5')

    def test_branch_rule(self):
        self.conf({'tracker': {'type': 'jira', 'jira_project_keys': ['PROJ']}, 'branch_ticket_re': r'feature/(\d+)'},
                  {'jira': {}})
        self.assertEqual(ag.branch_keys('feature/123-login'), {'PROJ-123'})
        self.assertEqual(ag.branch_keys('hotfix/PROJ-9'), {'PROJ-9'})
        self.conf({})
        self.assertEqual(ag.branch_keys('feature/123-login'), set())        # 규칙 없음 = 키 정규식만

    def test_slug_and_select_roundtrip_with_hash_key(self):
        self.conf({'tracker': {'type': 'github', 'repos': ['org/app']}})
        self.assertEqual(ag.slug('org/app#12'), 'org~app-12')
        ag.save_select({'org/app#12': {'state': '발표고정', 'memo': '메모 #1'}, 'PROJ-1': {'state': '비공개', 'memo': ''}})
        self.assertEqual(ag.load_select(), {'org/app#12': {'state': '발표고정', 'memo': '메모 #1'},
                                            'PROJ-1': {'state': '비공개', 'memo': ''}})
        self.assertFalse(ag.key_ok('../x'))

    def test_mask(self):
        out = ag.mask('password: hunter2secret\nAuthorization: Bearer abcdefghijkl\n설명: 그냥 문장입니다\n'
                      '-----BEGIN KEY-----\nzzz\n-----END KEY-----\nurl?token=abc123&x=1\nghp_ABCDEFGHIJKLMNOP')
        self.assertIn('password: [masked]', out)
        self.assertNotIn('hunter2', out)
        self.assertNotIn('abcdefghijkl', out)
        self.assertIn('설명: 그냥 문장입니다', out)
        self.assertNotIn('zzz', out)
        self.assertIn('token=[masked]', out)
        self.assertNotIn('ABCDEFGHIJKLMNOP', out)


# ---------------------------------------------------------------- Jira

def jira_issue(key, assignee, comments=(), cloud=True):
    who = (lambda u: {'accountId': u, 'displayName': u.upper()}) if cloud else (lambda u: {'name': u, 'displayName': u.upper()})
    return {'key': key, 'fields': {
        'summary': key + ' 제목', 'status': {'name': 'Done'}, 'issuetype': {'name': 'Task'},
        'created': '2026-10-01T10:00:00.000+0900', 'updated': '2026-10-05T10:00:00.000+0900', 'resolutiondate': None,
        'labels': ['a'], 'assignee': who(assignee),
        'comment': {'comments': [{'author': who(a), 'created': '2026-10-05T11:00:00.000+0900', 'body': b} for a, b in comments]}}}


def adf(text):
    return {'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}]}


class Jira(Base):
    CLOUD = {'jira': {'base_url': 'https://team.atlassian.net', 'auth': 'cloud', 'email': 'me@example.com', 'token_enc': 'x'}}
    SERVER = {'jira': {'base_url': 'https://jira.example.com', 'auth': 'server', 'token_enc': 'x'}}

    def test_cloud_headers_search_paging_adf(self):
        page1 = {'issues': [jira_issue('PROJ-1', 'acc-me', [('acc-me', adf('보고: 끝냈습니다')), ('acc-x', adf('남의 말'))])],
                 'nextPageToken': 'NEXT', 'isLast': False}
        page2 = {'issues': [jira_issue('PROJ-2', 'acc-tm')], 'isLast': True}
        fake = Fake([('/rest/api/3/myself', {'accountId': 'acc-me', 'displayName': '나', 'emailAddress': 'me@example.com'}),
                     ('/rest/api/3/user/search', [{'accountId': 'acc-tm', 'displayName': '홍길동'}]),
                     ('/rest/api/3/search/jql', lambda u: page2 if qs(u).get('nextPageToken') == 'NEXT' else page1)])
        self.conf({'tracker': {'type': 'jira'}, 'team': ['홍길동']}, self.CLOUD, fake)
        issues = ag.collect_issues('2026-10-01', '2026-10-07')
        self.assertEqual([i['key'] for i in issues], ['PROJ-1', 'PROJ-2'])
        url, headers = fake.calls[-1]
        self.assertEqual(headers['Authorization'], 'Basic ' + base64.b64encode(b'me@example.com:tok').decode())
        self.assertTrue(url.startswith('https://team.atlassian.net/rest/api/3/search/jql?'))
        jql = qs(fake.calls[-2][0])['jql']
        self.assertIn('"acc-me"', jql)
        self.assertIn('"acc-tm"', jql)
        self.assertIn('updated >= "2026-10-01"', jql)
        self.assertTrue(issues[0]['mine'])
        self.assertFalse(issues[1]['mine'])
        self.assertEqual(issues[0]['my_comments'], [{'created': '2026-10-05', 'body': '보고: 끝냈습니다'}])
        self.assertEqual(issues[0]['url'], 'https://team.atlassian.net/browse/PROJ-1')

    def test_server_bearer_startat_paging(self):
        def search(url):
            start = int(qs(url)['startAt'])
            return {'issues': [jira_issue('PROJ-%d' % (start + 1), 'me', cloud=False)], 'total': 2}
        fake = Fake([('/rest/api/2/myself', {'name': 'me', 'displayName': '나'}),
                     ('/rest/api/2/search', search)])
        self.conf({'tracker': {'type': 'jira'}, 'comment_prefixes': ['[보고]']}, self.SERVER, fake)
        issues = ag.collect_issues('2026-10-01', '2026-10-07')
        self.assertEqual([i['key'] for i in issues], ['PROJ-1', 'PROJ-2'])
        self.assertEqual(fake.calls[-1][1]['Authorization'], 'Bearer tok')
        self.assertIn('/rest/api/2/search?', fake.calls[-1][0])
        self.assertEqual([qs(u)['startAt'] for u, _ in fake.calls if '/search' in u], ['0', '1'])

    def test_server_comment_prefix_filter(self):
        it = jira_issue('PROJ-1', 'me', [('me', '[보고] 배포함'), ('me', '그냥 메모')], cloud=False)
        fake = Fake([('/rest/api/2/myself', {'name': 'me', 'displayName': '나'}),
                     ('/rest/api/2/search', {'issues': [it], 'total': 1})])
        self.conf({'tracker': {'type': 'jira'}, 'comment_prefixes': ['[보고]']}, self.SERVER, fake)
        self.assertEqual([c['body'] for c in ag.collect_issues('2026-10-01', '2026-10-07')[0]['my_comments']], ['[보고] 배포함'])

    def test_not_ready_raises(self):
        self.conf({'tracker': {'type': 'jira'}}, {'jira': {}}, Fake([]))
        with self.assertRaises(RuntimeError):
            ag.collect_issues('2026-10-01', '2026-10-07')


# ---------------------------------------------------------------- GitHub

def gh_item(n, user='me', pr=False, comments=0):
    it = {'number': n, 'title': '이슈 %d' % n, 'state': 'open', 'labels': [{'name': 'bug'}],
          'created_at': '2026-10-01T00:00:00Z', 'updated_at': '2026-10-02T00:00:00Z', 'closed_at': None,
          'assignees': [{'login': user}], 'html_url': 'https://github.com/org/app/issues/%d' % n,
          'comments': comments, 'comments_url': 'https://api.github.com/repos/org/app/issues/%d/comments' % n}
    if pr:
        it['pull_request'] = {'url': 'x'}
    return it


class GitHub(Base):
    def test_query_paging_pr_excluded_comments(self):
        def search(url):
            page = int(qs(url)['page'])
            if page == 1:
                return {'total_count': 105, 'items': [gh_item(i) for i in range(1, 100)] + [gh_item(500, pr=True)]}
            return {'total_count': 105, 'items': [gh_item(i, comments=1 if i == 101 else 0) for i in range(100, 105)]}
        fake = Fake([('/search/issues', search),
                     ('/issues/101/comments', [{'user': {'login': 'me'}, 'created_at': '2026-10-02T01:00:00Z', 'body': '진행 보고'}]),
                     ('/user', {'login': 'me', 'name': '나'})])
        self.conf({'tracker': {'type': 'github', 'repos': ['org/app'], 'type_labels': ['bug']}}, {}, fake)
        issues = ag.collect_issues('2026-10-01', '2026-10-07')
        keys = {i['key'] for i in issues}
        self.assertEqual(len(issues), 104)
        self.assertNotIn('org/app#500', keys)
        q = qs([u for u, _ in fake.calls if '/search/issues' in u][0])['q']
        self.assertEqual(q, 'repo:org/app is:issue assignee:me updated:2026-10-01..2026-10-07')
        self.assertEqual([qs(u)['page'] for u, _ in fake.calls if '/search/issues' in u], ['1', '2'])
        i101 = next(i for i in issues if i['key'] == 'org/app#101')
        self.assertEqual(i101['my_comments'][0]['body'], '진행 보고')
        self.assertEqual(i101['type'], 'bug')
        self.assertTrue(all(i['mine'] for i in issues))
        self.assertEqual(fake.calls[0][1]['Authorization'], 'Bearer tok')

    def test_ready_needs_repos(self):
        ok, why = tr.make({'type': 'github'}, token='t').ready()
        self.assertFalse(ok)
        self.assertIn('repos', why)


# ---------------------------------------------------------------- GitLab

class GitLab(Base):
    def test_issues_paging_and_notes_without_system(self):
        def issues(url):
            q = qs(url)
            self.assertEqual(q['assignee_username'], 'me')
            self.assertEqual(q['updated_after'], '2026-10-01T00:00:00Z')
            self.assertEqual(q['updated_before'], '2026-10-07T23:59:59Z')
            n = 100 if q['page'] == '1' else 3
            base = 0 if q['page'] == '1' else 100
            return [{'iid': base + i, 'title': 't', 'state': 'opened', 'labels': [], 'issue_type': 'issue',
                     'created_at': '2026-10-01T00:00:00Z', 'updated_at': '2026-10-03T00:00:00Z', 'closed_at': None,
                     'assignees': [{'username': 'me', 'name': '나'}], 'web_url': 'https://gitlab.example.com/grp/app/-/issues/%d' % (base + i),
                     'user_notes_count': 1 if base + i == 1 else 0} for i in range(n)]
        notes = [{'system': True, 'author': {'username': 'me'}, 'created_at': '2026-10-02T00:00:00Z', 'body': 'changed label'},
                 {'system': False, 'author': {'username': 'me'}, 'created_at': '2026-10-02T00:00:00Z', 'body': '고쳤습니다'}]
        fake = Fake([('/issues/1/notes', notes), ('/projects/grp%2Fapp/issues?', issues),
                     ('/user', {'username': 'me', 'name': '나'})])
        self.conf({'tracker': {'type': 'gitlab', 'api_url': 'https://gitlab.example.com/api/v4', 'projects': ['grp/app']}}, {}, fake)
        got = ag.collect_issues('2026-10-01', '2026-10-07')
        self.assertEqual(len(got), 103)
        one = next(i for i in got if i['key'] == 'grp/app#1')
        self.assertEqual([c['body'] for c in one['my_comments']], ['고쳤습니다'])
        self.assertEqual(fake.calls[0][1]['PRIVATE-TOKEN'], 'tok')


# ---------------------------------------------------------------- none 출처 · 하네스 · 선택 기능

def git(repo, *args):
    subprocess.run(['git', '-c', 'user.name=tester', '-c', 'user.email=tester@example.com', *args], cwd=repo,
                   check=True, capture_output=True)


class Pipeline(Base):
    def make_repo(self):
        repo = os.path.join(self.tmp, 'app')
        os.makedirs(repo)
        git(repo, 'init', '-q')
        for i, msg in enumerate(['PROJ-7 로그인 오류 고침', 'PROJ-7 테스트 보강', '정리 커밋']):
            with open(os.path.join(repo, 'f%d.txt' % i), 'w') as f:
                f.write(msg)
            git(repo, 'add', '.')
            git(repo, 'commit', '-q', '-m', msg)
        return repo

    def test_none_tracker_groups_by_commit_keys(self):
        repo = self.make_repo()
        today = dt.date.today().isoformat()
        self.conf({'repos': [repo], 'my_authors': ['tester']})
        ag.collect(today, today)
        doc = (ag.WIKI / 'tickets' / 'main' / 'PROJ-7.md').read_text(encoding='utf-8')
        fm = ag.front_matter(doc)
        self.assertEqual(fm['title'], 'PROJ-7 로그인 오류 고침')       # 그 키가 처음 나온 커밋 제목
        self.assertEqual(fm['commits'], '2')
        self.assertEqual(fm['mine'], 'Y')
        index = (ag.WIKI / 'INDEX.md').read_text(encoding='utf-8')
        self.assertIn('| part | ticket | updated | status | commits | 선택 | title |', index)   # 꼬리표·하네스 열 없음
        self.assertNotIn('하네스', index.split('## 티켓')[0])
        t = ag.list_tickets()
        self.assertEqual([x['key'] for x in t], ['PROJ-7'])

    def test_harness_on_without_docs_does_not_crash(self):
        repo = self.make_repo()
        today = dt.date.today().isoformat()
        self.conf({'workspace_root': repo, 'my_authors': ['tester'], 'harness': {'enabled': True}})
        ag.collect(today, today)
        self.assertTrue((ag.WIKI / 'tickets' / 'main' / 'PROJ-7.md').exists())
        self.assertIn('| harness |', (ag.WIKI / 'INDEX.md').read_text(encoding='utf-8'))

    def test_apply_select_and_compact_follow_columns(self):
        self.conf({'tag': {'label': '고객사'}, 'harness': {'enabled': True}})
        cols = ag.index_columns()
        self.assertEqual(cols, ['part', 'ticket', 'updated', '고객사', 'status', 'commits', 'harness', '선택', 'title'])
        index = '\n'.join(['# x', '## 티켓', '', '| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols),
                           '| main | A-1 | 2026-10-01 | 가 | Open | 1 | grilling |  | t1 |',
                           '| main | A-2 | 2026-10-01 |  | Open | 1 |  |  | t2 |',
                           '| main | A-3 | 2026-10-01 |  | Open | 1 | doc |  | t3 |', '', '## 다른 표', '| a | b |'])
        out = ag.apply_select(index, {'A-1': {'state': '발표고정'}, 'A-2': {'state': '비공개'}}, drop={'A-3'})
        self.assertIn('| 발표고정 |', out)
        self.assertNotIn('A-2', out)
        self.assertNotIn('A-3', out)
        self.assertIn('| a | b |', out)
        compact = ag.compact_index(index)
        self.assertIn('A-1', compact)
        self.assertNotIn('A-2', compact)

    def test_tag_off_and_on(self):
        self.conf({})
        self.assertEqual(ag.tag_of('[고객A] 오류'), '')
        self.assertNotIn('', ag.index_columns())
        self.conf({'tag': {'label': '고객사', 'ignore': ['긴급']}})
        self.assertEqual(ag.tag_of('[긴급][고객A] 오류'), '고객A')
        self.conf({'tag': {'label': '모듈', 'regex': r'<([^>]+)>'}})
        self.assertEqual(ag.tag_of('요청 <결제>'), '결제')

    def test_review_bot_off_and_on(self):
        report = '**요약**\n좋음\n**⚠️ Issue**\n- 널 확인 빠짐\n**칭찬**\n잘함\n'
        t = {'records': [], 'commits': [], 'mrs': [{'bot_issue_count': 2}], 'updated': '2026-10-07'}
        self.conf({})
        self.assertEqual(ag.bot_issues(report), [])
        self.assertNotIn('AI 리뷰', ag.recommend_score(t, 'none', dt.date(2026, 10, 7))[1])
        self.conf({'review_bot': {'name': 'review-bot', 'issue_heading': 'Issue'}})
        self.assertEqual(ag.bot_issues(report), ['널 확인 빠짐'])
        self.assertEqual(ag.bot_issues('**Issue**\n없음\n'), [])
        self.assertIn('AI 리뷰 지적', ag.recommend_score(t, 'none', dt.date(2026, 10, 7))[1])

    def test_mrs_skipped_without_gitlab(self):
        self.conf({}, {}, Fake([]))
        self.assertEqual(ag.collect_mrs('2026-10-01', '2026-10-07'), [])


# ---------------------------------------------------------------- 주간 업무 보고 초안

def fake_data(since, until, other=False):
    return {'since': since, 'until': until, 'errors': [], 'meta': {}, 'mrs': [], 'records': [],
            'issues': [{'key': 'PROJ-1', 'title': '결제 오류', 'status': 'Done', 'updated': until, 'resolved': until,
                        'url': 'https://jira.example.com/browse/PROJ-1', 'mine': True,
                        'my_comments': [{'created': until, 'body': '배포 완료'}]},
                       {'key': 'PROJ-9', 'title': '남의 것', 'status': 'Open', 'updated': until, 'resolved': '', 'url': '',
                        'mine': False, 'my_comments': []}],
            'commits': [{'repo': 'app', 'sha': 'abc1234', 'date': until, 'subject': 'PROJ-1 금액 계산 고침',
                         'mine': True, 'ai': True, 'tickets': ['PROJ-1']},
                        {'repo': 'app', 'sha': 'def5678', 'date': until, 'subject': '빌드 스크립트 정리',
                         'mine': True, 'ai': False, 'tickets': []}]}


class Weekly(Base):
    def setUp(self):
        super().setUp()
        self.conf({'tracker': {'type': 'jira'}, 'weekly_report': {'to': ['boss@example.com']}},
                  {'jira': {'base_url': 'https://jira.example.com'}, 'mail': {'user': 'me@example.com'}})
        self.sent = []

    def mailer(self, to, subject, body):
        self.sent.append((to, subject, body))

    def test_week_range_starts_monday(self):
        self.assertEqual(ag.week_range(dt.date(2026, 10, 16)), ('2026-10-12', '2026-10-16'))   # 금
        self.assertEqual(ag.week_range(dt.date(2026, 10, 12)), ('2026-10-12', '2026-10-12'))   # 월
        self.assertEqual(ag.week_range(dt.date(2026, 10, 18)), ('2026-10-12', '2026-10-18'))   # 일

    def test_draft_saved_and_mailed(self):
        seen = {}

        def llm(prompt, engine, model):
            seen['prompt'], seen['engine'] = prompt, engine
            return '# 주간 업무 보고\n- PROJ-1 결제 오류 해결'
        res = ag.weekly(gather_fn=fake_data, llm=llm, mailer=self.mailer, ready=lambda: (True, ''),
                        today=dt.date(2026, 10, 16))
        path = Path(res['path'])
        self.assertEqual(path.name, '20261016_주간보고.md')
        self.assertEqual(path.parent, ag.REPORTS)
        self.assertTrue(res['llm_ok'] and res['sent'])
        self.assertEqual(self.sent[0][0], ['boss@example.com'])
        self.assertIn('2026-10-12 ~ 2026-10-16', self.sent[0][1])
        self.assertEqual(self.sent[0][2], path.read_text(encoding='utf-8'))
        self.assertEqual(seen['engine'], 'claude')
        self.assertIn('PROJ-1 결제 오류', seen['prompt'])
        self.assertIn('https://jira.example.com/browse/PROJ-1', seen['prompt'])
        self.assertIn('Claude 공동작성 커밋 1/2 (50%)', seen['prompt'])
        self.assertNotIn('남의 것', seen['prompt'])                       # 팀원 이슈는 넣지 않는다
        self.assertTrue(self.status.call_args[0][1][0]['ok'])

    def test_llm_failure_sends_raw_material(self):
        def boom(*a):
            raise RuntimeError('claude 없음')
        res = ag.weekly(gather_fn=fake_data, llm=boom, mailer=self.mailer, ready=lambda: (True, ''),
                        today=dt.date(2026, 10, 16))
        self.assertFalse(res['llm_ok'])
        self.assertTrue(res['sent'])
        body = self.sent[0][2]
        self.assertIn('원자료', body)
        self.assertIn('PROJ-1 결제 오류', body)
        self.assertIn('빌드 스크립트 정리', body)
        self.assertIn('claude 없음', body)
        self.assertFalse(self.status.call_args[0][1][0]['ok'])

    def test_mail_not_ready_keeps_file_and_reports(self):
        res = ag.weekly(gather_fn=fake_data, llm=lambda *a: '초안', mailer=self.mailer,
                        ready=lambda: (False, '설정에 없는 값: user'), today=dt.date(2026, 10, 16))
        self.assertFalse(res['sent'])
        self.assertEqual(self.sent, [])
        self.assertTrue(Path(res['path']).exists())
        item = self.status.call_args[0][1][0]
        self.assertFalse(item['ok'])
        self.assertIn('메일 설정 필요', item['text'])

    def test_no_mail_and_gather_failure(self):
        def broken(*a, **k):
            raise RuntimeError('git 없음')
        res = ag.weekly(gather_fn=broken, llm=lambda p, e, m: '초안' if '수집 실패' in p else '', send=False,
                        today=dt.date(2026, 10, 16))
        self.assertTrue(res['llm_ok'])
        self.assertEqual(self.sent, [])
        self.assertIn('보내지 않음', res['why'])

    def test_recipients_fall_back_to_my_address(self):
        self.conf({}, {'mail': {'user': 'me@example.com'}})
        self.assertEqual(ag.weekly_recipients(), ['me@example.com'])


# ---------------------------------------------------------------- 토큰 · 허브 자동화

class TokenAndHub(Base):
    def test_set_token(self):
        saved = []
        full = {'ai_share': {'tracker': {'type': 'jira'}}}
        self.assertEqual(ag.set_token('tracker', secret=lambda p: 't', protect=lambda t: 'E', full=full, save=saved.append), 1)
        self.assertEqual(saved, [])
        full = {'ai_share': {'tracker': {'type': 'github'}}}
        self.assertEqual(ag.set_token('tracker', secret=lambda p: ' t ', protect=lambda t: 'E:' + t, full=full,
                                      save=saved.append), 0)
        self.assertEqual(full['ai_share']['tracker']['token_enc'], 'E:t')
        ag.set_token('gitlab', secret=lambda p: 'g', protect=lambda t: 'G', full=full, save=saved.append)
        self.assertEqual(full['ai_share']['gitlab']['token_enc'], 'G')

    def test_service_meta_and_settings(self):
        self.assertEqual(svc.META['owns'][0]['has'], ['ai-share-agent', 'agent.py', 'serve', '--kit-service'])
        self.assertEqual(svc.settings({}), (False, 8640))
        self.assertEqual(svc.settings({'ai_share': {'enabled': True, 'port': '8650'}}), (True, 8650))

    def test_weekly_job_schedule(self):
        w = job.settings({'ai_share': {'weekly_report': {'enabled': True, 'days': ['mon', 'fri'], 'at': '16:00'}}})
        self.assertEqual(w['days'], 'mon,fri')
        fri = dt.datetime(2026, 10, 16, 16, 5)
        self.assertTrue(job.is_due(w, {}, fri))
        self.assertFalse(job.is_due(w, {'last_run': fri.timestamp()}, fri))
        self.assertFalse(job.is_due(w, {'last_fail': fri.timestamp() - 60}, fri))
        self.assertFalse(job.is_due(w, {}, dt.datetime(2026, 10, 15, 16, 5)))      # 목요일
        self.assertFalse(job.is_due(dict(w, enabled=False), {}, fri))

    def test_weekly_feature_listed(self):
        import ops
        self.assertIn('weekly_report', dict(ops.FEATURES))


if __name__ == '__main__':
    unittest.main()
