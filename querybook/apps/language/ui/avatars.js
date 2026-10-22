"use strict";
// Avatar library: portraits → depth avatars that speak with all 52 face channels (Speech → Avatars).
const AV = { list: [], sel: null, face: null, audio: null, sources: {} };
// the calibration every face speaks with (approved by the admin in the Quality Lab)
fetch("/api/qlab/active").then(r => r.json()).then(c => { window.QB_CAL = c; }).catch(() => {});

async function avWaitJob(jid, note) {
  for (let i = 0; i < 600; i++) {
    const j = await api("/api/vse/job?id=" + jid);
    if (j.status === "completed") return j.result;
    if (j.status === "failed") throw new Error(j.error || "the face motion could not be made");
    if (note && j.progress) note(j.progress.message || "");
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error("the face motion took too long");
}

async function avLandmarks(url) {
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("image")); i.src = url; });
  const k = Math.min(1, 1280 / Math.max(img.width, img.height)), c = document.createElement("canvas");
  c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  const lm = await tracker(), r = lm.detectForVideo(c, performance.now());
  const L = r.faceLandmarks && r.faceLandmarks[0], q = x => Math.round(x * 1e5) / 1e5;
  if (L) return L.map(p => [q(p.x), q(p.y), q(p.z)]);
  // a full-length photo: the face is too small for the tracker — look again through zoomed windows over the upper part
  // of the picture, and map the points back onto the whole photo
  const W = img.width, H = img.height, z = document.createElement("canvas"); z.width = z.height = 640;
  for (const f of [0.5, 0.35, 0.7]) {
    const side = f * Math.min(W, H);
    for (let sy = 0; sy <= Math.max(0, 0.6 * H - side / 2); sy += side / 3) for (let sx = 0; sx + side <= W + 1; sx += side / 3) {
      const g = z.getContext("2d"); g.clearRect(0, 0, 640, 640); g.drawImage(img, sx, sy, side, side, 0, 0, 640, 640);
      const rr = lm.detectForVideo(z, performance.now()), M = rr.faceLandmarks && rr.faceLandmarks[0];
      if (M) return M.map(p => [q((sx + p.x * side) / W), q((sy + p.y * side) / H), q(p.z * side / W)]);
    }
  }
  return null;
}

