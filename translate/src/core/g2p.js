// Rule-seeded grapheme-to-phoneme (spec §6 step 6): phrase-level IPA with
// syllables and, where the orthography decides it, stress. The ladder is:
// dictionary pronunciation → language rule table → honest refusal. Stress is
// marked only where a rule decides it; it is never guessed.

import { kanaMorae } from './translit.js';

const PHONEMIC_NOTE = 'phonemic (broad) transcription';

// ---------- Spanish ----------
const ES_ONSETS = new Set(['pl', 'pɾ', 'bl', 'bɾ', 'fl', 'fɾ', 'kl', 'kɾ', 'ɡl', 'ɡɾ', 'tɾ', 'dɾ', 'tl']);
function spanishPhones(word, dialect) {
  const seseo = !(dialect === 'es-ES' || !dialect);
  const w = word.toLowerCase();
  const ph = []; // {p, v (vowel), acc (written accent)}
  const isFront = (c) => c && 'eiéí'.includes(c);
  for (let i = 0; i < w.length; i++) {
    const c = w[i];
    const n = w[i + 1];
    const vow = { a: 'a', e: 'e', i: 'i', o: 'o', u: 'u', á: 'a', é: 'e', í: 'i', ó: 'o', ú: 'u', ü: 'u' };
    if (c in vow) { ph.push({ p: vow[c], v: true, acc: 'áéíóú'.includes(c), weak: 'iuü'.includes(c) }); continue; }
    switch (c) {
      case 'c': if (n === 'h') { ph.push({ p: 'tʃ' }); i++; } else ph.push({ p: isFront(n) ? (seseo ? 's' : 'θ') : 'k' }); break;
      case 'l': if (n === 'l') { ph.push({ p: 'ʝ' }); i++; } else ph.push({ p: 'l' }); break;
      case 'r': if (n === 'r') { ph.push({ p: 'r' }); i++; } else ph.push({ p: i === 0 || 'lns'.includes(w[i - 1]) ? 'r' : 'ɾ' }); break;
      case 'q': ph.push({ p: 'k' }); if (n === 'u') i++; break;
      case 'g': if (n === 'u' && isFront(w[i + 2])) { ph.push({ p: 'ɡ' }); i++; } else ph.push({ p: isFront(n) ? 'x' : 'ɡ' }); break;
      case 'z': ph.push({ p: seseo ? 's' : 'θ' }); break;
      case 'j': ph.push({ p: 'x' }); break;
      case 'h': break;
      case 'ñ': ph.push({ p: 'ɲ' }); break;
      case 'v': case 'b': ph.push({ p: 'b' }); break;
      case 'x': if (i === 0) ph.push({ p: 's' }); else { ph.push({ p: 'k' }); ph.push({ p: 's' }); } break;
      case 'y': if (i === w.length - 1 || !(n in vow)) ph.push({ p: 'i', v: true, weak: true }); else ph.push({ p: 'ʝ' }); break;
      case 'w': ph.push({ p: 'w' }); break;
      default: if (/[a-z]/.test(c)) ph.push({ p: c === 'g' ? 'ɡ' : c });
    }
  }
  // Unstressed weak vowels next to another vowel become glides (diphthongs).
  for (let i = 0; i < ph.length; i++) {
    const x = ph[i];
    if (!x.v || !x.weak || x.acc) continue;
    const prevV = ph[i - 1] && ph[i - 1].v && !ph[i - 1].glide;
    const nextV = ph[i + 1] && ph[i + 1].v;
    if (nextV || prevV) { x.v = false; x.glide = true; x.p = x.p === 'i' ? 'j' : 'w'; }
  }
  return ph;
}

