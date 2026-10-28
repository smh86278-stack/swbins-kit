# -*- coding: utf-8 -*-
"""GitHub 릴리스 올리기 — 설치 파일을 빌드하고 태그·릴리스·TaskhandSetup-<버전>.exe · Taskhand-<버전>-mac.zip 첨부까지.

    <PyInstaller 가 있는 파이썬> installer\\release.py v0.3.2 notes.md
    ... --no-build                        (installer\\dist 의 설치 파일을 그대로 올림)
    ... --site-packages <경로>            (build_installer.py 에 넘김 — 기본: tools\\macro-hub\\.venv\\Lib\\site-packages)
    ... --no-mac                          (맥 앱 없이 윈도우 설치 파일만)

- 먼저 VERSION 을 그 버전으로 고쳐 **커밋**해 둔다(빌드는 git archive HEAD — 커밋 안 한 것은 빠진다).
  태그와 VERSION 이 다르거나, 커밋 안 한 변경이 있거나, 태그가 이미 있으면 멈춘다.
- 맥 앱은 이 PC 에서 서명할 수 없어 CI(test.yml 의 mac-app 잡 — 맥에서 빌드·ad-hoc 서명·첫 열기 시험)가 만든 것을 받아 붙인다.
  main 을 먼저 push 하고 그 커밋의 CI 가 **모두 통과**할 때까지 기다린다 — 실패하면 태그·릴리스 없이 멈춘다.
- 올리기 전에 설치 시험(무인 설치 → 허브 8630 → uninstall.py --yes)을 손으로 한 번 하는 것을 권한다 — README 「설치」.
- 토큰은 `git credential fill`(GCM)에서 꺼내 이 프로세스 안에서만 쓴다 — 화면·파일에 남기지 않는다.
- 다 올리면 installer\\dist 에는 이번 설치 파일 하나만 남긴다.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DIST = os.path.join(HERE, 'dist')
DEFAULT_SP = os.path.join(ROOT, 'tools', 'macro-hub', '.venv', 'Lib', 'site-packages')


def git(*args, **kw):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True, **kw).stdout


def repo_name():
    url = git('remote', 'get-url', 'origin').strip()
    m = re.search(r'github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$', url)
    if not m:
        raise SystemExit('origin 이 GitHub 저장소가 아닙니다: ' + url)
    return m.group(1)


def token(owner):
    out = git('credential', 'fill', input='protocol=https\nhost=github.com\nusername=%s\n\n' % owner)
    pw = dict(l.split('=', 1) for l in out.splitlines() if '=' in l).get('password')
    if not pw:
        raise SystemExit('git 자격 증명에서 GitHub 토큰을 찾지 못했습니다')
    return pw


def api(url, tok, data=None, ctype=None):
    h = {'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if ctype:
        h['Content-Type'] = ctype
    req = urllib.request.Request(url, data=data, headers=h, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise SystemExit('GitHub HTTP %s: %s' % (e.code, e.read().decode('utf-8', 'replace')[:300]))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def download(url, tok):
    """GitHub 의 내려받기(아티팩트) — 저장소로 넘겨주는 주소엔 토큰을 붙이지 않는다(붙이면 401)."""
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=600) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise SystemExit('GitHub HTTP %s: 내려받기 실패 %s' % (e.code, url))
        with urllib.request.urlopen(e.headers['Location'], timeout=600) as r:
            return r.read()


def wait_ci(repo, sha, tok, minutes=40, log=print):
    """그 커밋의 push CI(test.yml)가 끝나길 기다린다. 성공이면 run, 실패·시간 초과면 SystemExit."""
    end = time.time() + minutes * 60
    while time.time() < end:
        runs = api('https://api.github.com/repos/%s/actions/runs?head_sha=%s&event=push' % (repo, sha), tok)['workflow_runs']
        runs = [r for r in runs if r.get('path', '').endswith('test.yml')]
        if runs and runs[0]['status'] == 'completed':
            if runs[0]['conclusion'] != 'success':
                raise SystemExit('CI 가 실패했습니다(%s) — 고친 뒤 다시: %s' % (runs[0]['conclusion'], runs[0]['html_url']))
            return runs[0]
        log('CI 기다리는 중…' + (' ' + runs[0]['status'] if runs else ' (아직 시작 전)'))
        time.sleep(30)
    raise SystemExit('CI 가 %d분 안에 끝나지 않았습니다 — --no-mac 으로 윈도우만 올리거나 나중에 다시' % minutes)


def mac_zip(repo, run, tok, ver):
    """CI 아티팩트 Taskhand-mac(zip 안의 zip)에서 Taskhand-mac.zip 을 꺼내 dist/Taskhand-<버전>-mac.zip 로."""
    arts = api('https://api.github.com/repos/%s/actions/runs/%s/artifacts' % (repo, run['id']), tok)['artifacts']
    art = next((a for a in arts if a['name'] == 'Taskhand-mac' and not a.get('expired')), None)
    if not art:
        raise SystemExit('CI 에 Taskhand-mac 아티팩트가 없습니다: ' + run['html_url'])
    with zipfile.ZipFile(io.BytesIO(download(art['archive_download_url'], tok))) as z:
        inner = z.read('Taskhand-mac.zip')
    with zipfile.ZipFile(io.BytesIO(inner)) as z:                 # 앱 안 버전이 맞는지
        plist = z.read('Taskhand.app/Contents/Info.plist').decode('utf-8', 'replace')
    if '<string>%s</string>' % ver not in plist:
        raise SystemExit('CI 의 맥 앱 버전이 %s 가 아닙니다 — VERSION 커밋을 push 했는지 보세요' % ver)
    out = os.path.join(DIST, 'Taskhand-%s-mac.zip' % ver)
    os.makedirs(DIST, exist_ok=True)
    with open(out, 'wb') as f:
        f.write(inner)
    return out


def upload(rel, path, tok, ctype='application/octet-stream'):
    with open(path, 'rb') as f:
        return api(rel['upload_url'].split('{')[0] + '?name=' + os.path.basename(path), tok, f.read(), ctype)


def check(tag):
    """올리기 전 검사 — 문제가 있으면 SystemExit. 통과하면 버전 문자열."""
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag or ''):
        raise SystemExit(__doc__)
    ver = tag[1:]
    with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
        now = f.read().strip()
    if now != ver:
        raise SystemExit('VERSION 이 %s 입니다 — %s 로 고쳐 커밋한 뒤 다시 하세요' % (now, ver))
    if git('status', '--porcelain', '--untracked-files=no').strip():
        raise SystemExit('커밋 안 한 변경이 있습니다 — 먼저 커밋하세요(설치 파일엔 커밋된 것만 들어간다)')
    if tag in git('tag', '--list', tag).split():
        raise SystemExit('태그가 이미 있습니다: ' + tag)
    return ver


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    tag, notes = argv[0], argv[1]
    ver = check(tag)
    with open(notes, encoding='utf-8') as f:
        body = f.read()
    exe = os.path.join(DIST, 'TaskhandSetup-%s.exe' % ver)
    if '--no-build' not in argv:
        sp = argv[argv.index('--site-packages') + 1] if '--site-packages' in argv else DEFAULT_SP
        subprocess.run([sys.executable, '-X', 'utf8', os.path.join(HERE, 'build_installer.py'), '--site-packages', sp],
                       cwd=ROOT, check=True)
    if not os.path.isfile(exe):
        raise SystemExit('설치 파일이 없습니다: ' + exe)
    repo = repo_name()
    tok = token(repo.split('/')[0])
    git('push', 'origin', 'main')
    mac = None
    if '--no-mac' not in argv:
        run = wait_ci(repo, git('rev-parse', 'HEAD').strip(), tok)
        mac = mac_zip(repo, run, tok, ver)
    git('tag', '-a', tag, '-m', 'Taskhand ' + tag)
    git('push', 'origin', tag)
    rel = api('https://api.github.com/repos/%s/releases' % repo, tok,
              json.dumps({'tag_name': tag, 'name': 'Taskhand ' + tag, 'body': body}, ensure_ascii=False).encode('utf-8'),
              'application/json; charset=utf-8')
    assets = [upload(rel, exe, tok)] + ([upload(rel, mac, tok, 'application/zip')] if mac else [])
    keep = {os.path.normcase(p) for p in (exe, mac) if p}
    for old in (glob.glob(os.path.join(DIST, 'TaskhandSetup-*.exe')) + glob.glob(os.path.join(DIST, 'WorkKitSetup-*.exe'))
                + glob.glob(os.path.join(DIST, 'Taskhand-*-mac.zip'))):
        if os.path.normcase(old) not in keep:
            os.remove(old)                                # dist 엔 최신 하나씩만
    print('릴리스:', rel['html_url'])
    for a in assets:
        print('첨부:', a['name'], a['size'], a['state'])


if __name__ == '__main__':
    main(sys.argv[1:])
