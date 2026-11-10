// Control Panel → Books: the Book Harvester. Find books (Gutenberg's catalog ranked by downloads, or the Internet Archive),
// add one by its address, import a research folder; watch the harvest; review each book's Rights Record.
"use strict";
let BK = null, BK_FOUND = [], BK_TIMER = null;

async function loadBooks() {
  BK = await api("/api/books");
  $("#bk-blocked").textContent = BK.blocked_authors.join("; ");
  $("#bk-summary").innerHTML = `<b>${fmt(BK.books.length)}</b> harvested book(s) in <code>${esc(BK.library)}</code> · <b>${BK.bundled}</b> bundled with QueryBook` +
    ` · ${BK.running ? '<span class="good-t">harvesting now</span>' : "idle"} · ${fmt(BK.queued)} waiting · ${fmt(BK.done)} harvested · ${BK.held.length} held for review`;
  $("#bk-sources").innerHTML = `<table class="t"><tr><th>#</th><th>Source</th><th>Kind</th><th>Status</th><th>Access</th><th>Rights</th><th>Use in QueryBook</th></tr>` +
    BK.sources.map(s => `<tr><td>${s.priority}</td><td><b>${esc(s.name)}</b><div class="small muted">${esc(s.scale)}</div></td><td class="small">${esc(s.class)}</td>
      <td><span class="chip ${s.status === "active" ? "good" : s.status === "research only" ? "bad" : ""}">${esc(s.status)}</span></td>
      <td class="small">${esc(s.access)}</td><td class="small">${esc(s.rights)}</td><td class="small">${esc(s.use)}</td></tr>`).join("") + "</table>";
  if (!$("#bk-rights").options.length) $("#bk-rights").innerHTML = BK.rights_choices.map(r => `<option>${esc(r)}</option>`).join("");
  const job = [];
  if (BK.current) job.push(`<p><b>Now:</b> ${esc(BK.current.title || BK.current.id)} <span class="small muted">(${esc(BK.current.source)})</span></p>`);
  if (BK.queue.length) job.push(`<p class="small muted">Next: ${BK.queue.slice(0, 8).map(c => esc(c.title || c.id)).join(" · ")}${BK.queued > 8 ? " …" : ""}</p>`);
  if (BK.held.length) job.push(`<details><summary>${BK.held.length} held for review</summary><table class="t small"><tr><th>Book</th><th>Why</th></tr>` +
    BK.held.slice().reverse().map(h => `<tr><td>${esc(h.title || h.id)}</td><td>${esc(h.why)}</td></tr>`).join("") + "</table></details>");
  if (BK.failed.length) job.push(`<details><summary>${BK.failed.length} failed</summary><table class="t small">` +
    BK.failed.slice().reverse().map(h => `<tr><td>${esc(h.title || h.id)}</td><td>${esc(h.error)}</td></tr>`).join("") + "</table></details>");
  job.push(BK.log.length ? `<div class="small" style="max-height:220px;overflow:auto">${BK.log.slice().reverse().map(l => `<div><span class="muted">${esc(l.at.slice(11, 19))}</span> ${esc(l.msg)}</div>`).join("")}</div>`
    : '<p class="muted small">Nothing harvested yet — step 2 or 3.</p>');
  $("#bk-job").innerHTML = job.join("");
  $("#bk-count").textContent = `— ${BK.books.length} harvested`;
  $("#bk-books").innerHTML = BK.books.length ? `<table class="t"><tr><th>Book</th><th>Source</th><th>Fact Units</th><th>Rights Record</th><th>Review</th><th></th></tr>` +
    BK.books.map(b => {
      const rr = b.rights_record || {}, rv = rr.human_review || {};
      return `<tr><td><b>${esc(b.title)}</b><div class="small muted">${esc(b.author || "")}</div></td>
        <td class="small">${esc(rr.source || "")} ${esc(rr.source_id || "")}${rr.transformation && rr.transformation.ocr ? ' <span class="chip">OCR</span>' : ""}</td>
        <td>${fmt(b.units)}</td>
        <td class="small"><details><summary>${esc(rr.rights_status || "")}</summary>
          <div>Territory: ${esc(rr.territory || "")}</div><div>Original publication: ${esc(rr.original_publication || "")}</div>
          <div>Source file: ${esc((rr.source_file || {}).format || "")}, ${fmt((rr.source_file || {}).bytes || 0)} bytes, SHA-256 <code>${esc(((rr.source_file || {}).sha256 || "").slice(0, 16))}…</code></div>
          <div>Ingested: ${esc(rr.ingested || "")} · ${esc((rr.transformation || {}).normaliser || "")} · ${esc((rr.transformation || {}).parser || "")}</div></details></td>
        <td class="small">${rv.status === "reviewed" ? `<span class="chip good">reviewed</span> ${esc(rv.by)}` : `<button class="btn quiet bk-review" data-id="${esc(b.id)}">Mark reviewed</button>`}</td>
        <td><button class="btn quiet bk-remove" data-id="${esc(b.id)}" data-t="${esc(b.title)}">Remove</button></td></tr>`;
    }).join("") + "</table>" : '<p class="muted">No harvested books yet. The 19 bundled books are always in Book Query.</p>';
  $$(".bk-review").forEach(b => b.onclick = async () => { await api("/api/books/review", { book: b.dataset.id, by: "admin", status: "reviewed" }); loadBooks(); });
  $$(".bk-remove").forEach(b => b.onclick = async () => { if (!confirm(`Remove “${b.dataset.t}” from the library?`)) return; await api("/api/books/remove", { book: b.dataset.id }); loadBooks(); });
  clearTimeout(BK_TIMER);
  if (BK.running) BK_TIMER = setTimeout(() => { if (!$("#books").hidden) loadBooks().catch(() => {}); }, 4000);
}

