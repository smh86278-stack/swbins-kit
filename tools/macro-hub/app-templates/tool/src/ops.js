// 변환 규칙 — 글 → 글 순수 함수. 새 규칙은 OPS 에 하나 더하면 화면에 체크칸이 생긴다.
const lines = (t) => t.split(/\r?\n/);

export const OPS = [
  { id: 'trim', name: '앞뒤 공백 지우기', fn: (t) => lines(t).map((l) => l.trim()).join('\n') },
  { id: 'spaces', name: '연속 공백 하나로', fn: (t) => lines(t).map((l) => l.replace(/[ \t]+/g, ' ')).join('\n') },
  { id: 'blank', name: '빈 줄 지우기', fn: (t) => lines(t).filter((l) => l.trim() !== '').join('\n') },
  { id: 'dedupe', name: '중복 줄 지우기', fn: (t) => [...new Set(lines(t))].join('\n') },
  { id: 'sort', name: '가나다 정렬', fn: (t) => lines(t).sort((a, b) => a.localeCompare(b, 'ko')).join('\n') },
  { id: 'number', name: '번호 붙이기', fn: (t) => lines(t).map((l, i) => `${i + 1}. ${l}`).join('\n') },
  { id: 'comma', name: '한 줄로(쉼표)', fn: (t) => lines(t).filter((l) => l.trim()).join(', ') },
];

export function apply(text, enabled) {
  return OPS.filter((o) => enabled.includes(o.id)).reduce((t, o) => o.fn(t), text);
}

export function stats(text) {
  const ls = text ? lines(text) : [];
  return { lines: ls.length, chars: text.length, unique: new Set(ls).size };
}

// CSV(쉼표·탭) 미리보기 — 따옴표 안 쉼표도 처리
export function parseTable(text) {
  const rows = [];
  for (const line of lines(text)) {
    if (!line.trim()) continue;
    const sep = line.includes('\t') ? '\t' : ',';
    const cells = [];
    let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else q = !q; }
      else if (ch === sep && !q) { cells.push(cur); cur = ''; }
      else cur += ch;
    }
    cells.push(cur);
    rows.push(cells);
  }
  return rows;
}
