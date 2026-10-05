<?php

declare(strict_types=1);

/**
 * Node 2 — the consumer.
 *
 *   stream reader → verifier → decompressor → UFCS/FQL decoder → ingestion pipeline
 *
 * Listens on three ports (base = control, base+1 = normal, base+2 = bulk) and
 * tags every accepted connection with the role of the port it arrived on.
 * One event loop services every connection; each pass reads a bounded slice
 * per connection so a bulk transfer can never starve control traffic on the
 * receiving side either. Every frame that requests it is acknowledged with a
 * CONTROL ACK carrying the advertised window and the current queue depth.
 */
final class Receiver
{
    /** @var array<int, array{sock: resource, priority: int}> */
    private array $listeners = [];
    /** @var array<int, array<string, mixed>> */
    private array $clients = [];
    private bool $stopping = false;
    public FactStore $store;
    /** @var array<string, array<string, mixed>> */
    private array $streams = [];
    /** @var array<string, array<string, mixed>> */
    private array $completed = [];
    /** @var array<string, array<string, mixed>> HLS/DASH packages being rebuilt or finished */
    private array $packages = [];
    /** @var array<string, array<string, mixed>> per-class processing cost */
    private array $cost = [];
    /** @var array<int, array{0:float, 1:float}> message id => [arrival wall time, parse µs] for non-control frames */
    private array $arrivalLog = [];
    private array $stats;
    private int $nextId = 1;
    private float $started;

    /**
     * Options: window (frames in flight per connection), out_dir (write
     * received media), require_signature, verify_media (decode-check completed
     * streams with ffmpeg), read_slice (bytes per connection per pass).
     *
     * @param array<string, mixed> $opts
     */
    public function __construct(private string $host, private int $basePort, private array $opts = [])
    {
        $this->store = new FactStore();
        $this->started = hrtime(true) / 1e9;
        $this->resetStats();
    }

    private function resetStats(): void
    {
        $this->stats = ['by_priority' => [], 'by_content' => [], 'facts' => ['admitted' => 0, 'merged' => 0, 'rejected' => 0],
            'queries' => 0, 'pings' => 0, 'streams_completed' => 0, 'stream_errors' => 0, 'images' => 0, 'mixed_parts' => 0,
            'decode_errors' => 0, 'corrupt_frames' => 0, 'skipped_bytes' => 0];
        foreach (Protocol::PRIORITIES as $name) {
            $this->stats['by_priority'][$name] = ['frames' => 0, 'wire_bytes' => 0, 'payload_bytes' => 0, 'decoded_bytes' => 0];
        }
    }

    public function listen(): void
    {
        foreach ([Protocol::P_CONTROL, Protocol::P_NORMAL, Protocol::P_BULK] as $p) {
            $port = Protocol::portFor($this->basePort, $p);
            $sock = @stream_socket_server('tcp://' . $this->host . ':' . $port, $errno, $errstr);
            if ($sock === false) {
                $this->close();
                throw new RuntimeException('Cannot listen on ' . $this->host . ':' . $port . ' — ' . $errstr);
            }
            stream_set_blocking($sock, false);
            $this->listeners[(int) $sock] = ['sock' => $sock, 'priority' => $p];
        }
    }

    public function stop(): void
    {
        $this->stopping = true;
    }

    /** Run until SHUTDOWN, stop(), or $maxSeconds elapse. */
    public function run(float $maxSeconds = INF): void
    {
        $deadline = hrtime(true) / 1e9 + $maxSeconds;
        while (!$this->stopping || $this->hasPendingWrites()) {
            if (hrtime(true) / 1e9 > $deadline) {
                break;
            }
            $this->tick(0.05);
            if ($this->stopping && !$this->hasPendingWrites()) {
                break;
            }
        }
        $this->close();
    }

