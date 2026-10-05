<?php

declare(strict_types=1);

/**
 * AMF0 (Action Message Format 0) — the encoding of RTMP command and data
 * messages. Covers the types publishers actually send.
 */
final class Amf0
{
    public static function encode(mixed ...$values): string
    {
        $out = '';
        foreach ($values as $v) {
            $out .= self::one($v);
        }
        return $out;
    }

    private static function one(mixed $v): string
    {
        if ($v === null) {
            return "\x05";
        }
        if (is_bool($v)) {
            return "\x01" . ($v ? "\x01" : "\x00");
        }
        if (is_int($v) || is_float($v)) {
            return "\x00" . pack('E', (float) $v);
        }
        if (is_string($v)) {
            return strlen($v) > 0xFFFF ? "\x0C" . pack('N', strlen($v)) . $v : "\x02" . pack('n', strlen($v)) . $v;
        }
        if (is_array($v)) {
            if (array_is_list($v) && $v !== []) {
                return "\x0A" . pack('N', count($v)) . implode('', array_map([self::class, 'one'], $v));
            }
            $out = "\x03";
            foreach ($v as $k => $x) {
                $out .= pack('n', strlen((string) $k)) . $k . self::one($x);
            }
            return $out . "\x00\x00\x09";
        }
        throw new InvalidArgumentException('AMF0 cannot encode ' . get_debug_type($v));
    }

    /** @return array<int, mixed> */
    public static function decode(string $b): array
    {
        $pos = 0;
        $out = [];
        while ($pos < strlen($b)) {
            $out[] = self::read($b, $pos);
        }
        return $out;
    }

    private static function need(string $b, int $pos, int $n): void
    {
        if ($pos + $n > strlen($b)) {
            throw new RuntimeException('AMF0 truncated');
        }
    }

    private static function read(string $b, int &$pos): mixed
    {
        self::need($b, $pos, 1);
        $type = ord($b[$pos++]);
        switch ($type) {
            case 0x00:
                self::need($b, $pos, 8);
                $v = unpack('E', substr($b, $pos, 8))[1];
                $pos += 8;
                return $v;
            case 0x01:
                self::need($b, $pos, 1);
                return ord($b[$pos++]) !== 0;
            case 0x02:
                return self::str($b, $pos, 2);
            case 0x0C:
                return self::str($b, $pos, 4);
            case 0x05:
            case 0x06:
                return null;
            case 0x08: // ECMA array: u32 count hint, then an object body
                self::need($b, $pos, 4);
                $pos += 4;
                return self::props($b, $pos);
            case 0x03:
                return self::props($b, $pos);
            case 0x0A:
                self::need($b, $pos, 4);
                $n = unpack('N', substr($b, $pos, 4))[1];
                $pos += 4;
                $arr = [];
                for ($i = 0; $i < $n; $i++) {
                    $arr[] = self::read($b, $pos);
                }
                return $arr;
            case 0x0B: // date: f64 ms + s16 timezone
                self::need($b, $pos, 10);
                $v = unpack('E', substr($b, $pos, 8))[1];
                $pos += 10;
                return $v;
        }
        throw new RuntimeException(sprintf('AMF0 type 0x%02X not supported', $type));
    }

    private static function str(string $b, int &$pos, int $lenBytes): string
    {
        self::need($b, $pos, $lenBytes);
        $n = $lenBytes === 2 ? unpack('n', substr($b, $pos, 2))[1] : unpack('N', substr($b, $pos, 4))[1];
        $pos += $lenBytes;
        self::need($b, $pos, $n);
        $s = substr($b, $pos, $n);
        $pos += $n;
        return $s;
    }

    /** @return array<string, mixed> */
    private static function props(string $b, int &$pos): array
    {
        $o = [];
        while (true) {
            self::need($b, $pos, 3);
            if (substr($b, $pos, 3) === "\x00\x00\x09") {
                $pos += 3;
                return $o;
            }
            $k = self::str($b, $pos, 2);
            $o[$k] = self::read($b, $pos);
        }
    }
}

/** FLV container writer: what RTMP audio/video/data messages become on disk and on the wire. */
final class Flv
{
    public const AUDIO = 8;
    public const VIDEO = 9;
    public const SCRIPT = 18;

