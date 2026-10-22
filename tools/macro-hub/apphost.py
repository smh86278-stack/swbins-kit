# -*- coding: utf-8 -*-
"""✨ 나만의 앱 실행 환경 — 표준 라이브러리만.

앱은 폴더 하나다. 키트가 주는 견본은 apps\\<id>\\, 내가 만든 앱은 apps.local\\<id>\\(git 제외).
    app.json   {"name", "icon", "kind": "app"|"game"|"ai", "version", "desc", "permissions": ["db", ...]}
    index.html · src\\ · styles\\ · assets\\ …
앱 데이터는 앱 폴더가 아니라 data.local\\apps\\<id>\\ 에 둔다(키트 업데이트로 견본 폴더가 덮여도 남고, git 제외).

격리: 앱은 허브(8630)와 다른 포트(8631)에서, **앱마다 다른 출처** http://<id>.localhost:8631/ 로 뜬다
(브라우저는 *.localhost 를 이 PC 로 보낸다). 그래서 앱의 스크립트는 허브 토큰도, 다른 앱의 데이터도 못 읽는다.
  - Host 머리글이 '<id>.localhost:<port>' 가 아니면 403(DNS 리바인딩 막기). 그 앱의 파일과 API 만 내준다.
  - 앱 API(/_api/*)는 POST + 'X-App: 1' 머리글(다른 사이트의 폼·이미지 요청은 이 머리글을 못 붙인다) + Origin 이 자기 자신.
  - 화면은 CSP 로 바깥 주소에 못 붙는다(connect-src 'self') — 앱이 PC 자료를 밖으로 내보내지 못하게.
권한: app.json 에 적은 것 중 사람이 허브 「✨ 앱」 탭에서 허락한 것만 쓴다(data.local\\apps.json).
    db      이 앱 전용 SQLite(data.local\\apps\\<id>\\app.db) — ATTACH 로 다른 파일을 못 연다
    ai · run · notify · files   — 3d 단계에서 연다(지금은 501)
앱 화면의 도우미는 <script src="/_app.js"></script> → app.db(sql, params) · app.info().
"""
import json
import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DIR_BUILTIN = os.path.join(HERE, 'apps')
DIR_LOCAL = os.path.join(HERE, 'apps.local')
STATE = os.path.join(HERE, 'data.local', 'apps.json')
DATA = os.path.join(HERE, 'data.local', 'apps')
LIB = os.path.join(HERE, 'apps-lib')                 # 동봉 라이브러리 — 모든 앱에 /_lib/<파일>
TEMPLATES = os.path.join(HERE, 'app-templates')      # 새 앱의 뼈대 — <이름>\template.json + 앱 파일
PORT = 8631
ID_RE = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?')
KINDS = ('app', 'game', 'ai')
PERMS = {'db': '데이터 저장 (이 앱 전용 DB)',
         'ai': 'AI 에게 글 부탁 (고른 AI)',
         'run': '내 자동화 실행',
         'notify': '알림 보내기 (메일·메신저)',
         'files': '파일 읽기·쓰기 (이 앱 data 폴더 안만)'}
READY = ('db',)                    # 지금 동작하는 권한 — 나머지는 3d
MAX_ROWS = 5000
MAX_BODY = 2 * 1024 * 1024
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
         '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
         '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
         '.ico': 'image/x-icon', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav', '.mp4': 'video/mp4',
         '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.txt': 'text/plain; charset=utf-8',
         '.md': 'text/plain; charset=utf-8', '.wasm': 'application/wasm'}
HIDDEN_DIRS = ('data', '.history')
_lock = threading.Lock()

APP_JS = r'''// 나만의 앱 도우미 — 허브 키트가 내준다(/_app.js). 앱 데이터는 이 앱 전용, 바깥 주소로는 못 보낸다.
(function () {
  async function call(name, body) {
    const r = await fetch('/_api/' + name, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-App': '1'},
                                            body: JSON.stringify(body || {})});
    const d = await r.json().catch(() => ({error: '응답을 읽지 못했습니다 (' + r.status + ')'}));
    if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
    return d;
  }
  window.app = {
    info: () => call('info'),
    // SQL 하나 — SELECT 면 rows(객체 배열), 아니면 changes·last_id. 값은 ? 자리에 params 로.
    db: (sql, params) => call('db', {sql: sql, params: params || []}),
    // 여러 문장(테이블 만들기 등) — 값 없이 한 번에
    dbScript: (sql) => call('db', {script: sql}),
  };
})();
'''


