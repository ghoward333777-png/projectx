"use strict";
// Face & video: camera / screen / file capture, face tracking (MediaPipe Face Landmarker, bundled),
// live capture quality, sync check and lip-reading (worked out on this computer by lipread.py), overdub.
const VD = { lm: null, lmLoading: null, stream: null, src: null, blob: null, kind: "", rec: null, chunks: [], live: false,
  frames: [], fpsT: [], lastLight: 0.5, avatar: null, recT0: 0, lastDub: null };
const LM = { forehead: 10, chin: 152, nose: 1, cheekL: 234, cheekR: 454, mouthL: 61, mouthR: 291, lipTop: 13, lipBot: 14 };
const CLASS_COLORS = { P: "#7c3aed", F: "#db2777", W: "#2563eb", A: "#dc2626", E: "#f59e0b", T: "#16a34a", "-": "#cbd5e1" };

function vdLog(what, detail, status, seconds) {
  fetch("/api/video/event", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ what, detail, status: status || "ok", seconds: seconds || 0 }) }).catch(() => {});
}

async function tracker() {
  if (VD.lm) return VD.lm;
  if (VD.lmLoading) return VD.lmLoading;
  VD.lmLoading = (async () => {
    const t0 = performance.now();
    $("#vd-state").textContent = "Loading the face tracker…";
    const vision = await import("./vendor/mediapipe/vision_bundle.mjs");
    const files = await vision.FilesetResolver.forVisionTasks("vendor/mediapipe/wasm");
    const opts = d => ({ baseOptions: { modelAssetPath: "vendor/mediapipe/face_landmarker.task", delegate: d },
      outputFaceBlendshapes: true, runningMode: "VIDEO", numFaces: 1 });
    let lm;
    try { lm = await vision.FaceLandmarker.createFromOptions(files, opts("GPU")); }
    catch (e) { lm = await vision.FaceLandmarker.createFromOptions(files, opts("CPU")); }
    VD.lm = lm;
    const secs = (performance.now() - t0) / 1000;
    $("#vd-state").textContent = "Face tracker ready (" + secs.toFixed(2) + " s).";
    vdLog("tracker loaded", "MediaPipe Face Landmarker", "ok", secs);
    return lm;
  })();
  try { return await VD.lmLoading; } catch (e) { VD.lmLoading = null; $("#vd-state").textContent = "The face tracker could not start: " + e.message; vdLog("tracker failed", e.message, "failed"); throw e; }
}

// One video frame → the numbers lipread.py works with.
function measureFrame(res, video, t) {
  const W = video.videoWidth || 1, H = video.videoHeight || 1;
  const f = { t: Math.round(t * 1000) / 1000, face: false };
  const L = res && res.faceLandmarks && res.faceLandmarks[0];
  if (!L) return f;
  const p = i => L[i], d = (a, b) => Math.hypot((p(a).x - p(b).x) * W, (p(a).y - p(b).y) * H);
  const mw = d(LM.mouthL, LM.mouthR) || 1;
  f.face = true;
  f.mouth_px = Math.round(mw);
  f.gap = Math.round(1000 * d(LM.lipTop, LM.lipBot) / mw) / 1000;
  f.face_h = Math.round(1000 * Math.abs(p(LM.chin).y - p(LM.forehead).y)) / 1000;
  const r = (p(LM.nose).x - p(LM.cheekL).x) / ((p(LM.cheekR).x - p(LM.cheekL).x) || 1);
  f.yaw = Math.round(Math.asin(Math.max(-1, Math.min(1, (r - 0.5) * 2))) * 180 / Math.PI);
  const q = (p(LM.nose).y - p(LM.forehead).y) / ((p(LM.chin).y - p(LM.forehead).y) || 1);
  f.pitch = Math.round(Math.asin(Math.max(-1, Math.min(1, (q - 0.58) * 2.5))) * 180 / Math.PI);
  f.bs = {};
  const cats = res.faceBlendshapes && res.faceBlendshapes[0] ? res.faceBlendshapes[0].categories : [];
  cats.forEach(c => { if (/^(mouth|jaw|brow|cheek|noseSneer|eyeSquint|eyeWide|eyeBlink)/.test(c.categoryName)) f.bs[c.categoryName] = Math.round(c.score * 1000) / 1000; });
  f.light = VD.lastLight;
  f._L = L;
  return f;
}

// Face brightness: the face box scaled down to 24×24, mean luma (every few frames; cheap).
const lightCanvas = document.createElement("canvas"); lightCanvas.width = lightCanvas.height = 24;
function sampleLight(video, L) {
  try {
    const W = video.videoWidth, H = video.videoHeight;
    let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
    L.forEach(p => { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); });
    const g = lightCanvas.getContext("2d", { willReadFrequently: true });
    g.drawImage(video, x0 * W, y0 * H, Math.max(1, (x1 - x0) * W), Math.max(1, (y1 - y0) * H), 0, 0, 24, 24);
    const d = g.getImageData(0, 0, 24, 24).data;
    let s = 0; for (let i = 0; i < d.length; i += 4) s += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
    VD.lastLight = Math.round(1000 * s / (d.length / 4) / 255) / 1000;
  } catch (e) { /* cross-origin or not ready: keep the last value */ }
}

function drawOverlay(video, f) {
  const c = $("#vd-overlay"), W = video.videoWidth, H = video.videoHeight;
  if (!W) return;
  if (c.width !== W) { c.width = W; c.height = H; }
  const g = c.getContext("2d");
  g.clearRect(0, 0, W, H);
  if (!f || !f.face) return;
  const L = f._L, lw = Math.max(2, W / 400);
  // the recommended framing band: face 40–60% of the height
  g.strokeStyle = f.face_h >= 0.4 && f.face_h <= 0.6 ? "rgba(22,163,74,.9)" : "rgba(245,158,11,.9)"; g.lineWidth = lw;
  const ys = L.map(p => p.y), xs = L.map(p => p.x);
  g.strokeRect(Math.min(...xs) * W, Math.min(...ys) * H, (Math.max(...xs) - Math.min(...xs)) * W, (Math.max(...ys) - Math.min(...ys)) * H);
  // lips
  g.fillStyle = "rgba(220,38,38,.95)";
  [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185, 13, 14, 78, 308].forEach(i => { g.beginPath(); g.arc(L[i].x * W, L[i].y * H, lw * 1.3, 0, 7); g.fill(); });
}

