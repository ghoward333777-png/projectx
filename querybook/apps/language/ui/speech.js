"use strict";
// Speech Lab page: voice profile + engine controls, generation, target matching, analysis, spoken queries, providers, log.
const SP = { meta: null, profile: {}, engine: "espeak", adv: {}, wav: null, wavName: "", planTimer: null, loaded: false };
const pct = v => Math.round(100 * v) + "%";
const FMT = {
  intensity: v => pct(v), rate: v => "×" + Number(v).toFixed(2), pitch_st: v => (v > 0 ? "+" : "") + Number(v).toFixed(1) + " semitones",
  volume_db: v => (v > 0 ? "+" : "") + Number(v).toFixed(1) + " dB", pause_scale: v => "×" + Number(v).toFixed(2),
  tremble: v => pct(v), hoarse: v => pct(v), breath: v => pct(v),
  age: v => v < 0.15 ? "young adult" : v < 0.45 ? "adult (" + pct(v) + ")" : v < 0.7 ? "middle-aged (" + pct(v) + ")" : "elderly (" + pct(v) + ")",
};
const PRESETS = [
  ["🤫 Whispered secret", { whisper: true, volume_db: -8, rate: 0.9, emotion: "tender", intensity: 0.4, breath: 0.3 }, { elevenlabs: { audio_tags: "[whispers]" }, azure: { style: "whispering" } }],
  ["😢 Crying / heartbroken", { emotion: "sad", intensity: 1, tremble: 0.55, breath: 0.45, rate: 0.82, pitch_st: 2, pause_scale: 1.8 }, { elevenlabs: { audio_tags: "[crying]" } }],
  ["👴 Elderly storyteller", { age: 0.9, rate: 0.85, emotion: "calm", intensity: 0.5, tremble: 0.25, hoarse: 0.2, pause_scale: 1.4, gender: "male" }, { azure: { role: "SeniorMale" } }],
  ["😠 Angry shout", { emotion: "angry", intensity: 1, volume_db: 6, rate: 1.15, hoarse: 0.35, pitch_st: 3 }, { elevenlabs: { audio_tags: "[shouting]" }, azure: { style: "shouting" } }],
  ["🧘 Calm narrator", { emotion: "calm", intensity: 0.6, tone: "warm", rate: 0.92, pause_scale: 1.3, articulation: "precise" }, { azure: { style: "narration-relaxed" } }],
  ["🎉 Excited announcer", { emotion: "excited", intensity: 0.9, tone: "bright", rate: 1.15, volume_db: 3, pitch_st: 2 }, { azure: { style: "excited" } }],
  ["😰 Nervous", { emotion: "fearful", intensity: 0.7, tremble: 0.4, rate: 1.1, pause_scale: 0.8, breath: 0.2 }, { elevenlabs: { audio_tags: "[nervous]" } }],
  ["🤒 Hoarse with a cold", { hoarse: 0.7, breath: 0.3, rate: 0.95, volume_db: -2 }, {}],
  ["↺ Reset", {}, {}],
];

