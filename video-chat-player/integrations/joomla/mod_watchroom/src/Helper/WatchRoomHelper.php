<?php
declare(strict_types=1);

namespace WatchRoom\Module\WatchRoom\Site\Helper;

defined('_JEXEC') or die;

use Joomla\CMS\Application\SiteApplication;
use Joomla\CMS\Factory;
use Joomla\CMS\Uri\Uri;
use Joomla\Registry\Registry;

/**
 * Finds or creates the persistent room for a module instance and builds the embed options.
 * The player itself is bundled under modules/mod_watchroom/app and talks to its own files;
 * this helper only calls its PHP directly (no HTTP) to create rooms.
 */
final class WatchRoomHelper
{
    public function getEmbed(Registry $params, SiteApplication $app): array
    {
        $appDir = dirname(__DIR__, 2) . '/app/';
        $base = trim((string) $params->get('base_url', '')) !== '' ? rtrim((string) $params->get('base_url'), '/') . '/' : Uri::root() . 'modules/mod_watchroom/app/';
        $this->ensureLocalConfig($appDir, (int) $params->get('room_days', 30));
        $roomId = trim((string) $params->get('room_id', ''));
        if ($roomId === '') {
            $roomId = $this->persistentRoom($appDir, (string) $params->get('room_key', 'lobby'), (string) $params->get('src', ''));
        }
        $user = $app->getIdentity();
        return [
            'base' => $base,
            'room' => $roomId,
            'name' => $user && !$user->guest ? $user->name : null,
            'compact' => (string) $params->get('compact', '1') === '1',
            'height' => trim((string) $params->get('height', '')),
            'error' => $roomId === '' ? 'MOD_WATCHROOM_ERROR_ROOM' : '',
        ];
    }

    /** Points the bundled app at a writable rooms folder and allows this site to frame it. */
    private function ensureLocalConfig(string $appDir, int $days): void
    {
        $rooms = JPATH_ROOT . '/media/watchroom/rooms';
        $file = $appDir . 'local-config.php';
        $origin = rtrim(Uri::root(), '/');
        $p = parse_url($origin);
        $origin = ($p['scheme'] ?? 'https') . '://' . ($p['host'] ?? '') . (isset($p['port']) ? ':' . $p['port'] : '');
        $config = ['rooms_dir' => $rooms, 'cors_origins' => [$origin], 'room_max_age' => max(1, $days) * 86400];
        $current = is_file($file) ? require $file : null;
        if ($current === $config) {
            return;
        }
        if (!is_dir($rooms)) {
            @mkdir($rooms, 0775, true);
        }
        @file_put_contents(JPATH_ROOT . '/media/watchroom/.htaccess', "Require all denied\n");
        @file_put_contents($file, "<?php\n// Written by the Watch Room Joomla module.\nreturn " . var_export($config, true) . ";\n");
    }

    private function persistentRoom(string $appDir, string $key, string $src): string
    {
        $key = preg_replace('/[^a-z0-9_-]/i', '', $key) ?: 'lobby';
        $lib = $appDir . 'lib/WatchRoomApi.php';
        if (!is_file($lib)) {
            return '';
        }
        require_once $lib;
        $config = require $appDir . 'config.php';
        $store = new \RoomStore($config['rooms_dir']);
        $api = new \WatchRoomApi($store, $config['media_dir'], true, $config);
        $registry = $config['rooms_dir'] . '/_joomla-rooms.json';
        $rooms = is_file($registry) ? (array) json_decode((string) file_get_contents($registry), true) : [];
        if (isset($rooms[$key]['id']) && $store->load((string) $rooms[$key]['id']) !== null) {
            return (string) $rooms[$key]['id'];
        }
        [$status, $body] = $api->handle('room.create', 'POST', ['name' => (string) Factory::getApplication()->get('sitename', 'Host'), 'src' => $src]);
        if ($status !== 200 || empty($body['room']['id'])) {
            return '';
        }
        $rooms[$key] = ['id' => $body['room']['id'], 'hostToken' => $body['hostToken'], 'memberId' => $body['memberId'], 'createdAt' => time()];
        @file_put_contents($registry, json_encode($rooms));
        return (string) $body['room']['id'];
    }
}
