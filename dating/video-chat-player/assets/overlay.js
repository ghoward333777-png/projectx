import { bus } from './bus.js';
import { formatTime } from './controls.js';

const MAX_RENDERED = 200;
const PEEK_MS = 4000;

// Renders the message list inside the overlay and owns the peek behaviour: a new message
// from someone else while the overlay is hidden shows on its own for four seconds.
export class Overlay {
  constructor({ stage, idle, list, composer, input, seek, myId, controls }) {
    this.stage = stage;
    this.idle = idle;
    this.list = list;
    this.composer = composer;
    this.input = input;
    this.seek = seek;
    this.myId = myId;
    this.controls = controls;
    this.rows = new Map();
    this.unread = 0;
    this.peekTimer = 0;
    this.unreadBadge = document.getElementById('chat-unread');

    bus.on('chat:history', (messages) => { this.list.replaceChildren(); this.rows.clear(); messages.forEach((m) => this.render(m, { silent: true })); this.scrollToEnd(); });
    bus.on('chat:messages', (messages) => messages.forEach((m) => this.render(m)));
    bus.on('chat:pending', (m) => this.render(m, { silent: true }));
    bus.on('chat:sent', ({ id, message }) => { this.render({ ...message, pending: false }, { silent: true, replaceId: id }); });
    bus.on('chat:failed', ({ id, reason, retryable }) => this.markFailed(id, reason, retryable));
    bus.on('idle:state', (state) => { if (state !== 'hidden') this.endPeek(); });
    bus.on('chat:enabled', (on) => { if (on) this.clearUnread(); });
    this.list.addEventListener('click', (event) => {
      const stamp = event.target.closest('[data-seek]');
      if (stamp) { event.preventDefault(); this.seek(Number(stamp.dataset.seek)); }
      const retry = event.target.closest('[data-retry]');
      if (retry) { event.preventDefault(); bus.emit('chat:retry', retry.dataset.retry); }
    });
  }

  systemLine(text) {
    this.render({ id: `local_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`, kind: 'system', text, sentAt: Date.now(), name: '', colour: '' }, { silent: true });
  }

  render(message, { silent = false, replaceId = null } = {}) {
    const key = replaceId || message.id;
    let row = this.rows.get(key);
    const fresh = !row;
    if (!row) {
      row = document.createElement('div');
      this.list.appendChild(row);
    }
    if (replaceId && replaceId !== message.id) { this.rows.delete(replaceId); }
    this.rows.set(message.id, row);
    row.className = message.kind === 'system' ? 'msg msg--system' : `msg${message.memberId === this.myId() ? ' msg--mine' : ''}${message.pending ? ' msg--pending' : ''}`;
    row.dataset.id = message.id;
    row.replaceChildren();
    if (message.kind === 'system') {
      const p = document.createElement('p');
      p.className = 'msg__text';
      p.textContent = message.text;
      row.appendChild(p);
    } else {
      const head = document.createElement('div');
      head.className = 'msg__head';
      const dot = document.createElement('span');
      dot.className = 'msg__dot';
      dot.style.background = message.colour || '#fff';
      const name = document.createElement('span');
      name.className = 'msg__name';
      name.textContent = message.memberId === this.myId() ? 'You' : (message.name || '?');
      head.append(dot, name);
      if (Number.isFinite(message.mediaTime)) {
        const stamp = document.createElement('a');
        stamp.className = 'msg__stamp';
        stamp.href = '#';
        stamp.dataset.seek = String(message.mediaTime);
        stamp.title = 'Jump to this moment';
        stamp.textContent = formatTime(message.mediaTime);
        head.appendChild(stamp);
      }
      const text = document.createElement('p');
      text.className = 'msg__text';
      text.textContent = message.text;
      row.append(head, text);
      if (message.pending) {
        const s = document.createElement('span');
        s.className = 'msg__state';
        s.textContent = 'sending…';
        row.appendChild(s);
      }
    }
    while (this.list.children.length > MAX_RENDERED) {
      const first = this.list.firstElementChild;
      this.rows.delete(first.dataset.id);
      first.remove();
    }
    this.scrollToEnd();
    if (fresh && !silent && message.memberId !== this.myId()) this.arrived(message);
  }

  markFailed(id, reason, retryable) {
    const row = this.rows.get(id);
    if (!row) return;
    row.classList.remove('msg--pending');
    row.classList.add('msg--failed');
    let s = row.querySelector('.msg__state');
    if (!s) { s = document.createElement('span'); s.className = 'msg__state'; row.appendChild(s); }
    s.replaceChildren();
    s.append(`not sent: ${reason} `);
    if (retryable) {
      const a = document.createElement('a');
      a.href = '#';
      a.dataset.retry = id;
      a.textContent = 'retry';
      s.appendChild(a);
    }
  }

  arrived(message) {
    if (!this.controls.chatEnabled) {
      this.unread += 1;
      this.updateUnread();
      return;
    }
    if (this.idle.state === 'hidden' || this.idle.state === 'fading') this.peek();
  }

  peek() {
    this.stage.root.classList.add('is-peek');
    clearTimeout(this.peekTimer);
    this.peekTimer = setTimeout(() => this.endPeek(), PEEK_MS);
  }

  endPeek() {
    clearTimeout(this.peekTimer);
    this.stage.root.classList.remove('is-peek');
  }

  updateUnread() {
    if (!this.unreadBadge) return;
    this.unreadBadge.textContent = this.unread > 0 ? `${this.unread} new · press C` : 'chat off · press C';
  }

  clearUnread() { this.unread = 0; this.updateUnread(); }

  scrollToEnd() { this.list.scrollTop = this.list.scrollHeight; }
}
