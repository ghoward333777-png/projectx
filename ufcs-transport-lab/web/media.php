<?php

declare(strict_types=1);

/**
 * Serves HLS / DASH packages that Node 2 rebuilt under received/packages/,
 * with the MIME types players expect. Paths are validated: package id and a
 * relative, ".."-free file path only.
 *
 *   media.php?p=<package_id>/<path inside the package>
 */
require __DIR__ . '/../src/bootstrap.php';

$p = (string) ($_GET['p'] ?? '');
[$id, $path] = array_pad(explode('/', $p, 2), 2, '');
$root = realpath(__DIR__ . '/../received/packages');
if ($root === false || !preg_match('/^[a-z0-9_-]{1,64}$/i', $id) || !StreamPackager::safePath($path)) {
    http_response_code(404);
    exit;
}
$file = $root . '/' . $id . '/' . $path;
$real = realpath($file);
if ($real === false || !str_starts_with($real, $root . '/') || !is_file($real)) {
    http_response_code(404);
    exit;
}
$types = ['m3u8' => 'application/vnd.apple.mpegurl', 'mpd' => 'application/dash+xml', 'ts' => 'video/mp2t', 'm4s' => 'video/iso.segment',
    'mp4' => 'video/mp4', 'm4a' => 'audio/mp4', 'aac' => 'audio/aac', 'vtt' => 'text/vtt'];
header('Content-Type: ' . ($types[strtolower(pathinfo($real, PATHINFO_EXTENSION))] ?? 'application/octet-stream'));
header('Content-Length: ' . filesize($real));
header('Cache-Control: no-cache');
header('Access-Control-Allow-Origin: *');
readfile($real);
