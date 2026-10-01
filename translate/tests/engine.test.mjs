// Engine contract tests — run with: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TranslatorEngine } from '../src/core/engine.js';
import { runBattery } from '../src/core/qc.js';
import { normalize } from '../src/core/hygiene.js';
import { transliterate } from '../src/core/translit.js';
import { pronounce } from '../src/core/g2p.js';
import { validateCloudResult, plan } from '../src/platform/cloud.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => readFileSync(join(ROOT, p), 'utf8');
const registry = JSON.parse(read('data/languages.json'));
const catalog = JSON.parse(read('packs/catalog.json'));

function engine({ domains = null } = {}) {
  const e = new TranslatorEngine({ languages: registry });
  for (const p of catalog.packs) if (!domains || domains.includes(p.domain)) e.loadPack(JSON.parse(read(p.url)));
  return e;
}
const E = engine();
const T = (text, src, tgt, extra = {}) => E.translate({ text, src, tgt, ...extra });
const PACK_LANGS = [...new Set(catalog.packs.map((p) => p.lang))].sort();

test('registry covers 100+ languages with multiple dialects and many scripts', () => {
  const langs = registry.languages;
  assert.ok(langs.length >= 100, `${langs.length} languages`);
  assert.equal(new Set(langs.map((l) => l.code)).size, langs.length, 'codes are unique');
  assert.ok(langs.filter((l) => l.dialects.length > 1).length >= 30, 'many languages carry several dialects');
  assert.ok(new Set(langs.map((l) => l.script)).size >= 25, 'many scripts');
  for (const l of langs) {
    assert.ok(l.name && l.native && l.script && [1, 2, 3].includes(l.tier), `row ${l.code}`);
    assert.ok(l.dialects.length >= 1, `${l.code} has a dialect`);
  }
});

test('committed packs match their sources (deterministic build)', () => {
  execFileSync(process.execPath, [join(ROOT, 'tools/build-packs.mjs'), '--check'], { stdio: 'pipe' });
});

test('every Tier-1 language ships core, travel and medical packs', () => {
  for (const l of registry.languages.filter((x) => x.tier === 1)) {
    for (const d of ['base', 'travel', 'medical']) assert.ok(catalog.packs.some((p) => p.id === `${l.code}/${d}`), `${l.code}/${d}`);
  }
});

test('covenant: unknown words are passed through, flagged, never invented', () => {
  for (const lang of PACK_LANGS) {
    const r = T('Zqxv blorptastic', 'en', lang);
    assert.equal(r.coverage.percent, 0, lang);
    for (const s of r.segments.filter((x) => x.kind !== 'punct')) {
      assert.ok(s.flagged, `${lang}: ${s.source} flagged`);
      assert.equal(s.target, s.source, `${lang}: passed through unchanged`);
    }
  }
});

test('covenant: every rendered word carries source and target provenance', () => {
  for (const src of PACK_LANGS) {
    for (const tgt of PACK_LANGS) {
      const lex = E.lexicons.get(src);
      const sample = lex.packs[0].entries.slice(0, 20).map((e) => e.f[0]).filter(Boolean).join(' ');
      const r = T(sample, src, tgt);
      for (const s of r.segments) {
        if (['word', 'phrase', 'omitted'].includes(s.kind)) {
          assert.ok(s.provenance && s.provenance.source && s.provenance.target, `${src}→${tgt}: “${s.source}” has provenance`);
        }
        if (s.kind === 'unknown' || s.kind === 'gap') assert.ok(s.flagged);
      }
      assert.ok(r.coverage.percent >= 0 && r.coverage.percent <= 100);
    }
  }
});