    public static function header(bool $audio = true, bool $video = true): string
    {
        return 'FLV' . "\x01" . chr(($audio ? 4 : 0) | ($video ? 1 : 0)) . pack('N', 9) . pack('N', 0);
    }

    public static function tag(int $type, int $timestamp, string $data): string
    {
        $ts = $timestamp & 0xFFFFFFFF;
        $len = strlen($data);
        return chr($type) . substr(pack('N', $len), 1) . substr(pack('N', $ts & 0xFFFFFF), 1) . chr(($ts >> 24) & 0xFF) . "\x00\x00\x00" . $data . pack('N', 11 + $len);
    }

    /** FLV video codec id → lab compression code (7 = AVC/H.264, 12 = HEVC; enhanced-RTMP fourCCs too). */
    public static function videoCodec(string $data): int
    {
        if ($data === '') {
            return Protocol::C_NONE;
        }
        $b0 = ord($data[0]);
        if ($b0 & 0x80) { // enhanced RTMP: fourCC follows
            return match (substr($data, 1, 4)) {
                'hvc1' => Protocol::C_H265, 'av01' => Protocol::C_AV1, 'avc1' => Protocol::C_H264, default => Protocol::C_NONE,
            };
        }
        return match ($b0 & 0x0F) {
            7 => Protocol::C_H264, 12 => Protocol::C_H265, default => Protocol::C_NONE,
        };
    }

    public static function audioCodec(string $data): int
    {
        return $data === '' ? Protocol::C_NONE : match (ord($data[0]) >> 4) {
            10 => Protocol::C_AAC, 13 => Protocol::C_OPUS, default => Protocol::C_NONE,
        };
    }
}

/**
 * RTMP ingest server (Adobe RTMP 1.0): accepts publishers such as OBS,
 * ffmpeg or hardware encoders on rtmp://host:1935/<app>/<stream-key>.
 *
 * Implements the simple handshake (C0/C1/C2 ↔ S0/S1/S2), the chunk stream
 * (all four chunk header formats, extended timestamps, Set Chunk Size, Window
 * Acknowledgement), and the publish command flow (connect → releaseStream →
 * FCPublish → createStream → publish → … → FCUnpublish/deleteStream). Every
 * audio, video and @setDataFrame message becomes an FLV tag delivered to the
 * callbacks, which the bridge forwards to Node 2 as STREAM_CHUNK frames.
 * Playback (RTMP play) is not served — players use the HLS/DASH output.
 */
final class RtmpServer
{
    private const HANDSHAKE_SIZE = 1536;
    private const OUT_CHUNK = 4096;

    /** @var resource|null */
    private $listener = null;
    /** @var array<int, array<string, mixed>> */
    private array $sessions = [];
    public int $port = 0;
    /** @var array<string, callable> onPublish(sid, info), onTag(sid, type, ts, data, flvBytes), onEnd(sid, info) */
    private array $on;
    /** @var null|callable(string $app, string $key): bool */
    private $authorize;

    /** @param array<string, callable> $callbacks */
    public function __construct(array $callbacks = [], ?callable $authorize = null)
    {
        $this->on = $callbacks;
        $this->authorize = $authorize;
    }

    public function listen(string $host = '0.0.0.0', int $port = 1935): void
    {
        $sock = @stream_socket_server('tcp://' . $host . ':' . $port, $errno, $errstr);
        if ($sock === false) {
            throw new RuntimeException('RTMP cannot listen on ' . $host . ':' . $port . ' — ' . $errstr);
        }
        stream_set_blocking($sock, false);
        $this->listener = $sock;
        $this->port = $port;
    }

    public function activeSessions(): int
    {
        return count($this->sessions);
    }

