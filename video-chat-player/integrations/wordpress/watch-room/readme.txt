=== Watch Room ===
Contributors: watchroom
Tags: video, youtube, chat, watch party, player
Requires at least: 6.0
Tested up to: 6.6
Requires PHP: 8.1
Stable tag: 1.0.0
License: MIT

A video player with a chat overlay that floats over the picture and hides itself when nobody moves. MP4 files, YouTube videos and playlists, everyone in a room in sync.

== Description ==

Watch Room bundles the whole player inside the plugin: no external service, no API keys, no database tables. Rooms are files under wp-content/uploads/watch-room.

* `[watch_room key="lobby" src="https://youtu.be/…"]` – one persistent room per key; visitors who open the page watch and chat together.
* `[watch_room room="quiet-otter-41"]` – embed a specific existing room.
* Attributes: `name` (display name; logged-in users get theirs), `height` (CSS height, empty = 16:9), `compact` (1 hides the room bar and playlist rail), `autoplay`.
* Settings → Watch Room: default video, room lifetime, player height, health checks.
* Full REST API, JavaScript SDK and webhooks: see `app/api-docs.php` under the plugin URL.

== Installation ==

1. Upload the zip in Plugins → Add New → Upload, activate.
2. Put the shortcode in a page.
3. Make sure wp-content/uploads is writable (it normally is).

== Changelog ==

= 1.0.0 =
* First release.
