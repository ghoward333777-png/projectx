import { bus } from './bus.js';
import { api, ApiError } from './api.js';

const STORAGE_PREFIX = 'watchroom.member.';

// Room membership, the polling loop and the outbox. One request per tick carries
// messages, members, playlist and playback state. Failures back off and recover on
// their own; the health module shows the state and nothing ever throws at the UI.
export class ChatClient {
  constructor({ mediaTime, currentItemId }) {
    this.mediaTime = mediaTime;
    this.currentItemId = currentItemId;
    this.room = null;
    this.memberId = null;
    this.hostToken = null;
    this.since = 0;
    this.playlistRev = 0;
    this.stateRev = 0;
    this.roomRev = 0;
    this.members = [];
    this.actingHostId = null;
    this.offsets = [];
    this.outbox = [];
    this.failures = 0;
    this.timer = 0;
    this.inFlight = false;
    this.stopped = false;
    this.status = 'idle';
    this.listeners();
  }

  // ---- identity ----

  static loadIdentity(roomId) {
    try { return JSON.parse(localStorage.getItem(STORAGE_PREFIX + roomId) || 'null'); } catch (_err) { return null; }
  }

  static saveIdentity(roomId, identity) {
    try { localStorage.setItem(STORAGE_PREFIX + roomId, JSON.stringify(identity)); } catch (_err) { /* storage blocked */ }
  }

  static lastName() {
    try { return localStorage.getItem('watchroom.name') || ''; } catch (_err) { return ''; }
  }

  static rememberName(name) {
    try { localStorage.setItem('watchroom.name', name); } catch (_err) { /* storage blocked */ }
  }

  // ---- lifecycle ----

  async create(name, src) {
    const data = await api('room.create', { name, src });
    this.apply(data, { hostToken: data.hostToken });
    ChatClient.saveIdentity(this.room.id, { memberId: this.memberId, hostToken: this.hostToken, name });
    ChatClient.rememberName(name);
    this.start();
    return data;
  }

  async join(roomId, name) {
    const saved = ChatClient.loadIdentity(roomId);
    const data = await api('room.join', { roomId, name, memberId: saved?.memberId || undefined });
    this.apply(data, { hostToken: saved?.hostToken || null });
    ChatClient.saveIdentity(roomId, { memberId: this.memberId, hostToken: this.hostToken, name });
    ChatClient.rememberName(name);
    this.start();
    return data;
  }

  async rename(name) {
    const data = await api('room.join', { roomId: this.room.id, name, memberId: this.memberId });
    this.apply(data, { hostToken: this.hostToken, keepCursor: true });
    ChatClient.saveIdentity(this.room.id, { memberId: this.memberId, hostToken: this.hostToken, name });
    ChatClient.rememberName(name);
  }

  apply(data, { hostToken, keepCursor = false } = {}) {
    this.room = data.room;
    this.memberId = data.memberId;
    this.hostToken = hostToken ?? this.hostToken;
    this.members = data.room.members;
    this.actingHostId = data.actingHostId ?? null;
    this.roomRev = data.room.updatedAt || 0;
    this.noteServerTime(data.serverTime);
    if (!keepCursor) {
      this.since = data.since || 0;
      bus.emit('chat:history', data.messages || []);
    }
    this.absorbRevisions(data, true);
    bus.emit('room:update', { room: this.room, members: this.members, actingHostId: this.actingHostId, me: this.memberId });
  }

  /** Applies playlist/state from any response, ignoring anything older than what we already have (late polls). */
  absorbRevisions(data, force = false) {
    if (data.playlist && (force || data.playlist.rev > this.playlistRev)) { this.playlistRev = data.playlist.rev; bus.emit('playlist:update', data.playlist); }
    if (data.state && (force || data.state.rev > this.stateRev)) { this.stateRev = data.state.rev; bus.emit('state:update', data.state); }
  }

  get me() { return this.members.find((m) => m.id === this.memberId) || null; }
  get isHost() { return !!this.room && this.room.hostMemberId === this.memberId; }
  get isActingHost() { return this.actingHostId === this.memberId; }
  get onlineCount() { return this.members.filter((m) => m.online).length; }

  // ---- clock ----

  noteServerTime(serverTime) {
    if (!Number.isFinite(serverTime)) return;
    this.offsets.push(serverTime - Date.now());
    if (this.offsets.length > 5) this.offsets.shift();
  }

