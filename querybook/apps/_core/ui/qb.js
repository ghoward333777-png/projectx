// QueryBook dedicated applications — shared page helpers (no libraries).
"use strict";
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------- transparency: every request shows a bar, its time, and its button as busy
const BUSY = { n: 0, t0: 0, label: "", timer: null, hide: null };
let lastPress = { el: null, at: 0 };
document.addEventListener("click", e => { const b = e.target.closest && e.target.closest("button, a.btn"); if (b) lastPress = { el: b, at: Date.now() }; }, true);
function busyBar() {
  let el = document.getElementById("qb-busy");
  if (!el) {
    el = document.createElement("div"); el.id = "qb-busy"; el.setAttribute("role", "status");
    el.innerHTML = '<div class="qb-busy-track"><div class="qb-busy-fill"></div></div><span class="qb-busy-text"></span>';
    document.body.appendChild(el);
  }
  return el;
}
function actionLabel(path) {
  const p = path.split("?")[0].replace(/^\/api\//, "").replace(/[\/-]/g, " ").replace(/\.(csv|txt)$/, "");
  return p.charAt(0).toUpperCase() + p.slice(1);
}
function busyStart(label) {
  const el = busyBar();
  if (BUSY.n === 0) { BUSY.t0 = performance.now(); }
  BUSY.n++; BUSY.label = label;
  clearTimeout(BUSY.hide);
  el.className = "show working";
  const tick = () => { el.querySelector(".qb-busy-text").textContent = "⏳ " + BUSY.label + " · " + ((performance.now() - BUSY.t0) / 1000).toFixed(2) + " s"; };
  tick(); clearInterval(BUSY.timer); BUSY.timer = setInterval(tick, 50);
}
function busyEnd(label, ok, serverMs) {
  BUSY.n = Math.max(0, BUSY.n - 1);
  if (BUSY.n > 0) return;
  clearInterval(BUSY.timer);
  const el = busyBar(), secs = ((performance.now() - BUSY.t0) / 1000).toFixed(2);
  el.className = "show " + (ok ? "done" : "failed");
  el.querySelector(".qb-busy-text").textContent = (ok ? "✔ " : "✖ Failed: ") + label + " · " + secs + " s" + (serverMs ? " (server " + (serverMs / 1000).toFixed(2) + " s)" : "");
  BUSY.hide = setTimeout(() => { el.className = ""; }, ok ? 2500 : 6000);
}

// A pressed button shows that it is working (pulsing, live time to 0.01 s), then flashes the outcome.
function buttonStart(btn) {
  if (btn._qb) { clearTimeout(btn._qb.restore); btn.innerHTML = btn._qb.html; }
  const st = { html: btn.innerHTML, t0: performance.now(), timer: null, restore: null };
  btn._qb = st;
  btn.classList.remove("flash-ok", "flash-bad"); btn.classList.add("busy"); btn.setAttribute("aria-busy", "true");
  const tick = () => { btn.innerHTML = '<span class="qb-spin" aria-hidden="true"></span>' + st.html + ' <span class="qb-t">' + ((performance.now() - st.t0) / 1000).toFixed(2) + " s</span>"; };
  tick(); st.timer = setInterval(tick, 50);
}
function buttonEnd(btn, ok) {
  const st = btn._qb; if (!st) return;
  clearInterval(st.timer);
  const secs = ((performance.now() - st.t0) / 1000).toFixed(2);
  btn.classList.remove("busy"); btn.removeAttribute("aria-busy");
  btn.classList.add(ok ? "flash-ok" : "flash-bad");
  btn.innerHTML = (ok ? "✔ " : "✖ ") + st.html + ' <span class="qb-t">' + secs + " s</span>";
  st.restore = setTimeout(() => { btn.classList.remove("flash-ok", "flash-bad"); if (btn._qb === st) { btn.innerHTML = st.html; btn._qb = null; } }, ok ? 1800 : 4000);
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const label = actionLabel(path);
  const btn = (Date.now() - lastPress.at < 400) ? lastPress.el : null;
  if (btn && !btn.closest("nav.tabs, .subtabs")) buttonStart(btn);
  const quiet = body === undefined && /\/api\/(job|status|build)$/.test(path.split("?")[0]);
  if (!quiet) busyStart(label);
  let res, ok = false, data = {};
  try {
    try { res = await fetch(path, opt); }
    catch (e) { toast("The application is not responding. Is its window still open?", true); throw e; }
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok) { const msg = data.error || ("Error " + res.status); toast(msg, true); throw new Error(msg); }
    ok = true;
    return data;
  } finally {
    if (!quiet) busyEnd(label, ok, res && res.headers.get("X-QB-Ms"));
    if (btn && btn._qb) buttonEnd(btn, ok);
  }
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
  const fmtS = s => s === null || s === undefined ? "" : s < 60 ? Number(s).toFixed(2) + " s" : Math.floor(s / 60) + " min " + (s % 60).toFixed(2) + " s";
  el.innerHTML = '<div class="small"><b>' + esc(j.name) + "</b> — " + esc(j.state) + (j.message ? " — " + esc(j.message) : "") +
    " (" + Number(j.done || 0).toLocaleString() + (j.total ? " of " + Number(j.total).toLocaleString() : "") + ")</div>" +
    (j.state === "running" ? '<div class="meter tall live"><i style="width:' + (pct !== null ? pct : 100) + '%"></i></div>' : "") +
    '<div class="small muted">' + [pct !== null ? pct + "%" : "", "elapsed " + fmtS(j.elapsed), j.rate ? "speed " + Number(j.rate).toLocaleString() + " per second" : "",
      j.eta_s !== undefined && j.eta_s !== null ? "about " + fmtS(j.eta_s) + " left in this step" : "", j.updates_per_s ? j.updates_per_s + " updates/s" : ""].filter(Boolean).join(" · ") + "</div>";
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
      '<div class="card" id="gc-card"><h2>Google Cloud</h2><p class="small muted">Optional. Connects this application to your Google Cloud project: an off-site copy of every backup in Cloud Storage, health reports in Cloud Monitoring (with an alert if the application fails or goes silent), and — with the API key — Speech-to-Text, Text-to-Speech and YouTube. Keys are kept in this application\'s data folder (owner-only) and sent only to Google; they are never shown or logged.</p>' +
      '<div id="gc-status" class="small"></div>' +
      '<div class="grid-gc">' +
      '<label class="f">API key (Speech-to-Text, Text-to-Speech, YouTube) — <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">get one</a></label><input id="gc-key" type="password" autocomplete="off" placeholder="AIza…">' +
      '<label class="f">Service account key file (Cloud Storage, Monitoring) — <a href="https://console.cloud.google.com/iam-admin/serviceaccounts" target="_blank" rel="noopener">create one</a> with roles Storage Object Admin + Monitoring Editor, then Keys → Add key → JSON</label>' +
      '<label class="btn quiet" style="cursor:pointer;display:inline-block">📁 Choose the JSON key file<input id="gc-sa" type="file" accept=".json,application/json" hidden></label> <span id="gc-sa-name" class="small muted"></span>' +
      '<label class="f">Cloud Storage bucket — <a href="https://console.cloud.google.com/storage/create-bucket" target="_blank" rel="noopener">create one</a></label><input id="gc-bucket" type="text" placeholder="my-querybook-backups">' +
      '<label class="f">Keep this many backups in the bucket</label><input id="gc-keep" type="number" min="1" max="100" style="width:90px">' +
      '<label class="chk"><input type="checkbox" id="gc-storage"> Copy every backup to Cloud Storage</label>' +
      '<label class="chk"><input type="checkbox" id="gc-mon"> Send health reports to Cloud Monitoring</label></div>' +
      '<div class="row" style="margin-top:10px"><button class="btn" id="gc-save">Save</button><button class="btn quiet" id="gc-test">Test all Google services</button>' +
      '<button class="btn quiet" id="gc-up">Back up to Cloud now</button><button class="btn quiet" id="gc-list">Cloud backups</button><button class="btn quiet" id="gc-alert">Create alert</button>' +
      '<span id="gc-copy"></span><button class="btn quiet" id="gc-forget">Disconnect</button></div>' +
      '<div id="gc-job" style="margin-top:10px"></div><div id="gc-out" style="margin-top:10px"></div></div>' +
      '<div class="card"><h2>Backup mirror (redundancy)</h2><p class="small muted">A second, verified copy of every backup in another folder — best on another drive (USB disk, NAS, synced folder). Each copy is checked: same SHA-256 as the backup and a passing database check. Restoring can use either copy.</p>' +
      '<div class="row"><input id="mr-f" class="grow" type="text" placeholder="Folder on another drive, e.g. E:\\QB-Mirror" aria-label="Mirror folder"><button class="btn" id="mr-set">Set mirror</button><button class="btn quiet" id="mr-off">Switch off</button></div><div id="mr-out" class="small" style="margin-top:8px"></div></div>' +
      '<div class="card"><h2>Activity log</h2><p class="small muted">Every action that changes something, every background task, backup, import, diagnostics run and monitoring report — with its result and how long it took. Kept in this application\'s database (newest 20,000).</p>' +
      '<div class="row"><input id="act-q" type="text" placeholder="Filter by task" style="max-width:260px" aria-label="Filter activity"><button class="btn quiet" id="act-go">Refresh</button></div><div id="act-out" style="margin-top:10px;max-height:420px;overflow:auto"></div></div>' +
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
    let gcSA = null;
    const gcShow = async () => {
      const g = await api("/api/gcloud"), c = g.settings, st = g.state || {};
      $("#gc-status").innerHTML = '<div class="stats" style="margin-bottom:8px">' +
        '<div class="stat"><div class="k">API key</div><div class="v" style="font-size:16px">' + (c.api_key_set ? "✔ set" + (c.api_key_from_environment ? " (environment)" : "") : "— not set") + "</div></div>" +
        '<div class="stat"><div class="k">Service account</div><div class="v" style="font-size:14px">' + (c.service_account ? "✔ " + esc(c.service_account.client_email) : "— not set") + "</div></div>" +
        '<div class="stat"><div class="k">Cloud Storage</div><div class="v" style="font-size:14px">' + (c.storage_on ? "on → " + esc(c.bucket || "(no bucket)") : "off") + (st.last_upload ? '<div class="small muted">last copy ' + esc(st.last_upload) + "</div>" : "") + (st.last_error ? '<div class="small" style="color:var(--bad)">' + esc(st.last_error) + "</div>" : "") + "</div></div>" +
        '<div class="stat"><div class="k">Cloud Monitoring</div><div class="v" style="font-size:14px">' + (c.monitoring_on ? "on (project " + esc(c.project_id || "?") + ")" : "off") + (st.last_metrics ? '<div class="small muted">last report ' + esc(st.last_metrics) + "</div>" : "") + "</div></div></div>" +
        '<div class="small muted">Objects are stored under <span class="mono">' + esc(g.prefix) + "</span></div>";
      $("#gc-bucket").value = c.bucket || ""; $("#gc-keep").value = c.keep || 10; $("#gc-storage").checked = c.storage_on; $("#gc-mon").checked = c.monitoring_on;
      $("#gc-copy").innerHTML = (g.siblings || []).map(x => '<button class="btn quiet" data-gccopy="' + esc(x.app) + '">Copy settings from ' + esc({ language: "Language Builder", stem: "Math & Science", facts: "History & News" }[x.app] || x.app) + "</button>").join("");
      $$("[data-gccopy]").forEach(b => b.onclick = async () => { await api("/api/gcloud/copy-from", { app: b.dataset.gccopy }); toast("Google settings copied."); gcShow(); });
    };
    $("#gc-sa").onchange = e => { const f = e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { gcSA = r.result; $("#gc-sa-name").textContent = f.name + " — press Save"; }; r.readAsText(f); };
    $("#gc-save").onclick = async () => {
      const body = { bucket: $("#gc-bucket").value, keep: Number($("#gc-keep").value) || 10, storage_on: $("#gc-storage").checked, monitoring_on: $("#gc-mon").checked };
      if ($("#gc-key").value) body.api_key = $("#gc-key").value;
      if (gcSA) body.service_account_json = gcSA;
      await api("/api/gcloud", body); $("#gc-key").value = ""; gcSA = null; $("#gc-sa-name").textContent = ""; toast("Google Cloud settings saved."); gcShow();
    };
    $("#gc-test").onclick = async () => {
      const r = await api("/api/gcloud/test", {});
      $("#gc-out").innerHTML = '<table class="t small"><tr><th>Service</th><th>Result</th><th>Seconds</th><th>Detail</th></tr>' + r.results.map(x => "<tr><td>" + esc(x.service) + "</td><td>" +
        (x.ok ? '<span class="badge good">✔ works</span>' : '<span class="badge bad">✖ failed</span>') + "</td><td>" + Number(x.seconds).toFixed(2) + "</td><td>" + esc(x.detail) + "</td></tr>").join("") + "</table>";
    };
    $("#gc-up").onclick = async () => { await api("/api/gcloud/backup-now", {}); pollJob($("#gc-job"), () => gcShow()); };
    $("#gc-list").onclick = async () => {
      const r = await api("/api/gcloud/backups");
      $("#gc-out").innerHTML = r.backups.length ? '<table class="t small"><tr><th>Cloud backup</th><th>Size</th><th>Stored</th><th></th></tr>' + r.backups.map(x => '<tr><td class="mono">' + esc(x.name.split("/").pop()) +
        "</td><td>" + (x.bytes / 1048576).toFixed(2) + " MB</td><td>" + esc(x.updated || "") + '</td><td><button class="btn quiet" data-gcfetch="' + esc(x.name) + '">Download to this computer</button></td></tr>').join("") + "</table>" : '<p class="muted">No backups in the bucket yet.</p>';
      $$("[data-gcfetch]").forEach(b => b.onclick = async () => { const r2 = await api("/api/gcloud/fetch", { name: b.dataset.gcfetch }); toast(r2.saved + " saved. " + r2.note); });
    };
    $("#gc-alert").onclick = async () => { const r = await api("/api/gcloud/alert", {}); toast("Alert created: " + r.display_name + ". Add your e-mail as a notification channel in Cloud Monitoring → Alerting."); };
    $("#gc-forget").onclick = async () => { if (!confirm("Disconnect Google Cloud from this application? Keys are removed from this computer; nothing in your bucket is deleted.")) return; await api("/api/gcloud/forget", {}); gcShow(); };
    gcShow();
    const mirrorShow = async () => { const m = await api("/api/mirror"); $("#mr-out").innerHTML = m.folder ? "Mirror: <span class=\"mono\">" + esc(m.folder) + "</span> — " + m.copies.length + " verified cop" + (m.copies.length === 1 ? "y" : "ies") + (m.copies[0] ? "; newest " + esc(m.copies[0].name) : "") : "<span class=\"badge warn\">no mirror</span> Backups exist in one place only."; if (m.folder && !$("#mr-f").value) $("#mr-f").value = m.folder; };
    $("#mr-set").onclick = async () => { await api("/api/mirror", { folder: $("#mr-f").value }); toast("Mirror set; the newest backup was copied and verified."); mirrorShow(); };
    $("#mr-off").onclick = async () => { await api("/api/mirror", { folder: "off" }); $("#mr-f").value = ""; mirrorShow(); };
    mirrorShow();
    $("#act-go", el).onclick = () => showActivity(el);
    onEnter($("#act-q", el), () => showActivity(el));
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
  showActivity(el);
  refreshFooter();
}

async function showActivity(el) {
  const r = await api("/api/activity?limit=200&task=" + encodeURIComponent($("#act-q", el).value || ""));
  const badge = s => s === "ok" || s === "finished" ? '<span class="badge good">' + esc(s) + "</span>" : s === "started" ? '<span class="badge">' + esc(s) + "</span>" :
    (s === "warn" || s === "refused" || s === "stopped") ? '<span class="badge warn">' + esc(s) + "</span>" : '<span class="badge bad">' + esc(s) + "</span>";
  $("#act-out", el).innerHTML = r.activity.length ? '<table class="t small"><tr><th>When (UTC)</th><th>Task</th><th>Result</th><th>Time</th><th>Detail</th></tr>' + r.activity.map(a =>
    '<tr><td class="mono">' + esc(a.at.replace("T", " ").replace("Z", "")) + "</td><td>" + esc(a.task) + "</td><td>" + badge(a.status) + '</td><td class="mono">' +
    (a.ms === null ? "" : (a.ms / 1000).toFixed(2) + " s") + "</td><td>" + esc(a.detail || "") + "</td></tr>").join("") + "</table>" : '<p class="muted">Nothing logged yet.</p>';
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
