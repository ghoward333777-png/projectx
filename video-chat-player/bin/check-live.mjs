// Live-stream check: with the adapter reporting a live stream, the seek bar and speed go
// away, a LIVE badge shows, a host seek is not propagated, a host pause is, and messages
// carry no media time. YouTube itself cannot be reached from a sandbox, so the live state
// is simulated on the adapter; the behaviour around it is what this proves.
import { base, ok, sleep, launch, openViewer, wr, waitState, finish } from './_harness.mjs';

const browser = await launch();
const host = await openViewer(browser, `${base}index.php?src=media%2Ftest-long.webm`, 'Host');
await waitState(host.page, ['playing']);
const guest = await openViewer(browser, host.page.url(), 'Guest');
await waitState(guest.page, ['playing', 'paused']);
for (const p of [host.page, guest.page]) await wr(p, () => { const a = window.__watchRoom.player.current; a.isLive = () => true; a.duration = () => 0; });
await sleep(2500);
const h = await wr(host.page, () => ({ seekHidden: document.getElementById('ctl-seek').hidden, time: document.getElementById('ctl-time').textContent, rateDisabled: document.getElementById('ctl-rate').disabled, player: window.__watchRoom.health.items.get('player').detail }));
ok(h.seekHidden && h.rateDisabled, 'seek bar and speed are hidden for a live stream');
ok(/LIVE/.test(h.time) && h.player === 'live stream', `LIVE badge and health note (${h.time})`);
const before = await wr(guest.page, () => window.__watchRoom.player.currentTime());
await wr(host.page, () => window.__watchRoom.player.seek(30));
await sleep(2500);
const g1 = await wr(guest.page, () => ({ t: window.__watchRoom.player.currentTime(), sync: window.__watchRoom.health.items.get('sync').detail }));
ok(g1.t < 20 && g1.t >= before, `a host seek is not applied to a live viewer (guest at ${g1.t.toFixed(1)} s)`);
ok(/live stream/.test(g1.sync), 'sync reports live mode');
await host.page.keyboard.press('Space');
await sleep(2500);
ok(!(await wr(guest.page, () => window.__watchRoom.player.isPlaying())), 'a host pause still reaches the guest');
await host.page.keyboard.press('Space');
await sleep(1000);
await host.page.keyboard.press('Enter'); await host.page.keyboard.type('live chat'); await host.page.keyboard.press('Enter');
await sleep(1500);
ok(await wr(guest.page, () => { const m = [...document.querySelectorAll('.msg')].find((r) => r.textContent.includes('live chat')); return !!m && !m.querySelector('.msg__stamp'); }), 'messages during a live stream carry no media-time stamp');
await host.page.keyboard.press('Escape');
const t1 = await wr(host.page, () => window.__watchRoom.player.currentTime());
await host.page.keyboard.press('ArrowRight');
await sleep(300);
const t2 = await wr(host.page, () => window.__watchRoom.player.currentTime());
ok(t2 - t1 < 2, `arrow keys do not seek a live stream (${t1.toFixed(1)} → ${t2.toFixed(1)} s)`);
await browser.close();
finish('live');