# ---------------------------------------------------------------- 앱 목록·권한

def _read_json(path, default):
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _state():
    s = _read_json(STATE, {})
    return s if isinstance(s, dict) else {}


def _save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def manifest(folder):
    """app.json 을 읽어 고른 값만 — 잘못된 값은 기본값으로. 폴더 이름이 앱 id."""
    raw = _read_json(os.path.join(folder, 'app.json'), None)
    if not isinstance(raw, dict):
        raw = {'_error': 'app.json 이 없거나 JSON 이 아닙니다'}
    perms = [p for p in (raw.get('permissions') or []) if p in PERMS] if isinstance(raw.get('permissions'), list) else []
    return {'name': str(raw.get('name') or os.path.basename(folder))[:60],
            'icon': str(raw.get('icon') or '✨')[:4],
            'kind': raw.get('kind') if raw.get('kind') in KINDS else 'app',
            'version': str(raw.get('version') or '0.1.0')[:20],
            'desc': str(raw.get('desc') or '')[:300],
            'permissions': sorted(set(perms), key=list(PERMS).index),
            'error': raw.get('_error') or ('' if os.path.isfile(os.path.join(folder, 'index.html')) else 'index.html 이 없습니다')}


def discover():
    """{id: {id, dir, builtin, …manifest}} — 같은 id 면 내 앱(apps.local)이 이긴다."""
    out = {}
    for base, builtin in ((DIR_BUILTIN, True), (DIR_LOCAL, False)):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            if ID_RE.fullmatch(name) and os.path.isdir(folder):
                out[name] = dict(manifest(folder), id=name, dir=folder, builtin=builtin)
    return out


def find(app_id):
    return discover().get(app_id) if ID_RE.fullmatch(app_id or '') else None


def approved(app_id, app=None):
    """허락된 권한 — app.json 에 지금 적혀 있는 것과 겹치는 것만(권한을 뺀 앱이 옛 허락을 계속 갖지 않게)."""
    app = app or find(app_id)
    if not app:
        return []
    got = set(_state().get('approved', {}).get(app_id) or [])
    return [p for p in app['permissions'] if p in got]


def approve(app_id, perms):
    app = find(app_id)
    if not app:
        raise ValueError('없는 앱입니다')
    bad = [p for p in perms if p not in app['permissions']]
    if bad:
        raise ValueError('이 앱이 요청하지 않은 권한입니다: %s' % ', '.join(bad))
    with _lock:
        s = _state()
        s.setdefault('approved', {})[app_id] = sorted(set(perms), key=list(PERMS).index)
        _save_state(s)
    return approved(app_id)


def url(app_id, port=None):
    return 'http://%s.localhost:%d/' % (app_id, port or PORT)


def view(app, port=None):
    ok = approved(app['id'], app)
    return {k: app[k] for k in ('id', 'name', 'icon', 'kind', 'version', 'desc', 'permissions', 'builtin', 'error')} | {
        'approved': ok, 'pending': [p for p in app['permissions'] if p not in ok],
        'perm_names': {p: PERMS[p] for p in app['permissions']}, 'ready': [p for p in app['permissions'] if p in READY],
        'url': url(app['id'], port)}


def list_view(port=None):
    return [view(a, port) for a in discover().values()]


