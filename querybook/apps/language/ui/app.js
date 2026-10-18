"use strict";
// QueryBook Language Builder — one automated build of every language, shown step by step.
const fmt = n => Number(n || 0).toLocaleString();
const stat = (v, k) => '<div class="stat"><div class="v">' + esc(v) + '</div><div class="k">' + esc(k) + "</div></div>";
const NAMES = { en: "English", es: "Spanish", fr: "French", de: "German", it: "Italian", pt: "Portuguese", nl: "Dutch", sv: "Swedish", da: "Danish",
  no: "Norwegian", fi: "Finnish", pl: "Polish", cs: "Czech", el: "Greek", ro: "Romanian", hu: "Hungarian", ca: "Catalan" };
const SPEECH = { en: "en-US", es: "es-ES", fr: "fr-FR", de: "de-DE", it: "it-IT", pt: "pt-PT", nl: "nl-NL", sv: "sv-SE", da: "da-DK", no: "nb-NO",
  fi: "fi-FI", pl: "pl-PL", cs: "cs-CZ", el: "el-GR", ro: "ro-RO", hu: "hu-HU", ca: "ca-ES" };
const secs = s => s === null || s === undefined ? "" : s < 60 ? Number(s).toFixed(2) + " s" : Math.floor(s / 60) + " min " + (s % 60).toFixed(2) + " s";
const meter = (frac, pass, mark) => '<div class="meter' + (pass ? " pass" : "") + '"><i style="width:' + Math.max(0, Math.min(100, 100 * frac)).toFixed(1) + '%"></i>' +
  (mark !== undefined ? '<b style="left:' + Math.min(100, 100 * mark).toFixed(1) + '%"></b>' : "") + "</div>";

// ---------------------------------------------------------------- speech (listen buttons in Look up)
function voiceFor(code) {
  if (!("speechSynthesis" in window)) return null;
  const vs = speechSynthesis.getVoices(), want = SPEECH[code] || code;
  return vs.find(v => v.lang === want) || vs.find(v => v.lang && v.lang.toLowerCase().startsWith(code)) || null;
}
async function say(text, code) {
  // espeak-ng (bundled) is the default voice; the browser's own voice is only a fallback
  const res = await fetch("/api/speak?" + new URLSearchParams({ text, lang: code }));
  if (!res.ok) {
    const v = voiceFor(code);
    if (v) { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.voice = v; u.lang = v.lang; u.rate = 0.9; speechSynthesis.speak(u); return; }
    let m = "No voice for " + (NAMES[code] || code) + " on this computer."; try { m = (await res.json()).error || m; } catch (e) { /* ignore */ } toast(m, true); return;
  }
  const url = URL.createObjectURL(await res.blob()), a = new Audio(url);
  a.onended = () => URL.revokeObjectURL(url); a.play();
}
const speakBtn = (text, code) => '<button class="btn quiet speakbtn" data-say="' + esc(text) + '" data-code="' + esc(code) + '" title="Listen" aria-label="Listen to ' + esc(text) + '">🔊</button>';
function wireSay(root) { $$("[data-say]", root).forEach(b => b.onclick = () => say(b.dataset.say, b.dataset.code)); }

// ---------------------------------------------------------------- the build
let POLL = null, LAST_B = 0;

const clock = iso => iso ? new Date(iso).toLocaleTimeString() : "";
const day = iso => iso ? new Date(iso).toLocaleString() : "";

