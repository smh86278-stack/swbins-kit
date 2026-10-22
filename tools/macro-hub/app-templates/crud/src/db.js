// 데이터 — 이 앱 전용 DB(app.db). 화면 코드는 이 파일의 함수만 부른다.
export const STATUS = { todo: '할 일', doing: '진행 중', done: '완료' };

export async function init() {
  await app.dbScript(`
    CREATE TABLE IF NOT EXISTS items (
      id INTEGER PRIMARY KEY,
      title TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'todo',
      memo TEXT NOT NULL DEFAULT '',
      created TEXT NOT NULL,
      updated TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS items_status ON items(status);
  `);
}

export async function list({ q = '', status = '' } = {}) {
  const where = [], params = [];
  if (q) { where.push('(title LIKE ? OR memo LIKE ?)'); params.push(`%${q}%`, `%${q}%`); }
  if (status) { where.push('status = ?'); params.push(status); }
  const sql = 'SELECT * FROM items' + (where.length ? ' WHERE ' + where.join(' AND ') : '') +
              " ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END, updated DESC";
  return (await app.db(sql, params)).rows;
}

export async function counts() {
  const { rows } = await app.db('SELECT status, COUNT(*) AS n FROM items GROUP BY status');
  return Object.fromEntries(rows.map((r) => [r.status, r.n]));
}

export async function add({ title, status = 'todo', memo = '' }) {
  return app.db("INSERT INTO items (title, status, memo, created, updated) VALUES (?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))",
                [title, status, memo]);
}

export async function update(id, { title, status, memo }) {
  return app.db("UPDATE items SET title = ?, status = ?, memo = ?, updated = datetime('now','localtime') WHERE id = ?",
                [title, status, memo, id]);
}

export async function remove(id) {
  return app.db('DELETE FROM items WHERE id = ?', [id]);
}
