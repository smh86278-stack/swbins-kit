// 데이터 — entries(날짜·분류·숫자·메모). 집계는 SQL 로.
export async function init() {
  await app.dbScript(`
    CREATE TABLE IF NOT EXISTS entries (
      id INTEGER PRIMARY KEY,
      day TEXT NOT NULL,
      category TEXT NOT NULL,
      amount REAL NOT NULL,
      note TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS entries_day ON entries(day);
  `);
}

export const add = (e) =>
  app.db('INSERT INTO entries (day, category, amount, note) VALUES (?, ?, ?, ?)', [e.day, e.category, e.amount, e.note || '']);

export const remove = (id) => app.db('DELETE FROM entries WHERE id = ?', [id]);

export async function recent(limit = 20) {
  return (await app.db('SELECT * FROM entries ORDER BY day DESC, id DESC LIMIT ?', [limit])).rows;
}

export async function categories() {
  return (await app.db('SELECT category, SUM(amount) AS total, COUNT(*) AS n FROM entries GROUP BY category ORDER BY total DESC')).rows;
}

export async function daily(days = 30) {
  return (await app.db("SELECT day, SUM(amount) AS total FROM entries WHERE day >= date('now','localtime', ?) GROUP BY day ORDER BY day",
                       [`-${days - 1} days`])).rows;
}

export async function monthTotals() {
  const { rows } = await app.db(`
    SELECT
      COALESCE(SUM(CASE WHEN strftime('%Y-%m', day) = strftime('%Y-%m', 'now', 'localtime') THEN amount END), 0) AS this_month,
      COALESCE(SUM(CASE WHEN strftime('%Y-%m', day) = strftime('%Y-%m', 'now', 'localtime', 'start of month', '-1 month') THEN amount END), 0) AS last_month,
      COUNT(*) AS n,
      COALESCE(SUM(amount), 0) AS all_total
    FROM entries`);
  return rows[0];
}
