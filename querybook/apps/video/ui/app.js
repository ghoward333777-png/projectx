"use strict";
let INFO = null, PERSONAS = [], SHOTS = [];
const opt = (v, label, sel) => '<option value="' + esc(v) + '"' + (sel ? " selected" : "") + ">" + esc(label || v) + "</option>";
const secs = s => s === null || s === undefined ? "?" : s < 90 ? Number(s).toFixed(1) + " s" : Math.round(s / 60) + " min";

async function loadInfo() {
  INFO = await api("/api/studio/info");
  $("#p-format").innerHTML = INFO.formats.map(f => opt(f)).join("");
  $("#p-grade").innerHTML = INFO.grades.map(g => opt(g)).join("");
  $("#p-engine").innerHTML = INFO.engines.map(e => opt(e, e, e === "espeak")).join("");
  $("#l-actions").innerHTML = INFO.actions.map(a => opt(a.id)).join("");
  const lb = INFO.language;
  $("#lbstate").innerHTML = lb.ok ? '<span class="badge good">Language Builder connected</span> version ' + esc(lb.version || "") + " — voices and narrators available"
    : '<div class="note bad"><b>Language Builder is not running</b> (' + esc(lb.url) + "). <b>Start it first</b> for voices and narrators; action shots without voices still work.</div>";
  const p = await api("/api/personas");
  PERSONAS = p.personas || [];
  if (!SHOTS.length) SHOTS = [{ type: "action", action: INFO.stored_actions[0] || "walk-toward", say: "" }];
  drawShots();
  loadProjects();
}

function actionOptions(cur) {
  const stored = new Set(INFO.stored_actions);
  const ids = Array.from(new Set(INFO.actions.map(a => a.id).concat(INFO.stored_actions)));
  return ids.map(a => opt(a, a + (stored.has(a) ? " — stored (fast)" : " — generated once"), a === cur)).join("");
}

function drawShots() {
  $("#shots").innerHTML = SHOTS.map((s, i) => {
    const head = '<div class="hd"><b>Shot ' + (i + 1) + (s.type === "talk" ? " — narrator" : " — action") + "</b>" +
      (i ? '<button class="btn quiet" data-up="' + i + '">↑</button>' : "") + '<button class="btn quiet" data-del="' + i + '">Remove</button></div>';
    if (s.type === "talk") {
      const ps = PERSONAS.length ? PERSONAS.map(p => opt(p.id, p.name || p.id, p.id === s.persona)).join("") : opt("", "no narrators — create one in Language Builder");
      return '<div class="shot">' + head + '<div class="grid3"><div><label class="f">Narrator</label><select data-k="persona" data-i="' + i + '">' + ps + "</select></div>" +
        '<div><label class="f">Made by</label><select data-k="face_method" data-i="' + i + '">' + Object.entries(INFO.face_methods).map(([k, v]) => opt(k, v, k === s.face_method)).join("") + "</select></div>" +
        '<div><label class="f">Emotion (optional)</label><input type="text" data-k="emotion" data-i="' + i + '" value="' + esc(s.emotion || "") + '"></div></div>' +
        '<label class="f">What the narrator says</label><textarea data-k="text" data-i="' + i + '">' + esc(s.text || "") + "</textarea></div>";
    }
    return '<div class="shot">' + head + '<div class="grid3"><div><label class="f">Action</label><select data-k="action" data-i="' + i + '">' + actionOptions(s.action) + "</select></div>" +
      '<div><label class="f">Speed</label><select data-k="speed" data-i="' + i + '">' + [["1", "normal"], ["0.5", "half (slow motion)"], ["0.75", "slower"], ["1.5", "faster"]].map(([v, l]) => opt(v, l, String(s.speed || 1) === v)).join("") + "</select></div>" +
      '<div><label class="f">Longest (seconds, optional)</label><input type="number" min="1" step="0.5" data-k="max_seconds" data-i="' + i + '" value="' + esc(s.max_seconds || "") + '"></div></div>' +
      '<label class="f">Voice-over (optional, spoken by Language Builder)</label><textarea data-k="say" data-i="' + i + '">' + esc(s.say || "") + "</textarea></div>";
  }).join("");
  $$("#shots [data-k]").forEach(el => el.onchange = el.oninput = () => {
    const s = SHOTS[Number(el.dataset.i)], k = el.dataset.k;
    s[k] = k === "speed" ? Number(el.value) : k === "max_seconds" ? (el.value ? Number(el.value) : null) : el.value;
  });
  $$("#shots [data-del]").forEach(b => b.onclick = () => { SHOTS.splice(Number(b.dataset.del), 1); drawShots(); });
  $$("#shots [data-up]").forEach(b => b.onclick = () => { const i = Number(b.dataset.up); [SHOTS[i - 1], SHOTS[i]] = [SHOTS[i], SHOTS[i - 1]]; drawShots(); });
}

