# -*- coding: utf-8 -*-
"""DispatchChat.exe 만들기 — 다른 PC 에 복사해 쓰는 디스패치 대화 앱(허브 없이 혼자 돈다).

    ..\\macro-hub\\.venv\\Scripts\\python.exe build.py      (PyInstaller 는 허브 .venv 에 있다 — 아니면 pip install pyinstaller)

결과: 윈도우 dist\\DispatchChat.exe 한 파일 · 맥 dist/DispatchChat.app. 더블클릭 → 처음엔 메일 계정을 묻고 → 앱 창으로 열린다.
설정은 윈도우 %APPDATA%\\DispatchChat\\config.json(비밀번호 DPAPI), 맥 ~/Library/Application Support/DispatchChat(비밀번호 키체인).
맥에서 서명 안 된 앱이라 처음 한 번은 Finder 에서 우클릭 → 열기.
빌드 결과(dist·build)는 git 에 넣지 않는다.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "build")
ICO = os.path.join(HERE, "..", "macro-hub", "web", "app.ico")
# 펫 코드·그림 — 허브의 web\(pets.js·pets.css, 인형 그림은 skins\plush). 있는 것만 exe 안 pet\(그림은 pet\skin\plush)으로 묶는다.
# 인형 그림이 없으면 화면에 펫 칸이 뜨지 않을 뿐 앱은 그대로 돈다.
PET = os.path.join(HERE, "..", "macro-hub", "web")
PET_PLUSH = os.path.join(PET, "skins", "plush")
COMPANY = os.path.join(HERE, "company.json")              # 회사 값(견본 company.example.json 을 복사해 채운 것, git 제외) — 있으면 같이 묶는다


def main():
    if sys.platform == "darwin":
        # 맥은 DispatchChat.app 폴더(앱 묶음)로 만든다. 아이콘 .ico 는 Pillow 가 있어야 바꿔 넣을 수 있다
        try:
            import PIL  # noqa: F401
            look = ["--windowed", "--icon", ICO]
        except ImportError:
            look = ["--windowed"]
    else:
        look = ["--onefile", "--noconsole", "--icon", ICO]
    pets = [os.path.join(PET, f) for f in ("pets.js", "petwarp.js", "pets.css") if os.path.isfile(os.path.join(PET, f))]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", *look,
           "--name", "DispatchChat",
           "--add-data", os.path.join(HERE, "ui.html") + os.pathsep + ".",
           "--add-data", os.path.join(HERE, "chat-protocol.md") + os.pathsep + ".",   # 이 PC 에서 직접 실행할 때 claude 에 덧붙이는 대화 규칙
           *[x for f in pets for x in ("--add-data", f + os.pathsep + "pet")],
           *(["--add-data", PET_PLUSH + os.pathsep + os.path.join("pet", "skin", "plush")] if os.path.isdir(PET_PLUSH) else []),
           *(["--add-data", COMPANY + os.pathsep + "."] if os.path.isfile(COMPANY) else []),
           "--distpath", os.path.join(HERE, "dist"), "--workpath", WORK, "--specpath", WORK,
           os.path.join(HERE, "chat.py")]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)
    shutil.rmtree(WORK, ignore_errors=True)
    print("만들었습니다:", os.path.join(HERE, "dist", "DispatchChat.app" if sys.platform == "darwin" else "DispatchChat.exe"))


if __name__ == "__main__":
    main()