function renderJob(j, b) {
  const isBuild = j.name === "Build all languages";
  const running = j.state === "running" && isBuild;
  const other = j.state === "running" && !isBuild;
  const N = b.stages.length, nDone = b.stages.filter(s => s.done).length, L = b.languages.length, nLang = b.languages.filter(l => l.built).length;
  const log = b.stage_log || [];
  const lastLog = log[log.length - 1];
  const complete = !!b.built_at && nLang === L && nDone === N;
  let kind, icon, head, sub, btn, frac;
  if (running) {
    frac = j.overall || 0;
    kind = "run"; icon = "⏳"; head = "BUILDING NOW — " + Math.floor(100 * frac) + "% done";
    sub = "Step " + (j.stage_no || 1) + " of " + N + ": <b>" + esc(j.stage || "starting") + "</b>. " +
      "<br>You don't need to do anything. The build continues as long as the program window stays open" + (j.overall_eta_s !== undefined ? " — about <b>" + secs(j.overall_eta_s) + "</b> to go." : ".");
    btn = "Building…";
  } else if (other) {
    frac = nDone / N; kind = "run"; icon = "⏳"; head = "BUSY — " + esc(j.name);
    sub = esc(j.message || "") + "<br>The language build can start when this finishes.";
    btn = "Build all languages";
  } else if (complete && !(isBuild && (j.state === "stopped" || j.state === "failed"))) {
    frac = 1; kind = "ok"; icon = "✅"; head = "READY — all " + L + " languages are built";
    const took = log.reduce((t, r) => t + (r.seconds || 0), 0);
    sub = "Finished " + esc(day(b.built_at)) + (took ? " in " + secs(took) : "") + ". <b>Nothing to do.</b> QueryBook can use these languages for queries.";
    btn = "Rebuild everything";
  } else if (isBuild && j.state === "failed") {
    frac = nDone / N; kind = "bad"; icon = "❌"; head = "BUILD FAILED" + (lastLog ? " at step " + lastLog.no + " (" + esc(lastLog.name) + ")" : "");
    sub = "Reason: " + esc(j.message) + "<br>Press <b>Try again</b>. If it fails again, see Diagnostics.";
    btn = "Try again";
  } else if (lastLog && !complete) {
    frac = nDone / N; kind = "warn"; icon = "⏸"; head = "STOPPED — " + nDone + " of " + N + " steps done";
    sub = "Stopped during step " + lastLog.no + " (" + esc(lastLog.name) + "). Press <b>Continue building</b> to finish — finished steps are kept.";
    btn = "Continue building";
  } else {
    frac = 0; kind = "warn"; icon = "⚪"; head = "NOT BUILT YET";
    sub = "Press <b>Build all languages</b>. Everything else is automatic (about 2 minutes).";
    btn = "Build all languages";
  }
  $("#banner").className = "banner " + kind;
  $("#bicon").textContent = icon;
  $("#bhead").innerHTML = head;
  $("#bsub").innerHTML = sub;
  $("#bgo").textContent = btn;
  $("#bgo").disabled = running || other;
  $("#bgo").dataset.again = complete ? "1" : "";
  $("#bstop").style.display = running ? "" : "none";

  $("#ballpct").textContent = Math.floor(100 * frac) + "%";
  $("#bbar").style.width = (100 * frac).toFixed(1) + "%";
  $("#bbar").parentElement.classList.toggle("pass", frac >= 1 && !running);
  $("#bbar").parentElement.classList.toggle("live", running);
  $("#nowbar").parentElement.classList.add("live");
  $("#bfacts").innerHTML = [
    "<span><b>" + (running ? (j.stage_no - 1) : nDone) + "</b> of " + N + " steps finished</span>",
    "<span><b>" + nLang + "</b> of " + L + " languages built</span>",
    "<span><b>" + fmt(b.facts) + "</b> facts learned</span>",
    running ? "<span>running for <b>" + secs(j.elapsed) + "</b></span>" : "",
    running && j.overall_eta_s !== undefined ? "<span>about <b>" + secs(j.overall_eta_s) + "</b> left</span>" : "",
  ].filter(Boolean).join("");

  $("#nowcard").style.display = running ? "" : "none";
  if (running) {
    const sp = j.total ? j.done / j.total : 0;
    $("#nowstep").innerHTML = "Step <b>" + j.stage_no + "</b> of " + N + ": <b>" + esc(j.stage) + "</b><br><span class=\"muted\">" + esc(j.message || "") + "</span>";
    $("#nowbar").style.width = (100 * sp).toFixed(1) + "%";
    $("#nowfacts").innerHTML = ["<span><b>" + Math.round(100 * sp) + "%</b> of this step</span>",
      j.total ? "<span><b>" + fmt(j.done) + "</b> of " + fmt(j.total) + "</span>" : "",
      j.rate ? "<span>speed <b>" + fmt(Math.round(j.rate)) + "</b> per second</span>" : "",
      j.eta_s !== undefined && j.eta_s !== null ? "<span>about <b>" + secs(j.eta_s) + "</b> left in this step</span>" : "",
      "<span><b>" + fmt(j.steps) + "</b> updates so far</span>"].filter(Boolean).join("");
  }

  const byNo = {}; log.forEach(r => byNo[r.no] = r);
  const curNo = running ? j.stage_no : null;
  $("#stepcount").textContent = "— " + (running ? (j.stage_no - 1) : nDone) + " of " + N + " finished";
  $("#bsteps").innerHTML = b.stages.map((s, i) => {
    const no = i + 1, r = byNo[no], now = no === curNo;
    const st = now ? '<span class="st run">⏳ Running</span>' : s.done ? '<span class="st ok">✔ Done</span>' :
      (r && r.state === "running" ? '<span class="st warn">⏸ Stopped</span>' : '<span class="st wait">Waiting</span>');
    const took = now ? secs(j.elapsed - log.filter(x => x.no < no).reduce((t, x) => t + (x.seconds || 0), 0)) + "…" : r && r.seconds !== undefined ? secs(r.seconds) : "";
    return '<tr class="' + (now ? "now" : "") + '"><td>' + no + "</td><td>" + esc(s.name) + "</td><td>" + st + '</td><td class="hide-s">' + esc(r ? clock(r.started) : "") +
      "</td><td>" + esc(took) + '</td><td class="hide-s muted">' + esc(now ? (j.message || "") : r ? r.detail : "") + "</td></tr>";
  }).join("");

  const curLang = curNo ? (curNo <= 4 ? "en" : (b.stages[curNo - 1].key || "").slice(5)) : null;
  $("#langcount").textContent = "— " + nLang + " of " + L + " built";
  $("#blangs").innerHTML = b.languages.map(l => {
    const isNow = l.code === curLang;
    let f = l.built ? 1 : l.of ? l.words / l.of : 0;
    if (l.code === "en" && !l.built) f = b.stages.slice(0, 4).filter(s => s.done).length / 4;
    if (isNow && j.total) f = l.code === "en" ? ((j.stage_no - 1) + j.done / j.total) / 4 : j.done / j.total;
    const st = l.built ? '<span class="st ok">✔ Built</span>' : isNow ? '<span class="st run">⏳ Building now</span>' : '<span class="st wait">Waiting</span>';
    return "<tr><td><b>" + esc(l.name) + "</b></td><td>" + st + '</td><td class="bar">' + meter(f, l.built) + '<span class="small muted">' + Math.round(100 * f) + "%</span></td><td>" + fmt(l.words) +
      (l.of ? '<span class="muted"> of ' + fmt(l.of) + "</span>" : "") + '</td><td class="hide-s">' + fmt(l.sounds) + '</td><td class="hide-s">' + fmt(l.links) + "</td></tr>";
  }).join("");

  const ev = [];
  if (b.build_started) ev.push([b.build_started, "Build started"]);
  log.forEach(r => {
    ev.push([r.started, "Step " + r.no + " started: " + r.name]);
    if (r.finished) ev.push([r.finished, "Step " + r.no + " finished: " + r.name + " — " + secs(r.seconds) + (r.detail ? " — " + r.detail : "")]);
  });
  if (running && j.message) ev.push([new Date().toISOString(), "Step " + j.stage_no + " working: " + j.message]);
  if (b.built_at && complete) ev.push([b.built_at, "Build finished — all " + L + " languages built"]);
  if (isBuild && j.state === "stopped") ev.push([j.ended, "Build stopped by request"]);
  if (isBuild && j.state === "failed") ev.push([j.ended, "Build FAILED: " + j.message]);
  ev.sort((x, y) => String(y[0]).localeCompare(String(x[0])));
  $("#blog").innerHTML = ev.length ? ev.slice(0, 80).map(e => "<li>" + esc(clock(e[0])) + " · " + esc(e[1]) + "</li>").join("") : '<li class="muted">Nothing built yet.</li>';
}

