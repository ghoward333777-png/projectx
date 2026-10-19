"use strict";
// Avatar library: portraits → depth avatars that speak with all 52 face channels (Speech → Avatars).
const AV = { list: [], sel: null, face: null, audio: null, sources: {} };

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
  const L = r.faceLandmarks && r.faceLandmarks[0];
  return L ? L.map(p => [Math.round(p.x * 1e5) / 1e5, Math.round(p.y * 1e5) / 1e5, Math.round(p.z * 1e5) / 1e5]) : null;
}

async function avAnalyse(el, all) {
  const todo = AV.list.filter(a => all || !a.analysed), out = $("#av-msg", el);
  for (let n = 0; n < todo.length; n++) {
    out.textContent = "Analysing faces " + (n + 1) + " of " + todo.length + " (478 points with depth)…";
    let L = null;
    try { L = await avLandmarks("/api/avatars/image?id=" + todo[n].id); } catch (e) { L = null; }
    await api("/api/avatars/landmarks", { id: todo[n].id, landmarks: L || [] });
  }
  out.textContent = todo.length ? "Analysed " + todo.length + " portrait(s)." : "All portraits are analysed.";
  await avRefresh(el);
}

async function avRefresh(el) {
  const r = await api("/api/avatars/list");
  AV.list = r.avatars; AV.sources = r.sources;
  $("#av-grid", el).innerHTML = AV.list.length ? AV.list.map(a => '<div class="av-tile' + (AV.sel && AV.sel.id === a.id ? " sel" : "") + '" data-av="' + a.id + '" style="display:inline-block;width:132px;margin:4px;vertical-align:top;cursor:pointer;border:2px solid ' +
    (AV.sel && AV.sel.id === a.id ? "var(--accent,#1f6feb)" : "transparent") + ';border-radius:10px;padding:4px">' +
    '<img src="/api/avatars/image?id=' + a.id + '" alt="" loading="lazy" style="width:120px;height:120px;object-fit:cover;border-radius:8px">' +
    '<div class="small"><b>' + esc(a.name) + "</b></div>" + (a.tags.length ? '<div class="small muted">' + esc(a.tags.join(", ")) + "</div>" : "") +
    '<div class="small">' + (!a.analysed ? cmTag("not analysed", "warn") : (a.quality || []).length ? cmTag((a.quality || []).length + " note(s)", "warn") : cmTag("ready", "good")) + "</div></div>").join("")
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
  if (!a.analysed) { $("#av-stage", el).innerHTML = '<p class="muted">Analyse the faces first.</p>'; return; }
  AV.face = new TalkingFace($("#av-stage", el));
  await AV.face.setMode("avatar", { avatar: { imageUrl: "/api/avatars/image?id=" + a.id, landmarks: a.landmarks, label: a.label } });
  avChannels(el);
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
  AV.face.attach(a, { visemes: [], motion: res.motion });
  a.play().catch(() => {});
  note.textContent = res.motion.frames.length + " frames × 52 channels at " + res.motion.fps + " fps · voice: " + r.engine_used + " · " + ((performance.now() - t0) / 1000).toFixed(1) + " s";
}

