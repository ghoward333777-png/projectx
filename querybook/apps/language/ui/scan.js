"use strict";
// Object scan: recognize objects in the Face & video picture (MediaPipe Object Detector, bundled), follow them from
// frame to frame, zoom on one, record the enlarged view for lip-reading, save what was seen (numbers only), ask about it.
const SC = { det: null, loading: null, on: false, tracks: [], nextId: 1, focus: null, t0: 0, started: null, frames: 0,
  lastDet: 0, lastT: 0, dt: 0.1, lastDetT: null, view: null, rec: null, chunks: [], recT0: 0 };
const SC_KEEP = 1.0;      // seconds an unseen object is still matched to new boxes (longer when detection runs slowly)
const scKeep = () => Math.max(SC_KEEP, 2.5 * SC.dt);
const scShown = () => Math.max(0.4, 1.5 * SC.dt);
const sc_iou = (a, b) => {
  const x = Math.max(0, Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0])), y = Math.max(0, Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]));
  const i = x * y; return i / (a[2] * a[3] + b[2] * b[3] - i || 1);
};

async function scDetector() {
  if (SC.det) return SC.det;
  if (SC.loading) return SC.loading;
  SC.loading = (async () => {
    const t0 = performance.now();
    $("#sc-state").textContent = "Loading the object detector…";
    const vision = await import("./vendor/mediapipe/vision_bundle.mjs");
    const files = await vision.FilesetResolver.forVisionTasks("vendor/mediapipe/wasm");
    const opts = d => ({ baseOptions: { modelAssetPath: "vendor/mediapipe/efficientdet_lite0.tflite", delegate: d }, scoreThreshold: 0.25, maxResults: 15, runningMode: "VIDEO" });
    let det;
    try { det = await vision.ObjectDetector.createFromOptions(files, opts("GPU")); }
    catch (e) { det = await vision.ObjectDetector.createFromOptions(files, opts("CPU")); }
    SC.det = det;
    const secs = (performance.now() - t0) / 1000;
    $("#sc-state").textContent = "Object detector ready (" + secs.toFixed(2) + " s).";
    if (typeof vdLog === "function") vdLog("object detector loaded", "EfficientDet-Lite0", "ok", secs);
    return det;
  })();
  try { return await SC.loading; } catch (e) { SC.loading = null; $("#sc-state").textContent = "The object detector could not start: " + e.message; throw e; }
}

function scNow(v) { return v.srcObject ? (performance.now() - SC.t0) / 1000 : v.currentTime; }

function scReset() {
  SC.tracks = []; SC.nextId = 1; SC.focus = null; SC.frames = 0; SC.view = null; SC.dt = 0.1; SC.lastDetT = null;
  SC.t0 = performance.now(); SC.started = new Date().toISOString().replace(/\.\d+Z$/, "Z");
}

// match this frame's boxes to the objects being followed (same kind, best overlap)
function scTrack(dets, t) {
  const live = SC.tracks.filter(k => t - k.last_s <= scKeep() && t >= k.first_s - 0.05);
  const pairs = [];
  dets.forEach((d, i) => live.forEach(k => { if (k.label === d.label) { const o = sc_iou(k.box, d.box); if (o >= 0.25) pairs.push([o, i, k]); } }));
  pairs.sort((a, b) => b[0] - a[0]);
  const usedD = new Set(), usedK = new Set();
  for (const [, i, k] of pairs) {
    if (usedD.has(i) || usedK.has(k.id)) continue;
    usedD.add(i); usedK.add(k.id);
    const d = dets[i];
    k.box = k.box.map((v, j) => 0.5 * v + 0.5 * d.box[j]);
    k.last_s = t; k.frames++; k.cur = d.score;
    if (d.score > k.score) { k.score = d.score; k.best = d.box.slice(); }
  }
  dets.forEach((d, i) => {
    if (usedD.has(i)) return;
    SC.tracks.push({ id: SC.nextId++, label: d.label, box: d.box.slice(), best: d.box.slice(), first_s: t, last_s: t, frames: 1, score: d.score, cur: d.score });
  });
  // follow a named kind: keep (or pick) the largest one in view
  const want = ($("#sc-kind").value || "").trim().toLowerCase();
  const cur = SC.tracks.find(k => k.id === SC.focus);
  if (want && (!cur || t - cur.last_s > scKeep())) {
    const c = SC.tracks.filter(k => t - k.last_s < scShown() && (k.label === want || k.label + "s" === want || (want === "people" && k.label === "person")))
      .sort((a, b) => b.box[2] * b.box[3] - a.box[2] * a.box[3])[0];
    if (c) SC.focus = c.id;
  }
}

