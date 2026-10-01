#!/usr/bin/env node
// Build language × domain packs from the reviewable TSV sources in packs/src.
//   node tools/build-packs.mjs          write packs/<lang>/<domain>.json + packs/catalog.json
//   node tools/build-packs.mjs --check  fail if the committed packs are stale (CI)
// Output is deterministic: no timestamps, stable key order, sha256 per pack.

import { readFileSync, writeFileSync, readdirSync, mkdirSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, 'packs', 'src');
const OUT = join(ROOT, 'packs');
const check = process.argv.includes('--check');

const registry = JSON.parse(readFileSync(join(ROOT, 'data', 'languages.json'), 'utf8'));
const langs = new Map(registry.languages.map((l) => [l.code, l]));

const concepts = new Map();
for (const line of readFileSync(join(SRC, 'concepts.tsv'), 'utf8').split('\n')) {
  if (!line.trim() || line.startsWith('#')) continue;
  const [id, domain, gloss] = line.split('\t');
  if (concepts.has(id)) fail(`concepts.tsv: duplicate concept ${id}`);
  concepts.set(id, { domain, gloss, order: concepts.size });
}

function fail(msg) {
  console.error(`build-packs: ${msg}`);
  process.exit(1);
}

/** "谢谢{xièxie} ; 多谢" → {forms: ['谢谢','多谢'], readings: {谢谢: 'xièxie'}} */
function parseForms(text, where) {
  const forms = [];
  const readings = {};
  for (const raw of text.split(' ; ')) {
    const t = raw.trim();
    if (!t) fail(`${where}: empty form`);
    if (t === '∅') { forms.push(''); continue; }
    const m = t.match(/^(.*?)\{(.+)\}$/);
    const form = (m ? m[1] : t).trim().normalize('NFC');
    if (m) readings[form] = m[2].trim().normalize('NFC');
    forms.push(form);
  }
  return { forms, readings };
}

function parseCell(cell, where, lang) {
  const parts = cell.split(' | ');
  const first = parseForms(parts[0], where);
  const entry = { f: first.forms };
  const readings = { ...first.readings };
  for (const variant of parts.slice(1)) {
    const m = variant.match(/^([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*): (.+)$/);
    if (!m) fail(`${where}: bad dialect variant "${variant}"`);
    const tag = m[1];
    if (!langs.get(lang).dialects.some((d) => d[0] === tag || d[0].startsWith(tag + '-'))) fail(`${where}: dialect ${tag} is not registered for ${lang}`);
    const v = parseForms(m[2], where);
    entry.d = entry.d || {};
    entry.d[tag] = v.forms;
    Object.assign(readings, v.readings);
  }
  if (Object.keys(readings).length) entry.r = readings;
  return entry;
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value).sort()) out[k] = stable(value[k]);
    return out;
  }
  return value;
}

const catalog = { format: 'qbt-catalog/1', registryVersion: registry.version, packs: [] };
const report = [];
let stale = 0;

for (const file of readdirSync(SRC).filter((f) => f.endsWith('.tsv') && f !== 'concepts.tsv').sort()) {
  const lang = file.replace(/\.tsv$/, '');
  if (!langs.has(lang)) fail(`${file}: ${lang} is not in data/languages.json`);
  let rules = {};
  const norm = [];
  const byDomain = {};
  const seen = new Set();
  readFileSync(join(SRC, file), 'utf8').split('\n').forEach((line, i) => {
    const where = `${file}:${i + 1}`;
    if (!line.trim() || line.startsWith('#')) return;
    if (line.startsWith('@rules ')) { rules = JSON.parse(line.slice(7)); return; }
    if (line.startsWith('@norm ')) {
      const [from, to, dialect] = line.slice(6).split('\t');
      norm.push(dialect ? { dialect, from, to } : { from, to });
      return;
    }
    const tab = line.indexOf('\t');
    if (tab < 0) fail(`${where}: expected concept<TAB>forms`);
    const id = line.slice(0, tab);
    const c = concepts.get(id);
    if (!c) fail(`${where}: unknown concept ${id}`);
    if (seen.has(id)) fail(`${where}: duplicate concept ${id}`);
    seen.add(id);
    const entry = { c: id, ...parseCell(line.slice(tab + 1), where, lang) };
    (byDomain[c.domain] = byDomain[c.domain] || []).push(entry);
  });

  const missing = [...concepts.keys()].filter((id) => !seen.has(id));
  report.push(`${lang.padEnd(4)} ${String(seen.size).padStart(4)}/${concepts.size} concepts${missing.length ? `  (missing ${missing.length}: ${missing.slice(0, 6).join(', ')}${missing.length > 6 ? '…' : ''})` : ''}`);

  for (const domain of Object.keys(byDomain).sort()) {
    const entries = byDomain[domain].sort((a, b) => concepts.get(a.c).order - concepts.get(b.c).order);
    const meta = langs.get(lang);
    const pack = stable({
      format: 'qbt-pack/1',
      id: `${lang}/${domain}`,
      lang,
      domain,
      version: '1.0.0',
      title: `${meta.name} — ${domain === 'base' ? 'core' : domain}`,
      source: 'QueryBook Translate seed lexicon v1 (self-authored)',
      license: 'Self-owned; redistributable with QueryBook Translate',
      review: 'pending native-speaker review',
      rules: domain === 'base' ? rules : {},
      norm: domain === 'base' ? norm : [],
      entries,
    });
    const body = JSON.stringify(pack) + '\n';
    const dir = join(OUT, lang);
    const path = join(dir, `${domain}.json`);
    if (check) {
      if (!existsSync(path) || readFileSync(path, 'utf8') !== body) { console.error(`stale: packs/${lang}/${domain}.json`); stale++; }
    } else {
      mkdirSync(dir, { recursive: true });
      writeFileSync(path, body);
    }
    catalog.packs.push({
      id: pack.id, lang, domain, version: pack.version, entries: entries.length,
      bytes: Buffer.byteLength(body), sha256: createHash('sha256').update(body).digest('hex'),
      url: `packs/${lang}/${domain}.json`,
    });
  }
}

const catalogBody = JSON.stringify(stable(catalog), null, 1) + '\n';
const catalogPath = join(OUT, 'catalog.json');
if (check) {
  if (!existsSync(catalogPath) || readFileSync(catalogPath, 'utf8') !== catalogBody) { console.error('stale: packs/catalog.json'); stale++; }
  if (stale) fail(`${stale} file(s) stale — run node tools/build-packs.mjs`);
  console.log(`packs up to date (${catalog.packs.length} packs)`);
} else {
  writeFileSync(catalogPath, catalogBody);
  console.log(report.join('\n'));
  console.log(`wrote ${catalog.packs.length} packs + catalog.json`);
}
