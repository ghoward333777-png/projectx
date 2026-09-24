import { bus } from './bus.js';
import { Stage } from './stage.js';
import { Html5Adapter } from './player/html5.js';

const root = document.getElementById('stage');
const stage = new Stage(root);
const player = new Html5Adapter();
player.mount(stage.picture);

const $ = (id) => document.getElementById(id);
const playButton = $('ctl-play');
const timeLabel = $('ctl-time');
const cards = stage.cards;
const state = { name: 'loading', error: null };

// ---- state exposed for the browser check and for debugging ----
window.__watchRoom = { stage, player, get state() { return state.name; }, get error() { return state.error; } };

function setState(name, error = null) {
  state.name = name;
  state.error = error;
  $('dbg-state').textContent = error ? `${name}: ${error}` : name;
}

// ---- cards (first-play prompt, errors) ----
function showCard({ title, text, action }) {
  cards.replaceChildren();
  const card = document.createElement('div');
  card.className = 'card';
  const h = document.createElement('p');
  h.className = 'card__title';
  h.textContent = title;
  card.appendChild(h);
  if (text) {
    const p = document.createElement('p');
    p.className = 'card__text';
    p.textContent = text;
    card.appendChild(p);
  }
  if (action) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'button';
    b.textContent = action.label;
    b.addEventListener('click', action.run);
    card.appendChild(b);
  }
  cards.appendChild(card);
}
function clearCards() { cards.replaceChildren(); }

// ---- playback ----
async function togglePlay() {
  if (state.name === 'error') return;
  if (player.isPlaying()) { player.pause(); return; }
  try {
    await player.play();
    clearCards();
  } catch (err) {
    if (err && err.name === 'NotAllowedError') {
      showCard({ title: 'Tap to play', text: 'This browser wants a tap before it plays sound.', action: { label: 'Play', run: togglePlay } });
    } else {
      setState('error', err?.message || String(err));
      showCard({ title: 'Cannot play', text: err?.message || String(err) });
    }
  }
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
}

let lastRendered = -1;
function renderTime(t) {
  const whole = Math.floor(t);
  if (whole === lastRendered) return;
  lastRendered = whole;
  timeLabel.textContent = `${formatTime(t)} / ${formatTime(player.duration())}`;
}

player.on('play', () => { playButton.textContent = '⏸'; playButton.setAttribute('aria-label', 'Pause'); playButton.setAttribute('aria-pressed', 'true'); setState('playing'); });
player.on('pause', () => { playButton.textContent = '▶'; playButton.setAttribute('aria-label', 'Play'); playButton.setAttribute('aria-pressed', 'false'); if (state.name !== 'error') setState('paused'); });
player.on('ended', () => setState('ended'));
player.on('time', renderTime);
player.on('duration', () => { lastRendered = -1; renderTime(player.currentTime()); });
player.on('ready', (size) => {
  stage.setPictureSize(size);
  $('dbg-picture').textContent = size ? `${size.width} × ${size.height}` : '–';
});
player.on('error', (message) => {
  setState('error', message);
  showCard({ title: 'Cannot play this video', text: message });
});

// ---- controls ----
playButton.addEventListener('click', togglePlay);
$('ctl-fullscreen').addEventListener('click', () => stage.toggleFullscreen());

// Click on the picture toggles play; double-click toggles full screen. A short
// timer keeps the single click from firing on the way to a double click.
let clickTimer = 0;
stage.picture.addEventListener('click', () => {
  clearTimeout(clickTimer);
  clickTimer = setTimeout(togglePlay, 250);
});
stage.picture.addEventListener('dblclick', () => {
  clearTimeout(clickTimer);
  stage.toggleFullscreen();
});

document.addEventListener('keydown', (event) => {
  const target = event.target;
  const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable);
  if (typing) return;
  switch (event.key) {
    case ' ':
    case 'k':
    case 'K':
      event.preventDefault();
      togglePlay();
      break;
    case 'f':
    case 'F':
      event.preventDefault();
      stage.toggleFullscreen();
      break;
    case 'ArrowLeft':
      event.preventDefault();
      player.seek(player.currentTime() - (event.shiftKey ? 15 : 5));
      break;
    case 'ArrowRight':
      event.preventDefault();
      player.seek(player.currentTime() + (event.shiftKey ? 15 : 5));
      break;
    case 'Escape':
      if (root.classList.contains('is-fake-fullscreen')) stage.exitFullscreen();
      break;
    default:
      break;
  }
});

// ---- loader ----
const library = $('library');
if (library) {
  library.addEventListener('change', () => {
    if (library.value) location.href = `index.php?src=${encodeURIComponent(library.value)}`;
  });
}

// ---- geometry readout ----
bus.on('stage:layout', (rect) => {
  $('dbg-stage').textContent = `${Math.round(rect.stageWidth)} × ${Math.round(rect.stageHeight)}`;
  $('dbg-rect').textContent = `${Math.round(rect.x)}, ${Math.round(rect.y)} · ${Math.round(rect.width)} × ${Math.round(rect.height)} (${rect.source})`;
});
bus.on('stage:fullscreen', (on) => { $('dbg-fs').textContent = on ? 'yes' : 'no'; });

// ---- boot ----
(async () => {
  const src = root.dataset.src;
  setState('loading');
  try {
    await player.load({ src });
    setState('ready');
    await togglePlay();
  } catch (err) {
    setState('error', err?.message || String(err));
    showCard({ title: 'Cannot play this video', text: err?.message || String(err) });
  }
})();
