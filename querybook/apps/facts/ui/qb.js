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

// ---------------------------------------------------------------- keep the screen awake during long work
// The screen saver (and a sleeping screen) makes the browser pause pages it thinks nobody watches. Long work — learning
// loops, ingesting, recording, long speech — holds a screen wake lock while it runs; released when it ends.
const QB_WAKE = { n: 0, lock: null, why: new Set() };
async function qbWake(why) {
  QB_WAKE.n++; QB_WAKE.why.add(why || "work");
  try { if (!QB_WAKE.lock && navigator.wakeLock) { QB_WAKE.lock = await navigator.wakeLock.request("screen"); QB_WAKE.lock.addEventListener("release", () => { QB_WAKE.lock = null; }); } } catch (e) {}
}
function qbWakeEnd(why) {
  QB_WAKE.n = Math.max(0, QB_WAKE.n - 1); QB_WAKE.why.delete(why || "work");
  if (!QB_WAKE.n && QB_WAKE.lock) { QB_WAKE.lock.release().catch(() => {}); QB_WAKE.lock = null; }
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && QB_WAKE.n && !QB_WAKE.lock) qbWake("resume").then(() => qbWakeEnd("resume")); });

// ---------------------------------------------------------------- diagnostics and monitoring (shared by every application)
const DIAG_BADGE = { ok: '<span class="badge good">OK</span>', warn: '<span class="badge warn">WARNING</span>', fail: '<span class="badge bad">PROBLEM</span>' };

