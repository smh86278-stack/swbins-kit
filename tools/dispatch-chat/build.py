# -*- coding: utf-8 -*-
"""DispatchChat.exe 만들기 — 다른 PC 에 복사해 쓰는 디스패치 대화 앱(허브 없이 혼자 돈다).

    ..\\macro-hub\\.venv\\Scripts\\python.exe build.py      (PyInstaller 는 허브 .venv 에 있다)

결과: dist\\DispatchChat.exe 한 파일. 다른 PC 에서 더블클릭 → 처음엔 메일 계정을 묻고 → Edge 앱 창으로 열린다.
설정은 그 PC 의 %APPDATA%\\DispatchChat\\config.json(비밀번호는 그 PC 사용자 DPAPI), 로그는 %LOCALAPPDATA%\\DispatchChat.
빌드 결과(dist·build)는 git 에 넣지 않는다.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "build")
ICO = os.path.join(HERE, "..", "macro-hub", "web", "app.ico")


def main():
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
           "--name", "DispatchChat", "--icon", ICO,
           "--add-data", os.path.join(HERE, "ui.html") + os.pathsep + ".",
           "--distpath", os.path.join(HERE, "dist"), "--workpath", WORK, "--specpath", WORK,
           os.path.join(HERE, "chat.py")]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)
    shutil.rmtree(WORK, ignore_errors=True)
    print("만들었습니다:", os.path.join(HERE, "dist", "DispatchChat.exe"))


if __name__ == "__main__":
    main()
