/* QueryBook reader: a Kindle-style reading simulation with the QueryBook
   panel. Every answer comes from the server's grounded query path; this file
   only presents what the API returns. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = () => $("#app");

const store = {
  get(k, d) { try { const v = localStorage.getItem("qb." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("qb." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const DEFAULTS = { fs: 19, lh: 1.55, margin: 30, theme: "paper", font: "serif", frame: true, flash: false, eink: false };
const S = { me: null, settings: Object.assign({}, DEFAULTS, store.get("settings", {})), convo: {} };

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("on"), ms);
}

async function api(path, { method = "GET", body } = {}) {
  const isForm = body instanceof FormData;
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body && !isForm ? { "Content-Type": "application/json" } : {},
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });
  let j = {};
  try { j = await r.json(); } catch { /* empty body */ }
  if (r.status === 401) { S.me = null; renderLogin(); throw new Error("Please sign in."); }
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

const ICONS = {
  back: '<svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>',
  toc: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10"/></svg>',
  notes: '<svg viewBox="0 0 24 24"><path d="M6 3h9l3 3v15H6z"/><path d="M9 10h6M9 14h6"/></svg>',
  aa: '<svg viewBox="0 0 24 24"><path d="M3 18l5-12 5 12M5 14h6"/><path d="M14 18l3.5-8 3.5 8M15.2 15.5h4.6"/></svg>',
  qb: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.2-4.2"/><path d="M9 11h4M11 9v4"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  send: '<svg viewBox="0 0 24 24"><path d="M4 12l16-8-6 16-2-6z"/></svg>',
  shield: "⛨", info: "i", q: "?",
};

// ------------------------------------------------------------------ boot

async function boot() {
  try {
    S.me = await api("/api/me");
    route();
  } catch {
    renderLogin();
  }
}
window.addEventListener("hashchange", () => S.me && route());

function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const [view, arg] = h.split("/");
  teardownReader();
  if (view === "read" && arg) return openBook(decodeURIComponent(arg));
  if (view === "account") return renderAccount();
  if (view === "admin") return renderAdmin();
  return renderLibrary();
}

// ----------------------------------------------------------------- login

function renderLogin() {
  teardownReader();
  app().innerHTML = `
  <div class="login"><form class="login-card" id="lf">
    <h1 class="wordmark"><b>Query</b>Book</h1>
    <p class="tagline">Ask your book. Every answer is built only from the book's own facts, cites the passage it came from, and never reaches past the page you are on.</p>
    <label class="field">Username<input name="u" autocomplete="username" required></label>
    <label class="field">Password<input name="p" type="password" autocomplete="current-password" required></label>
    <label class="field">Device
      <select name="d"><option value="kindle-paperwhite">E-reader (Paperwhite-class)</option><option value="tablet">Tablet</option><option value="phone">Phone</option><option value="web">Web</option></select>
    </label>
    <div class="err" id="le"></div>
    <button class="btn primary" style="width:100%">Sign in</button>
    <p class="muted small" style="margin:14px 0 0">First start creates <b>reader / reader</b> and an <b>admin</b> account (password set by the operator).</p>
  </form></div>`;
  $("#lf").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      await api("/api/login", { method: "POST", body: { username: f.u.value.trim(), password: f.p.value, device: f.d.value } });
      S.me = await api("/api/me");
      location.hash = "#/library";
      route();
    } catch (err) { $("#le").textContent = err.message; }
  };
}

async function logout() {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  S.me = null;
  location.hash = "";
  renderLogin();
}

function topbar(title) {
  const u = S.me.user;
  const admin = u.roles.includes("operator") || u.roles.includes("author");
  return `<div class="topbar">
    <h1>${esc(title)}</h1><span class="spacer"></span>
    <a class="btn ghost small" href="#/library">Library</a>
    <a class="btn ghost small" href="#/account">Account &amp; privacy</a>
    ${admin ? '<a class="btn ghost small" href="#/admin">Admin</a>' : ""}
    <button class="btn small" id="so">Sign out ${esc(u.username)}</button>
  </div>`;
}
function wireTopbar() { const b = $("#so"); if (b) b.onclick = logout; }

// --------------------------------------------------------------- library

const COVER = ["#3d5a6c", "#6b4e3d", "#4a5d3a", "#5b3f5e", "#7a5230", "#34495e", "#704040", "#2f5d57", "#5c5470", "#6e6331", "#44556b", "#5d4a3a"];
function hash(s) { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }

async function renderLibrary() {
  const desk = (S.me.corpora || []).length ? `<section class="world-desk"><div class="lib-head"><h2>World knowledge</h2><span class="muted small">${esc(S.me.corpora.join(", "))}</span></div>
    <form id="wf" class="row"><input id="wq" placeholder="Ask the fact store — e.g. What is the capital of France?" autocomplete="off"><button class="btn">Ask</button></form><div id="wa"></div></section>` : "";
  app().innerHTML = topbar("QueryBook") + `<main class="library">${desk}<div class="lib-head"><h2>Your library</h2><span class="muted small" id="lc"></span></div><div class="shelf" id="shelf"><div class="muted">Loading…</div></div></main>`;
  wireTopbar();
  if (desk) wireWorldDesk();
  const { works } = await api("/api/library");
  $("#lc").textContent = `${works.length} book${works.length === 1 ? "" : "s"}`;
  if (!works.length) {
    $("#shelf").outerHTML = `<div class="empty">No books yet.<br>An operator adds books with <code>qb ingest</code> or from the Admin page.</div>`;
    return;
  }
  $("#shelf").innerHTML = works.map(({ work: w, progress: p }) => {
    const pct = w.positions ? Math.min(100, Math.round((p.pos / Math.max(1, w.positions - 1)) * 100)) : 0;
    const bg = COVER[hash(w.title) % COVER.length];
    return `<button class="book" data-id="${esc(w.id)}" aria-label="Open ${esc(w.title)}">
      <div class="cover" style="background:${bg}"><div><div class="t">${esc(w.title)}</div></div><div><div class="a">${esc(w.author || "")}</div><div class="cv-badge">QueryBook · ${w.facts.toLocaleString()} facts</div></div></div>
      <div class="meta">${pct}% read${w.rights === "public-domain" ? " · public domain" : ""}</div><div class="bar"><i style="width:${pct}%"></i></div>
    </button>`;
  }).join("");
  $$(".book").forEach((b) => (b.onclick = () => { location.hash = "#/read/" + encodeURIComponent(b.dataset.id); }));
}