// Turnaround (full body): a video of the person turning on the spot becomes their own side and back views. Every frame
// is aligned to the face where the tracker sees it (front to ~60° either way); behind, where no face shows, the
// alignment is carried across from the frames on either side. Frames are stored with the avatar; the part where the
// person actually turns is marked so the avatar can play just that.
async function avMotionAnalyse(file, note, prior) {
  const v = document.createElement("video"); v.muted = true; v.playsInline = true; v.src = URL.createObjectURL(file);
  await new Promise((ok, bad) => { v.onloadeddata = ok; v.onerror = () => bad(new Error("this video cannot be played here")); });
  if (!isFinite(v.duration)) await new Promise(res => { v.ondurationchange = () => { if (isFinite(v.duration)) res(); }; v.currentTime = 1e9; setTimeout(res, 3000); });
  const fps = 12, dur = Math.min(v.duration || 0, 30), W = v.videoWidth, H = v.videoHeight;
  const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
  const seek = t => new Promise(r => { v.onseeked = r; v.currentTime = t; });
  const lm = await tracker(), rows = [];
  let det = null; try { det = await scDetector(); } catch (e) { det = null; }     // the person's outline (also from behind)
  const zc = document.createElement("canvas"); zc.width = zc.height = 512; let zoomed = false;
  const sm = document.createElement("canvas"); sm.width = 64; sm.height = 36; const sg = sm.getContext("2d", { willReadFrequently: true }); let prev = null;
  for (let t = 0; t < dur - 0.02; t += 1 / fps) {
    await seek(t); g.drawImage(v, 0, 0);
    const now = performance.now() + rows.length;
    let face = null, yaw = null, box = null;
    if (det) { const people = (det.detectForVideo(c, now).detections || []).filter(d => (d.categories[0] || {}).categoryName === "person");
      const bb = people.sort((a, b) => b.boundingBox.width * b.boundingBox.height - a.boundingBox.width * a.boundingBox.height)[0];
      if (bb) box = { x: bb.boundingBox.originX, y: bb.boundingBox.originY, w: bb.boundingBox.width, h: bb.boundingBox.height }; }
    // the face: in the whole frame, or — full length, where it is small — in a zoomed square around the head
    const head = () => {                             // a square around the top of the person's outline, enlarged
      const side = Math.min(H, Math.max(box.w * 0.9, box.h * 0.3)), x0 = box.x + box.w / 2 - side / 2, y0 = Math.max(0, box.y - side * 0.08);
      zc.getContext("2d").drawImage(c, x0, y0, side, side, 0, 0, 512, 512); return { src: zc, map: { x: x0, y: y0, s: side / 512 } };
    };
    let src = c, map = { x: 0, y: 0, s: 1 };
    if (box && zoomed) ({ src, map } = head());
    let r = lm.detectForVideo(src, now), L = r.faceLandmarks && r.faceLandmarks[0];
    if (!L && !zoomed && box) { zoomed = true; ({ src, map } = head()); r = lm.detectForVideo(src, now + 0.5); L = r.faceLandmarks && r.faceLandmarks[0]; }
    if (L) {
      const X = q => map.x + q.x * src.width * map.s, Y = q => map.y + q.y * src.height * map.s;
      face = { cx: (X(L[10]) + X(L[152])) / 2, cy: (Y(L[10]) + Y(L[152])) / 2, fh: Math.hypot(X(L[10]) - X(L[152]), Y(L[10]) - Y(L[152])) };
      try { const m = measureFrame(r, { videoWidth: src.width, videoHeight: src.height }, t); yaw = m.pose ? m.pose[0] : null; } catch (e) { yaw = null; }
    }
    sg.drawImage(c, 0, 0, 64, 36); const px = sg.getImageData(0, 0, 64, 36).data; let diff = 0;
    if (prev) { for (let i = 0; i < px.length; i += 4) diff += Math.abs(px[i] - prev[i]) + Math.abs(px[i + 1] - prev[i + 1]); diff /= px.length / 2; }
    prev = px;
    rows.push({ t, face, yaw, box, cut: diff > 12 });
    if (rows.length % 12 === 0) note("Reading the turn… " + t.toFixed(0) + " of " + dur.toFixed(0) + " s");
  }
  const seen = rows.map((r, i) => r.face ? i : -1).filter(i => i >= 0);
  if (seen.length < 4) throw new Error("the face is hardly ever visible — use a video where the person faces the camera at least at times");
  const med0 = a => a.length ? a.slice().sort((x, y) => x - y)[Math.floor(a.length / 2)] : null;
  // calibrate the outline against the face on frames facing the camera: face size per shoulder width, head top to face centre
  const cal = rows.filter(r => r.face && r.box && Math.abs(r.yaw || 0) < 20);
  let qW = med0(cal.map(r => r.face.fh / r.box.w)), qTop = med0(cal.map(r => (r.face.cy - r.box.y) / r.face.fh)), qX = med0(cal.map(r => (r.face.cx - (r.box.x + r.box.w / 2)) / r.face.fh));
  const calib = { face_per_width: qW, headtop: qTop, x_off: qX, height_per_face: med0(cal.map(r => r.box.h / r.face.fh)), frames: cal.length };
  if (cal.length < 6 && prior && prior.face_per_width) {  // few clear views of her face here: her proportions from all her other footage
    qW = prior.face_per_width; qTop = prior.headtop; qX = prior.x_off || 0;
  }
  let seg = 0; rows.forEach(r => { if (r.cut) seg++; r.seg = seg; });
  const segW = {};                                     // per shot: the shoulder width when the body is square to the camera (front or back)
  rows.forEach(r => { if (r.box) (segW[r.seg] = segW[r.seg] || []).push(r.box.w); });
  Object.keys(segW).forEach(k => { const a = segW[k].sort((x, y) => x - y); segW[k] = a[Math.floor(a.length * 0.8)]; });
  rows.forEach(r => {
    if (r.face) { r.align = r.face; return; }
    if (r.box && qW && segW[r.seg]) { const fh = qW * segW[r.seg]; r.align = { fh, cx: r.box.x + r.box.w / 2 + (qX || 0) * fh, cy: r.box.y + qTop * fh }; }
  });
  const known = rows.map((r, i) => r.align ? i : -1).filter(i => i >= 0);
  rows.forEach((r, i) => {                             // anything still unknown: carried across from its neighbours
    if (r.align) return;
    const a = [...known].reverse().find(j => j < i), b = known.find(j => j > i);
    if (a === undefined || b === undefined) { r.align = Object.assign({}, rows[a === undefined ? b : a].align); return; }
    const u = (i - a) / (b - a), A = rows[a].align, B = rows[b].align;
    r.align = { cx: A.cx + (B.cx - A.cx) * u, cy: A.cy + (B.cy - A.cy) * u, fh: A.fh + (B.fh - A.fh) * u };
  });
  rows.forEach((r, i) => {                             // steady: a 5-frame running median within each shot
    const nb = rows.slice(Math.max(0, i - 2), i + 3).filter(x => x.seg === r.seg);
    r.al2 = { cx: med0(nb.map(x => x.align.cx)), cy: med0(nb.map(x => x.align.cy)), fh: med0(nb.map(x => x.align.fh)) };
  });
  rows.forEach(r => { r.align = r.al2; });
  return { v, file, W, H, fps, rows, seek, calib };
}

