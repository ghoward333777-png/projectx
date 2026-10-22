<?php

declare(strict_types=1);

/**
 * Stock Media Harvester
 *
 * Collects video *metadata* from free stock-media sources through their
 * official public APIs and normalizes every item into one record shape the
 * MediaAnalyzer understands. It never downloads, caches or re-hosts the
 * footage itself — only the descriptive fields each API returns (title,
 * tags, size, duration, creator, license, page link) — so the graph is an
 * index of what exists, not a copy of it.
 *
 * Keyless sources: Wikimedia Commons, Internet Archive, NASA Image and
 * Video Library. Keyed (free) sources: Pexels (PEXELS_API_KEY) and Pixabay
 * (PIXABAY_API_KEY); without a key they are skipped with a clear message.
 * Anything else — AI-video galleries, your own exports — comes in through
 * importManifest() as a JSON list.
 *
 * Normalized record keys: source, source_id, title, description, tags,
 * page_url, creator, license, width, height, duration, fps, created,
 * ai_generated (true/false/null), views, downloads.
 */
final class StockMediaHarvester
{
    public const MAX_PER_REQUEST = 50;

    public const SOURCES = [
        'wikimedia' => ['label' => 'Wikimedia Commons', 'key_env' => null, 'license' => 'Per item (CC / public domain)', 'site' => 'https://commons.wikimedia.org'],
        'archive' => ['label' => 'Internet Archive', 'key_env' => null, 'license' => 'Per item (often CC / public domain)', 'site' => 'https://archive.org'],
        'nasa' => ['label' => 'NASA Image and Video Library', 'key_env' => null, 'license' => 'NASA media guidelines (generally public domain)', 'site' => 'https://images.nasa.gov'],
        'pexels' => ['label' => 'Pexels Videos', 'key_env' => 'PEXELS_API_KEY', 'license' => 'Pexels License (free to use)', 'site' => 'https://www.pexels.com'],
        'pixabay' => ['label' => 'Pixabay Videos', 'key_env' => 'PIXABAY_API_KEY', 'license' => 'Pixabay Content License (free to use)', 'site' => 'https://pixabay.com'],
    ];

    private const USER_AGENT = 'BookIntelligenceStudio-MediaGraph/1.0 (metadata indexer; no media download)';

    /** @var callable(string, array<int, string>): string */
    private $fetcher;

    /** @var array<string, string> */
    private array $keys;

    /**
     * @param callable(string, array<int, string>): string|null $fetcher Returns the response body for a URL + headers.
     * @param array<string, string>|null $keys Source => API key; defaults to the environment.
     */
    public function __construct(?callable $fetcher = null, ?array $keys = null)
    {
        $this->fetcher = $fetcher ?? [$this, 'httpGet'];
        $this->keys = $keys ?? array_filter([
            'pexels' => (string) getenv('PEXELS_API_KEY'),
            'pixabay' => (string) getenv('PIXABAY_API_KEY'),
        ]);
    }

    /** Whether a source can be harvested right now (has its key, if it needs one). */
    public function available(string $source): bool
    {
        $meta = self::SOURCES[$source] ?? null;
        return $meta !== null && ($meta['key_env'] === null || ($this->keys[$source] ?? '') !== '');
    }

    /**
     * Search one source and return normalized records.
     *
     * @return array{records: array<int, array<string, mixed>>, error: ?string}
     */
    public function harvest(string $source, string $query, int $limit = 20): array
    {
        if (!isset(self::SOURCES[$source])) {
            return ['records' => [], 'error' => 'Unknown source: ' . $source];
        }
        if (!$this->available($source)) {
            return ['records' => [], 'error' => self::SOURCES[$source]['label'] . ' needs a free API key in ' . self::SOURCES[$source]['key_env'] . '.'];
        }
        $query = trim($query);
        if ($query === '') {
            return ['records' => [], 'error' => 'Enter a search term.'];
        }
        $limit = max(1, min(self::MAX_PER_REQUEST, $limit));
        try {
            $records = match ($source) {
                'wikimedia' => $this->wikimedia($query, $limit),
                'archive' => $this->archive($query, $limit),
                'nasa' => $this->nasa($query, $limit),
                'pexels' => $this->pexels($query, $limit),
                'pixabay' => $this->pixabay($query, $limit),
            };
        } catch (Throwable $e) {
            return ['records' => [], 'error' => self::SOURCES[$source]['label'] . ': ' . $e->getMessage()];
        }
        return ['records' => array_slice($records, 0, $limit), 'error' => null];
    }

