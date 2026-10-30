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
  element(manifest, spec, kind){                             // 스펙에 맞는 요소를 만든다. kind('dog'·'cat')를 주면 소품·계절 장식(PetAcc)도 얹는다
    const o = typeof spec === 'string' ? {file: spec} : spec;
    const acc = kind && window.PetAcc && o.rig ? PetAcc.svg(PetAcc.pick(kind), o.rig) : null;
    let el;
    if (o.frames && o.frames.length) {                       // PNG 시퀀스: 미리 읽어 두고 fps 로 src 를 바꾼다
      const urls = o.frames.map(f => this.url(manifest, f));
      urls.forEach(u => { const im = new Image(); im.src = u; });
      el = document.createElement('img'); el.alt = ''; el.draggable = false; el.src = urls[0];
      let n = 0;
      if (urls.length > 1) el._timer = setInterval(() => { n = (n + 1) % urls.length; el.src = urls[n]; }, 1000 / Math.max(1, Math.min(60, o.fps || 10)));
    } else if (o.rig && o.file && !this.isVideo(o.file) && window.PetWarp && PetWarp.ok()) {   // 그물 변형(web/petwarp.js): 고개 갸웃·끄덕·앞발 들기·숨쉬기
      el = PetWarp.element(this.url(manifest, o.file), o.rig, o.fx, acc);   // 소품은 그림과 한 텍스처로 — 고개를 따라 움직인다
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
    const deco = kind && window.PetAcc ? PetAcc.decoHtml(kind) : '';      // 계절 장식(박쥐·눈·꽃잎) — 그림 둘레에 조용히
    if (deco) box.insertAdjacentHTML('beforeend', deco);
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
    const ak = window.PetAcc ? PetAcc.key(kind) : '';                     // 소품·계절이 바뀌어도 다시 그린다
    if (artEl._spec !== spec || artEl._ak !== ak) { if (cur) this.dispose(cur); artEl.append(this.element(manifest, spec, kind)); artEl._spec = spec; artEl._ak = ak; }
  },
  reset(artEl){ const cur = artEl.querySelector('.skin-media'); if (cur) this.dispose(cur); artEl._spec = null; artEl._ak = null; }
};
/* 소품 · 계절 (2026-10-30) — 새 그림 없이 SVG 소품을 머리에 얹는다. 자리는 품종 rig(neck·crown·eye, skin.json)로 정하고,
   그물 변형(web/petwarp.js)이 그림과 한 텍스처로 합쳐서 고개 갸웃·끄덕에 같이 움직인다(WebGL 이 없으면 소품 없이 그림만).
   설정은 허브가 기억한다(state 'petx' — GET/POST /api/petx, 이벤트 {t:'petx'}): season(계절 소품 자동) · acc {dog, cat}('none' = 없음).
   계절이면 고른 소품 대신 계절 소품과 장식(박쥐·눈·꽃잎)을 쓴다. 허브가 없는 곳(폰 페이지)은 기본값(계절 자동·소품 없음).
   미리 보기: 페이지 주소에 ?season=halloween|xmas|spring|none · ?acc=crown 등 */
