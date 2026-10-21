/* 화면 모드(자동 · 라이트 · 다크) 단추 — 허브 첫 화면과 운영 화면이 함께 쓴다.
   모드는 허브가 기억하고(state['theme']) 페이지를 줄 때 <html data-mode> 에 심는다. 색은 theme.css 의 light-dark().
   바꾸면 허브가 /events 로 알려 열린 화면·전용 창이 같이 바뀐다(페이지는 HubMode.apply 를 부른다). */
// 허브 창(Electron) 안이면 왼쪽 아이콘 줄이 있으니 겹치는 맨 위 메뉴 링크(data-app-hide)를 숨긴다 — theme.css .in-app
if (/\bElectron\//.test(navigator.userAgent)) document.documentElement.classList.add('in-app');

const HubMode = (() => {
  const MODES = [['light', '☀️', '라이트'], ['dark', '🌙', '다크'], ['auto', '자동', '자동 — Windows 설정을 따름']];
  let box = null;
  function apply(mode) {
    if (!MODES.some(x => x[0] === mode)) mode = 'auto';
    const root = document.documentElement;
    if (root.dataset.mode !== mode) {
      root.classList.add('mode-anim'); clearTimeout(apply.t);
      apply.t = setTimeout(() => root.classList.remove('mode-anim'), 400);
      root.dataset.mode = mode;
    }
    if (box) for (const b of box.children) b.classList.toggle('on', b.dataset.m === mode);
  }
  function mount(sel, token) {
    box = document.querySelector(sel);
    if (!box) return;
    box.classList.add('modesw'); box.setAttribute('role', 'group'); box.title = '화면 모드';
    for (const [m, label, tip] of MODES) {
      const b = document.createElement('button');
      b.type = 'button'; b.dataset.m = m; b.textContent = label; b.title = tip;
      b.onclick = async () => {
        const prev = document.documentElement.dataset.mode;
        apply(m);
        try {
          const r = await fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hub-Token': token }, body: JSON.stringify({ mode: m }) });
          if (!r.ok) throw new Error(r.status);
        } catch (e) { apply(prev); }
      };
      box.append(b);
    }
    apply(document.documentElement.dataset.mode);
  }
  return { apply, mount };
})();

/* 🎨 꾸미기 — 색 테마 · 내 강조색 · 첫 화면 배치. 허브가 state['look'] 에 기억하고 페이지를 줄 때 <html> 에 심는다(macrohub.look_attrs).
   바꾸면 허브가 /events 로 {t:'look'} 을 보내 열린 화면이 같이 바뀐다(페이지가 HubLook.apply 를 부른다). */
const HubLook = (() => {
  const THEMES = [['pastel', '파스텔', '#8a72ee', '#ef8fbf'], ['navy', '네이비', '#2f5bd3', '#1f9fd0'], ['mint', '민트', '#139a72', '#2ea9bd'],
                  ['mono', '모노', '#3b3b46', '#6b6b7a'], ['sunset', '선셋', '#df5f34', '#e99a1f']];
  let cur = null, token = '', layout = false, panel = null;
  const pair = c => 'light-dark(' + c + ',color-mix(in srgb,' + c + ' 72%,white))';
  function apply(lk) {
    if (!lk) return;
    cur = lk;
    const r = document.documentElement, d = r.dataset;
    d.theme = lk.theme; d.hero = lk.hero; d.cols = lk.cols; d.swap = lk.swap ? '1' : '0'; d.dense = lk.dense ? '1' : '0';
    for (const [v, c] of [['--accent', lk.accent], ['--accent2', lk.accent2]]) c ? r.style.setProperty(v, pair(c)) : r.style.removeProperty(v);
    if (lk.accent) r.style.setProperty('--accentsoft', 'light-dark(color-mix(in srgb,' + lk.accent + ' 13%,white),color-mix(in srgb,' + lk.accent + ' 24%,#1a1826))');
    else r.style.removeProperty('--accentsoft');
    if (panel) draw();
  }
  async function save(change) {
    const prev = cur;
    apply(Object.assign({}, cur, change));
    try {
      const res = await fetch('/api/look', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hub-Token': token }, body: JSON.stringify(change) });
      if (!res.ok) throw new Error(res.status);
    } catch (e) { apply(prev); }
  }
  const el = (t, cls, txt) => { const e = document.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  function seg(key, opts) {
    const box = el('div', 'lrow seg');
    for (const [v, label] of opts) { const b = el('button', cur[key] === v ? 'on' : '', label); b.type = 'button'; b.onclick = () => save({ [key]: v }); box.append(b); }
    return box;
  }
  function draw() {
    panel.replaceChildren();
    panel.append(el('h3', '', '색 테마'));
    const th = el('div', 'lrow');
    for (const [id, name, a, b] of THEMES) {
      const s = el('button', 'sw' + (cur.theme === id ? ' on' : '')); s.type = 'button'; s.title = name;
      s.style.background = 'linear-gradient(135deg,' + a + ',' + b + ')'; s.onclick = () => save({ theme: id }); th.append(s);
    }
    panel.append(th);
    panel.append(el('h3', '', '내 강조색 (비우면 테마 색)'));
    const cr = el('div', 'lrow'), base = THEMES.find(t => t[0] === cur.theme) || THEMES[0];
    for (const [key, label, def] of [['accent', '강조색', base[2]], ['accent2', '둘째 색', base[3]]]) {
      const l = el('label', '', label), i = el('input'); i.type = 'color'; i.value = cur[key] || def;
      i.onchange = () => save({ [key]: i.value }); l.append(i); cr.append(l);
    }
    const rs = el('button', '', '테마 색으로'); rs.type = 'button'; rs.onclick = () => save({ accent: '', accent2: '' }); cr.append(rs);
    panel.append(cr);
    if (layout) {
      panel.append(el('h3', '', '펫 무대'), seg('hero', [['show', '보통'], ['small', '작게'], ['hide', '숨김']]));
      panel.append(el('h3', '', '목록 배치'), seg('cols', [['2', '두 칸'], ['1', '한 칸']]));
      const opt = el('div', 'lrow');
      for (const [key, label] of [['swap', '목록·만들기 좌우 바꾸기'], ['dense', '촘촘하게']]) {
        const l = el('label', '', ''), c = el('input'); c.type = 'checkbox'; c.checked = !!cur[key];
        c.onchange = () => save({ [key]: c.checked }); l.append(c, label); opt.append(l);
      }
      panel.append(el('h3', '', '그 밖에'), opt);
    }
  }
  function mount(sel, tok, opts) {
    const btn = document.querySelector(sel);
    if (!btn) return;
    token = tok; layout = !!(opts && opts.layout);
    fetch('/api/look', { headers: { 'X-Hub-Token': tok } }).then(r => r.json()).then(j => { cur = j.look; }).catch(() => {});
    btn.onclick = e => {
      e.stopPropagation();
      if (panel) { panel.remove(); panel = null; return; }
      if (!cur) return;
      panel = el('div', 'lookpanel'); panel.onclick = ev => ev.stopPropagation();
      document.body.append(panel); draw();
    };
    document.addEventListener('click', () => { if (panel) { panel.remove(); panel = null; } });
  }
  return { apply, mount };
})();
