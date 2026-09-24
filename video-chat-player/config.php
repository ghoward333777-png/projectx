<?php
declare(strict_types=1);

/**
 * Deployment settings. Environment variables win over the defaults here, so hosting
 * panels can configure the app without editing files.
 *
 *  WATCHROOM_API_KEY      when set, creating rooms through the REST API (/v1/rooms) requires
 *                         this key in the X-Api-Key header; the web page is unaffected.
 *  WATCHROOM_CORS_ORIGINS comma-separated origins allowed to call the API and to embed the
 *                         player from another site (e.g. "https://example.com,https://app.example.com").
 *  WATCHROOM_SSE_SECONDS  how long one event-stream connection stays open before the client
 *                         reconnects (default 25; keep it short on shared hosting).
 *  WATCHROOM_ROOMS_DIR    where room folders live (default: rooms/ next to this file).
 *  WATCHROOM_MEDIA_DIR    where local video files live (default: media/ next to this file).
 *  WATCHROOM_ROOM_MAX_AGE seconds a room may sit idle before it is removed (default 86400).
 *  WATCHROOM_DEFAULT_SRC  first item of every new room: a YouTube video or playlist link, an https
 *                         .mp4/.webm link, or media/<file> (default: the demo playlist below).
 *
 * A local-config.php next to this file (returning an array) overrides everything; the
 * WordPress plugin and the Joomla module write one at install time.
 */
$defaults = [
    'api_key' => (string) (getenv('WATCHROOM_API_KEY') ?: ''),
    'cors_origins' => array_values(array_filter(array_map('trim', explode(',', (string) (getenv('WATCHROOM_CORS_ORIGINS') ?: ''))))),
    'sse_seconds' => max(5, min(120, (int) (getenv('WATCHROOM_SSE_SECONDS') ?: 25))),
    'sse_interval_ms' => 500,
    'webhook_timeout' => 2,
    'webhooks_per_room' => 5,
    'rooms_dir' => (string) (getenv('WATCHROOM_ROOMS_DIR') ?: __DIR__ . '/rooms'),
    'media_dir' => (string) (getenv('WATCHROOM_MEDIA_DIR') ?: __DIR__ . '/media'),
    'room_max_age' => max(3600, (int) (getenv('WATCHROOM_ROOM_MAX_AGE') ?: 86400)),
    'default_src' => (string) (getenv('WATCHROOM_DEFAULT_SRC') ?: 'https://www.youtube.com/playlist?list=PLQ4K0DlePpSMMZXjwWGilHyefFENRUgOy'),
];
$local = is_file(__DIR__ . '/local-config.php') ? require __DIR__ . '/local-config.php' : [];
return (is_array($local) ? $local : []) + $defaults;
