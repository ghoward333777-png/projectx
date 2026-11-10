/* 📚 Book Query — QueryBook's first use case: choose a book from the library, then ask it anything.
   Every answer quotes the book with its exact chapter and paragraph (click to read it in place), and where the book's
   modern layer covers a claim, sets the book beside what is known today. The answering is done by the shell (bookq.py);
   the answer itself is drawn by askpage.js (akBookAnswer, akPassage). The view is built once and kept. */
"use strict";

const BQ = { root: null, books: null, book: akLoad("qb:bq:book", ""), info: null, filter: "all", search: "", last: null, busy: false };

function bqHistory(id) { try { return JSON.parse(localStorage.getItem("qb:bq:hist:" + id) || "[]"); } catch (e) { return []; } }
function bqRemember(id, q) {
  const h = [q].concat(bqHistory(id).filter(x => x !== q)).slice(0, 12);
  try { localStorage.setItem("qb:bq:hist:" + id, JSON.stringify(h)); } catch (e) { /* storage unavailable */ }
}

function bookQueryView() {
  if (!BQ.root) {
    BQ.root = el("div", { class: "view bq", id: "bqview" });
    bqLoad();
  }
  bqHeader();
  return BQ.root;
}

function bqHeader() {
  const inp = document.getElementById("askinput");
  if (inp) inp.placeholder = BQ.info ? `Ask “${BQ.info.title}”…` : "Choose a book below, then ask it anything";
}

async function bqLoad() {
  BQ.root.replaceChildren(el("div", { class: "card" }, el("p", { class: "muted" }, "Opening the library…")));
  try { BQ.books = (await (await fetch("/api/shell/library")).json()).books || []; }
  catch (e) { BQ.root.replaceChildren(el("div", { class: "card" }, el("p", { class: "note" }, "The library could not be opened. Is QueryBook still running?"))); return; }
  if (BQ.book && BQ.books.some(b => b.id === BQ.book)) await bqOpen(BQ.book, true);
  else { BQ.book = ""; bqDraw(); }
}

function bqDraw() {
  bqHeader();
  BQ.root.replaceChildren(...(BQ.book && BQ.info ? bqBookPage() : bqLibrary()));
}

/* ------------------------------------------------------------------ step 1: the library */
function bqLibrary() {
  const books = BQ.books || [];
  const n = k => books.filter(k).length;
  const filters = [
    ["all", `All ${books.length}`, () => true],
    ["nonfiction", `Nonfiction ${n(b => b.kind === "nonfiction")}`, b => b.kind === "nonfiction"],
    ["fiction", `Fiction ${n(b => b.kind === "fiction")}`, b => b.kind === "fiction"],
    ["modern", `Book vs today ${n(b => Object.keys(b.modern || {}).length)}`, b => Object.keys(b.modern || {}).length],
    ["harvested", `Harvested ${n(b => b.harvested)}`, b => b.harvested],
  ].filter(f => f[0] !== "harvested" || books.some(b => b.harvested));
  const f = (filters.find(x => x[0] === BQ.filter) || filters[0])[2];
  const s = BQ.search.toLowerCase();
  const shown = books.filter(f).filter(b => !s || [b.title, b.author, b.subject, b.structure].join(" ").toLowerCase().includes(s));
  const search = el("input", { type: "search", class: "akinput", placeholder: "Find a book — title, author or subject", value: BQ.search, "aria-label": "Find a book" });
  search.addEventListener("input", () => { BQ.search = search.value; const g = BQ.root.querySelector(".bqgrid-wrap"); if (g) g.replaceWith(bqGrid()); });
  const grid = () => bqGrid();
  function bqGrid() {
    const s2 = BQ.search.toLowerCase();
    const list = books.filter(f).filter(b => !s2 || [b.title, b.author, b.subject, b.structure].join(" ").toLowerCase().includes(s2));
    return el("div", { class: "bqgrid-wrap" }, list.length ? ["nonfiction", "fiction"].map(kind => {
      const group = list.filter(b => b.kind === kind);
      return group.length ? [el("div", { class: "libband" }, kind === "nonfiction" ? "Nonfiction" : "Fiction"),
        el("div", { class: "bqgrid" }, group.map(bqCard))] : null;
    }).flat(2) : el("p", { class: "muted" }, "No book matches."));
  }
  return [
    el("div", { class: "card bqintro" },
      el("h1", {}, "📚 Book Query"),
      el("p", {}, "Choose a book, then ask it anything. QueryBook answers from that book alone: every answer quotes the book with its exact chapter and paragraph, and where the book's knowledge has since changed, it shows the book beside what is known today."),
      el("ol", { class: "bqsteps" }, el("li", { class: "now" }, el("b", {}, "1 · Choose a book")), el("li", {}, "2 · Ask it"))),
    el("div", { class: "card" },
      el("div", { class: "akline" }, search),
      el("div", { class: "seg", style: "margin-top:10px" }, filters.map(([id, label]) => el("button", { type: "button", "aria-pressed": String(BQ.filter === id),
        onclick: () => { BQ.filter = id; bqDraw(); } }, label))),
      grid()),
  ];
}

