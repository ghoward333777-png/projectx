<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

// Node 2 as a real process, signatures required; Node 1 over loopback TCP.
$node = LocalNode::start(['--window=4', '--require-signature']);
try {
    $t = new Transport('127.0.0.1', $node->port, ['sign' => true]);
    $t->connect();
    $s = new Sender($t);
    check($t->stats()['control']['window'] === 4, 'receiver window advertised in the HELLO ACK');

    // Facts on the normal class, batched, with the window forcing backpressure (4 in flight).
    $records = Ufcs::synthesize(5000, 2);
    $sent = $s->sendFacts($records, Codec::preferredText(), 250);
    check($sent['frames'] === 20, '5,000 facts → 20 FACT_BATCH frames of 250');
    check($t->flush(60), 'all frames acknowledged');
    $remote = $s->remoteStats();
    check($remote['facts']['rejected'] === 0 && $remote['facts']['admitted'] + $remote['facts']['merged'] === 5000, 'every fact re-validated on Node 2');
    check($remote['by_priority']['normal']['frames'] === 21, 'fact batches (+ the HELLO) arrived on the normal connection');
    check($remote['corrupt_frames'] === 0, 'no corrupt frames on a clean link');

    // FQL round trip.
    $q = $s->query('FIND fact WHERE predicate = "has_capital" AND trust >= 0.5 RANK BY trust LIMIT 4');
    check(count($q['records']) === 4 && $q['rendered'] === 'FIND fact WHERE predicate = "has_capital" AND trust >= 0.5 RANK BY trust LIMIT 4', 'FQL answered over the wire');
    check(array_reduce($q['records'], fn ($ok, $r) => $ok && Ufcs::validate($r) === null && Ufcs::trust($r) >= 0.5, true), 'answers are valid UFCS records within the filter');
    throws(fn () => $s->query('FIND fact WHERE nonsense'), 'bad FQL is refused before it is sent');

    // Media: a stream of chunks is reassembled and hash-verified; a short object goes as one frame.
    $blob = random_bytes(300000);
    $m = $s->sendMedia($blob, Protocol::VIDEO, Protocol::C_H264, ['entity_ids' => ['V1']], Protocol::P_BULK, 65536, true);
    $one = $s->sendMedia(random_bytes(5000), Protocol::IMAGE, Protocol::C_WEBP);
    check($m['frames'] === 5 && $one['mode'] === 'single', 'chunking policy');
    $t->flush(30);
    $remote = $s->remoteStats();
    $stream = $remote['streams'][0] ?? [];
    check(($stream['intact'] ?? false) && $stream['bytes'] === 300000 && $stream['gaps'] === 0 && $stream['sha256'] === hash('sha256', $blob), 'stream reassembled intact');
    check($remote['by_priority']['bulk']['frames'] === 7 && $remote['images'] === 1, 'media (+ the HELLO) rode the bulk connection');

    // MIXED multipart.
    $mx = $s->sendMixed([
        ['name' => 'facts.jsonl', 'content_type' => Protocol::TEXT, 'compression' => Protocol::C_GZIP, 'bytes' => Codec::compress(Protocol::C_GZIP, Ufcs::encodeBatch(array_slice(Ufcs::sample(), 0, 10)))],
        ['name' => 'thumb.webp', 'content_type' => Protocol::IMAGE, 'compression' => Protocol::C_WEBP, 'bytes' => random_bytes(800)],
    ], Protocol::C_GZIP);
    $t->flush(10);
    $remote = $s->remoteStats();
    check($remote['mixed_parts'] === 2 && $remote['decode_errors'] === 0, 'MIXED parts ingested by their own content types');

    // Latency is measured per class.
    for ($i = 0; $i < 10; $i++) {
        $s->ping();
    }
    $t->flush(10);
    check(count($t->latencies(Protocol::P_CONTROL)) >= 10, 'control ACK latencies recorded');
    $t->close();

    // An unsigned sender is refused by a signature-requiring Node 2 (frames dropped, never ACKed).
    $u = new Transport('127.0.0.1', $node->port, ['sign' => false]);
    $threw = false;
    try {
        $u->connect(1.0);
    } catch (Throwable) {
        $threw = true;
    }
    check(!$u->idle() || $threw, 'unsigned frames are never acknowledged');
    $u->close();

    // Single-connection mode still works (the HOL-blocking baseline).
    $one = new Transport('127.0.0.1', $node->port, ['sign' => true, 'mode' => 'single']);
    $one->connect();
    $s1 = new Sender($one);
    $s1->sendFacts(array_slice(Ufcs::sample(), 0, 50), Protocol::C_GZIP, 25);
    check($one->flush(10) && count($one->stats()) === 1, 'single shared connection carries every class');
    $rs = $s1->remoteStats();
    $s1->control('SHUTDOWN');
    $one->close();
    check($rs['corrupt_frames'] >= 1, 'Node 2 counted the unsigned frames as refused');
} finally {
    $final = $node->finish();
}
check(isset($final['store_facts']), 'Node 2 exits cleanly after SHUTDOWN and reports stats');

// Token-bucket pacing on a real connection: 400 KB over a 2 Mbit/s link takes ~1.6 s.
$node = LocalNode::start();
$t = new Transport('127.0.0.1', $node->port, ['link_bps' => 250000]);
$t->connect();
$t0 = microtime(true);
(new Sender($t))->sendMedia(random_bytes(400000), Protocol::VIDEO, Protocol::C_H264, [], Protocol::P_BULK, 65536, true);
$t->flush(30);
$el = microtime(true) - $t0;
check($el > 1.2 && $el < 3.0, sprintf('link token bucket paces the sender (%.2fs for 400 KB at 2 Mbit/s)', $el));
(new Sender($t))->control('SHUTDOWN');
$t->close();
$node->finish();

done('transport-contract');
