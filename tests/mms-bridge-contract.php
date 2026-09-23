<?php

declare(strict_types=1);

/**
 * Contract checks for the MediaMarketplace bridge plugins (WordPress + Joomla).
 * Run: php tests/mms-bridge-contract.php
 */

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$root = dirname(__DIR__) . '/mediamarketplace/bridges';

// --- Every PHP file must parse ---------------------------------------------------
$files = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root));
$count = 0;
foreach ($files as $file) {
    if ($file->getExtension() !== 'php') {
        continue;
    }
    $count++;
    exec('php -l ' . escapeshellarg($file->getPathname()) . ' 2>&1', $out, $code);
    contract_check($code === 0, 'syntax error in ' . $file->getPathname() . ': ' . implode("\n", $out));
}
contract_check($count >= 8, "expected the bridge plugins to contain at least 8 PHP files, found {$count}");

// --- Both token helpers must produce the fixture the Rust server verifies ------------
// Same fixture as crates/mms-core/src/signer.rs (matches_php_bridge_fixture).
$claims = ['sub' => '42', 'email' => 'a@b.c', 'name' => 'Ada', 'host' => 'wordpress', 'exp' => 1900000000];
$expected = 'eyJzdWIiOiI0MiIsImVtYWlsIjoiYUBiLmMiLCJuYW1lIjoiQWRhIiwiaG9zdCI6IndvcmRwcmVzcyIsImV4cCI6MTkwMDAwMDAwMH0.8pn1jJulBkTg4ho6xxjDns7Akf83M9bYHHoTsF6lmr8';

require_once $root . '/wordpress/mediamarketplace-bridge/includes/token.php';
contract_check(mms_bridge_sign_token($claims, 'test-secret') === $expected, 'WordPress token helper must match the server fixture');
contract_check(mms_bridge_sign_token(['exp' => 1900000000, 'host' => 'wordpress', 'name' => 'Ada', 'email' => 'a@b.c', 'sub' => '42'], 'test-secret') === $expected, 'WordPress helper must canonicalise claim order');

require_once $root . '/joomla/plg_system_mmsbridge/src/Helper/TokenHelper.php';
contract_check(\Joomla\Plugin\System\Mmsbridge\Helper\TokenHelper::sign($claims, 'test-secret') === $expected, 'Joomla token helper must match the server fixture');
contract_check(\Joomla\Plugin\System\Mmsbridge\Helper\TokenHelper::sign($claims, 'other') !== $expected, 'a different secret must change the token');

// --- Manifests and metadata ----------------------------------------------------------
$wpMain = file_get_contents($root . '/wordpress/mediamarketplace-bridge/mediamarketplace-bridge.php');
contract_check(str_contains($wpMain, 'Plugin Name: MediaMarketplace Bridge'), 'WordPress plugin header must be present');
contract_check(!str_contains($wpMain, 'woocommerce'), 'the WordPress bridge must not depend on WooCommerce');

$pkg = file_get_contents($root . '/joomla/pkg_mmsbridge.xml');
contract_check(str_contains($pkg, 'plg_system_mmsbridge.zip') && str_contains($pkg, 'mod_mms_embed.zip'), 'Joomla package must list the plugin and module');
foreach (['plg_system_mmsbridge/mmsbridge.xml', 'mod_mms_embed/mod_mms_embed.xml'] as $manifest) {
    $xml = simplexml_load_file($root . '/joomla/' . $manifest);
    contract_check($xml !== false && (string) $xml['method'] === 'upgrade', "{$manifest} must be a valid upgrade manifest");
    contract_check(isset($xml->namespace) && str_starts_with((string) $xml->namespace, 'Joomla\\'), "{$manifest} must declare a namespace");
}
contract_check(!str_contains(file_get_contents($root . '/joomla/plg_system_mmsbridge/src/Extension/Mmsbridge.php'), 'virtuemart'), 'the Joomla bridge must not depend on VirtueMart');

echo "mms bridge contract: ok ({$count} PHP files, token fixture matches)\n";