function syllabify(ph, onsets, sOnsetSplit = false) {
  const nuclei = ph.map((x, i) => (x.v ? i : -1)).filter((i) => i >= 0);
  if (nuclei.length === 0) return [ph];
  const sylls = [];
  let start = 0;
  for (let k = 0; k < nuclei.length; k++) {
    const nuc = nuclei[k];
    const next = nuclei[k + 1];
    if (next === undefined) { sylls.push(ph.slice(start)); break; }
    // consonants strictly between nuclei (glides stay with the nucleus side they touch)
    const cons = ph.slice(nuc + 1, next);
    let split;
    const n = cons.length;
    if (n <= 1) split = nuc + 1;
    else {
      const lastTwo = cons.slice(-2).map((c) => c.p).join('');
      if (sOnsetSplit && cons[0].p === 's' && n >= 2) split = nuc + 1;
      else if (onsets.has(lastTwo)) split = next - 2;
      else split = next - 1;
      if (cons[cons.length - 1].glide) split = Math.min(split, next - (onsets.has(cons.slice(-3, -1).map((c) => c.p).join('')) ? 3 : 2));
    }
    sylls.push(ph.slice(start, split));
    start = split;
  }
  return sylls.filter((s) => s.length);
}

function spanish(word, dialect) {
  const ph = spanishPhones(word, dialect);
  const sylls = syllabify(ph, ES_ONSETS);
  let stress = sylls.findIndex((s) => s.some((x) => x.acc));
  let rule = 'written accent';
  if (stress < 0) {
    const last = word.toLowerCase().slice(-1);
    stress = /[aeiouns]/.test(last) ? Math.max(0, sylls.length - 2) : sylls.length - 1;
    rule = /[aeiouns]/.test(last) ? 'ends in vowel, n or s → penultimate' : 'ends in consonant → final';
  }
  return { sylls: sylls.map((s) => s.map((x) => x.p).join('')), stress, rule };
}

// ---------- Italian ----------
const IT_ONSETS = new Set(['pl', 'pr', 'bl', 'br', 'fl', 'fr', 'kl', 'kr', 'ɡl', 'ɡr', 'tr', 'dr', 'vr']);
function italian(word) {
  const w = word.toLowerCase();
  const ph = [];
  const front = (c) => c && 'eiéèì'.includes(c);
  const vow = { a: 'a', e: 'e', i: 'i', o: 'o', u: 'u', à: 'a', è: 'ɛ', é: 'e', ì: 'i', ò: 'ɔ', ó: 'o', ù: 'u' };
  for (let i = 0; i < w.length; i++) {
    const c = w[i];
    const n = w[i + 1];
    const after = w[i + 2];
    if (c in vow) {
      // silent i in ci/gi/sci/gli + vowel handled at the consonant
      ph.push({ p: vow[c], v: true, acc: 'àèéìòóù'.includes(c) });
      continue;
    }
    const gem = n === c && c !== 'h';
    const prevVowel = () => ph.length > 0 && ph[ph.length - 1].v;
    // ʎ ɲ ʃ are inherently long between vowels (fiʎ.ʎo), short word-initially.
    const long = (p) => { if (prevVowel()) ph.push({ p }); ph.push({ p }); };
    const push = (p) => { if (gem) { ph.push({ p }); ph.push({ p }); i++; } else ph.push({ p }); };
    switch (c) {
      case 'c': {
        if (gem) { const f = front(after); ph.push({ p: f ? 't' : 'k' }); ph.push({ p: f ? 'tʃ' : 'k' }); i++; if (f && after === 'i' && w[i + 2] in vow) i++; break; }
        if (n === 'h') { ph.push({ p: 'k' }); i++; break; }
        if (front(n)) { ph.push({ p: 'tʃ' }); if (n === 'i' && after in vow) i++; break; }
        ph.push({ p: 'k' });
        break;
      }
      case 'g': {
        if (n === 'l' && after === 'i') { long('ʎ'); i += w[i + 3] in vow ? 2 : 1; break; }
        if (n === 'n') { long('ɲ'); i++; break; }
        if (gem) { const f = front(after); ph.push({ p: f ? 'd' : 'ɡ' }); ph.push({ p: f ? 'dʒ' : 'ɡ' }); i++; if (f && after === 'i' && w[i + 2] in vow) i++; break; }
        if (n === 'h') { ph.push({ p: 'ɡ' }); i++; break; }
        if (front(n)) { ph.push({ p: 'dʒ' }); if (n === 'i' && after in vow) i++; break; }
        ph.push({ p: 'ɡ' });
        break;
      }
      case 's':
        if (n === 'c' && front(after)) { long('ʃ'); i++; if (after === 'i' && w[i + 2] in vow) i++; break; }
        push('s');
        break;
      case 'q': ph.push({ p: 'k' }); if (n === 'u') { ph.push({ p: 'w' }); i++; } break;
      case 'z': if (gem || (prevVowel() && n in vow)) ph.push({ p: 't' }); ph.push({ p: 'ts' }); if (gem) i++; break;
      case 'h': break;
      case 'r': push('r'); break;
      default: if (/[a-z]/.test(c)) push(c === 'j' ? 'j' : c);
    }
  }
  for (let i = 0; i < ph.length; i++) {
    const x = ph[i];
    if (x.v && !x.acc && (x.p === 'i' || x.p === 'u') && ph[i + 1] && ph[i + 1].v) { x.v = false; x.glide = true; x.p = x.p === 'i' ? 'j' : 'w'; }
  }
  const sylls = syllabify(ph, IT_ONSETS, true);
  const stress = sylls.findIndex((s) => s.some((x) => x.acc));
  return {
    sylls: sylls.map((s) => s.map((x) => x.p).join('')),
    stress,
    rule: stress >= 0 ? 'written accent' : 'stress not written — not marked',
  };
}

