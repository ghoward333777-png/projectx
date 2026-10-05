<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

// --- AMF0 ---
$vals = ['connect', 1.0, ['app' => 'live', 'tcUrl' => 'rtmp://h/live', 'fpad' => false, 'audioCodecs' => 3191.0], null, [1.0, 'x']];
check(Amf0::decode(Amf0::encode(...$vals)) === $vals, 'AMF0 round trip (string, number, object, null, strict array)');
check(bin2hex(Amf0::encode('_result')) === '0200075f726573756c74', 'AMF0 string wire format');
check(bin2hex(Amf0::encode(2.0)) === '004000000000000000', 'AMF0 number is a big-endian double');
check(Amf0::decode("\x08\x00\x00\x00\x01\x00\x01a\x00\x3f\xf0\x00\x00\x00\x00\x00\x00\x00\x00\x09") === [['a' => 1.0]], 'AMF0 ECMA array (onMetaData form)');
throws(fn () => Amf0::decode("\x02\x00\x09abc"), 'truncated AMF0 refused');

// --- FLV ---
$tag = Flv::tag(Flv::VIDEO, 0x01020304, "\x17\x00abc");
check(strlen($tag) === 11 + 5 + 4 && ord($tag[0]) === 9 && bin2hex(substr($tag, 4, 4)) === '02030401', 'FLV tag header with extended timestamp byte');
check(substr($tag, -4) === pack('N', 16), 'FLV PreviousTagSize');
check(Flv::videoCodec("\x17\x01") === Protocol::C_H264 && Flv::videoCodec("\x1C") === Protocol::C_H265 && Flv::videoCodec("\x90av01") === Protocol::C_AV1, 'FLV video codec ids (incl. enhanced RTMP)');
check(Flv::audioCodec("\xAF\x01") === Protocol::C_AAC, 'FLV AAC');

// --- Manifests ---
$master = Manifest::parseM3u8("#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-STREAM-INF:BANDWIDTH=985600,RESOLUTION=640x360,CODECS=\"avc1.64001e,mp4a.40.2\"\nv0/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=545600,RESOLUTION=426x240\nv1/index.m3u8\n");
check($master['type'] === 'master' && count($master['variants']) === 2 && $master['variants'][0]['codecs'] === 'avc1.64001e,mp4a.40.2', 'HLS master playlist');
$media = Manifest::parseM3u8("#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2.000,\nseg000.ts\n#EXTINF:1.5,\nseg001.ts\n#EXT-X-ENDLIST\n");
check($media['type'] === 'media' && count($media['segments']) === 2 && $media['endlist'] && $media['segments'][1]['duration'] === 1.5, 'HLS media playlist');
throws(fn () => Manifest::parseM3u8('nope'), 'non-playlist refused');
$mpd = Manifest::parseMpd('<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT6.0S"><Period><AdaptationSet mimeType="video/mp4">'
    . '<SegmentTemplate timescale="1000" initialization="init-$RepresentationID$.m4s" media="chunk-$RepresentationID$-$Number%05d$.m4s" startNumber="1"><SegmentTimeline><S t="0" d="2000" r="2"/></SegmentTimeline></SegmentTemplate>'
    . '<Representation id="0" bandwidth="800000" width="640" height="360"/><Representation id="1" bandwidth="400000" width="426" height="240"/></AdaptationSet></Period></MPD>');
check($mpd['duration_s'] === 6.0 && count($mpd['representations']) === 2, 'DASH MPD representations and duration');
check(in_array('init-1.m4s', $mpd['files'], true) && in_array('chunk-0-00003.m4s', $mpd['files'], true) && count($mpd['files']) === 8, 'SegmentTemplate + SegmentTimeline expansion');
check(Manifest::isoDuration('PT1H2M3.5S') === 3723.5, 'ISO 8601 durations');

// --- Path safety ---
foreach (['v0/seg000.ts', 'manifest.mpd', 'chunk-0-00001.m4s'] as $ok) {
    check(StreamPackager::safePath($ok), "safe path $ok");
}
foreach (['../etc/passwd', '/abs.ts', 'v0/../../x', '', 'a//b', 'v0/seg 1.ts', '.hidden'] as $bad) {
    check(!StreamPackager::safePath($bad), "unsafe path refused: '$bad'");
}

if (MediaCodec::ffmpeg() === '') {
    echo "  (skip HLS/DASH/RTMP end-to-end: ffmpeg not installed)\n";
    done('streaming-contract');
    exit(0);
}

$work = sys_get_temp_dir() . '/ufcs-stream-test-' . bin2hex(random_bytes(4));
mkdir($work);
$src = $work . '/src.mp4';
MediaCodec::makeTestAv($src, 640, 360, 4);
check(MediaCodec::probe($src)['audio'] && MediaCodec::probe($src)['height'] === 360, 'probe reads the AV source');
check(StreamPackager::ladder(1080, 3) === [['height' => 540, 'kbps' => 1500], ['height' => 360, 'kbps' => 800]], 'ladder follows link capacity (3 Mbps → 540p top rung)');
check(StreamPackager::ladder(1080, 100)[0] === ['height' => 1080, 'kbps' => 4500], 'fast link keeps the source rung');

