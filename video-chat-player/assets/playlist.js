import { bus } from './bus.js';
import { readYouTubePlaylist } from './player/youtube.js';

// The playlist rail and everything that decides what plays next. The server owns the
// list; this controller renders it, sends changes, and turns failures into "skip".
export class PlaylistController {
  constructor({ chat, listEl, form, input, note, health, modesEl, savedEl, player }) {
    this.chat = chat;
    this.listEl = listEl;
    this.form = form;
    this.input = input;
    this.note = note;
    this.health = health;
    this.modesEl = modesEl;
    this.savedEl = savedEl;
    this.player = player;
    this.playlist = { rev: 0, items: [], current: null, repeat: 'off', shuffle: false, order: [] };
    this.loadedId = null;
    this.inner = null;
    bus.on('playlist:update', (p) => this.receive(p));
    bus.on('playlist:next', () => this.step(1));
    bus.on('playlist:previous', () => this.step(-1));
    if (player) player.on('inner-playlist', (info) => { this.inner = info; this.render(); });
    this.form.addEventListener('submit', (event) => { event.preventDefault(); this.addMany(this.input.value); });
    this.input.addEventListener('paste', () => setTimeout(() => { if (/\s/.test(this.input.value.trim())) this.addMany(this.input.value); }, 0));
    if (this.modesEl) {
      this.modesEl.addEventListener('click', (event) => {
        const b = event.target.closest('[data-mode]');
        if (!b) return;
        if (b.dataset.mode === 'repeat') this.setRepeat({ off: 'all', all: 'one', one: 'off' }[this.playlist.repeat] || 'off');
        if (b.dataset.mode === 'shuffle') this.setShuffle(!this.playlist.shuffle);
      });
    }
    if (this.savedEl) this.savedEl.addEventListener('click', (event) => this.onSavedClick(event));
    this.listEl.addEventListener('click', (event) => {
      const jump = event.target.closest('[data-jump]');
      if (jump) { this.jump(jump.dataset.jump); return; }
      const remove = event.target.closest('[data-remove]');
      if (remove) this.remove(remove.dataset.remove);
    });
  }

  get current() { return this.find(this.playlist.current); }
  get currentId() { return this.playlist.current; }
  find(id) { return this.playlist.items.find((i) => i.id === id) || null; }

  receive(playlist) {
    this.playlist = { repeat: 'off', shuffle: false, order: playlist.items.map((i) => i.id), ...playlist };
    this.render();
    if (playlist.current !== this.loadedId) {
      this.loadedId = playlist.current;
      this.inner = null;
      bus.emit('playlist:current', this.current);
    }
  }

  /** Mirrors Playlist::nextId on the server: repeat-one, repeat-all wrap, shuffle order, skip errors. */
  nextId(from = this.playlist.current, direction = 1) {
    const order = this.playlist.order && this.playlist.order.length ? this.playlist.order : this.playlist.items.map((i) => i.id);
    if (!order.length) return null;
    const playable = (id) => { const it = this.find(id); return !!it && it.status !== 'error'; };
    if (this.playlist.repeat === 'one' && from && direction === 1 && playable(from)) return from;
    let index = from ? order.indexOf(from) : -1;
    const count = order.length;
    for (let step = 1; step <= count; step++) {
      let i = index + step * direction;
      if (i < 0 || i >= count) {
        if (this.playlist.repeat !== 'all' && !(direction === -1 && !from)) return null;
        i = ((i % count) + count) % count;
      }
      if (playable(order[i])) return order[i];
    }
    return null;
  }

  async setRepeat(mode) {
    if (!this.canControl()) { this.say('Only the host can change the repeat mode.'); return; }
    try { await this.chat.call('playlist.set', { repeat: mode }); this.say(`Repeat: ${mode}`); } catch (err) { this.say(err.message); }
  }

  async setShuffle(on) {
    if (!this.canControl()) { this.say('Only the host can change shuffle.'); return; }
    try { await this.chat.call('playlist.set', { shuffle: on }); this.say(on ? 'Shuffle on' : 'Shuffle off'); } catch (err) { this.say(err.message); }
  }

  canControl() {
    return this.chat.isActingHost || this.chat.isHost || !!this.chat.room?.guestsControl;
  }

  nextPlayable(from = this.playlist.current, direction = 1) {
    const id = this.nextId(from, direction);
    return id ? this.find(id) : null;
  }

  /** N/P: step inside a YouTube playlist item first, then across room items. */
  async step(direction) {
    const adapter = this.player?.current;
    if (adapter && adapter.caps?.innerPlaylist && this.current?.kind === 'youtube-playlist') {
      if (direction === 1 ? adapter.innerNext() : adapter.innerPrevious()) return;
    }
    const target = this.nextPlayable(this.playlist.current, direction);
    if (target) await this.jump(target.id);
    else this.say(direction === 1 ? 'End of the playlist.' : 'Start of the playlist.');
  }