def templates():
    """새 앱 뼈대 목록 [{id, name, desc, kind, tier}] — tier 는 free|pro(유료판 표시용, 지금은 모두 쓸 수 있음)."""
    out = []
    if os.path.isdir(TEMPLATES):
        for name in sorted(os.listdir(TEMPLATES)):
            t = _read_json(os.path.join(TEMPLATES, name, 'template.json'), None)
            if ID_RE.fullmatch(name) and isinstance(t, dict):
                out.append({'id': name, 'name': str(t.get('name') or name), 'desc': str(t.get('desc') or ''),
                            'kind': t.get('kind') if t.get('kind') in KINDS else 'app', 'tier': t.get('tier') or 'free',
                            'order': t.get('order', 99)})
    return sorted(out, key=lambda t: (t['order'], t['id']))


def create_app(app_id, name, template='blank', desc=''):
    """템플릿을 apps.local\\<id> 로 복사하고 app.json 의 이름·설명을 채운다. 만든 앱 정보를 돌려준다."""
    import shutil
    app_id = (app_id or '').strip().lower()
    if not ID_RE.fullmatch(app_id):
        raise ValueError('앱 주소 이름은 영문 소문자·숫자·하이픈(-)으로 2~40자 (예: sales-board)')
    if find(app_id):
        raise ValueError('이미 있는 앱 이름입니다: %s' % app_id)
    src = os.path.join(TEMPLATES, template or '')
    if not ID_RE.fullmatch(template or '') or not os.path.isfile(os.path.join(src, 'template.json')):
        raise ValueError('없는 템플릿입니다: %s' % template)
    dst = os.path.join(DIR_LOCAL, app_id)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns('template.json'))
    mf = os.path.join(dst, 'app.json')
    m = _read_json(mf, {}) if os.path.isfile(mf) else {}
    m['name'] = (name or '').strip()[:60] or app_id
    if desc:
        m['desc'] = desc.strip()[:300]
    with open(mf, 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    return find(app_id)


# ---------------------------------------------------------------- 앱 전용 DB

def _deny_attach(action, *args):
    return sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK


def db_path(app):
    return os.path.join(DATA, app['id'], 'app.db')


def run_sql(app, body):
    """{sql, params} 하나 또는 {script} — 결과 {rows} | {changes, last_id} | {ok}."""
    path = db_path(app)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    try:
        con.set_authorizer(_deny_attach)
        con.row_factory = sqlite3.Row
        if body.get('script') is not None:
            con.executescript(str(body['script']))
            con.commit()
            return {'ok': True}
        sql = str(body.get('sql') or '').strip()
        if not sql:
            raise ValueError('sql 이 비었습니다')
        params = body.get('params') or []
        if not isinstance(params, (list, dict)):
            raise ValueError('params 는 배열이나 객체여야 합니다')
        cur = con.execute(sql, params)
        if cur.description:
            rows = cur.fetchmany(MAX_ROWS + 1)
            out = {'rows': [dict(r) for r in rows[:MAX_ROWS]]}
            if len(rows) > MAX_ROWS:
                out['truncated'] = True
            return out
        con.commit()
        return {'changes': cur.rowcount, 'last_id': cur.lastrowid}
    finally:
        con.close()


# ---------------------------------------------------------------- 서버

class AppHandler(BaseHTTPRequestHandler):
    server_version = 'apphost'
    port = PORT
    hub_origins = ()

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        # 바깥 주소로 못 붙는다 — 앱이 PC 자료를 밖으로 내보내지 못하게. 허브 화면만 미리보기로 품을 수 있다.
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; "
                         "connect-src 'self'; worker-src 'self' blob:; form-action 'self'; base-uri 'self'; "
                         "frame-ancestors 'self' " + ' '.join(self.hub_origins))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _app(self):
        """Host 머리글에서 앱 — '<id>.localhost:<port>' 가 아니면 None."""
        m = re.fullmatch(r'([a-z0-9-]+)\.localhost:(\d+)', (self.headers.get('Host') or '').lower())
        if not m or int(m.group(2)) != self.port:
            return None
        return find(m.group(1))

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        app = self._app()
        if not app:
            return self._send(403, '앱 주소(http://<앱>.localhost:%d/)로 여세요 — 허브 「✨ 앱」 탭에서'.encode('utf-8') % self.port,
                              'text/plain; charset=utf-8')
        path = unquote(urlparse(self.path).path)
        if path == '/_app.js':
            return self._send(200, APP_JS.encode('utf-8'), TYPES['.js'])
        if path == '/favicon.ico' and not os.path.isfile(os.path.join(app['dir'], 'favicon.ico')):
            return self._send(204, b'', TYPES['.ico'])
        m = re.fullmatch(r'/_lib/([\w\-.]+\.(js|css))', path)
        if m:                                         # 동봉 라이브러리 — apps-lib 바로 아래 js·css 만
            full = os.path.join(LIB, m.group(1))
            if not os.path.isfile(full):
                return self._send(404, b'not found', 'text/plain')
            with open(full, 'rb') as f:
                return self._send(200, f.read(), TYPES['.' + m.group(2)])
        if path.startswith('/_api/'):
            return self._send(405, {'error': 'POST 로 부르세요'})
        rel = path.lstrip('/') or 'index.html'
        if rel.endswith('/'):
            rel += 'index.html'
        parts = rel.split('/')
        if parts[0] in HIDDEN_DIRS or any(p in ('', '.', '..') or p.startswith('.') for p in parts):
            return self._send(404, b'not found', 'text/plain')
        root = os.path.realpath(app['dir'])
        full = os.path.realpath(os.path.join(root, *parts))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self._send(404, b'not found', 'text/plain')
        ext = os.path.splitext(full)[1].lower()
        if ext not in TYPES:
            return self._send(404, b'not found', 'text/plain')
        with open(full, 'rb') as f:
            return self._send(200, f.read(), TYPES[ext])

    def do_POST(self):
        app = self._app()
        if not app:
            return self._send(403, {'error': 'forbidden'})
        if self.headers.get('X-App') != '1':
            return self._send(403, {'error': 'X-App 머리글이 없습니다'})
        origin = self.headers.get('Origin')
        if origin and origin.lower() != 'http://' + (self.headers.get('Host') or '').lower():
            return self._send(403, {'error': 'bad origin'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if n > MAX_BODY:
                return self._send(413, {'error': '요청이 너무 큽니다'})
            body = json.loads(self.rfile.read(n) or b'{}')
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._send(400, {'error': 'bad json'})
        name = urlparse(self.path).path[len('/_api/'):] if self.path.startswith('/_api/') else ''
        ok = approved(app['id'], app)
        if name == 'info':
            return self._send(200, {'id': app['id'], 'name': app['name'], 'version': app['version'],
                                    'permissions': app['permissions'], 'approved': ok})
        if name not in PERMS:
            return self._send(404, {'error': '없는 기능입니다: %s' % name})
        if name not in app['permissions']:
            return self._send(403, {'error': "app.json permissions 에 '%s' 가 없습니다" % name})
        if name not in ok:
            return self._send(403, {'error': "'%s' 권한을 아직 허락하지 않았습니다 — 허브 「✨ 앱」 탭에서 허락하세요" % PERMS[name]})
        if name not in READY:
            return self._send(501, {'error': '%s 기능은 아직 준비 중입니다' % PERMS[name]})
        try:
            return self._send(200, run_sql(app, body))
        except (sqlite3.Error, ValueError) as e:
            return self._send(400, {'error': 'DB 오류: %s' % e})


def make_server(port=PORT, hub_port=8630):
    """127.0.0.1 에만. serve_forever 는 부르는 쪽이."""
    handler = type('BoundAppHandler', (AppHandler,), {
        'port': port, 'hub_origins': ('http://127.0.0.1:%d' % hub_port, 'http://localhost:%d' % hub_port)})
    srv = ThreadingHTTPServer(('127.0.0.1', port), handler)
    srv.daemon_threads = True
    handler.port = srv.server_address[1]          # port=0(시험)이면 실제로 잡힌 포트로 Host 를 확인
    return srv


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='나만의 앱 실행 환경 (보통은 허브가 띄운다)')
    ap.add_argument('--port', type=int, default=PORT)
    a = ap.parse_args()
    print('나만의 앱 —', ', '.join(url(i, a.port) for i in discover()) or '(앱 없음)')
    make_server(a.port).serve_forever()
