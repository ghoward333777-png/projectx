// Records two short synthetic test videos (16:9 and 4:3) into video-chat-player/media/
// using Chromium's own MediaRecorder on an animated canvas, so the browser check can
// prove content-rect geometry with no network and no ffmpeg.
// Run: node video-chat-player/bin/make-test-media.mjs
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); } catch { playwright = require('/opt/node22/lib/node_modules/playwright'); }
const { chromium } = playwright;

const outDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'media');
mkdirSync(outDir, { recursive: true });
const clips = [
  { file: 'test-16x9.webm', width: 640, height: 360 },
  { file: 'test-4x3.webm', width: 640, height: 480 },
];

const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent('<canvas id="c"></canvas>');
for (const clip of clips) {
  const base64 = await page.evaluate(({ width, height, seconds }) => new Promise((resolve, reject) => {
    const canvas = document.getElementById('c');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    const stream = canvas.captureStream(24);
    const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8', videoBitsPerSecond: 600000 });
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onerror = (e) => reject(new Error(String(e.error || e)));
    rec.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' });
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    };
    const start = performance.now();
    const draw = () => {
      const t = (performance.now() - start) / 1000;
      const hue = (t * 60) % 360;
      ctx.fillStyle = `hsl(${hue} 60% 30%)`;
      ctx.fillRect(0, 0, width, height);
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 6;
      ctx.strokeRect(3, 3, width - 6, height - 6);
      ctx.fillStyle = '#fff';
      ctx.beginPath();
      ctx.arc(width / 2 + Math.cos(t * 2) * width * 0.3, height / 2 + Math.sin(t * 2) * height * 0.3, 24, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = `${Math.round(height / 8)}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(`${width}×${height}  ${t.toFixed(1)}s`, width / 2, height / 2);
      if (t < seconds) requestAnimationFrame(draw); else rec.stop();
    };
    rec.start(100);
    requestAnimationFrame(draw);
  }), { width: clip.width, height: clip.height, seconds: 4 });
  const bytes = Buffer.from(base64, 'base64');
  writeFileSync(join(outDir, clip.file), bytes);
  console.log(`${clip.file}  ${clip.width}×${clip.height}  ${bytes.length} bytes`);
}
await browser.close();
