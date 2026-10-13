# -*- coding: utf-8 -*-
"""마켓 장애 공지 감시(job_market_notice) — 공지 읽기·거르기·실패 급증·판정. 네트워크·진짜 로그 없음."""
import datetime
import importlib.util
import os
import sys
import unittest

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
spec = importlib.util.spec_from_file_location('job_market_notice', os.path.join(HUB, 'macros', 'job_market_notice.py'))
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)

D = datetime.datetime
NOW = D(2026, 10, 14, 12, 0).timestamp()
H = 3600

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>공지</title>
<item><title>[장애] 주문 조회 지연 안내</title><link>https://example.com/n/2</link><pubDate>Tue, 14 Oct 2026 11:20:00 +0900</pubDate></item>
<item><title>추석 연휴 배송 안내</title><link>https://example.com/n/1</link><pubDate>Mon, 13 Oct 2026 09:00:00 +0900</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>API 점검 예정</title><link href="https://example.com/a/1"/><updated>2026-10-14T02:00:00Z</updated></entry></feed>"""

HTML = """<ul><li><a href="/notice/31">[점검] 정기 서버 점검 안내</a><span>2026.10.14</span></li>
<li><a href="/notice/30">신규 기능 &amp; 개선</a><span>2026.10.10</span></li></ul>"""


class Parse(unittest.TestCase):
    def test_when(self):
        self.assertEqual(mn.parse_when('2026-10-14 09:30'), D(2026, 10, 14, 9, 30).timestamp())
        self.assertEqual(mn.parse_when('2026.10.14'), D(2026, 10, 14).timestamp())
        self.assertEqual(mn.parse_when('26.10.14'), D(2026, 10, 14).timestamp())
        self.assertEqual(mn.parse_when('Tue, 14 Oct 2026 11:20:00 +0900'),
                         D(2026, 10, 14, 2, 20, tzinfo=datetime.timezone.utc).timestamp())
        self.assertIsNone(mn.parse_when('어제'))

    def test_rss_and_atom(self):
        r = mn.parse_rss(RSS)
        self.assertEqual([x['title'] for x in r], ['[장애] 주문 조회 지연 안내', '추석 연휴 배송 안내'])
        self.assertEqual(r[0]['link'], 'https://example.com/n/2')
        a = mn.parse_rss(ATOM)
        self.assertEqual((a[0]['title'], a[0]['link']), ('API 점검 예정', 'https://example.com/a/1'))

    def test_html(self):
        rx = r'<a href="(?P<link>[^"]+)">(?P<title>[^<]+)</a><span>(?P<date>[^<]+)</span>'
        r = mn.parse_html(HTML, rx, 'https://example.com/board/')
        self.assertEqual([(x['title'], x['link']) for x in r],
                         [('[점검] 정기 서버 점검 안내', 'https://example.com/notice/31'), ('신규 기능 & 개선', 'https://example.com/notice/30')])
        with self.assertRaises(ValueError):
            mn.parse_html(HTML, r'<a>(?P<x>.*)</a>')

    def test_html_tag_goes_before_title(self):
        page = '<i>[긴급]</i><a href="/n/9"><b>주문 API 응답 지연</b></a><em>2026. 10. 08</em>'
        r = mn.parse_html(page, r'<i>(?P<tag>[^<]*)</i><a href="(?P<link>[^"]+)">(?P<title>.*?)</a><em>(?P<date>[^<]+)</em>', 'https://example.com/')
        self.assertEqual((r[0]['title'], r[0]['ts']), ('[긴급] 주문 API 응답 지연', D(2026, 10, 8).timestamp()))

    def test_json(self):
        data = {'item': [{'title': '[장애] 상품 API 오류', 'regDate': '2026-09-10T10:00:00', 'viewUrl': 'https://example.com/1',
                          'category': {'categoryName': '시스템'}, 'isEmergency': False},
                         {'title': '문서 변경', 'regDate': '2026-09-30T18:53:00', 'viewUrl': 'https://example.com/2',
                          'category': {'categoryName': '일반'}, 'isEmergency': True}]}
        src = {'items': 'item', 'title': 'title', 'date': 'regDate', 'link': 'viewUrl', 'tag': 'category.categoryName', 'emergency': 'isEmergency'}
        r = mn.parse_json(data, src)
        self.assertEqual([x['title'] for x in r], ['[시스템] [장애] 상품 API 오류', '[일반] 문서 변경'])
        self.assertEqual(r[0]['ts'], D(2026, 9, 10, 10, 0).timestamp())
        self.assertEqual([mn.is_incident(x, ['장애']) for x in r], [True, True])        # 두 번째는 isEmergency
        with self.assertRaises(ValueError):
            mn.parse_json({'item': {}}, src)

    def test_read_source(self):
        with self.assertRaises(ValueError):
            mn.read_source({'type': 'rss', 'url': 'file:///c:/x'}, get=lambda u: '')
        with self.assertRaises(ValueError):
            mn.read_source({'type': 'html', 'url': 'https://example.com'}, get=lambda u: '')
        asked = []

        def get(u):
            asked.append(u)
            return '' if u.endswith('/robots.txt') else RSS
        r = mn.read_source({'type': 'statuspage', 'url': 'https://status.example.com/'}, get=get)
        self.assertEqual(asked, ['https://status.example.com/robots.txt', 'https://status.example.com/history.rss'])
        self.assertTrue(all(x['incident'] for x in r))                                   # 상태 페이지는 전부 장애·점검

    def test_robots_blocks(self):
        def get(u):
            if u.endswith('/robots.txt'):
                return 'User-agent: *\nDisallow: /board/\n'
            raise AssertionError('robots.txt 가 막았는데 읽으러 갔다: ' + u)
        with self.assertRaises(PermissionError):
            mn.read_source({'type': 'rss', 'url': 'https://example.com/board/rss'}, get=get)
        self.assertTrue(mn.robots_allowed('https://example.com/notice', lambda u: 'User-agent: *\nDisallow: /board/\n'))
        self.assertTrue(mn.robots_allowed('https://example.com/x', lambda u: (_ for _ in ()).throw(OSError('404'))))


