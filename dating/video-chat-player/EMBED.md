# Embedding Watch Room in another project

Watch Room is a PHP folder. Host it anywhere PHP 8.1 runs, then any other project, site,
or Claude project embeds it through one endpoint.

## 1. Host the player

Copy `video-chat-player/` to a PHP host (or unzip `dist/watch-room-embed.zip`, built by
`php video-chat-player/bin/build-integrations.php`). Two settings matter:

| Setting | Value for embedding |
|---|---|
| `WATCHROOM_CORS_ORIGINS` | The origin(s) of the pages that will frame the player, e.g. `https://myproject.example`. Use `*` to let any page embed and drive it. |
| `WATCHROOM_DEFAULT_SRC` | First item of every new room (default: the demo playlist). |

Set them as environment variables or in a `local-config.php` next to `config.php`:

```php
<?php
return ['cors_origins' => ['*']];
```

Check it is alive: `https://HOST/video-chat-player/api.php/v1/health`.

## 2. The embed endpoint

```
https://HOST/video-chat-player/embed.php
```

| Parameter | Meaning |
|---|---|
| `room` | Join an existing room, e.g. `quiet-otter-41`. Omit to start a new room. |
| `src` | First item of a new room: a YouTube video or playlist link, an https `.mp4`/`.webm`, or `media/<file>`. |
| `name` | The viewer's display name. |
| `chat=0` | Hide the chat. |
| `autoplay=0` | Wait for a tap instead of starting. |
| `idle` | Overlay hide delay in ms (1500–10000, default 3000). |
| `compact=0` | Show the full page with the playlist rail instead of the stage only. |
| `format=json` | Return a descriptor instead of the page: snippet, endpoints, allowed embedders. |

Minimal embed, no JavaScript needed:

```html
<iframe src="https://HOST/video-chat-player/embed.php?room=quiet-otter-41&name=Sam"
        allow="autoplay; fullscreen; clipboard-write" allowfullscreen
        style="border:0;width:100%;aspect-ratio:16/9"></iframe>
```

## 3. Drive it from the host page

```html
<div id="player"></div>
<script src="https://HOST/video-chat-player/assets/embed.js"></script>
<script>
  const room = WatchRoom.embed(document.getElementById('player'), {
    base: 'https://HOST/video-chat-player/', room: 'quiet-otter-41', name: 'Sam',
  });
  room.on('message', (m) => console.log(m.name, m.text));
  room.on('time', ({ time, duration }) => { /* progress */ });
  await room.play();  await room.pause();  await room.seek(90);
  await room.send('hello');  await room.add('https://youtu.be/…');
  const snap = await room.snapshot();   // room, members, playing, time, item, playlist
</script>
```

Commands: `play`, `pause`, `toggle`, `seek`, `volume`, `mute`, `fullscreen`, `chat`, `send`,
`add`, `jump`, `next`, `previous`, `repeat`, `shuffle`, `reveal`, `snapshot`.
Events: `ready`, `play`, `pause`, `ended`, `seeked`, `time`, `error`, `message`, `playlist`,
`item`, `members`, `fullscreen`, `overlay`.

## 4. Create rooms from your own code

```bash
curl -X POST https://HOST/video-chat-player/api.php/v1/rooms \
     -H 'Content-Type: application/json' \
     -d '{"name":"My project","src":"https://www.youtube.com/playlist?list=PLQ4K0DlePpSMMZXjwWGilHyefFENRUgOy"}'
# → {"room":{"id":"quiet-otter-41"},"memberId":"m_…","hostToken":"…",…}
```

Then embed `embed.php?room=quiet-otter-41`. The full REST API, event stream, webhooks
and the Node/browser SDK are in [API.md](API.md).

## 5. oEmbed (automatic embedding)

Platforms that understand oEmbed can turn a Watch Room link into the player by asking:

```
https://HOST/video-chat-player/api.php/v1/oembed?url=https://HOST/video-chat-player/index.php?room=quiet-otter-41&maxwidth=800
```

The answer is a standard `rich` oEmbed response whose `html` is the iframe.

## 6. In a Claude project

Ask that project's Claude to add the iframe or the `embed.js` snippet above with your
host's URL; nothing else is needed on that side. Rooms created there through
`POST /v1/rooms` belong to your Watch Room host. Note that the Claude preview pane
blocks YouTube frames, so YouTube items only play when the page is opened in a browser
tab; MP4 items play anywhere.

## Endpoints at a glance

| URL | Purpose |
|---|---|
| `embed.php` | The player for an iframe (parameters above) |
| `embed.php?format=json` | Descriptor: snippet, script, SDK, API, oEmbed, allowed embedders |
| `assets/embed.js` | Host-page helper that creates the iframe and drives it |
| `assets/sdk.js` | REST client for browsers and Node |
| `api.php/v1/rooms` | Create rooms |
| `api.php/v1/oembed` | oEmbed |
| `api.php/v1/openapi.json` · `api-docs.php` | The whole API |
| `api.php/v1/health` | Is the host alive |
