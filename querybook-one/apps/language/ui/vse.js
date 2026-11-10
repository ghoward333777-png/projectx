"use strict";
// Visual Speech Engine: lip reading inside "Analyse video", the benchmark against lip-reading v1 and the lip-reading curriculum.
// (1.52: nothing here moves a face — every speaking face is a talking clip made by Gemini or HeyGen, see talk.js.)
const VSE = {};

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
    if (r.held_out) h = '<p class="small"><b>Honest score</b> — ' + esc(r.held_out.about) + ':</p><table class="tbl small"><tr><th>Stage</th><th>Exact word</th><th>Right look-alike set</th><th>Says when words look alike</th></tr>' +
      r.held_out.stages.map(s => "<tr><td>" + s.stage + ". " + esc(s.name) + "</td><td>" + pc(s.strict) + "</td><td>" + pc(s.look_alike) + "</td><td>" + pc(s.alternatives_shown) + "</td></tr>").join("") + "</table>" +
      '<p class="small muted">Below: the shipped models (' + esc(r.models) + ') on the same clips — they were trained on these clips, so this is not a fair score.</p>' + h;
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
  $("#vse-bench").onclick = vseBench;
});