function liveChips(f, fps) {
  const chip = (ok, warn, text) => '<span class="vd-chip ' + (ok ? "ok" : warn ? "warn" : "bad") + '">' + esc(text) + "</span>";
  const v = $("#vd-video");
  if (!f || !f.face) { $("#vd-live").innerHTML = chip(false, false, "no face found — see the guide"); return; }
  $("#vd-live").innerHTML =
    chip(f.face_h >= 0.4 && f.face_h <= 0.6, f.face_h >= 0.28 && f.face_h <= 0.75, "face " + Math.round(100 * f.face_h) + "% of height" + (f.face_h < 0.4 ? " — come closer" : f.face_h > 0.6 ? " — move back" : "")) +
    chip(f.mouth_px >= 150, f.mouth_px >= 90, "mouth " + f.mouth_px + " px") +
    chip(Math.abs(f.yaw) <= 20 && Math.abs(f.pitch) <= 15, Math.abs(f.yaw) <= 30, "angle " + f.yaw + "° / " + f.pitch + "°") +
    chip(f.light >= 0.3 && f.light <= 0.8, f.light >= 0.18 && f.light <= 0.9, "light " + Math.round(100 * f.light) + "%") +
    chip(fps >= 50, fps >= 29, (fps ? fps.toFixed(0) : "–") + " frames/s") +
    chip(v.videoHeight >= 1080, v.videoHeight >= 720, v.videoWidth + "×" + v.videoHeight) +
    '<span class="vd-chip">lips open ' + Math.round(100 * f.gap) + "%</span>";
}

// Mouth parameters for the avatar from the tracked face (same scale as the talking face's viseme table).
function mouthFromFace(f) {
  const b = f.bs || {}, g = k => b[k] || 0;
  const round = Math.max(g("mouthFunnel"), g("mouthPucker"));
  const spread = Math.max((g("mouthStretchLeft") + g("mouthStretchRight")) / 2, (g("mouthSmileLeft") + g("mouthSmileRight")) / 2);
  return { open: Math.min(1, Math.max(f.gap * 2.2, g("jawOpen") * 1.1)), width: Math.max(0.25, Math.min(0.85, 0.55 + 0.4 * spread - 0.3 * round)),
    round, teeth: Math.min(1, 0.3 + g("mouthUpperUpLeft") + g("mouthRollLower")), tongue: 0.2, press: Math.min(1, g("mouthClose") * 2 + g("mouthPressLeft")) };
}

// ---------------------------------------------------------------- sources
async function vdUse(stream, kind) {
  vdStop();
  VD.stream = stream; VD.kind = kind; VD.blob = null; VD.src = null;
  const v = $("#vd-video");
  v.srcObject = stream; v.muted = true; v.controls = false;
  await v.play().catch(() => {});
  $("#vd-empty").hidden = true;
  $("#vd-rec").disabled = false; $("#vd-stop").disabled = false; $("#vd-go").disabled = true; $("#vd-dub").disabled = true;
  const tr = stream.getVideoTracks()[0], st = tr ? tr.getSettings() : {};
  $("#vd-state").textContent = (kind === "camera" ? "Camera" : "Screen") + " on: " + (st.width || "?") + "×" + (st.height || "?") + " at " + (st.frameRate ? Math.round(st.frameRate) : "?") + " frames/s" +
    (stream.getAudioTracks().length ? ", with sound" : ", no sound") + ". Press Record, speak, then Stop.";
  vdLog(kind + " started", (st.width || "?") + "x" + (st.height || "?") + " @" + (st.frameRate ? Math.round(st.frameRate) : "?") + " fps, audio " + (stream.getAudioTracks().length ? "yes" : "no"));
  if (tr) tr.onended = () => { if (VD.rec && VD.rec.state === "recording") VD.rec.stop(); };
  vdLiveLoop();
}

function vdStop() {
  VD.live = false;
  if (VD.rec && VD.rec.state === "recording") VD.rec.stop();
  if (VD.stream) { VD.stream.getTracks().forEach(t => t.stop()); VD.stream = null; vdLog("capture stopped", VD.kind); }
  $("#vd-stop").disabled = true;
}

async function vdLiveLoop() {
  let lm;
  try { lm = await tracker(); } catch (e) { return; }
  const v = $("#vd-video");
  VD.live = true; VD.fpsT = [];
  let n = 0;
  const step = () => {
    if (!VD.live || !v.srcObject) return;
    if (v.readyState >= 2) {
      const now = performance.now();
      const res = lm.detectForVideo(v, now);
      const f = measureFrame(res, v, now / 1000);
      if (f.face && n++ % 6 === 0) sampleLight(v, f._L);
      VD.fpsT.push(now); while (VD.fpsT.length > 30) VD.fpsT.shift();
      const fps = VD.fpsT.length > 2 ? 1000 * (VD.fpsT.length - 1) / (VD.fpsT[VD.fpsT.length - 1] - VD.fpsT[0]) : 0;
      drawOverlay(v, f);
      if (n % 3 === 0) liveChips(f, fps);
      if (VD.avatar && f.face) VD.avatar.live(mouthFromFace(f));
    }
    if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(step); else requestAnimationFrame(step);
  };
  step();
}

function vdRecord() {
  if (VD.rec && VD.rec.state === "recording") { VD.rec.stop(); return; }
  if (!VD.stream) return;
  const types = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];
  const mimeType = types.find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
  VD.chunks = [];
  VD.rec = new MediaRecorder(VD.stream, mimeType ? { mimeType, videoBitsPerSecond: 8000000 } : {});
  VD.rec.ondataavailable = e => { if (e.data && e.data.size) VD.chunks.push(e.data); };
  VD.rec.onstop = () => {
    const secs = (performance.now() - VD.recT0) / 1000;
    VD.blob = new Blob(VD.chunks, { type: VD.rec.mimeType || "video/webm" });
    $("#vd-rec").textContent = "⏺ Record"; $("#vd-rec").classList.remove("busy");
    vdLog("recorded", VD.kind + " " + (VD.blob.size / 1e6).toFixed(1) + " MB", "ok", secs);
    vdLoadBlob(VD.blob, "recording (" + secs.toFixed(2) + " s)");
  };
  VD.recT0 = performance.now();
  VD.rec.start(250);
  $("#vd-rec").textContent = "⏹ Stop recording"; $("#vd-rec").classList.add("busy");
  const tick = () => { if (VD.rec && VD.rec.state === "recording") { $("#vd-state").textContent = "Recording… " + ((performance.now() - VD.recT0) / 1000).toFixed(2) + " s"; setTimeout(tick, 50); } };
  tick();
}

