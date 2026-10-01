// QueryBook Translate — app controller. All core work happens in the
// deterministic engine on the device; this file only wires UI, packs, speech
// and the optional cloud together.

import { TranslatorEngine } from './core/engine.js';
import { runBattery } from './core/qc.js';
import { scriptName } from './core/scripts.js';
import { PackManager, storageEstimate, requestPersistence } from './platform/packs.js';
import { storage } from './platform/storage.js';
import { asr, tts, onVoicesChanged } from './platform/speech.js';
import { plan, cloudTranslate, isOnline } from './platform/cloud.js';
import { installNativeBridge } from './platform/native-bridge.js';

const nativeShell = installNativeBridge(); // 'android' | 'ios' | null (browser / installed PWA)

const $ = (id) => document.getElementById(id);

/** Tiny DOM builder: h('div', {class:'x', onclick}, 'text', child) — text is always text, never HTML. */
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}

const DEFAULT_SETTINGS = {
  forceOffline: false,
  cloudOptIn: false,
  gatewayUrl: '',
  storeUrl: '',
  storeKey: '',
  storeConnected: false,
  cloudBelowCoverage: 70,
  forceCloud: false,
  telemetryOptIn: false,
  saveHistory: false,
  showTranslit: true,
  showIpa: true,
  speechRate: 0.95,
  preferOnDeviceAsr: true,
  theme: 'system',
  logging: false,
};

const ESSENTIALS = [
  ['Greetings', ['hello', 'good_morning', 'goodbye', 'please', 'thank_you', 'youre_welcome', 'excuse_me', 'sorry', 'yes', 'no']],
  ['Talking', ['i_dont_understand', 'do_you_speak_english', 'speak_slowly', 'repeat_please', 'what_is_your_name', 'my_name_is', 'nice_to_meet_you']],
  ['Getting around', ['where_is_the_bathroom', 'where_is', 'how_much_is_this', 'too_expensive', 'i_am_lost', 'train_station', 'airport', 'hotel', 'left', 'right', 'straight_ahead']],
  ['Food', ['table_for_two', 'the_bill_please', 'i_would_like', 'water', 'vegetarian', 'coffee']],
  ['Emergency', ['help', 'call_the_police', 'i_need_a_doctor', 'call_an_ambulance', 'it_hurts_here', 'i_am_allergic_to', 'i_cant_breathe', 'hospital', 'pharmacy']],
];

const app = {
  engine: null,
  packs: null,
  settings: { ...DEFAULT_SETTINGS },
  config: {},
  state: { src: 'auto', tgt: 'es', srcDialect: null, tgtDialect: null, domain: 'base', spokenSrc: null },
  last: null,
  lastLocal: null,
  usage: { local: 0, cloud: 0, cloudFailed: 0 },
  speechTimings: { asr: null, tts: null },
  qc: null,
  phrasebook: [],
  pbFilter: 'All',
  langFilter: 'Installed',
  picking: null,
  stopListening: null,
  runToken: 0,
};
window.qbt = app; // handy for power users in the console

// ---------------------------------------------------------------- boot
async function boot() {
  const [registry, config] = await Promise.all([
    fetch('data/languages.json').then((r) => r.json()),
    fetch('config.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
  ]);
  app.config = config || {};
  app.engine = new TranslatorEngine({ languages: registry });
  const saved = (await storage.get('kv', 'settings')) || {};
  app.settings = { ...DEFAULT_SETTINGS, ...presetFromConfig(app.config), ...saved };
  applyTheme();
  app.packs = new PackManager({ engine: app.engine });
  app.packs.setStore(storeSource());
  await app.packs.init();
  Object.assign(app.state, (await storage.get('kv', 'state')) || {});
  app.phrasebook = (await storage.get('kv', 'phrasebook')) || [];

  if (app.packs.installed.size === 0) await firstRun();
  if (!app.engine.language(app.state.tgt)) app.state.tgt = 'es';
  if (app.state.src !== 'auto' && !app.engine.language(app.state.src)) app.state.src = 'auto';

  wire();
  renderLangbar();
  await activate();
  renderNetBadge();
  renderEssentials();
  renderPhrasebook();
  if (!nativeShell && 'serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => {});
  requestPersistence();
  const deep = new URLSearchParams(location.search);
  if (deep.get('text')) { $('input').value = deep.get('text'); run(); }
  if (['converse', 'phrasebook', 'packs', 'monitor'].includes(deep.get('mode'))) showView(deep.get('mode'));
  window.addEventListener('qbt-voices', () => { if (app.last) renderResult(app.last); });
}

function presetFromConfig(cfg) {
  const p = {};
  if (cfg.storeUrl) p.storeUrl = cfg.storeUrl;
  if (cfg.storeKey) p.storeKey = cfg.storeKey;
  if (cfg.gatewayUrl) p.gatewayUrl = cfg.gatewayUrl;
  if (typeof cfg.cloudOptIn === 'boolean') p.cloudOptIn = cfg.cloudOptIn;
  if (typeof cfg.storeConnected === 'boolean') p.storeConnected = cfg.storeConnected;
  return p;
}

function storeSource() {
  const s = app.settings;
  return s.storeConnected && s.storeUrl && !s.forceOffline ? { base: s.storeUrl.replace(/\/?$/, '/'), key: s.storeKey || '' } : null;
}

/** First run: install core packs for English, the device language and the default target. */
async function firstRun() {
  const device = (navigator.language || 'en').split('-')[0];
  const want = [...new Set(['en', device, app.state.tgt])];
  for (const lang of want) {
    // Core + every domain overlay: a few KB each, and emergency phrases must work offline from day one.
    for (const p of app.packs.available(lang)) {
      try { await app.packs.install(p.id); } catch { /* offline first run: user can install later */ }
    }
  }
  if (device !== 'en' && app.packs.available(device).length) app.state.tgt = device === app.state.tgt ? 'en' : app.state.tgt;
}

async function saveSettings() {
  await storage.set('kv', 'settings', app.settings);
}
async function saveState() {
  await storage.set('kv', 'state', app.state);
}

function applyTheme() {
  const t = app.settings.theme;
  if (t === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', t);
}

// ---------------------------------------------------------------- helpers
const lang = (code) => app.engine.language(code);
const langLabel = (code) => (lang(code) ? lang(code).name : code);

function toast(msg, ms = 3200) {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, ms);
}

function fmtBytes(n) {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function log(...a) {
  if (app.settings.logging) console.log('[qbt]', ...a);
}

function effectiveSrc() {
  return app.state.src === 'auto' ? (app.state.spokenSrc || (navigator.language || 'en').split('-')[0]) : app.state.src;
}

function speechTagFor(code, dialect) {
  return app.engine.speechTag(code, dialect || app.engine.defaultDialect(code));
}

// ---------------------------------------------------------------- wiring
function wire() {
  document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => showView(b.dataset.tab)));
  $('src-chip').addEventListener('click', () => openPicker('src'));
  $('tgt-chip').addEventListener('click', () => openPicker('tgt'));
  $('swap').addEventListener('click', swap);
  $('src-dialect').addEventListener('change', async (e) => { app.state.srcDialect = e.target.value || null; await saveState(); run(); });
  $('tgt-dialect').addEventListener('change', async (e) => { app.state.tgtDialect = e.target.value || null; await saveState(); run(); renderEssentials(); });
  $('domain').addEventListener('change', async (e) => { app.state.domain = e.target.value; await saveState(); await activate(); });
  let debounce = null;
  $('input').addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(run, 140); });
  $('clear').addEventListener('click', () => { $('input').value = ''; $('asr-state').textContent = ''; run(); $('input').focus(); });
  $('mic').addEventListener('click', () => listenOneWay());
  $('mic-a').addEventListener('click', () => listenTurn('a'));
  $('mic-b').addEventListener('click', () => listenTurn('b'));
  $('type-turn').addEventListener('submit', (e) => { e.preventDefault(); const v = $('type-turn-input').value.trim(); if (v) { addTurn('a', v, null); $('type-turn-input').value = ''; } });
  $('face-to-face').addEventListener('change', (e) => document.querySelector('.converse').classList.toggle('face', e.target.checked));
  $('converse-clear').addEventListener('click', () => { $('turns-a').replaceChildren(); $('turns-b').replaceChildren(); });
  $('picker-search').addEventListener('input', renderPicker);
  $('pb-search').addEventListener('input', renderPhrasebook);
  $('lang-search').addEventListener('input', renderLanguages);
  $('import-pack').addEventListener('change', importPack);
  $('open-settings').addEventListener('click', openSettings);
  $('net-badge').addEventListener('click', openSettings);
  $('run-qc').addEventListener('click', runQc);
  window.addEventListener('online', () => { renderNetBadge(); });
  window.addEventListener('offline', () => { renderNetBadge(); });
  onVoicesChanged(() => { if (currentView() === 'monitor') renderMonitor(); else if (app.last) renderResult(app.last); });
}

