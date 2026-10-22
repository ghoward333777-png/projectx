"use strict";
// Visual Speech Engine (stage 1): full-face lip-sync motion from words + audio, its preview and exports,
// the engine's lip-reading and face analysis inside "Analyse video", and the benchmark against lip-reading v1.
const VSE = { motion: null, csv: null, audioUrl: null, raf: null };

async function vseJob(path, body, onProgress) {
  const j = await api(path, body);
  for (;;) {
    await new Promise(r => setTimeout(r, 400));
    const s = await fetch("/api/vse/job?id=" + j.job_id).then(r => r.json());
    if (onProgress && s.progress) onProgress(s.progress);
    if (s.status === "completed") return s.result;
    if (s.status === "failed") throw new Error(s.error || "the job failed");
  }
}

// ---------------------------------------------------------------- lip sync
async function vseLipSync() {
  const text = $("#vse-text").value.trim(), file = $("#vse-audio").files[0];
  if (!text) { toast("Type the words that are spoken.", true); return; }
  const btn = $("#vse-go"); buttonStart(btn);
  let ok = false;
  try {
    const body = { text, fps: Number($("#vse-fps").value), lang: (window.SP && SP.profile && SP.profile.lang) || "en" };
    if (file) {
      $("#vse-state").textContent = "Reading the audio…";
      const audio = await decodeTrack(file);
      body.audio_b64 = await wavB64(audio, 16000);
      if (VSE.audioUrl) URL.revokeObjectURL(VSE.audioUrl);
      VSE.audioUrl = URL.createObjectURL(file);
    } else VSE.audioUrl = null;
    const r = await vseJob("/api/vse/lip_sync", body, p => { $("#vse-state").textContent = p.message || "working…"; });
    VSE.motion = r.motion; VSE.csv = r.arkit_csv || null;
    const emo = r.emotion ? Object.entries(r.emotion).filter(([k, v]) => typeof v === "number" && v >= 0.25).map(([k, v]) => k + " " + v.toFixed(2)).join(", ") : "";
    const vis = (r.visemes || r.viseme_sequence || { visemes: [] }).visemes;
    $("#vse-out").innerHTML = '<div class="note good"><b>Motion ready:</b> ' + r.motion.frames.length + " frames at " + r.motion.fps + " per second · " + vis.length + " visemes · " +
      (r.motion.accents_s || []).length + " pitch accents · " + (r.motion.blinks_s || []).length + " blinks" + (emo ? " · emotion: " + esc(emo) : "") +
      (r.personal_targets && r.personal_targets.length ? " · your own mouth shapes for " + r.personal_targets.length + " visemes" : "") + (r.note ? " · " + esc(r.note) : "") + "</div>" +
      '<p class="small">Visemes reached (100% = the full mouth shape; lower = blended into its neighbours): ' +
      vis.slice(0, 40).map(v => '<span class="vd-word ' + (v.intensity >= 0.7 ? "ok" : v.intensity >= 0.4 ? "warn" : "bad") + '">' + esc(v.id) + " " + Math.round(100 * v.intensity) + "%</span>").join(" ") + "</p>";
    $("#vse-dl").innerHTML = '<a class="btn quiet" download="vse-motion.json" href="' + URL.createObjectURL(new Blob([JSON.stringify(r, null, 1)], { type: "application/json" })) + '">⬇ Motion (JSON)</a> ' +
      (VSE.csv ? '<a class="btn quiet" download="vse-arkit-blendshapes.csv" href="' + URL.createObjectURL(new Blob([VSE.csv], { type: "text/csv" })) + '">⬇ ARKit blendshapes (CSV)</a>' : "");
    $("#vse-play").disabled = false;
    $("#vse-state").textContent = "";
    vseDraw(0);
    ok = true;
  } catch (e) { $("#vse-state").textContent = "Stopped: " + e.message; }
  finally { buttonEnd(btn, ok); }
}

function vseFrame(t) {
  const m = VSE.motion; if (!m) return null;
  return m.frames[Math.max(0, Math.min(m.frames.length - 1, Math.round(t * m.fps)))];
}

