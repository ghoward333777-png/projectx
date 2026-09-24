// Playlist engine check: repeat-all wraps, repeat-one replays, shuffle keeps everyone on one
// order, multi-link paste, local playlists saved in the browser, YouTube playlist links as
// single items, and the player state machine. Run against a server with the 4 s test clips.
import { base, ok, sleep, launch, openViewer, wr, waitState, finish } from './_harness.mjs';

const browser = await launch();
const host = await openViewer(browser, `${base}index.php?src=media%2Ftest-16x9.webm`, 'Host');
await waitState(host.page, ['playing']);
await wr(host.page, () => { window.__seen = []; new MutationObserver(() => window.__seen.push(document.getElementById('rail-label').textContent)).observe(document.getElementById('rail-label'), { childList: true, characterData: true, subtree: true }); });

// Multi-link paste adds several items at once.
await host.page.fill('#pl-url', 'media/test-4x3.webm\nmedia/test-16x9.webm\nnot-a-link');
await host.page.click('#pl-form button');
await sleep(2500);
let titles = await wr(host.page, () => window.__watchRoom.playlist.playlist.items.map((i) => i.title));
ok(titles.length === 3, `pasting several links adds each one (${titles.join(', ')})`);
ok(/Added 2 of 3 \(1 not a link\)/.test(await wr(host.page, () => document.getElementById('pl-note').textContent)), 'the note says how many of the pasted links were accepted');

// Repeat all: after the last clip the first plays again.
await host.page.click('[data-mode="repeat"]'); // off → all
await sleep(800);
ok((await wr(host.page, () => window.__watchRoom.playlist.playlist.repeat)) === 'all', 'repeat cycles to "all"');
const lastId = await wr(host.page, () => window.__watchRoom.playlist.playlist.items[2].id);
await wr(host.page, (id) => window.__watchRoom.playlist.jump(id), lastId);
await host.page.waitForFunction(() => window.__watchRoom.item?.id === window.__watchRoom.playlist.playlist.items[2].id && window.__watchRoom.state === 'playing', null, { timeout: 15000 }).catch(() => {});
await wr(host.page, () => { window.__seen = []; });
await host.page.waitForFunction(() => window.__watchRoom.playlist.playlist.current === window.__watchRoom.playlist.playlist.items[0].id, null, { timeout: 20000 }).catch(() => {});
ok((await wr(host.page, () => window.__watchRoom.playlist.playlist.current === window.__watchRoom.playlist.playlist.items[0].id)), 'repeat-all wraps from the last clip to the first');

// Repeat one: the same clip replays instead of advancing.
await host.page.click('[data-mode="repeat"]'); // all → one
await sleep(800);
ok((await wr(host.page, () => window.__watchRoom.playlist.playlist.repeat)) === 'one', 'repeat cycles to "one"');
const firstId = await wr(host.page, () => window.__watchRoom.playlist.playlist.items[0].id);
await wr(host.page, (id) => window.__watchRoom.playlist.jump(id), firstId);
// Wait for a fresh start of that clip (position near zero), so the ending we observe is this cycle's.
await host.page.waitForFunction((id) => window.__watchRoom.item?.id === id && window.__watchRoom.state === 'playing' && window.__watchRoom.player.currentTime() < 1.5, firstId, { timeout: 20000 }).catch(() => {});
const before = await wr(host.page, () => window.__watchRoom.playlist.playlist.current);
// Record what the app decides at the moment this clip ends.
await wr(host.page, () => { window.__endedNext = null; window.__watchRoom.player.on('ended', () => { window.__endedNext = { repeat: window.__watchRoom.playlist.playlist.repeat, current: window.__watchRoom.playlist.playlist.current, next: window.__watchRoom.playlist.nextId() }; }); });
await host.page.waitForFunction(() => window.__endedNext !== null, null, { timeout: 15000 }).catch(() => {});
const decided = await wr(host.page, () => window.__endedNext);
ok(decided && decided.repeat === 'one' && decided.current === before && decided.next === before, `repeat-one queues the same clip again (repeat=${decided?.repeat}, current unchanged: ${decided?.current === before}, next is current: ${decided?.next === before})`);
await host.page.click('[data-mode="repeat"]'); // one → off
await sleep(600);

