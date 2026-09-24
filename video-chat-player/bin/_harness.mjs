// Shared bits for the browser checks: Playwright launch, pass/fail bookkeeping, helpers.
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); } catch { playwright = require('/opt/node22/lib/node_modules/playwright'); }
export const { chromium } = playwright;

export const base = (process.argv[2] || 'http://127.0.0.1:8082/video-chat-player/').replace(/\/?$/, '/');
export const failures = [];
export const ok = (cond, label) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}`); if (!cond) failures.push(label); };
export const near = (a, b, tol) => Math.abs(a - b) <= tol;
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch() {
  const args = ['--autoplay-policy=no-user-gesture-required'];
  if (process.env.WATCHROOM_SPKI) args.push(`--ignore-certificate-errors-spki-list=${process.env.WATCHROOM_SPKI}`);
  return chromium.launch({ args });
}

export async function openViewer(browser, url, name) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  page.on('pageerror', (e) => failures.push(`${name}: page error: ${e}`));
  const u = new URL(url);
  u.searchParams.set('name', name);
  await page.goto(u.toString(), { waitUntil: 'load' });
  await page.waitForFunction(() => window.__watchRoom && window.__watchRoom.chat.room, null, { timeout: 20000 });
  return { context, page };
}

export const wr = (page, fn, arg) => page.evaluate(fn, arg);
export const waitState = (page, states, timeout = 20000) => page.waitForFunction((s) => s.includes(window.__watchRoom.state), states, { timeout }).catch(() => {});
export const roomUrl = (page) => page.url();

export function finish(title) {
  console.log(failures.length ? `\n${failures.length} check(s) failed in ${title}` : `\nAll ${title} checks passed`);
  process.exit(failures.length ? 1 : 0);
}
