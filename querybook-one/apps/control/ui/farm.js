// Control Panel → Farm out: give datasets to another computer, download its harvester, import what it sealed.
"use strict";
let FM = null;

async function loadFarm() {
  FM = await api("/api/farm");
  const sel = new Set($$("#fm-datasets input:checked").map(i => i.value));
  const byArea = {};
  FM.datasets.filter(d => !d.helper).forEach(d => (byArea[d.area] = byArea[d.area] || []).push(d));
  $("#fm-datasets").innerHTML = Object.entries(byArea).map(([area, ds]) =>
    `<div class="fm-area"><b>${esc(area)}</b>` + ds.map(d => {
      const taken = d.farmed_to;
      return `<label class="fm-dsrow${taken ? " taken" : ""}" title="${esc(d.title)}"><input type="checkbox" value="${esc(d.key)}"${taken ? " disabled" : ""}${sel.has(d.key) ? " checked" : ""}>
        <span>${esc(d.key)}</span><span class="small muted">${taken ? "given to " + esc(taken) : d.facts_here ? fmt(d.facts_here) + " facts here" : ""}</span></label>`;
    }).join("") + "</div>").join("");
  $$("#fm-datasets input").forEach(i => i.onchange = fmCount);
  fmCount();
  const act = FM.assignments.filter(a => a.status === "active"), old = FM.assignments.filter(a => a.status !== "active");
  $("#fm-list").innerHTML = (act.length ? `<table class="t"><tr><th>Computer</th><th>Datasets</th><th>Brought back</th><th></th></tr>` + act.map(a => {
    const im = a.imported || {}, tally = Object.entries(im.tally || {}).sort((x, y) => y[1] - x[1]).slice(0, 4);
    const file = `QueryBook-Harvester-${a.machine}-${a.os === "windows" ? "Windows" : "Mac"}.zip`;
    return `<tr><td><b>${esc(a.machine)}</b><div class="small muted">${a.os === "windows" ? "Windows" : "Mac"} · ${esc(a.ip || "any IP address")} · ${esc(a.created.slice(0, 10))}${a.note ? " · " + esc(a.note) : ""}</div></td>
      <td class="small">${a.datasets.map(esc).join(", ")}</td>
      <td class="small">${im.files ? `${fmt(im.new)} new of ${fmt(im.facts)} · ${im.files} file(s)<div class="muted">${tally.map(([k, v]) => esc(k) + " " + fmt(v)).join(" · ")}</div>` : '<span class="muted">nothing yet</span>'}</td>
      <td><a class="btn" href="/api/farm/package?id=${encodeURIComponent(a.id)}" download="${esc(file)}">Download harvester</a>
        <button class="btn quiet fm-revoke" data-id="${esc(a.id)}" data-m="${esc(a.machine)}">End</button></td></tr>`;
  }).join("") + "</table>" : '<p class="muted">No computer has datasets yet — step 1.</p>') +
    (old.length ? `<p class="small muted">Ended: ${old.map(a => esc(a.machine) + " (" + a.datasets.length + " datasets)").join(", ")}</p>` : "") +
    `<p class="small muted">The Windows harvester ${FM.windows_python_inside ? "carries Python inside — nothing to install" : "needs Python 3.10+ from python.org on that PC (start this server from QueryBook.zip to put Python inside)"}.
      The Mac harvester uses the Mac's Python 3. Each zip contains this server's public key only — never the key that opens the sealed files.</p>`;
  $$(".fm-revoke").forEach(b => b.onclick = async () => {
    if (!confirm(`End ${b.dataset.m}'s harvesting? Its datasets come back to this server. Bring its last sealed files here first (step 3).`)) return;
    const r = await api("/api/farm/revoke", { id: b.dataset.id }); toast(r.summary); loadFarm();
  });
  const cur = $("#fm-drive").value;
  $("#fm-drive").innerHTML = '<option value="">Choose a drive…</option>' + FM.drives.map(d => `<option value="${esc(d.path)}">${esc(d.path)} — ${d.free_gb} GB free</option>`).join("");
  if (cur) $("#fm-drive").value = cur;
}

function fmCount() {
  const n = $$("#fm-datasets input:checked").length;
  $("#fm-count").textContent = n ? n + " chosen" : "— each goes to one computer only";
}

document.addEventListener("DOMContentLoaded", () => {
  $("#fm-refresh").onclick = () => loadFarm().catch(e => toast(e.message));
  if ($("#farm").classList.contains("active")) loadFarm().catch(e => toast(e.message));   // opened straight on this tab (#farm)
  $("#fm-drive").onchange = () => { if ($("#fm-drive").value) $("#fm-folder").value = $("#fm-drive").value.replace(/[\\/]$/, "") + (FM && FM.drives.length && $("#fm-drive").value.includes(":") ? "\\" : "/") + "QueryBook-Harvest"; };
  $("#fm-assign").onclick = async () => {
    const os_ = (document.querySelector('input[name="fm-os"]:checked') || {}).value;
    const r = await api("/api/farm/assign", { machine: $("#fm-machine").value, ip: $("#fm-ip").value, os: os_, note: $("#fm-note").value,
      datasets: $$("#fm-datasets input:checked").map(i => i.value) });
    $("#fm-assign-out").textContent = r.summary; toast(r.summary);
    $$("#fm-datasets input:checked").forEach(i => i.checked = false);
    loadFarm();
  };
  $("#fm-import").onclick = async () => {
    $("#fm-import-out").innerHTML = '<p class="muted">Opening and checking the sealed files…</p>';
    try {
      const r = await api("/api/farm/import", { folder: $("#fm-folder").value });
      const tally = Object.entries(r.tally).sort((a, b) => b[1] - a[1]);
      $("#fm-import-out").innerHTML = `<div class="note good"><b>${fmt(r.new)} new facts</b> from ${r.files} sealed file(s) (${fmt(r.facts)} in them; ${fmt(r.duplicates)} already held).` +
        (r.skipped_before ? ` ${r.skipped_before} file(s) were imported before and skipped.` : "") + "</div>" +
        (tally.length ? `<table class="t small"><tr><th>Record type</th><th>Records</th></tr>${tally.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${fmt(v)}</td></tr>`).join("")}</table>` : "") +
        (r.refused.length ? `<div class="note bad">${r.refused.length} file(s) refused: ${r.refused.map(x => esc(x.file) + " — " + esc(x.why)).join("; ")}</div>` : "");
      loadFarm();
    } catch (e) { $("#fm-import-out").innerHTML = ""; }
  };
});
