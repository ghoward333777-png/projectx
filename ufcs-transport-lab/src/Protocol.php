<?php

declare(strict_types=1);

/**
 * UFCS-FQL/1 wire protocol constants.
 *
 * Every byte between Node 1 (producer) and Node 2 (consumer) travels inside one
 * frame: a fixed 32-byte big-endian header, a UTF-8 JSON meta block, a binary
 * payload already compressed for its content type, and a footer carrying a
 * CRC32 plus an optional Ed25519 signature.
 *
 * The specification sketched the magic as "0xFQ10", which is not hexadecimal.
 * The concrete value is 0xF051: 0xF0 (a byte that can never begin UTF-8 text,
 * so a frame boundary is unambiguous inside a byte stream) followed by ASCII
 * 'Q'. Together with the version byte it is the resynchronisation anchor
 * (Registry F61, QueryBook Format: "a corrupt frame costs one frame rather
 * than the stream").
 */
final class Protocol
{
    public const MAGIC = 0xF051;
    public const VERSION = 1;
    public const NAME = 'UFCS-FQL-1';
    public const HEADER_LEN = 32;
    public const CRC_LEN = 4;
    public const SIGNATURE_LEN = 64;

    /** Plausibility caps used by the reader before it trusts a header's lengths. */
    public const MAX_META_LEN = 1048576;        // 1 MiB
    public const MAX_PAYLOAD_LEN = 67108864;    // 64 MiB

    // --- MsgType (header byte 3) -----------------------------------------
    public const FACT_BATCH = 0;
    public const STREAM_CHUNK = 1;
    public const CONTROL = 2;

    // --- ContentType (header byte 4) -------------------------------------
    public const TEXT = 0;
    public const IMAGE = 1;
    public const VIDEO = 2;
    public const AUDIO = 3;
    public const MIXED = 4;

    // --- CompressionType (header byte 5) ---------------------------------
    // 0-5 are the specification's codes; 6+ are lab extensions.
    public const C_NONE = 0;
    public const C_ZSTD = 1;
    public const C_GZIP = 2;
    public const C_H264 = 3;
    public const C_OPUS = 4;
    public const C_WEBP = 5;
    public const C_H265 = 6;
    public const C_AV1 = 7;
    public const C_AAC = 8;
    public const C_UFCS_DICT = 9;   // raw DEFLATE primed with the UFCS field dictionary

    // --- Flags (header bytes 6-7) ----------------------------------------
    public const F_PRIORITY_CONTROL = 0x0001;
    public const F_PRIORITY_NORMAL = 0x0002;
    public const F_PRIORITY_BULK = 0x0004;
    public const F_SIGNED = 0x0008;        // footer carries a 64-byte Ed25519 signature
    public const F_END_OF_STREAM = 0x0010; // last STREAM_CHUNK of a stream
    public const F_ACK_REQUESTED = 0x0020; // reliability "must": receiver acknowledges
    public const F_PRIORITY_MASK = 0x0007;

    // --- Priority classes -------------------------------------------------
    public const P_CONTROL = 0;
    public const P_NORMAL = 1;
    public const P_BULK = 2;

    public const MSG_TYPES = [0 => 'FACT_BATCH', 1 => 'STREAM_CHUNK', 2 => 'CONTROL'];
    public const CONTENT_TYPES = [0 => 'TEXT', 1 => 'IMAGE', 2 => 'VIDEO', 3 => 'AUDIO', 4 => 'MIXED'];
    public const COMPRESSIONS = [
        0 => 'NONE', 1 => 'ZSTD', 2 => 'GZIP', 3 => 'H264', 4 => 'OPUS',
        5 => 'WEBP', 6 => 'H265', 7 => 'AV1', 8 => 'AAC', 9 => 'UFCS_DICT',
    ];
    public const PRIORITIES = [0 => 'control', 1 => 'normal', 2 => 'bulk'];
    public const FLAG_NAMES = [
        0x0001 => 'PRIORITY_CONTROL', 0x0002 => 'PRIORITY_NORMAL', 0x0004 => 'PRIORITY_BULK',
        0x0008 => 'SIGNED', 0x0010 => 'END_OF_STREAM', 0x0020 => 'ACK_REQUESTED',
    ];

    /** Header field layout: [name, offset, size, pack code] — the single source of truth. */
    public const HEADER_LAYOUT = [
        ['Magic', 0, 2, 'n'],
        ['Version', 2, 1, 'C'],
        ['MsgType', 3, 1, 'C'],
        ['ContentType', 4, 1, 'C'],
        ['CompressionType', 5, 1, 'C'],
        ['Flags', 6, 2, 'n'],
        ['PayloadLen', 8, 4, 'N'],
        ['MetaLen', 12, 4, 'N'],
        ['MessageID', 16, 8, 'J'],
        ['Sequence', 24, 4, 'N'],
        ['Reserved', 28, 4, 'N'],
    ];

    /** Connection port offset from the base port, per priority class. */
    public static function portFor(int $basePort, int $priority): int
    {
        return $basePort + max(0, min(2, $priority));
    }

    public static function priorityFlag(int $priority): int
    {
        return [self::F_PRIORITY_CONTROL, self::F_PRIORITY_NORMAL, self::F_PRIORITY_BULK][max(0, min(2, $priority))];
    }

    /** The highest-urgency priority bit set wins; no bit set means normal. */
    public static function priorityFromFlags(int $flags): int
    {
        if ($flags & self::F_PRIORITY_CONTROL) {
            return self::P_CONTROL;
        }
        if ($flags & self::F_PRIORITY_NORMAL) {
            return self::P_NORMAL;
        }
        if ($flags & self::F_PRIORITY_BULK) {
            return self::P_BULK;
        }
        return self::P_NORMAL;
    }

    /** @return array<int, string> */
    public static function flagNames(int $flags): array
    {
        $names = [];
        foreach (self::FLAG_NAMES as $bit => $name) {
            if ($flags & $bit) {
                $names[] = $name;
            }
        }
        return $names;
    }

    public static function compressionName(int $code): string
    {
        return self::COMPRESSIONS[$code] ?? ('UNKNOWN_' . $code);
    }

    public static function compressionCode(string $name): int
    {
        $code = array_search(strtoupper($name), self::COMPRESSIONS, true);
        if ($code === false) {
            throw new InvalidArgumentException('Unknown compression type: ' . $name);
        }
        return (int) $code;
    }

    public static function contentCode(string $name): int
    {
        $code = array_search(strtoupper($name), self::CONTENT_TYPES, true);
        if ($code === false) {
            throw new InvalidArgumentException('Unknown content type: ' . $name);
        }
        return (int) $code;
    }
}
