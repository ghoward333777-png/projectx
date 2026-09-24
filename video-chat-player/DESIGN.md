# Watch Room — video player with an overlay chat

*Design document, pass 1. Working name "Watch Room"; rename freely.*

This is the design for the first building block of the new app: a video player that
plays MP4 files, YouTube videos and playlists, with a chat interface that floats over
the bottom of the picture and hides itself when nobody is touching the mouse or
keyboard. It works identically in the normal page layout and in full screen.

It is the successor to the Slo-Mo Dating player. Where that player was loose, this one
is exact: every visibility change has a stated trigger and a stated delay, the overlay
is aligned to the real picture rather than the box around it, and full screen is the
same code path as the normal view rather than a special case.

---

## 1. Goals and non-goals

**Goals (v1)**

1. Play an MP4 (or WebM) from a URL, or from a `media/` folder on the server.
2. Play a YouTube video from any common YouTube URL form.
3. Play playlists: an app playlist that mixes MP4 and YouTube items, and an imported
   YouTube playlist.
4. A chat panel drawn over the bottom of the picture. Multiple people in the same
   "room" see the same messages within about a second.
5. The chat panel hides after a fixed idle period with no mouse, touch or keyboard
   activity, and comes back instantly on any activity. Identical behaviour in the
   standard layout and in full screen.
6. Everyone in a room watches the same moment of the same item (host-driven sync).
7. Same stack as the rest of the repo: PHP 8.1+, no Composer, no database, no API keys,
   no build step. Deploys as a folder on ordinary PHP hosting.

**Non-goals (v1)**

- Video upload, transcoding or storage management (MP4s are referenced by URL or
  dropped in `media/`).
- Accounts, passwords, profiles, matching. A room is a link; a user is a display name.
- Voice or video calls. Text chat only.
- Mobile-native apps. The web page must work on a phone, but the phone is not the
  primary target.
- Monetisation, moderation tooling, recording.

---

## 2. What "more precise" means

The requirement is that this player be "similar to Slo-Mo Dating but more precise". The
design treats precision as four separate promises, each with a measurable definition.

| Promise | Definition | How it is met |
|---|---|---|
| Precise placement | The chat sits over the *picture*, not over the black bars, on every screen shape. | The overlay is positioned against a computed **content rect** (section 6), recalculated on every resize and on every media load. |
| Precise timing | Show/hide has one timer, one set of triggers, one set of exceptions. No flicker, no "stuck open", no "vanished while typing". | A single idle controller with an explicit state machine (section 4.3). |
| Precise parity | Standard mode and full screen behave the same to the pixel. | Full screen is requested on the player **stage** element, never on the `<video>` or the YouTube iframe, so the overlay is inside the fullscreen subtree (section 6.2). |
| Precise sync | Two viewers are within 250 ms of each other after any play, pause or seek. | Host clock with server-time offset and drift correction (section 8). |

---

## 3. User experience

### 3.1 Standard layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Watch Room   [room: quiet-otter-41]  [Copy invite]        name: Greg  [Leave] │
├───────────────────────────────────────────────────────┬──────────────────────┤
│                                                       │ PLAYLIST             │
│                                                       │ ▶ 1. Intro.mp4  3:12 │
│                    (video picture)                    │   2. YouTube: Ocean… │
│                                                       │   3. Trailer.mp4     │
│                                                       │   4. YouTube: Lofi…  │
│ ┌───────────────────────────────────────────────────┐ │                      │
│ │ Ana  2:14  did you see that                       │ │ + Add URL            │
│ │ Greg 2:16  yes!! rewind                           │ │ + Import YT playlist │
│ │ ┌───────────────────────────────────────────┐     │ │                      │
│ │ │ Say something…                            │ ⏎   │ │                      │
│ │ └───────────────────────────────────────────┘     │ │                      │
│ └───────────────────────────────────────────────────┘ │                      │
│ ▶  ━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━  2:16 / 3:12  🔊 ⛶ │                      │
└───────────────────────────────────────────────────────┴──────────────────────┘
```

- The **stage** (picture + chat overlay + control bar) keeps a 16:9 box in the page,
  letterboxing the picture inside it when the media is a different shape.
- The **playlist rail** is on the right at widths ≥ 1024 px and collapses below the
  stage on narrower screens.
- The **chat overlay** and **control bar** are two layers of the stage, both governed
  by the same idle controller.

### 3.2 Full screen

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                                                                              │
│                              (video picture)                                 │
│                                                                              │
│                                                                              │
│      ┌────────────────────────────────────────────────────────────────┐      │
│      │ Ana  2:14  did you see that                                    │      │
│      │ Greg 2:16  yes!! rewind                                        │      │
│      │ ┌──────────────────────────────────────────────────────┐       │      │
│      │ │ Say something…                                       │  ⏎    │      │
│      │ └──────────────────────────────────────────────────────┘       │      │
│      └────────────────────────────────────────────────────────────────┘      │
│  ▶  ━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2:16 / 3:12  🔊 ⛶   │
└──────────────────────────────────────────────────────────────────────────────┘
```