// Store one move from an analysed video: o = { slug, name, words, from, to (s), align: "track" | "fixed", trim }.
//   track — every frame aligned to the person (a turn on the spot: she stays where she stands);
//   fixed — one camera for the whole move, taken from its first frames, where it meets the talking avatar (a cartwheel, a
//           walk towards the camera: the body travels through the picture, as it should). Fixed moves keep their own
//           framing (a close-up stays a close-up).
async function avMotionStore(id, A, o, note) {
  const { v, W, H, fps, seek } = A, med = a => a.slice().sort((x, y) => x - y)[Math.floor(a.length / 2)];
  let rows = A.rows.filter(r => r.t >= (o.from || 0) - 1e-6 && r.t < (o.to === undefined ? 1e9 : o.to) - 1e-6);
  if (rows.length < 4) throw new Error("the move " + o.name + " is too short");
  const withFace = rows.filter(r => r.face);
  let faceH, faceCy, start = 0, end = rows.length - 1;
  if (o.align === "fixed") {
    // the camera comes from frames where she stands upright facing it (earliest first: where the move meets the talking
    // avatar); a move that starts bent over (a cartwheel) takes it from the moment she is upright
    const fr = rows.filter(r => r.face && Math.abs(r.yaw || 0) < 25), ys = fr.map(r => r.face.cy).sort((x, y) => x - y);
    const top = ys.length ? ys[Math.floor(ys.length * 0.3)] + 0.1 * med(fr.map(r => r.face.fh)) : null;
    const up = fr.filter(r => r.face.cy <= top);
    const lead = (up.length ? up.slice(0, Math.max(3, Math.round(0.5 * fps))) : rows.slice(0, Math.max(3, Math.round(0.5 * fps)))).map(r => r.face || r.align);
    const cam = { cx: med(lead.map(q => q.cx)), cy: med(lead.map(q => q.cy)), fh: med(lead.map(q => q.fh)) };
    rows = rows.map(r => Object.assign({}, r, { align: cam }));
    faceH = cam.fh / H; faceCy = cam.cy / H;
  } else {
    const ref = withFace.length ? withFace : rows;
    faceH = med(ref.map(r => (r.face || r.align).fh / H)); faceCy = med(ref.map(r => (r.face || r.align).cy / H));
  }
  if (o.trim) {                                        // a turnaround: keep from just before the head leaves the front to just after it is back
    const away = rows.map(r => r.face === null || Math.abs(r.yaw || 0) > 15);
    const first = away.indexOf(true), last = away.lastIndexOf(true);
    if (first >= 0) { start = Math.max(0, first - Math.round(0.4 * fps)); end = Math.min(rows.length - 1, last + Math.round(0.4 * fps)); }
  }
  const Hn = Math.min(720, H), Wn = Hn, cv = document.createElement("canvas"); cv.width = Wn; cv.height = Hn; const og = cv.getContext("2d");
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i], k = o.align === "fixed" ? Hn / H : faceH * Hn / r.align.fh;
    await seek(r.t);
    og.setTransform(1, 0, 0, 1, 0, 0); og.fillStyle = "#777"; og.fillRect(0, 0, Wn, Hn);
    const cover = Math.max(Wn / W, Hn / H); og.drawImage(v, (Wn - W * cover) / 2, (Hn - H * cover) / 2, W * cover, H * cover);   // nothing left blank
    og.setTransform(k, 0, 0, k, Wn / 2 - r.align.cx * k, faceCy * Hn - r.align.cy * k); og.drawImage(v, 0, 0);
    await api("/api/avatars/motion_put", { id, slug: o.slug, i, data_b64: cv.toDataURL("image/jpeg", 0.85) });
    if (i % 12 === 0) note("Storing “" + o.name + "”… " + Math.round(100 * i / rows.length) + "%");
  }
  AV.lastTurn = rows.map(r => ({ t: r.t, face: r.face, yaw: r.yaw, box: r.box, seg: r.seg }));       // kept for inspection
  return api("/api/avatars/motion_set", { id, slug: o.slug, meta: { name: o.name, words: o.words, frames: rows.length, fps, width: Wn, height: Hn, face_h: faceH,
    face_cy: faceCy, align: o.align || "track", take_of: o.take_of || null, yaw: rows.map(r => r.yaw === null ? null : +r.yaw.toFixed(1)), start, end, source: A.file.name } });
}

async function avTurnaround(id, file, note) {
  const A = await avMotionAnalyse(file, note, await avAnatomy(id));
  try { const r = await avMotionStore(id, A, { slug: "turn-around", name: "turn around", words: ["turn around"], align: "track", trim: true }, note); await avAnatomyLearn(id, A); return r; }
  finally { URL.revokeObjectURL(A.v.src); }
}

// The person's proportions, learned across all their footage (each video weighted by its clear front views)
async function avAnatomy(id) { try { return (await api("/api/avatars/anatomy?id=" + id)).anatomy; } catch (e) { return null; } }
async function avAnatomyLearn(id, A) {
  const c = A.calib; if (!c || c.frames < 3 || !c.face_per_width) return null;
  const prev = await avAnatomy(id);
  // a video whose proportions differ by more than a quarter (arms overhead, swimming, lying down) is a move, not a
  // measurement of how she stands: it does not change her profile
  if (prev && prev.face_per_width && Math.abs(c.face_per_width / prev.face_per_width - 1) > 0.25) return null;
  const old = prev, n0 = old ? old.frames || 0 : 0, n = n0 + c.frames, mix = k => old && old[k] !== undefined && c[k] !== null ? (old[k] * n0 + c[k] * c.frames) / n : c[k];
  return api("/api/avatars/anatomy", { id, anatomy: { face_per_width: mix("face_per_width"), headtop: mix("headtop"), height_per_face: mix("height_per_face"), x_off: mix("x_off"),
    frames: n, videos: ((old && old.videos) || []).concat([A.file.name]) } });
}

// The moves in a video of many: one suggestion per camera shot (edit the names, times and trigger words before storing)
function avMoveSuggest(A) {
  const out = []; let cur = null;
  A.rows.forEach(r => { if (!cur || r.seg !== cur.seg) { if (cur) out.push(cur); cur = { seg: r.seg, from: r.t, to: r.t }; } cur.to = r.t + 1 / A.fps; });
  if (cur) out.push(cur);
  return out.filter(m => m.to - m.from >= 0.5).map((m, k) => ({ slug: "move-" + (k + 1), name: "move " + (k + 1), words: [], from: +m.from.toFixed(2), to: +m.to.toFixed(2), align: "fixed" }));
}

