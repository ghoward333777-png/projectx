// Speech science (Language 1.51): speak any language, read the lips of an uploaded talking head, and measure every
// delivery with the Speech Science Protocol — per word and phrase, and by dialect, accent and emotion — with reports.
const SCI = { voices: [], blob: null, last: null, rows: [] };

function scMd(md) {          // a small Markdown renderer for the reports (headings, tables, lists, bold, code)
  const inl = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
  const out = [], L = String(md || "").split("\n");
  for (let i = 0; i < L.length; i++) {
    const l = L[i];
    if (/^\|/.test(l)) {
      const rows = [];
      while (i < L.length && /^\|/.test(L[i])) { if (!/^\|[-| ]+\|$/.test(L[i])) rows.push(L[i].slice(1, -1).split("|").map(c => c.trim())); i++; }
      i--;
      out.push('<table class="t small"><tr>' + rows[0].map(c => "<th>" + inl(c) + "</th>").join("") + "</tr>" +
        rows.slice(1).map(r => "<tr>" + r.map(c => "<td>" + inl(c) + "</td>").join("") + "</tr>").join("") + "</table>");
    } else if (/^### /.test(l)) out.push("<h4>" + inl(l.slice(4)) + "</h4>");
    else if (/^## /.test(l)) out.push("<h3>" + inl(l.slice(3)) + "</h3>");
    else if (/^# /.test(l)) out.push("<h2>" + inl(l.slice(2)) + "</h2>");
    else if (/^- /.test(l)) out.push("<div>• " + inl(l.slice(2)) + "</div>");
    else if (l.trim()) out.push("<p>" + inl(l) + "</p>");
  }
  return out.join("");
}

async function scInit() {
  if (SCI.ready) return; SCI.ready = true;
  try {
    const r = await api("/api/science/voices");
    SCI.voices = r.voices;
    $("#sc-voice").innerHTML = '<option value="">Detect from the text</option>' + r.voices.map(v => '<option value="' + esc(v.code) + '">' + esc(v.name) + " (" + esc(v.code) + ")" +
      (v.dict ? "" : " — letters only") + "</option>").join("");
    $("#sc-vcount").textContent = r.count + " languages and accents (" + r.with_dictionary + " with a pronunciation dictionary), offline with espeak-ng" + (r.espeak.version ? " " + r.espeak.version : "");
    $("#sc-lang").innerHTML = Object.entries({ en: "English", es: "Spanish", fr: "French", de: "German", it: "Italian", pt: "Portuguese", nl: "Dutch", sv: "Swedish", da: "Danish",
      no: "Norwegian", fi: "Finnish", pl: "Polish", cs: "Czech", el: "Greek", ro: "Romanian", hu: "Hungarian", ca: "Catalan" }).map(([k, n]) => '<option value="' + k + '">' + n + "</option>").join("");
  } catch (e) { $("#sc-vcount").textContent = e.message; }
  scList().catch(() => {}); scReports().catch(() => {});
}

// ---- 1. speak any language
async function scSpeak() {
  const text = $("#sc-text").value.trim();
  if (!text) return toast("Type what should be said.");
  let voice = $("#sc-voice").value;
  if (!voice) { const d = await api("/api/science/detect?text=" + encodeURIComponent(text.slice(0, 400))); voice = d.voice || "en";
    $("#sc-detected").textContent = "Detected: " + voice + (d.how ? " (by its " + d.how + ")" : " (no clear sign — English)"); }
  else $("#sc-detected").textContent = "";
  const res = await fetch("/api/science/speak", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice, rate: +$("#sc-rate").value, pitch: +$("#sc-pitch").value, variant: $("#sc-variant").value }) });
  if (!res.ok) { let m = "Error " + res.status; try { m = (await res.json()).error || m; } catch (e) {} return toast(m, true); }
  const url = URL.createObjectURL(await res.blob());
  $("#sc-player").innerHTML = '<audio controls src="' + url + '"></audio> <a class="btn quiet" download="speech-' + esc(voice) + '.wav" href="' + url + '">⬇ Download WAV</a>';
  $("#sc-player audio").play().catch(() => {});
  try { const ipa = await api("/api/science/ipa?voice=" + encodeURIComponent(voice) + "&text=" + encodeURIComponent(text.slice(0, 200))); $("#sc-ipa").textContent = ipa.ipa ? "/" + ipa.ipa + "/" : ""; } catch (e) {}
}

