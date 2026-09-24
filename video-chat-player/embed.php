<?php
declare(strict_types=1);

/**
 * The embed endpoint: one URL that another site or project can put in an <iframe>.
 *
 *   embed.php?room=quiet-otter-41&name=Sam            join an existing room, compact layout
 *   embed.php?src=https://youtu.be/…&name=Sam         start a new room with that first item
 *   embed.php?room=…&chat=0&autoplay=0&idle=5000      options
 *   embed.php?format=json                              machine-readable descriptor (snippet, endpoints)
 *
 * Which pages may frame it is set by WATCHROOM_CORS_ORIGINS ("*" allows any page); the
 * host page controls the player through assets/embed.js.
 */
require_once __DIR__ . '/lib/RoomStore.php';
require_once __DIR__ . '/lib/Embed.php';

$config = require __DIR__ . '/config.php';
$scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
$base = $scheme . '://' . ($_SERVER['HTTP_HOST'] ?? 'localhost') . rtrim(dirname((string) ($_SERVER['SCRIPT_NAME'] ?? '/embed.php')), '/') . '/';
$room = isset($_GET['room']) && RoomStore::isRoomId((string) $_GET['room']) ? (string) $_GET['room'] : '';

if (($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    if ($config['cors_origins'] === ['*']) {
        header('Access-Control-Allow-Origin: *');
    }
    echo json_encode(Embed::describe($base, $room, $config), JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
    exit;
}

// Normalise the options and hand over to the page in compact mode.
$_GET['embed'] = (isset($_GET['compact']) && $_GET['compact'] === '0') ? '0' : '1';
if ($room !== '') {
    $_GET['room'] = $room;
} else {
    unset($_GET['room']);
}
if (isset($_GET['chat']) && $_GET['chat'] === '0') {
    $_GET['nochat'] = '1';
}
if (isset($_GET['autoplay']) && $_GET['autoplay'] === '0') {
    $_GET['noautoplay'] = '1';
}
require __DIR__ . '/index.php';
