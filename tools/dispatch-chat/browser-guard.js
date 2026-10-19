#!/usr/bin/env node
'use strict';
/* 브라우저 안전장치 — claude -p 의 PreToolUse 훅(--settings 로 붙인다. 디스패치 대화 chat_runner.py).
 * matcher 는 mcp__browser__.* 와 Bash 두 곳.
 *
 * 2026-10-19 보안 점검으로 다시 짰다 — 전엔 '위험 낱말이 든 클릭만' 막아서 확인 창 accept·삭제 링크 이동·파일 올리기·
 * 난독화 스크립트·'휴지통 아이콘' 같은 흐린 설명이 다 통과했다. 이제는 **허용 목록**: 읽기·이동·검색어 입력처럼 안전한 동작만
 * 그냥 두고, 나머지 브라우저 동작은 사람 확인을 받는다.
 *   - 그냥 두는 것: snapshot·screenshot·hover·wait_for·console·network·find·tabs·resize·navigate_back·close,
 *     제출 없는 입력(type: submit 없고 줄바꿈 없음), 위험 낱말 없는 http(s) navigate, 화살표·Tab·Esc 같은 이동 키,
 *     확인 창 닫기(accept:false), 링크·탭·메뉴 클릭과 검색·다음·더보기 같은 단추 클릭(위험 낱말이 하나라도 있으면 막는다).
 *   - 클릭은 모델이 적은 element 설명만 믿지 않는다 — 세션 기록의 마지막 페이지 스냅숏에서 그 ref 의 실제 역할·이름을 찾아
 *     함께 본다. 스냅숏에서 못 찾으면 확인을 받는다.
 *   - 판정 전 정규화: NFKC, 공백·제로폭 문자 제거, 소문자('보 내 기', 'deleteBtn' 도 걸린다).
 *   - Bash: 전용 브라우저를 훅 밖에서 직접 조종하는 명령(9333·CDP·remote-debugging·playwright 로 띄우기)을 막는다.
 *
 * 허락: 마지막 사람 글이 정확히 '사용자 답(번호 선택): ☑ <n>. 진행해도 됩니다' 한 줄(덧붙인 말·여러 선택이면 무효)이거나,
 * 지시문 안에 '진행해도 됩니다' 한 줄만 따로 적은 사전 허락일 때. 허락 하나 = 동작 하나(같은 동작 다시 하기는 1번 더).
 * 대화 요약(isCompactSummary)·<command- 글·도구 결과·웹 페이지 글은 사람 글로 치지 않는다.
 * 어느 허락을 어느 동작에 썼는지 임시 폴더 dnc-guard\<세션>.json 에 적는다.
 * fail-closed: 입력이 깨졌거나 판정 중 오류가 나면 막는다.
 * Node 만 쓴다(브라우저 도구가 npx 라 Node 는 늘 있다 — python 없는 PC 의 대화 앱 exe 에서도 돈다). */
const fs = require('fs');
const os = require('os');
const path = require('path');

const PREFIX = '브라우저 안전장치';
const APPROVE = '진행해도 됩니다';
const OPTIONS = '["진행해도 됩니다", "하지 마세요"]';
const ANSWER_RE = /^사용자 답\(번호 선택\): ☑ \d+\. 진행해도 됩니다$/;

// 위험 낱말 — 정규화한 글자(공백 없음·소문자)에 들어 있으면 막는다. 낱말 경계를 보지 않는다(deletebtn 도 걸리게)
const RISKY = ['보내', '발송', '전송', '송신', '삭제', '지우', '제거', '휴지통', '비우', '결제', '구매', '구입', '주문하기', '주문확정',
  '송금', '이체', '출금', '제출', '승인', '탈퇴', '해지', '환불', '취소', '게시', '등록', '저장', '확인', '적용', '동의', '수락',
  '업로드', '첨부', '공유', '초대', '로그아웃', '영구', '초기화', '리셋', '변경', '수정', '추가', '생성', '실행', '발행', '배포',
  'send', 'submit', 'delete', 'remove', 'trash', 'erase', 'destroy', 'purge', 'pay', 'purchase', 'buy', 'checkout', 'placeorder',
  'transfer', 'withdraw', 'approve', 'accept', 'confirm', 'save', 'publish', 'upload', 'attach', 'share', 'invite', 'logout',
  'signout', 'reset', 'clear', 'empty', 'apply', 'agree', 'discard', 'archive', 'unsubscribe', 'cancel', 'deploy', 'execute'];
