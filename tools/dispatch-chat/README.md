# 디스패치 대화 (`dispatch-chat`)

메일로 맡긴 일을 **메신저처럼** 보는 PC 앱입니다. 쓰는 법은 [GUIDE.md](GUIDE.md)(받기·처음 설정·지시·선택지·맥).
허브와 따로 떨어진 앱이라 **다른 PC 에서도 exe 하나로**, **윈도우·맥** 모두 돕니다.

```
[이 PC]   허브 '💬 대화' → http://127.0.0.1:8620/   (허브 서비스 svc_dispatch_chat 이 chat.py --serve 로 띄움)
[다른 PC] DispatchChat.exe 더블클릭(build.py 로 만듦) → 처음엔 메일 계정 입력 → Edge 앱 창
[맥]      DispatchChat.command 더블클릭(처음 한 번은 우클릭 → 열기)  또는  python3 chat.py
[휴대폰]  디스패치 페이지(저장소의 dispatch-page — 정적 호스팅에 올려 씀) + 메일 앱의 답장 단추
```

## 계정 — 어디서 읽나

| 순서 | 출처 | 언제 |
|---|---|---|
| 1 | 이 PC 의 앱 설정 `%APPDATA%\DispatchChat\config.json`(맥 `~/Library/Application Support/DispatchChat/`) | 거기에 메일 주소가 있으면 |
| 2 | **키트 공통 설정** — 저장소 맨 위 `config.local.json` 의 `mail` · `dispatch` (화면에 '키트 설정 계정(이 PC 게이트웨이)') | 이 저장소 안에서 돌고 앱 설정에 계정이 없으면 |
| 3 | 기본값(회사 값 없음) — 처음 열면 계정을 묻습니다 | 그 밖(다른 PC) |

- 키트 설정을 쓰면 이 PC 가 곧 **게이트웨이 PC** 입니다. 비밀번호는 `mail.password_enc`(키트 `kit.protect` 와 같은 DPAPI)를 그대로 풉니다.
  보는 폴더 `dispatch.folders`, 태그 `dispatch.tags`·`write_tags`, 작업 폴더 `dispatch.default_workdir`·`workdir_keys`,
  보내는 방법 `dispatch.chat_send_mode`(없으면 `reply_mode` — 자기에게 보낸 메일을 딴 폴더로 옮기는 서버면 `append`).
- **이슈 칸** — 키트 이름 `dispatch.issue_prefix`(예: `PROJ-`)·`dispatch.issue_command`(기본 `/issue`)를 앱의 이슈 칸으로 옮겨 씁니다.
  번호를 넣으면 `#cw /issue PROJ-123` 을 보내고 게이트웨이가 `dispatch.issue_tools` 로 돌립니다. 키트 모드에서 `issue_prefix` 가 비면 칸이 숨습니다.
  다른 PC(앱 설정)는 ⚙ 의 「Jira 키 앞부분」·「이슈 명령」(비우면 `/jira` — 이 PC 에서 직접 실행이 알아보는 명령. 키트 게이트웨이로 보낼 땐 그쪽 `issue_command` 와 같게).
- 메일: IMAP·SMTP 가 되는 메일이면 어디든 됩니다. 메일 주소를 넣으면 잘 알려진 곳(Gmail·네이버·다음·iCloud)은 서버가 저절로 채워집니다.
  회사 밖 메일은 설정의 **암호 단어**를 게이트웨이 `dispatch.keyed_senders` 와 같게 넣으면 본문 마지막 줄에 `[k:단어]` 로 붙여 보냅니다(화면에는 안 보임).
- 사내 TLS 검사 프록시가 있으면 `mail.ca_bundle`(앱 설정이면 `ca_bundle`) — 메일과 Jira 감시가 같이 씁니다.
- 로그: 윈도우 `%LOCALAPPDATA%\DispatchChat\chat.log`, 맥 `~/Library/Application Support/DispatchChat/`.

## ⚙ 작업 폴더 (게이트웨이)

