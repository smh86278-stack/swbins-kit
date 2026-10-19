#!/usr/bin/env node
'use strict';
/* 명령 안전장치 — claude -p 의 PreToolUse 훅(matcher Bash). Bash 가 'Bash(git log:*)' 처럼 정해진 명령만 허용된 작업
 * (읽기 지시)에만 붙인다(워커 inbox-worker.ps1 · 메신저 chat_runner.py). Bash 전체가 열린 쓰기 지시엔 붙이지 않는다.
 *
 * 왜: 허용 규칙은 명령 앞부분만 본다. 'git log -1 --format=… --output=.git/config' 로 설정 파일을 쓰고
 * 'git status' 로 fsmonitor 명령을 돌리게 하면 읽기 지시에서 아무 명령이나 실행됐다(2026-10-19 보안 점검, 임시 저장소에서 실측).
 * 막는 것: 명령 잇기·돌려쓰기(; & | ` $( ) > < 줄바꿈), git 의 파일 쓰기·외부 명령·설정 바꾸기 옵션(--output -o --ext-diff
 * --textconv -c --config-env --exec-path --git-dir --work-tree -C --no-index --upload-pack …)과 core.·fsmonitor·alias. 같은 설정 이름.
 * 오류가 나면 막는다(fail-closed) — 이 훅이 죽어서 통과되는 일이 없게. Node 만 쓴다(브라우저 도구와 같은 이유). */

const CHAIN = /[;&|`<>\r\n]|\$\(/;
const GIT_OPT = /(^|\s)(--output|-o|--ext-diff|--textconv|-c|--config-env|--exec-path|--git-dir|--work-tree|-C|--no-index|--upload-pack|--receive-pack|--exec|--super-prefix|--namespace)(=|\s|$)/i;
const GIT_WORD = /\b(core\.|fsmonitor|alias\.|sshcommand|hookspath|diff\.external|textconv|filter\.|credential\.helper)/i;   // --no-pager 는 둔다(-c core.pager 는 -c 로 막힌다)

// 막을 이유(사람이 읽을 글), 괜찮으면 ''
function reason(cmd) {
  const c = String(cmd || '').trim().replace(/^rtk\s+/, '');
  if (!c) return '';
  if (CHAIN.test(c)) return '명령 잇기·돌려쓰기(; & | ` $( ) > < 줄바꿈)는 이 작업에서 쓰지 않습니다';
  if (/^git(\s|$)/i.test(c) || /\bgit(\.exe)?\s/i.test(c)) {
    const m = c.match(GIT_OPT);
    if (m) return 'git 의 ' + m[2] + ' 옵션은 파일을 쓰거나 다른 명령을 부를 수 있어 이 작업에서 쓰지 않습니다';
    const w = c.match(GIT_WORD);
    if (w) return 'git 설정(' + w[1] + ')을 건드리는 명령은 이 작업에서 쓰지 않습니다';
  }
  return '';
}

function deny(why) {
  return { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny',
    permissionDecisionReason: '명령 안전장치: ' + why + '. 읽기만 하는 같은 명령(옵션 없이)으로 다시 하거나, 꼭 필요하면 무엇이 필요한지 적고 멈추세요.' } };
}

function decide(d) {
  if (!d || typeof d !== 'object') return deny('훅 입력을 읽지 못했습니다');
  if (d.tool_name !== 'Bash') return null;
  const why = reason((d.tool_input || {}).command);
  return why ? deny(why) : null;
}

if (require.main === module) {
  let buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', c => { buf += c; });
  process.stdin.on('end', () => {
    let out;
    try { out = decide(JSON.parse(buf)); } catch (e) { out = deny('훅이 입력을 처리하지 못했습니다(' + e.message + ')'); }
    if (out) process.stdout.write(JSON.stringify(out));
    process.exit(0);
  });
}

module.exports = { reason, decide };
