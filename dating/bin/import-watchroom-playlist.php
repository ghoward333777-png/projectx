<?php

declare(strict_types=1);

/**
 * Import the Watch Room source playlist into the Watch Party showcase.
 *
 * Scrapes the playlist page for its video ids (no API key), verifies every
 * id against YouTube's oEmbed endpoint — alive AND embeddable, the same
 * bar every other showcase stream meets — and bakes the survivors, with
 * their real titles, into dating/data/watch-room-playlist.json. The
 * 'watch-room' showcase channel reads that file.
 *
 *   php dating/bin/import-watchroom-playlist.php [playlist-url] [limit]
 */

$listUrl = (string) ($argv[1] ?? 'https://www.youtube.com/playlist?list=PLQ4K0DlePpSMMZXjwWGilHyefFENRUgOy');
$limit = max(1, min(100, (int) ($argv[2] ?? 30)));

$context = stream_context_create(['http' => ['timeout' => 12, 'ignore_errors' => true,
    'header' => "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\nCookie: CONSENT=YES+cb\r\nAccept-Language: en\r\n"]]);

$page = @file_get_contents($listUrl, false, $context);
if (!is_string($page) || $page === '') {
    fwrite(STDERR, "Could not fetch the playlist page.\n");
    exit(1);
}
preg_match_all('/"videoId":"([A-Za-z0-9_-]{11})"/', $page, $matches);
$ids = array_values(array_unique($matches[1] ?? []));
if ($ids === []) {
    fwrite(STDERR, "No video ids found on the playlist page.\n");
    exit(1);
}

$rows = [];
foreach ($ids as $id) {
    if (count($rows) >= $limit) {
        break;
    }
    $body = @file_get_contents(
        'https://www.youtube.com/oembed?url=' . rawurlencode('https://youtu.be/' . $id) . '&format=json',
        false,
        $context,
    );
    if (!is_string($body)) {
        continue;
    }
    $meta = json_decode($body, true);
    if (!is_array($meta) || (string) ($meta['title'] ?? '') === '') {
        continue;   // dead, private, or not embeddable — skipped
    }
    $rows[] = ['id' => $id, 'title' => (string) $meta['title']];
    fwrite(STDOUT, "  kept {$id}  {$meta['title']}\n");
}

if ($rows === []) {
    fwrite(STDERR, "Nothing on the playlist survived verification.\n");
    exit(1);
}
$file = dirname(__DIR__) . '/data/watch-room-playlist.json';
file_put_contents($file, json_encode($rows, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
fwrite(STDOUT, 'Imported ' . count($rows) . " verified videos to {$file}\n");
