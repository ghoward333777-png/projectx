<?php

declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    exit;
}

require_once __DIR__ . '/../KeyVault.php';
require_once __DIR__ . '/../GoogleCloudClient.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

function contract_throws(callable $fn): ?Throwable
{
    try {
        $fn();
    } catch (Throwable $e) {
        return $e;
    }
    return null;
}

// ---------------------------------------------------------------- vault
$dir = sys_get_temp_dir() . '/ckm-test-' . bin2hex(random_bytes(4));
$vault = new KeyVault($dir . '/vault.json');
contract_check(!$vault->exists(), 'a fresh path has no vault');
contract_check(contract_throws(fn () => $vault->create('short')) instanceof InvalidArgumentException, 'short passphrases are refused');

$secret = 'AIzaFAKE-test-secret-0123456789abcdefghij';
$key = $vault->create('correct horse battery');
$data = KeyVault::upsert($vault->read($key), ['label' => 'Test key', 'key_string' => $secret, 'google_name' => 'projects/demo-proj/locations/global/keys/abc']);
$vault->write($key, $data);

$raw = (string) file_get_contents($vault->path());
contract_check(!str_contains($raw, $secret) && !str_contains($raw, 'Test key'), 'the vault file never contains secrets or labels in clear text');
contract_check((fileperms($vault->path()) & 0777) === 0600, 'the vault file is readable by its owner only');
contract_check(contract_throws(fn () => $vault->unlock('wrong passphrase!!')) instanceof InvalidArgumentException, 'a wrong passphrase does not open the vault');
contract_check(contract_throws(fn () => $vault->create('correct horse battery')) instanceof RuntimeException, 'an existing vault is never overwritten by setup');

$reopened = new KeyVault($dir . '/vault.json');
$again = $reopened->read($reopened->unlock('correct horse battery'));
contract_check(($again['entries'][0]['key_string'] ?? '') === $secret, 'stored keys survive a round trip');
$id = (string) $again['entries'][0]['id'];
contract_check(KeyVault::findByGoogleName($again, 'projects/demo-proj/locations/global/keys/abc')['id'] === $id, 'entries are found by Google resource name');

$again = KeyVault::upsert($again, ['id' => $id, 'label' => 'Renamed']);
contract_check(count($again['entries']) === 1 && $again['entries'][0]['key_string'] === $secret && $again['entries'][0]['label'] === 'Renamed', 'upsert by id edits in place and keeps unspecified fields');
contract_check(KeyVault::remove($again, $id)['entries'] === [], 'entries can be removed');
contract_check(KeyVault::mask($secret) === 'AIza••••••••ghij', 'masking shows only the ends of a key');

$tampered = json_decode($raw, true);
$tampered['ciphertext'] = base64_encode(strrev((string) base64_decode($tampered['ciphertext'])));
file_put_contents($dir . '/tampered.json', json_encode($tampered));
$broken = new KeyVault($dir . '/tampered.json');
contract_check(contract_throws(fn () => $broken->unlock('correct horse battery')) !== null, 'a tampered vault refuses to open');

$newKey = $vault->changePassphrase($key, 'a brand new passphrase');
contract_check(contract_throws(fn () => $vault->unlock('correct horse battery')) !== null, 'the old passphrase stops working after a change');
contract_check($vault->read($newKey)['entries'][0]['key_string'] === $secret, 'changing the passphrase keeps every entry');

array_map('unlink', array_merge(glob($dir . '/*') ?: [], [$dir . '/.htaccess']));
@rmdir($dir);

// ---------------------------------------------------------------- service account JWT
$pkey = openssl_pkey_new(['private_key_bits' => 2048, 'private_key_type' => OPENSSL_KEYTYPE_RSA]);
contract_check($pkey !== false, 'openssl can generate a test RSA key');
openssl_pkey_export($pkey, $pem);
$public = openssl_pkey_get_details($pkey)['key'];
$account = ['type' => 'service_account', 'client_email' => 'bot@demo-proj.iam.gserviceaccount.com', 'private_key' => $pem, 'private_key_id' => 'kid1', 'token_uri' => 'https://evil.example/token'];
$jwt = GoogleCloudClient::serviceAccountAssertion($account, 1700000000);
[$h64, $c64, $s64] = explode('.', $jwt);
$b64 = static fn (string $s): string => (string) base64_decode(strtr($s, '-_', '+/'));
$claims = json_decode($b64($c64), true);
contract_check(json_decode($b64($h64), true) === ['alg' => 'RS256', 'typ' => 'JWT', 'kid' => 'kid1'], 'the JWT header is RS256 with the key id');
contract_check($claims['aud'] === GoogleCloudClient::TOKEN_URI, 'the assertion is only ever addressed to Google, whatever token_uri says');
contract_check($claims['scope'] === GoogleCloudClient::SCOPE && $claims['exp'] === 1700003600, 'the assertion asks for cloud-platform for one hour');
contract_check(openssl_verify("{$h64}.{$c64}", $b64($s64), $public, OPENSSL_ALGO_SHA256) === 1, 'the JWT signature verifies with the public key');

