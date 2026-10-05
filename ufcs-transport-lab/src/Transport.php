<?php

declare(strict_types=1);

/**
 * Token bucket: tokens are bytes. A connection may write only as many bytes
 * as it holds tokens; tokens refill at $rate bytes/second up to $capacity.
 * A rate of 0 means unlimited.
 */
final class TokenBucket
{
    public float $tokens;
    private float $last;
    /** @var callable(): float */
    private $clock;

    public function __construct(public float $capacity, public float $rate, ?callable $clock = null)
    {
        $this->clock = $clock ?? static fn (): float => hrtime(true) / 1e9;
        $this->tokens = $capacity;
        $this->last = ($this->clock)();
    }

    public function unlimited(): bool
    {
        return $this->rate <= 0;
    }

    public function refill(): void
    {
        $now = ($this->clock)();
        if (!$this->unlimited()) {
            $this->tokens = min($this->capacity, $this->tokens + ($now - $this->last) * $this->rate);
        }
        $this->last = $now;
    }

    public function available(): float
    {
        $this->refill();
        return $this->unlimited() ? INF : $this->tokens;
    }

    /** The specification's Allow(): take $bytes if they are all available. */
    public function allow(int $bytes): bool
    {
        if ($this->available() >= $bytes) {
            $this->consume($bytes);
            return true;
        }
        return false;
    }

    public function consume(int $bytes): void
    {
        if (!$this->unlimited()) {
            $this->tokens -= $bytes;
        }
    }

    /** Seconds until $bytes tokens will be available (0 when they already are). */
    public function waitFor(int $bytes): float
    {
        $have = $this->available();
        if ($have >= $bytes) {
            return 0.0;
        }
        return ($min = min($bytes, $this->capacity) - $have) > 0 ? $min / $this->rate : 0.0;
    }
}

/** One TCP connection of Node 1's connection manager (one priority class). */
final class PeerConnection
{
    /** @var resource */
    public $sock;
    public string $out = '';
    public int $outOff = 0;
    public int $written = 0;
    public int $queued = 0;
    public int $window = 32;
    public int $remoteQueueDepth = 0;
    public bool $closed = false;
    /** @var array<int, array{0:string, 1:int, 2:float, 3:int}> frames held back by the window: [wire, msgId, enqueuedAt, priority] */
    public array $backlog = [];
    /** @var array<int, array{end:int, enq:float, wrote:?float, bytes:int}> */
    public array $inflight = [];
    public FrameReader $reader;
    public array $stats = ['frames_sent' => 0, 'bytes_sent' => 0, 'frames_acked' => 0, 'acks' => 0];
    /** @var array<int, float> ack latency samples (ms): enqueue → ACK */
    public array $latencies = [];

    /** @param resource $sock */
    public function __construct($sock, public int $priority, public string $role)
    {
        $this->sock = $sock;
        $this->reader = new FrameReader();
    }

    public function pendingBytes(): int
    {
        return strlen($this->out) - $this->outOff;
    }
}

/**
 * Node 1's transport manager.
 *
 * mode "multi" (default) opens one TCP connection per priority class —
 * control → base port, normal → base+1, bulk → base+2 — and services them in
 * strict priority order when they compete for link tokens. mode "single" puts
 * every frame on one FIFO connection (the baseline that shows head-of-line
 * blocking). Each connection has its own token bucket; an optional shared
 * link bucket models the physical link capacity. The receiver's advertised
 * window caps frames in flight (sent but not yet acknowledged) per connection.
 */
final class Transport
{
    /** @var array<int, PeerConnection> keyed by priority (single mode: every key → same object) */
    private array $conns = [];
    /** @var array<int, TokenBucket> */
    private array $buckets = [];
    private ?TokenBucket $link = null;
    private int $nextId = 1;
    /** @var array<int, Frame> */
    private array $inbox = [];
    private ?string $secretKey = null;
    public string $nodeId;
    public string $mode;
    private int $chunk;
    /** @var array<int, array<int, float>> ACK latency (ms) per frame priority class, any connection */
    private array $classLatency = [0 => [], 1 => [], 2 => []];
    /** @var array<int, int> wire bytes of fully written frames, per frame priority class */
    public array $classBytes = [0 => 0, 1 => 0, 2 => 0];

