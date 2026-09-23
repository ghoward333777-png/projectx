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
contract_check($count >= 16, "expected at least 16 PHP files across the packages, found {$count}");

// --- Token fixture shared with crates/mms-core/src/signer.rs --------------------------
require_once $pk . '/shared/MmsRuntime.php';
$expected = 'eyJzdWIiOiI0MiIsImVtYWlsIjoiYUBiLmMiLCJuYW1lIjoiQWRhIiwiaG9zdCI6IndvcmRwcmVzcyIsImV4cCI6MTkwMDAwMDAwMH0.8pn1jJulBkTg4ho6xxjDns7Akf83M9bYHHoTsF6lmr8';
$claims = ['sub' => '42', 'email' => 'a@b.c', 'name' => 'Ada', 'host' => 'wordpress', 'exp' => 1900000000];
contract_check(MmsRuntime::signToken($claims, 'test-secret') === $expected, 'runtime token must match the server fixture');
contract_check(MmsRuntime::signToken($claims + ['role' => 'admin'], 'test-secret') !== $expected, 'the admin role must be part of the signed payload');

// --- Sell-through request signature shared with crates/mms-core/src/commerce_bridge.rs ---
contract_check(MmsRuntime::signRequest('test-secret', 1900000000, 'post', '/mms/api/v1/commerce/orders', '{"a":1}') === '4f5d56454d11d6ed11ea7777e15c5cfe63cf67b855ff07616b5d86fb129e9e70', 'runtime request signature must match the server fixture');

