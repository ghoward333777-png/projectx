// Per-language lexicon assembled from a base pack plus any domain overlays.
// Every entry maps surface forms to a language-independent concept id; the
// concept id is the pivot, so any installed language translates to any other
// without an English middle step. Each hit carries its provenance (pack id,
// version, domain, concept, dialect) so the trust layer can show its source.

import { formKey } from './tokenize.js';
import { foldKey, lower } from './hygiene.js';
import { charScript, isUnspaced } from './scripts.js';

export const PACK_FORMAT = 'qbt-pack/1';

/** Validate a pack object; returns a list of problems (empty when valid). */
export function validatePack(pack) {
  const problems = [];
  if (!pack || typeof pack !== 'object') return ['pack is not an object'];
  if (pack.format !== PACK_FORMAT) problems.push(`format must be ${PACK_FORMAT}`);
  for (const k of ['id', 'lang', 'domain', 'version']) if (typeof pack[k] !== 'string' || !pack[k]) problems.push(`missing ${k}`);
  if (!Array.isArray(pack.entries)) problems.push('entries must be an array');
  else {
    pack.entries.forEach((e, i) => {
      if (!e || typeof e.c !== 'string' || !Array.isArray(e.f)) problems.push(`entry ${i}: needs c (concept) and f (forms)`);
      else if (e.f.length === 0) problems.push(`entry ${i} (${e.c}): no forms`);
    });
  }
  return problems;
}

function scriptOf(form) {
  for (const ch of form) {
    const s = charScript(ch);
    if (s !== 'Zyyy' && s !== 'Zinh') return s;
  }
  return 'Latn';
}

export class Lexicon {
  constructor(lang) {
    this.lang = lang;
    this.packs = [];
    this.rules = {};
    this.rebuild();
  }

  lower(w) {
    return lower(w, this.lang);
  }

  addPack(pack) {
    const problems = validatePack(pack);
    if (problems.length) throw new Error(`Invalid pack ${pack?.id ?? '?'}: ${problems.join('; ')}`);
    if (pack.lang !== this.lang) throw new Error(`Pack ${pack.id} is for ${pack.lang}, not ${this.lang}`);
    this.packs = this.packs.filter((p) => p.id !== pack.id);
    this.packs.push(pack);
    // Base first, then overlays alphabetically: load order never changes results.
    this.packs.sort((a, b) => (a.domain === 'base' ? -1 : b.domain === 'base' ? 1 : a.domain.localeCompare(b.domain)));
    this.rebuild();
  }

  removePack(id) {
    this.packs = this.packs.filter((p) => p.id !== id);
    this.rebuild();
  }

  get domains() {
    return this.packs.map((p) => p.domain);
  }

  get entryCount() {
    return this.packs.reduce((n, p) => n + p.entries.length, 0);
  }

  rebuild() {
    this.spaced = new Map(); // "dónde está" → candidates
    this.folded = new Map(); // accent-insensitive second chance
    this.chars = new Map(); // unspaced-script keys (Han, Kana, Thai…)
    this.concepts = new Map(); // concept → [{pack, entry}]
    this.norm = []; // colloquial → standard normalizations
    this.maxTokens = 1;
    this.maxChars = 1;
    this.rules = {};
    let order = 0;
    for (const pack of this.packs) {
      Object.assign(this.rules, pack.rules || {});
      for (const n of pack.norm || []) this.norm.push({ ...n, pack: pack.id });
      for (const entry of pack.entries) {
        if (!this.concepts.has(entry.c)) this.concepts.set(entry.c, []);
        this.concepts.get(entry.c).push({ pack, entry });
        const variants = [[null, entry.f]];
        for (const [tag, forms] of Object.entries(entry.d || {}).sort(([a], [b]) => a.localeCompare(b))) variants.push([tag, forms]);
        const defaults = new Set(entry.f.map((f) => this.lower(f)));
        for (const [dialect, forms] of variants) {
          forms.forEach((form, i) => {
            if (!form) return; // "" = no equivalent in this language; never matched as source
            const key = formKey(form, (w) => this.lower(w));
            if (!key) return;
            const cand = {
              concept: entry.c, form, pack: pack.id, version: pack.version, domain: pack.domain,
              dialect: dialect && !defaults.has(this.lower(form)) ? dialect : null,
              primary: i === 0, order: order++,
            };
            const script = scriptOf(form);
            if (isUnspaced(script) && !key.includes(' ')) {
              this.push(this.chars, key, cand);
              this.maxChars = Math.max(this.maxChars, [...key].length);
            } else {
              this.push(this.spaced, key, cand);
              const fk = key.split(' ').map((w) => foldKey(w, scriptOf(w))).join(' ');
              if (fk !== key) this.push(this.folded, fk, cand);
              this.maxTokens = Math.max(this.maxTokens, key.split(' ').length);
            }
          });
        }
      }
    }
  }

