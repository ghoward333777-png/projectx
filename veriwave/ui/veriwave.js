/* VeriWave window. Chat is the default screen; Answer, Code, Create (text, image, video, audio), QueryBook (every
   QueryBook screen, on demand), the Feature Registry and the Workspace (any screens side by side) are the alternatives.
   Everything the server returns is rendered with textContent, never as HTML. */
"use strict";

const MODES = [
  { id: "chat", name: "Chat" }, { id: "answer", name: "Answer" }, { id: "code", name: "Code" },
  { id: "create", name: "Create", subs: ["text", "image", "video", "audio"] },
  { id: "querybook", name: "QueryBook" }, { id: "features", name: "Feature Registry" }, { id: "workspace", name: "Workspace" },
  { id: "reasoning", name: "Reasoning", admin: true },
  { id: "readiness", name: "Readiness", admin: true },
];
const SUBS = { text: "Text", image: "Image", video: "Video", audio: "Audio" };
const ROLES = ["Reader", "Author", "Instructor", "Admin"];
const state = {
  status: null, role: load("vw:role", "Admin"), engine: load("vw:engine", ""), chat: [], subject: "",
  ws: loadJSON("vw:ws", []), wsLayout: load("vw:wsLayout", "tabs"), wsActive: load("vw:wsActive", ""),
  feat: { q: "", domain: "", area: "", implemented: "", open: 0 },
};

function load(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } }
function loadJSON(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }
function save(k, v) { try { localStorage.setItem(k, typeof v === "string" ? v : JSON.stringify(v)); } catch (e) { /* storage off */ } }
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) n.append(k instanceof Node ? k : String(k));
  return n;
}
function toast(msg) { const t = document.getElementById("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 2600); }
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({ error: "The server's reply could not be read." }));
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}
const iface = id => (state.status?.interfaces || []).find(i => i.id === id);
const visible = i => state.role === "Admin" || !i.admin;
const prog = app => (state.status?.querybook?.programs || []).find(p => p.id === app);

/* ------------------------------------------------------------------ frame */
function route() {
  const h = (location.hash || "#chat").slice(1);
  if (SUBS[h]) return { mode: "create", sub: h };
  if (h.startsWith("reasoning")) return { mode: state.role === "Admin" ? "reasoning" : "chat", sub: load("vw:sub", "text"), trace: h.split(":")[1] || "" };
  const m = MODES.find(x => x.id === h);
  if (m && m.admin && state.role !== "Admin") return { mode: "chat", sub: load("vw:sub", "text") };
  return { mode: m ? m.id : "chat", sub: load("vw:sub", "text") };
}
function drawBar() {
  const r = route();
  document.getElementById("modes").replaceChildren(...MODES.filter(m => !m.admin || state.role === "Admin").map(m =>
    el("a", { href: "#" + (m.subs ? r.sub || "text" : m.id), "aria-current": r.mode === m.id ? "page" : null }, m.name)));
  document.getElementById("roles").replaceChildren(...ROLES.map(x => el("button", { type: "button", "aria-pressed": String(x === state.role),
    onclick: () => { state.role = x; save("vw:role", x); drawBar(); render(); } }, x)));
  const eng = state.status?.engine;
  const b = document.getElementById("engineBadge");
  b.textContent = !state.status ? "…" : eng.claude && state.engine !== "local" ? "Local + Claude" : "Local engine";
  b.className = "badge" + (eng?.claude && state.engine !== "local" ? " on" : "");
  b.title = eng?.claude ? "Claude model: " + eng.model : "Set ANTHROPIC_API_KEY before starting VeriWave to add Claude.";
}
function render() {
  const r = route();
  if (r.mode === "create") save("vw:sub", r.sub);
  drawBar();
  const main = document.getElementById("main");
  main.replaceChildren();
  const views = { chat: chatView, answer: answerView, code: codeView, create: createView, querybook: querybookView, features: featuresView, workspace: workspaceView, reasoning: reasoningView, readiness: readinessView };
  main.append(views[r.mode](r));
  document.body.classList.toggle("in-ws", r.mode === "workspace" && state.ws.some(id => iface(id) && !iface(id).builtin));
  syncPanes(r.mode === "workspace");
}
window.addEventListener("hashchange", render);
document.getElementById("engine").value = state.engine;
document.getElementById("engine").onchange = e => { state.engine = e.target.value; save("vw:engine", state.engine); drawBar(); };

/* ------------------------------------------------------------------ chat */
function chatView() {
  const v = el("div", { class: "view chat" });
  if (!state.chat.length) {
    v.append(el("div", { class: "card" }, el("h2", {}, "Hello — I'm VeriWave."),
      el("p", { class: "muted" }, "Ask me anything and I answer from QueryBook's facts with citations, or tell you I don't know. Ask me to build an application, write, draw, compose or make a short film. Type /answer, /code, /text, /image, /video or /audio to choose yourself."),
      el("div", { class: "tiles" }, ["When was the printing press invented?", "What is 15% of 80?", "Build me a to-do app", "Draw a lighthouse by the sea at sunset",
        "Write a poem about the quiet sea at night", "Compose a calm melody", "Make a 20 second video about a harbour town", "Open the Language Lab", "What can you do?"]
        .map(q => el("button", { class: "tile", type: "button", onclick: () => send(q) }, q)))));
  }
  for (const m of state.chat) v.append(m.role === "user" ? el("div", { class: "msg me" }, m.content) : vwMessage(m));
  const ta = el("textarea", { id: "chatIn", placeholder: "Message VeriWave…", "aria-label": "Message VeriWave", rows: "1",
    onkeydown: e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } } });
  const form = el("form", { onsubmit: e => { e.preventDefault(); const t = ta.value.trim(); if (t) { ta.value = ""; send(t); } } }, ta, el("button", { class: "btn", type: "submit" }, "Send"));
  v.append(el("div", { class: "composer" }, form));
  setTimeout(() => { ta.focus(); window.scrollTo(0, document.body.scrollHeight); }, 0);
  return v;
}
function vwMessage(m) {
  if (m.pending) return el("div", { class: "msg vw" }, el("div", { class: "say thinking" }, "Working on it…"));
  if (m.error) return el("div", { class: "msg vw" }, el("div", { class: "err" }, m.error));
  const r = m.data;
  const box = el("div", { class: "msg vw" }, el("div", { class: "route" }, { answer: "Answer", code: "Code", text: "Text", image: "Image", video: "Video", audio: "Audio", open: "QueryBook", chat: "Chat" }[r.route] || r.route));
  if (r.reply && r.route !== "answer") box.append(el("div", { class: "say" }, r.reply));
  if (r.result) box.append(resultCard(r.route, r.result));
  if (r.trace_id && state.role === "Admin" && r.route !== "answer") box.append(el("a", { class: "small", style: "margin-left:6px", href: "#reasoning:" + r.trace_id }, "Reasoning trace"));
  return box;
}
async function send(text) {
  if (location.hash && location.hash !== "#chat") location.hash = "#chat";
  const history = state.chat.filter(m => !m.pending && !m.error).map(m => ({ role: m.role, content: m.role === "user" ? m.content : (m.data?.reply || "") })).slice(-12);
  state.chat.push({ role: "user", content: text });
  const slot = { role: "assistant", pending: true };
  state.chat.push(slot);
  render();
  try {
    const r = await api("/api/vw/chat", { message: text, history, subject: state.subject, engine: state.engine });
    slot.pending = false; slot.data = r;
    if (r.subject) state.subject = r.subject;
    if (r.route === "open" && r.result?.interface) setTimeout(() => openInterface(r.result.interface), 400);
  } catch (e) { slot.pending = false; slot.error = e.message; }
  render();
}

