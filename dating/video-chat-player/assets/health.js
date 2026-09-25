import { bus } from './bus.js';
import { api } from './api.js';

const ORDER = ['player', 'chat', 'sync', 'youtube', 'server', 'storage', 'network', 'app'];
const STALL_MS = 8000;

// Every subsystem reports here; the rail shows the state, the banner shows what the
// app did about a failure, and the watchdog recovers a stalled player on its own.
export class Health {
  constructor({ listEl, bannerEl, player, onStall }) {
    this.listEl = listEl;
    this.bannerEl = bannerEl;
    this.player = player;
    this.onStall = onStall;
    this.items = new Map();
    this.log = [];
    this.lastTime = -1;
    this.lastAdvance = Date.now();
    this.stallStrikes = 0;
    this.bannerTimer = 0;
    ORDER.forEach((name) => this.items.set(name, { status: 'ok', detail: '' }));
    this.report('storage', this.storageWorks() ? 'ok' : 'warn', this.storageWorks() ? 'remembers name and volume' : 'blocked: nothing remembered');
    this.report('network', navigator.onLine === false ? 'fail' : 'ok', navigator.onLine === false ? 'offline' : 'online');
    window.addEventListener('online', () => this.report('network', 'ok', 'online'));
    window.addEventListener('offline', () => this.report('network', 'fail', 'offline: chat and sync paused until the connection returns', true));
    window.addEventListener('error', (event) => this.report('app', 'warn', `script error: ${(event.message || '').slice(0, 80)}`));
    window.addEventListener('unhandledrejection', (event) => this.report('app', 'warn', `unhandled: ${String(event.reason?.message || event.reason).slice(0, 80)}`));
    bus.on('chat:status', ({ status, detail }) => {
      if (status === 'live') this.report('chat', 'ok', 'live');
      else if (status === 'offline') this.report('chat', 'warn', 'offline, will resume');
      else if (status === 'reconnecting') this.report('chat', 'warn', `reconnecting: ${detail}`, true);
      else if (status === 'lost') this.report('chat', 'fail', detail, true);
      else if (status === 'solo') this.report('chat', 'warn', detail || 'solo: no room');
    });
    player.on('time', (t) => this.tick(t));
    player.on('error', (m) => this.report('player', 'fail', m, true));
    player.on('play', () => this.report('player', 'ok', 'playing'));
    player.on('pause', () => this.report('player', 'ok', 'paused'));
    setInterval(() => this.watchdog(), 2000);
    this.render();
  }

  storageWorks() {
    try { localStorage.setItem('watchroom.probe', '1'); localStorage.removeItem('watchroom.probe'); return true; } catch (_err) { return false; }
  }

  report(name, status, detail = '', banner = false) {
    const prev = this.items.get(name);
    if (!prev || prev.status !== status || prev.detail !== detail) { this.log.push({ at: Date.now(), name, status, detail }); if (this.log.length > 100) this.log.shift(); }
    this.items.set(name, { status, detail });
    if (banner && status !== 'ok') this.banner(`${label(name)}: ${detail}`, status);
    else if (prev && prev.status !== 'ok' && status === 'ok' && this.bannerEl?.dataset.source === name) this.clearBanner();
    if (banner) this.bannerEl && (this.bannerEl.dataset.source = name);
    this.render();
  }

  banner(text, status = 'warn') {
    if (!this.bannerEl) return;
    this.bannerEl.textContent = text;
    this.bannerEl.className = `notice notice--${status === 'fail' ? 'fail' : 'warn'}`;
    this.bannerEl.hidden = false;
    clearTimeout(this.bannerTimer);
    if (status !== 'fail') this.bannerTimer = setTimeout(() => this.clearBanner(), 8000);
  }

  clearBanner() { if (this.bannerEl) { this.bannerEl.hidden = true; this.bannerEl.textContent = ''; } }

  tick(t) {
    if (t !== this.lastTime) { this.lastTime = t; this.lastAdvance = Date.now(); this.stallStrikes = 0; }
  }

  /** Playing but the clock has not moved for 8 s: try to recover, then skip. */
  watchdog() {
    if (!this.player.isPlaying()) { this.lastAdvance = Date.now(); return; }
    if (Date.now() - this.lastAdvance < STALL_MS) return;
    this.stallStrikes += 1;
    this.lastAdvance = Date.now();
    this.report('player', 'warn', `stalled, recovery attempt ${this.stallStrikes}`, true);
    this.onStall(this.stallStrikes);
  }

  async checkServer() {
    try {
      const data = await api('health', {}, { method: 'GET', timeoutMs: 5000 });
      const failing = (data.checks || []).filter((c) => !c.ok).map((c) => `${c.name} (${c.detail})`);
      this.report('server', data.ok ? 'ok' : 'fail', data.ok ? `${data.checks.length} checks pass` : `failing: ${failing.join(', ')}`, !data.ok);
      return data;
    } catch (err) {
      this.report('server', 'fail', err.message, true);
      return null;
    }
  }

  render() {
    if (!this.listEl) return;
    const frag = document.createDocumentFragment();
    for (const name of ORDER) {
      const item = this.items.get(name);
      const li = document.createElement('li');
      li.className = `health__item health__item--${item.status}`;
      const dot = document.createElement('span');
      dot.className = 'health__dot';
      const label_ = document.createElement('span');
      label_.className = 'health__name';
      label_.textContent = label(name);
      const detail = document.createElement('span');
      detail.className = 'health__detail';
      detail.textContent = item.detail;
      li.append(dot, label_, detail);
      frag.appendChild(li);
    }
    this.listEl.replaceChildren(frag);
  }

  summary() { return Object.fromEntries([...this.items.entries()]); }
}

function label(name) {
  return { player: 'Player', chat: 'Chat', sync: 'Sync', youtube: 'YouTube', server: 'Server', storage: 'Storage', network: 'Network', app: 'App' }[name] || name;
}