    public function tick(float $wait): void
    {
        $read = array_map(fn ($l) => $l['sock'], array_values($this->listeners));
        $write = [];
        foreach ($this->clients as $c) {
            $read[] = $c['sock'];
            if (strlen($c['out']) > 0) {
                $write[] = $c['sock'];
            }
        }
        $except = null;
        $sec = (int) floor($wait);
        if (@stream_select($read, $write, $except, $sec, (int) (($wait - $sec) * 1e6)) === false) {
            return;
        }
        foreach ($read as $sock) {
            if (isset($this->listeners[(int) $sock])) {
                $this->accept($this->listeners[(int) $sock]);
            }
        }
        // Control connections first, then normal, then bulk.
        $order = $this->clients;
        uasort($order, fn ($a, $b) => $a['priority'] <=> $b['priority']);
        foreach (array_keys($order) as $id) {
            if (isset($this->clients[$id]) && in_array($this->clients[$id]['sock'], $read, true)) {
                $this->readClient($id);
            }
        }
        foreach (array_keys($this->clients) as $id) {
            if (strlen($this->clients[$id]['out']) > 0) {
                $this->writeClient($id);
            }
        }
    }

    private function accept(array $listener): void
    {
        $sock = @stream_socket_accept($listener['sock'], 0, $peer);
        if ($sock === false) {
            return;
        }
        Transport::tune($sock);
        stream_set_blocking($sock, false);
        $keyResolver = fn (Frame $f): ?string => isset($f->metaArray()['source_node_id']) ? NodeKeys::forNode((string) $f->metaArray()['source_node_id'])['public'] : null;
        $this->clients[(int) $sock] = [
            'sock' => $sock, 'priority' => $listener['priority'], 'role' => Protocol::PRIORITIES[$listener['priority']],
            'peer' => $peer, 'node' => null, 'out' => '', 'queue' => 0,
            'reader' => new FrameReader($keyResolver, (bool) ($this->opts['require_signature'] ?? false)),
        ];
    }

    private function readClient(int $id): void
    {
        $c = &$this->clients[$id];
        $slice = (int) ($this->opts['read_slice'] ?? 262144);
        $data = @fread($c['sock'], $slice);
        if ($data === false || ($data === '' && feof($c['sock']))) {
            $this->dropClient($id);
            return;
        }
        /** @var FrameReader $reader */
        $reader = $c['reader'];
        $before = [$reader->corruptFrames, $reader->skippedBytes];
        $reader->push($data);
        $frames = [];
        while (true) {
            $t0 = hrtime(true);
            $f = $reader->next(); // parse + CRC32 (+ Ed25519) verification
            if ($f === null) {
                break;
            }
            $f->arrivedAt = microtime(true);
            $f->parseUs = (hrtime(true) - $t0) / 1000;
            if ($f->msgType !== Protocol::CONTROL && count($this->arrivalLog) < 20000) {
                $this->arrivalLog[$f->messageId] = [round($f->arrivedAt, 6), round($f->parseUs, 1)];
            }
            $frames[] = $f;
        }
        $this->stats['corrupt_frames'] += $reader->corruptFrames - $before[0];
        $this->stats['skipped_bytes'] += $reader->skippedBytes - $before[1];
        $c['queue'] = count($frames);
        $acks = [];
        foreach ($frames as $f) {
            $this->clients[$id]['queue']--;
            $t0 = hrtime(true);
            $this->handle($id, $f);
            $this->recordCost($f, (hrtime(true) - $t0) / 1000);
            if ($f->flags & Protocol::F_ACK_REQUESTED) {
                $acks[] = $f->messageId;
            }
        }
        if ($acks && isset($this->clients[$id])) {
            $this->reply($id, Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE,
                ['control' => 'ACK', 'ack' => $acks, 'window' => (int) ($this->opts['window'] ?? 32), 'queue_depth' => $this->clients[$id]['queue']], '');
        }
    }

    private function writeClient(int $id): void
    {
        $c = &$this->clients[$id];
        $n = @fwrite($c['sock'], $c['out']);
        if ($n === false) {
            $this->dropClient($id);
            return;
        }
        $c['out'] = (string) substr($c['out'], $n);
    }

