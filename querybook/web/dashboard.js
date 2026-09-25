/* QueryBook operator dashboard: live statistics, trends, charts, progress and meters.
   Plain SVG/HTML, no libraries. Refreshes every 5 s while visible. */
"use strict";

const DASH = { timer: null, last: 0, data: null, tick: null };
const DAY = 86400;

function stopDashboard() {
  clearTimeout(DASH.timer); clearInterval(DASH.tick);
  DASH.timer = null; DASH.tick = null;
  document.removeEventListener("visibilitychange", dashVisibility);
}
function dashVisibility() { if (!document.hidden && DASH.timer === null && location.hash.startsWith("#/dashboard")) pollDashboard(); }

async function renderDashboard() {
  stopDashboard();
  app().innerHTML = topbar("QueryBook") + `<main class="page dash">
    <div class="dash-head"><h2>Dashboard</h2><span class="live" id="live"><i></i><span>connecting…</span></span></div>
    <div id="dash"><div class="muted">Loading…</div></div></main><div class="dtip" id="dtip" role="tooltip"></div>`;
  wireTopbar();
  document.addEventListener("visibilitychange", dashVisibility);
  DASH.tick = setInterval(updateLive, 1000);
  await pollDashboard(true);
}

async function pollDashboard(first) {
  clearTimeout(DASH.timer);
  DASH.timer = null;
  if (!location.hash.startsWith("#/dashboard")) return stopDashboard();
  try {
    const d = await api("/api/admin/dashboard");
    DASH.data = d; DASH.last = Date.now();
    drawDashboard(d, first);
  } catch (e) {
    if (first) { $("#dash").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    const l = $("#live span"); if (l) l.textContent = "reconnecting…";
  }
  if (!document.hidden) DASH.timer = setTimeout(() => pollDashboard(false), 5000);
}

function updateLive() {
  const l = $("#live"); if (!l || !DASH.last) return;
  const s = Math.round((Date.now() - DASH.last) / 1000);
  l.classList.toggle("stale", s > 15);
  $("span", l).textContent = document.hidden ? "paused" : `live · updated ${s < 2 ? "just now" : s + " s ago"}`;
}

// ------------------------------------------------------------------ helpers

const nf = (n) => (n == null ? "—" : Number(n).toLocaleString());
function compact(n) {
  n = Number(n) || 0;
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (Math.abs(n) >= 1e4) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toLocaleString();
}
function bytes(b) {
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; b = Number(b) || 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return (i ? b.toFixed(1) : b) + " " + u[i];
}
function ago(ts) {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + " min ago";
  if (s < 129600) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " days ago";
}
const dayLabel = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

/** Fill a per-day series over the 30-day window (missing days are zero). */
function daily(since, rows) {
  const m = new Map(rows.map((r) => [r.day, r.n]));
  const out = [];
  for (let i = 0; i < 30; i++) { const t = since + i * DAY; out.push({ t, n: m.get(t) || 0 }); }
  return out;
}
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const k of [1, 2, 2.5, 5, 10]) if (k * p >= v) return k * p;
  return 10 * p;
}

function tip(html, x, y) {
  const t = $("#dtip"); if (!t) return;
  t.innerHTML = html; t.style.display = "block";
  const w = t.offsetWidth, h = t.offsetHeight;
  t.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x - w / 2)) + "px";
  t.style.top = Math.max(8, y - h - 12) + "px";
}
function untip() { const t = $("#dtip"); if (t) t.style.display = "none"; }

// ------------------------------------------------------------------ charts

/** Sparkline for a stat tile (no axes; the tile's number is the headline). */
function spark(values) {
  const w = 120, h = 28, max = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * w},${h - 2 - (v / max) * (h - 4)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}"/></svg>`;
}