  push(map, key, cand) {
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(cand);
  }

  /** Candidates for a spaced key, exact first, then accent-insensitive. */
  lookup(key) {
    const exact = this.spaced.get(key);
    if (exact) return { cands: exact, how: 'exact' };
    const fk = key.split(' ').map((w) => foldKey(w, scriptOf(w))).join(' ');
    const folded = this.folded.get(fk) || (fk !== key ? this.spaced.get(fk) : undefined);
    if (folded) return { cands: folded, how: 'accent-insensitive' };
    return null;
  }

  lookupChars(key) {
    const c = this.chars.get(key);
    return c ? { cands: c, how: 'exact' } : null;
  }

  /**
   * Render a concept in this language.
   * Dialect: exact tag → language default. Domain: the active domain's pack wins.
   * @returns {null | {form, alternatives, reading, pack, version, domain, dialect, omitted}}
   */
  render(concept, dialect, domain) {
    const rows = this.concepts.get(concept);
    if (!rows) return null;
    const ranked = [...rows].sort((a, b) => rank(a.pack.domain, domain) - rank(b.pack.domain, domain));
    const { pack, entry } = ranked[0];
    let forms = entry.f;
    let usedDialect = null;
    if (dialect && entry.d) {
      const tag = Object.keys(entry.d).find((t) => t === dialect) || Object.keys(entry.d).find((t) => dialect.startsWith(t + '-'));
      if (tag) {
        forms = entry.d[tag];
        usedDialect = tag;
      }
    }
    const form = forms[0];
    return {
      form,
      alternatives: forms.slice(1).filter(Boolean),
      reading: entry.r ? entry.r[form] ?? null : null,
      ipa: entry.p ? entry.p[form] ?? null : null,
      pack: pack.id,
      version: pack.version,
      domain: pack.domain,
      dialect: usedDialect,
      omitted: form === '',
      note: entry.n || null,
    };
  }

  /** Apply the pack's colloquial→standard normalization for the active dialect. */
  normalizeColloquial(text, dialect) {
    let out = text;
    const applied = [];
    for (const n of this.norm) {
      if (n.dialect && dialect && !dialect.startsWith(n.dialect)) continue;
      const re = new RegExp(`(^|[^\\p{L}\\p{M}])${escapeRe(n.from)}(?=$|[^\\p{L}\\p{M}])`, 'giu');
      if (re.test(out)) {
        out = out.replace(re, (_, pre) => pre + n.to);
        applied.push({ from: n.from, to: n.to, pack: n.pack });
      }
    }
    return { text: out, applied };
  }
}

function rank(packDomain, active) {
  if (active && packDomain === active) return 0;
  if (packDomain === 'base') return 1;
  return 2;
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Rank source candidates deterministically: active domain, base, dialect match, primary form, entry order. */
export function pickCandidate(cands, domain, dialect) {
  return [...cands].sort((a, b) =>
    rank(a.domain, domain) - rank(b.domain, domain)
    || (b.dialect && dialect && dialect.startsWith(b.dialect) ? 1 : 0) - (a.dialect && dialect && dialect.startsWith(a.dialect) ? 1 : 0)
    || (b.primary ? 1 : 0) - (a.primary ? 1 : 0)
    || a.order - b.order)[0];
}
