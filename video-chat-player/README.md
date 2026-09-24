# Watch Room

A video player with a chat overlay that floats over the picture and hides itself when
nobody is touching the mouse or keyboard. Same stack as the rest of the repository:
PHP 8.1+, no Composer, no database, no API keys, no build step.

The design lives in [DESIGN.md](DESIGN.md). Build progress against its section 13:

| Step | Scope | Status |
|---|---|---|
| 1 | Stage, HTML5 adapter, content rect, full screen on the stage | done |
| 2 | Idle controller, control bar, keyboard map | – |
| 3 | Rooms and chat | – |
| 4 | YouTube adapter, shield, docked mode | – |
| 5 | Playlists | – |
| 6 | Sync | – |
| 7 | Hardening | – |

## Run

```bash
# from the repository root
php -S 127.0.0.1:8082
# open http://127.0.0.1:8082/video-chat-player/index.php
```

The page plays a public sample MP4 by default. Paste any https link ending in `.mp4`,
`.webm` or `.m4v`, or drop files into `video-chat-player/media/` and pick them from the
menu. `media/` and `rooms/` are ignored by git.

## Check

```bash
php tests/video-chat-player-contract.php          # source resolver + page shell, plain PHP
node video-chat-player/bin/make-test-media.mjs      # two synthetic test videos (Chromium records them)
node video-chat-player/bin/check-stage.mjs http://127.0.0.1:8082/video-chat-player/
```

The browser check drives real Chromium through Playwright: it proves the video plays,
the content rect matches a 16:9 and a 4:3 picture, the overlay sits inside the picture,
and all of it holds in full screen.