// ---- 2 & 3. a talking head: read it, measure it
function scLoad(file) {
  SCI.blob = file; SCI.kind = "upload";
  const v = $("#sc-video"); v.src = URL.createObjectURL(file); v.hidden = false;
  $("#sc-read").disabled = $("#sc-measure").disabled = false;
  $("#sc-state").textContent = file.name + " — ready. Press Read the words, or Measure this delivery.";
}

// Frame by frame, by seeking (never by playing): every frame of the file is read whatever the computer's speed, and the
// same file always gives the same frames. The frame rate is measured first from the frames the browser presents.
const SC_RATES = [12, 15, 23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60];
async function scFrameRate(v) {
  if (!v.requestVideoFrameCallback) return 30;
  v.muted = true; v.currentTime = 0;
  await new Promise(r => v.addEventListener("seeked", r, { once: true }));
  let p0 = null, m0 = 0, p1 = null, m1 = 0;
  await new Promise(res => {
    const step = (now, meta) => { if (p0 === null) { p0 = meta.presentedFrames; m0 = meta.mediaTime; } p1 = meta.presentedFrames; m1 = meta.mediaTime;
      if (m1 - m0 > 0.6 || v.ended) { v.pause(); res(); } else v.requestVideoFrameCallback(step); };
    v.requestVideoFrameCallback(step); v.play().catch(res);
    setTimeout(() => { v.pause(); res(); }, 4000);
  });
  const est = m1 > m0 && p1 > p0 ? (p1 - p0) / (m1 - m0) : 30;
  return SC_RATES.reduce((a, b) => Math.abs(b - est) < Math.abs(a - est) ? b : a, 30);
}
async function scTrackSeek(v, onProgress) {
  const lm = await tracker();
  if (v.readyState < 2) await new Promise(r => v.addEventListener("loadeddata", r, { once: true }));
  const fps = await scFrameRate(v), dur = v.duration, n = Math.floor(dur * fps + 1e-6), frames = [];
  v.pause(); v.controls = false;
  for (let i = 0; i < n; i++) {
    const t = (i + 0.5) / fps;                                    // the middle of frame i: the browser shows frame i there
    await new Promise(r => { v.addEventListener("seeked", r, { once: true }); v.currentTime = Math.min(t, dur - 1e-3); });
    const res = lm.detectForVideo(v, Math.round(1000 * t) + 1);
    const f = measureFrame(res, v, i / fps); delete f._L; frames.push(f);
    if (onProgress && i % 3 === 0) onProgress(i / fps, i, n);
  }
  v.controls = true;
  return { frames, fps, tracked: fps, span: n / fps };
}
async function scTrack() {
  const v = $("#sc-video");
  const tr = await scTrackSeek(v, (t, i, n) => { $("#sc-prog").style.width = (100 * i / Math.max(1, n)).toFixed(1) + "%";
    $("#sc-state").textContent = "Reading the face frame by frame: frame " + i + " of " + n + " (" + t.toFixed(2) + " s) — every frame, by seeking"; });
  let env = null, wav = null, note = "";
  try { const au = await decodeTrack(SCI.blob); env = envelope(au); wav = await wavB64(au, 16000); }
  catch (e) { note = " (the sound could not be read: lips only)"; }
  $("#sc-state").textContent = "Read " + tr.frames.length + " frames at " + tr.fps + " frames per second" + note + ".";
  return { frames: tr.frames, env, env_fps: 100, wav_b64: wav, info: { width: v.videoWidth, height: v.videoHeight, fps: tr.fps,
    source: SCI.kind || "upload", seconds: Math.round(tr.span * 100) / 100 } };
}

function scBody(t) {
  return Object.assign(t, { lang: $("#sc-lang").value, script: $("#sc-script").value.trim(), use_stt: $("#sc-stt").checked,
    labels: { speaker: $("#sc-l-speaker").value.trim(), role: $("#sc-l-role").value, dialect: $("#sc-l-dialect").value.trim(), accent: $("#sc-l-accent").value.trim(),
              emotion: $("#sc-l-emotion").value, source: SCI.kind || "upload" } });
}

function scWordsTable(words, src) {
  if (!words || !words.length) return '<p class="muted small">No words.</p>';
  return '<table class="t small"><tr><th>word</th><th>from–to (s)</th><th>confidence</th><th>looks like on the lips</th></tr>' + words.map(w =>
    "<tr><td>" + esc(w.word) + "</td><td>" + (w.from_s ?? w.start_s ?? "").toString() + "–" + (w.to_s ?? w.end_s ?? "").toString() + "</td><td>" +
    (w.confidence !== undefined ? Math.round(100 * w.confidence) + "%" : "—") + "</td><td>" + esc((w.same_on_lips || []).slice(0, 4).join(", ")) + "</td></tr>").join("") + "</table>" +
    '<p class="small muted">Source: ' + esc(src) + "</p>";
}