    /**
     * Options: node_id, mode (multi|single), sign (bool), chunk (write slice bytes),
     * link_bps (shared link capacity, bytes/s, 0 = unlimited),
     * rates [p => bytes/s], capacity [p => bytes], region.
     *
     * @param array<string, mixed> $opts
     */
    public function __construct(private string $host, private int $basePort, private array $opts = [])
    {
        $this->nodeId = (string) ($opts['node_id'] ?? 'node-1');
        $this->mode = (string) ($opts['mode'] ?? 'multi');
        $this->chunk = (int) ($opts['chunk'] ?? 16384);
        if (!empty($opts['sign'])) {
            $this->secretKey = NodeKeys::forNode($this->nodeId)['secret'];
        }
        // Control: small bucket, fast refill. Normal: medium. Bulk: large, slower.
        $rates = ($opts['rates'] ?? []) + [0 => 0, 1 => 0, 2 => 0];
        $caps = ($opts['capacity'] ?? []) + [0 => 65536, 1 => 1048576, 2 => 4194304];
        foreach ([0, 1, 2] as $p) {
            $this->buckets[$p] = new TokenBucket((float) $caps[$p], (float) $rates[$p]);
        }
        $linkBps = (float) ($opts['link_bps'] ?? 0);
        if ($linkBps > 0) {
            $this->link = new TokenBucket(max(16384.0, $linkBps / 50), $linkBps);
        }
    }

    public function connect(float $timeout = 5.0): void
    {
        $roles = $this->mode === 'single' ? [Protocol::P_NORMAL] : [Protocol::P_CONTROL, Protocol::P_NORMAL, Protocol::P_BULK];
        foreach ($roles as $p) {
            $port = Protocol::portFor($this->basePort, $p);
            $sock = @stream_socket_client('tcp://' . $this->host . ':' . $port, $errno, $errstr, $timeout);
            if ($sock === false) {
                throw new RuntimeException('Cannot reach Node 2 at ' . $this->host . ':' . $port . ' — ' . $errstr);
            }
            self::tune($sock);
            stream_set_blocking($sock, false);
            $conn = new PeerConnection($sock, $p, $this->mode === 'single' ? 'shared' : Protocol::PRIORITIES[$p]);
            $this->conns[$p] = $conn;
        }
        if ($this->mode === 'single') {
            $this->conns[Protocol::P_CONTROL] = $this->conns[Protocol::P_BULK] = $this->conns[Protocol::P_NORMAL];
        }
        // HELLO on each physical connection; the ACK carries the receiver's window.
        $ids = [];
        foreach ($this->physical() as $conn) {
            $ids[] = $this->sendOn($conn, Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE, $conn->priority,
                ['control' => 'HELLO', 'node_id' => $this->nodeId, 'role' => $conn->role, 'mode' => $this->mode], '');
        }
        $this->flush($timeout);
    }

    /** @param resource $sock */
    public static function tune($sock): void
    {
        if (function_exists('socket_import_stream') && defined('TCP_NODELAY')) {
            $s = @socket_import_stream($sock);
            if ($s !== false && $s !== null) {
                @socket_set_option($s, SOL_TCP, TCP_NODELAY, 1);
            }
        }
    }

    /** @return array<int, PeerConnection> distinct connections, highest priority first */
    private function physical(): array
    {
        $seen = [];
        foreach ([0, 1, 2] as $p) {
            if (isset($this->conns[$p])) {
                $seen[spl_object_id($this->conns[$p])] = $this->conns[$p];
            }
        }
        return array_values($seen);
    }

    public function nextMessageId(): int
    {
        return $this->nextId++;
    }

    /**
     * Queue a frame. The ConnManager picks the connection from the frame's
     * priority flags. Returns the message id.
     */
    public function send(Frame $f): int
    {
        if ($f->messageId === 0) {
            $f->messageId = $this->nextMessageId();
        }
        $f->flags |= Protocol::F_ACK_REQUESTED;
        $meta = $f->metaArray();
        if (!isset($meta['source_node_id'])) {
            $meta['source_node_id'] = $this->nodeId;
            $meta['source_region'] = (string) ($this->opts['region'] ?? 'lab-local');
            ksort($meta);
            $f->meta = Frame::encodeMeta($meta);
        }
        $conn = $this->conns[$f->priority()] ?? $this->conns[Protocol::P_NORMAL];
        $conn->backlog[] = [$f->encode($this->secretKey), $f->messageId, hrtime(true) / 1e9, $f->priority()];
        return $f->messageId;
    }

