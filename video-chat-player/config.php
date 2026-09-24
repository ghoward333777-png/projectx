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
 */
return [
    'api_key' => (string) (getenv('WATCHROOM_API_KEY') ?: ''),
    'cors_origins' => array_values(array_filter(array_map('trim', explode(',', (string) (getenv('WATCHROOM_CORS_ORIGINS') ?: ''))))),
    'sse_seconds' => max(5, min(120, (int) (getenv('WATCHROOM_SSE_SECONDS') ?: 25))),
    'sse_interval_ms' => 500,
    'webhook_timeout' => 2,
    'webhooks_per_room' => 5,
];
