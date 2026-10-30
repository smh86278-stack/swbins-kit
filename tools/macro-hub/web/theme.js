/* 화면 모드(자동 · 라이트 · 다크) · 화면 꾸미기 · 왼쪽 사이드바 — 허브 첫 화면과 운영 화면이 함께 쓴다.
   모드는 허브가 기억하고(state['theme']) 페이지를 줄 때 <html data-mode> 에 심는다. 색은 theme.css 의 light-dark().
   바꾸면 허브가 /events 로 알려 열린 화면·전용 창이 같이 바뀐다(페이지는 HubMode.apply 를 부른다). */
// 허브 창(Electron) 안이면 왼쪽 아이콘 줄이 있으니 겹치는 메뉴(data-app-hide)를 숨긴다 — theme.css .in-app
if (/\bElectron\//.test(navigator.userAgent)) document.documentElement.classList.add('in-app');

const HubIcons = {   // 선(stroke) 아이콘 — 24×24, theme.css svg.i
  list: 'M4 6h16M4 12h16M4 18h10', plus: 'M12 5v14M5 12h14', apps: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  clock: 'M12 3.5a8.5 8.5 0 1 0 0 17a8.5 8.5 0 1 0 0-17M12 7.5V12l3 2', history: 'M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4M12 8v4l3 2',
  mail: 'M3.5 6.5h17v11h-17zM3.5 7l8.5 6 8.5-6', gear: 'M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1',
  book: 'M5 4.5h10a3 3 0 0 1 3 3v12H8a3 3 0 0 1-3-3zM5 16.5a3 3 0 0 1 3-3h10', brush: 'M14 4l6 6-8.5 8.5a3 3 0 0 1-4.2 0l-1.8-1.8a3 3 0 0 1 0-4.2zM4 20l3-3',
  search: 'M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14M20 20l-3.5-3.5', alert: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 7.5v5M12 16h.01',
  more: 'M5 12h.01M12 12h.01M19 12h.01', chev: 'M9 6l6 6-6 6', x: 'M6 6l12 12M18 6 6 18', play: 'M7 5l12 7-12 7z',
  record: 'M12 7a5 5 0 1 0 0 10a5 5 0 1 0 0-10M12 2.5a9.5 9.5 0 1 0 0 19a9.5 9.5 0 1 0 0-19', chat: 'M4 5h16v11H9l-5 4z',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  tool: 'M14.7 6.3a4 4 0 0 0-5.2 5.2L4 17v3h3l5.5-5.5a4 4 0 0 0 5.2-5.2l-2.6 2.6-2.4-.6-.6-2.4z', box: 'M4 7.5 12 3.5l8 4v9l-8 4-8-4zM4 7.5l8 4 8-4M12 11.5v9',
  user: 'M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4.5 20.5a7.5 7.5 0 0 1 15 0',
  test: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3', external: 'M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5',
};
function hubIcon(name, size) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('class', 'i');
  if (size) { s.style.width = s.style.height = size + 'px'; }
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', HubIcons[name] || ''); s.append(p);
  if (name === 'more') s.style.strokeWidth = '3';
  return s;
}

const HubMode = (() => {
  const MODES = [['light', '라이트'], ['dark', '다크'], ['auto', '자동']];
  let token = '';
  function apply(mode) {
    if (!MODES.some(x => x[0] === mode)) mode = 'auto';
    const root = document.documentElement;
    if (root.dataset.mode !== mode) {
      root.classList.add('mode-anim'); clearTimeout(apply.t);
      apply.t = setTimeout(() => root.classList.remove('mode-anim'), 400);
      root.dataset.mode = mode;
    }
    HubNav.refresh(); HubLook.redraw();
  }
  async function set(m) {
    const prev = document.documentElement.dataset.mode;
    apply(m);
    try {
      const r = await fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hub-Token': token }, body: JSON.stringify({ mode: m }) });
      if (!r.ok) throw new Error(r.status);
    } catch (e) { apply(prev); }
  }
  // mount(sel, token) — 예전 화면 모드 단추 자리. 이제 단추는 「화면 꾸미기」 창 안에 있고, 여기서는 토큰만 받는다
  function mount(sel, tok) { token = tok; const box = sel && document.querySelector(sel); if (box) box.hidden = true; }
  const isDark = () => { const m = document.documentElement.dataset.mode; return m === 'dark' || (m !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches); };
  return { apply, mount, set, isDark, MODES };
})();

