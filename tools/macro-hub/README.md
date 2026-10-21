# macro-hub — 업무 화면 처리 자동화 허브

회사 업무 화면(웹·윈도우 프로그램)을 조작하는 자동화를 한곳에서 만들고, 돌리고, 자동 실행까지 거는 **트레이 상주 앱**.
본인 전용 · Windows · 웹 화면은 이 PC 에서만 열린다.

```
setup.bat          처음 한 번 — .venv 에 Playwright · pywinauto · pystray · Pillow 설치 (브라우저는 설치된 Chrome 을 쓴다)
start_app.bat      트레이 앱 시작 → 웹 화면 http://127.0.0.1:8630/   (이미 떠 있으면 화면만 연다)
start_server.bat   콘솔 모드(디버깅용) — 트레이 없이 허브만, 이 창을 닫으면 끝
```

## 응용프로그램 — `WorkKit.exe`

허브는 이제 보통 프로그램처럼 쓴다. **시작 메뉴·바탕화면의 「자동화 허브」**(강아지 아이콘)를 누르면
허브가 안 떠 있으면 띄우고, 허브 **전용 창**을 연다(브라우저 탭이 아니다).

| 무엇 | 파일 | 하는 일 |
|---|---|---|
| 입구 · 감시자 | `WorkKit.exe` (= `launcher.py`, 표준 라이브러리만) | 트레이 앱(`app.py --child`)을 자식으로 띄우고 **지킨다** — 오류·강제 종료로 죽으면 다시 띄운다(5분 안에 5번 죽으면 멈추고 알림). 트레이 **「종료」로 끝나면 같이 끝난다**. 감시자는 한 번에 하나(`Local\workkit-watch`) — 이미 있으면 창만 연다 |
| 허브 창 | `shell\` (Electron — 화면 펫의 `pet\node_modules` 를 같이 씀) | 「자동화 허브」 창 — 카카오톡 PC 처럼 세로로 긴 창(571×860)에 **왼쪽 아이콘 줄**(🏠 허브 · 🛠 만들기 · 💬 대화 · ⏰ 운영)로 화면을 오가고, 화면마다 살려 두어 돌아와도 그대로. 💬 는 디스패치 대화(8620)가 떠 있을 때만 보인다. 아이콘을 **끌어 순서 바꾸기**, **창 밖에 놓거나 우클릭 「새 창으로 떼어 내기」** 로 따로 창, 떼어 낸 창은 닫거나 **제목 표시줄을 잡고 아이콘 줄 위에 끌어 놓으면** 다시 붙는다(올라가면 줄이 밝아지고 창이 흐려짐). **닫기(X)는 숨기기** — 트레이 「자동화 허브 열기」로 보던 화면 그대로 바로 뜬다(창 프로세스가 150MB 안팎을 계속 씀), 완전히 끄는 건 트레이 「종료」. 한 번에 하나, 허브·대화 밖 주소는 기본 브라우저로. 크기·위치·아이콘 순서는 `shell\window.local.json` |
| 만들기 화면 | `web\index.html` (`/?view=make`) | 「나만의 자동화 만들기」 — 🎬 **보여 주기**(웹 녹화: 주소·이름 → 녹화 시작) · 💬 **말로 부탁하기**(할 일·언제를 적고 누르면 디스패치 대화가 켜져 있을 때 `POST /api/ask` → `macrohub.ask_chat` 이 대화 화면의 그때그때 토큰으로 `/api/send` 에 쓰기 지시로 **바로 보내고** 대화 창을 연다. 대화가 꺼져 있으면 부탁 글만 복사 — Claude Code 에 붙여 넣는다) 두 장만 크게, 빈 자동화 파일(템플릿)·요소 찍기·구조 보기·폴더 열기는 🧰 **고급 도구**에 접어 둔다 |
| 내 자동화 카드 | `web\index.html` · `POST /api/test` | META `steps`(쉬운 말 단계)를 번호 목록으로 보여 주고, **🧪 시험** 단추가 `ctx.for_real()` 로 감싼 동작(보내기·제출·삭제)을 건너뛰고 한 번 돌린다(`runner.py --test` 와 같은 `dry_run`). 기본·상시 자동화는 막고(for_real 을 안 써서 진짜로 닿는다), 시험 실행은 실행 기록·실패 알림 메일·카드의 마지막 결과에 넣지 않는다 |
| 아이콘 | `web\app.ico` | 트레이의 직접 그린 강아지(상태 점 없이), 16~256px |

- `WorkKit.exe` · `--background`(창 없이 — 로그온 자동 시작) · `--page=/ops`(그 화면으로) · `--install`(바로가기 2개 + 로그온 자동 시작을 이 exe 로).
- 만들기: `build_exe.bat` (PyInstaller 한 파일 exe, 약 6MB — `.venv\Scripts\python.exe -m pip install pyinstaller` 가 한 번 필요). exe 는 **이 폴더에 있어야 한다**(트레이 앱·자동화는 여전히 `.venv` Python 으로 돈다). 빌드 결과는 git 에 넣지 않는다.
- 트레이 앱만 다시 띄우려면(코드를 고친 뒤) 트레이 「**허브 다시 시작**」 — 종료 코드 3 으로 끝나 감시자가 바로 다시 띄운다(그 프로세스 `app.py --child` 를 꺼도 3초 안에 다시 뜬다). 허브를 완전히 끄려면 트레이 「종료」.
- 허브가 띄운 서버·워처는 원래 허브와 떨어진 프로세스라 트레이 앱이 다시 떠도 끊기지 않는다(아래 "서버·워처 지키기").

## 트레이 앱 (`app.py`)

- **아이콘** — 초록: 켜 둔 상시 자동화가 모두 동작 중 · 노랑: 시작 중/멈춤/일시정지 · 회색: 켜 둔 게 없음.
  얼굴은 고른 스킨(모습)의 강아지 역할 캐릭터를 따른다(`skinicon.py` — 상태 그림에서 얼굴 쪽을 잘라 밝은 원 위에 얹는다. 정상=alert · 경고=worried · 대기=sleep, 고른 강아지 품종). 고른 스킨이 없으면 기본 `plush`, 영상뿐이면 직접 그린 강아지.
  왼쪽 클릭 = 허브 창. 우클릭 메뉴는 묶음만 보인다:
  자동화 허브 열기 · ⏰ 운영 화면 열기 · 🌐 서버 ▸ · 🔧 도구 ▸ · ⏰ 예약 작업 ▸ · 🔗 바로가기 ▸ · ⚙ 설정 ▸(화면 펫 · 로그온 시 자동 시작 · 실패 알림 메일 · 허브 다시 시작) · 종료.
  🔗 바로가기는 `config.local.json` 의 `"links": [{"label", "url"}]` 에서 온다(비었으면 메뉴가 안 보인다).
  서버(브라우저로 열기 · 재시작 · 상시 실행 · 폴더)와 도구(상태 · 일시정지 · 도구별 명령 · 로그 · 다시 띄우기 · 폴더)는 저장소 맨 위 `services.json` 이 **있을 때만** 보인다(선택 — 없어도 된다).
  트레이 이름에는 설정의 회사 이름(`company.name`)이 붙는다.
  묶음 안에 문제가 있으면 이름 끝에 `(⚠ n)` — 허브가 지키는 서버가 꺼짐 · 도구 멈춤/오류 · 예약 작업 마지막 실행 실패.
- **알림 풍선** — 자동화가 `ctx.notify()` 를 부를 때, 자동 실행된 자동화가 실패할 때, 상시 자동화가 죽었을 때.
- **실패 알림 메일** (`alertmail.py`) — 예약 작업·상시 서비스가 실패하거나 제한 시간을 넘기면 `[자동화 허브] … 실패 — 이름` 메일을 보낸다(마지막 로그 30줄 포함). 직접 누른 실행은 빼고, 같은 자동화는 60분에 한 번만. 보내는 길은 `kit.alert()` — `config.local.json` 의 `mail.alert_via` 가 `smtp` 면 `alert_to`(없으면 내 주소)로 발송, `append` 면 내 INBOX 에 직접 넣는다(자기에게 보낸 메일을 딴 폴더로 치우는 서버용). 메일 설정이 아직 없으면(`python setup.py` 전) 조용히 건너뛰고 로그에 한 번만 남긴다. 켜고 끄기: 트레이 ⚙ 설정 → 실패 알림 메일(`state.local.json` 의 `alert`). 보낸 기록·오류는 `data.local\alertmail.json`·`alertmail.log`. 허브 자체가 죽어 감시자가 포기할 때는 여전히 메시지 상자뿐이다.
  디스패치(`dispatch.enabled`)가 켜져 있으면 알림 메일 맨 위에 **🔍 원인 봐 줘** 단추가 붙는다 — 누르면 읽기 지시(`#c 실패 원인 봐 줘`, 로그 끝 15줄)가 채워진 메일이 열리고, 보내면 Claude 가 원인만 찾아 답한다(고치기는 허브 화면의 🩹 고쳐 달라기). `workdir_keys` 에 키트 폴더를 가리키는 키가 있으면 `@그 키` 로 간다.
