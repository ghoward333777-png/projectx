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
      s.health ? "Health: " + DIAG_BADGE[s.health] : "",
      "Last backup: " + esc(db.last_backup || "none yet"),
      "Version " + esc(s.version || ""),
    ];
    $("footer.status").innerHTML = parts.filter(Boolean).map(p => "<span>" + p + "</span>").join("");
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

// ---------------------------------------------------------------- diagnostics and monitoring (shared by every application)
const DIAG_BADGE = { ok: '<span class="badge good">OK</span>', warn: '<span class="badge warn">WARNING</span>', fail: '<span class="badge bad">PROBLEM</span>' };

async function renderDiagnostics(el, rerun) {
  if (!el.dataset.built) {
    el.dataset.built = "1";
    el.innerHTML =
      '<div class="card"><h2>Internal diagnostics</h2><p class="small muted">The application checks itself when it starts and every hour: program files, data folder, disk space, database, backups, recent errors and its own calculations. Nothing here reads your facts, words or answers.</p>' +
      '<div class="row"><button class="btn" id="dg-run">Run checks now</button><button class="btn quiet" id="dg-self">Run full self-test</button>' +
      '<a class="btn quiet" href="/api/diagnostics/report.txt" download="diagnostics.txt" style="text-decoration:none">Download report</a></div>' +
      '<div id="dg-out" style="margin-top:12px"></div><pre id="dg-selfout" class="small mono" style="display:none;white-space:pre-wrap;max-height:320px;overflow:auto;background:var(--chip);padding:10px;border-radius:8px"></pre></div>' +
      '<div class="card"><h2>Monitoring connection</h2>' +
      '<p class="small">Sends health reports to the development repository on GitHub, as comments on one issue for this application on this computer, so problems can be seen and fixed from the development side. ' +
      "Reports contain only the check results, versions and error messages shown above — never your facts, words, answers, or your name and folders.</p>" +
      '<div id="mon-state"></div>' +
      '<div class="grid2" style="display:grid;grid-template-columns:1fr 1fr;gap:0 14px">' +
      '<div><label class="f" for="mon-repo">Repository (owner/name)</label><input id="mon-repo" type="text"></div>' +
      '<div><label class="f" for="mon-label">Name for this computer (optional)</label><input id="mon-label" type="text" placeholder="e.g. office PC"></div>' +
      '<div><label class="f" for="mon-token">GitHub token</label><input id="mon-token" type="password" autocomplete="off" placeholder="paste a fine-grained token"></div>' +
      '<div><label class="f" for="mon-freq">Send</label><select id="mon-freq"></select></div></div>' +
      '<label style="display:block;margin-top:10px"><input type="checkbox" id="mon-on"> Monitoring connection on</label>' +
      '<div class="row" style="margin-top:10px"><button class="btn" id="mon-save">Save</button><button class="btn secondary" id="mon-test">Send a test report</button>' +
      '<button class="btn quiet" id="mon-preview">Preview a report</button><button class="btn quiet" id="mon-off">Remove token</button></div>' +
      '<pre id="mon-prev" class="small mono" style="display:none;white-space:pre-wrap;max-height:320px;overflow:auto;background:var(--chip);padding:10px;border-radius:8px"></pre>' +
      '<details style="margin-top:12px"><summary class="small"><b>How to make the token (once)</b></summary><ol class="small">' +
      '<li>On github.com open <b>Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token</b>.</li>' +
      "<li>Repository access: <b>Only select repositories</b> → the repository above.</li>" +
      "<li>Permissions → Repository permissions → <b>Issues: Read and write</b>. Nothing else is needed.</li>" +
      "<li>Generate, copy the token, paste it here, tick <b>Monitoring connection on</b>, press <b>Save</b>, then <b>Send a test report</b>.</li>" +
      "</ol><p class=\"small muted\">The token is kept only in this application's data folder (monitor.json) and is only ever sent to GitHub. One token can be used by all three applications.</p></details></div>";
    $("#dg-run", el).onclick = () => renderDiagnostics(el, true);
    $("#dg-self", el).onclick = async () => {
      const b = $("#dg-self", el), pre = $("#dg-selfout", el);
      b.disabled = true; b.textContent = "Running self-test…"; pre.style.display = "none";
      try {
        const r = await api("/api/selftest", {});
        pre.textContent = r.output; pre.style.display = "block";
        toast(r.passed ? "Self-test passed." : "Self-test found problems — see the list.", !r.passed);
      } finally { b.disabled = false; b.textContent = "Run full self-test"; }
    };
    const monBody = () => ({ repo: $("#mon-repo", el).value, label: $("#mon-label", el).value, token: $("#mon-token", el).value,
      frequency: $("#mon-freq", el).value, enabled: $("#mon-on", el).checked });
    $("#mon-save", el).onclick = async () => { const m = await api("/api/monitor", monBody()); $("#mon-token", el).value = ""; showMonitor(el, m); toast("Monitoring settings saved."); };
    $("#mon-test", el).onclick = async () => {
      const b = $("#mon-test", el); b.disabled = true;
      try {
        if ($("#mon-token", el).value) await api("/api/monitor", monBody());
        const r = await api("/api/monitor/test", {}); $("#mon-token", el).value = ""; showMonitor(el, r.monitor);
        toast("Test report sent to GitHub.");
      } finally { b.disabled = false; }
    };
    $("#mon-preview", el).onclick = async () => { const r = await api("/api/monitor/preview"); const pre = $("#mon-prev", el); pre.textContent = r.title + "\n\n" + r.body; pre.style.display = "block"; };
    $("#mon-off", el).onclick = async () => { if (confirm("Remove the token and turn the monitoring connection off?")) showMonitor(el, await api("/api/monitor/disconnect", {})); };
  }
  const r = rerun ? await api("/api/diagnostics/run", {}) : await api("/api/diagnostics");
  $("#dg-out", el).innerHTML = '<p>Overall: ' + DIAG_BADGE[r.overall] + ' <span class="small muted">' + esc(r.app) + " " + esc(r.version) + " · checked " + esc(r.time) + " · running for " + esc(r.uptime) + "</span></p>" +
    '<table class="t"><tr><th>Check</th><th>Result</th><th>Detail</th></tr>' + r.checks.map(c => "<tr><td>" + esc(c.name) + "</td><td>" + DIAG_BADGE[c.status] + '</td><td class="small">' + esc(c.detail) + "</td></tr>").join("") + "</table>" +
    '<p class="small muted">Python ' + esc(r.environment.python) + " · " + esc(r.environment.os) + " · SQLite " + esc(r.environment.sqlite) + "</p>" +
    (r.errors.length ? '<h3>Recent errors</h3><ul class="small mono">' + r.errors.map(e => "<li>" + esc(e.time) + " " + esc(e.message) + "</li>").join("") + "</ul>" : "");
  showMonitor(el, await api("/api/monitor"));
  refreshFooter();
}