function wireWorldDesk() {
  $("#wf").onsubmit = async (e) => {
    e.preventDefault();
    const q = $("#wq").value.trim();
    if (!q) return;
    const out = $("#wa");
    out.innerHTML = `<div class="muted small">Asking…</div>`;
    try {
      const a = await api("/api/query", { method: "POST", body: { work: "world", mode: "ask", query: q } });
      const byN = Object.fromEntries(a.citations.map((c) => [c.n, c]));
      const lines = a.lines.map((l) => `<p class="a-line">${esc(l.text)} ${l.cites.map((n) => `<button class="cite" data-inspect="${esc(byN[n]?.fuid || "")}" title="Inspect record">${n}</button>`).join("")}</p>`).join("");
      out.innerHTML = `<div class="a-card"><div class="muted small">${esc(q)}</div>${lines || `<p class="muted">No grounded answer in the fact store.</p>`}
        <div class="muted small">${a.citations.length} record${a.citations.length === 1 ? "" : "s"} cited · ${a.ms} ms · output hash <span class="mono">${esc(a.output_hash.slice(0, 16))}</span></div></div>`;
      out.onclick = (ev) => { if (ev.target.dataset.inspect) inspect(ev.target.dataset.inspect); };
    } catch (err) { out.innerHTML = `<div class="muted">${esc(err.message)}</div>`; }
  };
}

// ---------------------------------------------------------------- reader

let R = null;

function teardownReader() {
  if (!R) return;
  window.removeEventListener("keydown", R.onKey);
  window.removeEventListener("resize", R.onResize);
  clearTimeout(R.saveT);
  hidePopover();
  R = null;
}

async function openBook(id) {
  app().innerHTML = `<div class="loading-page">Opening…</div>`;
  const data = await api(`/api/works/${encodeURIComponent(id)}`);
  const w = data.work;
  R = {
    id, work: w, chapters: Array.isArray(w.chapters) ? w.chapters : [], progress: data.progress, mastery: data.mastery,
    cache: {}, ch: 0, page: 0, pages: 1, chrome: false, panel: window.innerWidth > 900, world: false,
    annotations: [], sheet: null,
  };
  if (!S.convo[id]) S.convo[id] = [];
  R.convo = S.convo[id];
  try { R.annotations = (await api(`/api/works/${encodeURIComponent(id)}/annotations`)).annotations; } catch { R.annotations = []; }
  renderReaderShell();
  const saved = store.get("loc." + id, null);
  const start = saved != null ? saved : (R.chapters[0]?.start ?? 0);
  await goToPos(start, false);
  if (R.panel) openPanel();
}

function chapterForPos(pos) {
  let c = 0;
  for (const ch of R.chapters) if (ch.start <= pos) c = ch.index;
  return c;
}

function renderReaderShell() {
  const s = S.settings;
  app().innerHTML = `
  <div class="reader ${s.frame && window.innerWidth > 900 ? "framed" : ""}" id="reader">
    <div class="device">
      <div class="screen ${esc(s.theme)} ${s.eink ? "eink" : ""}" id="screen">
        <header class="chrome top">
          <button class="icon" id="rb" title="Library" aria-label="Back to library">${ICONS.back}</button>
          <button class="icon" id="rt" title="Contents" aria-label="Contents">${ICONS.toc}</button>
          <div class="title">${esc(R.work.title)}</div>
          <button class="icon" id="rn" title="Notes &amp; highlights" aria-label="Notes and highlights">${ICONS.notes}</button>
          <button class="icon" id="ra" title="Display" aria-label="Display settings">${ICONS.aa}</button>
          <button class="icon" id="rq" title="QueryBook" aria-label="Open QueryBook">${ICONS.qb}</button>
        </header>
        <div class="viewport" id="vp"><div class="flow" id="flow"></div></div>
        <footer class="status"><span id="st-l"></span><span id="st-r"></span><i class="progress-line" id="st-bar"></i></footer>
      </div>
    </div>
    <aside class="qb hidden" id="qb" aria-label="QueryBook"></aside>
  </div>`;
  applySettings();
  $("#rb").onclick = () => { location.hash = "#/library"; };
  $("#rt").onclick = () => toggleSheet("toc");
  $("#rn").onclick = () => toggleSheet("notes");
  $("#ra").onclick = () => toggleSheet("settings");
  $("#rq").onclick = () => (R.panel ? closePanel() : openPanel());
  const vp = $("#vp");
  vp.addEventListener("click", onPageClick);
  vp.addEventListener("mouseup", () => setTimeout(checkSelection, 10));
  vp.addEventListener("touchend", () => setTimeout(checkSelection, 300));
  let tx = null;
  vp.addEventListener("touchstart", (e) => { tx = e.touches[0].clientX; }, { passive: true });
  vp.addEventListener("touchend", (e) => {
    if (tx == null) return;
    const dx = e.changedTouches[0].clientX - tx;
    tx = null;
    if (Math.abs(dx) > 50 && !hasSelection()) turn(dx < 0 ? 1 : -1);
  });
  R.onKey = (e) => {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) return;
    if (["ArrowRight", "PageDown", " "].includes(e.key)) { e.preventDefault(); turn(1); }
    if (["ArrowLeft", "PageUp"].includes(e.key)) { e.preventDefault(); turn(-1); }
    if (e.key === "Escape") { hidePopover(); closeSheet(); }
  };
  R.onResize = debounce(() => relayout(), 150);
  window.addEventListener("keydown", R.onKey);
  window.addEventListener("resize", R.onResize);
}

function applySettings() {
  const s = S.settings;
  const flow = $("#flow");
  if (!flow) return;
  flow.style.setProperty("--fs", s.fs + "px");
  flow.style.setProperty("--lh", s.lh);
  flow.style.setProperty("--read-font", s.font === "sans" ? "var(--sans)" : "var(--serif)");
  const screen = $("#screen");
  screen.className = `screen ${s.theme} ${s.eink ? "eink" : ""} ${R && R.chrome ? "show-chrome" : ""}`;
  $("#reader").classList.toggle("framed", s.frame && window.innerWidth > 900);
}

function hasSelection() { const s = window.getSelection(); return s && !s.isCollapsed && s.toString().trim().length > 0; }

function onPageClick(e) {
  if (hasSelection() || e.target.closest("mark,.popover")) return;
  const vp = $("#vp").getBoundingClientRect();
  const x = (e.clientX - vp.left) / vp.width;
  if (x < 0.28) turn(-1);
  else if (x > 0.72) turn(1);
  else { R.chrome = !R.chrome; $("#screen").classList.toggle("show-chrome", R.chrome); }
}

async function loadChapter(ch) {
  if (!R.cache[ch]) R.cache[ch] = (await api(`/api/works/${encodeURIComponent(R.id)}/chapter/${ch}`)).passages;
  return R.cache[ch];
}

function highlightHtml(p) {
  let html = esc(p.text);
  const notes = [];
  for (const a of R.annotations.filter((a) => a.pos === p.pos)) {
    if (a.kind === "highlight" && a.text) {
      const t = esc(a.text);
      const i = html.indexOf(t);
      if (i >= 0) html = html.slice(0, i) + `<mark class="hl ${esc(a.color || "yellow")}" data-fuid="${esc(a.fuid)}">${t}</mark>` + html.slice(i + t.length);
    }
    if (a.kind === "note") notes.push(a);
  }
  if (notes.length) html += notes.map((n) => `<span class="note-dot" title="${esc(n.note)}"></span>`).join("");
  return html;
}

