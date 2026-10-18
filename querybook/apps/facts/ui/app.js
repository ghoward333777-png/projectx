"use strict";
let OPT = null, page = 0, lastQuery = {};

const statusBadge = s => s === "sourced" ? '<span class="badge good">sourced</span>' : s === "needs checking" ? '<span class="badge warn">needs checking</span>' : '<span class="badge bad">needs source</span>';
const fmt = n => n === null || n === undefined ? "" : Number(n).toLocaleString();
const stat = (v, k) => '<div class="stat"><div class="v">' + esc(v) + '</div><div class="k">' + esc(k) + "</div></div>";

async function options() {
  if (OPT) return OPT;
  OPT = await api("/api/options");
  const cats = '<option value="">All categories</option>' + OPT.categories.map(c => "<option>" + esc(c) + "</option>").join("");
  $("#cat").innerHTML = cats; $("#tcat").innerHTML = cats;
  $("#a-category").innerHTML = OPT.categories.map(c => "<option" + (c === "History" ? " selected" : "") + ">" + esc(c) + "</option>").join("");
  $("#preds").innerHTML = OPT.single_valued.map(p => '<option value="' + esc(p) + '">').join("");
  return OPT;
}

function factRow(f) {
  return '<div class="fact" data-id="' + f.id + '"><div class="st">' + esc(f.statement) + '</div><div class="meta">' +
    (f.date_text ? esc(f.date_text) + " · " : "") + (f.place ? esc(f.place) + " · " : "") + esc(f.category) + " · " + statusBadge(f.status) +
    (f.disputed ? ' <span class="badge bad">disputed</span>' : "") + " · " + f.source_count + " source" + (f.source_count === 1 ? "" : "s") + "</div></div>";
}

async function search(params) {
  lastQuery = params || { q: $("#q").value, category: $("#cat").value, status: $("#stat").value, disputed: $("#disp").checked ? 1 : "" };
  const qs = new URLSearchParams(Object.assign({ limit: 50, offset: page * 50 }, lastQuery)).toString();
  const r = await api("/api/facts?" + qs);
  $("#results").innerHTML = '<p class="small muted">' + fmt(r.total) + " fact" + (r.total === 1 ? "" : "s") + "</p>" +
    (r.facts.length ? r.facts.map(factRow).join("") : '<p class="muted">Nothing found. Add a fact, import a spreadsheet, or bring in the old QueryBook store from <b>Data &amp; backups</b>.</p>') +
    '<div class="row" style="margin-top:8px">' + (page > 0 ? '<button class="btn quiet" id="prev">Previous</button>' : "") + ((page + 1) * 50 < r.total ? '<button class="btn quiet" id="next">Next</button>' : "") + "</div>";
  wireFacts($("#results"));
  if ($("#prev")) $("#prev").onclick = () => { page--; search(lastQuery); };
  if ($("#next")) $("#next").onclick = () => { page++; search(lastQuery); };
}
function wireFacts(root) { $$(".fact", root).forEach(el => el.onclick = () => showFact(Number(el.dataset.id))); }

function sourceForm(prefix) {
  const kinds = (OPT ? OPT.source_kinds : []).map(k => "<option>" + esc(k) + "</option>").join("");
  return '<div class="srcbox" data-src="' + prefix + '"><div class="grid2">' +
    '<div><label class="f">Source name *</label><input type="text" data-k="name" placeholder="Book title, newspaper, archive…"></div>' +
    '<div><label class="f">Kind *</label><select data-k="kind"><option value="">Choose…</option>' + kinds + "</select></div>" +
    '<div><label class="f">Web address</label><input type="url" data-k="url" placeholder="https://…"></div>' +
    '<div><label class="f">Author or publisher</label><input type="text" data-k="author"></div>' +
    '<div><label class="f">Published</label><input type="text" data-k="published" placeholder="2015 · 3 May 1998"></div>' +
    '<div><label class="f">Page or section</label><input type="text" data-k="page"></div></div>' +
    '<label class="f">Quotation that supports the fact (optional)</label><input type="text" data-k="quote"></div>';
}
function readSource(box) {
  const s = {};
  $$("[data-k]", box).forEach(i => { s[i.dataset.k] = i.value.trim(); });
  return s;
}

