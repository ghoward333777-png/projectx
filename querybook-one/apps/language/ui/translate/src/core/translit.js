// Deterministic transliteration to Latin for readers who cannot read the
// script (spec §4.3 "optional transliteration"). Each scheme is a rule table.
// Scripts without a rule table return an honest refusal; a pack may supply a
// character map for any script via `translit.map` (expandable without code).

import { charScript, scriptName } from './scripts.js';

const CYRL = { а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'yo', ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'kh', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'shch', ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya', є: 'ye', і: 'i', ї: 'yi', ґ: 'g', ў: 'w', ђ: 'đ', ј: 'j', љ: 'lj', њ: 'nj', ћ: 'ć', џ: 'dž', ѓ: 'gj', ќ: 'kj', ѕ: 'dz', ә: 'ä', ғ: 'gh', қ: 'q', ң: 'ng', ө: 'ö', ұ: 'u', ү: 'ü', һ: 'h', ӣ: 'ī', ӯ: 'ū', ҳ: 'h', ҷ: 'j', ҫ: 'th', ӑ: 'ă', ӗ: 'ĕ', ҡ: 'q' };
const CYRL_LANG = {
  uk: { г: 'h', и: 'y', е: 'e', і: 'i', й: 'i' },
  be: { г: 'h', і: 'i' },
  sr: { ж: 'ž', ц: 'c', ч: 'č', ш: 'š', х: 'h', й: 'j' },
  mk: { ж: 'ž', ц: 'c', ч: 'č', ш: 'š', х: 'h' },
  bg: { щ: 'sht', ъ: 'a', х: 'h' },
  kk: { і: 'ı', у: 'u', х: 'h' },
  mn: { х: 'kh', ү: 'ü', ө: 'ö' },
};

const GREK = { α: 'a', β: 'v', γ: 'g', δ: 'd', ε: 'e', ζ: 'z', η: 'i', θ: 'th', ι: 'i', κ: 'k', λ: 'l', μ: 'm', ν: 'n', ξ: 'x', ο: 'o', π: 'p', ρ: 'r', σ: 's', ς: 's', τ: 't', υ: 'y', φ: 'f', χ: 'ch', ψ: 'ps', ω: 'o' };
const GREK_DIGRAPH = { ου: 'ou', αι: 'ai', ει: 'ei', οι: 'oi', γγ: 'ng', γκ: 'gk', μπ: 'mp', ντ: 'nt', αυ: 'av', ευ: 'ev' };

const GEOR = { ა: 'a', ბ: 'b', გ: 'g', დ: 'd', ე: 'e', ვ: 'v', ზ: 'z', თ: 't', ი: 'i', კ: "k'", ლ: 'l', მ: 'm', ნ: 'n', ო: 'o', პ: "p'", ჟ: 'zh', რ: 'r', ს: 's', ტ: "t'", უ: 'u', ფ: 'p', ქ: 'k', ღ: 'gh', ყ: "q'", შ: 'sh', ჩ: 'ch', ც: 'ts', ძ: 'dz', წ: "ts'", ჭ: "ch'", ხ: 'kh', ჯ: 'j', ჰ: 'h' };

const ARMN = { ա: 'a', բ: 'b', գ: 'g', դ: 'd', ե: 'e', զ: 'z', է: 'e', ը: 'ə', թ: "t'", ժ: 'zh', ի: 'i', լ: 'l', խ: 'kh', ծ: 'ts', կ: 'k', հ: 'h', ձ: 'dz', ղ: 'gh', ճ: 'ch', մ: 'm', յ: 'y', ն: 'n', շ: 'sh', ո: 'o', չ: "ch'", պ: 'p', ջ: 'j', ռ: 'r', ս: 's', վ: 'v', տ: 't', ր: 'r', ց: "ts'", ւ: 'v', փ: "p'", ք: "k'", օ: 'o', ֆ: 'f', և: 'ev' };

const ARAB = { 'ء': "'", 'آ': 'ā', 'أ': 'a', 'إ': 'i', 'ؤ': "'", 'ئ': "'", 'ب': 'b', 'ة': 'a', 'ت': 't', 'ث': 'th', 'ج': 'j', 'ح': 'ḥ', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh', 'ص': 'ṣ', 'ض': 'ḍ', 'ط': 'ṭ', 'ظ': 'ẓ', 'ع': 'ʿ', 'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n', 'ه': 'h', 'ى': 'ā', 'پ': 'p', 'چ': 'ch', 'ژ': 'zh', 'گ': 'g', 'ک': 'k', 'ٹ': 'ṭ', 'ڈ': 'ḍ', 'ڑ': 'ṛ', 'ں': 'n', 'ہ': 'h', 'ھ': 'h', 'ے': 'e', 'ۀ': 'e', 'ټ': 'ṭ', 'ډ': 'ḍ', 'ړ': 'ṛ', 'ږ': 'ẓ', 'ښ': 'x', 'ځ': 'dz', 'څ': 'ts', 'ڼ': 'ṇ', 'ې': 'e', 'ۍ': 'ay', 'ڤ': 'v', 'ۆ': 'o', 'ێ': 'ê', 'ڵ': 'll', 'ڕ': 'rr' };
const ARAB_VOWEL_SIGNS = { '\u064E': 'a', '\u064F': 'u', '\u0650': 'i', '\u064B': 'an', '\u064C': 'un', '\u064D': 'in', '\u0652': '', '\u0670': 'ā' };

const HEBR = { א: '', ב: 'v', ג: 'g', ד: 'd', ה: 'h', ו: 'v', ז: 'z', ח: 'kh', ט: 't', י: 'y', כ: 'kh', ך: 'kh', ל: 'l', מ: 'm', ם: 'm', נ: 'n', ן: 'n', ס: 's', ע: '', פ: 'f', ף: 'f', צ: 'ts', ץ: 'ts', ק: 'k', ר: 'r', ש: 'sh', ת: 't' };
const HEBR_DAGESH = { ב: 'b', כ: 'k', ך: 'k', פ: 'p' };
const HEBR_VOWELS = { '\u05B7': 'a', '\u05B8': 'a', '\u05B6': 'e', '\u05B5': 'e', '\u05B4': 'i', '\u05B9': 'o', '\u05BB': 'u', '\u05B0': 'e', '\u05B1': 'e', '\u05B2': 'a', '\u05B3': 'o' };
const YIDDISH = { 'א\u05B7': 'a', 'א\u05B8': 'o', 'ײ\u05B7': 'ay', 'ײ': 'ey', 'ױ': 'oy', 'ו\u05BC': 'u', 'וו': 'v', 'י\u05B4': 'i', 'ב\u05BF': 'v', 'כ\u05BC': 'k', 'פ\u05BC': 'p', 'פ\u05BF': 'f', 'ש\u05C2': 's', 'ת\u05BC': 't', 'א': '', 'ו': 'u', 'י': 'i', 'ע': 'e', 'ב': 'b', 'ג': 'g', 'ד': 'd', 'ה': 'h', 'ז': 'z', 'ח': 'kh', 'ט': 't', 'כ': 'kh', 'ך': 'kh', 'ל': 'l', 'מ': 'm', 'ם': 'm', 'נ': 'n', 'ן': 'n', 'ס': 's', 'פ': 'f', 'ף': 'f', 'צ': 'ts', 'ץ': 'ts', 'ק': 'k', 'ר': 'r', 'ש': 'sh', 'ת': 's' };

// Brahmic scripts share the ISCII-derived block layout, so one offset table serves nine scripts.
const BRAHMIC_BASE = { Deva: 0x0900, Beng: 0x0980, Guru: 0x0A00, Gujr: 0x0A80, Orya: 0x0B00, Taml: 0x0B80, Telu: 0x0C00, Knda: 0x0C80, Mlym: 0x0D00 };
const B_VOWEL = { 0x05: 'a', 0x06: 'ā', 0x07: 'i', 0x08: 'ī', 0x09: 'u', 0x0A: 'ū', 0x0B: 'ṛ', 0x0C: 'ḷ', 0x0D: 'ê', 0x0E: 'e', 0x0F: 'e', 0x10: 'ai', 0x11: 'ô', 0x12: 'o', 0x13: 'o', 0x14: 'au', 0x60: 'ṝ', 0x61: 'ḹ' };
const B_CONS = { 0x15: 'k', 0x16: 'kh', 0x17: 'g', 0x18: 'gh', 0x19: 'ṅ', 0x1A: 'c', 0x1B: 'ch', 0x1C: 'j', 0x1D: 'jh', 0x1E: 'ñ', 0x1F: 'ṭ', 0x20: 'ṭh', 0x21: 'ḍ', 0x22: 'ḍh', 0x23: 'ṇ', 0x24: 't', 0x25: 'th', 0x26: 'd', 0x27: 'dh', 0x28: 'n', 0x29: 'ṉ', 0x2A: 'p', 0x2B: 'ph', 0x2C: 'b', 0x2D: 'bh', 0x2E: 'm', 0x2F: 'y', 0x30: 'r', 0x31: 'ṟ', 0x32: 'l', 0x33: 'ḷ', 0x34: 'ḻ', 0x35: 'v', 0x36: 'ś', 0x37: 'ṣ', 0x38: 's', 0x39: 'h', 0x5F: 'y' };
const B_SIGN = { 0x3E: 'ā', 0x3F: 'i', 0x40: 'ī', 0x41: 'u', 0x42: 'ū', 0x43: 'ṛ', 0x44: 'ṝ', 0x45: 'ê', 0x46: 'e', 0x47: 'e', 0x48: 'ai', 0x49: 'ô', 0x4A: 'o', 0x4B: 'o', 0x4C: 'au', 0x57: 'au', 0x62: 'ḷ', 0x63: 'ḹ' };
const B_NUKTA = { k: 'q', kh: 'x', g: 'ġ', j: 'z', 'ḍ': 'ṛ', 'ḍh': 'ṛh', ph: 'f', y: 'ẏ' };
const SCHWA_DROP = new Set(['hi', 'mr', 'pa', 'gu', 'ne', 'mai', 'bho', 'bn', 'as']);

// Hangul (Revised Romanization, with liaison across a silent ㅇ).
const H_L = ['g', 'kk', 'n', 'd', 'tt', 'r', 'm', 'b', 'pp', 's', 'ss', '', 'j', 'jj', 'ch', 'k', 't', 'p', 'h'];
const H_V = ['a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', 'wae', 'oe', 'yo', 'u', 'wo', 'we', 'wi', 'yu', 'eu', 'ui', 'i'];
const H_T = ['', 'k', 'k', 'k', 'n', 'n', 'n', 't', 'l', 'k', 'm', 'l', 'l', 'l', 'p', 'l', 'm', 'p', 'p', 't', 't', 'ng', 't', 't', 'k', 't', 'p', 't'];
const H_T_LIAISON = ['', 'g', 'kk', 'k', 'n', 'n', 'n', 'd', 'r', 'g', 'm', 'b', 's', 't', 'p', 'r', 'm', 'b', 's', 's', 'ss', 'ng', 'j', 'ch', 'k', 't', 'p', ''];

// Kana (Hepburn). Katakana maps onto hiragana by a fixed code-point offset.
const KANA = {};
{
  const pairs = 'あ a い i う u え e お o か ka き ki く ku け ke こ ko が ga ぎ gi ぐ gu げ ge ご go さ sa し shi す su せ se そ so ざ za じ ji ず zu ぜ ze ぞ zo た ta ち chi つ tsu て te と to だ da ぢ ji づ zu で de ど do な na に ni ぬ nu ね ne の no は ha ひ hi ふ fu へ he ほ ho ば ba び bi ぶ bu べ be ぼ bo ぱ pa ぴ pi ぷ pu ぺ pe ぽ po ま ma み mi む mu め me も mo や ya ゆ yu よ yo ら ra り ri る ru れ re ろ ろ わ wa ゐ i ゑ e を o ん n ゔ vu ぁ a ぃ i ぅ u ぇ e ぉ o ゎ wa'.replace('ろ ろ', 'ろ ro').split(' ');
  for (let i = 0; i < pairs.length; i += 2) KANA[pairs[i]] = pairs[i + 1];
}
const SMALL_Y = { ゃ: 'a', ゅ: 'u', ょ: 'o' };
const SMALL_V = { ぁ: 'a', ぃ: 'i', ぅ: 'u', ぇ: 'e', ぉ: 'o' };
const MACRON = { a: 'ā', i: 'ī', u: 'ū', e: 'ē', o: 'ō' };

// Ethiopic syllabary: consonant rows of eight vowel orders.
const ETHI_ROWS = { 0x1200: 'h', 0x1208: 'l', 0x1210: 'h', 0x1218: 'm', 0x1220: 's', 0x1228: 'r', 0x1230: 's', 0x1238: 'sh', 0x1240: 'q', 0x1248: 'qw', 0x1250: 'qh', 0x1260: 'b', 0x1268: 'v', 0x1270: 't', 0x1278: 'ch', 0x1280: 'h', 0x1288: 'hw', 0x1290: 'n', 0x1298: 'ny', 0x12A0: '', 0x12A8: 'k', 0x12B0: 'kw', 0x12B8: 'kh', 0x12C0: 'khw', 0x12C8: 'w', 0x12D0: '', 0x12D8: 'z', 0x12E0: 'zh', 0x12E8: 'y', 0x12F0: 'd', 0x12F8: 'dd', 0x1300: 'j', 0x1308: 'g', 0x1310: 'gw', 0x1318: 'ng', 0x1320: "t'", 0x1328: "ch'", 0x1330: "p'", 0x1338: "ts'", 0x1340: "ts'", 0x1348: 'f', 0x1350: 'p' };
const ETHI_ORDERS = ['e', 'u', 'i', 'a', 'é', 'ə', 'o', 'wa'];
const ETHI_PUNCT = { '።': '.', '፣': ',', '፤': ';', '፥': ':', '፧': '?', '፡': ' ' };

function mapCased(text, table) {
  let out = '';
  for (const ch of text) {
    const lo = ch.toLowerCase();
    if (lo in table) {
      const t = table[lo];
      out += ch !== lo && t ? t[0].toUpperCase() + t.slice(1) : t;
    } else out += ch;
  }
  return out;
}

function cyrillic(text, lang) {
  return mapCased(text, { ...CYRL, ...(CYRL_LANG[lang] || {}) });
}

function greek(text) {
  let t = text.normalize('NFD').replace(/[\u0300-\u036F]/g, '').normalize('NFC');
  for (const [k, v] of Object.entries(GREK_DIGRAPH)) t = t.replace(new RegExp(k, 'g'), v).replace(new RegExp(k[0].toUpperCase() + k.slice(1), 'g'), v[0].toUpperCase() + v.slice(1));
  return mapCased(t, GREK);
}

function arabic(text) {
  let out = '';
  const chars = [...text];
  chars.forEach((ch, i) => {
    const prev = chars[i - 1];
    const isL = (c) => c && /\p{Script=Arabic}/u.test(c) && /\p{L}/u.test(c);
    if (ch in ARAB_VOWEL_SIGNS) { out += ARAB_VOWEL_SIGNS[ch]; return; }
    if (ch === '\u0651') { const m = out.match(/(sh|th|kh|dh|gh|[^aeiouāīū])$/); if (m) out += m[1]; return; }
    if (ch === 'ا') { out += isL(prev) ? 'ā' : 'a'; return; }
    if (ch === 'و') { out += isL(prev) && !/[aeiouāīū]$/.test(out) ? 'ū' : 'w'; return; }
    if (ch === 'ي' || ch === 'ی') { out += isL(prev) && !/[aeiouāīū]$/.test(out) ? 'ī' : 'y'; return; }
    out += ch in ARAB ? ARAB[ch] : ch;
  });
  return out;
}

function hebrew(text, lang) {
  if (lang === 'yi') {
    let out = '';
    const s = text.normalize('NFC');
    for (let i = 0; i < s.length;) {
      const two = s.slice(i, i + 2);
      const three = s.slice(i, i + 3);
      if (three in YIDDISH) { out += YIDDISH[three]; i += 3; } else if (two in YIDDISH) { out += YIDDISH[two]; i += 2; } else { out += s[i] in YIDDISH ? YIDDISH[s[i]] : s[i]; i++; }
    }
    return out;
  }
  let out = '';
  const chars = [...text.normalize('NFD')];
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (ch in HEBR) {
      const marks = [];
      while (chars[i + 1] && /\p{M}/u.test(chars[i + 1])) marks.push(chars[++i]);
      const dagesh = marks.includes('\u05BC');
      if (ch === 'ו' && marks.includes('\u05B9')) { out += 'o'; continue; }
      if (ch === 'ו' && dagesh && marks.length === 1) { out += 'u'; continue; }
      if (ch === 'ש' && marks.includes('\u05C2')) out += 's';
      else out += dagesh && HEBR_DAGESH[ch] ? HEBR_DAGESH[ch] : HEBR[ch];
      for (const m of marks) if (m in HEBR_VOWELS) out += HEBR_VOWELS[m];
    } else if (!/\p{M}/u.test(ch)) out += ch;
  }
  return out;
}

function brahmic(text, script, lang) {
  const base = BRAHMIC_BASE[script];
  const chars = [...text];
  let out = '';
  let pendingSchwa = false;
  for (let i = 0; i < chars.length; i++) {
    const cp = chars[i].codePointAt(0);
    const off = cp - base;
    if (off < 0 || off > 0x7F) {
      if (pendingSchwa) { out += SCHWA_DROP.has(lang) && /[\s\p{P}]/u.test(chars[i]) ? '' : 'a'; pendingSchwa = false; }
      out += chars[i];
      continue;
    }
    if (off in B_CONS) {
      if (pendingSchwa) out += 'a';
      let c = B_CONS[off];
      if (chars[i + 1] && chars[i + 1].codePointAt(0) - base === 0x3C) { c = B_NUKTA[c] || c; i++; }
      out += c;
      pendingSchwa = true;
      continue;
    }
    if (off in B_SIGN) { out += B_SIGN[off]; pendingSchwa = false; continue; }
    if (off === 0x4D) { pendingSchwa = false; continue; } // virama
    if (pendingSchwa) { out += 'a'; pendingSchwa = false; }
    if (off in B_VOWEL) out += B_VOWEL[off];
    else if (off === 0x02 || off === 0x70) out += 'ṁ';
    else if (off === 0x01) out += 'm\u0310';
    else if (off === 0x03) out += 'ḥ';
    else if (off === 0x3D) out += "'";
    else if (off === 0x50) out += 'oṁ';
    else if (off === 0x64 || off === 0x65) out += '.';
    else if (off >= 0x66 && off <= 0x6F) out += String(off - 0x66);
    else if (script === 'Beng' && off === 0x4E) out += 't';
    else if (off === 0x71) { /* Gurmukhi addak: gemination of the next consonant */ const n = chars[i + 1] && B_CONS[chars[i + 1].codePointAt(0) - base]; if (n) out += n[0]; }
    else if (off === 0x3C) { /* stray nukta */ }
    else out += chars[i];
  }
  if (pendingSchwa) out += SCHWA_DROP.has(lang) ? '' : 'a';
  return out.normalize('NFC');
}

function hangul(text) {
  const chars = [...text];
  let out = '';
  for (let i = 0; i < chars.length; i++) {
    const code = chars[i].codePointAt(0) - 0xAC00;
    if (code < 0 || code > 11171) { out += chars[i]; continue; }
    const L = Math.floor(code / 588);
    const V = Math.floor((code % 588) / 28);
    const T = code % 28;
    const prevCode = i > 0 ? chars[i - 1].codePointAt(0) - 0xAC00 : -1;
    const prevT = prevCode >= 0 && prevCode <= 11171 ? prevCode % 28 : 0;
    let initial = H_L[L];
    if (L === 5 && prevT === 8) initial = 'l'; // ㄹㄹ → ll
    out += initial + H_V[V];
    const nextCode = i + 1 < chars.length ? chars[i + 1].codePointAt(0) - 0xAC00 : -1;
    const nextSilent = nextCode >= 0 && nextCode <= 11171 && Math.floor(nextCode / 588) === 11;
    const nextL = nextCode >= 0 && nextCode <= 11171 ? Math.floor(nextCode / 588) : -1;
    let fin = T && nextSilent ? H_T_LIAISON[T] : H_T[T];
    // Nasal assimilation before ㄴ / ㅁ (합니다 → hamnida).
    if (nextL === 2 || nextL === 6) fin = { p: 'm', k: 'ng', t: 'n' }[fin] ?? fin;
    out += fin;
  }
  return out;
}

/** Kana → morae (Hepburn). Exported for the Japanese G2P. */
export function kanaMorae(text) {
  const morae = [];
  const chars = [...text];
  let geminate = false;
  for (let i = 0; i < chars.length; i++) {
    let ch = chars[i];
    const cp = ch.codePointAt(0);
    if (cp >= 0x30A1 && cp <= 0x30F6) ch = String.fromCodePoint(cp - 0x60);
    if (ch === 'っ') { geminate = true; continue; }
    if (ch === 'ー' && morae.length) { morae.push({ r: '-', long: true }); continue; }
    let r = KANA[ch];
    if (r === undefined) { morae.push({ r: chars[i], other: true }); geminate = false; continue; }
    let next = chars[i + 1];
    if (next) { const ncp = next.codePointAt(0); if (ncp >= 0x30A1 && ncp <= 0x30F6) next = String.fromCodePoint(ncp - 0x60); }
    if (next in SMALL_Y && r.endsWith('i') && r.length > 1) {
      r = (['shi', 'chi', 'ji'].includes(r) ? r.slice(0, -1) : r.slice(0, -1) + 'y') + SMALL_Y[next];
      i++;
    } else if (next in SMALL_V && r.length > 1 && !(ch in SMALL_V)) {
      r = r.replace(/[aiueo]$/, '') + SMALL_V[next];
      i++;
    }
    if (geminate) { r = (r.startsWith('ch') ? 't' : r[0]) + r; geminate = false; }
    morae.push({ r, n: ch === 'ん' });
  }
  return morae;
}

function kana(text) {
  const morae = kanaMorae(text);
  let out = '';
  morae.forEach((m, i) => {
    if (m.long) { out = out.replace(/([aiueo])$/, (v) => MACRON[v]); return; }
    let r = m.r;
    if (m.n && morae[i + 1] && /^[aiueoy]/.test(morae[i + 1].r)) r = "n'";
    out += r;
  });
  return out;
}

function ethiopic(text) {
  let out = '';
  const chars = [...text];
  chars.forEach((ch, i) => {
    const cp = ch.codePointAt(0);
    if (ch in ETHI_PUNCT) { out += ETHI_PUNCT[ch]; return; }
    if (cp < 0x1200 || cp > 0x135A) { out += ch; return; }
    const row = cp - ((cp - 0x1200) % 8);
    const order = (cp - 0x1200) % 8;
    const cons = ETHI_ROWS[row];
    if (cons === undefined) { out += ch; return; }
    let v = ETHI_ORDERS[order];
    const atEnd = !chars[i + 1] || !/\p{Script=Ethiopic}/u.test(chars[i + 1]) || chars[i + 1] in ETHI_PUNCT;
    if (order === 5) v = atEnd || cons === '' ? (cons === '' ? 'ə' : '') : 'ə';
    if (cons.endsWith('w') && order === 7) v = 'a';
    out += cons + v;
  });
  return out;
}

/**
 * Transliterate to Latin.
 * @returns {{ok: true, text: string, scheme: string, partial: boolean} | {ok: false, reason: string}}
 */
export function transliterate(text, lang, { packMap = null, readings = null } = {}) {
  const scripts = new Set();
  for (const ch of text) { const s = charScript(ch); if (s !== 'Zyyy' && s !== 'Zinh') scripts.add(s); }
  if (scripts.size === 0) return { ok: true, text, scheme: 'none needed', partial: false };
  if ([...scripts].every((s) => s === 'Latn')) return { ok: true, text, scheme: 'already Latin', partial: false };
  if (packMap) {
    let out = '';
    for (const ch of text) out += ch in packMap ? packMap[ch] : ch;
    return { ok: true, text: out, scheme: 'pack character map', partial: [...out].some((c) => !/[\p{Script=Latin}\p{P}\p{N}\s\p{M}]/u.test(c)) };
  }
  let out = text;
  const schemes = [];
  const unsupported = [];
  for (const s of [...scripts].sort()) {
    if (s === 'Latn') continue;
    if (s === 'Cyrl') { out = cyrillic(out, lang); schemes.push('Cyrillic → Latin (BGN-style)'); }
    else if (s === 'Grek') { out = greek(out); schemes.push('Greek → Latin (ELOT-style)'); }
    else if (s === 'Arab') { out = arabic(out); schemes.push('Arabic script → Latin (simplified; short vowels appear only if written)'); }
    else if (s === 'Hebr') { out = hebrew(out, lang); schemes.push(lang === 'yi' ? 'YIVO' : 'Hebrew → Latin (vowels appear only if pointed)'); }
    else if (s in BRAHMIC_BASE) { out = brahmic(out, s, lang); schemes.push(`${scriptName(s)} → Latin (ISO 15919 / IAST-style)`); }
    else if (s === 'Hang') { out = hangul(out); schemes.push('Revised Romanization of Korean'); }
    else if (s === 'Hira' || s === 'Kana') { if (!schemes.includes('Hepburn')) { out = kana(out); schemes.push('Hepburn'); } }
    else if (s === 'Geor') { out = mapCased(out, GEOR); schemes.push('Georgian national romanization'); }
    else if (s === 'Armn') { out = mapCased(out, ARMN); schemes.push('Armenian → Latin (Eastern)'); }
    else if (s === 'Ethi') { out = ethiopic(out); schemes.push('Ethiopic → Latin (practical)'); }
    else if (s === 'Hani' && readings) { /* handled by the caller from dictionary readings */ unsupported.push(s); }
    else unsupported.push(s);
  }
  const partial = unsupported.length > 0;
  if (schemes.length === 0) {
    return { ok: false, reason: `No transliteration rule table for ${[...scripts].map(scriptName).join(', ')} yet. The native script is shown as written; a pack can add a character map.` };
  }
  return { ok: true, text: out, scheme: schemes.join(' + '), partial, unsupported: unsupported.map(scriptName) };
}