    /** One pass of the event loop. */
    public function tick(float $wait = 0.02): void
    {
        $read = $this->listener ? [$this->listener] : [];
        $write = [];
        foreach ($this->sessions as $s) {
            $read[] = $s['sock'];
            if ($s['out'] !== '') {
                $write[] = $s['sock'];
            }
        }
        if (!$read) {
            usleep((int) ($wait * 1e6));
            return;
        }
        $except = null;
        if (@stream_select($read, $write, $except, 0, (int) ($wait * 1e6)) === false) {
            return;
        }
        foreach ($read as $sock) {
            if ($sock === $this->listener) {
                $c = @stream_socket_accept($this->listener, 0, $peer);
                if ($c !== false) {
                    stream_set_blocking($c, false);
                    $this->sessions[(int) $c] = ['sock' => $c, 'peer' => $peer, 'stage' => 0, 'in' => '', 'out' => '', 'chunkIn' => 128,
                        'prev' => [], 'partial' => [], 'app' => '', 'key' => '', 'publishing' => false, 'bytesIn' => 0, 'acked' => 0, 'ackWindow' => 2500000,
                        'tags' => 0, 'video_codec' => Protocol::C_NONE, 'audio_codec' => Protocol::C_NONE, 'started' => microtime(true), 'flvStarted' => false];
                }
                continue;
            }
            $this->readSession((int) $sock);
        }
        foreach (array_keys($this->sessions) as $id) {
            $this->flushOut($id);
        }
    }

    private function readSession(int $id): void
    {
        $s = &$this->sessions[$id];
        $data = @fread($s['sock'], 262144);
        if ($data === false || ($data === '' && feof($s['sock']))) {
            $this->end($id, 'disconnected');
            return;
        }
        $s['in'] .= $data;
        $s['bytesIn'] += strlen($data);
        try {
            $this->process($id);
        } catch (Throwable $e) {
            $this->end($id, 'protocol error: ' . $e->getMessage());
            return;
        }
        if (isset($this->sessions[$id]) && $s['bytesIn'] - $s['acked'] >= $s['ackWindow']) {
            $s['acked'] = $s['bytesIn'];
            $this->sendMsg($id, 2, 3, 0, pack('N', $s['bytesIn'] & 0xFFFFFFFF)); // Acknowledgement
        }
    }

    private function process(int $id): void
    {
        $s = &$this->sessions[$id];
        if ($s['stage'] === 0) {
            if (strlen($s['in']) < 1 + self::HANDSHAKE_SIZE) {
                return;
            }
            if (ord($s['in'][0]) !== 3) {
                throw new RuntimeException('unsupported RTMP version ' . ord($s['in'][0]));
            }
            $c1 = substr($s['in'], 1, self::HANDSHAKE_SIZE);
            $s['in'] = (string) substr($s['in'], 1 + self::HANDSHAKE_SIZE);
            $s1 = pack('N', 0) . pack('N', 0) . random_bytes(self::HANDSHAKE_SIZE - 8);
            $s['out'] .= "\x03" . $s1 . $c1; // S0 + S1 + S2 (echo of C1)
            $s['stage'] = 1;
        }
        if ($s['stage'] === 1) {
            if (strlen($s['in']) < self::HANDSHAKE_SIZE) {
                return;
            }
            $s['in'] = (string) substr($s['in'], self::HANDSHAKE_SIZE); // C2
            $s['stage'] = 2;
        }
        while (isset($this->sessions[$id]) && ($msg = $this->nextMessage($id)) !== null) {
            $this->onMessage($id, $msg);
        }
    }