// ---------- Japanese (kana) ----------
const JA_CONS = { k: 'k', g: 'ɡ', s: 's', z: 'z', t: 't', d: 'd', n: 'n', h: 'h', b: 'b', p: 'p', m: 'm', r: 'ɾ', w: 'w', f: 'ɸ', v: 'v', j: 'dʑ' };
function japaneseMora(r) {
  const special = { shi: 'ɕi', chi: 'tɕi', tsu: 'tsɯ', fu: 'ɸɯ', ji: 'dʑi', hi: 'çi', ni: 'ɲi', u: 'ɯ' };
  if (r in special) return special[r];
  let m = r.match(/^(sh|ch|ts|j)([aueo])$/);
  if (m) return { sh: 'ɕ', ch: 'tɕ', ts: 'ts', j: 'dʑ' }[m[1]] + (m[2] === 'u' ? 'ɯ' : m[2]);
  m = r.match(/^([kgnhbpmr])y([aueo])$/);
  if (m) return (m[1] === 'n' ? 'ɲ' : m[1] === 'h' ? 'ç' : (JA_CONS[m[1]] + 'j')) + (m[2] === 'u' ? 'ɯ' : m[2]);
  m = r.match(/^([a-z]*?)([aiueo])$/);
  if (m) {
    const cons = m[1];
    const v = m[2] === 'u' ? 'ɯ' : m[2];
    if (cons === '') return v;
    if (cons.length === 2 && cons[0] === cons[1]) return JA_CONS[cons[0]] + 'ː' + v;
    if (cons.startsWith('t') && cons.length > 1) return 'tː' + japaneseMora(cons.slice(1) + m[2]).replace(/^t/, '');
    return (JA_CONS[cons] || cons) + v;
  }
  return r;
}
function japanese(text) {
  const morae = kanaMorae(text);
  if (morae.some((m) => m.other && /\p{Script=Han}/u.test(m.r))) return null;
  const sylls = [];
  for (const m of morae) {
    if (m.other) continue;
    if (m.long) { if (sylls.length) sylls[sylls.length - 1] += 'ː'; continue; }
    if (m.n) { sylls.push('ɴ'); continue; }
    sylls.push(japaneseMora(m.r));
  }
  return { sylls, stress: -1, rule: 'pitch accent not marked', unit: 'mora' };
}

