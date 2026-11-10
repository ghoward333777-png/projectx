/* The Ask page: every way to ask QueryBook (type, speak, live camera, a video, a photo, pasted text, a structured query,
   a watched question), every mode (Q&A, guided follow-ups, discussion, tutorial, quiz, flashcards, connections, checking a
   claim) and an answer shaped for the topic (or the format you pick). The arranging is done by the shell (modes.py);
   this page only collects the question and draws the answer. The page is built once and kept, so a running camera or a
   half-done quiz survives switching areas. */
"use strict";

function akLoad(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }   // (shell.js loads after this file)
const AK = {
  root: null, cat: null, input: akLoad("qb:ask:input", "type"), mode: akLoad("qb:ask:mode", "qa"), format: akLoad("qb:ask:format", "auto"),
  register: akLoad("qb:ask:register", "plain"), turns: [], last: null, busy: false, seed: 1,
  library: null, book: akLoad("qb:ask:book", ""), bookInfo: null,
  det: null, detLoading: null, cam: null, camOn: false, camDets: [], camT0: 0, vidDets: [], photoDets: [],
};
const AK_EXAMPLES = {
  qa: ["When was the printing press invented?", "What does obsequious mean?", "60 mph to km/h", "Marie Curie", "molar mass of H2O"],
  guided: ["Eiffel Tower", "then: when was it built?", "then: and the architect?"],
  discussion: ["Albert Einstein", "Great Wall of China", "Penicillin"],
  tutorial: ["Photosynthesis", "Printing press", "Isaac Newton"],
  quiz: ["Marie Curie", "Paris", "Moon"],
  flashcards: ["Leonardo da Vinci", "serendipity", "Mount Everest"],
  explore: ["Johannes Gutenberg", "Amazon River", "Ada Lovelace"],
  verify: ["The printing press was invented in 1440.", "Marie Curie was born in Paris.", "Mount Everest is in Nepal."],
};
const VERDICT_CLASS = { VERIFIED: "verified", CONTRADICTED: "disputed", UNKNOWN: "" };

async function akPost(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "QueryBook could not answer.");
  return j;
}

function askView() {
  if (!AK.root) {
    AK.root = el("div", { class: "view", id: "askview" },
      el("button", { type: "button", class: "bqbanner", onclick: () => show("bookquery") },
        el("span", { class: "bqbig" }, "📚"),
        el("span", {}, el("b", {}, "Book Query"), el("span", { class: "small" }, "Choose a book from the library and ask it anything — answers quoted from the book, chapter and paragraph.")),
        el("span", { class: "btn" }, "Open →")),
      el("div", { class: "card askcontrols" },
        el("div", { class: "ctlrow" }, el("span", { class: "ctllabel" }, "How you ask"), el("div", { class: "seg", id: "ak-inputs", role: "group", "aria-label": "How you ask" })),
        el("div", { class: "ctlrow" }, el("span", { class: "ctllabel" }, "Mode"), el("div", { class: "seg", id: "ak-modes", role: "group", "aria-label": "Mode" })),
        el("div", { class: "ctlrow" }, el("span", { class: "ctllabel" }, "Answer as"),
          el("select", { id: "ak-format", "aria-label": "Answer format", onchange: e => { AK.format = e.target.value; save("qb:ask:format", AK.format); akRedraw(); } }),
          el("select", { id: "ak-register", "aria-label": "Tone", onchange: e => { AK.register = e.target.value; save("qb:ask:register", AK.register); akRedraw(); } })),
        el("div", { class: "small muted", id: "ak-about" })),
      el("div", { id: "ak-panel" }),
      el("div", { id: "ak-out", "aria-live": "polite" }));
    akCatalog();
  }
  return AK.root;
}

async function akCatalog() {
  try { AK.cat = await (await fetch("/api/shell/modes")).json(); }
  catch (e) { AK.cat = null; }
  akControls(); akPanel(); akRedraw();
}

function akControls() {
  const c = AK.cat; if (!c) return;
  const seg = (box, items, key, after) => {
    const b = AK.root.querySelector(box);
    b.replaceChildren(...items.map(it => el("button", { type: "button", "aria-pressed": String(AK[key] === it.id), title: it.about || "",
      onclick: () => { AK[key] = it.id; save("qb:ask:" + key, it.id); akControls(); after(); } }, it.name)));
  };
  seg("#ak-inputs", c.inputs, "input", () => {
    akStopCamera();
    if (AK.input === "book") { AK.input = "type"; save("qb:ask:input", "type"); akControls(); show("bookquery"); return; }   // its own page
    akPanel();
  });
  seg("#ak-modes", c.modes, "mode", () => { AK.turns = []; akPanel(); if (AK.last && AK.last.question && AK.input !== "check" && AK.input !== "watch") akAsk(AK.last.question); });
  const f = AK.root.querySelector("#ak-format");
  f.replaceChildren(...c.formats.map(x => el("option", { value: x.id, selected: x.id === AK.format }, x.name)));
  const r = AK.root.querySelector("#ak-register");
  r.replaceChildren(...c.registers.map(x => el("option", { value: x.id, selected: x.id === AK.register }, "Tone: " + x.name)));
  const inp = c.inputs.find(x => x.id === AK.input) || {}, md = c.modes.find(x => x.id === AK.mode) || {};
  const book = AK.input === "book";
  AK.root.querySelectorAll(".ctlrow").forEach((row, k) => { row.hidden = book && k > 0; });   // a book answers in its own layers
  AK.root.querySelector("#ak-about").textContent = (inp.about || "") + (book ? "" : " " + (md.about || ""));
}