    /** @param array<string, mixed> $meta */
    public function sendOn(PeerConnection $conn, int $msgType, int $content, int $codec, int $priority, array $meta, string $payload, int $seq = 0, int $flags = 0): int
    {
        $meta += ['source_node_id' => $this->nodeId, 'source_region' => (string) ($this->opts['region'] ?? 'lab-local')];
        $f = Frame::make($msgType, $content, $codec, $priority, $meta, $payload, $this->nextMessageId(), $seq, $flags);
        $f->flags |= Protocol::F_ACK_REQUESTED;
        $conn->backlog[] = [$f->encode($this->secretKey), $f->messageId, hrtime(true) / 1e9, $priority];
        return $f->messageId;
    }

    /** Bytes queued for a priority's connection but not yet written (backlog + socket buffer). */
    public function queuedBytes(int $priority): int
    {
        $c = $this->conns[$priority] ?? null;
        if ($c === null) {
            return 0;
        }
        $n = $c->pendingBytes();
        foreach ($c->backlog as $b) {
            $n += strlen($b[0]);
        }
        return $n;
    }

    public function idle(): bool
    {
        foreach ($this->physical() as $c) {
            if ($c->backlog || $c->pendingBytes() > 0 || $c->inflight) {
                return false;
            }
        }
        return true;
    }

    /** Run the event loop until every queued frame is written and acknowledged. */
    public function flush(float $timeout = 60.0): bool
    {
        $deadline = hrtime(true) / 1e9 + $timeout;
        while (!$this->idle()) {
            if (hrtime(true) / 1e9 > $deadline) {
                return false;
            }
            $this->pump(0.05);
        }
        return true;
    }

    /** One iteration of the event loop: admit, read ACKs, write within tokens. */
    public function pump(float $maxWait = 0.01): void
    {
        $conns = $this->physical();
        foreach ($conns as $c) {
            while ($c->backlog && count($c->inflight) < $c->window) {
                [$wire, $id, $enq, $p] = array_shift($c->backlog);
                $c->out .= $wire;
                $c->queued += strlen($wire);
                $c->inflight[$id] = ['end' => $c->queued, 'enq' => $enq, 'wrote' => null, 'bytes' => strlen($wire), 'p' => $p];
            }
        }
        $read = [];
        $write = [];
        $wait = $maxWait;
        foreach ($conns as $c) {
            if ($c->closed) {
                continue;
            }
            $read[] = $c->sock;
            if ($c->pendingBytes() > 0) {
                $need = min($c->pendingBytes(), 512);
                $w = max($this->buckets[$c->priority]->waitFor($need), $this->link ? $this->link->waitFor($need) : 0.0);
                if ($w <= 0) {
                    $write[] = $c->sock;
                } else {
                    $wait = min($wait, $w);
                }
            }
        }
        $except = null;
        $sec = (int) floor($wait);
        $usec = (int) (($wait - $sec) * 1e6);
        if (@stream_select($read, $write, $except, $sec, $usec) === false) {
            return;
        }
        foreach ($conns as $c) {
            if (in_array($c->sock, $read, true)) {
                $this->readFrom($c);
            }
        }
        // Strict priority: control spends link tokens before normal, normal before bulk.
        foreach ($conns as $c) {
            if (in_array($c->sock, $write, true)) {
                $this->writeTo($c);
            }
        }
    }

    private function writeTo(PeerConnection $c): void
    {
        $tokens = min($this->buckets[$c->priority]->available(), $this->link ? $this->link->available() : INF);
        $allow = (int) min((float) $this->chunk, (float) $c->pendingBytes(), floor($tokens)); // (int) INF is 0: clamp first
        if ($allow <= 0) {
            return;
        }
        $n = @fwrite($c->sock, substr($c->out, $c->outOff, $allow));
        if ($n === false || $n === 0) {
            return;
        }
        $this->buckets[$c->priority]->consume($n);
        $this->link?->consume($n);
        $c->outOff += $n;
        $c->written += $n;
        $c->stats['bytes_sent'] += $n;
        if ($c->outOff > 1048576 || $c->outOff === strlen($c->out)) {
            $c->out = substr($c->out, $c->outOff);
            $c->outOff = 0;
        }
        $now = hrtime(true) / 1e9;
        foreach ($c->inflight as $id => &$f) {
            if ($f['wrote'] === null && $f['end'] <= $c->written) {
                $f['wrote'] = $now;
                $c->stats['frames_sent']++;
                $this->classBytes[$f['p']] += $f['bytes'];
            }
        }
        unset($f);
    }

