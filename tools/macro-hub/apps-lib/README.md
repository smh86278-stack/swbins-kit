# 나만의 앱 동봉 라이브러리 (`/_lib/…`)

앱은 바깥 주소(CDN)를 못 쓰니(CSP) 자주 쓰는 라이브러리를 키트에 담아 둔다. `apphost.py` 가 모든 앱에 `/_lib/<파일>` 로 내준다.

| 파일 | 원본 | 라이선스 |
|---|---|---|
| `preact-htm.js` | htm@3.1.1 `preact/standalone.module.js` (Preact 10 포함) | htm Apache-2.0 (`LICENSE-htm.txt`) · Preact MIT (`LICENSE-preact.txt`) |
| `chart.umd.js` | chart.js@4.4.1 `dist/chart.umd.js` | MIT (`LICENSE-chartjs.txt`) |
| `phaser.min.js` | phaser@3.80.1 `dist/phaser.min.js` | MIT (`LICENSE-phaser.txt`) |
| `app-kit.css` | 키트가 직접 만든 기본 꾸밈 | 키트와 같음 |

2026-10-22 에 cdn.jsdelivr.net/npm 에서 받았다. 버전을 올릴 때는 같은 이름으로 바꿔 넣고 이 표를 고친다.