function currentView() {
  const b = document.querySelector('.tabs button[aria-current="page"]');
  return b ? b.dataset.tab : 'translate';
}

function showView(name) {
  document.querySelectorAll('.view').forEach((v) => { v.hidden = v.dataset.view !== name; });
  document.querySelectorAll('.tabs button').forEach((b) => (b.dataset.tab === name ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current')));
  $('langbar').hidden = name === 'packs' || name === 'monitor';
  if (name === 'packs') renderLanguages();
  if (name === 'monitor') renderMonitor();
  if (name === 'phrasebook') { renderEssentials(); renderPhrasebook(); }
  if (name === 'converse') renderConverseHeads();
}

// ---------------------------------------------------------------- language bar
function renderLangbar() {
  const chip = (el, code, isSrc) => {
    el.replaceChildren();
    if (isSrc && code === 'auto') {
      el.append(h('span', { class: 'native' }, 'Auto-detect'), h('span', { class: 'english' }, app.last && app.last.lid && app.last.lid.best ? `heard ${langLabel(app.last.lid.best)}` : 'from your text'));
    } else {
      const l = lang(code);
      el.append(h('span', { class: 'native', lang: code }, l ? l.native : code), h('span', { class: 'english' }, `${l ? l.name : code}${app.packs.installedFor(code).length ? '' : ' · no pack'}`));
    }
  };
  chip($('src-chip'), app.state.src, true);
  chip($('tgt-chip'), app.state.tgt, false);
  const fill = (sel, code, current, auto) => {
    sel.replaceChildren();
    if (auto) {
      sel.append(h('option', { value: '' }, 'Dialect: auto'));
      sel.disabled = true;
      return;
    }
    const l = lang(code);
    sel.disabled = !l || l.dialects.length < 2;
    for (const d of l ? l.dialects : []) sel.append(h('option', { value: d[0], selected: d[0] === current }, `${d[1]} (${d[0]})`));
  };
  fill($('src-dialect'), app.state.src, app.state.srcDialect, app.state.src === 'auto');
  fill($('tgt-dialect'), app.state.tgt, app.state.tgtDialect, false);
  const dom = $('domain');
  dom.replaceChildren(h('option', { value: 'base' }, 'Everyday vocabulary'));
  for (const d of app.packs.domains()) dom.append(h('option', { value: d, selected: d === app.state.domain }, `${d[0].toUpperCase()}${d.slice(1)} vocabulary`));
  dom.value = app.state.domain;
  renderConverseHeads();
}

async function swap() {
  const src = app.state.src === 'auto' ? (app.last && app.last.src && app.last.src !== 'und' ? app.last.src : effectiveSrc()) : app.state.src;
  const out = app.last ? app.last.output : '';
  [app.state.src, app.state.tgt] = [app.state.tgt, src];
  [app.state.srcDialect, app.state.tgtDialect] = [app.state.tgtDialect, app.state.srcDialect];
  if (out) $('input').value = out;
  await saveState();
  renderLangbar();
  await activate();
}

async function activate() {
  const installedLangs = [...new Set([...app.packs.installed.values()].map((m) => m.lang))];
  const langs = app.state.src === 'auto' ? installedLangs : [app.state.src, app.state.tgt];
  await app.packs.activate(langs);
  const missing = [app.state.src, app.state.tgt].filter((c) => c !== 'auto' && !app.packs.installedFor(c).some((m) => m.domain === 'base'));
  if (app.state.domain !== 'base') {
    const noDomain = [app.state.src, app.state.tgt].filter((c) => c !== 'auto' && app.packs.available(c).some((p) => p.domain === app.state.domain) && !app.packs.isInstalled(`${c}/${app.state.domain}`));
    if (noDomain.length) offerInstall(noDomain.map((c) => `${c}/${app.state.domain}`), `${app.state.domain} vocabulary is not installed for ${noDomain.map(langLabel).join(' and ')}.`);
  }
  if (missing.length) {
    const ids = missing.map((c) => app.packs.available(c).find((p) => p.domain === 'base')).filter(Boolean).map((p) => p.id);
    if (ids.length) offerInstall(ids, `${missing.map(langLabel).join(' and ')} dictionary not installed yet.`);
  }
  renderLangbar();
  run();
}

function offerInstall(ids, msg) {
  const banner = $('lid-banner');
  banner.hidden = false;
  banner.className = 'lid-banner confirm';
  banner.replaceChildren(h('span', {}, msg), h('button', { type: 'button', onclick: async () => {
    banner.replaceChildren(h('span', {}, 'Installing…'));
    for (const id of ids) {
      try { await app.packs.install(id); } catch (e) { toast(`Could not install ${id}: ${e.message}`); }
    }
    banner.hidden = true;
    await activate();
    renderEssentials();
  } }, isOnline() ? 'Install now (one-time download)' : 'Install when online'));
}

// ---------------------------------------------------------------- picker
function openPicker(which) {
  app.picking = which;
  $('picker-title').textContent = which === 'src' ? 'Translate from' : 'Translate to';
  $('picker-search').value = '';
  renderPicker();
  $('picker').showModal();
  $('picker-search').focus();
}

function renderPicker() {
  const q = $('picker-search').value.trim().toLowerCase();
  const list = $('picker-list');
  list.replaceChildren();
  const current = app.picking === 'src' ? app.state.src : app.state.tgt;
  const choose = async (code) => {
    if (app.picking === 'src') { app.state.src = code; app.state.srcDialect = null; } else { app.state.tgt = code; app.state.tgtDialect = null; }
    $('picker').close();
    await saveState();
    await activate();
    renderEssentials();
  };
  if (app.picking === 'src' && (!q || 'auto detect'.includes(q))) {
    list.append(h('li', {}, h('button', { type: 'button', 'aria-selected': current === 'auto', onclick: () => choose('auto') }, h('span', { class: 'nm' }, 'Auto-detect', h('small', {}, 'Scores your text against every installed dictionary')), h('span', { class: 'st' }, ''))));
  }
  const match = (l) => !q || l.name.toLowerCase().includes(q) || l.native.toLowerCase().includes(q) || l.code === q || l.dialects.some((d) => d[0].toLowerCase() === q || d[1].toLowerCase().includes(q));
  const rank = (l) => (app.packs.installedFor(l.code).length ? 0 : app.packs.available(l.code).length ? 1 : 2);
  const groups = [[0, 'Installed — work offline'], [1, 'Dictionary pack available'], [2, 'Script detection, transliteration and device voice only (no dictionary yet)']];
  const langs = app.engine.languages.filter(match).sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  for (const [g, title] of groups) {
    const inGroup = langs.filter((l) => rank(l) === g);
    if (!inGroup.length) continue;
    list.append(h('li', { class: 'group' }, title));
    for (const l of inGroup) {
      const caps = app.engine.capabilities(l.code);
      list.append(h('li', {}, h('button', { type: 'button', 'aria-selected': current === l.code, onclick: () => choose(l.code) },
        h('span', { class: 'nm' }, h('span', { lang: l.code, dir: caps.direction }, l.native), h('small', {}, `${l.name} · ${l.code}`)),
        h('span', { class: 'st' }, `Tier ${l.tier} · ${scriptName(l.script)}${l.dialects.length > 1 ? ` · ${l.dialects.length} dialects` : ''}`))));
    }
  }
  if (!langs.length) list.append(h('li', { class: 'empty' }, 'No language matches. Languages are added in data/languages.json.'));
}

// ---------------------------------------------------------------- translate
async function run() {
  const token = ++app.runToken;
  const text = $('input').value;
  const out = $('result');
  if (!text.trim()) {
    out.replaceChildren(h('p', { class: 'empty' }, 'Translations appear here with how much was translated from a known source.'));
    $('lid-banner').hidden = true;
    app.last = null;
    return;
  }
  const req = { text, src: app.state.src, tgt: app.state.tgt, srcDialect: app.state.src === 'auto' ? null : app.state.srcDialect, tgtDialect: app.state.tgtDialect, domain: app.state.domain === 'base' ? null : app.state.domain };
  const r = app.engine.translate(req);
  app.last = r;
  app.lastLocal = r;
  app.usage.local++;
  log('translate', r);
  renderLid(r);
  renderResult(r);
  if (app.state.src === 'auto') renderLangbar();
  if (app.settings.saveHistory) saveHistory(r);

  // Optional cloud enhancement, never blocking.
  const words = text.trim().split(/\s+/).length;
  const route = plan(app.settings, { coverage: r.coverage.percent, words });
  r.route = route;
  if (route.mt === 'cloud') {
    const res = await cloudTranslate(app.settings, { ...req, src: r.src, srcDialect: r.srcDialect });
    if (token !== app.runToken) return;
    if (res.result) {
      app.usage.cloud++;
      const cloud = { ...r, ...res.result, engine: 'cloud', src: r.src, tgt: r.tgt, route, lid: r.lid, localFallback: r };
      app.last = cloud;
      renderResult(cloud);
    } else {
      app.usage.cloudFailed++;
      r.notes = [...r.notes, `Cloud: ${res.error}.`];
      renderResult(r);
    }
  }
  sendTelemetry(r);
}

function renderLid(r) {
  const b = $('lid-banner');
  if (app.state.src !== 'auto' || !r.lid) { if (b.dataset.kind === 'lid') b.hidden = true; return; }
  b.dataset.kind = 'lid';
  b.hidden = false;
  const lid = r.lid;
  if (!lid.best) { b.className = 'lid-banner confirm'; b.replaceChildren('No letters to identify yet.'); return; }
  const pick = async (code) => { app.state.src = code; app.state.spokenSrc = code; await saveState(); await activate(); };
  if (lid.needsConfirmation) {
    b.className = 'lid-banner confirm';
    b.replaceChildren(h('span', {}, 'Not sure which language this is — confirm:'), ...lid.ranked.slice(0, 4).map((c) => h('button', { type: 'button', onclick: () => pick(c.lang) }, langLabel(c.lang))));
  } else {
    b.className = 'lid-banner';
    const d = lid.dialect ? ` · ${lid.dialect.tag}` : '';
    b.replaceChildren(h('span', {}, `Detected ${langLabel(lid.best)}${d} · confidence ${Math.round(lid.confidence * 100)}%`), h('button', { type: 'button', onclick: () => openPicker('src') }, 'Change'), h('button', { type: 'button', onclick: () => pick(lid.best) }, `Lock ${langLabel(lid.best)}`));
  }
}

function coverageLevel(p) {
  return p >= 90 ? 'high' : p >= 60 ? 'mid' : 'low';
}

function renderResult(r) {
  const out = $('result');
  const tgtLang = r.tgt;
  const outputEl = h('p', { class: 'output', lang: tgtLang, dir: r.direction || 'auto' });
  if (r.pieces) {
    for (const piece of r.pieces) {
      if (piece.seg === null) { outputEl.append(piece.text); continue; }
      const s = r.segments[piece.seg];
      if (s.kind === 'punct' || s.kind === 'number') { outputEl.append(piece.text); continue; }
      const cls = ['seg', s.flagged ? 'flagged' : '', s.provenance && s.provenance.type === 'name' ? 'name' : ''].filter(Boolean).join(' ');
      outputEl.append(h('span', { class: cls, role: 'button', tabindex: 0, title: s.flagged ? 'Not translated — tap for details' : 'Tap to see the source', onclick: () => showProvenance(r, s), onkeydown: (e) => { if (e.key === 'Enter') showProvenance(r, s); } }, piece.text));
    }
  } else outputEl.append(r.output);

  const level = coverageLevel(r.coverage.percent);
  const cov = h('div', { class: 'coverage', dataset: { level } },
    h('div', { class: 'meter', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': r.coverage.percent, 'aria-label': 'Coverage' }, h('span', { style: `width:${r.coverage.percent}%` })),
    h('span', { class: 'coverage-label' }, r.engine === 'cloud'
      ? `${r.coverage.percent}% translated from a known source (cloud engine, provenance kept)`
      : `${r.coverage.percent}% translated from the dictionary${level === 'low' ? ' — low coverage: confirm the meaning another way' : ''}`));

  const extra = [];
  if (app.settings.showTranslit && r.transliteration) {
    const t = r.transliteration;
    if (t.ok && t.scheme !== 'already Latin' && t.scheme !== 'none needed') extra.push(h('p', { class: 'translit', lang: `${tgtLang}-Latn` }, t.text, ' ', h('span', { class: 'method' }, `· ${t.scheme}${t.partial ? ' (partial)' : ''}`)));
    else if (!t.ok) extra.push(h('p', { class: 'translit' }, h('span', { class: 'method' }, t.reason)));
  }
  if (app.settings.showIpa && r.pronunciation) {
    const p = r.pronunciation;
    if (p.ok) extra.push(h('p', { class: 'ipa', title: (p.notes || []).join('; ') }, `/${p.ipa}/ `, h('span', { class: 'method' }, `· ${p.method}${p.syllables ? ` · ${p.syllables} syllables` : ''}`)));
    else extra.push(h('p', { class: 'ipa' }, h('span', { class: 'method' }, p.reason)));
  }

  const notes = (r.notes || []).length ? h('ul', { class: 'notes' }, r.notes.map((n) => h('li', {}, n))) : null;
  const tag = speechTagFor(r.tgt, r.tgtDialect);
  const voice = tts.voiceStatus(tag, { allowNetwork: !app.settings.forceOffline && isOnline() });
  const actions = h('div', { class: 'actions' },
    h('button', { class: 'text-btn primary', type: 'button', onclick: () => speak(r.output, tag), disabled: !voice.ok, title: voice.detail }, voice.ok ? 'Speak' : 'No voice'),
    h('button', { class: 'text-btn', type: 'button', onclick: () => copy(r.output) }, 'Copy'),
    h('button', { class: 'text-btn', type: 'button', onclick: () => savePhrase(r) }, 'Save'),
    r.engine === 'cloud' && r.localFallback ? h('button', { class: 'text-btn', type: 'button', onclick: () => { app.last = r.localFallback; renderResult(r.localFallback); } }, 'Show on-device result') : null);
  const engineLine = h('div', { class: 'engine-line' },
    h('span', { class: `pill ${r.engine === 'cloud' ? 'warn' : 'ok'}` }, r.engine === 'cloud' ? 'Cloud-enhanced' : 'On-device · deterministic'),
    r.fingerprint ? h('span', { class: 'pill', title: 'Identical input always gives this fingerprint' }, `fp ${r.fingerprint}`) : null,
    r.timings ? h('span', { class: 'pill' }, `${Object.values(r.timings).reduce((a, b) => a + b, 0).toFixed(1)} ms`) : null,
    h('span', { class: 'pill' }, `${langLabel(r.src)} → ${langLabel(r.tgt)}${r.tgtDialect ? ` (${r.tgtDialect})` : ''}`),
    !voice.ok ? h('span', { class: 'pill warn', title: voice.detail }, 'No real voice — text and pronunciation only') : null,
    r.hygiene && r.hygiene.length ? h('span', { class: 'pill', title: 'Input normalization applied' }, `normalized: ${r.hygiene.join(', ')}`) : null);
  out.replaceChildren(h('div', { class: 'card result', 'aria-live': 'polite' }, outputEl, ...extra, cov, notes, actions, engineLine));
}

function showProvenance(r, s) {
  const p = s.provenance || {};
  const rows = [['Source text', s.source], ['Rendered as', s.target || '(omitted by rule)']];
  if (s.concept) rows.push(['Concept', s.concept]);
  if (p.source) rows.push(['Source entry', `${p.source.pack} v${p.source.version} · “${p.source.form}”${p.source.dialect ? ` · ${p.source.dialect}` : ''}`]);
  if (p.target && p.target.pack) rows.push(['Target entry', `${p.target.pack} v${p.target.version}${p.target.dialect ? ` · ${p.target.dialect}` : ''}${p.target.domain && p.target.domain !== 'base' ? ` · ${p.target.domain} sense` : ''}`]);
  if (s.matchedBy) rows.push(['Matched', s.matchedBy]);
  if (s.alternatives && s.alternatives.length) rows.push(['Alternatives', s.alternatives.join(' · ')]);
  if (s.reading) rows.push(['Reading', s.reading]);
  if (p.engine) rows.push(['Engine', p.engine]);
  const pack = s.provenance && s.provenance.target && app.packs.installed.get(s.provenance.target.pack);
  if (pack && pack.review) rows.push(['Review status', pack.review]);
  $('prov-body').replaceChildren(h('div', { class: 'prov' },
    h('p', { class: `detail${s.flagged ? ' flag' : ''}` }, p.detail || (s.flagged ? 'Not translated.' : 'Dictionary entry.')),
    h('dl', {}, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))));
  $('provenance').showModal();
}

async function speak(text, tag) {
  const t0 = performance.now();
  const res = await tts.speak(text, tag, { rate: app.settings.speechRate, allowNetwork: !app.settings.forceOffline && isOnline() });
  app.speechTimings.tts = Math.round(performance.now() - t0);
  if (!res.ok) toast(res.detail, 5000);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied'); } catch { toast('Copy is not available here'); }
}

// ---------------------------------------------------------------- speech in
function listenOneWay() {
  if (app.stopListening) { app.stopListening(); return; }
  const src = effectiveSrc();
  const tag = speechTagFor(src, app.state.src === 'auto' ? null : app.state.srcDialect);
  const mic = $('mic');
  const state = $('asr-state');
  if (!asr.available) { toast('Speech recognition is not available on this device — type instead.', 5000); return; }
  mic.classList.add('listening');
  state.className = 'asr-state live';
  state.textContent = `Listening (${tag})… speak now`;
  const t0 = performance.now();
  let firstPartial = null;
  app.stopListening = asr.start({
    tag,
    preferOnDevice: app.settings.preferOnDeviceAsr || app.settings.forceOffline,
    onPartial: (text) => {
      if (firstPartial === null) firstPartial = Math.round(performance.now() - t0);
      $('input').value = text;
      state.textContent = 'Hearing… (recognized speech — check it before trusting)';
      run();
    },
    onFinal: ({ text, confidence }) => {
      $('input').value = text;
      app.speechTimings.asr = firstPartial;
      state.className = 'asr-state';
      state.textContent = confidence !== null && confidence < 0.6 ? `Low-confidence recognition (${Math.round(confidence * 100)}%) — check the text above` : 'Recognized speech — edit if anything was misheard';
      run();
    },
    onError: (code, message) => { state.className = 'asr-state'; state.textContent = message; },
    onEnd: () => { mic.classList.remove('listening'); app.stopListening = null; },
  });
}

// ---------------------------------------------------------------- conversation
function renderConverseHeads() {
  const a = effectiveSrc();
  const b = app.state.tgt;
  $('party-a-lang').textContent = `You · ${langLabel(a)}`;
  $('party-b-lang').textContent = `${lang(b) ? lang(b).native : b} · ${langLabel(b)}`;
}

function listenTurn(side) {
  if (app.stopListening) { app.stopListening(); return; }
  const from = side === 'a' ? effectiveSrc() : app.state.tgt;
  const tag = speechTagFor(from, side === 'a' ? (app.state.src === 'auto' ? null : app.state.srcDialect) : app.state.tgtDialect);
  const mic = $(side === 'a' ? 'mic-a' : 'mic-b');
  if (!asr.available) { toast('Speech recognition is not available on this device — type your turn instead.', 5000); return; }
  mic.classList.add('listening');
  app.stopListening = asr.start({
    tag,
    preferOnDevice: app.settings.preferOnDeviceAsr || app.settings.forceOffline,
    onFinal: ({ text, confidence }) => addTurn(side, text, confidence),
    onError: (code, message) => toast(message, 4500),
    onEnd: () => { mic.classList.remove('listening'); app.stopListening = null; },
  });
}

/** A turn: recognized text (untrusted) → confirm if low confidence → translate → speak. */
function addTurn(side, heard, confidence) {
  const from = side === 'a' ? effectiveSrc() : app.state.tgt;
  const to = side === 'a' ? app.state.tgt : effectiveSrc();
  const fromDialect = side === 'a' ? app.state.srcDialect : app.state.tgtDialect;
  const toDialect = side === 'a' ? app.state.tgtDialect : app.state.srcDialect;
  const li = h('li', { class: 'turn' });
  $(side === 'a' ? 'turns-a' : 'turns-b').append(li);
  const translateTurn = (text) => {
    const r = app.engine.translate({ text, src: from, tgt: to, srcDialect: fromDialect, tgtDialect: toDialect, domain: app.state.domain === 'base' ? null : app.state.domain });
    app.usage.local++;
    li.className = 'turn';
    const tag = speechTagFor(to, r.tgtDialect);
    li.replaceChildren(
      h('div', { class: 'heard', lang: from }, text),
      h('div', { class: 'said', lang: to, dir: r.direction }, r.output),
      h('div', { class: 'meta' }, h('span', { class: `pill ${coverageLevel(r.coverage.percent) === 'high' ? 'ok' : 'warn'}` }, `${r.coverage.percent}% from dictionary`),
        h('button', { class: 'text-btn', type: 'button', onclick: () => speak(r.output, tag) }, 'Speak'),
        h('button', { class: 'text-btn', type: 'button', onclick: () => edit(text) }, 'Edit'),
        h('button', { class: 'text-btn', type: 'button', onclick: () => { $('input').value = text; app.state.src = from; app.state.tgt = to; showView('translate'); activate(); } }, 'Details')));
    // Mirror the translation on the listener's side so both people can read it.
    const other = $(side === 'a' ? 'turns-b' : 'turns-a');
    other.append(h('li', { class: 'turn' }, h('div', { class: 'said', lang: to, dir: r.direction }, r.output), h('div', { class: 'meta' }, `${langLabel(from)} → ${langLabel(to)} · ${r.coverage.percent}%`)));
    other.lastChild.scrollIntoView({ block: 'nearest' });
    li.scrollIntoView({ block: 'nearest' });
    if ($('auto-speak').checked) speak(r.output, tag);
  };
  const edit = (text) => {
    const ta = h('textarea', { rows: 2, dir: 'auto', lang: from }, text);
    li.className = 'turn pending';
    li.replaceChildren(h('div', { class: 'heard' }, 'Check what was heard:'), ta, h('div', { class: 'meta' }, h('button', { class: 'text-btn primary', type: 'button', onclick: () => translateTurn(ta.value.trim()) }, 'Translate')));
    ta.focus();
  };
  if (confidence !== null && confidence !== undefined && confidence < 0.6) edit(heard);
  else translateTurn(heard);
}

// ---------------------------------------------------------------- phrasebook
async function savePhrase(r, category = null) {
  const cat = category || (r.domain ? r.domain[0].toUpperCase() + r.domain.slice(1) : 'General');
  const item = { id: `${r.fingerprint}-${app.phrasebook.length}`, src: r.src, tgt: r.tgt, tgtDialect: r.tgtDialect, input: r.input, output: r.output, translit: r.transliteration && r.transliteration.ok ? r.transliteration.text : '', ipa: r.pronunciation && r.pronunciation.ok ? r.pronunciation.ipa : '', coverage: r.coverage.percent, fingerprint: r.fingerprint, category: cat };
  if (app.phrasebook.some((p) => p.fingerprint === item.fingerprint)) { toast('Already in your phrasebook'); return; }
  app.phrasebook.unshift(item);
  await storage.set('kv', 'phrasebook', app.phrasebook);
  toast('Saved for offline use');
  renderPhrasebook();
}

async function saveHistory(r) {
  const hist = (await storage.get('kv', 'history')) || [];
  hist.unshift({ input: r.input, output: r.output, src: r.src, tgt: r.tgt, coverage: r.coverage.percent });
  await storage.set('kv', 'history', hist.slice(0, 50));
}

function renderPhrasebook() {
  const cats = ['All', ...new Set(app.phrasebook.map((p) => p.category))];
  if (!cats.includes(app.pbFilter)) app.pbFilter = 'All';
  $('pb-filters').replaceChildren(...cats.map((c) => h('button', { type: 'button', 'aria-pressed': c === app.pbFilter, onclick: () => { app.pbFilter = c; renderPhrasebook(); } }, c)));
  const q = $('pb-search').value.trim().toLowerCase();
  const items = app.phrasebook.filter((p) => (app.pbFilter === 'All' || p.category === app.pbFilter) && (!q || p.input.toLowerCase().includes(q) || p.output.toLowerCase().includes(q)));
  const list = $('pb-saved');
  if (!items.length) { list.replaceChildren(h('li', { class: 'empty' }, app.phrasebook.length ? 'Nothing matches.' : 'Saved translations appear here and work fully offline.')); return; }
  list.replaceChildren(...items.map((p) => h('li', { class: 'phrase' },
    h('span', { class: 'src', lang: p.src }, p.input),
    h('span', { class: 'tgt', lang: p.tgt, dir: app.engine.direction(p.tgt, p.tgtDialect) }, p.output),
    h('span', { class: 'sub' }, [p.translit, p.ipa ? `/${p.ipa}/` : '', `${p.coverage}% · ${langLabel(p.src)} → ${langLabel(p.tgt)} · ${p.category}`].filter(Boolean).join(' · ')),
    h('span', { class: 'row-actions' },
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Speak', onclick: () => speak(p.output, speechTagFor(p.tgt, p.tgtDialect)) }, '▶'),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Delete', onclick: async () => { app.phrasebook = app.phrasebook.filter((x) => x !== p); await storage.set('kv', 'phrasebook', app.phrasebook); renderPhrasebook(); } }, '✕')))));
}

function renderEssentials() {
  const list = $('pb-essentials');
  if (!list) return;
  const src = effectiveSrc();
  const tgt = app.state.tgt;
  const sLex = app.engine.lexicons.get(src);
  const tLex = app.engine.lexicons.get(tgt);
  if (!sLex || !tLex) { list.replaceChildren(h('li', { class: 'empty' }, `Install ${[!sLex ? langLabel(src) : null, !tLex ? langLabel(tgt) : null].filter(Boolean).join(' and ')} to generate essentials offline.`)); return; }
  const rows = [];
  for (const [cat, concepts] of ESSENTIALS) {
    for (const c of concepts) {
      const a = sLex.render(c, app.state.src === 'auto' ? null : app.state.srcDialect);
      const b = tLex.render(c, app.state.tgtDialect);
      if (!a || !b || !b.form) continue;
      const tr = b.reading ? { ok: true, text: b.reading } : app.engine.transliterate(b.form, tgt);
      rows.push(h('li', { class: 'phrase' },
        h('span', { class: 'src', lang: src }, a.form),
        h('span', { class: 'tgt', lang: tgt, dir: app.engine.direction(tgt, app.state.tgtDialect) }, b.form),
        h('span', { class: 'sub' }, `${cat}${tr.ok && tr.text !== b.form ? ' · ' + tr.text : ''} · ${b.pack}`),
        h('span', { class: 'row-actions' },
          h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Speak', onclick: () => speak(b.form, speechTagFor(tgt, app.state.tgtDialect)) }, '▶'),
          h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Save', onclick: () => savePhrase(app.engine.translate({ text: a.form, src, tgt, tgtDialect: app.state.tgtDialect }), cat) }, '＋'))));
    }
  }
  list.replaceChildren(...rows);
}

// ---------------------------------------------------------------- languages & packs
function renderLanguages() {
  const total = app.packs.totalBytes();
  storageEstimate().then((est) => {
    $('storage-summary').textContent = `Packs on device: ${fmtBytes(total)} · ${app.packs.installed.size} installed · ${app.engine.languages.length} languages, ${app.engine.languages.reduce((n, l) => n + l.dialects.length, 0)} dialects${est ? ` · device free ≈ ${fmtBytes(est.quota - est.usage)}` : ''}${storage.isPersistent ? '' : ' · storage not persistent here'}`;
  });
  const filters = ['Installed', 'With pack', 'Tier 1', 'Tier 2', 'Tier 3', 'All'];
  $('lang-filters').replaceChildren(...filters.map((f) => h('button', { type: 'button', 'aria-pressed': f === app.langFilter, onclick: () => { app.langFilter = f; renderLanguages(); } }, f)));
  const q = $('lang-search').value.trim().toLowerCase();
  const keep = (l) => {
    if (q && !(l.name.toLowerCase().includes(q) || l.native.toLowerCase().includes(q) || l.code === q)) return false;
    switch (app.langFilter) {
      case 'Installed': return app.packs.installedFor(l.code).length > 0;
      case 'With pack': return app.packs.available(l.code).length > 0;
      case 'Tier 1': return l.tier === 1;
      case 'Tier 2': return l.tier === 2;
      case 'Tier 3': return l.tier === 3;
      default: return true;
    }
  };
  const langs = app.engine.languages.filter(keep);
  const list = $('lang-list');
  if (!langs.length) { list.replaceChildren(h('li', { class: 'empty' }, app.langFilter === 'Installed' ? 'No languages installed yet — choose “With pack”.' : 'No language matches.')); return; }
  list.replaceChildren(...langs.map((l) => {
    const caps = app.engine.capabilities(l.code);
    const avail = app.packs.available(l.code);
    const custom = app.packs.installedFor(l.code).filter((m) => !avail.some((a) => a.id === m.id));
    const btns = [...avail, ...custom].map((p) => {
      const installed = app.packs.isInstalled(p.id);
      const upd = installed && app.packs.updateAvailable(p.id);
      const label = `${p.domain === 'base' ? 'Core' : p.domain[0].toUpperCase() + p.domain.slice(1)} · ${fmtBytes(p.bytes)}${p.source === 'store' ? ' · store' : ''}`;
      const btn = h('button', { class: `pack-btn${installed ? ' installed' : ''}`, type: 'button', title: installed ? 'Installed — tap to remove' : 'Download once, then works offline' }, installed ? `✓ ${label}${upd ? ' · update' : ''}` : `＋ ${label}`);
      btn.addEventListener('click', async () => {
        btn.classList.add('busy');
        try {
          if (upd) await app.packs.install(p.id);
          else if (installed) await app.packs.remove(p.id);
          else await app.packs.install(p.id);
        } catch (e) { toast(e.message, 5000); }
        await activate();
        renderLanguages();
        renderEssentials();
      });
      return btn;
    });
    const capsText = [
      caps.dictionary || avail.length ? null : 'No dictionary pack yet — import one to translate',
      caps.transliteration ? 'transliteration' : null,
      caps.pronunciationRules ? 'IPA rules' : null,
      `voice: ${tts.voiceStatus(speechTagFor(l.code)).ok ? 'yes' : 'not on this device'}`,
    ].filter(Boolean).join(' · ');
    return h('li', { class: 'lang-row' },
      h('div', { class: 'top' }, h('span', { class: 'native', lang: l.code, dir: caps.direction }, l.native), h('span', { class: 'english' }, `${l.name} · ${l.code}`)),
      h('div', { class: 'tags' }, h('span', { class: 'pill' }, `Tier ${l.tier}`), h('span', { class: 'pill' }, scriptName(l.script)), caps.direction === 'rtl' ? h('span', { class: 'pill' }, 'RTL') : null, h('span', { class: 'pill', title: l.dialects.map((d) => `${d[1]} (${d[0]})`).join(', ') }, `${l.dialects.length} dialect${l.dialects.length > 1 ? 's' : ''}`)),
      btns.length ? h('div', { class: 'packs' }, btns) : null,
      h('div', { class: 'caps' }, capsText));
  }));
}

async function importPack(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  try {
    const meta = await app.packs.importText(await file.text());
    toast(`Imported ${meta.id} (${meta.entries} entries)`);
    await activate();
    renderLanguages();
  } catch (err) {
    toast(`Import failed: ${err.message}`, 6000);
  }
  e.target.value = '';
}

// ---------------------------------------------------------------- monitor
function panel(title, ...body) {
  return h('div', { class: 'panel' }, h('h3', {}, title), ...body);
}
function table(rows, head) {
  return h('table', {}, head ? h('thead', {}, h('tr', {}, head.map((c) => h('th', {}, c)))) : null, h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c, i) => h('td', { class: i > 0 && typeof c === 'number' ? 'num' : null }, c))))));
}

