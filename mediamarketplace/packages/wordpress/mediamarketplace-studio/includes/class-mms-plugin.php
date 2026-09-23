<?php

if (!defined('ABSPATH')) {
    exit;
}

/**
 * Runs the bundled MediaMarketplace server inside this WordPress site.
 *
 *  - https://site/mms/...  is proxied to the server (rewrite rule + template_redirect)
 *  - "MediaMarketplace" admin menu signs the WordPress administrator into the server admin
 *  - shortcodes place the store in pages; a watchdog keeps the server running
 */
final class MMS_Plugin
{
    public const OPTION = 'mms_settings';
    public const QUERY_VAR = 'mms_route';
    public const CRON_HOOK = 'mms_watchdog';
    public const MOUNT = 'mms';

    private static ?self $instance = null;
    private ?MmsRuntime $runtime = null;
    private ?string $problem = null;
    private bool $loaderPrinted = false;

    public static function instance(): self
    {
        return self::$instance ??= new self();
    }

    private function __construct()
    {
        add_action('init', [$this, 'registerRewrite']);
        add_filter('query_vars', static fn(array $vars): array => array_merge($vars, [self::QUERY_VAR]));
        add_action('parse_request', [$this, 'maybeProxy'], 1);
        add_action('admin_menu', [$this, 'adminMenu']);
        add_action('admin_init', [$this, 'watchdog']);
        add_action('admin_notices', [$this, 'notices']);
        add_action(self::CRON_HOOK, [$this, 'watchdog']);
        add_shortcode('mms_showcase', [$this, 'showcaseShortcode']);
        add_shortcode('mms_embed', [$this, 'embedShortcode']);
        add_shortcode('mms_signin', [$this, 'signinShortcode']);
        add_action('wp_footer', [$this, 'printLoader']);
        add_filter('plugin_action_links_' . plugin_basename(MMS_FILE), [$this, 'actionLinks']);
    }

    // ----- runtime -------------------------------------------------------------------

    public function runtime(): MmsRuntime
    {
        if ($this->runtime === null) {
            $site = home_url('/');
            $origin = rtrim((string) preg_replace('#^(https?://[^/]+).*$#', '$1', $site), '/');
            $this->runtime = new MmsRuntime([
                'data_dir'   => self::dataDir(),
                'bin'        => MMS_DIR . '/bin/mms-server',
                'public_url' => rtrim($site, '/') . '/' . self::MOUNT,
                'origin'     => $origin,
                'host'       => 'wordpress',
                'site_name'  => (string) get_bloginfo('name'),
            ]);
        }
        return $this->runtime;
    }

    /** Outside the web root when possible; otherwise a protected folder under uploads. */
    public static function dataDir(): string
    {
        $saved = (string) get_option('mms_data_dir', '');
        if ($saved !== '') {
            return $saved;
        }
        $outside = dirname(ABSPATH) . '/mms-data';
        $dir = (is_writable(dirname(ABSPATH)) || is_dir($outside)) ? $outside : (wp_upload_dir()['basedir'] . '/mms-data');
        update_option('mms_data_dir', $dir, false);
        return $dir;
    }

    public static function activate(): void
    {
        $self = self::instance();
        $self->registerRewrite();
        flush_rewrite_rules();
        if (!wp_next_scheduled(self::CRON_HOOK)) {
            wp_schedule_event(time() + 300, 'hourly', self::CRON_HOOK);
        }
        try {
            $self->runtime()->ensureInstalled();
            $self->runtime()->start();
        } catch (Throwable $e) {
            update_option('mms_last_error', $e->getMessage(), false);
        }
    }

    public static function deactivate(): void
    {
        wp_clear_scheduled_hook(self::CRON_HOOK);
        try {
            self::instance()->runtime()->stop();
        } catch (Throwable $e) {
            // nothing to stop
        }
        flush_rewrite_rules();
    }

