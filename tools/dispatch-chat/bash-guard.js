#!/usr/bin/env node
'use strict';
/* 명령 안전장치 — claude -p 의 PreToolUse 훅(matcher Bash). Bash 가 'Bash(git log:*)' 처럼 정해진 명령만 허용된 작업
 * (읽기 지시)에만 붙인다(워커 inbox-worker.ps1 · 메신저 chat_runner.py). Bash 전체가 열린 쓰기 지시엔 붙이지 않는다.
 *
 * 왜: 허용 규칙은 명령 앞부분만 본다. 'git log -1 --format=… --output=.git/config' 로 설정 파일을 쓰고
 * 'git status' 로 fsmonitor 명령을 돌리게 하면 읽기 지시에서 아무 명령이나 실행됐다(2026-10-19 보안 점검, 임시 저장소에서 실측).
 * 막는 것: 명령 잇기·돌려쓰기(; & | ` $( ) > < 줄바꿈), git 의 파일 쓰기·외부 명령·설정 바꾸기 옵션(--output -o --ext-diff
 * --textconv -c --config-env --exec-path --git-dir --work-tree -C --no-index --upload-pack …)과 core.·fsmonitor·alias. 같은 설정 이름.
 * 오류가 나면 막는다(fail-closed) — 이 훅이 죽어서 통과되는 일이 없게. Node 만 쓴다(브라우저 도구와 같은 이유).
 *
 * 읽기 도구(matcher Read|Glob|Grep)에도 붙는다(2026-10-28, 10-19 점검의 남은 낮은 항목): Read 는 경로 제한이 없어
 * 작업 폴더 밖의 비밀(메일 암호 설정·.keys·SSH 키·브라우저 로그인 DB 등)을 읽어 답장에 실을 수 있었다.
 * 보통 파일 읽기는 그대로 두고, 비밀 자리와 홈·드라이브 맨 위 통째 검색만 막는다. */

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

// 비밀이 사는 자리 — 경로를 / 로 바꾸고 소문자로 맞춘 뒤 본다
const SECRET_DIR = /\/(\.ssh|\.aws|\.gnupg|\.azure|\.kube|\.keys|chrome-profile|pw-profile)(\/|$)|\/(google\/chrome|microsoft\/edge|bravesoftware\/brave-browser)\/user data(\/|$)|\/mozilla\/firefox\/profiles(\/|$)|\/microsoft\/(credentials|protect|vault)(\/|$)|\/windows\/system32\/config(\/|$)/;
const SECRET_FILE = /(^|\/)(mail\.local\.json|creds\.json|\.credentials\.json|\.git-credentials|[._]netrc|\.env(\.[^/]*)?|login data( for account)?|cookies|web data|local state|id_(rsa|dsa|ecdsa|ed25519)[^/]*|[^/]*\.(key|pfx|p12|kdbx|keychain(-db)?)|secrets?(\.local)?\.json|[^/]*(secret|credential|password|passwd)[^/]*\.(json|txt|ini|ya?ml|xml))$/;

function norm(p) {
  return String(p || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '').toLowerCase();
}

// 홈·드라이브 맨 위·AppData 통째로 훑는 검색 — 비밀 파일까지 같이 훑는다
function tooWide(p) {
  const n = norm(p);
  return /^[a-z]:$/.test(n) || n === '' || n === '~' || /^([a-z]:)?\/users(\/[^/]+)?$/.test(n) ||
    /^([a-z]:)?\/users\/[^/]+\/appdata(\/(local|roaming))?$/.test(n) || /^\/(home(\/[^/]+)?)?$/.test(n);
}

function secretReason(p) {
  const n = norm(p);
  if (!n) return '';
  if (SECRET_DIR.test(n) || SECRET_FILE.test(n.split('/').pop())) return '비밀이 든 자리(' + String(p) + ')는 이 작업에서 읽지 않습니다';
  return '';
}

// 읽기 도구(Read·Glob·Grep)를 막을 이유, 괜찮으면 ''
function readReason(tool, inp) {
  const i = inp || {};
  if (tool === 'Read') return secretReason(i.file_path);
  const why = secretReason(i.path) || (tool === 'Glob' ? secretReason(i.pattern) : '');
  if (why) return why;
  if (i.path && tooWide(i.path)) return '홈·드라이브 맨 위(' + i.path + ')를 통째로 훑는 검색은 이 작업에서 쓰지 않습니다 — 폴더를 좁혀 주세요';
  if (tool === 'Glob' && /^([a-z]:)?[\\/]/i.test(String(i.pattern || '')) && tooWide(String(i.pattern).replace(/[\\/]\*.*$/, ''))) {
    return '홈·드라이브 맨 위를 통째로 훑는 패턴(' + i.pattern + ')은 이 작업에서 쓰지 않습니다';
  }
  return '';
}

function deny(why, tail) {
  return { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny',
    permissionDecisionReason: '명령 안전장치: ' + why + '. ' + (tail || '읽기만 하는 같은 명령(옵션 없이)으로 다시 하거나, 꼭 필요하면 무엇이 필요한지 적고 멈추세요.') } };
}

function decide(d) {
  if (!d || typeof d !== 'object') return deny('훅 입력을 읽지 못했습니다');
  if (d.tool_name === 'Read' || d.tool_name === 'Glob' || d.tool_name === 'Grep') {
    const why = readReason(d.tool_name, d.tool_input);
    return why ? deny(why, '다른 방법으로 우회하지 말고, 꼭 필요하면 무엇이 필요한지 적고 멈추세요.') : null;
  }
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

module.exports = { reason, readReason, decide };
