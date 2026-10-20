"use strict";
// Quality Lab (Speech → Quality lab): each avatar test is recorded as a video with every word of the script, measured
// with the face tracker the same way as human reference clips, scored against them, and used to propose the next
// calibration. Only the admin approves a calibration; every face outside the lab speaks with the approved one.
const QL = { busy: false };
const QL_SCRIPTS = [
  "Peter picked a few bright blue boats while Martha thought about the moon.",
  "Will you choose the cheese or the juice? Everybody laughed when Joe said yes.",
  "Five quick vans whizzed through the village just as the judge began to speak.",
  "My mother made warm bread, and we thanked her with a happy song.",
];

function qlWords(t) { return (String(t).match(/[\p{L}\p{N}']+/gu) || []).filter(w => /[\p{L}\p{N}]/u.test(w)); }
function qlB64(blob) { return new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(blob); }); }
const qlPct = (a, p) => { if (!a.length) return 0; const s = a.slice().sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
const qlMean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0;
const qlStd = a => { const m = qlMean(a); return Math.sqrt(qlMean(a.map(x => (x - m) ** 2))); };

// Measure a video (avatar or human) with the face tracker, frame by frame, plus its sound envelope.
async function qlMeasure(url, note) {
  const lm = await tracker();
  const v = document.createElement("video"); v.src = url; v.muted = true; v.playsInline = true; v.style.width = "240px";
  const box = $("#ql-measure"); box.innerHTML = ""; box.appendChild(v);
  await new Promise((res, rej) => { v.onloadeddata = res; v.onerror = () => rej(new Error("the video could not be read")); });
  // step through every frame (seek, measure, next) so no frame is skipped however slow the computer
  if (!isFinite(v.duration)) { await new Promise(res => { v.ondurationchange = () => { if (isFinite(v.duration)) res(); }; v.currentTime = 1e9; setTimeout(res, 3000); }); }
  const dur = isFinite(v.duration) ? v.duration : 0, fr = [], fps = 30;
  if (!QL.cv) QL.cv = document.createElement("canvas");
  for (let t = 0; t < dur; t += 1 / fps) {
    await new Promise(res => { v.onseeked = res; v.currentTime = t; });
    const cv = QL.cv; cv.width = v.videoWidth; cv.height = v.videoHeight; cv.getContext("2d").drawImage(v, 0, 0);
    QL.ts = Math.max((QL.ts || 0) + 1, performance.now());
    const r = lm.detectForVideo(cv, QL.ts), L = r.faceLandmarks && r.faceLandmarks[0];
    if (L) { const W = cv.width, H = cv.height, d = (a, b) => Math.hypot((L[a].x - L[b].x) * W, (L[a].y - L[b].y) * H);
      fr.push({ t, w: d(61, 291), ap: d(13, 14), up: d(0, 13), lo: d(14, 17) }); } else fr.push({ t, miss: 1 });
    if (note && fr.length % 10 === 0) note("measuring the mouth, " + t.toFixed(1) + " of " + dur.toFixed(1) + " s");
  }
  // sound envelope at the frame times
  let env = fr.map(() => 0);
  try {
    const buf = await (await fetch(url)).arrayBuffer(), ac = new (window.AudioContext || window.webkitAudioContext)();
    const au = await ac.decodeAudioData(buf), ch = au.getChannelData(0), sr = au.sampleRate;
    env = fr.map(f => { const c = Math.floor(f.t * sr), h = Math.floor(0.015 * sr); let s = 0, n = 0;
      for (let i = Math.max(0, c - h); i < Math.min(ch.length, c + h); i++) { s += ch[i] * ch[i]; n++; } return n ? Math.sqrt(s / n) : 0; });
    ac.close();
  } catch (e) {}
  const ok = fr.map((f, i) => [f, env[i]]).filter(([f]) => !f.miss);
  if (ok.length < 10) throw new Error("the face was not found in enough frames");
  const W0 = qlPct(ok.map(([f]) => f.w), 0.5), emax = Math.max(...ok.map(x => x[1]), 1e-9);
  const sp = ok.filter(([, e]) => e > 0.12 * emax).map(([f]) => f);
  const S = sp.length > 5 ? sp : ok.map(([f]) => f);
  const ap = S.map(f => f.ap / W0), vel = [], jerk = [];
  for (let i = 1; i < ok.length; i++) { const a = ok[i - 1][0], b = ok[i][0], dt = b.t - a.t; if (dt > 0) vel.push(Math.abs(b.ap - a.ap) / W0 / dt); }
  for (let i = 2; i < ok.length; i++) { const a = ok[i - 2][0], b = ok[i - 1][0], c = ok[i][0], dt = (c.t - a.t) / 2;
    if (dt > 0) jerk.push((c.ap - 2 * b.ap + a.ap) / W0 / (dt * dt)); }
  // lips vs sound: the lag (ms) at which the opening best follows the loudness
  const A = ok.map(([f]) => f.ap / W0), E = ok.map(x => x[1]), z = a => { const m = qlMean(a), s = qlStd(a) || 1; return a.map(x => (x - m) / s); };
  const za = z(A), ze = z(E), fpsM = ok.length / Math.max(0.1, ok[ok.length - 1][0].t - ok[0][0].t);
  let best = [0, -Infinity];
  for (let k = -Math.round(0.3 * fpsM); k <= Math.round(0.3 * fpsM); k++) { let s = 0, n = 0;
    for (let i = 0; i < za.length; i++) { const j = i + k; if (j >= 0 && j < za.length) { s += za[j] * ze[i]; n++; } } if (n && s / n > best[1]) best = [k, s / n]; }
  return { aperture_mean: qlMean(ap), aperture_p90: qlPct(ap, 0.9), width_var: qlStd(S.map(f => f.w / W0)),
    upper_thick_cv: qlStd(S.map(f => f.up)) / (qlMean(S.map(f => f.up)) || 1), lower_thick_cv: qlStd(S.map(f => f.lo)) / (qlMean(S.map(f => f.lo)) || 1),
    velocity_p90: qlPct(vel, 0.9), jerk_rms: Math.sqrt(qlMean(jerk.map(x => x * x))), closure_rate: S.filter(f => f.ap / W0 < 0.04).length / S.length,
    av_lag_ms: 1000 * best[0] / fpsM, frames: fr.length, tracked: ok.length / fr.length };
}

// Record one test: the chosen avatar says the script; picture and sound are recorded together.
async function qlRecordTest(script) {
  const note = m => { $("#ql-note").textContent = m; };
  const cal = await api("/api/qlab/active?lab=1");
  const list = (await api("/api/avatars/list")).avatars.filter(a => a.analysed);
  const want = Number(typeof faceChoice === "function" ? faceChoice() : 0), av = list.find(a => a.id === want) || list[0];
  if (!av) throw new Error("no analysed avatar — add faces in the Avatar studio");
  note("Speaking the script with " + av.name + " (calibration v" + cal.version + ")…");
  const body = { id: av.id, text: script, profile: typeof SP !== "undefined" && SP.profile ? { emotion: SP.profile.emotion, lang: SP.profile.lang } : {} };
  if ($("#sp-engine") && $("#sp-engine").value) { body.engine = $("#sp-engine").value; body.voice = ($("#sp-voice") || {}).value || ""; }
  const r = await api("/api/avatars/speak", body);
  const res = await avWaitJob(r.job.job_id, m => note("Face motion: " + m));
  const full = await api("/api/avatars/get?id=" + av.id);
  const stage = $("#ql-stage"); stage.innerHTML = "";
  const f = new DepthFace(stage, { imageUrl: "/api/avatars/image?id=" + av.id, landmarks: full.landmarks, label: full.label }, { cal: cal.params });
  await f.ready;
  const audio = new Audio("/api/speech/audio?name=" + encodeURIComponent(r.audio)); audio.preload = "auto";
  await new Promise((ok, bad) => { audio.oncanplaythrough = ok; audio.onerror = () => bad(new Error("the speech could not be loaded")); audio.load(); });
  const ac = new (window.AudioContext || window.webkitAudioContext)(), src = ac.createMediaElementSource(audio), dest = ac.createMediaStreamDestination();
  src.connect(dest); src.connect(ac.destination);
  const stream = new MediaStream([...f.cv.captureStream(30).getVideoTracks(), ...dest.stream.getAudioTracks()]);
  const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find(m => MediaRecorder.isTypeSupported(m));
  const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 4000000 }), chunks = [];
  rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  const track = { visemes: res.visemes || [], motion: res.motion };
  let raf; const loop = () => { f.frame(track, audio.currentTime); raf = requestAnimationFrame(loop); };
  rec.start(250); const t0 = performance.now(); loop();
  await new Promise(ok => setTimeout(ok, 300));
  note("Recording — every word of the script…");
  await ac.resume(); await audio.play();
  await new Promise(ok => { audio.onended = ok; });
  await new Promise(ok => setTimeout(ok, 400));
  await new Promise(ok => { rec.onstop = ok; rec.stop(); });
  cancelAnimationFrame(raf); ac.close();
  const blob = new Blob(chunks, { type: "video/webm" }), duration = (performance.now() - t0) / 1000;
  const wText = qlWords(script), wTimed = (res.words || []).map(w => w.word);
  note("Saving the test video…");
  const smp = await api("/api/qlab/sample", { kind: "avatar", video_b64: await qlB64(blob), avatar_id: av.id, avatar_name: av.name, script,
    words_text: wText.length, words_timed: wTimed.length, duration, audio_duration: audio.duration });
  note("Measuring the video against human speech…");
  const m = await qlMeasure(URL.createObjectURL(blob), note);
  const out = await api("/api/qlab/metrics", { id: smp.id, metrics: m });
  if ($("#ql-auto").checked && out.proposal_notes && out.proposal_notes.length) await api("/api/qlab/candidate", { params: out.proposal, origin: "auto (sample " + smp.id + ")" });
  qlShowResult(smp, out, wText, wTimed);
  note("Done: sample " + smp.id + " · score " + out.score + " / 100 (" + out.basis + ")");
  return out;
}

function qlShowResult(smp, out, wText, wTimed) {
  const rows = Object.entries(out.scores || {}).map(([k, s]) => "<tr><td>" + esc(QL.metrics[k] || k) + "</td><td>" + s.value + "</td><td>" + s.human.join(" – ") + "</td><td><b>" +
    s.score + "</b></td><td>" + (s.score >= 99.9 ? cmTag("human", "good") : cmTag(s.verdict, "warn")) + "</td></tr>").join("");
  $("#ql-result").innerHTML = '<div class="card"><h3>Sample ' + smp.id + " — score " + out.score + ' / 100 <span class="small muted">' + esc(out.basis) + "</span></h3>" +
    (smp.complete ? '<p class="small">✔ Every word recorded (' + wText.length + " words; video " + smp.duration.toFixed(1) + " s ≥ speech " + smp.audio_duration.toFixed(1) + " s)</p>"
      : '<div class="note bad small">Not every word was recorded (' + wTimed.length + " of " + wText.length + " words timed) — this sample is marked incomplete.</div>") +
    '<video controls src="/api/qlab/video?id=' + smp.id + '" style="max-width:420px;width:100%"></video>' +
    '<table class="t small"><thead><tr><th>Measure</th><th>Avatar</th><th>Human range</th><th>Score</th><th></th></tr></thead><tbody>' + rows + "</tbody></table>" +
    (out.proposal_notes && out.proposal_notes.length ? '<p class="small"><b>Next calibration' + ($("#ql-auto").checked ? " (applied)" : " (proposed)") + ":</b> " + esc(out.proposal_notes.join("; ")) + "</p>" : '<p class="small">All measures within the human range.</p>') +
    '<div class="row small"><input id="ql-vnote" class="grow" placeholder="your note on this sample"><button class="btn small" data-qv="approved">👍 Good</button><button class="btn quiet small" data-qv="rejected">👎 Not good enough</button></div></div>';
  $$("#ql-result [data-qv]").forEach(b => b.onclick = async () => { await api("/api/qlab/verdict", { id: smp.id, verdict: b.dataset.qv, note: $("#ql-vnote").value }); toast("Saved."); qlRefresh(); });
  qlRefresh();
}

async function qlRefresh() {
  const st = await api("/api/qlab/status"), cal = await api("/api/qlab/calibration"), smp = (await api("/api/qlab/list?kind=avatar")).samples, refs = (await api("/api/qlab/list?kind=reference")).samples;
  QL.metrics = cal.metrics;
  const a = cal.approved, c = cal.candidate;
  $("#ql-status").innerHTML = (a ? '<div class="note good">✔ Approved calibration v' + a.version + " (" + esc(a.level || "") + ", " + esc(a.approved_at || "") + ") — every face outside the lab speaks with it.</div>"
    : '<div class="note bad">⚠ No calibration approved yet — faces speak with the default. Keep testing until the quality is right, then approve below.</div>') +
    '<p class="small">Tests: ' + st.samples + " · human references: " + st.references + " · recent average score: " + (st.recent_mean_score == null ? "—" : st.recent_mean_score) + " · ranges " + esc(st.basis) + "</p>";
  const P = (c && c.params) || cal.defaults;
  $("#ql-cal").innerHTML = '<p class="small">Candidate v' + (c ? c.version + " (" + esc(c.origin || "") + ")" : "0 (defaults)") + " — used by the tests in this lab:</p>" +
    Object.keys(cal.defaults).map(k => '<label class="small" style="display:inline-block;margin:2px 8px">' + k + ' <input type="number" step="0.01" data-qp="' + k + '" value="' + P[k] + '" style="width:80px"></label>').join("") +
    '<div class="row small"><button class="btn quiet small" id="ql-savecand">Save as new candidate</button></div>' +
    '<div class="row small"><input id="ql-pass" type="password" placeholder="admin passphrase"><input id="ql-level" placeholder="quality level, e.g. production" value="production">' +
    '<button class="btn small" id="ql-approve">✔ Approve candidate v' + (c ? c.version : 0) + '</button><button class="btn quiet small" id="ql-ship">Ship approved with the installer</button>' +
    '<a class="small" href="/api/qlab/export" download="calibration.json">export approved</a></div>';
  $("#ql-savecand").onclick = async () => { const p = {}; $$("#ql-cal [data-qp]").forEach(i => p[i.dataset.qp] = Number(i.value)); await api("/api/qlab/candidate", { params: p, origin: "admin" }); toast("Saved."); qlRefresh(); };
  $("#ql-approve").onclick = async () => { if (!c) return toast("Run a test first."); try { await api("/api/qlab/approve", { version: c.version, passphrase: $("#ql-pass").value, level: $("#ql-level").value });
    window.QB_CAL = await api("/api/qlab/active"); toast("Approved — all faces now speak with v" + c.version + "."); qlRefresh(); } catch (e) { toast(e.message); } };
  $("#ql-ship").onclick = async () => { try { const r = await api("/api/qlab/ship", { passphrase: $("#ql-pass").value }); toast("Written: " + r.written); } catch (e) { toast(e.message); } };
  $("#ql-samples").innerHTML = smp.length ? '<table class="t small"><thead><tr><th>#</th><th>When</th><th>Face</th><th>Script</th><th>Cal.</th><th>Score</th><th>Words</th><th>Verdict</th><th></th></tr></thead><tbody>' +
    smp.map(s => "<tr><td>" + s.id + "</td><td>" + esc(s.created) + "</td><td>" + esc(s.avatar_name || "") + "</td><td>" + esc((s.script || "").slice(0, 40)) + "…</td><td>v" + (s.calibration || 0) +
      "</td><td><b>" + (s.score == null ? "—" : s.score) + "</b></td><td>" + (s.complete ? "✔ all" : "⚠ " + s.words_timed + "/" + s.words_text) + "</td><td>" + esc(s.verdict) + '</td><td><a href="/api/qlab/video?id=' + s.id + '" target="_blank">video</a></td></tr>').join("") + "</tbody></table>"
    : '<p class="small muted">No tests yet.</p>';
  $("#ql-refs").innerHTML = refs.length ? refs.map(r => '<div class="small">#' + r.id + " " + esc(r.source) + (r.licence ? " · " + esc(r.licence) : "") + (r.metrics ? " · measured" : " · ⚠ not measured") +
    ' · <a href="/api/qlab/video?id=' + r.id + '" target="_blank">video</a> · <a href="#" data-qdel="' + r.id + '">remove</a></div>').join("") : '<p class="small muted">No human references yet — the scores use provisional ranges.</p>';
  $$("#ql-refs [data-qdel]").forEach(x => x.onclick = async e => { e.preventDefault(); await api("/api/qlab/delete", { id: Number(x.dataset.qdel) }); qlRefresh(); });
}

async function qlAddReference(blob, source, licence) {
  const note = m => { $("#ql-rnote").textContent = m; };
  note("Saving the reference…");
  const smp = await api("/api/qlab/sample", { kind: "reference", video_b64: await qlB64(blob), source, licence });
  note("Measuring the human mouth in the reference…");
  const m = await qlMeasure(URL.createObjectURL(blob), note);
  await api("/api/qlab/metrics", { id: smp.id, metrics: m });
  note("Reference " + smp.id + " added (" + m.frames + " frames, face found in " + Math.round(100 * m.tracked) + "%).");
  qlRefresh();
}

async function qlWebcam() {
  const btn = $("#ql-cam");
  if (QL.cam) { QL.cam.stop(); return; }
  const s = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: true });
  const v = $("#ql-campv"); v.srcObject = s; v.muted = true; v.hidden = false; v.play();
  const rec = new MediaRecorder(s, { mimeType: ["video/webm;codecs=vp9,opus", "video/webm"].find(m => MediaRecorder.isTypeSupported(m)) }), ch = [];
  rec.ondataavailable = e => { if (e.data.size) ch.push(e.data); };
  rec.onstop = async () => { s.getTracks().forEach(t => t.stop()); v.hidden = true; QL.cam = null; btn.textContent = "🎥 Record myself reading the script";
    await qlAddReference(new Blob(ch, { type: "video/webm" }), "own recording (webcam): " + $("#ql-script").value.slice(0, 80), "own"); };
  rec.start(250); QL.cam = rec; btn.textContent = "■ Stop recording";
}

