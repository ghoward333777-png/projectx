# Watch Room

A video player with a chat overlay that floats over the picture and hides itself when
nobody is touching the mouse or keyboard. Plays MP4 files, YouTube videos and YouTube
playlists; everyone in a room watches the same moment and chats over the action, in the
page and in full screen. Same stack as the rest of the repository: PHP 8.1+, no Composer,
no database, no API keys, no build step.

The design lives in [DESIGN.md](DESIGN.md). All seven build steps of its section 13 are
implemented, plus the API layer ([API.md](API.md)) and the WordPress and Joomla packages
([INTEGRATIONS.md](INTEGRATIONS.md)).

## Run

```bash
# from the repository root
php -S 127.0.0.1:8082
# open http://127.0.0.1:8082/video-chat-player/index.php
```

Opening the page creates a room and puts its id in the address bar; share that link.
The page plays the bundled `media/sample.mp4` first (a public sample MP4 if that file is
missing). Add any https link ending in `.mp4`, `.webm` or `.m4v`, any YouTube video or
playlist link, or files dropped into `video-chat-player/media/`. Files in `media/` stream
through `media.php`, which honours byte ranges so seeking works even on PHP's built-in
server. `media/` (except the sample) and `rooms/` are ignored by git.

For the event stream during local development start PHP with workers:
`PHP_CLI_SERVER_WORKERS=4 php -S 127.0.0.1:8082`.

## Rooms

Rooms are folders under `rooms/` and are removed after 24 h without activity (configurable).
The creator is the host: only the host reorders or removes playlist items and changes the
room settings (guests may pause and seek for everyone; chat docked under the picture for
YouTube; the YouTube engine). When the host is away, the earliest-joined online member
acts as host automatically, so auto-advance and sync never stall.

Keys: Space/K play · ← → 5 s (Shift 15 s) · J/L 10 s · ↑↓ volume · M mute · F full
screen · C chat on/off · Enter, T or / to type · Esc stop typing · N/P next/previous.
The overlay hides after 3 s without mouse or keys (`?idle=` 1500–10000 ms) and never
hides while you type, hold a draft, hover it, or pause.

## YouTube without YouTube's API

Under the default **Auto** engine a YouTube item is a plain embed iframe that the app
drives over `postMessage`: no YouTube script on the page, no API key, no quota. A YouTube
playlist link is one item; the embed's own next/previous move inside it (N and P keys),
and the room advances when the list ends. If an embed never answers or never starts, the
app falls back to YouTube's IFrame Player API once, and the host can pin either engine in
Host settings.

The playlist has repeat (off, one, all) and shuffle with a shared order, accepts many
links pasted at once, shows thumbnails fetched without any API, and can be saved and
reloaded in the browser ("My playlists"). Playback follows an explicit state machine
(idle → loading → ready → playing ⇄ paused/buffering → ended, error from anywhere) that
the health panel watches.

