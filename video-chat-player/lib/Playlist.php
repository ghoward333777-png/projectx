<?php
declare(strict_types=1);

require_once __DIR__ . '/Source.php';
require_once __DIR__ . '/Http.php';
require_once __DIR__ . '/Text.php';

/**
 * Playlist items and URL recognition. A room's playlist lives in playlist.json with a
 * revision counter that clients poll against.
 */
final class Playlist
{
    public const MAX_ITEMS = 200;
    public const ADD_LIMIT_COUNT = 10;
    public const ADD_LIMIT_WINDOW_MS = 60000;

    /** @return array{kind: string, id?: string, list?: string, src?: string, name?: string}|null */
    public static function parseUrl(string $input, string $mediaDir): ?array
    {
        $input = trim($input);
        if ($input === '') {
            return null;
        }
        if (preg_match('/<iframe[^>]+src=["\']([^"\']+)["\']/i', $input, $m)) {
            $input = html_entity_decode($m[1]);
        }
        if (preg_match('/^[A-Za-z0-9_-]{11}$/', $input)) {
            return ['kind' => 'youtube', 'id' => $input];
        }
        $p = parse_url($input);
        if (!is_array($p)) {
            return null;
        }
        $host = strtolower((string) ($p['host'] ?? ''));
        $host = preg_replace('/^(www|m|music)\./', '', $host) ?? $host;
        parse_str((string) ($p['query'] ?? ''), $q);
        $path = (string) ($p['path'] ?? '');
        $scheme = strtolower((string) ($p['scheme'] ?? ''));
        if (in_array($host, ['youtube.com', 'youtube-nocookie.com', 'youtu.be'], true) && in_array($scheme, ['https', 'http'], true)) {
            $list = isset($q['list']) && preg_match('/^[A-Za-z0-9_-]{10,64}$/', (string) $q['list']) ? (string) $q['list'] : null;
            $id = null;
            if ($host === 'youtu.be') {
                $id = ltrim($path, '/');
            } elseif (preg_match('#^/(?:watch|playlist)/?$#', $path)) {
                $id = (string) ($q['v'] ?? '');
            } elseif (preg_match('#^/(?:embed|shorts|live|v)/([A-Za-z0-9_-]{11})#', $path, $m)) {
                $id = $m[1] === 'videoseries' ? '' : $m[1];
            }
            $id = is_string($id) && preg_match('/^[A-Za-z0-9_-]{11}$/', $id) ? $id : null;
            if ($list !== null && ($id === null || str_contains($path, '/playlist'))) {
                return ['kind' => 'youtube-playlist', 'list' => $list, 'id' => $id];
            }
            if ($id !== null) {
                return ['kind' => 'youtube', 'id' => $id, 'list' => $list];
            }
            return null;
        }
        $file = Source::resolve($input, $mediaDir);
        if ($file !== null) {
            return $file['kind'] === 'file'
                ? ['kind' => 'mp4', 'src' => $file['src'], 'name' => $file['label']]
                : ['kind' => 'mp4', 'src' => $file['src'], 'name' => $file['label']];
        }
        return null;
    }

    /** Builds a stored item from a parsed URL; titles for YouTube come from oEmbed when reachable. */
    public static function makeItem(array $parsed, string $addedBy, bool $lookup = true): array
    {
        $id = 'p_' . bin2hex(random_bytes(6));
        $now = (int) floor(microtime(true) * 1000);
        if ($parsed['kind'] === 'youtube') {
            $meta = $lookup ? self::youtubeMeta($parsed['id']) : null;
            return [
                'id' => $id, 'kind' => 'youtube', 'src' => $parsed['id'],
                'title' => $meta['title'] ?? ('YouTube video ' . $parsed['id']),
                'thumb' => $meta['thumb'] ?? ('https://i.ytimg.com/vi/' . $parsed['id'] . '/mqdefault.jpg'),
                'durationSec' => null, 'addedBy' => $addedBy, 'addedAt' => $now, 'status' => 'ok', 'error' => null,
            ];
        }
        return [
            'id' => $id, 'kind' => 'mp4', 'src' => $parsed['src'], 'title' => Text::cut((string) ($parsed['name'] ?? 'Video'), 120),
            'thumb' => null, 'durationSec' => null, 'addedBy' => $addedBy, 'addedAt' => $now, 'status' => 'ok', 'error' => null,
        ];
    }

    /** oEmbed title and thumbnail without an API key; cached per video; null when unreachable. */
    public static function youtubeMeta(string $videoId, ?string $cacheDir = null): ?array
    {
        if (!preg_match('/^[A-Za-z0-9_-]{11}$/', $videoId)) {
            return null;
        }
        $cacheDir ??= dirname(__DIR__) . '/rooms/_cache';
        $cacheFile = $cacheDir . '/yt-' . $videoId . '.json';
        if (is_file($cacheFile) && time() - (int) filemtime($cacheFile) < 86400 * 7) {
            $cached = json_decode((string) file_get_contents($cacheFile), true);
            if (is_array($cached)) {
                return $cached;
            }
        }
        $url = 'https://www.youtube.com/oembed?format=json&url=' . rawurlencode('https://www.youtube.com/watch?v=' . $videoId);
        [$status, $body] = Http::get($url, 16384);
        if ($status !== 200) {
            return null;
        }
        $data = json_decode($body, true);
        if (!is_array($data) || !isset($data['title'])) {
            return null;
        }
        $meta = [
            'title' => Text::cut(trim((string) $data['title']), 160),
            'author' => Text::cut(trim((string) ($data['author_name'] ?? '')), 80),
            'thumb' => isset($data['thumbnail_url']) && Http::isPublicHttpsUrl((string) $data['thumbnail_url']) ? (string) $data['thumbnail_url'] : null,
            'width' => (int) ($data['width'] ?? 0),
            'height' => (int) ($data['height'] ?? 0),
        ];
        if (is_dir($cacheDir) || @mkdir($cacheDir, 0775, true)) {
            @file_put_contents($cacheFile, json_encode($meta));
        }
        return $meta;
    }

    // ---- storage ----

    public static function empty(): array
    {
        return ['rev' => 1, 'items' => [], 'current' => null];
    }

    public static function load(string $roomPath): array
    {
        $file = $roomPath . '/playlist.json';
        if (!is_file($file)) {
            return self::empty();
        }
        $data = json_decode((string) file_get_contents($file), true);
        return is_array($data) && isset($data['rev'], $data['items']) ? $data : self::empty();
    }

    public static function save(string $roomPath, array $playlist): array
    {
        $playlist['rev'] = (int) $playlist['rev'] + 1;
        $file = $roomPath . '/playlist.json';
        $tmp = $file . '.' . bin2hex(random_bytes(4)) . '.tmp';
        file_put_contents($tmp, json_encode($playlist, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
        rename($tmp, $file);
        return $playlist;
    }

    public static function find(array $playlist, ?string $itemId): ?array
    {
        foreach ($playlist['items'] as $item) {
            if ($item['id'] === $itemId) {
                return $item;
            }
        }
        return null;
    }

    /** The item after $itemId, wrapping is not done: null at the end. */
    public static function next(array $playlist, ?string $itemId, bool $skipErrors = true): ?array
    {
        $found = $itemId === null;
        foreach ($playlist['items'] as $item) {
            if ($found && (!$skipErrors || $item['status'] !== 'error')) {
                return $item;
            }
            if ($item['id'] === $itemId) {
                $found = true;
            }
        }
        return null;
    }
}