/* ------------------------------------------------------------------ result cards */
function resultCard(kind, r) {
  if (kind === "answer") return answerCard(r);
  if (kind === "code") return codeCard(r);
  if (kind === "text") return textCard(r);
  if (kind === "image") return imageCard(r);
  if (kind === "video") return videoCard(r);
  if (kind === "audio") return audioCard(r);
  if (kind === "open") return el("div", { class: "card" }, el("button", { class: "btn", type: "button", onclick: () => openInterface(r.interface), disabled: !r.interface }, r.name ? "Open " + r.name : "Show every QueryBook screen"));
  return el("div");
}
function engineNote(r) { return r.engine_note ? el("div", { class: "note" }, r.engine_note) : null; }
function answerCard(r) {
  const c = el("div", { class: "card" },
    el("div", { class: "row" }, el("span", { class: "verdict " + r.verdict }, r.verdict), r.resolved ? el("span", { class: "small muted" }, "Asked as: " + r.resolved) : null,
      el("span", { class: "small muted" }, "engine: " + (r.engine || "local"))),
    el("div", { class: "short" }, r.prose || r.short));
  if (r.prose && r.short && r.short !== r.prose) c.append(el("div", { class: "small muted" }, "Short answer: " + r.short));
  for (const k of r.conflicts || []) c.append(el("div", { class: "conflict" }, el("b", {}, `Sources disagree on ${k.subject} — ${k.predicate}:`),
    el("ul", {}, k.values.map(v => el("li", {}, v.value, v.sources.length ? el("span", { class: "small muted" }, " (" + v.sources.join(", ") + ")") : null)))));
  if ((r.citations || []).length) c.append(el("h3", {}, "Citations"), el("ol", { class: "cites" }, r.citations.map(x => el("li", {},
    el("span", { class: "n" }, "[" + x.n + "]"),
    el("span", {}, x.text, el("div", { class: "small muted" }, x.where, x.link ? el("span", {}, " · ", el("a", { href: x.link, target: "_blank", rel: "noopener" }, "source")) : null,
      x.interface ? el("span", {}, " · ", el("a", { href: "#", onclick: e => { e.preventDefault(); openInterface(x.interface); } }, "open the screen")) : null)),
    el("span", { class: "trust" }, x.trust + "% trust")))));
  const meta = [];
  if (r.withheld) meta.push(r.withheld + " fact(s) held back below " + r.min_trust + "% trust");
  if ((r.asked || []).length) meta.push("asked: " + r.asked.join(", "));
  if ((r.unavailable || []).length) meta.push("not answering: " + r.unavailable.map(u => u.source).join(", "));
  if (meta.length) c.append(el("div", { class: "small muted", style: "margin-top:8px" }, meta.join(" · ")));
  c.append(el("div", { class: "hash", title: "SHA-256 over the question and every citation" }, "provenance " + r.provenance));
  if (r.trace_id && state.role === "Admin") c.append(el("a", { class: "btn ghost small", style: "margin-top:8px", href: "#reasoning:" + r.trace_id }, "Reasoning trace"));
  if (r.engine_note) c.append(engineNote(r));
  return c;
}
function codeCard(r) {
  const files = Object.keys(r.files || {});
  let cur = r.entry;
  const pre = el("pre", { class: "code" });
  const tabs = el("div", { class: "filetabs" });
  const show = f => { cur = f; pre.textContent = r.files[f]; tabs.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.textContent === f))); };
  files.forEach(f => tabs.append(el("button", { type: "button", onclick: () => show(f) }, f)));
  const c = el("div", { class: "card" }, el("div", { class: "row" }, el("h2", { class: "grow", style: "margin:0" }, r.title),
    r.preview_url ? el("a", { class: "btn ghost small", href: r.preview_url, target: "_blank", rel: "noopener" }, "Open in a new tab") : null,
    el("a", { class: "btn small", href: r.zip, download: r.id + ".zip" }, "Download .zip")),
    el("div", { class: "small muted" }, (r.engine === "claude" ? "Written by Claude" : "Local engine: " + r.kind + " application") + " · " + files.length + " files" + (r.notes ? " · " + r.notes : "")),
    engineNote(r));
  if (r.preview_url) c.append(el("h3", {}, "Live preview"), el("iframe", { class: "preview", src: r.preview_url, sandbox: "allow-scripts allow-forms allow-modals allow-downloads", title: r.title + " preview" }));
  c.append(el("h3", {}, "Files"), tabs, pre);
  show(cur);
  return c;
}
function textCard(r) {
  const body = el("div", { class: r.layout === "verse" ? "verse" : "prose" });
  if (r.layout === "prose") for (const p of (r.text || "").split(/\n{2,}/)) body.append(p.startsWith("## ") ? el("h3", {}, p.slice(3)) : el("p", { style: "white-space:pre-wrap" }, p));
  else body.textContent = r.text;
  return el("div", { class: "card" }, el("div", { class: "row" }, el("h2", { class: "grow", style: "margin:0" }, r.title || "Text"),
    el("button", { class: "btn ghost small", type: "button", onclick: () => navigator.clipboard?.writeText(r.text).then(() => toast("Copied")) }, "Copy"),
    r.urls ? el("a", { class: "btn small", href: r.urls["text.md"], download: (r.id || "text") + ".md" }, "Download") : null),
    el("div", { class: "small muted" }, r.form + " · " + (r.engine === "claude" ? "written by Claude" : "local engine") + (r.grounded ? " · grounded in " + r.grounded + " QueryBook fact(s)" : "")),
    engineNote(r), el("div", { style: "margin-top:10px" }, body));
}
function imageCard(r) {
  return el("div", { class: "card" }, el("img", { class: "media", src: r.url, alt: "Generated picture" }),
    el("div", { class: "row", style: "margin-top:8px" }, el("span", { class: "small muted grow" }, (r.engine === "claude" ? "Drawn by Claude" : "Local painter: " + (r.kind === "abstract" ? "abstract composition" : (r.elements || []).join(", ") + (r.light ? " · " + r.light : "")))),
      el("a", { class: "btn small", href: r.url, download: (r.id || "image") + ".svg" }, "Download SVG")), engineNote(r));
}
function videoCard(r) {
  return el("div", { class: "card" }, el("img", { class: "media", src: r.url + "?t=" + Date.now(), alt: "Generated film" }),
    el("div", { class: "row", style: "margin-top:8px" }, el("span", { class: "small muted grow" }, r.seconds + " seconds · " + r.scenes.length + " scenes · " + (r.engine === "claude" ? "storyboard by Claude" : "local engine")),
      el("a", { class: "btn ghost small", href: r.url, target: "_blank", rel: "noopener" }, "Play full size"),
      el("a", { class: "btn small", href: r.url, download: (r.id || "film") + ".svg" }, "Download"),
      el("button", { class: "btn ghost small", type: "button", onclick: () => openInterface("video-studio") }, "Take to Video Studio")),
    el("h3", {}, "Storyboard"), el("ol", {}, r.scenes.map(s => el("li", {}, s.caption, el("span", { class: "small muted" }, " — " + (s.start / 10) + " s")))), engineNote(r));
}
function audioCard(r) {
  if (r.error) return el("div", { class: "card" }, el("div", { class: "err" }, r.error), r.text ? el("p", { class: "small muted" }, "Words to say: " + r.text) : null,
    el("button", { class: "btn ghost small", type: "button", onclick: () => openInterface("lang-speech") }, "Open the Language Builder's Speech tab"));
  const what = r.kind === "music" ? `Music · ${r.key} ${r.scale} · ${r.tempo} bpm · ${r.notes} notes` : r.kind === "speech" ? "Speech (espeak-ng): " + r.text : "Sound effect · " + r.effect;
  return el("div", { class: "card" }, el("audio", { controls: true, src: r.url, style: "width:100%" }),
    el("div", { class: "row", style: "margin-top:6px" }, el("span", { class: "small muted grow" }, what + (r.seconds ? " · " + r.seconds + " s" : "")),
      el("a", { class: "btn small", href: r.url, download: (r.id || "audio") + ".wav" }, "Download WAV")));
}