Same DOM, same CSS, same controller. The only differences are that the stage fills the
screen and the playlist rail is hidden (it is reachable via the `L` key as a temporary
drawer over the right edge; it obeys the same idle timer).

### 3.3 Chat overlay anatomy

```
┌─ overlay (max-width 720 px, centred, bottom-anchored to the content rect) ───┐
│  message list: last 5 messages visible, older reachable by scroll             │
│    ┌ avatar-dot ┐ name  hh:mm:ss(media)  text ……………………………………………………           │
│  composer: single-line input (grows to 3 lines), send button, typing hint     │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Background**: semi-transparent dark glass (`rgba(10,10,14,.55)` + 12 px blur),
  never a solid block, so the action underneath stays visible.
- **Message height budget**: the list never exceeds 32 % of the content-rect height.
  On a 1080p full screen that is about 5 lines; on a phone in landscape about 3.
- **Media time stamp**: every message shows the video time it was sent at (e.g. `2:14`),
  not the wall-clock time. Clicking the stamp seeks the video there. This is the one
  feature that makes a watch-together chat useful and it was missing before.
- **Own messages** align right with a lighter glass; others align left.
- **System lines** (joined, left, changed item, seeked to 1:20) are 80 % opacity and
  italic, and do not count toward the 5-line budget.

### 3.4 Overlay visibility rules

Written as a contract so the implementation and the tests agree.

| Rule | Value |
|---|---|
| Idle timeout | **3000 ms** in both modes (configurable 1500–10000 in settings). |
| Activity events | `pointermove`, `pointerdown`, `wheel`, `touchstart`, `keydown` on the stage; `focus` on any control. |
| Reveal latency | ≤ 1 frame. Reveal is a class toggle; no reveal animation. |
| Hide animation | 220 ms opacity + 8 px downward drift. Pointer events are off during the fade so an accidental hover cannot re-open it. |
| Never hide while | the composer has focus, **or** the composer holds unsent text, **or** the pointer is over the overlay, **or** playback is paused, **or** a modal (settings, add-URL) is open. |
| New incoming message while hidden | The overlay does **not** fully open. The new message alone "peeks": it is shown for 4000 ms at 85 % opacity in the message slot, then fades. Pressing any key or moving the mouse promotes the peek to a full reveal. |
| Mouse leaves the stage | Hide timer shortened to 1000 ms. |
| Cursor | Hidden together with the overlay while playing; restored on reveal. |
| Touch devices | A tap on the picture toggles the overlay (no hover). The idle timer is 5000 ms. |

Idle controller state machine:

```
             activity                       timeout (3 s)
  HIDDEN ─────────────▶ VISIBLE ───────────────────────────▶ FADING ──220 ms──▶ HIDDEN
     ▲                    │  ▲                                  │
     │   activity         │  │ activity (restarts timer)        │ activity
     └────────────────────┘  └──────────────────────────────────┘
                              │
                              │ pinned (composer focus / draft / hover / paused / modal)
                              ▼
                           PINNED  ── unpinned ──▶ VISIBLE (timer restarts)

  PEEK is a sub-state of HIDDEN: the message list alone is shown; activity ⇒ VISIBLE.
