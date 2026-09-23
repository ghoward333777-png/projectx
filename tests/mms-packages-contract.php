<?php

declare(strict_types=1);

/**
 * Contract checks for the MediaMarketplace packages (WordPress plugin, Joomla package, shared runtime).
 * Run: php tests/mms-packages-contract.php
 *
 * When mediamarketplace/target/release/mms-server exists, the runtime is exercised for real:
 * it starts the server, proxies requests through PHP's built-in web server and signs an
 * administrator in through the proxy.
 */

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$root = dirname(__DIR__) . '/mediamarketplace';
$pk = $root . '/packages';

// --- Every PHP file must parse -------------------------------------------------------
$count = 0;
foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator($pk)) as $file) {
    if ($file->getExtension() !== 'php') {
        continue;
    }
    $count++;
    exec('php -l ' . escapeshellarg($file->getPathname()) . ' 2>&1', $out, $code);
    contract_check($code === 0, 'syntax error in ' . $file->getPathname() . ': ' . implode("\n", $out));
}
contract_check($count >= 12, "expected at least 12 PHP files across the packages, found {$count}");

// --- Token fixture shared with crates/mms-core/src/signer.rs --------------------------
require_once $pk . '/shared/MmsRuntime.php';
$expected = 'eyJzdWIiOiI0MiIsImVtYWlsIjoiYUBiLmMiLCJuYW1lIjoiQWRhIiwiaG9zdCI6IndvcmRwcmVzcyIsImV4cCI6MTkwMDAwMDAwMH0.8pn1jJulBkTg4ho6xxjDns7Akf83M9bYHHoTsF6lmr8';
$claims = ['sub' => '42', 'email' => 'a@b.c', 'name' => 'Ada', 'host' => 'wordpress', 'exp' => 1900000000];
contract_check(MmsRuntime::signToken($claims, 'test-secret') === $expected, 'runtime token must match the server fixture');
contract_check(MmsRuntime::signToken($claims + ['role' => 'admin'], 'test-secret') !== $expected, 'the admin role must be part of the signed payload');

// --- Manifests and independence from commerce engines ---------------------------------
$wpMain = (string) file_get_contents($pk . '/wordpress/mediamarketplace-studio/mediamarketplace-studio.php');
contract_check(str_contains($wpMain, 'Plugin Name: MediaMarketplace Studio'), 'WordPress plugin header must be present');
foreach (['wordpress', 'joomla'] as $host) {
    foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator("$pk/$host")) as $file) {
        if ($file->getExtension() === 'php') {
            $src = (string) file_get_contents($file->getPathname());
            foreach (['woocommerce_', 'WC()', "class_exists('WooCommerce')", 'WC_Product', 'vmPSPlugin', 'VmConfig', 'VmModel', 'virtuemart_'] as $needle) {
                contract_check(!str_contains($src, $needle), $file->getPathname() . " must not integrate with a commerce engine ({$needle})");
            }
        }
    }
}
$pkg = simplexml_load_file($pk . '/joomla/pkg_mediamarketplace.xml');
contract_check($pkg !== false && count($pkg->files->file) === 3, 'Joomla package must list plugin, component and module');
foreach (['plg_system_mediamarketplace/mediamarketplace.xml', 'com_mediamarketplace/mediamarketplace.xml', 'mod_mms_embed/mod_mms_embed.xml'] as $manifest) {
    $xml = simplexml_load_file("$pk/joomla/$manifest");
    contract_check($xml !== false && (string) $xml['method'] === 'upgrade' && isset($xml->namespace), "$manifest must be a namespaced upgrade manifest");
}
contract_check(str_contains((string) file_get_contents("$pk/joomla/plg_system_mediamarketplace/mediamarketplace.xml"), '<folder>bin</folder>'), 'the Joomla plugin manifest must ship the bin folder');