/* ------------------------------------------------------------------ the input panel */
function akPanel() {
  const p = AK.root.querySelector("#ak-panel");
  p.replaceChildren();
  const box = el("div", { class: "card" });
  p.append(box);
  const askLine = (placeholder, onAsk) => {
    const i = el("input", { type: "search", class: "akinput", placeholder, "aria-label": placeholder });
    const go = () => onAsk(i.value);
    i.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); go(); } });
    return el("div", { class: "akline" }, i, el("button", { class: "btn", type: "button", onclick: go }, "Ask"));
  };
  if (AK.input === "book") {
    box.append(akLibraryPanel());
  } else if (AK.input === "type" || AK.input === "speak") {
    if (AK.input === "speak") box.append(akSpeak());
    else box.append(askLine(AK.mode === "verify" ? "Say something you believe is true" : AK.mode === "guided" && AK.turns.length ? "Ask a follow-up (\"when was it built?\")" : "Ask anything — a word, a fact, a calculation", akAsk));
    box.append(el("div", { class: "tiles small", style: "margin-top:10px" }, (AK_EXAMPLES[AK.mode] || AK_EXAMPLES.qa).map(q =>
      el("button", { class: "tile", type: "button", onclick: () => akAsk(q.replace(/^then: /, "")) }, q))));
    if (AK.mode === "guided") box.append(akTurns());
  } else if (AK.input === "camera") {
    box.append(akCameraPanel());
  } else if (AK.input === "video") {
    box.append(akVideoPanel());
  } else if (AK.input === "photo") {
    box.append(akPhotoPanel());
  } else if (AK.input === "check") {
    const t = el("textarea", { class: "aktext", rows: 7, placeholder: "Paste an article, a paragraph or another AI's answer. Each sentence that states something is checked against the facts QueryBook holds.", "aria-label": "Text to check" });
    box.append(t, el("div", { class: "akline" }, el("button", { class: "btn", type: "button", onclick: () => akCheck(t.value) }, "Check every claim"),
      el("span", { class: "small muted" }, "Up to 12 claims at a time; nothing is sent outside your computer.")));
  } else if (AK.input === "structured") {
    const s = el("input", { class: "akinput", placeholder: "Subject — e.g. Marie Curie", "aria-label": "Subject" });
    const w = el("input", { class: "akinput", placeholder: "What to know — e.g. award, date of birth (blank: everything)", list: "ak-preds", "aria-label": "What to know" });
    const dl = el("datalist", { id: "ak-preds" }, ["date of birth", "place of birth", "occupation", "award received", "inception", "inventor", "country",
      "population", "coordinate location", "chemical formula", "mass", "author", "founded by", "instance of", "part of"].map(x => el("option", { value: x })));
    const go = () => akAsk(s.value, { subject: s.value, want: w.value });
    for (const i of [s, w]) i.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); go(); } });
    box.append(el("div", { class: "akgrid" }, s, w, dl), el("div", { class: "akline" }, el("button", { class: "btn", type: "button", onclick: go }, "Run the query"),
      el("span", { class: "small muted" }, "Read-only: a structured query never changes anything.")));
  } else if (AK.input === "watch") {
    box.append(akWatchPanel());
  }
}

function akTurns() {
  if (!AK.turns.length) return el("p", { class: "small muted" }, "Start with a subject, then ask follow-ups with \"it\", \"he\", \"she\", \"they\" — QueryBook remembers what you were talking about.");
  return el("div", { class: "turns" }, el("div", { class: "small muted" }, "This conversation (newer questions count more):"),
    AK.turns.slice(-6).map((t, i, a) => el("div", { class: "turn" }, el("span", { class: "chip" }, "weight " + Math.pow(0.6, a.length - i).toFixed(2)), " ", t.question)),
    el("button", { class: "btn ghost", type: "button", onclick: () => { AK.turns = []; akPanel(); } }, "Start a new conversation"));
}

/* ------------------------------------------------------------------ speak */
function akSpeak() {
  const R = window.SpeechRecognition || window.webkitSpeechRecognition;
  const state = el("span", { class: "small muted" }, R ? "Hold the button and speak; let go to ask." : "This browser has no speech recognition. Use Chrome or Edge, or type instead.");
  const heard = el("div", { class: "short", style: "min-height:1.4em" });
  if (!R) return el("div", {}, state);
  let rec = null, text = "";
  const start = () => {
    if (rec) return;
    rec = new R(); rec.lang = navigator.language || "en-US"; rec.interimResults = true; rec.continuous = true; text = "";
    rec.onresult = e => { text = Array.from(e.results).map(r => r[0].transcript).join(" "); heard.textContent = text; };
    rec.onerror = e => { state.textContent = e.error === "not-allowed" ? "The microphone was not allowed. Allow it in the browser's address bar." : "Speech recognition: " + e.error; };
    rec.onend = () => { rec = null; btn.classList.remove("rec"); if (text.trim()) { state.textContent = "Asking…"; akAsk(text.trim()); } else state.textContent = "Nothing was heard. Hold the button and speak."; };
    rec.start(); btn.classList.add("rec"); state.textContent = "Listening…";
  };
  const stop = () => { if (rec) rec.stop(); };
  const btn = el("button", { class: "btn mic", type: "button", onpointerdown: start, onpointerup: stop, onpointerleave: stop,
    onkeydown: e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); start(); } }, onkeyup: e => { if (e.key === " " || e.key === "Enter") stop(); } }, "🎤 Hold to speak");
  return el("div", {}, el("div", { class: "akline" }, btn, state), heard,
    el("p", { class: "small muted" }, "The microphone is on only while you hold the button. Answers can be spoken back: choose \"Answer as: Spoken\"."));
}

/* ------------------------------------------------------------------ the object detector (bundled, offline) */
async function akDetector(mode) {
  if (AK.det && AK.det.mode === mode) return AK.det.d;
  if (AK.det) { try { await AK.det.d.setOptions({ runningMode: mode }); AK.det.mode = mode; return AK.det.d; } catch (e) { /* recreate below */ } }
  if (!AK.detLoading) AK.detLoading = (async () => {
    const vision = await import("/vendor/mediapipe/vision_bundle.mjs");
    const files = await vision.FilesetResolver.forVisionTasks("/vendor/mediapipe/wasm");
    const opts = d => ({ baseOptions: { modelAssetPath: "/vendor/mediapipe/efficientdet_lite0.tflite", delegate: d }, scoreThreshold: 0.35, maxResults: 10, runningMode: mode });
    let d;
    try { d = await vision.ObjectDetector.createFromOptions(files, opts("GPU")); } catch (e) { d = await vision.ObjectDetector.createFromOptions(files, opts("CPU")); }
    AK.det = { d, mode };
    return d;
  })();
  try { return await AK.detLoading; } finally { AK.detLoading = null; }
}
const akBoxes = r => (r.detections || []).map(d => ({ label: (d.categories[0] || {}).categoryName || "?", score: (d.categories[0] || {}).score || 0, box: d.boundingBox }));

function akSeenChips(rows, where) {
  if (!rows.length) return el("p", { class: "small muted" }, "Nothing recognised yet.");
  return el("div", { class: "chips" }, el("span", { class: "small muted" }, "Ask about: "),
    rows.map(r => el("button", { class: "chip btnchip", type: "button", title: `seen ${r.count}× · best ${Math.round(r.best * 100)}%`, onclick: () => akAsk(r.label, { from: where }) },
      `${r.label}${r.count > 1 ? " ×" + r.count : ""}`)));
}

