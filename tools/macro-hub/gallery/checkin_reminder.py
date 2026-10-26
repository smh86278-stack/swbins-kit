# -*- coding: utf-8 -*-
"""📚 갤러리 견본 — 출근 체크 알림. 허브 🛠 만들기 → 자동화 갤러리 → 「내 자동화로 복사」로 사본을 만들어 쓴다."""
import re
import webbrowser

META = {
    "name": "출근 체크 알림",
    "icon": "⏰",
    "desc": "평일 아침에 근태 화면을 열어 주고 '출근 체크 하셨나요?' 알림을 띄운다. 체크 버튼은 사람이 누른다.",
    "keywords": ["출근", "근태", "출석", "체크", "아침"],  # 만들기 칸에 적은 말과 맞춰 비슷한 견본으로 띄운다(말 줄기 — 조사·어미가 붙어도 맞게)
    "steps": ["평일 아침 정해진 시각에", "근태(출근 체크) 화면을 기본 브라우저로 열기", "알림 띄우기 (mail 칸이 yes 면 메일로도)"],
    "kind": "ctx",
    "target": "desktop",
    "motion": "mail",
    "params": {"url": "https://example.com/attendance", "message": "출근 체크 하셨나요?", "mail": "no"},
    "hint": "url 칸에 근태 화면 주소를 넣고 💾 기억 → 🧪 시험 → 「자동 실행」을 켜면 평일 08:55 에 알려 줘요(시각은 ⏰ 운영에서 바꿈)",
    "triggers": [{"type": "schedule", "at": "08:55", "days": "mon-fri"}],
    "timeout": 60,
}

YES = ("yes", "y", "1", "true", "on", "예", "네")


def run(ctx):
    url = ctx.param("url").strip()
    msg = ctx.param("message").strip() or "출근 체크 하셨나요?"
    if url:
        if not re.match(r"^https?://", url):
            raise ValueError("url 은 http:// 또는 https:// 로 시작해야 합니다: %s" % url)
        ctx.log("근태 화면 열기:", url)
        webbrowser.open(url)
    ctx.notify("⏰ 출근 체크", msg)
    if ctx.param("mail").strip().lower() in YES and ctx.for_real("알림 메일 보내기"):
        import kit
        kit.alert("⏰ " + msg, "%s\n\n근태 화면: %s\n(자동화 허브 「출근 체크 알림」)" % (msg, url or "-"))
        ctx.log("알림 메일을 보냈습니다")