function profileUI() {
  const P = SP.profile;
  $$("#pf-emotion button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === P.emotion));
  $$("#pf-articulation button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === P.articulation));
  ["intensity", "rate", "pitch_st", "volume_db", "pause_scale", "tremble", "hoarse", "breath", "age"].forEach(k => {
    $("#pf-" + k).value = P[k]; $("#pf-" + k + "-v").textContent = FMT[k](P[k]);
  });
  $("#pf-tone").value = P.tone; $("#pf-lang").value = P.lang; $("#pf-accent").value = P.accent || ""; $("#pf-gender").value = P.gender;
  $("#pf-whisper").checked = !!P.whisper;
  const d = (SP.meta.dialects || []).find(x => x.id === P.accent);
  $("#pf-accent-note").textContent = d ? d.summary : "";
}

function schedulePlan() { clearTimeout(SP.planTimer); SP.planTimer = setTimeout(showPlan, 250); }

function advValues() {
  const out = {};
  $$("#sp-adv [data-adv]").forEach(el => { if (el.value !== "") out[el.dataset.adv] = el.value; });
  return out;
}

function genBody(extra) {
  return Object.assign({ text: $("#sp-text").value, profile: SP.profile, engine: SP.engine, voice: $("#sp-voice").value, model: $("#sp-model").value,
    advanced: advValues() }, extra || {});
}

async function showPlan() {
  if (!SP.loaded) return;
  let pl;
  try { pl = await api("/api/speech/plan", genBody()); } catch (e) { return; }
  const eng = SP.meta.engines.find(e => e.id === SP.engine);
  $("#sp-cov-engine").textContent = eng ? eng.name : SP.engine;
  $("#sp-cov").innerHTML = pl.coverage.map(r => '<tr' + (r.in_use ? ' style="font-weight:600"' : "") + "><td>" + esc(r.label) + "</td><td>" + esc(typeof r.value === "number" ? (FMT[r.control] ? FMT[r.control](r.value) : r.value) : String(r.value === "" ? "—" : r.value)) +
    "</td><td>" + (r.how === "native" ? '<span class="badge good">native</span>' : r.how.startsWith("added") ? '<span class="badge warn">added by post-processing</span>' :
      r.how.startsWith("approx") ? '<span class="badge warn">approximated</span> <span class="small muted">' + esc(r.how.slice(14)) + "</span>" : r.how === "not needed" ? '<span class="muted">not needed</span>' :
      '<span class="badge bad">not available</span>') + "</td></tr>").join("");
  $("#sp-req").textContent = JSON.stringify(pl.request, null, 2);
  const pp = Object.entries(pl.post_processing).filter(([k, v]) => (k === "pause_scale" ? v !== 1 : v !== 0));
  $("#sp-direction").innerHTML = (pl.direction ? "<p><b>Performance direction written from the profile:</b> “" + esc(pl.direction) + "”</p>" : "") +
    (pp.length ? "<p><b>Post-processing after the engine:</b> " + pp.map(([k, v]) => esc(k) + " " + esc(FMT[k] ? FMT[k](v) : v)).join(", ") + "</p>" : "<p class=\"muted\">No post-processing needed.</p>");
}

async function loadVoices() {
  const r = await api("/api/speech/voices?engine=" + SP.engine + "&lang=" + SP.profile.lang);
  $("#sp-voice").innerHTML = (r.voices || []).map(v => '<option value="' + esc(v.id) + '">' + esc(v.name) + "</option>").join("") || '<option value="">default</option>';
  $("#sp-model").innerHTML = (r.models && r.models.length ? r.models : ["(default)"]).map(m => '<option value="' + (m.startsWith("(") ? "" : esc(m)) + '">' + esc(m) + "</option>").join("");
}

function renderAdv() {
  const eng = SP.meta.engines.find(e => e.id === SP.engine);
  const prev = SP.adv[SP.engine] || {};
  $("#sp-adv-title").textContent = "Advanced " + eng.name + " parameters (" + eng.params.length + ")";
  $("#sp-adv").innerHTML = eng.params.length ? eng.params.map(p => {
    const v = prev[p.key] !== undefined ? prev[p.key] : "";
    let ctl;
    if (p.type === "select") ctl = '<select data-adv="' + p.key + '"><option value="">(from profile)</option>' + p.options.map(o => "<option" + (String(v) === String(o) ? " selected" : "") + ">" + esc(o) + "</option>").join("") + "</select>";
    else if (p.type === "textarea") ctl = '<textarea data-adv="' + p.key + '" placeholder="(from profile)">' + esc(v) + "</textarea>";
    else ctl = '<input data-adv="' + p.key + '" type="' + (p.type === "number" ? "number" : "text") + '"' + (p.min !== null ? ' min="' + p.min + '"' : "") + (p.max !== null ? ' max="' + p.max + '"' : "") +
      (p.step ? ' step="' + p.step + '"' : "") + ' value="' + esc(v) + '" placeholder="(from profile)">';
    return "<div><label class=\"f\">" + esc(p.label) + "</label>" + ctl + (p.help ? '<div class="small muted">' + esc(p.help) + "</div>" : "") + "</div>";
  }).join("") : '<p class="small muted">This engine has no extra parameters beyond the voice profile.</p>';
  $$("#sp-adv [data-adv]").forEach(el => el.oninput = () => { (SP.adv[SP.engine] = SP.adv[SP.engine] || {})[el.dataset.adv] = el.value; schedulePlan(); });
}

async function selectEngine(id) {
  SP.engine = id;
  const eng = SP.meta.engines.find(e => e.id === id);
  $("#sp-engine-note").innerHTML = esc(eng.notes) + (eng.available ? "" : ' <span class="badge bad">' + esc(eng.why_not) + "</span> — the offline voice is used instead (when “use the offline voice” is ticked).");
  renderAdv();
  await loadVoices();
  schedulePlan();
}

function stagesTable(stages, total) {
  if (typeof stages === "string") { try { stages = JSON.parse(stages); } catch (e) { stages = []; } }
  const max = Math.max(0.01, ...stages.map(s => s.seconds || 0));
  return '<table class="t small"><tr><th>Stage</th><th>Started at</th><th>Seconds</th><th style="width:40%"></th></tr>' + stages.map(s =>
    "<tr><td>" + esc(s.stage) + "</td><td>" + (s.at_s !== undefined ? Number(s.at_s).toFixed(2) + " s" : "") + "</td><td><b>" + Number(s.seconds || 0).toFixed(2) + "</b></td><td>" +
    '<div class="meter"><i style="width:' + (100 * (s.seconds || 0) / max).toFixed(1) + '%"></i></div></td></tr>').join("") +
    (total !== undefined ? "<tr><td><b>Total</b></td><td></td><td><b>" + Number(total).toFixed(2) + "</b></td><td></td></tr>" : "") + "</table>";
}

// Talking face card: lip-sync track from the server, drawn in 2D (SVG) or 3D (three.js, with Enter VR), synced to the audio.
async function faceCard(host, audioName, text, lang, emotion) {
  const box = document.createElement("div"); box.className = "card face-card";
  box.innerHTML = '<h3>Talking face <span class="small muted">mouth shapes timed to this audio</span></h3>' +
    '<div class="row"><button class="btn small" data-fm="2d">2D face</button><button class="btn small" data-fm="3d">3D / VR face</button>' +
    '<label class="small"><input type="checkbox" data-exact> exact timing (Google Speech-to-Text)</label>' +
    '<span class="small">Export: <a data-fx="json">JSON</a> · <a data-fx="csv">CSV</a> · <a data-fx="tsv">Rhubarb TSV</a></span></div>' +
    '<div class="face-stage" style="max-width:360px"></div><p class="small muted" data-finfo>Working out the mouth shapes…</p>';
  host.appendChild(box);
  const stage = box.querySelector(".face-stage"), info = box.querySelector("[data-finfo]"), audio = host.querySelector("audio");
  box.querySelectorAll("[data-fx]").forEach(a => { a.href = "/api/speech/lipsync.export?audio=" + encodeURIComponent(audioName) + "&text=" + encodeURIComponent(text) + "&lang=" + encodeURIComponent(lang) + "&format=" + a.dataset.fx; a.setAttribute("download", ""); });
  const face = new TalkingFace(stage);
  face.setEmotion(emotion || "neutral");
  const load = async exact => {
    const t0 = performance.now();
    const tr = await api("/api/speech/lipsync", { audio: audioName, text, lang, exact });
    face.attach(audio, tr);
    info.textContent = tr.words.length + " words, " + tr.visemes.length + " mouth shapes, " + tr.duration.toFixed(2) + " s of audio — timing: " + tr.method + " (" + ((performance.now() - t0) / 1000).toFixed(2) + " s)";
    return tr;
  };
  await face.setMode("2d");
  box.querySelectorAll("[data-fm]").forEach(b => b.onclick = () => face.setMode(b.dataset.fm).catch(e => { info.textContent = "3D could not start here: " + e.message; face.setMode("2d"); }));
  box.querySelector("[data-exact]").onchange = e => load(e.target.checked).catch(err => { info.textContent = "Exact timing failed: " + err.message; });
  try { await load(false); } catch (e) { info.textContent = "Lip-sync failed: " + e.message; }
  return face;
}

// The author's AI narrator speaks a text (Photo Real Lab persona): photo-driven face with the proven settings.
async function narratorCard(host, pid, text, emotion) {
  const box = document.createElement("div"); box.className = "card face-card";
  box.innerHTML = '<h3>Answered by the author\'s AI narrator</h3><div class="face-stage" style="max-width:420px"></div><div class="nar-player"></div>';
  host.appendChild(box);
  try {
    const p = await api("/api/persona/get?id=" + pid);
    const a0 = host.querySelector("audio"); if (a0) a0.pause();
    const r = await api("/api/persona/narrate", { id: pid, text, face_method: "photo", emotion });
    const a = document.createElement("audio"); a.controls = true; a.src = "/api/speech/audio?name=" + encodeURIComponent(r.audio);
    box.querySelector(".nar-player").appendChild(a);
    const f = new TalkingFace(box.querySelector(".face-stage"));
    f.setEmotion(emotion || "neutral");
    await f.setMode("photo", { persona: prFaceSource(p, pid), params: (p.reference || {}).params });
    f.attach(a, r.track); a.play().catch(() => {});
  } catch (e) { box.insertAdjacentHTML("beforeend", '<div class="note bad">The narrator could not answer: ' + esc(e.message) + "</div>"); }
}

function audioEl(name) { return '<audio controls preload="auto" src="/api/speech/audio?name=' + encodeURIComponent(name) + '"></audio>'; }

async function generate() {
  const r = await api("/api/speech/generate", genBody({ fallback: $("#sp-fallback").checked }));
  const s = r.summary, m = r.measure;
  $("#sp-out").innerHTML = '<div class="row">' + audioEl(r.audio) + '<a class="small" href="/api/speech/audio?name=' + encodeURIComponent(r.audio) + '" download>download WAV</a></div>' +
    (s.warning ? '<div class="note bad">⚠ ' + esc(s.warning) + "</div>" : "") +
    (s.fallback_reason ? '<div class="note bad">The chosen engine could not be used (' + esc(s.fallback_reason) + "); the offline voice spoke instead.</div>" : "") +
    '<div class="stats" style="margin-top:10px">' + stat(s.engine_used, "engine used") + (m ? stat(m.pitch.mean_hz ? m.pitch.mean_hz + " Hz" : "—", "measured pitch") +
      stat(m.rate.articulation_rate_syl_s + "/s", "syllables per second") + stat(m.volume.mean_dbfs + " dBFS", "loudness") + stat(m.vocal_mode.label, "vocal mode heard") +
      stat(m.duration_s + " s", "length") : "") + "</div>" +
    (s.effects && s.effects.length ? '<p class="small"><b>Added after the engine:</b> ' + esc(s.effects.join("; ")) + "</p>" : "") +
    "<details><summary class=\"small\">Timing of every stage (to 0.01 s)</summary>" + stagesTable(r.stages.stages, r.stages.seconds) + "</details>";
  if (window.TalkingFace) faceCard($("#sp-out"), r.audio, $("#sp-text").value, SP.profile.lang, SP.profile.emotion);
}

// ---------------------------------------------------------------- match
function renderTargets() {
  const T = SP.meta.targets, defaults = { pitch_hz: 160, rate_syl_s: 4.0, volume_dbfs: -24, pause_ratio: 0.15, tremble: 40, breathiness: 0.3 };
  $("#mt-targets").innerHTML = Object.entries(T).map(([k, label]) => '<label><input type="checkbox" data-tk="' + k + '"' + (["pitch_hz", "rate_syl_s", "volume_dbfs"].includes(k) ? " checked" : "") +
    "> " + esc(label) + ' <input type="number" step="any" data-tv="' + k + '" value="' + defaults[k] + '"></label>').join("");
}

async function match() {
  const target = {};
  $$("#mt-targets [data-tk]").forEach(c => { if (c.checked) target[c.dataset.tk] = Number($('[data-tv="' + c.dataset.tk + '"]').value); });
  await api("/api/speech/match", genBody({ target, rounds: Number($("#mt-rounds").value) }));
  $("#mt-out").innerHTML = "";
  pollJob($("#mt-job"), async j => {
    const r = j.result;
    if (!r || !r.rounds) return;
    const keys = Object.keys(r.target);
    $("#mt-job").innerHTML = '<div class="note ' + (r.matched ? "good" : "") + '">' + (r.matched ? "✅ Matched in round " + r.best_round : "Closest result: round " + r.best_round + " (not every target within tolerance)") +
      " — " + r.rounds.length + " round(s), " + secs(j.elapsed) + "</div>";
    $("#mt-out").innerHTML = '<table class="t small"><tr><th>Round</th><th>Settings sent</th>' + keys.map(k => "<th>" + esc(SP.meta.targets[k]) + "<br>target " + r.target[k] + "</th>").join("") +
      "<th>OK</th><th>Seconds</th><th>Listen</th></tr>" + r.rounds.map(x => "<tr><td>" + x.round + "</td><td>pitch " + Number(x.profile.pitch_st).toFixed(1) + " st · speed ×" + Number(x.profile.rate).toFixed(2) +
        " · volume " + Number(x.profile.volume_db).toFixed(1) + " dB · pauses ×" + Number(x.profile.pause_scale).toFixed(2) + " · tremble " + pct(x.profile.tremble) + " · breath " + pct(x.profile.breath) + (x.post_correction && (x.post_correction.pitch_st || x.post_correction.tempo !== 1) ? "<br><span class=\"small muted\">corrected after the engine: pitch " + Number(x.post_correction.pitch_st).toFixed(1) + " st, speed ×" + Number(x.post_correction.tempo).toFixed(2) + "</span>" : "") + "</td>" +
        keys.map(k => "<td>" + (x.measured[k] === null ? "—" : Number(x.measured[k]).toFixed(2)) + ' <span class="small muted">(' + (x.error[k] > 0 ? "+" : "") + x.error[k] + ")</span></td>").join("") +
        "<td>" + (x.within_tolerance ? "✅" : "") + "</td><td>" + (x.seconds !== null ? Number(x.seconds).toFixed(2) : "") + "</td><td>" + audioEl(x.audio) + "</td></tr>").join("") + "</table>" +
      '<p class="small muted">Tolerance: ' + Object.entries(r.tolerance).filter(([k]) => keys.includes(k)).map(([k, v]) => esc(k) + " " + (["pitch_hz", "rate_syl_s"].includes(k) ? "±" + Math.round(100 * v) + "%" : "±" + v)).join(", ") +
      '. <button class="btn quiet" id="mt-use">Use the best settings in the voice profile</button></p>';
    $("#mt-use").onclick = () => { Object.assign(SP.profile, r.final_profile); profileUI(); schedulePlan(); toast("The voice profile now holds the matched settings."); };
  });
}

// ---------------------------------------------------------------- recording (WAV, 16 kHz mono)
const REC = { ctx: null, src: null, proc: null, chunks: [], stream: null, on: false, t0: 0, sr: 16000 };
async function recStart(levelEl, stateEl) {
  REC.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  REC.ctx = new (window.AudioContext || window.webkitAudioContext)();
  REC.src = REC.ctx.createMediaStreamSource(REC.stream);
  REC.proc = REC.ctx.createScriptProcessor(4096, 1, 1);
  REC.chunks = []; REC.on = true; REC.t0 = performance.now();
  REC.proc.onaudioprocess = e => {
    const d = e.inputBuffer.getChannelData(0); REC.chunks.push(new Float32Array(d));
    let m = 0; for (let i = 0; i < d.length; i++) m = Math.max(m, Math.abs(d[i]));
    if (levelEl) levelEl.style.width = Math.min(100, 100 * m * 1.4) + "%";
    if (stateEl) stateEl.textContent = "● recording " + ((performance.now() - REC.t0) / 1000).toFixed(2) + " s — press again to stop";
  };
  REC.src.connect(REC.proc); REC.proc.connect(REC.ctx.destination);
}
function recStop() {
  REC.on = false;
  REC.proc.disconnect(); REC.src.disconnect(); REC.stream.getTracks().forEach(t => t.stop());
  const inSr = REC.ctx.sampleRate; REC.ctx.close();
  let n = 0; REC.chunks.forEach(c => n += c.length);
  const all = new Float32Array(n); let o = 0; REC.chunks.forEach(c => { all.set(c, o); o += c.length; });
  const k = inSr / REC.sr, outN = Math.floor(n / k), pcm = new Int16Array(outN);
  for (let i = 0; i < outN; i++) { let s = 0, a = Math.floor(i * k), b = Math.min(n, Math.floor((i + 1) * k)); for (let j = a; j < b; j++) s += all[j]; s /= Math.max(1, b - a); pcm[i] = Math.max(-32767, Math.min(32767, s * 32767)); }
  const buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf);
  const w = (p, s) => { for (let i = 0; i < s.length; i++) v.setUint8(p + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, REC.sr, true); v.setUint32(28, REC.sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: "audio/wav" });
}
const blobB64 = b => new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(b); });
const Recog = window.SpeechRecognition || window.webkitSpeechRecognition;
function listenWords(lang, onText) {
  if (!Recog) return null;
  const r = new Recog(); r.lang = { en: "en-US", es: "es-ES", fr: "fr-FR", de: "de-DE", it: "it-IT", pt: "pt-PT", nl: "nl-NL", sv: "sv-SE" }[lang] || "en-US";
  r.interimResults = true; r.continuous = true; r.maxAlternatives = 5; r._alts = [];
  r.onresult = e => {
    let t = ""; for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript; onText(t);
    // other readings of the whole utterance: the best reading with one stretch swapped (the camera can choose between them)
    const tops = Array.from(e.results).map(x => x[0].transcript), alts = [{ text: t.trim(), confidence: e.results[0] && e.results[0][0].confidence || null }];
    Array.from(e.results).forEach((x, i) => { for (let j = 1; j < x.length; j++) { const v = tops.slice(); v[i] = x[j].transcript; alts.push({ text: v.join("").trim(), confidence: x[j].confidence || null }); } });
    r._alts = alts.slice(0, 8);
  };
  r.onerror = () => {}; try { r.start(); } catch (e) { return null; }
  return r;
}