// 그냥 눌러도 되는 단추 이름(위험 낱말이 없을 때만)
const SAFE_BUTTON = ['검색', '조회', '찾기', '다음', '이전', '더보기', '펼치기', '접기', '닫기', '새로고침', '보기', '목록', '탭',
  'search', 'next', 'prev', 'previous', 'more', 'expand', 'collapse', 'refresh', 'view', 'show', 'close', 'menu'];
const SAFE_ROLES = ['link', 'tab', 'menuitem', 'treeitem'];
const NAV_ROLES = SAFE_ROLES;
const SAFE_TOOLS = ['browser_snapshot', 'browser_take_screenshot', 'browser_hover', 'browser_wait_for', 'browser_console_messages',
  'browser_network_requests', 'browser_network_request', 'browser_find', 'browser_tabs', 'browser_resize', 'browser_navigate_back',
  'browser_close', 'browser_install'];
const SAFE_KEYS = /^(arrow(up|down|left|right)|page(up|down)|home|end|tab|shift\+tab|escape|esc)$/i;
const URL_RISKY = ['delete', 'del', 'remove', 'rm', 'destroy', 'logout', 'logoff', 'signout', 'pay', 'payment', 'checkout',
  'purchase', 'order', 'transfer', 'withdraw', 'unsubscribe', 'approve', 'submit', 'send', 'cancel', 'reset', 'trash', 'drop'];
// Bash 로 전용 브라우저를 훅 밖에서 조종하는 길
const BASH_BROWSER = ['9333', 'connectovercdp', 'remote-debugging', 'chrome-devtools', 'devtools', '/json/version', '/json/list',
  'devtoolsactiveport', 'pw-profile', 'chrome.exe', 'msedge.exe'];
const BASH_PLAYWRIGHT = /playwright.*(connect|launch|chromium|codegen|open|persistentcontext|userdatadir|cr\b|screenshot)/;

const norm = s => String(s || '').normalize('NFKC').toLowerCase().replace(/[\s\u00ad\u180e\u200b-\u200f\u2028-\u202f\u205f-\u2064\ufeff]/g, '');
const hasAny = (s, words) => words.some(w => s.includes(w));

// ---------------------------------------------------------------- 세션 기록 읽기

function readLines(file) {
  try { return fs.readFileSync(file, 'utf8').split('\n'); } catch (_) { return []; }
}

function textOf(c) {
  if (typeof c === 'string') return c;
  if (Array.isArray(c)) return c.map(x => (x && typeof x.text === 'string' ? x.text : '')).join('\n');
  return '';
}

// 마지막 사람 글 {uuid, text} — 도구 결과·메타·대화 요약·명령 글은 건너뛴다
function lastHuman(lines) {
  let last = null;
  for (const line of lines) {
    if (!/"type"\s*:\s*"user"/.test(line)) continue;
    let d;
    try { d = JSON.parse(line); } catch (_) { continue; }
    if (d.type !== 'user' || d.isMeta || d.isCompactSummary || !d.message) continue;
    const c = d.message.content;
    if (Array.isArray(c) && c.some(x => x && x.type === 'tool_result')) continue;
    const text = textOf(c).trim();
    if (!text || /^<(command-|local-command|system-reminder)/.test(text)) continue;
    last = { uuid: d.uuid || text, text };
  }
  return last;
}

