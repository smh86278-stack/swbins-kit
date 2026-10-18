#!/usr/bin/env node
'use strict';
/* 브라우저 안전장치 — claude -p 의 PreToolUse 훅(--settings 로 붙인다. 디스패치 대화 chat_runner.py).
 * 전용 브라우저(mcp__browser__*)로 되돌리기 어려운 동작(보내기·삭제·결제·제출·승인·저장 단추, 입력 후 제출·Enter,
 * 클릭·전송하는 스크립트)을 하려 하면 막고, 사람에게 choices 로 묻게 한다. 전엔 chat-protocol.md 의 문장뿐이라
 * 모델이 지켜 주기만 바랐다(2026-10-19).
 *
 * 허락: 마지막 사람 글(세션 기록 transcript 의 type=user 글)에 '진행해도 됩니다' 가 있으면 그 글 하나당 동작 하나만 통과시킨다
 * (choices 답은 "사용자 답(번호 선택): ☑ 1. 진행해도 됩니다" 로 들어온다. 지시문에 미리 적어도 같다).
 * 어느 허락을 어느 동작에 썼는지 임시 폴더 dnc-guard\<세션>.json 에 적어 다른 동작에 또 쓰지 않는다.
 * 한계: 클릭은 모델이 적는 element 설명으로 판단한다 — 설명이 '파란 단추' 처럼 흐리면 못 거른다.
 * Node 만 쓴다(브라우저 도구가 npx 라 Node 는 늘 있다 — python 없는 PC 의 대화 앱 exe 에서도 돈다). */
const fs = require('fs');
const os = require('os');
const path = require('path');

const APPROVE = '진행해도 됩니다';
const OPTIONS = '["진행해도 됩니다", "하지 마세요"]';
// STRONG 은 늘 막는다. RISKY 는 메뉴·탭·목록처럼 화면만 옮기는 클릭(NAV)이면 둔다 — '주문 조회' 메뉴·'상품등록' 탭은 읽기다
const STRONG = /삭제|결제|송금|이체|탈퇴|해지|환불|\b(delete|pay|purchase|transfer)\b/i;
const RISKY = /보내기|발송|전송|송신|구매|주문하기|주문 ?확정|제출|승인|게시|등록|저장|\b(send|submit|remove|buy|checkout|approve|save|publish)\b/i;
const NAV = /메뉴|탭|링크|목록|조회|검색|menu|tab|link|list/i;
const SEARCH = /검색|찾기|조회|search|find|filter/i;
const SCRIPT = /\.click\(|\.submit\(|requestSubmit|dispatchEvent|\bfetch\(|XMLHttpRequest|\.(press|check|setInputFiles)\(/i;

// 이 동작이 위험하면 사람이 읽을 설명, 아니면 ''
function risky(tool, inp) {
  const act = String(tool || '').replace(/^mcp__browser__/, '');
  const el = String(inp.element || '');
  if (act === 'browser_click') return STRONG.test(el) || (RISKY.test(el) && !NAV.test(el)) ? `"${el}" 클릭` : '';
  if (act === 'browser_type' && inp.submit) return SEARCH.test(el) && !STRONG.test(el) && !RISKY.test(el) ? '' : `"${el}" 에 입력하고 제출(Enter)`;
  if (act === 'browser_press_key' && /^(enter|numpadenter)$/i.test(String(inp.key || ''))) return 'Enter 키(폼 제출·메시지 보내기가 될 수 있음)';
  if (/^browser_(evaluate|run_code)/.test(act)) {
    const code = JSON.stringify(inp);
    return SCRIPT.test(code) || STRONG.test(code) || RISKY.test(code) ? '클릭·전송하는 스크립트 실행' : '';
  }
  return '';
}

// 세션 기록에서 마지막 사람 글 {uuid, text} — 도구 결과(배열)·메타 글은 건너뛴다
function lastHuman(file) {
  let last = null;
  try {
    for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
      if (!/"type"\s*:\s*"user"/.test(line)) continue;
      try {
        const d = JSON.parse(line);
        const c = d.message && d.message.content;
        if (d.type === 'user' && !d.isMeta && typeof c === 'string') last = { uuid: d.uuid || c, text: c };
      } catch (_) {}
    }
  } catch (_) {}
  return last;
}

// 허락 하나는 동작 하나에만 — 처음 쓴 동작을 적어 두고, 같은 동작을 다시 하는 것(실패 뒤 다시 누르기)만 또 통과시킨다.
// 이어서 실행하면 브라우저가 새로 떠 첫 클릭이 빈 화면에서 실패하는 일이 있다(2026-10-19 실측) — 그때 허락이 날아가지 않게
function consume(session, uuid, what) {
  const dir = path.join(os.tmpdir(), 'dnc-guard');
  const file = path.join(dir, String(session || 'none').replace(/[^\w-]/g, '_') + '.json');
  let used = {};
  try { used = JSON.parse(fs.readFileSync(file, 'utf8')).used || {}; } catch (_) {}
  if (Array.isArray(used)) used = {};
  if (uuid in used) return used[uuid] === what;
  used[uuid] = what;
  const keep = Object.fromEntries(Object.entries(used).slice(-50));
  try { fs.mkdirSync(dir, { recursive: true }); fs.writeFileSync(file, JSON.stringify({ used: keep })); } catch (_) {}
  return true;
}

function decide(d) {
  const what = risky(d.tool_name, d.tool_input || {});
  if (!what) return null;                                       // 위험하지 않음 — 평소대로(허용 목록이 정한다)
  const h = lastHuman(d.transcript_path || '');
  if (h && h.text.includes(APPROVE) && consume(d.session_id, h.uuid, what)) return null;   // 사람이 허락함 — 이 동작 하나만
  return {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse', permissionDecision: 'deny',
      permissionDecisionReason:
        `브라우저 안전장치: ${what} 은(는) 되돌리기 어려울 수 있는 브라우저 동작이라 사람 확인 없이는 하지 않습니다. ` +
        `여기서 멈추고, 무엇을 하려는지(사이트·단추·입력값)를 짧게 적은 뒤 choices 로 물어보세요 — 선택지는 정확히 ${OPTIONS}. ` +
        `사람이 "${APPROVE}" 를 고르면 그 답을 받은 실행에서 같은 동작을 한 번 할 수 있습니다. 검색이면 검색 단추를 누르세요.`,
    },
  };
}

if (require.main === module) {
  let buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', c => { buf += c; });
  process.stdin.on('end', () => {
    let d = {};
    try { d = JSON.parse(buf); } catch (_) { process.exit(0); }   // 못 읽으면 막지 않는다(허용 목록이 상한)
    const out = decide(d);
    if (out) process.stdout.write(JSON.stringify(out));
    process.exit(0);
  });
}

module.exports = { risky, lastHuman, decide, APPROVE };