- **자동 시작** — HKCU Run `MacroHub` = `WorkKit.exe --background`(감시자째로 뜬다. exe 가 없으면 `launcher.py`). 관리자 권한 불필요.
  `WorkKit.exe --install` 또는 `python app.py --install-autostart` / `--remove-autostart`, 트레이 메뉴에서도 토글.
  로그온하면 허브가 뜨고, 켜 둔 상시 자동화는 `state.local.json` 에 기억돼 있어 자동으로 다시 시작한다.
- **한 번에 하나만** — 뮤텍스로 막는다(이미 떠 있으면 허브 창만 연다).
  트레이 「종료」는 화면 펫과 허브 창도 같이 닫는다. 이전 실행이 비정상 종료돼 남은 `runner.py` 는 시작할 때 정리한다.
- Windows 11 은 새 트레이 아이콘을 `^`(숨겨진 아이콘) 안에 넣는다. 설정 → 개인 설정 → 작업 표시줄 → 기타 시스템 트레이 아이콘에서 켜거나, 아이콘을 끌어다 놓는다.
- 앱 오류·상태 변화는 `data.local\app.log`.

## 화면 펫 (Electron) — `pet\`

화면 구석에 강아지·고양이가 올라앉아 허브 상태를 표정과 몸짓으로 보여 준다. 배경이 투명해서 **그림 위에서만** 마우스가 반응하고 나머지는 아래 창으로 통과한다.

