/* 화면 모드(자동 · 라이트 · 다크) 단추 — 허브 첫 화면과 운영 화면이 함께 쓴다.
   모드는 허브가 기억하고(state['theme']) 페이지를 줄 때 <html data-mode> 에 심는다. 색은 theme.css 의 light-dark().
   바꾸면 허브가 /events 로 알려 열린 화면·전용 창이 같이 바뀐다(페이지는 HubMode.apply 를 부른다). */
const HubMode = (() => {
  const MODES = [['light', '☀️', '라이트'], ['dark', '🌙', '다크'], ['auto', '자동', '자동 — Windows 설정을 따름']];
  let box = null;
  function apply(mode) {
    if (!MODES.some(x => x[0] === mode)) mode = 'auto';
    const root = document.documentElement;
    if (root.dataset.mode !== mode) {
      root.classList.add('mode-anim'); clearTimeout(apply.t);
      apply.t = setTimeout(() => root.classList.remove('mode-anim'), 400);
      root.dataset.mode = mode;
    }
    if (box) for (const b of box.children) b.classList.toggle('on', b.dataset.m === mode);
  }
  function mount(sel, token) {
    box = document.querySelector(sel);
    if (!box) return;
    box.classList.add('modesw'); box.setAttribute('role', 'group'); box.title = '화면 모드';
    for (const [m, label, tip] of MODES) {
      const b = document.createElement('button');
      b.type = 'button'; b.dataset.m = m; b.textContent = label; b.title = tip;
      b.onclick = async () => {
        const prev = document.documentElement.dataset.mode;
        apply(m);
        try {
          const r = await fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hub-Token': token }, body: JSON.stringify({ mode: m }) });
          if (!r.ok) throw new Error(r.status);
        } catch (e) { apply(prev); }
      };
      box.append(b);
    }
    apply(document.documentElement.dataset.mode);
  }
  return { apply, mount };
})();