function scDraw(v, t) {
  const c = $("#sc-overlay"), W = v.videoWidth, H = v.videoHeight;
  if (!W) return;
  if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
  const g = c.getContext("2d");
  g.clearRect(0, 0, W, H);
  if (!SC.on) return;
  g.lineWidth = Math.max(2, W / 400); g.font = Math.max(12, Math.round(W / 55)) + "px system-ui, sans-serif";
  for (const k of SC.tracks) {
    if (t - k.last_s > scShown() || t < k.first_s - 0.05) continue;
    const f = k.id === SC.focus, [x, y, w, h] = k.box;
    g.strokeStyle = f ? "#f59e0b" : "#22d3ee"; g.lineWidth = f ? Math.max(4, W / 220) : Math.max(2, W / 400);
    g.strokeRect(x * W, y * H, w * W, h * H);
    const txt = (f ? "◎ " : "") + k.label + " " + Math.round(100 * k.cur) + "% #" + k.id;
    const tw = g.measureText(txt).width + 8, th = parseInt(g.font, 10) + 6;
    g.fillStyle = f ? "#f59e0b" : "#0e7490"; g.fillRect(x * W, Math.max(0, y * H - th), tw, th);
    g.fillStyle = "#fff"; g.fillText(txt, x * W + 4, Math.max(th - 6, y * H - 6));
  }
}

// the enlarged view: the followed object, padded, at the zoom canvas's shape, moving smoothly
function scZoom(v, t) {
  const z = $("#sc-zoom"), g = z.getContext("2d"), W = v.videoWidth, H = v.videoHeight;
  const k = SC.tracks.find(x => x.id === SC.focus);
  if (!W || !k || t - k.last_s > 2 * scKeep()) {
    if (SC.view) { g.fillStyle = "#0f172a"; g.fillRect(0, 0, z.width, z.height); SC.view = null; }
    $("#sc-zinfo").textContent = SC.focus && k ? "Lost sight of the " + k.label + " — waiting for it to come back." : "Click a box in the picture, or name a kind, to follow it here.";
    $("#sc-zrec").disabled = !(SC.rec && SC.rec.state === "recording");
    return;
  }
  const ar = z.width / z.height;
  let [x, y, w, h] = k.box; x *= W; y *= H; w *= W; h *= H;
  const cx = x + w / 2, cy = y + h / 2;
  let sw = Math.max(w * 1.3, 48), sh = Math.max(h * 1.3, 36);
  if (sw / sh > ar) sh = sw / ar; else sw = sh * ar;
  sw = Math.min(sw, W); sh = Math.min(sh, H);
  const want = [Math.min(Math.max(0, cx - sw / 2), W - sw), Math.min(Math.max(0, cy - sh / 2), H - sh), sw, sh];
  SC.view = SC.view ? SC.view.map((p, i) => p + 0.25 * (want[i] - p)) : want;
  g.drawImage(v, SC.view[0], SC.view[1], SC.view[2], SC.view[3], 0, 0, z.width, z.height);
  const mag = W / SC.view[2];
  $("#sc-zinfo").innerHTML = "Following <b>" + esc(k.label) + " #" + k.id + "</b> · " + mag.toFixed(1) + "× enlarged · source " + Math.round(SC.view[2]) + "×" + Math.round(SC.view[3]) + " pixels" +
    (SC.view[2] < 200 ? ' · <span class="badge warn">few pixels: the enlarged view will be soft</span>' : "");
  $("#sc-zrec").disabled = false;
}

