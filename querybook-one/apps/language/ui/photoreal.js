"use strict";
// Photo Real Lab: author personas (with consent), the perfect reference sample, narration videos made by Gemini, HeyGen
// or D-ID (1.52: no face is animated in this browser), measurement against the author's own mouth model, the gate, the graph.
const PR = { meta: null, sel: null, persona: null, photo: null, sample: null, narr: null, rec: false, refRec: false };
const PR_VIS = ["PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"];

async function landmarksOf(canvas) {
  const lm = await tracker();
  const res = lm.detectForVideo(canvas, performance.now());
  const L = res.faceLandmarks && res.faceLandmarks[0];
  return L ? L.map(p => [Math.round(p.x * 1e5) / 1e5, Math.round(p.y * 1e5) / 1e5]) : null;
}

function prCanvasFrom(img, max) {
  const k = Math.min(1, (max || 1280) / Math.max(img.width || img.videoWidth, img.height || img.videoHeight));
  const c = document.createElement("canvas");
  c.width = Math.round((img.width || img.videoWidth) * k); c.height = Math.round((img.height || img.videoHeight) * k);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return c;
}

async function prSetPhoto(canvas) {
  const lm = await landmarksOf(canvas);
  PR.photo = { dataUrl: canvas.toDataURL("image/jpeg", 0.92), landmarks: lm };
  $("#pr-photo-prev").innerHTML = '<img src="' + PR.photo.dataUrl + '" style="max-width:180px;border-radius:8px;margin-top:6px"> ' +
    (lm ? '<span class="good-t">✔ face found (' + lm.length + " landmarks)</span>" : '<span class="bad-t">✖ no face found — use a clear, front-facing photo</span>');
}

function prConsentText() {
  const t = (PR.meta && PR.meta.consent_text) || "";
  $("#pr-consent-text").textContent = t.replace("{signer}", $("#pr-signer").value || "[your full name]").replace("{name}", $("#pr-name").value || "[the author]");
}

async function prLoad() {
  const r = await api("/api/persona"); PR.meta = r;
  $("#pr-list").innerHTML = r.personas.length ? r.personas.map(p => '<div class="pr-card' + (p.id === PR.sel ? " sel" : "") + '" data-pid="' + p.id + '"><img src="/api/persona/photo?id=' + p.id + '" alt=""><b>' + esc(p.name) +
    '</b><div class="small muted">' + esc((r.voice_methods[(p.voice || {}).method] || "").split(" (")[0]) + " · " + esc((r.face_methods[(p.face || {}).method] || "").split(",")[0]) + "</div>" +
    '<div class="small">' + (p.reference ? (p.reference.proven ? '<span class="good-t">✔ proven ' + p.reference.proven.score + "/100</span>" : "reference recorded") : "no reference yet") + "</div></div>").join("")
    : '<p class="muted small">No personas yet.</p>';
  $$("[data-pid]").forEach(el => el.onclick = () => prSelect(Number(el.dataset.pid)));
  $("#pr-voice").innerHTML = Object.entries(r.voice_methods).map(([k, v]) => '<option value="' + k + '">' + esc(v) + "</option>").join("");
  const faces = Object.entries(r.face_methods).map(([k, v]) => '<option value="' + k + '">' + esc(v) + "</option>").join("");
  $("#pr-face").innerHTML = faces; $("#pr-nface").innerHTML = faces;
  $("#pr-passage").textContent = r.passage;
  prConsentText();
  prAskOptions(r.personas);
  if (PR.sel) prSelect(PR.sel, true);
}

function prAskOptions(list) {
  const s = $("#ak-as"); if (!s) return;
  s.innerHTML = '<option value="">the talking face</option>' + list.map(p => '<option value="' + p.id + '">' + esc(p.name) + " (AI narrator)</option>").join("");
}