    private function dropClient(int $id): void
    {
        @fclose($this->clients[$id]['sock']);
        unset($this->clients[$id]);
    }

    private function hasPendingWrites(): bool
    {
        foreach ($this->clients as $c) {
            if (strlen($c['out']) > 0) {
                return true;
            }
        }
        return false;
    }

    /** @param array<string, mixed> $meta */
    private function reply(int $clientId, int $msgType, int $content, int $codec, array $meta, string $payload): void
    {
        $priority = $this->clients[$clientId]['priority'];
        $meta['source_node_id'] = (string) ($this->opts['node_id'] ?? 'node-2');
        $f = Frame::make($msgType, $content, $codec, $priority, $meta, $payload, $this->nextId++);
        $this->clients[$clientId]['out'] .= $f->encode();
        $this->writeClient($clientId);
    }

    private function handle(int $clientId, Frame $f): void
    {
        $meta = $f->metaArray();
        $role = Protocol::PRIORITIES[$f->priority()];
        $s = &$this->stats['by_priority'][$role];
        $s['frames']++;
        $s['wire_bytes'] += $f->wireLength();
        $s['payload_bytes'] += strlen($f->payload);
        $ct = Protocol::CONTENT_TYPES[$f->contentType];
        $this->stats['by_content'][$ct] ??= ['frames' => 0, 'payload_bytes' => 0];
        $this->stats['by_content'][$ct]['frames']++;
        $this->stats['by_content'][$ct]['payload_bytes'] += strlen($f->payload);

        try {
            if (isset($meta['package_id'], $meta['path']) && $f->msgType === Protocol::FACT_BATCH) {
                $this->packageFile($meta, Codec::isLossless($f->compression) ? Codec::decompress($f->compression, $f->payload) : $f->payload);
                return;
            }
            switch ($f->msgType) {
                case Protocol::CONTROL:
                    $this->handleControl($clientId, $f, $meta);
                    return;
                case Protocol::STREAM_CHUNK:
                    $this->handleChunk($f, $meta);
                    return;
                default:
                    $decoded = $this->ingest($f->contentType, $f->compression, $f->payload, $meta);
                    $s['decoded_bytes'] += $decoded;
            }
        } catch (Throwable $e) {
            $this->stats['decode_errors']++;
            $this->stats['last_error'] = $e->getMessage();
        }
    }

    /** Ingestion pipeline. Returns the decoded byte count. */
    private function ingest(int $content, int $codec, string $payload, array $meta, string $name = ''): int
    {
        switch ($content) {
            case Protocol::TEXT:
                $jsonl = Codec::decompress($codec, $payload);
                $res = $this->store->ingest(Ufcs::decodeBatch($jsonl));
                foreach ($res as $k => $v) {
                    $this->stats['facts'][$k] += $v;
                }
                return strlen($jsonl);
            case Protocol::MIXED:
                $total = 0;
                foreach (Multipart::decode(Codec::decompress($codec, $payload)) as $part) {
                    $this->stats['mixed_parts']++;
                    $total += $this->ingest($part['content_type'], $part['compression'], $part['bytes'], [], $part['name']);
                }
                return $total;
            default:
                // A single-frame media object (image or short clip).
                if (isset($meta['sha256']) && hash('sha256', $payload) !== $meta['sha256']) {
                    throw new RuntimeException('media object hash mismatch');
                }
                if ($content === Protocol::IMAGE) {
                    $this->stats['images']++;
                }
                $this->storeMedia($name !== '' ? $name : 'object-' . substr(hash('sha256', $payload), 0, 12), $codec, $payload);
                return strlen($payload);
        }
    }