let LS_RECOG = null;
async function lsRecord() {
  if (!REC.on) {
    try { await recStart($("#ls-level"), $("#ls-recstate")); } catch (e) { toast("The microphone could not be opened: " + e.message, true); return; }
    $("#ls-rec").textContent = "⏹ Stop";
    SP.video = null;
    if ($("#ls-kind").value === "speech") LS_RECOG = listenWords(SP.profile.lang, t => $("#ls-transcript").value = t);
    if ($("#ls-cam").checked) camSideStart($("#ls-cam-view"), REC.t0);
  } else {
    const blob = recStop();
    const cam = camSideStop($("#ls-cam-view"));
    SP.video = cam ? Object.assign(cam, { alternatives: (LS_RECOG && LS_RECOG._alts) || [] }) : null;
    if (LS_RECOG) { try { LS_RECOG.stop(); } catch (e) { /* ignore */ } LS_RECOG = null; }
    $("#ls-rec").textContent = "🎙 Record"; $("#ls-level").style.width = "0";
    $("#ls-recstate").textContent = "recorded " + ((performance.now() - REC.t0) / 1000).toFixed(2) + " s";
    SP.wav = await blobB64(blob); SP.wavName = "recording";
    $("#ls-audio").src = URL.createObjectURL(blob); $("#ls-audio").hidden = false; $("#ls-go").disabled = false;
  }
}