async function avCropFace(url, L, id) {
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("image")); i.src = url; });
  const xs = L.map(p => p[0] * img.width), ys = L.map(p => p[1] * img.height);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  let side = Math.min(img.width, img.height, 2.2 * Math.max(x1 - x0, y1 - y0));
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2 - 0.08 * side;
  const sx = Math.max(0, Math.min(img.width - side, cx - side / 2)), sy = Math.max(0, Math.min(img.height - side, cy - side / 2));
  const out = Math.min(768, Math.round(side)); if (out < 160) return false;
  const c = document.createElement("canvas"); c.width = c.height = out;
  c.getContext("2d").drawImage(img, sx, sy, side, side, 0, 0, out, out);
  await api("/api/avatars/crop", { id, data_b64: c.toDataURL("image/jpeg", 0.9) });
  return true;
}

// Movement check of one face: build it off-screen, run the anatomy/fold/crossing checks (with per-face tuning), keep the result.
async function avCheck(id) {
  const av = await api("/api/avatars/get?id=" + id);
  if (!av.landmarks) return null;
  const host = document.createElement("div"); host.style.cssText = "position:absolute;left:-9999px;width:320px"; document.body.appendChild(host);
  try {
    const f = new DepthFace(host, { imageUrl: "/api/avatars/image?id=" + id, landmarks: av.landmarks, label: "", body: av.kind === "body" }); await f.ready;
    const q = f.quality; f.dispose();
    await api("/api/avatars/qc", { id, qc: q });
    return q;
  } finally { host.remove(); }
}
function avQcText(q) {
  if (!q) return "";
  const t = Object.entries(q.tuned || {}).map(([k, v]) => k + " ×" + v).join(", ");
  const lip = q.lip_line && /moved/.test(q.lip_line.reason || "") ? "; lip line corrected from the photo (" + q.lip_line.moved_px + " px)" : "";
  return q.ok ? "✔ Movement check passed — " + q.poses + " mouth poses within human limits, no folds, lips never cross" + lip + (t ? " (tuned for this face: " + t + ")" : "")
    : "⚠ Movement check: " + q.issues.slice(0, 4).join("; ") + (q.issues.length > 4 ? " … +" + (q.issues.length - 4) : "");
}
async function avCheckAll(el) {
  const out = $("#av-msg", el), list = AV.list.filter(a => a.analysed);
  let ok = 0;
  for (let n = 0; n < list.length; n++) { out.textContent = "Checking movement " + (n + 1) + " of " + list.length + "…"; const q = await avCheck(list[n].id); if (q && q.ok) ok++; }
  out.textContent = "Movement check: " + ok + " of " + list.length + " faces pass every check.";
  await avRefresh(el);
}

async function avAnalyse(el, all) {
  const todo = AV.list.filter(a => all || !a.analysed), out = $("#av-msg", el);
  for (let n = 0; n < todo.length; n++) {
    out.textContent = "Analysing faces " + (n + 1) + " of " + todo.length + " (478 points with depth)…";
    let L = null;
    const url = "/api/avatars/image?id=" + todo[n].id;
    try { L = await avLandmarks(url); } catch (e) { L = null; }
    // A full-length or group photo: crop square around the face so it fills the frame, then measure again.
    if (L && todo[n].kind !== "body" && Math.abs(L[152][1] - L[10][1]) < 0.4) {
      try { if (await avCropFace(url, L, todo[n].id)) L = await avLandmarks(url + "&t=" + Date.now()); } catch (e) {}
    }
    await api("/api/avatars/landmarks", { id: todo[n].id, landmarks: L || [] });
    if (L) { try { await avCheck(todo[n].id); } catch (e) {} }
  }
  out.textContent = todo.length ? "Analysed " + todo.length + " portrait(s)." : "All portraits are analysed.";
  await avRefresh(el);
  if (!AV.sel) {                                       // open the studio straight away on the remembered (or first) face
    const ready = AV.list.filter(a => a.analysed), want = typeof faceChoice === "function" ? Number(faceChoice()) : 0;
    const pick = ready.find(a => a.id === want) || ready[0];
    if (pick) await avSelect(el, pick.id);
  }
}

async function avRefresh(el) {
  const r = await api("/api/avatars/list");
  AV.list = r.avatars; AV.sources = r.sources;
  if (typeof faceAvatars === "function") {
    faceAvatars(true);
    if ($("#sp-faces")) facePicker($("#sp-faces"), () => {});
    facePicker($("#av-faces", el), v => avSelect(el, Number(v)), { avatarsOnly: true, current: AV.sel ? AV.sel.id : "" });
  }
  $("#av-grid", el).innerHTML = AV.list.length ? AV.list.map(a => '<div class="av-tile' + (AV.sel && AV.sel.id === a.id ? " sel" : "") + '" data-av="' + a.id + '" style="display:inline-block;width:132px;margin:4px;vertical-align:top;cursor:pointer;border:2px solid ' +
    (AV.sel && AV.sel.id === a.id ? "var(--accent,#1f6feb)" : "transparent") + ';border-radius:10px;padding:4px">' +
    '<img src="/api/avatars/image?id=' + a.id + '" alt="" loading="lazy" style="width:120px;height:120px;object-fit:cover;border-radius:8px">' +
    '<div class="small"><b>' + esc(a.name) + "</b></div>" + (a.tags.length ? '<div class="small muted">' + esc(a.tags.join(", ")) + "</div>" : "") +
    '<div class="small">' + (!a.analysed ? cmTag("not analysed", "warn") : a.qc && !a.qc.ok ? cmTag("⚠ movement", "warn") : (a.quality || []).length ? cmTag((a.quality || []).length + " note(s)", "warn") : cmTag(a.qc ? "✔ checked" : "ready", "good")) + "</div></div>").join("")
    : '<p class="muted">No avatars yet — import portraits above.</p>';
}

