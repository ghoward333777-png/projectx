<?php

declare(strict_types=1);

/**
 * Benchmark plan, executable: compression ratio per content type and codec,
 * throughput per priority connection, latency per frame class, CPU on both
 * nodes, and the mixed workload that checks bulk traffic cannot starve
 * control or normal traffic — run with one TCP connection per priority
 * ("multi") and, as the baseline, one shared FIFO connection ("single").
 *
 * Node 2 is a real separate process (LocalNode) on loopback by default, or a
 * remote receiver (`remote` => "host:port") on another machine. A simulated
 * link capacity (token bucket) stands in for the 100 Mbps / 1 Gbps network
 * in the plan; set link_mbps to 0 to run at loopback speed.
 */
final class Benchmark
{
    public const PRESETS = [
        'quick' => ['facts' => 20000, 'batch' => 1000, 'images' => 6, 'image_w' => 1280, 'image_h' => 720,
            'video_w' => 640, 'video_h' => 360, 'video_seconds' => 3.0, 'audio_seconds' => 8.0,
            'link_mbps' => 100.0, 'mixed_link_mbps' => 40.0, 'mixed_seconds' => 3.0, 'video_codecs' => ['H264', 'H265', 'AV1']],
        'full' => ['facts' => 200000, 'batch' => 1000, 'images' => 24, 'image_w' => 1920, 'image_h' => 1080,
            'video_w' => 1280, 'video_h' => 720, 'video_seconds' => 10.0, 'audio_seconds' => 30.0,
            'link_mbps' => 100.0, 'mixed_link_mbps' => 40.0, 'mixed_seconds' => 8.0, 'video_codecs' => ['H264', 'H265', 'AV1']],
        'smoke' => ['facts' => 3000, 'batch' => 1000, 'images' => 2, 'image_w' => 640, 'image_h' => 360,
            'video_w' => 320, 'video_h' => 180, 'video_seconds' => 1.0, 'audio_seconds' => 2.0,
            'link_mbps' => 0.0, 'mixed_link_mbps' => 20.0, 'mixed_seconds' => 2.0, 'video_codecs' => ['H264']],
    ];

    /** Bitrate ladder (height → kbps ceiling) used for resolution/bitrate planning. */
    public const LADDER = [1080 => 4500, 720 => 2500, 540 => 1500, 360 => 800, 240 => 400, 180 => 250];

    /** @var array<string, mixed> */
    private array $cfg;
    private ?LocalNode $node = null;
    private string $host = '127.0.0.1';
    private int $port = 0;
    /** @var callable(string): void */
    private $log;
    private string $work;

    /** @param array<string, mixed> $cfg preset name in 'preset', any preset key overrides it */
    public function __construct(array $cfg = [], ?callable $log = null)
    {
        $preset = self::PRESETS[$cfg['preset'] ?? 'quick'] ?? self::PRESETS['quick'];
        $this->cfg = $cfg + $preset + ['preset' => 'quick', 'remote' => '', 'sign' => false];
        $this->log = $log ?? static function (string $m): void {
        };
        $this->work = sys_get_temp_dir() . '/ufcs-bench-' . bin2hex(random_bytes(4));
        mkdir($this->work, 0775, true);
    }

    public static function cpuSeconds(): float
    {
        $u = getrusage();
        return round($u['ru_utime.tv_sec'] + $u['ru_utime.tv_usec'] / 1e6 + $u['ru_stime.tv_sec'] + $u['ru_stime.tv_usec'] / 1e6, 3);
    }

