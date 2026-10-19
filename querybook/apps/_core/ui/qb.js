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
      '<div class="card"><h2>Harvesting engine</h2><p class="small muted">One engine runs the three harvest teams in turn — language, STEM and history — so they never harvest at the same time. ' +
      "Each turn goes to the application with the most to gain: checks other applications are waiting for, a fast recent harvest, or no harvest yet; the one that just harvested waits, and one that found nothing new backs off for longer each time (less volume). " +
      "Every task is checked against the policy registry first: only sources whose licence puts no restriction on QueryBook are harvested. Everything is logged with its source and why.</p>" +
      '<div id="hv-engine"></div></div>' +
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
    (x.url ? '<a href="' + esc(x.url) + '" target="_blank" rel="noopener noreferrer">' + esc(x.name) + "</a>" : esc(x.name)) + '</b><br><span class="mono muted">' + esc(x.key) + "</span></td><td>" + esc(x.apps || "") + "</td><td>" +
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
