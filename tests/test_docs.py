# -*- coding: utf-8 -*-
"""공개 도움말(docs/index.html)이 코드와 맞는지 — 설정 견본·매크로 설명·ctx 도구가 바뀌면 다시 만들어야 한다."""
import importlib.util
import os
import re
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
spec = importlib.util.spec_from_file_location('build_docs', os.path.join(ROOT, 'docs', 'build_docs.py'))
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)


class Docs(unittest.TestCase):
    def test_up_to_date(self):
        with open(bd.OUT, encoding='utf-8', newline='') as f:
            cur = f.read().replace('\r\n', '\n')
        self.assertEqual(cur, bd.build(), 'docs/index.html 이 코드와 어긋났습니다 — python docs/build_docs.py')

    def test_every_config_section_documented(self):
        import json
        with open(os.path.join(ROOT, 'config.example.json'), encoding='utf-8') as f:
            conf = json.load(f)
        documented = {k for k, _, _ in bd.SECTIONS}
        missing = [k for k in conf if not k.startswith('_') and k not in documented]
        self.assertEqual(missing, [], '새 설정 갈래를 docs/build_docs.py 의 SECTIONS 에 넣으세요')

    def test_ctx_methods_found(self):
        names = [s for s, _ in bd.ctx_methods()]
        self.assertIn('ctx.log(*parts)', names)
        self.assertIn('ctx.page', names)

    def test_only_example_addresses(self):
        # 공개 문서에 실제 회사 메일 주소가 섞이지 않게 — 견본 주소는 example.com · *.example(예약된 견본 도메인)만
        text = bd.build()
        mails = set(re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', text))
        self.assertEqual({m for m in mails if not re.search(r'@(example\.com|[\w.-]+\.example)$', m.lower())}, set())


if __name__ == '__main__':
    unittest.main()
