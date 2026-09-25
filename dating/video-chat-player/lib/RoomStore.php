<?php
declare(strict_types=1);

/**
 * Rooms are folders under rooms/<id>/ with room.json (atomic writes) and messages.jsonl.
 * A room is a link; a member is a display name plus a random id kept in the browser.
 */
require_once __DIR__ . '/Text.php';

final class RoomStore
{
    public const NAME_MAX = 32;
    public const IDLE_MAX_AGE = 86400; // rooms untouched for 24 h are removed by gc()
    private const ADJECTIVES = ['quiet', 'amber', 'brisk', 'calm', 'clever', 'cosy', 'crisp', 'dusky', 'eager', 'gentle', 'golden', 'happy', 'humble', 'jolly', 'keen', 'lively', 'lucky', 'mellow', 'merry', 'misty', 'noble', 'plucky', 'proud', 'rapid', 'rosy', 'silver', 'sleepy', 'snug', 'sunny', 'swift', 'tidy', 'velvet', 'vivid', 'warm', 'witty', 'zesty'];
    private const NOUNS = ['otter', 'heron', 'maple', 'comet', 'harbor', 'lantern', 'meadow', 'orchid', 'pebble', 'river', 'saddle', 'thistle', 'walnut', 'willow', 'anchor', 'beacon', 'canyon', 'dune', 'ember', 'falcon', 'glacier', 'island', 'juniper', 'kestrel', 'lagoon', 'marble', 'nectar', 'oak', 'prairie', 'quartz', 'raven', 'summit', 'tundra', 'valley', 'wren', 'zephyr'];
    private const COLOURS = ['#ff8fb1', '#8fd3ff', '#ffd97a', '#a6f0c6', '#d9b3ff', '#ffb38a', '#9be7e0', '#f2a4ff'];

    public function __construct(private readonly string $dir)
    {
    }

    public function dir(): string { return $this->dir; }

    public function path(string $roomId): string { return $this->dir . '/' . $roomId; }

    public static function isRoomId(string $id): bool
    {
        return preg_match('/^[a-z]{3,10}-[a-z]{3,10}-\d{2}$/', $id) === 1;
    }

    public static function cleanName(string $name): string
    {
        $name = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', $name) ?? '';
        $name = trim(preg_replace('/\s+/u', ' ', $name) ?? '');
        if ($name === '') {
            return '';
        }
        return Text::cut($name, self::NAME_MAX);
    }

    /** @return array{room: array, member: array, hostToken: string} */
    public function create(string $name): array
    {
        $name = self::cleanName($name);
        if ($name === '') {
            throw new InvalidArgumentException('A display name is required.');
        }
        if (!is_dir($this->dir) && !mkdir($this->dir, 0775, true) && !is_dir($this->dir)) {
            throw new RuntimeException('Cannot create the rooms folder.');
        }
        do {
            $id = self::ADJECTIVES[random_int(0, count(self::ADJECTIVES) - 1)] . '-'
                . self::NOUNS[random_int(0, count(self::NOUNS) - 1)] . '-'
                . str_pad((string) random_int(0, 99), 2, '0', STR_PAD_LEFT);
        } while (is_dir($this->path($id)));
        mkdir($this->path($id), 0775, true);
        $hostToken = bin2hex(random_bytes(32));
        $now = self::now();
        $member = $this->newMember($name, 0, $now);
        $room = [
            'id' => $id,
            'createdAt' => $now,
            'updatedAt' => $now,
            'hostMemberId' => $member['id'],
            'hostTokenHash' => hash('sha256', $hostToken),
            'chatMode' => 'overlay',
            'guestsControl' => true,
            'members' => [$member['id'] => $member],
        ];
        $this->save($room);
        return ['room' => $room, 'member' => $member, 'hostToken' => $hostToken];
    }

    /** Join as a returning member (id known) or a new one. @return array{room: array, member: array} */
    public function join(string $roomId, string $name, ?string $memberId = null): array
    {
        $room = $this->load($roomId);
        if ($room === null) {
            throw new RuntimeException('That room does not exist or has expired.');
        }
        $name = self::cleanName($name);
        if ($name === '') {
            throw new InvalidArgumentException('A display name is required.');
        }
        $now = self::now();
        if ($memberId !== null && isset($room['members'][$memberId])) {
            $member = $room['members'][$memberId];
            $member['name'] = $name;
            $member['lastSeen'] = $now;
        } else {
            $member = $this->newMember($name, count($room['members']), $now);
        }
        $room['members'][$member['id']] = $member;
        $room['updatedAt'] = $now;
        $this->save($room);
        return ['room' => $room, 'member' => $member];
    }

