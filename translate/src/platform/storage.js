// Minimal IndexedDB key-value store with an in-memory fallback (private
// windows, blocked storage). Everything the app keeps on the device lives here:
// installed packs, settings, phrasebook. Nothing is sent anywhere.

const DB_NAME = 'querybook-translate';
const DB_VERSION = 1;
const STORES = ['packs', 'kv'];

let dbPromise = null;
const memory = { packs: new Map(), kv: new Map() };
let persistent = true;

function open() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      if (typeof indexedDB === 'undefined') throw new Error('no IndexedDB');
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        for (const s of STORES) if (!req.result.objectStoreNames.contains(s)) req.result.createObjectStore(s);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => { persistent = false; resolve(null); };
      req.onblocked = () => { persistent = false; resolve(null); };
    } catch {
      persistent = false;
      resolve(null);
    }
  });
  return dbPromise;
}

function tx(db, store, mode, fn) {
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const s = t.objectStore(store);
    const result = fn(s);
    t.oncomplete = () => resolve(result && 'result' in result ? result.result : undefined);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

export const storage = {
  get isPersistent() {
    return persistent;
  },
  async get(store, key) {
    const db = await open();
    if (!db) return memory[store].get(key);
    return tx(db, store, 'readonly', (s) => s.get(key));
  },
  async set(store, key, value) {
    const db = await open();
    if (!db) { memory[store].set(key, value); return; }
    await tx(db, store, 'readwrite', (s) => s.put(value, key));
  },
  async delete(store, key) {
    const db = await open();
    if (!db) { memory[store].delete(key); return; }
    await tx(db, store, 'readwrite', (s) => s.delete(key));
  },
  async keys(store) {
    const db = await open();
    if (!db) return [...memory[store].keys()];
    return tx(db, store, 'readonly', (s) => s.getAllKeys());
  },
};
