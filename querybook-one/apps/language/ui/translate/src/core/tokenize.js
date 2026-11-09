// Tokenizer: splits normalized text into word, number and punctuation tokens,
// remembering whether each token was preceded by whitespace. Word runs are
// split where the script changes between spaced and unspaced writing systems
// (e.g. "I喜欢coffee"), so each run can be matched with the right strategy.

import { charScript, isUnspaced } from './scripts.js';

const TOKEN = /(\p{Nd}+(?:[.,:/]\p{Nd}+)*%?)|([\p{L}\p{M}](?:[\p{L}\p{M}\p{Nd}\u200C\u200D]|['\-·](?=[\p{L}\p{M}]))*)|(\S)/gu;

function runScript(word) {
  for (const ch of word) {
    const s = charScript(ch);
    if (s !== 'Zyyy' && s !== 'Zinh') return s;
  }
  return 'Zyyy';
}

/** Split a word at spaced/unspaced script boundaries. */
function splitMixed(word, start) {
  const parts = [];
  let buf = '';
  let bufStart = start;
  let mode = null;
  let offset = start;
  for (const ch of word) {
    const s = charScript(ch);
    const m = s === 'Zyyy' || s === 'Zinh' ? mode : isUnspaced(s);
    if (mode !== null && m !== mode && buf) {
      parts.push([buf, bufStart]);
      buf = '';
      bufStart = offset;
    }
    if (m !== null) mode = m;
    buf += ch;
    offset += ch.length;
  }
  if (buf) parts.push([buf, bufStart]);
  return parts;
}

/**
 * @returns {Array<{type:'w'|'n'|'p', text:string, start:number, end:number, space:boolean, script:string, unspaced:boolean}>}
 */
export function tokenize(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const space = m.index > last && /\s/.test(text.slice(last, m.index));
    if (m[1]) {
      out.push({ type: 'n', text: m[1], start: m.index, end: m.index + m[1].length, space, script: 'Zyyy', unspaced: false });
    } else if (m[2]) {
      const parts = splitMixed(m[2], m.index);
      parts.forEach(([w, s], i) => {
        const script = runScript(w);
        out.push({ type: 'w', text: w, start: s, end: s + w.length, space: i === 0 ? space : false, script, unspaced: isUnspaced(script) });
      });
    } else {
      out.push({ type: 'p', text: m[3], start: m.index, end: m.index + m[3].length, space, script: 'Zyyy', unspaced: false });
    }
    last = m.index + m[0].length;
  }
  return out;
}

/** Number of letters (not marks, digits or punctuation) — the coverage weight of a span. */
export function letterWeight(text) {
  let n = 0;
  for (const ch of text) if (/\p{L}/u.test(ch)) n++;
  return n;
}

/** Lowercased word-token key for a dictionary form ("¿Dónde está?" → "dónde está"). */
export function formKey(form, lowerFn) {
  const toks = tokenize(form).filter((t) => t.type !== 'p');
  if (toks.length === 0) return '';
  if (toks.every((t) => t.unspaced || t.type === 'n')) return lowerFn(toks.map((t) => t.text).join(''));
  return lowerFn(toks.map((t) => t.text).join(' '));
}