    /**
     * Plan a video encode for a link: the bitrate ceiling is the smaller of the
     * source rung of the ladder and 80% of the link; if that budget cannot
     * carry the source resolution, step down the ladder (downscale).
     *
     * @return array{height:int, kbps:int, downscaled:bool, reason:string}
     */
    public static function planVideo(int $sourceHeight, float $linkMbps): array
    {
        $rungs = array_filter(self::LADDER, fn ($kbps, $h) => $h <= $sourceHeight, ARRAY_FILTER_USE_BOTH);
        if (!$rungs) {
            $rungs = [$sourceHeight => 250];
        }
        krsort($rungs);
        $budget = $linkMbps > 0 ? MediaCodec::targetVideoKbps((int) ($linkMbps * 1000)) : PHP_INT_MAX;
        foreach ($rungs as $h => $kbps) {
            if ($kbps <= $budget) {
                return ['height' => $h, 'kbps' => $kbps, 'downscaled' => $h < $sourceHeight,
                    'reason' => $h < $sourceHeight ? sprintf('link budget %d kbps < %dp rung; downscaled', $budget, $sourceHeight) : sprintf('%dp rung %d kbps fits link budget', $h, $kbps)];
            }
        }
        $h = (int) array_key_last($rungs);
        return ['height' => $h, 'kbps' => max(150, $budget), 'downscaled' => $h < $sourceHeight, 'reason' => 'link below the lowest rung; bitrate capped at the budget'];
    }

    /** @return array<string, mixed> the full report */
    public function run(): array
    {
        $t0 = microtime(true);
        $report = [
            'lab' => 'QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab',
            'protocol' => Protocol::NAME,
            'generated_at' => gmdate('c'),
            'config' => $this->cfg,
            'environment' => ['php' => PHP_VERSION, 'os' => PHP_OS_FAMILY, 'zstd' => Codec::zstdBinary() !== '', 'ffmpeg' => MediaCodec::ffmpeg() !== '',
                'node2' => $this->cfg['remote'] !== '' ? 'remote ' . $this->cfg['remote'] : 'local process over loopback TCP'],
            'capabilities' => Codec::capabilities(),
            'scenarios' => [],
        ];
        $this->startNode();
        try {
            $report['scenarios']['text'] = $this->scenarioText();
            $report['scenarios']['image'] = $this->scenarioImages();
            $report['scenarios']['video'] = $this->scenarioVideo();
            $report['scenarios']['audio'] = $this->scenarioAudio();
            $report['scenarios']['mixed'] = $this->scenarioMixed();
            $report['scenarios']['streaming'] = $this->scenarioStreaming();
        } finally {
            $this->stopNode();
            $this->cleanup();
        }
        $report['criteria'] = self::criteria($report);
        $report['elapsed_s'] = round(microtime(true) - $t0, 2);
        return $report;
    }

    private function startNode(): void
    {
        if ($this->cfg['remote'] !== '') {
            [$this->host, $port] = explode(':', (string) $this->cfg['remote']) + [1 => '9100'];
            $this->port = (int) $port;
            return;
        }
        $this->node = LocalNode::start(['--window=64', '--verify-media', '--repackage', '--out=' . $this->work . '/node2']);
        $this->port = $this->node->port;
    }

    private function stopNode(): void
    {
        if ($this->node === null) {
            return;
        }
        try {
            $t = $this->connect('multi', 0);
            (new Sender($t))->control('SHUTDOWN');
            $t->close();
            $this->node->finish();
        } catch (Throwable) {
            $this->node->kill();
        }
    }

    private function cleanup(): void
    {
        StreamPackager::removeDir($this->work);
    }

    private function connect(string $mode, float $linkMbps): Transport
    {
        $t = new Transport($this->host, $this->port, ['mode' => $mode, 'link_bps' => $linkMbps * 125000, 'sign' => (bool) $this->cfg['sign'],
            'node_id' => 'node-1', 'region' => 'lab-local', 'chunk' => 16384]);
        $t->connect();
        return $t;
    }

    /** Run $fn against a fresh connection to a freshly reset Node 2; adds timing and CPU. */
    private function measured(string $mode, float $linkMbps, callable $fn): array
    {
        $t = $this->connect($mode, $linkMbps);
        $s = new Sender($t);
        $s->control('RESET');
        $t->resetLatencies();
        $rxCpu0 = (float) ($s->remoteStats()['cpu_s'] ?? 0);
        $cpu0 = self::cpuSeconds();
        $w0 = microtime(true);
        $row = $fn($s, $t);
        $ok = $t->flush(300);
        $row['transfer_s'] = round(microtime(true) - $w0 - ($row['prep_s'] ?? 0), 3);
        $row['sender_cpu_s'] = round(self::cpuSeconds() - $cpu0, 3);
        $remote = $s->remoteStats();
        $row['receiver_cpu_s'] = round((float) ($remote['cpu_s'] ?? 0) - $rxCpu0, 3);
        $row['delivered'] = $ok;
        $row['remote'] = $remote;
        $row['latency_ms'] = Stats::summary(array_merge($t->latencies(0), $t->latencies(1), $t->latencies(2)));
        $t->close();
        return $row;
    }