function scLiveList(t) {
  const now = SC.tracks.filter(k => t - k.last_s <= scShown() && t >= k.first_s - 0.05).sort((a, b) => b.box[2] * b.box[3] - a.box[2] * a.box[3]);
  const total = {};
  SC.tracks.forEach(k => { if (k.frames >= 3) total[k.label] = (total[k.label] || 0) + 1; });
  $("#sc-live").innerHTML = (now.length ? '<table class="t small"><tr><th>In view now</th><th>Sure</th><th>Seen for</th><th></th></tr>' + now.slice(0, 10).map(k =>
    "<tr><td>" + (k.id === SC.focus ? "◎ " : "") + esc(k.label) + " #" + k.id + "</td><td>" + Math.round(100 * k.cur) + "%</td><td>" + (k.last_s - k.first_s).toFixed(1) + " s</td><td>" +
    (k.id === SC.focus ? "" : '<button class="btn quiet" data-scf="' + k.id + '">Follow</button>') + "</td></tr>").join("") + "</table>" : '<p class="muted small">Nothing recognized in view.</p>') +
    '<p class="small">This scan so far: ' + (Object.keys(total).length ? Object.entries(total).sort((a, b) => b[1] - a[1]).map(([l, n]) => n + " " + esc(l)).join(", ") : "nothing yet") + "</p>";
}

async function scLoop() {
  let det;
  try { det = await scDetector(); } catch (e) { $("#sc-on").checked = false; SC.on = false; return; }
  const v = $("#vd-video");
  let n = 0;
  const step = () => {
    if (!SC.on) { scDraw(v, 0); return; }
    if (v.readyState >= 2 && v.videoWidth) {
      const t = scNow(v), now = performance.now();
      if (!v.srcObject && t + 0.5 < SC.lastT) SC.tracks.forEach(k => { k.last_s = Math.min(k.last_s, t - 10); });   // the file was rewound
      SC.lastT = t;
      if (now - SC.lastDet >= 1000 / Number($("#sc-fps").value) && (v.srcObject || !v.paused || SC.frames === 0)) {
        SC.lastDet = now;
        const min = Number($("#sc-min").value), W = v.videoWidth, H = v.videoHeight;
        const r = det.detectForVideo(v, now);
        const dets = (r.detections || []).map(d => ({ label: d.categories[0].categoryName, score: d.categories[0].score,
          box: [d.boundingBox.originX / W, d.boundingBox.originY / H, d.boundingBox.width / W, d.boundingBox.height / H] })).filter(d => d.score >= min);
        if (SC.lastDetT !== null && t > SC.lastDetT) SC.dt = 0.8 * SC.dt + 0.2 * Math.min(3, t - SC.lastDetT);   // how often detection really runs
        SC.lastDetT = t;
        scTrack(dets, t); SC.frames++;
        if (n++ % 3 === 0) scLiveList(t);
      }
      scDraw(v, t); scZoom(v, t);
    }
    requestAnimationFrame(step);
  };
  step();
}

// click a box in the picture to follow it
function scClick(e) {
  if (!SC.on) return;
  const v = $("#vd-video"), r = v.getBoundingClientRect();
  const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height, t = scNow(v);
  const hit = SC.tracks.filter(k => t - k.last_s <= scShown() && px >= k.box[0] && px <= k.box[0] + k.box[2] && py >= k.box[1] && py <= k.box[1] + k.box[3])
    .sort((a, b) => a.box[2] * a.box[3] - b.box[2] * b.box[3])[0];
  if (hit) { SC.focus = hit.id; SC.view = null; e.preventDefault(); e.stopPropagation(); }
}

