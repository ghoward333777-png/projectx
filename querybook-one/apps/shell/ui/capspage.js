/* ✨ AI Capabilities — the twelve things QueryBook's AI does for a person, one tile each:
   Ask/Search · Summarize · Write/Create · Organize · Analyze · Develop/Project · Tools · Processes/Workflows · Agent(s) ·
   Chatbot · Translate/Languages · Learn/Study.
   The catalogue and all the work come from the shell (caps.py, assist.py: GET /api/shell/caps, POST /api/shell/caps/run);
   this page only collects the input and draws the result, and always shows who did the work (QueryBook's rules, its
   facts, the Language app, or Claude / Gemini). Capabilities that already have a home (the Ask page and its modes, Book
   Query, Translate, STEM, Video Studio, Harvest) open that home. The view is built once and kept. */
"use strict";

const CP = { root: null, cat: null, cap: akLoad("qb:caps:cap", ""), task: {}, ai: akLoad("qb:caps:ai", "1") === "1", busy: false,
  text: {}, result: {}, chat: [], turns: [], wf: null, wfPick: "brief", wfDraft: [], lang: akLoad("qb:caps:lang", "es"), style: akLoad("qb:caps:style", ""),
  area: akLoad("qb:caps:area", ""), doctype: akLoad("qb:caps:doctype", ""), purpose: "", controls: JSON.parse(akLoad("qb:caps:controls", "{}") || "{}"), err: "" };
const CP_LANGS = [["es", "Spanish"], ["fr", "French"], ["de", "German"], ["it", "Italian"], ["pt", "Portuguese"], ["nl", "Dutch"], ["pl", "Polish"],
  ["sv", "Swedish"], ["el", "Greek"], ["ro", "Romanian"], ["ja", "Japanese"], ["zh", "Chinese"], ["ko", "Korean"], ["ar", "Arabic"], ["hi", "Hindi"],
  ["ru", "Russian"], ["tr", "Turkish"], ["sw", "Swahili"], ["uk", "Ukrainian"], ["en", "English"]];
const cpSave = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } };
const cpRun = body => akPost("/api/shell/caps/run", Object.assign({ ai: CP.ai }, body));

function capsView() {
  if (!CP.root) {
    CP.root = el("div", { class: "view caps", id: "capsview" }, el("div", { class: "card" }, el("p", { class: "muted" }, "Opening…")));
    fetch("/api/shell/caps").then(r => r.json()).then(j => { CP.cat = j; cpDraw(); })
      .catch(() => CP.root.replaceChildren(el("div", { class: "card" }, el("p", { class: "note" }, "The capabilities could not be loaded. Is QueryBook still running?"))));
  }
  const inp = document.getElementById("askinput"); if (inp) inp.placeholder = "Ask anything — a word, a fact, a calculation";
  return CP.root;
}
function capsPageView() { if (CP.textgen) { CP.textgen = false; CP.cap = akLoad("qb:caps:cap", ""); } const v = capsView(); if (CP.cat) cpDraw(); return v; }

function cpCap() { return (CP.cat.capabilities || []).find(c => c.id === CP.cap); }
function cpTask(c) { return c.tasks.find(t => t.id === CP.task[c.id]) || c.tasks[0]; }
function cpOpen(id) { if (CP.textgen && !id) return show("caps"); CP.cap = id; cpSave("qb:caps:cap", id); CP.err = ""; cpDraw(); if (id === "workflow") cpLoadWf(); if (id === "project") cpProjects(); }

