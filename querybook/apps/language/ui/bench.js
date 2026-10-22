// Calibration bench (Avatar studio): her original clip and our face speaking the same voice, side by side, on this computer.
// Three columns: the original, our face with the approved calibration, our face with a trial calibration you set with the
// sliders. Each column: the face, a level same-scale mouth close-up with the tracked lip outline (and her outline laid over
// ours), and live numbers. Play at full, half or quarter speed, step frames, jump to the worst words, record the
// comparison as a video. The trial goes to the Quality Lab only as a candidate — the admin approves it there.
"use strict";
const BN = { lm: null };
const BN_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185];
const BN_INNER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191];
const BN_COL = ["#3c8ceb", "#f06e37", "#23be87"];
const BN_NAME = ["Original", "Approved calibration", "Trial calibration"];
const BN_HELP = { jaw: "mouth opening (jaw and lower lip)", spread: "smile and width", round: "rounding (oo, oh, w)", rest_round: "rounding at rest (takes the photo's smile out)",
  close: "lip closure (p, b, m)", arch: "upper-lip lift", teeth: "teeth", smooth_ms: "smoothing (ms)", lead_ms: "lips ahead of the sound (ms)",
  head: "head movement", brow: "brows", sway: "body sway", breath: "breathing" };

// a face tracker for single pictures (the three columns are different faces: no frame-to-frame tracking between them)
async function bnTracker() {
  if (BN.lm) return BN.lm;
  const vision = await import("./vendor/mediapipe/vision_bundle.mjs");
  const files = await vision.FilesetResolver.forVisionTasks("vendor/mediapipe/wasm");
  const opts = d => ({ baseOptions: { modelAssetPath: "vendor/mediapipe/face_landmarker.task", delegate: d }, runningMode: "IMAGE", numFaces: 1 });
  try { BN.lm = await vision.FaceLandmarker.createFromOptions(files, opts("GPU")); }
  catch (e) { BN.lm = await vision.FaceLandmarker.createFromOptions(files, opts("CPU")); }
  return BN.lm;
}
// geometry of one tracked frame, in face units: 1 = the distance between the eye centres, eyes level, origin under the nose
function bnGeom(L, W, H) {
  const P = i => [L[i].x * W, L[i].y * H], mid = (a, b) => [(P(a)[0] + P(b)[0]) / 2, (P(a)[1] + P(b)[1]) / 2];
  const e1 = mid(33, 133), e2 = mid(263, 362), iod = Math.hypot(e2[0] - e1[0], e2[1] - e1[1]) || 1, ang = Math.atan2(e2[1] - e1[1], e2[0] - e1[0]), o = P(2);
  const c = Math.cos(-ang), s = Math.sin(-ang);
  const F = i => { const p = P(i), dx = p[0] - o[0], dy = p[1] - o[1]; return [(dx * c - dy * s) / iod, (dx * s + dy * c) / iod]; };
  const outer = BN_OUTER.map(F), inner = BN_INNER.map(F), l = F(61), r = F(291), up = F(13), lo = F(14);
  return { iod, ang, o, nose: P(1), outer, inner, width: Math.hypot(r[0] - l[0], r[1] - l[1]), open: Math.max(0, lo[1] - up[1]), lift: (l[1] + r[1]) / 2 - up[1] };
}
async function bnJpeg(src, W, H) {
  const k = Math.min(1, 900 / W), c = document.createElement("canvas"); c.width = Math.round(W * k); c.height = Math.round(H * k);
  c.getContext("2d").drawImage(src, 0, 0, c.width, c.height);
  return await new Promise(r => c.toBlob(r, "image/jpeg", 0.88));
}
// one column: every frame's picture (JPEG) and its tracked geometry
async function bnReadVideo(v, fps, dur, note) {
  const lm = await bnTracker(), W = v.videoWidth, H = v.videoHeight, c = document.createElement("canvas"); c.width = W; c.height = H;
  const g = c.getContext("2d"), seek = t => new Promise(r => { v.onseeked = r; v.currentTime = t; }), out = [];
  for (let i = 0; i < Math.round(dur * fps); i++) {
    await seek(i / fps); g.drawImage(v, 0, 0);
    const res = lm.detect(c), L = res.faceLandmarks && res.faceLandmarks[0];
    out.push({ img: await bnJpeg(c, W, H), srcW: W, g: L ? bnGeom(L, W, H) : null });
    if (i % 12 === 0) note("Reading the original: frame " + i + " of " + Math.round(dur * fps));
  }
  return out;
}
async function bnReadFace(a, cal, track, fps, dur, note, label) {
  const lm = await bnTracker(), f = await rvFaceFor(a, cal), out = [];
  try {
    f.director = false; if (f.body && f.closeUp) f.closeUp(true);
    for (let i = 0; i < Math.round(dur * fps); i++) {
      f.frame(track, i / fps);
      const W = f.cv.width, H = f.cv.height, res = lm.detect(f.cv), L = res.faceLandmarks && res.faceLandmarks[0];
      out.push({ img: await bnJpeg(f.cv, W, H), srcW: W, g: L ? bnGeom(L, W, H) : null });
      if (i % 12 === 0) { note("Rendering " + label + ": frame " + i + " of " + Math.round(dur * fps)); await new Promise(r => setTimeout(r, 0)); }
    }
  } finally { f.dispose(); f._host.remove(); }
  return out;
}
// per column: the upper-lip lift is measured from that face's own closed mouth (the average of its most-closed tenth)
function bnFinish(col) {
  const ok = col.filter(x => x.g), closed = ok.slice().sort((x, y) => x.g.open - y.g.open).slice(0, Math.max(1, Math.round(ok.length / 10)));
  const rest = closed.reduce((s, x) => s + x.g.lift, 0) / closed.length;
  ok.forEach(x => { x.g.upper = x.g.lift - rest; });
  const xs = ok.map(x => x.g.nose[0]), ys = ok.map(x => x.g.nose[1]), io = ok.map(x => x.g.iod), m = a => a.reduce((s, v) => s + v, 0) / Math.max(1, a.length);
  col.crop = { x: m(xs), y: m(ys), iod: m(io) };                     // a fixed crop: the head's own movement shows
  return col;
}
// how close a column is to the original, frame by frame and word by word
function bnScore(cols, k, words, fps) {
  const O = cols[0], C = cols[k], pairs = O.map((o, i) => [o.g, C[i] && C[i].g]).filter(p => p[0] && p[1]);
  const m = a => a.reduce((s, v) => s + v, 0) / Math.max(1, a.length), d = key => m(pairs.map(p => Math.abs(p[1][key] - p[0][key])));
  const corr = key => { const a = pairs.map(p => p[0][key]), b = pairs.map(p => p[1][key]), ma = m(a), mb = m(b);
    const n = a.reduce((s, v, i) => s + (v - ma) * (b[i] - mb), 0), da = Math.sqrt(a.reduce((s, v) => s + (v - ma) ** 2, 0)), db = Math.sqrt(b.reduce((s, v) => s + (v - mb) ** 2, 0));
    return da && db ? n / (da * db) : 0; };
  const W = (words || []).map(w => { const ix = []; for (let i = Math.floor(w.start * fps); i <= Math.ceil(w.end * fps); i++) if (O[i] && O[i].g && C[i] && C[i].g) ix.push(i);
    if (!ix.length) return null;
    const dd = key => m(ix.map(i => Math.abs(C[i].g[key] - O[i].g[key])));
    const err = dd("width") / 0.06 + dd("open") / 0.05 + dd("upper") / 0.03;
    return { word: w.word, start: w.start, end: w.end, match: Math.max(0, Math.round(100 - 10 * err)), dw: dd("width"), dop: dd("open"), du: dd("upper") }; }).filter(Boolean);
  return { width: d("width"), open: d("open"), upper: d("upper"), corr: corr("open"), wcorr: corr("width"), words: W,
    match: W.length ? Math.round(m(W.map(w => w.match))) : null };
}

