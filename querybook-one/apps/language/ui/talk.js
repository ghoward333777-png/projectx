"use strict";
// Talking clips (Speech → Talking clips): a portrait says the words in a video made by Gemini — the way the October 29
// answer videos were made — and by HeyGen when Gemini cannot. Nothing here animates a face; the page only asks and plays.
const TK = { ready: false, face: null, picture: null, pictureName: "", poll: null };

function tkFaceChoice() { try { return localStorage.getItem("qb.talkface") || ""; } catch (e) { return ""; } }
function tkSetFace(v) { try { localStorage.setItem("qb.talkface", v); } catch (e) { /* ignore */ } }

async function tkStatus() {
  const s = await api("/api/talk/status");
  const bits = [];
  bits.push(s.gemini_key ? "Gemini: <b>" + s.gemini_left_today + " of " + s.gemini_daily + "</b> videos left today (shared with the exemplar generator)"
    : '<span class="bad-t">No Gemini key — add it on Speech → Voice providers (Google Gemini)</span>');
  bits.push(s.heygen_key ? "HeyGen: key set" : '<span class="muted">HeyGen: no key (needed when Gemini cannot make a clip)</span>');
  bits.push(s.speech_to_text ? "each clip's words are checked with Speech-to-Text" : '<span class="muted">Speech-to-Text not set up: words are not checked</span>');
  $("#tk-status").innerHTML = bits.join(" · ");
  return s;
}

async function tkFaces() {
  const r = await api("/api/avatars/list");
  const faces = r.avatars.filter(a => a.kind !== "body");
  const cur = tkFaceChoice() || String((faces.find(a => a.name === "Pamela") || faces[0] || {}).id || "");
  $("#tk-faces").innerHTML = faces.map(a => '<button class="fp-tile' + (String(a.id) === cur && !TK.picture ? " on" : "") + '" data-tkf="' + a.id + '" title="' + esc(a.name) + '">' +
    '<img loading="lazy" alt="" src="/api/avatars/image?id=' + a.id + '"><span>' + esc(a.name) + "</span></button>").join("") ||
    '<p class="small muted">No portraits yet — use another picture below.</p>';
  TK.face = cur;
  $$("#tk-faces [data-tkf]").forEach(b => b.onclick = () => {
    TK.face = b.dataset.tkf; TK.picture = null; $("#tk-file-name").textContent = ""; tkSetFace(TK.face);
    $$("#tk-faces [data-tkf]").forEach(x => x.classList.toggle("on", x === b));
  });
}

function tkVoice() {
  // the voice chosen on the Speak page, for the HeyGen route (Gemini speaks with its own voice)
  if (!window.SP || !SP.loaded) return null;
  return { engine: SP.engine, voice: ($("#sp-voice") || {}).value || "", model: ($("#sp-model") || {}).value || "", profile: SP.profile };
}

function tkClipHtml(c) {
  const by = c.route === "gemini" ? "Gemini" : c.route === "heygen" ? "HeyGen" : "";
  let h = '<div class="card" data-tkc="' + c.id + '"><div class="small"><b>' + esc(c.face || "face") + "</b> · " + esc(c.created.replace("T", " ")) + " · " + esc(c.lang) + "</div>" +
    '<p>“' + esc(c.line) + "”</p>";
  if (c.status === "done") {
    h += '<video controls playsinline preload="metadata" style="max-width:100%;max-height:420px;border-radius:10px" src="/api/talk/video?id=' + c.id + '"></video>' +
      '<div class="small">Made by <b>' + by + "</b>" + (c.why && c.route === "heygen" ? " — " + esc(c.why) : "") + " in " + (c.seconds || 0).toFixed(1) + " s" +
      (c.heard_share !== null && c.heard_share !== undefined ? ' · words heard: <b class="' + (c.heard_share >= 0.8 ? "good-t" : "bad-t") + '">' + Math.round(100 * c.heard_share) + "%</b>" +
        (c.heard ? ' <span class="muted">(“' + esc(c.heard) + '”)</span>' : "") : "") +
      ' · <a href="/api/talk/video?id=' + c.id + '" download="talking-clip-' + c.id + '.mp4">download MP4</a> · <a href="#" data-tkdel="' + c.id + '">delete</a></div>' +
      '<p class="small muted">' + esc(c.label) + "</p>";
  } else if (c.status === "failed") {
    h += '<div class="note bad">Not made: ' + esc(c.detail) + '</div><div class="small"><a href="#" data-tkdel="' + c.id + '">delete</a></div>';
  } else {
    h += '<div class="meter live"><i style="width:100%"></i></div><p class="small">' + esc(c.detail || c.status) + "</p>";
  }
  return h + "</div>";
}

function tkWire(el) {
  el.querySelectorAll("[data-tkdel]").forEach(a => a.onclick = async e => {
    e.preventDefault(); if (!confirm("Delete this talking clip?")) return;
    await api("/api/talk/delete", { id: a.dataset.tkdel }); tkList(); const o = $("#tk-out [data-tkc='" + a.dataset.tkdel + "']"); if (o) o.remove();
  });
}

async function tkList() {
  const r = await api("/api/talk/list?limit=30");
  $("#tk-list").innerHTML = r.clips.length ? r.clips.map(tkClipHtml).join("") : '<p class="small muted">No clips yet.</p>';
  tkWire($("#tk-list"));
}

async function tkFollow(id) {
  clearTimeout(TK.poll);
  const c = await api("/api/talk/clip?id=" + encodeURIComponent(id));
  $("#tk-out").innerHTML = tkClipHtml(c); tkWire($("#tk-out"));
  if (c.status === "queued" || c.status === "working") TK.poll = setTimeout(() => tkFollow(id).catch(e => toast(e.message, true)), 3000);
  else { tkList(); tkStatus(); }
}

async function tkMake() {
  const text = $("#tk-text").value.trim();
  if (!text) { toast("Type what the face should say.", true); return; }
  if (!TK.picture && !TK.face) { toast("Choose a face first.", true); return; }
  const btn = $("#tk-go"); buttonStart(btn); let ok = false;
  try {
    const body = { text, lang: $("#tk-lang").value, person: $("#tk-person").value, route: $("#tk-route").value, voice: tkVoice() };
    if (TK.picture) { body.image = TK.picture; body.face_name = TK.pictureName; } else body.face = TK.face;
    const c = await api("/api/talk/make", body);
    ok = true; tkFollow(c.id);
  } catch (e) { $("#tk-out").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; }
  finally { buttonEnd(btn, ok); }
}

// from the Speak page: the same words, in the same language
function tkFrom(text, lang) {
  tkInit();
  if (text) $("#tk-text").value = text;
  if (lang && $("#tk-lang").querySelector('option[value="' + lang + '"]')) $("#tk-lang").value = lang;
}

function tkInit() {
  if (!TK.ready) {
    TK.ready = true;
    const names = typeof NAMES !== "undefined" ? NAMES : { en: "English" };
    $("#tk-lang").innerHTML = Object.entries(names).map(([k, v]) => '<option value="' + k + '">' + esc(v) + "</option>").join("");
    $("#tk-lang").value = "en";
    $("#tk-go").onclick = tkMake;
    $("#tk-file").onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      TK.picture = await blobB64(f); TK.pictureName = f.name.replace(/\.[^.]+$/, "");
      $("#tk-file-name").textContent = "✔ " + f.name; $$("#tk-faces [data-tkf]").forEach(x => x.classList.remove("on"));
    };
    tkFaces().catch(e => { $("#tk-faces").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; });
  }
  tkStatus().catch(() => {});
  tkList().catch(() => {});
}