  /** serverTime − localTime, median of the last five samples. */
  get offset() {
    if (this.offsets.length === 0) return 0;
    const sorted = [...this.offsets].sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)];
  }

  serverNow() { return Date.now() + this.offset; }

  // ---- polling ----

  start() {
    this.stopped = false;
    this.schedule(0);
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
  }

  interval() {
    if (this.failures > 0) return Math.min(15000, 1000 * 2 ** this.failures);
    if (document.hidden) return 5000;
    return this.onlineCount >= 2 ? 1000 : 2500;
  }

  schedule(ms) {
    clearTimeout(this.timer);
    if (this.stopped) return;
    this.timer = setTimeout(() => this.poll(), ms);
  }

  async poll() {
    if (this.inFlight || this.stopped || !this.room) return;
    if (navigator.onLine === false) { this.setStatus('offline'); this.schedule(2000); return; }
    this.inFlight = true;
    try {
      const data = await api('sync.poll', { roomId: this.room.id, memberId: this.memberId, since: this.since, prev: this.playlistRev, srev: this.stateRev, rrev: this.roomRev }, { method: 'GET', timeoutMs: 6000 });
      this.failures = 0;
      this.setStatus('live');
      this.noteServerTime(data.serverTime);
      this.members = data.members || this.members;
      this.actingHostId = data.actingHostId ?? this.actingHostId;
      if (data.room) { this.room = data.room; this.roomRev = data.room.updatedAt || this.roomRev; }
      bus.emit('room:update', { room: this.room, members: this.members, actingHostId: this.actingHostId, me: this.memberId });
      if (data.messages && data.messages.length) {
        this.since = data.since;
        bus.emit('chat:messages', data.messages);
      }
      this.absorbRevisions(data);
      this.flushOutbox();
    } catch (err) {
      this.failures = Math.min(this.failures + 1, 6);
      if (err instanceof ApiError && (err.code === 'not_found' || err.code === 'bad_request')) {
        this.setStatus('lost', err.message);
        bus.emit('room:lost', err);
        this.stop();
        return;
      }
      this.setStatus(this.failures >= 2 ? 'reconnecting' : 'live', err.message);
    } finally {
      this.inFlight = false;
      this.schedule(this.interval());
    }
  }

  setStatus(status, detail = '') {
    if (this.status === status && !detail) return;
    this.status = status;
    bus.emit('chat:status', { status, detail, failures: this.failures });
  }

  // ---- sending ----

  send(text) {
    text = String(text || '').trim();
    if (!text || !this.room) return null;
    const me = this.me;
    const message = {
      id: `c_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`,
      kind: 'chat', memberId: this.memberId, name: me?.name || 'me', colour: me?.colour || '#fff',
      text, mediaTime: (() => { const t = this.mediaTime(); return Number.isFinite(t) ? Math.round(t * 100) / 100 : null; })(), itemId: this.currentItemId(), sentAt: this.serverNow(), pending: true, attempts: 0,
    };
    this.outbox.push(message);
    bus.emit('chat:pending', message);
    this.flushOutbox();
    return message;
  }

  async flushOutbox() {
    if (this.flushing) return;
    this.flushing = true;
    try {
      while (this.outbox.length) {
        const message = this.outbox[0];
        if (message.nextTry && message.nextTry > Date.now()) break;
        try {
          const data = await api('chat.send', { roomId: this.room.id, memberId: this.memberId, id: message.id, text: message.text, mediaTime: message.mediaTime, itemId: message.itemId });
          this.outbox.shift();
          bus.emit('chat:sent', { id: message.id, message: data.message });
          this.schedule(0);
        } catch (err) {
          message.attempts += 1;
          if (err instanceof ApiError && (err.code === 'rate_limited' || err.code === 'bad_request' || err.code === 'forbidden')) {
            this.outbox.shift();
            bus.emit('chat:failed', { id: message.id, reason: err.message, retryable: err.code === 'rate_limited' });
            continue;
          }
          if (message.attempts >= 4) {
            this.outbox.shift();
            bus.emit('chat:failed', { id: message.id, reason: err.message, retryable: true });
            continue;
          }
          message.nextTry = Date.now() + 1000 * 2 ** (message.attempts - 1);
          setTimeout(() => this.flushOutbox(), 1000 * 2 ** (message.attempts - 1));
          break;
        }
      }
    } finally {
      this.flushing = false;
    }
  }

  /** Re-queue a failed message by id (from the "retry" link on the bubble). */
  retry(message) {
    message.attempts = 0;
    message.nextTry = 0;
    message.pending = true;
    this.outbox.push(message);
    this.flushOutbox();
  }

  // ---- room actions (playlist, state, settings) all go through here so errors are uniform ----

  async call(action, params, options) {
    if (!this.room) throw new ApiError('Not in a room yet.', 'no_room', 0, null);
    const data = await api(action, { roomId: this.room.id, memberId: this.memberId, hostToken: this.hostToken || undefined, ...params }, options);
    this.noteServerTime(data.serverTime);
    this.absorbRevisions(data);
    if (data.room) { this.room = data.room; this.members = data.room.members; this.roomRev = data.room.updatedAt || this.roomRev; bus.emit('room:update', { room: this.room, members: this.members, actingHostId: this.actingHostId, me: this.memberId }); }
    return data;
  }

  listeners() {
    document.addEventListener('visibilitychange', () => { if (!document.hidden) this.schedule(0); });
    window.addEventListener('online', () => { this.failures = 0; this.setStatus('live'); this.schedule(0); this.flushOutbox(); });
    window.addEventListener('offline', () => this.setStatus('offline'));
  }
}
