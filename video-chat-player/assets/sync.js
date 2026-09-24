import { bus } from './bus.js';

const HEARTBEAT_MS = 10000;

// Keeps every viewer on the same moment. The acting host (or any member when the room
// allows guest control) publishes play/pause/seek; everyone applies the shared clock.
export class SyncController {
  constructor({ chat, player, playlist, health, requestPlay }) {
    this.chat = chat;
    this.player = player;
    this.playlist = playlist;
    this.health = health;
    this.requestPlay = requestPlay;
    this.state = null;
    this.expected = { play: [], pause: [], seek: [] };
    this.enabled = false;
    this.nudgeTimer = 0;
    this.heartbeat = 0;
    this.lastPublish = 0;
    bus.on('state:update', (state) => this.receive(state));
    player.on('play', () => this.local('play'));
    player.on('pause', () => this.local('pause'));
    player.on('seeked', () => this.local('seek'));
    player.on('ended', () => { this.stopHeartbeat(); });
  }

  get threshold() { return this.player.kind === 'youtube' ? 0.5 : 0.25; }

  canControl() { return this.chat.isActingHost || this.chat.isHost || !!this.chat.room?.guestsControl; }

  /** Where the shared clock says we should be right now. */
  expectedPosition(state = this.state) {
    if (!state) return null;
    if (!state.playing) return state.mediaTime;
    return state.mediaTime + ((this.chat.serverNow() - state.at) / 1000) * (state.rate || 1);
  }

  receive(state) {
    this.state = state;
    if (!this.enabled) return;
    if (state.by === this.chat.memberId && Date.now() - this.lastPublish < 1500) return; // our own echo
    this.apply();
  }

  /** Called after the current item finished loading, and on every remote state change. */
  apply() {
    const state = this.state;
    if (!state || !this.enabled) return;
    if (state.itemId && state.itemId !== this.playlist.loadedId) return; // the playlist handler switches items first
    const target = this.expectedPosition(state);
    const now = this.player.currentTime();
    const drift = target - now;
    if (Number.isFinite(state.rate) && state.rate !== this.player.rate) { this.player.setRate(state.rate); this.player.rate = state.rate; }
    if (Math.abs(drift) > this.threshold) {
      if (state.playing && Math.abs(drift) <= 1.5 && this.player.kind !== 'youtube') this.nudge(drift);
      else this.silently('seek', () => this.player.seek(Math.max(0, target)));
    }
    if (state.playing && !this.player.isPlaying()) this.silently('play', () => this.requestPlay());
    if (!state.playing && this.player.isPlaying()) this.silently('pause', () => this.player.pause());
    this.health?.report('sync', 'ok', `drift ${Math.round(drift * 1000)} ms`);
  }

  /** Runs a player call whose resulting event must not be published back as a user action. */
  silently(kind, fn) {
    this.expected[kind].push(Date.now());
    fn();
  }

  /** True (and consumed) when this event is the echo of something apply() just did. */
  consumeExpected(kind) {
    const list = this.expected[kind];
    const fresh = list.filter((t) => Date.now() - t < 3000);
    this.expected[kind] = fresh;
    if (fresh.length === 0) return false;
    fresh.shift();
    return true;
  }

  /** Small drift is corrected by running slightly fast or slow for a moment: invisible. */
  nudge(drift) {
    clearTimeout(this.nudgeTimer);
    const base = this.state?.rate || 1;
    const factor = drift > 0 ? 1.05 : 0.95;
    this.player.setRate(base * factor);
    const ms = Math.min(4000, Math.abs(drift) / 0.05 * 1000);
    this.nudgeTimer = setTimeout(() => this.player.setRate(base), ms);
  }

  /** A local user action becomes the room's state (when this member may control). */
  async local(kind) {
    if (!this.enabled) return;
    if (this.consumeExpected(kind)) return;
    if (!this.canControl()) {
      // Guests without control snap back to the shared clock instead of drifting off.
      if (this.state) setTimeout(() => this.apply(), 50);
      return;
    }
    await this.publish(kind);
  }

  async publish(reason = 'update') {
    if (!this.enabled || !this.chat.room) return;
    const item = this.playlist.currentId;
    const update = { itemId: item || undefined, playing: this.player.isPlaying(), mediaTime: this.player.currentTime(), rate: this.player.rate || 1, baseRev: this.state?.rev || 0 };
    this.lastPublish = Date.now();
    try {
      const data = await this.chat.call('state.set', { state: update });
      this.state = data.state;
      if (update.playing) this.startHeartbeat(); else this.stopHeartbeat();
    } catch (err) {
      if (err.code === 'stale' && err.body?.state) { this.state = err.body.state; this.apply(); return; }
      if (err.code === 'forbidden') { this.health?.report('sync', 'warn', 'host controls playback'); this.apply(); return; }
      this.health?.report('sync', 'warn', `${reason} not shared: ${err.message}`);
    }
  }

  startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeat = setInterval(() => { if (this.canControl() && this.player.isPlaying()) this.publish('heartbeat'); }, HEARTBEAT_MS);
  }

  stopHeartbeat() { clearInterval(this.heartbeat); this.heartbeat = 0; }

  /** After an item loads or a room is joined: the acting host's player is the truth, everyone else follows. */
  settle() {
    if (!this.enabled) return;
    if (this.chat.isActingHost) this.publish('settle');
    else this.apply();
  }

  enable() { this.enabled = true; }
  disable() { this.enabled = false; this.stopHeartbeat(); }
}
