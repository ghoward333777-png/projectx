<?php

declare(strict_types=1);

/**
 * Serves colorization outputs from colorized/<job>/ — a file inline (previews,
 * downloads) or a 16K frame sequence as a zip. Paths are validated: a job id
 * and one file or directory name, nothing else.
 *
 *   colorized.php?f=<job>/<file>[&download=1]
 */
$root = realpath(__DIR__ . '/../colorized');
$f = (string) ($_GET['f'] ?? '');
if ($root === false || !preg_match('#^[a-z0-9_-]{1,64}/[A-Za-z0-9._-]{1,128}$#', $f) || str_contains($f, '..')) {
    http_response_code(404);
    exit;
}
$path = realpath($root . '/' . $f);
if ($path === false || !str_starts_with($path, $root . '/')) {
    http_response_code(404);
    exit;
}
if (is_dir($path)) {
    if (!class_exists('ZipArchive')) {
        http_response_code(501);
        header('Content-Type: text/plain; charset=utf-8');
        echo "Downloading a folder needs PHP's zip extension. Run php bin/doctor.php for the install command.\n";
        exit;
    }
    $zip = sys_get_temp_dir() . '/colorized-' . md5($path) . '.zip';
    if (!is_file($zip) || filemtime($zip) < filemtime($path)) {
        $z = new ZipArchive();
        $z->open($zip, ZipArchive::CREATE | ZipArchive::OVERWRITE);
        foreach (glob($path . '/*') ?: [] as $file) {
            $z->addFile($file, basename($path) . '/' . basename($file));
            $z->setCompressionName(basename($path) . '/' . basename($file), ZipArchive::CM_STORE);
        }
        $z->close();
    }
    header('Content-Type: application/zip');
    header('Content-Disposition: attachment; filename="' . basename($path) . '.zip"');
    header('Content-Length: ' . filesize($zip));
    readfile($zip);
    exit;
}
$types = ['png' => 'image/png', 'jpg' => 'image/jpeg', 'mp4' => 'video/mp4', 'json' => 'application/json'];
header('Content-Type: ' . ($types[strtolower(pathinfo($path, PATHINFO_EXTENSION))] ?? 'application/octet-stream'));
header('Content-Length: ' . filesize($path));
if (!empty($_GET['download'])) {
    header('Content-Disposition: attachment; filename="' . basename($path) . '"');
}
readfile($path);