function factsLine(f) {
  if (!f) return null;
  if (f.connected) {
    const parts = (f.ufcs || []).map(u => "UFCS " + u.path + " (" + u.facts.toLocaleString() + ")");
    if (f.commons) parts.push("Commons (" + f.commons.facts.toLocaleString() + ")");
    if ((f.shards || []).length) parts.push(f.shards.length + " bulk shard(s)");
    return el("div", { class: "row small", style: "margin:6px 0" }, el("span", { class: "dot ok" }),
      el("span", { style: "flex:1;min-width:0;overflow-wrap:anywhere" }, el("b", {}, f.facts.toLocaleString() + " facts"), " connected directly from " + f.root + " (read-only): " + parts.join(" · ")));
  }
  return el("div", { class: "row small", style: "margin:6px 0" }, el("span", { class: "dot err" }),
    el("span", { style: "flex:1;min-width:0" }, f.root ? (f.root_exists ? "No fact store found in " + f.root + "." : f.root + " is not connected — plug in the drive and restart VeriWave.") : "No data folder set."));
}

/* ------------------------------------------------------------------ Answer */
let lastAnswer = null;
function answerView() {
  const v = el("div", { class: "view" });
  const q = el("input", { type: "search", class: "grow", placeholder: "Ask a question — a fact, a word, a calculation", "aria-label": "Question", value: lastAnswer?.question || "" });
  const trust = el("input", { type: "range", min: "0", max: "100", step: "5", value: load("vw:trust", "50"), "aria-label": "Minimum trust" });
  const tv = el("span", { class: "small muted" }, trust.value + "%");
  trust.oninput = () => { tv.textContent = trust.value + "%"; save("vw:trust", trust.value); };
  const out = el("div");
  const go = async () => {
    if (!q.value.trim()) return;
    out.replaceChildren(el("div", { class: "card thinking" }, "Asking every QueryBook application…"));
    try { lastAnswer = await api("/api/vw/answer", { q: q.value, min_trust: +trust.value, subject: state.subject, engine: state.engine }); if (lastAnswer.subject) state.subject = lastAnswer.subject; out.replaceChildren(answerCard(lastAnswer)); }
    catch (e) { out.replaceChildren(el("div", { class: "err" }, e.message)); }
  };
  v.append(el("div", { class: "card" }, el("h2", {}, "Answer"),
    el("p", { class: "small muted" }, "Cite-or-refuse (QueryBook registry #1): every line comes from a QueryBook fact or an exact calculation, with its source and trust. Below the trust threshold a fact is held back; with nothing left, the answer is UNKNOWN."),
    factsLine(state.status?.facts),
    el("form", { class: "row", onsubmit: e => { e.preventDefault(); go(); } }, q, el("button", { class: "btn", type: "submit" }, "Ask")),
    el("div", { class: "row", style: "margin-top:8px" }, el("label", { class: "small muted" }, "Minimum trust "), trust, tv)), out);
  if (lastAnswer) out.append(answerCard(lastAnswer));
  return v;
}

/* ------------------------------------------------------------------ Code */
let lastCode = null;
function codeView() {
  const v = el("div", { class: "view" });
  const p = el("textarea", { placeholder: "Describe the application: \"a to-do list called Today\", \"track my books with title, author and year read\", \"a python script that counts words\"…", "aria-label": "Application description" }, lastCode?.prompt || "");
  const kind = el("select", { "aria-label": "Kind" }, [["", "Detect the kind"], ["todo", "To-do list"], ["calculator", "Calculator"], ["timer", "Timer / stopwatch"], ["notes", "Notes"], ["quiz", "Quiz"],
    ["converter", "Unit converter"], ["game", "Guessing game"], ["drawing", "Sketch pad"], ["landing", "Landing page"], ["records", "Record keeper"], ["python", "Python command-line tool"]].map(([val, t]) => el("option", { value: val }, t)));
  const out = el("div");
  const btn = el("button", { class: "btn", type: "submit" }, "Build it");
  v.append(el("div", { class: "card" }, el("h2", {}, "Code"),
    el("p", { class: "small muted" }, "The local engine builds eleven kinds of complete, single-file applications; with Claude on, anything you describe."),
    el("form", { onsubmit: async e => { e.preventDefault(); if (!p.value.trim()) return; btn.disabled = true; out.replaceChildren(el("div", { class: "card thinking" }, "Building…"));
      try { lastCode = await api("/api/vw/code", { prompt: p.value, kind: kind.value, engine: state.engine }); lastCode.prompt = p.value; out.replaceChildren(codeCard(lastCode)); }
      catch (err) { out.replaceChildren(el("div", { class: "err" }, err.message)); } btn.disabled = false; } },
      p, el("div", { class: "row", style: "margin-top:8px" }, kind, btn))), out);
  if (lastCode) out.append(codeCard(lastCode));
  return v;
}

