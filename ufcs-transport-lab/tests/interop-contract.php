<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

/**
 * Wire compatibility with the Go and Rust reference implementations
 * (ref/go, ref/rust), in both directions. Skips a language whose toolchain
 * is not installed.
 */
$bin = sys_get_temp_dir() . '/ufcs-interop-' . bin2hex(random_bytes(4));
mkdir($bin);
$refs = [];
if (trim((string) shell_exec('command -v go 2>/dev/null')) !== '') {
    exec('cd ' . escapeshellarg(__DIR__ . '/../ref/go') . ' && go build -o ' . escapeshellarg($bin . '/go-ref') . ' . 2>&1', $o, $rc);
    check($rc === 0, 'Go reference builds: ' . implode("\n", $o));
    $refs['go'] = ['recv' => fn ($port) => [$bin . '/go-ref', 'recv', '-port', (string) $port],
        'send' => fn ($port, $file) => [$bin . '/go-ref', 'send', '-port', (string) $port, '-file', $file, '-batch', '50']];
} else {
    echo "  (skip Go: toolchain not installed)\n";
}
if (trim((string) shell_exec('command -v cargo 2>/dev/null')) !== '') {
    exec('cd ' . escapeshellarg(__DIR__ . '/../ref/rust') . ' && CARGO_TARGET_DIR=' . escapeshellarg($bin . '/rust') . ' cargo build --release --offline -q 2>&1', $o, $rc);
    check($rc === 0, 'Rust reference builds');
    $refs['rust'] = ['recv' => fn ($port) => [$bin . '/rust/release/ufcsframe', 'recv', (string) $port],
        'send' => fn ($port, $file) => [$bin . '/rust/release/ufcsframe', 'send', '127.0.0.1', (string) $port, $file, '50']];
} else {
    echo "  (skip Rust: toolchain not installed)\n";
}

foreach ($refs as $lang => $r) {
    // PHP Node 1 (signed, GZIP) → reference Node 2
    $port = random_int(20000, 60000);
    $proc = proc_open(($r['recv'])($port), [1 => ['pipe', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
    check(str_starts_with((string) fgets($pipes[1]), 'READY'), "$lang receiver ready");
    $t = new Transport('127.0.0.1', $port, ['sign' => true]);
    $t->connect();
    $s = new Sender($t);
    $s->sendFacts(Ufcs::sample(), Protocol::C_GZIP, 50);
    $s->ping();
    check($t->flush(10), "$lang receiver acknowledged every PHP frame");
    $s->control('SHUTDOWN');
    $t->close();
    $summary = json_decode(trim((string) stream_get_contents($pipes[1])), true);
    proc_close($proc);
    check(($summary['errors'] ?? 1) === 0, "$lang receiver saw no CRC/framing errors");
    check(array_sum((array) $summary['frames']) === 3 + 5 + 1 + 1, "$lang receiver counted every frame by connection");
    if ($lang === 'go') {
        check($summary['facts'] === 242 && $summary['rejected'] === 0 && $summary['admitted'] === 162, 'Go re-validated every UFCS fingerprint (incl. numeric objects)');
    }

    // Reference Node 1 → PHP Node 2
    $node = LocalNode::start();
    exec(implode(' ', array_map('escapeshellarg', ($r['send'])($node->port, Ufcs::SAMPLE_FILE))) . ' 2>&1', $out, $rc);
    check($rc === 0, "$lang sender completed");
    $t = new Transport('127.0.0.1', $node->port);
    $t->connect();
    $s = new Sender($t);
    $st = $s->remoteStats();
    check($st['facts']['admitted'] === 162 && $st['facts']['merged'] === 80 && $st['facts']['rejected'] === 0, "PHP Node 2 admitted every fact sent by $lang");
    check($st['corrupt_frames'] === 0, "no corrupt frames from $lang");
    $s->control('SHUTDOWN');
    $t->close();
    $node->finish();
    $out = [];
}
StreamPackager::removeDir($bin);
done('interop-contract');
