'use strict';
/* 자동화 허브 창 — 허브(http://127.0.0.1:8630/)와 디스패치 대화(8620)를 브라우저 탭이 아니라 창 하나에 연다. 카카오톡 PC 처럼
 * 왼쪽 아이콘 줄(rail.html)로 🏠 허브 · 💬 대화 · ⏰ 운영 을 오가고, 화면마다 따로 살려 두어 돌아와도 그대로다.
 * 💬 대화 아이콘은 디스패치 대화가 떠 있을 때만 보인다(dispatch.enabled 를 켜야 뜬다 — 기본 꺼짐).
 *
 *   electron.exe shell [--page=/ops]     (보통은 WorkKit.exe · 트레이 '자동화 허브 열기' 가 띄운다)
 *
 * 화면 펫(pet\)과 같은 Electron 을 쓴다. 창은 한 번에 하나 — 다시 열면 떠 있는 창이 앞으로 나오고 그 화면으로 간다.
 * 창을 닫으면 숨기기만 한다(프로세스는 남아 다시 열 때 바로 뜬다). 허브·트레이·서비스는 이 프로세스와 상관없이 돈다. 허브·대화 밖 주소는 기본 브라우저로 연다.
 * 대화 화면 코드(tools\dispatch-chat)는 손대지 않는다 — 배지는 대화 /api/state 를 읽어 여기서 센다. */
const { app, BaseWindow, BrowserWindow, WebContentsView, ipcMain, shell, Menu, nativeTheme, screen } = require('electron');
const fs = require('fs');
const path = require('path');

const HUB = 'http://127.0.0.1:8630';
const CHAT = 'http://127.0.0.1:' + (parseInt(process.env.DISPATCH_CHAT_PORT, 10) || 8620);   // svc_dispatch_chat.py 와 같은 규칙
const STATE = path.join(__dirname, 'window.local.json');
const ICON = path.join(__dirname, '..', 'web', 'app.ico');
const TITLE = '자동화 허브';
const RAIL = 64;                                                          // 왼쪽 아이콘 줄 너비 — rail.html 의 --rail 과 같게
const TABS = { hub: HUB + '/', make: HUB + '/?view=make', chat: CHAT + '/', ops: HUB + '/ops' };
const pageArg = argv => { const a = argv.find(x => x.startsWith('--page=')); const p = a ? a.slice(7) : '/'; return p.startsWith('/') ? p : '/'; };

app.setAppUserModelId('WorkKit');
app.setName(TITLE);
app.setPath('userData', path.join(__dirname, '..', 'data.local', 'shell-profile'));   // 펫과 프로필을 나눈다
if (!app.requestSingleInstanceLock()) { app.quit(); return; }

let win = null;
let quitting = false;                                                     // true 일 때만 창 닫기가 진짜로 닫힌다(아니면 숨김)
const views = {};                                                         // 탭 → WebContentsView (처음 열 때 만든다)
let active = null;
const popped = {};                                                        // 떼어 낸 탭 → 그 창(BaseWindow). 닫으면 다시 붙는다
let dropTab = null;                                                       // 떼어 낸 창을 끌어 아이콘 줄 위에 올려 둔 탭 — 놓으면 다시 붙는다
const NAMES = { hub: TITLE, make: '자동화 만들기', chat: '디스패치 대화', ops: '운영' };

