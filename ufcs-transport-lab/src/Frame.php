<?php

declare(strict_types=1);

/**
 * One UFCS-FQL/1 frame.
 *
 *   +-------------------+---------------+-----------------+------------------------+
 *   | Header (32 bytes) | Meta (MetaLen)| Payload         | Footer                 |
 *   |                   | UTF-8 JSON    | (PayloadLen)    | CRC32 (4) [+ Sig (64)] |
 *   +-------------------+---------------+-----------------+------------------------+
 *
 * CRC32 (IEEE) covers header + meta + payload. When the SIGNED flag is set an
 * Ed25519 signature over header + meta + payload + CRC follows the CRC.
 */
final class Frame
{
    public function __construct(
        public int $msgType,
        public int $contentType,
        public int $compression,
        public int $flags,
        public string $meta,
        public string $payload,
        public int $messageId,
        public int $sequence = 0,
        public int $reserved = 0,
        public int $version = Protocol::VERSION,
        public ?string $signature = null,
        public ?int $crc = null,
    ) {
    }

    /**
     * Convenience constructor: meta as an array, priority as a class number.
     *
     * @param array<string, mixed> $meta
     */
    public static function make(
        int $msgType,
        int $contentType,
        int $compression,
        int $priority,
        array $meta,
        string $payload,
        int $messageId,
        int $sequence = 0,
        int $extraFlags = 0,
    ): self {
        $meta['priority'] = $priority;
        ksort($meta);
        return new self(
            $msgType,
            $contentType,
            $compression,
            Protocol::priorityFlag($priority) | $extraFlags,
            self::encodeMeta($meta),
            $payload,
            $messageId,
            $sequence,
        );
    }

    /** @param array<string, mixed> $meta */
    public static function encodeMeta(array $meta): string
    {
        return json_encode($meta, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION | JSON_THROW_ON_ERROR);
    }

    /** @return array<string, mixed> */
    public function metaArray(): array
    {
        if ($this->meta === '') {
            return [];
        }
        $decoded = json_decode($this->meta, true);
        return is_array($decoded) ? $decoded : [];
    }

    public function priority(): int
    {
        return Protocol::priorityFromFlags($this->flags);
    }

    public function header(): string
    {
        return pack(
            'nCCCCnNNJNN',
            Protocol::MAGIC,
            $this->version,
            $this->msgType,
            $this->contentType,
            $this->compression,
            $this->flags & 0xFFFF,
            strlen($this->payload),
            strlen($this->meta),
            $this->messageId,
            $this->sequence & 0xFFFFFFFF,
            $this->reserved & 0xFFFFFFFF,
        );
    }

    /**
     * Serialise to wire bytes. Passing an Ed25519 secret key signs the frame
     * (and sets the SIGNED flag); otherwise the SIGNED flag is cleared.
     */
    public function encode(?string $secretKey = null): string
    {
        if ($secretKey !== null) {
            $this->flags |= Protocol::F_SIGNED;
        } else {
            $this->flags &= ~Protocol::F_SIGNED;
            $this->signature = null;
        }
        $body = $this->header() . $this->meta . $this->payload;
        $this->crc = crc32($body);
        $wire = $body . pack('N', $this->crc);
        if ($secretKey !== null) {
            $this->signature = sodium_crypto_sign_detached($wire, $secretKey);
            $wire .= $this->signature;
        }
        return $wire;
    }

    public function wireLength(): int
    {
        return Protocol::HEADER_LEN + strlen($this->meta) + strlen($this->payload) + Protocol::CRC_LEN
            + (($this->flags & Protocol::F_SIGNED) ? Protocol::SIGNATURE_LEN : 0);
    }

    /**
     * Parse the fixed header.
     *
     * @return array{magic:int,version:int,msgType:int,contentType:int,compression:int,flags:int,payloadLen:int,metaLen:int,messageId:int,sequence:int,reserved:int}
     */
    public static function parseHeader(string $bytes): array
    {
        if (strlen($bytes) < Protocol::HEADER_LEN) {
            throw new FrameException('Header needs ' . Protocol::HEADER_LEN . ' bytes, got ' . strlen($bytes));
        }
        $h = unpack('nmagic/Cversion/CmsgType/CcontentType/Ccompression/nflags/NpayloadLen/NmetaLen/JmessageId/Nsequence/Nreserved', $bytes);
        return array_map('intval', $h);
    }

    /** Total bytes the frame described by this header occupies on the wire. */
    public static function totalLength(array $h): int
    {
        return Protocol::HEADER_LEN + $h['metaLen'] + $h['payloadLen'] + Protocol::CRC_LEN
            + (($h['flags'] & Protocol::F_SIGNED) ? Protocol::SIGNATURE_LEN : 0);
    }