function showMonitor(el, m) {
  $("#mon-repo", el).value = m.repo;
  $("#mon-label", el).value = m.label;
  $("#mon-freq", el).innerHTML = Object.entries(m.frequencies).map(([k, v]) => '<option value="' + k + '"' + (k === m.frequency ? " selected" : "") + ">" + esc(v) + "</option>").join("");
  $("#mon-on", el).checked = m.enabled;
  $("#mon-token", el).placeholder = m.token_set ? "token saved (" + m.token_hint + ") — paste a new one to replace it" : "paste a fine-grained token";
  $("#mon-state", el).innerHTML = '<div class="note ' + (m.enabled ? "good" : "") + '">' + (m.enabled ? "<b>Connected.</b> " : "<b>Off.</b> ") +
    "Reports go to <span class=\"mono\">" + esc(m.repo) + "</span>, issue “" + esc(m.title) + "”" +
    (m.issue_url ? ' — <a href="' + esc(m.issue_url) + '" target="_blank" rel="noopener noreferrer">open the issue</a>' : "") + ".<br>" +
    '<span class="small">Last report: ' + esc(m.last_sent || "none yet") + (m.last_status ? " (" + esc(m.last_status) + ")" : "") +
    (m.waiting ? " · " + m.waiting + " report(s) waiting to be sent" : "") + " · install " + esc(m.install_id) + "</span></div>";
}
