/* QueryBook one window. Each area is either the Ask page (built in) or one of the suite's applications shown in place.
   Applications stay loaded when you switch away, so nothing you typed is lost. */
"use strict";

const AREAS = [
  { band: "Everyday" },
  { id: "ask", name: "Ask", builtin: true },
  { id: "language", name: "Language", app: "language" },
  { id: "stem", name: "STEM", app: "stem" },
  { id: "history", name: "History & News", app: "facts" },
  { id: "video", name: "Video Studio", app: "video" },
  { band: "Operate", admin: true },
  { id: "harvest", name: "Harvest", app: "control", hash: "bulk", admin: true },
  { id: "knowledge", name: "Knowledge", app: "control", hash: "facts", admin: true },
  { id: "trust", name: "Trust & Security", app: "control", hash: "audit", admin: true },
  { id: "system", name: "System", app: "control", hash: "diag", admin: true },
];
const SOON = ["Learn — stage 3", "Author & Publish — stage 3", "Insight — stage 4"];
const ROLES = ["Reader", "Author", "Instructor", "Admin"];
let role = load("qb:role", "Admin"), current = load("qb:area", "ask");
let status = { programs: [] };
const frames = {};

function load(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
function save(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.append(k instanceof Node ? k : String(k));
  return n;
}
const prog = id => (status.programs || []).find(p => p.id === id) || { state: "starting" };
const visible = a => !a.admin || role === "Admin";

function drawRoles() {
  const box = document.getElementById("roles");
  box.replaceChildren(...ROLES.map(r => el("button", { type: "button", "aria-pressed": String(r === role), onclick: () => {
    role = r; save("qb:role", r);
    if (!visible(AREAS.find(a => a.id === current) || {})) current = "ask";
    drawRoles(); drawRail(); show(current);
  } }, r)));
}

function drawRail() {
  const rail = document.getElementById("rail");
  rail.replaceChildren();
  for (const a of AREAS) {
    if (!visible(a)) continue;
    if (a.band) { rail.append(el("div", { class: "band" }, a.band)); continue; }
    const st = a.builtin ? "running" : prog(a.app).state;
    const cls = st === "running" ? "ok" : st === "starting" ? "wait" : "err";
    rail.append(el("button", { type: "button", "aria-current": a.id === current ? "page" : null, onclick: () => show(a.id), title: a.builtin ? "" : st },
      el("span", {}, a.name), el("span", { class: "dot " + cls, "aria-label": st })));
  }
  rail.append(el("div", { class: "soon" }, el("b", {}, "Coming next"), ...SOON.map(s => el("div", {}, s))));
}

function show(id) {
  current = id; save("qb:area", id);
  drawRail();
  const pane = document.getElementById("pane");
  for (const f of Object.values(frames)) f.hidden = true;
  const old = pane.querySelector(".view"); if (old) old.remove();
  const a = AREAS.find(x => x.id === id);
  if (!a) return;
  if (a.builtin) { pane.append(askView()); return; }
  const p = prog(a.app);
  if (p.state !== "running" || !p.url) { pane.append(waitingView(a, p)); return; }
  const src = p.url + (a.hash ? "#" + a.hash : "");
  let f = frames[id];
  if (!f || f.dataset.base !== p.url) {
    if (f) f.remove();
    f = el("iframe", { title: a.name, src, "data-base": p.url, allow: "camera; microphone; autoplay; clipboard-write; fullscreen; xr-spatial-tracking" });
    frames[id] = f; pane.append(f);
  } else if (a.hash) {
    try { f.contentWindow.location.hash = a.hash; } catch (e) { f.src = src; }
  }
  f.hidden = false;
}

function waitingView(a, p) {
  const starting = p.state === "starting";
  return el("div", { class: "view" }, el("div", { class: "card" },
    el("h2", {}, a.name),
    el("p", {}, starting ? "Starting… this takes a few seconds the first time." : `This application ${p.state}.`),
    !starting && p.output && p.output.length ? el("pre", { class: "out" }, p.output.join("\n")) : null,
    !starting ? el("button", { class: "btn", type: "button", onclick: async () => {
      await fetch("/api/shell/restart", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: a.app }) });
      refresh();
    } }, "Start it again") : null));
}

