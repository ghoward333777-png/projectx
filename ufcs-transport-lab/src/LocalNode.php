<?php

declare(strict_types=1);

/**
 * Starts Node 2 (bin/receiver.php) as a child process on a free port range
 * so Node 1 can talk to it over real loopback TCP — used by the benchmark,
 * the tests and the dashboard.
 */
final class LocalNode
{
    /** @var resource */
    private $proc;
    /** @var array<int, resource> */
    private array $pipes = [];
    public int $port;

    /** @param array<int, string> $args extra receiver flags */
    public static function start(array $args = [], int $attempts = 8): self
    {
        $last = '';
        for ($i = 0; $i < $attempts; $i++) {
            $port = random_int(20000, 60000);
            $node = new self();
            $cmd = array_merge([PHP_BINARY, __DIR__ . '/../bin/receiver.php', '--port=' . $port], $args);
            $node->proc = proc_open($cmd, [0 => ['file', ufcs_lab_devnull(), 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $node->pipes);
            $line = (string) fgets($node->pipes[1]);
            if (str_starts_with($line, 'READY')) {
                $node->port = $port;
                return $node;
            }
            $last = trim($line . stream_get_contents($node->pipes[2]));
            proc_close($node->proc);
        }
        throw new RuntimeException('Could not start Node 2: ' . $last);
    }

    /** Wait for the receiver to exit (after SHUTDOWN) and return its final stats. */
    public function finish(float $timeout = 10.0): array
    {
        $deadline = microtime(true) + $timeout;
        stream_set_blocking($this->pipes[1], false);
        $out = '';
        while (microtime(true) < $deadline) {
            $out .= (string) stream_get_contents($this->pipes[1]);
            if (!proc_get_status($this->proc)['running']) {
                $out .= (string) stream_get_contents($this->pipes[1]);
                break;
            }
            usleep(20000);
        }
        if (proc_get_status($this->proc)['running']) {
            proc_terminate($this->proc);
        }
        $lines = array_values(array_filter(explode("\n", trim($out))));
        proc_close($this->proc);
        return $lines ? (array) json_decode(end($lines), true) : [];
    }

    public function kill(): void
    {
        if (is_resource($this->proc)) {
            proc_terminate($this->proc);
            proc_close($this->proc);
        }
    }
}
