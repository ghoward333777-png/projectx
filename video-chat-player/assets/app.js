import { bus } from './bus.js';
import { Stage } from './stage.js';
import { IdleController } from './idle.js';
import { Controls, installKeyboard } from './controls.js';
import { Html5Adapter } from './player/html5.js';
import { YouTubeAdapter, loadYouTubeApi } from './player/youtube.js';
import { PlayerProxy } from './player/proxy.js';
import { ChatClient } from './chat.js';
import { Overlay } from './overlay.js';
import { PlaylistController } from './playlist.js';
import { SyncController } from './sync.js';
import { Health } from './health.js';
import { installBridge } from './bridge.js';

const $ = (id) => document.getElementById(id);
const root = $('stage');
const stage = new Stage(root);
const idle = new IdleController(stage, { timeout: Number(root.dataset.idleTimeout) || 3000 });
const player = new PlayerProxy(stage.picture);
player.rate = 1;
const cards = stage.cards;
const composer = $('overlay-input');
const state = { name: 'loading', error: null, item: null, upNextTimer: 0, solo: false };

function setState(name, error = null) {
  state.name = name;
  state.error = error;
  $('dbg-state').textContent = error ? `${name}: ${error}` : name;
}

// ---- cards ----
function showCard({ title, text, action, secondary, id = 'card' }) {
  cards.replaceChildren();
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.card = id;
  const h = document.createElement('p');
  h.className = 'card__title';
  h.textContent = title;
  card.appendChild(h);
  if (text) { const p = document.createElement('p'); p.className = 'card__text'; p.textContent = text; card.appendChild(p); }
  const row = document.createElement('div');
  row.className = 'card__actions';
  for (const a of [action, secondary]) {
    if (!a) continue;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = a === action ? 'button' : 'button button--quiet';
    b.textContent = a.label;
    b.addEventListener('click', a.run);
    row.appendChild(b);
  }
  if (row.children.length) card.appendChild(row);
  cards.appendChild(card);
  idle.pin('modal');
  return card;
}
function clearCards() { cards.replaceChildren(); idle.unpin('modal'); clearTimeout(state.upNextTimer); }

// ---- playback ----
async function requestPlay() {
  if (state.name === 'error' || !player.current) return;
  try {
    await player.play();
    if (cards.querySelector('[data-card="tap"]')) clearCards();
  } catch (err) {
    if (err && err.name === 'NotAllowedError') {
      showCard({ id: 'tap', title: 'Tap to play', text: 'Your browser wants a tap before it plays sound.', action: { label: 'Play', run: requestPlay } });
    } else {
      health.report('player', 'warn', err?.message || String(err));
    }
  }
}
async function togglePlay() {
  if (state.name === 'error' || !player.current) return;
  if (player.isPlaying()) { player.pause(); return; }
  await requestPlay();
}

const controls = new Controls({ root, player, stage, idle, togglePlay });
installKeyboard({ player, stage, idle, controls, composer, togglePlay });

const health = new Health({ listEl: $('health-list'), bannerEl: $('banner'), player, onStall: recoverStall });
const chat = new ChatClient({ mediaTime: () => player.currentTime(), currentItemId: () => playlist.currentId });
const playlist = new PlaylistController({ chat, listEl: $('pl-list'), form: $('pl-form'), input: $('pl-url'), note: $('pl-note'), health });
const overlay = new Overlay({ stage, idle, list: $('overlay-list'), composer: $('overlay-composer'), input: composer, seek: (t) => player.seek(t), myId: () => chat.memberId, controls });
const sync = new SyncController({ chat, player, playlist, health, requestPlay });

// ---- loading items ----
let loadToken = 0;
async function loadItem(item, { autoplay = true } = {}) {
  clearCards();
  const token = ++loadToken;
  state.item = item;
  sync.unsettle();
  if (!item) {
    setState('idle');
    showCard({ id: 'empty', title: 'Nothing to play yet', text: 'Add a video link in the playlist on the right.' });
    return;
  }
  $('rail-label').textContent = item.title;
  setState('loading');
  const kind = item.kind === 'youtube' ? 'youtube' : 'html5';
  root.classList.toggle('is-youtube', kind === 'youtube');
  try {
    if (player.kind !== kind) {
      player.use(kind === 'youtube' ? new YouTubeAdapter() : new Html5Adapter(), kind);
      controls.setVolume(controls.currentVolume());
      controls.setMuted(controls.currentMuted());
    }
    if (kind === 'youtube') health.report('youtube', 'ok', 'loading player');
    const size = await player.load({ src: item.src });
    if (token !== loadToken) return;
    stage.setPictureSize(size);
    $('dbg-picture').textContent = size ? `${size.width} × ${size.height}` : '–';
    setState('ready');
    if (kind === 'youtube') health.report('youtube', 'ok', 'player ready');
    health.report('player', 'ok', `loaded ${item.kind}`);
    if (autoplay) await requestPlay();
    sync.settle();
  } catch (err) {
    if (token !== loadToken) return;
    await itemFailed(item, err?.message || String(err), kind);
  }
}

