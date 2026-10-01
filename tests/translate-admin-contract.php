<?php

declare(strict_types=1);

// Contract for the QueryBook Translate admin downloads and cloud pack store.

require_once __DIR__ . '/../translate/admin/TranslatePackager.php';
require_once __DIR__ . '/../translate/store/PackStore.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

/** @return array<string, string> entry name → bytes */
function unzip_all(string $bytes): array
{
    $tmp = tempnam(sys_get_temp_dir(), 'qbtzip');
    file_put_contents($tmp, $bytes);
    $zip = new ZipArchive();
    contract_check($zip->open($tmp) === true, 'download must be a valid ZIP');
    $out = [];
    for ($i = 0; $i < $zip->numFiles; $i++) {
        $name = (string) $zip->getNameIndex($i);
        $out[$name] = (string) $zip->getFromIndex($i);
    }
    $zip->close();
    unlink($tmp);
    return $out;
}

$root = dirname(__DIR__) . '/translate';
$packager = new TranslatePackager($root);

// Every web-app file the editions ship exists, and the engine + registry + packs are included.
$web = $packager->webFiles();
foreach (['index.html', 'src/app.js', 'src/core/engine.js', 'src/platform/native-bridge.js', 'data/languages.json', 'packs/catalog.json', 'packs/en/base.json', 'sw.js'] as $must) {
    contract_check(in_array($must, $web, true), "web edition ships {$must}");
}
foreach ($web as $f) {
    contract_check(is_file("{$root}/{$f}"), "listed web file exists: {$f}");
}
contract_check(!in_array('sw.js', $packager->webFiles(false), true), 'native editions do not ship the service worker');

// Store connection presets: https only, cloud enhancement always starts opted out.
$cfg = $packager->config('android', ['storeUrl' => 'https://store.example.com/translate/store/index.php', 'storeKey' => 'k1', 'storeConnected' => true]);
contract_check($cfg['storeUrl'] === 'https://store.example.com/translate/store/index.php/', 'store URL is normalized with a trailing slash');
contract_check($cfg['storeConnected'] === true && $cfg['storeKey'] === 'k1', 'store key and connection are carried');
contract_check($cfg['cloudOptIn'] === false, 'cloud enhancement is never pre-enabled');
contract_check(!isset($packager->config('ios')['storeUrl']), 'no store unless the admin asks for one');
$rejected = false;
try {
    $packager->config('android', ['storeUrl' => 'http://store.example.com/']);
} catch (InvalidArgumentException) {
    $rejected = true;
}
contract_check($rejected, 'plain-http store URLs are rejected');

// Android project: Gradle project + Java shell + web app in assets + baked config.
$android = unzip_all($packager->export('android', ['storeUrl' => 'https://s.example.com/store/', 'storeConnected' => true]));
foreach (['settings.gradle', 'app/build.gradle', 'app/src/main/AndroidManifest.xml', 'app/src/main/java/com/querybook/translate/MainActivity.java', 'app/src/main/assets/www/index.html', 'app/src/main/assets/www/packs/ja/base.json', 'app/src/main/res/mipmap-xxxhdpi/ic_launcher.png', 'BUILD-ANDROID.txt'] as $f) {
    contract_check(isset($android["QueryBookTranslate-android/{$f}"]), "android project contains {$f}");
}
$acfg = json_decode($android['QueryBookTranslate-android/app/src/main/assets/www/config.json'], true);
contract_check($acfg['edition'] === 'android' && $acfg['storeUrl'] === 'https://s.example.com/store/', 'android config.json carries the store');
contract_check(!array_filter(array_keys($android), fn ($n) => str_contains($n, '/build/') || str_contains($n, 'local.properties')), 'android export excludes build outputs and local SDK paths');
contract_check(str_contains($android['QueryBookTranslate-android/app/src/main/AndroidManifest.xml'], 'RECORD_AUDIO'), 'android shell asks for the microphone');

