"use strict";
// Audio files (MP3, M4A, OGG, WAV…): live captions while the file plays, and whole-file transcription of any length.
// The browser decodes the file; Google Speech-to-Text hears it in pieces cut at pauses, sent ahead of playback so
// each word can light up as it is spoken.
const TR = { file: null, pcm: null, sr: 16000, words: [], pieces: [], session: null, playing: false, inflight: 0, next: 0, t0: 0, result: null };

function trFloatWav(x, sr) {
  const dv = new DataView(new ArrayBuffer(44 + x.length * 2));
  const w = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); dv.setUint32(4, 36 + x.length * 2, true); w(8, "WAVE"); w(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, sr, true); dv.setUint32(28, sr * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); w(36, "data"); dv.setUint32(40, x.length * 2, true);
  for (let i = 0; i < x.length; i++) dv.setInt16(44 + 2 * i, Math.max(-32767, Math.min(32767, x[i] * 32767)), true);
  return new Blob([dv.buffer], { type: "audio/wav" });
}

async function trDecode(file) {
  const buf = await file.arrayBuffer();
  const ac = new (window.AudioContext || window.webkitAudioContext)();
  let audio;
  try { audio = await ac.decodeAudioData(buf); } finally { ac.close(); }
  const n = Math.ceil(audio.duration * TR.sr), off = new OfflineAudioContext(1, n, TR.sr);
  const s = off.createBufferSource(); s.buffer = audio; s.connect(off.destination); s.start();
  return (await off.startRendering()).getChannelData(0);
}

// Cut at the quietest 0.3 s between minS and maxS after the previous cut (short first pieces: captions start sooner).
function trCuts(x, sr) {
  const hop = Math.round(sr * 0.02), rms = [];
  for (let i = 0; i < x.length; i += hop) { let e = 0; for (let j = i; j < Math.min(x.length, i + hop); j += 4) e += x[j] * x[j]; rms.push(e); }
  const cuts = [0]; let start = 0, k = 0;
  while ((rms.length - start) * 0.02 > (k === 0 ? 8 : 18)) {
    const minS = k === 0 ? 4 : 10, maxS = k === 0 ? 8 : 18;
    const lo = start + Math.round(minS / 0.02), hi = Math.min(rms.length - 15, start + Math.round(maxS / 0.02));
    let best = Infinity, bi = hi;
    for (let i = lo; i < hi; i++) { let e = 0; for (let j = i; j < i + 15; j++) e += rms[j]; if (e < best) { best = e; bi = i; } }
    start = bi + 7; cuts.push(start); k++;
  }
  return cuts.map(c => c * hop).concat([x.length]);
}

async function trLoad(file) {
  TR.file = file; TR.words = []; TR.result = null;
  $("#tr-out").innerHTML = ""; $("#tr-live").innerHTML = "";
  $("#tr-state").textContent = "Reading " + file.name + "…";
  const t0 = performance.now();
  try { TR.pcm = await trDecode(file); }
  catch (e) { $("#tr-state").textContent = "This file could not be decoded here (" + e.message + "). Try MP3, M4A, OGG or WAV."; return; }
  const dur = TR.pcm.length / TR.sr;
  $("#tr-audio").src = URL.createObjectURL(file); $("#tr-audio").hidden = false;
  $("#tr-state").textContent = file.name + " — " + trTime(dur) + " of audio, read in " + ((performance.now() - t0) / 1000).toFixed(2) + " s.";
  ["#tr-live-go", "#tr-file-go", "#tr-ingest"].forEach(id => $(id).disabled = false);
}

function trTime(s) { const m = Math.floor(s / 60), r = s - 60 * m; return (m ? m + " min " : "") + r.toFixed(2) + " s"; }
function trStamp(s, sep) { const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, r = s % 60; return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + r.toFixed(3).padStart(6, "0").replace(".", sep); }

