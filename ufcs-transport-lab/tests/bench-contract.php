<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

// The smoke preset runs every scenario end to end in a few seconds.
$r = (new Benchmark(['preset' => 'smoke', 'sign' => true]))->run();
foreach (['text', 'image', 'video', 'audio', 'mixed', 'streaming'] as $k) {
    check(isset($r['scenarios'][$k]), "scenario $k present");
}
check(count($r['scenarios']['mixed']['modes']) === 2, 'mixed workload runs multi and single connection modes');
$failed = array_filter($r['criteria'], fn ($c) => $c['pass'] === false);
check($failed === [], 'all success criteria pass: ' . implode('; ', array_map(fn ($c) => $c['criterion'] . ' — ' . $c['measured'], $failed)));
$html = ReportView::page($r);
check(str_contains($html, '<svg') && str_contains($html, 'Success criteria') && !str_contains($html, '<script'), 'HTML report renders charts without scripts');
done('bench-contract');
