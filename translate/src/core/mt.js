// Deterministic dictionary MT through the concept pivot (spec §6 step 5).
// Known words and phrases are rendered from a dictionary entry, with their
// alternatives and provenance. Unknown words are passed through and flagged;
// nothing is ever invented. Coverage is the share of the source's letters that
// were translated from a known source.

import { tokenize, letterWeight } from './tokenize.js';
import { pickCandidate } from './lexicon.js';
import { isUnspaced, isCased } from './scripts.js';

const NEUTRAL_PUNCT = { '？': '?', '！': '!', '。': '.', '、': ',', '，': ',', '：': ':', '；': ';', '؟': '?', '،': ',', '؛': ';', '।': '.', '॥': '.', '።': '.', '፣': ',', '፧': '?', '¿': '', '¡': '', '«': '"', '»': '"', '„': '"', '“': '"', '”': '"', '「': '"', '」': '"' };

const TARGET_PUNCT = {
  Hans: { '?': '？', '!': '！', ',': '，', '.': '。', ':': '：', ';': '；' },
  Hant: { '?': '？', '!': '！', ',': '，', '.': '。', ':': '：', ';': '；' },
  Jpan: { '?': '？', '!': '！', ',': '、', '.': '。' },
  Arab: { '?': '؟', ',': '،', ';': '؛' },
  Deva: { '.': '।' },
  Beng: { '.': '।' },
  Ethi: { '.': '።', ',': '፣' },
};

const CLOSING = new Set(['.', ',', '?', '!', ':', ';', ')', ']', '}', '%', '。', '，', '、', '？', '！', '：', '；', '؟', '،', '؛', '।', '።', '፣', '"']);
const OPENING = new Set(['(', '[', '{', '¿', '¡']);

/**
 * Segment source tokens against a lexicon. Shared by MT and language ID.
 * @returns {Array<{kind, source, start, end, weight, cand?, how?}>}
 */
export function segment(tokens, lex, { domain = null, dialect = null } = {}) {
  const segs = [];
  let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];
    if (tok.type === 'n') { segs.push({ kind: 'number', source: tok.text, tok, weight: 0 }); i++; continue; }
    if (tok.type === 'p') { segs.push({ kind: 'punct', source: tok.text, tok, weight: 0 }); i++; continue; }
    if (tok.unspaced) { segmentChars(tok, lex, domain, dialect, segs); i++; continue; }

    // Longest n-gram over consecutive spaced word tokens.
    let matched = false;
    const limit = Math.min(lex ? lex.maxTokens : 1, tokens.length - i);
    for (let n = limit; n >= 1 && lex; n--) {
      const span = tokens.slice(i, i + n);
      if (span.some((t, k) => t.type !== 'w' || t.unspaced || (k > 0 && !t.space))) continue;
      const key = span.map((t) => lex.lower(t.text)).join(' ');
      const hit = lex.lookup(key);
      if (hit) {
        const source = span.map((t, k) => (k ? ' ' : '') + t.text).join('');
        segs.push({ kind: n > 1 ? 'phrase' : 'word', source, tok: span[0], weight: letterWeight(source), cand: pickCandidate(hit.cands, domain, dialect), how: hit.how, tokens: n });
        i += n;
        matched = true;
        break;
      }
    }
    if (matched) continue;
    const inflected = lex ? stripInflection(tok.text, lex) : null;
    if (inflected) {
      segs.push({ kind: 'word', source: tok.text, tok, weight: letterWeight(tok.text), cand: pickCandidate(inflected.cands, domain, dialect), how: inflected.how });
      i++;
      continue;
    }
    const pieces = lex ? splitWord(tok.text, lex) : null;
    if (pieces) {
      pieces.forEach((p, k) => segs.push({ kind: 'word', source: p.text, tok: k === 0 ? tok : { ...tok, space: false }, weight: letterWeight(p.text), cand: pickCandidate(p.cands, domain, dialect), how: p.how }));
    } else {
      segs.push({ kind: 'unknown', source: tok.text, tok, weight: letterWeight(tok.text) });
    }
    i++;
  }
  return segs;
}

