import { PlayerAdapter } from './adapter.js';

const EVENTS = ['ready', 'play', 'pause', 'time', 'seeked', 'ended', 'error', 'buffering', 'duration'];

// One stable player object for the rest of the app. Swapping the concrete adapter
// (HTML5 ↔ YouTube) never disturbs the controls, sync or chat subscriptions.
export class PlayerProxy extends PlayerAdapter {
  constructor(container) {
    super();
    this.container = container;
    this.current = null;
    this.kind = null;
    this._unbind = [];
  }

  use(adapter, kind) {
    if (this.current === adapter) return adapter;
    this.release();
    this.current = adapter;
    this.kind = kind;
    this._unbind = EVENTS.map((event) => adapter.on(event, (payload) => this.emit(event, payload)));
    adapter.mount(this.container);
    return adapter;
  }

  release() {
    this._unbind.forEach((off) => off());
    this._unbind = [];
    if (this.current) {
      try { this.current.destroy(); } catch (_err) { /* already gone */ }
    }
    this.current = null;
    this.kind = null;
  }

  get el() { return this.current?.el ?? null; }
  async load(item) { if (!this.current) throw new Error('No player'); return this.current.load(item); }
  play() { return this.current ? this.current.play() : Promise.reject(new Error('No player')); }
  pause() { this.current?.pause(); }
  seek(s) { this.current?.seek(s); }
  currentTime() { return this.current ? this.current.currentTime() : 0; }
  duration() { return this.current ? this.current.duration() : 0; }
  setVolume(v) { this.current?.setVolume(v); }
  setMuted(m) { this.current?.setMuted(m); }
  setRate(r) { this.current?.setRate(r); }
  pictureSize() { return this.current ? this.current.pictureSize() : null; }
  isPlaying() { return !!this.current && this.current.isPlaying(); }
  isMuted() { return !!this.current && this.current.isMuted(); }
  volume() { return this.current ? this.current.volume() : 1; }
  get caps() { return this.current ? this.current.caps : {}; }
  destroy() { this.release(); super.destroy(); }
}
