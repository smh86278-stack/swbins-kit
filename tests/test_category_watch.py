# -*- coding: utf-8 -*-
"""카테고리·정보고시 변경 감시(job_category_watch) — 나무 펼치기·비교·깨진 매핑·쿠팡 서명. 네트워크 없음."""
import hashlib
import hmac
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub'))
sys.path.insert(0, HUB)
spec = importlib.util.spec_from_file_location('job_category_watch', os.path.join(HUB, 'macros', 'job_category_watch.py'))
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)

TREE = {'data': {'code': 0, 'name': '전체', 'status': 'ACTIVE', 'child': [
    {'code': 10, 'name': '패션', 'status': 'ACTIVE', 'child': [
        {'code': 101, 'name': '티셔츠', 'status': 'ACTIVE', 'notice': '의류', 'child': []},
        {'code': 102, 'name': '바지', 'status': 'INACTIVE', 'child': []}]},
    {'code': 20, 'name': '식품', 'status': 'ACTIVE', 'notice': '가공식품'}]}}
SPEC = {'items': 'data', 'children': 'child', 'code': 'code', 'label': 'name', 'notice': 'notice', 'status': 'status'}


class Logic(unittest.TestCase):
    def test_flatten_tree(self):
        s = cw.flatten(cw.get_path(TREE, 'data'), SPEC)
        self.assertEqual(sorted(s), ['0', '10', '101', '20'])               # 102 는 INACTIVE
        self.assertEqual(s['101'], {'label': '전체 > 패션 > 티셔츠', 'notice': '의류', 'leaf': True})
        self.assertFalse(s['10']['leaf'])

    def test_diff_and_broken(self):
        old = cw.flatten(cw.get_path(TREE, 'data'), SPEC)
        new = json.loads(json.dumps(old))
        new.pop('20')                                                        # 식품 없어짐
        new['101'] = dict(new['101'], notice='의류(개정)', leaf=False)       # 정보고시 바뀌고 하위가 생김
        new['10'] = dict(new['10'], label='전체 > 패션의류')
        new['30'] = {'label': '전체 > 가전', 'notice': '', 'leaf': True}
        d = cw.diff(old, new)
        self.assertEqual([c for c, _ in d['removed']], ['20'])
        self.assertEqual([c for c, _ in d['added']], ['30'])
        self.assertEqual([c for c, _ in d['renamed']], ['10'])
        self.assertEqual([c for c, _ in d['notice']], ['101'])
        self.assertEqual([c for c, _ in d['not_leaf']], ['101'])
        rows = [{'상품': 'A', '코드': '20'}, {'상품': 'B', '코드': '101'}, {'상품': 'C', '코드': '30'}, {'상품': 'D', '코드': ''}]
        bad = cw.broken(rows, {'code': '코드', 'key': '상품'}, new, ['101'])
        self.assertEqual([(k, c) for k, c, _ in bad], [('A', '20'), ('B', '101')])
        self.assertIn('말단이 아님', bad[1][2])

    def test_evaluate_first_then_change(self):
        snap = {'1': {'label': 'a', 'notice': '', 'leaf': True}}
        d, bad, text, first = cw.evaluate_market('몰', None, snap, [])
        self.assertTrue(first)
        self.assertIsNone(d)
        d, bad, text, first = cw.evaluate_market('몰', snap, {}, [({'name': 'm', 'code': 'c'}, [{'c': '1'}])])
        self.assertEqual(len(d['removed']), 1)
        self.assertEqual(bad, [('m', '', '1', '마켓에 없는 카테고리')])
        self.assertIn('없어짐 1', text)

    def test_coupang_auth(self):
        url = 'https://api-gateway.coupang.com/v2/providers/x/apis/api/v1/meta?a=1'
        h = cw.coupang_auth('GET', url, 'AK', 'SK', now=0)
        sig = hmac.new(b'SK', b'700101T000000ZGET/v2/providers/x/apis/api/v1/metaa=1', hashlib.sha256).hexdigest()
        self.assertEqual(h, 'CEA algorithm=HmacSHA256, access-key=AK, signed-date=700101T000000Z, signature=' + sig)


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_csv_cp949_and_json_file(self):
        p = os.path.join(self.tmp, 'cat.csv')
        with open(p, 'w', encoding='cp949', newline='') as f:
            f.write('카테고리코드,카테고리명,정보고시\n101,티셔츠,의류\n,빈줄,\n')
        s = cw.load_market({'type': 'file', 'path': p, 'code': '카테고리코드', 'label': '카테고리명', 'notice': '정보고시'})
        self.assertEqual(s, {'101': {'label': '티셔츠', 'notice': '의류', 'leaf': True}})
        j = os.path.join(self.tmp, 'cat.json')
        with open(j, 'w', encoding='utf-8') as f:
            json.dump(TREE, f, ensure_ascii=False)
        self.assertEqual(len(cw.load_market(dict(SPEC, type='file', path=j))), 4)

    def test_json_url_signs_for_coupang(self):
        seen = []

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(TREE).encode()

        def opener(req):
            seen.append(req)
            return R()
        m = dict(SPEC, type='json_url', url='https://api-gateway.coupang.com/v2/x', auth='coupang', access_key_enc='a', secret_key_enc='b')
        with mock.patch.object(cw.kit, 'unprotect', side_effect=lambda v: v.upper()):
            s = cw.load_market(m, opener=opener)
        self.assertEqual(len(s), 4)
        self.assertTrue(seen[0].get_header('Authorization').startswith('CEA algorithm=HmacSHA256, access-key=A,'))
        with self.assertRaises(ValueError):
            cw.load_market(dict(m, url='http://example.com'))

    def test_report_csv(self):
        p = os.path.join(self.tmp, 'r', 'report.csv')
        d = cw.diff({'1': {'label': 'a', 'notice': '', 'leaf': True}}, {})
        cw.write_report(p, '몰', d, [('A', '1', '마켓에 없는 카테고리')])
        with open(p, encoding='utf-8-sig') as f:
            text = f.read()
        self.assertIn('몰,없어짐,1,a', text)
        self.assertIn('몰,깨진 매핑,1,A — 마켓에 없는 카테고리', text)


if __name__ == '__main__':
    unittest.main()
