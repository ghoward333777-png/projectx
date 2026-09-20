<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';

/**
 * Photo — a member's own uploaded pictures, served only to their owner.
 * Other people see pictures exclusively through avatar.php, which
 * enforces the platform image mode and per-chat reveal choices.
 *
 * Usage (signed-in member): photo.php?slot=public | private
 * Gallery photos: photo.php?gallery=<photoId> — served to the photo's
 * owner, or to premium members (the Premium Members Only gallery).
 * Another member's private picture: photo.php?private=<userId> — sharp
 * only for the owner, premium members, and chat partners the owner
 * invited (their private picture chosen for that chat); everyone else
 * receives a fuzzed rendition with no detail to recover.
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

$privateOwner = (string) ($_GET['private'] ?? '');
if ($privateOwner !== '') {
    $view = $viewer !== null ? $engine->privatePhotoView($viewer, $privateOwner) : null;
    if ($view === null) {
        http_response_code(404);
        header('Content-Type: text/plain; charset=utf-8');
        echo 'No picture in this slot.';
        exit;
    }
    header('Content-Type: ' . $view['mime']);
    header('X-Content-Type-Options: nosniff');
    header('Content-Security-Policy: default-src \'none\'');
    header('Cache-Control: private, no-store');
    echo $view['bytes'];
    exit;
}

$galleryId = (string) ($_GET['gallery'] ?? '');
if ($galleryId !== '') {
    $photo = $viewer !== null ? $engine->galleryPhoto($viewer, $galleryId) : null;
} else {
    $slot = (string) ($_GET['slot'] ?? 'public');
    $photo = ($viewer !== null && in_array($slot, SlowDatingEngine::PHOTO_SLOTS, true))
        ? $engine->memberPhoto($viewer, $slot)
        : null;
}

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