async function avSelect(el, id) {
  const a = await api("/api/avatars/get?id=" + id);
  AV.sel = a;
  await avRefresh(el);
  $("#av-studio", el).hidden = false;
  $("#av-name", el).value = a.name; $("#av-tags", el).value = a.tags.join(", ");
  $("#av-info", el).innerHTML = '<span class="small">' + esc(a.label) + " · " + esc(AV.sources[a.source] || a.source) + (a.width ? " · " + a.width + "×" + a.height + " px" : "") +
    (a.voice ? " · voice: " + esc([a.voice.engine, a.voice.voice].filter(Boolean).join(" ")) : " · voice: the Speak tab's current voice") + "</span>" +
    ((a.quality || []).length ? '<div class="note warn small">' + a.quality.map(esc).join("<br>") + "</div>" : "");
  if (!a.analysed) { if (AV.face && AV.face.impl) AV.face.impl.dispose(); AV.face = null; $("#av-stage", el).innerHTML = '<p class="muted">Analyse the faces first.</p>'; return; }
  if (a.kind === "body") {
    const moves = (a.motions || []).length ? (await api("/api/avatars/motions?id=" + a.id)).motions : [];
    $("#av-info", el).insertAdjacentHTML("beforeend", '<div class="note small" id="av-moves"><b>Moves</b> — her own recorded movements (turning, stretching, walking …), played on a button or ' +
      "when the text says their words.<div class=\"row\">" + (moves.length ? moves.map(m => '<span><button class="btn" data-avmove="' + esc(m.slug) + '">▶ ' + esc(m.name) + '</button><button class="btn quiet small" data-avmovedel="' +
      esc(m.slug) + '" title="Remove">✕</button> <span class="muted">' + esc((m.words || []).join(", ")) + "</span></span>").join(" ") : '<span class="muted">none yet</span>') + "</div>" +
      '<div class="row"><input type="file" accept="video/*" id="av-movefile" aria-label="Video of the person moving"><button class="btn quiet" id="av-turnimp">Import as a turnaround</button>' +
      '<button class="btn quiet" id="av-movefind">Find the moves in it</button><span class="muted" id="av-turnnote"></span></div><div id="av-moveplan"></div></div>');
    const note = m => { $("#av-turnnote", el).textContent = m; }, file = () => { const f = $("#av-movefile", el).files[0]; if (!f) toast("Choose a video of the person first."); return f; };
    $("#av-turnimp", el).onclick = async () => { const f = file(); if (!f) return;
      try { await avTurnaround(a.id, f, note); toast("Turnaround stored."); avSelect(el, a.id); } catch (e) { note("Could not import: " + e.message); } };
    $("#av-movefind", el).onclick = async () => {
      const f = file(); if (!f) return;
      let A; try { A = await avMotionAnalyse(f, note, await avAnatomy(a.id)); } catch (e) { return note("Could not read it: " + e.message); }
      const plan = avMoveSuggest(A);
      note(plan.length + " shot(s) found — name each move, set its times and the words that start it, then store them.");
      const draw = () => { $("#av-moveplan", el).innerHTML = '<table class="t small"><tr><th>Move</th><th>Words that start it</th><th>From (s)</th><th>To (s)</th><th>Camera</th><th>Another take of</th><th></th></tr>' +
        plan.map((m, k) => '<tr><td><input data-mp="name" data-k="' + k + '" value="' + esc(m.name) + '" style="width:120px"></td><td><input data-mp="words" data-k="' + k + '" value="' + esc(m.words.join(", ")) +
          '" placeholder="e.g. stretch, warm up"></td><td><input data-mp="from" data-k="' + k + '" type="number" step="0.05" value="' + m.from + '" style="width:70px"></td><td><input data-mp="to" data-k="' + k +
          '" type="number" step="0.05" value="' + m.to + '" style="width:70px"></td><td><select data-mp="align" data-k="' + k + '"><option value="fixed"' + (m.align === "fixed" ? " selected" : "") +
          '>still camera (the body moves)</option><option value="track"' + (m.align === "track" ? " selected" : "") + '>follow her (on the spot)</option></select></td><td><input data-mp="take_of" data-k="' + k + '" value="' + esc(m.take_of || "") +
          '" placeholder="(a move she has)" style="width:110px"></td><td><button class="btn quiet small" data-mpdel="' + k + '">✕</button></td></tr>').join("") +
        '</table><div class="row"><button class="btn quiet" id="av-mpadd">+ Add a move</button><button class="btn" id="av-mpstore">Store these moves</button></div>';
        $("#av-moveplan", el).querySelectorAll("[data-mp]").forEach(x => x.onchange = () => { const m = plan[+x.dataset.k], f2 = x.dataset.mp;
          m[f2] = f2 === "words" ? x.value.split(",").map(w => w.trim()).filter(Boolean) : f2 === "from" || f2 === "to" ? Number(x.value) : x.value; });
        $("#av-moveplan", el).querySelectorAll("[data-mpdel]").forEach(x => x.onclick = () => { plan.splice(+x.dataset.mpdel, 1); draw(); });
        $("#av-mpadd", el).onclick = () => { const last = plan[plan.length - 1]; plan.push({ name: "move " + (plan.length + 1), words: [], from: last ? last.to : 0, to: (last ? last.to : 0) + 1, align: "fixed" }); draw(); };
        $("#av-mpstore", el).onclick = async () => {
          try { for (const m of plan) await avMotionStore(a.id, A, Object.assign({}, m, { slug: m.name }), note); await avAnatomyLearn(a.id, A); toast(plan.length + " move(s) stored."); avSelect(el, a.id); }
          catch (e) { note("Could not store: " + e.message); } finally { URL.revokeObjectURL(A.v.src); }
        };
      };
      draw();
    };
    $("#av-moves", el).querySelectorAll("[data-avmovedel]").forEach(b => b.onclick = async () => { if (confirm("Remove this move?")) { await api("/api/avatars/motion_delete", { id: a.id, slug: b.dataset.avmovedel }); avSelect(el, a.id); } });
  }
  if (!AV.face) AV.face = new TalkingFace($("#av-stage", el));
  await AV.face.setMode("avatar", { avatar: { imageUrl: "/api/avatars/image?id=" + a.id, landmarks: a.landmarks, label: a.label, body: a.kind === "body", turnId: (a.motions || []).length ? a.id : null } });
  el.querySelectorAll("[data-avmove]").forEach(b => b.onclick = () => AV.face.impl && AV.face.impl.playMove && AV.face.impl.playMove(b.dataset.avmove));
  if (AV.audio && AV.motion) AV.face.attach(AV.audio, { visemes: [], motion: AV.motion });   // the same speech carries on, on the new face
  const fq = AV.face.impl && AV.face.impl.quality;
  if (fq) { $("#av-info", el).insertAdjacentHTML("beforeend", '<div class="small ' + (fq.ok ? "" : "note warn") + '">' + esc(avQcText(fq)) + "</div>"); api("/api/avatars/qc", { id: a.id, qc: fq }).catch(() => {}); }
  const ft = AV.face.impl && AV.face.impl.fit;
  if (ft) $("#av-info", el).insertAdjacentHTML("beforeend", '<div class="small muted">Mouth fit (from this face): mouth ' + ft.mouth_mm + " mm wide, lips " + ft.upper_lip_mm + " / " + ft.lower_lip_mm +
    " mm, opens about " + ft.aa_open_mm + ' mm on "aa", teeth show ≤ ' + ft.teeth_mm.toFixed(1) + " mm · scale from the " + ft.scale_from + "</div>");
  avChannels(el);
  if (window.rvStudio) rvStudio(el, a).catch(e => console.warn("review:", e));   // flags, reference clips, reproduce & compare, learning
}

