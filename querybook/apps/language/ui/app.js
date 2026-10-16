"use strict";
let LANGS = [], NATIVE = "en", LANG = "es", MODE = "cards", SESSION = null, QUEUE = [], POS = 0, STATS = { right: 0, wrong: 0 };
const fmt = n => Number(n || 0).toLocaleString();
const stat = (v, k) => '<div class="stat"><div class="v">' + esc(v) + '</div><div class="k">' + esc(k) + "</div></div>";
const langName = code => (LANGS.find(l => l.code === code) || {}).name || code;
const SPEECH = { en: "en-US", es: "es-ES", fr: "fr-FR", de: "de-DE", it: "it-IT", pt: "pt-PT", nl: "nl-NL", sv: "sv-SE", da: "da-DK", no: "nb-NO",
  fi: "fi-FI", pl: "pl-PL", cs: "cs-CZ", el: "el-GR", ro: "ro-RO", hu: "hu-HU", ca: "ca-ES" };

// ---------------------------------------------------------------- speech
function voiceFor(code) {
  if (!("speechSynthesis" in window)) return null;
  const vs = speechSynthesis.getVoices();
  const want = SPEECH[code] || code;
  return vs.find(v => v.lang === want) || vs.find(v => v.lang && v.lang.replace("_", "-").toLowerCase().startsWith(code + "-")) ||
    vs.find(v => v.lang && v.lang.toLowerCase().startsWith(code)) || null;
}
async function say(text, code) {
  const v = voiceFor(code);
  if (v) {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.voice = v; u.lang = v.lang; u.rate = 0.9;
    speechSynthesis.speak(u);
    return;
  }
  const res = await fetch("/api/speak?" + new URLSearchParams({ text, lang: code }));
  if (!res.ok) {
    let msg = "No voice for " + langName(code) + " on this computer.";
    try { msg = (await res.json()).error || msg; } catch (e) { /* ignore */ }
    toast(msg, true);
    return;
  }
  const url = URL.createObjectURL(await res.blob());
  const a = new Audio(url);
  a.onended = () => URL.revokeObjectURL(url);
  a.play();
}
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => { /* voices now available */ };
const speakBtn = (text, code) => '<button class="btn quiet speakbtn" data-say="' + esc(text) + '" data-code="' + esc(code) + '" title="Listen" aria-label="Listen to ' + esc(text) + '">🔊</button>';
function wireSay(root) { $$("[data-say]", root).forEach(b => b.onclick = () => say(b.dataset.say, b.dataset.code)); }
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

// ---------------------------------------------------------------- languages
async function loadLangs() {
  const r = await api("/api/languages");
  LANGS = r.languages; NATIVE = r.native;
  try { const s = localStorage.getItem("qb-lang"); if (s && LANGS.find(l => l.code === s)) LANG = s; } catch (e) { /* ignore */ }
  if (LANG === NATIVE) LANG = (LANGS.find(l => !l.is_native) || {}).code;
  $("#native").innerHTML = LANGS.map(l => '<option value="' + l.code + '"' + (l.is_native ? " selected" : "") + ">" + esc(l.name) + " — " + esc(l.native) + "</option>").join("");
  $("#langs").innerHTML = LANGS.filter(l => !l.is_native).map(l => '<button class="lang" data-lang="' + l.code + '" aria-pressed="' + (l.code === LANG) + '"><div class="n">' + esc(l.name) +
    ' <span class="muted small">' + esc(l.native) + '</span></div><div class="s">' + fmt(l.learning) + " learning · " + fmt(l.mastered) + " mastered · <b>" + fmt(l.due) + "</b> due</div></button>").join("");
  $$("[data-lang]").forEach(b => b.onclick = () => { LANG = b.dataset.lang; try { localStorage.setItem("qb-lang", LANG); } catch (e) { /* ignore */ }
    $$("[data-lang]").forEach(x => x.setAttribute("aria-pressed", x.dataset.lang === LANG)); refreshTab(); });
}