// ---------------------------------------------------------------- live captions
async function trLive() {
  if (!TR.pcm) return;
  const btn = $("#tr-live-go"), a = $("#tr-audio");
  if (TR.playing) { TR.playing = false; a.pause(); btn.textContent = "▶ Play with live captions"; return; }
  const cuts = trCuts(TR.pcm, TR.sr);
  TR.pieces = cuts.slice(0, -1).map((c, i) => ({ a: c, b: cuts[i + 1], state: "waiting" }));
  TR.words = []; TR.next = 0; TR.inflight = 0; TR.playing = true; TR.t0 = performance.now();
  const s = await api("/api/speech/caption/start", { name: TR.file.name, duration_s: +(TR.pcm.length / TR.sr).toFixed(2), lang: (SP.profile && SP.profile.lang) || "en" });
  TR.session = s.session;
  btn.textContent = "⏸ Pause";
  trPump();
  a.currentTime = 0; a.play().catch(() => {});
  trCaptionLoop();
}

function trPump() {                                     // keep two pieces in flight, ahead of playback
  while (TR.playing && TR.inflight < 2 && TR.next < TR.pieces.length) {
    const p = TR.pieces[TR.next++]; p.state = "sent"; TR.inflight++;
    const wavBlob = trFloatWav(TR.pcm.subarray(p.a, p.b), TR.sr);
    blobB64(wavBlob).then(b64 => fetch("/api/speech/caption/piece", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_b64: b64, offset_s: p.a / TR.sr, lang: (SP.profile && SP.profile.lang) || "en", session: TR.session }) }))
      .then(r => r.json()).then(r => {
        if (r.error) { p.state = "failed"; p.error = r.error; }
        else { p.state = "done"; p.ready_at = (performance.now() - TR.t0) / 1000; TR.words = TR.words.concat(r.words).sort((x, y) => x.start_s - y.start_s); }
      }).catch(e => { p.state = "failed"; p.error = e.message; })
      .finally(() => { TR.inflight--; trPump(); trRenderTranscript(); });
  }
}

function trCaptionLoop() {
  const a = $("#tr-audio"), t = a.currentTime;
  const piece = TR.pieces.find(p => p.a / TR.sr <= t && t < p.b / TR.sr);
  const line = TR.words.filter(w => w.start_s <= t + 0.02 && w.start_s > t - 6).slice(-14);
  let html = line.map(w => '<span class="' + (w.end_s >= t ? "tr-now" : "") + '">' + esc(w.word) + "</span>").join(" ");
  if (piece && piece.state !== "done") html += ' <span class="muted">' + (piece.state === "failed" ? "[this part could not be transcribed: " + esc(piece.error) + "]" : "…") + "</span>";
  $("#tr-live").innerHTML = html || '<span class="muted">…</span>';
  const ahead = TR.pieces.filter(p => p.state === "done").reduce((m, p) => Math.max(m, p.b / TR.sr), 0) - t;
  $("#tr-lag").textContent = ahead >= 0 ? "captions ready " + ahead.toFixed(2) + " s ahead of the voice" : "captions " + (-ahead).toFixed(2) + " s behind the voice";
  if (TR.playing && !a.ended) requestAnimationFrame(trCaptionLoop);
  else { TR.playing = false; $("#tr-live-go").textContent = "▶ Play with live captions"; trRenderTranscript(); }
}

// ---------------------------------------------------------------- whole file (any length)
async function trWhole() {
  if (!TR.pcm) return;
  const btn = $("#tr-file-go"); buttonStart(btn);
  let ok = false;
  try {
    const b64 = await blobB64(trFloatWav(TR.pcm, TR.sr));
    await api("/api/speech/transcribe-file", { audio_b64: b64, lang: (SP.profile && SP.profile.lang) || "en", mode: $("#tr-mode").value });
    for (;;) {
      await new Promise(r => setTimeout(r, 700));
      const j = await api("/api/job");
      const pct = Math.round(100 * (j.overall || (j.total ? j.done / j.total : 0)));
      $("#tr-state").textContent = (j.message || "working") + " — " + pct + "% · " + (j.elapsed || 0).toFixed(2) + " s";
      $("#tr-prog").style.width = pct + "%";
      if (j.state === "finished") { TR.result = j.result; TR.words = j.result.words; ok = true; break; }
      if (j.state === "failed" || j.state === "stopped") { $("#tr-state").textContent = "Transcription stopped: " + (j.message || j.state); break; }
    }
    if (ok) $("#tr-state").textContent = "Transcribed " + trTime(TR.result.duration_s) + " in " + (TR.result.method || "") + " — " + TR.words.length + " words" +
      (TR.result.confidence !== null && TR.result.confidence !== undefined ? ", confidence " + Math.round(100 * TR.result.confidence) + "%" : "") + ".";
    trRenderTranscript();
  } catch (e) { $("#tr-state").textContent = e.message; }
  finally { buttonEnd(btn, ok); }
}

