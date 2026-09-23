<?php
/**
 * Plugin Name: MediaMarketplace Bridge
 * Plugin URI:  https://example.com/mediamarketplace
 * Description: Embeds your MediaMarketplace Studio store (showcases, widgets, players, cart) in this site and signs visitors in with one click. No WooCommerce required.
 * Version:     0.1.0
 * Requires at least: 6.4
 * Requires PHP: 8.1
 * Author:      MediaMarketplace Studio
 * License:     GPL-3.0-or-later
 * Text Domain: mediamarketplace-bridge
 */

if (!defined('ABSPATH')) {
    exit;
}

define('MMS_BRIDGE_VERSION', '0.1.0');
define('MMS_BRIDGE_FILE', __FILE__);

require_once __DIR__ . '/includes/token.php';
require_once __DIR__ . '/includes/class-mms-bridge.php';

MMS_Bridge::instance();