function renderGate(b) {
  const g = b.gate, m = b.metrics, h = b.history || [];
  const NAMES_G = { phonemic_completeness: "Sounds found (phonics)", lexical_stability: "Common words settled", cooccurrence_density: "Words that go together", pattern_saturation: "New patterns still appearing" };
  const rows = Object.entries(g.checks).map(([k, c]) => {
    const low = k === "pattern_saturation", scale = low ? 1 : Math.max(c.threshold * 1.25, c.value);
    return "<div><b>" + esc(NAMES_G[k]) + "</b></div>" + meter(c.value / scale, c.pass, c.threshold / scale) +
      "<div>" + c.value + (low ? " (needs below " : " (needs ") + c.threshold + ") " + (c.pass ? "✔" : "") + "</div>";
  }).join("");
  $("#bgate").innerHTML = '<p class="small">Gate <b>' + (g.opened ? "open" : "closed — " + g.progress + "% of the way") + "</b>" + (g.opened_at ? " since " + esc(g.opened_at) : "") +
    ". Meanings are only attached after it opens.</p>" + '<div class="gate">' + rows + "</div>" +
    '<div class="stats" style="margin-top:12px">' + stat(fmt(m.total_tokens), "words read") + stat(fmt(m.distinct_words), "different words") +
    stat(m.distinct_phonemes + " / " + m.phoneme_target, "sounds found") + stat(fmt(m.distinct_bigrams), "word pairs") + stat(fmt(m.ingests), "readings") + "</div>" +
    (h.length ? '<p class="small muted" style="margin:12px 0 0">Progress to the gate, reading by reading (green = open):</p><div class="spark">' + h.map(x => {
      const f = (Math.min(1, x.phon / .8) + Math.min(1, x.stab / .7) + Math.min(1, x.dens / 1.5) + (x.novel > 0 ? Math.min(1, .2 / x.novel) : 1)) / 4;
      return '<div class="' + (x.opened ? "open" : "") + '" style="height:' + (100 * f).toFixed(0) + '%" title="' + esc(x.t) + '"></div>'; }).join("") + "</div>" : "");
}

