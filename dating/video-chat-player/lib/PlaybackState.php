<?php
declare(strict_types=1);

/** The shared playback clock: what everyone should be watching, and where, right now. */
final class PlaybackState
{
    public static function initial(?string $itemId): array
    {
        return ['rev' => 1, 'itemId' => $itemId, 'playing' => false, 'mediaTime' => 0.0, 'at' => self::now(), 'rate' => 1.0, 'by' => null];
    }

    public static function load(string $roomPath, ?string $fallbackItemId = null): array
    {
        $file = $roomPath . '/state.json';
        if (!is_file($file)) {
            return self::initial($fallbackItemId);
        }
        $data = json_decode((string) file_get_contents($file), true);
        return is_array($data) && isset($data['rev']) ? $data : self::initial($fallbackItemId);
    }

    /**
     * Applies a client update. Returns the new state, or null when the update is stale
     * (its baseRev is older than the stored rev) so two hosts cannot fight.
     */
    public static function apply(string $roomPath, array $current, array $update, string $by): ?array
    {
        $baseRev = (int) ($update['baseRev'] ?? $current['rev']);
        if ($baseRev < (int) $current['rev']) {
            return null;
        }
        $state = [
            'rev' => (int) $current['rev'] + 1,
            'itemId' => isset($update['itemId']) && is_string($update['itemId']) ? $update['itemId'] : $current['itemId'],
            'playing' => (bool) ($update['playing'] ?? $current['playing']),
            'mediaTime' => round(max(0.0, (float) ($update['mediaTime'] ?? 0)), 3),
            'at' => self::now(),
            'rate' => self::cleanRate($update['rate'] ?? $current['rate']),
            'by' => $by,
        ];
        $file = $roomPath . '/state.json';
        $tmp = $file . '.' . bin2hex(random_bytes(4)) . '.tmp';
        file_put_contents($tmp, json_encode($state));
        rename($tmp, $file);
        return $state;
    }

    /** Where the media should be at $nowMs according to the state. */
    public static function expectedPosition(array $state, int $nowMs): float
    {
        if (!$state['playing']) {
            return (float) $state['mediaTime'];
        }
        return (float) $state['mediaTime'] + (($nowMs - (int) $state['at']) / 1000) * (float) $state['rate'];
    }

    public static function cleanRate(mixed $rate): float
    {
        $r = is_numeric($rate) ? (float) $rate : 1.0;
        return in_array($r, [0.5, 0.75, 1.0, 1.25, 1.5, 2.0], true) ? $r : 1.0;
    }

    public static function now(): int
    {
        return (int) floor(microtime(true) * 1000);
    }
}
