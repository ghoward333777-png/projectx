<?php
declare(strict_types=1);

require_once __DIR__ . '/lib/WatchRoomApi.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$input = $_GET;
if ($method === 'POST') {
    $raw = (string) file_get_contents('php://input');
    $body = $raw === '' ? [] : json_decode($raw, true);
    if (!is_array($body)) {
        http_response_code(400);
        echo json_encode(['error' => 'Send a JSON object.']);
        exit;
    }
    $input = $body + $_GET;
}
$action = (string) ($input['action'] ?? '');
$api = new WatchRoomApi(new RoomStore(__DIR__ . '/rooms'), __DIR__ . '/media');
[$status, $payload] = $api->handle($action, $method, $input);
http_response_code($status);
echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