function segmentChars(tok, lex, domain, dialect, segs) {
  const chars = [...tok.text];
  let j = 0;
  let unknown = '';
  let first = true;
  const flush = () => {
    if (!unknown) return;
    segs.push({ kind: 'unknown', source: unknown, tok: { ...tok, space: first ? tok.space : false }, weight: letterWeight(unknown) });
    first = false;
    unknown = '';
  };
  while (j < chars.length) {
    let hit = null;
    let len = 0;
    for (let n = Math.min(lex ? lex.maxChars : 0, chars.length - j); n >= 1; n--) {
      const key = chars.slice(j, j + n).join('');
      const h = lex.lookupChars(key) || lex.lookup(lex.lower(key)) || (n === 1 ? particle(key, lex) : null);
      if (h) { hit = h; len = n; break; }
    }
    if (hit) {
      flush();
      const source = chars.slice(j, j + len).join('');
      segs.push({ kind: len > 1 ? 'phrase' : 'word', source, tok: { ...tok, space: first ? tok.space : false }, weight: letterWeight(source), cand: pickCandidate(hit.cands, domain, dialect), how: hit.how });
      first = false;
      j += len;
    } else {
      unknown += chars[j];
      j++;
    }
  }
  flush();
}

/**
 * Inflection fallback: strip a declared suffix ("tickets" → "ticket", "ragazzi" → "ragazzo")
 * and look the lemma up. The rendering is the lemma's entry, so the provenance says so.
 * Rule syntax: "s" strips; "i>o" replaces a final "i" with "o".
 */
function stripInflection(word, lex) {
  const rules = lex.rules.suffixes;
  if (!rules) return null;
  const lw = lex.lower(word);
  for (const rule of rules) {
    const [suffix, repl = ''] = rule.split('>');
    if (!lw.endsWith(suffix) || lw.length - suffix.length < 2) continue;
    const hit = lex.lookup(lw.slice(0, -suffix.length) + repl);
    if (hit) return { cands: hit.cands, how: `inflection (-${suffix}${repl ? ' → -' + repl : ''})` };
  }
  return null;
}

/** Grammatical particles (Korean 는/를, Japanese は/が): known, meaningful only as grammar. */
function particle(piece, lex) {
  if (!(lex.rules.particles || []).includes(piece)) return null;
  const pack = lex.packs.find((p) => p.domain === 'base') || lex.packs[0];
  return { cands: [{ concept: null, particle: true, form: piece, pack: pack.id, version: pack.version, domain: pack.domain, dialect: null, primary: true, order: -1 }], how: 'particle' };
}

/** Elision ("l'hôtel") and compound / particle splitting ("Bahnhofstraße", "저는"). Whole-word decomposition only. */
function splitWord(word, lex) {
  const lw = lex.lower(word);
  const elision = lex.rules.elision;
  if (elision && lw.includes("'")) {
    const at = lw.indexOf("'") + 1;
    // "l'" is indexed as "l" (the tokenizer drops a trailing apostrophe), so try both.
    const head = lex.lookup(lw.slice(0, at)) || lex.lookup(lw.slice(0, at - 1));
    const tail = lex.lookup(lw.slice(at));
    if (head && tail) return [{ text: word.slice(0, at), cands: head.cands, how: 'elision' }, { text: word.slice(at), cands: tail.cands, how: 'elision' }];
  }
  if (!lex.rules.split) return null;
  const chars = [...lw];
  const orig = [...word];
  const minPart = lex.rules.minPart || 2;
  // best[k] = fewest pieces covering chars[0..k)
  const best = new Array(chars.length + 1).fill(null);
  best[0] = [];
  for (let a = 0; a < chars.length; a++) {
    if (!best[a]) continue;
    for (let b = chars.length; b >= a + 1; b--) {
      const piece = chars.slice(a, b).join('');
      const tooShort = b - a < minPart && !(lex.rules.particles || []).includes(piece);
      if (tooShort) continue;
      let hit = lex.lookup(piece) || particle(piece, lex);
      // German linking -s- / -n- between compound members.
      if (!hit && lex.rules.linkers && a > 0) {
        for (const l of lex.rules.linkers) if (piece.startsWith(l) && lex.lookup(piece.slice(l.length))) hit = lex.lookup(piece.slice(l.length));
      }
      if (!hit) continue;
      const cand = [...best[a], { text: orig.slice(a, b).join(''), cands: hit.cands, how: 'compound' }];
      if (!best[b] || cand.length < best[b].length) best[b] = cand;
    }
  }
  const full = best[chars.length];
  return full && full.length > 1 ? full : null;
}

/**
 * Translate text between two installed languages.
 * @param {object} p {text, src, tgt, srcLex, tgtLex, srcDialect, tgtDialect, domain, srcScript, tgtScript}
 */
