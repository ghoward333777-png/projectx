// Drives the example host page. Kept as a file because the page's CSP allows no inline scripts.
(function () {
  const box = document.getElementById('box');
  const log = document.getElementById('log');
  const say = (line) => { log.textContent = `${new Date().toLocaleTimeString()}  ${line}\n` + log.textContent.split('\n').slice(0, 30).join('\n'); };
  const room = window.WatchRoom.embed(box, { base: './', room: box.dataset.room || null, name: 'Host page' });
  window.embeddedRoom = room;
  room.on('*', (event, payload) => {
    if (event === 'time') return;
    say(`${event} ${payload && typeof payload === 'object' ? JSON.stringify(payload).slice(0, 120) : ''}`);
  });
  room.on('ready', async () => { const s = await room.snapshot(); say(`ready · room ${s.room} · ${s.members.length} member(s)`); history.replaceState(null, '', `?room=${s.room}`); });
  const act = (id, fn) => document.getElementById(id).addEventListener('click', () => fn().catch((err) => say(`error: ${err.message}`)));
  act('b-play', () => room.play());
  act('b-pause', () => room.pause());
  act('b-back', async () => { const s = await room.snapshot(); return room.seek(Math.max(0, s.state.time - 10)); });
  act('b-fwd', async () => { const s = await room.snapshot(); return room.seek(s.state.time + 10); });
  act('b-chat', () => room.send('hello from the host page'));
  act('b-snap', async () => { say(JSON.stringify(await room.snapshot()).slice(0, 300)); });
})();