function avChannels(el) {
  const groups = { "Eyes and gaze": /^eye/, "Jaw": /^jaw/, "Mouth": /^mouth/, "Brows, cheeks, nose, tongue": /^(brow|cheek|nose|tongue)/ };
  $("#av-ch", el).innerHTML = Object.entries(groups).map(([g, re]) => "<details" + (g === "Mouth" ? " open" : "") + '><summary class="small"><b>' + g + "</b></summary>" +
    window.ARKIT52.filter(k => re.test(k)).map(k => '<label class="small" style="display:inline-flex;align-items:center;gap:4px;width:250px">' +
      '<span style="width:140px">' + k + '</span><input type="range" min="0" max="1" step="0.01" value="0" data-ch="' + k + '"></label>').join("") + "</details>").join("");
  el.querySelectorAll("input[data-ch]").forEach(r => r.oninput = () => {
    if (!AV.face || !AV.face.impl) return;
    if (AV.audio) AV.audio.pause();
    cancelAnimationFrame(AV.face.raf);
    const v = {}; el.querySelectorAll("input[data-ch]").forEach(x => { v[x.dataset.ch] = Number(x.value); });
    AV.face.impl.setChannels(v);
  });
}

const AV_PRESETS = {
  neutral: {}, smile: { mouthSmileLeft: 0.8, mouthSmileRight: 0.8, cheekSquintLeft: 0.5, cheekSquintRight: 0.5, eyeSquintLeft: 0.4, eyeSquintRight: 0.4, mouthDimpleLeft: 0.3, mouthDimpleRight: 0.3 },
  surprise: { jawOpen: 0.45, browInnerUp: 0.8, browOuterUpLeft: 0.7, browOuterUpRight: 0.7, eyeWideLeft: 0.7, eyeWideRight: 0.7, mouthFunnel: 0.3 },
  "say O": { jawOpen: 0.35, mouthFunnel: 0.6, mouthPucker: 0.3 }, "say EE": { jawOpen: 0.1, mouthStretchLeft: 0.5, mouthStretchRight: 0.5, mouthSmileLeft: 0.3, mouthSmileRight: 0.3 },
  "say TH": { jawOpen: 0.15, tongueOut: 0.6 }, blink: { eyeBlinkLeft: 1, eyeBlinkRight: 1 }, "look left": { eyeLookOutRight: 0.8, eyeLookInLeft: 0.8 },
  sad: { mouthFrownLeft: 0.6, mouthFrownRight: 0.6, browInnerUp: 0.6, mouthShrugLower: 0.3 }, frown: { browDownLeft: 0.8, browDownRight: 0.8, noseSneerLeft: 0.3, noseSneerRight: 0.3, mouthPressLeft: 0.4, mouthPressRight: 0.4 },
};