const BQ_HUE = { nonfiction: 212, fiction: 18 };
function bqCard(b) {
  const initials = (b.title || "?").split(/[\s-]+/).filter(w => w && !/^(the|a|an|of|and|in|on|to|or|for|by|with|its)$/i.test(w))
    .slice(0, 2).map(w => w[0]).join("").toUpperCase();
  const hue = (BQ_HUE[b.kind] || 160) + ((b.title || "").length * 7) % 40;
  return el("button", { type: "button", class: "bqcard", onclick: () => bqOpen(b.id) },
    el("span", { class: "bqcover", style: `background:hsl(${hue} 45% 42%)` }, initials),
    el("span", { class: "bqmeta" },
      el("b", {}, b.title),
      el("span", { class: "small" }, `${b.author}${b.year ? " · " + (b.year < 0 ? -b.year + " BC" : b.year) : ""}`),
      el("span", { class: "small muted" }, b.subject || ""),
      el("span", { class: "libtags" },
        el("span", { class: "chip" }, `${(b.units || 0).toLocaleString()} Fact Units`),
        Object.keys(b.modern || {}).length ? el("span", { class: "chip verified" }, b.kind === "fiction" ? "real history" : "book vs today") : null,
        b.people ? el("span", { class: "chip" }, `${b.people} characters`) : null,
        b.harvested ? el("span", { class: "chip context" }, "harvested") : null)));
}

/* ------------------------------------------------------------------ step 2: the book */
async function bqOpen(id, quiet) {
  BQ.book = id; save("qb:bq:book", id); BQ.last = null;
  if (!quiet) BQ.root.replaceChildren(el("div", { class: "card" }, el("p", { class: "muted" }, "Opening the book…")));
  try {
    const r = await fetch("/api/shell/book?book=" + encodeURIComponent(id));
    if (!r.ok) throw new Error((await r.json()).error || "not found");
    BQ.info = Object.assign({}, (BQ.books || []).find(b => b.id === id) || {}, await r.json());
  } catch (e) { BQ.book = ""; BQ.info = null; save("qb:bq:book", ""); }
  bqDraw();
  if (!quiet) window.scrollTo({ top: 0 });
  const i = BQ.root.querySelector("#bq-q"); if (i && !quiet) i.focus();
}