async function prSelect(id, quiet) {
  PR.sel = id;
  const p = await api("/api/persona/get?id=" + id); PR.persona = p;
  $$("[data-pid]").forEach(el => el.classList.toggle("sel", Number(el.dataset.pid) === id));
  $("#pr-detail").hidden = false;
  $("#pr-title").textContent = p.name + " — AI narrator";
  $("#pr-voice").value = (p.voice || {}).method || "offline";
  const fm0 = PR.meta.face_methods[(p.face || {}).method] ? p.face.method : "gemini";
  $("#pr-face").value = fm0; $("#pr-nface").value = fm0;
  $("#pr-voice-now").innerHTML = "Now: <b>" + esc(PR.meta.voice_methods[(p.voice || {}).method] || "") + "</b>" + ((p.voice || {}).matched === false ? " (closest match kept)" : "");
  $("#pr-face-now").innerHTML = "Now: <b>" + esc(PR.meta.face_methods[(p.face || {}).method] || "") + "</b>" +
    (p.photo_check && p.photo_check.length ? '<br><span class="bad-t">Photo: ' + esc(p.photo_check.join("; ")) + ".</span>" : "");
  prFaceOpts();
  prShowReference(p.reference);
  if (!quiet) { $("#pr-score").innerHTML = ""; $("#pr-stage").innerHTML = ""; $("#pr-player").innerHTML = ""; $("#pr-measure").disabled = true; }
  prFindings();
}

function prFaceOpts() {
  const m = $("#pr-face").value, f = (PR.persona && PR.persona.face) || {}, keys = PR.meta.keys;
  let h = "";
  if (m === "heygen" || m === "did") {
    h = '<div class="row"><input id="pr-key" type="password" placeholder="' + (m === "heygen" ? "HeyGen" : "D-ID") + ' API key' + (keys[m] ? " (saved — type to replace)" : "") + '"><button class="btn small" id="pr-key-save">Save key</button></div>' +
      '<span class="muted">The photo and the narration audio are sent to ' + (m === "heygen" ? "HeyGen" : "D-ID") + " to make each video.</span>";
  } else if (m === "gemini") h = '<span class="muted">Gemini performs the line from the author\'s photo (face, lips and its own voice), with the instructions that made the October 29 answer videos. ' +
      (keys.google_gemini ? "" : "No Gemini key yet — add it on Speech → Voice providers. ") + "When Gemini cannot, HeyGen makes it with the persona's voice.</span>";
  $("#pr-face-opts").innerHTML = h;
  if ($("#pr-key-save")) $("#pr-key-save").onclick = async () => { await api("/api/speech/keys", { provider: m, values: { api_key: $("#pr-key").value } }); $("#pr-key").value = ""; toast("Key saved."); PR.meta = await api("/api/persona"); };
}

function prShowReference(ref) {
  if (!ref) { $("#pr-ref-out").innerHTML = '<p class="small muted">No perfect sample yet — the lab needs it to measure the narrator videos.</p>'; return; }
  const m = ref.signature.model || {}, g = m.gap || {}, mx = Math.max(0.05, ...Object.values(g));
  $("#pr-ref-out").innerHTML = (ref.warnings && ref.warnings.length ? '<div class="note bad"><b>This sample is not good enough for a perfect narrator:</b> ' + esc(ref.warnings.join("; ")) + "</div>" :
    '<div class="note good">✔ A good perfect sample: every narrator video can be measured against it.</div>') + '<div class="stats">' + stat((m.lead_ms ?? "—") + " ms", "lips lead the sound") + stat((m.tau_ms ?? "—") + " ms", "mouth response time") +
    stat(Math.round(100 * (m.explained || 0)) + "%", "lip motion explained by the model") + stat(ref.signature.frames, "frames") + stat(ref.signature.seconds + " s", "length") +
    (ref.proven ? stat(ref.proven.score + "/100", "photo face proven") : "") + "</div>" +
    '<p class="small"><b>The author\'s lip opening for each sound</b> (share of mouth width):</p><div class="pr-bars">' +
    PR_VIS.map(v => '<div title="' + v + ": " + (g[v] ?? "not shown") + '" style="height:' + (g[v] !== undefined ? Math.max(2, 100 * g[v] / mx) : 2) + "%;" + (g[v] === undefined ? "background:#cbd5e1" : "") + '"><span>' + v + "</span></div>").join("") + "</div>" +
    (m.missing && m.missing.length ? '<p class="small muted" style="margin-top:22px">Not shown in the sample (estimated from look-alike sounds): ' + esc(m.missing.join(", ")) + "</p>" : '<p style="margin-top:22px"></p>') +
    (ref.library && ref.library.rest ? '<p class="small"><b>Real-mouth library</b> — the author\'s own frames the narrator is made from:</p><div class="row">' +
      Object.keys(ref.library).map(v => '<figure style="margin:0;text-align:center"><img src="/api/persona/lib?id=' + PR.sel + "&v=" + encodeURIComponent(v) + '" style="width:72px;height:72px;object-fit:cover;object-position:50% 70%;border-radius:6px"><figcaption class="small">' + esc(v) + "</figcaption></figure>").join("") + "</div>"
      : '<p class="small muted">No real-mouth library yet: it is taken from the video of the perfect sample (record it here, or open the video file).</p>');
}

