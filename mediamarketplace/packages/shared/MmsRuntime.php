<?php
/**
 * MediaMarketplace Studio runtime: runs the bundled server on the same machine as the
 * website and proxies requests to it. Plain PHP, no framework dependencies, so the same
 * file ships inside the WordPress plugin and the Joomla package and can be unit tested.
 *
 * Responsibilities:
 *   - keep a data directory (SQLite database, media, config, pid, log)
 *   - write mms.toml, including this site's bridge entry and secret
 *   - start, stop and supervise the mms-server process bound to 127.0.0.1
 *   - forward https://site/mms/... requests to the process (HTTP reverse proxy)
 *   - build single sign-on URLs and embed markup
 */
final class MmsRuntime
{
    public const VERSION = '0.2.0';
    private const TOKEN_TTL = 300;
    private const STATE_FILE = 'runtime.json';

    /** @var array<string,mixed> */
    private array $o;
    /** @var array<string,mixed>|null */
    private ?array $state = null;

    /**
     * @param array{data_dir:string,bin:string,public_url:string,origin:string,host:string,site_name:string} $options
     */
    public function __construct(array $options)
    {
        foreach (['data_dir', 'bin', 'public_url', 'origin', 'host', 'site_name'] as $k) {
            if (empty($options[$k])) {
                throw new InvalidArgumentException("MmsRuntime option {$k} is required");
            }
        }
        $options['public_url'] = rtrim($options['public_url'], '/');
        $options['origin'] = rtrim($options['origin'], '/');
        $this->o = $options;
    }

    // ----- paths -------------------------------------------------------------------

    public function dataDir(): string { return rtrim((string) $this->o['data_dir'], '/'); }
    public function binPath(): string
    {
        $bin = (string) $this->o['bin'];
        // ARM servers (Graviton, Ampere, Raspberry Pi) get the aarch64 build when the package carries it.
        $arch = strtolower((string) php_uname('m'));
        if (($arch === 'aarch64' || $arch === 'arm64') && is_file($bin . '-aarch64')) {
            return $bin . '-aarch64';
        }
        return $bin;
    }
    public function configPath(): string { return $this->dataDir() . '/mms.toml'; }
    public function pidPath(): string { return $this->dataDir() . '/mms-server.pid'; }
    public function logPath(): string { return $this->dataDir() . '/mms-server.log'; }
    public function publicUrl(): string { return (string) $this->o['public_url']; }

    /** Path prefix the server is mounted at, e.g. "/mms". */
    public function basePath(): string
    {
        $path = (string) parse_url($this->publicUrl(), PHP_URL_PATH);
        return rtrim($path, '/');
    }

    // ----- platform checks -----------------------------------------------------------

    /** Returns a human-readable reason when the server cannot run here, or null. */
    public function platformProblem(): ?string
    {
        if (PHP_OS_FAMILY !== 'Linux') {
            return 'The bundled server runs on Linux only (this host is ' . PHP_OS_FAMILY . ').';
        }
        if (!in_array(php_uname('m'), ['x86_64', 'amd64'], true)) {
            return 'The bundled server is built for x86_64 (this host is ' . php_uname('m') . ').';
        }
        if (!function_exists('exec') || !function_exists('proc_open')) {
            return 'PHP must be allowed to start processes (exec and proc_open are disabled).';
        }
        if (!function_exists('curl_init')) {
            return 'The PHP curl extension is required.';
        }
        if (!is_file($this->binPath())) {
            return 'The server binary is missing at ' . $this->binPath() . '.';
        }
        return null;
    }

    // ----- installation --------------------------------------------------------------

