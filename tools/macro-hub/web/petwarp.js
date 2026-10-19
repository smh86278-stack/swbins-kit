/* 펫 그물 변형 — 그림 한 장에 보이지 않는 그물을 씌워 일부만 휘게 한다(Live2D 간이판, WebGL).
   고개 갸웃·끄덕이기·앞발 들기·숨쉬기를 그림을 새로 그리지 않고 만든다.

   skin.json 상태 값(또는 품종)에 "rig" 를 주면 web/pets.js 가 그림 대신 이 캔버스를 쓴다(WebGL 이 없으면 그냥 그림).
     "rig": {"neck": [0.55, 0.50], "pawL": [0.39, 0.93], "pawR": [0.70, 0.92]}
   좌표는 그림 한 변을 1 로 본 값 — neck 고개가 도는 목 축 · pawL/pawR 앞발 가운데.
   선택: band(목 둘레 부드러운 폭, 0.12) · pawRad(앞발 둘레, 0.11) */
(() => {
  const PAD = 0.2;                                   // 캔버스 위쪽 여유(그림 높이 대비) — 고개를 기울여도 귀가 안 잘리게
  const VS = `
attribute vec2 uv;
uniform vec2 neck, pawL, pawR; uniform float band, pawRad, pad;
uniform float tilt, nod, lift, breath, pawSide;
varying vec2 vUv;
void main(){
  vec2 p = uv;
  p.y = 1.0 - (1.0 - p.y) * (1.0 + breath);                          // 숨쉬기: 바닥 기준으로 위아래
  float wh = smoothstep(neck.y + band * 0.5, neck.y - band, uv.y);   // 머리: 목 선 위쪽일수록 많이
  vec2 d = p - neck; float a = tilt * wh;
  p = neck + vec2(d.x * cos(a) - d.y * sin(a), d.x * sin(a) + d.y * cos(a));
  p.y += nod * wh * (0.4 + 0.6 * smoothstep(neck.y, 0.0, uv.y));     // 끄덕: 위로 갈수록 많이
  vec2 paw = pawSide < 0.0 ? pawL : pawR;                            // 앞발 들기: 발 둘레만 위로
  float wp = exp(-dot(uv - paw, uv - paw) / (pawRad * pawRad));
  p.y -= lift * wp; p.x += lift * wp * 0.25 * (pawSide < 0.0 ? -1.0 : 1.0);
  vUv = uv;
  gl_Position = vec4(p.x * 2.0 - 1.0, 1.0 - 2.0 * (p.y + pad) / (1.0 + pad), 0.0, 1.0);
}`;
  const FS = `precision mediump float; varying vec2 vUv; uniform sampler2D img; void main(){ gl_FragColor = texture2D(img, vUv); }`;

  let supported = null;
  const release = gl => { const x = gl && gl.getExtension('WEBGL_lose_context'); if (x) x.loseContext(); };   // 브라우저는 GPU 캔버스를 16개쯤만 둔다 — 다 쓴 건 바로 돌려준다
  function ok() {
    if (supported === null) {
      try { const gl = document.createElement('canvas').getContext('webgl'); supported = !!gl; release(gl); } catch (e) { supported = false; }
    }
    return supported;
  }

  function make(canvas, image, rig) {                // → draw({tilt, nod, lift, pawSide, breath})
    const gl = canvas.getContext('webgl', {premultipliedAlpha: false, alpha: true});
    const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o)); return o; };
    const pr = gl.createProgram(); gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pr); gl.useProgram(pr);
    const N = 40, pts = [];
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++)
      for (const [a, b] of [[i, j], [i + 1, j], [i, j + 1], [i + 1, j], [i + 1, j + 1], [i, j + 1]]) pts.push(a / N, b / N);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(pts), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr, 'uv'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    const U = n => gl.getUniformLocation(pr, n);
    gl.uniform2fv(U('neck'), rig.neck); gl.uniform2fv(U('pawL'), rig.pawL || [0.38, 0.93]); gl.uniform2fv(U('pawR'), rig.pawR || [0.68, 0.93]);
    gl.uniform1f(U('band'), rig.band || 0.12); gl.uniform1f(U('pawRad'), rig.pawRad || 0.11); gl.uniform1f(U('pad'), PAD);
    const draw = s => {
      gl.viewport(0, 0, canvas.width, canvas.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(U('tilt'), s.tilt || 0); gl.uniform1f(U('nod'), s.nod || 0); gl.uniform1f(U('lift'), s.lift || 0);
      gl.uniform1f(U('breath'), s.breath || 0); gl.uniform1f(U('pawSide'), s.pawSide || -1);
      gl.drawArrays(gl.TRIANGLES, 0, pts.length / 2);
    };
    draw.gl = gl;
    return draw;
  }

  /* 상태(fx)별 몸짓 — t 초 → 변형 값. 갸웃은 몇 초에 한 번씩만(계속 흔들면 정신없다) */
  const ease = x => x < 0 ? 0 : x > 1 ? 1 : x * x * (3 - 2 * x);
  const every = (t, period, dur) => { const k = (t % period) / dur; return k < 1 ? Math.sin(Math.PI * ease(k)) : 0; };   // 주기마다 한 번 0→1→0
  const MOTION = {
    idle: t => ({breath: 0.012 * Math.sin(t * 2.2), tilt: 0.13 * every(t, 7, 1.8) * (Math.floor(t / 7) % 2 ? 1 : -1)}),
    sleep: t => ({breath: 0.018 * Math.sin(t * 1.3), nod: 0.03}),
    worried: t => ({breath: 0.01 * Math.sin(t * 3), tilt: 0.05 * Math.sin(t * 2.6), nod: 0.012}),
    bark: t => ({nod: 0.025 * Math.max(0, Math.sin(t * 9)), tilt: 0.08, lift: 0.08 * every(t, 1.6, 1.0), pawSide: -1}),
    work: t => ({nod: 0.015 * Math.max(0, Math.sin(t * 7)), breath: 0.008 * Math.sin(t * 2.2)}),
    happy: t => ({tilt: 0.12 * Math.sin(t * 3.2), lift: 0.07 * every(t, 1.4, 0.9), pawSide: 1, breath: 0.01 * Math.sin(t * 2.2)}),
    sad: t => ({nod: 0.03, tilt: -0.05, breath: 0.01 * Math.sin(t * 1.6)}),
  };

  /* 스킨 그림 자리에 넣을 캔버스. el._stop() 으로 멈춘다(web/pets.js 의 dispose 가 부른다) */
  function element(url, rig, fx) {
    const c = document.createElement('canvas');
    c.width = 400; c.height = Math.round(400 * (1 + PAD));
    c.style.marginTop = -(PAD * 100) + '%';            // 위쪽 여유만큼 끌어올려 그림 자리는 그대로
    let raf = 0, stopped = false;
    const img = new Image();
    img.onload = () => {
      if (stopped) return;
      let draw;
      try { draw = make(c, img, rig); c._gl = draw.gl; } catch (e) { return; }
      const move = MOTION[fx] || MOTION.idle, t0 = performance.now() / 1000 - Math.random() * 7;
      const loop = () => { if (stopped) return; draw(move(performance.now() / 1000 - t0)); raf = requestAnimationFrame(loop); };
      loop();
    };
    img.src = url;
    c._stop = () => { stopped = true; cancelAnimationFrame(raf); release(c._gl); };
    return c;
  }

  window.PetWarp = {ok, make, element, MOTION, PAD};
})();