/* ------------------------------------------------------------------ Create */
const lastCreate = {};
function createView(r) {
  const sub = r.sub || "text";
  const v = el("div", { class: "view" });
  v.append(el("div", { class: "subtabs" }, Object.entries(SUBS).map(([k, n]) => el("a", { href: "#" + k, "aria-current": k === sub ? "page" : null }, n))));
  const ideas = { text: ["Write a haiku about rain", "A short story about a lost key", "An email to my landlord about the broken heating", "An article about honey bees", "A slogan for my bakery"],
    image: ["A lighthouse by the sea at sunset", "A snowy mountain village at night", "A city skyline at night", "A flower meadow with a cottage", "Sailing boat in the harbour at dawn"],
    video: ["A 20 second video about a harbour town", "Six scenes about a mountain forest", "A short film about a city at night"],
    audio: ["A calm piano melody", "An upbeat jingle", "20 seconds of rain", "Ocean waves", "Say \"Welcome to VeriWave\""] };
  const p = el("textarea", { "aria-label": "Prompt", placeholder: "Describe what to make…" }, lastCreate[sub]?.prompt || "");
  const out = el("div");
  const btn = el("button", { class: "btn", type: "submit" }, "Create");
  const go = async () => { if (!p.value.trim()) return; btn.disabled = true; out.replaceChildren(el("div", { class: "card thinking" }, "Creating…"));
    try { const res = await api("/api/vw/create", { kind: sub, prompt: p.value, engine: state.engine }); res.prompt = p.value; lastCreate[sub] = res; out.replaceChildren(resultCard(sub, res)); gallery(); }
    catch (e) { out.replaceChildren(el("div", { class: "err" }, e.message)); } btn.disabled = false; };
  v.append(el("div", { class: "card" }, el("h2", {}, "Create: " + SUBS[sub]),
    el("form", { onsubmit: e => { e.preventDefault(); go(); } }, p, el("div", { class: "row", style: "margin-top:8px" }, btn)),
    el("div", { class: "tiles" }, ideas[sub].map(t => el("button", { class: "tile", type: "button", onclick: () => { p.value = t; go(); } }, t)))), out);
  if (lastCreate[sub]) out.append(resultCard(sub, lastCreate[sub]));
  const gal = el("div", { class: "card" }, el("h2", {}, "Recent creations"), el("div", { class: "gallery", id: "gallery" }));
  v.append(gal);
  gallery();
  return v;
}
async function gallery() {
  const g = document.getElementById("gallery");
  if (!g) return;
  try {
    const r = await api("/api/vw/items?limit=24");
    g.replaceChildren(...r.items.map(it => {
      const f = it.files || [];
      const first = f.find(x => /\.(svg)$/.test(x));
      const main = first || f.find(x => x !== "README.md") || f[0];
      return el("a", { href: "/out/" + it.id + "/" + (it.entry || main), target: "_blank", rel: "noopener" },
        first ? el("img", { src: "/out/" + it.id + "/" + first, alt: "", loading: "lazy" }) : null,
        el("b", {}, it.kind), el("div", { class: "muted" }, (it.title || it.prompt || "").slice(0, 60)));
    }));
    if (!r.items.length) g.append(el("p", { class: "muted small" }, "Nothing yet."));
  } catch (e) { g.replaceChildren(el("p", { class: "small muted" }, e.message)); }
}

/* ------------------------------------------------------------------ QueryBook interfaces */
function dotFor(i) {
  if (i.builtin) return "ok";
  if (i.url) return "ok";
  const p = prog(i.app);
  return p && p.state === "starting" ? "wait" : "err";
}
function querybookView() {
  const v = el("div", { class: "view" });
  const st = state.status;
  if (!st) { v.append(el("div", { class: "card thinking" }, "Loading…")); return v; }
  const sel = new Set();
  const qb = st.querybook;
  v.append(el("div", { class: "card" }, el("h2", {}, "QueryBook — every screen, on demand"),
    el("p", { class: "small muted" }, qb.note + " Tick any screens and open them together in the Workspace, or open one on its own."),
    factsLine(st.facts),
    el("div", { class: "apps" }, (qb.programs || []).map(p => el("span", { class: "app" }, el("span", { class: "dot " + (p.state === "running" ? "ok" : p.state === "starting" ? "wait" : "err") }), p.name, " · ", p.state,
      p.state !== "running" && p.state !== "starting" && qb.mode !== "none" ? el("button", { class: "btn ghost small", type: "button", onclick: async () => { try { await api("/api/vw/querybook/restart", { id: p.id }); toast("Starting " + p.name); setTimeout(refresh, 1500); } catch (e) { toast(e.message); } } }, "Start") : null)),
      st.querybook.books_url ? el("span", { class: "app" }, el("span", { class: "dot ok" }), "Book Intelligence Studio") : el("span", { class: "app" }, el("span", { class: "dot err" }), "Book Studio (needs PHP)")),
    el("div", { class: "row", style: "margin-top:10px" },
      el("button", { class: "btn", type: "button", onclick: () => { if (!sel.size) return toast("Tick at least one screen"); for (const id of sel) addPane(id); location.hash = "#workspace"; } }, "Open ticked screens in the Workspace"),
      el("button", { class: "btn ghost", type: "button", onclick: () => { for (const i of st.interfaces.filter(x => visible(x) && !x.builtin && x.url)) addPane(i.id); location.hash = "#workspace"; } }, "Open every running screen"))));
  const groups = {};
  for (const i of st.interfaces.filter(visible)) (groups[i.group_name] = groups[i.group_name] || []).push(i);
  for (const [g, items] of Object.entries(groups)) {
    v.append(el("div", { class: "group" }, el("h3", {}, g), el("div", { class: "ifaces" }, items.map(i => el("div", { class: "iface" },
      el("label", {}, el("input", { type: "checkbox", onchange: e => e.target.checked ? sel.add(i.id) : sel.delete(i.id) }), el("span", { class: "dot " + dotFor(i) }), el("span", {}, i.name)),
      el("p", {}, i.about),
      el("div", { class: "row" }, el("button", { class: "btn small", type: "button", onclick: () => openInterface(i.id) }, i.builtin ? "Go" : "Open"),
        !i.builtin && i.url ? el("a", { class: "btn ghost small", href: i.url, target: "_blank", rel: "noopener" }, "New window") : null,
        i.serves.length ? el("span", { class: "small muted" }, "registry: " + i.serves.join(", ")) : null))))));
  }
  return v;
}
function openInterface(id) {
  const i = iface(id);
  if (!i) { location.hash = "#querybook"; return; }
  if (i.builtin) { location.hash = "#" + i.hash; return; }
  addPane(id);
  state.wsActive = id; save("vw:wsActive", id);
  if (location.hash === "#workspace") render(); else location.hash = "#workspace";
}
function addPane(id) { if (!state.ws.includes(id)) { state.ws.push(id); save("vw:ws", state.ws); } }

/* ------------------------------------------------------------------ Workspace
   The panes live outside <main> and are only shown, hidden or re-laid-out, never rebuilt or moved: an iframe that is
   moved reloads, and a QueryBook screen would lose what you typed. */