async function renderChapter(ch) {
  const passages = await loadChapter(ch);
  R.ch = ch;
  const flow = $("#flow");
  let first = true;
  flow.innerHTML = passages.map((p) => {
    if (p.kind === "h") { first = true; return `<h2 data-qb-pos="${p.pos}" data-qb-chapter="${ch}">${esc(p.text)}</h2>`; }
    const cls = first ? ' class="first"' : "";
    first = false;
    return `<p${cls} data-qb-pos="${p.pos}" data-qb-chapter="${ch}">${highlightHtml(p)}</p>`;
  }).join("") + `<span class="end" style="display:inline-block;width:1px;height:1px"></span>`;
  R.chWords = passages.reduce((n, p) => n + p.text.split(/\s+/).length, 0);
  measure();
}

function measure() {
  const vp = $("#vp");
  const flow = $("#flow");
  const M = S.settings.margin;
  const W = Math.max(200, vp.clientWidth - 2 * M);
  const G = 2 * M;
  vp.style.padding = `0 ${M}px`;
  flow.style.width = W + "px";
  flow.style.columnWidth = W + "px";
  flow.style.columnGap = G + "px";
  flow.style.transform = "translateX(0)";
  R.W = W; R.G = G;
  const fr = flow.getBoundingClientRect();
  const end = $(".end", flow).getBoundingClientRect();
  R.pages = Math.max(1, Math.floor((end.left - fr.left + 1) / (W + G)) + 1);
}

function pageOfEl(el) {
  const fr = $("#flow").getBoundingClientRect();
  const r = el.getClientRects()[0] || el.getBoundingClientRect();
  return Math.max(0, Math.floor((r.left - fr.left + 2) / (R.W + R.G)));
}

function firstVisiblePos() {
  const fr = $("#flow").getBoundingClientRect();
  const lo = R.page * (R.W + R.G) - 2, hi = lo + R.W + 4;
  for (const el of $$("[data-qb-pos]", $("#flow"))) {
    for (const r of el.getClientRects()) {
      const x = r.left - fr.left;
      if (x >= lo && x < hi) return +el.dataset.qbPos;
    }
  }
  return R.chapters[R.ch]?.start ?? 0;
}

function showPage(p) {
  R.page = Math.max(0, Math.min(p, R.pages - 1));
  $("#flow").style.transform = `translateX(${-R.page * (R.W + R.G)}px)`;
  if (S.settings.flash) {
    const f = document.createElement("div");
    f.className = "eink-flash";
    $("#screen").appendChild(f);
    setTimeout(() => f.remove(), 140);
  }
  updateStatus();
}

function updateStatus() {
  const pos = firstVisiblePos();
  R.pos = pos;
  const total = Math.max(1, R.work.positions);
  const pct = Math.round((pos / Math.max(1, total - 1)) * 100);
  const ch = R.chapters[R.ch];
  const left = Math.max(0, R.pages - R.page - 1);
  const mins = Math.round((left * (R.chWords / Math.max(1, R.pages))) / 250);
  $("#st-l").textContent = ch ? ch.title.slice(0, 60) : "";
  $("#st-r").textContent = `Loc ${pos + 1} of ${total} · ${pct}%${left ? ` · ${mins < 1 ? "<1" : mins} min left in chapter` : ""}`;
  $("#st-bar").style.width = pct + "%";
  store.set("loc." + R.id, pos);
  clearTimeout(R.saveT);
  R.saveT = setTimeout(saveProgress, 1200);
  const sl = $("#scope-line");
  if (sl) sl.innerHTML = scopeLine();
}

async function saveProgress() {
  if (!R) return;
  try {
    const { progress } = await api(`/api/works/${encodeURIComponent(R.id)}/progress`, { method: "POST", body: { pos: R.pos } });
    R.progress = progress;
    const sl = $("#scope-line");
    if (sl) sl.innerHTML = scopeLine();
  } catch { /* offline: retried on next page turn */ }
}

async function turn(d) {
  hidePopover();
  const n = R.page + d;
  if (n >= 0 && n < R.pages) return showPage(n);
  const next = R.ch + d;
  if (next < 0 || next >= R.chapters.length) { toast(d > 0 ? "End of book" : "Beginning of book"); return; }
  await renderChapter(next);
  showPage(d > 0 ? 0 : R.pages - 1);
}

async function goToPos(pos, flash = true) {
  const ch = chapterForPos(pos);
  if (ch !== R.ch || !$("#flow").children.length) await renderChapter(ch);
  const el = $(`[data-qb-pos="${pos}"]`, $("#flow"));
  showPage(el ? pageOfEl(el) : 0);
  if (el && flash) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
}

async function relayout() {
  if (!R || !$("#flow")) return;
  const pos = R.pos ?? firstVisiblePos();
  applySettings();
  measure();
  const el = $(`[data-qb-pos="${pos}"]`, $("#flow"));
  showPage(el ? pageOfEl(el) : 0);
}

// selection → highlight / note / ask
function checkSelection() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return hidePopover();
  const text = sel.toString().trim();
  if (!text || text.length > 2000) return hidePopover();
  const node = sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
  const pEl = node && node.closest("[data-qb-pos]");
  if (!pEl || !$("#flow").contains(pEl)) return hidePopover();
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  showPopover(rect, +pEl.dataset.qbPos, text);
}

function showPopover(rect, pos, text) {
  hidePopover();
  const pop = document.createElement("div");
  pop.className = "popover";
  pop.id = "pop";
  pop.innerHTML = `
    <button class="sw" style="background:var(--hl-yellow)" data-c="yellow" aria-label="Yellow highlight"></button>
    <button class="sw" style="background:var(--hl-blue)" data-c="blue" aria-label="Blue highlight"></button>
    <button class="sw" style="background:var(--hl-pink)" data-c="pink" aria-label="Pink highlight"></button>
    <button data-a="note">Note</button><button data-a="ask">Ask QueryBook</button><button data-a="copy">Copy</button>`;
  document.body.appendChild(pop);
  const w = pop.offsetWidth;
  pop.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, rect.left + rect.width / 2 - w / 2)) + "px";
  pop.style.top = Math.max(8, rect.top - 52) + "px";
  pop.onmousedown = (e) => e.preventDefault();
  pop.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.c) await annotate({ kind: "highlight", pos, text, color: b.dataset.c });
    if (b.dataset.a === "note") {
      const note = prompt("Note on this passage:");
      if (note && note.trim()) await annotate({ kind: "note", pos, text, note: note.trim() });
    }
    if (b.dataset.a === "ask") {
      const words = text.split(/\s+/);
      const named = words.length <= 4 && /^[A-Z]/.test(text);
      openPanel();
      ask({ mode: "ask", query: named ? `Who is ${text}?` : text, label: named ? `Who is ${text}?` : `“${text.length > 120 ? text.slice(0, 120) + "…" : text}”` });
    }
    if (b.dataset.a === "copy") { navigator.clipboard?.writeText(text); toast("Copied"); }
    window.getSelection().removeAllRanges();
    hidePopover();
  };
}
function hidePopover() { const p = $("#pop"); if (p) p.remove(); }