    /** Per-frame cost on Node 2: parse+verify and handling time, per priority class. */
    private function recordCost(Frame $f, float $handleUs): void
    {
        $role = Protocol::PRIORITIES[$f->priority()];
        $c = &$this->cost[$role];
        $c ??= ['frames' => 0, 'bytes' => 0, 'parse_us' => 0.0, 'handle_us' => 0.0, 'parse_samples' => []];
        $c['frames']++;
        $c['bytes'] += $f->wireLength();
        $c['parse_us'] += (float) $f->parseUs;
        $c['handle_us'] += $handleUs;
        if (count($c['parse_samples']) < 20000) {
            $c['parse_samples'][] = (float) $f->parseUs;
        }
    }

    private function handleChunk(Frame $f, array $meta): void
    {
        $sid = (string) ($meta['stream_id'] ?? 'unknown');
        $st = &$this->streams[$sid];
        $st ??= ['bytes' => '', 'next' => 0, 'gaps' => 0, 'chunks' => 0, 'codec' => $f->compression, 'content' => $f->contentType, 'started' => hrtime(true) / 1e9, 'arrivals' => []];
        if (count($st['arrivals']) < 5000) {
            $st['arrivals'][] = array_filter(['id' => $f->messageId, 'seq' => $f->sequence, 'at' => $f->arrivedAt, 'bytes' => strlen($f->payload), 'parse_us' => round((float) $f->parseUs, 1),
                'media_ts_ms' => $meta['media_ts_ms'] ?? null, 'edge_first' => $meta['edge_first'] ?? null, 'edge_last' => $meta['edge_last'] ?? null, 'edge_flush' => $meta['edge_flush'] ?? null], fn ($v) => $v !== null);
        }
        if ($f->sequence !== $st['next']) {
            $st['gaps']++;
        }
        $st['next'] = $f->sequence + 1;
        $st['chunks']++;
        $st['bytes'] .= $f->payload;
        if (($f->flags & Protocol::F_END_OF_STREAM) && isset($meta['package_id'], $meta['path'])) {
            $bytes = $st['bytes'];
            unset($this->streams[$sid]);
            $this->packageFile($meta, $bytes); // hash-checked there
            return;
        }
        if ($f->flags & Protocol::F_END_OF_STREAM) {
            $intact = isset($meta['sha256']) && hash('sha256', $st['bytes']) === $meta['sha256'] && $st['gaps'] === 0;
            $elapsed = hrtime(true) / 1e9 - $st['started'];
            $summary = [
                'stream_id' => $sid, 'codec' => Protocol::compressionName($st['codec']), 'content' => Protocol::CONTENT_TYPES[$st['content']],
                'chunks' => $st['chunks'], 'bytes' => strlen($st['bytes']), 'gaps' => $st['gaps'], 'intact' => $intact,
                'sha256' => hash('sha256', $st['bytes']), 'receive_seconds' => round($elapsed, 3), 'arrivals' => $st['arrivals'],
                'sustained_kbps' => $elapsed > 0 ? round(strlen($st['bytes']) * 8 / 1000 / $elapsed, 1) : null,
            ];
            $ext = ($meta['container'] ?? '') === 'flv' ? '.flv' : MediaCodec::extensionFor($st['codec']);
            if (!empty($this->opts['verify_media'])) {
                $summary['decodes'] = MediaCodec::verifyDecodes($st['bytes'], $ext);
            }
            if (isset($meta['protocol'])) {
                $summary['protocol'] = $meta['protocol'];
            }
            $summary['file'] = $this->storeMedia($sid . $ext, $st['codec'], $st['bytes']);
            if (($meta['container'] ?? '') === 'flv' && $intact && !empty($this->opts['repackage']) && $summary['file'] !== null) {
                $summary['repackaged'] = $this->repackage($sid, $summary['file']);
            }
            $this->completed[$sid] = $summary;
            $this->stats['streams_completed']++;
            if (!$intact) {
                $this->stats['stream_errors']++;
            }
            unset($this->streams[$sid]);
        }
    }

