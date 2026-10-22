# -*- coding: utf-8 -*-
"""✨ 나만의 앱 내보내기·가져오기 — 표준 라이브러리만.

  zip        앱 폴더 그대로(점 폴더 빼고) — 다른 PC 의 키트에서 「가져오기」로 다시 앱이 된다.
  HTML 한 장  허브 없이 브라우저만으로 도는 파일 하나 — 더블클릭으로 연다.
             - JS 모듈은 import map + data: 주소로 한 파일에 담는다(빌드 도구 없이). /_lib 동봉 라이브러리도.
             - css·그림은 안에 넣는다(<link> → <style>, 그림 → data:).
             - /_app.js 대신 혼자 도는 도우미: app.db 는 sql.js(SQLite 를 브라우저에서, wasm 도 안에) + IndexedDB 에 저장,
               app.files 는 IndexedDB. app.ai·run·notify 는 허브가 있어야 해서 '허브에서만' 오류로 답한다.
  exe        HTML 한 장을 품은 작은 실행 파일 — Windows 에 늘 있는 C# 컴파일러(.NET Framework csc.exe)로 만든다.
             누르면 %LOCALAPPDATA%\\MyApps\\<id>\\ 에 HTML 을 풀고 Edge 앱 창(--app, 앱 전용 프로필)으로 연다(Edge 없으면 기본 브라우저).
             서명이 없어 처음엔 SmartScreen 이 물을 수 있다.
  가져오기    zip → apps.local\\<id>\\ — 경로 탈출·허용 안 된 파일·너무 큰 것은 막는다. 권한은 다시 허락해야 한다.
"""
import base64
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile

import apphistory
import apphost

IMPORT_MAX = 30 * 1024 * 1024
IMPORT_EXTS = ('.html', '.js', '.mjs', '.css', '.json', '.md', '.txt', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp',
               '.ico', '.mp3', '.ogg', '.wav', '.mp4', '.woff', '.woff2', '.ttf', '.wasm')
MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
        '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav',
        '.mp4': 'video/mp4', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.json': 'application/json'}
CSC = [os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Microsoft.NET', d, 'v4.0.30319', 'csc.exe')
       for d in ('Framework64', 'Framework')]
SCHEME = 'app:///'          # import map 의 열쇠 — 앱 안 파일은 app:///src/main.js, 동봉 라이브러리는 app:///_lib/…
IMPORT_RE = re.compile(r'''(\bimport\s*\(\s*|\bfrom\s*|\bimport\s+)(['"])([^'"\n]+)\2''')


# ---------------------------------------------------------------- zip

def export_zip(app):
    return '%s-%s.zip' % (app['id'], app['version']), apphistory.export_zip(app['dir'])


