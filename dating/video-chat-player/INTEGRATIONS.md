# Watch Room in WordPress and Joomla

Both packages bundle the whole player, so one upload installs everything: no external
service, no API keys, no database tables. Rooms are files in a folder the CMS already
owns. Build the packages from the repository:

```bash
php video-chat-player/bin/build-integrations.php
# → video-chat-player/dist/watch-room-wordpress.zip
# → video-chat-player/dist/mod_watchroom-joomla.zip
```

Requirements on the host: PHP 8.1+, the `zip` extension only for building (not for
running), `curl` or `allow_url_fopen` for YouTube titles (optional).

## WordPress

1. Plugins → Add New → Upload Plugin → `watch-room-wordpress.zip` → Activate.
   Activation creates `wp-content/uploads/watch-room/rooms/`, shields it from the web,
   and writes the bundled player's `local-config.php` (rooms folder, your site's origin
   as the only allowed embedder, 30-day room lifetime).
2. Put a shortcode in any page or post:

   ```
   [watch_room key="lobby" src="https://youtu.be/aqz-KE-bpKQ"]
   ```

   `key` names one persistent room for that page. Everyone who opens the page joins the
   same room and watches together. If the room ever expires, it is recreated on the next
   view with the same `src`.

   | Attribute | Meaning |
   |---|---|
   | `key` | Persistent room name (default: one room per post). |
   | `room` | Embed a specific existing room id instead, e.g. `quiet-otter-41`. |
   | `src` | First video: a YouTube link or an https .mp4/.webm link. Falls back to the plugin's default video. |
   | `name` | Display name; logged-in users get their own name automatically. |
   | `height` | CSS height such as `480px`; empty keeps a 16:9 box. |
   | `compact` | `1` (default) hides the room bar and playlist rail; `0` shows the full page. |
   | `autoplay` | `1` (default) or `0`. |

3. Settings → Watch Room: default video, room lifetime, player height, an advanced
   "player URL" for hosting the player elsewhere, and the live health checks.

The player is served from `wp-content/plugins/watch-room/app/`; its API reference is at
`…/app/api-docs.php`. Browsers block sound until the first click, so the embed shows a
"Tap to play" card when needed.

## Joomla 4 and 5

1. System → Install → Extensions → upload `mod_watchroom-joomla.zip`.
2. Content → Site Modules → New → **Watch Room**. Set a room key, a first video, choose a
   position, publish. To put it inside an article use `{loadmoduleid N}` (N is the module
   id) or `{loadposition watchroom}` with a matching position name.
3. On first render the module creates `media/watchroom/rooms/`, shields it, writes the
   bundled player's `local-config.php` with your site's origin, and creates the keyed room.

Module parameters mirror the WordPress attributes: room key, existing room id, first
video, compact, height, idle-room lifetime, and an advanced player URL.

The module follows the Joomla 4/5 structure (namespaced dispatcher and helper, service
provider, web asset manager), so it installs cleanly without legacy compatibility.

## Any other site

Host the `video-chat-player/` folder on any PHP host, set `WATCHROOM_CORS_ORIGINS` to the
site that will embed it, and use `assets/embed.js` as shown in [API.md](API.md). The
embed bridge is the same one the plugin and the module use.

## What the integrations test proves

`php tests/video-chat-player-integrations-contract.php` builds both packages, activates
the WordPress plugin against function stubs, renders the shortcode, checks that the same
key reuses its room and a different key gets another, recreates an expired room, and
confirms the bundled API reads the uploads folder from `local-config.php` and allows only
the site's origin. The chat browser check also runs against a copy of the WordPress
package installed under a plugin-style path to prove the nested deployment works.
