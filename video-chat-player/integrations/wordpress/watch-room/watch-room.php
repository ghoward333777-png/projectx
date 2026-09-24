<?php
/**
 * Plugin Name: Watch Room
 * Plugin URI:  https://github.com/ghoward333777-png/projectx
 * Description: A video player with a chat overlay that floats over the picture and hides itself. Plays MP4 files, YouTube videos and playlists, keeps everyone in a room in sync. Shortcode: [watch_room key="lobby" src="https://youtu.be/…"].
 * Version:     1.0.0
 * Requires at least: 6.0
 * Requires PHP: 8.1
 * Author:      Watch Room
 * License:     MIT
 * Text Domain: watch-room
 */

if (!defined('ABSPATH')) {
    exit;
}

final class Watch_Room_Plugin
{
    const OPTION = 'watch_room_settings';
    const ROOMS_OPTION = 'watch_room_rooms';

    public static function boot(): void
    {
        register_activation_hook(__FILE__, [self::class, 'activate']);
        add_action('init', [self::class, 'register']);
        add_action('admin_menu', [self::class, 'admin_menu']);
        add_action('admin_init', [self::class, 'admin_init']);
        add_shortcode('watch_room', [self::class, 'shortcode']);
    }

    /** Where the bundled player lives on disk and on the web. */
    public static function app_dir(): string { return plugin_dir_path(__FILE__) . 'app/'; }
    public static function app_url(): string
    {
        $settings = self::settings();
        return $settings['base_url'] !== '' ? trailingslashit($settings['base_url']) : plugin_dir_url(__FILE__) . 'app/';
    }

    public static function settings(): array
    {
        $saved = get_option(self::OPTION, []);
        return array_merge(['base_url' => '', 'default_src' => '', 'guests_control' => 1, 'room_days' => 30, 'height' => ''], is_array($saved) ? $saved : []);
    }

    /** Creates the writable rooms folder and points the bundled app at it. */
    public static function activate(): void
    {
        $uploads = wp_upload_dir();
        $rooms = trailingslashit($uploads['basedir']) . 'watch-room/rooms';
        wp_mkdir_p($rooms);
        file_put_contents(trailingslashit($uploads['basedir']) . 'watch-room/.htaccess', "Require all denied\n");
        self::write_local_config($rooms);
    }

    public static function write_local_config(string $rooms = ''): void
    {
        if ($rooms === '') {
            $uploads = wp_upload_dir();
            $rooms = trailingslashit($uploads['basedir']) . 'watch-room/rooms';
        }
        $settings = self::settings();
        $origins = array_values(array_unique(array_filter([self::origin(home_url()), self::origin(site_url())])));
        $config = [
            'rooms_dir' => $rooms,
            'cors_origins' => $origins,
            'room_max_age' => max(1, (int) $settings['room_days']) * 86400,
        ];
        $php = "<?php\n// Written by the Watch Room WordPress plugin; edit settings in WordPress instead.\nreturn " . var_export($config, true) . ";\n";
        @file_put_contents(self::app_dir() . 'local-config.php', $php);
    }

    private static function origin(string $url): string
    {
        $p = wp_parse_url($url);
        if (!$p || empty($p['host'])) {
            return '';
        }
        return ($p['scheme'] ?? 'https') . '://' . $p['host'] . (isset($p['port']) ? ':' . $p['port'] : '');
    }

    public static function register(): void
    {
        wp_register_script('watch-room-embed', self::app_url() . 'assets/embed.js', [], '1.0.0', true);
    }

    /**
     * [watch_room key="lobby" src="…" name="" height="" compact="1" room=""]
     * `key` names a persistent room for this page (created on first view, recreated if it
     * expired); `room` embeds a specific existing room instead.
     */
    public static function shortcode($atts): string
    {
        $a = shortcode_atts(['key' => '', 'room' => '', 'src' => '', 'name' => '', 'height' => '', 'compact' => '1', 'autoplay' => '1'], $atts, 'watch_room');
        $settings = self::settings();
        $room = $a['room'] !== '' ? $a['room'] : self::persistent_room($a['key'] !== '' ? $a['key'] : 'post-' . get_the_ID(), $a['src'] !== '' ? $a['src'] : $settings['default_src']);
        if ($room === '') {
            return '<p class="watch-room-error">Watch Room could not create a room. Check that the uploads folder is writable.</p>';
        }
        $id = 'watch-room-' . wp_unique_id();
        $name = $a['name'] !== '' ? $a['name'] : (is_user_logged_in() ? wp_get_current_user()->display_name : '');
        $height = $a['height'] !== '' ? $a['height'] : $settings['height'];
        wp_enqueue_script('watch-room-embed');
        $opts = [
            'base' => self::app_url(),
            'room' => $room,
            'name' => $name !== '' ? $name : null,
            'compact' => $a['compact'] === '1',
            'autoplay' => $a['autoplay'] === '1',
        ];
        if ($height !== '') {
            $opts['aspect'] = 'auto';
        }
        $js = 'document.addEventListener("DOMContentLoaded",function(){var el=document.getElementById(' . wp_json_encode($id) . ');if(el&&window.WatchRoom){var h=window.WatchRoom.embed(el,' . wp_json_encode($opts) . ');' . ($height !== '' ? 'h.iframe.style.height=' . wp_json_encode($height) . ';' : '') . 'el.watchRoom=h;}});';
        wp_add_inline_script('watch-room-embed', $js);
        return '<div class="watch-room" id="' . esc_attr($id) . '" data-room="' . esc_attr($room) . '"></div>';
    }

