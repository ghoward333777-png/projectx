<?php
if (!defined('WP_UNINSTALL_PLUGIN')) {
    exit;
}
delete_option('mms_bridge_settings');
