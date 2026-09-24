# Watch Room API

Everything the player does, programmable. Three layers, same server, no dependencies:

| Layer | For | Where |
|---|---|---|
| **REST `/v1`** | Any language, bots, integrations | `api.php/v1/…` (or `api.php?route=/v1/…`), documented at `api-docs.php` and `api.php/v1/openapi.json` |
| **JavaScript SDK** | Browsers and Node 18+ | `assets/sdk.js` (ES module, zero dependencies) |
| **Embed bridge** | Putting the player inside another site and driving it | `assets/embed.js` on the host page, `postMessage` underneath |

The web page itself uses the compact `api.php?action=…` dialect; both dialects share one
implementation, so nothing can drift.

## Concepts

- **Room**: a link. `POST /v1/rooms` makes one; it lives under `rooms/<id>/` and expires after 24 h without activity.
- **Member**: a display name plus an unguessable id (`m_…`). The id is the **Bearer token**. Keep it as you would a session cookie.
- **Host**: the creator, who also receives a **host token** once. Host-only calls send `X-Host-Token`. The host can hand the role over (`PATCH /v1/rooms/{id}` with `hostMemberId`). When the host is offline, the earliest online member acts as host automatically.
- **Playlist**: revisioned (`rev`). Items are `mp4` (any https .mp4/.webm, or `media/<file>`), `youtube` (one video) or `youtube-playlist` (a whole YouTube list played as one item through the embed's own next/previous). `repeat` is `off`, `one` or `all`; `shuffle` stores a shared `order` so every viewer advances the same way.
- **YouTube engines**: `lite` (default under `auto`) is API-free: a plain embed iframe driven over postMessage, no YouTube script on the page, no keys, no quotas. `api` uses YouTube's IFrame Player API. `auto` tries `lite` and falls back to `api` when the embed does not answer or never starts.
- **State**: the shared clock `{ itemId, playing, mediaTime, at, rate, rev }`. The position now is `mediaTime + (serverNow − at)/1000 × rate` while playing. Writes carry `baseRev`; a stale one is refused with 409 and the current state, so two controllers never fight.
- **Cursors**: `since` (message seq), `prev` (playlist rev), `srev` (state rev). `GET /sync` and the event stream return only what moved past them.
- **Time**: Unix milliseconds. Every response carries `serverTime`; compute `offset = serverTime − Date.now()` and keep the median of a few samples.
- **Errors**: always `{ "error": "for people", "code": "for_programs" }`. Codes: `bad_request`, `unauthorized`, `forbidden`, `not_found`, `rate_limited`, `stale`, `method`, `server_error`.

## REST in five calls

```bash
B=https://example.com/video-chat-player/api.php

# 1. create a room (host)
curl -s -X POST "$B/v1/rooms" -H 'Content-Type: application/json' \
     -d '{"name":"Bot","src":"https://youtu.be/qqwhjSzFJqY"}'
# → {"room":{"id":"quiet-otter-41",…},"memberId":"m_…","hostToken":"…","playlist":{…},"state":{…},"since":1}

# 2. someone else joins
curl -s -X POST "$B/v1/rooms/quiet-otter-41/members" -H 'Content-Type: application/json' -d '{"name":"Sam"}'

# 3. say something at a moment in the video
curl -s -X POST "$B/v1/rooms/quiet-otter-41/messages" -H "Authorization: Bearer m_…" \
     -H 'Content-Type: application/json' -d '{"id":"msg-0001","text":"watch this","mediaTime":134.2}'

# 4. play for everyone from 2:00
curl -s -X PUT "$B/v1/rooms/quiet-otter-41/state" -H "Authorization: Bearer m_…" \
     -H 'Content-Type: application/json' -d '{"state":{"playing":true,"mediaTime":120,"baseRev":3}}'

# 5. follow the room live
curl -N "$B/v1/rooms/quiet-otter-41/events?since=0" -H "Authorization: Bearer m_…"
```

### Endpoints

| Method | Path | Auth | Does |
|---|---|---|---|
| GET | `/v1/health` | – | Server self-checks |
| GET | `/v1/openapi.json` | – | OpenAPI 3.1 document |
| GET | `/v1/resolve?url=` | – | What a link would become (kind, title, thumbnail) |
| POST | `/v1/rooms` | API key if configured | Create a room; returns `hostToken` once |
| GET | `/v1/rooms/{id}` | member | Room, members, playlist, state |
| PATCH | `/v1/rooms/{id}` | host | `guestsControl`, `chatMode` (`overlay`/`docked`), `youtubeEngine` (`auto`/`lite`/`api`), `hostMemberId` |
| POST | `/v1/rooms/{id}/members` | – | Join (or rejoin with `memberId`) |
| PATCH | `/v1/rooms/{id}/members/me` | member | Rename |
| GET | `/v1/rooms/{id}/messages?since=&limit=` | member | Messages after a cursor, or the latest |
| POST | `/v1/rooms/{id}/messages` | member | Send (`id` de-duplicates retries) |
| GET | `/v1/rooms/{id}/sync?since=&prev=&srev=` | member | One poll: everything that changed |
| GET | `/v1/rooms/{id}/events` | member (header or `?memberId=`) | Server-sent events |
| GET | `/v1/rooms/{id}/playlist` | member | The playlist |
| POST | `/v1/rooms/{id}/playlist` | member | Add by link. A YouTube playlist link becomes one playable item; with `expand: true` it answers `needsImport` for `playlist/import` instead |
| POST | `/v1/rooms/{id}/playlist/import` | member | Add many YouTube ids |
| PATCH | `/v1/rooms/{id}/playlist` | member / host | `current` (jump), `repeat` (`off`/`one`/`all`), `shuffle` (bool), `order` (host), `remove` (host), `status` (report a failed item) |
| DELETE | `/v1/rooms/{id}/playlist/{itemId}` | host | Remove |
| GET | `/v1/rooms/{id}/state` | member | Shared clock plus `expectedPosition` |
| PUT | `/v1/rooms/{id}/state` | member (host when guest control is off) | Play, pause, seek, rate, item |
| GET/POST | `/v1/rooms/{id}/webhooks` | host | List / register |
| DELETE | `/v1/rooms/{id}/webhooks/{webhookId}` | host | Remove |

### Event stream

`text/event-stream` with events `message` (id = seq), `state` (id = s{rev}), `playlist`
(id = p{rev}), `members`, `ping` every 10 s, and `end` when the window closes (default
25 s; `EventSource` reconnects by itself, and the SDK does too). Pass your cursors as
`since`, `prev`, `srev` to resume. Browsers cannot set headers on `EventSource`, so this
endpoint also accepts `?memberId=` in the query.

On PHP's built-in dev server one stream occupies a worker: start it with
`PHP_CLI_SERVER_WORKERS=4 php -S 127.0.0.1:8082` when you use streams locally.
Real hosts (Apache, nginx + FPM) need nothing special.

### Webhooks

The host registers up to 5 https URLs per room with a subset of `message`, `state`,
`playlist`, `member`. Each delivery is a POST:

```
X-WatchRoom-Event: message
X-WatchRoom-Signature: sha256=<hex HMAC-SHA256 of the raw body, keyed with the webhook secret>

{ "id": "evt_…", "event": "message", "roomId": "quiet-otter-41", "at": 1790280000000, "data": { …message… } }
```

Answer 2xx within 2 s. Ten consecutive failures remove the webhook. Deliveries are
synchronous with the write that caused them, so a slow endpoint slows that one request by
at most the timeout. Private and loopback addresses are refused (SSRF guard), redirects
are not followed.

### Rate limits and sizes

5 messages / 5 s per member · 10 playlist additions / minute per member · 500-character
messages · 32-character names · 200 playlist items · 5 webhooks per room.

### Deployment settings (environment variables)

| Variable | Effect |
|---|---|
| `WATCHROOM_API_KEY` | When set, `POST /v1/rooms` requires `X-Api-Key`. The web page is unaffected. |
| `WATCHROOM_CORS_ORIGINS` | Comma-separated origins allowed to call the API cross-site **and** to embed the player in an iframe (`frame-ancestors`). |
| `WATCHROOM_SSE_SECONDS` | Length of one event-stream window (5–120, default 25). |
| `WATCHROOM_DEFAULT_SRC` | First item of every new room (default: the demo YouTube playlist). |

## JavaScript SDK

```js
import { WatchRoomClient } from './assets/sdk.js';   // browser or Node 18+

const room = await WatchRoomClient.create({ base: 'https://example.com/video-chat-player/api.php', name: 'Bot', src: 'https://youtu.be/qqwhjSzFJqY' });
console.log(room.inviteUrl);                      // share this

room.on('message', (m) => console.log(`${m.name} @ ${m.mediaTime}s: ${m.text}`));
room.on('state',   (s) => console.log(s.playing ? 'playing' : 'paused', room.expectedPosition()));
room.on('members', ({ members }) => console.log(members.filter((m) => m.online).map((m) => m.name)));
const stop = room.subscribe();                    // SSE in browsers, polling in Node; returns a stop function

await room.send('hello');                         // stamps the current shared position automatically
await room.add('https://example.com/trailer.mp4');
await room.play(0);   await room.pause();   await room.seek(90);   await room.rate(1.25);
await room.jump(room.playlistCache.items[1].id);
await room.repeat('all');   await room.shuffle(true);   // playlist modes
await room.add('https://www.youtube.com/playlist?list=PL…');   // one item that plays the whole list
await room.addExpanded('https://www.youtube.com/playlist?list=PL…');   // ids for playlist/import instead
await room.settings({ guestsControl: false });    // host only
await room.addWebhook('https://hooks.example.com/room', ['message', 'state']);

// Joining an existing room, and rejoining as the same member later:
const me = await WatchRoomClient.join({ base, roomId: 'quiet-otter-41', name: 'Sam' });
const again = await WatchRoomClient.join({ base, roomId: 'quiet-otter-41', name: 'Sam', memberId: me.memberId });
```

Every method rejects with `WatchRoomError { code, status, body }`. `setState` (and
`play/pause/seek/rate`) retries once automatically when the server answers `stale`.

A complete bot lives in `bin/bot-example.mjs`:

```bash
node video-chat-player/bin/bot-example.mjs https://example.com/video-chat-player/api.php quiet-otter-41
```

## Embedding the player in another site

```html
<div id="box"></div>
<script src="https://example.com/video-chat-player/assets/embed.js"></script>
<script>
  const room = WatchRoom.embed(document.getElementById('box'), {
    base: 'https://example.com/video-chat-player/', room: 'quiet-otter-41', name: 'Sam',
  });
  room.on('message', (m) => console.log(m.name, m.text));
  room.on('time', ({ time, duration }) => progress.value = time / duration);
  document.getElementById('pause').onclick = () => room.pause();
  const snapshot = await room.snapshot();   // room, members, playing, time, item, playlist
</script>
```

Commands: `play`, `pause`, `toggle`, `seek {seconds}`, `volume {value}`, `mute {muted}`,
`fullscreen {on}`, `chat {on}`, `send {text}`, `add {url}`, `jump {itemId}`, `next`,
`previous`, `repeat {mode}`, `shuffle {on}`, `reveal`, `snapshot`. Events: `ready`, `play`, `pause`, `ended`, `seeked`,
`time` (once a second), `error`, `message`, `playlist`, `item`, `members`, `fullscreen`,
`overlay`. Add `embed: false`-style options: `autoplay`, `compact` (hides the room bar and
rail), `src` (first item for a new room), `width`, `aspect`.

The host page's origin must be listed in `WATCHROOM_CORS_ORIGINS`; otherwise the player
refuses to be framed (`frame-ancestors`) and ignores commands. Same-origin pages need
nothing.

## Checks

```bash
php tests/video-chat-player-api-contract.php       # routing, auth, codes, OpenAPI ↔ router, webhooks, SSE format
php video-chat-player/bin/selftest.php             # includes REST routing and auth
node video-chat-player/bin/check-api.mjs http://127.0.0.1:8082/video-chat-player/   # SDK, stream, embed bridge
```
