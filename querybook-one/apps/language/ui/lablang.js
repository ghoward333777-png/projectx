"use strict";
// QueryBook Language Lab — one screen, one text: pick a word or type/say a sentence, translate it, hear it in the
// language's voice while a face mouths it, then say it yourself and see which words were heard.
// Everything is offline except speech recognition (the browser's, or Google's when a key is set).

const LL = {
  langs: [], from: "en", to: "es", deckOff: 0, deckQ: "", engine: null, packsLoaded: new Set(),
  out: null, said: null, playing: null, raf: 0, rec: null, wordsTimer: 0,
};
const LL_FLAG = { en: "🇬🇧", es: "🇪🇸", fr: "🇫🇷", de: "🇩🇪", it: "🇮🇹", pt: "🇵🇹", nl: "🇳🇱", sv: "🇸🇪", da: "🇩🇰", no: "🇳🇴", fi: "🇫🇮",
  pl: "🇵🇱", cs: "🇨🇿", el: "🇬🇷", ro: "🇷🇴", hu: "🇭🇺", ca: "🏳️" };
const llName = c => (LL.langs.find(l => l.code === c) || {}).name || c;
const llSpeechTag = c => (LL.langs.find(l => l.code === c) || {}).speech || c;
const LL_RECOG = window.SpeechRecognition || window.webkitSpeechRecognition;

// ---------------------------------------------------------------- languages
async function llInit() {
  if (LL.ready) return;
  LL.ready = true;
  // every language QueryBook can translate and speak (Language 1.55): the Builder's 17 with word lists, the Translate
  // dictionary packs, and — with a Google or Gemini key — every language of the Translate registry
  let r;
  try { r = await api("/api/lablang/languages"); } catch (e) { r = await api("/api/languages"); }
  LL.cloud = !!r.cloud; LL.cloudBy = r.cloud_by || "";
  LL.langs = (r.languages || []).map(l => ({ code: l.code, name: l.name, native: l.native, speech: l.speech || SPEECH[l.code] || l.code,
    espeak: l.espeak, offline: l.offline !== false, words: l.words !== false }));
  if (!LL.langs.length) LL.langs = Object.keys(NAMES).map(c => ({ code: c, name: NAMES[c], speech: SPEECH[c] }));
  try { const s = JSON.parse(localStorage.getItem("qb-lab-pair") || "{}"); if (s.from) LL.from = s.from; if (s.to) LL.to = s.to; } catch (e) { /* first visit */ }
  if (LL.from === LL.to) LL.to = LL.from === "en" ? "es" : "en";
  const opts = LL.langs.map(l => '<option value="' + l.code + '">' + (LL_FLAG[l.code] || "") + " " + esc(l.name) + (l.native && l.native !== l.name ? " — " + esc(l.native) : "") + "</option>").join("");
  $("#ll-from").innerHTML = opts; $("#ll-to").innerHTML = opts;
  $("#ll-from").value = LL.from; $("#ll-to").value = LL.to;
  $("#ll-from").addEventListener("change", () => llSetPair($("#ll-from").value, LL.to));
  $("#ll-to").addEventListener("change", () => llSetPair(LL.from, $("#ll-to").value));
  $("#ll-swap").addEventListener("click", () => {
    const back = LL.out ? LL.out.text : "";
    llSetPair(LL.to, LL.from);
    if (back) { $("#ll-text").value = back; llTranslate(); }
  });
  $("#ll-wq").addEventListener("input", () => { clearTimeout(LL.wordsTimer); LL.wordsTimer = setTimeout(() => { LL.deckQ = $("#ll-wq").value.trim(); llDeck(true); }, 220); });
  $("#ll-wmore").addEventListener("click", () => llDeck(false));
  $("#ll-tr").addEventListener("click", llTranslate);
  $("#ll-text").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); llTranslate(); } });
  $("#ll-text").addEventListener("input", () => llMark(false));
  $("#ll-mic").addEventListener("click", () => llListen("source"));
  $("#ll-practice").addEventListener("click", () => llListen("practice"));
  $("#ll-play").addEventListener("click", () => llSay("target"));
  // the talking face: Gemini (HeyGen with the Speak page's voice when Gemini cannot) — Speech → Talking clips
  $("#ll-clip").addEventListener("click", () => {
    if (!LL.out || !LL.out.text) return;
    $$('nav.tabs button[data-tab="speech"]')[0].click();
    if (window.tkFrom) tkFrom(LL.out.text, LL.to);
    if (window.showSub) showSub("talk");
  });
  $("#ll-play-src").addEventListener("click", () => llSay("source"));
  $("#ll-avgo").addEventListener("click", llAvSay);
  llAvatars().catch(e => { $("#ll-avstate").textContent = "The avatars could not be loaded: " + e.message; });
  $("#ll-stop").addEventListener("click", llStop);
  $("#ll-clear").addEventListener("click", () => { $("#ll-text").value = ""; LL.out = null; llRenderOut(); llMark(false); $("#ll-text").focus(); });
  $$("#ll-examples button").forEach(b => b.addEventListener("click", () => { $("#ll-text").value = b.dataset.say; llTranslate(); }));
  llFace("sil", 0);
  llSetPair(LL.from, LL.to, true);
}