async function renderAvatars(el) {
  if (!el.dataset.ready) {
    el.dataset.ready = "1";
    el.innerHTML =
      '<div class="card"><h2>Avatar library</h2><p class="small muted">Portraits become talking avatars. Each portrait is measured at 478 points with depth; when the avatar speaks, ' +
      "the Visual Speech Engine drives <b>all 52 face channels</b> (jaw, lips, cheeks, nose, eyelids, eye direction, brows, tongue) with natural co-articulation, blinks and head motion, and the head turns in 3D. " +
      "Only portraits that show nobody real (AI-generated), or a real person who agreed, can be added — every avatar is labelled as synthetic.</p>" +
      '<div class="row small"><label><input type="radio" name="av-src" value="synthetic" checked> AI-generated portraits (no real person)</label>' +
      '<label><input type="radio" name="av-src" value="consented"> A real person who agreed</label></div>' +
      '<div class="row small" id="av-syn"><label><input type="checkbox" id="av-attest"> I confirm these portraits are AI-generated and show no real person.</label></div>' +
      '<div class="row small" id="av-con" hidden><input id="av-subject" type="text" placeholder="the person\'s name" aria-label="Person"><label><input type="checkbox" id="av-consent"> They agreed to become an avatar (consent)</label></div>' +
      '<div class="row"><input id="av-files" type="file" accept="image/png,image/jpeg,image/webp" multiple aria-label="Portraits"><span class="small muted">or a folder / .zip on this computer</span>' +
      '<input id="av-path" class="grow" type="text" placeholder="/path/to/portraits.zip" aria-label="Folder or zip"><button class="btn" id="av-import">Import</button>' +
      '<button class="btn quiet" id="av-analyse">Analyse faces</button></div><div class="small" id="av-msg" aria-live="polite"></div>' +
      '<div id="av-grid" style="margin-top:8px"></div></div>' +
      '<div class="card" id="av-studio" hidden><h2>Avatar studio</h2><div class="row"><input id="av-name" type="text" aria-label="Name"><input id="av-tags" class="grow" type="text" placeholder="tags, comma separated" aria-label="Tags">' +
      '<button class="btn quiet" id="av-save">Save</button><button class="btn quiet" id="av-voice">Give it the Speak tab\'s current voice</button><button class="btn quiet" id="av-del">Delete</button></div><div id="av-info"></div>' +
      '<div class="grid2"><div><div id="av-stage" style="max-width:440px"></div><div id="av-player" class="row"></div><p class="small muted" id="av-note"></p></div>' +
      '<div><textarea id="av-text" rows="3" aria-label="What the avatar says">Hello! I can speak any text you give me, with natural lips, eyes and expressions.</textarea>' +
      '<div class="row"><button class="btn bigbtn" id="av-speak">🗣 Speak</button></div>' +
      '<p class="small"><b>Try an expression:</b> ' + Object.keys(AV_PRESETS).map(k => '<button class="btn quiet small" data-avp="' + k + '">' + k + "</button>").join(" ") + "</p>" +
      '<p class="small muted">The 52 face channels — move any slider to see what it does:</p><div id="av-ch"></div></div></div></div>';
    el.querySelectorAll('input[name="av-src"]').forEach(r => r.onchange = () => {
      const syn = el.querySelector('input[name="av-src"]:checked').value === "synthetic";
      $("#av-syn", el).hidden = !syn; $("#av-con", el).hidden = syn;
    });
    $("#av-import", el).onclick = async () => {
      const source = el.querySelector('input[name="av-src"]:checked').value, attest = $("#av-attest", el).checked;
      let r;
      if (source === "consented") {
        const fs = [...$("#av-files", el).files];
        if (!fs.length) return toast("Choose the person's portrait.");
        let added = 0;
        for (const f of fs) {
          const data = await new Promise(res => { const rd = new FileReader(); rd.onload = () => res(rd.result); rd.readAsDataURL(f); });
          const x = await api("/api/avatars/add", { data_b64: data, filename: f.name, source, subject: $("#av-subject", el).value, consent: $("#av-consent", el).checked });
          if (!x.duplicate) added++;
        }
        r = { added, duplicates: fs.length - added, failed: [] };
      } else if ($("#av-path", el).value.trim()) {
        r = await api("/api/avatars/import", { path: $("#av-path", el).value.trim(), source, attest });
      } else {
        const fs = [...$("#av-files", el).files];
        if (!fs.length) return toast("Choose portraits, or give a folder or .zip.");
        const files = await Promise.all(fs.map(f => new Promise(res => { const rd = new FileReader(); rd.onload = () => res({ name: f.name, data_b64: rd.result }); rd.readAsDataURL(f); })));
        r = await api("/api/avatars/import", { files, source, attest });
      }
      $("#av-msg", el).textContent = "Added " + r.added + (r.duplicates ? ", " + r.duplicates + " already in the library" : "") + (r.failed.length ? ", " + r.failed.length + " skipped" : "") + ".";
      await avRefresh(el);
      if (r.added) await avAnalyse(el, false);
    };
    $("#av-analyse", el).onclick = () => avAnalyse(el, true);
    $("#av-grid", el).onclick = e => { const t = e.target.closest("[data-av]"); if (t) avSelect(el, Number(t.dataset.av)); };
    $("#av-save", el).onclick = async () => { await api("/api/avatars/update", { id: AV.sel.id, name: $("#av-name", el).value, tags: $("#av-tags", el).value.split(",").map(s => s.trim()).filter(Boolean) }); avRefresh(el); toast("Saved."); };
    $("#av-voice", el).onclick = async () => {
      if (!$("#sp-engine") || !$("#sp-engine").value) return toast("Choose a voice on the Speak tab first.");
      await api("/api/avatars/update", { id: AV.sel.id, voice: { engine: $("#sp-engine").value, voice: ($("#sp-voice") || {}).value || "", model: ($("#sp-model") || {}).value || "", lang: (typeof SP !== "undefined" && SP.profile && SP.profile.lang) || "en" } });
      toast("This avatar now speaks with that voice."); avSelect(el, AV.sel.id);
    };
    $("#av-del", el).onclick = async () => { if (!confirm("Delete this avatar and its portrait?")) return; await api("/api/avatars/delete", { id: AV.sel.id }); AV.sel = null; $("#av-studio", el).hidden = true; avRefresh(el); };
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
}