async function annotate(body) {
  try {
    const { annotation } = await api(`/api/works/${encodeURIComponent(R.id)}/annotations`, { method: "POST", body });
    R.annotations.push(annotation);
    const pos = R.pos;
    await renderChapter(R.ch);
    const el = $(`[data-qb-pos="${pos}"]`, $("#flow"));
    showPage(el ? pageOfEl(el) : R.page);
    toast(body.kind === "note" ? "Note saved (visible only to you)" : "Highlighted (visible only to you)");
    if (R.sheet === "notes") renderSheet();
  } catch (e) { toast(e.message); }
}

// sheets: contents / notes / display
function toggleSheet(kind) { if (R.sheet === kind) closeSheet(); else { R.sheet = kind; renderSheet(); } }
function closeSheet() { R && (R.sheet = null); const s = $("#sheet"); if (s) s.remove(); }

function renderSheet() {
  const old = $("#sheet");
  if (old) old.remove();
  const el = document.createElement("div");
  el.id = "sheet";
  const k = R.sheet;
  if (k === "toc") {
    el.className = "sheet left";
    const far = R.progress.pos;
    el.innerHTML = `<div class="sheet-head"><h3>Contents</h3><button class="icon" data-x>${ICONS.close}</button></div>
      <div class="sheet-body toc">${R.chapters.map((c) => `<a href="#" data-pos="${c.start}" class="${c.index === R.ch ? "cur" : ""} ${R.progress.spoiler && c.start > far ? "ahead" : ""}"><span>${esc(c.title)}</span><span class="muted small">${c.start + 1}</span></a>`).join("")}</div>`;
  } else if (k === "notes") {
    el.className = "sheet left";
    const list = R.annotations.length
      ? R.annotations.map((a) => `<div style="border-bottom:1px solid var(--rule);padding:9px 2px">
          <div class="row"><span class="badge ${a.kind === "note" ? "info" : "ok"}">${a.kind}</span><span class="muted small">Loc ${a.pos + 1}</span><span class="spacer"></span>
          <button class="btn small" data-pos="${a.pos}">Go</button><button class="btn small" data-del="${esc(a.fuid)}">Erase</button></div>
          ${a.text ? `<div style="font-family:var(--serif);margin-top:6px">“${esc(a.text)}”</div>` : ""}${a.note ? `<div style="margin-top:4px">${esc(a.note)}</div>` : ""}</div>`).join("")
      : `<p class="muted">Select text on the page to highlight it or add a note. Notes are stored as your own records, visible only to you.</p>`;
    el.innerHTML = `<div class="sheet-head"><h3>Notes &amp; highlights</h3><button class="icon" data-x>${ICONS.close}</button></div><div class="sheet-body">${list}</div>`;
  } else {
    el.className = "sheet settings";
    const s = S.settings;
    const seg = (key, opts) => `<div class="seg">${opts.map(([v, l]) => `<button data-set="${key}" data-v="${v}" class="${String(s[key]) === String(v) ? "on" : ""}">${l}</button>`).join("")}</div>`;
    el.innerHTML = `<div class="sheet-head"><h3>Display</h3><button class="icon" data-x>${ICONS.close}</button></div><div class="sheet-body">
      <div class="set-row">Text size<div class="row"><button class="btn small" data-fs="-1">A−</button><span style="min-width:48px;text-align:center">${s.fs}px</span><button class="btn small" data-fs="1">A+</button></div></div>
      <div class="set-row">Theme ${seg("theme", [["paper", "Paper"], ["sepia", "Sepia"], ["night", "Night"]])}</div>
      <div class="set-row">Font ${seg("font", [["serif", "Serif"], ["sans", "Sans"]])}</div>
      <div class="set-row">Line spacing ${seg("lh", [[1.35, "Tight"], [1.55, "Normal"], [1.8, "Loose"]])}</div>
      <div class="set-row">Margins ${seg("margin", [[18, "Narrow"], [30, "Normal"], [48, "Wide"]])}</div>
      <label class="switch">Show e-reader frame <input type="checkbox" data-sw="frame" ${s.frame ? "checked" : ""}></label>
      <label class="switch">E-ink page refresh flash <input type="checkbox" data-sw="flash" ${s.flash ? "checked" : ""}></label>
      <label class="switch">Grayscale e-ink screen <input type="checkbox" data-sw="eink" ${s.eink ? "checked" : ""}></label>
    </div>`;
  }
  $("#screen").appendChild(el);
  el.onclick = async (e) => {
    const t = e.target.closest("[data-x],[data-pos],[data-del],[data-set],[data-fs]");
    if (!t) return;
    e.preventDefault();
    if (t.dataset.x !== undefined) return closeSheet();
    if (t.dataset.pos) { closeSheet(); return goToPos(+t.dataset.pos); }
    if (t.dataset.del) {
      await api(`/api/annotations/${t.dataset.del}`, { method: "DELETE" });
      R.annotations = R.annotations.filter((a) => a.fuid !== t.dataset.del);
      toast("Erased. The ledger records that an erasure happened, not what it was.");
      await relayoutChapter();
      return renderSheet();
    }
    if (t.dataset.fs) S.settings.fs = Math.max(13, Math.min(32, S.settings.fs + +t.dataset.fs));
    if (t.dataset.set) S.settings[t.dataset.set] = isNaN(+t.dataset.v) ? t.dataset.v : +t.dataset.v;
    store.set("settings", S.settings);
    await relayout();
    renderSheet();
  };
  el.onchange = async (e) => {
    const t = e.target.closest("[data-sw]");
    if (!t) return;
    S.settings[t.dataset.sw] = t.checked;
    store.set("settings", S.settings);
    await relayout();
  };
}

async function relayoutChapter() {
  const pos = R.pos;
  await renderChapter(R.ch);
  const el = $(`[data-qb-pos="${pos}"]`, $("#flow"));
  showPage(el ? pageOfEl(el) : 0);
}

// --------------------------------------------------------- QueryBook panel

function exempt() { return S.me.user.roles.some((r) => ["author", "instructor", "researcher"].includes(r)); }

function scopeLine() {
  const bound = exempt()
    ? "across the <b>whole book</b> (the spoiler shield does not apply to authors, instructors and researchers)"
    : R.progress.spoiler ? `up to <b>Loc ${Math.max(R.progress.pos, R.pos ?? 0) + 1}</b> (where you have read)` : "across the <b>whole book</b>";
  return `Answers come only from this book’s own records, ${bound}.${R.world ? " World knowledge is included and labelled." : ""}`;
}

