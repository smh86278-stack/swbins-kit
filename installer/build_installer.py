# -*- coding: utf-8 -*-
"""설치 파일(WorkKitSetup-<버전>.exe) 만들기 — 키트 파일 + 내장 파이썬 + 필요한 패키지를 exe 하나로 묶는다.

    <PyInstaller 가 있는 파이썬> installer\\build_installer.py --site-packages <패키지를 가져올 site-packages>

예 (개발 PC — 허브 .venv 에 pystray·Pillow·pywinauto·PyInstaller 가 이미 있다):
    tools\\macro-hub\\.venv\\Scripts\\python.exe installer\\build_installer.py --site-packages tools\\macro-hub\\.venv\\Lib\\site-packages

하는 일
  1. 키트 파일 — git 에 커밋된 것만(git archive HEAD). 작업 중인 변경·설정·기록은 들어가지 않는다.
  2. 내장 파이썬(runtime\\) — 이 빌드를 돌리는 파이썬의 본체(sys.base_prefix)를 복사한다. 테스트·문서·tcl 은 뺀다.
     패키지는 --site-packages 에서 복사하되 빌드 전용·웹 매크로 전용(playwright, 100MB 넘음)은 뺀다.
     ⚠ 패키지를 가져오는 site-packages 와 이 파이썬은 같은 버전(예: 3.10)이어야 한다 — 확인하고 다르면 멈춘다.
  3. 1+2 를 payload.zip 으로 → install_main.py 와 함께 PyInstaller 한 파일 exe(창 모드)로.
결과: installer\\dist\\WorkKitSetup-<VERSION>.exe  (git 에 넣지 않는다)
웹 매크로(playwright)가 필요한 회사는 설치 뒤:  runtime\\python.exe -m pip install playwright
"""
import argparse
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
BUILD = os.path.join(HERE, 'build')
DIST = os.path.join(HERE, 'dist')
ICON = os.path.join(ROOT, 'tools', 'macro-hub', 'web', 'app.ico')

# 내장 파이썬 본체에서 뺄 것(용량만 크고 키트가 안 쓴다)
SKIP_TOP = {'Doc', 'Tools', 'include', 'libs', 'tcl', 'Scripts', 'NEWS.txt'}
SKIP_LIB = {'site-packages', 'test', 'idlelib', 'tkinter', 'turtledemo', 'lib2to3', 'ensurepip', 'unittest\\test',
            'distutils\\tests', '__pycache__'}
# site-packages 에서 뺄 것 — 빌드 도구 · 웹 매크로(playwright 와 그 의존) · 문서
SKIP_PKG = re.compile(r'^(playwright|greenlet|pyee|pyinstaller|PyInstaller|_pyinstaller_hooks_contrib|altgraph|pefile|'
                      r'pywin32_ctypes|win32ctypes|PyWin32\.chm|__pycache__)', re.I)


def log(*a):
    print(*a, flush=True)


def version():
    with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
        return f.read().strip()


def check_clean():
    st = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, capture_output=True,
                        text=True).stdout.strip()
    if st:
        log('⚠ 커밋 안 한 변경이 있습니다 — 설치 파일에는 커밋된 내용만 들어갑니다:\n' + st)


def kit_files(zf):
    """git archive HEAD 를 그대로 zip 에 담는다(installer\\ 자신은 뺀다)."""
    raw = subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=ROOT, capture_output=True, check=True).stdout
    n = 0
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for m in tar.getmembers():
            if not m.isfile() or m.name.startswith('installer/'):
                continue
            zf.writestr(m.name, tar.extractfile(m).read())
            n += 1
    return n


def _skip_lib(rel):
    parts = rel.replace('/', '\\').split('\\')
    return any(p in SKIP_LIB for p in parts) or any(rel.replace('/', '\\').startswith(s) for s in SKIP_LIB if '\\' in s)


def runtime_files(zf, site_packages):
    base = sys.base_prefix
    n = 0
    for name in os.listdir(base):
        src = os.path.join(base, name)
        if name in SKIP_TOP:
            continue
        if os.path.isfile(src):
            if name.lower().endswith(('.exe', '.dll', '.txt')) and not name.lower().startswith(('unins',)):
                zf.write(src, 'runtime/' + name)
                n += 1
            continue
        for dirpath, dirnames, files in os.walk(src):
            rel_dir = os.path.relpath(dirpath, base)
            inner = os.path.relpath(dirpath, os.path.join(base, 'Lib')) if name == 'Lib' else ''
            if name == 'Lib' and inner != '.' and _skip_lib(inner):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for f in files:
                if f.endswith(('.pyc', '.pyo')):
                    continue
                zf.write(os.path.join(dirpath, f), 'runtime/' + os.path.join(rel_dir, f).replace('\\', '/'))
                n += 1
    m = 0
    for name in sorted(os.listdir(site_packages)):
        if SKIP_PKG.match(name):
            continue
        src = os.path.join(site_packages, name)
        dst = 'runtime/Lib/site-packages/' + name
        if os.path.isfile(src):
            zf.write(src, dst)
            m += 1
            continue
        for dirpath, dirnames, files in os.walk(src):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for f in files:
                if f.endswith(('.pyc', '.pyo')):
                    continue
                full = os.path.join(dirpath, f)
                zf.write(full, dst + '/' + os.path.relpath(full, src).replace('\\', '/'))
                m += 1
    return n, m


def check_versions(site_packages):
    want = 'python%d%d' % sys.version_info[:2]
    hits = glob.glob(os.path.join(site_packages, '*', '*.cp%d%d-*.pyd' % sys.version_info[:2]))
    other = [p for p in glob.glob(os.path.join(site_packages, '*', '*.cp3*-*.pyd')) if p not in hits]
    if other and not hits:
        sys.exit('site-packages 의 패키지가 이 파이썬(%s)과 버전이 다릅니다: %s' % (want, other[0]))
    if not os.path.isdir(os.path.join(site_packages, 'pystray')):
        sys.exit('site-packages 에 pystray 가 없습니다 — 허브 트레이 앱에 필요합니다: %s' % site_packages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-packages', required=True, help='pystray·Pillow·pywinauto 가 깔린 site-packages')
    ap.add_argument('--keep-build', action='store_true')
    args = ap.parse_args()
    sp = os.path.abspath(args.site_packages)
    check_versions(sp)
    check_clean()
    ver = version()
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD)
    payload = os.path.join(BUILD, 'payload.zip')
    log('payload.zip 만드는 중…')
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        k = kit_files(zf)
        r, p = runtime_files(zf, sp)
    log('  키트 %d개 · 파이썬 %d개 · 패키지 %d개 → %.1f MB' % (k, r, p, os.path.getsize(payload) / 1048576))
    shutil.copy(ICON, os.path.join(BUILD, 'app.ico'))
    name = 'WorkKitSetup-%s' % ver
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed', '--name', name,
           '--icon', ICON, '--add-data', payload + os.pathsep + '.', '--add-data', os.path.join(BUILD, 'app.ico') + os.pathsep + '.',
           '--distpath', DIST, '--workpath', os.path.join(BUILD, 'pyi'), '--specpath', BUILD,
           os.path.join(HERE, 'install_main.py')]
    log('PyInstaller 로 묶는 중…')
    subprocess.run(cmd, check=True)
    out = os.path.join(DIST, name + '.exe')
    log('만들었습니다: %s (%.1f MB)' % (out, os.path.getsize(out) / 1048576))
    if not args.keep_build:
        shutil.rmtree(os.path.join(BUILD, 'pyi'), ignore_errors=True)


if __name__ == '__main__':
    main()
