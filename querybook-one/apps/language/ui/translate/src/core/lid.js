// Text language ID (spec §4.1): every installed dictionary scores the text;
// script evidence ranks languages that have no pack yet. Returns a ranked list
// with a confidence value; low confidence means "ask the user", never a silent
// guess. Dialect evidence comes from dialect-specific dictionary forms.

import { tokenize } from './tokenize.js';
import { segment } from './mt.js';
import { scriptCounts, baseScripts } from './scripts.js';

// Below this the user is asked to confirm; real ties ("no", "merci") score ~0.
export const CONFIRM_BELOW = 0.4;

/**
 * @param {string} text normalized text
 * @param {{languages: Array, lexicons: Map<string, import('./lexicon.js').Lexicon>, scriptFor?: (lang)=>string[]}} ctx
 */
export function detectLanguage(text, ctx) {
  const counts = scriptCounts(text);
  const letters = Object.values(counts).reduce((a, b) => a + b, 0);
  if (letters === 0) return { ranked: [], best: null, confidence: 0, needsConfirmation: true, dialect: null, scripts: counts, reason: 'No letters to identify.' };

  const scriptsOf = (lang) => {
    const all = new Set(baseScripts(lang.script));
    for (const d of lang.dialects) if (d[2]) baseScripts(d[2]).forEach((s) => all.add(s));
    return all;
  };
  const fitFor = (lang) => {
    const own = scriptsOf(lang);
    let n = 0;
    for (const [s, c] of Object.entries(counts)) if (own.has(s)) n += c;
    return n / letters;
  };
  // A script is "unique" when exactly one registry language writes it by default (Hangul → Korean).
  const writers = {};
  for (const l of ctx.languages) for (const s of scriptsOf(l)) (writers[s] = writers[s] || []).push(l.code);

  const tokens = tokenize(text);
  const scored = [];
  for (const lang of ctx.languages) {
    const fit = fitFor(lang);
    if (fit === 0) continue;
    const lex = ctx.lexicons.get(lang.code);
    if (lex && lex.entryCount > 0) {
      const segs = segment(tokens, lex);
      let known = 0;
      let total = 0;
      const dialects = {};
      let lexical = 0;
      for (const s of segs) {
        total += s.weight;
        if (s.cand) {
          // Exact dictionary hits are strong evidence; inflection, compound and
          // accent-insensitive matches are weaker (they also fire on cognates).
          known += s.how === 'exact' ? s.weight : s.weight * 0.5;
          lexical++;
          if (s.cand.dialect) dialects[s.cand.dialect] = (dialects[s.cand.dialect] || 0) + 1;
        }
      }
      const hit = total ? known / total : 0;
      scored.push({ lang: lang.code, score: fit * (0.25 + 0.75 * hit), fit, hit, method: 'dictionary', dialects, lexical });
    } else {
      const dominant = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0];
      const unique = (writers[dominant] || []).length === 1 && writers[dominant][0] === lang.code;
      const tierWeight = lang.tier === 1 ? 1 : lang.tier === 2 ? 0.96 : 0.92;
      scored.push({ lang: lang.code, score: fit * (unique ? 0.7 : 0.2) * tierWeight, fit, hit: null, method: unique ? 'unique script' : 'script only', dialects: {}, lexical: 0 });
    }
  }
  scored.sort((a, b) => b.score - a.score || a.lang.localeCompare(b.lang));
  const [top, second] = scored;
  let confidence = 0;
  if (top && top.score > 0) confidence = ((top.score - (second ? second.score : 0)) / top.score) * Math.min(1, top.score / 0.7);
  confidence = Math.round(confidence * 100) / 100;

  let dialect = null;
  if (top) {
    const ev = Object.entries(top.dialects).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    if (ev.length) dialect = { tag: ev[0][0], evidence: ev[0][1], confidence: Math.round((ev[0][1] / Math.max(1, top.lexical)) * 100) / 100 };
    if (!dialect) {
      const lang = ctx.languages.find((l) => l.code === top.lang);
      // Script-variant dialects (zh-TW Traditional, sr-Latn, pa-PK Shahmukhi) are decidable from orthography alone.
      const byScript = lang?.dialects.filter((d) => d[2] && baseScripts(d[2]).some((s) => counts[s]));
      if (byScript && byScript.length === 1 && lang.dialects.some((d) => d[2] && d[2] !== byScript[0][2])) dialect = { tag: byScript[0][0], evidence: 0, confidence: 0.6 };
    }
  }
  return {
    ranked: scored.slice(0, 5).map((s) => ({ lang: s.lang, score: Math.round(s.score * 1000) / 1000, method: s.method, hit: s.hit })),
    best: top ? top.lang : null,
    confidence,
    needsConfirmation: confidence < CONFIRM_BELOW,
    dialect,
    scripts: counts,
  };
}
