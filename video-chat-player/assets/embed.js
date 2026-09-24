// Host-page helper: puts the Watch Room player in an iframe and gives you a promise-based
// handle to drive it. Plain script (no module) so it works from any page:
//
//   <script src="https://example.com/video-chat-player/assets/embed.js"></script>
//   <script>
//     const room = WatchRoom.embed(document.getElementById('box'), { base: 'https://example.com/video-chat-player/', room: 'quiet-otter-41', name: 'Sam' });
//     room.on('message', (m) => console.log(m.name, m.text));
//     await room.command('play');
//   </script>
//
// The deployment must list your page's origin in WATCHROOM_CORS_ORIGINS, or the player ignores commands.
(function (global) {
  function embed(container, { base, room = null, name = null, src = null, autoplay = true, compact = true, width = '100%', aspect = '16 / 9' } = {}) {
    const url = new URL('index.php', new URL(base.endsWith('/') ? base : base + '/', document.baseURI));
    if (room) url.searchParams.set('room', room);
    if (name) url.searchParams.set('name', name);
    if (src) url.searchParams.set('src', src);
    if (compact) url.searchParams.set('embed', '1');
    const iframe = document.createElement('iframe');
    iframe.src = url.toString();
    iframe.allow = 'autoplay; fullscreen; clipboard-write';
    iframe.setAttribute('allowfullscreen', '');
    iframe.style.cssText = `border:0;width:${width};aspect-ratio:${aspect};display:block;background:#000;`;
    container.appendChild(iframe);
    const origin = url.origin;
    const handlers = new Map();
    const pending = new Map();
    let seq = 0;
    global.addEventListener('message', (event) => {
      if (event.source !== iframe.contentWindow || event.origin !== origin) return;
      const data = event.data || {};
      if (data.type === 'watchroom:event') { (handlers.get(data.event) || []).forEach((fn) => fn(data.payload)); (handlers.get('*') || []).forEach((fn) => fn(data.event, data.payload)); }
      if (data.type === 'watchroom:reply' && pending.has(data.id)) { const { resolve, reject } = pending.get(data.id); pending.delete(data.id); data.error ? reject(new Error(data.error)) : resolve(data.result); }
    });
    const handle = {
      iframe,
      on(event, fn) { if (!handlers.has(event)) handlers.set(event, []); handlers.get(event).push(fn); return () => handlers.set(event, handlers.get(event).filter((f) => f !== fn)); },
      command(command, args = {}) {
        return new Promise((resolve, reject) => {
          const id = ++seq;
          pending.set(id, { resolve, reject });
          iframe.contentWindow.postMessage({ type: 'watchroom:command', id, command, args }, origin);
          setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error(`No answer to "${command}" (is this origin allowed?)`)); } }, 5000);
        });
      },
      play: () => handle.command('play'), pause: () => handle.command('pause'), seek: (seconds) => handle.command('seek', { seconds }),
      send: (text) => handle.command('send', { text }), add: (url) => handle.command('add', { url }), snapshot: () => handle.command('snapshot'),
      fullscreen: (on = true) => handle.command('fullscreen', { on }), destroy: () => iframe.remove(),
    };
    if (!autoplay) handle.on('ready', () => handle.command('pause').catch(() => {}));
    return handle;
  }
  global.WatchRoom = Object.assign(global.WatchRoom || {}, { embed });
})(window);