async function renderQualityLab(el) {
  if (!el.dataset.ready) {
    el.dataset.ready = "1";
    el.innerHTML =
      '<div class="card"><h2>🎬 Quality lab <span class="small muted">every test is recorded, measured against real human speech, and calibrates the next one</span></h2><div id="ql-status"></div></div>' +
      '<div class="card"><h2><span class="step">1</span> Record a test</h2>' +
      '<p class="small muted">The face chosen on the Speak tab says the script with the Speak tab\'s voice. The video holds every word; it is then measured with the face tracker exactly like the human references.</p>' +
      '<div class="row"><select id="ql-pick">' + QL_SCRIPTS.map((s, i) => '<option value="' + i + '">Script ' + (i + 1) + ": " + esc(s.slice(0, 50)) + "…</option>").join("") + '<option value="c">My own text</option></select>' +
      '<label class="small"><input type="checkbox" id="ql-auto" checked> calibrate automatically after each test</label></div>' +
      '<textarea id="ql-script" rows="2"></textarea>' +
      '<div class="row"><button class="btn bigbtn" id="ql-go">⏺ Record test</button><button class="btn" id="ql-all">Run all four scripts</button></div>' +
      '<p class="small" id="ql-note" aria-live="polite"></p><div class="grid2"><div id="ql-stage" style="max-width:420px"></div><div id="ql-measure"></div></div><div id="ql-result"></div></div>' +
      '<div class="card"><h2><span class="step">2</span> Human references</h2><p class="small muted">Real people speaking, filmed face-on: record yourself reading the script, or add clips you may use — public domain, Creative Commons, government works, or your own. Only measurements are compared.</p>' +
      '<div class="row"><button class="btn" id="ql-cam">🎥 Record myself reading the script</button></div><video id="ql-campv" hidden style="max-width:320px"></video>' +
      '<div class="row small"><input type="file" id="ql-file" accept="video/mp4,video/webm"><input id="ql-src" class="grow" placeholder="where it comes from (address or description)"><input id="ql-lic" placeholder="licence (e.g. public domain, CC BY)"><button class="btn quiet" id="ql-addref">Add reference</button></div>' +
      '<p class="small" id="ql-rnote"></p><div id="ql-refs"></div></div>' +
      '<div class="card"><h2><span class="step">3</span> Calibration — approved by the admin</h2><div id="ql-cal"></div></div>' +
      '<div class="card"><h2>All tests</h2><div id="ql-samples"></div></div>';
    const setScript = () => { const v = $("#ql-pick").value; $("#ql-script").value = v === "c" ? ($("#sp-text") ? $("#sp-text").value : "") : QL_SCRIPTS[Number(v)]; };
    $("#ql-pick").onchange = setScript; setScript();
    const run = async scripts => { if (QL.busy) return; QL.busy = true;
      try { for (const s of scripts) await qlRecordTest(s); } catch (e) { $("#ql-note").textContent = "Test failed: " + e.message; } finally { QL.busy = false; } };
    $("#ql-go").onclick = () => run([$("#ql-script").value.trim()]);
    $("#ql-all").onclick = () => run(QL_SCRIPTS);
    $("#ql-cam").onclick = () => qlWebcam().catch(e => toast("Camera: " + e.message));
    $("#ql-addref").onclick = async () => { const f = $("#ql-file").files[0]; if (!f) return toast("Choose a video file.");
      try { await qlAddReference(f, $("#ql-src").value.trim(), $("#ql-lic").value.trim()); } catch (e) { $("#ql-rnote").textContent = "Not added: " + e.message; } };
  }
  await qlRefresh();
}
