<?php

declare(strict_types=1);

/**
 * Key Vault
 *
 * One encrypted file holding every API key you store plus the Google
 * connection settings. The file key is derived from your passphrase with
 * Argon2id (libsodium) and the contents are sealed with XSalsa20-Poly1305,
 * so the file on disk never contains a key, a token or a label in clear
 * text, and any tampering makes it refuse to open.
 *
 * Data shape:
 *   entries:    list of stored keys (Google or any other provider)
 *   connection: how to reach Google (mode, gcloud path, service account, ...)
 */
final class KeyVault
{
    public const MIN_PASSPHRASE = 10;
    private const FORMAT = 'cloud-key-manager-vault';

    public function __construct(private string $path)
    {
        if (!function_exists('sodium_crypto_secretbox')) {
            throw new RuntimeException('The PHP sodium extension is required for the key vault.');
        }
    }

    /** Where the vault lives unless KEY_MANAGER_VAULT says otherwise — outside the web root. */
    public static function defaultPath(): string
    {
        $env = getenv('KEY_MANAGER_VAULT');
        if (is_string($env) && $env !== '') {
            return $env;
        }
        $home = getenv('HOME') ?: getenv('USERPROFILE');
        if (is_string($home) && $home !== '') {
            return rtrim($home, '/\\') . DIRECTORY_SEPARATOR . '.cloud-key-manager' . DIRECTORY_SEPARATOR . 'vault.json';
        }
        return __DIR__ . DIRECTORY_SEPARATOR . 'vault' . DIRECTORY_SEPARATOR . 'vault.json';
    }

    public function path(): string
    {
        return $this->path;
    }

    public function exists(): bool
    {
        return is_file($this->path);
    }

    /** Create an empty vault and return its unlocked file key. */
    public function create(string $passphrase): string
    {
        if ($this->exists()) {
            throw new RuntimeException('A vault already exists at ' . $this->path);
        }
        self::assertPassphrase($passphrase);
        $kdf = self::newKdf();
        $key = self::derive($passphrase, $kdf);
        $this->persist($kdf, $key, self::emptyData());
        return $key;
    }

    /** Return the file key, or throw if the passphrase is wrong. */
    public function unlock(string $passphrase): string
    {
        $file = $this->readFile();
        $key = self::derive($passphrase, $file['kdf']);
        if (self::open($file, $key) === null) {
            sodium_memzero($key);
            throw new InvalidArgumentException('That passphrase does not open this vault.');
        }
        return $key;
    }

    /** @return array{entries: array<int, array<string, mixed>>, connection: array<string, mixed>} */
    public function read(string $key): array
    {
        $data = self::open($this->readFile(), $key);
        if ($data === null) {
            throw new RuntimeException('The vault could not be decrypted — it is locked with a different passphrase or was modified.');
        }
        return $data + self::emptyData();
    }

    /** @param array<string, mixed> $data */
    public function write(string $key, array $data): void
    {
        $file = $this->readFile();
        if (self::open($file, $key) === null) {
            throw new RuntimeException('Refusing to overwrite the vault with a key that does not open it.');
        }
        $this->persist($file['kdf'], $key, $data);
    }

    /** Re-encrypt under a new passphrase; returns the new file key. */
    public function changePassphrase(string $key, string $newPassphrase): string
    {
        self::assertPassphrase($newPassphrase);
        $data = $this->read($key);
        $kdf = self::newKdf();
        $newKey = self::derive($newPassphrase, $kdf);
        $this->persist($kdf, $newKey, $data);
        return $newKey;
    }

    // ------------------------------------------------------------------
    // Entries
    // ------------------------------------------------------------------

