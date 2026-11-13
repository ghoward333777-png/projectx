<?php

declare(strict_types=1);

/**
 * Flat-file storage for the magazine: no database, no dependencies.
 *
 * Every data file is a .php file that begins with an exit guard, so a web server
 * that serves the data directory by mistake returns a 404 instead of the contents.
 */
final class MagazineStore
{
    private const GUARD = "<?php http_response_code(404); exit; ?>\n";
    public const ROLES = ['reader', 'editor', 'admin'];

    /** @var array<int, array<string, mixed>>|null */
    private ?array $departments = null;

    public function __construct(private string $dir)
    {
        $this->dir = rtrim($dir, '/');
        foreach (['', '/articles', '/comments', '/rate'] as $sub) {
            if (!is_dir($this->dir . $sub) && !mkdir($this->dir . $sub, 0770, true) && !is_dir($this->dir . $sub)) {
                throw new RuntimeException('The magazine data directory is not writable: ' . $this->dir);
            }
        }
        if (!is_file($this->dir . '/.htaccess')) {
            @file_put_contents($this->dir . '/.htaccess', "Require all denied\nDeny from all\n");
        }
    }

    // ---- low-level files -------------------------------------------------

    private function path(string $name): string
    {
        if (!preg_match('~^[a-z0-9/_-]+$~', $name)) {
            throw new InvalidArgumentException('Invalid storage name.');
        }
        return $this->dir . '/' . $name . '.json.php';
    }

    public function read(string $name, mixed $default = []): mixed
    {
        $path = $this->path($name);
        if (!is_file($path)) {
            return $default;
        }
        $raw = (string) file_get_contents($path);
        $data = json_decode(substr($raw, strlen(self::GUARD)), true);
        return $data ?? $default;
    }

    public function write(string $name, mixed $data): void
    {
        $path = $this->path($name);
        $tmp = $path . '.' . bin2hex(random_bytes(4)) . '.tmp';
        $json = json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
        if (file_put_contents($tmp, self::GUARD . $json) === false || !rename($tmp, $path)) {
            @unlink($tmp);
            throw new RuntimeException('Could not write magazine data.');
        }
    }

