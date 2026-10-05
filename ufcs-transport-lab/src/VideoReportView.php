<?php

declare(strict_types=1);

/**
 * Renders the video transit report (VideoLab::run()) as one HTML page:
 * findings, the test matrix, then the four reports — compression, transport
 * efficiency, decompression overhead, propagation — each organised as
 * before / during / after. Charts are inline SVG, coloured from theme tokens.
 */
final class VideoReportView
{
    private const CSS = <<<'CSS'
/* Layout: one reading column for prose, full-width cards for tables and charts. */
:root{
  --bg:#f7f8fa;--panel:#ffffff;--ink:#11161d;--ink2:#4a5361;--muted:#7b8494;--line:#dfe3ea;--grid:#eceff4;--code:#f0f2f6;
  --accent:#1c5cab;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#4a3aa7;--good:#0c8a0c;--crit:#c43333;
  --display:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;--body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#14171c;--panel:#1b1f26;--ink:#f1f3f6;--ink2:#c0c6d0;--muted:#8d95a3;--line:#2e3440;--grid:#262b34;--code:#232831;
  --accent:#6da7ec;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#9085e9;--good:#3fbf3f;--crit:#e66767;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#14171c;--panel:#1b1f26;--ink:#f1f3f6;--ink2:#c0c6d0;--muted:#8d95a3;--line:#2e3440;--grid:#262b34;--code:#232831;
  --accent:#6da7ec;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#9085e9;--good:#3fbf3f;--crit:#e66767;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--body)}
.wrap{max-width:1120px;margin:0 auto;padding-inline:16px;padding-block:28px 64px;display:flex;flex-direction:column;gap:14px}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0}
h1{font-size:2.1rem;font-weight:600;letter-spacing:-.01em}
h2{font-size:1.45rem;font-weight:600;margin-top:26px;padding-top:18px;border-top:1px solid var(--line)}
h3{font-size:1.05rem;font-weight:600;margin-top:8px}
.eyebrow{font:600 .75rem/1.2 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.prose{max-width:68ch;color:var(--ink2);margin:0}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;font:.82rem var(--mono);color:var(--muted)}
.tag{font:600 .72rem var(--mono);letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:4px;background:var(--code);color:var(--ink2)}
.tag.before{color:var(--s1)}.tag.during{color:var(--s2)}.tag.after{color:var(--s3)}
.phase{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;min-width:0}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{font:600 .74rem var(--mono);letter-spacing:.03em;color:var(--muted);white-space:nowrap}
td.n,th.n{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
td.k{white-space:nowrap;font-weight:500}
td.w{min-width:15rem;font-size:.8rem;color:var(--ink2)}
.sub{color:var(--muted);font-size:.78rem;display:block}
ul.findings{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px;max-width:92ch}
.ok{color:var(--good);font-weight:600}.bad{color:var(--crit);font-weight:600}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.8rem;color:var(--ink2);margin:2px 0 6px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:10px;height:10px;border-radius:2px;display:inline-block}
svg.chart{display:block;width:100%;height:auto}
svg.chart text{fill:var(--ink2);font:12px var(--body)}
svg.chart text.v{fill:var(--ink);font:600 11.5px var(--mono)}
svg.chart line.g{stroke:var(--grid)}
svg.chart g.m:hover rect,svg.chart g.m:hover circle{opacity:.78}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.kpi b{display:block;font:600 1.45rem var(--display);font-variant-numeric:tabular-nums}
.kpi span{font-size:.8rem;color:var(--ink2)}
code{font-family:var(--mono);font-size:.85em;background:var(--code);padding:1px 4px;border-radius:3px}
CSS;

    /** Full standalone HTML document (local file). */
    public static function page(array $r): string
    {
        return "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            . self::head() . '</head><body>' . self::body($r) . '</body></html>';
    }

    /** Fragment for publishing (the host adds the document skeleton). */
    public static function fragment(array $r): string
    {
        return self::head() . self::body($r);
    }

    private static function head(): string
    {
        return '<title>Video Transit Report</title>'
            . '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            . '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">'
            . '<style>' . self::CSS . '</style>';
    }

    private static function e(mixed $s): string
    {
        return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8');
    }

    private static function n(mixed $v, int $dp = 1): string
    {
        if ($v === null || $v === '') {
            return '—';
        }
        $v = (float) $v;
        if (abs($v) >= 1000) {
            return number_format($v, 0);
        }
        $out = number_format($v, $dp, '.', '');
        return str_contains($out, '.') ? rtrim(rtrim($out, '0'), '.') : $out;
    }

