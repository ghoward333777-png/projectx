// Unicode script handling: per-character script classification, writing
// direction, and the typographic traits the tokenizer and assembler need.
// Pure and deterministic; works in browsers and Node alike.

// Base scripts (Unicode Script property values) the classifier knows about.
const BASE = [
  ['Latn', 'Latin'], ['Cyrl', 'Cyrillic'], ['Grek', 'Greek'], ['Arab', 'Arabic'],
  ['Hebr', 'Hebrew'], ['Deva', 'Devanagari'], ['Beng', 'Bengali'], ['Guru', 'Gurmukhi'],
  ['Gujr', 'Gujarati'], ['Orya', 'Oriya'], ['Taml', 'Tamil'], ['Telu', 'Telugu'],
  ['Knda', 'Kannada'], ['Mlym', 'Malayalam'], ['Sinh', 'Sinhala'], ['Thai', 'Thai'],
  ['Laoo', 'Lao'], ['Khmr', 'Khmer'], ['Mymr', 'Myanmar'], ['Tibt', 'Tibetan'],
  ['Ethi', 'Ethiopic'], ['Geor', 'Georgian'], ['Armn', 'Armenian'], ['Hani', 'Han'],
  ['Hira', 'Hiragana'], ['Kana', 'Katakana'], ['Hang', 'Hangul'], ['Thaa', 'Thaana'],
  ['Cans', 'Canadian_Aboriginal'], ['Cher', 'Cherokee'], ['Tfng', 'Tifinagh'], ['Syrc', 'Syriac'],
];

const MATCHERS = BASE.map(([code, name]) => [code, new RegExp(`\\p{Script=${name}}`, 'u')]);

// Composite (writing-system) scripts used in the registry → the base scripts they draw on.
const COMPOSITE = {
  Hans: ['Hani'], Hant: ['Hani'], Jpan: ['Hani', 'Hira', 'Kana'], Kore: ['Hang', 'Hani'],
};

const RTL = new Set(['Arab', 'Hebr', 'Thaa', 'Syrc', 'Nkoo']);
// Scripts written without spaces between words: segmentation is dictionary-driven.
const UNSPACED = new Set(['Hani', 'Hira', 'Kana', 'Hans', 'Hant', 'Jpan', 'Thai', 'Laoo', 'Khmr', 'Mymr', 'Tibt']);
const CASED = new Set(['Latn', 'Cyrl', 'Grek', 'Armn']);

const LETTER = /[\p{L}\p{M}]/u;
const cache = new Map();

/** Base script code of one character, 'Zyyy' for common (digits, punctuation, spaces). */
export function charScript(ch) {
  const hit = cache.get(ch);
  if (hit) return hit;
  let found = 'Zyyy';
  if (LETTER.test(ch)) {
    for (const [code, re] of MATCHERS) {
      if (re.test(ch)) { found = code; break; }
    }
    if (found === 'Zyyy') found = 'Zinh';
  }
  if (cache.size < 20000) cache.set(ch, found);
  return found;
}

/** Letter counts per base script, e.g. { Latn: 12, Hani: 3 }. Combining marks count with their base. */
export function scriptCounts(text) {
  const counts = {};
  let prev = null;
  for (const ch of text) {
    let s = charScript(ch);
    if (s === 'Zinh') s = prev; // combining mark inherits its base letter's script
    if (s && s !== 'Zyyy') counts[s] = (counts[s] || 0) + 1;
    if (s !== null && s !== 'Zyyy') prev = s;
  }
  return counts;
}

export function dominantScript(text) {
  const counts = scriptCounts(text);
  let best = null;
  for (const k of Object.keys(counts).sort()) if (!best || counts[k] > counts[best]) best = k;
  return best;
}

/** Base scripts a registry script code covers. */
export function baseScripts(script) {
  return COMPOSITE[script] || [script];
}

export function isRtl(script) {
  return RTL.has(script);
}

export function isUnspaced(script) {
  return baseScripts(script).every((s) => UNSPACED.has(s)) || UNSPACED.has(script);
}

export function isCased(script) {
  return CASED.has(script);
}

export function scriptName(code) {
  const hit = BASE.find(([c]) => c === code);
  if (hit) return hit[1].replace(/_/g, ' ');
  return { Hans: 'Simplified Han', Hant: 'Traditional Han', Jpan: 'Japanese', Kore: 'Korean' }[code] || code;
}

export const KNOWN_SCRIPTS = BASE.map(([c]) => c);
