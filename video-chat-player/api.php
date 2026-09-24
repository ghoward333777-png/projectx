<?php
declare(strict_types=1);

// One entry point, two dialects:
//   api.php?action=chat.send ...            the compact action API the web page uses
//   api.php/v1/rooms/{id}/messages          the REST API (also api.php?route=/v1/... on hosts without PATH_INFO)
require_once __DIR__ . '/lib/RestApi.php';

$config = require __DIR__ . '/config.php';
$method = strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET');
$headers = [];
foreach ($_SERVER as $k => $v) {
    if (str_starts_with($k, 'HTTP_')) {
        $headers[strtolower(str_replace('_', '-', substr($k, 5)))] = (string) $v;
    }
}
if (isset($_SERVER['CONTENT_TYPE'])) {
    $headers['content-type'] = (string) $_SERVER['CONTENT_TYPE'];
}
$route = (string) ($_SERVER['PATH_INFO'] ?? ($_GET['route'] ?? ''));
$api = new WatchRoomApi(new RoomStore(__DIR__ . '/rooms'), __DIR__ . '/media', true, $config);
$rest = new RestApi($api, $config);

$emit = static function (int $status, array $payload, array $extra = []) use ($rest, $headers): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('X-Content-Type-Options: nosniff');
    foreach ($extra + $rest->cors((string) ($headers['origin'] ?? '')) as $k => $v) {
        header("{$k}: {$v}");
    }
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
};

if ($method === 'OPTIONS') {
    http_response_code(204);
    foreach ($rest->cors((string) ($headers['origin'] ?? '')) as $k => $v) {
        header("{$k}: {$v}");
    }
    exit;
}

$body = [];
if (in_array($method, ['POST', 'PUT', 'PATCH', 'DELETE'], true)) {
    $raw = (string) file_get_contents('php://input');
    if ($raw !== '') {
        $decoded = json_decode($raw, true);
        if (!is_array($decoded)) {
            $emit(400, ['error' => 'Send a JSON object.', 'code' => 'bad_request']);
            exit;
        }
        $body = $decoded;
    }
}

if ($route !== '' && str_starts_with('/' . ltrim($route, '/'), '/v1')) {
    $query = $_GET;
    unset($query['route']);
    $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
    $baseUrl = $scheme . '://' . ($_SERVER['HTTP_HOST'] ?? 'localhost') . (string) ($_SERVER['SCRIPT_NAME'] ?? '/api.php');
    [$status, $payload, $extra] = $rest->dispatch($method, $route, $query, $body, $headers, $baseUrl);
    if ($status === 200 && isset($payload['__sse'])) {
        http_response_code(200);
        header('Content-Type: text/event-stream; charset=utf-8');
        header('Cache-Control: no-store');
        header('X-Accel-Buffering: no');
        foreach ($rest->cors((string) ($headers['origin'] ?? '')) as $k => $v) {
            header("{$k}: {$v}");
        }
        @ini_set('output_buffering', '0');
        @ini_set('zlib.output_compression', '0');
        while (ob_get_level() > 0) {
            ob_end_flush();
        }
        set_time_limit((int) $config['sse_seconds'] + 10);
        $rest->streamEvents($payload['__sse'], (int) $config['sse_seconds'], (int) $config['sse_interval_ms'], static function (string $chunk): void { echo $chunk; flush(); }, static fn (): bool => connection_aborted() === 1);
        exit;
    }
    $emit($status, $payload, $extra);
    exit;
}

// Compact action dialect (the web page). Bearer/host headers are honoured here too.
$input = $body + $_GET;
if (($bearer = RestApi::bearer($headers)) !== '') {
    $input['memberId'] = $bearer;
}
if (isset($headers['x-host-token'])) {
    $input['hostToken'] = $headers['x-host-token'];
}
[$status, $payload] = $api->handle((string) ($input['action'] ?? ''), $method, $input);
$emit($status, $payload, ['Cache-Control' => 'no-store']);