    private function readFrom(PeerConnection $c): void
    {
        $data = @fread($c->sock, 262144);
        if ($data === false || ($data === '' && feof($c->sock))) {
            // A peer closing an idle connection (e.g. after SHUTDOWN) is not an error.
            if (!$c->inflight && !$c->backlog && $c->pendingBytes() === 0) {
                $c->closed = true;
                return;
            }
            throw new RuntimeException('Node 2 closed the ' . $c->role . ' connection with ' . count($c->inflight) . ' frame(s) unacknowledged');
        }
        $c->reader->push($data);
        while (($f = $c->reader->next()) !== null) {
            $meta = $f->metaArray();
            if ($f->msgType === Protocol::CONTROL && ($meta['control'] ?? '') === 'ACK') {
                $now = hrtime(true) / 1e9;
                $c->stats['acks']++;
                foreach ((array) ($meta['ack'] ?? []) as $id) {
                    if (isset($c->inflight[$id])) {
                        $ms = ($now - $c->inflight[$id]['enq']) * 1000;
                        $c->latencies[] = $ms;
                        $this->classLatency[$c->inflight[$id]['p']][] = $ms;
                        unset($c->inflight[$id]);
                        $c->stats['frames_acked']++;
                    }
                }
                if (isset($meta['window'])) {
                    $c->window = max(1, (int) $meta['window']);
                }
                $c->remoteQueueDepth = (int) ($meta['queue_depth'] ?? 0);
                continue;
            }
            $this->inbox[] = $f;
        }
    }

    /** Send a frame and wait for the frame whose meta.reply_to names it. */
    public function request(Frame $f, float $timeout = 30.0): Frame
    {
        $id = $this->send($f);
        $deadline = hrtime(true) / 1e9 + $timeout;
        while (true) {
            foreach ($this->inbox as $i => $in) {
                if ((int) ($in->metaArray()['reply_to'] ?? 0) === $id) {
                    unset($this->inbox[$i]);
                    return $in;
                }
            }
            if (hrtime(true) / 1e9 > $deadline) {
                throw new RuntimeException('No reply to message ' . $id . ' within ' . $timeout . 's');
            }
            $this->pump(0.02);
        }
    }

    /** @return array<string, mixed> per-connection transport statistics */
    public function stats(): array
    {
        $out = [];
        foreach ($this->physical() as $c) {
            $out[$c->role] = $c->stats + [
                'window' => $c->window,
                'latency_ms' => Stats::summary($c->latencies),
            ];
        }
        return $out;
    }

    public function resetLatencies(): void
    {
        foreach ($this->physical() as $c) {
            $c->latencies = [];
        }
        $this->classLatency = [0 => [], 1 => [], 2 => []];
        $this->classBytes = [0 => 0, 1 => 0, 2 => 0];
    }

    /** @return array<int, float> ACK latencies (ms) of frames of this priority class */
    public function latencies(int $priority): array
    {
        return $this->classLatency[$priority] ?? [];
    }

    public function close(): void
    {
        foreach ($this->physical() as $c) {
            @fclose($c->sock);
        }
        $this->conns = [];
    }
}

/** Small statistics helpers shared by the transport and the benchmark. */
final class Stats
{
    /** @param array<int, float> $samples */
    public static function percentile(array $samples, float $p): float
    {
        if (!$samples) {
            return 0.0;
        }
        sort($samples);
        $idx = (int) ceil($p / 100 * count($samples)) - 1;
        return (float) $samples[max(0, min(count($samples) - 1, $idx))];
    }

    /** @param array<int, float> $samples */
    public static function summary(array $samples): array
    {
        return [
            'count' => count($samples),
            'p50' => round(self::percentile($samples, 50), 2),
            'p95' => round(self::percentile($samples, 95), 2),
            'max' => round($samples ? max($samples) : 0.0, 2),
            'mean' => round($samples ? array_sum($samples) / count($samples) : 0.0, 2),
        ];
    }
}