// 화면 모드(자동·라이트·다크) — 허브가 기억한다(/api/theme). 창 테두리(nativeTheme)와 배경색(web/theme.css 의 --bg)을 맞추고,
// 허브 /events 를 들어 화면에서 바꾸면 바로 따라간다. 허브가 꺼져 있으면 5초마다 다시 붙는다. 아이콘 줄은 prefers-color-scheme 로 따라온다.
const BG = { light: '#f7f4fc', dark: '#1a1826' };
const bg = () => (nativeTheme.shouldUseDarkColors ? BG.dark : BG.light);
function paint() {
  if (!win) return;
  win.setBackgroundColor(bg());
  for (const v of Object.values(views)) v.setBackgroundColor(bg());
  for (const w of Object.values(popped)) w.setBackgroundColor(bg());
}
function applyMode(mode) {
  nativeTheme.themeSource = mode === 'light' || mode === 'dark' ? mode : 'system';
  paint();
}
nativeTheme.on('updated', paint);
async function fetchMode() {
  try { applyMode((await (await fetch(HUB + '/api/theme', { signal: AbortSignal.timeout(1500) })).json()).mode); } catch (_) {}
}
async function watchMode() {
  for (;;) {
    try {
      await fetchMode();
      const res = await fetch(HUB + '/events');
      const dec = new TextDecoder();
      let buf = '';
      for await (const chunk of res.body) {
        buf += dec.decode(chunk, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const ev = buf.slice(0, i); buf = buf.slice(i + 2);
          if (!ev.startsWith('data: ')) continue;
          try { const m = JSON.parse(ev.slice(6)); if (m.t === 'theme') applyMode(m.mode); } catch (_) {}
        }
      }
    } catch (_) {}
    await new Promise(r => setTimeout(r, 5000));
  }
}

// 💬 배지 — 대화의 '답할 것'(질문·확인 기다림) 수. 대화가 안 떠 있으면 배지를 지우고 아이콘도 숨긴다(없는 화면을 가리키지 않게)
let badge = 0;
let chatUp = false;
async function watchChat() {
  for (;;) {
    let n = 0, up = false;
    try {
      const st = await (await fetch(CHAT + '/api/state', { signal: AbortSignal.timeout(3000) })).json();
      up = true;
      n = (st.threads || []).filter(t => t.status === 'ask' || t.status === 'confirm').length;
    } catch (_) {}
    if (n !== badge || up !== chatUp) { badge = n; chatUp = up; sendRail(); }
    await new Promise(r => setTimeout(r, 15000));
  }
}

