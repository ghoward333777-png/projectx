// The on-device deterministic core (spec §5, §6): normalize → language/dialect
// ID → dictionary MT with coverage and provenance → transliteration →
// pronunciation. Stateless per call apart from the loaded packs, so packs can
// be loaded and released freely (spec §8 dynamic load/unload).

import { normalize } from './hygiene.js';
import { Lexicon } from './lexicon.js';
import { translate as mtTranslate, resultFingerprint } from './mt.js';
import { detectLanguage } from './lid.js';
import { transliterate } from './translit.js';
import { pronounce, hasRules } from './g2p.js';
import { isRtl, isUnspaced } from './scripts.js';

const CJK_PUNCT = { '？': '?', '！': '!', '。': '.', '、': ',', '，': ',', '：': ':', '；': ';', '؟': '?', '،': ',', '؛': ';', '।': '.' };
function asciiPunct(t) {
  if (!t.ok) return t;
  return { ...t, text: t.text.replace(/[？！。、，：；؟،؛।]/g, (c) => CJK_PUNCT[c]).replace(/ ([,.?!;:])/g, '$1') };
}

const defaultClock = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

export class TranslatorEngine {
  constructor({ languages, clock = defaultClock } = {}) {
    if (!languages || !Array.isArray(languages.languages)) throw new Error('TranslatorEngine needs the language registry');
    this.registryVersion = languages.version;
    this.languages = languages.languages;
    this.byCode = new Map(this.languages.map((l) => [l.code, l]));
    this.lexicons = new Map();
    this.clock = clock;
  }

  language(code) {
    return this.byCode.get(code) || null;
  }

  /** Dialect row [tag, name, script?, speechTag?] or null. */
  dialect(code, tag) {
    const lang = this.language(code);
    if (!lang || !tag) return null;
    return lang.dialects.find((d) => d[0] === tag) || null;
  }

  defaultDialect(code) {
    const lang = this.language(code);
    return lang ? lang.dialects[0][0] : null;
  }

  scriptFor(code, dialectTag) {
    const d = this.dialect(code, dialectTag);
    if (d && d[2]) return d[2];
    const lang = this.language(code);
    return lang ? lang.script : 'Latn';
  }

  direction(code, dialectTag) {
    return isRtl(this.scriptFor(code, dialectTag)) ? 'rtl' : 'ltr';
  }

  /** BCP-47 tag for speech engines (ASR/TTS) for a language + dialect. */
  speechTag(code, dialectTag) {
    const d = this.dialect(code, dialectTag) || (this.language(code) ? this.language(code).dialects[0] : null);
    if (!d) return code;
    return d[3] || d[0];
  }

  // ---- pack management ----
  loadPack(pack) {
    if (!this.byCode.has(pack.lang)) throw new Error(`Pack ${pack.id} targets unknown language ${pack.lang}`);
    if (!this.lexicons.has(pack.lang)) this.lexicons.set(pack.lang, new Lexicon(pack.lang));
    this.lexicons.get(pack.lang).addPack(pack);
  }

  unloadPack(id) {
    for (const [lang, lex] of this.lexicons) {
      lex.removePack(id);
      if (lex.packs.length === 0) this.lexicons.delete(lang);
    }
  }

  unloadLanguage(code) {
    this.lexicons.delete(code);
  }

  loadedLanguages() {
    return [...this.lexicons.keys()].sort();
  }

  // ---- pipeline ----
  detect(text) {
    const n = normalize(text);
    return detectLanguage(n.text, { languages: this.languages, lexicons: this.lexicons });
  }

  /**
   * @param {{text, src: string|'auto', tgt, srcDialect?, tgtDialect?, domain?}} req
   */
  translate(req) {
    const t = {};
    const mark = (k, t0) => { t[k] = Math.round((this.clock() - t0) * 100) / 100; };
    let t0 = this.clock();
    const hyg = normalize(req.text);
    mark('normalize', t0);

    let src = req.src;
    let srcDialect = req.srcDialect || null;
    let lid = null;
    t0 = this.clock();
    if (!src || src === 'auto') {
      lid = detectLanguage(hyg.text, { languages: this.languages, lexicons: this.lexicons });
      src = lid.best || 'und';
      if (lid.dialect && !srcDialect) srcDialect = lid.dialect.tag;
    }
    mark('lid', t0);
    if (!srcDialect && this.language(src)) srcDialect = this.defaultDialect(src);
    const tgt = req.tgt;
    const tgtDialect = req.tgtDialect || this.defaultDialect(tgt);

    t0 = this.clock();
    const r = mtTranslate({
      text: hyg.text, src, tgt, srcDialect, tgtDialect, domain: req.domain || null,
      srcLex: this.lexicons.get(src) || null,
      tgtLex: this.lexicons.get(tgt) || null,
      srcScript: this.scriptFor(src, srcDialect),
      tgtScript: this.scriptFor(tgt, tgtDialect),
    });
    mark('mt', t0);

    t0 = this.clock();
    r.transliteration = asciiPunct(this.transliterateResult(r));
    mark('transliterate', t0);
    t0 = this.clock();
    r.pronunciation = this.pronounceResult(r);
    mark('pronounce', t0);

    r.hygiene = hyg.changes;
    r.lid = lid;
    r.direction = this.direction(tgt, tgtDialect);
    r.sourceDirection = this.direction(src, srcDialect);
    r.timings = t;
    r.fingerprint = resultFingerprint(r);
    return r;
  }