    private static function bytes(mixed $v): string
    {
        $v = (float) $v;
        return $v >= 1048576 ? self::n($v / 1048576, 2) . ' MiB' : ($v >= 1024 ? self::n($v / 1024, 1) . ' KiB' : self::n($v, 0) . ' B');
    }

    private static function path(array $r, string $key): string
    {
        return $r['paths'][$key]['label'] ?? $key;
    }

    private static function name(array $t): string
    {
        return match (true) {
            $t['kind'] === 'VOD' => ucfirst($t['source']) . ' · ' . $t['codec'],
            $t['kind'] === 'HLS', $t['kind'] === 'DASH' => $t['kind'] . ' ladder',
            default => $t['kind'] . (isset($t['mode']) && str_starts_with($t['kind'], 'Direct') ? ($t['mode'] === 'multi' ? ' · 3 conns' : ' · 1 conn') : ''),
        };
    }

    // ------------------------------------------------------------------ body

    private static function body(array $r): string
    {
        $all = array_merge($r['vod'], $r['packages'], $r['sweep'], $r['live']);
        $h = '<main class="wrap">';
        $h .= '<div class="eyebrow">' . self::e($r['lab']) . '</div><h1>Video Transit Report</h1>';
        $h .= '<div class="meta"><span>' . self::e(substr($r['generated_at'], 0, 16)) . ' UTC</span><span>preset ' . self::e($r['config']['preset']) . '</span><span>'
            . count($all) . ' transfers</span><span>' . self::e($r['environment']['cpus'] ?? '?') . ' CPU cores</span><span>run time ' . self::e($r['elapsed_s']) . ' s</span><span>'
            . self::e($r['environment']['ffmpeg']) . '</span></div>';
        $h .= '<p class="prose">Video-on-demand and live video feeds sent from Node 1 to Node 2 as UFCS-FQL/1 frames over TCP, through emulated network paths. Each transfer is measured at three points: <b>before</b> (the source and its encode), <b>during transit</b> (a per-frame trace on both nodes), and <b>after</b> (what Node 2 received, what it costs to decode, and how close it is to the source).</p>';
        $h .= self::kpis($r);
        $h .= '<h2>Key findings</h2><ul class="findings">' . implode('', array_map(fn ($f) => '<li>' . self::e($f) . '</li>', $r['findings'])) . '</ul>';
        $h .= self::matrix($r);
        $h .= self::compression($r);
        $h .= self::efficiency($r);
        $h .= self::decompression($r);
        $h .= self::propagation($r);
        $h .= self::method($r);
        return $h . '</main>';
    }

    private static function kpis(array $r): string
    {
        $vod = array_values(array_filter($r['vod'], fn ($v) => isset($v['after']['quality']['psnr_avg'])));
        $ratios = array_map(fn ($v) => $v['before']['ratio_vs_raw'], $vod);
        $eff = array_filter(array_column(array_column(array_merge($r['vod'], $r['sweep'], $r['packages']), 'during'), 'framing_efficiency_pct'));
        $intact = count(array_filter(array_merge($r['vod'], $r['packages'], $r['sweep'], $r['live']), fn ($t) => $t['after']['intact'] ?? false));
        $total = count($r['vod']) + count($r['packages']) + count($r['sweep']) + count($r['live']);
        $multi = array_values(array_filter($r['live'], fn ($l) => $l['kind'] === 'Direct live' && $l['mode'] === 'multi'))[0] ?? null;
        $single = array_values(array_filter($r['live'], fn ($l) => $l['kind'] === 'Direct live' && $l['mode'] === 'single'))[0] ?? null;
        $k = '<div class="kpis">';
        $k .= '<div class="kpi"><b>' . $intact . ' / ' . $total . '</b><span>transfers arrived bit-exact on Node 2</span></div>';
        if ($ratios) {
            $k .= '<div class="kpi"><b>' . self::n(min($ratios), 0) . '–' . self::n(max($ratios), 0) . '×</b><span>VOD size reduction vs raw video</span></div>';
        }
        if ($eff) {
            $k .= '<div class="kpi"><b>' . self::n(min($eff), 2) . '%</b><span>worst-case framing efficiency (payload ÷ wire)</span></div>';
        }
        if ($multi && $single) {
            $k .= '<div class="kpi"><b>' . self::n($multi['during']['live']['edge_to_node2_ms']['p50'], 0) . ' vs ' . self::n($single['during']['live']['edge_to_node2_ms']['p50'], 0) . ' ms</b><span>live feed edge → Node 2 (p50) beside bulk traffic: 3 connections vs 1</span></div>';
        }
        return $k . '</div>';
    }

