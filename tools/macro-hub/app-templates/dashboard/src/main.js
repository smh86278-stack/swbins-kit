// 화면 연결 — 요약 숫자·차트·최근 기록. 데이터는 db.js, 차트는 charts.js.
import * as db from './db.js';
import * as charts from './charts.js';

const $ = (s) => document.querySelector(s);
const fmt = (n) => Number(n).toLocaleString('ko-KR', { maximumFractionDigits: 2 });

function showError(e) {
  $('#error').textContent = e.message;
  $('#error').hidden = false;
}

function stat(label, value, extra = '') {
  const c = document.createElement('div');
  c.className = 'card stat';
  c.innerHTML = '<b></b><span></span>';
  c.querySelector('b').textContent = value;
  c.querySelector('span').textContent = label;
  if (extra) {
    const s = document.createElement('small');
    s.className = extra.startsWith('▲') ? 'up' : 'down';
    s.textContent = ' ' + extra;
    c.querySelector('span').append(s);
  }
  return c;
}

async function refresh() {
  const [m, cats, days, recent] = await Promise.all([db.monthTotals(), db.categories(), db.daily(30), db.recent(20)]);
  const diff = m.last_month ? ((m.this_month - m.last_month) / Math.abs(m.last_month)) * 100 : null;
  $('#stats').replaceChildren(
    stat('이번 달 합계', fmt(m.this_month), diff == null ? '' : (diff >= 0 ? '▲ ' : '▼ ') + Math.abs(diff).toFixed(1) + '%'),
    stat('지난달 합계', fmt(m.last_month)),
    stat('전체 기록', fmt(m.n) + '건'),
    stat('분류', cats.length + '개'),
  );
  $('#cats').replaceChildren(...cats.map((c) => Object.assign(document.createElement('option'), { value: c.category })));
  charts.trend(days, 30);
  charts.share(cats);
  const body = $('#recent tbody');
  body.replaceChildren();
  for (const r of recent) {
    const tr = document.createElement('tr');
    for (const [v, cls] of [[r.day, ''], [r.category, ''], [fmt(r.amount), 'num'], [r.note, 'muted']]) {
      const td = document.createElement('td');
      td.textContent = v;
      if (cls) td.className = cls;
      tr.append(td);
    }
    const td = document.createElement('td');
    const del = Object.assign(document.createElement('button'), { className: 'ghost', textContent: '✕', title: '지우기' });
    del.onclick = () => db.remove(r.id).then(refresh).catch(showError);
    td.append(del);
    tr.append(td);
    body.append(tr);
  }
  $('#empty').hidden = recent.length > 0;
  $('#recent').hidden = recent.length === 0;
}

$('#date').value = new Date().toLocaleDateString('sv-SE');
$('#add').onsubmit = async (ev) => {
  ev.preventDefault();
  try {
    await db.add({ day: $('#date').value, category: $('#category').value.trim(), amount: Number($('#amount').value), note: $('#note').value.trim() });
    $('#amount').value = '';
    $('#note').value = '';
    await refresh();
    $('#amount').focus();
  } catch (e) { showError(e); }
};

db.init().then(refresh).catch(showError);