function vdLoadBlob(blob, label) {
  VD.live = false;
  if (VD.stream) { VD.stream.getTracks().forEach(t => t.stop()); VD.stream = null; }
  VD.blob = blob;
  if (VD.src) URL.revokeObjectURL(VD.src);
  VD.src = URL.createObjectURL(blob);
  const v = $("#vd-video");
  v.srcObject = null; v.src = VD.src; v.controls = true; v.muted = false;
  $("#vd-empty").hidden = true;
  $("#vd-rec").disabled = true; $("#vd-stop").disabled = true; $("#vd-go").disabled = false; $("#vd-dub").disabled = false;
  $("#vd-state").innerHTML = "Loaded: " + esc(label) + " · " + (blob.size / 1e6).toFixed(1) + " MB · " +
    '<a href="' + VD.src + '" download="querybook-capture.' + (/mp4/.test(blob.type) ? "mp4" : "webm") + '">download</a>';
  $("#vd-overlay").getContext("2d").clearRect(0, 0, 99999, 99999);
}

// ---------------------------------------------------------------- the soundtrack
async function decodeTrack(blob) {
  const buf = await blob.arrayBuffer();
  const ac = new (window.AudioContext || window.webkitAudioContext)();
  try { return await ac.decodeAudioData(buf); } finally { ac.close(); }
}
function envelope(audio) {
  // loudness at 100 per second, 0 (quiet) … 1 (loudest)
  const x = audio.getChannelData(0), sr = audio.sampleRate, hop = Math.round(sr / 100), db = [];
  for (let i = 0; i + hop <= x.length; i += hop) {
    let s = 0; for (let j = i; j < i + hop; j++) s += x[j] * x[j];
    db.push(10 * Math.log10(s / hop + 1e-10));
  }
  const top = Math.max(...db), floor = top - 50;
  return db.map(v => Math.round(1000 * Math.max(0, (v - floor) / 50)) / 1000);
}
async function wavB64(audio, rate) {
  const n = Math.ceil(audio.duration * rate);
  const off = new OfflineAudioContext(1, n, rate);
  const s = off.createBufferSource(); s.buffer = audio; s.connect(off.destination); s.start();
  const y = (await off.startRendering()).getChannelData(0);
  const dv = new DataView(new ArrayBuffer(44 + y.length * 2));
  const w = (o, str) => { for (let i = 0; i < str.length; i++) dv.setUint8(o + i, str.charCodeAt(i)); };
  w(0, "RIFF"); dv.setUint32(4, 36 + y.length * 2, true); w(8, "WAVE"); w(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, rate, true); dv.setUint32(28, rate * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); w(36, "data"); dv.setUint32(40, y.length * 2, true);
  for (let i = 0; i < y.length; i++) dv.setInt16(44 + 2 * i, Math.max(-32767, Math.min(32767, y[i] * 32767)), true);
  return await blobB64(new Blob([dv.buffer], { type: "audio/wav" }));
}

// ---------------------------------------------------------------- analyse
// Play a video element once through the face tracker (muted, slowed down on a slow computer so no frame is
// skipped). Returns the per-frame measurements, the video's own frame rate and the tracked rate.
async function trackVideo(v, onProgress) {
  const lm = await tracker();
  v.pause(); v.muted = true; v.controls = false;
  if (v.readyState < 2) await new Promise(r => v.addEventListener("loadeddata", r, { once: true }));
  if (v.currentTime > 0) await new Promise(r => { v.addEventListener("seeked", r, { once: true }); v.currentTime = 0; });
  const frames = [], times = [];
  let n = 0, lastT = -1, p0 = null, p1 = null, m0 = 0, m1 = 0, detMs = 0;
  v.playbackRate = 1;
  await new Promise((resolve, reject) => {
    const step = (now, meta) => {
      const t = meta && meta.mediaTime !== undefined ? meta.mediaTime : v.currentTime;
      if (meta && meta.presentedFrames !== undefined) {           // the video's own frame count, for its real frame rate
        if (p0 === null) { p0 = meta.presentedFrames; m0 = t; }
        p1 = meta.presentedFrames; m1 = t;
      }
      if (t > lastT) {
        lastT = t;
        try {
          const d0 = performance.now();
          const res = lm.detectForVideo(v, d0);
          detMs = detMs ? 0.8 * detMs + 0.2 * (performance.now() - d0) : performance.now() - d0;
          const f = measureFrame(res, v, t);
          if (f.face && n++ % 5 === 0) sampleLight(v, f._L);
          if (v === $("#vd-video")) drawOverlay(v, f);
          delete f._L; frames.push(f); times.push(t);
        } catch (e) { reject(e); return; }
        // a slow computer plays the video slower while tracking, so no frames are skipped (the sound is muted)
        const want = Math.max(0.1, Math.min(1, 1000 / (Math.max(1, detMs) * 1.3 * 30)));
        if (Math.abs(v.playbackRate - want) > 0.05) v.playbackRate = want;
        if (onProgress) onProgress(t, v.playbackRate);
      }
      if (v.ended) { resolve(); return; }
      if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(step); else requestAnimationFrame(() => step(performance.now()));
    };
    v.onended = () => resolve();
    v.play().then(() => step(performance.now()), reject);
  });
  v.controls = true; v.muted = false; v.playbackRate = 1;
  const span = times.length > 1 ? times[times.length - 1] - times[0] : 0;
  const tracked = span > 0 ? (times.length - 1) / span : 0;
  // the video's frame rate: from frames presented when the browser reports them (live captures are measured as recorded)
  const fps = p1 !== null && m1 > m0 && p1 > p0 ? (p1 - p0) / (m1 - m0) : tracked;
  return { frames, fps, tracked, span };
}