test('deterministic: identical input gives identical output and fingerprint', () => {
  const a = T('Where is the hotel? I need a doctor, please.', 'en', 'ja');
  const b = engine().translate({ text: 'Where is the hotel? I need a doctor, please.', src: 'en', tgt: 'ja' });
  assert.equal(a.output, b.output);
  assert.equal(a.fingerprint, b.fingerprint);
  const shuffled = new TranslatorEngine({ languages: registry });
  for (const p of [...catalog.packs].reverse()) shuffled.loadPack(JSON.parse(read(p.url)));
  assert.equal(shuffled.translate({ text: 'Where is the hotel? I need a doctor, please.', src: 'en', tgt: 'ja' }).fingerprint, a.fingerprint, 'pack load order does not matter');
});

test('key phrases translate fully between every installed pair', () => {
  for (const src of PACK_LANGS) {
    const lex = E.lexicons.get(src);
    const phrase = lex.render('where_is_the_bathroom').form;
    for (const tgt of PACK_LANGS) {
      const r = T(phrase, src, tgt);
      assert.equal(r.coverage.percent, 100, `${src}→${tgt}: ${phrase} → ${r.output}`);
      assert.equal(r.segments.find((s) => s.concept).concept, 'where_is_the_bathroom');
    }
  }
});

test('phrase translations read naturally', () => {
  assert.equal(T('Where is the bathroom?', 'en', 'es').output, '¿Dónde está el baño?');
  assert.equal(T('Thank you very much!', 'en', 'fr').output, 'Merci beaucoup\u202F!');
  assert.equal(T('Where is the bathroom?', 'en', 'zh').output, '洗手间在哪里？');
  assert.equal(T('Where is the bathroom?', 'en', 'ar').output, 'أين الحمام؟');
  assert.equal(T('¿Dónde está el baño?', 'es', 'en').output, 'Where is the bathroom?');
});

test('dialects: rendering follows the target dialect', () => {
  assert.equal(T('bus', 'en', 'es', { tgtDialect: 'es-MX' }).output, 'Camión');
  assert.equal(T('bus', 'en', 'es', { tgtDialect: 'es-AR' }).output, 'Colectivo');
  assert.equal(T('bus', 'en', 'pt', { tgtDialect: 'pt-PT' }).output, 'Autocarro');
  assert.equal(T('bus', 'en', 'pt', { tgtDialect: 'pt-BR' }).output, 'Ônibus');
  assert.equal(T('taxi', 'en', 'zh', { tgtDialect: 'zh-TW' }).output, '計程車');
  assert.equal(T('breakfast', 'en', 'fr', { tgtDialect: 'fr-CA' }).output, 'Déjeuner');
  assert.equal(T('breakfast', 'en', 'fr', { tgtDialect: 'fr-FR' }).output, 'Petit-déjeuner');
  assert.equal(T('how much is this', 'en', 'ar', { tgtDialect: 'ar-EG' }).output, 'ده بكام');
  assert.equal(T('the bill please', 'en', 'en', { tgtDialect: 'en-GB' }).output, 'The bill please');
});

test('dialects: source dialect is detected from dialect-specific words', () => {
  const r = T('فين الحمام', 'auto', 'en');
  assert.equal(r.src, 'ar');
  assert.equal(r.lid.dialect.tag, 'ar-EG');
  assert.equal(r.output, 'Where is the bathroom');
  assert.equal(T('el colectivo', 'auto', 'en').lid.dialect.tag, 'es-AR');
});

test('domain packs disambiguate senses (medical "cold" vs temperature)', () => {
  assert.equal(T('cold', 'en', 'es').segments[0].concept, 'cold');
  assert.equal(T('cold', 'en', 'es', { domain: 'medical' }).segments[0].concept, 'cold_illness');
  assert.equal(T('cold', 'en', 'es', { domain: 'medical' }).output, 'Resfriado');
});

test('modular packs: removing a domain pack removes exactly its vocabulary', () => {
  const baseOnly = engine({ domains: ['base'] });
  const r = baseOnly.translate({ text: 'passport', src: 'en', tgt: 'de' });
  assert.equal(r.coverage.percent, 0);
  assert.ok(r.segments[0].flagged);
  assert.equal(T('passport', 'en', 'de').output, 'Reisepass');
});