키트 설정을 쓰는 메신저면 ⚙ 에 「작업 폴더 (게이트웨이)」 칸이 보입니다 — 폴더를 고르지 않은 지시가 도는 **기본 폴더**와 `키=폴더` 목록.
저장하면 `config.local.json` 의 `dispatch.default_workdir`·`dispatch.workdir_keys` 만 고치고(다른 키는 그대로, 허브 「변경 이력」에 남음)
게이트웨이는 폴링마다 설정을 다시 읽어 바로 따릅니다. 회사 모드 폴더(`dispatch.company_workdirs`)를 따로 안 정했으면 기본 폴더를 바꿀 때
**옛 기본 폴더를 회사 폴더로 박아 둡니다** — 폰으로 회사 소스가 나가지 않게 막던 폴더가 조용히 바뀌지 않게. 새 대화의 폴더 칩 옆 **＋** 로도 이 칸이 열립니다.

## 이 PC 에서 직접 실행 (게이트웨이 없이, 기본 꺼짐)

게이트웨이 PC 가 없어도 **메신저를 설치한 PC 가 직접 일하게** 할 수 있습니다. ⚙ 아래 「이 PC 에서 직접 실행」 스위치를 켜면
내 메일함에 온 지시(`#c` 읽기 · `#cw` 수정 허용 — 게이트웨이와 같은 형식)를 이 PC 의 Claude Code(`claude -p`)로 실행하고,
답을 **같은 메일함에** 넣습니다(IMAP 으로 받은편지함에 써 넣기). 답은 게이트웨이 회신과 같은 제목·머리글(`X-Dispatch-*`)·대화 번호 `[T12]`·선택지
형식이라 이 화면·폰 페이지가 그대로 보여 줍니다. 코드는 `chat_runner.py`(파이썬만 — 윈도우·맥).

- **필요한 것**: 이 PC 에 Claude Code 설치 + 한 번 로그인(터미널에서 `claude`). `claude` 를 못 찾으면 스위치 옆에 안내만 나오고 켜지지 않습니다.
- **게이트웨이 PC 에서는 켜지지 않습니다** — 키트 설정의 계정을 쓰는 중이거나, 이 저장소의 키트 게이트웨이가 켜져 있으면(`dispatch.enabled`)
  스위치가 막히고 이유가 뜹니다. 켠 뒤 메일함에 다른 실행기(게이트웨이)의 회신이 보이면 스스로 끄고 화면 위에 알립니다.
- **안전**
  - 지시는 **이 계정 자신의 주소에서 온 것만** 받습니다. 설정에 **암호 단어**가 있으면 제목 끝·본문 줄 `[k:단어]` 가 맞는 것만(권장).
    서버가 붙인 발신 인증(Authentication-Results)이 실패한 메일도 버립니다.
  - **스위치를 켠 시각 이후에** 메일함에 들어온 지시만. 처리한 메일은 상태 폴더의 `runner/state.json` 에 적어 두 번 실행하지 않습니다.
  - 수정 허용(`#cw`) 새 지시는 실행 전에 확인을 한 번 묻습니다(60분 안에 답이 없으면 취소). 읽기 지시는 읽기 도구만 씁니다.
  - 끄면 하던 일·기다리던 일도 그 자리에서 멈춥니다. claude 는 자식 프로세스까지 한 묶음으로 끊습니다(윈도우 작업 개체 · 맥 프로세스 그룹).
- **되는 것**: 이어서 하기(같은 대화 → `claude --resume`), 선택지 번호 답(`1,3`), 멈춤, 🔁 다시 실행, 수정 허용 확인,
  폰·메일 앱 지시에 접수 신호(ack), 3분 넘게 걸리면 진행 메일 1통(`X-Dispatch-Kind: progress`, 설정 `progress_after_min`, 0 이면 끔),
  진행 카드, 폰이 보낸 사진, 제한 시간 15분, 질문 답 기한(24시간 — `X-Dispatch-Kind: closed`, 설정 `ask_ttl_hours`, 0 이면 끔 — 게이트웨이와 같은 규칙),
  하루 비용 한도(⚙ 칸 · 설정 `daily_cost_usd`, 0 이면 없음 — 닿으면 새 지시·다시 실행은 실행하지 않고 이유만 회신, '멈춤' 은 막지 않음),
  작업 하나 상한(설정 파일 `job_cost_usd`·`job_max_turns`, 0 이면 없음 — `claude -p --max-budget-usd`·`--max-turns`. 도는 중인 작업을 끊고
  "상한에 닿아 멈췄습니다 — '계속' 이라고 답하면 이어서" 를 회신, 세션은 남음. 게이트웨이 워커는 `dispatch.max_budget_usd`·`max_turns`),
  브라우저 안전장치(`browser-guard.js`, PreToolUse 훅 — 브라우저 도구가 붙는 작업에만 `--settings` 로. 보내기·삭제·결제·제출·승인·저장 단추,
  입력 후 제출·Enter, 클릭·전송 스크립트는 사람이 '진행해도 됩니다' 라고 답하기 전엔 막는다. 허락 하나는 동작 하나에만. node 로 돈다).
