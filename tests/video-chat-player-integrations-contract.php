<?php
declare(strict_types=1);

// Contract test for the WordPress plugin and Joomla module packaging: the zips contain the
// bundled player, the plugin's shortcode renders an embed against WordPress function stubs,
// persistent rooms are reused, and local-config overrides take effect in the bundled app.

require_once __DIR__ . '/../video-chat-player/lib/IntegrationBuilder.php';

$failures = 0;
$checks = 0;
$assert = static function (bool $condition, string $label) use (&$failures, &$checks): void {
    $checks++;
    if (!$condition) {
        $failures++;
        fwrite(STDERR, "FAIL  {$label}\n");
    }
};
$appDir = realpath(__DIR__ . '/../video-chat-player');
$tmp = sys_get_temp_dir() . '/watchroom-int-' . getmypid();
mkdir($tmp, 0775, true);

// --- packages ---
$wp = IntegrationBuilder::wordpressFiles($appDir);
$jm = IntegrationBuilder::joomlaFiles($appDir);
$assert(isset($wp['watch-room/watch-room.php'], $wp['watch-room/app/index.php'], $wp['watch-room/app/api.php'], $wp['watch-room/app/assets/embed.js'], $wp['watch-room/app/lib/WatchRoomApi.php'], $wp['watch-room/app/media/sample.mp4']), 'WordPress package bundles plugin + player');
$assert(isset($jm['mod_watchroom.xml'], $jm['services/provider.php'], $jm['src/Helper/WatchRoomHelper.php'], $jm['tmpl/default.php'], $jm['app/index.php'], $jm['app/assets/embed.js']), 'Joomla package bundles manifest, services, helper, template + player');
$assert(!array_filter(array_keys($wp), static fn ($k) => str_contains($k, 'local-config') || str_contains($k, '/rooms/') || str_contains($k, '/bin/') || str_contains($k, 'test-')), 'no local config, rooms, bin scripts or test media in the packages');
if (class_exists(ZipArchive::class)) {
    $built = IntegrationBuilder::buildAll($appDir, $tmp . '/dist');
    $assert(count($built) === 2 && min($built) > 20, 'both zips build');
    $zip = new ZipArchive();
    $zip->open($tmp . '/dist/mod_watchroom-joomla.zip');
    $xml = (string) $zip->getFromName('mod_watchroom.xml');
    $zip->close();
    $assert(str_contains($xml, '<folder>app</folder>') && str_contains($xml, 'WatchRoom\Module\WatchRoom'), 'Joomla manifest ships the app folder and the namespace');
}

// --- WordPress plugin under stubs ---
$GLOBALS['wr_options'] = [];
$GLOBALS['wr_scripts'] = [];
function add_action(...$a): void {}
function add_shortcode(...$a): void {}
function register_activation_hook(...$a): void {}
function shortcode_atts(array $pairs, $atts, $shortcode = ''): array { return array_merge($pairs, is_array($atts) ? $atts : []); }
function get_option(string $k, $d = false) { return $GLOBALS['wr_options'][$k] ?? $d; }
function update_option(string $k, $v, $autoload = null): bool { $GLOBALS['wr_options'][$k] = $v; return true; }
function plugin_dir_path(string $f): string { return $GLOBALS['wr_plugin_dir']; }
function plugin_dir_url(string $f): string { return 'https://blog.example/wp-content/plugins/watch-room/'; }
function trailingslashit(string $s): string { return rtrim($s, '/') . '/'; }
function wp_upload_dir(): array { return ['basedir' => $GLOBALS['wr_uploads']]; }
function wp_mkdir_p(string $d): bool { return is_dir($d) || mkdir($d, 0775, true); }
function home_url(): string { return 'https://blog.example'; }
function site_url(): string { return 'https://blog.example/wp'; }
function wp_parse_url(string $u) { return parse_url($u); }
function wp_register_script(...$a): void {}
function wp_enqueue_script(string $h): void { $GLOBALS['wr_scripts'][] = $h; }
function wp_add_inline_script(string $h, string $js): void { $GLOBALS['wr_inline'] = $js; }
function wp_unique_id(): string { return (string) (++$GLOBALS['wr_uid']); }
function wp_json_encode($v): string { return json_encode($v); }
function esc_attr(string $s): string { return htmlspecialchars($s, ENT_QUOTES); }
function esc_url_raw(string $s): string { return $s; }
function sanitize_key(string $s): string { return preg_replace('/[^a-z0-9_-]/', '', strtolower($s)); }
function sanitize_text_field(string $s): string { return trim($s); }
function is_user_logged_in(): bool { return false; }
function get_the_ID(): int { return 7; }
function get_bloginfo(string $k): string { return 'Example Blog'; }
$GLOBALS['wr_uid'] = 0;
define('ABSPATH', $tmp . '/');

// A fake plugin folder with the real app copied in (so config.php + lib load from there).
$pluginDir = $tmp . '/plugin/';
mkdir($pluginDir . 'app', 0775, true);
foreach (IntegrationBuilder::appFiles($appDir) as $rel => $src) {
    if (str_starts_with($rel, 'media/')) { continue; }
    @mkdir(dirname($pluginDir . 'app/' . $rel), 0775, true);
    copy($src, $pluginDir . 'app/' . $rel);
}
$GLOBALS['wr_plugin_dir'] = $pluginDir;
$GLOBALS['wr_uploads'] = $tmp . '/uploads';
require $appDir . '/integrations/wordpress/watch-room/watch-room.php';

