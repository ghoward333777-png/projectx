// Language Pack Manager (spec §5, §8.1): download once, verify, keep on the
// device, load lazily, release when idle. Packs are modular along two axes —
// language and domain — so the device holds exactly the languages × domains in use.

import { storage } from './storage.js';
import { validatePack } from '../core/lexicon.js';

async function sha256(text) {
  if (!globalThis.crypto || !crypto.subtle) return null;
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export class PackManager {
  constructor({ engine, base = './', fetchImpl = (...a) => fetch(...a) } = {}) {
    this.engine = engine;
    this.base = base;
    this.fetch = fetchImpl;
    this.catalog = { packs: [] };
    this.installed = new Map(); // id → meta {id, lang, domain, version, bytes, sha256, entries, custom}
    this.loaded = new Set(); // pack ids currently in the engine
    this.cache = new Map(); // id → parsed pack (released on unload)
    this.store = null; // optional cloud QueryBook store {base, key}
  }

  /** Connect (or disconnect with null) a cloud QueryBook store as a second pack source. */
  setStore(store) {
    this.store = store && store.base ? store : null;
  }

  storeHeaders() {
    return this.store && this.store.key ? { authorization: `Bearer ${this.store.key}` } : {};
  }

  async init() {
    for (const id of await storage.keys('packs')) {
      const rec = await storage.get('packs', id);
      if (rec && rec.meta) this.installed.set(id, rec.meta);
    }
    this.catalog = (await storage.get('kv', 'catalog')) || { packs: [] };
    await this.refreshCatalog();
    return this;
  }

  /** Refresh the catalog when the network allows; otherwise keep the stored copy. */
  async refreshCatalog() {
    let bundled = null;
    let store = null;
    try {
      const res = await this.fetch(this.base + 'packs/catalog.json', { cache: 'no-cache' });
      if (res.ok) bundled = await res.json();
    } catch { /* offline: keep the stored copy */ }
    if (this.store) {
      try {
        const res = await this.fetch(this.store.base + 'catalog.json', { cache: 'no-cache', headers: this.storeHeaders() });
        if (res.ok) store = await res.json();
      } catch { /* store unreachable: bundled catalog still works */ }
    }
    if (!bundled && !store) return false;
    const previous = this.catalog.packs || [];
    const byId = new Map();
    for (const p of bundled ? bundled.packs : previous.filter((x) => x.source !== 'store')) byId.set(p.id, { ...p, source: 'bundled' });
    // Store packs override bundled ones with the same id: the store is the managed source.
    for (const p of store ? store.packs : this.store ? previous.filter((x) => x.source === 'store') : []) {
      byId.set(p.id, { ...p, source: 'store', url: /^https?:/.test(p.url) ? p.url : this.store.base + p.url.replace(/^packs\//, 'packs/') });
    }
    this.catalog = { format: 'qbt-catalog/1', packs: [...byId.values()].sort((a, b) => a.id.localeCompare(b.id)) };
    await storage.set('kv', 'catalog', this.catalog);
    return !!(store || !this.store);
  }

  available(lang) {
    return this.catalog.packs.filter((p) => !lang || p.lang === lang);
  }

  isInstalled(id) {
    return this.installed.has(id);
  }

  installedFor(lang) {
    return [...this.installed.values()].filter((m) => m.lang === lang);
  }

  updateAvailable(id) {
    const inst = this.installed.get(id);
    const cat = this.catalog.packs.find((p) => p.id === id);
    return !!(inst && cat && !inst.custom && cat.sha256 !== inst.sha256);
  }

  async install(id) {
    const entry = this.catalog.packs.find((p) => p.id === id);
    if (!entry) throw new Error(`Pack ${id} is not in the catalog`);
    const fromStore = entry.source === 'store';
    const res = await this.fetch(fromStore ? entry.url : this.base + entry.url, fromStore ? { headers: this.storeHeaders() } : undefined);
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    const text = await res.text();
    const digest = await sha256(text);
    if (digest && digest !== entry.sha256) throw new Error(`Integrity check failed for ${id}`);
    const pack = JSON.parse(text);
    const problems = validatePack(pack);
    if (problems.length) throw new Error(problems.join('; '));
    const meta = { id, lang: pack.lang, domain: pack.domain, version: pack.version, bytes: text.length, sha256: entry.sha256, entries: pack.entries.length, title: pack.title, review: pack.review || null, source: entry.source || 'bundled' };
    await storage.set('packs', id, { meta, text });
    this.installed.set(id, meta);
    if (this.loaded.has(id)) { this.engine.loadPack(pack); this.cache.set(id, pack); }
    return meta;
  }

  /** Import a pack file the user supplied (expandability without an app update). */
  async importText(text) {
    let pack;
    try { pack = JSON.parse(text); } catch { throw new Error('Not a JSON pack file'); }
    const problems = validatePack(pack);
    if (problems.length) throw new Error(problems.join('; '));
    if (!this.engine.language(pack.lang)) throw new Error(`Unknown language code ${pack.lang} — add it to data/languages.json first`);
    const id = pack.id;
    const meta = { id, lang: pack.lang, domain: pack.domain, version: pack.version, bytes: text.length, sha256: await sha256(text), entries: pack.entries.length, title: pack.title || id, review: pack.review || 'user-imported', custom: true };
    await storage.set('packs', id, { meta, text });
    this.installed.set(id, meta);
    return meta;
  }

  async remove(id) {
    this.unload(id);
    await storage.delete('packs', id);
    this.installed.delete(id);
  }

  async read(id) {
    if (this.cache.has(id)) return this.cache.get(id);
    const rec = await storage.get('packs', id);
    if (!rec) return null;
    const pack = JSON.parse(rec.text);
    this.cache.set(id, pack);
    return pack;
  }

  unload(id) {
    if (!this.loaded.has(id)) return;
    this.engine.unloadPack(id);
    this.loaded.delete(id);
    this.cache.delete(id);
  }

  /**
   * Make the engine hold exactly the installed packs of these languages
   * (base plus every installed domain overlay; the chosen domain only sets
   * sense priority). Packs of other languages are released.
   */
  async activate(langs) {
    const want = new Set();
    for (const lang of langs) for (const meta of this.installedFor(lang)) want.add(meta.id);
    for (const id of [...this.loaded]) if (!want.has(id)) this.unload(id);
    for (const id of [...want].sort()) {
      if (this.loaded.has(id)) continue;
      const pack = await this.read(id);
      if (pack) { this.engine.loadPack(pack); this.loaded.add(id); }
    }
    return [...this.loaded];
  }

  totalBytes() {
    let n = 0;
    for (const m of this.installed.values()) n += m.bytes;
    return n;
  }

  loadedBytes() {
    let n = 0;
    for (const id of this.loaded) n += (this.installed.get(id) || {}).bytes || 0;
    return n;
  }

  domains() {
    return [...new Set(this.catalog.packs.map((p) => p.domain).concat([...this.installed.values()].map((m) => m.domain)))].filter((d) => d !== 'base').sort();
  }
}

export async function storageEstimate() {
  try {
    if (navigator.storage && navigator.storage.estimate) return await navigator.storage.estimate();
  } catch { /* not exposed */ }
  return null;
}

export async function requestPersistence() {
  try {
    if (navigator.storage && navigator.storage.persist) return await navigator.storage.persist();
  } catch { /* not exposed */ }
  return false;
}
