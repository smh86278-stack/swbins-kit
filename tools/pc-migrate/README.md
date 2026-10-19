# PC 이전 — 새 PC 로 옮기기

PC 를 바꿀 때 **설치·clone 으로는 다시 오지 않는 것**만 골라 암호 걸린 `.7z` 하나로 묶고(`pack.ps1`),
새 PC 에서 풀어 넣습니다(`restore.ps1`). 원본은 건드리지 않습니다.

| 담는 것 | 어디서 | 새 PC 에서 |
|---|---|---|
| Claude Code 대화 기록·메모리·지침·스킬·훅 | `~\.claude` | 자동으로 넣음(있으면 안 덮음) |
| MCP 서버 목록 | `~\.claude.json` 의 `mcpServers` 만 | `-MergeMcp` 일 때 없는 것만 더함 |
| 키트 설정 · 내 자동화 · 켜 둔 상태 · 가져온 스킨 | `config.local.json` · `macros.local\` 등 | 자동으로 넣음(있으면 `.imported` 로 옆에) |
| 저장소의 커밋 안 한 파일 · `.env` 같은 제외 파일 | 설정 `migrate.repos` | 명령을 알려 줌(robocopy) |
| 저장소의 커밋 안 한 수정분 | 〃 (`git diff`) | 명령을 알려 줌(`git apply`) |
| 원격 어디에도 없는 로컬 브랜치 | 〃 (`git bundle`) | 명령을 알려 줌(`git fetch`) |
| 환경변수 값(토큰 등) | 설정 `migrate.env_vars` | `-SetEnv` 일 때 없는 것만 넣음 |
| 그 밖에 챙길 파일·폴더 | 설정 `migrate.extra_paths` | 원래 위치를 알려 줌 |

담지 않는 것: Claude Code 로그인(`.credentials.json`)·`plugins\`·`settings.json`,
로그·크래시 덤프, `node_modules`·`.venv`·`target`·`build`·`dist` 처럼 다시 만들 수 있는 것,
저장소 안에 든 다른 저장소(다시 clone 하라고 알려 줍니다).

## 1. 설정 (`config.local.json`)

```json
"migrate": {
  "repos": ["%USERPROFILE%\\work\\my-app"],
  "env_vars": ["JIRA_TOKEN", "GITLAB_TOKEN"],
  "extra_paths": ["%USERPROFILE%\\.ssh"],
  "claude_projects": []
}
```

`claude_projects` 를 비우면 임시 폴더를 뺀 Claude Code 대화 폴더를 모두 담습니다.

## 2. 지금 PC 에서 묶기

1. 저장소마다 커밋·push 할 것은 미리 한다(묶음은 안전망이다).
2. **Claude Code 를 모두 닫는다** — 열려 있는 대화는 기록 끝이 잘린다.
3. **따로 연 PowerShell 창**에서(`Win + R` → `powershell`) — 암호를 입력받아야 해서 Claude Code 안에서는 안 된다.

```
powershell -ExecutionPolicy Bypass -File "<키트 위치>\tools\pc-migrate\pack.ps1" -DryRun    # 무엇이 담기는지·크기
powershell -ExecutionPolicy Bypass -File "<키트 위치>\tools\pc-migrate\pack.ps1"            # 바탕화면\pc-migration.7z
```

- 반디집이나 7-Zip 이 있어야 한다(반디집 → 7-Zip 순으로 찾는다). 암호를 두 번 묻고, 파일 이름까지 암호화한다.
- 압축을 시험으로 풀어 본 뒤 평문 폴더를 지운다(남기려면 `-KeepFolder`).
- `.7z` 는 회사가 허용하는 방법(암호화 USB 등)으로만 옮긴다. 암호를 잃으면 못 푼다.

## 3. 새 PC 에서 풀기

1. Claude Code 설치 → 한 번 실행해 로그인 · 키트 설치 · 저장소 clone(`--recurse-submodules`).
2. `.7z` 를 풀고, 풀린 폴더 안에서:

```
powershell -ExecutionPolicy Bypass -File restore.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File restore.ps1 -SetEnv -MergeMcp
```

3. 화면에 나온 저장소 명령(robocopy · `git apply` · `git fetch`)을 실행한다.
4. 키트 「메일·계정 설정」에서 비밀번호를 다시 넣는다 — Windows 가 PC 에 묶어 암호화한 값이라 옮겨도 풀리지 않는다.
5. 허브에서 자동화가 켜져 있는지 보고, 풀린 폴더를 지운다.

작업 폴더 경로가 옛 PC 와 다르면 Claude Code 대화가 안 보인다 — `-ProjectMap "C--work-app=D--src-app"` 로 이름을 바꿔 넣는다
(폴더 이름 = 경로에서 영숫자가 아닌 글자를 `-` 로 바꾼 것).

## 4. 옛 PC 정리 (반납 직전)

키트 제거(`uninstall.py` 또는 Windows 「앱」에서 제거) — 자동 시작·바로가기가 같이 지워진다.
