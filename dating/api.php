<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingApi.php';

/**
 * SlowMoDating HTTP entry point.
 *
 * Works under the PHP built-in server (`php -S 127.0.0.1:8082`) and any
 * shared host: the API path comes from PATH_INFO when available, or from
 * the `route` query parameter otherwise (api.php?route=/users/search).
 */

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = (string) ($_SERVER['PATH_INFO'] ?? ($_GET['route'] ?? '/'));
$query = $_GET;
unset($query['route']);

$body = [];
$raw = file_get_contents('php://input');
if (is_string($raw) && $raw !== '') {
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) {
        $body = $decoded;
    }
}
if ($body === [] && $_POST !== []) {
    $body = $_POST;
}

$headers = [];
foreach ($_SERVER as $key => $value) {
    if (str_starts_with($key, 'HTTP_')) {
        $headers[strtolower(str_replace('_', '-', substr($key, 5)))] = (string) $value;
    }
}

$api = new SlowDatingApi();
[$status, $payload] = $api->route($method, $path, $query, $body, $headers);

http_response_code($status);
header('Content-Type: application/json; charset=utf-8');
if ($status !== 204) {
    echo json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
}