/* ------------------------------------------------------------------ live camera */
function akCameraPanel() {
  const video = el("video", { playsinline: true, muted: true, class: "akmedia" });
  const canvas = el("canvas", { class: "akoverlay" });
  const state = el("span", { class: "small muted" }, "The camera is used only on this computer, only while it is on.");
  const chips = el("div", {});
  const q = el("input", { class: "akinput", placeholder: "Ask about what the camera saw — \"is there a cup?\", \"what did you see?\"", "aria-label": "Question about the camera" });
  const ans = el("div", { class: "short small" });
  const askSeen = async () => { const j = await akPost("/api/shell/seen", { detections: AK.camDets, q: q.value }); ans.textContent = j.answer; };
  q.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); askSeen(); } });
  const toggle = el("button", { class: "btn", type: "button" }, "Turn the camera on");
  toggle.onclick = async () => {
    if (AK.camOn) { akStopCamera(); toggle.textContent = "Turn the camera on"; return; }
    try {
      state.textContent = "Starting the camera and the object finder…";
      AK.cam = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      video.srcObject = AK.cam; await video.play();
      const det = await akDetector("VIDEO");
      AK.camOn = true; AK.camDets = []; AK.camT0 = performance.now(); toggle.textContent = "Turn the camera off";
      state.textContent = "Watching. Click a name below to ask about it.";
      let lastSummary = 0;
      const loop = async () => {
        if (!AK.camOn) return;
        if (video.readyState >= 2) {
          const t = (performance.now() - AK.camT0) / 1000;
          const boxes = akBoxes(det.detectForVideo(video, performance.now()));
          for (const b of boxes) AK.camDets.push({ label: b.label, score: b.score, t });
          if (AK.camDets.length > 20000) AK.camDets.splice(0, 5000);
          akDraw(canvas, video, boxes);
          if (t - lastSummary > 1.5) {
            lastSummary = t;
            const recent = AK.camDets.filter(d => t - d.t < 30);
            akPost("/api/shell/seen", { detections: recent }).then(j => chips.replaceChildren(akSeenChips(j.seen, "camera"))).catch(() => {});
          }
        }
        setTimeout(() => requestAnimationFrame(loop), 120);
      };
      loop();
    } catch (e) {
      akStopCamera(); state.textContent = e.name === "NotAllowedError" ? "The camera was not allowed. Allow it in the browser's address bar." : "The camera could not start: " + e.message;
    }
  };
  return el("div", {}, el("div", { class: "akline" }, toggle, state), el("div", { class: "akstage" }, video, canvas), chips,
    el("div", { class: "akline" }, q, el("button", { class: "btn ghost", type: "button", onclick: askSeen }, "Ask")), ans,
    el("p", { class: "small muted" }, "QueryBook recognises 80 everyday kinds of things (people, animals, vehicles, furniture, food, tools). People are only counted, never identified."));
}
function akStopCamera() {
  AK.camOn = false;
  if (AK.cam) { for (const t of AK.cam.getTracks()) t.stop(); AK.cam = null; }
}
function akDraw(canvas, media, boxes) {
  const w = media.videoWidth || media.naturalWidth, h = media.videoHeight || media.naturalHeight;
  if (!w) return;
  canvas.width = w; canvas.height = h;
  const g = canvas.getContext("2d");
  g.clearRect(0, 0, w, h); g.lineWidth = Math.max(2, w / 300); g.font = `${Math.max(14, w / 40)}px system-ui, sans-serif`;
  for (const b of boxes) {
    const bb = b.box; g.strokeStyle = "#2f8fff"; g.strokeRect(bb.originX, bb.originY, bb.width, bb.height);
    const label = `${b.label} ${Math.round(b.score * 100)}%`, tw = g.measureText(label).width + 10, th = Math.max(18, w / 34);
    g.fillStyle = "#2f8fff"; g.fillRect(bb.originX, Math.max(0, bb.originY - th), tw, th);
    g.fillStyle = "#fff"; g.fillText(label, bb.originX + 5, Math.max(th - 5, bb.originY - 5));
  }
}