function scRecord() {
  if (SC.rec && SC.rec.state === "recording") { SC.rec.stop(); return; }
  const k = SC.tracks.find(x => x.id === SC.focus);
  if (!k) return;
  if (k.label === "person" && !$("#sc-consent").checked) { toast("Tick the box first: recording an enlarged person is for people who know and agree, or public talks and broadcasts.", true); return; }
  const v = $("#vd-video"), stream = $("#sc-zoom").captureStream(30);
  const src = VD.stream || (v.captureStream ? v.captureStream() : null);
  if (src) src.getAudioTracks().forEach(a => stream.addTrack(a));
  const types = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"];
  const mimeType = types.find(x => window.MediaRecorder && MediaRecorder.isTypeSupported(x)) || "";
  SC.chunks = [];
  SC.rec = new MediaRecorder(stream, mimeType ? { mimeType, videoBitsPerSecond: 6000000 } : {});
  SC.rec.ondataavailable = ev => { if (ev.data && ev.data.size) SC.chunks.push(ev.data); };
  SC.rec.onstop = () => {
    const secs = (performance.now() - SC.recT0) / 1000;
    $("#sc-zrec").textContent = "⏺ Record the enlarged view"; $("#sc-zrec").classList.remove("busy");
    const blob = new Blob(SC.chunks, { type: SC.rec.mimeType || "video/webm" });
    if (typeof vdLog === "function") vdLog("enlarged view recorded", k.label + " " + (blob.size / 1e6).toFixed(1) + " MB", "ok", secs);
    scSave(true).catch(() => {});
    SC.on = false; $("#sc-on").checked = false;
    vdLoadBlob(blob, "enlarged " + k.label + " (" + secs.toFixed(2) + " s)");
    toast("The enlarged view is loaded below for lip-reading (steps 2–4).");
  };
  SC.recT0 = performance.now();
  SC.rec.start(250);
  $("#sc-zrec").textContent = "⏹ Stop recording"; $("#sc-zrec").classList.add("busy");
}

async function scSave(quiet) {
  const tracks = SC.tracks.filter(k => k.frames >= 3).map(k => ({ label: k.label, first_s: k.first_s, last_s: k.last_s, frames: k.frames, score: k.score,
    box: k.best, followed: k.id === SC.focus }));
  if (!tracks.length) { if (!quiet) toast("Nothing recognized yet to save."); return null; }
  const v = $("#vd-video"), file = !v.srcObject;
  const r = await api("/api/scan/save", { label: $("#sc-label").value.trim() || (file ? "video file" : VD.kind || "camera") + " " + new Date().toLocaleString(),
    source: file ? "file" : (VD.kind || "camera"), started: SC.started, seconds: Math.max(0, ...tracks.map(k => k.last_s)), frames: SC.frames, tracks });
  $("#sc-saved").innerHTML = "✔ Saved as scan " + r.session_id + ": " + esc(r.summary) + ".";
  scReset();
  scSessions();
  return r;
}

async function scSessions() {
  const r = await api("/api/scan/sessions");
  $("#sc-sessions").innerHTML = r.sessions.length ? '<table class="t small"><tr><th>#</th><th>Name</th><th>Source</th><th>Started (UTC)</th><th>Length</th><th>Seen</th><th></th></tr>' +
    r.sessions.map(s => "<tr><td>" + s.id + "</td><td>" + esc(s.label) + "</td><td>" + esc(s.source) + "</td><td>" + esc(s.started.replace("T", " ").replace("Z", "")) + "</td><td>" +
      Number(s.seconds).toFixed(1) + " s</td><td>" + esc(s.summary) + '</td><td><button class="btn quiet" data-scdel="' + s.id + '">Delete</button></td></tr>').join("") + "</table>" :
    '<p class="muted small">No scans saved yet.</p>';
}