function readState() { try { return JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch (_) { return {}; } }
function saveState() {
  if (!win) return;
  try { fs.writeFileSync(STATE, JSON.stringify({ bounds: win.getNormalBounds(), max: win.isMaximized(), order })); } catch (_) {}
}
// 아이콘 줄의 순서 — 끌어서 바꾸면 기억한다. Ctrl+1~4 도 이 순서(안 보이는 💬 는 건너뛴다)
const MOVABLE = ['hub', 'make', 'chat', 'ops'];
const sameSet = l => Array.isArray(l) && l.length === MOVABLE.length && MOVABLE.every(t => l.includes(t));
// 저장된 순서를 살린다 — 나중에 생긴 탭(0.2.4 의 🛠 만들기)은 기본 자리에 끼우고, 없어진 탭·겹친 것은 뺀다
function fixOrder(l) {
  if (!Array.isArray(l)) return MOVABLE.slice();
  const out = l.filter((t, i) => MOVABLE.includes(t) && l.indexOf(t) === i);
  MOVABLE.forEach((t, i) => { if (!out.includes(t)) out.splice(Math.min(i, out.length), 0, t); });
  return out;
}
let order = fixOrder(readState().order);
const ORDER = () => order.filter(t => t !== 'chat' || chatUp || views.chat);
const under = (url, base) => url === base || url.startsWith(base + '/');
const internal = url => under(url, HUB) || under(url, CHAT);
// 허브·메신저 밖 주소는 기본 브라우저로 — 단 http·https·mailto 만(search-ms:·file://\공유폴더 같은 것이 열리지 않게. 2026-10-19 보안 점검)
const openOut = url => { if (/^(https?:|mailto:)/i.test(url)) shell.openExternal(url); };
function tabFor(url) {                                                    // 주소 → 그 화면을 맡는 탭
  if (under(url, CHAT)) return 'chat';
  const p = url.slice(HUB.length).split(/[?#]/)[0];
  if (p === '/ops' || p.startsWith('/ops/')) return 'ops';
  if (p === '/' && /[?&]view=make(&|#|$)/.test(url)) return 'make';
  return 'hub';
}
const toUrl = page => (/^https?:/.test(page) ? page : HUB + page);

function sendRail() { if (win) win.webContents.send('rail', { active, badge, order: ORDER(), popped: Object.keys(popped), drop: !!dropTab }); }
function layout() {
  if (!win) return;
  const [w, h] = win.getContentSize();
  for (const [t, v] of Object.entries(views)) if (!popped[t]) v.setBounds({ x: RAIL, y: 0, width: Math.max(0, w - RAIL), height: h });
}

function keys(wc) {                                                       // F5 · Ctrl+R 새로고침, Ctrl+Shift+I 개발자 도구,
  wc.on('before-input-event', (e, input) => {                             // Alt+←/→ 뒤로·앞으로, Ctrl+1~4 탭
    if (input.type !== 'keyDown') return;
    const k = input.key.toLowerCase();
    const cur = win && wc === win.webContents ? views[active] && views[active].webContents : wc;   // 아이콘 줄이면 앞에 보이는 탭, 아니면 그 화면(떼어 낸 창 포함)
    if (input.control && !input.shift && !input.alt && /^[1-9]$/.test(k)) { const t = ORDER()[+k - 1]; if (t) show(t); e.preventDefault(); return; }
    if (!cur) return;
    if (input.key === 'F5' || (input.control && k === 'r')) { cur.reload(); e.preventDefault(); }
    if (input.control && input.shift && k === 'i') { cur.toggleDevTools(); e.preventDefault(); }
    const nav = cur.navigationHistory;
    if (input.alt && input.key === 'ArrowLeft' && nav.canGoBack()) { nav.goBack(); e.preventDefault(); }
    if (input.alt && input.key === 'ArrowRight' && nav.canGoForward()) { nav.goForward(); e.preventDefault(); }
  });
}

function makeView(tab) {
  const v = new WebContentsView({ webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
  v.setBackgroundColor(bg());
  const wc = v.webContents;
  wc.on('will-navigate', (e, url) => {                                    // 다른 탭 화면으로 가는 링크는 그 탭에서 연다
    if (!internal(url)) { e.preventDefault(); openOut(url); return; }
    if (tabFor(url) !== tab) { e.preventDefault(); show(tabFor(url), url); }
  });
  wc.setWindowOpenHandler(({ url }) => {
    if (internal(url)) show(tabFor(url), url); else openOut(url);
    return { action: 'deny' };
  });
  wc.on('did-fail-load', (_e, code, _desc, url, main) => {               // 허브·대화가 막 뜨는 중 — 실패한 그 주소를 다시
    if (code !== -3 && main) setTimeout(() => { if (!wc.isDestroyed()) wc.loadURL(internal(url) ? url : TABS[tab]).catch(() => {}); }, 1500);
  });
  keys(wc);
  win.contentView.addChildView(v);
  views[tab] = v;
  layout();
  return v;
}

function show(tab, url) {                                                 // 탭을 앞으로 — url 이 오면 그 주소로, 처음이면 탭 첫 화면으로
  if (!win || !TABS[tab]) return;
  const fresh = !views[tab];
  const v = views[tab] || makeView(tab);
  if (url && url !== v.webContents.getURL()) v.webContents.loadURL(url).catch(() => {});
  else if (fresh) v.webContents.loadURL(TABS[tab]).catch(() => {});
  if (popped[tab]) {                                                      // 떼어 낸 탭이면 그 창을 앞으로
    const pw = popped[tab];
    if (pw.isMinimized()) pw.restore();
    pw.show(); pw.focus(); v.webContents.focus();
    return;
  }
  for (const [t, o] of Object.entries(views)) if (!popped[t]) o.setVisible(t === tab);
  active = tab;
  v.webContents.focus();
  sendRail();
}

// 탭 떼어 내기 — 카톡 대화방처럼 따로 창으로. 화면(WebContentsView)을 통째로 옮겨 보던 상태 그대로, 그 창을 닫으면 다시 붙는다
const clamp = (n, lo, hi) => Math.max(lo, Math.min(n, hi));
function detach(tab, x, y) {
  if (!win || !TABS[tab]) return;
  if (popped[tab]) return show(tab);
  if (!views[tab]) { makeView(tab); views[tab].webContents.loadURL(TABS[tab]).catch(() => {}); }
  const v = views[tab];
  win.contentView.removeChildView(v);
  const wa = screen.getDisplayNearestPoint({ x: Math.round(x), y: Math.round(y) }).workArea;
  const W = 571, H = Math.min(860, wa.height);
  const pw = new BaseWindow({
    x: clamp(Math.round(x) - 60, wa.x, wa.x + wa.width - W), y: clamp(Math.round(y) - 20, wa.y, wa.y + wa.height - H),
    width: W, height: H, minWidth: 380, minHeight: 400, title: NAMES[tab], icon: ICON, backgroundColor: bg(),
  });
  pw.contentView.addChildView(v);
  v.setVisible(true);
  const fit = () => { const [w, h] = pw.getContentSize(); v.setBounds({ x: 0, y: 0, width: w, height: h }); };
  fit(); pw.on('resize', fit);
  pw.on('close', () => { pw.contentView.removeChildView(v); delete popped[tab]; dock(tab, v); });
  // 끌어다 다시 합치기 — 탐색기 탭처럼 제목 표시줄을 잡고 원래 창의 아이콘 줄 위에 놓으면 붙는다.
  // 끄는 동안 아이콘 줄이 밝아지고 이 창이 반투명해져 '놓으면 붙는다'를 알린다. will-move 는 끄는 내내, moved 는 놓을 때 온다(윈도우)
  pw.on('will-move', () => {
    const t = overRail() ? tab : null;
    if (t === dropTab) return;
    dropTab = t; pw.setOpacity(t ? 0.55 : 1); sendRail();
  });
  pw.on('moved', () => {
    const back = overRail();
    if (dropTab) { dropTab = null; pw.setOpacity(1); sendRail(); }
    if (back) { pw.close(); win.show(); win.focus(); }
  });
  popped[tab] = pw;
  if (active === tab) { active = null; const next = ORDER().find(t => !popped[t]); if (next) show(next); }
  v.webContents.focus();
  sendRail();
}
function overRail() {                                                     // 마우스가 원래 창의 아이콘 줄 위에 있나
  if (!win || !win.isVisible() || win.isMinimized()) return false;
  const p = screen.getCursorScreenPoint(), b = win.getContentBounds();
  return p.x >= b.x && p.x < b.x + RAIL && p.y >= b.y && p.y < b.y + b.height;
}
function dock(tab, v) {                                                   // 떼어 낸 창을 닫음 → 원래 창으로 돌아와 앞에 보인다
  if (!win) { if (!v.webContents.isDestroyed()) v.webContents.close(); delete views[tab]; return; }
  win.contentView.addChildView(v);
  layout();
  show(tab);
}

ipcMain.on('rail-select', (e, tab) => {                                   // 아이콘 줄에서 누름 — 이미 그 탭이면 탭 첫 화면으로
  if (!win || e.sender !== win.webContents || !TABS[tab]) return;
  const v = views[tab];
  if (tab === active && v && v.webContents.getURL() !== TABS[tab]) show(tab, TABS[tab]);
  else show(tab);
});
ipcMain.on('rail-ready', e => { if (win && e.sender === win.webContents) sendRail(); });
ipcMain.on('rail-order', (e, list) => {                                    // 아이콘을 끌어 순서를 바꿈
  if (!win || e.sender !== win.webContents || !sameSet(list)) return;
  order = list.slice(); saveState(); sendRail();
});
ipcMain.on('rail-detach', (e, tab, x, y) => {                              // 아이콘을 창 밖으로 끌어 놓음
  if (win && e.sender === win.webContents && Number.isFinite(x) && Number.isFinite(y)) detach(tab, x, y);
});
ipcMain.on('rail-menu', (e, tab) => {                                      // 아이콘 우클릭
  if (!win || e.sender !== win.webContents || !TABS[tab]) return;
  const item = popped[tab]
    ? { label: '원래 창으로 다시 붙이기', click: () => popped[tab] && popped[tab].close() }
    : { label: '새 창으로 떼어 내기', click: () => { const p = screen.getCursorScreenPoint(); detach(tab, p.x + 90, p.y); } };
  Menu.buildFromTemplate([item]).popup({ window: win });
});

function create(page) {
  const st = readState();
  win = new BrowserWindow({
    // 카톡처럼 세로로 긴 창 — 571×860. 그보다 좁으면 답답해 최소 폭도 같게. 더 넓히는 건 자유(넓히면 허브가 두 칸으로 펼쳐진다)
    width: 571, height: 860, ...(st.bounds || {}), minWidth: 571, minHeight: 480,
    title: TITLE, icon: ICON, autoHideMenuBar: true, backgroundColor: bg(), show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, 'rail-preload.js') },
  });
  if (st.max) win.maximize();
  Menu.setApplicationMenu(null);
  win.once('ready-to-show', () => win.show());
  // ready-to-show 가 안 와서 창이 숨은 채로 남는 일이 있다(재부팅 직후 등 — 프로세스·창은 있는데 안 보임) — 2초 뒤엔 그냥 띄운다
  setTimeout(() => { if (win && !win.isDestroyed() && !win.isVisible() && !quitting) win.show(); }, 2000);
  const wc = win.webContents;                                             // 창 자신의 화면 = 왼쪽 아이콘 줄(로컬 파일)
  wc.on('will-navigate', e => e.preventDefault());
  wc.setWindowOpenHandler(() => ({ action: 'deny' }));
  keys(wc);
  win.loadFile(path.join(__dirname, 'rail.html')).catch(() => {});
  win.on('resize', layout);
  win.on('page-title-updated', e => e.preventDefault());               // 창 제목은 '자동화 허브' 로 둔다
  // 닫기(X)는 카톡처럼 숨기기만 — 다시 열 때(트레이 「자동화 허브 열기」) Electron 이 새로 뜨는 1초 가까이를 안 기다리고 보던 화면 그대로.
  // 대신 150MB 안팎을 계속 쓴다. 완전히 끄는 건 트레이 「종료」(프로세스를 끈다)·윈도우 종료뿐
  win.on('close', e => {
    saveState();
    if (quitting) return;
    e.preventDefault();
    win.hide();
  });
  // 트레이 「자동화 허브 열기」가 숨은 창에 보내는 신호 — electron.exe 를 또 띄워 넘겨받는(second-instance) 0.2~0.4초 없이 바로.
  // 트레이가 Win32 ShowWindow 로 직접 꺼내면 화면이 다시 안 그려져(옛 그림만 보임) 꼭 여기서 win.show() 한다. 번호는 app.py WM_SHELL_SHOW 와 같게
  win.hookWindowMessage(0xA0DC, () => {
    if (win.isMinimized()) win.restore();
    win.show(); win.focus();
  });
  win.on('query-session-end', () => { quitting = true; });               // 로그오프·재부팅을 막지 않게
  win.on('session-end', () => { quitting = true; });
  win.on('closed', () => {                                                // 떼어 낸 창은 그대로 둔다(닫을 때 원래 창이 없으면 그냥 닫힌다)
    win = null; active = null;
    for (const t of Object.keys(views)) {
      if (popped[t]) continue;
      try { if (!views[t].webContents.isDestroyed()) views[t].webContents.close(); } catch (_) {}
      delete views[t];
    }
  });
  const url = toUrl(page);
  show(tabFor(url), url);
}

app.on('second-instance', (_e, argv) => {
  if (!win) return create(pageArg(argv));
  if (win.isMinimized()) win.restore();
  win.show(); win.focus();
  if (argv.some(a => a.startsWith('--page='))) { const url = toUrl(pageArg(argv)); show(tabFor(url), url); }
});
app.whenReady().then(async () => { await fetchMode(); create(pageArg(process.argv)); watchMode(); watchChat(); });
app.on('before-quit', () => { quitting = true; });
app.on('window-all-closed', () => app.quit());
