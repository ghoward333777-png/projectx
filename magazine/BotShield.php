<?php

declare(strict_types=1);

/**
 * Layered anti-robot protection with no third-party dependency by default:
 *
 *  1. Proof of work  - the browser must solve a signed SHA-256 puzzle (no image puzzles,
 *                      no tracking, nothing for a person to click). Each solution is
 *                      single-use and expires.
 *  2. Honeypot       - a field people never see; bots that fill every input are rejected.
 *  3. Time trap      - a signed timestamp; forms submitted faster than a person can type
 *                      (or hours later) are rejected.
 *  4. Rate limits    - enforced by the caller through MagazineStore::hit().
 *  5. Turnstile      - optional. When Cloudflare Turnstile keys are configured, its
 *                      behavioural check is verified server-side on top of the above.
 */
final class BotShield
{
    public const HONEYPOT = 'website';
    private const CHALLENGE_TTL = 600;
    private const FORM_MIN_AGE = 2;
    private const FORM_MAX_AGE = 7200;

    /** @var callable|null test seam: fn(string $url, array $fields): ?array */
    private $http;

    /** @param array<string, mixed> $config */
    public function __construct(private MagazineStore $store, private array $config = [], ?callable $http = null)
    {
        $this->http = $http;
    }

    private function sign(string $value): string
    {
        return hash_hmac('sha256', $value, $this->store->secret());
    }

    /** @return array{salt: string, challenge: string, max: int, signature: string} */
    public function challenge(?int $now = null): array
    {
        $max = max(1000, (int) ($this->config['pow_max'] ?? 50000));
        $salt = bin2hex(random_bytes(12)) . '.' . (($now ?? time()) + self::CHALLENGE_TTL);
        $challenge = hash('sha256', $salt . random_int(0, $max));
        return ['salt' => $salt, 'challenge' => $challenge, 'max' => $max, 'signature' => $this->sign($challenge)];
    }

    /** Verify a base64-JSON solution {salt, challenge, signature, number}; each may be used once. */
    public function verifyChallenge(string $payload, ?int $now = null): bool
    {
        $now ??= time();
        $data = json_decode((string) base64_decode($payload, true), true);
        if (!is_array($data)) {
            return false;
        }
        $salt = (string) ($data['salt'] ?? '');
        $challenge = (string) ($data['challenge'] ?? '');
        $number = $data['number'] ?? null;
        if (!is_int($number) || !preg_match('~^[a-f0-9]{24}\.(\d{9,11})$~', $salt, $m) || (int) $m[1] < $now) {
            return false;
        }
        if (!hash_equals($this->sign($challenge), (string) ($data['signature'] ?? ''))
            || !hash_equals($challenge, hash('sha256', $salt . $number))) {
            return false;
        }
        $fresh = true;
        $this->store->mutate('used-challenges', static function ($used) use ($salt, $now, &$fresh) {
            $used = array_filter((array) $used, static fn ($exp) => $exp >= $now);
            if (isset($used[$salt])) {
                $fresh = false;
            } else {
                $used[$salt] = (int) substr($salt, 25);
            }
            return $used;
        });
        return $fresh;
    }

    /** Signed timestamp embedded in each protected form. */
    public function formToken(?int $now = null): string
    {
        $ts = (string) ($now ?? time());
        return $ts . '.' . $this->sign('form:' . $ts);
    }

    public function verifyFormToken(string $token, ?int $now = null): bool
    {
        [$ts, $sig] = array_pad(explode('.', $token, 2), 2, '');
        if (!ctype_digit($ts) || !hash_equals($this->sign('form:' . $ts), $sig)) {
            return false;
        }
        $age = ($now ?? time()) - (int) $ts;
        return $age >= self::FORM_MIN_AGE && $age <= self::FORM_MAX_AGE;
    }

    public function turnstileSiteKey(): string
    {
        return !empty($this->config['turnstile_secret']) ? (string) ($this->config['turnstile_site_key'] ?? '') : '';
    }

    private function verifyTurnstile(string $response, string $ip): bool
    {
        if ($response === '') {
            return false;
        }
        $fields = ['secret' => $this->config['turnstile_secret'], 'response' => $response, 'remoteip' => $ip];
        $url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
        $result = $this->http ? ($this->http)($url, $fields) : MagazineAuth::httpJson($url, $fields);
        return is_array($result) && ($result['success'] ?? false) === true;
    }

    /**
     * Run every layer against a submitted form.
     *
     * @param array<string, mixed> $post
     * @return string|null null when the submission looks human, otherwise a message for the visitor
     */
    public function check(array $post, string $ip, ?int $now = null): ?string
    {
        if (trim((string) ($post[self::HONEYPOT] ?? '')) !== '') {
            return 'This submission was blocked.';
        }
        if (!$this->verifyFormToken((string) ($post['form_token'] ?? ''), $now)) {
            return 'The form expired or was submitted too quickly. Please try again.';
        }
        if ($this->turnstileSiteKey() !== '' && !$this->verifyTurnstile((string) ($post['cf-turnstile-response'] ?? ''), $ip)) {
            return 'The human verification did not complete. Please try again.';
        }
        if (!$this->verifyChallenge((string) ($post['shield'] ?? ''), $now)) {
            return 'The automatic human check did not complete. Make sure JavaScript is enabled and try again.';
        }
        return null;
    }
}
