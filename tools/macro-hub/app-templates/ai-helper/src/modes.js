// 할 일 — 이름과 AI 에게 줄 지시(system). 새 할 일은 여기에 하나 더하면 단추가 생긴다.
export const MODES = [
  { id: 'summary', name: '요약', system: '아래 글을 한국어로 핵심만 3~5줄 글머리표로 요약해. 숫자·날짜·사람·할 일은 빠뜨리지 마. 없는 내용은 지어내지 마.' },
  { id: 'reply', name: '답장 초안', system: '아래 메일(또는 메시지)에 보낼 정중하고 간결한 한국어 업무 답장 초안을 써. 확인이 필요한 내용은 [확인: …] 로 표시해. 서명은 쓰지 마.' },
  { id: 'polish', name: '다듬기', system: '아래 글의 뜻은 그대로 두고 맞춤법·띄어쓰기를 고치고 업무용으로 자연스럽게 다듬어. 고친 글만 보여 줘.' },
  { id: 'translate', name: '번역(한↔영)', system: '아래 글이 한국어면 자연스러운 영어로, 영어면 자연스러운 한국어로 번역해. 번역문만 보여 줘.' },
  { id: 'table', name: '표로 정리', system: '아래 글에서 항목을 뽑아 마크다운 표로 정리해. 열 이름은 내용에 맞게 정하고, 없는 값은 비워 둬.' },
  { id: 'custom', name: '직접 지시', system: '' },
];

export const byId = Object.fromEntries(MODES.map((m) => [m.id, m]));