function cpDraw() {
  const c = cpCap(), ai = CP.cat.ai || {};
  const head = el("div", { class: "card" },
    el("h2", {}, CP.textgen ? "✍️ AI text gen" : "✨ AI Capabilities"),
    el("p", { class: "muted" }, CP.textgen ? "Any kind of document, planned from its own record and checked at five layers: sentence flow, paragraph pattern, structure, register and the rules of its field."
      : "Twelve things QueryBook can do for you. Pick one."),
    CP.textgen ? el("p", { class: "small muted" }, `Library: ${(CP.cat.genres || []).length} kinds of document, ${(CP.cat.fields || []).length} fields, ${(CP.cat.styles || []).length} styles. ` +
      ((CP.cat.learned || {}).rules ? `Learned from sources: ${CP.cat.learned.rules} rules from ${CP.cat.learned.pages} pages of ${CP.cat.learned.sources} sources (in QueryBook's own words; no passage kept).`
        : "Nothing has been learned from a source yet.")) : null,
    el("div", { class: "small muted bqai" }, ai.claude || ai.gemini
      ? el("label", {}, el("input", { type: "checkbox", checked: CP.ai, onchange: e => { CP.ai = e.target.checked; cpSave("qb:caps:ai", CP.ai ? "1" : "0"); } }),
          ` Use ${ai.claude ? "Claude" : "Gemini"} (${ai.model}) for writing, summaries and plans. Every result says who made it. Off: QueryBook's own rules only.`)
      : "No AI key is saved, so everything here is done by QueryBook's own rules and facts — exact, but it cannot write a full draft. Save a Claude or Gemini key in the Control Panel → Harvesting → API keys to add that."));
  const tiles = el("div", { class: c ? "capstrip" : "tiles captiles" }, CP.cat.capabilities.map(k =>
    el("button", { type: "button", class: c ? "chip btnchip" + (k.id === CP.cap ? " on" : "") : "tile captile", "aria-pressed": String(k.id === CP.cap), onclick: () => cpOpen(k.id), title: k.about },
      c ? `${k.icon} ${k.name}` : [el("span", { class: "capnum" }, String(k.n)), el("span", { class: "capicon" }, k.icon), el("b", {}, k.name), el("span", { class: "small muted" }, k.about)])));
  CP.root.replaceChildren(head, ...(CP.textgen ? [] : [tiles]), ...(c ? [cpPanel(c)] : []));
}

/* AI text gen (the rail, beside Language and Translate): the Write capability opened on the writing machine */
function textGenView() {
  CP.textgen = true; CP.cap = "write";
  if (!CP.task.write || !/^write\.(doc|check|analyze|voice|story_check|styles|grammar|style|learn)$/.test(CP.task.write)) CP.task.write = "write.doc";
  const v = capsView();
  if (CP.cat) cpDraw();
  return v;
}

/* ------------------------------------------------------------------ one capability */
function cpPanel(c) {
  const t = cpTask(c);
  const box = el("div", { class: "card cappanel" },
    el("div", { class: "akline" }, el("h2", { style: "margin:0" }, `${c.icon} ${c.name}`), el("button", { type: "button", class: "btn ghost", style: "margin-left:auto", onclick: () => cpOpen("") }, "← All twelve")),
    el("p", { class: "muted" }, c.about),
    c.tasks.length > 1 ? el("div", { class: "seg" }, c.tasks.map(x => el("button", { type: "button", class: "chip btnchip" + (x.id === t.id ? " on" : ""),
      onclick: () => { CP.task[c.id] = x.id; CP.err = ""; cpDraw(); if (x.id === "proj.list") cpProjects(); } }, x.name))) : null,
    t.about ? el("p", { class: "small muted" }, t.about) : null);
  if (t.opens) box.append(el("div", { class: "akline" }, el("button", { type: "button", class: "btn", onclick: () => show(t.opens) }, `Open ${t.name} →`)));
  else if (c.id === "chat") box.append(cpChat(t));
  else if (t.id === "wf.run" || t.id === "wf.edit") box.append(cpWorkflow(t));
  else if (t.id === "proj.list") box.append(cpProjectList());
  else if (t.id === "write.styles") box.append(cpStyleLibrary(c));
  else box.append(cpInput(c, t));
  if (CP.err) box.append(el("p", { class: "note" }, CP.err));
  const r = CP.result[t.id];
  if (r && !t.opens && c.id !== "chat") box.append(cpResult(t, r));
  return box;
}