/** Single-series line/area over time, with a crosshair tooltip. */
function lineChart(el, pts, fmt, label) {
  const W = Math.max(280, el.clientWidth || 560), H = 190, L = 48, R = 12, T = 12, B = 26;
  const vals = pts.map((p) => p.v);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y0 = lo > 0 && (hi - lo) / hi < 0.5 ? Math.floor(lo * 0.98) : 0; // zoom when the series is nearly flat
  const y1 = y0 + niceMax(Math.max(1, hi - y0));
  const x = (i) => L + (i / Math.max(1, pts.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const grid = [0, 0.5, 1].map((f) => { const v = y0 + f * (y1 - y0); return `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${compact(v)}</text>`; }).join("");
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const area = `${line}L${x(pts.length - 1)},${y(y0)}L${x(0)},${y(y0)}Z`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(label)}">
    ${grid}<path class="area" d="${area}"/><path class="line" d="${line}"/>
    <text class="tick" x="${L}" y="${H - 6}">${dayLabel(pts[0].t)}</text><text class="tick" x="${W - R}" y="${H - 6}" text-anchor="end">${dayLabel(pts[pts.length - 1].t)}</text>
    <line class="xh" y1="${T}" y2="${H - B}" style="display:none"/><circle class="dot" r="4.5" style="display:none"/>
    <rect class="hit" x="${L}" y="0" width="${W - L - R}" height="${H}"/></svg>`;
  const svg = $("svg", el), xh = $(".xh", svg), dot = $(".dot", svg);
  $(".hit", svg).onmousemove = (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(pts.length - 1, Math.round(((px - L) / (W - L - R)) * (pts.length - 1))));
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.style.display = "";
    dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(pts[i].v)); dot.style.display = "";
    tip(`<b>${fmt(pts[i].v)}</b><span>${dayLabel(pts[i].t)}</span>`, r.left + (x(i) / W) * r.width, r.top + (y(pts[i].v) / H) * r.height);
  };
  $(".hit", svg).onmouseleave = () => { xh.style.display = "none"; dot.style.display = "none"; untip(); };
}

/** Single-series columns per day, per-bar hover. */
function columnChart(el, pts, unit, label) {
  const W = Math.max(280, el.clientWidth || 560), H = 190, L = 40, R = 8, T = 12, B = 26;
  const max = niceMax(Math.max(1, ...pts.map((p) => p.n)));
  const bw = (W - L - R) / pts.length, gap = Math.min(2, bw * 0.2);
  const y = (v) => T + (1 - v / max) * (H - T - B);
  const bars = pts.map((p, i) => {
    const h = y(0) - y(p.n); if (p.n <= 0) return "";
    const x0 = L + i * bw + gap / 2, w = Math.max(1, bw - gap), r = Math.min(4, w / 2, h);
    return `<path class="col" data-i="${i}" d="M${x0},${y(0)}V${y(p.n) + r}Q${x0},${y(p.n)} ${x0 + r},${y(p.n)}H${x0 + w - r}Q${x0 + w},${y(p.n)} ${x0 + w},${y(p.n) + r}V${y(0)}Z"/>`;
  }).join("");
  const hits = pts.map((p, i) => `<rect class="hit" data-i="${i}" x="${L + i * bw}" y="${T}" width="${bw}" height="${H - T - B}"/>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(label)}">
    ${[0, 0.5, 1].map((f) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(f * max)}" y2="${y(f * max)}"/><text class="tick" x="${L - 6}" y="${y(f * max) + 4}" text-anchor="end">${compact(f * max)}</text>`).join("")}
    ${bars}<text class="tick" x="${L}" y="${H - 6}">${dayLabel(pts[0].t)}</text><text class="tick" x="${W - R}" y="${H - 6}" text-anchor="end">${dayLabel(pts[pts.length - 1].t)}</text>${hits}</svg>`;
  const svg = $("svg", el);
  $$(".hit", svg).forEach((h) => {
    h.onmousemove = (e) => {
      const p = pts[+h.dataset.i];
      $$(".col", svg).forEach((c) => c.classList.toggle("dim", c.dataset.i !== h.dataset.i));
      tip(`<b>${nf(p.n)} ${unit}</b><span>${dayLabel(p.t)}</span>`, e.clientX, e.clientY);
    };
    h.onmouseleave = () => { $$(".col", svg).forEach((c) => c.classList.remove("dim")); untip(); };
  });
}

/** Horizontal bars (single series), value labels at the bar end. */
function hbars(rows, fmt) {
  const max = Math.max(1, ...rows.map((r) => r.v));
  return `<div class="hbars">${rows.map((r) => `<div class="hb" data-tip="${esc(r.label)}: ${esc(fmt(r.v))}">
      <span class="hb-l" title="${esc(r.label)}">${esc(r.label)}</span>
      <span class="hb-t"><i style="width:${Math.max(0.5, (r.v / max) * 100)}%"></i></span><span class="hb-v">${esc(fmt(r.v))}</span></div>`).join("")}</div>`;
}

/** Radial meter 0..1 with the value in the middle. */
function meter(frac, big, sub, cls = "") {
  const f = Math.max(0, Math.min(1, frac || 0)), r = 42, c = Math.PI * r; // half circle
  return `<div class="gauge ${cls}"><svg viewBox="0 0 100 60" aria-hidden="true">
      <path class="m-track" d="M8,54 A42,42 0 0 1 92,54"/>
      <path class="m-val" d="M8,54 A42,42 0 0 1 92,54" stroke-dasharray="${(f * c).toFixed(1)} ${c.toFixed(1)}"/></svg>
    <b>${esc(big)}</b><span>${esc(sub)}</span></div>`;
}

/** Status chip: never color alone (icon + label). */
function status(kind, label) {
  const icon = { good: "✓", warning: "!", critical: "✕", info: "•" }[kind] || "•";
  return `<span class="st st-${kind}"><i aria-hidden="true">${icon}</i>${esc(label)}</span>`;
}

function dataTable(head, rows) {
  return `<details class="dt"><summary class="small">Show data table</summary><div class="tbl-wrap"><table class="tbl"><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table></div></details>`;
}

// ------------------------------------------------------------------ page

function drawDashboard(d, first) {
  const s = d.store, la = d.lattice, ac = d.activity, tr = d.trends;
  const added = daily(tr.since, tr.facts_added);
  let run = tr.facts_before;
  const cumulative = added.map((p) => ({ t: p.t, v: (run += p.n) }));
  const questions = daily(tr.since, tr.questions);
  const added7 = added.slice(-7).reduce((a, p) => a + p.n, 0);
  const cells = la.cells_filled + la.cells_absent + la.cells_open;
  const decided = la.confirmed + la.refuted;
  const precision = decided ? la.confirmed / decided : null;
  const lastBackup = Math.max(d.backups.last_backup || 0, d.backups.last_upload || 0);
  const backupAge = lastBackup ? Date.now() / 1000 - lastBackup : Infinity;
  const backupState = !lastBackup ? ["critical", "No backup yet"] : backupAge < 36 * 3600 ? ["good", "Backed up " + ago(lastBackup)] : ["warning", "Last backup " + ago(lastBackup)];
  const answeredShare = ac.questions_total ? 1 - ac.unanswered_total / ac.questions_total : null;
  const openDetails = first ? [] : $$("#dash details[open]").map((x) => x.dataset.k);

  $("#dash").innerHTML = `
  <section class="tiles">
    <div class="tile"><span>Facts in store</span><b>${compact(s.facts)}</b><em>+${nf(added7)} in 7 days</em>${spark(cumulative.map((p) => p.v))}</div>
    <div class="tile"><span>Books</span><b>${nf(d.library.works)}</b><em>${compact(s.book_facts)} book facts</em></div>
    <div class="tile"><span>World knowledge</span><b>${compact(s.world_facts)}</b><em>${d.feeds.length} feed${d.feeds.length === 1 ? "" : "s"}</em></div>
    <div class="tile"><span>Questions · 7 days</span><b>${nf(ac.questions_7d)}</b><em>${nf(ac.questions_total)} all time</em>${spark(questions.map((p) => p.n))}</div>
    <div class="tile"><span>Accounts</span><b>${nf(ac.users)}</b><em>readers, authors, operators</em></div>
    <div class="tile"><span>Disk used</span><b>${bytes(s.disk_bytes)}</b><em>store, index, ledger</em></div>
  </section>

  <div class="dgrid">
    <section class="panel"><h3>Facts in the store <span class="muted small">· last 30 days</span></h3><div class="chart" id="c-facts"></div>
      ${dataTable(["Day", "Facts added", "Total"], cumulative.map((p, i) => [dayLabel(p.t), nf(added[i].n), nf(p.v)])).replace("<details", '<details data-k="facts"')}</section>
    <section class="panel"><h3>Reader questions per day <span class="muted small">· last 30 days</span></h3><div class="chart" id="c-q"></div>
      ${dataTable(["Day", "Questions"], questions.map((p) => [dayLabel(p.t), nf(p.n)])).replace("<details", '<details data-k="q"')}</section>
  </div>

  <div class="dgrid">
    <section class="panel"><h3>Facts per book <span class="muted small">· top ${d.library.top.length}</span></h3>
      ${d.library.top.length ? hbars(d.library.top.map((w) => ({ label: w.title, v: w.facts })), nf) : `<p class="muted">No books yet.</p>`}</section>
    <section class="panel"><h3>Knowledge lattice</h3>
      ${cells ? `<div class="prog-l"><span>Cells harvested</span><b>${((100 * (la.cells_filled + la.cells_absent)) / cells).toFixed(1)}%</b></div>
      <div class="stack" role="img" aria-label="filled ${la.cells_filled}, absent ${la.cells_absent}, open ${la.cells_open}">
        <i class="s1" style="width:${(100 * la.cells_filled) / cells}%"></i><i class="s2" style="width:${(100 * la.cells_absent) / cells}%"></i></div>
      <div class="legend"><span><i class="s1"></i>filled ${nf(la.cells_filled)}</span><span><i class="s2"></i>absent in Wikidata ${nf(la.cells_absent)}</span><span><i class="s0"></i>open ${nf(la.cells_open)}</span></div>` : `<p class="muted small">No census yet — run <code>qb lattice census</code>.</p>`}
      <div class="gauges">
        ${meter(precision, precision == null ? "—" : (precision * 100).toFixed(1) + "%", "prediction precision")}
        ${meter(la.classes_total ? Math.min(1, la.classes_censused / la.classes_total) : 0, la.classes_total ? `${nf(la.classes_censused)} / ${nf(la.classes_total)}` : "—", "classes censused")}
      </div>
      <p class="small muted" style="margin:6px 0 0">${nf(la.members)} members · ${nf(la.predictions)} predictions · ${nf(la.confirmed)} confirmed · ${nf(la.refuted)} refuted${la.findings ? ` · ${la.findings} finding${la.findings === 1 ? "" : "s"} for review` : ""}</p>
    </section>
  </div>

  <div class="dgrid">
    <section class="panel"><h3>Rule reliability</h3>
      ${la.rules.length ? `<div class="rules">${la.rules.map((r) => `<div class="rule"><span class="r-n" title="${esc(r.rule)}">${esc(r.rule)}</span>
        <span class="r-m"><i style="width:${(r.reliability * 100).toFixed(1)}%"></i></span><span class="r-v">${(r.reliability * 100).toFixed(0)}%</span>
        <span class="r-c muted small">${r.confirmed + r.refuted ? `${nf(r.confirmed)} ✓ · ${nf(r.refuted)} ✕` : "prior only — no outcomes yet"}</span></div>`).join("")}</div>` : `<p class="muted small">Rules are measured after <code>qb lattice expect</code>.</p>`}</section>
    <section class="panel"><h3>Health</h3>
      <div class="health">
        <div>${status(backupState[0], backupState[1])}<span class="small muted">${d.backups.drive_authorised ? "Google Drive connected" : "Google Drive not connected"}</span></div>
        <div>${status("good", "Ledger " + nf(d.ledger.nodes) + " nodes")}<span class="small muted mono">${esc((d.ledger.head || "").slice(0, 16))}…</span> <button class="btn small" id="vl">Verify now</button></div>
        <div>${status(s.indexed === s.facts ? "good" : "warning", s.indexed === s.facts ? "Index matches store" : `Index ${nf(s.indexed)} of ${nf(s.facts)}`)}</div>
        <div>${status(answeredShare == null || answeredShare >= 0.8 ? "good" : "warning", answeredShare == null ? "No questions yet" : `${(answeredShare * 100).toFixed(0)}% of questions answered`)}</div>
      </div>
      <p class="small muted" style="margin:10px 0 0">${esc(s.regime)}</p></section>
  </div>

  <div class="dgrid">
    <section class="panel"><h3>Jobs</h3>${d.jobs.length ? d.jobs.map((j) => {
      const m = /(\d[\d,]*)\s*\/\s*(\d[\d,]*)/.exec(j.detail || "");
      const frac = j.status === "running" ? (m ? +m[1].replace(/,/g, "") / Math.max(1, +m[2].replace(/,/g, "")) : null) : 1;
      const kind = j.status === "running" ? "info" : j.status === "failed" ? "critical" : "good";
      return `<div class="job"><div class="job-h">${status(kind, j.status)}<b>${esc(j.label)}</b><span class="muted small">${ago(j.started)}</span></div>
        <div class="pbar ${frac == null ? "indet" : ""}"><i style="width:${frac == null ? 30 : (frac * 100).toFixed(1)}%"></i></div>
        <div class="muted small">${esc(j.detail || "")}</div></div>`;
    }).join("") : `<p class="muted small">No ingestion jobs yet. Books added from Admin show live progress here.</p>`}</section>
    <section class="panel"><h3>Recent questions</h3>${ac.recent.length ? `<div class="tbl-wrap"><table class="tbl">${ac.recent.map((q) => `<tr><td>${q.answered ? status("good", "answered") : status("warning", "unanswered")}</td><td>${esc(q.question)}<div class="muted small">${esc(q.work)} · ${ago(q.ts)}</div></td></tr>`).join("")}</table></div>` : `<p class="muted small">No questions yet.</p>`}</section>
  </div>

  <section class="panel"><h3>World-knowledge feeds</h3>${d.feeds.length ? `<div class="tbl-wrap"><table class="tbl"><tr><th>Feed</th><th>Imported</th><th>Refused</th><th>Updated</th></tr>
    ${d.feeds.map((f) => `<tr><td class="mono">${esc(f.feed)}</td><td>${nf(f.imported)}</td><td>${nf(f.refused)}</td><td>${ago(f.updated)}</td></tr>`).join("")}</table></div>` : `<p class="muted small">No feeds imported yet.</p>`}</section>`;

  lineChart($("#c-facts"), cumulative, nf, "Facts in the store, last 30 days");
  columnChart($("#c-q"), questions, "questions", "Reader questions per day, last 30 days");
  openDetails.forEach((k) => { const x = $(`#dash details[data-k="${k}"]`); if (x) x.open = true; });
  $$("#dash .hb").forEach((b) => { b.onmousemove = (e) => tip(esc(b.dataset.tip), e.clientX, e.clientY); b.onmouseleave = untip; });
  $("#vl").onclick = async (e) => {
    e.target.disabled = true; e.target.textContent = "Verifying…";
    try { const v = await api("/api/ledger/verify"); e.target.textContent = v.first_failure ? "Failed at " + v.first_failure : `✓ ${nf(v.verified)} verified`; }
    catch (err) { e.target.textContent = err.message; }
  };
  updateLive();
}

window.addEventListener("resize", () => { if (DASH.data && location.hash.startsWith("#/dashboard")) drawDashboard(DASH.data, false); });