    private static function matrix(array $r): string
    {
        $h = '<h2>Test matrix</h2><div class="phase"><span class="tag before">Before</span><span class="prose">Sources are rendered once into lossless FFV1 masters; every encode, live feed and quality comparison reads from the same master.</span></div>';
        $h .= '<div class="card scroll"><table><tr><th>Source</th><th>Content</th><th class="n">Resolution</th><th class="n">Length</th><th class="n">Raw rate</th><th class="n">Raw size</th><th class="n">Lossless master</th><th class="n">SI</th><th class="n">TI</th></tr>';
        foreach ($r['sources'] as $s) {
            $h .= '<tr><td class="k">' . self::e($s['key']) . '</td><td>' . self::e($s['label']) . '</td><td class="n">' . self::e($s['resolution']) . ' @ ' . $s['fps'] . '</td><td class="n">' . self::n($s['seconds']) . ' s</td>'
                . '<td class="n">' . self::n($s['raw_mbps']) . ' Mbps</td><td class="n">' . self::bytes($s['raw_bytes']) . '</td><td class="n">' . self::bytes($s['lossless_master_bytes']) . ' <span class="sub">' . self::n($s['lossless_ratio'], 2) . '× lossless</span></td>'
                . '<td class="n">' . self::n($s['si']) . '</td><td class="n">' . self::n($s['ti']) . '</td></tr>';
        }
        $h .= '</table><p class="prose" style="font-size:.8rem;margin-top:8px">SI / TI: ITU-T P.910 spatial and temporal information. Higher TI means more motion, which costs more bits at the same quality.</p></div>';
        $h .= '<div class="card scroll"><table><tr><th>Path</th><th class="n">Capacity</th><th class="n">One-way delay</th><th class="n">Round trip</th><th>Used for</th></tr>';
        $use = [];
        foreach (array_merge($r['vod'], $r['packages'], $r['sweep'], $r['live']) as $t) {
            $use[$t['path']][self::name($t) . ($t['kind'] === 'VOD' && str_starts_with($t['test'], 'sweep') ? ' (sweep)' : '')] = true;
        }
        foreach ($r['paths'] as $k => $p) {
            if (!isset($use[$k])) {
                continue;
            }
            $h .= '<tr><td class="k">' . self::e(explode(' · ', $p['label'])[0]) . '</td><td class="n">' . self::n($p['mbps'], 0) . ' Mbps</td><td class="n">' . self::n($p['delay_ms']) . ' ms</td><td class="n">' . self::n($p['delay_ms'] * 2) . ' ms</td><td>' . self::e(implode(', ', array_keys($use[$k]))) . '</td></tr>';
        }
        return $h . '</table></div>';
    }

    // ------------------------------------------------------------------ 1. compression

    private static function compression(array $r): string
    {
        $rows = array_merge($r['vod'], $r['packages'], $r['sweep'], array_values(array_filter($r['live'], fn ($l) => $l['mode'] === 'multi' || $l['kind'] === 'RTMP live')));
        $h = '<h2>1 · Compression</h2><p class="prose">What each encode did to the source (before) and how faithful the copy on Node 2 is (after). PSNR and SSIM compare Node 2\'s decoded copy with the lossless master, scaled back to the master\'s resolution. "Actual" is the container bitrate (MPEG-TS, Matroska or FLV), so it includes about 2–4% muxing overhead. SVT-AV1 runs PSNR-tuned while x264 and x265 tune for perceived quality, which lowers their PSNR. Compare SSIM across codecs and PSNR within one codec.</p>';
        $h .= '<div class="phase"><span class="tag before">Before</span><span class="tag after">After</span></div>';
        $h .= '<div class="card scroll"><table><tr><th>Transfer</th><th>Encode</th><th class="n">Output</th><th class="n">Target</th><th class="n">Actual</th><th class="n">vs raw</th><th class="n">vs lossless</th><th class="n">Bits / pixel</th><th class="n">Encode speed</th><th class="n">PSNR</th><th class="n">SSIM</th></tr>';
        foreach ($rows as $t) {
            $b = $t['before'];
            $q = $t['after']['quality'] ?? [];
            $target = $b['plan']['kbps'] ?? (isset($b['top_rung']) ? null : 2500);
            $h .= '<tr><td class="k">' . self::e(self::name($t)) . '<span class="sub">' . self::e(explode(' · ', self::path($r, $t['path']))[0]) . '</span></td><td class="w">' . self::e($b['encode_mode'] ?? ('ladder ' . implode(' / ', array_map(fn ($x) => $x['height'] . 'p@' . $x['kbps'] . 'k', $b['ladder'] ?? [])))) . '</td>'
                . '<td class="n">' . self::e($b['output'] ?? ($b['top_rung'] ?? ($r['sources']['studio']['resolution'] ?? ''))) . '</td><td class="n">' . ($target ? self::n($target, 0) . ' kbps' : 'ladder') . '</td><td class="n">' . self::n($b['actual_kbps'] ?? null, 0) . ' kbps</td>'
                . '<td class="n">' . self::n($b['ratio_vs_raw'] ?? null, 0) . '×</td><td class="n">' . (isset($b['ratio_vs_lossless']) ? self::n($b['ratio_vs_lossless']) . '×' : '—') . '</td>'
                . '<td class="n">' . self::n($b['bits_per_pixel'] ?? null, 3) . '</td><td class="n">' . (isset($b['encode_speed_x']) ? self::n($b['encode_speed_x']) . '× RT' : 'real time') . '</td>'
                . '<td class="n">' . self::n($q['psnr_avg'] ?? null, 2) . ' dB</td><td class="n">' . self::n($q['ssim'] ?? null, 4) . '</td></tr>';
        }
        $h .= '</table></div>';
        $vod = array_values(array_filter($r['vod'], fn ($v) => isset($v['after']['quality']['psnr_avg'])));
        if ($vod) {
            $h .= '<div class="grid2"><div class="card"><h3>Size reduction vs raw video</h3>' . self::legend([['studio', 'var(--s1)'], ['motion', 'var(--s2)']])
                . self::hbars(array_map(fn ($v) => [$v['codec'] . ' · ' . $v['source'], $v['before']['ratio_vs_raw'], $v['source'] === 'studio' ? 'var(--s1)' : 'var(--s2)'], $vod), '×', 0) . '</div>'
                . '<div class="card"><h3>PSNR at the same bitrate (dB)</h3>' . self::legend([['studio', 'var(--s1)'], ['motion', 'var(--s2)']])
                . self::hbars(array_map(fn ($v) => [$v['codec'] . ' · ' . $v['source'], $v['after']['quality']['psnr_avg'], $v['source'] === 'studio' ? 'var(--s1)' : 'var(--s2)'], $vod), ' dB', null) . '</div></div>';
        }
        return $h;
    }