function contourSvg(c, segs) {
  const f0 = c.f0_hz, db = c.db, n = f0.length; if (!n) return "";
  const W = 900, H = 180, P = 30, x = i => P + (W - 2 * P) * i / Math.max(1, n - 1);
  const fv = f0.filter(v => v > 0), fmin = Math.min(...fv, 80) * 0.9, fmax = Math.max(...fv, 300) * 1.05;
  const dmin = Math.min(...db), dmax = Math.max(...db);
  const yf = v => H - P - (H - 2 * P) * (v - fmin) / (fmax - fmin), yd = v => H - P - (H - 2 * P) * (v - dmin) / Math.max(1, dmax - dmin);
  let fp = "", started = false;
  f0.forEach((v, i) => { if (v > 0) { fp += (started ? "L" : "M") + x(i).toFixed(1) + " " + yf(v).toFixed(1); started = true; } else started = false; });
  const dp = db.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + yd(v).toFixed(1)).join(" ");
  const dur = n * c.hop_s;
  return '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Pitch and loudness over time">' +
    '<path d="' + dp + '" fill="none" stroke="currentColor" opacity=".35" stroke-width="1.5"/>' +
    '<path d="' + fp + '" fill="none" stroke="var(--accent)" stroke-width="2.5"/>' +
    (c.nuclei || []).map(i => '<circle cx="' + x(i).toFixed(1) + '" cy="' + (H - P + 8) + '" r="3" fill="var(--good)"/>').join("") +
    '<text x="' + P + '" y="16" font-size="13" fill="var(--accent)">— pitch (' + Math.round(fmin) + "–" + Math.round(fmax) + ' Hz)</text>' +
    '<text x="' + (P + 230) + '" y="16" font-size="13" fill="currentColor" opacity=".6">— loudness</text>' +
    '<text x="' + (P + 340) + '" y="16" font-size="13" fill="var(--good)">● syllables</text>' +
    '<text x="' + (W - P) + '" y="' + (H - 4) + '" font-size="12" fill="currentColor" text-anchor="end">' + dur.toFixed(2) + " s</text></svg>";
}

