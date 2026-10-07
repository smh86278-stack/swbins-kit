'use strict';
/* 매크로 허브 창 — 허브 화면(http://127.0.0.1:8630/)을 브라우저 탭이 아니라 '매크로 허브' 전용 창으로 연다.
 *
 *   electron.exe shell [--page=/ops]     (보통은 WorkKit.exe · 트레이 '매크로 허브 열기' 가 띄운다)
 *
 * 화면 펫(pet\)과 같은 Electron 을 쓴다. 창은 한 번에 하나 — 다시 열면 떠 있는 창이 앞으로 나오고 그 화면으로 간다.
 * 창을 닫아도 허브·트레이·서비스는 그대로 돈다(이 프로세스는 창만 맡는다). 허브 밖 주소는 기본 브라우저로 연다. */
const { app, BrowserWindow, shell, Menu, nativeTheme } = require('electron');
const fs = require('fs');
const path = require('path');

const HUB = 'http://127.0.0.1:8630';
const STATE = path.join(__dirname, 'window.local.json');
const ICON = path.join(__dirname, '..', 'web', 'app.ico');
const pageArg = argv => { const a = argv.find(x => x.startsWith('--page=')); const p = a ? a.slice(7) : '/'; return p.startsWith('/') ? p : '/'; };

app.setAppUserModelId('WorkKit');
app.setName('매크로 허브');
app.setPath('userData', path.join(__dirname, '..', 'data.local', 'shell-profile'));   // 펫과 프로필을 나눈다
if (!app.requestSingleInstanceLock()) { app.quit(); return; }

let win = null;

// 화면 모드(자동·라이트·다크) — 허브가 기억한다(/api/theme). 창 테두리(nativeTheme)와 배경색(web/theme.css 의 --bg)을 맞추고,
// 허브 /events 를 들어 화면에서 바꾸면 바로 따라간다. 허브가 꺼져 있으면 5초마다 다시 붙는다.
const BG = { light: '#f7f4fc', dark: '#1a1826' };
const bg = () => (nativeTheme.shouldUseDarkColors ? BG.dark : BG.light);
function applyMode(mode) {
  nativeTheme.themeSource = mode === 'light' || mode === 'dark' ? mode : 'system';
  if (win) win.setBackgroundColor(bg());
}
nativeTheme.on('updated', () => { if (win) win.setBackgroundColor(bg()); });
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
function readState() { try { return JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch (_) { return {}; } }
function saveState() {
  if (!win) return;
  try { fs.writeFileSync(STATE, JSON.stringify({ bounds: win.getNormalBounds(), max: win.isMaximized() })); } catch (_) {}
}
function internal(url) { return url === HUB || url.startsWith(HUB + '/'); }
function load(page) { win.loadURL(HUB + page).catch(() => {}); }

function create(page) {
  const st = readState();
  win = new BrowserWindow({
    width: 1280, height: 860, ...(st.bounds || {}), minWidth: 720, minHeight: 480,
    title: '매크로 허브', icon: ICON, autoHideMenuBar: true, backgroundColor: bg(), show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  if (st.max) win.maximize();
  Menu.setApplicationMenu(null);
  win.once('ready-to-show', () => win.show());
  const wc = win.webContents;
  wc.on('will-navigate', (e, url) => { if (!internal(url)) { e.preventDefault(); shell.openExternal(url); } });
  wc.setWindowOpenHandler(({ url }) => {
    if (internal(url)) { load(url.slice(HUB.length) || '/'); } else { shell.openExternal(url); }
    return { action: 'deny' };
  });
  wc.on('did-fail-load', (_e, code) => { if (code !== -3) setTimeout(() => load(page), 1500); });   // 허브가 막 뜨는 중
  wc.on('before-input-event', (e, input) => {                           // F5 · Ctrl+R 새로고침, Ctrl+Shift+I 개발자 도구
    if (input.type !== 'keyDown') return;
    if (input.key === 'F5' || (input.control && input.key.toLowerCase() === 'r')) { wc.reload(); e.preventDefault(); }
    if (input.control && input.shift && input.key.toLowerCase() === 'i') { wc.toggleDevTools(); e.preventDefault(); }
  });
  win.on('page-title-updated', e => e.preventDefault());               // 창 제목은 '매크로 허브' 로 둔다
  win.on('close', saveState);
  win.on('closed', () => { win = null; });
  load(page);
}

app.on('second-instance', (_e, argv) => {
  if (!win) return create(pageArg(argv));
  if (win.isMinimized()) win.restore();
  win.show(); win.focus();
  const page = pageArg(argv);
  if (page !== '/' || argv.some(a => a.startsWith('--page='))) load(page);
});
app.whenReady().then(async () => { await fetchMode(); create(pageArg(process.argv)); watchMode(); });
app.on('window-all-closed', () => app.quit());
