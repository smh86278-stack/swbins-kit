# 디스패치 대화 (`dispatch-chat`)

메일로 맡긴 일을 **메신저처럼** 보는 PC 화면입니다. 허브와 따로 떨어진 앱이라 **다른 PC 에서도 exe 하나로** 돕니다.

```
[이 PC]   허브 '💬 대화' → http://127.0.0.1:8620/   (허브 서비스 svc_dispatch_chat 이 chat.py --serve 로 띄움)
[다른 PC] DispatchChat.exe 더블클릭 → 처음엔 메일 계정 입력 → Edge 앱 창
[휴대폰]  디스패치 페이지(저장소의 dispatch-page — 정적 호스팅에 올려 씀) + 메일 앱의 답장 단추
```

- 통로는 회사 메일입니다. 이 앱은 메일함(`dispatch.folders`, 기본 INBOX)에서 지시 태그(`#c`/`#cw`) 메일만 골라 대화 번호 `[T12]` 별로 묶어 보여 주고,
  입력한 말을 메일로 보냅니다. 일반 업무 메일은 읽지 않습니다. 실제 실행은 이 PC 의 메일 게이트웨이·인박스 워커가 합니다.
- 봇 메일은 게이트웨이가 붙이는 `X-Dispatch-*` 헤더로 알아봅니다(선택지는 `X-Dispatch-Ask`). Claude 가 남긴 질문은 체크박스(여러 개)·
  라디오(하나)로 고르고, `멈춤` 으로 멈추게 할 수 있습니다. 대화 규칙은 저장소 루트의 `chat-protocol.md`.
- **이슈 칸**은 `dispatch.issue_prefix`(예: `PROJ-`)를 넣어야 보입니다. 번호를 넣으면 `#cw /issue PROJ-123` 을 보내고,
  게이트웨이가 `dispatch.issue_tools` 로 돌립니다. `/issue` 자리는 `dispatch.issue_command` — 그 이슈를 처리할 Claude Code 스킬 이름입니다.
- 화면은 127.0.0.1 에만 열리고, 보내기 같은 요청은 띄울 때마다 새로 만드는 토큰이 있어야 합니다.
- 계정: 이 저장소 안에서 돌면 키트 공통 설정(저장소 맨 위 `config.local.json` 의 `mail` · `dispatch`)을 그대로 씁니다.
  다른 PC 는 `%APPDATA%\DispatchChat\config.json`(비밀번호는 그 PC 사용자 DPAPI 로 암호화). 로그는 `%LOCALAPPDATA%\DispatchChat\chat.log`.
- 보내는 방법(`send_mode`)은 `dispatch.chat_send_mode`, 없으면 `dispatch.reply_mode` 를 따릅니다 —
  자기에게 보낸 메일을 메일 규칙이 딴 폴더로 옮기는 서버면 `append`(받은편지함에 바로 넣기).
- 포트가 겹치면 `DISPATCH_CHAT_PORT` 환경변수로 바꿉니다.

## exe 만들기

```
..\macro-hub\.venv\Scripts\python.exe build.py      → dist\DispatchChat.exe (git 제외)
```

## 확인

`python -X utf8 -m unittest tests.test_dispatch_chat` — 게이트웨이가 실제로 만드는 회신 메일을 먹여 대화 묶기·선택지·보낼 제목을 확인합니다.
