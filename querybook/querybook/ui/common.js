/* Shared helpers for every QueryBook UI. No framework, no network beyond this local server. */
const qb = (() => {
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid instanceof Node ? kid : String(kid));
    return n;
  };
  async function api(path, opts = {}) {
    const init = { headers: { "Content-Type": "application/json" }, ...opts };
    if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
    const res = await fetch(path, init);
    const data = await res.json().catch(() => ({ ok: false, error: { message: res.statusText } }));
    return data;
  }
  /* Wrap whole-word matches of `term` in <mark>, safely (no innerHTML). */
  function highlight(text, term) {
    const frag = document.createDocumentFragment();
    if (!term) { frag.append(text); return frag; }
    const re = new RegExp("\\b(" + term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")\\b", "gi");
    let last = 0, m;
    while ((m = re.exec(text))) { frag.append(text.slice(last, m.index), el("mark", {}, m[0])); last = m.index + m[0].length; }
    frag.append(text.slice(last));
    return frag;
  }
  async function header(active) {
    const info = await api("/api/apps");
    const nav = el("nav");
    if (info.mode === "hub") nav.append(el("a", { href: "/", class: active === "hub" ? "on" : "" }, "Hub"));
    for (const a of info.apps) {
      nav.append(el("a", { href: info.mode === "hub" ? "/" + a.key : "/", class: a.key === active ? "on" : "" }, a.title));
    }
    const live = el("span", { class: "live", title: "Real-time change feed" }, el("span", { class: "dot" }), el("span", {}, "connecting…"));
    document.body.prepend(el("header", { class: "top" }, el("a", { class: "brand", href: "/" }, "QueryBook"), nav, live));
    return { info, live };
  }
  /* Subscribe to the shared database's change feed (Server-Sent Events). */
  function stream(coll, onChange, liveEl) {
    const url = "/api/stream" + (coll ? "?coll=" + encodeURIComponent(coll) : "");
    const es = new EventSource(url);
    const label = liveEl && liveEl.querySelector("span:last-child");
    es.addEventListener("hello", () => { if (liveEl) { liveEl.classList.add("on"); label.textContent = "live"; } });
    es.addEventListener("change", (e) => onChange(JSON.parse(e.data)));
    es.onerror = () => { if (liveEl) { liveEl.classList.remove("on"); label.textContent = "reconnecting…"; } };
    return es;
  }
  function fqlList(container, queries) {
    container.replaceChildren(...(queries || []).map((q) => el("pre", { class: "fql" }, q)));
    if (!queries || !queries.length) container.append(el("p", { class: "muted small" }, "No queries yet."));
  }
  function sourceList(container, sources) {
    container.replaceChildren();
    if (!sources || !sources.length) { container.append(el("p", { class: "muted small" }, "No sources yet.")); return; }
    container.append(el("ul", { class: "sources" }, sources.map((s) =>
      el("li", {}, el("span", { class: "coll" }, s.coll || ""), s.url ? el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title || s.url) : s.title || "(untitled)",
         s.source ? el("div", { class: "muted small" }, s.source) : null))));
  }
  /* Standard wiring for a domain page: form, example chips, ?q= in the URL, live banner. */
  async function domainPage({ key, collection, render }) {
    const { info, live } = await header(key);
    const app = info.apps.find((a) => a.key === key) || {};
    document.getElementById("tagline").textContent = app.tagline || "";
    const form = document.getElementById("ask"), input = form.querySelector("input");
    input.placeholder = app.placeholder || "";
    const chips = document.getElementById("examples");
    (app.examples || []).forEach((ex) => chips.append(el("button", { class: "chip", type: "button", onclick: () => { input.value = ex; run(); } }, ex)));
    const banner = document.getElementById("banner");
    let pending = 0, lastQuery = "";
    async function run() {
      const q = input.value.trim();
      if (!q) return;
      lastQuery = q; pending = 0; banner.classList.remove("show");
      history.replaceState(null, "", "?q=" + encodeURIComponent(q));
      const btn = form.querySelector("button"); btn.disabled = true;
      try {
        const res = await api(`/api/${key}/query?q=${encodeURIComponent(q)}`);
        render(res);
        fqlList(document.getElementById("fql"), res.fql);
        sourceList(document.getElementById("sources"), res.sources);
        document.getElementById("timing").textContent = res.took_ms != null ? `${res.took_ms} ms` : "";
      } finally { btn.disabled = false; }
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    stream(collection, (ev) => {
      if (!lastQuery || ev.type === "update") return;
      pending += 1;
      banner.replaceChildren(el("span", {}, `${pending} new ${collection} document${pending > 1 ? "s" : ""} arrived since this answer.`),
        el("button", { type: "button", onclick: run }, "Refresh answer"));
      banner.classList.add("show");
    }, live);
    const q0 = new URLSearchParams(location.search).get("q");
    if (q0) { input.value = q0; run(); }
    return { run, input };
  }
  return { el, api, highlight, header, stream, fqlList, sourceList, domainPage };
})();