    /** Directory under which Node 2 rebuilds HLS/DASH packages. */
    public function packageRoot(): string
    {
        $dir = (string) ($this->opts['out_dir'] ?? '');
        if ($dir === '') {
            $dir = sys_get_temp_dir() . '/ufcs-node2-' . $this->basePort;
        }
        return rtrim($dir, '/') . '/packages';
    }

    /** Write one package file (hash-checked, path-sanitised); verify the package when complete. */
    private function packageFile(array $meta, string $bytes): void
    {
        $id = (string) $meta['package_id'];
        $path = (string) $meta['path'];
        if (!preg_match('/^[a-z0-9_-]{1,64}$/i', $id) || !StreamPackager::safePath($path)) {
            throw new RuntimeException('unsafe package path refused: ' . $id . '/' . $path);
        }
        if (isset($meta['sha256']) && hash('sha256', $bytes) !== $meta['sha256']) {
            throw new RuntimeException('package file hash mismatch: ' . $path);
        }
        $dir = $this->packageRoot() . '/' . $id;
        $target = $dir . '/' . $path;
        if (!is_dir(dirname($target))) {
            mkdir(dirname($target), 0775, true);
        }
        file_put_contents($target, $bytes);
        $p = &$this->packages[$id];
        $p ??= ['package_id' => $id, 'protocol' => $meta['protocol'] ?? '?', 'root_manifest' => $meta['root_manifest'] ?? '', 'files' => 0,
            'expected' => (int) ($meta['file_count'] ?? 0), 'bytes' => 0, 'complete' => false, 'started' => hrtime(true) / 1e9];
        $p['files']++;
        $p['bytes'] += strlen($bytes);
        if ($p['expected'] > 0 && $p['files'] >= $p['expected']) {
            $check = Manifest::verify($dir, (string) $p['root_manifest']);
            $p = array_merge($p, $check, ['complete' => true, 'dir' => $dir, 'receive_seconds' => round(hrtime(true) / 1e9 - $p['started'], 3)]);
            $this->stats['packages_completed'] = ($this->stats['packages_completed'] ?? 0) + 1;
        }
    }

    /** RTMP-ingested FLV → HLS + DASH on Node 2, stream-copied (no re-encode) when possible. */
    private function repackage(string $sid, string $flv): array
    {
        $out = [];
        $id = preg_replace('/[^a-z0-9_-]/i', '_', $sid);
        foreach (['hls' => 'master.m3u8', 'dash' => 'manifest.mpd'] as $kind => $root) {
            $dir = $this->packageRoot() . '/' . $id . '-' . $kind;
            if (!is_dir($dir)) {
                mkdir($dir, 0775, true);
            }
            $args = $kind === 'hls'
                ? [MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $flv, '-c', 'copy', '-f', 'hls', '-hls_time', '2', '-hls_playlist_type', 'vod',
                    '-hls_segment_filename', $dir . '/seg%03d.ts', $dir . '/index.m3u8']
                : [MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $flv, '-c', 'copy', '-f', 'dash', '-seg_duration', '2',
                    '-init_seg_name', 'init-$RepresentationID$.m4s', '-media_seg_name', 'chunk-$RepresentationID$-$Number%05d$.m4s', $dir . '/manifest.mpd'];
            $t0 = hrtime(true);
            $r = MediaCodec::exec($args);
            $ms = round((hrtime(true) - $t0) / 1e6, 1);
            if ($kind === 'hls' && $r['code'] === 0) {
                $root = 'index.m3u8';
            }
            $check = $r['code'] === 0 ? Manifest::verify($dir, $root) : ['ok' => false, 'missing' => [trim($r['stderr'])], 'segments' => 0, 'variants' => 0, 'duration_s' => 0.0];
            $this->packages[$id . '-' . $kind] = ['package_id' => $id . '-' . $kind, 'protocol' => strtoupper($kind), 'root_manifest' => $root, 'complete' => true,
                'source' => 'rtmp:' . $sid, 'dir' => $dir] + $check;
            $out[$kind] = ['package_id' => $id . '-' . $kind, 'ok' => $check['ok'], 'segments' => $check['segments'], 'repackage_ms' => $ms];
        }
        return $out;
    }