// ---------------------------------------------------------------- learn
async function loadSetup() {
  const s = await api("/api/settings?lang=" + LANG);
  const n = langName(LANG);
  const nn = langName(NATIVE);
  $("#dir").innerHTML = '<option value="from_native">' + esc(nn) + " → " + esc(n) + '</option><option value="to_native">' + esc(n) + " → " + esc(nn) + "</option>";
  $("#dir").value = s.direction;
  $("#npd").value = s.new_per_day;
  $$("#modes [data-mode]").forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === MODE));
  const l = LANGS.find(x => x.code === LANG);
  $("#sinfo").innerHTML = fmt(l.due) + " word(s) due for review · up to " + s.new_per_day + " new word(s) a day · " + fmt(l.words_available) + " words in the " + esc(n) + " list" +
    (MODE === "speak" ? '<div class="note" style="margin-top:8px">' + (Recognition ? "Speaking uses your browser's speech recognition. In Chrome and Edge the recording is processed online by the browser maker." :
      "This browser cannot recognise speech. Use Chrome, Edge or Safari for speaking practice.") + "</div>" : "");
  $("#run").style.display = "none";
  $("#setup").style.display = "block";
}

async function start() {
  if (MODE === "speak" && !Recognition) { toast("This browser cannot recognise speech. Use Chrome, Edge or Safari.", true); return; }
  SESSION = await api("/api/session?" + new URLSearchParams({ lang: LANG, mode: MODE, direction: $("#dir").value }));
  QUEUE = SESSION.items.slice(); POS = 0; STATS = { right: 0, wrong: 0 };
  if (!QUEUE.length) {
    $("#run").style.display = "block";
    $("#run").innerHTML = '<h2>All done for today</h2><p>No words are due' + (SESSION.settings.new_per_day ? " and today's new words are learned." : ".") +
      ' Come back tomorrow, raise <b>New words a day</b>, or add your own words.</p>';
    return;
  }
  $("#setup").style.display = "none";
  $("#run").style.display = "block";
  show();
}

function header() {
  return '<div class="row small muted" style="justify-content:space-between"><span>' + (POS + 1) + " of " + QUEUE.length + " · " + esc(SESSION.language) +
    "</span><span>✔ " + STATS.right + " · ✘ " + STATS.wrong + '</span><button class="btn quiet" id="quit" style="padding:4px 10px">Finish</button></div>';
}