async function tickBuild() {
  const j = await api("/api/job");
  if (j.state !== "running" || Date.now() - LAST_B > 2500) return refreshBuild();
  const b = window._lastBuild; if (b) renderJob(j, b);
  POLL = setTimeout(tickBuild, 700);
}
async function refreshBuild() {   // full refresh; fast ticks in between only re-read the job
  clearTimeout(POLL);
  const [j, b] = await Promise.all([api("/api/job"), api("/api/build")]);
  window._lastBuild = b; LAST_B = Date.now();
  renderJob(j, b); renderGate(b);
  if (j.state === "running") POLL = setTimeout(tickBuild, 700);
}


// ---------------------------------------------------------------- verification (proof for third parties)
function curveSvg(curve) {
  if (!curve || !curve.length) return "";
  const W = 900, H = 200, P = 34, n = curve.length, maxW = Math.max(...curve.map(r => r.different_words)) || 1;
  const x = i => P + (W - 2 * P) * (n === 1 ? 0 : i / (n - 1));
  const line = (vals, max) => vals.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + (H - P - (H - 2 * P) * Math.min(1, v / max)).toFixed(1)).join(" ");
  const gate = curve.map(r => (Math.min(1, r.sounds_found / .8) + Math.min(1, r.words_settled / .7) + Math.min(1, r.pairs_per_word / 1.5) + (r.new_patterns > 0 ? Math.min(1, .2 / r.new_patterns) : 1)) / 4);
  return '<svg class="curve" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Learning curve">' +
    '<line x1="' + P + '" y1="' + (H - P) + '" x2="' + (W - P) + '" y2="' + (H - P) + '" stroke="currentColor" opacity=".3"/>' +
    '<path d="' + line(curve.map(r => r.different_words), maxW) + '" fill="none" stroke="var(--accent)" stroke-width="3"/>' +
    '<path d="' + line(gate, 1) + '" fill="none" stroke="var(--good)" stroke-width="3" stroke-dasharray="6 4"/>' +
    '<text x="' + P + '" y="' + (H - 10) + '" font-size="13" fill="currentColor">reading 1 (0 words before)</text>' +
    '<text x="' + (W - P) + '" y="' + (H - 10) + '" font-size="13" fill="currentColor" text-anchor="end">reading ' + n + " — gate " + esc(curve[n - 1].gate) + "</text>" +
    '<text x="' + P + '" y="16" font-size="13" fill="var(--accent)">— different words (0 → ' + fmt(maxW) + ')</text>' +
    '<text x="' + (P + 300) + '" y="16" font-size="13" fill="var(--good)">- - progress to the Transition Gate (0 → 100%)</text></svg>';
}