    // --- Scenario 1: text (UFCS facts), raw vs GZIP vs ZSTD vs UFCS_DICT --------

    private function scenarioText(): array
    {
        $n = (int) $this->cfg['facts'];
        ($this->log)("text: synthesising $n UFCS facts");
        $records = Ufcs::synthesize($n, 1);
        $rows = [];
        foreach ([Protocol::C_NONE, Protocol::C_GZIP, Protocol::C_ZSTD, Protocol::C_UFCS_DICT] as $codec) {
            $name = Protocol::compressionName($codec);
            if (!Codec::available($codec)) {
                $rows[] = ['codec' => $name, 'skipped' => 'unavailable on this node'];
                continue;
            }
            ($this->log)("text: $name");
            $row = $this->measured('multi', (float) $this->cfg['link_mbps'], function (Sender $s) use ($records, $codec) {
                $t = microtime(true);
                $r = $s->sendFacts($records, $codec, (int) $this->cfg['batch']);
                $r['prep_s'] = round(microtime(true) - $t, 3);
                return $r;
            });
            $facts = $row['remote']['facts'] ?? [];
            $rows[] = [
                'codec' => $name, 'facts' => $row['facts'], 'frames' => $row['frames'],
                'raw_bytes' => $row['raw_bytes'], 'payload_bytes' => $row['payload_bytes'], 'wire_bytes' => $row['wire_bytes'],
                'ratio' => round($row['raw_bytes'] / max(1, $row['payload_bytes']), 2),
                'header_overhead_pct' => round(100 * ($row['wire_bytes'] - $row['payload_bytes']) / max(1, $row['wire_bytes']), 3),
                'compress_ms' => $row['compress_ms'], 'transfer_s' => $row['transfer_s'],
                'wire_mb_s' => round($row['wire_bytes'] / 1e6 / max(1e-6, $row['transfer_s']), 2),
                'facts_per_s' => (int) round($row['facts'] / max(1e-6, $row['transfer_s'] + $row['compress_ms'] / 1000)),
                'sender_cpu_s' => $row['sender_cpu_s'], 'receiver_cpu_s' => $row['receiver_cpu_s'],
                'latency_ms' => $row['latency_ms'],
                'verified' => ($facts['rejected'] ?? 1) === 0 && (($facts['admitted'] ?? 0) + ($facts['merged'] ?? 0)) === $n,
                'admitted' => $facts['admitted'] ?? 0, 'merged' => $facts['merged'] ?? 0, 'rejected' => $facts['rejected'] ?? 0,
            ];
        }
        return ['title' => 'Text — UFCS fact batches', 'facts' => $n, 'batch' => (int) $this->cfg['batch'], 'link_mbps' => $this->cfg['link_mbps'], 'rows' => $rows];
    }

    // --- Scenario 2: images, PNG vs WebP ----------------------------------------