async function bnSection(box, a) {
  box.innerHTML = '<h4 style="margin:8px 0 4px">Calibration bench <span class="muted">(side by side with her original clip — calibrate on this computer)</span></h4>' +
    '<div class="row"><input type="file" accept="video/*" data-bnfile aria-label="Her original clip"><input data-bnwords placeholder="the words spoken in the clip" style="flex:1">' +
    '<button class="btn quiet" data-bnstt>Transcribe</button></div><div class="row"><label class="small">Frames per second <select data-bnfps><option>12</option><option selected>24</option></select></label>' +
    '<button class="btn" data-bngo>Build the side-by-side</button><span class="muted" data-bnn></span></div><div data-bnout></div>';
  const note = m => { box.querySelector("[data-bnn]").textContent = m; };
  box.querySelector("[data-bnstt]").onclick = async () => { const f = box.querySelector("[data-bnfile]").files[0]; if (!f) return toast("Choose her clip first.");
    try { note("Transcribing…"); const st = await api("/api/speech/transcribe-file", { audio_b64: await rvWav(f), lang: "en", mode: "auto" }); let res;
      for (let i = 0; i < 240; i++) { res = await api("/api/speech/transcribe-status?task=" + encodeURIComponent(st.task)); if (res.state !== "running") break; await new Promise(r => setTimeout(r, 1000)); }
      box.querySelector("[data-bnwords]").value = (res && res.result && res.result.transcript) || ""; note("Transcribed — check the words."); }
    catch (e) { note("Transcription is not available (" + e.message + ") — type the words."); } };
  box.querySelector("[data-bngo]").onclick = async () => {
    const f = box.querySelector("[data-bnfile]").files[0], words = box.querySelector("[data-bnwords]").value.trim(), fps = +box.querySelector("[data-bnfps]").value;
    if (!f) return toast("Choose her clip first."); if (!words) return toast("Type (or transcribe) the words spoken in the clip first.");
    try { await bnBuild(box.querySelector("[data-bnout]"), a, f, words, fps, note); } catch (e) { note("Could not build: " + e.message); console.error(e); }
  };
}