async function renderMonitor() {
  const m = $('monitor');
  const loaded = [...app.packs.loaded].sort();
  const t = app.last && app.last.timings ? app.last.timings : {};
  const est = await storageEstimate();
  const mem = performance.memory ? `${fmtBytes(performance.memory.usedJSHeapSize)} JS heap` : 'not exposed by this browser';
  const voices = tts.voices();
  const onDeviceAsr = app.onDeviceAsr;
  const ctl = (label, key, help) => h('label', { class: 'ctl' }, h('span', {}, label, help ? h('small', {}, ` ${help}`) : null), h('input', { type: 'checkbox', checked: !!app.settings[key], onchange: async (e) => { app.settings[key] = e.target.checked; await saveSettings(); if (key === 'storeConnected' || key === 'forceOffline') app.packs.setStore(storeSource()); renderNetBadge(); renderMonitor(); } }));

  const panels = [
    panel('Active models', table([
      ['Engine', 'deterministic dictionary MT (on-device)'],
      ['Loaded packs', loaded.length ? loaded.join(', ') : 'none'],
      ['Loaded entries', app.engine.loadedLanguages().reduce((n, c) => n + app.engine.lexicons.get(c).entryCount, 0)],
      ['RAM for packs (approx.)', fmtBytes(app.packs.loadedBytes() * 3)],
      ['App memory', mem],
      ['ASR provider', h('span', {}, `${asr.provider}${onDeviceAsr === true ? ' · on-device' : onDeviceAsr === false ? ' · needs network' : ''} `, asr.available ? h('button', { class: 'text-btn', type: 'button', onclick: checkOnDeviceAsr }, onDeviceAsr === undefined ? 'Check on-device' : 'Recheck') : null)],
      ['TTS voices', `${voices.length} (${voices.filter((v) => v.onDevice).length} on-device)`],
    ])),
    panel('Latency (last request)', table([
      ['ASR first partial', app.speechTimings.asr !== null ? `${app.speechTimings.asr} ms` : '—'],
      ['Normalize', t.normalize !== undefined ? `${t.normalize} ms` : '—'],
      ['Language ID', t.lid !== undefined ? `${t.lid} ms` : '—'],
      ['Translate (MT)', t.mt !== undefined ? `${t.mt} ms` : '—'],
      ['Transliterate', t.transliterate !== undefined ? `${t.transliterate} ms` : '—'],
      ['Pronounce (G2P)', t.pronounce !== undefined ? `${t.pronounce} ms` : '—'],
      ['TTS total', app.speechTimings.tts !== null ? `${app.speechTimings.tts} ms` : '—'],
    ])),
    panel('Language ID & routing', table([
      ['Last detection', app.last && app.last.lid ? `${langLabel(app.last.lid.best)} · ${Math.round(app.last.lid.confidence * 100)}%${app.last.lid.needsConfirmation ? ' (asked to confirm)' : ''}` : 'source fixed'],
      ['Dialect', app.last && app.last.lid && app.last.lid.dialect ? `${app.last.lid.dialect.tag} · ${Math.round(app.last.lid.dialect.confidence * 100)}%` : app.last ? app.last.srcDialect || '—' : '—'],
      ['Coverage', app.last ? `${app.last.coverage.percent}%` : '—'],
      ['Route (MT)', app.last && app.last.route ? `${app.last.route.mt}${app.last.route.reasons.length ? ' — ' + app.last.route.reasons.join(', ') : ''}` : 'local'],
      ['Requests', `${app.usage.local} on-device · ${app.usage.cloud} cloud · ${app.usage.cloudFailed} cloud fallbacks`],
    ])),
    panel('Storage', table([
      ...[...app.packs.installed.values()].sort((a, b) => a.id.localeCompare(b.id)).map((p) => [p.id, fmtBytes(p.bytes)]),
      ['Total packs', fmtBytes(app.packs.totalBytes())],
      ['Origin usage / quota', est ? `${fmtBytes(est.usage)} / ${fmtBytes(est.quota)}` : 'not exposed'],
    ])),
    panel('Controls',
      ctl('Force offline', 'forceOffline', '(radios-off behaviour)'),
      ctl('Force cloud MT', 'forceCloud', '(when opted in)'),
      ctl('Connected to cloud store', 'storeConnected'),
      ctl('Pipeline logging', 'logging', '(console)'),
      h('div', { class: 'ctl' }, h('span', {}, 'Unload all packs'), h('button', { class: 'text-btn', type: 'button', onclick: async () => { for (const id of [...app.packs.loaded]) app.packs.unload(id); renderMonitor(); toast('Packs released; they reload on next use'); } }, 'Release'))),
    panel('QC battery', app.qc ? h('div', {}, ...app.qc.map((q) => h('div', {},
      h('p', {}, h('b', {}, `${langLabel(q.lang)} — ${q.passed}/${q.total} (${q.score}%)`)),
      table(q.checks.map((c) => [h('span', { class: c.severity === 'pass' ? 'qc-pass' : c.severity === 'fail' ? 'qc-fail' : 'qc-warn' }, c.severity === 'pass' ? '✓' : c.severity === 'fail' ? '✕' : '!'), c.label, c.detail]))))) : h('p', { class: 'empty' }, 'Run the battery to self-check every loaded language: covenant, determinism, round trips, transliteration, pronunciation and voices.')),
  ];
  m.replaceChildren(...panels);
}