export function translate(p) {
  const { srcLex, tgtLex, domain = null } = p;
  const notes = [];
  let text = p.text;
  let colloquial = [];
  if (srcLex) {
    const c = srcLex.normalizeColloquial(text, p.srcDialect);
    text = c.text;
    colloquial = c.applied;
    if (colloquial.length) notes.push(`Dialect normalization: ${colloquial.map((a) => `“${a.from}” → “${a.to}”`).join(', ')}`);
  }
  const tokens = tokenize(text);
  const segs = segment(tokens, srcLex, { domain, dialect: p.srcDialect });
  const tgtUnspaced = isUnspaced(p.tgtScript);
  const out = [];
  for (const s of segs) {
    const seg = { kind: s.kind, source: s.source, space: s.tok.space, weight: s.weight, flagged: false };
    if (s.kind === 'number') { seg.target = s.source; seg.provenance = { type: 'preserved', detail: 'Number preserved exactly' }; }
    else if (s.kind === 'punct') { seg.target = mapPunct(s.source, p.tgtScript); }
    else if (s.kind === 'unknown') {
      seg.target = s.source;
      seg.flagged = true;
      const looksLikeName = isCased(s.tok.script) && /^\p{Lu}/u.test(s.source) && !isSentenceStart(segs, s);
      seg.provenance = { type: looksLikeName ? 'name' : 'unknown', detail: looksLikeName ? 'Not in the dictionary — kept as written (looks like a name)' : `Not in the installed ${p.src} dictionary — passed through untranslated` };
    } else if (s.cand.particle) {
      seg.kind = 'omitted';
      seg.target = '';
      seg.matchedBy = 'particle';
      seg.provenance = { type: 'grammar', detail: `Grammatical particle “${s.source}” — marks the role of the word before it; no separate word in ${p.tgt}, omitted by rule`, source: { pack: s.cand.pack, version: s.cand.version, domain: s.cand.domain, form: s.cand.form }, target: { pack: 'rule', version: '1' } };
    } else {
      const r = tgtLex ? tgtLex.render(s.cand.concept, p.tgtDialect, domain) : null;
      seg.concept = s.cand.concept;
      seg.matchedBy = s.how;
      const srcProv = { pack: s.cand.pack, version: s.cand.version, domain: s.cand.domain, form: s.cand.form, dialect: s.cand.dialect };
      if (!r) {
        seg.kind = 'gap';
        seg.target = s.source;
        seg.flagged = true;
        seg.provenance = { type: 'gap', detail: `Recognized (${s.cand.concept}) but the installed ${p.tgt} dictionary has no entry for it — passed through`, source: srcProv };
      } else {
        seg.target = r.form;
        seg.alternatives = r.alternatives;
        seg.reading = r.reading;
        seg.ipa = r.ipa;
        if (r.omitted) seg.kind = 'omitted';
        seg.provenance = {
          type: 'dictionary',
          detail: r.omitted ? `${p.tgt} has no separate word for this (${s.cand.concept}) — omitted by rule` : `Dictionary entry ${s.cand.concept}`,
          source: srcProv,
          target: { pack: r.pack, version: r.version, domain: r.domain, dialect: r.dialect, note: r.note },
        };
        if (s.how === 'accent-insensitive') seg.provenance.detail += ' (matched ignoring accents)';
        if (s.how && s.how.startsWith('inflection')) seg.provenance.detail += ` — matched as the dictionary form by ${s.how}; rendered in its dictionary form`;
      }
    }
    out.push(seg);
  }

  const pieces = assemble(out, p.tgtScript, tgtUnspaced, tgtLex ? tgtLex.rules : {});
  const output = pieces.map((x) => x.text).join('');
  let known = 0;
  let total = 0;
  for (const s of out) {
    total += s.weight;
    if (!s.flagged && (s.kind === 'word' || s.kind === 'phrase' || s.kind === 'omitted')) known += s.weight;
  }
  const lexical = out.filter((s) => ['word', 'phrase', 'omitted', 'gap'].includes(s.kind));
  const wordByWord = lexical.length > 1;
  if (wordByWord) notes.push('Assembled entry by entry from the dictionary: word order follows the source, so read it as a faithful gloss.');
  if (!srcLex) notes.push(`No ${p.src} dictionary installed — nothing could be translated. Install its pack to translate offline.`);
  else if (!tgtLex) notes.push(`No ${p.tgt} dictionary installed — install its pack to render translations.`);
  const flaggedCount = out.filter((s) => s.flagged).length;
  if (flaggedCount) notes.push(`${flaggedCount} item${flaggedCount === 1 ? '' : 's'} not translated — underlined and passed through as written.`);

  return {
    engine: 'local-deterministic',
    src: p.src, tgt: p.tgt, srcDialect: p.srcDialect || null, tgtDialect: p.tgtDialect || null, domain,
    input: p.text,
    output,
    pieces,
    segments: out,
    coverage: { known, total, percent: total === 0 ? 100 : Math.floor((known / total) * 100) },
    wordByWord,
    colloquial,
    notes,
  };
}

