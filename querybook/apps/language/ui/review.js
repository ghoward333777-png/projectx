// Delivery review (Speech → talking face, Avatar studio): check a delivery frame by frame, flag what looks wrong, compare
// with the person's own reference clips, reproduce a reference clip and compare it word by word, and learn from the flags.
// Everything is measured here in the browser with the same face tracker for the original and for our delivery;
// nothing changes the faces without the admin (the learning loop only proposes a calibration to the Quality Lab).
"use strict";
const RV = { reasons: null };
fetch("/api/status").then(r => r.json()).then(s => { window.QB_VERSION = s.version; }).catch(() => {});
const REF_KEYS = ["brow_inner_sd", "brow_outer_sd", "blinks_per_min", "yaw_range", "pitch_range", "roll_range", "gap_mean", "gap_p90", "smile_p50", "upper_lift"];
const REF_TEXT = { brow_inner_sd: "inner brows move", brow_outer_sd: "outer brows move", blinks_per_min: "blinks per minute", yaw_range: "head turns (left–right, °)",
  pitch_range: "head nods (°)", roll_range: "head tilts (°)", gap_mean: "mouth opening (average)", gap_p90: "mouth opening (wide moments)", smile_p50: "speaking smile",
  upper_lift: "upper lip's share of the opening" };
const KIND_COLOR = { background: "#d33", region: "#e67e22", hair: "#8e44ad", jump: "#c0392b", lips: "#2a7ae2", fold: "#16a085" };

async function rvReasons() {
  if (!RV.reasons) RV.reasons = (await api("/api/avatars/flags?id=-1")).reasons;
  return RV.reasons;
}

