<?php
declare(strict_types=1);

/** Outbound fetch helpers with an SSRF guard: only public https hosts, short timeouts. */
final class Http
{
    public const TIMEOUT = 4;

    /** True when the URL is https to a public host (no loopback, private or link-local ranges). */
    public static function isPublicHttpsUrl(string $url): bool
    {
        $p = parse_url($url);
        if (!is_array($p) || ($p['scheme'] ?? '') !== 'https' || ($p['host'] ?? '') === '' || isset($p['user']) || isset($p['pass'])) {
            return false;
        }
        $host = strtolower((string) $p['host']);
        if ($host === 'localhost' || str_ends_with($host, '.localhost') || str_ends_with($host, '.local') || str_ends_with($host, '.internal')) {
            return false;
        }
        if (filter_var($host, FILTER_VALIDATE_IP) !== false) {
            return self::isPublicIp($host);
        }
        return preg_match('/^[a-z0-9.-]+\.[a-z]{2,}$/', $host) === 1;
    }

    public static function isPublicIp(string $ip): bool
    {
        return filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE | FILTER_FLAG_GLOBAL_RANGE) !== false;
    }

    /**
     * GET a public https URL. Returns [status, body] or [0, ''] when unreachable.
     * Resolves the host first and refuses private addresses, so DNS cannot point inside.
     * @return array{0: int, 1: string}
     */
    public static function get(string $url, int $maxBytes = 262144): array
    {
        if (!self::isPublicHttpsUrl($url)) {
            return [0, ''];
        }
        $host = (string) parse_url($url, PHP_URL_HOST);
        if (filter_var($host, FILTER_VALIDATE_IP) === false) {
            $ip = gethostbyname($host);
            if ($ip !== $host && !self::isPublicIp($ip)) {
                return [0, ''];
            }
        }
        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_FOLLOWLOCATION => false,
                CURLOPT_CONNECTTIMEOUT => self::TIMEOUT,
                CURLOPT_TIMEOUT => self::TIMEOUT,
                CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
                CURLOPT_USERAGENT => 'WatchRoom/1.0',
                CURLOPT_MAXFILESIZE => $maxBytes,
            ]);
            $body = curl_exec($ch);
            $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            curl_close($ch);
            return [$body === false ? 0 : $status, is_string($body) ? substr($body, 0, $maxBytes) : ''];
        }
        $ctx = stream_context_create(['http' => ['method' => 'GET', 'timeout' => self::TIMEOUT, 'follow_location' => 0, 'ignore_errors' => true, 'user_agent' => 'WatchRoom/1.0']]);
        $body = @file_get_contents($url, false, $ctx, 0, $maxBytes);
        $status = 0;
        foreach ($http_response_header ?? [] as $h) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $h, $m)) {
                $status = (int) $m[1];
            }
        }
        return [$body === false ? 0 : $status, (string) $body];
    }

    /**
     * POST a JSON body to a public https URL with extra headers. Returns the status, 0 when
     * unreachable. Used for webhooks; never follows redirects.
     */
    public static function postJson(string $url, string $json, array $headers = [], int $timeout = 2): int
    {
        if (!self::isPublicHttpsUrl($url)) {
            return 0;
        }
        $host = (string) parse_url($url, PHP_URL_HOST);
        if (filter_var($host, FILTER_VALIDATE_IP) === false) {
            $ip = gethostbyname($host);
            if ($ip !== $host && !self::isPublicIp($ip)) {
                return 0;
            }
        }
        $headers[] = 'Content-Type: application/json';
        $headers[] = 'User-Agent: WatchRoom/1.0';
        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_POST => true,
                CURLOPT_POSTFIELDS => $json,
                CURLOPT_HTTPHEADER => $headers,
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_FOLLOWLOCATION => false,
                CURLOPT_CONNECTTIMEOUT => $timeout,
                CURLOPT_TIMEOUT => $timeout,
                CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
            ]);
            curl_exec($ch);
            $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            curl_close($ch);
            return $status;
        }
        $ctx = stream_context_create(['http' => ['method' => 'POST', 'header' => implode("\r\n", $headers), 'content' => $json, 'timeout' => $timeout, 'follow_location' => 0, 'ignore_errors' => true]]);
        @file_get_contents($url, false, $ctx);
        foreach ($http_response_header ?? [] as $h) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $h, $m)) {
                return (int) $m[1];
            }
        }
        return 0;
    }

    /** HEAD-style reachability probe (uses GET with a tiny body cap). */
    public static function reachable(string $url): bool
    {
        [$status] = self::get($url, 1024);
        return $status >= 200 && $status < 400;
    }
}
