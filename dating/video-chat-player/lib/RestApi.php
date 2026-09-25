<?php
declare(strict_types=1);

require_once __DIR__ . '/WatchRoomApi.php';
require_once __DIR__ . '/OpenApi.php';

/**
 * The versioned REST surface (/v1/...) over WatchRoomApi's actions. Resource paths,
 * HTTP verbs, Bearer member tokens, host tokens and API keys live here; the actions
 * themselves stay in WatchRoomApi so the web page and the API cannot drift apart.
 *
 * Auth model:
 *  - Authorization: Bearer <memberId>   identifies the member (returned by POST /v1/rooms or /members)
 *  - X-Host-Token: <hostToken>          proves host rights (returned once by POST /v1/rooms)
 *  - X-Api-Key: <key>                   required for POST /v1/rooms when config api_key is set
 */
final class RestApi
{
    /** [method, pattern, action, needs] — needs: 'member' | 'host' | 'none' | 'key' */
    public const ROUTES = [
        ['GET', '#^/v1/health$#', 'health', 'none'],
        ['GET', '#^/v1/openapi\.json$#', 'openapi', 'none'],
        ['GET', '#^/v1/resolve$#', 'resolve', 'none'],
        ['GET', '#^/v1/oembed$#', 'oembed', 'none'],
        ['POST', '#^/v1/rooms$#', 'room.create', 'key'],
        ['GET', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)$#', 'room.get', 'member'],
        ['PATCH', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)$#', 'room.settings', 'host'],
        ['POST', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/members$#', 'room.join', 'none'],
        ['PATCH', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/members/me$#', 'room.join', 'member'],
        ['GET', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/messages$#', 'messages.list', 'member'],
        ['POST', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/messages$#', 'chat.send', 'member'],
        ['GET', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/sync$#', 'sync.poll', 'member'],
        ['GET', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/events$#', 'events', 'member'],
        ['GET', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/playlist$#', 'playlist.get', 'member'],
        ['POST', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/playlist$#', 'playlist.add', 'member'],
        ['POST', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/playlist/import$#', 'playlist.import', 'member'],
        ['PATCH', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/playlist$#', 'playlist.set', 'member'],
        ['DELETE', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/playlist/(?<remove>p_[a-f0-9]+)$#', 'playlist.set', 'member'],
        ['GET', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/state$#', 'state.get', 'member'],
        ['PUT', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/state$#', 'state.set', 'member'],
        ['GET', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/webhooks$#', 'webhook.list', 'host'],
        ['POST', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/webhooks$#', 'webhook.add', 'host'],
        ['DELETE', '#^/v1/rooms/(?<roomId>[a-z-]+\d\d)/webhooks/(?<webhookId>wh_[a-f0-9]+)$#', 'webhook.remove', 'host'],
    ];

    public function __construct(private readonly WatchRoomApi $api, private readonly array $config)
    {
    }

    /**
     * Resolves a request to [status, body, headers]. `events` is returned as a special
     * body ['__sse' => input] for api.php to stream.
     * @param array<string, string> $headers lower-case header names
     * @return array{0: int, 1: array, 2: array<string, string>}
     */
    public function dispatch(string $method, string $path, array $query, array $body, array $headers, string $baseUrl = ''): array
    {
        $method = strtoupper($method);
        $path = '/' . trim($path, '/');
        $extra = ['Cache-Control' => 'no-store'];
        $matchedPath = false;
        foreach (self::ROUTES as [$verb, $pattern, $action, $needs]) {
            if (preg_match($pattern, $path, $m) !== 1) {
                continue;
            }
            $matchedPath = true;
            if ($verb !== $method) {
                continue;
            }
            $input = $body + $query;
            foreach ($m as $k => $v) {
                if (is_string($k)) {
                    $input[$k] = $v;
                }
            }
            $bearer = self::bearer($headers);
            if ($bearer !== '') {
                $input['memberId'] = $bearer;
            }
            if (isset($headers['x-host-token'])) {
                $input['hostToken'] = $headers['x-host-token'];
            }
            if (in_array($needs, ['member', 'host'], true) && ($input['memberId'] ?? '') === '') {
                return [401, ['error' => 'Send the member id as a Bearer token.', 'code' => 'unauthorized'], $extra + ['WWW-Authenticate' => 'Bearer realm="watchroom"']];
            }
            if ($needs === 'host' && ($input['hostToken'] ?? '') === '') {
                return [403, ['error' => 'This needs the X-Host-Token header.', 'code' => 'forbidden'], $extra];
            }
            if ($needs === 'key' && $this->config['api_key'] !== '' && !hash_equals($this->config['api_key'], (string) ($headers['x-api-key'] ?? ''))) {
                return [401, ['error' => 'A valid X-Api-Key header is required to create rooms through the API.', 'code' => 'unauthorized'], $extra];
            }
            if ($action === 'openapi') {
                return [200, OpenApi::spec($baseUrl), $extra + ['Cache-Control' => 'public, max-age=300']];
            }
            if ($action === 'events') {
                return [200, ['__sse' => $input], $extra];
            }
            if ($action === 'oembed') {
                return $this->oembed($input, $baseUrl);
            }
            // A REST verb always maps to the action's expected method.
            [$status, $payload] = $this->api->handle($action, $action === 'health' || str_ends_with($action, '.get') || $action === 'messages.list' || $action === 'sync.poll' || $action === 'resolve' || $action === 'webhook.list' ? 'GET' : 'POST', $input);
            if ($status === 200 && $method === 'POST' && in_array($action, ['room.create', 'chat.send', 'playlist.add', 'playlist.import'], true)) {
                $status = 201;
            }
            return [$status, $payload, $extra];
        }
        if ($matchedPath) {
            return [405, ['error' => 'Method not allowed for this path.', 'code' => 'method'], $extra + ['Allow' => implode(', ', self::allowed($path))]];
        }
        return [404, ['error' => 'No such endpoint. See /v1/openapi.json.', 'code' => 'not_found'], $extra];
    }

    /** @return list<string> */
    public static function allowed(string $path): array
    {
        $out = [];
        foreach (self::ROUTES as [$verb, $pattern]) {
            if (preg_match($pattern, $path) === 1) {
                $out[] = $verb;
            }
        }
        return array_values(array_unique($out));
    }

    public static function bearer(array $headers): string
    {
        $auth = (string) ($headers['authorization'] ?? '');
        return preg_match('/^Bearer\s+(m_[a-f0-9]{16})$/i', trim($auth), $m) === 1 ? $m[1] : '';
    }

    /** CORS headers for an origin, or [] when the origin is not allowed. @return array<string, string> */
    /**
     * oEmbed (https://oembed.com): turn a room, embed or player URL into an embeddable
     * snippet, so platforms that understand oEmbed embed Watch Room automatically.
     * @return array{0: int, 1: array, 2: array<string, string>}
     */
    public function oembed(array $input, string $baseUrl): array
    {
        $url = (string) ($input['url'] ?? '');
        $parts = parse_url($url);
        $room = '';
        if (is_array($parts)) {
            parse_str((string) ($parts['query'] ?? ''), $q);
            $room = isset($q['room']) && RoomStore::isRoomId((string) $q['room']) ? (string) $q['room'] : '';
        }
        if ($url === '' || !is_array($parts) || !preg_match('#/(index|embed)\.php$#', (string) ($parts['path'] ?? ''))) {
            return [404, ['error' => 'Give the URL of a Watch Room page (index.php or embed.php, optionally with ?room=).', 'code' => 'not_found'], ['Cache-Control' => 'no-store']];
        }
        $appBase = preg_replace('#api\.php$#', '', $baseUrl) ?? $baseUrl;
        $embed = $appBase . 'embed.php' . ($room !== '' ? '?room=' . rawurlencode($room) : '');
        $width = max(200, min(4096, (int) ($input['maxwidth'] ?? 800)));
        $height = max(113, min(2304, (int) ($input['maxheight'] ?? (int) round($width * 9 / 16))));
        return [200, [
            'version' => '1.0',
            'type' => 'rich',
            'provider_name' => 'Watch Room',
            'provider_url' => $appBase,
            'title' => $room !== '' ? "Watch Room {$room}" : 'Watch Room',
            'html' => '<iframe src="' . htmlspecialchars($embed, ENT_QUOTES, 'UTF-8') . '" width="' . $width . '" height="' . $height . '" allow="autoplay; fullscreen; clipboard-write" allowfullscreen style="border:0"></iframe>',
            'width' => $width,
            'height' => $height,
        ], ['Cache-Control' => 'public, max-age=300']];
    }

    public function cors(string $origin): array
    {
        if ($this->config['cors_origins'] === ['*']) {
            return [
                'Access-Control-Allow-Origin' => '*',
                'Access-Control-Allow-Methods' => 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
                'Access-Control-Allow-Headers' => 'Authorization, Content-Type, X-Host-Token, X-Api-Key',
                'Access-Control-Max-Age' => '600',
            ];
        }
        if ($origin === '' || !in_array($origin, $this->config['cors_origins'], true)) {
            return [];
        }
        return [
            'Access-Control-Allow-Origin' => $origin,
            'Vary' => 'Origin',
            'Access-Control-Allow-Methods' => 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
            'Access-Control-Allow-Headers' => 'Authorization, Content-Type, X-Host-Token, X-Api-Key',
            'Access-Control-Max-Age' => '600',
        ];
    }

    /**
     * Server-sent events: polls the room every interval and writes messages, state,
     * playlist and members as they change, for up to $seconds, then ends so the client
     * reconnects (EventSource does that by itself; the app's SDK too).
     */
    public function streamEvents(array $input, int $seconds, int $intervalMs, callable $write, ?callable $aborted = null): void
    {
        $since = max(0, (int) ($input['since'] ?? 0));
        $prev = max(0, (int) ($input['prev'] ?? 0));
        $srev = max(0, (int) ($input['srev'] ?? 0));
        $membersKey = '';
        $deadline = microtime(true) + $seconds;
        $lastPing = microtime(true);
        $write("retry: 1000\n\n");
        while (microtime(true) < $deadline) {
            if ($aborted !== null && $aborted()) {
                return;
            }
            [$status, $data] = $this->api->handle('sync.poll', 'GET', ['roomId' => $input['roomId'] ?? '', 'memberId' => $input['memberId'] ?? '', 'since' => $since, 'prev' => $prev, 'srev' => $srev]);
            if ($status !== 200) {
                $write(self::sse('error', $data, 'end'));
                return;
            }
            foreach ($data['messages'] ?? [] as $message) {
                $since = max($since, (int) $message['seq']);
                $write(self::sse('message', $message, (string) $message['seq']));
            }
            if (isset($data['state'])) {
                $srev = (int) $data['state']['rev'];
                $write(self::sse('state', $data['state'], 's' . $srev));
            }
            if (isset($data['playlist'])) {
                $prev = (int) $data['playlist']['rev'];
                $write(self::sse('playlist', $data['playlist'], 'p' . $prev));
            }
            $key = json_encode(array_map(static fn ($m) => [$m['id'], $m['name'], $m['online']], $data['members'] ?? []));
            if ($key !== $membersKey) {
                $membersKey = $key;
                $write(self::sse('members', ['members' => $data['members'], 'actingHostId' => $data['actingHostId'] ?? null]));
            }
            if (microtime(true) - $lastPing >= 10) {
                $lastPing = microtime(true);
                $write(self::sse('ping', ['serverTime' => $data['serverTime']]));
            }
            usleep($intervalMs * 1000);
        }
        $write(self::sse('end', ['reason' => 'reconnect']));
    }

    public static function sse(string $event, array $data, ?string $id = null): string
    {
        return ($id !== null ? "id: {$id}\n" : '') . "event: {$event}\ndata: " . json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n\n";
    }
}