  /** Reading-aware text: dictionary readings (pinyin, kana) where an entry carries one. */
  readingText(result) {
    const unspaced = isUnspaced(this.scriptFor(result.tgt, result.tgtDialect));
    const parts = result.segments.filter((s) => s.kind !== 'omitted' && s.target !== '').map((s) => s.reading || s.target);
    return { text: parts.join(unspaced ? ' ' : ' ').replace(/ ([,.?!;:，。？！、])/g, '$1'), full: result.segments.every((s) => s.reading || !/\p{Script=Han}/u.test(s.target)) };
  }

  transliterateResult(result) {
    const lex = this.lexicons.get(result.tgt);
    const packMap = lex && lex.rules.translit ? lex.rules.translit : null;
    if (result.tgt === 'zh' || result.tgt === 'yue') {
      const rt = this.readingText(result);
      if (!/\p{Script=Han}/u.test(result.output)) return transliterate(result.output, result.tgt);
      return rt.full
        ? { ok: true, text: rt.text, scheme: 'Hanyu Pinyin (from dictionary readings)', partial: false }
        : { ok: true, text: rt.text, scheme: 'Hanyu Pinyin (from dictionary readings)', partial: true, unsupported: ['Han characters without a dictionary reading'] };
    }
    if (result.tgt === 'ja') {
      const rt = this.readingText(result);
      const tr = transliterate(rt.text, 'ja');
      if (tr.ok && /\p{Script=Han}/u.test(rt.text)) return { ...tr, partial: true, unsupported: ['Kanji without a dictionary reading'] };
      return tr.ok ? { ...tr, scheme: tr.scheme + (rt.text !== result.output ? ' (from dictionary readings)' : '') } : tr;
    }
    return transliterate(result.output, result.tgt, { packMap });
  }

  pronounceResult(result) {
    if (!result.output) return { ok: false, reason: 'Nothing to pronounce.' };
    const ipas = result.segments.filter((s) => s.ipa).map((s) => s.ipa);
    if (ipas.length && ipas.length === result.segments.filter((s) => s.kind === 'word' || s.kind === 'phrase').length) {
      return { ok: true, ipa: ipas.join(' '), syllables: null, method: 'dictionary pronunciation', notes: [] };
    }
    if (result.tgt === 'zh') {
      return { ok: false, reason: 'Mandarin pronunciation is given as Pinyin (with tone marks) in the transliteration line.' };
    }
    // Only dictionary-rendered words are transcribed: target-language rules must not
    // be applied to source words that were passed through untranslated.
    const rendered = result.segments.filter((s) => !s.flagged && s.target && (s.kind === 'word' || s.kind === 'phrase'));
    if (!rendered.length) return { ok: false, reason: 'Nothing translated to pronounce.' };
    const text = rendered.map((s) => s.target).join(' ');
    const reading = result.tgt === 'ja' ? rendered.map((s) => s.reading || s.target).join('') : null;
    const p = pronounce(text, result.tgt, { dialect: result.tgtDialect, reading });
    if (p.ok && result.segments.some((s) => s.flagged)) p.notes = [...p.notes, 'untranslated words are not transcribed'];
    return p;
  }

  /** Pronounce arbitrary text in a language (phrasebook, typed text). */
  pronounce(text, lang, dialect) {
    return pronounce(normalize(text).text, lang, { dialect });
  }

  transliterate(text, lang) {
    const lex = this.lexicons.get(lang);
    return transliterate(normalize(text).text, lang, { packMap: lex && lex.rules.translit ? lex.rules.translit : null });
  }

  capabilities(code) {
    const lang = this.language(code);
    const lex = this.lexicons.get(code);
    return {
      dictionary: !!lex,
      entries: lex ? lex.entryCount : 0,
      domains: lex ? lex.domains : [],
      pronunciationRules: hasRules(code),
      transliteration: lang ? lang.script !== 'Latn' : false,
      script: lang ? lang.script : null,
      direction: lang ? (isRtl(lang.script) ? 'rtl' : 'ltr') : 'ltr',
    };
  }
}
