<?php

declare(strict_types=1);

/**
 * Network path emulator between Node 1 and Node 2 (all three priority ports).
 *
 *   php bin/netem-proxy.php --listen=9200 --to=9100 [--to-host=127.0.0.1]
 *                           [--delay-ms=40] [--mbps=20] [--max-seconds=N]
 *
 * Node 1 connects to the --listen ports; traffic reaches Node 2 after the
 * one-way delay at the capped rate, and ACKs come back the same way.
 */
require __DIR__ . '/../src/bootstrap.php';

$o = getopt('', ['listen:', 'to:', 'to-host:', 'delay-ms:', 'mbps:', 'max-seconds:']);
$proxy = new NetemProxy((string) ($o['to-host'] ?? '127.0.0.1'), (int) ($o['to'] ?? 9100), (float) ($o['delay-ms'] ?? 40), (float) ($o['mbps'] ?? 0));
try {
    $proxy->listen('127.0.0.1', (int) ($o['listen'] ?? 9200));
} catch (Throwable $e) {
    fwrite(STDERR, $e->getMessage() . "\n");
    exit(2);
}
fwrite(STDOUT, "READY\n");
fflush(STDOUT);
$proxy->run(isset($o['max-seconds']) ? (float) $o['max-seconds'] : INF);
