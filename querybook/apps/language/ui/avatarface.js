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
  const BROWS = new Set(["browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight"].map(k => IDX[k]));
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

  // Full-body calibration, measured frame by frame (face tracker) against a reference video of the same model speaking the
  // same lines (Gemini, October 2026): there the mouth opens mostly by lifting the upper lip and dropping the lower one,
  // with less jaw and little rounding; brows move 6–10× more; within a shot the head turns ~15°, nods ~12° and tilts
  // ~11°, the torso follows, and the camera cuts every ~2.5 s between a wide and a close shot with a slow push-in.
  const BODY_CAL = {
    // (revised after the first full-body test: stronger settings read as a worried brow and a sneer on a real face)
    // (1.43: measured against her two Gemini speaking clips by reproducing them — same voice, same words — and reading
    // both with the face tracker: more jaw, a stronger upper-lip arch and livelier brows brought ours closest to hers)
    gain: { jawOpen: 0.84, mouthLowerDownLeft: 1.2, mouthLowerDownRight: 1.2, mouthUpperUpLeft: 1.4, mouthUpperUpRight: 1.4, mouthPucker: 1.0,
            mouthFunnel: 0.9, mouthPressLeft: 1.5, mouthPressRight: 1.5, browInnerUp: 4.5, browOuterUpLeft: 4.5, browOuterUpRight: 4.5,
            browDownLeft: 1.4, browDownRight: 1.4, eyeSquintLeft: 1.1, eyeSquintRight: 1.1 },
    derive: { up: 0.35, upSmile: 0.2, down: 0.5 },     // (1.44: less lift tied to the jaw — each sound now sets its own upper lip)     // lips open with the jaw: upper lip lifts, lower lip drops (speaking smile)
    arch: 1.6,                                           // the upper lip arches up in the middle as the mouth opens
    teeth_mm: 6.5, teeth_frac: 0.5, lower_teeth: 0.12,  // upper front teeth show as she speaks, never a dark gape or a wall of teeth
    head: [3, 2.2, 4.5],                                 // yaw, pitch, roll of the WHOLE head (face, hair and skull move as one piece)
    parallax: [1.8, 1.4],                                // the little 3D turn inside the face itself (more makes it slide like a decal)
    sway: 1.0, breath: 1.2, torsoFollow: 0.3,
    shot_s: 2.5, shots: [1.0, 0.5, 0.78, 0.47], push: 0.05,
  };
  // The person's silhouette in the portrait: everything outside it is background and must never move. MediaPipe's
  // selfie segmenter (bundled, ~250 KB, Apache-2.0) runs once per portrait in the browser; without it the renderer
  // falls back to its fixed frame of anchors.
  let SEG = null;
  async function personMask(img) {
    if (!SEG) SEG = (async () => {
      const vision = await import("./vendor/mediapipe/vision_bundle.mjs");
      const files = await vision.FilesetResolver.forVisionTasks("vendor/mediapipe/wasm");
      const o = d => ({ baseOptions: { modelAssetPath: "vendor/mediapipe/selfie_segmenter.tflite", delegate: d }, outputConfidenceMasks: true, runningMode: "IMAGE" });
      try { return await vision.ImageSegmenter.createFromOptions(files, o("GPU")); } catch (e) { return vision.ImageSegmenter.createFromOptions(files, o("CPU")); }
    })();
    const seg = await SEG, k = Math.min(1, 1024 / Math.max(img.width, img.height)), c = document.createElement("canvas");
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    const r = seg.segment(c), m = r.confidenceMasks[0], out = { w: m.width, h: m.height, d: Float32Array.from(m.getAsFloat32Array()) };
    try { r.close(); } catch (e) { }
    return out;
  }
  // a soft "how much is this the person" field over the portrait: the mask widened a little (stray hair, a missed sliver
  // beside an arm) and feathered, sampled bilinearly in portrait pixels
  function personField(mask, W, H, grow, feather) {
    const { w, h, d } = mask, sx = w / W, r1 = Math.max(1, Math.round(grow * sx)), r2 = Math.max(1, Math.round(feather * sx));
    let a = new Float32Array(w * h); for (let i = 0; i < w * h; i++) a[i] = d[i] > 0.5 ? 1 : 0;
    const pass = (src, r, op, horiz) => { const o = new Float32Array(w * h);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { let v = op === "max" ? 0 : 0, n = 0;
        for (let k = -r; k <= r; k++) { const xx = horiz ? x + k : x, yy = horiz ? y : y + k; if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
          const q = src[yy * w + xx]; if (op === "max") { if (q > v) v = q; } else { v += q; n++; } }
        o[y * w + x] = op === "max" ? v : v / Math.max(1, n); }
      return o; };
    a = pass(pass(a, r1, "max", true), r1, "max", false);
    a = pass(pass(a, r2, "avg", true), r2, "avg", false);
    const raw = d;
    const at = (f, x, y) => { x = Math.max(0, Math.min(w - 1.001, x * sx)); y = Math.max(0, Math.min(h - 1.001, y * sx));
      const x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0, i = y0 * w + x0;
      return f[i] * (1 - fx) * (1 - fy) + f[i + 1] * fx * (1 - fy) + f[i + w] * (1 - fx) * fy + f[i + w + 1] * fx * fy; };
    return { soft: (x, y) => at(a, x, y), inside: (x, y) => at(raw, x, y) > 0.5, field: a };
  }
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
      const cal = Object.assign({ jaw: 1, spread: 1, round: 1, close: 1, arch: 1, teeth: 1, smooth_ms: 20, lead_ms: 40 },
        (window.QB_CAL && window.QB_CAL.params) || {}, (params && params.cal) || {});
      this.cal = cal;
      cal.head = cal.head || 1; cal.brow = cal.brow || 1;
      if (avatar.body) cal.arch = (cal.arch || 1) * BODY_CAL.arch;
      this.params = Object.assign({ lead_ms: cal.lead_ms, smooth_ms: cal.smooth_ms, head_gain: cal.head, label: avatar.label || "Synthetic avatar — AI-generated" }, params || {});
      const cg = { jawOpen: cal.jaw, mouthLowerDownLeft: cal.jaw, mouthLowerDownRight: cal.jaw, mouthStretchLeft: cal.spread, mouthStretchRight: cal.spread,
        mouthSmileLeft: cal.spread, mouthSmileRight: cal.spread, mouthDimpleLeft: cal.spread, mouthDimpleRight: cal.spread, mouthPucker: cal.round,
        mouthFunnel: cal.round, mouthClose: cal.close, mouthPressLeft: cal.close, mouthPressRight: cal.close,
        browDownLeft: cal.brow, browDownRight: cal.brow, browInnerUp: cal.brow, browOuterUpLeft: cal.brow, browOuterUpRight: cal.brow };
      this.calGain = Float32Array.from(BS.map(k => (cg[k] || 1) * (avatar.body ? BODY_CAL.gain[k] || 1 : 1)));
      this.headAxis = avatar.body ? BODY_CAL.head : [1, 1, 1];
      this.director = avatar.body && !(params && params.camera === "still");     // full body: the camera cuts and pushes in
      this.cur = new Float32Array(BS.length); this.head = [0, 0, 0]; this.t = null;
      this.ready = new Promise((res, rej) => {
        const img = new Image();
        img.onload = async () => {
          let mask = null;
          if (avatar.body || params && params.mask) { try { mask = await personMask(img); } catch (e) { mask = null; } }   // no silhouette: the fixed frame still holds
          try { this._setup(img, avatar.landmarks, mask); res(); } catch (e) { rej(e); } };
        img.onerror = () => rej(new Error("the portrait could not be loaded"));
        img.src = avatar.imageUrl;
      });
      if (avatar.turnId) this._loadTurn(avatar.turnId);
    }
    _setup(img, lm, mask) {
      if (!lm || lm.length < 468) throw new Error("this avatar has not been analysed yet — use “Analyse faces” in the library");
      const body = this.body = !!this.avatar.body;          // full-body avatar: the whole figure is shown and breathes and sways
      const scale = Math.min(1, (body ? 1600 : 1000) / Math.max(img.width, img.height));
      const W = Math.round(img.width * scale), H = Math.round(img.height * scale);
      const src = document.createElement("canvas"); src.width = W; src.height = H; src.getContext("2d").drawImage(img, 0, 0, W, H);
      this.src = src;
      const pts3 = lm.slice(0, 478).map(p => [p[0] * W, p[1] * H, (p[2] || 0) * W]);
      this.lipFix = this._refineLipLine(src, pts3);      // where the lips really meet, from the photo itself
      this.hasIris = pts3.length >= 478; this.hasDepth = lm[0].length > 2;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      pts3.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); });
      const fw = x1 - x0, fh = y1 - y0, fcx = (x0 + x1) / 2, fcy = (y0 + y1) / 2;
      const crop = body ? { x: Math.max(0, fcx - fw * 3.4), y: Math.max(0, y0 - fh * 0.9) } : { x: Math.max(0, fcx - fw * 1.1), y: Math.max(0, y0 - fh * 0.5) };
      crop.w = Math.min(W, fcx + fw * (body ? 3.4 : 1.1)) - crop.x; crop.h = (body ? H : Math.min(H, y1 + fh * 0.55)) - crop.y;
      // fixed anchors: a ring around the face and the crop's edge, so hair, neck and background stretch, never tear
      const anchors = [];
      for (let a = 0; a < 32; a++) {
        const q = [fcx + Math.cos(a / 32 * 2 * Math.PI) * fw * 0.8, fcy + Math.sin(a / 32 * 2 * Math.PI) * fh * 0.74, 0];
        // full body: the ring stays whole even where the head nears the top of the photo (the head must move up there too)
        if (!body || Math.min(q[0] - crop.x, crop.x + crop.w - q[0]) > 0.3 * fh) anchors.push(q);
      }
      for (let k = 0; k <= 4; k++) [[crop.x + crop.w * k / 4, crop.y], [crop.x + crop.w * k / 4, crop.y + crop.h], [crop.x, crop.y + crop.h * k / 4], [crop.x + crop.w, crop.y + crop.h * k / 4]]
        .forEach(([x, y]) => anchors.push([x, y, 0]));
      if (body) {                                         // above the head: points along the top that move with it, and a fixed row
        for (let k = 1; k < 8; k++) if (k % 2) anchors.push([crop.x + crop.w * k / 8, crop.y, 0]);   // beyond the picture, where any stretch stays out of sight
        for (let k = 0; k <= 8; k++) anchors.push([crop.x + crop.w * k / 8, crop.y - 0.9 * fh, 0]);
      }
      this.nEdge = anchors.length;                       // the crop's edge never moves (the background stays put)
      if (body) {                                         // a lattice over the figure carries breathing and sway to hair, shoulders and arms
        for (let j = 1; j < 10; j++) for (let k = 1; k < 8; k++) {
          const x = crop.x + crop.w * k / 8, y = crop.y + crop.h * j / 10;
          if (((x - fcx) / (fw * 0.95)) ** 2 + ((y - fcy) / (fh * 0.9)) ** 2 > 1) anchors.push([x, y, 0]);
        }
      }
      // the silhouette: pairs of points along the person's outline — one just outside (pinned: the background stays put),
      // one just inside (free: it moves with her) — so her edge moves crisply and nothing behind her slides
      // (revised: a band only ~0.1 face width wide tore the hair and shoulders into shards when she moved — the movement now
      // fades out over ~0.4 face width across her edge; the background beyond that band stays perfectly still)
      const pf = this.pfield = mask ? personField(mask, W, H, 0.06 * fw, 0.05 * fw) : null;
      // how much a point moves with her ramps smoothly from 1 just inside her edge to 0 about half a face width outside it
      // (wispy hair the outline misses moves with her head; nothing shears; the background beyond stays perfectly still)
      const wide = this.pwide = mask ? personField(mask, W, H, 0.12 * fw, 0.3 * fw) : null;
      if (pf && body) {
        const st = 0.2 * fw, out = 0.45 * fw, inn = 0.15 * fw;
        for (let y = crop.y + 0.1 * fh; y < crop.y + crop.h; y += st) {
          let prev = pf.inside(crop.x, y);
          for (let x = crop.x + 2; x < crop.x + crop.w; x += 2) {
            const now = pf.inside(x, y);
            if (now !== prev) { const dir = now ? 1 : -1;      // entering (left edge) or leaving (right edge) the person
              anchors.push([x - dir * out, y, 0, "out"], [x + dir * inn, y, 0, "in"]); prev = now; }
          }
        }
        for (let x = fcx - 1.8 * fw; x <= fcx + 1.8 * fw; x += st) {   // over the head
          for (let y = crop.y; y < fcy; y += 2) if (pf.inside(x, y)) { if (y > crop.y + 0.05 * fh) anchors.push([x, y - out, 0, "out"], [x, y + inn, 0, "in"]); break; }
        }
      }
      const seen = new Set();                            // each corner is listed by two edges: a point twice makes zero-area triangles
      this.base3 = pts3.concat(anchors.filter(([x, y]) => { const key = Math.round(x) + "," + Math.round(y);
        if (x < 0 || y < (body ? crop.y - fh : 0) || x > W || y > H || seen.has(key)) return false; seen.add(key); return true; }).map(q => q.slice(0, 3)));
      this.nFace = pts3.length;
      const ringN = 32, edgeOf = new Set();
      this.base3.forEach(([x, y], i) => { if (i >= pts3.length + ringN && (Math.abs(x - crop.x) < 0.5 || Math.abs(y - crop.y) < 0.5 || Math.abs(x - crop.x - crop.w) < 0.5 || Math.abs(y - crop.y - crop.h) < 0.5)) edgeOf.add(i); });
      if (body) {                                         // the top edge over the head is free to move with it; the row beyond the picture holds
        this.base3.forEach(([x, y], i) => {
          if (i < pts3.length) return;
          if (Math.abs(y - crop.y) < 0.5 && Math.abs(x - fcx) < 2.2 * fw) edgeOf.delete(i);
          if (y < crop.y - 1) edgeOf.add(i);
        });
      }
      // background: pinned — every helper point beyond the ramp (the ramp alone decides: a point the outline missed, like
      // wispy hair, still moves with her)
      if (pf && body) this.base3.forEach(([x, y], i) => { if (i >= pts3.length && wide.soft(x, y) < 0.03) edgeOf.add(i); });
      this.fixed = edgeOf;
      // how much each point belongs to her (1 inside, 0 in the background): every body and head movement is scaled by it
      this.personW = pf && body ? Float32Array.from(this.base3.map(([x, y], i) => i < pts3.length ? 1 : Math.min(1, wide.soft(x, y) * 1.1))) : null;
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
      this.tris = constrain(delaunay(sub).map(t => t.map(j => at.get(j))), Psub, cons).filter(t => t[0] !== t[1] && t[1] !== t[2] && t[0] !== t[2] &&
        Math.abs((triPts[t[1]][0] - triPts[t[0]][0]) * (triPts[t[2]][1] - triPts[t[0]][1]) - (triPts[t[2]][0] - triPts[t[0]][0]) * (triPts[t[1]][1] - triPts[t[0]][1])) > 1e-6);
      this.triPts = triPts; this.cons = cons;
      // the opening: triangles whose centre lies between the inner lip lines (in the parted copy)
      const poly = IN_UP.concat(IN_LO.slice(1, -1)).map(i => triPts[i]);
      const inside = (x, y) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c; } return c; };
      const isIn = t => { const R = this.ring; if (!(R.has(t[0]) && R.has(t[1]) && R.has(t[2]))) return false;
        return inside((triPts[t[0]][0] + triPts[t[1]][0] + triPts[t[2]][0]) / 3, (triPts[t[0]][1] + triPts[t[1]][1] + triPts[t[2]][1]) / 3); };
      this.inner = this.tris.filter(isIn);
      this.mesh = this.tris.filter(t => !isIn(t));
      const sgn = t => Math.sign((triPts[t[1]][0] - triPts[t[0]][0]) * (triPts[t[2]][1] - triPts[t[0]][1]) - (triPts[t[2]][0] - triPts[t[0]][0]) * (triPts[t[1]][1] - triPts[t[0]][1]));
      this.meshSign = this.mesh.map(sgn);
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
      const pxW = body ? Math.min(crop.w, 720) : outW;   // a full figure is drawn sharper than it is shown (the face stays detailed in video)
      cv.width = Math.round(pxW); cv.height = Math.round(pxW * crop.h / crop.w);
      cv.style.width = "100%"; cv.style.maxWidth = (body ? Math.max(outW, 420) : outW) + "px"; cv.style.borderRadius = "10px";
      this.bodyShape = { fw, fh, fcx, fcy, H };
      this.el.innerHTML = ""; this.el.appendChild(cv);
      const lab = document.createElement("div"); lab.className = "small muted"; lab.textContent = this.params.label; this.el.appendChild(lab);
      this.cv = cv; this.ctx = cv.getContext("2d");
      this.gl = this._glInit();                          // the photo is warped on the graphics card (fast); 2D canvas if WebGL is missing
      this.autotune();                                    // quality control before the face ever speaks (draws when done)
      this._pickRenderer();
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
      // each upper lid's own skin: just above the lid crease, below the brow
      const lidOf = (lid, brow) => { const q = mid(lid, brow, 0.38); return avg(q[0], q[1], ew * 0.07).map(Math.round); };
      return { lip: lip.map(Math.round), sclera: sclera.map(Math.round), teeth, skin: skin.map(Math.round), lidLeft: lidOf(386, 334), lidRight: lidOf(159, 105),
        crease: tone(skin, 0.55), sheen: tone(skin, 1.12),
        cavDeep: tone(lip, 0.22, [8, 1, 1]), cavEdge: tone(lip, 0.45, [8, 0, 0]), tongue: tone(lip, 0.4, [8, -5, -4]),
        tongueHi: tone(lip, 0.52, [12, -7, -5]), gum: tone(lip, 0.75) };
    }
    // Mouth fit: the speaking mouth sized and shaped from this face's own anatomy, measured once per portrait.
    //  * scale: millimetres per pixel from the iris (≈11.7 mm across in adults, the steadiest size in a face),
    //    cross-checked against face height (forehead to chin ≈ 150–230 mm);
    //  * size: conversational speech opens the lips about 0.28 × mouth width on an open vowel ("aa"), 9–16 mm,
    //    so a small mouth opens less than a large one;
    //  * shape: the opening follows this person's own lower-lip outline, blended with an anatomical lens;
    //  * teeth: upper incisors show at most ~5 mm on a wide open vowel (about 3 mm in ordinary speech), never more than a third of the opening.
    _fit() {
      const B = this.base3, d = (a, b) => Math.hypot(B[a][0] - B[b][0], B[a][1] - B[b][1]);
      let pxmm = null, how = "iris";
      if (this.hasIris) { const iris = (d(469, 471) + d(470, 472) + d(474, 476) + d(475, 477)) / 4; if (iris > 2) pxmm = iris / 11.7; }
      const Fmm = pxmm ? this.F / pxmm : 0;
      if (!pxmm || Fmm < 150 || Fmm > 230) { pxmm = this.F / 185; how = "face height"; }
      const Wmm = this.Wm / pxmm, upLip = d(0, 13) / pxmm, loLip = d(14, 17) / pxmm, chin = d(17, 152) / pxmm;
      const aa = Math.max(11, Math.min(19, 0.34 * Wmm));                      // lip opening on "aa", mm (clear articulation, measured on a reference speaker)
      const jaw1 = aa / 0.45 * pxmm;                                            // the speech engine's "aa" is jawOpen ≈ 0.45
      const gain = jaw1 / (0.184 * this.F);                                     // the jaw field gives 0.184·F of opening at 1
      // the person's lower-lip outline under the lip line, normalised: the opening takes the same curve
      const line = lipLine(B), outl = OUT_LO.map(i => [B[i][0], B[i][1] - line(B[i][0])]).sort((a, b) => a[0] - b[0]);
      const depth = Math.max(1e-6, ...outl.map(q => q[1]));
      const own = x => { if (x <= outl[0][0] || x >= outl[outl.length - 1][0]) return 0;
        for (let j = 1; j < outl.length; j++) if (x <= outl[j][0]) { const t = (x - outl[j - 1][0]) / ((outl[j][0] - outl[j - 1][0]) || 1);
          return Math.max(0, (outl[j - 1][1] + (outl[j][1] - outl[j - 1][1]) * t) / depth); } return 0; };
      return { pxmm, scale_from: how, mouth_mm: +Wmm.toFixed(1), upper_lip_mm: +upLip.toFixed(1), lower_lip_mm: +loLip.toFixed(1), chin_mm: +chin.toFixed(1),
        aa_open_mm: +aa.toFixed(1), jaw_gain: gain, teeth_mm: Math.min(5, 0.3 * aa) * this.cal.teeth, own };
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
      // The lower lip's inner edge must curve down like the upper one arches up: the taper reaches nothing at both corners
      // (measured from the true middle between the corners), and the person's own lip outline only shades it — a flat
      // lower lip in the photo must not make a flat, straight lower edge in speech (it reads as a swollen lip)
      const Mc = (B[61][0] + B[291][0]) / 2;
      const prof = i => { const t = Math.min(1, Math.abs(B[i][0] - Mc) / (0.5 * Wm)), lens = Math.pow(1 - t * t, 0.8);
        return lens * (0.75 + 0.25 * Math.min(1, fit.own(B[i][0]) * 1.15)); };
      const lipBand = i => { const ax = Math.abs(B[i][0] - M[0]);
        return Math.exp(-(((B[i][1] - M[1]) / (0.09 * F)) ** 2)) * (ax < 0.6 * Wm ? 1 : Math.exp(-(((ax - 0.6 * Wm) / (0.15 * Wm)) ** 2))); };
      const wOpen = i => 1 - lipBand(i) * (1 - prof(i));
      // the jaw is a hinge: the whole lower face below the mouth swings down — widest at the chin, fading toward the ears
      const jawW = i => Math.exp(-(((B[i][0] - M[0]) / (0.75 * F)) ** 2)) * below(i) *
        (LOWER.has(i) ? 1 : smooth(-0.02 * F, 0.12 * F, B[i][1] - M[1] + 0.06 * F));
      // Each lip moves as a solid band: every row of a lip moves together, so its thickness and its width stay what they
      // are in the portrait (lips do not stretch or shrink while we talk). Only the skin around them takes up the motion:
      // above the upper lip it fades out within ~6% of the face, below the lower lip it blends into the chin.
      const outUp = lipLine(B, OUT_UP), outLo = lipLine(B, OUT_LO);
      const lat = i => { const ax = Math.abs(B[i][0] - M[0]); return ax < 0.5 * Wm ? 1 : Math.exp(-(((ax - 0.5 * Wm) / (0.12 * Wm)) ** 2)); };
      const upBand = i => UPPER.has(i) ? 1 : (B[i][1] < outUp(B[i][0]) ? (1 - smooth(0, 0.06 * F, outUp(B[i][0]) - B[i][1])) * lat(i) : 0);
      const loBand = i => LOWER.has(i) ? 1 : (B[i][1] > outLo(B[i][0]) ? (1 - smooth(0, 0.1 * F, B[i][1] - outLo(B[i][0]))) * lat(i) : 0);
      const chinMix = i => smooth(0, 0.1 * F, B[i][1] - outLo(B[i][0]));    // 0 at the lower lip, 1 well down the chin
      // corners: rounding and spreading move the corners, not the middle of the lips
      // rounding gathers the whole lip toward the true middle of the mouth — half-way between the corners, not the lip-centre
      // landmarks (off-centre on a smiling or turned face) — so both corners travel the same distance and the lips keep
      // their proportions as they narrow; the skin around follows within the lip bands
      const Mx = (cL[0] + cR[0]) / 2, CORNERS = [61, 291, 78, 308];
      // how far a point sits from the line between the lips (its own lip's thickness, for the skin just outside a lip):
      // scaling this makes the lips fuller (rounded, pushed forward and turned out) or thinner (spread, stretched flat)
      const thick = (i, ub, lb) => { const [x, y] = B[i], m = mid(x);
        if (UPPER.has(i) || LOWER.has(i)) return y - m;
        return y < m ? (outUp(x) - m) * ub : (outLo(x) - m) * lb; };
      for (let i = 0; i < nF; i++) {
        const [x, y] = B[i], lz = lipZ(i), up = above(i), lo = below(i), sL = side(i, 1), sR = side(i, -1), dxm = x - M[0];
        const pf = prof(i), ub = upBand(i), lb = loBand(i), jg = fit.jaw_gain, sg = Math.sign(dxm);
        // jaw: the chin swings down; the lower lip rides on it as a band, opening as a lens (most at the centre)
        // the lower lip rides the jaw as a lens; the chin travels further than the lip (≈1.35×), as a jaw rotating open does
        const jawMove = LOWER.has(i) ? pf : lo > 0.5 ? pf + (1.35 - pf) * chinMix(i) : 0;
        // a real mouth opens as a curve on both lips: the lower lip drops (about 70% of the opening) and the upper lip
        // arches up toward its middle (about 30%), both tapering to the corners — never a flat upper edge
        add("jawOpen", i, -dxm * 0.03 * jawW(i) * chinMix(i), 0.155 * F * jawW(i) * jawMove * jg, 0.03 * F * jawW(i) * jg);
        const arch = Math.pow(Math.max(0, 1 - (Math.min(1, Math.abs(dxm) / (0.5 * Wm))) ** 2), 1.5);
        add("jawOpen", i, 0, -0.03 * F * arch * ub * jg * this.cal.arch, 0);
        add("jawForward", i, 0, 0.006 * F * jawW(i), -0.05 * F * jawW(i));
        add("jawLeft", i, 0.045 * F * jawW(i), 0, 0); add("jawRight", i, -0.045 * F * jawW(i), 0, 0);
        // closing the lips against an open jaw: the lower lip band rises back to the upper lip
        add("mouthClose", i, 0, -0.17 * F * jawW(i) * 1.1 * jg * (LOWER.has(i) ? pf : lo > 0.5 ? pf * (1 - chinMix(i)) : 0), 0);
        // rounding (o, u, w, ch): the corners come in and the lips push forward; the lips keep their own width
        // rounding (oo, w, r, sh, o): the lips gather toward the middle (pucker narrows the mouth by up to ~30%, funnel ~12%)
        // and grow fuller as they push forward and turn out, most at the centre, least at the corners
        const gw = CORNERS.includes(i) || UPPER.has(i) || LOWER.has(i) ? 1 : Math.max(ub, lb);
        const tk = thick(i, ub, lb) * (1 - 0.7 * smooth(0.3 * Wm, 0.5 * Wm, Math.abs(x - Mx)));
        // (revised: a strong pout read as swollen lips and an exaggerated pucker — rounding narrows the mouth by up to ~18%
        // and the lips stay their own thickness within a few percent, as they look from the front)
        add("mouthFunnel", i, -0.08 * (x - Mx) * gw, (lb - ub) * 0.012 * F * pf + 0.02 * tk, -0.03 * F * lz);
        add("mouthPucker", i, -0.2 * (x - Mx) * gw, 0.04 * tk - 0.016 * F * ub * pf, -0.045 * F * lz);   // the upper lip flares up and out as it rounds
        add("mouthLeft", i, 0.13 * Wm * lz, 0, 0); add("mouthRight", i, -0.13 * Wm * lz, 0, 0);
        for (const [k, s, c] of [["Left", 1, cL], ["Right", -1, cR]]) {
          const cw = g(i, c, 0.24 * Wm), sd = s > 0 ? sL : sR;
          add("mouthSmile" + k, i, s * 0.09 * Wm * cw, -0.06 * F * cw - 0.04 * F * ub * pf * sd, 0);   // the upper lip's middle rises with the corners (upper teeth show)
          add("mouthFrown" + k, i, s * 0.03 * Wm * cw, 0.045 * F * cw, 0);
          add("mouthDimple" + k, i, s * 0.03 * Wm * cw, -0.008 * F * cw, 0.02 * F * cw);
          add("mouthStretch" + k, i, s * 0.08 * Wm * cw, 0.01 * F * cw - 0.05 * tk * sd - 0.03 * F * ub * pf * sd, 0);   // spread lips thin out; the upper lip's middle lifts
          // pressing: the outer edges of the lips draw in toward the closed line; the line itself stays put (never crosses)
          const outer = UPPER.has(i) || LOWER.has(i) ? Math.min(1, Math.abs(y - mid(x)) / (0.05 * F)) : 0;
          add("mouthPress" + k, i, 0, (ub - lb) * 0.014 * F * outer * sd, 0);
          add("mouthLowerDown" + k, i, 0, 0.06 * F * lb * sd * pf, 0);           // a curve, deepest in the middle
          add("mouthUpperUp" + k, i, 0, -0.03 * F * ub * sd * pf, 0);                // the upper lip arches up in the middle, not as a block
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
          add("browInnerUp", i, 0, -0.045 * F * g(i, inC, 0.06 * F) * (bw > 0.01 ? 1 : 0.4), 0);
          add("browOuterUp" + k, i, 0, -0.045 * F * g(i, outC, 0.06 * F), 0);
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
          add("eyeSquint" + k, l, 0, -dy * 0.42, 0);
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
      // the face's outline does not move with the cheeks, the squint, the nose or the brows: their movement fades to nothing
      // at the outline (thin triangles there flipped over — a smear by the cheekbones — when she smiled or squinted)
      const OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
        172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
      const segD = (p, a, b) => { const dx = b[0] - a[0], dy = b[1] - a[1], u = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
        return Math.hypot(p[0] - a[0] - u * dx, p[1] - a[1] - u * dy); };
      const toOval = i => { let m = Infinity; for (let j = 0; j < OVAL.length; j++) m = Math.min(m, segD(B[i], B[OVAL[j]], B[OVAL[(j + 1) % OVAL.length]])); return m; };
      const fade = Float32Array.from({ length: nF }, (_, i) => smooth(0, 0.06 * F, toOval(i)));
      BS.forEach((k, ki) => { if (!/^(cheek|eyeSquint|noseSneer|brow)/.test(k)) return; const d = D[ki];
        for (let i = 0; i < nF; i++) for (let q = 0; q < 3; q++) d[3 * i + q] *= fade[i]; });
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
    // The camera of a full-body avatar: shots of ~2.5 s alternating wide and close, each with a slow push-in, framed on
    // the face (the output keeps its size; only the part of the photo it shows changes)
    _camera(t) {
      if (!this.director || !this.t) return null;
      const c = this.crop, k = Math.floor(t / BODY_CAL.shot_s), u = (t - k * BODY_CAL.shot_s) / BODY_CAL.shot_s;
      // never closer than the photo's own resolution allows (at least ~0.62 photo pixels per screen pixel: no soft blow-ups)
      const s = Math.max(BODY_CAL.shots[k % BODY_CAL.shots.length] * (1 - BODY_CAL.push * u), Math.min(1, 0.62 * this.cv.width / c.w));
      const w = c.w * s, h = c.h * s, fx = this.fc[0], fy = this.fc[1] - this.F * 0.1;
      const x = Math.max(0, Math.min(this.src.width - w, fx - w / 2)), y = Math.max(0, Math.min(this.src.height - h, s >= 0.99 ? c.y : fy - h * 0.36));
      return s >= 0.99 && u === 0 ? null : { x, y: s >= 0.99 ? c.y + (c.h - h) * 0.15 : y, w, h };
    }
    // Turnaround: the person's own frames of turning on the spot (side and back views a photo cannot give), aligned to this
    // avatar's face. Playing it cuts to a medium shot the frames cover, fades into them, and fades back to the talking photo.
    _loadTurn(id) {                                       // every recorded move of this avatar (the turnaround is one of them)
      fetch("/api/avatars/motions?id=" + id).then(r => r.json()).then(d => {
        this.moves = {};
        for (const m of (d && d.motions) || []) {
          const imgs = [];
          for (let i = m.start || 0; i <= (m.end === undefined ? m.frames - 1 : m.end); i++) { const im = new Image(); im.src = "/api/avatars/motion_frame?id=" + id + "&slug=" + m.slug + "&i=" + i; imgs[i] = im; }
          this.moves[m.slug] = { meta: m, imgs };
        }
        this.turnSet = this.moves["turn-around"] || null;
        if (this._pendingWords) this.cueTurns(this._pendingWords);
      }).catch(() => {});
    }
    moveList() { return Object.values(this.moves || {}).filter(x => !x.meta.take_of).map(x => ({ slug: x.meta.slug, name: x.meta.name, words: x.meta.words })); }
    // Play a move: cut to the shot its frames cover, fade into them, and back to the talking photo. at: a time on the speech
    // track (a word cue); none: now (wall clock). At the person's own pace (a real turn on the spot takes ~7–8 s).
    playMove(slug, at) {
      // a move with several takes plays them in turn (the same words never replay the identical clip)
      const takes = this.moves ? [slug].concat(Object.values(this.moves).filter(x => x.meta.take_of === slug).map(x => x.meta.slug)) : [];
      this.takeN = this.takeN || {};
      if (takes.length > 1) { const k = this.takeN[slug] = ((this.takeN[slug] === undefined ? -1 : this.takeN[slug]) + 1) % takes.length; slug = takes[k]; }
      const mv = this.moves && this.moves[slug];
      if (!mv || this.turning) return false;
      const m = mv.meta, s0 = m.start || 0, s1 = m.end === undefined ? m.frames - 1 : m.end;
      const k = this.F / (m.face_h * m.height), fw = m.width * k, fh = m.height * k, asp = this.cv.width / this.cv.height;
      const vh = Math.min(fh, fw / asp) * 0.9, vw = vh * asp, fx = this.fc[0] - m.width / 2 * k, fy = this.fc[1] - m.face_cy * m.height * k;
      this.turning = { slug, set: mv, clock: at === undefined ? "wall" : "track", t0: at === undefined ? performance.now() / 1000 : at, s0, s1,
        dur: (s1 - s0 + 1) / m.fps, k, fx, fy, view: { x: fx + (fw - vw) / 2, y: fy + (fh - vh) * 0.3, w: vw, h: vh } };
      return true;
    }
    turnAround(at) { return this.playMove("turn-around", at); }
    // the words that set off each move ("turn around", "stretch", "water" …), at the moment they are spoken
    cueTurns(words) {
      this._pendingWords = words; this.moveQueue = [];
      const norm = x => String(x || "").toLowerCase().replace(/[^a-z']/g, "").replace(/'/g, ""), W = (words || []).map(w => norm(w.word));
      this.turnCues = [];
      for (const mv of Object.values(this.moves || {}).filter(x => !x.meta.take_of)) for (const phrase of mv.meta.words || []) {
        const P = phrase.split(/\s+/).map(norm).filter(Boolean);
        if (!P.length) continue;
        for (let i = 0; i + P.length <= W.length; i++) {
          const hit = P.every((p, j) => W[i + j] === p || (p.length >= 4 && W[i + j].startsWith(p)) || (p === "turn" && /^turn/.test(W[i + j])));
          if (hit) this.turnCues.push({ t: words[i].start, slug: mv.meta.slug });
        }
      }
      this.turnCues.sort((a, b) => a.t - b.t);
      // one sentence often names a move twice ("a swim in the pool"): once is enough within a few seconds
      this.turnCues = this.turnCues.filter((c, i, all) => !all.slice(0, i).some(p => p.slug === c.slug && c.t - p.t < 4));
    }
    _turnNow() {
      const T = this.turning; if (!T) return null;
      const e = (T.clock === "track" ? (this.t || 0) : performance.now() / 1000) - T.t0;
      if (e > T.dur) { this.turning = null; return null; }
      return e < 0 ? null : e;
    }
    _turnOverlay(c) {
      const T = this.turning, e = this._turnNow(); if (e === null || !T) return;
      const m = T.set.meta, idx = T.s0 + Math.min(T.s1 - T.s0, Math.floor(e / T.dur * (T.s1 - T.s0 + 1))), img = T.set.imgs[idx];
      if (!img || !img.complete || !img.naturalWidth) return;
      const a = Math.max(0, Math.min(1, e / 0.2, (T.dur - e) / 0.25)), cr = this.view || this.crop, kk = this.cv.width / cr.w;
      c.save(); c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = a;
      c.drawImage(img, (T.fx - cr.x) * kk, (T.fy - cr.y) * kk, m.width * T.k * kk, m.height * T.k * kk);
      c.restore();
    }
    frame(track, t) {
      this._advance(track, t);
      this.view = this._turnNow() !== null ? this.turning.view : this.fixedView || this._camera(t);
      this._draw();
    }
    // one step of the animation state (shared by playback and the delivery check, so the check sees exactly what plays)
    _advance(track, t) {
      const tt = t + this.params.lead_ms / 1000, tgt = this._target(track, tt);
      const dt = this.t === null ? 1 / 24 : Math.max(0, Math.min(0.2, t - this.t)); this.t = t;   // the first frame eases in from rest
      const a = 1 - Math.exp(-dt / Math.max(0.005, this.params.smooth_ms / 1000));
      const hold = this.body ? Math.exp(-dt / 0.07) : 0;                 // full body: a blink stays shut a little longer (~0.25 s)
      for (let k = 0; k < BS.length; k++) this.cur[k] = k === IDX.eyeBlinkLeft || k === IDX.eyeBlinkRight ? Math.max(tgt[k], this.cur[k] * hold) : this.cur[k] + (tgt[k] - this.cur[k]) * a;
      this.head = this.head.map((h, q) => h + ((this.headT || [0, 0, 0])[q] - h) * a);
      // moves named in the script: each starts as its words are spoken; one named while another plays follows it
      if (this.turnCues && this.tPrev !== undefined) for (const cu of this.turnCues) if (this.tPrev < cu.t && cu.t <= t) (this.moveQueue = this.moveQueue || []).push(cu.slug);
      if (this.moveQueue && this.moveQueue.length && this._turnNow() === null) this.playMove(this.moveQueue.shift(), t);
      if (this.turning && this.turning.clock === "track" && this.tPrev !== undefined && t === this.tPrev) {   // the speech ended or paused mid-turn:
        this.turning.t0 = performance.now() / 1000 - (t - this.turning.t0); this.turning.clock = "wall";     // she finishes turning anyway
      }
      this.tPrev = t;
    }
    setChannels(values) { Object.entries(values || {}).forEach(([k, v]) => { if (k in IDX) this.cur[IDX[k]] = v; }); this._draw(); }
    draw(m) {                                                // live mirroring from a tracked camera face
      const v = {}; BS.forEach(k => { v[k] = 0; });
      v.jawOpen = Math.min(1, (m.open || 0) * 1.1); v.mouthStretchLeft = v.mouthStretchRight = Math.max(0, ((m.width || 0.55) - 0.55) * 2);
      v.mouthSmileLeft = v.mouthSmileRight = m.smile || 0;
      this.setChannels(v);
    }
    // Idle life of a standing figure: breathing (chest and shoulders rise, the head with them) and a slow shift of weight that
    // sways everything above the hips, growing with height; the crop's edge stays still so the background never slides.
    _bodyMove(x, y, t) {
      const { fw, fh, fcx, fcy, H } = this.bodyShape;
      const pivot = H + 2.2 * fh, up = Math.max(0, Math.min(1.3, (pivot - y) / (pivot - fcy)));
      const col = 1 - smooth(3.0 * fw, 4.6 * fw, Math.abs(x - fcx));   // the whole body moves as one piece (arms included: no shear)
      const sway = 0.045 * BODY_CAL.sway * (this.cal.sway ?? 1) * fh * (0.75 * Math.sin(2 * Math.PI * t / 6.3) + 0.25 * Math.sin(2 * Math.PI * t / 2.9 + 1.1));
      const br = 0.5 - 0.5 * Math.cos(2 * Math.PI * t / 4.1);
      const chest = smooth(fcy + 0.6 * fh, fcy + 1.4 * fh, y) * (1 - smooth(fcy + 2.8 * fh, fcy + 4 * fh, y)), above = 1 - smooth(fcy + 1.4 * fh, fcy + 2.4 * fh, y);
      const dy = -0.018 * BODY_CAL.breath * (this.cal.breath ?? 1) * fh * br * Math.max(chest, above), dx = sway * up + (x - fcx) * 0.003 * br * chest;
      return [dx * col, dy * col];
    }
    _points(chan, head) {
      const n = this.base3.length, out = new Array(n), c = Float32Array.from(chan || this.cur), D = this.D, nF = this.nFace, g = this.params.head_gain;
      if (this.body) for (const k of ["Left", "Right"]) {           // a speaking smile: the lips, not only the jaw, open the mouth
        const j = c[JAW], dv = BODY_CAL.derive, up = IDX["mouthUpperUp" + k], dn = IDX["mouthLowerDown" + k];
        // the upper lip does not lift while the lips close (m, b, p, f) or round (oo, w): otherwise the opening comes only
        // from the top and the lower lip's edge stays straight
        const hold = Math.min(1, c[MC] + c[IDX["mouthPress" + k]] + c[IDX.mouthRollLower]), rnd = Math.min(1, Math.max(c[IDX.mouthPucker], c[IDX.mouthFunnel]));
        c[up] = Math.min(1, c[up] + (dv.up * j + dv.upSmile * c[IDX["mouthSmile" + k]] * Math.min(1, 4 * j)) * (1 - hold) * (1 - 0.6 * rnd));
        c[dn] = Math.min(1, c[dn] + dv.down * j);
      }
      // while an eye closes, its "wide", squint and gaze give way to the lid (together they fought the blink and folded the eye)
      for (const k of ["Left", "Right"]) {
        const bl = Math.min(1, c[IDX["eyeBlink" + k]]);
        c[IDX["eyeWide" + k]] *= 1 - bl; c[IDX["eyeSquint" + k]] *= 1 - 0.7 * bl;
        for (const d of ["Up", "Down", "In", "Out"]) c[IDX["eyeLook" + d + k]] *= 1 - 0.8 * bl;
      }
      // a mouth widens at most ~10% in speech: stretch, smile and dimple share one soft-limited budget per side
      for (const k of ["Left", "Right"]) {
        const ks = ["mouthStretch" + k, "mouthSmile" + k, "mouthDimple" + k].map(q => IDX[q]);
        const wide = 0.08 * c[ks[0]] + 0.09 * c[ks[1]] + 0.03 * c[ks[2]], cap = 0.09;
        if (wide > 1e-4) { const f = cap * Math.tanh(wide / cap) / wide; ks.forEach(q => { c[q] *= f; }); }
      }
      const [yaw, pitch, roll] = (head || this.head).map((d, q) => d * g * this.headAxis[q] * Math.PI / 180), [px, py, pz] = this.pivot;
      // full body: the face only gets a little 3D turn of its own; the turn and the tilt move the whole head — face, hair
      // and skull — as one rigid piece (below), so the face never slides over the head like a decal
      const yawF = this.body ? yaw / this.headAxis[0] * BODY_CAL.parallax[0] : yaw, pitchF = this.body ? pitch / this.headAxis[1] * BODY_CAL.parallax[1] : pitch, rollF = this.body ? 0 : roll;
      const cy = Math.cos(yawF), sy = Math.sin(yawF), cp = Math.cos(pitchF), sp = Math.sin(pitchF), cr = Math.cos(rollF), sr = Math.sin(rollF);
      for (let i = 0; i < n; i++) {
        let [x, y, z] = this.base3[i];
        if (i < nF || i >= this.nX0) {
          for (let k = 0; k < c.length; k++) {
            let w = (k === MC ? Math.min(c[k], c[JAW]) : c[k]) * this.gain[k] * this.calGain[k];   // lips can only close against an open jaw
            if (w > 0.85 && BROWS.has(k)) w = 0.85;                                               // brows stay within their range
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
      if (this.body) {                     // the whole head as one piece: tilt about the neck, and a turn/nod that carries it sideways/up
        const F = this.F, [hx, hy] = this.fc, { fw } = this.bodyShape, c2 = Math.cos(roll), s2 = Math.sin(roll);
        // the face's own little 3D turn moves it by (mx, my): the hair and skull must move exactly the same way (opposite
        // ways tear the forehead), and the whole head then carries on a little further in that same direction
        // (from the head's turn alone — never from the brows or the forehead skin: a brow raise must not lift the whole
        // region above the face, which read as the head and the background jumping for no reason)
        const O = [10, 109, 338, 67, 297, 103, 332];          // the top of the forehead, where the hair begins
        let mx = 0, my = 0;
        O.forEach(i => { const [x, y, z] = this.base3[i], X = x - px, Y = y - py, Z = z - pz, X1 = X * cy + Z * sy, Z1 = -X * sy + Z * cy;
          mx += X1 - X; my += Y * cp - Z1 * sp - Y; });
        mx /= O.length; my /= O.length;
        const k = 1.5;
        const H2 = (x, y, face) => [px + (x - px) * c2 - (y - py) * s2 + (face ? k - 1 : k) * mx, py + (x - px) * s2 + (y - py) * c2 + (face ? k - 1 : k) * my];
        for (let i = 0; i < n; i++) {
          if (this.fixed.has(i)) continue;
          let w = 1;
          if (i >= nF) {
            const [x0, y0] = this.base3[i], ax = Math.abs(x0 - hx) / (fw * 0.95);
            // above the face the whole head column moves (hair up to the top of the picture); below, it fades into the neck
            w = y0 < hy ? 1 - smooth(1.15, 2.0, ax) : 1 - smooth(1.15, 2.3, Math.hypot(ax, (y0 - hy) / (F * 0.9)));
            if (this.personW) w *= this.personW[i];             // only her head and hair: the background beside them stays
          }
          if (w <= 0) continue;
          const q = i < nF ? H2(out[i][0], out[i][1], true) : H2(this.base3[i][0], this.base3[i][1], false);
          out[i] = [out[i][0] + w * (q[0] - out[i][0]), out[i][1] + w * (q[1] - out[i][1])];
        }
      }
      if (this.body && !head && this.t !== null) {                          // checks (qc) pass a head pose and see the figure at rest (t = 0 is a time, not "none")
        const { fw, fh, fcx, H } = this.bodyShape, hp = H + 2.2 * fh;
        const tr = BODY_CAL.torsoFollow * roll, ty = BODY_CAL.torsoFollow * Math.sin(yaw) * fh * 1.2, ct = Math.cos(tr), st = Math.sin(tr);
        for (let i = 0; i < n; i++) {
          if (this.fixed.has(i)) continue;
          const [x0, y0] = this.base3[i], [bx, by] = this._bodyMove(x0, y0, this.t);
          // the torso follows the head a little: it leans with the tilt (about the hips) and turns with it
          const col = 1 - smooth(3.0 * fw, 4.6 * fw, Math.abs(x0 - fcx)), up = Math.max(0, Math.min(1.2, (hp - y0) / (hp - this.fc[1])));
          const rx = fcx + (x0 - fcx) * ct - (y0 - hp) * st - x0, ry = hp + (x0 - fcx) * st + (y0 - hp) * ct - y0;
          const pw = this.personW ? this.personW[i] : 1;                    // she moves; what is behind her does not
          const w = col * pw;                                               // face, hair and body lean together
          out[i] = [out[i][0] + pw * bx + w * (rx + ty * up), out[i][1] + pw * by + w * ry];
        }
      }
      return out;
    }
    // Use whichever way of drawing is faster on this computer (graphics card vs. CPU), timed on the face itself with the
    // head moving (every triangle redrawn) — a slow draw is a jerky, puppet-like face.
    _pickRenderer() {
      const time = () => { const h = this.head, t0 = performance.now();
        for (let i = 0; i < 6; i++) { this.head = [3 * Math.sin(i), 2 * Math.cos(i), 0]; this._draw(); }
        this.head = h; return (performance.now() - t0) / 6; };
      const gl = this.gl;
      const tGL = gl ? time() : Infinity;
      this.gl = null; const t2D = time();
      this.gl = gl && tGL <= t2D ? gl : null;
      this.renderer = { method: this.gl ? "WebGL (graphics card)" : "2D canvas", ms_per_frame: +Math.min(tGL, t2D).toFixed(1), webgl_ms: isFinite(tGL) ? +tGL.toFixed(1) : null, canvas_ms: +t2D.toFixed(1) };
      this._draw();
    }
    // WebGL: one textured mesh, drawn in two layers (portrait + its own mouth, then the moving face) so the inside of the
    // mouth can sit between them. Positions are uploaded each frame; triangles and texture stay on the card.
    _glInit() {
      try {
        const glc = document.createElement("canvas"); glc.width = this.cv.width; glc.height = this.cv.height;
        const gl = glc.getContext("webgl", { premultipliedAlpha: true, preserveDrawingBuffer: true, alpha: true, antialias: true });
        if (!gl) return null;
        const sh = (t, src) => { const x = gl.createShader(t); gl.shaderSource(x, src); gl.compileShader(x); if (!gl.getShaderParameter(x, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(x)); return x; };
        const prog = gl.createProgram();
        gl.attachShader(prog, sh(gl.VERTEX_SHADER, "attribute vec2 aPos; attribute vec2 aUv; uniform vec4 uCrop; varying vec2 vUv;" +
          "void main(){ vUv = aUv; gl_Position = vec4((aPos.x - uCrop.x) / uCrop.z * 2.0 - 1.0, 1.0 - (aPos.y - uCrop.y) / uCrop.w * 2.0, 0.0, 1.0); }"));
        gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, "precision mediump float; uniform sampler2D uTex; varying vec2 vUv; void main(){ gl_FragColor = texture2D(uTex, vUv); }"));
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
        gl.useProgram(prog);
        const tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.src);
        [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T].forEach(p => gl.texParameteri(gl.TEXTURE_2D, p, gl.CLAMP_TO_EDGE));
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        const W = this.src.width, H = this.src.height, n = this.base.length;
        const buf = (data, kind) => { const b = gl.createBuffer(); gl.bindBuffer(kind || gl.ARRAY_BUFFER, b); gl.bufferData(kind || gl.ARRAY_BUFFER, data, gl.STATIC_DRAW); return b; };
        const uv = new Float32Array(2 * n); this.base.forEach((q, i) => { uv[2 * i] = q[0] / W; uv[2 * i + 1] = q[1] / H; });
        const g = { gl, glc, prog, aPos: gl.getAttribLocation(prog, "aPos"), aUv: gl.getAttribLocation(prog, "aUv"), uCrop: gl.getUniformLocation(prog, "uCrop"),
          pos: gl.createBuffer(), uv: buf(uv), posArr: new Float32Array(2 * n),
          inner: buf(new Uint16Array(this.inner.flat()), gl.ELEMENT_ARRAY_BUFFER), nInner: this.inner.length * 3,
          mesh: buf(new Uint16Array(this.mesh.flat()), gl.ELEMENT_ARRAY_BUFFER), nMesh: this.mesh.length * 3,
          qpos: buf(new Float32Array([0, 0, W, 0, 0, H, W, H])), quv: buf(new Float32Array([0, 0, 1, 0, 0, 1, 1, 1])) };
        gl.uniform1i(gl.getUniformLocation(prog, "uTex"), 0);
        gl.uniform4f(g.uCrop, this.crop.x, this.crop.y, this.crop.w, this.crop.h);
        gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        return g;
      } catch (e) { return null; }
    }
    // Full body: a background triangle (touching the hair, the lattice or the frame) that turns over in a big head move is
    // not drawn — the photo beneath shows instead of a streak of stretched texture
    _flips(pts) {
      if (!this.body) return null;
      const nF = this.nFace, out = new Set();
      this.mesh.forEach((t, j) => {
        if (t[0] < nF && t[1] < nF && t[2] < nF) return;
        const a = (pts[t[1]][0] - pts[t[0]][0]) * (pts[t[2]][1] - pts[t[0]][1]) - (pts[t[2]][0] - pts[t[0]][0]) * (pts[t[1]][1] - pts[t[0]][1]);
        if (Math.sign(a) !== this.meshSign[j]) out.add(j);
      });
      return out.size ? out : null;
    }
    _glPass(layer, pts) {
      const g = this.gl, gl = g.gl;
      gl.viewport(0, 0, g.glc.width, g.glc.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      const attr = (loc, b) => { gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0); };
      if (layer === "back") {                                 // the untouched portrait, then its own mouth (moved)
        attr(g.aPos, g.qpos); attr(g.aUv, g.quv); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
      for (let i = 0; i < pts.length; i++) { g.posArr[2 * i] = pts[i][0]; g.posArr[2 * i + 1] = pts[i][1]; }
      gl.bindBuffer(gl.ARRAY_BUFFER, g.pos); gl.bufferData(gl.ARRAY_BUFFER, g.posArr, gl.DYNAMIC_DRAW);
      attr(g.aPos, g.pos); attr(g.aUv, g.uv);
      let ib = layer === "back" ? g.inner : g.mesh, nb = layer === "back" ? g.nInner : g.nMesh;
      if (layer !== "back") {
        const skip = this._flips(pts);
        if (skip || g.filtered) {                        // upload the triangles without the flipped ones (or restore all)
          const keep = skip ? this.mesh.filter((t, j) => !skip.has(j)) : this.mesh;
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, g.mesh); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(keep.flat()), gl.DYNAMIC_DRAW);
          g.filtered = !!skip; nb = keep.length * 3;
        }
      }
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.drawElements(gl.TRIANGLES, nb, gl.UNSIGNED_SHORT, 0);
      return g.glc;
    }
    _draw() {
      if (!this.ctx) return;
      if (this.gl) return this._drawGL();
      const pts = this._points(), c = this.ctx, cr = this.view || this.crop, k = this.cv.width / cr.w, src = this.src, B = this.base, F = this.F;
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
      const skip = this._flips(pts);
      this.mesh.forEach((tr, j) => { if (!skip || !skip.has(j)) warp(tr); });
      if (vis > 0.01) this._mouthInside(c, pts, open, extra, vis, true);     // final pass: a smooth, feathered edge (no facets)
      this._wrinkles(c, pts);
      this._lids(c, pts);
      this._turnOverlay(c);
    }
    _drawGL() {
      const pts = this._points(), c = this.ctx, cr = this.view || this.crop, k = this.cv.width / cr.w, B = this.base, F = this.F;
      const vw = this.view || this.crop; this.gl.gl.uniform4f(this.gl.uCrop, vw.x, vw.y, vw.w, vw.h);
      const crop = () => c.setTransform(k, 0, 0, k, -cr.x * k, -cr.y * k), px = () => c.setTransform(1, 0, 0, 1, 0, 0);
      px(); c.clearRect(0, 0, this.cv.width, this.cv.height);
      c.drawImage(this._glPass("back", pts), 0, 0);
      const gap = (q, i, j) => Math.hypot(q[i][0] - q[j][0], q[i][1] - q[j][1]);
      const open = gap(pts, 13, 14), extra = open - gap(B, 13, 14), vis = smooth(0.002 * F, 0.01 * F, extra);
      crop();
      if (vis > 0.01) this._mouthInside(c, pts, open, extra, vis);
      px(); c.drawImage(this._glPass("face", pts), 0, 0);
      crop();
      if (vis > 0.01) this._mouthInside(c, pts, open, extra, vis, true);
      this._wrinkles(c, pts);
      this._lids(c, pts);
      this._turnOverlay(c);
    }
    // A blink that really closes: on small or stylised eyes the moving lid alone can leave the iris showing through a
    // smeared strip of lashes. As the lid comes down, the opening (from where the upper lid would be at rest down to the
    // lower lid) is covered with this face's own lid skin, shaded towards the fold, with a soft lash line on the closing lid.
    _lids(c, pts) {
      const pal = this.palette, D = this.D;
      for (const [side, E] of [["Left", EYE.L], ["Right", EYE.R]]) {
        const k = IDX["eyeBlink" + side], w = this.cur[k] * this.gain[k] * this.calGain[k];
        const a = smooth(0.3, 0.75, this.cur[k]);                         // the blink itself decides closure, whatever the lid's tuning
        if (a < 0.02) continue;
        const rest = E.up.map(i => [pts[i][0] - w * D[k][3 * i], pts[i][1] - w * D[k][3 * i + 1]]);
        const lo = E.lo.map(i => pts[i]), oc = pts[E.outer], ic = pts[E.inner];
        const top = Math.min(...rest.map(q => q[1])), bot = Math.max(...lo.map(q => q[1]));
        const own = pal["lid" + side] || pal.skin, lid = own, fold = own.map(v => Math.round(v * 0.78));
        const g = c.createLinearGradient(0, top, 0, bot);
        g.addColorStop(0, "rgba(" + lid + "," + a + ")"); g.addColorStop(0.8, "rgba(" + lid + "," + a + ")"); g.addColorStop(1, "rgba(" + fold + "," + a + ")");
        c.save(); c.beginPath(); c.moveTo(oc[0], oc[1]);
        // the eye list runs outer → inner on both lids
        rest.forEach(q => c.lineTo(q[0], q[1])); c.lineTo(ic[0], ic[1]);
        lo.slice().reverse().forEach(q => c.lineTo(q[0], q[1])); c.closePath();
        const lw = Math.max(0.6, 0.012 * this.F);
        c.fillStyle = g; c.filter = "blur(" + (0.35 * lw * (this.cv.width / (this.view || this.crop).w)).toFixed(2) + "px)"; c.fill(); c.filter = "none";
        const ln = E.up.map(i => pts[i]);
        c.beginPath(); c.moveTo(oc[0], oc[1]); ln.forEach(q => c.lineTo(q[0], q[1] + lw * 0.3)); c.lineTo(ic[0], ic[1]);
        c.strokeStyle = "rgba(" + own.map(v => Math.round(v * 0.3)) + "," + (0.7 * a) + ")"; c.lineWidth = 1.4 * lw; c.lineCap = "round"; c.stroke();
        c.restore();
      }
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
        c.save(); c.lineCap = "round";                    // a soft fold: a wide faint stroke under a narrow one (no blur filter: fast)
        c.globalAlpha = Math.min(0.12, a * 0.4); c.strokeStyle = rgb(pal.crease, 1); c.lineWidth = w * 2.4; path(0); c.stroke();
        c.globalAlpha = Math.min(0.24, a * 0.8); c.lineWidth = w; path(0); c.stroke();
        c.globalAlpha = Math.min(0.18, a * 0.6); c.strokeStyle = rgb(pal.sheen, 1); c.lineWidth = w * 0.8; path(-w * 0.9); c.stroke();
        c.restore();
      };
      const P = i => pts[i], lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], w = Math.max(0.8, F * 0.0035);
      // forehead: three arcs across the brows, rising with them
      const up = Math.max(G("browInnerUp"), (G("browOuterUpLeft") + G("browOuterUpRight")) / 2);
      const browArc = [70, 63, 105, 66, 107, 336, 296, 334, 293, 300].map(P);
      [0.06, 0.1].forEach((h, k) => fold(browArc.map(q => [q[0], q[1] - h * F]).slice(2 + k, browArc.length - 2 - k), 0.11 * up * (1 - 0.3 * k), w * 0.9));
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
    //    the lip above and darker toward the corners; at most ~5 mm and a third of the opening; coloured from the sclera;
    //  * the tongue rests low and is attached to the floor of the mouth (it rises for th/l, never floats);
    //  * gums are never shown in speech; lower teeth only as a faint edge in a wide opening.
    // How much upper tooth shows below the lip: a third of the opening and ~3 mm for a neutral speaker; the full-body
    // calibration's speaking smile shows more (as the reference speaker does), up to half the opening
    _teethLen(open) {
      return this.body ? Math.min(open * BODY_CAL.teeth_frac, BODY_CAL.teeth_mm * this.fit.pxmm) : Math.min(open * 0.33, this.fit.teeth_mm * this.fit.pxmm);
    }
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
      // tongue: the body of the tongue fills the floor of the mouth behind the lower teeth. In a narrow opening only its
      // dark back shows; as the jaw opens wide its top surface comes into view — a domed, moist, pink-red surface, lit at
      // the tip and falling away into shadow at the sides and the back, with the faint groove down its middle. It lifts
      // toward the upper teeth for th / l / t / n. Never as light as the lips (the guardrail's "flesh in the opening").
      const tng = this.cur[IDX.tongueOut], lowC = loY(mx);
      if (open > F * 0.012) {
        const wide = smooth2(0.022 * F, 0.06 * F, open);                      // how much of the top surface is in view
        const rise = open * (0.12 + 0.14 * wide + 0.45 * tng), half = tw * (0.36 + 0.06 * wide);   // low in the mouth, under the lower lip's edge
        const topY = lowC - rise, baseY = lowC + open * 0.2;
        const body = () => { c.beginPath(); c.moveTo(mx - half, baseY);
          c.bezierCurveTo(mx - half, lowC - rise * 0.55, mx - half * 0.55, topY, mx, topY);
          c.bezierCurveTo(mx + half * 0.55, topY, mx + half, lowC - rise * 0.55, mx + half, baseY); c.closePath(); };
        const tg = c.createRadialGradient(mx, topY + rise * 0.25, 0, mx, topY + rise * 0.4, half * 1.1);
        tg.addColorStop(0, rgb(wide > 0.05 ? pal.tongueHi : pal.tongue)); tg.addColorStop(0.55, rgb(pal.tongue)); tg.addColorStop(1, rgb(pal.cavDeep));
        c.fillStyle = tg; body(); c.fill();
        if (wide > 0.05) {
          // the median groove, and the moist sheen on the front of the tongue
          c.strokeStyle = rgb(pal.cavDeep, 0.28 * wide); c.lineWidth = Math.max(0.6, tw * 0.012);
          c.beginPath(); c.moveTo(mx, topY + rise * 0.12); c.quadraticCurveTo(mx + tw * 0.005, topY + rise * 0.45, mx, topY + rise * 0.8); c.stroke();
          c.fillStyle = rgb(pal.tongueHi, 0.35 * wide); c.beginPath();
          c.ellipse(mx - half * 0.18, topY + rise * 0.2, half * 0.16, Math.max(0.6, rise * 0.07), -0.15, 0, 2 * Math.PI); c.fill();
          // shadow where the tongue meets the lower teeth and the cheeks
          const ts = c.createLinearGradient(0, topY, 0, lowC);
          ts.addColorStop(0, rgb(pal.cavDeep, 0)); ts.addColorStop(1, rgb(pal.cavDeep, 0.35));
          c.fillStyle = ts; body(); c.fill();
        }
      }
      // upper front teeth, hanging from the upper lip's curve
      const th = this._teethLen(open) * smooth2(0.01 * F, 0.03 * F, extra);
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
        // each tooth's own form: the enamel catches the light down its middle (never brighter than the row's own colour),
        // the biting edge is a little greyer and translucent, the gaps between teeth darken toward the biting edge and
        // open into small V-shaped notches there; the canines at the ends sit back in shadow
        c.save(); c.clip();
        teethL.forEach((t, n) => { const yy = upY(t.cx) - 1, L = lenAt(t.cx);
          const hi = c.createLinearGradient(t.x, 0, t.x + t.w, 0), a = n === 2 || n === 3 ? 0.55 : 0.3;
          hi.addColorStop(0, rgb(tc, 0)); hi.addColorStop(0.42, rgb(tc, a)); hi.addColorStop(0.6, rgb(tc, a * 0.6)); hi.addColorStop(1, rgb(tc, 0));
          c.fillStyle = hi; c.fillRect(t.x, yy + L * 0.12, t.w, L * 0.7);
          const edge = c.createLinearGradient(0, yy + L * 0.72, 0, yy + L);
          edge.addColorStop(0, rgb(pal.cavEdge, 0)); edge.addColorStop(1, rgb(pal.cavEdge, 0.22));
          c.fillStyle = edge; c.fillRect(t.x, yy + L * 0.72, t.w, L * 0.3); });
        c.restore();
        teethL.slice(1).forEach(t => { const yy = upY(t.x), L = lenAt(t.x);
          const sep = c.createLinearGradient(0, yy, 0, yy + L);
          sep.addColorStop(0, rgb(pal.cavDeep, 0.1)); sep.addColorStop(1, rgb(pal.cavDeep, 0.38));
          c.strokeStyle = sep; c.lineWidth = Math.max(0.5, span * 0.006);
          c.beginPath(); c.moveTo(t.x, yy); c.lineTo(t.x, yy + L * 0.92); c.stroke();
          const v = Math.min(t.w * 0.18, L * 0.22);                  // the notch between two biting edges
          c.fillStyle = rgb(pal.cavDeep, 0.6); c.beginPath();
          c.moveTo(t.x - v, yy + L + 0.5); c.lineTo(t.x, yy + L - v * 1.4); c.lineTo(t.x + v, yy + L + 0.5); c.closePath(); c.fill(); });
        // lower front teeth: a smaller row rising from behind the lower lip, only as the jaw opens wide (as in real
        // speech, where the lower incisors show on open vowels); shaded, never brighter than the upper row
        // (revised: a flat light row along the lower lip read as a straight, swollen lower lip — the lower incisors now show
        // only on a wide-open vowel, small, in shadow, and their edge follows the lip's own curve)
        const lt = Math.min(th * 0.45, open * (this.body ? BODY_CAL.lower_teeth : 0.1)) * smooth(0.05 * F, 0.085 * F, extra);
        if (lt > 0.8) {
          const lspan = span * 0.5, lx0 = mx - lspan / 2, N2 = 24;
          c.beginPath(); c.moveTo(lx0, loY(lx0) + 1);
          for (let q = 0; q <= N2; q++) { const xx = lx0 + lspan * q / N2, u = Math.abs(xx - mx) / (lspan / 2); c.lineTo(xx, loY(xx) + 1 - lt * (1 - 0.35 * u * u)); }
          c.lineTo(lx0 + lspan, loY(lx0 + lspan) + 1); c.closePath();
          const lg2 = c.createLinearGradient(0, lowC - lt, 0, lowC);
          lg2.addColorStop(0, rgb(pal.teeth.map(v => Math.round(v * 0.72)))); lg2.addColorStop(1, rgb(pal.teeth.map(v => Math.round(v * 0.45))));
          c.fillStyle = lg2; c.fill();
          const sd2 = c.createLinearGradient(lx0, 0, lx0 + lspan, 0);
          sd2.addColorStop(0, rgb(pal.cavDeep, 0.6)); sd2.addColorStop(0.3, rgb(pal.cavDeep, 0)); sd2.addColorStop(0.7, rgb(pal.cavDeep, 0)); sd2.addColorStop(1, rgb(pal.cavDeep, 0.6));
          c.fillStyle = sd2; c.fill();
          c.strokeStyle = rgb(pal.cavDeep, 0.3); c.lineWidth = Math.max(0.4, lspan * 0.006);
          for (let q = 1; q < 4; q++) { const xx = lx0 + lspan * q / 4, yy = loY(xx) + 1, u = Math.abs(xx - mx) / (lspan / 2);
            c.beginPath(); c.moveTo(xx, yy); c.lineTo(xx, yy - lt * (1 - 0.35 * u * u) * 0.9); c.stroke(); }
        }
      }
      // shadows: the corners go dark, the upper lip shades what is under it
      const sh = c.createLinearGradient(mx - tw / 2, 0, mx + tw / 2, 0);
      sh.addColorStop(0, rgb(pal.cavDeep, 0.95)); sh.addColorStop(0.2, rgb(pal.cavDeep, 0)); sh.addColorStop(0.8, rgb(pal.cavDeep, 0)); sh.addColorStop(1, rgb(pal.cavDeep, 0.95));
      c.fillStyle = sh; c.fillRect(mx - tw, top, tw * 2, h);
      const us = c.createLinearGradient(0, pts[13][1] - 1, 0, pts[13][1] + Math.max(2, open * 0.22));
      us.addColorStop(0, rgb(pal.cavDeep, 0.3)); us.addColorStop(1, rgb(pal.cavDeep, 0));
      c.fillStyle = us; c.fillRect(mx - tw, pts[13][1] - 2, tw * 2, Math.max(3, open * 0.3));
      // the lower lip's inner edge: a soft shadow just inside it, following its curve, so the edge reads as the lip's own
      // rounded rim (never a straight line at the tooth line)
      c.strokeStyle = rgb(pal.cavDeep, 0.55); c.lineWidth = Math.max(1.5, open * 0.22); c.lineJoin = "round";
      c.beginPath(); IN_LO.forEach((i, j) => j ? c.lineTo(pts[i][0], pts[i][1]) : c.moveTo(pts[i][0], pts[i][1])); c.stroke();
      c.restore();
      // soft inner lip edge: the lips round into the mouth, there is no cut line
      c.save(); c.globalAlpha = 0.35 * vis;                   // soft inner lip edge (a wide faint stroke; no blur filter: fast)
      c.strokeStyle = rgb(pal.cavEdge); c.lineWidth = Math.max(1.5, F * 0.005);
      outline(); c.stroke();
      c.restore();
    }
    // Delivery check: replays a delivery exactly as it plays (same animation state, frame by frame) and measures, in the
    // portrait's own pixels, everything that must not happen. Returns time spans with the worst value, the limit, why it
    // matters and the region (a box in portrait pixels), plus the per-frame series for the timeline. Deterministic.
    //   background   anything outside her silhouette moves
    //   region       the forehead, hair or head region moves beyond what the head's own turn explains
    //   hair         the hair separates from the head
    //   jump         a sudden jump of the head between frames
    //   lips         a flat, straight lower lip edge; swollen lips; an exaggerated pucker or spread
    //   fold         part of the face turned over (smears)
    _checkCtx() {
      if (this._cctx) return this._cctx;
      const F = this.F, B = this.base3, nF = this.nFace, pf = this.pfield;
      const tri = this.mesh.filter(t => t.every(i => i < this.base.length)), probes = [];
      const bary = (q, a, b, c) => { const d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]); if (Math.abs(d) < 1e-9) return null;
        const l1 = ((b[1] - c[1]) * (q[0] - c[0]) + (c[0] - b[0]) * (q[1] - c[1])) / d, l2 = ((c[1] - a[1]) * (q[0] - c[0]) + (a[0] - c[0]) * (q[1] - c[1])) / d;
        return [l1, l2, 1 - l1 - l2]; };
      const cr = this.crop, step = Math.max(4, 0.12 * F);
      const isBg = (x, y) => pf ? (this.pwide || pf).soft(x, y) < 0.02 : Math.hypot((x - this.fc[0]) / (0.9 * (this.bodyShape ? this.bodyShape.fw : F * 0.8)), (y - this.fc[1]) / F) > 1.6;
      for (let y = cr.y + step / 2; y < cr.y + cr.h; y += step) for (let x = cr.x + step / 2; x < cr.x + cr.w; x += step) {
        if (!isBg(x, y)) continue;
        for (const t of tri) { const w = bary([x, y], this.base[t[0]], this.base[t[1]], this.base[t[2]]); if (w && w[0] >= -1e-6 && w[1] >= -1e-6 && w[2] >= -1e-6) { probes.push({ x, y, t, w }); break; } }
      }
      const top = B[10][1], eyeY = (B[159][1] + B[386][1]) / 2, hair = [], region = [];
      for (let i = nF; i < B.length; i++) { const [x, y] = B[i]; if (this.fixed.has(i)) continue;
        if (y < top && Math.abs(x - this.fc[0]) < 0.6 * F && (!pf || pf.soft(x, y) > 0.9)) hair.push(i);
        if (y < eyeY && (!pf || pf.soft(x, y) > 0.5)) region.push(i); }
      const area = (P, t) => (P[t[1]][0] - P[t[0]][0]) * (P[t[2]][1] - P[t[0]][1]) - (P[t[2]][0] - P[t[0]][0]) * (P[t[1]][1] - P[t[0]][1]);
      const faceTris = this.mesh.filter(t => t[0] < nF && t[1] < nF && t[2] < nF);
      const sag = (Q, i) => { const a = Q[78], c = Q[308], u = (Q[i][0] - a[0]) / ((c[0] - a[0]) || 1); return Q[i][1] - (a[1] + u * (c[1] - a[1])); };
      const lipg = Q => ({ up: sag(Q, 13), lo: sag(Q, 14), loT: Q[17][1] - Q[14][1], upT: Q[13][1] - Q[0][1], w: Math.hypot(Q[291][0] - Q[61][0], Q[291][1] - Q[61][1]) });
      // tear probes: the triangles outside the face that touch a moving point and a pinned one (her edge, her hair's edge):
      // their sides must not stretch or squeeze beyond what reads as natural
      const nonFace = this.mesh.filter(t => t.some(i => i >= nF) && t.some(i => !this.fixed.has(i) && i >= nF) && t.some(i => this.fixed.has(i)));
      const len = (P, a, b) => Math.hypot(P[a][0] - P[b][0], P[a][1] - P[b][1]);
      return this._cctx = { probes, hair, region, area, faceTris, a0: faceTris.map(t => area(B, t)), lipg, L0: lipg(B.map(q => [q[0], q[1]])), edgeTris: nonFace, len,
        // (background: a couple of pixels in the fade beside her edge cannot be seen; the defect it catches was 0.2 face heights)
        LIM: { background: 0.02, region: 0.012, hair: 0.025, jump: 0.03, flat: 0.35, swell: 0.12, pucker: -0.24, spread: 0.18, tear: 0.35 } };
    }
    // every measurement of one moment: P as delivered, R the same moment with no expression (the rigid head and body);
    // `box` (portrait pixels) limits the measurement to a region; returns values and the offending points of each kind
    _measure(P, R, box, prevTop, fpsK) {
      const C = this._checkCtx(), F = this.F, Wm = this.Wm, B = this.base3, LIM = C.LIM;
      const inBox = (x, y) => !box || (x >= box[0] && y >= box[1] && x <= box[0] + box[2] && y <= box[1] + box[3]);
      const m = { pts: {} };
      let bg = 0; m.pts.background = [];
      for (const pr of C.probes) { if (!inBox(pr.x, pr.y)) continue; const [a, b, c] = pr.t;
        const dx = pr.w[0] * (P[a][0] - B[a][0]) + pr.w[1] * (P[b][0] - B[b][0]) + pr.w[2] * (P[c][0] - B[c][0]),
          dy = pr.w[0] * (P[a][1] - B[a][1]) + pr.w[1] * (P[b][1] - B[b][1]) + pr.w[2] * (P[c][1] - B[c][1]), d = Math.hypot(dx, dy) / F;
        if (d > bg) bg = d; if (d > LIM.background) m.pts.background.push([pr.x, pr.y]); }
      m.background = bg;
      let rg = 0; m.pts.region = [];
      for (const i of C.region.concat([10, 151, 109, 338, 67, 297])) { if (!inBox(B[i][0], B[i][1])) continue; const d = Math.hypot(P[i][0] - R[i][0], P[i][1] - R[i][1]) / F;
        if (d > rg) rg = d; if (d > LIM.region) m.pts.region.push(B[i]); }
      m.region = rg;
      // hair against the head: the top of the forehead gives the head's own movement (shift, turn, scale) — the hair must
      // follow it; a hair point that goes its own way is the hair separating from the head
      const O2 = [10, 109, 338, 67, 297, 103, 332, 151]; let ax = 0, ay = 0, bx = 0, by = 0;
      O2.forEach(i => { ax += B[i][0]; ay += B[i][1]; bx += P[i][0]; by += P[i][1]; }); ax /= O2.length; ay /= O2.length; bx /= O2.length; by /= O2.length;
      let sxx = 0, sxy = 0, n2 = 0; O2.forEach(i => { const x = B[i][0] - ax, y = B[i][1] - ay, u = P[i][0] - bx, v = P[i][1] - by; sxx += x * u + y * v; sxy += x * v - y * u; n2 += x * x + y * y; });
      const sa = sxx / n2, sb = sxy / n2;
      let hr = 0; m.pts.hair = [];
      for (const i of C.hair) { if (!inBox(B[i][0], B[i][1])) continue; const x = B[i][0] - ax, y = B[i][1] - ay, qx = bx + sa * x - sb * y, qy = by + sb * x + sa * y;
        const d = Math.hypot(P[i][0] - qx, P[i][1] - qy) / F; if (d > hr) hr = d; if (d > LIM.hair) m.pts.hair.push(B[i]); }
      m.hair = hr;
      m.jump = prevTop ? Math.hypot(P[10][0] - prevTop[0], P[10][1] - prevTop[1]) / F * (fpsK || 1) : 0;
      const g = C.lipg(P), L0 = C.L0, open = (g.lo - g.up) - (L0.lo - L0.up), dUp = -(g.up - L0.up), dLo = g.lo - L0.lo;
      const mouthIn = inBox(B[13][0], B[13][1]);
      // (thinner lips are natural when they press together for p, b, m — only swelling counts)
      // (only real openings: on ee, s, f the upper lip rightly makes most of a small opening while the lower stays by the teeth)
      m.lowerShare = mouthIn && open > 0.1 * Wm ? dLo / Math.max(1e-6, dUp + dLo) : null;
      m.thick = mouthIn ? Math.max(g.loT / L0.loT - 1, g.upT / L0.upT - 1) : 0;
      m.width = mouthIn ? g.w / L0.w - 1 : 0;
      // tearing near her edge: the most any side of an edge triangle stretched or squeezed (0.35 = 35%)
      let tr = 0; m.pts.tear = [];
      for (const t of C.edgeTris) { if (!inBox(B[t[0]][0], B[t[0]][1])) continue;
        for (const [a, b] of [[t[0], t[1]], [t[1], t[2]], [t[2], t[0]]]) { const l0 = C.len(B, a, b); if (l0 < 0.08 * F || B[a][1] < 0 || B[b][1] < 0) continue;   // visible sides only
          const d = Math.abs(C.len(P, a, b) / l0 - 1); if (d > tr) tr = d; if (d > C.LIM.tear) m.pts.tear.push(B[a], B[b]); } }
      m.tear = tr;
      // (slivers smaller than ~2% of the face on a side — a few pixels along the face's edge — flip on a nod without a visible mark)
      m.folds = 0; m.pts.fold = []; m.foldIds = [];
      C.faceTris.forEach((t, j) => { const ar = C.area(P, t), a0 = C.a0[j];
        if (Math.sign(ar) !== Math.sign(a0) && Math.abs(a0) > 0.0004 * F * F && Math.abs(ar) > 0.1 * Math.abs(a0) && inBox(B[t[0]][0], B[t[0]][1])) {
          m.folds++; m.pts.fold.push(B[t[0]], B[t[1]], B[t[2]]); m.foldIds.push(t.join("-")); } });
      return m;
    }
    // how bad one moment is for one complaint (0 = fine; >1 = over the limit) — what the learning loop minimises
    badness(m, kind) {
      const L = this._checkCtx().LIM;
      if (kind === "background") return m.background / L.background;
      if (kind === "region") return Math.max(m.region / L.region, m.jump / L.jump);
      if (kind === "hair") return m.hair / L.hair;
      if (kind === "lips") return Math.max(m.lowerShare === null ? 0 : (0.6 - m.lowerShare) / (0.6 - L.flat), m.thick / L.swell, m.width / L.pucker, m.width / L.spread);
      if (kind === "fold") return Math.max(m.folds, m.tear / L.tear);
      return 0;
    }
    // one stored moment (a flag): the same measurements, restricted to its box
    measureState(state, box) {
      const save = { cur: this.cur, head: this.head, t: this.t };
      this.cur = Float32Array.from(state.chan); this.head = state.head.slice(); this.t = state.t;
      const P = this._points(), R = this._points(new Float32Array(BS.length));
      Object.assign(this, save);
      const m = this._measure(P, R, box, null);
      delete m.pts; return m;
    }
    // a fixed head-and-shoulders view (measuring and side-by-side comparison: the face large enough to read the lips)
    closeUp(on) {
      if (!on) { this.fixedView = null; return; }
      const F = this.F, w = Math.min(this.src.width, 3.2 * F), h = Math.min(this.src.height, w * this.cv.height / this.cv.width);
      this.fixedView = { x: Math.max(0, Math.min(this.src.width - w, this.fc[0] - w / 2)), y: Math.max(0, Math.min(this.src.height - h, this.fc[1] - 0.42 * h)), w, h };
    }
    // screen ↔ portrait: a point on the shown picture (canvas pixels) and the same point in the portrait, for flag boxes
    toPortrait(cx, cy) { const cr = this.view || this.crop, k = this.cv.width / cr.w; return [cr.x + cx / k, cr.y + cy / k]; }
    toCanvas(x, y) { const cr = this.view || this.crop, k = this.cv.width / cr.w; return [(x - cr.x) * k, (y - cr.y) * k]; }
    // the exact moment being shown (for a flag): channels, head pose and time
    state() { return { chan: Array.from(this.cur, v => +v.toFixed(4)), head: this.head.map(v => +v.toFixed(3)), t: this.t, body: !!this.body }; }
    deliveryCheck(track, opts) {
      opts = opts || {};
      const fps = opts.fps || 24, F = this.F, B = this.base3, C = this._checkCtx(), LIM = C.LIM;
      const dur = opts.duration || (track && track.motion && track.motion.frames.length ? track.motion.frames.length / track.motion.fps : (track && track.duration) || 0);
      const save = { cur: Float32Array.from(this.cur), head: this.head.slice(), t: this.t, tPrev: this.tPrev, view: this.view, turning: this.turning, moveQueue: this.moveQueue };
      this.cur = new Float32Array(BS.length); this.head = [0, 0, 0]; this.t = null; this.tPrev = undefined; this.turning = null; this.moveQueue = [];
      const zero = new Float32Array(BS.length), KINDS = ["background", "region", "hair", "jump", "lowerShare", "thick", "width", "folds", "tear"];
      const series = { t: [] }; KINDS.forEach(k => { series[k] = []; });
      const hits = [], hit = (kind, i, value, box, why) => hits.push({ kind, i, value, box, why });
      const bbox = pts => { if (!pts.length) return null; let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        pts.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); });
        const mg = 0.15 * F; return [Math.round(x0 - mg), Math.round(y0 - mg), Math.round(x1 - x0 + 2 * mg), Math.round(y1 - y0 + 2 * mg)]; };
      const region_of = id => { const v = id.split("-").map(Number), near = set => v.some(i => set.includes(i));
        return near([33, 133, 159, 145, 362, 263, 386, 374, 468, 473, 380, 373, 390, 144, 153, 160, 158, 385, 387]) ? "the eyes" :
          near([61, 291, 0, 17, 13, 14, 78, 308, 37, 267, 84, 314]) ? "the mouth" : near([234, 454, 127, 356, 93, 323, 132, 361, 227, 447, 116, 345]) ? "the cheekbones" :
          near([70, 63, 105, 66, 107, 300, 293, 334, 296, 336, 10, 151, 109, 338]) ? "the brows / forehead" : near([152, 148, 377, 176, 400, 149, 378]) ? "the chin" : "the face"; };
      const mouthBox = bbox([B[61], B[291], B[0], B[17]]), headBox = bbox([B[10], B[152], B[234], B[454]]);
      let prevTop = null;
      const n = Math.max(1, Math.floor(dur * fps));
      for (let k = 0; k < n; k++) {
        const t = k / fps;
        this._advance(track, t);
        series.t.push(+t.toFixed(3));
        if (this._turnNow() !== null) { KINDS.forEach(k2 => series[k2].push(null)); prevTop = null; continue; }   // a recorded move plays its own video
        const P = this._points(), R = this._points(zero), m = this._measure(P, R, null, prevTop, 24 / fps);
        prevTop = P[10];
        KINDS.forEach(k2 => series[k2].push(m[k2] === null ? null : +(+m[k2]).toFixed(4)));
        if (m.background > LIM.background) hit("background", k, m.background, bbox(m.pts.background), "the background moves");
        if (m.region > LIM.region) hit("region", k, m.region, bbox(m.pts.region), "the forehead / head region moves without the head turning");
        if (m.hair > LIM.hair) hit("hair", k, m.hair, bbox(m.pts.hair.concat([B[10]])), "the hair separates from the head");
        if (m.jump > LIM.jump) hit("jump", k, m.jump, headBox, "the head jumps between frames");
        if (m.lowerShare !== null && m.lowerShare < LIM.flat) hit("lips", k, m.lowerShare, mouthBox, "the lower lip's edge stays straight while the upper lip curves");
        if (m.thick > LIM.swell) hit("lips", k, m.thick, mouthBox, "the lips swell (thicker by more than " + Math.round(LIM.swell * 100) + "%)");
        if (m.width < LIM.pucker) hit("lips", k, m.width, mouthBox, "exaggerated pucker (the mouth narrows by more than " + Math.round(-LIM.pucker * 100) + "%)");
        if (m.width > LIM.spread) hit("lips", k, m.width, mouthBox, "exaggerated spread (the mouth widens by more than " + Math.round(LIM.spread * 100) + "%)");
        if (m.folds) hit("fold", k, m.folds, bbox(m.pts.fold), "part of the face folds over (smears) near " + region_of(m.foldIds[0]));
        if (m.tear > LIM.tear) hit("tear", k, m.tear, bbox(m.pts.tear), "the picture tears or shears near her edge (hair, shoulders)");
      }
      // consecutive frames of one kind and reason become one span; its box covers the whole span
      const spans = [];
      hits.sort((a, b) => a.kind.localeCompare(b.kind) || a.why.localeCompare(b.why) || a.i - b.i).forEach(h => {
        const last = spans[spans.length - 1], low = h.why.startsWith("the lower") || h.why.startsWith("exaggerated pucker");
        if (last && last.kind === h.kind && last.why === h.why && h.i - last.i1 <= 2) {
          last.i1 = h.i; last.worst = low ? Math.min(last.worst, h.value) : Math.max(last.worst, h.value);
          if (h.box) { const b = last.box || h.box, x0 = Math.min(b[0], h.box[0]), y0 = Math.min(b[1], h.box[1]);
            last.box = [x0, y0, Math.max(b[0] + b[2], h.box[0] + h.box[2]) - x0, Math.max(b[1] + b[3], h.box[1] + h.box[3]) - y0]; }
        } else spans.push({ kind: h.kind, why: h.why, i0: h.i, i1: h.i, worst: h.value, box: h.box });
      });
      spans.forEach(sp => { sp.t0 = +(sp.i0 / fps).toFixed(2); sp.t1 = +((sp.i1 + 1) / fps).toFixed(2); sp.limit = sp.kind === "lips" || sp.kind === "fold" ? null : LIM[sp.kind];
        sp.worst = +sp.worst.toFixed(4); delete sp.i0; delete sp.i1; });
      spans.sort((a, b) => a.t0 - b.t0);
      Object.assign(this, save); this._draw();
      const secs = spans.reduce((a, s2) => a + (s2.t1 - s2.t0), 0);
      return { fps, frames: n, duration: +dur.toFixed(2), spans, series, limits: LIM, probes: C.probes.length, silhouette: !!this.pfield,
        score: Math.max(0, Math.round(100 * (1 - secs / Math.max(0.5, dur)))) };
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
      // human limits; width limits from a clearly articulating reference speaker (mouth 0.65–1.19 of its rest width)
      // (fuller lips are allowed on a pucker: lips pushed forward and turned out read ~25% thicker from the front)
      const lim = { upT: [0.86, 1.3], loT: [0.85, 1.32], upW: [0.6, 1.2], mW: [0.58, 1.25] };
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
      const teethMm = this._teethLen(open) / this.fit.pxmm;
      if (teethMm > (this.body ? BODY_CAL.teeth_mm + 0.2 : 5.2)) issues.push("too much tooth showing");
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