/** Asked only on demand: some engines take long (or misbehave) answering availability probes. */
async function checkOnDeviceAsr() {
  const tag = speechTagFor(effectiveSrc());
  const answer = await Promise.race([asr.onDevice(tag), new Promise((r) => setTimeout(() => r(null), 4000))]);
  app.onDeviceAsr = answer;
  if (answer === false && !nativeShell) {
    toast(`On-device recognition for ${tag} is not installed — trying to install it`, 4000);
    if (await asr.installOnDevice(tag)) app.onDeviceAsr = true;
  }
  renderMonitor();
}

function runQc() {
  const langs = app.engine.loadedLanguages();
  if (!langs.length) { toast('Install a language first'); return; }
  app.qc = langs.map((l) => runBattery(app.engine, l, {
    partner: langs.find((x) => x !== l) || null,
    voiceCheck: (code) => tts.voiceStatus(speechTagFor(code), { allowNetwork: false }),
  }));
  renderMonitor();
}

// ---------------------------------------------------------------- network & settings
function renderNetBadge() {
  const b = $('net-badge');
  const online = isOnline() && !app.settings.forceOffline;
  const cloud = online && app.settings.cloudOptIn && app.settings.gatewayUrl;
  const store = online && app.settings.storeConnected && app.settings.storeUrl;
  b.dataset.state = !online ? 'offline' : cloud || store ? 'cloud' : 'local';
  b.textContent = !online ? 'Offline · on-device' : cloud ? 'On-device + cloud' : store ? 'On-device · store linked' : 'On-device';
}

