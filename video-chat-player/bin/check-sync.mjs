// Step 6 check: the guest follows the host's play, pause and seek within tolerance; a
// guest with control can pause for everyone; a stalled player recovers by itself.
// Needs media/test-long.webm from make-test-media.mjs --long.
import { base, ok, near, sleep, launch, openViewer, wr, waitState, finish } from './_harness.mjs';

const browser = await launch();
const host = await openViewer(browser, `${base}index.php?src=media%2Ftest-long.webm`, 'Host');
await waitState(host.page, ['playing']);
const url = host.page.url();
const guest = await openViewer(browser, url, 'Guest');
await waitState(guest.page, ['playing', 'paused']);
await sleep(3000);
const pos = (page) => wr(page, () => ({ t: window.__watchRoom.player.currentTime(), playing: window.__watchRoom.player.isPlaying(), state: window.__watchRoom.state }));

let h = await pos(host.page); let g = await pos(guest.page);
ok(g.playing && h.playing, `both playing (host ${h.t.toFixed(2)} s, guest ${g.t.toFixed(2)} s)`);
ok(near(h.t, g.t, 0.6), `guest within 600 ms of host after joining (Δ ${Math.abs(h.t - g.t).toFixed(3)} s)`);

// Host seeks forward.
await wr(host.page, () => window.__watchRoom.player.seek(20));
await sleep(3000);
h = await pos(host.page); g = await pos(guest.page);
ok(near(h.t, g.t, 0.6) && g.t > 18, `guest followed the host's seek (host ${h.t.toFixed(2)}, guest ${g.t.toFixed(2)})`);

// Host pauses.
await host.page.keyboard.press('Space');
await sleep(2500);
g = await pos(guest.page);
ok(!g.playing, 'guest paused when the host paused');
await host.page.keyboard.press('Space');
await sleep(2500);
g = await pos(guest.page);
ok(g.playing, 'guest resumed when the host resumed');

// Guest with control pauses for everyone (default room setting).
await guest.page.keyboard.press('Space');
await sleep(2500);
h = await pos(host.page);
ok(!h.playing, 'guest with control paused the host too');
await guest.page.keyboard.press('Space');
await sleep(2500);

// Host turns guest control off: the guest's pause is undone.
await host.page.check('#set-guests', { force: true }).catch(() => {});
await host.page.uncheck('#set-guests', { force: true });
await sleep(2500);
await guest.page.keyboard.press('Space');
await sleep(2500);
h = await pos(host.page); g = await pos(guest.page);
ok(h.playing && g.playing, `with guest control off, the guest cannot pause the room (host ${h.playing}, guest ${g.playing})`);

// Drift: knock the guest 1 s off; it is nudged back without a visible seek.
await wr(guest.page, () => { window.__watchRoom.player.seek(window.__watchRoom.player.currentTime() - 1); });
await sleep(6000);
h = await pos(host.page); g = await pos(guest.page);
ok(near(h.t, g.t, 0.6), `drift corrected (Δ ${Math.abs(h.t - g.t).toFixed(3)} s)`);

// Stall recovery: freeze the host's clock and see the watchdog act.
await wr(host.page, () => { const v = window.__watchRoom.player.el; v.pause(); Object.defineProperty(v, 'paused', { value: false, configurable: true }); });
await host.page.waitForFunction(() => window.__watchRoom.health.log.some((e) => /stalled/.test(e.detail)), null, { timeout: 20000 }).catch(() => {});
const stalled = await wr(host.page, () => window.__watchRoom.health.log.filter((e) => e.name === 'player').map((e) => e.detail).slice(-3).join(' → '));
ok(/stalled/.test(stalled), `watchdog noticed the stall and acted (${stalled})`);

await browser.close();
finish('sync');
