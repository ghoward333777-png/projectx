// QueryBook Control Panel page.
"use strict";
let S = null, pending = null;
const NAMES = { language: "Language Builder", stem: "Math, Science & Engineering", facts: "History & News" };
const level = l => l === "error" ? "bad" : l === "warn" ? "warn" : "good";

function tabs() {
  const show = id => { $$("nav.tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === id)); $$("section.panel").forEach(s => s.classList.toggle("active", s.id === id));
    try { localStorage.setItem("qb-control-tab", id); } catch (e) { } if (id === "audit") loadAudit(); if (id === "self") loadSelf().catch(e => toast(e.message)); if (id === "exemplars") loadExemplars().catch(e => toast(e.message)); if (id === "bulk") { loadBulk().catch(e => toast(e.message)); loadGather().catch(e => toast(e.message)); } if (id === "apis") loadApis().catch(e => toast(e.message)); };
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
// ---- the fact gatherer
async function loadGather() {
  const g = await api("/api/gather"), sel = $("#ga-provider"), keep = sel.value;
  sel.innerHTML = g.providers.map(p => `<option value="${p.id}" ${p.key_set ? "" : "disabled"}>${esc(p.id)} (${esc(p.model)})${p.key_set ? "" : " — no key"}</option>`).join("");
  sel.value = keep || (g.providers.find(p => p.key_set) || {}).id || "";
  $("#ga-providers").innerHTML = g.providers.map(p => `<span class="pill">${esc(p.id)}: ${p.key_set ? `key set · ${p.used_today}/${p.budget} today` : "no key"}</span>`).join(" ") +
    (g.approved ? "" : ` <span class="badge bad">source not approved in the registry</span>`);
  const ss = $("#ga-series"), keepS = ss.value;
  ss.innerHTML = `<option value="">every series, newest first</option>` + Object.entries(g.series).map(([k, n]) => `<option value="${k}">${esc(n)} (${g.open_slots[k]} open)</option>`).join("");
  ss.value = keepS;
  $("#ga-open").textContent = `${fmt(Object.values(g.open_slots).reduce((a, b) => a + b, 0))} editions still open`;
  $("#ga-recent").innerHTML = g.recent.length ? `<table class="t small"><tr><th>When</th><th>Question</th><th>Kept</th><th>Facts (✓ confirmed on the page)</th></tr>` +
    g.recent.map(r => `<tr><td>${esc((r.at || "").slice(0, 16).replace("T", " "))}<div class="muted">${esc(r.provider)}</div></td><td>${esc(r.question)}</td>
      <td>${r.kept} of ${r.facts.length}<div class="muted">${r.pages.filter(p => p.read).length}/${r.pages.length} pages read</div></td>
      <td>${r.facts.map(f => `${f.kept ? "✓" : "✗"} ${esc(f.subject)} — ${esc(f.predicate)}: <b>${esc(f.object)}</b>${f.kept ? "" : ` <span class="muted">(${esc(f.why)})</span>`}`).join("<br>")}</td></tr>`).join("") + "</table>"
    : `<p class="muted small">No gathering runs yet.</p>`;
}
async function gatherStart(body) {
  try { const r = await api("/api/gather/start", Object.assign({ provider: $("#ga-provider").value, passphrase: $("#bk-pass").value }, body)); toast(r.summary); loadGather(); }
  catch (e) { toast(e.message); }
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
  $("#api-refresh").onclick = () => loadApis().catch(e => toast(e.message));
  $("#cn-cat").onchange = () => CONNS && renderConns();
  $("#cn-test-all").onclick = async () => { $("#cn-test-all").disabled = true; toast("Testing every connection…");
    try { (await api("/api/connections/test", { all: true })).results.forEach(r => CN_TEST[r.id] = r); renderConns(); } catch (e) { toast(e.message); }
    $("#cn-test-all").disabled = false; };
  $("#api-q").oninput = () => APIS && renderRef(); $("#api-explained").onchange = () => APIS && renderRef();
  $("#bk-refresh").onclick = () => { loadBulk().catch(e => toast(e.message)); loadGather().catch(e => toast(e.message)); };
  $("#ga-ask").onclick = () => gatherStart({ mode: "ask", area: $("#ga-area").value, question: $("#ga-q").value });
  $("#ga-slots").onclick = () => gatherStart({ mode: "slots", series: $("#ga-series").value, limit: +$("#ga-limit").value || 5 });
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
  tkActive(T.active || []);
  const feed = T.latest.map(f => `${NAMES[f.origin_app] || f.origin_app}: ${f.subject} — ${f.predicate} — ${f.object} (${f.status})`).join("   •   ");
  const sp = $("#tk-feed span"); if (sp.dataset.v !== feed) { sp.dataset.v = feed; sp.textContent = feed || "No facts yet — start harvesting to see them arrive."; }
}
// ---- harvests in action: one mini bar each, on its own scale (bytes of the publisher's file, rows, tasks or facts)
function unitFmt(n, unit) {
  if (n == null) return "—";
  if (unit === "bytes") return n >= 1e9 ? (n / 1e9).toFixed(2) + " GB" : n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.round(n / 1e3) + " KB";
  return fmt(n) + " " + unit;
}
const dur = s => s == null ? "" : s < 90 ? Math.round(s) + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h";
function tkActive(list) {
  const el = $("#tk-active");
  if (!list.length) { el.innerHTML = ""; return; }
  el.innerHTML = list.map(h => {
    const f = h.fraction == null ? null : Math.max(0, Math.min(1, h.fraction)), pc = f == null ? "…" : (f * 100).toFixed(f < 0.1 ? 1 : 0) + "%";
    const scaleTotal = h.kind === "bulk" && h.parts > 1 ? `${h.parts} files` : unitFmt(h.total, h.unit);
    const now = h.kind === "bulk"
      ? `file ${h.part_no} of ${h.parts}: ${esc(h.part || "")} — ${unitFmt(h.done, h.unit)} of ${unitFmt(h.total, h.unit)}` +
        (h.rate ? ` · ${unitFmt(h.rate, h.unit)}/s` : "") + (h.eta_s ? ` · ${dur(h.eta_s)} left in this file` : "") +
        ` · +${fmt(h.facts_per_min)} facts/min`
      : `${unitFmt(h.done, h.unit)} of ${unitFmt(h.total, h.unit)}` + (h.detail ? ` · now: ${esc(h.detail)}` : "");
    return `<div class="hv" title="${esc(h.title)}"><div class="top"><span class="nm">${esc(h.title)}</span><span class="pct">${pc}</span></div>
      <div class="bar2 ${h.kind}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${f == null ? 0 : Math.round(f * 100)}"
        aria-label="${esc(h.title)}"><i style="width:${f == null ? 0 : (f * 100).toFixed(2)}%"></i></div>
      <div class="scale"><span>0</span><span>25%</span><span>50%</span><span>75%</span><span>${esc(scaleTotal)}</span></div>
      <div class="sub">${now}</div></div>`;
  }).join("");
}
async function tick() {
  if (document.visibilityState !== "visible") return;
  try { tkRender(await (await fetch("/api/panel/ticker")).json()); TK.ok = true; } catch (e) { TK.ok = false; }
}

// ---- the master API page: recipes, every endpoint, try it, copy as curl / Python / JavaScript
let APIS = null;
const KIND_BADGE = { read: ["good", "read"], changes: ["warn", "changes"], admin: ["bad", "admin"] };
let CONNS = null, CN_TEST = {};
async function loadConns() {
  CONNS = await api("/api/connections");
  const sel = $("#cn-cat"), keep = sel.value;
  sel.innerHTML = `<option value="">All kinds</option>` + CONNS.categories.map(c => `<option>${esc(c)}</option>`).join("");
  sel.value = keep; renderConns();
}
function renderConns() {
  const cat = $("#cn-cat").value, rows = CONNS.connections.filter(c => !cat || c.category === cat);
  const missing = CONNS.connections.filter(c => c.key_status === "not set").length;
  $("#cn-summary").textContent = `· ${CONNS.connections.length} services · ${missing} key(s) not set`;
  const keyBadge = c => c.key_status === "set" ? `<span class="badge good">key set</span>` : c.key_status === "not set" ? `<span class="badge warn">key not set</span>`
    : c.key_status === "no key needed" ? `<span class="small muted">no key</span>` : `<span class="small muted">${esc(c.key_where)}</span>`;
  const testCell = c => { const t = CN_TEST[c.id]; return t ? `<span class="badge ${t.reachable ? "good" : "bad"}">${t.reachable ? "reachable" : "unreachable"}</span>
    <span class="small muted">${t.status || ""} · ${t.ms} ms${t.reachable ? "" : " · " + esc(t.detail)}</span>` : ""; };
  $("#cn-table").innerHTML = `<table class="t small"><tr><th>Service</th><th>Used by · for</th><th>Key</th><th>Approved</th><th>Last used</th><th></th></tr>` +
    rows.map(c => `<tr><td><b>${esc(c.name)}</b><div class="muted">${esc(c.category)} · <a href="${esc(c.docs)}" target="_blank" rel="noopener">docs</a></div></td>
      <td>${esc(c.used_by)}<div class="muted">${esc(c.purpose)}</div></td><td>${keyBadge(c)}${c.key_status === "not set" ? `<div class="muted">${esc(c.key_where)}</div>` : ""}</td>
      <td>${c.approved == null ? "—" : c.approved ? `<span class="badge good">approved</span>` : `<span class="badge bad">not approved</span>`}</td>
      <td>${c.last_used ? esc(c.last_used.slice(0, 16).replace("T", " ")) + `<div class="muted">${fmt(c.uses)} harvests</div>` : "—"}</td>
      <td><button class="btn quiet" data-cn="${esc(c.id)}">Test</button> ${testCell(c)}</td></tr>`).join("") + "</table>";
  $$("[data-cn]").forEach(b => b.onclick = async () => { b.disabled = true;
    try { const r = await api("/api/connections/test", { id: b.dataset.cn }); CN_TEST[b.dataset.cn] = r.results[0]; } catch (e) { toast(e.message); }
    renderConns(); });
}
async function loadApis() {
  loadConns().catch(e => toast(e.message));
  APIS = await api("/api/panel/apis");
  $("#api-progs").innerHTML = APIS.programs.map(p => `<span class="pill"><span class="dot ${p.running ? "on" : "off"}"></span>${esc(p.name)} ·
    <span class="mono">${esc(p.url)}</span>${p.running ? ` · <a href="${esc(p.url)}/api/openapi.json" target="_blank" rel="noopener">OpenAPI</a>` : " · not running"}</span>`).join(" ");
  $("#api-recipes").innerHTML = APIS.recipes.map((r, i) => `<div class="recipe" data-recipe="${i}" tabindex="0"><b>${esc(r.title)}</b>
    <span class="meth ${r.method}">${r.method}</span> <span class="mono small">${esc(r.path)}</span>
    <div class="small muted">${esc(progName(r.program))}</div></div>`).join("");
  $$("[data-recipe]").forEach(el => { const go = () => { const r = APIS.recipes[+el.dataset.recipe]; openTry(r.program, r.method, r.path, r.params); };
    el.onclick = go; el.onkeydown = e => { if (e.key === "Enter") go(); }; });
  renderRef();
}
const progName = k => (APIS.programs.find(p => p.program === k) || {}).name || k;
const progUrl = k => (APIS.programs.find(p => p.program === k) || {}).url || "";
function routeDoc(program, method, path) {
  const p = APIS.programs.find(x => x.program === program);
  return (p && p.routes.find(r => r.path === path && r.method === method)) || { method, path, params: [], doc: null, text: "" };
}
function renderRef() {
  const q = ($("#api-q").value || "").toLowerCase(), only = $("#api-explained").checked;
  $("#api-ref").innerHTML = APIS.programs.map(p => {
    const rows = p.routes.filter(r => (!only || r.doc) && (!q || (r.path + " " + (r.text || "") + " " + ((r.doc || {}).title || "") + " " + ((r.doc || {}).group || "")).toLowerCase().includes(q)));
    const groups = {};
    rows.forEach(r => (groups[(r.doc || {}).group || "More: " + r.path.split("/")[2]] ||= []).push(r));
    const names = Object.keys(groups).sort((a, b) => (a.startsWith("More") - b.startsWith("More")) || a.localeCompare(b));
    return `<details class="prog" ${q || p.program === "control" ? "open" : ""}><summary>${esc(p.name)} <span class="small muted">· ${rows.length} endpoint(s) ·
      ${esc(p.url)}${p.running ? "" : " · not running — listed from the guide"}</span></summary>` +
      names.map(g => `<h4 style="margin:10px 0 2px">${esc(g)}</h4>` + groups[g].map(r => {
        const k = KIND_BADGE[(r.doc || {}).kind || (r.method === "GET" ? "read" : "changes")];
        return `<div class="api-row"><span class="meth ${r.method}">${r.method}</span><div><span class="path">${esc(r.path)}</span>
          ${r.doc ? ` — <b>${esc(r.doc.title)}</b>` : ""}<div class="small muted">${esc(r.text || "")}${r.params.length ? ` <span class="mono">(${r.params.map(esc).join(", ")})</span>` : ""}</div></div>
          <div><span class="badge ${k[0]}">${k[1]}</span> <button class="btn quiet" data-try="${esc(p.program)}|${r.method}|${esc(r.path)}">Try it</button></div></div>`;
      }).join("")).join("") + "</details>";
  }).join("");
  $$("[data-try]").forEach(b => b.onclick = () => { const [prog, m, path] = b.dataset.try.split("|"); const r = routeDoc(prog, m, path);
    openTry(prog, m, path, (r.doc && r.doc.example) || Object.fromEntries(r.params.map(n => [n, ""]))); });
}
function snippets(program, method, path, params) {
  const base = progUrl(program), shown = JSON.parse(JSON.stringify(params || {}));
  if ("passphrase" in shown) shown.passphrase = "<admin passphrase>";
  const qs = new URLSearchParams(Object.entries(shown).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)])).toString();
  const url = base + path + (method === "GET" && qs ? "?" + qs : ""), body = JSON.stringify(shown);
  return method === "GET" ? {
    curl: `curl "${url}"`,
    Python: `import json, urllib.request\n\nprint(json.load(urllib.request.urlopen("${url}")))`,
    JavaScript: `const r = await fetch("${url}");\nconsole.log(await r.json());` } : {
    curl: `curl -X POST "${url}" \\\n  -H "Content-Type: application/json" \\\n  -d '${body.replace(/'/g, "'\\''")}'`,
    Python: `import json, urllib.request\n\nreq = urllib.request.Request("${url}", data=json.dumps(${JSON.stringify(shown, null, 1).replace(/\btrue\b/g, "True").replace(/\bfalse\b/g, "False").replace(/\bnull\b/g, "None")}).encode(),\n                             headers={"Content-Type": "application/json"})\nprint(json.load(urllib.request.urlopen(req)))`,
    JavaScript: `const r = await fetch("${url}", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify(${body}),\n});\nconsole.log(await r.json());` };
}
function openTry(program, method, path, params) {
  const r = routeDoc(program, method, path), kind = (r.doc || {}).kind || (method === "GET" ? "read" : "changes");
  const el = $("#api-try");
  el.innerHTML = `<div class="try"><div class="sechead"><h3 style="margin:0"><span class="meth ${method}">${method}</span> <span class="mono">${esc(path)}</span></h3>
      <span class="small muted">${esc(progName(program))}</span><button class="btn quiet" id="try-close">Close</button></div>
    ${r.doc ? `<p class="small"><b>${esc(r.doc.title)}.</b> ${esc(r.doc.text)}</p>` : r.text ? `<p class="small">${esc(r.text)}</p>` : ""}
    <label class="small">${method === "GET" ? "Query parameters" : "Body"} (JSON)</label><textarea id="try-params" spellcheck="false">${esc(JSON.stringify(params || {}, null, 2))}</textarea>
    <div class="row"><button class="btn" id="try-run">▶ Run</button><span class="badge ${KIND_BADGE[kind][0]}">${KIND_BADGE[kind][1]}</span>
      <span class="small muted" id="try-meta"></span></div>
    <pre id="try-out" class="small muted">Press Run to see the answer.</pre>
    <div class="snip"><div class="tabs2 row">${["curl", "Python", "JavaScript"].map((t, i) => `<button data-snip="${t}" aria-selected="${i === 0}">${t}</button>`).join("")}
      <button class="btn quiet" id="try-copy">Copy</button></div><pre id="try-snip"></pre></div></div>`;
  let lang = "curl";
  const params_ = () => { try { return JSON.parse($("#try-params").value || "{}"); } catch (e) { return null; } };
  const showSnip = () => { const p = params_(); $("#try-snip").textContent = p ? snippets(program, method, path, p)[lang] : "The parameters are not valid JSON."; };
  $$("[data-snip]").forEach(b => b.onclick = () => { lang = b.dataset.snip; $$("[data-snip]").forEach(x => x.setAttribute("aria-selected", x === b)); showSnip(); });
  $("#try-params").oninput = showSnip; showSnip();
  $("#try-copy").onclick = async () => { try { await navigator.clipboard.writeText($("#try-snip").textContent); toast("Copied."); } catch (e) { toast("Select the text and copy it."); } };
  $("#try-close").onclick = () => { el.innerHTML = ""; };
  $("#try-run").onclick = async () => {
    const p = params_();
    if (!p) return toast("The parameters are not valid JSON.", true);
    if (kind !== "read" && !confirm(`This ${kind === "admin" ? "admin " : ""}call changes harvesting (${method} ${path} on ${progName(program)}). Run it?`)) return;
    $("#try-out").textContent = "Running…";
    try { const r = await api("/api/panel/try", { program, method, path, params: p });
      $("#try-meta").textContent = `answered in ${r.ms} ms`; $("#try-out").textContent = JSON.stringify(r.result, null, 2).slice(0, 200000);
    } catch (e) { $("#try-meta").textContent = ""; $("#try-out").textContent = "Error: " + e.message; }
  };
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

tabs(); bind(); load(); loadChat(); tick();
setInterval(tick, 2000);
setInterval(() => { if (document.visibilityState === "visible" && $("#bulk").classList.contains("active")) { loadBulk().catch(() => {}); loadGather().catch(() => {}); } }, 5000);
setInterval(() => { if (document.visibilityState === "visible") load(true); }, 10000);