function llSetPair(from, to, first) {
  if (from === to) { to = from === "en" ? "es" : "en"; }
  LL.from = from; LL.to = to;
  $("#ll-from").value = from; $("#ll-to").value = to;
  try { localStorage.setItem("qb-lab-pair", JSON.stringify({ from, to })); } catch (e) { /* ignore */ }
  $$(".ll-fromname").forEach(e => e.textContent = llName(from));
  $$(".ll-toname").forEach(e => e.textContent = llName(to));
  $("#ll-text").setAttribute("lang", from);
  $("#ll-caps").innerHTML = (LL_RECOG ? '<span class="chip ok">🎙 listening: this browser</span>' : '<span class="chip">🎙 listening: Google key needed (or use Chrome / Edge)</span>') +
    llCapChips(to);
  LL.deckOff = 0; llDeck(true);
  if (!first && $("#ll-text").value.trim()) llTranslate(); else { LL.out = null; llRenderOut(); }
}

function llCapChips(to) {
  const l = LL.langs.find(x => x.code === to) || {};
  const voice = l.espeak !== "" ? '<span class="chip ok">🔊 voice: built in, offline</span>' : '<span class="chip">🔊 voice: this browser’s ' + esc(llName(to)) + " voice</span>";
  const tr = l.offline ? '<span class="chip ok">🌍 translation: offline' + (LL.cloud ? " (+ " + esc(LL.cloudBy) + " for gaps)" : "") + "</span>"
    : '<span class="chip">🌍 translation: ' + esc(LL.cloudBy || "online") + " (online)</span>";
  return voice + tr;
}

// ---------------------------------------------------------------- step 1: words
async function llDeck(reset) {
  if (reset) { LL.deckOff = 0; $("#ll-wlist").innerHTML = ""; }
  // the list is in the language being learned; learning English, it is drawn from the speaker's own language's list
  const learn = LL.to, deckLang = learn === "en" ? LL.from : learn;
  const r = await api("/api/lablang/deck?lang=" + encodeURIComponent(deckLang) + "&q=" + encodeURIComponent(LL.deckQ) + "&limit=60&offset=" + LL.deckOff);
  if (r.nolist) {                                          // a Translate language: no word list, type or say a sentence instead
    $("#ll-wlist").innerHTML = '<li class="muted small">' + esc(llName(deckLang)) + " has no word list here — type or say a word or sentence on the right; it is translated " +
      (LL.cloud ? "by " + esc(LL.cloudBy) + "." : "with the dictionary pack.") + "</li>";
    $("#ll-wcount").textContent = ""; $("#ll-wmore").hidden = true;
    return;
  }
  const shortest = a => a.slice().sort((x, y) => x.length - y.length)[0];
  const rows = r.words.map(w => {
    const target = learn === "en" ? w.en : shortest(w.tr);                          // the word in the language being learned
    const mine = learn === "en" ? shortest(w.tr) : LL.from === "en" ? w.en : "";      // the same word in the speaker's language ("" = look it up)
    const gloss = learn === "en" ? w.tr.slice(0, 3).join(", ") : w.en;
    return '<li><button class="ll-word" data-word="' + esc(target) + '" data-mine="' + esc(mine) + '" data-en="' + esc(w.en) + '" title="Use this word">' +
      '<b lang="' + learn + '">' + esc(target) + '</b><span class="muted">' + esc(gloss) + '</span></button>' +
      '<button class="icon ll-say1" data-word="' + esc(target) + '" aria-label="Hear ' + esc(target) + '" title="Hear it">🔊</button></li>';
  }).join("");
  $("#ll-wlist").insertAdjacentHTML("beforeend", rows || (reset ? '<li class="muted small">No word starts with “' + esc(LL.deckQ) + '”.</li>' : ""));
  LL.deckOff += r.words.length;
  $("#ll-wcount").textContent = QB.num(r.total) + (LL.deckQ ? " matching" : "") + " words, most common first";
  $("#ll-wmore").hidden = LL.deckOff >= r.total;
  $$("#ll-wlist .ll-word").forEach(b => b.onclick = () => llPickWord(b.dataset.word, b.dataset.mine, b.dataset.en));
  $$("#ll-wlist .ll-say1").forEach(b => b.onclick = () => llSay("word", b.dataset.word));
}

