"use strict";
// Depth avatar: a portrait animated by all 52 ARKit face channels on its 478-point 3D face mesh.
// Each channel moves its own region (lips, jaw, cheeks, nose, lids, irises, brows) by a displacement field
// defined on the mesh in face-relative units; head yaw and pitch rotate the mesh in 3D using the landmarks'
// depth (the nose moves against the cheeks), roll turns the whole head. The photo is warped triangle by triangle.
(function () {
  const BS = ["eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeSquintLeft", "eyeWideLeft",
    "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeSquintRight", "eyeWideRight",
    "jawForward", "jawLeft", "jawRight", "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight", "mouthDimpleLeft", "mouthDimpleRight",
    "mouthStretchLeft", "mouthStretchRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthPressLeft", "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthUpperUpLeft", "mouthUpperUpRight",
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "cheekPuff", "cheekSquintLeft",
    "cheekSquintRight", "noseSneerLeft", "noseSneerRight", "tongueOut"];
  const IDX = Object.fromEntries(BS.map((k, i) => [k, i])), MC = IDX.mouthClose, JAW = IDX.jawOpen;
  // MediaPipe face-mesh landmarks ("Left" = the subject's left = the right of the picture)
  const OUT_UP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291], OUT_LO = [291, 375, 321, 405, 314, 17, 84, 181, 91, 146, 61];
  const IN_UP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308], IN_LO = [308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78];
  const RING = new Set(IN_UP.concat(IN_LO));
  const EYE = {
    L: { up: [466, 388, 387, 386, 385, 384, 398], lo: [249, 390, 373, 374, 380, 381, 382], iris: [473, 474, 475, 476, 477], outer: 263, inner: 362,
         brow: [336, 296, 334, 293, 300, 285, 295, 282, 283, 276], browIn: [336, 285, 296, 295], browOut: [300, 276, 293, 283], cheek: 425, wing: [358, 327, 294, 278] },
    R: { up: [246, 161, 160, 159, 158, 157, 173], lo: [7, 163, 144, 145, 153, 154, 155], iris: [468, 469, 470, 471, 472], outer: 33, inner: 133,
         brow: [107, 66, 105, 63, 70, 55, 65, 52, 53, 46], browIn: [107, 55, 66, 65], browOut: [70, 46, 63, 53], cheek: 205, wing: [129, 98, 64, 48] },
  };
  // viseme → mouth channels, used only until the Visual Speech Engine's motion arrives
  const VIS = { sil: { jawOpen: 0.03 }, PP: { mouthClose: 0.5, mouthPressLeft: 0.45, mouthPressRight: 0.45 }, FF: { mouthRollLower: 0.55, jawOpen: 0.08, mouthUpperUpLeft: 0.15, mouthUpperUpRight: 0.15 },
    TH: { jawOpen: 0.15, tongueOut: 0.5 }, DD: { jawOpen: 0.14, mouthStretchLeft: 0.12, mouthStretchRight: 0.12 }, kk: { jawOpen: 0.18 },
    CH: { jawOpen: 0.12, mouthFunnel: 0.45, mouthPucker: 0.25 }, SS: { jawOpen: 0.08, mouthStretchLeft: 0.22, mouthStretchRight: 0.22, mouthSmileLeft: 0.08, mouthSmileRight: 0.08 },
    nn: { jawOpen: 0.12, mouthStretchLeft: 0.1, mouthStretchRight: 0.1 }, RR: { jawOpen: 0.12, mouthFunnel: 0.4, mouthPucker: 0.32 },
    aa: { jawOpen: 0.5, mouthLowerDownLeft: 0.3, mouthLowerDownRight: 0.3 }, E: { jawOpen: 0.25, mouthStretchLeft: 0.35, mouthStretchRight: 0.35, mouthSmileLeft: 0.15, mouthSmileRight: 0.15 },
    I: { jawOpen: 0.1, mouthStretchLeft: 0.45, mouthStretchRight: 0.45, mouthSmileLeft: 0.3, mouthSmileRight: 0.3 }, O: { jawOpen: 0.35, mouthFunnel: 0.55, mouthPucker: 0.2 },
    U: { jawOpen: 0.15, mouthFunnel: 0.3, mouthPucker: 0.65 } };

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
  const smooth = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

  class DepthFace {
    constructor(el, avatar, params) {
      this.el = el; this.avatar = avatar;
      this.params = Object.assign({ lead_ms: 40, smooth_ms: 35, head_gain: 1, label: avatar.label || "Synthetic avatar — AI-generated" }, params || {});
      this.cur = new Float32Array(BS.length); this.head = [0, 0, 0]; this.t = null;
      this.ready = new Promise((res, rej) => {
        const img = new Image();
        img.onload = () => { try { this._setup(img, avatar.landmarks); res(); } catch (e) { rej(e); } };
        img.onerror = () => rej(new Error("the portrait could not be loaded"));
        img.src = avatar.imageUrl;
      });
    }
    _setup(img, lm) {
      if (!lm || lm.length < 468) throw new Error("this avatar has not been analysed yet — use “Analyse faces” in the library");
      const scale = Math.min(1, 1000 / Math.max(img.width, img.height));
      const W = Math.round(img.width * scale), H = Math.round(img.height * scale);
      const src = document.createElement("canvas"); src.width = W; src.height = H; src.getContext("2d").drawImage(img, 0, 0, W, H);
      this.src = src;
      const pts3 = lm.slice(0, 478).map(p => [p[0] * W, p[1] * H, (p[2] || 0) * W]);
      this.hasIris = pts3.length >= 478; this.hasDepth = lm[0].length > 2;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      pts3.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); });
      const fw = x1 - x0, fh = y1 - y0, fcx = (x0 + x1) / 2, fcy = (y0 + y1) / 2;
      const crop = { x: Math.max(0, fcx - fw * 1.1), y: Math.max(0, y0 - fh * 0.5) };
      crop.w = Math.min(W, fcx + fw * 1.1) - crop.x; crop.h = Math.min(H, y1 + fh * 0.55) - crop.y;
      // fixed anchors: a ring around the face and the crop's edge, so hair, neck and background stretch, never tear
      const anchors = [];
      for (let a = 0; a < 32; a++) anchors.push([fcx + Math.cos(a / 32 * 2 * Math.PI) * fw * 0.8, fcy + Math.sin(a / 32 * 2 * Math.PI) * fh * 0.74, 0]);
      for (let k = 0; k <= 4; k++) [[crop.x + crop.w * k / 4, crop.y], [crop.x + crop.w * k / 4, crop.y + crop.h], [crop.x, crop.y + crop.h * k / 4], [crop.x + crop.w, crop.y + crop.h * k / 4]]
        .forEach(([x, y]) => anchors.push([x, y, 0]));
      this.base3 = pts3.concat(anchors.filter(([x, y]) => x >= 0 && y >= 0 && x <= W && y <= H));
      this.base = this.base3.map(([x, y]) => [x, y]);
      this.nFace = pts3.length;
      // triangulate a copy with the mouth slightly open, so no triangle bridges the lips (they part cleanly when the jaw drops)
      const Pb = i => this.base[i], Fh = Math.hypot(Pb(10)[0] - Pb(152)[0], Pb(10)[1] - Pb(152)[1]);
      const cRb = Pb(61), cLb = Pb(291), Wmb = Math.hypot(cRb[0] - cLb[0], cRb[1] - cLb[1]), Mb = [(Pb(13)[0] + Pb(14)[0]) / 2, (Pb(13)[1] + Pb(14)[1]) / 2];
      const lowSet = new Set(IN_LO.concat(OUT_LO).filter(i => ![61, 291, 78, 308].includes(i)));
      const upSet = new Set(IN_UP.concat(OUT_UP).filter(i => ![61, 291, 78, 308].includes(i)));
      const midY = x => cRb[1] + (cLb[1] - cRb[1]) * (x - cRb[0]) / ((cLb[0] - cRb[0]) || 1);
      const triPts = this.base.map(([x, y], i) => {
        if (i >= this.nFace || upSet.has(i)) return [x, y];
        const near = Math.abs(x - Mb[0]) < 0.75 * Wmb && y < Mb[1] + 0.45 * Fh;
        return lowSet.has(i) || (near && y > midY(x) + 0.002 * Fh) ? [x, y + 0.04 * Fh] : [x, y];
      });
      this.tris = delaunay(triPts);
      this.inner = this.tris.filter(t => RING.has(t[0]) && RING.has(t[1]) && RING.has(t[2]));
      this.mesh = this.tris.filter(t => !(RING.has(t[0]) && RING.has(t[1]) && RING.has(t[2])));
      const P = i => this.base3[i];
      this.F = Math.hypot(P(10)[0] - P(152)[0], P(10)[1] - P(152)[1]);
      this.Wm = Math.hypot(P(61)[0] - P(291)[0], P(61)[1] - P(291)[1]);
      this.M = [(P(13)[0] + P(14)[0]) / 2, (P(13)[1] + P(14)[1]) / 2];
      this.fc = [fcx, fcy]; this.crop = crop;
      this.zMean = pts3.reduce((s, p) => s + p[2], 0) / pts3.length;
      this.pivot = [fcx, P(152)[1] + this.F * 0.35, this.zMean + this.F * 0.5];      // the neck
      this._fields();
      const cv = document.createElement("canvas"), outW = Math.min(this.el.clientWidth || 380, 480);
      cv.width = Math.round(outW); cv.height = Math.round(outW * crop.h / crop.w);
      cv.style.width = "100%"; cv.style.maxWidth = outW + "px"; cv.style.borderRadius = "10px";
      this.el.innerHTML = ""; this.el.appendChild(cv);
      const lab = document.createElement("div"); lab.className = "small muted"; lab.textContent = this.params.label; this.el.appendChild(lab);
      this.cv = cv; this.ctx = cv.getContext("2d");
      this._draw();
    }
    // per-channel displacement fields over the mesh (pixels at channel value 1), built once per portrait
    _fields() {
      const n = this.base3.length, B = this.base3, F = this.F, Wm = this.Wm, M = this.M, nF = this.nFace;
      const D = BS.map(() => new Float32Array(n * 3));
      const add = (k, i, dx, dy, dz) => { if (i >= nF) return; const a = D[IDX[k]]; a[3 * i] += dx; a[3 * i + 1] += dy; a[3 * i + 2] += dz || 0; };
      const g = (i, c, s) => Math.exp(-(((B[i][0] - c[0]) ** 2 + (B[i][1] - c[1]) ** 2) / (s * s)));
      // mouth geometry: midline between the lips, corners, which side of the midline each point is
      const cL = B[291], cR = B[61], mid = x => { const t = (x - cR[0]) / ((cL[0] - cR[0]) || 1); return cR[1] + (cL[1] - cR[1]) * t; };
      const LOWER = new Set(IN_LO.concat(OUT_LO).filter(i => ![61, 291, 78, 308].includes(i)));
      const UPPER = new Set(IN_UP.concat(OUT_UP).filter(i => ![61, 291, 78, 308].includes(i)));
      const below = i => LOWER.has(i) ? 1 : UPPER.has(i) ? 0 : smooth(-0.004 * F, 0.006 * F, B[i][1] - mid(B[i][0]));   // lower lip and chin side
      const above = i => 1 - below(i);
      const lipZ = i => Math.exp(-((Math.hypot(B[i][0] - M[0], (B[i][1] - M[1]) * 1.5) / (0.75 * Wm)) ** 2));
      const side = (i, s) => smooth(-0.15 * Wm, 0.25 * Wm, s * (B[i][0] - M[0]));                // 1 on that side (s=+1: picture right = subject left)
      const jawW = i => Math.exp(-(((B[i][0] - M[0]) / (0.42 * F)) ** 2)) * below(i) * (1 - 0.25 * smooth(0, 0.3 * F, B[i][1] - M[1]));
      for (let i = 0; i < nF; i++) {
        const [x, y] = B[i], lz = lipZ(i), up = above(i), lo = below(i), sL = side(i, 1), sR = side(i, -1), dxm = x - M[0];
        // jaw: the lower face swings down and slightly back; the lower lip rides with it
        add("jawOpen", i, -dxm * 0.04 * jawW(i), 0.17 * F * jawW(i), 0.03 * F * jawW(i));
        add("jawForward", i, 0, 0.006 * F * jawW(i), -0.05 * F * jawW(i));
        add("jawLeft", i, 0.045 * F * jawW(i), 0, 0); add("jawRight", i, -0.045 * F * jawW(i), 0, 0);
        // lips: closing against an open jaw, rounding, sideways, corners
        add("mouthClose", i, 0, -0.17 * F * jawW(i) * lz * 1.1, 0);
        add("mouthFunnel", i, -dxm * 0.28 * lz, (lo - up) * 0.025 * F * lz, -0.035 * F * lz);
        add("mouthPucker", i, -dxm * 0.42 * lz, -(y - M[1]) * 0.15 * lz, -0.05 * F * lz);
        add("mouthLeft", i, 0.13 * Wm * lz, 0, 0); add("mouthRight", i, -0.13 * Wm * lz, 0, 0);
        for (const [k, s, c] of [["Left", 1, cL], ["Right", -1, cR]]) {
          const cw = g(i, c, 0.32 * Wm), sd = s > 0 ? sL : sR;
          add("mouthSmile" + k, i, s * 0.16 * Wm * cw, -0.055 * F * cw, 0);
          add("mouthFrown" + k, i, s * 0.03 * Wm * cw, 0.045 * F * cw, 0);
          add("mouthDimple" + k, i, s * 0.07 * Wm * cw, -0.008 * F * cw, 0.02 * F * cw);
          add("mouthStretch" + k, i, s * 0.17 * Wm * cw, 0.02 * F * cw, 0);
          add("mouthPress" + k, i, 0, (up - lo) * 0.012 * F * lz * sd, 0);
          add("mouthLowerDown" + k, i, 0, 0.04 * F * lz * lo * sd, 0);
          add("mouthUpperUp" + k, i, 0, -0.035 * F * lz * up * sd, 0);
        }
        add("mouthRollLower", i, 0, -0.018 * F * lz * lo, 0.01 * F * lz * lo);
        add("mouthRollUpper", i, 0, 0.016 * F * lz * up, 0.01 * F * lz * up);
        add("mouthShrugLower", i, 0, -0.03 * F * lz * lo, -0.01 * F * lz * lo);
        add("mouthShrugUpper", i, 0, -0.02 * F * lz * up, 0);
        // cheeks and nose
        for (const [k, s, e] of [["Left", 1, EYE.L], ["Right", -1, EYE.R]]) {
          const ck = g(i, B[e.cheek], 0.16 * F);
          add("cheekSquint" + k, i, 0, -0.022 * F * ck, 0);
          add("cheekPuff", i, s * 0.035 * F * g(i, [M[0] + s * 0.75 * Wm, M[1] - 0.02 * F], 0.13 * F), 0, -0.02 * F * ck);
          const wing = e.wing.reduce((a, j) => [a[0] + B[j][0] / e.wing.length, a[1] + B[j][1] / e.wing.length], [0, 0]);
          add("noseSneer" + k, i, s * 0.004 * F * g(i, wing, 0.05 * F), -0.016 * F * g(i, wing, 0.05 * F), 0);
          // brows
          const browC = e.brow.reduce((a, j) => [a[0] + B[j][0] / e.brow.length, a[1] + B[j][1] / e.brow.length], [0, 0]);
          const bw = g(i, browC, 0.11 * F) * smooth(0.02 * F, -0.02 * F, y - (B[e.up[3]][1] - 0.01 * F));
          const inC = [B[e.browIn[0]][0], B[e.browIn[0]][1]], outC = [B[e.browOut[0]][0], B[e.browOut[0]][1]];
          add("browDown" + k, i, -s * 0.008 * F * bw, 0.022 * F * bw, 0);
          add("browInnerUp", i, 0, -0.03 * F * g(i, inC, 0.06 * F) * (bw > 0.01 ? 1 : 0.4), 0);
          add("browOuterUp" + k, i, 0, -0.03 * F * g(i, outC, 0.06 * F), 0);
        }
      }
      // eyelids, squint, wide, and the irises (gaze)
      for (const [k, e] of [["Left", EYE.L], ["Right", EYE.R]]) {
        const ew = Math.hypot(B[e.outer][0] - B[e.inner][0], B[e.outer][1] - B[e.inner][1]);
        e.up.forEach((u, j) => {
          const l = e.lo[j], dy = B[l][1] - B[u][1];
          add("eyeBlink" + k, u, (B[l][0] - B[u][0]) * 0.9, dy * 0.92, 0);
          add("eyeWide" + k, u, 0, -dy * 0.3, 0);
          add("eyeSquint" + k, l, 0, -dy * 0.3, 0);
          add("eyeLookUp" + k, u, 0, -dy * 0.12, 0); add("eyeLookDown" + k, u, 0, dy * 0.25, 0);
        });
        if (this.hasIris) e.iris.forEach(j => {
          const s = k === "Left" ? 1 : -1;                                   // "out" is toward the ear
          add("eyeLookOut" + k, j, s * 0.13 * ew, 0, 0); add("eyeLookIn" + k, j, -s * 0.13 * ew, 0, 0);
          add("eyeLookUp" + k, j, 0, -0.06 * ew, 0); add("eyeLookDown" + k, j, 0, 0.07 * ew, 0);
          add("eyeBlink" + k, j, 0, 0.08 * ew, 0);
        });
      }
      this.D = D;
    }
    // channel values for audio time t: the VSE's 52-channel motion when present, else the viseme fallback
    _target(track, t) {
      const out = new Float32Array(BS.length), mo = track && track.motion;
      if (mo && mo.frames && mo.frames.length && mo.frames[0].bs) {
        const f = Math.max(0, t * mo.fps), i = Math.min(mo.frames.length - 1, Math.floor(f)), j = Math.min(mo.frames.length - 1, i + 1), w = f - i;
        const a = mo.frames[i], b = mo.frames[j];
        for (let k = 0; k < BS.length; k++) out[k] = a.bs[k] * (1 - w) + b.bs[k] * w;
        this.headT = a.head_pose_deg.map((x, q) => x * (1 - w) + b.head_pose_deg[q] * w);
        return out;
      }
      let v = "sil";
      for (const x of (track && track.visemes) || []) { if (x.start <= t && t < x.end) { v = x.v; break; } }
      Object.entries(VIS[v] || VIS.sil).forEach(([k, x]) => { out[IDX[k]] = x; });
      const per = 3.7, ph = (t + 0.4 * Math.sin(t * 0.7)) % per, bl = ph < 0.14 ? Math.sin(Math.PI * ph / 0.14) : 0;
      out[IDX.eyeBlinkLeft] = out[IDX.eyeBlinkRight] = bl;
      this.headT = [1.5 * Math.sin(0.9 * t), 0.8 * Math.sin(0.6 * t + 1), 0.6 * Math.sin(0.5 * t)];
      return out;
    }
    frame(track, t) {
      const tt = t + this.params.lead_ms / 1000, tgt = this._target(track, tt);
      const dt = this.t === null ? 1 : Math.max(0, Math.min(0.2, t - this.t)); this.t = t;
      const a = 1 - Math.exp(-dt / Math.max(0.005, this.params.smooth_ms / 1000));
      for (let k = 0; k < BS.length; k++) this.cur[k] += (tgt[k] - this.cur[k]) * (k === IDX.eyeBlinkLeft || k === IDX.eyeBlinkRight ? 1 : a);
      this.head = this.head.map((h, q) => h + ((this.headT || [0, 0, 0])[q] - h) * a);
      this._draw();
    }
    setChannels(values) { Object.entries(values || {}).forEach(([k, v]) => { if (k in IDX) this.cur[IDX[k]] = v; }); this._draw(); }
    draw(m) {                                                // live mirroring from a tracked camera face
      const v = {}; BS.forEach(k => { v[k] = 0; });
      v.jawOpen = Math.min(1, (m.open || 0) * 1.1); v.mouthStretchLeft = v.mouthStretchRight = Math.max(0, ((m.width || 0.55) - 0.55) * 2);
      v.mouthSmileLeft = v.mouthSmileRight = m.smile || 0;
      this.setChannels(v);
    }
    _points() {
      const n = this.base3.length, out = new Array(n), c = this.cur, D = this.D, nF = this.nFace, g = this.params.head_gain;
      const [yaw, pitch, roll] = this.head.map(d => d * g * Math.PI / 180), [px, py, pz] = this.pivot;
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
      for (let i = 0; i < n; i++) {
        let [x, y, z] = this.base3[i];
        if (i < nF) {
          for (let k = 0; k < c.length; k++) {
            const w = k === MC ? Math.min(c[k], c[JAW]) : c[k];               // lips can only close against an open jaw
            if (w > 0.002) { x += w * D[k][3 * i]; y += w * D[k][3 * i + 1]; z += w * D[k][3 * i + 2]; }
          }
          // head rotation about the neck: yaw (y axis), pitch (x axis), roll (z axis), then a weak perspective
          let X = x - px, Y = y - py, Z = z - pz;
          let X1 = X * cy + Z * sy, Z1 = -X * sy + Z * cy;
          let Y1 = Y * cp - Z1 * sp, Z2 = Y * sp + Z1 * cp;
          const X2 = X1 * cr - Y1 * sr, Y2 = X1 * sr + Y1 * cr;
          out[i] = [px + X2, py + Y2];                                      // orthographic: the face at rest maps exactly onto the portrait
        } else out[i] = [x, y];
      }
      return out;
    }
    _draw() {
      if (!this.ctx) return;
      const pts = this._points(), c = this.ctx, cr = this.crop, k = this.cv.width / cr.w, src = this.src, B = this.base, F = this.F;
      c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, this.cv.width, this.cv.height);
      c.setTransform(k, 0, 0, k, -cr.x * k, -cr.y * k);
      c.drawImage(src, 0, 0);
      const warp = tr => {
        const [a, b, d] = tr, s0 = B[a], s1 = B[b], s2 = B[d], d0 = pts[a], d1 = pts[b], d2 = pts[d];
        if (Math.abs(d0[0] - s0[0]) + Math.abs(d0[1] - s0[1]) + Math.abs(d1[0] - s1[0]) + Math.abs(d1[1] - s1[1]) + Math.abs(d2[0] - s2[0]) + Math.abs(d2[1] - s2[1]) < 0.05) return;
        const den = (s1[0] - s0[0]) * (s2[1] - s0[1]) - (s2[0] - s0[0]) * (s1[1] - s0[1]);
        if (Math.abs(den) < 1e-6) return;
        const m11 = ((d1[0] - d0[0]) * (s2[1] - s0[1]) - (d2[0] - d0[0]) * (s1[1] - s0[1])) / den;
        const m12 = ((d2[0] - d0[0]) * (s1[0] - s0[0]) - (d1[0] - d0[0]) * (s2[0] - s0[0])) / den;
        const m21 = ((d1[1] - d0[1]) * (s2[1] - s0[1]) - (d2[1] - d0[1]) * (s1[1] - s0[1])) / den;
        const m22 = ((d2[1] - d0[1]) * (s1[0] - s0[0]) - (d1[1] - d0[1]) * (s2[0] - s0[0])) / den;
        const dx = d0[0] - m11 * s0[0] - m12 * s0[1], dy = d0[1] - m21 * s0[0] - m22 * s0[1];
        const cx = (d0[0] + d1[0] + d2[0]) / 3, cy = (d0[1] + d1[1] + d2[1]) / 3, grow = q => [q[0] + (q[0] - cx) * 0.05, q[1] + (q[1] - cy) * 0.05];
        const [e0, e1, e2] = [grow(d0), grow(d1), grow(d2)];
        const sx = Math.max(0, Math.floor(Math.min(s0[0], s1[0], s2[0]) - 3)), sy = Math.max(0, Math.floor(Math.min(s0[1], s1[1], s2[1]) - 3));
        const sw = Math.min(src.width, Math.ceil(Math.max(s0[0], s1[0], s2[0]) + 3)) - sx, sh = Math.min(src.height, Math.ceil(Math.max(s0[1], s1[1], s2[1]) + 3)) - sy;
        if (sw <= 0 || sh <= 0) return;
        c.save(); c.beginPath(); c.moveTo(e0[0], e0[1]); c.lineTo(e1[0], e1[1]); c.lineTo(e2[0], e2[1]); c.closePath(); c.clip();
        c.transform(m11, m21, m12, m22, dx, dy); c.drawImage(src, sx, sy, sw, sh, sx, sy, sw, sh); c.restore();
      };
      // the inside of the mouth first (cavity, teeth, tongue), then the face over it
      const ring = IN_UP.concat(IN_LO.slice(1, -1)).map(i => pts[i]);
      const open = Math.hypot(pts[13][0] - pts[14][0], pts[13][1] - pts[14][1]);
      if (open > 1) {
        c.save(); c.beginPath(); ring.forEach((q, i) => i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1])); c.closePath(); c.clip();
        const tw = Math.hypot(pts[78][0] - pts[308][0], pts[78][1] - pts[308][1]), mx = (pts[78][0] + pts[308][0]) / 2, my = (pts[13][1] + pts[14][1]) / 2;
        const gr = c.createRadialGradient(mx, my, 0, mx, my, tw * 0.6);
        gr.addColorStop(0, "#140606"); gr.addColorStop(0.7, "#2c0e0e"); gr.addColorStop(1, "#45191a");
        c.fillStyle = gr; c.fillRect(mx - tw, pts[13][1] - open, tw * 2, open * 3);
        const th = Math.min(open * 0.34, F * 0.024), y0 = pts[13][1];
        const tg = c.createLinearGradient(0, y0, 0, y0 + th); tg.addColorStop(0, "#d6d0c3"); tg.addColorStop(0.35, "#f2eee5"); tg.addColorStop(1, "#cbc4b4");
        c.fillStyle = tg; c.beginPath(); c.ellipse(mx, y0, tw * 0.4, th, 0, 0, Math.PI); c.fill();
        const tongue = this.cur[IDX.tongueOut];
        if (open > F * 0.045) {                                // lower teeth and a resting tongue, low in a well-open mouth
          c.fillStyle = "rgba(118,48,54,.85)"; c.beginPath(); c.ellipse(mx, pts[14][1] + open * 0.02, tw * 0.24, open * 0.14, 0, Math.PI, 2 * Math.PI); c.fill();
          c.fillStyle = "rgba(222,216,204,.6)"; c.beginPath(); c.ellipse(mx, pts[14][1], tw * 0.28, th * 0.4, 0, Math.PI, 2 * Math.PI); c.fill();
        }
        if (tongue > 0.1) {                                    // tongue tip between the teeth (th), forward with tongueOut
          c.fillStyle = "rgba(170,82,88,.95)"; c.beginPath();
          c.ellipse(mx, (pts[13][1] + pts[14][1]) / 2 + open * 0.1, tw * (0.16 + 0.1 * tongue), Math.max(open * 0.35, F * 0.008) * (0.5 + 0.5 * tongue), 0, 0, 2 * Math.PI); c.fill();
        }
        const sh = c.createLinearGradient(mx - tw / 2, 0, mx + tw / 2, 0);
        sh.addColorStop(0, "rgba(0,0,0,.55)"); sh.addColorStop(0.2, "rgba(0,0,0,0)"); sh.addColorStop(0.8, "rgba(0,0,0,0)"); sh.addColorStop(1, "rgba(0,0,0,.55)");
        c.fillStyle = sh; c.fillRect(mx - tw, pts[13][1] - open, tw * 2, open * 3);
        c.restore();
      }
      for (const tr of this.mesh) warp(tr);
    }
    dispose() { this.el.innerHTML = ""; this.ctx = null; }
  }
  window.DepthFace = DepthFace;
  window.ARKIT52 = BS;
})();
