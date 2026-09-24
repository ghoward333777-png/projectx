// Steps 4–5 check: adding items, auto-advance with the "Up next" card, a broken file that
// is retried then skipped, a YouTube item whose failure is reported and skipped, and a
// guest who cannot reorder. Runs anywhere: YouTube itself may be blocked here, and that
// blocked path is exactly what the fallback must survive.
import { base, ok, near, sleep, launch, openViewer, wr, waitState, finish } from './_harness.mjs';

const browser = await launch();
const host = await openViewer(browser, `${base}index.php?src=media%2Ftest-16x9.webm`, 'Host');
await waitState(host.page, ['playing']);
const url = host.page.url();

// Record every item the stage loads, so short clips that advance quickly are still observed.
await wr(host.page, () => { window.__seen = [window.__watchRoom.item?.title]; new MutationObserver(() => window.__seen.push(document.getElementById('rail-label').textContent)).observe(document.getElementById('rail-label'), { childList: true, characterData: true, subtree: true }); });
const add = async (page, value) => { await page.fill('#pl-url', value); await page.click('#pl-form button'); await sleep(1500); };
await add(host.page, 'media/test-4x3.webm');
let items = await wr(host.page, () => window.__watchRoom.playlist.playlist.items.map((i) => i.title));
ok(items.length === 2 && items[1] === 'test-4x3.webm', `local file added to the playlist (${items.join(' → ')})`);
await add(host.page, 'not a link at all');
ok(/YouTube link|https link/.test(await wr(host.page, () => document.getElementById('pl-note').textContent)), 'garbage input is refused with a plain explanation');
await add(host.page, 'https://example.com/missing-video.mp4');
items = await wr(host.page, () => window.__watchRoom.playlist.playlist.items.map((i) => i.title));
ok(items.length === 3, `unreachable https file is accepted as an item (${items[2]}) and judged when played`);

// Auto-advance: the 4 s clip ends → Up next card → second clip plays.
await host.page.waitForFunction(() => document.querySelector('[data-card="upnext"]'), null, { timeout: 15000 }).catch(() => {});
ok(await wr(host.page, () => !!document.querySelector('[data-card="upnext"]')), '"Up next" card appears when the clip ends');
await host.page.waitForFunction(() => window.__seen.includes('test-4x3.webm'), null, { timeout: 15000 }).catch(() => {});
await host.page.waitForFunction(() => window.__watchRoom.item?.title !== 'test-4x3.webm' || window.__watchRoom.state === 'playing', null, { timeout: 15000 }).catch(() => {});
const second = await wr(host.page, () => ({ seen: window.__seen, title: window.__watchRoom.item?.title, state: window.__watchRoom.state, rect: window.__watchRoom.stage.contentRect() }));
ok(second.seen.includes('test-4x3.webm'), `advanced to the second clip automatically (loaded: ${second.seen.join(' → ')})`);
if (second.title === 'test-4x3.webm') ok(near(second.rect.width / second.rect.height, 4 / 3, 0.02), 'content rect switched to 4:3 for the new clip');

// The broken file: retried once, then marked and skipped (nothing after it → end card).
await host.page.waitForFunction(() => window.__watchRoom.playlist.playlist.items.some((i) => i.status === 'error'), null, { timeout: 40000 }).catch(() => {});
const broken = await wr(host.page, () => window.__watchRoom.playlist.playlist.items.find((i) => i.status === 'error'));
ok(broken && /missing-video/.test(broken.title), `unplayable file is marked in the playlist for everyone (${broken?.error})`);
ok(await wr(host.page, () => !!document.querySelector('[data-card="error"], [data-card="end"], [data-card="upnext"]')), 'a card explains what happened instead of a black frame');

// YouTube: add a video; whether YouTube plays here or is blocked, the app must end in a defined state.
await add(host.page, 'https://youtu.be/qqwhjSzFJqY?si=q1wNGoJplwMWRINb');
const yt = await wr(host.page, () => window.__watchRoom.playlist.playlist.items.find((i) => i.kind === 'youtube'));
ok(!!yt, `YouTube link becomes a playlist item (${yt?.title})`);
await wr(host.page, (id) => window.__watchRoom.playlist.jump(id), yt.id);
await host.page.waitForFunction(() => ['playing', 'error', 'paused'].includes(window.__watchRoom.state) && window.__watchRoom.item?.kind === 'youtube', null, { timeout: 40000 }).catch(() => {});
const ytResult = await wr(host.page, () => ({ state: window.__watchRoom.state, error: window.__watchRoom.error, health: window.__watchRoom.health.items.get('youtube'), shield: !!document.querySelector('.yt-shield'), iframe: !!document.querySelector('.yt-host iframe'), card: document.querySelector('.card')?.textContent || '' }));
if (ytResult.state === 'playing') {
  ok(ytResult.iframe && ytResult.shield, `YouTube plays here with the pointer shield in place`);
} else {
  ok(ytResult.state === 'error' && /YouTube|block|uploader|removed/i.test(ytResult.error || ytResult.card), `YouTube is refused here and the app says so plainly: "${(ytResult.error || '').slice(0, 80)}"`);
  ok(ytResult.health.status === 'fail' && ytResult.health.detail, 'health panel records the YouTube failure');
  ok(/Cannot play/.test(ytResult.card), 'viewer sees a card with the reason');
}

// Guest cannot reorder; host can remove.
const guest = await openViewer(browser, url, 'Guest');
await sleep(1500);
const guestReorder = await wr(guest.page, async () => { try { await window.__watchRoom.chat.call('playlist.set', { order: [] }); return 'allowed'; } catch (e) { return e.code; } });
ok(guestReorder === 'forbidden', `guest reorder is refused (${guestReorder})`);
const removed = await wr(host.page, async (id) => { await window.__watchRoom.chat.call('playlist.set', { remove: id }); return window.__watchRoom.playlist.playlist.items.length; }, broken.id);
ok(removed === 3, `host removed the broken item (${removed} left)`);
await guest.page.waitForFunction((n) => window.__watchRoom.playlist.playlist.items.length === n, removed, { timeout: 6000 }).catch(() => {});
ok((await wr(guest.page, () => window.__watchRoom.playlist.playlist.items.length)) === removed, 'guest sees the updated playlist');

await browser.close();
finish('playlist');