/* ------------------------------------------------------------------ video file */
function akVideoPanel() {
  const video = el("video", { controls: true, playsinline: true, muted: true, class: "akmedia" });
  const canvas = el("canvas", { class: "akoverlay" });
  const state = el("span", { class: "small muted" }, "The video stays on this computer.");
  const table = el("div", {});
  const q = el("input", { class: "akinput", placeholder: "Ask about the video — \"when does the dog appear?\", \"what is in it?\"", "aria-label": "Question about the video" });
  const ans = el("div", { class: "short small" });
  const askSeen = async () => { const j = await akPost("/api/shell/seen", { detections: AK.vidDets, q: q.value }); ans.textContent = j.answer; };
  q.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); askSeen(); } });
  const file = el("input", { type: "file", accept: "video/*", "aria-label": "Video file" });
  file.onchange = async () => {
    const f = file.files[0]; if (!f) return;
    video.src = URL.createObjectURL(f); AK.vidDets = []; table.replaceChildren();
    await new Promise(r => video.addEventListener("loadeddata", r, { once: true }));
    state.textContent = "Loading the object finder…";
    const det = await akDetector("VIDEO");
    const dur = video.duration || 0, step = dur > 600 ? 3 : dur > 120 ? 2 : 1;
    let ts = 0;
    for (let t = 0; t <= dur; t += step) {
      video.currentTime = t;
      await new Promise(r => video.addEventListener("seeked", r, { once: true }));
      ts += 1000;                                           // detectForVideo needs increasing timestamps
      const boxes = akBoxes(det.detectForVideo(video, ts));
      for (const b of boxes) AK.vidDets.push({ label: b.label, score: b.score, t });
      akDraw(canvas, video, boxes);
      state.textContent = `Looking through the video… ${Math.min(100, Math.round(100 * t / Math.max(1, dur)))}%`;
    }
    video.currentTime = 0;
    const j = await akPost("/api/shell/seen", { detections: AK.vidDets });
    state.textContent = `Done: ${j.seen.length} kind${j.seen.length === 1 ? "" : "s"} of thing found (checked every ${step} s).`;
    table.replaceChildren(akSeenChips(j.seen, "video"), j.seen.length ? el("div", { class: "tbl" }, el("table", {},
      el("tr", {}, el("th", {}, "What"), el("th", {}, "First seen"), el("th", {}, "Last seen"), el("th", {}, "Times"), el("th", {}, "")),
      j.seen.map(r => el("tr", {}, el("td", {}, r.label), el("td", {}, akClock(r.first)), el("td", {}, akClock(r.last)), el("td", {}, String(r.count)),
        el("td", {}, el("button", { class: "btn ghost small", type: "button", onclick: () => { video.currentTime = r.first; video.play(); } }, "▶ Jump"))))))
      : null);
  };
  return el("div", {}, el("div", { class: "akline" }, file, state), el("div", { class: "akstage" }, video, canvas), table,
    el("div", { class: "akline" }, q, el("button", { class: "btn ghost", type: "button", onclick: askSeen }, "Ask")), ans);
}
const akClock = t => { const s = Math.max(0, Math.floor(t)); return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

/* ------------------------------------------------------------------ photo */
function akPhotoPanel() {
  const img = el("img", { class: "akmedia", alt: "" });
  const canvas = el("canvas", { class: "akoverlay" });
  const state = el("span", { class: "small muted" }, "The picture stays on this computer.");
  const chips = el("div", {});
  const file = el("input", { type: "file", accept: "image/*", "aria-label": "Photo" });
  file.onchange = async () => {
    const f = file.files[0]; if (!f) return;
    img.src = URL.createObjectURL(f);
    await img.decode();
    state.textContent = "Looking…";
    const det = await akDetector("IMAGE");
    const boxes = akBoxes(det.detect(img));
    akDraw(canvas, img, boxes);
    AK.photoDets = boxes.map(b => ({ label: b.label, score: b.score, t: 0 }));
    const j = await akPost("/api/shell/seen", { detections: AK.photoDets });
    state.textContent = boxes.length ? `${boxes.length} thing${boxes.length === 1 ? "" : "s"} recognised.` : "Nothing recognised in this picture.";
    chips.replaceChildren(akSeenChips(j.seen, "photo"));
  };
  return el("div", {}, el("div", { class: "akline" }, file, state), el("div", { class: "akstage" }, img, canvas), chips);
}

/* ------------------------------------------------------------------ watched questions */
function akWatchPanel() {
  const list = el("div", {});
  const draw = rows => list.replaceChildren(rows.length ? el("div", { class: "tbl" }, el("table", {},
    el("tr", {}, el("th", {}, "Question"), el("th", {}, "Answer now"), el("th", {}, "Checked"), el("th", {}, "Changed"), el("th", {}, "")),
    rows.map(w => el("tr", {}, el("td", {}, el("a", { href: "#", onclick: e => { e.preventDefault(); akAsk(w.q); } }, w.q)),
      el("td", {}, w.now || el("span", { class: "muted" }, "nothing held yet"), w.was != null && w.last_change ? el("div", { class: "small muted" }, "was: " + (w.was || "nothing")) : null),
      el("td", {}, `${w.checks}×`, w.last ? el("div", { class: "small muted" }, new Date(w.last * 1000).toLocaleString()) : null),
      el("td", {}, w.changes ? el("span", { class: "chip disputed" }, `${w.changes}×`) : "no", w.last_change ? el("div", { class: "small muted" }, new Date(w.last_change * 1000).toLocaleString()) : null),
      el("td", {}, el("button", { class: "btn ghost small", type: "button", onclick: async () => draw((await akPost("/api/shell/watch", { action: "remove", q: w.q })).watches) }, "Stop watching"))))))
    : el("p", { class: "small muted" }, "No questions are watched yet."));
  const i = el("input", { class: "akinput", placeholder: "A question to watch — e.g. population of Tokyo", "aria-label": "Question to watch" });
  const add = async () => { try { draw((await akPost("/api/shell/watch", { action: "add", q: i.value })).watches); i.value = ""; } catch (e) { alert(e.message); } };
  i.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  fetch("/api/shell/watch").then(r => r.json()).then(j => draw(j.watches || [])).catch(() => {});
  return el("div", {}, el("div", { class: "akline" }, i, el("button", { class: "btn", type: "button", onclick: add }, "Watch")),
    el("p", { class: "small muted" }, "QueryBook asks each watched question again every hour while its window is open (and whenever you press Ask again now), and marks the ones whose answer changed."),
    el("button", { class: "btn ghost", type: "button", onclick: async () => { list.prepend(el("p", { class: "small muted" }, "Asking again…")); draw((await akPost("/api/shell/watch", { action: "run" })).watches); } }, "Ask all again now"),
    list);
}

/* ------------------------------------------------------------------ asking */
async function ask(q) {                                       // the header's Ask box
  if (current === "bookquery") { if (BQ.book) return bqAsk(q); return; }   // Book Query: ask the open book
  if (current !== "ask") show("ask");
  if (["camera", "video", "photo", "check", "watch", "structured"].includes(AK.input)) { AK.input = "type"; save("qb:ask:input", "type"); akControls(); akPanel(); }
  return akAsk(q);
}

async function akAsk(q, extra) {
  q = (q || "").trim(); if (!q) return;
  document.getElementById("askinput").value = q;
  if (current !== "ask") show("ask");
  AK.busy = true; AK.last = { question: q, loading: true }; akRedraw();
  try {
    const body = Object.assign({ q, mode: AK.mode, format: AK.format, register: AK.register, seed: AK.seed, turns: AK.mode === "guided" ? AK.turns : [] }, extra || {});
    AK.last = await akPost("/api/shell/ask", body);
    if (AK.mode === "guided") {
      AK.turns.push({ question: AK.last.question, subject: (AK.last.understood || {}).subject || "" });
      akPanel();
    }
  } catch (e) { AK.last = { question: q, error: e.message }; }
  AK.busy = false; akRedraw();
}

async function akCheck(text) {
  if (!text.trim()) return;
  AK.last = { question: "Checking the pasted text", loading: true }; akRedraw();
  try { AK.last = Object.assign({ checked: true }, await akPost("/api/shell/check", { text })); }
  catch (e) { AK.last = { error: e.message }; }
  akRedraw();
}

/* ------------------------------------------------------------------ drawing the answer */
function akRedraw() {
  if (!AK.root) return;
  const out = AK.root.querySelector("#ak-out");
  out.replaceChildren(...akAnswer(AK.last));
}

function akAnswer(r) {
  if (!r) return [];
  if (r.loading) return [el("div", { class: "card" }, el("p", { class: "muted" }, r.loadingText || `Asking every part of QueryBook about “${r.question}”…`))];
  if (r.error) return [el("div", { class: "card" }, el("p", { class: "note" }, r.error))];
  if (r.checked) return [akChecked(r)];
  if (r.bookAnswer) return akBookAnswer(r);
  const cards = [];
  const fmt = AK.format === "auto" ? r.format : AK.format;     // a changed format redraws without asking again where it can
  const v = r.view || {};
  const top = el("div", { class: "card" },
    el("div", { class: "small muted" }, r.question, r.guided && r.guided.resolved ? `  (about ${r.guided.resolved})` : ""),
    r.clarify ? el("p", { class: "note" }, r.clarify) : null,
    el("div", { class: "short" }, akSaid(r) || (r.sections.length ? "Here is what QueryBook holds about this:" : "QueryBook holds nothing on this yet.")),
    el("div", { class: "small muted", style: "margin-top:6px" },
      `Topic: ${r.topic} · shown as ${akFormatName(fmt)}${r.register !== "plain" ? " · tone: " + r.register : ""} · asked: ${(r.asked || []).map(nameOf).join(", ") || "nothing"}` +
      ((r.unavailable || []).length ? ` · not answering: ${r.unavailable.map(u => nameOf(u.source)).join(", ")}` : "")),
    (fmt === "spoken" || r.format === "spoken") && (r.short || "") ? akSpeakBtn(akSaid(r)) : el("div", { class: "akline" }, (r.short ? akSpeakBtn(akSaid(r), true) : null),
      r.question && !["watch"].includes(AK.input) ? el("button", { class: "btn ghost small", type: "button", onclick: async () => { try { await akPost("/api/shell/watch", { action: "add", q: r.question }); alert("Watching: " + r.question); } catch (e) { alert(e.message); } } }, "Watch this question") : null));
  cards.push(top);
  // the mode first
  if (v.verdict) cards.push(akVerdictCard(v.verdict));
  if (v.discussion) cards.push(akDiscussion(v.discussion));
  if (v.connections) cards.push(akConnections(v.connections));
  if (v.quiz) cards.push(akQuiz(v.quiz));
  if (AK.mode === "tutorial" && v.steps) cards.push(akSteps(v.steps, "Tutorial"));
  if (AK.mode === "flashcards" && v.cards) cards.push(akCards(v.cards));
  if (r.guided && r.guided.earlier && r.guided.earlier.length) cards.push(el("div", { class: "card small" }, el("b", {}, "Shaped by earlier questions: "),
    r.guided.earlier.map(t => `${t.question} (weight ${t.weight})`).join(" · ")));
  // then the answer in its format
  if (fmt === "timeline") cards.push(akTimeline(v.timeline || akLocalTimeline(r)));
  else if (fmt === "profile") cards.push(akProfile(v.profile || [], v.map), v.timeline && v.timeline.length ? akTimeline(v.timeline) : null);
  else if (fmt === "steps" && AK.mode !== "tutorial") cards.push(akSteps(v.steps || [], "Step by step"));
  else if (fmt === "cards" && AK.mode !== "flashcards") cards.push(akCards(v.cards || []));
  if (fmt !== "short" && fmt !== "spoken") for (const s of r.sections) cards.push(akSection(s, fmt));
  return cards.filter(Boolean);
}
function akSaid(r) {
  if (AK.register === r.register || !r.short) return r.said || r.short;
  const lead = { plain: "", formal: "According to the sources held, ", academic: "The recorded evidence indicates the following: ", child: "Here is the answer, simply: " }[AK.register] || "";
  return lead + (AK.register === "child" ? r.short.replace(/\s*\([^)]*\)/g, "") : r.short);
}
function akFormatName(id) { const f = ((AK.cat || {}).formats || []).find(x => x.id === id); return f ? f.name.toLowerCase() : id === "profile" ? "a profile" : id; }
function akLocalTimeline(r) {
  const rows = [];
  for (const s of r.sections) if (s.kind === "facts") for (const f of s.items) {
    const m = String(f.date || "").match(/-?\d{3,4}/) || (/date|year|time|inception|born|death|founded/i.test(f.predicate || "") ? String(f.object || "").match(/-?\d{3,4}/) : null);
    if (m) rows.push({ year: +m[0], text: `${(f.subject || "").replace(/\s*\(Q\d+\)/, "")} — ${f.predicate}: ${String(f.object || f.statement || "").replace(/\s*\(Q\d+\)/g, "")}`, where: f.where });
  }
  return rows.sort((a, b) => a.year - b.year);
}