    /**
     * Insert or update an entry (matched by id) and return the new data.
     *
     * @param array<string, mixed> $data
     * @param array<string, mixed> $entry
     * @return array<string, mixed>
     */
    public static function upsert(array $data, array $entry): array
    {
        $now = gmdate(DATE_ATOM);
        $entries = (array) ($data['entries'] ?? []);
        $id = (string) ($entry['id'] ?? '');
        foreach ($entries as $i => $existing) {
            if ($id !== '' && ($existing['id'] ?? '') === $id) {
                $entries[$i] = array_merge($existing, $entry, ['id' => $id, 'updated_at' => $now]);
                $data['entries'] = $entries;
                return $data;
            }
        }
        $entries[] = array_merge([
            'label' => '',
            'provider' => 'Google Cloud',
            'project' => '',
            'google_name' => '',
            'key_string' => '',
            'notes' => '',
            'status' => '',
        ], $entry, [
            'id' => $id !== '' ? $id : bin2hex(random_bytes(8)),
            'created_at' => $now,
            'updated_at' => $now,
        ]);
        $data['entries'] = $entries;
        return $data;
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>
     */
    public static function remove(array $data, string $id): array
    {
        $data['entries'] = array_values(array_filter(
            (array) ($data['entries'] ?? []),
            static fn (array $entry): bool => ($entry['id'] ?? '') !== $id
        ));
        return $data;
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>|null
     */
    public static function find(array $data, string $id): ?array
    {
        foreach ((array) ($data['entries'] ?? []) as $entry) {
            if ($id !== '' && ($entry['id'] ?? '') === $id) {
                return $entry;
            }
        }
        return null;
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>|null
     */
    public static function findByGoogleName(array $data, string $name): ?array
    {
        foreach ((array) ($data['entries'] ?? []) as $entry) {
            if ($name !== '' && ($entry['google_name'] ?? '') === $name) {
                return $entry;
            }
        }
        return null;
    }

    /** Show enough of a secret to recognise it, never enough to use it. */
    public static function mask(string $secret): string
    {
        $length = strlen($secret);
        if ($length === 0) {
            return '—';
        }
        if ($length <= 10) {
            return str_repeat('•', $length);
        }
        return substr($secret, 0, 4) . str_repeat('•', 8) . substr($secret, -4);
    }

    // ------------------------------------------------------------------
    // Internals
    // ------------------------------------------------------------------

    /** @return array{entries: array<int, mixed>, connection: array<string, mixed>} */
    private static function emptyData(): array
    {
        return ['entries' => [], 'connection' => []];
    }

    private static function assertPassphrase(string $passphrase): void
    {
        if (mb_strlen($passphrase) < self::MIN_PASSPHRASE) {
            throw new InvalidArgumentException('Use a passphrase of at least ' . self::MIN_PASSPHRASE . ' characters — a short sentence works well.');
        }
    }

    /** @return array{alg: string, salt: string, opslimit: int, memlimit: int} */
    private static function newKdf(): array
    {
        return [
            'alg' => 'argon2id13',
            'salt' => base64_encode(random_bytes(SODIUM_CRYPTO_PWHASH_SALTBYTES)),
            'opslimit' => SODIUM_CRYPTO_PWHASH_OPSLIMIT_INTERACTIVE,
            'memlimit' => SODIUM_CRYPTO_PWHASH_MEMLIMIT_INTERACTIVE,
        ];
    }

    /** @param array<string, mixed> $kdf */
    private static function derive(string $passphrase, array $kdf): string
    {
        $salt = base64_decode((string) ($kdf['salt'] ?? ''), true);
        if ($salt === false || strlen($salt) !== SODIUM_CRYPTO_PWHASH_SALTBYTES) {
            throw new RuntimeException('The vault header is damaged (bad salt).');
        }
        return sodium_crypto_pwhash(
            SODIUM_CRYPTO_SECRETBOX_KEYBYTES,
            $passphrase,
            $salt,
            (int) $kdf['opslimit'],
            (int) $kdf['memlimit'],
            SODIUM_CRYPTO_PWHASH_ALG_ARGON2ID13
        );
    }

    /**
     * @param array<string, mixed> $file
     * @return array<string, mixed>|null
     */
    private static function open(array $file, string $key): ?array
    {
        $nonce = base64_decode((string) ($file['nonce'] ?? ''), true);
        $cipher = base64_decode((string) ($file['ciphertext'] ?? ''), true);
        if ($nonce === false || $cipher === false || strlen($key) !== SODIUM_CRYPTO_SECRETBOX_KEYBYTES || strlen($nonce) !== SODIUM_CRYPTO_SECRETBOX_NONCEBYTES) {
            return null;
        }
        $plain = sodium_crypto_secretbox_open($cipher, $nonce, $key);
        if ($plain === false) {
            return null;
        }
        $data = json_decode($plain, true);
        return is_array($data) ? $data : null;
    }

    /** @return array<string, mixed> */
    private function readFile(): array
    {
        $raw = @file_get_contents($this->path);
        if ($raw === false) {
            throw new RuntimeException('No vault found at ' . $this->path);
        }
        $file = json_decode($raw, true);
        if (!is_array($file) || ($file['format'] ?? '') !== self::FORMAT || !is_array($file['kdf'] ?? null)) {
            throw new RuntimeException('The file at ' . $this->path . ' is not a key manager vault.');
        }
        return $file;
    }

    /**
     * @param array<string, mixed> $kdf
     * @param array<string, mixed> $data
     */
    private function persist(array $kdf, string $key, array $data): void
    {
        $dir = dirname($this->path);
        if (!is_dir($dir) && !@mkdir($dir, 0700, true) && !is_dir($dir)) {
            throw new RuntimeException('Could not create the vault folder: ' . $dir);
        }
        // If someone points the vault inside a web root, keep Apache from serving it.
        if (!is_file($dir . '/.htaccess')) {
            @file_put_contents($dir . '/.htaccess', "Require all denied\nDeny from all\n");
        }
        $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
        $plain = json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
        $file = [
            'format' => self::FORMAT,
            'version' => 1,
            'kdf' => $kdf,
            'nonce' => base64_encode($nonce),
            'ciphertext' => base64_encode(sodium_crypto_secretbox($plain, $nonce, $key)),
        ];
        sodium_memzero($plain);
        $tmp = $this->path . '.' . bin2hex(random_bytes(4)) . '.tmp';
        if (@file_put_contents($tmp, json_encode($file, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), LOCK_EX) === false) {
            throw new RuntimeException('Could not write the vault to ' . $dir);
        }
        @chmod($tmp, 0600);
        if (!@rename($tmp, $this->path)) {
            @unlink($tmp);
            throw new RuntimeException('Could not replace the vault file at ' . $this->path);
        }
    }
}