function renderVerification(rep) {
  if (!rep) {
    $("#vbanner").className = "banner warn"; $("#vicon").textContent = "🔍"; $("#vhead").textContent = "NOT VERIFIED YET";
    $("#vsub").innerHTML = "Press <b>Verify from scratch</b> (about 2 minutes). Nothing needs to be prepared.";
    $("#vresult").innerHTML = ""; return;
  }
  const ok = rep.verdict === "PASS", fp = rep.fingerprint || {};
  $("#vbanner").className = "banner " + (ok ? "ok" : "bad");
  $("#vicon").textContent = ok ? "✅" : "❌";
  $("#vhead").textContent = ok ? "VERIFIED — learned from scratch" : "VERIFICATION FAILED";
  $("#vsub").innerHTML = (ok ? "All " + rep.checks.length + " checks passed" : rep.checks.filter(c => !c.pass).length + " check(s) failed") +
    " · " + esc(new Date(rep.finished).toLocaleString()) + " · took " + secs(rep.seconds) + " · " + fmt(rep.all_reports) + " report(s) kept";
  const lc = rep.learning_curve || [], first = lc[0] || {}, last = lc[lc.length - 1] || {};
  $("#vresult").innerHTML =
    '<div class="card"><h2>Checks</h2><ul class="chk">' + rep.checks.map(c => '<li class="' + (c.pass ? "y" : "n") + '"><b>' + esc(c.check) + "</b>" +
      (c.detail ? '<div class="small muted">' + esc(c.detail) + "</div>" : "") + "</li>").join("") + "</ul></div>" +
    '<div class="card"><h2>Fingerprint of everything learned</h2><div class="fp mono" id="fpv">' + esc(fp.sha256 || "") + "</div>" +
      '<p class="small muted">SHA-256 over ' + fmt(fp.facts_in_fingerprint) + " learned facts and the Phase 1 model (timestamps left out; " + fmt(fp.espeak_facts_excluded) +
      " pronunciations from espeak-ng left out because they depend on its version).</p>" +
      '<div class="row"><button class="btn quiet" id="fpcopy">Copy fingerprint</button><a class="btn quiet" style="text-decoration:none;padding:9px 16px;border-radius:8px;border:1px solid var(--line)" href="/api/verify/report.txt" download>Download report (.txt)</a>' +
      '<a class="btn quiet" style="text-decoration:none;padding:9px 16px;border-radius:8px;border:1px solid var(--line)" href="/api/verify/report.json" download>Download full data (.json)</a></div></div>' +
    '<div class="card"><h2>Learning curve from zero (Phase 1)</h2><p class="small">Reading 1 started with an empty memory and found ' + fmt(first.different_words) + " different words and " + fmt(first.sounds) +
      " sounds; after reading " + fmt(last.reading) + " it knew " + fmt(last.different_words) + " words and " + fmt(last.sounds) + " sounds, and the gate was " + esc(last.gate || "") + ".</p>" + curveSvg(lc) +
      '<details><summary class="small">Every reading</summary><table class="t small"><tr><th>Reading</th><th>Words read</th><th>Different words</th><th>Sounds</th><th>Word pairs</th><th>Sounds found</th><th>Words settled</th><th>Pairs/word</th><th>New patterns</th><th>Gate</th></tr>' +
      lc.map(r => "<tr><td>" + r.reading + "</td><td>" + fmt(r.words_read) + "</td><td>" + fmt(r.different_words) + "</td><td>" + r.sounds + "</td><td>" + fmt(r.word_pairs) + "</td><td>" + r.sounds_found +
        "</td><td>" + r.words_settled + "</td><td>" + r.pairs_per_word + "</td><td>" + r.new_patterns + "</td><td>" + esc(r.gate) + "</td></tr>").join("") + "</table></details></div>" +
    '<div class="card"><h2>Inputs — everything the builder reads</h2><table class="t small"><tr><th>File</th><th>What it is</th><th>Bytes</th><th>SHA-256</th></tr>' +
      (rep.inputs || []).map(f => '<tr><td class="mono">' + esc(f.file) + "</td><td>" + esc(f.kind) + "</td><td>" + fmt(f.bytes) + '</td><td class="mono" style="word-break:break-all">' + esc(f.sha256) + "</td></tr>").join("") + "</table></div>" +
    '<div class="card"><h2>Code imports</h2><p class="small muted">Every module the builder\'s code uses. Anything outside the Python standard library would fail the check.</p><table class="t small"><tr><th>Module</th><th>Kind</th><th>Used in</th></tr>' +
      ((rep.imports || {}).modules || []).map(m => "<tr><td class=\"mono\">" + esc(m.module) + "</td><td>" + (m.allowed ? "" : "❌ ") + esc(m.kind) + "</td><td>" + esc(m.used_in.join(", ")) + "</td></tr>").join("") + "</table></div>";
  $("#fpcopy").onclick = () => { navigator.clipboard.writeText(fp.sha256).then(() => toast("Fingerprint copied.")); };
}