async function scAsk(q) {
  q = (q || $("#sc-q").value).trim();
  if (!q) return;
  const v = $("#vd-video"), t = scNow(v);
  const seen = SC.tracks.filter(k => t - k.last_s <= scShown());
  const f = seen.find(k => k.id === SC.focus) || seen.sort((a, b) => b.box[2] * b.box[3] - a.box[2] * a.box[3])[0];
  const r = await api("/api/scan/query", { q, tz_min: -new Date().getTimezoneOffset(), live: f ? { label: f.label, score: f.cur } : null });
  let h = '<div class="note"><b>' + esc(r.answer) + "</b></div>";
  if (r.translations && Object.keys(r.translations).length) {
    h += (r.definition ? '<p class="small"><b>' + esc(r.word) + ":</b> " + esc(r.definition) + ' <span class="muted">(Webster 1913)</span></p>' : "") +
      '<table class="t small"><tr><th>Language</th><th>Word</th></tr>' + Object.values(r.translations).map(x => "<tr><td>" + esc(x.language) + "</td><td>" + esc(x.forms.join(", ")) + "</td></tr>").join("") + "</table>";
  }
  if (r.matches && r.matches.length) {
    h += '<table class="t small"><tr><th>Scan</th><th>Object</th><th>Seen (UTC)</th><th>Into the scan</th><th>Sure</th></tr>' + r.matches.map(m => "<tr><td>" + m.session_id + " · " + esc(m.session_label) +
      "</td><td>" + esc(m.label) + "</td><td>" + esc(m.first_at.replace("T", " ").replace("Z", "")) + "</td><td>" + Number(m.first_s).toFixed(1) + "–" + Number(m.last_s).toFixed(1) + " s</td><td>" +
      Math.round(100 * m.score) + "%</td></tr>").join("") + "</table>";
  }
  $("#sc-answer").innerHTML = h;
  if ($("#sc-speak").checked && window.speechSynthesis) { speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(r.answer)); }
}

function scMic() {
  const R = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!R) { toast("This browser cannot listen; type the question instead.", true); return; }
  const rec = new R(); rec.lang = "en-US"; rec.interimResults = false; rec.maxAlternatives = 1;
  $("#sc-mic").classList.add("busy");
  rec.onresult = e => { const q = e.results[0][0].transcript; $("#sc-q").value = q; scAsk(q); };
  rec.onend = () => $("#sc-mic").classList.remove("busy");
  rec.onerror = e => toast("Could not hear the question (" + e.error + ").", true);
  rec.start();
}

document.addEventListener("DOMContentLoaded", () => {
  if (!$("#sc-card")) return;
  $("#sc-on").onchange = e => {
    SC.on = e.target.checked;
    if (SC.on) { scReset(); scLoop(); $("#sc-state").textContent = "Scanning."; }
    else { if (SC.tracks.some(k => k.frames >= 3)) scSave(true).catch(() => {}); $("#sc-state").textContent = "Scan off."; }
  };
  $(".vd-wrap").addEventListener("click", scClick, true);
  $("#sc-live").addEventListener("click", e => { const b = e.target.closest("[data-scf]"); if (b) { SC.focus = Number(b.dataset.scf); SC.view = null; } });
  $("#sc-unfollow").onclick = () => { SC.focus = null; $("#sc-kind").value = ""; };
  $("#sc-zrec").onclick = scRecord;
  $("#sc-save").onclick = () => scSave(false);
  $("#sc-ask").onclick = () => scAsk();
  $("#sc-mic").onclick = scMic;
  onEnter($("#sc-q"), () => scAsk());
  $("#sc-sessions").addEventListener("click", async e => { const b = e.target.closest("[data-scdel]"); if (b) { await api("/api/scan/delete", { id: Number(b.dataset.scdel) }); scSessions(); } });
  scSessions().catch(() => {});
});
