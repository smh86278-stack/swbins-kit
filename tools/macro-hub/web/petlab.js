/* 펫 실험실(개발용) — /pet?lab=1 : 품종 × 소품을 한 화면에 그려 자리를 맞춘다. 허브에 저장하지 않는다(값만 보여 주고 복사).
     ?state=sleep    잠자는 그림으로(같은 틀)          ?marks=1  잰 자리(눈·정수리·머리 폭·목 선)를 표시
     ?acc=glasses,beret  보일 소품만                   ?kind=cat  강아지·고양이 한쪽만
     ?size=150  칸 크기(px)                            ?shot=1  화면 찍기용(위 칸 없이)
     ?breeds=shiba,maltese,cream  보일 품종만(계절 소품을 대표 품종으로만 볼 때)
   맞추기: 칸을 누르면 고른다 → 끌면 옮기고, 휠로 크기 → 위 칸에 skin.json 의 rig.acc 로 붙일 JSON 이 나온다(「복사」).
   「자동 측정」: 그림의 투명도·어두운 눈동자로 rig 의 eyes·crown·head·chin 을 다시 잰다(눈을 못 찾으면 EYES_MANUAL). */
window.PetLab = {
  EYES_MANUAL: {                                             // 눈을 잘못 찾는 그림(눈이 검은 털 안: 판다·턱시도, 어두운 귀 끝: 삼색이·샴)
    'panda.webp': [0.40, 0.275, 0.64, 0.27], 'cat-tuxedo.webp': [0.345, 0.28, 0.545, 0.28],
    'cat-calico.webp': [0.42, 0.308, 0.59, 0.308], 'cat-siamese.webp': [0.385, 0.323, 0.595, 0.323],
  },
  pixels(img){
    const W = img.naturalWidth, H = img.naturalHeight, c = document.createElement('canvas'); c.width = W; c.height = H;
    const x = c.getContext('2d'); x.drawImage(img, 0, 0);
    return {W, H, d: x.getImageData(0, 0, W, H).data};
  },
  eyes({W, H, d}){                                           // 얼굴 쪽 어두운 덩어리 중 좌우 대칭인 한 쌍(web/skins/_source/plush/make_rigs.py 와 같은 방식)
    const A = (i, j) => d[(j * W + i) * 4 + 3], G = (i, j) => { const k = (j * W + i) * 4; return 0.299 * d[k] + 0.587 * d[k + 1] + 0.114 * d[k + 2]; };
    const y0 = Math.round(0.08 * H), y1 = Math.round(0.62 * H), f = (W / 512) ** 2;
    for (const thr of [45, 60, 75, 90]) {
      const on = (i, j) => G(i, j) < thr && A(i, j) > 200, lab = new Uint8Array(W * H), bs = [];
      for (let j = y0; j < y1; j++) for (let i = 0; i < W; i++) {
        if (lab[j * W + i] || !on(i, j)) continue;
        const st = [[i, j]]; lab[j * W + i] = 1; let a = 0, sx = 0, sy = 0, x0 = i, x1 = i, t0 = j, t1 = j;
        while (st.length) {
          const [p, q] = st.pop(); a++; sx += p; sy += q; x0 = Math.min(x0, p); x1 = Math.max(x1, p); t0 = Math.min(t0, q); t1 = Math.max(t1, q);
          for (let dq = -1; dq <= 1; dq++) for (let dp = -1; dp <= 1; dp++) {
            const P = p + dp, Q = q + dq;
            if (P >= 0 && P < W && Q >= y0 && Q < y1 && !lab[Q * W + P] && on(P, Q)) { lab[Q * W + P] = 1; st.push([P, Q]); }
          }
        }
        const w = x1 - x0 + 1, h = t1 - t0 + 1;
        if (a > 15 * f && a < 3500 * f && w / h > 0.45 && w / h < 2.2) bs.push({x: sx / a, y: sy / a, a});
      }
      let best = null;
      for (let i = 0; i < bs.length; i++) for (let k = i + 1; k < bs.length; k++) {
        const [l, r] = bs[i].x < bs[k].x ? [bs[i], bs[k]] : [bs[k], bs[i]], dx = r.x - l.x, dy = Math.abs(r.y - l.y);
        if (0.1 * W < dx && dx < 0.4 * W && dy < 0.05 * H && Math.max(l.a, r.a) / Math.min(l.a, r.a) < 2.5) {
          const sc = dy * 2 + Math.abs((l.x + r.x) / 2 - W * 0.52) * 0.5 - Math.min(l.a, r.a) * 0.002;
          if (!best || sc < best[0]) best = [sc, l, r];
        }
      }
      if (best) return [best[1].x / W, best[1].y / H, best[2].x / W, best[2].y / H];
    }
    return null;
  },
  span({W, H, d}, cx, y){                                    // y 줄에서 cx 를 품은 불투명 구간 [왼, 오] (0~1)
    const j = Math.round(y * H), A = i => d[(j * W + i) * 4 + 3] > 100;
    let l = Math.round(cx * W), r = l;
    if (!A(l)) return [cx, cx];
    while (l > 0 && A(l - 1)) l--;
    while (r < W - 1 && A(r + 1)) r++;
    return [l / W, r / W];
  },
  measure(img, file){                                        // → {eyes, crown, head, chin}
    const px = this.pixels(img), e = this.EYES_MANUAL[file] || this.eyes(px);
    if (!e) return null;
    const {W, H, d} = px, ex = (e[0] + e[2]) / 2, ey = (e[1] + e[3]) / 2, ed = e[2] - e[0], r3 = v => Math.round(v * 1000) / 1000;
    const tops = [];                                         // 정수리: 눈 가운데 세로줄 근처의 머리 윗선(가운데값) — 쫑긋한 귀 사이 이마
    for (let k = -3; k <= 3; k++) {
      const i = Math.round((ex + k * 0.01) * W);
      let j = 0; while (j < H && d[(j * W + i) * 4 + 3] <= 100) j++;
      tops.push(j / H);
    }
    tops.sort((a, b) => a - b);
    const crown = tops[3];
    const s = this.span(px, ex, ey), face = s[1] - s[0];    // 머리 폭: 눈 높이의 얼굴 폭 — 늘어진 귀까지 이어지면 넓어지니 눈 사이로 범위를 묶는다
    const head = Math.min(Math.max(face, 2.1 * ed), 2.9 * ed, 0.58);   // 그림 폭의 58% 넘게는 안 키운다(눈이 큰 크림·귀가 긴 닥스훈트)
    let best = null;                                         // 목 선: 눈 아래 0.6~1.25 눈사이에서 가장 좁은 줄(안 좁아지면 눈 아래 0.95)
    for (let y = ey + 0.6 * ed; y < Math.min(0.85, ey + 1.25 * ed); y += 0.005) {
      const t = this.span(px, ex, y), w = t[1] - t[0];
      if (!best || w < best[1] - 0.002) best = [y, w];
    }
    const chinY = best && best[1] < face * 0.92 ? best[0] : ey + 0.95 * ed;
    const cw = Math.min(Math.max(best ? Math.min(best[1], face) * 0.8 : 1.9 * ed, 1.6 * ed), 2.3 * ed);
    return {eyes: e.map(r3), crown: r3(crown), head: r3(head), chin: [r3(chinY), r3(cw)]};
  },
};
document.addEventListener('DOMContentLoaded', async () => {
  const q = new URLSearchParams(location.search), S = +(q.get('size') || 110), PAD = window.PetWarp ? PetWarp.PAD : 0.2;
  const skinId = q.get('skin') || PetSkin.DEFAULT;
  const m = await (await fetch('/skin/' + encodeURIComponent(skinId) + '/skin.json')).json();
  const accs = (q.get('acc') || Object.keys(PetAcc.ART).join(',')).split(',').filter(a => PetAcc.ART[a]);
  const kinds = q.get('kind') ? [q.get('kind')] : ['dog', 'cat'];
  const tune = {};                                           // 'dog:shiba' → {glasses: {dx, dy, s}} (손으로 맞춘 것)
  const measured = {};
  document.title = '펫 실험실';
  document.body.innerHTML = '';
  document.body.style.cssText = 'margin:0;padding:0 8px 8px;background:#f4efe6;color:#2b2723;overflow:auto;font:12px/1.4 "Malgun Gothic",sans-serif';
  document.documentElement.style.overflow = 'auto';
  const grid = document.createElement('div');
  grid.style.cssText = `display:grid;grid-template-columns:repeat(${accs.length + 1},${S}px);gap:2px`;
  document.body.append(grid);
  const panel = document.createElement('div');
  panel.style.cssText = 'position:sticky;top:0;z-index:1;margin:0 -8px 6px;background:#fffaf2;border-bottom:1px solid #8c8276;padding:6px 8px;display:flex;gap:8px;align-items:flex-start';
  panel.innerHTML = '<div style="width:220px"><b>펫 실험실</b><br><span id="sel">칸을 누르면 고릅니다</span><br>끌기 = 옮기기 · 휠 = 크기<br>' +
    '<button id="copy">복사</button> <button id="reset">고른 칸 되돌리기</button> <button id="meas">자동 측정</button></div>' +
    '<textarea id="out" style="flex:1;height:140px;font:11px monospace" spellcheck="false"></textarea>';
  document.body.prepend(panel); if (q.get('shot')) panel.style.display = 'none';   // ?shot=1 — 화면 찍기용(위 칸 없이)
  const out = panel.querySelector('#out');
  const rigOf = (kind, bid) => {
    const b = m.breeds[kind][bid], k = kind + ':' + bid;
    const rig = Object.assign({}, b.rig, measured[k] || {});
    rig.acc = Object.assign({}, (b.rig || {}).acc || {}, tune[k] || {});
    return rig;
  };
  const show = () => {
    const o = {};
    for (const [k, v] of Object.entries(tune)) { const [kind, bid] = k.split(':'); ((o[kind] = o[kind] || {})[bid] = rigOf(kind, bid).acc); }
    out.value = (Object.keys(measured).length ? '// 자동 측정(rig 에 덮어쓸 값)\n' + JSON.stringify(measured, null, 1) + '\n' : '') +
      (Object.keys(o).length ? '// rig.acc (품종별 소품 자리)\n' + JSON.stringify(o, null, 1) : '');
  };
  const imgs = {};
  const load = src => imgs[src] || (imgs[src] = new Promise(res => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; }));
  const cells = [];
  let sel = null;
  async function paint(cell){
    const {kind, bid, acc, cv} = cell, b = m.breeds[kind][bid];
    const file = (q.get('state') === 'sleep' && b.sleep) || b.alert || b.idle;
    const img = await load('/skin/' + skinId + '/' + file);
    const rig = rigOf(kind, bid), svg = PetAcc.svg(acc, rig);
    const over = svg ? await load('data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)) : null;
    const g = cv.getContext('2d'); g.clearRect(0, 0, cv.width, cv.height);
    if (img) g.drawImage(img, 0, PAD * cv.width, cv.width, cv.width);
    if (over) g.drawImage(over, 0, 0, cv.width, cv.height);
    if (q.get('marks') && rig.eyes) {
      const G = PetAcc.geom(rig), X = v => v / 100 * cv.width, Y = v => (v / 100 + PAD) * cv.width;
      g.strokeStyle = 'red'; g.lineWidth = 1;
      for (const [x, y] of [[rig.eyes[0], rig.eyes[1]], [rig.eyes[2], rig.eyes[3]]]) { g.beginPath(); g.arc(X(x * 100), Y(y * 100), 3, 0, 7); g.stroke(); }
      g.strokeStyle = 'blue'; g.beginPath(); g.moveTo(X(G.ex - G.hw / 2), Y(G.c)); g.lineTo(X(G.ex + G.hw / 2), Y(G.c)); g.stroke();
      g.strokeStyle = 'green'; g.beginPath(); g.moveTo(X(G.ex - G.cw / 2), Y(G.cy)); g.lineTo(X(G.ex + G.cw / 2), Y(G.cy)); g.stroke();
    }
    cell.box.style.outline = sel === cell ? '2px solid #cf6a52' : (tune[kind + ':' + bid] || {})[acc] ? '1px dashed #3f5c86' : '';
  }
  const only = q.get('breeds') ? q.get('breeds').split(',') : null;
  for (const kind of kinds) for (const bid of Object.keys(m.breeds[kind] || {})) {
    if (only && !only.includes(bid)) continue;
    const lab = document.createElement('div'); lab.textContent = kind + ' · ' + bid; lab.style.cssText = 'align-self:center;font-weight:bold';
    grid.append(lab);
    for (const acc of accs) {
      const box = document.createElement('div'); box.title = acc; box.style.cssText = 'background:#fff;cursor:grab;position:relative';
      const cv = document.createElement('canvas'); cv.width = S * 2; cv.height = Math.round(S * 2 * (1 + PAD)); cv.style.cssText = `width:${S}px;display:block`;
      box.append(cv); grid.append(box);
      const cell = {kind, bid, acc, cv, box}; cells.push(cell);
      box.onmousedown = ev => {
        const prev = sel; sel = cell; if (prev && prev !== cell) paint(prev);
        panel.querySelector('#sel').textContent = kind + ' · ' + bid + ' · ' + acc; paint(cell);
        let lx = ev.clientX, ly = ev.clientY;
        const mv = e => { const k = kind + ':' + bid, t = (tune[k] = tune[k] || {}), o = t[acc] = Object.assign({dx: 0, dy: 0, s: 1}, rigOf(kind, bid).acc[acc] || {});
          o.dx = Math.round((o.dx + (e.clientX - lx) * 100 / S) * 10) / 10; o.dy = Math.round((o.dy + (e.clientY - ly) * 100 / S) * 10) / 10; lx = e.clientX; ly = e.clientY; paint(cell); show(); };
        const up = () => { removeEventListener('mousemove', mv); removeEventListener('mouseup', up); };
        addEventListener('mousemove', mv); addEventListener('mouseup', up);
        ev.preventDefault();
      };
      box.onwheel = ev => {
        if (sel !== cell) return;
        ev.preventDefault();
        const k = kind + ':' + bid, t = (tune[k] = tune[k] || {}), o = t[acc] = Object.assign({dx: 0, dy: 0, s: 1}, rigOf(kind, bid).acc[acc] || {});
        o.s = Math.round(o.s * (ev.deltaY < 0 ? 1.04 : 1 / 1.04) * 1000) / 1000; paint(cell); show();
      };
    }
  }
  panel.querySelector('#copy').onclick = () => { out.select(); try { navigator.clipboard.writeText(out.value); } catch (e) { document.execCommand('copy'); } };
  panel.querySelector('#reset').onclick = () => { if (!sel) return; const k = sel.kind + ':' + sel.bid; if (tune[k]) delete tune[k][sel.acc]; if (m.breeds[sel.kind][sel.bid].rig && m.breeds[sel.kind][sel.bid].rig.acc) delete m.breeds[sel.kind][sel.bid].rig.acc[sel.acc]; paint(sel); show(); };
  panel.querySelector('#meas').onclick = async () => {
    for (const kind of kinds) for (const [bid, b] of Object.entries(m.breeds[kind] || {})) {
      const file = b.alert || b.idle, img = await load('/skin/' + skinId + '/' + file), r = img && PetLab.measure(img, file);
      if (r) measured[kind + ':' + bid] = r;
    }
    cells.forEach(paint); show();
  };
  window.PetLab.cells = cells; window.PetLab.measured = measured; window.PetLab.tune = tune; window.PetLab.manifest = m;
  await Promise.all(cells.map(paint));
  document.body.dataset.ready = '1';
});
