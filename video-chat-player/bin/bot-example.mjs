// A room bot built on the SDK, runnable in Node 18+:
//   node video-chat-player/bin/bot-example.mjs http://127.0.0.1:8082/video-chat-player/api.php quiet-otter-41
// It joins, greets, answers "!time" with the shared position, "!next" by advancing the
// playlist, and "!add <url>" by adding a video. Ctrl+C to stop.
import { WatchRoomClient } from '../assets/sdk.js';

const [,, base = 'http://127.0.0.1:8082/video-chat-player/api.php', roomId] = process.argv;
if (!roomId) { console.error('usage: bot-example.mjs <api base> <room id>'); process.exit(1); }

const bot = await WatchRoomClient.join({ base, roomId, name: 'Bot' });
console.log(`joined ${roomId} as ${bot.memberId}`);
await bot.send('Bot here. Try !time, !next or !add <link>.');
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

bot.on('message', async (m) => {
  if (m.kind !== 'chat' || m.memberId === bot.memberId) return;
  const [cmd, ...rest] = m.text.trim().split(/\s+/);
  try {
    if (cmd === '!time') await bot.send(`We are at ${fmt(bot.expectedPosition())} (${bot.stateCache?.playing ? 'playing' : 'paused'}).`);
    if (cmd === '!next') { const items = bot.playlistCache?.items || []; const i = items.findIndex((x) => x.id === bot.playlistCache.current); const next = items.slice(i + 1).find((x) => x.status !== 'error'); if (next) await bot.jump(next.id); else await bot.send('Nothing after this one.'); }
    if (cmd === '!add' && rest[0]) { const r = await bot.add(rest[0]); await bot.send(r.needsImport ? 'That is a playlist; open it in the player to import.' : `Added ${r.item.title}.`); }
  } catch (err) { await bot.send(`Could not do that: ${err.message}`).catch(() => {}); }
});
bot.on('status', (s) => { if (s.status !== 'live') console.log('status', s.status); });
bot.subscribe({ mode: 'poll' });
