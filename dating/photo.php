<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';

/**
 * Photo — a member's own uploaded pictures, served only to their owner.
 * Other people see pictures exclusively through avatar.php, which
 * enforces the platform image mode and per-chat reveal choices.
 *
 * Usage (signed-in member): photo.php?slot=public | private
 */

session_start();

$engine = new SlowDatingEngine();
$viewer = null;
if (isset($_SESSION['sd_member_token'])) {
    $auth = $engine->authenticate((string) $_SESSION['sd_member_token']);
    if ($auth !== null && $auth[1] === 'member') {
        $viewer = $auth[0];
    }
}

$slot = (string) ($_GET['slot'] ?? 'public');
$photo = ($viewer !== null && in_array($slot, SlowDatingEngine::PHOTO_SLOTS, true))
    ? $engine->memberPhoto($viewer, $slot)
    : null;

if ($photo === null) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'No picture in this slot.';
    exit;
}

header('Content-Type: ' . $photo['mime']);
header('X-Content-Type-Options: nosniff');
header('Content-Security-Policy: default-src \'none\'');
header('Cache-Control: private, no-store');
readfile($photo['path']);
