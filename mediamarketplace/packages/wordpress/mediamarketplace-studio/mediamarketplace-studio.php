<?php
/**
 * Plugin Name: MediaMarketplace Studio
 * Plugin URI:  https://example.com/mediamarketplace
 * Description: A complete media marketplace (video, audio, images, PDFs, live sessions, passes) that runs inside this WordPress site. Bundles its own server and its own checkout; optionally sells through WooCommerce. No external services.
 * Version:     0.2.0
 * Requires at least: 6.4
 * Requires PHP: 8.1
 * Author:      MediaMarketplace Studio
 * License:     GPL-3.0-or-later
 * Text Domain: mediamarketplace-studio
 */

if (!defined('ABSPATH')) {
    exit;
}

define('MMS_VERSION', '0.2.0');
define('MMS_FILE', __FILE__);
define('MMS_DIR', __DIR__);

if (is_file(__DIR__ . '/includes/MmsRuntime.php')) {
    require_once __DIR__ . '/includes/MmsRuntime.php';
} else {
    require_once dirname(__DIR__, 2) . '/shared/MmsRuntime.php'; // development checkout
}
require_once __DIR__ . '/includes/class-mms-plugin.php';

register_activation_hook(__FILE__, ['MMS_Plugin', 'activate']);
register_deactivation_hook(__FILE__, ['MMS_Plugin', 'deactivate']);

MMS_Plugin::instance();
