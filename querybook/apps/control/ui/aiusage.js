// LLM subscriptions & usage — a sub-menu of API registration (Control Panel 1.32): every LLM / AI call's time, tokens and
// estimated charge across the suite, and the subscriptions they bill to.
function aiMoney(x) { return x === null || x === undefined ? "—" : "$" + (x < 0.01 && x > 0 ? x.toFixed(4) : x.toFixed(2)); }

async function loadAiUsage() {
  const r = await api("/api/ai-usage"), t = r.totals;
  $("#ai-totals").innerHTML = [["This month: usage (estimated)", aiMoney(t.month_usage_usd)], ["Subscriptions (monthly fees)", aiMoney(t.month_subscriptions_usd)],
    ["Calls this month", QB.num(t.month_calls)], ["Tokens this month", QB.num(t.month_tokens)], ["Time in calls", QB.dur(t.month_seconds)]]
    .map(([k, v]) => `<div class="stat"><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`).join("");
  $("#ai-table").innerHTML = `<table class="t small"><tr><th>Service</th><th>Calls (failed)</th><th>Tokens in / out</th><th>Characters · minutes</th><th>Time</th>
    <th>Usage (est.)</th><th>Month total</th><th>Budget used</th><th>Plan</th><th>Monthly fee</th><th>Renews</th><th>Budget / month</th><th></th></tr>` +
    r.rows.map(x => {
      const m = x.month, s = x.subscription || {};
      const u = Object.entries(m.units || {}).map(([k, v]) => QB.num(Math.round(v * 100) / 100) + " " + k).join(" · ");
      return `<tr data-prov="${esc(x.provider)}"><td><b>${esc(x.title)}</b><div class="muted">${esc(x.kind)}${x.key_set === true ? " · key set" : ""}</div></td>
      <td>${QB.num(m.calls)}${m.failed ? " (" + m.failed + ")" : ""}</td><td>${QB.num(m.input_tokens)} / ${QB.num(m.output_tokens)}</td><td>${esc(u || "—")}</td>
      <td>${QB.dur(m.seconds)}</td><td>${aiMoney(m.cost_usd)}${m.unpriced_calls ? ` <span class="muted" title="calls without a price (billed through the subscription)">+${m.unpriced_calls} unpriced</span>` : ""}</td>
      <td><b>${aiMoney(x.month_total_usd)}</b></td>
      <td>${x.budget_used === null ? "—" : `<span class="badge ${x.budget_used >= 100 ? "bad" : x.budget_used >= 80 ? "warn" : "good"}">${x.budget_used}%</span>`}</td>
      <td><input data-f="plan" value="${esc(s.plan || "")}" placeholder="plan" style="width:6.5em"></td>
      <td><input data-f="monthly_usd" value="${s.monthly_usd ?? ""}" placeholder="$" style="width:4em"></td>
      <td><input data-f="renews" value="${esc(s.renews || "")}" placeholder="YYYY-MM-DD" style="width:6.5em"></td>
      <td><input data-f="budget_usd" value="${s.budget_usd ?? ""}" placeholder="$" style="width:4em"></td>
      <td><button class="btn quiet" data-aisave style="padding:2px 8px">Save</button> <a href="${esc(x.billing)}" target="_blank" rel="noopener">bill ↗</a></td></tr>`;
    }).join("") + "</table>";
  $$("#ai-table [data-aisave]").forEach(b => b.onclick = async () => {
    const tr = b.closest("tr"), body = { provider: tr.dataset.prov, passphrase: ($("#gs-pass") || {}).value || "" };
    tr.querySelectorAll("input[data-f]").forEach(i => { body[i.dataset.f] = i.value.trim(); });
    await api("/api/ai-usage/subscription", body); toast("Saved"); loadAiUsage();
  });
  const days = r.summary.by_day || [];
  $("#ai-days").innerHTML = days.length ? `<table class="t small"><tr><th>Day</th><th>Service</th><th>Calls</th><th>Tokens in / out</th><th>Usage (est.)</th></tr>` +
    days.map(d => `<tr><td>${esc(d.day)}</td><td>${esc(d.provider)}</td><td>${QB.num(d.calls)}</td><td>${QB.num(d.input_tokens)} / ${QB.num(d.output_tokens)}</td><td>${aiMoney(d.cost_usd)}</td></tr>`).join("") + "</table>"
    : '<p class="muted">No calls yet. Calls appear here as the programs use Gemini, OpenAI, Anthropic, Perplexity, cloud voices or Speech-to-Text.</p>';
  $("#ai-calls").innerHTML = r.calls.length ? `<table class="t small"><tr><th>When</th><th>Program</th><th>What for</th><th>Service · model</th><th>Tokens in / out</th><th>Characters · minutes</th><th>Time</th><th>Result</th><th>Charge (est.)</th></tr>` +
    r.calls.map(c => `<tr><td>${esc(new Date(c.at * 1000).toLocaleString())}</td><td>${esc(c.app || "")}</td><td>${esc(c.purpose || "")}</td><td>${esc(c.provider)} · ${esc(c.model || "")}</td>
      <td>${c.input_tokens ?? "—"} / ${c.output_tokens ?? "—"}</td><td>${c.units !== null ? QB.num(c.units) + " " + esc(c.unit) : "—"}</td><td>${c.seconds !== null ? c.seconds.toFixed(1) + " s" : "—"}</td>
      <td>${c.ok ? "ok" : '<span class="badge bad">' + esc(c.error || "failed") + "</span>"}</td><td>${c.priced ? aiMoney(c.cost_usd) : '<span class="muted">not priced</span>'}</td></tr>`).join("") + "</table>" : "";
  $("#ai-pnote").textContent = r.prices_note;
  $("#ai-prices").innerHTML = `<table class="t small"><tr><th>Service</th><th>Model (prefix)</th><th>in / 1M tokens</th><th>out / 1M tokens</th><th>per 1M characters</th><th>per minute</th><th>per second</th><th></th></tr>` +
    Object.entries(r.prices).flatMap(([prov, ms]) => Object.entries(ms).map(([m, pr]) => `<tr data-prov="${esc(prov)}" data-model="${esc(m)}"><td>${esc(prov)}</td><td>${esc(m || "(any)")}</td>` +
      ["in_per_m", "out_per_m", "per_m_chars", "per_minute", "per_second"].map(k => `<td><input data-k="${k}" value="${pr[k] ?? ""}" style="width:4.5em"></td>`).join("") +
      `<td><button class="btn quiet" data-aiprice style="padding:2px 8px">Save</button></td></tr>`)).join("") + "</table>";
  $$("#ai-prices [data-aiprice]").forEach(b => b.onclick = async () => {
    const tr = b.closest("tr"), pr = {};
    tr.querySelectorAll("input[data-k]").forEach(i => { if (i.value.trim() !== "") pr[i.dataset.k] = +i.value; });
    await api("/api/ai-usage/prices", { prices: { [tr.dataset.prov]: { [tr.dataset.model]: pr } }, passphrase: ($("#gs-pass") || {}).value || "" });
    toast("Price saved"); loadAiUsage();
  });
}

document.querySelectorAll("#rg-menu [data-rgview]").forEach(b => b.onclick = () => {
  const ai = b.dataset.rgview === "ai";
  $("#rg-table").hidden = ai; $("#ai-box").hidden = !ai;
  document.querySelectorAll("#rg-menu [data-rgview]").forEach(x => x.classList.toggle("quiet", x !== b));
  if (ai) loadAiUsage().catch(e => toast(e.message, true));
});