/* a question goes to the Ask page (its modes draw the answer); a text or a brief is worked on here */
function cpInput(c, t) {
  const key = t.id, single = t.input === "question";
  const field = single
    ? el("input", { class: "akinput bqinput", type: "text", value: CP.text[key] || "", placeholder: t.placeholder || "", oninput: e => { CP.text[key] = e.target.value; },
        onkeydown: e => { if (e.key === "Enter") go(); } })
    : el("textarea", { class: "aktext", rows: t.input === "text" ? 8 : 3, placeholder: t.placeholder || (t.input === "text" ? "Paste or type the text here" : "Say what you need"),
        oninput: e => { CP.text[key] = e.target.value; } }, CP.text[key] || "");
  const label = { question: "Go", goal: c.id === "agent" ? "Give it to the agent" : "Make the plan", brief: "Write it", text: t.name }[t.input] || "Go";
  const lang = t.id === "tr.quick" ? el("label", { class: "small" }, "Into ", el("select", { onchange: e => { CP.lang = e.target.value; cpSave("qb:caps:lang", CP.lang); } },
    CP_LANGS.map(([code, name]) => el("option", { value: code, selected: code === CP.lang }, name)))) : null;
  async function go() {
    const text = (CP.text[key] || "").trim();
    if (!text) { CP.err = "Type or paste something first."; return cpDraw(); }
    if (single) {                                              // Ask, the tools that ask, and the study modes: the Ask page answers
      AK.mode = t.mode || "qa"; save("qb:ask:mode", AK.mode); AK.input = "type"; save("qb:ask:input", "type");
      show("ask"); akControls(); akPanel();
      return akAsk(text);
    }
    if (t.id === "tool.speak") return cpSpeak(text);
    // the engine works from the type of document: the person is asked for it before anything is planned or judged
    if (t.option === "genre" && !CP.doctype) { CP.err = "First choose the type of document: its area, then its type."; return cpDraw(); }
    await cpDo(t.id, { task: t.id, text, option: t.id === "tr.quick" ? CP.lang : t.option === "genre" ? (CP.genre || "") : t.option === "source" ? (CP.source || "") : "",
      style: CP.style || "", field: CP.field || "", name: CP.styleName || "", stage: "plan", doctype: t.option === "genre" ? CP.doctype : "", purpose: CP.purpose || "", controls: CP.controls || {} });
    if (t.id === "write.style" || t.id === "write.learn") { try { CP.cat = await (await fetch("/api/shell/caps")).json(); } catch (e) { /* the list refreshes next time */ } cpDraw(); }
  }
  const pickOf = (label, key, first, rows, group) => el("label", { class: "small" }, label + " ", el("select", { onchange: e => { CP[key] = e.target.value; } },
    el("option", { value: "", selected: !CP[key] }, first),
    group ? [...new Set(rows.map(group))].map(gname => el("optgroup", { label: gname }, rows.filter(r => group(r) === gname).map(r => el("option", { value: r.id, selected: r.id === CP[key] }, r.name))))
      : rows.map(r => el("option", { value: r.id, selected: r.id === CP[key] }, r.name + (r.by === "you" ? " (yours)" : "")))));
  // style and field (for a document or a check); the name of a style being learned; the source a page belongs to
  const style = t.option === "genre" ? pickOf("Style", "style", "The genre's own", CP.cat.styles || [], r => r.group) : null;
  const fieldPick = t.option === "genre" ? pickOf("Field", "field", "Not chosen", CP.cat.fields || [], r => r.group) : null;
  const naming = t.option === "name" ? el("label", { class: "small" }, "Call it ", el("input", { type: "text", value: CP.styleName || "", placeholder: "My style", style: "width:14em",
    oninput: e => { CP.styleName = e.target.value; } })) : null;
  const sourcePick = t.option === "source" ? pickOf("Source", "source", "Another source",
    (CP.cat.sources || []).map(x => Object.assign({}, x, { name: x.name + (x.rules ? ` — ${x.rules} rules learned` : "") })), r => r.wave_name) : null;
  // the type of document (the universal taxonomy): the area first, then the type; then, if wished, what it is for
  const DT = (CP.cat.doctypes || { domains: [], purposes: [] }), dom = DT.domains.find(d => String(d.n) === String(CP.area));
  const genre = t.option === "genre" ? el("div", { class: "akline doctypepick" },
    el("label", { class: "small" }, el("b", {}, "1. Area "), el("select", { onchange: e => { CP.area = e.target.value; CP.doctype = ""; cpSave("qb:caps:area", CP.area); cpSave("qb:caps:doctype", ""); cpDraw(); } },
      el("option", { value: "", selected: !CP.area }, "Choose the area…"),
      DT.domains.map(d => el("option", { value: d.n, selected: String(d.n) === String(CP.area) }, d.name)))),
    el("label", { class: "small" }, el("b", {}, "2. Type of document "), el("select", { disabled: !dom, onchange: e => { CP.doctype = e.target.value; cpSave("qb:caps:doctype", CP.doctype); CP.err = ""; cpDraw(); } },
      el("option", { value: "", selected: !CP.doctype }, dom ? "Choose the type…" : "Choose the area first"),
      ...(dom ? dom.families.flatMap(f => { const opts = f.types.map(x => el("option", { value: x.id, selected: x.id === CP.doctype }, x.name + (x.full ? "  ★" : "")));
        return f.name ? [el("optgroup", { label: f.name }, opts)] : opts; }) : []))),
    el("label", { class: "small" }, "Purpose ", el("select", { onchange: e => { CP.purpose = e.target.value; } },
      el("option", { value: "", selected: !CP.purpose }, "As usual for the type"), DT.purposes.map(x => el("option", { value: x, selected: x === CP.purpose }, x)))),
    el("span", { class: "small muted" }, "★ = QueryBook holds a full record for this type; the others are planned from the type's own expected parts.")) : null;
  // the writer's controls: every aspect of the writing is the person's to set; anything left alone follows the type and the style
  const setCtl = (k, v) => { if (v) CP.controls[k] = v; else delete CP.controls[k]; cpSave("qb:caps:controls", JSON.stringify(CP.controls)); };
  const nset = Object.keys(CP.controls || {}).length;
  const controls = t.id === "write.doc" && CP.cat.controls ? el("details", { class: "small ctlbox", open: nset > 0 },
    el("summary", {}, el("b", {}, "3. Your controls"), ` — tone, voice, formality, length and more${nset ? ` (${nset} set)` : " (all as usual for the type)"}`),
    el("div", { class: "ctlgrid" },
      Object.keys(CP.cat.controls).map(k => el("label", { class: "small" }, (CP.cat.control_names || {})[k] || k, " ",
        el("select", { onchange: e => setCtl(k, e.target.value) }, el("option", { value: "", selected: !CP.controls[k] }, "—"),
          CP.cat.controls[k].map(v => el("option", { value: v, selected: CP.controls[k] === v }, v))))),
      el("label", { class: "small" }, "Length (words) ", el("input", { type: "number", min: 0, step: 50, style: "width:7em", value: CP.controls.words || "", oninput: e => setCtl("words", e.target.value) }))),
    nset ? el("button", { type: "button", class: "btn ghost", onclick: () => { CP.controls = {}; cpSave("qb:caps:controls", "{}"); cpDraw(); } }, "Clear my settings") : null) : null;
  return el("div", {}, genre, controls, field, el("div", { class: "akline" },
    el("button", { type: "button", class: "btn", disabled: CP.busy, onclick: go }, CP.busy ? "Working…" : t.id === "write.doc" ? "Plan it" : t.id === "write.learn" ? "Learn from this page" : label),
    lang, fieldPick, style, naming, sourcePick,
    single ? el("span", { class: "small muted" }, "The answer opens on the Ask page, with its sources.") : null));
}