    private function scenarioImages(): array
    {
        $count = (int) $this->cfg['images'];
        $images = [];
        for ($i = 1; $i <= $count; $i++) {
            $images[] = MediaCodec::makeTestImage((int) $this->cfg['image_w'], (int) $this->cfg['image_h'], $i);
        }
        $source = array_sum(array_map('strlen', $images));
        $rows = [];
        $variants = [
            ['label' => 'PNG as-is (NONE)', 'codec' => Protocol::C_NONE],
            ['label' => 'WebP q80', 'codec' => Protocol::C_WEBP, 'quality' => 80],
            ['label' => 'WebP q60, max 960px (non-critical)', 'codec' => Protocol::C_WEBP, 'quality' => 60, 'max_width' => 960],
        ];
        foreach ($variants as $v) {
            if ($v['codec'] === Protocol::C_WEBP && !Codec::available(Protocol::C_WEBP)) {
                $rows[] = ['codec' => $v['label'], 'skipped' => 'GD built without WebP'];
                continue;
            }
            ($this->log)('image: ' . $v['label']);
            $encMs = 0.0;
            $encoded = [];
            foreach ($images as $png) {
                if ($v['codec'] === Protocol::C_NONE) {
                    $encoded[] = $png;
                    continue;
                }
                $e = MediaCodec::encodeImage($png, $v);
                $encMs += $e['encode_ms'];
                $encoded[] = $e['bytes'];
            }
            $bytes = array_sum(array_map('strlen', $encoded));
            $row = $this->measured('multi', (float) $this->cfg['link_mbps'], function (Sender $s) use ($encoded, $v) {
                $wire = 0;
                foreach ($encoded as $i => $img) {
                    $wire += $s->sendMedia($img, Protocol::IMAGE, $v['codec'], ['query_id' => 'img-' . $i, 'entity_ids' => ['IMG' . $i]], Protocol::P_BULK)['wire_bytes'];
                }
                return ['wire_bytes' => $wire];
            });
            $rows[] = ['codec' => $v['label'], 'images' => $count, 'source_bytes' => $source, 'payload_bytes' => $bytes, 'wire_bytes' => $row['wire_bytes'],
                'ratio' => round($source / max(1, $bytes), 2), 'encode_ms' => round($encMs, 1), 'transfer_s' => $row['transfer_s'],
                'wire_mb_s' => round($row['wire_bytes'] / 1e6 / max(1e-6, $row['transfer_s']), 2),
                'received' => (int) ($row['remote']['images'] ?? 0), 'decode_errors' => (int) ($row['remote']['decode_errors'] ?? 0),
                'latency_ms' => $row['latency_ms']];
        }
        return ['title' => 'Images — PNG source vs WebP', 'resolution' => $this->cfg['image_w'] . 'x' . $this->cfg['image_h'], 'rows' => $rows];
    }

    // --- Scenario 3: video streaming --------------------------------------------

    private function scenarioVideo(): array
    {
        if (MediaCodec::ffmpeg() === '') {
            return ['title' => 'Video streaming', 'skipped' => 'ffmpeg not installed', 'rows' => []];
        }
        $w = (int) $this->cfg['video_w'];
        $h = (int) $this->cfg['video_h'];
        $sec = (float) $this->cfg['video_seconds'];
        $src = $this->work . '/source.y4m';
        ($this->log)("video: generating {$w}x{$h} {$sec}s raw Y4M source");
        MediaCodec::makeTestVideo($src, $w, $h, $sec);
        $raw = filesize($src);
        $plan = self::planVideo($h, (float) $this->cfg['link_mbps']);
        $rows = [];
        foreach ((array) $this->cfg['video_codecs'] as $name) {
            $codec = Protocol::compressionCode((string) $name);
            if (!Codec::available($codec)) {
                $rows[] = ['codec' => $name, 'skipped' => 'encoder unavailable'];
                continue;
            }
            ($this->log)("video: $name at {$plan['kbps']} kbps");
            $enc = MediaCodec::encodeVideo($src, ['codec' => $codec, 'kbps' => $plan['kbps'], 'height' => $plan['downscaled'] ? $plan['height'] : null]);
            $row = $this->measured('multi', (float) $this->cfg['link_mbps'], fn (Sender $s) => $s->sendMedia($enc['bytes'], Protocol::VIDEO, $codec,
                ['query_id' => 'video-' . strtolower((string) $name), 'entity_ids' => ['VID-1']], Protocol::P_BULK, 65536, true));
            $stream = $row['remote']['streams'][0] ?? [];
            $actualKbps = strlen($enc['bytes']) * 8 / 1000 / $sec;
            $rows[] = ['codec' => $name, 'mode' => $enc['mode'], 'raw_bytes' => $raw, 'payload_bytes' => strlen($enc['bytes']), 'wire_bytes' => $row['wire_bytes'],
                'ratio' => round($raw / max(1, strlen($enc['bytes'])), 1), 'target_kbps' => $plan['kbps'], 'actual_kbps' => round($actualKbps, 1),
                'encode_ms' => $enc['encode_ms'], 'chunks' => $row['frames'], 'transfer_s' => $row['transfer_s'],
                'sustained_kbps' => $stream['sustained_kbps'] ?? null, 'intact' => (bool) ($stream['intact'] ?? false),
                'decodes' => $stream['decodes']['ok'] ?? null, 'chunk_latency_ms' => $row['latency_ms']];
        }
        return ['title' => 'Video — raw Y4M → streamed STREAM_CHUNK frames', 'source' => "{$w}x{$h}, {$sec}s, 30 fps, yuv420p", 'plan' => $plan, 'rows' => $rows];
    }

