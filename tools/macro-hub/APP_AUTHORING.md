# 나만의 앱 만들기 안내 — AI 가 따르는 순서

허브의 「✨ 나만의 앱」(설계서 쓰기 · 만들기 · 말로 고치기)이 이 파일을 먼저 읽으라고 한다. 사람용 설명은 `README.md`.
목표는 **전문가가 만든 것 같은 앱** — 설계서대로, 구조를 나눠, 스스로 열어 검사하고, 안 되면 고쳐서, 쉬운 말로 보고한다.

## 앱 하나 = 폴더 하나

```
apps.local\<id>\              (id = 영문 소문자·숫자·하이픈, 주소 http://<id>.localhost:8631/ 가 된다)
  app.json        {"name", "icon", "kind": "app"|"game"|"ai", "version", "desc",
                   "permissions": ["db", "files", "ai", "run", "notify"] 중 쓰는 것만, "macros": ["local/<자동화>"] (run 일 때)}
  spec.md         설계서 — 목적 · 화면 · 데이터 · 동작 · 완료 기준. 만들기 전에 먼저 쓰고 사람이 확인한다
  index.html      시작 화면
  src\*.js        기능별로 파일을 나눈다(main.js 하나에 다 넣지 않는다 — 화면·데이터·계산을 갈라서)
  style.css       화면 꾸밈
  assets\         그림·소리 (직접 만든 SVG·CSS 그림을 우선. 저작권 있는 그림 금지)
  tests\smoke.json   검사 시나리오 (아래)
```