function akSpeakBtn(text, small) {
  const b = el("button", { class: "btn" + (small ? " ghost small" : ""), type: "button" }, small ? "🔊 Hear it" : "🔊 Hear the answer");
  b.onclick = async () => {
    b.disabled = true;
    try { const j = await akPost("/api/shell/say", { text: text.slice(0, 300) }); new Audio(j.audio).play(); }
    catch (e) {
      if ("speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance(text));
      else alert(e.message);
    }
    b.disabled = false;
  };
  if (!small) setTimeout(() => b.click(), 50);
  return el("div", { class: "akline" }, b);
}

function akSection(s, fmt) {
  if (s.kind === "facts") {
    const rows = fmt === "table" || fmt === "full" || fmt === "auto" ? s.items : s.items.slice(0, 12);
    return el("div", { class: "card" }, el("h2", {}, `Facts (${s.items.length})`),
      el("div", { class: "tbl" }, el("table", {}, el("tr", {}, el("th", {}, "Subject"), el("th", {}, "What"), el("th", {}, "Value"), el("th", {}, "Where it came from")),
        rows.map(f => el("tr", {}, el("td", {}, akName(f.subject)), el("td", {}, f.predicate || ""),
          el("td", {}, akLink(f.object || f.statement || ""), f.date ? el("div", { class: "small muted" }, f.date) : null),
          el("td", {}, f.link ? el("a", { href: f.link, target: "_blank", rel: "noopener" }, f.where || "source") : (f.where || ""),
            f.status ? el("div", {}, el("span", { class: "chip " + f.status }, f.status)) : null,
            f.provenance ? el("div", { class: "small muted" }, f.provenance) : null))))));
  }
  if (s.kind === "word") {
    return el("div", { class: "card" }, el("h2", {}, "Meaning"), s.items.map(it =>
      it.translations ? el("div", { class: "small", style: "margin-top:8px" }, el("b", {}, "Translations: "),
        Object.entries(it.translations).map(([l, w]) => `${l}: ${[].concat(w).slice(0, 3).join(", ")}`).join(" · "))
      : el("div", {}, it.word ? el("div", { class: "short" }, it.word, it.pos ? el("span", { class: "small muted" }, "  " + it.pos) : null) : null,
          el("p", { style: "white-space:pre-wrap;margin:6px 0" }, it.text), it.source ? el("div", { class: "small muted" }, it.source) : null)),
      el("button", { class: "btn ghost", type: "button", style: "margin-top:10px", onclick: () => show("language") }, "Practise it in the Language Lab"));
  }
  if (s.kind === "math") {
    return el("div", { class: "card" }, el("h2", {}, "Calculation"), s.items.map(it => el("div", {}, el("div", { class: "short" }, it.text),
      el("div", { class: "small muted" }, (it.exact ? "Exact · " : "") + (it.how || "")))),
      el("button", { class: "btn ghost", type: "button", style: "margin-top:10px", onclick: () => show("stem") }, "Open in STEM"));
  }
  return null;
}
const akName = s => String(s || "").replace(/\s*\(Q\d+\)$/, "");
function akLink(v) {                                          // a value that names something can be asked about next
  const s = String(v || ""), m = s.match(/^(.*?)\s*\(Q\d+\)$/);
  return m ? el("a", { href: "#", onclick: e => { e.preventDefault(); akAsk(m[1]); } }, m[1]) : s.replace(/\s*\(Q\d+\)/g, "");
}

function akTimeline(rows) {
  return el("div", { class: "card" }, el("h2", {}, "Timeline"), rows.length ? el("ol", { class: "timeline" },
    rows.map(r => el("li", {}, el("span", { class: "yr" }, r.year < 0 ? `${-r.year} BC` : String(r.year)), el("span", {}, r.text, el("div", { class: "small muted" }, r.where || "")))))
    : el("p", { class: "small muted" }, "None of these facts has a date, so there is no timeline. Try \"Full, with sources\"."));
}
function akProfile(rows, map) {
  return el("div", { class: "card" }, el("h2", {}, "At a glance"), el("dl", { class: "profile" },
    rows.slice(0, 16).map(r => [el("dt", {}, r.label), el("dd", {}, r.value, el("span", { class: "small muted" }, "  " + (r.where || "")))])),
    map ? el("a", { href: map, target: "_blank", rel: "noopener", class: "btn ghost small" }, "🗺 Show on a map (OpenStreetMap)") : null);
}
function akSteps(steps, title) {
  if (!steps.length) return el("div", { class: "card" }, el("h2", {}, title), el("p", { class: "small muted" }, "There are not enough facts to make steps from."));
  let at = 0;
  const box = el("div", {});
  const draw = () => box.replaceChildren(el("ol", { class: "steps" }, steps.map((s, i) => el("li", { class: i < at ? "done" : i === at ? "now" : "later" },
    el("div", { class: "small muted" }, `Step ${s.n} · ${s.title} · level ${s.level}`), i <= at ? el("div", {}, s.text, el("div", { class: "small muted" }, s.where || "")) : el("div", { class: "muted" }, "…")))),
    el("div", { class: "akline" }, el("button", { class: "btn", type: "button", disabled: at >= steps.length - 1, onclick: () => { at++; draw(); } }, at >= steps.length - 1 ? "All steps done" : "Next step"),
      el("span", { class: "small muted" }, `${at + 1} of ${steps.length}`),
      AK.mode === "tutorial" ? el("button", { class: "btn ghost", type: "button", onclick: () => { AK.mode = "quiz"; save("qb:ask:mode", "quiz"); akControls(); akAsk(AK.last.question); } }, "Test me on it") : null));
  draw();
  return el("div", { class: "card" }, el("h2", {}, title), box);
}
function akCards(cards) {
  if (!cards.length) return el("div", { class: "card" }, el("h2", {}, "Cards"), el("p", { class: "small muted" }, "There are not enough facts to make cards from."));
  return el("div", { class: "card" }, el("h2", {}, `Cards (${cards.length}) — click a card to flip it`), el("div", { class: "fcards" },
    cards.map(c => { const d = el("button", { class: "fcard", type: "button" }, el("div", { class: "front" }, c.front), el("div", { class: "back" }, c.back, el("div", { class: "small muted" }, c.where || "")));
      d.onclick = () => d.classList.toggle("flipped"); return d; })));
}
function akQuiz(items) {
  if (!items.length) return el("div", { class: "card" }, el("h2", {}, "Quiz"), el("p", { class: "small muted" }, "There are not enough facts to make questions from."));
  let right = 0, done = 0;
  const score = el("span", { class: "small muted" }, `0 of ${items.length} answered`);
  return el("div", { class: "card" }, el("h2", {}, "Quiz"), items.map(it => {
    const res = el("div", { class: "small" });
    const typed = el("input", { class: "akinput", placeholder: "Type your answer, or pick one below", "aria-label": it.question });
    const answer = async given => {
      if (res.dataset.done) return;
      const g = await akPost("/api/shell/grade", { given, expected: it.answer });
      res.dataset.done = "1"; done++; if (g.verdict === "right") right++;
      res.replaceChildren(el("span", { class: "chip " + (g.verdict === "right" ? "verified" : g.verdict === "nearly" ? "" : "disputed") },
        { right: "Right", nearly: "Nearly", wrong: "Not quite", blank: "No answer" }[g.verdict]), ` The answer: ${it.answer} — ${it.where || ""}`);
      score.textContent = `${right} right of ${done} answered (${items.length} questions)`;
    };
    typed.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); answer(typed.value); } });
    return el("div", { class: "qitem" }, el("b", {}, `${it.n}. ${it.question}`), el("div", { class: "akline" }, typed, el("button", { class: "btn ghost small", type: "button", onclick: () => answer(typed.value) }, "Check")),
      el("div", { class: "chips" }, it.choices.map(c => el("button", { class: "chip btnchip", type: "button", onclick: () => answer(c) }, c))), res);
  }), el("div", { class: "akline" }, score, el("button", { class: "btn ghost", type: "button", onclick: () => { AK.seed++; akAsk(AK.last.question); } }, "New questions")));
}
function akDiscussion(d) {
  return el("div", { class: "card" }, el("h2", {}, "Discussion — what each source says"),
    d.viewpoints.length ? d.viewpoints.map(v => el("div", { class: "qitem" },
      el("b", {}, v.source), " ", el("span", { class: "chip " + (v.adopted ? "verified" : "disputed") }, `grounded ${Math.round(v.groundedness * 100)}%`),
      el("span", { class: "small muted" }, ` · ${v.facts} fact${v.facts === 1 ? "" : "s"}${v.adopted ? "" : " · not grounded enough to rely on"}`),
      el("ul", { class: "small" }, v.says.map(s => el("li", {}, s.replace(/\s*\(Q\d+\)/g, "")))))) : el("p", { class: "small muted" }, "No source holds anything on this, so there is nothing to discuss — QueryBook does not make up a view."),
    d.agree.length ? el("div", {}, el("h3", {}, "Where sources agree"), el("ul", { class: "small" }, d.agree.map(a => el("li", {}, `${a.about}: ${a.value} — ${a.sources.join(", ")}`)))) : null,
    d.differ.length ? el("div", {}, el("h3", {}, "Where they differ"), el("ul", { class: "small" }, d.differ.map(x => el("li", {}, `${x.about}: `,
      x.values.map(vv => `${vv.value} (${vv.sources.join(", ")})`).join("  vs  "))))) : null);
}
function akConnections(rows) {
  return el("div", { class: "card" }, el("h2", {}, "Connected to"), rows.length ? el("div", { class: "conns" }, rows.map(c =>
    el("button", { class: "conn", type: "button", onclick: () => akAsk(c.name), title: c.how.join(", ") },
      el("b", {}, c.name), el("span", { class: "sbar" }, el("span", { style: `width:${Math.round(c.strength * 100)}%` })), el("span", { class: "small muted" }, c.how.slice(0, 3).join(", ")))))
    : el("p", { class: "small muted" }, "No connected names among these facts."));
}
function akVerdictCard(v) {
  return el("div", { class: "card" }, el("h2", {}, "Is it true?"),
    el("div", { class: "short" }, el("span", { class: "chip big " + (VERDICT_CLASS[v.verdict] || "") }, { VERIFIED: "Supported", CONTRADICTED: "Contradicted", UNKNOWN: "Not known" }[v.verdict])),
    el("p", {}, v.claim), v.facts.length ? el("ul", { class: "small" }, v.facts.map(f => el("li", {}, f.text, el("span", { class: "muted" }, " — " + f.where))))
      : el("p", { class: "small muted" }, "QueryBook holds no fact that settles this. It does not guess."));
}
function akChecked(r) {
  return el("div", { class: "card" }, el("h2", {}, "Every claim, checked"),
    el("div", { class: "small" }, `Supported ${r.tally.VERIFIED} · contradicted ${r.tally.CONTRADICTED} · not known ${r.tally.UNKNOWN}`),
    r.claims.length ? r.claims.map(c => el("div", { class: "qitem" }, el("span", { class: "chip " + (VERDICT_CLASS[c.verdict] || "") }, { VERIFIED: "Supported", CONTRADICTED: "Contradicted", UNKNOWN: "Not known" }[c.verdict]),
      " ", c.claim, c.facts.length ? el("ul", { class: "small" }, c.facts.map(f => el("li", {}, f.text, el("span", { class: "muted" }, " — " + f.where)))) : null))
      : el("p", { class: "small muted" }, "No sentence in the text states something that can be checked."));
}