    // --- Scenario 4: audio --------------------------------------------------------

    private function scenarioAudio(): array
    {
        if (MediaCodec::ffmpeg() === '') {
            return ['title' => 'Audio streaming', 'skipped' => 'ffmpeg not installed', 'rows' => []];
        }
        $sec = (float) $this->cfg['audio_seconds'];
        $src = $this->work . '/source.wav';
        MediaCodec::makeTestAudio($src, $sec);
        $raw = filesize($src);
        $rows = [];
        $variants = [
            ['label' => 'Opus speech (24 kHz mono, 24 kbps)', 'codec' => Protocol::C_OPUS, 'rate' => 24000, 'channels' => 1, 'kbps' => 24],
            ['label' => 'Opus music (48 kHz stereo, 96 kbps)', 'codec' => Protocol::C_OPUS, 'rate' => 48000, 'channels' => 2, 'kbps' => 96],
            ['label' => 'AAC (48 kHz stereo, 128 kbps)', 'codec' => Protocol::C_AAC, 'rate' => 48000, 'channels' => 2, 'kbps' => 128],
        ];
        foreach ($variants as $v) {
            if (!Codec::available($v['codec'])) {
                $rows[] = ['codec' => $v['label'], 'skipped' => 'encoder unavailable'];
                continue;
            }
            ($this->log)('audio: ' . $v['label']);
            $enc = MediaCodec::encodeAudio($src, $v);
            $row = $this->measured('multi', (float) $this->cfg['link_mbps'], fn (Sender $s) => $s->sendMedia($enc['bytes'], Protocol::AUDIO, $v['codec'],
                ['query_id' => 'audio', 'entity_ids' => ['AUD-1']], Protocol::P_BULK, 16384, true));
            $stream = $row['remote']['streams'][0] ?? [];
            $rows[] = ['codec' => $v['label'], 'raw_bytes' => $raw, 'payload_bytes' => strlen($enc['bytes']), 'ratio' => round($raw / max(1, strlen($enc['bytes'])), 1),
                'target_kbps' => $v['kbps'], 'actual_kbps' => round(strlen($enc['bytes']) * 8 / 1000 / $sec, 1), 'encode_ms' => $enc['encode_ms'],
                'chunks' => $row['frames'], 'transfer_s' => $row['transfer_s'], 'intact' => (bool) ($stream['intact'] ?? false),
                'decodes' => $stream['decodes']['ok'] ?? null, 'chunk_latency_ms' => $row['latency_ms']];
        }
        return ['title' => 'Audio — PCM WAV (48 kHz stereo) → streamed', 'source' => "{$sec}s PCM s16 48 kHz stereo", 'rows' => $rows];
    }

    // --- Scenario 5: mixed workload, multi vs single connection -----------------