```

Everything that can show or hide the overlay goes through this one object. The control
bar subscribes to the same state; nothing else touches visibility classes.

### 3.5 Keyboard map

Global shortcuts apply when the composer is **not** focused.

| Key | Action |
|---|---|
| `Space`, `K` | Play / pause |
| `←` / `→` | Seek −5 s / +5 s (`Shift` = 15 s) |
| `J` / `L` | Seek −10 s / +10 s |
| `↑` / `↓` | Volume ±5 % |
| `M` | Mute |
| `F` | Toggle full screen |
| `N` / `P` | Next / previous playlist item |
| `Enter`, `T`, `/` | Focus the composer (and reveal the overlay) |
| `C` | Toggle chat overlay on/off entirely (a "cinema" mode; a small dot in the corner shows unread count) |
| `Esc` | Blur the composer; if already blurred, exit full screen |

Inside the composer: `Enter` sends, `Shift+Enter` newline, `Esc` blurs, `↑` recalls
your last message for editing. All other keys type. Shortcuts never fire while typing.

### 3.6 Playlist behaviour

- Items advance automatically on end; the transition shows a 5-second "Up next" card
  in the overlay slot with a **Cancel** button.
- Any participant can add items; only the host can reorder, remove or jump.
- YouTube playlist import (`?list=…`) expands to individual items so the app treats
  every source the same way (section 9).
- The current item is highlighted; items that failed to load show a red dot and a
  reason (`blocked by owner`, `404`, `not embeddable`).

---

## 4. Architecture

### 4.1 Stack

- **Backend**: PHP 8.1+, plain files, no Composer, no database. Rooms are folders.
- **Frontend**: vanilla ES modules, one CSS file, no framework, no bundler. The only
  external script is YouTube's IFrame Player API, loaded lazily when the first YouTube
  item is queued.
- **Transport**: HTTP short-polling with a cursor (section 7.3). Chosen over WebSockets
  because the target hosting cannot run a long-lived process, and over SSE because PHP's
  built-in dev server is single-threaded and SSE would block it.

### 4.2 File layout

```
video-chat-player/
├── DESIGN.md                    ← this document
├── index.php                    ← page shell; creates/joins a room
├── api.php                      ← JSON endpoints (section 7.2)
├── lib/
│   ├── RoomStore.php            ← create/open rooms, locking, GC
│   ├── MessageLog.php           ← append-only JSONL messages + cursor reads
│   ├── PlaybackState.php        ← host clock state, atomic write
│   ├── Playlist.php             ← item model, URL parsing, YouTube ID extraction
│   ├── YouTubeMeta.php          ← oEmbed title/thumbnail lookup (no API key)
│   └── Http.php                 ← JSON response helpers, rate limit, CSRF token
├── assets/
│   ├── app.js                   ← boot, wiring, settings
│   ├── stage.js                 ← stage element, content-rect maths, fullscreen
│   ├── idle.js                  ← the idle controller (section 3.4)
│   ├── overlay.js               ← chat overlay DOM + peek behaviour
│   ├── chat.js                  ← polling client, message model, composer
│   ├── controls.js              ← control bar, keyboard map
│   ├── playlist.js              ← rail UI + playlist client
│   ├── sync.js                  ← host clock, drift correction
│   ├── player/
│   │   ├── adapter.js           ← the interface (section 5)
│   │   ├── html5.js             ← <video> adapter
│   │   └── youtube.js           ← IFrame API adapter
│   └── styles.css
├── rooms/                       ← runtime data, one folder per room (gitignored)
└── media/                       ← optional local MP4s (gitignored)