    /** Read-modify-write under an exclusive lock. The callback returns the new value. */
    public function mutate(string $name, callable $fn, mixed $default = []): mixed
    {
        $lock = fopen($this->dir . '/.lock', 'c');
        if ($lock === false) {
            throw new RuntimeException('Could not open the magazine lock file.');
        }
        flock($lock, LOCK_EX);
        try {
            $next = $fn($this->read($name, $default));
            $this->write($name, $next);
            return $next;
        } finally {
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }

    /** Signing key for challenges and form tokens; created once per installation. */
    public function secret(): string
    {
        $data = $this->read('secret', null);
        if (!is_array($data) || empty($data['key'])) {
            $data = $this->mutate('secret', static fn ($cur) => is_array($cur) && !empty($cur['key']) ? $cur : ['key' => bin2hex(random_bytes(32))], null);
        }
        return (string) $data['key'];
    }

    /** Fixed-window rate limit. Returns false once $limit hits have landed inside $window seconds. */
    public function hit(string $key, int $limit, int $window, ?int $now = null): bool
    {
        $now ??= time();
        $name = 'rate/' . hash('sha256', $key);
        $allowed = true;
        $this->mutate($name, static function ($hits) use ($now, $limit, $window, &$allowed) {
            $hits = array_values(array_filter((array) $hits, static fn ($t) => $t > $now - $window));
            if (count($hits) >= $limit) {
                $allowed = false;
                return $hits;
            }
            $hits[] = $now;
            return $hits;
        });
        return $allowed;
    }

    // ---- departments -----------------------------------------------------

    /** @return array<int, array<string, mixed>> */
    public function departments(): array
    {
        if ($this->departments === null) {
            $this->departments = require __DIR__ . '/departments.php';
            foreach ($this->departments as $i => &$d) {
                $d['number'] = $i + 1;
            }
        }
        return $this->departments;
    }

    /** @return array<string, mixed>|null */
    public function department(string $slug): ?array
    {
        foreach ($this->departments() as $d) {
            if ($d['slug'] === $slug) {
                return $d;
            }
        }
        return null;
    }

    // ---- users -----------------------------------------------------------

    /** @return array<int, array<string, mixed>> */
    public function users(): array
    {
        return $this->read('users', []);
    }

    public static function normalizeEmail(string $email): string
    {
        return strtolower(trim($email));
    }

    /** @return array<string, mixed>|null */
    public function findUser(string $id): ?array
    {
        foreach ($this->users() as $u) {
            if ($u['id'] === $id) {
                return $u;
            }
        }
        return null;
    }

    /** @return array<string, mixed>|null */
    public function findUserByEmail(string $email): ?array
    {
        $email = self::normalizeEmail($email);
        foreach ($this->users() as $u) {
            if ($u['email'] === $email) {
                return $u;
            }
        }
        return null;
    }

    /**
     * @param array<string, mixed> $fields name, email, optional password_hash / google_sub / role
     * @return array<string, mixed> the created user
     */
    public function createUser(array $fields): array
    {
        $user = [
            'id' => bin2hex(random_bytes(8)),
            'name' => trim((string) $fields['name']),
            'email' => self::normalizeEmail((string) $fields['email']),
            'password_hash' => (string) ($fields['password_hash'] ?? ''),
            'google_sub' => (string) ($fields['google_sub'] ?? ''),
            'role' => in_array($fields['role'] ?? '', self::ROLES, true) ? $fields['role'] : 'reader',
            'created' => time(),
        ];
        $this->mutate('users', static function ($users) use ($user) {
            foreach ($users as $u) {
                if ($u['email'] === $user['email']) {
                    throw new DomainException('An account with that email already exists.');
                }
            }
            $users[] = $user;
            return $users;
        });
        return $user;
    }

    /** @param array<string, mixed> $changes */
    public function updateUser(string $id, array $changes): void
    {
        unset($changes['id'], $changes['email']);
        $this->mutate('users', static function ($users) use ($id, $changes) {
            foreach ($users as &$u) {
                if ($u['id'] === $id) {
                    $u = array_merge($u, $changes);
                }
            }
            return $users;
        });
    }

    // ---- articles --------------------------------------------------------

    /** All article metadata, newest publish date first. @return array<int, array<string, mixed>> */
    public function articles(): array
    {
        $list = $this->read('articles', []);
        usort($list, static fn ($a, $b) => [$b['publish_at'], $b['id']] <=> [$a['publish_at'], $a['id']]);
        return $list;
    }

    /** @param array<string, mixed> $a */
    public static function isLive(array $a, ?int $now = null): bool
    {
        return $a['status'] === 'published' && $a['publish_at'] <= ($now ?? time());
    }

    /** Published articles whose publish time has arrived. @return array<int, array<string, mixed>> */
    public function liveArticles(?string $dept = null, ?int $now = null): array
    {
        return array_values(array_filter(
            $this->articles(),
            static fn ($a) => self::isLive($a, $now) && ($dept === null || $a['dept'] === $dept)
        ));
    }

    /** Article with body, by slug. @return array<string, mixed>|null */
    public function article(string $slug): ?array
    {
        foreach ($this->articles() as $a) {
            if ($a['slug'] === $slug) {
                $a['body'] = (string) ($this->read('articles/' . $a['id'], [])['body'] ?? '');
                return $a;
            }
        }
        return null;
    }

    /** @return array<string, mixed>|null */
    public function articleById(string $id): ?array
    {
        foreach ($this->articles() as $a) {
            if ($a['id'] === $id) {
                return $this->article($a['slug']);
            }
        }
        return null;
    }

    public static function slugify(string $title): string
    {
        $slug = strtolower(trim((string) preg_replace('~[^A-Za-z0-9]+~', '-', iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $title) ?: $title), '-'));
        return substr($slug, 0, 80) ?: 'article';
    }