async function showFact(id) {
  const f = await api("/api/fact?id=" + id);
  const d = $("#detail");
  d.style.display = "block";
  d.innerHTML = '<h2>' + esc(f.statement) + "</h2>" +
    '<p class="small">' + statusBadge(f.status) + (f.disputed ? ' <span class="badge bad">disputed</span>' : "") + " · " + esc(f.category) +
    (f.date_text ? " · " + esc(f.date_text) + (f.end_text ? " – " + esc(f.end_text) : "") : "") + (f.place ? " · " + esc(f.place) : "") + "</p>" +
    '<p class="small muted">About <b>' + esc(f.subject) + "</b>" + (f.predicate ? " · " + esc(f.predicate) + " · <b>" + esc(f.object || "") + "</b>" : "") +
    " · origin: " + esc(f.origin) + " · " + esc(f.created) + "</p>" +
    (f.disputed && f.others.length ? '<div class="note bad"><b>Disputed.</b> Other facts give a different value:<ul>' +
      f.others.map(o => '<li><a href="#" data-open="' + o.id + '">' + esc(o.object || o.statement) + "</a></li>").join("") + "</ul>Compare the sources of each.</div>" : "") +
    "<h3>Sources</h3>" + (f.sources.length ? '<ul class="list-plain">' + f.sources.map(s =>
      "<li><b>" + esc(s.name) + '</b> <span class="chip">' + esc(s.kind) + "</span>" + (s.author ? " · " + esc(s.author) : "") + (s.published ? " · " + esc(s.published) : "") +
      (s.page ? " · p. " + esc(s.page) : "") + (s.url ? ' · <a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.url) + "</a>" : "") +
      (s.quote ? '<div class="small muted">“' + esc(s.quote) + "”</div>" : "") +
      ' <button class="btn quiet" data-rmsrc="' + s.id + '" style="padding:2px 8px;font-size:13px">Remove</button></li>').join("") + "</ul>" : '<p class="muted">No sources yet.</p>') +
    "<h3>Add a source</h3>" + sourceForm("d") + '<button class="btn quiet" id="dsadd">Add source</button>' +
    '<div class="row" style="margin-top:16px"><button class="btn secondary" id="dedit">Edit</button><button class="btn secondary" id="ddel">Delete fact</button><button class="btn quiet" id="dclose">Close</button></div>';
  $$("[data-open]", d).forEach(a => a.onclick = e => { e.preventDefault(); showFact(Number(a.dataset.open)); });
  $$("[data-rmsrc]", d).forEach(b => b.onclick = async () => { await api("/api/fact/remove-source", { id, source_id: Number(b.dataset.rmsrc) }); showFact(id); search(lastQuery); });
  $("#dsadd").onclick = async () => { await api("/api/fact/add-source", { id, source: readSource($('[data-src="d"]', d)) }); toast("Source added."); showFact(id); search(lastQuery); };
  $("#ddel").onclick = async () => { if (confirm("Delete this fact? Its sources stay in the source list.")) { await api("/api/fact/delete", { id }); d.style.display = "none"; search(lastQuery); } };
  $("#dclose").onclick = () => { d.style.display = "none"; };
  $("#dedit").onclick = () => editFact(f);
  d.scrollIntoView({ behavior: "smooth", block: "start" });
}

function editFact(f) {
  const d = $("#detail");
  const cats = OPT.categories.map(c => "<option" + (c === f.category ? " selected" : "") + ">" + esc(c) + "</option>").join("");
  d.innerHTML = "<h2>Edit fact</h2>" +
    '<label class="f">The fact</label><textarea id="e-statement">' + esc(f.statement) + "</textarea>" +
    '<div class="grid2"><div><label class="f">Subject</label><input id="e-subject" type="text" value="' + esc(f.subject) + '"></div>' +
    '<div><label class="f">Category</label><select id="e-category">' + cats + "</select></div>" +
    '<div><label class="f">Relation</label><input id="e-predicate" type="text" list="preds" value="' + esc(f.predicate || "") + '"></div>' +
    '<div><label class="f">Value</label><input id="e-object" type="text" value="' + esc(f.object || "") + '"></div>' +
    '<div><label class="f">Date</label><input id="e-date" type="text" value="' + esc(f.date_text || "") + '"></div>' +
    '<div><label class="f">End date</label><input id="e-end" type="text" value="' + esc(f.end_text || "") + '"></div>' +
    '<div><label class="f">Place</label><input id="e-place" type="text" value="' + esc(f.place || "") + '"></div></div>' +
    '<div class="row" style="margin-top:12px"><button class="btn" id="esave">Save changes</button><button class="btn quiet" id="ecancel">Cancel</button></div>';
  $("#ecancel").onclick = () => showFact(f.id);
  $("#esave").onclick = async () => {
    const v = k => $("#e-" + k).value;
    await api("/api/fact/update", { id: f.id, fact: { statement: v("statement"), subject: v("subject"), category: v("category"), predicate: v("predicate"),
      object: v("object"), date: v("date").replace(/^c\. /, "c. "), end_date: v("end"), place: v("place") } });
    toast("Saved."); showFact(f.id); search(lastQuery);
  };
}

// ---------------------------------------------------------------- add
function resetAdd() {
  ["statement", "subject", "predicate", "object", "date", "end", "place"].forEach(k => { $("#a-" + k).value = ""; });
  $("#srcs").innerHTML = sourceForm("a0");
}
async function saveFact() {
  const v = k => $("#a-" + k).value;
  const sources = $$("#srcs [data-src]").map(readSource).filter(s => s.name);
  const r = await api("/api/fact/add", { fact: { statement: v("statement"), subject: v("subject"), predicate: v("predicate"), object: v("object"),
    date: v("date"), end_date: v("end"), place: v("place"), category: v("category") }, sources });
  toast(r.merged ? "This fact was already here — your source was added to it." : (sources.length ? "Fact saved." : "Fact saved. It needs a source to count as sourced."));
  resetAdd();
}

// ---------------------------------------------------------------- timeline
async function timeline(params) {
  const p = params || { from: $("#tfrom").value, to: $("#tto").value, category: $("#tcat").value };
  const r = await api("/api/facts?" + new URLSearchParams(Object.assign({ order: "date", limit: 500 }, p)).toString());
  const dated = r.facts.filter(f => f.date_sort !== null);
  let html = "", last = null;
  dated.forEach(f => {
    const y = Math.trunc(f.date_sort / 10000);
    const label = y < 0 ? (-y) + " BC" : String(y);
    if (label !== last) { html += '<div class="yearhead">' + esc(label) + "</div>"; last = label; }
    html += factRow(f);
  });
  $("#tl").innerHTML = '<p class="small muted">' + fmt(dated.length) + " dated fact" + (dated.length === 1 ? "" : "s") + (r.total > 500 ? " (first 500 shown — narrow the range)" : "") + "</p>" +
    (html || '<p class="muted">No dated facts in this range.</p>');
  wireFacts($("#tl"));
  $$(".fact", $("#tl")).forEach(el => el.onclick = () => { $('nav.tabs button[data-tab="search"]').click(); showFact(Number(el.dataset.id)); });
}

// ---------------------------------------------------------------- news
async function loadNews() {
  await options();
  const r = await api("/api/feeds");
  $("#feeds").innerHTML = r.feeds.length ? '<table class="t"><tr><th>Feed</th><th>Last fetched</th><th>Headlines</th><th></th></tr>' + r.feeds.map(f =>
    "<tr><td><b>" + esc(f.name) + '</b><div class="small muted mono">' + esc(f.url) + "</div></td><td class=\"small\">" + esc(f.last_fetched || "never") +
    (f.last_status ? '<div class="muted">' + esc(f.last_status) + "</div>" : "") + "</td><td>" + fmt(f.headlines) +
    '</td><td><button class="btn quiet" data-fetch="' + f.id + '">Fetch</button> <button class="btn quiet" data-rm="' + f.id + '">Remove</button></td></tr>').join("") + "</table>"
    : '<p class="muted">No feeds yet. Add one below — any RSS or Atom address from a news outlet.</p>';
  $$("[data-fetch]").forEach(b => b.onclick = async () => { b.disabled = true; b.textContent = "Fetching…";
    try { const x = await api("/api/feeds/fetch", { id: Number(b.dataset.fetch) }); toast(x.new_headlines + " new headline(s)."); } finally { loadNews(); } });
  $$("[data-rm]").forEach(b => b.onclick = async () => { if (confirm("Remove this feed and its headlines? Facts you added from it stay.")) { await api("/api/feeds/remove", { id: Number(b.dataset.rm) }); loadNews(); } });
  $("#fsugg").innerHTML = "Suggestions: " + OPT.suggested_feeds.map(f => '<a href="#" data-sname="' + esc(f.name) + '" data-surl="' + esc(f.url) + '">' + esc(f.name) + "</a>").join(" · ");
  $$("[data-surl]").forEach(a => a.onclick = e => { e.preventDefault(); $("#fname").value = a.dataset.sname; $("#furl").value = a.dataset.surl; });
  const h = await api("/api/headlines");
  $("#heads").innerHTML = h.headlines.length ? '<ul class="list-plain">' + h.headlines.map(x =>
    "<li><b>" + esc(x.title) + '</b><div class="small muted">' + esc(x.author || x.feed_name) + (x.author ? " (YouTube channel)" : "") + " reported · " + esc(x.published || "") +
    (x.link ? ' · <a href="' + esc(x.link) + '" target="_blank" rel="noopener noreferrer">open</a>' : "") + "</div>" +
    (x.summary ? '<div class="small">' + esc(x.summary) + "</div>" : "") +
    (x.fact_id ? '<span class="badge good">added as a fact</span>' : '<button class="btn quiet" data-promote="' + x.id + '" style="margin-top:4px">Add as fact</button>') + "</li>").join("") + "</ul>"
    : '<p class="muted">No headlines yet. Press Fetch on a feed.</p>';
  $$("[data-promote]").forEach(b => b.onclick = async () => { await api("/api/headlines/promote", { id: Number(b.dataset.promote) }); toast("Added as a news fact, with the outlet as its source."); loadNews(); });
}

// ---------------------------------------------------------------- sources, data
async function loadSources() {
  const r = await api("/api/sources");
  $("#slist").innerHTML = r.sources.length ? '<table class="t"><tr><th>Source</th><th>Kind</th><th>Facts</th></tr>' + r.sources.map(s =>
    "<tr><td><b>" + esc(s.name) + "</b>" + (s.author ? " · " + esc(s.author) : "") + (s.url ? '<div class="small"><a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.url) + "</a></div>" : "") +
    '</td><td><span class="chip">' + esc(s.kind) + "</span></td><td>" + fmt(s.facts) + "</td></tr>").join("") + "</table>" : '<p class="muted">No sources yet.</p>';
}
async function loadData() {
  const s = await api("/api/status"), st = s.store;
  $("#dstatus").innerHTML = '<div class="stats">' + stat(fmt(s.facts_total), "facts") + stat(fmt(s.facts.sourced || 0), "sourced") +
    stat(fmt(s.facts["needs checking"] || 0), "need checking") + stat(fmt(s.facts["needs source"] || 0), "need a source") + stat(fmt(s.disputed), "disputed") +
    stat(fmt(s.sources), "sources") + "</div>" +
    '<p class="small">Database: <span class="mono">' + esc(st.database) + "</span> (" + Math.round(st.bytes / 1024) + " KB) · search: " + (s.full_text_search ? "full-text" : "simple") + "</p>" +
    (st.read_only ? '<div class="note bad">The database failed its check (' + esc(st.damage) + '). Nothing will be written. Close the app and run <span class="mono">python app.py restore</span>.</div>'
      : '<div class="note good">The database passed its check when the application started.</div>');
  const b = await api("/api/backups");
  $("#blist").innerHTML = '<p class="small muted">Folder: <span class="mono">' + esc(b.folder) + '</span></p><ul class="list-plain small">' + b.backups.map(x => '<li class="mono">' + esc(x.name) + " · " + x.kb + " KB</li>").join("") + "</ul>";
  const h = await api("/api/imports");
  $("#ihist").innerHTML = h.imports.length ? '<table class="t small"><tr><th>Kind</th><th>Started</th><th>Read</th><th>Added</th><th>Already here</th><th>Skipped</th><th></th></tr>' +
    h.imports.map(i => "<tr><td>" + esc(i.kind) + "</td><td>" + esc(i.started) + "</td><td>" + fmt(i.read) + "</td><td>" + fmt(i.added) + "</td><td>" + fmt(i.merged) + "</td><td>" + fmt(i.skipped) + "</td><td>" + esc(i.note || "") + "</td></tr>").join("") + "</table>" : "";
  pollJob($("#ijob"));
}

document.addEventListener("DOMContentLoaded", async () => {
  await options();
  resetAdd();
  setupTabs(id => {
    if (id === "search") search(lastQuery.q !== undefined ? lastQuery : undefined);
    if (id === "timeline") timeline();
    if (id === "news") loadNews();
    if (id === "sources") loadSources();
    if (id === "data") loadData();
    if (id === "commons") renderCommons($("#commons"));
    if (id === "diag") renderDiagnostics($("#diag"));
  });
  $("#go").onclick = () => { page = 0; search(); };
  onEnter($("#q"), () => { page = 0; search(); });
  ["#cat", "#stat", "#disp"].forEach(s => $(s).onchange = () => { page = 0; search(); });
  $("#today").onclick = () => { const d = new Date(); page = 0; $("#q").value = ""; search({ month: d.getMonth() + 1, day: d.getDate(), order: "date" }); };
  $("#moresrc").onclick = () => $("#srcs").insertAdjacentHTML("beforeend", sourceForm("a" + $$("#srcs [data-src]").length));
  $("#save").onclick = saveFact;
  $("#tgo").onclick = () => timeline();
  $("#fadd").onclick = async () => { await api("/api/feeds/add", { name: $("#fname").value, url: $("#furl").value }); $("#fname").value = ""; $("#furl").value = ""; loadNews(); };
  $("#csvfile").onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    const r = await api("/api/import-csv", { text });
    $("#csvout").innerHTML = r.error_count ? '<div class="note bad">' + esc(r.note) + "<ul>" + r.errors.map(x => "<li>Line " + x.line + ": " + esc(x.error) + "</li>").join("") + "</ul></div>"
      : '<div class="note good">Added ' + fmt(r.added) + " fact(s); " + fmt(r.merged) + " were already here and gained the new sources.</div>";
    e.target.value = "";
    loadData();
  };
  api("/api/old-store-hint").then(h => { if (h.folder && !$("#oldf").value) $("#oldf").value = h.folder; });
  $("#oldcheck").onclick = async () => {
    const r = await api("/api/old-store?folder=" + encodeURIComponent($("#oldf").value));
    $("#oldinfo").innerHTML = 'Found the old store at <span class="mono">' + esc(r.folder) + "</span> — " + r.blocks + " block file(s)" +
      (r.manifest && r.manifest.facts ? ", about " + fmt(r.manifest.facts) + " facts in total (all subjects)" : "") + ".";
  };
  $("#oldgo").onclick = async () => { await api("/api/import-old", { folder: $("#oldf").value }); pollJob($("#ijob"), () => loadData()); };
  $("#jobstop").onclick = () => api("/api/job/stop", {});
  $("#bnow").onclick = async () => { const r = await api("/api/backup", {}); toast("Backup written: " + r.backup); loadData(); };
  refreshFooter();
});

document.addEventListener("DOMContentLoaded", () => {
  const ytSearch = async () => { const r = await api("/api/youtube/search", { q: $("#ytq").value }); toast(r.new_headlines + " new video(s) — " + r.status); loadNews(); };
  $("#ytgo").onclick = ytSearch; onEnter($("#ytq"), ytSearch);
  $("#ytadd").onclick = async () => { const r = await api("/api/youtube/add", { url: $("#yturl").value }); $("#yturl").value = ""; toast("Added: " + r.video.title + " — " + r.video.channel); loadNews(); };
});
