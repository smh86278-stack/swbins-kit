// 메모장 견본 — app.db(sql, params) 로 이 앱 전용 DB 를 쓴다(허브 「✨ 앱」 탭에서 db 권한을 허락해야 동작)
const $ = (s) => document.querySelector(s);

function showError(e) {
  $('#err').textContent = e.message;
  $('#err').hidden = false;
}

async function load() {
  const { rows } = await app.db('SELECT id, text, created FROM notes ORDER BY id DESC');
  const list = $('#list');
  list.replaceChildren();
  for (const n of rows) {
    const li = document.createElement('li');
    const span = document.createElement('span');
    span.textContent = n.text;
    const time = document.createElement('time');
    time.textContent = n.created.slice(5, 16);
    const del = document.createElement('button');
    del.textContent = '✕';
    del.title = '지우기';
    del.onclick = () => app.db('DELETE FROM notes WHERE id = ?', [n.id]).then(load).catch(showError);
    li.append(span, time, del);
    list.append(li);
  }
}

$('#add').onsubmit = async (ev) => {
  ev.preventDefault();
  const text = $('#text').value.trim();
  if (!text) return;
  try {
    await app.db("INSERT INTO notes (text, created) VALUES (?, datetime('now', 'localtime'))", [text]);
    $('#text').value = '';
    await load();
  } catch (e) { showError(e); }
};

app.dbScript('CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created TEXT NOT NULL)')
  .then(load)
  .catch(showError);