// --- Manifests; the core stays independent of commerce engines --------------------------
// The store never depends on WooCommerce or VirtueMart. The optional "sell through"
// modules live in their own files (loaded only when the engine is present); every other
// file must stay free of engine calls.
$wpMain = (string) file_get_contents($pk . '/wordpress/mediamarketplace-studio/mediamarketplace-studio.php');
contract_check(str_contains($wpMain, 'Plugin Name: MediaMarketplace Studio'), 'WordPress plugin header must be present');
$optional = 0;
foreach (['wordpress', 'joomla'] as $host) {
    foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator("$pk/$host")) as $file) {
        if ($file->getExtension() !== 'php') {
            continue;
        }
        if (preg_match('#woocommerce|virtuemart|vmcustom#i', $file->getPathname()) === 1) {
            $optional++;
            continue;
        }
        $src = (string) file_get_contents($file->getPathname());
        foreach (['woocommerce_', 'WC()', "class_exists('WooCommerce')", 'WC_Product', 'vmPSPlugin', 'VmConfig', 'VmModel', 'virtuemart_'] as $needle) {
            contract_check(!str_contains($src, $needle), $file->getPathname() . " must not integrate with a commerce engine ({$needle})");
        }
    }
}
contract_check($optional >= 4, "expected the optional WooCommerce and VirtueMart modules, found {$optional} files");
$wpClassSrc = (string) file_get_contents($pk . '/wordpress/mediamarketplace-studio/includes/class-mms-plugin.php');
contract_check(str_contains($wpClassSrc, "class_exists('WooCommerce', false)") && str_contains($wpClassSrc, 'class-mms-woocommerce.php'), 'the WordPress plugin must load the WooCommerce module only when WooCommerce is active');
$wc = (string) file_get_contents($pk . '/wordpress/mediamarketplace-studio/includes/class-mms-woocommerce.php');
foreach (['woocommerce_payment_complete', 'woocommerce_order_status_completed', 'woocommerce_order_status_refunded', 'woocommerce_order_status_cancelled', 'woocommerce_subscription_status_updated', 'woocommerce_product_data_tabs', 'woocommerce_account_menu_items', "'/api/v1/commerce'", "'/orders'", "'/subscriptions'", "'/link'", "'/mode'"] as $needle) {
    contract_check(str_contains($wc, $needle), "the WooCommerce module must use {$needle}");
}
$vmBridge = (string) file_get_contents($pk . '/joomla/plg_system_mediamarketplace/src/Commerce/VirtueMartBridge.php');
foreach (['#__virtuemart_orders', '#__virtuemart_order_items', 'function mapStatus', 'function reportOrder', 'function reconcile', 'function importProducts', "'/api/v1/commerce'"] as $needle) {
    contract_check(str_contains($vmBridge, $needle), "the VirtueMart bridge must contain {$needle}");
}
$vmPlugin = (string) file_get_contents($pk . '/joomla/plg_vmcustom_mediamarketplace/mediamarketplace.php');
contract_check(str_contains($vmPlugin, 'extends vmCustomPlugin') && str_contains($vmPlugin, 'plgVmOnUpdateOrderPayment') && str_contains($vmPlugin, "if (!class_exists('vmCustomPlugin'))"), 'the VirtueMart plugin must be a vmcustom plugin that degrades without VirtueMart');
contract_check(str_contains((string) file_get_contents($pk . '/joomla/plg_system_mediamarketplace/src/Extension/Mediamarketplace.php'), 'public function virtuemart(): ?VirtueMartBridge'), 'the system plugin must expose the optional VirtueMart bridge');
$pkg = simplexml_load_file($pk . '/joomla/pkg_mediamarketplace.xml');
contract_check($pkg !== false && count($pkg->files->file) === 4, 'Joomla package must list the system plugin, component, module and VirtueMart plugin');
foreach (['plg_system_mediamarketplace/mediamarketplace.xml', 'com_mediamarketplace/mediamarketplace.xml', 'mod_mms_embed/mod_mms_embed.xml'] as $manifest) {
    $xml = simplexml_load_file("$pk/joomla/$manifest");
    contract_check($xml !== false && (string) $xml['method'] === 'upgrade' && isset($xml->namespace), "$manifest must be a namespaced upgrade manifest");
}
$vmXml = simplexml_load_file("$pk/joomla/plg_vmcustom_mediamarketplace/mediamarketplace.xml");
contract_check($vmXml !== false && (string) $vmXml['group'] === 'vmcustom' && isset($vmXml->vmconfig), 'the VirtueMart plugin manifest must be a vmcustom plugin with vmconfig params');
contract_check(str_contains((string) file_get_contents("$pk/joomla/com_mediamarketplace/mediamarketplace.xml"), 'view=virtuemart') && is_file("$pk/joomla/com_mediamarketplace/administrator/src/View/Virtuemart/HtmlView.php"), 'the Joomla component must offer the VirtueMart page');
contract_check(str_contains((string) file_get_contents(dirname(__DIR__) . '/mediamarketplace/build/package.sh'), 'plg_vmcustom_mediamarketplace.zip'), 'the package script must ship the VirtueMart plugin');
contract_check(str_contains((string) file_get_contents("$pk/joomla/plg_system_mediamarketplace/mediamarketplace.xml"), '<folder>bin</folder>'), 'the Joomla plugin manifest must ship the bin folder');

// --- Phase 2 placement: Gutenberg blocks and Joomla menu item types ------------------
foreach (['showcase', 'embed', 'signin'] as $block) {
    $json = json_decode((string) file_get_contents("$pk/wordpress/mediamarketplace-studio/blocks/$block/block.json"), true);
    contract_check(is_array($json) && $json['name'] === "mms/$block" && $json['editorScript'] === 'mms-blocks-editor', "block.json for mms/$block must be valid");
}
$wpClass = (string) file_get_contents($pk . '/wordpress/mediamarketplace-studio/includes/class-mms-plugin.php');
foreach (['register_block_type(MMS_DIR . \'/blocks/showcase\'', 'register_block_type(MMS_DIR . \'/blocks/embed\'', 'register_block_type(MMS_DIR . \'/blocks/signin\''] as $needle) {
    contract_check(str_contains($wpClass, $needle), "the WordPress plugin must register the block: $needle");
}
contract_check(str_contains((string) file_get_contents($pk . '/wordpress/mediamarketplace-studio/blocks/editor.js'), "registerBlockType('mms/embed'"), 'the block editor script must register mms/embed');
$comXml = (string) file_get_contents("$pk/joomla/com_mediamarketplace/mediamarketplace.xml");
contract_check(str_contains($comXml, '<files folder="site">'), 'the Joomla component must ship a site part');
foreach (['showcase', 'widget', 'account'] as $view) {
    $meta = simplexml_load_file("$pk/joomla/com_mediamarketplace/site/tmpl/$view/default.xml");
    contract_check($meta !== false && isset($meta->layout['title']), "Joomla menu item type for $view must declare a layout title");
    contract_check(is_file("$pk/joomla/com_mediamarketplace/site/src/View/" . ucfirst($view) . "/HtmlView.php"), "Joomla site view $view must exist");
}

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
// Whatever happens below, never leave the proxy or the store process behind.
register_shutdown_function(static function () use (&$srv, $rt): void {
    if (isset($srv) && is_resource($srv)) {
        proc_terminate($srv);
    }
    $rt->stop();
});
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

