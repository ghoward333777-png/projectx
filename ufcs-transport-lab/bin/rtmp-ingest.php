<?php

declare(strict_types=1);

/**
 * RTMP ingest → UFCS-FQL transport bridge (Node 1 side).
 *
 *   php bin/rtmp-ingest.php [--rtmp-port=1935] [--host=127.0.0.1] [--port=9100]
 *                           [--key=SECRET] [--sign] [--max-seconds=N] [--once]
 *
 * Point OBS / ffmpeg / an encoder at rtmp://<this-host>:1935/live/<stream-key>.
 * Every published stream is forwarded live to Node 2 as FLV STREAM_CHUNK frames
 * on the bulk connection; start Node 2 with --out=DIR --repackage to get HLS and
 * DASH renditions of each finished stream. --key restricts publishing to one
 * stream key; --once exits after the first stream ends. Prints JSON lines.
 */
require __DIR__ . '/../src/bootstrap.php';

$o = getopt('', ['rtmp-port:', 'rtmp-host:', 'host:', 'port:', 'key:', 'sign', 'max-seconds:', 'once']);
$t = new Transport((string) ($o['host'] ?? '127.0.0.1'), (int) ($o['port'] ?? 9100), ['sign' => isset($o['sign']), 'node_id' => 'rtmp-edge']);
$t->connect();
$bridge = new RtmpBridge($t);
$key = isset($o['key']) ? (string) $o['key'] : null;
$cb = $bridge->callbacks();
$emit = fn (array $x) => fwrite(STDOUT, json_encode($x, JSON_UNESCAPED_SLASHES) . "\n");
$server = new RtmpServer([
    'onPublish' => function (string $sid, array $info) use ($cb, $emit) {
        $cb['onPublish']($sid, $info);
        $emit(['event' => 'publish', 'stream_id' => $sid] + $info);
    },
    'onTag' => $cb['onTag'],
    'onEnd' => function (string $sid, array $info) use ($cb, $emit) {
        $cb['onEnd']($sid, $info);
        $emit(['event' => 'end', 'stream_id' => $sid] + $info);
    },
], $key === null ? null : fn (string $app, string $k) => hash_equals($key, $k));
$server->listen((string) ($o['rtmp-host'] ?? '0.0.0.0'), (int) ($o['rtmp-port'] ?? 1935));
fwrite(STDOUT, 'READY rtmp://0.0.0.0:' . $server->port . "/live/<key>\n");
fflush(STDOUT);

$deadline = isset($o['max-seconds']) ? microtime(true) + (float) $o['max-seconds'] : INF;
while (microtime(true) < $deadline) {
    $server->tick(0.005);
    $bridge->tick();
    $t->pump(0);
    if (isset($o['once']) && $bridge->finished && $bridge->liveCount() === 0 && $server->activeSessions() === 0) {
        break;
    }
}
$t->flush(30);
$server->close();
$emit(['event' => 'summary', 'streams' => $bridge->finished, 'transport' => $t->stats()]);
$t->close();
