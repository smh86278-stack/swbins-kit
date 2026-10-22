// 기록 — 최근 부탁과 AI 답. 원문이 길 수 있어 목록에는 앞부분만 쓴다.
export async function init() {
  await app.dbScript(`
    CREATE TABLE IF NOT EXISTS history (
      id INTEGER PRIMARY KEY,
      mode TEXT NOT NULL,
      instruction TEXT NOT NULL DEFAULT '',
      input TEXT NOT NULL,
      output TEXT NOT NULL,
      engine TEXT NOT NULL DEFAULT '',
      at TEXT NOT NULL
    );
  `);
}

export const add = (h) =>
  app.db("INSERT INTO history (mode, instruction, input, output, engine, at) VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))",
         [h.mode, h.instruction || '', h.input, h.output, h.engine || '']);

export async function recent(limit = 30) {
  return (await app.db('SELECT * FROM history ORDER BY id DESC LIMIT ?', [limit])).rows;
}

export const clear = () => app.db('DELETE FROM history');