/* 화면 꾸미기 — 화면 모드 · 내 강조색 · 촘촘하게 · 화면 펫. 색 테마는 「종이 노트」(paper) 하나뿐이다(2026-10-26). 허브가 state['look'] 에 기억하고 페이지를 줄 때 <html> 에 심는다(macrohub.look_attrs).
   바꾸면 허브가 /events 로 {t:'look'} 을 보내 열린 화면이 같이 바뀐다(페이지가 HubLook.apply 를 부른다). */
const HubLook = (() => {
  // [id, 이름, 바탕색, 강조색] — 예전 basic·navy·pastel 은 허브가 paper 로 읽는다(macrohub.look)
  const THEMES = [['paper', '종이 노트', '#f4efe6', '#9a3f1d']];
  let cur = null, token = '', opts = {}, panel = null, anchor = null;
  const pair = c => 'light-dark(' + c + ',color-mix(in srgb,' + c + ' 72%,white))';
  function apply(lk) {
    if (!lk) return;
    cur = lk;
    const r = document.documentElement, d = r.dataset;
    d.theme = 'paper'; d.hero = lk.hero; d.cols = lk.cols; d.swap = lk.swap ? '1' : '0'; d.dense = lk.dense ? '1' : '0';
    for (const [v, c] of [['--accent', lk.accent], ['--accent2', lk.accent2]]) c ? r.style.setProperty(v, pair(c)) : r.style.removeProperty(v);
    if (lk.accent) r.style.setProperty('--accentsoft', 'light-dark(color-mix(in srgb,' + lk.accent + ' 12%,#fffaf2),color-mix(in srgb,' + lk.accent + ' 22%,#27231f))');
    else r.style.removeProperty('--accentsoft');
    HubNav.refresh(); redraw();
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
  function seg(label, items, on, pick) {   // 여럿 중 하나 — aria-pressed 단추 묶음
    const box = el('div', 'seg'); box.setAttribute('role', 'group'); box.setAttribute('aria-label', label);
    for (const [v, text, dot] of items) {
      const b = el('button'); b.type = 'button'; b.setAttribute('aria-pressed', String(on === v));
      if (dot) { const s = el('span', 'swd'); s.style.background = dot; b.append(s); }
      b.append(text); b.onclick = () => pick(v); box.append(b);
    }
    return box;
  }
  let petNode = null;                                // 페이지의 펫 칸 — 다시 그릴 때 창에서 떼어져도 잃지 않게 붙잡아 둔다
  function draw() {
    petNode = (opts.pets && document.getElementById(opts.pets)) || petNode;
    panel.replaceChildren();
    panel.append(el('h3', '', '화면 모드'), seg('화면 모드', HubMode.MODES, document.documentElement.dataset.mode, m => HubMode.set(m)));
    panel.append(el('h3', '', '강조색'));
    const cr = el('div', 'lrow'), base = THEMES[0];
    const l = el('label', '', '내 색'), i = el('input'); i.type = 'color'; i.value = cur.accent || base[3]; i.setAttribute('aria-label', '내 강조색');
    i.onchange = () => save({ accent: i.value }); l.append(i); cr.append(l);
    const rs = el('button', '', '기본 색으로'); rs.type = 'button'; rs.onclick = () => save({ accent: '', accent2: '' }); cr.append(rs);
    panel.append(cr);
    if (opts.layout) {
      const l2 = el('label'), c = el('input'); c.type = 'checkbox'; c.checked = !!cur.dense;
      c.onchange = () => save({ dense: c.checked }); l2.append(c, '촘촘하게');
      panel.append(el('h3', '', '목록'), l2);
    }
    if (opts.pets) {
      panel.append(el('h3', '', '화면 펫 · 인형'), seg('펫 무대', [['show', '보통'], ['small', '작게'], ['hide', '숨김']], cur.hero, v => save({ hero: v })));
      if (petNode) { petNode.hidden = false; panel.append(petNode); }
    }
    if (opts.more) opts.more(panel, el);             // 페이지가 덧붙이는 칸(허브 첫 화면: 펫 소품)
  }
  function close() {
    if (!panel) return;
    const node = opts.pets && (document.getElementById(opts.pets) || petNode);
    if (node) { node.hidden = true; document.body.append(node); }   // 펫 칸은 페이지 것 — 창을 닫아도 남겨 둔다(id 로 찾는 코드가 있다)
    panel.remove(); panel = null;
    if (anchor) anchor.setAttribute('aria-expanded', 'false');
  }
  function place() {
    const r = anchor.getBoundingClientRect(), w = panel.offsetWidth, h = panel.offsetHeight;
    if (r.right < 300 && innerWidth > 860) {   // 사이드바 아래쪽 단추 — 오른쪽으로 펼친다
      panel.style.left = Math.round(r.right + 8) + 'px';
      panel.style.top = Math.max(12, Math.min(innerHeight - h - 12, r.bottom - h)) + 'px';
    } else {
      panel.style.top = Math.round(r.bottom + 6) + 'px';
      panel.style.left = Math.max(12, Math.min(innerWidth - w - 12, r.right - w)) + 'px';
    }
  }
  function open(btn) {
    if (panel) { close(); return; }
    if (!cur) return;
    anchor = btn; btn.setAttribute('aria-expanded', 'true');
    panel = el('div', 'lookpanel'); panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', '화면 꾸미기');
    panel.onclick = ev => ev.stopPropagation();
    document.body.append(panel); draw(); place();
  }
  function redraw() { if (panel) { draw(); place(); } }
  // mount(sel, token, {layout, pets, more}) — sel 은 예전 단추 자리(없어도 된다). 꾸미기 단추는 사이드바(HubNav)에 있다
  function mount(sel, tok, o) {
    token = tok; opts = o || {};
    const d = document.documentElement.dataset;
    cur = { theme: 'paper', hero: d.hero || 'hide', cols: d.cols || '2', swap: d.swap === '1', dense: d.dense === '1', accent: '', accent2: '' };
    fetch('/api/look', { headers: { 'X-Hub-Token': tok } }).then(r => r.json()).then(j => { cur = j.look; redraw(); }).catch(() => {});
    const old = sel && document.querySelector(sel); if (old) old.hidden = true;
    document.addEventListener('click', close);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && panel) { const a = anchor; close(); a && a.focus(); } });
    addEventListener('resize', () => { if (panel) place(); });
  }
  return { apply, mount, open, close, redraw, save, THEMES, get cur() { return cur; } };
})();

