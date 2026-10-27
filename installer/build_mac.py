# -*- coding: utf-8 -*-
"""맥 Taskhand.app 만들기 → installer/dist/Taskhand-mac.zip

    python installer/build_mac.py            (맥에서 — ad-hoc 서명까지. CI: .github/workflows/test.yml mac-app)
    python installer/build_mac.py --no-sign  (윈도우에서 모양만 볼 때)

.app 은 얇은 실행기다 — 파이썬을 담지 않는다(맥에 python.org 파이썬 3.10+ 이 있어야 한다).
  Contents/MacOS/Taskhand        셸: 파이썬 3.10+ 을 찾아 mac_launch.py 를 부른다(없으면 python.org 안내)
  Contents/Resources/kit/        키트 파일 — git 에 커밋된 것만(git archive HEAD, installer\\ 는 뺀다)
처음 열면 키트를 ~/Library/Application Support/Taskhand/kit 로 옮기고 .venv(Playwright)를 만든 뒤 허브를 띄운다
(tools/macro-hub/mac_launch.py). 서명·공증이 없어 처음엔 우클릭 → 열기 를 한 번 해야 한다.
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DIST = os.path.join(HERE, 'dist')
ICON = os.path.join(ROOT, 'tools', 'macro-hub', 'web', 'app.ico')
APP = 'Taskhand'
BUNDLE_ID = 'io.github.taskhand'

LAUNCHER = r'''#!/bin/sh
# Taskhand.app — 파이썬 3.10+ 을 찾아 키트의 mac_launch.py 를 부른다. Finder 로 켜면 PATH 가 짧아 흔한 위치를 직접 본다.
CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$CONTENTS/Resources/kit"
for c in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3)" /usr/bin/python3; do
  [ -x "$c" ] || continue
  if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    exec "$c" "$SRC/tools/macro-hub/mac_launch.py" --src "$SRC" "$@"
  fi
done
ans=$(osascript -e 'display dialog "Taskhand 를 쓰려면 Python 3.10 이상이 필요합니다.\n\npython.org 에서 macOS 용 설치 파일을 받아 설치한 뒤 다시 열어 주세요." buttons {"닫기", "python.org 열기"} default button 2 with title "Taskhand"' 2>/dev/null)
case "$ans" in *python.org*) open "https://www.python.org/downloads/macos/" ;; esac
exit 1
'''

PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{app}</string>
  <key>CFBundleDisplayName</key><string>{app}</string>
  <key>CFBundleIdentifier</key><string>{bid}</string>
  <key>CFBundleExecutable</key><string>{app}</string>
  <key>CFBundleIconFile</key><string>app.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{ver}</string>
  <key>CFBundleVersion</key><string>{ver}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
'''


def version():
    with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
        return f.read().strip()


def kit_files(dest):
    """git archive HEAD → dest (installer\\ 와 .github\\ 는 뺀다). 실행 비트(.sh·.command)는 살린다."""
    raw = subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=ROOT, capture_output=True, check=True).stdout
    n = 0
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for m in tar.getmembers():
            if not m.isfile() or m.name.startswith(('installer/', '.github/')):
                continue
            out = os.path.join(dest, *m.name.split('/'))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, 'wb') as f:
                f.write(tar.extractfile(m).read())
            os.chmod(out, 0o755 if m.name.endswith(('.sh', '.command')) else 0o644)
            n += 1
    return n


def icns(out):
    try:
        from PIL import Image
        Image.open(ICON).save(out, format='ICNS')
        return True
    except Exception as e:                       # Pillow 가 없거나 ICNS 를 못 쓰면 기본 아이콘으로
        print('아이콘 건너뜀:', e)
        return False


def zip_app(app_dir, zpath):
    """서명은 확장 속성까지 담아야 해서 맥은 ditto 로. 그 밖은 zipfile 로(실행 비트만 살린다)."""
    if sys.platform == 'darwin':
        subprocess.run(['ditto', '-c', '-k', '--keepParent', app_dir, zpath], check=True)
        return
    base = os.path.dirname(app_dir)
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(app_dir):
            for f in files:
                p = os.path.join(root, f)
                info = zipfile.ZipInfo(os.path.relpath(p, base).replace(os.sep, '/'))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = ((0o755 if os.stat(p).st_mode & 0o111 or f == APP else 0o644) | 0o100000) << 16
                with open(p, 'rb') as fh:
                    zf.writestr(info, fh.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-sign', action='store_true', help='ad-hoc 서명 건너뛰기(맥이 아니면 늘 건너뛴다)')
    a = ap.parse_args()
    ver = version()
    app_dir = os.path.join(DIST, APP + '.app')
    shutil.rmtree(app_dir, ignore_errors=True)
    contents = os.path.join(app_dir, 'Contents')
    os.makedirs(os.path.join(contents, 'MacOS'))
    os.makedirs(os.path.join(contents, 'Resources'))
    n = kit_files(os.path.join(contents, 'Resources', 'kit'))
    exe = os.path.join(contents, 'MacOS', APP)
    with open(exe, 'w', encoding='utf-8', newline='\n') as f:
        f.write(LAUNCHER)
    os.chmod(exe, 0o755)
    with open(os.path.join(contents, 'Info.plist'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(PLIST.format(app=APP, bid=BUNDLE_ID, ver=ver))
    icns(os.path.join(contents, 'Resources', 'app.icns'))
    if sys.platform == 'darwin' and not a.no_sign:
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', app_dir], check=True)
    zpath = os.path.join(DIST, '%s-mac.zip' % APP)
    if os.path.exists(zpath):
        os.remove(zpath)
    zip_app(app_dir, zpath)
    print('만들었습니다: %s (키트 파일 %d개, 버전 %s)' % (zpath, n, ver))


if __name__ == '__main__':
    main()