/* ------------------------------------------------------------------ Ask */
let lastAnswer = null, lastQuestion = "";
function askView() {
  const v = el("div", { class: "view", id: "askview" });
  if (!lastAnswer) {
    v.append(el("div", { class: "card" }, el("h2", {}, "Ask anything"),
      el("p", { class: "muted" }, "One question goes to every part of QueryBook at once: word meanings and translations, calculations and conversions, history, the shared facts and the bulk datasets on your data drive. Every answer line says where it came from."),
      el("div", { class: "tiles" }, ["When was the printing press invented?", "What does obsequious mean?", "60 mph to km/h", "Marie Curie", "molar mass of H2O"].map(q =>
        el("button", { class: "tile", type: "button", onclick: () => ask(q) }, el("b", {}, q))))));
    return v;
  }
  const r = lastAnswer;
  if (r.loading) { v.append(el("div", { class: "card" }, el("p", { class: "muted" }, `Asking every application about “${lastQuestion}”…`))); return v; }
  if (r.error) { v.append(el("div", { class: "card" }, el("p", { class: "note" }, r.error))); return v; }
  v.append(el("div", { class: "card" },
    el("div", { class: "small muted" }, r.question),
    el("div", { class: "short" }, r.short || (r.sections.length ? "Here is what QueryBook holds about this:" : "QueryBook holds nothing on this yet.")),
    el("div", { class: "small muted", style: "margin-top:6px" }, `Asked: ${(r.asked || []).map(nameOf).join(", ") || "nothing"}` +
      ((r.unavailable || []).length ? ` · not answering: ${r.unavailable.map(u => nameOf(u.source)).join(", ")}` : ""))));
  for (const s of r.sections) {
    if (s.kind === "facts") {
      v.append(el("div", { class: "card" }, el("h2", {}, `Facts (${s.items.length})`),
        el("div", { class: "tbl" }, el("table", {}, el("tr", {}, el("th", {}, "Subject"), el("th", {}, "What"), el("th", {}, "Value"), el("th", {}, "Where it came from")),
          s.items.map(f => el("tr", {}, el("td", {}, f.subject || ""), el("td", {}, f.predicate || ""),
            el("td", {}, f.object || f.statement || "", f.date ? el("div", { class: "small muted" }, f.date) : null),
            el("td", {}, f.link ? el("a", { href: f.link, target: "_blank", rel: "noopener" }, f.where || "source") : (f.where || ""),
              f.status ? el("div", {}, el("span", { class: "chip " + f.status }, f.status)) : null,
              f.provenance ? el("div", { class: "small muted" }, f.provenance) : null)))))));
    } else if (s.kind === "word") {
      v.append(el("div", { class: "card" }, el("h2", {}, "Meaning"), s.items.map(it =>
        it.translations ? el("div", { class: "small", style: "margin-top:8px" }, el("b", {}, "Translations: "),
          Object.entries(it.translations).map(([l, w]) => `${l}: ${[].concat(w).slice(0, 3).join(", ")}`).join(" · "))
        : el("div", {}, it.word ? el("div", { class: "short" }, it.word, it.pos ? el("span", { class: "small muted" }, "  " + it.pos) : null) : null,
            el("p", { style: "white-space:pre-wrap;margin:6px 0" }, it.text), it.source ? el("div", { class: "small muted" }, it.source) : null)),
        el("button", { class: "btn ghost", type: "button", style: "margin-top:10px", onclick: () => show("language") }, "Open in Language")));
    } else if (s.kind === "math") {
      v.append(el("div", { class: "card" }, el("h2", {}, "Calculation"), s.items.map(it => el("div", {}, el("div", { class: "short" }, it.text),
        el("div", { class: "small muted" }, (it.exact ? "Exact · " : "") + (it.how || "")))),
        el("button", { class: "btn ghost", type: "button", style: "margin-top:10px", onclick: () => show("stem") }, "Open in STEM")));
    }
  }
  return v;
}
function nameOf(s) { return { stem: "STEM", language: "Language", history: "History & News", commons: "Shared facts", bulk: "Bulk datasets" }[s] || s; }
async function ask(q) {
  q = (q || "").trim(); if (!q) return;
  document.getElementById("askinput").value = q;
  lastQuestion = q; lastAnswer = { loading: true }; show("ask");
  try {
    const res = await fetch("/api/shell/ask?q=" + encodeURIComponent(q));
    lastAnswer = await res.json();
    if (!res.ok) lastAnswer = { error: lastAnswer.error || "QueryBook could not answer." };
  } catch (e) { lastAnswer = { error: "QueryBook is not responding. Is its window still open?" }; }
  if (current === "ask") show("ask");
}
document.getElementById("askform").addEventListener("submit", e => { e.preventDefault(); ask(document.getElementById("askinput").value); });

/* ------------------------------------------------------------------ status */
async function refresh() {
  try {
    status = await (await fetch("/api/shell/status")).json();
  } catch (e) { return; }
  drawRail();
  const a = AREAS.find(x => x.id === current);
  if (a && !a.builtin) {
    const p = prog(a.app);
    const showingWait = !!document.querySelector("#pane .view");
    if ((p.state === "running" && showingWait) || (p.state !== "running" && !showingWait)) show(current);
  }
}
drawRoles(); drawRail(); show(current); refresh();
setInterval(refresh, 3000);