async function vdAnalyse() {
  const btn = $("#vd-go"); if (!VD.blob) return;
  buttonStart(btn);
  let ok = false;
  try {
    const v = $("#vd-video");
    const { frames, fps, tracked, span } = await trackVideo(v, (t, rate) => {
      if (isFinite(v.duration)) $("#vd-prog").style.width = (100 * t / v.duration).toFixed(1) + "%";
      $("#vd-state").textContent = "Tracking the face frame by frame… " + t.toFixed(2) + " s" + (rate < 1 ? " (playing at " + rate.toFixed(2) + "× so every frame is read)" : "");
    });
    $("#vd-state").textContent = "Tracked " + frames.length + " frames (" + tracked.toFixed(1) + " per second of video).";
    let env = null, note = "";
    try { env = envelope(await decodeTrack(VD.blob)); } catch (e) { note = "This file's sound could not be read here, so the sync check was skipped."; }
    const r = await api("/api/video/analyse", { frames, env, env_fps: 100, script: $("#vd-script").value, words: $("#vd-words").value,
      read_lips: $("#vd-read").checked, lang: (window.SP && SP.profile && SP.profile.lang) || "en",
      info: { width: v.videoWidth, height: v.videoHeight, fps: Math.round(Math.max(fps, tracked) * 10) / 10, tracked_fps: Math.round(tracked * 10) / 10, source: VD.kind || "file", seconds: Math.round(span * 100) / 100 } });
    VD.analysed = { frames, env, info: { width: v.videoWidth, height: v.videoHeight, fps: Math.round(Math.max(fps, tracked) * 10) / 10, source: VD.kind || "file" } };
    $("#vd-ingest").disabled = false;
    vdShow(r, note);
    ok = true;
  } catch (e) {
    $("#vd-out").innerHTML = '<div class="note bad">The analysis stopped: ' + esc(e.message) + "</div>";
  } finally { buttonEnd(btn, ok); $("#vd-prog").style.width = ok ? "100%" : "0"; }
}

function vdShow(r, note) {
  const q = r.quality, icon = { ok: "✔", warn: "⚠", bad: "✖" };
  let h = (note ? '<div class="note bad">' + esc(note) + "</div>" : "") + (r.error ? '<div class="note bad">' + esc(r.error) + "</div>" : "");
  h += '<h3>Capture quality: ' + q.score + "/100 <span class=\"small muted\">(" + q.frames_with_face + " of " + q.frames + " frames had a face)</span></h3>" +
    '<table class="tbl small"><tr><th></th><th>Item</th><th>This video</th><th>Recommended</th></tr>' +
    q.items.map(i => '<tr class="' + i.status + '"><td>' + icon[i.status] + "</td><td>" + esc(i.item) + "</td><td>" + esc(i.value) + "</td><td>" + esc(i.advice) + "</td></tr>").join("") + "</table>";
  if (r.sync) h += '<h3>Sound and lips</h3><div class="note ' + (r.sync.ok && /in sync|accept/.test(r.sync.verdict) ? "good" : "bad") + '">' +
    (r.sync.ok ? "<b>" + esc(r.sync.verdict) + "</b> — offset " + r.sync.offset_ms + " ms (positive = sound after the lips), match strength " + r.sync.correlation : esc(r.sync.reason || r.sync.verdict)) + "</div>";
  if (r.timeline) h += '<h3>What the lips did</h3><div class="vd-strip">' + r.timeline.map(s => '<i title="' + esc(s.start + " s: " + r.classes[s.class]) + '" style="flex:' + s.seconds + ";background:" + CLASS_COLORS[s.class] + '"></i>').join("") + "</div>" +
    '<p class="small">' + Object.entries(r.classes).map(([k, d]) => '<span class="vd-key" style="background:' + CLASS_COLORS[k] + '"></span>' + esc(d)).join(" &nbsp; ") + "</p>";
  if (r.script) h += '<h3>Lips against the script: ' + r.script.agreement + '% <span class="small muted">(raw match ' + r.script.raw_match + "%, chance " + r.script.chance_match + "%)</span></h3>" +
    '<div class="note ' + (r.script.agreement >= 40 ? "good" : "bad") + '">' + esc(r.script.verdict) + "</div><p>" +
    r.script.words.map(w => '<span class="vd-word ' + (w.agreement >= 0.6 ? "ok" : w.agreement >= 0.4 ? "warn" : "bad") + '" title="looks like ' + esc(w.looks_like) + '">' + esc(w.word) + " " + Math.round(100 * w.agreement) + "%</span>").join(" ") + "</p>";
  if (r.lipread) h += '<h3>Lip-reading</h3><p><b>' + esc(r.lipread.text || "(nothing readable)") + '</b></p><p class="small muted">' + esc(r.lipread.note) + " Vocabulary: " + r.lipread.vocabulary_size + " words in " + r.lipread.look_alike_groups + " look-alike groups.</p>" +
    r.lipread.segments.map(s => '<div class="small"><b>' + s.from_s.toFixed(2) + "–" + s.to_s.toFixed(2) + " s</b> (confidence " + Math.round(100 * s.confidence) + "%): " +
      s.words.map(w => "<b>" + esc(w.word) + "</b>" + (w.same_on_lips.length ? ' <span class="muted">(or ' + esc(w.same_on_lips.slice(0, 4).join(", ")) + ")</span>" : "")).join(" · ") + "</div>").join("");
  if (r.stages) h += '<details><summary class="small">Timing of every stage (to 0.01 s)</summary>' + stagesTable(r.stages.stages, r.stages.seconds) + "</details>";
  $("#vd-out").innerHTML = h;
}

// ---------------------------------------------------------------- overdub
async function vdOverdub() {
  if (!VD.blob) return;
  const text = $("#vd-dub-text").value.trim();
  if (!text) { toast("Type the new words first.", true); return; }
  if (!$("#vd-consent").checked) { toast("Tick the permission box first: overdubbing replaces a person's voice.", true); return; }
  let audio;
  try { audio = await decodeTrack(VD.blob); } catch (e) { toast("This video's sound could not be read here.", true); return; }
  const r = await api("/api/video/overdub", genBody({ text, consent: true, audio_b64: await wavB64(audio, 16000) }));
  VD.lastDub = r;
  const box = $("#vd-dub-out");
  box.innerHTML = '<div class="note good">Fitted ' + esc(r.mode) + ", " + r.duration_s.toFixed(2) + " s, voice: " + esc(r.engine_used) + ". " + esc(r.label) + "</div>" +
    r.warnings.map(w => '<div class="note bad">' + esc(w) + "</div>").join("") +
    '<table class="tbl small"><tr><th>Original speech</th><th>New words took</th><th>Stretch</th></tr>' +
    r.phrases.map(p => "<tr><td>" + p.original_from_s.toFixed(2) + "–" + p.original_to_s.toFixed(2) + " s</td><td>" + p.new_seconds.toFixed(2) + " s</td><td>" + p.stretch.toFixed(2) + "×</td></tr>").join("") + "</table>" +
    '<div class="row"><button class="btn" id="vd-prev">▶ Preview with the video</button><button class="btn" id="vd-export">⬇ Make the overdubbed video</button>' +
    audioEl(r.audio) + '<a class="small" href="/api/speech/audio?name=' + encodeURIComponent(r.audio) + '" download>new soundtrack (WAV)</a></div>' +
    '<p class="small muted" id="vd-exp-state"></p>' +
    (r.stages ? '<details><summary class="small">Timing of every stage (to 0.01 s)</summary>' + stagesTable(r.stages.stages, r.stages.seconds) + "</details>" : "");
  $("#vd-prev").onclick = () => vdPreview(box.querySelector("audio"));
  $("#vd-export").onclick = vdExport;
  if (window.TalkingFace) faceCard(box, r.audio, text, (SP.profile && SP.profile.lang) || "en");
}