    /** Keeps the server alive; cheap when it is already answering. */
    public function watchdog(): void
    {
        if ($this->problem !== null) {
            return;
        }
        try {
            $rt = $this->runtime();
            if ($p = $rt->platformProblem()) {
                $this->problem = $p;
                return;
            }
            if (!$rt->ensureRunning()) {
                update_option('mms_last_error', 'The server did not start. Log: ' . $rt->logTail(5), false);
            } else {
                delete_option('mms_last_error');
            }
        } catch (Throwable $e) {
            update_option('mms_last_error', $e->getMessage(), false);
        }
    }

    // ----- routing -------------------------------------------------------------------

    public function registerRewrite(): void
    {
        add_rewrite_rule('^' . self::MOUNT . '(/.*)?$', 'index.php?' . self::QUERY_VAR . '=1', 'top');
    }

    /** @param WP $wp */
    public function maybeProxy($wp): void
    {
        $uri = (string) ($_SERVER['REQUEST_URI'] ?? '');
        $path = (string) parse_url($uri, PHP_URL_PATH);
        $home = rtrim((string) parse_url(home_url('/'), PHP_URL_PATH), '/');
        $mount = $home . '/' . self::MOUNT;
        if (!(isset($wp->query_vars[self::QUERY_VAR]) || $path === $mount || str_starts_with($path, $mount . '/'))) {
            return;
        }
        // Strip a sub-directory install prefix so the server sees /mms/...
        $forward = $home !== '' && str_starts_with($uri, $home) ? substr($uri, strlen($home)) : $uri;
        $this->runtime()->proxy($forward);
        exit;
    }

    // ----- admin ---------------------------------------------------------------------

    public function adminMenu(): void
    {
        add_menu_page('MediaMarketplace', 'MediaMarketplace', 'manage_options', 'mms-open', [$this, 'openAdmin'], 'dashicons-store', 58);
        add_submenu_page('mms-open', 'Open store admin', 'Open store admin', 'manage_options', 'mms-open', [$this, 'openAdmin']);
        add_submenu_page('mms-open', 'Status', 'Status', 'manage_options', 'mms-status', [$this, 'statusPage']);
    }

    /** Signs the WordPress administrator into the bundled server admin. */
    public function openAdmin(): void
    {
        $this->watchdog();
        $u = wp_get_current_user();
        $url = $this->runtime()->ssoUrl(['id' => $u->ID, 'email' => $u->user_email, 'name' => $u->display_name], '/admin', current_user_can('manage_options'));
        echo '<div class="wrap"><h1>MediaMarketplace</h1><p>Opening the store admin…</p><p><a class="button button-primary" href="' . esc_url($url) . '">Open store admin</a></p>'
            . '<script>window.location.href=' . wp_json_encode($url) . ';</script></div>';
    }

    public function statusPage(): void
    {
        $rt = $this->runtime();
        if (isset($_POST['mms_action']) && check_admin_referer('mms_status')) {
            try {
                if ($_POST['mms_action'] === 'restart') {
                    $rt->ensureInstalled();
                    $rt->restart();
                } elseif ($_POST['mms_action'] === 'stop') {
                    $rt->stop();
                }
            } catch (Throwable $e) {
                update_option('mms_last_error', $e->getMessage(), false);
            }
        }
        $problem = $rt->platformProblem();
        $ping = $problem ? null : $rt->ping();
        ?>
        <div class="wrap">
            <h1><?php esc_html_e('MediaMarketplace status', 'mediamarketplace-studio'); ?></h1>
            <table class="widefat striped" style="max-width:900px">
                <tr><th>Server</th><td><?php echo $ping ? '<span style="color:#00a32a">running</span>, version ' . esc_html((string) $ping['version']) : '<span style="color:#b32d2e">not running</span>'; ?></td></tr>
                <tr><th>Store address</th><td><code><?php echo esc_html($rt->publicUrl()); ?></code></td></tr>
                <tr><th>Local port</th><td><code>127.0.0.1:<?php echo (int) $rt->port(); ?></code></td></tr>
                <tr><th>Data directory</th><td><code><?php echo esc_html($rt->dataDir()); ?></code></td></tr>
                <tr><th>Server binary</th><td><code><?php echo esc_html($rt->binPath()); ?></code></td></tr>
                <tr><th>PHP upload limit</th><td><?php echo (int) MmsRuntime::phpUploadLimitMb(); ?> MB per file (upload_max_filesize / post_max_size in php.ini)</td></tr>
                <?php if ($problem): ?><tr><th>Problem</th><td style="color:#b32d2e"><?php echo esc_html($problem); ?></td></tr><?php endif; ?>
                <?php if ($err = get_option('mms_last_error')): ?><tr><th>Last error</th><td style="color:#b32d2e"><?php echo esc_html((string) $err); ?></td></tr><?php endif; ?>
            </table>
            <form method="post" style="margin-top:12px">
                <?php wp_nonce_field('mms_status'); ?>
                <button class="button button-primary" name="mms_action" value="restart">Start / restart server</button>
                <button class="button" name="mms_action" value="stop">Stop server</button>
            </form>
            <h2>Recent log</h2>
            <pre style="background:#fff;border:1px solid #c3c4c7;padding:12px;max-width:900px;overflow:auto"><?php echo esc_html($rt->logTail(40)); ?></pre>
            <h2>Shortcodes</h2>
            <ul>
                <li><code>[mms_showcase view="grid" category=""]</code> — product showcase</li>
                <li><code>[mms_embed kind="widget" id="…"]</code> — widget, player, cart, sitepass or page</li>
                <li><code>[mms_signin label="My media"]</code> — one-click sign-in for logged-in members</li>
            </ul>
        </div>
        <?php
    }