    private function storeMedia(string $name, int $codec, string $bytes): ?string
    {
        $dir = (string) ($this->opts['out_dir'] ?? '');
        if ($dir === '') {
            return null;
        }
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
        $path = rtrim($dir, '/') . '/' . preg_replace('/[^A-Za-z0-9._-]/', '_', $name) . (pathinfo($name, PATHINFO_EXTENSION) === '' ? MediaCodec::extensionFor($codec) : '');
        file_put_contents($path, $bytes);
        return $path;
    }

    private function handleControl(int $clientId, Frame $f, array $meta): void
    {
        switch ((string) ($meta['control'] ?? '')) {
            case 'HELLO':
                $this->clients[$clientId]['node'] = $meta['node_id'] ?? null;
                return;
            case 'PING':
                $this->stats['pings']++;
                return;
            case 'QUERY':
                $this->stats['queries']++;
                try {
                    $q = Fql::parse((string) ($meta['fql'] ?? ''));
                    $hits = $this->store->query($q);
                    $codec = Codec::preferredText();
                    $this->reply($clientId, Protocol::FACT_BATCH, Protocol::TEXT, $codec,
                        ['reply_to' => $f->messageId, 'query_id' => $meta['query_id'] ?? '', 'fql' => $q->render(), 'fact_count' => count($hits)]
                        + Ufcs::batchContext($hits), Codec::compress($codec, Ufcs::encodeBatch($hits)));
                } catch (Throwable $e) {
                    $this->reply($clientId, Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE, ['reply_to' => $f->messageId, 'error' => $e->getMessage()], '');
                }
                return;
            case 'STATS':
                $this->reply($clientId, Protocol::CONTROL, Protocol::TEXT, Protocol::C_GZIP, ['control' => 'STATS', 'reply_to' => $f->messageId],
                    Codec::compress(Protocol::C_GZIP, json_encode($this->snapshot(), JSON_UNESCAPED_SLASHES)));
                return;
            case 'RESET':
                $this->store->clear();
                $this->streams = [];
                $this->completed = [];
                $this->packages = [];
                $this->cost = [];
                $this->arrivalLog = [];
                $this->resetStats();
                return;
            case 'SHUTDOWN':
                $this->stopping = true;
                return;
        }
    }

    /** @return array<string, mixed> */
    public function snapshot(): array
    {
        return $this->stats + [
            'store_facts' => $this->store->count(),
            'rejections' => array_slice($this->store->rejections, -5),
            'streams' => array_values($this->completed),
            'packages' => array_values(array_map(fn ($p) => array_diff_key($p, ['started' => 1]), $this->packages)),
            'package_root' => $this->packageRoot(),
            'open_streams' => count($this->streams),
            'connections' => array_values(array_map(fn ($c) => ['role' => $c['role'], 'peer' => $c['peer'], 'node' => $c['node']], $this->clients)),
            'uptime_s' => round(hrtime(true) / 1e9 - $this->started, 2),
            'cpu_s' => Benchmark::cpuSeconds(),
            'arrival_log' => $this->arrivalLog,
            'cost' => array_map(fn ($c) => ['frames' => $c['frames'], 'bytes' => $c['bytes'], 'parse_us_total' => round($c['parse_us'], 1), 'handle_us_total' => round($c['handle_us'], 1),
                'parse_us' => Stats::summary($c['parse_samples']), 'verify_mb_s' => $c['parse_us'] > 0 ? round($c['bytes'] / $c['parse_us'], 1) : null], $this->cost),
        ];
    }

    public function close(): void
    {
        foreach ($this->clients as $id => $_) {
            $this->dropClient($id);
        }
        foreach ($this->listeners as $l) {
            @fclose($l['sock']);
        }
        $this->listeners = [];
    }
}