async function avSpeak(el) {
  if (!AV.sel || !AV.face) return toast("Choose an analysed avatar first.");
  const text = $("#av-text", el).value.trim();
  if (!text) return toast("Type what the avatar should say.");
  const note = $("#av-note", el), t0 = performance.now();
  note.textContent = "Speaking and working out 52 face channels…";
  const body = { id: AV.sel.id, text, profile: typeof SP !== "undefined" && SP.profile ? { emotion: SP.profile.emotion, lang: SP.profile.lang } : {} };
  if (!AV.sel.voice && $("#sp-engine") && $("#sp-engine").value) { body.engine = $("#sp-engine").value; body.voice = ($("#sp-voice") || {}).value || ""; }
  const r = await api("/api/avatars/speak", body);
  const res = await avWaitJob(r.job.job_id, m => { note.textContent = "Face motion: " + m; });
  if (AV.audio) AV.audio.pause();
  const a = document.createElement("audio"); a.controls = true; a.src = "/api/speech/audio?name=" + encodeURIComponent(r.audio);
  $("#av-player", el).innerHTML = ""; $("#av-player", el).appendChild(a); AV.audio = a;
  const blob = new Blob([res.arkit52_csv], { type: "text/csv" });
  $("#av-player", el).insertAdjacentHTML("beforeend", ' <a class="small" download="avatar-arkit52.csv" href="' + URL.createObjectURL(blob) + '">52-channel CSV</a>');
  AV.motion = res.motion;
  AV.face.attach(a, { visemes: [], motion: res.motion });
  a.play().catch(() => {});
  note.textContent = res.motion.frames.length + " frames × 52 channels at " + res.motion.fps + " fps · voice: " + r.engine_used + " · " + ((performance.now() - t0) / 1000).toFixed(1) + " s";
  if (window.rvAttach) { const sel = AV.sel; rvAttach($("#av-player", el), AV.face, { avatarId: () => sel.id, text, audio: a }); }
}

// Play the speech while the faces take turns, so each one can be seen speaking.
async function avTour(el) {
  const faces = AV.list.filter(a => a.analysed && !a.hidden);
  if (!faces.length) return toast("Analyse the faces first.");
  if (!AV.audio || !AV.motion) await avSpeak(el);
  if (!AV.audio) return;
  const btn = $("#av-tour", el), a = AV.audio, step = Math.max(1.2, Math.min(3, a.duration / Math.min(faces.length, 8) || 2));
  AV.touring = !AV.touring;
  btn.textContent = AV.touring ? "■ Stop" : "🎭 Every face in turn";
  if (!AV.touring) return;
  let i = Math.max(0, faces.findIndex(f => AV.sel && f.id === AV.sel.id));
  a.loop = true; a.currentTime = 0; a.play().catch(() => {});
  while (AV.touring && $("#av-tour", el)) {
    await new Promise(r => setTimeout(r, step * 1000));
    if (!AV.touring) break;
    i = (i + 1) % faces.length;
    await avSelect(el, faces[i].id);
  }
  a.loop = false;
}