    public function notices(): void
    {
        if (!current_user_can('manage_options')) {
            return;
        }
        $p = $this->problem ?? $this->runtime()->platformProblem();
        if ($p !== null) {
            printf('<div class="notice notice-error"><p><b>MediaMarketplace:</b> %s</p></div>', esc_html($p));
        } elseif ($err = get_option('mms_last_error')) {
            printf('<div class="notice notice-warning"><p><b>MediaMarketplace:</b> %s <a href="%s">%s</a></p></div>', esc_html((string) $err), esc_url(admin_url('admin.php?page=mms-status')), esc_html__('Open status', 'mediamarketplace-studio'));
        }
    }

    /** @param string[] $links */
    public function actionLinks(array $links): array
    {
        array_unshift($links, '<a href="' . esc_url(admin_url('admin.php?page=mms-status')) . '">Status</a>');
        return $links;
    }

    // ----- front end -----------------------------------------------------------------

    /** @param array<string,string>|string $atts */
    public function showcaseShortcode($atts): string
    {
        $a = shortcode_atts(['view' => 'grid', 'category' => ''], is_array($atts) ? $atts : [], 'mms_showcase');
        return $this->markup('showcase', ['view' => $a['view'], 'category' => $a['category']]);
    }

    /** @param array<string,string>|string $atts */
    public function embedShortcode($atts): string
    {
        $a = shortcode_atts(['kind' => 'showcase', 'id' => '', 'view' => ''], is_array($atts) ? $atts : [], 'mms_embed');
        return $this->markup((string) $a['kind'], ['id' => $a['id'], 'view' => $a['view']]);
    }

    /** @param array<string,string> $params */
    private function markup(string $kind, array $params): string
    {
        $this->loaderPrinted = false;
        return $this->runtime()->embed($kind, $params);
    }

    /** @param array<string,string>|string $atts */
    public function signinShortcode($atts): string
    {
        $a = shortcode_atts(['label' => __('My media', 'mediamarketplace-studio'), 'return' => '/account', 'class' => 'mms-signin'], is_array($atts) ? $atts : [], 'mms_signin');
        if (!is_user_logged_in()) {
            return '';
        }
        $u = wp_get_current_user();
        $url = $this->runtime()->ssoUrl(['id' => $u->ID, 'email' => $u->user_email, 'name' => $u->display_name], (string) $a['return']);
        return '<a class="' . esc_attr($a['class']) . '" href="' . esc_url($url) . '" rel="nofollow">' . esc_html($a['label']) . '</a>';
    }

    public function printLoader(): void
    {
        if ($this->loaderPrinted) {
            return;
        }
        $this->loaderPrinted = true;
        echo $this->runtime()->loaderTag() . "\n";
    }
}