// A multipart upload through the PHP proxy must reach the store (PHP parses multipart bodies itself).
$csrfPage = http("http://127.0.0.1:{$proxyPort}/mms/admin/media", [CURLOPT_COOKIE => 'mms_session=' . $m[1]]);
contract_check($csrfPage[0] === 200 && preg_match('/name="_csrf" value="([^"]+)"/', $csrfPage[2], $cm) === 1, 'media page must render for the administrator');
$png = "\x89PNG\r\n\x1a\n" . pack('N', 13) . 'IHDR' . pack('NN', 1, 1) . "\x08\x02\x00\x00\x00" . pack('N', crc32('IHDR' . pack('NN', 1, 1) . "\x08\x02\x00\x00\x00"));
$idat = gzcompress("\x00\xff\x00\x00", 6);
$png .= pack('N', strlen($idat)) . 'IDAT' . $idat . pack('N', crc32('IDAT' . $idat)) . pack('N', 0) . 'IEND' . pack('N', crc32('IEND'));
$pngFile = $tmp . '/pixel.png';
file_put_contents($pngFile, $png);
[$code, $hdr] = http("http://127.0.0.1:{$proxyPort}/mms/admin/media/upload", [
    CURLOPT_COOKIE => 'mms_session=' . $m[1],
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => ['_csrf' => $cm[1], 'private' => '0', 'files[]' => new CURLFile($pngFile, 'image/png', 'pixel.png')],
]);
contract_check($code === 303 && preg_match('#location:\s*/mms/admin/media\?notice=1\+file#i', $hdr) === 1, "multipart upload must be proxied to the store (got {$code}: " . trim(preg_replace('/\s+/', ' ', $hdr)) . ')');

// The sell-through API through the runtime's signed client, against the real binary.
$st = $rt->apiCall('GET', '/api/v1/commerce/status');
contract_check($st['ok'] && ($st['data']['mode'] ?? '') === 'native' && ($st['data']['site']['host'] ?? '') === 'joomla', 'signed status call must reach the store: ' . $st['error']);
$bad = $rt->apiCall('POST', '/api/v1/commerce/orders', ['system' => 'virtuemart', 'external_id' => '1', 'status' => 'paid', 'customer' => ['email' => 'x@example.com'], 'items' => [['slug' => 'nothing', 'unit_cents' => 100]]]);
contract_check($bad['ok'] && !empty($bad['data']['ignored']), 'an order without store products must be ignored, not fail: ' . $bad['error']);
$mode = $rt->apiCall('POST', '/api/v1/commerce/mode', ['mode' => 'virtuemart']);
$st = $rt->apiCall('GET', '/api/v1/commerce/status');
contract_check($mode['ok'] && ($st['data']['mode'] ?? '') === 'virtuemart', 'mode switch must round-trip through the signed client');
$rt->apiCall('POST', '/api/v1/commerce/mode', ['mode' => 'native']);
[$code, , $body] = http("http://127.0.0.1:{$proxyPort}/mms/api/v1/commerce/status");
contract_check($code === 401, "unsigned sell-through calls must be refused (got {$code})");

// Cleanup
proc_terminate($srv);
$rt->stop();
usleep(300000);
contract_check(!$rt->pidAlive(), 'stop must end the server process');
exec('rm -rf ' . escapeshellarg($tmp));
echo "mms packages contract: ok ({$count} PHP files; bundled server started, proxied and administered through PHP)\n";