    /**
     * Normalize a JSON manifest — a list of items, or {"items": [...]} — from
     * any other free source (AI-video galleries, CSV exports turned JSON).
     *
     * @param array<mixed> $manifest
     * @return array<int, array<string, mixed>>
     */
    public function importManifest(array $manifest, string $defaultSource = 'manifest'): array
    {
        $items = isset($manifest['items']) && is_array($manifest['items']) ? $manifest['items'] : $manifest;
        $records = [];
        foreach ($items as $i => $item) {
            if (!is_array($item)) {
                continue;
            }
            $item['source'] = (string) ($item['source'] ?? $defaultSource);
            $item['source_id'] = (string) ($item['source_id'] ?? $item['id'] ?? ('item-' . ($i + 1)));
            $records[] = self::normalize($item);
        }
        return $records;
    }

    /**
     * Fill every record key with a typed value.
     *
     * @param array<string, mixed> $raw
     * @return array<string, mixed>
     */
    public static function normalize(array $raw): array
    {
        $tags = $raw['tags'] ?? [];
        if (is_string($tags)) {
            $tags = preg_split('/\s*[,|;]\s*/', $tags) ?: [];
        }
        $ai = $raw['ai_generated'] ?? null;
        return [
            'source' => (string) ($raw['source'] ?? 'manifest'),
            'source_id' => (string) ($raw['source_id'] ?? ''),
            'title' => self::text((string) ($raw['title'] ?? '')),
            'description' => self::text((string) ($raw['description'] ?? '')),
            'tags' => array_values(array_filter(array_map(static fn ($t): string => self::text((string) $t), (array) $tags), static fn (string $t): bool => $t !== '')),
            'page_url' => (string) ($raw['page_url'] ?? ''),
            'creator' => self::text((string) ($raw['creator'] ?? '')),
            'license' => self::text((string) ($raw['license'] ?? '')),
            'width' => (int) ($raw['width'] ?? 0),
            'height' => (int) ($raw['height'] ?? 0),
            'duration' => (float) ($raw['duration'] ?? 0),
            'fps' => (float) ($raw['fps'] ?? 0),
            'created' => (string) ($raw['created'] ?? ''),
            'ai_generated' => is_bool($ai) ? $ai : null,
            'views' => (int) ($raw['views'] ?? 0),
            'downloads' => (int) ($raw['downloads'] ?? 0),
        ];
    }

    /** @return array<int, array<string, mixed>> */
    private function wikimedia(string $query, int $limit): array
    {
        $url = 'https://commons.wikimedia.org/w/api.php?' . http_build_query([
            'action' => 'query', 'format' => 'json', 'generator' => 'search', 'gsrnamespace' => 6,
            'gsrsearch' => 'filetype:video ' . $query, 'gsrlimit' => $limit,
            'prop' => 'imageinfo', 'iiprop' => 'url|size|mime|extmetadata',
            'iiextmetadatafilter' => 'LicenseShortName|Artist|ImageDescription|Categories|DateTimeOriginal',
        ]);
        $data = $this->json($url);
        $pages = (array) ($data['query']['pages'] ?? []);
        ksort($pages);
        $records = [];
        foreach ($pages as $page) {
            $info = (array) ($page['imageinfo'][0] ?? []);
            $meta = (array) ($info['extmetadata'] ?? []);
            $title = preg_replace(['/^File:/', '/\.[a-z0-9]+$/i'], '', (string) ($page['title'] ?? ''));
            $records[] = self::normalize([
                'source' => 'wikimedia',
                'source_id' => (string) ($page['pageid'] ?? $title),
                'title' => str_replace('_', ' ', (string) $title),
                'description' => (string) ($meta['ImageDescription']['value'] ?? ''),
                'tags' => explode('|', (string) ($meta['Categories']['value'] ?? '')),
                'page_url' => (string) ($info['descriptionurl'] ?? ''),
                'creator' => (string) ($meta['Artist']['value'] ?? ''),
                'license' => (string) ($meta['LicenseShortName']['value'] ?? ''),
                'width' => $info['width'] ?? 0,
                'height' => $info['height'] ?? 0,
                'duration' => $info['duration'] ?? 0,
                'created' => substr(strip_tags((string) ($meta['DateTimeOriginal']['value'] ?? '')), 0, 10),
            ]);
        }
        return $records;
    }