// One failure → retry once (cache-bust for files). Second failure → mark and skip.
const retried = new Set();
async function itemFailed(item, reason, kind) {
  if (kind === 'youtube') health.report('youtube', 'fail', reason, true);
  else health.report('player', 'fail', reason, true);
  if (!retried.has(item.id) && kind === 'html5') {
    retried.add(item.id);
    health.report('player', 'warn', 'retrying once');
    const src = item.src + (item.src.includes('?') ? '&' : '?') + 'retry=' + Date.now();
    return loadItem({ ...item, src }, { autoplay: true });
  }
  setState('error', reason);
  const next = await playlist.reportFailure(item, reason);
  const isYouTubeBlocked = kind === 'youtube' && /block|did not answer|could not load/i.test(reason);
  const text = isYouTubeBlocked
    ? 'This window blocks YouTube. Open the room in a normal browser tab to watch YouTube items.'
    : reason;
  if (next && playlist.canControl()) {
    showUpNext(next, `Cannot play “${item.title}”`, text);
  } else if (next) {
    showCard({ id: 'error', title: `Cannot play “${item.title}”`, text: `${text} Waiting for the host to move on.` });
  } else {
    showCard({ id: 'error', title: `Cannot play “${item.title}”`, text: `${text} Add another video to continue.`, action: isYouTubeBlocked ? { label: 'Open in a browser tab', run: () => window.open(location.href, '_blank', 'noopener') } : null });
  }
}

function showUpNext(next, title = 'Up next', text = '') {
  let seconds = 5;
  const card = showCard({
    id: 'upnext', title, text: `${text ? text + ' ' : ''}Up next: ${next.title} in ${seconds} s`,
    action: { label: 'Play now', run: () => { clearCards(); playlist.jump(next.id); } },
    secondary: { label: 'Cancel', run: () => clearCards() },
  });
  const textEl = card.querySelector('.card__text');
  state.upNextTimer = setInterval(() => {
    seconds -= 1;
    if (seconds <= 0) { clearInterval(state.upNextTimer); clearCards(); playlist.jump(next.id); return; }
    textEl.textContent = `${text ? text + ' ' : ''}Up next: ${next.title} in ${seconds} s`;
  }, 1000);
}

function recoverStall(strike) {
  if (!state.item) return;
  if (strike === 1) {
    const t = player.currentTime();
    if (player.kind === 'html5' && player.el) { player.el.load(); player.seek(t); requestPlay(); }
    else { player.seek(t); requestPlay(); }
    return;
  }
  itemFailed(state.item, 'Playback stalled and could not be recovered.', player.kind === 'youtube' ? 'youtube' : 'html5');
}

player.on('ended', () => {
  setState('ended');
  idle.pin('paused');
  const next = playlist.nextPlayable();
  if (next && playlist.canControl()) showUpNext(next);
  else if (!next) showCard({ id: 'end', title: 'That was the last video', text: 'Add another link in the playlist to keep going.', action: { label: 'Replay', run: () => { player.seek(0); requestPlay(); } } });
});
player.on('play', () => { setState('playing'); idle.unpin('paused'); if (cards.querySelector('[data-card="end"]')) clearCards(); });
player.on('pause', () => { if (state.name !== 'error') setState('paused'); idle.pin('paused'); });
player.on('error', (message) => { if (state.item && state.name !== 'loading') itemFailed(state.item, message, player.kind === 'youtube' ? 'youtube' : 'html5'); });

bus.on('playlist:current', (item) => loadItem(item));
bus.on('room:update', ({ room, members, actingHostId, me }) => {
  $('room-id').textContent = room.id;
  const online = members.filter((m) => m.online);
  $('room-members').replaceChildren(...online.map((m) => {
    const s = document.createElement('span');
    s.className = 'member';
    s.style.setProperty('--c', m.colour);
    s.textContent = m.name + (m.id === me ? ' (you)' : '') + (m.id === actingHostId ? ' · host' : '');
    return s;
  }));
  root.classList.toggle('is-docked', room.chatMode === 'docked');
  stage.setDock(room.chatMode === 'docked' ? 132 : 0);
  const settings = $('room-settings');
  if (settings) {
    settings.hidden = !chat.isHost;
    $('set-guests').checked = !!room.guestsControl;
    $('set-docked').checked = room.chatMode === 'docked';
  }
  playlist.render();
});
bus.on('room:lost', () => {
  showCard({ id: 'lost', title: 'This room has expired', text: 'Rooms close after a day without activity.', action: { label: 'Start a new room', run: () => { location.href = 'index.php'; } } });
});
bus.on('chat:retry', (id) => { const row = overlay.rows.get(id); if (row) chat.retry({ id, text: row.querySelector('.msg__text').textContent, mediaTime: null, itemId: playlist.currentId, kind: 'chat', memberId: chat.memberId, name: chat.me?.name, colour: chat.me?.colour }); });

