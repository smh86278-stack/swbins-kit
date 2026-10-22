// 최고 점수 — 앱 전용 DB. 권한이 없으면(허락 전) 이번 판 동안만 기억한다.
let memory = 0;

export async function init() {
  try {
    await app.dbScript('CREATE TABLE IF NOT EXISTS scores (id INTEGER PRIMARY KEY, score INTEGER NOT NULL, at TEXT NOT NULL)');
  } catch (e) { console.warn('최고 점수 저장 안 됨 —', e.message); }
}

export async function best() {
  try {
    const { rows } = await app.db('SELECT COALESCE(MAX(score), 0) AS best FROM scores');
    return Math.max(rows[0].best, memory);
  } catch (e) { return memory; }
}

export async function save(score) {
  memory = Math.max(memory, score);
  try {
    await app.db("INSERT INTO scores (score, at) VALUES (?, datetime('now','localtime'))", [score]);
  } catch (e) { /* 허락 전이면 기억만 */ }
}
