<?php
declare(strict_types=1);

/**
 * Append-only JSONL message log for one room. `seq` is the polling cursor: clients ask
 * for everything after the last seq they saw. Duplicate client ids are ignored so a
 * retried send never double-posts.
 */
require_once __DIR__ . '/Text.php';

final class MessageLog
{
    public const TEXT_MAX = 500;
    public const RATE_LIMIT_COUNT = 5;
    public const RATE_LIMIT_WINDOW_MS = 5000;

    public function __construct(private readonly string $file)
    {
    }

    public static function cleanText(string $text): string
    {
        $text = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]+/u', '', $text) ?? '';
        $text = trim(preg_replace('/[ \t]+/u', ' ', $text) ?? '');
        return Text::cut($text, self::TEXT_MAX);
    }

    /**
     * Appends a message and returns it with its seq, or the existing message when the
     * client id was already stored. Throws on rate-limit violations.
     */
    public function append(array $message): array
    {
        $fh = fopen($this->file, 'c+');
        if ($fh === false) {
            throw new RuntimeException('Cannot open the message log.');
        }
        try {
            if (!flock($fh, LOCK_EX)) {
                throw new RuntimeException('Cannot lock the message log.');
            }
            $recent = $this->tail($fh, 64);
            $lastSeq = 0;
            $sameMemberInWindow = 0;
            $cutoff = RoomStore::now() - self::RATE_LIMIT_WINDOW_MS;
            foreach ($recent as $existing) {
                $lastSeq = max($lastSeq, (int) $existing['seq']);
                if ($existing['id'] === $message['id']) {
                    return $existing;
                }
                if ($existing['kind'] === 'chat' && $existing['memberId'] === $message['memberId'] && (int) $existing['sentAt'] >= $cutoff) {
                    $sameMemberInWindow++;
                }
            }
            if ($message['kind'] === 'chat' && $sameMemberInWindow >= self::RATE_LIMIT_COUNT) {
                throw new OverflowException('Slow down: at most ' . self::RATE_LIMIT_COUNT . ' messages every ' . (self::RATE_LIMIT_WINDOW_MS / 1000) . ' seconds.');
            }
            $message['seq'] = $lastSeq + 1;
            fseek($fh, 0, SEEK_END);
            fwrite($fh, json_encode($message, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
            fflush($fh);
            return $message;
        } finally {
            flock($fh, LOCK_UN);
            fclose($fh);
        }
    }

    /** Messages with seq > $since, oldest first, at most $limit. @return list<array> */
    public function since(int $since, int $limit = 200): array
    {
        if (!is_file($this->file)) {
            return [];
        }
        $out = [];
        $fh = fopen($this->file, 'r');
        if ($fh === false) {
            return [];
        }
        flock($fh, LOCK_SH);
        while (($line = fgets($fh)) !== false) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $m = json_decode($line, true);
            if (!is_array($m) || (int) ($m['seq'] ?? 0) <= $since) {
                continue;
            }
            $out[] = $m;
            if (count($out) >= $limit) {
                break;
            }
        }
        flock($fh, LOCK_UN);
        fclose($fh);
        return $out;
    }

    /** The newest $n messages, oldest first. @return list<array> */
    public function latest(int $n): array
    {
        if (!is_file($this->file)) {
            return [];
        }
        $fh = fopen($this->file, 'r');
        if ($fh === false) {
            return [];
        }
        flock($fh, LOCK_SH);
        $rows = $this->tail($fh, $n);
        flock($fh, LOCK_UN);
        fclose($fh);
        return $rows;
    }

    public function lastSeq(): int
    {
        $rows = $this->latest(1);
        return $rows === [] ? 0 : (int) $rows[0]['seq'];
    }

    /** @param resource $fh @return list<array> */
    private function tail($fh, int $n): array
    {
        $stat = fstat($fh);
        $size = (int) ($stat['size'] ?? 0);
        if ($size === 0) {
            return [];
        }
        $chunk = 8192;
        $pos = $size;
        $buffer = '';
        while ($pos > 0 && substr_count($buffer, "\n") <= $n) {
            $read = min($chunk, $pos);
            $pos -= $read;
            fseek($fh, $pos);
            $buffer = fread($fh, $read) . $buffer;
        }
        $lines = array_values(array_filter(explode("\n", $buffer), static fn (string $l): bool => trim($l) !== ''));
        $lines = array_slice($lines, -$n);
        $out = [];
        foreach ($lines as $line) {
            $m = json_decode($line, true);
            if (is_array($m)) {
                $out[] = $m;
            }
        }
        return $out;
    }
}