$tokenCalls = [];
$tokenTransport = function (string $method, string $url, array $headers, ?string $body) use (&$tokenCalls): array {
    $tokenCalls[] = $url;
    return ['status' => 200, 'body' => '{"access_token":"ya29.test","expires_in":3600}'];
};
$provider = GoogleCloudClient::serviceAccountTokenProvider($account, $tokenTransport, fn (): int => 1700000000);
contract_check($provider() === 'ya29.test' && $provider() === 'ya29.test', 'the service account provider returns the exchanged token');
contract_check($tokenCalls === [GoogleCloudClient::TOKEN_URI], 'tokens are cached and only fetched from Google');

// ---------------------------------------------------------------- REST client with a fake Google
/** @var array<int, array{0: string, 1: string, 2: array<int, string>, 3: ?string}> $calls */
$calls = [];
$routes = [];
$fake = function (string $method, string $url, array $headers, ?string $body) use (&$calls, &$routes): array {
    $calls[] = [$method, $url, $headers, $body];
    foreach ($routes as [$m, $prefix, $response]) {
        if ($m === $method && (str_starts_with($prefix, '*') ? str_contains($url, substr($prefix, 1)) : str_starts_with($url, $prefix))) {
            return is_array($response) ? $response : ['status' => 200, 'body' => (string) $response];
        }
    }
    return ['status' => 404, 'body' => '{"error":{"message":"no fake route for ' . $method . ' ' . $url . '"}}'];
};
$client = new GoogleCloudClient(fn (): string => 'ya29.fake', $fake, 'demo-proj', static function (int $ms): void {});

$keyName = 'projects/demo-proj/locations/global/keys/k1';
$routes = [
    ['POST', 'https://apikeys.googleapis.com/v2/projects/demo-proj/locations/global/keys', '{"name":"operations/akmf.op1","done":false}'],
    ['GET', 'https://apikeys.googleapis.com/v2/operations/akmf.op1', '{"name":"operations/akmf.op1","done":true,"response":{"name":"' . $keyName . '","displayName":"YouTube uploader","keyString":"AIzaNEW"}}'],
];
$restrictions = GoogleCloudClient::buildRestrictions('server', "203.0.113.7\n\n198.51.100.0/24", ['youtube.googleapis.com']);
$created = $client->createKey('demo-proj', '  YouTube   uploader ', $restrictions);
contract_check($created['keyString'] === 'AIzaNEW', 'createKey waits for the operation and returns the key string');
contract_check($calls[0][0] === 'POST' && json_decode((string) $calls[0][3], true) === [
    'displayName' => 'YouTube uploader',
    'restrictions' => ['serverKeyRestrictions' => ['allowedIps' => ['203.0.113.7', '198.51.100.0/24']], 'apiTargets' => [['service' => 'youtube.googleapis.com']]],
], 'createKey sends the cleaned name and restrictions');
contract_check(in_array('Authorization: Bearer ya29.fake', $calls[0][2], true) && in_array('x-goog-user-project: demo-proj', $calls[0][2], true), 'requests carry the bearer token and quota project');

$calls = [];
$routes = [
    ['PATCH', 'https://apikeys.googleapis.com/v2/' . $keyName . '?updateMask=displayName,restrictions', '{"name":"operations/akmf.op2","done":true,"response":{"name":"' . $keyName . '","displayName":"Renamed"}}'],
];
$client->updateKey($keyName, 'Renamed', [], 'etag-1');
contract_check($calls[0][3] === '{"displayName":"Renamed","restrictions":{},"etag":"etag-1"}', 'clearing restrictions sends an empty object, not a list');

$calls = [];
$routes = [
    ['GET', 'https://apikeys.googleapis.com/v2/projects/demo-proj/locations/global/keys?pageSize=300&showDeleted=true&pageToken=p2', '{"keys":[{"name":"b","createTime":"2026-01-01T00:00:00Z"}]}'],
    ['GET', 'https://apikeys.googleapis.com/v2/projects/demo-proj/locations/global/keys?pageSize=300&showDeleted=true', '{"keys":[{"name":"a","createTime":"2026-05-01T00:00:00Z"}],"nextPageToken":"p2"}'],
];
$listed = $client->listKeys('demo-proj', true);
contract_check(array_column($listed, 'name') === ['a', 'b'] && count($calls) === 2, 'listKeys follows every page, newest first');

