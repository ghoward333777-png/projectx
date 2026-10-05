<?php

declare(strict_types=1);

/**
 * A live encoder feeding the transport directly (no RTMP): ffmpeg encodes a
 * looped master in real time with x264 zerolatency into MPEG-TS on a pipe;
 * Node 1 cuts what arrives into STREAM_CHUNK frames every $flushMs and stamps
 * each with when its first and last bytes left the encoder.
 */
final class LiveFeed
{
    /**
     * @param array<string, mixed> $o seconds, kbps, height, flush_ms, priority, stream_id, tick (callable)
     * @return array<string, mixed>
     */
    public static function run(Transport $t, string $master, array $o): array
    {
        $sec = (float) ($o['seconds'] ?? 15);
        $kbps = (int) ($o['kbps'] ?? 2500);
        $flushMs = (int) ($o['flush_ms'] ?? 100);
        $priority = (int) ($o['priority'] ?? Protocol::P_NORMAL);
        $sid = (string) ($o['stream_id'] ?? 'live-' . bin2hex(random_bytes(3)));
        $args = [MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-re', '-stream_loop', '-1', '-i', $master, '-t', (string) $sec,
            '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency', '-b:v', $kbps . 'k', '-maxrate', (int) ($kbps * 1.1) . 'k', '-bufsize', (int) ($kbps / 2) . 'k',
            '-g', '30', '-pix_fmt', 'yuv420p'];
        if (!empty($o['height'])) {
            $args = array_merge($args, ['-vf', 'scale=-2:' . (int) $o['height']]);
        }
        $args = array_merge($args, ['-c:a', 'aac', '-b:a', '96k', '-f', 'mpegts', '-muxdelay', '0', '-flush_packets', '1', 'pipe:1']);
        $proc = proc_open($args, [0 => ['file', '/dev/null', 'r'], 1 => ['pipe', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
        stream_set_blocking($pipes[1], false);
        $buf = '';
        $first = $last = null;
        $seq = 0;
        $hash = hash_init('sha256');
        $total = 0;
        $lastFlush = microtime(true);
        $started = $lastFlush;
        $send = function (bool $final) use ($t, &$buf, &$first, &$last, &$seq, $hash, &$total, $sid, $priority, $kbps, $flushMs): void {
            $meta = ['stream_id' => $sid, 'protocol' => 'LIVE-TS', 'container' => 'mpegts', 'live' => true, 'reliability' => 'must',
                'latency_target_ms' => 2 * $flushMs, 'target_kbps' => $kbps, 'edge_first' => $first, 'edge_last' => $last, 'edge_flush' => microtime(true)];
            $flags = 0;
            if ($final) {
                $flags = Protocol::F_END_OF_STREAM;
                $meta['sha256'] = hash_final($hash);
                $meta['total_bytes'] = $total;
            }
            $t->send(Frame::make(Protocol::STREAM_CHUNK, Protocol::VIDEO, Protocol::C_H264, $priority, $meta, $buf, 0, $seq++, $flags));
            $buf = '';
            $first = $last = null;
        };
        while (true) {
            $r = [$pipes[1]];
            $w = $e = null;
            @stream_select($r, $w, $e, 0, 2000);
            $data = (string) fread($pipes[1], 262144);
            if ($data !== '') {
                $now = microtime(true);
                $first ??= $now;
                $last = $now;
                $buf .= $data;
                hash_update($hash, $data);
                $total += strlen($data);
            }
            if ($buf !== '' && (microtime(true) - $lastFlush) * 1000 >= $flushMs) {
                $send(false);
                $lastFlush = microtime(true);
            }
            if (isset($o['tick'])) {
                ($o['tick'])();
            }
            $t->pump(0);
            if (feof($pipes[1])) {
                break;
            }
        }
        $send(true);
        fclose($pipes[1]);
        $rc = proc_close($proc);
        $t->flush(60);
        return ['stream_id' => $sid, 'encoder_rc' => $rc, 'chunks' => $seq, 'bytes' => $total, 'seconds' => round(microtime(true) - $started, 3)];
    }
}

/**
 * Video transit test lab: runs video-on-demand and live video feeds between
 * Node 1 and Node 2 through emulated network paths and measures every stage —
 *
 *   BEFORE   source characteristics (raw rate, SI/TI) and the encode
 *   DURING   per-frame trace on both nodes: queueing, serialisation, path,
 *            ACK; framing and modelled TCP/IP overhead; goodput; live lag
 *   AFTER    integrity on Node 2, transport parse/verify cost, media decode
 *            cost, objective quality (PSNR/SSIM) against the source master
 *
 * and turns them into four reports: compression, transport efficiency,
 * decompression overhead, propagation.
 */
final class VideoLab
{
    public const PRESETS = [
        'standard' => ['w' => 1280, 'h' => 720, 'seconds' => 10.0, 'live_seconds' => 15.0, 'codecs' => ['H264', 'H265', 'AV1'],
            'sweep' => ['lan', 'regional', 'long_haul', 'mobile'], 'vod_path' => 'regional'],
        'quick' => ['w' => 640, 'h' => 360, 'seconds' => 4.0, 'live_seconds' => 5.0, 'codecs' => ['H264'],
            'sweep' => ['lan', 'mobile'], 'vod_path' => 'regional'],
    ];

    /** Bytes added per TCP segment below the frame: IPv4 20 + TCP 20 + timestamps 12 + Ethernet 14+4 + preamble/IFG 20. */
    public const L2_OVERHEAD_PER_SEGMENT = 90;
    public const MSS = 1448;

    /** Paths available to the lab (mobile is 3 Mbps here so the ladder visibly adapts). */
    public const PATHS = [
        'lan' => ['delay_ms' => 0.5, 'mbps' => 1000.0, 'label' => 'LAN · 1 Gbps · 0.5 ms'],
        'regional' => ['delay_ms' => 20.0, 'mbps' => 50.0, 'label' => 'Regional · 50 Mbps · 20 ms'],
        'long_haul' => ['delay_ms' => 80.0, 'mbps' => 20.0, 'label' => 'Long-haul · 20 Mbps · 80 ms'],
        'mobile' => ['delay_ms' => 40.0, 'mbps' => 3.0, 'label' => 'Mobile · 3 Mbps · 40 ms'],
    ];

    private array $cfg;
    private string $work;
    private LocalNode $node;
    /** @var callable(string): void */
    private $log;
    /** @var array<string, array<string, mixed>> */
    private array $sources = [];

    public function __construct(array $cfg = [], ?callable $log = null)
    {
        $this->cfg = $cfg + self::PRESETS[$cfg['preset'] ?? 'standard'] + ['preset' => 'standard'];
        $this->log = $log ?? static function (string $m): void {
        };
        $this->work = sys_get_temp_dir() . '/ufcs-videolab-' . bin2hex(random_bytes(4));
        mkdir($this->work, 0775, true);
    }

    public function run(): array
    {
        if (MediaCodec::ffmpeg() === '') {
            throw new RuntimeException('The video lab needs ffmpeg');
        }
        $t0 = microtime(true);
        $this->node = LocalNode::start(['--window=32', '--out=' . $this->work . '/node2', '--repackage']);
        $r = ['lab' => 'QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab', 'title' => 'Video transit report', 'generated_at' => gmdate('c'),
            'config' => $this->cfg, 'paths' => self::PATHS, 'environment' => ['php' => PHP_VERSION, 'cpus' => (int) trim((string) shell_exec('nproc 2>/dev/null')) ?: null,
                'ffmpeg' => trim(explode("\n", (string) shell_exec(escapeshellarg(MediaCodec::ffmpeg()) . ' -version'))[0])]];
        try {
            $r['sources'] = $this->prepareSources();
            $r['vod'] = [];
            foreach (['studio', 'motion'] as $src) {
                foreach ($this->cfg['codecs'] as $codec) {
                    $r['vod'][] = $this->vodTest($src, (string) $codec, (string) $this->cfg['vod_path']);
                }
            }
            $r['packages'] = [$this->packageTest('hls', (string) $this->cfg['vod_path']), $this->packageTest('dash', (string) $this->cfg['vod_path'])];
            $r['sweep'] = [];
            foreach ($this->cfg['sweep'] as $path) {
                $r['sweep'][] = $this->vodTest('studio', 'H264', (string) $path, true);
            }
            $r['live'] = [$this->rtmpLive('regional')];
            foreach (['multi', 'single'] as $mode) {
                $r['live'][] = $this->directLive('long_haul', $mode);
            }
            $r['envelope'] = self::envelopeDecode();
        } finally {
            $this->shutdown();
        }
        $r['elapsed_s'] = round(microtime(true) - $t0, 1);
        $r['findings'] = self::findings($r);
        return $r;
    }

    // ------------------------------------------------------------------ BEFORE

    private function prepareSources(): array
    {
        $w = (int) $this->cfg['w'];
        $h = (int) $this->cfg['h'];
        $sec = (float) $this->cfg['seconds'];
        $defs = [
            'studio' => ['label' => 'Studio graphics (testsrc2 + sensor noise)',
                'v' => "testsrc2=size={$w}x{$h}:rate=30,noise=alls=4:allf=t+u:all_seed=7", 'a' => 'sine=frequency=330:sample_rate=48000'],
            'motion' => ['label' => 'High motion (Mandelbrot zoom + sensor noise)',
                'v' => 'mandelbrot=size=' . intdiv($w, 2) . 'x' . intdiv($h, 2) . ':rate=30:end_scale=0.0005:end_pts=' . (int) ($sec * 30) . ",scale={$w}:{$h}:flags=bicubic,noise=alls=4:allf=t+u:all_seed=9",
                'a' => 'anoisesrc=color=pink:amplitude=0.2:sample_rate=48000'],
        ];
        $out = [];
        foreach ($defs as $key => $d) {
            ($this->log)("before: rendering lossless master '$key'");
            $path = $this->work . '/' . $key . '.mkv';
            $t = microtime(true);
            $r = MediaCodec::exec([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', $d['v'], '-f', 'lavfi', '-i', $d['a'],
                '-t', (string) $sec, '-c:v', 'ffv1', '-level', '3', '-threads', '4', '-slices', '16', '-c:a', 'flac', '-shortest', $path]);
            if ($r['code'] !== 0) {
                throw new RuntimeException('master render failed: ' . $r['stderr']);
            }
            $frames = (int) round($sec * 30);
            $raw = (int) ($w * $h * 1.5 * $frames);
            $siti = MediaCodec::siti($path);
            $out[$key] = ['key' => $key, 'label' => $d['label'], 'resolution' => "{$w}x{$h}", 'fps' => 30, 'seconds' => $sec, 'frames' => $frames,
                'raw_bytes' => $raw, 'raw_mbps' => round($raw * 8 / $sec / 1e6, 1), 'lossless_master_bytes' => filesize($path),
                'lossless_ratio' => round($raw / filesize($path), 2), 'si' => $siti['si'], 'ti' => $siti['ti'], 'render_s' => round(microtime(true) - $t, 1), 'path' => $path];
        }
        $this->sources = $out;
        return array_map(fn ($s) => array_diff_key($s, ['path' => 1]), $out);
    }

    // ------------------------------------------------------------------ transfer + DURING

    /**
     * Connect through an emulated path, run $send, flush, and collect both
     * nodes' traces. Sender shaping at 95% of the path rate keeps the
     * bottleneck queue on Node 1, where priority scheduling happens.
     */
    private function transfer(string $pathKey, string $mode, callable $send): array
    {
        $path = self::PATHS[$pathKey];
        $proxy = PathEmulator::start($this->node->port, $path['delay_ms'], $path['mbps']);
        try {
            $t = new Transport('127.0.0.1', $proxy->port, ['mode' => $mode, 'trace' => true, 'link_bps' => $path['mbps'] * 0.95 * 125000, 'node_id' => 'node-1']);
            $t->connect(10);
            $s = new Sender($t);
            $s->control('RESET');
            for ($i = 0; $i < 5; $i++) {
                $s->ping();
                $t->flush(5);
            }
            $rtt = Stats::summary($t->latencies(Protocol::P_CONTROL));
            $t->resetLatencies();
            $t->trace = [];
            $bytesBack0 = array_sum(array_map(fn ($c) => (int) ($c['bytes_received'] ?? 0), $t->stats()));
            $w0 = microtime(true);
            $result = $send($s, $t);
            $t->flush(300);
            $elapsed = microtime(true) - $w0;
            $remote = $s->remoteStats();
            $bytesBack = array_sum(array_map(fn ($c) => (int) ($c['bytes_received'] ?? 0), $t->stats())) - $bytesBack0;
            $trace = $t->trace;
            $s->control('RESET');
            $t->close();
        } finally {
            $proxy->stop();
        }
        return ['result' => $result, 'remote' => $remote, 'trace' => $trace, 'elapsed' => $elapsed, 'rtt' => $rtt, 'ack_bytes' => $bytesBack, 'path' => $pathKey, 'mode' => $mode];
    }

    /**
     * Transport efficiency + propagation from a transfer.
     *
     * @param null|int $priority count only this class (default: every non-control frame)
     */
    private static function analyse(array $x, ?int $priority = null): array
    {
        $path = self::PATHS[$x['path']];
        $log = $x['remote']['arrival_log'] ?? [];
        $rows = [];
        foreach ($x['trace'] as $id => $f) {
            if ($f['p'] === Protocol::P_CONTROL || !isset($log[$id]) || ($priority !== null && $f['p'] !== $priority)) {
                continue;
            }
            [$at, $parse] = $log[$id];
            $rows[] = $f + ['id' => $id, 'arrive' => (float) $at, 'parse_us' => (float) $parse];
        }
        $wire = array_sum(array_column($rows, 'bytes'));
        $payload = 0;
        foreach ($x['remote']['by_priority'] ?? [] as $name => $cls) {
            if ($priority === null || $name === Protocol::PRIORITIES[$priority]) {
                $payload += (int) $cls['payload_bytes'];
            }
        }
        $segments = (int) ceil($wire / self::MSS);
        $l2 = $wire + $segments * self::L2_OVERHEAD_PER_SEGMENT;
        $span = $rows ? max(array_column($rows, 'arrive')) - min(array_column($rows, 'enq')) : $x['elapsed'];
        $pick = fn (string $a, string $b) => array_values(array_filter(array_map(fn ($r) => isset($r[$a], $r[$b]) && $r[$a] !== null && $r[$b] !== null ? ($r[$b] - $r[$a]) * 1000 : null, $rows), fn ($v) => $v !== null));
        // RFC 3550 interarrival jitter, using first-byte-sent and arrival times in frame order.
        usort($rows, fn ($a, $b) => $a['id'] <=> $b['id']);
        $j = 0.0;
        for ($i = 1; $i < count($rows); $i++) {
            $d = (($rows[$i]['arrive'] - $rows[$i - 1]['arrive']) - (($rows[$i]['first'] ?? 0) - ($rows[$i - 1]['first'] ?? 0))) * 1000;
            $j += (abs($d) - $j) / 16;
        }
        return [
            'frames' => count($rows), 'payload_bytes' => $payload, 'wire_bytes' => $wire,
            'framing_efficiency_pct' => $wire > 0 ? round(100 * min($payload, $wire) / $wire, 3) : null,
            'l2_bytes_modelled' => $l2, 'l2_efficiency_pct' => $l2 > 0 ? round(100 * min($payload, $wire) / $l2, 2) : null,
            'ack_bytes' => $x['ack_bytes'], 'ack_overhead_pct' => $wire > 0 ? round(100 * $x['ack_bytes'] / $wire, 3) : null,
            'transfer_s' => round($span, 3), 'goodput_mbps' => $span > 0 ? round($payload * 8 / $span / 1e6, 2) : null,
            'link_mbps' => $path['mbps'], 'link_utilisation_pct' => $span > 0 ? round(100 * $wire * 8 / $span / ($path['mbps'] * 1e6), 1) : null,
            'rtt_ms' => $x['rtt']['p50'], 'bdp_bytes' => (int) round($path['mbps'] * 1e6 / 8 * $x['rtt']['p50'] / 1000),
            'propagation' => [
                'queue_ms' => Stats::summary($pick('enq', 'first')),
                'serialisation_ms' => Stats::summary($pick('first', 'last')),
                'path_ms' => Stats::summary($pick('last', 'arrive')),
                'ack_return_ms' => Stats::summary($pick('arrive', 'ack')),
                'delivery_ms' => Stats::summary($pick('enq', 'arrive')),
                'jitter_ms' => round($j, 2),
            ],
            'node2_parse_us' => Stats::summary(array_column($rows, 'parse_us')),
            'node2_verify_mb_s' => array_sum(array_column($rows, 'parse_us')) > 0 ? round($wire / array_sum(array_column($rows, 'parse_us')), 1) : null,
        ];
    }

    // ------------------------------------------------------------------ VOD tests

    private function vodTest(string $srcKey, string $codecName, string $pathKey, bool $sweep = false): array
    {
        $src = $this->sources[$srcKey];
        $codec = Protocol::compressionCode($codecName);
        $plan = Benchmark::planVideo((int) $this->cfg['h'], self::PATHS[$pathKey]['mbps']);
        ($this->log)(sprintf('vod: %s %s at %d kbps / %dp over %s', $srcKey, $codecName, $plan['kbps'], $plan['height'], $pathKey));
        // BEFORE: encode
        $enc = MediaCodec::encodeVideo($src['path'], ['codec' => $codec, 'kbps' => $plan['kbps'], 'height' => $plan['downscaled'] ? $plan['height'] : null]);
        $bytes = $enc['bytes'];
        // DURING
        $x = $this->transfer($pathKey, 'multi', fn (Sender $s) => $s->sendMedia($bytes, Protocol::VIDEO, $codec, ['query_id' => "vod-$srcKey", 'entity_ids' => [$srcKey]], Protocol::P_BULK, 65536, true));
        $tr = self::analyse($x);
        // AFTER
        $stream = $x['remote']['streams'][0] ?? [];
        $after = $this->after($stream, $src, $bytes);
        $h = $plan['downscaled'] ? $plan['height'] : (int) $this->cfg['h'];
        $w = (int) round($h * 16 / 9 / 2) * 2;
        return [
            'test' => ($sweep ? 'sweep' : 'vod') . ":$srcKey:$codecName:$pathKey", 'kind' => 'VOD', 'source' => $srcKey, 'codec' => $codecName, 'path' => $pathKey,
            'before' => ['plan' => $plan, 'encode_mode' => $enc['mode'], 'container' => $enc['container'], 'encode_s' => round($enc['encode_ms'] / 1000, 2),
                'encode_speed_x' => round($src['seconds'] / max(0.001, $enc['encode_ms'] / 1000), 1), 'bytes' => strlen($bytes),
                'actual_kbps' => round(strlen($bytes) * 8 / $src['seconds'] / 1000, 1), 'ratio_vs_raw' => round($src['raw_bytes'] / strlen($bytes), 1),
                'ratio_vs_lossless' => round($src['lossless_master_bytes'] / strlen($bytes), 1),
                'bits_per_pixel' => round(strlen($bytes) * 8 / ($w * $h * $src['frames']), 4), 'output' => "{$w}x{$h}"],
            'during' => $tr + ['chunks' => $x['result']['frames'] ?? null],
            'after' => $after,
        ];
    }

    /** Integrity, decode cost and quality on Node 2's received copy. */
    private function after(array $stream, array $src, ?string $sentBytes, bool $loop = false, ?float $seconds = null): array
    {
        $file = (string) ($stream['file'] ?? '');
        $out = ['intact' => (bool) ($stream['intact'] ?? false), 'gaps' => $stream['gaps'] ?? null, 'chunks' => $stream['chunks'] ?? null,
            'sha256_match' => $sentBytes !== null ? (($stream['sha256'] ?? '') === hash('sha256', $sentBytes)) : (bool) ($stream['intact'] ?? false)];
        if ($file === '' || !is_file($file)) {
            return $out + ['error' => 'no file on Node 2'];
        }
        [$w, $h] = array_map('intval', explode('x', $src['resolution']));
        $out['decode'] = MediaCodec::decodeCost($file);
        // Live feeds loop the master; compare only the first pass, where frames align one to one.
        $out['quality'] = MediaCodec::quality($file, $src['path'], $w, $h, $loop ? min((float) $seconds, $src['seconds']) - 0.1 : $seconds);
        $out['quality']['window_s'] = $loop ? round(min((float) $seconds, $src['seconds']) - 0.1, 1) : $src['seconds'];
        if (isset($stream['repackaged'])) {
            $out['repackaged'] = $stream['repackaged'];
        }
        return $out;
    }

    private function packageTest(string $kind, string $pathKey): array
    {
        $src = $this->sources['studio'];
        ($this->log)("vod: $kind package over $pathKey");
        $pkg = StreamPackager::$kind($src['path'], ['link_mbps' => self::PATHS[$pathKey]['mbps'], 'segment_seconds' => 2]);
        $x = $this->transfer($pathKey, 'multi', fn (Sender $s) => $s->sendPackage($pkg, "lab-$kind"));
        $tr = self::analyse($x);
        $p = array_values(array_filter($x['remote']['packages'] ?? [], fn ($q) => $q['package_id'] === "lab-$kind"))[0] ?? [];
        $after = ['intact' => (bool) ($p['ok'] ?? false), 'files' => $p['files'] ?? 0, 'segments' => $p['segments'] ?? 0, 'variants' => $p['variants'] ?? 0];
        if (isset($p['dir'])) {
            $root = $p['dir'] . '/' . $p['root_manifest'];
            [$w, $h] = array_map('intval', explode('x', $src['resolution']));
            $after['decode'] = MediaCodec::decodeCost($root);
            $after['quality'] = MediaCodec::quality($root, $src['path'], $w, $h);
        }
        StreamPackager::removeDir($pkg['dir']);
        $top = $pkg['ladder'][0];
        return ['test' => "package:$kind:$pathKey", 'kind' => strtoupper($kind), 'source' => 'studio', 'codec' => 'H264+AAC', 'path' => $pathKey,
            'before' => ['ladder' => $pkg['ladder'], 'files' => count($pkg['files']), 'segments' => $pkg['segments'], 'bytes' => $pkg['bytes'], 'encode_s' => round($pkg['encode_ms'] / 1000, 2),
                'encode_speed_x' => round($src['seconds'] / max(0.001, $pkg['encode_ms'] / 1000), 1), 'ratio_vs_raw' => round($src['raw_bytes'] / $pkg['bytes'], 1),
                'actual_kbps' => round($pkg['bytes'] * 8 / $src['seconds'] / 1000, 1), 'top_rung' => $top['height'] . 'p@' . $top['kbps'] . 'k'],
            'during' => $tr, 'after' => $after];
    }

    // ------------------------------------------------------------------ live tests

    private function liveEncodeArgs(string $master, float $sec): array
    {
        return ['-stream_loop', '-1', '-i', $master, '-t', (string) $sec, '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
            '-b:v', '2500k', '-maxrate', '2750k', '-bufsize', '1250k', '-g', '30', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '96k'];
    }

    private function rtmpLive(string $pathKey): array
    {
        $src = $this->sources['studio'];
        $sec = (float) $this->cfg['live_seconds'];
        ($this->log)("live: RTMP publish → edge → $pathKey → Node 2 ({$sec}s)");
        $x = $this->transfer($pathKey, 'multi', fn (Sender $s, Transport $t) => RtmpBridge::publishWith($t, $this->liveEncodeArgs($src['path'], $sec), $sec + 60));
        $stream = $x['remote']['streams'][0] ?? [];
        $tr = self::analyse($x);
        $live = self::liveTiming($stream, true);
        $after = $this->after($stream, $src, null, true, $sec);
        return ['test' => "live:rtmp:$pathKey", 'kind' => 'RTMP live', 'source' => 'studio (looped)', 'codec' => 'H264+AAC', 'path' => $pathKey, 'mode' => 'multi',
            'before' => ['encode_mode' => 'x264 veryfast zerolatency, 2500 kbps CBR-capped, GOP 1 s', 'seconds' => $sec, 'bytes' => (int) ($x['result']['stream']['bytes'] ?? 0),
                'actual_kbps' => round(((int) ($x['result']['stream']['bytes'] ?? 0)) * 8 / $sec / 1000, 1), 'ratio_vs_raw' => ($x['result']['stream']['bytes'] ?? 0) > 0 ? round($src['raw_bytes'] / $src['seconds'] * $sec / $x['result']['stream']['bytes'], 1) : null,
                'publisher_rc' => $x['result']['publisher_rc'], 'flv_tags' => $x['result']['stream']['tags'] ?? null],
            'during' => $tr + ['live' => $live], 'after' => $after];
    }

    private function directLive(string $pathKey, string $mode): array
    {
        $src = $this->sources['studio'];
        $sec = (float) $this->cfg['live_seconds'];
        ($this->log)("live: direct MPEG-TS feed over $pathKey with competing bulk ($mode connection mode)");
        $filler = random_bytes(65536 * 16);
        $chunks = str_split($filler, 65536);
        $bulkSeq = 0;
        $x = $this->transfer($pathKey, $mode, function (Sender $s, Transport $t) use ($src, $sec, $chunks, &$bulkSeq) {
            $tick = function () use ($t, $chunks, &$bulkSeq) {
                while ($t->queuedBytes(Protocol::P_BULK) < 1048576) {
                    $t->send(Frame::make(Protocol::STREAM_CHUNK, Protocol::VIDEO, Protocol::C_H264, Protocol::P_BULK, ['stream_id' => 'bulk-backfill', 'reliability' => 'best_effort'],
                        $chunks[$bulkSeq % count($chunks)], 0, $bulkSeq));
                    $bulkSeq++;
                }
            };
            $r = LiveFeed::run($t, $src['path'], ['seconds' => $sec, 'kbps' => 2500, 'flush_ms' => 100, 'priority' => Protocol::P_NORMAL, 'stream_id' => 'live-direct', 'tick' => $tick]);
            return $r;
        });
        $streams = array_column($x['remote']['streams'] ?? [], null, 'stream_id');
        $stream = $streams['live-direct'] ?? [];
        $tr = self::analyse($x, Protocol::P_NORMAL);
        $bulk = self::analyse($x, Protocol::P_BULK);
        $live = self::liveTiming($stream, false);
        $after = $this->after($stream, $src, null, true, $sec);
        return ['test' => "live:direct:$pathKey:$mode", 'kind' => 'Direct live', 'source' => 'studio (looped)', 'codec' => 'H264+AAC', 'path' => $pathKey, 'mode' => $mode,
            'before' => ['encode_mode' => 'x264 veryfast zerolatency, 2500 kbps, GOP 1 s, MPEG-TS on a pipe, 100 ms chunks', 'seconds' => $sec, 'bytes' => (int) ($x['result']['bytes'] ?? 0),
                'actual_kbps' => round(((int) ($x['result']['bytes'] ?? 0)) * 8 / $sec / 1000, 1), 'encoder_rc' => $x['result']['encoder_rc'] ?? null,
                'ratio_vs_raw' => ($x['result']['bytes'] ?? 0) > 0 ? round($src['raw_bytes'] / $src['seconds'] * $sec / $x['result']['bytes'], 1) : null,
                'competing_bulk' => 'background backfill on the bulk class, kept 1 MiB deep'],
            'during' => $tr + ['live' => $live, 'competing_bulk_goodput_mbps' => $bulk['goodput_mbps'] ?? null], 'after' => $after];
    }

    /**
     * Live timing from Node 2's per-chunk arrival log: edge→Node 2 propagation
     * (last byte at the edge → chunk on Node 2), edge hold (chunk building),
     * and lag drift (does Node 2 keep pace with real time?).
     */
    private static function liveTiming(array $stream, bool $hasMediaTs): array
    {
        $arr = $stream['arrivals'] ?? [];
        $prop = [];
        $hold = [];
        $wait = [];
        $transit = [];
        $drift = [];
        $a0 = $m0 = null;
        foreach ($arr as $a) {
            if (isset($a['edge_last'])) {
                $prop[] = ($a['at'] - $a['edge_last']) * 1000;
                $hold[] = ($a['edge_last'] - $a['edge_first']) * 1000;
                if (isset($a['edge_flush'])) {
                    $wait[] = ($a['edge_flush'] - $a['edge_last']) * 1000;
                    $transit[] = ($a['at'] - $a['edge_flush']) * 1000;
                }
            }
            if ($hasMediaTs && isset($a['media_ts_ms'])) {
                $a0 ??= $a['at'];
                $m0 ??= $a['media_ts_ms'];
                $drift[] = (($a['at'] - $a0) * 1000) - ($a['media_ts_ms'] - $m0);
            } elseif (!$hasMediaTs && isset($a['edge_last'])) {
                $drift[] = ($a['at'] - $a['edge_last']) * 1000;
            }
        }
        // Lag is reported above its best (minimum) value: the first chunk includes encoder
        // start-up, so measuring from it would show a spurious negative drift.
        if ($drift) {
            $floor = min($drift);
            $drift = array_map(fn ($d) => $d - $floor, $drift);
        }
        $series = array_map(fn ($a) => isset($a['edge_last']) ? round(($a['at'] - $a['edge_last']) * 1000, 1) : null, $arr);
        return ['chunks' => count($arr), 'edge_to_node2_ms' => Stats::summary($prop), 'edge_hold_ms' => Stats::summary($hold),
            'flush_wait_ms' => Stats::summary($wait), 'transport_transit_ms' => Stats::summary($transit),
            'lag_start_ms' => $drift ? round($drift[0], 1) : null, 'lag_end_ms' => $drift ? round(end($drift), 1) : null, 'lag_max_ms' => $drift ? round(max($drift), 1) : null,
            'series_ms' => array_values(array_filter($series, fn ($v) => $v !== null))];
    }

    // ------------------------------------------------------------------ decompression micro-benchmarks

    /** Lossless envelope decode throughput (fact batches, manifests) and frame parse/verify throughput. */
    public static function envelopeDecode(): array
    {
        $text = Ufcs::encodeBatch(Ufcs::synthesize(5000));
        $rows = [];
        foreach ([Protocol::C_GZIP, Protocol::C_ZSTD, Protocol::C_UFCS_DICT] as $c) {
            if (!Codec::available($c)) {
                continue;
            }
            $z = Codec::compress($c, $text);
            $n = $c === Protocol::C_ZSTD ? 5 : 20;
            $t = hrtime(true);
            for ($i = 0; $i < $n; $i++) {
                Codec::decompress($c, $z);
            }
            $sec = (hrtime(true) - $t) / 1e9 / $n;
            $rows[] = ['codec' => Protocol::compressionName($c), 'ratio' => round(strlen($text) / strlen($z), 2), 'decode_ms' => round($sec * 1000, 2),
                'mb_s' => round(strlen($text) / 1e6 / $sec, 1), 'note' => $c === Protocol::C_ZSTD ? 'includes spawning the zstd CLI per call' : 'in-process'];
        }
        $keys = NodeKeys::forNode('node-1');
        $payload = random_bytes(65536);
        foreach ([false, true] as $signed) {
            $wire = Frame::make(Protocol::STREAM_CHUNK, Protocol::VIDEO, Protocol::C_H264, Protocol::P_BULK, ['stream_id' => 'x', 'source_node_id' => 'node-1'], $payload, 1)->encode($signed ? $keys['secret'] : null);
            $t = hrtime(true);
            for ($i = 0; $i < 200; $i++) {
                $f = Frame::decode($wire, $signed ? $keys['public'] : null);
            }
            $sec = (hrtime(true) - $t) / 1e9 / 200;
            $rows[] = ['codec' => $signed ? 'Frame parse + CRC32 + Ed25519 (64 KiB chunk)' : 'Frame parse + CRC32 (64 KiB chunk)', 'ratio' => null,
                'decode_ms' => round($sec * 1000, 3), 'mb_s' => round(strlen($wire) / 1e6 / $sec, 1), 'note' => 'per frame, in-process'];
        }
        return $rows;
    }

    // ------------------------------------------------------------------ findings

    public static function findings(array $r): array
    {
        $f = [];
        $vod = array_values(array_filter($r['vod'], fn ($v) => isset($v['after']['quality']['psnr_avg'])));
        if ($vod) {
            usort($vod, fn ($a, $b) => $b['before']['ratio_vs_raw'] <=> $a['before']['ratio_vs_raw']);
            $over = array_filter($vod, fn ($v) => $v['before']['actual_kbps'] > $v['before']['plan']['kbps'] * 1.1);
            $f[] = sprintf('Compression: %d of %d encodes landed within 10%% of their %d kbps target (container bitrate)%s. Raw video shrank %s–%s×.',
                count($vod) - count($over), count($vod), $vod[0]['before']['plan']['kbps'],
                $over ? '; over target: ' . implode(', ', array_map(fn ($v) => $v['source'] . ' ' . $v['codec'] . ' at ' . round($v['before']['actual_kbps']) . ' kbps', $over)) . ' (the VBV buffer starts full, which lets a short, complex clip run past the cap, plus about 4% MPEG-TS overhead)' : '',
                min(array_map(fn ($v) => $v['before']['ratio_vs_raw'], $vod)), max(array_map(fn ($v) => $v['before']['ratio_vs_raw'], $vod)));
            foreach (['studio', 'motion'] as $src) {
                $q = array_filter($vod, fn ($v) => $v['source'] === $src);
                if ($q) {
                    $f[] = sprintf('Quality at the same target, %s source: %s. SVT-AV1 runs PSNR-tuned while x264/x265 tune for perceived quality, so compare SSIM across codecs and PSNR within one.',
                        $src, implode('; ', array_map(fn ($v) => $v['codec'] . ' ' . $v['after']['quality']['psnr_avg'] . ' dB PSNR / ' . $v['after']['quality']['ssim'] . ' SSIM', $q)));
                }
            }
        }
        $eff = array_filter(array_merge($r['vod'], $r['packages'], $r['sweep']), fn ($v) => isset($v['during']['framing_efficiency_pct']));
        if ($eff) {
            $f[] = sprintf('Transport efficiency: UFCS-FQL framing kept %s–%s%% of bytes as payload; with modelled TCP/IP + Ethernet overhead %s–%s%%. ACK traffic back was %s–%s%% of the forward bytes.',
                min(array_column(array_column($eff, 'during'), 'framing_efficiency_pct')), max(array_column(array_column($eff, 'during'), 'framing_efficiency_pct')),
                min(array_column(array_column($eff, 'during'), 'l2_efficiency_pct')), max(array_column(array_column($eff, 'during'), 'l2_efficiency_pct')),
                min(array_column(array_column($eff, 'during'), 'ack_overhead_pct')), max(array_column(array_column($eff, 'during'), 'ack_overhead_pct')));
        }
        foreach ($r['sweep'] as $s) {
            $f[] = sprintf('Path %s: %s at %s, goodput %s Mbps (%s%% of the link), chunk delivery p50 %s ms, path transit p50 %s ms.',
                self::PATHS[$s['path']]['label'], $s['before']['output'], $s['before']['plan']['kbps'] . ' kbps', $s['during']['goodput_mbps'], $s['during']['link_utilisation_pct'],
                $s['during']['propagation']['delivery_ms']['p50'], $s['during']['propagation']['path_ms']['p50']);
        }
        $dec = array_filter($r['vod'], fn ($v) => isset($v['after']['decode']['realtime_x']));
        if ($dec) {
            $f[] = 'Decompression: on one CPU core, ' . implode('; ', array_map(fn ($v) => $v['source'] . ' ' . $v['codec'] . ' decodes ' . $v['after']['decode']['realtime_x'] . '× real time', $dec)) . '.';
        }
        foreach ($r['live'] as $l) {
            $f[] = sprintf('%s over %s (%s): edge → Node 2 p50 %s ms / p95 %s ms; lag above its best %s ms at the end (worst %s ms); arrived %s.',
                $l['kind'], self::PATHS[$l['path']]['label'], $l['mode'] === 'single' ? 'one shared connection' : 'per-priority connections',
                $l['during']['live']['edge_to_node2_ms']['p50'], $l['during']['live']['edge_to_node2_ms']['p95'], $l['during']['live']['lag_end_ms'], $l['during']['live']['lag_max_ms'],
                $l['after']['intact'] ? 'intact' : 'NOT intact');
        }
        return $f;
    }

    private function shutdown(): void
    {
        try {
            $t = new Transport('127.0.0.1', $this->node->port);
            $t->connect();
            (new Sender($t))->control('SHUTDOWN');
            $t->close();
            $this->node->finish();
        } catch (Throwable) {
            $this->node->kill();
        }
        if (empty($this->cfg['keep'])) {
            StreamPackager::removeDir($this->work);
        }
    }
}
