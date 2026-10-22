<?php

declare(strict_types=1);

/**
 * Media Graph Store — the UFCS (Universal Fact & Concept Store)
 *
 * A dependency-free graph database for the stock-media intelligence graph.
 * Every piece of knowledge is one fact: subject → predicate → object, where
 * the object is either a node (another vertex in the graph, e.g.
 * `concept:weather/rain`) or a literal (a title, a number, a URL). Facts are
 * held in three in-memory indexes (by subject, by predicate, by object) so
 * FQL patterns resolve from the smallest candidate set, and persisted as
 * sorted JSON Lines under `media-graph/facts.jsonl` — plain files, no
 * database server, consistent with the rest of the app.
 *
 * Saving sorts the facts, so the same inputs always produce the same file.
 */
final class MediaGraphStore
{
    public const NODE = 'n';
    public const LITERAL = 'l';

    private string $dir;
    private bool $loaded = false;

    /** @var array<string, array{s: string, p: string, o: string, k: string}> */
    private array $facts = [];
    /** @var array<string, array<string, true>> */
    private array $bySubject = [];
    /** @var array<string, array<string, true>> */
    private array $byPredicate = [];
    /** @var array<string, array<string, true>> */
    private array $byObject = [];

    public function __construct(?string $dir = null)
    {
        $this->dir = $dir ?? __DIR__ . '/media-graph';
    }

    public function directory(): string
    {
        return $this->dir;
    }

    public function path(): string
    {
        return $this->dir . '/facts.jsonl';
    }

    /** Read the persisted facts into the indexes (once). */
    public function load(): void
    {
        if ($this->loaded) {
            return;
        }
        $this->loaded = true;
        if (!is_file($this->path())) {
            return;
        }
        $handle = fopen($this->path(), 'rb');
        if ($handle === false) {
            throw new RuntimeException('Could not read the media graph: ' . $this->path());
        }
        while (($line = fgets($handle)) !== false) {
            $row = json_decode(trim($line), true);
            if (is_array($row) && isset($row['s'], $row['p'], $row['o'])) {
                $this->add((string) $row['s'], (string) $row['p'], (string) $row['o'], (string) ($row['k'] ?? self::LITERAL));
            }
        }
        fclose($handle);
    }