    /** Parse one complete chunk from the input buffer; return a message when one completes. */
    private function nextMessage(int $id): ?array
    {
        $s = &$this->sessions[$id];
        while (true) {
            $buf = $s['in'];
            $len = strlen($buf);
            if ($len < 1) {
                return null;
            }
            $b0 = ord($buf[0]);
            $fmt = $b0 >> 6;
            $csid = $b0 & 0x3F;
            $p = 1;
            if ($csid === 0) {
                if ($len < 2) {
                    return null;
                }
                $csid = 64 + ord($buf[1]);
                $p = 2;
            } elseif ($csid === 1) {
                if ($len < 3) {
                    return null;
                }
                $csid = 64 + ord($buf[1]) + 256 * ord($buf[2]);
                $p = 3;
            }
            $hdrLen = [11, 7, 3, 0][$fmt];
            if ($len < $p + $hdrLen) {
                return null;
            }
            $prev = $s['prev'][$csid] ?? ['ts' => 0, 'delta' => 0, 'len' => 0, 'type' => 0, 'msid' => 0, 'ext' => false];
            $h = $prev;
            $tsField = null;
            if ($fmt <= 2) {
                $tsField = unpack('N', "\x00" . substr($buf, $p, 3))[1];
            }
            if ($fmt <= 1) {
                $h['len'] = unpack('N', "\x00" . substr($buf, $p + 3, 3))[1];
                $h['type'] = ord($buf[$p + 6]);
            }
            if ($fmt === 0) {
                $h['msid'] = unpack('V', substr($buf, $p + 7, 4))[1];
            }
            $p += $hdrLen;
            $ext = $tsField !== null ? $tsField === 0xFFFFFF : $prev['ext'];
            if ($ext) {
                if ($len < $p + 4) {
                    return null;
                }
                $extTs = unpack('N', substr($buf, $p, 4))[1];
                $p += 4;
                if ($tsField !== null) {
                    $tsField = $extTs;
                }
            }
            $partial = $s['partial'][$csid] ?? '';
            $starting = $partial === '';
            if ($starting) {
                if ($fmt === 0) {
                    $h['ts'] = $tsField;
                    $h['delta'] = 0;
                } elseif ($fmt === 1 || $fmt === 2) {
                    $h['delta'] = $tsField;
                    $h['ts'] = $prev['ts'] + $tsField;
                } else {
                    $h['ts'] = $prev['ts'] + $prev['delta'];
                }
            }
            $h['ext'] = $ext;
            $want = min($s['chunkIn'], $h['len'] - strlen($partial));
            if ($len < $p + $want) {
                return null;
            }
            $partial .= substr($buf, $p, $want);
            $s['in'] = (string) substr($buf, $p + $want);
            $s['prev'][$csid] = $h;
            if (strlen($partial) >= $h['len']) {
                $s['partial'][$csid] = '';
                return ['type' => $h['type'], 'ts' => $h['ts'], 'msid' => $h['msid'], 'csid' => $csid, 'data' => $partial];
            }
            $s['partial'][$csid] = $partial;
        }
    }

    private function onMessage(int $id, array $m): void
    {
        $s = &$this->sessions[$id];
        switch ($m['type']) {
            case 1: // Set Chunk Size
                $s['chunkIn'] = max(1, unpack('N', $m['data'])[1] & 0x7FFFFFFF);
                return;
            case 5: // Window Acknowledgement Size
                $s['ackWindow'] = max(1, unpack('N', $m['data'])[1]);
                return;
            case 20: // AMF0 command
                $this->command($id, Amf0::decode($m['data']), $m);
                return;
            case 8:
            case 9:
            case 18:
                if (!$s['publishing']) {
                    return;
                }
                $data = $m['data'];
                if ($m['type'] === 18) {
                    $vals = Amf0::decode($data);
                    if (($vals[0] ?? '') === '@setDataFrame') {
                        $data = Amf0::encode(...array_slice($vals, 1)); // store as onMetaData
                    }
                } elseif ($m['type'] === 9 && $s['video_codec'] === Protocol::C_NONE) {
                    $s['video_codec'] = Flv::videoCodec($data);
                } elseif ($m['type'] === 8 && $s['audio_codec'] === Protocol::C_NONE) {
                    $s['audio_codec'] = Flv::audioCodec($data);
                }
                $flv = ($s['flvStarted'] ? '' : Flv::header()) . Flv::tag($m['type'], $m['ts'], $data);
                $s['flvStarted'] = true;
                $s['tags']++;
                if (isset($this->on['onTag'])) {
                    ($this->on['onTag'])($this->sid($id), $m['type'], $m['ts'], $data, $flv, $this->info($id));
                }
                return;
        }
        // 3 Acknowledgement, 4 User Control, 6 Set Peer Bandwidth: nothing to do for an ingest server.
    }

