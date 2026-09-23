<?php

if (!defined('ABSPATH')) {
    exit;
}

/**
 * Thin bridge: settings page, embed shortcodes and single sign-on links.
 * Everything else (catalogue, cart, checkout, media, protection) lives on the MediaMarketplace server.
 */
final class MMS_Bridge
{
    public const OPTION = 'mms_bridge_settings';
    private const TOKEN_TTL = 300;

    private static ?self $instance = null;
    private bool $loaderPrinted = false;

    public static function instance(): self
    {
        return self::$instance ??= new self();
    }

    private function __construct()
    {
        add_action('admin_menu', [$this, 'adminMenu']);
        add_action('admin_init', [$this, 'registerSettings']);
        add_action('admin_notices', [$this, 'configNotice']);
        add_shortcode('mms_showcase', [$this, 'showcaseShortcode']);
        add_shortcode('mms_embed', [$this, 'embedShortcode']);
        add_shortcode('mms_signin', [$this, 'signinShortcode']);
        add_action('wp_footer', [$this, 'printLoader']);
    }

    /** @return array{server_url:string,site_id:string,secret:string} */
    public function settings(): array
    {
        $saved = get_option(self::OPTION, []);
        return [
            'server_url' => rtrim((string) ($saved['server_url'] ?? ''), '/'),
            'site_id'    => (string) ($saved['site_id'] ?? ''),
            'secret'     => (string) ($saved['secret'] ?? ''),
        ];
    }

    public function configured(): bool
    {
        $s = $this->settings();
        return $s['server_url'] !== '' && $s['site_id'] !== '' && $s['secret'] !== '';
    }

    // ----- admin -----------------------------------------------------------

    public function adminMenu(): void
    {
        add_options_page('MediaMarketplace', 'MediaMarketplace', 'manage_options', 'mms-bridge', [$this, 'settingsPage']);
    }

    public function registerSettings(): void
    {
        register_setting('mms_bridge', self::OPTION, ['sanitize_callback' => [$this, 'sanitize']]);
    }

    /** @param mixed $input */
    public function sanitize($input): array
    {
        $input = is_array($input) ? $input : [];
        $url = esc_url_raw(trim((string) ($input['server_url'] ?? '')));
        $siteId = preg_replace('/[^0-9a-f-]/', '', strtolower((string) ($input['site_id'] ?? '')));
        $secret = preg_replace('/[^0-9a-f]/', '', strtolower((string) ($input['secret'] ?? '')));
        if ($secret === '' && !empty($this->settings()['secret'])) {
            $secret = $this->settings()['secret']; // blank keeps the stored secret
        }
        return ['server_url' => rtrim($url, '/'), 'site_id' => $siteId, 'secret' => $secret];
    }

    public function configNotice(): void
    {
        if ($this->configured() || !current_user_can('manage_options')) {
            return;
        }
        printf('<div class="notice notice-warning"><p>%s <a href="%s">%s</a></p></div>',
            esc_html__('MediaMarketplace Bridge is not connected to a server yet.', 'mediamarketplace-bridge'),
            esc_url(admin_url('options-general.php?page=mms-bridge')),
            esc_html__('Open settings', 'mediamarketplace-bridge'));
    }

