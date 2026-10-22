// 화면 — Preact + htm. 데이터는 db.js 로만.
import { html, render, useState, useEffect, useCallback } from '/_lib/preact-htm.js';
import * as db from './db.js';

function ItemForm({ initial, onSave, onCancel }) {
  const [title, setTitle] = useState(initial?.title || '');
  const [status, setStatus] = useState(initial?.status || 'todo');
  const [memo, setMemo] = useState(initial?.memo || '');
  const submit = (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    onSave({ title: title.trim(), status, memo: memo.trim() });
    if (!initial) { setTitle(''); setMemo(''); setStatus('todo'); }
  };
  return html`
    <form class="form card" onSubmit=${submit}>
      <input id="title" placeholder="항목 이름" value=${title} onInput=${(e) => setTitle(e.target.value)} required />
      <select id="status" value=${status} onChange=${(e) => setStatus(e.target.value)}>
        ${Object.entries(db.STATUS).map(([k, v]) => html`<option value=${k}>${v}</option>`)}
      </select>
      <div class="row">
        <button class="pri" id="save">${initial ? '고치기' : '추가'}</button>
        ${onCancel && html`<button type="button" class="ghost" onClick=${onCancel}>취소</button>`}
      </div>
      <textarea id="memo" placeholder="메모 (선택)" value=${memo} onInput=${(e) => setMemo(e.target.value)} />
    </form>`;
}

function App() {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);

  const reload = useCallback(async () => {
    try {
      setItems(await db.list({ q, status }));
      setCounts(await db.counts());
      setError('');
    } catch (e) { setError(e.message); }
  }, [q, status]);

  useEffect(() => { db.init().then(() => setReady(true)).catch((e) => setError(e.message)); }, []);
  useEffect(() => { if (ready) reload(); }, [ready, reload]);

  const run = (fn) => async (...a) => { try { await fn(...a); await reload(); } catch (e) { setError(e.message); } };
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return html`
    <h1>📋 목록 관리</h1>
    <p class="hint">항목을 적고 상태별로 관리해요. 데이터는 이 앱 전용 DB 에만 저장돼요.</p>
    ${error && html`<p class="error" id="error">${error}</p>`}
    <${ItemForm} onSave=${run(db.add)} />
    <div class="row toolbar">
      <input class="grow" id="search" placeholder="🔍 찾기" value=${q} onInput=${(e) => setQ(e.target.value)} />
      <div class="row counts">
        <button class=${status === '' ? 'on' : ''} onClick=${() => setStatus('')}>전체 ${total}</button>
        ${Object.entries(db.STATUS).map(([k, v]) => html`
          <button class=${status === k ? 'on' : ''} onClick=${() => setStatus(k)}>${v} ${counts[k] || 0}</button>`)}
      </div>
    </div>
    ${editing && html`<${ItemForm} initial=${editing} onCancel=${() => setEditing(null)}
                         onSave=${run(async (v) => { await db.update(editing.id, v); setEditing(null); })} />`}
    <div class="card">
      ${items.length === 0
        ? html`<div class="empty" id="empty">${q || status ? '찾는 항목이 없어요' : '아직 항목이 없어요 — 위에서 추가해 보세요'}</div>`
        : html`<table id="list">
            <thead><tr><th>항목</th><th>상태</th><th>메모</th><th>고친 때</th><th></th></tr></thead>
            <tbody>${items.map((it) => html`
              <tr class=${it.status} key=${it.id}>
                <td class="title">${it.title}</td>
                <td><span class=${'status ' + it.status}>${db.STATUS[it.status] || it.status}</span></td>
                <td class="memo" title=${it.memo}>${it.memo}</td>
                <td class="muted">${it.updated.slice(5, 16)}</td>
                <td class="row" style="justify-content:flex-end">
                  <button class="ghost" title="고치기" onClick=${() => setEditing(it)}>✎</button>
                  <button class="ghost" title="지우기" onClick=${run(async () => { if (confirm('지울까요? ' + it.title)) await db.remove(it.id); })}>✕</button>
                </td>
              </tr>`)}
            </tbody>
          </table>`}
    </div>`;
}

render(html`<${App} />`, document.getElementById('root'));
