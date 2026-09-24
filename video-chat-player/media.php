<?php
declare(strict_types=1);

// Streams a file from media/ with byte-range support, so seeking works even on PHP's
// built-in dev server (which ignores Range headers when serving static files).
require_once __DIR__ . '/lib/Source.php';

$name = (string) ($_GET['f'] ?? '');
$dir = __DIR__ . '/media';
if (!Source::isMediaName($name) || !is_file($dir . '/' . $name)) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    exit('Not found');
}
$path = $dir . '/' . $name;
$size = filesize($path) ?: 0;
$range = Source::parseRange((string) ($_SERVER['HTTP_RANGE'] ?? ''), $size);
if ($range === false) {
    http_response_code(416);
    header('Content-Range: bytes */' . $size);
    exit;
}
[$start, $end] = $range ?? [0, max(0, $size - 1)];
http_response_code($range === null ? 200 : 206);
header('Content-Type: ' . Source::mimeType($name));
header('Accept-Ranges: bytes');
header('Content-Length: ' . ($size === 0 ? 0 : $end - $start + 1));
header('Cache-Control: public, max-age=3600');
header('X-Content-Type-Options: nosniff');
if ($range !== null) {
    header("Content-Range: bytes {$start}-{$end}/{$size}");
}
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'HEAD' || $size === 0) {
    exit;
}
$fh = fopen($path, 'rb');
if ($fh === false) {
    http_response_code(500);
    exit;
}
fseek($fh, $start);
$left = $end - $start + 1;
while ($left > 0 && !feof($fh)) {
    $chunk = fread($fh, (int) min(65536, $left));
    if ($chunk === false || $chunk === '') {
        break;
    }
    echo $chunk;
    $left -= strlen($chunk);
    flush();
}
fclose($fh);