const wsPanes = document.getElementById("wsPanes");
const paneEls = {};
function workspaceView() {
  const wrap = el("div", { class: "ws" });
  const panes = state.ws.map(iface).filter(Boolean).filter(i => !i.builtin);
  if (!panes.length) {
    wrap.append(el("div", { class: "view" }, el("div", { class: "card" }, el("h2", {}, "Workspace"),
      el("p", { class: "muted" }, "Any QueryBook screens, side by side or as tabs. Choose them on the QueryBook page, or ask in Chat: \"open the Language Lab\"."),
      el("a", { class: "btn", href: "#querybook" }, "Choose screens"))));
    return wrap;
  }
  if (!panes.some(p => p.id === state.wsActive)) state.wsActive = panes[0].id;
  const layout = state.wsLayout;
  wrap.append(el("div", { class: "wsbar" },
    el("div", { class: "wstabs" }, panes.map(i => el("button", { type: "button", "aria-pressed": String(layout === "tabs" && i.id === state.wsActive), onclick: () => { state.wsActive = i.id; save("vw:wsActive", i.id); if (layout !== "tabs") { state.wsLayout = "tabs"; save("vw:wsLayout", "tabs"); } render(); } },
      i.name, el("span", { class: "x", role: "button", "aria-label": "Close " + i.name, onclick: e => { e.stopPropagation(); state.ws = state.ws.filter(x => x !== i.id); save("vw:ws", state.ws); render(); } }, "×")))),
    el("label", { class: "small muted" }, "Layout ", el("select", { onchange: e => { state.wsLayout = e.target.value; save("vw:wsLayout", e.target.value); render(); } },
      [["tabs", "Tabs"], ["two", "Side by side"], ["grid", "Grid"]].map(([k, n]) => el("option", { value: k, selected: k === layout }, n)))),
    el("a", { class: "btn ghost small", href: "#querybook" }, "Add screens")));
  return wrap;
}
function buildPane(i) {
  const pane = el("section", { class: "pane", "aria-label": i.name, "data-url": i.url || "" }, el("header", {}, el("b", {}, i.name), el("span", { class: "small muted" }, i.app_name),
    i.url ? el("a", { class: "small", href: i.url, target: "_blank", rel: "noopener" }, "New window") : null));
  if (i.url) pane.append(el("iframe", { src: i.url, title: i.name, allow: "camera; microphone; autoplay; clipboard-write; fullscreen" }));
  else {
    const p = prog(i.app);
    pane.append(el("div", { class: "wait" }, el("p", {}, i.app === "books" ? "The Book Intelligence Studio needs PHP on this computer (php -S runs it)." :
      p ? p.name + " is " + p.state + "." : "QueryBook's applications are not running with VeriWave."),
      p && p.state !== "running" ? el("button", { class: "btn small", type: "button", onclick: async () => { try { await api("/api/vw/querybook/restart", { id: i.app }); toast("Starting…"); setTimeout(refresh, 2000); } catch (e) { toast(e.message); } } }, "Start it") : null));
  }
  return pane;
}
function syncPanes(show) {
  const panes = state.ws.map(iface).filter(Boolean).filter(i => !i.builtin);
  wsPanes.hidden = !show || !panes.length;
  wsPanes.className = "panes " + state.wsLayout;
  for (const id of Object.keys(paneEls)) if (!state.ws.includes(id)) { paneEls[id].remove(); delete paneEls[id]; }
  for (const i of panes) {
    let pe = paneEls[i.id];
    if (pe && pe.dataset.url !== (i.url || "")) { pe.remove(); pe = null; }   // its application started (or stopped): rebuild once
    if (!pe) { pe = buildPane(i); paneEls[i.id] = pe; wsPanes.append(pe); }
    pe.hidden = state.wsLayout === "tabs" && i.id !== state.wsActive;
  }
}

/* ------------------------------------------------------------------ Feature Registry */
let featCache = null;
function featuresView() {
  const v = el("div", { class: "view" });
  const s = state.status?.registry;
  if (s) v.append(el("div", { class: "stats", style: "margin-bottom:14px" },
    [["Features", s.total], ["Built", s.built], ["Partly built", s.partial], ["Not built yet", s.not_built], ["Added by VeriWave", s.veriwave]].map(([k, n]) => el("div", { class: "stat" }, el("b", {}, n), el("span", { class: "small muted" }, k)))));
  const f = state.feat;
  const q = el("input", { type: "search", class: "grow", placeholder: "Search 407 features (name, rule, screen, notes) or a number", value: f.q, "aria-label": "Search features" });
  const mk = (key, label, opts) => el("select", { "aria-label": label, onchange: e => { f[key] = e.target.value; list(); } }, el("option", { value: "" }, label), opts.map(o => el("option", { value: o[0], selected: f[key] === o[0] }, o[1])));
  const domains = Object.keys(s?.domains || {}).map(d => [d, d]);
  const areas = Object.keys(s?.areas || {}).map(d => [d, d]);
  const impl = Object.entries(s?.status_names || {}).map(([k, n]) => [k, n]);
  const table = el("div", { class: "tbl" });
  q.oninput = () => { f.q = q.value; clearTimeout(q.t); q.t = setTimeout(list, 200); };
  v.append(el("div", { class: "card" }, el("h2", {}, "QueryBook Composite Feature Registry v71"),
    el("p", { class: "small muted" }, "Every feature with its rule, formula, status in QueryBook v9.64 and the applications, and the screen that serves it. Click a row for the details."),
    el("div", { class: "row" }, q, mk("domain", "All domains", domains), mk("area", "All screens", areas), mk("implemented", "Any status", impl))), el("div", { class: "card" }, table));
  async function list() {
    const p = new URLSearchParams({ q: f.q, domain: f.domain, area: f.area, implemented: f.implemented, limit: "500" });
    try { featCache = (await api("/api/vw/features?" + p)).features; } catch (e) { table.replaceChildren(el("div", { class: "err" }, e.message)); return; }
    drawTable();
  }
  function drawTable() {
    const rows = [el("tr", {}, ["#", "Feature", "Domain", "Screen", "Status"].map(h => el("th", {}, h)))];
    for (const x of featCache) {
      rows.push(el("tr", { class: "f", onclick: () => { f.open = f.open === x.no ? 0 : x.no; drawTable(); } },
        el("td", {}, x.no), el("td", {}, x.feature, x.veriwave ? el("span", { class: "chip vw", style: "margin-left:6px" }, "VeriWave") : null), el("td", { class: "small" }, x.domain),
        el("td", { class: "small" }, x.area), el("td", {}, el("span", { class: "chip " + (x.implemented.startsWith("built") ? "built" : x.implemented === "partial" ? "partial" : "not") }, x.status))));
      if (f.open === x.no) rows.push(el("tr", { class: "detail" }, el("td", { colspan: "5" }, el("dl", {},
        el("dt", {}, "Rule"), el("dd", {}, x.rule || "—"), el("dt", {}, "On screen"), el("dd", {}, x.on_screen || "—"),
        el("dt", {}, "Formula"), el("dd", { class: "small" }, x.formula || "—", x.lean ? el("span", { class: "chip", style: "margin-left:6px" }, "Lean-provable") : null),
        el("dt", {}, "Where it lives"), el("dd", { class: "small" }, x.where.length ? el("ul", { style: "margin:0;padding-left:18px" }, x.where.map(w => el("li", {}, w))) : "—"),
        x.veriwave ? [el("dt", {}, "In VeriWave"), el("dd", {}, x.veriwave)] : null,
        el("dt", {}, "Notes"), el("dd", { class: "small" }, x.notes || "—")),
        el("button", { class: "btn small", type: "button", onclick: () => openInterface(x.interface) }, "Open " + (iface(x.interface)?.name || "its screen")))));
    }
    table.replaceChildren(el("p", { class: "small muted" }, featCache.length + " feature(s)"), el("table", { class: "ftable" }, rows));
  }
  if (featCache && !f.q && !f.domain && !f.area && !f.implemented) drawTable(); else list();
  return v;
}

/* ------------------------------------------------------------------ Reasoning (admin)
   Every kind of logic, reasoning, decision and analysis the QueryBook Bible documents, for one prompt. */