// ---------------------------------------------------------------- the perfect sample
async function prRefRecord() {
  const btn = $("#pr-ref-rec");
  if (!PR.refRec) {
    try { await recStart(null, $("#pr-ref-out")); } catch (e) { toast("The microphone could not be opened: " + e.message, true); return; }
    if (!(await camSideStart($("#pr-ref-cam"), REC.t0))) { recStop(); return; }
    PR.refRec = true; btn.textContent = "⏹ Stop — finished reading"; btn.classList.add("busy");
  } else {
    PR.refRec = false; btn.textContent = "🎙📷 Record the perfect sample"; btn.classList.remove("busy");
    const blob = recStop();
    const cam = camSideStop($("#pr-ref-cam"));
    if (!cam) { $("#pr-ref-out").textContent = "No face frames were recorded."; return; }
    await prRefSend(await blobB64(blob), cam.frames, cam.info);
  }
}
async function prRefFile(file) {
  const v = document.createElement("video"); v.src = URL.createObjectURL(file); v.playsInline = true;
  $("#pr-ref-out").innerHTML = '<p class="small">Tracking the face in the video…</p>'; $("#pr-ref-out").appendChild(v); v.style.maxWidth = "320px";
  const t = await trackVideo(v, s => { $("#pr-ref-out").firstChild.textContent = "Tracking the face in the video… " + s.toFixed(2) + " s"; });
  const audio = await decodeTrack(file);
  await prRefSend(await wavB64(audio, 16000), t.frames, { width: v.videoWidth, height: v.videoHeight, fps: Math.round(10 * Math.max(t.fps, t.tracked)) / 10, source: "file" });
}

async function prRefSend(wav, frames, info) {
  const r = await api("/api/photoreal/reference", { persona: PR.sel, audio_b64: wav, frames, info, text: PR.meta.passage, lang: (PR.persona.voice || {}).lang || "en" });
  toast("Perfect sample analysed: the author's mouth model is ready.");
  await prSelect(PR.sel, true);
  prShowReference(PR.persona.reference);
  return r;
}

// ---------------------------------------------------------------- narrate and measure
async function prNarrate() {
  const text = $("#pr-text").value.trim(); if (!text) { toast("Type what the narrator should say.", true); return; }
  const fm = $("#pr-nface").value;
  const r = await api("/api/persona/narrate", { id: PR.sel, text, face_method: fm });
  PR.narr = Object.assign(r, { text });
  $("#pr-score").innerHTML = ""; $("#pr-measure").disabled = true;
  $("#pr-player").innerHTML = '<p class="small muted">' + esc(r.label) + (r.voice_fallback ? " · the chosen voice failed (" + esc(r.voice_fallback) + "), the offline voice spoke" : "") + "</p>";
  $("#pr-stage").innerHTML = '<div class="meter live"><i style="width:100%"></i></div><p class="small" id="pr-wait">Making the video…</p>';
  {
    for (;;) {
      await new Promise(res => setTimeout(res, 2000));
      const n = await api("/api/persona/narration?id=" + r.id);
      if ($("#pr-wait")) $("#pr-wait").textContent = n.detail || n.status;
      if (n.status === "done") {
        $("#pr-stage").innerHTML = '<video controls playsinline style="width:100%;border-radius:10px" src="/api/persona/video?narration=' + r.id + '"></video><div class="small muted">' + esc(r.label) + "</div>";
        $("#pr-measure").disabled = !PR.persona.reference; break;
      }
      if (n.status === "failed") { $("#pr-stage").innerHTML = '<div class="note bad">The video could not be made: ' + esc(n.detail) + "</div>"; break; }
    }
  }
}

