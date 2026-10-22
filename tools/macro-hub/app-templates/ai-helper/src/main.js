// 화면 — 할 일 고르기 · 글 붙여 넣기 · AI 답(🤖 AI 작성 표시) · 기록. AI 는 app.ai(허브에서 고른 AI, 내 로그인).
import { html, render, useState, useEffect } from '/_lib/preact-htm.js';
import { MODES, byId } from './modes.js';
import * as db from './db.js';

function App() {
  const [mode, setMode] = useState('summary');
  const [instruction, setInstruction] = useState('');
  const [input, setInput] = useState('');
  const [result, setResult] = useState(null);       // {text, label}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState([]);
  const [copied, setCopied] = useState(false);

  const reload = async () => { try { setHistory(await db.recent()); } catch (e) { setError(e.message); } };
  useEffect(() => { db.init().then(reload).catch((e) => setError(e.message)); }, []);

  const ask = async () => {
    if (!input.trim()) return;
    const m = byId[mode];
    const system = mode === 'custom' ? instruction.trim() : m.system;
    if (mode === 'custom' && !system) { setError('직접 지시를 적어 주세요'); return; }
    setBusy(true); setError(''); setResult(null);
    try {
      const r = await app.ai(input, { system });
      setResult(r);
      await db.add({ mode, instruction: mode === 'custom' ? system : '', input, output: r.text, engine: r.engine });
      await reload();
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(result.text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch (e) { setError('복사하지 못했습니다'); }
  };

  const open = (h) => {
    setMode(h.mode); setInstruction(h.instruction); setInput(h.input);
    setResult({ text: h.output, label: '🤖 AI 작성 — ' + (h.engine || 'AI') + ' · ' + h.at.slice(5, 16) });
  };

  return html`
    <h1>🤖 AI 도우미</h1>
    <p class="hint">글을 붙여 넣고 할 일을 고르면 허브에서 고른 AI 가 써 줘요. 결과는 AI 가 쓴 것이니 확인하고 쓰세요.</p>
    ${error && html`<p class="error" id="error">${error}</p>`}
    <div class="layout">
      <section>
        <div class="card">
          <div class="modes">
            ${MODES.map((m) => html`<button class=${mode === m.id ? 'on' : ''} id=${'mode-' + m.id} onClick=${() => setMode(m.id)}>${m.name}</button>`)}
          </div>
          ${mode === 'custom' && html`<input id="instruction" style="width:100%;margin-bottom:8px" placeholder="AI 에게 할 말 (예: 고객에게 보낼 사과문으로)"
                                         value=${instruction} onInput=${(e) => setInstruction(e.target.value)} />`}
          <textarea id="input" placeholder="여기에 글을 붙여 넣기" value=${input} onInput=${(e) => setInput(e.target.value)} />
          <div class="row" style="margin-top:8px">
            <span class="muted grow">${input.length.toLocaleString()}자</span>
            <button class="pri" id="ask" onClick=${ask} disabled=${busy || !input.trim()}>${busy ? 'AI 가 쓰는 중…' : byId[mode].name + ' 해 줘'}</button>
          </div>
        </div>
        ${(busy || result) && html`
          <div class="card" style="margin-top:12px">
            ${busy ? html`<p class="busy">AI 가 쓰는 중이에요… (내용에 따라 수십 초)</p>` : html`
              <span class="ai-mark" id="ai-mark">${result.label}</span>
              <div class="result" id="result">${result.text}</div>
              <div class="row" style="justify-content:flex-end;margin-top:8px"><button id="copy" onClick=${copy}>${copied ? '복사됨 ✓' : '복사'}</button></div>`}
          </div>`}
      </section>
      <aside class="card">
        <div class="row"><h2 class="grow" style="margin:0">기록</h2>
          ${history.length > 0 && html`<button class="ghost" onClick=${async () => { if (confirm('기록을 모두 지울까요?')) { await db.clear(); reload(); } }}>모두 지우기</button>`}</div>
        ${history.length === 0 ? html`<p class="empty">아직 기록이 없어요</p>` : html`
          <ul class="history" id="history">${history.map((h) => html`
            <li key=${h.id} onClick=${() => open(h)}>${(byId[h.mode] || {}).name || h.mode} · ${h.input.slice(0, 40)}
              <small>${h.at.slice(5, 16)} · ${h.engine}</small></li>`)}</ul>`}
      </aside>
    </div>`;
}

render(html`<${App} />`, document.getElementById('root'));