async function bnBuild(out, a, file, words, fps, note) {
  note("Taking the clip's own voice…");
  const job = await api("/api/vse/lip_sync", { audio_b64: await rvWav(file), text: words, lang: "en" }), res = await avWaitJob(job.job_id, note);
  const track = { visemes: [], motion: res.motion, words: res.words };
  const v = document.createElement("video"); v.playsInline = true; v.preload = "auto"; v.src = URL.createObjectURL(await rvPlayable(file));
  await new Promise((ok, bad) => { v.onloadeddata = ok; v.onerror = () => bad(new Error("this video cannot be played here")); });
  const dur = Math.min(v.duration || 0, 60);
  const calInfo = await api("/api/qlab/calibration"), approved = Object.assign({}, (await api("/api/qlab/active")).params);
  const S = { a, v, fps, dur, track, words: res.words || [], approved, trial: Object.assign({}, approved), bounds: calInfo.bounds, cols: [], ghost: true, lines: true, file: file.name };
  v.muted = true;
  S.cols[0] = bnFinish(await bnReadVideo(v, fps, dur, note));
  S.cols[1] = bnFinish(await bnReadFace(a, approved, track, fps, dur, note, "the approved calibration"));
  S.cols[2] = S.cols[1];                                             // the trial starts as the approved calibration
  v.muted = false; v.currentTime = 0;
  bnUi(out, S, note);
  note("Ready — play it, or move a slider and press Re-render the trial.");
}