- **작업 폴더**: 기본 작업 폴더 하나 + `키=폴더` 목록(지시에 `@키`).
- **폰에서**: 폰 페이지·폰 메일 앱이 **같은 계정에서 자기 자신에게** 보내야 받습니다.
- **전용 브라우저(스위치, 기본 꺼짐)**: 켜면 수정 허용(`#cw`) 새 지시에 Playwright MCP(`npx @playwright/mcp@0.0.83`, `mcp__browser`)를 붙입니다.
  프로필은 상태 폴더의 `runner/browser/profile` — **로그인 창 열기**로 그 프로필 Chrome(없으면 윈도우 Edge)을 `127.0.0.1:9333` 디버깅 포트로 열어
  한 번 로그인해 둡니다. 켤 때 npx·Chrome 이 없으면 막힙니다. 읽기 지시·Jira 지시에는 붙지 않습니다.
- **Jira 처리(스위치, 기본 꺼짐)**: 켜면 `#cw /jira 키`(또는 설정의 이슈 명령)를 Jira 도구
  (`mcp__jira__jira_get_issue`·`_search`·`_get_transitions` + 읽기·고치기·Bash)와 거부 목록(curl·wget·ssh 등 밖으로 내보내는 명령, `rtk` 붙은 것까지)으로 돌립니다.
  Jira 주소는 회사 값 `jira_url`(company.json)이 있으면 미리 채워집니다. 토큰을 넣으면 `uvx mcp-atlassian@0.23.1 --read-only` 를 붙이고
  (토큰은 DPAPI·키체인), 비우면 이 PC 의 Claude Code 에 이미 있는 `jira` MCP 를 씁니다. 작업 폴더나 `~/.claude` 에 설정의 **Jira 스킬**(기본 `jira`)이
  있으면 `/<스킬> 키` 로, 없으면 이슈를 읽고 방향을 묻는 지시로 넘깁니다. **curl·ssh 허용**을 켜면 거부 목록을 뺍니다(스킬이 curl 로 Jira REST 를 부를 때).
