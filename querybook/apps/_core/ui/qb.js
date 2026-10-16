// QueryBook dedicated applications — shared page helpers (no libraries).
"use strict";
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let res;
  try { res = await fetch(path, opt); }
  catch (e) { toast("The application is not responding. Is its window still open?", true); throw e; }
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) { const msg = data.error || ("Error " + res.status); toast(msg, true); throw new Error(msg); }
  return data;
}

let toastTimer = null;
function toast(msg, bad) {
  const t = $("#toast");
  if (!t) return;
  t.textContent = msg;
  t.className = "show" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, bad ? 7000 : 3500);
}

function setupTabs(onShow) {
  const tabs = $$("nav.tabs button");
  function show(id) {
    tabs.forEach(b => b.setAttribute("aria-selected", b.dataset.tab === id ? "true" : "false"));
    $$("section.panel").forEach(p => p.classList.toggle("active", p.id === id));
    try { localStorage.setItem(document.title + ":tab", id); } catch (e) { /* storage unavailable */ }
    if (onShow) onShow(id);
  }
  tabs.forEach(b => b.addEventListener("click", () => show(b.dataset.tab)));
  let start = tabs[0].dataset.tab;
  try { const s = localStorage.getItem(document.title + ":tab"); if (s && $("#" + s)) start = s; } catch (e) { /* ignore */ }
  show(start);
  return show;
}

async function refreshFooter() {
  try {
    const s = await api("/api/status");
    const db = s.store || {};
    const parts = [
      "Data: " + esc(db.folder || ""),
      db.read_only ? '<span class="badge bad">Database check failed — read-only</span>' : '<span class="badge good">Database OK</span>',
      "Last backup: " + esc(db.last_backup || "none yet"),
      "Version " + esc(s.version || ""),
    ];
    $("footer.status").innerHTML = parts.map(p => "<span>" + p + "</span>").join("");
  } catch (e) { /* toast already shown */ }
}

function onEnter(input, fn) {
  input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); fn(); } });
}

async function pollJob(el, onDone) {
  const j = await api("/api/job");
  if (j.state === "idle") { el.innerHTML = ""; return; }
  const pct = j.total ? Math.min(100, Math.round(100 * j.done / j.total)) : null;
  el.innerHTML = '<div class="small"><b>' + esc(j.name) + "</b> — " + esc(j.state) + (j.message ? " — " + esc(j.message) : "") +
    " (" + Number(j.done || 0).toLocaleString() + (j.total ? " of " + Number(j.total).toLocaleString() : "") + ")</div>" +
    (pct !== null ? '<progress max="100" value="' + pct + '"></progress>' : (j.state === "running" ? "<progress></progress>" : ""));
  if (j.state !== "running" && j.result && typeof j.result === "object") {
    const nice = k => k.replace(/_/g, " ");
    el.innerHTML = '<div class="note ' + (j.state === "finished" ? "good" : "") + '"><b>' + esc(j.name) + "</b> — " + esc(j.state) + '<ul class="small" style="margin:6px 0 0">' +
      Object.entries(j.result).filter(([k, v]) => k !== "old_store" && typeof v !== "object").map(([k, v]) =>
        "<li>" + esc(nice(k)) + ": <b>" + esc(typeof v === "number" ? v.toLocaleString() : v) + "</b></li>").join("") + "</ul></div>";
  } else if (j.state === "failed") {
    el.innerHTML = '<div class="note bad"><b>' + esc(j.name) + "</b> failed: " + esc(j.message) + "</div>";
  }
  if (j.state === "running") setTimeout(() => pollJob(el, onDone), 800);
  else if (onDone) onDone(j);
}

// A failed request already showed its message in a toast; don't also report it as a page error.
window.addEventListener("unhandledrejection", e => e.preventDefault());