    /** Creates the data directory, protects it, prepares state and writes the config. Idempotent. */
    public function ensureInstalled(): void
    {
        $dir = $this->dataDir();
        foreach ([$dir, "$dir/media", "$dir/media/public", "$dir/media/private"] as $d) {
            if (!is_dir($d) && !@mkdir($d, 0750, true) && !is_dir($d)) {
                throw new RuntimeException("Cannot create data directory {$d}");
            }
        }
        if (!is_file("$dir/.htaccess")) {
            @file_put_contents("$dir/.htaccess", "Require all denied\n<IfModule !mod_authz_core.c>\nDeny from all\n</IfModule>\n");
        }
        if (!is_file("$dir/index.html")) {
            @file_put_contents("$dir/index.html", '');
        }
        if (!is_executable($this->binPath())) {
            @chmod($this->binPath(), 0755);
        }
        $this->state();
        $this->writeConfig();
    }

    /** @return array{uuid:string,secret:string,port:int,secret_key:string} */
    public function state(): array
    {
        if ($this->state !== null) {
            return $this->state;
        }
        $file = $this->dataDir() . '/' . self::STATE_FILE;
        $s = is_file($file) ? json_decode((string) file_get_contents($file), true) : null;
        if (!is_array($s) || empty($s['uuid']) || empty($s['secret']) || empty($s['secret_key'])) {
            $s = [
                'uuid'       => self::uuid(),
                'secret'     => bin2hex(random_bytes(32)),
                'secret_key' => base64_encode(random_bytes(32)),
                'port'       => $this->pickPort(),
            ];
            $this->saveState($s);
        }
        return $this->state = $s;
    }

    private function saveState(array $s): void
    {
        $file = $this->dataDir() . '/' . self::STATE_FILE;
        if (file_put_contents($file, json_encode($s, JSON_PRETTY_PRINT), LOCK_EX) === false) {
            throw new RuntimeException("Cannot write {$file}");
        }
        @chmod($file, 0600);
        $this->state = $s;
    }

    public function siteId(): string { return (string) $this->state()['uuid']; }
    public function secret(): string { return (string) $this->state()['secret']; }
    public function port(): int { return (int) $this->state()['port']; }

    /** Writes mms.toml from the current options and state. */
    public function writeConfig(): void
    {
        $s = $this->state();
        $toml = "# Written by MediaMarketplace Studio (" . $this->o['host'] . " package). Do not edit by hand.\n"
            . "data_dir = " . self::tomlString($this->dataDir()) . "\n\n"
            . "[server]\n"
            . "bind = \"127.0.0.1:" . $s['port'] . "\"\n"
            . "public_url = " . self::tomlString($this->publicUrl()) . "\n\n"
            . "[security]\n"
            . "secret_key = " . self::tomlString($s['secret_key']) . "\n"
            . "session_ttl_seconds = 43200\n\n"
            . "[media]\n"
            . "max_upload_mb = 512\n"
            . "ffmpeg_path = \"ffmpeg\"\n\n"
            . "[[bridges]]\n"
            . "uuid = " . self::tomlString($s['uuid']) . "\n"
            . "name = " . self::tomlString((string) $this->o['site_name']) . "\n"
            . "host = " . self::tomlString((string) $this->o['host']) . "\n"
            . "origin = " . self::tomlString((string) $this->o['origin']) . "\n"
            . "secret = " . self::tomlString($s['secret']) . "\n"
            . "admin_sso = true\n";
        if (file_put_contents($this->configPath(), $toml, LOCK_EX) === false) {
            throw new RuntimeException('Cannot write ' . $this->configPath());
        }
        @chmod($this->configPath(), 0600);
    }

    private static function tomlString(string $v): string
    {
        return '"' . str_replace(['\\', '"'], ['\\\\', '\\"'], $v) . '"';
    }

    // ----- process control -----------------------------------------------------------

    public function pid(): ?int
    {
        $pid = is_file($this->pidPath()) ? (int) trim((string) file_get_contents($this->pidPath())) : 0;
        return $pid > 0 ? $pid : null;
    }

    public function pidAlive(): bool
    {
        $pid = $this->pid();
        if ($pid === null) {
            return false;
        }
        if (function_exists('posix_kill')) {
            return @posix_kill($pid, 0);
        }
        return is_dir("/proc/{$pid}");
    }

