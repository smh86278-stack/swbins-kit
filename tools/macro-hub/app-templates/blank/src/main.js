// 시작점 — 화면 컴포넌트는 Preact + htm(/_lib/preact-htm.js), 데이터는 app.db(...)
import { html, render } from '/_lib/preact-htm.js';

function App() {
  return html`
    <h1>✨ 새 앱</h1>
    <p class="hint">설계서(spec.md)를 쓰고 「만들기」를 누르면 AI 가 이 화면을 채웁니다.</p>
  `;
}

render(html`<${App} />`, document.getElementById('root'));
