<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

$text = Ufcs::encodeBatch(Ufcs::synthesize(400));

// --- Lossless codecs round-trip and actually compress ---
foreach ([Protocol::C_NONE, Protocol::C_GZIP, Protocol::C_UFCS_DICT, Protocol::C_ZSTD] as $c) {
    if (!Codec::available($c)) {
        echo '  (skip ' . Protocol::compressionName($c) . ": unavailable)\n";
        continue;
    }
    $z = Codec::compress($c, $text);
    check(Codec::decompress($c, $z) === $text, Protocol::compressionName($c) . ' round trip');
    check(Codec::compress($c, $text) === $z, Protocol::compressionName($c) . ' is deterministic');
    if ($c !== Protocol::C_NONE) {
        check(strlen($text) / strlen($z) >= 3, Protocol::compressionName($c) . ' compresses UFCS text ≥ 3×');
    }
}
check(substr(Codec::compress(Protocol::C_GZIP, 'x'), 0, 2) === "\x1f\x8b", 'GZIP is RFC 1952 (interoperable)');
throws(fn () => Codec::decompress(Protocol::C_GZIP, 'not gzip'), 'bad GZIP refused');
throws(fn () => Codec::compress(Protocol::C_H264, 'x'), 'lossy codecs are not byte codecs');
// The dictionary earns its keep on small batches.
$one = Ufcs::encodeBatch(array_slice(Ufcs::sample(), 0, 3));
check(strlen(Codec::compress(Protocol::C_UFCS_DICT, $one)) < strlen(gzdeflate($one, 9)), 'UFCS_DICT beats plain DEFLATE on a small batch');
check(Codec::preferredText() === (Codec::zstdBinary() !== '' ? Protocol::C_ZSTD : Protocol::C_GZIP), 'never labels a payload ZSTD unless zstd exists');

// --- Multipart ---
$parts = [
    ['name' => 'facts.jsonl', 'content_type' => Protocol::TEXT, 'compression' => Protocol::C_GZIP, 'bytes' => Codec::compress(Protocol::C_GZIP, $one)],
    ['name' => 'cover.webp', 'content_type' => Protocol::IMAGE, 'compression' => Protocol::C_WEBP, 'bytes' => random_bytes(300)],
    ['name' => '', 'content_type' => Protocol::AUDIO, 'compression' => Protocol::C_NONE, 'bytes' => ''],
];
check(Multipart::decode(Multipart::encode($parts)) === $parts, 'multipart round trip');
throws(fn () => Multipart::decode(substr(Multipart::encode($parts), 0, -310)), 'truncated multipart refused');

// --- Classifier and policy ---
check(ContentClassifier::classify("\x89PNG\r\n\x1a\nxxxxxxxx") === Protocol::IMAGE, 'PNG → IMAGE');
check(ContentClassifier::classify("RIFF\0\0\0\0WAVEfmt ") === Protocol::AUDIO, 'WAV → AUDIO');
check(ContentClassifier::classify("\0\0\0\x20ftypisom") === Protocol::VIDEO, 'MP4 → VIDEO');
check(ContentClassifier::classify("YUV4MPEG2 W640") === Protocol::VIDEO, 'Y4M → VIDEO');
check(ContentClassifier::classify('{"fuid":"x"}') === Protocol::TEXT, 'JSON → TEXT');
check(ContentClassifier::classify('????', 'clip.webm') === Protocol::VIDEO, 'extension fallback');
check(ContentClassifier::policy(Protocol::VIDEO, 5 << 20)['msg_type'] === Protocol::STREAM_CHUNK, 'large video streams');
check(ContentClassifier::policy(Protocol::VIDEO, 100)['msg_type'] === Protocol::FACT_BATCH, 'short clip is one frame');
check(ContentClassifier::policy(Protocol::TEXT, 100)['priority'] === Protocol::P_NORMAL, 'facts ride the normal class');
check(ContentClassifier::policy(Protocol::IMAGE, 100)['priority'] === Protocol::P_BULK, 'media rides the bulk class');

// --- Token bucket (injected clock) ---
$now = 0.0;
$tb = new TokenBucket(1000, 500, function () use (&$now) {
    return $now;
});
check($tb->allow(800) && !$tb->allow(300), 'bucket starts full and empties');
$now = 1.0;
check($tb->available() == 700.0, 'refills at rate');
$now = 100.0;
check($tb->available() == 1000.0, 'capped at capacity');
$tb->consume(1000);
check(abs($tb->waitFor(250) - 0.5) < 1e-9, 'waitFor = deficit / rate');
check((new TokenBucket(10, 0))->waitFor(1 << 30) === 0.0, 'rate 0 = unlimited');

// --- Video planning from link capacity ---
check(Benchmark::planVideo(720, 100)['height'] === 720, '100 Mbps carries 720p');
$p = Benchmark::planVideo(1080, 2);
check($p['downscaled'] && $p['kbps'] <= MediaCodec::targetVideoKbps(2000), '2 Mbps link downscales 1080p within budget');
check(MediaCodec::targetVideoKbps(1000) === 768, 'video budget = 80% of link minus audio');

done('codec-contract');