function bnUi(out, S, note) {
  const keys = Object.keys(S.bounds).filter(k => S.a.kind === "body" || (k !== "sway" && k !== "breath"));
  out.innerHTML = '<canvas data-bncv width="1440" height="880" style="width:100%;max-width:1440px;background:#111317;border-radius:6px"></canvas>' +
    '<div class="row"><button class="btn" data-bnplay>▶ Play</button><button class="btn quiet" data-bnprev title="one frame back">◀</button><button class="btn quiet" data-bnnext title="one frame on">▶|</button>' +
    '<label class="small">Speed <select data-bnrate><option value="1">1×</option><option value="0.5">½×</option><option value="0.25">¼×</option></select></label>' +
    '<input type="range" data-bnscrub min="0" max="' + (S.cols[0].length - 1) + '" value="0" style="flex:1" aria-label="Frame">' +
    '<label class="small"><input type="checkbox" data-bnghost checked> her outline over ours</label><label class="small"><input type="checkbox" data-bnlines checked> outlines</label></div>' +
    '<div class="row"><button class="btn quiet" data-bnrec>● Record this comparison</button><label class="small">as <select data-bnfmt><option value="webm">WebM</option><option value="mp4">MP4 (ffmpeg)</option></select></label>' +
    '<span class="muted" data-bnrecn></span></div>' +
    '<div class="row" style="align-items:flex-start;gap:24px"><div style="flex:1;min-width:300px"><b>Trial calibration</b> <span class="muted small">(the approved values are marked ┃)</span><div data-bnsl></div>' +
    '<div class="row"><button class="btn" data-bnrender>Re-render the trial</button><button class="btn quiet" data-bnreset>Back to approved</button>' +
    '<button class="btn quiet" data-bnsend>Send the trial to the Quality Lab</button></div></div><div style="flex:1;min-width:300px" data-bnscore></div></div><div data-bnwordsres></div>';
  const cv = out.querySelector("[data-bncv]"), g = cv.getContext("2d"), v = S.v, scrub = out.querySelector("[data-bnscrub]");
  const cache = new Map();
  const bmp = async blob => { if (!cache.has(blob)) { if (cache.size > 90) cache.delete(cache.keys().next().value); cache.set(blob, await createImageBitmap(blob)); } return cache.get(blob); };
  let drawing = false, want = 0;
  const draw = async i => {
    want = i; if (drawing) return; drawing = true;
    try { while (true) { const k = want; await bnDraw(g, S, k, bmp); if (want === k) break; } } finally { drawing = false; }
  };
  const frameNow = () => Math.max(0, Math.min(S.cols[0].length - 1, Math.round(v.currentTime * S.fps)));
  const loop = () => { if (v.paused && !S.rec) return; const i = frameNow(); scrub.value = i; draw(i); requestAnimationFrame(loop); };
  const play = out.querySelector("[data-bnplay]");
  play.onclick = () => { if (v.paused) { if (v.currentTime >= S.dur - 0.05) v.currentTime = 0; v.play(); play.textContent = "❚❚ Pause"; requestAnimationFrame(loop); } else { v.pause(); play.textContent = "▶ Play"; } };
  v.onpause = () => { play.textContent = "▶ Play"; draw(frameNow()); };
  v.ontimeupdate = () => { if (v.currentTime >= S.dur) v.pause(); };
  const goto = i => { v.pause(); i = Math.max(0, Math.min(S.cols[0].length - 1, i)); v.currentTime = (i + 0.01) / S.fps; scrub.value = i; draw(i); };
  out.querySelector("[data-bnprev]").onclick = () => goto(frameNow() - 1);
  out.querySelector("[data-bnnext]").onclick = () => goto(frameNow() + 1);
  scrub.oninput = () => goto(+scrub.value);
  out.querySelector("[data-bnrate]").onchange = e => { v.playbackRate = +e.target.value; v.preservesPitch = true; };
  out.querySelector("[data-bnghost]").onchange = e => { S.ghost = e.target.checked; draw(frameNow()); };
  out.querySelector("[data-bnlines]").onchange = e => { S.lines = e.target.checked; draw(frameNow()); };
  S.goto = goto;
  // sliders
  const sl = out.querySelector("[data-bnsl]");
  sl.innerHTML = keys.map(k => { const [lo, hi] = S.bounds[k], step = hi - lo > 20 ? 1 : 0.01, ap = S.approved[k] ?? 1;
    return '<div class="row small" style="gap:8px"><span style="width:250px">' + esc(BN_HELP[k] || k) + '</span><input type="range" data-bnk="' + k + '" min="' + lo + '" max="' + hi + '" step="' + step + '" value="' + S.trial[k] +
      '" style="flex:1;background:linear-gradient(90deg,transparent calc(' + ((ap - lo) / (hi - lo) * 100) + '% - 1px),#888 0 calc(' + ((ap - lo) / (hi - lo) * 100) + '% + 1px),transparent 0)">' +
      '<span data-bnv="' + k + '" style="width:60px;text-align:right">' + S.trial[k] + "</span></div>"; }).join("");
  sl.querySelectorAll("[data-bnk]").forEach(r => r.oninput = () => { S.trial[r.dataset.bnk] = +r.value; sl.querySelector('[data-bnv="' + r.dataset.bnk + '"]').textContent = r.value;
    sl.querySelector('[data-bnv="' + r.dataset.bnk + '"]').style.color = +r.value !== (S.approved[r.dataset.bnk] ?? 1) ? "#f06e37" : ""; });
  out.querySelector("[data-bnreset]").onclick = () => { S.trial = Object.assign({}, S.approved); S.cols[2] = S.cols[1]; bnUi(out, S, note); };
  out.querySelector("[data-bnrender]").onclick = async () => {
    const btn = out.querySelector("[data-bnrender]"); btn.disabled = true; v.pause();
    try { S.cols[2] = bnFinish(await bnReadFace(S.a, S.trial, S.track, S.fps, S.dur, note, "the trial")); cache.clear(); bnScores(out, S); draw(frameNow()); note("Trial re-rendered — compare the green column and the scores."); }
    catch (e) { note("Could not render the trial: " + e.message); } finally { btn.disabled = false; }
  };
  out.querySelector("[data-bnsend]").onclick = async () => {
    const changed = keys.filter(k => S.trial[k] !== (S.approved[k] ?? 1));
    if (!changed.length) return toast("The trial is the same as the approved calibration.");
    const s1 = bnScore(S.cols, 1, S.words, S.fps), s2 = bnScore(S.cols, 2, S.words, S.fps);
    const r = await api("/api/qlab/candidate", { params: S.trial, origin: "bench", note: "calibration bench on " + S.a.name + " with " + S.file + ": " + changed.map(k => k + " " + (S.approved[k] ?? 1) + " → " + S.trial[k]).join(", ") +
      " · word match " + s1.match + " → " + s2.match });
    toast("Candidate v" + r.version + " is waiting for the admin in the Quality Lab.");
  };
  // recording: the canvas as drawn, with the clip's own sound, played through once from the start
  out.querySelector("[data-bnrec]").onclick = async () => {
    const rn = out.querySelector("[data-bnrecn]"), fmt = out.querySelector("[data-bnfmt]").value;
    if (!window.MediaRecorder || !cv.captureStream) return toast("This browser cannot record — use Chrome or Edge.");
    const stream = cv.captureStream(30);
    try { const as = v.captureStream ? v.captureStream() : v.mozCaptureStream(); as.getAudioTracks().forEach(t => stream.addTrack(t)); } catch (e) { /* no sound: picture only */ }
    const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find(m => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8e6 }), parts = [];
    rec.ondataavailable = e => { if (e.data.size) parts.push(e.data); };
    const done = new Promise(r => { rec.onstop = r; });
    v.pause(); v.currentTime = 0; await new Promise(r => setTimeout(r, 200));
    S.rec = true; rec.start(250); rn.textContent = "Recording…"; v.play(); requestAnimationFrame(loop);
    await new Promise(r => { const t = setInterval(() => { if (v.paused || v.ended || v.currentTime >= S.dur - 0.02) { clearInterval(t); r(); } }, 100); });
    v.pause(); S.rec = false; rec.stop(); await done;
    let blob = new Blob(parts, { type: "video/webm" }), ext = "webm";
    if (fmt === "mp4") { rn.textContent = "Converting to MP4…";
      try { const r = await api("/api/media/convert", { file_b64: await agB64(blob), to: "mp4" }); blob = await (await fetch(r.b64)).blob(); ext = "mp4"; }
      catch (e) { toast("MP4 conversion failed (" + e.message + ") — saved as WebM."); } }
    const name = (S.a.name || "avatar").replace(/[^\w-]+/g, "-") + "-side-by-side-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + "." + ext;
    rn.innerHTML = '<a download="' + esc(name) + '" href="' + URL.createObjectURL(blob) + '">Save ' + esc(name) + "</a> (" + (blob.size / 1048576).toFixed(1) + " MB)";
  };
  bnScores(out, S);
  draw(0);
}

