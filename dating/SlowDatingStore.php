<?php

declare(strict_types=1);

/**
 * Slow Dating Store
 *
 * Plain-file persistence for the SlowDating app: one JSON file per
 * collection under a state directory. No database, no Composer — the same
 * storage philosophy as the rest of this repository. Every record is an
 * associative array keyed by its id inside the collection file.
 */
final class SlowDatingStore
{
    private string $dir;

    /** @var array<string, array<string, array<string, mixed>>> */
    private array $cache = [];

    public function __construct(?string $dir = null)
    {
        $this->dir = $dir ?? __DIR__ . '/state';
    }

    public function directory(): string
    {
        return $this->dir;
    }

    /**
     * @return array<string, array<string, mixed>> All records keyed by id.
     */
    public function all(string $collection): array
    {
        $this->loadCollection($collection);
        return $this->cache[$collection];
    }

    /**
     * @return array<string, mixed>|null
     */
    public function get(string $collection, string $id): ?array
    {
        $this->loadCollection($collection);
        return $this->cache[$collection][$id] ?? null;
    }

    /**
     * @param array<string, mixed> $record
     */
    public function put(string $collection, string $id, array $record): void
    {
        $this->loadCollection($collection);
        $record['id'] = $id;
        $this->cache[$collection][$id] = $record;
        $this->flush($collection);
    }

    public function delete(string $collection, string $id): void
    {
        $this->loadCollection($collection);
        unset($this->cache[$collection][$id]);
        $this->flush($collection);
    }

    public function count(string $collection): int
    {
        $this->loadCollection($collection);
        return count($this->cache[$collection]);
    }

    /**
     * Find records matching every given field/value pair.
     *
     * @param array<string, mixed> $criteria
     * @return array<int, array<string, mixed>>
     */
    public function where(string $collection, array $criteria): array
    {
        $rows = [];
        foreach ($this->all($collection) as $record) {
            foreach ($criteria as $field => $value) {
                if (($record[$field] ?? null) !== $value) {
                    continue 2;
                }
            }
            $rows[] = $record;
        }
        return $rows;
    }

    private function loadCollection(string $collection): void
    {
        if (isset($this->cache[$collection])) {
            return;
        }
        if (preg_match('/^[a-z_]+$/', $collection) !== 1) {
            throw new InvalidArgumentException('Invalid collection name: ' . $collection);
        }
        $file = $this->path($collection);
        if (!is_file($file)) {
            $this->cache[$collection] = [];
            return;
        }
        $decoded = json_decode((string) file_get_contents($file), true);
        $this->cache[$collection] = is_array($decoded) ? $decoded : [];
    }

    private function flush(string $collection): void
    {
        if (!is_dir($this->dir) && !@mkdir($this->dir, 0775, true) && !is_dir($this->dir)) {
            throw new RuntimeException('Could not create the state directory: ' . $this->dir);
        }
        $json = json_encode($this->cache[$collection], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($json === false || file_put_contents($this->path($collection), $json) === false) {
            throw new RuntimeException('Could not write the ' . $collection . ' collection.');
        }
    }

    private function path(string $collection): string
    {
        return $this->dir . '/' . $collection . '.json';
    }
}