- **빠진 것(게이트웨이·워커 대비)**: 다른 주소의 암호 단어 발신자(`keyed_senders`)·폰 주소로 회신 사본 · 작업 일시정지 깃발·알림 큐 · 회신을 SMTP 로 보내기(늘 메일함에 써 넣기).
- 상태 폴더: 윈도우 `%LOCALAPPDATA%\DispatchChat\runner\`, 맥 `~/Library/Application Support/DispatchChat/runner/`.
  대화 규칙은 이 폴더의 `chat-protocol.md`(exe 에 같이 묶임 — 게이트웨이·워커는 저장소 맨 위의 것을 씁니다).

## Jira 새 티켓 감시 · 자리비움 (스위치, 기본 꺼짐 — 직접 실행 PC 용)

⚙ 아래 「Jira 새 티켓 감시」를 켜면 1분마다 **내게 배정된 새 Jira 티켓**을 봅니다(`jira_watch.py`). 대화 목록 위에 **🏃 자리비움** 단추가 생깁니다.

- **자리비움 켜짐** → 새 티켓마다 `/jira 키` 작업을 이 PC 에서 직접 실행 큐에 넣습니다(한 번에 최대 3건, 직접 실행이 켜져 있어야 함).
- **자리비움 꺼짐** → 실행하지도 묻지도 않고 '처리됨'으로만 적고, 단추 아래에 '새 티켓 N건 — 직접 처리' 를 작게 띄웁니다.
- 처음 켤 때 지금 있는 티켓은 **본 것으로만** 적습니다. 하루 비용 한도에 닿았으면 넣지 않고 처리됨으로만 + 이유 알림.
- **게이트웨이 PC(키트 모드)에서는 켜지지 않습니다** — 그 PC 의 새 이슈는 키트의 `jira-watch.py`(`config.local.json` 의 `jira` 갈래,
  허브 「상시 서비스」의 Jira 감시)가 대화 앱으로 "지금 처리할까요?" 를 묻고 처리합니다. 둘 다 돌면 같은 이슈가 두 번 처리되고,
  이 감시가 넣는 작업 모양은 키트 게이트웨이가 회신하지 않으므로 막아 둡니다.
- Jira 주소·토큰·작업 폴더·스킬은 위 「Jira 처리」 칸을 같이 씁니다(토큰이 비면 환경변수 `JIRA_TOKEN`). 제외 규칙(발생환경 계정 · 연결 이슈 제목, 정규식)은
  회사마다 다르니 `company.json` 의 `jira_watch_exclude_account`·`jira_watch_exclude_linked` 로 미리 채웁니다(코드 기본값은 비어 있음).
- 자리비움을 켜고 끈 것·넣은 작업은 메신저 로그의 `[Jira 감시]` 줄에 남습니다. 상태는 `runner/jira-watch.json`.

## 진행 상황(실시간)

게이트웨이 PC(키트 모드)에서 돌리거나 **이 PC 에서 직접 실행**을 켜면, **일하는 중인 대화**에 Claude 가 지금 무엇을 하는지(쓰는 도구·중간 말·할 일 목록)가
2초마다 카드로 올라옵니다. 작업 파일(키트 `inbox/jobs/*.json` · 직접 실행 큐)과 Claude Code 가 스스로 남기는 세션 기록(`~/.claude/projects/<작업 폴더>/*.jsonl`)을
읽기만 합니다. 단계를 누르면 **자세히** — 도구에 넘긴 전체 입력과 결과 출력(2,000자까지). 다른 PC 에서는 '작업 중' 표시만 보입니다.

## 화면에서 더

🔥 급건(목록 맨 위 고정) · 📝 저장해 두는 답 · 🗑 대화 지우기 · 🧹 대화 전체 지우기(끝난 대화만, 되돌리기 가능) — 모두 메일은 그대로 두고 이 PC 목록에서만.
실패한 대화엔 🔁 다시 실행과 기록 복사(회사 값 `support_email` 이 있으면 ✉ 문의).

## 회사마다 세팅

- 설정 화면(⚙)에서 메일 서버·이슈 키 앞부분·암호 단어를 넣으면 됩니다. 이 저장소 안이면 `config.local.json` 이 정본입니다(`python setup.py`).
- 다른 PC 용 exe 에 회사 값을 처음부터 채워 두려면 `company.example.json` 을 `company.json` 으로 복사해 채웁니다(설정 화면 기본값 + 메일 주소 프리셋).
  `build.py` 가 있으면 exe 에 같이 묶습니다. 커밋하지 않습니다(`.gitignore`).

## 그 밖

- 화면은 127.0.0.1 에만 열리고, 보내기 같은 요청은 띄울 때마다 새로 만드는 토큰이 있어야 합니다.
- 포트가 겹치면 `DISPATCH_CHAT_PORT` 환경변수로 바꿉니다(이미 같은 포트에 앱이 떠 있으면 새로 띄우지 않고 창만 엽니다).
- 펫(강아지·고양이)은 허브의 인형 스킨(`tools/macro-hub/web/skins/plush`)이 있을 때만 보입니다 — 없으면 칸이 숨습니다.
- 키트 게이트웨이는 진행 메일(`progress`)을 보내지 않습니다 — 게이트웨이 PC 의 진행은 진행 카드로 봅니다.

## 만들기 · 확인

```
..\macro-hub\.venv\Scripts\python.exe build.py      → 윈도우 dist\DispatchChat.exe · 맥 dist/DispatchChat.app   (dist·build 는 git 제외)
python -X utf8 -m unittest tests.test_dispatch_chat tests.test_dispatch_chat_app tests.test_chat_runner tests.test_chat_jira_watch
                                → 메일 묶기·키트 설정 출처 · 진행 상황 · 직접 실행(가짜 메일함·가짜 claude) · Jira 감시 (저장소 맨 위에서)
```