async function llPickWord(target, mine, en) {
  if (!mine) {                                             // neither side is English: the word in the speaker's language, via English
    const f = await api("/api/lablang/fill", { src: "en", tgt: LL.from, words: [en] });
    mine = (f.words[en] && f.words[en].via) ? f.words[en].text : en;
  }
  $("#ll-text").value = mine;
  const seg = { kind: "wordlist", source: mine, target, flagged: false, others: [],
    provenance: { type: "wordlist", detail: "From the word list — " + llName(LL.to) + " for “" + en + "”" } };
  LL.out = { pieces: [{ text: target, seg: 0 }], segs: [seg], notes: [], text: target };
  llRenderOut(); llMark(false);
  llSay("target");
}

// ---------------------------------------------------------------- step 2–3: translate
async function llEngine() {
  if (!LL.engine) {
    const mod = await import("./translate/src/core/engine.js");
    const reg = await (await fetch("translate/data/languages.json")).json();
    LL.engine = new mod.TranslatorEngine({ languages: reg });
    LL.catalog = (await (await fetch("translate/packs/catalog.json")).json()).packs || [];
  }
  for (const code of [LL.from, LL.to]) {
    for (const p of LL.catalog.filter(x => x.lang === code && !LL.packsLoaded.has(x.id))) {
      try { LL.engine.loadPack(await (await fetch("translate/" + p.url)).json()); LL.packsLoaded.add(p.id); } catch (e) { /* a missing pack: the word list fills in */ }
    }
  }
  return LL.engine;
}

