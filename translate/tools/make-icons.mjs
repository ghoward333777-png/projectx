#!/usr/bin/env node
// Rasterize the app icon to PNG (no dependencies): two overlapping speech
// bubbles on the brand colour. node tools/make-icons.mjs
import { writeFileSync, mkdirSync } from 'node:fs';
import { deflateSync } from 'node:zlib';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'icons');
const BG = [11, 110, 95];
const FG = [255, 255, 255];
const FG2 = [146, 226, 210];

function crc32(buf) {
  let c, crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function png(size, px) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    px.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))]);
}
// Signed distance to a rounded rectangle centred at (cx, cy).
function sdRound(x, y, cx, cy, hw, hh, r) {
  const qx = Math.abs(x - cx) - hw + r, qy = Math.abs(y - cy) - hh + r;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
}
function sdTri(x, y, [ax, ay], [bx, by], [cx, cy]) {
  const s = (px, py, qx, qy, rx, ry) => (px - rx) * (qy - ry) - (qx - rx) * (py - ry);
  const d1 = s(x, y, ax, ay, bx, by), d2 = s(x, y, bx, by, cx, cy), d3 = s(x, y, cx, cy, ax, ay);
  const inside = (d1 < 0) === (d2 < 0) && (d2 < 0) === (d3 < 0);
  return inside ? -1 : 1;
}
function render(size, { maskable = false, rounded = true } = {}) {
  const px = Buffer.alloc(size * size * 4);
  const u = (v) => v * size;
  const pad = maskable ? 0.12 : 0; // keep artwork inside the maskable safe zone
  const sc = 1 - pad * 2;
  const at = (v) => u(pad + v * sc);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const cover = (sd) => Math.max(0, Math.min(1, 0.5 - sd));
      const bgA = maskable || !rounded ? 1 : cover(sdRound(x + 0.5, y + 0.5, u(0.5), u(0.5), u(0.5), u(0.5), u(0.22)));
      let col = BG;
      // back bubble (light)
      const b2 = Math.min(sdRound(x + 0.5, y + 0.5, at(0.6), at(0.58), u(0.2 * sc), u(0.15 * sc), u(0.07 * sc)), sdTri(x + 0.5, y + 0.5, [at(0.66), at(0.7)], [at(0.76), at(0.7)], [at(0.76), at(0.82)]) * 2);
      const a2 = cover(b2);
      // front bubble (white)
      const b1 = Math.min(sdRound(x + 0.5, y + 0.5, at(0.42), at(0.42), u(0.24 * sc), u(0.17 * sc), u(0.08 * sc)), sdTri(x + 0.5, y + 0.5, [at(0.3), at(0.55)], [at(0.42), at(0.55)], [at(0.28), at(0.68)]) * 2);
      const a1 = cover(b1);
      const mix = (c, d, t) => c.map((v, k) => Math.round(v * (1 - t) + d[k] * t));
      col = mix(col, FG2, a2);
      col = mix(col, FG, a1);
      // two "text lines" in the front bubble
      for (const ly of [0.37, 0.47]) {
        const ln = sdRound(x + 0.5, y + 0.5, at(0.42), at(ly), u(0.14 * sc), u(0.02 * sc), u(0.02 * sc));
        col = mix(col, BG, cover(ln) * a1);
      }
      px[i] = col[0]; px[i + 1] = col[1]; px[i + 2] = col[2]; px[i + 3] = Math.round(bgA * 255);
    }
  }
  return png(size, px);
}
writeFileSync(join(OUT, 'icon-192.png'), render(192));
writeFileSync(join(OUT, 'icon-512.png'), render(512));
writeFileSync(join(OUT, 'maskable-512.png'), render(512, { maskable: true }));
writeFileSync(join(OUT, 'apple-touch-icon.png'), render(180, { rounded: false }));

// Native shells: Android launcher mipmaps and the iOS/iPadOS app icon (opaque, unrounded — the OS masks it).
const NATIVE = join(OUT, '..', 'native');
for (const [dpi, size] of [['mdpi', 48], ['hdpi', 72], ['xhdpi', 96], ['xxhdpi', 144], ['xxxhdpi', 192]]) {
  const dir = join(NATIVE, 'android', 'app', 'src', 'main', 'res', `mipmap-${dpi}`);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'ic_launcher.png'), render(size));
}
writeFileSync(join(NATIVE, 'ios', 'QueryBookTranslate', 'Assets.xcassets', 'AppIcon.appiconset', 'icon-1024.png'), render(1024, { rounded: false }));
writeFileSync(join(OUT, 'icon.svg'), `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="rgb(${BG})"/><rect x="40" y="43" width="40" height="30" rx="7" fill="rgb(${FG2})"/><path d="M66 70h10v12z" fill="rgb(${FG2})"/><rect x="18" y="25" width="48" height="34" rx="8" fill="#fff"/><path d="M30 55h12L28 68z" fill="#fff"/><rect x="28" y="35" width="28" height="4" rx="2" fill="rgb(${BG})"/><rect x="28" y="45" width="28" height="4" rx="2" fill="rgb(${BG})"/></svg>\n`);
console.log('icons written');