function prScoreHtml(sc, title) {
  return '<h3>' + esc(title || "Measured against the author") + ": " + sc.overall + '/100</h3><div class="note ' + (sc.passed ? "good" : "bad") + '"><b>' + esc(sc.verdict) + "</b></div>" +
    '<table class="tbl small"><tr><th>What is compared</th><th>Author</th><th>This</th><th>Score</th></tr>' +
    Object.values(sc.dimensions).map(d => '<tr class="' + (d.score >= 85 ? "ok" : d.score >= 70 ? "warn" : "bad") + '"><td>' + esc(d.label) + (d.critical ? " *" : "") + "</td><td>" + esc(d.reference) + "</td><td>" + esc(d.candidate) +
      "</td><td><b>" + d.score + "</b></td></tr>").join("") + '</table><p class="small muted">* must score ' + PR.meta.gate.critical + "+; overall must be " + PR.meta.gate.overall + "+ to pass.</p>";
}

async function prMeasure() {
  const r = PR.narr; if (!r) return;
  const btn = $("#pr-measure"); buttonStart(btn); let ok = false;
  try {
    const v = $("#pr-stage video");
    const t = await trackVideo(v, s => { $("#pr-score").textContent = "Tracking the video… " + s.toFixed(2) + " s"; });
    const info = { width: v.videoWidth, height: v.videoHeight, fps: Math.round(10 * Math.max(t.fps, t.tracked)) / 10, source: r.face_method };
    // the video's own soundtrack: Gemini speaks with its own voice, so the narration audio made here is not what is heard
    const sound = await decodeTrack(await (await fetch(v.src)).blob());
    const n = await api("/api/persona/narration?id=" + r.id);
    const m = await api("/api/photoreal/measure", { persona: PR.sel, audio_b64: await wavB64(sound, 16000), frames: t.frames, info, text: r.text,
      method: n.face_method || r.face_method, narration: r.id, lang: (PR.persona.voice || {}).lang || "en" });
    $("#pr-score").innerHTML = prScoreHtml(m.score);
    ok = true; prFindings();
  } catch (e) { $("#pr-score").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; }
  finally { buttonEnd(btn, ok); }
}

async function prFindings() {
  if (!PR.sel) return;
  const f = await api("/api/photoreal/findings?persona=" + PR.sel);
  $("#pr-findings").innerHTML = f.methods.length ? '<table class="tbl small"><tr><th>Method</th><th>Measured</th><th>Passed</th><th>Average</th><th>Best</th><th>Holds it back most</th></tr>' +
    f.methods.map(m => "<tr><td>" + esc(m.method) + "</td><td>" + m.measured + "</td><td>" + Math.round(100 * m.pass_rate) + "%</td><td>" + m.mean_score + "</td><td>" + m.best_score + "</td><td>" +
      esc(m.most_common_failures.map(x => x[0] + " (" + x[1] + ")").join("; ") || "—") + "</td></tr>").join("") + "</table>" +
    '<p class="small">' + f.facts + " facts in the photoreal graph" + (f.best ? "; best so far: <b>" + esc(f.best) + "</b>" : "") + ".</p>"
    : '<p class="small muted">Nothing measured yet. ' + f.facts + " facts in the graph.</p>";
  prGraph();
}
async function prGraph() {
  const q = $("#pr-gq").value.trim();
  const g = await api("/api/photoreal/graph?subject=" + encodeURIComponent(q));
  let facts = g.facts;
  if (q && facts.length === 0) facts = (await api("/api/photoreal/graph?predicate=" + encodeURIComponent(q))).facts;
  $("#pr-graph").innerHTML = '<table class="tbl small"><tr><th>Subject</th><th>Predicate</th><th>Object</th><th>Trust</th><th>From</th></tr>' +
    facts.slice(-60).reverse().map(x => "<tr><td>" + esc(x.subject) + "</td><td>" + esc(x.predicate) + "</td><td>" + esc(String(x.object).slice(0, 120)) + "</td><td>" + x.trust + "</td><td>" + esc(x.source) + "</td></tr>").join("") + "</table>";
}