    private function scenarioMixed(): array
    {
        $bulk = '';
        if (MediaCodec::ffmpeg() !== '' && is_file($this->work . '/source.y4m')) {
            $bulk = MediaCodec::encodeVideo($this->work . '/source.y4m', ['codec' => Protocol::C_H264, 'crf' => 18])['bytes'];
        }
        while (strlen($bulk) < 2097152) {
            $bulk .= hash('sha512', 'bulk' . strlen($bulk), true); // incompressible filler when no ffmpeg
        }
        $facts = Ufcs::synthesize(500, 9);
        $out = ['title' => 'Mixed workload — control + normal + bulk on a constrained link', 'link_mbps' => $this->cfg['mixed_link_mbps'],
            'seconds' => $this->cfg['mixed_seconds'], 'load' => 'ping every 20 ms (control) · 500-fact ZSTD batch every 100 ms (normal) · H.264 chunks kept 1 MB deep (bulk)', 'modes' => []];
        foreach (['multi', 'single'] as $mode) {
            ($this->log)("mixed: $mode connection mode");
            $out['modes'][$mode] = $this->runMixed($mode, $bulk, $facts);
        }
        return $out;
    }

    private function runMixed(string $mode, string $bulk, array $facts): array
    {
        $link = (float) $this->cfg['mixed_link_mbps'];
        $t = $this->connect($mode, $link);
        $s = new Sender($t);
        $s->control('RESET');
        $t->resetLatencies();
        $codec = Codec::preferredText();
        $duration = (float) $this->cfg['mixed_seconds'];
        $chunks = str_split($bulk, 65536);
        $start = microtime(true);
        $nextPing = $start;
        $nextBatch = $start;
        $ci = 0;
        $pings = 0;
        $batches = 0;
        while (($now = microtime(true)) - $start < $duration) {
            if ($now >= $nextPing) {
                $s->ping();
                $pings++;
                $nextPing += 0.02;
            }
            if ($now >= $nextBatch) {
                $s->sendFacts($facts, $codec, 500, Protocol::P_NORMAL, 'mixed-' . $batches);
                $batches++;
                $nextBatch += 0.1;
            }
            while ($t->queuedBytes(Protocol::P_BULK) < 1048576) {
                $f = Frame::make(Protocol::STREAM_CHUNK, Protocol::VIDEO, Protocol::C_H264, Protocol::P_BULK,
                    ['stream_id' => 'mixed-bulk', 'reliability' => 'best_effort'], $chunks[$ci % count($chunks)], 0, $ci);
                $t->send($f);
                $ci++;
            }
            $t->pump(0.002);
        }
        $elapsed = microtime(true) - $start;
        $bytes = $t->classBytes;
        $t->flush(60);
        $result = [
            'connections' => $mode === 'multi' ? 3 : 1,
            'control_latency_ms' => Stats::summary($t->latencies(Protocol::P_CONTROL)),
            'normal_latency_ms' => Stats::summary($t->latencies(Protocol::P_NORMAL)),
            'bulk_latency_ms' => Stats::summary($t->latencies(Protocol::P_BULK)),
            'pings' => $pings, 'fact_batches' => $batches,
            'throughput_mbps' => [
                'control' => round($bytes[0] * 8 / 1e6 / $elapsed, 3),
                'normal' => round($bytes[1] * 8 / 1e6 / $elapsed, 2),
                'bulk' => round($bytes[2] * 8 / 1e6 / $elapsed, 2),
            ],
        ];
        $result['link_utilisation_pct'] = round(100 * array_sum($result['throughput_mbps']) / max(1e-9, $link), 1);
        $t->close();
        return $result;
    }

    // --- Scenario 6: HLS, MPEG-DASH and RTMP ------------------------------------