- **켜기/끄기**: 트레이 메뉴 `화면 펫`, 허브 웹 화면 오른쪽 위 `화면 펫 켜기/끄기` 버튼, 또는 `pet\start_pet.bat`. 켜 둔 상태는 기억돼서 다음에 허브가 시작할 때 같이 뜬다. 펫 우클릭 `펫 끄기`도 같은 상태로 기억된다.
- **조작**: 끌어서 옮기기 · 클릭하면 허브 화면 열기 · 우클릭 메뉴(강아지/고양이 보이기, 크기, 스킨, 항상 위) · **펫 위에서 마우스 휠로 크기 조절**(40%~200%).
- **스킨**: 그림을 GIF·WebP·WebM·PNG 시퀀스로 통째로 바꿀 수 있다. 외부에서 받은 스프라이트 팩은 `skin_import.py` 로 한 번에 변환 → `web\skins\README.md`.
  - 허브 화면 위쪽 `모습` 선택칸이나 펫 우클릭 → 모습(스킨) 어느 쪽에서 골라도 **같은 하나의 설정**이다. 허브가 `state.local.json` 에 기억하고(`/api/skin`), 펫·허브 화면이 실시간으로 같이 바뀐다(펫 쪽 `settings.local.json` 에는 스킨을 두지 않는다).
  - **기본 모습은 `plush`(인형 강아지 10종·고양이 8종·판다)** — AI(SDXL)로 직접 만든 그림이라 저장소에 담는다(`.gitignore` 예외, 조건은 `plush\LICENSE.txt`).
    허브 위쪽 🐶·🐱 칸이나 펫 우클릭에서 품종을 고른다. 마우스를 올리면 쓰다듬기(강아지는 짖고, 고양이는 💗), 품종마다 고개 갸웃·앞발 들기 같은 몸짓(`web\petwarp.js`, WebGL).
    옛 내장 SVG 그림과 '기본 그림' 선택지는 없앴다. 직접 가져온 다른 스킨 폴더는 git 에 올라가지 않는다.
