# -*- coding: utf-8 -*-
"""✨ 나만의 앱 검사 — 진짜 브라우저(Playwright)로 앱을 열어 콘솔 오류·검사 시나리오·스크린샷을 본다.

    "<허브 파이썬>" appcheck.py <앱 id> [--headed] [--channel chrome|msedge]

- 허브의 앱 서버를 쓰지 않고 **자기 서버를 임시로**(port 0) 띄운다. 데이터·권한도 임시 폴더 —
  사람의 앱 데이터는 건드리지 않고, 앱이 요청한 권한 중 동작하는 것(db 등)은 검사 동안만 허락한 것으로 본다.
- 정적 검사: app.json · index.html · 바깥 주소(http/https — CSP 로 막힐 것) · tests\\smoke.json 형식.
- 브라우저: 콘솔 error · 잡히지 않은 예외 · 자기 출처의 4xx/5xx 요청(파비콘 빼고) · CSP 위반을 모은다.
- tests\\smoke.json 의 steps 를 차례로: fill · press · click · expect_text · expect(+count_at_least) · eval · wait.
- 스크린샷은 앱 폴더의 .check\\check.png (점으로 시작하는 폴더라 앱 주소로는 안 보인다).
마지막 줄 '🔍 검사 결과: 성공|실패', 종료 코드 0|1.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apphost  # noqa: E402

STEP_TIMEOUT = 5000
EXTERNAL = re.compile(r'''(?:src|href)\s*=\s*["'](https?://(?!localhost|127\.0\.0\.1)[^"']+)|(?:import|from)\s*\(?\s*["'](https?://[^"']+)|fetch\(\s*["'](https?://(?!localhost|127\.0\.0\.1)[^"']+)''')


def log(*a):
    print(*a, flush=True)


def static_check(app):
    """파일만 보고 찾는 문제 — [(수준, 말)]."""
    out = []
    if app['error']:
        out.append(('error', app['error']))
    for root, dirs, files in os.walk(app['dir']):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'node_modules']
        for name in files:
            if not name.endswith(('.html', '.js', '.mjs', '.css')):
                continue
            path = os.path.join(root, name)
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read()
            for m in EXTERNAL.finditer(text):
                url = next(g for g in m.groups() if g)
                out.append(('error', '%s: 바깥 주소 %s — 이 환경에선 막힌다(동봉 /_lib/ 를 쓰거나 파일로 넣기)'
                            % (os.path.relpath(path, app['dir']), url[:80])))
    smoke = os.path.join(app['dir'], 'tests', 'smoke.json')
    if os.path.isfile(smoke):
        try:
            with open(smoke, encoding='utf-8-sig') as f:
                steps = json.load(f).get('steps')
            if not isinstance(steps, list):
                out.append(('error', 'tests/smoke.json 에 steps 목록이 없습니다'))
        except ValueError as e:
            out.append(('error', 'tests/smoke.json 이 JSON 이 아닙니다: %s' % e))
    else:
        out.append(('warn', 'tests/smoke.json 이 없어 화면이 뜨는지만 봅니다'))
    return out


def load_steps(app):
    try:
        with open(os.path.join(app['dir'], 'tests', 'smoke.json'), encoding='utf-8-sig') as f:
            steps = json.load(f).get('steps') or []
        return steps if isinstance(steps, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def run_step(page, step):
    """한 단계 — 실패하면 AssertionError(사람이 읽을 말)."""
    t = STEP_TIMEOUT
    if 'fill' in step:
        page.locator(step['fill']).first.fill(str(step.get('value', '')), timeout=t)
        return '입력 %s ← %s' % (step['fill'], str(step.get('value', ''))[:30].replace('\n', '⏎'))
    if 'press' in step:
        page.locator(step['press']).first.press(step.get('key', 'Enter'), timeout=t)
        return '키 %s @ %s' % (step.get('key', 'Enter'), step['press'])
    if 'click' in step:
        page.locator(step['click']).first.click(timeout=t)
        return '누름 %s' % step['click']
    if 'expect_text' in step:
        loc = page.get_by_text(str(step['expect_text']), exact=False).first
        try:
            loc.wait_for(state='visible', timeout=t)
        except Exception:
            raise AssertionError("'%s' 글자가 화면에 없습니다" % step['expect_text'])
        return "보임 '%s'" % step['expect_text']
    if 'expect' in step:
        loc = page.locator(step['expect'])
        need = int(step.get('count_at_least', 1))
        deadline = time.time() + t / 1000
        while loc.count() < need and time.time() < deadline:
            page.wait_for_timeout(100)
        if loc.count() < need:
            raise AssertionError('%s 가 %d개 이상이어야 하는데 %d개' % (step['expect'], need, loc.count()))
        return '있음 %s (%d개)' % (step['expect'], loc.count())
    if 'eval' in step:
        deadline = time.time() + t / 1000
        ok = False
        while time.time() < deadline:
            try:
                ok = bool(page.evaluate('() => (%s)' % step['eval']))
            except Exception:
                ok = False
            if ok:
                break
            page.wait_for_timeout(150)
        if not ok:
            raise AssertionError('식이 참이 아닙니다: %s' % step['eval'][:120])
        return '참 %s' % step['eval'][:60]
    if 'wait' in step:
        page.wait_for_timeout(int(step['wait']))
        return '기다림 %sms' % step['wait']
    raise AssertionError('모르는 단계입니다: %s' % json.dumps(step, ensure_ascii=False)[:100])


def browser_check(app, headed=False, channel=''):
    """(문제 목록, 단계 로그) — 임시 서버·임시 데이터로 연다."""
    from playwright.sync_api import sync_playwright
    tmp = tempfile.mkdtemp(prefix='appcheck-')
    saved = (apphost.STATE, apphost.DATA)
    apphost.STATE, apphost.DATA = os.path.join(tmp, 'apps.json'), os.path.join(tmp, 'data')
    apphost.approve(app['id'], [p for p in app['permissions'] if p in apphost.READY])
    srv = apphost.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = apphost.url(app['id'], srv.server_address[1])
    problems, steps_log = [], []
    try:
        with sync_playwright() as p:
            browser = None
            for ch in ([channel] if channel else ['chrome', 'msedge', '']):
                try:
                    browser = p.chromium.launch(channel=ch or None, headless=not headed)
                    break
                except Exception:
                    continue
            if not browser:
                return [('error', '브라우저를 띄우지 못했습니다(Chrome·Edge 없음 — playwright install chromium)')], []
            page = browser.new_page(viewport={'width': 1280, 'height': 800})
            origin = url.rstrip('/')

            def on_console(m):
                if m.type == 'error':
                    problems.append(('error', '콘솔 오류: %s' % m.text[:300]))

            def on_response(r):
                if r.url.startswith(origin) and r.status >= 400 and not r.url.endswith('/favicon.ico'):
                    problems.append(('error', '요청 실패 %d %s' % (r.status, r.url[len(origin):][:120])))

            page.on('console', on_console)
            page.on('pageerror', lambda e: problems.append(('error', '잡히지 않은 오류: %s' % str(e)[:300])))
            page.on('response', on_response)
            try:
                page.goto(url, wait_until='load', timeout=15000)
                page.wait_for_timeout(500)
                steps_log.append('✔ 열림 %s — 제목 「%s」' % (url, page.title()))
            except Exception as e:
                problems.append(('error', '앱을 열지 못했습니다: %s' % str(e).splitlines()[0]))
            else:
                for i, step in enumerate(load_steps(app), 1):
                    try:
                        steps_log.append('✔ %d. %s' % (i, run_step(page, step)))
                    except AssertionError as e:
                        problems.append(('error', '%d단계 실패: %s' % (i, e)))
                        steps_log.append('✖ %d. %s' % (i, e))
                        break
                    except Exception as e:
                        msg = str(e).splitlines()[0][:200]
                        problems.append(('error', '%d단계 실패: %s' % (i, msg)))
                        steps_log.append('✖ %d. %s' % (i, msg))
                        break
                page.wait_for_timeout(300)
            shot_dir = os.path.join(app['dir'], '.check')
            os.makedirs(shot_dir, exist_ok=True)
            try:
                page.screenshot(path=os.path.join(shot_dir, 'check.png'), full_page=True)
                steps_log.append('📷 스크린샷 %s' % os.path.join(shot_dir, 'check.png'))
            except Exception as e:
                steps_log.append('📷 스크린샷 실패: %s' % str(e).splitlines()[0])
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        apphost.STATE, apphost.DATA = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return problems, steps_log


def check(app_id, headed=False, channel=''):
    app = apphost.find(app_id)
    if not app:
        log('✖ 없는 앱입니다: %s (apps.local\\<id> 에 app.json·index.html)' % app_id)
        return 1
    log('🔍 %s (%s) 검사 — %s' % (app['name'], app_id, app['dir']))
    problems = static_check(app)
    if not any(lv == 'error' for lv, _ in problems):
        more, steps = browser_check(app, headed, channel)
        for line in steps:
            log('  ' + line)
        problems += more
    seen = set()
    for lv, msg in problems:
        if msg not in seen:
            seen.add(msg)
            log(('  ✖ ' if lv == 'error' else '  ⚠ ') + msg)
    ok = not any(lv == 'error' for lv, _ in problems)
    log('🔍 검사 결과: %s' % ('성공' if ok else '실패 — 위 ✖ 를 고치세요'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description='나만의 앱 검사(진짜 브라우저)')
    ap.add_argument('app_id')
    ap.add_argument('--headed', action='store_true', help='브라우저 창을 보이게')
    ap.add_argument('--channel', default='', help='chrome · msedge (비면 있는 것)')
    a = ap.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    return check(a.app_id, a.headed, a.channel)


if __name__ == '__main__':
    sys.exit(main())