function isSentenceStart(segs, s) {
  const idx = segs.indexOf(s);
  for (let k = idx - 1; k >= 0; k--) {
    if (segs[k].kind === 'punct') return /[.?!。？！]/.test(segs[k].source);
    return false;
  }
  return true;
}

function mapPunct(p, tgtScript) {
  const neutral = p in NEUTRAL_PUNCT ? NEUTRAL_PUNCT[p] : p;
  const table = TARGET_PUNCT[tgtScript] || {};
  return table[neutral] ?? neutral;
}

/** Join target segments with script-appropriate spacing, punctuation and casing. */
function assemble(segs, tgtScript, tgtUnspaced, rules) {
  const pieces = [];
  let prev = null;
  segs.forEach((s, idx) => {
    if (s.target === '' && s.kind !== 'punct') {
      return; // omitted by rule: contributes nothing visible
    }
    if (s.kind === 'punct' && s.target === '') return;
    let sep = '';
    if (prev) {
      const isClose = s.kind === 'punct' && CLOSING.has(s.target);
      const prevOpen = prev.kind === 'punct' && OPENING.has(prev.target);
      if (s.kind === 'punct' && rules.spaceBeforeHighPunct && /^[?!:;]$/.test(s.target)) sep = '\u202F';
      else if (isClose || prevOpen) sep = '';
      else if (s.kind === 'punct' && s.target === '"') sep = s.space ? ' ' : '';
      else if (tgtUnspaced) {
        const fromSource = (x) => x.flagged || x.kind === 'number';
        sep = (fromSource(s) && !isUnspacedText(s.target)) || (fromSource(prev) && !isUnspacedText(prev.target)) ? ' ' : '';
        if (prev.kind === 'punct') sep = /[.?!,;:]/.test(prev.target) ? ' ' : '';
      } else sep = ' ';
    }
    if (sep) pieces.push({ text: sep, seg: null });
    pieces.push({ text: s.target, seg: idx });
    prev = s;
  });
  if (isCased(tgtScript)) capitalize(pieces, segs);
  if (rules.invertedQuestion) invert(pieces);
  return pieces;
}

function isUnspacedText(t) {
  return /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Thai}\p{Script=Lao}\p{Script=Khmer}\p{Script=Myanmar}]/u.test(t);
}

function capitalize(pieces, segs) {
  let start = true;
  for (const p of pieces) {
    if (p.seg === null) continue;
    const s = segs[p.seg];
    if (s.kind === 'punct') { if (/[.?!]/.test(p.text)) start = true; continue; }
    if (start && s.kind !== 'number') p.text = p.text.replace(/^\p{Ll}/u, (c) => c.toLocaleUpperCase());
    start = false;
  }
}

/** Spanish-style ¿…? and ¡…! around each sentence. */
function invert(pieces) {
  let sentenceStart = 0;
  for (let k = 0; k < pieces.length; k++) {
    const t = pieces[k].text;
    if (t === '?' || t === '!' || t === '.') {
      const open = t === '?' ? '¿' : t === '!' ? '¡' : null;
      let first = sentenceStart;
      while (first < k && pieces[first].seg === null) first++;
      if (open && first < k) {
        pieces[first] = { ...pieces[first], text: open + pieces[first].text };
      }
      sentenceStart = k + 1;
    }
  }
}

/** Language-independent fingerprint of a result, for the determinism guarantee. */
export function resultFingerprint(r) {
  const s = JSON.stringify([r.src, r.tgt, r.srcDialect, r.tgtDialect, r.domain, r.input, r.output, r.coverage, r.segments.map((x) => [x.kind, x.source, x.target, x.concept || null])]);
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(16).padStart(8, '0');
}

