const $ = s => document.querySelector(s);
const TAG = { read: '#c', write: '#cw' };          // PC 게이트웨이의 지시 태그(읽기 · 수정 허용)
const store = {                                   // 이 기기의 설정·보낸 기록. 저장이 막힌 브라우저에서도 화면은 돈다
  // 키 앞머리 'kitdispatch.' — 같은 github.io 출처의 다른 페이지와 저장 공간이 겹치지 않게(2026-10-19 보안 점검).
  // 옛 'dispatch.' 값은 옮겨 오지 않는다 — 같은 출처의 다른 페이지 것(Gmail 토큰 등)을 가져올 수 있어서. 설정은 한 번 다시 넣는다
  get(k, d) { try { const v = localStorage.getItem('kitdispatch.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('kitdispatch.' + k, JSON.stringify(v)); } catch (e) {} },
};
let cfg = store.get('cfg', { mail: '', folders: [], prefix: '', cmd: '/issue' });
let sent = store.get('sent', []);
let mode = 'read', folder = '', picks = new Set(), stop = false, pickN = 4;

function toast(t) { const e = $('#toast'); e.textContent = t; e.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => e.classList.remove('show'), 2600); }
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
const pad = n => String(n).padStart(2, '0');

/* ---- 보낸 기록 ---- */
function draw() {
  const box = $('#log'); box.replaceChildren();
  if (gOn()) { drawGmail(box); return; }
  plainBar();
  if (!sent.length) {
    const e = el('div', 'empty');
    e.innerHTML = '<b>메일로 일을 맡기는 곳</b><br><br>아래에 할 일을 적고 보내면 메일 앱이 다 채워진 채 열립니다. <b>보내기</b>만 누르세요.<br><br><b>답은 이 화면이 아니라 메일 앱으로 옵니다</b>(이 페이지는 메일함을 읽지 못해요). 메일 안의 단추로 바로 답하거나, 여기 <b>답하기</b> 탭에서 체크박스로 고르세요.';
    box.append(e); return;
  }
  let lastDay = '';
  for (const s of sent) {
    const d = new Date(s.at), day = (d.getMonth() + 1) + '월 ' + d.getDate() + '일';
    if (day !== lastDay) { box.append(el('div', 'day', day)); lastDay = day; }
    const m = el('div', 'msg'), b = el('div', 'bubble', s.text), meta = el('div', 'meta');
    meta.append(el('span', 'tagchip' + (s.mode === 'write' ? ' w' : ''), s.label));
    meta.append(el('span', '', pad(d.getHours()) + ':' + pad(d.getMinutes())));
    const del = el('button', 'del', '지우기');                // 이 기기의 보낸 기록에서만 뺀다(PC·메일은 그대로)
    del.onclick = () => { sent = sent.filter(x => x !== s); store.set('sent', sent); draw(); };
    meta.append(del);
    if (s.kind === 'say') {
      const again = el('button', 'again', '다시 쓰기');
      again.onclick = () => { setTab('say'); $('#sayText').value = s.text; $('#sayThread').value = s.thread || ''; setMode(s.mode); grow($('#sayText')); refresh(); $('#sayText').focus(); };
      meta.append(again);
    }
    m.append(b, meta); box.append(m);
  }
  const hint = el('div', 'tail', '답은 메일 앱으로 옵니다');     // 메일 앱 모드는 보내기 전용 — 메일함을 읽지 못한다
  const go = el('a', '', '메일 앱 열기'); go.href = 'message://';  // iOS 메일 앱
  hint.append(go); box.append(hint);
  box.scrollTop = box.scrollHeight;
}

function plainBar() {                                 // 메일 앱 모드: 대화방 없이 처음 화면 그대로
  for (const id of ['#sayRow', '#ansRow', '#modeChips', '#logo']) $(id).style.display = '';
  $('#quick').style.display = 'none';
  $('#clipBtn').style.display = 'none'; attach = []; drawAttach();      // 메일 앱으로는 사진을 못 붙인다
  for (const b of document.querySelectorAll('.tabs button')) b.style.display = '';
  editing = false; $('#editBar').classList.remove('on'); $('.composer').style.display = '';
  $('#pinBtn').style.display = 'none'; $('#searchBar').classList.remove('on');
  $('#backBtn').style.display = $('#delBtn').style.display = 'none'; $('#ttl').textContent = '디스패치'; $('.tabs').style.display = '';
  document.querySelector('.tabs [data-pane=say]').textContent = '지시';
  $('#sayText').disabled = false; $('#sayText').placeholder = '할 일을 적으세요 (첫 줄이 제목)';
}

/* ---- 메일 앱 열기 ---- */
function openMail(subject, body, rec) {
  if (!cfg.mail) { openSettings(); toast('먼저 메일 주소를 넣어 주세요'); return false; }   // 입력은 지우지 않는다
  const enc = s => encodeURIComponent(s).replace(/%0A/g, '%0D%0A');
  // '새 지시는 메일 앱으로'를 켜면 새 지시(사진 없음)만 메일 앱으로 — 회사 메일 스팸 장비가 외부 Gmail(API) 로 보낸 새 메일만
  // 붙잡는 곳이 있다. 답장(이어 말하기·답하기·멈춤)은 대개 걸리지 않는다. 더 나은 길은 '나에게 보내기'(PC 가 Gmail 을 직접 읽음).
  const viaApp = gOn() && !cfg.self && cfg.viaApp === true && !(rec.thread > 0) && !(rec.files || []).length && (rec.kind === 'say' || rec.kind === 'issue');
  if (viaApp) {
    gloc.push({ at: Date.now(), subj: subject, text: rec.text, mode: rec.mode });
    gloc = gloc.filter(x => Date.now() - x.at < 7 * 86400e3).slice(-100); store.set('gloc', gloc);
  }
  if (gOn() && !viaApp) {                                   // Gmail 로 바로 보낸다. 연결이 끊겼으면 다시 연결하고 돌아와서 보낸다
    // 암호 단어는 제목 대신 본문 마지막 줄로 — 제목을 깨끗하게 둔다(PC 가 떼어 낸다)
    if (cfg.key) body = (body ? body + '\n\n' : '') + '[k:' + cfg.key + ']';
    gout.push({ subject, body, files: rec.files || [], reply: rec.reply || gReplyTo(rec.thread), text: rec.text, mode: rec.mode, thread: rec.thread || null, at: Date.now() });
    store.set('gout', gout); draw();
    if (gLive()) gPoll(); else if (gtok) gAuth(true); else gAuth(false);
    return true;
  }
  if (cfg.key) subject += ' [k:' + cfg.key + ']';          // 메일 앱은 제목 끝에 — PC 회신 메일의 답장 단추도 이 모양이다
  const url ='mailto:' + encodeURIComponent(cfg.mail) + '?subject=' + enc(subject) + '&body=' + enc(body);
  (window.dispatchGo || (u => { location.href = u; }))(url);   // dispatchGo: 시험용 가로채기
  if (viaApp) { draw(); toast('메일 앱에서 보내기를 누르세요'); gPoll(); return true; }
  sent.push(Object.assign({ at: Date.now() }, rec)); sent = sent.slice(-200); store.set('sent', sent); draw();
  toast('메일 앱에서 보내기를 누르세요');
 
  return true;
}

/* ---- 지시 ---- */
function setMode(m) { mode = m; for (const b of document.querySelectorAll('#modeChips [data-mode]')) b.classList.toggle('on', b.dataset.mode === m); }
function drawFolders() {
  const box = $('#folderChips'); box.replaceChildren();
  for (const f of [''].concat(cfg.folders || [])) {
    const b = el('button', 'chip' + (f === folder ? ' on' : ''), f ? '@' + f : '기본 폴더');
    b.onclick = () => { folder = f; drawFolders(); }; box.append(b);
  }
}
$('#saySend').onclick = () => {
  let text = $('#sayText').value.trim();
  const t = parseInt($('#sayThread').value, 10), files = attach.slice();
  if (!text && !files.length) return;
  if (!text) text = '사진 봐줘';                          // 사진만 보내면 이 말로
  const [first, ...rest] = text.split('\n');
  const head = [TAG[mode]];
  if (t > 0) head.push('[T' + t + ']');
  else if (folder) head.push('@' + folder);             // 이어 쓰는 대화는 원래 폴더를 그대로 쓴다
  const subject = head.join(' ') + ' ' + first.trim().slice(0, 90);
  const body = (first.trim().length > 90 ? first.trim() + '\n' : '') + rest.join('\n').trim();
  if (!openMail(subject, body, { kind: 'say', text, mode, files, thread: t > 0 ? t : '', label: (t > 0 ? 'T' + t + ' · ' : '') + (mode === 'write' ? '수정' : '읽기') + (folder && !(t > 0) ? ' @' + folder : '') })) return;
  $('#sayText').value = ''; grow($('#sayText')); attach = []; drawAttach(); refresh();
};

/* ---- 사진 붙이기(Gmail 모드) — 폰에서 긴 변 1600px JPEG 로 줄여 지시 메일에 붙인다. PC 가 저장해 Claude 가 Read 로 본다 ---- */
let attach = [];                                         // [{ b64, url }]
const MAX_ATTACH = 5;
function shrink(file) {
  return new Promise((res, rej) => {
    const src = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement('canvas');
      c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      const url = c.toDataURL('image/jpeg', 0.82);
      URL.revokeObjectURL(src);
      res({ b64: url.slice(url.indexOf(',') + 1), url });
    };
    img.onerror = () => { URL.revokeObjectURL(src); rej(new Error('사진을 읽지 못했습니다')); };
    img.src = src;
  });
}
function drawAttach() {
  const box = $('#attPrev');
  box.style.display = attach.length ? '' : 'none';
  box.replaceChildren(...attach.map((a, i) => {
    const t = el('div', 'thumb'), im = document.createElement('img'), x = el('button', '', '✕');
    im.src = a.url; im.alt = '붙인 사진 ' + (i + 1);
    x.onclick = () => { attach.splice(i, 1); drawAttach(); refresh(); };
    t.append(im, x); return t;
  }));
}
$('#clipBtn').onclick = () => {
  if (attach.length >= MAX_ATTACH) { toast('사진은 ' + MAX_ATTACH + '장까지 붙일 수 있어요'); return; }
  $('#clipIn').click();
};
$('#clipIn').onchange = async e => {
  const files = [...e.target.files];
  e.target.value = '';
  if (files.length > MAX_ATTACH - attach.length) toast('사진은 ' + MAX_ATTACH + '장까지 — 앞의 것만 붙였어요');
  for (const f of files.slice(0, MAX_ATTACH - attach.length)) {
    try { attach.push(await shrink(f)); } catch (err) { toast(err.message); }
  }
  drawAttach(); refresh();
};

/* ---- 답하기(체크박스) ---- */
function drawPicks() {
  const box = $('#picks'); box.replaceChildren();
  for (let i = 1; i <= pickN; i++) {
    const b = el('button', 'pick' + (picks.has(i) ? ' on' : ''));
    b.setAttribute('role', 'checkbox'); b.setAttribute('aria-checked', picks.has(i));
    const box2 = el('span', 'box', picks.has(i) ? '✓' : ''); b.append(box2, String(i));
    b.onclick = () => { picks.has(i) ? picks.delete(i) : picks.add(i); stop = false; $('#stopBtn').classList.remove('on'); drawPicks(); refresh(); };
    box.append(b);
  }
}
$('#stopBtn').onclick = () => { stop = !stop; if (stop) picks.clear(); $('#stopBtn').classList.toggle('on', stop); drawPicks(); refresh(); };
$('#ansSend').onclick = () => {
  const t = parseInt($('#ansThread').value, 10), extra = $('#ansText').value.trim();
  if (!(t > 0)) { toast('메일 제목의 [T번호] 를 넣어 주세요'); return; }
  const nums = [...picks].sort((a, b) => a - b).join(',');
  const body = stop ? '멈춤' : (nums + (nums && extra ? ' ' : '') + extra);
  if (!body) return;
  if (!openMail('Re: ' + TAG.read + ' [T' + t + '] 답', body, { kind: 'answer', thread: t, text: stop ? '멈춤' : (nums ? '☑ ' + nums.split(',').join(' ☑ ') : '') + (extra ? (nums ? '\n' : '') + extra : ''), mode: 'read', label: 'T' + t + ' · 답' })) return;
  picks.clear(); stop = false; pickN = 4; $('#stopBtn').classList.remove('on'); $('#ansText').value = ''; drawPicks(); refresh();
  if (gOn()) setTab('say');
};

/* ---- 이슈 ---- */
$('#issueSend').onclick = () => {
  const n = $('#issueNo').value.trim(); if (!n || !cfg.prefix) return;
  const key = (/^[A-Za-z]/.test(n) ? '' : cfg.prefix) + n.toUpperCase();   // 키 전체를 적었으면 앞부분을 붙이지 않는다
  if (!/^[A-Z][A-Z0-9_]*-\d+$/.test(key)) { toast('이슈 키 형식이 아닙니다 (예: ' + cfg.prefix + '123)'); return; }
  if (!openMail(TAG.write + ' ' + (cfg.cmd || '/issue') + ' ' + key, '', { kind: 'issue', text: '이슈 ' + key + ' 처리 시작', mode: 'write', label: '이슈' })) return;
  $('#issueNo').value = ''; refresh();
};

/* ---- 공통 ---- */
function setTab(name) {
  for (const b of document.querySelectorAll('.tabs button')) b.classList.toggle('on', b.dataset.pane === name);
  for (const p of document.querySelectorAll('.pane')) p.classList.toggle('on', p.id === name);
  store.set('tab', name);
}
for (const b of document.querySelectorAll('.tabs button')) b.onclick = () => setTab(b.dataset.pane);
for (const b of document.querySelectorAll('#modeChips [data-mode]')) b.onclick = () => setMode(b.dataset.mode);
function grow(t) { t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 140) + 'px'; }
function refresh() {
  $('#saySend').disabled = !$('#sayText').value.trim() && !attach.length;
  $('#ansSend').disabled = !(parseInt($('#ansThread').value, 10) > 0 && (picks.size || stop || $('#ansText').value.trim()));
  $('#issueSend').disabled = !$('#issueNo').value.trim();
}
for (const id of ['#sayText', '#ansText']) $(id).addEventListener('input', e => { grow(e.target); refresh(); });
for (const id of ['#ansThread', '#issueNo', '#sayThread']) $(id).addEventListener('input', refresh);

