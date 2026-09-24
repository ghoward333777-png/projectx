import { bus } from './bus.js';
import { readYouTubePlaylist } from './player/youtube.js';

// The playlist rail and everything that decides what plays next. The server owns the
// list; this controller renders it, sends changes, and turns failures into "skip".
export class PlaylistController {
  constructor({ chat, listEl, form, input, note, health }) {
    this.chat = chat;
    this.listEl = listEl;
    this.form = form;
    this.input = input;
    this.note = note;
    this.health = health;
    this.playlist = { rev: 0, items: [], current: null };
    this.loadedId = null;
    bus.on('playlist:update', (p) => this.receive(p));
    bus.on('playlist:next', () => this.step(1));
    bus.on('playlist:previous', () => this.step(-1));
    this.form.addEventListener('submit', (event) => { event.preventDefault(); this.add(this.input.value); });
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
    this.playlist = playlist;
    this.render();
    if (playlist.current !== this.loadedId) {
      this.loadedId = playlist.current;
      bus.emit('playlist:current', this.current);
    }
  }

  canControl() {
    return this.chat.isActingHost || this.chat.isHost || !!this.chat.room?.guestsControl;
  }

  nextPlayable(from = this.playlist.current, direction = 1) {
    const items = this.playlist.items;
    const index = items.findIndex((i) => i.id === from);
    for (let i = index + direction; i >= 0 && i < items.length; i += direction) {
      if (items[i].status !== 'error') return items[i];
    }
    return null;
  }

  async step(direction) {
    const target = this.nextPlayable(this.playlist.current, direction);
    if (target) await this.jump(target.id);
  }

  async jump(id) {
    if (!this.canControl()) { this.say('Only the host can change what is playing.'); return false; }
    try {
      await this.chat.call('playlist.set', { current: id });
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
      const title = document.createElement('span');
      title.className = 'pl__title';
      title.textContent = item.title;
      const kind = document.createElement('span');
      kind.className = 'pl__kind';
      kind.textContent = item.kind === 'youtube' ? 'YouTube' : 'file';
      btn.append(num, title, kind);
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
  }
}
