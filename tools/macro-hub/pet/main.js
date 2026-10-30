'use strict';
/* 자동화 허브 데스크톱 펫 — 허브가 내려 주는 투명 페이지(http://127.0.0.1:8630/pet)를 화면 구석에 띄운다.
 *
 *   npm start                 펫 시작 (이미 떠 있으면 두 번째는 바로 종료)
 *   npx electron . --selftest 창·마우스 처리 자가 점검(JSON 출력 후 종료, 설정 파일을 건드리지 않는다)
 *
 * 창은 투명·테두리 없음·항상 위·작업 표시줄에 안 보임·포커스를 가져가지 않는다(타이핑 중에 방해하지 않도록).
 * 투명한 곳은 마우스가 아래 창으로 통과하고, 펫 몸 위에서만 클릭·끌기가 된다(렌더러가 알려 준다).
 * 그림·표정·허브 연결은 전부 허브 쪽 페이지가 맡고, 여기는 창과 OS 기능만 다룬다. */
const { app, BrowserWindow, dialog, ipcMain, Menu, screen, shell } = require('electron');
const fs = require('fs');
const path = require('path');

const HUB = (process.env.HUB_URL || 'http://127.0.0.1:8630').replace(/\/$/, '');
const TEST = process.argv.includes('--selftest');
const SETTINGS_FILE = path.join(__dirname, TEST ? 'settings.selftest.json' : 'settings.local.json');
const SLOT_W = 184, PAD_W = 8, BASE_H = 268;

const defaults = { showDog: true, showCat: true, scale: 0.7, alwaysOnTop: true, x: null, y: null };
const MIN_SCALE = 0.4, MAX_SCALE = 2;
let settings = { ...defaults, ...readSettings() };
let win = null;
const recorded = [];                                   // 자가 점검용: 렌더러가 보낸 IPC 기록
const rec = (name, arg) => { if (TEST) recorded.push({ name, arg }); };

function readSettings() {
  try { return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8')); } catch (_) { return {}; }
}
function saveSettings() {
  try { fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 1)); } catch (_) { /* 저장 실패는 치명적이지 않다 */ }
}

function sizeFor(s) {
  const n = (s.showDog ? 1 : 0) + (s.showCat ? 1 : 0) || 1;
  return { width: Math.round((n * SLOT_W + PAD_W) * s.scale), height: Math.round(BASE_H * s.scale) };
}

function clampToScreen(b) {
  const wa = screen.getDisplayMatching(b).workArea;
  const keep = 80;                                      // 화면 밖으로 끌어내도 최소한 이만큼은 보이게 한다
  return {
    ...b,
    x: Math.min(Math.max(b.x, wa.x - b.width + keep), wa.x + wa.width - keep),
    y: Math.min(Math.max(b.y, wa.y - b.height + keep), wa.y + wa.height - keep),
  };
}

function initialBounds() {
  const { width, height } = sizeFor(settings);
  const wa = screen.getPrimaryDisplay().workArea;
  let b = { x: wa.x + wa.width - width - 16, y: wa.y + wa.height - height - 8, width, height };
  if (Number.isFinite(settings.x) && Number.isFinite(settings.y)) b = { ...b, x: settings.x, y: settings.y };
  return clampToScreen(b);
}

function trusted(e) {                                   // 허브 페이지에서 온 요청만 받는다
  try { return e.senderFrame.url.startsWith(HUB + '/'); } catch (_) { return false; }
}

function applySettings(patch) {
  if (patch && !('showDog' in patch && 'showCat' in patch)) {
    const next = { ...settings, ...patch };
    if (!next.showDog && !next.showCat) return;         // 둘 다 숨기는 건 막는다(종료 메뉴가 따로 있다)
  }
  const old = win.getBounds();
  settings = { ...settings, ...patch };
  const { width, height } = sizeFor(settings);
  // 오른쪽·아래 모서리를 고정한 채 크기만 바꾼다(화면 구석에 붙어 있던 펫이 밀려나지 않게)
  win.setBounds(clampToScreen({ x: old.x + old.width - width, y: old.y + old.height - height, width, height }));
  win.setAlwaysOnTop(!!settings.alwaysOnTop, 'floating');
  win.webContents.send('pet:settings', publicSettings());
  const b = win.getBounds(); settings.x = b.x; settings.y = b.y;
  saveSettings();
}
const publicSettings = () => ({ showDog: settings.showDog, showCat: settings.showCat, scale: settings.scale });