function openSettings() {
  $('#setKey').value = cfg.key || ''; $('#setGcid').value = cfg.gcid || ''; $('#setViaApp').checked = cfg.viaApp === true; $('#setCmd').value = cfg.cmd || '/issue'; $('#setSelf').checked = !!cfg.self;
  $('#gOff').style.display = gtok ? '' : 'none';
  $('#gHint').textContent = gtok && gtok.email ? gtok.email + ' 로 연결돼 있습니다.' : '넣고 저장하면 Google 로그인 화면이 열립니다. 그 Gmail 로 보내고, PC 의 답이 여기 말풍선으로 옵니다.';
  $('#clearSent').textContent = gOn() ? '대화 기록 비우기 (이 기기 화면에서만)' : '보낸 기록 모두 지우기 (이 기기에서만)';
  $('#setMail').value = cfg.mail || ''; $('#setFolders').value = (cfg.folders || []).join(', '); $('#setPrefix').value = cfg.prefix || '';
  $('#dlg').showModal();
}
$('#setBtn').onclick = openSettings;
$('#dlg').addEventListener('close', () => {
  if ($('#dlg').returnValue !== 'ok') return;
  cfg = { mail: $('#setMail').value.trim(), folders: $('#setFolders').value.split(',').map(s => s.trim().replace(/^@/, '')).filter(Boolean), prefix: $('#setPrefix').value.trim(), key: $('#setKey').value.trim().replace(/[\s\[\]]/g, ''), gcid: $('#setGcid').value.trim(), viaApp: $('#setViaApp').checked, self: $('#setSelf').checked, cmd: $('#setCmd').value.trim() || '/issue' };
  store.set('cfg', cfg); applyCfg(); draw(); toast('저장했습니다');
  if (gOn() && cfg.mail) { if (gLive()) gPoll(); else gAuth(false); }   // 처음 넣었으면 바로 Google 로그인
});
const short = a => a.replace(/^(.{2}).*(@.*)$/, '$1…$2');
function applyCfg() {
  if (!(gOn() && room)) $('#who').textContent = !cfg.mail ? '설정에서 메일 주소를 넣어 주세요'
    : gOn() ? (gtok && gtok.email ? short(gtok.email) : 'Gmail') + (cfg.self ? ' · 나에게 보냄' : '') + ' · 실시간'
    : short(cfg.mail) + ' 로 보냅니다';
  $('#issuePrefix').textContent = cfg.prefix || '';
  $('#issueCmdShow').textContent = cfg.cmd || '/issue';
  $('#issueTab').hidden = !cfg.prefix;                   // 이슈 키 앞부분이 없으면 이슈 탭을 숨긴다
  if (!cfg.prefix && $('#issue').classList.contains('on')) setTab('say');
  if (!(cfg.folders || []).includes(folder)) folder = '';
  drawFolders();
}

