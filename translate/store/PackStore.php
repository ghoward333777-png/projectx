<?php

declare(strict_types=1);

/**
 * QueryBook Translate — cloud pack store.
 *
 * Serves the language × domain pack catalog to apps that opt in to a cloud
 * QueryBook store. The bundled packs (translate/packs) are always offered;
 * packs the admin publishes are stored under store/data/packs and override a
 * bundled pack with the same id. Packs are verified by sha256 on the device,
 * downloaded once, and then work offline forever.
 */
final class PackStore
{
    public const FORMAT = 'qbt-pack/1';

    private string $root;
    private string $dataDir;

    public function __construct(?string $translateRoot = null, ?string $dataDir = null)
    {
        $this->root = rtrim($translateRoot ?? dirname(__DIR__), '/');
        $this->dataDir = rtrim($dataDir ?? (getenv('QBT_STORE_DATA') ?: __DIR__ . '/data'), '/');
    }

    /** The bearer key apps must present, or null when the store is open. */
    public static function accessKey(): ?string
    {
        $env = getenv('QBT_STORE_KEY');
        if (is_string($env) && $env !== '') {
            return $env;
        }
        $file = __DIR__ . '/store-config.php';
        if (is_file($file)) {
            $cfg = require $file;
            if (is_array($cfg) && !empty($cfg['key'])) {
                return (string) $cfg['key'];
            }
        }
        return null;
    }

    public static function authorized(?string $authorizationHeader): bool
    {
        $key = self::accessKey();
        if ($key === null) {
            return true;
        }
        if ($authorizationHeader === null || !preg_match('/^Bearer\s+(.+)$/i', trim($authorizationHeader), $m)) {
            return false;
        }
        return hash_equals($key, trim($m[1]));
    }

    /** @return array<string, mixed> */
    public function registry(): array
    {
        $data = json_decode((string) file_get_contents($this->root . '/data/languages.json'), true);
        return is_array($data) ? $data : ['languages' => []];
    }

    /** @return array<string, array<string, mixed>> id → catalog entry */
    public function catalog(): array
    {
        $out = [];
        $bundled = json_decode((string) @file_get_contents($this->root . '/packs/catalog.json'), true);
        foreach (($bundled['packs'] ?? []) as $p) {
            $out[$p['id']] = $p + ['origin' => 'bundled'];
        }
        foreach ($this->publishedFiles() as $file) {
            $body = (string) file_get_contents($file);
            $pack = json_decode($body, true);
            if (!is_array($pack) || $this->validate($pack) !== []) {
                continue;
            }
            $out[$pack['id']] = [
                'id' => $pack['id'],
                'lang' => $pack['lang'],
                'domain' => $pack['domain'],
                'version' => $pack['version'],
                'entries' => count($pack['entries']),
                'bytes' => strlen($body),
                'sha256' => hash('sha256', $body),
                'url' => 'packs/' . $pack['lang'] . '/' . $pack['domain'] . '.json',
                'origin' => 'published',
            ];
        }
        ksort($out);
        return $out;
    }

    /** JSON body for GET catalog.json. */
    public function catalogJson(): string
    {
        $packs = [];
        foreach ($this->catalog() as $p) {
            $entry = $p;
            unset($entry['origin']);
            $packs[] = $entry;
        }
        return json_encode(['format' => 'qbt-catalog/1', 'store' => 'QueryBook store', 'packs' => $packs], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
    }

    /** Raw pack body for GET packs/{lang}/{domain}.json, or null. */
    public function packBody(string $lang, string $domain): ?string
    {
        if (!self::safeSegment($lang) || !self::safeSegment($domain)) {
            return null;
        }
        foreach ([$this->dataDir . "/packs/{$lang}/{$domain}.json", $this->root . "/packs/{$lang}/{$domain}.json"] as $file) {
            if (is_file($file)) {
                return (string) file_get_contents($file);
            }
        }
        return null;
    }

    /**
     * Validate a pack document. Mirrors validatePack() in src/core/lexicon.js.
     * @param array<string, mixed> $pack
     * @return string[] problems (empty when valid)
     */
    public function validate(array $pack): array
    {
        $problems = [];
        if (($pack['format'] ?? null) !== self::FORMAT) {
            $problems[] = 'format must be ' . self::FORMAT;
        }
        foreach (['id', 'lang', 'domain', 'version'] as $k) {
            if (!is_string($pack[$k] ?? null) || $pack[$k] === '') {
                $problems[] = "missing {$k}";
            }
        }
        if ($problems !== []) {
            return $problems;
        }
        $codes = array_column($this->registry()['languages'] ?? [], 'code');
        if (!in_array($pack['lang'], $codes, true)) {
            $problems[] = "unknown language {$pack['lang']} — add it to data/languages.json";
        }
        if (!self::safeSegment($pack['lang']) || !self::safeSegment($pack['domain'])) {
            $problems[] = 'lang and domain may use letters, digits and hyphens only';
        }
        if ($pack['id'] !== $pack['lang'] . '/' . $pack['domain']) {
            $problems[] = 'id must be "<lang>/<domain>"';
        }
        if (!is_array($pack['entries'] ?? null) || $pack['entries'] === []) {
            $problems[] = 'entries must be a non-empty array';
        } else {
            foreach ($pack['entries'] as $i => $e) {
                if (!is_array($e) || !is_string($e['c'] ?? null) || !is_array($e['f'] ?? null) || $e['f'] === []) {
                    $problems[] = "entry {$i}: needs c (concept) and f (forms)";
                    break;
                }
            }
        }
        return $problems;
    }

    /** Publish (or replace) a pack. @return string[] problems */
    public function publish(string $json): array
    {
        $pack = json_decode($json, true);
        if (!is_array($pack)) {
            return ['not a JSON pack file'];
        }
        $problems = $this->validate($pack);
        if ($problems !== []) {
            return $problems;
        }
        $dir = $this->dataDir . '/packs/' . $pack['lang'];
        if (!is_dir($dir) && !mkdir($dir, 0775, true) && !is_dir($dir)) {
            return ['could not create the store data directory'];
        }
        // Store canonical JSON so the sha256 the device verifies is stable.
        $body = json_encode($pack, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
        file_put_contents($dir . '/' . $pack['domain'] . '.json', $body, LOCK_EX);
        return [];
    }

    public function unpublish(string $id): bool
    {
        [$lang, $domain] = array_pad(explode('/', $id, 2), 2, '');
        if (!self::safeSegment($lang) || !self::safeSegment($domain)) {
            return false;
        }
        $file = $this->dataDir . "/packs/{$lang}/{$domain}.json";
        return is_file($file) && unlink($file);
    }

    /** @return string[] */
    private function publishedFiles(): array
    {
        $files = glob($this->dataDir . '/packs/*/*.json') ?: [];
        sort($files);
        return $files;
    }

    private static function safeSegment(string $s): bool
    {
        return (bool) preg_match('/^[A-Za-z0-9-]{1,40}$/', $s);
    }
}