function bkDrawFound() {
  if (!BK_FOUND.length) { $("#bk-found").innerHTML = '<p class="muted small">Nothing found.</p>'; return; }
  const fresh = BK_FOUND.filter(c => !c.have);
  $("#bk-found").innerHTML = `<div class="row"><button class="btn" id="bk-take">Harvest the ${fresh.length} checked</button><span class="small muted">${BK_FOUND.length - fresh.length} already in the library</span></div>
    <table class="t small"><tr><th></th><th>Title</th><th>Author</th><th>Subject</th><th>Rank</th><th>Rights</th></tr>` +
    BK_FOUND.map((c, k) => `<tr class="${c.have ? "muted" : ""}"><td><input type="checkbox" data-k="${k}" ${c.have || c.rights === "unknown" ? "" : "checked"} ${c.have ? "disabled" : ""}></td>
      <td>${esc(c.title)}</td><td>${esc(c.author || "")}</td><td>${esc(c.subject)}</td><td>${c.rank || ""}</td>
      <td>${c.have ? "in the library" : c.source === "internet-archive" ? esc(c.rights) + ` <span class="muted">(${esc(c.why)})</span>` : "public domain in the USA"}</td></tr>`).join("") + "</table>";
  $("#bk-take").onclick = async () => {
    const pick = $$("#bk-found input[data-k]:checked").map(i => BK_FOUND[+i.dataset.k]);
    const r = await api("/api/books/harvest", { candidates: pick });
    toast(`${r.added} book(s) added to the harvest`); loadBooks();
  };
}

async function bkFind(phase) {
  $("#bk-find-out").textContent = phase ? "Reading the catalog and the download rankings (this takes a minute for 1,000 books)…" : "Searching…";
  try {
    const r = await api("/api/books/discover", { phase, source: phase ? "gutenberg" : $("#bk-source").value, subjects: $("#bk-subjects").value,
      per_subject: +$("#bk-per").value || 10, language: $("#bk-lang").value });
    BK_FOUND = r.candidates;
    $("#bk-find-out").textContent = `${BK_FOUND.length} found.`;
    bkDrawFound();
  } catch (e) { $("#bk-find-out").textContent = ""; }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#bk-refresh").onclick = () => loadBooks();
  $("#bk-find").onclick = () => bkFind(null);
  $$("#books [data-phase]").forEach(b => b.onclick = () => bkFind(b.dataset.phase));
  $("#bk-add").onclick = async () => {
    const r = await api("/api/books/address", { url: $("#bk-url").value, source: $("#bk-asrc").value, rights: $("#bk-rights").value,
      title: $("#bk-title").value, author: $("#bk-author").value });
    toast(r.added ? "Added to the harvest" : "Already in the harvest"); loadBooks();
  };
  $("#bk-import").onclick = async () => {
    const r = await api("/api/books/import", { folder: $("#bk-folder").value, agree: $("#bk-agree").checked, rights: "licensed for noncommercial research" });
    toast(`${r.imported.length} volume(s) imported`); loadBooks();
  };
  $("#bk-stop").onclick = async () => { await api("/api/books/stop", {}); toast("Stopping after the current book"); loadBooks(); };
  $("#bk-start").onclick = async () => { await api("/api/books/start", {}); loadBooks(); };
  if (location.hash === "#books" || (document.querySelector("#books") && !document.querySelector("#books").hidden)) loadBooks().catch(() => {});
});