    public function settingsPage(): void
    {
        $s = $this->settings();
        ?>
        <div class="wrap">
            <h1><?php esc_html_e('MediaMarketplace Bridge', 'mediamarketplace-bridge'); ?></h1>
            <p><?php esc_html_e('Create this site under Bridges in your MediaMarketplace server admin, then paste the values here.', 'mediamarketplace-bridge'); ?></p>
            <form method="post" action="options.php">
                <?php settings_fields('mms_bridge'); ?>
                <table class="form-table" role="presentation">
                    <tr><th scope="row"><label for="mms_server_url"><?php esc_html_e('Server URL', 'mediamarketplace-bridge'); ?></label></th>
                        <td><input id="mms_server_url" class="regular-text code" name="<?php echo esc_attr(self::OPTION); ?>[server_url]" value="<?php echo esc_attr($s['server_url']); ?>" placeholder="https://media.example.com"></td></tr>
                    <tr><th scope="row"><label for="mms_site_id"><?php esc_html_e('Site ID', 'mediamarketplace-bridge'); ?></label></th>
                        <td><input id="mms_site_id" class="regular-text code" name="<?php echo esc_attr(self::OPTION); ?>[site_id]" value="<?php echo esc_attr($s['site_id']); ?>"></td></tr>
                    <tr><th scope="row"><label for="mms_secret"><?php esc_html_e('Secret', 'mediamarketplace-bridge'); ?></label></th>
                        <td><input id="mms_secret" type="password" class="regular-text code" name="<?php echo esc_attr(self::OPTION); ?>[secret]" value="" placeholder="<?php echo $s['secret'] !== '' ? esc_attr__('saved; leave blank to keep', 'mediamarketplace-bridge') : ''; ?>" autocomplete="off"></td></tr>
                </table>
                <?php submit_button(); ?>
            </form>
            <h2><?php esc_html_e('Shortcodes', 'mediamarketplace-bridge'); ?></h2>
            <ul>
                <li><code>[mms_showcase view="grid" category=""]</code> — <?php esc_html_e('product showcase', 'mediamarketplace-bridge'); ?></li>
                <li><code>[mms_embed kind="widget" id="…"]</code> — <?php esc_html_e('any embed the server offers (widget, player, cart, sitepass)', 'mediamarketplace-bridge'); ?></li>
                <li><code>[mms_signin label="My media" return="/account"]</code> — <?php esc_html_e('single sign-on link for logged-in visitors', 'mediamarketplace-bridge'); ?></li>
            </ul>
        </div>
        <?php
    }

    // ----- front end -------------------------------------------------------

    /** @param array<string,string>|string $atts */
    public function showcaseShortcode($atts): string
    {
        $a = shortcode_atts(['view' => 'grid', 'category' => ''], is_array($atts) ? $atts : [], 'mms_showcase');
        return $this->embed('showcase', ['view' => $a['view'], 'category' => $a['category']]);
    }

    /** @param array<string,string>|string $atts */
    public function embedShortcode($atts): string
    {
        $a = shortcode_atts(['kind' => 'showcase', 'id' => '', 'view' => ''], is_array($atts) ? $atts : [], 'mms_embed');
        return $this->embed((string) $a['kind'], array_filter(['id' => $a['id'], 'view' => $a['view']], 'strlen'));
    }

    /** @param array<string,string> $params */
    public function embed(string $kind, array $params): string
    {
        if (!$this->configured()) {
            return current_user_can('manage_options') ? '<p><em>MediaMarketplace Bridge is not configured.</em></p>' : '';
        }
        $s = $this->settings();
        $attrs = 'data-mms-embed="' . esc_attr($kind) . '" data-mms-site="' . esc_attr($s['site_id']) . '"';
        foreach ($params as $k => $v) {
            $attrs .= ' data-mms-' . esc_attr((string) $k) . '="' . esc_attr((string) $v) . '"';
        }
        $this->loaderPrinted = false;
        return '<div class="mms-embed" ' . $attrs . '></div>';
    }

    /** @param array<string,string>|string $atts */
    public function signinShortcode($atts): string
    {
        $a = shortcode_atts(['label' => __('My media', 'mediamarketplace-bridge'), 'return' => '/account', 'class' => 'mms-signin'], is_array($atts) ? $atts : [], 'mms_signin');
        $url = $this->ssoUrl((string) $a['return']);
        if ($url === null) {
            return '';
        }
        return '<a class="' . esc_attr($a['class']) . '" href="' . esc_url($url) . '" rel="nofollow">' . esc_html($a['label']) . '</a>';
    }

    /** SSO URL for the current user, or null when nobody is logged in or the bridge is unconfigured. */
    public function ssoUrl(string $return = '/account'): ?string
    {
        if (!$this->configured() || !is_user_logged_in()) {
            return null;
        }
        $user = wp_get_current_user();
        $s = $this->settings();
        $token = mms_bridge_sign_token([
            'sub'   => (string) $user->ID,
            'email' => (string) $user->user_email,
            'name'  => (string) $user->display_name,
            'host'  => 'wordpress',
            'exp'   => time() + self::TOKEN_TTL,
        ], $s['secret']);
        return $s['server_url'] . '/sso?' . http_build_query(['site' => $s['site_id'], 'token' => $token, 'return' => $return]);
    }

    public function printLoader(): void
    {
        if ($this->loaderPrinted || !$this->configured()) {
            return;
        }
        $this->loaderPrinted = true;
        echo '<script src="' . esc_url($this->settings()['server_url'] . '/embed.js') . '" defer></script>' . "\n";
    }
}