async function scRead() {
  const btn = $("#sc-read"); buttonStart(btn); let ok = false;
  try {
    const r = await api("/api/science/read", scBody(await scTrack()));
    const lipsErr = r.lips.error ? '<div class="note bad">Lips: ' + esc(r.lips.error) + "</div>" : "";
    $("#sc-out").innerHTML = '<div class="note"><b>Words:</b> ' + esc(r.final.text || "—") + ' <span class="muted small">(from ' + esc(r.final.source) + ")</span></div>" + lipsErr +
      "<h4>Read from the lips</h4><p>" + esc(r.lips.text || "—") + "</p>" + scWordsTable(r.lips.words, "the Visual Speech Engine (HMM over look-alike mouth shapes)") +
      (r.stt ? "<h4>Heard (Speech-to-Text)</h4>" + (r.stt.error ? '<p class="muted">' + esc(r.stt.error) + "</p>" : "<p>" + esc(r.stt.transcript) + " <span class='muted small'>(confidence " +
        Math.round(100 * (r.stt.confidence || 0)) + "%)</span></p>" + scWordsTable(r.stt.words, "Google Speech-to-Text")) : "") +
      (r.vse_script ? '<p class="small">Lips vs your script: <b>' + r.vse_script.agreement + "%</b> agreement (chance-corrected) — " + esc(r.vse_script.verdict || "") + "</p>" : "") +
      '<p class="small muted">Lip reading alone is uncertain: many sounds look alike on the lips (p/b/m, f/v, t/d/n …), so each word lists its look-alikes. ' +
      "Words are most reliable with the sound (Speech-to-Text) or a script.</p>";
    ok = true;
  } catch (e) { $("#sc-out").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; }
  finally { buttonEnd(btn, ok); $("#sc-prog").style.width = ok ? "100%" : "0"; }
}

function scDeliveryHtml(d) {
  const v = d.verdict, cls = v.result === "PASS" ? "good" : v.result === "FAIL" ? "bad" : "";
  const sc = d.scores, f = x => x === undefined || x === null ? "—" : (+x).toFixed(1);
  return '<div class="note ' + cls + '" style="font-size:1.05em"><b>' + v.result + "</b> · Delivery Index " + f(sc.DI) + " · Articulation Conformance " + f(sc.AC) +
    " · Naturalness " + f(sc.naturalness) + (sc.sync !== undefined ? " · Sync " + f(sc.sync) : "") + (sc.intelligibility !== undefined ? " · Intelligibility " + f(sc.intelligibility) : "") + "</div>" +
    (v.why.length ? "<h4>Why</h4>" + v.why.map(w => "<div>• " + esc(w) + "</div>").join("") : "") +
    '<table class="t small"><tr><th>criterion</th><th>rule</th><th>measured</th><th></th><th>status</th></tr>' + v.criteria.map(c => "<tr><td>" + esc(c.criterion) + "</td><td>" + esc(c.rule) +
      "</td><td>" + (c.value ?? "—") + "</td><td>" + (c.passed === null ? "not measured" : c.passed ? "pass" : "<b>FAIL</b>") + '</td><td class="muted">' + esc(c.status || "") + "</td></tr>").join("") + "</table>" +
    '<h4>Words and sounds</h4><table class="t small"><tr><th>word</th><th>IPA</th><th>time (s)</th><th>AC</th><th>sounds (viseme AC)</th></tr>' + d.words.map(w =>
      "<tr><td>" + esc(w.word) + "</td><td>/" + esc(w.ipa) + "/</td><td>" + w.start.toFixed(2) + "–" + w.end.toFixed(2) + "</td><td><b>" + Math.round(w.AC) + "</b></td><td>" +
      w.sounds.map(s => '<span title="' + esc(s.note || "on target") + '" style="white-space:nowrap;' + (s.AC < 50 ? "color:#b3261e;font-weight:600" : "") + '">' + esc(s.symbol) + "·" + esc(s.viseme) + " " +
        Math.round(s.AC) + "</span>").join(" ") + "</td></tr>").join("") + "</table>" +
    '<p class="small">Timing: ' + esc((d.inputs || {}).timing || "—") + " · expectations: " + esc((d.expectation_basis || []).join(", ")) + " · fingerprint " + esc(d.fingerprint.slice(0, 16)) +
    (d.report ? ' · <a href="#" data-screp="' + esc(d.report) + '">full report</a> · <a href="/api/science/report?name=' + encodeURIComponent(d.report) + '" download="' + esc(d.report) + '.md">download .md</a>' +
      ' · <a href="/api/science/report?fmt=json&name=' + encodeURIComponent(d.report) + '" download="' + esc(d.report) + '.json">data .json</a>' : "") + "</p>";
}

