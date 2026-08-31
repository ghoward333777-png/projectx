<?php

declare(strict_types=1);

require_once __DIR__ . '/SitePackageExporter.php';

$exporter = new SitePackageExporter();

try {
    $bytes = $exporter->export();
} catch (Throwable $exception) {
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Could not build the hosting package: ' . $exception->getMessage();
    exit;
}

header('Content-Type: application/zip');
header('Content-Disposition: attachment; filename="book-intelligence-studio.zip"');
header('Content-Length: ' . strlen($bytes));
echo $bytes;