function vdPreview(a) {
  const v = $("#vd-video");
  v.muted = true; v.currentTime = 0; a.currentTime = 0;
  v.play(); a.play();
  const keep = () => { if (v.paused || v.ended) { a.pause(); v.muted = false; return; } if (Math.abs(a.currentTime - v.currentTime) > 0.08 && a.currentTime < a.duration) a.currentTime = v.currentTime; requestAnimationFrame(keep); };
  keep();
}

async function vdExport() {
  const r = VD.lastDub; if (!r) return;
  const btn = $("#vd-export"); buttonStart(btn);
  let ok = false;
  const t0 = performance.now();
  try {
    const v = document.createElement("video"); v.src = VD.src; v.muted = true; v.playsInline = true;
    if (v.readyState < 2) await new Promise(res => v.addEventListener("loadeddata", res, { once: true }));
    const a = new Audio("/api/speech/audio?name=" + encodeURIComponent(r.audio));
    if (a.readyState < 4) await new Promise(res => { a.addEventListener("canplaythrough", res, { once: true }); a.load(); });
    const scale = Math.min(1, 1280 / v.videoWidth), W = Math.round(v.videoWidth * scale / 2) * 2, H = Math.round(v.videoHeight * scale / 2) * 2;
    const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
    const ac = new AudioContext(), dest = ac.createMediaStreamDestination();
    ac.createMediaElementSource(a).connect(dest);
    const stream = new MediaStream([...c.captureStream(30).getVideoTracks(), ...dest.stream.getAudioTracks()]);
    const type = ["video/webm;codecs=vp9,opus", "video/webm"].find(t => MediaRecorder.isTypeSupported(t)) || "";
    const rec = new MediaRecorder(stream, type ? { mimeType: type, videoBitsPerSecond: 6000000 } : {}), parts = [];
    rec.ondataavailable = e => { if (e.data.size) parts.push(e.data); };
    const done = new Promise(res => { rec.onstop = res; });
    rec.start(250); await v.play(); await a.play();
    const end = Math.max(v.duration || 0, r.duration_s);
    await new Promise(res => {
      const draw = () => {
        g.drawImage(v, 0, 0, W, H);
        g.fillStyle = "rgba(0,0,0,.55)"; g.fillRect(8, H - 34, 330, 26);
        g.fillStyle = "#fff"; g.font = "bold 15px sans-serif"; g.fillText("SYNTHETIC VOICE — overdubbed", 16, H - 15);
        const t = Math.max(v.currentTime, a.currentTime);
        $("#vd-exp-state").textContent = "Recording the new video… " + t.toFixed(2) + " / " + end.toFixed(2) + " s";
        if ((v.ended || v.paused) && (a.ended || a.paused)) { res(); return; }
        requestAnimationFrame(draw);
      };
      draw();
    });
    rec.stop(); await done; ac.close();
    const out = new Blob(parts, { type: rec.mimeType || "video/webm" }), url = URL.createObjectURL(out);
    const secs = (performance.now() - t0) / 1000;
    $("#vd-exp-state").innerHTML = '✔ Overdubbed video ready (' + (out.size / 1e6).toFixed(1) + " MB, made in " + secs.toFixed(2) + ' s): <a href="' + url + '" download="querybook-overdub.webm">download</a> · labelled “SYNTHETIC VOICE”.';
    vdLog("overdub video exported", (out.size / 1e6).toFixed(1) + " MB, " + W + "x" + H, "ok", secs);
    ok = true;
  } catch (e) {
    $("#vd-exp-state").textContent = "The video could not be made here: " + e.message;
    vdLog("overdub video export failed", e.message, "failed", (performance.now() - t0) / 1000);
  } finally { buttonEnd(btn, ok); }
}

// ---------------------------------------------------------------- setup
async function vdSetup() {
  if (VD.ready) return; VD.ready = true;
  try {
    const g = await api("/api/video/guide");
    const names = { framing: "What to capture", mouth_px: "Mouth size", resolution: "HD or 4K", frame_rate: "Frame rate", angle: "Angle", light: "Light", clear: "Nothing over the mouth", screen: "Screen capture", sound: "Sound" };
    $("#vd-guide").innerHTML = Object.entries(g.guide).map(([k, t]) => "<li><b>" + esc(names[k] || k) + ":</b> " + esc(t) + "</li>").join("");
  } catch (e) { /* the guide is also in Help */ }
  $("#vd-cam").onclick = async () => {
    const h = Number($("#vd-res").value), w = Math.round(h * 16 / 9), fps = Number($("#vd-fps").value);
    try {
      vdUse(await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: w }, height: { ideal: h }, frameRate: { ideal: fps }, facingMode: "user" },
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } }), "camera");
    } catch (e) { toast("The camera could not be opened: " + e.message, true); vdLog("camera failed", e.message, "failed"); }
  };
  $("#vd-screen").onclick = async () => {
    try { vdUse(await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: 60 } }, audio: true }), "screen"); }
    catch (e) { toast("Screen sharing was not started: " + e.message, true); vdLog("screen capture failed", e.message, "failed"); }
  };
  $("#vd-file").onchange = e => { const f = e.target.files[0]; if (f) { VD.kind = "file"; vdLoadBlob(f, f.name); vdLog("video file opened", f.name + " " + (f.size / 1e6).toFixed(1) + " MB"); } };
  $("#vd-rec").onclick = vdRecord;
  $("#vd-stop").onclick = vdStop;
  $("#vd-go").onclick = vdAnalyse;
  $("#vd-dub").onclick = vdOverdub;
  $("#vd-ingest").onclick = vdIngest;
  $("#vd-mirror").onchange = async e => {
    const el = $("#vd-avatar");
    el.hidden = !e.target.checked;
    if (e.target.checked) {
      el.innerHTML = '<div class="row"><button class="btn small" data-am="2d">2D</button><button class="btn small" data-am="3d">3D / VR</button></div><div class="vd-av"></div>';
      VD.avatar = new TalkingFace(el.querySelector(".vd-av"));
      await VD.avatar.setMode("2d");
      el.querySelectorAll("[data-am]").forEach(b => b.onclick = () => VD.avatar.setMode(b.dataset.am));
    } else { VD.avatar = null; el.innerHTML = ""; }
  };
}

