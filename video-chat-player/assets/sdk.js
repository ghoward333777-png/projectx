// Watch Room SDK: one small client for browsers and Node (18+). No dependencies.
//
//   import { WatchRoomClient } from './assets/sdk.js';
//   const room = await WatchRoomClient.create({ base: 'https://example.com/video-chat-player/api.php', name: 'Bot', src: 'https://youtu.be/…' });
//   room.on('message', (m) => console.log(m.name, m.text));
//   await room.send('hello');
//   await room.play(0);
//   const stop = room.subscribe();            // SSE when available, polling otherwise
//
// Every method resolves with the server's JSON or rejects with a WatchRoomError { code, status, body }.

export class WatchRoomError extends Error {
  constructor(message, code, status, body) { super(message); this.code = code; this.status = status; this.body = body; }
}

export class WatchRoomClient {
  constructor({ base, roomId, memberId, hostToken = null, apiKey = null, fetchImpl = null }) {
    this.base = String(base).replace(/\/$/, '');
    this.roomId = roomId;
    this.memberId = memberId;
    this.hostToken = hostToken;
    this.apiKey = apiKey;
    this.fetch = fetchImpl || globalThis.fetch.bind(globalThis);
    this.cursors = { since: 0, prev: 0, srev: 0 };
    this.handlers = new Map();
    this.offset = 0;
    this.stateCache = null;
    this.playlistCache = null;
    this.members = [];
  }

  // ---- constructors ----

  static async create({ base, name, src, apiKey = null, fetchImpl = null }) {
    const c = new WatchRoomClient({ base, roomId: null, memberId: null, apiKey, fetchImpl });
    const data = await c.request('POST', '/v1/rooms', { name, src });
    c.roomId = data.room.id;
    c.memberId = data.memberId;
    c.hostToken = data.hostToken;
    c.absorb(data);
    return c;
  }

  static async join({ base, roomId, name, memberId = null, hostToken = null, fetchImpl = null }) {
    const c = new WatchRoomClient({ base, roomId, memberId, hostToken, fetchImpl });
    const data = await c.request('POST', `/v1/rooms/${roomId}/members`, { name, memberId: memberId || undefined }, { auth: false });
    c.memberId = data.memberId;
    c.absorb(data);
    return c;
  }

  // ---- rooms ----

  room() { return this.request('GET', `/v1/rooms/${this.roomId}`); }
  rename(name) { return this.request('PATCH', `/v1/rooms/${this.roomId}/members/me`, { name }); }
  settings(patch) { return this.request('PATCH', `/v1/rooms/${this.roomId}`, patch, { host: true }); }
  get inviteUrl() { return `${this.base.replace(/api\.php$/, 'index.php')}?room=${this.roomId}`; }

  // ---- messages ----