function show() {
  if (POS >= QUEUE.length) return finish();
  const it = QUEUE[POS], code = LANG, foreignCode = code;
  const toEn = it.direction === "to_native";
  const promptCode = toEn ? foreignCode : NATIVE;
  let h = header() + (it.new ? '<div class="hint small"><span class="badge warn">new word</span></div>' : "");
  if (MODE === "listen") {
    h += '<div class="prompt">' + speakBtn(it.foreign, code) + '</div><div class="hint">Write the ' + esc(SESSION.language) + " word you hear</div>" +
      '<input class="bigin" id="ans" type="text" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="Your answer"><div class="row" style="justify-content:center;margin-top:10px"><button class="btn" id="check">Check</button><button class="btn quiet" id="skip">I don\'t know</button></div>';
  } else if (MODE === "speak") {
    h += '<div class="prompt">' + esc(it.foreign) + " " + speakBtn(it.foreign, code) + '</div><div class="hint">' + esc(it.en) + " — listen, then say it</div>" +
      '<button class="btn mic" id="mic" aria-label="Start speaking">🎤</button><div class="hint small" id="heard"></div><div class="row" style="justify-content:center"><button class="btn quiet" id="skip">Skip</button></div>';
  } else {
    h += '<div class="prompt">' + esc(it.prompt) + " " + speakBtn(it.prompt, promptCode) + "</div>" +
      '<div class="hint">' + (toEn ? "What does this mean in " + esc(SESSION.native_name) + "?" : "How do you say this in " + esc(SESSION.language) + "?") + "</div>" +
      (!toEn && it.definition && NATIVE === "en" ? '<div class="hint small" style="margin-top:4px">' + esc(it.definition.slice(0, 160)) + (it.definition.length > 160 ? "…" : "") + "</div>" : "");
    if (MODE === "cards") {
      h += '<div class="row" style="justify-content:center;margin-top:16px"><button class="btn" id="reveal">Show the answer</button></div><div id="back"></div>';
    } else if (MODE === "choice") {
      h += '<div class="choices">' + it.choices.map(c => '<button class="btn quiet" data-choice="' + esc(c) + '">' + esc(c) + "</button>").join("") + "</div>";
    } else {
      h += '<input class="bigin" id="ans" type="text" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="Your answer" style="margin-top:14px">' +
        '<div class="row" style="justify-content:center;margin-top:10px"><button class="btn" id="check">Check</button><button class="btn quiet" id="skip">I don\'t know</button></div>';
    }
  }
  h += '<div id="fb"></div>';
  $("#run").innerHTML = h;
  wireSay($("#run"));
  $("#quit").onclick = finish;
  if (MODE === "listen") setTimeout(() => say(it.foreign, code), 250);
  if ($("#ans")) { $("#ans").focus(); onEnter($("#ans"), () => submit({ given: $("#ans").value })); }
  if ($("#check")) $("#check").onclick = () => submit({ given: $("#ans").value });
  if ($("#skip")) $("#skip").onclick = () => submit({ given: "", knew: false });
  if ($("#reveal")) $("#reveal").onclick = () => {
    $("#back").innerHTML = '<div class="answer" style="text-align:center">' + esc(it.accepted.join(", ")) + " " + speakBtn(it.accepted[0], toEn ? NATIVE : code) + "</div>" +
      '<div class="row" style="justify-content:center"><button class="btn" id="knew">I knew it</button><button class="btn secondary" id="didnt">I didn\'t</button></div>';
    wireSay($("#back"));
    $("#reveal").style.display = "none";
    $("#knew").onclick = () => submit({ knew: true });
    $("#didnt").onclick = () => submit({ knew: false });
  };
  $$("[data-choice]").forEach(b => b.onclick = () => submit({ given: b.dataset.choice }, b));
  if ($("#mic")) $("#mic").onclick = () => listen(it);
}

function listen(it) {
  const r = new Recognition();
  r.lang = SPEECH[LANG]; r.interimResults = false; r.maxAlternatives = 3;
  const mic = $("#mic");
  mic.classList.add("on"); $("#heard").textContent = "Listening…";
  r.onresult = e => {
    const alts = Array.from(e.results[0]).map(a => a.transcript);
    $("#heard").textContent = "Heard: “" + alts[0] + "”";
    submit({ given: alts[0] });
  };
  r.onerror = e => { mic.classList.remove("on"); $("#heard").textContent = e.error === "not-allowed" ? "Microphone permission was refused." : "Didn't catch that — try again (" + e.error + ")."; };
  r.onend = () => mic.classList.remove("on");
  r.start();
}

async function submit(body, btn) {
  const it = QUEUE[POS];
  $$("#run button:not(#quit)").forEach(b => { if (!b.dataset.say) b.disabled = true; });
  const r = await api("/api/answer", Object.assign({ lang: LANG, en: it.en, mode: MODE, direction: it.direction }, body));
  if (r.correct) STATS.right++; else STATS.wrong++;
  if (MODE === "choice") $$("[data-choice]").forEach(b => {
    if (r.all_answers.map(x => x.toLowerCase()).includes(b.dataset.choice.toLowerCase())) b.classList.add("right");
    else if (b === btn) b.classList.add("wrongpick");
  });
  const cls = r.result === "correct" ? "good" : r.result === "accent" || r.result === "close" ? "warn" : r.correct ? "good" : "bad";
  const msg = r.result === "correct" ? "Right!" : r.result === "accent" ? "Right — but check the accents: " : r.result === "close" ? "Nearly — one letter off. It's " :
    MODE === "speak" ? (r.correct ? "Good — " + r.similarity + "% match." : "Not quite (" + (r.similarity || 0) + "% match). It's ") : "It's ";
  const showAns = r.result !== "correct" || MODE === "speak";
  $("#fb").innerHTML = '<div class="feedback ' + cls + '">' + esc(msg) + (showAns && !(MODE === "speak" && r.correct) ? "<b>" + esc(r.all_answers.join(", ")) + "</b>" : "") +
    (it.direction === "from_native" || MODE === "listen" || MODE === "speak" ? " " + speakBtn(it.foreign, LANG) : "") +
    (LANG === "en" && it.definition ? '<div class="small" style="margin-top:4px">' + esc(it.foreign) + ": " + esc(it.definition) + "</div>" : "") +
    '<div class="small" style="margin-top:4px">' + (r.correct ? "Next review: " + esc(r.next_review) : "You'll see it again in this session and today.") + "</div></div>" +
    '<div class="row" style="justify-content:center;margin-top:12px"><button class="btn" id="next">Next</button></div>';
  wireSay($("#fb"));
  if (!r.correct && QUEUE.filter(x => x.en === it.en).length < 2) QUEUE.push(Object.assign({}, it, { new: false }));
  $("#next").onclick = () => { POS++; show(); };
  $("#next").focus();
  if (r.correct && MODE === "choice") setTimeout(() => { if ($("#next")) $("#next").click(); }, 900);
}