async function llTranslate() {
  const text = $("#ll-text").value.trim();
  if (!text) { toast("Type something first, pick a word on the left, or press 🎙 and say it."); $("#ll-text").focus(); return; }
  let r = null;
  try { const eng = await llEngine(); if (eng.language(LL.from) && eng.language(LL.to)) r = eng.translate({ text, src: LL.from, tgt: LL.to }); }
  catch (e) { r = null; }
  // pieces: [{text, seg}], segments: [{kind, source, target, flagged, provenance, alternatives}]
  let pieces, segs;
  if (r && r.pieces) { pieces = r.pieces.map(p => Object.assign({}, p)); segs = r.segments.map(s => Object.assign({}, s)); }
  else {
    segs = []; pieces = [];
    (text.match(/[\p{L}\p{M}'’-]+|\d+|[^\s\p{L}\p{M}\d]+|\s+/gu) || []).forEach(t => {
      if (/^\s+$/.test(t)) { pieces.push({ text: t, seg: null }); return; }
      const word = /\p{L}/u.test(t);
      segs.push({ kind: word ? "unknown" : "punct", source: t, target: t, flagged: word });
      pieces.push({ text: t, seg: segs.length - 1 });
    });
  }
  const need = [...new Set(segs.filter(s => s.flagged && (s.kind === "unknown" || s.kind === "gap") && /\p{L}/u.test(s.source)).map(s => s.source))];
  if (need.length) {
    const f = await api("/api/lablang/fill", { src: LL.from, tgt: LL.to, words: need });
    segs.forEach((s, i) => {
      const w = f.words[s.source];
      if (s.flagged && w && w.via) {
        Object.assign(s, { target: llCase(s.source, w.text), flagged: false, kind: "wordlist", others: w.others, provenance: { type: "wordlist", detail: "From the " + w.via + (w.others.length ? " — other words: " + w.others.join(", ") : "") } });
        pieces.forEach(p => { if (p.seg === i) p.text = s.target; });
      }
    });
  }
  LL.out = { pieces, segs, notes: r ? r.notes : [], text: pieces.map(p => p.text).join("").replace(/\s+([,.?!;:])/g, "$1").trim() };
  // online (Google Translate, else Gemini) when there is no offline data, or the offline words leave gaps; the
  // word-by-word result stays underneath so every word can still be checked
  const gaps = segs.some(s => s.flagged && /\p{L}/u.test(s.source));
  if (LL.cloud && (gaps || !r || !r.pieces)) {
    $("#ll-out").innerHTML = '<p class="muted ll-empty">Translating with ' + esc(LL.cloudBy) + "…</p>";
    try {
      const c = await api("/api/lablang/cloudtr", { text, src: LL.from, tgt: LL.to });
      const offline = LL.out;
      const seg = { kind: "cloud", source: text, target: c.text, flagged: false, others: [], provenance: { type: "cloud", detail: "Translated by " + c.by + " (online)" } };
      LL.out = { pieces: [{ text: c.text, seg: 0 }], segs: [seg], notes: [], text: c.text, by: c.by, offline };
    } catch (e) { LL.out.cloudError = e.message; }
  }
  llRenderOut();
  llMark(false);
}
const llCase = (src, t) => /^\p{Lu}/u.test(src) ? t.charAt(0).toLocaleUpperCase() + t.slice(1) : t;

function llRenderOut() {
  const o = LL.out;
  $("#ll-play").disabled = !o; $("#ll-practice").disabled = !o; $("#ll-clip").disabled = !o; $("#ll-avgo").disabled = !o;
  if (!o) {
    $("#ll-out").innerHTML = '<p class="muted ll-empty">The translation appears here, word by word — tap any word to see where it came from.</p>';
    $("#ll-ipa").textContent = ""; $("#ll-karaoke").innerHTML = ""; $("#ll-score").innerHTML = ""; $("#ll-notes").innerHTML = "";
    return;
  }
  $("#ll-out").setAttribute("lang", LL.to);
  $("#ll-out").innerHTML = o.pieces.map((p, k) => {
    if (p.seg === null || p.seg === undefined) return esc(p.text);
    const s = o.segs[p.seg], cls = s.kind === "punct" || s.kind === "number" ? "" : s.flagged ? "unk" : s.kind === "wordlist" ? "wl" : s.kind === "cloud" ? "cl" : "dict";
    if (!cls) return esc(p.text);
    return '<button class="ll-tok ' + cls + '" data-seg="' + p.seg + '">' + esc(p.text) + "</button>";
  }).join("");
  $$("#ll-out .ll-tok").forEach(b => b.onclick = () => llWhy(+b.dataset.seg, b));
  const unk = o.segs.filter(s => s.flagged && /\p{L}/u.test(s.source)).length, wl = o.segs.filter(s => s.kind === "wordlist").length;
  const off = o.offline && o.offline.segs.some(s => !s.flagged && /\p{L}/u.test(s.source)) ? o.offline.text : "";
  $("#ll-notes").innerHTML = (o.by ? '<span class="chip ok">🌐 Translated by ' + esc(o.by) + " (online)</span>" +
      (off && off !== o.text ? '<p class="small muted">Word by word, offline: <span lang="' + LL.to + '">' + esc(off) + "</span></p>" : "") : "") +
    (o.cloudError ? '<p class="small bad-t">Online translation failed: ' + esc(o.cloudError) + "</p>" : "") +
    (!o.by && !LL.cloud && unk ? '<p class="small muted">Add a Google or Gemini key (Speech → Keys, or Control Panel → API keys) to translate the missing words online.</p>' : "") +
    (o.by ? "" : unk ? '<span class="chip warn">' + unk + " word" + (unk > 1 ? "s" : "") + " not found — kept as written (underlined)</span>" : "") +
    (wl ? '<span class="chip">' + wl + " from the word list (dotted) — tap to choose another</span>" : "") +
    (o.segs.some(s => s.kind === "phrase" || s.kind === "word" || s.kind === "omitted") ? '<span class="chip ok">dictionary phrases and words</span>' : "") +
    ((o.notes || []).some(n => /entry by entry/.test(n)) || o.segs.filter(s => s.kind !== "punct" && s.kind !== "number").length > 1 && o.segs.some(s => s.kind === "wordlist")
      ? '<p class="small muted">Put together word by word: the words are right, but word endings, gender (el / la) and word order may need a native speaker’s eye.</p>' : "");
  $("#ll-score").innerHTML = "";
  $("#ll-karaoke").innerHTML = '<span class="muted">Press ▶ to hear it.</span>';
}

function llWhy(i, el) {
  const s = LL.out.segs[i];
  const alts = (s.others || (s.alternatives || []).map(a => a.form || a)).filter(Boolean).slice(0, 6);
  $("#ll-why").innerHTML = '<div class="note' + (s.flagged ? " bad" : "") + '"><b lang="' + LL.to + '">' + esc(s.target || s.source) + "</b> ← <span lang=\"" + LL.from + '">' + esc(s.source) + "</span><br>" +
    '<span class="small">' + esc((s.provenance && s.provenance.detail) || "") + "</span>" +
    (alts.length ? '<div class="row" style="margin-top:6px"><span class="small muted">Use instead:</span>' + alts.map(a => '<button class="btn secondary small ll-alt" data-alt="' + esc(a) + '">' + esc(a) + "</button>").join("") + "</div>" : "") +
    '<div class="row" style="margin-top:6px"><button class="btn secondary small" id="ll-why-say">🔊 Hear this word</button></div></div>';
  $$("#ll-why .ll-alt").forEach(b => b.onclick = () => {
    s.target = llCase(s.source, b.dataset.alt);
    LL.out.pieces.forEach(p => { if (p.seg === i) p.text = s.target; });
    LL.out.text = LL.out.pieces.map(p => p.text).join("").replace(/\s+([,.?!;:])/g, "$1").trim();
    llRenderOut(); llWhy(i);
  });
  $("#ll-why-say").onclick = () => llSay("word", s.target || s.source);
}

// ---------------------------------------------------------------- step 4: hear it, watch the mouth
async function llSay(which, word) {
  const lang = which === "source" ? LL.from : LL.to;
  const text = which === "word" ? word : which === "source" ? $("#ll-text").value.trim() : (LL.out && LL.out.text);
  if (!text) { toast(which === "target" ? "Translate first, then press ▶." : "Type something first."); return; }
  llStop();
  let r;
  try { r = await api("/api/lablang/say", { text, lang, voice: $("#ll-voice").value, rate: +$("#ll-speed").value }); }
  catch (e) {
    if (/^no-espeak-voice|espeak-ng is missing/.test(e.message)) return llBrowserSay(text, lang);
    throw e;
  }
  LL.said = r;
  $("#ll-ipa").innerHTML = r.ipa ? '<span class="muted">Say it like:</span> <span class="ipa">/' + esc(r.ipa) + "/</span>" : "";
  const words = r.track.words || [];
  $("#ll-karaoke").setAttribute("lang", lang);
  $("#ll-karaoke").innerHTML = words.length ? words.map((w, k) => '<span data-k="' + k + '">' + esc(w.word) + "</span>").join(" ") : esc(text);
  const a = new Audio(r.audio);
  LL.playing = a;
  a.onended = () => { cancelAnimationFrame(LL.raf); llFace("sil", 0); $$("#ll-karaoke span").forEach(s => s.classList.remove("on")); $("#ll-mouthnow").textContent = "";
    if ($("#ll-repeat").checked && LL.playing === a) setTimeout(() => { if (LL.playing === a) { a.currentTime = 0; a.play(); llAnimate(a, r.track); } }, 700); };
  await a.play().catch(() => toast("The browser blocked the sound — press ▶ again.", true));
  llAnimate(a, r.track);
}
// the browser's own voice for the language (Windows / Edge / Chrome have voices for many languages espeak-ng lacks)
function llBrowserSay(text, lang) {
  if (!window.speechSynthesis) { toast("No voice for " + llName(lang) + " here — try Edge or Chrome.", true); return; }
  const tag = llSpeechTag(lang), base = tag.split("-")[0].toLowerCase(), all = speechSynthesis.getVoices();
  const v = all.find(x => x.lang.toLowerCase() === tag.toLowerCase()) || all.find(x => x.lang.toLowerCase().split(/[-_]/)[0] === base);
  if (!v) toast("This browser has no " + llName(lang) + " voice installed — Windows: Settings → Time & language → Speech → Add voices.", true);
  const u = new SpeechSynthesisUtterance(text);
  u.lang = tag; if (v) u.voice = v; u.rate = Math.max(0.5, Math.min(2, (+$("#ll-speed").value || 150) / 150));
  $("#ll-ipa").textContent = "";
  $("#ll-karaoke").setAttribute("lang", lang);
  const words = text.split(/\s+/);
  $("#ll-karaoke").innerHTML = words.map((w, k) => '<span data-k="' + k + '">' + esc(w) + "</span>").join(" ") + ' <span class="muted small">(browser voice)</span>';
  let k = 0;
  u.onboundary = ev => { if (ev.name !== "word") return; $$("#ll-karaoke span[data-k]").forEach(s => s.classList.toggle("on", +s.dataset.k === k)); llFace(["aa", "E", "O", "I", "U"][k % 5]); k++; };
  u.onend = () => { llFace("sil", 0); $$("#ll-karaoke span").forEach(s => s.classList.remove("on")); };
  LL.playing = { pause: () => speechSynthesis.cancel() };
  speechSynthesis.cancel(); speechSynthesis.speak(u);
}
function llStop() {
  if (LL.playing) { LL.playing.pause(); LL.playing = null; }
  cancelAnimationFrame(LL.raf); llFace("sil", 0);
}

// mouth shapes (Oculus/Meta 15): [opening 0–1, width 0–1, rounding 0–1, show: teeth / tongue / lip-on-teeth]
const LL_SHAPE = { sil: [0.02, 0.55, 0, ""], PP: [0, 0.5, 0, ""], FF: [0.12, 0.6, 0, "lip"], TH: [0.22, 0.6, 0, "tongue"], DD: [0.26, 0.62, 0, "teeth"],
  kk: [0.32, 0.6, 0, ""], CH: [0.26, 0.42, 0.6, "teeth"], SS: [0.1, 0.7, 0, "teeth"], nn: [0.2, 0.6, 0, "tongue"], RR: [0.26, 0.46, 0.5, ""],
  aa: [0.85, 0.66, 0, "teeth"], E: [0.48, 0.76, 0, "teeth"], I: [0.22, 0.82, 0, "teeth"], O: [0.62, 0.44, 0.8, ""], U: [0.3, 0.34, 1, ""] };
const LL_DESC = { sil: "rest", PP: "lips pressed (p b m)", FF: "lower lip to teeth (f v)", TH: "tongue between teeth (th)", DD: "tongue behind teeth (t d)",
  kk: "back of tongue (k g)", CH: "lips forward (ch sh j)", SS: "teeth close (s z)", nn: "tongue up (n l)", RR: "lips rounded (r)", aa: "jaw open (a)",
  E: "spread, half open (e)", I: "spread, nearly closed (ee)", O: "rounded, open (o)", U: "small round (oo w)" };
let LL_CUR = [0.02, 0.55, 0];

function llAnimate(a, track) {
  const vs = track.visemes || [], ws = track.words || [];
  const step = () => {
    if (LL.playing !== a) return;
    const t = a.currentTime;
    const v = vs.find(x => t >= x.start && t < x.end) || { v: "sil" };
    const tgt = LL_SHAPE[v.v] || LL_SHAPE.sil;
    for (let k = 0; k < 3; k++) LL_CUR[k] += (tgt[k] - LL_CUR[k]) * 0.45;      // ease toward the shape (lips are not instant)
    llDraw(LL_CUR, tgt[3]);
    $("#ll-mouthnow").textContent = v.v !== "sil" ? "mouth: " + (LL_DESC[v.v] || v.v) : "";
    const cur = ws.findIndex(w => t >= w.start && t < w.end);                    // exactly one word lit (the one being said)
    $$("#ll-karaoke span").forEach(s => s.classList.toggle("on", +s.dataset.k === cur));
    if (!a.paused && !a.ended) LL.raf = requestAnimationFrame(step);
  };
  LL.raf = requestAnimationFrame(step);
}
function llFace(v) { const s = LL_SHAPE[v] || LL_SHAPE.sil; LL_CUR = s.slice(0, 3); llDraw(LL_CUR, s[3]); }

function llDraw(cur, show) {
  const [open, width, round] = cur;
  const cx = 100, cy = 150, w = 18 + 34 * width * (1 - 0.35 * round), h = 2 + 30 * open + 6 * round * open;
  const lip = 3.5 + 2.5 * round;
  const outer = "M" + (cx - w - lip) + "," + cy + " C" + (cx - w * 0.6) + "," + (cy - h - lip * 1.6) + " " + (cx + w * 0.6) + "," + (cy - h - lip * 1.6) + " " + (cx + w + lip) + "," + cy +
    " C" + (cx + w * 0.6) + "," + (cy + h + lip * 1.8) + " " + (cx - w * 0.6) + "," + (cy + h + lip * 1.8) + " " + (cx - w - lip) + "," + cy + "Z";
  const inner = "M" + (cx - w) + "," + cy + " C" + (cx - w * 0.55) + "," + (cy - h) + " " + (cx + w * 0.55) + "," + (cy - h) + " " + (cx + w) + "," + cy +
    " C" + (cx + w * 0.55) + "," + (cy + h) + " " + (cx - w * 0.55) + "," + (cy + h) + " " + (cx - w) + "," + cy + "Z";
  let extra = "";
  if (h > 4 && show === "teeth") extra += '<rect x="' + (cx - w * 0.7) + '" y="' + (cy - h * 0.62) + '" width="' + (w * 1.4) + '" height="' + Math.min(6, h * 0.35) + '" rx="2" fill="#fff"/>';
  if (show === "lip") extra += '<rect x="' + (cx - w * 0.6) + '" y="' + (cy - 3) + '" width="' + (w * 1.2) + '" height="4" rx="2" fill="#fff"/>';
  if (show === "tongue" && h > 3) extra += '<ellipse cx="' + cx + '" cy="' + (cy + h * 0.25) + '" rx="' + (w * 0.5) + '" ry="' + Math.max(2, h * 0.45) + '" fill="#d9707a"/>';
  $("#ll-mouth").innerHTML = '<path d="' + outer + '" fill="var(--ll-lip)"/>' + (h > 1.2 ? '<path d="' + inner + '" fill="#3b1218"/>' + extra : "") +
    '<path d="M' + (cx - w) + "," + cy + " L" + (cx + w) + "," + cy + '" stroke="#5a1a22" stroke-width="' + (h > 1.2 ? 0 : 1.4) + '"/>';
}

// ---------------------------------------------------------------- speech in: say the source text, or practise the translation
async function llListen(mode) {
  if (LL.rec) { LL.rec.stop(); return; }
  const lang = mode === "source" ? LL.from : LL.to;
  const btn = mode === "source" ? $("#ll-mic") : $("#ll-practice");
  const label = btn.textContent;
  const done = () => { LL.rec = null; btn.textContent = label; btn.classList.remove("rec"); $("#ll-micstate").textContent = ""; };
  if (LL_RECOG) {
    const r = new LL_RECOG();
    r.lang = llSpeechTag(lang); r.interimResults = true; r.continuous = false; r.maxAlternatives = 3;
    let heard = "";
    r.onresult = e => {
      heard = Array.from(e.results).map(x => x[0].transcript).join("");
      if (mode === "source") $("#ll-text").value = heard; else llScore(heard, false);
    };
    r.onerror = e => { if (e.error === "not-allowed") toast("The microphone is blocked — allow it in the address bar and try again.", true);
      else if (e.error === "no-speech") toast("Nothing was heard — try again a little closer to the microphone."); else if (e.error !== "aborted") toast("Listening stopped: " + e.error, true); };
    r.onend = () => { done(); if (!heard) return; if (mode === "source") llTranslate(); else llScore(heard, true); };
    LL.rec = r; btn.textContent = "⏹ Stop listening"; btn.classList.add("rec");
    $("#ll-micstate").textContent = mode === "source" ? "Listening in " + llName(lang) + "…" : "";
    try { r.start(); } catch (e) { done(); }
    return;
  }
  // no browser recognizer: record, and let the app's Google Speech-to-Text (if a key is set) write the words
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { toast("The microphone could not be opened: " + e.message, true); return; }
  const ctx = new (window.AudioContext || window.webkitAudioContext)(), src = ctx.createMediaStreamSource(stream), proc = ctx.createScriptProcessor(4096, 1, 1), chunks = [];
  proc.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(proc); proc.connect(ctx.destination);
  LL.rec = { stop: async () => {
    proc.disconnect(); src.disconnect(); stream.getTracks().forEach(t => t.stop());
    const sr = ctx.sampleRate; ctx.close(); done();
    const n = chunks.reduce((s, c) => s + c.length, 0), pcm = new Int16Array(n); let o = 0;
    chunks.forEach(c => { for (let i = 0; i < c.length; i++) pcm[o++] = Math.max(-32768, Math.min(32767, c[i] * 32768)); });
    const buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf), wr = (p, s) => { for (let i = 0; i < s.length; i++) v.setUint8(p + i, s.charCodeAt(i)); };
    wr(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); wr(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); wr(36, "data"); v.setUint32(40, pcm.length * 2, true);
    new Int16Array(buf, 44).set(pcm);
    const b64 = await new Promise(res => { const f = new FileReader(); f.onload = () => res(f.result); f.readAsDataURL(new Blob([buf], { type: "audio/wav" })); });
    const r = await api("/api/lablang/hear", { audio_b64: b64, lang });
    if (mode === "source") { $("#ll-text").value = r.text; llTranslate(); } else llScore(r.text, true);
  } };
  btn.textContent = "⏹ Stop"; btn.classList.add("rec");
  $("#ll-micstate").textContent = "Recording… press Stop when you have finished.";
}