// ---------------------------------------------------------------- QueryBook ingestion of a video: sound + face together
async function vdIngest() {
  if (!VD.blob || !VD.analysed) { toast("Analyse the video first (step 2).", true); return; }
  let audio;
  try { audio = await decodeTrack(VD.blob); } catch (e) { toast("This video's sound could not be read here.", true); return; }
  const r = await api("/api/speech/ingest", { audio_b64: await wavB64(audio, 16000), transcript: $("#vd-script").value, expected: $("#vd-script").value, label: "video", recognizer: "auto",
    lang: (window.SP && SP.profile && SP.profile.lang) || "en", video: { frames: VD.analysed.frames, env: VD.analysed.env, info: VD.analysed.info } });
  const m = r.measure;
  $("#vd-ingest-out").innerHTML = '<div class="note good">Ingested: <b>' + esc(r.transcript || "(no words)") + "</b> — heard by " + esc(r.heard_by) + "</div>" +
    faceEvidenceHtml(r.face, m.vocal_mode) + learnedNote(r.learning) +
    (r.semantics ? '<p class="small"><b>Words:</b> ' + r.semantics.words.map(w => esc(w.word) + (w.known_to_builder ? "" : "?")).join(" ") + " — " + esc(r.semantics.language_name) + "</p>" : "");
}

// ---------------------------------------------------------------- the camera alongside a voice recording (Ask, Listen)
const CAMSIDE = { on: false, stream: null, frames: [], t0: 0, info: null };
async function camSideStart(host, t0) {
  CAMSIDE.frames = []; CAMSIDE.t0 = t0;
  try {
    CAMSIDE.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 60 }, facingMode: "user" } });
  } catch (e) { toast("The camera could not be opened — the sound alone will be used: " + e.message, true); return false; }
  host.hidden = false;
  host.innerHTML = '<video playsinline muted style="width:220px;border-radius:8px;transform:scaleX(-1)"></video><div class="small muted"></div>';
  const v = host.querySelector("video"), note = host.querySelector("div");
  v.srcObject = CAMSIDE.stream; await v.play().catch(() => {});
  CAMSIDE.on = true;
  let lm;
  try { lm = await tracker(); } catch (e) { note.textContent = "Face tracker unavailable — the sound alone will be used."; return false; }
  let n = 0;
  const step = () => {
    if (!CAMSIDE.on) return;
    if (v.readyState >= 2) {
      const now = performance.now();
      const f = measureFrame(lm.detectForVideo(v, now), v, (now - CAMSIDE.t0) / 1000);
      if (f.face && n % 6 === 0) sampleLight(v, f._L);
      delete f._L; CAMSIDE.frames.push(f); n++;
      if (n % 10 === 0) note.textContent = f.face ? "face tracked · lips open " + Math.round(100 * f.gap) + "%" : "no face — look at the camera";
    }
    if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(step); else requestAnimationFrame(step);
  };
  step();
  CAMSIDE.info = () => { const fr = CAMSIDE.frames, span = fr.length > 1 ? fr[fr.length - 1].t - fr[0].t : 0;
    return { width: v.videoWidth, height: v.videoHeight, fps: span > 0 ? Math.round(10 * (fr.length - 1) / span) / 10 : 0, source: "camera" }; };
  return true;
}
function camSideStop(host) {
  if (!CAMSIDE.on && !CAMSIDE.stream) return null;
  CAMSIDE.on = false;
  const info = CAMSIDE.info ? CAMSIDE.info() : {};
  if (CAMSIDE.stream) CAMSIDE.stream.getTracks().forEach(t => t.stop());
  CAMSIDE.stream = null;
  if (host) host.hidden = true;
  const frames = CAMSIDE.frames; CAMSIDE.frames = [];
  vdLog("camera with voice", frames.filter(f => f.face).length + " of " + frames.length + " frames with a face");
  return frames.length ? { frames, info } : null;
}

// What the camera added to a spoken input, in plain words.
function faceEvidenceHtml(face, heard) {
  if (!face) return "";
  if (!face.face_seen) return '<div class="note bad">Camera: ' + esc(face.note || "no face seen") + "</div>";
  const m = face.mode, ex = face.expression || {}, sc = face.speaker_check || {}, tr = face.transcript;
  let h = '<div class="card face-evidence"><h3>What the camera added</h3><div class="stats">' +
    stat(m.label, "vocal mode (sound + face)") + stat(m.confidence, "how sure") + stat(ex.label || "—", "face shows") +
    stat(face.sync && face.sync.ok ? face.sync.offset_ms + " ms" : "—", "sound vs lips") + stat(sc.trust || "—", "voice belongs to this face") + "</div>" +
    '<p class="small">' + m.reasons.map(esc).join(" · ") + (ex.reasons ? " · face: " + ex.reasons.map(esc).join("; ") : "") + "</p>" +
    '<div class="note ' + (sc.trust === "high" ? "good" : sc.trust === "low" ? "bad" : "") + '"><b>Speaker check:</b> ' + esc(sc.verdict || "") +
    (sc.flags && sc.flags.length ? " — " + sc.flags.map(esc).join("; ") : "") + (sc.ok && sc.ok.length ? ' <span class="muted">(' + sc.ok.map(esc).join("; ") + ")</span>" : "") + "</div>";
  if (tr && tr.candidates && tr.candidates.length > 1)
    h += '<h3>Which words were said' + (tr.changed_by_lips ? ' — <span class="good-t">corrected by the lips</span>' : "") + '</h3><table class="tbl small"><tr><th></th><th>Possible words</th><th>From</th><th>Sound</th><th>Lips</th><th>Together</th></tr>' +
      tr.candidates.map(c => "<tr><td>" + (c.chosen ? "✔" : "") + "</td><td>" + (c.chosen ? "<b>" + esc(c.text) + "</b>" : esc(c.text)) + "</td><td>" + esc(c.source) + "</td><td>" +
        Math.round(100 * c.audio_confidence) + "%</td><td>" + Math.round(100 * c.lip_agreement) + "%</td><td>" + Math.round(100 * c.score) + "%</td></tr>").join("") +
      '</table><p class="small muted">The lips count for ' + Math.round(100 * tr.lip_weight) + "% here (more when the picture is good: capture quality " + face.quality.score + "/100).</p>";
  return h + "</div>";
}

