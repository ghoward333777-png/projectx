<?php
declare(strict_types=1);

// Contract test for the REST API layer: routing, auth, status codes, OpenAPI consistency,
// webhook signatures and the event-stream format. Plain `php tests/video-chat-player-api-contract.php`.

require_once __DIR__ . '/../video-chat-player/lib/RestApi.php';

$failures = 0;
$checks = 0;
$assert = static function (bool $condition, string $label) use (&$failures, &$checks): void {
    $checks++;
    if (!$condition) {
        $failures++;
        fwrite(STDERR, "FAIL  {$label}\n");
    }
};

$tmp = sys_get_temp_dir() . '/watchroom-api-' . getmypid();
$config = ['api_key' => '', 'cors_origins' => ['https://site.example'], 'sse_seconds' => 1, 'sse_interval_ms' => 50, 'webhook_timeout' => 1, 'webhooks_per_room' => 2];
$api = new WatchRoomApi(new RoomStore($tmp), __DIR__ . '/../video-chat-player/media', false, $config);
$rest = new RestApi($api, $config);
$call = static fn (string $m, string $p, array $q = [], array $b = [], array $h = []) => $rest->dispatch($m, $p, $q, $b, $h, 'https://host.example/api.php');

// --- system routes ---
[$s, $b] = $call('GET', '/v1/health');
$assert($s === 200 && $b['ok'] === true, 'GET /v1/health');
[$s, $b] = $call('GET', '/v1/openapi.json');
$assert($s === 200 && $b['openapi'] === '3.1.0' && $b['servers'][0]['url'] === 'https://host.example/api.php', 'GET /v1/openapi.json carries the base URL');
$spec = $b;
[$s, $b] = $call('GET', '/v1/resolve', ['url' => 'https://youtu.be/dQw4w9WgXcQ']);
$assert($s === 200 && $b['kind'] === 'youtube' && $b['src'] === 'dQw4w9WgXcQ', 'GET /v1/resolve recognises YouTube');
[$s, $b] = $call('GET', '/v1/resolve', ['url' => 'https://www.youtube.com/playlist?list=PL9oaxTKWGJ7ONeR1-1cMkCAGAl-gozWij']);
$assert($s === 200 && $b['kind'] === 'youtube-playlist', 'GET /v1/resolve recognises playlists');
[$s, $b] = $call('GET', '/v1/resolve', ['url' => 'ftp://x']);
$assert($s === 400 && $b['code'] === 'bad_request', 'GET /v1/resolve rejects junk with a code');

// --- rooms and auth ---
[$s, $b] = $call('POST', '/v1/rooms', [], ['name' => 'Ana', 'src' => 'media/sample.mp4']);
$assert($s === 201 && isset($b['hostToken'], $b['memberId']) && $b['playlist']['items'][0]['kind'] === 'mp4', 'POST /v1/rooms → 201 with host token and first item');
$room = $b['room']['id'];
$ana = $b['memberId'];
$host = $b['hostToken'];
$stateRev = $b['state']['rev'];
[$s, $b] = $call('GET', "/v1/rooms/{$room}");
$assert($s === 401 && $b['code'] === 'unauthorized', 'member routes without Bearer → 401');
[$s, $b] = $call('GET', "/v1/rooms/{$room}", [], [], ['authorization' => 'Bearer nope']);
$assert($s === 401, 'malformed Bearer → 401');
$auth = ['authorization' => "Bearer {$ana}"];
[$s, $b] = $call('GET', "/v1/rooms/{$room}", [], [], $auth);
$assert($s === 200 && $b['room']['id'] === $room && isset($b['playlist'], $b['state']), 'GET /v1/rooms/{id} with Bearer');
[$s, $b] = $call('GET', '/v1/rooms/quiet-otter-00', [], [], $auth);
$assert($s === 404 && $b['code'] === 'not_found', 'unknown room → 404');
[$s, $b] = $call('POST', "/v1/rooms/{$room}/members", [], ['name' => 'Bob']);
$assert($s === 200 && isset($b['memberId']) && count($b['room']['members']) === 2, 'POST /members joins without auth');
$bob = $b['memberId'];
$bobAuth = ['authorization' => "Bearer {$bob}"];
[$s, $b] = $call('PATCH', "/v1/rooms/{$room}/members/me", [], ['name' => 'Roberto'], $bobAuth);
$assert($s === 200 && $b['room']['members'][1]['name'] === 'Roberto', 'PATCH /members/me renames');
[$s, $b] = $call('PATCH', "/v1/rooms/{$room}", [], ['guestsControl' => false], $bobAuth);
$assert($s === 403 && $b['code'] === 'forbidden', 'PATCH room without host token → 403');
[$s, $b] = $call('PATCH', "/v1/rooms/{$room}", [], ['guestsControl' => false], $auth + ['x-host-token' => $host]);
$assert($s === 200 && $b['room']['guestsControl'] === false, 'PATCH room with host token changes settings');