    /** A header is plausible when magic, version, enums and lengths are all in range. */
    public static function plausible(array $h): ?string
    {
        if ($h['magic'] !== Protocol::MAGIC) {
            return sprintf('bad magic 0x%04X', $h['magic']);
        }
        if ($h['version'] !== Protocol::VERSION) {
            return 'unsupported version ' . $h['version'];
        }
        if (!isset(Protocol::MSG_TYPES[$h['msgType']])) {
            return 'unknown MsgType ' . $h['msgType'];
        }
        if (!isset(Protocol::CONTENT_TYPES[$h['contentType']])) {
            return 'unknown ContentType ' . $h['contentType'];
        }
        if (!isset(Protocol::COMPRESSIONS[$h['compression']])) {
            return 'unknown CompressionType ' . $h['compression'];
        }
        if ($h['metaLen'] > Protocol::MAX_META_LEN) {
            return 'MetaLen ' . $h['metaLen'] . ' exceeds cap';
        }
        if ($h['payloadLen'] > Protocol::MAX_PAYLOAD_LEN) {
            return 'PayloadLen ' . $h['payloadLen'] . ' exceeds cap';
        }
        return null;
    }

    /**
     * Decode exactly one frame from $bytes (which must hold the whole frame).
     * Verifies CRC32, and the signature when the frame is signed and a public
     * key is supplied (or required).
     */
    public static function decode(string $bytes, ?string $publicKey = null, bool $requireSignature = false): self
    {
        $h = self::parseHeader($bytes);
        if (($why = self::plausible($h)) !== null) {
            throw new FrameException($why);
        }
        $total = self::totalLength($h);
        if (strlen($bytes) < $total) {
            throw new FrameException('Truncated frame: need ' . $total . ' bytes, got ' . strlen($bytes));
        }
        $bodyLen = Protocol::HEADER_LEN + $h['metaLen'] + $h['payloadLen'];
        $crc = unpack('N', substr($bytes, $bodyLen, 4))[1];
        if (crc32(substr($bytes, 0, $bodyLen)) !== $crc) {
            throw new FrameException('CRC32 mismatch');
        }
        $signature = null;
        if ($h['flags'] & Protocol::F_SIGNED) {
            $signature = substr($bytes, $bodyLen + 4, Protocol::SIGNATURE_LEN);
            if ($publicKey !== null && !sodium_crypto_sign_verify_detached($signature, substr($bytes, 0, $bodyLen + 4), $publicKey)) {
                throw new FrameException('Ed25519 signature does not verify');
            }
        } elseif ($requireSignature) {
            throw new FrameException('Unsigned frame refused (signature required)');
        }
        return new self(
            $h['msgType'],
            $h['contentType'],
            $h['compression'],
            $h['flags'],
            substr($bytes, Protocol::HEADER_LEN, $h['metaLen']),
            substr($bytes, Protocol::HEADER_LEN + $h['metaLen'], $h['payloadLen']),
            $h['messageId'],
            $h['sequence'],
            $h['reserved'],
            $h['version'],
            $signature,
            $crc,
        );
    }

    /** @return array<string, mixed> Human-readable summary (no payload bytes). */
    public function describe(): array
    {
        return [
            'msg_type' => Protocol::MSG_TYPES[$this->msgType] ?? $this->msgType,
            'content_type' => Protocol::CONTENT_TYPES[$this->contentType] ?? $this->contentType,
            'compression' => Protocol::compressionName($this->compression),
            'flags' => Protocol::flagNames($this->flags),
            'priority' => Protocol::PRIORITIES[$this->priority()],
            'message_id' => $this->messageId,
            'sequence' => $this->sequence,
            'meta_len' => strlen($this->meta),
            'payload_len' => strlen($this->payload),
            'wire_len' => $this->wireLength(),
            'crc32' => $this->crc === null ? null : sprintf('%08x', $this->crc),
            'signed' => $this->signature !== null,
            'meta' => $this->metaArray(),
        ];
    }
}

final class FrameException extends RuntimeException
{
}

/**
 * Lab node identities. Keys are derived from the node id so every run is
 * reproducible — this is a demonstration keyring, NOT a secure key store.
 */
final class NodeKeys
{
    /** @return array{public:string, secret:string} */
    public static function forNode(string $nodeId): array
    {
        $seed = sodium_crypto_generichash('ufcs-transport-lab/node/' . $nodeId, '', SODIUM_CRYPTO_SIGN_SEEDBYTES);
        $pair = sodium_crypto_sign_seed_keypair($seed);
        return [
            'public' => sodium_crypto_sign_publickey($pair),
            'secret' => sodium_crypto_sign_secretkey($pair),
        ];
    }
}