/* the style template library: every template by kind, what it asks of the writer, and one click to use it */
function cpStyleLibrary(c) {
  const rows = CP.cat.styles || [], groups = [...new Set(rows.map(r => r.group))];
  const use = id => { CP.style = id; cpSave("qb:caps:style", id); CP.task[c.id] = "write.doc"; cpDraw(); };
  return el("div", {},
    el("p", { class: "small" }, CP.style ? ["In use: ", el("b", {}, (rows.find(r => r.id === CP.style) || { name: CP.style }).name), " ",
      el("button", { type: "button", class: "btn ghost", onclick: () => { CP.style = ""; cpSave("qb:caps:style", ""); cpDraw(); } }, "Use the genre's own instead")]
      : "No template chosen: each kind of document uses its own usual style."),
    groups.map(gname => el("div", {}, el("h3", { style: "margin:14px 0 6px" }, gname),
      el("div", { class: "stylegrid" }, rows.filter(r => r.group === gname).map(r => el("div", { class: "card stylecard" + (r.id === CP.style ? " on" : "") },
        el("b", {}, r.name + (r.by === "you" ? " (yours)" : "")),
        el("p", { class: "small", style: "margin:4px 0" }, r.about),
        r.for ? el("p", { class: "small muted", style: "margin:4px 0" }, "Good for: " + r.for) : null,
        r.asks ? el("details", { class: "small" }, el("summary", {}, "What it asks of the writer"), el("p", { class: "small muted" }, r.asks)) : null,
        el("button", { type: "button", class: "btn" + (r.id === CP.style ? "" : " ghost"), onclick: () => use(r.id) }, r.id === CP.style ? "In use — write with it →" : "Use this style")))))));
}

async function cpDo(key, body) {
  CP.busy = true; CP.err = ""; cpDraw();
  try { CP.result[key] = await cpRun(body); }
  catch (e) { CP.err = e.message; }
  CP.busy = false; cpDraw();
}