    // ------------------------------------------------------------------ 2. transport efficiency

    private static function efficiency(array $r): string
    {
        $rows = array_merge($r['vod'], $r['packages'], $r['sweep'], $r['live']);
        $h = '<h2>2 · Transport efficiency</h2><p class="prose">How much of what crossed the link was video. Framing efficiency is payload ÷ UFCS-FQL wire bytes (header, meta JSON, CRC). The TCP/IP figure adds a modelled 90 bytes per 1,448-byte segment (IPv4, TCP with timestamps, Ethernet framing). ACK overhead is the bytes Node 2 sent back. Utilisation is wire bytes over the transfer time against the path capacity; Node 1 shapes to 95% of it.</p>';
        $h .= '<div class="phase"><span class="tag during">During</span></div>';
        $h .= '<div class="card scroll"><table><tr><th>Transfer</th><th>Path</th><th class="n">Frames</th><th class="n">Payload</th><th class="n">Wire</th><th class="n">Framing eff.</th><th class="n">With TCP/IP</th><th class="n">ACK overhead</th><th class="n">Goodput</th><th class="n">Utilisation</th><th class="n">RTT</th><th class="n">BDP</th></tr>';
        foreach ($rows as $t) {
            $d = $t['during'];
            $h .= '<tr><td class="k">' . self::e(self::name($t)) . '</td><td>' . self::e(explode(' · ', self::path($r, $t['path']))[0]) . '</td><td class="n">' . self::n($d['frames'], 0) . '</td>'
                . '<td class="n">' . self::bytes($d['payload_bytes']) . '</td><td class="n">' . self::bytes($d['wire_bytes']) . '</td><td class="n">' . self::n($d['framing_efficiency_pct'], 3) . '%</td>'
                . '<td class="n">' . self::n($d['l2_efficiency_pct'], 2) . '%</td><td class="n">' . self::n($d['ack_overhead_pct'], 3) . '%</td><td class="n">' . self::n($d['goodput_mbps'], 2) . ' Mbps</td>'
                . '<td class="n">' . self::n($d['link_utilisation_pct']) . '%</td><td class="n">' . self::n($d['rtt_ms']) . ' ms</td><td class="n">' . self::bytes($d['bdp_bytes']) . '</td></tr>';
        }
        $h .= '</table></div>';
        if ($r['sweep']) {
            $items = [];
            foreach ($r['sweep'] as $s) {
                $items[] = [explode(' · ', self::path($r, $s['path']))[0] . ' · capacity', $s['during']['link_mbps'], 'var(--s4)'];
                $items[] = [explode(' · ', self::path($r, $s['path']))[0] . ' · goodput', $s['during']['goodput_mbps'], 'var(--s1)'];
            }
            $h .= '<div class="card"><h3>Path sweep: goodput against capacity (Mbps, log scale)</h3>'
                . '<p class="prose" style="font-size:.85rem">The same studio clip, encoded for each path. A short VOD file is a burst, so on fast paths the transfer ends before it reaches full speed, and on the LAN path the path emulator (a single PHP process relaying every byte) is itself a ceiling; treat LAN goodput as a lower bound. On constrained paths the shaper at 95% of capacity is the limit.</p>'
                . self::legend([['path capacity', 'var(--s4)'], ['measured goodput', 'var(--s1)']]) . self::hbars($items, ' Mbps', null, true) . '</div>';
        }
        return $h;
    }

