# -*- coding: utf-8 -*-
"""정기 예약 메일 — config.local.json 의 scheduled_mails 항목을 정해진 요일·시각에 보낸다.

항목: {name, at 'HH:MM', days, to, cc, bcc, subject, body, attachments, enabled}
- 제목·본문·첨부 경로의 {date}·{prev_month}·{company} 같은 자리표시는 kit.render 가 채운다.
- 첨부 파일이 없으면 그 항목만 실패한다(빈 메일이 나가는 것보다 낫다). 나머지 항목은 계속 보낸다.
- 보낸 직후 바로 상태 파일에 적는다 — 다음 항목에서 죽어도 같은 메일이 두 번 나가지 않게.
- 실패한 항목은 RETRY_MIN 분 뒤에 다시 시도한다(매분 SMTP 를 두드리지 않게). 시각이 grace(3시간)를 넘기면 그날은 포기.
"""
import datetime
import os
import time

import kit

FEATURE = 'scheduled_mail'
RETRY_MIN = 10

META = {
    "name": "정기 예약 메일",
    "desc": "설정(scheduled_mails)에 적힌 메일을 정해진 요일·시각에 보낸다. 실패하면 10분 뒤 다시 시도.",
    "kind": "ctx",
    "target": "desktop",
    "motion": "mail",
    "triggers": [{"type": "schedule", "every": "1m"}],
    "timeout": 300,
    "cooldown": 20,
}


def item_key(item):
    """상태 파일의 열쇠 — 이름이 없으면 제목+시각."""
    return str(item.get('name') or '%s@%s' % (item.get('subject', ''), item.get('at', '')))


def pick_due(items, state, now):
    """지금 보낼 차례인 (열쇠, 항목) 목록. 꺼진 항목·최근 실패해 쉬는 항목은 뺀다."""
    out = []
    for it in items or []:
        if not isinstance(it, dict) or it.get('enabled') is False:
            continue
        key = item_key(it)
        st = state.get(key) or {}
        if not kit.due(it, st.get('last_run'), now):
            continue
        fail = st.get('last_fail')
        if isinstance(fail, (int, float)) and now.timestamp() - fail < RETRY_MIN * 60:
            continue
        out.append((key, it))
    return out


def build(item, now):
    """보낼 내용 — (받는사람, 참조, 숨은참조, 제목, 본문, 첨부 경로들). 문제가 있으면 예외."""
    to = kit._as_list(item.get('to'))
    if not to:
        raise ValueError('받는 사람(to)이 없습니다')
    files = []
    for p in kit._as_list(item.get('attachments')):
        path = kit.expand(kit.render(p, now))
        if not os.path.isfile(path):
            raise FileNotFoundError('첨부 파일이 없습니다: %s' % path)
        files.append(path)
    return (to, kit._as_list(item.get('cc')), kit._as_list(item.get('bcc')),
            kit.render(item.get('subject', ''), now), kit.render(item.get('body', ''), now), files)


def send_due(items, state, now, save, log=print):
    """차례가 된 항목을 보낸다. 항목마다 결과를 state 에 적고 save(state) 를 바로 부른다. 실패 메시지 목록을 돌려준다."""
    errors = []
    for key, it in pick_due(items, state, now):
        st = state.setdefault(key, {})
        try:
            to, cc, bcc, subject, body, files = build(it, now)
            kit.send_mail(to, subject, body, cc=cc, bcc=bcc, attachments=files)
        except Exception as e:
            st.update(last_fail=now.timestamp(), last_ok=False, last_err='%s: %s' % (type(e).__name__, e))
            save(state)
            errors.append('%s — %s' % (key, st['last_err']))
            log('✖ %s 보내기 실패: %s' % (key, st['last_err']))
            continue
        st.update(last_run=now.timestamp(), last_ok=True, last_err='', last_fail=None)
        save(state)                          # 보낸 직후 기록 — 두 번 보내지 않게
        log('✉ %s → %s%s' % (key, ', '.join(to), ' (첨부 %d개)' % len(files) if files else ''))
    return errors


def status_items(items, state):
    rows = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        key = item_key(it)
        st = state.get(key) or {}
        when = '%s %s' % (it.get('days') or 'daily', it.get('at', '?'))
        if it.get('enabled') is False:
            rows.append({'name': key, 'ok': None, 'text': '꺼짐 · %s' % when})
            continue
        last = st.get('last_run')
        text = '%s · 마지막 발송 %s' % (when, _fmt(last) if last else '없음')
        if st.get('last_ok') is False:
            rows.append({'name': key, 'ok': False, 'text': '%s · 실패: %s' % (text, st.get('last_err', ''))})
        else:
            rows.append({'name': key, 'ok': True if last else None, 'text': text})
    return rows


def _fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def run(ctx):
    items = kit.section('scheduled_mails') or []
    if not items:
        ctx.log('정기 예약 메일: 설정에 없음 (config.local.json 의 scheduled_mails)')
        kit.write_status(FEATURE, [], note='설정에 없음')
        return
    path = os.path.join(kit.data_dir(FEATURE), 'state.json')
    state = kit.read_json(path, {}) or {}
    now = datetime.datetime.now()
    errors = []
    if pick_due(items, state, now):
        ok, why = kit.mail_ready()
        if not ok:
            # 메일 설정이 없으면 실패 알림 메일도 못 보낸다 — 상태 화면에만 남기고 조용히 끝낸다
            ctx.log('정기 예약 메일: 메일 설정이 안 됨 — %s' % why)
            kit.write_status(FEATURE, status_items(items, state), note='메일 설정 필요: %s' % why)
            return
        errors = send_due(items, state, now, lambda s: kit.write_json(path, s), log=ctx.log)
    kit.write_status(FEATURE, status_items(items, state),
                     note='확인 %s' % time.strftime('%H:%M') + (' · 실패 %d건' % len(errors) if errors else ''))
    if errors:
        raise RuntimeError('정기 예약 메일 %d건 실패:\n%s' % (len(errors), '\n'.join(errors)))
