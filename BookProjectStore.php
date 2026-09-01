<?php

declare(strict_types=1);

/**
 * Book Project Store
 *
 * Every book generation is a project worth keeping. This store writes one
 * JSON record per save under `projects/` — the topic and options, the table
 * of contents, the full manuscript chapters, and the KDP listing metadata —
 * so no outline or manuscript is ever lost between sessions. Plain files,
 * no database, consistent with the rest of the app.
 */
final class BookProjectStore
{
    private string $dir;

    public function __construct(?string $dir = null)
    {
        $this->dir = $dir ?? __DIR__ . '/projects';
    }

    /**
     * Persist a generated book as a project record. Returns the record id.
     *
     * @param string $topic
     * @param array<string, mixed> $options The writeBook options used.
     * @param array<string, mixed> $result The writeBook result (kit/book/kdp/media/outline_review).
     */
    public function save(string $topic, array $options, array $result): string
    {
        if (!is_dir($this->dir) && !@mkdir($this->dir, 0775, true) && !is_dir($this->dir)) {
            throw new RuntimeException('Could not create the projects directory: ' . $this->dir);
        }
        $book = (array) ($result['book'] ?? []);
        $id = $this->slug($topic) . '-' . gmdate('Ymd-His');
        $record = [
            'id' => $id,
            'saved_at' => gmdate(DATE_ATOM),
            'topic' => $topic,
            'options' => $this->scrubOptions($options),
            'metadata' => (array) ($result['kdp']['metadata'] ?? []),
            'outline_review' => (array) ($result['outline_review'] ?? []),
            'table_of_contents' => (array) ($book['table_of_contents'] ?? []),
            'summary' => [
                'style' => (string) ($book['style_label'] ?? ''),
                'chapters' => count((array) ($book['chapters'] ?? [])),
                'page_count' => (int) ($book['page_count'] ?? 0),
                'total_word_count' => (int) ($book['total_word_count'] ?? 0),
            ],
            'chapters' => array_map(
                static fn (array $chapter): array => [
                    'number' => (int) ($chapter['number'] ?? 0),
                    'title' => (string) ($chapter['title'] ?? ''),
                    'purpose' => (string) ($chapter['purpose'] ?? ''),
                    'detail' => (string) ($chapter['detail'] ?? ''),
                    'word_count' => (int) ($chapter['word_count'] ?? 0),
                    'content' => (string) ($chapter['content'] ?? ''),
                ],
                (array) ($book['chapters'] ?? []),
            ),
        ];
        $json = json_encode($record, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($json === false || file_put_contents($this->path($id), $json) === false) {
            throw new RuntimeException('Could not write the project record.');
        }
        return $id;
    }

    /**
     * All saved records, newest first, without the heavy chapter texts.
     *
     * @return array<int, array<string, mixed>>
     */
    public function list(): array
    {
        if (!is_dir($this->dir)) {
            return [];
        }
        $rows = [];
        foreach (glob($this->dir . '/*.json') ?: [] as $file) {
            $record = json_decode((string) file_get_contents($file), true);
            if (!is_array($record) || !isset($record['id'])) {
                continue;
            }
            $rows[] = [
                'id' => (string) $record['id'],
                'saved_at' => (string) ($record['saved_at'] ?? ''),
                'topic' => (string) ($record['topic'] ?? ''),
                'title' => (string) ($record['metadata']['title'] ?? ''),
                'summary' => (array) ($record['summary'] ?? []),
                'chapters' => count((array) ($record['table_of_contents'] ?? [])),
            ];
        }
        usort($rows, static fn (array $a, array $b): int => strcmp($b['id'], $a['id']));
        return $rows;
    }

    /**
     * Load one full record by id.
     *
     * @return array<string, mixed>|null
     */
    public function load(string $id): ?array
    {
        if (preg_match('/^[a-z0-9-]+$/', $id) !== 1) {
            return null;
        }
        $file = $this->path($id);
        if (!is_file($file)) {
            return null;
        }
        $record = json_decode((string) file_get_contents($file), true);
        return is_array($record) ? $record : null;
    }

    public function directory(): string
    {
        return $this->dir;
    }

    private function path(string $id): string
    {
        return $this->dir . '/' . $id . '.json';
    }

    private function slug(string $topic): string
    {
        $slug = strtolower(trim((string) preg_replace('/[^a-z0-9]+/i', '-', $topic), '-'));
        return $slug !== '' ? substr($slug, 0, 60) : 'book';
    }

    /**
     * Options minus anything bulky or sensitive (voice sample paths stay,
     * chapter texts do not — the record already keeps the manuscript).
     *
     * @param array<string, mixed> $options
     * @return array<string, mixed>
     */
    private function scrubOptions(array $options): array
    {
        unset($options['developed_chapters']);
        return $options;
    }
}
