<?php

declare(strict_types=1);

require_once __DIR__ . '/ManuscriptHygiene.php';

/**
 * Blog Store
 *
 * Articles are read from `data/blog-articles.json`; reader comments are kept
 * as one JSON file per article under `blog-comments/`. Plain files, no
 * database, consistent with the rest of the app.
 */
final class BlogStore
{
    public const MAX_NAME = 60;
    public const MAX_BODY = 2000;
    public const MIN_BODY = 2;
    public const MAX_COMMENTS_PER_ARTICLE = 500;

    private string $articlesFile;
    private string $commentsDir;

    /** @var array<int, array<string, mixed>>|null */
    private ?array $articles = null;

    public function __construct(?string $commentsDir = null, ?string $articlesFile = null)
    {
        $this->commentsDir = $commentsDir ?? __DIR__ . '/blog-comments';
        $this->articlesFile = $articlesFile ?? __DIR__ . '/data/blog-articles.json';
    }

    /** @return array<int, array<string, mixed>> Articles in editorial order (featured first). */
    public function articles(): array
    {
        if ($this->articles !== null) {
            return $this->articles;
        }
        $raw = @file_get_contents($this->articlesFile);
        $decoded = $raw === false ? null : json_decode($raw, true);
        if (!is_array($decoded)) {
            throw new RuntimeException('The blog articles file is missing or is not valid JSON: ' . $this->articlesFile);
        }
        $articles = [];
        foreach ($decoded as $article) {
            if (!is_array($article) || !self::validSlug((string) ($article['slug'] ?? ''))) {
                continue;
            }
            $article['blocks'] = array_values(array_filter((array) ($article['blocks'] ?? []), 'is_array'));
            $article['tags'] = array_values(array_map('strval', (array) ($article['tags'] ?? [])));
            $article['read_minutes'] = self::readMinutes($article['blocks']);
            $articles[] = $article;
        }
        return $this->articles = $articles;
    }

    /** @return array<string, mixed>|null */
    public function article(string $slug): ?array
    {
        foreach ($this->articles() as $article) {
            if ($article['slug'] === $slug) {
                return $article;
            }
        }
        return null;
    }

    /** @return array<int, string> Every tag in use, in first-seen order. */
    public function tags(): array
    {
        $tags = [];
        foreach ($this->articles() as $article) {
            foreach ($article['tags'] as $tag) {
                $tags[$tag] = true;
            }
        }
        return array_keys($tags);
    }

    /**
     * Every video across the blog, in editorial order, without repeats.
     *
     * @return array<int, array{id: string, title: string, channel: string, slug: string}>
     */
    public function videos(): array
    {
        $videos = [];
        foreach ($this->articles() as $article) {
            foreach ($article['blocks'] as $block) {
                $id = (string) ($block['id'] ?? '');
                if (($block['type'] ?? '') === 'video' && self::validVideoId($id) && !isset($videos[$id])) {
                    $videos[$id] = [
                        'id' => $id,
                        'title' => (string) ($block['title'] ?? ''),
                        'channel' => (string) ($block['channel'] ?? ''),
                        'slug' => (string) $article['slug'],
                    ];
                }
            }
        }
        return array_values($videos);
    }

    /** @return array<int, array{id: string, name: string, body: string, at: string}> Oldest first. */
    public function comments(string $slug): array
    {
        if ($this->article($slug) === null) {
            return [];
        }
        $raw = @file_get_contents($this->commentsFile($slug));
        $decoded = $raw === false ? [] : json_decode($raw, true);
        $comments = [];
        foreach (is_array($decoded) ? $decoded : [] as $row) {
            if (is_array($row) && isset($row['name'], $row['body'])) {
                $comments[] = [
                    'id' => (string) ($row['id'] ?? ''),
                    'name' => (string) $row['name'],
                    'body' => (string) $row['body'],
                    'at' => (string) ($row['at'] ?? ''),
                ];
            }
        }
        return $comments;
    }

    public function commentCount(string $slug): int
    {
        return count($this->comments($slug));
    }

    /**
     * Validate and store one comment.
     *
     * @return array{ok: bool, error: string, id: string}
     */
    public function addComment(string $slug, string $name, string $body): array
    {
        if ($this->article($slug) === null) {
            return ['ok' => false, 'error' => 'That article does not exist.', 'id' => ''];
        }
        $name = ManuscriptHygiene::cleanLine($name);
        $body = ManuscriptHygiene::clean($body);
        if ($name === '') {
            return ['ok' => false, 'error' => 'Please add your name.', 'id' => ''];
        }
        if (self::length($name) > self::MAX_NAME) {
            return ['ok' => false, 'error' => 'Names can be up to ' . self::MAX_NAME . ' characters.', 'id' => ''];
        }
        if (self::length($body) < self::MIN_BODY) {
            return ['ok' => false, 'error' => 'Please write a comment before posting.', 'id' => ''];
        }
        if (self::length($body) > self::MAX_BODY) {
            return ['ok' => false, 'error' => 'Comments can be up to ' . self::MAX_BODY . ' characters.', 'id' => ''];
        }
        if (!is_dir($this->commentsDir) && !@mkdir($this->commentsDir, 0775, true) && !is_dir($this->commentsDir)) {
            return ['ok' => false, 'error' => 'Comments cannot be saved right now (the comments folder is not writable).', 'id' => ''];
        }

        $handle = @fopen($this->commentsFile($slug), 'c+');
        if ($handle === false) {
            return ['ok' => false, 'error' => 'Comments cannot be saved right now (the comments folder is not writable).', 'id' => ''];
        }
        try {
            flock($handle, LOCK_EX);
            $existing = json_decode((string) stream_get_contents($handle), true);
            $existing = is_array($existing) ? $existing : [];
            if (count($existing) >= self::MAX_COMMENTS_PER_ARTICLE) {
                return ['ok' => false, 'error' => 'This discussion is full.', 'id' => ''];
            }
            $last = end($existing);
            if (is_array($last) && ($last['name'] ?? '') === $name && ($last['body'] ?? '') === $body) {
                return ['ok' => false, 'error' => 'That comment was already posted.', 'id' => ''];
            }
            $id = 'c' . bin2hex(random_bytes(6));
            $existing[] = ['id' => $id, 'name' => $name, 'body' => $body, 'at' => gmdate(DATE_ATOM)];
            ftruncate($handle, 0);
            rewind($handle);
            fwrite($handle, (string) json_encode($existing, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
            fflush($handle);
            return ['ok' => true, 'error' => '', 'id' => $id];
        } finally {
            flock($handle, LOCK_UN);
            fclose($handle);
        }
    }

    public static function validSlug(string $slug): bool
    {
        return preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $slug) === 1 && strlen($slug) <= 80;
    }

    public static function validVideoId(string $id): bool
    {
        return preg_match('/^[A-Za-z0-9_-]{11}$/', $id) === 1;
    }

    /** @param array<int, array<string, mixed>> $blocks */
    private static function readMinutes(array $blocks): int
    {
        $words = 0;
        array_walk_recursive($blocks, static function ($value, $key) use (&$words): void {
            if (is_string($value) && !in_array($key, ['type', 'id', 'tone'], true)) {
                $words += str_word_count($value);
            }
        });
        return max(1, (int) ceil($words / 220));
    }

    private static function length(string $text): int
    {
        return function_exists('mb_strlen') ? mb_strlen($text, 'UTF-8') : strlen($text);
    }

    private function commentsFile(string $slug): string
    {
        // Callers confirm the slug names a real article first, so it is always [a-z0-9-].
        return $this->commentsDir . '/' . $slug . '.json';
    }
}