// ---------------------------------------------------------------- transcript, downloads, ingestion
function trLines(maxS, maxChars) {
  const lines = []; let cur = null;
  for (const w of TR.words) {
    if (!cur || w.start_s - cur.start > maxS || (cur.text + " " + w.word).length > maxChars || w.start_s - cur.end > 1.2) { cur = { start: w.start_s, end: w.end_s, text: w.word }; lines.push(cur); }
    else { cur.text += " " + w.word; cur.end = w.end_s; }
  }
  return lines;
}
function trRenderTranscript() {
  if (!TR.words.length) return;
  const lines = trLines(7, 84);
  $("#tr-out").innerHTML = '<div class="row" style="margin:6px 0">' + ["txt", "srt", "vtt", "json"].map(f => '<button class="btn quiet small" data-trdl="' + f + '">⬇ ' + f.toUpperCase() + "</button>").join("") + "</div>" +
    '<div class="tr-text">' + lines.map(l => '<p><a class="tr-t" data-t="' + l.start + '">' + trStamp(l.start, ".").slice(3, 11) + "</a> " + esc(l.text) + "</p>").join("") + "</div>";
  $$("#tr-out [data-t]").forEach(el => el.onclick = () => { const a = $("#tr-audio"); a.currentTime = Number(el.dataset.t); a.play().catch(() => {}); });
  $$("#tr-out [data-trdl]").forEach(b => b.onclick = () => trDownload(b.dataset.trdl));
}
function trDownload(fmt) {
  const lines = trLines(6, 42), base = (TR.file ? TR.file.name.replace(/\.[^.]+$/, "") : "transcript");
  let text, type = "text/plain";
  if (fmt === "srt") text = lines.map((l, i) => (i + 1) + "\n" + trStamp(l.start, ",") + " --> " + trStamp(l.end, ",") + "\n" + l.text + "\n").join("\n");
  else if (fmt === "vtt") { text = "WEBVTT\n\n" + lines.map(l => trStamp(l.start, ".") + " --> " + trStamp(l.end, ".") + "\n" + l.text + "\n").join("\n"); type = "text/vtt"; }
  else if (fmt === "json") { text = JSON.stringify({ file: TR.file && TR.file.name, words: TR.words, transcript: TR.words.map(w => w.word).join(" ") }, null, 1); type = "application/json"; }
  else text = trLines(30, 400).map(l => "[" + trStamp(l.start, ".").slice(0, 8) + "] " + l.text).join("\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = base + "." + fmt; a.click();
}
async function trIngest() {
  if (!TR.pcm) return;
  const dur = TR.pcm.length / TR.sr;
  // how it was said is measured on up to the first 5 minutes; the words come from the whole file
  const part = TR.pcm.subarray(0, Math.min(TR.pcm.length, 300 * TR.sr));
  const transcript = TR.words.length ? TR.words.map(w => w.word).join(" ") : "";
  SP.wav = await blobB64(trFloatWav(part, TR.sr)); SP.wavName = TR.file.name; SP.video = null;
  $("#ls-transcript").value = transcript;
  $("#ls-recog").value = transcript ? "browser" : "auto";
  await lsAnalyse();
  if (dur > 300) toast("How it was said was measured on the first 5 minutes; the words cover the whole file.");
}

function trSetup() {
  if (TR.ready) return; TR.ready = true;
  $("#tr-file").onchange = e => { const f = e.target.files[0]; if (f) trLoad(f); };
  $("#tr-live-go").onclick = trLive;
  $("#tr-file-go").onclick = trWhole;
  $("#tr-ingest").onclick = trIngest;
  $("#tr-audio").addEventListener("pause", () => { if (TR.playing && !$("#tr-audio").ended) { TR.playing = false; $("#tr-live-go").textContent = "▶ Play with live captions"; } });
}
document.addEventListener("click", e => { const b = e.target.closest && e.target.closest('#sptabs [data-sp="listen"]'); if (b) trSetup(); });
