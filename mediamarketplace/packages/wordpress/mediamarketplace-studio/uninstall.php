<?php
if (!defined('WP_UNINSTALL_PLUGIN')) {
    exit;
}
// Stop the bundled server. Store data is kept on purpose; delete the data directory by hand to remove it.
require_once __DIR__ . '/includes/MmsRuntime.php';
$dir = (string) get_option('mms_data_dir', '');
if ($dir !== '' && is_file($dir . '/mms-server.pid')) {
    $pid = (int) file_get_contents($dir . '/mms-server.pid');
    if ($pid > 0 && function_exists('posix_kill')) {
        @posix_kill($pid, 15);
    }
}
delete_option('mms_last_error');
delete_option('mms_settings');