// --- API key gate ---
$gated = new RestApi($api, ['api_key' => 'secret-key'] + $config);
[$s, $b] = $gated->dispatch('POST', '/v1/rooms', [], ['name' => 'X'], []);
$assert($s === 401, 'room creation needs X-Api-Key when configured');
[$s] = $gated->dispatch('POST', '/v1/rooms', [], ['name' => 'X'], ['x-api-key' => 'secret-key']);
$assert($s === 201, 'room creation works with the right X-Api-Key');
[$s] = $gated->dispatch('GET', '/v1/health', [], [], []);
$assert($s === 200, 'API key is not required for reads');

// --- messages ---
[$s, $b] = $call('POST', "/v1/rooms/{$room}/messages", [], ['id' => 'apimsg01', 'text' => 'hello', 'mediaTime' => 4.25], $auth);
$assert($s === 201 && $b['message']['text'] === 'hello' && $b['message']['mediaTime'] === 4.25, 'POST /messages → 201');
[$s, $b2] = $call('POST', "/v1/rooms/{$room}/messages", [], ['id' => 'apimsg01', 'text' => 'hello again'], $auth);
$assert($s === 201 && $b2['seq'] === $b['seq'], 'duplicate client id returns the stored message (idempotent)');
[$s, $b] = $call('GET', "/v1/rooms/{$room}/messages", ['since' => 0], [], $bobAuth);
$texts = array_column($b['messages'], 'text');
$assert($s === 200 && in_array('hello', $texts, true) && !in_array('hello again', $texts, true), 'GET /messages?since=0 lists the log');
[$s, $b] = $call('GET', "/v1/rooms/{$room}/messages", ['limit' => 1], [], $bobAuth);
$assert($s === 200 && count($b['messages']) === 1, 'GET /messages?limit=1 returns the latest');
for ($i = 0; $i < 5; $i++) {
    [$s] = $call('POST', "/v1/rooms/{$room}/messages", [], ['id' => "flood{$i}x", 'text' => "m{$i}"], $bobAuth);
}
[$s, $b] = $call('POST', "/v1/rooms/{$room}/messages", [], ['id' => 'flood99x', 'text' => 'too many'], $bobAuth);
$assert($s === 429 && $b['code'] === 'rate_limited', 'sixth message in 5 s → 429');