async function lsAnalyse() {
  const rec = $("#ls-recog").value;
  const r = await api("/api/speech/ingest", { audio_b64: SP.wav, transcript: rec === "google" ? "" : $("#ls-transcript").value, expected: $("#ls-expected").value,
    label: SP.wavName, recognizer: rec, lang: SP.profile.lang, video: SP.video || null });
  if (r.transcript && !$("#ls-transcript").value) $("#ls-transcript").value = r.transcript;
  const m = r.measure, I = m.indicators, vm = m.vocal_mode, q = m.quality, p = m.pitch;
  const card = (title, o, extra) => '<div class="stat"><div class="k">' + esc(title) + '</div><div class="v">' + esc(o.label) + (o.level !== undefined && o.level !== null ? " · " + o.level + "/100" : "") + "</div>" +
    (o.reasons ? '<div class="small muted">' + o.reasons.map(esc).join("; ") + "</div>" : "") + (extra || "") + "</div>";
  $("#ls-out").innerHTML = (r.face ? faceEvidenceHtml(r.face) + learnedNote(r.learning) : "") +
    '<div class="card"><h2>Vocal mode' + (r.face ? " heard (sound only)" : "") + '</h2><div class="modebig">' + esc(vm.label) + ' <span class="small muted">(' + esc(vm.confidence || "") + ")</span></div>" +
      (vm.scores || []).map(s => '<div class="scorebar"><span>' + esc(s.mode) + '</span><div class="meter"><i style="width:' + s.score + '%"></i></div><b>' + s.score + '</b></div><div class="small muted" style="margin:-2px 0 6px 118px">' + s.reasons.map(esc).join("; ") + "</div>").join("") +
      '<p class="small muted">' + esc(vm.note || "") + "</p></div>" +
    '<div class="card"><h2>How it was said</h2><div class="ind">' + card("Emotion (estimate)", I.emotion) + card("Tone", I.tone) + card("Volume", I.volume, '<div class="small">' + m.volume.mean_dbfs + " dBFS mean, peak " + m.volume.peak_dbfs + ", range " + m.volume.range_db + " dB</div>") +
      card("Articulation", { label: I.articulation.label }, '<div class="small">' + I.articulation.rate_syl_s + " syllables/s; " + pct(I.articulation.pause_ratio) + " pauses</div>") +
      card("Tremble", I.tremble) + card("Hoarseness", I.hoarseness) + card("Voice age features", I.voice_age) + "</div>" +
      '<p class="small">Reliability of voice-condition numbers: <b>' + esc(q.reliability) + "</b></p></div>" +
    '<div class="card"><h2>Pitch and loudness over time</h2>' + contourSvg(r.contour, r.segments) +
      '<p class="small">Pauses: ' + (m.pauses.count ? m.pauses.list.map(x => x.seconds.toFixed(2) + " s at " + x.at_s.toFixed(2) + " s").join(", ") : "none") + "</p></div>" +
    '<div class="card"><h2>All measurements</h2><table class="t small">' + [
      ["Length", m.duration_s + " s (speech " + m.speech_s + " s)"], ["Pitch", p.mean_hz ? p.mean_hz + " Hz mean, " + p.low_hz + "–" + p.high_hz + " Hz, " + p.range_semitones + " semitones range" : "no voiced sound"],
      ["Intonation", p.intonation ? p.intonation + " (end slope " + p.end_slope_semitones + " st)" : "—"], ["Speaking rate", m.rate.speaking_rate_syl_s + " syllables/s overall, " + m.rate.articulation_rate_syl_s + " while speaking (" + m.rate.syllables + " syllables)"],
      ["Jitter", q.jitter_pct + " % (cycle to cycle; normal < 1.04 %)"], ["Shimmer", q.shimmer_pct + " % (normal < 3.81 %)"], ["Harmonics-to-noise", q.hnr_db + " dB (normal > 20 dB)"],
      ["Tremor (pitch)", (q.tremor_pitch.detected ? "detected" : "not detected") + (q.tremor_pitch.freq_hz ? " — " + q.tremor_pitch.freq_hz + " Hz, depth " + q.tremor_pitch.depth_pct + " %" : "")],
      ["Breathiness", q.breathiness], ["Voiced share", pct(m.vocal.voiced_ratio)], ["Voiced bursts", m.vocal.bursts + " (" + m.vocal.burst_rate_hz + " per second, " + m.vocal.burst_mean_s + " s each)"],
      ["Cycles measured", q.cycles_measured + " (longest voiced stretch " + q.longest_voiced_s + " s)"]].map(([a, b]) => "<tr><td>" + esc(a) + "</td><td>" + esc(b) + "</td></tr>").join("") + "</table></div>" +
    (r.semantics ? '<div class="card"><h2>The words — meaning and pronunciation</h2><p class="small">Language: <b>' + esc(r.semantics.language_name) + "</b> · syllables expected " + r.semantics.syllables_expected +
      (r.semantics.syllables_heard ? ", heard " + r.semantics.syllables_heard : "") + (r.semantics.match_to_expected !== undefined ? " · matches the expected text " + r.semantics.match_to_expected + "%" : "") +
      (r.semantics.accent_cues && r.semantics.accent_cues.length ? " · accent cues: " + r.semantics.accent_cues.map(a => esc(a.name) + " (" + a.score + ")").join(", ") : "") + "</p>" +
      '<p class="small">Words heard by: <b>' + esc(r.heard_by) + "</b>" + (r.stt ? " · Google confidence " + (r.stt.confidence !== null ? Math.round(100 * r.stt.confidence) + "%" : "—") + " · " + Number(r.stt.seconds).toFixed(2) + " s" : "") + "</p>" +
      '<table class="t small"><tr><th>Word</th><th>Heard at</th><th>Language</th><th>Pronunciation</th><th>Syllables / stress</th><th>Meaning</th><th>Learned</th></tr>' + r.semantics.words.map(w => "<tr><td><b>" + esc(w.word) + "</b>" +
        (w.stt_confidence !== undefined && w.stt_confidence !== null ? ' <span class="small muted">' + Math.round(100 * w.stt_confidence) + "%</span>" : "") + "</td><td class=\"mono\">" +
        (w.start_s !== undefined ? Number(w.start_s).toFixed(2) + "–" + Number(w.end_s).toFixed(2) + " s" : "") + "</td><td>" + esc(w.lang) + "</td><td class=\"mono\" title=\"" + esc(w.ipa_source || "") + "\">" + esc(w.ipa || "—") + "</td><td>" + (w.syllables || "") + " / " + (w.stress_syllable || "") +
        "</td><td>" + esc(w.meaning || "") + "</td><td>" + (w.known_to_builder ? "✔" : "") + "</td></tr>").join("") + "</table></div>" : "") +
    '<div class="card"><details><summary>Timing of every stage (to 0.01 s) — log entry #' + r.log_id + "</summary><div id=\"ls-stages\"></div></details></div>";
  const lg = await api("/api/speech/log?limit=1&process=ingest");
  if (lg.log[0]) $("#ls-stages").innerHTML = stagesTable(lg.log[0].stages, lg.log[0].seconds);
}