// A simple face drawn from the motion (preview only — the numbers drive real rigs through the exports).
function vseDraw(t) {
  const c = $("#vse-canvas"), g = c.getContext("2d"), f = vseFrame(t);
  if (!f) return;
  const P = {}; VSE.motion.params.forEach((k, i) => { P[k] = f.mouth[i]; });
  const W = c.width, H = c.height, cx = W / 2, yaw = f.head_pose_deg[0], pitch = f.head_pose_deg[1];
  g.clearRect(0, 0, W, H);
  g.save(); g.translate(cx + yaw * 2, H * 0.5 + pitch * 2); g.rotate(f.head_pose_deg[2] * Math.PI / 180);
  const jaw = 26 * P.jawOpen;
  g.fillStyle = "#f1c9a5"; g.beginPath(); g.ellipse(0, jaw / 3, 92, 118 + jaw / 2, 0, 0, Math.PI * 2); g.fill();
  // eyes, blinks, gaze, brows
  [-1, 1].forEach(s => {
    const ex = s * 36, ey = -30, open = 9 * (1 - f.blink);
    g.fillStyle = "#fff"; g.beginPath(); g.ellipse(ex, ey, 15, Math.max(0.8, open), 0, 0, Math.PI * 2); g.fill();
    if (open > 2) { g.fillStyle = "#3b2f2f"; g.beginPath(); g.arc(ex + f.eye_gaze[0] * 18, ey - f.eye_gaze[1] * 10, 5, 0, Math.PI * 2); g.fill(); }
    g.strokeStyle = "#5b4636"; g.lineWidth = 4; g.beginPath(); g.moveTo(ex - 16, ey - 20 - 10 * f.brows[s < 0 ? 0 : 1]); g.lineTo(ex + 16, ey - 20 - 10 * f.brows[0]); g.stroke();
  });
  // mouth: width from stretch/smile against rounding; opening from the lip gap; closure presses the lips
  const w = 34 * (1 + 0.35 * P.stretch + 0.25 * P.smile - 0.45 * P.mouthPucker - 0.25 * P.mouthFunnel);
  const h = Math.max(0.5, 2 * w * P.gap), my = 52 + jaw * 0.6, lipT = 5 + 3 * P.mouthFunnel - 2 * P.press;
  g.fillStyle = "#7a2230"; g.beginPath(); g.ellipse(0, my, w, h / 2 + 0.5, 0, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "#b5545e"; g.lineWidth = lipT; g.beginPath(); g.ellipse(0, my, w + 2, h / 2 + 3, 0, 0, Math.PI * 2); g.stroke();
  if (P.smile > 0.1) { g.strokeStyle = "#b5545e"; g.lineWidth = 2; g.beginPath(); g.moveTo(-w - 2, my); g.quadraticCurveTo(-w - 6, my - 8 * P.smile, -w - 4, my - 10 * P.smile); g.moveTo(w + 2, my); g.quadraticCurveTo(w + 6, my - 8 * P.smile, w + 4, my - 10 * P.smile); g.stroke(); }
  g.restore();
  g.fillStyle = "#64748b"; g.font = "12px system-ui"; g.fillText(t.toFixed(2) + " s · jaw " + f.jaw_rotation_deg.toFixed(1) + "° · yaw " + yaw.toFixed(1) + "°", 8, H - 8);
}

function vsePlay() {
  if (!VSE.motion) return;
  cancelAnimationFrame(VSE.raf);
  const a = $("#vse-player");
  const dur = VSE.motion.frames.length / VSE.motion.fps;
  let t0 = performance.now();
  if (VSE.audioUrl) { a.src = VSE.audioUrl; a.currentTime = 0; a.play().catch(() => {}); }
  const step = () => {
    const t = VSE.audioUrl && !a.paused ? a.currentTime : (performance.now() - t0) / 1000;
    vseDraw(Math.min(t, dur));
    if (t < dur) VSE.raf = requestAnimationFrame(step);
  };
  step();
}

// ---------------------------------------------------------------- lip reading and face analysis inside "Analyse video"
function vseRender(r) {
  let h = "";
  const v = r.vse;
  if (v && v.lipread) {
    h += '<h3>Lip-reading — Visual Speech Engine <span class="small muted">(' + esc(v.engine) + "; mouth models " + esc(v.class_models) + ")</span></h3>" +
      "<p><b>" + esc(v.lipread.text || "(nothing readable)") + "</b></p>" +
      v.lipread.segments.map(s => '<div class="small"><b>' + s.from_s.toFixed(2) + "–" + s.to_s.toFixed(2) + " s</b> (confidence " + Math.round(100 * s.confidence) + "%): " +
        s.words.map(w => "<b>" + esc(w.word) + "</b> " + Math.round(100 * w.confidence) + "%" + (w.same_on_lips.length ? ' <span class="muted">(or ' + esc(w.same_on_lips.slice(0, 4).join(", ")) + ")</span>" : "")).join(" · ") + "</div>").join("");
  }
  if (v && v.script) h += '<h3>Lips against the script — Visual Speech Engine: ' + v.script.agreement + '%</h3><div class="note ' + (v.script.agreement >= 40 ? "good" : "bad") + '">' + esc(v.script.verdict) +
    "</div><p>" + v.script.words.map(w => '<span class="vd-word ' + (w.agreement >= 0.6 ? "ok" : w.agreement >= 0.4 ? "warn" : "bad") + '" title="' + esc((w.from_s ?? "") + "–" + (w.to_s ?? "") + " s") + '">' + esc(w.word) + " " + Math.round(100 * w.agreement) + "%</span>").join(" ") + "</p>";
  const p = r.vps;
  if (p && p.frames_with_face) {
    const rows = [];
    if (p.head_pose_deg) rows.push(["Head pose (mean ± movement)", ["yaw", "pitch", "roll"].map(k => k + " " + p.head_pose_deg[k].mean + "° ±" + p.head_pose_deg[k].spread).join(", ")]);
    if (p.camera_motion) rows.push(["Camera / framing", p.camera_motion.verdict + " (shift " + p.camera_motion.mean_shift_per_frame + " per frame)"]);
    if (p.lighting_sh1) rows.push(["Lighting", "from " + p.lighting_sh1.from + ", " + p.lighting_sh1.evenness + " (ambient " + p.lighting_sh1.ambient + ", directional " + p.lighting_sh1.directional + ")"]);
    if (p.identity) rows.push(["Same face throughout", p.identity.same_face_throughout === null ? "too few neutral frames to say" : (p.identity.same_face_throughout ? "yes" : "NO — the face geometry changed") + " (drift " + p.identity.drift_between_halves + ")"]);
    if (rows.length) h += '<h3>Face analysis — Visual Speech Engine</h3><table class="tbl small">' + rows.map(x => "<tr><td>" + esc(x[0]) + "</td><td>" + esc(x[1]) + "</td></tr>").join("") + "</table>";
  }
  if (r.vse_error) h += '<p class="small muted">Visual Speech Engine: ' + esc(r.vse_error) + "</p>";
  return h;
}

// ---------------------------------------------------------------- benchmark
async function vseBench() {
  const btn = $("#vse-bench"); buttonStart(btn);
  let ok = false;
  try {
    const r = await vseJob("/api/vse/benchmark", {}, p => { $("#vse-bench-out").innerHTML = '<p class="small">Measuring… ' + (p.done || 0) + " of " + (p.total || "?") + " · " + esc(p.message || "") + "</p>"; });
    const s = r.synthetic, pc = x => x === null || x === undefined ? "—" : Math.round(100 * x) + "%";
    let h = '<table class="tbl small"><tr><th>Measure (synthetic speakers)</th><th>Lip-reading v1</th><th>Visual Speech Engine</th></tr>' +
      "<tr><td>Mouth shape read correctly, per frame</td><td>" + pc(s.frame_class_accuracy.v1) + "</td><td>" + pc(s.frame_class_accuracy.vse) + "</td></tr>" +
      "<tr><td>Word error rate (exact word, lower is better)</td><td>" + pc(s.word_error_rate.v1) + "</td><td>" + pc(s.word_error_rate.vse) + "</td></tr>" +
      "<tr><td>Look-alike word error rate (right lip pattern, lower is better)</td><td>" + pc(s.lookalike_group_error_rate.v1) + "</td><td>" + pc(s.lookalike_group_error_rate.vse) + "</td></tr>" +
      "<tr><td>Script check tells the right script from a wrong one</td><td>" + pc(s.script_check_separates_right_from_wrong.v1) + "</td><td>" + pc(s.script_check_separates_right_from_wrong.vse) + "</td></tr></table>" +
      '<p class="small muted">' + s.utterances + " utterances from " + s.speakers + " synthetic speakers. " + esc(s.note) + " " + r.seconds + " s.</p>";
    if (r.real) h += '<table class="tbl small"><tr><th>Your held-out recordings (' + r.real.held_out_recordings + ')</th><th>v1</th><th>VSE</th></tr>' +
      "<tr><td>Mouth shape read correctly, per frame</td><td>" + pc(r.real.frame_class_accuracy.v1) + "</td><td>" + pc(r.real.frame_class_accuracy.vse) + "</td></tr>" +
      "<tr><td>Lip-sync: synthesized mouth opening against your real mouth (correlation)</td><td>—</td><td>" + (r.real.lip_sync_mouth_opening_correlation ?? "—") + "</td></tr></table>";
    else h += '<p class="small muted">No recordings in the ingestion reservoir yet — teach it (step 5) to measure on your own face.</p>';
    $("#vse-bench-out").innerHTML = h;
    ok = true;
  } catch (e) { $("#vse-bench-out").innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; }
  finally { buttonEnd(btn, ok); }
}

// ---------------------------------------------------------------- lip-reading curriculum (1.47): five stages, scored stage by stage
async function vseCurriculum() {
  const btn = $("#vse-curr"), out = $("#vse-curr-out"); buttonStart(btn);
  let ok = false;
  try {
    const r = await vseJob("/api/vse/curriculum/run", {}, p => { out.innerHTML = '<p class="small">Reading… ' + (p.done || 0) + " of " + (p.total || "?") + " · " + esc(p.message || "") + "</p>"; });
    const pc = x => x === null || x === undefined ? "—" : Math.round(100 * x) + "%";
    let h = '<table class="tbl small"><tr><th>Stage</th><th>Clips</th><th>Told beforehand</th><th>Exact word</th><th>Right look-alike set</th><th>Says when words look alike</th></tr>' +
      r.stages.map(s => "<tr" + (r.weakest_stage && r.weakest_stage.stage === s.stage ? ' style="background:#fff4e5"' : "") + "><td>" + s.stage + ". " + esc(s.name) +
        '<div class="muted">' + esc(s.about) + "</div></td><td>" + s.clips + "</td><td>" + esc(s.told) + "</td><td>" + pc(s.strict) + "</td><td>" + pc(s.look_alike) + "</td><td>" + pc(s.alternatives_shown) + "</td></tr>").join("") + "</table>";
    if (r.weakest_stage) h += '<p class="small">Weakest stage: <b>' + r.weakest_stage.stage + ". " + esc(r.weakest_stage.name) + "</b> — the place to work first.</p>";
    h += '<details class="small"><summary>Every clip</summary><table class="tbl small"><tr><th>Clip</th><th>Said</th><th>Read</th><th>Exact</th><th>Look-alike</th></tr>' +
      r.items.map(i => "<tr><td>" + i.item + "</td><td>" + esc(i.script) + "</td><td>" + esc(i.text) + "</td><td>" + pc(i.strict) + "</td><td>" + pc(i.look_alike) + "</td></tr>").join("") + "</table></details>";
    out.innerHTML = h + '<p class="small muted">' + r.clips + " clips · " + esc(r.engine) + " · the same clips always give the same scores.</p>";
    ok = true;
  } catch (e) { out.innerHTML = '<div class="note bad">' + esc(e.message) + "</div>"; }
  finally { buttonEnd(btn, ok); }
}

document.addEventListener("DOMContentLoaded", () => {
  if (!$("#vse-card")) return;
  if ($("#vse-curr")) $("#vse-curr").onclick = vseCurriculum;
  $("#vse-go").onclick = vseLipSync;
  $("#vse-play").onclick = vsePlay;
  $("#vse-bench").onclick = vseBench;
});