// the face tracker needs its frame times to keep increasing, across every measurement on the page
const rvTs = () => (RV.ts = Math.max((RV.ts || 0) + 1, Math.floor(performance.now())));
// a clip's sound as WAV (data URL): the browser decodes it; where it cannot (some codecs), ffmpeg on this computer does
async function rvWav(file) {
  try { return await agWav(file); }
  catch (e) { return (await api("/api/media/convert", { file_b64: await agB64(file), to: "wav" })).b64; }
}
// a clip the browser can play: as it is, or converted to WebM by ffmpeg on this computer
async function rvPlayable(file) {
  const ok = await new Promise(res => { const v = document.createElement("video"); v.muted = true; v.onloadeddata = () => res(true); v.onerror = () => res(false);
    v.src = URL.createObjectURL(file); setTimeout(() => res(false), 8000); });
  if (ok) return file;
  const r = await api("/api/media/convert", { file_b64: await agB64(file), to: "webm" });
  return await (await fetch(r.b64)).blob();
}
// ---------------------------------------------------------------- measuring with the face tracker (original clips and our deliveries alike)
function rvFrame(m, W, H) {
  const f = { t: m.t, face: !!m.face };
  if (!m.face) return f;
  f.gap = m.gap; f.pose = m.pose ? m.pose.slice(0, 3) : null;
  f.bs = {}; ["browInnerUp", "browOuterUpLeft", "browOuterUpRight", "eyeBlinkLeft", "eyeBlinkRight", "mouthSmileLeft", "mouthSmileRight", "jawOpen", "mouthPucker", "mouthFunnel"]
    .forEach(k => { f.bs[k] = (m.bs || {})[k] || 0; });
  const L = m._L, P = i => [L[i].x * W, L[i].y * H];
  if (L) {                                                  // the lips relative to the line between the inner corners (scale-free: ÷ mouth width)
    const a = P(78), c = P(308), mw = Math.hypot(P(61)[0] - P(291)[0], P(61)[1] - P(291)[1]) || 1;
    const line = q => { const u = (q[0] - a[0]) / ((c[0] - a[0]) || 1); return q[1] - (a[1] + u * (c[1] - a[1])); };
    f.mw = mw; f.up = -line(P(13)) / mw; f.lo = line(P(14)) / mw;
  }
  return f;
}
function rvStats(frames, fps) {
  const f = frames.filter(x => x.face);
  if (f.length < 12) return null;
  const pct = (a, p) => { a = a.slice().sort((x, y) => x - y); return a.length ? a[Math.min(a.length - 1, Math.floor(p * a.length))] : 0; };
  const mean = a => a.reduce((s, x) => s + x, 0) / Math.max(1, a.length), sd = a => { const m = mean(a); return Math.sqrt(mean(a.map(x => (x - m) ** 2))); };
  const bs = k => f.map(x => x.bs[k] || 0), av = (a, b) => bs(a).map((v, i) => (v + bs(b)[i]) / 2);
  const bl = bs("eyeBlinkLeft"); let blinks = 0; for (let i = 1; i < bl.length; i++) if (bl[i] > 0.5 && bl[i - 1] <= 0.5) blinks++;
  const pose = f.filter(x => x.pose).map(x => x.pose), pr = i => pose.length > 6 ? pct(pose.map(p => p[i]), 0.95) - pct(pose.map(p => p[i]), 0.05) : null;
  const gap = f.map(x => x.gap || 0), r = v => v === null ? null : +v.toFixed(4);
  // how much of an opening the upper lip makes (it lifts while the lower lip drops): middle of the lips against the corner line
  const op = f.filter(x => (x.gap || 0) > 0.12 && x.up !== undefined && x.lo + x.up > 0.02), lift = op.length >= 6 ? pct(op.map(x => Math.max(-0.5, Math.min(1.5, x.up / (x.up + x.lo)))), 0.5) : null;
  return { brow_inner_sd: r(sd(bs("browInnerUp"))), brow_outer_sd: r(sd(av("browOuterUpLeft", "browOuterUpRight"))), blinks_per_min: r(blinks / (frames.length / fps) * 60),
    yaw_range: r(pr(0)), pitch_range: r(pr(1)), roll_range: r(pr(2)), gap_mean: r(mean(gap)), gap_p90: r(pct(gap, 0.9)), smile_p50: r(pct(av("mouthSmileLeft", "mouthSmileRight"), 0.5)), upper_lift: r(lift) };
}
// an original clip (a video file): every 1/12 s through it, at most 60 s
async function rvMeasureVideo(file, note, maxS) {
  const v = document.createElement("video"); v.muted = true; v.playsInline = true; v.src = typeof file === "string" ? file : URL.createObjectURL(file);
  await new Promise((ok, bad) => { v.onloadeddata = ok; v.onerror = () => bad(new Error("this video cannot be played here")); });
  if (!isFinite(v.duration)) await new Promise(res => { v.ondurationchange = () => { if (isFinite(v.duration)) res(); }; v.currentTime = 1e9; setTimeout(res, 3000); });
  const fps = 12, dur = Math.min(v.duration || 0, maxS || 60), W = v.videoWidth, H = v.videoHeight;
  const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
  const seek = t => new Promise(r => { v.onseeked = r; v.currentTime = t; });
  const lm = await tracker(), frames = [];
  for (let t = 0; t < dur - 0.02; t += 1 / fps) {
    await seek(t); g.drawImage(v, 0, 0);
    const res = lm.detectForVideo(c, rvTs());
    frames.push(rvFrame(measureFrame(res, { videoWidth: W, videoHeight: H }, t), W, H));
    if (note && frames.length % 12 === 0) note("Reading the original: " + t.toFixed(0) + " of " + dur.toFixed(0) + " s");
  }
  return { frames, fps, duration: dur, video: v };
}
// our delivery of a track, on a face (DepthFace): the same frames the person sees, read by the same tracker
async function rvMeasureDelivery(impl, track, duration, note) {
  const lm = await tracker(), fps = 12, frames = [], save = { director: impl.director, t: impl.t, tPrev: impl.tPrev, cur: Float32Array.from(impl.cur), head: impl.head.slice() };
  impl.director = false; impl.t = null; impl.tPrev = undefined; impl.cur = new Float32Array(impl.cur.length); impl.head = [0, 0, 0];
  const keepView = impl.fixedView; if (impl.body && impl.closeUp) impl.closeUp(true);       // a full figure's face is too small to read: measure in close-up
  try {
    for (let t = 0; t < duration - 0.02; t += 1 / fps) {
      impl.frame(track, t);
      const res = lm.detectForVideo(impl.cv, rvTs());
      frames.push(rvFrame(measureFrame(res, { videoWidth: impl.cv.width, videoHeight: impl.cv.height }, t), impl.cv.width, impl.cv.height));
      if (note && frames.length % 12 === 0) { note("Reading our delivery: " + t.toFixed(0) + " of " + duration.toFixed(0) + " s"); await new Promise(r => setTimeout(r, 0)); }
    }
  } finally { Object.assign(impl, save); impl.fixedView = keepView; }
  return { frames, fps, duration };
}
function rvCompare(mine, ref) {
  return REF_KEYS.filter(k => ref && ref[k] !== undefined && ref[k] !== null && mine && mine[k] !== null && mine[k] !== undefined).map(k => {
    const a = ref[k], b = mine[k], abs = k === "blinks_per_min" || k === "smile_p50" || k === "upper_lift";
    let verdict = "matches", ratio = a ? b / a : null;
    if (k === "blinks_per_min") { if (Math.abs(b - a) > Math.max(4, 0.5 * a)) verdict = b < a ? "too few" : "too many"; }
    else if (k === "upper_lift") { if (Math.abs(b - a) > 0.15) verdict = b < a ? "upper lip lifts too little" : "upper lip lifts too much"; }
    else if (k === "smile_p50") { if (Math.abs(b - a) > 0.2) verdict = b < a ? "too little" : "too much"; }
    else if (ratio !== null && ratio < 0.6) verdict = "too little";
    else if (ratio !== null && ratio > 1.6) verdict = "too much";
    return { key: k, text: REF_TEXT[k], ref: a, mine: b, ratio: abs || ratio === null ? null : +ratio.toFixed(2), verdict };
  });
}
function rvCompareTable(rows) {
  if (!rows || !rows.length) return "";
  const f = v => v === null || v === undefined ? "—" : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(3);
  return '<table class="t small"><tr><th>Compared with her own clips</th><th>Her clips</th><th>This delivery</th><th>Ratio</th><th></th></tr>' + rows.map(r =>
    "<tr><td>" + esc(r.text) + "</td><td>" + f(r.ref) + "</td><td>" + f(r.mine) + "</td><td>" + (r.ratio === null ? "" : r.ratio + "×") + '</td><td><span class="badge ' +
    (r.verdict === "matches" ? "good" : "warn") + '">' + esc(r.verdict) + "</span></td></tr>").join("") + "</table>";
}
// word by word: the original against our reproduction of the same audio (opening, width, how the lower lip drops)
function rvWords(words, A, Bm) {
  const med = fr => { const w = fr.filter(x => x.face && x.mw).map(x => x.mw).sort((a, b) => a - b); return w[Math.floor(w.length / 2)] || 1; };
  const mA = med(A.frames), mB = med(Bm.frames);
  const at = (fr, w, mw) => { const in_ = fr.filter(x => x.face && x.t >= w.start - 0.02 && x.t <= w.end + 0.02); if (!in_.length) return null;
    const open = Math.max(...in_.map(x => x.gap || 0)), wid = in_.map(x => (x.mw || mw) / mw), op = in_.filter(x => (x.gap || 0) > 0.08 && x.up !== undefined);
    const share = op.length ? op.reduce((s, x) => s + x.lo / Math.max(1e-6, x.lo + x.up), 0) / op.length : null;
    return { open, wmin: Math.min(...wid), wmax: Math.max(...wid), share, brow: in_.reduce((s, x) => s + x.bs.browInnerUp, 0) / in_.length }; };
  return words.map(w => {
    const a = at(A.frames, w, mA), b = at(Bm.frames, w, mB);
    if (!a || !b) return { word: w.word, start: w.start, end: w.end, missing: true };
    const d = { open: b.open - a.open, narrow: b.wmin - a.wmin, wide: b.wmax - a.wmax, share: a.share !== null && b.share !== null ? b.share - a.share : 0, brow: b.brow - a.brow };
    const err = Math.abs(d.open) / 0.15 + Math.abs(d.narrow) / 0.08 + Math.abs(d.wide) / 0.08 + Math.abs(d.share) / 0.2 + Math.abs(d.brow) / 0.25;
    const say = [];
    if (Math.abs(d.open) > 0.08) say.push(d.open > 0 ? "opens too wide" : "opens too little");
    if (d.narrow < -0.06) say.push("puckers too much"); else if (d.narrow > 0.06) say.push("not rounded enough");
    if (d.wide > 0.06) say.push("spreads too wide"); else if (d.wide < -0.06) say.push("not spread enough");
    if (d.share < -0.15) say.push("lower lip drops too little"); else if (d.share > 0.15) say.push("lower lip drops too much");
    if (Math.abs(d.brow) > 0.15) say.push(d.brow > 0 ? "brows too active" : "brows too still");
    return { word: w.word, start: w.start, end: w.end, orig: a, ours: b, d, match: Math.max(0, Math.round(100 - 12 * err)), say };
  }).sort((x, y) => (x.missing ? 101 : x.match) - (y.missing ? 101 : y.match));
}

