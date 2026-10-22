# 업무 자동화 키트

회사 PC 한 대에서 **반복 업무를 대신 돌려 주는 도구 모음**이다. 어느 회사에서나 쓰도록 회사마다 다른 값
(메일 계정·받는 사람·감시할 주소·백업 폴더)은 전부 `config.local.json` **한 파일**에 둔다.
가운데에는 **자동화 허브**(트레이 상주 앱, 이 PC 에서만 열리는 웹 화면 <http://127.0.0.1:8630/>)가 있고,
기능은 허브가 정해진 시각에 돌리는 예약 작업이다. 작업 스케줄러를 쓰지 않는다.

Windows 10/11 · Python 3.10+ · 관리자 권한 불필요.

**도움말·개발자 안내**: 저장소의 [`docs/index.html`](docs/index.html) — 받은 뒤 브라우저로 연다(코드에서 만든다, `python docs/build_docs.py`) — 기능별 설정 견본, 알림 웹훅 받는 쪽(JSON·서명 검증), 자동화 만들기(META·ctx), 허브 API.
코드에서 만든다(`python docs/build_docs.py`, 시험 `tests/test_docs.py` 가 어긋나면 알려 줌).

## 기능

| 기능 | 하는 일 | 설정 (`config.local.json`) |
|---|---|---|
| 📮 정기 메일 | 정한 요일·시각에 정해진 메일(첨부 포함)을 보낸다 — 주간 보고·월말 안내 등. 제목·본문에 `{date}` `{prev_month}` `{company}` 같은 자리표시 | `scheduled_mails` |
| 🗂 폴더 정리 | 다운로드 같은 폴더에서 오래된 파일을 보관 폴더(`YYYY-MM`)로 옮긴다. 지우지 않는다 | `tidy` |
| 🌐 사이트·서버 감시 | 웹 주소·서버 포트를 몇 분마다 확인하고, 내려가면/돌아오면/인증서가 곧 끝나면 메일로 알린다 | `monitors` |
| 💽 PC 디스크 감시 | 드라이브 남은 공간이 기준 밑으로 내려가면 알린다 | `pc_watch` |
| 🔑 로그인·키 만료 예고 | 끊기기 **전에** 알린다 — Claude Code 로그인·Jira 토큰·적어 둔 키(쇼핑몰 API 키 등)는 만료 7일 전부터, 메일 비밀번호는 로그인이 거부되면 바로 | `cred_watch` |
| ⏱ API 호출 한도 조절·미터기 | 직접 만든 연동 도구가 `ratelimit.Limiter` 로 부르면 여러 프로그램이 한 한도를 나눠 쓰고, 429·Retry-After 를 보고 쉬었다 다시 보낸다. 사용량은 운영 화면, 거의 차거나 막히면 알림 | `rate_limits` |
| 💾 폴더 백업 | 폴더를 정한 시각에 날짜별 폴더로 복사하고, 오래된 백업은 정리한다 | `backups` |
| 🔔 실패 알림 메일 | 위 작업이 실패하면 나에게 메일로 알린다(같은 작업은 60분에 한 번) | `mail.alert_to` · `mail.alert_via` |
| 📣 알림 출구 | 모든 알림을 메일과 함께 슬랙·Teams·디스코드·구글 챗·웹훅으로도 — `python setup.py --webhook` 으로 추가(주소는 암호화 저장), 보낸 기록이 남는다 | `notify` |
| ☀ 아침 브리핑 | 정한 요일·시각에 어제 자동화(성공·실패)·맡긴 일·답 기다리는 질문·상시 서비스·기능 상태 ✖ 를 한 통으로(LLM 안 씀) | `morning_brief` |
| 🔌 허브 MCP 서버 | Claude Code·Claude Desktop·Cursor 같은 AI 도구가 허브 상태(서비스·실행 기록·로그·기능 상태·맡긴 일)를 **읽기 전용** 도구로 바로 묻는다 — `python setup.py --mcp` 로 등록(실행·끄기·비밀값은 내주지 않음) | `dispatch.extra_tools` |
| 🔗 바로가기 | 자주 여는 사내 사이트를 트레이 메뉴에 | `links` |
| 📝 주간 업무 보고 초안 | 이번 주 이슈·커밋을 모아 AI(claude CLI·ollama·codex·gemini)가 주간 보고 초안을 쓰고 메일로 보낸다 — 아래 「AI 공유 위키」 (기본 꺼짐) | `ai_share.weekly_report` |
| 🧠 AI 고르기 | 「말로 부탁하기」·「고쳐 달라기」·주간 보고 초안을 **Claude Code · Codex(ChatGPT) · Gemini CLI · 로컬 AI(Ollama)** 중 이 PC 에 깔린 것으로. Codex·Gemini·Ollama 는 허브가 직접 띄워 실행 기록에서 진행을 보여 준다(Codex 는 허브 폴더 안에서만 쓰는 샌드박스). 로컬 AI 는 무료이고 PC 밖으로 안 나간다 — 모델이 돌려준 파일을 내 자동화 폴더에만 쓰고, 시험 실행은 `ai.ollama_test` 를 켰을 때만(`ollama_agent.py`). 메일·대화로 일 맡기기는 권한 묻기 때문에 Claude 전용 — `tools\macro-hub\aicli.py` | `ai` |
| ✨ 나만의 앱 | 이 PC 에서만 도는 앱·게임을 AI 와 같이 만든다(🛠 만들기 화면) — 템플릿(목록 관리·기록 대시보드·변환 도구·2D 게임·빈 앱) → AI 가 **설계서** → 확인 뒤 **이대로 만들기** → 진짜 브라우저로 **자동 검사**(콘솔 오류·시나리오·스크린샷, `appcheck.py`) → 실패하면 고치기 → 「말로 고치기」 · 🕘 버전(맡기기 전·후 저절로 남음, 바뀐 곳 보기·되돌리기, `apphistory.py`) · 📦 내보내기(zip → 다른 PC 키트에서 📥 가져오기 · **HTML 한 장**/​**exe** — 허브 없이 도는 복사본, `apppack.py`). 동봉 라이브러리(Preact·Chart.js·Phaser, 설치·빌드 없음). 앱마다 `http://<id>.localhost:8631/` 로 따로 격리돼 허브·다른 앱 데이터에 손대지 못하고 바깥 주소로 자료를 못 내보낸다. 권한은 허브에서 허락해야 동작 — 이 앱 전용 DB · 파일 상자 · **고른 AI 에게 글 부탁**(결과에 「🤖 AI 작성」 표시, 「AI 도우미」 템플릿) · 허락한 내 자동화 실행 · 알림 보내기(시간당 상한 `apps.limits`) — 안내서 `APP_AUTHORING.md`, 내 앱 `apps.local\<id>\` (`apphost.py`) | `apps` |
| 🤖 자동화 | 웹(Playwright)·윈도우 프로그램(pywinauto) 화면 조작을 파이썬 자동화로 — 녹화·요소 찍기·자동 실행 트리거 | `tools\macro-hub\macros.local\` |
| 🚚 PC 이전 | PC 를 바꿀 때 Claude Code 대화 기록·키트 설정·저장소의 커밋 안 한 작업물·환경변수 값을 암호 걸린 `.7z` 하나로 묶고 새 PC 에서 풀어 넣는다 — [tools\pc-migrate\README.md](tools/pc-migrate/README.md) | `migrate` |

운영 화면 <http://127.0.0.1:8630/ops> 에서 기능마다 켜고 끄고, 시각을 바꾸고, 「📊 기능 상태」 탭에서 마지막 결과를 본다.
기능은 **처음엔 모두 꺼져 있다** — 설정에 대상을 적은 뒤 켠다.

### 고급 — 메일로 AI 에게 일 맡기기 (디스패치, 기본 꺼짐)

정해진 태그를 단 메일을 받으면 이 PC 의 Claude Code 가 그 일을 하고 결과를 메일로 답한다(`config.local.json` 의 `dispatch`).
Claude Code 가 깔려 있어야 하고, **`dispatch.enabled` 를 직접 켜야만** 동작한다.

> ⚠ **보안 경고 — 메일 한 통으로 이 PC 에서 명령이 실행되는 통로다.**
> 보낸 사람 주소는 위조할 수 있다. 켜기 전에 `allowed_senders` 를 본인 주소로만 좁히고, 작업 폴더(`default_workdir` · `workdir_keys`)를
> 업무에 필요한 곳으로 한정하고, 회사 보안 담당자와 먼저 상의할 것. 쓰지 않을 때는 끈다. 확실하지 않으면 켜지 않는다.

폰에서 보내기(폰 페이지 `dispatch-page\`)에 쓰는 설정 — 전부 기본 꺼짐, 자세한 설명은 `config.example.json` 의 `_…_설명`:

- **암호 단어** `keyed_senders` — 회사 주소가 아닌 폰 기본 메일(iCloud·Gmail 등)도 그 주소의 암호 단어 `[k:단어]` 가
  제목 끝이나 본문 한 줄로 붙어 있을 때만 받는다(폰 페이지가 자동으로 붙인다). 그 주소로 회신과 접수 신호(읽음 '1')도 보낸다.
  다른 주소로 받으려면 `phone_reply_to`.
- **멈춤** — 폰 대화방의 '멈춤' 답장이 대기·실행 중인 일을 가리키면 워커가 2초 안에 끊는다(지시보다 먼저 와도 기억해 둔다).
- **진행?** — 돌고 있는 대화에 폰이 `진행`(`진행?`·`지금 뭐 해`·`어디까지`·`상태`)이라고 보내면 새 작업 없이 지금 하는 일 한 줄
  (`진행 중 · 6분째 — 테스트 돌리기 · 할 일 1/3`, 시작 전이면 `아직 시작 전 · 앞에 N개`)을 폰으로 바로 답한다. 게이트웨이·직접 실행 모드 둘 다.
  몇 분 넘는 일에 저절로 한 통 보내는 진행 메일은 `progress_after_min`(기본 0 = 꺼짐, 예: 3).
- **권한 요청** — 맡긴 일이 허용 목록 밖의 도구(파일 쓰기·명령 실행 등)에서 막히면 회신에 "허용하고 이어서 하기 / 허용하지 않음" 질문을 붙인다.
  허용하면 **그 권한만**(명령은 그 명령 하나 — 하나로 못 적으면 "명령 실행 전체" 라고 밝힘) 더해 같은 대화를 이어 간다. 허용은 그 대화 안에서만,
  메일 게이트웨이로 돌 때 물을 수 있는 도구는 워커 상한 7개(Read·Glob·Grep·Edit·Write·NotebookEdit·Bash), 폴더 정책은 그대로 적용된다.
  디스패치 대화의 '이 PC 에서 직접 실행' 모드에도 있다 — 그 모드의 상한은 그 실행기의 쓰기 도구(Skill·WebFetch·WebSearch 포함) + 전용 브라우저다.
- **사진** — 지시 메일에 붙인 사진(최대 5장)을 `inbox\attachments\` 에 저장해 Claude 가 읽게 한다(7일 뒤 지운다).
- **스팸함** `junk_folders` — 회사 메일이 폰 지시를 스팸으로 돌릴 때 그 폴더도 보되, 암호 단어가 맞는 메일만.
- **Gmail 직접 읽기** `gmail` — 회사 스팸 장비가 외부 Gmail 새 지시를 오래 붙잡으면, 폰 페이지가 지시를 '나에게' 보내고
  PC 가 Gmail 받은편지함을 바로 읽는다. `python mail-gateway.py --setup-gmail` 창에 Gmail 주소와 앱 비밀번호
  (Google 계정 2단계 인증 → 앱 비밀번호)를 넣는다. 그 주소는 `keyed_senders` 에도 있어야 한다.

### 고급 — Jira 새 이슈 감시 (기본 꺼짐)

조건(JQL)에 맞는 새 Jira 이슈가 생기면 디스패치 대화 앱에 **"새 Jira 이슈 KEY 요약 — 1. 지금 처리 2. 내가 직접"** 이 뜬다.
'지금 처리' 를 고르면 이 PC 의 Claude Code 가 그 이슈를 읽고 할 일을 정리하고, 고칠 게 있으면 고칠 곳과 방법을 선택지로 묻는다
(그 뒤로는 디스패치 대화와 똑같이 이어진다). '내가 직접' 이거나 하루(`ask_ttl_min`) 안에 답이 없으면 건너뛰고 다시 묻지 않는다.
설정은 `config.local.json` 의 `jira`(견본·설명은 `config.example.json`).

- **디스패치가 먼저다** — `dispatch.enabled` 와 허브의 메일 게이트웨이·작업 인박스 워커가 켜져 있어야 묻고 실행한다.
  디스패치가 꺼져 있으면 감시는 돌지 않고 경고만 남긴다.
- **Claude 에게 Jira 자격증명을 주지 않는다.** 감시가 이슈의 요약·설명(길면 자른다)·링크를 지시문에 담아 넘긴다.
  이슈 본문은 남이 쓴 글이라 '자료로만 읽으라'고 적고, 밖으로 내보내는 명령(curl·ssh 등)은 기본으로 막는다(`disallowed_tools`).
- **토큰 발급**
  - Jira Cloud(`*.atlassian.net`) — Atlassian 계정의 API 토큰: <https://id.atlassian.com/manage-profile/security/api-tokens>.
    인증 방식 `cloud`(계정 이메일 + 토큰).
  - Jira Server / Data Center — Jira 오른쪽 위 내 프로필 → **개인 액세스 토큰**(Personal Access Tokens). 인증 방식 `server`.
  - 토큰은 DPAPI 로 암호화한 `token_enc` 로만 저장된다(이 PC·이 사용자만 풀 수 있다).

켜는 순서:

1. 디스패치를 먼저 켜고 대화 앱에서 지시가 오가는지 확인한다(위 절).
2. `python setup.py --jira` — 주소 · 인증 방식 · (Cloud 면 이메일) · 토큰 · 작업 폴더를 넣고 켠다.
3. `python jira-watch.py --test` — 연결과 검색 결과 건수를 확인한다. 조건은 `jira.jql`
   (기본 `assignee = currentUser() AND resolution = Unresolved AND created >= -3d`).
4. 운영 화면 「🛡 상시 서비스」에서 **Jira 새 이슈 감시** 를 켠다. 처음 돌 때 지금 있는 이슈는 묻지 않고 '이미 본 것'으로만 기록한다
   (`jql`·`base_url` 을 바꿔도 다시 그렇게 한다). 그 뒤 새로 생긴 이슈부터 묻는다. 결과는 「📊 기능 상태」.

### 고급 — AI 공유 위키 · 주간 업무 보고 초안 (기본 꺼짐)

`tools\ai-share-agent\` — 내가 이번 주에 한 일(이슈 도구의 담당 이슈 + git 커밋 + 선택 기능)을 **이슈 키로 묶어**
주간 업무 보고 초안을 쓰고, 쌓인 기록으로 팀 "업무 공유" 발표 준비 자료도 만든다. 이슈 도구가 Jira 가 아니어도 된다
(GitHub · GitLab · 없음). 설정은 `config.local.json` 의 `ai_share`(견본·설명은 `config.example.json`).
LLM 단계는 이 PC 에 로그인된 **claude CLI**(구독 — API 키 과금 없음) 또는 로컬 **ollama** 로만 돈다. 모은 자료는
`wiki_dir`(기본 `tools\macro-hub\data.local\ai_share\wiki`, git 제외)에만 쌓이고, Claude 에게 이슈 도구 토큰을 주지 않는다.

**1) 주간 업무 보고 초안** — 허브 예약 작업 `job_weekly_report`(`ai_share.weekly_report`)

- 정한 요일·시각(기본 금 16:00, `days`·`at` 은 다른 예약과 같은 표기)에 **이번 주 월요일~오늘**을 모아
  "이번 주 한 일 / 진행 중 / 다음 주 할 일 / 막힌 것"(이슈 키·링크, Claude 공동작성 커밋 비율 한 줄) 초안을 쓰게 하고
  `<wiki_dir>\reports\YYYYMMDD_주간보고.md` 로 저장한 뒤 `to`(비면 `mail.user` — 내가 먼저 보고 고쳐 보내게)에게 메일로 보낸다.
- **빈손이 되지 않게** — LLM 이 실패하면 모은 원자료(이슈·커밋 목록)를 대신 보낸다. 메일 설정이 안 돼 있으면 파일만 남기고
  「📊 기능 상태」에 이유를 적는다. 이슈 도구 조회가 실패해도 git 커밋만으로 계속한다.
- 손으로: `python tools\ai-share-agent\agent.py weekly [--since YYYY-MM-DD --until YYYY-MM-DD] [--no-mail]`,
  또는 웹 화면의 **📝 주간 보고 초안** 단추(미리 보고 **✉ 메일로 보내기** 는 따로 누른다).
- 프롬프트는 `prompt_weekly.md` — 팀 양식이 다르면 복사해 고치고 `weekly_report.prompt_file` 로 가리킨다.

**2) AI 공유 위키 화면** — 허브 상시 서비스 `svc_ai_share`, <http://127.0.0.1:8640/> (허브 머리의 📚 AI 위키)

- 이슈 목록·검색·담당자/선택 필터, 이슈마다 커밋·댓글·(선택) MR·하네스 기록, 요약 카드. 이 PC 에서만 열린다(127.0.0.1,
  쓰기 요청은 전용 헤더 필수). **수집** 은 LLM 없이 몇 초. 팀 명단·이름 별칭은 👥 에서 고치면 `ai_share` 에 저장된다.
- 🔒 내 프롬프트 — 이 PC 의 Claude Code 대화 기록에서 내가 친 프롬프트를 이슈별로 보여 준다. 화면에만 보이고 보고·발표·위키 문서에는 안 들어간다.

**3) 업무 공유 발표 준비 (선택)** — `python tools\ai-share-agent\agent.py present` (claude CLI, 사용량 큼 · `--engine ollama` 맛보기)

- 화면에서 이슈마다 **발표고정 / 발표제외 / 비공개** 를 고르고(`wiki\select.txt`), ⭐ 추천(점수: 되돌린 커밋 +2 · 여러 레포 +1 ·
  커밋 3개↑ +1 · 이슈 댓글 +1 · 이번 주 +2/지난주 +1, 하네스 grilling +3·문서 +1·리뷰 +1, AI 리뷰 지적 +1 — 꺼진 기능은 0)
  상위 10건이 먼저 들어간다. 결과 `<wiki_dir>\reports\YYYYMMDD_<report_name>.md`. 프롬프트 `prompt_present.md`(`prompt_file` 로 교체),
  지난 발표 주제 목록은 `history_file`.
- `mask()` 가 비밀번호·토큰·계정 꼴 값을 `[masked]` 로 가리지만 **휴리스틱**이다 — 위키를 남과 나누기 전에는 사람이 한 번 훑는다.

**켜는 순서**

1. `ai_share.repos`(커밋을 볼 레포 경로 목록) 또는 `workspace_root`(서브모듈 `.gitmodules` 가 있으면 그 레포들, 아니면 그 폴더 자체)를 적는다.
   내 git 이름은 비워 두면 토큰 주인·`git config user.name`·이메일 아이디로 알아낸다(`my_authors` 로 지정 가능).
2. 이슈 출처 `ai_share.tracker.type` 을 고른다 —

   | type | 접속 | 이슈 키 |
   |---|---|---|
   | `none`(기본) | 없음 — 커밋 메시지·브랜치 이름의 키로만 묶고 제목은 그 키가 처음 나온 커밋 제목 | `key_regex`(기본 `[A-Z][A-Z0-9]+-\d+`) |
   | `jira` | 키트의 `jira` 갈래(주소·cloud/server·이메일·토큰)를 그대로 — `python setup.py --jira` (마지막의 "감시를 켤까요?" 는 아니요여도 된다). Server/DC 는 PAT(Bearer)·`/rest/api/2`, Cloud 는 이메일+API 토큰·accountId·`/rest/api/3/search/jql` | `jira_project_keys`(예 `["PROJ"]`), 비면 `[A-Z][A-Z0-9]+-\d+` |
   | `github` | `repos`(`["owner/name"]`) · `api_url`(GitHub Enterprise 면 `https://<호스트>/api/v3`) · 토큰 `python agent.py set-token` | `owner/name#123`(화면엔 `name#123`), 레포가 하나면 커밋의 `#123` 도 |
   | `gitlab` | `api_url`(`https://gitlab.example.com/api/v4`) · `projects`(경로 목록) · 토큰 `python agent.py set-token` | `경로#123`, 프로젝트가 하나면 커밋의 `#123` 도 |

   GitHub·GitLab 은 `type_labels`(라벨 중 유형으로 볼 것)를 줄 수 있다. 토큰은 DPAPI 로 암호화한 `token_enc` 로만 저장된다.
   브랜치 이름 규칙이 따로 있으면 `branch_ticket_re`(예 `feature/(\d+)-` — 숫자면 레포·프로젝트 키가 하나일 때 그것으로 붙인다).
3. `ai_share.enabled` 를 켜고 운영 화면 「🛡 상시 서비스」에서 **AI 공유 위키** 를 켠다 → 화면에서 **수집**.
4. 주간 보고를 받으려면 `ai_share.weekly_report.enabled` 를 켜고 「⏰ 예약 작업」에서 **주간 업무 보고 초안** 을 켠다
   (메일 설정 필요, claude CLI 로그인 또는 ollama).

**선택 기능** — 비워 두면 그 수집·점수·화면 칸이 통째로 빠지고 나머지는 그대로 돈다.

| 설정 | 하는 일 |
|---|---|
| `team` · `aliases` | 팀원 이슈·커밋도 모아 담당자별로 본다(보고·추천·발표는 내 것만). `aliases` = git author → 표시 이름 |
| `comment_prefixes` | 이 머리말로 시작하는 담당자 댓글만 기록에 — 비면 담당자 본인 댓글 모두 |
| `gitlab` · `review_bot` | 내 GitLab MR 을 이슈에 붙인다(출처가 gitlab 이면 그 토큰, 아니면 `set-token --gitlab`). `review_bot.name`·`issue_heading` 이 있으면 AI 코드 리뷰 봇의 지적을 세어 점수·카드에 |
| `tag` | 제목 꼬리표(예 `[고객사]`)를 열·'자주 나온 …' 카드로 — `label`·`regex`(첫 묶음)·`ignore` |
| `harness` | 작업 폴더(`tasks_dir/<작업>/state.md·grilling·review`)·이슈 문서·패턴·결정 기록을 두는 팀이면 켠다 |
| `other` | (harness 와 함께) 다른 파트 하네스 레포를 읽기 전용 clone 으로 참고 — clone/pull 은 5분 제한, 토큰은 환경변수로만 넘긴다 |
| `exclude_types` | 추천·발표 후보에서 뺄 이슈 유형 |

## 설치 — 파일 하나 (권장)

`WorkKitSetup-<버전>.exe` 를 실행하고 「설치」를 누르면 끝이다. **파이썬·인터넷이 없는 PC 에도 된다**(내장 파이썬을 함께 깐다).

- 관리자 권한이 필요 없다 — 내 계정 폴더(`%LOCALAPPDATA%\WorkKit`)에 깔린다.
- 시작 메뉴 「업무 자동화 키트」(허브 열기) · 「메일·계정 설정」(설정 창, `setup_gui.py`) · 「업무 자동화 키트 제거」, 바탕화면 바로가기, 로그온 자동 시작이 생긴다.
- 처음 설치하면 「메일·계정 설정」 창이 이어서 뜬다(회사 이름·메일 서비스·주소·비밀번호 → 저장 → 시험 메일 보내기). 허브는 <http://127.0.0.1:8630/> (이 PC 에서만).
- **다시 설치하면 업데이트**다 — 설정·기록은 그대로 남는다.
- 제거는 '설정 → 앱 → 설치된 앱' 또는 시작 메뉴의 「제거」. 설정을 남기면 다음 설치 때 되살아난다.
- IT 담당자 일괄 배포: `WorkKitSetup-<버전>.exe /S` (무인 설치, 폴더 지정은 `/D=D:\WorkKit`).
- 서명되지 않은 exe 라 처음 실행 때 Windows SmartScreen 이 경고할 수 있다 — 「추가 정보 → 실행」.
- 웹 자동화(playwright)는 용량이 커서 기본으로 넣지 않는다. 필요하면 설치 폴더에서 `runtime\python.exe -m pip install playwright`.

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
3. **허브 실행 환경** — `tools\macro-hub\setup.bat` (처음 한 번. 자동화용 패키지를 `.venv` 에 설치).
4. **허브 시작** — `tools\macro-hub\start_app.bat` → 트레이에 강아지 아이콘이 뜨고 허브 화면이 열린다.
   로그온할 때 자동으로 뜨게 하려면 트레이 메뉴 ⚙ 설정 → 로그온 시 자동 시작.
5. **기능 켜기** — `config.local.json` 에 대상(받는 사람·주소·폴더)을 적고, 운영 화면 「⏰ 예약 작업」에서 스위치를 켠다.
   「지금 실행」으로 바로 시험해 볼 수 있다.

> Gmail·네이버처럼 2단계 인증을 쓰는 메일은 계정 비밀번호 대신 **앱 비밀번호**를 넣어야 한다.
> 회사 메일은 관리자가 IMAP/SMTP 사용을 허용해야 하는 경우가 많다.

## 보안

- **허브는 `127.0.0.1` 에만 열린다.** 허브는 프로그램을 띄우고 자동화를 돌리는 화면이라, 같은 망에 열면 원격 실행 구멍이 된다 —
  `0.0.0.0`·LAN 으로 바인딩하거나 포트를 터 주지 말 것. 실행 요청에는 허브가 시작할 때마다 새로 만드는 토큰이 필요하다.
- **비밀번호는 Windows DPAPI 로 암호화**해 `password_enc` 로만 저장한다. 이 PC·이 Windows 사용자만 풀 수 있다
  (PC 를 옮기면 `python setup.py` 로 다시 넣는다).
- **`config.local.json` 은 절대 커밋하지 않는다** — `.gitignore` 에 들어 있다. 견본은 `config.example.json`.
  자동화가 쓰는 계정은 `tools\macro-hub\secrets.local.json`(역시 커밋 안 함), 실행 기록·상태는 `tools\macro-hub\data.local\`.
- 자동화는 임의의 파이썬 코드다 — 남이 준 자동화는 열어 보고 돌린다.

## 구조

```
setup_gui.py             메일·계정 설정 창 (보통은 이것 — 시작 메뉴·트레이에서 연다)
setup.py                 같은 설정을 명령 창으로 (--test 시험 메일 · --show 설정 보기)
config.example.json      설정 견본 — 갈래별 설명은 이 파일 안 "_설명"
config.local.json        이 PC 의 실제 설정 (git 제외, setup.py 가 만든다)
mail-gateway.py · inbox-worker.ps1   디스패치 — 메일 지시를 받아 Claude Code 로 실행하고 회신 (기본 꺼짐)
jira-watch.py            Jira 새 이슈 감시 — 새 이슈를 디스패치 대화로 물어본다 (기본 꺼짐, setup.py --jira)
tools\ai-share-agent\    AI 공유 위키 — 주간 업무 보고 초안 · 이슈별 작업 기록 · 발표 준비 (기본 꺼짐, ai_share)
tools\macro-hub\         자동화 허브 — 트레이 앱 · 웹 화면 · 예약 작업 · 상시 서비스 (자세히: tools\macro-hub\README.md)
    kit.py               공통 바탕 — 설정 · 메일 · DPAPI · 예약 시각 판정 · 기능 상태 파일
    macros\job_*.py      기능 (정기 메일 · 폴더 정리 · 감시 · PC 점검 · 백업)
    macros.local\        내가 만든 자동화 (git 제외)
tools\pc-migrate\        PC 이전 묶음 — pack.ps1(지금 PC) · restore.ps1(새 PC) (migrate)
tools\proc-live\         허브의 내부 모듈(프로세스 스냅샷)
tests\                   python -m unittest discover -s tests · 커밋 전 tests\verify.ps1
```

## 문제가 생기면

- 운영 화면 「⚙ 설정」 — 메일 설정이 준비됐는지, 설정 파일이 어디 있는지.
- 운영 화면 「📊 기능 상태」 — 기능별 마지막 결과. 「⏰ 예약 작업」 — 마지막 실행의 성공/실패와 로그.
- 허브 로그 `tools\macro-hub\data.local\app.log` · 알림 메일 기록 `data.local\alertmail.log`.
