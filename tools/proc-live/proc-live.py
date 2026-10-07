# -*- coding: utf-8 -*-
"""PC 프로세스 실시간 감시 — 프로그램이 뜨고 꺼지는 순간을 웹 화면에 바로 보여준다.

    python proc-live.py                 http://127.0.0.1:8600/
    python proc-live.py --port 8700 --open

외부 패키지 없이 표준 라이브러리 + ctypes 만 쓴다(Windows 전용).
  - 감지   : 0.15초마다 프로세스 스냅샷을 떠서 이전과 비교한다. 그보다 짧게 끝나는 프로세스는 놓칠 수 있다.
  - 화면   : SSE(/events)로 밀어 준다. 새로고침이 필요 없다.
  - 기록   : events.jsonl (5MB 가 넘으면 events.old.jsonl 로 넘긴다)
  - 학습   : known.json — 지금까지 본 실행 파일 경로. 처음 실행하면 떠 있는 프로세스로 채운다.
  - 규칙   : rules.local.json 이 있으면 기본값 위에 덮어쓴다(trusted_prefixes · ignore_names).

백신처럼 실행을 막지는 못한다 — 이미 뜬 뒤에 알려 줄 뿐이다.
프로세스 목록과 명령줄은 민감하므로 기본은 127.0.0.1 에만 바인딩한다.
"""
import argparse
import atexit
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))      # 이 키트 저장소 맨 위 — 여기서 뜬 것은 믿는다
F_EVENTS = os.path.join(HERE, 'events.jsonl')
F_OLD = os.path.join(HERE, 'events.old.jsonl')
F_KNOWN = os.path.join(HERE, 'known.json')
F_RULES = os.path.join(HERE, 'rules.local.json')

INTERVAL = 0.15
RING = 2000
LOG_LIMIT = 5 * 1024 * 1024

DEFAULT_RULES = {
    'trusted_prefixes': [
        'C:\\Windows\\', 'C:\\Program Files\\', 'C:\\Program Files (x86)\\',
        'C:\\ProgramData\\Microsoft\\', REPO_ROOT.rstrip('\\') + '\\',
    ],
    'ignore_names': [
        'conhost.exe', 'wmiprvse.exe', 'backgroundtaskhost.exe', 'runtimebroker.exe',
        'taskhostw.exe', 'searchprotocolhost.exe', 'searchfilterhost.exe', 'smartscreen.exe',
    ],
}


def load_rules():
    rules = {k: list(v) for k, v in DEFAULT_RULES.items()}
    if os.path.exists(F_RULES):
        try:
            with open(F_RULES, encoding='utf-8-sig') as f:
                for k, v in json.load(f).items():
                    if k in rules and isinstance(v, list):
                        rules[k] = [str(x) for x in v]
        except Exception as e:
            print('rules.local.json 읽기 실패(기본값 사용):', e, file=sys.stderr)
    return {
        'trusted': tuple(p.lower() for p in rules['trusted_prefixes']),
        'ignore': frozenset(n.lower() for n in rules['ignore_names']),
    }


# ---------------------------------------------------------------- Win32

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
ntdll = ctypes.WinDLL('ntdll')

TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED = 0x1000
PROCESS_QUERY_INFO = 0x0400
PROCESS_VM_READ = 0x0010
BAD_HANDLE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD),
                ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
                ('pcPriClassBase', wt.LONG), ('dwFlags', wt.DWORD), ('szExeFile', wt.WCHAR * 260)]


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [('ExitStatus', ctypes.c_long), ('PebBaseAddress', ctypes.c_void_p),
                ('AffinityMask', ctypes.c_void_p), ('BasePriority', ctypes.c_long),
                ('UniqueProcessId', ctypes.c_void_p), ('InheritedFromUniqueProcessId', ctypes.c_void_p)]


k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = ctypes.c_void_p
k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
ntdll.NtQueryInformationProcess.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
                                            ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]


def snapshot():
    """{pid: (ppid, name)} — 프로세스 전체 목록 한 번."""
    h = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h in (None, BAD_HANDLE):
        return {}
    out = {}
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(h, ctypes.byref(e))
        while ok:
            out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = k32.Process32NextW(h, ctypes.byref(e))
    finally:
        k32.CloseHandle(h)
    return out


