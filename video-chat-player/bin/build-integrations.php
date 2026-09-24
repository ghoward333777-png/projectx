<?php
declare(strict_types=1);

// Builds dist/watch-room-wordpress.zip and dist/mod_watchroom-joomla.zip with the whole
// player bundled. Run: php video-chat-player/bin/build-integrations.php
require_once dirname(__DIR__) . '/lib/IntegrationBuilder.php';

$appDir = dirname(__DIR__);
$dist = $appDir . '/dist';
foreach (IntegrationBuilder::buildAll($appDir, $dist) as $zip => $count) {
    printf("%s  %d files  %s\n", basename($zip), $count, round(filesize($zip) / 1048576, 2) . ' MB');
}
