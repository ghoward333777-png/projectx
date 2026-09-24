// API check: the SDK from Node (create, join, send, subscribe by polling, playback, resolve,
// webhooks), the raw event stream over fetch, and the embed bridge driven from a host page
// in real Chromium. Run: node video-chat-player/bin/check-api.mjs http://127.0.0.1:8082/video-chat-player/
import { base, ok, near, sleep, launch, finish, failures } from './_harness.mjs';
import { WatchRoomClient } from '../assets/sdk.js';

const apiBase = `${base}api.php`;

// ---- SDK in Node ----
const host = await WatchRoomClient.create({ base: apiBase, name: 'Host', src: 'media/test-long.webm' });
ok(!!host.roomId && !!host.hostToken, `SDK created room ${host.roomId} with a host token`);
ok(host.inviteUrl.endsWith(`index.php?room=${host.roomId}`), `inviteUrl is ${host.inviteUrl}`);
const guest = await WatchRoomClient.join({ base: apiBase, roomId: host.roomId, name: 'Guest' });
ok(guest.memberId !== host.memberId && guest.members.length === 2, 'SDK joined as a second member');

const received = [];
const stop = guest.subscribe({ mode: 'poll', intervalMs: 300 });
guest.on('message', (m) => received.push(m));
const stateEvents = [];
guest.on('state', (s) => stateEvents.push(s));
await host.send('hello from node', { mediaTime: 12.5 });
await sleep(1200);
ok(received.some((m) => m.text === 'hello from node' && m.mediaTime === 12.5), 'guest received the message through the polling subscription');

await host.play(0);
await sleep(1500);
ok(host.stateCache.playing && stateEvents.some((s) => s.playing), 'play() shared the state and the guest saw it');
const expected = guest.expectedPosition();
ok(expected > 0.8 && expected < 4, `guest computes the expected position from the clock (${expected.toFixed(2)} s)`);
await host.pause(5);
await sleep(1200);
ok(!host.stateCache.playing && near(guest.expectedPosition(), 5, 0.01), 'pause(5) parks everyone at 5 s');
await host.seek(20);
ok(near(host.stateCache.mediaTime, 20, 0.01) && !host.stateCache.playing, 'seek() keeps the paused state');

// Stale write is retried transparently by the SDK.
guest.stateCache = { ...guest.stateCache, rev: 1 };
await host.settings({ guestsControl: true });
const st = await guest.play(1);
ok(st.playing && st.rev > 1, 'SDK recovers from a stale baseRev on its own');

const resolved = await host.resolve('https://youtu.be/aqz-KE-bpKQ');
ok(resolved.kind === 'youtube' && /Big Buck Bunny/.test(resolved.title), `resolve() reads the title without an API key (${resolved.title})`);
const added = await host.add('media/test-4x3.webm');
ok(added.item.kind === 'mp4' && added.playlist.items.length === 2, 'add() appends a local file');
await host.jump(added.item.id);
await sleep(800);
ok(guest.playlistCache?.current === added.item.id, 'jump() moved everyone to the new item');
const wh = await host.addWebhook('https://hooks.example.com/watchroom', ['message']);
ok(!!wh.webhook.secret && (await host.webhooks()).webhooks.length === 1, 'webhooks can be registered and listed by the host');
await host.removeWebhook(wh.webhook.id);
let denied = null;
try { await guest.reorder([]); } catch (err) { denied = err.code; }
ok(denied === 'forbidden', `guest reorder is refused with a typed error (${denied})`);
stop();

// ---- raw event stream ----
const controller = new AbortController();
const res = await fetch(`${apiBase}/v1/rooms/${host.roomId}/events?since=0`, { headers: { Authorization: `Bearer ${guest.memberId}` }, signal: controller.signal });
ok(res.ok && /text\/event-stream/.test(res.headers.get('content-type') || ''), `event stream answers with text/event-stream (${res.status})`);
const reader = res.body.getReader();
let text = '';
const t0 = Date.now();
setTimeout(() => host.send('streamed message').catch(() => {}), 700);
while (Date.now() - t0 < 4000 && !/streamed message/.test(text)) {
  const { value, done } = await reader.read();
  if (done) break;
  text += Buffer.from(value).toString('utf8');
}
controller.abort();
ok(/^retry: 1000/.test(text) && /event: state/.test(text) && /event: playlist/.test(text) && /event: members/.test(text), 'stream opens with retry hint, state, playlist and members');
ok(/streamed message/.test(text), 'a message sent while the stream is open arrives on it');

// ---- embed bridge in a browser ----
const browser = await launch();
const page = await (await browser.newContext({ viewport: { width: 1100, height: 700 } })).newPage();
page.on('pageerror', (e) => failures.push(`embed page error: ${e}`));
await page.goto(`${base}embed-demo.php?room=${host.roomId}`, { waitUntil: 'load' });
const bridge = await page.evaluate(async ({ base, room }) => {
  const h = window.embeddedRoom; // created by the example page with WatchRoom.embed()
  await new Promise((r) => setTimeout(r, 300));
  const box = document.getElementById('box');
  const events = [];
  h.on('*', (e) => events.push(e));
  await new Promise((r) => { h.on('ready', r); setTimeout(r, 15000); });
  await new Promise((r) => setTimeout(r, 2500));
  const snap = await h.command('snapshot');
  await h.pause();
  await new Promise((r) => setTimeout(r, 600));
  const snap2 = await h.command('snapshot');
  await h.send('hi from the host page');
  await new Promise((r) => setTimeout(r, 1500));
  let unknown = null;
  try { await h.command('explode'); } catch (err) { unknown = err.message; }
  return { compact: h.iframe.src.includes('embed=1'), room: snap.room, members: snap.members.map((m) => m.name), playingBefore: snap.state.playing, playingAfter: snap2.state.playing, events: [...new Set(events)], log: document.getElementById('log').textContent, unknown };
}, { base, room: host.roomId });
ok(bridge.compact && bridge.room === host.roomId, `embed loads the compact player into the room (${bridge.room})`);
ok(bridge.members.includes('Host page'), 'embedded viewer joined as its own member');
ok(bridge.playingAfter === false, `pause command reached the player (playing ${bridge.playingBefore} → ${bridge.playingAfter})`);
ok(/ready · room/.test(bridge.log) && /playlist/.test(bridge.log) && bridge.events.includes('pause'), `host page receives events (page log has ready+playlist; live: ${bridge.events.join(', ')})`);
ok(/Unknown command/.test(bridge.unknown || ''), 'unknown commands are answered with an error, not silence');
await sleep(1000);
const list = await host.messages({ since: 0, limit: 200 });
ok(list.messages.some((m) => m.text === 'hi from the host page'), 'message sent through the bridge is in the room');
await browser.close();
finish('api');