async function cpSpeak(text) {
  CP.err = "";
  try { const r = await akPost("/api/shell/say", { text: text.slice(0, 300), lang: "en" }); new Audio(r.audio).play(); }
  catch (e) { CP.err = e.message; cpDraw(); }
}

async function cpStage(t, stage, draft) {
  const text = (CP.text[t.id] || "").trim();
  if (stage === "revise" && !(CP.notes || "").trim()) { CP.err = "Say what to change first."; return cpDraw(); }
  await cpDo(t.id, { task: t.id, text, option: CP.genre || "", style: CP.style || "", field: CP.field || "", stage, draft: draft || "", notes: CP.notes || "", own: CP.own || "", doctype: CP.doctype || "", purpose: CP.purpose || "", controls: CP.controls || {} });
  if (stage === "revise") CP.notes = "";
}

function cpBy(r) { return r.by_label ? el("span", { class: "chip" + (r.by === "rules" || r.by === "facts" || r.by === "language" ? " verified" : "") }, "Made by: " + r.by_label) : null; }

function cpResult(t, r) {
  if (r.trace) return cpTrace(r);
  if (r.project) return cpProject(r.project, r);
  const out = el("div", { class: "capresult" },
    el("div", { class: "akline" }, cpBy(r),
      el("button", { type: "button", class: "btn ghost", onclick: e => { navigator.clipboard && navigator.clipboard.writeText(r.text || ""); e.target.textContent = "Copied"; } }, "Copy"),
      el("button", { type: "button", class: "btn ghost", onclick: () => cpSpeak(r.text || "") }, "🔊 Read aloud"),
      t.input === "text" ? el("button", { type: "button", class: "btn ghost", title: "Put this result in the box, to work on it further", onclick: () => { CP.text[t.id] = r.text || ""; delete CP.result[t.id]; cpDraw(); } }, "Use as the input") : null),
    r.note ? el("p", { class: "note" }, r.note) : null,
    r.header && r.rows ? cpTable(r) : el("pre", { class: "capout" }, r.text || ""),
    r.insight ? el("p", {}, el("b", {}, "In plain words: "), r.insight, " ", el("span", { class: "chip" }, r.insight_by)) : null,
    r.rules_text && r.rules_text !== r.text ? el("details", { class: "small" }, el("summary", {}, "The text's own key sentences (QueryBook's rules, no AI)"), el("pre", { class: "capout" }, r.rules_text)) : null,
    // the writing machine works in steps the person reviews: the plan, then the draft, then their notes on it
    // VOICE: before a word is drafted the writer is asked for what only they know; the draft is then built from it
    t.id === "write.doc" && r.stage === "plan" && r.interview_text ? el("div", {},
      el("details", { class: "small", open: true }, el("summary", {}, "Before it is written — your own material (so the draft is yours, not anyone's)"), el("pre", { class: "capout" }, r.interview_text)),
      el("textarea", { class: "aktext", rows: 4, placeholder: "Your answers, notes, evidence and sources — in any order. The draft uses only this, your brief and QueryBook's facts; nothing is invented.",
        oninput: e => { CP.own = e.target.value; } }, CP.own || "")) : null,
    r.voice_text && r.voice_text !== r.text ? el("details", { class: "small", open: !(r.voice || {}).passed }, el("summary", {}, "VOICE check — verified, owned, insightful, clear, engaging (QueryBook's rules, no AI)"), el("pre", { class: "capout" }, r.voice_text)) : null,
    r.story_text && r.story_text !== r.text ? el("details", { class: "small", open: !(r.story || {}).passed }, el("summary", {}, "Story check — six common habits (QueryBook's rules, no AI)"), el("pre", { class: "capout" }, r.story_text)) : null,
    r.essay_text && r.essay_text !== r.text && !(r.text || "").includes("STRUCTURE FOR THE READER") ? el("details", { class: "small", open: !(r.essay || {}).passed }, el("summary", {}, "Structure for the reader — title, introduction, index, key terms, conclusion (QueryBook's rules, no AI)"), el("pre", { class: "capout" }, r.essay_text)) : null,
    // analysis -> generation: the controls are set from what was read, and the type too when the rules found one
    r.analysis ? el("div", { class: "akline" }, el("button", { type: "button", class: "btn", onclick: () => {
        CP.controls = Object.fromEntries(Object.entries(r.analysis.controls).filter(([, v]) => v)); cpSave("qb:caps:controls", JSON.stringify(CP.controls));
        const lt = (r.analysis.likely_types || [])[0];
        if (lt) { CP.doctype = lt.id; CP.area = lt.id.split("-")[0]; cpSave("qb:caps:doctype", CP.doctype); cpSave("qb:caps:area", CP.area); }
        if ((r.analysis.styles || [])[0]) { CP.style = r.analysis.styles[0].id; cpSave("qb:caps:style", CP.style); }
        CP.task.write = "write.doc"; cpDraw(); } }, "Write with these settings →"),
      el("span", { class: "small muted" }, "Sets tone, point of view, formality and the rest from this reading. You can change any of them.")) : null,
    r.settings_text ? el("details", { class: "small", open: (r.settings_check || []).some(x => x.ok === false) }, el("summary", {}, "Your settings, checked against the draft"), el("pre", { class: "capout" }, r.settings_text)) : null,
    r.editor_text ? el("details", { class: "small", open: true }, el("summary", {}, "An editor's second reading — it does not rewrite (made by: " + (r.editor_by || "AI") + ")"), el("pre", { class: "capout" }, r.editor_text)) : null,
    t.id === "write.doc" && r.stage === "plan" && r.can_draft ? el("div", { class: "akline" },
      el("button", { type: "button", class: "btn", disabled: CP.busy, onclick: () => cpStage(t, "draft") }, CP.busy ? "Writing…" : "Write it to this plan"),
      el("span", { class: "small muted" }, "The draft is checked at five layers before you see it.")) : null,
    t.id === "write.doc" && r.stage !== "plan" && r.can_draft ? el("div", {},
      el("textarea", { class: "aktext", rows: 2, placeholder: "What should change? e.g. shorter opening; add the delivery date; make the tone warmer", oninput: e => { CP.notes = e.target.value; } }, CP.notes || ""),
      el("div", { class: "akline" }, el("button", { type: "button", class: "btn", disabled: CP.busy, onclick: () => cpStage(t, "revise", r.text) }, CP.busy ? "Revising…" : "Revise to my notes"),
        el("button", { type: "button", class: "btn ghost", disabled: CP.busy, onclick: () => cpStage(t, "draft") }, "Write it again"))) : null,
    // the writing machine: what the draft was planned from, and how the critic judged it (QueryBook's rules, no AI)
    r.critique_text && r.critique_text !== r.text ? el("details", { class: "small", open: !(r.critique || {}).passed }, el("summary", {}, "The critic's reading — five layers (QueryBook's rules, no AI)"), el("pre", { class: "capout" }, r.critique_text)) : null,
    r.blueprint_text && r.blueprint_text !== r.text ? el("details", { class: "small" }, el("summary", {}, "The blueprint it was written to"), el("pre", { class: "capout" }, r.blueprint_text)) : null,
    (r.facts || []).length && typeof r.facts[0] === "string" ? el("details", { class: "small" }, el("summary", {}, "Facts QueryBook supplied (" + r.facts.length + ")"), el("pre", { class: "capout" }, r.facts.join("\n"))) : null);
  return out;
}

