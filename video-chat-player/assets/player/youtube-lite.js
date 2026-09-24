import { PlayerAdapter } from './adapter.js';
import { describeYouTubeError } from './youtube.js';

const HOST = 'https://www.youtube-nocookie.com';
const READY_TIMEOUT_MS = 10000;

// API-free YouTube engine: a plain embed <iframe src="…/embed/ID?enablejsapi=1"> driven
// with the same postMessage protocol YouTube's own player script uses, so nothing from
// YouTube runs on our page. A playlist item embeds videoseries?list=… and the embed's own
// next/previous keep the whole list inside one item.
export class YouTubeLiteAdapter extends PlayerAdapter {
  constructor() {
    super();
    this.host = document.createElement('div');
    this.host.className = 'yt-host';
    this.frame = null;
    this.shield = document.createElement('div');
    this.shield.className = 'yt-shield';
    this.host.appendChild(this.shield);
    this.ready = false;
    this.playing = false;
    this.info = { currentTime: 0, duration: 0, playerState: -1, playlist: null, playlistIndex: -1, volume: 100, muted: false };
    this._volume = 1;
    this._muted = false;
    this._pending = null;
    this._lastTime = -1;
    this._onMessage = (event) => this.receive(event);
    window.addEventListener('message', this._onMessage);
  }

  mount(container) { container.appendChild(this.host); }
  get el() { return this.host; }

  static embedUrl(item) {
    const params = new URLSearchParams({ enablejsapi: '1', controls: '0', rel: '0', playsinline: '1', fs: '0', iv_load_policy: '3', disablekb: '1', modestbranding: '1', origin: location.origin, widget_referrer: location.href });
    if (item.kind === 'youtube-playlist') {
      params.set('list', item.src);
      params.set('listType', 'playlist');
      return `${HOST}/embed/${item.firstVideo || 'videoseries'}?${params}`;
    }
    return `${HOST}/embed/${item.src}?${params}`;
  }

  load(item) {
    this.ready = false;
    this.playing = false;
    this.info = { ...this.info, currentTime: 0, duration: 0, playerState: -1, playlist: null, playlistIndex: -1 };
    if (this.frame) this.frame.remove();
    const frame = document.createElement('iframe');
    frame.className = 'yt-lite-frame';
    frame.allow = 'autoplay; encrypted-media; picture-in-picture';
    frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    frame.src = YouTubeLiteAdapter.embedUrl(item);
    this.frame = frame;
    this.host.insertBefore(frame, this.shield);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this._pending = null; reject(new Error('The YouTube embed did not answer. This window may block YouTube.')); }, READY_TIMEOUT_MS);
      this._pending = { resolve, reject, timer };
      frame.addEventListener('load', () => this.handshake());
      frame.addEventListener('error', () => this.settle('reject', new Error('The YouTube embed could not load.')));
    });
  }

  /** Tells the embed we are listening; it answers with onReady and starts infoDelivery. */
  handshake() {
    this.post({ event: 'listening', id: 1, channel: 'widget' });
    // Some builds only start delivering after a command; ask for the current state.
    setTimeout(() => this.command('getPlayerState'), 300);
  }

  settle(kind, value) {
    if (!this._pending) return;
    clearTimeout(this._pending.timer);
    const p = this._pending;
    this._pending = null;
    kind === 'resolve' ? p.resolve(value) : p.reject(value);
  }

  post(message) {
    try { this.frame?.contentWindow?.postMessage(JSON.stringify(message), HOST); } catch (_err) { /* frame gone */ }
  }

  command(func, args = []) { this.post({ event: 'command', func, args, id: 1, channel: 'widget' }); }

  receive(event) {
    if (event.origin !== HOST || !this.frame || event.source !== this.frame.contentWindow) return;
    let data;
    try { data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data; } catch (_err) { return; }
    if (!data || typeof data !== 'object') return;
    if (data.event === 'onReady' || data.event === 'initialDelivery') {
      if (data.info) Object.assign(this.info, data.info);
      if (!this.ready) {
        this.ready = true;
        this.command('setVolume', [Math.round(this._volume * 100)]);
        if (this._muted) this.command('mute');
        this.emit('duration', this.info.duration || 0);
        this.emit('ready', this.pictureSize());
        this.settle('resolve', this.pictureSize());
      }
    }
    if (data.event === 'infoDelivery' && data.info) {
      const before = this.info.duration;
      Object.assign(this.info, data.info);
      if (typeof data.info.currentTime === 'number' && data.info.currentTime !== this._lastTime) { this._lastTime = data.info.currentTime; this.emit('time', data.info.currentTime); }
      if (typeof data.info.duration === 'number' && data.info.duration !== before) this.emit('duration', data.info.duration);
      if (typeof data.info.playerState === 'number') this.onState(data.info.playerState);
      if (data.info.playlist) this.emit('inner-playlist', { index: this.info.playlistIndex, count: this.info.playlist.length });
    }
    if (data.event === 'onStateChange') this.onState(Number(data.info));
    if (data.event === 'onError') {
      const message = describeYouTubeError(data.info);
      this.settle('reject', new Error(message));
      this.emit('error', message);
    }
  }

  onState(state) {
    if (state === this.info.lastState) return;
    this.info.lastState = state;
    if (state === 1) { this.playing = true; this.emit('buffering', false); this.emit('play'); }
    else if (state === 2) { this.playing = false; this.emit('pause'); }
    else if (state === 0) { this.playing = false; this.emit('ended'); }
    else if (state === 3) this.emit('buffering', true);
    else if (state === 5) this.emit('duration', this.info.duration || 0);
  }

  play() { return new Promise((resolve, reject) => { if (!this.ready) { reject(new Error('YouTube embed is not ready.')); return; } this.command('playVideo'); resolve(); }); }
  pause() { this.command('pauseVideo'); }
  seek(seconds) { this.command('seekTo', [Math.max(0, seconds), true]); this.emit('time', seconds); this.emit('seeked', seconds); }
  currentTime() { return this.info.currentTime || 0; }
  duration() { return this.info.duration || 0; }
  setVolume(v) { this._volume = v; this.command('setVolume', [Math.round(v * 100)]); }
  setMuted(m) { this._muted = m; this.command(m ? 'mute' : 'unMute'); }
  setRate(r) { this.command('setPlaybackRate', [r]); }
  pictureSize() { return { width: 16, height: 9 }; }
  isPlaying() { return this.playing; }
  isLive() { const vd = this.info.videoData; if (vd && typeof vd.isLive === 'boolean') return vd.isLive; return this.ready && (this.playing || this.info.playerState === 3) && !(this.info.duration > 0) && this.info.currentTime > 1; }
  isMuted() { return this._muted; }
  volume() { return this._volume; }

  /** Inner playlist (a youtube-playlist item): position and stepping without leaving the item. */
  innerPlaylist() { return this.info.playlist ? { index: this.info.playlistIndex, count: this.info.playlist.length } : null; }
  innerNext() { const p = this.innerPlaylist(); if (!p || p.index >= p.count - 1) return false; this.command('nextVideo'); return true; }
  innerPrevious() { const p = this.innerPlaylist(); if (!p || p.index <= 0) return false; this.command('previousVideo'); return true; }

  get caps() {
    return { preciseTime: false, rate: true, captions: false, seekWhilePaused: true, nativeShield: true, autoplayNeedsGesture: true, innerPlaylist: true, engine: 'lite' };
  }

  destroy() {
    window.removeEventListener('message', this._onMessage);
    if (this._pending) { clearTimeout(this._pending.timer); this._pending = null; }
    this.frame?.remove();
    this.host.remove();
    super.destroy();
  }
}
