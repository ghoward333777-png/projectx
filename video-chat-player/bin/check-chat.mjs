// Step 3 check: two viewers in one room, message round trip, media-time stamps that seek,
// peek while idle, rename, and recovery after the connection drops.
import { base, ok, near, sleep, launch, openViewer, wr, waitState, finish, failures } from './_harness.mjs';

const browser = await launch();
const ana = await openViewer(browser, `${base}index.php?src=media%2Ftest-16x9.webm`, 'Ana');
await wr(ana.page, () => { window.__watchRoom.player.el.loop = true; });
const url = ana.page.url();
ok(/[?&]room=[a-z]+-[a-z]+-\d\d/.test(url), `room created and put in the URL (${new URL(url).searchParams.get('room')})`);
await waitState(ana.page, ['playing']);
ok((await wr(ana.page, () => window.__watchRoom.state)) === 'playing', 'host is playing the requested clip');

const bob = await openViewer(browser, url, 'Bob');
await wr(bob.page, () => { window.__watchRoom.player.el.loop = true; });
await sleep(2500);
const bobSeesAna = await wr(bob.page, () => window.__watchRoom.chat.members.filter((m) => m.online).map((m) => m.name).sort());
ok(bobSeesAna.join(',') === 'Ana,Bob', `both members online (${bobSeesAna.join(', ')})`);

// Round trip Ana → Bob.
await wr(ana.page, () => window.__watchRoom.player.seek(2.5));
await sleep(300);
const t0 = Date.now();
await ana.page.keyboard.press('Enter');
await ana.page.keyboard.type('did you see that');
await ana.page.keyboard.press('Enter');
await bob.page.waitForFunction(() => [...document.querySelectorAll('.msg__text')].some((e) => e.textContent === 'did you see that'), null, { timeout: 6000 }).catch(() => {});
const rtt = Date.now() - t0;
const arrived = await wr(bob.page, () => [...document.querySelectorAll('.msg__text')].some((e) => e.textContent === 'did you see that'));
ok(arrived && rtt <= 3500, `message reached the other viewer in ${rtt} ms (≤ 3500 with 1 s polling)`);
const stamp = await wr(bob.page, () => { const s = [...document.querySelectorAll('.msg')].reverse().find((m) => m.textContent.includes('did you see that'))?.querySelector('.msg__stamp'); return s ? { text: s.textContent, seek: Number(s.dataset.seek) } : null; });
ok(stamp && near(stamp.seek, 2.5, 0.6), `message carries the media time (${stamp?.text}, ${stamp?.seek}s)`);
const ownRow = await wr(ana.page, () => { const m = [...document.querySelectorAll('.msg')].find((r) => r.textContent.includes('did you see that')); return { mine: m?.classList.contains('msg--mine'), pending: m?.classList.contains('msg--pending') }; });
ok(ownRow.mine && !ownRow.pending, 'own message renders right-aligned and reconciled (not pending)');

// Clicking the stamp seeks Bob.
await wr(bob.page, () => window.__watchRoom.player.seek(0.2));
await bob.page.mouse.move(640, 400); // reveal the overlay first, as a person would
await sleep(200);
await bob.page.click('.msg__stamp');
await sleep(400);
const bobTime = await wr(bob.page, () => window.__watchRoom.player.currentTime());
ok(near(bobTime, 2.5, 0.8), `clicking the stamp seeks to it (${bobTime.toFixed(2)} s)`);

// Peek: Bob idle, Ana sends → Bob's overlay peeks for 4 s at 85 %.
await bob.page.mouse.move(600, 300);
await wr(bob.page, () => window.__watchRoom.idle.hideNow());
await sleep(400);
ok((await wr(bob.page, () => window.__watchRoom.idle.state)) === 'hidden', 'Bob\'s overlay is hidden');
await ana.page.keyboard.press('Enter');
await ana.page.keyboard.type('peek at this');
await ana.page.keyboard.press('Enter');
await bob.page.waitForFunction(() => document.getElementById('stage').classList.contains('is-peek'), null, { timeout: 6000 }).catch(() => {});
const peek = await wr(bob.page, () => ({ peek: document.getElementById('stage').classList.contains('is-peek'), state: window.__watchRoom.idle.state, opacity: getComputedStyle(window.__watchRoom.stage.overlay).opacity, composer: getComputedStyle(document.getElementById('overlay-composer')).display }));
ok(peek.peek && peek.state === 'hidden' && Number(peek.opacity) > 0.8 && peek.composer === 'none', `new message peeks without opening the whole overlay (opacity ${peek.opacity}, composer ${peek.composer})`);
await sleep(4500);
ok(!(await wr(bob.page, () => document.getElementById('stage').classList.contains('is-peek'))), 'peek ends after 4 s');

// Chat off collects unread.
await bob.page.keyboard.press('c');
await ana.page.keyboard.press('Enter'); await ana.page.keyboard.type('while off'); await ana.page.keyboard.press('Enter');
await sleep(2500);
ok((await wr(bob.page, () => document.getElementById('chat-unread').textContent)).startsWith('1 new'), 'unread count shows while the chat is off');
await bob.page.keyboard.press('c');

// Rename.
await bob.page.fill('#room-name', 'Roberto');
await bob.page.click('#room-name-form button');
await ana.page.waitForFunction(() => [...document.querySelectorAll('.msg__text')].some((e) => e.textContent.includes('is now Roberto')), null, { timeout: 6000 }).catch(() => {});
ok(await wr(ana.page, () => window.__watchRoom.chat.members.some((m) => m.name === 'Roberto')), 'rename reaches the other viewer');

// Connection drops: sending queues, status shows reconnecting, then everything recovers.
await bob.context.setOffline(true);
await bob.page.keyboard.press('Enter'); await bob.page.keyboard.type('sent while offline'); await bob.page.keyboard.press('Enter');
await sleep(4000);
const offline = await wr(bob.page, () => ({ chat: window.__watchRoom.health.items.get('chat').status, net: window.__watchRoom.health.items.get('network').status, pending: !!document.querySelector('.msg--pending, .msg--failed') }));
ok(offline.chat !== 'ok' && offline.pending, `offline is detected (chat ${offline.chat}, network ${offline.net}) and the message waits`);
await bob.context.setOffline(false);
await ana.page.waitForFunction(() => [...document.querySelectorAll('.msg__text')].some((e) => e.textContent === 'sent while offline'), null, { timeout: 25000 }).catch(() => {});
ok(await wr(ana.page, () => [...document.querySelectorAll('.msg__text')].some((e) => e.textContent === 'sent while offline')), 'queued message is delivered once the connection returns');
await bob.page.waitForFunction(() => window.__watchRoom.health.items.get('chat').status === 'ok', null, { timeout: 25000 }).catch(() => {});
ok((await wr(bob.page, () => window.__watchRoom.health.items.get('chat').status)) === 'ok', 'chat status returns to live');

// Expired room → new room instead of a dead page.
const dead = await openViewer(browser, `${base}index.php?room=quiet-otter-00`, 'Cara').catch(() => null);
if (dead) {
  const info = await wr(dead.page, () => ({ room: window.__watchRoom.chat.room?.id, note: [...document.querySelectorAll('.msg__text')].map((e) => e.textContent).join(' | ') }));
  ok(info.room && info.room !== 'quiet-otter-00' && /expired/.test(info.note), `a dead room link starts a fresh room (${info.room})`);
} else {
  ok(false, 'a dead room link starts a fresh room');
}

await browser.close();
finish('chat');
