// Speech motion library (Language 1.47, Avatar studio): a person's own mouth movement, sound by sound, from exemplar clips.
// Each approved exemplar clip of the person is read here frame by frame with the face tracker (478 points), its own sound is
// cut into phonemes by the Visual Speech Engine, and both go to the program, which removes the head's movement, measures how
// the lower face moved from her closed-mouth rest, and keeps it per sound in context. Built into a library and given to an
// avatar (admin), the avatar then speaks with her movement — chosen sound by sound and joined to the new timing — instead of
// the hand-built mouth model. The exemplars are learning objects: QueryBook measures them; it never asks the model that made them.
"use strict";

// the face tracker for clips: single pictures, with the blendshapes (the lip reader's measures) as well as the 478 points
async function mlTracker() {
  if (window._mlLm) return window._mlLm;
  const vision = await import("./vendor/mediapipe/vision_bundle.mjs"), files = await vision.FilesetResolver.forVisionTasks("vendor/mediapipe/wasm");
  const opts = d => ({ baseOptions: { modelAssetPath: "vendor/mediapipe/face_landmarker.task", delegate: d }, runningMode: "IMAGE", numFaces: 1, outputFaceBlendshapes: true });
  try { window._mlLm = await vision.FaceLandmarker.createFromOptions(files, opts("GPU")); }
  catch (e) { window._mlLm = await vision.FaceLandmarker.createFromOptions(files, opts("CPU")); }
  return window._mlLm;
}
// every frame of a clip, tracked: 478 points in pixels (null where no face was found), and the same frame as the lip reader
// measures it (lip gap and mouth blendshapes — for the lip-reading curriculum)
async function mlTrack(url, fps, note) {
  const lm = await mlTracker(), v = document.createElement("video");
  v.muted = true; v.preload = "auto"; v.src = url;
  await new Promise((res, rej) => { v.onloadeddata = res; v.onerror = () => rej(new Error("this clip cannot be played here")); });
  const W = v.videoWidth, H = v.videoHeight, c = document.createElement("canvas"); c.width = W; c.height = H;
  const g = c.getContext("2d"), seek = t => new Promise(r => { const k = setTimeout(r, 4000); v.onseeked = () => { clearTimeout(k); r(); }; v.currentTime = t; }),
    n = Math.floor(v.duration * fps), out = [], lip = [];
  for (let i = 0; i < n; i++) {
    await seek(i / fps); g.drawImage(v, 0, 0);
    const r = lm.detect(c), L = r.faceLandmarks && r.faceLandmarks[0];
    out.push(L ? L.map(p => [Math.round(p.x * W * 10) / 10, Math.round(p.y * H * 10) / 10]) : null);
    const m = measureFrame(r, { videoWidth: W, videoHeight: H }, i / fps);
    lip.push({ t: m.t, face: m.face, gap: m.gap, bs: m.bs });
    if (i % 24 === 0) note("frame " + i + " of " + n);
  }
  return { frames: out, lip };
}

// one exemplar take → analysed on the program's side
async function mlAnalyse(person, take, note) {
  const blob = await (await fetch("/api/exemplars/file?id=" + encodeURIComponent(take.id))).blob();
  note(take.item + ": cutting her own sound into phonemes");
  const job = await api("/api/vse/lip_sync", { audio_b64: await rvWav(blob), text: take.script || "", lang: "en" }), res = await avWaitJob(job.job_id);
  const url = URL.createObjectURL(await rvPlayable(blob));        // (converted to WebM by ffmpeg where this browser cannot play it)
  try {
    const tr = await mlTrack(url, 24, m => note(take.item + ": tracking " + m));
    await api("/api/vse/curriculum/clip", { exemplar: take.id, item: take.item, skill: take.skill, script: take.script || "", frames: tr.lip });
    return await api("/api/motionlib/clip", { person, exemplar: take.id, fps: 24, frames: tr.frames, phonemes: res.phonemes, script: take.script || "" });
  } finally { URL.revokeObjectURL(url); }
}