    /** @return array<int, array<string, mixed>> */
    private function archive(string $query, int $limit): array
    {
        $fields = ['identifier', 'title', 'description', 'subject', 'creator', 'licenseurl', 'date', 'downloads'];
        $url = 'https://archive.org/advancedsearch.php?' . http_build_query([
            'q' => '(title:(' . $query . ') OR subject:(' . $query . ')) AND mediatype:movies',
            'rows' => $limit, 'page' => 1, 'output' => 'json',
        ]);
        foreach ($fields as $field) {
            $url .= '&fl[]=' . $field;
        }
        $data = $this->json($url);
        $records = [];
        foreach ((array) ($data['response']['docs'] ?? []) as $doc) {
            $first = static fn ($v): string => is_array($v) ? (string) ($v[0] ?? '') : (string) $v;
            $records[] = self::normalize([
                'source' => 'archive',
                'source_id' => (string) ($doc['identifier'] ?? ''),
                'title' => $first($doc['title'] ?? ''),
                'description' => mb_substr($first($doc['description'] ?? ''), 0, 600),
                'tags' => (array) ($doc['subject'] ?? []),
                'page_url' => 'https://archive.org/details/' . rawurlencode((string) ($doc['identifier'] ?? '')),
                'creator' => $first($doc['creator'] ?? ''),
                'license' => self::licenseFromUrl((string) ($doc['licenseurl'] ?? '')),
                'created' => substr($first($doc['date'] ?? ''), 0, 10),
                'downloads' => $doc['downloads'] ?? 0,
            ]);
        }
        return $records;
    }

    /** @return array<int, array<string, mixed>> */
    private function nasa(string $query, int $limit): array
    {
        $url = 'https://images-api.nasa.gov/search?' . http_build_query(['q' => $query, 'media_type' => 'video', 'page_size' => $limit]);
        $data = $this->json($url);
        $records = [];
        foreach ((array) ($data['collection']['items'] ?? []) as $item) {
            $meta = (array) ($item['data'][0] ?? []);
            $id = (string) ($meta['nasa_id'] ?? '');
            $records[] = self::normalize([
                'source' => 'nasa',
                'source_id' => $id,
                'title' => (string) ($meta['title'] ?? ''),
                'description' => mb_substr((string) ($meta['description'] ?? ''), 0, 600),
                'tags' => (array) ($meta['keywords'] ?? []),
                'page_url' => 'https://images.nasa.gov/details/' . rawurlencode($id),
                'creator' => (string) ($meta['secondary_creator'] ?? $meta['center'] ?? ''),
                'license' => 'NASA media guidelines',
                'created' => substr((string) ($meta['date_created'] ?? ''), 0, 10),
            ]);
        }
        return $records;
    }

    /** @return array<int, array<string, mixed>> */
    private function pexels(string $query, int $limit): array
    {
        $url = 'https://api.pexels.com/videos/search?' . http_build_query(['query' => $query, 'per_page' => $limit]);
        $data = $this->json($url, ['Authorization: ' . $this->keys['pexels']]);
        $records = [];
        foreach ((array) ($data['videos'] ?? []) as $video) {
            $best = ['width' => 0, 'height' => 0, 'fps' => 0];
            foreach ((array) ($video['video_files'] ?? []) as $file) {
                if ((int) ($file['width'] ?? 0) > $best['width']) {
                    $best = ['width' => (int) $file['width'], 'height' => (int) ($file['height'] ?? 0), 'fps' => (float) ($file['fps'] ?? 0)];
                }
            }
            $page = (string) ($video['url'] ?? '');
            // Pexels returns no tags; the page slug carries the descriptive words.
            $slug = (string) preg_replace('/-\d+\/?$/', '', basename(rtrim($page, '/')));
            $words = trim(str_replace('-', ' ', $slug));
            $records[] = self::normalize([
                'source' => 'pexels',
                'source_id' => (string) ($video['id'] ?? ''),
                'title' => ucfirst($words),
                'tags' => array_filter(explode(' ', $words)),
                'page_url' => $page,
                'creator' => (string) ($video['user']['name'] ?? ''),
                'license' => 'Pexels License',
                'width' => $best['width'] ?: ($video['width'] ?? 0),
                'height' => $best['height'] ?: ($video['height'] ?? 0),
                'duration' => $video['duration'] ?? 0,
                'fps' => $best['fps'],
            ]);
        }
        return $records;
    }

