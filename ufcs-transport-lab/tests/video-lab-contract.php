<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

if (MediaCodec::ffmpeg() === '') {
    echo "  (skip video-lab: ffmpeg not installed)\n";
    done('video-lab-contract');
    exit(0);
}

// The path emulator adds its one-way delay in both directions.
$node = LocalNode::start();
$px = PathEmulator::start($node->port, 30, 20);
$t = new Transport('127.0.0.1', $px->port);
$t->connect(10);
$s = new Sender($t);
for ($i = 0; $i < 5; $i++) {
    $s->ping();
    $t->flush(5);
}
$rtt = Stats::summary($t->latencies(Protocol::P_CONTROL));
check($rtt['p50'] >= 59 && $rtt['p50'] < 90, 'emulated 30 ms one-way path gives a ~60 ms round trip (got ' . $rtt['p50'] . ' ms)');
$t->close();
$px->stop();
$t = new Transport('127.0.0.1', $node->port);
$t->connect();
(new Sender($t))->control('SHUTDOWN');
$t->close();
$node->finish();

// Quick preset end to end: before / during / after for every transfer.
$r = (new VideoLab(['preset' => 'quick']))->run();
$all = array_merge($r['vod'], $r['packages'], $r['sweep'], $r['live']);
check(count($r['sources']) === 2 && $r['sources']['motion']['ti'] > $r['sources']['studio']['ti'], 'two masters; the motion source has more temporal information');
foreach ($all as $t) {
    check($t['after']['intact'] ?? false, $t['test'] . ' arrived intact on Node 2');
    check(($t['after']['decode']['ok'] ?? false) && ($t['after']['quality']['ssim'] ?? 0) > 0.7, $t['test'] . ' decodes and has measured quality');
    $d = $t['during'];
    check($d['framing_efficiency_pct'] > 98.5 && $d['frames'] > 0, $t['test'] . ' framing efficiency measured');
    $delay = $r['paths'][$t['path']]['delay_ms'];
    check($d['propagation']['path_ms']['p50'] >= $delay * 0.9, $t['test'] . ' path transit is at least the one-way delay');
}
$live = array_column($r['live'], null, 'mode');
$direct = array_values(array_filter($r['live'], fn ($l) => $l['kind'] === 'Direct live'));
check(count($direct) === 2, 'direct live feed ran in both connection modes');
$m = array_values(array_filter($direct, fn ($l) => $l['mode'] === 'multi'))[0];
$sg = array_values(array_filter($direct, fn ($l) => $l['mode'] === 'single'))[0];
check($m['during']['live']['edge_to_node2_ms']['p50'] < $sg['during']['live']['edge_to_node2_ms']['p50'], 'per-priority connections keep the live feed ahead of bulk traffic');
check(count($r['envelope']) >= 4 && count($r['findings']) >= 5, 'decompression micro-benchmarks and findings produced');
$html = VideoReportView::page($r);
check(str_contains($html, '4 · Propagation') && str_contains($html, '<svg') && !str_contains($html, '<script'), 'report renders without scripts');
done('video-lab-contract');