    private function scenarioStreaming(): array
    {
        if (MediaCodec::ffmpeg() === '') {
            return ['title' => 'Streaming protocols', 'skipped' => 'ffmpeg not installed', 'rows' => []];
        }
        $w = (int) $this->cfg['video_w'];
        $h = (int) $this->cfg['video_h'];
        $sec = max(4.0, (float) $this->cfg['video_seconds']);
        $src = $this->work . '/av-source.mp4';
        ($this->log)("streaming: generating {$w}x{$h} {$sec}s H.264+AAC source");
        MediaCodec::makeTestAv($src, $w, $h, $sec);
        $rows = [];
        foreach (['hls' => 'HLS', 'dash' => 'DASH'] as $kind => $label) {
            ($this->log)("streaming: $label package over UFCS-FQL");
            $pkg = StreamPackager::$kind($src, ['link_mbps' => (float) $this->cfg['link_mbps'], 'segment_seconds' => 2]);
            $row = $this->measured('multi', (float) $this->cfg['link_mbps'], fn (Sender $s) => $s->sendPackage($pkg));
            StreamPackager::removeDir($pkg['dir']);
            $remote = array_values(array_filter($row['remote']['packages'] ?? [], fn ($p) => $p['package_id'] === $row['package_id']))[0] ?? [];
            $play = isset($remote['dir']) ? MediaCodec::verifyPath($remote['dir'] . '/' . $remote['root_manifest']) : null;
            $rows[] = ['protocol' => $label, 'mode' => 'VOD package, ' . count($pkg['ladder']) . '-rung ladder ' . implode(' / ', array_map(fn ($r) => $r['height'] . 'p@' . $r['kbps'], $pkg['ladder'])),
                'files' => $pkg['files'] ? count($pkg['files']) : 0, 'segments' => $pkg['segments'], 'bytes' => $pkg['bytes'], 'package_ms' => $pkg['encode_ms'],
                'overhead_pct' => $row['overhead_pct'], 'transfer_s' => $row['transfer_s'], 'latency_ms' => $row['latency_ms'],
                'rebuilt' => (bool) ($remote['ok'] ?? false), 'plays' => $play['ok'] ?? null, 'detail' => $play['detail'] ?? ($remote['missing'] ?? [])];
        }
        $rows[] = $this->rtmpRun($src);
        return ['title' => 'Streaming protocols — HLS, MPEG-DASH, RTMP over UFCS-FQL', 'source' => "{$w}x{$h}, {$sec}s, H.264 + AAC", 'rows' => $rows];
    }

    /** Publish the source with ffmpeg to the lab's RTMP server, bridge it live to Node 2, check what arrives. */
    private function rtmpRun(string $src): array
    {
        ($this->log)('streaming: RTMP publish → ingest → Node 2');
        $t = $this->connect('multi', (float) $this->cfg['link_mbps']);
        $s = new Sender($t);
        $s->control('RESET');
        $t->resetLatencies();
        $run = RtmpBridge::publishFile($t, $src);
        $rc = $run['publisher_rc'];
        $fin = $run['stream'];
        $remote = $s->remoteStats();
        $stream = $remote['streams'][0] ?? [];
        $rep = $stream['repackaged'] ?? [];
        $row = ['protocol' => 'RTMP', 'mode' => 'live ingest (ffmpeg publisher → PHP RTMP server → bridge) ' . ($fin['video_codec'] ?? '?') . '+' . ($fin['audio_codec'] ?? '?'),
            'files' => 1, 'segments' => (int) ($stream['chunks'] ?? 0), 'bytes' => (int) ($fin['bytes'] ?? 0), 'package_ms' => null, 'overhead_pct' => null,
            'transfer_s' => $run['seconds'], 'latency_ms' => Stats::summary($t->latencies(Protocol::P_BULK)),
            'rebuilt' => (bool) ($stream['intact'] ?? false) && ($rep['hls']['ok'] ?? false) && ($rep['dash']['ok'] ?? false),
            'plays' => $stream['decodes']['ok'] ?? null, 'detail' => 'publisher rc ' . $rc . '; ' . ($fin['tags'] ?? 0) . ' FLV tags; repackaged HLS ' . (($rep['hls']['ok'] ?? false) ? 'ok' : 'FAILED') . ', DASH ' . (($rep['dash']['ok'] ?? false) ? 'ok' : 'FAILED')];
        $t->close();
        return $row;
    }

    // --- Success criteria -----------------------------------------------------------