// ---------------------------------------------------------------- the review bar under a talking face
function rvOverlay(impl) {
  const cv = impl.cv, host = cv.parentElement;
  let ov = host.querySelector("canvas.rv-ov");
  if (!ov) { ov = document.createElement("canvas"); ov.className = "rv-ov"; host.style.position = "relative"; ov.style.cssText = "position:absolute;left:0;top:0;pointer-events:none"; host.appendChild(ov); }
  ov.width = cv.width; ov.height = cv.height; ov.style.left = cv.offsetLeft + "px"; ov.style.top = cv.offsetTop + "px"; ov.style.width = cv.clientWidth + "px"; ov.style.height = cv.clientHeight + "px";
  return ov;
}
function rvShowBox(impl, box, color, label) {
  const ov = rvOverlay(impl), g = ov.getContext("2d"); g.clearRect(0, 0, ov.width, ov.height);
  if (!box) return;
  const [x0, y0] = impl.toCanvas(box[0], box[1]), [x1, y1] = impl.toCanvas(box[0] + box[2], box[1] + box[3]);
  g.strokeStyle = color || "#d33"; g.lineWidth = Math.max(2, ov.width / 200); g.strokeRect(x0, y0, x1 - x0, y1 - y0);
  if (label) { g.font = Math.round(ov.width / 32) + "px sans-serif"; g.fillStyle = color || "#d33"; g.fillText(label, x0 + 3, Math.max(14, y0 - 4)); }
  clearTimeout(RV.boxTimer); RV.boxTimer = setTimeout(() => g.clearRect(0, 0, ov.width, ov.height), 6000);
}
// drag a box on the picture; resolves with the box in portrait pixels (or null if cancelled with Esc)
function rvDrawBox(impl) {
  return new Promise(resolve => {
    const ov = rvOverlay(impl), g = ov.getContext("2d"), sc = () => ov.width / ov.clientWidth;
    ov.style.pointerEvents = "auto"; ov.style.cursor = "crosshair";
    let a = null;
    const pos = e => { const r = ov.getBoundingClientRect(); return [(e.clientX - r.left) * sc(), (e.clientY - r.top) * sc()]; };
    const done = box => { ov.style.pointerEvents = "none"; ov.style.cursor = ""; ov.onpointerdown = ov.onpointermove = ov.onpointerup = null; document.removeEventListener("keydown", esc_); resolve(box); };
    const esc_ = e => { if (e.key === "Escape") { g.clearRect(0, 0, ov.width, ov.height); done(null); } };
    document.addEventListener("keydown", esc_);
    ov.onpointerdown = e => { a = pos(e); ov.setPointerCapture(e.pointerId); };
    ov.onpointermove = e => { if (!a) return; const b = pos(e); g.clearRect(0, 0, ov.width, ov.height); g.strokeStyle = "#d33"; g.lineWidth = Math.max(2, ov.width / 200); g.strokeRect(a[0], a[1], b[0] - a[0], b[1] - a[1]); };
    ov.onpointerup = e => { if (!a) return; const b = pos(e), p0 = impl.toPortrait(Math.min(a[0], b[0]), Math.min(a[1], b[1])), p1 = impl.toPortrait(Math.max(a[0], b[0]), Math.max(a[1], b[1]));
      if (Math.abs(b[0] - a[0]) < 6 || Math.abs(b[1] - a[1]) < 6) { a = null; return; }
      done([Math.round(p0[0]), Math.round(p0[1]), Math.round(p1[0] - p0[0]), Math.round(p1[1] - p0[1])]); };
  });
}
function rvThumb(impl, box) {
  const c = document.createElement("canvas"); c.width = impl.cv.width; c.height = impl.cv.height; const g = c.getContext("2d"); g.drawImage(impl.cv, 0, 0);
  if (box) { const [x0, y0] = impl.toCanvas(box[0], box[1]), [x1, y1] = impl.toCanvas(box[0] + box[2], box[1] + box[3]); g.strokeStyle = "#d33"; g.lineWidth = Math.max(2, c.width / 200); g.strokeRect(x0, y0, x1 - x0, y1 - y0); }
  return c.toDataURL("image/jpeg", 0.85);
}
async function rvFlagForm(host, defaults) {
  const reasons = await rvReasons();
  return new Promise(resolve => {
    const d = document.createElement("div"); d.className = "note small";
    d.innerHTML = '<b>Flag this moment</b><div class="row"><select data-r>' + Object.entries(reasons).map(([k, v]) => '<option value="' + k + '"' + (k === defaults.reason ? " selected" : "") + ">" + esc(v) + "</option>").join("") +
      '</select><input data-n placeholder="what is wrong (optional)" value="' + esc(defaults.note || "") + '" style="flex:1"><button class="btn" data-s>Save flag</button><button class="btn quiet" data-c>Cancel</button></div>';
    host.prepend(d);
    d.querySelector("[data-s]").onclick = () => { const r = { reason: d.querySelector("[data-r]").value, note: d.querySelector("[data-n]").value }; d.remove(); resolve(r); };
    d.querySelector("[data-c]").onclick = () => { d.remove(); resolve(null); };
  });
}
// the timeline of a check: one lane per kind, a mark for every span; click a mark to see that moment with its box
function rvTimeline(r, onPick) {
  const kinds = [...new Set(r.spans.map(s => s.kind))], W = 640, lane = 14, H = Math.max(1, kinds.length) * lane + 18;
  const c = document.createElement("canvas"); c.width = W; c.height = H; c.style.cssText = "width:100%;max-width:640px;cursor:pointer;background:var(--chip);border-radius:6px";
  const g = c.getContext("2d"), x = t => 4 + (W - 8) * t / Math.max(0.1, r.duration);
  g.font = "10px sans-serif"; g.fillStyle = "#888";
  for (let s = 0; s <= r.duration; s += Math.max(1, Math.round(r.duration / 10))) { g.fillRect(x(s), H - 14, 1, 4); g.fillText(s + "s", x(s) + 2, H - 4); }
  r.spans.forEach(s => { const k = kinds.indexOf(s.kind); g.fillStyle = KIND_COLOR[s.kind] || "#555"; g.fillRect(x(s.t0), 3 + k * lane, Math.max(3, x(s.t1) - x(s.t0)), lane - 4); });
  c.onclick = e => { const rc = c.getBoundingClientRect(), t = (e.clientX - rc.left) / rc.width * r.duration, k = Math.floor((e.clientY - rc.top) / rc.height * H / lane);
    const sp = r.spans.filter(s => kinds.indexOf(s.kind) === k).sort((a, b) => Math.abs((a.t0 + a.t1) / 2 - t) - Math.abs((b.t0 + b.t1) / 2 - t))[0]; if (sp) onPick(sp); };
  return c;
}
function rvAttach(box, face, ctx) {
  let bar = box.querySelector("[data-rv]");
  if (!bar) { bar = document.createElement("div"); bar.dataset.rv = "1"; box.appendChild(bar); }
  bar.innerHTML = '<div class="row" style="margin:6px 0"><button class="btn quiet" data-rvcheck>🔍 Check delivery</button><button class="btn quiet" data-rvflag>⚑ Flag a problem</button>' +
    '<span class="small muted" data-rvnote>Check measures every frame (background, forehead and head region, hair, lips, smears) and compares with her own clips; Flag: pause, drag a box around what is wrong.</span></div><div data-rvout></div>';
  const note = m => { bar.querySelector("[data-rvnote]").textContent = m; }, out = bar.querySelector("[data-rvout]");
  const impl = () => face.impl && face.impl.deliveryCheck ? face.impl : null;
  const seek = t => { if (ctx.audio) { ctx.audio.pause(); ctx.audio.currentTime = Math.max(0, t); } };
  const flag = async (t, box2, reason, src, noteText) => {
    const f = impl(); if (!f) return;
    const form = await rvFlagForm(out, { reason, note: noteText });
    if (!form) return;
    const r = await api("/api/avatars/flag", { id: ctx.avatarId(), t, box: box2, reason: form.reason, note: form.note, source: src, state: f.state(), script: ctx.text,
      renderer: window.QB_VERSION || "", thumb: rvThumb(f, box2) });
    toast("Flag #" + r.id + " saved — Avatar studio → Flags lists it; the learning loop works on it.");
  };
  bar.querySelector("[data-rvflag]").onclick = async () => {
    const f = impl(); if (!f) return toast("Flags work on library faces (choose a face above).");
    if (ctx.audio) ctx.audio.pause();
    note("Drag a box around what is wrong on the picture (Esc cancels). The moment shown is the one flagged: scrub the audio to the right spot first if needed.");
    await new Promise(r => setTimeout(r, 150));
    const t = ctx.audio ? ctx.audio.currentTime : 0, b2 = await rvDrawBox(f);
    if (!b2) return note("Flag cancelled.");
    note("Say what is wrong, then save.");
    await flag(t, b2, "other", "you", "");
  };
  bar.querySelector("[data-rvcheck]").onclick = async () => {
    const f = impl(); if (!f) return toast("The check works on library faces (choose a face above).");
    if (!face.track || !face.track.motion) return toast("Wait until all 52 face channels are ready, then check.");
    if (ctx.audio) ctx.audio.pause();
    note("Checking every frame…"); await new Promise(r => setTimeout(r, 30));
    const r = f.deliveryCheck(face.track);
    let ref = null, cmp = null;
    try { ref = (await api("/api/avatars/reference?id=" + ctx.avatarId())).reference; } catch (e) { ref = null; }
    if (ref && ref.stats) {
      try { const D = await rvMeasureDelivery(f, face.track, r.duration, note); cmp = rvCompare(rvStats(D.frames, D.fps), ref.stats); } catch (e) { cmp = null; note("Comparison with her clips failed: " + e.message); }
    }
    api("/api/avatars/check", { id: ctx.avatarId(), script: ctx.text, duration: r.duration, score: r.score, spans: r.spans, reference: cmp, renderer: window.QB_VERSION || "" }).catch(() => {});
    note("");
    const kinds = {}; r.spans.forEach(s => { kinds[s.kind] = (kinds[s.kind] || 0) + (s.t1 - s.t0); });
    out.innerHTML = '<div class="note small"><b>Delivery check: ' + r.score + "/100</b> — " + (r.spans.length ? r.spans.length + " problem span(s): " +
      Object.entries(kinds).map(([k, s]) => '<span style="color:' + (KIND_COLOR[k] || "#555") + '">■</span> ' + esc(k) + " " + s.toFixed(1) + " s").join(" · ") : "nothing found in " + r.frames + " frames") +
      (r.silhouette ? "" : " · (no silhouette: background measured outside the head only)") + ' <button class="btn quiet small" data-rvclr>Clear</button></div>';
    if (r.spans.length) {
      out.appendChild(rvTimeline(r, sp => { seek((sp.t0 + sp.t1) / 2); setTimeout(() => rvShowBox(f, sp.box, KIND_COLOR[sp.kind], sp.kind), 120); }));
      out.insertAdjacentHTML("beforeend", '<table class="t small"><tr><th>When</th><th>What</th><th>Worst</th><th></th></tr>' + r.spans.slice(0, 60).map((s, i) =>
        "<tr><td>" + s.t0.toFixed(2) + "–" + s.t1.toFixed(2) + ' s</td><td><span style="color:' + (KIND_COLOR[s.kind] || "#555") + '">■</span> ' + esc(s.why) + "</td><td>" + s.worst +
        (s.limit ? " (limit " + s.limit + ")" : "") + '</td><td><button class="btn quiet small" data-rvshow="' + i + '">Show</button><button class="btn quiet small" data-rvkeep="' + i + '">⚑ Keep as flag</button></td></tr>').join("") + "</table>");
      out.querySelectorAll("[data-rvshow]").forEach(b => b.onclick = () => { const s = r.spans[+b.dataset.rvshow]; seek((s.t0 + s.t1) / 2); setTimeout(() => rvShowBox(f, s.box, KIND_COLOR[s.kind], s.kind), 120); });
      out.querySelectorAll("[data-rvkeep]").forEach(b => b.onclick = async () => { const s = r.spans[+b.dataset.rvkeep]; seek((s.t0 + s.t1) / 2); await new Promise(z => setTimeout(z, 150));
        const reason = { background: "background", region: "region", hair: "hair", jump: "head", lips: "lips", fold: "fold" }[s.kind] || "other"; await flag((s.t0 + s.t1) / 2, s.box, reason, "check", s.why); });
    }
    if (cmp) out.insertAdjacentHTML("beforeend", rvCompareTable(cmp));
    else if (!ref) out.insertAdjacentHTML("beforeend", '<p class="small muted">No reference clips for this face yet — Avatar studio → Reference clips: add videos of the person speaking to compare with.</p>');
    const clr = out.querySelector("[data-rvclr]"); if (clr) clr.onclick = () => { out.innerHTML = ""; rvShowBox(f, null); };
  };
}

