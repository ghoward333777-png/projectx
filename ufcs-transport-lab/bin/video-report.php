<?php

declare(strict_types=1);

/**
 * Video transit tests — before / during / after — for video-on-demand and
 * live feeds through emulated network paths, with four reports:
 * compression, transport efficiency, decompression overhead, propagation.
 *
 *   php bin/video-report.php [--preset=standard|quick] [--out=reports] [--keep]
 *
 * Writes <out>/video-report.json and <out>/video-report.html.
 */
require __DIR__ . '/../src/bootstrap.php';

$o = getopt('', ['preset:', 'out:', 'keep']);
$preset = (string) ($o['preset'] ?? 'standard');
if (!isset(VideoLab::PRESETS[$preset])) {
    fwrite(STDERR, "Unknown preset; use standard or quick\n");
    exit(1);
}
fwrite(STDERR, "Video transit lab ($preset)\n");
$lab = new VideoLab(['preset' => $preset, 'keep' => isset($o['keep'])], fn (string $m) => fwrite(STDERR, '  · ' . $m . "\n"));
$r = $lab->run();
$out = rtrim((string) ($o['out'] ?? __DIR__ . '/../reports'), '/');
if (!is_dir($out)) {
    mkdir($out, 0775, true);
}
file_put_contents($out . '/video-report.json', json_encode($r, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
if (class_exists('VideoReportView')) {
    file_put_contents($out . '/video-report.html', VideoReportView::page($r));
}
foreach ($r['findings'] as $line) {
    echo '• ' . $line . "\n";
}
echo "\nFinished in {$r['elapsed_s']} s. Reports in $out/\n";