$node = LocalNode::start(['--out=' . $work . '/node2', '--repackage', '--verify-media']);
try {
    $t = new Transport('127.0.0.1', $node->port, ['sign' => true]);
    $t->connect();
    $s = new Sender($t);
    $hls = StreamPackager::hls($src, ['link_mbps' => 3]);
    $dash = StreamPackager::dash($src, ['link_mbps' => 3]);
    check(count($hls['ladder']) === 2 && $hls['segments'] === 4 && in_array('master.m3u8', $hls['files'], true), 'HLS ladder packaged');
    check(in_array('manifest.mpd', $dash['files'], true) && $dash['segments'] > 0, 'DASH packaged');
    $h = $s->sendPackage($hls, 'test-hls');
    $d = $s->sendPackage($dash, 'test-dash');
    check($t->flush(60), 'package frames acknowledged');
    $remote = $s->remoteStats();
    $pk = array_column($remote['packages'], null, 'package_id');
    check(($pk['test-hls']['ok'] ?? false) && $pk['test-hls']['variants'] === 2 && $pk['test-hls']['files'] === $h['files'], 'Node 2 rebuilt the HLS package completely');
    check(($pk['test-dash']['ok'] ?? false) && $pk['test-dash']['files'] === $d['files'], 'Node 2 rebuilt the DASH package completely');
    check(MediaCodec::verifyPath($pk['test-hls']['dir'] . '/master.m3u8')['ok'], 'rebuilt HLS plays (ffmpeg decode)');
    check(MediaCodec::verifyPath($pk['test-dash']['dir'] . '/manifest.mpd')['ok'], 'rebuilt DASH plays (ffmpeg decode)');
    foreach ($hls['files'] as $f) {
        check(hash_file('sha256', $hls['dir'] . '/' . $f) === hash_file('sha256', $pk['test-hls']['dir'] . '/' . $f), "byte-identical: $f");
    }
    // Hostile package frames are refused.
    $evil = Frame::make(Protocol::FACT_BATCH, Protocol::VIDEO, Protocol::C_H264, Protocol::P_BULK, ['package_id' => 'evil', 'path' => '../../escape.ts', 'file_count' => 1], 'x', 0);
    $bad = Frame::make(Protocol::FACT_BATCH, Protocol::VIDEO, Protocol::C_H264, Protocol::P_BULK, ['package_id' => 'evil', 'path' => 'seg.ts', 'file_count' => 1, 'sha256' => str_repeat('0', 64)], 'x', 0);
    $t->send($evil);
    $t->send($bad);
    $t->flush(10);
    $r2 = $s->remoteStats();
    check($r2['decode_errors'] === 2 && !file_exists($work . '/node2/escape.ts') && !file_exists($work . '/node2/packages/evil/seg.ts'), 'path traversal and hash mismatch refused');

    // RTMP ingest: ffmpeg publishes, the PHP RTMP server bridges live, Node 2 repackages.
    $s->control('RESET');
    $run = RtmpBridge::publishFile($t, $src);
    check($run['publisher_rc'] === 0, 'ffmpeg completed an RTMP publish to the lab server');
    check(($run['stream']['video_codec'] ?? '') === 'H264' && ($run['stream']['audio_codec'] ?? '') === 'AAC' && $run['stream']['tags'] > 100, 'RTMP media messages parsed (H.264 + AAC)');
    check(strlen($run['stream']['stream_key_sha256']) === 16 && !str_contains(json_encode($run['stream']), '"lab"'), 'stream key is hashed, never forwarded');
    $remote = $s->remoteStats();
    $st = $remote['streams'][0] ?? [];
    check(($st['intact'] ?? false) && $st['sha256'] === $run['stream']['sha256'] && $st['chunks'] === $run['stream']['chunks'], 'FLV arrived intact on Node 2');
    check(($st['decodes']['ok'] ?? false) && str_ends_with((string) $st['file'], '.flv'), 'FLV stored and decodes');
    check(($st['repackaged']['hls']['ok'] ?? false) && ($st['repackaged']['dash']['ok'] ?? false), 'Node 2 repackaged the RTMP stream as HLS and DASH');
    $s->control('SHUTDOWN');
    $t->close();
} finally {
    $node->finish();
}

// RTMP egress + stream-key enforcement through the CLI edge.
$node = LocalNode::start(['--out=' . $work . '/node2b']);
$port = random_int(20000, 60000);
$edge = proc_open([PHP_BINARY, __DIR__ . '/../bin/rtmp-ingest.php', '--port=' . $node->port, '--rtmp-port=' . $port, '--rtmp-host=127.0.0.1', '--key=right', '--once', '--max-seconds=60'],
    [0 => ['file', '/dev/null', 'r'], 1 => ['pipe', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
check(str_starts_with((string) fgets($pipes[1]), 'READY'), 'RTMP edge listening');
$refused = RtmpPublisher::push($src, 'rtmp://127.0.0.1:' . $port . '/live/wrong', false);
check($refused['code'] !== 0, 'wrong stream key is refused');
$ok = RtmpPublisher::push($hls['dir'] . '/master.m3u8', 'rtmp://127.0.0.1:' . $port . '/live/right', true);
check($ok['code'] === 0, 'RTMP egress pushed an HLS package to an RTMP endpoint');
$out = stream_get_contents($pipes[1]);
proc_close($edge);
check(str_contains($out, '"event":"end"') && str_contains($out, '"video_codec":"H264"'), 'edge reported the published stream');
$t = new Transport('127.0.0.1', $node->port);
$t->connect();
$s = new Sender($t);
$st = $s->remoteStats()['streams'][0] ?? [];
check(($st['intact'] ?? false) && ($st['protocol'] ?? '') === 'RTMP', 'egress stream crossed the transport intact');
$s->control('SHUTDOWN');
$t->close();
$node->finish();

StreamPackager::removeDir($hls['dir']);
StreamPackager::removeDir($dash['dir']);
StreamPackager::removeDir($work);
done('streaming-contract');
