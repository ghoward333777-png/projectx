"use strict";
let lastAnswer = null, FORMULAS = [], ELEMENTS = [];

const EXAMPLES = ["12 × 7", "0.1 + 0.2", "2^100", "sqrt(2)", "25!", "factor(360)", "isprime(2^61-1)", "sind(30)",
  "15% of 200", "60 mph to km/h", "100 degF to degC", "1 atm to psi", "molar mass of C6H12O6", "Fe"];

function answerHtml(r) {
  const exact = r.exact ? '<span class="badge good">exact</span>' : '<span class="badge warn">approximate</span>';
  let extra = "";
  const d = r.detail || {};
  if (r.kind === "calc" && d.fraction && d.decimal && d.display !== d.fraction) extra += '<div class="small muted">As a fraction: <span class="mono">' + esc(d.fraction) + "</span></div>";
  if (r.kind === "calc" && d.fraction && d.decimal && d.display === d.fraction) extra += '<div class="small muted">Decimal: <span class="mono">' + esc(d.decimal) + "</span></div>";
  if (r.kind === "calc" && d.scientific) extra += '<div class="small muted">Scientific: <span class="mono">' + esc(d.scientific) + "</span></div>";
  if (r.kind === "molar") extra += molarTable(d);
  return '<div class="answer mono">' + esc(r.display) + "</div><div class=\"row small\">" + exact +
    '<span class="muted">Method: ' + esc(r.method) + "</span></div>" + extra +
    (r.kind !== "element" ? '<div style="margin-top:10px"><button class="btn quiet" id="save">Save this answer</button></div>' : "");
}

function molarTable(d) {
  return '<table class="t" style="margin-top:8px"><tr><th>Element</th><th>Count</th><th>Atomic weight</th><th>Subtotal</th></tr>' +
    d.elements.map(e => "<tr><td>" + esc(e.name) + " (" + esc(e.symbol) + ")</td><td>" + e.count + '</td><td class="mono">' + esc(e.weight) +
      '</td><td class="mono">' + esc(e.subtotal) + "</td></tr>").join("") + "</table>" +
    '<p class="small muted">' + esc(d.note) + "</p>";
}

async function ask(q) {
  q = q === undefined ? $("#q").value : q;
  $("#q").value = q;
  try {
    const r = await api("/api/ask", { q });
    lastAnswer = r;
    $("#out").innerHTML = answerHtml(r);
    const b = $("#save");
    if (b) b.onclick = () => save(r.kind, r.question, r.answer, r.detail);
  } catch (e) { $("#out").innerHTML = ""; }
}

async function save(kind, question, answer, detail) {
  const r = await api("/api/save", { kind, question, answer, detail });
  toast(r.status === "verified" ? "Saved — computed again and confirmed." : "Saved, but the re-computation differs: " + r.recomputed, r.status !== "verified");
}

// ---------------------------------------------------------------- formulas
async function loadFormulas() {
  if (FORMULAS.length) return;
  FORMULAS = (await api("/api/formulas")).formulas;
  const sel = $("#fsel");
  let field = "";
  sel.innerHTML = FORMULAS.map(f => {
    let s = "";
    if (f.field !== field) { s += (field ? "</optgroup>" : "") + '<optgroup label="' + esc(f.field) + '">'; field = f.field; }
    return s + '<option value="' + esc(f.id) + '">' + esc(f.name) + "</option>";
  }).join("") + "</optgroup>";
  sel.onchange = showFormula;
  $("#funk").onchange = showInputs;
  showFormula();
}
function currentFormula() { return FORMULAS.find(f => f.id === $("#fsel").value); }
function showFormula() {
  const f = currentFormula();
  $("#feq").textContent = f.equation;
  $("#funk").innerHTML = f.variables.filter(v => v.solvable).map(v => '<option value="' + esc(v.symbol) + '">solve for ' + esc(v.symbol) + " — " + esc(v.meaning) + "</option>").join("");
  showInputs();
}
function showInputs() {
  const f = currentFormula(), unk = $("#funk").value;
  $("#finputs").innerHTML = f.variables.filter(v => v.symbol !== unk).map(v =>
    '<label class="f" for="fi-' + esc(v.symbol) + '"><b>' + esc(v.symbol) + "</b> — " + esc(v.meaning) + " (" + esc(v.unit) + ")" + (v.default ? " · default " + esc(v.default) : "") + "</label>" +
    '<input type="text" id="fi-' + esc(v.symbol) + '" data-v="' + esc(v.symbol) + '" placeholder="' + esc(v.default || "value, e.g. 12 or 12 " + (v.unit !== "(no unit)" ? v.unit : "")) + '">').join("") +
    (Object.keys(f.constants).length ? '<p class="small muted">Constants used: ' + Object.entries(f.constants).map(([k, v]) => esc(k) + " = " + esc(v)).join(", ") + "</p>" : "");
  $("#fres").innerHTML = "";
}
async function solve() {
  const f = currentFormula(), given = {};
  $$("#finputs input").forEach(i => { if (i.value.trim()) given[i.dataset.v] = i.value.trim(); });
  try {
    const r = await api("/api/solve", { id: f.id, unknown: $("#funk").value, given, out_unit: $("#fout").value });
    $("#fres").innerHTML = '<div class="answer mono">' + esc(r.unknown) + " = " + esc(r.result.display.replace(/^≈ /, "≈ ")) + " " + esc(r.unit) + "</div>" +
      (r.converted ? '<div class="small">' + esc(r.converted) + "</div>" : "") +
      '<div class="small muted">Method: ' + esc(r.method) + " · inputs in SI: " + r.inputs.map(i => esc(i.symbol) + " = " + esc(i.si)).join(", ") + "</div>" +
      '<div style="margin-top:10px"><button class="btn quiet" id="fsave">Save this answer</button></div>';
    $("#fsave").onclick = () => save("formula", r.formula + ": " + r.unknown + " (" + Object.entries(given).map(([k, v]) => k + "=" + v).join(", ") + ")",
      r.result.value, { id: f.id, unknown: r.unknown, given });
  } catch (e) { $("#fres").innerHTML = ""; }
}