// ---------------------------------------------------------------- ask by voice
let AK = null;
async function akRecord() {
  if (!REC.on) {
    try { await recStart(null, $("#ak-state")); } catch (e) { toast("The microphone could not be opened: " + e.message, true); return; }
    $("#ak-rec").textContent = "⏹ Stop and answer";
    AK = listenWords(SP.profile.lang, t => $("#ak-text").value = t);
    if (!AK) $("#ak-state").textContent += " (this browser has no speech recognition — type the question too)";
    if ($("#ak-cam").checked) camSideStart($("#ak-cam-view"), REC.t0);
  } else {
    const blob = recStop(); if (AK) { try { AK.stop(); } catch (e) { /* ignore */ } }
    const cam = camSideStop($("#ak-cam-view"));
    $("#ak-rec").textContent = "🎙 Ask";
    await new Promise(r => setTimeout(r, 400));
    ask(await blobB64(blob), cam ? Object.assign(cam, { alternatives: (AK && AK._alts) || [] }) : null);
  }
}
async function ask(audio, video) {
  const r = await api("/api/speech/query", genBody({ transcript: $("#ak-text").value, audio_b64: audio || null, respond_to_mood: $("#ak-mood").checked, video: video || null }));
  if (r.question && r.question !== $("#ak-text").value) $("#ak-text").value = r.question;
  $("#ak-out").innerHTML = '<div class="note good"><b>Answer:</b> ' + esc(r.answer) + "</div>" + audioEl(r.audio) +
    (r.how_said ? '<p class="small"><b>How you asked:</b> ' + esc(r.how_said.vocal_mode) + " (" + esc(r.how_said.confidence) + "), " + esc(r.how_said.emotion) + ", " + esc(r.how_said.volume) + "; answered with emotion " +
      esc(r.voice_used.emotion) + (r.voice_used.whisper ? ", whispering" : "") + ".</p>" : "") +
    '<p class="small"><b>Words understood:</b> ' + r.semantics.words.map(w => esc(w.word) + (w.known_to_builder ? "" : "?")).join(" ") + " — " + esc(r.semantics.language_name) + "</p>" +
    (window.faceEvidenceHtml ? faceEvidenceHtml(r.face) + learnedNote(r.learning) : "");
  const a = $("#ak-out audio"); if (a) a.play().catch(() => {});
  const as = $("#ak-as") && $("#ak-as").value;
  if (as) narratorCard($("#ak-out"), Number(as), r.answer, r.voice_used.emotion);   // the author's AI narrator answers
  else if (window.TalkingFace) faceCard($("#ak-out"), r.audio, r.answer, SP.profile.lang, r.voice_used.emotion);
}

// ---------------------------------------------------------------- providers
const PV_LINKS = { google_gemini: "https://aistudio.google.com/apikey", google_cloud: "https://console.cloud.google.com/apis/library/texttospeech.googleapis.com",
  elevenlabs: "https://elevenlabs.io/app/settings/api-keys", openai: "https://platform.openai.com/api-keys", azure: "https://portal.azure.com/#create/Microsoft.CognitiveServicesSpeechServices",
  polly: "https://console.aws.amazon.com/iam/" };
