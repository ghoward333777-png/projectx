<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';

/**
 * Chat image — serves an image shared inside a chat, exclusively to the
 * two participants. Anyone else (including signed-out visitors) gets 404.
 *
 * Usage: chatimage.php?chat=<chat id>&m=<message id>
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

$image = null;
if ($viewer !== null) {
    try {
        $image = $engine->chatImage((string) ($_GET['chat'] ?? ''), (string) ($_GET['m'] ?? ''), $viewer);
    } catch (InvalidArgumentException) {
        $image = null;
    }
}

if ($image === null) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Not available.';
    exit;
}

header('Content-Type: ' . $image['mime']);
header('X-Content-Type-Options: nosniff');
header('Content-Security-Policy: default-src \'none\'');
header('Cache-Control: private, no-store');
readfile($image['path']);
