<?php

declare(strict_types=1);

/**
 * A failed Google Cloud REST call, with the machine-readable bits the UI
 * needs to offer a fix (for example "this API is turned off — enable it").
 */
final class GoogleApiException extends RuntimeException
{
    public function __construct(
        string $message,
        public readonly int $httpStatus = 0,
        public readonly string $reason = '',
        public readonly string $service = '',
    ) {
        parent::__construct($message, $httpStatus);
    }

    public function isServiceDisabled(): bool
    {
        return $this->reason === 'SERVICE_DISABLED';
    }
}

/**
 * Google Cloud Client
 *
 * Dependency-free REST client for the handful of Google Cloud APIs the key
 * manager needs, so nobody has to open the Cloud Console:
 *
 *   - API Keys API v2        create / list / read / edit / delete / restore keys
 *   - Service Usage API v1   list and enable the APIs a project can call
 *   - Resource Manager v3    list the projects you can reach
 *   - Monitoring API v3      requests, error rate and latency per API
 *
 * Authentication is a token provider callable. Three are built in: your own
 * gcloud sign-in, a service account key file (signed locally with openssl),
 * or a pasted access token. The HTTP transport is injectable so the contract
 * tests run offline.
 */
final class GoogleCloudClient
{
    public const SCOPE = 'https://www.googleapis.com/auth/cloud-platform';
    public const TOKEN_URI = 'https://oauth2.googleapis.com/token';

    private const API_KEYS = 'https://apikeys.googleapis.com/v2/';
    private const SERVICE_USAGE = 'https://serviceusage.googleapis.com/v1/';
    private const RESOURCE_MANAGER = 'https://cloudresourcemanager.googleapis.com/v3/';
    private const MONITORING = 'https://monitoring.googleapis.com/v3/';

    /** Application restriction types the editor understands. */
    public const APP_TYPES = [
        'none' => 'No restriction',
        'browser' => 'Websites (HTTP referrers)',
        'server' => 'Servers (IP addresses)',
        'android' => 'Android apps',
        'ios' => 'iOS apps',
    ];

    /** @var callable(): string */
    private $tokenProvider;

    /** @var callable(string, string, array<int, string>, ?string): array{status: int, body: string} */
    private $transport;

    /** @var callable(int): void */
    private $sleep;

    public function __construct(
        callable $tokenProvider,
        ?callable $transport = null,
        private ?string $quotaProject = null,
        ?callable $sleep = null,
    ) {
        $this->tokenProvider = $tokenProvider;
        $this->transport = $transport ?? self::curlTransport();
        $this->sleep = $sleep ?? static function (int $ms): void {
            usleep($ms * 1000);
        };
        if ($quotaProject !== null) {
            self::assertProject($quotaProject);
        }
    }

    // ------------------------------------------------------------------
    // Authentication
    // ------------------------------------------------------------------