function bqSuggestions(b) {
  const groups = [];
  if ((b.examples || []).length) groups.push(["Ask about the book", b.examples]);
  const coversModern = (b.examples || []).some(q => /since|still considered|current accepted|reasonable in|beside the modern/i.test(q));
  if (Object.keys(b.modern || {}).length && b.kind !== "fiction" && !coversModern) {
    const someCh = (b.chapters || []).find(c => /^Chapter [IVXLC]+$/.test(c.label) && c.n >= 3) || {};
    groups.push(["The book beside what is known today", [
      "Show me everything that has been discovered or corrected since this book was published",
      someCh.label ? `Which statements in ${someCh.label} are still considered correct?` : "Which statements are still considered correct?",
      "Give me the current accepted value for every measurement in the book",
      "Show the book's claims beside the modern view"]]);
  }
  const ppl = [];
  if (b.people) {
    ppl.push("List the main characters");
    (b.top_people || []).slice(0, 2).forEach(p => ppl.push(`Show the relationship network around ${p}`));
    (b.families || []).slice(0, 2).forEach(f => ppl.push(`Trace the ${f} family`));
    if ((b.top_people || [])[0]) ppl.push(`Where does ${(b.top_people || [])[0]} first appear?`);
    if (b.historical) ppl.push("Separate fictional characters from historical figures");
    else if (Object.keys(b.modern || {}).length) ppl.push("Separate fictional events from real history");
  }
  if (ppl.length) groups.push(["People and relationships", ppl]);
  groups.push(["Time and structure", ["Build a timeline of the dates in the book", "How is the book put together?"]]);
  // no near-duplicates: a generated question is dropped when an example already asks it ("around Pierre" ~ "around Pierre Bezúkhov")
  const key = q => q.toLowerCase().replace(/[^a-z ]/g, "").split(" ").slice(0, 6).join(" ");
  const seen = new Set();
  return groups.map(([t, qs]) => [t, qs.filter(q => { const k = key(q); if (seen.has(k)) return false; seen.add(k); return true; })]).filter(g => g[1].length);
}

function bqBookPage() {
  const b = BQ.info;
  const pv = b.provenance || {};
  const input = el("input", { type: "search", id: "bq-q", class: "akinput bqinput", placeholder: `Ask “${b.title}” anything…`, "aria-label": "Your question" });
  const go = () => bqAsk(input.value);
  input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  const hist = bqHistory(b.id);
  const parts = [];
  let lastPart = null;
  const chapters = (b.chapters || []).filter(c => c.n || c.label !== "Front matter");
  return [
    el("div", { class: "card bqbook" },
      el("div", { class: "akline", style: "margin-top:0" },
        el("button", { class: "btn ghost small", type: "button", onclick: () => { BQ.book = ""; BQ.info = null; save("qb:bq:book", ""); bqDraw(); } }, "← All books"),
        el("ol", { class: "bqsteps" }, el("li", {}, "1 · Choose a book ✓"), el("li", { class: "now" }, el("b", {}, "2 · Ask it")))),
      el("div", { class: "bqhead" },
        bqCard(b).querySelector(".bqcover").cloneNode(true),
        el("div", {}, el("h1", {}, b.title), el("div", {}, `${b.author} · ${b.published || b.year || ""}`),
          el("div", { class: "small muted" }, `${b.subject || ""}${b.structure ? " · " + b.structure : ""} · ${(b.units || 0).toLocaleString()} Fact Units in ${chapters.length} parts`))),
      b.about ? el("p", { class: "small" }, b.about) : null,
      el("div", { class: "akline" }, input, el("button", { class: "btn", type: "button", onclick: go }, "Ask the book")),
      el("div", { class: "small muted", style: "margin-top:6px" }, "QueryBook answers from this book alone and never invents: if the book does not say, it tells you so.")),
    el("div", { id: "bq-out" }, ...(BQ.last ? bqAnswerCards(BQ.last) : [])),
    el("div", { class: "bqcols" },
      el("div", { class: "card" }, el("h2", {}, "What you can ask"),
        bqSuggestions(b).map(([title, qs]) => el("div", { class: "bqgroup" }, el("div", { class: "alabel" }, title),
          el("div", { class: "chips" }, qs.map(q => el("button", { class: "chip btnchip", type: "button", onclick: () => { input.value = q; bqAsk(q); } }, q))))),
        hist.length ? el("div", { class: "bqgroup" }, el("div", { class: "alabel" }, "Your earlier questions"),
          el("div", { class: "chips" }, hist.map(q => el("button", { class: "chip btnchip", type: "button", onclick: () => { input.value = q; bqAsk(q); } }, q)))) : null),
      el("div", { class: "card" }, el("h2", {}, "Contents"), el("div", { class: "small muted" }, "Click a chapter to read it — every sentence is a Fact Unit."),
        el("div", { class: "bqtoc" }, chapters.map(c => {
          const head = c.part && c.part !== lastPart ? el("div", { class: "alabel", style: "margin-top:8px" }, c.part) : null;
          lastPart = c.part;
          return [head, el("button", { type: "button", class: "bqch", onclick: () => bqRead(b.id, c.n) },
            c.label + (c.title ? " — " + c.title : ""), c.editorial ? el("span", { class: "small muted" }, " (editor)") : null)];
        }).flat()))),
    el("div", { class: "small muted", style: "margin:4px 4px 24px" }, "Source: ", pv.url ? el("a", { href: pv.url, target: "_blank", rel: "noopener" }, pv.source || pv.url) : (pv.source || ""),
      pv.fetched ? ` (fetched ${pv.fetched}). ` : ". ", pv.rights || ""),
  ];
}

