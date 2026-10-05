<?php

declare(strict_types=1);

/**
 * Colorization + upscaling benchmark.
 *
 *   php bin/colorize-bench.php [--out=reports] [--quick]
 *
 * Part A reproduces the only hands-on test in Atlas Cloud's "best video upscaler"
 * roundup (2026-09-18): three short low-resolution clips (256×144, 256×150,
 * 174×256; 5.4–7 s) upscaled 2× and to 640 px. Here they are also colorized.
 * Part B measures throughput at 1K, 4K and 16K on a 720p clip. Clips are
 * synthetic (DemoScenes) with known colour, so colour accuracy is scored.
 * Writes <out>/colorize-bench.json.
 */
require __DIR__ . '/../src/bootstrap.php';
ufcs_lab_ensure_jit();

$o = getopt('', ['out:', 'quick']);
$out = rtrim((string) ($o['out'] ?? __DIR__ . '/../reports'), '/');
@mkdir($out, 0775, true);
$work = sys_get_temp_dir() . '/ufcs-colorbench-' . bin2hex(random_bytes(3));
mkdir($work);
$cpu = function (): float {
    $s = getrusage(0);
    $c = getrusage(1);
    return $s['ru_utime.tv_sec'] + $s['ru_utime.tv_usec'] / 1e6 + $s['ru_stime.tv_sec'] + $s['ru_stime.tv_usec'] / 1e6
        + $c['ru_utime.tv_sec'] + $c['ru_utime.tv_usec'] / 1e6 + $c['ru_stime.tv_sec'] + $c['ru_stime.tv_usec'] / 1e6;
};
$run = function (string $label, string $src, array $opts) use ($cpu): array {
    $c0 = $cpu();
    $t0 = microtime(true);
    $m = (new Colorizer())->run($src, $opts);
    $wall = microtime(true) - $t0;
    $cpuS = $cpu() - $c0;
    $sec = max(0.001, (float) $m['input']['seconds']);
    fwrite(STDERR, sprintf("  · %-28s %6.1f s wall  %6.1f s CPU  (%s s of video)\n", $label, $wall, $cpuS, $sec));
    return ['label' => $label, 'input' => $m['input'], 'outputs' => array_map(fn ($x) => array_diff_key($x, ['file' => 1, 'sha256' => 1]), $m['outputs']),
        'wall_s' => round($wall, 2), 'cpu_s' => round($cpuS, 2), 'realtime_x' => round($sec / $wall, 3), 'cpu_s_per_video_min' => round($cpuS / $sec * 60, 1),
        'evaluation' => $m['evaluation'] ?? null, 'withheld_pct' => $m['withheld_pct'], 'agents' => array_column($m['agents'], 'ms', 'agent')];
};

$report = ['generated_at' => gmdate('c'), 'host' => ['cpus' => (int) trim((string) shell_exec('nproc')), 'php' => PHP_VERSION,
    'ffmpeg' => trim(explode("\n", (string) shell_exec(escapeshellarg(MediaCodec::ffmpeg()) . ' -version'))[0])], 'part_a' => [], 'part_b' => []];

// Part A — the roundup's clip sizes and lengths.
fwrite(STDERR, "Part A: the roundup's three test clips, colorized and upscaled\n");
$clips = [['portrait', 256, 144, 7.0], ['game', 256, 150, 5.4], ['ai-clip', 174, 256, 6.0]];
foreach ($clips as [$name, $w, $h, $sec]) {
    $src = "$work/$name.mp4";
    DemoScenes::landscapeClip($src, $sec, $w, $h);
    $report['part_a'][] = $run("$name {$w}×{$h} → 2× and 640 px", $src, ['scene' => 'setting=lake,beach;time=midday', 'targets' => ['2x', 'w640'],
        'out_dir' => "$work/a-$name", 'evaluate' => true, 'max_seconds' => $sec]);
}

// Part B — 1K / 4K / 16K throughput on a 720p clip.
fwrite(STDERR, "Part B: 720p clip to 1K, 4K and 16K\n");
$sec = isset($o['quick']) ? 2.0 : 5.0;
$src = "$work/hd.mp4";
DemoScenes::landscapeClip($src, $sec, 1280, 720);
foreach (['1k', '4k', '16k'] as $t) {
    $report['part_b'][] = $run("720p → " . strtoupper($t), $src, ['scene' => 'setting=lake,beach;time=midday', 'targets' => [$t], 'out_dir' => "$work/b-$t",
        'evaluate' => true, 'max_seconds' => $sec, 'max_16k_frames' => (int) ($sec * 30)]);
}
StreamPackager::removeDir($work);
file_put_contents("$out/colorize-bench.json", json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
echo "Written $out/colorize-bench.json\n";