async function dgPower(refresh) {
  const box = document.getElementById("dg-power"); if (!box) return;
  const b = document.getElementById("dg-power-re"); if (b) b.onclick = () => dgPower(true);
  try {
    const p = await api("/api/system/power" + (refresh ? "?refresh=1" : "")), s = p.system || {};
    const ev = (s.events || []).slice(0, 20).map(e => "<tr><td>" + esc(e.time) + "</td><td>" + esc(e.event) + "</td><td>" + esc(e.detail || "") + "</td></tr>").join("");
    const set = Object.entries(s.settings || {}).map(([k, v]) => "<li>" + esc(k) + ": " + esc(typeof v === "object" ? JSON.stringify(v) : String(v)) + "</li>").join("");
    box.innerHTML = "<p>" + (p.keep_awake ? "✔ Keeping the computer awake — " : "⚠ Not keeping the computer awake — ") + esc(p.method || "") + "</p>" +
      ((s.advice || []).length ? "<ul>" + s.advice.map(a => "<li>" + esc(a) + "</li>").join("") + "</ul>" : "") +
      ((p.sleeps || []).length ? "<p><b>Paused while running:</b> " + p.sleeps.map(x => esc(x.from) + " → " + esc(x.to) + " (" + x.seconds + " s)").join("; ") + "</p>" : "") +
      (set ? "<p><b>System settings</b></p><ul>" + set + "</ul>" : "") +
      (ev ? '<p><b>Sleep, wake and shutdowns (system log, newest first)</b></p><table class="t small"><tbody>' + ev + "</tbody></table>" : "<p>No sleep, wake or shutdown events in the system log for the last 48 h.</p>");
  } catch (e) { box.textContent = "Could not read: " + e.message; }
}

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
      '<div class="note" style="margin:10px 0"><b>Easiest: let Google set everything up for you (about 2 minutes).</b><ol class="small" style="margin:6px 0 0 18px;padding:0">' +
      '<li>Open <a href="https://console.cloud.google.com/?cloudshell=true" target="_blank" rel="noopener">Google Cloud with Cloud Shell</a> (signed in as you; a terminal opens at the bottom — press <b>Authorize</b> if asked).</li>' +
      '<li>Press <button class="btn quiet" id="gc-copyscript" style="padding:2px 10px">📋 Copy the setup commands</button>, click in the Cloud Shell terminal, paste (Ctrl+V / ⌘V) and press Enter.</li>' +
      '<li>When it finishes, copy the line that starts with <span class="mono">QBSETUP-</span> and paste it here:</li></ol>' +
      '<div class="row" style="margin-top:6px"><input id="gc-code" class="grow" type="password" autocomplete="off" placeholder="QBSETUP-…"><button class="btn" id="gc-apply">Apply setup code</button></div>' +
      '<label class="chk"><input type="checkbox" id="gc-all" checked> Set up all QueryBook applications on this computer at once</label>' +
      '<details class="small" style="margin-top:6px"><summary>What the setup commands do</summary><pre class="mono" id="gc-script" style="white-space:pre-wrap;max-height:260px;overflow:auto;background:var(--chip);padding:8px;border-radius:6px"></pre></details></div>' +
      '<details><summary class="small"><b>Or enter the details by hand</b></summary>' +
      '<div class="grid-gc">' +
      '<label class="f">API key (Speech-to-Text, Text-to-Speech, YouTube) — <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">get one</a></label><input id="gc-key" type="password" autocomplete="off" placeholder="AIza…">' +
      '<label class="f">Service account key file (Cloud Storage, Monitoring) — <a href="https://console.cloud.google.com/iam-admin/serviceaccounts" target="_blank" rel="noopener">create one</a> with roles Storage Object Admin + Monitoring Editor, then Keys → Add key → JSON</label>' +
      '<label class="btn quiet" style="cursor:pointer;display:inline-block">📁 Choose the JSON key file<input id="gc-sa" type="file" accept=".json,application/json" hidden></label> <span id="gc-sa-name" class="small muted"></span>' +
      '<label class="f">Cloud Storage bucket — <a href="https://console.cloud.google.com/storage/create-bucket" target="_blank" rel="noopener">create one</a></label><input id="gc-bucket" type="text" placeholder="my-querybook-backups">' +
      '<label class="f">Keep this many backups in the bucket</label><input id="gc-keep" type="number" min="1" max="100" style="width:90px">' +
      '<label class="chk"><input type="checkbox" id="gc-storage"> Copy every backup to Cloud Storage</label>' +
      '<label class="chk"><input type="checkbox" id="gc-mon"> Send health reports to Cloud Monitoring</label></div></details>' +
      '<div class="row" style="margin-top:10px"><button class="btn" id="gc-save">Save</button><button class="btn quiet" id="gc-test">Test all Google services</button>' +
      '<button class="btn quiet" id="gc-up">Back up to Cloud now</button><button class="btn quiet" id="gc-list">Cloud backups</button><button class="btn quiet" id="gc-alert">Create alert</button>' +
      '<span id="gc-copy"></span><button class="btn quiet" id="gc-forget">Disconnect</button></div>' +
      '<div id="gc-job" style="margin-top:10px"></div><div id="gc-out" style="margin-top:10px"></div></div>' +
      '<div class="card"><h2>Backup mirror (redundancy)</h2><p class="small muted">A second, verified copy of every backup in another folder — best on another drive (USB disk, NAS, synced folder). Each copy is checked: same SHA-256 as the backup and a passing database check. Restoring can use either copy.</p>' +
      '<div class="row"><input id="mr-f" class="grow" type="text" placeholder="Folder on another drive, e.g. E:\\QB-Mirror" aria-label="Mirror folder"><button class="btn" id="mr-set">Set mirror</button><button class="btn quiet" id="mr-off">Switch off</button></div><div id="mr-out" class="small" style="margin-top:8px"></div></div>' +
      '<div class="card"><h2>Power, sleep and the log</h2><p class="small muted">While it runs, QueryBook asks the computer not to sleep (the screen may still turn off); long work in the browser keeps the screen awake. At start-up it reads the system\'s own log for sleep, wake and unexpected shutdowns.</p>' +
      '<div id="dg-power" class="small">Checking…</div><div class="row"><button class="btn quiet" id="dg-power-re">Check the system log again</button>' +
      '<a class="btn quiet" href="/api/system/log.txt" download="querybook-log.txt" style="text-decoration:none">Download the log</a></div></div>' +
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
    api("/api/gcloud/setup-script").then(r => { $("#gc-script").textContent = r.script; SETUP_TXT = r.script; });
    let SETUP_TXT = "";
    $("#gc-copyscript").onclick = async () => {
      try { await navigator.clipboard.writeText(SETUP_TXT); toast("Setup commands copied — paste them into Cloud Shell and press Enter."); }
      catch (e) { $("#gc-script").parentElement.open = true; toast("Select the commands below and copy them (Ctrl+C).", true); }
    };
    $("#gc-apply").onclick = async () => {
      const r = await api("/api/gcloud/setup-code", { code: $("#gc-code").value, all_apps: $("#gc-all").checked });
      $("#gc-code").value = "";
      toast("Google Cloud is set up for: " + r.applied_to.map(a => ({ language: "Language Builder", stem: "Math & Science", facts: "History & News" }[a] || a)).join(", ") + ". Press 'Test all Google services'.");
      gcShow();
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
  dgPower(false);
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

// ---------------------------------------------------------------- the Commons: shared facts and the harvest teams
const CM_STATUS = { verified: "good", corroborated: "good", sourced: "good", reported: "warn", unsourced: "", disputed: "warn", rejected: "bad" };
const cmTag = (text, cls) => '<span class="badge ' + (cls || "") + '">' + esc(text || "") + "</span>";
const cmBadge = s => cmTag(s, CM_STATUS[s]);
const cmWhen = t => t ? esc(String(t).replace("T", " ").replace(/\.\d+Z$|Z$/, "")) : "never";
let CM_TIMER = null;

async function renderCommons(el) {
  if (!el.dataset.ready) {
    el.dataset.ready = "1";
    el.innerHTML =
      '<div class="card"><h2>Shared facts and the harvest teams</h2><p class="small muted">All three QueryBook applications keep the facts they stand behind in one shared database, the Commons. ' +
      "Each application has a team of four agents — a Strategist, a Planner, a Harvester and a Curator — that devise a harvest strategy, plan it, carry it out and save and manage what was found. " +
      "The applications check each other's facts: each kind of check is answered by the application able to answer it, and the answer is kept with the fact as evidence, with its reasoning. " +
      "The agents are deterministic programs, not AI models.</p>" +
      '<div class="row"><button class="btn" id="cm-run">Run this team now</button><label class="row small"><input type="checkbox" id="cm-auto"> Harvest automatically (the engine gives each application its turn)</label>' +
      '<label class="row small">Licence policy <select id="cm-policy"></select></label></div><div id="cm-state" aria-live="polite"></div></div>' +
      '<div id="hv"></div>' +
      '<div class="card"><h2>The teams</h2><div id="cm-teams"></div></div>' +
      '<div class="card"><h2>This team\'s strategy and plan</h2><div id="cm-plan"></div></div>' +
      '<div class="card"><h2>The shared database</h2><div id="cm-db"></div></div>' +
      '<div class="card"><h2>Browse shared facts</h2><div class="row"><input id="cm-q" class="grow" type="text" placeholder="Search subject or value" aria-label="Search shared facts">' +
      '<select id="cm-domain" aria-label="Domain"><option value="">all domains</option><option>language</option><option>stem</option><option>history</option></select>' +
      '<select id="cm-status" aria-label="Status"><option value="">any status</option>' + Object.keys(CM_STATUS).map(s => "<option>" + s + "</option>").join("") + "</select>" +
      '<button class="btn quiet" id="cm-find">Search</button></div><div id="cm-facts"></div><div id="cm-fact"></div></div>' +
      '<div class="card"><h2>Agent log</h2><div id="cm-log"></div></div>';
    $("#cm-run", el).addEventListener("click", async () => { await api("/api/commons/run", {}); toast("The team has started."); setTimeout(() => renderCommons(el), 800); });
    $("#cm-auto", el).addEventListener("change", e => api("/api/commons/settings", { auto: e.target.checked ? "on" : "off" }));
    $("#cm-policy", el).addEventListener("change", e => api("/api/commons/settings", { policy: e.target.value }).then(() => toast("Licence policy saved for all three applications.")));
    const find = async () => {
      const r = await api("/api/commons/facts", { q: $("#cm-q", el).value, domain: $("#cm-domain", el).value, status: $("#cm-status", el).value, limit: 100 });
      $("#cm-fact", el).innerHTML = "";
      $("#cm-facts", el).innerHTML = r.facts.length ? '<table class="t small"><tr><th>Subject</th><th>Predicate</th><th>Value</th><th>Domain</th><th>Status</th><th>Apps</th></tr>' +
        r.facts.map(f => '<tr data-cmf="' + f.id + '" style="cursor:pointer"><td>' + esc(f.subject) + "</td><td>" + esc(f.predicate) + "</td><td>" + esc(String(f.object).slice(0, 160)) +
          "</td><td>" + esc(f.domain) + "</td><td>" + cmBadge(f.status) + "</td><td>" + f.apps + "</td></tr>").join("") + "</table>" : '<p class="muted">No shared facts match.</p>';
    };
    $("#cm-find", el).addEventListener("click", find);
    onEnter($("#cm-q", el), find);
    $("#cm-facts", el).addEventListener("click", async e => {
      const tr = e.target.closest("tr[data-cmf]");
      if (!tr) return;
      const f = await api("/api/commons/fact", { id: Number(tr.dataset.cmf) });
      $("#cm-fact", el).innerHTML = '<div class="note"><b>' + esc(f.subject) + " — " + esc(f.predicate) + ":</b> " + esc(f.object) + " " + cmBadge(f.status) +
        ' <span class="small muted">confidence ' + f.confidence + " · first harvested by " + esc(f.origin_app) + "</span></div>" +
        "<h3>Evidence</h3>" + (f.evidence.length ? '<table class="t small"><tr><th>App</th><th>Method</th><th>Source</th><th>Licence</th><th>Verdict</th><th>Detail</th></tr>' +
          f.evidence.map(x => "<tr><td>" + esc(x.app) + "</td><td>" + esc(x.method) + "</td><td>" + (x.url ? '<a href="' + esc(x.url) + '" target="_blank" rel="noopener noreferrer">' + esc(x.source) + "</a>" : esc(x.source)) +
            "</td><td>" + esc(x.licence || "") + "</td><td>" + cmTag(x.verdict, x.verdict === "supports" ? "good" : x.verdict === "contradicts" ? "bad" : "") +
            "</td><td>" + esc(x.detail || x.quote || "") + "</td></tr>").join("") + "</table>" : '<p class="muted">No evidence yet.</p>') +
        "<h3>Reasoning</h3>" + (f.reasoning.length ? "<ol class=\"small\">" + f.reasoning.map(x => "<li><b>" + esc(x.app) + " " + esc(x.agent) + ":</b> " + esc(x.text) + "</li>").join("") + "</ol>" : '<p class="muted">None recorded.</p>') +
        "<h3>Checks asked of other applications</h3>" + (f.requests.length ? '<table class="t small"><tr><th>Check</th><th>Asked by</th><th>Answered by</th><th>Status</th><th>Detail</th></tr>' +
          f.requests.map(x => "<tr><td>" + esc(x.kind) + "</td><td>" + esc(x.from_app) + "</td><td>" + esc(x.to_app) + "</td><td>" + esc(x.status === "open" ? "waiting" : x.verdict) +
            "</td><td>" + esc(x.detail || "") + "</td></tr>").join("") + "</table>" : '<p class="muted">None.</p>');
    });
  }
  renderHarvest($("#hv", el));
  const s = await api("/api/commons/status");
  const c = s.commons;
  $("#cm-auto", el).checked = s.auto;
  $("#cm-policy", el).innerHTML = Object.entries(c.policies).map(([k, v]) => '<option value="' + k + '"' + (k === c.policy ? " selected" : "") + ">" + esc(v) + "</option>").join("");
  $("#cm-state", el).innerHTML = '<div class="note' + (s.state.running ? "" : " good") + '">' + (s.state.running ? "<b>Working:</b> the " + esc(s.state.role || "") + " is running." :
    "<b>Idle.</b> " + (s.state.last ? (s.state.last.error ? "Last cycle failed: " + esc(s.state.last.error) : "Last cycle: " + (s.state.last.new || 0) + " new facts, " + (s.state.last.merged || 0) +
      " merged, " + (s.state.last.checks_answered || 0) + " checks answered.") : "No cycle in this session yet.")) +
    '<br><span class="small">Shared database: <span class="mono">' + esc(c.database) + "</span>" + (c.read_only ? ' <span class="badge bad">failed its check — read-only</span>' : "") + "</span></div>";
  $("#cm-teams", el).innerHTML = '<table class="t small"><tr><th>Application</th>' + ["Strategist", "Planner", "Harvester", "Curator"].map(x => "<th>" + x + "</th>").join("") + "</tr>" +
    s.teams.map(t => "<tr><td><b>" + esc(t.name) + "</b>" + (t.app === s.app ? " (this one)" : "") + "</td>" + t.agents.map(a => "<td>" + (a.last_run ?
      cmTag(a.last_status, a.last_status === "ok" ? "good" : "bad") + " " + cmWhen(a.last_run) + '<br><span class="muted">' + esc(String(a.last_summary || "").slice(0, 140)) + "</span>" :
      '<span class="muted">' + esc(a.duty) + " — not run yet</span>") + "</td>").join("") + "</tr>").join("") + "</table>";
  const st = s.strategy && s.strategy.body;
  $("#cm-plan", el).innerHTML = !st ? '<p class="muted">Run the team to see its strategy and plan.</p>' :
    "<h3>Strategy (" + cmWhen(s.strategy.created) + ", policy: " + esc(st.policy) + ")</h3><ol>" + (st.goals || []).map(g => "<li><b>" + esc(g.goal) + "</b> — " + esc(g.why) + "</li>").join("") + "</ol>" +
    ((st.sources || []).length ? '<table class="t small"><tr><th>Source</th><th>Licence</th><th>Use</th></tr>' + st.sources.map(x => "<tr><td>" + esc(x.name) + "</td><td>" + esc(x.licence || "") + "</td><td>" + esc(x.use || "") + "</td></tr>").join("") + "</table>" : "") +
    (s.plan ? "<h3>Plan: " + esc(s.plan.summary || "") + " (" + esc(s.plan.status) + ")</h3>" + '<table class="t small"><tr><th>#</th><th>Task</th><th>Status</th><th>Items</th><th>Detail</th></tr>' +
      s.plan.tasks.map(t => "<tr><td>" + t.step + "</td><td>" + esc(t.title) + "</td><td>" + esc(t.status) + "</td><td>" + (t.items === null ? "" : t.items) + "</td><td>" + esc(t.detail || "") + "</td></tr>").join("") + "</table>" : "");
  const doms = {};
  c.by_domain.forEach(r => { (doms[r.domain] = doms[r.domain] || {})[r.status] = r.n; });
  $("#cm-db", el).innerHTML = '<div class="stats"><div class="stat"><div class="v">' + c.facts.toLocaleString() + '</div><div class="k">shared facts</div></div><div class="stat"><div class="v">' +
    c.shared.toLocaleString() + '</div><div class="k">facts with evidence from more than one application</div></div></div>' +
    '<table class="t small" style="margin-top:10px"><tr><th>Domain</th>' + Object.keys(CM_STATUS).map(x => "<th>" + x + "</th>").join("") + "</tr>" +
    Object.entries(doms).map(([d, v]) => "<tr><td>" + esc(d) + "</td>" + Object.keys(CM_STATUS).map(x => "<td>" + (v[x] || "") + "</td>").join("") + "</tr>").join("") + "</table>" +
    "<h3>Checks between applications</h3>" + (c.requests.length ? '<table class="t small"><tr><th>Asked by</th><th>Answered by</th><th>Check</th><th>Status</th><th>Count</th></tr>' +
      c.requests.map(r => "<tr><td>" + esc(r.from_app) + "</td><td>" + esc(r.to_app) + "</td><td>" + esc(s.checks[r.kind] || r.kind) + "</td><td>" + esc(r.status === "open" ? "waiting" : r.status) + "</td><td>" + r.n + "</td></tr>").join("") + "</table>" : '<p class="muted">None yet.</p>');
  $("#cm-log", el).innerHTML = s.log.length ? '<table class="t small"><tr><th>When (UTC)</th><th>Application</th><th>Agent</th><th>What it did</th><th>Time</th></tr>' + s.log.map(l => '<tr><td class="mono">' + cmWhen(l.at) +
    "</td><td>" + esc(l.app) + "</td><td>" + esc(l.role) + "</td><td>" + esc(l.message) + '</td><td class="mono">' + (l.ms === null ? "" : (l.ms / 1000).toFixed(2) + " s") + "</td></tr>").join("") + "</table>" : '<p class="muted">Nothing yet.</p>';
  clearTimeout(CM_TIMER);
  if (s.state.running && el.classList.contains("active")) CM_TIMER = setTimeout(() => renderCommons(el), 1500);
}

// ---------------------------------------------------------------- the harvesting engine, policy registry and approvals
let HV_PASS = "";            // the admin passphrase, held in this page only (never stored)
let HV_LOG = [];
const hvClass = (cls, classes) => cmTag(cls, classes[cls] && classes[cls].allowed ? "good" : "bad");
const hvState = s => cmTag(s, s === "approved" || s === "applied" || s === "harvested" || s === "refreshed" ? "good" : s === "blocked" || s === "rejected" || s === "failed" ? "bad" : "warn");
const hvPass = el => { const v = $("#hv-pass", el).value; if (v) HV_PASS = v; if (!HV_PASS) { toast("Type the admin passphrase first."); throw new Error("no passphrase"); } return HV_PASS; };

async function renderHarvest(el) {
  if (!el.dataset.ready) {
    el.dataset.ready = "1";
    el.innerHTML =
      '<div class="card" id="hv-master-card"><h2>Master control</h2><div id="hv-master"></div>' +
      '<div class="row" style="margin:10px 0"><button class="btn" id="hv-start-all">▶ Start all harvesting</button><button class="btn" id="hv-stop-all" style="background:#b42318">■ Stop all harvesting</button></div>' +
      '<details open><summary class="small">Start or stop selected</summary><p class="small muted">Tick applications and online harvesters, then <b>Start selected</b> (only the ticked ones run; ticking a harvester also turns its application on) or <b>Stop selected</b> (the ticked ones stop; the rest carry on). A running task finishes; the rest of its turn is skipped.</p>' +
      '<div id="hv-select"></div><div class="row"><button class="btn quiet" id="hv-start-sel">▶ Start selected</button><button class="btn quiet" id="hv-stop-sel">■ Stop selected</button>' +
      '<button class="btn quiet" id="hv-sel-all">Tick all</button><button class="btn quiet" id="hv-sel-none">Tick none</button></div></details></div>' +
      '<div class="card"><h2>Harvesting engine</h2><p class="small muted">One engine runs the three harvest teams in turn — language, STEM and history — so they never harvest at the same time. ' +
      "Each turn goes to the application with the most to gain: checks other applications are waiting for, a fast recent harvest, or no harvest yet; the one that just harvested waits, and one that found nothing new backs off for longer each time (less volume). " +
      "Every task is checked against the policy registry first: only sources whose licence puts no restriction on QueryBook are harvested. Everything is logged with its source and why.</p>" +
      '<div id="hv-engine"></div><h3>Online harvesters</h3><label class="row small"><input type="checkbox" id="hv-online"> Harvest from the online sources the admin approved (this application)</label><div id="hv-online-list"></div>' +
      '<h3>API keys (free)</h3><p class="small muted">Some approved sources need a free key. Keys are kept only in the shared folder on this computer (api-keys.json, owner-only) — never in the database, its backups or the logs. Saving a key needs the admin passphrase.</p><div id="hv-keys"></div></div>' +
      '<div class="card"><h2>Waiting for your approval</h2><p class="small muted">The learning agent reads the harvest record and recommends changes — bigger or smaller batches, pausing a failing task, classifying a new source. ' +
      "Nothing is changed until you, the admin, approve it here. Every decision is versioned.</p>" +
      '<div id="hv-admin"></div><div id="hv-pending"></div><details><summary class="small">Decided recommendations</summary><div id="hv-decided"></div></details></div>' +
      '<div class="card"><h2>Policy registry — sources</h2><p class="small muted">A source is harvested only when it is <b>approved</b>. Licence classes that restrict QueryBook (attribution, share-alike, non-commercial, no-derivatives, copyrighted text, terms of service, unknown) are blocked; ' +
      "approving one needs your passphrase and an explicit acceptance of the restriction. Third-party wording (quotes) is kept only from public-domain, CC0, US-federal or computed sources.</p>" +
      '<div id="hv-sources"></div><details><summary class="small">Add a source</summary><div class="row">' +
      '<input id="hv-k" type="text" placeholder="key, e.g. wikidata-cc0" aria-label="Source key"><input id="hv-n" class="grow" type="text" placeholder="name" aria-label="Source name">' +
      '<input id="hv-a" type="text" placeholder="apps (language, stem, facts)" aria-label="Applications"><input id="hv-u" type="text" placeholder="URL" aria-label="URL"></div>' +
      '<div class="row"><input id="hv-l" type="text" placeholder="licence as stated" aria-label="Licence"><select id="hv-c" aria-label="Licence class"></select>' +
      '<input id="hv-r" class="grow" type="text" placeholder="why this source" aria-label="Reason"><button class="btn quiet" id="hv-add">Add (pending until approved)</button></div></details>' +
      '<details><summary class="small">Licence classes</summary><div id="hv-classes"></div></details></div>' +
      '<div class="card"><h2>Learning — is harvesting getting faster?</h2><div id="hv-metrics"></div><div class="row"><button class="btn quiet" id="hv-review">Ask the learning agent to review now</button></div></div>' +
      '<div class="card"><h2>Harvest log</h2><p class="small muted">Every task — harvested, blocked, failed or refreshed — with its source, licence class and why. Entries are hash-chained (any later edit is detected) and archived monthly as JSON lines in the shared folder.</p>' +
      '<div class="row"><select id="hv-fa" aria-label="Application"><option value="">all applications</option><option value="language">language</option><option value="stem">stem</option><option value="facts">history</option></select>' +
      '<select id="hv-fd" aria-label="Decision"><option value="">any decision</option><option>harvested</option><option>blocked</option><option>failed</option><option>refreshed</option></select>' +
      '<button class="btn quiet" id="hv-show">Show</button><button class="btn quiet" id="hv-verify">Verify the chain</button><button class="btn quiet" id="hv-arch">Archive now</button>' +
      '<button class="btn quiet" id="hv-csv">Export CSV</button></div><div id="hv-vres"></div><div id="hv-log"></div></div>' +
      '<div class="card"><h2>Parameters and policy versions</h2><div id="hv-params"></div><details><summary class="small">Policy versions (every change, who and why)</summary><div id="hv-versions"></div></details></div>';
    const showLog = async () => {
      const r = await api("/api/harvest/log", { app: $("#hv-fa", el).value, decision: $("#hv-fd", el).value, limit: 300 });
      HV_LOG = r.log;
      $("#hv-log", el).innerHTML = r.log.length ? '<table class="t small"><tr><th>#</th><th>When (UTC)</th><th>Domain</th><th>Task</th><th>Source</th><th>Class</th><th>Decision</th><th>Items</th><th>New</th><th>Time</th><th>Why</th></tr>' +
        r.log.map(h => "<tr><td>" + h.id + '</td><td class="mono">' + cmWhen(h.at) + "</td><td>" + esc(h.domain) + "</td><td>" + esc(h.title) + '</td><td class="mono">' + esc(h.source_key || "") +
          "</td><td>" + esc(h.licence_class || "") + "</td><td>" + hvState(h.decision) + "</td><td>" + h.items + "</td><td>" + h.new + '</td><td class="mono">' + (h.seconds || 0).toFixed(2) +
          " s</td><td>" + esc(h.reason) + "</td></tr>").join("") + "</table>" : '<p class="muted">Nothing logged yet.</p>';
    };
    el._showLog = showLog;
    $("#hv-show", el).addEventListener("click", showLog);
    const control = async (action, scope) => {
      const ticked = [...el.querySelectorAll("#hv-select input[data-sel]:checked")];
      const body = { action, scope, apps: ticked.filter(x => x.dataset.kind === "app").map(x => x.dataset.sel),
        harvesters: ticked.filter(x => x.dataset.kind === "harvester").map(x => x.dataset.sel) };
      await api("/api/harvest/control", body);
      toast(action === "start" ? "Harvesting started" + (scope === "all" ? " for all applications." : " for the selection.") : "Harvesting stopped" + (scope === "all" ? " everywhere." : " for the selection."));
      renderHarvest(el);
    };
    $("#hv-start-all", el).addEventListener("click", () => control("start", "all"));
    $("#hv-stop-all", el).addEventListener("click", () => control("stop", "all"));
    $("#hv-start-sel", el).addEventListener("click", () => control("start", "selected"));
    $("#hv-stop-sel", el).addEventListener("click", () => control("stop", "selected"));
    $("#hv-sel-all", el).addEventListener("click", () => el.querySelectorAll("#hv-select input[data-sel]").forEach(x => { x.checked = true; }));
    $("#hv-sel-none", el).addEventListener("click", () => el.querySelectorAll("#hv-select input[data-sel]").forEach(x => { x.checked = false; }));
    $("#hv-online", el).addEventListener("change", e => api("/api/commons/settings", { online: e.target.checked ? "on" : "off" }).then(() => toast("Online harvesting " + (e.target.checked ? "on." : "off."))));
    $("#hv-verify", el).addEventListener("click", async () => {
      const v = await api("/api/harvest/verify", {});
      $("#hv-vres", el).innerHTML = '<div class="note ' + (v.ok ? "good" : "bad") + '">' + (v.ok ? "<b>Chain intact:</b> " + v.entries + " entries, last hash <span class=\"mono\">" + esc(String(v.last_hash).slice(0, 16)) + "…</span>"
        : "<b>Chain broken</b> at entry #" + v.broken_at + " — " + v.entries + " entries before it are intact. The record was edited outside the engine.") + "</div>";
    });
    $("#hv-arch", el).addEventListener("click", async () => { const r = await api("/api/harvest/archive", {}); toast(r.archived ? r.archived + " entries archived to " + r.folder : "Nothing new to archive."); });
    $("#hv-csv", el).addEventListener("click", () => {
      const cols = ["id", "at", "app", "domain", "action", "title", "source_key", "licence_class", "decision", "items", "new", "merged", "seconds", "reason", "budget_key", "turn_id", "policy_version", "hash"];
      const q = v => '"' + String(v === null || v === undefined ? "" : v).replace(/"/g, '""') + '"';
      const blob = new Blob([cols.join(",") + "\n" + HV_LOG.map(h => cols.map(k => q(h[k])).join(",")).join("\n")], { type: "text/csv" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "querybook-harvest-log.csv"; a.click();
    });
    $("#hv-review", el).addEventListener("click", async () => { const r = await api("/api/harvest/review", {}); toast(r.made ? r.made + " new recommendation(s) for you to decide." : "No new recommendations."); renderHarvest(el); });
    $("#hv-add", el).addEventListener("click", async () => {
      await api("/api/harvest/source_add", { passphrase: hvPass(el), key: $("#hv-k", el).value, name: $("#hv-n", el).value, apps: $("#hv-a", el).value, url: $("#hv-u", el).value,
        licence: $("#hv-l", el).value, licence_class: $("#hv-c", el).value, reason: $("#hv-r", el).value });
      toast("Source added as pending — approve it below when its licence is confirmed."); renderHarvest(el);
    });
    el.addEventListener("click", async e => {
      const b = e.target.closest("button[data-hv]");
      if (!b) return;
      const [act, id] = b.dataset.hv.split(":");
      if (act === "setpass") {
        await api("/api/harvest/admin", { new: $("#hv-new", el).value, old: $("#hv-old", el) ? $("#hv-old", el).value : "" });
        HV_PASS = $("#hv-new", el).value; toast("Admin passphrase saved (only a salted hash is kept)."); renderHarvest(el); return;
      }
      if (act === "ok" || act === "no") {
        const r = await api("/api/harvest/decide", { id: Number(id), approve: act === "ok", passphrase: hvPass(el), note: $("#hv-note-" + id, el).value });
        toast("Recommendation #" + r.id + " " + r.status + "."); renderHarvest(el); return;
      }
      if (act === "src") {
        const row = b.closest("tr");
        await api("/api/harvest/source", { key: id, status: $("select.hv-st", row).value, licence_class: $("select.hv-cl", row).value, passphrase: hvPass(el),
          reason: $("input.hv-why", row).value || "admin decision", accept_restriction: $("input.hv-acc", row).checked });
        toast("Registry updated — the change is versioned."); renderHarvest(el); return;
      }
      if (act === "key") {
        const row = b.closest("tr");
        await api("/api/harvest/key", { service: id, key: $("input.hv-kv", row).value, passphrase: hvPass(el) });
        toast("Key saved — its harvesters start on their next turn."); renderHarvest(el); return;
      }
      if (act === "dpla") {
        const row = b.closest("tr");
        const r = await api("/api/harvest/dpla_request", { email: $("input.hv-email", row).value, passphrase: hvPass(el) });
        toast(r.message); return;
      }
      if (act === "param") {
        const row = b.closest("tr");
        await api("/api/harvest/param", { key: id, value: $("input.hv-pv", row).value, passphrase: hvPass(el), reason: "set by the admin" });
        toast("Parameter saved."); renderHarvest(el);
      }
    });
  }
  const f = document.activeElement;
  if (f && el.contains(f) && /^(INPUT|SELECT|TEXTAREA)$/.test(f.tagName)) return;    // don't wipe what the admin is typing
  const s = await api("/api/harvest/status");
  const classes = s.classes;
  const names = { language: "Language", stem: "Math & Science", facts: "History & News" };
  const e = s.engine;
  $("#hv-engine", el).innerHTML = '<div class="note' + (s.auto ? " good" : "") + '">' + (s.auto ? "<b>Automatic harvesting is on</b> for this application." : "<b>Automatic harvesting is off</b> for this application — tick the box below to let the engine give it turns.") +
    ' <span class="small">Engine ' + esc(e.version) + " · policy version " + s.policy_version + " · " + s.log_entries.toLocaleString() + " log entries</span></div>" +
    '<table class="t small"><tr><th>Application</th><th>Last heard</th></tr>' + e.heartbeats.map(h => "<tr><td>" + esc(names[h.app] || h.app) + "</td><td>" +
      (h.seconds_ago < 180 ? cmTag("running", "good") : cmTag("not running")) + " " + Math.round(h.seconds_ago) + " s ago</td></tr>").join("") + "</table>" +
    "<h3>Recent turns</h3>" + (e.turns.length ? '<table class="t small"><tr><th>#</th><th>Started (UTC)</th><th>Domain</th><th>Why this turn</th><th>Result</th></tr>' + e.turns.map(t => "<tr><td>" + t.id +
      '</td><td class="mono">' + cmWhen(t.started) + "</td><td>" + esc(t.domain) + "</td><td>" + esc(t.reason) + "</td><td>" + (!t.ended ? cmTag("running", "warn") : !t.result ? "" :
        t.result.error ? cmTag("failed", "bad") + " " + esc(t.result.error) : t.result.timeout ? cmTag("timed out", "warn") :
          (t.result.new || 0) + " new, " + (t.result.checks_answered || 0) + " checks, " + (t.result.blocked || 0) + " blocked") + "</td></tr>").join("") + "</table>" : '<p class="muted">No turns yet.</p>');
  const ct = s.control, running = ct.master === "running";
  const busy = e.turns.find(t => !t.ended);
  $("#hv-master", el).innerHTML = '<div class="note ' + (running ? "good" : "bad") + '" style="font-size:1.1em"><b>' + (running ? "▶ Harvesting is ON" : "■ Harvesting is STOPPED") + "</b> — " +
    (running ? ct.apps.filter(a => a.on).length + " of 3 applications and " + ct.harvesters.filter(h => h.on).length + " of " + ct.harvesters.length + " online harvesters switched on" +
      (busy ? "; now harvesting: " + esc(busy.domain) : "; waiting for the next turn") : "no application will start a harvest until you press Start.") + "</div>";
  const tick = (kind, key, label, on, extra) => '<label class="row small" style="margin-right:14px"><input type="checkbox" data-kind="' + kind + '" data-sel="' + esc(key) + '"> ' +
    cmTag(on ? "on" : "off", on ? "good" : "") + " " + esc(label) + (extra ? ' <span class="muted">(' + esc(extra) + ")</span>" : "") + "</label>";
  $("#hv-select", el).innerHTML = "<h3>Applications</h3><div class=\"row\">" + ct.apps.map(a => tick("app", a.app, a.name, a.on)).join("") + "</div>" +
    "<h3>Online harvesters</h3><div>" + ct.harvesters.map(h => tick("harvester", h.name, h.title, h.on, names[h.app] || h.app)).join("<br>") + "</div>";
  $("#hv-online", el).checked = s.online;
  $("#hv-online-list", el).innerHTML = (s.offline_env ? '<div class="note warn small">QB_OFFLINE is set: no online harvesting in this process.</div>' : "") +
    '<table class="t small"><tr><th>Harvester</th><th>Application</th><th>Source</th><th>Progress</th></tr>' + s.harvesters.map(h => "<tr><td><b>" + esc(h.title) + '</b><br><span class="muted">' + esc(h.why) +
      "</span></td><td>" + esc(names[h.app] || h.app) + '</td><td class="mono">' + esc(h.source) + " " + (h.approved ? cmTag("approved", "good") : cmTag("not approved", "bad")) + "</td><td>" +
      (h.needs_key && !s.keys.find(k => k.service === h.needs_key && k.set) ? cmTag("waiting for its " + h.needs_key + " key", "warn") : h.cursor === null ? "not started" : h.cursor === "-1" ? cmTag("finished", "good") : "next item " + (Number(h.cursor) + 1)) + "</td></tr>").join("") + "</table>";
  $("#hv-keys", el).innerHTML = '<table class="t small"><tr><th>Service</th><th>How to get it</th><th>Key</th></tr>' + s.keys.map(k => "<tr><td><b>" + esc(k.title) + "</b><br>" +
    (k.set ? cmTag("saved " + k.hint, "good") : cmTag("not set", "warn")) + "</td><td>" + esc(k.how) +
    (k.service === "dpla" ? '<br><input class="hv-email" type="email" placeholder="your email" aria-label="Email for the DPLA key"> <button class="btn quiet" data-hv="dpla:x">Request my DPLA key</button>' : "") +
    '</td><td><input class="hv-kv" type="password" autocomplete="off" placeholder="' + (k.set ? "paste a new key to replace" : "paste the key") + '" aria-label="API key"> <button class="btn quiet" data-hv="key:' + esc(k.service) + '">Save</button></td></tr>').join("") + "</table>";
  $("#hv-admin", el).innerHTML = s.admin_set ?
    '<div class="row"><label class="row small">Admin passphrase <input id="hv-pass" type="password" autocomplete="current-password" placeholder="' + (HV_PASS ? "remembered for this page" : "needed to decide") + '"></label>' +
    '<details class="small"><summary>Change passphrase</summary><input id="hv-old" type="password" placeholder="current"> <input id="hv-new" type="password" placeholder="new (8+ characters)"> <button class="btn quiet" data-hv="setpass">Change</button></details></div>' :
    '<div class="note warn"><b>Set the admin passphrase first.</b> Only the admin can approve recommendations or change the registry. <input id="hv-new" type="password" autocomplete="new-password" placeholder="at least 8 characters"> ' +
    '<button class="btn" data-hv="setpass">Set admin passphrase</button><input id="hv-pass" type="hidden"></div>';
  $("#hv-pending", el).innerHTML = s.pending.length ? '<table class="t small"><tr><th>#</th><th>Kind</th><th>Recommendation</th><th>Why</th><th>Change</th><th>Decision</th></tr>' + s.pending.map(r => "<tr><td>" + r.id +
    "</td><td>" + cmTag(r.kind) + "</td><td><b>" + esc(r.title) + "</b></td><td>" + esc(r.rationale) + '</td><td class="mono">' + esc(JSON.stringify(r.change)) +
    '</td><td><input id="hv-note-' + r.id + '" type="text" placeholder="note (optional)"> <button class="btn" data-hv="ok:' + r.id + '">Approve</button> <button class="btn quiet" data-hv="no:' + r.id + '">Reject</button></td></tr>').join("") + "</table>" :
    '<p class="muted">Nothing waiting for you.</p>';
  $("#hv-decided", el).innerHTML = s.decided.filter(r => r.status !== "pending").map(r => '<div class="small">#' + r.id + " " + hvState(r.status) + " " + esc(r.title) + " — " + cmWhen(r.decided_at) + (r.note ? " (" + esc(r.note) + ")" : "") + "</div>").join("") || '<p class="muted small">None yet.</p>';
  const clsOpts = sel => Object.keys(classes).map(k => '<option value="' + k + '"' + (k === sel ? " selected" : "") + ">" + k + "</option>").join("");
  $("#hv-c", el).innerHTML = clsOpts("unknown");
  $("#hv-sources", el).innerHTML = '<table class="t small"><tr><th>Source</th><th>Apps</th><th>Licence</th><th>Class</th><th>Status</th><th>Why / decided</th><th>Admin decision</th></tr>' + s.sources.map(x => "<tr><td><b>" +
    (x.url ? '<a href="' + esc(x.url) + '" target="_blank" rel="noopener noreferrer">' + esc(x.name) + "</a>" : esc(x.name)) + '</b><br><span class="mono muted">' + esc(x.key) + "</span>" + (x.kind ? '<br><span class="small muted">' + esc(x.kind) + "</span>" : "") + "</td><td>" + esc(x.apps || "") + "</td><td>" +
    esc(x.licence || "") + "</td><td>" + hvClass(x.licence_class, classes) + "</td><td>" + hvState(x.status) + "</td><td>" + esc(x.reason || "") + (x.decided_by ? '<br><span class="muted">' + esc(x.decided_by) + " " + cmWhen(x.decided_at) + "</span>" : "") +
    '</td><td><select class="hv-st"><option' + (x.status === "approved" ? " selected" : "") + ">approved</option><option" + (x.status === "blocked" ? " selected" : "") + ">blocked</option><option" + (x.status === "pending" ? " selected" : "") + ">pending</option></select> " +
    '<select class="hv-cl">' + clsOpts(x.licence_class) + '</select> <input class="hv-why" type="text" placeholder="reason"> <label class="small"><input class="hv-acc" type="checkbox"> accept the restriction</label> ' +
    '<button class="btn quiet" data-hv="src:' + esc(x.key) + '">Save</button></td></tr>').join("") + "</table>";
  $("#hv-classes", el).innerHTML = '<table class="t small"><tr><th>Class</th><th>Harvested?</th><th>Why</th></tr>' + Object.entries(classes).map(([k, v]) => "<tr><td>" + esc(k) + "</td><td>" + (v.allowed ? cmTag("yes", "good") : cmTag("blocked", "bad")) + "</td><td>" + esc(v.why) + "</td></tr>").join("") + "</table>";
  $("#hv-metrics", el).innerHTML = s.metrics.length ? '<table class="t small"><tr><th>Application</th><th>Tasks</th><th>Harvested</th><th>Blocked</th><th>Failed</th><th>Items</th><th>New</th><th>New share</th><th>New facts / s</th></tr>' +
    s.metrics.map(m => "<tr><td>" + esc(names[m.app] || m.app) + "</td><td>" + m.tasks + "</td><td>" + m.harvested + "</td><td>" + m.blocked + "</td><td>" + m.failed + "</td><td>" + (m.items || 0).toLocaleString() + "</td><td>" + (m.new || 0).toLocaleString() +
      "</td><td>" + (m.new_share === null ? "" : Math.round(100 * m.new_share) + "%") + "</td><td>" + (m.facts_per_s === null ? "" : m.facts_per_s) + "</td></tr>").join("") + "</table>" +
    (s.trend.length ? "<h3>By day</h3>" + '<table class="t small"><tr><th>Day</th><th>Domain</th><th>New</th><th>Items</th><th>Seconds</th></tr>' + s.trend.map(t => '<tr><td class="mono">' + esc(t.day) + "</td><td>" + esc(t.domain) + "</td><td>" + t.new + "</td><td>" + t.items + "</td><td>" + t.seconds + "</td></tr>").join("") + "</table>" : "") :
    '<p class="muted">No harvests logged yet.</p>';
  $("#hv-params", el).innerHTML = '<table class="t small"><tr><th>Parameter</th><th>Value</th><th>What it does</th><th>Last set</th><th></th></tr>' + s.params.map(p => '<tr><td class="mono">' + esc(p.key) + '</td><td><input class="hv-pv" type="text" size="8" value="' +
    esc(JSON.stringify(p.value)) + '"></td><td>' + esc(p.description || "") + "</td><td>" + esc(p.updated_by || "") + " " + cmWhen(p.updated) + '</td><td><button class="btn quiet" data-hv="param:' + esc(p.key) + '">Save</button></td></tr>').join("") + "</table>";
  $("#hv-versions", el).innerHTML = s.versions.map(v => '<div class="small"><span class="mono">v' + v.id + " " + cmWhen(v.at) + "</span> <b>" + esc(v.actor) + "</b> " + esc(JSON.stringify(v.change)) + " — " + esc(v.reason || "") + "</div>").join("") || '<p class="muted small">No changes yet.</p>';
  if (el._showLog) el._showLog();
}

// ---------------------------------------------------------------- Devices: the device gateway
let DV = { hr: null, hrBuf: [], hrTimer: null, cam: null };
const dvBadge = s => cmTag(s, s === "built-in" || s.startsWith("built-in") ? "good" : s.startsWith("import") ? "good" : s === "API" ? "" : "warn");

async function renderDevices(el) {
  if (!el.dataset.ready) {
    el.dataset.ready = "1";
    el.innerHTML =
      '<div class="card"><h2>Devices</h2><p class="small muted">One documented API for cameras, phones, smart glasses, robots, wearables, motion suits, eye trackers and microphones. ' +
      "Each device is registered here and gets its own key; it sends <b>observations, not recordings</b> — heart rate, a fixation, an object seen, a sentence heard, a contact force. " +
      "Devices that record people, body signals or location need the person's consent recorded at registration. Raw events are kept for a limited time; summaries stay.</p>" +
      '<div id="dv-state"></div><div class="row"><label class="row small"><input type="checkbox" id="dv-lan"> Accept devices on my home network (device API only — the application pages stay on this computer)</label>' +
      '<label class="row small">Keep raw events <input id="dv-days" type="number" min="1" max="3650" style="width:5em"> days</label>' +
      '<a class="btn quiet" href="/api/devices/openapi.json" target="_blank" rel="noopener">API description (OpenAPI)</a></div></div>' +
      '<div class="card"><h2>Supported devices</h2><p class="small muted"><b>built-in</b> works in this page; <b>import</b> reads the device\'s export files; <b>bridge</b> is a small program in the <span class="mono">bridges</span> folder that runs beside the device and sends events (test it on your device); <b>API</b> means the device\'s own software posts events.</p><div id="dv-cat"></div></div>' +
      '<div class="card"><h2>Register a device</h2><div class="row"><select id="dv-model" aria-label="Device model"></select><input id="dv-name" type="text" placeholder="name, e.g. Lab glasses" aria-label="Device name"></div>' +
      '<div class="row small">Records: <label><input type="checkbox" class="dv-c" value="people"> people (faces, voices, gaze)</label> <label><input type="checkbox" class="dv-c" value="body"> body signals</label> <label><input type="checkbox" class="dv-c" value="location"> location</label></div>' +
      '<div class="row"><input id="dv-subject" type="text" placeholder="person recorded (name)" aria-label="Person recorded"><label class="row small"><input type="checkbox" id="dv-consent"> They agreed to be recorded (consent)</label>' +
      '<input id="dv-pass" type="password" placeholder="admin passphrase" aria-label="Admin passphrase"><button class="btn" id="dv-reg">Register</button></div><div id="dv-key"></div></div>' +
      '<div class="card"><h2>My devices</h2><div id="dv-list"></div></div>' +
      '<div class="card"><h2>Live connections</h2><h3>Heart-rate sensor (Bluetooth — Polar H10, Verity Sense and any standard strap)</h3>' +
      '<div class="row"><select id="dv-hr-dev" aria-label="Registered device"></select><button class="btn" id="dv-hr-go">Connect heart-rate sensor</button><button class="btn quiet" id="dv-hr-stop">Disconnect</button><span id="dv-hr-now" class="mono"></span></div>' +
      '<p class="small muted">Uses the browser\'s Bluetooth (Chrome or Edge). Readings are sent every 5 seconds to the selected device record.</p>' +
      '<h3>Camera controls (webcams with pan, tilt and zoom — Insta360 Link 2 Pro, Logitech MX Brio)</h3><div class="row"><button class="btn" id="dv-cam-go">Start camera</button><button class="btn quiet" id="dv-cam-stop">Stop</button></div>' +
      '<video id="dv-cam" autoplay playsinline muted style="max-width:420px;display:none;border-radius:8px"></video><div id="dv-ptz"></div></div>' +
      '<div class="card"><h2>Import a device file</h2><div class="row"><select id="dv-imp-dev" aria-label="Registered device"></select><select id="dv-fmt" aria-label="Format">' +
      '<option value="apple-health">Apple Health export.xml (Apple Watch)</option><option value="arkit-csv">ARKit face CSV (iPhone, Live Link Face)</option>' +
      '<option value="pupil-csv">Pupil Labs gaze.csv / fixations.csv (Neon)</option><option value="bvh">BVH motion capture (Rokoko and others)</option><option value="jsonl">JSON-lines events (any device)</option></select></div>' +
      '<div class="row"><input id="dv-file" type="file" aria-label="File"><span class="small muted">or a path on this computer (for large files)</span><input id="dv-path" class="grow" type="text" placeholder="/path/to/export.xml" aria-label="Path"><button class="btn" id="dv-imp">Import</button></div><div id="dv-imp-out"></div></div>' +
      '<div class="card"><h2>Observations</h2><div class="row"><select id="dv-kind" aria-label="Kind"><option value="">all kinds</option></select><input id="dv-label" type="text" placeholder="when did I last see… (label)" aria-label="Label">' +
      '<button class="btn quiet" id="dv-find">Show</button></div><div id="dv-obs"></div></div>' +
      '<div class="card"><h2>For developers</h2><pre class="mono small" id="dv-curl" style="white-space:pre-wrap"></pre></div>';
    $("#dv-reg", el).onclick = async () => {
      const r = await api("/api/devices/register", { model: $("#dv-model", el).value, name: $("#dv-name", el).value, consent: [...el.querySelectorAll(".dv-c:checked")].map(x => x.value),
        subject: $("#dv-subject", el).value, consent_confirmed: $("#dv-consent", el).checked, passphrase: $("#dv-pass", el).value });
      $("#dv-key", el).innerHTML = '<div class="note good"><b>Device registered.</b> Its key (shown only now — copy it into the device or bridge):<br><span class="mono">' + esc(r.token) + "</span></div>";
      renderDevices(el);
    };
    $("#dv-lan", el).onchange = async e => { try { await api("/api/devices/settings", { lan: e.target.checked, passphrase: $("#dv-pass", el).value }); } finally { renderDevices(el); } };
    $("#dv-days", el).onchange = e => api("/api/devices/settings", { retain_days: Number(e.target.value) });
    $("#dv-find", el).onclick = () => dvObs(el);
    el.addEventListener("click", async e => {
      const b = e.target.closest("button[data-dv]");
      if (!b) return;
      const [act, id] = b.dataset.dv.split(":");
      if (act === "revoke" && confirm("Revoke this device's key? It will no longer be able to send anything.")) { await api("/api/devices/revoke", { id: Number(id), passphrase: $("#dv-pass", el).value }); renderDevices(el); }
      if (act === "pick") { $("#dv-model", el).value = id; $("#dv-name", el).focus(); }
    });
    $("#dv-imp", el).onclick = async () => {
      const f = $("#dv-file", el).files[0], body = { device_id: Number($("#dv-imp-dev", el).value), format: $("#dv-fmt", el).value };
      if ($("#dv-path", el).value.trim()) body.path = $("#dv-path", el).value.trim();
      else if (f) body.text = await f.text();
      else return toast("Choose a file or give its path.");
      const r = await api("/api/devices/import", body);
      $("#dv-imp-out", el).innerHTML = '<div class="note good">Imported: <span class="mono">' + esc(JSON.stringify(r)) + "</span></div>"; dvObs(el);
    };
    $("#dv-hr-go", el).onclick = () => dvHeart(el);
    $("#dv-hr-stop", el).onclick = () => { if (DV.hr) DV.hr.disconnect(); DV.hr = null; clearInterval(DV.hrTimer); $("#dv-hr-now", el).textContent = "disconnected"; };
    $("#dv-cam-go", el).onclick = () => dvCamera(el);
    $("#dv-cam-stop", el).onclick = () => { if (DV.cam) DV.cam.getTracks().forEach(t => t.stop()); DV.cam = null; $("#dv-cam", el).style.display = "none"; $("#dv-ptz", el).innerHTML = ""; };
  }
  const [s, cat] = await Promise.all([api("/api/devices/status"), api("/api/devices/catalog")]);
  $("#dv-state", el).innerHTML = '<div class="note' + (s.lan.running ? " warn" : "") + '"><b>Device gateway ' + esc(s.version) + "</b> · " + s.devices.filter(d => !d.revoked).length + " active device(s)" +
    (s.latest_heart ? " · latest heart rate " + s.latest_heart.bpm + " bpm (" + cmWhen(s.latest_heart.minute) + ")" : "") +
    (s.lan.running ? '<br>Network listener ON — devices send to <span class="mono">http://' + esc((s.lan.addresses[0] || "this-computer")) + ":" + s.lan.port + '/api/devices/ingest</span> (device API only; use on a trusted home network)' : "<br>Network listener off — devices on this computer send to this page's address.") + "</div>";
  $("#dv-lan", el).checked = s.lan.running; $("#dv-days", el).value = s.settings.retain_days;
  $("#dv-cat", el).innerHTML = '<table class="t small"><tr><th>Device</th><th>Type</th><th>Records</th><th>How it connects</th><th>Status</th><th></th></tr>' + cat.devices.map(d => "<tr><td><b>" + esc(d.name) + "</b></td><td>" + esc(d.category) +
    "</td><td>" + esc(d.captures.join(", ") || "—") + "</td><td>" + esc(d.how) + "</td><td>" + dvBadge(d.status) + '</td><td><button class="btn quiet" data-dv="pick:' + esc(d.id) + '">Register</button></td></tr>').join("") + "</table>";
  if (!$("#dv-model", el).options.length) $("#dv-model", el).innerHTML = cat.devices.map(d => '<option value="' + esc(d.id) + '">' + esc(d.name) + "</option>").join("");
  const active = s.devices.filter(d => !d.revoked);
  $("#dv-list", el).innerHTML = s.devices.length ? '<table class="t small"><tr><th>#</th><th>Name</th><th>Model</th><th>Consent</th><th>Person</th><th>Key</th><th>Last seen</th><th>Events</th><th></th></tr>' + s.devices.map(d => "<tr><td>" + d.id + "</td><td>" + esc(d.name) +
    "</td><td>" + esc(d.model_name) + "</td><td>" + esc(d.consent.join(", ") || "none") + "</td><td>" + esc(d.subject || "") + '</td><td class="mono">…' + esc(d.token_hint) + "</td><td>" + cmWhen(d.last_seen) + "</td><td>" + d.events +
    "</td><td>" + (d.revoked ? cmTag("revoked", "bad") : '<button class="btn quiet" data-dv="revoke:' + d.id + '">Revoke</button>') + "</td></tr>").join("") + "</table>" : '<p class="muted">No devices registered yet.</p>';
  const opts = list => list.map(d => '<option value="' + d.id + '">' + esc(d.name) + " (#" + d.id + ")</option>").join("") || '<option value="">register a device first</option>';
  $("#dv-hr-dev", el).innerHTML = opts(active.filter(d => d.consent.includes("body")));
  $("#dv-imp-dev", el).innerHTML = opts(active);
  if ($("#dv-kind", el).options.length < 2) $("#dv-kind", el).innerHTML += ["detection", "transcript", "gaze", "touch", "face", "pose", "daily", "ecg", "location", "note"].map(k => "<option>" + k + "</option>").join("");
  const base = location.origin;
  $("#dv-curl", el).textContent = "# send events (any language — this is curl)\ncurl -X POST " + base + "/api/devices/ingest \\\n  -H 'Authorization: Bearer qbd_YOUR_DEVICE_KEY' -H 'Content-Type: application/json' \\\n" +
    "  -d '{\"events\": [{\"kind\": \"detection\", \"data\": {\"label\": \"cup\", \"confidence\": 0.91}},\n                {\"kind\": \"heart\", \"t\": 1760900000, \"data\": {\"bpm\": 72}}]}'\n\n# Python bridges: see the bridges folder (qb_device_client.py) — event kinds: " + Object.keys(cat.kinds).join(", ");
  dvObs(el);
}

async function dvObs(el) {
  const label = $("#dv-label", el).value.trim();
  if (label) {
    const r = await api("/api/devices/last_seen", { label });
    $("#dv-obs", el).innerHTML = r.observation ? '<div class="note good">Last seen <b>' + esc(label) + "</b>: " + cmWhen(r.observation.t) + " (device #" + r.observation.device_id + ")</div>" : '<p class="muted">Never seen “' + esc(label) + "”.</p>";
    return;
  }
  const r = await api("/api/devices/observations", { kind: $("#dv-kind", el).value, limit: 100 });
  $("#dv-obs", el).innerHTML = r.observations.length ? '<table class="t small"><tr><th>When (UTC)</th><th>Device</th><th>Kind</th><th>What</th><th>Value</th><th>Detail</th><th>From</th></tr>' + r.observations.map(o => '<tr><td class="mono">' + cmWhen(o.t) +
    "</td><td>#" + (o.device_id || "") + "</td><td>" + esc(o.kind) + "</td><td>" + esc(o.label) + "</td><td>" + esc(o.value === null ? "" : o.value + (o.unit ? " " + o.unit : "")) + "</td><td>" + esc(o.detail || "") + "</td><td>" + esc(o.source) + "</td></tr>").join("") + "</table>" : '<p class="muted">No observations yet.</p>';
}

async function dvHeart(el) {
  const did = Number($("#dv-hr-dev", el).value);
  if (!did) return toast("Register a device with body-signal consent first.");
  if (!navigator.bluetooth) return toast("This browser has no Bluetooth access. Use Chrome or Edge.");
  const dev = await navigator.bluetooth.requestDevice({ filters: [{ services: ["heart_rate"] }] });
  const server = await dev.gatt.connect();
  const ch = await (await server.getPrimaryService("heart_rate")).getCharacteristic("heart_rate_measurement");
  DV.hr = dev.gatt; DV.hrBuf = [];
  ch.addEventListener("characteristicvaluechanged", e => {
    const v = e.target.value, flags = v.getUint8(0), wide = flags & 1;
    const bpm = wide ? v.getUint16(1, true) : v.getUint8(1);
    let i = wide ? 3 : 2; if (flags & 0x08) i += 2;
    const rr = []; if (flags & 0x10) for (; i + 1 < v.byteLength; i += 2) rr.push(Math.round(v.getUint16(i, true) * 1000 / 1024));
    DV.hrBuf.push({ kind: "heart", t: Date.now() / 1000, data: rr.length ? { bpm, rr_ms: rr } : { bpm } });
    $("#dv-hr-now", el).textContent = "♥ " + bpm + " bpm — " + esc(dev.name || "sensor");
  });
  await ch.startNotifications();
  clearInterval(DV.hrTimer);
  DV.hrTimer = setInterval(async () => { if (!DV.hrBuf.length) return; const ev = DV.hrBuf.splice(0); try { await api("/api/devices/ingest", { device_id: did, events: ev }); } catch (e) { DV.hrBuf.unshift(...ev); } }, 5000);
  toast("Heart-rate sensor connected.");
}

async function dvCamera(el) {
  try { DV.cam = await navigator.mediaDevices.getUserMedia({ video: { pan: true, tilt: true, zoom: true } }); }
  catch (e) { DV.cam = await navigator.mediaDevices.getUserMedia({ video: true }); }
  const v = $("#dv-cam", el); v.srcObject = DV.cam; v.style.display = "block";
  const track = DV.cam.getVideoTracks()[0], caps = track.getCapabilities ? track.getCapabilities() : {}, set = track.getSettings();
  const ctl = ["zoom", "pan", "tilt"].filter(k => caps[k]);
  $("#dv-ptz", el).innerHTML = '<p class="small">' + esc(track.label || "camera") + "</p>" + (ctl.length ? ctl.map(k => '<label class="row small">' + k + ' <input type="range" data-ptz="' + k + '" min="' + caps[k].min + '" max="' + caps[k].max +
    '" step="' + (caps[k].step || 1) + '" value="' + (set[k] !== undefined ? set[k] : caps[k].min) + '"></label>').join("") : '<p class="small muted">This camera or browser offers no pan, tilt or zoom control.</p>');
  el.querySelectorAll("input[data-ptz]").forEach(r => r.oninput = () => track.applyConstraints({ advanced: [{ [r.dataset.ptz]: Number(r.value) }] }).catch(() => {}));
}

// ---------------------------------------------------------------- Agents: pick your agents, learn from the best, Open Claw as knowledge
const AG = { status: null, skill: null, pass: "", touch: [], stroke: 0, motion: null };
const agPass = el => ($("#ag-pass", el) && $("#ag-pass", el).value) || AG.pass;
const agB64 = blob => new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });

// any recording → 16 kHz mono 16-bit WAV (the Listener measures WAV; the browser decodes every other format)
async function agWav(blob) {
  const ac = new (window.AudioContext || window.webkitAudioContext)();
  const buf = await ac.decodeAudioData(await blob.arrayBuffer()); ac.close();
  const sr = 16000, n = Math.min(Math.floor(buf.duration * sr), sr * 90), ch = buf.numberOfChannels, src = buf.sampleRate;
  const out = new DataView(new ArrayBuffer(44 + 2 * n)), w = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); out.setUint32(4, 36 + 2 * n, true); w(8, "WAVEfmt "); out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, sr, true); out.setUint32(28, 2 * sr, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); w(36, "data"); out.setUint32(40, 2 * n, true);
  const data = [...Array(ch).keys()].map(c => buf.getChannelData(c));
  for (let i = 0; i < n; i++) { const j = Math.floor(i * src / sr); let v = 0; for (let c = 0; c < ch; c++) v += data[c][j] || 0; v = Math.max(-1, Math.min(1, v / ch)); out.setInt16(44 + 2 * i, v * 32767, true); }
  return agB64(new Blob([out.buffer], { type: "audio/wav" }));
}
async function agRecord(kind, seconds, note) {                     // live microphone or camera, for a few seconds
  const stream = await navigator.mediaDevices.getUserMedia(kind === "audio" ? { audio: true } : { video: true });
  try {
    if (kind === "video") return await agFrames(stream, seconds, note);
    const rec = new MediaRecorder(stream), parts = [];
    rec.ondataavailable = e => parts.push(e.data); rec.start();
    for (let s = seconds; s > 0; s--) { note("Listening… " + s + " s"); await new Promise(r => setTimeout(r, 1000)); }
    await new Promise(r => { rec.onstop = r; rec.stop(); });
    return { wav_b64: await agWav(new Blob(parts, { type: rec.mimeType })) };
  } finally { stream.getTracks().forEach(t => t.stop()); }
}
// per-frame measures of a video (file or camera): movement, brightness, contrast, colour — computed here, only numbers are sent
async function agFrames(source, seconds, note) {
  const v = document.createElement("video"); v.muted = true; v.playsInline = true;
  if (source instanceof Blob) v.src = URL.createObjectURL(source); else v.srcObject = source;
  await new Promise((ok, bad) => { v.onloadedmetadata = ok; v.onerror = () => bad(new Error("this video cannot be played here")); });
  const c = document.createElement("canvas"); c.width = 64; c.height = 36; const g = c.getContext("2d", { willReadFrequently: true });
  const fps = 6, frames = []; let prev = null;
  const grab = () => {
    g.drawImage(v, 0, 0, 64, 36); const d = g.getImageData(0, 0, 64, 36).data, n = d.length / 4;
    let sum = 0, sum2 = 0, sat = 0, mo = 0; const lum = new Float32Array(n);
    for (let i = 0; i < n; i++) { const r = d[4 * i], gg = d[4 * i + 1], b = d[4 * i + 2], L = 0.299 * r + 0.587 * gg + 0.114 * b; lum[i] = L; sum += L; sum2 += L * L;
      sat += Math.max(r, gg, b) - Math.min(r, gg, b); if (prev) mo += Math.abs(L - prev[i]); }
    const m = sum / n; frames.push({ motion: prev ? +(mo / n).toFixed(3) : 0, bright: +m.toFixed(2), contrast: +Math.sqrt(Math.max(0, sum2 / n - m * m)).toFixed(2), sat: +(sat / n).toFixed(2) }); prev = lum;
  };
  if (source instanceof Blob) {                                      // a file: step through it, frame by frame
    const dur = Math.min(v.duration || 0, 120);
    for (let t = 0; t < dur; t += 1 / fps) { v.currentTime = t; await new Promise(r => { v.onseeked = r; }); grab(); if (frames.length % 30 === 0) note("Watching… " + t.toFixed(0) + " of " + dur.toFixed(0) + " s"); }
    URL.revokeObjectURL(v.src);
  } else {
    await v.play();
    for (let i = 0; i < seconds * fps; i++) { grab(); if (i % fps === 0) note("Watching… " + Math.ceil(seconds - i / fps) + " s"); await new Promise(r => setTimeout(r, 1000 / fps)); }
  }
  return { frames: frames.slice(1), fps };
}
async function agMotion(seconds, note) {                              // the phone's own accelerometer
  if (window.DeviceMotionEvent && DeviceMotionEvent.requestPermission) await DeviceMotionEvent.requestPermission();
  const acc = [], t0 = performance.now();
  const on = e => { const a = e.accelerationIncludingGravity || {}; acc.push(Math.hypot(a.x || 0, a.y || 0, a.z || 0)); };
  window.addEventListener("devicemotion", on);
  for (let s = seconds; s > 0; s--) { note("Move now… " + s + " s"); await new Promise(r => setTimeout(r, 1000)); }
  window.removeEventListener("devicemotion", on);
  if (acc.length < 10) throw new Error("no motion sensor here — use a phone, or Devices");
  return { acc, rate_hz: acc.length / ((performance.now() - t0) / 1000) };
}
// the input area for one agent; returns a function that collects its input
function agInput(host, agent, feeds) {
  const note = m => { $("[data-agnote]", host).textContent = m; };
  const parts = {
    text: '<textarea data-ag="text" rows="5" placeholder="Paste text here — or choose any document, or give a web page address"></textarea>' +
      '<div class="row"><input type="file" data-ag="file" aria-label="Document"><input type="url" data-ag="url" class="grow" placeholder="https://… (a web page)"></div>',
    audio: '<div class="row"><input type="file" data-ag="file" accept="audio/*,video/*" aria-label="Recording"><button class="btn quiet" data-agrec="audio">🎙 Record 15 s</button></div>',
    video: '<div class="row"><input type="file" data-ag="file" accept="video/*" aria-label="Video"><button class="btn quiet" data-agrec="video">📷 Camera 10 s</button></div>',
    touch: '<canvas data-agpad width="480" height="200" style="width:100%;max-width:480px;border:1px dashed var(--line);border-radius:10px;touch-action:none;background:var(--panel)"></canvas>' +
      '<div class="row"><button class="btn quiet" data-agclear>Clear</button><button class="btn quiet" data-agdev="touch">✋ From tactile devices</button><span class="small muted">draw, write or tap on the pad (pen and touch pressure are measured)</span></div>',
    motion: '<div class="row"><button class="btn quiet" data-agrec="motion">📱 Record phone motion 10 s</button><button class="btn quiet" data-agdev="motion">⌚ From body devices</button></div>',
    sensor: '<textarea data-ag="csv" rows="4" placeholder="CSV with a header row, e.g. time,ethanol,temperature"></textarea><div class="row"><input type="file" data-ag="file" accept=".csv,.txt,.json" aria-label="Sensor file"><label class="small">samples per second <input data-ag="rate" type="number" value="1" step="any" style="width:70px"></label></div>',
    live: '<select data-ag="feed">' + (feeds || []).map(f => '<option value="' + f.id + '">' + esc(f.name) + " (" + f.n + " readings)</option>").join("") + "</select>" +
      '<span class="small muted"> add feeds under Live data below</span>',
  };
  host.innerHTML = (parts[agent] || "") + '<div class="small muted" data-agnote aria-live="polite"></div>';
  let captured = null;
  host.querySelectorAll("[data-agrec]").forEach(b => b.onclick = async () => {
    try { captured = b.dataset.agrec === "motion" ? await agMotion(10, note) : await agRecord(b.dataset.agrec, b.dataset.agrec === "audio" ? 15 : 10, note); note("Captured — now add it as an exemplar or score it."); }
    catch (e) { note("Could not capture: " + e.message); }
  });
  host.querySelectorAll("[data-agdev]").forEach(b => b.onclick = async () => {
    try { captured = await api("/api/agents/from_devices", { kind: b.dataset.agdev }); note(captured.count + " readings from the Device gateway."); } catch (e) { note(e.message); }
  });
  const pad = $("[data-agpad]", host);
  if (pad) {
    AG.touch = []; AG.stroke = 0; const g = pad.getContext("2d"); let down = false;
    const pt = e => { const r = pad.getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.width, t: Math.round(e.timeStamp), p: e.pressure, w: e.width || 1, stroke: AG.stroke }; };
    pad.onpointerdown = e => { down = true; AG.stroke++; pad.setPointerCapture(e.pointerId); AG.touch.push(pt(e)); };
    pad.onpointermove = e => { if (!down) return; const a = AG.touch[AG.touch.length - 1], b = pt(e); AG.touch.push(b);
      g.lineWidth = 1 + 6 * (b.p || 0.5); g.lineCap = "round"; g.strokeStyle = "#1f6feb"; g.beginPath(); g.moveTo(a.x * pad.width, a.y * pad.width); g.lineTo(b.x * pad.width, b.y * pad.width); g.stroke(); };
    pad.onpointerup = pad.onpointercancel = () => { down = false; note(AG.stroke + " stroke(s), " + AG.touch.length + " points"); };
    $("[data-agclear]", host).onclick = () => { AG.touch = []; AG.stroke = 0; g.clearRect(0, 0, pad.width, pad.height); note(""); };
  }
  return async () => {
    if (captured) { const c = captured; captured = null; return c; }
    const f = $('[data-ag="file"]', host), file = f && f.files[0];
    if (agent === "text") {
      if (file) return { file_b64: await agB64(file), name: file.name };
      if ($('[data-ag="url"]', host).value.trim()) return { url: $('[data-ag="url"]', host).value.trim() };
      return { text: $('[data-ag="text"]', host).value };
    }
    if (agent === "audio") { if (!file) throw new Error("choose a recording or record one"); note("Converting the sound…"); return { wav_b64: await agWav(file) }; }
    if (agent === "video") { if (!file) throw new Error("choose a video or use the camera"); return await agFrames(file, 0, note); }
    if (agent === "touch") { if (AG.touch.length < 5) throw new Error("draw or tap on the pad first"); return { points: AG.touch.slice() }; }
    if (agent === "motion") throw new Error("record motion or read it from devices first");
    if (agent === "sensor") { const t = file ? await file.text() : $('[data-ag="csv"]', host).value; return t.trim().startsWith("{") ? JSON.parse(t) : { csv: t, rate_hz: Number($('[data-ag="rate"]', host).value) || 1 }; }
    if (agent === "live") return { feed_id: Number($('[data-ag="feed"]', host).value) };
    return {};
  };
}

