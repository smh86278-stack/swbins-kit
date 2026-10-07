/* 강아지 · 고양이 — 허브 페이지(index.html)와 데스크톱 펫(pet.html)이 함께 쓴다.
   PetArt  : SVG 그림 (모양은 pets.css 의 data-mood / data-bark 로 바뀐다)
   PetMood : 허브 상태(macros)와 최근 사건(flash)으로 두 마리의 표정·말풍선을 계산한다 */
window.PetArt = {
  dog: `<svg viewBox="0 0 240 250" aria-label="감시견 강아지">
        <defs>
          <linearGradient id="dBody" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#34363d"/><stop offset="1" stop-color="#1b1c20"/></linearGradient>
          <linearGradient id="dHead" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2e3036"/><stop offset="1" stop-color="#1f2024"/></linearGradient>
          <linearGradient id="dWhite" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fffdf9"/><stop offset="1" stop-color="#eee8df"/></linearGradient>
          <radialGradient id="dIris" cx=".4" cy=".35" r=".8"><stop offset="0" stop-color="#b07a3c"/><stop offset="1" stop-color="#5b3517"/></radialGradient>
        </defs>
        <ellipse cx="120" cy="244" rx="86" ry="9" fill="#0002"/>
        <g class="bodywrap">
          <g class="tail"><path d="M206 234 C228 230 240 208 232 184 C228 196 218 206 204 212 Z" fill="#1c1d21"/><path d="M232 184 C231 192 226 199 220 204 C229 202 235 194 232 184 Z" fill="#fffdf9"/></g>
          <path d="M26 250 C26 196 70 168 120 168 C170 168 214 196 214 250 Z" fill="url(#dBody)"/>
          <path d="M90 250 C94 206 108 184 120 182 C132 184 146 206 150 250 Z" fill="url(#dWhite)"/>
          <path d="M64 250 C60 224 70 204 90 192" stroke="#fff1" stroke-width="3" fill="none" stroke-linecap="round"/>
          <g class="head">
            <g class="earL"><path d="M66 58 C42 64 30 98 36 136 C54 138 76 118 86 88 Z" fill="#1c1d21"/><path d="M64 78 C52 86 48 104 50 120 C60 116 70 104 76 90 Z" fill="#3a3c44" opacity=".7"/></g>
            <g class="earR"><path d="M174 58 C198 64 210 98 204 136 C186 138 164 118 154 88 Z" fill="#1c1d21"/><path d="M176 78 C188 86 192 104 190 120 C180 116 170 104 164 90 Z" fill="#3a3c44" opacity=".7"/></g>
            <path d="M120 38 C172 38 196 76 194 114 C192 154 158 180 120 180 C82 180 48 154 46 114 C44 76 68 38 120 38 Z" fill="url(#dHead)"/>
            <path d="M120 42 C134 42 141 70 139 98 C137 120 141 138 148 156 C140 172 100 172 92 156 C99 138 103 120 101 98 C99 70 106 42 120 42 Z" fill="url(#dWhite)"/>
            <ellipse cx="120" cy="146" rx="38" ry="30" fill="url(#dWhite)"/>
            <ellipse cx="88" cy="86" rx="7" ry="4.5" fill="#b9733a"/><ellipse cx="152" cy="86" rx="7" ry="4.5" fill="#b9733a"/>
            <g class="eyeL"><g class="lid pv"><ellipse cx="88" cy="108" rx="13" ry="14" fill="#fff" opacity=".95"/>
              <g class="pupils"><ellipse cx="88" cy="109" rx="10.5" ry="12" fill="url(#dIris)"/><circle cx="88" cy="109" r="5.6" fill="#0d0d10"/><circle cx="84.6" cy="104.6" r="2.7" fill="#fff"/><circle cx="92" cy="113" r="1.2" fill="#fff" opacity=".8"/></g></g></g>
            <g class="eyeR"><g class="lid pv"><ellipse cx="152" cy="108" rx="13" ry="14" fill="#fff" opacity=".95"/>
              <g class="pupils"><ellipse cx="152" cy="109" rx="10.5" ry="12" fill="url(#dIris)"/><circle cx="152" cy="109" r="5.6" fill="#0d0d10"/><circle cx="148.6" cy="104.6" r="2.7" fill="#fff"/><circle cx="156" cy="113" r="1.2" fill="#fff" opacity=".8"/></g></g></g>
            <ellipse cx="120" cy="130" rx="12.5" ry="9" fill="#141416"/><ellipse cx="116" cy="127" rx="4.5" ry="2.2" fill="#fff" opacity=".55"/>
            <path d="M120 139 L120 150 M120 150 C112 162 98 159 96 152 M120 150 C128 162 142 159 144 152" stroke="#25262b" stroke-width="2.6" fill="none" stroke-linecap="round"/>
            <path class="tongue" d="M111 154 C111 176 129 176 129 154 Z" fill="#ff7f93"/>
            <ellipse cx="66" cy="136" rx="9" ry="6" fill="#ff9aa8" opacity=".22"/><ellipse cx="174" cy="136" rx="9" ry="6" fill="#ff9aa8" opacity=".22"/>
          </g>
          <g class="sweat"><path d="M186 70 C180 82 180 90 186 92 C192 90 192 82 186 70 Z" fill="#79c4ff"/></g>
        </g>
        <g class="zz"><text x="170" y="60">Z</text><text x="186" y="42">z</text><text x="200" y="26">z</text></g>
      </svg>`,
  cat: `<svg viewBox="0 0 240 250" aria-label="일꾼 고양이">
        <defs>
          <linearGradient id="cBody" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f2a04c"/><stop offset="1" stop-color="#d9822f"/></linearGradient>
          <linearGradient id="cHead" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6aa56"/><stop offset="1" stop-color="#e58f3a"/></linearGradient>
          <linearGradient id="cWhite" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fffaf2"/><stop offset="1" stop-color="#f1e6d6"/></linearGradient>
          <radialGradient id="cIris" cx=".4" cy=".3" r=".9"><stop offset="0" stop-color="#d4f27c"/><stop offset="1" stop-color="#5fae3e"/></radialGradient>
          <linearGradient id="cLap" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#dfe3ea"/><stop offset="1" stop-color="#aeb4c0"/></linearGradient>
        </defs>
        <ellipse cx="120" cy="244" rx="90" ry="9" fill="#0002"/>
        <g class="bodywrap">
          <g class="tail"><path d="M36 240 C8 238 -2 214 12 194 C17 188 26 191 23 198 C17 212 24 224 44 226 Z" fill="#ec9640"/><path d="M14 200 L24 204 M10 214 L21 215 M16 228 L26 224" stroke="#c46f1f" stroke-width="3.2" stroke-linecap="round" fill="none"/></g>
          <path d="M30 250 C30 200 72 174 120 174 C168 174 210 200 210 250 Z" fill="url(#cBody)"/>
          <path d="M70 250 C72 222 82 204 98 194 M170 250 C168 222 158 204 142 194" stroke="#c46f1f" stroke-width="5" fill="none" stroke-linecap="round" opacity=".5"/>
          <path d="M96 250 C100 210 110 192 120 190 C130 192 140 210 144 250 Z" fill="url(#cWhite)"/>
          <g class="head">
            <g class="earL"><path d="M60 96 L54 34 L110 66 Z" fill="#ec9640"/><path d="M69 86 L66 52 L98 70 Z" fill="#f6a9ac"/></g>
            <g class="earR"><path d="M180 96 L186 34 L130 66 Z" fill="#ec9640"/><path d="M171 86 L174 52 L142 70 Z" fill="#f6a9ac"/></g>
            <ellipse cx="120" cy="114" rx="76" ry="64" fill="url(#cHead)"/>
            <path d="M120 54 L120 78 M104 56 L107 76 M136 56 L133 76" stroke="#c46f1f" stroke-width="5" stroke-linecap="round" opacity=".75"/>
            <path d="M46 112 L60 108 M46 124 L62 122 M194 112 L180 108 M194 124 L178 122" stroke="#c46f1f" stroke-width="4" stroke-linecap="round" opacity=".6"/>
            <ellipse cx="120" cy="142" rx="32" ry="23" fill="url(#cWhite)"/>
            <g><g class="eye-open"><g class="lid pv"><ellipse cx="86" cy="110" rx="16" ry="17" fill="url(#cIris)"/><ellipse class="pupil pv" cx="86" cy="111" rx="5" ry="12.5" fill="#101114"/><circle cx="80.5" cy="104" r="3.6" fill="#fff"/><circle cx="92" cy="118" r="1.6" fill="#fff" opacity=".8"/></g></g>
              <path class="arc" d="M71 114 C77 100 95 100 101 114" stroke="#5a3210" stroke-width="5" fill="none" stroke-linecap="round"/></g>
            <g><g class="eye-open"><g class="lid pv"><ellipse cx="154" cy="110" rx="16" ry="17" fill="url(#cIris)"/><ellipse class="pupil pv" cx="154" cy="111" rx="5" ry="12.5" fill="#101114"/><circle cx="148.5" cy="104" r="3.6" fill="#fff"/><circle cx="160" cy="118" r="1.6" fill="#fff" opacity=".8"/></g></g>
              <path class="arc" d="M139 114 C145 100 163 100 169 114" stroke="#5a3210" stroke-width="5" fill="none" stroke-linecap="round"/></g>
            <path d="M111 131 L129 131 L120 142 Z" fill="#f08c9c" stroke="#f08c9c" stroke-width="2" stroke-linejoin="round"/>
            <path d="M120 142 L120 148 M120 148 C114 157 103 155 101 148 M120 148 C126 157 137 155 139 148" stroke="#6b3a1a" stroke-width="2.4" fill="none" stroke-linecap="round"/>
            <path d="M80 142 L34 132 M80 149 L32 150 M82 156 L38 168 M160 142 L206 132 M160 149 L208 150 M158 156 L202 168" stroke="#fff" stroke-width="1.8" stroke-linecap="round" opacity=".85"/>
            <ellipse cx="62" cy="140" rx="9" ry="6" fill="#ff9aa8" opacity=".3"/><ellipse cx="178" cy="140" rx="9" ry="6" fill="#ff9aa8" opacity=".3"/>
          </g>
          <g class="laptop">
            <rect x="58" y="186" width="124" height="64" rx="9" fill="url(#cLap)"/>
            <rect class="screen" x="66" y="192" width="108" height="3" rx="1.5" fill="#6aa0ff"/>
            <circle cx="120" cy="220" r="7.5" fill="#fff" opacity=".65"/>
            <ellipse class="pawL" cx="92" cy="188" rx="17" ry="12" fill="#ec9640"/><ellipse class="pawR" cx="148" cy="188" rx="17" ry="12" fill="#ec9640"/>
            <path d="M86 186 L86 192 M92 185 L92 192 M98 186 L98 192 M142 186 L142 192 M148 185 L148 192 M154 186 L154 192" stroke="#fffaf2" stroke-width="2" stroke-linecap="round"/>
          </g>
          <g class="sweat"><path d="M190 76 C184 88 184 96 190 98 C196 96 196 88 190 76 Z" fill="#79c4ff"/></g>
        </g>
        <g class="sparks"><path class="spk pv" d="M40 62 l4 10 10 4 -10 4 -4 10 -4 -10 -10 -4 10 -4z" fill="#ffd54a"/><path class="spk pv" d="M204 54 l3 8 8 3 -8 3 -3 8 -3 -8 -8 -3 8 -3z" fill="#ffd54a"/><path class="spk pv" d="M214 120 l3 7 7 3 -7 3 -3 7 -3 -7 -7 -3 7 -3z" fill="#fff"/></g>
      </svg>`,
  // 일의 종류(motion) 표시 — 고양이 머리 옆 말풍선. 스킨을 써도 그대로 보인다(data-motion 으로 하나만 켜진다)
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
    // 일하는 중 = 일반 매크로가 도는 중, 또는 상시 매크로가 ctx.motion() 으로 잠깐 일하는 모습을 보이는 중
    // ctx.motion(hold=) 이 끝났으면 META 기본 모습으로(상시 매크로는 기본이 없으니 지켜보기로) 돌아간다
    const motionOf = m => (!m.motion_until || m.motion_until > now) ? m.motion : m.motion_default;
    const active = m => !!motionOf(m);
    const working = macros.filter(m => m.running && (!m.service || active(m)));
    let dog, dogText;
    if (!on.length) { dog = 'sleep'; dogText = '쿨쿨… 상시 매크로를 켜면 깨울게요'; }
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
   고양이 "work" 는 일의 종류별로 "work:web" · "work:desktop" · "work:write" · "work:mail" · "work:search" 를 따로 줄 수 있다(없으면 work). */
window.PetSkin = {
  async list(){ try { return await (await fetch('/api/skins')).json(); } catch (e) { return []; } },
  async load(id){
    if (!id) return null;
    try {
      const r = await fetch('/skin/' + encodeURIComponent(id) + '/skin.json');
      if (!r.ok) return null;
      const m = await r.json(); m._id = id; m._cache = {}; return m;
    } catch (e) { return null; }
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
  url(manifest, file){ return '/skin/' + encodeURIComponent(manifest._id) + '/' + encodeURIComponent(file); },
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
    } else if (this.isVideo(o.file)) {
      el = document.createElement('video'); el.src = this.url(manifest, o.file); el.loop = true; el.muted = true; el.autoplay = true; el.playsInline = true;
    } else {
      el = document.createElement('img'); el.src = this.url(manifest, o.file); el.alt = ''; el.draggable = false;
    }
    el.className = 'skin-media';
    if (o.pixel) el.style.imageRendering = 'pixelated';                   // 도트 그림이 번지지 않게
    if (o.frames && o.frames.length === 1) el.classList.add('still');    // 한 장짜리 자세(잠자기 등)는 숨 쉬듯 살짝 움직인다
    if (o.filter) el.style.filter = o.filter;
    if (o.flip) el.style.transform = 'scaleX(-1)';
    if (o.scale) { el.style.width = (o.scale * 100) + '%'; el.style.margin = '0 auto'; }
    return el;
  },
  dispose(el){ if (el && el._timer) clearInterval(el._timer); if (el && el.remove) el.remove(); },
  render(manifest, petEl, artEl, kind, mood, bark, motion){  // 허브 화면과 펫이 같이 쓴다: 상태에 맞는 스킨을 art 칸에 그린다(없으면 내장 그림)
    const spec = manifest ? this.file(manifest, kind, mood, bark, motion) : null;
    petEl.classList.toggle('skinned', !!spec);
    const cur = artEl.querySelector('.skin-media');
    if (!spec) { if (cur) this.dispose(cur); artEl._spec = null; return; }
    if (artEl._spec !== spec) { if (cur) this.dispose(cur); artEl.append(this.element(manifest, spec)); artEl._spec = spec; }
  },
  reset(artEl){ const cur = artEl.querySelector('.skin-media'); if (cur) this.dispose(cur); artEl._spec = null; }
};