// ---------------------------------------------------------------- tables
async function loadConstants() {
  if ($("#ctab").innerHTML) return;
  const r = await api("/api/constants");
  $("#csrc").textContent = "Source: " + r.source;
  $("#ctab").innerHTML = "<tr><th>Symbol</th><th>Name</th><th>Value</th><th>Unit</th><th></th></tr>" + r.constants.map(c =>
    '<tr><td class="mono">' + esc(c.symbol) + "</td><td>" + esc(c.name) + '</td><td class="mono">' + esc(c.value) + '</td><td class="mono">' + esc(c.unit) +
    "</td><td>" + (c.exact ? '<span class="badge good">exact</span>' : '<span class="badge warn">measured</span>') + ' <span class="small muted">' + esc(c.note) + "</span></td></tr>").join("");
}
async function loadElements() {
  if (!ELEMENTS.length) {
    const r = await api("/api/elements");
    ELEMENTS = r.elements;
    $("#esrc").textContent = "Source: " + r.source;
  }
  const f = $("#efilter").value.trim().toLowerCase();
  const rows = ELEMENTS.filter(e => !f || e.name.toLowerCase().includes(f) || e.symbol.toLowerCase() === f || String(e.z) === f);
  $("#etab").innerHTML = "<tr><th>Z</th><th>Symbol</th><th>Name</th><th>Atomic weight</th></tr>" + rows.map(e =>
    "<tr><td>" + e.z + '</td><td class="mono">' + esc(e.symbol) + "</td><td>" + esc(e.name) + '</td><td class="mono">' + esc(e.weight) + "</td></tr>").join("");
}
async function molar() {
  try {
    const r = await api("/api/molar", { formula: $("#mf").value });
    $("#mout").innerHTML = '<div class="answer mono">' + esc(r.molar_mass) + " g/mol</div>" + molarTable(r) +
      '<button class="btn quiet" id="msave">Save this answer</button>';
    $("#msave").onclick = () => save("molar", r.formula, r.molar_mass + " g/mol", {});
  } catch (e) { $("#mout").innerHTML = ""; }
}

// ---------------------------------------------------------------- saved
let page = 0;
async function loadSaved() {
  const r = await api("/api/facts?limit=50&offset=" + page * 50 + "&q=" + encodeURIComponent($("#sq").value) + "&status=" + $("#sst").value);
  const badge = s => s === "verified" ? '<span class="badge good">verified</span>' : s === "mismatch" ? '<span class="badge bad">mismatch</span>' : '<span class="badge warn">' + esc(s) + "</span>";
  $("#slist").innerHTML = '<p class="small muted">' + Number(r.total).toLocaleString() + " saved</p>" +
    '<table class="t"><tr><th>Question</th><th>Answer</th><th>Status</th><th>Source</th><th></th></tr>' + r.facts.map(f =>
      "<tr><td>" + esc(f.question) + '</td><td class="mono">' + esc(f.answer) + "</td><td>" + badge(f.status) + '</td><td class="small muted">' + esc(f.source) +
      '</td><td><button class="btn quiet" data-del="' + f.id + '">Delete</button></td></tr>').join("") + "</table>" +
    '<div class="row" style="margin-top:8px">' + (page > 0 ? '<button class="btn quiet" id="prev">Previous</button>' : "") +
    ((page + 1) * 50 < r.total ? '<button class="btn quiet" id="next">Next</button>' : "") + "</div>";
  $$("[data-del]").forEach(b => b.onclick = async () => { if (confirm("Delete this saved answer?")) { await api("/api/facts/delete", { id: Number(b.dataset.del) }); loadSaved(); } });
  if ($("#prev")) $("#prev").onclick = () => { page--; loadSaved(); };
  if ($("#next")) $("#next").onclick = () => { page++; loadSaved(); };
}