test('language ID: confident when clear, asks when ambiguous', () => {
  for (const [text, lang] of [['Où sont les toilettes', 'fr'], ['Wo ist der Bahnhof', 'de'], ['Спасибо', 'ru'], ['감사합니다', 'ko'], ['ありがとう', 'ja'], ['谢谢', 'zh'], ['شكرا', 'ar'], ['धन\u094Dयवाद', 'hi'], ['Obrigado', 'pt'], ['Grazie mille', 'it']]) {
    const d = E.detect(text);
    assert.equal(d.best, lang, text);
    assert.ok(!d.needsConfirmation, `${text} confident (${d.confidence})`);
  }
  assert.ok(E.detect('no').needsConfirmation, '"no" is ambiguous across languages');
  assert.equal(E.detect('Καλημέρα').best, 'el', 'unique script identifies a language without a pack');
});

test('inflection, elision, compounds and particles resolve to dictionary entries', () => {
  assert.equal(T('tickets', 'en', 'de').segments[0].concept, 'ticket');
  assert.equal(T("l'hôtel", 'fr', 'en').output, 'The hotel');
  const de = T('Bahnhofstraße', 'de', 'en');
  assert.deepEqual(de.segments.map((s) => s.concept), ['train_station', 'street']);
  const ko = T('저는 커피를 원해요', 'ko', 'en');
  assert.equal(ko.coverage.percent, 100);
  assert.ok(ko.segments.some((s) => s.kind === 'omitted' && s.matchedBy === 'particle'));
});

test('hygiene: NFC, invisible characters, exotic spaces, full-width forms; ZWNJ kept', () => {
  const n = normalize('Ｈｅｌｌｏ\u00A0wor\u200Bld  \uFEFFcafe\u0301\u3000test');
  assert.equal(n.text, 'Hello world café test');
  assert.equal(normalize('می\u200Cخواهم').text, 'می\u200Cخواهم');
  assert.equal(T('ｗｈｅｒｅ\u3000ｉｓ\u3000ｔｈｅ\u3000ｂａｔｈｒｏｏｍ？', 'en', 'es').output, '¿Dónde está el baño?');
});

test('numbers and names are preserved exactly', () => {
  const r = T('I want 2 coffee', 'en', 'es');
  assert.ok(r.output.includes('2'));
  const n = T('Hello Maria', 'en', 'es');
  assert.ok(n.output.includes('Maria'));
  assert.equal(n.segments.find((s) => s.source === 'Maria').provenance.type, 'name');
});

test('transliteration covers major scripts and refuses honestly otherwise', () => {
  assert.equal(transliterate('Спасибо', 'ru').text, 'Spasibo');
  assert.equal(transliterate('감사합니다', 'ko').text, 'gamsahamnida');
  assert.equal(transliterate('ありがとう', 'ja').text, 'arigatou');
  assert.equal(transliterate('नमस\u094Dत\u0947', 'hi').text, 'namaste');
  assert.equal(transliterate('Καλημέρα', 'el').text, 'Kalimera');
  assert.equal(transliterate('ሰላም', 'am').text, 'selam');
  assert.equal(transliterate('გამარჯობა', 'ka').text, 'gamarjoba');
  const thai = transliterate('สว\u0E31สด\u0E35', 'th');
  assert.equal(thai.ok, false);
  assert.match(thai.reason, /No transliteration rule table/);
  assert.equal(T('thank you', 'en', 'zh').transliteration.text, 'xièxie');
});

