/* QueryBook one window. Each area is either the Ask page (built in) or one of the suite's applications shown in place.
   Applications stay loaded when you switch away, so nothing you typed is lost. */
"use strict";

const AREAS = [
  { band: "Everyday" },
  { id: "ask", name: "Ask", builtin: true },
  { id: "bookquery", name: "📚 Book Query", builtin: true },
  { id: "language", name: "Language", app: "language", hash: "learn" },
  { id: "stem", name: "STEM", app: "stem" },
  { id: "history", name: "History & News", app: "facts" },
  { id: "video", name: "Video Studio", app: "video" },
  { band: "Operate", admin: true },
  { id: "harvest", name: "Harvest", app: "control", hash: "bulk", admin: true },
  { id: "books", name: "Book Harvester", app: "control", hash: "books", admin: true },
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
  if (a.builtin) { pane.append(id === "bookquery" ? bookQueryView() : askView()); if (id !== "bookquery") document.getElementById("askinput").placeholder = "Ask anything — a word, a fact, a calculation"; return; }
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

/* ------------------------------------------------------------------ Ask: askpage.js (askView, ask) */
function nameOf(s) { return { stem: "STEM", language: "Language", history: "History & News", commons: "Shared facts", bulk: "Bulk datasets" }[s] || s; }
document.getElementById("askform").addEventListener("submit", e => { e.preventDefault(); ask(document.getElementById("askinput").value); });

/* ------------------------------------------------------------------ status */
async function refresh() {
  try {
    status = await (await fetch("/api/shell/status")).json();
  } catch (e) { return; }
  drawRail();
  const v = document.getElementById("qbver"); if (v && status.version) v.textContent = status.version;
  const a = AREAS.find(x => x.id === current);
  if (a && !a.builtin) {
    const p = prog(a.app);
    const showingWait = !!document.querySelector("#pane .view");
    if ((p.state === "running" && showingWait) || (p.state !== "running" && !showingWait)) show(current);
  }
}
drawRoles(); drawRail(); show(current); refresh();
setInterval(refresh, 3000);
