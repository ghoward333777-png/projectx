<?php
declare(strict_types=1);

require_once __DIR__ . '/Http.php';

/**
 * Room webhooks: the host registers https URLs; the server POSTs signed JSON envelopes for
 * chosen events (message, state, playlist, member). Deliveries are best effort, capped by a
 * short timeout, and never block a viewer for more than a moment.
 */
final class Webhooks
{
    public const EVENTS = ['message', 'state', 'playlist', 'member'];

    public static function add(array $room, string $url, array $events, int $max): array
    {
        if (!Http::isPublicHttpsUrl($url)) {
            throw new InvalidArgumentException('Webhook URLs must be public https addresses.');
        }
        $events = array_values(array_intersect(self::EVENTS, array_map('strval', $events)));
        if ($events === []) {
            $events = self::EVENTS;
        }
        $hooks = $room['webhooks'] ?? [];
        if (count($hooks) >= $max) {
            throw new OverflowException("At most {$max} webhooks per room.");
        }
        $hook = ['id' => 'wh_' . bin2hex(random_bytes(6)), 'url' => $url, 'events' => $events, 'secret' => bin2hex(random_bytes(24)), 'createdAt' => (int) floor(microtime(true) * 1000), 'failures' => 0];
        $hooks[] = $hook;
        $room['webhooks'] = $hooks;
        return [$room, $hook];
    }

    public static function remove(array $room, string $id): array
    {
        $room['webhooks'] = array_values(array_filter($room['webhooks'] ?? [], static fn ($h) => $h['id'] !== $id));
        return $room;
    }

    /** Public view: no secrets. */
    public static function listing(array $room): array
    {
        return array_map(static fn ($h) => ['id' => $h['id'], 'url' => $h['url'], 'events' => $h['events'], 'createdAt' => $h['createdAt'], 'failures' => (int) ($h['failures'] ?? 0)], $room['webhooks'] ?? []);
    }

    public static function signature(string $secret, string $body): string
    {
        return 'sha256=' . hash_hmac('sha256', $body, $secret);
    }

    public static function envelope(string $roomId, string $event, array $payload): string
    {
        return json_encode([
            'id' => 'evt_' . bin2hex(random_bytes(8)),
            'event' => $event,
            'roomId' => $roomId,
            'at' => (int) floor(microtime(true) * 1000),
            'data' => $payload,
        ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    }

    /**
     * Sends $event to every hook that subscribed to it. Returns the room (failure counters
     * updated); hooks that fail ten times in a row are dropped so a dead endpoint cannot slow
     * the room forever.
     */
    public static function dispatch(array $room, string $event, array $payload, int $timeout): array
    {
        if (empty($room['webhooks'])) {
            return $room;
        }
        $body = self::envelope($room['id'], $event, $payload);
        foreach ($room['webhooks'] as $i => $hook) {
            if (!in_array($event, $hook['events'], true)) {
                continue;
            }
            $status = Http::postJson($hook['url'], $body, ['X-WatchRoom-Signature: ' . self::signature($hook['secret'], $body), 'X-WatchRoom-Event: ' . $event], $timeout);
            $ok = $status >= 200 && $status < 300;
            $room['webhooks'][$i]['failures'] = $ok ? 0 : (int) ($hook['failures'] ?? 0) + 1;
        }
        $room['webhooks'] = array_values(array_filter($room['webhooks'], static fn ($h) => (int) ($h['failures'] ?? 0) < 10));
        return $room;
    }
}