function bnScores(out, S) {
  const s1 = bnScore(S.cols, 1, S.words, S.fps), s2 = bnScore(S.cols, 2, S.words, S.fps), same = S.cols[2] === S.cols[1];
  const row = (name, a, b, better, f) => "<tr><td>" + name + "</td><td>" + f(a) + "</td><td>" + (same ? '<span class="muted">—</span>' : f(b) + (better(b, a) ? ' <span class="badge good">better</span>' : better(a, b) ? ' <span class="badge warn">worse</span>' : "")) + "</td></tr>";
  const lt = (x, y) => x < y * 0.97, gt = (x, y) => x > y + 0.02, f3 = x => x.toFixed(3), f2 = x => x.toFixed(2);
  out.querySelector("[data-bnscore]").innerHTML = '<b>How close to her</b> <span class="muted small">(face units: 1 = the distance between the eyes)</span><table class="t small"><tr><th></th><th>Approved</th><th>Trial</th></tr>' +
    row("Word match (0–100)", s1.match ?? 0, s2.match ?? 0, gt, x => String(x)) +
    row("Mouth width, average miss", s1.width, s2.width, lt, f3) + row("Opening, average miss", s1.open, s2.open, lt, f3) + row("Upper-lip lift, average miss", s1.upper, s2.upper, lt, f3) +
    row("Opening follows hers (correlation)", s1.corr, s2.corr, gt, f2) + row("Width follows hers (correlation)", s1.wcorr, s2.wcorr, gt, f2) + "</table>";
  const W = (same ? s1 : s2).words.slice().sort((x, y) => x.match - y.match);
  const box = out.querySelector("[data-bnwordsres]");
  box.innerHTML = '<b class="small">Words, worst first (' + (same ? "approved" : "trial") + ')</b> <span class="muted small">— click to jump there</span><div class="row" style="flex-wrap:wrap;gap:6px">' +
    W.map((w, i) => '<button class="btn quiet small" data-bnw="' + i + '" title="width miss ' + w.dw.toFixed(3) + ", opening miss " + w.dop.toFixed(3) + ", upper-lip miss " + w.du.toFixed(3) + '">' + esc(w.word) +
      ' <span class="badge ' + (w.match >= 80 ? "good" : w.match >= 60 ? "warn" : "bad") + '">' + w.match + "</span></button>").join("") + "</div>";
  box.querySelectorAll("[data-bnw]").forEach(b => b.onclick = () => { const w = W[+b.dataset.bnw]; S.goto(Math.round((w.start + w.end) / 2 * S.fps)); });
}