Watch_Room_Plugin::activate();
$local = require $pluginDir . 'app/local-config.php';
$assert($local['rooms_dir'] === $tmp . '/uploads/watch-room/rooms' && in_array('https://blog.example', $local['cors_origins'], true) && $local['room_max_age'] === 30 * 86400, 'activation writes local-config with the uploads rooms folder, the site origin and a 30-day lifetime');
$config = require $pluginDir . 'app/config.php';
$assert($config['rooms_dir'] === $local['rooms_dir'] && $config['api_key'] === '', 'bundled config.php picks up local-config overrides and keeps defaults');
$assert(is_file($tmp . '/uploads/watch-room/.htaccess'), 'rooms folder is shielded from the web');

$html = Watch_Room_Plugin::shortcode(['key' => 'lobby', 'src' => 'https://youtu.be/aqz-KE-bpKQ']);
$assert(preg_match('/data-room="([a-z]+-[a-z]+-\d\d)"/', $html, $m) === 1, 'shortcode renders a container with a room id');
$roomId = $m[1] ?? '';
$assert(in_array('watch-room-embed', $GLOBALS['wr_scripts'], true) && str_contains($GLOBALS['wr_inline'], 'WatchRoom.embed') && str_contains($GLOBALS['wr_inline'], '"room":"' . $roomId . '"') && str_contains($GLOBALS['wr_inline'], '"base":"https:\/\/blog.example\/wp-content\/plugins\/watch-room\/app\/"'), 'shortcode enqueues embed.js and initialises the embed with the bundled base');
$assert(is_dir($tmp . '/uploads/watch-room/rooms/' . $roomId) && is_file($tmp . '/uploads/watch-room/rooms/' . $roomId . '/playlist.json'), 'room was created inside the uploads folder');
$playlist = json_decode((string) file_get_contents($tmp . '/uploads/watch-room/rooms/' . $roomId . '/playlist.json'), true);
$assert(($playlist['items'][0]['kind'] ?? '') === 'youtube' && ($playlist['items'][0]['src'] ?? '') === 'aqz-KE-bpKQ', 'the src attribute became the first playlist item');
$html2 = Watch_Room_Plugin::shortcode(['key' => 'lobby']);
$assert(str_contains($html2, 'data-room="' . $roomId . '"'), 'same key → same persistent room');
$html3 = Watch_Room_Plugin::shortcode(['key' => 'other']);
$assert(!str_contains($html3, 'data-room="' . $roomId . '"'), 'different key → different room');
$html4 = Watch_Room_Plugin::shortcode(['room' => 'quiet-otter-41', 'height' => '480px', 'compact' => '0']);
$assert(str_contains($html4, 'data-room="quiet-otter-41"') && str_contains($GLOBALS['wr_inline'], '480px') && str_contains($GLOBALS['wr_inline'], '"compact":false'), 'explicit room, height and compact attributes are honoured');
// Expired room is recreated transparently.
$store = new RoomStore($config['rooms_dir']);
foreach (glob($config['rooms_dir'] . '/' . $roomId . '/*') ?: [] as $f) { unlink($f); }
rmdir($config['rooms_dir'] . '/' . $roomId);
$html5 = Watch_Room_Plugin::shortcode(['key' => 'lobby']);
$assert(preg_match('/data-room="([a-z]+-[a-z]+-\d\d)"/', $html5, $m2) === 1 && $m2[1] !== $roomId, 'an expired keyed room is recreated');

// --- bundled app answers through its own config from the plugin folder ---
require_once $pluginDir . 'app/lib/RestApi.php';
$api = new WatchRoomApi(new RoomStore($config['rooms_dir']), $config['media_dir'], false, $config);
$rest = new RestApi($api, $config);
[$s, $b] = $rest->dispatch('GET', '/v1/health', [], [], []);
$roomsCheck = array_values(array_filter($b['checks'], static fn ($c) => $c['name'] === 'rooms_writable'))[0] ?? ['ok' => false, 'detail' => ''];
$assert($s === 200 && $b['ok'] === true && str_ends_with((string) $roomsCheck['detail'], 'uploads/watch-room/rooms'), 'bundled API health reports the uploads rooms folder');
$assert($rest->cors('https://blog.example') !== [] && $rest->cors('https://other.example') === [], 'CORS allows the site and nobody else');

// Joomla helper: the embed options logic is exercised through its template contract.
$tmpl = file_get_contents($appDir . '/integrations/joomla/mod_watchroom/tmpl/default.php');
$assert(str_contains($tmpl, 'WatchRoom.embed') && str_contains($tmpl, 'assets/embed.js') && str_contains($tmpl, 'addInlineScript'), 'Joomla template loads embed.js through the web asset manager and initialises the embed');
$helper = file_get_contents($appDir . '/integrations/joomla/mod_watchroom/src/Helper/WatchRoomHelper.php');
$assert(str_contains($helper, "media/watchroom/rooms") && str_contains($helper, 'room.create') && str_contains($helper, 'cors_origins'), 'Joomla helper creates persistent rooms and writes local-config');

// cleanup
$rm = static function (string $dir) use (&$rm): void {
    foreach (scandir($dir) ?: [] as $e) {
        if ($e === '.' || $e === '..') { continue; }
        $p = $dir . '/' . $e;
        is_dir($p) ? $rm($p) : @unlink($p);
    }
    @rmdir($dir);
};
$rm($tmp);

if ($failures > 0) {
    fwrite(STDERR, "video-chat-player integrations contract: {$failures} of {$checks} checks failed\n");
    exit(1);
}
echo "video-chat-player integrations contract: {$checks} checks passed\n";