function openPanel() {
  R.panel = true;
  const p = $("#qb");
  p.classList.remove("hidden");
  const worldToggle = (S.me.corpora || []).length ? `<button class="tog ${R.world ? "on" : ""}" id="tw"><span class="dot"></span>World knowledge</button>` : "";
  p.innerHTML = `
    <div class="qb-grip"></div>
    <div class="qb-head">
      <div class="qb-brand"><span class="logo">Q</span><h3>QueryBook</h3><button class="icon" id="qx" aria-label="Close QueryBook">${ICONS.close}</button></div>
      <div class="scope-line" id="scope-line">${scopeLine()}</div>
      <div class="toggles">${exempt() ? "" : `<button class="tog ${R.progress.spoiler ? "on" : ""}" id="ts"><span class="dot"></span>Spoiler shield</button>`}${worldToggle}</div>
    </div>
    <div class="chips">
      <button class="chip" data-m="who">Who’s who</button>
      <button class="chip" data-m="recap">Story so far</button>
      <button class="chip" data-m="summary">This chapter</button>
      <button class="chip" data-m="timeline">Timeline</button>
      <button class="chip" data-m="flashcards">Flashcards</button>
      <button class="chip" data-m="quiz">Quiz me</button>
    </div>
    <div class="convo" id="convo"></div>
    <form class="qb-input" id="qf"><textarea id="qi" rows="1" placeholder="Ask about this book…" aria-label="Ask about this book"></textarea><button class="icon" aria-label="Ask">${ICONS.send}</button></form>`;
  $("#qx").onclick = closePanel;
  if ($("#ts")) $("#ts").onclick = async () => {
    const { progress } = await api(`/api/works/${encodeURIComponent(R.id)}/progress`, { method: "POST", body: { spoiler: !R.progress.spoiler } });
    R.progress = progress;
    $("#ts").classList.toggle("on", progress.spoiler);
    $("#scope-line").innerHTML = scopeLine();
    toast(progress.spoiler ? "Spoiler shield on: nothing past your reading position can be retrieved." : "Spoiler shield off: answers may draw on the whole book.");
  };
  const tw = $("#tw");
  if (tw) tw.onclick = () => { R.world = !R.world; tw.classList.toggle("on", R.world); $("#scope-line").innerHTML = scopeLine(); };
  $$(".chip", p).forEach((c) => (c.onclick = () => {
    const m = c.dataset.m;
    ask({ mode: m, chapter: m === "summary" ? R.ch : undefined, label: c.textContent });
  }));
  const qi = $("#qi");
  qi.addEventListener("input", () => { qi.style.height = "auto"; qi.style.height = Math.min(120, qi.scrollHeight) + "px"; });
  qi.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#qf").requestSubmit(); } });
  $("#qf").onsubmit = (e) => {
    e.preventDefault();
    const q = qi.value.trim();
    if (!q) return;
    qi.value = "";
    qi.style.height = "auto";
    ask({ mode: "ask", query: q, label: q });
  };
  renderConvo();
  if (window.innerWidth > 900) setTimeout(() => relayout(), 30);
}

function closePanel() {
  R.panel = false;
  $("#qb").classList.add("hidden");
  if (window.innerWidth > 900) setTimeout(() => relayout(), 30);
}