function openSettings() {
  const s = app.settings;
  const field = (key, label, type = 'checkbox', help = '', extra = {}) => {
    const input = type === 'checkbox'
      ? h('input', { type, checked: !!s[key], ...extra })
      : type === 'select'
        ? h('select', {}, extra.options.map(([v, l]) => h('option', { value: v, selected: String(s[key]) === String(v) }, l)))
        : h('input', { type, value: s[key] ?? '', ...extra });
    input.addEventListener('change', async () => {
      s[key] = type === 'checkbox' ? input.checked : type === 'number' || type === 'range' ? Number(input.value) : input.value.trim();
      await saveSettings();
      applyTheme();
      app.packs.setStore(storeSource());
      renderNetBadge();
      if (['showTranslit', 'showIpa'].includes(key)) run();
    });
    return h('div', { class: 'setting' }, type === 'checkbox' ? h('label', {}, h('span', {}, label), input) : h('label', { style: 'display:grid' }, h('span', {}, label), input), help ? h('small', {}, help) : null);
  };
  const testStore = h('button', { class: 'text-btn', type: 'button', onclick: async () => {
    app.packs.setStore(storeSource());
    const ok = await app.packs.refreshCatalog();
    toast(ok ? `Store catalog: ${app.packs.catalog.packs.filter((p) => p.source === 'store').length} packs available` : 'Could not reach the store — the app keeps working offline', 5000);
    renderLangbar();
  } }, 'Test connection & refresh catalog');
  $('settings-body').replaceChildren(
    h('div', { class: 'setting-group' }, 'Offline & privacy'),
    field('forceOffline', 'Offline only', 'checkbox', 'Never use the network. Every installed language keeps translating, pronouncing and speaking (where a device voice exists).'),
    field('preferOnDeviceAsr', 'Prefer on-device speech recognition', 'checkbox', 'Where the device supports it, audio never leaves the phone.'),
    field('saveHistory', 'Keep translation history on this device', 'checkbox', 'Off by default: nothing you say or type is stored unless you save it.'),
    h('div', { class: 'setting-group' }, 'Cloud QueryBook store (optional)'),
    field('storeConnected', 'Connect to a QueryBook store', 'checkbox', 'Adds the store’s language and domain packs to the catalog. Packs download once and then work offline.'),
    field('storeUrl', 'Store URL', 'url', 'e.g. https://store.example.com/translate/store/', { placeholder: 'https://…/store/', inputmode: 'url' }),
    field('storeKey', 'Store access key (if required)', 'password', 'Sent only to the store, as a bearer token.'),
    testStore,
    h('div', { class: 'setting-group' }, 'Cloud enhancement (optional)'),
    field('cloudOptIn', 'Allow cloud enhancement when online', 'checkbox', 'The on-device result always appears first. Cloud answers must carry coverage and provenance or they are rejected.'),
    field('gatewayUrl', 'QueryBook gateway URL', 'url', 'Endpoints: /mt, /model-selection, /telemetry', { placeholder: 'https://…', inputmode: 'url' }),
    field('cloudBelowCoverage', 'Ask the cloud when coverage is below', 'select', '', { options: [[50, '50%'], [70, '70%'], [90, '90%'], [101, 'always (when opted in)']] }),
    field('telemetryOptIn', 'Share anonymous quality metrics', 'checkbox', 'Language pair, coverage band and latency only — never text or audio.'),
    h('div', { class: 'setting-group' }, 'Display'),
    field('showTranslit', 'Show transliteration'),
    field('showIpa', 'Show pronunciation (IPA)'),
    field('speechRate', 'Speaking rate', 'select', '', { options: [[0.75, 'Slow'], [0.95, 'Normal'], [1.15, 'Fast']] }),
    field('theme', 'Theme', 'select', '', { options: [['system', 'System'], ['light', 'Light'], ['dark', 'Dark']] }),
    h('p', { class: 'setting' }, h('small', {}, `QueryBook Translate · ${app.config.edition || nativeShell || 'web'} edition · registry v${app.engine.registryVersion} · ${app.engine.languages.length} languages · deterministic on-device engine. Seed dictionaries are self-authored and pending native-speaker review.`)),
  );
  $('settings').showModal();
}

function sendTelemetry(r) {
  const s = app.settings;
  if (!s.telemetryOptIn || !s.cloudOptIn || !s.gatewayUrl || s.forceOffline || !isOnline()) return;
  const band = r.coverage.percent >= 90 ? 'high' : r.coverage.percent >= 60 ? 'mid' : 'low';
  const body = JSON.stringify({ pair: `${r.src}-${r.tgt}`, coverage: band, ms: Math.round(Object.values(r.timings || {}).reduce((a, b) => a + b, 0)) });
  try { navigator.sendBeacon(s.gatewayUrl.replace(/\/$/, '') + '/telemetry', body); } catch { /* best effort, opt-in only */ }
}

boot().catch((e) => {
  console.error(e);
  document.body.append(h('p', { class: 'noscript' }, `QueryBook Translate could not start: ${e.message}`));
});