tests/
└── video-chat-player-contract.php   ← PHP contract tests (section 12)
```

The player is self-contained under `video-chat-player/` and does not touch the book
studio. It is deliberately **not** added to `SitePackageExporter::FILES`; it ships as
its own folder and gets its own hosting zip later if wanted.

### 4.3 Module responsibilities

| Module | Owns | Talks to |
|---|---|---|
| `stage.js` | the stage element, content rect, fullscreen toggle, resize observer | adapters (for `videoWidth/Height`), overlay, controls |
| `idle.js` | visibility state machine and timers | overlay, controls, cursor |
| `overlay.js` | rendering messages, peek, composer | idle (pin/unpin), chat |
| `chat.js` | polling loop, cursor, outbox, retry | api.php |
| `sync.js` | applying host state, publishing host state, drift correction | adapters, api.php |
| `playlist.js` | rail UI, add/import dialogs, current index | api.php, sync |
| `controls.js` | control bar, keyboard map, seek bar scrubbing | adapters, stage, idle |
| `player/*.js` | one uniform API over two very different players | nothing else |

One rule keeps this tidy: **modules never reach into each other's DOM**. They talk
through a tiny event bus (`bus.on('player:time', …)`).

---

## 5. Player adapters

Both players are hidden behind one interface so the overlay, controls, sync and
playlist never know which one is active.

```js
// player/adapter.js
export class PlayerAdapter {
  /** Load an item; resolves when metadata is known. */
  async load(item) {}
  play() {}  pause() {}  seek(seconds) {}
  currentTime() {}  duration() {}
  setVolume(v) {}  setMuted(m) {}  setRate(r) {}
  /** Natural picture size, or null until known. */
  pictureSize() { return { width, height } }
  /** Events: 'ready' 'play' 'pause' 'timeupdate' 'seeked' 'ended' 'error' 'buffering' */
  on(event, fn) {}
  destroy() {}
  /** Capability flags the UI reads (section 5.3). */
  get caps() {}
}
```

### 5.1 HTML5 adapter (`html5.js`)

- Wraps one `<video playsinline preload="metadata">` element with native controls off.
- `pictureSize()` comes from `videoWidth` / `videoHeight` once `loadedmetadata` fires.
- Sources: any `https://` URL with an `mp4`/`webm`/`m4v` extension, or
  `media/<file>` on the server. CORS is not required for playback, only for captions.
- `timeupdate` is too coarse (≈ 4 Hz), so the adapter emits its own `time` event from
  `requestAnimationFrame` while playing. The overlay's message stamps and the seek bar
  read that.

### 5.2 YouTube adapter (`youtube.js`)

- Loads `https://www.youtube.com/iframe_api` once, resolves `onYouTubeIframeAPIReady`.
- Creates the player with `controls: 0, rel: 0, modestbranding: 1, fs: 0,
  playsinline: 1, enablejsapi: 1, origin: location.origin`. `fs: 0` removes YouTube's
  own fullscreen button, which would put only the iframe into full screen and lose the
  overlay. Our `F` key and ⛶ button drive full screen on the stage instead.
- `currentTime()` polls `getCurrentTime()` at 10 Hz while playing (the API has no
  event for time).
- `pictureSize()` is assumed 16:9 unless oEmbed returns a different `width`/`height`.
  YouTube renders its own letterboxing inside the iframe for non-16:9 videos, so the
  iframe itself is sized to the 16:9 box and the overlay aligns to that.
- State mapping: `PlayerState.PLAYING → play`, `PAUSED → pause`, `BUFFERING →
  buffering`, `ENDED → ended`. `onError` codes 101/150 map to `not embeddable`.

**Pointer events and the iframe.** The browser delivers mouse events inside the iframe
to YouTube, not to our page, so the idle controller would never see movement over the
picture. The adapter therefore places a transparent **shield** `<div>` over the iframe.
The shield forwards a click to play/pause and a double-click to full screen, and lets
`pointermove` reach the stage. This is what makes the auto-hide behave identically over
MP4 and YouTube.

**Terms note (decision required before launch).** YouTube's API Services terms restrict
placing content over the embedded player and disabling its controls. The shield and the
overlay both do that. This design keeps the behaviour the user asked for (chat over the
action) as the default and adds a per-room switch, `chatMode: "overlay" | "docked"`.
In *docked* mode the YouTube iframe is shortened by the overlay's height so the chat
sits in a band directly under the picture, still inside the fullscreen stage, and the
shield is removed. MP4 items are unaffected. Confirm which default you want before
public release; the code cost of keeping both is small (one CSS class).

### 5.3 Capability flags