function project() {
  return {
    name: $("#p-name").value.trim() || "video", format: $("#p-format").value, grade: $("#p-grade").value,
    voice: { engine: $("#p-engine").value, voice: $("#p-voice").value.trim(), lang: $("#p-lang").value.trim() || "en" },
    fps: $("#p-fps").value ? Number($("#p-fps").value) : null, height: $("#p-height").value ? Number($("#p-height").value) : null,
    interp: $("#p-interp").value, bridges: $("#p-bridges").checked, captions: $("#p-captions").checked, burn_captions: $("#p-burn").checked,
    shots: SHOTS.map(s => Object.assign({}, s)),
  };
}

function setProject(p) {
  $("#p-name").value = p.name || ""; $("#p-format").value = p.format || "horizontal"; $("#p-grade").value = p.grade || "none";
  const v = p.voice || {}; $("#p-engine").value = v.engine || "espeak"; $("#p-voice").value = v.voice || ""; $("#p-lang").value = v.lang || "en";
  $("#p-fps").value = p.fps || ""; $("#p-height").value = p.height || ""; $("#p-interp").value = p.interp || "best";
  $("#p-bridges").checked = p.bridges !== false; $("#p-captions").checked = p.captions !== false; $("#p-burn").checked = !!p.burn_captions;
  SHOTS = (p.shots || []).map(s => Object.assign({}, s)); drawShots();
}

async function loadProjects() {
  const r = await api("/api/projects");
  window._projects = r.projects;
  $("#projects").innerHTML = opt("", "Open a saved project…") + r.projects.map((p, i) => opt(String(i), p.name)).join("");
}

async function showPlan() {
  const r = await api("/api/studio/plan", { project: project() });
  $("#planout").innerHTML = '<table class="plan"><tr><th>Shot</th><th>What</th><th>Route</th><th>Why</th><th>About</th></tr>' +
    r.shots.map(s => "<tr><td>" + s.shot + "</td><td>" + esc(s.what) + (s.voice_over ? '<div class="small muted">' + esc(s.voice_over) + "</div>" : "") +
      "</td><td>" + cmTag(s.route, s.route === "reuse" ? "good" : s.route === "missing" ? "bad" : "warn") + "</td><td>" + esc(s.why) + "</td><td>" + secs(s.estimate_s) + "</td></tr>").join("") +
    r.frame_work.map(e => '<tr><td></td><td>' + esc(e.step) + "</td><td>" + esc(e.backend) + "</td><td>" + esc(e.why) + "</td><td>" + secs(e.estimate_s) + "</td></tr>").join("") +
    "</table><p><b>Estimated total: " + secs(r.estimate_s) + "</b>" + (r.generator ? "" : ' <span class="small muted">(no video-model key: actions not in the library cannot be made)</span>') + "</p>";
}

function showResult(rep) {
  if (!rep || !rep.output) return;
  const u = "/api/output?name=" + encodeURIComponent(rep.output);
  $("#result").innerHTML = '<div class="note ' + (rep.ok ? "good" : "bad") + '"><b>' + (rep.ok ? "Finished and checked" : "Finished — a check failed") + "</b> — " +
    esc(rep.duration_s) + " s video, " + esc(rep.size) + ", made in " + secs(rep.total_s) + "</div>" +
    '<div class="out"><video controls src="' + u + '"></video></div>' +
    '<p class="small"><a href="' + u + '" download>Download the video</a>' + (rep.captions ? ' · <a href="/api/output?name=' + encodeURIComponent(rep.captions) + '" download>captions (.srt)</a>' : "") + "</p>" +
    '<ul class="small">' + rep.shots.map(s => "<li>Shot " + s.shot + ": " + esc(s.what || s.type) + " — " + esc(s.route) + (s.voice_over ? ", voice " + esc(s.voice_over) : "") +
      (s.held_s ? ", held " + s.held_s + " s for the voice" : "") + (s.lip_sync_kept === false ? ' <span class="badge bad">lip-sync length changed</span>' : "") +
      (s.ok ? ' <span class="badge good">OK</span>' : ' <span class="badge bad">check failed</span>') + "</li>").join("") +
    (rep.joins || []).map(j => "<li>Join " + j.join + ": " + esc(j.how) + (j.backend ? " (" + esc(j.backend) + ")" : "") + "</li>").join("") +
    "<li>Sound matches picture: " + (rep.sound_matches_picture ? "yes" : "no") + "</li></ul>";
}

async function render() {
  await api("/api/studio/render", { project: project() });
  $("#result").innerHTML = "";
  pollJob($("#job"), j => { if (j.state === "finished") { showResult(j.result); toast("The video is ready."); } });
}

