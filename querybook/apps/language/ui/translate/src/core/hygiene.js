// Deterministic text hygiene (spec §4.3 / §6 step 3): NFC, invisible-character
// stripping, exotic spaces, half/full-width folding, collapsed runs. Numbers and
// named entities are never altered. ZWJ / ZWNJ are kept: they carry meaning in
// Persian and Indic orthography.

const INVISIBLE = /[\u200B\u2060\uFEFF\u00AD\u200E\u200F\u202A-\u202E\u2066-\u2069\u180Eـ]/g;
const EXOTIC_SPACE = /[\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000\t]/g;
const WIDTH_FORMS = /[！-～｡-ﾟ￠-￮]/g;
const SMART_APOSTROPHE = /[’‘ʼ`´]/g;

/**
 * Normalize raw input (typed, pasted, or ASR output).
 * @returns {{text: string, changes: string[]}}
 */
export function normalize(raw) {
  const changes = [];
  let text = String(raw ?? '');
  const step = (label, fn) => {
    const next = fn(text);
    if (next !== text) changes.push(label);
    text = next;
  };
  step('line endings', (t) => t.replace(/\r\n?/g, '\n'));
  step('NFC', (t) => t.normalize('NFC'));
  step('invisible characters', (t) => t.replace(INVISIBLE, ''));
  step('exotic spaces', (t) => t.replace(EXOTIC_SPACE, ' '));
  step('full/half-width forms', (t) => t.replace(WIDTH_FORMS, (c) => c.normalize('NFKC')));
  step('apostrophes', (t) => t.replace(SMART_APOSTROPHE, "'"));
  step('collapsed runs', (t) => t.replace(/ {2,}/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim());
  return { text, changes };
}

/** Locale-aware lowercase (Turkish dotted/dotless i, Lithuanian, …). */
export function lower(word, lang) {
  try {
    return word.toLocaleLowerCase(lang || undefined);
  } catch {
    return word.toLowerCase();
  }
}

/**
 * Accent-insensitive matching key. Applied only where folding is lossless
 * enough to be a safe second chance; never to Indic or Brahmic scripts, where
 * combining marks are vowels.
 */
export function foldKey(word, script) {
  switch (script) {
    case 'Latn':
    case 'Grek':
      return word.normalize('NFD').replace(/\p{M}/gu, '').replace(/ς/g, 'σ').replace(/ß/g, 'ss').normalize('NFC');
    case 'Cyrl':
      return word.replace(/ё/g, 'е');
    case 'Arab':
      return word.replace(/[\u064B-\u065F\u0670]/g, '').replace(/[أإآٱ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه');
    case 'Hebr':
      return word.replace(/[\u0591-\u05BD\u05BF\u05C1\u05C2\u05C4\u05C5\u05C7]/g, '');
    default:
      return word;
  }
}
