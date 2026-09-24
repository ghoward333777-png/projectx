// The one interface the rest of the app sees. Concrete adapters extend it.
// Events: 'ready' (pictureSize), 'play', 'pause', 'time' (seconds), 'seeked',
// 'ended', 'error' (message), 'buffering' (bool), 'duration' (seconds).
export class PlayerAdapter {
  constructor() {
    this._handlers = new Map();
  }

  /** Load an item ({ src }); resolves with the picture size once metadata is known. */
  async load(_item) { throw new Error('load() not implemented'); }
  play() {}
  pause() {}
  seek(_seconds) {}
  currentTime() { return 0; }
  duration() { return 0; }
  setVolume(_v) {}
  setMuted(_m) {}
  setRate(_r) {}
  /** Natural picture size { width, height }, or null until known. */
  pictureSize() { return null; }
  isPlaying() { return false; }
  get caps() { return {}; }
  destroy() { this._handlers.clear(); }

  on(event, fn) {
    if (!this._handlers.has(event)) this._handlers.set(event, new Set());
    this._handlers.get(event).add(fn);
    return () => this._handlers.get(event)?.delete(fn);
  }

  emit(event, payload) {
    this._handlers.get(event)?.forEach((fn) => fn(payload));
  }
}