async function loadProviders() {
  const r = await api("/api/speech/engines"); SP.meta.keys = r.keys; SP.meta.engines = r.engines;
  $("#pv-list").innerHTML = r.engines.map(e => {
    const k = r.keys[e.id];
    return '<div class="card"><h2>' + esc(e.name) + " " + (e.available ? '<span class="badge good">ready</span>' : '<span class="badge warn">' + esc(e.why_not) + "</span>") + "</h2>" +
      '<p class="small">' + esc(e.notes) + "</p>" +
      (k ? '<div class="row">' + k.fields.map(f => '<input class="grow" data-pv="' + e.id + '" data-f="' + f.field + '" type="' + (f.field === "region" ? "text" : "password") + '" autocomplete="off" placeholder="' +
        esc(f.field.replace(/_/g, " ")) + (f.set ? (f.from_environment ? " — set in the environment" : " — saved (type to replace)") : "") + '"' + (f.field === "region" && f.value ? ' value="' + esc(f.value) + '"' : "") + ">").join("") +
        '<button class="btn" data-pvsave="' + e.id + '">Save</button>' + (k.configured ? '<button class="btn quiet" data-pvforget="' + e.id + '">Forget</button>' : "") +
        '<button class="btn quiet" data-pvtest="' + e.id + '">Test</button></div><p class="small muted">Get a key: <a href="' + PV_LINKS[e.id] + '" target="_blank" rel="noopener">' + esc(PV_LINKS[e.id]) +
        "</a>. Keys stay in this computer's data folder (owner-only) and are sent only to the provider; they are never shown or logged.</p>" :
        '<button class="btn quiet" data-pvtest="' + e.id + '">Test</button>') + '<div class="small" data-pvout="' + e.id + '"></div></div>';
  }).join("");
  $$("[data-pvsave]").forEach(b => b.onclick = async () => {
    const values = {}; $$('[data-pv="' + b.dataset.pvsave + '"]').forEach(i => { if (i.value) values[i.dataset.f] = i.value; });
    await api("/api/speech/keys", { provider: b.dataset.pvsave, values }); toast("Saved."); await loadProviders(); await refreshEngines();
  });
  $$("[data-pvforget]").forEach(b => b.onclick = async () => { await api("/api/speech/keys/forget", { provider: b.dataset.pvforget }); toast("Removed."); await loadProviders(); await refreshEngines(); });
  $$("[data-pvtest]").forEach(b => b.onclick = async () => {
    const id = b.dataset.pvtest, out = $('[data-pvout="' + id + '"]');
    out.textContent = "Testing…";
    try {
      const t0 = performance.now();
      const r2 = await api("/api/speech/generate", { text: "This is a test of the voice.", profile: SP.profile, engine: id, fallback: false });
      out.innerHTML = "✅ " + esc(r2.summary.engine_used) + " answered in " + ((performance.now() - t0) / 1000).toFixed(2) + " s " + audioEl(r2.audio);
    } catch (e) { out.innerHTML = '<span class="badge bad">failed</span> ' + esc(e.message); }
  });
}
const QUICK = [["espeak", "🗣 Built-in voice", "espeak-ng · offline · default"], ["google_gemini", "✨ Google AI voice", "Gemini TTS · 30 voices · emotion"],
  ["google_cloud", "🔊 Google Cloud voices", "Studio / Neural2 / Chirp · SSML"], ["elevenlabs", "🎙 ElevenLabs", "cloud · very natural"],
  ["openai", "💬 OpenAI voice", "cloud · instructions"], ["azure", "🪟 Microsoft Azure", "cloud · styles and roles"]];
function renderQuick() {
  $("#sp-quick").innerHTML = QUICK.map(([id, name, sub]) => {
    const e = SP.meta.engines.find(x => x.id === id) || {};
    return '<button data-quick="' + id + '" aria-pressed="' + (SP.engine === id) + '"><span class="vn">' + name + '</span><span class="vs">' + sub + "</span><br>" +
      (e.available ? '<span class="badge good">ready</span>' : '<span class="badge warn">' + esc(e.needs_key ? "needs a key" : (e.why_not || "unavailable")) + "</span>") + "</button>";
  }).join("");
  $$("[data-quick]").forEach(b => b.onclick = async () => {
    const e = SP.meta.engines.find(x => x.id === b.dataset.quick);
    if (e && !e.available && e.needs_key) {
      toast(e.name + " needs your key: Diagnostics → Google Cloud (one paste sets up Google), or Speech → Voice providers.", true);
    }
    $("#sp-engine").value = b.dataset.quick; await selectEngine(b.dataset.quick); renderQuick();
  });
}
async function refreshEngines() {
  const r = await api("/api/speech/engines"); SP.meta.engines = r.engines;
  setTimeout(renderQuick, 0);
  $("#sp-engine").innerHTML = r.engines.map(e => '<option value="' + e.id + '"' + (e.id === SP.engine ? " selected" : "") + ">" + (e.available ? "● " : "○ ") + esc(e.name) + (e.available ? "" : " — " + esc(e.why_not)) + "</option>").join("");
  await selectEngine(SP.engine);
}

// ---------------------------------------------------------------- log
async function loadLog() {
  const r = await api("/api/speech/log?limit=200" + ($("#lg-proc").value ? "&process=" + $("#lg-proc").value : ""));
  $("#lg-stats").innerHTML = r.stats.length ? '<table class="t small"><tr><th>Process</th><th>Engine</th><th>Runs</th><th>OK</th><th>Mean</th><th>Fastest</th><th>Slowest</th><th>Total</th></tr>' +
    r.stats.map(s => "<tr><td>" + esc(s.process) + "</td><td>" + esc(s.engine) + "</td><td>" + s.runs + "</td><td>" + s.ok + "</td><td>" + Number(s.mean_s).toFixed(2) + "</td><td>" + Number(s.min_s).toFixed(2) +
      "</td><td>" + Number(s.max_s).toFixed(2) + "</td><td>" + Number(s.total_s).toFixed(2) + "</td></tr>").join("") + "</table>" : '<p class="muted">Nothing yet.</p>';
  $("#lg-out").innerHTML = r.log.length ? '<table class="t small"><tr><th>#</th><th>Started (UTC)</th><th>Seconds</th><th>Process</th><th>Engine</th><th>Status</th><th>What</th><th>Audio</th></tr>' + r.log.map(x =>
    "<tr><td>" + x.id + '</td><td class="mono">' + esc(x.started) + "</td><td><b>" + Number(x.seconds || 0).toFixed(2) + "</b></td><td>" + esc(x.process) + "</td><td>" + esc(x.engine) + "</td><td>" + esc(x.status) +
    "</td><td>" + esc(x.description) + (x.stages && x.stages.length ? '<details><summary class="small">' + x.stages.length + " stages</summary>" + stagesTable(x.stages, x.seconds) + "</details>" : "") + "</td><td>" +
    (x.audio ? audioEl(x.audio) : "") + "</td></tr>").join("") + "</table>" : '<p class="muted">No speech processes yet.</p>';
}

