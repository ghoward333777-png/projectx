import { PlayerAdapter } from './adapter.js';

// Wraps one <video>. Emits a smooth 'time' event from requestAnimationFrame while
// playing because the native timeupdate is only ~4 Hz.
export class Html5Adapter extends PlayerAdapter {
  constructor() {
    super();
    const el = document.createElement('video');
    el.playsInline = true;
    el.setAttribute('playsinline', '');
    el.preload = 'metadata';
    el.controls = false;
    el.crossOrigin = null;
    this.el = el;
    this._raf = 0;
    this._size = null;

    el.addEventListener('loadedmetadata', () => {
      this._size = { width: el.videoWidth, height: el.videoHeight };
      this.emit('duration', el.duration);
    });
    el.addEventListener('durationchange', () => this.emit('duration', el.duration));
    el.addEventListener('play', () => { this._startClock(); this.emit('play'); });
    el.addEventListener('pause', () => { this._stopClock(); this.emit('pause'); });
    el.addEventListener('seeked', () => { this.emit('time', el.currentTime); this.emit('seeked', el.currentTime); });
    el.addEventListener('ended', () => { this._stopClock(); this.emit('ended'); });
    el.addEventListener('waiting', () => this.emit('buffering', true));
    el.addEventListener('playing', () => this.emit('buffering', false));
    el.addEventListener('canplay', () => this.emit('buffering', false));
    el.addEventListener('error', () => this.emit('error', describeMediaError(el.error)));
  }

  mount(container) {
    container.appendChild(this.el);
  }

  load(item) {
    const el = this.el;
    this._size = null;
    return new Promise((resolve, reject) => {
      const done = () => { cleanup(); resolve(this.pictureSize()); };
      const fail = () => { cleanup(); reject(new Error(describeMediaError(el.error))); };
      const cleanup = () => {
        el.removeEventListener('loadedmetadata', done);
        el.removeEventListener('error', fail);
      };
      el.addEventListener('loadedmetadata', done);
      el.addEventListener('error', fail);
      el.src = item.src;
      el.load();
    }).then((size) => { this.emit('ready', size); return size; });
  }

  play() { return this.el.play(); }
  pause() { this.el.pause(); }
  seek(seconds) {
    const d = this.duration();
    const t = Math.max(0, Number.isFinite(d) && d > 0 ? Math.min(seconds, d) : seconds);
    this.el.currentTime = t;
  }
  currentTime() { return this.el.currentTime; }
  duration() { return Number.isFinite(this.el.duration) ? this.el.duration : 0; }
  setVolume(v) { this.el.volume = Math.min(1, Math.max(0, v)); }
  setMuted(m) { this.el.muted = !!m; }
  setRate(r) { this.el.playbackRate = r; }
  pictureSize() { return this._size; }
  isPlaying() { return !this.el.paused && !this.el.ended; }
  isMuted() { return this.el.muted; }
  volume() { return this.el.volume; }

  get caps() {
    return {
      preciseTime: true,
      rate: true,
      captions: true,
      seekWhilePaused: true,
      nativeShield: false,
      autoplayNeedsGesture: true,
    };
  }

  destroy() {
    this._stopClock();
    this.el.removeAttribute('src');
    this.el.load();
    this.el.remove();
    super.destroy();
  }

  _startClock() {
    this._stopClock();
    const tick = () => {
      this.emit('time', this.el.currentTime);
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  _stopClock() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
  }
}

function describeMediaError(err) {
  if (!err) return 'The video could not be loaded.';
  switch (err.code) {
    case 1: return 'Loading was aborted.';
    case 2: return 'A network error stopped the download.';
    case 3: return 'The file is damaged or uses a codec this browser cannot decode.';
    case 4: return 'The source is not a playable video, or the server refused it.';
    default: return 'The video could not be loaded.';
  }
}