    public function load(string $roomId): ?array
    {
        if (!self::isRoomId($roomId)) {
            return null;
        }
        $file = $this->path($roomId) . '/room.json';
        if (!is_file($file)) {
            return null;
        }
        $data = json_decode((string) file_get_contents($file), true);
        return is_array($data) ? $data : null;
    }

    public function save(array $room): void
    {
        $file = $this->path($room['id']) . '/room.json';
        $tmp = $file . '.' . bin2hex(random_bytes(4)) . '.tmp';
        file_put_contents($tmp, json_encode($room, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
        rename($tmp, $file);
    }

    /** Records that a member is still here; cheap enough to run on every poll. */
    public function touch(array $room, string $memberId): array
    {
        if (!isset($room['members'][$memberId])) {
            return $room;
        }
        $now = self::now();
        if ($now - (int) $room['members'][$memberId]['lastSeen'] < 3000 && $now - (int) $room['updatedAt'] < 3000) {
            return $room;
        }
        $room['members'][$memberId]['lastSeen'] = $now;
        $room['updatedAt'] = $now;
        $this->save($room);
        return $room;
    }

    public function isHost(array $room, string $token): bool
    {
        return $token !== '' && hash_equals((string) $room['hostTokenHash'], hash('sha256', $token));
    }

    /** Members as the client sees them: no secrets, plus an online flag. @return list<array> */
    public static function publicMembers(array $room): array
    {
        $now = self::now();
        $out = [];
        foreach ($room['members'] as $m) {
            $out[] = [
                'id' => $m['id'],
                'name' => $m['name'],
                'colour' => $m['colour'],
                'online' => ($now - (int) $m['lastSeen']) < 15000,
                'host' => $m['id'] === $room['hostMemberId'],
                'joinedAt' => (int) $m['joinedAt'],
            ];
        }
        return $out;
    }

    /** Removes rooms idle longer than $maxAge seconds. Returns how many were removed. */
    public function gc(int $maxAge = self::IDLE_MAX_AGE): int
    {
        if (!is_dir($this->dir)) {
            return 0;
        }
        $removed = 0;
        $cutoff = time() - $maxAge;
        foreach (scandir($this->dir) ?: [] as $entry) {
            if (!self::isRoomId($entry)) {
                continue;
            }
            $path = $this->path($entry);
            $file = $path . '/room.json';
            $mtime = is_file($file) ? (int) filemtime($file) : (int) filemtime($path);
            if ($mtime > $cutoff) {
                continue;
            }
            foreach (glob($path . '/*') ?: [] as $f) {
                @unlink($f);
            }
            if (@rmdir($path)) {
                $removed++;
            }
        }
        return $removed;
    }

    public static function now(): int
    {
        return (int) floor(microtime(true) * 1000);
    }

    private function newMember(string $name, int $index, int $now): array
    {
        return [
            'id' => 'm_' . bin2hex(random_bytes(8)),
            'name' => $name,
            'colour' => self::COLOURS[$index % count(self::COLOURS)],
            'joinedAt' => $now,
            'lastSeen' => $now,
        ];
    }

    /**
     * The member allowed to drive playback for everyone right now: the host while online,
     * otherwise the online member who joined earliest. Null when nobody is online.
     */
    public static function actingHostId(array $room): ?string
    {
        $now = self::now();
        $host = $room['members'][$room['hostMemberId']] ?? null;
        if ($host !== null && $now - (int) $host['lastSeen'] < 15000) {
            return $host['id'];
        }
        $best = null;
        foreach ($room['members'] as $m) {
            if ($now - (int) $m['lastSeen'] >= 15000) {
                continue;
            }
            if ($best === null || (int) $m['joinedAt'] < (int) $best['joinedAt']) {
                $best = $m;
            }
        }
        return $best['id'] ?? null;
    }
}