window.PetAcc = {
  LIST: [['ribbon', '리본'], ['scarf', '목도리'], ['glasses', '안경'], ['beret', '베레모'], ['bowtie', '나비넥타이'], ['crown', '왕관']],
  SEASONS: {                                                 // 날짜는 월-일(양 끝 포함)
    halloween: {name: '할로윈', from: '10-24', to: '10-31', dog: 'pumpkin', cat: 'witch', deco: {cat: 'bat'}},
    xmas: {name: '크리스마스', from: '12-01', to: '12-26', dog: 'santa', cat: 'santa', deco: {dog: 'snow', cat: 'snow'}},
    spring: {name: '봄', from: '03-28', to: '04-12', dog: 'blossom', cat: 'blossom', deco: {cat: 'petal'}},
  },
  // bubble: 말풍선(쪽지) 켬 · quiet: 조용히 시간(none·lunch·night·both) — 데스크톱 펫(pet.html)이 쓴다
  // grow: 키우기(간식·레벨) 켬 · lv: 허브 petgrow.view {snacks, level, floor, next, week, prev_week} · unlock: 소품이 풀리는 레벨
  conf: {season: true, grow: true, bubble: true, quiet: 'none', acc: {dog: 'none', cat: 'none'}, lv: null, unlock: {}},
  force: {},                                                 // 미리 보기(주소의 ?season= · ?acc= · ?level=)
  set(c){                                                    // 허브 설정을 받는다(빠진 키는 그대로) — 바뀌었으면 true(그리는 쪽은 key 로 알아챈다)
    if (!c) return false;
    const has = k => Object.prototype.hasOwnProperty.call(c, k), cur = this.conf;
    const next = {season: has('season') ? c.season !== false : cur.season, grow: has('grow') ? c.grow !== false : cur.grow,
      bubble: has('bubble') ? c.bubble !== false : cur.bubble, quiet: has('quiet') ? c.quiet || 'none' : cur.quiet,
      acc: has('acc') ? Object.assign({dog: 'none', cat: 'none'}, c.acc || {}) : cur.acc, lv: c.lv || cur.lv, unlock: c.unlock || cur.unlock};
    const changed = JSON.stringify(next) !== JSON.stringify(cur);
    Object.assign(cur, next);
    return changed;
  },
  level(){ return +this.force.level || (this.conf.lv && this.conf.lv.level) || 1; },
  locked(id){ return !!this.conf.grow && (this.conf.unlock[id] || 0) > this.level(); },   // 키우기를 끄면 다 풀린다
  lvText(){                                                  // 마우스를 올렸을 때 한 줄 — 키우기를 끄면 빈 글
    const v = this.conf.lv;
    if (!this.conf.grow || !v) return '';
    return 'Lv.' + this.level() + ' · 간식 ' + v.snacks + '개' + (v.next ? ' (다음까지 ' + (v.next - v.snacks) + ')' : '');
  },
  unlockedAt(lv){ const e = Object.entries(this.conf.unlock).find(([, n]) => n === lv); return e ? (this.LIST.find(x => x[0] === e[0]) || [])[1] : null; },
  seasonOf(d){
    const md = String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    return Object.keys(this.SEASONS).find(id => this.SEASONS[id].from <= md && md <= this.SEASONS[id].to) || null;
  },
  season(now){
    if ('season' in this.force) return this.SEASONS[this.force.season] ? this.force.season : null;
    return this.conf.season ? this.seasonOf(now || new Date()) : null;
  },
  pick(kind){                                                // 지금 얹을 소품 id(없으면 null)
    if (this.force.acc) return this.ART[this.force.acc] ? this.force.acc : null;
    const s = this.season();
    if (s) return this.SEASONS[s][kind] || null;
    const a = this.conf.acc[kind];
    return a && this.ART[a] && !this.locked(a) ? a : null;
  },
  deco(kind){ const s = this.season(); return s ? (this.SEASONS[s].deco || {})[kind] || null : null; },
  key(kind){ return (this.pick(kind) || '') + '|' + (this.deco(kind) || ''); },
  geom(rig){                                                 // 그림 한 변 = 100. x·n 목(입 아래) · c 정수리 · u 머리 크기 · ey/eh 눈 높이·눈 사이 절반
    const x = rig.neck[0] * 100, n = rig.neck[1] * 100, c = (rig.crown != null ? rig.crown : rig.neck[1] - 0.42) * 100, u = n - c;
    const ey = rig.eye ? rig.eye[0] * 100 : c + u * 0.5, eh = rig.eye ? rig.eye[1] * 100 : u * 0.24;
    return {x, n, c, u, ey, eh, k: u / 38};
  },
  svg(id, rig){                                              // 소품 SVG(그물 변형 텍스처와 같은 칸: 가로 0~100, 세로 -20~100 — 위쪽 20 은 머리 위 여유)
    const f = id && rig && rig.neck && this.ART[id];
    if (!f) return null;
    const g = this.geom(rig), r = v => Math.round(v * 100) / 100;
    const at = (x, y, rot, s) => `<g transform="translate(${r(x)} ${r(y)}) rotate(${rot || 0}) scale(${r(s == null ? g.k : s)})">`;
    return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="480" viewBox="0 -20 100 120">' +
      '<g stroke="#3b302a" stroke-width=".55" stroke-linejoin="round" stroke-linecap="round">' + f(g, at) + '</g></svg>';
  },
  flower(cx, cy, s, rot){                                    // 벚꽃 한 송이(꽃잎 다섯 장)
    let p = '';
    for (let i = 0; i < 5; i++) p += `<path d="M0 0C-2.6-1.6-3.2-4.6-1.2-6.2L0-5.2L1.2-6.2C3.2-4.6 2.6-1.6 0 0Z" transform="rotate(${i * 72})"/>`;
    return `<g transform="translate(${cx} ${cy}) rotate(${rot || 0}) scale(${s})" fill="#f6c4cf" stroke-width=".45">${p}<circle r="1.2" fill="#e7a245" stroke="none"/></g>`;
  },
  ART: {                                                     // 그림체: 가는 먹선 + 흐린 색(종이 노트). g.k 는 머리 크기 배율
    ribbon: (g, at) => at(g.x + g.u * 0.3, g.c + g.u * 0.07, 18) +
      '<path d="M-1 1L-5 9.5L-2.4 8.8L-1.3 11Z M1 1L5 9.5L2.4 8.8L1.3 11Z" fill="#b5503b"/>' +
      '<path d="M0 0C-3-5-11-7.5-12-1.2C-12.4 4.6-4 5 0 0Z M0 0C3-5 11-7.5 12-1.2C12.4 4.6 4 5 0 0Z" fill="#cf6a52"/>' +
      '<path d="M-3-1.6C-6-3.6-9-3.6-10.2-1.4 M3-1.6C6-3.6 9-3.6 10.2-1.4" fill="none" stroke="#efa48f" stroke-width=".5"/>' +
      '<ellipse rx="2.3" ry="2.7" fill="#b5503b"/></g>',
    scarf: (g, at) => at(g.x, g.n + g.u * 0.1, 0) +
      '<path d="M7 3.5L13.5 3.6L12.6 17L6.4 16.6Z" fill="#a8432a"/>' +
      '<path d="M7.2 17v2.4M9.3 17.1v2.4M11.4 17.2v2.4" fill="none" stroke-width=".7"/>' +
      '<path d="M-21-3C-10 2.4 10 2.4 21-3L20.4 3.4C10 8.6-10 8.6-20.4 3.4Z" fill="#a8432a"/>' +
      '<path d="M-20.6 0.2C-10 5.6 10 5.6 20.6 0.2" fill="none" stroke="#efe3cf" stroke-width="1.1"/>' +
      '<path d="M7.4 9.5L13 9.8" fill="none" stroke="#efe3cf" stroke-width="1.1"/></g>',
    glasses: (g, at) => at(g.x, g.ey, 0, g.eh / 10) +
      '<circle cx="-10" r="6.4" fill="#ffffff" fill-opacity=".16" stroke-width="1.05"/><circle cx="10" r="6.4" fill="#ffffff" fill-opacity=".16" stroke-width="1.05"/>' +
      '<path d="M-3.6-.9C-1.6-2.6 1.6-2.6 3.6-.9 M-16.3-1.2L-19.6-2.6 M16.3-1.2L19.6-2.6" fill="none" stroke-width="1"/>' +
      '<path d="M-13.6-3.1a4.2 4.2 0 0 1 3-1.7 M6.4-3.1a4.2 4.2 0 0 1 3-1.7" fill="none" stroke="#ffffff" stroke-width=".8"/></g>',
    beret: (g, at) => at(g.x - g.u * 0.05, g.c + g.u * 0.07, -12) +
      '<path d="M-15 0C-17.4-7-6.5-11.4 2-10.8C12-10.2 18.4-6 15 0C8 2.6-8 2.6-15 0Z" fill="#3f5c86"/>' +
      '<path d="M-14.2-1.6C-8 1 8 1 14.2-1.6" fill="none" stroke="#2c4366" stroke-width=".8"/>' +
      '<path d="M1.5-10.6L2.4-13.4" fill="none" stroke-width="1.4"/></g>',
    bowtie: (g, at) => at(g.x, g.n + g.u * 0.09, 0) +
      '<path d="M0 0L-9-5.6C-10.6-2-10.6 2-9 5.6Z M0 0L9-5.6C10.6-2 10.6 2 9 5.6Z" fill="#7b3a6b"/>' +
      '<g fill="#f2dfe9" stroke="none"><circle cx="-6" cy="-1.6" r=".8"/><circle cx="-6.4" cy="2.2" r=".8"/><circle cx="6" cy="-1.6" r=".8"/><circle cx="6.4" cy="2.2" r=".8"/></g>' +
      '<rect x="-2.2" y="-2.7" width="4.4" height="5.4" rx="1.3" fill="#5e2a52"/></g>',
    crown: (g, at) => at(g.x, g.c + g.u * 0.05, 0) +
      '<path d="M-10 0L-11.6-10L-5.4-5L0-12.4L5.4-5L11.6-10L10 0Z" fill="#e3b847"/>' +
      '<path d="M-10 0h20v2.8h-20Z" fill="#c99a2e"/>' +
      '<circle cy="-12.4" r="1.3" fill="#cf6a52"/><circle cx="-11.6" cy="-10" r="1.1" fill="#5b86bd"/><circle cx="11.6" cy="-10" r="1.1" fill="#5b86bd"/>' +
      '<circle cy="-2.4" r="1.3" fill="#cf6a52" stroke-width=".4"/></g>',
    pumpkin: (g, at) => at(g.x, g.c + g.u * 0.07, -6) +
      '<path d="M-1-14.4C-1.2-17-.4-19 1.8-19.8L2.7-18.6C1.1-17.8 1-16 1.2-14.2Z" fill="#6c8442"/>' +
      '<path d="M1.6-17C4.2-19.6 7.4-18 6.6-15.4" fill="none" stroke="#6c8442" stroke-width=".9"/>' +
      '<path d="M0-14.6C-9-15.2-14.4-11-14.4-6S-9 2.6 0 2.6 14.4-1 14.4-6 9-15.2 0-14.6Z" fill="#e48a33"/>' +
      '<path d="M-5.4-14C-8.4-10-8.4-1-5.4 2.2 M5.4-14C8.4-10 8.4-1 5.4 2.2" fill="none" stroke="#b9661f" stroke-width=".6"/>' +
      '<path d="M-6.6-7.6L-4.6-10.8L-2.6-7.6Z M2.6-7.6L4.6-10.8L6.6-7.6Z M-5-4.4C-2-2 2-2 5-4.4L3.4-2.9L1.8-3.9L0-2.8L-1.8-3.9L-3.4-2.9Z" fill="#5a3410" stroke="none"/></g>',
    witch: (g, at) => at(g.x + g.u * 0.03, g.c + g.u * 0.08, -8) +
      '<path d="M-9-1C-6-9-3-17 1-23C3-25.6 6.2-26 8.2-24.4C5.2-24 3.6-21 3.2-17C4-10 7-4 9-1Z" fill="#3d3350"/>' +
      '<ellipse rx="17.4" ry="4.2" fill="#3d3350"/>' +
      '<path d="M-8.6-2.4C-3-1 3-1 8.6-2.4L7.9-5.6C3-4.2-3-4.2-7.7-5.6Z" fill="#e48a33"/>' +
      '<rect x="-1.9" y="-5.2" width="3.8" height="3.2" fill="none" stroke="#f2c14e" stroke-width=".7"/></g>',
    santa: (g, at) => at(g.x, g.c + g.u * 0.08, -6) +
      '<path d="M-12.6-1C-12-9-6-16 2-17.2C8.4-17.8 13.6-14 16.4-7.8C13.4-9.8 10.4-10.4 8.2-9C9.2-6 10.4-3 12.4-1Z" fill="#c23f33"/>' +
      '<rect x="-14.6" y="-3.4" width="28.6" height="5.8" rx="2.9" fill="#fbf7ef"/>' +
      '<circle cx="16.6" cy="-6.6" r="3.2" fill="#fbf7ef"/></g>',
    blossom: (g, at) => at(g.x + g.u * 0.28, g.c + g.u * 0.09, 0) +
      PetAcc.flower(0, 0, 1.25, 10) + PetAcc.flower(-5.6, 3.4, 0.85, 40) + '</g>',
  },
  DECO: {                                                    // 계절 장식 — 그림 둘레에서 천천히(pets.css .fx-bat·.fx-snow·.fx-petal)
    bat: '<i class="fx-deco fx-bat" aria-hidden="true"><svg viewBox="0 0 24 12"><path d="M12 4.2C11 2.4 11 1.2 11.6.4C12 1 12.4 1 12.4.4C13 1.2 13 2.4 12 4.2C14 2.2 18.4.8 23 1.8C21 2.8 20 4.4 20 6.4C18.4 5.4 16.6 5.6 15.4 7C14.4 5.8 13 5.6 12 6.4C11 5.6 9.6 5.8 8.6 7C7.4 5.6 5.6 5.4 4 6.4C4 4.4 3 2.8 1 1.8C5.6.8 10 2.2 12 4.2Z"/></svg></i>',
    snow: '<i class="fx-deco fx-snow" aria-hidden="true"><b></b><b></b><b></b><b></b><b></b><b></b></i>',
    petal: '<i class="fx-deco fx-petal" aria-hidden="true"><b></b><b></b><b></b><b></b></i>',
  },
  decoHtml(kind){ const d = this.deco(kind); return d ? this.DECO[d] || '' : ''; },
};
(() => {
  try {
    const q = new URLSearchParams(location.search);
    if (q.get('season')) PetAcc.force.season = q.get('season');
    if (q.get('acc')) PetAcc.force.acc = q.get('acc');
    if (q.get('level')) PetAcc.force.level = +q.get('level');
  } catch (e) { /* 주소를 못 읽어도 그대로 */ }
})();