async function scMeasure() {
  const btn = $("#sc-measure"); buttonStart(btn); let ok = false;
  try {
    const d = await api("/api/science/measure", scBody(await scTrack()));
    SCI.last = d; $("#sc-out").innerHTML = scDeliveryHtml(d); scWire($("#sc-out"));
    scList().catch(() => {}); scReports().catch(() => {}); ok = true;
  } catch (e) { $("#sc-out").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; }
  finally { buttonEnd(btn, ok); $("#sc-prog").style.width = ok ? "100%" : "0"; }
}

// an avatar says the text; its own canvas is recorded with the sound, then measured exactly like a person on video
async function scAvatar() {
  const btn = $("#sc-avatar"); buttonStart(btn); let ok = false;
  try {
    const text = $("#sc-script").value.trim();
    if (!text) throw new Error("Type the script the avatar should say.");
    const list = (await api("/api/avatars/list")).avatars.filter(a => a.analysed && !a.hidden);
    const want = +$("#sc-av").value, av = list.find(a => a.id === want) || list[0];
    if (!av) throw new Error("No analysed avatar.");
    $("#sc-state").textContent = av.name + " is speaking the script…";
    const r = await api("/api/avatars/speak", { id: av.id, text, profile: { emotion: $("#sc-l-emotion").value || undefined, lang: $("#sc-lang").value } });
    const res = await avWaitJob(r.job.job_id, m => { $("#sc-state").textContent = "Face motion: " + m; });
    const full = await api("/api/avatars/get?id=" + av.id), stage = $("#sc-stage"); stage.innerHTML = ""; stage.hidden = false;
    const f = new DepthFace(stage, { imageUrl: "/api/avatars/image?id=" + av.id, landmarks: full.landmarks, label: full.label, body: full.kind === "body" });
    await f.ready;
    const audio = new Audio("/api/speech/audio?name=" + encodeURIComponent(r.audio)); audio.preload = "auto";
    await new Promise((y, n) => { audio.oncanplaythrough = y; audio.onerror = () => n(new Error("the speech could not be loaded")); audio.load(); });
    const ac = new (window.AudioContext || window.webkitAudioContext)(), src = ac.createMediaElementSource(audio), dest = ac.createMediaStreamDestination();
    src.connect(dest); src.connect(ac.destination);
    const stream = new MediaStream([...f.cv.captureStream(30).getVideoTracks(), ...dest.stream.getAudioTracks()]);
    const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find(m => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 4000000 }), chunks = [];
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    const track = { visemes: [], motion: res.motion, mouth: res.mouth };
    let raf; const loop = () => { f.frame(track, audio.currentTime); raf = requestAnimationFrame(loop); };
    rec.start(250); loop(); await new Promise(y => setTimeout(y, 300));
    $("#sc-state").textContent = "Recording the avatar's own picture and sound…";
    await ac.resume(); await audio.play();
    await new Promise(y => { audio.onended = y; setTimeout(y, (audio.duration || 30) * 1000 + 3000); });   // never waits forever
    await new Promise(y => setTimeout(y, 400)); await new Promise(y => { rec.onstop = y; rec.stop(); });
    cancelAnimationFrame(raf); ac.close();
    SCI.blob = new Blob(chunks, { type: "video/webm" }); SCI.kind = "avatar:" + av.name;
    const v = $("#sc-video"); v.src = URL.createObjectURL(SCI.blob); v.hidden = false;
    $("#sc-read").disabled = $("#sc-measure").disabled = false;
    ok = true; buttonEnd(btn, ok);
    await scMeasure();
  } catch (e) { $("#sc-out").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; buttonEnd(btn, false); }
}

