// QueryBook Control Panel page.
"use strict";
let S = null, pending = null;
const NAMES = { language: "Language Builder", stem: "Math, Science & Engineering", facts: "History & News" };
const level = l => l === "error" ? "bad" : l === "warn" ? "warn" : "good";

function tabs() {
  const show = id => { $$("nav.tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === id)); $$("section.panel").forEach(s => s.classList.toggle("active", s.id === id));
    try { localStorage.setItem("qb-control-tab", id); } catch (e) { } if (id === "audit") loadAudit(); if (id === "self") loadSelf().catch(e => toast(e.message)); if (id === "exemplars") loadExemplars().catch(e => toast(e.message)); if (id === "bulk") loadBulk().catch(e => toast(e.message)); };
  $$("nav.tabs button").forEach(b => b.onclick = () => show(b.dataset.tab));
  let t = "overview"; try { t = localStorage.getItem("qb-control-tab") || t; } catch (e) { }
  show($("#" + t) ? t : "overview");
}

async function load(quiet) {
  try { S = quiet ? await (await fetch("/api/panel/status")).json() : await api("/api/panel/status"); } catch (e) { return; }
  if (!S || !S.apps) return;
  renderApps(); renderAlerts(); renderMonitor(); renderHarvest(); renderRules();
  const run = S.apps.filter(a => a.running).length;
  $("#hdr-state").textContent = run + " of 3 running · harvesting " + S.control.master + " · " + S.alerts.length + " alert(s)";
}

function renderApps() {
  $("#apps").innerHTML = S.apps.map(a => {
    const lt = a.last_turn && a.last_turn.result;
    return `<div class="appcard"><h3><span class="dot ${a.running ? (a.health === "fail" ? "bad" : "on") : "off"}"></span>${esc(a.name)}</h3>
      <div class="kv"><b>State</b><span>${a.running ? "running" + (a.version ? " · v" + esc(a.version) : "") : (a.installed ? "not running" : "not installed here")}</span>
      <b>Health</b><span>${a.health ? `<span class="badge ${level(a.health === "fail" ? "error" : a.health === "warn" ? "warn" : "ok")}">${esc(a.health)}</span>` : "—"}</span>
      <b>Harvesting</b><span>${a.harvest_on ? "on" : "off"}${a.heartbeat_s !== null ? " · checked in " + Math.round(a.heartbeat_s) + " s ago" : ""}</span>
      <b>Facts</b><span>${a.facts.toLocaleString()} (${esc(a.domain)})</span>
      <b>Last turn</b><span class="small">${a.last_turn ? esc(a.last_turn.started) + (lt ? ` — ${lt.new || 0} new, ${lt.merged || 0} merged${lt.filtered ? ", " + lt.filtered + " filtered out" : ""}${lt.on_target ? ", " + lt.on_target + " on target" : ""}` : " (running)") : "—"}</span></div>
      <div class="btns">${a.running ? `<a class="btn quiet" href="${esc(a.url)}" target="_blank" rel="noopener" style="padding:6px 11px;font-size:14px;border-radius:8px;text-decoration:none">Open</a>
        <button class="btn quiet" data-app="${a.app}" data-act="harvest">Harvest now</button><button class="btn secondary" data-app="${a.app}" data-act="stop">Stop</button>`
        : `<button class="btn" data-app="${a.app}" data-act="start" ${a.installed ? "" : "disabled"}>Start</button>`}</div></div>`;
  }).join("");
  $$("#apps [data-act]").forEach(b => b.onclick = async () => {
    if (b.dataset.act === "stop" && !confirm("Stop " + NAMES[b.dataset.app] + "?")) return;
    const r = await api("/api/panel/app", { app: b.dataset.app, action: b.dataset.act });
    toast(r.summary); setTimeout(() => load(true), b.dataset.act === "start" ? 4000 : 1200);
  });
}

function renderAlerts() {
  const all = $("#alerts-all").checked, show = rows => rows.length ? rows.map(x => `<div class="alert ${x.level}"><span class="badge ${level(x.level)}">${esc(x.level)}</span>
      <div class="txt">${esc(x.text)}<div class="muted small">first ${esc(x.first)} · last ${esc(x.last)}${x.status !== "open" ? " · " + esc(x.status) : ""}</div></div>
      ${x.status === "open" ? `<button class="btn quiet" data-dismiss="${x.id}">Clear</button>` : ""}</div>`).join("") : `<p class="muted">No ${all ? "" : "open "}alerts.</p>`;
  $("#alert-n").textContent = S.alerts.length;
  if (all) api("/api/panel/alerts?all=1").then(r => { $("#alerts").innerHTML = show(r.alerts); bindDismiss(); });
  else { $("#alerts").innerHTML = show(S.alerts); bindDismiss(); }
}
function bindDismiss() { $$("[data-dismiss]").forEach(b => b.onclick = async () => { await api("/api/panel/alerts_clear", { id: +b.dataset.dismiss }); load(true); }); }

function renderMonitor() {
  const o = S.overview, run = S.apps.filter(a => a.running).length;
  $("#last-check").textContent = S.last_check ? "last check " + S.last_check : "first check in a few seconds";
  $("#stats").innerHTML = [["Applications running", run + " / 3"], ["Harvesting", S.control.master], ["Shared facts", o.facts.toLocaleString()],
    ["Confirmed by 2+ apps", o.shared.toLocaleString()], ["Open alerts", S.alerts.length], ["Target", S.rules.target_text === "none (everything)" ? "none" : "set"],
    ["Filter", S.rules.filter_text === "none (everything)" ? "none" : "set"]].map(([k, v]) => `<div class="stat"><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`).join("");
  const doms = Object.entries(o.by_domain), max = Math.max(1, ...doms.map(([, v]) => Object.values(v).reduce((a, b) => a + b, 0)));
  $("#domains").innerHTML = doms.length ? doms.map(([d, v]) => { const n = Object.values(v).reduce((a, b) => a + b, 0);
    return `<div class="row small" style="margin:4px 0"><span style="width:90px">${esc(d)}</span><div class="bar grow"><i style="width:${100 * n / max}%"></i></div>
      <span style="width:240px" class="muted">${n.toLocaleString()} — ${Object.entries(v).map(([s, k]) => esc(s) + " " + k).join(", ")}</span></div>`; }).join("") : `<p class="muted">No shared facts yet.</p>`;
  $("#turns").innerHTML = o.turns.length ? `<table class="t"><tr><th>When</th><th>App</th><th>Result</th><th>Why its turn</th></tr>` + o.turns.map(t => {
    const r = t.result || {};
    return `<tr><td class="small">${esc(t.started)}</td><td>${esc(NAMES[t.app] || t.app)}</td><td class="small">${t.ended ? (r.timeout ? "timed out" : `${r.new || 0} new, ${r.merged || 0} merged` +
      (r.filtered ? `, ${r.filtered} filtered out` : "") + (r.on_target ? `, ${r.on_target} on target` : "") + (r.blocked ? `, ${r.blocked} blocked/skipped` : "")) : "running"}</td>
      <td class="small muted">${esc(t.reason)}</td></tr>`; }).join("") + "</table>" : `<p class="muted">No harvest turns yet.</p>`;
}

function checks(el, items, name, sel) {
  const keep = new Set($$("input:checked", el).map(i => i.value));
  el.innerHTML = items.map(([v, label]) => `<label><input type="checkbox" name="${name}" value="${esc(v)}" ${(sel ? sel.includes(v) : keep.has(v)) ? "checked" : ""}> ${esc(label)}</label>`).join("");
}
const picked = el => $$("input:checked", el).map(i => i.value);

function renderHarvest() {
  const m = $("#h-master"); m.textContent = "harvesting " + S.control.master; m.className = "badge " + (S.control.master === "running" ? "good" : "warn");
  if (!$("#h-apps").children.length) {
    checks($("#h-apps"), S.control.apps.map(a => [a.app, a.name]), "h-app");
    checks($("#h-harvesters"), S.harvesters.map(h => [h.name, h.title + " (" + (NAMES[h.app] || h.app) + ")"]), "h-hv");
  }
}

let rulesShown = null;
function renderRules() {
  const R = S.rules, t = R.target, f = R.filter;
  $("#t-now").textContent = R.target_text; $("#f-now").textContent = R.filter_text;
  const sig = JSON.stringify([t, f]);
  if (sig === rulesShown) return;                // do not overwrite what the user is typing unless the rules changed
  rulesShown = sig;
  $("#t-topics").value = t.topics.join(", "); $("#t-sources").value = t.sources.join(", ");
  $("#t-only").checked = t.only; $("#t-boost").value = t.boost;
  checks($("#t-apps"), Object.entries(NAMES), "t-app", t.apps);
  checks($("#t-harvesters"), S.harvesters.map(h => [h.name, h.title]), "t-hv", t.harvesters);
  $("#f-ex").value = f.exclude_words.join(", "); $("#f-req").value = f.require_words.join(", ");
  $("#f-y1").value = f.years ? f.years[0] : ""; $("#f-y2").value = f.years ? f.years[1] : "";
  checks($("#f-domains"), [["language", "language"], ["stem", "stem"], ["history", "history"]], "f-dom", f.domains);
  checks($("#f-lic"), S.licence_classes.map(c => [c, c]), "f-lic", f.licence_classes);
}

function filterRules() {
  const y1 = $("#f-y1").value, y2 = $("#f-y2").value;
  return { exclude_words: $("#f-ex").value, require_words: $("#f-req").value, years: y1 && y2 ? [+y1, +y2] : null,
           domains: picked($("#f-domains")), licence_classes: picked($("#f-lic")) };
}

async function diag(section) {
  const r = await api("/api/panel/diagnose", { section });
  const el = $("#diag-" + section) || $("#diag-all");
  el.innerHTML = `<div class="note ${r.overall === "fail" ? "bad" : r.overall === "ok" ? "good" : ""}"><b>Diagnostics (${esc(section)}): ${esc(r.overall.toUpperCase())}</b>
    <span class="muted small"> · ${esc(r.at)}</span> <button class="btn quiet" style="padding:2px 8px;font-size:13px" data-clear-diag>Clear</button>
    ${r.checks.map(c => `<div class="ck"><span class="badge ${c.status === "ok" ? "good" : c.status === "warn" ? "warn" : "bad"}">${esc(c.status)}</span><span class="grow">${esc(c.name)}</span>
      <span class="muted">${esc(c.detail)}</span></div>`).join("")}</div>`;
  $("[data-clear-diag]", el).onclick = () => { el.innerHTML = ""; };
}

// ---- Self-Knowledge Layer
const SK_BADGE = { "built and tested": "good", "partly built": "warn", "specified, not yet built": "", "not planned (by design)": "",
  "not in this application": "", "description, not a capability": "" };
const skSrc = s => (s || []).map(x => `${esc(x.file)}${x.line ? ":" + x.line : ""}`).join(", ");
async function loadSelf() {
  const r = await api("/api/self");
  $("#sk-counts").innerHTML = Object.entries(r.counts).map(([k, v]) => `<span class="badge ${SK_BADGE[k] || ""}">${v} ${esc(k)}</span>`).join(" ") +
    ` <span class="muted small">${esc(r.layer)} ${esc(r.version)} · ${esc(r.codebase)}</span>`;
  $("#sk-contra").innerHTML = r.contradictions.length ? `<div class="note bad"><b>Contradictions — these statements would not be true, so QueryBook will not make them until fixed:</b>
    ${r.contradictions.map(c => `<div>${esc(c)}</div>`).join("")}</div>` : `<div class="note good">No contradictions: every claim is backed by code that exists.</div>`;
  $("#sk-aspects").innerHTML = `<table class="t small"><tr><th>Aspect</th><th>Status</th><th>What QueryBook says</th><th>Sources</th><th>Design</th></tr>` +
    r.aspects.map(a => `<tr><td><b>${esc(a.name)}</b></td><td><span class="badge ${SK_BADGE[a.label] || ""}">${esc(a.label)}</span></td><td>${esc(a.text)}</td>
      <td class="mono">${skSrc(a.sources.filter(s => s.found))}</td><td>${esc(a.sections.join("; "))}</td></tr>`).join("") + "</table>";
  $("#sk-process").innerHTML = `<ol class="small">${r.process.map(p => `<li><b>${esc(p.step)}</b> — ${esc(p.what)} <span class="muted">(${esc(p.sections.join("; "))})</span></li>`).join("")}</ol>`;
  $("#sk-sections").innerHTML = `<table class="t small"><tr><th>§</th><th>Section</th><th>Status</th><th>Note</th><th>Sources</th></tr>` +
    r.sections.map(s => `<tr><td>${esc(s.section)}</td><td>${esc(s.title)}</td><td><span class="badge ${SK_BADGE[s.label] || ""}">${esc(s.label)}</span></td>
      <td>${esc(s.note || "")}</td><td class="mono">${skSrc(s.sources.filter(x => x.found))}</td></tr>`).join("") + "</table>";
}
// ---- exemplar library: best-in-class examples, approved by the admin
const exPc = x => x === null || x === undefined ? "—" : (Math.round(x * 100) / 100).toFixed(2);
async function loadExemplars() {
  const r = await api("/api/exemplars"), s = r.summary;
  $("#ex-summary").innerHTML = `<p class="small">${s.takes} takes in <span class="mono">${esc(s.folder)}</span></p>` + (Object.keys(s.skills).length ?
    `<table class="t small"><tr><th>Skill</th><th>Items</th><th>Takes</th><th>Exemplars</th><th>Candidates</th><th>Also ran</th><th>Rejected</th><th>From</th></tr>` +
    Object.entries(s.skills).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td>${v.items}</td><td>${v.takes}</td><td>${v.exemplar}</td><td>${v.candidate}</td><td>${v.also_ran}</td>
      <td>${v.rejected}</td><td>${esc(Object.entries(v.origins).map(([o, n]) => o + " ×" + n).join(", "))}</td></tr>`).join("") + "</table>" : `<p class="muted small">No exemplars yet.</p>`);
  try { const cs = await api("/api/campaigns"), on = cs.tools.filter(t => t.on);
    $("#ex-gen").innerHTML = (cs.runner.alive ? `<span class="badge good">running</span> ${esc(cs.runner.note || "")}` : `<span class="badge">not running</span>`) +
      ` · tools on: ${on.length ? on.map(t => esc(t.title)).join(", ") : "none"} · Google source ${cs.source.approved ? "approved" : "not approved"}`; } catch (e) { $("#ex-gen").textContent = e.message; }
  const p = (await api("/api/exemplars/proposals")).proposals;
  $("#ex-proposals").innerHTML = p.length ? `<table class="t small"><tr><th>Skill</th><th>Item</th><th>Proposed take</th><th>Score</th><th>Current exemplar</th><th></th></tr>` +
    p.map(x => `<tr><td class="mono">${esc(x.skill)}</td><td>${esc(x.item)}</td><td class="mono"><a href="/api/exemplars/file?id=${esc(x.proposed)}" target="_blank" rel="noopener">${esc(x.proposed)}</a></td>
      <td>${exPc(x.overall)}</td><td class="mono">${esc(x.current || "—")} ${x.current ? exPc(x.current_overall) : ""}</td>
      <td><button class="btn" data-exok="${esc(x.proposed)}">Approve</button></td></tr>`).join("") + "</table>" +
    `<button class="btn quiet" id="ex-okall">Approve all ${p.length}</button>` : `<p class="muted small">Nothing waiting.</p>`;
  $$("[data-exok]").forEach(b => b.onclick = () => exApprove([b.dataset.exok]));
  if ($("#ex-okall")) $("#ex-okall").onclick = () => exApprove(p.map(x => x.proposed));
}
// ---- bulk harvesting: datasets, agents, scaffold slots
const BK_STATE = { done: "good", running: "good", paused: "warn", stopped: "warn", failed: "bad", blocked: "bad" };
const bytes = n => n > 1e9 ? (n / 1e9).toFixed(1) + " GB" : n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.round(n / 1e3) + " KB";
async function loadBulk() {
  const r = await api("/api/bulk");
  const picked = new Set($$("[data-bk]:checked").map(b => b.dataset.bk));
  $("#bk-summary").innerHTML = `<span class="pill">${fmt(r.total)} bulk facts</span><span class="pill">+${fmt(r.last_minute)} last min</span>` +
    `<span class="pill">+${fmt(r.last_hour)} last hr</span><span class="pill">${bytes(r.bytes)} on disk</span>` +
    `<span class="pill">runner: ${r.runner.alive ? "running · " + esc(r.runner.note || "") : "stopped"}</span>`;
  $("#bk-table").innerHTML = `<table class="t small"><tr><th></th><th>Dataset</th><th>Area</th><th>Source · licence</th><th>State</th><th>Facts</th><th>Rate</th><th>Parts</th></tr>` +
    r.datasets.map(d => `<tr><td><input type="checkbox" data-bk="${esc(d.key)}" ${d.approved ? "" : "disabled"} ${picked.has(d.key) ? "checked" : ""}></td>
      <td><b>${esc(d.title)}</b><div class="small muted">${esc(d.why)} — ${esc(d.approx)}</div></td><td>${esc(d.area)}</td>
      <td class="small">${esc(d.source)}<br>${esc(d.licence)}${d.approved ? "" : `<br><span class="badge bad">not approved</span> ${esc(d.approval)}`}</td>
      <td><span class="badge ${BK_STATE[d.state] || ""}">${esc(d.state)}</span>${d.error ? `<div class="small muted">${esc(d.error)}</div>` : ""}</td>
      <td>${fmt(d.facts)}<div class="small muted">${bytes(d.bytes)}</div></td><td class="small">+${fmt(d.last_minute)}/min<br>+${fmt(d.last_hour)}/hr</td>
      <td class="small">${d.parts.map(p => `${esc(p.name)}: ${fmt(p.rows)} rows${p.done ? " ✓" : ""}`).join("<br>")}</td></tr>`).join("") + "</table>";
  const se = r.datasets.find(d => d.key === "wikidata-series");
  $("#bk-slots").innerHTML = se && se.slots && se.slots.length ? se.slots.map(x => `${esc(x.series)}: ${fmt(x.filled)} of ${fmt(x.expected)} editions filled`).join(" · ")
    : "Not filled yet — start “Recurring events” (Wikidata answers one query a minute).";
}
async function exApprove(ids) {
  let n = 0;
  try { for (const id of ids) { await api("/api/exemplars/approve", { id, passphrase: $("#ex-pass").value, note: "approved in the Control Panel" }); n++; } toast(n + " approved."); }
  catch (e) { toast((n ? n + " approved; then: " : "") + e.message); }
  loadExemplars();
}
async function listTakes() {
  const r = await api("/api/exemplars?skill=" + encodeURIComponent($("#ex-skill").value.trim()));
  $("#ex-takes").innerHTML = `<table class="t small"><tr><th>Item</th><th>Take</th><th>Status</th><th>Score</th><th>Checks</th><th>Origin</th><th></th></tr>` +
    r.takes.map(t => `<tr><td>${esc(t.item)}</td><td class="mono"><a href="/api/exemplars/file?id=${esc(t.id)}" target="_blank" rel="noopener">${esc(t.id)}</a></td><td>${esc(t.status)}</td>
      <td>${exPc(t.overall)}</td><td>${t.checks.map(c => `<span class="badge ${c.ok ? "good" : "bad"}" title="${esc(c.detail)}">${esc(c.name)}</span>`).join(" ")}</td>
      <td>${esc(t.label)}</td><td>${t.status === "rejected" ? "" : `<button class="btn quiet" data-exno="${esc(t.id)}">Reject</button>`}</td></tr>`).join("") + "</table>";
  $$("[data-exno]").forEach(b => b.onclick = async () => { try { await api("/api/exemplars/reject", { id: b.dataset.exno, passphrase: $("#ex-pass").value, reason: "rejected in the Control Panel" }); listTakes(); } catch (e) { toast(e.message); } });
}
async function askSelf() {
  const q = $("#sk-q").value.trim(); if (!q) return;
  const r = await api("/api/self/ask?q=" + encodeURIComponent(q) + "&level=" + $("#sk-level").value);
  $("#sk-answer").innerHTML = `<div class="note"><b>${esc(q)}</b><div>${esc(r.answer)}</div>
    ${r.source_text ? `<div class="muted small">Sources: ${esc(r.source_text)}</div>` : ""}${r.sections.length ? `<div class="muted small">Design: ${esc(r.sections.join("; "))}</div>` : ""}</div>`;
}

async function loadAudit() {
  const r = await api("/api/panel/audit");
  $("#a-out").innerHTML = (r.hidden_before ? `<p class="muted small">View cleared at ${esc(r.hidden_before)} — ${r.total} entries kept in all.</p>` : "") +
    (r.audit.length ? `<table class="t"><tr><th>When</th><th>Who</th><th>Action</th><th>Details</th><th>Outcome</th></tr>` + r.audit.map(x =>
      `<tr><td class="small">${esc(x.at)}</td><td>${esc(x.actor)}</td><td>${esc(x.action)}</td><td class="small mono">${esc(x.detail)}</td>
       <td class="small"><span class="badge ${x.ok ? "good" : "bad"}">${x.ok ? "done" : "failed"}</span> ${esc(x.result)}</td></tr>`).join("") + "</table>" : `<p class="muted">Nothing since the view was cleared.</p>`);
}

// ---------------------------------------------------------------- the assistant
const SUGG = ["status", "any alerts?", "harvest now", "stop all harvesting", "focus on volcanoes in history", "exclude football", "find Einstein", "run diagnostics", "help"];
function chatMsg(role, text, did) {
  const d = document.createElement("div"); d.className = "msg " + role; d.textContent = text;
  if (did) { const s = document.createElement("span"); s.className = "did"; s.textContent = "✓ did: " + did + " (in the audit trail)"; d.appendChild(s); }
  $("#c-log").appendChild(d); $("#c-log").scrollTop = $("#c-log").scrollHeight;
}
async function say(text) {
  text = (text || $("#c-in").value).trim(); if (!text) return;
  $("#c-in").value = ""; chatMsg("you", text);
  const r = await api("/api/panel/chat", { message: text, passphrase: $("#c-pass").value, pending });
  pending = r.pending || null;
  chatMsg("assistant", r.reply, r.did);
  if (r.needs === "passphrase") $("#c-pass").focus();
  if (r.did) load(true);
}
async function loadChat() {
  const r = await api("/api/panel/chat");
  $("#c-log").innerHTML = ""; r.chat.forEach(m => { let did = null; try { did = JSON.parse(m.data || "{}").did; } catch (e) { } chatMsg(m.role, m.text, did); });
  if (!r.chat.length) chatMsg("assistant", "Hello — I can report on the three applications and work this panel for you. Try a suggestion above, or type “help”.");
}

function bind() {
  $("#bk-refresh").onclick = () => loadBulk().catch(e => toast(e.message));
  $("#bk-all").onclick = () => $$("[data-bk]:not(:disabled)").forEach(b => b.checked = true);
  $("#bk-start").onclick = async () => { try { const r = await api("/api/bulk/start", { datasets: $$("[data-bk]:checked").map(b => b.dataset.bk),
      agents: +$("#bk-agents").value || 4, passphrase: $("#bk-pass").value }); toast(r.summary); loadBulk(); } catch (e) { toast(e.message); } };
  $("#bk-stop").onclick = async () => { const r = await api("/api/bulk/stop", {}); toast(r.summary); loadBulk(); };
  const bkGo = async () => { const r = await api("/api/bulk/search?q=" + encodeURIComponent($("#bk-q").value));
    $("#bk-out").innerHTML = r.facts.length ? `<table class="t small"><tr><th>Subject</th><th>Predicate</th><th>Value</th><th>From</th></tr>` + r.facts.map(f =>
      `<tr><td>${f.link ? `<a href="${esc(f.link)}" target="_blank" rel="noopener">${esc(f.subject)}</a>` : esc(f.subject)}</td><td>${esc(f.predicate)}</td><td>${esc(f.object)}</td>
       <td class="small">${esc(f.dataset)} · ${esc(f.provenance)} · ${esc(f.status)}</td></tr>`).join("") + "</table>" : `<p class="muted small">Nothing starts with that.</p>`; };
  $("#bk-go").onclick = bkGo; $("#bk-q").onkeydown = e => { if (e.key === "Enter") bkGo(); };
  $("#ex-refresh").onclick = () => loadExemplars(); $("#ex-list").onclick = listTakes;
  $("#ex-gen-start").onclick = async () => { try { const r = await api("/api/gtools/runner", { action: "start", passphrase: $("#ex-pass").value }); toast(r.summary); loadExemplars(); } catch (e) { toast(e.message); } };
  $("#ex-gen-stop").onclick = async () => { const r = await api("/api/gtools/runner", { action: "stop" }); toast(r.summary); loadExemplars(); };
  $("#ex-verify").onclick = async () => { const r = await api("/api/exemplars/verify"); toast(r.checked + " checked, " + r.problems.length + " problem(s)" + (r.problems.length ? ": " + r.problems.map(p => p.id + " " + p.problem).join("; ") : "")); };
  $("#sk-refresh").onclick = () => loadSelf(); $("#sk-ask").onclick = askSelf; $("#sk-clear").onclick = () => { $("#sk-answer").innerHTML = ""; $("#sk-q").value = ""; };
  $("#sk-q").onkeydown = e => { if (e.key === "Enter") askSelf(); };
  $("#refresh").onclick = async () => { await api("/api/panel/check", {}); load(); };
  $("#alerts-all").onchange = renderAlerts;
  $("#alerts-clear").onclick = async () => { await api("/api/panel/alerts_clear", {}); load(true); };
  const H = async (action, sel, now) => { const body = { action, now }; if (sel) { body.apps = picked($("#h-apps")); body.harvesters = picked($("#h-harvesters"));
    if (!body.apps.length && !body.harvesters.length) return toast("Tick at least one application or harvester first.", true); }
    if (action === "stop" && !confirm(sel ? "Stop the selected harvesting?" : "Stop all harvesting in all three applications?")) return;
    const r = await api("/api/panel/harvest", body); toast(r.summary); load(true); };
  $("#h-start-all").onclick = () => H("start", false, false); $("#h-now").onclick = () => H("start", false, true);
  $("#h-stop-all").onclick = () => H("stop", false); $("#h-start-sel").onclick = () => H("start", true, true); $("#h-stop-sel").onclick = () => H("stop", true);
  $("#h-clear-sel").onclick = () => $$("#h-apps input, #h-harvesters input").forEach(i => { i.checked = false; });
  $("#t-save").onclick = async () => { const r = await api("/api/panel/rules", { kind: "target", passphrase: $("#t-pass").value, rules: {
      topics: $("#t-topics").value, apps: picked($("#t-apps")), harvesters: picked($("#t-harvesters")), sources: $("#t-sources").value,
      only: $("#t-only").checked, boost: +$("#t-boost").value } }); toast(r.summary); load(true); };
  $("#t-clear").onclick = async () => { if (!confirm("Clear the target (harvest everything evenly again)?")) return;
    const r = await api("/api/panel/rules_clear", { kind: "target", passphrase: $("#t-pass").value }); toast(r.summary); load(true); };
  $("#f-preview").onclick = async () => { const r = await api("/api/panel/preview", { rules: filterRules() });
    $("#f-out").innerHTML = `<div class="note"><b>Dry run:</b> of the latest ${r.checked} shared facts, ${r.kept} would be kept and ${r.dropped} left out
      ${Object.keys(r.dropped_by_domain).length ? "(" + Object.entries(r.dropped_by_domain).map(([d, n]) => esc(d) + " " + n).join(", ") + ")" : ""}. Rules: ${esc(r.rules)}.
      ${r.examples.length ? `<ul class="small">${r.examples.map(x => `<li>${esc(x.subject)} — ${esc(x.predicate)} — ${esc(x.object)}: <i>${esc(x.why)}</i></li>`).join("")}</ul>` : ""}
      <button class="btn quiet" style="padding:2px 8px;font-size:13px" onclick="this.parentNode.remove()">Clear</button></div>`; };
  $("#f-save").onclick = async () => { const r = await api("/api/panel/rules", { kind: "filter", passphrase: $("#f-pass").value, rules: filterRules() }); toast(r.summary); load(true); };
  $("#f-clear").onclick = async () => { if (!confirm("Clear the filter (let every fact in again)?")) return;
    const r = await api("/api/panel/rules_clear", { kind: "filter", passphrase: $("#f-pass").value }); toast(r.summary); load(true); };
  const search = async () => { const r = await api("/api/panel/search", { q: $("#s-q").value, domain: $("#s-domain").value });
    $("#s-out").innerHTML = r.facts.length ? `<table class="t"><tr><th>Subject</th><th>Predicate</th><th>Value</th><th>Domain</th><th>Status</th><th>Apps</th></tr>` +
      r.facts.map(f => `<tr><td>${esc(f.subject)}</td><td>${esc(f.predicate)}</td><td>${esc(String(f.object).slice(0, 160))}</td><td>${esc(f.domain)}</td>
        <td>${esc(f.status)}</td><td>${f.apps}</td></tr>`).join("") + "</table>" : `<p class="muted">Nothing found.</p>`; };
  $("#s-go").onclick = search; $("#s-q").onkeydown = e => { if (e.key === "Enter") search(); };
  $("#s-clear").onclick = () => { $("#s-q").value = ""; $("#s-out").innerHTML = ""; };
  $("#a-refresh").onclick = loadAudit;
  $("#a-clear").onclick = async () => { await api("/api/panel/audit_clear", {}); loadAudit(); };
  $("#a-all").onclick = async () => { await api("/api/panel/audit_clear", { show_all: true }); loadAudit(); };
  $("#d-clear").onclick = () => { $("#diag-all").innerHTML = ""; };
  $$("[data-diag]").forEach(b => b.onclick = () => diag(b.dataset.diag));
  $("#c-send").onclick = () => say(); $("#c-in").onkeydown = e => { if (e.key === "Enter") say(); };
  $("#c-clear").onclick = async () => { await api("/api/panel/chat_clear", {}); pending = null; loadChat(); };
  $("#c-sugg").innerHTML = SUGG.map(s => `<button>${esc(s)}</button>`).join("");
  $$("#c-sugg button").forEach(b => b.onclick = () => say(b.textContent));
}

// ---- live fact ticker: UFCS fact counts per area, polled every 2 s; numbers count up to the new value
const TK = { last: {}, shown: {}, ok: false };
const fmt = n => n == null ? "—" : Number(n).toLocaleString();
function tkCount(el, key, to) {
  const from = TK.shown[key] ?? to; TK.shown[key] = to;
  if (from === to || window.matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = fmt(to); return; }
  el.classList.add("up"); const t0 = performance.now(), d = 900;
  const step = t => { const k = Math.min(1, (t - t0) / d); el.textContent = fmt(Math.round(from + (to - from) * k)); if (k < 1) requestAnimationFrame(step); else setTimeout(() => el.classList.remove("up"), 600); };
  requestAnimationFrame(step);
}
function tkRender(T) {
  const cells = T.areas.map(a => ({ key: a.app, name: a.area, n: a.facts, live: a.running,
    sub: `+${fmt(a.last_minute)} last min · +${fmt(a.last_hour)} last hr · ${fmt(a.verified_or_corroborated)} verified/corroborated` +
         (a.bulk ? ` · bulk ${fmt(a.bulk)}` : "") + (a.own_store != null ? ` · own store ${fmt(a.own_store)}` : "") }));
  cells.push({ key: "total", name: "All areas (UFCS facts)", n: T.total, live: T.areas.some(a => a.running), total: true,
    sub: `+${fmt(T.last_minute)} last min · +${fmt(T.last_hour)} last hr` + (T.other.facts ? ` · other ${fmt(T.other.facts)}` : "") });
  const row = $("#tk-row");
  if (row.children.length !== cells.length) row.innerHTML = cells.map(c => `<div class="tk${c.total ? " total" : ""}" data-k="${c.key}"><div class="nm"><i class="tk-live"></i><span></span></div><div class="n">—</div><div class="sub"></div></div>`).join("");
  cells.forEach(c => { const el = row.querySelector(`[data-k="${c.key}"]`);
    el.querySelector(".nm span").textContent = c.name; el.querySelector(".tk-live").classList.toggle("on", !!c.live);
    el.querySelector(".tk-live").title = c.live ? "harvesting application running" : "not running";
    el.querySelector(".sub").textContent = c.sub; tkCount(el.querySelector(".n"), c.key, c.n); });
  const feed = T.latest.map(f => `${NAMES[f.origin_app] || f.origin_app}: ${f.subject} — ${f.predicate} — ${f.object} (${f.status})`).join("   •   ");
  const sp = $("#tk-feed span"); if (sp.dataset.v !== feed) { sp.dataset.v = feed; sp.textContent = feed || "No facts yet — start harvesting to see them arrive."; }
}
async function tick() {
  if (document.visibilityState !== "visible") return;
  try { tkRender(await (await fetch("/api/panel/ticker")).json()); TK.ok = true; } catch (e) { TK.ok = false; }
}

tabs(); bind(); load(); loadChat(); tick();
setInterval(tick, 2000);
setInterval(() => { if (document.visibilityState === "visible" && $("#bulk").classList.contains("active")) loadBulk().catch(() => {}); }, 5000);
setInterval(() => { if (document.visibilityState === "visible") load(true); }, 10000);
