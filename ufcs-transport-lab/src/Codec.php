<?php

declare(strict_types=1);

/**
 * Lossless byte codecs (text, fact batches, multipart envelopes).
 *
 * NONE, GZIP and UFCS_DICT are built into PHP (zlib). ZSTD uses the `zstd`
 * command-line tool when it is installed — PHP has no bundled Zstandard — and
 * is reported unavailable otherwise; a sender never labels a payload ZSTD
 * unless it really is.
 *
 * Media codecs (H.264/H.265/AV1, Opus/AAC, WebP) are lossy transcoders and
 * live in MediaCodec; on the receiving side their payload is the bitstream.
 */
final class Codec
{
    /**
     * Preset dictionary for UFCS_DICT: the structural vocabulary of a UFCS
     * record (field names, enum values, JSON punctuation), most frequent last
     * as DEFLATE prefers. Priming the window with it makes small batches
     * compress like large ones. Changing it changes the wire format.
     */
    public const UFCS_DICTIONARY =
        '"version": {"chain_id": "", "version": 1, "supersedes": null}, "links": [{"rel": "same_subject", "target_fuid": "'
        . '"safety": {"classification": "PUBLIC", "acl": ["reader"]}, "embedding_ref": "emb:", "confidence_trend": "STABLE"'
        . '"ASCENDING""DESCENDING""official""academic""encyclopedia""news""web""SRC-GOV""Government Registry""SRC-WEB""Web Crawl"'
        . '"provenance": {"ref": "", "chain_index": , "signature": "ed25519:"}, "certification": {"authority_class": "", "trust_score": 0.'
        . '"temporal": {"anchor": "2026-05-29T12:00:00Z", "ingested": "2026-05-29T12:00:00Z", "attestation": "2025-07-28T12:00:00Z"}, '
        . '"source_diversity": 1.0, "sources": [{"id": "SRC-", "name": "", "class": "", "reputation": 0.'
        . '"confidence": {"alpha": 0., "beta": 0., "score": 0., "evidence_weight": , "credible_interval": [0., 1]}, '
        . '"polarity": "+", "semantic_fingerprint": "'
        . '{"fuid": "", "fact_type": "assertion", "group": "", "nucleus": {"subject": "", "predicate": "", "object": ""}, ';

    private static ?string $zstdBinary = null;

    /** @return array<string, array{available:bool, kind:string, note:string}> */
    public static function capabilities(): array
    {
        $zstd = self::zstdBinary();
        $caps = [
            'NONE' => ['available' => true, 'kind' => 'lossless', 'note' => 'identity'],
            'GZIP' => ['available' => function_exists('gzencode'), 'kind' => 'lossless', 'note' => 'RFC 1952 via PHP zlib'],
            'ZSTD' => ['available' => $zstd !== '', 'kind' => 'lossless', 'note' => $zstd !== '' ? 'zstd CLI: ' . $zstd : 'install the zstd command-line tool'],
            'UFCS_DICT' => ['available' => function_exists('deflate_init'), 'kind' => 'lossless', 'note' => 'raw DEFLATE primed with the UFCS field dictionary'],
            'WEBP' => ['available' => function_exists('imagewebp'), 'kind' => 'lossy image', 'note' => 'PHP GD'],
        ];
        foreach (MediaCodec::codecMatrix() as $name => $row) {
            $caps[$name] = $row;
        }
        return $caps;
    }

    public static function available(int $code): bool
    {
        $name = Protocol::compressionName($code);
        return (bool) (self::capabilities()[$name]['available'] ?? false);
    }

    public static function isLossless(int $code): bool
    {
        return in_array($code, [Protocol::C_NONE, Protocol::C_GZIP, Protocol::C_ZSTD, Protocol::C_UFCS_DICT], true);
    }

    /** Best lossless codec this node can actually run (ZSTD, else GZIP). */
    public static function preferredText(): int
    {
        return self::zstdBinary() !== '' ? Protocol::C_ZSTD : Protocol::C_GZIP;
    }

    public static function compress(int $code, string $data, int $level = 0): string
    {
        switch ($code) {
            case Protocol::C_NONE:
                return $data;
            case Protocol::C_GZIP:
                return gzencode($data, $level > 0 ? min(9, $level) : 6);
            case Protocol::C_UFCS_DICT:
                $ctx = deflate_init(ZLIB_ENCODING_RAW, ['level' => $level > 0 ? min(9, $level) : 9, 'dictionary' => self::UFCS_DICTIONARY]);
                return deflate_add($ctx, $data, ZLIB_FINISH);
            case Protocol::C_ZSTD:
                return self::zstd(['-q', '-c', '-' . ($level > 0 ? min(19, $level) : 9)], $data);
        }
        throw new InvalidArgumentException(Protocol::compressionName($code) . ' is not a lossless byte codec');
    }

