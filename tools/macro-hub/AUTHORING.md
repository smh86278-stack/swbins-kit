# 자동화 만들기 안내 — Claude 가 따르는 순서

허브의 「말로 부탁하기」·「🩹 고쳐 달라기」가 이 파일을 먼저 읽으라고 한다. 사람을 위한 설명은 `README.md`.
목표는 **만든 사람이 코드를 몰라도 믿고 켤 수 있는 자동화** — 만들고, 스스로 시험하고, 안 되면 고쳐서, 쉬운 말로 보고한다.

## 순서

1. **무엇을 할지 정리** — 부탁을 단계로 나눈다(① 사이트 열기 ② 로그인 ③ 표 읽기 ④ 바뀌었으면 알림). 여러 가지 일이면 일마다 파일을 따로.
   모르는 값(주소·계정 이름·받을 사람)은 짐작하지 말고 `params` 로 빼거나 물어본다.
2. **만들기** — `macros.local\<영문_이름>.py` 하나(이 폴더 = 허브 폴더, 이 안내서가 있는 곳). 형식은 아래.
3. **시험 실행** — 허브 폴더에서
   ```
   "<허브 파이썬>" runner.py --test macros.local\<파일>.py [이름=값 ...]
   ```
   (부탁 글에 정확한 명령이 적혀 있다.) 마지막 줄이 `🧪 시험 결과: 성공|실패`, 종료 코드도 같다.
4. **실패하면 고쳐서 다시** — 로그를 읽고 원인을 고쳐 3번을 다시. **최대 3번.** 3번 안에 안 되면 멈추고 무엇이 막혔는지 보고한다.
   - 로그인 만료·사이트 점검·네트워크처럼 **코드 밖 문제**면 고치지 말고 그렇다고 보고한다.
   - 비밀값이 아직 없어 멈추면(`secrets.local.json 에 '…' 가 없습니다`) 거기까지가 시험이다 — 넣을 키 이름을 보고한다.
5. **보고** — 아래 「보고 형식」대로, 코드가 아니라 쉬운 말로.

## 지킬 것

- **고치는 파일은 `macros.local\` 의 그 자동화 하나뿐.** 허브·키트 코드, `macros\` 의 기본 자동화, 설정(`config.local.json`)은 건드리지 않는다.
- **되돌릴 수 없는 동작은 `ctx.for_real(설명)` 으로 감싼다** — 메일·메시지 보내기, 제출·저장·승인 버튼, 삭제, 결제, 주문.
  시험 실행에서는 그 부분을 건너뛰고 `🧪 시험이라 건너뜀: …` 로그만 남는다.
  ```python
  if ctx.for_real('결재 승인 누르기'):
      page.get_by_role('button', name='승인').click()
  ```
- **비밀번호·토큰·계정은 파일에 쓰지 않는다** — `ctx.secret('키')`. 값은 사람이 `secrets.local.json` 에 넣는다(견본 `secrets.example.json`).
  `secrets.local.json` 을 직접 만들거나 고치지 않는다. 값은 DPAPI 로 암호화돼 있어(`dpapi:…`) 열어 봐도 읽을 수 없다 — `ctx.secret` 이 풀어 준다.
- 파일 지우기·많은 사람에게 메일 같은 큰 일은 만들기 전에 물어본다.
- 시험은 **허브 없이 이 파일만** 돌린다. 허브 화면·API 를 부르지 않는다.

## 파일 형식

```python
# -*- coding: utf-8 -*-
META = {
    "name": "공지 첫 글 확인",                  # 허브 목록에 보일 이름
    "desc": "공지 게시판 첫 글이 바뀌면 알림",
    "steps": ["공지 게시판 열기", "첫 글 제목 읽기", "지난번과 다르면 알림"],   # 쉬운 말 단계 — 사람이 보고 믿고 켜게
    "kind": "ctx",
    "target": "web",                           # web · desktop
    "params": {"url": "https://example.com/notice"},   # 허브 화면에 입력칸으로 뜬다(기본값)
    "triggers": [{"type": "schedule", "every": "30m"}],
    "timeout": 300,                            # 초
}


def run(ctx):
    page = ctx.page
    page.goto(ctx.params["url"])
    first = page.get_by_role("link").first.inner_text()
    ...