// iOS/iPadOS project: universal target, Swift shell, web app, icon, baked config.
$ios = unzip_all($packager->export('ios'));
foreach (['QueryBookTranslate.xcodeproj/project.pbxproj', 'QueryBookTranslate/App.swift', 'QueryBookTranslate/NativeBridge.swift', 'QueryBookTranslate/Assets.xcassets/AppIcon.appiconset/icon-1024.png', 'QueryBookTranslate/www/index.html', 'QueryBookTranslate/www/config.json', 'project.yml', 'BUILD-IOS.txt'] as $f) {
    contract_check(isset($ios["QueryBookTranslate-ios/{$f}"]), "ios project contains {$f}");
}
$pbx = $ios['QueryBookTranslate-ios/QueryBookTranslate.xcodeproj/project.pbxproj'];
contract_check(str_contains($pbx, 'TARGETED_DEVICE_FAMILY = "1,2";'), 'one universal app for iPhone and iPad');
contract_check(str_contains($pbx, 'NSSpeechRecognitionUsageDescription') && str_contains($pbx, 'NSMicrophoneUsageDescription'), 'iOS privacy strings present');
contract_check(substr_count($pbx, '{') === substr_count($pbx, '}'), 'pbxproj braces balance');

// Web edition.
$pwa = unzip_all($packager->export('pwa'));
contract_check(isset($pwa['querybook-translate-web/sw.js'], $pwa['querybook-translate-web/manifest.webmanifest'], $pwa['querybook-translate-web/INSTALL.txt']), 'web edition is installable');

// Prebuilt binaries are listed only from dist/ and only by exact name.
contract_check($packager->prebuiltPath('../admin/admin-config.php') === null, 'prebuilt downloads cannot escape dist/');

// Store: validation, publishing, override of bundled packs, catalog integrity, access key.
$data = sys_get_temp_dir() . '/qbt-store-' . bin2hex(random_bytes(4));
$store = new PackStore($root, $data);
$bundled = $store->catalog();
contract_check(count($bundled) >= 36 && isset($bundled['en/base']), 'store offers the bundled packs');
contract_check($store->validate(['format' => 'qbt-pack/1', 'id' => 'xx/base', 'lang' => 'xx', 'domain' => 'base', 'version' => '1', 'entries' => [['c' => 'a', 'f' => ['b']]]]) !== [], 'unknown languages are rejected');
contract_check($store->publish('{"format":"qbt-pack/1","id":"../x","lang":"en","domain":"base","version":"1","entries":[{"c":"a","f":["b"]}]}') !== [], 'malformed ids are rejected');
$pack = ['format' => 'qbt-pack/1', 'id' => 'sv/base', 'lang' => 'sv', 'domain' => 'base', 'version' => '0.1.0', 'entries' => [['c' => 'hello', 'f' => ['hej']], ['c' => 'thank_you', 'f' => ['tack']]]];
contract_check($store->publish(json_encode($pack)) === [], 'a valid pack publishes');
$cat = $store->catalog();
contract_check(isset($cat['sv/base']) && $cat['sv/base']['origin'] === 'published', 'published pack appears in the catalog');
$body = $store->packBody('sv', 'base');
contract_check($body !== null && hash('sha256', $body) === $cat['sv/base']['sha256'], 'catalog sha256 matches the served pack bytes');
contract_check($store->packBody('..', 'base') === null, 'pack paths cannot traverse');
$json = json_decode($store->catalogJson(), true);
contract_check(($json['format'] ?? '') === 'qbt-catalog/1' && !isset($json['packs'][0]['origin']), 'catalog JSON matches the app format');
contract_check($store->unpublish('sv/base') && !isset($store->catalog()['sv/base']), 'unpublish removes the pack');
@rmdir("{$data}/packs/sv");
@rmdir("{$data}/packs");
@rmdir($data);

putenv('QBT_STORE_KEY=s3cret');
contract_check(!PackStore::authorized(null) && !PackStore::authorized('Bearer nope') && PackStore::authorized('Bearer s3cret'), 'a store key is enforced when set');
putenv('QBT_STORE_KEY');
contract_check(PackStore::authorized(null), 'an open store needs no key');

echo "translate admin contract: OK\n";