    /** Write every fact, sorted, atomically. */
    public function save(): void
    {
        $this->load();
        if (!is_dir($this->dir) && !@mkdir($this->dir, 0775, true) && !is_dir($this->dir)) {
            throw new RuntimeException('Could not create the media graph directory: ' . $this->dir);
        }
        $facts = array_values($this->facts);
        usort($facts, static fn (array $a, array $b): int => [$a['s'], $a['p'], $a['k'], $a['o']] <=> [$b['s'], $b['p'], $b['k'], $b['o']]);
        $tmp = $this->path() . '.tmp';
        $handle = fopen($tmp, 'wb');
        if ($handle === false) {
            throw new RuntimeException('Could not write the media graph: ' . $tmp);
        }
        foreach ($facts as $fact) {
            fwrite($handle, json_encode($fact, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
        }
        fclose($handle);
        if (!rename($tmp, $this->path())) {
            throw new RuntimeException('Could not finalize the media graph: ' . $this->path());
        }
    }

    /** Add one fact. Returns false when it already existed. */
    public function add(string $subject, string $predicate, string $object, string $kind = self::NODE): bool
    {
        $this->load();
        $kind = $kind === self::LITERAL ? self::LITERAL : self::NODE;
        $key = $this->key($subject, $predicate, $object, $kind);
        if (isset($this->facts[$key])) {
            return false;
        }
        $this->facts[$key] = ['s' => $subject, 'p' => $predicate, 'o' => $object, 'k' => $kind];
        $this->bySubject[$subject][$key] = true;
        $this->byPredicate[$predicate][$key] = true;
        $this->byObject[$kind . "\x1f" . $object][$key] = true;
        return true;
    }

    /**
     * Replace everything known about one subject — re-harvesting a video
     * refreshes its facts instead of piling up stale view counts.
     *
     * @param array<int, array{0: string, 1: string, 2: string}> $facts [predicate, object, kind]
     */
    public function replaceSubject(string $subject, array $facts): void
    {
        $this->load();
        foreach (array_keys($this->bySubject[$subject] ?? []) as $key) {
            $this->remove($key);
        }
        foreach ($facts as [$predicate, $object, $kind]) {
            $this->add($subject, $predicate, $object, $kind);
        }
    }

    /**
     * Every fact matching the given positions (null = any).
     *
     * @return array<int, array{s: string, p: string, o: string, k: string}>
     */
    public function match(?string $subject = null, ?string $predicate = null, ?string $object = null, ?string $kind = null): array
    {
        $this->load();
        $candidates = null;
        if ($subject !== null) {
            $candidates = $this->bySubject[$subject] ?? [];
        }
        if ($object !== null) {
            $keys = [];
            foreach ($kind === null ? [self::NODE, self::LITERAL] : [$kind] as $k) {
                $keys += $this->byObject[$k . "\x1f" . $object] ?? [];
            }
            $candidates = $candidates === null || count($keys) < count($candidates) ? $keys : $candidates;
        }
        if ($predicate !== null) {
            $keys = $this->byPredicate[$predicate] ?? [];
            $candidates = $candidates === null || count($keys) < count($candidates) ? $keys : $candidates;
        }
        $candidates ??= $this->facts;

        $out = [];
        foreach (array_keys($candidates) as $key) {
            $fact = $this->facts[$key];
            if (($subject === null || $fact['s'] === $subject)
                && ($predicate === null || $fact['p'] === $predicate)
                && ($object === null || $fact['o'] === $object)
                && ($kind === null || $fact['k'] === $kind)) {
                $out[] = $fact;
            }
        }
        return $out;
    }

    public function count(): int
    {
        $this->load();
        return count($this->facts);
    }

    public function subjectCount(): int
    {
        $this->load();
        return count($this->bySubject);
    }

    /** @return array<string, int> predicate => fact count, largest first */
    public function predicateCounts(): array
    {
        $this->load();
        $counts = array_map('count', $this->byPredicate);
        arsort($counts);
        return $counts;
    }

    /** Forget every fact (in memory and on disk). */
    public function clear(): void
    {
        $this->facts = $this->bySubject = $this->byPredicate = $this->byObject = [];
        $this->loaded = true;
        if (is_file($this->path())) {
            unlink($this->path());
        }
    }

    /** Canonical text for a numeric literal, so `4`, `4.0` and "4" match. */
    public static function number(float|int|string $value): string
    {
        $n = (float) $value;
        if (floor($n) === $n && abs($n) < 1e15) {
            return (string) (int) $n;
        }
        return rtrim(rtrim(number_format($n, 3, '.', ''), '0'), '.');
    }

    private function remove(string $key): void
    {
        $fact = $this->facts[$key] ?? null;
        if ($fact === null) {
            return;
        }
        unset($this->facts[$key], $this->bySubject[$fact['s']][$key], $this->byPredicate[$fact['p']][$key]);
        $objectKey = $fact['k'] . "\x1f" . $fact['o'];
        unset($this->byObject[$objectKey][$key]);
        if (($this->bySubject[$fact['s']] ?? null) === []) {
            unset($this->bySubject[$fact['s']]);
        }
        if (($this->byPredicate[$fact['p']] ?? null) === []) {
            unset($this->byPredicate[$fact['p']]);
        }
        if (($this->byObject[$objectKey] ?? null) === []) {
            unset($this->byObject[$objectKey]);
        }
    }

    private function key(string $s, string $p, string $o, string $k): string
    {
        return md5($s . "\x1f" . $p . "\x1f" . $k . "\x1f" . $o);
    }
}