  /** Splits pasted text into links and adds each one; blank and duplicate lines are ignored. */
  async addMany(text) {
    const tokens = String(text || '').split(/\s+/).map((u) => u.trim()).filter(Boolean);
    const looksLikeLink = (u) => /^(https?:\/\/|media\/|media\.php\?)/i.test(u) || /^[A-Za-z0-9_-]{11}$/.test(u);
    const urls = [...new Set(tokens.filter(looksLikeLink))];
    if (tokens.length <= 1 || urls.length <= 1) return this.add(String(text || '').trim());
    let added = 0;
    for (const url of urls) {
      try { const data = await this.chat.call('playlist.add', { url }); if (data.item) added++; } catch (err) { this.say(`${url.slice(0, 40)}…: ${err.message}`); }
    }
    const skipped = new Set(tokens).size - urls.length;
    this.say(`Added ${added} of ${new Set(tokens).size}${skipped ? ` (${skipped} not a link)` : ''}.`);
    this.input.value = '';
  }

  // ---- local playlists (this browser only) ----

  static savedPlaylists() {
    try { return JSON.parse(localStorage.getItem('watchroom.playlists') || '{}') || {}; } catch (_err) { return {}; }
  }

  static storePlaylists(all) {
    try { localStorage.setItem('watchroom.playlists', JSON.stringify(all)); return true; } catch (_err) { return false; }
  }

  saveLocal(name) {
    const urls = this.playlist.items.map((i) => (i.kind === 'youtube' ? `https://youtu.be/${i.src}` : i.kind === 'youtube-playlist' ? `https://www.youtube.com/playlist?list=${i.src}` : i.src));
    const all = PlaylistController.savedPlaylists();
    all[name] = { urls, savedAt: Date.now() };
    if (!PlaylistController.storePlaylists(all)) { this.say('This browser blocks storage; nothing saved.'); return; }
    this.say(`Saved "${name}" (${urls.length} links) in this browser.`);
    this.renderSaved();
  }

  async loadLocal(name) {
    const entry = PlaylistController.savedPlaylists()[name];
    if (!entry) return;
    await this.addMany(entry.urls.join('\n'));
  }

  deleteLocal(name) {
    const all = PlaylistController.savedPlaylists();
    delete all[name];
    PlaylistController.storePlaylists(all);
    this.renderSaved();
  }

  exportText() {
    return this.playlist.items.map((i) => (i.kind === 'youtube' ? `https://youtu.be/${i.src}` : i.kind === 'youtube-playlist' ? `https://www.youtube.com/playlist?list=${i.src}` : i.src)).join('\n');
  }

  onSavedClick(event) {
    const save = event.target.closest('[data-save]');
    if (save) { const name = (this.savedEl.querySelector('#pl-save-name')?.value || '').trim() || `Playlist ${new Date().toLocaleDateString()}`; this.saveLocal(name); return; }
    const load = event.target.closest('[data-load]');
    if (load) { this.loadLocal(load.dataset.load); return; }
    const del = event.target.closest('[data-delete]');
    if (del) { this.deleteLocal(del.dataset.delete); return; }
    const copy = event.target.closest('[data-copy]');
    if (copy) { navigator.clipboard?.writeText(this.exportText()).then(() => this.say('Links copied.'), () => this.say('Could not copy; select them from the box below.')); const box = this.savedEl.querySelector('#pl-export'); if (box) { box.value = this.exportText(); box.hidden = false; } }
  }

  renderSaved() {
    if (!this.savedEl) return;
    const list = this.savedEl.querySelector('#pl-saved-list');
    if (!list) return;
    const all = PlaylistController.savedPlaylists();
    const frag = document.createDocumentFragment();
    for (const [name, entry] of Object.entries(all)) {
      const li = document.createElement('li');
      li.className = 'pl__saved';
      const load = document.createElement('button');
      load.type = 'button'; load.className = 'pl__jump'; load.dataset.load = name; load.textContent = `${name} · ${entry.urls.length}`;
      const del = document.createElement('button');
      del.type = 'button'; del.className = 'pl__remove'; del.dataset.delete = name; del.setAttribute('aria-label', `Forget ${name}`); del.textContent = '×';
      li.append(load, del);
      frag.appendChild(li);
    }
    list.replaceChildren(frag);
  }

  async jump(id) {
    if (!this.canControl()) { this.say('Only the host can change what is playing.'); return false; }
    try {
      await this.chat.call('playlist.set', { current: id });
      bus.emit('playlist:jumped', id);
      return true;
    } catch (err) {
      this.say(err.message);
      return false;
    }
  }