function bqAnswerCards(r) {
  if (r.loading) return [el("div", { class: "card" }, el("p", { class: "muted" }, `Reading ${BQ.info ? BQ.info.title : "the book"} for “${r.query}”…`))];
  if (r.error) return [el("div", { class: "card" }, el("p", { class: "note" }, r.error))];
  return akBookAnswer(r);
}

async function bqAsk(q) {
  q = (q || "").trim();
  if (!q || !BQ.book) return;
  if (current !== "bookquery") show("bookquery");
  const box = () => BQ.root.querySelector("#bq-out");
  const inp = BQ.root.querySelector("#bq-q"); if (inp) inp.value = q;
  document.getElementById("askinput").value = q;
  BQ.last = { loading: true, query: q };
  if (box()) { box().replaceChildren(...bqAnswerCards(BQ.last)); box().scrollIntoView({ behavior: "smooth", block: "start" }); }
  try {
    BQ.last = await akPost("/api/shell/book/ask", { book: BQ.book, q });
    bqRemember(BQ.book, q);
  } catch (e) { BQ.last = { error: e.message, query: q }; }
  bqDraw();
  const o = box(); if (o) o.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ------------------------------------------------------------------ reading a chapter (the Original Text layer) */
async function bqRead(book, n) {
  let j;
  try {
    const r = await fetch(`/api/shell/book/chapter?book=${encodeURIComponent(book)}&n=${n}`);
    j = await r.json(); if (!r.ok) throw new Error(j.error);
  } catch (e) { return; }
  const old = document.querySelector("dialog.passage"); if (old) { old.close(); old.remove(); }
  const c = j.chapter;
  const dlg = el("dialog", { class: "passage reader" },
    el("div", { class: "akline", style: "margin-top:0;justify-content:space-between" },
      el("span", { class: "small muted" }, j.title),
      el("span", {}, j.prev != null ? el("button", { class: "btn ghost small", type: "button", onclick: () => bqRead(book, j.prev) }, "← Previous") : null, " ",
        j.next != null ? el("button", { class: "btn ghost small", type: "button", onclick: () => bqRead(book, j.next) }, "Next →") : null, " ",
        el("button", { class: "btn small", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Close"))),
    el("h2", {}, (c.part ? c.part + ", " : "") + c.label + (c.title ? " — " + c.title : "")),
    j.paragraphs.map(p => el("div", { class: "ptext" }, el("p", {}, p.units.map(u => [el("span", { title: "Fact Unit " + u.id + " · " + u.kind }, u.text), " "])))),
    j.more ? el("p", { class: "small muted" }, "This part is long; the first 1,500 paragraphs are shown.") : null);
  document.body.append(dlg);
  dlg.showModal();
  dlg.scrollTop = 0;
}