    // ------------------------------------------------------------------ 3. decompression overhead

    private static function decompression(array $r): string
    {
        $rows = array_merge($r['vod'], $r['packages'], $r['live']);
        $h = '<h2>3 · Decompression overhead</h2><p class="prose">What Node 2 spends turning frames back into usable video. Transport decode is the time to parse each frame and verify its CRC32, measured inside Node 2 per frame. Media decode is ffmpeg on a single core: speed against real time and CPU seconds per second of video.</p>';
        $h .= '<div class="phase"><span class="tag during">During</span><span class="tag after">After</span></div>';
        $h .= '<div class="card scroll"><table><tr><th>Transfer</th><th class="n">Frames</th><th class="n">Parse + verify p50</th><th class="n">p95</th><th class="n">Verify rate</th><th class="n">Media decode</th><th class="n">CPU per video second</th><th class="n">Decodes</th><th>Repackaging on Node 2</th></tr>';
        foreach ($rows as $t) {
            $d = $t['during'];
            $dec = $t['after']['decode'] ?? [];
            $rep = $t['after']['repackaged'] ?? null;
            $h .= '<tr><td class="k">' . self::e(self::name($t)) . '</td><td class="n">' . self::n($d['frames'], 0) . '</td><td class="n">' . self::n($d['node2_parse_us']['p50'], 0) . ' µs</td><td class="n">' . self::n($d['node2_parse_us']['p95'], 0) . ' µs</td>'
                . '<td class="n">' . self::n($d['node2_verify_mb_s'], 0) . ' MB/s</td><td class="n">' . self::n($dec['realtime_x'] ?? null) . '× RT</td><td class="n">' . self::n(isset($dec['cpu_per_media_s']) ? $dec['cpu_per_media_s'] * 1000 : null, 0) . ' ms</td>'
                . '<td class="n">' . (($dec['ok'] ?? false) ? '<span class="ok">✔ yes</span>' : '<span class="bad">✖ no</span>') . '</td>'
                . '<td>' . ($rep ? 'HLS ' . self::n($rep['hls']['repackage_ms'] ?? null, 0) . ' ms · DASH ' . self::n($rep['dash']['repackage_ms'] ?? null, 0) . ' ms' : '—') . '</td></tr>';
        }
        $h .= '</table></div>';
        $h .= '<div class="card scroll"><h3>Envelope and frame decode (in-process micro-benchmark)</h3><table><tr><th>Operation</th><th class="n">Ratio</th><th class="n">Time</th><th class="n">Throughput</th><th>Note</th></tr>';
        foreach ($r['envelope'] as $e) {
            $h .= '<tr><td class="k">' . self::e($e['codec'] . ($e['ratio'] !== null ? ' (5,000 UFCS facts)' : '')) . '</td><td class="n">' . ($e['ratio'] !== null ? self::n($e['ratio'], 2) . '×' : '—') . '</td><td class="n">' . self::n($e['decode_ms'], 3) . ' ms</td><td class="n">' . self::n($e['mb_s']) . ' MB/s</td><td>' . self::e($e['note']) . '</td></tr>';
        }
        return $h . '</table></div>';
    }

    // ------------------------------------------------------------------ 4. propagation