```

**트리거**(허브에서 사람이 「자동 실행」을 켜야 돈다 — 만들 때는 꺼진 채)
```python
{"type": "schedule", "at": "09:00", "days": "mon-fri"}   # 매일/요일 — days: daily · mon-fri · mon,thu
{"type": "schedule", "every": "30m"}                     # 주기 s/m/h
{"type": "window", "title": "접속|Login", "process": "x.exe"}   # 창이 나타날 때(제목 정규식)
{"type": "process", "name": "notepad.exe"}               # 프로세스가 뜰 때
```
그 밖의 META: `"headless": True`(화면 없이) · `"web_timeout": 30`(요소 기다리는 초) · `"no_mouse": True`(마우스·키보드 안 쓰기) ·
`"cooldown": 10` · `"service": True`(계속 떠 있는 감시형 — 무한 루프, 제한 시간 없음).

## ctx 도구

| 도구 | |
|---|---|
| `ctx.page` · `ctx.browser_context` | Chrome(Playwright). 자동화마다 프로필이 따로라 **로그인이 남는다** — 처음 한 번은 사람이 로그인해야 할 수 있다 |
| `ctx.window(제목정규식, exclude=)` · `ctx.window_handles()` · `ctx.start(명령)` | 데스크톱 창(pywinauto UIA). 띄우기 전 `window_handles()` 를 `exclude` 로 넘겨 사람의 창을 잡지 않게 |
| `ctx.click(컨트롤)` · `ctx.set_text(컨트롤, 글)` | 마우스·키보드 없이 먼저 시도 |
| `ctx.params` · `ctx.param(키)` · `ctx.secret(키)` · `ctx.data_dir` | 입력값(사전 · 글자 하나) · 비밀값 · 이 자동화 전용 폴더(지난번 값 저장 등) |
| `ctx.log(...)` · `ctx.notify(제목, 글)` | 로그 · 알림(트레이·허브 화면) |
| `ctx.for_real(설명)` · `ctx.dry_run` | 되돌릴 수 없는 동작 앞 — 시험이면 False |
| `import kit` → `kit.send_mail(받는사람, 제목, 본문)` · `kit.alert(제목, 본문)` | 메일 · 알림(설정된 메일 계정·알림 출구로) — 보내기는 `for_real` 안에 |

**실패하면**: 오류로 끝나면 허브가 그 순간 화면(웹은 Chrome, 데스크톱은 전체 화면)을 `data.local\failshots\` 에 남기고 실패 알림 메일에 붙인다 —
고치러 왔다면 로그의 `📸 실패한 순간 화면을 남겼습니다: …` 줄의 그림을 먼저 열어 본다. 오류를 삼키지 말고 그대로 올려야 찍힌다.
**녹화 스크립트**(kind script)의 `param("칸")` 은 META params 의 값, `secret("키")` 는 비밀값이다 — 고칠 때 값을 코드에 다시 박지 않는다.
**웹 요령**: 선택자는 `get_by_role` · `get_by_text` · `get_by_label` 을 먼저(화면 글자가 바뀌지 않는 한 오래 간다). 화면을 모르면
시험 중에 `ctx.log(page.content()[:3000])` 이나 `page.screenshot(path=os.path.join(ctx.data_dir, 'shot.png'))` 로 보고 고친다(다 고치면 지운다).
**데스크톱 요령**: 허브 「🧰 고급 도구 → 요소 찍기·구조 보기」가 만드는 코드를 쓴다. UWP 앱(계산기 등)은 `process` 조건을 주지 않는다.

## 보고 형식

```
✅ 「공지 첫 글 확인」을 만들었어요 (macros.local\notice_check.py)
하는 일: ① 공지 게시판 열기 → ② 첫 글 제목 읽기 → ③ 지난번과 다르면 알림
언제: 30분마다 — 허브 목록에서 「자동 실행」을 켜면 시작해요
시험: 성공 (첫 글 「10월 정기 점검 안내」 확인, 알림 보내기는 시험이라 건너뜀)
해 주실 것: (있으면) secrets.local.json 에 site_id · site_pw 넣기 / 처음 한 번 로그인
```
실패로 끝났으면 `❌` 로 시작해 어디서 막혔는지(몇 번째 단계, 화면에 무엇이 없었는지)와 사람이 할 일을 적는다.