async function loadVerify() {
  const [j, r] = await Promise.all([api("/api/job"), api("/api/verify/last")]);
  const running = j.state === "running" && j.name === "Verify from scratch";
  $("#vgo").disabled = j.state === "running";
  $("#vjobcard").style.display = running ? "" : "none";
  renderVerification(r.report);
  if (running) {
    $("#vbanner").className = "banner run"; $("#vicon").textContent = "⏳";
    $("#vhead").textContent = "VERIFYING NOW — " + Math.floor(100 * (j.overall || 0)) + "%";
    $("#vsub").innerHTML = esc(j.stage || "") + "<br>You don't need to do anything.";
    const f = j.overall || 0;
    $("#vjob").innerHTML = '<div class="lbl"><span>' + esc(j.stage || "") + "</span><span>" + Math.floor(100 * f) + '%</span></div><div class="meter tall"><i style="width:' + (100 * f).toFixed(1) + '%"></i></div>' +
      '<div class="facts"><span>' + esc(j.message || "") + "</span><span>running for <b>" + secs(j.elapsed) + "</b></span>" +
      (j.overall_eta_s !== undefined ? "<span>about <b>" + secs(j.overall_eta_s) + "</b> left</span>" : "") + (j.rate ? "<span>speed <b>" + fmt(Math.round(j.rate)) + "</b>/s</span>" : "") + "</div>";
    clearTimeout(POLL); POLL = setTimeout(loadVerify, 1500);
  }
}

// ---------------------------------------------------------------- look up
async function lookup() {
  const w = $("#q").value.trim(); if (!w) return;
  const [r, c] = await Promise.all([api("/api/lookup?q=" + encodeURIComponent(w)), api("/api/lab/word?w=" + encodeURIComponent(w))]);
  let h = "";
  if (r.english) {
    h += "<h2>" + esc(r.english.word) + " " + speakBtn(r.english.word, "en") + "</h2>" +
      (r.english.definition ? "<p>" + esc(r.english.definition) + '</p><p class="small muted">Webster\'s Unabridged Dictionary (1913), public domain.</p>' : "") +
      '<table class="t"><tr><th>Language</th><th>Word</th></tr>' + Object.entries(r.english.translations).map(([code, tr]) =>
        "<tr><td>" + esc(NAMES[code] || code) + "</td><td>" + (tr.length ? tr.map(t => esc(t) + " " + speakBtn(t, code)).join(" · ") : '<span class="muted">—</span>') + "</td></tr>").join("") + "</table>";
  }
  if (r.foreign.length) h += "<h3>As a word in another language</h3><ul class=\"list-plain\">" + r.foreign.map(f => "<li><b>" + esc(f.word) + "</b> " + speakBtn(f.word, f.lang) + " (" + esc(f.language) + ") = " + esc(f.english.join(", ")) + "</li>").join("") + "</ul>";
  const p = c.pronunciation_now;
  h += "<h3>What the builder learned about “" + esc(c.word) + "”</h3><p class=\"small\">Seen " + fmt(c.seen_in_phase1) + " times while reading English" +
    (p && p.ipa ? " · sounds <span class=\"mono\">" + esc(p.ipa) + "</span>, " + p.syllables + " syllable(s), stress on syllable " + p.stress_syllable : "") + ".</p>" +
    (c.facts.length ? '<table class="t small"><tr><th>About</th><th>Learned</th><th>Value</th><th>Source</th></tr>' + c.facts.slice(0, 80).map(f =>
      "<tr><td>" + esc(f.subject) + "</td><td>" + esc(f.predicate.replace(/_/g, " ")) + "</td><td>" + esc(f.object) + '</td><td class="muted">' + esc(f.source) + "</td></tr>").join("") + "</table>"
      : '<p class="muted small">No learned facts for this word yet.</p>');
  $("#qout").innerHTML = h; wireSay($("#qout"));
}