// ---------------------------------------------------------------- teach and improve (the ingestion reservoir)
const LC = { i: 0, rec: false, status: null };
function learnedNote(l) {
  if (!l) return "";
  return '<p class="small ' + (l.stored ? "good-t" : "muted") + '">' + (l.stored ? "✔ Added to the ingestion reservoir (" + l.labelled_frames + " frames labelled, " + l.split + " set) — the app learns from it." :
    "Not added to the ingestion reservoir: " + esc(l.reason)) + "</p>";
}
async function lcLoad() {
  const r = await api("/api/lipcoach"); LC.status = r;
  const vs = r.versions, act = vs.find(v => v.id === r.active_version), m = act ? act.metrics : {};
  const last = vs.length ? vs[vs.length - 1].metrics : {};
  const pct = v => v === null || v === undefined ? "—" : Math.round(100 * v) + "%";
  const tr = r.reservoir.filter(x => x.split === "train").reduce((a, x) => a + x.recordings, 0), te = r.total - tr;
  $("#lc-stats").innerHTML = stat(r.total, "recordings in the reservoir") + stat(tr + " / " + te, "to learn from / held back") + stat(r.exact_timing, "with exact word times") +
    stat(r.active_version ? "version " + r.active_version : "built-in rules", "in use") +
    stat(pct(last.rules_accuracy) + " → " + pct(m.learned_accuracy !== undefined && m.reader_switched_on ? m.learned_accuracy : last.learned_accuracy), "mouth shapes read right (rules → learned)") +
    stat((last.agreement_rules ?? "—") + " → " + (last.agreement_learned ?? "—"), "lips agree with the true words") +
    stat((r.bias_ms || 0) + " ms", "camera/microphone delay (learned)") + stat(last.align ? last.align.before_ms + " → " + last.align.after_ms + " ms" : "—", "lip-sync timing error") +
    (r.training ? stat("learning…", "status") : "");
  $("#lc-auto").checked = r.auto;
  $("#lc-sentence").textContent = r.teach[LC.i % r.teach.length];
  // progress chart: learned vs rules accuracy and agreement, per version
  const pts = vs.filter(v => v.metrics.rules_accuracy !== undefined && v.metrics.rules_accuracy !== null);
  if (pts.length) {
    const W = 640, H = 160, X = i => 30 + (pts.length === 1 ? (W - 60) / 2 : i * (W - 60) / (pts.length - 1)), Y = v => H - 20 - v * (H - 40);
    const line = (k, col, scale) => { const p = pts.map((v, i) => [X(i), Y(Math.max(0, Math.min(1, (v.metrics[k] || 0) / (scale || 1))))]);
      return '<polyline fill="none" stroke="' + col + '" stroke-width="2.5" points="' + p.map(q => q.join(",")).join(" ") + '"/>' + p.map(q => '<circle cx="' + q[0] + '" cy="' + q[1] + '" r="3.5" fill="' + col + '"/>').join(""); };
    $("#lc-chart").innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" style="width:100%;max-width:680px"><line x1="30" y1="' + Y(0) + '" x2="' + (W - 30) + '" y2="' + Y(0) + '" stroke="#cbd5e1"/><line x1="30" y1="' + Y(1) + '" x2="' + (W - 30) + '" y2="' + Y(1) + '" stroke="#e2e8f0"/>' +
      line("rules_accuracy", "#94a3b8") + line("learned_accuracy", "#7c3aed") + line("agreement_learned", "#16a34a", 100) +
      '<text x="30" y="12" font-size="11" fill="#475569">held-back recordings, per version: <tspan fill="#7c3aed">■ learned reader</tspan> <tspan fill="#94a3b8">■ built-in rules</tspan> <tspan fill="#16a34a">■ lips agree with the words</tspan></text></svg>';
  } else $("#lc-chart").innerHTML = '<p class="small muted">No versions yet — teach a few sentences (learning starts after three recordings).</p>';
  $("#lc-versions").innerHTML = vs.length ? '<table class="tbl small"><tr><th>Version</th><th>Made (UTC)</th><th>Recordings</th><th>Rules</th><th>Learned</th><th>Lips agree</th><th>Timing error</th><th>What happened</th><th></th></tr>' +
    vs.slice().reverse().map(v => { const x = v.metrics; return '<tr class="' + (v.id === r.active_version ? "lc-active" : "") + '"><td>' + v.id + (v.id === r.active_version ? " ✔ in use" : "") + "</td><td>" + esc(v.created) + "</td><td>" + v.examples + "</td><td>" +
      pct(x.rules_accuracy) + "</td><td>" + pct(x.learned_accuracy) + "</td><td>" + (x.agreement_rules ?? "—") + " → " + (x.agreement_learned ?? "—") + "</td><td>" + (x.align ? x.align.before_ms + " → " + x.align.after_ms + " ms" : "—") +
      "</td><td>" + esc(v.note || "") + "</td><td>" + (v.id === r.active_version ? "" : '<button class="btn small quiet" data-lcuse="' + v.id + '">use</button>') + "</td></tr>"; }).join("") + "</table>" : "";
  $$("[data-lcuse]").forEach(b => b.onclick = async () => { await api("/api/lipcoach/use", { version: b.dataset.lcuse }); lcLoad(); });
  if (r.training) setTimeout(lcLoad, 1500);
}
async function lcRecord() {
  const btn = $("#lc-rec");
  if (!LC.rec) {
    try { await recStart(null, $("#lc-last")); } catch (e) { toast("The microphone could not be opened: " + e.message, true); return; }
    if (!(await camSideStart($("#lc-cam-view"), REC.t0))) { recStop(); return; }
    LC.rec = true; btn.textContent = "⏹ Stop — done reading"; btn.classList.add("busy");
  } else {
    LC.rec = false; btn.textContent = "🎙📷 Record this sentence"; btn.classList.remove("busy");
    const blob = recStop(), cam = camSideStop($("#lc-cam-view"));
    const text = $("#lc-own").value.trim() || $("#lc-sentence").textContent;
    if (!cam) { $("#lc-last").textContent = "No face frames were recorded."; return; }
    const r = await api("/api/lipcoach/teach", { audio_b64: await blobB64(blob), frames: cam.frames, info: cam.info, text, lang: (SP.profile && SP.profile.lang) || "en" });
    $("#lc-last").innerHTML = r.stored ? "✔ “" + esc(text) + "”: " + r.labelled_frames + " frames labelled (" + r.split + " set" + (r.exact_word_times ? ", exact word times" : "") + "). Built-in rules read " +
      Math.round(100 * r.rules_accuracy) + "% of them right" + (r.current_accuracy !== null ? ", the version in use " + Math.round(100 * r.current_accuracy) + "%" : "") + "." : "Not added: " + esc(r.reason);
    if (r.stored) {                                   // a rejected recording keeps the same sentence, to read again
      if (!$("#lc-own").value.trim()) LC.i++;
      $("#lc-own").value = "";
    }
    lcLoad();
  }
}
function lcSetup() {
  if (LC.ready) return; LC.ready = true;
  tracker().catch(() => {});                          // load the face tracker now, so the first recording is complete
  $("#lc-rec").onclick = lcRecord;
  $("#lc-skip").onclick = () => { LC.i++; if (LC.status) $("#lc-sentence").textContent = LC.status.teach[LC.i % LC.status.teach.length]; };
  $("#lc-auto").onchange = e => api("/api/lipcoach/auto", { on: e.target.checked });
  $("#lc-train").onclick = async () => { const r = await api("/api/lipcoach/train", {}); toast((r.note || []).join("; ") || "Learned."); lcLoad(); };
  $("#lc-rules").onclick = async () => { await api("/api/lipcoach/use", { version: "rules" }); lcLoad(); };
  $("#lc-import").onchange = async e => { const f = e.target.files[0]; if (!f) return;
    try { const r = await api("/api/lipcoach/import", { data: JSON.parse(await f.text()) }); toast(r.added + " recordings added to the reservoir."); lcLoad(); } catch (err) { toast("Import failed: " + err.message, true); } };
  lcLoad();
}

