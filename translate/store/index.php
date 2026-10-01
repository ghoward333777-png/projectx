<?php

declare(strict_types=1);

/**
 * QueryBook store endpoint for QueryBook Translate apps.
 *
 *   GET  <store>/catalog.json                  pack catalog (bundled + published)
 *   GET  <store>/packs/<lang>/<domain>.json    one pack (apps verify its sha256)
 *   GET  <store>/health                        status
 *
 * <store> is ".../translate/store/index.php/" (works on any PHP host and with
 * `php -S`); with the bundled .htaccess, ".../translate/store/" works too.
 * Set QBT_STORE_KEY (or store-config.php) to require "Authorization: Bearer <key>".
 */

require_once __DIR__ . '/PackStore.php';

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Headers: authorization, content-type');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('X-Content-Type-Options: nosniff');

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$path = $_SERVER['PATH_INFO'] ?? ($_GET['path'] ?? '');
if ($path === '' && isset($_SERVER['REQUEST_URI'])) {
    $uri = (string) parse_url((string) $_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $base = rtrim(dirname((string) ($_SERVER['SCRIPT_NAME'] ?? '')), '/');
    if ($base !== '' && str_starts_with($uri, $base)) {
        $path = substr($uri, strlen($base));
    }
}
$path = '/' . ltrim((string) $path, '/');

function store_send(int $status, string $body, string $type = 'application/json; charset=utf-8'): void
{
    http_response_code($status);
    header('Content-Type: ' . $type);
    header('Cache-Control: no-cache');
    echo $body;
}

$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? ($_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null);
if (!PackStore::authorized($auth)) {
    header('WWW-Authenticate: Bearer realm="QueryBook store"');
    store_send(401, json_encode(['error' => 'store access key required']) . "\n");
    return;
}

$store = new PackStore();

if ($path === '/' || $path === '/health' || $path === '/index.php') {
    store_send(200, json_encode(['ok' => true, 'service' => 'QueryBook store', 'packs' => count($store->catalog()), 'protected' => PackStore::accessKey() !== null]) . "\n");
    return;
}
if ($path === '/catalog.json') {
    store_send(200, $store->catalogJson());
    return;
}
if (preg_match('#^/packs/([A-Za-z0-9-]+)/([A-Za-z0-9-]+)\.json$#', $path, $m)) {
    $body = $store->packBody($m[1], $m[2]);
    if ($body !== null) {
        store_send(200, $body);
        return;
    }
}
store_send(404, json_encode(['error' => 'not found', 'path' => $path]) . "\n");