// the takes to learn from: each item's approved exemplar; where none is approved yet, its best passing take (shown as such)
async function mlTakes(skill) {
  const r = await api("/api/exemplars?skill=" + encodeURIComponent(skill)), by = {};
  for (const t of r.takes) if (t.kind === "video" && t.script && t.status !== "rejected" && t.status !== "retired") (by[t.item] = by[t.item] || []).push(t);
  const pass = t => t.overall !== null && t.checks.every(c => c.ok);
  return Object.keys(by).sort().map(item => {
    const ts = by[item], ex = ts.find(t => t.status === "exemplar");
    if (ex) return Object.assign({ approved: true }, ex);
    const ok = ts.filter(pass).sort((a, b) => b.overall - a.overall || (a.added < b.added ? -1 : 1));
    return ok.length ? Object.assign({ approved: false }, ok[0]) : null;
  }).filter(Boolean);
}

async function mlSection(box, a) {
  const guess = (a.name || "").split(/[ —-]/)[0] || "";
  box.innerHTML = '<h4 style="margin:8px 0 4px">Speech motion library <span class="muted">(her own mouth movement, sound by sound, from exemplar clips)</span></h4>' +
    '<div class="row"><input data-mlperson placeholder="whose movement (e.g. Pamela)" value="' + esc(guess) + '" style="width:12em">' +
    '<input data-mlskill placeholder="exemplar skill" value="speech-video-' + esc(guess.toLowerCase()) + '" style="width:16em">' +
    '<button class="btn" data-mlbuild>Build from exemplars</button><span class="muted" data-mln></span></div>' +
    '<div class="row"><input type="password" data-mlpass placeholder="admin passphrase" style="width:12em">' +
    '<button class="btn quiet" data-mluse>Speak with this movement</button><button class="btn quiet" data-mloff>Back to the mouth model</button></div><div data-mlout class="small"></div>';
  const note = m => { box.querySelector("[data-mln]").textContent = m; }, $p = () => box.querySelector("[data-mlperson]").value.trim();
  const show = async () => {
    const r = await api("/api/motionlib"), mine = r.assignments[String(a.id)];
    box.querySelector("[data-mlout]").innerHTML = (r.libraries.length ? r.libraries.map(l => '<div>' + esc(l.person) + ': ' + l.clips + ' clips, ' + l.units +
      ' sounds in context' + (mine === l.slug ? ' — <b>this avatar speaks with it</b>' : '') + '</div>').join("") : '<div class="muted">No library yet.</div>') +
      (mine ? "" : '<div class="muted">This avatar uses the hand-built mouth model.</div>');
  };
  box.querySelector("[data-mlbuild]").onclick = async () => {
    const person = $p(), skill = box.querySelector("[data-mlskill]").value.trim();
    if (!person) return toast("Name the person whose movement this is.");
    try {
      const takes = await mlTakes(skill);
      if (!takes.length) return note("No passing video exemplars under " + skill + " — add and score them first (tools/generate_exemplars.py).");
      for (let i = 0; i < takes.length; i++) { note((i + 1) + " of " + takes.length + " — " + takes[i].item); await mlAnalyse(person, takes[i], note); }
      const r = await api("/api/motionlib/build", { person });
      note("Built: " + r.clips + " clips, " + r.units + " sounds in context" + (takes.some(t => !t.approved) ? " (some items not yet approved as exemplars: their best passing take was used)" : ""));
      show();
    } catch (e) { note("Could not build: " + e.message); console.error(e); }
  };
  const assign = async person => {
    try { await api("/api/motionlib/assign", { avatar: a.id, person, passphrase: box.querySelector("[data-mlpass]").value }); toast(person ? "This avatar now speaks with " + person + "'s movement." : "Back to the mouth model."); show(); }
    catch (e) { toast(e.message); }
  };
  box.querySelector("[data-mluse]").onclick = () => assign($p());
  box.querySelector("[data-mloff]").onclick = () => assign("");
  show();
}