function openHub() { rec('open'); if (!TEST) shell.openExternal(HUB + '/'); }

async function fetchSkins() {
  try {
    const r = await fetch(HUB + '/api/skins', { signal: AbortSignal.timeout(1500) });
    return r.ok ? await r.json() : [];
  } catch (_) { return []; }
}

async function currentSkin(full) {                      // 스킨·품종은 허브가 기억한다(정본) — 여기엔 저장하지 않는다
  try {
    const r = await fetch(HUB + '/api/skin', { signal: AbortSignal.timeout(1500) });
    const j = r.ok ? await r.json() : {};
    return full ? { skin: j.skin || 'plush', breed: j.breed || {} } : (j.skin || 'plush');
  } catch (_) { return full ? { skin: 'plush', breed: {} } : null; }
}

async function skinBreeds(id) {                          // 스킨의 품종 목록 {dog: {shiba: {name}}, cat: {...}} — 없으면 {}
  try {
    const r = await fetch(HUB + '/skin/' + encodeURIComponent(id) + '/skin.json', { signal: AbortSignal.timeout(1500) });
    return r.ok ? ((await r.json()).breeds || {}) : {};
  } catch (_) { return {}; }
}

async function currentPetx() {                          // 소품·계절 — 허브가 기억한다(web/pets.js PetAcc · /api/petx)
  try {
    const r = await fetch(HUB + '/api/petx', { signal: AbortSignal.timeout(1500) });
    return r.ok ? await r.json() : null;
  } catch (_) { return null; }
}
const QUIET = [['none', '없음'], ['lunch', '점심 (12~13시)'], ['night', '저녁·밤 (18~9시)'], ['both', '점심 + 저녁·밤']];
const ACCS = [['none', '없음'], ['ribbon', '리본'], ['scarf', '목도리'], ['glasses', '안경'], ['beret', '베레모'], ['bowtie', '나비넥타이'], ['crown', '왕관']];