function cpTable(r) {
  return el("div", { class: "tbl" }, el("table", {}, r.header.length ? el("thead", {}, el("tr", {}, r.header.map(h => el("th", {}, h)))) : null,
    el("tbody", {}, r.rows.map(row => el("tr", {}, row.map(c => el("td", {}, c)))))));
}

function cpTrace(r) {
  return el("div", { class: "capresult" },
    r.planner_label ? el("p", { class: "small muted" }, `The agent's plan (chosen by ${r.planner_label}): `, (r.plan || []).join(" → ") || "—") : null,
    r.note ? el("p", { class: "note" }, r.note) : null,
    r.trace.map((s, i) => el("div", { class: "capstep" },
      el("div", { class: "akline" }, el("b", {}, `Step ${i + 1} — ${s.name}`), s.error ? el("span", { class: "chip disputed" }, "stopped") : cpBy(s)),
      s.error ? el("p", { class: "note" }, s.error) : el("pre", { class: "capout" }, s.text || ""),
      s.note ? el("p", { class: "small muted" }, s.note) : null)),
    el("div", { class: "akline" }, el("span", { class: "small muted" }, `${r.done} of ${r.of} step${r.of === 1 ? "" : "s"} done.`),
      el("button", { type: "button", class: "btn ghost", onclick: e => { navigator.clipboard && navigator.clipboard.writeText(r.text || ""); e.target.textContent = "Copied"; } }, "Copy the final result")));
}