const STATUS_CLS = { "ran": "built", "not applicable": "not", "specified, not built": "partial" };
let traceCache = { list: [], types: [] };
function reasoningView(r) {
  const v = el("div", { class: "view wide" });
  const list = el("div", { class: "tlist" });
  const detail = el("div", { class: "tdetail" });
  v.append(el("div", { class: "card" }, el("h2", {}, "Reasoning — every logic type behind each answer"),
    el("p", { class: "small muted" }, "For each prompt: the stages VeriWave ran, each tagged with its logic type and the QueryBook Bible chapter that specifies it; every Fact Unit with its UFCS packet tracking and Ontology Mesh links; and the status of every Bible logic type — ran, not applicable to this prompt, or specified in the Bible but not built yet.")),
    el("div", { class: "tgrid" }, list, detail));
  const pick = async id => {
    detail.replaceChildren(el("div", { class: "card thinking" }, "Loading the trace…"));
    try { detail.replaceChildren(traceDetail(await api("/api/vw/trace?id=" + encodeURIComponent(id)))); }
    catch (e) { detail.replaceChildren(el("div", { class: "err" }, e.message)); }
    list.querySelectorAll("button").forEach(b => b.setAttribute("aria-current", b.dataset.id === id ? "page" : "false"));
  };
  (async () => {
    try { const d = await api("/api/vw/traces?limit=200"); traceCache = { list: d.traces, types: d.logic_types }; }
    catch (e) { list.replaceChildren(el("div", { class: "err" }, e.message)); return; }
    if (!traceCache.list.length) { list.append(el("p", { class: "muted small" }, "No prompts yet. Ask something in Chat or Answer.")); detail.replaceChildren(logicLegend()); return; }
    list.append(...traceCache.list.map(t => el("button", { type: "button", "data-id": t.id, onclick: () => { history.replaceState(null, "", "#reasoning:" + t.id); pick(t.id); } },
      el("span", { class: "chip" }, t.route), t.verdict ? el("span", { class: "verdict " + t.verdict, style: "margin-left:6px" }, t.verdict) : null,
      el("div", { class: "tprompt" }, t.prompt), el("div", { class: "small muted" }, new Date(t.at * 1000).toLocaleTimeString() + " · " + t.total_ms + " ms"))));
    pick(r.trace || traceCache.list[0].id);
  })();
  return v;
}
function logicLegend() {
  return el("div", { class: "card" }, el("h2", {}, "The QueryBook Bible's logic types"), el("div", { class: "lgrid" }, traceCache.types.map(t =>
    el("div", { class: "lcard" }, el("b", {}, t.name), el("div", { class: "small muted" }, t.chapters), el("p", { class: "small" }, t.bible)))));
}
function traceDetail(t) {
  const out = el("div");
  const ran = t.logic.filter(l => l.status === "ran").length;
  out.append(el("div", { class: "card" },
    el("div", { class: "row" }, el("span", { class: "chip" }, t.route), t.verdict ? el("span", { class: "verdict " + t.verdict }, t.verdict) : null,
      el("span", { class: "small muted" }, "trace " + t.id + " · " + new Date(t.at * 1000).toLocaleString() + " · " + t.total_ms + " ms")),
    el("div", { class: "short" }, t.prompt), t.short ? el("div", { class: "muted" }, t.short) : null));
  out.append(el("div", { class: "card" }, el("h2", {}, "Logic types — " + ran + " of " + t.logic.length + " ran for this prompt"),
    el("div", { class: "lgrid" }, t.logic.map(l => el("div", { class: "lcard " + STATUS_CLS[l.status] },
      el("div", { class: "row" }, el("b", { class: "grow" }, l.name), el("span", { class: "chip " + STATUS_CLS[l.status] }, l.status)),
      el("div", { class: "small muted" }, l.chapters),
      el("p", { class: "small", style: "margin:6px 0 4px" }, el("i", {}, "Bible: "), l.bible),
      el("p", { class: "small", style: "margin:0" }, el("i", {}, "VeriWave: "), l.veriwave),
      l.stages.length ? el("div", { class: "small muted", style: "margin-top:4px" }, "In: " + l.stages.join(", ")) : null)))));
  out.append(el("div", { class: "card" }, el("h2", {}, "Stages, in the order they ran"),
    el("ol", { class: "stages" }, t.stages.map(s => el("li", { class: STATUS_CLS[s.status] },
      el("details", { open: s.status === "ran" && ["packets", "linkage", "deduce", "gate"].includes(s.id) ? true : null },
        el("summary", {}, el("b", {}, s.name), " ", el("span", { class: "chip " + STATUS_CLS[s.status] }, s.status),
          s.logic.map(id => el("span", { class: "chip logic" }, (t.logic.find(l => l.id === id) || { name: id }).name)),
          s.status === "ran" ? el("span", { class: "small muted" }, " " + s.ms + " ms · " + s.category) : null,
          el("div", { class: "small", style: "margin:4px 0 0 2px" }, s.summary)),
        stageData(s, t)))))));
  if ((t.packets || []).length) out.append(packetCard(t.packets));
  const ln = t.stages.find(s => s.id === "linkage");
  if (ln && ln.status === "ran") out.append(linkCard(ln.data.links));
  if ((t.slices || []).length) {
    const max = Math.max(...t.slices.map(x => x.ms), 0.01);
    out.append(el("div", { class: "card" }, el("h2", {}, "Processor Slices (Ch. 69)"),
      t.slices.map(x => el("div", { class: "slice" }, el("span", { class: "sname" }, x.category + " (" + x.stages + ")"),
        el("span", { class: "sbar" }, el("span", { style: "width:" + Math.max(1, Math.round(x.ms / max * 100)) + "%" })), el("span", { class: "small muted" }, x.ms + " ms")))));
  }
  return out;
}
function kv(obj) {
  const rows = Object.entries(obj || {}).filter(([k, v]) => v !== "" && v != null && !(Array.isArray(v) && !v.length) && typeof v !== "object");
  return rows.length ? el("dl", { class: "kv" }, rows.flatMap(([k, v]) => [el("dt", {}, k.replace(/_/g, " ")), el("dd", {}, String(v))])) : null;
}
function stageData(s, t) {
  const d = s.data || {};
  const box = el("div", { class: "sdata" });
  if (s.id === "route" || s.id === "understand" || s.id === "engine" || s.id === "generate" || s.id === "store" || s.id === "temporal" || s.id === "directive" || s.id === "express" || s.id === "provenance") box.append(kv(d) || "");
  if (s.id === "understand") box.append(el("div", { class: "small" }, "Spellings looked up: " + (d.spellings || []).join(" · ") + (d.predicate_hints?.length ? " — predicate hints: " + d.predicate_hints.join(", ") : "")));
  if (s.id === "retrieve") {
    box.append(el("div", { class: "small" }, el("b", {}, "FQL issued"), el("ul", {}, (d.fql || []).map(q => el("li", { class: "mono" }, q)))));
    if ((d.stores || []).length) box.append(el("div", { class: "small" }, el("b", {}, "Stores read (read-only): "), d.stores.join(" · ")));
    if ((d.applications_asked || []).length) box.append(el("div", { class: "small" }, "QueryBook applications asked: " + d.applications_asked.join(", ")));
    if (d.rph) box.append(el("div", { class: "small" }, el("b", {}, "Response provenance hash (RPH): "), el("span", { class: "hash" }, d.rph), el("div", { class: "hash" }, "over: " + d.rph_input.slice(0, 160) + (d.rph_input.length > 160 ? "…" : ""))));
  }
  if (s.id === "packets") box.append(el("div", { class: "small muted" }, "See UFCS packet tracking below."));
  if (s.id === "linkage") box.append(el("div", { class: "small muted" }, "See Fact Unit linkage below."));
  if (s.id === "gate") box.append(el("table", { class: "ftable" }, el("tr", {}, el("th", {}, "#"), el("th", {}, "Fact Unit"), el("th", {}, "Trust"), el("th", {}, "Source")),
    (d.offered || []).map(o => el("tr", {}, el("td", {}, o.n), el("td", {}, o.text), el("td", {}, o.trust + "%"), el("td", { class: "small" }, o.where)))),
    el("div", { class: "small muted" }, "Threshold " + d.threshold + "% · held back " + d.withheld + " · distinct sources " + d.distinct_sources));
  if (s.id === "consistency") box.append(el("div", { class: "small" }, "Rule: " + d.rule), (d.conflicts || []).map(k => el("div", { class: "conflict" }, k.subject + " — " + k.predicate + ": " + k.values.map(v => v.value).join(" vs "))));
  if (s.id === "deduce") {
    box.append(el("div", { class: "small" }, "Rule: " + d.rule), el("div", { class: "small" }, "Premises: " + ((d.premises || []).map(n => "[" + n + "]").join(" ") || "none")));
    if (d.derivation && d.derivation.expression) box.append(kv(d.derivation));
  }
  return box;
}
function packetCard(packets) {
  const pre = el("pre", { class: "code", hidden: true });
  return el("div", { class: "card" }, el("h2", {}, "UFCS packet tracking — " + packets.length + " Fact Unit(s)"),
    el("p", { class: "small muted" }, "Each cited Fact Unit: its nucleus, the semantic fingerprint stored in the UFCS index, the fingerprint VeriWave recomputed from the nucleus (SHA-256 of norm(subject)|norm(predicate)|norm(object)|polarity), and the block holding the full packet."),
    el("div", { class: "tbl" }, el("table", { class: "ftable" }, el("tr", {}, ["#", "Nucleus (subject · predicate · object)", "Pol.", "Trust", "Store", "Semantic fingerprint", "Verified", ""].map(h => el("th", {}, h))),
      packets.map((p, i) => el("tr", {}, el("td", {}, i + 1),
        el("td", {}, p.nucleus.subject, el("span", { class: "muted" }, " · " + p.nucleus.predicate + " · "), p.nucleus.object),
        el("td", {}, p.polarity || "?"), el("td", {}, p.trust + "%"),
        el("td", { class: "small" }, p.kind.toUpperCase(), p.block_file ? el("div", { class: "muted" }, p.block_file) : null, p.dataset ? el("div", { class: "muted" }, p.dataset) : null),
        el("td", { class: "hash", title: "stored: " + p.stored_fp + "\ncomputed: " + p.computed_fp }, (p.stored_fp || "—").slice(0, 16) + "…"),
        el("td", {}, p.verified ? el("span", { class: "chip built" }, "✓ matches") : el("span", { class: "chip " + (p.kind === "ufcs" ? "partial" : "not"), title: p.note || "" }, p.kind === "ufcs" ? "✗ differs" : "suite id")),
        el("td", {}, p.kind === "ufcs" ? el("button", { class: "btn ghost small", type: "button", onclick: async e => {
          e.target.disabled = true; pre.hidden = false; pre.textContent = "Reading block " + p.block + " for this packet…";
          try { pre.textContent = JSON.stringify(await api("/api/vw/packet?store=" + encodeURIComponent(p.store) + "&block=" + p.block + "&fp=" + p.stored_fp), null, 2); }
          catch (err) { pre.textContent = err.message; } e.target.disabled = false; } }, "Full packet") : null))))), pre);
}
function linkCard(links) {
  const box = el("div", { class: "card" }, el("h2", {}, "Fact Unit linkage (Ontology Mesh, one hop)"),
    el("p", { class: "small muted" }, "Siblings share the cited Fact Unit's subject; onward links are Fact Units about its object. Inbound links (facts whose object is this subject) need an object index the UFCS store does not keep."));
  for (const l of links) {
    const nodes = [...l.siblings.map(x => ({ x, kind: "sibling" })), ...l.onward.map(x => ({ x, kind: "onward" }))].slice(0, 10);
    const W = 760, H = 60 + Math.max(1, nodes.length) * 34;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("class", "lsvg"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Links of " + l.fact);
    const add = (tag, attrs, text) => { const n = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text) n.textContent = text; svg.append(n); return n; };
    const cy = H / 2;
    nodes.forEach((n, i) => { const y = 40 + i * 34; add("line", { x1: 250, y1: cy, x2: 430, y2: y, class: "ledge " + n.kind });
      add("text", { x: 440, y: y + 4, class: "ltext" }, (n.kind === "onward" ? "→ " : "↔ ") + n.x.predicate + ": " + n.x.object.slice(0, 40) + "  (" + n.x.trust + "%)"); });
    add("rect", { x: 10, y: cy - 22, width: 240, height: 44, rx: 8, class: "lnode" });
    add("text", { x: 20, y: cy - 4, class: "ltext b" }, l.fact.split(" — ")[0].slice(0, 30));
    add("text", { x: 20, y: cy + 12, class: "ltext s" }, (l.fact.split(" — ")[1] || "").slice(0, 36));
    if (!nodes.length) add("text", { x: 440, y: cy + 4, class: "ltext s" }, "no linked Fact Units one hop away");
    box.append(svg);
  }
  return box;
}

