<?php

declare(strict_types=1);

/**
 * Renders a benchmark report: a standalone HTML page (reports/latest.html),
 * the same body embedded in the dashboard, and a plain-text summary for the
 * terminal. Charts are inline SVG — no scripts, no external assets.
 */
final class ReportView
{
    public const CSS = <<<'CSS'
:root{color-scheme:light;--surface:#fcfcfb;--panel:#ffffff;--line:#e4e3df;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--good:#0ca30c;--crit:#d03b3b;--grid:#ecebe7;--code:#f4f3f0;--accent:#2a78d6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--surface:#1a1a19;--panel:#222220;--line:#383835;--text:#ffffff;--text2:#c3c2b7;--muted:#99988f;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--grid:#2c2c2a;--code:#2a2a28;--accent:#3987e5}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--panel:#222220;--line:#383835;--text:#ffffff;--text2:#c3c2b7;--muted:#99988f;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--grid:#2c2c2a;--code:#2a2a28;--accent:#3987e5}
*{box-sizing:border-box}body{margin:0;background:var(--surface);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.2rem;margin:32px 0 8px}h3{font-size:1rem;margin:20px 0 6px}
.sub{color:var(--text2);margin:0 0 16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th,td.num,td:first-child{white-space:nowrap}
th{color:var(--text2);font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.pass{color:var(--good);font-weight:600}.fail{color:var(--crit);font-weight:600}.na{color:var(--muted)}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem}pre{background:var(--code);padding:12px;border-radius:8px;overflow-x:auto}
.chart text{fill:var(--text2);font-size:12px}.chart .val{fill:var(--text);font-weight:600}.chart .gridl{stroke:var(--grid)}
.chart rect.bar{rx:4px}.chart g.m:hover rect.bar{opacity:.8}.legend{display:flex;gap:16px;font-size:.85rem;color:var(--text2);margin:4px 0 8px}
.legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:var(--c)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi b{display:block;font-size:1.5rem;font-variant-numeric:tabular-nums}.kpi span{color:var(--text2);font-size:.85rem}
CSS;

    public static function page(array $r): string
    {
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            . '<title>UFCS-FQL Benchmark Report</title><style>' . self::CSS . '</style></head><body><main>'
            . '<h1>UFCS-FQL Benchmark Report</h1><p class="sub">' . self::e($r['lab'] ?? '') . ' · ' . self::e($r['generated_at'] ?? '') . '</p>'
            . self::body($r) . '</main></body></html>';
    }

    public static function body(array $r): string
    {
        $h = self::summary($r);
        $h .= self::criteriaTable($r['criteria'] ?? []);
        $h .= self::ratioChart($r);
        $sc = $r['scenarios'] ?? [];
        if (isset($sc['mixed'])) {
            $h .= self::mixed($sc['mixed']);
        }
        if (isset($sc['text'])) {
            $t = $sc['text'];
            $h .= '<h2>' . self::e($t['title']) . '</h2><p class="sub">' . number_format($t['facts']) . ' facts, ' . $t['batch'] . ' per FACT_BATCH, simulated link '
                . self::link($t['link_mbps']) . '. Ratio = raw JSONL bytes ÷ compressed payload bytes.</p>';
            $h .= self::table($t['rows'], ['codec' => 'Codec', 'ratio' => 'Ratio ×', 'raw_bytes' => 'Raw', 'payload_bytes' => 'Payload', 'header_overhead_pct' => 'Frame overhead %',
                'compress_ms' => 'Compress ms', 'transfer_s' => 'Transfer s', 'wire_mb_s' => 'Wire MB/s', 'facts_per_s' => 'Facts/s', 'sender_cpu_s' => 'Node 1 CPU s',
                'receiver_cpu_s' => 'Node 2 CPU s', 'latency_ms.p50' => 'ACK p50 ms', 'rejected' => 'Rejected']);
        }
        if (isset($sc['image'])) {
            $i = $sc['image'];
            $h .= '<h2>' . self::e($i['title']) . '</h2><p class="sub">Photo-like test images at ' . self::e($i['resolution']) . ', sent on the bulk connection.</p>';
            $h .= self::table($i['rows'], ['codec' => 'Variant', 'ratio' => 'Ratio ×', 'source_bytes' => 'PNG bytes', 'payload_bytes' => 'Payload', 'encode_ms' => 'Encode ms',
                'transfer_s' => 'Transfer s', 'wire_mb_s' => 'Wire MB/s', 'received' => 'Received', 'decode_errors' => 'Errors']);
        }
        foreach (['video', 'audio'] as $k) {
            if (!isset($sc[$k])) {
                continue;
            }
            $v = $sc[$k];
            $h .= '<h2>' . self::e($v['title']) . '</h2>';
            if (!empty($v['skipped'])) {
                $h .= '<p class="na">Skipped: ' . self::e($v['skipped']) . '</p>';
                continue;
            }
            $h .= '<p class="sub">Source: ' . self::e($v['source']) . (isset($v['plan']) ? '. Bitrate plan: ' . self::e($v['plan']['reason']) : '') . '. Ratio is against the uncompressed source.</p>';
            $h .= self::table($v['rows'], ['codec' => 'Codec', 'ratio' => 'Ratio ×', 'target_kbps' => 'Target kbps', 'actual_kbps' => 'Actual kbps', 'payload_bytes' => 'Bitstream',
                'encode_ms' => 'Encode ms', 'chunks' => 'Chunks', 'transfer_s' => 'Transfer s', 'chunk_latency_ms.p50' => 'Chunk p50 ms', 'chunk_latency_ms.p95' => 'Chunk p95 ms',
                'intact' => 'Intact', 'decodes' => 'Decodes']);
        }
        if (isset($sc['streaming'])) {
            $st = $sc['streaming'];
            $h .= '<h2>' . self::e($st['title']) . '</h2>';
            if (!empty($st['skipped'])) {
                $h .= '<p class="na">Skipped: ' . self::e($st['skipped']) . '</p>';
            } else {
                $h .= '<p class="sub">Source: ' . self::e($st['source']) . '. HLS and DASH packages travel file by file (segments on the bulk class, manifests last); RTMP is ingested live and repackaged on Node 2.</p>';
                $h .= self::table($st['rows'], ['protocol' => 'Protocol', 'mode' => 'Mode', 'files' => 'Files', 'segments' => 'Segments / chunks', 'bytes' => 'Bytes',
                    'package_ms' => 'Package ms', 'overhead_pct' => 'Frame overhead %', 'transfer_s' => 'Transfer s', 'latency_ms.p50' => 'ACK p50 ms', 'rebuilt' => 'Rebuilt', 'plays' => 'Plays']);
            }
        }
        $h .= '<h2>Environment</h2><div class="card"><pre>' . self::e(json_encode(['environment' => $r['environment'] ?? [], 'config' => $r['config'] ?? []], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)) . '</pre></div>';
        return $h;
    }

    private static function summary(array $r): string
    {
        $crit = $r['criteria'] ?? [];
        $pass = count(array_filter($crit, fn ($c) => $c['pass'] === true));
        $zstd = null;
        foreach ($r['scenarios']['text']['rows'] ?? [] as $row) {
            if ($row['codec'] === 'ZSTD' && empty($row['skipped'])) {
                $zstd = $row['ratio'];
            }
        }
        $multi = $r['scenarios']['mixed']['modes']['multi'] ?? null;
        $single = $r['scenarios']['mixed']['modes']['single'] ?? null;
        $k = '<div class="kpis">';
        $k .= '<div class="kpi"><b>' . $pass . ' / ' . count($crit) . '</b><span>success criteria met</span></div>';
        if ($zstd !== null) {
            $k .= '<div class="kpi"><b>' . $zstd . '×</b><span>UFCS facts with Zstd</span></div>';
        }
        if ($multi) {
            $k .= '<div class="kpi"><b>' . $multi['control_latency_ms']['p95'] . ' ms</b><span>control p95 under bulk load</span></div>';
        }
        if ($single) {
            $k .= '<div class="kpi"><b>' . $single['control_latency_ms']['p95'] . ' ms</b><span>same, one shared connection</span></div>';
        }
        $k .= '<div class="kpi"><b>' . self::e((string) ($r['elapsed_s'] ?? '')) . ' s</b><span>benchmark run time</span></div>';
        return $k . '</div>';
    }

    private static function criteriaTable(array $crit): string
    {
        $h = '<h2>Success criteria</h2><div class="card"><table><tr><th>Result</th><th>Criterion</th><th>Target</th><th>Measured</th></tr>';
        foreach ($crit as $c) {
            $res = $c['pass'] === null ? '<span class="na">— n/a</span>' : ($c['pass'] ? '<span class="pass">✔ Pass</span>' : '<span class="fail">✖ Fail</span>');
            $h .= '<tr><td>' . $res . '</td><td>' . self::e($c['criterion']) . '</td><td>' . self::e($c['target']) . '</td><td>' . self::e($c['measured']) . '</td></tr>';
        }
        return $h . '</table></div>';
    }

    /** Single-series horizontal bars: compression ratio of every codec run. */
    private static function ratioChart(array $r): string
    {
        $items = [];
        foreach (['text' => 'Text', 'image' => 'Image', 'video' => 'Video', 'audio' => 'Audio'] as $k => $label) {
            foreach ($r['scenarios'][$k]['rows'] ?? [] as $row) {
                if (empty($row['skipped']) && isset($row['ratio'])) {
                    $items[] = [$label . ' · ' . $row['codec'], (float) $row['ratio']];
                }
            }
        }
        if (!$items) {
            return '';
        }
        return '<h2>Compression ratio by content type and codec</h2><p class="sub">Times smaller than the source (log scale). Hover a bar for the exact value; the tables below hold every number.</p>'
            . '<div class="card">' . self::hbars($items, [['', 'var(--s1)']], true, '×') . '</div>';
    }

    private static function mixed(array $m): string
    {
        $h = '<h2>' . self::e($m['title']) . '</h2><p class="sub">Simulated link ' . self::link($m['link_mbps']) . ' for ' . self::e((string) $m['seconds']) . ' s. Load: ' . self::e($m['load']) . '.</p>';
        $multi = $m['modes']['multi'] ?? null;
        $single = $m['modes']['single'] ?? null;
        if ($multi && $single) {
            $items = [];
            foreach (['control' => 'Control', 'normal' => 'Normal'] as $k => $lbl) {
                foreach (['p50', 'p95'] as $p) {
                    $items[] = [$lbl . ' ' . $p, (float) $multi[$k . '_latency_ms'][$p], (float) $single[$k . '_latency_ms'][$p]];
                }
            }
            $h .= '<div class="card"><h3>ACK latency (ms, log scale) — lower is better</h3><div class="legend"><span style="--c:var(--s1)">3 connections (per priority)</span><span style="--c:var(--s2)">1 shared connection</span></div>'
                . self::hbars($items, [['3 connections', 'var(--s1)'], ['1 connection', 'var(--s2)']], true, ' ms') . '</div>';
        }
        $rows = [];
        foreach ($m['modes'] as $mode => $x) {
            $rows[] = ['mode' => $mode === 'multi' ? '3 connections' : '1 shared connection', 'control_p50' => $x['control_latency_ms']['p50'], 'control_p95' => $x['control_latency_ms']['p95'],
                'normal_p50' => $x['normal_latency_ms']['p50'], 'normal_p95' => $x['normal_latency_ms']['p95'], 'bulk_p50' => $x['bulk_latency_ms']['p50'],
                'bulk_mbps' => $x['throughput_mbps']['bulk'], 'normal_mbps' => $x['throughput_mbps']['normal'], 'util' => $x['link_utilisation_pct'], 'pings' => $x['pings']];
        }
        return $h . self::table($rows, ['mode' => 'Mode', 'control_p50' => 'Control p50 ms', 'control_p95' => 'Control p95 ms', 'normal_p50' => 'Normal p50 ms', 'normal_p95' => 'Normal p95 ms',
            'bulk_p50' => 'Bulk p50 ms', 'bulk_mbps' => 'Bulk Mbps', 'normal_mbps' => 'Normal Mbps', 'util' => 'Link use %', 'pings' => 'Pings']);
    }

    /**
     * Horizontal bar chart. $items: [label, value, value2?]; $series: [[name, color], ...].
     *
     * @param array<int, array<int, mixed>> $items
     * @param array<int, array{0:string, 1:string}> $series
     */
    public static function hbars(array $items, array $series, bool $log, string $unit): string
    {
        $labelW = 20 + 7 * max(10, ...array_map(fn ($it) => mb_strlen((string) $it[0]), $items));
        $plotW = 560;
        $barH = 14;
        $gap = 2;
        $groupGap = 12;
        $n = count($series);
        $max = 0.0;
        $min = INF;
        foreach ($items as $it) {
            for ($s = 1; $s <= $n; $s++) {
                $max = max($max, (float) $it[$s]);
                if ((float) $it[$s] > 0) {
                    $min = min($min, (float) $it[$s]);
                }
            }
        }
        $lo = $log ? 10 ** floor(log10(max(1e-3, min(1.0, $min)))) : 0.0;
        $hi = $log ? 10 ** ceil(log10(max($max, $lo * 10))) : max(1e-9, $max);
        $x = function (float $v) use ($log, $lo, $hi, $plotW): float {
            if ($log) {
                $v = max($v, $lo);
                return $plotW * (log10($v) - log10($lo)) / (log10($hi) - log10($lo));
            }
            return $plotW * $v / $hi;
        };
        $groupH = $n * $barH + ($n - 1) * $gap;
        $height = count($items) * ($groupH + $groupGap) + 24;
        $width = $labelW + $plotW + 90;
        $svg = '<svg class="chart" role="img" viewBox="0 0 ' . $width . ' ' . $height . '" width="100%" style="max-width:' . $width . 'px">';
        // gridlines + ticks
        $ticks = [];
        if ($log) {
            for ($t = $lo; $t <= $hi * 1.0001; $t *= 10) {
                $ticks[] = $t;
            }
        } else {
            for ($i = 0; $i <= 4; $i++) {
                $ticks[] = $hi * $i / 4;
            }
        }
        foreach ($ticks as $t) {
            $tx = $labelW + $x((float) $t);
            $svg .= '<line class="gridl" x1="' . round($tx, 1) . '" x2="' . round($tx, 1) . '" y1="0" y2="' . ($height - 20) . '"/>'
                . '<text x="' . round($tx, 1) . '" y="' . ($height - 6) . '" text-anchor="middle">' . self::num((float) $t) . '</text>';
        }
        $y = 0;
        foreach ($items as $it) {
            $svg .= '<text x="' . ($labelW - 8) . '" y="' . ($y + $groupH / 2 + 4) . '" text-anchor="end">' . self::e((string) $it[0]) . '</text>';
            for ($s = 1; $s <= $n; $s++) {
                $v = (float) $it[$s];
                $w = max(2.0, $x($v));
                $by = $y + ($s - 1) * ($barH + $gap);
                $name = $series[$s - 1][0];
                $svg .= '<g class="m"><title>' . self::e($it[0] . ($name !== '' ? ' — ' . $name : '') . ': ' . self::num($v) . trim($unit)) . '</title>'
                    . '<rect class="bar" x="' . $labelW . '" y="' . $by . '" width="' . round($w, 1) . '" height="' . $barH . '" fill="' . $series[$s - 1][1] . '"/>'
                    . '<text class="val" x="' . round($labelW + $w + 6, 1) . '" y="' . ($by + $barH - 3) . '">' . self::num($v) . self::e($unit) . '</text></g>';
            }
            $y += $groupH + $groupGap;
        }
        return $svg . '</svg>';
    }

    /** @param array<int, array<string, mixed>> $rows @param array<string, string> $cols */
    public static function table(array $rows, array $cols): string
    {
        $h = '<div class="card"><table><tr>';
        foreach ($cols as $label) {
            $h .= '<th>' . self::e($label) . '</th>';
        }
        $h .= '</tr>';
        foreach ($rows as $row) {
            $h .= '<tr>';
            if (!empty($row['skipped'])) {
                $h .= '<td>' . self::e((string) $row['codec']) . '</td><td colspan="' . (count($cols) - 1) . '" class="na">Skipped: ' . self::e((string) $row['skipped']) . '</td></tr>';
                continue;
            }
            foreach (array_keys($cols) as $key) {
                $v = $row;
                foreach (explode('.', $key) as $part) {
                    $v = is_array($v) && array_key_exists($part, $v) ? $v[$part] : null;
                }
                if (is_bool($v)) {
                    $h .= '<td>' . ($v ? '<span class="pass">✔ yes</span>' : '<span class="fail">✖ no</span>') . '</td>';
                } elseif ($v === null) {
                    $h .= '<td class="na">—</td>';
                } elseif (is_int($v) || is_float($v)) {
                    $h .= '<td class="num">' . self::num((float) $v, str_ends_with($key, 'bytes')) . '</td>';
                } else {
                    $h .= '<td>' . self::e((string) $v) . '</td>';
                }
            }
            $h .= '</tr>';
        }
        return $h . '</table></div>';
    }

    public static function text(array $r): string
    {
        $out = "\n";
        foreach ($r['criteria'] ?? [] as $c) {
            $out .= sprintf("%-5s %s — %s (target %s)\n", $c['pass'] === null ? 'N/A' : ($c['pass'] ? 'PASS' : 'FAIL'), $c['criterion'], $c['measured'], $c['target']);
        }
        foreach ($r['scenarios']['text']['rows'] ?? [] as $row) {
            if (empty($row['skipped'])) {
                $out .= sprintf("  text  %-10s %6.2f×  %8.1f ms compress  %7.3f s transfer\n", $row['codec'], $row['ratio'], $row['compress_ms'], $row['transfer_s']);
            }
        }
        return $out . sprintf("\nFinished in %ss. Report: reports/latest.html\n", $r['elapsed_s'] ?? '?');
    }

    private static function link(mixed $mbps): string
    {
        return (float) $mbps > 0 ? self::e((string) $mbps) . ' Mbps' : 'unlimited (loopback)';
    }

    public static function num(float $v, bool $bytes = false): string
    {
        if ($bytes) {
            return $v >= 1048576 ? number_format($v / 1048576, 2) . ' MiB' : ($v >= 1024 ? number_format($v / 1024, 1) . ' KiB' : number_format($v) . ' B');
        }
        if (abs($v) >= 1000) {
            return number_format($v, 0);
        }
        if (abs($v) >= 10 || floor($v) == $v) {
            return rtrim(rtrim(number_format($v, 1, '.', ''), '0'), '.');
        }
        return rtrim(rtrim(number_format($v, 2, '.', ''), '0'), '.');
    }

    public static function e(string $s): string
    {
        return htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
    }
}
