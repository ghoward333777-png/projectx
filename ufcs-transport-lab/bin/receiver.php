<?php

declare(strict_types=1);

/**
 * Node 2 — receiver.
 *
 *   php bin/receiver.php [--host=127.0.0.1] [--port=9100] [--window=32]
 *                        [--out=received/] [--require-signature] [--verify-media]
 *                        [--max-seconds=N]
 *
 * Listens on port (control), port+1 (normal) and port+2 (bulk). Prints
 * "READY <port>" when listening, a JSON stats line when it stops.
 */
require __DIR__ . '/../src/bootstrap.php';

$o = getopt('', ['host:', 'port:', 'window:', 'out:', 'require-signature', 'verify-media', 'repackage', 'max-seconds:', 'node-id:']);
$host = (string) ($o['host'] ?? '127.0.0.1');
$port = (int) ($o['port'] ?? 9100);
$rx = new Receiver($host, $port, [
    'window' => (int) ($o['window'] ?? 32),
    'out_dir' => (string) ($o['out'] ?? ''),
    'require_signature' => isset($o['require-signature']),
    'verify_media' => isset($o['verify-media']),
    'repackage' => isset($o['repackage']),
    'node_id' => (string) ($o['node-id'] ?? 'node-2'),
]);
try {
    $rx->listen();
} catch (Throwable $e) {
    fwrite(STDERR, $e->getMessage() . "\n");
    exit(2);
}
fwrite(STDOUT, "READY $port\n");
fflush(STDOUT);
$rx->run(isset($o['max-seconds']) ? (float) $o['max-seconds'] : INF);
$snap = $rx->snapshot();
unset($snap['connections']);
fwrite(STDOUT, json_encode($snap, JSON_UNESCAPED_SLASHES) . "\n");