    /** @param array<int, mixed> $args */
    private function command(int $id, array $args, array $m): void
    {
        $s = &$this->sessions[$id];
        $name = (string) ($args[0] ?? '');
        $txn = (float) ($args[1] ?? 0);
        switch ($name) {
            case 'connect':
                $s['app'] = trim((string) ($args[2]['app'] ?? ''), '/');
                $this->sendMsg($id, 2, 5, 0, pack('N', 2500000));          // Window Acknowledgement Size
                $this->sendMsg($id, 2, 6, 0, pack('N', 2500000) . "\x02"); // Set Peer Bandwidth (dynamic)
                $this->sendMsg($id, 2, 1, 0, pack('N', self::OUT_CHUNK));  // Set Chunk Size
                $this->sendMsg($id, 3, 20, 0, Amf0::encode('_result', $txn,
                    ['fmsVer' => 'FMS/3,5,7,7009', 'capabilities' => 31.0, 'mode' => 1.0],
                    ['level' => 'status', 'code' => 'NetConnection.Connect.Success', 'description' => 'Connection succeeded.', 'objectEncoding' => 0.0]));
                return;
            case 'releaseStream':
            case 'FCPublish':
                $this->sendMsg($id, 3, 20, 0, Amf0::encode('_result', $txn, null));
                return;
            case 'createStream':
                $this->sendMsg($id, 3, 20, 0, Amf0::encode('_result', $txn, null, 1.0));
                return;
            case 'publish':
                $s['key'] = (string) ($args[3] ?? '');
                if ($this->authorize && !($this->authorize)($s['app'], $s['key'])) {
                    $this->sendMsg($id, 5, 20, 1, Amf0::encode('onStatus', 0.0, null, ['level' => 'error', 'code' => 'NetStream.Publish.BadName', 'description' => 'Stream key refused.']));
                    $this->flushOut($id);
                    $this->end($id, 'stream key refused');
                    return;
                }
                $s['publishing'] = true;
                $this->sendMsg($id, 5, 20, 1, Amf0::encode('onStatus', 0.0, null,
                    ['level' => 'status', 'code' => 'NetStream.Publish.Start', 'description' => 'Publishing ' . $s['key'] . '.']));
                if (isset($this->on['onPublish'])) {
                    ($this->on['onPublish'])($this->sid($id), $this->info($id));
                }
                return;
            case 'FCUnpublish':
            case 'deleteStream':
            case 'closeStream':
                if ($s['publishing']) {
                    $this->end($id, 'unpublished');
                }
                return;
        }
    }

    private function sid(int $id): string
    {
        $s = $this->sessions[$id];
        return 'rtmp-' . preg_replace('/[^a-z0-9]/i', '', $s['app'] ?: 'live') . '-' . substr(hash('sha256', $s['key'] . '|' . $id . '|' . $s['started']), 0, 8);
    }

    /** @return array<string, mixed> (the stream key itself never leaves this process) */
    private function info(int $id): array
    {
        $s = $this->sessions[$id];
        return ['app' => $s['app'], 'stream_key_sha256' => substr(hash('sha256', $s['key']), 0, 16), 'peer' => $s['peer'], 'tags' => $s['tags'],
            'bytes_in' => $s['bytesIn'], 'video_codec' => Protocol::compressionName($s['video_codec']), 'audio_codec' => Protocol::compressionName($s['audio_codec']),
            'seconds' => round(microtime(true) - $s['started'], 2)];
    }

    /** Send a message as fmt-0 chunks of OUT_CHUNK bytes (control messages use the default 128 until announced). */
    private function sendMsg(int $id, int $csid, int $type, int $msid, string $payload): void
    {
        $s = &$this->sessions[$id];
        $size = empty($s['outChunk']) ? 128 : self::OUT_CHUNK;
        $out = chr($csid & 0x3F) . "\x00\x00\x00" . substr(pack('N', strlen($payload)), 1) . chr($type) . pack('V', $msid);
        $pieces = str_split($payload, $size) ?: [''];
        foreach ($pieces as $i => $piece) {
            $out .= ($i > 0 ? chr(0xC0 | ($csid & 0x3F)) : '') . $piece;
        }
        if ($type === 1) {
            $s['outChunk'] = true; // our chunk size is OUT_CHUNK from now on
        }
        $s['out'] .= $out;
    }

    private function flushOut(int $id): void
    {
        if (!isset($this->sessions[$id]) || $this->sessions[$id]['out'] === '') {
            return;
        }
        $s = &$this->sessions[$id];
        $n = @fwrite($s['sock'], $s['out']);
        if ($n === false) {
            $this->end($id, 'write failed');
            return;
        }
        $s['out'] = (string) substr($s['out'], $n);
    }