async function renderConvo() {
  const c = $("#convo");
  if (!c) return;
  if (!R.convo.length) {
    let qs = [];
    try { qs = (await api(`/api/works/${encodeURIComponent(R.id)}/suggested`)).questions; } catch { /* none */ }
    c.innerHTML = `<div class="a-card"><p style="margin:0 0 10px">Ask anything about <i>${esc(R.work.title)}</i>. QueryBook answers only from the book’s own facts and cites the passage behind every sentence. Tap a number to see the source.</p>
      ${qs.length ? `<div class="muted small" style="margin-bottom:6px">Readers often ask</div><div class="suggest">${qs.map((q) => `<button data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}</div>`;
    $$("[data-q]", c).forEach((b) => (b.onclick = () => ask({ mode: "ask", query: b.dataset.q, label: b.dataset.q })));
    return;
  }
  c.innerHTML = R.convo.map((t, i) => `<div class="q-bubble">${esc(t.label)}</div>${t.pending ? `<div class="a-card thinking"><i></i><i></i><i></i> Retrieving and stabilizing records…</div>` : t.error ? `<div class="a-card">${esc(t.error)}</div>` : renderAnswer(t.answer, i)}`).join("");
  wireAnswers(c);
  c.scrollTop = c.scrollHeight;
}

async function ask({ mode, query = "", chapter, focus, label }) {
  if (!R.panel) openPanel();
  const turnObj = { label: label || query, pending: true };
  R.convo.push(turnObj);
  renderConvo();
  try {
    turnObj.answer = await api("/api/query", { method: "POST", body: { work: R.id, mode, query, chapter, focus, at: R.pos, world: R.world } });
  } catch (e) { turnObj.error = e.message; }
  turnObj.pending = false;
  renderConvo();
}

function cites(ns) { return ns.map((n) => `<button class="cite" data-n="${n}">${n}</button>`).join(""); }
function lineHtml(l) { return `<p class="a-line">${esc(l.text)}${cites(l.cites)}</p>`; }

function renderAnswer(a, i) {
  let body = "";
  if (a.status === "clarify") {
    body += `<div class="status-msg clarify"><span class="ic">${ICONS.q}</span><div>${esc(a.clarify?.question || "Which one do you mean?")}
      <div class="opts">${(a.clarify?.options || []).map((o) => `<button class="btn small" data-focus="${esc(o.concept)}" data-label="${esc(o.label)}" data-q="${esc(a.query)}">${esc(o.label)}</button>`).join("")}</div></div></div>`;
  } else if (a.status === "beyond-position") {
    body += `<div class="status-msg beyond"><span class="ic">${ICONS.shield}</span><div>${esc(a.message)}</div></div>`;
  } else if (a.status === "not-in-book") {
    body += `<div class="status-msg none"><span class="ic">${ICONS.info}</span><div>${esc(a.message || "The book doesn’t say.")}</div></div>`;
  }
  body += a.lines.map(lineHtml).join("");
  for (const s of a.sections) {
    body += `<h4>${s.title.length < 60 && a.mode === "who" ? `<a href="#" data-explore="${esc(s.title)}">${esc(s.title)}</a>` : esc(s.title)}</h4>` + s.lines.map(lineHtml).join("");
  }
  if (a.neighbors.length) body += `<h4>Connected in the book</h4><div class="neighbors">${a.neighbors.map((n) => `<button class="chip" data-focus-explore="${esc(n.concept)}" data-label="${esc(n.label)}">${esc(n.label)} · ${n.strength}</button>`).join("")}</div>`;
  if (a.cards.length) {
    body += `<div class="cards">${a.cards.map((c, k) => `<div class="card"><div class="card-inner"><div class="card-front">${esc(c.front)}</div>
      <div class="card-back hidden" id="cb-${i}-${k}">${esc(c.back)}${cites([c.cite])}<div class="grade">${[["Again", 1], ["Hard", 3], ["Good", 4], ["Easy", 5]].map(([l, q]) => `<button class="btn small" data-grade="${q}" data-fuid="${esc(c.fuid)}">${l}</button>`).join("")}</div></div>
      <button class="btn small" style="margin-top:8px" data-flip="cb-${i}-${k}">Show answer</button></div></div>`).join("")}</div>`;
  }
  if (a.quiz.length) {
    body += a.quiz.map((q, k) => `<p class="quiz-q">${k + 1}. ${esc(q.prompt)}</p><div class="quiz-opts" data-ans="${q.answer}" data-cite="${q.cite}">${q.options.map((o, j) => `<button data-j="${j}">${esc(o)}</button>`).join("")}</div>`).join("");
  }
  if (a.status === "answered" && !a.lines.length && !a.sections.length && !a.cards.length && !a.quiz.length && !a.neighbors.length) {
    body += `<div class="status-msg none"><span class="ic">${ICONS.info}</span><div>Nothing grounded to show for this yet.</div></div>`;
  }
  const cv = a.convergence;
  const why = `<details class="why"><summary><span class="badge ${a.served_from === "precomputed" ? "info" : "ok"}">${a.served_from === "precomputed" ? "pre-computed" : "live"}</span>
      <span>${a.citations.length} record${a.citations.length === 1 ? "" : "s"} cited · ${a.ms} ms</span><span class="spacer"></span><span>Why this answer ▾</span></summary>
      <dl class="kv"><dt>Scope</dt><dd>${esc(a.scope.work)} ${a.scope.spoiler_bounded ? `· positions ≤ ${a.scope.marker + 1}` : "· whole work"}${a.scope.corpora.length ? " · " + esc(a.scope.corpora.join(", ")) : ""}</dd>
      <dt>Regime</dt><dd>${esc(a.regime)}</dd>
      ${cv ? `<dt>Convergence</dt><dd>${cv.units} units → ${cv.retained} retained · ${cv.iterations} iterations · residual ${cv.residual.toExponential(1)} · ‖W‖ ${cv.weight_norm}</dd>` : ""}
      <dt>Candidates</dt><dd>${a.candidates}${a.rejected_propositions ? ` · ${a.rejected_propositions} proposition(s) rejected as not derivable` : ""}</dd>
      <dt>Context key</dt><dd class="mono">${esc(a.context_key.slice(0, 24))}…</dd>
      <dt>Output hash</dt><dd class="mono">${esc(a.output_hash.slice(0, 24))}… <span class="muted">(same key + same question ⇒ same bytes)</span></dd></dl>
      ${a.fql ? `<div>FQL executed</div><pre>${esc(a.fql)}</pre>` : ""}
      ${a.trace.length ? `<div>Domain crossings</div><pre>${esc(a.trace.join("\n"))}</pre>` : ""}</details>`;
  return `<div class="a-card" data-i="${i}">${body}${why}</div>`;
}

function citation(i, n) { return R.convo[i]?.answer?.citations.find((c) => c.n === n); }

function previewHtml(c) {
  const conf = Math.round(c.confidence * 100);
  const where = c.work ? `Loc ${c.pos + 1}${c.chapter_title ? " · " + esc(c.chapter_title) : ""}` : `<span class="badge warn">outside this book</span> ${esc(c.corpus)}`;
  return `<div class="preview"><blockquote>“${esc(c.quote || c.rendered)}”</blockquote>
    <div class="row small"><span>${where}</span></div>
    <div class="row small" style="margin-top:6px"><span>Confidence</span><span class="meter"><i style="width:${conf}%"></i></span><span>${conf}%</span><span class="muted">trust ${c.trust.toFixed(2)}</span></div>
    <div class="row small" style="margin-top:6px">
      <span class="badge ${c.verified ? "ok" : "warn"}">${c.verified ? "quote verified" : "quote unverified"}</span>
      <span class="badge info">${esc(c.engine)}</span>
      <span class="muted">${c.diversity.toFixed(1)} source class${c.diversity >= 1.5 ? "es" : ""}${c.restated ? ` · restated ${c.restated}×` : ""}</span>
      ${c.safety !== "general" ? `<span class="badge warn">${esc(c.safety)}</span>` : ""}
    </div>
    <div class="row" style="margin-top:8px">${c.work ? `<button class="btn small" data-go="${c.pos}">Go to passage</button>` : ""}<button class="btn small" data-inspect="${esc(c.fuid)}">Inspect record</button></div></div>`;
}

function wireAnswers(root) {
  root.onclick = async (e) => {
    const t = e.target;
    const card = t.closest(".a-card");
    const i = card ? +card.dataset.i : -1;
    if (t.classList.contains("cite")) {
      const line = t.closest(".a-line, .card-back, .quiz-opts") || t.parentElement;
      const n = +t.dataset.n;
      const existing = line.nextElementSibling;
      if (existing && existing.classList.contains("preview") && existing.dataset.n == n) { existing.remove(); t.classList.remove("on"); return; }
      if (existing && existing.classList.contains("preview")) existing.remove();
      $$(".cite.on", line).forEach((x) => x.classList.remove("on"));
      const c = citation(i, n);
      if (!c) return;
      t.classList.add("on");
      line.insertAdjacentHTML("afterend", previewHtml(c));
      line.nextElementSibling.dataset.n = n;
      return;
    }
    if (t.dataset.go) { if (window.innerWidth <= 900) closePanel(); return goToPos(+t.dataset.go); }
    if (t.dataset.inspect) return inspect(t.dataset.inspect);
    if (t.dataset.focus) return ask({ mode: "ask", query: t.dataset.q, focus: t.dataset.focus, label: `${t.dataset.q} → ${t.dataset.label}` });
    if (t.dataset.focusExplore) return ask({ mode: "explore", focus: t.dataset.focusExplore, label: `Explore ${t.dataset.label}` });
    if (t.dataset.explore) { e.preventDefault(); return ask({ mode: "explore", query: t.dataset.explore, label: `Explore ${t.dataset.explore}` }); }
    if (t.dataset.flip) { $("#" + t.dataset.flip).classList.remove("hidden"); t.remove(); return; }
    if (t.dataset.grade) {
      const r = await api("/api/study/review", { method: "POST", body: { work: R.id, fuid: t.dataset.fuid, quality: +t.dataset.grade } });
      t.parentElement.innerHTML = `<span class="muted small">Next review in ${r.review.interval_days} day${r.review.interval_days === 1 ? "" : "s"} · ${r.mastery.mastered}/${r.mastery.cards} cards mastered</span>`;
      return;
    }
    if (t.dataset.j !== undefined) {
      const box = t.parentElement;
      if (box.dataset.done) return;
      box.dataset.done = 1;
      const ans = +box.dataset.ans;
      $$("button", box).forEach((b, j) => { if (j === ans) b.classList.add("right"); else if (b === t) b.classList.add("wrong"); });
      box.insertAdjacentHTML("beforeend", `<div class="small muted">${+t.dataset.j === ans ? "Correct." : "Not quite."} Source ${cites([+box.dataset.cite])}</div>`);
    }
  };
}

async function inspect(fuid) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal"><div class="sheet-head"><h3>Fact Unit</h3><button class="icon" data-x>${ICONS.close}</button></div><div class="sheet-body">Loading…</div></div>`;
  document.body.appendChild(back);
  back.onclick = (e) => { if (e.target === back || e.target.closest("[data-x]")) back.remove(); };
  try {
    const d = await api(`/api/facts/${fuid}`);
    const r = d.record, n = d.ledger_node;
    $(".sheet-body", back).innerHTML = `
      <dl class="kv"><dt>FUID</dt><dd class="mono">${esc(r.fuid)}</dd><dt>Fingerprint</dt><dd class="mono">${esc(r.fingerprint)}</dd>
      <dt>Assertion</dt><dd>${esc(r.atom.subject)} · <b>${esc(r.atom.predicate)}</b> · ${esc(JSON.stringify(r.atom.object.v))}${r.atom.polarity ? "" : " (negated)"}</dd>
      <dt>Type</dt><dd>${esc(r.type_ref)} · ${esc(r.modality)} · safety ${esc(r.safety)}</dd>
      ${r.narrative && r.narrative.cfi ? `<dt>Anchor</dt><dd class="mono">${esc(r.narrative.cfi)}${r.narrative.sentence != null ? ` · sentence ${r.narrative.sentence + 1}` : ""}</dd>` : ""}
      <dt>Evidence</dt><dd>α ${r.evidence.alpha.toFixed(2)} · β ${r.evidence.beta.toFixed(2)} → confidence ${(d.confidence * 100).toFixed(1)}% (lower ${(d.lower * 100).toFixed(1)}%), diversity ${d.diversity.toFixed(2)}, trust ${d.trust.toFixed(3)}</dd>
      <dt>Derivation</dt><dd>${esc(r.derivation.kind)}${r.derivation.engine ? " · engine " + esc(r.derivation.engine) : ""}${r.derivation.citation_verified === false ? " · <b>citation unverified</b>" : ""}</dd>
      <dt>Access</dt><dd>${esc(r.acl.join(", "))}</dd>
      <dt>Ledger node</dt><dd>${n ? `#${n.seq} · ${esc(n.op)} · ${esc(n.crossing)} · safety “${esc(n.safety)}” · signed` : "—"}</dd>
      <dt>Merkle proof</dt><dd>${d.merkle.verified ? `<span class="badge ok">verified</span> ${d.merkle.proof_steps} steps over ${d.merkle.leaves} records` : `<span class="badge warn">not verified</span>`}</dd>
      ${d.adjustments.length ? `<dt>Adjustments</dt><dd>${d.adjustments.length} corroboration(s)</dd>` : ""}
      ${d.superseded ? `<dt>Status</dt><dd><span class="badge warn">superseded</span></dd>` : ""}</dl>
      <details><summary class="small">Full record (canonical JSON)</summary><pre>${esc(JSON.stringify(r, null, 2))}</pre></details>`;
  } catch (e) { $(".sheet-body", back).textContent = e.message; }
}

// ------------------------------------------------------ account & privacy

async function renderAccount() {
  app().innerHTML = topbar("QueryBook") + `<main class="page"><h2>Account &amp; privacy</h2>
    <div class="grid2">
      <section class="panel"><h3>Your data</h3><p class="small muted">Your questions are kept by default so you can revisit them; erase them any time. Erasures are recorded in the ledger without their content.</p>
        <div class="row"><button class="btn small" data-er="session">Erase this session</button><button class="btn small" data-er="account">Erase all my history</button><a class="btn small" href="/api/export">Export my data (JSON)</a></div></section>
      <section class="panel"><h3>Provenance ledger</h3><p class="small muted">Every admitted record, election and erasure is a signed, hash-linked ledger node.</p>
        <div class="row"><button class="btn small primary" id="vf">Verify the whole ledger</button><span id="vr" class="small"></span></div></section>
    </div>
    <section class="panel"><h3>Reading history</h3><div class="tbl-wrap" id="hist">Loading…</div></section>
    <section class="panel"><h3>Recent ledger nodes</h3><div class="tbl-wrap" id="led">Loading…</div></section></main>`;
  wireTopbar();
  $$("[data-er]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Erase? This cannot be undone.")) return;
    const r = await api(`/api/history?scope=${b.dataset.er}`, { method: "DELETE" });
    toast(`Erased ${r.erased} item(s)`);
    renderAccount();
  }));
  $("#vf").onclick = async () => {
    $("#vr").textContent = "Verifying…";
    const v = await api("/api/ledger/verify");
    $("#vr").innerHTML = v.first_failure ? `<span class="badge warn">${esc(v.first_failure)}</span>` : `<span class="badge ok">${v.verified}/${v.nodes} nodes verified</span> <span class="mono">key ${esc(v.verifying_key.slice(0, 16))}…</span>`;
  };
  const { history } = await api("/api/history");
  $("#hist").innerHTML = history.length ? `<table class="tbl"><tr><th>When</th><th>Book</th><th>Asked</th><th>Answer</th></tr>${history.map((h) => `<tr><td class="small">${new Date(h.ts * 1000).toLocaleString()}</td><td class="small">${esc(h.work)}</td><td>${esc(h.query)}</td><td class="small">${esc(h.answer.slice(0, 160))}${h.answer.length > 160 ? "…" : ""}</td></tr>`).join("")}</table>` : `<p class="muted">No history.</p>`;
  const { nodes } = await api("/api/ledger");
  $("#led").innerHTML = `<table class="tbl"><tr><th>#</th><th>Operation</th><th>Actor</th><th>Crossing</th><th>Records</th><th>Hash</th></tr>${nodes.map((n) => `<tr><td>${n.seq}</td><td>${esc(n.op)}</td><td class="small">${esc(n.actor)}</td><td class="small">${esc(n.crossing)}</td><td>${n.leaves}</td><td class="mono">${esc(n.hash.slice(0, 12))}…</td></tr>`).join("")}</table>`;
}

// ------------------------------------------------------------------ admin

async function renderAdmin() {
  app().innerHTML = topbar("QueryBook") + `<main class="page"><h2>Administration</h2><div id="adm">Loading…</div></main>`;
  wireTopbar();
  let s;
  try { s = await api("/api/admin/stats"); } catch (e) { $("#adm").textContent = e.message; return; }
  const engineOpts = s.engines.map((e) => `<label class="switch" style="justify-content:flex-start;gap:8px"><input type="checkbox" name="eng" value="${esc(e.id)}" ${e.id === "rules" ? "checked" : ""} ${e.ready ? "" : "disabled"}> ${esc(e.id)} <span class="muted small">${esc(e.kind)}${e.model ? " · " + esc(e.model) : ""}${e.ready ? "" : " · key not set"}</span></label>`).join("");
  $("#adm").innerHTML = `
    <section class="panel"><div class="stats">
      <div class="stat"><b>${s.records.toLocaleString()}</b><span>Fact Units stored</span></div>
      <div class="stat"><b>${s.indexed.toLocaleString()}</b><span>indexed views</span></div>
      <div class="stat"><b>${s.works.length}</b><span>works</span></div>
      <div class="stat"><b>${s.feeds.length}</b><span>UFCS feeds</span></div>
      <div class="stat"><b class="mono" style="font-size:13px">${esc(s.store_version.slice(0, 16))}</b><span>store version</span></div></div>
      <p class="small muted" style="margin:12px 0 0">Convergence: ${esc(s.regime)}</p></section>
    <div class="grid2">
      <section class="panel"><h3>Add a book</h3>
        <form id="up">
          <label class="field">File (EPUB, DOCX, HTML, TXT, Markdown)<input type="file" name="file" required accept=".epub,.docx,.html,.htm,.txt,.md"></label>
          <label class="field">Rights you hold<select name="rights" required><option value="">Choose…</option>${s.rights.map((r) => `<option>${r}</option>`).join("")}</select></label>
          <label class="field">Rights note<input name="rights_note" placeholder="e.g. Project Gutenberg #1342, or contract ref"></label>
          <label class="field">Genre<input name="genre" placeholder="fiction, history, how-to…"></label>
          <div class="field">Extraction engines${engineOpts}</div>
          <label class="switch" style="justify-content:flex-start;gap:8px"><input type="checkbox" name="replace"> Replace an existing copy</label>
          <button class="btn primary">Ingest</button></form></section>
      <section class="panel"><h3>Jobs</h3><div id="jobs" class="tbl-wrap">…</div></section>
    </div>
    <section class="panel"><h3>Works</h3><div class="tbl-wrap"><table class="tbl"><tr><th>Title</th><th>Facts</th><th>Passages</th><th>Rights</th><th>Engines</th><th></th></tr>
      ${s.works.map((w) => `<tr><td>${esc(w.title)}<div class="muted small mono">${esc(w.id)}</div></td><td>${w.facts.toLocaleString()}</td><td>${w.positions.toLocaleString()}</td><td class="small">${esc(w.rights)}</td><td class="small">${esc(w.engines)}</td><td><button class="btn small" data-rq="${esc(w.id)}">Reader questions</button></td></tr>`).join("")}</table></div><div id="rq"></div></section>
    <div class="grid2">
      <section class="panel"><h3>Users</h3><div class="tbl-wrap"><table class="tbl"><tr><th>User</th><th>Roles</th></tr>${s.users.map((u) => `<tr><td>${esc(u.username)}</td><td class="small">${esc(u.roles)}</td></tr>`).join("")}</table></div>
        <form id="nu" class="row" style="margin-top:10px"><input name="username" placeholder="username" required style="flex:1;min-width:110px;padding:7px;border:1px solid var(--rule);border-radius:8px;background:var(--paper)"><input name="password" placeholder="password" required style="flex:1;min-width:110px;padding:7px;border:1px solid var(--rule);border-radius:8px;background:var(--paper)"><select name="roles" style="padding:7px;border-radius:8px;border:1px solid var(--rule);background:var(--paper)"><option>reader</option><option>author</option><option>instructor</option><option>researcher</option><option>operator</option></select><button class="btn small">Add</button></form></section>
      <section class="panel"><h3>UFCS feeds</h3>${s.feeds.length ? `<table class="tbl"><tr><th>Feed</th><th>Imported</th><th>Refused</th><th>Cursor</th></tr>${s.feeds.map((f) => `<tr><td>${esc(f.feed)}</td><td>${f.imported.toLocaleString()}</td><td>${f.refused.toLocaleString()}</td><td class="mono small">${esc(String(f.cursor).slice(0, 18))}</td></tr>`).join("")}</table>` : `<p class="muted small">No feeds yet. Import with <code>qb import-ufcs --mapping feed.toml</code>.</p>`}</section>
    </div>`;
  $("#up").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const fd = new FormData();
    fd.append("file", f.file.files[0]);
    fd.append("rights", f.rights.value);
    fd.append("rights_note", f.rights_note.value);
    fd.append("genre", f.genre.value);
    fd.append("engines", $$('input[name="eng"]:checked', f).map((x) => x.value).join(","));
    if (f.replace.checked) fd.append("replace", "true");
    try { await api("/api/admin/upload", { method: "POST", body: fd }); toast("Ingestion started"); f.reset(); pollJobs(); } catch (err) { toast(err.message); }
  };
  $("#nu").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    try { await api("/api/admin/users", { method: "POST", body: { username: f.username.value, password: f.password.value, roles: f.roles.value } }); toast("User saved"); renderAdmin(); } catch (err) { toast(err.message); }
  };
  $$("[data-rq]").forEach((b) => (b.onclick = async () => {
    const { questions } = await api(`/api/admin/questions/${encodeURIComponent(b.dataset.rq)}`);
    $("#rq").innerHTML = `<h3 style="margin-top:16px">What readers ask · ${esc(b.dataset.rq)}</h3>` + (questions.length ? `<table class="tbl"><tr><th>Question</th><th>Asked</th><th>Readers</th><th>Unanswered</th></tr>${questions.map((q) => `<tr><td>${esc(q.question)}</td><td>${q.asked}</td><td>${q.readers}</td><td>${q.unanswered}</td></tr>`).join("")}</table><p class="small muted">Unanswered questions show where supplemental author material would help.</p>` : `<p class="muted small">No questions yet.</p>`);
  }));
  pollJobs();
}

async function pollJobs() {
  const el = $("#jobs");
  if (!el) return;
  const { jobs } = await api("/api/admin/jobs");
  el.innerHTML = jobs.length ? `<table class="tbl"><tr><th>File</th><th>Status</th><th>Detail</th></tr>${jobs.map((j) => {
    let d = j.detail;
    try { const r = JSON.parse(j.detail); d = `${r.admitted} records · ${r.questions} pre-computed answers · ${r.seconds.toFixed(1)}s`; } catch { /* progress text */ }
    return `<tr><td class="small">${esc(j.label)}</td><td><span class="badge ${j.status === "done" ? "ok" : j.status === "failed" ? "warn" : "info"}">${esc(j.status)}</span></td><td class="small">${esc(d)}</td></tr>`;
  }).join("")}</table>` : `<p class="muted small">No jobs.</p>`;
  if (jobs.some((j) => j.status === "running")) setTimeout(pollJobs, 1500);
}

function debounce(f, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => f(...a), ms); }; }

boot();
