<?php

declare(strict_types=1);

/**
 * Network path emulator: a TCP relay between Node 1 and Node 2 that adds a
 * one-way propagation delay and a bandwidth cap in BOTH directions, on all
 * three priority ports. With it, ACKs take a real round trip, so the
 * receiver window, the bandwidth-delay product and propagation all behave
 * as they would over a WAN. It does not drop or reorder data (TCP would hide
 * loss as retransmission delay anyway); use Linux netem for loss studies.
 *
 * Bytes are serialised at the capped rate (a FIFO per direction per
 * connection, sharing one link bucket per direction), then held for the
 * propagation delay before delivery.
 */
final class NetemProxy
{
    /** @var array<int, array{sock: resource, priority: int}> */
    private array $listeners = [];
    /** @var array<int, array<string, mixed>> pipe id => state */
    private array $pipes = [];
    /** @var array<string, float> per-direction link "busy until" time (serialisation) */
    private array $linkFree = ['up' => 0.0, 'down' => 0.0];
    private bool $stopping = false;

    /**
     * @param float $delayMs one-way propagation delay
     * @param float $mbps    link capacity per direction (0 = unlimited)
     */
    public function __construct(private string $upHost, private int $upBase, private float $delayMs, private float $mbps)
    {
    }

    public function listen(string $host, int $base): void
    {
        foreach ([0, 1, 2] as $p) {
            $s = @stream_socket_server('tcp://' . $host . ':' . ($base + $p), $errno, $errstr);
            if ($s === false) {
                throw new RuntimeException('netem cannot listen on ' . ($base + $p) . ': ' . $errstr);
            }
            stream_set_blocking($s, false);
            $this->listeners[(int) $s] = ['sock' => $s, 'priority' => $p];
        }
    }

    public function run(float $maxSeconds = INF): void
    {
        $deadline = microtime(true) + $maxSeconds;
        while (!$this->stopping && microtime(true) < $deadline) {
            $this->tick();
        }
    }

    private function tick(): void
    {
        $now = microtime(true);
        $read = array_map(fn ($l) => $l['sock'], array_values($this->listeners));
        $wait = 0.05;
        foreach ($this->pipes as $p) {
            $read[] = $p['a'];
            $read[] = $p['b'];
            foreach (['up', 'down'] as $dir) {
                if ($p[$dir]) {
                    $wait = min($wait, max(0.0, $p[$dir][0][0] - $now));
                }
            }
        }
        $w = $e = null;
        if (@stream_select($read, $w, $e, 0, (int) ($wait * 1e6)) === false) {
            return;
        }
        foreach ($read as $sock) {
            if (isset($this->listeners[(int) $sock])) {
                $this->accept($this->listeners[(int) $sock]);
                continue;
            }
            foreach ($this->pipes as $id => $p) {
                if ($sock === $p['a']) {
                    $this->ingest($id, 'up', $p['a']);
                } elseif ($sock === $p['b']) {
                    $this->ingest($id, 'down', $p['b']);
                }
            }
        }
        $now = microtime(true);
        foreach (array_keys($this->pipes) as $id) {
            foreach (['up' => 'b', 'down' => 'a'] as $dir => $to) {
                while (isset($this->pipes[$id]) && $this->pipes[$id][$dir] && $this->pipes[$id][$dir][0][0] <= $now) {
                    [$at, $bytes] = array_shift($this->pipes[$id][$dir]);
                    $this->deliver($id, $to, $bytes);
                }
            }
            if (isset($this->pipes[$id]) && $this->pipes[$id]['closing'] && !$this->pipes[$id]['up'] && !$this->pipes[$id]['down']) {
                $this->close($id);
            }
        }
    }

    private function accept(array $l): void
    {
        $a = @stream_socket_accept($l['sock'], 0);
        if ($a === false) {
            return;
        }
        $b = @stream_socket_client('tcp://' . $this->upHost . ':' . ($this->upBase + $l['priority']), $errno, $errstr, 5);
        if ($b === false) {
            fclose($a);
            return;
        }
        Transport::tune($a);
        Transport::tune($b);
        stream_set_blocking($a, false);
        stream_set_blocking($b, true); // delivery writes complete; the kernel buffer absorbs them
        stream_set_blocking($a, true);
        $this->pipes[(int) $a] = ['a' => $a, 'b' => $b, 'up' => [], 'down' => [], 'closing' => false];
    }

    /** Read what arrived and schedule it: serialisation at the link rate, then propagation. */
    private function ingest(int $id, string $dir, $sock): void
    {
        stream_set_blocking($sock, false);
        $data = @fread($sock, 65536);
        stream_set_blocking($sock, true);
        if ($data === false || ($data === '' && feof($sock))) {
            $this->pipes[$id]['closing'] = true;
            return;
        }
        if ($data === '') {
            return;
        }
        $now = microtime(true);
        $start = max($now, $this->linkFree[$dir]);
        $done = $this->mbps > 0 ? $start + strlen($data) * 8 / ($this->mbps * 1e6) : $now;
        $this->linkFree[$dir] = $done;
        $this->pipes[$id][$dir][] = [$done + $this->delayMs / 1000, $data];
    }

    private function deliver(int $id, string $to, string $bytes): void
    {
        $sock = $this->pipes[$id][$to];
        $off = 0;
        while ($off < strlen($bytes)) {
            $n = @fwrite($sock, substr($bytes, $off));
            if ($n === false || $n === 0) {
                $this->close($id);
                return;
            }
            $off += $n;
        }
    }

    private function close(int $id): void
    {
        @fclose($this->pipes[$id]['a']);
        @fclose($this->pipes[$id]['b']);
        unset($this->pipes[$id]);
    }
}

/** Spawns bin/netem-proxy.php as a child process in front of a Node 2. */
final class PathEmulator
{
    /** Named paths used by the video lab: [one-way delay ms, Mbps]. */
    public const PATHS = [
        'lan' => ['delay_ms' => 0.5, 'mbps' => 1000.0, 'label' => 'LAN (1 Gbps, 0.5 ms)'],
        'regional' => ['delay_ms' => 20.0, 'mbps' => 50.0, 'label' => 'Regional (50 Mbps, 20 ms one-way)'],
        'long_haul' => ['delay_ms' => 80.0, 'mbps' => 20.0, 'label' => 'Long-haul (20 Mbps, 80 ms one-way)'],
        'mobile' => ['delay_ms' => 40.0, 'mbps' => 5.0, 'label' => 'Constrained mobile (5 Mbps, 40 ms one-way)'],
    ];

    /** @var resource */
    private $proc;
    public int $port;

    public static function start(int $node2Port, float $delayMs, float $mbps): self
    {
        $last = '';
        for ($i = 0; $i < 8; $i++) {
            $port = random_int(20000, 60000);
            $self = new self();
            $self->proc = proc_open([PHP_BINARY, __DIR__ . '/../bin/netem-proxy.php', '--listen=' . $port, '--to=' . $node2Port, '--delay-ms=' . $delayMs, '--mbps=' . $mbps],
                [0 => ['file', '/dev/null', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
            $line = (string) fgets($pipes[1]);
            if (str_starts_with($line, 'READY')) {
                $self->port = $port;
                return $self;
            }
            $last = $line . stream_get_contents($pipes[2]);
            proc_terminate($self->proc);
        }
        throw new RuntimeException('netem proxy did not start: ' . $last);
    }

    public function stop(): void
    {
        if (is_resource($this->proc)) {
            proc_terminate($this->proc);
            proc_close($this->proc);
        }
    }
}
