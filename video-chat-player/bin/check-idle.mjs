// Browser check for step 2: the overlay hides after the idle timeout, reveals on activity,
// never hides while typing, holding a draft, or paused, and the keyboard map works.
// Run: node video-chat-player/bin/check-idle.mjs http://127.0.0.1:8082/video-chat-player/
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); } catch { playwright = require('/opt/node22/lib/node_modules/playwright'); }
const { chromium } = playwright;

const base = (process.argv[2] || 'http://127.0.0.1:8082/video-chat-player/').replace(/\/?$/, '/');
const failures = [];
const ok = (cond, label) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}`); if (!cond) failures.push(label); };
const near = (a, b, tol) => Math.abs(a - b) <= tol;

const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
page.on('pageerror', (e) => failures.push(`page error: ${e}`));
const wr = (fn, arg) => page.evaluate(fn, arg);
const idleState = () => wr(() => window.__watchRoom.idle.state);
const overlayStyle = () => wr(() => {
  const o = getComputedStyle(window.__watchRoom.stage.overlay);
  const c = getComputedStyle(window.__watchRoom.stage.controls);
  return { opacity: Number(o.opacity), pointer: o.pointerEvents, display: o.display, controlsOpacity: Number(c.opacity), cursor: getComputedStyle(window.__watchRoom.stage.root).cursor };
});

await page.goto(`${base}index.php?src=media%2Ftest-16x9.webm`, { waitUntil: 'load' });
await page.waitForFunction(() => window.__watchRoom && window.__watchRoom.state === 'playing', null, { timeout: 15000 });
// The synthetic clip is 4 s long; loop it so playback never ends mid-check.
await page.evaluate(() => { window.__watchRoom.player.el.loop = true; });
await page.mouse.move(400, 300);

// 1. Timing: activity → fading at 3000 ms → hidden at 3220 ms.
const timing = await wr(() => new Promise((resolve) => {
  const idle = window.__watchRoom.idle;
  const t0 = performance.now();
  let fade = null;
  idle.activity();
  const id = setInterval(() => {
    if (idle.state === 'fading' && fade === null) fade = performance.now() - t0;
    if (idle.state === 'hidden') { clearInterval(id); resolve({ fade, hidden: performance.now() - t0 }); }
    if (performance.now() - t0 > 8000) { clearInterval(id); resolve({ fade, hidden: null }); }
  }, 5);
}));
ok(timing.fade !== null && near(timing.fade, 3000, 120), `fade starts at ${timing.fade?.toFixed(0)} ms (target 3000 ± 120)`);
ok(timing.hidden !== null && near(timing.hidden, 3220, 150), `hidden at ${timing.hidden?.toFixed(0)} ms (target 3220 ± 150)`);
let st = await overlayStyle();
ok(st.opacity === 0 && st.controlsOpacity === 0 && st.pointer === 'none', `hidden overlay and controls are invisible and inert (opacity ${st.opacity}, pointer-events ${st.pointer})`);
ok(st.cursor === 'none', `cursor is hidden while idle (${st.cursor})`);

// 2. Reveal is instant on mouse movement.
await page.mouse.move(420, 320);
ok((await idleState()) === 'visible', 'mouse movement reveals immediately');
st = await overlayStyle();
ok(st.opacity === 1 && st.pointer !== 'none', 'revealed overlay is fully visible');

// 3. Composer focus pins; draft keeps it pinned after blur; clearing releases it.
await page.keyboard.press('Enter');
ok(await wr(() => document.activeElement === document.getElementById('overlay-input')), 'Enter focuses the composer');
await page.waitForTimeout(3600);
ok((await idleState()) === 'pinned', 'overlay stays while the composer has focus (3.6 s later)');
await page.keyboard.type('hello');
await page.keyboard.press('Escape');
ok(await wr(() => document.activeElement !== document.getElementById('overlay-input')), 'Escape leaves the composer');
await page.waitForTimeout(3600);
ok((await idleState()) === 'pinned' && await wr(() => window.__watchRoom.idle.isPinned('draft')), 'unsent draft keeps the overlay open after leaving the composer');
await page.focus('#overlay-input');
await page.keyboard.press('Control+A');
await page.keyboard.press('Backspace');
await page.keyboard.press('Escape');
await page.waitForFunction(() => window.__watchRoom.idle.state === 'hidden', null, { timeout: 5000 }).catch(() => {});
ok((await idleState()) === 'hidden', 'clearing the draft lets the overlay hide again');

// 4. Paused playback pins.
await page.mouse.move(500, 300);
await page.keyboard.press('Space');
ok(await wr(() => window.__watchRoom.player.el.paused), 'Space pauses');
await page.waitForTimeout(3600);
ok((await idleState()) === 'pinned', 'overlay never hides while paused');
await page.keyboard.press('k');
ok(await wr(() => !window.__watchRoom.player.el.paused), 'K resumes');

// 5. Keyboard map.
const t1 = await wr(() => window.__watchRoom.player.currentTime());
await page.keyboard.press('ArrowLeft');
await page.waitForTimeout(150);
const t2 = await wr(() => window.__watchRoom.player.currentTime());
ok(t2 < t1, `ArrowLeft seeks back (${t1.toFixed(2)} → ${t2.toFixed(2)})`);
await page.keyboard.press('m');
ok(await wr(() => window.__watchRoom.player.el.muted), 'M mutes');
await page.keyboard.press('m');
ok(await wr(() => !window.__watchRoom.player.el.muted), 'M again unmutes');
const v1 = await wr(() => window.__watchRoom.player.el.volume);
await page.keyboard.press('ArrowDown');
const v2 = await wr(() => window.__watchRoom.player.el.volume);
ok(near(v2, v1 - 0.05, 0.001), `ArrowDown lowers volume (${v1.toFixed(2)} → ${v2.toFixed(2)})`);
await page.keyboard.press('c');
st = await overlayStyle();
ok(st.display === 'none' && await wr(() => !document.getElementById('chat-dot').hidden), 'C hides the chat entirely and shows the corner dot');
await page.keyboard.press('c');
st = await overlayStyle();
ok(st.display !== 'none', 'C again restores the chat');
await page.keyboard.press('f');
await page.waitForFunction(() => window.__watchRoom.stage.isFullscreen(), null, { timeout: 5000 }).catch(() => {});
ok(await wr(() => window.__watchRoom.stage.isFullscreen()), 'F enters full screen');
await page.waitForFunction(() => window.__watchRoom.idle.state === 'hidden', null, { timeout: 6000 }).catch(() => {});
ok((await idleState()) === 'hidden', 'overlay hides in full screen too');
await page.mouse.move(640, 400);
ok((await idleState()) === 'visible', 'mouse movement reveals in full screen');
await page.keyboard.press('f');
await page.waitForFunction(() => !window.__watchRoom.stage.isFullscreen(), null, { timeout: 5000 }).catch(() => {});

// 6. Leaving the stage shortens the timer to 1 s.
await page.mouse.move(500, 300);
await page.evaluate(() => window.__watchRoom.idle.activity());
await page.mouse.move(1100, 700);
const leave = await wr(() => new Promise((resolve) => {
  const idle = window.__watchRoom.idle; const t0 = performance.now();
  const id = setInterval(() => { if (idle.state === 'fading' || idle.state === 'hidden') { clearInterval(id); resolve(performance.now() - t0); } if (performance.now() - t0 > 4000) { clearInterval(id); resolve(null); } }, 5);
}));
ok(leave !== null && leave < 1300, `mouse leaving the stage hides within ~1 s (${leave?.toFixed(0)} ms)`);

// 7. Control bar: seek bar scrubs, click play/pause works.
await page.mouse.move(500, 300);
await page.evaluate(() => { const s = document.getElementById('ctl-seek'); s.value = '500'; s.dispatchEvent(new Event('input', { bubbles: true })); s.dispatchEvent(new Event('change', { bubbles: true })); });
await page.waitForTimeout(200);
const mid = await wr(() => window.__watchRoom.player.currentTime() / window.__watchRoom.player.duration());
ok(near(mid, 0.5, 0.12), `seek bar scrubs to the middle (${(mid * 100).toFixed(0)} %)`);
await page.click('#ctl-play');
ok(await wr(() => window.__watchRoom.player.el.paused), 'play button pauses');
await page.click('#ctl-play');
ok(await wr(() => !window.__watchRoom.player.el.paused), 'play button resumes');

await browser.close();
console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nAll idle and control checks passed');
process.exit(failures.length ? 1 : 0);