| cap | HTML5 | YouTube | Read by |
|---|---|---|---|
| `preciseTime` (≥ 30 Hz) | yes | no (10 Hz) | seek bar smoothing |
| `rate` | yes | yes (fixed set) | speed menu |
| `captions` | via `<track>` | via `cc_load_policy` | CC button |
| `seekWhilePaused` | yes | yes | sync |
| `nativeShield` | no | yes | stage (adds the shield layer) |
| `autoplayNeedsGesture` | yes | yes | first-play prompt |

---

## 6. Stage geometry and full screen

### 6.1 The content rect

The stage is a 16:9 box; the picture inside it may be a different shape. The overlay
must sit over the picture. `stage.js` computes:

```
stageW, stageH        = stage element size (ResizeObserver)
picW, picH            = adapter.pictureSize() or 16:9 fallback
scale                 = min(stageW / picW, stageH / picH)
contentW, contentH    = picW * scale, picH * scale
contentX, contentY    = (stageW - contentW) / 2, (stageH - contentH) / 2
```

and writes them as CSS custom properties on the stage:
`--content-x`, `--content-y`, `--content-w`, `--content-h`. The overlay is positioned
purely from those variables:

```css
.overlay {
  left:   calc(var(--content-x) + 16px);
  width:  min(720px, calc(var(--content-w) - 32px));
  bottom: calc(var(--content-y) + var(--controls-h) + 12px);
}
```

Recomputed on: resize, orientation change, fullscreen change, `loadedmetadata`,
playlist item change. Never on a timer.

### 6.2 Full screen on the stage, not the player

`stage.requestFullscreen()` (with the `webkit` fallback for Safari, and the
`navigator.standalone`/iOS fallback of a fixed-position pseudo-fullscreen when the API
is unavailable). Because the overlay, control bar and shield are children of the stage,
they are inside the fullscreen subtree and keep working. In full screen the stage is
`100vw × 100vh`, so the content rect maths handles the letterboxing exactly as in the
page.

On `fullscreenchange` the stage recomputes the content rect, the idle controller gets a
fresh `activity()` tick (so the overlay is visible for the first 3 s), and the playlist
rail is detached from layout.

### 6.3 Layers (z-order, bottom to top)

1. picture (`<video>` or iframe)
2. shield (YouTube only)
3. "Up next" / error / first-play cards
4. control bar
5. chat overlay
6. modals (settings, add URL, import playlist)

---

## 7. Chat and rooms

### 7.1 Data model

```
Room {
  id: "quiet-otter-41",             // 2 words + 2 digits, from a wordlist, URL-safe
  createdAt, hostToken, chatMode,
  members: { [memberId]: { name, colour, lastSeen } }
}

Message {
  seq: 1042,                        // monotonic per room, the polling cursor
  id: "m_7f3a…",                    // client-generated, for dedupe/retry
  memberId, name, colour,
  text: "did you see that",         // ≤ 500 chars, plain text
  mediaTime: 134.2,                 // seconds into the current item
  itemId: "p_3",                    // playlist item it refers to
  sentAt: 1758700000123,            // server ms
  kind: "chat" | "system"
}

PlaybackState {                     // written only by the host
  itemId, playing: bool,
  mediaTime: 134.2,                 // position at `at`
  at: 1758700000123,                // server ms when mediaTime was true
  rate: 1.0, rev: 57                // rev increments on every change
}

PlaylistItem {
  id: "p_3", kind: "mp4" | "youtube",
  src: "https://…/file.mp4" | "dQw4w9WgXcQ",
  title, durationSec, thumb, addedBy, status: "ok" | "error", error?
}
```

On disk, per room:

```
rooms/quiet-otter-41/
├── room.json         atomic write (tmp + rename)
├── playlist.json     atomic write
├── state.json        atomic write, rev-guarded
└── messages.jsonl    append-only, one JSON object per line, flock(LOCK_EX) on append
```

Rooms idle for 24 h are removed by an opportunistic GC in `api.php` (1-in-50 requests).

### 7.2 API (`api.php`, JSON in/out)

