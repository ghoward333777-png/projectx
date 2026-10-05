<?php

declare(strict_types=1);

/**
 * Incremental frame parser for a TCP byte stream (Node 2's stream reader).
 *
 * Bytes arrive in arbitrary pieces; push() them and call next() until it
 * returns null. A frame that fails its header plausibility or CRC check costs
 * that frame only: the reader skips one byte past the bad anchor, scans for the
 * next magic + version, and carries on (Registry F61 — resynchronisation to
 * the next valid frame without reparsing the preceding one).
 */
final class FrameReader
{
    private string $buffer = '';
    private int $offset = 0;

    /** Stats a receiver reports. */
    public int $framesOk = 0;
    public int $corruptFrames = 0;
    public int $skippedBytes = 0;
    public int $bytesIn = 0;
    /** @var array<int, string> last few corruption reasons */
    public array $errors = [];

    /** @var null|callable(Frame): ?string Resolves the Ed25519 public key for a signed frame. */
    private $keyResolver;

    public function __construct(?callable $keyResolver = null, private bool $requireSignature = false)
    {
        $this->keyResolver = $keyResolver;
    }

    public function push(string $bytes): void
    {
        $this->bytesIn += strlen($bytes);
        if ($this->offset > 1048576) {
            $this->buffer = substr($this->buffer, $this->offset);
            $this->offset = 0;
        }
        $this->buffer .= $bytes;
    }

    public function buffered(): int
    {
        return strlen($this->buffer) - $this->offset;
    }

    /** Return the next complete, verified frame, or null when more bytes are needed. */
    public function next(): ?Frame
    {
        while (true) {
            $available = strlen($this->buffer) - $this->offset;
            if ($available < Protocol::HEADER_LEN) {
                return null;
            }
            $h = Frame::parseHeader(substr($this->buffer, $this->offset, Protocol::HEADER_LEN));
            if (($why = Frame::plausible($h)) !== null) {
                $this->resync($why);
                continue;
            }
            $total = Frame::totalLength($h);
            if ($available < $total) {
                return null;
            }
            try {
                $frame = Frame::decode(substr($this->buffer, $this->offset, $total));
                $this->checkSignature($frame);
            } catch (FrameException $e) {
                $this->resync($e->getMessage());
                continue;
            }
            $this->offset += $total;
            $this->framesOk++;
            return $frame;
        }
    }

    /**
     * End of stream: whatever is left can never complete. Resynchronise through
     * it so frames hidden behind a corrupt length are still recovered.
     *
     * @return array<int, Frame>
     */
    public function finish(): array
    {
        $frames = [];
        while ($this->buffered() > 0) {
            $frame = $this->next();
            if ($frame !== null) {
                $frames[] = $frame;
                continue;
            }
            if ($this->buffered() === 0) {
                break;
            }
            $this->resync('truncated frame at end of stream');
        }
        return $frames;
    }

    private function checkSignature(Frame $frame): void
    {
        if ($frame->signature === null) {
            if ($this->requireSignature) {
                throw new FrameException('Unsigned frame refused (signature required)');
            }
            return;
        }
        $key = $this->keyResolver ? ($this->keyResolver)($frame) : null;
        if ($key === null) {
            if ($this->requireSignature) {
                throw new FrameException('Signed by an unknown node');
            }
            return;
        }
        $signed = $frame->header() . $frame->meta . $frame->payload . pack('N', $frame->crc);
        if (!sodium_crypto_sign_verify_detached($frame->signature, $signed, $key)) {
            throw new FrameException('Ed25519 signature does not verify');
        }
    }

    private function resync(string $why): void
    {
        $this->corruptFrames++;
        $this->errors[] = $why;
        if (count($this->errors) > 20) {
            array_shift($this->errors);
        }
        $anchor = pack('nC', Protocol::MAGIC, Protocol::VERSION);
        $next = strpos($this->buffer, $anchor, $this->offset + 1);
        if ($next === false) {
            // Keep the last two bytes: they may be the start of an anchor still arriving.
            $keep = min(2, strlen($this->buffer) - $this->offset);
            $newOffset = strlen($this->buffer) - $keep;
            $this->skippedBytes += max(1, $newOffset - $this->offset);
            $this->offset = max($this->offset + 1, $newOffset);
            if ($this->offset > strlen($this->buffer)) {
                $this->offset = strlen($this->buffer);
            }
            return;
        }
        $this->skippedBytes += $next - $this->offset;
        $this->offset = $next;
    }
}