async function finish() {
  const total = STATS.right + STATS.wrong;
  $("#run").innerHTML = "<h2>Session finished</h2><p>" + STATS.right + " right, " + STATS.wrong + " to practise" + (total ? " (" + Math.round(100 * STATS.right / total) + "%)" : "") + ".</p>" +
    '<div class="row"><button class="btn" id="again">Practise again</button><button class="btn quiet" id="back2">Change mode</button></div>';
  $("#again").onclick = start;
  $("#back2").onclick = loadSetup;
  await loadLangs();
}

// ---------------------------------------------------------------- words, dictionary, mine
async function loadWords() {
  const r = await api("/api/words?" + new URLSearchParams({ lang: LANG, which: $("#wwhich").value, q: $("#wq").value, limit: 200 }));
  const boxName = b => b === null || b === undefined ? "" : b >= 6 ? "mastered" : "box " + b;
  $("#wlist").innerHTML = '<p class="small muted">' + fmt(r.total) + " word(s)" + (r.total > 200 ? " — first 200 shown" : "") + "</p>" +
    '<table class="t"><tr><th>' + esc(langName(LANG)) + "</th><th>" + esc(langName(NATIVE)) + "</th><th>Box</th><th>Next review</th><th></th></tr>" + r.words.map(w =>
      "<tr><td>" + esc(w.foreign) + " " + (w.foreign ? speakBtn(w.foreign.split(",")[0], LANG) : "") + "</td><td>" + esc(w.meaning) + " " + (w.meaning ? speakBtn(w.meaning.split(",")[0], NATIVE) : "") + "</td><td>" + esc(boxName(w.box)) +
      "</td><td>" + esc(w.due || "") + "</td><td>" + (w.box !== null && w.box !== undefined ? '<button class="btn quiet" data-reset="' + esc(w.word) + '" style="padding:2px 8px;font-size:13px">Start over</button>' : "") + "</td></tr>").join("") + "</table>";
  wireSay($("#wlist"));
  $$("[data-reset]").forEach(b => b.onclick = async () => { if (confirm("Start this word over from the beginning?")) { await api("/api/words/reset", { lang: LANG, word: b.dataset.reset }); loadWords(); } });
}

async function lookup() {
  const r = await api("/api/lookup?q=" + encodeURIComponent($("#dq").value));
  let h = "";
  if (r.english) {
    h += '<h2>' + esc(r.english.word) + " " + speakBtn(r.english.word, "en") + "</h2>" +
      (r.english.definition ? '<p>' + esc(r.english.definition) + '</p><p class="small muted">Webster\'s Unabridged Dictionary (1913), public domain — older wording.</p>' : "") +
      '<table class="t"><tr><th>Language</th><th>Translation</th></tr>' + Object.entries(r.english.translations).map(([code, tr]) =>
        "<tr><td>" + esc(langName(code)) + "</td><td>" + (tr.length ? tr.map(t => esc(t) + " " + speakBtn(t, code)).join(" · ") : '<span class="muted">—</span>') + "</td></tr>").join("") + "</table>";
  }
  if (r.foreign.length) {
    h += "<h3>As a word in another language</h3><ul class=\"list-plain\">" + r.foreign.map(f => "<li><b>" + esc(f.word) + "</b> " + speakBtn(f.word, f.lang) + " (" + esc(f.language) + ") = " + esc(f.english.join(", ")) + "</li>").join("") + "</ul>";
  }
  $("#dout").innerHTML = h || '<p class="muted">Not in the bundled word lists. You can add it under <b>My words</b>.</p>';
  wireSay($("#dout"));
}

