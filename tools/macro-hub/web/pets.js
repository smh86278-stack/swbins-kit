/* 강아지 · 고양이 — 허브 페이지(index.html)와 데스크톱 펫(pet.html)이 함께 쓴다.
   PetArt  : 고양이 일의 종류 배지와 문구 (그림은 스킨 — 기본은 web/skins/plush, 옛 내장 SVG 그림은 2026-10-07 에 없앴다)
   PetMood : 허브 상태(macros)와 최근 사건(flash)으로 두 마리의 표정·말풍선을 계산한다 */
window.PetArt = {
  badge: `<div class="motion-badge" aria-hidden="true"><svg viewBox="0 0 48 48">
        <circle cx="24" cy="24" r="21" fill="#fff"/><circle cx="24" cy="24" r="21" fill="none" stroke="#0001" stroke-width="1.5"/>
        <g class="mo mo-web"><circle cx="24" cy="24" r="11" fill="#dbeafe" stroke="#3b82f6" stroke-width="2.4"/>
          <ellipse class="mer pv" cx="24" cy="24" rx="5" ry="11" fill="none" stroke="#3b82f6" stroke-width="2"/>
          <path d="M13 24h22M15.5 18h17M15.5 30h17" stroke="#3b82f6" stroke-width="1.8" fill="none"/></g>
        <g class="mo mo-desktop"><rect x="11" y="13" width="26" height="19" rx="2.5" fill="#eef2f7" stroke="#64748b" stroke-width="2"/>
          <path d="M11 18h26" stroke="#64748b" stroke-width="2"/><circle cx="14.5" cy="15.6" r="1" fill="#f87171"/>
          <rect x="15" y="22" width="9" height="5" rx="1" fill="#93c5fd"/>
          <path class="cur" d="M25 23v12l3-3 2.6 5 2.2-1.1-2.6-5h4.3z" fill="#111" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/></g>
        <g class="mo mo-write"><rect x="12" y="11" width="20" height="26" rx="2" fill="#fff8e7" stroke="#b08a4a" stroke-width="1.8"/>
          <path class="ln1" d="M16 18h12" stroke="#b08a4a" stroke-width="1.8" stroke-linecap="round"/>
          <path class="ln2" d="M16 23h12" stroke="#b08a4a" stroke-width="1.8" stroke-linecap="round"/>
          <path class="ln3" d="M16 28h8" stroke="#b08a4a" stroke-width="1.8" stroke-linecap="round"/>
          <g class="pen"><path d="M27 33l11-11 3.4 3.4-11 11-4.4 1z" fill="#facc15" stroke="#a16207" stroke-width="1.4" stroke-linejoin="round"/><path d="M36 24l3.4 3.4" stroke="#a16207" stroke-width="1.4"/></g></g>
        <g class="mo mo-mail"><g class="env"><rect x="11" y="15" width="26" height="18" rx="2.5" fill="#fff1e0" stroke="#f08a24" stroke-width="2"/>
          <path d="M11.8 16.5L24 26l12.2-9.5" fill="none" stroke="#f08a24" stroke-width="2" stroke-linejoin="round"/></g>
          <path class="whoosh" d="M5 20h4M3 25h6M5 30h4" stroke="#f08a24" stroke-width="1.8" stroke-linecap="round"/></g>
        <g class="mo mo-search"><g class="lens"><circle cx="21" cy="21" r="8.5" fill="#dcfce7" stroke="#16a34a" stroke-width="2.6"/>
          <path d="M27 27l8.5 8.5" stroke="#16a34a" stroke-width="3.6" stroke-linecap="round"/><path d="M17 18.5a4.5 4.5 0 0 1 4-2.7" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round"/></g></g>
      </svg></div>`,
  // 일의 종류별 말풍선
  motionText: {web: '웹 페이지 다니는 중', desktop: '창 조작하는 중', write: '열심히 입력하는 중', mail: '메일 처리하는 중', search: '찾아보는 중'}
};
window.PetMood = {
  newFlash(){ return {cat:null, until:0, dogBark:0, dogText:''}; },
  compute(macros, flash, now, force){
    force = force || {};
    const svc = macros.filter(m => m.service), on = svc.filter(m => m.enabled), down = on.filter(m => !m.running);
    // 일하는 중 = 일반 자동화가 도는 중, 또는 상시 자동화가 ctx.motion() 으로 잠깐 일하는 모습을 보이는 중
    // ctx.motion(hold=) 이 끝났으면 META 기본 모습으로(상시 자동화는 기본이 없으니 지켜보기로) 돌아간다
    const motionOf = m => (!m.motion_until || m.motion_until > now) ? m.motion : m.motion_default;
    const active = m => !!motionOf(m);
    const working = macros.filter(m => m.running && (!m.service || active(m)));
    let dog, dogText;
    if (!on.length) { dog = 'sleep'; dogText = '쿨쿨… 상시 자동화를 켜면 깨울게요'; }
    else if (down.length) { dog = 'worried'; dogText = '앗, ' + down[0].name + ' 다시 살리는 중이에요…'; }
    else { dog = 'alert'; dogText = on.map(m => m.name).join(', ') + ' 지키는 중!'; }
    const barking = flash.dogBark > now;
    let cat, catText, catMotion = null;
    if (working.length) {
      const w = working.find(active) || working[0];
      catMotion = motionOf(w) || null;
      cat = 'work'; catText = w.name + (catMotion ? ' — ' + PetArt.motionText[catMotion] + '…' : ' 처리 중…');
    }
    else if (flash.until > now) { cat = flash.cat; catText = cat === 'happy' ? '다 했어요! 🎉' : '앗, 실패했어요…'; }
    else { cat = 'idle'; catText = '할 일 기다리는 중'; }
    if (force.dog) dog = force.dog;
    if (force.cat) cat = force.cat;
    if (force.motion) { catMotion = force.motion; if (!force.cat) cat = 'work'; catText = (PetArt.motionText[catMotion] || catMotion) + '…'; }
    if (cat !== 'work') catMotion = null;
    return {dog, dogText: barking ? flash.dogText : dogText, cat, catText, catMotion, barking, on, down, working};
  },
  react(flash, r){                     // 실행(run) 이벤트에 대한 반응
    if (r.tool) return;
    if (r.status === 'running' && r.trigger !== 'manual' && r.trigger !== 'service') { flash.dogBark = Date.now() + 2600; flash.dogText = '멍! ' + r.name + ' 시작'; }
    if (r.status === 'ok') { flash.cat = 'happy'; flash.until = Date.now() + 4200; }
    if (r.status === 'fail' || r.status === 'timeout') { flash.cat = 'sad'; flash.until = Date.now() + 6000; }
  },
  notify(flash, m){ flash.dogBark = Date.now() + 2600; flash.dogText = '멍! ' + (m.title || '알림'); },
  mood(el, kind, value){ el.dataset[kind] = value; }
};