// 마지막 페이지 스냅숏(도구 결과 글) — {url, refs: {e4: {role, name}}}
function lastSnapshot(lines) {
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (!line.includes('tool_result') || !line.includes('[ref=')) continue;
    let d;
    try { d = JSON.parse(line); } catch (_) { continue; }
    const parts = (d.message && Array.isArray(d.message.content)) ? d.message.content : [];
    for (let k = parts.length - 1; k >= 0; k--) {
      const p = parts[k];
      if (!p || p.type !== 'tool_result') continue;
      const t = textOf(p.content);
      if (!t.includes('[ref=')) continue;
      const refs = {};
      for (const ln of t.split('\n')) {
        const m = ln.match(/^\s*-\s+([\w-]+)(?:\s+"((?:[^"\\]|\\.)*)")?([^\n]*?)\[ref=(e\d+)\](?:[^:]*:\s*(.*))?/);
        if (m) refs[m[4]] = { role: m[1], name: (m[2] || '') + ' ' + (m[5] || '') };
      }
      const u = t.match(/Page URL:\s*(\S+)/);
      return { url: u ? u[1] : '', refs };
    }
  }
  return { url: '', refs: {} };
}

// ---------------------------------------------------------------- 판정

function urlRisky(raw) {
  let u;
  try { u = new URL(String(raw)); } catch (_) { return '열 수 없는 주소'; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return u.protocol + ' 주소';
  let rest = u.pathname + ' ' + u.search + ' ' + u.hash;
  try { rest = decodeURIComponent(rest); } catch (_) {}
  const toks = norm(rest).split(/[^a-z0-9가-힣]+/).filter(Boolean);
  if (toks.some(t => URL_RISKY.includes(t)) || hasAny(norm(rest), RISKY.filter(w => /[가-힣]/.test(w)))) return '위험한 낱말이 든 주소';
  return '';
}

// 이 동작이 확인을 받아야 하면 {what, why}, 아니면 null
function judge(tool, inp, snap) {
  if (tool === 'Bash') {
    const c = norm(inp.command);
    if (hasAny(c, BASH_BROWSER) || BASH_PLAYWRIGHT.test(c)) return { what: 'Bash 로 브라우저 직접 조종', why: '전용 브라우저는 브라우저 도구로만' };
    return null;
  }
  if (!/^mcp__browser__/.test(String(tool || ''))) return null;
  const act = String(tool).replace(/^mcp__browser__/, '');
  if (SAFE_TOOLS.includes(act)) return null;
  const at = snap.url ? ' @' + snap.url.split(/[?#]/)[0] : '';
  const ref = id => (id && snap.refs[id]) || null;
  const label = (id, el) => { const r = ref(id); return (r ? r.role + ' "' + r.name.trim() + '"' : '"' + String(el || '') + '"') + (id ? ' [' + id + ']' : ''); };
  if (act === 'browser_navigate') {
    const why = urlRisky(inp.url);
    return why ? { what: 'navigate ' + inp.url, why } : null;
  }
  if (act === 'browser_type') {
    const txt = String(inp.text || '');
    if (!inp.submit && !/[\r\n]/.test(txt)) return null;
    return { what: label(inp.ref, inp.element) + ' 입력 후 제출' + at, why: '입력 후 제출(Enter)' };
  }
  if (act === 'browser_press_key') {
    const k = String(inp.key || '');
    return SAFE_KEYS.test(k.replace(/\s/g, '')) ? null : { what: '키 ' + k + at, why: 'Enter·스페이스·조합키는 제출·보내기가 될 수 있음' };
  }
  if (act === 'browser_handle_dialog') {
    return inp.accept === false ? null : { what: '확인 창 수락' + (inp.promptText ? ' "' + inp.promptText + '"' : '') + at, why: '확인 창 수락' };
  }
  if (act === 'browser_click') {
    const r = ref(inp.ref);
    const words = norm((r ? r.name : '') + ' ' + (inp.element || ''));
    if (r && !hasAny(words, RISKY) && !inp.doubleClick &&
        (NAV_ROLES.includes(r.role) || (r.role === 'button' && hasAny(norm(r.name), SAFE_BUTTON)))) return null;
    return { what: label(inp.ref, inp.element) + ' 클릭' + at, why: r ? '되돌리기 어려울 수 있는 단추' : '화면에서 찾지 못한 단추' };
  }
  if (act === 'browser_file_upload' && (!inp.paths || !inp.paths.length)) return null;   // 파일 고르기 창 닫기
  const target = inp.ref || inp.startRef ? label(inp.ref || inp.startRef, inp.element || inp.startElement) : '';
  return { what: act.replace(/^browser_/, '') + (target ? ' ' + target : '') + at, why: '확인이 필요한 브라우저 동작' };
}

function approved(text) {
  const t = String(text || '').trim();
  if (/^사용자 답\(/.test(t)) return ANSWER_RE.test(t);                    // 선택지 답은 정확히 그 한 줄만
  return t.split('\n').some(l => l.trim() === APPROVE);                    // 지시문 안의 사전 허락 한 줄
}

// 허락 하나는 동작 하나 — 같은 동작 다시 하기(실패 뒤 다시 누르기)는 1번 더
function consume(session, uuid, what) {
  const dir = path.join(os.tmpdir(), 'dnc-guard');
  const file = path.join(dir, String(session || 'none').replace(/[^\w-]/g, '_') + '.json');
  let used = {};
  try { used = JSON.parse(fs.readFileSync(file, 'utf8')).used || {}; } catch (_) {}
  if (typeof used !== 'object' || Array.isArray(used)) used = {};
  const rec = used[uuid];
  if (rec && (typeof rec !== 'object' || rec.what !== what || rec.n >= 2)) return false;
  used[uuid] = { what, n: rec ? rec.n + 1 : 1 };
  const keep = Object.fromEntries(Object.entries(used).slice(-50));
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ used: keep }));
  return true;
}

function deny(reason) {
  return { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: reason } };
}