test('pronunciation: rule tables give IPA with syllables; stress only where decidable', () => {
  assert.equal(pronounce('gracias', 'es', { dialect: 'es-MX' }).ipa, 'ˈɡɾa.sjas');
  assert.equal(pronounce('gracias', 'es', { dialect: 'es-ES' }).ipa, 'ˈɡɾa.θjas');
  assert.equal(pronounce('città', 'it').ipa, 'tʃit.ˈta');
  assert.equal(pronounce('grazie', 'it').ipa, 'ɡrat.tsje', 'unwritten Italian stress is not guessed');
  assert.equal(pronounce('감사합니다', 'ko').ipa, 'kam.sa.ham.ni.da');
  assert.equal(pronounce('ちょっと', 'ja').ipa, 'tɕo.tːo');
  assert.equal(pronounce('नमस\u094Dत\u0947', 'hi').ipa, 'nə.məs.t\u032Aeː');
  assert.equal(pronounce('hello', 'en').ok, false);
  assert.equal(T('Hello', 'en', 'ja').pronunciation.ipa, 'ko.ɴ.ɲi.tɕi.wa', 'particle は read as wa from the dictionary reading');
});

test('QC battery passes for every shipped language', () => {
  for (const lang of PACK_LANGS) {
    const r = runBattery(E, lang, { partner: lang === 'en' ? 'es' : 'en' });
    assert.equal(r.failed, 0, `${lang}: ${r.checks.filter((c) => c.severity === 'fail').map((c) => c.label + ' — ' + c.detail).join('; ')}`);
  }
});

test('performance: on-device translation is far inside the 500 ms budget', () => {
  const text = 'Hello, where is the train station? I need a ticket and a taxi to the airport, please. Thank you very much!';
  const t0 = performance.now();
  for (let i = 0; i < 50; i++) T(text, 'en', PACK_LANGS[i % PACK_LANGS.length]);
  const per = (performance.now() - t0) / 50;
  assert.ok(per < 100, `${per.toFixed(1)} ms per translation`);
});

test('footprint: every pack stays tiny (spec Tier-3 budget < 3 MB)', () => {
  for (const p of catalog.packs) assert.ok(p.bytes < 3 * 1024 * 1024, p.id);
  const perLang = {};
  for (const p of catalog.packs) perLang[p.lang] = (perLang[p.lang] || 0) + p.bytes;
  for (const [l, b] of Object.entries(perLang)) assert.ok(b < 200 * 1024, `${l}: ${b} bytes`);
});

test('cloud results without coverage or provenance are rejected', () => {
  assert.match(validateCloudResult({ output: 'x' }), /coverage/);
  assert.match(validateCloudResult({ output: 'x', coverage: { percent: 90 }, segments: [{ source: 'a', target: 'b' }] }), /provenance/);
  assert.equal(validateCloudResult({ output: 'b', coverage: { percent: 100 }, segments: [{ source: 'a', target: 'b', provenance: { engine: 'qb-cloud' } }] }), null);
});

test('cloud is never on the critical path: offline, opt-out or no gateway → local', () => {
  const base = { cloudOptIn: true, gatewayUrl: 'https://gw.example', forceOffline: false, cloudBelowCoverage: 70 };
  assert.equal(plan(base, { coverage: 10, online: true }).mt, 'cloud');
  assert.equal(plan(base, { coverage: 10, online: false }).mt, 'local');
  assert.equal(plan({ ...base, forceOffline: true }, { coverage: 10, online: true }).mt, 'local');
  assert.equal(plan({ ...base, cloudOptIn: false }, { coverage: 10, online: true }).mt, 'local');
  assert.equal(plan({ ...base, gatewayUrl: '' }, { coverage: 10, online: true }).mt, 'local');
  assert.equal(plan(base, { coverage: 100, words: 3, online: true }).mt, 'local');
});

test('service worker precaches every app source file', () => {
  const sw = read('sw.js');
  const walk = (dir) => readdirSync(join(ROOT, dir), { withFileTypes: true }).flatMap((d) => (d.isDirectory() ? walk(`${dir}/${d.name}`) : [`${dir}/${d.name}`]));
  for (const f of walk('src')) assert.ok(sw.includes(`'${f}'`), `${f} missing from sw.js SHELL`);
});