    private static function propagation(array $r): string
    {
        $rows = array_merge($r['vod'], $r['packages'], $r['sweep'], $r['live']);
        $h = '<h2>4 · Propagation</h2><p class="prose">Where each frame\'s time goes, joined from the two nodes\' traces (same host clock). <b>Queue</b>: enqueued until its first byte left Node 1. <b>Serialisation</b>: first to last byte at the shaped rate. <b>Path</b>: last byte out until Node 2 had the whole frame (propagation delay plus the emulator\'s serialisation). <b>ACK return</b>: Node 2 receipt until Node 1 saw the acknowledgement. VOD files are queued all at once, so their queue time grows through the file; live chunks are queued as the encoder produces them.</p>';
        $h .= '<div class="phase"><span class="tag during">During</span></div>';
        $h .= '<div class="card scroll"><table><tr><th>Transfer</th><th>Path</th><th class="n">Queue p50</th><th class="n">Serialisation p50</th><th class="n">Path p50</th><th class="n">ACK return p50</th><th class="n">Delivery p50</th><th class="n">Delivery p95</th><th class="n">Jitter</th></tr>';
        foreach ($rows as $t) {
            $p = $t['during']['propagation'];
            $h .= '<tr><td class="k">' . self::e(self::name($t)) . '</td><td>' . self::e(explode(' · ', self::path($r, $t['path']))[0]) . '</td><td class="n">' . self::n($p['queue_ms']['p50']) . ' ms</td><td class="n">' . self::n($p['serialisation_ms']['p50']) . ' ms</td>'
                . '<td class="n">' . self::n($p['path_ms']['p50']) . ' ms</td><td class="n">' . self::n($p['ack_return_ms']['p50']) . ' ms</td><td class="n">' . self::n($p['delivery_ms']['p50']) . ' ms</td><td class="n">' . self::n($p['delivery_ms']['p95']) . ' ms</td><td class="n">' . self::n($p['jitter_ms'], 2) . ' ms</td></tr>';
        }
        $h .= '</table></div>';
        // Stacked decomposition for the sweep + live
        $stack = array_merge($r['sweep'], $r['live']);
        if ($stack) {
            $items = array_map(fn ($t) => [self::name($t) . ' · ' . explode(' · ', self::path($r, $t['path']))[0], [
                $t['during']['propagation']['queue_ms']['p50'], $t['during']['propagation']['serialisation_ms']['p50'], $t['during']['propagation']['path_ms']['p50']]], $stack);
            $h .= '<div class="card"><h3>Median delivery time per frame, by stage (ms)</h3>' . self::legend([['queue', 'var(--s1)'], ['serialisation', 'var(--s2)'], ['path', 'var(--s3)']])
                . self::stacked($items, ['var(--s1)', 'var(--s2)', 'var(--s3)'], ['queue', 'serialisation', 'path']) . '</div>';
        }
        // Live
        $h .= '<h3>Live feeds</h3><p class="prose">For live feeds the edge stamps each chunk: when its first and last bytes left the encoder, and when it was flushed onto the transport. <b>Edge → Node 2</b> is last byte at the edge until the chunk was on Node 2. <b>Lag above best</b> tracks whether Node 2 keeps pace with real time: each chunk\'s delay (for RTMP, against its media timestamp) minus the run\'s best chunk. A value that stays low means no backlog builds up.</p>';
        $h .= '<div class="card scroll"><table><tr><th>Feed</th><th>Path</th><th>Connections</th><th class="n">Chunks</th><th class="n">Chunk build</th><th class="n">Flush wait</th><th class="n">Transit p50</th><th class="n">Edge → Node 2 p50</th><th class="n">p95</th><th class="n">Lag above best: start → end</th><th class="n">Worst</th><th>Arrived</th></tr>';
        foreach ($r['live'] as $l) {
            $v = $l['during']['live'];
            $h .= '<tr><td class="k">' . self::e($l['kind']) . '</td><td>' . self::e(explode(' · ', self::path($r, $l['path']))[0]) . '</td><td>' . ($l['mode'] === 'single' ? '1 shared' : '3 (per priority)')
                . (isset($l['during']['competing_bulk_goodput_mbps']) ? '<span class="sub">+ bulk at ' . self::n($l['during']['competing_bulk_goodput_mbps'], 1) . ' Mbps</span>' : '') . '</td>'
                . '<td class="n">' . $v['chunks'] . '</td><td class="n">' . self::n($v['edge_hold_ms']['p50']) . ' ms</td><td class="n">' . self::n($v['flush_wait_ms']['p50']) . ' ms</td><td class="n">' . self::n($v['transport_transit_ms']['p50']) . ' ms</td>'
                . '<td class="n">' . self::n($v['edge_to_node2_ms']['p50']) . ' ms</td><td class="n">' . self::n($v['edge_to_node2_ms']['p95']) . ' ms</td><td class="n">' . self::n($v['lag_start_ms'], 0) . ' → ' . self::n($v['lag_end_ms'], 0) . ' ms</td>'
                . '<td class="n">' . self::n($v['lag_max_ms'], 0) . ' ms' . (isset($v['edge_lag_max_ms']) ? '<span class="sub">' . self::n($v['edge_lag_max_ms'], 0) . ' ms at the edge</span>' : '') . '</td><td>' . (($l['after']['intact'] ?? false) ? '<span class="ok">✔ bit-exact</span>' : '<span class="bad">✖ damaged</span>') . '</td></tr>';
        }
        $h .= '</table></div>';
        $series = [];
        $colors = ['var(--s3)', 'var(--s1)', 'var(--s2)'];
        foreach ($r['live'] as $i => $l) {
            $series[] = [self::name($l) . ' · ' . explode(' · ', self::path($r, $l['path']))[0], $l['during']['live']['series_ms'], $colors[$i % 3]];
        }
        if ($series) {
            $h .= '<div class="card"><h3>Edge → Node 2 per live chunk over the run (ms)</h3>' . self::legend(array_map(fn ($s) => [$s[0], $s[2]], $series)) . self::lines($series) . '</div>';
        }
        return $h;
    }