async function showMenu() {
  rec('menu');
  if (TEST) return;
  const sizes = [['아주 작게', 0.5], ['작게', 0.7], ['보통', 0.9], ['크게', 1.15], ['아주 크게', 1.5]];
  const [skins, cur, px] = await Promise.all([fetchSkins(), currentSkin(true), currentPetx()]);
  const setPetx = v => { if (win) win.webContents.send('pet:set-skin', { petx: v }); };   // 렌더러가 토큰을 붙여 /api/petx 로
  // 키우기(간식·레벨) — 켜 두면 레벨로 소품이 풀린다(허브 petgrow.py). 끄면 다 풀리고 레벨은 안 보인다
  const lv = px && px.lv, level = lv ? lv.level : 1, grow = !!(px && px.grow !== false);
  const locked = id => grow && ((px.unlock || {})[id] || 0) > level;
  const lvLine = grow && lv ? [{ label: 'Lv.' + level + ' · 간식 ' + lv.snacks + '개' + (lv.next ? '  (다음 레벨까지 ' + (lv.next - lv.snacks) + '개)' : ''), enabled: false }] : [];
  const accMenu = px ? [{
    label: '소품 · 말풍선', submenu: [
      ...lvLine,
      { label: '계절 소품 자동 (할로윈·크리스마스·봄)', type: 'checkbox', checked: px.season, click: () => setPetx({ season: !px.season }) },
      { label: '키우기 (자동화가 성공하면 간식 · 레벨로 소품이 풀림)', type: 'checkbox', checked: grow, click: () => setPetx({ grow: !grow }) },
      { label: '말풍선 (예약 곧 · 실패 · 메신저 · 주간 소식, 20분에 한 번)', type: 'checkbox', checked: px.bubble !== false, click: () => setPetx({ bubble: px.bubble === false }) },
      { label: '조용히 시간 (실패만 알림)', submenu: QUIET.map(([id, name]) => ({ label: name, type: 'radio', checked: (px.quiet || 'none') === id, click: () => setPetx({ quiet: id }) })) },
      { type: 'separator' },
      ...['dog', 'cat'].map(kind => ({ label: kind === 'dog' ? '강아지' : '고양이', submenu: ACCS.map(([id, name]) => ({
        label: locked(id) ? name + '  (잠김 · Lv.' + px.unlock[id] + ')' : name, type: 'radio', enabled: !locked(id),
        checked: (px.acc[kind] || 'none') === id, click: () => setPetx({ acc: { [kind]: id } }) })) })),
    ],
  }] : [];
  const curSkin = cur.skin, breeds = await skinBreeds(curSkin);
  const pickSkin = id => { if (win) win.webContents.send('pet:set-skin', id); };   // 렌더러가 토큰을 붙여 허브에 요청한다
  const breedMenu = (kind, label) => {                   // 품종 — 고른 게 없거나 모르는 것이면 첫 번째가 쓰인다(web/pets.js applyBreed 와 같게)
    const ids = Object.keys(breeds[kind] || {});
    if (!ids.length) return [];
    const sel = ids.includes(cur.breed[kind]) ? cur.breed[kind] : ids[0];
    return [{ label, submenu: ids.map(b => ({ label: breeds[kind][b].name || b, type: 'radio', checked: sel === b,
      click: () => { if (win) win.webContents.send('pet:set-skin', { breed: { [kind]: b } }); } })) }];
  };
  const isSize = v => Math.abs(settings.scale - v) < 0.01;
  const menu = Menu.buildFromTemplate([
    { label: '강아지 보이기', type: 'checkbox', checked: settings.showDog, click: () => applySettings({ showDog: !settings.showDog }) },
    { label: '고양이 보이기', type: 'checkbox', checked: settings.showCat, click: () => applySettings({ showCat: !settings.showCat }) },
    { type: 'separator' },
    { label: '크기 (펫 위에서 마우스 휠로 미세 조정)', submenu: sizes.map(([label, scale]) => ({ label, type: 'radio', checked: isSize(scale), click: () => applySettings({ scale }) })) },
    {
      label: '모습(스킨)', submenu: [
        ...skins.map(k => ({ label: k.name || k.id, type: 'radio', checked: curSkin === k.id, click: () => pickSkin(k.id) })),
        ...(skins.length ? [] : [{ label: '(web\\skins 에 폴더를 넣으면 여기에 나옵니다)', enabled: false }]),
      ],
    },
    ...breedMenu('dog', '강아지 품종'),
    ...breedMenu('cat', '고양이 품종'),
    ...accMenu,
    { label: '항상 위에 표시', type: 'checkbox', checked: settings.alwaysOnTop, click: () => applySettings({ alwaysOnTop: !settings.alwaysOnTop }) },
    { type: 'separator' },
    { label: '자동화 허브 열기', click: openHub },
    { label: '펫 끄기  (트레이 메뉴·허브 화면에서 다시 켤 수 있어요)', click: askOff },
  ]);
  menu.popup({ window: win });
}

async function askOff() {
  // 펫은 화면 아래에 있어 메뉴가 위로 열리고, 맨 아래 '펫 끄기'가 마우스 바로 밑에 온다 — 잘못 눌러 꺼지는 일이 잦아 한 번 묻는다(2026-10-07)
  if (!TEST) {
    const r = await dialog.showMessageBox({
      type: 'question', title: '자동화 허브 펫', message: '화면 펫을 끌까요?',
      detail: '트레이 메뉴나 허브 화면의 「화면 펫 켜기」로 다시 켤 수 있어요.',
      buttons: ['펫 끄기', '취소'], defaultId: 1, cancelId: 1, noLink: true,
    });
    if (r.response !== 0) return;
  }
  // 허브에 '꺼 둔 상태'로 기억시킨 뒤 허브가 이 프로세스를 끈다. 허브가 안 떠 있으면 3초 뒤 직접 끈다.
  if (win) win.webContents.send('pet:ask-off');
  setTimeout(() => app.quit(), 3000);
}

function loadHub() {
  win.loadURL(HUB + '/pet').catch(() => {});            // 실패하면 did-fail-load 가 다시 시도한다
}

