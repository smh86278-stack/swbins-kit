// 화면 — 왼쪽 원본, 가운데 규칙 체크, 오른쪽 결과(복사). 규칙은 ops.js.
import { html, render, useState, useMemo } from '/_lib/preact-htm.js';
import { OPS, apply, stats, parseTable } from './ops.js';

function App() {
  const [text, setText] = useState('');
  const [enabled, setEnabled] = useState(['trim', 'blank']);
  const [table, setTable] = useState(false);
  const [copied, setCopied] = useState(false);
  const out = useMemo(() => apply(text, enabled), [text, enabled]);
  const sIn = stats(text), sOut = stats(out);
  const rows = useMemo(() => (table ? parseTable(out).slice(0, 50) : []), [table, out]);

  const toggle = (id) => setEnabled(enabled.includes(id) ? enabled.filter((x) => x !== id) : [...enabled, id]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(out); } catch (e) {
      const ta = document.getElementById('output'); ta.select(); document.execCommand('copy');
    }
    setCopied(true); setTimeout(() => setCopied(false), 1500);
  };

  return html`
    <h1>🧹 텍스트 손질</h1>
    <p class="hint">왼쪽에 붙여 넣고 규칙을 고르면 오른쪽에 바로 정리돼요. 글은 이 PC 밖으로 나가지 않아요.</p>
    <div class="ops card">
      ${OPS.map((o) => html`<label><input type="checkbox" id=${'op-' + o.id} checked=${enabled.includes(o.id)} onChange=${() => toggle(o.id)} />${o.name}</label>`)}
      <label><input type="checkbox" id="op-table" checked=${table} onChange=${() => setTable(!table)} />표로 미리보기(CSV·탭)</label>
    </div>
    <div class="panes">
      <div class="card">
        <div class="pane-head"><b>원본</b><span>${sIn.lines}줄 · ${sIn.chars}자</span></div>
        <textarea id="input" placeholder="여기에 붙여 넣기" value=${text} onInput=${(e) => setText(e.target.value)} />
      </div>
      <div class="card">
        <div class="pane-head"><b>결과</b><span id="out-stats">${sOut.lines}줄 · 중복 없는 줄 ${sOut.unique}</span>
          <button class="pri" id="copy" onClick=${copy} disabled=${!out}>${copied ? '복사됨 ✓' : '복사'}</button></div>
        <textarea id="output" readonly value=${out} />
      </div>
    </div>
    ${table && rows.length > 0 && html`
      <div class="card"><table class="preview" id="preview">
        <tbody>${rows.map((r, i) => html`<tr>${r.map((c) => (i === 0 ? html`<th>${c}</th>` : html`<td>${c}</td>`))}</tr>`)}</tbody>
      </table></div>`}
  `;
}

render(html`<${App} />`, document.getElementById('root'));