- **설치**: `cd pet && npm install` (Electron 약 350MB, 이 폴더 안에만 설치됨). `npx electron . --selftest` 로 자가 점검(점검 뒤 원래 스킨으로 되돌린다).
- 펫 페이지는 허브가 `/pet` 으로 내려 준다 — 그림·표정 로직(`web\pets.js`, `pets.css`)은 허브 화면과 같은 파일을 쓴다.

## 실시간 감지 — 폴링이 아니라 이벤트

- **창**: Windows 창 이벤트(`SetWinEventHook`, `winevents.py`)로 창이 뜨는 순간 깨어난다. 허브의 `window` 트리거가 이걸 쓴다.
  가짜 접속창 시험에서 대화상자 생성 → 입력 완료까지 **17~44ms(평균 25ms)**.
- **프로세스·시간 예약**: 0.5초마다 훑는다(프로세스 시작은 관리자 권한 없이 받을 이벤트가 없다).
- **안전 점검**: 이벤트를 놓칠 수 있으니, 창을 기다리는 상시 자동화는 몇 초마다 한 번 전체를 훑어 두는 것이 좋다.

## 구조

```
launcher.py     입구·감시자 → WorkKit.exe (build_exe.py · build_exe.bat)
shell/          허브 전용 창(Electron)
app.py          트레이 앱 — 허브를 같은 프로세스에서 돌리고 트레이·알림·자동 시작을 맡는다
winevents.py    창 이벤트(SetWinEventHook) 수신
hubutil.py      자동화 공용 도구 — DPAPI 암호화 · TOTP
macrohub.py     허브 본체 — 웹 서버(SSE) · 자동화 목록 · 실행/중지 · 자동 실행 트리거 · 상시 자동화 감독
runner.py       자동화 1개를 .venv 파이썬에서 별도 프로세스로 실행 (ctx 제공). 중지하면 프로세스 트리째 끈다
web/index.html  화면
web/theme.css   공통 테마(파스텔 색·단추·칩·입력) — index.html·ops.html 이 함께 쓴다. 색은 여기 :root 만 고친다(light-dark 한 쌍)
web/theme.js    화면 모드 단추(☀️ 라이트 · 🌙 다크 · 자동=Windows 설정) — 허브가 기억(/api/theme), 열린 화면·전용 창이 같이 바뀐다
web/ops.html    운영 화면(/ops) — 예약 작업 · 상시 서비스 · 기능 상태 · 설정 · 에이전트
ops.py          운영 화면의 데이터 — 기능 상태(kit.read_status) · 설정 준비 여부 · 에이전트 보드
kit.py          키트 공통 바탕 — 설정(config.local.json) · 메일 · DPAPI · 예약 시각 판정 · 상태 파일
alertmail.py    실패 알림 메일
macros/         예제 (git 에 들어간다)
macros.local/   실제 업무 자동화 (git 제외)          ← 회사 자동화는 여기에
builtin/        요소 찍기 · 창 구조 보기 (허브가 부르는 도구)
secrets.local.json   계정·비밀번호 (git 제외, 견본 secrets.example.json)
data.local/     자동화별 전용 데이터(ctx.data_dir) — 자격증명·설정·상태 (git 제외)
```