async function loadMine() {
  const r = await api("/api/custom?lang=" + LANG);
  $("#me").placeholder = "Word in " + langName(LANG); $("#mf").placeholder = "Meaning in " + langName(NATIVE);
  $("#mlist").innerHTML = r.words.length ? '<table class="t"><tr><th>' + esc(langName(LANG)) + "</th><th>" + esc(langName(NATIVE)) + "</th><th>Note</th><th></th></tr>" + r.words.map(w =>
    "<tr><td>" + esc(w.target_word) + " " + speakBtn(w.target_word, LANG) + "</td><td>" + esc(w.native_word) + '</td><td class="small">' + esc(w.note || "") +
    '</td><td><button class="btn quiet" data-del="' + w.id + '" style="padding:2px 8px;font-size:13px">Remove</button></td></tr>').join("") + "</table>" : '<p class="muted">No words of your own yet for ' + esc(langName(LANG)) + ".</p>";
  wireSay($("#mlist"));
  $$("[data-del]").forEach(b => b.onclick = async () => { await api("/api/custom/delete", { id: Number(b.dataset.del) }); loadMine(); });
}

// ---------------------------------------------------------------- progress, data
async function loadProgress() {
  const p = await api("/api/progress?lang=" + LANG), l = LANGS.find(x => x.code === LANG);
  $("#pstats").innerHTML = "<h2>" + esc(langName(LANG)) + '</h2><div class="stats">' + stat(fmt(l.learning), "words learning") + stat(fmt(l.mastered), "mastered") + stat(fmt(l.due), "due today") +
    stat(p.streak + " day" + (p.streak === 1 ? "" : "s"), "streak") + stat(p.week_accuracy === null ? "—" : p.week_accuracy + "%", "right this week (" + p.week_reviews + " answers)") + "</div>";
  const max = Math.max(1, ...p.series.map(d => d.reviews));
  $("#pchart").innerHTML = '<div class="bars">' + p.series.map(d => '<div title="' + esc(d.day) + ": " + d.reviews + " answers, " + d.correct + ' right" style="height:' + Math.round(100 * d.reviews / max) + '%"></div>').join("") +
    '</div><div class="barlabels"><span>' + esc(p.series[0].day) + "</span><span>today</span></div>";
  $("#pboxes").innerHTML = '<table class="t"><tr><th>Box</th><th>Seen again after</th><th>Words</th></tr>' + p.boxes.map((n, b) =>
    "<tr><td>" + (b === 0 ? "new / missed" : "box " + b) + "</td><td>" + (b === 0 ? "same day" : p.intervals[b] + " day" + (p.intervals[b] === 1 ? "" : "s")) + "</td><td>" + fmt(n) + "</td></tr>").join("") + "</table>";
  $("#phard").innerHTML = p.hardest.length ? '<table class="t"><tr><th>' + esc(langName(LANG)) + "</th><th>" + esc(langName(NATIVE)) + "</th><th>Right</th><th>Missed</th></tr>" + p.hardest.map(h =>
    "<tr><td>" + esc(h.foreign) + " " + speakBtn(h.foreign, LANG) + "</td><td>" + esc(h.meaning || "") + "</td><td>" + h.correct + "</td><td>" + h.wrong + "</td></tr>").join("") + "</table>" : '<p class="muted">No missed words yet.</p>';
  wireSay($("#phard"));
}