// ---- 4. the corpus and group comparisons
async function scList() {
  const r = await api("/api/science/deliveries"); SCI.rows = r.deliveries;
  $("#sc-list").innerHTML = r.deliveries.length ? '<table class="t small"><tr><th>#</th><th>when</th><th>text</th><th>result</th><th>DI</th><th>speaker</th><th>role</th><th>dialect</th><th>accent</th><th>emotion</th><th></th></tr>' +
    r.deliveries.map(d => '<tr data-id="' + d.id + '"><td>' + d.id + "</td><td>" + esc(d.at.replace("T", " ")) + "</td><td>" + esc((d.text || "").slice(0, 40)) + "</td><td>" + esc(d.result) + "</td><td>" + (d.DI || 0).toFixed(0) +
      "</td>" + ["speaker", "role", "dialect", "accent", "emotion"].map(k => '<td><input data-k="' + k + '" value="' + esc(d.labels[k] || "") + '" style="width:6.5em"></td>').join("") +
      '<td><button class="btn quiet small" data-scsave>Save</button> <button class="btn quiet small" data-scview>View</button> <button class="btn quiet small" data-scdel>✕</button></td></tr>').join("") + "</table>"
    : '<p class="muted small">No measured deliveries yet. Measure a video or an avatar above; each one is kept here with its labels.</p>';
  $$("#sc-list [data-scsave]").forEach(b => b.onclick = async () => { const tr = b.closest("tr"), lab = {};
    tr.querySelectorAll("input[data-k]").forEach(i => { lab[i.dataset.k] = i.value.trim(); });
    const keep = (SCI.rows.find(x => x.id === +tr.dataset.id) || {}).labels || {};
    await api("/api/science/label", { id: +tr.dataset.id, labels: Object.assign({}, keep, lab) }); toast("Labels saved"); });
  $$("#sc-list [data-scview]").forEach(b => b.onclick = async () => { const d = await api("/api/science/delivery?id=" + b.closest("tr").dataset.id);
    $("#sc-out").innerHTML = scDeliveryHtml(d); scWire($("#sc-out")); $("#sc-out").scrollIntoView({ behavior: "smooth" }); });
  $$("#sc-list [data-scdel]").forEach(b => b.onclick = async () => { if (!confirm("Delete this measured delivery?")) return;
    await api("/api/science/delete", { id: +b.closest("tr").dataset.id }); scList(); });
}

async function scCompare() {
  try {
    const c = await api("/api/science/compare", { by: $("#sc-by").value, baseline: $("#sc-base").value.trim(), word: $("#sc-word").value.trim() });
    const rep = await (await fetch("/api/science/report?name=" + encodeURIComponent(c.report))).text();
    $("#sc-cmp").innerHTML = scMd(rep); scReports().catch(() => {});
  } catch (e) { $("#sc-cmp").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; }
}

// ---- 5. reports and the protocol
async function scReports() {
  const r = await api("/api/science/reports");
  $("#sc-reps").innerHTML = r.reports.length ? r.reports.slice(0, 40).map(n => '<div class="small"><a href="#" data-screp="' + esc(n) + '">' + esc(n) + '</a> · <a href="/api/science/report?name=' +
    encodeURIComponent(n) + '" download="' + esc(n) + '.md">.md</a> · <a href="/api/science/report?fmt=json&name=' + encodeURIComponent(n) + '" download="' + esc(n) + '.json">.json</a></div>').join("") : '<p class="muted small">No reports yet.</p>';
  scWire($("#sc-reps"));
}
function scWire(el) {
  el.querySelectorAll("[data-screp]").forEach(a => a.onclick = async e => { e.preventDefault();
    const t = await (await fetch("/api/science/report?name=" + encodeURIComponent(a.dataset.screp))).text(); $("#sc-repview").innerHTML = scMd(t); $("#sc-repview").scrollIntoView({ behavior: "smooth" }); });
}
async function scProtocol() { const p = await api("/api/science/protocol"); $("#sc-repview").innerHTML = scMd(p.methods); }

async function scAvatars() {
  if (SCI.avs) return; SCI.avs = true;
  try { const l = (await api("/api/avatars/list")).avatars.filter(a => a.analysed && !a.hidden);
    $("#sc-av").innerHTML = l.map(a => '<option value="' + a.id + '">' + esc(a.name) + "</option>").join(""); } catch (e) { /* none */ }
}
function scSetup() {
  const b = document.querySelector('nav.tabs button[data-tab="science"]');
  if (!b) return;
  b.addEventListener("click", () => { scInit(); scAvatars(); });
  $("#sc-say").onclick = () => scSpeak().catch(e => toast(e.message, true));
  $("#sc-file").onchange = e => { if (e.target.files[0]) scLoad(e.target.files[0]); };
  $("#sc-read").onclick = () => scRead();
  $("#sc-measure").onclick = () => scMeasure();
  $("#sc-avatar").onclick = () => scAvatar();
  $("#sc-cmpgo").onclick = () => scCompare();
  $("#sc-proto").onclick = () => scProtocol().catch(e => toast(e.message, true));
  try { if (localStorage.getItem(document.title + ":tab") === "science") { scInit(); scAvatars(); } } catch (e) { /* ignore */ }
}
scSetup();