## 자동화 쓰는 법

`macros.local\이름.py` 에 `META` 와 `run(ctx)` 를 둔다 (화면의 "새 자동화"가 템플릿을 만든다).

```python
META = {
    "name": "일일 접수 확인", "desc": "…", "target": "web",
    "motion": "search",                                    # 펫 고양이가 보일 일의 모습(아래 '일마다 다른 모션')
    "params": {"url": "https://…"},                       # 화면에 입력칸으로 뜬다
    "triggers": [{"type": "schedule", "at": "09:00", "days": "mon-fri"}],
    "timeout": 300, "cooldown": 10,
}

def run(ctx):
    page = ctx.page                                        # Chrome (자동화별 프로필 → 로그인 유지)
    page.goto(ctx.params["url"])
    page.fill("#id", ctx.secret("site_id"))                # 비밀값은 파일에 직접 쓰지 않는다
```

| `ctx` | |
|---|---|
| `ctx.page` · `ctx.browser_context` | Playwright. `META["headless"]=True` 면 화면 없이 돈다 |
| `ctx.window_handles()` · `ctx.start(cmd)` · `ctx.window(re, exclude=)` | 데스크톱(pywinauto). **띄우기 전 핸들을 기억해 `exclude` 로 넘겨야 내 창을 안 잡는다** |
| `ctx.secret(key)` · `ctx.params` · `ctx.trigger` · `ctx.log()` | 비밀값 · 입력값 · 어떤 트리거로 켜졌는지 · 화면 로그 |
| `ctx.notify(title, text)` · `ctx.motion(kind, hold=)` | 알림 풍선 · 펫 고양이의 일 모습 바꾸기 |

### 일마다 다른 모션

자동화가 도는 동안 고양이(허브 화면·화면 펫)가 **일의 종류에 맞는 모습**을 보인다. 머리 옆 말풍선 아이콘, 몸짓, 노트북 화면 색, 말풍선 글이 바뀐다.

| `motion` | 모습 |
|---|---|
| `web` | 지구본이 돈다 · 파란 화면 |
| `desktop` | 창 위에서 커서가 딸깍 · 한 손으로 클릭 |
| `write` | 연필로 줄을 쓴다 · 빠른 타자 |
| `mail` | 봉투가 날아간다 · 꼬리 살랑 |
| `search` | 돋보기가 훑는다 · 두리번 |

- `META["motion"]` 이 기본값. 없으면 `target`(web·desktop)을 따른다.
- 도는 중에 `ctx.motion("mail")` 로 바꾸고, `ctx.motion()` 으로 기본값으로 되돌린다.
- **상시 자동화**는 평소 지켜보기만 하다가 `ctx.motion("write", hold=4)` 처럼 **잠깐** 일하는 모습을 보일 수 있다(예: 접속창 자동 입력). `hold` 가 끝나면 원래대로.
- 미리 보기: 허브 주소 뒤에 `?motion=mail` (펫 페이지 `/pet?motion=mail` 도 같다).
- 스킨은 `work:<종류>` 로 따로 그림을 줄 수 있다 → `web\skins\README.md`.

## 자동 실행 트리거 — 자동화마다 켜야 동작한다 (기본 꺼짐)

```python
{"type": "process",  "name": "notepad.exe"}                        # 프로세스가 뜰 때
{"type": "window",   "title": "접속|Login", "process": "x.exe"}   # 창이 나타날 때 (제목 정규식, process 는 선택)
{"type": "schedule", "at": "09:00", "days": "mon-fri"}            # 매일/요일
{"type": "schedule", "every": "30m"}                               # 주기 (s/m/h) — 허브를 켠 시점부터 센다
```
- 같은 자동화가 실행 중이면 새로 켜지 않고, `cooldown` 초 안의 재발동도 무시한다.
- **계산기·설정 같은 UWP 앱은 창을 `ApplicationFrameHost.exe` 가 가지므로 `process` 조건을 주지 말 것** (제목으로만 건다).

