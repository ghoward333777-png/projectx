<?php

declare(strict_types=1);

/**
 * Decode a file of captured UFCS-FQL/1 frames (any number, back to back) and
 * print each frame's header and meta; corrupt regions are reported and skipped.
 *
 *   php bin/inspect.php capture.bin
 *   php bin/inspect.php --demo        (writes and decodes a 3-frame sample)
 */
require __DIR__ . '/../src/bootstrap.php';

if (($argv[1] ?? '') === '--demo') {
    $records = array_slice(Ufcs::sample(), 0, 5);
    $bytes = '';
    foreach ([Protocol::C_NONE, Protocol::C_GZIP, Codec::preferredText()] as $i => $c) {
        $bytes .= Frame::make(Protocol::FACT_BATCH, Protocol::TEXT, $c, Protocol::P_NORMAL, Ufcs::batchContext($records) + ['query_id' => 'demo'],
            Codec::compress($c, Ufcs::encodeBatch($records)), $i + 1)->encode();
    }
} elseif (isset($argv[1]) && is_file($argv[1])) {
    $bytes = (string) file_get_contents($argv[1]);
} else {
    fwrite(STDERR, "usage: php bin/inspect.php FILE | --demo\n");
    exit(1);
}
$reader = new FrameReader();
$reader->push($bytes);
$frames = [];
while (($f = $reader->next()) !== null) {
    $frames[] = $f;
}
$frames = array_merge($frames, $reader->finish());
foreach ($frames as $f) {
    $d = $f->describe();
    printf("#%d %s %s/%s %s  meta=%dB payload=%dB wire=%dB crc=%s%s\n  %s\n", $d['message_id'], $d['msg_type'], $d['content_type'], $d['compression'],
        $d['priority'], $d['meta_len'], $d['payload_len'], $d['wire_len'], $d['crc32'], $d['signed'] ? ' signed' : '', json_encode($d['meta'], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
}
printf("%d frame(s), %d corrupt, %d byte(s) skipped\n", count($frames), $reader->corruptFrames, $reader->skippedBytes);