/* ---- Gmail 로 주고받기 ----
   서버 없이 Google 로그인 화면을 거쳐 돌아올 때 주소 끝(#access_token=…)으로 1시간짜리 토큰을 받는다(이 기기에만).
   보내기는 Gmail API 로, 받기는 PC 메일 주소와 오간 메일을 몇 초마다 읽어 PC 대화 앱(chat.py)과 같은 규칙으로 말풍선을 만든다. */
const GSCOPE = 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send';
const GAPI = 'https://gmail.googleapis.com/gmail/v1/users/me/';
const HOME = location.origin + location.pathname.replace(/index\.html$/, '');   // 구글에 등록한 리디렉션 주소와 같아야 한다
let gtok = store.get('gtok', null);            // { t, exp, email }
let gmsgs = store.get('gm', {});               // Gmail id → 대화 메시지(지시 메일이 아니면 { skip })
let gout = store.get('gout', []);              // 아직 못 보낸 것 — 연결되면 보낸다
let gloc = store.get('gloc', []);              // 메일 앱으로 보낸 새 지시 — Gmail 에 없어서 이 기기에 기억해 둔다 { at, subj, text, mode }
let gstate = '', gBusy = false, gTimer = 0, gHashErr = false;
const gOn = () => !!cfg.gcid;
const gLive = () => !!(gtok && gtok.t && gtok.exp > Date.now() + 30000);