    public static function decompress(int $code, string $data): string
    {
        switch ($code) {
            case Protocol::C_NONE:
                return $data;
            case Protocol::C_GZIP:
                $out = @gzdecode($data);
                if ($out === false) {
                    throw new RuntimeException('GZIP payload does not decode');
                }
                return $out;
            case Protocol::C_UFCS_DICT:
                $ctx = inflate_init(ZLIB_ENCODING_RAW, ['dictionary' => self::UFCS_DICTIONARY]);
                $out = @inflate_add($ctx, $data, ZLIB_FINISH);
                if ($out === false) {
                    throw new RuntimeException('UFCS_DICT payload does not decode');
                }
                return $out;
            case Protocol::C_ZSTD:
                return self::zstd(['-q', '-d', '-c'], $data);
        }
        // Lossy media bitstreams are delivered as-is.
        return $data;
    }

    public static function zstdBinary(): string
    {
        if (self::$zstdBinary === null) {
            self::$zstdBinary = '';
            $env = getenv('UFCS_LAB_ZSTD');
            if ($env === 'off') {
                return '';
            }
            foreach (array_filter([$env ?: null, '/usr/bin/zstd', '/usr/local/bin/zstd', '/opt/homebrew/bin/zstd']) as $candidate) {
                if (is_file($candidate) && is_executable($candidate)) {
                    return self::$zstdBinary = $candidate;
                }
            }
            $found = trim((string) @shell_exec('command -v zstd 2>/dev/null'));
            if ($found !== '' && is_executable($found)) {
                self::$zstdBinary = $found;
            }
        }
        return self::$zstdBinary;
    }

