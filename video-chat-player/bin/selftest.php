<?php
declare(strict_types=1);

// Server-side QC in one command: the same checks the health endpoint runs, plus a full
// room round trip in a temporary folder. Exit code 0 means the server side is healthy.
// Run: php video-chat-player/bin/selftest.php

require_once dirname(__DIR__) . '/lib/WatchRoomApi.php';

$rows = [];
$fail = 0;
$row = static function (string $name, bool $ok, string $detail) use (&$rows, &$fail): void {
    $rows[] = [$ok ? 'ok  ' : 'FAIL', $name, $detail];
    if (!$ok) {
        $fail++;
    }
};

$live = new WatchRoomApi(new RoomStore(dirname(__DIR__) . '/rooms'), dirname(__DIR__) . '/media', false);
foreach ($live->health()['checks'] as $c) {
    $row($c['name'], (bool) $c['ok'], (string) $c['detail']);
}

$tmp = sys_get_temp_dir() . '/watchroom-selftest-' . getmypid();
$api = new WatchRoomApi(new RoomStore($tmp), dirname(__DIR__) . '/media', false);
try {
    [$s, $b] = $api->handle('room.create', 'POST', ['name' => 'Selftest']);
    $row('room.create', $s === 200 && isset($b['room']['id']), "status {$s}");
    $roomId = $b['room']['id'] ?? '';
    $me = $b['memberId'] ?? '';
    [$s, $b2] = $api->handle('room.join', 'POST', ['roomId' => $roomId, 'name' => 'Guest']);
    $row('room.join', $s === 200 && count($b2['room']['members']) === 2, "status {$s}");
    [$s, $b3] = $api->handle('chat.send', 'POST', ['roomId' => $roomId, 'memberId' => $me, 'id' => 'selftest01', 'text' => 'hello', 'mediaTime' => 1.5]);
    $row('chat.send', $s === 200 && ($b3['seq'] ?? 0) > 0, "status {$s}");
    [$s, $b4] = $api->handle('sync.poll', 'GET', ['roomId' => $roomId, 'memberId' => $b2['memberId'], 'since' => 0, 'prev' => 0, 'srev' => 0]);
    $row('sync.poll', $s === 200 && count($b4['messages']) >= 3 && isset($b4['playlist'], $b4['state']), 'messages ' . count($b4['messages'] ?? []));
    [$s, $b5] = $api->handle('playlist.add', 'POST', ['roomId' => $roomId, 'memberId' => $me, 'url' => 'https://youtu.be/qqwhjSzFJqY']);
    $row('playlist.add', $s === 200 && ($b5['item']['kind'] ?? '') === 'youtube', "status {$s}");
    [$s, $b6] = $api->handle('state.set', 'POST', ['roomId' => $roomId, 'memberId' => $me, 'hostToken' => $b['hostToken'], 'state' => ['playing' => true, 'mediaTime' => 3, 'baseRev' => $b4['state']['rev']]]);
    $row('state.set', $s === 200 && ($b6['state']['playing'] ?? false) === true, "status {$s}");
    [$s] = $api->handle('state.set', 'POST', ['roomId' => $roomId, 'memberId' => $me, 'hostToken' => $b['hostToken'], 'state' => ['playing' => false, 'baseRev' => 1]]);
    $row('stale write refused', $s === 409, "status {$s}");
    [$s] = $api->handle('room.join', 'POST', ['roomId' => 'quiet-otter-00', 'name' => 'x']);
    $row('missing room is 404', $s === 404, "status {$s}");
    require_once dirname(__DIR__) . '/lib/RestApi.php';
    $rest = new RestApi($api, ['api_key' => '', 'cors_origins' => [], 'sse_seconds' => 1, 'sse_interval_ms' => 50, 'webhook_timeout' => 1, 'webhooks_per_room' => 5]);
    [$s, $rb] = $rest->dispatch('GET', "/v1/rooms/{$roomId}/state", [], [], ['authorization' => "Bearer {$me}"]);
    $row('REST /v1 routing', $s === 200 && isset($rb['expectedPosition']), "status {$s}");
    [$s] = $rest->dispatch('GET', "/v1/rooms/{$roomId}/state", [], [], []);
    $row('REST auth required', $s === 401, "status {$s}");
    $store = new RoomStore($tmp);
    touch($tmp . '/' . $roomId . '/room.json', time() - 90000);
    $row('gc removes idle rooms', $store->gc() === 1 && !is_dir($tmp . '/' . $roomId), 'after 25 h idle');
} catch (Throwable $e) {
    $row('round trip', false, get_class($e) . ': ' . $e->getMessage());
} finally {
    foreach (glob($tmp . '/*/*') ?: [] as $f) { @unlink($f); }
    foreach (glob($tmp . '/*') ?: [] as $d) { @rmdir($d); }
    @rmdir($tmp);
}

foreach ($rows as [$status, $name, $detail]) {
    printf("%s  %-22s %s\n", $status, $name, $detail);
}
echo $fail === 0 ? "\nWatch Room selftest: all " . count($rows) . " checks passed\n" : "\nWatch Room selftest: {$fail} of " . count($rows) . " checks FAILED\n";
exit($fail === 0 ? 0 : 1);