/* 왼쪽 목차 — 이름 · 메뉴 · 화면 모드(라이트·다크·자동) · 화면 꾸미기 · 연결 상태. HubNav.mount('#side', {active, dot}) */
const HubNav = (() => {
  const ITEMS = [   // [key, 이름, 주소, 아이콘, 허브 창 안에서 숨김(왼쪽 아이콘 줄에 있음), 새 탭]
    ['hub', '자동화', '/', 'list', true], ['make', '만들기', '/?view=make', 'plus', true], ['apps', '내 앱', '/?view=make#appsBox', 'apps'],
    ['sched', '예약', '/ops#sched', 'clock'], ['log', '기록', '/ops#audit', 'history'],
    ['chat', '메일로 맡기기', 'http://127.0.0.1:8620/', 'mail', true, true], ['set', '설정', '/ops#set', 'gear'],
    null, ['wiki', 'AI 작업 회고', '/retro', 'book', true, true],   // 허브가 회고 화면으로 넘긴다(꺼져 있으면 켜는 법). 허브 창에선 아이콘 줄 「회고」
  ];
  const TIPS = { chat: '디스패치 대화 — 메일로 맡긴 일을 메신저처럼', wiki: 'AI 작업 회고 · 주간 보고 초안 (ai_share.enabled 를 켜야 뜹니다)',
    sched: '예약 작업 · 상시 서비스 · 기능 상태', log: '변경 이력 · 지시 실행 기록', set: '메일 계정 · 설정' };
  let nav = null, mbs = [];
  function setActive(key) {
    if (!nav) return;
    for (const a of nav.querySelectorAll('a.nav-i')) a.dataset.k === key ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current');
  }
  function refresh() {
    if (!nav) return;
    const m = document.documentElement.dataset.mode || 'auto';
    for (const b of mbs) b.setAttribute('aria-pressed', String(b.dataset.k === m));
  }
  function mount(sel, o) {
    nav = document.querySelector(sel);
    if (!nav) return;
    o = o || {};
    nav.classList.add('side'); nav.setAttribute('aria-label', '메뉴');
    const brand = document.createElement('a'); brand.className = 'brand'; brand.href = '/'; brand.setAttribute('aria-label', 'Taskhand 첫 화면');
    brand.innerHTML = '<span class="logo" aria-hidden="true">T</span><b>Taskhand</b>';   // 이름 — 명조, 아래 굵은 줄
    nav.append(brand);
    for (const it of ITEMS) {
      if (!it) { const d = document.createElement('div'); d.className = 'divider'; d.setAttribute('aria-hidden', 'true'); nav.append(d); continue; }
      const [k, label, href, ic, appHide, blank] = it;
      const a = document.createElement('a'); a.className = 'nav-i'; a.href = href; a.dataset.k = k;
      if (appHide) a.setAttribute('data-app-hide', '');
      if (blank) { a.target = '_blank'; a.rel = 'noopener'; }
      if (TIPS[k]) a.title = TIPS[k];
      a.append(hubIcon(ic), label); nav.append(a);
    }
    const sp = document.createElement('div'); sp.className = 'spacer'; nav.append(sp);
    const tb = document.createElement('div'); tb.className = 'themebox';
    const lbl = document.createElement('div'); lbl.className = 'lbl'; lbl.textContent = '화면'; lbl.id = 'modeLbl';
    const row = document.createElement('div'); row.className = 'modes'; row.setAttribute('role', 'group'); row.setAttribute('aria-labelledby', 'modeLbl');
    mbs = HubMode.MODES.map(([k, name]) => {
      const b = document.createElement('button'); b.type = 'button'; b.dataset.k = k; b.textContent = name;
      b.onclick = () => HubMode.set(k); row.append(b); return b;
    });
    const lb = document.createElement('button'); lb.type = 'button'; lb.className = 'lookbtn'; lb.id = 'lookBtn';
    lb.setAttribute('aria-haspopup', 'dialog'); lb.setAttribute('aria-expanded', 'false'); lb.title = '화면 꾸미기 — 모드 · 강조색' + (o.pets ? ' · 화면 펫' : '');
    lb.textContent = '화면 꾸미기';
    lb.onclick = e => { e.stopPropagation(); HubLook.open(lb); };
    tb.append(lbl, row, lb); nav.append(tb);
    if (o.dot) {
      const c = document.createElement('div'); c.className = 'conn';
      c.innerHTML = '<span id="dot" role="status"></span><span class="ct"></span>'; nav.append(c);
    }
    setActive(o.active); refresh();
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', refresh);
  }
  return { mount, setActive, refresh };
})();