    /**
     * Create or update an article. Pass 'id' to update. The slug is fixed at creation
     * so published links never break.
     *
     * @param array<string, mixed> $in
     * @return array<string, mixed> stored metadata
     */
    public function saveArticle(array $in): array
    {
        if ($this->department((string) ($in['dept'] ?? '')) === null) {
            throw new DomainException('Choose one of the 20 departments.');
        }
        $title = trim((string) ($in['title'] ?? ''));
        if ($title === '') {
            throw new DomainException('An article needs a title.');
        }
        $body = (string) ($in['body'] ?? '');
        $saved = [];
        $this->mutate('articles', function ($list) use ($in, $title, &$saved) {
            $now = time();
            $meta = [
                'title' => $title,
                'dek' => trim((string) ($in['dek'] ?? '')),
                'dept' => (string) $in['dept'],
                'status' => ($in['status'] ?? 'draft') === 'published' ? 'published' : 'draft',
                'publish_at' => (int) ($in['publish_at'] ?? $now),
                'comments' => !empty($in['comments']),
                'video' => (string) ($in['video'] ?? ''),
                'updated' => $now,
            ];
            foreach ($list as &$a) {
                if ($a['id'] === ($in['id'] ?? null)) {
                    $a = array_merge($a, $meta);
                    $saved = $a;
                    return $list;
                }
            }
            unset($a);
            $slugs = array_column($list, 'slug');
            $base = self::slugify($title);
            $slug = $base;
            for ($n = 2; in_array($slug, $slugs, true); $n++) {
                $slug = $base . '-' . $n;
            }
            $saved = $meta + [
                'id' => bin2hex(random_bytes(8)),
                'slug' => $slug,
                'author_id' => (string) ($in['author_id'] ?? ''),
                'author_name' => (string) ($in['author_name'] ?? 'The Editors'),
                'created' => $now,
            ];
            $list[] = $saved;
            return $list;
        });
        $this->write('articles/' . $saved['id'], ['body' => str_replace(["\r\n", "\r"], "\n", $body)]);
        return $saved;
    }

    public function deleteArticle(string $id): void
    {
        $this->mutate('articles', static fn ($list) => array_values(array_filter($list, static fn ($a) => $a['id'] !== $id)));
        if (preg_match('~^[a-f0-9]{16}$~', $id)) {
            @unlink($this->path('articles/' . $id));
            @unlink($this->path('comments/' . $id));
        }
    }

    /** Seed one opening brief per department the first time the magazine runs. */
    public function seedIfEmpty(): void
    {
        if (is_file($this->path('articles'))) {
            return;
        }
        $this->write('articles', []);
        $now = time();
        $departments = $this->departments();
        foreach ($departments as $i => $d) {
            $o = $d['opener'];
            $body = $o['body'] . "\n\n## What we will keep asking\n\n- " . implode("\n- ", $o['questions']);
            if (!empty($o['scorecard'])) {
                $body .= "\n\n[scorecard: Sample product (illustration only, not a rating)]\n";
                foreach (array_slice($departments, 1, 7) as $p) {
                    $body .= $p['name'] . ": 0 | Scored 0 to 5, with the reasoning stated here\n";
                }
                $body .= '[/scorecard]';
            }
            $body .= "\n\nNew articles join this department as they are published. The mission above stays fixed.";
            $this->saveArticle([
                'title' => $o['title'],
                'dek' => $o['dek'],
                'dept' => $d['slug'],
                'body' => $body,
                'status' => 'published',
                // Stagger by a second so department order is preserved in the stream.
                'publish_at' => $now - $i,
                'comments' => true,
            ]);
        }
    }

    // ---- comments --------------------------------------------------------

    /** @return array<int, array<string, mixed>> */
    public function comments(string $articleId): array
    {
        return $this->read('comments/' . $articleId, []);
    }

    /** @param array<string, mixed> $user */
    public function addComment(string $articleId, array $user, string $body): void
    {
        $body = trim(str_replace(["\r\n", "\r"], "\n", $body));
        $body = (string) preg_replace("~\n{3,}~", "\n\n", $body);
        if ($body === '' || mb_strlen($body) > 2000) {
            throw new DomainException('Comments must be between 1 and 2,000 characters.');
        }
        $this->mutate('comments/' . $articleId, static function ($list) use ($user, $body) {
            $list[] = [
                'id' => bin2hex(random_bytes(6)),
                'user_id' => $user['id'],
                'name' => $user['name'],
                'body' => $body,
                'created' => time(),
            ];
            return $list;
        });
    }

    public function deleteComment(string $articleId, string $commentId): void
    {
        $this->mutate('comments/' . $articleId, static fn ($list) => array_values(array_filter($list, static fn ($c) => $c['id'] !== $commentId)));
    }
}
