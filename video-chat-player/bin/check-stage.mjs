// Browser check for step 1: the stage plays an HTML5 video, the content rect matches the
// picture's shape, the overlay sits inside the picture, and all of that holds in full
// screen. Run: node video-chat-player/bin/check-stage.mjs http://127.0.0.1:8082/video-chat-player/
// Needs the test media from bin/make-test-media.mjs and Playwright with Chromium.
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); } catch { playwright = require('/opt/node22/lib/node_modules/playwright'); }
const { chromium } = playwright;

const base = (process.argv[2] || 'http://127.0.0.1:8082/video-chat-player/').replace(/\/?$/, '/');
const cases = [
  { name: '16:9 picture', src: 'media/test-16x9.webm', ratio: 16 / 9 },
  { name: '4:3 picture', src: 'media/test-4x3.webm', ratio: 4 / 3 },
];
const failures = [];
const ok = (cond, label) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}`); if (!cond) failures.push(label); };
const near = (a, b, tol) => Math.abs(a - b) <= tol;

const args = ['--autoplay-policy=no-user-gesture-required'];
if (process.env.WATCHROOM_SPKI) args.push(`--ignore-certificate-errors-spki-list=${process.env.WATCHROOM_SPKI}`);
const browser = await chromium.launch({ args });
const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
page.on('pageerror', (e) => failures.push(`page error: ${e}`));

const snapshot = () => page.evaluate(() => {
  const wr = window.__watchRoom;
  const root = wr.stage.root;
  const box = root.getBoundingClientRect();
  const ov = wr.stage.overlay.getBoundingClientRect();
  const v = root.querySelector('video');
  return {
    state: wr.state, error: wr.error,
    rect: wr.stage.contentRect(),
    fullscreen: wr.stage.isFullscreen(),
    fullscreenElementIsStage: document.fullscreenElement === root,
    box: { x: box.left, y: box.top, width: box.width, height: box.height },
    overlay: { left: ov.left - box.left, right: ov.right - box.left, top: ov.top - box.top, bottom: ov.bottom - box.top, width: ov.width },
    video: { paused: v.paused, time: v.currentTime, w: v.videoWidth, h: v.videoHeight },
    viewport: { w: window.innerWidth, h: window.innerHeight },
  };
});

function checkGeometry(s, label, ratio) {
  const r = s.rect;
  ok(r && r.source === 'media', `${label}: content rect comes from the media size`);
  ok(near(r.width / r.height, ratio, 0.02), `${label}: content rect aspect ${(r.width / r.height).toFixed(3)} ≈ ${ratio.toFixed(3)}`);
  ok(near(r.x * 2 + r.width, r.stageWidth, 1) && near(r.y * 2 + r.height, r.stageHeight, 1), `${label}: content rect is centred`);
  const o = s.overlay;
  ok(o.left >= r.x - 0.5 && o.right <= r.x + r.width + 0.5, `${label}: overlay is horizontally inside the picture (${o.left.toFixed(0)}–${o.right.toFixed(0)} within ${r.x.toFixed(0)}–${(r.x + r.width).toFixed(0)})`);
  ok(o.bottom <= r.y + r.height + 0.5 && o.top >= r.y - 0.5, `${label}: overlay is vertically inside the picture (bottom ${o.bottom.toFixed(0)} ≤ ${(r.y + r.height).toFixed(0)})`);
  ok(near(o.left - r.x, r.x + r.width - o.right, 1), `${label}: overlay is horizontally centred on the picture`);
  ok(o.width <= 720.5, `${label}: overlay width ${o.width.toFixed(0)} ≤ 720`);
}

for (const c of cases) {
  await page.goto(`${base}index.php?src=${encodeURIComponent(c.src)}`, { waitUntil: 'load' });
  await page.waitForFunction(() => window.__watchRoom && ['playing', 'paused', 'ready', 'error', 'ended'].includes(window.__watchRoom.state), null, { timeout: 15000 });
  await page.waitForTimeout(1200);
  let s = await snapshot();
  ok(s.state === 'playing' && !s.video.paused && s.video.time > 0.2, `${c.name}: video is playing (state=${s.state}${s.error ? ', ' + s.error : ''}, t=${s.video.time.toFixed(2)})`);
  checkGeometry(s, `${c.name} · page`, c.ratio);

  await page.keyboard.press('f');
  await page.waitForFunction(() => window.__watchRoom.stage.isFullscreen(), null, { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(600);
  s = await snapshot();
  ok(s.fullscreen, `${c.name}: stage entered full screen (${s.fullscreenElementIsStage ? 'Fullscreen API on the stage element' : 'fallback'})`);
  ok(near(s.box.width, s.viewport.w, 1) && near(s.box.height, s.viewport.h, 1), `${c.name}: stage fills the viewport in full screen (${s.box.width}×${s.box.height})`);
  ok(!s.video.paused, `${c.name}: video kept playing through the fullscreen change`);
  checkGeometry(s, `${c.name} · fullscreen`, c.ratio);

  await page.keyboard.press('f');
  await page.waitForFunction(() => !window.__watchRoom.stage.isFullscreen(), null, { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(400);
  s = await snapshot();
  ok(!s.fullscreen, `${c.name}: left full screen with F`);
  checkGeometry(s, `${c.name} · back in page`, c.ratio);
}

// A refused source falls back to the default and says so.
await page.goto(`${base}index.php?src=${encodeURIComponent('javascript:alert(1)')}`, { waitUntil: 'load' });
ok(await page.locator('.notice--warn').count() === 1, 'rejected source shows the warning notice');
const fallback = await page.locator('#stage').getAttribute('data-src');
ok(fallback && !fallback.includes('javascript'), `rejected source falls back to the default (${fallback})`);

await browser.close();
console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nAll stage checks passed');
process.exit(failures.length ? 1 : 0);
