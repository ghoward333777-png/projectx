"use strict";
// Photo-driven talking face: the author's own photo, animated by warping the face-landmark mesh.
// The mouth is driven to measured geometry (lip opening as a share of mouth width, mouth width as a share of
// face height) — by default the generic viseme table, and after the Photo Real Lab has analysed a reference
// recording, the author's own per-sound shapes, timing lead, smoothing, lip-closure hold, blinks and head motion.
(function () {
  const IN_UP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308];
  const IN_LO = [308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78];
  const RING = new Set(IN_UP.concat(IN_LO));
  const LID = { up: [[246, 7], [161, 163], [160, 144], [159, 145], [158, 153], [157, 154], [173, 155],
                     [466, 249], [388, 390], [387, 373], [386, 374], [385, 380], [384, 381], [398, 382]] };
  const DEFAULT_SHAPE = { sil: [0.02, 0.0], PP: [0.0, -0.05], FF: [0.06, 0.0], TH: [0.12, 0.0], DD: [0.14, 0.0], kk: [0.2, 0.0], CH: [0.13, -0.18],
    SS: [0.07, 0.07], nn: [0.1, 0.0], RR: [0.13, -0.12], aa: [0.5, 0.05], E: [0.28, 0.14], I: [0.14, 0.18], O: [0.38, -0.2], U: [0.16, -0.3] };

  // Bowyer–Watson Delaunay triangulation (points [[x, y]] → triangles [[i, j, k]])
  function delaunay(pts) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    pts.forEach(([x, y]) => { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); });
    const d = Math.max(maxX - minX, maxY - minY) * 20, cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    const P = pts.concat([[cx - d, cy - d], [cx, cy + d], [cx + d, cy - d]]), n = pts.length;
    let tris = [[n, n + 1, n + 2]];
    const circ = t => {
      const [ax, ay] = P[t[0]], [bx, by] = P[t[1]], [qx, qy] = P[t[2]];
      const D = 2 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by));
      const ux = ((ax * ax + ay * ay) * (by - qy) + (bx * bx + by * by) * (qy - ay) + (qx * qx + qy * qy) * (ay - by)) / D;
      const uy = ((ax * ax + ay * ay) * (qx - bx) + (bx * bx + by * by) * (ax - qx) + (qx * qx + qy * qy) * (bx - ax)) / D;
      return [ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2];
    };
    let cc = tris.map(circ);
    for (let i = 0; i < n; i++) {
      const [px, py] = P[i], bad = [], keep = [], keepC = [];
      tris.forEach((t, k) => { const c = cc[k]; if ((px - c[0]) ** 2 + (py - c[1]) ** 2 <= c[2]) bad.push(t); else { keep.push(t); keepC.push(c); } });
      const edges = new Map();
      bad.forEach(t => [[t[0], t[1]], [t[1], t[2]], [t[2], t[0]]].forEach(([a, b]) => {
        const k = a < b ? a + "," + b : b + "," + a; edges.set(k, edges.has(k) ? null : [a, b]); }));
      tris = keep; cc = keepC;
      edges.forEach(e => { if (e) { const t = [e[0], e[1], i]; tris.push(t); cc.push(circ(t)); } });
    }
    return tris.filter(t => t[0] < n && t[1] < n && t[2] < n);
  }

  class PhotoFace {
    constructor(el, persona, params) {
      this.el = el; this.params = Object.assign({ gap_gain: 1, width_gain: 1, lead_ms: 60, smooth_ms: 60, closure_hold_ms: 0, blink_per_min: 15, head_sd_deg: 1, shapes: {} }, params || {});
      this.state = { gap: 0, width: null, t: null, blink: 0, closedUntil: -1 };
      this.ready = new Promise((res, rej) => {
        const img = new Image(); img.crossOrigin = "anonymous";
        img.onload = () => { try { this._setup(img, persona.landmarks); res(); } catch (e) { rej(e); } };
        img.onerror = () => rej(new Error("the author's photo could not be loaded"));
        img.src = persona.photoUrl;
      });
    }
    _setup(img, lm) {
      if (!lm || lm.length < 400) throw new Error("this persona has no face landmarks yet — open it once so the photo is analysed");
      const scale = Math.min(1, 900 / Math.max(img.width, img.height));
      const W = Math.round(img.width * scale), H = Math.round(img.height * scale);
      const src = document.createElement("canvas"); src.width = W; src.height = H; src.getContext("2d").drawImage(img, 0, 0, W, H);
      this.src = src;
      const pts = lm.slice(0, 468).map(([x, y]) => [x * W, y * H]);           // iris points left out: the lids cover them
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      pts.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); });
      const fw = x1 - x0, fh = y1 - y0, fcx = (x0 + x1) / 2, fcy = (y0 + y1) / 2;
      // fixed anchors: a ring around the face and the crop corners, so the neck and background stretch, never tear
      const crop = { x: Math.max(0, fcx - fw * 1.05), y: Math.max(0, y0 - fh * 0.45), w: 0, h: 0 };
      crop.w = Math.min(W, fcx + fw * 1.05) - crop.x; crop.h = Math.min(H, y1 + fh * 0.55) - crop.y;
      const anchors = [];
      for (let a = 0; a < 24; a++) anchors.push([fcx + Math.cos(a / 24 * 2 * Math.PI) * fw * 0.78, fcy + Math.sin(a / 24 * 2 * Math.PI) * fh * 0.72]);
      [[crop.x, crop.y], [crop.x + crop.w, crop.y], [crop.x, crop.y + crop.h], [crop.x + crop.w, crop.y + crop.h],
       [crop.x + crop.w / 2, crop.y], [crop.x + crop.w / 2, crop.y + crop.h], [crop.x, crop.y + crop.h / 2], [crop.x + crop.w, crop.y + crop.h / 2]].forEach(p => anchors.push(p));
      this.base = pts.concat(anchors.filter(([x, y]) => x >= 0 && y >= 0 && x <= W && y <= H));
      this.nFace = pts.length;
      this.tris = delaunay(this.base);
      const P = i => this.base[i];
      this.M = [(P(13)[0] + P(14)[0]) / 2, (P(13)[1] + P(14)[1]) / 2];
      this.W0 = Math.hypot(P(61)[0] - P(291)[0], P(61)[1] - P(291)[1]);
      this.G0 = Math.hypot(P(13)[0] - P(14)[0], P(13)[1] - P(14)[1]);
      this.F = Math.hypot(P(10)[0] - P(152)[0], P(10)[1] - P(152)[1]);
      this.fc = [fcx, fcy]; this.crop = crop;
      // weights per point (fixed): jaw drop, upper-lip lift, mouth-width scaling
      const F = this.F, M = this.M, W0 = this.W0;
      this.wJaw = this.base.map(([x, y], i) => i >= this.nFace ? 0 : Math.exp(-(((x - M[0]) / (0.36 * F)) ** 2)) * Math.max(0, Math.min(1, (y - M[1] + 0.006 * F) / (0.02 * F))) *
        (1 - 0.15 * Math.max(0, Math.min(1, (y - M[1]) / (0.25 * F)))));
      this.wUp = this.base.map(([x, y], i) => i >= this.nFace || y > M[1] + 0.004 * F ? 0 : Math.exp(-(((x - M[0]) / (0.6 * W0)) ** 2)) * Math.max(0, 1 - (M[1] - y) / (0.07 * F)));
      this.wWide = this.base.map(([x, y], i) => i >= this.nFace ? 0 : Math.exp(-((Math.hypot(x - M[0], (y - M[1]) * 1.6) / (0.85 * W0)) ** 2)));
      this.lid = LID.up.map(([u, l]) => [u, l]);
      // which triangles can move (any vertex with weight), and which are the inside of the mouth
      const moving = new Set();
      this.base.forEach((_, i) => { if (this.wJaw[i] > 0.002 || this.wUp[i] > 0.002 || this.wWide[i] > 0.01) moving.add(i); });
      this.lid.forEach(([u]) => moving.add(u));
      this.dyn = this.tris.filter(t => !(RING.has(t[0]) && RING.has(t[1]) && RING.has(t[2])) && t.some(i => moving.has(i)));
      // the inside of the mouth: when the photo already shows it (teeth visible), it is warped from the photo itself
      this.inner = this.tris.filter(t => RING.has(t[0]) && RING.has(t[1]) && RING.has(t[2]));
      this.photoOpen = this.G0 > 0.04 * this.W0;
      const cv = document.createElement("canvas");
      const outW = Math.min(this.el.clientWidth || 360, 480);
      cv.width = Math.round(outW); cv.height = Math.round(outW * crop.h / crop.w);
      cv.style.width = "100%"; cv.style.maxWidth = outW + "px"; cv.style.borderRadius = "10px";
      this.el.innerHTML = ""; this.el.appendChild(cv);
      const lab = document.createElement("div"); lab.className = "small muted"; lab.textContent = "AI narrator — generated with consent"; this.el.appendChild(lab);
      this.cv = cv; this.ctx = cv.getContext("2d");
      this.state.width = W0;
    }
    // geometry targets for a viseme: [lip gap as share of mouth width, mouth width in pixels]
    _target(v) {
      const p = this.params, s = p.shapes && p.shapes[v];
      if (s) return [s.gap * p.gap_gain, s.width * this.F * p.width_gain];
      const d = DEFAULT_SHAPE[v] || DEFAULT_SHAPE.sil;
      return [d[0] * p.gap_gain, this.W0 * (1 + d[1]) * p.width_gain];
    }
    // one frame at audio time t (seconds); deterministic for a given sequence of t
    frame(track, t, expr) {
      const p = this.params, vs = (track && track.visemes) || [];
      const tt = t + p.lead_ms / 1000;                                    // the lips lead the sound
      let v = "sil";
      for (const x of vs) { if (x.start <= tt && tt < x.end) { v = x.v; break; } }
      let [g, w] = this._target(v);
      if (v === "PP") this.state.closedUntil = tt + (p.closure_hold_ms || 0) / 1000;
      if (tt < this.state.closedUntil) g = 0;                             // lips stay shut long enough on p / b / m
      const dt = this.state.t === null ? 1 / 30 : Math.max(0, Math.min(0.2, t - this.state.t));
      this.state.t = t;
      const a = 1 - Math.exp(-dt / Math.max(0.005, p.smooth_ms / 1000));
      this.state.gap += (g - this.state.gap) * a;
      this.state.width += (w - this.state.width) * a;
      // blinks at the author's rate (deterministic schedule), and slow head micro-motion
      const period = 60 / Math.max(1, p.blink_per_min), ph = (t + 0.37 * Math.sin(t * 0.7)) % period;
      this.state.blink = ph < 0.12 ? Math.sin(Math.PI * ph / 0.12) : 0;
      this._draw(expr || {}, t);
    }
    // the generic live mouth (avatar mirroring a camera): m.open / m.width as in the cartoon faces
    draw(m, t) {
      const g = Math.max(0, (m.open || 0) * 0.55 * this.params.gap_gain), w = this.W0 * (0.85 + 0.5 * ((m.width || 0.55) - 0.55)) * this.params.width_gain;
      this.state.gap = g; this.state.width = w; this.state.blink = 0;
      this._draw(m, t || 0);
    }
    _draw(expr, t) {
      if (!this.ctx) return;
      const s = this.state, M = this.M, F = this.F;
      const scaleW = s.width / this.W0;
      const G = Math.max(-this.G0, s.gap * s.width - this.G0);           // opening change in pixels (negative closes a photo's open mouth)
      const smile = (expr.smile || 0) * 0.012 * F;
      const pts = this.base.map(([x, y], i) => {
        if (i >= this.nFace) return [x, y];
        let nx = x + (x - M[0]) * (scaleW - 1) * this.wWide[i];
        let ny = y + G * 0.72 * this.wJaw[i] - G * 0.28 * this.wUp[i];
        if (smile) ny -= smile * this.wWide[i] * Math.min(1, ((x - M[0]) / (this.W0 / 2)) ** 2);
        return [nx, ny];
      });
      if (s.blink > 0) this.lid.forEach(([u, l]) => { pts[u] = [pts[u][0], pts[u][1] + (pts[l][1] - pts[u][1]) * 0.92 * s.blink]; });
      const c = this.ctx, cr = this.crop, k = this.cv.width / cr.w;
      const hd = (this.params.head_sd_deg || 0) * Math.PI / 180;
      const rot = hd * (0.8 * Math.sin(t * 0.53) + 0.6 * Math.sin(t * 1.31 + 1.1)) / 1.4;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, this.cv.width, this.cv.height);
      const view = () => { c.setTransform(k, 0, 0, k, -cr.x * k, -cr.y * k); c.translate(this.fc[0], this.fc[1] + F * 0.6); c.rotate(rot); c.scale(1.02, 1.02); c.translate(-this.fc[0], -this.fc[1] - F * 0.6); };
      view();
      c.drawImage(this.src, 0, 0);
      const warp = tr => {                                                 // affine-map one triangle of the photo
        const [a, b, d] = tr, s0 = this.base[a], s1 = this.base[b], s2 = this.base[d], d0 = pts[a], d1 = pts[b], d2 = pts[d];
        const den = (s1[0] - s0[0]) * (s2[1] - s0[1]) - (s2[0] - s0[0]) * (s1[1] - s0[1]);
        if (Math.abs(den) < 1e-6) return;
        const m11 = ((d1[0] - d0[0]) * (s2[1] - s0[1]) - (d2[0] - d0[0]) * (s1[1] - s0[1])) / den;
        const m12 = ((d2[0] - d0[0]) * (s1[0] - s0[0]) - (d1[0] - d0[0]) * (s2[0] - s0[0])) / den;
        const m21 = ((d1[1] - d0[1]) * (s2[1] - s0[1]) - (d2[1] - d0[1]) * (s1[1] - s0[1])) / den;
        const m22 = ((d2[1] - d0[1]) * (s1[0] - s0[0]) - (d1[1] - d0[1]) * (s2[0] - s0[0])) / den;
        const dx = d0[0] - m11 * s0[0] - m12 * s0[1], dy = d0[1] - m21 * s0[0] - m22 * s0[1];
        const cx = (d0[0] + d1[0] + d2[0]) / 3, cy = (d0[1] + d1[1] + d2[1]) / 3, grow = q => [q[0] + (q[0] - cx) * 0.04, q[1] + (q[1] - cy) * 0.04];
        const [e0, e1, e2] = [grow(d0), grow(d1), grow(d2)];
        c.save(); c.beginPath(); c.moveTo(e0[0], e0[1]); c.lineTo(e1[0], e1[1]); c.lineTo(e2[0], e2[1]); c.closePath(); c.clip();
        c.transform(m11, m21, m12, m22, dx, dy); c.drawImage(this.src, 0, 0); c.restore();
      };
      const ring = IN_UP.concat(IN_LO.slice(1, -1)).map(i => pts[i]);
      const open = Math.hypot(pts[13][0] - pts[14][0], pts[13][1] - pts[14][1]);
      const ringPath = () => { c.beginPath(); ring.forEach((q, i) => i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1])); c.closePath(); };
      // inside of the mouth first, so the lips are drawn over its edge
      if (open > 1.0) {
        c.save(); ringPath(); c.clip();
        const tw = Math.hypot(pts[78][0] - pts[308][0], pts[78][1] - pts[308][1]), mx = (pts[78][0] + pts[308][0]) / 2;
        const gr = c.createRadialGradient(mx, (pts[13][1] + pts[14][1]) / 2, 0, mx, (pts[13][1] + pts[14][1]) / 2, tw * 0.6);
        gr.addColorStop(0, "#2a0d0d"); gr.addColorStop(0.7, "#4a1818"); gr.addColorStop(1, "#6b2a2a");
        c.fillStyle = gr; c.fillRect(mx - tw, pts[13][1] - open, tw * 2, open * 3);
        if (this.photoOpen) this.inner.forEach(warp);                     // the author's own teeth, stretched with the lips
        else {
          const th = Math.min(open * 0.36, F * 0.024), y0 = pts[13][1];
          const tg = c.createLinearGradient(0, y0, 0, y0 + th);           // upper teeth: a row, shaded toward the gum and the corners
          tg.addColorStop(0, "#d9d4c7"); tg.addColorStop(0.35, "#f4f1e8"); tg.addColorStop(1, "#cfc9ba");
          c.fillStyle = tg; c.beginPath(); c.ellipse(mx, y0, tw * 0.4, th, 0, 0, Math.PI); c.fill();
          c.strokeStyle = "rgba(120,110,95,.35)"; c.lineWidth = Math.max(0.5, tw / 160);
          for (let k = -3; k <= 3; k++) { const x = mx + k * tw * 0.085; c.beginPath(); c.moveTo(x, y0); c.lineTo(x, y0 + th * Math.sqrt(Math.max(0, 1 - (k * 0.085 / 0.4) ** 2))); c.stroke(); }
          if (open > F * 0.035) {                                         // tongue and lower teeth when the jaw is well open
            c.fillStyle = "rgba(170,80,85,.9)"; c.beginPath(); c.ellipse(mx, pts[14][1] - open * 0.12, tw * 0.3, open * 0.22, 0, Math.PI, 2 * Math.PI); c.fill();
            c.fillStyle = "rgba(225,220,208,.75)"; c.beginPath(); c.ellipse(mx, pts[14][1], tw * 0.3, th * 0.45, 0, Math.PI, 2 * Math.PI); c.fill();
          }
          const sh = c.createLinearGradient(mx - tw / 2, 0, mx + tw / 2, 0);  // corners of the mouth in shadow
          sh.addColorStop(0, "rgba(0,0,0,.55)"); sh.addColorStop(0.2, "rgba(0,0,0,0)"); sh.addColorStop(0.8, "rgba(0,0,0,0)"); sh.addColorStop(1, "rgba(0,0,0,.55)");
          c.fillStyle = sh; c.fillRect(mx - tw, pts[13][1] - open, tw * 2, open * 3);
        }
        c.restore();
      }
      for (const tr of this.dyn) warp(tr);
    }
    dispose() { this.el.innerHTML = ""; this.ctx = null; }
  }
  // The author's own mouth: real frames of the perfect sample (one per sound, a rest frame, a blink frame), aligned on
  // the eyes and nose and blended in with feathered masks — real lips, teeth and light; nothing in the mouth is painted.
  const ANCHORS = [33, 133, 362, 263, 1, 168, 6, 197, 195, 5, 4];
  function similarity(P, Q) {                           // least-squares rotation + scale + shift taking points P onto Q
    const n = P.length; let mpx = 0, mpy = 0, mqx = 0, mqy = 0;
    for (let i = 0; i < n; i++) { mpx += P[i][0]; mpy += P[i][1]; mqx += Q[i][0]; mqy += Q[i][1]; }
    mpx /= n; mpy /= n; mqx /= n; mqy /= n;
    let sa = 0, sb = 0, sp = 0;
    for (let i = 0; i < n; i++) {
      const px = P[i][0] - mpx, py = P[i][1] - mpy, qx = Q[i][0] - mqx, qy = Q[i][1] - mqy;
      sa += px * qx + py * qy; sb += px * qy - py * qx; sp += px * px + py * py;
    }
    const a = sa / sp, b = sb / sp;
    return [a, b, mqx - (a * mpx - b * mpy), mqy - (b * mpx + a * mpy)];
  }
  class LibraryFace {
    constructor(el, persona, params) {
      this.el = el; this.params = Object.assign({ lead_ms: 60, smooth_ms: 60, blink_per_min: 15, head_sd_deg: 1, shapes: {} }, params || {});
      this.state = { t: null, cur: "rest", prev: "rest", since: 0, blink: 0, gap: 0 };
      this.lib = {};
      this.ready = Promise.all(Object.entries(persona.library).map(([v, ent]) => new Promise((res, rej) => {
        const im = new Image();
        im.onload = () => { this.lib[v] = { img: im, L: ent.landmarks.map(([x, y]) => [x * im.width, y * im.height]) }; res(); };
        im.onerror = () => rej(new Error("a frame of the mouth library could not be loaded"));
        im.src = persona.libUrl(v);
      }))).then(() => this._setup());
    }
    _setup() {
      const base = this.lib.rest, L = base.L, W = base.img.width, H = base.img.height;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      L.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); });
      const fw = x1 - x0, fh = y1 - y0;
      this.fc = [(x0 + x1) / 2, (y0 + y1) / 2]; this.F = fh;
      this.crop = { x: Math.max(0, this.fc[0] - fw * 1.05), y: Math.max(0, y0 - fh * 0.45) };
      this.crop.w = Math.min(W, this.fc[0] + fw * 1.05) - this.crop.x; this.crop.h = Math.min(H, y1 + fh * 0.55) - this.crop.y;
      const mouth = [(L[13][0] + L[14][0]) / 2, (L[13][1] + L[14][1]) / 2], chin = L[152], nose = L[4];
      const mask = (cx, cy, rx, ry, inner) => {          // feathered ellipse: solid inside, fading to nothing at the edge
        const m = document.createElement("canvas"); m.width = W; m.height = H; const g = m.getContext("2d");
        g.translate(cx, cy); g.scale(1, ry / rx);
        const gr = g.createRadialGradient(0, 0, 0, 0, 0, rx); gr.addColorStop(0, "rgba(0,0,0,1)"); gr.addColorStop(inner, "rgba(0,0,0,1)"); gr.addColorStop(1, "rgba(0,0,0,0)");
        g.fillStyle = gr; g.beginPath(); g.arc(0, 0, rx, 0, 2 * Math.PI); g.fill();
        return m;
      };
      const mouthMask = mask(mouth[0], (nose[1] + chin[1] * 1.6) / 2.6 + fh * 0.02, fw * 0.36, (chin[1] - nose[1]) * 0.78, 0.62);
      const eyeMask = document.createElement("canvas"); eyeMask.width = W; eyeMask.height = H;
      [[33, 133], [362, 263]].forEach(([a, b]) => {
        const cx = (L[a][0] + L[b][0]) / 2, cy = (L[a][1] + L[b][1]) / 2, w = Math.hypot(L[a][0] - L[b][0], L[a][1] - L[b][1]);
        eyeMask.getContext("2d").drawImage(mask(cx, cy, w * 0.85, w * 0.55, 0.55), 0, 0);
      });
      const anchors = ANCHORS.map(i => L[i]);
      this.patch = {};
      for (const [v, e] of Object.entries(this.lib)) {   // each frame aligned to the rest frame and masked, once
        if (v === "rest") continue;
        const [a, b, tx, ty] = similarity(ANCHORS.map(i => e.L[i]), anchors);
        const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
        g.setTransform(a, b, -b, a, tx, ty); g.drawImage(e.img, 0, 0); g.setTransform(1, 0, 0, 1, 0, 0);
        g.globalCompositeOperation = "destination-in"; g.drawImage(v === "blink" ? eyeMask : mouthMask, 0, 0);
        this.patch[v] = c;
      }
      const cv = document.createElement("canvas"), outW = Math.min(this.el.clientWidth || 360, 480);
      cv.width = Math.round(outW); cv.height = Math.round(outW * this.crop.h / this.crop.w);
      cv.style.width = "100%"; cv.style.maxWidth = outW + "px"; cv.style.borderRadius = "10px";
      this.el.innerHTML = ""; this.el.appendChild(cv);
      const lab = document.createElement("div"); lab.className = "small muted"; lab.textContent = "AI narrator — generated with consent (the author's own mouth, from the reference recording)"; this.el.appendChild(lab);
      this.cv = cv; this.ctx = cv.getContext("2d");
    }
    _pick(v) {
      if (this.patch[v]) return v;
      return "rest";                                     // silence, or a sound the sample did not show clearly
    }
    frame(track, t, expr) {
      const p = this.params, tt = t + p.lead_ms / 1000;
      let v = "sil";
      for (const x of (track && track.visemes) || []) { if (x.start <= tt && tt < x.end) { v = x.v; break; } }
      const want = this._pick(v);
      if (this.state.t === null) { this.state.cur = this.state.prev = want; this.state.since = t - 1; }
      if (want !== this.state.cur) { this.state.prev = this.state.mix >= 0.5 ? this.state.cur : this.state.prev; this.state.cur = want; this.state.since = t; }
      this.state.t = t;
      this.state.mix = 1 - Math.exp(-(t - this.state.since) / Math.max(0.005, p.smooth_ms / 1000));
      const period = 60 / Math.max(1, p.blink_per_min), ph = (t + 0.37 * Math.sin(t * 0.7)) % period;
      this.state.blink = ph < 0.12 ? Math.sin(Math.PI * ph / 0.12) : 0;
      this._draw(t);
    }
    draw(m, t) {                                         // live mirroring: the library frame whose opening is closest
      const target = (m.open || 0) * 0.55; let best = "rest", d = Math.abs(target);
      for (const v of Object.keys(this.patch)) { const s = this.params.shapes[v]; if (s && v !== "blink" && Math.abs(s.gap - target) < d) { d = Math.abs(s.gap - target); best = v; } }
      this.state.prev = this.state.cur = best; this.state.mix = 1; this.state.blink = 0;
      this._draw(t || 0);
    }
    _draw(t) {
      if (!this.ctx) return;
      const c = this.ctx, cr = this.crop, k = this.cv.width / cr.w, F = this.F;
      const hd = (this.params.head_sd_deg || 0) * Math.PI / 180, rot = hd * (0.8 * Math.sin(t * 0.53) + 0.6 * Math.sin(t * 1.31 + 1.1)) / 1.4;
      c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, this.cv.width, this.cv.height);
      c.setTransform(k, 0, 0, k, -cr.x * k, -cr.y * k);
      c.translate(this.fc[0], this.fc[1] + F * 0.6); c.rotate(rot); c.scale(1.02, 1.02); c.translate(-this.fc[0], -this.fc[1] - F * 0.6);
      c.drawImage(this.lib.rest.img, 0, 0);
      const s = this.state;
      if (s.prev !== "rest") c.drawImage(this.patch[s.prev], 0, 0);
      if (s.cur !== "rest") { c.globalAlpha = s.mix; c.drawImage(this.patch[s.cur], 0, 0); c.globalAlpha = 1; }
      else if (s.prev !== "rest") { c.globalAlpha = s.mix; c.drawImage(this.lib.rest.img, 0, 0); c.globalAlpha = 1; }   // back to rest
      if (s.blink > 0 && this.patch.blink) { c.globalAlpha = s.blink; c.drawImage(this.patch.blink, 0, 0); c.globalAlpha = 1; }
    }
    dispose() { this.el.innerHTML = ""; this.ctx = null; }
  }
  // the author's face: the real-mouth library when the perfect sample provided one, else the warped photo
  window.authorFace = (el, persona, params) => persona.library && persona.library.rest ? new LibraryFace(el, persona, params) : new PhotoFace(el, persona, params);
  window.PhotoFace = PhotoFace;
  window.LibraryFace = LibraryFace;
})();
