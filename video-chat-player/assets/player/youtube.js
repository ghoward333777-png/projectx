import { PlayerAdapter } from './adapter.js';

const API_URL = 'https://www.youtube.com/iframe_api';
const API_TIMEOUT_MS = 8000;
const START_TIMEOUT_MS = 15000;
let apiPromise = null;

// Loads YouTube's IFrame API once. Rejects (and forgets, so a retry is possible) when
// the script is blocked or never calls back: the claude.ai preview panel, ad blockers
// and some corporate networks all do that.
export function loadYouTubeApi(timeoutMs = API_TIMEOUT_MS) {
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve, reject) => {
    const timer = setTimeout(() => fail(new Error('YouTube did not answer. This window may block YouTube.')), timeoutMs);
    const previous = window.onYouTubeIframeAPIReady;
    const done = () => { clearTimeout(timer); if (typeof previous === 'function') previous(); resolve(window.YT); };
    const fail = (err) => { clearTimeout(timer); apiPromise = null; script.remove(); reject(err); };
    window.onYouTubeIframeAPIReady = done;
    const script = document.createElement('script');
    script.src = API_URL;
    script.async = true;
    script.onerror = () => fail(new Error('The YouTube player script could not load. This window blocks YouTube.'));
    document.head.appendChild(script);
  });
  return apiPromise;
}

export function describeYouTubeError(code) {
  switch (Number(code)) {
    case 2: return 'That YouTube link is not valid.';
    case 5: return 'YouTube could not play this in an HTML5 player.';
    case 100: return 'This video was removed or is private.';
    case 101:
    case 150: return 'The uploader does not allow this video to play outside YouTube.';
    default: return 'YouTube could not play this video here.';
  }
}

export class YouTubeAdapter extends PlayerAdapter {
  constructor() {
    super();
    this.host = document.createElement('div');
    this.host.className = 'yt-host';
    this.target = document.createElement('div');
    this.host.appendChild(this.target);
    // The shield keeps pointer events on our page (the iframe would swallow them), so
    // the idle timer and click-to-pause behave exactly as they do over an MP4.
    this.shield = document.createElement('div');
    this.shield.className = 'yt-shield';
    this.host.appendChild(this.shield);
    this.player = null;
    this.ready = false;
    this.playing = false;
    this.clock = 0;
    this._duration = 0;
    this._muted = false;
    this._volume = 1;
    this._pending = null;
  }

  mount(container) { container.appendChild(this.host); }

  get el() { return this.host; }

