// Permanent QC battery (spec §6 step 8, §14 covenant QA): a deterministic
// self-check per installed language, surfaced in the System Monitor. It asserts
// the covenant — no translated word without a source, coverage always reported,
// identical input → identical output — plus pack integrity, round-trips,
// transliteration and pronunciation. Voice availability is injected by the
// platform layer because it depends on the device.

import { validatePack } from './lexicon.js';
import { hasRules } from './g2p.js';
import { formKey } from './tokenize.js';

const NONSENSE = 'Xq7zzv qwpkjh';

export function runBattery(engine, lang, { voiceCheck = null, partner = null } = {}) {
  const checks = [];
  const add = (id, label, pass, detail, severity = 'fail') => checks.push({ id, label, pass, detail, severity: pass ? 'pass' : severity });
  const lex = engine.lexicons.get(lang);
  if (!lex) {
    add('pack', 'Dictionary pack installed', false, `No ${lang} pack loaded — text LID by script, transliteration and device voices still work.`, 'warn');
    return summarize(lang, checks);
  }

  const problems = lex.packs.flatMap((p) => validatePack(p).map((x) => `${p.id}: ${x}`));
  add('integrity', 'Pack integrity', problems.length === 0, problems.length ? problems.slice(0, 3).join('; ') : `${lex.packs.length} pack(s), ${lex.entryCount} entries valid`);

  // Every primary form must be indexed back to its own concept. Homographs
  // ("no" = no / not) are allowed: the concept only has to be among the candidates.
  let selfOk = 0;
  let selfTotal = 0;
  const misses = [];
  for (const pack of lex.packs) {
    for (const e of pack.entries) {
      const form = e.f[0];
      if (!form) continue;
      selfTotal++;
      const key = formKey(form, (w) => lex.lower(w));
      const hit = lex.lookup(key) || lex.lookupChars(key);
      if (hit && hit.cands.some((c) => c.concept === e.c)) selfOk++;
      else if (misses.length < 3) misses.push(`${e.c} “${form}”`);
    }
  }
  add('self-match', 'Every entry resolves to its own concept', selfOk === selfTotal, `${selfOk}/${selfTotal}${misses.length ? ' — misses: ' + misses.join(', ') : ''}`);

  // Covenant: unknown input is never translated, always flagged, coverage 0.
  const target = partner && engine.lexicons.has(partner) ? partner : lang;
  const nonsense = engine.translate({ text: NONSENSE, src: lang, tgt: target });
  const fabricated = nonsense.segments.filter((s) => (s.kind === 'word' || s.kind === 'phrase') && !s.provenance?.source);
  add('covenant-unknown', 'Unknown words pass through flagged (no fabrication)', nonsense.coverage.percent === 0 && fabricated.length === 0 && nonsense.segments.filter((s) => s.kind === 'unknown').every((s) => s.flagged && s.target === s.source), `coverage ${nonsense.coverage.percent}% on nonsense input`);

  // Covenant: every rendered word carries a dictionary source.
  const sample = lex.packs[0].entries.slice(0, 12).map((e) => e.f[0]).filter(Boolean).join(' ');
  const s1 = engine.translate({ text: sample, src: lang, tgt: target });
  const unsourced = s1.segments.filter((s) => ['word', 'phrase', 'omitted'].includes(s.kind) && !(s.provenance && s.provenance.source && s.provenance.target));
  add('covenant-provenance', 'Every rendered word has provenance', unsourced.length === 0, unsourced.length ? `${unsourced.length} unsourced segment(s)` : `${s1.segments.length} segments, all sourced or flagged`);
  add('coverage-reported', 'Coverage always reported', typeof s1.coverage.percent === 'number' && s1.coverage.percent >= 0 && s1.coverage.percent <= 100, `${s1.coverage.percent}% on sample`);

  // Determinism.
  const s2 = engine.translate({ text: sample, src: lang, tgt: target });
  add('deterministic', 'Identical input → identical output', s1.fingerprint === s2.fingerprint, `fingerprint ${s1.fingerprint}`);

  // Round trip through a partner language over shared concepts.
  if (partner && engine.lexicons.has(partner) && partner !== lang) {
    let ok = 0;
    let n = 0;
    const pLex = engine.lexicons.get(partner);
    for (const e of lex.packs[0].entries) {
      if (!e.f[0] || !pLex.concepts.has(e.c)) continue;
      const there = engine.translate({ text: e.f[0], src: lang, tgt: partner });
      const seg = there.segments.find((s) => s.concept);
      if (!seg || there.segments.filter((s) => s.concept).length !== 1 || seg.kind === 'omitted') continue;
      n++;
      const back = engine.translate({ text: there.output, src: partner, tgt: lang });
      if (back.segments.some((s) => s.concept === e.c) || back.segments.some((s) => s.concept && lex.render(s.concept)?.form === lex.render(e.c)?.form)) ok++;
      if (n >= 40) break;
    }
    const pct = n ? Math.round((ok / n) * 100) : 100;
    add('round-trip', `Round trip via ${partner}`, pct >= 85, `${ok}/${n} concepts survive ${lang}→${partner}→${lang} (${pct}%)`, 'warn');
  }

  const caps = engine.capabilities(lang);
  if (caps.transliteration) {
    const first = lex.packs[0].entries.find((e) => e.f[0])?.f[0] || '';
    const tr = engine.transliterate(first, lang);
    add('transliteration', 'Transliteration available or refused honestly', tr.ok ? tr.text.length > 0 : typeof tr.reason === 'string', tr.ok ? `${first} → ${tr.text} (${tr.scheme})` : tr.reason, tr.ok ? 'fail' : 'warn');
  }
  if (hasRules(lang)) {
    const word = lex.packs[0].entries.map((e) => e.r ? Object.values(e.r)[0] : e.f[0]).find((f) => f && f.length > 2) || '';
    const p = engine.pronounce(word, lang);
    add('pronunciation', 'IPA produced with sane syllable count', p.ok && p.ipa.length > 0 && (p.syllables === null || (p.syllables >= 1 && p.syllables <= [...word].length)), p.ok ? `${word} → /${p.ipa}/` : p.reason);
  }
  if (voiceCheck) {
    const v = voiceCheck(lang);
    add('voice', 'Real device voice available', !!v.ok, v.detail, 'warn');
  }
  return summarize(lang, checks);
}

function summarize(lang, checks) {
  const failed = checks.filter((c) => c.severity === 'fail').length;
  const passed = checks.filter((c) => c.pass).length;
  return { lang, checks, passed, total: checks.length, failed, score: checks.length ? Math.round((passed / checks.length) * 100) : 0 };
}
