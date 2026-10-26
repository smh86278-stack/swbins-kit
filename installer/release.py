# -*- coding: utf-8 -*-
"""GitHub 릴리스 올리기 — 설치 파일을 빌드하고 태그·릴리스·TaskhandSetup-<버전>.exe 첨부까지.

    <PyInstaller 가 있는 파이썬> installer\\release.py v0.3.2 notes.md
    ... --no-build                        (installer\\dist 의 설치 파일을 그대로 올림)
    ... --site-packages <경로>            (build_installer.py 에 넘김 — 기본: tools\\macro-hub\\.venv\\Lib\\site-packages)

- 먼저 VERSION 을 그 버전으로 고쳐 **커밋**해 둔다(빌드는 git archive HEAD — 커밋 안 한 것은 빠진다).
  태그와 VERSION 이 다르거나, 커밋 안 한 변경이 있거나, 태그가 이미 있으면 멈춘다.
- 올리기 전에 설치 시험(무인 설치 → 허브 8630 → uninstall.py --yes)을 손으로 한 번 하는 것을 권한다 — README 「설치」.
- 토큰은 `git credential fill`(GCM)에서 꺼내 이 프로세스 안에서만 쓴다 — 화면·파일에 남기지 않는다.
- 다 올리면 installer\\dist 에는 이번 설치 파일 하나만 남긴다.
"""
import glob
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

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
    git('tag', '-a', tag, '-m', 'Taskhand ' + tag)
    git('push', 'origin', 'main')
    git('push', 'origin', tag)
    tok = token(repo.split('/')[0])
    rel = api('https://api.github.com/repos/%s/releases' % repo, tok,
              json.dumps({'tag_name': tag, 'name': 'Taskhand ' + tag, 'body': body}, ensure_ascii=False).encode('utf-8'),
              'application/json; charset=utf-8')
    with open(exe, 'rb') as f:
        asset = api(rel['upload_url'].split('{')[0] + '?name=' + os.path.basename(exe), tok, f.read(), 'application/octet-stream')
    for old in glob.glob(os.path.join(DIST, 'TaskhandSetup-*.exe')) + glob.glob(os.path.join(DIST, 'WorkKitSetup-*.exe')):
        if os.path.normcase(old) != os.path.normcase(exe):
            os.remove(old)                                # dist 엔 최신 하나만
    print('릴리스:', rel['html_url'])
    print('첨부:', asset['name'], asset['size'], asset['state'])


if __name__ == '__main__':
    main(sys.argv[1:])