def image_path(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ''
    finally:
        k32.CloseHandle(h)


def _read(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def command_line(pid):
    """PEB 를 읽어 명령줄을 얻는다(64비트 파이썬 기준). 권한이 없거나 이미 끝났으면 ''."""
    if sys.maxsize <= 2 ** 32:
        return ''
    h = k32.OpenProcess(PROCESS_QUERY_INFO | PROCESS_VM_READ, False, pid)
    if not h:
        return ''
    try:
        pbi = PROCESS_BASIC_INFORMATION()
        if ntdll.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None) != 0 or not pbi.PebBaseAddress:
            return ''
        raw = _read(h, pbi.PebBaseAddress + 0x20, 8)               # PEB.ProcessParameters
        if not raw:
            return ''
        params = int.from_bytes(raw, 'little')
        raw = _read(h, params + 0x70, 16)                          # CommandLine (UNICODE_STRING)
        if not raw:
            return ''
        length = int.from_bytes(raw[0:2], 'little')
        buf_addr = int.from_bytes(raw[8:16], 'little')
        if not length or not buf_addr:
            return ''
        data = _read(h, buf_addr, min(length, 4096))
        return data.decode('utf-16-le', 'replace') if data else ''
    except Exception:
        return ''
    finally:
        k32.CloseHandle(h)


# ---------------------------------------------------------------- 상태 · 방송

RULES = load_rules()
ring = deque(maxlen=RING)          # 화면에 줄 행(시작 이벤트). 종료되면 end 가 채워진다
by_id = {}
lock = threading.Lock()
subs = []
known = set()
known_dirty = False
next_id = int(time.time() * 1000)
stats = {'started': 0, 'first': 0, 'since': int(time.time() * 1000)}


def broadcast(msg):
    data = json.dumps(msg, ensure_ascii=False)
    with lock:
        for q in list(subs):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def is_trusted(path):
    return path.lower().startswith(RULES['trusted'])


def append_log(row):
    try:
        if os.path.exists(F_EVENTS) and os.path.getsize(F_EVENTS) > LOG_LIMIT:
            os.replace(F_EVENTS, F_OLD)
        with open(F_EVENTS, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    except OSError:
        pass


def load_history():
    """재시작 직후에도 화면이 비지 않도록 기록 끝부분을 되살린다(종료 시각은 알 수 없다)."""
    if not os.path.exists(F_EVENTS):
        return
    try:
        with open(F_EVENTS, encoding='utf-8') as f:
            lines = f.readlines()[-300:]
    except OSError:
        return
    for line in lines:
        try:
            row = json.loads(line)
            row['end'] = row.get('end') or -1       # -1: 종료 시각 모름
            ring.append(row)
            by_id[row['id']] = row
        except Exception:
            continue


def load_known():
    global known_dirty
    if os.path.exists(F_KNOWN):
        try:
            with open(F_KNOWN, encoding='utf-8') as f:
                known.update(p.lower() for p in json.load(f))
            return True
        except Exception:
            pass
    known_dirty = True
    return False


def save_known():
    global known_dirty
    if not known_dirty:
        return
    try:
        with open(F_KNOWN, 'w', encoding='utf-8') as f:
            json.dump(sorted(known), f, ensure_ascii=False)
        known_dirty = False
    except OSError:
        pass


# ---------------------------------------------------------------- 감지 루프

def scan_loop():
    global next_id, known_dirty
    me = os.getpid()
    alive = {}                     # pid -> {'key': (ppid, name), 'id': 행 id 또는 None}

    seeded = load_known()
    for pid, key in snapshot().items():
        alive[pid] = {'key': key, 'id': None}
        if not seeded:
            p = image_path(pid)
            if p:
                known.add(p.lower())
                known_dirty = True
    save_known()

    last_save = time.time()
    while True:
        time.sleep(INTERVAL)
        cur = snapshot()
        now = int(time.time() * 1000)

        for pid, key in cur.items():
            old = alive.get(pid)
            if old and old['key'] == key:
                continue
            if old and old['id'] is not None:                      # PID 재사용 — 앞 프로세스는 끝난 것
                end_row(old['id'], now)
            if pid == me or key[1].lower() in RULES['ignore']:
                alive[pid] = {'key': key, 'id': None}
                continue
            path = image_path(pid)
            first = False
            if path and path.lower() not in known:
                known.add(path.lower())
                known_dirty = True
                first = True
            next_id += 1
            ppid = key[0]
            parent = cur.get(ppid, (0, ''))[1] if ppid in cur else ''
            row = {'id': next_id, 't': now, 'pid': pid, 'ppid': ppid, 'parent': parent, 'name': key[1],
                   'path': path, 'cmd': command_line(pid),
                   'trusted': is_trusted(path) if path else None, 'first': first, 'end': None}
            with lock:
                ring.append(row)
                by_id[row['id']] = row
                if len(by_id) > RING * 2:
                    for k in [k for k in by_id if k < ring[0]['id']]:
                        del by_id[k]
            stats['started'] += 1
            stats['first'] += 1 if first else 0
            append_log({k: v for k, v in row.items() if k != 'end'})
            broadcast({'t': 'start', 'row': row})
            alive[pid] = {'key': key, 'id': row['id']}

        for pid in [p for p in alive if p not in cur]:
            gone = alive.pop(pid)
            if gone['id'] is not None:
                end_row(gone['id'], now)

        if time.time() - last_save > 30:
            last_save = time.time()
            save_known()


def end_row(row_id, now):
    row = by_id.get(row_id)
    if row and not row['end']:
        row['end'] = now
        broadcast({'t': 'end', 'id': row_id, 'end': now})


# ---------------------------------------------------------------- 웹

PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>프로세스 실시간 감시</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--text:#1d2330;--muted:#6b7385;--line:#e3e6ec;--accent:#2f6fed;--ok:#1f9d55;--warn:#d9822b;--bad:#d64545;--flash:#e7f0ff}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14171d;--panel:#1c2029;--text:#e6e9ef;--muted:#8d95a6;--line:#2b303b;--accent:#6aa0ff;--ok:#4cc38a;--warn:#f0a35a;--bad:#ef7676;--flash:#223252}}
:root[data-theme=dark]{--bg:#14171d;--panel:#1c2029;--text:#e6e9ef;--muted:#8d95a6;--line:#2b303b;--accent:#6aa0ff;--ok:#4cc38a;--warn:#f0a35a;--bad:#ef7676;--flash:#223252}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Segoe UI","Malgun Gothic",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--panel);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center}
h1{font-size:16px;margin:0;display:flex;align-items:center;gap:8px}
#dot{width:10px;height:10px;border-radius:50%;background:var(--bad)}
#dot.on{background:var(--ok);box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 25%,transparent)}
.stats{color:var(--muted);font-size:13px}
.stats b{color:var(--text);font-variant-numeric:tabular-nums}
.tools{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-left:auto}
input[type=search]{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 10px;min-width:200px}
label{display:flex;gap:4px;align-items:center;color:var(--muted);cursor:pointer;user-select:none}
button{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 10px;cursor:pointer}
button:hover{border-color:var(--accent)}
button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
main{padding:12px 16px 40px}
.wrap{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;color:var(--muted);font-weight:600;font-size:12px;background:var(--panel)}
td.t,td.pid,td.st{white-space:nowrap;font-variant-numeric:tabular-nums}
td.name{font-weight:600}
td.path{color:var(--muted);word-break:break-all;font-size:12.5px;cursor:pointer}
.cmd{display:none;margin-top:4px;padding:6px 8px;background:var(--bg);border-radius:4px;color:var(--text);white-space:pre-wrap}
tr.open .cmd{display:block}
tr.new td{animation:flash 1.6s ease-out}
@keyframes flash{from{background:var(--flash)}to{background:transparent}}
.badge{display:inline-block;border-radius:10px;padding:0 7px;font-size:11px;font-weight:600;margin-left:6px;vertical-align:1px}
.b-first{background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent)}
.b-bad{background:color-mix(in srgb,var(--warn) 22%,transparent);color:var(--warn)}
tr.sus td.name{color:var(--warn)}
.run{color:var(--ok)}.end{color:var(--muted)}
.empty{padding:28px;text-align:center;color:var(--muted)}
@media (max-width:640px){header{padding:10px 12px}main{padding:10px 12px}.tools{margin-left:0}}
@media (prefers-reduced-motion:reduce){tr.new td{animation:none}}
</style>
</head>
<body>
<header>
  <h1><span id="dot" title="연결 상태"></span>프로세스 실시간 감시</h1>
  <div class="stats">실행 중 <b id="nRun">0</b> · 화면 <b id="nShow">0</b> · 새로 본 것 <b id="nFirst">0</b></div>
  <div class="tools">
    <input id="q" type="search" placeholder="이름·경로·명령줄 검색">
    <label><input id="fSus" type="checkbox">신뢰 경로 밖만</label>
    <label><input id="fFirst" type="checkbox">처음 본 것만</label>
    <label><input id="fRun" type="checkbox">실행 중만</label>
    <button id="freeze">화면 멈춤</button>
    <button id="clear">비우기</button>
  </div>
</header>
<main>
  <div class="wrap">
    <table>
      <thead><tr><th>시작</th><th>이름</th><th>PID</th><th>부모</th><th>경로 (클릭하면 명령줄)</th><th>상태</th></tr></thead>
      <tbody id="body"></tbody>
    </table>
    <div id="empty" class="empty">감지 대기 중… 프로그램을 하나 실행해 보세요.</div>
  </div>
</main>
<script>
const $=s=>document.querySelector(s), MAX=1000;
const rows=new Map(); let frozen=false, pending=[], firstCount=0, hadOpen=false;
const pad=(n,w=2)=>String(n).padStart(w,'0');
function fmtT(t){const d=new Date(t);return pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds())+'.'+pad(d.getMilliseconds(),3)}
function fmtD(ms){const s=Math.max(0,Math.floor(ms/1000));if(s<60)return s+'초';const m=Math.floor(s/60);return m<60?m+'분 '+s%60+'초':Math.floor(m/60)+'시간 '+m%60+'분'}
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}