/* ------------------------------------------------------------------ 6 projects */
async function cpProjects() { try { CP.projects = (await cpRun({ task: "proj.list" })).projects; } catch (e) { CP.projects = []; } if (CP.cap === "project") cpDraw(); }
function cpProjectList() {
  const rows = CP.projects || [];
  if (!rows.length) return el("p", { class: "muted" }, "No projects yet. Choose “Plan a project” and say what you want to achieve.");
  return el("div", {}, rows.map(p => cpProject(p, null)));
}
function cpProject(p, r) {
  const act = async body => { try { const j = await cpRun(Object.assign({ id: p.id }, body)); CP.projects = j.projects; const cur = j.projects.find(x => x.id === p.id);
    if (CP.result["proj.plan"] && CP.result["proj.plan"].project && CP.result["proj.plan"].project.id === p.id) { if (cur) CP.result["proj.plan"].project = cur; else delete CP.result["proj.plan"]; } }
    catch (e) { CP.err = e.message; } cpDraw(); };
  const pr = p.progress || { done: 0, total: 0, percent: 0 };
  return el("div", { class: "capresult capproject" },
    el("div", { class: "akline" }, el("b", {}, p.name), p.target ? el("span", { class: "chip" }, "Target: " + p.target) : null,
      el("span", { class: "chip" + (pr.percent === 100 ? " verified" : "") }, `${pr.done} of ${pr.total} done (${pr.percent}%)`), r ? cpBy(r) : null,
      el("button", { type: "button", class: "btn ghost", style: "margin-left:auto", onclick: () => act({ task: "proj.delete" }) }, "Delete")),
    el("p", { class: "small muted" }, "Goal: " + p.goal),
    r && r.note ? el("p", { class: "note" }, r.note) : null,
    p.phases.map((ph, i) => el("div", { class: "capphase" }, el("b", {}, `${i + 1}. ${ph.name}`),
      ph.tasks.map((t, k) => el("label", { class: "captask" + (t.done ? " done" : "") }, el("input", { type: "checkbox", checked: t.done, onchange: () => act({ task: "proj.toggle", phase: i, item: k }) }), " " + t.text)),
      el("input", { class: "akinput small", type: "text", placeholder: "Add a task and press Enter", onkeydown: e => { if (e.key === "Enter" && e.target.value.trim()) act({ task: "proj.add", phase: i, text: e.target.value }); } }))),
    (p.risks || []).length ? el("div", { class: "capphase" }, el("b", {}, "What could go wrong"), p.risks.map(x => el("div", { class: "small" }, "• " + x))) : null);
}

