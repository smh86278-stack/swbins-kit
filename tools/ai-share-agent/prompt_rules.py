"""내 프롬프트 규칙 점검 — AI 작업 회고(agent.py)와 허브 화면 펫 간식(macro-hub/petsnack.py)이 함께 쓴다(agent.py 에서 떼어 냄).
표준 라이브러리만, 바깥 호출 없음. 규칙은 적게·확실한 것만 — 대부분 세션 첫 프롬프트만 본다.
이슈 키는 흔한 모양(ABC-123 · #123)과, 넘겨주면 이슈 출처의 키 모양(key_re)도 본다.
"""
import re


PASTE_RE = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content[^>]*>", re.S)
TAG_BLOCK_RE = re.compile(r"<(system-reminder|local-command-stdout|local-command-caveat)>.*?</\1>", re.S)


def clean_text(text):
    """사람이 친 프롬프트만 남긴다(가리기 전). 붙여 넣은 원문은 길이만, 슬래시 명령은 "/이름 인자" 한 줄로, 500자까지."""
    text = PASTE_RE.sub(lambda m: f"[붙여넣은 내용 {len(m.group(1))}자]", text)
    text = TAG_BLOCK_RE.sub("", text)
    cmd = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
    if cmd:
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        text = f"{cmd.group(1).strip()} {args.group(1).strip() if args else ''}"
    text = re.sub(r"<[^>\n]{1,40}>", "", text).strip()
    return text[:500] + ("…" if len(text) > 500 else "")


ISSUE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b|#\d+\b")   # 흔한 이슈 키 모양(ABC-123 · #123) — 출처 키 모양(TR.key_re)도 함께 본다
DEMONSTRATIVE_RE = re.compile(r"(이거|그거|저거|이것|그것|저것|여기|거기|이건|그건|위에 거|아까 거)")
TARGET_RE = re.compile(
    r"https?://|[\w./\\-]+\.(?:php|py|js|ts|tsx|jsx|html|css|json|md|java|kt|sql|xml|yml|yaml|ps1|bat|go|rs|cs|vue|txt|csv|xlsx)\b"
    r"|`[^`]+`|\b[a-z]+[A-Z]\w*\b|\b[A-Z][a-z]+[A-Z]\w*\b|\b\w+_\w+\b|\b\w+\(\)|[A-Za-z]:\\"
    r"|붙여넣은 내용|\[Image|화면|페이지|버튼|탭|메뉴|API|함수|클래스|메서드|테이블|컬럼|쿼리|폴더|파일|브랜치|커밋|MR|PR|레포|이슈|티켓|에러|오류 메시지|로그")
CHANGE_RE = re.compile(r"(고쳐|수정|만들어|추가|바꿔|변경|구현|개발|넣어|빼|지워|리팩터|정리해|개선)")
CRITERIA_RE = re.compile(r"(확인|테스트|시험|검증|되면|될 때|완료|기대|결과|나오게|보이게|되게|도록|해야|통과|처럼|예상|성공|기준|일 때|경우)")
BROAD_RE = re.compile(r"(전부|전체|모두|싹|다 바꿔|리팩터|갈아엎|정리해)")
CONSTRAINT_RE = re.compile(r"(말고|하지 ?마|건드리지|그대로|유지|만\b|금지|빼고|없이|제외|범위|안 ?바꾸|손대지)")
# 다음 프롬프트가 앞 지시를 고쳐 말한 것 — 맨 앞 "아니" 만으로는 맞장구("아니 근데…")일 수 있어 뒤에 말고·아니라·다시 가 있어야 센다
CORRECTION_RE = re.compile(r"^\s*(?:(?:아니|아냐|아니야)\b.{0,40}(?:말고|아니라|다시|가 아니)|아니라|그게 아니|그거 말고|그건 아니|다시 해|다시 만들"
                           r"|틀렸|잘못 (?:했|이해|만들)|그렇게 말고|내 말은)")
QUESTION_RE = re.compile(r"(\?|나요?|까요?|니|냐|지|는지|던가|었나|았나|했나)\s*[.?!~]*\s*$")
ASK_RE = re.compile(r"(줘|주세요|줄래|해\s?봐)(?![가-힣])")              # 부탁 끝맺음 — 고쳐줘·바꿔 주세요·찾아줄래
NUMBERED_RE = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S")
SMALLTALK_RE = re.compile(r"^\s*(응|ㅇㅇ|네|예|좋아|오케이|ok|okay|ㄱㄱ|고마워|감사|진행|계속|커밋|푸시|push|commit)", re.I)


