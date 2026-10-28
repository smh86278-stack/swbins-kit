# Taskhand(업무 자동화, 옛 이름 「업무 자동화 키트·WorkKit」) — 개발 규칙

보이는 이름은 「Taskhand」(2026-10-26). 설치 폴더·레지스트리 APP_ID·`WorkKit.exe`·뮤텍스 같은 내부 이름은 기존 설치와 이어지게 그대로 — 바꾸지 말 것.
옛 이름 바로가기는 설치·제거가 OLD_NAMES 로 지운다(installer\install_main.py · uninstall.py).

어느 회사에서나 쓰는 범용 키트다. 사용 설명은 `README.md`, 허브 내부는 `tools\macro-hub\README.md`.

## 설정 계약

- 회사·사람마다 다른 값은 **전부 `config.local.json`** 에 둔다(견본 `config.example.json`, 처음 설정 `python setup.py`).
  읽기는 `tools\macro-hub\kit.py` 로만 — `kit.load_config()` · `kit.section('monitors', 기본값)` · `kit.mail_config()` ·
  `kit.mail_ready()` · `kit.company_name()`. 새 갈래를 추가하면 `config.example.json` 에 견본과 `_설명` 을 함께 넣는다.
- 메일은 `kit.send_mail` · `kit.append_inbox` · `kit.alert` 만 쓴다. 비밀번호는 `kit.protect`(DPAPI) 로 암호화한 `password_enc` 만 저장한다.
- 기능 자동화(`macros\job_*.py`)는 결과를 `kit.write_status(기능, items)` 로 남긴다 — 운영 화면 「📊 기능 상태」가 읽는다.
  기능 목록은 `ops.FEATURES`.
- `kit.py` 의 기존 함수 이름·인자는 바꾸지 않는다(허브·자동화·게이트웨이가 함께 쓴다). 표준 라이브러리만.

## 맥 (일부 기능 — README 「맥에서 쓰기」)

- 윈도우·맥 차이는 **`tools\macro-hub\plat.py` 한곳에서** — Popen 은 `**plat.bg()`(creationflags 를 직접 쓰면 맥에서 ValueError),
  끄기는 `plat.kill_tree`, 폴더 열기 `plat.open_path`·`plat.reveal`, 중복 실행 `plat.single_instance`. `taskkill`·`os.startfile`·
  `ctypes.windll` 을 새로 쓰지 말 것. 윈도우 전용 모듈은 모듈 맨 위에서 import 하지 않는다(맥에서 허브가 뜨자마자 죽는다).
- 비밀값은 맥에서 키체인(`keychain:<id>`) — `kit.protect`·`hubutil.seal` 이 알아서 고른다.
- 윈도우 전용 자동화는 META `"windows_only": True`(맥 목록에서 빠짐), 화면 요소는 `data-winonly`(`<html data-os="mac">` 이면 숨김).
- 맥 앱 `installer\build_mac.py` → `Taskhand-mac.zip`(실행기는 `tools\macro-hub\mac_launch.py`). 이 PC 에 맥이 없다 —
  시험은 CI `verify-mac`·`mac-app` 잡으로 본다.

## 하지 말 것

- **회사 이름·도메인·사내 주소·개인 경로·계정을 코드·문서·테스트에 박지 않는다.** 예시는 `example.com`, 경로는 `%USERPROFILE%`
  또는 저장소 기준 상대 경로(`kit.ROOT`). 견본 값도 `config.example.json` 에만.
- `config.local.json` · `*.local.json` · `data.local\` · `macros.local\` 커밋 금지(`.gitignore`). `git add -A` 대신 손댄 파일만 지정한다.
- **허브(8630)를 `127.0.0.1` 밖으로 열지 않는다** — 프로그램을 띄우고 자동화를 돌리는 화면이라 LAN·`0.0.0.0` 바인딩은 원격 실행 구멍이다.
  실행 요청 토큰은 허브가 시작할 때마다 새로 만들어 화면에만 심는다 — 파일로 남기지 않는다.
- 디스패치(메일 → Claude Code)는 기본 꺼짐을 유지한다. 켜는 기본값으로 바꾸지 않는다.
- 작업 스케줄러 작업을 만들지 않는다 — 예약은 허브의 `job_*` 가 맡는다.

## 검증

```
python -X utf8 -m unittest discover -s tests          단위 테스트 (네트워크·실제 메일 없음)
powershell -ExecutionPolicy Bypass -File tests\verify.ps1   커밋 전 — py_compile 전부 + unittest
```

- 테스트는 허브를 띄우지 않고 메일을 보내지 않는다. 메일 경로는 `send=`·`ready=` 같은 인자나 monkeypatch 로 막는다.
- 한글이 든 `.ps1` 은 **UTF-8 BOM 필수**(PS 5.1 은 BOM 이 없으면 CP949 로 읽어 문자열이 깨진다).
- 큰 HTML·JSON 은 셸 heredoc 말고 편집 도구로 쓴다(따옴표가 뭉개진다).

## 설치 파일 · 릴리스

```
1. VERSION 을 새 버전으로 고쳐 커밋 (빌드는 git archive HEAD — 커밋 안 한 것은 빠진다)
2. 설치 시험: installer\dist\TaskhandSetup-<버전>.exe /S → runtime\pythonw.exe tools\macro-hub\launcher.py --background → 8630 확인 → runtime\python.exe uninstall.py --yes
   (Git Bash 는 /S 를 경로로 바꾼다 — PowerShell Start-Process 로. 남는 %LOCALAPPDATA%\WorkKit-설정백업 은 시험 로그뿐이면 지운다)
3. <PyInstaller 있는 파이썬> installer\release.py v<버전> notes.md   빌드 → main push → 그 커밋 CI 통과 기다림(실패면 멈춤)
   → CI 아티팩트에서 맥 앱 받기 → 태그 push → GitHub 릴리스 + TaskhandSetup-<버전>.exe · Taskhand-<버전>-mac.zip 첨부 → dist 엔 최신 하나씩만
   (맥 없이 올리려면 --no-mac)
```