class ExampleConfig(unittest.TestCase):
    def test_example_sources_are_valid(self):
        import json
        import re
        with open(os.path.join(HUB, '..', '..', 'config.example.json'), encoding='utf-8') as f:
            conf = json.load(f)['market_notice']
        self.assertTrue(conf['sources'])
        for src in conf['sources']:
            with self.subTest(src=src['name']):
                self.assertIn(src['type'], ('rss', 'statuspage', 'html', 'json'))
                self.assertTrue(src['url'].startswith('https://'))
                if src['type'] == 'html':
                    self.assertIn('title', re.compile(src['item'], re.S).groupindex)


class Flow(unittest.TestCase):
    CONF = {'sources': [{'name': '몰A', 'type': 'rss', 'url': 'https://example.com/rss'}],
            'failures': [{'name': '주문 수집', 'path': 'x', 'match': '실패', 'spike_min': 5, 'spike_ratio': 3}], 'window_min': 120}

    def test_first_read_seeds_then_new_alerts(self):
        items = mn.parse_rss(RSS)
        st, status, alerts = mn.evaluate(self.CONF, {}, {'몰A': items}, {'주문 수집': []}, NOW)
        self.assertEqual(alerts, [])                                         # 처음 — 있던 공지는 알리지 않는다
        self.assertIn('처음 읽음', status[0]['text'])
        more = items + [{'title': '[긴급] 상품 등록 오류', 'link': 'https://example.com/n/3', 'ts': NOW - 600}]
        st, status, alerts = mn.evaluate(self.CONF, st, {'몰A': more}, {'주문 수집': []}, NOW)
        self.assertEqual(len(alerts), 1)
        self.assertIn('상품 등록 오류', alerts[0][0])
        self.assertEqual(mn.evaluate(self.CONF, st, {'몰A': more}, {'주문 수집': []}, NOW)[2], [])   # 같은 공지 두 번 안 알림

    def test_spike_with_and_without_notice(self):
        quiet = [NOW - 10 * H + i * 60 for i in range(3)]                     # 평소: 하루 3건
        burst = quiet + [NOW - 1800 + i * 60 for i in range(8)]               # 지난 1시간 8건
        state = {'seen': {'몰A': []}, 'notices': [{'source': '몰A', 'title': '[장애] 주문 조회 지연', 'ts': NOW - 1200, 'link': ''}]}
        st, status, alerts = mn.evaluate(self.CONF, state, {'몰A': []}, {'주문 수집': burst}, NOW)
        self.assertTrue(alerts[0][0].startswith('[실패 급증] 주문 수집 — 1시간 8건'))
        self.assertIn('마켓 쪽일 가능성', alerts[0][1])
        self.assertFalse(status[-1]['ok'])
        self.assertEqual(mn.evaluate(self.CONF, st, {'몰A': []}, {'주문 수집': burst}, NOW + 60)[2], [])   # 급증 중 — 다시 안 알림
        st2, _, alerts = mn.evaluate(self.CONF, st, {'몰A': []}, {'주문 수집': quiet}, NOW + 120)
        self.assertTrue(alerts[0][0].startswith('[실패 급증 풀림]'))
        _, _, alerts = mn.evaluate(self.CONF, dict(st2, notices=[]), {'몰A': []}, {'주문 수집': burst}, NOW + 180)
        self.assertIn('우리 쪽', alerts[0][1])

    def test_read_errors_are_status_not_crash(self):
        _, status, alerts = mn.evaluate(self.CONF, {}, {'몰A': OSError('timed out')}, {'주문 수집': OSError('없음')}, NOW)
        self.assertEqual([s['ok'] for s in status], [None, None])
        self.assertEqual(alerts, [])

    def test_failure_times(self):
        lines = ['2026-10-14 11:50:01 주문수집 실패 몰A', '2026-10-14 11:51 주문수집 성공', '시각 없는 실패 줄',
                 '[2026.10.14 11:55:00] ERROR 주문수집 실패']
        self.assertEqual(mn.failure_times(lines, '실패'), [D(2026, 10, 14, 11, 50, 1).timestamp(), D(2026, 10, 14, 11, 55).timestamp()])

    def test_spike_needs_minimum(self):
        self.assertFalse(mn.spike_check([NOW - 60] * 2, NOW, 5, 3)[2])        # 평소 0건이어도 5건은 넘어야
        self.assertTrue(mn.spike_check([NOW - 60] * 5, NOW, 5, 3)[2])


if __name__ == '__main__':
    unittest.main()