/* 펼침 메뉴 — 「더 보기」 단추. HubMenu.open(btn, [[이름, fn, 'bad'?], …]) */
const HubMenu = (() => {
  let box = null, from = null;
  function close() { if (!box) return; box.remove(); box = null; if (from) from.setAttribute('aria-expanded', 'false'); }
  function open(btn, items) {
    const again = box && from === btn; close(); if (again) return;
    from = btn; btn.setAttribute('aria-expanded', 'true');
    box = document.createElement('div'); box.className = 'menu'; box.setAttribute('role', 'menu');
    for (const [label, fn, cls] of items) {
      const b = document.createElement('button'); b.type = 'button'; b.setAttribute('role', 'menuitem'); b.textContent = label; if (cls) b.className = cls;
      b.onclick = e => { e.stopPropagation(); close(); fn(); }; box.append(b);
    }
    box.onclick = e => e.stopPropagation();
    box.onkeydown = e => {
      const bs = [...box.querySelectorAll('button')], i = bs.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); bs[(i + 1) % bs.length].focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); bs[(i - 1 + bs.length) % bs.length].focus(); }
    };
    document.body.append(box);
    const r = btn.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + 'px';
    box.style.top = (r.bottom + h + 8 > innerHeight ? Math.max(8, r.top - h - 4) : r.bottom + 4) + 'px';
    box.querySelector('button')?.focus();
  }
  document.addEventListener('click', close);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && box) { const f = from; close(); f && f.focus(); } });
  addEventListener('scroll', close, true);
  return { open, close };
})();