A video whose uploader disabled embedding (YouTube error 150, common for full-movie
uploads such as https://youtu.be/qqwhjSzFJqY) cannot play in any embedded player. The app
says so within a second, offers "Open on YouTube", marks the item and moves on.

YouTube's API terms restrict overlaying content on the embedded player. The room setting
"Chat under the picture for YouTube (docked)" moves the chat into a band beneath the
picture, still inside full screen, for rooms where that matters.

## How it stays up

Every subsystem reports into the **System** list on the right, and every failure has an
automatic response before anyone sees a blank frame:

| What can go wrong | What the app does |
|---|---|
| A file will not play | Retries once with a fresh request, then marks the item for everyone and moves to the next one with an "Up next" card. |
| YouTube is blocked in this window, or a video is region-locked, private, or not embeddable | Reports the exact reason, marks the item, skips it; offers "Open on YouTube"; if nothing else can play, offers to open the room in a normal browser tab. |
| A YouTube embed answers but never starts | 12 s start timeout, one engine fallback (API-free embed ⇄ IFrame API), then mark and skip. |
| Playback stalls for 8 s while "playing" | The watchdog reloads at the same position; a second stall marks the item and skips it. |
| The browser refuses autoplay with sound | A "Tap to play" card; the shared clock is applied after the tap. |
| The connection drops | Chat and sync pause with a visible status, messages queue in an outbox and send when the network returns; polling backs off and recovers by itself. |
| The server is unreachable at load | Solo mode: the video plays anyway (resuming where this browser left off) and the page keeps trying to join every 5 s. |
| A room link has expired | A fresh room is started and the viewer is told. |
| The host leaves | The earliest-joined online member becomes the acting host. |
| Two people change playback at once | The server refuses the stale write (409) and the loser adopts the winner's state. |
| Full screen is refused (phones, some panels) | Fixed-position fallback that fills the window. |
| Storage is blocked (private mode) | Names, volume and saved playlists are simply not remembered; nothing breaks. |
| Someone floods the chat or the playlist | Rate limits: 5 messages / 5 s, 30 additions / minute, 500-character messages, 200 items. |

Server-side, `api.php?action=health` and `php video-chat-player/bin/selftest.php` run the
same checks (PHP version, extensions, rooms folder writable, disk space, outbound https)
plus a full room round trip in a temporary folder.

## API

A REST API (`api.php/v1/…`, OpenAPI at `api.php/v1/openapi.json`, reference at
`api-docs.php`), a zero-dependency JavaScript SDK (`assets/sdk.js`) for browsers and Node,
webhooks, a live event stream, and an embed bridge (`assets/embed.js`) for hosting the
player on other sites. All of it is in [API.md](API.md).

## WordPress and Joomla

`php video-chat-player/bin/build-integrations.php` produces a WordPress plugin zip with a
`[watch_room]` shortcode and a Joomla 4/5 module zip, each bundling the whole player. See
[INTEGRATIONS.md](INTEGRATIONS.md).

## Check

```bash
php tests/video-chat-player-contract.php               # resolver, streamer ranges, page shell
php tests/video-chat-player-api-contract.php           # routing, auth, codes, OpenAPI ↔ router, webhooks, SSE
php tests/video-chat-player-integrations-contract.php  # WordPress plugin + Joomla module packaging
php video-chat-player/bin/selftest.php                 # server health + API round trip
node video-chat-player/bin/make-test-media.mjs         # two synthetic 4 s clips (Chromium records them)
node video-chat-player/bin/make-test-media.mjs --long  # one 40 s clip for the sync check
node video-chat-player/bin/check-stage.mjs    http://127.0.0.1:8082/video-chat-player/
node video-chat-player/bin/check-idle.mjs     http://127.0.0.1:8082/video-chat-player/
node video-chat-player/bin/check-chat.mjs     http://127.0.0.1:8082/video-chat-player/
node video-chat-player/bin/check-playlist.mjs http://127.0.0.1:8082/video-chat-player/
node video-chat-player/bin/check-sync.mjs     http://127.0.0.1:8082/video-chat-player/
node video-chat-player/bin/check-api.mjs      http://127.0.0.1:8082/video-chat-player/
node video-chat-player/bin/check-modes.mjs    http://127.0.0.1:8082/video-chat-player/
```

The browser checks drive real Chromium through Playwright. Stage: playback, content rect
for 16:9 and 4:3, overlay inside the picture, full screen parity. Idle: the 3 s hide,
instant reveal, every pin, the keyboard map. Chat: two viewers, round trip, media-time
stamps, peek, unread, rename, offline queueing and recovery, expired-room fallback.
Playlist: adding, auto-advance, broken file retry-then-skip, YouTube failure reported and
skipped, guest permissions. Sync: follow seek/pause/play, guest control on and off, drift
correction, watchdog stall recovery. API: the SDK from Node, the event stream, the embed
bridge. Modes: repeat-all wrap, repeat-one, shared shuffle order, multi-link paste, saved
playlists, YouTube playlist items, the state machine.
