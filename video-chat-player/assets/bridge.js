import { bus } from './bus.js';

// Embed bridge: when the player runs inside an iframe, the host page can drive it with
// postMessage commands and receive its events. Only origins listed in the deployment's
// WATCHROOM_CORS_ORIGINS (passed as data-embed-origins) are answered; same-origin always is.
export function installBridge({ root, player, chat, playlist, stage, controls, idle, requestPlay }) {
  if (window.parent === window) return;
  const allowed = (root.dataset.embedOrigins || '').split(',').map((s) => s.trim()).filter(Boolean);
  const isAllowed = (origin) => origin === location.origin || allowed.includes(origin);
  let parentOrigin = null;
  const post = (event, payload) => { if (parentOrigin) window.parent.postMessage({ type: 'watchroom:event', event, payload }, parentOrigin); };

  const commands = {
    play: () => requestPlay(),
    pause: () => player.pause(),
    toggle: () => (player.isPlaying() ? player.pause() : requestPlay()),
    seek: ({ seconds }) => player.seek(Number(seconds) || 0),
    volume: ({ value }) => controls.setVolume(Number(value)),
    mute: ({ muted }) => controls.setMuted(muted !== false),
    fullscreen: ({ on }) => (on === false ? stage.exitFullscreen() : stage.enterFullscreen()),
    chat: ({ on }) => controls.toggleChat(on !== false),
    send: ({ text }) => chat.send(String(text || '')),
    add: ({ url }) => playlist.add(String(url || '')),
    jump: ({ itemId }) => playlist.jump(String(itemId || '')),
    repeat: ({ mode }) => playlist.setRepeat(mode),
    shuffle: ({ on }) => playlist.setShuffle(on !== false),
    next: () => bus.emit('playlist:next'),
    previous: () => bus.emit('playlist:previous'),
    reveal: () => idle.activity(),
    snapshot: () => ({
      room: chat.room?.id || null, memberId: chat.memberId, isHost: chat.isHost, members: chat.members,
      state: { playing: player.isPlaying(), time: player.currentTime(), duration: player.duration(), item: playlist.current, fullscreen: stage.isFullscreen(), engine: player.kind, machine: window.__watchRoom?.machine?.state },
      playlist: playlist.playlist,
    }),
  };

  window.addEventListener('message', async (event) => {
    const data = event.data;
    if (!data || data.type !== 'watchroom:command' || !isAllowed(event.origin)) return;
    parentOrigin = event.origin;
    const fn = commands[data.command];
    const reply = (result, error) => window.parent.postMessage({ type: 'watchroom:reply', id: data.id, result, error }, event.origin);
    if (!fn) { reply(null, `Unknown command "${data.command}"`); return; }
    try { reply(await fn(data.args || {}) ?? null, null); } catch (err) { reply(null, err?.message || String(err)); }
  });

  player.on('play', () => post('play', { time: player.currentTime() }));
  player.on('pause', () => post('pause', { time: player.currentTime() }));
  player.on('ended', () => post('ended', { item: playlist.current }));
  player.on('seeked', (t) => post('seeked', { time: t }));
  player.on('error', (message) => post('error', { message }));
  let lastWhole = -1;
  player.on('time', (t) => { const w = Math.floor(t); if (w !== lastWhole) { lastWhole = w; post('time', { time: t, duration: player.duration() }); } });
  bus.on('chat:messages', (messages) => messages.forEach((m) => post('message', m)));
  bus.on('playlist:update', (p) => post('playlist', p));
  bus.on('playlist:current', (item) => post('item', item));
  bus.on('room:update', ({ room, members }) => post('members', { room: room.id, members }));
  bus.on('stage:fullscreen', (on) => post('fullscreen', { on }));
  bus.on('idle:state', (state) => post('overlay', { state }));
  window.addEventListener('load', () => { window.parent.postMessage({ type: 'watchroom:event', event: 'ready', payload: {} }, '*'); });
}