async function renderAgents(el) {
  if (!el.dataset.ready) {
    el.dataset.ready = "1";
    el.innerHTML =
      '<div class="card"><h2>Agents</h2><p class="small muted">Agents you pick and choose. They take in text, sound, video, live data, touch, body motion and any other sensor, ' +
      "and learn from <b>best-in-class examples</b> of people with superior skills: each skill's exemplars become a profile of mastery, and every new sample is scored against it, " +
      "with advice on what to change. Open Claw agents, skills and tools are taken in as <b>knowledge</b> — read, never run.</p><div id=\"ag-purity\"></div>" +
      '<div class="row small"><label>Admin passphrase (when one is set) <input id="ag-pass" type="password" autocomplete="off" style="width:200px"></label></div></div>' +
      '<div class="card"><h2>1 · Pick your agents</h2><div id="ag-list"></div></div>' +
      '<div class="card"><h2>2 · Skills — learn from the best</h2><div class="row"><input id="ag-sname" placeholder="New skill, e.g. Persuasive speaking" class="grow">' +
      '<select id="ag-sagent"></select><button class="btn" id="ag-sadd">Add skill</button></div><div id="ag-skills"></div><div id="ag-skill"></div></div>' +
      '<div class="card"><h2>3 · Open Claw — agents, skills and tools as knowledge</h2><p class="small muted">Open Claw agents are made for language models. Here they are read by deterministic ' +
      "programs: checklists, commands, required tools, terms and links are kept; every line that instructs a model (persona, tone, prompts, “respond with…”) is <b>quarantined</b> — " +
      "kept for you to inspect, never used; scripts are listed, never run.</p>" +
      '<div class="row"><input id="ag-cq" class="grow" placeholder="Search ClawHub skills, e.g. calendar, pdf, weather"><button class="btn" id="ag-csearch">Search</button>' +
      '<button class="btn quiet" id="ag-cindex">Index every ClawHub skill</button><label class="small"><input type="checkbox" id="ag-csafe" checked> skip suspicious</label></div><div id="ag-cres"></div>' +
      '<div class="row"><button class="btn quiet" id="ag-clocal">Read my Open Claw installation</button><input id="ag-chome" class="grow" placeholder="(default ~/.openclaw — another folder needs the admin passphrase)">' +
      '<label class="small"><input type="checkbox" id="ag-cpers"> include USER.md and memory</label></div>' +
      '<div class="row"><input type="file" id="ag-cup" accept=".zip,.md" aria-label="Skill folder (zip) or SKILL.md"><button class="btn quiet" id="ag-cupb">Import a skill folder (.zip) or SKILL.md</button></div>' +
      '<div class="small" id="ag-cmsg" aria-live="polite"></div><div id="ag-pbs"></div><div id="ag-pb"></div></div>' +
      '<div class="card"><h2>4 · Live data</h2><p class="small muted">A data address (JSON or CSV) read on a schedule while QueryBook runs. Addresses of AI-model services are refused.</p>' +
      '<div class="row"><input id="ag-fname" placeholder="name" style="width:140px"><input id="ag-furl" class="grow" placeholder="https://…/data.json"><input id="ag-fpath" placeholder="JSON path (e.g. data.price) or CSV column" style="width:220px">' +
      '<input id="ag-fevery" type="number" value="300" min="30" style="width:80px" title="seconds"><button class="btn" id="ag-fadd">Add feed</button></div><div id="ag-feeds"></div></div>';
    $("#ag-sadd", el).onclick = async () => { const s = await api("/api/agents/skill_add", { name: $("#ag-sname", el).value, agent: $("#ag-sagent", el).value }); $("#ag-sname", el).value = ""; AG.skill = s.id; renderAgents(el); };
    $("#ag-csearch", el).onclick = async () => {
      const r = await api("/api/agents/claw/search", { q: $("#ag-cq", el).value, safe: $("#ag-csafe", el).checked });
      $("#ag-cres", el).innerHTML = agClawTable(r.results);
    };
    onEnter($("#ag-cq", el), () => $("#ag-csearch", el).click());
    $("#ag-cindex", el).onclick = async () => {
      $("#ag-cmsg", el).textContent = "Indexing every ClawHub skill (names and summaries only)…";
      const r = await api("/api/agents/claw/sync_index", { safe: $("#ag-csafe", el).checked });
      $("#ag-cmsg", el).textContent = r.total + " ClawHub skills in the local index" + (r.complete ? "" : " (more remain — run again to continue)") + ". Search filters the index too.";
      const ix = await api("/api/agents/claw/index?limit=200&q=" + encodeURIComponent($("#ag-cq", el).value));
      $("#ag-cres", el).innerHTML = '<p class="small muted">' + ix.total + " skills" + (ix.total > 200 ? " — showing 200; type to filter" : "") + "</p>" + agClawTable(ix.items);
    };
    $("#ag-cres", el).onclick = async e => {
      const b = e.target.closest("[data-cimp]"); if (!b) return;
      const r = await api("/api/agents/claw/import", { slug: b.dataset.cimp });
      $("#ag-cmsg", el).textContent = r.duplicate ? "Already imported." : "Imported " + r.name + ": " + r.kept + " usable lines kept, " + r.quarantined + " model instructions quarantined.";
      agPlaybooks(el);
    };
    $("#ag-clocal", el).onclick = async () => {
      const r = await api("/api/agents/claw/local", { home: $("#ag-chome", el).value.trim() || null, include_personal: $("#ag-cpers", el).checked, passphrase: agPass(el) });
      $("#ag-cmsg", el).textContent = r.found ? "Open Claw at " + r.home + ": " + r.agents + " agent(s), " + r.skills + " skill(s) and the tools catalogue imported as knowledge." + (r.config_error ? " " + r.config_error : "")
        : "No Open Claw installation at " + r.home + ".";
      agPlaybooks(el);
    };
    $("#ag-cupb", el).onclick = async () => {
      const f = $("#ag-cup", el).files[0]; if (!f) return toast("Choose a skill folder (.zip) or a SKILL.md.");
      const r = await api("/api/agents/claw/upload", { name: f.name, data_b64: await agB64(f) });
      $("#ag-cmsg", el).textContent = r.duplicate ? "Already imported." : "Imported " + r.name + ": " + r.kept + " kept, " + r.quarantined + " quarantined.";
      agPlaybooks(el);
    };
    $("#ag-pbs", el).onclick = async e => {
      const v = e.target.closest("[data-pbv]"), d = e.target.closest("[data-pbd]"), t = e.target.closest("[data-pbt]");
      if (v) agPlaybook(el, v.dataset.pbv);
      if (d && confirm("Remove this playbook?")) { await api("/api/agents/playbook_delete", { id: Number(d.dataset.pbd) }); agPlaybooks(el); $("#ag-pb", el).innerHTML = ""; }
      if (t) { await api("/api/agents/playbook_pick", { id: Number(t.dataset.pbt), enabled: t.checked }); }
    };
    $("#ag-fadd", el).onclick = async () => {
      const r = await api("/api/agents/feed_add", { name: $("#ag-fname", el).value, url: $("#ag-furl", el).value, path: $("#ag-fpath", el).value, every_s: Number($("#ag-fevery", el).value) });
      toast(r.error ? "Feed added, but: " + r.error : "Feed added — first reading " + r.value); agFeeds(el);
    };
    $("#ag-feeds", el).onclick = async e => {
      const p = e.target.closest("[data-fp]"), d = e.target.closest("[data-fd]");
      if (p) { const r = await api("/api/agents/feed_poll", { id: Number(p.dataset.fp) }); toast(r.error || "Reading: " + r.value); }
      if (d && confirm("Remove this feed and its readings?")) await api("/api/agents/feed_delete", { id: Number(d.dataset.fd) });
      agFeeds(el);
    };
    $("#ag-list", el).onchange = async e => {
      const c = e.target.closest("[data-agpick]"); if (!c) return;
      try { await api("/api/agents/pick", { agent: c.dataset.agpick, enabled: c.checked, passphrase: agPass(el) }); } catch (err) { c.checked = !c.checked; }
      renderAgents(el);
    };
    $("#ag-skills", el).onclick = e => { const b = e.target.closest("[data-sk]"); if (b) { AG.skill = Number(b.dataset.sk); renderAgents(el); } };
  }
  const st = AG.status = await api("/api/agents/status");
  const pu = st.purity;
  $("#ag-purity", el).innerHTML = '<div class="note ' + (pu.ok ? "good" : "bad") + '"><b>' + (pu.ok ? "✔ Non-LLM reasoning" : "⚠ Check the agents") + "</b> — " + esc(pu.statement) +
    " <span class=\"small\">(" + pu.llm_hosts_blocked + " AI-model services blocked · imported lines kept " + (pu.imported_lines_kept || 0) + ", quarantined " + (pu.imported_lines_quarantined || 0) + ")</span></div>";
  $("#ag-list", el).innerHTML = '<table class="t small"><tr><th>Use</th><th>Agent</th><th>Sense</th><th>Takes in</th><th>Measures / does</th><th>Network</th><th>Reasoning</th></tr>' +
    st.agents.map(a => '<tr><td><input type="checkbox" data-agpick="' + a.id + '"' + (a.enabled ? " checked" : "") + ' aria-label="Use ' + esc(a.name) + '"></td><td>' + a.icon + " <b>" + esc(a.name) + "</b></td><td>" +
      esc(a.sense) + "</td><td>" + esc(a.takes) + "</td><td>" + esc(a.measures) + "</td><td>" + esc(a.network) + "</td><td>" + cmTag("deterministic · no LLM", "good") + "</td></tr>").join("") + "</table>";
  const sel = $("#ag-sagent", el);
  if (!sel.options.length) sel.innerHTML = st.agents.filter(a => ["text", "audio", "video", "live", "touch", "motion", "sensor"].includes(a.id)).map(a => '<option value="' + a.id + '">measured by ' + esc(a.name) + " (" + esc(a.sense) + ")</option>").join("");
  const sk = (await api("/api/agents/skills")).skills;
  $("#ag-skills", el).innerHTML = sk.length ? '<div class="row">' + sk.map(s => '<button class="btn ' + (s.id === AG.skill ? "" : "quiet") + '" data-sk="' + s.id + '">' + esc(s.name) +
    ' <span class="small">· ' + s.exemplars + " exemplar(s)</span></button>").join("") + "</div>" : '<p class="muted">No skills yet — name one above and choose the agent that measures it.</p>';
  if (AG.skill && sk.find(s => s.id === AG.skill)) await agSkill(el, sk.find(s => s.id === AG.skill));
  else $("#ag-skill", el).innerHTML = "";
  agPlaybooks(el); agFeeds(el);
}
function agClawTable(items) {
  return items && items.length ? '<table class="t small"><tr><th>Skill</th><th>Summary</th><th>Version</th><th>Owner</th><th></th></tr>' + items.map(r => "<tr><td><b>" + esc(r.name) + '</b><br><span class="mono">' +
    esc(r.slug) + "</span></td><td>" + esc(r.summary || "") + "</td><td>" + esc(r.version || "") + "</td><td>" + esc(r.owner || "") + '</td><td><button class="btn quiet" data-cimp="' + esc(r.slug) + '">Import as knowledge</button></td></tr>').join("") + "</table>"
    : '<p class="muted">Nothing found.</p>';
}
async function agSkill(el, s) {
  const box = $("#ag-skill", el), agent = AG.status.agents.find(a => a.id === s.agent);
  const [ex, pr, sm, fd, pbs] = await Promise.all([api("/api/agents/exemplars?skill_id=" + s.id), api("/api/agents/profile?skill_id=" + s.id), api("/api/agents/samples?skill_id=" + s.id),
    api("/api/agents/feeds"), api("/api/agents/playbooks")]);
  const p = pr.profile, defs = (await api("/api/agents/features"))[s.agent] || {};
  box.innerHTML = '<h3>' + esc(s.name) + ' <span class="small muted">measured by ' + agent.icon + " " + esc(agent.name) + '</span> <button class="btn quiet small" data-skdel>Delete skill</button></h3>' +
    '<div class="grid2"><div><h4>Add a best-in-class exemplar — or score your own sample</h4><div data-aginput></div>' +
    '<div class="row small"><input data-ex="title" placeholder="title (e.g. Keynote, 2019)" class="grow"><input data-ex="performer" placeholder="performer"></div>' +
    '<div class="row small"><input data-ex="source" placeholder="source (address or reference)" class="grow"><select data-ex="licence"><option value="">licence…</option><option>own work</option><option>public domain</option>' +
    '<option>Creative Commons</option><option>government work</option><option>permission from the owner</option></select><label>rating <select data-ex="rating"><option>5</option><option selected>4</option><option>3</option><option>2</option><option>1</option></select></label></div>' +
    '<div class="row"><button class="btn" data-exadd>➕ Add as exemplar</button><button class="btn bigbtn" data-score>🎯 Score my sample</button></div>' +
    (s.agent === "text" ? '<div class="row small">Playbook terms to cover: <select data-attach><option value="">none</option>' + pbs.playbooks.filter(b => b.enabled).map(b => '<option value="' + b.id + '"' + (b.id === s.playbook_id ? " selected" : "") + ">" +
      esc(b.name) + "</option>").join("") + "</select></div>" : "") + '<div data-result></div></div>' +
    "<div><h4>Mastery profile " + (p ? "v" + p.version + " · " + esc(p.status) + (p.adopted ? "" : ' <button class="btn quiet small" data-adopt="' + p.version + '">Adopt</button>') : "") + "</h4>" +
    (p ? '<table class="t small"><tr><th>Measure</th><th>Masters (median)</th><th>Range</th><th>Weight</th></tr>' + Object.entries(p.profile.features).sort((a, b) => b[1].importance - a[1].importance).map(([k, v]) =>
      "<tr><td>" + esc((defs[k] || [k])[0]) + "</td><td>" + v.median + " " + esc((defs[k] || [0, ""])[1]) + "</td><td>" + v.p10 + " – " + v.p90 + '</td><td><div class="meter"><i style="width:' + Math.round(100 * v.importance / Math.max(...Object.values(p.profile.features).map(x => x.importance))) + '%"></i></div></td></tr>').join("") + "</table>"
      : '<p class="muted">No exemplars yet. Add recordings or samples of people with superior skill — the profile is built from them.</p>') +
    "<h4>Exemplars (" + ex.exemplars.length + ")</h4>" + (ex.exemplars.length ? '<table class="t small">' + ex.exemplars.map(x => "<tr><td><b>" + esc(x.title) + "</b> " + esc(x.performer || "") + '<br><span class="muted">' + esc(x.licence) +
      (x.source ? " · " + esc(x.source) : "") + "</span></td><td>" + "★".repeat(x.rating) + '</td><td><button class="btn quiet small" data-exdel="' + x.id + '">Remove</button></td></tr>').join("") + "</table>" : "") +
    "<h4>Your samples</h4>" + (sm.samples.length ? '<table class="t small">' + sm.samples.map(x => "<tr><td>" + esc(x.created) + "</td><td>" + esc(x.title) + "</td><td><b>" + (x.overall === null ? "—" : x.overall) + "</b> " + esc(x.verdict || "") +
      '<br><span class="small muted">' + x.advice.map(esc).join("<br>") + "</span></td></tr>").join("") + "</table>" : '<p class="muted">None yet.</p>') + "</div></div>";
  const collect = agInput($("[data-aginput]", box), s.agent, fd.feeds);
  const v = k => $('[data-ex="' + k + '"]', box).value;
  $("[data-skdel]", box).onclick = async () => { if (confirm("Delete this skill, its exemplars and samples?")) { await api("/api/agents/skill_delete", { id: s.id }); AG.skill = null; renderAgents(el); } };
  $("[data-exadd]", box).onclick = async () => {
    let input; try { input = await collect(); } catch (e) { return toast(e.message, true); }
    const r = await api("/api/agents/exemplar_add", { skill_id: s.id, input, title: v("title") || "exemplar", performer: v("performer"), source: v("source"), licence: v("licence"), rating: Number(v("rating")) });
    toast(r.duplicate ? "That exemplar is already in." : "Exemplar added — profile v" + r.profile.version + " from " + r.profile.exemplars + " exemplar(s)."); renderAgents(el);
  };
  $("[data-score]", box).onclick = async () => {
    let input; try { input = await collect(); } catch (e) { return toast(e.message, true); }
    const r = await api("/api/agents/sample", { skill_id: s.id, input, title: v("title") || "my sample" });
    $("[data-result]", box).innerHTML = r.overall === null ? '<div class="note">' + esc(r.note || "No profile yet.") + "</div>" :
      '<div class="note ' + (r.overall >= 70 ? "good" : r.overall < 50 ? "bad" : "") + '"><b>' + r.overall + " / 100 — " + esc(r.verdict) + "</b> (profile v" + r.profile_version + ", " + esc(r.profile_status) + ")" +
      (r.closest_exemplar ? "<br>Closest to: <b>" + esc(r.closest_exemplar.title) + "</b> " + esc(r.closest_exemplar.performer || "") : "") +
      (r.advice.length ? "<ul>" + r.advice.map(a => "<li>" + esc(a.text) + "</li>").join("") + "</ul>" : "<br>Every measure is within the masters' range.") + "</div>";
  };
  box.querySelectorAll("[data-exdel]").forEach(b => b.onclick = async () => { await api("/api/agents/exemplar_delete", { id: Number(b.dataset.exdel) }); renderAgents(el); });
  const ad = $("[data-adopt]", box); if (ad) ad.onclick = async () => { await api("/api/agents/adopt", { skill_id: s.id, version: Number(ad.dataset.adopt), passphrase: agPass(el) }); renderAgents(el); };
  const at = $("[data-attach]", box); if (at) at.onchange = () => api("/api/agents/skill_attach", { id: s.id, playbook_id: at.value ? Number(at.value) : null });
}
async function agPlaybooks(el) {
  const r = await api("/api/agents/playbooks");
  $("#ag-pbs", el).innerHTML = r.playbooks.length ? '<table class="t small"><tr><th>Use</th><th>Kind</th><th>Name</th><th>From</th><th>Kept</th><th>Quarantined</th><th></th></tr>' + r.playbooks.map(b =>
    '<tr><td><input type="checkbox" data-pbt="' + b.id + '"' + (b.enabled ? " checked" : "") + ' aria-label="Use"></td><td>' + esc(b.kind) + "</td><td><b>" + esc(b.name) + "</b> " + esc(b.version || "") +
    '<br><span class="small muted">' + esc(b.description || "") + "</span></td><td>" + esc(b.origin) + "</td><td>" + b.kept + "</td><td>" + (b.quarantined ? cmTag(b.quarantined + " model line(s)", "warn") : "0") +
    '</td><td><button class="btn quiet small" data-pbv="' + b.id + '">View</button><button class="btn quiet small" data-pbd="' + b.id + '">Remove</button></td></tr>').join("") + "</table>"
    : '<p class="muted">No Open Claw agents, skills or tools imported yet.</p>';
}
async function agPlaybook(el, id) {
  const b = await api("/api/agents/playbook?id=" + id), d = b.data, k = d.kept || {};
  const list = (title, xs, mono) => xs && xs.length ? "<h4>" + title + " (" + xs.length + ')</h4><ul class="small">' + xs.slice(0, 80).map(x => "<li" + (mono ? ' class="mono"' : "") + ">" + esc(x) + "</li>").join("") + "</ul>" : "";
  $("#ag-pb", el).innerHTML = '<div class="note"><h3>' + esc(b.name) + " " + esc(b.version || "") + '</h3><p class="small">' + esc(b.description || "") + "</p>" +
    '<p class="small"><b>How it is used:</b> ' + esc(d.how_used || "") + "</p>" + (b.warnings.length ? '<p class="small">' + b.warnings.map(w => cmTag(w, "warn")).join(" ") + "</p>" : "") +
    (d.requires && (d.requires.bins || []).length ? '<p class="small"><b>Needs tools:</b> ' + esc(d.requires.bins.concat(d.requires.anyBins || []).join(", ")) + (d.requires.env && d.requires.env.length ? " · <b>settings:</b> " + esc(d.requires.env.join(", ")) : "") + "</p>" : "") +
    (d.tools_config ? '<p class="small"><b>Tools configuration:</b> <span class="mono">' + esc(JSON.stringify(d.tools_config)) + "</span><br><b>Plugins:</b> " + esc((d.plugins || []).join(", ") || "none") +
      " · <b>MCP servers:</b> " + esc((d.mcp_servers || []).join(", ") || "none") + " · <b>Tools its skills use:</b> " + esc((d.skill_tools || []).join(", ") || "none") + "</p>" : "") +
    list("Checklist steps", k.steps) + list("Commands — listed, never run", k.commands, true) + list("Facts and notes", k.facts) + list("Key terms", k.terms) + list("Links", k.links, true) +
    (d.resources && d.resources.length ? "<h4>Files</h4><ul class=\"small\">" + d.resources.map(r => "<li><span class=\"mono\">" + esc(r.path) + "</span> · " + esc(r.format) + (r.note ? " · " + cmTag(r.note, "warn") : "") + "</li>").join("") + "</ul>" : "") +
    (d.quarantined && d.quarantined.length ? "<h4>Quarantined — instructions for a language model, not used (" + d.quarantined.length + ')</h4><ul class="small muted">' +
      d.quarantined.slice(0, 80).map(q => "<li>" + esc(q.line) + " <i>(" + esc(q.why) + (q.file ? ", " + esc(q.file) : "") + ")</i></li>").join("") + "</ul>" : "") + "</div>";
}
async function agFeeds(el) {
  const r = await api("/api/agents/feeds");
  $("#ag-feeds", el).innerHTML = r.feeds.length ? '<table class="t small"><tr><th>Feed</th><th>Every</th><th>Readings</th><th>Latest</th><th>Last read</th><th></th></tr>' + r.feeds.map(f => "<tr><td><b>" + esc(f.name) +
    '</b><br><span class="mono small">' + esc(f.url) + (f.path ? " · " + esc(f.path) : "") + "</span></td><td>" + f.every_s + " s</td><td>" + f.n + "</td><td>" + (f.latest === null ? "—" : f.latest) + "</td><td>" + esc(f.last || "") +
    (f.error ? "<br>" + cmTag(f.error, "bad") : "") + '</td><td><button class="btn quiet small" data-fp="' + f.id + '">Read now</button><button class="btn quiet small" data-fd="' + f.id + '">Remove</button></td></tr>').join("") + "</table>"
    : '<p class="muted">No live feeds yet.</p>';
}