    /** True when the server answers on its port. */
    public function isRunning(): bool
    {
        return $this->ping() !== null;
    }

    /** @return array{ok:bool,version:string}|null */
    public function ping(int $timeoutSeconds = 1): ?array
    {
        $ch = curl_init('http://127.0.0.1:' . $this->port() . $this->basePath() . '/api/v1/ping');
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => $timeoutSeconds, CURLOPT_CONNECTTIMEOUT => $timeoutSeconds]);
        $body = curl_exec($ch);
        $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        if ($body === false || $code !== 200) {
            return null;
        }
        $j = json_decode((string) $body, true);
        return is_array($j) && !empty($j['ok']) ? $j : null;
    }

    /** Starts the server if it is not answering. Returns true when it answers afterwards. */
    public function ensureRunning(): bool
    {
        if ($this->isRunning()) {
            return true;
        }
        $this->ensureInstalled();
        return $this->start();
    }

    public function start(): bool
    {
        if ($problem = $this->platformProblem()) {
            throw new RuntimeException($problem);
        }
        if ($this->isRunning()) {
            return true;
        }
        // Port taken by something that is not ours: move to a free one.
        if (!$this->pidAlive() && self::portBusy($this->port())) {
            $s = $this->state();
            $s['port'] = $this->pickPort();
            $this->saveState($s);
            $this->writeConfig();
        }
        $cmd = sprintf(
            'nohup %s --config %s serve >> %s 2>&1 < /dev/null & echo $!',
            escapeshellarg($this->binPath()),
            escapeshellarg($this->configPath()),
            escapeshellarg($this->logPath())
        );
        $out = [];
        exec($cmd, $out);
        $pid = (int) trim((string) ($out[0] ?? '0'));
        if ($pid > 0) {
            file_put_contents($this->pidPath(), (string) $pid);
        }
        for ($i = 0; $i < 40; $i++) { // up to ~4 s
            usleep(100000);
            if ($this->isRunning()) {
                return true;
            }
        }
        return false;
    }

    public function stop(): void
    {
        $pid = $this->pid();
        if ($pid !== null) {
            if (function_exists('posix_kill')) {
                @posix_kill($pid, 15);
            } else {
                exec('kill ' . (int) $pid . ' 2>/dev/null');
            }
            @unlink($this->pidPath());
        }
    }

    public function restart(): bool
    {
        $this->stop();
        usleep(300000);
        return $this->start();
    }

    public function logTail(int $lines = 40): string
    {
        if (!is_file($this->logPath())) {
            return '';
        }
        $all = file($this->logPath(), FILE_IGNORE_NEW_LINES) ?: [];
        return implode("\n", array_slice($all, -$lines));
    }

    private static function portBusy(int $port): bool
    {
        $fp = @fsockopen('127.0.0.1', $port, $errno, $errstr, 0.3);
        if ($fp) {
            fclose($fp);
            return true;
        }
        return false;
    }

    private function pickPort(): int
    {
        for ($p = 8090; $p < 8190; $p++) {
            if (!self::portBusy($p)) {
                return $p;
            }
        }
        throw new RuntimeException('No free local port between 8090 and 8189');
    }

    // ----- reverse proxy -------------------------------------------------------------

    /**
     * Forwards the current HTTP request to the server and streams the response back.
     * $requestUri is the full path + query as seen by the website (e.g. /mms/admin?x=1).
     * Never returns normally: the caller must exit afterwards.
     */
    public function proxy(string $requestUri): void
    {
        while (ob_get_level() > 0) {
            ob_end_clean();
        }
        if (!$this->ensureRunning()) {
            http_response_code(503);
            header('Content-Type: text/plain; charset=utf-8');
            header('Retry-After: 5');
            echo "MediaMarketplace server is starting or could not start. Check the plugin status page.\n";
            return;
        }
        $method = strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET');
        $target = 'http://127.0.0.1:' . $this->port() . $requestUri;

        $headers = [];
        foreach (self::requestHeaders() as $name => $value) {
            $lower = strtolower($name);
            if (in_array($lower, ['host', 'connection', 'content-length', 'accept-encoding', 'transfer-encoding', 'expect'], true)) {
                continue;
            }
            $headers[] = $name . ': ' . $value;
        }
        $publicHost = (string) parse_url($this->publicUrl(), PHP_URL_HOST);
        $headers[] = 'Host: ' . $publicHost;
        $headers[] = 'X-Forwarded-Host: ' . $publicHost;
        $headers[] = 'X-Forwarded-Proto: ' . (str_starts_with($this->publicUrl(), 'https://') ? 'https' : 'http');
        if (!empty($_SERVER['REMOTE_ADDR'])) {
            $headers[] = 'X-Forwarded-For: ' . $_SERVER['REMOTE_ADDR'];
        }

        $ch = curl_init($target);
        curl_setopt_array($ch, [
            CURLOPT_CUSTOMREQUEST  => $method,
            CURLOPT_HTTPHEADER     => $headers,
            CURLOPT_HEADER         => false,
            CURLOPT_RETURNTRANSFER => false,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_TIMEOUT        => 300,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_ENCODING       => '',
        ]);
        if (!in_array($method, ['GET', 'HEAD'], true)) {
            $contentType = (string) ($_SERVER['CONTENT_TYPE'] ?? '');
            if (stripos($contentType, 'multipart/form-data') === 0) {
                // PHP has already parsed the multipart body into $_POST and $_FILES; rebuild it for curl.
                $headers = array_values(array_filter($headers, static fn (string $h): bool => stripos($h, 'Content-Type:') !== 0));
                curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
                curl_setopt($ch, CURLOPT_POSTFIELDS, self::multipartFields());
            } else {
                curl_setopt($ch, CURLOPT_POSTFIELDS, (string) file_get_contents('php://input'));
            }
        }
        if ($method === 'HEAD') {
            curl_setopt($ch, CURLOPT_NOBODY, true);
        }
        $statusSent = false;
        curl_setopt($ch, CURLOPT_HEADERFUNCTION, static function ($ch, string $line) use (&$statusSent): int {
            $trimmed = trim($line);
            if ($trimmed === '') {
                return strlen($line);
            }
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $trimmed, $m)) {
                http_response_code((int) $m[1]);
                $statusSent = true;
                return strlen($line);
            }
            $lower = strtolower(strtok($trimmed, ':'));
            if (in_array($lower, ['transfer-encoding', 'connection', 'keep-alive', 'content-length', 'content-encoding'], true)) {
                return strlen($line);
            }
            header($trimmed, false);
            return strlen($line);
        });
        curl_setopt($ch, CURLOPT_WRITEFUNCTION, static function ($ch, string $chunk): int {
            echo $chunk;
            flush();
            return strlen($chunk);
        });
        $ok = curl_exec($ch);
        if ($ok === false && !$statusSent) {
            http_response_code(502);
            header('Content-Type: text/plain; charset=utf-8');
            echo "MediaMarketplace server did not respond: " . curl_error($ch) . "\n";
        }
        curl_close($ch);
    }

    /**
     * Rebuilds a parsed multipart request as curl fields. Repeated fields (files[]) become
     * name[0], name[1], ... which the server reads as the same field name.
     *
     * @return array<string,mixed>
     */
    private static function multipartFields(): array
    {
        $fields = [];
        foreach ($_POST as $name => $value) {
            if (is_array($value)) {
                foreach (array_values($value) as $i => $v) {
                    $fields[$name . '[' . $i . ']'] = (string) $v;
                }
            } else {
                $fields[(string) $name] = (string) $value;
            }
        }
        foreach ($_FILES as $name => $file) {
            $names = (array) $file['name'];
            $tmps = (array) $file['tmp_name'];
            $types = (array) ($file['type'] ?? []);
            $errors = (array) ($file['error'] ?? []);
            $multi = is_array($file['name']);
            foreach ($tmps as $i => $tmp) {
                if (($errors[$i] ?? UPLOAD_ERR_OK) !== UPLOAD_ERR_OK || $tmp === '' || !is_uploaded_file($tmp)) {
                    continue;
                }
                $key = $multi ? $name . '[' . $i . ']' : (string) $name;
                $fields[$key] = new CURLFile($tmp, (string) ($types[$i] ?? 'application/octet-stream'), (string) ($names[$i] ?? 'upload'));
            }
        }
        return $fields;
    }

    /** Effective PHP upload limits, the smaller of upload_max_filesize and post_max_size, in MB. */
    public static function phpUploadLimitMb(): int
    {
        $toMb = static function (string $v): int {
            $v = trim($v);
            if ($v === '' || $v === '0' || $v === '-1') {
                return PHP_INT_MAX;
            }
            $n = (float) $v;
            switch (strtolower(substr($v, -1))) {
                case 'g': return (int) ($n * 1024);
                case 'm': return (int) $n;
                case 'k': return (int) max(1, $n / 1024);
                default: return (int) max(1, $n / 1048576);
            }
        };
        return min($toMb((string) ini_get('upload_max_filesize')), $toMb((string) ini_get('post_max_size')));
    }

    /** @return array<string,string> */
    private static function requestHeaders(): array
    {
        if (function_exists('getallheaders')) {
            $h = getallheaders();
            if (is_array($h)) {
                return $h;
            }
        }
        $out = [];
        foreach ($_SERVER as $k => $v) {
            if (str_starts_with($k, 'HTTP_')) {
                $out[str_replace(' ', '-', ucwords(strtolower(str_replace('_', ' ', substr($k, 5)))))] = (string) $v;
            } elseif ($k === 'CONTENT_TYPE') {
                $out['Content-Type'] = (string) $v;
            }
        }
        return $out;
    }

    // ----- single sign-on and embeds -------------------------------------------------

    /**
     * @param array{id:int|string,email:string,name:string} $user
     */
    public function ssoUrl(array $user, string $return = '/account', bool $admin = false): string
    {
        $claims = [
            'sub'   => (string) $user['id'],
            'email' => (string) $user['email'],
            'name'  => (string) $user['name'],
            'host'  => (string) $this->o['host'],
            'exp'   => time() + self::TOKEN_TTL,
        ];
        if ($admin) {
            $claims['role'] = 'admin';
        }
        $token = self::signToken($claims, $this->secret());
        return $this->publicUrl() . '/sso?' . http_build_query(['site' => $this->siteId(), 'token' => $token, 'return' => $return]);
    }

    /**
     * Token = base64url(json) . "." . base64url(HMAC-SHA256(json, secret)).
     * Canonical claim order: sub, email, name, host, [role], exp. The server verifies
     * the signature over the raw JSON bytes.
     *
     * @param array<string,mixed> $claims
     */
    public static function signToken(array $claims, string $secret): string
    {
        $ordered = ['sub' => (string) $claims['sub'], 'email' => (string) $claims['email'], 'name' => (string) $claims['name'], 'host' => (string) $claims['host']];
        if (!empty($claims['role'])) {
            $ordered['role'] = (string) $claims['role'];
        }
        $ordered['exp'] = (int) $claims['exp'];
        $json = json_encode($ordered, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($json === false) {
            throw new RuntimeException('Could not encode SSO claims');
        }
        return self::b64url($json) . '.' . self::b64url(hash_hmac('sha256', $json, $secret, true));
    }

    public static function b64url(string $raw): string
    {
        return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
    }

    /** @param array<string,string> $params */
    public function embed(string $kind, array $params = []): string
    {
        $attrs = 'data-mms-embed="' . htmlspecialchars($kind, ENT_QUOTES) . '" data-mms-site="' . htmlspecialchars($this->siteId(), ENT_QUOTES) . '"';
        foreach ($params as $k => $v) {
            if ((string) $v === '' || !preg_match('/^[a-z_]+$/', (string) $k)) {
                continue;
            }
            $attrs .= ' data-mms-' . $k . '="' . htmlspecialchars((string) $v, ENT_QUOTES) . '"';
        }
        return '<div class="mms-embed" ' . $attrs . '></div>';
    }

    public function loaderTag(): string
    {
        return '<script src="' . htmlspecialchars($this->publicUrl() . '/embed.js', ENT_QUOTES) . '" defer></script>';
    }

    public function adminUrl(): string { return $this->publicUrl() . '/admin'; }

    // ----- sell-through API (WooCommerce / VirtueMart modules) ------------------------

    /**
     * Signature for a sell-through request: HMAC-SHA256 over "{ts}\n{METHOD}\n{path}\n{body}"
     * with the site secret, as lowercase hex. The path excludes the query string.
     * Fixture shared with crates/mms-core/src/commerce_bridge.rs.
     */
    public static function signRequest(string $secret, int $ts, string $method, string $path, string $body): string
    {
        return hash_hmac('sha256', $ts . "\n" . strtoupper($method) . "\n" . $path . "\n" . $body, $secret);
    }

    /**
     * Calls the store's sell-through API directly on localhost (no proxy round trip),
     * signed with this site's secret. Returns ['ok' => bool, 'status' => int, 'data' => mixed, 'error' => string].
     *
     * @param array<string,mixed>|null $body
     * @return array{ok:bool,status:int,data:mixed,error:string}
     */
    public function apiCall(string $method, string $path, ?array $body = null): array
    {
        if (!$this->ensureRunning()) {
            return ['ok' => false, 'status' => 0, 'data' => null, 'error' => 'The store server is not running'];
        }
        $method = strtoupper($method);
        $query = '';
        if (($q = strpos($path, '?')) !== false) {
            $query = substr($path, $q);
            $path = substr($path, 0, $q);
        }
        $signedPath = $this->basePath() . $path;
        $raw = $body === null ? '' : (string) json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $ts = time();
        $ch = curl_init('http://127.0.0.1:' . $this->port() . $signedPath . $query);
        $headers = [
            'Accept: application/json',
            'X-MMS-Site: ' . $this->siteId(),
            'X-MMS-Timestamp: ' . $ts,
            'X-MMS-Signature: ' . self::signRequest($this->secret(), $ts, $method, $signedPath, $raw),
        ];
        if ($body !== null) {
            $headers[] = 'Content-Type: application/json';
        }
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 20, CURLOPT_CONNECTTIMEOUT => 3,
            CURLOPT_CUSTOMREQUEST => $method, CURLOPT_HTTPHEADER => $headers,
            CURLOPT_POSTFIELDS => $body === null ? null : $raw,
        ]);
        $res = curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if ($res === false) {
            return ['ok' => false, 'status' => 0, 'data' => null, 'error' => $err !== '' ? $err : 'no response'];
        }
        $j = json_decode((string) $res, true);
        if (!is_array($j)) {
            return ['ok' => false, 'status' => $status, 'data' => null, 'error' => 'invalid response (' . $status . ')'];
        }
        if ($status >= 400 || isset($j['error'])) {
            $msg = is_array($j['error'] ?? null) ? (string) ($j['error']['message'] ?? 'error') : (string) ($j['error'] ?? 'error');
            return ['ok' => false, 'status' => $status, 'data' => $j['data'] ?? null, 'error' => $msg];
        }
        return ['ok' => true, 'status' => $status, 'data' => $j['data'] ?? $j, 'error' => ''];
    }

    /** Where a member lands after sign-on, as a full store address (for links in the shop). */
    public function accountUrl(string $path = '/account'): string
    {
        return $this->publicUrl() . $path;
    }

    private static function uuid(): string
    {
        $b = random_bytes(16);
        $b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
        $b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
    }
}
