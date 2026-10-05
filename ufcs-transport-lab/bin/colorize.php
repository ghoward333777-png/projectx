<?php

declare(strict_types=1);

/**
 * QueryBook Semantic Colorization Engine (VCUM): black-and-white → colour at 1K, 4K and 16K.
 *
 *   php bin/colorize.php --in=photo.png [--targets=1k,4k,16k] [--out=colorized/]
 *       [--scene="setting=beach;era=1950s;time=golden_hour;contains=people"]
 *       [--fact="Golden Gate Bridge|has_color|#C0362C"]... [--region="0.6,0.2,0.9,0.6=Golden Gate Bridge"]...
 *       [--max-seconds=10] [--max-16k-frames=30] [--still-16k=jpg|png] [--evaluate]
 *   php bin/colorize.php --demo [--targets=...]       (synthetic landscape, scored against its true colours)
 *
 * Scene keys: setting, contains, era (1920s–1980s, modern), time (golden_hour, midday, overcast, night, tungsten).
 * Region boxes are fractions of the frame (x0,y0,x1,y1). Facts are UFCS triples; a "has_color" fact with a hex
 * value gives a named thing its known colour. Writes <name>-<target>.<ext>, a side-by-side preview and
 * <name>.colorization.json (the provenance manifest).
 */
require __DIR__ . '/../src/bootstrap.php';
ufcs_lab_ensure_jit();

$o = [];
foreach (array_slice($argv, 1) as $arg) {
    if (preg_match('/^--([a-z0-9-]+)(?:=(.*))?$/s', $arg, $m)) {
        if (in_array($m[1], ['fact', 'region'], true)) {
            $o[$m[1]][] = $m[2] ?? '';
        } else {
            $o[$m[1]] = $m[2] ?? true;
        }
    }
}
$out = (string) ($o['out'] ?? 'colorized');
if (!empty($o['demo'])) {
    if (!is_dir($out)) {
        mkdir($out, 0775, true);
    }
    DemoScenes::landscape($out . '/demo-landscape.png');
    $o['in'] = $out . '/demo-landscape.png';
    $o['scene'] ??= 'setting=lake,beach;time=midday';
    $o['region'] ??= ['0.66,0.28,0.82,0.55=stone'];
    $o['evaluate'] = true;
}
if (empty($o['in'])) {
    fwrite(STDERR, "usage: php bin/colorize.php --in=FILE [options] | --demo (see the header of this file)\n");
    exit(1);
}
$m = (new Colorizer())->run((string) $o['in'], [
    'scene' => (string) ($o['scene'] ?? ''),
    'facts' => (array) ($o['fact'] ?? []),
    'regions' => (array) ($o['region'] ?? []),
    'targets' => explode(',', (string) ($o['targets'] ?? '1k,4k')),
    'out_dir' => $out,
    'max_seconds' => (float) ($o['max-seconds'] ?? 10),
    'max_16k_frames' => (int) ($o['max-16k-frames'] ?? 30),
    'still_16k' => (string) ($o['still-16k'] ?? 'jpg'),
    'evaluate' => !empty($o['evaluate']),
]);
printf("%s → %s %dx%d, %d frame(s), %s s\n", $m['input']['file'], $m['input']['kind'], $m['input']['width'], $m['input']['height'], $m['input']['frames'], $m['elapsed_s']);
printf("Scene: lighting %s, era %s · saturation %s, warmth %s\n", $m['grade']['lighting'], $m['grade']['era'], $m['grade']['saturation'], $m['grade']['warmth']);
foreach ($m['regions'] as $cls => $r) {
    printf("  %-10s %5.1f%% of frame  colour %s  confidence %.2f  withheld %s%%\n", $cls, $r['share_pct'], $r['color'] ?? '—', $r['mean_confidence'], $r['withheld_pct']);
}
foreach ($m['outputs'] as $t => $x) {
    printf("  %-4s %dx%d %-20s %8.1f MB  consistency %s dB  → %s\n", strtoupper($t), $x['width'], $x['height'], $x['format'], $x['bytes'] / 1e6, $x['consistency_psnr_db'], $x['file']);
}
if (isset($m['evaluation']['skipped'])) {
    echo $m['evaluation']['skipped'], "\n";
} elseif (isset($m['evaluation'])) {
    printf("Against the true colours: ΔE %s (gray input %s), %s%% closer\n", $m['evaluation']['mean_delta_e_colorized'], $m['evaluation']['mean_delta_e_gray'], $m['evaluation']['improvement_pct']);
}
printf("Withheld (kept gray, confidence < %s): %s%% · manifest: %s\n", Colorizer::WITHHOLD_BELOW, $m['withheld_pct'], $m['manifest_file']);