// ---------- Korean ----------
const KO_L = ['k', 'k\u0348', 'n', 't', 't\u0348', 'ɾ', 'm', 'p', 'p\u0348', 's', 's\u0348', '', 'tɕ', 'tɕ\u0348', 'tɕʰ', 'kʰ', 'tʰ', 'pʰ', 'h'];
const KO_V = ['a', 'ɛ', 'ja', 'jɛ', 'ʌ', 'e', 'jʌ', 'je', 'o', 'wa', 'wɛ', 'we', 'jo', 'u', 'wʌ', 'we', 'wi', 'ju', 'ɯ', 'ɰi', 'i'];
const KO_T = ['', 'k\u031A', 'k\u031A', 'k\u031A', 'n', 'n', 'n', 't\u031A', 'l', 'k\u031A', 'm', 'l', 'l', 'l', 'p\u031A', 'l', 'm', 'p\u031A', 'p\u031A', 't\u031A', 't\u031A', 'ŋ', 't\u031A', 't\u031A', 'k\u031A', 't\u031A', 'p\u031A', 't\u031A'];
const KO_T_LIAISON = ['', 'ɡ', 'k\u0348', 'k', 'n', 'n', 'n', 'd', 'ɾ', 'ɡ', 'm', 'b', 's', 'tʰ', 'pʰ', 'ɾ', 'm', 'b', 's', 's', 's\u0348', 'ŋ', 'dʑ', 'tɕʰ', 'kʰ', 'tʰ', 'pʰ', ''];
function korean(text) {
  const chars = [...text].filter((c) => { const x = c.codePointAt(0) - 0xAC00; return x >= 0 && x <= 11171; });
  if (!chars.length) return null;
  const parts = chars.map((c) => { const x = c.codePointAt(0) - 0xAC00; return { L: Math.floor(x / 588), V: Math.floor((x % 588) / 28), T: x % 28 }; });
  const sylls = parts.map((p, i) => {
    const next = parts[i + 1];
    const prev = parts[i - 1];
    let onset = KO_L[p.L];
    if (prev && prev.T && p.L === 11) onset = KO_T_LIAISON[prev.T];
    else if (prev && prev.T === 8 && p.L === 5) onset = 'l';
    else if (prev && (!prev.T || [4, 5, 6, 8, 16, 21].includes(prev.T)) && [0, 3, 7, 12].includes(p.L)) onset = { 0: 'ɡ', 3: 'd', 7: 'b', 12: 'dʑ' }[p.L]; // lenis voicing between vowels
    let coda = next && next.L === 11 ? '' : KO_T[p.T];
    if (next && (next.L === 2 || next.L === 6)) coda = { 'k\u031A': 'ŋ', 't\u031A': 'n', 'p\u031A': 'm' }[coda] ?? coda;
    return onset + KO_V[p.V] + coda;
  });
  return { sylls, stress: -1, rule: 'Korean has no lexical stress', unit: 'syllable block' };
}

// ---------- Hindi (Devanagari) ----------
const HI_CONS = { क: 'k', ख: 'kʰ', ग: 'ɡ', घ: 'ɡʱ', ङ: 'ŋ', च: 'tʃ', छ: 'tʃʰ', ज: 'dʒ', झ: 'dʒʱ', ञ: 'ɲ', ट: 'ʈ', ठ: 'ʈʰ', ड: 'ɖ', ढ: 'ɖʱ', ण: 'ɳ', त: 't\u032A', थ: 't\u032Aʰ', द: 'd\u032A', ध: 'd\u032Aʱ', न: 'n', प: 'p', फ: 'pʰ', ब: 'b', भ: 'bʱ', म: 'm', य: 'j', र: 'ɾ', ल: 'l', व: 'ʋ', श: 'ʃ', ष: 'ʃ', स: 's', ह: 'ɦ' };
const HI_NUKTA = { क: 'q', ख: 'x', ग: 'ɣ', ज: 'z', ड: 'ɽ', ढ: 'ɽʱ', फ: 'f' };
const HI_VOW = { अ: 'ə', आ: 'aː', इ: 'ɪ', ई: 'iː', उ: 'ʊ', ऊ: 'uː', ऋ: 'ɾɪ', ए: 'eː', ऐ: 'ɛː', ओ: 'oː', औ: 'ɔː', ऑ: 'ɔ' };
const HI_SIGN = { 'ा': 'aː', 'ि': 'ɪ', 'ी': 'iː', '\u0941': 'ʊ', '\u0942': 'uː', '\u0943': 'ɾɪ', '\u0947': 'eː', '\u0948': 'ɛː', 'ो': 'oː', 'ौ': 'ɔː', 'ॉ': 'ɔ' };
function hindi(word) {
  const chars = [...word];
  const seg = []; // {p, v, schwa}
  for (let i = 0; i < chars.length; i++) {
    const c = chars[i];
    if (c in HI_CONS) {
      let p = HI_CONS[c];
      if (chars[i + 1] === '\u093C') { p = HI_NUKTA[c] || p; i++; }
      seg.push({ p });
      const n = chars[i + 1];
      if (n in HI_SIGN) { seg.push({ p: HI_SIGN[n], v: true }); i++; }
      else if (n === '\u094D') { i++; }
      else seg.push({ p: 'ə', v: true, schwa: true });
    } else if (c in HI_VOW) seg.push({ p: HI_VOW[c], v: true });
    else if (c === '\u0902' || c === '\u0901') { const last = [...seg].reverse().find((x) => x.v); if (last) last.p += '\u0303'; }
    else if (c === 'ः') seg.push({ p: 'ɦ' });
  }
  // Schwa deletion: word-final, then V C ə C V medially (Ohala's rule, applied right to left).
  const last = seg[seg.length - 1];
  if (last && last.schwa && seg.length > 2) seg.pop();
  for (let i = seg.length - 2; i >= 2; i--) {
    const x = seg[i];
    if (x.schwa && seg[i - 2] && seg[i - 2].v && !seg[i - 1].v && seg[i + 1] && !seg[i + 1].v && seg[i + 2] && seg[i + 2].v) seg.splice(i, 1);
  }
  const sylls = syllabify(seg, new Set());
  return { sylls: sylls.map((s) => s.map((x) => x.p).join('')), stress: -1, rule: 'stress not marked' };
}

