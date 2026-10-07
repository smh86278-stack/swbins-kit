# -*- coding: utf-8 -*-
"""WorkKit.exe 만들기 — 앱 아이콘(web\\app.ico)을 그리고 launcher.py 를 PyInstaller 로 한 파일 exe 로 묶는다.

    build_exe.bat          (= .venv\\Scripts\\python.exe build_exe.py)
    WorkKit.exe --install 바로가기·로그온 자동 시작 등록

exe 는 입구·감시자만 맡는 작은 실행 파일이다(표준 라이브러리만). 트레이 앱·매크로는 여전히 .venv 의 Python 으로 돈다 —
그래서 exe 는 이 폴더(tools\\macro-hub) 안에 있어야 한다. 빌드 결과(WorkKit.exe)와 중간 파일은 git 에 넣지 않는다.
PyInstaller 는 .venv 에 따로 설치한다: .venv\\Scripts\\python.exe -m pip install pyinstaller
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ICO = os.path.join(HERE, 'web', 'app.ico')
WORK = os.path.join(HERE, 'data.local', 'build')


def make_icon():
    """트레이의 직접 그린 강아지(상태 점 없이)를 여러 크기로 담은 .ico."""
    sys.path.insert(0, HERE)
    from PIL import Image
    import app                                          # draw_dog_icon — 트레이 아이콘과 같은 그림
    big = app.draw_dog_icon('ok', dot=False, size=256)
    big.save(ICO, format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('아이콘:', ICO)


def build():
    os.makedirs(WORK, exist_ok=True)
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--noconsole',
           '--name', 'WorkKit', '--icon', ICO, '--distpath', HERE, '--workpath', WORK, '--specpath', WORK,
           os.path.join(HERE, 'launcher.py')]
    print(' '.join(cmd))
    subprocess.check_call(cmd, cwd=HERE)
    print('만들었습니다:', os.path.join(HERE, 'WorkKit.exe'))


if __name__ == '__main__':
    make_icon()
    exe = os.path.join(HERE, 'WorkKit.exe')
    if os.path.exists(exe):
        try:
            os.replace(exe, exe + '.old')                 # 돌고 있는 exe 는 덮어쓸 수 없어도 이름은 바꿀 수 있다
        except OSError:
            pass
    build()
    shutil.rmtree(WORK, ignore_errors=True)