    /** One room per key, created through the bundled app's own PHP (no HTTP), kept in an option. */
    public static function persistent_room(string $key, string $src): string
    {
        $key = sanitize_key($key);
        $rooms = get_option(self::ROOMS_OPTION, []);
        if (!is_array($rooms)) {
            $rooms = [];
        }
        $api = self::api();
        if ($api === null) {
            return '';
        }
        if (isset($rooms[$key]) && $api->rooms()->load($rooms[$key]['id']) !== null) {
            return $rooms[$key]['id'];
        }
        [$status, $body] = $api->handle('room.create', 'POST', ['name' => get_bloginfo('name') ?: 'Host', 'src' => $src]);
        if ($status !== 200 || empty($body['room']['id'])) {
            return '';
        }
        $rooms[$key] = ['id' => $body['room']['id'], 'hostToken' => $body['hostToken'], 'memberId' => $body['memberId'], 'createdAt' => time()];
        update_option(self::ROOMS_OPTION, $rooms, false);
        return $body['room']['id'];
    }

    private static function api(): ?WatchRoomApi
    {
        $lib = self::app_dir() . 'lib/WatchRoomApi.php';
        if (!is_file($lib)) {
            return null;
        }
        require_once $lib;
        $config = require self::app_dir() . 'config.php';
        try {
            return new WatchRoomApi(new RoomStore($config['rooms_dir']), $config['media_dir'], true, $config);
        } catch (Throwable $e) {
            return null;
        }
    }

    // ---- settings page ----

    public static function admin_menu(): void
    {
        add_options_page('Watch Room', 'Watch Room', 'manage_options', 'watch-room', [self::class, 'settings_page']);
    }

    public static function admin_init(): void
    {
        register_setting('watch_room', self::OPTION, ['sanitize_callback' => [self::class, 'sanitize']]);
    }

    public static function sanitize($input): array
    {
        $out = [
            'base_url' => isset($input['base_url']) ? esc_url_raw(trim((string) $input['base_url'])) : '',
            'default_src' => isset($input['default_src']) ? esc_url_raw(trim((string) $input['default_src'])) : '',
            'guests_control' => empty($input['guests_control']) ? 0 : 1,
            'room_days' => max(1, min(365, (int) ($input['room_days'] ?? 30))),
            'height' => isset($input['height']) ? sanitize_text_field((string) $input['height']) : '',
        ];
        self::write_local_config();
        return $out;
    }

    public static function settings_page(): void
    {
        if (!current_user_can('manage_options')) {
            return;
        }
        $s = self::settings();
        $api = self::api();
        $health = $api ? $api->health() : ['ok' => false, 'checks' => [['name' => 'app', 'ok' => false, 'detail' => 'bundled player not found']]];
        ?>
        <div class="wrap">
            <h1>Watch Room</h1>
            <p>Put <code>[watch_room key="lobby" src="https://youtu.be/…"]</code> in any page or post. Each <code>key</code> is one persistent room; visitors who open the page watch and chat together. Player: <a href="<?php echo esc_url(self::app_url() . 'index.php'); ?>" target="_blank" rel="noopener"><?php echo esc_html(self::app_url()); ?></a> · <a href="<?php echo esc_url(self::app_url() . 'api-docs.php'); ?>" target="_blank" rel="noopener">API reference</a></p>
            <form method="post" action="options.php">
                <?php settings_fields('watch_room'); ?>
                <table class="form-table" role="presentation">
                    <tr><th scope="row"><label for="wr-src">Default video</label></th><td><input id="wr-src" name="<?php echo esc_attr(self::OPTION); ?>[default_src]" type="url" class="regular-text" value="<?php echo esc_attr($s['default_src']); ?>" placeholder="https://youtu.be/… or https://…/film.mp4"><p class="description">First item for new rooms when the shortcode gives no <code>src</code>.</p></td></tr>
                    <tr><th scope="row"><label for="wr-days">Keep idle rooms for</label></th><td><input id="wr-days" name="<?php echo esc_attr(self::OPTION); ?>[room_days]" type="number" min="1" max="365" value="<?php echo esc_attr((string) $s['room_days']); ?>"> days</td></tr>
                    <tr><th scope="row"><label for="wr-height">Player height</label></th><td><input id="wr-height" name="<?php echo esc_attr(self::OPTION); ?>[height]" type="text" value="<?php echo esc_attr($s['height']); ?>" placeholder="empty = 16:9"><p class="description">CSS height such as <code>480px</code>; leave empty for a 16:9 box.</p></td></tr>
                    <tr><th scope="row"><label for="wr-base">Player URL (advanced)</label></th><td><input id="wr-base" name="<?php echo esc_attr(self::OPTION); ?>[base_url]" type="url" class="regular-text" value="<?php echo esc_attr($s['base_url']); ?>" placeholder="leave empty to use the bundled player"><p class="description">Only if you host the player elsewhere. That deployment must list this site in <code>WATCHROOM_CORS_ORIGINS</code>.</p></td></tr>
                </table>
                <?php submit_button(); ?>
            </form>
            <h2>Health</h2>
            <table class="widefat striped" style="max-width:640px"><tbody>
            <?php foreach ($health['checks'] as $c): ?>
                <tr><td><?php echo $c['ok'] ? '✅' : '❌'; ?></td><td><?php echo esc_html($c['name']); ?></td><td><?php echo esc_html((string) $c['detail']); ?></td></tr>
            <?php endforeach; ?>
            </tbody></table>
        </div>
        <?php
    }
}

Watch_Room_Plugin::boot();