function createWindow() {
  const b = initialBounds();
  win = new BrowserWindow({
    ...b,
    transparent: true, frame: false, resizable: false, hasShadow: false, show: false,
    skipTaskbar: true, focusable: false, alwaysOnTop: !!settings.alwaysOnTop, title: '자동화 허브 펫',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: false },
  });
  win.setAlwaysOnTop(!!settings.alwaysOnTop, 'floating');
  win.setIgnoreMouseEvents(true, { forward: true });    // 시작은 클릭 통과, 펫 위에 올라가면 렌더러가 풀어 준다
  win.once('ready-to-show', () => win.showInactive());

  const wc = win.webContents;
  wc.on('will-navigate', (e, url) => { if (!url.startsWith(HUB + '/')) e.preventDefault(); });
  wc.setWindowOpenHandler(() => ({ action: 'deny' }));
  wc.on('did-fail-load', (_e, code) => { if (code !== -3) setTimeout(loadHub, 3000); });   // 허브가 아직 안 떴으면 계속 기다린다
  wc.on('render-process-gone', () => setTimeout(loadHub, 1000));
  loadHub();
}

ipcMain.on('pet:ignore', (e, v) => { if (!trusted(e) || !win) return; rec('ignore', !!v); win.setIgnoreMouseEvents(!!v, { forward: true }); });
ipcMain.on('pet:drag', (e, dx, dy) => {
  if (!trusted(e) || !win) return;
  rec('drag', [dx, dy]);
  const b = win.getBounds();
  win.setBounds({ x: Math.round(b.x + dx), y: Math.round(b.y + dy), width: b.width, height: b.height });   // 크기를 같이 넘겨야 DPI 배율에서 안 커진다
});
ipcMain.on('pet:save', e => {
  if (!trusted(e) || !win) return;
  rec('save');
  const b = clampToScreen(win.getBounds());
  win.setBounds(b);
  settings.x = b.x; settings.y = b.y; saveSettings();
});
ipcMain.on('pet:open', e => { if (trusted(e)) openHub(); });
ipcMain.on('pet:open-url', (e, p) => {                 // 쪽지(말풍선) — 허브 안 경로('/ops' 등) 또는 이 PC 의 메신저·AI 작업 회고 첫 화면만 연다
  if (!trusted(e) || typeof p !== 'string') return;
  rec('open-url', p);
  const url = /^\/(?!\/)/.test(p) ? HUB + p : /^http:\/\/127\.0\.0\.1:\d{2,5}\/$/.test(p) ? p : null;   // 바깥은 이 PC 화면의 첫 페이지만(주소는 허브 /api/petnote 가 설정에서)
  if (url && !TEST) shell.openExternal(url);
});
ipcMain.on('pet:scale', (e, dir) => {                  // 펫 위에서 휠: 한 칸에 약 10%
  if (!trusted(e) || !win) return;
  rec('scale', dir);
  const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round(settings.scale * (dir > 0 ? 1.1 : 1 / 1.1) * 100) / 100));
  if (next !== settings.scale) applySettings({ scale: next });
});
ipcMain.on('pet:menu', e => { if (trusted(e) && win) showMenu(); });
ipcMain.handle('pet:settings', e => (trusted(e) ? publicSettings() : defaults));

