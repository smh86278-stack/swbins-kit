// 차트 — Chart.js(/_lib/chart.umd.js, 전역 Chart). 다시 그릴 때 옛 차트를 지운다.
const charts = {};
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const PALETTE = ['#8a7cf0', '#4cb5ae', '#f0a35e', '#e2738c', '#6aa8e6', '#9bc46b', '#c792ea', '#a0a0b0'];

function draw(id, config) {
  charts[id]?.destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

export function lastDays(days) {
  const out = [];
  const d = new Date();
  d.setDate(d.getDate() - (days - 1));
  for (let i = 0; i < days; i++) {
    out.push(d.toLocaleDateString('sv-SE'));
    d.setDate(d.getDate() + 1);
  }
  return out;
}

export function trend(rows, days = 30) {
  const by = Object.fromEntries(rows.map((r) => [r.day, r.total]));
  const labels = lastDays(days);
  draw('trend', {
    type: 'line',
    data: { labels: labels.map((l) => l.slice(5)),
            datasets: [{ data: labels.map((l) => by[l] || 0), borderColor: css('--accent'), backgroundColor: css('--accent-soft'),
                         fill: true, tension: 0.3, pointRadius: 2 }] },
    options: { plugins: { legend: { display: false } }, animation: false,
               scales: { x: { ticks: { color: css('--muted'), maxTicksLimit: 8 }, grid: { display: false } },
                         y: { ticks: { color: css('--muted') }, grid: { color: css('--line') }, beginAtZero: true } } },
  });
}

export function share(rows) {
  draw('share', {
    type: 'doughnut',
    data: { labels: rows.map((r) => r.category),
            datasets: [{ data: rows.map((r) => r.total), backgroundColor: rows.map((_, i) => PALETTE[i % PALETTE.length]), borderWidth: 0 }] },
    options: { animation: false, cutout: '62%', plugins: { legend: { position: 'bottom', labels: { color: css('--text'), boxWidth: 10 } } } },
  });
}