// practice: which words of the translation were heard
const llNorm = s => s.toLocaleLowerCase().normalize("NFD").replace(/\p{M}/gu, "").replace(/[^\p{L}\d\s']/gu, " ").split(/\s+/).filter(Boolean);
function llScore(heard, final) {
  const want = llNorm(LL.out ? LL.out.text : ""), got = llNorm(heard), pool = got.slice();
  const marks = want.map(w => { const i = pool.findIndex(g => g === w || (w.length > 3 && (g.startsWith(w.slice(0, -1)) || w.startsWith(g.slice(0, -1))))); if (i >= 0) { pool.splice(i, 1); return true; } return false; });
  const n = marks.filter(Boolean).length, pct = want.length ? Math.round(100 * n / want.length) : 0;
  const words = (LL.out ? LL.out.text : "").split(/\s+/);
  $("#ll-score").innerHTML = '<p lang="' + LL.to + '" class="ll-practice">' + words.map((w, k) => '<span class="' + (marks[k] ? "hit" : final ? "miss" : "") + '">' + esc(w) + "</span>").join(" ") + "</p>" +
    '<p class="small">Heard: “' + esc(heard) + "”</p>" + (final ? '<p><b>' + n + " of " + want.length + " words</b> " +
      (pct === 100 ? "— perfect! 🎉" : pct >= 60 ? "— nearly there. Press 🔊 on the red words, then try again." : "— listen once more at the slow speed, then try again.") + "</p>" : "");
}

function llMark(on) { $("#ll-tr").classList.toggle("pulse", !!$("#ll-text").value.trim() && !LL.out); }

// ---------------------------------------------------------------- step 4: the human avatar (Language 1.54)
// A library avatar (Pamela, the starter faces, any face added on Speech) says the sentence in a talking video made by
// Gemini; when Gemini cannot, ElevenLabs (or the Speak page's voice) speaks and HeyGen moves the face — the talking
// clips of Speech → Talking clips, shown right here. Nothing animates the face on this computer.
function llAvGuess(name) { return /^(man|male|boy)\b/i.test(name) ? "man" : /^(woman|pamela|girl|female)\b/i.test(name) ? "woman" : "person"; }
async function llAvatars() {
  const r = await api("/api/avatars/list");
  const faces = (r.avatars || []).filter(a => a.kind !== "body");
  let cur = "";
  try { cur = localStorage.getItem("qb-lab-avatar") || ""; } catch (e) { /* first visit */ }
  if (!faces.some(a => String(a.id) === cur)) cur = String((faces.find(a => a.name === "Pamela") || faces[0] || {}).id || "");
  $("#ll-avfaces").innerHTML = faces.map(a => '<button type="button" data-av="' + a.id + '" data-name="' + esc(a.name) + '" title="' + esc(a.name) + '"><img loading="lazy" alt="' + esc(a.name) + '" src="/api/avatars/image?id=' + a.id + '"></button>').join("")
    || '<p class="small muted">No avatars yet — add one on Speech → Talking clips.</p>';
  $$("#ll-avfaces [data-av]").forEach(b => b.onclick = () => llAvPick(b.dataset.av, b.dataset.name));
  const b = $('#ll-avfaces [data-av="' + cur + '"]');
  if (b) llAvPick(cur, b.dataset.name);
}
function llAvPick(id, name) {
  LL.avatar = id; LL.avatarName = name;
  try { localStorage.setItem("qb-lab-avatar", id); } catch (e) { /* storage unavailable */ }
  $$("#ll-avfaces [data-av]").forEach(x => x.classList.toggle("on", x.dataset.av === String(id)));
  $("#ll-avstage").innerHTML = '<img id="ll-avimg" alt="' + esc(name) + '" src="/api/avatars/image?id=' + id + '">';
  $("#ll-avperson").value = llAvGuess(name);
  $("#ll-avstate").textContent = "";
}
async function llAvSay() {
  if (!LL.out || !LL.out.text || !LL.avatar) return;
  const btn = $("#ll-avgo"); btn.disabled = true;
  llSay("target").catch(() => {});                         // heard at once; the lip-synced video follows
  $("#ll-avstate").textContent = (LL.avatarName || "The avatar") + " is getting ready to say it — the lip-synced video takes about a minute…";
  try {
    const c = await api("/api/talk/make", { text: LL.out.text, lang: LL.to, person: $("#ll-avperson").value, route: "auto", face: LL.avatar });
    llAvFollow(c.id);
  } catch (e) {
    $("#ll-avstate").innerHTML = '<span class="bad-t">The video could not be made: ' + esc(e.message) + "</span>" +
      '<br><span class="small muted">It needs a Gemini key, or ElevenLabs + HeyGen keys (Speech → Keys, or Control Panel → API keys). The sentence was spoken with the built-in voice.</span>';
    btn.disabled = false;
  }
}
async function llAvFollow(id) {
  let c;
  try { c = await api("/api/talk/clip?id=" + encodeURIComponent(id)); }
  catch (e) { $("#ll-avstate").innerHTML = '<span class="bad-t">' + esc(e.message) + "</span>"; $("#ll-avgo").disabled = false; return; }
  if (c.status === "queued" || c.status === "working") {
    $("#ll-avstate").textContent = (c.detail || "working") + "…";
    LL.avPoll = setTimeout(() => llAvFollow(id), 3000);
    return;
  }
  $("#ll-avgo").disabled = false;
  if (c.status === "done") {
    $("#ll-avstage").innerHTML = '<video controls autoplay playsinline src="/api/talk/video?id=' + c.id + '"></video>';
    $("#ll-avstate").innerHTML = "Made by <b>" + (c.route === "gemini" ? "Gemini" : "HeyGen") + "</b>" + (c.why && c.route === "heygen" ? " — " + esc(c.why) : "") +
      ' · <a href="/api/talk/video?id=' + c.id + '" download="talking-clip-' + c.id + '.mp4">download</a> · <span class="muted">' + esc(c.label || "") + "</span>";
  } else {
    const d = String(c.detail || ""), m = d.match(/"message":\s*"([^"]+)"/);   // a service's JSON error: just its message
    $("#ll-avstate").innerHTML = '<span class="bad-t">Not made: ' + esc(m ? d.split("(")[0].trim() + " — " + m[1] + (/HeyGen/.test(d) ? " (and no HeyGen key is set)" : "") : d) + "</span>" +
      '<br><span class="small muted">The sentence was spoken with the built-in voice. Keys: Speech → Keys, or Control Panel → API keys.</span>';
  }
}