  async send(text, { mediaTime = null, itemId = null } = {}) {
    const id = `sdk_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
    const t = mediaTime ?? (this.stateCache ? this.expectedPosition() : undefined);
    return this.request('POST', `/v1/rooms/${this.roomId}/messages`, { id, text, mediaTime: t, itemId: itemId ?? this.playlistCache?.current ?? undefined });
  }
  messages({ since = null, limit = 100 } = {}) {
    const q = new URLSearchParams({ limit: String(limit) });
    if (since !== null) q.set('since', String(since));
    return this.request('GET', `/v1/rooms/${this.roomId}/messages?${q}`);
  }

  // ---- playlist ----

  playlist() { return this.request('GET', `/v1/rooms/${this.roomId}/playlist`); }
  add(url) { return this.request('POST', `/v1/rooms/${this.roomId}/playlist`, { url }); }
  importIds(videoIds, listId = null) { return this.request('POST', `/v1/rooms/${this.roomId}/playlist/import`, { videoIds, listId: listId || undefined }); }
  jump(itemId) { return this.request('PATCH', `/v1/rooms/${this.roomId}/playlist`, { current: itemId }); }
  reorder(order) { return this.request('PATCH', `/v1/rooms/${this.roomId}/playlist`, { order }, { host: true }); }
  remove(itemId) { return this.request('DELETE', `/v1/rooms/${this.roomId}/playlist/${itemId}`, null, { host: true }); }
  reportItem(itemId, status, error = '') { return this.request('PATCH', `/v1/rooms/${this.roomId}/playlist`, { status: { itemId, status, error } }); }
  resolve(url) { return this.request('GET', `/v1/resolve?url=${encodeURIComponent(url)}`, null, { auth: false }); }

  // ---- playback ----

  state() { return this.request('GET', `/v1/rooms/${this.roomId}/state`); }
  async setState(patch) {
    try {
      const data = await this.request('PUT', `/v1/rooms/${this.roomId}/state`, { state: { baseRev: this.stateCache?.rev ?? 0, ...patch } });
      this.stateCache = data.state;
      return data.state;
    } catch (err) {
      if (err.code === 'stale' && err.body?.state) { this.stateCache = err.body.state; return this.setState(patch); }
      throw err;
    }
  }
  play(mediaTime = null) { return this.setState({ playing: true, mediaTime: mediaTime ?? this.expectedPosition() }); }
  pause(mediaTime = null) { return this.setState({ playing: false, mediaTime: mediaTime ?? this.expectedPosition() }); }
  seek(mediaTime) { return this.setState({ mediaTime, playing: this.stateCache?.playing ?? false }); }
  rate(rate) { return this.setState({ rate, mediaTime: this.expectedPosition(), playing: this.stateCache?.playing ?? false }); }
  expectedPosition(state = this.stateCache) {
    if (!state) return 0;
    if (!state.playing) return state.mediaTime;
    return state.mediaTime + ((Date.now() + this.offset - state.at) / 1000) * (state.rate || 1);
  }

  // ---- webhooks (host) ----

  webhooks() { return this.request('GET', `/v1/rooms/${this.roomId}/webhooks`, null, { host: true }); }
  addWebhook(url, events = []) { return this.request('POST', `/v1/rooms/${this.roomId}/webhooks`, { url, events }, { host: true }); }
  removeWebhook(id) { return this.request('DELETE', `/v1/rooms/${this.roomId}/webhooks/${id}`, null, { host: true }); }

  // ---- events ----

  on(event, fn) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event).add(fn);
    return () => this.handlers.get(event)?.delete(fn);
  }
  emit(event, payload) { this.handlers.get(event)?.forEach((fn) => { try { fn(payload); } catch (err) { this.emit('error', err); } }); }

  /** Starts receiving events. mode: 'auto' (SSE if EventSource exists), 'sse', 'poll'. Returns a stop function. */
  subscribe({ mode = 'auto', intervalMs = 1000 } = {}) {
    const useSse = mode === 'sse' || (mode === 'auto' && typeof EventSource !== 'undefined' && this.canUseEventSource());
    return useSse ? this.subscribeSse() : this.subscribePoll(intervalMs);
  }

  canUseEventSource() {
    // EventSource cannot set headers; the server also accepts the member id as a query
    // parameter for this one endpoint, so browsers can use it. Node falls back to polling.
    return true;
  }

  subscribeSse() {
    let es = null;
    let stopped = false;
    const open = () => {
      if (stopped) return;
      const q = new URLSearchParams({ memberId: this.memberId, since: String(this.cursors.since), prev: String(this.cursors.prev), srev: String(this.cursors.srev) });
      es = new EventSource(`${this.base}/v1/rooms/${this.roomId}/events?${q}`);
      es.addEventListener('message', (e) => this.handleEvent('message', JSON.parse(e.data)));
      es.addEventListener('state', (e) => this.handleEvent('state', JSON.parse(e.data)));
      es.addEventListener('playlist', (e) => this.handleEvent('playlist', JSON.parse(e.data)));
      es.addEventListener('members', (e) => this.handleEvent('members', JSON.parse(e.data)));
      es.addEventListener('ping', (e) => this.handleEvent('ping', JSON.parse(e.data)));
      es.addEventListener('end', () => { es.close(); setTimeout(open, 250); });
      es.addEventListener('error', (e) => { this.emit('status', { status: 'reconnecting' }); });
      es.onopen = () => this.emit('status', { status: 'live', transport: 'sse' });
    };
    open();
    return () => { stopped = true; es?.close(); };
  }

  subscribePoll(intervalMs) {
    let stopped = false;
    let failures = 0;
    const tick = async () => {
      if (stopped) return;
      try {
        const q = new URLSearchParams({ since: String(this.cursors.since), prev: String(this.cursors.prev), srev: String(this.cursors.srev) });
        const data = await this.request('GET', `/v1/rooms/${this.roomId}/sync?${q}`);
        failures = 0;
        (data.messages || []).forEach((m) => this.handleEvent('message', m));
        if (data.state) this.handleEvent('state', data.state);
        if (data.playlist) this.handleEvent('playlist', data.playlist);
        this.handleEvent('members', { members: data.members, actingHostId: data.actingHostId });
        this.emit('status', { status: 'live', transport: 'poll' });
      } catch (err) {
        failures = Math.min(failures + 1, 6);
        this.emit('status', { status: 'reconnecting', error: err });
        if (err.code === 'not_found') { stopped = true; this.emit('lost', err); return; }
      }
      if (!stopped) setTimeout(tick, failures ? Math.min(15000, intervalMs * 2 ** failures) : intervalMs);
    };
    tick();
    return () => { stopped = true; };
  }

  handleEvent(event, payload) {
    if (event === 'message') { this.cursors.since = Math.max(this.cursors.since, payload.seq || 0); }
    if (event === 'state') { this.cursors.srev = payload.rev; this.stateCache = payload; }
    if (event === 'playlist') { this.cursors.prev = payload.rev; this.playlistCache = payload; }
    if (event === 'members') { this.members = payload.members || []; }
    this.emit(event, payload);
  }

  // ---- transport ----

  absorb(data) {
    if (data.serverTime) this.offset = data.serverTime - Date.now();
    if (data.playlist) { this.playlistCache = data.playlist; this.cursors.prev = data.playlist.rev; }
    if (data.state) { this.stateCache = data.state; this.cursors.srev = data.state.rev; }
    if (data.since) this.cursors.since = data.since;
    if (data.room?.members) this.members = data.room.members;
  }

  async request(method, path, body = null, { auth = true, host = false, timeoutMs = 10000 } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== null) headers['Content-Type'] = 'application/json';
    if (auth && this.memberId) headers.Authorization = `Bearer ${this.memberId}`;
    if ((host || this.hostToken) && this.hostToken) headers['X-Host-Token'] = this.hostToken;
    if (this.apiKey) headers['X-Api-Key'] = this.apiKey;
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    let response;
    try {
      response = await this.fetch(`${this.base}${path}`, { method, headers, body: body === null ? undefined : JSON.stringify(body), signal: controller?.signal });
    } catch (err) {
      if (timer) clearTimeout(timer);
      throw new WatchRoomError(err?.name === 'AbortError' ? 'Timed out.' : 'No connection.', err?.name === 'AbortError' ? 'timeout' : 'network', 0, null);
    }
    if (timer) clearTimeout(timer);
    let data = null;
    try { data = await response.json(); } catch (_err) { data = null; }
    if (!response.ok) throw new WatchRoomError(data?.error || `HTTP ${response.status}`, data?.code || 'http_error', response.status, data);
    if (data && data.serverTime) this.offset = data.serverTime - Date.now();
    if (data && data.state) { this.stateCache = data.state; this.cursors.srev = Math.max(this.cursors.srev, data.state.rev); }
    if (data && data.playlist) { this.playlistCache = data.playlist; this.cursors.prev = Math.max(this.cursors.prev, data.playlist.rev); }
    return data;
  }
}

export default WatchRoomClient;