  async load(item) {
    const YT = await loadYouTubeApi();
    this.ready = false;
    this.playing = false;
    this._duration = 0;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this._pending = null; reject(new Error('The YouTube player did not start in time.')); }, START_TIMEOUT_MS);
      this._pending = { resolve, reject, timer };
      const settle = (fn, value) => { if (!this._pending) return; clearTimeout(this._pending.timer); this._pending = null; fn(value); };
      const onReady = () => {
        this.ready = true;
        try { this.player.setVolume(Math.round(this._volume * 100)); if (this._muted) this.player.mute(); } catch (_err) { /* not ready */ }
        this._duration = this.safe(() => this.player.getDuration()) || 0;
        this.emit('duration', this._duration);
        this.emit('ready', this.pictureSize());
        settle(resolve, this.pictureSize());
      };
      const onError = (event) => {
        const message = describeYouTubeError(event.data);
        settle(reject, new Error(message));
        this.emit('error', message);
      };
      const isList = item.kind === 'youtube-playlist';
      if (this.player) {
        try { isList ? this.player.loadPlaylist({ list: item.src, listType: 'playlist' }) : this.player.loadVideoById(item.src); } catch (_err) { /* fallthrough to rebuild */ }
        if (this.ready) { clearTimeout(timer); this._pending = null; this.emit('duration', 0); resolve(this.pictureSize()); }
        return;
      }
      try {
        const playerVars = { controls: 0, rel: 0, modestbranding: 1, fs: 0, playsinline: 1, enablejsapi: 1, iv_load_policy: 3, disablekb: 1, autoplay: 0, origin: location.origin };
        if (isList) { playerVars.listType = 'playlist'; playerVars.list = item.src; }
        this.player = new YT.Player(this.target, {
          ...(isList ? {} : { videoId: item.src }),
          width: '100%',
          height: '100%',
          host: 'https://www.youtube-nocookie.com',
          playerVars,
          events: {
            onReady,
            onError,
            onStateChange: (event) => this.onState(event.data, YT),
          },
        });
      } catch (err) {
        settle(reject, err);
      }
    });
  }

  onState(state, YT) {
    const S = YT.PlayerState;
    if (state === S.PLAYING) {
      this.playing = true;
      if (!this._duration) { this._duration = this.safe(() => this.player.getDuration()) || 0; this.emit('duration', this._duration); }
      this.startClock();
      this.emit('buffering', false);
      this.emit('play');
    } else if (state === S.PAUSED) {
      this.playing = false;
      this.stopClock();
      this.emit('pause');
    } else if (state === S.ENDED) {
      this.playing = false;
      this.stopClock();
      this.emit('ended');
    } else if (state === S.BUFFERING) {
      this.emit('buffering', true);
    } else if (state === S.CUED) {
      this.emit('duration', this.safe(() => this.player.getDuration()) || 0);
    }
  }

  safe(fn, fallback = null) { try { return fn(); } catch (_err) { return fallback; } }

  play() {
    return new Promise((resolve, reject) => {
      if (!this.ready) { reject(new Error('YouTube player is not ready.')); return; }
      this.safe(() => this.player.playVideo());
      resolve();
    });
  }

  pause() { this.safe(() => this.player.pauseVideo()); }
  seek(seconds) { this.safe(() => this.player.seekTo(Math.max(0, seconds), true)); this.emit('time', seconds); this.emit('seeked', seconds); }
  currentTime() { return this.safe(() => this.player.getCurrentTime(), 0) || 0; }
  duration() { return this._duration || this.safe(() => this.player.getDuration(), 0) || 0; }
  setVolume(v) { this._volume = v; this.safe(() => this.player.setVolume(Math.round(v * 100))); }
  setMuted(m) { this._muted = m; this.safe(() => (m ? this.player.mute() : this.player.unMute())); }
  setRate(r) { this.safe(() => this.player.setPlaybackRate(r)); }
  pictureSize() { return { width: 16, height: 9 }; }
  isPlaying() { return this.playing; }
  isLive() { const vd = this.safe(() => this.player.getVideoData(), null); if (vd && typeof vd.isLive === 'boolean') return vd.isLive; return this.ready && this.playing && !(this.duration() > 0) && this.currentTime() > 1; }
  isMuted() { return this._muted; }
  volume() { return this._volume; }

  /** Inner playlist support (a youtube-playlist item) through the API's own playlist calls. */
  innerPlaylist() { const list = this.safe(() => this.player.getPlaylist(), null); return list && list.length ? { index: this.safe(() => this.player.getPlaylistIndex(), 0) || 0, count: list.length } : null; }
  innerNext() { const p = this.innerPlaylist(); if (!p || p.index >= p.count - 1) return false; this.safe(() => this.player.nextVideo()); return true; }
  innerPrevious() { const p = this.innerPlaylist(); if (!p || p.index <= 0) return false; this.safe(() => this.player.previousVideo()); return true; }

  get caps() {
    return { preciseTime: false, rate: true, captions: true, seekWhilePaused: true, nativeShield: true, autoplayNeedsGesture: true, innerPlaylist: true, engine: 'api' };
  }

  startClock() {
    this.stopClock();
    this.clock = setInterval(() => { this.emit('time', this.currentTime()); const p = this.innerPlaylist(); if (p && (p.index !== this._innerIndex)) { this._innerIndex = p.index; this.emit('inner-playlist', p); } }, 100);
  }

  stopClock() { clearInterval(this.clock); this.clock = 0; }

  destroy() {
    this.stopClock();
    if (this._pending) { clearTimeout(this._pending.timer); this._pending = null; }
    this.safe(() => this.player && this.player.destroy());
    this.player = null;
    this.host.remove();
    super.destroy();
  }
}

/** Reads a YouTube playlist's video ids through a hidden player (no API key needed). */
export async function readYouTubePlaylist(listId, timeoutMs = 12000) {
  const YT = await loadYouTubeApi();
  const holder = document.createElement('div');
  holder.style.cssText = 'position:fixed;left:-9999px;top:0;width:200px;height:200px;';
  const target = document.createElement('div');
  holder.appendChild(target);
  document.body.appendChild(holder);
  let player = null;
  try {
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('YouTube did not return that playlist.')), timeoutMs);
      const finish = () => {
        const ids = (player && player.getPlaylist && player.getPlaylist()) || [];
        if (ids.length) { clearTimeout(timer); resolve(ids); }
      };
      player = new YT.Player(target, {
        width: 200, height: 200,
        playerVars: { listType: 'playlist', list: listId, controls: 0 },
        events: {
          onReady: () => { setTimeout(finish, 500); setTimeout(finish, 2500); setTimeout(finish, 6000); },
          onStateChange: () => finish(),
          onError: (e) => { clearTimeout(timer); reject(new Error(describeYouTubeError(e.data))); },
        },
      });
    });
  } finally {
    try { player && player.destroy(); } catch (_err) { /* ignore */ }
    holder.remove();
  }
}