/* ------------------------------------------------------------------ Book Query: the sample-ebook library */
const STATUS_CLASS = { Confirmed: "verified", "Historically significant": "verified", Refined: "refined", Superseded: "disputed", Incorrect: "disputed", "Historical context": "context" };
function akLibraryPanel() {
  const box = el("div", { id: "ak-library" });
  const draw = () => {
    const books = AK.library || [];
    const cur = books.find(b => b.id === AK.book);
    box.replaceChildren(
      el("div", { class: "small muted" }, "Choose a book. QueryBook answers only from that book, quoting it with its chapter and paragraph, and shows where it now differs from what is known today."),
      el("details", { class: "libwrap", open: !cur }, el("summary", {}, cur ? `📚 ${cur.title} — change book (${books.length} in the library)` : `📚 The library — ${books.length} books`),
      el("div", { class: "libgrid" }, ["nonfiction", "fiction"].map(kind => [
        el("div", { class: "libband" }, kind === "nonfiction" ? "Nonfiction" : "Fiction"),
        books.filter(b => b.kind === kind).map(b => el("button", { type: "button", class: "libcard", "aria-pressed": String(b.id === AK.book), onclick: () => { AK.book = b.id; save("qb:ask:book", b.id); AK.last = null; draw(); akRedraw(); } },
          el("b", {}, b.title), el("span", { class: "small" }, `${b.author} · ${b.year < 0 ? -b.year + " BC" : b.year}`),
          el("span", { class: "small muted" }, b.subject),
          el("span", { class: "libtags" }, el("span", { class: "chip" }, `${b.units.toLocaleString()} Fact Units`),
            Object.keys(b.modern || {}).length ? el("span", { class: "chip verified" }, b.kind === "fiction" ? "historical context" : "modern layer") : null,
            b.people ? el("span", { class: "chip" }, `${b.people} people`) : null,
            b.harvested ? el("span", { class: "chip context" }, "harvested") : null)))]).flat(2))),
      cur ? akBookDetail(cur) : el("p", { class: "small muted" }, "No book chosen yet."));
  };
  if (AK.library) draw();
  else fetch("/api/shell/library").then(r => r.json()).then(j => { AK.library = j.books || []; if (!AK.library.some(b => b.id === AK.book)) AK.book = ""; draw(); })
    .catch(() => box.replaceChildren(el("p", { class: "note" }, "The library could not be loaded.")));
  box.append(el("p", { class: "small muted" }, "Loading the library…"));
  return box;
}