## 상시 자동화 (`"service": True`)

계속 떠 있어야 하는 감시형 자동화(예: 접속창 자동 입력). 자동화의 `run(ctx)` 가 무한 루프를 돌고, 허브가 **살려 둔다.**

- 화면의 `상시 실행` 스위치를 켜면 3초 안에 시작하고, 죽으면 다시 살린다(연달아 바로 죽으면 3→6→…→60초로 간격을 늘림). 끄면 멈춘다.
- 제한 시간이 없다(`timeout` 기본 0). 스위치 상태는 허브를 껐다 켜도 `state.local.json` 에 남는다.
- **허브(트레이 앱)가 떠 있어야 동작한다.** 로그온 시 자동 시작은 위 "트레이 앱" 절 참고.
- 자동화 전용 폴더 `ctx.data_dir` (= `data.local\<자동화 id>\`, git 제외)에 자격증명·설정·상태를 둔다.
- 공용 도구 `hubutil.py`: `protect_text`/`unprotect_text`(DPAPI, PowerShell `ConvertFrom-SecureString` 과 호환), `totp()`.

## 서버·워처 지키기 · 기능 자동화 — 작업 스케줄러 대신 (`extsvc.py`, `macros/svc_*` · `job_*`)

작업 스케줄러를 쓰지 않는다. 로그온하면 허브가 뜨고, 허브가 예약 작업(`job_*`)을 정해진 시각에 돌리고 상시 서비스(`svc_*`)를 띄우고 지킨다.
키트의 기능은 모두 `job_*` 자동화다 — 처음엔 꺼져 있고, 운영 화면 「⏰ 예약 작업」에서 켠다. 대상은 `config.local.json` 에서 정한다.

| 자동화 | 기능 | 설정 갈래 |
|---|---|---|
| `job_scheduled_mail` | 정기 메일 — 정한 요일·시각에 정해진 메일 발송 | `scheduled_mails` |
| `job_tidy` | 폴더 정리 — 오래된 파일을 보관 폴더로 | `tidy` |
| `job_monitors` | 사이트·서버 감시 — 주소·포트·인증서 만료 | `monitors` |
| `job_pc_watch` | PC 디스크 감시 — 드라이브 남은 공간 | `pc_watch` |
| `job_cred_watch` | 로그인·키 만료 예고 — Claude Code 로그인·메일 로그인·Jira 토큰·적어 둔 키 만료일 | `cred_watch` |
| `job_rate_meter` | API 호출 한도 미터기 — `ratelimit.py` 를 쓰는 도구들의 사용량·429 (보기만) | `rate_limits` |
| `job_backup` | 폴더 백업 — 폴더를 날짜별로 복사, 오래된 것 정리 | `backups` |
| `job_weekly_report` | 주간 업무 보고 초안 — 이번 주 이슈·커밋을 모아 AI 가 초안, 메일로 (`toolsi-share-agent`) | `ai_share.weekly_report` |

- 기능 자동화는 결과를 `kit.write_status(기능, items)` 로 남기고, 운영 화면 「📊 기능 상태」 탭이 읽는다.
- **진짜 프로그램은 허브와 떨어진 프로세스다.** `extsvc.launch` 가 잠깐 사는 중간 프로세스로 띄워 부모 관계를 끊는다.
  그래서 **허브를 끄거나 죽여도 서버·워처는 끊기지 않고**, 다시 뜬 허브가 `META["owns"]`
  (프로세스 이름 + 커맨드라인 문자열)로 찾아 **넘겨받는다**(중복 실행 없음).
- **`상시 실행` 을 끌 때만 진짜로 멈춘다**(`stop_owned`). 죽으면 5초 안에 다시 띄운다. 1분 안에 세 번 연달아 죽으면 실패로 끝내고 허브의 재시작 간격(최대 60초)을 따른다.
- 슈퍼바이저가 덤으로 하는 일: 도구의 `notify.jsonl` 을 허브 알림(트레이 풍선·웹 토스트·펫)으로, 도구 로그를 허브 실시간 로그로, `state.json` 의 바쁨 상태를 고양이 모션으로.
- 바깥 프로그램 환경: 사용자 환경변수(API 토큰 등)를 **띄울 때마다 레지스트리에서 다시 읽는다**(허브 재시작 불필요). 허브가 러너에 넣는 `MACROHUB_CTX`·`PYTHONUTF8` 등은 빼고 넘긴다. Python 은 `python-path.txt` → `%LOCALAPPDATA%\Python\pythoncore-3.14-64` 순서로 찾는다.
- 시작·멈춤·재시작·지금 실행은 `POST /api/service {"id", "action": start|stop|restart|run}` 다(운영 화면이 부른다 — 트레이는 같은 프로세스라 `service_action()` 을 직접 부른다). 토큰은 허브가 시작할 때마다 새로 만들어 허브 화면에만 심는다 — 파일로 남기지 않는다. `services.json` 의 `hub` = 자동화 id.
- 로그인하기 전에는 아무것도 안 뜬다(허브는 로그온 자동 시작이다).

## 운영 화면 — `/ops`

<http://127.0.0.1:8630/ops> · 트레이 "⏰ 운영 화면 열기". 허브와 같이 이 PC 에서만 열린다. 데이터는 `ops.py`, 화면은 `web\ops.html`.

| 탭 | 무엇 |
|---|---|
| ⏰ 예약 작업 | `job_*` 의 다음 실행 시각 · 마지막 결과 · 켜기/끄기 · 지금 실행 · **시각 바꾸기**. 바꾼 시각은 `state.local.json` 에 들어가고 자동화 파일의 `META` 는 기본값으로 남는다("기본값으로" 로 되돌림). 마지막 실행은 실행 기록(`runs.jsonl`)에서 읽어 허브를 다시 켜도 남는다 |
| 🛡 상시 서비스 | `svc_*` 켜기/끄기 · 다시 띄우기 |
| 📊 기능 상태 | 정기 메일 · 폴더 정리 · 사이트·서버 감시 · PC 디스크 감시 · 폴더 백업 — 각 기능이 마지막에 남긴 결과(대상별 정상/문제). 아직 안 돈 기능은 "설정 안 됨" |
| ⚙ 설정 | 보기 전용 — 메일 계정 준비 여부 · 설정 파일 위치. 바꾸는 건 `python setup.py` |
| 🧵 에이전트 | Claude Code 디스패치 보드 보기 전용 · 끝난 백그라운드 작업 「치우기」·「치운 것 되돌리기」(목록 파일 `data.local\agents-dismissed.json` 에만 — 상태 파일은 그대로, `POST /api/ops/agents/dismiss {id}` · `{undo: true}`) |
| 📜 변경 이력 | 켜고 끄기·다시 띄우기·지금 실행·예약 시각·자동화 만듦·설정 변경(바뀐 갈래·키 이름만, 값 없음)을 누가(Windows 사용자)·어디서(화면 주소·트레이·설정 프로그램)·언제 — `kit.audit()` → `data.local\audit.jsonl`(2MB 넘으면 `.1` 로 한 번), `GET /api/audit`. 보안 심사용 |

**안 쓰는 것 숨기기** — 허브 첫 화면 자동화 카드·'🛠 만들기 → 🧰 고급 도구' 줄, `/ops` 예약 작업·상시 서비스 카드에 「숨기기」.
지우지도 끄지도 않고 목록에서만 접는다 — 목록 아래 「▸ 숨긴 것 N개 보기」를 펼쳐 「다시 보이기」. **켜져 있는 것은 숨길 수 없다**(먼저 끈다).
숨긴 id 는 `state.local.json` 의 `hidden`(도구는 `tool:new`·`tool:record`·`tool:desktop`), 숨김·다시 보임은 📜 변경 이력에 남는다. `GET /api/hidden` · `POST /api/hide {id, hidden}`.

**내 자동화 지우기** — 허브 첫 화면의 내 자동화(`macros.local`) 카드에 「지우기」. 키트 예제는 지울 수 없고(숨기기를 쓴다), **꺼져 있고 돌고 있지 않을 때만** 된다.
바로 지우지 않고 파일을 `data.local\deleted\<이름>-<시각>.py` 로 옮기며 켜짐·숨김·예약 시각 기록도 지운다.
목록 아래 「▸ 🗑 지운 것 N개」에서 「되살리기」 — 원래 이름으로 꺼진 채 돌아온다(같은 이름이 이미 있으면 거절).
지움·되살림은 📜 변경 이력에 남는다. `GET /api/deleted` · `POST /api/delete {id}` · `POST /api/undelete {file}`.

API — `GET /api/schedule` · `POST /api/schedule` · `GET /api/ops/{features,settings,agents}` · `POST /api/service`.
**허브를 `127.0.0.1` 밖으로 열지 말 것** — 프로그램을 띄우는 화면이다.

## 녹화 · 도구

- **웹 녹화**: 주소·이름을 넣고 시작 → Chrome 이 뜬다 → 조작하고 창을 닫으면 `macros.local` 에 저장 (`playwright codegen`).
  저장할 때 `secretize_recording` 이 비밀번호 칸(그 줄 locator 에 password·pwd·pw·비밀번호·암호…)의 `.fill("값")` 을
  `secret('<이름>_비밀번호')` 로 바꾸고 값은 `save_secrets` 로 `secrets.local.json` 에 넣는다. 녹화 스크립트(kind script)엔
  runner 가 `secret` 함수를 넣어 주고, 읽은 값은 로그에서 ●●● 로 가린다. 시험 `tests\test_hub_logic.py` SecretizeRecording.
- **요소 찍기**: 누르고 3초 안에 컨트롤에 마우스를 올리면 자동화에 붙일 `child_window(...)` 코드가 로그에 나온다.
- **구조 보기**: 창 제목 일부를 넣으면 컨트롤 트리를 출력한다. 비우면 열린 창 목록.

## 내가 다른 일을 해도 되나?

| 조작 방식 | 내 마우스·키보드 | 다른 일 |
|---|---|---|
| 웹 + `headless=True` | 안 건드림 | 가능 |
| 웹 (기본, Chrome 창이 보임) | 안 건드림 (창만 뜸) | 가능, 창이 가끔 앞으로 올 수 있음 |
| 데스크톱 `.invoke()` · `.set_edit_text()` · `.select()` (UIA 패턴) | 안 건드림 (0/10 측정) | 가능 |
| 데스크톱 `.click_input()` · `.type_keys()` (실제 입력) | **마우스를 움직이고 포커스를 가져감** | **불가** — 그동안 손대지 말 것 |

실제 입력이 꼭 필요한 업무는 **별도 세션(RDP 로 접속해 둔 창·VM·남는 PC)에서 돌리면** 내 작업과 분리된다.

## 한계

- 화면이 바뀌면 깨진다. 컨트롤을 `auto_id` 로 잡으면 덜 깨진다 (요소 찍기가 가능하면 `auto_id` 를 우선 넣는다).
- 로그인 화면의 OTP·캡차 같은 사람 확인은 자동화가 못 넘긴다.
- 허브가 켜져 있어야 트리거가 동작한다(로그온 자동 시작 + 감시자가 죽으면 다시 띄운다). 시각 예약은 허브가 꺼져 있던 동안 놓친 **오늘** 것만 한 번 따라잡는다.
- 자동화는 임의의 파이썬이다 — 남이 준 자동화를 열어 보지 않고 돌리지 말 것.