**고치는 곳은 그 앱 폴더 하나뿐.** 허브·키트 코드, 다른 앱, 설정 파일, 견본(`apps\`)은 건드리지 않는다.

## 이 환경의 규칙 (어기면 화면에서 막힌다)

- **바깥 주소를 못 쓴다** — CDN(`https://unpkg.com/…`)·외부 API·웹폰트 모두 CSP 로 막힌다. 라이브러리는 아래 동봉본만.
- **npm·빌드 없음** — 브라우저가 그대로 읽는 JS(ES 모듈 `<script type="module">` 가능).
- 데이터는 `/_app.js` 도우미로 — localStorage 대신 **앱 전용 DB**(권한 `db`). 사람이 허브에서 권한을 허락해야 동작하니,
  허락 전 오류(403)는 화면에 "허브 「✨ 나만의 앱」에서 '데이터 저장'을 허락하세요" 처럼 안내한다.

### 동봉 라이브러리 `/_lib/…`

| 주소 | 무엇 | 쓰는 법 |
|---|---|---|
| `/_lib/preact-htm.js` | Preact + htm (화면 컴포넌트, JSX 없이) | `import { html, render, useState, useEffect } from '/_lib/preact-htm.js'` |
| `/_lib/chart.umd.js` | Chart.js 4 (차트) | `<script src="/_lib/chart.umd.js"></script>` → `new Chart(canvas, {...})` |
| `/_lib/phaser.min.js` | Phaser 3.80 (2D 게임) | `<script src="/_lib/phaser.min.js"></script>` → `new Phaser.Game({...})` |
| `/_lib/app-kit.css` | 기본 꾸밈(밝음·어두움 자동, 카드·표·단추·입력) | `<link rel="stylesheet" href="/_lib/app-kit.css">` |
| `/_app.js` | 앱 도우미 | `<script src="/_app.js"></script>` → `window.app` |

### `window.app`

```js
await app.info()                              // {id, name, version, permissions, approved}
await app.dbScript('CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, name TEXT)')   // 여러 문장, 값 없이
const { rows } = await app.db('SELECT * FROM t WHERE name = ?', ['a'])                // 조회 → rows
const { changes, last_id } = await app.db('INSERT INTO t (name) VALUES (?)', ['b'])   // 변경
```
값은 꼭 `?` 자리에 넣는다(문자열 이어 붙이기 금지). 한 번에 5000줄까지.

다른 권한(app.json `permissions` 에 적고 사람이 허락해야 동작):

```js
// files — 이 앱 전용 파일 상자(하나 5MB·합계 100MB). 사람이 고른 파일은 <input type="file"> 로 읽어 write 한다
await app.files.write('reports/10월.csv', csvText)            // 바이너리는 app.files.write(p, b64, {base64: true})
const { data } = await app.files.read('reports/10월.csv')
const { files } = await app.files.list()                        // [{path, size, modified}]
await app.files.remove('reports/10월.csv')

// ai — 허브에서 고른 AI(Claude·Codex·Gemini·로컬)에게 글만. 한 번에 하나, 앱마다 시간당 60번
const r = await app.ai(본문, { system: '아래 글을 3줄로 요약해' })  // {text, engine, label}
// ⚠ AI 가 쓴 글을 보여 줄 때는 r.label('🤖 AI 작성 — …')을 꼭 같이 보여 준다(AI 기본법 — 생성물 표시)

// run — app.json "macros": ["local/daily_report"] 에 적은 내 자동화만
const x = await app.run('local/daily_report', { 날짜: '2026-10-22' }, { wait: 60 })  // {run, status, lines}
const y = await app.runStatus(x.run)                                            // 안 끝났으면 나중에 다시

// notify — 허브 알림 출구(메일·슬랙…)로 '✨ 앱 이름 — 제목'. 시간당 20번
await app.notify('재고 부족', '볼펜 3개 남음')
```
검사(appcheck)에서는 ai·run·notify 가 **가짜**로 답한다 — AI 답은 '(검사용 가짜 AI 답) …', 알림·자동화는 실제로 안 간다.

## 순서

1. **설계서(`spec.md`)** — 부탁만 받았으면 먼저 설계서를 쓰고 멈춘다. 형식:
   `## 목적` · `## 화면`(구역별) · `## 데이터`(테이블·열) · `## 동작`(누르면 무엇) · `## 완료 기준`(검사로 확인할 것 3~6개).
2. **만들기** — 설계서대로. 템플릿에서 시작했으면 그 구조를 살린다. 빈 상태·오류·긴 글·많은 데이터도 보기 좋게.
3. **검사 시나리오** — `tests\smoke.json` 을 완료 기준에 맞춰 고친다(형식은 아래).
4. **검사 실행** — 허브 폴더에서
   ```
   "<허브 파이썬>" appcheck.py <id>
   ```
   (부탁 글에 정확한 명령이 있다.) 진짜 브라우저로 열어 콘솔 오류·시나리오·스크린샷을 본다. 마지막 줄 `🔍 검사 결과: 성공|실패`.
   검사는 **임시 데이터**로 돈다(사람의 앱 데이터는 그대로).
5. **실패하면 고쳐서 다시** — 최대 3번. 스크린샷(`.check\check.png`)도 열어 보고 화면이 깨졌는지 본다.
6. **보고** — 쉬운 말로: 무엇을 만들었나 · 어떻게 쓰나 · 허락할 권한 · 검사 결과 · 남은 한계.

## `tests\smoke.json`

```json
{"steps": [
  {"fill": "#text", "value": "첫 메모"},
  {"press": "#text", "key": "Enter"},
  {"click": "text=저장"},
  {"expect_text": "첫 메모"},
  {"expect": "#list li", "count_at_least": 1},
  {"wait": 300}
]}
```
선택자는 Playwright 형식(`#id`, `.class`, `text=글자`, `button:has-text("추가")`). 게임처럼 누르기 어려운 화면은
`{"expect": "canvas"}` 와 `{"eval": "window.game && window.game.isRunning"}`(참이어야 통과) 로 확인한다.

## 게임 (`kind: game`)

- Phaser 장면(Scene)을 파일로 나눈다(`src\scenes\*.js`). 그림은 `this.add.rectangle`·`graphics`·직접 만든 SVG 로.
- `window.game = new Phaser.Game(...)` 로 두어 검사가 상태를 볼 수 있게. 최고 점수는 DB 에.
- 키보드·마우스·터치 모두. 일시정지·다시 시작.