    /** @return array<int, array<string, mixed>> */
    private function pixabay(string $query, int $limit): array
    {
        $url = 'https://pixabay.com/api/videos/?' . http_build_query(['key' => $this->keys['pixabay'], 'q' => $query, 'per_page' => max(3, $limit)]);
        $data = $this->json($url);
        $records = [];
        foreach ((array) ($data['hits'] ?? []) as $hit) {
            $largest = ['width' => 0, 'height' => 0];
            foreach ((array) ($hit['videos'] ?? []) as $rendition) {
                if ((int) ($rendition['width'] ?? 0) > $largest['width']) {
                    $largest = ['width' => (int) $rendition['width'], 'height' => (int) ($rendition['height'] ?? 0)];
                }
            }
            $tags = (string) ($hit['tags'] ?? '');
            $records[] = self::normalize([
                'source' => 'pixabay',
                'source_id' => (string) ($hit['id'] ?? ''),
                'title' => ucfirst(explode(',', $tags)[0] ?? ''),
                'tags' => $tags,
                'page_url' => (string) ($hit['pageURL'] ?? ''),
                'creator' => (string) ($hit['user'] ?? ''),
                'license' => 'Pixabay Content License',
                'width' => $largest['width'],
                'height' => $largest['height'],
                'duration' => $hit['duration'] ?? 0,
                'views' => $hit['views'] ?? 0,
                'downloads' => $hit['downloads'] ?? 0,
            ]);
        }
        return $records;
    }

    /**
     * @param array<int, string> $headers
     * @return array<mixed>
     */
    private function json(string $url, array $headers = []): array
    {
        $body = ($this->fetcher)($url, $headers);
        $data = json_decode($body, true);
        if (!is_array($data)) {
            throw new RuntimeException('the API did not return JSON (' . mb_substr(trim(strip_tags($body)), 0, 120) . ')');
        }
        return $data;
    }

    /** @param array<int, string> $headers */
    private function httpGet(string $url, array $headers): string
    {
        $headers[] = 'Accept: application/json';
        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true, CURLOPT_FOLLOWLOCATION => true, CURLOPT_TIMEOUT => 30,
                CURLOPT_USERAGENT => self::USER_AGENT, CURLOPT_HTTPHEADER => $headers,
            ]);
            $body = curl_exec($ch);
            $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
            $error = curl_error($ch);
            curl_close($ch);
            if ($body === false) {
                throw new RuntimeException('request failed: ' . $error);
            }
            if ($status >= 400) {
                throw new RuntimeException('HTTP ' . $status . ' (' . mb_substr(trim(strip_tags((string) $body)), 0, 120) . ')');
            }
            return (string) $body;
        }
        $context = stream_context_create(['http' => ['header' => implode("\r\n", $headers), 'user_agent' => self::USER_AGENT, 'timeout' => 30]]);
        $body = @file_get_contents($url, false, $context);
        if ($body === false) {
            throw new RuntimeException('request failed');
        }
        return $body;
    }

    private static function licenseFromUrl(string $url): string
    {
        if ($url === '') {
            return '';
        }
        if (preg_match('#creativecommons\.org/(licenses|publicdomain)/([a-z\-]+)/?([0-9.]*)#i', $url, $m)) {
            return $m[1] === 'publicdomain' ? 'Public domain (' . strtoupper($m[2]) . ')' : trim('CC ' . strtoupper($m[2]) . ' ' . $m[3]);
        }
        return $url;
    }

    private static function text(string $value): string
    {
        $value = html_entity_decode(strip_tags($value), ENT_QUOTES | ENT_HTML5, 'UTF-8');
        return trim((string) preg_replace('/\s+/u', ' ', $value));
    }
}