// ---------------------------------------------------------------- setup
function showSub(id) {
  $$("#sptabs button").forEach(b => b.setAttribute("aria-pressed", b.dataset.sp === id));
  $$("#speech .sp").forEach(s => s.hidden = s.id !== "sp-" + id);
  $("#sp-shared").hidden = !["speak", "match", "ask"].includes(id);
  if (id === "providers") loadProviders();
  if (id === "log") loadLog();
}

async function loadSpeech() {
  if (SP.loaded) { schedulePlan(); return; }
  SP.meta = await api("/api/speech/engines");
  SP.profile = Object.assign({}, SP.meta.profile_default);
  $("#pf-emotion").innerHTML = SP.meta.emotions.map(e => '<button data-v="' + e + '">' + e + "</button>").join("");
  $("#pf-articulation").innerHTML = SP.meta.articulation.map(e => '<button data-v="' + e + '">' + e + "</button>").join("");
  $("#pf-tone").innerHTML = SP.meta.tones.map(t => "<option>" + t + "</option>").join("");
  $("#pf-lang").innerHTML = SP.meta.languages.map(l => '<option value="' + l.code + '">' + esc(l.name) + "</option>").join("");
  $("#pf-accent").innerHTML = '<option value="">standard</option>' + SP.meta.dialects.map(d => '<option value="' + d.id + '">' + esc(d.name) + "</option>").join("");
  $$("#pf-emotion button").forEach(b => b.onclick = () => { SP.profile.emotion = b.dataset.v; profileUI(); schedulePlan(); });
  $$("#pf-articulation button").forEach(b => b.onclick = () => { SP.profile.articulation = b.dataset.v; profileUI(); schedulePlan(); });
  ["intensity", "rate", "pitch_st", "volume_db", "pause_scale", "tremble", "hoarse", "breath", "age"].forEach(k => $("#pf-" + k).oninput = e => { SP.profile[k] = Number(e.target.value); profileUI(); schedulePlan(); });
  $("#pf-tone").onchange = e => { SP.profile.tone = e.target.value; schedulePlan(); };
  $("#pf-lang").onchange = async e => { SP.profile.lang = e.target.value; await loadVoices(); schedulePlan(); };
  $("#pf-accent").onchange = e => { SP.profile.accent = e.target.value; profileUI(); schedulePlan(); };
  $("#pf-gender").onchange = e => { SP.profile.gender = e.target.value; schedulePlan(); };
  $("#pf-whisper").onchange = e => { SP.profile.whisper = e.target.checked; schedulePlan(); };
  $("#sp-presets").innerHTML = "<span class=\"small muted\">Presets:</span>" + PRESETS.map((p, i) => '<button data-preset="' + i + '">' + esc(p[0]) + "</button>").join("");
  $$("[data-preset]").forEach(b => b.onclick = () => {
    const [name, prof, adv] = PRESETS[Number(b.dataset.preset)];
    SP.profile = Object.assign({}, SP.meta.profile_default, { lang: SP.profile.lang }, prof);
    SP.adv = JSON.parse(JSON.stringify(adv));
    profileUI(); renderAdv(); schedulePlan(); toast("Preset: " + name);
  });
  $("#sp-engine").onchange = async e => { await selectEngine(e.target.value); renderQuick(); };
  $("#sp-voice").onchange = schedulePlan; $("#sp-model").onchange = schedulePlan; $("#sp-text").oninput = schedulePlan;
  $("#sp-go").onclick = generate;
  $("#mt-go").onclick = match;
  $("#ls-rec").onclick = lsRecord;
  $("#ls-file").onchange = async e => { const f = e.target.files[0]; if (!f) return; SP.video = null; SP.wav = await blobB64(f); SP.wavName = f.name; $("#ls-audio").src = URL.createObjectURL(f); $("#ls-audio").hidden = false; $("#ls-go").disabled = false; $("#ls-recstate").textContent = f.name; };
  $("#ls-go").onclick = lsAnalyse;
  $("#ak-rec").onclick = akRecord; $("#ak-go").onclick = () => ask(null); onEnter($("#ak-text"), () => ask(null));
  $("#lg-go").onclick = loadLog; $("#lg-proc").onchange = loadLog;
  $("#cv-go").onclick = async () => {
    const f = $("#cv-file").files[0]; if (!f) { toast("Choose a voice sample first.", true); return; }
    const r = await api("/api/speech/custom-voice", { name: $("#cv-name").value, language: $("#cv-lang").value, consent: $("#cv-consent").checked, audio_b64: await blobB64(f) });
    $("#cv-out").textContent = "Custom voice '" + r.name + "' built. Choose it in the Google Cloud voice list."; loadProviders();
  };
  $("#ik-go").onclick = async () => {
    const r = await api("/api/speech/keys/import-prototype", { folder: $("#ik-f").value });
    $("#ik-out").innerHTML = r.imported.length ? '<div class="note good">✔ Imported from <span class="mono">' + esc(r.found) + "</span>: " + r.imported.map(esc).join(", ") +
      (r.defaults && r.defaults.google_voice ? ". The prototype used Google voice <b>" + esc(r.defaults.google_voice) + "</b>" + (r.defaults.google_model ? " (" + esc(r.defaults.google_model) + ")" : "") : "") +
      ". Press <b>Test</b> below to check each provider.</div>"
      : '<div class="note bad">No old QueryBook key file found (' + r.searched + " found in the usual places). Type the old QueryBook folder above — the one with <span class=\"mono\">qb_language.py</span> — and try again.</div>";
    await loadProviders(); await refreshEngines();
  };
  $$("#sptabs button").forEach(b => b.onclick = () => showSub(b.dataset.sp));
  ["#ak-cam", "#ls-cam"].forEach(id => $(id).addEventListener("change", e => { if (e.target.checked && window.tracker) tracker().catch(() => {}); }));
  renderTargets();
  profileUI();
  SP.loaded = true;
  await refreshEngines();
}