    /** Use the access token of whoever ran `gcloud auth login` on this machine. */
    public static function gcloudTokenProvider(string $binary = 'gcloud'): callable
    {
        return static function () use ($binary): string {
            $process = @proc_open(
                [$binary, 'auth', 'print-access-token'],
                [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
                $pipes
            );
            if (!is_resource($process)) {
                throw new GoogleApiException('Could not run gcloud ("' . $binary . '"). Install the Google Cloud CLI or set its full path on the Connection tab.');
            }
            fclose($pipes[0]);
            $out = (string) stream_get_contents($pipes[1]);
            $err = (string) stream_get_contents($pipes[2]);
            fclose($pipes[1]);
            fclose($pipes[2]);
            $code = proc_close($process);
            $token = trim($out);
            if ($code !== 0 || $token === '') {
                $detail = trim($err !== '' ? $err : $out);
                throw new GoogleApiException('gcloud did not return a token' . ($detail !== '' ? ': ' . $detail : '') . '. Run "gcloud auth login" in a terminal once, then try again.');
            }
            return $token;
        };
    }

    /** A token pasted by the user (for example from `gcloud auth print-access-token`). */
    public static function staticTokenProvider(string $token): callable
    {
        $token = trim($token);
        return static function () use ($token): string {
            if ($token === '') {
                throw new GoogleApiException('No access token saved. Paste one on the Connection tab.');
            }
            return $token;
        };
    }

    /**
     * Exchange a service account key file for access tokens. The JWT is signed
     * locally and only ever sent to Google's own token endpoint, whatever the
     * key file's token_uri says.
     *
     * @param array<string, mixed> $account Decoded service account JSON.
     */
    public static function serviceAccountTokenProvider(array $account, ?callable $transport = null, ?callable $clock = null): callable
    {
        $transport ??= self::curlTransport();
        $clock ??= static fn (): int => time();
        $cache = ['token' => '', 'expires' => 0];
        return static function () use ($account, $transport, $clock, &$cache): string {
            $now = $clock();
            if ($cache['token'] !== '' && $cache['expires'] - 60 > $now) {
                return $cache['token'];
            }
            $body = http_build_query([
                'grant_type' => 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion' => self::serviceAccountAssertion($account, $now),
            ]);
            $response = $transport('POST', self::TOKEN_URI, ['Content-Type: application/x-www-form-urlencoded', 'Accept: application/json'], $body);
            $data = json_decode($response['body'], true);
            if ($response['status'] >= 400 || !is_array($data) || !isset($data['access_token'])) {
                $why = is_array($data) ? (string) ($data['error_description'] ?? $data['error'] ?? '') : '';
                throw new GoogleApiException('Google refused the service account key' . ($why !== '' ? ': ' . $why : '.'), $response['status']);
            }
            $cache = ['token' => (string) $data['access_token'], 'expires' => $now + (int) ($data['expires_in'] ?? 3600)];
            return $cache['token'];
        };
    }

    /** @param array<string, mixed> $account */
    public static function serviceAccountAssertion(array $account, int $now): string
    {
        $email = (string) ($account['client_email'] ?? '');
        $pem = (string) ($account['private_key'] ?? '');
        if ($email === '' || $pem === '') {
            throw new InvalidArgumentException('That is not a service account key file (client_email and private_key are required).');
        }
        $header = ['alg' => 'RS256', 'typ' => 'JWT'];
        if (!empty($account['private_key_id'])) {
            $header['kid'] = (string) $account['private_key_id'];
        }
        $claims = ['iss' => $email, 'scope' => self::SCOPE, 'aud' => self::TOKEN_URI, 'iat' => $now, 'exp' => $now + 3600];
        $input = self::base64Url((string) json_encode($header, JSON_UNESCAPED_SLASHES))
            . '.' . self::base64Url((string) json_encode($claims, JSON_UNESCAPED_SLASHES));
        $key = openssl_pkey_get_private($pem);
        if ($key === false) {
            throw new InvalidArgumentException('The service account private key could not be read.');
        }
        $signature = '';
        if (!openssl_sign($input, $signature, $key, OPENSSL_ALGO_SHA256)) {
            throw new RuntimeException('Could not sign the service account token request.');
        }
        return $input . '.' . self::base64Url($signature);
    }

    public static function base64Url(string $bytes): string
    {
        return rtrim(strtr(base64_encode($bytes), '+/', '-_'), '=');
    }

    /** @return callable(string, string, array<int, string>, ?string): array{status: int, body: string} */
    public static function curlTransport(): callable
    {
        return static function (string $method, string $url, array $headers, ?string $body): array {
            if (!function_exists('curl_init')) {
                throw new GoogleApiException('The PHP curl extension is required to talk to Google.');
            }
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_CUSTOMREQUEST => $method,
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_HTTPHEADER => $headers,
                CURLOPT_CONNECTTIMEOUT => 10,
                CURLOPT_TIMEOUT => 45,
            ]);
            if ($body !== null) {
                curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
            }
            $response = curl_exec($ch);
            if ($response === false) {
                throw new GoogleApiException('Could not reach Google: ' . curl_error($ch));
            }
            return ['status' => (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE), 'body' => (string) $response];
        };
    }

    // ------------------------------------------------------------------
    // Projects and APIs
    // ------------------------------------------------------------------

    /** @return array<int, array{id: string, name: string, number: string, state: string}> */
    public function searchProjects(): array
    {
        $projects = [];
        foreach ($this->pages(self::RESOURCE_MANAGER . 'projects:search?pageSize=200', 'projects') as $project) {
            $projects[] = [
                'id' => (string) ($project['projectId'] ?? ''),
                'name' => (string) ($project['displayName'] ?? $project['projectId'] ?? ''),
                'number' => preg_replace('~^projects/~', '', (string) ($project['name'] ?? '')) ?? '',
                'state' => (string) ($project['state'] ?? ''),
            ];
        }
        usort($projects, static fn (array $a, array $b): int => strcasecmp($a['name'], $b['name']));
        return $projects;
    }

    /** @return array<string, string> service name => human title, sorted by title */
    public function enabledServices(string $project): array
    {
        self::assertProject($project);
        $url = self::SERVICE_USAGE . 'projects/' . rawurlencode($project) . '/services?filter=state:ENABLED&pageSize=200';
        $services = [];
        foreach ($this->pages($url, 'services') as $service) {
            $name = (string) ($service['config']['name'] ?? basename((string) ($service['name'] ?? '')));
            if ($name !== '') {
                $services[$name] = (string) ($service['config']['title'] ?? $name);
            }
        }
        uasort($services, static fn (string $a, string $b): int => strcasecmp($a, $b));
        return $services;
    }

    public function enableService(string $project, string $service): void
    {
        self::assertProject($project);
        self::assertService($service);
        $operation = $this->call('POST', self::SERVICE_USAGE . 'projects/' . rawurlencode($project) . '/services/' . $service . ':enable', (object) []);
        $this->waitFor(self::SERVICE_USAGE, $operation);
    }

    // ------------------------------------------------------------------
    // API keys
    // ------------------------------------------------------------------

    /** @return array<int, array<string, mixed>> */
    public function listKeys(string $project, bool $showDeleted = false): array
    {
        self::assertProject($project);
        $url = self::API_KEYS . 'projects/' . rawurlencode($project) . '/locations/global/keys?pageSize=300' . ($showDeleted ? '&showDeleted=true' : '');
        $keys = $this->pages($url, 'keys');
        usort($keys, static fn (array $a, array $b): int => strcmp((string) ($b['createTime'] ?? ''), (string) ($a['createTime'] ?? '')));
        return $keys;
    }

    /** @return array<string, mixed> */
    public function getKey(string $name): array
    {
        self::assertKeyName($name);
        return $this->call('GET', self::API_KEYS . $name);
    }

    public function keyString(string $name): string
    {
        self::assertKeyName($name);
        $data = $this->call('GET', self::API_KEYS . $name . '/keyString');
        return (string) ($data['keyString'] ?? '');
    }

    /**
     * Create a key and return it — including its keyString, which Google only
     * hands back here and from keyString().
     *
     * @param array<string, mixed> $restrictions
     * @return array<string, mixed>
     */
    public function createKey(string $project, string $displayName, array $restrictions = []): array
    {
        self::assertProject($project);
        $body = ['displayName' => self::cleanDisplayName($displayName)];
        if ($restrictions !== []) {
            $body['restrictions'] = $restrictions;
        }
        $operation = $this->call('POST', self::API_KEYS . 'projects/' . rawurlencode($project) . '/locations/global/keys', $body);
        $key = $this->waitFor(self::API_KEYS, $operation);
        if (!isset($key['keyString']) && isset($key['name'])) {
            $key['keyString'] = $this->keyString((string) $key['name']);
        }
        return $key;
    }

    /**
     * Rename a key and replace its restrictions. Passing the etag from
     * getKey() makes Google refuse the edit if someone changed the key since.
     *
     * @param array<string, mixed> $restrictions
     * @return array<string, mixed>
     */
    public function updateKey(string $name, string $displayName, array $restrictions, string $etag = ''): array
    {
        self::assertKeyName($name);
        $body = [
            'displayName' => self::cleanDisplayName($displayName),
            'restrictions' => $restrictions === [] ? (object) [] : $restrictions,
        ];
        if ($etag !== '') {
            $body['etag'] = $etag;
        }
        $operation = $this->call('PATCH', self::API_KEYS . $name . '?updateMask=displayName,restrictions', $body);
        return $this->waitFor(self::API_KEYS, $operation);
    }

    /** Soft-delete: Google keeps the key restorable for 30 days. */
    public function deleteKey(string $name, string $etag = ''): void
    {
        self::assertKeyName($name);
        $operation = $this->call('DELETE', self::API_KEYS . $name . ($etag !== '' ? '?etag=' . rawurlencode($etag) : ''));
        $this->waitFor(self::API_KEYS, $operation);
    }

    public function undeleteKey(string $name): void
    {
        self::assertKeyName($name);
        $operation = $this->call('POST', self::API_KEYS . $name . ':undelete', (object) []);
        $this->waitFor(self::API_KEYS, $operation);
    }

    // ------------------------------------------------------------------
    // Traffic (the Console's "Requests / Errors / Latency" table)
    // ------------------------------------------------------------------

    /**
     * @return array<string, array{requests: int, errors: int, error_pct: ?float, p50_ms: ?float, p95_ms: ?float}>
     */
    public function serviceMetrics(string $project, int $windowSeconds, ?int $now = null): array
    {
        self::assertProject($project);
        $windowSeconds = max(60, $windowSeconds);
        $end = $now ?? time();
        $interval = [
            'interval.startTime' => gmdate('Y-m-d\TH:i:s\Z', $end - $windowSeconds),
            'interval.endTime' => gmdate('Y-m-d\TH:i:s\Z', $end),
            'aggregation.alignmentPeriod' => $windowSeconds . 's',
        ];
        $metrics = [];
        $blank = ['requests' => 0, 'errors' => 0, 'error_pct' => null, 'p50_ms' => null, 'p95_ms' => null];

        $counts = $this->timeSeries($project, $interval + [
            'filter' => 'metric.type="serviceruntime.googleapis.com/api/request_count" AND resource.type="consumed_api"',
            'aggregation.perSeriesAligner' => 'ALIGN_DELTA',
            'aggregation.crossSeriesReducer' => 'REDUCE_SUM',
        ], ['resource.label.service', 'metric.label.response_code_class']);
        foreach ($counts as $series) {
            $service = (string) ($series['resource']['labels']['service'] ?? '');
            if ($service === '') {
                continue;
            }
            $class = (string) ($series['metric']['labels']['response_code_class'] ?? '');
            $total = 0;
            foreach ((array) ($series['points'] ?? []) as $point) {
                $total += (int) ($point['value']['int64Value'] ?? 0);
            }
            $metrics[$service] ??= $blank;
            $metrics[$service]['requests'] += $total;
            if (in_array($class, ['4xx', '5xx'], true)) {
                $metrics[$service]['errors'] += $total;
            }
        }

        foreach (['p50_ms' => 'REDUCE_PERCENTILE_50', 'p95_ms' => 'REDUCE_PERCENTILE_95'] as $field => $reducer) {
            $latencies = $this->timeSeries($project, $interval + [
                'filter' => 'metric.type="serviceruntime.googleapis.com/api/request_latencies" AND resource.type="consumed_api"',
                'aggregation.perSeriesAligner' => 'ALIGN_DELTA',
                'aggregation.crossSeriesReducer' => $reducer,
            ], ['resource.label.service']);
            foreach ($latencies as $series) {
                $service = (string) ($series['resource']['labels']['service'] ?? '');
                $point = $series['points'][0]['value'] ?? null;
                if ($service === '' || !is_array($point) || !isset($point['doubleValue'])) {
                    continue;
                }
                $metrics[$service] ??= $blank;
                $metrics[$service][$field] = round((float) $point['doubleValue'] * 1000, 1);
            }
        }

        foreach ($metrics as &$row) {
            $row['error_pct'] = $row['requests'] > 0 ? round($row['errors'] / $row['requests'] * 100, 2) : null;
        }
        unset($row);
        ksort($metrics);
        return $metrics;
    }

    // ------------------------------------------------------------------
    // Restrictions: form fields <-> API shape
    // ------------------------------------------------------------------

    /**
     * Build the API's restrictions object from simple form input.
     *
     * @param string $appType One of APP_TYPES.
     * @param string $lines One referrer / IP / bundle id per line; Android lines are "package.name SHA1".
     * @param array<int, string> $apiServices Services the key may call; empty means any API.
     * @return array<string, mixed>
     */
    public static function buildRestrictions(string $appType, string $lines, array $apiServices): array
    {
        $values = array_values(array_unique(array_filter(array_map('trim', preg_split('/[\r\n,]+/', $lines) ?: []), static fn (string $v): bool => $v !== '')));
        $restrictions = [];
        if ($values !== []) {
            switch ($appType) {
                case 'browser':
                    $restrictions['browserKeyRestrictions'] = ['allowedReferrers' => $values];
                    break;
                case 'server':
                    $restrictions['serverKeyRestrictions'] = ['allowedIps' => $values];
                    break;
                case 'ios':
                    $restrictions['iosKeyRestrictions'] = ['allowedBundleIds' => $values];
                    break;
                case 'android':
                    $apps = [];
                    foreach ($values as $value) {
                        $parts = preg_split('/[\s;]+/', $value) ?: [];
                        if (count($parts) !== 2) {
                            throw new InvalidArgumentException('Android lines need a package name and a SHA-1 fingerprint, e.g. "com.example.app DA:39:A3:...": ' . $value);
                        }
                        $apps[] = ['packageName' => $parts[0], 'sha1Fingerprint' => $parts[1]];
                    }
                    $restrictions['androidKeyRestrictions'] = ['allowedApplications' => $apps];
                    break;
            }
        }
        $targets = [];
        foreach (array_values(array_unique($apiServices)) as $service) {
            self::assertService($service);
            $targets[] = ['service' => $service];
        }
        if ($targets !== []) {
            $restrictions['apiTargets'] = $targets;
        }
        return $restrictions;
    }

    /**
     * @param array<string, mixed> $restrictions
     * @return array{type: string, lines: string, apis: array<int, string>}
     */
    public static function restrictionsToForm(array $restrictions): array
    {
        $type = 'none';
        $values = [];
        if (isset($restrictions['browserKeyRestrictions'])) {
            $type = 'browser';
            $values = (array) ($restrictions['browserKeyRestrictions']['allowedReferrers'] ?? []);
        } elseif (isset($restrictions['serverKeyRestrictions'])) {
            $type = 'server';
            $values = (array) ($restrictions['serverKeyRestrictions']['allowedIps'] ?? []);
        } elseif (isset($restrictions['iosKeyRestrictions'])) {
            $type = 'ios';
            $values = (array) ($restrictions['iosKeyRestrictions']['allowedBundleIds'] ?? []);
        } elseif (isset($restrictions['androidKeyRestrictions'])) {
            $type = 'android';
            foreach ((array) ($restrictions['androidKeyRestrictions']['allowedApplications'] ?? []) as $app) {
                $values[] = ($app['packageName'] ?? '') . ' ' . ($app['sha1Fingerprint'] ?? '');
            }
        }
        $apis = [];
        foreach ((array) ($restrictions['apiTargets'] ?? []) as $target) {
            $apis[] = (string) ($target['service'] ?? '');
        }
        return ['type' => $type, 'lines' => implode("\n", array_map('strval', $values)), 'apis' => array_values(array_filter($apis))];
    }

    /**
     * Plain-English summary for the keys table.
     *
     * @param array<string, mixed> $restrictions
     * @param array<string, string> $titles service => title
     * @return array{app: string, apis: string}
     */
    public static function describeRestrictions(array $restrictions, array $titles = []): array
    {
        $form = self::restrictionsToForm($restrictions);
        $count = $form['lines'] === '' ? 0 : count(explode("\n", $form['lines']));
        $app = match ($form['type']) {
            'browser' => "Only {$count} website" . ($count === 1 ? '' : 's'),
            'server' => "Only {$count} IP address" . ($count === 1 ? '' : 'es'),
            'android' => "Only {$count} Android app" . ($count === 1 ? '' : 's'),
            'ios' => "Only {$count} iOS app" . ($count === 1 ? '' : 's'),
            default => 'Usable from anywhere',
        };
        if ($form['apis'] === []) {
            $apis = 'Can call any enabled API';
        } else {
            $names = array_map(static fn (string $s): string => $titles[$s] ?? $s, $form['apis']);
            $apis = count($names) <= 2 ? implode(', ', $names) : $names[0] . ', ' . $names[1] . ' +' . (count($names) - 2) . ' more';
        }
        return ['app' => $app, 'apis' => $apis];
    }

    // ------------------------------------------------------------------
    // Validation (names go into URL paths, so they must be exact)
    // ------------------------------------------------------------------

    public static function isProjectId(string $project): bool
    {
        return preg_match('/^(?:[a-z0-9.\-]+:)?[a-z0-9][a-z0-9\-]{2,61}[a-z0-9]$/', $project) === 1;
    }

    public static function assertProject(string $project): void
    {
        if (!self::isProjectId($project)) {
            throw new InvalidArgumentException('That does not look like a Google Cloud project ID: ' . $project);
        }
    }

    public static function assertKeyName(string $name): void
    {
        if (preg_match('~^projects/[a-z0-9.:\-]+/locations/global/keys/[A-Za-z0-9\-]+$~', $name) !== 1) {
            throw new InvalidArgumentException('Not a valid API key resource name.');
        }
    }

    public static function assertService(string $service): void
    {
        if (preg_match('/^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$/', $service) !== 1) {
            throw new InvalidArgumentException('Not a valid API service name (expected something like youtube.googleapis.com): ' . $service);
        }
    }

    private static function cleanDisplayName(string $name): string
    {
        $name = trim(preg_replace('/\s+/u', ' ', $name) ?? '');
        if ($name === '') {
            throw new InvalidArgumentException('Give the key a name so you can recognise it later.');
        }
        return mb_substr($name, 0, 63);
    }

    // ------------------------------------------------------------------
    // Plumbing
    // ------------------------------------------------------------------

    /**
     * @param array<string, string> $params
     * @param array<int, string> $groupBy
     * @return array<int, array<string, mixed>>
     */
    private function timeSeries(string $project, array $params, array $groupBy): array
    {
        $query = http_build_query($params, '', '&', PHP_QUERY_RFC3986);
        foreach ($groupBy as $field) {
            $query .= '&aggregation.groupByFields=' . rawurlencode($field);
        }
        return $this->pages(self::MONITORING . 'projects/' . rawurlencode($project) . '/timeSeries?' . $query, 'timeSeries');
    }

    /** @return array<int, array<string, mixed>> */
    private function pages(string $url, string $field): array
    {
        $items = [];
        $token = '';
        for ($page = 0; $page < 50; $page++) {
            $data = $this->call('GET', $url . ($token !== '' ? '&pageToken=' . rawurlencode($token) : ''));
            foreach ((array) ($data[$field] ?? []) as $item) {
                $items[] = (array) $item;
            }
            $token = (string) ($data['nextPageToken'] ?? '');
            if ($token === '') {
                break;
            }
        }
        return $items;
    }

    /**
     * Wait for a long-running operation and return its response.
     *
     * @param array<string, mixed> $operation
     * @return array<string, mixed>
     */
    private function waitFor(string $base, array $operation): array
    {
        $delay = 300;
        for ($attempt = 0; empty($operation['done']); $attempt++) {
            $name = (string) ($operation['name'] ?? '');
            if ($attempt >= 20 || preg_match('~^operations/[A-Za-z0-9._\-]+$~', $name) !== 1) {
                throw new GoogleApiException('Google accepted the change but it is still in progress. Refresh in a minute to see it.');
            }
            ($this->sleep)($delay);
            $delay = min($delay * 2, 3000);
            $operation = $this->call('GET', $base . $name);
        }
        if (isset($operation['error'])) {
            throw new GoogleApiException('Google could not finish the change: ' . (string) ($operation['error']['message'] ?? 'unknown error'));
        }
        return (array) ($operation['response'] ?? []);
    }

    /**
     * @param array<string, mixed>|object|null $body
     * @return array<string, mixed>
     */
    private function call(string $method, string $url, array|object|null $body = null): array
    {
        $headers = ['Authorization: Bearer ' . ($this->tokenProvider)(), 'Accept: application/json'];
        if ($this->quotaProject !== null) {
            $headers[] = 'x-goog-user-project: ' . $this->quotaProject;
        }
        $payload = null;
        if ($body !== null) {
            $headers[] = 'Content-Type: application/json';
            $payload = json_encode($body, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
        }
        $response = ($this->transport)($method, $url, $headers, $payload);
        $data = $response['body'] === '' ? [] : json_decode($response['body'], true);
        if ($response['status'] >= 400 || !is_array($data)) {
            throw self::errorFrom($response['status'], is_array($data) ? $data : []);
        }
        return $data;
    }

    /** @param array<string, mixed> $data */
    private static function errorFrom(int $status, array $data): GoogleApiException
    {
        $error = (array) ($data['error'] ?? []);
        $reason = '';
        $service = '';
        foreach ((array) ($error['details'] ?? []) as $detail) {
            if (str_ends_with((string) ($detail['@type'] ?? ''), 'google.rpc.ErrorInfo')) {
                $reason = (string) ($detail['reason'] ?? '');
                $service = (string) ($detail['metadata']['service'] ?? '');
            }
        }
        $message = (string) ($error['message'] ?? ($status > 0 ? "Google answered with HTTP {$status}." : 'Google sent an unreadable answer.'));
        if ($status === 401) {
            $message = 'Google did not accept the sign-in (it may have expired). Check the Connection tab. ' . $message;
        } elseif ($status === 403 && $reason !== 'SERVICE_DISABLED') {
            $message = 'Permission denied — the signed-in account cannot do this in this project. ' . $message;
        }
        return new GoogleApiException($message, $status, $reason, $service);
    }
}
