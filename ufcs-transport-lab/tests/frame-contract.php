<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

// --- Exact byte layout (golden bytes cross-checked against Python struct + zlib) ---
check(Protocol::HEADER_LEN === 32, 'header is 32 bytes');
check(array_sum(array_column(Protocol::HEADER_LAYOUT, 2)) === 32, 'layout sizes sum to 32');
$f = new Frame(Protocol::FACT_BATCH, Protocol::TEXT, Protocol::C_ZSTD, 0x0022, '{}', 'abc', 7, 3);
$wire = $f->encode();
check(bin2hex(substr($wire, 0, 32)) === 'f051010000010022000000030000000200000000000000070000000300000000', 'golden header bytes');
check(bin2hex(substr($wire, -4)) === '19519cc5', 'golden CRC32 (IEEE, big-endian, over header+meta+payload)');
check(strlen($wire) === 32 + 2 + 3 + 4, 'unsigned frame length');
check(Protocol::priorityFromFlags(0x0022) === Protocol::P_NORMAL, 'priority from flags');
check(Protocol::priorityFromFlags(0x0005) === Protocol::P_CONTROL, 'highest-urgency priority bit wins');
check(Protocol::priorityFromFlags(0) === Protocol::P_NORMAL, 'no priority bit → normal');

// --- Round trip ---
$d = Frame::decode($wire);
check($d->messageId === 7 && $d->sequence === 3 && $d->payload === 'abc' && $d->meta === '{}', 'decode round trip');
$big = new Frame(Protocol::STREAM_CHUNK, Protocol::VIDEO, Protocol::C_H264, Protocol::F_PRIORITY_BULK, '{"stream_id":"s"}', random_bytes(70000), PHP_INT_MAX, 0xFFFFFFFF);
$bd = Frame::decode($big->encode());
check($bd->messageId === PHP_INT_MAX && $bd->sequence === 0xFFFFFFFF, 'u64 message id and u32 sequence survive');

// --- CRC and plausibility ---
$bad = $wire;
$bad[35] = 'X';
throws(fn () => Frame::decode($bad), 'payload corruption fails CRC');
$bad = $wire;
$bad[5] = chr(200);
throws(fn () => Frame::decode($bad), 'unknown CompressionType is implausible');
throws(fn () => Frame::decode(substr($wire, 0, 20)), 'short header refused');
throws(fn () => Frame::decode(substr($wire, 0, -1)), 'truncated frame refused');

// --- Ed25519 signature ---
$keys = NodeKeys::forNode('node-1');
$other = NodeKeys::forNode('node-x');
$s = Frame::make(Protocol::FACT_BATCH, Protocol::TEXT, Protocol::C_NONE, Protocol::P_NORMAL, ['source_node_id' => 'node-1'], 'facts', 9);
$sw = $s->encode($keys['secret']);
check(strlen($sw) === $s->wireLength() && ($s->flags & Protocol::F_SIGNED), 'signed frame carries 64-byte signature and flag');
check(Frame::decode($sw, $keys['public'])->signature !== null, 'signature verifies');
throws(fn () => Frame::decode($sw, $other['public']), 'wrong key refused');
throws(fn () => Frame::decode($wire, null, true), 'unsigned frame refused when signatures are required');
check(NodeKeys::forNode('node-1') === $keys, 'lab keys are deterministic');

// --- Stream reader: byte-at-a-time, resync after corruption ---
$frames = [];
for ($i = 1; $i <= 5; $i++) {
    $frames[] = Frame::make(Protocol::FACT_BATCH, Protocol::TEXT, Protocol::C_NONE, Protocol::P_NORMAL, ['n' => $i], str_repeat("payload-$i ", 50), $i)->encode();
}
$r = new FrameReader();
$got = [];
foreach (str_split(implode('', $frames)) as $byte) {
    $r->push($byte);
    while (($x = $r->next()) !== null) {
        $got[] = $x->messageId;
    }
}
check($got === [1, 2, 3, 4, 5], 'byte-by-byte delivery reassembles every frame');

foreach ([40 => 'payload', 3 => 'MsgType', 9 => 'PayloadLen', 0 => 'magic'] as $at => $field) {
    $corrupt = $frames;
    $corrupt[2][$at] = chr(ord($corrupt[2][$at]) ^ 0x5A);
    $r = new FrameReader();
    $r->push(implode('', $corrupt));
    $got = [];
    while (($x = $r->next()) !== null) {
        $got[] = $x->messageId;
    }
    foreach ($r->finish() as $x) {
        $got[] = $x->messageId;
    }
    check($got === [1, 2, 4, 5], "corrupt $field costs exactly one frame (got " . implode(',', $got) . ')');
    check($r->corruptFrames >= 1, "corruption in $field is counted");
}
$r = new FrameReader();
$r->push(random_bytes(500) . $frames[0] . "\x00\xF0\x51" . $frames[1]);
$got = [];
while (($x = $r->next()) !== null) {
    $got[] = $x->messageId;
}
check($got === [1, 2], 'garbage and false anchors are skipped');

// --- Signed frames through the reader ---
$r = new FrameReader(fn (Frame $f) => NodeKeys::forNode('node-1')['public'], true);
$tampered = $sw;
$tampered[strlen($tampered) - 1] = chr(ord($tampered[strlen($tampered) - 1]) ^ 1);
$r->push($tampered . $sw);
$x = $r->next();
check($x !== null && $x->messageId === 9 && $r->corruptFrames === 1, 'bad signature dropped, good one admitted');

done('frame-contract');