async function loadLibrary() {
  const r = await api("/api/library");
  $("#clips").innerHTML = r.clips.length ? '<div class="clips">' + r.clips.map(c => '<div class="clip"><img loading="lazy" alt="" src="/api/library/thumb?id=' + esc(c.id) + '">' +
    '<div class="small"><b>' + esc(c.action.startsWith("talk-") ? "narration" : c.action) + "</b> · " + esc(c.duration_s) + " s" + (c.look ? " · " + esc(c.look) : "") +
    '</div><div class="small muted">' + esc(c.source) + '</div><div class="row small"><a href="/api/library/clip?id=' + esc(c.id) + '" target="_blank">Play</a>' +
    '<button class="btn quiet" data-rm="' + esc(c.id) + '">Remove</button></div></div>').join("") + "</div>"
    : '<p class="muted">No clips yet. Add footage above, or make a video: generated actions and narrations are stored here.</p>';
  $$("#clips [data-rm]").forEach(b => b.onclick = async () => { if (confirm("Remove this clip from the library?")) { await api("/api/library/remove", { id: b.dataset.rm }); loadLibrary(); } });
  const t = Object.entries(r.timings).filter(([, v]) => v);
  $("#timings").innerHTML = t.length ? "Measured here (median seconds): " + t.map(([k, v]) => esc(k.replace(/_/g, " ")) + " " + Number(v).toFixed(1)).join(" · ") : "";
}

async function loadOutputs() {
  const r = await api("/api/outputs");
  $("#outs").innerHTML = r.outputs.length ? r.outputs.map(o => '<div class="card"><b>' + esc(o.project_name || o.output) + "</b> " + cmTag(o.ok ? "checked" : "check failed", o.ok ? "good" : "bad") +
    '<div class="small muted">' + esc(o.finished || "") + " · " + esc(o.duration_s) + " s · " + esc(o.size) + " · made in " + secs(o.total_s) + "</div>" +
    '<div class="out"><video controls preload="none" src="/api/output?name=' + encodeURIComponent(o.output) + '"></video></div>' +
    '<p class="small"><a download href="/api/output?name=' + encodeURIComponent(o.output) + '">Download</a>' + (o.captions ? ' · <a download href="/api/output?name=' + encodeURIComponent(o.captions) + '">captions</a>' : "") + "</p></div>").join("")
    + '<p class="small muted">Saved in ' + esc(r.folder) + "</p>" : '<p class="muted">No videos yet.</p>';
}

async function loadSettings() {
  const s = await api("/api/settings");
  $("#s-url").value = s.language_url;
  $("#s-keystate").textContent = s.gemini_key_set ? "A key is set (" + s.gemini_key_hint + ", from " + s.gemini_key_from + ")." : "No key: only actions already in the library can be used.";
}

function fileData(file) {
  return new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = bad; r.readAsDataURL(file); });
}

document.addEventListener("DOMContentLoaded", () => {
  setupTabs(id => {
    if (id === "studio") loadInfo();
    if (id === "library") loadLibrary();
    if (id === "outputs") loadOutputs();
    if (id === "settings") loadSettings();
    if (id === "diag") renderDiagnostics($("#diag"));
  });
  $("#add-action").onclick = () => { SHOTS.push({ type: "action", action: (INFO && INFO.stored_actions[0]) || "walk-toward", say: "" }); drawShots(); };
  $("#add-talk").onclick = () => { SHOTS.push({ type: "talk", persona: PERSONAS[0] ? PERSONAS[0].id : "", face_method: "gemini", text: "" }); drawShots(); };
  $("#plan").onclick = showPlan;
  $("#render").onclick = render;
  $("#stop").onclick = () => api("/api/job/stop", {});
  $("#saveproj").onclick = async () => { await api("/api/projects/save", { project: project() }); toast("Project saved."); loadProjects(); };
  $("#projects").onchange = () => { const p = (window._projects || [])[Number($("#projects").value)]; if ($("#projects").value !== "" && p) setProject(p.project); };
  $("#l-add").onclick = async () => {
    const f = $("#l-file").files[0];
    if (!f) return toast("Choose a video file.", true);
    const r = await api("/api/library/add", { action: $("#l-action").value, look: $("#l-look").value, source: $("#l-source").value, consent: $("#l-consent").value, data: await fileData(f) });
    toast(r.warning || "Added to the library.", !!r.warning); loadLibrary();
  };
  $("#s-save").onclick = async () => {
    const b = { language_url: $("#s-url").value };
    if ($("#s-key").value) b.gemini_key = $("#s-key").value;
    await api("/api/settings", b); $("#s-key").value = ""; toast("Saved."); loadSettings();
  };
  refreshFooter();
  pollJob($("#job"), j => { if (j.state === "finished") showResult(j.result); });
});
