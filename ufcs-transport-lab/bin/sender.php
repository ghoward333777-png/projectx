<?php

declare(strict_types=1);

/**
 * Node 1 — sender.
 *
 *   php bin/sender.php facts  [--host=H] [--port=9100] [--count=242] [--codec=ZSTD] [--batch=1000] [--sign] [--single]
 *   php bin/sender.php file   --file=PATH [--kbps=800] [--height=720]     (classify → compress → send)
 *   php bin/sender.php query  --fql='FIND fact WHERE entity = "France" LIMIT 5'
 *   php bin/sender.php ping   [--n=20]
 *   php bin/sender.php stats | shutdown
 *
 * Node 2 must already be listening (php bin/receiver.php --port=9100).
 */
require __DIR__ . '/../src/bootstrap.php';

$cmd = $argv[1] ?? 'help';
// getopt() stops at the subcommand word, so parse --key[=value] by hand.
$o = [];
foreach (array_slice($argv, 2) as $arg) {
    if (preg_match('/^--([a-z-]+)(?:=(.*))?$/s', $arg, $m)) {
        $o[$m[1]] = $m[2] ?? true;
    }
}
if (!in_array($cmd, ['facts', 'file', 'query', 'ping', 'stats', 'shutdown'], true)) {
    fwrite(STDERR, "usage: php bin/sender.php facts|file|query|ping|stats|shutdown [options] (see the header of this file)\n");
    exit(1);
}
$t = new Transport((string) ($o['host'] ?? '127.0.0.1'), (int) ($o['port'] ?? 9100), [
    'mode' => isset($o['single']) ? 'single' : 'multi', 'sign' => isset($o['sign']), 'link_bps' => (float) ($o['link-mbps'] ?? 0) * 125000,
]);
$t->connect();
$s = new Sender($t);
$print = fn ($x) => print(json_encode($x, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");

switch ($cmd) {
    case 'facts':
        $n = (int) ($o['count'] ?? 242);
        $records = $n <= 242 ? array_slice(Ufcs::sample(), 0, $n) : array_merge(Ufcs::sample(), Ufcs::synthesize($n - 242));
        $codec = Protocol::compressionCode((string) ($o['codec'] ?? Protocol::compressionName(Codec::preferredText())));
        $r = $s->sendFacts($records, $codec, (int) ($o['batch'] ?? 1000));
        $r['delivered'] = $t->flush(300);
        $r['transport'] = $t->stats();
        $print($r);
        break;
    case 'file':
        $path = (string) ($o['file'] ?? '');
        if (!is_file($path)) {
            fwrite(STDERR, "--file=PATH required\n");
            exit(1);
        }
        $bytes = (string) file_get_contents($path);
        $ct = ContentClassifier::classify($bytes, $path);
        $policy = ContentClassifier::policy($ct, strlen($bytes));
        $meta = ['query_id' => 'file-' . basename($path), 'entity_ids' => [basename($path)]];
        if ($ct === Protocol::VIDEO) {
            $enc = MediaCodec::encodeVideo($path, ['codec' => Protocol::C_H264, 'kbps' => (int) ($o['kbps'] ?? 800), 'height' => isset($o['height']) ? (int) $o['height'] : null]);
        } elseif ($ct === Protocol::AUDIO) {
            $enc = MediaCodec::encodeAudio($path, ['codec' => Protocol::C_OPUS]);
        } elseif ($ct === Protocol::IMAGE) {
            $enc = MediaCodec::encodeImage($bytes, ['quality' => 80]);
        } else {
            $enc = ['bytes' => Codec::compress($policy['compression'], $bytes), 'codec' => $policy['compression'], 'mode' => Protocol::compressionName($policy['compression'])];
        }
        $r = $s->sendMedia($enc['bytes'], $ct, (int) $enc['codec'], $meta, $policy['priority']);
        $r += ['content' => Protocol::CONTENT_TYPES[$ct], 'policy' => $policy['reason'], 'source_bytes' => strlen($bytes),
            'ratio' => round(strlen($bytes) / max(1, strlen($enc['bytes'])), 2), 'encode' => $enc['mode'] ?? '', 'delivered' => $t->flush(300)];
        $print($r);
        break;
    case 'query':
        $r = $s->query((string) ($o['fql'] ?? 'FIND fact LIMIT 10'));
        $print(['fql' => $r['rendered'], 'codec' => $r['codec'], 'count' => count($r['records']),
            'facts' => array_map(fn ($x) => $x['nucleus'] + ['trust' => $x['certification']['trust_score'] ?? null], $r['records'])]);
        break;
    case 'ping':
        for ($i = 0; $i < (int) ($o['n'] ?? 20); $i++) {
            $s->ping();
            $t->flush(5);
        }
        $print(['control_ack_ms' => Stats::summary($t->latencies(Protocol::P_CONTROL))]);
        break;
    case 'stats':
        $print($s->remoteStats());
        break;
    case 'shutdown':
        $s->control('SHUTDOWN');
        echo "Node 2 asked to shut down\n";
        break;
}
$t->close();
