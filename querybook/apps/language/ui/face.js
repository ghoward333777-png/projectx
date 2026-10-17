"use strict";
// Talking face: plays a viseme track in sync with an <audio> element. 2D (SVG) here; 3D + VR in face3d.mjs.
// Mouth parameters per viseme: open (0..1), width (0..1), round (0..1), teeth (0..1), tongue (0..1), press (lips together 0..1)
const MOUTH = {
  sil: { open: 0.02, width: 0.55, round: 0.0, teeth: 0.0, tongue: 0.0, press: 0.6 },
  PP:  { open: 0.0,  width: 0.50, round: 0.1, teeth: 0.0, tongue: 0.0, press: 1.0 },
  FF:  { open: 0.10, width: 0.56, round: 0.0, teeth: 1.0, tongue: 0.0, press: 0.3 },
  TH:  { open: 0.18, width: 0.56, round: 0.0, teeth: 0.8, tongue: 1.0, press: 0.0 },
  DD:  { open: 0.22, width: 0.56, round: 0.0, teeth: 0.7, tongue: 0.4, press: 0.0 },
  kk:  { open: 0.32, width: 0.55, round: 0.0, teeth: 0.4, tongue: 0.2, press: 0.0 },
  CH:  { open: 0.22, width: 0.38, round: 0.6, teeth: 0.8, tongue: 0.0, press: 0.0 },
  SS:  { open: 0.10, width: 0.64, round: 0.0, teeth: 1.0, tongue: 0.0, press: 0.0 },
  nn:  { open: 0.16, width: 0.56, round: 0.0, teeth: 0.5, tongue: 0.8, press: 0.0 },
  RR:  { open: 0.22, width: 0.42, round: 0.5, teeth: 0.3, tongue: 0.3, press: 0.0 },
  aa:  { open: 0.85, width: 0.62, round: 0.0, teeth: 0.3, tongue: 0.2, press: 0.0 },
  E:   { open: 0.45, width: 0.72, round: 0.0, teeth: 0.5, tongue: 0.1, press: 0.0 },
  I:   { open: 0.22, width: 0.78, round: 0.0, teeth: 0.8, tongue: 0.0, press: 0.0 },
  O:   { open: 0.62, width: 0.40, round: 0.85, teeth: 0.1, tongue: 0.0, press: 0.0 },
  U:   { open: 0.26, width: 0.30, round: 1.0, teeth: 0.0, tongue: 0.0, press: 0.0 },
};
const KEYS = ["open", "width", "round", "teeth", "tongue", "press"];
// Expression per voice emotion: smile (-1 frown … 1 smile) and brow (-1 lowered … 1 inner brows raised)
const EXPRESSIONS = { neutral: { smile: 0, brow: 0 }, happy: { smile: 0.7, brow: 0.1 }, excited: { smile: 0.6, brow: 0.3 }, tender: { smile: 0.3, brow: 0.5 },
  calm: { smile: 0.15, brow: 0 }, sad: { smile: -0.5, brow: 0.8 }, fearful: { smile: -0.2, brow: 0.9 }, angry: { smile: -0.3, brow: -0.8 },
  serious: { smile: 0, brow: -0.3 }, surprised: { smile: 0, brow: 0.6 }, disgusted: { smile: -0.4, brow: -0.5 } };

// Mouth parameters at time t: the current viseme blended with its neighbours over ±60 ms (coarticulation),
// with the jaw following the measured loudness a little.
function mouthAt(track, t) {
  const vs = track.visemes, out = Object.assign({}, MOUTH.sil);
  if (!vs || !vs.length) return out;
  let i = 0, lo = 0, hi = vs.length - 1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (vs[m].end < t) lo = m + 1; else { i = m; hi = m - 1; } }
  const cur = vs[Math.min(i, vs.length - 1)], blendT = 0.06;
  const w = {}; w[cur.v] = 1;
  const prev = vs[i - 1], next = vs[i + 1];
  if (prev && t - cur.start < blendT) { const a = 0.5 * (1 - (t - cur.start) / blendT); w[prev.v] = (w[prev.v] || 0) + a; w[cur.v] -= a; }
  if (next && cur.end - t < blendT) { const a = 0.5 * (1 - (cur.end - t) / blendT); w[next.v] = (w[next.v] || 0) + a; w[cur.v] -= a; }
  KEYS.forEach(k => { out[k] = 0; Object.entries(w).forEach(([v, a]) => { out[k] += a * (MOUTH[v] || MOUTH.sil)[k]; }); });
  const jaw = track.jaw && track.jaw.length ? track.jaw[Math.min(track.jaw.length - 1, Math.max(0, Math.round(t * (track.jaw_fps || 100))))] : 0;
  if (cur.v !== "PP" && cur.v !== "sil") out.open = Math.min(1, 0.75 * out.open + 0.35 * jaw);
  out.viseme = cur.v;
  return out;
}