async function bnDraw(g, S, i, bmp) {
  const CW = 480, TOP = 400, MH = 300, MZ = 230, MO = [240, 34], t = i / S.fps;
  g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = "#111317"; g.fillRect(0, 0, 1440, 880);
  const her = S.cols[0][i] && S.cols[0][i].g;
  for (let c = 0; c < 3; c++) {
    const col = S.cols[c], fr = col[i]; if (!fr) continue;
    const img = await bmp(fr.img), sc = img.width / fr.srcW;          // pictures are stored downscaled: geometry is in source pixels
    const x0 = c * CW;
    // top: the face, a fixed crop
    const cr = col.crop, half = Math.min(1.95 * cr.iod * sc, img.height / 2), halfW = half * CW / TOP;
    const cx = Math.min(Math.max(cr.x * sc, halfW), img.width - halfW), cy = Math.min(Math.max(cr.y * sc, half), img.height - half);
    g.save(); g.beginPath(); g.rect(x0, 0, CW, TOP); g.clip();
    g.drawImage(img, cx - halfW, cy - half, 2 * halfW, 2 * half, x0, 0, CW, TOP); g.restore();
    // bottom: the mouth, level, same scale in every column
    g.save(); g.beginPath(); g.rect(x0, TOP, CW, MH); g.clip(); g.fillStyle = "#111317"; g.fillRect(x0, TOP, CW, MH);
    if (fr.g) {
      const k = MZ / (fr.g.iod * sc);
      g.translate(x0 + MO[0], TOP + MO[1]); g.rotate(-fr.g.ang); g.scale(k, k); g.translate(-fr.g.o[0] * sc, -fr.g.o[1] * sc);
      g.drawImage(img, 0, 0); g.setTransform(1, 0, 0, 1, 0, 0);
      const pt = q => [x0 + MO[0] + q[0] * MZ, TOP + MO[1] + q[1] * MZ];
      const loop = (pts, color, w, dash) => { g.beginPath(); pts.forEach((q, j) => { const p = pt(q); j ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); }); g.closePath();
        g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash || []); g.stroke(); g.setLineDash([]); };
      if (S.ghost && c > 0 && her) { loop(her.outer, "rgba(80,150,255,.95)", 3); loop(her.inner, "rgba(80,150,255,.95)", 2); }
      if (S.lines) { loop(fr.g.outer, BN_COL[c], 2); loop(fr.g.inner, BN_COL[c], 2, [5, 3]); }
    }
    g.restore();
    // labels and numbers
    g.fillStyle = "rgba(17,19,23,.82)"; g.fillRect(x0, 0, CW, 34); g.fillRect(x0, TOP, CW, 26);
    g.fillStyle = BN_COL[c]; g.beginPath(); g.arc(x0 + 16, 17, 7, 0, 7); g.fill();
    g.fillStyle = "#f0f0f0"; g.font = "bold 19px system-ui, sans-serif"; g.fillText(BN_NAME[c], x0 + 30, 24);
    g.font = "13px system-ui, sans-serif"; g.fillStyle = "#b8c4dc";
    g.fillText(c ? (S.ghost ? "blue = her lips, same scale, under our nose" : "mouth, level, same scale") : "mouth, level, same scale for all", x0 + 12, TOP + 18);
    g.font = "15px ui-monospace, Menlo, Consolas, monospace";
    const items = [["width", "width"], ["open ", "open"], ["upper", "upper"]], lim = { width: 0.06, open: 0.05, upper: 0.03 };
    items.forEach(([lab, key], j) => {
      const val = fr.g ? fr.g[key] : null, ref = her ? her[key] : null;
      let txt = lab + " " + (val === null || val === undefined ? "  —" : val.toFixed(2)), colr = "#dcdcdc";
      if (c && val !== null && val !== undefined && ref !== null && ref !== undefined) { const d = val - ref; txt += " (" + (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(2) + ")"; colr = Math.abs(d) > lim[key] ? "#ff7864" : "#96dca0"; }
      g.fillStyle = colr; g.fillText(txt, x0 + 16, TOP + MH + 24 + j * 22);
    });
    if (c) { g.fillStyle = "#111317"; g.fillRect(x0, 0, 3, TOP + MH + 76); }
  }
  // the words
  const y0 = 800; g.fillStyle = "#1a1d23"; g.fillRect(0, y0 - 14, 1440, 880 - y0 + 14);
  const W = S.words, cur = W.find(w => w.start <= t && t < w.end), nxt = cur || W.find(w => w.start > t) || W[W.length - 1];
  let x = 20; const ci = W.indexOf(nxt);
  W.forEach((w, j) => { if (j < ci - 4 || j > ci + 8) return; const on = w === cur; g.font = on ? "bold 30px system-ui, sans-serif" : "19px system-ui, sans-serif";
    const tw = g.measureText(w.word).width; if (x + tw > 1180) return; g.fillStyle = on ? "#fff" : "#7c838e"; g.fillText(w.word, x, y0 + 32); x += tw + 16; });
  g.font = "15px ui-monospace, Menlo, Consolas, monospace"; g.fillStyle = "#c8c8c8"; g.fillText("t = " + t.toFixed(2) + " s   frame " + i, 1220, y0 + 20);
  g.fillStyle = "#8a919c"; g.fillText("QueryBook " + (window.QB_VERSION || ""), 1220, y0 + 44);
}

window.bnSection = bnSection;
