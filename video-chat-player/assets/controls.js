import { bus } from './bus.js';
import { isTypingIn } from './idle.js';

const STORAGE_KEY = 'watchroom.audio';

export function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m);
  return `${h > 0 ? `${h}:` : ''}${mm}:${String(r).padStart(2, '0')}`;
}

// Control bar + keyboard map. Talks to the player and the stage; never to the overlay's DOM.
export class Controls {
  constructor({ root, player, stage, idle, togglePlay }) {
    this.player = player;
    this.stage = stage;
    this.idle = idle;
    this.togglePlay = togglePlay;
    this.chatEnabled = true;
    const $ = (id) => root.querySelector(`#${id}`);
    this.el = {
      play: $('ctl-play'), seek: $('ctl-seek'), time: $('ctl-time'), mute: $('ctl-mute'),
      volume: $('ctl-volume'), rate: $('ctl-rate'), chat: $('ctl-chat'), fullscreen: $('ctl-fullscreen'),
      chatDot: $('chat-dot'),
    };
    this.scrubbing = false;
    this.lastWhole = -1;
    this.wire();
    this.restoreAudio();
  }

  wire() {
    const { el, player } = this;
    el.play.addEventListener('click', () => this.togglePlay());
    el.fullscreen.addEventListener('click', () => this.stage.toggleFullscreen());
    el.chat.addEventListener('click', () => this.toggleChat());
    el.mute.addEventListener('click', () => this.setMuted(!this.currentMuted()));
    el.volume.addEventListener('input', () => { this.setVolume(Number(el.volume.value)); if (this.currentMuted() && Number(el.volume.value) > 0) this.setMuted(false); });
    el.rate.addEventListener('change', () => { player.rate = Number(el.rate.value); player.setRate(player.rate); player.emit('seeked', player.currentTime()); });

    // While dragging, the bar shows the target time instead of the playing time; the
    // seek itself happens on release and on every change (keyboard, programmatic).
    el.seek.addEventListener('pointerdown', () => { this.scrubbing = true; });
    el.seek.addEventListener('input', () => { this.renderTime(this.seekValueToTime()); });
    const commit = () => { this.scrubbing = false; player.seek(this.seekValueToTime()); };
    el.seek.addEventListener('change', commit);
    el.seek.addEventListener('pointerup', commit);
    el.seek.addEventListener('pointercancel', () => { this.scrubbing = false; });
    el.seek.addEventListener('keydown', (event) => {
      // The range input handles arrows itself; keep the global map out of it.
      if (event.key.startsWith('Arrow')) event.stopPropagation();
    });

    player.on('play', () => this.setPlaying(true));
    player.on('pause', () => this.setPlaying(false));
    player.on('ended', () => this.setPlaying(false));
    player.on('time', (t) => { if (!this.scrubbing) this.renderTime(t); });
    player.on('duration', () => { this.lastWhole = -1; this.renderTime(player.currentTime()); });
    bus.on('stage:fullscreen', (on) => {
      el.fullscreen.setAttribute('aria-label', on ? 'Leave full screen' : 'Full screen');
      el.fullscreen.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  seekValueToTime() {
    return (Number(this.el.seek.value) / 1000) * this.player.duration();
  }

  setPlaying(on) {
    const b = this.el.play;
    b.textContent = on ? '⏸' : '▶';
    b.setAttribute('aria-label', on ? 'Pause' : 'Play');
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  renderTime(t) {
    const d = this.player.duration();
    if (!this.scrubbing && d > 0) this.el.seek.value = String(Math.round((t / d) * 1000));
    const whole = Math.floor(t);
    if (whole === this.lastWhole && d > 0) return;
    this.lastWhole = whole;
    this.el.time.textContent = `${formatTime(t)} / ${d > 0 ? formatTime(d) : '–:––'}`;
  }

  setVolume(v) {
    v = Math.min(1, Math.max(0, v));
    this.player.setVolume(v);
    this.el.volume.value = String(v);
    this.persistAudio();
  }

  setMuted(m) {
    this.player.setMuted(m);
    this.el.mute.textContent = m || Number(this.el.volume.value) === 0 ? '🔇' : '🔊';
    this.el.mute.setAttribute('aria-label', m ? 'Unmute' : 'Mute');
    this.el.mute.setAttribute('aria-pressed', m ? 'true' : 'false');
    this.persistAudio();
  }

  currentVolume() { return Number(this.el.volume.value); }
  currentMuted() { return this.el.mute.getAttribute('aria-pressed') === 'true'; }

  nudgeVolume(delta) {
    this.setVolume(Number(this.el.volume.value) + delta);
    if (this.currentMuted() && delta > 0) this.setMuted(false);
  }

  toggleChat(force) {
    this.chatEnabled = typeof force === 'boolean' ? force : !this.chatEnabled;
    this.stage.root.classList.toggle('is-chat-off', !this.chatEnabled);
    this.el.chat.setAttribute('aria-pressed', this.chatEnabled ? 'true' : 'false');
    this.el.chat.setAttribute('aria-label', this.chatEnabled ? 'Hide chat' : 'Show chat');
    this.el.chatDot.hidden = this.chatEnabled;
    bus.emit('chat:enabled', this.chatEnabled);
  }

  persistAudio() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ volume: Number(this.el.volume.value), muted: this.currentMuted() }));
    } catch (_err) { /* private mode or blocked storage */ }
  }

  restoreAudio() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch (_err) { saved = null; }
    this.setVolume(saved && Number.isFinite(saved.volume) ? saved.volume : 1);
    this.setMuted(!!(saved && saved.muted));
  }
}

// Global shortcuts; none of them fire while typing (the composer handles its own keys).
export function installKeyboard({ player, stage, idle, controls, composer, togglePlay }) {
  document.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (isTypingIn(target)) {
      if (event.key === 'Escape' && target === composer) { composer.blur(); stage.root.focus(); }
      return;
    }
    const seekBy = (delta) => player.seek(player.currentTime() + delta);
    let handled = true;
    switch (event.key) {
      case ' ': case 'k': case 'K': togglePlay(); break;
      case 'ArrowLeft': seekBy(event.shiftKey ? -15 : -5); break;
      case 'ArrowRight': seekBy(event.shiftKey ? 15 : 5); break;
      case 'j': case 'J': seekBy(-10); break;
      case 'l': case 'L': seekBy(10); break;
      case 'ArrowUp': controls.nudgeVolume(0.05); break;
      case 'ArrowDown': controls.nudgeVolume(-0.05); break;
      case 'm': case 'M': controls.setMuted(!controls.currentMuted()); break;
      case 'f': case 'F': stage.toggleFullscreen(); break;
      case 'c': case 'C': controls.toggleChat(); break;
      case 'n': case 'N': bus.emit('playlist:next'); break;
      case 'p': case 'P': bus.emit('playlist:previous'); break;
      case 'Enter': case 't': case 'T': case '/':
        if (!controls.chatEnabled) controls.toggleChat(true);
        idle.activity();
        composer.focus();
        break;
      case 'Escape':
        if (stage.isFullscreen() && stage.root.classList.contains('is-fake-fullscreen')) stage.exitFullscreen();
        else handled = false;
        break;
      default: handled = false;
    }
    if (handled) event.preventDefault();
  });
}
