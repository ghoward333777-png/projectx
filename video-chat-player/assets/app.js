import { bus } from './bus.js';
import { Stage } from './stage.js';
import { IdleController } from './idle.js';
import { Controls, installKeyboard } from './controls.js';
import { Html5Adapter } from './player/html5.js';

const root = document.getElementById('stage');
const stage = new Stage(root);
const player = new Html5Adapter();
player.mount(stage.picture);
const idle = new IdleController(stage, { timeout: Number(root.dataset.idleTimeout) || 3000 });

const $ = (id) => document.getElementById(id);
const cards = stage.cards;
const composer = $('overlay-input');
const state = { name: 'loading', error: null };

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
  idle.pin('modal');
}
function clearCards() { cards.replaceChildren(); idle.unpin('modal'); }

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

const controls = new Controls({ root, player, stage, idle, togglePlay });
installKeyboard({ player, stage, idle, controls, composer, togglePlay });

player.on('play', () => { setState('playing'); idle.unpin('paused'); });
player.on('pause', () => { if (state.name !== 'error') setState('paused'); idle.pin('paused'); });
player.on('ended', () => { setState('ended'); idle.pin('paused'); });
player.on('ready', (size) => {
  stage.setPictureSize(size);
  $('dbg-picture').textContent = size ? `${size.width} × ${size.height}` : '–';
});
player.on('error', (message) => {
  setState('error', message);
  showCard({ title: 'Cannot play this video', text: message });
});

// ---- picture clicks: desktop toggles play / double-click full screen; touch toggles the overlay ----
let clickTimer = 0;
stage.picture.addEventListener('click', () => {
  clearTimeout(clickTimer);
  if (idle.touch) { idle.toggle(); return; }
  clickTimer = setTimeout(togglePlay, 250);
});
stage.picture.addEventListener('dblclick', () => {
  clearTimeout(clickTimer);
  stage.toggleFullscreen();
});

// ---- composer pins (the chat itself arrives in step 3) ----
composer.addEventListener('focus', () => idle.pin('composer'));
composer.addEventListener('blur', () => idle.unpin('composer'));
composer.addEventListener('input', () => {
  if (composer.value.trim() !== '') idle.pin('draft');
  else idle.unpin('draft');
});
$('overlay-composer').addEventListener('submit', (event) => {
  event.preventDefault();
  const text = composer.value.trim();
  if (text === '') return;
  const line = document.createElement('p');
  line.className = 'overlay__system';
  line.textContent = `Sending arrives in step 3. You typed: "${text}"`;
  $('overlay-list').appendChild(line);
  $('overlay-list').scrollTop = $('overlay-list').scrollHeight;
  composer.value = '';
  idle.unpin('draft');
});

// ---- loader ----
const library = $('library');
if (library) {
  library.addEventListener('change', () => {
    if (library.value) location.href = `index.php?src=${encodeURIComponent(library.value)}`;
  });
}

// ---- geometry / state readout ----
bus.on('stage:layout', (rect) => {
  $('dbg-stage').textContent = `${Math.round(rect.stageWidth)} × ${Math.round(rect.stageHeight)}`;
  $('dbg-rect').textContent = `${Math.round(rect.x)}, ${Math.round(rect.y)} · ${Math.round(rect.width)} × ${Math.round(rect.height)} (${rect.source})`;
});
bus.on('stage:fullscreen', (on) => { $('dbg-fs').textContent = on ? 'yes' : 'no'; });
bus.on('idle:state', (s) => { $('dbg-idle').textContent = s + (idle.pins.size ? ` (${[...idle.pins].join(', ')})` : ''); });

window.__watchRoom = { stage, player, idle, controls, get state() { return state.name; }, get error() { return state.error; } };

// ---- boot ----
(async () => {
  setState('loading');
  try {
    await player.load({ src: root.dataset.src });
    setState('ready');
    await togglePlay();
  } catch (err) {
    setState('error', err?.message || String(err));
    showCard({ title: 'Cannot play this video', text: err?.message || String(err) });
  }
})();
