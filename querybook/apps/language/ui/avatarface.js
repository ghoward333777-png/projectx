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
  // every landmark row of each lip (inner line → outer line), so a curved mouth is split by the lip, not by a straight line
  const LIP_LO = [14, 87, 178, 88, 95, 317, 402, 318, 324, 15, 86, 179, 89, 96, 316, 403, 319, 325, 16, 85, 180, 90, 77, 315, 404, 320, 307, 17, 84, 181, 91, 146, 314, 405, 321, 375];
  const LIP_UP = [13, 82, 81, 80, 191, 312, 311, 310, 415, 12, 38, 41, 42, 183, 268, 271, 272, 407, 11, 72, 73, 74, 184, 302, 303, 304, 408, 0, 37, 39, 40, 185, 267, 269, 270, 409];
  // y of the upper inner lip line at x (straight on beyond the corners)
  const lipLine = (P, ids) => { const q = (ids || IN_UP).map(i => P[i]).sort((a, b) => a[0] - b[0]);
    return x => { if (x <= q[0][0]) return q[0][1]; if (x >= q[q.length - 1][0]) return q[q.length - 1][1];
      for (let j = 1; j < q.length; j++) if (x <= q[j][0]) { const t = (x - q[j - 1][0]) / ((q[j][0] - q[j - 1][0]) || 1); return q[j - 1][1] + (q[j][1] - q[j - 1][1]) * t; } return q[q.length - 1][1]; }; };
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
  // edge flipping until every constraint edge is in the triangulation (Sloan's method, brute force: the mesh is small)
  function constrain(tris, P, cons) {
    const ori = (a, b, c) => (P[b][0] - P[a][0]) * (P[c][1] - P[a][1]) - (P[b][1] - P[a][1]) * (P[c][0] - P[a][0]);
    const cross = (a, b, c, d) => a !== c && a !== d && b !== c && b !== d && ori(a, b, c) * ori(a, b, d) < 0 && ori(c, d, a) * ori(c, d, b) < 0;
    const key = (a, b) => a < b ? a + "," + b : b + "," + a;
    for (const [a, b] of cons) {
      for (let guard = 0; guard < 400; guard++) {
        const owners = new Map();
        tris.forEach((t, k) => [[t[0], t[1], t[2]], [t[1], t[2], t[0]], [t[2], t[0], t[1]]].forEach(([u, v, w]) => {
          const q = key(u, v); if (!owners.has(q)) owners.set(q, []); owners.get(q).push([k, w]); }));
        if (owners.has(key(a, b))) break;
        let flipped = false;
        for (const [q, own] of owners) {
          if (own.length !== 2) continue;
          const [u, v] = q.split(",").map(Number);
          if (!cross(a, b, u, v)) continue;
          const p1 = own[0][1], p2 = own[1][1];
          if (!cross(p1, p2, u, v)) continue;                  // the quad is not convex: flip another crossing edge first
          tris[own[0][0]] = [p1, p2, u]; tris[own[1][0]] = [p2, p1, v]; flipped = true; break;
        }
        if (!flipped) break;
      }
    }
    return tris;
  }
  const smooth = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

  class DepthFace {
    constructor(el, avatar, params) {
      this.el = el; this.avatar = avatar;
      // calibration (Quality Lab): the admin-approved one everywhere; the lab passes its candidate in params.cal
      const cal = Object.assign({ jaw: 1, spread: 1, round: 1, close: 1, arch: 1, teeth: 1, smooth_ms: 35, lead_ms: 40 },
        (window.QB_CAL && window.QB_CAL.params) || {}, (params && params.cal) || {});
      this.cal = cal;
      cal.head = cal.head || 1; cal.brow = cal.brow || 1;
      this.params = Object.assign({ lead_ms: cal.lead_ms, smooth_ms: cal.smooth_ms, head_gain: cal.head, label: avatar.label || "Synthetic avatar — AI-generated" }, params || {});
      const cg = { jawOpen: cal.jaw, mouthLowerDownLeft: cal.jaw, mouthLowerDownRight: cal.jaw, mouthStretchLeft: cal.spread, mouthStretchRight: cal.spread,
        mouthSmileLeft: cal.spread, mouthSmileRight: cal.spread, mouthDimpleLeft: cal.spread, mouthDimpleRight: cal.spread, mouthPucker: cal.round,
        mouthFunnel: cal.round, mouthClose: cal.close, mouthPressLeft: cal.close, mouthPressRight: cal.close,
        browDownLeft: cal.brow, browDownRight: cal.brow, browInnerUp: cal.brow, browOuterUpLeft: cal.brow, browOuterUpRight: cal.brow };
      this.calGain = Float32Array.from(BS.map(k => cg[k] || 1));
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
      this.lipFix = this._refineLipLine(src, pts3);      // where the lips really meet, from the photo itself
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
      this.nFace = pts3.length;
      this.nX0 = this.base3.length; this.extra = []; this.ring = new Set(RING);
      this.base = this.base3.map(([x, y]) => [x, y]);
      // triangulate a copy with the mouth slightly open, so no triangle bridges the lips (they part cleanly when the jaw drops)
      const Pb = i => this.base[i], Fh = Math.hypot(Pb(10)[0] - Pb(152)[0], Pb(10)[1] - Pb(152)[1]);
      const cRb = Pb(61), cLb = Pb(291), Wmb = Math.hypot(cRb[0] - cLb[0], cRb[1] - cLb[1]), Mb = [(Pb(13)[0] + Pb(14)[0]) / 2, (Pb(13)[1] + Pb(14)[1]) / 2];
      const lowSet = new Set(IN_LO.concat(OUT_LO, LIP_LO).filter(i => ![61, 291, 78, 308].includes(i)));
      const upSet = new Set(IN_UP.concat(OUT_UP, LIP_UP).filter(i => ![61, 291, 78, 308].includes(i)));
      const midY = lipLine(this.base);
      const triPts = this.base.map(([x, y], i) => {
        if (i >= this.nX0) return null;
        if (i >= this.nFace || upSet.has(i)) return [x, y];
        const near = Math.abs(x - Mb[0]) < 0.75 * Wmb && y < Mb[1] + 0.45 * Fh;
        const tq = Math.min(1, Math.abs(x - Mb[0]) / (0.5 * Wmb)), dy = 0.04 * Fh * Math.max(0.25, 1 - tq * tq);   // a lens, like the real opening
        return lowSet.has(i) || (near && y > midY(x) + 0.002 * Fh) ? [x, y + dy] : [x, y];
      });
      // the lip lines are constraints: no triangle may cross them (edges that do are flipped until they don't)
      const lines = [IN_UP, IN_LO, OUT_UP, OUT_LO], cons = [];
      lines.forEach(l => { for (let j = 0; j + 1 < l.length; j++) cons.push([l[j], l[j + 1]]); });
      // the iris outline runs under the lids (the iris is a circle partly hidden by them): those points stay out of the
      // mesh, and the eye moves by the iris centre, so the lids never fold over the iris
      const IRIS_RING = new Set([469, 470, 471, 472, 474, 475, 476, 477]);
      const use = triPts.map((q, i) => i).filter(i => triPts[i] && !IRIS_RING.has(i)), sub = use.map(i => triPts[i]);
      const at = new Map(use.map((i, j) => [j, i])), Psub = triPts;
      this.tris = constrain(delaunay(sub).map(t => t.map(j => at.get(j))), Psub, cons); this.triPts = triPts; this.cons = cons;
      // the opening: triangles whose centre lies between the inner lip lines (in the parted copy)
      const poly = IN_UP.concat(IN_LO.slice(1, -1)).map(i => triPts[i]);
      const inside = (x, y) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c; } return c; };
      const isIn = t => { const R = this.ring; if (!(R.has(t[0]) && R.has(t[1]) && R.has(t[2]))) return false;
        return inside((triPts[t[0]][0] + triPts[t[1]][0] + triPts[t[2]][0]) / 3, (triPts[t[0]][1] + triPts[t[1]][1] + triPts[t[2]][1]) / 3); };
      this.inner = this.tris.filter(isIn);
      this.mesh = this.tris.filter(t => !isIn(t));
      const P = i => this.base3[i];
      this.F = Math.hypot(P(10)[0] - P(152)[0], P(10)[1] - P(152)[1]);
      this.Wm = Math.hypot(P(61)[0] - P(291)[0], P(61)[1] - P(291)[1]);
      this.M = [(P(13)[0] + P(14)[0]) / 2, (P(13)[1] + P(14)[1]) / 2];
      this.fc = [fcx, fcy]; this.crop = crop;
      this.zMean = pts3.reduce((s, p) => s + p[2], 0) / pts3.length;
      this.pivot = [fcx, P(152)[1] + this.F * 0.35, this.zMean + this.F * 0.5];      // the neck
      this.palette = this._palette(src, pts3);
      this.fit = this._fit(); this.gain = new Float32Array(BS.length).fill(1);
      this._fields();
      const cv = document.createElement("canvas"), outW = Math.min(this.el.clientWidth || 380, 480);
      cv.width = Math.round(outW); cv.height = Math.round(outW * crop.h / crop.w);
      cv.style.width = "100%"; cv.style.maxWidth = outW + "px"; cv.style.borderRadius = "10px";
      this.el.innerHTML = ""; this.el.appendChild(cv);
      const lab = document.createElement("div"); lab.className = "small muted"; lab.textContent = this.params.label; this.el.appendChild(lab);
      this.cv = cv; this.ctx = cv.getContext("2d");
      this.autotune();                                    // quality control before the face ever speaks (draws when done)
    }
    // The face tracker sometimes puts the line where the lips meet too low or too high (glossy or stylised lips): then
    // part of one lip is moved with the other and shows as a flap of "gum" when the mouth opens. With the mouth closed in
    // the portrait, the true line is the dark crease between the outer lip edges: it is found column by column, fitted
    // with a smooth curve through the corners, and the lip landmarks are moved onto it (the rows inside each lip are
    // re-spaced so they keep their order). Nothing changes when the tracker already agrees with the photo.
    _refineLipLine(src, P) {
      const g = src.getContext("2d"), F = Math.hypot(P[10][0] - P[152][0], P[10][1] - P[152][1]);
      if (Math.hypot(P[13][0] - P[14][0], P[13][1] - P[14][1]) > 0.012 * F) return { moved_px: 0, reason: "mouth open in the portrait" };
      const line = ids => lipLine(P, ids), oUp = line(OUT_UP), oLo = line(OUT_LO), inn = line(IN_UP);
      const cR = P[61], cL = P[291], x0 = Math.min(cR[0], cL[0]), x1 = Math.max(cR[0], cL[0]), hw = (x1 - x0) / 2, xm = (x0 + x1) / 2;
      const yTop = Math.floor(Math.min(...OUT_UP.map(i => P[i][1]))), yBot = Math.ceil(Math.max(...OUT_LO.map(i => P[i][1])));
      const img = g.getImageData(Math.floor(x0), yTop, Math.max(1, Math.ceil(x1 - x0)), Math.max(1, yBot - yTop)).data, iw = Math.max(1, Math.ceil(x1 - x0));
      const L = (x, y) => { const xi = Math.max(0, Math.min(iw - 1, Math.round(x - Math.floor(x0)))), yi = Math.round(y - yTop), i = 4 * (yi * iw + xi);
        return 0.2126 * img[i] + 0.7152 * img[i + 1] + 0.0722 * img[i + 2]; };
      const samples = [];
      for (let t = -0.75; t <= 0.751; t += 0.1) {
        const x = xm + t * hw, a = oUp(x), b = oLo(x), h = b - a;
        if (h < 4) continue;
        // a crease is a valley — darker than the lip just above it AND just below it — not merely the darkest row
        // (with one dark and one pale lip, the darkest row lies inside the dark lip)
        const prof = [], y0r = Math.ceil(a + 0.12 * h), y1r = Math.floor(b - 0.15 * h);
        for (let y = y0r - 8; y <= y1r + 8; y++) { let v = 0; for (let dx = -2; dx <= 2; dx++) for (let dy = -1; dy <= 1; dy++) v += L(x + dx, y + dy); prof.push([y, v / 15]); }
        const at = y => { const j = y - (y0r - 8); return prof[Math.max(0, Math.min(prof.length - 1, j))][1]; };
        const k = Math.max(3, Math.round(0.06 * h));
        let best = null;
        for (let y = y0r; y <= y1r; y++) {
          let up = 0, dn = 0; for (let d = 2; d <= k + 1; d++) { up += at(y - d); dn += at(y + d); } up /= k; dn /= k;
          const score = Math.min(up, dn) - at(y);
          if (!best || score > best[1]) best = [y, score];
        }
        if (best && best[1] > 6) samples.push([x, best[0]]);   // a clear crease
      }
      if (samples.length < 6) return { moved_px: 0, reason: "no clear crease" };
      // smooth curve through the corners: y = c0 + c1·u + c2·u² (u = position across the mouth), least squares with the corners weighted
      const pts = samples.map(([x, y]) => [(x - xm) / hw, y, 1]).concat([[(cR[0] - xm) / hw, cR[1], 4], [(cL[0] - xm) / hw, cL[1], 4]]);
      const S = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], r = [0, 0, 0];
      pts.forEach(([u, y, w]) => { const v = [1, u, u * u]; for (let i = 0; i < 3; i++) { r[i] += w * v[i] * y; for (let j = 0; j < 3; j++) S[i][j] += w * v[i] * v[j]; } });
      const det = m => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
      const D = det(S); if (Math.abs(D) < 1e-9) return { moved_px: 0, reason: "fit failed" };
      const cf = [0, 1, 2].map(k => det(S.map((row, i) => row.map((v, j) => j === k ? r[i] : v))) / D);
      const crease = x => { const u = (x - xm) / hw; return cf[0] + cf[1] * u + cf[2] * u * u; };
      const mid = IN_UP.filter(i => ![78, 308].includes(i)), shift = mid.reduce((s, i) => s + (crease(P[i][0]) - inn(P[i][0])), 0) / mid.length;
      if (Math.abs(shift) < 0.006 * F) return { moved_px: +shift.toFixed(1), reason: "the tracker agrees with the photo" };
      // move the lip line onto the crease, re-space the rows inside each lip by their fraction of the lip
      const old = P.map(q => q.slice());
      const newIn = x => Math.max(oUp(x) + 1, Math.min(oLo(x) - 1, crease(x)));
      IN_UP.concat(IN_LO).forEach(i => { if (![78, 308].includes(i)) P[i][1] = newIn(old[i][0]); });
      LIP_UP.forEach(i => { if (IN_UP.includes(i) || OUT_UP.includes(i)) return; const x = old[i][0], a = oUp(x), b = inn(x);
        const f = Math.max(0, Math.min(1, (old[i][1] - a) / ((b - a) || 1))); P[i][1] = a + f * (newIn(x) - a); });
      LIP_LO.forEach(i => { if (IN_LO.includes(i) || OUT_LO.includes(i)) return; const x = old[i][0], a = inn(x), b = oLo(x);
        const f = Math.max(0, Math.min(1, (old[i][1] - a) / ((b - a) || 1))); P[i][1] = newIn(x) + f * (b - newIn(x)); });
      return { moved_px: +shift.toFixed(1), moved_mm: null, reason: "lip line moved onto the crease in the photo" };
    }
    // Colours for the inside of the mouth, taken from this portrait so they match its light and white balance:
    // the lips (the cavity is a deep, warm shade of them), and the whites of the eyes (teeth are never brighter or
    // bluer than the sclera of the same face — the commonest tell of a fake mouth).
    _palette(src, P) {
      const g = src.getContext("2d"), W = src.width, H = src.height;
      const avg = (x, y, r) => { x = Math.round(x); y = Math.round(y); r = Math.max(1, Math.round(r));
        const x0 = Math.max(0, x - r), y0 = Math.max(0, y - r), w = Math.min(W, x + r + 1) - x0, h = Math.min(H, y + r + 1) - y0;
        if (w <= 0 || h <= 0) return [128, 128, 128];
        const d = g.getImageData(x0, y0, w, h).data; let R = 0, G = 0, B = 0, n = 0;
        for (let i = 0; i < d.length; i += 4) { R += d[i]; G += d[i + 1]; B += d[i + 2]; n++; } return [R / n, G / n, B / n]; };
      const mid = (a, b, t) => [P[a][0] + (P[b][0] - P[a][0]) * t, P[a][1] + (P[b][1] - P[a][1]) * t];
      const lipR = Math.max(1, Math.hypot(P[0][0] - P[13][0], P[0][1] - P[13][1]) * 0.2);
      const lips = [mid(0, 13, 0.5), mid(14, 17, 0.5), mid(37, 82, 0.5), mid(267, 312, 0.5)].map(q => avg(q[0], q[1], lipR));
      const lip = [0, 1, 2].map(c => lips.reduce((s, v) => s + v[c], 0) / lips.length);
      const lum = v => 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
      // sclera: between the iris and each eye corner; the brightest honest sample
      const ew = Math.hypot(P[33][0] - P[133][0], P[33][1] - P[133][1]), sc = [];
      if (P.length >= 478) for (const [c, a, b] of [[468, 33, 133], [473, 263, 362]]) for (const corner of [a, b]) { const q = mid(c, corner, 0.55); sc.push(avg(q[0], q[1], ew * 0.04)); }
      sc.sort((a, b) => lum(b) - lum(a));
      let sclera = sc.length ? sc[0] : [225, 220, 210];
      if (lum(sclera) < 120) sclera = [Math.max(sclera[0], 170), Math.max(sclera[1], 162), Math.max(sclera[2], 150)];
      // teeth: a little darker and warmer than the sclera, never brighter, never blue
      const L = Math.min(lum(sclera) * 0.9, 222), base = [1.0, 0.975, 0.92], k = L / lum(base.map(x => x * 255));
      const teeth = base.map(x => Math.round(x * 255 * k));
      const tone = (v, f, add) => v.map((x, i) => Math.round(Math.max(0, Math.min(255, x * f + (add ? add[i] : 0)))));
      const skinS = [avg(P[205][0], P[205][1], ew * 0.12), avg(P[425][0], P[425][1], ew * 0.12)];
      const skin = [0, 1, 2].map(c => (skinS[0][c] + skinS[1][c]) / 2);
      return { lip: lip.map(Math.round), sclera: sclera.map(Math.round), teeth, skin: skin.map(Math.round),
        crease: tone(skin, 0.55), sheen: tone(skin, 1.12),
        cavDeep: tone(lip, 0.22, [8, 1, 1]), cavEdge: tone(lip, 0.45, [8, 0, 0]), tongue: tone(lip, 0.62, [10, -4, -2]), gum: tone(lip, 0.75) };
    }
    // Mouth fit: the speaking mouth sized and shaped from this face's own anatomy, measured once per portrait.
    //  * scale: millimetres per pixel from the iris (≈11.7 mm across in adults, the steadiest size in a face),
    //    cross-checked against face height (forehead to chin ≈ 150–230 mm);
    //  * size: conversational speech opens the lips about 0.28 × mouth width on an open vowel ("aa"), 9–16 mm,
    //    so a small mouth opens less than a large one;
    //  * shape: the opening follows this person's own lower-lip outline, blended with an anatomical lens;
    //  * teeth: upper incisors show at most ~3 mm, never more than a third of the opening.
    _fit() {
      const B = this.base3, d = (a, b) => Math.hypot(B[a][0] - B[b][0], B[a][1] - B[b][1]);
      let pxmm = null, how = "iris";
      if (this.hasIris) { const iris = (d(469, 471) + d(470, 472) + d(474, 476) + d(475, 477)) / 4; if (iris > 2) pxmm = iris / 11.7; }
      const Fmm = pxmm ? this.F / pxmm : 0;
      if (!pxmm || Fmm < 150 || Fmm > 230) { pxmm = this.F / 185; how = "face height"; }
      const Wmm = this.Wm / pxmm, upLip = d(0, 13) / pxmm, loLip = d(14, 17) / pxmm, chin = d(17, 152) / pxmm;
      const aa = Math.max(8, Math.min(13, 0.24 * Wmm));                       // lip opening on "aa", mm (conversational, not a shout)
      const jaw1 = aa / 0.45 * pxmm;                                            // the speech engine's "aa" is jawOpen ≈ 0.45
      const gain = jaw1 / (0.184 * this.F);                                     // the jaw field gives 0.184·F of opening at 1
      // the person's lower-lip outline under the lip line, normalised: the opening takes the same curve
      const line = lipLine(B), outl = OUT_LO.map(i => [B[i][0], B[i][1] - line(B[i][0])]).sort((a, b) => a[0] - b[0]);
      const depth = Math.max(1e-6, ...outl.map(q => q[1]));
      const own = x => { if (x <= outl[0][0] || x >= outl[outl.length - 1][0]) return 0;
        for (let j = 1; j < outl.length; j++) if (x <= outl[j][0]) { const t = (x - outl[j - 1][0]) / ((outl[j][0] - outl[j - 1][0]) || 1);
          return Math.max(0, (outl[j - 1][1] + (outl[j][1] - outl[j - 1][1]) * t) / depth); } return 0; };
      return { pxmm, scale_from: how, mouth_mm: +Wmm.toFixed(1), upper_lip_mm: +upLip.toFixed(1), lower_lip_mm: +loLip.toFixed(1), chin_mm: +chin.toFixed(1),
        aa_open_mm: +aa.toFixed(1), jaw_gain: gain, teeth_mm: Math.min(3, 0.3 * aa) * this.cal.teeth, own };
    }
    // per-channel displacement fields over the mesh (pixels at channel value 1), built once per portrait
    _fields() {
      const n = this.base3.length, B = this.base3, F = this.F, Wm = this.Wm, M = this.M, nF = this.nFace;
      const D = BS.map(() => new Float32Array(n * 3));
      const add = (k, i, dx, dy, dz) => { if (i >= nF) return; const a = D[IDX[k]]; a[3 * i] += dx; a[3 * i + 1] += dy; a[3 * i + 2] += dz || 0; };
      const g = (i, c, s) => Math.exp(-(((B[i][0] - c[0]) ** 2 + (B[i][1] - c[1]) ** 2) / (s * s)));
      // mouth geometry: midline between the lips, corners, which side of the midline each point is
      const cL = B[291], cR = B[61], mid = lipLine(B);
      const LOWER = new Set(IN_LO.concat(OUT_LO, LIP_LO).filter(i => ![61, 291, 78, 308].includes(i)));
      const UPPER = new Set(IN_UP.concat(OUT_UP, LIP_UP).filter(i => ![61, 291, 78, 308].includes(i)));
      const below = i => LOWER.has(i) ? 1 : UPPER.has(i) ? 0 : smooth(-0.004 * F, 0.006 * F, B[i][1] - mid(B[i][0]));   // lower lip and chin side
      const above = i => 1 - below(i);
      const lipZ = i => Math.exp(-((Math.hypot(B[i][0] - M[0], (B[i][1] - M[1]) * 1.5) / (0.75 * Wm)) ** 2));
      const side = (i, s) => smooth(-0.15 * Wm, 0.25 * Wm, s * (B[i][0] - M[0]));                // 1 on that side (s=+1: picture right = subject left)
      // lips part as a lens, not a slot: the opening tapers to nothing at the corners (prof = 1 at the centre, 0 at a corner),
      // and only the lip band follows that taper — the chin below drops with the whole jaw
      const fit = this.fit;
      const prof = i => { const t = Math.min(1, Math.abs(B[i][0] - M[0]) / (0.5 * Wm)), lens = Math.pow(1 - t * t, 0.8);
        return 0.5 * lens + 0.5 * Math.min(1, fit.own(B[i][0]) * 1.15); };
      const lipBand = i => { const ax = Math.abs(B[i][0] - M[0]);
        return Math.exp(-(((B[i][1] - M[1]) / (0.09 * F)) ** 2)) * (ax < 0.6 * Wm ? 1 : Math.exp(-(((ax - 0.6 * Wm) / (0.15 * Wm)) ** 2))); };
      const wOpen = i => 1 - lipBand(i) * (1 - prof(i));
      const jawW = i => Math.exp(-(((B[i][0] - M[0]) / (0.42 * F)) ** 2)) * below(i) * (1 - 0.25 * smooth(0, 0.3 * F, B[i][1] - M[1]));
      // Each lip moves as a solid band: every row of a lip moves together, so its thickness and its width stay what they
      // are in the portrait (lips do not stretch or shrink while we talk). Only the skin around them takes up the motion:
      // above the upper lip it fades out within ~6% of the face, below the lower lip it blends into the chin.
      const outUp = lipLine(B, OUT_UP), outLo = lipLine(B, OUT_LO);
      const lat = i => { const ax = Math.abs(B[i][0] - M[0]); return ax < 0.5 * Wm ? 1 : Math.exp(-(((ax - 0.5 * Wm) / (0.12 * Wm)) ** 2)); };
      const upBand = i => UPPER.has(i) ? 1 : (B[i][1] < outUp(B[i][0]) ? (1 - smooth(0, 0.06 * F, outUp(B[i][0]) - B[i][1])) * lat(i) : 0);
      const loBand = i => LOWER.has(i) ? 1 : (B[i][1] > outLo(B[i][0]) ? (1 - smooth(0, 0.1 * F, B[i][1] - outLo(B[i][0]))) * lat(i) : 0);
      const chinMix = i => smooth(0, 0.1 * F, B[i][1] - outLo(B[i][0]));    // 0 at the lower lip, 1 well down the chin
      // corners: rounding and spreading move the corners, not the middle of the lips
      const corner = i => smooth(0.32 * Wm, 0.52 * Wm, Math.abs(B[i][0] - M[0])) * Math.exp(-(((B[i][1] - M[1]) / (0.08 * F)) ** 2));
      for (let i = 0; i < nF; i++) {
        const [x, y] = B[i], lz = lipZ(i), up = above(i), lo = below(i), sL = side(i, 1), sR = side(i, -1), dxm = x - M[0];
        const pf = prof(i), ub = upBand(i), lb = loBand(i), jg = fit.jaw_gain, sg = Math.sign(dxm);
        // jaw: the chin swings down; the lower lip rides on it as a band, opening as a lens (most at the centre)
        const jawMove = LOWER.has(i) ? pf : lo > 0.5 ? pf + (1 - pf) * chinMix(i) : 0;
        // a real mouth opens as a curve on both lips: the lower lip drops (about 70% of the opening) and the upper lip
        // arches up toward its middle (about 30%), both tapering to the corners — never a flat upper edge
        add("jawOpen", i, -dxm * 0.03 * jawW(i) * chinMix(i), 0.122 * F * jawW(i) * jawMove * jg, 0.03 * F * jawW(i) * jg);
        const arch = Math.pow(Math.max(0, 1 - (Math.min(1, Math.abs(dxm) / (0.5 * Wm))) ** 2), 1.5);
        add("jawOpen", i, 0, -0.062 * F * arch * ub * jg * this.cal.arch, 0);
        add("jawForward", i, 0, 0.006 * F * jawW(i), -0.05 * F * jawW(i));
        add("jawLeft", i, 0.045 * F * jawW(i), 0, 0); add("jawRight", i, -0.045 * F * jawW(i), 0, 0);
        // closing the lips against an open jaw: the lower lip band rises back to the upper lip
        add("mouthClose", i, 0, -0.17 * F * jawW(i) * 1.1 * jg * (LOWER.has(i) ? pf : lo > 0.5 ? pf * (1 - chinMix(i)) : 0), 0);
        // rounding (o, u, w, ch): the corners come in and the lips push forward; the lips keep their own width
        add("mouthFunnel", i, -sg * 0.05 * Wm * corner(i), (lb - ub) * 0.012 * F * pf, -0.03 * F * lz);
        add("mouthPucker", i, -sg * 0.075 * Wm * corner(i), 0, -0.045 * F * lz);
        add("mouthLeft", i, 0.13 * Wm * lz, 0, 0); add("mouthRight", i, -0.13 * Wm * lz, 0, 0);
        for (const [k, s, c] of [["Left", 1, cL], ["Right", -1, cR]]) {
          const cw = g(i, c, 0.24 * Wm), sd = s > 0 ? sL : sR;
          add("mouthSmile" + k, i, s * 0.07 * Wm * cw, -0.045 * F * cw, 0);
          add("mouthFrown" + k, i, s * 0.03 * Wm * cw, 0.045 * F * cw, 0);
          add("mouthDimple" + k, i, s * 0.03 * Wm * cw, -0.008 * F * cw, 0.02 * F * cw);
          add("mouthStretch" + k, i, s * 0.06 * Wm * cw, 0.01 * F * cw, 0);
          // pressing: the outer edges of the lips draw in toward the closed line; the line itself stays put (never crosses)
          const outer = UPPER.has(i) || LOWER.has(i) ? Math.min(1, Math.abs(y - mid(x)) / (0.05 * F)) : 0;
          add("mouthPress" + k, i, 0, (ub - lb) * 0.006 * F * outer * sd, 0);
          add("mouthLowerDown" + k, i, 0, 0.04 * F * lb * sd * Math.sqrt(pf), 0);
          add("mouthUpperUp" + k, i, 0, -0.03 * F * ub * sd * Math.sqrt(pf), 0);
        }
        add("mouthRollLower", i, 0, -0.008 * F * lb * pf, 0.006 * F * lb);
        add("mouthRollUpper", i, 0, 0.006 * F * ub * pf, 0.006 * F * ub);
        add("mouthShrugLower", i, 0, -0.015 * F * lb, -0.008 * F * lb);
        add("mouthShrugUpper", i, 0, -0.01 * F * ub, 0);
        // cheeks and nose
        for (const [k, s, e] of [["Left", 1, EYE.L], ["Right", -1, EYE.R]]) {
          const ck = g(i, B[e.cheek], 0.16 * F);
          add("cheekSquint" + k, i, 0, -0.032 * F * ck, 0);
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
        // a blink closes along a curve from corner to corner, a third of the way down to the lower lid: the upper lid comes
        // down to it, the lower lid rises a little to meet it (no lid point can pass a corner, so nothing folds)
        const cA = B[e.outer], cB = B[e.inner], cline = x => cA[1] + (cB[1] - cA[1]) * (x - cA[0]) / ((cB[0] - cA[0]) || 1);
        const lidAt = (ids, x) => { const q = ids.map(i => B[i]).sort((a, b) => a[0] - b[0]);
          if (x <= q[0][0]) return q[0][1]; if (x >= q[q.length - 1][0]) return q[q.length - 1][1];
          for (let n = 1; n < q.length; n++) if (x <= q[n][0]) return q[n - 1][1] + (q[n][1] - q[n - 1][1]) * (x - q[n - 1][0]) / ((q[n][0] - q[n - 1][0]) || 1); };
        const shut = x => cline(x) + 0.35 * (lidAt(e.lo, x) - cline(x));
        e.lo.forEach(l => add("eyeBlink" + k, l, 0, Math.min(0, shut(B[l][0]) - B[l][1]), 0));
        this.shut = this.shut || {}; this.shut[k] = shut;
        e.up.forEach((u, j) => {
          const l = e.lo[j], dy = B[l][1] - B[u][1];
          add("eyeBlink" + k, u, 0, Math.max(0, shut(B[u][0]) - B[u][1]), 0);
          add("eyeWide" + k, u, 0, -dy * 0.3, 0);
          add("eyeSquint" + k, l, 0, -dy * 0.3, 0);
          add("eyeLookUp" + k, u, 0, -dy * 0.12, 0); add("eyeLookDown" + k, u, 0, dy * 0.25, 0);
        });
        if (this.hasIris) e.iris.forEach(j => {
          const s = k === "Left" ? 1 : -1;                                   // "out" is toward the ear
          // the iris stays inside the lids: modest travel, and it does not dive under the lower lid on a blink
          add("eyeLookOut" + k, j, s * 0.06 * ew, 0, 0); add("eyeLookIn" + k, j, -s * 0.06 * ew, 0, 0);
          add("eyeLookUp" + k, j, 0, -0.02 * ew, 0); add("eyeLookDown" + k, j, 0, 0.02 * ew, 0);
          // as the lid closes the eye's contents are squeezed under it toward the lower lid (never overlapped by it)
          const at = (ids, x) => { const q = ids.map(i => B[i]).sort((a, b) => a[0] - b[0]);
            if (x <= q[0][0]) return q[0][1]; if (x >= q[q.length - 1][0]) return q[q.length - 1][1];
            for (let n = 1; n < q.length; n++) if (x <= q[n][0]) return q[n - 1][1] + (q[n][1] - q[n - 1][1]) * (x - q[n - 1][0]) / ((q[n][0] - q[n - 1][0]) || 1); };
          add("eyeBlink" + k, j, 0, this.shut[k](B[j][0]) - B[j][1], 0);
        });
      }
      // relax the mouth and jaw fields over the mesh (lips pinned): the skin takes up the lips' motion smoothly, so no
      // triangle beside a lip or corner can fold over
      const nb = Array.from({ length: nF }, () => new Set());
      this.tris.forEach(t => t.forEach(a => t.forEach(b2 => { if (a !== b2 && a < nF && b2 < nF) nb[a].add(b2); })));
      // the corners: a small patch around each corner moves with it rigidly (the corner skin is not squeezed past it)
      const patch = [];
      for (const cnr of [61, 291]) for (let i = 0; i < nF; i++)
        if (i !== cnr && !UPPER.has(i) && !LOWER.has(i) && Math.hypot(B[i][0] - B[cnr][0], B[i][1] - B[cnr][1]) < 0.1 * Wm) patch.push([i, cnr]);
      BS.forEach((k, ki) => { if (!/^(jaw|mouth)/.test(k)) return; const d = D[ki];
        patch.forEach(([i, cnr]) => { for (let q = 0; q < 3; q++) d[3 * i + q] = d[3 * cnr + q]; }); });
      const pinned = new Set([...UPPER, ...LOWER, ...RING, 61, 291, 78, 308, ...patch.map(p => p[0])]);
      const free = [...Array(nF).keys()].filter(i => !pinned.has(i) && nb[i].size && Math.hypot(B[i][0] - M[0], B[i][1] - M[1]) < 0.45 * F);
      BS.forEach((k, ki) => {
        if (!/^(jaw|mouth)/.test(k)) return;
        const d = D[ki];
        for (let it = 0; it < 8; it++) {
          const nd = d.slice();
          for (const i of free) { let sx = 0, sy = 0, sz = 0; nb[i].forEach(j => { sx += d[3 * j]; sy += d[3 * j + 1]; sz += d[3 * j + 2]; });
            const n = nb[i].size; nd[3 * i] = 0.5 * d[3 * i] + 0.5 * sx / n; nd[3 * i + 1] = 0.5 * d[3 * i + 1] + 0.5 * sy / n; nd[3 * i + 2] = 0.5 * d[3 * i + 2] + 0.5 * sz / n; }
          d.set(nd);
        }
      });
      this.extra.forEach(([a, b, t], j) => { const i = this.nX0 + j;
        D.forEach(d => { for (let q = 0; q < 3; q++) d[3 * i + q] = d[3 * a + q] * (1 - t) + d[3 * b + q] * t; }); });
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
    _points(chan, head) {
      const n = this.base3.length, out = new Array(n), c = Float32Array.from(chan || this.cur), D = this.D, nF = this.nFace, g = this.params.head_gain;
      // a mouth widens at most ~10% in speech: stretch, smile and dimple share one soft-limited budget per side
      for (const k of ["Left", "Right"]) {
        const ks = ["mouthStretch" + k, "mouthSmile" + k, "mouthDimple" + k].map(q => IDX[q]);
        const wide = 0.06 * c[ks[0]] + 0.07 * c[ks[1]] + 0.03 * c[ks[2]], cap = 0.035;
        if (wide > 1e-4) { const f = cap * Math.tanh(wide / cap) / wide; ks.forEach(q => { c[q] *= f; }); }
      }
      const [yaw, pitch, roll] = (head || this.head).map(d => d * g * Math.PI / 180), [px, py, pz] = this.pivot;
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
      for (let i = 0; i < n; i++) {
        let [x, y, z] = this.base3[i];
        if (i < nF || i >= this.nX0) {
          for (let k = 0; k < c.length; k++) {
            const w = (k === MC ? Math.min(c[k], c[JAW]) : c[k]) * this.gain[k] * this.calGain[k];   // lips can only close against an open jaw
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
      const warp = (tr, always) => {
        const [a, b, d] = tr, s0 = B[a], s1 = B[b], s2 = B[d], d0 = pts[a], d1 = pts[b], d2 = pts[d];
        if (!always && Math.abs(d0[0] - s0[0]) + Math.abs(d0[1] - s0[1]) + Math.abs(d1[0] - s1[0]) + Math.abs(d1[1] - s1[1]) + Math.abs(d2[0] - s2[0]) + Math.abs(d2[1] - s2[1]) < 0.05) return;
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
      // the inside of the mouth: the portrait's own mouth first (exact at rest), then — only as the lips part beyond
      // where they are in the portrait — a dark cavity with soft teeth that follow the curve of the lips
      for (const tr of this.inner) warp(tr, true);
      const gap = (q, i, j) => Math.hypot(q[i][0] - q[j][0], q[i][1] - q[j][1]);
      const open = gap(pts, 13, 14), extra = open - gap(B, 13, 14), vis = smooth(0.002 * F, 0.01 * F, extra);
      if (vis > 0.01) this._mouthInside(c, pts, open, extra, vis);
      for (const tr of this.mesh) warp(tr);
      if (vis > 0.01) this._mouthInside(c, pts, open, extra, vis, true);     // final pass: a smooth, feathered edge (no facets)
      this._wrinkles(c, pts);
    }
    // Skin creases that deepen and fade with the muscles while talking — drawn along the moving mesh, in a darker shade of
    // this face's own skin with a faint highlight above each one (a fold, not a pen line): forehead lines as the brows rise,
    // frown lines as they lower, crow's feet and under-eye bunching as the cheeks lift and the eyes narrow, and the smile
    // lines from nose to mouth as the lips spread.
    _wrinkles(c, pts) {
      const F = this.F, pal = this.palette, cur = this.cur, G = k => cur[IDX[k]] * this.gain[IDX[k]] * this.calGain[IDX[k]];
      const rgb = (v, a) => "rgba(" + v[0] + "," + v[1] + "," + v[2] + "," + a + ")";
      const fold = (q, a, w) => {
        if (a < 0.015 || q.length < 2) return;
        const path = dy => { c.beginPath(); c.moveTo(q[0][0], q[0][1] + dy);
          for (let i = 1; i < q.length - 1; i++) c.quadraticCurveTo(q[i][0], q[i][1] + dy, (q[i][0] + q[i + 1][0]) / 2, (q[i][1] + q[i + 1][1]) / 2 + dy);
          c.lineTo(q[q.length - 1][0], q[q.length - 1][1] + dy); };
        c.save(); c.lineCap = "round"; c.filter = "blur(" + (w * 0.55).toFixed(2) + "px)";
        c.globalAlpha = Math.min(0.3, a); c.strokeStyle = rgb(pal.crease, 1); c.lineWidth = w; path(0); c.stroke();
        c.globalAlpha = Math.min(0.18, a * 0.6); c.strokeStyle = rgb(pal.sheen, 1); c.lineWidth = w * 0.8; path(-w * 0.9); c.stroke();
        c.restore();
      };
      const P = i => pts[i], lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], w = Math.max(0.8, F * 0.0035);
      // forehead: three arcs across the brows, rising with them
      const up = Math.max(G("browInnerUp"), (G("browOuterUpLeft") + G("browOuterUpRight")) / 2);
      const browArc = [70, 63, 105, 66, 107, 336, 296, 334, 293, 300].map(P);
      [0.05, 0.085, 0.12].forEach((h, k) => fold(browArc.map(q => [q[0], q[1] - h * F]).slice(1 + k % 2, browArc.length - 1 - k % 2), 0.22 * up * (1 - 0.2 * k), w));
      // frown lines between the brows
      const bd = (G("browDownLeft") + G("browDownRight")) / 2, iL = P(336), iR = P(107);
      [0.38, 0.62].forEach(t => { const m = lerp(iR, iL, t); fold([[m[0], m[1] - 0.01 * F], [m[0] + (t - 0.5) * 0.01 * F, m[1] + 0.02 * F], [m[0], m[1] + 0.04 * F]], 0.3 * bd, w * 0.8); });
      for (const [k, corner, lids, s] of [["Left", 263, [249, 390, 373, 374, 380, 381, 382], 1], ["Right", 33, [7, 163, 144, 145, 153, 154, 155], -1]]) {
        // crow's feet and under-eye bunching
        const sq = Math.max(G("eyeSquint" + k), G("cheekSquint" + k)), o = P(corner);
        [-0.45, 0, 0.45].forEach(ang => { const a0 = [o[0] + s * 0.012 * F, o[1]], dir = [s * Math.cos(ang), Math.sin(ang)];
          fold([a0, [a0[0] + dir[0] * 0.02 * F, a0[1] + dir[1] * 0.02 * F], [a0[0] + dir[0] * 0.035 * F, a0[1] + dir[1] * 0.035 * F]], 0.24 * sq, w * 0.7); });
        fold(lids.map(i => [P(i)[0], P(i)[1] + 0.022 * F]), 0.18 * G("cheekSquint" + k), w * 0.8);
        // smile line: from the side of the nose, curving out and down past the mouth corner
        const nose = P(s > 0 ? 358 : 129), mc = P(s > 0 ? 291 : 61), sp = G("mouthSmile" + k) + 0.5 * G("mouthStretch" + k) + 0.5 * G("mouthUpperUp" + k) + 0.3 * G("cheekSquint" + k);
        fold([[nose[0] + s * 0.01 * F, nose[1]], [mc[0] + s * 0.05 * F, (nose[1] + mc[1]) / 2], [mc[0] + s * 0.03 * F, mc[1] + 0.03 * F]], 0.2 * Math.min(1.2, sp), w);
      }
    }
    // The inside of the mouth, drawn as a real one looks while talking (the aesthetic guardrail):
    //  * the opening is a soft, deep, warm shade of this person's lips — never a flat black slot, never hard-edged;
    //  * upper front teeth: six teeth (canines, laterals, centrals) under the upper lip, rounded, with fine gaps, shaded by
    //    the lip above and darker toward the corners; at most ~3 mm and a third of the opening; coloured from the sclera;
    //  * the tongue rests low and is attached to the floor of the mouth (it rises for th/l, never floats);
    //  * gums are never shown in speech; lower teeth only as a faint edge in a wide opening.
    _mouthInside(c, pts, open, extra, vis, smoothEdge) {
      const F = this.F, pal = this.palette, rgb = (v, a) => "rgba(" + v[0] + "," + v[1] + "," + v[2] + "," + (a === undefined ? 1 : a) + ")";
      const smooth2 = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
      const tw = Math.hypot(pts[78][0] - pts[308][0], pts[78][1] - pts[308][1]), mx = (pts[78][0] + pts[308][0]) / 2;
      const upY = lipLine(pts, IN_UP), loY = lipLine(pts, IN_LO), my = (pts[13][1] + pts[14][1]) / 2;
      // the outline of the opening: the mesh's own lip line, or (final pass) a smooth curve through it
      const outline = () => { c.beginPath(); const ring = IN_UP.concat(IN_LO.slice(1, -1)).map(i => pts[i]), n = ring.length;
        if (!smoothEdge) { ring.forEach((q, j) => j ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1])); c.closePath(); return; }
        const m = j => [(ring[j % n][0] + ring[(j + 1) % n][0]) / 2, (ring[j % n][1] + ring[(j + 1) % n][1]) / 2];
        c.moveTo(...m(0)); for (let j = 1; j <= n; j++) c.quadraticCurveTo(ring[j % n][0], ring[j % n][1], ...m(j)); c.closePath(); };
      c.save(); c.globalAlpha = vis;
      outline(); c.clip();
      const top = pts[13][1] - open - F * 0.02, h = open * 3 + F * 0.04;
      // depth: lighter (lip-coloured) near the lips, deep at the back
      const gr = c.createRadialGradient(mx, my + open * 0.15, 0, mx, my, tw * 0.55);
      gr.addColorStop(0, rgb(pal.cavDeep)); gr.addColorStop(0.7, rgb(pal.cavDeep)); gr.addColorStop(1, rgb(pal.cavEdge));
      c.fillStyle = gr; c.fillRect(mx - tw, top, tw * 2, h);
      // tongue: a soft mound rising from the floor of the mouth; it lifts toward the teeth for th / l
      const tng = this.cur[IDX.tongueOut], lowC = loY(mx);
      if (open > F * 0.012) {
        const ty = lowC + open * (0.32 - 0.55 * tng), ry = open * (0.55 + 0.2 * tng), rx = tw * (0.3 + 0.06 * tng);
        const tg = c.createRadialGradient(mx, ty - ry * 0.6, 0, mx, ty, Math.max(rx, ry));
        tg.addColorStop(0, rgb(pal.tongue)); tg.addColorStop(1, rgb(pal.cavEdge));
        c.fillStyle = tg; c.beginPath(); c.ellipse(mx, ty, rx, ry, 0, 0, 2 * Math.PI); c.fill();
      }
      // upper front teeth, hanging from the upper lip's curve
      const th = Math.min(open * 0.33, this.fit.teeth_mm * this.fit.pxmm) * smooth2(0.01 * F, 0.03 * F, extra);
      if (th > 0.6) {
        // one continuous row (as teeth read at speaking distance), its lower edge gently scalloped tooth by tooth,
        // then barely-there separations; the side teeth sit deeper and darker
        const span = tw * 0.66, widths = [0.78, 0.74, 1, 1, 0.74, 0.78], tot = widths.reduce((a, b) => a + b, 0);
        const teethL = [], x0 = mx - span / 2; let x = x0;
        widths.forEach((wf, n) => { const w = span * wf / tot, cx = x + w / 2, side = Math.abs(cx - mx) / (span / 2);
          teethL.push({ x, w, cx, len: th * (n === 2 || n === 3 ? 1 : n === 1 || n === 4 ? 0.9 : 0.8) * (1 - 0.2 * side) }); x += w; });
        // the row's lower edge is one smooth curve along the lip (no steps), with a faint scallop at each tooth
        const lenAt = xx => { const t = Math.max(0, Math.min(1, Math.abs(xx - mx) / (span / 2))); return th * (1 - 0.32 * t * t); };
        const scal = xx => { for (const t of teethL) if (xx >= t.x && xx <= t.x + t.w) { const u = (xx - t.x) / t.w; return 0.07 * (1 - Math.sin(Math.PI * u)); } return 0; };
        const N = 36;
        c.beginPath(); c.moveTo(x0, upY(x0) - 1);
        for (let q = 0; q <= N; q++) { const xx = x0 + span * q / N; c.lineTo(xx, upY(xx) - 1); }
        for (let q = N; q >= 0; q--) { const xx = x0 + span * q / N, L = lenAt(xx); c.lineTo(xx, upY(xx) - 1 + L * (1 - scal(xx))); }
        c.closePath();
        const y0 = upY(mx) - 1, tc = pal.teeth;
        const lg = c.createLinearGradient(0, y0, 0, y0 + th);
        lg.addColorStop(0, rgb(tc.map(v => Math.round(v * 0.86)))); lg.addColorStop(0.5, rgb(tc)); lg.addColorStop(1, rgb(tc.map(v => Math.round(v * 0.93))));
        c.fillStyle = lg; c.fill();
        const side = c.createLinearGradient(x0, 0, x0 + span, 0);         // deeper toward the corners
        side.addColorStop(0, rgb(pal.cavDeep, 0.55)); side.addColorStop(0.3, rgb(pal.cavDeep, 0)); side.addColorStop(0.7, rgb(pal.cavDeep, 0)); side.addColorStop(1, rgb(pal.cavDeep, 0.55));
        c.fillStyle = side; c.fill();
        c.strokeStyle = rgb(pal.cavDeep, 0.16); c.lineWidth = Math.max(0.4, span * 0.004);
        teethL.slice(1).forEach(t => { const yy = upY(t.x); c.beginPath(); c.moveTo(t.x, yy); c.lineTo(t.x, yy + lenAt(t.x) * 0.75); c.stroke(); });
        // faint lower incisal edge in a wide opening only
        if (open > F * 0.05) {
          c.fillStyle = rgb(pal.teeth.map(v => Math.round(v * 0.7)), 0.5);
          c.beginPath(); c.ellipse(mx, lowC - 0.5, span * 0.3, Math.max(0.8, th * 0.22), 0, Math.PI, 2 * Math.PI); c.fill();
        }
      }
      // shadows: the corners go dark, the upper lip shades what is under it
      const sh = c.createLinearGradient(mx - tw / 2, 0, mx + tw / 2, 0);
      sh.addColorStop(0, rgb(pal.cavDeep, 0.95)); sh.addColorStop(0.2, rgb(pal.cavDeep, 0)); sh.addColorStop(0.8, rgb(pal.cavDeep, 0)); sh.addColorStop(1, rgb(pal.cavDeep, 0.95));
      c.fillStyle = sh; c.fillRect(mx - tw, top, tw * 2, h);
      const us = c.createLinearGradient(0, pts[13][1] - 1, 0, pts[13][1] + Math.max(2, open * 0.22));
      us.addColorStop(0, rgb(pal.cavDeep, 0.3)); us.addColorStop(1, rgb(pal.cavDeep, 0));
      c.fillStyle = us; c.fillRect(mx - tw, pts[13][1] - 2, tw * 2, Math.max(3, open * 0.3));
      c.restore();
      // soft inner lip edge: the lips round into the mouth, there is no cut line
      c.save(); c.globalAlpha = 0.55 * vis; c.filter = "blur(" + Math.max(0.6, F * 0.0016).toFixed(2) + "px)";
      c.strokeStyle = rgb(pal.cavEdge); c.lineWidth = Math.max(1, F * 0.003);
      outline(); c.stroke();
      c.restore();
    }
    // Quality control of the face and its movement: every mouth pose is checked on the mesh against human anatomy —
    // lips keep their thickness and width, the mouth widens/narrows within human limits, the lips never cross, and no
    // triangle of the face folds over (folds are what show up as smeared lips or "gums"). Deterministic, no network.
    qc() {
      const P0 = this._points(new Float32Array(BS.length), [0, 0, 0]), F = this.F, nF = this.nFace;
      const dist = (P, a, b) => Math.hypot(P[a][0] - P[b][0], P[a][1] - P[b][1]);
      const m = P => ({ upT: (dist(P, 0, 13) + dist(P, 37, 82) + dist(P, 267, 312)) / 3, loT: (dist(P, 14, 17) + dist(P, 87, 84) + dist(P, 317, 314)) / 3,
        upW: Math.abs(P[40][0] - P[270][0]), mW: dist(P, 61, 291) });
      const r0 = m(P0), area = (P, t) => (P[t[1]][0] - P[t[0]][0]) * (P[t[2]][1] - P[t[0]][1]) - (P[t[2]][0] - P[t[0]][0]) * (P[t[1]][1] - P[t[0]][1]);
      const faceTris = this.mesh.filter(t => t[0] < nF && t[1] < nF && t[2] < nF), a0 = faceTris.map(t => area(P0, t));
      const lim = { upT: [0.88, 1.15], loT: [0.85, 1.2], upW: [0.9, 1.07], mW: [0.8, 1.1] };
      const label = { upT: "upper-lip thickness", loT: "lower-lip thickness", upW: "upper-lip width", mW: "mouth width" };
      // one pose: its measurements and what is wrong with it
      const evalPose = v => {
        const P = this._points(v, [0, 0, 0]), q = m(P), out = [], ratio = {};
        for (const k of Object.keys(lim)) { const r = q[k] / r0[k]; ratio[k] = r; if (r < lim[k][0] || r > lim[k][1]) out.push(label[k] + " ×" + r.toFixed(2)); }
        // a fold is a triangle turned over with visible area (one that only flattens shut, like a closing lid, is not)
        const f = faceTris.reduce((s, t, j) => { const n = area(P, t); return s + (Math.sign(n) !== Math.sign(a0[j]) && Math.abs(a0[j]) > 0.5 && Math.abs(n) > 0.1 * Math.abs(a0[j]) ? 1 : 0); }, 0);
        if (f) out.push(f + " folded triangle(s)");
        const line = lipLine(P), c = IN_LO.filter(i => ![78, 308].includes(i) && P[i][1] < line(P[i][0]) - 0.003 * F).length;
        if (c) out.push("lips cross at " + c + " point(s)");
        return { out, ratio, folds: f, cross: c };
      };
      const z = () => new Float32Array(BS.length), set = o => { const v = z(); Object.entries(o).forEach(([k, x]) => { v[IDX[k]] = x; }); return v; };
      const poses = Object.entries(VIS).map(([k, o]) => [k, set(o)]).concat([
        ["aa-strong", set({ jawOpen: 0.6, mouthLowerDownLeft: 0.4, mouthLowerDownRight: 0.4 })],
        ["ee-strong", set({ jawOpen: 0.12, mouthStretchLeft: 0.6, mouthStretchRight: 0.6, mouthSmileLeft: 0.5, mouthSmileRight: 0.5 })],
        ["oo-strong", set({ jawOpen: 0.2, mouthPucker: 0.9, mouthFunnel: 0.5 })], ["smile", set({ mouthSmileLeft: 0.8, mouthSmileRight: 0.8, jawOpen: 0.1 })],
        ["blink", set({ eyeBlinkLeft: 1, eyeBlinkRight: 1 })], ["look down", set({ eyeLookDownLeft: 0.8, eyeLookDownRight: 0.8 })],
        ["look up", set({ eyeLookUpLeft: 0.8, eyeLookUpRight: 0.8 })], ["look aside", set({ eyeLookOutLeft: 0.8, eyeLookInRight: 0.8 })],
        ["half blink, looking down", set({ eyeBlinkLeft: 0.5, eyeBlinkRight: 0.5, eyeLookDownLeft: 0.6, eyeLookDownRight: 0.6 })]]);
      const issues = [], worst = { upT: [1, 1], loT: [1, 1], upW: [1, 1], mW: [1, 1] }, culprits = new Set();
      let folds = 0, cross = 0;
      for (const [name, v] of poses) {
        const e = evalPose(v);
        Object.entries(e.ratio).forEach(([k, r]) => { worst[k] = [Math.min(worst[k][0], r), Math.max(worst[k][1], r)]; });
        folds += e.folds; cross += e.cross;
        if (!e.out.length) continue;
        e.out.forEach(t => issues.push(name + ": " + t));
        // which channel is to blame: the pose without it passes (or gets better)
        v.forEach((x, k) => { if (x <= 0.05 || !/^(jaw|mouth|eye)/.test(BS[k])) return; const w = v.slice(); w[k] = 0;
          if (evalPose(w).out.length < e.out.length || evalPose(w).folds < e.folds) culprits.add(k); });
      }
      const aest = this.aesthetic(); aest.issues.forEach(t => issues.push("look: " + t));
      const r = x => +x.toFixed(2);
      return { ok: !issues.length, issues, poses: poses.length, aesthetic: aest.measures, lip_line: this.lipFix, folds, crossings: cross, culprits: [...culprits],
        range: Object.fromEntries(Object.entries(worst).map(([k, [a, b]]) => [k, [r(a), r(b)]])) };
    }
    // Aesthetic guardrail, measured on the rendered pixels of an open "aa" (the most revealing pose): the inside of the mouth
    // must read like a real one — teeth no brighter and no bluer than the whites of this face's eyes, teeth showing no more
    // than ~3 mm and a third of the opening, the cavity a deep shade of the lips (not black, not lighter than the lips),
    // and no stray bright or saturated-pink pixels inside the opening (no "gums" or flaps of lip).
    aesthetic() {
      const save = Float32Array.from(this.cur), z = new Float32Array(BS.length);
      z[IDX.jawOpen] = 0.45; z[IDX.mouthLowerDownLeft] = z[IDX.mouthLowerDownRight] = 0.25;
      this.cur = z; this._draw();
      const P = this._points(z, [0, 0, 0]), cr = this.crop, k = this.cv.width / cr.w, X = q => (q[0] - cr.x) * k, Y = q => (q[1] - cr.y) * k;
      const ring = IN_UP.concat(IN_LO.slice(1, -1)).map(i => [X(P[i]), Y(P[i])]);
      const xs = ring.map(q => q[0]), ys = ring.map(q => q[1]), x0 = Math.floor(Math.min(...xs)), y0 = Math.floor(Math.min(...ys));
      const w = Math.ceil(Math.max(...xs)) - x0 + 1, h = Math.ceil(Math.max(...ys)) - y0 + 1;
      const inside = (x, y) => { let c = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c; } return c; };
      const d = this.ctx.getImageData(x0, y0, Math.max(1, w), Math.max(1, h)).data, pal = this.palette;
      const lum = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b, lipL = lum(...pal.lip), scL = lum(...pal.sclera);
      let n = 0, cav = 0, cavN = 0, bright = 0, pink = 0, blue = 0, teethMax = 0;
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        if (!inside(x0 + x + 0.5, y0 + y + 0.5)) continue;
        const i = 4 * (y * w + x), R = d[i], G = d[i + 1], B = d[i + 2], L = lum(R, G, B); n++;
        if (L > scL * 1.04 + 4) bright++;
        if (L > lipL * 0.7 && R > G + 60 && R > B + 40) pink++;          // lip-pink flesh inside the opening = "gums"/flaps
        if (L > lipL * 0.7 && B > R + 6) blue++;
        if (L < lipL * 0.6) { cav += L; cavN++; }
        teethMax = Math.max(teethMax, L);
      }
      this.cur = save; this._draw();
      const issues = [], open = Math.hypot(P[13][0] - P[14][0], P[13][1] - P[14][1]);
      const cavRel = cavN ? cav / cavN / Math.max(1, lipL) : 0;
      if (!n) return { issues: ["the opening could not be measured"], measures: {} };
      if (bright / n > 0.01) issues.push("teeth brighter than the eye whites (" + (100 * bright / n).toFixed(1) + "% of the opening)");
      if (pink / n > 0.06) issues.push("lip-coloured flesh inside the opening (" + (100 * pink / n).toFixed(1) + "%)");
      if (blue / n > 0.01) issues.push("bluish teeth");
      if (cavRel < 0.08) issues.push("the inside of the mouth is flat black");
      if (cavRel > 0.6) issues.push("the inside of the mouth is too light");
      const teethMm = Math.min(open * 0.33, this.fit.teeth_mm * this.fit.pxmm) / this.fit.pxmm;
      if (teethMm > 3.2) issues.push("too much tooth showing");
      return { issues, measures: { opening_mm: +(open / this.fit.pxmm).toFixed(1), teeth_mm: +teethMm.toFixed(1), cavity_vs_lips: +cavRel.toFixed(2),
        bright_pct: +(100 * bright / n).toFixed(2), pink_pct: +(100 * pink / n).toFixed(2), teeth_vs_sclera: +(teethMax / Math.max(1, scL)).toFixed(2) } };
    }
    // check, and where a pose fails, soften only the channels to blame (×0.9 per round, at most 6 rounds) for this face
    autotune() {
      let q = this.qc(); const tuned = {};
      for (let round = 0; round < 6 && !q.ok && q.culprits.length; round++) {
        q.culprits.forEach(k => { this.gain[k] *= 0.9; tuned[BS[k]] = +this.gain[k].toFixed(2); });
        q = this.qc();
      }
      delete q.culprits; q.tuned = tuned; this.quality = q; this._draw();
      return q;
    }
    dispose() { this.el.innerHTML = ""; this.ctx = null; }
  }
  window.DepthFace = DepthFace;
  window.ARKIT52 = BS;
})();
