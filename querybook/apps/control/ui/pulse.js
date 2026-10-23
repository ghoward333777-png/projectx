// The master harvest status bar: one line, on every Control Panel page, saying whether harvesting is running,
// how fast facts arrive and what each application is doing. Polls /api/panel/pulse every 5 seconds.
"use strict";
(function () {
  const bar = document.getElementById("hbar");
  if (!bar) return;
  const css = document.createElement("style");
  css.textContent = `
    .hbar { position: sticky; top: 0; z-index: 9; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 8px 16px;
            background: var(--panel); border-bottom: 1px solid var(--line); font-size: 13px; }
    .hbar b { color: var(--ink); }
    .hb-st { font-weight: 700; padding: 3px 12px; border-radius: 999px; color: #fff; background: #7a8594; }
    .hb-st.run { background: #1f8a55; } .hb-st.wait { background: #b7791f; } .hb-st.stall { background: #a8322d; }
    .hb-mut { color: var(--muted); }
    .hb-apps { display: flex; gap: 6px; flex-wrap: wrap; }
    .hb-app { border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; font-size: 12px; color: var(--muted); max-width: 420px;
              overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .hb-app i { font-style: normal; opacity: .8; }
    .hb-app.working { border-color: #1f8a55; color: var(--good); } .hb-app.waiting { border-color: #b7791f; color: #b7791f; }
    .hb-app.stalled { border-color: #a8322d; color: var(--bad); }
    .hb-btn { margin-left: auto; }`;
  document.head.appendChild(css);
  const e = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const n = x => Number(x || 0).toLocaleString();
  const ago = s => s == null ? "none yet" : s < 90 ? s + " s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago";
  const LABEL = { harvesting: "Harvesting", waiting: "Harvesting — sources waiting their turn", stalled: "Harvest stalled",
    stopped: "Harvest stopped", "no-apps": "No application running", error: "Control Panel not answering" };
  const ICON = { working: "●", waiting: "⏳", paused: "⏸", stalled: "⚠", off: "○" };

  async function act(action) {
    try {
      const r = await fetch("/api/panel/harvest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
      if (!r.ok) throw new Error((await r.json()).error || r.status);
    } catch (err) { bar.querySelector(".hb-msg").textContent = "Could not " + action + ": " + err.message; }
    tick();
  }

  function render(p) {
    const cls = { harvesting: "run", waiting: "wait", stalled: "stall", error: "stall" }[p.overall] || "";
    const apps = (p.apps || []).map(a => `<span class="hb-app ${e(a.state)}" title="${e(a.name + ": " + a.why)}">${ICON[a.state] || ""} ${e(a.name)}` +
      (a.state === "working" || a.new_10min ? ` <b>+${n(a.new_10min)}</b>` : "") + (a.state === "stalled" || a.state === "waiting" ? ` <i>${e(a.why)}</i>` : "") + "</span>").join("");
    const on = p.master === "running";
    bar.innerHTML = `<span class="hb-st ${cls}">${e(LABEL[p.overall] || p.overall)}</span>` +
      (p.overall === "error" ? "" :
        `<span><b>${n(p.facts_per_min)}</b> <span class="hb-mut">new facts/min</span></span>` +
        `<span><b>${n(p.facts_10min)}</b> <span class="hb-mut">in 10 min · ${n(p.tasks_10min)} tasks</span></span>` +
        `<span class="hb-mut">last new fact ${ago(p.last_new_s)} · ${n(p.facts)} facts in the Commons</span>` +
        `<span class="hb-apps">${apps}</span>` +
        `<button class="btn ${on ? "secondary" : ""} hb-btn" data-hb="${on ? "stop" : "start"}">${on ? "Stop all harvesting" : "Start all harvesting"}</button>`) +
      `<span class="hb-msg hb-mut"></span>`;
    const b = bar.querySelector("[data-hb]");
    if (b) b.onclick = () => act(b.dataset.hb);
  }

  async function tick() {
    try { render(await (await fetch("/api/panel/pulse")).json()); }
    catch (err) { render({ overall: "error" }); }
  }
  tick();
  setInterval(tick, 5000);
})();