// ---------------------------------------------------------------- silent questions (lips only)
const SI = { on: false, patterns: null };
async function siSetup() {
  if (SI.ready) return; SI.ready = true;
  try {
    SI.patterns = await api("/api/silent/patterns");
    $("#si-pattern").innerHTML = SI.patterns.patterns.map(p => '<option value="' + p.id + '">' + esc(p.parts.map(x => typeof x === "string" ? x : "___").join(" ")) + "</option>").join("");
    $("#si-lang").innerHTML = SI.patterns.languages.map(l => "<option>" + esc(l) + "</option>").join("");
  } catch (e) { /* shown when used */ }
  $$('input[name="si-mode"]').forEach(r => r.onchange = () => { $("#si-guided").hidden = siMode() !== "word"; });
  $("#si-pattern").onchange = () => { const p = SI.patterns.patterns.find(x => x.id === $("#si-pattern").value); $("#si-lang").hidden = !p.parts.some(x => x.slot === "language"); };
  $("#si-go").onclick = siToggle;
  $("#si-box").addEventListener("toggle", () => { if ($("#si-box").open) tracker().catch(() => {}); });
}
function siMode() { return ($('input[name="si-mode"]:checked') || {}).value || "question"; }
function siCompose(word) {
  const p = SI.patterns.patterns.find(x => x.id === $("#si-pattern").value);
  return p.parts.map(x => typeof x === "string" ? x : x.slot === "word" ? word : $("#si-lang").value).join(" ");
}
async function siToggle() {
  const btn = $("#si-go");
  if (!SI.on) {
    SI.t0 = performance.now();
    if (!(await camSideStart($("#si-cam"), SI.t0))) return;
    SI.on = true; btn.textContent = "⏹ Done — read my lips"; btn.classList.add("busy");
    const tick = () => { if (SI.on) { $("#si-state").textContent = "● watching " + ((performance.now() - SI.t0) / 1000).toFixed(2) + " s"; setTimeout(tick, 50); } };
    tick();
  } else {
    SI.on = false; btn.textContent = "📷 Start — mouth the question"; btn.classList.remove("busy");
    const cam = camSideStop($("#si-cam"));
    if (!cam) { $("#si-out").textContent = "No face was seen."; return; }
    const mode = siMode();
    const r = await api("/api/silent/read", { frames: cam.frames, mode });
    $("#si-state").textContent = "";
    if (!r.readings.length) { $("#si-out").innerHTML = '<div class="note bad">' + esc(r.note || "Nothing could be read.") + " Try again, facing the camera.</div>"; return; }
    const pick = q => { $("#ak-text").value = q; ask(null); $("#si-box").open = false; };
    $("#si-out").innerHTML = '<p class="small">' + esc(r.note) + "</p>" + r.readings.map((x, i) => {
      const q = mode === "word" ? siCompose(x.word) : x.question;
      const alts = mode === "word" ? x.same_on_lips.map(a => siCompose(a)) : Object.entries(x.same_on_lips || {}).flatMap(([w, ms]) => ms.map(m => x.question.replace(new RegExp("\\b" + w + "\\b"), m)));
      return '<div><button class="btn si-pick" data-q="' + esc(q) + '">' + (i === 0 ? "★ " : "") + esc(q) + "</button>" +
        alts.slice(0, 4).map(a => '<button class="btn quiet small si-alt" data-q="' + esc(a) + '">' + esc(a) + "</button>").join("") + "</div>";
    }).join("") + '<p class="small muted">Not there? Type it in the box above, or mouth it again.</p>';
    $$("#si-out [data-q]").forEach(b => b.onclick = () => pick(b.dataset.q));
  }
}

document.addEventListener("click", e => { const b = e.target.closest && e.target.closest('#sptabs [data-sp="ask"]'); if (b) siSetup(); });
document.addEventListener("click", e => { const b = e.target.closest && e.target.closest('#sptabs [data-sp="video"]'); if (b) { vdSetup(); lcSetup(); } });