// ---------------------------------------------------------------- setup
async function prInit() {
  if (PR.ready) return; PR.ready = true;
  tracker().catch(() => {});
  $("#pr-lang").innerHTML = Object.entries(typeof NAMES !== "undefined" ? NAMES : { en: "English" }).map(([k, v]) => '<option value="' + k + '">' + esc(v) + "</option>").join("");
  ["#pr-name", "#pr-signer"].forEach(id => $(id).oninput = prConsentText);
  $("#pr-photo").onchange = async e => { const f = e.target.files[0]; if (!f) return; const img = new Image(); img.src = URL.createObjectURL(f); await img.decode(); await prSetPhoto(prCanvasFrom(img)); };
  $("#pr-snap").onclick = async () => {
    try {
      const st = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: "user" } });
      const v = document.createElement("video"); v.srcObject = st; v.muted = true; await v.play();
      $("#pr-photo-prev").textContent = "Look at the camera, mouth closed… 3"; for (const n of [2, 1]) { await new Promise(r => setTimeout(r, 900)); $("#pr-photo-prev").textContent = "Look at the camera, mouth closed… " + n; }
      await new Promise(r => setTimeout(r, 900));
      const c = prCanvasFrom(v); st.getTracks().forEach(t => t.stop()); await prSetPhoto(c);
    } catch (e) { toast("The camera could not be opened: " + e.message, true); }
  };
  $("#pr-rec").onclick = async () => {
    if (!PR.rec) { try { await recStart(null, $("#pr-wav-state")); } catch (e) { toast("The microphone could not be opened: " + e.message, true); return; } PR.rec = true; $("#pr-rec").textContent = "⏹ Stop recording"; }
    else { PR.rec = false; $("#pr-rec").textContent = "🎙 Record a voice sample"; const b = recStop(); PR.sample = await blobB64(b); $("#pr-wav-state").textContent = "✔ voice sample recorded (" + ((performance.now() - REC.t0) / 1000).toFixed(2) + " s)"; }
  };
  $("#pr-wav").onchange = async e => { const f = e.target.files[0]; if (!f) return; PR.sample = await blobB64(f); $("#pr-wav-state").textContent = "✔ " + f.name; };
  $("#pr-create").onclick = async () => {
    if (!PR.photo || !PR.photo.landmarks) { toast("Add a clear, front-facing photo of the author first.", true); return; }
    if (!PR.sample) { toast("Add a voice sample first.", true); return; }
    const p = await api("/api/persona/create", { name: $("#pr-name").value, signer: $("#pr-signer").value, consent: $("#pr-consent").checked, on_behalf: $("#pr-behalf").checked,
      photo_b64: PR.photo.dataUrl, sample_b64: PR.sample, lang: $("#pr-lang").value, landmarks: PR.photo.landmarks });
    PR.sel = p.id; $("#pr-new").open = false; PR.photo = null; PR.sample = null; $("#pr-photo-prev").innerHTML = ""; await prLoad();
  };
  $("#pr-face").onchange = prFaceOpts;
  $("#pr-voice-go").onclick = async () => { await api("/api/persona/voice", { id: PR.sel, method: $("#pr-voice").value, lang: (PR.persona.voice || {}).lang || "en" }); await prLoad(); };
  $("#pr-face-go").onclick = async () => {
    await api("/api/persona/face", { id: PR.sel, method: $("#pr-face").value }); await prLoad();
  };
  $("#pr-delete").onclick = async () => {
    if (!confirm("Delete this persona, its photo, voice sample and narrations?")) return;
    const r = await api("/api/persona/delete", { id: PR.sel }); if (r.note) toast(r.note);
    PR.sel = null; $("#pr-detail").hidden = true; await prLoad();
  };
  $("#pr-ref-rec").onclick = prRefRecord;
  $("#pr-ref-file").onchange = e => { const f = e.target.files[0]; if (f) prRefFile(f).catch(err => toast(err.message, true)); };
  $("#pr-narrate").onclick = prNarrate;
  $("#pr-measure").onclick = prMeasure;
  $("#pr-gq").oninput = () => { clearTimeout(PR.gt); PR.gt = setTimeout(prGraph, 300); };
  await prLoad();
}

document.addEventListener("click", e => { const b = e.target.closest && e.target.closest('nav.tabs button[data-tab="photoreal"]'); if (b) prInit(); });
document.addEventListener("DOMContentLoaded", () => {
  if (document.querySelector("#photoreal.active")) prInit();
  fetch("/api/persona").then(r => r.json()).then(r => prAskOptions(r.personas || [])).catch(() => {});
});