function decide(d) {
  if (!d || typeof d !== 'object' || typeof d.tool_name !== 'string') return deny(PREFIX + ': 훅 입력을 읽지 못해 막았습니다.');
  const inp = d.tool_input && typeof d.tool_input === 'object' ? d.tool_input : {};
  const lines = readLines(d.transcript_path || '');
  const j = judge(d.tool_name, inp, d.tool_name === 'Bash' ? { url: '', refs: {} } : lastSnapshot(lines));
  if (!j) return null;
  if (d.tool_name === 'Bash') return deny(PREFIX + ': ' + j.what + '은(는) 막혀 있습니다 — ' + j.why + '(mcp__browser__*) 다루세요.');
  const h = lastHuman(lines);
  if (h && approved(h.text) && consume(d.session_id, h.uuid, j.what)) return null;   // 사람이 허락함 — 이 동작 하나만
  return deny(
    `${PREFIX}: ${j.what} — ${j.why}. 사람 확인 없이는 하지 않습니다. ` +
    `여기서 멈추고, 무엇을 하려는지(사이트·단추·입력값)를 짧게 적은 뒤 choices 로 물어보세요 — 선택지는 정확히 ${OPTIONS}. ` +
    `사람이 "${APPROVE}" 를 고르면 그 답을 받은 실행에서 같은 동작을 한 번 할 수 있습니다. ` +
    '읽기·이동·검색(snapshot·navigate·검색어 입력·링크와 탭 클릭)은 확인 없이 됩니다.');
}

function main(buf) {
  try {
    const out = decide(JSON.parse(buf));
    return out ? JSON.stringify(out) : '';
  } catch (e) {                                                              // fail-closed — 깨진 입력·판정 오류면 막는다
    return JSON.stringify(deny(PREFIX + ': 판정 중 오류가 나 막았습니다 (' + String(e && e.message || e).slice(0, 120) + ')'));
  }
}

if (require.main === module) {
  let buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', c => { buf += c; });
  process.stdin.on('end', () => { process.stdout.write(main(buf)); process.exit(0); });
}

module.exports = { judge, lastHuman, lastSnapshot, approved, decide, main, norm, APPROVE };