class Face2D {
  constructor(el) {
    this.el = el;
    el.innerHTML = '<svg viewBox="0 0 300 340" class="face2d" role="img" aria-label="Talking face">' +
      '<defs><radialGradient id="fskin" cx="50%" cy="40%" r="65%"><stop offset="0%" stop-color="#f6d3b8"/><stop offset="100%" stop-color="#e2ac8b"/></radialGradient></defs>' +
      '<ellipse cx="150" cy="170" rx="118" ry="150" fill="url(#fskin)" stroke="#c98d6c" stroke-width="2"/>' +
      '<path d="M40 120 Q150 -20 260 120 Q240 60 150 50 Q60 60 40 120Z" fill="#5a3b2a"/>' +
      '<g id="f-eyes"><ellipse cx="105" cy="140" rx="20" ry="11" fill="#fff"/><ellipse cx="195" cy="140" rx="20" ry="11" fill="#fff"/>' +
      '<circle cx="105" cy="140" r="7" fill="#3b2a1f"/><circle cx="195" cy="140" r="7" fill="#3b2a1f"/>' +
      '<rect id="f-lid-l" x="83" y="128" width="44" height="0" fill="#e8b897"/><rect id="f-lid-r" x="173" y="128" width="44" height="0" fill="#e8b897"/></g>' +
      '<path id="f-brow-l" d="M82 118 Q105 106 128 116" stroke="#4a3022" stroke-width="5" fill="none" stroke-linecap="round"/><path id="f-brow-r" d="M172 116 Q195 106 218 118" stroke="#4a3022" stroke-width="5" fill="none" stroke-linecap="round"/>' +
      '<path d="M150 150 L140 200 Q150 207 160 200" stroke="#c98d6c" stroke-width="3" fill="none" stroke-linecap="round"/>' +
      '<g id="f-mouth"><path id="f-cavity" fill="#5b1f1f"/><rect id="f-teeth-u" fill="#fbfbf6" rx="3"/><rect id="f-teeth-l" fill="#f1f1ea" rx="3"/>' +
      '<ellipse id="f-tongue" fill="#d36b6b"/><path id="f-lip-u" fill="#b5555a"/><path id="f-lip-l" fill="#c4626a"/></g>' +
      '<text id="f-vis" x="150" y="332" text-anchor="middle" font-size="13" fill="currentColor" opacity=".6"></text></svg>';
    this.blinkAt = 1.2;
  }
  draw(m, t) {
    const $e = id => this.el.querySelector("#" + id);
    const cx = 150, cy0 = 240, cy = cy0 - 7 * (m.smile || 0);          // mouth corners rise with a smile
    const W = 30 + 48 * m.width * (1 - 0.35 * m.round), H = 3 + 38 * m.open, R = m.round;
    const top = cy0 - H * 0.35, bot = cy0 + H * 0.65, lip = 7 - 3 * m.press;
    const curve = (y0, dir, h) => "M" + (cx - W) + " " + cy + " Q" + (cx - W * 0.5) + " " + (y0 - dir * h * R * 0.3) + " " + cx + " " + y0 + " Q" + (cx + W * 0.5) + " " + (y0 - dir * h * R * 0.3) + " " + (cx + W) + " " + cy;
    $e("f-cavity").setAttribute("d", curve(top, 1, H) + " Q" + (cx + W * 0.5) + " " + (bot + H * R * 0.2) + " " + cx + " " + bot + " Q" + (cx - W * 0.5) + " " + (bot + H * R * 0.2) + " " + (cx - W) + " " + cy + "Z");
    $e("f-cavity").setAttribute("opacity", m.open > 0.03 ? 1 : 0);
    const tw = W * 1.1, th = Math.min(H * 0.35, 9) * m.teeth;
    $e("f-teeth-u").setAttribute("x", cx - tw / 2); $e("f-teeth-u").setAttribute("y", top); $e("f-teeth-u").setAttribute("width", tw); $e("f-teeth-u").setAttribute("height", th);
    $e("f-teeth-l").setAttribute("x", cx - tw / 2.4); $e("f-teeth-l").setAttribute("y", bot - th * 0.8); $e("f-teeth-l").setAttribute("width", tw / 1.2); $e("f-teeth-l").setAttribute("height", th * 0.8);
    $e("f-tongue").setAttribute("cx", cx); $e("f-tongue").setAttribute("cy", bot - H * 0.15 - 8 * m.tongue); $e("f-tongue").setAttribute("rx", W * 0.55); $e("f-tongue").setAttribute("ry", Math.max(0, H * 0.25 * (0.5 + m.tongue)));
    $e("f-tongue").setAttribute("opacity", m.open > 0.1 ? 1 : 0);
    $e("f-lip-u").setAttribute("d", "M" + (cx - W - 3) + " " + cy + " Q" + (cx - W * 0.5) + " " + (top - lip - 4) + " " + cx + " " + (top - lip + 2) + " Q" + (cx + W * 0.5) + " " + (top - lip - 4) + " " + (cx + W + 3) + " " + cy +
      " Q" + (cx + W * 0.5) + " " + top + " " + cx + " " + top + " Q" + (cx - W * 0.5) + " " + top + " " + (cx - W - 3) + " " + cy + "Z");
    $e("f-lip-l").setAttribute("d", "M" + (cx - W - 3) + " " + cy + " Q" + (cx - W * 0.5) + " " + (bot + H * R * 0.2) + " " + cx + " " + bot + " Q" + (cx + W * 0.5) + " " + (bot + H * R * 0.2) + " " + (cx + W + 3) + " " + cy +
      " Q" + (cx + W * 0.5) + " " + (bot + lip + 6) + " " + cx + " " + (bot + lip + 6) + " Q" + (cx - W * 0.5) + " " + (bot + lip + 6) + " " + (cx - W - 3) + " " + cy + "Z");
    const br = m.brow || 0, inner = 116 - 9 * br, mid = 106 - 3 * Math.abs(br);
    $e("f-brow-l").setAttribute("d", "M82 118 Q105 " + mid + " 128 " + inner);
    $e("f-brow-r").setAttribute("d", "M172 " + inner + " Q195 " + mid + " 218 118");
    const blink = Math.max(0, 1 - Math.abs(t - this.blinkAt) / 0.08);
    if (t > this.blinkAt + 0.2) this.blinkAt = t + 2.5 + ((t * 7.3) % 2);
    ["f-lid-l", "f-lid-r"].forEach(id => $e(id).setAttribute("height", 24 * blink));
    $e("f-vis").textContent = m.viseme ? m.viseme : "";
  }
  dispose() { this.el.innerHTML = ""; }
}