/* ------------------------------------------------------------------ 8 workflows */
async function cpLoadWf() { try { CP.wf = await cpRun({ task: "wf.list" }); } catch (e) { CP.wf = { workflows: [], steps: [] }; } if (CP.cap === "workflow") cpDraw(); }
function cpStepLine(steps) { return steps.map(s => (CP.cat.steps.find(x => x.id === s.do) || { name: s.do }).name + (s.option ? " (" + s.option + ")" : "")).join("  →  "); }
function cpWorkflow(t) {
  if (!CP.wf) return el("p", { class: "muted" }, "Loading the workflows…");
  const list = CP.wf.workflows || [];
  if (t.id === "wf.run") {
    const w = list.find(x => x.id === CP.wfPick) || list[0];
    return el("div", {},
      el("div", { class: "capwfs" }, list.map(x => el("button", { type: "button", class: "conn" + (w && x.id === w.id ? " on" : ""), onclick: () => { CP.wfPick = x.id; cpDraw(); } },
        el("b", {}, x.name), el("span", { class: "small muted" }, cpStepLine(x.steps)), x.starter ? null : el("span", { class: "chip" }, "yours")))),
      el("textarea", { class: "aktext", rows: 7, placeholder: "Paste the text the workflow should work on", oninput: e => { CP.text["wf.run"] = e.target.value; } }, CP.text["wf.run"] || ""),
      el("div", { class: "akline" }, el("button", { type: "button", class: "btn", disabled: CP.busy || !w, onclick: () => cpDo("wf.run", { task: "wf.run", id: w.id, text: CP.text["wf.run"] || "" }) }, CP.busy ? "Working…" : `Run “${w ? w.name : ""}”`)));
  }
  let pick = (CP.cat.steps[0] || {}).id, lang = CP.lang;
  const mine = list.filter(x => !x.starter);
  const nameBox = el("input", { class: "akinput", type: "text", placeholder: "Name of the workflow", value: CP.wfName || "", oninput: e => { CP.wfName = e.target.value; } });
  return el("div", {},
    el("p", { class: "small muted" }, "Add steps in order. Each step works on the result of the one before."),
    el("ol", { class: "capdraft" }, CP.wfDraft.map((s, i) => el("li", {}, cpStepLine([s]), " ", el("button", { type: "button", class: "chipx", title: "Remove", onclick: () => { CP.wfDraft.splice(i, 1); cpDraw(); } }, "×")))),
    el("div", { class: "akline" },
      el("select", { onchange: e => { pick = e.target.value; } }, CP.cat.steps.map(s => el("option", { value: s.id }, s.name))),
      el("select", { title: "Language, for a Translate step", onchange: e => { lang = e.target.value; } }, CP_LANGS.map(([code, name]) => el("option", { value: code, selected: code === lang }, name))),
      el("button", { type: "button", class: "btn ghost", onclick: () => { if (CP.wfDraft.length < 8) CP.wfDraft.push(pick === "tr.quick" ? { do: pick, option: lang } : { do: pick }); cpDraw(); } }, "+ Add step")),
    el("div", { class: "akline" }, nameBox,
      el("button", { type: "button", class: "btn", onclick: async () => { try { CP.wf = Object.assign(CP.wf, await cpRun({ task: "wf.save", name: CP.wfName || "", steps: CP.wfDraft })); CP.wfDraft = []; CP.wfName = ""; CP.err = ""; } catch (e) { CP.err = e.message; } cpDraw(); } }, "Save the workflow")),
    mine.length ? el("div", { class: "capphase" }, el("b", {}, "Your workflows"), mine.map(x => el("div", { class: "akline small" }, el("span", {}, x.name + " — " + cpStepLine(x.steps)),
      el("button", { type: "button", class: "btn ghost", onclick: async () => { CP.wf = Object.assign(CP.wf, await cpRun({ task: "wf.delete", id: x.id })); cpDraw(); } }, "Delete")))) : null);
}

/* ------------------------------------------------------------------ 10 chatbot */
function cpChat(t) {
  const log = el("div", { class: "capchat" }, CP.chat.length ? CP.chat.map(m => el("div", { class: "capmsg " + m.role },
    el("div", { class: "capbubble" }, m.text),
    m.role === "assistant" ? el("div", { class: "small muted" }, m.by_label || "", (m.facts || []).length ? el("details", {}, el("summary", {}, `${m.facts.length} fact${m.facts.length === 1 ? "" : "s"} used`),
      m.facts.map(f => el("div", {}, `${f.subject} — ${f.predicate}: ${f.value} `, el("span", { class: "chip" }, f.where)))) : null) : null))
    : el("p", { class: "muted" }, "Say hello, or ask about a person, a place, a word, a date or a calculation. Follow-ups like “when was it built?” remember the subject."));
  const inp = el("input", { class: "akinput bqinput", type: "text", placeholder: t.placeholder || "", onkeydown: e => { if (e.key === "Enter") send(); } });
  async function send() {
    const text = inp.value.trim(); if (!text || CP.busy) return;
    CP.chat.push({ role: "user", text }); CP.busy = true; cpDraw();
    try {
      const r = await cpRun({ task: "chat.talk", text, turns: CP.turns.concat(CP.chat.slice(-8).map(m => ({ role: m.role, text: m.text }))) });
      CP.chat.push({ role: "assistant", text: r.reply, by_label: r.by_label, facts: r.facts });
      if (r.turn && r.turn.subject) CP.turns.push(r.turn);
    } catch (e) { CP.chat.push({ role: "assistant", text: e.message, by_label: "QueryBook" }); }
    CP.busy = false; cpDraw();
    const box = document.querySelector("#capsview .capchat"); if (box) box.scrollTop = box.scrollHeight;
    const again = document.querySelector("#capsview .cappanel .bqinput"); if (again) again.focus();
  }
  return el("div", {}, log, el("div", { class: "akline" }, inp, el("button", { type: "button", class: "btn", disabled: CP.busy, onclick: send }, CP.busy ? "Thinking…" : "Send"),
    CP.chat.length ? el("button", { type: "button", class: "btn ghost", onclick: () => { CP.chat = []; CP.turns = []; cpDraw(); } }, "New chat") : null));
}