/* ---------------- 자가 점검 ---------------- */
async function selfTest() {
  const out = [];
  const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });
  const run = code => win.webContents.executeJavaScript(code);
  await new Promise(r => setTimeout(r, 2000));                         // 페이지 스크립트·첫 연결 대기
  // 마우스 점검은 기본 스킨(plush) 그림을 겨냥하므로 잠시 기본 스킨으로 바꾸고, 끝에서 허브가 기억하던 모습으로 되돌린다
  const setSkinOnHub = id => run(`fetch('/api/skin', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Hub-Token': TOKEN}, body: JSON.stringify({skin: ${JSON.stringify(id)}})}).then(r => r.ok)`);
  const prevSkin = await currentSkin();
  check('허브에 모습(스킨)을 요청할 수 있다', await setSkinOnHub('plush'));
  for (let i = 0; i < 30 && !(await run(`!!document.querySelector('#dog .skin-media')`)); i++) await new Promise(r => setTimeout(r, 200));
  await new Promise(r => setTimeout(r, 800));
  const take = () => recorded.splice(0, recorded.length);

  const pts = await run(`(() => {
    const el = document.querySelector('#dog .skin-media'); const r = el.getBoundingClientRect();
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
  })()`);
  const fire = (type, x, y, extra) => run(`(() => {
    const el = document.elementFromPoint(${x}, ${y}) || document.body;
    const Ev = '${type}'.startsWith('pointer') ? PointerEvent : '${type}' === 'wheel' ? WheelEvent : MouseEvent;
    el.dispatchEvent(new Ev('${type}', Object.assign({ bubbles: true, cancelable: true, button: 0, clientX: ${x}, clientY: ${y},
      screenX: ${x}, screenY: ${y}, pointerId: 1, isPrimary: true }, ${JSON.stringify(extra || {})})));
    return el.tagName;
  })()`);

  // 1) 투명 배경
  check('배경이 투명하다', await run(`getComputedStyle(document.body).backgroundColor === 'rgba(0, 0, 0, 0)'`));
  // 2) 히트 테스트: 펫 몸 위에서는 마우스를 받고, 빈 곳에서는 통과
  take(); await fire('mousemove', pts.x, pts.y);
  const onPet = take();
  check('펫 위에서는 마우스를 받는다', onPet.some(r => r.name === 'ignore' && r.arg === false), JSON.stringify(onPet));
  // 빈 곳(펫·말풍선이 아닌 페이지 바탕)에 마우스가 오면 통과 — 말풍선은 글에 따라 크기가 바뀌며 떴다 사라져서, 좌표 대신 바탕에 직접 보낸다
  const empty = { x: 2, y: 2 };
  await run(`document.documentElement.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 2, clientY: 2 }))`);
  await new Promise(r => setTimeout(r, 150));
  const onEmpty = take();
  check('투명한 곳은 클릭이 통과한다', onEmpty.some(r => r.name === 'ignore' && r.arg === true), JSON.stringify(onEmpty) + ' at ' + JSON.stringify(empty));
  // 3) 끌기: 4px 이상 움직이면 창이 따라 움직이고, 클릭(허브 열기)으로 오인하지 않는다
  await fire('mousemove', pts.x, pts.y); take();
  const b0 = win.getBounds();
  await fire('pointerdown', pts.x, pts.y);
  await fire('pointermove', pts.x + 60, pts.y + 20);
  await fire('pointerup', pts.x + 60, pts.y + 20);
  const dragRec = take(); const b1 = win.getBounds();
  check('끌면 창이 따라 움직인다', Math.abs(b1.x - b0.x - 60) <= 1 && Math.abs(b1.y - b0.y - 20) <= 1, `이동 ${b1.x - b0.x},${b1.y - b0.y}`);
  check('끌기를 클릭으로 오인하지 않는다', !dragRec.some(r => r.name === 'open'), JSON.stringify(dragRec.map(r => r.name)));
  check('끌기가 끝나면 위치를 저장한다', dragRec.some(r => r.name === 'save'));
  // 4) 클릭: 거의 안 움직이면 허브를 연다
  await fire('mousemove', pts.x + 60, pts.y + 20); take();
  await fire('pointerdown', pts.x + 60, pts.y + 20);
  await fire('pointerup', pts.x + 60, pts.y + 20);
  check('클릭하면 허브를 연다', take().some(r => r.name === 'open'));
  // 5) 오른쪽 클릭: 메뉴
  await fire('contextmenu', pts.x + 60, pts.y + 20);
  check('오른쪽 클릭하면 메뉴를 연다', take().some(r => r.name === 'menu'));
  // 6) 화면 밖 보정: 아주 멀리 끌어도 일부는 화면 안에 남는다
  win.setBounds({ ...win.getBounds(), x: -5000, y: -5000 });
  win.webContents.send('pet:settings', publicSettings());
  const fixed = clampToScreen(win.getBounds());
  const wa = screen.getDisplayMatching(fixed).workArea;
  check('화면 밖으로 나가도 되돌린다', fixed.x + fixed.width > wa.x && fixed.y + fixed.height > wa.y, JSON.stringify(fixed));
  // 6-2) 휠로 크기 조절: 올리면 커지고 내리면 작아지며, 한계에서 멈춘다
  const s0 = settings.scale, w0 = win.getBounds().width;
  await fire('wheel', pts.x, pts.y, { deltaY: -100 });
  const grown = settings.scale, w1 = win.getBounds().width;
  check('휠을 올리면 커진다', grown > s0 && w1 > w0, `scale ${s0} → ${grown}, 폭 ${w0} → ${w1}`);
  // 크기가 바뀌면 펫이 창 안에서 움직이므로, 휠을 돌릴 때마다 펫 몸 위의 좌표를 다시 구한다
  const wheel = async dy => { const q = await run(`(() => { const r = document.querySelector('#dog .art').getBoundingClientRect();
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) }; })()`); await fire('wheel', q.x, q.y, { deltaY: dy }); };
  for (let i = 0; i < 40; i++) await wheel(100);
  check('휠을 계속 내려도 하한(' + MIN_SCALE + ')에서 멈춘다', settings.scale >= MIN_SCALE && settings.scale < 0.5, 'scale ' + settings.scale);
  for (let i = 0; i < 40; i++) await wheel(-100);
  check('휠을 계속 올려도 상한(' + MAX_SCALE + ')에서 멈춘다', settings.scale <= MAX_SCALE && settings.scale > 1.9, 'scale ' + settings.scale);
  applySettings({ scale: s0 });
  // 7) 그림·표정이 실제로 붙었나
  const mood = await run(`({ dog: document.querySelector('#dog').dataset.mood, cat: document.querySelector('#cat').dataset.mood,
    bubble: document.querySelector('#dogBubble').textContent, arts: document.querySelectorAll('.art .skin-media').length, badge: !!document.querySelector('#cat .motion-badge') })`);
  check('두 마리의 그림과 표정이 붙었다', mood.arts === 2 && !!mood.dog && !!mood.cat, JSON.stringify(mood));
  check('고양이에 일의 종류 표시(배지)가 붙었다', mood.badge);
  check('말풍선에 말이 있다', mood.bubble.length > 0, mood.bubble);

  if (process.env.SELFTEST_SKIN) {
    await setSkinOnHub(process.env.SELFTEST_SKIN);
    await new Promise(r => setTimeout(r, 2500));
    const sk = await run(`(() => { const m = document.querySelector('#dog .skin-media'); return m ? { tag: m.tagName, ok: (im => im.tagName === 'IMG' ? (im.complete && im.naturalWidth > 0) : im.tagName === 'CANVAS' ? im.width > 0 : im.readyState >= 2)(m.querySelector('img,video,canvas') || m),
      skinned: document.querySelector('#dog').classList.contains('skinned') } : null; })()`);
    check('스킨 이미지가 실제로 표시된다', sk && sk.ok && sk.skinned, JSON.stringify(sk));
    if (process.env.SELFTEST_SKIN_SEQ) {
      const srcs = new Set();
      for (let i = 0; i < 10; i++) { srcs.add(await run(`(document.querySelector('#dog .skin-media') || {}).src || ''`)); await new Promise(r => setTimeout(r, 120)); }
      check('PNG 시퀀스가 프레임을 바꿔 가며 재생된다', srcs.size >= 3, 'src 종류 ' + srcs.size);
    }
  }
  await setSkinOnHub(prevSkin);                         // 시험이 허브가 기억한 모습을 바꿔 놓지 않게 되돌린다

  const failed = out.filter(r => !r.ok);
  for (const r of out) console.log((r.ok ? 'PASS ' : 'FAIL ') + r.name + (r.detail ? '  → ' + r.detail : ''));
  console.log('결과: %d/%d 통과', out.length - failed.length, out.length);
  try { fs.unlinkSync(SETTINGS_FILE); } catch (_) { /* 시험 설정 파일 정리 */ }
  app.exit(failed.length ? 1 : 0);
}

/* ---------------- 시작 ---------------- */
if (!TEST && !app.requestSingleInstanceLock()) {
  app.quit();                                           // 이미 떠 있다
} else {
  app.whenReady().then(() => {
    createWindow();
    if (TEST) win.webContents.once('did-finish-load', () => selfTest().catch(e => { console.log('FAIL 자가 점검 오류: ' + e); app.exit(2); }));
  });
  app.on('window-all-closed', () => app.quit());
}