// Controller: one face area, 2D or 3D, synced to an audio element.
class TalkingFace {
  constructor(el) { this.el = el; this.mode = "2d"; this.track = null; this.audio = null; this.impl = null; this.raf = null; this.expr = EXPRESSIONS.neutral; }
  setEmotion(name) { this.expr = EXPRESSIONS[name] || EXPRESSIONS.neutral; }
  async setMode(mode) {
    const old = this.impl;
    this.impl = null;                                  // the draw loop pauses while the new face loads
    if (old) old.dispose();
    this.mode = mode;
    if (mode === "3d") {
      const mod = await import("./face3d.mjs");
      this.impl = new mod.Face3D(this.el);
    } else this.impl = new Face2D(this.el);
    this.impl.draw(Object.assign(mouthAt(this.track || { visemes: [] }, 0), this.expr), 0);
  }
  // drive the mouth directly (e.g. from a tracked camera face) instead of from an audio track
  live(m) {
    cancelAnimationFrame(this.raf); this.raf = null;
    if (this.impl) this.impl.draw(Object.assign({ viseme: "" }, this.expr, m), performance.now() / 1000);
  }
  attach(audio, track) {
    this.audio = audio; this.track = track;
    cancelAnimationFrame(this.raf);
    const loop = () => {
      const t = audio ? audio.currentTime : 0;
      if (this.impl) this.impl.draw(Object.assign(mouthAt(this.track, (audio && !audio.paused) || t > 0 ? t : 0), this.expr), performance.now() / 1000);
      this.raf = requestAnimationFrame(loop);
    };
    loop();
  }
}
window.TalkingFace = TalkingFace;
window.mouthAt = mouthAt;
