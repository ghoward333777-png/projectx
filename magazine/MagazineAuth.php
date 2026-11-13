<?php

declare(strict_types=1);

/**
 * Accounts and sessions: native email + password registration, and Google sign-in
 * (OAuth 2.0 authorization-code flow, implemented directly against Google's endpoints).
 */
final class MagazineAuth
{
    public const MIN_PASSWORD = 10;
    private const GOOGLE_AUTH = 'https://accounts.google.com/o/oauth2/v2/auth';
    private const GOOGLE_TOKEN = 'https://oauth2.googleapis.com/token';
    private const GOOGLE_USERINFO = 'https://openidconnect.googleapis.com/v1/userinfo';

    /** @var callable|null test seam: fn(string $url, ?array $postFields, array $headers): ?array */
    private $http;

    /** @param array<string, mixed> $config */
    public function __construct(private MagazineStore $store, private array $config = [], ?callable $http = null)
    {
        $this->http = $http;
    }

    // ---- sessions --------------------------------------------------------

    public function startSession(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE || PHP_SAPI === 'cli') {
            return;
        }
        $secure = (($_SERVER['HTTPS'] ?? '') !== '' && $_SERVER['HTTPS'] !== 'off') || ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https';
        session_name('magazine_session');
        session_set_cookie_params(['lifetime' => 0, 'path' => '/', 'secure' => $secure, 'httponly' => true, 'samesite' => 'Lax']);
        ini_set('session.use_strict_mode', '1');
        session_start();
    }

    /** @return array<string, mixed>|null */
    public function user(): ?array
    {
        $id = $_SESSION['uid'] ?? null;
        return is_string($id) ? $this->store->findUser($id) : null;
    }

    /** @param array<string, mixed> $user */
    private function signIn(array $user): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            session_regenerate_id(true);
        }
        $_SESSION['uid'] = $user['id'];
        unset($_SESSION['csrf']);
    }

    public function logout(): void
    {
        $_SESSION = [];
        if (session_status() === PHP_SESSION_ACTIVE) {
            session_regenerate_id(true);
        }
    }

    public function csrfToken(): string
    {
        return $_SESSION['csrf'] ??= bin2hex(random_bytes(24));
    }

    public function checkCsrf(string $token): bool
    {
        return $token !== '' && hash_equals((string) ($_SESSION['csrf'] ?? ''), $token);
    }

    /** @param array<string, mixed>|null $user */
    public static function isStaff(?array $user): bool
    {
        return $user !== null && in_array($user['role'], ['editor', 'admin'], true);
    }

    // ---- native accounts -------------------------------------------------

    /** @return array<string, mixed> the new, signed-in user */
    public function register(string $name, string $email, string $password): array
    {
        $name = trim((string) preg_replace('~\s+~u', ' ', $name));
        if (mb_strlen($name) < 2 || mb_strlen($name) > 60) {
            throw new DomainException('Please enter a display name between 2 and 60 characters.');
        }
        if (filter_var($email, FILTER_VALIDATE_EMAIL) === false || strlen($email) > 190) {
            throw new DomainException('Please enter a valid email address.');
        }
        if (strlen($password) < self::MIN_PASSWORD || strlen($password) > 200) {
            throw new DomainException('Passwords must be at least ' . self::MIN_PASSWORD . ' characters.');
        }
        // Native email addresses are unverified, so they never receive a staff role automatically.
        $user = $this->store->createUser([
            'name' => $name,
            'email' => $email,
            'password_hash' => password_hash($password, PASSWORD_DEFAULT),
        ]);
        $this->signIn($user);
        return $user;
    }

    public function login(string $email, string $password): bool
    {
        $user = $this->store->findUserByEmail($email);
        $hash = (string) ($user['password_hash'] ?? '');
        if ($hash === '') {
            // Spend the same work when there is no password to check, so timing does not reveal accounts.
            password_hash($password, PASSWORD_DEFAULT);
            return false;
        }
        if (!password_verify($password, $hash)) {
            return false;
        }
        if (password_needs_rehash($hash, PASSWORD_DEFAULT)) {
            $this->store->updateUser($user['id'], ['password_hash' => password_hash($password, PASSWORD_DEFAULT)]);
        }
        $this->signIn($user);
        return true;
    }

    // ---- Google sign-in --------------------------------------------------

    public function googleEnabled(): bool
    {
        return !empty($this->config['google_client_id']) && !empty($this->config['google_client_secret']);
    }

    public function googleAuthUrl(string $redirectUri): string
    {
        $_SESSION['google_state'] = bin2hex(random_bytes(16));
        return self::GOOGLE_AUTH . '?' . http_build_query([
            'client_id' => $this->config['google_client_id'],
            'redirect_uri' => $redirectUri,
            'response_type' => 'code',
            'scope' => 'openid email profile',
            'state' => $_SESSION['google_state'],
            'prompt' => 'select_account',
        ]);
    }

    /** Finish the Google flow and sign the visitor in. @return array<string, mixed> */
    public function googleCallback(string $code, string $state, string $redirectUri): array
    {
        $expected = (string) ($_SESSION['google_state'] ?? '');
        unset($_SESSION['google_state']);
        if ($expected === '' || !hash_equals($expected, $state) || $code === '') {
            throw new DomainException('The Google sign-in could not be verified. Please try again.');
        }
        $token = $this->request(self::GOOGLE_TOKEN, [
            'code' => $code,
            'client_id' => $this->config['google_client_id'],
            'client_secret' => $this->config['google_client_secret'],
            'redirect_uri' => $redirectUri,
            'grant_type' => 'authorization_code',
        ]);
        $access = (string) ($token['access_token'] ?? '');
        $profile = $access !== '' ? $this->request(self::GOOGLE_USERINFO, null, ['Authorization: Bearer ' . $access]) : null;
        $sub = (string) ($profile['sub'] ?? '');
        $email = MagazineStore::normalizeEmail((string) ($profile['email'] ?? ''));
        if ($sub === '' || $email === '' || !filter_var($profile['email_verified'] ?? false, FILTER_VALIDATE_BOOLEAN)) {
            throw new DomainException('Google did not return a verified email address for this account.');
        }
        $isAdmin = in_array($email, array_map([MagazineStore::class, 'normalizeEmail'], (array) ($this->config['admin_emails'] ?? [])), true);

        $user = null;
        foreach ($this->store->users() as $u) {
            if ($u['google_sub'] === $sub) {
                $user = $u;
            }
        }
        $user ??= $this->store->findUserByEmail($email);
        if ($user === null) {
            $user = $this->store->createUser([
                'name' => mb_substr(trim((string) ($profile['name'] ?? '')) ?: strstr($email, '@', true), 0, 60),
                'email' => $email,
                'google_sub' => $sub,
                'role' => $isAdmin ? 'admin' : 'reader',
            ]);
        } else {
            $changes = [];
            if ($user['google_sub'] === '') {
                // First Google link to a natively registered (unverified) address: Google has proven
                // ownership, so retire the old password in case someone else registered it first.
                $changes = ['google_sub' => $sub, 'password_hash' => ''];
            }
            if ($isAdmin && $user['role'] !== 'admin') {
                $changes['role'] = 'admin';
            }
            if ($changes !== []) {
                $this->store->updateUser($user['id'], $changes);
                $user = array_merge($user, $changes);
            }
        }
        $this->signIn($user);
        return $user;
    }

    /**
     * @param array<string, mixed>|null $post
     * @param array<int, string> $headers
     * @return array<string, mixed>|null
     */
    private function request(string $url, ?array $post, array $headers = []): ?array
    {
        return $this->http ? ($this->http)($url, $post, $headers) : self::httpJson($url, $post, $headers);
    }

    /**
     * Minimal JSON-over-HTTPS client (POST when $post is given, otherwise GET).
     *
     * @param array<string, mixed>|null $post
     * @param array<int, string> $headers
     * @return array<string, mixed>|null
     */
    public static function httpJson(string $url, ?array $post = null, array $headers = []): ?array
    {
        $context = stream_context_create(['http' => [
            'method' => $post === null ? 'GET' : 'POST',
            'header' => implode("\r\n", array_merge($headers, $post === null ? [] : ['Content-Type: application/x-www-form-urlencoded'])),
            'content' => $post === null ? '' : http_build_query($post),
            'timeout' => 10,
            'ignore_errors' => true,
        ]]);
        $body = @file_get_contents($url, false, $context);
        $data = $body === false ? null : json_decode($body, true);
        return is_array($data) ? $data : null;
    }
}