    /** @param array<int, string> $args */
    private static function zstd(array $args, string $input): string
    {
        $bin = self::zstdBinary();
        if ($bin === '') {
            throw new RuntimeException('ZSTD unavailable: install the zstd command-line tool');
        }
        // Input via a temp file so a large payload can never deadlock the pipes.
        $tmp = tempnam(sys_get_temp_dir(), 'ufcs-zstd-');
        file_put_contents($tmp, $input);
        $proc = proc_open(array_merge([$bin], $args, [$tmp]), [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
        if (!is_resource($proc)) {
            @unlink($tmp);
            throw new RuntimeException('Could not start zstd');
        }
        $out = stream_get_contents($pipes[1]);
        $err = stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($proc);
        @unlink($tmp);
        if ($code !== 0) {
            throw new RuntimeException('zstd failed: ' . trim((string) $err));
        }
        return (string) $out;
    }
}

/**
 * MIXED payload: several parts, each with its own content type and codec.
 *
 *   "QBMP" | u16 part count | per part:
 *     u8 content_type | u8 compression | u16 name length | name | u32 length | bytes
 *
 * The whole block may then be wrapped by the frame's own CompressionType
 * (ZSTD/GZIP) — useful when parts are text, pointless for media parts.
 */
final class Multipart
{
    public const MAGIC = 'QBMP';

    /** @param array<int, array{name:string, content_type:int, compression:int, bytes:string}> $parts */
    public static function encode(array $parts): string
    {
        $out = self::MAGIC . pack('n', count($parts));
        foreach ($parts as $p) {
            $out .= pack('CCn', $p['content_type'], $p['compression'], strlen($p['name'])) . $p['name']
                . pack('N', strlen($p['bytes'])) . $p['bytes'];
        }
        return $out;
    }

    /** @return array<int, array{name:string, content_type:int, compression:int, bytes:string}> */
    public static function decode(string $block): array
    {
        if (substr($block, 0, 4) !== self::MAGIC) {
            throw new RuntimeException('Not a multipart block');
        }
        $count = unpack('n', substr($block, 4, 2))[1];
        $pos = 6;
        $parts = [];
        for ($i = 0; $i < $count; $i++) {
            if ($pos + 4 > strlen($block)) {
                throw new RuntimeException('Multipart block truncated');
            }
            $h = unpack('Cct/Ccomp/nnameLen', substr($block, $pos, 4));
            $pos += 4;
            if ($pos + $h['nameLen'] + 4 > strlen($block)) {
                throw new RuntimeException('Multipart block truncated');
            }
            $name = substr($block, $pos, $h['nameLen']);
            $pos += $h['nameLen'];
            $len = unpack('N', substr($block, $pos, 4))[1];
            $pos += 4;
            if ($pos + $len > strlen($block)) {
                throw new RuntimeException('Multipart part "' . $name . '" truncated');
            }
            $parts[] = ['name' => $name, 'content_type' => $h['ct'], 'compression' => $h['comp'], 'bytes' => substr($block, $pos, $len)];
            $pos += $len;
        }
        return $parts;
    }
}

/**
 * Content classifier: decides ContentType from magic bytes (then extension),
 * and the transport policy for it — codec, message type and priority class.
 */
final class ContentClassifier
{
    /** Media at or above this size is streamed as STREAM_CHUNK frames. */
    public const STREAM_THRESHOLD = 1048576;

    public static function classify(string $bytes, string $name = ''): int
    {
        $head = substr($bytes, 0, 16);
        if (str_starts_with($head, "\x89PNG") || str_starts_with($head, "\xFF\xD8\xFF") || str_starts_with($head, 'GIF8')
            || (str_starts_with($head, 'RIFF') && substr($head, 8, 4) === 'WEBP') || substr($head, 4, 8) === 'ftypavif') {
            return Protocol::IMAGE;
        }
        if ((str_starts_with($head, 'RIFF') && substr($head, 8, 4) === 'WAVE') || str_starts_with($head, 'OggS')
            || str_starts_with($head, 'fLaC') || str_starts_with($head, 'ID3') || (strlen($head) > 1 && ord($head[0]) === 0xFF && (ord($head[1]) & 0xF0) === 0xF0)) {
            return Protocol::AUDIO;
        }
        if (substr($head, 4, 4) === 'ftyp' || str_starts_with($head, "\x1A\x45\xDF\xA3") || str_starts_with($head, 'YUV4MPEG2')
            || (strlen($head) > 0 && ord($head[0]) === 0x47 && strlen($bytes) > 188 && ord($bytes[188]) === 0x47)
            || (str_starts_with($head, 'RIFF') && substr($head, 8, 3) === 'AVI')) {
            return Protocol::VIDEO;
        }
        if (str_starts_with($head, Multipart::MAGIC)) {
            return Protocol::MIXED;
        }
        $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
        $byExt = [
            'png' => Protocol::IMAGE, 'jpg' => Protocol::IMAGE, 'jpeg' => Protocol::IMAGE, 'gif' => Protocol::IMAGE, 'webp' => Protocol::IMAGE,
            'wav' => Protocol::AUDIO, 'ogg' => Protocol::AUDIO, 'opus' => Protocol::AUDIO, 'mp3' => Protocol::AUDIO, 'aac' => Protocol::AUDIO, 'flac' => Protocol::AUDIO,
            'mp4' => Protocol::VIDEO, 'mkv' => Protocol::VIDEO, 'webm' => Protocol::VIDEO, 'ts' => Protocol::VIDEO, 'y4m' => Protocol::VIDEO, 'mov' => Protocol::VIDEO, 'avi' => Protocol::VIDEO,
        ];
        return $byExt[$ext] ?? Protocol::TEXT;
    }

    /**
     * Transport policy for a classified payload.
     *
     * @return array{content_type:int, compression:int, msg_type:int, priority:int, reason:string}
     */
    public static function policy(int $contentType, int $size): array
    {
        switch ($contentType) {
            case Protocol::VIDEO:
                $streamed = $size >= self::STREAM_THRESHOLD;
                return ['content_type' => $contentType, 'compression' => Protocol::C_H264, 'msg_type' => $streamed ? Protocol::STREAM_CHUNK : Protocol::FACT_BATCH,
                    'priority' => Protocol::P_BULK, 'reason' => 'video: H.264 transcode, bitrate from link capacity; ' . ($streamed ? 'large → streamed chunks' : 'short clip → single frame')];
            case Protocol::AUDIO:
                $streamed = $size >= self::STREAM_THRESHOLD;
                return ['content_type' => $contentType, 'compression' => Protocol::C_OPUS, 'msg_type' => $streamed ? Protocol::STREAM_CHUNK : Protocol::FACT_BATCH,
                    'priority' => Protocol::P_BULK, 'reason' => 'audio: Opus, speech downsampled to 24 kHz mono; ' . ($streamed ? 'large → streamed chunks' : 'short clip → single frame')];
            case Protocol::IMAGE:
                return ['content_type' => $contentType, 'compression' => Protocol::C_WEBP, 'msg_type' => Protocol::FACT_BATCH,
                    'priority' => Protocol::P_BULK, 'reason' => 'image: WebP re-encode, optional downscale'];
            case Protocol::MIXED:
                return ['content_type' => $contentType, 'compression' => Codec::preferredText(), 'msg_type' => Protocol::FACT_BATCH,
                    'priority' => Protocol::P_NORMAL, 'reason' => 'mixed: per-part codecs, envelope wrapped'];
        }
        return ['content_type' => Protocol::TEXT, 'compression' => Codec::preferredText(), 'msg_type' => Protocol::FACT_BATCH,
            'priority' => Protocol::P_NORMAL, 'reason' => 'text: batched UFCS facts, ' . Protocol::compressionName(Codec::preferredText())];
    }
}
