<?php

declare(strict_types=1);

/**
 * Benchmark Node 1 → Node 2.
 *
 *   php bin/bench.php [--preset=quick|full|smoke] [--remote=host:port] [--sign]
 *                     [--facts=N] [--link-mbps=100] [--mixed-link-mbps=40]
 *                     [--mixed-seconds=3] [--video=1280x720] [--video-seconds=10]
 *                     [--out=reports]
 *
 * Without --remote it starts Node 2 as a local process and talks to it over
 * loopback TCP. With --remote, start `php bin/receiver.php --host=0.0.0.0`
 * on the other machine first (ports P, P+1, P+2 must be reachable).
 * Writes <out>/bench-<time>.json, <out>/latest.json and <out>/latest.html.
 */
require __DIR__ . '/../src/bootstrap.php';

$o = getopt('', ['preset:', 'remote:', 'sign', 'facts:', 'link-mbps:', 'mixed-link-mbps:', 'mixed-seconds:', 'video:', 'video-seconds:', 'audio-seconds:', 'images:', 'out:']);
$cfg = ['preset' => (string) ($o['preset'] ?? 'quick')];
if (!isset(Benchmark::PRESETS[$cfg['preset']])) {
    fwrite(STDERR, "Unknown preset; use quick, full or smoke\n");
    exit(1);
}
foreach (['facts' => 'facts', 'images' => 'images'] as $flag => $key) {
    if (isset($o[$flag])) {
        $cfg[$key] = (int) $o[$flag];
    }
}
foreach (['link-mbps' => 'link_mbps', 'mixed-link-mbps' => 'mixed_link_mbps', 'mixed-seconds' => 'mixed_seconds', 'video-seconds' => 'video_seconds', 'audio-seconds' => 'audio_seconds'] as $flag => $key) {
    if (isset($o[$flag])) {
        $cfg[$key] = (float) $o[$flag];
    }
}
if (isset($o['video']) && preg_match('/^(\d+)x(\d+)$/', (string) $o['video'], $m)) {
    $cfg['video_w'] = (int) $m[1];
    $cfg['video_h'] = (int) $m[2];
}
$cfg['remote'] = (string) ($o['remote'] ?? '');
$cfg['sign'] = isset($o['sign']);

$bench = new Benchmark($cfg, function (string $m): void {
    fwrite(STDERR, '  · ' . $m . "\n");
});
fwrite(STDERR, "QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab — benchmark ({$cfg['preset']})\n");
$report = $bench->run();

$out = rtrim((string) ($o['out'] ?? __DIR__ . '/../reports'), '/');
if (!is_dir($out)) {
    mkdir($out, 0775, true);
}
$json = json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
file_put_contents($out . '/bench-' . gmdate('Ymd-His') . '.json', $json);
file_put_contents($out . '/latest.json', $json);
file_put_contents($out . '/latest.html', ReportView::page($report));

echo ReportView::text($report);
$failed = count(array_filter($report['criteria'], fn ($c) => $c['pass'] === false));
exit($failed > 0 ? 3 : 0);