const RULES = {
  es: { name: 'Spanish rule table', fn: (w, d) => spanish(w, d), script: /\p{Script=Latin}/u },
  it: { name: 'Italian rule table', fn: (w) => italian(w), script: /\p{Script=Latin}/u },
  ja: { name: 'Japanese kana table', fn: null, script: /[\p{Script=Hiragana}\p{Script=Katakana}]/u },
  ko: { name: 'Korean Hangul rules', fn: null, script: /\p{Script=Hangul}/u },
  hi: { name: 'Hindi Devanagari rules', fn: (w) => hindi(w), script: /\p{Script=Devanagari}/u },
};

export function hasRules(lang) {
  return lang in RULES;
}

function render(words) {
  return words.map((w) => w.sylls.map((s, i) => (w.stress === i && w.sylls.length > 1 ? 'ˈ' : '') + s).join('.')).join(' ');
}

/**
 * Pronounce a phrase.
 * @param {string} text phrase in the language's script
 * @param {object} opts {dialect, dictionaryIpa, reading}
 * @returns {{ok:true, ipa, syllables, method, notes} | {ok:false, reason}}
 */
export function pronounce(text, lang, { dialect = null, dictionaryIpa = null, reading = null } = {}) {
  if (dictionaryIpa) return { ok: true, ipa: dictionaryIpa, syllables: null, method: 'dictionary pronunciation', notes: [] };
  const rule = RULES[lang];
  if (!rule) return { ok: false, reason: `No pronunciation rule table for ${lang} yet — showing transliteration instead.` };
  const words = (reading || text).split(/[\s\p{P}]+/u).filter(Boolean);
  if (lang === 'ja') {
    const r = japanese((reading || text).replace(/[\s\p{P}]+/gu, ''));
    if (!r) return { ok: false, reason: 'Kanji need a dictionary reading; none available for this text.' };
    return { ok: true, ipa: r.sylls.join('.'), syllables: r.sylls.length, method: rule.name + (reading ? ' (from dictionary reading)' : ''), notes: [r.rule, PHONEMIC_NOTE] };
  }
  if (lang === 'ko') {
    const out = words.map((w) => korean(w)).filter(Boolean);
    if (!out.length) return { ok: false, reason: 'No Hangul to pronounce.' };
    return { ok: true, ipa: out.map((w) => w.sylls.join('.')).join(' '), syllables: out.reduce((n, w) => n + w.sylls.length, 0), method: rule.name, notes: [out[0].rule, PHONEMIC_NOTE] };
  }
  const usable = words.filter((w) => rule.script.test(w));
  if (!usable.length) return { ok: false, reason: 'The text is not in the script this rule table reads.' };
  const out = usable.map((w) => rule.fn(w, dialect));
  const rules = [...new Set(out.map((w) => w.rule))];
  return { ok: true, ipa: render(out), syllables: out.reduce((n, w) => n + w.sylls.length, 0), method: rule.name + (lang === 'es' && dialect ? ` (${dialect === 'es-ES' ? 'distinción' : 'seseo'})` : ''), notes: [...rules, PHONEMIC_NOTE] };
}