  async add(url) {
    url = String(url || '').trim();
    if (!url) return;
    this.say('Adding…');
    try {
      const data = await this.chat.call('playlist.add', { url });
      if (data.needsImport) {
        this.say('Reading the YouTube playlist…');
        let ids;
        try {
          ids = await readYouTubePlaylist(data.list);
        } catch (err) {
          if (data.firstVideo) {
            this.say(`${err.message} Added the first video instead.`);
            await this.chat.call('playlist.add', { url: data.firstVideo });
            this.input.value = '';
            return;
          }
          throw err;
        }
        const imported = await this.chat.call('playlist.import', { videoIds: ids, listId: data.list });
        this.say(`Added ${imported.added} videos.`);
      } else {
        this.say(`Added ${data.item.title}.`);
      }
      this.input.value = '';
    } catch (err) {
      this.say(err.message);
    }
  }

  async remove(id) {
    try { await this.chat.call('playlist.set', { remove: id }); } catch (err) { this.say(err.message); }
  }

  /** Called by the app when the current item cannot play here. */
  async reportFailure(item, reason) {
    if (!item) return null;
    this.say(`${item.title}: ${reason}`);
    try { await this.chat.call('playlist.set', { status: { itemId: item.id, status: 'error', error: reason } }); } catch (_err) { /* offline: local skip only */ }
    return this.nextPlayable(item.id, 1);
  }

  say(text) {
    if (!this.note) return;
    this.note.textContent = text;
    clearTimeout(this._noteTimer);
    this._noteTimer = setTimeout(() => { if (this.note.textContent === text) this.note.textContent = ''; }, 6000);
  }

  render() {
    const frag = document.createDocumentFragment();
    const canControl = this.canControl();
    const isHost = this.chat.isHost || this.chat.isActingHost;
    this.playlist.items.forEach((item, index) => {
      const row = document.createElement('li');
      row.className = `pl__item${item.id === this.playlist.current ? ' pl__item--current' : ''}${item.status === 'error' ? ' pl__item--error' : ''}`;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pl__jump';
      btn.dataset.jump = item.id;
      btn.disabled = !canControl;
      btn.title = canControl ? 'Play this' : 'Only the host can change what is playing';
      const num = document.createElement('span');
      num.className = 'pl__num';
      num.textContent = item.id === this.playlist.current ? '▶' : String(index + 1);
      const thumb = document.createElement('span');
      thumb.className = 'pl__thumb';
      if (item.thumb) {
        const img = document.createElement('img');
        img.alt = '';
        img.loading = 'lazy';
        img.src = item.thumb;
        img.addEventListener('error', () => { img.remove(); thumb.textContent = '▶'; });
        thumb.appendChild(img);
      } else {
        thumb.textContent = '▶';
      }
      const title = document.createElement('span');
      title.className = 'pl__title';
      title.textContent = item.title;
      if (item.id === this.playlist.current && item.kind === 'youtube-playlist' && this.inner && this.inner.count) title.textContent += ` · ${this.inner.index + 1}/${this.inner.count}`;
      const kind = document.createElement('span');
      kind.className = 'pl__kind';
      kind.textContent = item.kind === 'youtube' ? 'YouTube' : item.kind === 'youtube-playlist' ? 'YT list' : 'file';
      btn.append(num, thumb, title, kind);
      row.appendChild(btn);
      if (item.status === 'error') {
        const err = document.createElement('span');
        err.className = 'pl__error';
        err.textContent = item.error || 'failed';
        row.appendChild(err);
      }
      if (isHost && this.playlist.items.length > 1) {
        const rm = document.createElement('button');
        rm.type = 'button';
        rm.className = 'pl__remove';
        rm.dataset.remove = item.id;
        rm.setAttribute('aria-label', `Remove ${item.title}`);
        rm.textContent = '×';
        row.appendChild(rm);
      }
      frag.appendChild(row);
    });
    this.listEl.replaceChildren(frag);
    if (this.modesEl) {
      const r = this.modesEl.querySelector('[data-mode="repeat"]');
      const sh = this.modesEl.querySelector('[data-mode="shuffle"]');
      if (r) { r.textContent = { off: 'Repeat: off', all: 'Repeat: all', one: 'Repeat: one' }[this.playlist.repeat] || 'Repeat: off'; r.setAttribute('aria-pressed', this.playlist.repeat !== 'off' ? 'true' : 'false'); r.disabled = !canControl; }
      if (sh) { sh.textContent = this.playlist.shuffle ? 'Shuffle: on' : 'Shuffle: off'; sh.setAttribute('aria-pressed', this.playlist.shuffle ? 'true' : 'false'); sh.disabled = !canControl; }
    }
    this.renderSaved();
  }
}