    private static function method(array $r): string
    {
        return '<h2>Method and limits</h2><ul class="findings">'
            . '<li>Both nodes ran as separate processes on one host (' . self::e($r['environment']['cpus'] ?? '?') . ' cores), so their clocks are shared and one-way times are exact. Paths are emulated by a relay that adds one-way delay and a capacity cap in both directions; it does not drop or reorder data, so loss and retransmission are not measured.</li>'
            . '<li>Sources are synthetic: generated graphics with sensor noise, and a Mandelbrot zoom for high motion. The added noise is not compressible, which keeps PSNR modest at these bitrates; real camera footage usually scores higher at the same rate.</li>'
            . '<li>VOD encodes use ffmpeg with a target bitrate from the link plan (libx264 / libx265 veryfast, SVT-AV1 preset 10). Live encodes use x264 zerolatency at 2.5 Mbps with a 1 s GOP; the RTMP edge flushes every 64 KiB or 200 ms, the direct feed every 100 ms.</li>'
            . '<li>Quality is PSNR (luma and average) and SSIM against the lossless master, frames aligned by index. Live feeds loop the master and are compared over its first pass. Media decode cost is measured single-threaded.</li>'
            . '<li>The TCP/IP overhead column is a model (90 bytes per 1,448-byte segment); everything else is measured.</li></ul>';
    }

    // ------------------------------------------------------------------ charts

    /** @param array<int, array{0:string, 1:string}> $items */
    private static function legend(array $items): string
    {
        return '<div class="legend">' . implode('', array_map(fn ($i) => '<span><i style="background:' . $i[1] . '"></i>' . self::e($i[0]) . '</span>', $items)) . '</div>';
    }

    /** Horizontal bars. $items: [label, value, color]. $floor: axis minimum (null = 0). */
    private static function hbars(array $items, string $unit, ?float $floor, bool $log = false): string
    {
        $lw = 12 + 6.6 * max(array_map(fn ($i) => mb_strlen($i[0]), $items));
        $pw = 330;
        $bh = 15;
        $gap = 7;
        $vals = array_map(fn ($i) => (float) $i[1], $items);
        $lo = $log ? 10 ** floor(log10(max(0.01, min($vals)))) : ($floor ?? 0.0);
        $hi = $log ? 10 ** ceil(log10(max($vals))) : self::niceMax(max($vals));
        $x = fn (float $v) => $log ? $pw * (log10(max($v, $lo)) - log10($lo)) / max(1e-9, log10($hi) - log10($lo)) : $pw * max(0, $v - $lo) / max(1e-9, $hi - $lo);
        $H = count($items) * ($bh + $gap) + 24;
        $W = $lw + $pw + 70;
        $s = '<svg class="chart" viewBox="0 0 ' . round($W) . ' ' . $H . '" style="max-width:' . round($W) . 'px" role="img">';
        $ticks = $log ? array_map(fn ($e) => 10 ** $e, range((int) log10($lo), (int) log10($hi))) : array_map(fn ($i) => $lo + ($hi - $lo) * $i / 4, range(0, 4));
        foreach ($ticks as $t) {
            $tx = round($lw + $x((float) $t), 1);
            $s .= '<line class="g" x1="' . $tx . '" x2="' . $tx . '" y1="0" y2="' . ($H - 20) . '"/><text x="' . $tx . '" y="' . ($H - 5) . '" text-anchor="middle">' . self::n($t) . '</text>';
        }
        foreach ($items as $i => [$label, $v, $c]) {
            $y = $i * ($bh + $gap) + 2;
            $w = max(2.0, $x((float) $v));
            $s .= '<g class="m"><title>' . self::e($label . ': ' . self::n($v, 2) . $unit) . '</title><text x="' . round($lw - 8) . '" y="' . ($y + 11.5) . '" text-anchor="end">' . self::e($label) . '</text>'
                . '<rect x="' . round($lw) . '" y="' . $y . '" width="' . round($w, 1) . '" height="' . $bh . '" rx="3" fill="' . $c . '"/>'
                . '<text class="v" x="' . round($lw + $w + 6, 1) . '" y="' . ($y + 11.5) . '">' . self::n($v, 1) . self::e($unit) . '</text></g>';
        }
        return $s . '</svg>';
    }