async function loadData() {
  const s = await api("/api/status"), st = s.store;
  $("#dstatus").innerHTML = '<div class="stats">' + stat(fmt(s.cards), "words in your lessons") + stat(fmt(s.reviews), "answers recorded") + stat(st.backups, "backups kept") +
    stat(s.speech.espeak ? "yes" : "no", "offline voice (espeak-ng)") + "</div>" +
    '<p class="small">Database: <span class="mono">' + esc(st.database) + "</span> (" + Math.round(st.bytes / 1024) + " KB)</p>" +
    (st.read_only ? '<div class="note bad">The database failed its check (' + esc(st.damage) + '). Nothing will be written. Close the app and run <span class="mono">python app.py restore</span>.</div>'
      : '<div class="note good">The database passed its check when the application started.</div>');
  const b = await api("/api/backups");
  $("#blist").innerHTML = '<p class="small muted">Folder: <span class="mono">' + esc(b.folder) + '</span></p><ul class="list-plain small">' + b.backups.map(x => '<li class="mono">' + esc(x.name) + " · " + x.kb + " KB</li>").join("") + "</ul>";
  const o = await api("/api/old-words");
  $("#oldwords").innerHTML = o.total ? "<p class=\"small\">" + fmt(o.total) + " words recorded from the old QueryBook. Most seen: " + o.top.slice(0, 30).map(w => esc(w.word)).join(", ") + "</p>" +
    '<button class="btn quiet" id="oldadd">Add 20 of these to my ' + esc(langName(LANG)) + " lessons</button>" : "";
  if ($("#oldadd")) $("#oldadd").onclick = async () => { const r = await api("/api/old-words/add", { lang: LANG, limit: 20 }); toast(r.added + " word(s) added to today's lessons."); loadLangs(); };
  pollJob($("#ijob"));
}

let CURRENT = "learn";
function refreshTab() {
  ({ learn: loadSetup, words: loadWords, dict: () => {}, mine: loadMine, progress: loadProgress, data: loadData, diag: () => renderDiagnostics($("#diag")), help: () => {} })[CURRENT]();
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadLangs();
  setupTabs(id => { CURRENT = id; refreshTab(); });
  $$("#modes [data-mode]").forEach(b => b.onclick = () => { MODE = b.dataset.mode; loadSetup(); });
  $("#dir").onchange = () => api("/api/settings", { lang: LANG, direction: $("#dir").value });
  $("#npd").onchange = async () => { await api("/api/settings", { lang: LANG, new_per_day: Number($("#npd").value) }); loadSetup(); };
  $("#start").onclick = start;
  $("#native").onchange = async () => { await api("/api/native", { native: $("#native").value }); await loadLangs(); refreshTab(); };
  $("#wgo").onclick = loadWords; $("#wwhich").onchange = loadWords; onEnter($("#wq"), loadWords);
  $("#dgo").onclick = lookup; onEnter($("#dq"), lookup);
  $("#madd").onclick = async () => { await api("/api/custom/add", { lang: LANG, target_word: $("#me").value, native_word: $("#mf").value, note: $("#mn").value });
    $("#me").value = $("#mf").value = $("#mn").value = ""; loadMine(); };
  api("/api/old-store-hint").then(h => { if (h.folder && !$("#oldf").value) $("#oldf").value = h.folder; });
  $("#oldcheck").onclick = async () => { const r = await api("/api/old-store?folder=" + encodeURIComponent($("#oldf").value));
    $("#oldinfo").innerHTML = 'Found <span class="mono">' + esc(r.folder) + "</span> — language model file(s): " + (r.language_models.length ? esc(r.language_models.join(", ")) : "none") + "."; };
  $("#oldgo").onclick = async () => { await api("/api/import-old", { folder: $("#oldf").value }); pollJob($("#ijob"), () => loadData()); };
  $("#bnow").onclick = async () => { const r = await api("/api/backup", {}); toast("Backup written: " + r.backup); loadData(); };
  const s = await api("/api/status");
  $("#srcs").innerHTML = "Translations: " + esc(s.sources.bilingual) + ".<br>Definitions and word order: " + esc(s.sources.dictionary) + ".";
  refreshFooter();
});