def prompt_hints(text, first=False, next_text="", key_re=None):
    """프롬프트 하나에 대한 규칙 점검. [{kind: "tip"|"good", code, text, ex}] — kind good 은 잘한 점.
    first = 세션 첫 프롬프트(앞 맥락 없음), next_text = 바로 다음 프롬프트(고쳐 말했는지 보려고),
    key_re = 이슈 출처의 키 모양(있으면 흔한 모양과 함께 대상으로 본다)."""
    t = text.strip()
    if not t or t.startswith("/"):                          # 슬래시 명령은 사람이 쓴 지시문이 아니다
        return []
    tips, good = [], []
    has_key = bool(ISSUE_KEY_RE.search(t) or (key_re is not None and key_re.search(t)))
    has_target = has_key or bool(TARGET_RE.search(t))
    n = len(re.sub(r"\s+", "", t))
    numbered = len(NUMBERED_RE.findall(t)) >= 2
    ask = bool((ASK_RE.search(t) or CHANGE_RE.search(t)) and not QUESTION_RE.search(t))   # 질문·혼잣말·붙여 넣은 자료는 지시가 아니다
    if first and n < 25 and DEMONSTRATIVE_RE.search(t) and not has_target:
        tips.append({"kind": "tip", "code": "vague", "text": "'이거·거기' 같은 지시어만 있어 무엇을 말하는지 AI 가 짐작해야 해요.",
                     "ex": "이거 고쳐줘 → 주문 목록 화면(orders/list.html)의 '내보내기' 버튼이 두 번 눌리는 문제 고쳐줘"})
    elif first and ask and 12 <= n <= 300 and not has_target and not SMALLTALK_RE.match(t):
        tips.append({"kind": "tip", "code": "target", "text": "어디(파일·화면·이슈 키)를 말하는지 없어요 — 대상을 적으면 찾는 시간이 줄어요.",
                     "ex": "…해줘 → ABC-123, src/orders/import.py 의 주문 가져오기에서 …해줘"})
    if first and ask and n >= 30 and CHANGE_RE.search(t) and ASK_RE.search(t) and not CRITERIA_RE.search(t):
        tips.append({"kind": "tip", "code": "criteria", "text": "무엇이 되면 끝인지(완료 기준·확인 방법)가 없어요.",
                     "ex": "…고쳐줘. 같은 주문을 두 번 가져와도 1건만 저장되면 완료, 기존 테스트도 통과해야 해"})
    if not numbered and len(ASK_RE.findall(t)) >= 3:
        tips.append({"kind": "tip", "code": "many", "text": "한 프롬프트에 부탁이 여러 개 섞여 있어요 — 번호로 나누거나 따로 맡기면 빠지는 게 줄어요.",
                     "ex": "1) 버튼 문구 바꾸기 2) 저장 오류 고치기 3) 테스트 추가 — 순서대로 하고 각각 확인해줘"})
    if first and ask and BROAD_RE.search(t) and not CONSTRAINT_RE.search(t):
        tips.append({"kind": "tip", "code": "scope", "text": "크게 바꾸는 부탁인데 건드리면 안 되는 곳·범위가 없어요.",
                     "ex": "…정리해줘. 단 공개 함수 이름·DB 스키마는 그대로 두고, 이 폴더 안에서만"})
    if ask and next_text and CORRECTION_RE.match(next_text):
        tips.append({"kind": "tip", "code": "redo", "text": "바로 다음에 고쳐 말했어요 — 그 조건을 처음에 넣었으면 한 번에 됐을 수 있어요.",
                     "ex": "다음 프롬프트: " + next_text.strip()[:80]})
    if ask and n >= 30:
        if has_key or re.search(r"\.\w{2,4}\b|`", t):
            good.append({"kind": "good", "code": "target", "text": "대상(이슈·파일)을 콕 집어 적었어요.", "ex": ""})
        if numbered:
            good.append({"kind": "good", "code": "steps", "text": "할 일을 번호·목록으로 나눠 적었어요.", "ex": ""})
        if CHANGE_RE.search(t) and CRITERIA_RE.search(t) and first:
            good.append({"kind": "good", "code": "criteria", "text": "끝났는지 볼 기준을 같이 적었어요.", "ex": ""})
        if CHANGE_RE.search(t) and CONSTRAINT_RE.search(t):
            good.append({"kind": "good", "code": "scope", "text": "건드리지 말 것·범위를 함께 적었어요.", "ex": ""})
    return tips + good[:2]


GOOD_MIN = 30                                                # 이보다 짧으면 규칙이 다 걸리지 않으니 '잘 썼다'고 보지 않는다


def is_instruction(text):
    """규칙이 제대로 보는 지시문인가 — 슬래시 명령·질문·맞장구·짧은 말(공백 빼고 GOOD_MIN 자 미만)은 아니다."""
    t = (text or "").strip()
    if not t or t.startswith("/") or SMALLTALK_RE.match(t):
        return False
    ask = bool((ASK_RE.search(t) or CHANGE_RE.search(t)) and not QUESTION_RE.search(t))
    return ask and len(re.sub(r"\s+", "", t)) >= GOOD_MIN


def good_first(text, next_text="", **kw):
    """세션 첫 프롬프트가 규칙 점검을 💡 하나 없이 통과했나(화면 펫 '좋은 프롬프트' 간식). 지시문이 아니면 False."""
    if not is_instruction(text):
        return False
    return not any(h["kind"] == "tip" for h in prompt_hints(text, True, next_text, **kw))
