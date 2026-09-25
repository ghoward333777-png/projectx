# Installers

Built by `php video-chat-player/bin/build-integrations.php`; each bundles the whole player.

| File | Install where | How |
|---|---|---|
| `watch-room-wordpress.zip` | WordPress 6+, PHP 8.1+ | Plugins → Add New → Upload Plugin → Activate. Shortcode `[watch_room key="lobby" src="…"]`. Settings → Watch Room. |
| `mod_watchroom-joomla.zip` | Joomla 4 / 5, PHP 8.1+ | System → Install → Extensions → upload. Content → Site Modules → New → Watch Room. `{loadmoduleid N}` in articles. |
| `watch-room-embed.zip` | Any PHP 8.1+ host | Unzip under the web root; open `video-chat-player/index.php`. Embed elsewhere with `embed.php` (see EMBED.md). |