function build(r,fresh){
  const tr=el('tr',fresh?'new':'');
  const name=el('td','name',r.name);
  if(r.first){name.append(el('span','badge b-first','★ 새것'))}
  if(r.trusted===false){name.append(el('span','badge b-bad','신뢰 경로 밖'))}
  const path=el('td','path',r.path||'(경로 확인 불가)');
  if(r.cmd){path.append(el('div','cmd',r.cmd))}
  path.onclick=()=>tr.classList.toggle('open');
  tr.append(el('td','t',fmtT(r.t)),name,el('td','pid',r.pid),el('td','',r.parent||'—'),path,el('td','st'));
  if(r.first&&r.trusted===false)tr.classList.add('sus');
  return tr;
}
function paintState(o){
  const c=o.tr.lastChild,r=o.r;
  if(!r.end){c.className='st run';c.textContent='● '+fmtD(Date.now()-r.t)}
  else if(r.end<0){c.className='st end';c.textContent='종료 (시각 모름)'}
  else{c.className='st end';c.textContent='종료 · '+fmtD(r.end-r.t)}
}
function visible(r){
  const q=$('#q').value.trim().toLowerCase();
  if($('#fSus').checked&&r.trusted!==false)return false;
  if($('#fFirst').checked&&!r.first)return false;
  if($('#fRun').checked&&r.end)return false;
  if(q&&!((r.name+' '+r.path+' '+r.cmd+' '+r.parent).toLowerCase().includes(q)))return false;
  return true;
}
function refresh(){
  let show=0,run=0;
  for(const o of rows.values()){const v=visible(o.r);o.tr.hidden=!v;if(v)show++;if(!o.r.end)run++}
  $('#nShow').textContent=show;$('#nRun').textContent=run;$('#nFirst').textContent=firstCount;
  $('#empty').style.display=rows.size?'none':'';
}
function addRow(r,fresh){
  if(rows.has(r.id)){rows.get(r.id).r=r;paintState(rows.get(r.id));return}
  const o={r,tr:build(r,fresh)};rows.set(r.id,o);paintState(o);
  $('#body').prepend(o.tr);
  if(r.first&&fresh)firstCount++;
  while(rows.size>MAX){const last=$('#body').lastChild;for(const[k,v]of rows)if(v.tr===last){rows.delete(k);break}last.remove()}
  o.tr.hidden=!visible(r);
}
function onMsg(m){
  if(m.t==='start'){if(frozen){pending.push(m);$('#freeze').textContent='재개 ('+pending.length+')';return}addRow(m.row,true)}
  else if(m.t==='end'){const o=rows.get(m.id);if(o){o.r.end=m.end;paintState(o)}else{pending.forEach(p=>{if(p.row.id===m.id)p.row.end=m.end})}}
  refresh();
}
async function loadRecent(){
  try{const list=await (await fetch('/api/recent')).json();firstCount=list.filter(r=>r.first).length;list.forEach(r=>addRow(r,false));refresh()}catch(e){}
}
function connect(){
  const es=new EventSource('/events');
  es.onopen=()=>{$('#dot').classList.add('on');if(hadOpen)loadRecent();hadOpen=true};
  es.onerror=()=>$('#dot').classList.remove('on');
  es.onmessage=e=>onMsg(JSON.parse(e.data));
}
['#q','#fSus','#fFirst','#fRun'].forEach(s=>$(s).addEventListener('input',refresh));
$('#freeze').onclick=()=>{
  frozen=!frozen;$('#freeze').classList.toggle('active',frozen);
  if(!frozen){const p=pending;pending=[];p.forEach(m=>addRow(m.row,true));refresh()}
  $('#freeze').textContent=frozen?'재개':'화면 멈춤';
};
$('#clear').onclick=()=>{rows.clear();$('#body').replaceChildren();firstCount=0;refresh()};
setInterval(()=>{for(const o of rows.values())if(!o.r.end&&!o.tr.hidden)paintState(o)},1000);
loadRecent().then(connect);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = 'proc-live'
    allowed_hosts = None

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # DNS rebinding 방어 — 루프백에 묶인 경우 Host 헤더가 우리 주소가 아니면 거절한다
        if self.allowed_hosts and self.headers.get('Host', '') not in self.allowed_hosts:
            return self._send(403, b'forbidden', 'text/plain')
        u = urlparse(self.path)
        if u.path == '/':
            return self._send(200, PAGE.encode('utf-8'), 'text/html; charset=utf-8')
        if u.path == '/favicon.ico':
            return self._send(204, b'', 'image/x-icon')
        if u.path == '/api/recent':
            n = int(parse_qs(u.query).get('n', ['500'])[0] or 500)
            with lock:
                rows = list(ring)[-max(1, min(n, RING)):]
            return self._send(200, json.dumps(rows, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')
        if u.path == '/api/stats':
            return self._send(200, json.dumps(stats).encode('utf-8'), 'application/json')
        if u.path == '/events':
            return self._sse()
        self._send(404, b'not found', 'text/plain')

    def _sse(self):
        q = queue.Queue(maxsize=2000)
        with lock:
            subs.append(q)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.wfile.write(b': connected\n\n')
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=15)
                    self.wfile.write(('data: ' + data + '\n\n').encode('utf-8'))
                except queue.Empty:
                    self.wfile.write(b': ping\n\n')
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with lock:
                if q in subs:
                    subs.remove(q)


def main():
    ap = argparse.ArgumentParser(description='PC 프로세스 실시간 감시 + 웹 화면')
    ap.add_argument('--port', type=int, default=8600)
    ap.add_argument('--host', default='127.0.0.1', help='기본은 이 PC 에서만. 0.0.0.0 으로 열면 같은 망에서 프로세스 목록이 보인다')
    ap.add_argument('--open', action='store_true', help='시작하면 브라우저를 연다')
    args = ap.parse_args()

    load_history()
    atexit.register(save_known)
    threading.Thread(target=scan_loop, daemon=True).start()

    if args.host in ('127.0.0.1', 'localhost'):
        Handler.allowed_hosts = {'127.0.0.1:%d' % args.port, 'localhost:%d' % args.port}
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    url = 'http://127.0.0.1:%d/' % args.port
    print('프로세스 실시간 감시 —', url, '(Ctrl+C 로 종료)', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
