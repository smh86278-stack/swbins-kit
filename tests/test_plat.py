# -*- coding: utf-8 -*-
"""plat(윈도우·맥 차이) · 맥 실행기(mac_launch) 의 옮기기 — 윈도우·맥 CI 둘 다에서 돈다."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'macro-hub')
sys.path.insert(0, HUB)
import plat  # noqa: E402
import extsvc  # noqa: E402
import mac_launch  # noqa: E402


class Plat(unittest.TestCase):
    def test_bg_and_kill_tree(self):
        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], **plat.bg())
        plat.kill_tree(p.pid)
        for _ in range(50):
            if p.poll() is not None:
                break
            time.sleep(0.1)
        self.assertIsNotNone(p.poll())

    def test_kill_tree_gone_pid(self):
        p = subprocess.Popen([sys.executable, '-c', 'pass'], **plat.bg())
        p.wait()
        plat.kill_tree(p.pid)                      # 이미 끝난 것 — 조용히

    def test_single_instance(self):
        name = 'taskhand-test-%d' % os.getpid()
        self.assertTrue(plat.single_instance(name))
        if not plat.IS_WIN:                        # 맥은 같은 프로세스에서 다시 잡아도 잠금 파일이 거절한다
            self.assertFalse(plat.single_instance(name))

    def test_venv_python_shape(self):
        p = plat.venv_python('/x')
        self.assertIn('.venv', p)
        self.assertTrue(p.endswith('python.exe') if plat.IS_WIN else 'python' in os.path.basename(p))

    def test_flags(self):
        self.assertEqual(plat.NO_WINDOW, 0x08000000 if plat.IS_WIN else 0)

    @unittest.skipUnless(plat.IS_MAC and os.environ.get('KIT_KEYCHAIN_TESTS') == '1', '맥 키체인 — KIT_KEYCHAIN_TESTS=1 일 때만')
    def test_keychain_roundtrip(self):
        mark = plat.keychain_put('비밀 값 123')
        self.assertTrue(mark.startswith(plat.KEYCHAIN_PREFIX))
        self.assertEqual(plat.keychain_get(mark), '비밀 값 123')


class OwnsNames(unittest.TestCase):
    def test_name_ok(self):
        if plat.IS_WIN:
            self.assertTrue(extsvc._name_ok(['python.exe'], 'Python.exe'))
            self.assertFalse(extsvc._name_ok(['python.exe'], 'python3.12'))
        else:
            self.assertTrue(extsvc._name_ok(['python.exe', 'pythonw.exe'], 'python3.12'))
            self.assertTrue(extsvc._name_ok(['python.exe'], 'Python'))
            self.assertFalse(extsvc._name_ok(['node.exe'], 'python3'))


class MacSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, 'src')
        self.dst = os.path.join(self.tmp, 'dst')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, root, rel, text):
        p = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)

    def read(self, root, rel):
        with open(os.path.join(root, *rel.split('/')), encoding='utf-8') as f:
            return f.read()

    def test_first_copy_then_update_keeps_user_files(self):
        self.write(self.src, 'VERSION', '1.0')
        self.write(self.src, 'tools/macro-hub/macrohub.py', 'v1')
        self.write(self.src, 'tools/macro-hub/old.py', 'old')
        self.assertEqual(mac_launch.sync(self.src, self.dst), 3)
        self.assertEqual(mac_launch.sync(self.src, self.dst), 0)          # 같은 버전 — 그대로
        self.write(self.dst, 'config.local.json', '{"mine": 1}')
        self.write(self.dst, 'tools/macro-hub/macros.local/my.py', 'mine')
        self.write(self.dst, 'tools/macro-hub/.venv/bin/python3', '')
        # 새 버전: 코드는 바뀌고, 없어진 파일은 지워지고, 사용자 것은 남는다
        os.remove(os.path.join(self.src, 'tools', 'macro-hub', 'old.py'))
        self.write(self.src, 'VERSION', '1.1')
        self.write(self.src, 'tools/macro-hub/macrohub.py', 'v2')
        self.write(self.src, 'config.local.json', '{"default": 1}')        # 견본이 섞여 와도 덮지 않는다
        mac_launch.sync(self.src, self.dst)
        self.assertEqual(self.read(self.dst, 'tools/macro-hub/macrohub.py'), 'v2')
        self.assertFalse(os.path.exists(os.path.join(self.dst, 'tools', 'macro-hub', 'old.py')))
        self.assertEqual(self.read(self.dst, 'config.local.json'), '{"mine": 1}')
        self.assertEqual(self.read(self.dst, 'tools/macro-hub/macros.local/my.py'), 'mine')
        self.assertTrue(os.path.exists(os.path.join(self.dst, 'tools', 'macro-hub', '.venv', 'bin', 'python3')))

    def test_login_autostart_plist(self):
        import plistlib
        agents = os.path.join(self.tmp, 'LaunchAgents')
        self.assertFalse(mac_launch.autostart_enabled(agents))
        self.assertTrue(mac_launch.set_autostart(True, python='/usr/bin/python3', agents=agents))
        with open(mac_launch.plist_path(agents), 'rb') as f:
            d = plistlib.load(f)
        self.assertEqual(d['Label'], 'com.taskhand.hub')
        self.assertTrue(d['RunAtLoad'])
        args = d['ProgramArguments']
        self.assertEqual(args[0], '/usr/bin/python3')
        self.assertTrue(args[1].endswith(os.path.join('tools', 'macro-hub', 'mac_launch.py')))
        self.assertEqual(args[2:], ['--src', mac_launch.KIT, '--login'])   # 로그인 땐 옮겨 둔 키트에서 — 대화 상자 없이
        self.assertFalse(mac_launch.set_autostart(False, agents=agents))
        self.assertFalse(os.path.exists(mac_launch.plist_path(agents)))
        mac_launch.set_autostart(False, agents=agents)                      # 이미 꺼져 있어도 괜찮다

    def test_menubar_menu(self):
        import mac_menubar
        spec = [s for s in mac_menubar.menu_spec() if s]
        labels = [s[0] for s in spec if isinstance(s[0], str)]
        self.assertEqual(labels, ['Taskhand 열기', '운영 화면', '로그인 때 자동 시작', '허브 다시 띄우기', '끄기 (허브와 메뉴 막대)'])
        self.assertEqual([s[0] for s in spec if s[3]], ['Taskhand 열기'])  # 아이콘을 누르면 여는 기본 항목은 하나
        self.assertTrue(os.path.isfile(mac_menubar.ICON))
        self.assertIn(mac_menubar.status_text(), ('허브: 도는 중', '허브: 꺼짐'))


if __name__ == '__main__':
    unittest.main()
