// Service worker: makes the app shell available offline forever after the
// first visit. Language packs are stored by the app in IndexedDB, not here,
// so the device holds only the languages × domains the user installed.
const VERSION = 'qbt-shell-v1';
const SHELL = [
  './',
  'index.html',
  'app.css',
  'manifest.webmanifest',
  'data/languages.json',
  'packs/catalog.json',
  'icons/icon.svg',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/maskable-512.png',
  'icons/apple-touch-icon.png',
  'src/app.js',
  'src/core/engine.js',
  'src/core/g2p.js',
  'src/core/hygiene.js',
  'src/core/lexicon.js',
  'src/core/lid.js',
  'src/core/mt.js',
  'src/core/qc.js',
  'src/core/scripts.js',
  'src/core/tokenize.js',
  'src/core/translit.js',
  'src/platform/cloud.js',
  'src/platform/packs.js',
  'src/platform/speech.js',
  'src/platform/storage.js',
  'src/platform/native-bridge.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin) return; // cloud calls pass straight through
  // Catalog and config: network first (fresh when online), cache when offline.
  if (url.pathname.endsWith('/packs/catalog.json') || url.pathname.endsWith('/config.json')) {
    event.respondWith(fetch(event.request).then((res) => {
      const copy = res.clone();
      if (res.ok) caches.open(VERSION).then((c) => c.put(event.request, copy));
      return res;
    }).catch(() => caches.match(event.request).then((hit) => hit || new Response('{}', { headers: { 'content-type': 'application/json' } }))));
    return;
  }
  // Pack files go straight to the network; the app verifies and stores them itself.
  if (url.pathname.includes('/packs/')) return;
  event.respondWith(caches.match(event.request, { ignoreSearch: true }).then((hit) => hit || fetch(event.request)));
});