// Shuffle: a stored order everyone shares, starting with the current item.
await host.page.click('[data-mode="shuffle"]');
await sleep(800);
const shuffled = await wr(host.page, () => ({ on: window.__watchRoom.playlist.playlist.shuffle, order: window.__watchRoom.playlist.playlist.order, current: window.__watchRoom.playlist.playlist.current, n: window.__watchRoom.playlist.playlist.items.length }));
ok(shuffled.on && shuffled.order.length === shuffled.n && shuffled.order[0] === shuffled.current, 'shuffle stores a full order that starts with the current item');
const guest = await openViewer(browser, host.page.url(), 'Guest');
await sleep(1500);
const guestOrder = await wr(guest.page, () => window.__watchRoom.playlist.playlist.order);
ok(JSON.stringify(guestOrder) === JSON.stringify(shuffled.order), 'the guest sees the same shuffle order');
const guestSaw = await wr(guest.page, () => document.querySelector('[data-mode="shuffle"]').textContent);
ok(/Shuffle: on/.test(guestSaw), 'the guest\'s rail shows shuffle on');
await host.page.click('[data-mode="shuffle"]');
await sleep(600);

// YouTube playlist link becomes one item with a thumbnail and the list label.
await host.page.fill('#pl-url', 'https://www.youtube.com/playlist?list=PL9oaxTKWGJ7ONeR1-1cMkCAGAl-gozWij');
await host.page.click('#pl-form button');
await sleep(2000);
const list = await wr(host.page, () => { const i = window.__watchRoom.playlist.playlist.items.find((x) => x.kind === 'youtube-playlist'); return i ? { title: i.title, src: i.src, label: [...document.querySelectorAll('.pl__kind')].map((e) => e.textContent).includes('YT list') } : null; });
ok(list && list.src === 'PL9oaxTKWGJ7ONeR1-1cMkCAGAl-gozWij' && list.label, `a YouTube playlist link is one item (${list?.title})`);

// Local playlists: save, list, copy links, load into the room.
await host.page.click('#pl-saved summary');
await host.page.fill('#pl-save-name', 'Friday');
await host.page.click('[data-save]');
await sleep(300);
const saved = await wr(host.page, () => JSON.parse(localStorage.getItem('watchroom.playlists') || '{}'));
ok(saved.Friday && saved.Friday.urls.length === 4 && saved.Friday.urls.some((u) => u.includes('playlist?list=')), `playlist saved in the browser (${saved.Friday?.urls.length} links)`);
ok((await wr(host.page, () => document.querySelectorAll('#pl-saved-list .pl__saved').length)) === 1, 'saved playlist is listed');
await host.page.click('[data-copy]');
await sleep(300);
ok((await wr(host.page, () => document.getElementById('pl-export').value.split('\n').length)) === 4, 'export box holds one link per line');
const beforeLoad = await wr(host.page, () => window.__watchRoom.playlist.playlist.items.length);
await host.page.click('[data-load="Friday"]');
await sleep(4000);
const afterLoad = await wr(host.page, () => window.__watchRoom.playlist.playlist.items.length);
ok(afterLoad === beforeLoad + 3, `loading a saved playlist adds its distinct links (${beforeLoad} → ${afterLoad}; one duplicate link skipped)`);
await host.page.click('[data-delete="Friday"]');
ok((await wr(host.page, () => document.querySelectorAll('#pl-saved-list .pl__saved').length)) === 0, 'forgetting a saved playlist removes it');

// State machine: transitions were legal and the history reads sensibly.
const machine = await wr(host.page, () => ({ state: window.__watchRoom.machine.state, illegal: window.__watchRoom.machine.history.filter((h) => !h.legal).map((h) => `${h.from}>${h.to}`), seen: [...new Set(window.__watchRoom.machine.history.map((h) => h.to))] }));
ok(machine.illegal.length === 0, `no illegal state transitions (seen ${machine.seen.join(', ')}${machine.illegal.length ? '; illegal: ' + machine.illegal.join(' ') : ''})`);

await browser.close();
finish('modes');