    private function end(int $id, string $why): void
    {
        if (!isset($this->sessions[$id])) {
            return;
        }
        $wasPublishing = $this->sessions[$id]['publishing'];
        $sid = $this->sid($id);
        $info = $this->info($id) + ['reason' => $why];
        $this->sessions[$id]['publishing'] = false;
        @fclose($this->sessions[$id]['sock']);
        unset($this->sessions[$id]);
        if ($wasPublishing && isset($this->on['onEnd'])) {
            ($this->on['onEnd'])($sid, $info);
        }
    }

    public function close(): void
    {
        foreach (array_keys($this->sessions) as $id) {
            $this->end($id, 'server closing');
        }
        if ($this->listener) {
            @fclose($this->listener);
            $this->listener = null;
        }
    }
}

/**
 * RTMP → UFCS-FQL bridge: each published stream becomes a live STREAM_CHUNK
 * sequence on Node 1's bulk connection (container FLV), flushed every
 * $flushBytes or $flushMs so latency stays bounded. The last chunk carries
 * END_OF_STREAM and the SHA-256 of the whole FLV so Node 2 can prove it intact.
 */
final class RtmpBridge
{
    /** @var array<string, array<string, mixed>> */
    private array $live = [];
    /** @var array<int, array<string, mixed>> */
    public array $finished = [];

    public function __construct(private Transport $transport, private int $flushBytes = 65536, private int $flushMs = 200)
    {
    }

    /** @return array<string, callable> callbacks for RtmpServer */
    public function callbacks(): array
    {
        return [
            'onPublish' => function (string $sid, array $info): void {
                $this->live[$sid] = ['buf' => '', 'seq' => 0, 'hash' => hash_init('sha256'), 'bytes' => 0, 'last' => microtime(true), 'info' => $info];
            },
            'onTag' => function (string $sid, int $type, int $ts, string $data, string $flv, array $info): void {
                if (!isset($this->live[$sid])) {
                    return;
                }
                $l = &$this->live[$sid];
                $now = microtime(true);
                if ($l['buf'] === '') {
                    $l['edge_first'] = $now;
                }
                $l['edge_last'] = $now;
                if ($type !== Flv::SCRIPT) {
                    $l['media_ts'] = $ts;
                }
                $l['buf'] .= $flv;
                $l['info'] = $info;
                hash_update($l['hash'], $flv);
                $l['bytes'] += strlen($flv);
                if (strlen($l['buf']) >= $this->flushBytes) {
                    $this->flush($sid, false);
                }
            },
            'onEnd' => function (string $sid, array $info): void {
                if (!isset($this->live[$sid])) {
                    return;
                }
                $this->live[$sid]['info'] = $info;
                $this->flush($sid, true);
            },
        ];
    }

    /** Time-based flush so a low-bitrate stream still moves every $flushMs. */
    public function tick(): void
    {
        foreach (array_keys($this->live) as $sid) {
            if ($this->live[$sid]['buf'] !== '' && (microtime(true) - $this->live[$sid]['last']) * 1000 >= $this->flushMs) {
                $this->flush($sid, false);
            }
        }
    }

    private function flush(string $sid, bool $final): void
    {
        $l = &$this->live[$sid];
        $codec = Protocol::compressionCode((string) ($l['info']['video_codec'] ?? 'NONE'));
        $meta = ['stream_id' => $sid, 'protocol' => 'RTMP', 'container' => 'flv', 'live' => true, 'app' => $l['info']['app'] ?? '',
            'stream_key_sha256' => $l['info']['stream_key_sha256'] ?? '', 'audio_codec' => $l['info']['audio_codec'] ?? 'NONE',
            'reliability' => 'must', 'latency_target_ms' => $this->flushMs * 2,
            // Live timing: when this chunk's first/last FLV tag reached the edge, and its last media timestamp.
            'edge_first' => $l['edge_first'] ?? null, 'edge_last' => $l['edge_last'] ?? null, 'edge_flush' => microtime(true), 'media_ts_ms' => $l['media_ts'] ?? null];
        $flags = 0;
        if ($final) {
            $flags = Protocol::F_END_OF_STREAM;
            $meta['sha256'] = hash_final($l['hash']);
            $meta['total_bytes'] = $l['bytes'];
        }
        $f = Frame::make(Protocol::STREAM_CHUNK, Protocol::VIDEO, $codec, Protocol::P_BULK, $meta, $l['buf'], 0, $l['seq'], $flags);
        $this->transport->send($f);
        $l['seq']++;
        $l['buf'] = '';
        $l['last'] = microtime(true);
        if ($final) {
            $this->finished[] = ['stream_id' => $sid, 'chunks' => $l['seq'], 'bytes' => $l['bytes'], 'sha256' => $meta['sha256']] + $l['info'];
            unset($this->live[$sid]);
        }
    }