function gAuth(silent) {
  if (!cfg.gcid) return;
  const st = Math.random().toString(36).slice(2);
  store.set('gst', st); store.set('glast', Date.now());
  const p = new URLSearchParams({ client_id: cfg.gcid, redirect_uri: HOME, response_type: 'token', scope: GSCOPE, include_granted_scopes: 'true', state: st });
  if (silent) p.set('prompt', 'none');                    // 이미 허락했으면 화면 없이 바로 돌아온다
  if (gtok && gtok.email) p.set('login_hint', gtok.email);
  location.href = 'https://accounts.google.com/o/oauth2/v2/auth?' + p;
}
function gTakeHash() {                                     // 로그인에서 돌아왔으면 토큰을 받아 두고 주소를 깨끗이
  if (!/(^#|&)(access_token|error)=/.test(location.hash)) return;
  const h = new URLSearchParams(location.hash.slice(1));
  history.replaceState(null, '', location.pathname + location.search);
  if (h.get('state') !== store.get('gst', '')) return;
  store.set('gst', '');
  if (h.get('access_token')) {
    gtok = { t: h.get('access_token'), exp: Date.now() + (parseInt(h.get('expires_in'), 10) || 3600) * 1000, email: (gtok && gtok.email) || '' };
    store.set('gtok', gtok);
  } else { gstate = 'need'; gHashErr = true; }           // 조용한 재연결이 안 됐다 — 단추로 다시 로그인
}
async function gFetch(path, opt) {
  const o = Object.assign({}, opt);
  o.headers = Object.assign({ Authorization: 'Bearer ' + gtok.t }, o.headers);
  const r = await fetch(GAPI + path, o);
  if (r.status === 401) { gtok.exp = 0; store.set('gtok', gtok); throw new Error('auth'); }
  if (!r.ok) throw new Error('Gmail ' + r.status);
  return r.json();
}

/* 메일 해석 — tools/dispatch-chat/chat.py 의 parse_message 와 같은 규칙 */
const KEY_RE = /\s*\[k:[^\]\s]{1,64}\]\s*$/, THREAD_RE = /\[T(\d{1,6})\]/, RE_RE = /^\s*(re|fw|fwd|회신|답장)\s*[:：]\s*/i;
const SIG_RE = /^\s*(--\s*$|보낸 사람:|보낸사람:|From:|-----Original Message-----|(나의 |내 )?iPhone에서 보냄|Sent from my |Get Outlook for |\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\..*작성:\s*$|On .+ wrote:\s*$)/m;
const ASK_SPLIT = '─'.repeat(16);
const bin = s => Uint8Array.from(s, c => c.charCodeAt(0));
const b64u = s => bin(atob(s.replace(/-/g, '+').replace(/_/g, '/')));
function txt(bytes, cs) { try { return new TextDecoder(cs || 'utf-8').decode(bytes); } catch (e) { return new TextDecoder().decode(bytes); } }
function mimeWords(s) {                                    // =?utf-8?b?…?= · =?utf-8?q?…?= 풀기
  return String(s || '').replace(/\?=\s+=\?/g, '?==?').replace(/=\?([^?]+)\?([bq])\?([^?]*)\?=/gi, (all, cs, enc, x) => {
    try {
      return txt(enc.toUpperCase() === 'B' ? bin(atob(x))
        : bin(x.replace(/_/g, ' ').replace(/=([0-9A-F]{2})/gi, (m, h) => String.fromCharCode(parseInt(h, 16)))), cs);
    } catch (e) { return all; }
  });
}
function gPlain(payload) {
  const parts = [], walk = p => { parts.push(p); (p.parts || []).forEach(walk); };
  walk(payload);
  const has = t => parts.find(p => p.mimeType === t && p.body && p.body.data && !/attachment/i.test(hval(p, 'content-disposition')));
  const p = has('text/plain') || has('text/html');
  if (!p) return '';
  const cs = (hval(p, 'content-type').match(/charset="?([^";\s]+)/i) || [])[1];
  const t = txt(b64u(p.body.data), cs);
  return p.mimeType === 'text/html' ? t.replace(/<[^>]+>/g, ' ') : t;
}
function hval(p, name) { const h = (p.headers || []).find(x => x.name.toLowerCase() === name); return h ? h.value : ''; }
function gParse(g) {
  const H = {}, AR = [];
  for (const h of g.payload.headers || []) {
    const k = h.name.toLowerCase();
    if (k === 'authentication-results') AR.push(String(h.value || '')); else H[k] = h.value;
  }
  const ts = +g.internalDate || Date.now();
  const subject = mimeWords(H.subject).replace(/\s+/g, ' ').trim();
  let clean = subject;
  for (let i = 0; i < 5; i++) { const n = clean.replace(RE_RE, ''); if (n === clean) break; clean = n; }
  clean = clean.trim().replace(KEY_RE, '');
  const tag = [TAG.write, TAG.read].find(t => clean === t || (clean.startsWith(t) && /\s/.test(clean[t.length])));   // 긴 태그 먼저
  if (!tag) return { skip: 1, ts };
  const body = gPlain(g.payload).replace(/\r/g, '').replace(/^[ \t]*\[k:[^\]\s]{1,64}\][ \t]*$/gm, '');   // 본문 끝 암호 단어 줄은 안 보인다
  let photos = 0;
  (function walk(p) { if (/^image\//.test(p.mimeType || '') && p.filename) photos++; (p.parts || []).forEach(walk); })(g.payload);
  const tm = clean.match(THREAD_RE), th = String(H['x-dispatch-thread'] || '').trim();
  const m = { id: (H['message-id'] || '').trim(), ts, mode: tag === TAG.write ? 'write' : 'read',
    thread: parseInt(/^\d+$/.test(th) ? th : (tm ? tm[1] : '0'), 10) || null,
    rest: clean.slice(tag.length).replace(THREAD_RE, '').trim(), bot: H['x-dispatch'] === 'bot' && gAuthOk(AR, H.from), photos,
    refs: ((H['in-reply-to'] || '') + ' ' + (H.references || '')).match(/<[^<>]+>/g) || [] };
  if (m.bot) {
    m.kind = H['x-dispatch-kind'] || 'reply'; m.status = H['x-dispatch-status'] || '';
    m.ack = m.kind === 'ack';                          // PC 가 받았다는 신호 — 말풍선으로는 안 보이고 내 말의 '1' 을 지운다
    let b = body.includes(ASK_SPLIT) ? body.slice(body.indexOf(ASK_SPLIT) + ASK_SPLIT.length) : body;   // 맨 위 ☐ 선택지 줄은 따로 받는다
    const i = b.lastIndexOf('\n--\n');
    m.text = (i >= 0 ? b.slice(0, i) : b).trim();
    m.ask = null;
    if (H['x-dispatch-ask']) try { m.ask = JSON.parse(txt(bin(atob(mimeWords(H['x-dispatch-ask']).replace(/\s+/g, ''))))); } catch (e) {}
  } else {
    const cut = body.search(SIG_RE);
    const said = (cut >= 0 ? body.slice(0, cut) : body).split('\n').filter(l => !l.trimStart().startsWith('>')).join('\n').trim();
    // 첫 지시는 제목+본문이 지시문이고, 이어지는 말은 본문이 곧 말이다(비면 제목)
    m.text = (/^re:/i.test(subject) || tm) && said ? said : [m.rest, said].filter(Boolean).join('\n').trim();
  }
  return m;
}
// PC 회신(X-Dispatch: bot)이 진짜인가 — X-Dispatch 머리글은 누구나 달 수 있다(2026-10-19 보안 점검: From 을 회사 주소로 꾸민
// 메일로 가짜 질문을 띄워 진짜 PC 대화에 답을 보내게 할 수 있었다). 밖에서 온 메일엔 Gmail(mx.google.com)이 인증 결과를 꼭 붙이니
// 그것이 있으면 DMARC 통과나 From 도메인과 맞는 DKIM·SPF 통과만 믿는다. 인증 결과가 아예 없으면 PC 가 IMAP 으로 내 메일함에 직접
// 넣은 것(메일함 주인만 넣을 수 있다)이라 그대로 둔다.
function gAuthOk(ar, from) {
  const mine = ar.filter(v => /^\s*mx\.google\.com\s*;/i.test(v));
  if (!ar.length) return true;
  if (!mine.length) return false;
  const v = mine[0], dom = (String(from || '').match(/@([^>\s]+)/) || [])[1] || '';
  if (/\bdmarc=pass\b/i.test(v)) return true;
  const same = d => !!dom && !!d && (d.toLowerCase() === dom.toLowerCase() || dom.toLowerCase().endsWith('.' + d.toLowerCase()));
  const dk = (v.match(/\bdkim=pass\b[^;]*?header\.(?:i|d)=@?([^\s;]+)/i) || [])[1] || '';
  const sp = (v.match(/\bspf=pass\b[^;]*?smtp\.mailfrom=(?:[^@\s;]*@)?([^\s;]+)/i) || [])[1] || '';
  return same(dk) || same(sp);
}
function gList() {                                         // 화면에 보일 메시지(시간순). 번호 없는 첫 지시는 그 지시에 답한 봇 메일로 번호를 찾는다
  const since = store.get('gsince', 0);
  const list = Object.values(gmsgs).filter(m => m && !m.skip && m.ts > since);
  // 메일 앱으로 보낸 지시: 같은 제목으로 온 PC 접수 신호·답(봇 메일)을 이 지시에 대한 것으로 이어 준다
  const norm = t => String(t || '').replace(/\s+/g, ' ').trim();
  for (const x of gloc) {
    if (x.at <= since) continue;
    const tag = x.subj.startsWith(TAG.write + ' ') ? TAG.write : TAG.read, rest = norm(x.subj.slice(tag.length));
    const loc = { id: 'loc:' + x.at, ts: x.at, mode: x.mode, rest, text: x.text, bot: false, local: true, thread: null, refs: [] };
    for (const m of list) if (m.bot && m.ts >= x.at - 60000 && norm(m.rest) === rest) {
      if (!m.refs.includes(loc.id)) m.refs = m.refs.concat(loc.id);
      if (m.ack && !loc.real) loc.real = m.refs.find(r => !r.startsWith('loc:'));    // PC 가 받은 원래 메일 — 멈춤이 가리킬 곳
    }
    list.push(loc);
  }
  list.sort((a, b) => a.ts - b.ts);
  const byId = {}; for (const m of list) if (m.id) byId[m.id] = m;
  for (const m of list) if (m.thread) for (const r of m.refs) { const o = byId[r]; if (o && !o.thread) o.thread = m.thread; }
  for (const m of list) if (m.ack) for (const r of m.refs) if (byId[r]) byId[r].got = true;
  return list.filter(m => !m.ack);
}
function gWaiting(list) {                                  // 내가 보내고 아직 답이 없는 대화(30분 안) — 'PC 가 일하는 중'
  const last = {};
  for (const m of list) last[m.thread ? 'T' + m.thread : 'm:' + m.id] = m;
  return Object.values(last).filter(m => !m.bot && Date.now() - m.ts < 30 * 60000);
}
function gReplyTo(t) {                                     // 이어 말할 때 그 대화의 마지막 봇 메일에 답장으로 단다
  if (!(t > 0)) return '';
  const b = gList().filter(m => m.bot && m.thread === t && m.id);
  return b.length ? b[b.length - 1].id : '';
}
async function gGet(id) {
  try { gmsgs[id] = gParse(await gFetch('messages/' + id + '?format=full')); }
  catch (e) { if (e.message === 'auth') throw e; }
}
function gSave() {                                         // 기기 저장소가 넘치지 않게 최근 400통만
  const ids = Object.keys(gmsgs).sort((a, b) => (gmsgs[b] || {}).ts - (gmsgs[a] || {}).ts);
  for (const id of ids.slice(400)) delete gmsgs[id];
  store.set('gm', gmsgs);
}
const enc8 = s => new TextEncoder().encode(s);
function b64(bytes) { let s = ''; for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192)); return btoa(s); }
function mimeHead(s) {                                     // 제목 → =?UTF-8?B?…?= 조각들(글자를 가르지 않게 45바이트씩)
  const out = []; let cur = '';
  for (const ch of s) { if (cur && enc8(cur + ch).length > 45) { out.push(cur); cur = ''; } cur += ch; }
  if (cur) out.push(cur);
  return out.map(x => '=?UTF-8?B?' + b64(enc8(x)) + '?=').join('\r\n ') || '""';
}
function rfcDate(d) {                                     // 'Thu, 08 Oct 2026 11:10:00 +0900' (이 기기 시간대)
  const off = -d.getTimezoneOffset(), a = Math.abs(off);
  return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()] + ', ' + pad(d.getDate()) + ' ' +
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()] + ' ' + d.getFullYear() + ' ' +
    pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) + ' ' + (off < 0 ? '-' : '+') + pad(Math.floor(a / 60)) + pad(a % 60);
}
// 'PC 가 내 Gmail 을 직접 읽음'이면 나에게 보낸다 — 회사 메일·스팸 장비를 거치지 않는다(PC 게이트웨이의 Gmail 직접 읽기)
function gTo() { return cfg.self && gtok && gtok.email ? gtok.email : cfg.mail; }
async function gSend(o) {
  // Date 를 빼면 Gmail 서버가 자기 시간대로 채운다 — 받는 쪽 스팸 검사가 의심하기 쉽다. 이 기기 시각으로 넣는다
  const head = ['To: ' + gTo(), 'Date: ' + rfcDate(new Date()), 'Subject: ' + mimeHead(o.subject), 'MIME-Version: 1.0'];
  if (o.reply) head.push('In-Reply-To: ' + o.reply, 'References: ' + o.reply);
  const wrap = x => (x.match(/.{1,76}/g) || []).join('\r\n');
  const text = ['Content-Type: text/plain; charset=UTF-8', 'Content-Transfer-Encoding: base64', '', wrap(b64(enc8(o.body || '')))];
  let raw;
  if (!(o.files || []).length) raw = head.concat(text).join('\r\n') + '\r\n';
  else {                                                 // 사진 — PC 게이트웨이가 저장해 Claude 가 Read 로 연다
    const bd = 'dispatch-' + Math.random().toString(36).slice(2);
    const parts = ['--' + bd].concat(text);
    o.files.forEach((f, i) => parts.push('--' + bd, 'Content-Type: image/jpeg; name="photo' + (i + 1) + '.jpg"',
      'Content-Disposition: attachment; filename="photo' + (i + 1) + '.jpg"', 'Content-Transfer-Encoding: base64', '', wrap(f.b64)));
    parts.push('--' + bd + '--');
    raw = head.concat('Content-Type: multipart/mixed; boundary="' + bd + '"', '').join('\r\n') + '\r\n' + parts.join('\r\n') + '\r\n';
  }
  const r = await gFetch('messages/send', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw: b64(enc8(raw)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') }) });
  if (r.id) await gGet(r.id);                              // 보낸 편지함에서 바로 가져와 말풍선으로
}
async function gPoll() {
  clearTimeout(gTimer);
  if (!gOn() || !cfg.mail || document.hidden) return;
  if (!gLive()) {
    // 토큰이 끊겼으면 조용히 다시 받아 온다(입력 중이면 글이 날아가지 않게 두고 띠만 띄운다)
    if (gtok && !gHashErr && !$('#sayText').value.trim() && !$('#ansText').value.trim() && Date.now() - store.get('glast', 0) > 120000) { gAuth(true); return; }
    gstate = 'need'; drawBanner(); return;
  }
  if (gBusy) return;
  gBusy = true;
  let changed = false;
  try {
    if (!gtok.email) { gtok.email = (await gFetch('profile')).emailAddress || ''; store.set('gtok', gtok); applyCfg(); }
    while (gout.length) {                                  // 못 보낸 것부터
      await gSend(gout[0]); gout.shift(); store.set('gout', gout); changed = true; toast('보냈습니다');
    }
    const q = '{from:' + cfg.mail + ' to:' + cfg.mail + '} newer_than:30d';
    const r = await gFetch('messages?maxResults=80&includeSpamTrash=true&q=' + encodeURIComponent(q));
    const mine = cfg.self ? await gFetch('messages?maxResults=80&q=' + encodeURIComponent('from:me to:me newer_than:30d')) : {};   // 나에게 보낸 지시
    const ids = [...new Set((r.messages || []).concat(mine.messages || []).map(x => x.id))].filter(id => !(id in gmsgs));
    for (let i = 0; i < ids.length; i += 6) await Promise.all(ids.slice(i, i + 6).map(gGet));
    if (ids.length) changed = true;
    gstate = 'ok';
  } catch (e) {
    gstate = e.message === 'auth' ? 'need' : 'err';
  } finally {
    gBusy = false;
    if (changed) { gSave(); draw(); }
    drawBanner();
    if (gstate === 'need') setTimeout(gPoll, 0);         // 토큰이 막 끊겼으면 조용히 다시 받아 오기를 해 본다
    else gTimer = setTimeout(gPoll, gWaiting(gList()).length || gout.length ? 8000 : 30000);
  }
}
function drawBanner() {
  const bar = $('#gbar'), n = gout.length;
  const msg = !gOn() ? '' : gstate === 'need' ? 'Google 연결이 끊겼어요' + (n ? ' · 보낼 것 ' + n + '건 대기' : '')
    : gstate === 'err' ? 'Gmail 을 못 읽었어요 — 잠시 뒤 다시 해 봅니다' : '';
  bar.classList.toggle('on', !!msg); $('#gbarText').textContent = msg;
  $('#gbarBtn').style.display = gstate === 'need' ? '' : 'none';
}
$('#gbarBtn').onclick = () => gAuth(false);
$('#gOff').onclick = () => {
  if (!confirm('이 기기에서 Gmail 연결을 끊을까요? (클라이언트 ID 도 지웁니다)')) return;
  gtok = null; gmsgs = {}; gout = []; cfg.gcid = '';
  for (const k of ['gtok', 'gm', 'gout']) store.set(k, k === 'gtok' ? null : k === 'gm' ? {} : []);
  store.set('cfg', cfg); $('#dlg').close(); applyCfg(); draw(); drawBanner(); toast('끊었습니다');
};
/* PC 답을 보기 좋게 — Claude 답은 마크다운(표·목록·**굵게**·`코드`·```블록```)이다.
   글자는 먼저 전부 이스케이프하고 정해진 태그만 만든다(메일 내용을 HTML 로 그대로 넣지 않는다). */
const esc = t => String(t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inl = t => esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
function md(src) {
  const L = String(src || '').replace(/\r/g, '').split('\n'), out = [];
  const isRow = x => /^\s*\|.*\|\s*$/.test(x);
  for (let i = 0; i < L.length;) {
    const l = L[i];
    if (/^\s*```/.test(l)) {                            // 코드 블록
      const buf = []; i++;
      while (i < L.length && !/^\s*```/.test(L[i])) buf.push(L[i++]);
      i++; out.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>'); continue;
    }
    if (isRow(l) && i + 1 < L.length && /^\s*\|?\s*:?-{2,}/.test(L[i + 1])) {   // 표
      const cells = x => x.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => inl(c.trim()));
      const head = cells(l), rows = []; i += 2;
      while (i < L.length && isRow(L[i])) rows.push(cells(L[i++]));
      out.push('<div class="tbl"><table><tr>' + head.map(c => '<th>' + c + '</th>').join('') + '</tr>' +
        rows.map(r => '<tr>' + r.map(c => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</table></div>');
      continue;
    }
    const h = l.match(/^#{1,4}\s+(.*)$/);
    if (h) { out.push('<div class="h">' + inl(h[1]) + '</div>'); i++; continue; }
    const li = l.match(/^(\s*)([-*•]|\d+[.)])\s+(.*)$/);
    if (li) {
      out.push('<div class="li" style="padding-left:' + Math.min(li[1].length, 8) * 7 + 'px"><span class="bul">' +
        (/\d/.test(li[2]) ? esc(li[2]) : '•') + '</span><span>' + inl(li[3]) + '</span></div>');
      i++; continue;
    }
    out.push(l.trim() ? '<div>' + inl(l) + '</div>' : '<div class="sp"></div>'); i++;
  }
  return out.join('');
}
const opened = new Set();                              // '더 보기' 로 펼친 답(다시 그려도 펼친 채로)
function mdBubble(b, text, id) {                       // 봇 말풍선 — 길면 접고 '더 보기'
  b.classList.add('md');
  const body = el('div', 'mdbody'); body.innerHTML = md(text); b.append(body);
  if (text.length > 700 || text.split('\n').length > 16) {
    const f0 = !opened.has(id);
    body.classList.toggle('fold', f0);
    const more = el('button', 'more', f0 ? '더 보기 ▼' : '접기 ▲');
    more.onclick = () => {
      const f = body.classList.toggle('fold'); more.textContent = f ? '더 보기 ▼' : '접기 ▲';
      if (f) opened.delete(id); else opened.add(id);
    };
    b.append(more);
  }
}

/* 대화방 — 카톡처럼 대화 번호([T12])별 방 목록과 방 안 화면. 번호가 아직 없는 첫 지시는 'm:<Message-ID>' 방이고
   첫 답이 오면 번호 방으로 옮겨 간다. 보내는 중인 새 지시는 'o:<시각>' 방. */
let room = null;
let gseen = store.get('gseen', {});                    // 방마다 마지막으로 본 시각 — 안 읽은 답 표시
let gpin = store.get('gpin', {});                      // 고정한 방 → 고정한 시각(먼저 고정한 것이 위)
let query = '';                                        // 목록 검색어
let ghide = store.get('ghide', {});                    // 지운 방 → 지운 시각. 그 뒤에 온 말만 다시 보인다(Gmail·PC 는 그대로)
const roomKey = m => m.thread ? 'T' + m.thread : 'm:' + (m.id || m.ts);
function gRooms(list) {
  const rooms = {}, get = (k, no) => rooms[k] || (rooms[k] = { key: k, no: no || null, msgs: [], out: [] });
  for (const m of list) { const k = roomKey(m); if (m.ts > (ghide[k] || 0)) get(k, m.thread).msgs.push(m); }
  for (const o of gout) get(o.thread ? 'T' + o.thread : 'o:' + o.at, o.thread).out.push(o);
  const waiting = new Set(gWaiting(list).map(roomKey));
  const got = new Set(gWaiting(list).filter(m => m.got).map(roomKey));
  for (const r of Object.values(rooms)) {
    const first = r.msgs.find(m => !m.bot) || r.out[0], last = r.msgs[r.msgs.length - 1];
    r.title = (((first && (first.text || first.rest)) || '').split('\n')[0].replace(/^@\S+\s+/, '')
      .slice(0, 60)) || (r.no ? '대화 T' + r.no : '(제목 없음)');
    r.mode = r.msgs.some(m => m.mode === 'write') || r.out.some(o => o.mode === 'write') ? 'write' : 'read';
    r.ts = Math.max(last ? last.ts : 0, ...r.out.map(o => o.at));
    r.last = r.out.length ? r.out[r.out.length - 1].text : last ? (last.text || last.rest || '') : '';
    r.st = r.out.length ? '보내는 중' : got.has(r.key) ? '일하는 중' : waiting.has(r.key) ? '전송됨' : !last || !last.bot ? ''
      : last.kind === 'confirm' ? '실행 확인' : last.status === 'error' ? '오류' : last.ask ? '질문' : '완료';
    r.ask = last && last.bot && last.ask ? last : null;
    r.unread = !!(last && last.bot && last.ts > (gseen[r.key] || 0));
  }
  return Object.values(rooms).sort((a, b) => {
    const pa = gpin[a.key], pb = gpin[b.key];
    if (pa || pb) return !pa ? 1 : !pb ? -1 : pa - pb;
    return b.ts - a.ts;
  });
}
function gFollow(key, list) {                          // 방 번호가 바뀌었으면(첫 답이 와서 번호가 붙음 · 보내는 중이던 것이 실제 메일로) 따라간다
  if (key.startsWith('m:')) { const m = list.find(x => x.id === key.slice(2)); if (m && m.thread) return 'T' + m.thread; }
  if (key.startsWith('o:')) { const at = +key.slice(2), m = list.find(x => !x.bot && x.ts >= at - 120000); if (m) return roomKey(m); }
  return null;
}
function openRoom(key) {
  room = key; picks.clear(); stop = false; pickN = 4;
  try { history.pushState({ room: key }, ''); } catch (e) {}
  setTab('say'); $('#sayText').value = ''; draw();
}
function closeRoom() {
  if (history.state && history.state.room) history.back();       // 아이폰 쓸어 넘기기와 같은 길로
  else { room = null; draw(); }
}
addEventListener('popstate', e => { room = (e.state && e.state.room) || null; draw(); });
$('#backBtn').onclick = closeRoom;
let editing = false;
const picked = new Set();                              // 편집 중 고른 방 키
$('#delBtn').onclick = () => {
  if (!room) { editing = !editing; picked.clear(); draw(); return; }
  if (!confirm('이 대화를 이 기기 화면에서 지울까요?\n(Gmail·PC 의 메일은 그대로이고, 새 답이 오면 그 뒤부터 다시 보입니다)')) return;
  ghide[room] = Date.now(); store.set('ghide', ghide);
  closeRoom(); toast('지웠습니다');
};
$('#pinBtn').onclick = () => {
  if (!room) return;
  if (gpin[room]) delete gpin[room]; else gpin[room] = Date.now();
  store.set('gpin', gpin); toast(gpin[room] ? '목록 맨 위에 고정했습니다' : '고정을 풀었습니다'); draw();
};
$('#q').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); draw(); });
$('#selAll').onclick = () => {
  const keys = [...document.querySelectorAll('#log .room')].map(n => n.dataset.key);
  if (keys.every(k => picked.has(k))) picked.clear(); else keys.forEach(k => picked.add(k));
  draw();
};
$('#selDel').onclick = () => {
  if (!picked.size || !confirm('고른 대화 ' + picked.size + '개를 이 기기 화면에서 지울까요?\n(Gmail·PC 의 메일은 그대로이고, 새 답이 오면 그 뒤부터 다시 보입니다)')) return;
  const now = Date.now();
  for (const k of picked) ghide[k] = now;
  store.set('ghide', ghide);
  toast(picked.size + '개 지웠습니다');
  editing = false; picked.clear(); draw();
};
const when = ts => {
  const d = new Date(ts), n = new Date();
  return d.toDateString() === n.toDateString() ? pad(d.getHours()) + ':' + pad(d.getMinutes()) : (d.getMonth() + 1) + '/' + d.getDate();
};
function roomBar(r) {                                  // 머리줄 · 입력부를 지금 화면(목록/방)에 맞춘다
  const inRoom = !!r, tab = name => document.querySelector('.tabs [data-pane=' + name + ']');
  if (inRoom) editing = false;
  $('#backBtn').style.display = inRoom ? '' : 'none';
  $('#delBtn').textContent = inRoom ? '지우기' : editing ? '완료' : '편집';
  $('#pinBtn').style.display = inRoom ? '' : 'none';
  if (inRoom) $('#pinBtn').textContent = gpin[r.key] ? '고정 해제' : '고정';
  $('#delBtn').style.display = inRoom ? '' : 'none';             // 목록에선 방이 있을 때 drawRooms 가 켠다
  $('.composer').style.display = editing ? 'none' : '';
  $('#editBar').classList.toggle('on', editing);
  $('#logo').style.display = inRoom ? 'none' : '';
  $('#ttl').textContent = inRoom ? r.title : '디스패치';
  if (inRoom) $('#who').textContent = (r.no ? 'T' + r.no + ' · ' : '') + (r.mode === 'write' ? '수정 허용' : '읽기') + (r.st ? ' · ' + r.st : '');
  else applyCfg();
  $('#sayRow').style.display = $('#ansRow').style.display = 'none';     // 대화 번호는 방이 정한다
  $('#modeChips').style.display = inRoom ? 'none' : '';              // 이어 말하면 권한·폴더는 처음 그대로
  tab('answer').style.display = inRoom && r.ask ? '' : 'none';
  tab('issue').style.display = inRoom ? 'none' : '';
  tab('say').textContent = inRoom ? '말하기' : '새 지시';
  $('.tabs').style.display = inRoom && !r.ask ? 'none' : '';      // 방 안에 질문이 없으면 탭이 하나뿐 — 줄을 숨긴다
  $('#sayThread').value = inRoom && r.no ? r.no : '';
  if (inRoom && r.no) $('#ansThread').value = r.no;
  const wait = inRoom && !r.no;                        // 번호가 붙기 전엔 이어 말할 수 없다
  $('#clipBtn').style.display = wait ? 'none' : '';
  $('#sayText').disabled = wait;
  $('#sayText').placeholder = wait ? '첫 답이 오면 이어서 말할 수 있어요' : inRoom ? '이어서 말하기' : '새로 맡길 일 (첫 줄이 제목)';
  const on = document.querySelector('.tabs button.on');
  if (!on || on.style.display === 'none') setTab('say');
  refresh();
}
function roomStop(r) {                                 // PC 가 하던 일을 끊는다(워커가 2초 안에 멈추고 '멈췄습니다' 회신)
  const mine = r.msgs.filter(m => !m.bot && m.id && (!m.local || m.real)).map(m => m.local ? Object.assign({}, m, { id: m.real }) : m);
  if (!mine.length) { toast('PC 가 받은 뒤에 멈출 수 있어요'); return; }
  if (!mine.length || !confirm('PC 가 하던 일을 지금 멈출까요?')) return;
  openMail('Re: ' + TAG.read + (r.no ? ' [T' + r.no + ']' : '') + ' 멈춤', '멈춤',
    { kind: 'stop', text: '멈춤', mode: r.mode, thread: r.no || '', reply: mine[mine.length - 1].id });
}
const QUICK = ['계속해', '요약만 해줘', '자세히 설명해줘', '고마워'];   // 방 안 빠른 답 — 누르면 입력칸에 채운다(보내기는 직접)
function drawQuick(r) {
  const box = $('#quick'), on = !!(r && r.no && !r.out.length && r.st !== '일하는 중' && r.st !== '전송됨');
  box.style.display = on ? '' : 'none';
  if (!on) return;
  box.replaceChildren(...QUICK.map(q => {
    const b = el('button', 'chip', q);
    b.onclick = () => { const t = $('#sayText'); t.value = q; grow(t); refresh(); t.focus(); };
    return b;
  }));
}
function drawGmail(box) {
  const list = gList(), rooms = gRooms(list);
  if (room && !rooms.some(r => r.key === room)) {
    room = gFollow(room, list);
    try { history.replaceState(room ? { room } : null, ''); } catch (e) {}
  }
  const r = room && rooms.find(x => x.key === room);
  roomBar(r); drawQuick(r);
  if (r) { $('#searchBar').classList.remove('on'); drawRoom(box, r); } else drawRooms(box, rooms);
}
function drawRooms(box, rooms) {
  $('#searchBar').classList.toggle('on', rooms.length > 4 || !!query);   // 방이 몇 개 넘으면 검색칸
  if (query) {
    const hit = t => (t || '').toLowerCase().includes(query);
    rooms = rooms.filter(r => hit(r.title) || hit(r.last) || r.msgs.some(m => hit(m.text) || hit(m.rest)) || hit(r.no ? 'T' + r.no : ''));
    if (!rooms.length) { box.append(el('div', 'empty', '「' + $('#q').value.trim() + '」 이(가) 들어간 대화가 없습니다')); return; }
  }
  if (!rooms.length) {
    const e = el('div', 'empty');
    e.innerHTML = '<b>Gmail 로 주고받습니다</b><br><br>아래에 할 일을 적고 보내면 PC 가 받아 일하고, 대화마다 <b>방</b>이 생겨 답이 말풍선으로 옵니다.<br><br>선택지가 오면 방 안 말풍선의 단추를 누르고 보내기만 누르세요.';
    box.append(e); return;
  }
  for (const r of rooms) {
    const row = el('button', 'room'), body = el('div', 'rbody'), top = el('div', 'rtop'), bot = el('div', 'rbot');
    top.append(el('span', 'rtitle', r.title));
    if (gpin[r.key]) top.append(el('span', 'pin', '📌'));
    top.append(el('span', 'rtime', when(r.ts)));
    const firstLine = (r.last || '').split('\n').map(x => x.replace(/^\s*(#+|[-*•]|\|)\s*/, '').replace(/\*\*|`/g, '').trim()).find(Boolean) || '';
    bot.append(el('span', 'rlast', firstLine));          // 미리보기는 마크다운 기호를 뗀 첫 줄
    if (r.st) bot.append(el('span', 'rst' + ({ '질문': ' ask', '실행 확인': ' ask', '오류': ' err', '일하는 중': ' busy', '보내는 중': ' busy', '전송됨': '' }[r.st] || ''), r.st));
    if (r.unread) bot.append(el('span', 'dot'));
    body.append(top, bot);
    row.dataset.key = r.key;
    if (editing) {
      row.classList.toggle('sel', picked.has(r.key));
      row.append(el('span', 'chk', picked.has(r.key) ? '✓' : ''));
    }
    row.append(el('span', 'tagchip' + (r.mode === 'write' ? ' w' : ''), r.no ? 'T' + r.no : '새'), body);
    row.onclick = () => {
      if (!editing) return openRoom(r.key);
      picked.has(r.key) ? picked.delete(r.key) : picked.add(r.key); draw();
    };
    box.append(row);
  }
  $('#delBtn').style.display = '';
  if (editing) {
    $('#selDel').disabled = !picked.size;
    $('#selDel').textContent = picked.size ? picked.size + '개 지우기' : '지우기';
    $('#selAll').textContent = rooms.every(r => picked.has(r.key)) ? '모두 해제' : '모두 선택';
  }
  box.scrollTop = 0;
}
function drawRoom(box, r) {
  const ansT = parseInt($('#ansThread').value, 10);
  let lastDay = '';
  const add = (ts, node) => {
    const d = new Date(ts), day = (d.getMonth() + 1) + '월 ' + d.getDate() + '일';
    if (day !== lastDay) { box.append(el('div', 'day', day)); lastDay = day; }
    box.append(node);
  };
  const hm = ts => { const d = new Date(ts); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
  for (const m of r.msgs) {
    const w = el('div', 'msg' + (m.bot ? ' bot' : '')), b = el('div', 'bubble' + (m.bot ? ' bot' : ''));
    if (m.bot) mdBubble(b, m.text || '(빈 회신)', m.id || m.ts);
    else b.textContent = (m.text || m.rest || '(빈 메일)') + (m.photos ? '\n📷 사진 ' + m.photos + '장' : '');
    const meta = el('div', 'meta');
    const st = !m.bot ? '' : m.kind === 'confirm' ? '실행 확인' : m.status === 'error' ? '오류' : m.ask ? '질문' : '';
    if (st) meta.append(el('span', 'tagchip' + (m.mode === 'write' ? ' w' : ''), st));
    if (r.st === '전송됨' && m === r.msgs[r.msgs.length - 1]) meta.append(el('span', 'unread', '1'));   // 카톡 읽음 표시 — PC 가 받으면 사라진다
    meta.append(el('span', '', hm(m.ts)));
    if (r.ask === m && Array.isArray(m.ask.options)) {   // 모양이 틀린 질문은 안 그린다                  // 아직 답하지 않은 질문 — 단추로 고른다
      const a = { question: String(m.ask.question || ''), multi: !!m.ask.multi, options: m.ask.options.slice(0, 9).map(String) }, ask = el('div', 'ask');
      ask.append(el('div', 'q', '❓ ' + a.question + (a.multi ? ' (여러 개)' : '')));
      a.options.forEach((o, i) => {
        const n = i + 1, c = el('button', 'opt' + (ansT === m.thread && picks.has(n) ? ' on' : ''), n + '. ' + o);
        c.onclick = () => {
          if (parseInt($('#ansThread').value, 10) !== m.thread) { picks.clear(); $('#ansThread').value = m.thread; }
          if (a.multi && picks.has(n)) picks.delete(n); else { if (!a.multi) picks.clear(); picks.add(n); }
          stop = false; $('#stopBtn').classList.remove('on'); pickN = Math.min(9, Math.max(a.options.length, 1));
          setTab('answer'); drawPicks(); refresh(); draw();
        };
        ask.append(c);
      });
      b.append(ask);
    }
    w.append(b, meta); add(m.ts, w);
  }
  for (const o of r.out) {                             // 아직 못 보낸 것
    const w = el('div', 'msg');
    w.append(el('div', 'bubble wait', o.text + ((o.files || []).length ? '\n📷 사진 ' + o.files.length + '장' : '')), el('div', 'meta', '보내는 중…'));
    add(o.at, w);
  }
  if (r.st === '일하는 중' || r.st === '전송됨') {
    const w = el('div', 'msg bot'), row = el('div', 'typingrow');
    if (r.st === '일하는 중') row.append(el('div', 'bubble bot typing', '🐱 PC 가 일하는 중…'));
    const stopB = el('button', 'stopbtn', '■ 멈춤');
    stopB.onclick = () => roomStop(r);
    row.append(stopB); w.append(row); box.append(w);
  }
  if (r.st === '전송됨' && Date.now() - r.ts > 3 * 60000)   // 보통 1분 안에 받는다 — 오래 못 받으면 메일 스팸 격리가 흔한 원인
    box.append(el('div', 'tail warn', r.msgs.length && r.msgs[r.msgs.length - 1].local
      ? 'PC 가 아직 못 받았어요 — 메일 앱에서 「보내기」를 눌렀는지 확인해 보세요'
      : 'PC 가 아직 못 받았어요 — 메일 스팸함(격리함)에 걸렸는지 확인해 보세요'));
  gseen[r.key] = r.ts; store.set('gseen', gseen);
  box.scrollTop = box.scrollHeight;
}
gTakeHash();
document.addEventListener('visibilitychange', () => { if (!document.hidden) gPoll(); });

const tab0 = store.get('tab', 'say');
applyCfg(); drawPicks(); draw(); refresh(); setTab(['say', 'answer'].includes(tab0) || (tab0 === 'issue' && cfg.prefix) ? tab0 : 'say');
if (gOn()) gPoll();
if (!cfg.mail) setTimeout(openSettings, 300);

$('#clearSent').addEventListener('click', () => {
  if (gOn()) {                                           // Gmail 은 그대로 — 이 기기 화면에서 지금까지의 대화만 안 보이게
    if (!confirm('지금까지의 대화를 이 기기 화면에서 비울까요? (Gmail·PC 는 그대로)')) return;
    store.set('gsince', Date.now()); draw(); toast('비웠습니다'); return;
  }
  if (!sent.length) { toast('지울 기록이 없습니다'); return; }
  if (!confirm('이 기기의 보낸 기록 ' + sent.length + '건을 모두 지울까요? (PC·메일은 그대로)')) return;
  sent = []; store.set('sent', sent); draw(); toast('지웠습니다');
});