async function renderAvatars(el) {
  if (!el.dataset.ready) {
    el.dataset.ready = "1";
    el.innerHTML =
      '<div class="card" id="av-studio" hidden><h2>Avatar studio <span class="small muted">click a face to try it — speech keeps playing on the new face</span></h2><div id="av-faces"></div><div class="row"><input id="av-name" type="text" aria-label="Name"><input id="av-tags" class="grow" type="text" placeholder="tags, comma separated" aria-label="Tags">' +
      '<button class="btn quiet" id="av-save">Save</button><button class="btn quiet" id="av-voice">Give it the Speak tab\'s current voice</button><button class="btn quiet" id="av-del">Delete</button></div><div id="av-info"></div>' +
      '<div class="grid2"><div><div id="av-stage" style="max-width:440px"></div><div id="av-player" class="row"></div><p class="small muted" id="av-note"></p></div>' +
      '<div><textarea id="av-text" rows="3" aria-label="What the avatar says">Hello! I can speak any text you give me, with natural lips, eyes and expressions.</textarea>' +
      '<div class="row"><button class="btn bigbtn" id="av-speak">🗣 Speak</button><button class="btn" id="av-tour">🎭 Every face in turn</button></div>' +
      '<p class="small"><b>Try an expression:</b> ' + Object.keys(AV_PRESETS).map(k => '<button class="btn quiet small" data-avp="' + k + '">' + k + "</button>").join(" ") + "</p>" +
      '<p class="small muted">The 52 face channels — move any slider to see what it does:</p><div id="av-ch"></div></div></div></div>' +
      '<div class="card"><h2>Avatar library</h2><p class="small muted">Portraits become talking avatars. Each portrait is measured at 478 points with depth; when the avatar speaks, ' +
      "the Visual Speech Engine drives <b>all 52 face channels</b> (jaw, lips, cheeks, nose, eyelids, eye direction, brows, tongue) with natural co-articulation, blinks and head motion, and the head turns in 3D. " +
      "Only portraits that show nobody real (AI-generated), or a real person who agreed, can be added — every avatar is labelled as synthetic.</p>" +
      '<div class="row small"><label><input type="radio" name="av-src" value="synthetic" checked> AI-generated portraits (no real person)</label>' +
      '<label><input type="radio" name="av-src" value="consented"> A real person who agreed</label></div>' +
      '<div class="row small" id="av-syn"><label><input type="checkbox" id="av-attest"> I confirm these portraits are AI-generated and show no real person.</label></div>' +
      '<div class="row small" id="av-con" hidden><input id="av-subject" type="text" placeholder="the person\'s name" aria-label="Person"><label><input type="checkbox" id="av-consent"> They agreed to become an avatar (consent)</label></div>' +
      '<div class="row"><input id="av-files" type="file" accept="image/png,image/jpeg,image/webp" multiple aria-label="Portraits"><span class="small muted">or a folder / .zip on this computer</span>' +
      '<input id="av-path" class="grow" type="text" placeholder="/path/to/portraits.zip" aria-label="Folder or zip">' +
      '<label class="small"><input type="checkbox" id="av-body"> full-body photos (keep the whole figure)</label><button class="btn" id="av-import">Import</button>' +
      '<button class="btn quiet" id="av-analyse">Analyse faces</button><button class="btn quiet" id="av-checkall">Check movement of every face</button></div><div class="small" id="av-msg" aria-live="polite"></div>' +
      '<div id="av-grid" style="margin-top:8px"></div></div>';
    el.querySelectorAll('input[name="av-src"]').forEach(r => r.onchange = () => {
      const syn = el.querySelector('input[name="av-src"]:checked').value === "synthetic";
      $("#av-syn", el).hidden = !syn; $("#av-con", el).hidden = syn;
    });
    $("#av-import", el).onclick = async () => {
      const source = el.querySelector('input[name="av-src"]:checked').value, attest = $("#av-attest", el).checked, kind = $("#av-body", el).checked ? "body" : "face";
      let r;
      if (source === "consented") {
        const fs = [...$("#av-files", el).files];
        if (!fs.length) return toast("Choose the person's portrait.");
        let added = 0;
        for (const f of fs) {
          const data = await new Promise(res => { const rd = new FileReader(); rd.onload = () => res(rd.result); rd.readAsDataURL(f); });
          const x = await api("/api/avatars/add", { data_b64: data, filename: f.name, source, subject: $("#av-subject", el).value, consent: $("#av-consent", el).checked, tags: kind === "body" ? ["body"] : [] });
          if (!x.duplicate) added++;
        }
        r = { added, duplicates: fs.length - added, failed: [] };
      } else if ($("#av-path", el).value.trim()) {
        r = await api("/api/avatars/import", { path: $("#av-path", el).value.trim(), source, attest, kind });
      } else {
        const fs = [...$("#av-files", el).files];
        if (!fs.length) return toast("Choose portraits, or give a folder or .zip.");
        const files = await Promise.all(fs.map(f => new Promise(res => { const rd = new FileReader(); rd.onload = () => res({ name: f.name, data_b64: rd.result }); rd.readAsDataURL(f); })));
        r = await api("/api/avatars/import", { files, source, attest, kind });
      }
      $("#av-msg", el).textContent = "Added " + r.added + (r.duplicates ? ", " + r.duplicates + " already in the library" : "") + (r.failed.length ? ", " + r.failed.length + " skipped" : "") + ".";
      await avRefresh(el);
      if (r.added) await avAnalyse(el, false);
    };
    $("#av-analyse", el).onclick = () => avAnalyse(el, true);
    $("#av-checkall", el).onclick = () => avCheckAll(el).catch(e => { $("#av-msg", el).textContent = "Check failed: " + e.message; });
    $("#av-grid", el).onclick = e => { const t = e.target.closest("[data-av]"); if (t) avSelect(el, Number(t.dataset.av)); };
    $("#av-save", el).onclick = async () => { await api("/api/avatars/update", { id: AV.sel.id, name: $("#av-name", el).value, tags: $("#av-tags", el).value.split(",").map(s => s.trim()).filter(Boolean) }); avRefresh(el); toast("Saved."); };
    $("#av-voice", el).onclick = async () => {
      if (!$("#sp-engine") || !$("#sp-engine").value) return toast("Choose a voice on the Speak tab first.");
      await api("/api/avatars/update", { id: AV.sel.id, voice: { engine: $("#sp-engine").value, voice: ($("#sp-voice") || {}).value || "", model: ($("#sp-model") || {}).value || "", lang: (typeof SP !== "undefined" && SP.profile && SP.profile.lang) || "en" } });
      toast("This avatar now speaks with that voice."); avSelect(el, AV.sel.id);
    };
    $("#av-del", el).onclick = async () => { if (!confirm("Delete this avatar and its portrait?")) return; await api("/api/avatars/delete", { id: AV.sel.id }); AV.sel = null; $("#av-studio", el).hidden = true; avRefresh(el); };
    $("#av-tour", el).onclick = () => avTour(el).catch(e => { $("#av-note", el).textContent = "Could not speak: " + e.message; });
    $("#av-speak", el).onclick = () => avSpeak(el).catch(e => { $("#av-note", el).textContent = "Could not speak: " + e.message; });
    el.addEventListener("click", e => {
      const b = e.target.closest("[data-avp]");
      if (!b || !AV.face || !AV.face.impl) return;
      if (AV.audio) AV.audio.pause();
      cancelAnimationFrame(AV.face.raf);
      const v = Object.fromEntries(window.ARKIT52.map(k => [k, 0]));
      Object.assign(v, AV_PRESETS[b.dataset.avp]);
      el.querySelectorAll("input[data-ch]").forEach(x => { x.value = v[x.dataset.ch] || 0; });
      AV.face.impl.setChannels(v);
    });
  }
  await avRefresh(el);
  if (!AV.sel) {                                       // open the studio straight away on the remembered (or first) face
    const ready = AV.list.filter(a => a.analysed), want = typeof faceChoice === "function" ? Number(faceChoice()) : 0;
    const pick = ready.find(a => a.id === want) || ready[0];
    if (pick) await avSelect(el, pick.id);
  }
}
