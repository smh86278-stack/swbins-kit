# 업무 자동화 키트

회사 PC 한 대에서 **반복 업무를 대신 돌려 주는 도구 모음**이다. 어느 회사에서나 쓰도록 회사마다 다른 값
(메일 계정·받는 사람·감시할 주소·백업 폴더)은 전부 `config.local.json` **한 파일**에 둔다.
가운데에는 **매크로 허브**(트레이 상주 앱, 이 PC 에서만 열리는 웹 화면 <http://127.0.0.1:8630/>)가 있고,
기능은 허브가 정해진 시각에 돌리는 예약 작업이다. 작업 스케줄러를 쓰지 않는다.

Windows 10/11 · Python 3.10+ · 관리자 권한 불필요.

## 기능

| 기능 | 하는 일 | 설정 (`config.local.json`) |
|---|---|---|
| 📮 정기 메일 | 정한 요일·시각에 정해진 메일(첨부 포함)을 보낸다 — 주간 보고·월말 안내 등. 제목·본문에 `{date}` `{prev_month}` `{company}` 같은 자리표시 | `scheduled_mails` |
| 🗂 폴더 정리 | 다운로드 같은 폴더에서 오래된 파일을 보관 폴더(`YYYY-MM`)로 옮긴다. 지우지 않는다 | `tidy` |
| 🌐 사이트·서버 감시 | 웹 주소·서버 포트를 몇 분마다 확인하고, 내려가면/돌아오면/인증서가 곧 끝나면 메일로 알린다 | `monitors` |
| 💽 PC 디스크 감시 | 드라이브 남은 공간이 기준 밑으로 내려가면 알린다 | `pc_watch` |
| 💾 폴더 백업 | 폴더를 정한 시각에 날짜별 폴더로 복사하고, 오래된 백업은 정리한다 | `backups` |
| 🔔 실패 알림 메일 | 위 작업이 실패하면 나에게 메일로 알린다(같은 작업은 60분에 한 번) | `mail.alert_to` · `mail.alert_via` |
| 🔗 바로가기 | 자주 여는 사내 사이트를 트레이 메뉴에 | `links` |
| 🤖 매크로 | 웹(Playwright)·윈도우 프로그램(pywinauto) 화면 조작을 파이썬 매크로로 — 녹화·요소 찍기·자동 실행 트리거 | `tools\macro-hub\macros.local\` |

운영 화면 <http://127.0.0.1:8630/ops> 에서 기능마다 켜고 끄고, 시각을 바꾸고, 「📊 기능 상태」 탭에서 마지막 결과를 본다.
기능은 **처음엔 모두 꺼져 있다** — 설정에 대상을 적은 뒤 켠다.

### 고급 — 메일로 AI 에게 일 맡기기 (디스패치, 기본 꺼짐)

정해진 태그를 단 메일을 받으면 이 PC 의 Claude Code 가 그 일을 하고 결과를 메일로 답한다(`config.local.json` 의 `dispatch`).
Claude Code 가 깔려 있어야 하고, **`dispatch.enabled` 를 직접 켜야만** 동작한다.

> ⚠ **보안 경고 — 메일 한 통으로 이 PC 에서 명령이 실행되는 통로다.**
> 보낸 사람 주소는 위조할 수 있다. 켜기 전에 `allowed_senders` 를 본인 주소로만 좁히고, 작업 폴더(`default_workdir` · `workdir_keys`)를
> 업무에 필요한 곳으로 한정하고, 회사 보안 담당자와 먼저 상의할 것. 쓰지 않을 때는 끈다. 확실하지 않으면 켜지 않는다.

## 설치 — 파일 하나 (권장)

`WorkKitSetup-<버전>.exe` 를 실행하고 「설치」를 누르면 끝이다. **파이썬·인터넷이 없는 PC 에도 된다**(내장 파이썬을 함께 깐다).

- 관리자 권한이 필요 없다 — 내 계정 폴더(`%LOCALAPPDATA%\WorkKit`)에 깔린다.
- 시작 메뉴 「업무 자동화 키트」(허브 열기) · 「메일·계정 설정」(설정 창, `setup_gui.py`) · 「업무 자동화 키트 제거」, 바탕화면 바로가기, 로그온 자동 시작이 생긴다.
- 처음 설치하면 「메일·계정 설정」 창이 이어서 뜬다(회사 이름·메일 서비스·주소·비밀번호 → 저장 → 시험 메일 보내기). 허브는 <http://127.0.0.1:8630/> (이 PC 에서만).
- **다시 설치하면 업데이트**다 — 설정·기록은 그대로 남는다.
- 제거는 '설정 → 앱 → 설치된 앱' 또는 시작 메뉴의 「제거」. 설정을 남기면 다음 설치 때 되살아난다.
- IT 담당자 일괄 배포: `WorkKitSetup-<버전>.exe /S` (무인 설치, 폴더 지정은 `/D=D:\WorkKit`).
- 서명되지 않은 exe 라 처음 실행 때 Windows SmartScreen 이 경고할 수 있다 — 「추가 정보 → 실행」.
- 웹 매크로(playwright)는 용량이 커서 기본으로 넣지 않는다. 필요하면 설치 폴더에서 `runtime\python.exe -m pip install playwright`.

설치 파일 만들기(개발 PC): `installer\build_installer.py` 맨 위 설명 참고 → `installer\dist\WorkKitSetup-<버전>.exe`.

## 5분 시작 — 소스로 직접 (개발용)

1. **Python 3.10 이상 설치** — <https://www.python.org/downloads/> (설치 화면에서 "Add python.exe to PATH" 체크).
   명령 창에서 `python --version` 이 나오면 된다.
2. **처음 설정** — 이 폴더에서
   ```
   python setup.py
   ```
   회사 이름 · 메일 주소 · 메일 서버(Gmail / Microsoft 365 / 네이버 등 미리 채움, 또는 직접 입력) · 비밀번호 · 알림 받을 곳을 묻는다.
   끝에 알림 시험 메일을 한 통 보내 볼 수 있다(`python setup.py --test` 로 언제든 다시). 지금 설정 보기는 `python setup.py --show`.
3. **허브 실행 환경** — `tools\macro-hub\setup.bat` (처음 한 번. 매크로용 패키지를 `.venv` 에 설치).
4. **허브 시작** — `tools\macro-hub\start_app.bat` → 트레이에 강아지 아이콘이 뜨고 허브 화면이 열린다.
   로그온할 때 자동으로 뜨게 하려면 트레이 메뉴 ⚙ 설정 → 로그온 시 자동 시작.
5. **기능 켜기** — `config.local.json` 에 대상(받는 사람·주소·폴더)을 적고, 운영 화면 「⏰ 예약 작업」에서 스위치를 켠다.
   「지금 실행」으로 바로 시험해 볼 수 있다.

> Gmail·네이버처럼 2단계 인증을 쓰는 메일은 계정 비밀번호 대신 **앱 비밀번호**를 넣어야 한다.
> 회사 메일은 관리자가 IMAP/SMTP 사용을 허용해야 하는 경우가 많다.

## 보안

- **허브는 `127.0.0.1` 에만 열린다.** 허브는 프로그램을 띄우고 매크로를 돌리는 화면이라, 같은 망에 열면 원격 실행 구멍이 된다 —
  `0.0.0.0`·LAN 으로 바인딩하거나 포트를 터 주지 말 것. 실행 요청에는 허브가 시작할 때마다 새로 만드는 토큰이 필요하다.
- **비밀번호는 Windows DPAPI 로 암호화**해 `password_enc` 로만 저장한다. 이 PC·이 Windows 사용자만 풀 수 있다
  (PC 를 옮기면 `python setup.py` 로 다시 넣는다).
- **`config.local.json` 은 절대 커밋하지 않는다** — `.gitignore` 에 들어 있다. 견본은 `config.example.json`.
  매크로가 쓰는 계정은 `tools\macro-hub\secrets.local.json`(역시 커밋 안 함), 실행 기록·상태는 `tools\macro-hub\data.local\`.
- 매크로는 임의의 파이썬 코드다 — 남이 준 매크로는 열어 보고 돌린다.

## 구조

```
setup_gui.py             메일·계정 설정 창 (보통은 이것 — 시작 메뉴·트레이에서 연다)
setup.py                 같은 설정을 명령 창으로 (--test 시험 메일 · --show 설정 보기)
config.example.json      설정 견본 — 갈래별 설명은 이 파일 안 "_설명"
config.local.json        이 PC 의 실제 설정 (git 제외, setup.py 가 만든다)
tools\macro-hub\         매크로 허브 — 트레이 앱 · 웹 화면 · 예약 작업 · 상시 서비스 (자세히: tools\macro-hub\README.md)
    kit.py               공통 바탕 — 설정 · 메일 · DPAPI · 예약 시각 판정 · 기능 상태 파일
    macros\job_*.py      기능 (정기 메일 · 폴더 정리 · 감시 · PC 점검 · 백업)
    macros.local\        내가 만든 매크로 (git 제외)
tools\proc-live\         허브의 내부 모듈(프로세스 스냅샷)
tests\                   python -m unittest discover -s tests · 커밋 전 tests\verify.ps1
```

## 문제가 생기면

- 운영 화면 「⚙ 설정」 — 메일 설정이 준비됐는지, 설정 파일이 어디 있는지.
- 운영 화면 「📊 기능 상태」 — 기능별 마지막 결과. 「⏰ 예약 작업」 — 마지막 실행의 성공/실패와 로그.
- 허브 로그 `tools\macro-hub\data.local\app.log` · 알림 메일 기록 `data.local\alertmail.log`.