// ---- picture clicks ----
let clickTimer = 0;
stage.picture.addEventListener('click', () => {
  clearTimeout(clickTimer);
  if (idle.touch) { idle.toggle(); return; }
  clickTimer = setTimeout(togglePlay, 250);
});
stage.picture.addEventListener('dblclick', () => { clearTimeout(clickTimer); stage.toggleFullscreen(); });

// ---- composer ----
composer.addEventListener('focus', () => idle.pin('composer'));
composer.addEventListener('blur', () => idle.unpin('composer'));
composer.addEventListener('input', () => { if (composer.value.trim() !== '') idle.pin('draft'); else idle.unpin('draft'); });
$('overlay-composer').addEventListener('submit', (event) => {
  event.preventDefault();
  const text = composer.value.trim();
  if (!text) return;
  if (state.solo) { overlay.systemLine('Not connected to a room, so nobody else can see this yet.'); }
  const sent = chat.send(text);
  if (!sent && !state.solo) overlay.systemLine('Could not send: not in a room.');
  composer.value = '';
  idle.unpin('draft');
});
composer.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowUp' && composer.value === '' && chat.lastText) { composer.value = chat.lastText; event.preventDefault(); }
});
bus.on('chat:pending', (m) => { chat.lastText = m.text; });

// ---- room bar ----
$('room-copy').addEventListener('click', async () => {
  const url = location.href;
  try { await navigator.clipboard.writeText(url); $('room-copy').textContent = 'Copied'; }
  catch (_err) { window.prompt('Copy this invite link', url); }
  setTimeout(() => { $('room-copy').textContent = 'Copy invite'; }, 2000);
});
$('room-name-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = $('room-name').value.trim();
  if (!name) return;
  try { await chat.rename(name); overlay.systemLine(`You are now ${name}`); } catch (err) { health.banner(err.message, 'warn'); }
});
const settingsForm = $('room-settings');
if (settingsForm) {
  settingsForm.addEventListener('change', async () => {
    try { await chat.call('room.settings', { guestsControl: $('set-guests').checked, chatMode: $('set-docked').checked ? 'docked' : 'overlay' }); }
    catch (err) { health.banner(err.message, 'warn'); }
  });
}

// ---- geometry / debug ----
bus.on('stage:layout', (rect) => {
  $('dbg-stage').textContent = `${Math.round(rect.stageWidth)} × ${Math.round(rect.stageHeight)}`;
  $('dbg-rect').textContent = `${Math.round(rect.x)}, ${Math.round(rect.y)} · ${Math.round(rect.width)} × ${Math.round(rect.height)} (${rect.source})`;
});
bus.on('stage:fullscreen', (on) => { $('dbg-fs').textContent = on ? 'yes' : 'no'; });
bus.on('idle:state', (s) => { $('dbg-idle').textContent = s + (idle.pins.size ? ` (${[...idle.pins].join(', ')})` : ''); });

installBridge({ root, player, chat, playlist, stage, controls, idle, requestPlay });

window.__watchRoom = { stage, player, idle, controls, chat, playlist, sync, overlay, health, get state() { return state.name; }, get error() { return state.error; }, get item() { return state.item; } };

// ---- boot: join the room in the URL, else create one; if the server is unreachable, play solo and keep trying ----
async function boot() {
  const params = new URLSearchParams(location.search);
  const roomId = params.get('room');
  const name = params.get('name') || ChatClient.lastName() || 'Guest';
  $('room-name').value = name;
  setState('joining');
  health.checkServer();
  try {
    if (roomId) {
      try {
        await chat.join(roomId, name);
      } catch (err) {
        if (err.code !== 'not_found') throw err;
        await chat.create(name, root.dataset.src);
        overlay.systemLine('That room had expired, so a new one was started.');
      }
    } else {
      await chat.create(name, root.dataset.src);
    }
    const url = new URL(location.href);
    url.searchParams.set('room', chat.room.id);
    url.searchParams.delete('src');
    url.searchParams.delete('name');
    history.replaceState(null, '', url);
    state.solo = false;
    sync.enable();
    if (state.name === 'playing' || state.name === 'paused' || state.name === 'ready') sync.settle();
  } catch (err) {
    // Solo fallback: the video still plays; chat and sync resume when the server answers.
    state.solo = true;
    health.report('chat', 'warn', `solo: ${err.message}`, true);
    bus.emit('chat:status', { status: 'solo', detail: err.message });
    const src = root.dataset.src;
    loadItem({ id: 'local', kind: 'mp4', src, title: root.dataset.label || 'Video', status: 'ok' });
    setTimeout(boot, 5000);
  }
}
boot();
if (root.dataset.kind === 'youtube-preload') loadYouTubeApi().catch(() => {});