    /** Stacked horizontal bars. $items: [label, [v1, v2, v3]]. */
    private static function stacked(array $items, array $colors, array $names): string
    {
        $lw = 12 + 6.6 * max(array_map(fn ($i) => mb_strlen($i[0]), $items));
        $pw = 380;
        $bh = 16;
        $gap = 8;
        $hi = self::niceMax(max(array_map(fn ($i) => array_sum(array_map('floatval', $i[1])), $items)));
        $H = count($items) * ($bh + $gap) + 24;
        $W = $lw + $pw + 80;
        $s = '<svg class="chart" viewBox="0 0 ' . round($W) . ' ' . $H . '" style="max-width:' . round($W) . 'px" role="img">';
        for ($t = 0; $t <= 4; $t++) {
            $tx = round($lw + $pw * $t / 4, 1);
            $s .= '<line class="g" x1="' . $tx . '" x2="' . $tx . '" y1="0" y2="' . ($H - 20) . '"/><text x="' . $tx . '" y="' . ($H - 5) . '" text-anchor="middle">' . self::n($hi * $t / 4) . '</text>';
        }
        foreach ($items as $i => [$label, $vals]) {
            $y = $i * ($bh + $gap) + 2;
            $s .= '<text x="' . round($lw - 8) . '" y="' . ($y + 12) . '" text-anchor="end">' . self::e($label) . '</text>';
            $cx = $lw;
            foreach ($vals as $k => $v) {
                $w = $pw * (float) $v / $hi;
                if ($w < 0.5) {
                    continue;
                }
                $s .= '<g class="m"><title>' . self::e($label . ' — ' . $names[$k] . ': ' . self::n($v, 1) . ' ms') . '</title><rect x="' . round($cx, 1) . '" y="' . $y . '" width="' . round(max(1, $w - 2), 1) . '" height="' . $bh . '" rx="2" fill="' . $colors[$k] . '"/></g>';
                $cx += $w;
            }
            $s .= '<text class="v" x="' . round($cx + 6, 1) . '" y="' . ($y + 12) . '">' . self::n(array_sum(array_map('floatval', $vals)), 0) . ' ms</text>';
        }
        return $s . '</svg>';
    }

    /** Line chart of per-chunk series. $series: [name, values[], color]. */
    private static function lines(array $series): string
    {
        $W = 760;
        $H = 230;
        $l = 52;
        $b = 26;
        $pw = $W - $l - 16;
        $ph = $H - $b - 10;
        $max = 1.0;
        $n = 1;
        foreach ($series as $s) {
            if ($s[1]) {
                $max = max($max, max($s[1]));
                $n = max($n, count($s[1]));
            }
        }
        $hi = self::niceMax($max);
        $svg = '<svg class="chart" viewBox="0 0 ' . $W . ' ' . $H . '" style="max-width:' . $W . 'px" role="img">';
        for ($t = 0; $t <= 4; $t++) {
            $y = round(10 + $ph - $ph * $t / 4, 1);
            $svg .= '<line class="g" x1="' . $l . '" x2="' . ($W - 16) . '" y1="' . $y . '" y2="' . $y . '"/><text x="' . ($l - 6) . '" y="' . ($y + 4) . '" text-anchor="end">' . self::n($hi * $t / 4, 0) . '</text>';
        }
        $svg .= '<text x="' . ($l + $pw / 2) . '" y="' . ($H - 4) . '" text-anchor="middle">chunk number (time →)</text>';
        foreach ($series as [$name, $vals, $c]) {
            if (!$vals) {
                continue;
            }
            $pts = [];
            foreach ($vals as $i => $v) {
                $pts[] = round($l + $pw * $i / max(1, $n - 1), 1) . ',' . round(10 + $ph - $ph * min($v, $hi) / $hi, 1);
            }
            $svg .= '<g class="m"><title>' . self::e($name . ': median ' . self::n(Stats::percentile($vals, 50), 1) . ' ms, max ' . self::n(max($vals), 1) . ' ms') . '</title>'
                . '<polyline fill="none" stroke="' . $c . '" stroke-width="2" stroke-linejoin="round" points="' . implode(' ', $pts) . '"/></g>';
        }
        return $svg . '</svg>';
    }

    private static function niceMax(float $v): float
    {
        if ($v <= 0) {
            return 1.0;
        }
        $p = 10 ** floor(log10($v));
        foreach ([1, 2, 2.5, 5, 10] as $m) {
            if ($m * $p >= $v) {
                return $m * $p;
            }
        }
        return 10 * $p;
    }
}