    /** @return array<int, array{criterion:string, target:string, measured:string, pass:?bool}> */
    public static function criteria(array $r): array
    {
        $c = [];
        $multi = $r['scenarios']['mixed']['modes']['multi'] ?? null;
        $single = $r['scenarios']['mixed']['modes']['single'] ?? null;
        if ($multi) {
            $c[] = ['criterion' => 'Control frames stay fast under bulk load', 'target' => 'median < 50 ms',
                'measured' => $multi['control_latency_ms']['p50'] . ' ms median, ' . $multi['control_latency_ms']['p95'] . ' ms p95', 'pass' => $multi['control_latency_ms']['p50'] < 50];
            $c[] = ['criterion' => 'Normal fact batches stay responsive', 'target' => 'median < 200 ms',
                'measured' => $multi['normal_latency_ms']['p50'] . ' ms median', 'pass' => $multi['normal_latency_ms']['p50'] < 200];
            $c[] = ['criterion' => 'Bulk fills the remaining bandwidth', 'target' => 'link ≥ 80% utilised',
                'measured' => $multi['link_utilisation_pct'] . '% (bulk ' . $multi['throughput_mbps']['bulk'] . ' Mbps)', 'pass' => $multi['link_utilisation_pct'] >= 80];
        }
        if ($multi && $single) {
            $c[] = ['criterion' => 'Per-priority connections beat one shared connection', 'target' => 'control p95 lower than single-connection baseline',
                'measured' => $multi['control_latency_ms']['p95'] . ' ms vs ' . $single['control_latency_ms']['p95'] . ' ms', 'pass' => $multi['control_latency_ms']['p95'] < $single['control_latency_ms']['p95']];
        }
        foreach ($r['scenarios']['text']['rows'] ?? [] as $row) {
            if ($row['codec'] === 'ZSTD' && empty($row['skipped'])) {
                $c[] = ['criterion' => 'Text compresses with Zstd', 'target' => '≥ 3×', 'measured' => $row['ratio'] . '×', 'pass' => $row['ratio'] >= 3];
            }
        }
        foreach ($r['scenarios']['text']['rows'] ?? [] as $row) {
            if (empty($row['skipped'])) {
                $c[] = ['criterion' => 'Every fact re-validates on Node 2 (' . $row['codec'] . ')', 'target' => '0 rejected, all accounted', 'measured' => $row['admitted'] . ' admitted, ' . $row['merged'] . ' merged, ' . $row['rejected'] . ' rejected', 'pass' => $row['verified']];
            }
        }
        foreach ($r['scenarios']['image']['rows'] ?? [] as $row) {
            if ($row['codec'] === 'WebP q80') {
                $c[] = ['criterion' => 'Images compress with WebP', 'target' => '≥ 2×', 'measured' => $row['ratio'] . '×', 'pass' => $row['ratio'] >= 2];
            }
        }
        foreach ($r['scenarios']['streaming']['rows'] ?? [] as $row) {
            $c[] = ['criterion' => $row['protocol'] . ' delivered over UFCS-FQL, rebuilt on Node 2 and playable', 'target' => 'manifest complete, every segment hash-verified, decodes',
                'measured' => ($row['rebuilt'] ? 'rebuilt' : 'NOT rebuilt') . ', ' . ($row['plays'] === null ? 'playback not checked' : ($row['plays'] ? 'plays' : 'DOES NOT PLAY')) . ' — ' . (is_string($row['detail']) ? $row['detail'] : implode(', ', $row['detail'])),
                'pass' => $row['rebuilt'] && $row['plays'] !== false];
        }
        foreach (['video', 'audio'] as $kind) {
            foreach ($r['scenarios'][$kind]['rows'] ?? [] as $row) {
                if (!empty($row['skipped'])) {
                    continue;
                }
                $c[] = ['criterion' => ucfirst($kind) . ' ' . $row['codec'] . ' meets its bitrate target, arrives intact and decodes', 'target' => '≤ 125% of ' . $row['target_kbps'] . ' kbps',
                    'measured' => $row['actual_kbps'] . ' kbps, ' . ($row['intact'] ? 'intact' : 'NOT intact') . ', ' . ($row['decodes'] === null ? 'decode not checked' : ($row['decodes'] ? 'decodes' : 'DOES NOT DECODE')),
                    'pass' => $row['actual_kbps'] <= $row['target_kbps'] * 1.25 && $row['intact'] && $row['decodes'] !== false];
            }
        }
        return $c;
    }
}