// --- playlist ---
[$s, $b] = $call('POST', "/v1/rooms/{$room}/playlist", [], ['url' => 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'], $bobAuth);
$assert($s === 201 && $b['item']['kind'] === 'youtube', 'POST /playlist adds a YouTube item → 201');
$item = $b['item']['id'];
[$s, $b] = $call('GET', "/v1/rooms/{$room}/playlist", [], [], $bobAuth);
$assert($s === 200 && count($b['playlist']['items']) === 2, 'GET /playlist');
[$s, $b] = $call('PATCH', "/v1/rooms/{$room}/playlist", [], ['order' => [$item]], $bobAuth);
$assert($s === 403, 'guest reorder → 403');
[$s, $b] = $call('PATCH', "/v1/rooms/{$room}/playlist", [], ['order' => [$item]], $auth + ['x-host-token' => $host]);
$assert($s === 200 && $b['playlist']['items'][0]['id'] === $item, 'host reorder moves the item first');
[$s, $b] = $call('PATCH', "/v1/rooms/{$room}/playlist", [], ['current' => $item], $auth + ['x-host-token' => $host]);
$assert($s === 200 && $b['playlist']['current'] === $item && $b['state']['itemId'] === $item && $b['state']['playing'] === true, 'PATCH current jumps and starts the item');
[$s, $b] = $call('POST', "/v1/rooms/{$room}/playlist/import", [], ['videoIds' => ['dQw4w9WgXcQ', 'bad', 'dQw4w9WgXcQ']], $auth);
$assert($s === 201 && $b['added'] === 1, 'POST /playlist/import de-duplicates and validates ids');
[$s, $b] = $call('DELETE', "/v1/rooms/{$room}/playlist/{$item}", [], [], $bobAuth);
$assert($s === 403, 'guest delete → 403');
[$s, $b] = $call('DELETE', "/v1/rooms/{$room}/playlist/{$item}", [], [], $auth + ['x-host-token' => $host]);
$assert($s === 200 && !in_array($item, array_column($b['playlist']['items'], 'id'), true), 'host DELETE /playlist/{item} removes it');

// --- state ---
[$s, $b] = $call('GET', "/v1/rooms/{$room}/state", [], [], $bobAuth);
$assert($s === 200 && isset($b['expectedPosition']), 'GET /state includes expectedPosition');
$rev = $b['state']['rev'];
[$s, $b] = $call('PUT', "/v1/rooms/{$room}/state", [], ['state' => ['playing' => false, 'mediaTime' => 7, 'baseRev' => $rev]], $bobAuth);
$assert($s === 403 && $b['code'] === 'forbidden', 'guest PUT /state with guest control off → 403');
[$s, $b] = $call('PUT', "/v1/rooms/{$room}/state", [], ['state' => ['playing' => false, 'mediaTime' => 7, 'baseRev' => $rev]], $auth + ['x-host-token' => $host]);
$assert($s === 200 && $b['state']['mediaTime'] === 7.0 && $b['state']['rev'] === $rev + 1, 'host PUT /state');
[$s, $b] = $call('PUT', "/v1/rooms/{$room}/state", [], ['state' => ['playing' => true, 'baseRev' => $rev]], $auth + ['x-host-token' => $host]);
$assert($s === 409 && $b['code'] === 'stale' && isset($b['state']), 'stale baseRev → 409 with the current state');

// --- webhooks ---
[$s, $b] = $call('GET', "/v1/rooms/{$room}/webhooks", [], [], $auth);
$assert($s === 403, 'webhooks need the host token');
[$s, $b] = $call('POST', "/v1/rooms/{$room}/webhooks", [], ['url' => 'http://example.com/x'], $auth + ['x-host-token' => $host]);
$assert($s === 400, 'webhook must be https');
[$s, $b] = $call('POST', "/v1/rooms/{$room}/webhooks", [], ['url' => 'https://127.0.0.1/x'], $auth + ['x-host-token' => $host]);
$assert($s === 400, 'webhook cannot point at a private address');
[$s, $b] = $call('POST', "/v1/rooms/{$room}/webhooks", [], ['url' => 'https://hooks.example.com/a', 'events' => ['message', 'bogus']], $auth + ['x-host-token' => $host]);
$assert($s === 201 && $b['webhook']['events'] === ['message'] && strlen($b['webhook']['secret']) === 48, 'POST /webhooks → 201 with a secret and filtered events');
$hook = $b['webhook'];
[$s, $b] = $call('POST', "/v1/rooms/{$room}/webhooks", [], ['url' => 'https://hooks.example.com/b'], $auth + ['x-host-token' => $host]);
[$s, $b] = $call('POST', "/v1/rooms/{$room}/webhooks", [], ['url' => 'https://hooks.example.com/c'], $auth + ['x-host-token' => $host]);
$assert($s === 429, 'webhook cap per room is enforced');
[$s, $b] = $call('GET', "/v1/rooms/{$room}/webhooks", [], [], $auth + ['x-host-token' => $host]);
$assert($s === 200 && count($b['webhooks']) === 2 && !isset($b['webhooks'][0]['secret']), 'GET /webhooks lists without secrets');
[$s, $b] = $call('DELETE', "/v1/rooms/{$room}/webhooks/{$hook['id']}", [], [], $auth + ['x-host-token' => $host]);
$assert($s === 200 && count($b['webhooks']) === 1, 'DELETE /webhooks/{id}');
$body = Webhooks::envelope($room, 'message', ['text' => 'x']);
$sig = Webhooks::signature('abc', $body);
$assert($sig === 'sha256=' . hash_hmac('sha256', $body, 'abc') && json_decode($body, true)['event'] === 'message', 'webhook signature is HMAC-SHA256 over the raw envelope');

// --- routing details ---
[$s, $b, $h] = $call('DELETE', "/v1/rooms/{$room}", [], [], $auth);
$assert($s === 405 && str_contains($h['Allow'], 'GET') && str_contains($h['Allow'], 'PATCH'), '405 carries Allow');
[$s, $b] = $call('GET', '/v1/nothing');
$assert($s === 404 && $b['code'] === 'not_found', 'unknown endpoint → 404');
$assert($rest->cors('https://site.example')['Access-Control-Allow-Origin'] === 'https://site.example' && $rest->cors('https://evil.example') === [], 'CORS only for configured origins');

// Every router route is documented, and every documented path has a route.
$documented = [];
foreach ($spec['paths'] as $path => $ops) {
    foreach (array_keys($ops) as $verb) {
        $documented[] = strtoupper($verb) . ' ' . $path;
    }
}
$routed = [];
foreach (RestApi::ROUTES as [$verb, $pattern]) {
    $sample = preg_replace(['/\(\?<roomId>[^)]*\)/', '/\(\?<remove>[^)]*\)/', '/\(\?<webhookId>[^)]*\)/'], ['quiet-otter-41', 'p_abc123', 'wh_abc123'], $pattern);
    $sample = str_replace(['#^', '$#', '\.'], ['', '', '.'], $sample);
    $routed[] = $verb . ' ' . $sample;
}
$docSamples = array_map(static fn ($d) => str_replace(['{roomId}', '{itemId}', '{webhookId}'], ['quiet-otter-41', 'p_abc123', 'wh_abc123'], $d), $documented);
$assert(array_diff($routed, $docSamples) === [] && array_diff($docSamples, $routed) === [], 'OpenAPI paths and router routes match exactly');

// --- SSE format ---
$out = '';
$rest->streamEvents(['roomId' => $room, 'memberId' => $ana, 'since' => 0, 'prev' => 0, 'srev' => 0], 1, 50, static function (string $chunk) use (&$out): void { $out .= $chunk; });
$assert(str_starts_with($out, "retry: 1000\n\n") && str_contains($out, "event: message\n") && str_contains($out, "event: state\n") && str_contains($out, "event: playlist\n") && str_contains($out, "event: members\n") && str_ends_with($out, "event: end\ndata: {\"reason\":\"reconnect\"}\n\n"), 'event stream emits retry, message, state, playlist, members and end');
$assert(preg_match('/^id: \d+\nevent: message\ndata: \{.*\}\n\n/m', $out) === 1, 'message events carry their seq as id');

foreach (glob($tmp . '/*/*') ?: [] as $f) { @unlink($f); }
foreach (glob($tmp . '/*') ?: [] as $d) { @rmdir($d); }
@rmdir($tmp);

if ($failures > 0) {
    fwrite(STDERR, "video-chat-player API contract: {$failures} of {$checks} checks failed\n");
    exit(1);
}
echo "video-chat-player API contract: {$checks} checks passed\n";