| `action` | Method | Body | Returns |
|---|---|---|---|
| `room.create` | POST | `{ name }` | `{ room, memberId, hostToken }` |
| `room.join` | POST | `{ roomId, name }` | `{ room, memberId, playlist, state, since }` |
| `chat.send` | POST | `{ roomId, memberId, id, text, mediaTime, itemId }` | `{ seq }` |
| `sync.poll` | GET | `roomId, memberId, since, rev` | `{ messages[], state?, playlist?, members[] , serverTime }` |
| `state.set` | POST | `{ roomId, hostToken, state }` | `{ rev }` |
| `playlist.add` | POST | `{ roomId, memberId, url }` | `{ item }` (title resolved via oEmbed for YouTube) |
| `playlist.import` | POST | `{ roomId, memberId, listUrl }` | `{ items[] }` |
| `playlist.set` | POST | `{ roomId, hostToken, order[], current }` | `{ playlist }` |

One poll returns everything that changed: messages after `since`, the playback state if
its `rev` is newer than the client's, the playlist if its revision moved, and a
`serverTime` for clock offset. One request per tick keeps the hosting happy.

### 7.3 Polling loop (`chat.js`)

- Tick every **1000 ms** while the tab is visible and the room has ≥ 2 members;
  **2500 ms** when alone; **5000 ms** when the tab is hidden.
- The tick after a local send is immediate.
- Requests carry an `If-None-Match`-style `since`/`rev` pair; an unchanged room returns
  `204` with no body, which costs a few hundred bytes.
- Outbox: a send that fails is retried with backoff (1, 2, 4 s) using the same client
  `id`; the server ignores duplicate ids, so retries never double-post.
- Pending messages render immediately in the overlay with a faint "sending" state and
  are reconciled by `id` when the poll returns them.

Measured latency budget: one tick + one request ≈ 1.1 s median between two viewers.
That is "chat" precision, not "typing indicator" precision; typing indicators are
deliberately left out.

---

## 8. Playback sync

- The room creator is the **host**; their client is the only writer of
  `PlaybackState`. Host status can be handed to another member (`room.json`).
- Every client keeps `offset = serverTime − localTime` from poll responses (median of
  the last 5).
- Expected position at any instant: `mediaTime + (now + offset − at) × rate` while
  playing, `mediaTime` while paused.
- On receiving a newer `rev`, a guest applies play/pause and seeks if the difference to
  the expected position exceeds **250 ms**. While playing, guests correct small drift
  (250 ms–1.5 s) by nudging `rate` to 0.95/1.05 for a few seconds rather than seeking,
  which is invisible; larger drift seeks.
- The host publishes state on `play`, `pause`, `seeked`, `ratechange`, item change, and
  as a heartbeat every 10 s.
- Guest controls are enabled by default (anyone can pause for everyone); this is a room
  setting `guestsControl: true|false`. When false, guest controls are shown disabled with
  a tooltip.
- YouTube's 10 Hz clock plus iframe latency means the practical sync target for YouTube
  is 500 ms; the 250 ms figure applies to MP4.

---

## 9. Playlists and URL handling

`Playlist.php` recognises, in this order:

1. `youtube.com/playlist?list=…`, `…/watch?v=…&list=…` → **YouTube playlist import**.
2. `youtube.com/watch?v=ID`, `youtu.be/ID`, `youtube.com/shorts/ID`,
   `youtube.com/embed/ID`, `youtube.com/live/ID` → **YouTube item** (11-char ID).
3. `https://…/*.mp4|.webm|.m4v` → **MP4 item** (HEAD request to confirm reachability
   and read `Content-Length`; failure records `status: error`).
4. `media/<name>.mp4` present on disk → **MP4 item**.
5. Anything else → rejected with a clear message.

**Titles without an API key.** YouTube's oEmbed endpoint
(`https://www.youtube.com/oembed?url=…&format=json`) returns title, author and thumbnail
for a single video and needs no key. `YouTubeMeta.php` calls it server-side with a 3 s
timeout and caches results in `rooms/_cache/yt-<id>.json`. Playlist *contents* are not
available from oEmbed; import uses the IFrame API in the browser: the host's adapter
calls `cuePlaylist({ list })`, reads `getPlaylist()` for the video IDs, and posts them
to `playlist.import`, which then resolves titles. This keeps the "no API key" promise
at the cost of playlist import being a host-side (browser) action. The known limit is
YouTube's 200-item cap per cued playlist.

---

## 10. Security and privacy