// --- Runtime against the real binary ---------------------------------------------------
$bin = $root . '/target/release/mms-server';
if (!is_file($bin)) {
    echo "mms packages contract: ok ({$count} PHP files; runtime test skipped, build the release binary to enable it)\n";
    exit(0);
}
$tmp = sys_get_temp_dir() . '/mms-pkg-' . bin2hex(random_bytes(4));
mkdir($tmp);
$proxyPort = 8199;
$rt = new MmsRuntime([
    'data_dir'   => $tmp . '/data',
    'bin'        => $bin,
    'public_url' => "http://127.0.0.1:{$proxyPort}/mms",
    'origin'     => "http://127.0.0.1:{$proxyPort}",
    'host'       => 'joomla',
    'site_name'  => 'Contract site',
]);
contract_check($rt->platformProblem() === null, 'runtime must accept this Linux host: ' . (string) $rt->platformProblem());
$rt->ensureInstalled();
contract_check(is_file($tmp . '/data/mms.toml') && is_file($tmp . '/data/.htaccess'), 'ensureInstalled must write the config and protect the data dir');
$toml = (string) file_get_contents($tmp . '/data/mms.toml');
contract_check(str_contains($toml, '[[bridges]]') && str_contains($toml, 'admin_sso = true') && str_contains($toml, 'public_url = "http://127.0.0.1:' . $proxyPort . '/mms"'), 'config must declare this site as an admin-capable bridge');
contract_check($rt->start(), 'the bundled server must start: ' . $rt->logTail(10));
contract_check($rt->isRunning() && ($rt->ping()['version'] ?? '') !== '', 'ping must answer once started');

// Proxy through PHP's built-in server, exactly as the plugins do.
$router = $tmp . '/router.php';
file_put_contents($router, '<?php require ' . var_export($pk . '/shared/MmsRuntime.php', true) . '; $rt = new MmsRuntime(' . var_export([
    'data_dir' => $tmp . '/data', 'bin' => $bin, 'public_url' => "http://127.0.0.1:{$proxyPort}/mms",
    'origin' => "http://127.0.0.1:{$proxyPort}", 'host' => 'joomla', 'site_name' => 'Contract site',
], true) . '); $rt->proxy($_SERVER["REQUEST_URI"]); exit;');
$srv = proc_open(['php', '-S', "127.0.0.1:{$proxyPort}", $router], [0 => ['file', '/dev/null', 'r'], 1 => ['file', $tmp . '/php.log', 'a'], 2 => ['file', $tmp . '/php.log', 'a']], $pipes);
contract_check(is_resource($srv), 'PHP built-in server must start');
usleep(700000);

function http(string $url, array $opts = []): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_HEADER => true, CURLOPT_TIMEOUT => 10] + $opts);
    $raw = (string) curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $hsize = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    curl_close($ch);
    return [$code, substr($raw, 0, $hsize), substr($raw, $hsize)];
}

[$code, , $body] = http("http://127.0.0.1:{$proxyPort}/mms/api/v1/ping");
contract_check($code === 200 && str_contains($body, '"ok":true'), "proxy must forward /mms/api/v1/ping (got {$code}: {$body})");
[$code, $hdr] = http("http://127.0.0.1:{$proxyPort}/mms/");
contract_check($code === 303 && preg_match('#^location:\s*/mms\s*$#im', $hdr) === 1, "trailing slash must redirect to /mms (got {$code})");
[$code, , $body] = http("http://127.0.0.1:{$proxyPort}/mms/embed/showcase?site=" . $rt->siteId());
contract_check($code === 200 && str_contains($body, 'No products published yet'), "showcase must render for the declared site (got {$code})");

// Administrator sign-on through the proxy, then an authenticated admin page.
$sso = $rt->ssoUrl(['id' => 1, 'email' => 'owner@example.com', 'name' => 'Owner'], '/admin', true);
[$code, $hdr] = http($sso);
contract_check($code === 303 && preg_match('#^location:\s*/mms/admin\s*$#im', $hdr) === 1, "admin SSO must redirect to /mms/admin (got {$code})");
contract_check(preg_match('#^set-cookie:\s*mms_session=([^;]+)#im', $hdr, $m) === 1, 'SSO must set the session cookie through the proxy');
[$code, , $body] = http("http://127.0.0.1:{$proxyPort}/mms/admin", [CURLOPT_COOKIE => 'mms_session=' . $m[1]]);
contract_check($code === 200 && str_contains($body, 'Dashboard') && str_contains($body, 'href="/mms/admin/bridges"'), "site administrator must reach the store dashboard (got {$code})");

// Cleanup
proc_terminate($srv);
$rt->stop();
usleep(300000);
contract_check(!$rt->pidAlive(), 'stop must end the server process');
exec('rm -rf ' . escapeshellarg($tmp));
echo "mms packages contract: ok ({$count} PHP files; bundled server started, proxied and administered through PHP)\n";