// ---------------------------------------------------------------- Avatar studio: flags, reference clips, reproduce & compare, learning from flags
async function rvStudio(el, a) {
  const host = document.createElement("div"); host.className = "note small"; host.id = "rv-studio";
  const old = $("#rv-studio", el); if (old) old.remove();
  $("#av-info", el).appendChild(host);
  host.innerHTML = '<b>Delivery review</b> — flags, reference clips and learning. <div data-rvref></div><div data-rvflags></div>';
  await rvRefSection(host.querySelector("[data-rvref]"), a);
  await rvFlagSection(host.querySelector("[data-rvflags]"), a);
}
async function rvRefSection(box, a) {
  const ref = (await api("/api/avatars/reference?id=" + a.id)).reference;
  box.innerHTML = '<h4 style="margin:8px 0 4px">Reference clips <span class="muted">(how she really speaks — from her original creator)</span></h4>' +
    (ref && ref.clips.length ? '<table class="t small"><tr><th>Clip</th><th>Frames</th>' + REF_KEYS.map(k => "<th title=\"" + esc(REF_TEXT[k]) + "\">" + esc(REF_TEXT[k].split(" (")[0]) + "</th>").join("") + "<th></th></tr>" +
      ref.clips.map(c => "<tr><td>" + esc(c.clip) + "</td><td>" + c.frames + "</td>" + REF_KEYS.map(k => "<td>" + (c.stats[k] === undefined ? "—" : (+c.stats[k]).toFixed(Math.abs(c.stats[k]) >= 10 ? 1 : 3)) + "</td>").join("") +
        '<td><button class="btn quiet small" data-rvrefdel="' + esc(c.clip) + '">✕</button></td></tr>').join("") + "</table>" : '<p class="muted">None yet.</p>') +
    '<div class="row"><input type="file" accept="video/*" data-rvfile aria-label="A video of her speaking"><input data-rvwords placeholder="the words spoken in the clip (for Reproduce & compare)" style="flex:1">' +
    '<button class="btn quiet" data-rvstt title="Google Speech-to-Text (needs your key)">Transcribe</button></div><div class="row"><button class="btn" data-rvadd>Add as reference clip</button>' +
    '<button class="btn" data-rvrepro>Reproduce &amp; compare</button><span class="muted" data-rvn></span></div><div data-rvres></div>';
  const note = m => { box.querySelector("[data-rvn]").textContent = m; }, file = () => { const f = box.querySelector("[data-rvfile]").files[0]; if (!f) toast("Choose a video of her speaking first."); return f; };
  box.querySelectorAll("[data-rvrefdel]").forEach(b => b.onclick = async () => { if (confirm("Remove this reference clip?")) { await api("/api/avatars/reference_remove", { id: a.id, clip: b.dataset.rvrefdel }); rvRefSection(box, a); } });
  box.querySelector("[data-rvadd]").onclick = async () => { const f = file(); if (!f) return;
    try { const M = await rvMeasureVideo(await rvPlayable(f), note), st = rvStats(M.frames, M.fps); if (!st) throw new Error("no face was found in enough of it");
      await api("/api/avatars/reference", { id: a.id, clip: f.name, stats: st, frames: M.frames.filter(x => x.face).length }); note("Added."); rvRefSection(box, a); }
    catch (e) { note("Could not add: " + e.message); } };
  box.querySelector("[data-rvstt]").onclick = async () => { const f = file(); if (!f) return;
    try { note("Transcribing…"); const b64 = await rvWav(f);              // the clip's sound as WAV (data URL)
      const st = await api("/api/speech/transcribe-file", { audio_b64: b64, lang: "en", mode: "auto" });
      let res; for (let i = 0; i < 240; i++) { res = await api("/api/speech/transcribe-status?task=" + encodeURIComponent(st.task)); if (res.state !== "running") break; await new Promise(r => setTimeout(r, 1000)); }
      box.querySelector("[data-rvwords]").value = (res && res.result && res.result.transcript) || ""; note(res && res.state === "failed" ? "Transcription failed (" + res.message + ") — type the words." : "Transcribed — check the words."); }
    catch (e) { note("Transcription is not available (" + e.message + ") — type the words."); } };
  box.querySelector("[data-rvrepro]").onclick = async () => {
    const f = file(); if (!f) return;
    const words = box.querySelector("[data-rvwords]").value.trim(); if (!words) return toast("Type (or transcribe) the words spoken in the clip first.");
    try { await rvReproduce(box.querySelector("[data-rvres]"), a, f, words, note); } catch (e) { note("Could not reproduce: " + e.message); }
  };
}
// the clip's own voice and words → our lip sync → her face; both read by the tracker; word by word, side by side
async function rvReproduce(out, a, file, words, note) {
  note("Taking the clip's own voice…");
  const b64 = await rvWav(file);                             // the clip's own sound as WAV (data URL)
  note("Lip sync of the clip's voice…");
  const job = await api("/api/vse/lip_sync", { audio_b64: b64, text: words, lang: "en" }), res = await avWaitJob(job.job_id, note);
  const track = { visemes: [], motion: res.motion, words: res.words };
  const A = await rvMeasureVideo(await rvPlayable(file), note);
  out.innerHTML = '<div class="row" style="align-items:flex-start"><div style="flex:1;min-width:240px"><b class="small">Original</b><div data-rvorig></div></div>' +
    '<div style="flex:1;min-width:240px"><b class="small">QueryBook reproduction (same voice, same words)</b><div data-rvours style="max-width:420px"></div></div></div><div data-rvbar></div><div data-rvtab></div>';
  const v = A.video; v.controls = true; v.muted = false; v.style.width = "100%"; out.querySelector("[data-rvorig]").appendChild(v);
  const face = new TalkingFace(out.querySelector("[data-rvours]"));
  await face.setMode("avatar", { avatar: { imageUrl: "/api/avatars/image?id=" + a.id, landmarks: a.landmarks, label: a.label, body: a.kind === "body" }, params: { camera: "still" } });
  if (face.impl.body) face.impl.closeUp(true);               // framed like the original: head and shoulders
  face.attach(v, track);                                     // the original video drives our face: both play in step
  const B = await rvMeasureDelivery(face.impl, track, A.duration, note);
  const sA = rvStats(A.frames, A.fps), sB = rvStats(B.frames, B.fps), cmp = rvCompare(sB, sA), W = rvWords(res.words || [], A, B);
  rvAttach(out.querySelector("[data-rvbar]"), face, { avatarId: () => a.id, text: words, audio: v });
  out.querySelector("[data-rvtab]").innerHTML = rvCompareTable(cmp).replace("Compared with her own clips", "Whole clip") +
    '<table class="t small"><tr><th>Word</th><th>Time</th><th>Match</th><th>Opening (orig / ours)</th><th>Narrowest</th><th>Widest</th><th>Lower lip share</th><th>What differs</th><th></th></tr>' +
    W.map((w, i) => w.missing ? "<tr><td>" + esc(w.word) + '</td><td colspan="8" class="muted">no face found at that moment</td></tr>' :
      "<tr><td><b>" + esc(w.word) + "</b></td><td>" + w.start.toFixed(2) + "</td><td><span class=\"badge " + (w.match >= 80 ? "good" : w.match >= 60 ? "warn" : "bad") + '">' + w.match + "</span></td><td>" +
      w.orig.open.toFixed(2) + " / " + w.ours.open.toFixed(2) + "</td><td>" + w.orig.wmin.toFixed(2) + " / " + w.ours.wmin.toFixed(2) + "</td><td>" + w.orig.wmax.toFixed(2) + " / " + w.ours.wmax.toFixed(2) + "</td><td>" +
      (w.orig.share === null ? "—" : w.orig.share.toFixed(2)) + " / " + (w.ours.share === null ? "—" : w.ours.share.toFixed(2)) + "</td><td>" + esc(w.say.join(", ") || "close") +
      '</td><td><button class="btn quiet small" data-rvw="' + i + '">Show</button></td></tr>').join("") + "</table>";
  out.querySelectorAll("[data-rvw]").forEach(b => b.onclick = () => { const w = W[+b.dataset.rvw]; v.pause(); v.currentTime = (w.start + w.end) / 2; });
  api("/api/avatars/check", { id: a.id, script: "reproduction of " + file.name + ": " + words, duration: A.duration, score: Math.round(W.filter(w => !w.missing).reduce((s, w) => s + w.match, 0) / Math.max(1, W.filter(w => !w.missing).length)),
    spans: [], reference: { kind: "reproduction", whole: cmp, words: W.map(w => ({ word: w.word, start: w.start, match: w.match, say: w.say, d: w.d })) }, renderer: window.QB_VERSION || "" }).catch(() => {});
  note("Done — worst-matching words first. Play the original: our face follows it. Flag anything you see.");
}
async function rvFlagSection(box, a) {
  const flags = (await api("/api/avatars/flags?id=" + a.id)).flags, open = flags.filter(f => f.status === "open");
  box.innerHTML = '<h4 style="margin:8px 0 4px">Flags <span class="muted">(' + open.length + " open of " + flags.length + ')</span></h4>' +
    (flags.length ? '<div class="row"><button class="btn" data-rvimprove' + (open.some(f => f.measured) ? "" : " disabled") + '>Improve from flags</button><button class="btn quiet" data-rvrecheckall>Re-check all open</button>' +
      '<span class="muted" data-rvfn>The learning loop tries calibrations against every open, measurable flag and proposes the best to the Quality Lab — the admin approves it there.</span></div><div data-rvimp></div>' +
      '<table class="t small"><tr><th>Picture</th><th>#</th><th>When</th><th>What</th><th>Status</th><th>Now</th><th></th></tr>' + flags.map(f =>
        "<tr><td>" + (f.has_thumb ? '<img src="/api/avatars/flag_thumb?flag=' + f.id + '" style="max-width:150px;border-radius:4px">' : "") + "</td><td>" + f.id + "</td><td>" + esc(f.created) + "<br>at " + (f.t || 0).toFixed(2) + " s · " +
        (f.source === "check" ? "found by the check" : "flagged by you") + "</td><td><b>" + esc(f.reason_text) + "</b>" + (f.note ? "<br>" + esc(f.note) : "") + (f.measured ? "" : '<br><span class="muted">needs your eyes (not measured)</span>') +
        "</td><td>" + esc(f.status) + "</td><td data-rvnow=\"" + f.id + '">' + rvRecheckText(f) + '</td><td><button class="btn quiet small" data-rvre="' + f.id + '">Re-check</button>' +
        '<button class="btn quiet small" data-rvst="fixed" data-f="' + f.id + '">Fixed</button><button class="btn quiet small" data-rvst="open" data-f="' + f.id + '">Still wrong</button>' +
        '<button class="btn quiet small" data-rvst="wontfix" data-f="' + f.id + '">Won\'t fix</button><button class="btn quiet small" data-rvdel="' + f.id + '">✕</button></td></tr>').join("") + "</table>" : '<p class="muted">No flags yet — under a talking face: ⚑ Flag a problem.</p>');
  const reload = () => rvFlagSection(box, a);
  box.querySelectorAll("[data-rvst]").forEach(b => b.onclick = async () => { await api("/api/avatars/flag_set", { flag: +b.dataset.f, status: b.dataset.rvst }); reload(); });
  box.querySelectorAll("[data-rvdel]").forEach(b => b.onclick = async () => { if (confirm("Delete this flag?")) { await api("/api/avatars/flag_delete", { flag: +b.dataset.rvdel }); reload(); } });
  box.querySelectorAll("[data-rvre]").forEach(b => b.onclick = async () => { await rvRecheck(a, flags.filter(f => f.id === +b.dataset.rvre)); reload(); });
  const all = box.querySelector("[data-rvrecheckall]"); if (all) all.onclick = async () => { await rvRecheck(a, open); reload(); };
  const imp = box.querySelector("[data-rvimprove]"); if (imp) imp.onclick = () => rvImprove(box.querySelector("[data-rvimp]"), a, open.filter(f => f.measured && f.state), m => { box.querySelector("[data-rvfn]").textContent = m; });
}
function rvRecheckText(f) {
  const last = (f.history || []).filter(h => h.recheck).slice(-1)[0];
  if (!last) return '<span class="muted">not re-checked</span>';
  const r = last.recheck;
  return (r.badness === null ? "re-rendered" : (r.badness <= 1 ? '<span class="badge good">within limits</span>' : '<span class="badge bad">' + r.badness.toFixed(2) + "× the limit</span>")) +
    '<br><span class="muted">' + esc(last.at) + "</span>" + (r.picture ? '<br><img src="' + r.picture + '" style="max-width:150px;border-radius:4px" title="as it renders now">' : "");
}
async function rvFaceFor(a, cal) {
  const h = document.createElement("div"); h.style.cssText = "position:absolute;left:-9999px;width:480px"; document.body.appendChild(h);
  const f = new DepthFace(h, { imageUrl: "/api/avatars/image?id=" + a.id, landmarks: a.landmarks, label: "", body: a.kind === "body" }, { camera: "still", cal });
  await f.ready; f._host = h; return f;
}
// a flag's moment under the current renderer: measured (where the reason is measurable) and drawn again
async function rvRecheck(a, flags) {
  const f = await rvFaceFor(a);
  try {
    for (const fl of flags) {
      if (!fl.state) continue;
      const m = f.measureState(fl.state, fl.box), bad = fl.measured ? +f.badness(m, fl.reason).toFixed(3) : null;
      f.cur = Float32Array.from(fl.state.chan); f.head = fl.state.head.slice(); f.t = fl.state.t; f.view = null; f._draw();
      const pic = rvThumb(f, fl.box);
      const small = await new Promise(r => { const i = new Image(); i.onload = () => { const c = document.createElement("canvas"), k = 220 / i.width; c.width = 220; c.height = Math.round(i.height * k);
        c.getContext("2d").drawImage(i, 0, 0, c.width, c.height); r(c.toDataURL("image/jpeg", 0.8)); }; i.src = pic; });
      await api("/api/avatars/flag_set", { flag: fl.id, recheck: { badness: bad, renderer: window.QB_VERSION || "", picture: small } });
    }
  } finally { f.dispose(); f._host.remove(); }
}
// the learning loop: coordinate search over the calibration, scored on every open measurable flag; the mouth-pose quality
// control must not get worse. The best set goes to the Quality Lab as a candidate — the admin approves it there.
async function rvImprove(out, a, flags, note) {
  if (!flags.length) return note("No open flag that can be measured (background, forehead/head region, lips, hair, smear).");
  const calInfo = await api("/api/qlab/calibration"), bounds = calInfo.bounds, start = Object.assign({}, (await api("/api/qlab/active")).params);
  const KEYS = ["brow", "head", "round", "spread", "jaw", "arch", "close", "sway", "breath"].filter(k => k in bounds && (a.kind === "body" || (k !== "sway" && k !== "breath")));
  const score = async cal => { const f = await rvFaceFor(a, cal);
    try { const per = flags.map(fl => f.badness(f.measureState(fl.state, fl.box), fl.reason)); return { per, total: per.reduce((s, b) => s + Math.max(0, b - 0.5), 0), qc: f.quality ? f.quality.issues.length : 0 }; }
    finally { f.dispose(); f._host.remove(); } };
  note("Scoring the current calibration on " + flags.length + " flag(s)…");
  const base = await score(start), trials = [{ change: "current calibration", total: base.total, qc: base.qc }];
  let best = { cal: start, ...base };
  for (let round = 1; round <= 3; round++) {
    let moved = false;
    for (const k of KEYS) for (const m of [0.85, 1.15]) {
      const cal = Object.assign({}, best.cal); cal[k] = Math.max(bounds[k][0], Math.min(bounds[k][1], +(cal[k] * m).toFixed(3)));
      if (cal[k] === best.cal[k]) continue;
      note("Round " + round + ": " + k + " × " + m + "…");
      const s = await score(cal);
      trials.push({ change: k + " " + best.cal[k] + " → " + cal[k], total: s.total, qc: s.qc });
      if (s.total < best.total * 0.98 && s.qc <= base.qc) { best = { cal, ...s }; moved = true; }
    }
    if (!moved) break;
  }
  const changed = KEYS.filter(k => best.cal[k] !== start[k]);
  out.innerHTML = '<div class="note small"><b>Learning from ' + flags.length + " flag(s)</b> — " + (base.total === 0 ? "every flag is already within its limits with the current renderer — re-check them and mark them fixed if you agree." : changed.length ? "a better calibration found: " + changed.map(k => esc(k) + " " + start[k] + " → " + best.cal[k]).join(", ") +
    ". Total badness " + base.total.toFixed(2) + " → " + best.total.toFixed(2) + "." : "no calibration change helps these flags — they need a change in the renderer itself (send them with your next feedback).") +
    '<table class="t small"><tr><th>Flag</th><th>What</th><th>Now</th><th>With the proposal</th></tr>' + flags.map((fl, i) => "<tr><td>#" + fl.id + "</td><td>" + esc(fl.reason_text) + "</td><td>" + base.per[i].toFixed(2) +
      "</td><td>" + best.per[i].toFixed(2) + "</td></tr>").join("") + "</table><details><summary>All " + trials.length + " trials</summary><table class=\"t small\">" + trials.map(t => "<tr><td>" + esc(t.change) + "</td><td>" + t.total.toFixed(3) +
      "</td><td>" + (t.qc ? t.qc + " QC issue(s)" : "") + "</td></tr>").join("") + "</table></details>" +
    (changed.length ? '<div class="row"><button class="btn" data-rvsave>Send to the Quality Lab as a candidate</button><span class="muted">the admin approves it there (Speech → Quality lab); until then nothing changes</span></div>' : "") + "</div>";
  const sv = out.querySelector("[data-rvsave]");
  if (sv) sv.onclick = async () => { const r = await api("/api/qlab/candidate", { params: best.cal, origin: "flags", note: "from " + flags.length + " flag(s) on " + a.name + ": " + changed.join(", ") });
    toast("Candidate v" + r.version + " is waiting for the admin in the Quality Lab."); };
  note("Done: " + trials.length + " trials.");
}
window.rvAttach = rvAttach; window.rvStudio = rvStudio;