- Room IDs are unguessable enough for a private link (≈ 2 × 10⁶ combinations per
  wordlist pair, plus the two digits) and are never listed anywhere.
- `hostToken` is a 32-byte random hex, stored in the host's `localStorage`, sent only
  on host actions, never echoed to guests.
- Every string from a client is stored as plain text and HTML-escaped at render time
  (`textContent`, never `innerHTML`). Message text ≤ 500 chars, name ≤ 32 chars.
- Rate limits per member: 5 messages / 5 s, 10 playlist adds / minute, 1 poll / 500 ms.
  Excess returns `429`.
- Server-side fetches (oEmbed, MP4 HEAD) only follow `https://` to public hosts; private
  and loopback ranges are refused (SSRF guard).
- CSP: `default-src 'self'; frame-src https://www.youtube.com https://www.youtube-nocookie.com;
  script-src 'self' https://www.youtube.com; media-src https: 'self'; img-src https: data:`.
- No cookies except the PHP session; no analytics; nothing leaves the server except
  the two YouTube calls above.

---

## 11. Accessibility

- The overlay is `role="log" aria-live="polite"`; the composer is a labelled textbox.
- Auto-hide never hides *focus*: if keyboard focus is inside the stage the overlay is
  pinned, so keyboard users are never typing into an invisible box.
- Control bar buttons have names, states and a 44 px hit target.
- `prefers-reduced-motion` removes the fade drift.
- Message colours (per member) pass 4.5:1 against the glass background; names are
  shown in text, so colour is never the only distinguisher.

---

## 12. Testing plan

**PHP contract test** (`tests/video-chat-player-contract.php`, runs with plain `php`):

- URL parsing table: every YouTube URL form, MP4 URLs with query strings, rejections.
- `MessageLog`: append under concurrent `flock`, cursor reads, duplicate-id rejection.
- `PlaybackState`: rev guard refuses stale writes; expected-position maths.
- `RoomStore`: create, join, GC of an aged room, host-token checks.
- `Http`: rate limiter windows, SSRF guard, CSP header presence.

**Browser checks** (Playwright, run from the pre-installed Chromium; not part of `php`
tests but scripted in `bin/check-player.js` later):

- Overlay hides at 3.0 s ± 50 ms and reveals on `mousemove`, in page and in full screen.
- Overlay stays while the composer has text.
- Content rect: 4:3 MP4 inside the 16:9 stage puts the overlay over the picture.
- Two contexts in one room: message round-trip ≤ 1.5 s; host seek applied on guest
  within 250 ms of expected position (MP4).
- YouTube: shield forwards click to play/pause; auto-hide behaves identically.

**Determinism**: the same message log and state file always render the same overlay,
and the same URL always parses to the same item. No randomness outside room IDs.

---

## 13. Build plan

Each step is a working, demoable increment.

1. **Stage + HTML5 adapter + content rect + full screen on the stage.** An MP4 plays,
   the overlay box (empty) sits over the picture in both modes.
2. **Idle controller + control bar + keyboard map.** Auto-hide contract from 3.4 passes
   in the browser checks.
3. **Rooms + chat.** `api.php`, `MessageLog`, polling client, composer, peek behaviour,
   media-time stamps that seek.
4. **YouTube adapter + shield + docked mode switch.**
5. **Playlists.** Add URL, mixed items, auto-advance, "Up next" card, YouTube playlist
   import via `getPlaylist()`.
6. **Sync.** Host clock, drift correction, guest controls setting.
7. **Hardening.** Rate limits, SSRF guard, GC, CSP, accessibility pass, contract tests
   green, README section.

Steps 1–3 are the minimum that proves the concept end to end.

---

## 14. Decisions to confirm

1. **YouTube chat placement default**: overlay (as requested) or docked, given the
   terms note in 5.2. The design ships both behind one switch.
2. **Guest controls**: anyone can pause/seek for the room (default here), or host-only.
3. **Idle timeout**: 3 s is the default; say if you want it longer for slow chatting.
4. **Room lifetime**: 24 h after last activity, then deleted. Say if rooms should
   persist longer or be pinned.
5. **Local media folder**: keep `media/` support (handy for testing and for your own
   files) or go URL-only.