/* ------------------------------------------------------------------ Readiness (admin)
   How well VeriWave answers from the fact store on D:\QB: sampled real facts in several phrasings plus your own questions. */
const TARGETS = [["accuracy", "Accuracy", 98, ">="], ["top_answer_accuracy", "Top answer right", 90, ">="], ["answer_rate", "Answer rate", 90, ">="],
  ["wrong_refusal_rate", "Wrong refusals", 10, "<="], ["p95_ms", "95th-percentile time (ms)", 2000, "<="]];
let evalTimer = null;
function readinessView() {
  const v = el("div", { class: "view wide" });
  const head = el("div", { class: "card" }, el("p", { class: "muted" }, "Loading…"));
  const reports = el("div");
  const detail = el("div");
  v.append(head, el("div", { class: "tgrid" }, reports, detail));
  const showReport = async name => {
    detail.replaceChildren(el("div", { class: "card thinking" }, "Loading the report…"));
    try { detail.replaceChildren(reportView(await api("/api/vw/eval?name=" + encodeURIComponent(name)))); }
    catch (e) { detail.replaceChildren(el("div", { class: "err" }, e.message)); }
    reports.querySelectorAll("button").forEach(b => b.setAttribute("aria-current", b.dataset.name === name ? "page" : "false"));
  };
  const refreshEvals = async first => {
    let d;
    try { d = await api("/api/vw/evals"); } catch (e) { head.replaceChildren(el("div", { class: "err" }, e.message)); return; }
    const size = el("select", { "aria-label": "Sample size" }, [100, 300, 1000].map(n => el("option", { value: n, selected: n === 300 }, n + " facts × " + d.phrasings.length + " phrasings")));
    const st = d.state;
    const busy = st.running;
    head.replaceChildren(el("h2", {}, "Readiness — is VeriWave ready to publish?"),
      el("p", { class: "small muted" }, "Real Fact Units are drawn at random from the store and asked about in " + d.phrasings.length + " phrasings (" + d.phrasings.join(" · ") + "). The fact is known to be there, so \u201cI don't know\u201d is a retrieval failure and a citation without the right object is a wrong answer. Your own questions in " + d.questions_file + " are added (one JSON object per line: {\"question\": \u2026, \"expect\": [\u2026]} or {\"question\": \u2026, \"expect_unknown\": true})."),
      el("div", { class: "row small", style: "margin:8px 0" }, el("span", { class: "dot " + (d.blocked ? "err" : "ok") }),
        el("span", { style: "flex:1;min-width:0" }, d.blocked ? el("b", {}, d.blocked) : [el("b", {}, "Evaluating against " + d.root), " — " + (d.store.facts || 0).toLocaleString() + " facts connected (read-only)"])),
      el("div", { class: "row" }, size, el("button", { class: "btn", type: "button", disabled: busy || !!d.blocked || null, onclick: async () => {
        try { await api("/api/vw/eval/run", { sample: +size.value, seed: Math.floor(Date.now() / 1000) % 100000 }); refreshEvals(false); } catch (e) { toast(e.message); } } }, busy ? "Running…" : "Run evaluation"),
        busy ? el("span", { class: "small muted" }, st.total ? st.done + " / " + st.total + " questions" : "drawing facts from the store…") : null,
        st.error ? el("span", { class: "err small" }, st.error) : null));
    reports.replaceChildren(el("div", { class: "tlist" }, d.reports.length ? d.reports.map(r => el("button", { type: "button", "data-name": r.name, onclick: () => showReport(r.name) },
      el("b", {}, new Date(r.at * 1000).toLocaleString()), r.ok ? el("div", { class: "small" }, "accuracy " + r.summary.accuracy + "% · answer rate " + r.summary.answer_rate + "%") : el("div", { class: "err small" }, r.error),
      el("div", { class: "small muted" }, r.root + " · " + (r.facts || 0).toLocaleString() + " facts · " + (r.summary ? r.summary.questions : 0) + " questions"))) : el("p", { class: "muted small" }, "No reports yet.")));
    clearTimeout(evalTimer);
    if (busy) evalTimer = setTimeout(() => { if (route().mode === "readiness") refreshEvals(false); }, 2000);
    if ((first || (!busy && st.last)) && d.reports.length) showReport(st.last && !busy ? st.last : d.reports[0].name);
  };
  refreshEvals(true);
  return v;
}
function reportView(r) {
  const out = el("div");
  if (!r.ok) { out.append(el("div", { class: "card" }, el("h2", {}, "Did not run"), el("div", { class: "err" }, r.error))); return out; }
  const s = r.summary;
  out.append(el("div", { class: "card" }, el("h2", {}, "Report — " + new Date(r.at * 1000).toLocaleString()),
    el("div", { class: "small muted" }, "Store " + r.root + " · " + (r.store.facts || 0).toLocaleString() + " facts · " + s.questions + " questions · seed " + r.seed + " · " + (r.seconds || 0) + " s"),
    el("div", { class: "stats", style: "margin-top:10px" }, [["Accuracy", s.accuracy + "%"], ["Top answer right", s.top_answer_accuracy + "%"], ["Answer rate", s.answer_rate + "%"],
      ["Wrong refusals", s.wrong_refusal_rate + "%"], ["Median time", s.median_ms + " ms"], ["95th percentile", s.p95_ms + " ms"]].map(([k, n]) => el("div", { class: "stat" }, el("b", {}, n), el("span", { class: "small muted" }, k))))));
  out.append(el("div", { class: "card" }, el("h2", {}, "Against suggested release targets"),
    el("p", { class: "small muted" }, "Starting points for a cite-or-refuse system — a confident wrong answer with a citation is worse than a refusal. The bar is your decision."),
    el("table", { class: "ftable" }, el("tr", {}, ["Measure", "This run", "Suggested", ""].map(h => el("th", {}, h))),
      TARGETS.map(([k, name, t, op]) => { const val = s[k]; const pass = op === ">=" ? val >= t : val <= t;
        return el("tr", {}, el("td", {}, name), el("td", {}, String(val) + (k.endsWith("ms") ? "" : "%")), el("td", {}, op + " " + t + (k.endsWith("ms") ? "" : "%")),
          el("td", {}, el("span", { class: "chip " + (pass ? "built" : "partial") }, pass ? "meets" : "not yet"))); }))));
  if (r.by_phrasing) out.append(el("div", { class: "card" }, el("h2", {}, "By phrasing (where retrieval breaks)"),
    el("table", { class: "ftable" }, el("tr", {}, ["Phrasing", "Answer rate", "Accuracy", "Wrong refusals"].map(h => el("th", {}, h))),
      Object.entries(r.by_phrasing).map(([t, p]) => el("tr", {}, el("td", { class: "mono" }, t), el("td", {}, p.answer_rate + "%"), el("td", {}, p.accuracy + "%"), el("td", {}, p.wrong_refusal_rate + "%"))))));
  const bad = r.rows.filter(x => x.outcome !== "correct" && x.outcome !== "correct refusal");
  out.append(el("div", { class: "card" }, el("h2", {}, "Failures (" + bad.length + ")"),
    bad.length ? el("div", { class: "tbl" }, el("table", { class: "ftable" }, el("tr", {}, ["Question", "Outcome", "Expected", "VeriWave said", ""].map(h => el("th", {}, h))),
      bad.slice(0, 300).map(x => el("tr", {}, el("td", {}, x.question), el("td", {}, el("span", { class: "chip partial" }, x.outcome)), el("td", { class: "small" }, (x.expect || []).join(" | ") || "(I don't know)"),
        el("td", { class: "small" }, x.short), el("td", {}, x.trace_id ? el("a", { class: "small", href: "#reasoning:" + x.trace_id }, "trace") : null))))) : el("p", { class: "muted" }, "None.")));
  return out;
}

/* ------------------------------------------------------------------ start */
async function refresh() {
  const before = JSON.stringify((state.status?.interfaces || []).map(i => i.url)) + JSON.stringify((state.status?.querybook?.programs || []).map(p => p.state));
  try { state.status = await api("/api/vw/status"); } catch (e) { toast("VeriWave is not answering: " + e.message); }
  const after = JSON.stringify((state.status?.interfaces || []).map(i => i.url)) + JSON.stringify((state.status?.querybook?.programs || []).map(p => p.state));
  if (!refresh.done || (before !== after && ["querybook", "workspace"].includes(route().mode))) render(); else drawBar();
  refresh.done = true;
}
render();
refresh();
setInterval(() => { if (["querybook", "workspace"].includes(route().mode)) refresh(); }, 8000);