$routes = [['GET', 'https://apikeys.googleapis.com/v2/projects/demo-proj', ['status' => 403, 'body' => json_encode(['error' => ['code' => 403, 'message' => 'API Keys API has not been used in project demo-proj', 'details' => [['@type' => 'type.googleapis.com/google.rpc.ErrorInfo', 'reason' => 'SERVICE_DISABLED', 'metadata' => ['service' => 'apikeys.googleapis.com']]]]])]]];
$error = contract_throws(fn () => $client->listKeys('demo-proj'));
contract_check($error instanceof GoogleApiException && $error->isServiceDisabled() && $error->service === 'apikeys.googleapis.com', 'a disabled API is reported with the service to turn on');

foreach (['projects/demo-proj/locations/global/keys/../../evil', 'projects/demo-proj/locations/global/keys/k1?x=1', 'https://evil.example/'] as $bad) {
    contract_check(contract_throws(fn () => $client->getKey($bad)) instanceof InvalidArgumentException, 'malformed key names never reach a URL: ' . $bad);
}
contract_check(contract_throws(fn () => $client->listKeys('Bad/Project')) instanceof InvalidArgumentException, 'malformed project ids are refused');
contract_check(contract_throws(fn () => GoogleCloudClient::buildRestrictions('none', '', ['youtube.googleapis.com/../x'])) instanceof InvalidArgumentException, 'malformed service names are refused');

// ---------------------------------------------------------------- restrictions round trip
$android = GoogleCloudClient::buildRestrictions('android', 'com.example.app DA:39:A3', []);
contract_check($android === ['androidKeyRestrictions' => ['allowedApplications' => [['packageName' => 'com.example.app', 'sha1Fingerprint' => 'DA:39:A3']]]], 'android lines become package + fingerprint pairs');
contract_check(GoogleCloudClient::buildRestrictions('browser', '', []) === [], 'no values and no APIs means no restrictions');
$form = GoogleCloudClient::restrictionsToForm($restrictions);
contract_check($form === ['type' => 'server', 'lines' => "203.0.113.7\n198.51.100.0/24", 'apis' => ['youtube.googleapis.com']], 'restrictions load back into the edit form');
contract_check(GoogleCloudClient::buildRestrictions($form['type'], $form['lines'], $form['apis']) === $restrictions, 'saving an untouched edit form keeps the restrictions identical');
contract_check(GoogleCloudClient::describeRestrictions($restrictions, ['youtube.googleapis.com' => 'YouTube Data API v3']) === ['app' => 'Only 2 IP addresses', 'apis' => 'YouTube Data API v3'], 'restrictions are summarised in plain English');

// ---------------------------------------------------------------- traffic table
$routes = [
    ['GET', '*serviceruntime.googleapis.com%2Fapi%2Frequest_count', json_encode(['timeSeries' => [
        ['metric' => ['labels' => ['response_code_class' => '2xx']], 'resource' => ['labels' => ['service' => 'youtube.googleapis.com']], 'points' => [['value' => ['int64Value' => '90']]]],
        ['metric' => ['labels' => ['response_code_class' => '4xx']], 'resource' => ['labels' => ['service' => 'youtube.googleapis.com']], 'points' => [['value' => ['int64Value' => '10']]]],
    ]])],
    ['GET', '*serviceruntime.googleapis.com%2Fapi%2Frequest_latencies', json_encode(['timeSeries' => [
        ['resource' => ['labels' => ['service' => 'youtube.googleapis.com']], 'points' => [['value' => ['doubleValue' => 0.0425]]]],
    ]])],
];
$calls = [];
$metrics = $client->serviceMetrics('demo-proj', 86400, 1700000000);
$yt = $metrics['youtube.googleapis.com'] ?? [];
contract_check(($yt['requests'] ?? 0) === 100 && ($yt['errors'] ?? 0) === 10 && ($yt['error_pct'] ?? 0) === 10.0, 'requests and error rate are summed per API');
contract_check(($yt['p50_ms'] ?? 0) === 42.5 && ($yt['p95_ms'] ?? 0) === 42.5, 'latency is reported in milliseconds');
contract_check(str_contains($calls[0][1], '&aggregation.groupByFields=resource.label.service&aggregation.groupByFields=metric.label.response_code_class'), 'group-by fields are sent as repeated parameters');

fwrite(STDOUT, "Key manager contract passed\n");