function akBookDetail(b) {
  const i = el("input", { type: "search", class: "akinput", placeholder: `Ask ${b.title}…`, "aria-label": "Question about the book" });
  const go = () => akBookAsk(i.value);
  i.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  const pv = b.provenance || {};
  return el("div", { class: "bookdetail" },
    el("h3", {}, b.title, el("span", { class: "small muted" }, `  ${b.author} · ${b.published || b.year}`)),
    b.about ? el("p", { class: "small" }, b.about) : null,
    el("p", { class: "small muted" }, `Structure: ${b.structure || ""}. ${b.units.toLocaleString()} Fact Units — ` +
      Object.entries(b.kinds || {}).sort((x, y) => y[1] - x[1]).map(([k, n]) => `${n.toLocaleString()} ${k}`).join(", ") + "."),
    el("div", { class: "akline" }, i, el("button", { class: "btn", type: "button", onclick: go }, "Book Query")),
    el("div", { class: "chips" }, el("span", { class: "small muted" }, "Try: "), (b.examples || []).map(q => el("button", { class: "chip btnchip", type: "button", onclick: () => { i.value = q; akBookAsk(q); } }, q))),
    el("p", { class: "small muted" }, "Source: ", pv.url ? el("a", { href: pv.url, target: "_blank", rel: "noopener" }, pv.source || pv.url) : (pv.source || ""),
      pv.fetched ? ` (fetched ${pv.fetched}). ` : ". ", pv.rights || ""));
}

async function akBookAsk(q) {
  q = (q || "").trim(); if (!q || !AK.book) return;
  document.getElementById("askinput").value = q;
  if (current !== "ask") show("ask");
  const b = (AK.library || []).find(x => x.id === AK.book) || {};
  AK.last = { question: q, loading: true, loadingText: `Reading ${b.title || "the book"}…` }; akRedraw();
  try { AK.last = Object.assign({ bookAnswer: true }, await akPost("/api/shell/book/ask", { book: AK.book, q })); }
  catch (e) { AK.last = { question: q, error: e.message }; }
  akRedraw();
}

function akAnchor(book, unit, anchor) {
  return el("a", { href: "#", class: "anchor", title: "Show this passage in the original text" + (unit ? " · Fact Unit " + unit : ""),
    onclick: e => { e.preventDefault(); akPassage(book, unit); } }, anchor);
}