// ---------------------------------------------------------------- data
async function loadData() {
  const s = await api("/api/status"), st = s.store;
  $("#dstatus").innerHTML = '<div class="stats">' + stat(st.backups, "backups kept") + stat(s.speech.espeak ? "yes" : "no", "espeak-ng installed") + stat(Math.round(st.bytes / 1024) + " KB", "database size") + "</div>" +
    '<p class="small">Database: <span class="mono">' + esc(st.database) + "</span></p>" +
    (st.read_only ? '<div class="note bad">The database failed its check (' + esc(st.damage) + '). Nothing will be written. Close the app and run <span class="mono">python app.py restore</span>.</div>'
      : '<div class="note good">The database passed its check when the application started.</div>');
  const b = await api("/api/backups");
  $("#blist").innerHTML = '<p class="small muted">Folder: <span class="mono">' + esc(b.folder) + '</span></p><ul class="list-plain small">' + b.backups.map(x => '<li class="mono">' + esc(x.name) + " · " + x.kb + " KB</li>").join("") + "</ul>";
  pollJob($("#ijob"));
}

let CURRENT = "build";
function refreshTab() {
  clearTimeout(POLL);
  ({ build: refreshBuild, speech: loadSpeech, verify: loadVerify, lookup: () => $("#q").focus(), data: loadData, diag: () => renderDiagnostics($("#diag")), help: () => {}, photoreal: () => { if (window.prInit) prInit(); } })[CURRENT]();
}

document.addEventListener("DOMContentLoaded", async () => {
  setupTabs(id => { CURRENT = id; refreshTab(); });
  $("#bgo").onclick = async () => {
    const again = !!$("#bgo").dataset.again;
    if (again && !confirm("All languages are already built. Rebuild everything from scratch? (A backup is taken first.)")) return;
    await api("/api/lab/run", again ? { fresh: true } : {}); refreshBuild();
  };
  $("#bstop").onclick = async () => { await api("/api/job/stop", {}); toast("Stopping after the current batch…"); };
  $("#labfeed").onclick = async () => { await api("/api/lab/feed", { text: $("#labtext").value, url: $("#laburl").value }); $("#labtext").value = ""; toast("Reading it — see the progress above."); refreshBuild(); };
  $("#vgo").onclick = async () => { await api("/api/verify", {}); loadVerify(); };
  $("#qgo").onclick = lookup; onEnter($("#q"), lookup);
  $("#bnow").onclick = async () => { const r = await api("/api/backup", {}); toast("Backup written: " + r.backup); loadData(); };
  $("#oldgo").onclick = async () => { await api("/api/import-old", { folder: $("#oldf").value }); pollJob($("#ijob"), () => loadData()); };
  $("#forget").onclick = async () => {
    if (!confirm("Forget everything that was built and build all languages again? A backup is taken first.")) return;
    await api("/api/lab/run", { fresh: true }); $$('nav.tabs button[data-tab="build"]')[0].click();
  };
  api("/api/old-store-hint").then(h => { if (h.folder && !$("#oldf").value) $("#oldf").value = h.folder; });
  api("/api/lab/sources").then(s => { $("#labsrc").innerHTML = s.sources.map(u => '<li><a href="#" data-u="' + esc(u.url) + '">' + esc(u.name) + "</a></li>").join("");
    $$("#labsrc [data-u]").forEach(a => a.onclick = e => { e.preventDefault(); $("#laburl").value = a.dataset.u; }); });
  api("/api/status").then(s => { $("#srcs").innerHTML = "Links between languages: " + esc(s.sources.bilingual) + ".<br>Meanings: " + esc(s.sources.dictionary) + "."; });
  refreshFooter();
});