// ---------------------------------------------------------------- data
async function loadData() {
  const s = await api("/api/status");
  const st = s.store;
  $("#dstatus").innerHTML = '<div class="stats">' +
    stat(Number(s.facts_total).toLocaleString(), "saved answers") + stat(Number(s.facts.verified || 0).toLocaleString(), "verified") +
    stat(Number(s.facts.mismatch || 0).toLocaleString(), "mismatches") + stat(st.backups, "backups kept") + "</div>" +
    '<p class="small">Database: <span class="mono">' + esc(st.database) + "</span> (" + Math.round(st.bytes / 1024) + " KB)</p>" +
    (st.read_only ? '<div class="note bad">The database failed its check (' + esc(st.damage) + '). Nothing will be written. Close the app and run <span class="mono">python app.py restore</span>.</div>'
      : '<div class="note good">The database passed its check when the application started.</div>');
  const b = await api("/api/backups");
  $("#blist").innerHTML = '<p class="small muted">Folder: <span class="mono">' + esc(b.folder) + "</span></p>" +
    '<ul class="list-plain small">' + b.backups.map(x => '<li class="mono">' + esc(x.name) + " · " + x.kb + " KB</li>").join("") + "</ul>";
  const h = await api("/api/imports");
  $("#ihist").innerHTML = h.imports.length ? '<table class="t small"><tr><th>Started</th><th>Read</th><th>Kept (verified)</th><th>Already here</th><th>Did not recompute</th><th>Left for other apps</th><th></th></tr>' +
    h.imports.map(i => "<tr><td>" + esc(i.started) + "</td><td>" + fmt(i.records_read) + "</td><td>" + fmt(i.imported) + "</td><td>" + fmt(i.already_present) + "</td><td>" + fmt(i.mismatched) + "</td><td>" + fmt(i.not_deterministic) + "</td><td>" + esc(i.note || "running") + "</td></tr>").join("") + "</table>" : "";
  pollJob($("#ijob"));
}
const stat = (v, k) => '<div class="stat"><div class="v">' + esc(v) + '</div><div class="k">' + esc(k) + "</div></div>";
const fmt = n => n === null || n === undefined ? "" : Number(n).toLocaleString();

async function loadHelp() {
  if ($("#htab").innerHTML) return;
  const r = await api("/api/help");
  $("#htab").innerHTML = "<tr><th>Type</th><th>Meaning</th></tr>" + r.functions.map(f => '<tr><td class="mono">' + esc(f.syntax) + "</td><td>" + esc(f.meaning) + "</td></tr>").join("") +
    '<tr><td class="mono">5 km to mi · 72 inches in cm · 1 kWh to J</td><td>unit conversion (units of different kinds are refused)</td></tr>' +
    '<tr><td class="mono">molar mass of CuSO4·5H2O</td><td>molar mass from standard atomic weights</td></tr>' +
    '<tr><td class="mono">Fe · gold · 79</td><td>element lookup</td></tr>';
}

// ---------------------------------------------------------------- wire up
document.addEventListener("DOMContentLoaded", () => {
  setupTabs(id => {
    if (id === "formulas") loadFormulas();
    if (id === "constants") loadConstants();
    if (id === "elements") loadElements();
    if (id === "saved") loadSaved();
    if (id === "data") loadData();
    if (id === "help") loadHelp();
    if (id === "diag") renderDiagnostics($("#diag"));
  });
  $("#examples").innerHTML = EXAMPLES.map(e => '<button class="btn quiet" style="margin:3px" data-ex="' + esc(e) + '">' + esc(e) + "</button>").join("");
  $$("[data-ex]").forEach(b => b.onclick = () => ask(b.dataset.ex));
  $("#go").onclick = () => ask();
  onEnter($("#q"), () => ask());
  $("#fsolve").onclick = solve;
  $("#mgo").onclick = molar;
  onEnter($("#mf"), molar);
  $("#efilter").oninput = loadElements;
  $("#sfind").onclick = () => { page = 0; loadSaved(); };
  onEnter($("#sq"), () => { page = 0; loadSaved(); });
  $("#sverify").onclick = async () => { await api("/api/verify-all", {}); pollJob($("#sjob"), () => loadSaved()); };
  api("/api/old-store-hint").then(h => { if (h.folder && !$("#oldf").value) $("#oldf").value = h.folder; });
  $("#oldcheck").onclick = async () => {
    const r = await api("/api/old-store?folder=" + encodeURIComponent($("#oldf").value));
    $("#oldinfo").innerHTML = "Found the old store at <span class=\"mono\">" + esc(r.folder) + "</span> — " + r.blocks + " block file(s)" +
      (r.manifest && r.manifest.facts ? ", about " + Number(r.manifest.facts).toLocaleString() + " facts in total (all subjects)" : "") + ".";
  };
  $("#oldgo").onclick = async () => { await api("/api/import-old", { folder: $("#oldf").value }); pollJob($("#ijob"), () => loadData()); };
  $("#jobstop").onclick = () => api("/api/job/stop", {});
  $("#bnow").onclick = async () => { const r = await api("/api/backup", {}); toast("Backup written: " + r.backup); loadData(); };
  refreshFooter();
  $("#q").focus();
});