async function akPassage(book, unit) {
  if (!unit) return;
  let j;
  try { j = await (await fetch(`/api/shell/book/passage?book=${encodeURIComponent(book)}&unit=${encodeURIComponent(unit)}`)).json(); }
  catch (e) { return; }
  const dlg = el("dialog", { class: "passage" },
    el("div", { class: "small muted" }, "Original text — ", j.title || ""),
    el("h3", {}, j.anchor),
    (j.paragraphs || []).map(p => el("div", { class: "ptext" }, el("div", { class: "small muted" }, p.anchor),
      el("p", {}, p.units.map(u => [el("span", { class: u.here ? "here" : "", title: "Fact Unit " + u.id + " · " + u.kind }, u.text), " "])))),
    el("p", { class: "small muted" }, "Fact Unit ", el("code", {}, j.unit), " · ", (j.provenance || {}).source || ""),
    el("button", { class: "btn", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Close"));
  document.body.append(dlg);
  dlg.showModal();
  const h = dlg.querySelector(".here"); if (h) h.scrollIntoView({ block: "center" });
}

function akBookAnswer(r) {
  const cards = [];
  const bk = r.book;
  cards.push(el("div", { class: "card" }, el("div", { class: "small muted" }, `${r.title} · ${r.query}`),
    el("div", { class: "short" }, r.lead || "The book does not say."),
    el("div", { class: "small muted", style: "margin-top:6px" }, "Answered from the book alone" + (r.chapter ? ` (${r.chapter ? "one chapter" : ""})` : "") + ". Every quotation links to its place in the original text.")));
  if ((r.assertions || []).length) {
    cards.push(el("div", { class: "card" }, el("h2", {}, r.intent === "historical" ? "Real history around the story" : "The book beside what is known today"),
      r.assertions.map(a => el("div", { class: "assert" },
        el("div", { class: "arow" }, el("b", {}, a.topic), " ", el("span", { class: "chip " + (STATUS_CLASS[a.status] || "") }, a.status)),
        el("div", { class: "agrid" },
          el("div", {}, el("div", { class: "alabel" }, "Book assertion"), a.book.map(x => el("blockquote", {}, "“" + x.text + "”", el("div", { class: "small" }, akAnchor(bk, x.unit, x.anchor))))),
          el("div", {}, el("div", { class: "alabel" }, a.status === "Historical context" ? "What history records" : "Current verified fact"), el("p", {}, a.modern),
            a.value ? el("div", { class: "small" }, el("b", {}, "Value: "), a.value) : null)),
        a.relationship ? el("div", { class: "small" }, el("span", { class: "alabel" }, "Fact relationship "), a.relationship) : null,
        a.why_then ? el("div", { class: "small" }, el("span", { class: "alabel" }, "Why it was reasonable then "), a.why_then) : null,
        el("div", { class: "small muted" }, el("span", { class: "alabel" }, "Sources "), a.sources.join(" · "))))));
  }
  if ((r.new_since || []).length) cards.push(el("div", { class: "card" }, el("h2", {}, "Discovered since the book was written"),
    el("ol", { class: "timeline" }, r.new_since.map(n => el("li", {}, el("span", { class: "yr" }, String(n.year)), el("span", {}, n.what, el("div", { class: "small muted" }, n.source)))))));
  if ((r.edges || []).length) cards.push(el("div", { class: "card" }, el("h2", {}, `Relationship network — ${(r.people[0] || {}).name || ""}`),
    el("div", { class: "small muted" }, "Counted as paragraphs in which both are named. Click a name to see their network."),
    el("div", { class: "conns" }, r.edges.map(e => el("button", { class: "conn", type: "button", onclick: () => akBookAsk("Show the relationship network around " + e.with) },
      el("b", {}, e.with), el("span", { class: "sbar" }, el("span", { style: `width:${Math.round(100 * e.together / r.edges[0].together)}%` })), el("span", { class: "small muted" }, `${e.together} paragraphs together`))))));
  if ((r.people || []).length && !(r.edges || []).length) cards.push(el("div", { class: "card" }, el("h2", {}, "People"),
    el("div", { class: "tbl" }, el("table", {}, el("tr", {}, el("th", {}, "Name"), el("th", {}, ""), el("th", {}, "Also called"), el("th", {}, "Named"), el("th", {}, "First"), el("th", {}, "Last")),
      r.people.map(p => el("tr", {}, el("td", {}, el("a", { href: "#", onclick: e => { e.preventDefault(); akBookAsk("Show the relationship network around " + p.name); } }, p.name)),
        el("td", {}, el("span", { class: "chip " + (p.historical ? "context" : "") }, p.historical ? "historical" : "fictional"), p.family ? el("div", { class: "small muted" }, p.family + " family") : null),
        el("td", { class: "small" }, (p.aliases || []).slice(0, 4).join(", ")), el("td", {}, String(p.mentions)),
        el("td", { class: "small" }, p.first), el("td", { class: "small" }, p.last)))))));
  if ((r.chapters || []).length) cards.push(el("div", { class: "card" }, el("h2", {}, r.intent === "structure" ? "Parts of the book" : "Through the book, chapter by chapter"),
    el("div", { class: "tbl" }, el("table", {}, el("tr", {}, el("th", {}, "Chapter"), el("th", {}, r.intent === "structure" ? "Paragraphs" : "Times named"), r.intent === "structure" ? null : el("th", {}, "First mention")),
      r.chapters.map(c => el("tr", {}, el("td", {}, c.name), el("td", {}, String(c.mentions)),
        c.first ? el("td", { class: "small" }, "“" + c.first.text.slice(0, 160) + (c.first.text.length > 160 ? "…" : "") + "” ", akAnchor(bk, c.first.unit, "↗")) : null))))));
  if ((r.timeline || []).length) cards.push(el("div", { class: "card" }, el("h2", {}, "Timeline"),
    el("ol", { class: "timeline" }, r.timeline.map(t => el("li", {}, el("span", { class: "yr" }, t.year < 0 ? `${-t.year} BC` : String(t.year)),
      el("span", {}, "“" + t.text + "”", el("div", { class: "small" }, akAnchor(bk, t.unit, t.anchor))))))));
  if ((r.passages || []).length) cards.push(el("div", { class: "card" }, el("h2", {}, r.intent === "evidence" ? "Evidence and deduction, in story order" : r.intent === "values" ? "Measurements in the book" : "From the book"),
    r.passages.map(p => el("div", { class: "qitem" },
      p.reasoning ? el("span", { class: "chip " + (p.reasoning === "deduced" ? "refined" : "verified") }, p.reasoning === "deduced" ? "deduction" : "observed") : null,
      p.checked ? el("span", { class: "chip verified" }, "checked today") : null,
      el("blockquote", {}, "“" + p.text + "”"),
      el("div", { class: "small" }, akAnchor(bk, p.unit, p.anchor), el("span", { class: "muted" }, ` · ${p.kind}` + (p.unit ? ` · ${p.unit}` : "")))))));
  const pv = r.provenance || {};
  cards.push(el("div", { class: "small muted", style: "margin:0 4px 20px" }, "Answer provenance: ", r.title, " — QueryBook edition of ", pv.source || "", ". ", pv.rights || ""));
  return cards;
}
