# 업무 자동화 키트 — 개발 규칙

어느 회사에서나 쓰는 범용 키트다. 사용 설명은 `README.md`, 허브 내부는 `tools\macro-hub\README.md`.

## 설정 계약

- 회사·사람마다 다른 값은 **전부 `config.local.json`** 에 둔다(견본 `config.example.json`, 처음 설정 `python setup.py`).
  읽기는 `tools\macro-hub\kit.py` 로만 — `kit.load_config()` · `kit.section('monitors', 기본값)` · `kit.mail_config()` ·
  `kit.mail_ready()` · `kit.company_name()`. 새 갈래를 추가하면 `config.example.json` 에 견본과 `_설명` 을 함께 넣는다.
- 메일은 `kit.send_mail` · `kit.append_inbox` · `kit.alert` 만 쓴다. 비밀번호는 `kit.protect`(DPAPI) 로 암호화한 `password_enc` 만 저장한다.
- 기능 매크로(`macros\job_*.py`)는 결과를 `kit.write_status(기능, items)` 로 남긴다 — 운영 화면 「📊 기능 상태」가 읽는다.
  기능 목록은 `ops.FEATURES`.
- `kit.py` 의 기존 함수 이름·인자는 바꾸지 않는다(허브·매크로·게이트웨이가 함께 쓴다). 표준 라이브러리만.

## 하지 말 것

- **회사 이름·도메인·사내 주소·개인 경로·계정을 코드·문서·테스트에 박지 않는다.** 예시는 `example.com`, 경로는 `%USERPROFILE%`
  또는 저장소 기준 상대 경로(`kit.ROOT`). 견본 값도 `config.example.json` 에만.
- `config.local.json` · `*.local.json` · `data.local\` · `macros.local\` 커밋 금지(`.gitignore`). `git add -A` 대신 손댄 파일만 지정한다.
- **허브(8630)를 `127.0.0.1` 밖으로 열지 않는다** — 프로그램을 띄우고 매크로를 돌리는 화면이라 LAN·`0.0.0.0` 바인딩은 원격 실행 구멍이다.
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