def import_zip(data, app_id, name=''):
    """zip bytes → apps.local\\<app_id>. 폴더 하나로 싸여 있으면 벗긴다. 만든 앱 정보."""
    app_id = (app_id or '').strip().lower()
    if not apphost.ID_RE.fullmatch(app_id):
        raise ValueError('앱 주소 이름은 영문 소문자·숫자·하이픈(-)으로 (예: clients)')
    if apphost.find(app_id):
        raise ValueError('이미 있는 앱 이름입니다: %s' % app_id)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError('zip 파일이 아닙니다')
    entries = [i for i in z.infolist() if not i.is_dir()]
    if sum(i.file_size for i in entries) > IMPORT_MAX:
        raise ValueError('풀면 %dMB 가 넘습니다' % (IMPORT_MAX // 1024 // 1024))
    names = [i.filename.replace('\\', '/') for i in entries]
    tops = {n.split('/', 1)[0] for n in names}
    strip = next(iter(tops)) + '/' if len(tops) == 1 and all('/' in n for n in names) else ''
    files = {}
    for info, n in zip(entries, names):
        rel = n[len(strip):]
        parts = rel.split('/')
        if not rel or any(p in ('', '.', '..') or p.startswith('.') for p in parts) or ':' in rel:
            continue                                   # 경로 탈출·숨김(.history 등)은 버린다
        if not rel.lower().endswith(IMPORT_EXTS):
            raise ValueError('앱에 넣을 수 없는 파일입니다: %s' % rel[:80])
        files[rel] = z.read(info)
    if 'app.json' not in files or 'index.html' not in files:
        raise ValueError('app.json · index.html 이 있는 앱 zip 이 아닙니다')
    dst = os.path.join(apphost.DIR_LOCAL, app_id)
    root = os.path.realpath(dst)
    for rel, body in files.items():
        full = os.path.realpath(os.path.join(root, *rel.split('/')))
        if not full.startswith(root + os.sep):
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as f:
            f.write(body)
    if name:
        mf = os.path.join(dst, 'app.json')
        m = apphost._read_json(mf, {})
        m['name'] = name.strip()[:60]
        with open(mf, 'w', encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    return apphost.find(app_id)


# ---------------------------------------------------------------- HTML 한 장

STANDALONE_JS = r'''// 나만의 앱 — 허브 없이 도는 도우미(HTML 한 장 내보내기). db 는 sql.js + IndexedDB, files 는 IndexedDB.
(function () {
  const APP = %(meta)s;
  const KEY = 'myapp:' + APP.id;
  const idb = new Promise((ok, no) => {
    const r = indexedDB.open(KEY, 1);
    r.onupgradeneeded = () => { r.result.createObjectStore('kv'); r.result.createObjectStore('files'); };
    r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error);
  });
  const tx = (store, mode, fn) => idb.then((d) => new Promise((ok, no) => {
    const t = d.transaction(store, mode), s = t.objectStore(store), req = fn(s);
    t.oncomplete = () => ok(req && req.result); t.onerror = () => no(t.error);
  }));
  let dbReady = null, saveTimer = null;
  function sql() {
    if (!dbReady) {
      if (typeof initSqlJs !== 'function') return Promise.reject(new Error("이 앱은 'db' 권한이 없습니다"));
      const wasm = Uint8Array.from(atob(window.__SQL_WASM__), (c) => c.charCodeAt(0));
      dbReady = Promise.all([initSqlJs({ wasmBinary: wasm }), tx('kv', 'readonly', (s) => s.get('db'))])
        .then(([SQL, bytes]) => new SQL.Database(bytes ? new Uint8Array(bytes) : undefined));
    }
    return dbReady;
  }
  function save(db) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => tx('kv', 'readwrite', (s) => s.put(db.export(), 'db')), 150);
  }
  window.addEventListener('beforeunload', () => { if (saveTimer && dbReady) dbReady.then((db) => tx('kv', 'readwrite', (s) => s.put(db.export(), 'db'))); });
  const offline = (what) => () => Promise.reject(new Error(what + ' 기능은 허브에서 연 앱에서만 됩니다(이 파일은 허브 없이 도는 내보내기본)'));
  const fail = (e) => { throw new Error('DB 오류: ' + (e && e.message || e)); };
  window.app = {
    standalone: true,
    info: async () => ({ id: APP.id, name: APP.name, version: APP.version, permissions: APP.permissions, approved: APP.permissions }),
    db: async (q, params) => {
      const db = await sql();
      try {
        const st = db.prepare(q);
        if (params && (Array.isArray(params) ? params.length : Object.keys(params).length)) st.bind(params);
        if (st.getColumnNames().length) {
          const rows = [];
          while (st.step()) rows.push(st.getAsObject());
          st.free();
          return { rows };
        }
        st.step(); st.free();
        const changes = db.getRowsModified();
        const last = db.exec('SELECT last_insert_rowid() AS id')[0];
        save(db);
        return { changes, last_id: last ? last.values[0][0] : null };
      } catch (e) { fail(e); }
    },
    dbScript: async (q) => { const db = await sql(); try { db.exec(q); save(db); return { ok: true }; } catch (e) { fail(e); } },
    files: {
      list: async () => {
        const keys = await tx('files', 'readonly', (s) => s.getAllKeys());
        return { files: (keys || []).map((k) => ({ path: k, size: 0, modified: '' })) };
      },
      read: async (path, opts) => {
        const v = await tx('files', 'readonly', (s) => s.get(path));
        if (v == null) throw new Error('없는 파일입니다: ' + path);
        return { data: opts && opts.base64 ? v.b64 : (v.text != null ? v.text : atob(v.b64)) };
      },
      write: async (path, data, opts) => { await tx('files', 'readwrite', (s) => s.put(opts && opts.base64 ? { b64: data } : { text: data }, path)); return { ok: true }; },
      remove: async (path) => { await tx('files', 'readwrite', (s) => s.delete(path)); return { ok: true }; },
    },
    ai: offline('AI 부탁'), run: offline('자동화 실행'), runStatus: offline('자동화 실행'), notify: offline('알림'),
  };
})();
'''


def _resolve(base_rel, spec):
    """모듈 안 import 주소 → 앱 기준 경로('src/db.js' · '_lib/preact-htm.js'). 바깥 주소면 None."""
    if spec.startswith(('http://', 'https://', 'data:', SCHEME)):
        return None
    if spec.startswith('/'):
        path = spec.lstrip('/')
    else:
        path = posixpath.normpath(posixpath.join(posixpath.dirname(base_rel), spec))
    return None if path.startswith('..') else path


class Bundle:
    def __init__(self, app):
        self.app = app
        self.files = apphistory.files(app['dir'])           # {rel: bytes}
        self.modules = {}                                  # rel → data: 주소
        self.missing = []

    def read(self, rel):
        if rel.startswith('_lib/'):
            path = os.path.join(apphost.LIB, rel[5:])
            if os.path.isfile(path) and '/' not in rel[5:]:
                with open(path, 'rb') as f:
                    return f.read()
            return None
        return self.files.get(rel)

    def rewrite(self, code, base_rel):
        """import 주소를 app:/// 열쇠로 바꾸고, 걸린 모듈을 차례로 담는다."""
        def sub(m):
            rel = _resolve(base_rel, m.group(3))
            if rel is None:
                return m.group(0)
            self.module(rel)
            return '%s%s%s%s%s' % (m.group(1), m.group(2), SCHEME, rel, m.group(2))
        return IMPORT_RE.sub(sub, code)

    def module(self, rel):
        if rel in self.modules:
            return
        self.modules[rel] = ''                             # 순환 import 에서 다시 들어오지 않게 먼저 자리를 잡는다
        raw = self.read(rel)
        if raw is None:
            self.missing.append(rel)
            return
        code = self.rewrite(raw.decode('utf-8', 'replace'), rel)
        self.modules[rel] = 'data:text/javascript;base64,' + base64.b64encode(code.encode('utf-8')).decode('ascii')

    def data_url(self, rel):
        raw = self.read(rel)
        if raw is None:
            self.missing.append(rel)
            return None
        mime = MIME.get(os.path.splitext(rel)[1].lower(), 'application/octet-stream')
        return 'data:%s;base64,%s' % (mime, base64.b64encode(raw).decode('ascii'))

    def css(self, text, base_rel):
        def sub(m):
            spec = m.group(2)
            rel = _resolve(base_rel, spec) if not spec.startswith(('data:', 'http', '#')) else None
            url = self.data_url(rel) if rel else None
            return 'url("%s")' % url if url else m.group(0)
        return re.sub(r'''url\(\s*(['"]?)([^'")]+)\1\s*\)''', sub, text)


def _script_safe(code):
    return code.replace('</script', '<\\/script').replace('<!--', '<\\!--')


def export_html(app):
    """(파일 이름, HTML 글) — 허브 없이 도는 한 장."""
    b = Bundle(app)
    html = b.files.get('index.html', b'').decode('utf-8', 'replace')
    if not html:
        raise ValueError('index.html 이 없습니다')
    head_inject = []
    meta = json.dumps({'id': app['id'], 'name': app['name'], 'version': app['version'], 'permissions': app['permissions']},
                      ensure_ascii=False)
    if 'db' in app['permissions']:
        with open(os.path.join(apphost.LIB, 'sql-wasm.js'), encoding='utf-8') as f:
            head_inject.append('<script>%s</script>' % _script_safe(f.read()))
        with open(os.path.join(apphost.LIB, 'sql-wasm.wasm'), 'rb') as f:
            head_inject.append('<script>window.__SQL_WASM__="%s";</script>' % base64.b64encode(f.read()).decode('ascii'))
    standalone = '<script>%s</script>' % _script_safe(STANDALONE_JS % {'meta': meta})

    def classic(m):
        src = m.group(2)
        if src in ('/_app.js', '_app.js'):
            return standalone
        rel = _resolve('index.html', src)
        raw = b.read(rel) if rel else None
        if raw is None:
            if rel:
                b.missing.append(rel)
            return m.group(0)
        return '<script%s>%s</script>' % (m.group(1).replace(' defer', ''), _script_safe(raw.decode('utf-8', 'replace')))

    def module_tag(m):
        rel = _resolve('index.html', m.group(2))
        if rel is None:
            return m.group(0)
        b.module(rel)
        return '<script type="module">import "%s%s";</script>' % (SCHEME, rel)

    def inline_module(m):
        return '<script type="module"%s>%s</script>' % (m.group(1), b.rewrite(m.group(2), 'index.html'))

    def link(m):
        rel = _resolve('index.html', m.group(1))
        raw = b.read(rel) if rel else None
        if raw is None:
            return m.group(0)
        return '<style>%s</style>' % b.css(raw.decode('utf-8', 'replace'), rel)

    def attr(m):
        spec = m.group(3)
        if spec.startswith(('http', 'data:', '#', 'javascript:', 'mailto:')) or spec.endswith(('.html', '.js', '.css')):
            return m.group(0)
        rel = _resolve('index.html', spec)
        url = b.data_url(rel) if rel and rel in b.files else None
        return '%s=%s%s%s' % (m.group(1), m.group(2), url, m.group(2)) if url else m.group(0)

    html = re.sub(r'<script\s+type=["\']module["\']\s+src=(["\'])([^"\']+)\1[^>]*>\s*</script>', module_tag, html, flags=re.I)
    html = re.sub(r'<script((?:\s+(?!src)[\w-]+(?:=["\'][^"\']*["\'])?)*)\s+src=(?:["\'])([^"\']+)["\'][^>]*>\s*</script>',
                  classic, html, flags=re.I)
    html = re.sub(r'<script\s+type=["\']module["\']([^>]*)>(.*?)</script>', inline_module, html, flags=re.I | re.S)
    html = re.sub(r'<link\s+rel=["\']stylesheet["\']\s+href=["\']([^"\']+)["\'][^>]*>', link, html, flags=re.I)
    html = re.sub(r'<style>(.*?)</style>', lambda m: '<style>%s</style>' % b.css(m.group(1), 'index.html'), html, flags=re.S)
    html = re.sub(r'\b(src|href)=(["\'])([^"\']+)\2', attr, html)
    if b.missing:
        raise ValueError('찾지 못한 파일이 있어 묶지 못했습니다: %s' % ', '.join(sorted(set(b.missing)))[:300])
    importmap = '<script type="importmap">%s</script>' % json.dumps(
        {'imports': {SCHEME + rel: url for rel, url in b.modules.items()}})
    stamp = ('<!-- 나만의 앱 「%s」 v%s — 허브 없이 도는 내보내기본(키트 apppack). 데이터는 이 브라우저(IndexedDB)에 저장된다. -->'
             % (app['name'].replace('--', '－'), app['version']))
    inject = '\n'.join([importmap] + head_inject)
    if re.search(r'<head[^>]*>', html, flags=re.I):
        html = re.sub(r'(<head[^>]*>)', lambda m: m.group(1) + '\n' + inject, html, count=1, flags=re.I)
    else:
        html = inject + html
    return '%s-%s.html' % (app['id'], app['version']), stamp + '\n' + html


# ---------------------------------------------------------------- exe (csc)

LAUNCHER_CS = r'''using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
[assembly: AssemblyTitle("%(title)s")]
[assembly: AssemblyProduct("%(title)s")]
[assembly: AssemblyVersion("%(version)s")]
class Launcher {
  [STAThread]
  static void Main() {
    string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MyApps", "%(id)s");
    Directory.CreateDirectory(dir);
    string html = Path.Combine(dir, "index.html");
    using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.html"))
    using (FileStream f = File.Create(html)) { s.CopyTo(f); }
    string url = new Uri(html).AbsoluteUri;
    string[] edges = { @"%%ProgramFiles(x86)%%\Microsoft\Edge\Application\msedge.exe", @"%%ProgramFiles%%\Microsoft\Edge\Application\msedge.exe" };
    foreach (string e in edges) {
      string p = Environment.ExpandEnvironmentVariables(e);
      if (File.Exists(p)) {
        Process.Start(p, "--app=\"" + url + "\" --user-data-dir=\"" + Path.Combine(dir, "profile") + "\" --no-first-run");
        return;
      }
    }
    Process.Start(url);
  }
}
'''


def csc_path():
    return next((p for p in CSC if os.path.isfile(p)), None)


def export_exe(app, out_dir):
    """HTML 한 장을 품은 실행 파일을 out_dir 에 만든다 — 만든 파일 경로."""
    csc = csc_path()
    if not csc:
        raise RuntimeError('이 PC 에 .NET Framework 의 C# 컴파일러(csc.exe)가 없어 exe 를 만들 수 없습니다 — HTML 한 장으로 내보내세요')
    _, html = export_html(app)
    work = tempfile.mkdtemp(prefix='appexe-')
    try:
        with open(os.path.join(work, 'app.html'), 'w', encoding='utf-8') as f:
            f.write(html)
        ver = re.sub(r'[^0-9.]', '', app['version']) or '0.1.0'
        ver = '.'.join((ver.split('.') + ['0', '0', '0'])[:4])
        title = re.sub(r'["\\\r\n]', '', app['name'])
        with open(os.path.join(work, 'launcher.cs'), 'w', encoding='utf-8') as f:
            f.write(LAUNCHER_CS % {'id': app['id'], 'title': title, 'version': ver})
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, '%s.exe' % app['id'])
        p = subprocess.run([csc, '/nologo', '/target:winexe', '/optimize+', '/utf8output', '/codepage:65001',
                            '/out:' + out, '/resource:app.html,app.html', 'launcher.cs'],
                           cwd=work, capture_output=True, timeout=120,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if p.returncode != 0:
            raise RuntimeError('exe 를 만들지 못했습니다: %s' % (p.stdout + p.stderr).decode('utf-8', 'replace')[-800:])
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