    public function liveCount(): int
    {
        return count($this->live);
    }

    /**
     * Self-contained RTMP run: start an RTMP server on a free loopback port,
     * have ffmpeg publish $source to it in real time, and bridge the stream to
     * Node 2 over $transport. Returns what the publisher and the bridge saw.
     *
     * @return array{publisher_rc:int, port:int, stream:array<string, mixed>, seconds:float}
     */
    public static function publishFile(Transport $transport, string $source, float $timeout = 120.0): array
    {
        return self::publishWith($transport, ['-i', $source, '-c', 'copy'], $timeout);
    }

    /**
     * As publishFile(), with the publisher's input and encoder arguments given
     * (e.g. a live x264 zerolatency encode of a looped master).
     *
     * @param array<int, string> $ffmpegArgs everything between "ffmpeg -re" and "-f flv URL"
     * @return array{publisher_rc:int, port:int, stream:array<string, mixed>, seconds:float}
     */
    public static function publishWith(Transport $transport, array $ffmpegArgs, float $timeout = 120.0, ?callable $tick = null): array
    {
        $bridge = new self($transport);
        $server = new RtmpServer($bridge->callbacks(), fn (string $app, string $key) => $key === 'lab');
        $port = 0;
        for ($i = 0; $i < 8 && $port === 0; $i++) {
            try {
                $try = random_int(20000, 60000);
                $server->listen('127.0.0.1', $try);
                $port = $try;
            } catch (Throwable) {
            }
        }
        if ($port === 0) {
            throw new RuntimeException('No free port for the RTMP server');
        }
        $proc = proc_open(array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-re'], $ffmpegArgs, ['-f', 'flv', 'rtmp://127.0.0.1:' . $port . '/live/lab']),
            [0 => ['file', '/dev/null', 'r'], 1 => ['file', '/dev/null', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
        $t0 = microtime(true);
        while (microtime(true) - $t0 < $timeout) {
            $server->tick(0.005);
            $bridge->tick();
            if ($tick !== null) {
                $tick();
            }
            $transport->pump(0);
            if (!proc_get_status($proc)['running'] && $server->activeSessions() === 0 && $bridge->liveCount() === 0) {
                break;
            }
        }
        $rc = proc_close($proc);
        $transport->flush(60);
        $server->close();
        return ['publisher_rc' => $rc, 'port' => $port, 'stream' => $bridge->finished[0] ?? [], 'seconds' => round(microtime(true) - $t0, 3)];
    }
}

/** RTMP egress: push a file or a Node 2 output to any RTMP endpoint (YouTube, Twitch, a CDN) via ffmpeg. */
final class RtmpPublisher
{
    /** @return array{code:int, stderr:string, ms:float} */
    public static function push(string $source, string $url, bool $realtime = true, bool $copy = true): array
    {
        if (!preg_match('#^rtmps?://#', $url)) {
            throw new InvalidArgumentException('RTMP URL must start with rtmp:// or rtmps://');
        }
        $args = [MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error'];
        if ($realtime) {
            $args[] = '-re';
        }
        $args = array_merge($args, ['-i', $source], $copy ? ['-c', 'copy'] : ['-c:v', 'libx264', '-preset', 'veryfast', '-c:a', 'aac'], ['-f', 'flv', $url]);
        $t = hrtime(true);
        $r = MediaCodec::exec($args);
        return ['code' => $r['code'], 'stderr' => trim($r['stderr']), 'ms' => round((hrtime(true) - $t) / 1e6, 1)];
    }
}