/* 스킨 — 그림 대신 움직이는 이미지/영상/PNG 시퀀스로 통째로 바꾼다. web/skins/<이름>/skin.json 에 상태별로 적는다. 자세한 건 web/skins/README.md
   한 상태의 값:  "파일.gif"                                           (GIF·APNG·WebP·PNG·WebM 한 개)
                  {"frames":["a_00.png","a_01.png",...], "fps":12}    (PNG 시퀀스를 fps 로 반복 재생)
                  {"from":"alert", "filter":"brightness(.7)", "fps":4}  (다른 상태 것을 빌려 효과만 바꿈 — 예: 잠자는 모습)
                  공통 효과: filter(CSS 필터) · flip(좌우 반전) · scale(1=기본 폭)
                  fx(연출): idle · sleep · worried · bark · work · happy · sad — 그림 한 장으로도 상태가 보이게 움직임과 장식을 얹는다
   고양이 "work" 는 일의 종류별로 "work:web" · "work:desktop" · "work:write" · "work:mail" · "work:search" 를 따로 줄 수 있다(없으면 work). */
window.PetSkin = {
  DEFAULT: 'plush',                                          // 스킨을 안 골랐을 때 쓰는 기본 모습(인형 시바·고양이 — 저장소에 들어 있다)
  BASE: '/',                                                 // 스킨 폴더 앞 경로 — 허브·메신저는 '/skin/…', 폰 페이지(GitHub Pages 하위 경로)는 'pet/' 로 바꿔 'pet/skin/…'
  async list(){ try { return await (await fetch('/api/skins')).json(); } catch (e) { return []; } },
  async load(id, breed){
    id = id || this.DEFAULT;
    try {
      const r = await fetch(this.BASE + 'skin/' + encodeURIComponent(id) + '/skin.json');
      if (!r.ok) return null;
      const m = await r.json(); m._id = id; m._cache = {}; this.applyBreed(m, breed); return m;
    } catch (e) { return null; }
  },
  /* 품종: skin.json 의 "breeds": {"dog": {"shiba": {"name": "시바", "alert": "dog-shiba.webp", "sleep": ...}}, "cat": {...}}
     고른 품종(없거나 모르는 것이면 첫 번째)의 상태별 파일을 dog/cat 표에 덮어쓴다 — 효과(fx·filter·from)는 표의 것을 그대로 쓴다 */
  breedIds(manifest, kind){ return Object.keys(((manifest && manifest.breeds) || {})[kind] || {}); },
  applyBreed(m, breed){
    m._breed = {};
    for (const kind of ['dog', 'cat']) {
      const ids = this.breedIds(m, kind);
      if (!ids.length) continue;
      const b = ids.includes((breed || {})[kind]) ? breed[kind] : ids[0];
      m._breed[kind] = b;
      const t = m[kind] = Object.assign({}, m[kind]);
      const {name, rig, ...files} = m.breeds[kind][b];
      for (const [state, file] of Object.entries(files)) t[state] = Object.assign({}, typeof t[state] === 'string' ? {file: t[state]} : t[state], {file});
      if (rig) for (const state of Object.keys(t)) t[state] = Object.assign({}, typeof t[state] === 'string' ? {file: t[state]} : t[state], {rig});   // 품종 그림의 목·앞발 위치(그물 변형)
    }
  },
  resolve(manifest, kind, key){                              // 상태 값을 하나의 객체로 풀어 준다(from 처리). 같은 객체를 돌려줘야 바뀐 줄 안다
    const t = (manifest && manifest[kind]) || {};
    const ck = kind + ':' + key;
    if (manifest._cache[ck] !== undefined) return manifest._cache[ck];
    let v = t[key], out = null;
    if (v) {
      const o = typeof v === 'string' ? {file: v} : Object.assign({}, v);
      if (o.from && o.from !== key && t[o.from]) {
        const base = this.resolve(manifest, kind, o.from);
        out = base ? Object.assign({}, base, o) : null;
      } else out = (o.file || (o.frames && o.frames.length)) ? o : null;
    }
    return (manifest._cache[ck] = out);
  },
  file(manifest, kind, mood, bark, motion){                  // 상태에 맞는 스펙. 없으면 기본 표정 → 없으면 null(= 내장 그림)
    if (kind === 'dog' && bark) { const b = this.resolve(manifest, kind, 'bark'); if (b) return b; }
    if (motion) { const w = this.resolve(manifest, kind, mood + ':' + motion); if (w) return w; }   // 일의 종류별 모습(work:mail 등), 없으면 그냥 work
    return this.resolve(manifest, kind, mood) || this.resolve(manifest, kind, kind === 'dog' ? 'alert' : 'idle');
  },
  url(manifest, file){ return this.BASE + 'skin/' + encodeURIComponent(manifest._id) + '/' + encodeURIComponent(file); },
  isVideo(file){ return /\.(mp4|webm)$/i.test(file); },
  element(manifest, spec){                                   // 스펙에 맞는 요소를 만든다
    const o = typeof spec === 'string' ? {file: spec} : spec;
    let el;
    if (o.frames && o.frames.length) {                       // PNG 시퀀스: 미리 읽어 두고 fps 로 src 를 바꾼다
      const urls = o.frames.map(f => this.url(manifest, f));
      urls.forEach(u => { const im = new Image(); im.src = u; });
      el = document.createElement('img'); el.alt = ''; el.draggable = false; el.src = urls[0];
      let n = 0;
      if (urls.length > 1) el._timer = setInterval(() => { n = (n + 1) % urls.length; el.src = urls[n]; }, 1000 / Math.max(1, Math.min(60, o.fps || 10)));
    } else if (o.rig && o.file && !this.isVideo(o.file) && window.PetWarp && PetWarp.ok()) {   // 그물 변형(web/petwarp.js): 고개 갸웃·끄덕·앞발 들기·숨쉬기
      el = PetWarp.element(this.url(manifest, o.file), o.rig, o.fx);
    } else if (this.isVideo(o.file)) {
      el = document.createElement('video'); el.src = this.url(manifest, o.file); el.loop = true; el.muted = true; el.autoplay = true; el.playsInline = true;
    } else {
      el = document.createElement('img'); el.src = this.url(manifest, o.file); el.alt = ''; el.draggable = false;
    }
    el.className = 'skin-media';
    if (o.pixel) el.style.imageRendering = 'pixelated';                   // 도트 그림이 번지지 않게
    if (o.frames && o.frames.length === 1 && !o.fx) el.classList.add('still');    // 한 장짜리 자세(잠자기 등)는 숨 쉬듯 살짝 움직인다
    if (o.filter) el.style.filter = o.filter;
    if (o.flip) el.style.transform = 'scaleX(-1)';
    if (o.scale) { el.style.width = (o.scale * 100) + '%'; el.style.margin = '0 auto'; }
    if (!o.fx || !this.FX.hasOwnProperty(o.fx)) return el;
    const box = document.createElement('div');                           // 연출(fx): 그림을 움직이고 💤·땀방울·"멍!" 같은 장식을 얹는다(pets.css 의 .fx-*)
    box.className = 'skin-media skin-fx fx-' + o.fx;
    el.className = 'skin-img';
    box._timer = el._timer; box._stop = el._stop;
    box.append(el);
    box.insertAdjacentHTML('beforeend', this.FX[o.fx]);
    return box;
  },
  FX: {                                                      // 그림 한 장으로 상태를 보여 주는 연출 — 장식 HTML
    idle: '', work: '',
    sleep: '<i class="fx-deco fx-z" aria-hidden="true"><b>z</b><b>z</b><b>Z</b></i>',
    worried: '<i class="fx-deco fx-drop" aria-hidden="true"><svg viewBox="0 0 12 18"><path d="M6 0C2 7 0 10 0 12.5A6 6 0 0 0 12 12.5C12 10 10 7 6 0Z"/></svg></i>',
    sad: '<i class="fx-deco fx-drop" aria-hidden="true"><svg viewBox="0 0 12 18"><path d="M6 0C2 7 0 10 0 12.5A6 6 0 0 0 12 12.5C12 10 10 7 6 0Z"/></svg></i>',
    bark: '<i class="fx-deco fx-say" aria-hidden="true">멍!</i>',
    happy: '<i class="fx-deco fx-spark" aria-hidden="true"><b>✦</b><b>✦</b><b>✦</b></i>',
  },
  petted(kind, mood, bark){                                  // 마우스를 올렸을 때(쓰다듬기): 강아지는 반갑게 짖고(자다가도 깬다), 고양이는 기뻐한다 — 일하는 중이면 그대로
    return kind === 'dog' ? {mood: mood === 'sleep' ? 'alert' : mood, bark: true} : {mood: mood === 'work' ? mood : 'happy', bark};
  },
  dispose(el){ if (el && el._timer) clearInterval(el._timer); if (el && el._stop) el._stop(); if (el && el.remove) el.remove(); },
  render(manifest, petEl, artEl, kind, mood, bark, motion){  // 허브 화면과 펫이 같이 쓴다: 상태에 맞는 스킨을 art 칸에 그린다(없으면 내장 그림)
    const spec = manifest ? this.file(manifest, kind, mood, bark, motion) : null;
    petEl.classList.toggle('skinned', !!spec);
    const cur = artEl.querySelector('.skin-media');
    if (!spec) { if (cur) this.dispose(cur); artEl._spec = null; return; }
    if (artEl._spec !== spec) { if (cur) this.dispose(cur); artEl.append(this.element(manifest, spec)); artEl._spec = spec; }
  },
  reset(artEl){ const cur = artEl.querySelector('.skin-media'); if (cur) this.dispose(cur); artEl._spec = null; }
};
