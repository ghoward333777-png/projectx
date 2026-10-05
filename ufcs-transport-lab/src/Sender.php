<?php

declare(strict_types=1);

/**
 * Node 1 — the producer. Turns UFCS facts, media and FQL queries into frames:
 *
 *   UFCS/FQL encoder → content classifier → compressor → framer → transport manager
 *
 * Every method returns what it measured (sizes, codec, timings) so the
 * benchmark and the dashboard report real numbers, not intentions.
 */
final class Sender
{
    private int $streamCounter = 0;

    public function __construct(public Transport $transport, private string $queryPrefix = 'q')
    {
    }

    /**
     * Batch UFCS facts into FACT_BATCH frames (default 1,000 per frame).
     *
     * @param array<int, array<string, mixed>> $records
     * @return array<string, mixed>
     */
    public function sendFacts(array $records, int $codec, int $batchSize = 1000, int $priority = Protocol::P_NORMAL, string $queryId = '', int $level = 0): array
    {
        $raw = 0;
        $payload = 0;
        $wire = 0;
        $frames = 0;
        $compressNs = 0;
        foreach (array_chunk($records, max(1, $batchSize)) as $i => $batch) {
            $jsonl = Ufcs::encodeBatch($batch);
            $t0 = hrtime(true);
            $body = Codec::compress($codec, $jsonl, $level);
            $compressNs += hrtime(true) - $t0;
            $meta = Ufcs::batchContext($batch) + [
                'query_id' => $queryId !== '' ? $queryId : $this->queryPrefix . '-batch-' . $i,
                'fact_count' => count($batch),
                'raw_bytes' => strlen($jsonl),
                'reliability' => 'must',
                'latency_target_ms' => $priority === Protocol::P_CONTROL ? 50 : 200,
            ];
            $f = Frame::make(Protocol::FACT_BATCH, Protocol::TEXT, $codec, $priority, $meta, $body, 0);
            $this->transport->send($f);
            $raw += strlen($jsonl);
            $payload += strlen($body);
            $wire += $f->wireLength();
            $frames++;
        }
        return ['facts' => count($records), 'frames' => $frames, 'raw_bytes' => $raw, 'payload_bytes' => $payload,
            'wire_bytes' => $wire, 'compress_ms' => round($compressNs / 1e6, 1), 'codec' => Protocol::compressionName($codec)];
    }

    /**
     * Send an already-encoded media bitstream. At or above the stream threshold
     * (or when $forceStream) it goes as STREAM_CHUNK frames with sequence
     * numbers; otherwise as one FACT_BATCH frame.
     *
     * @param array<string, mixed> $meta
     * @return array<string, mixed>
     */
    public function sendMedia(string $bitstream, int $contentType, int $codec, array $meta = [], int $priority = Protocol::P_BULK, int $chunkSize = 65536, ?bool $forceStream = null): array
    {
        $stream = $forceStream ?? strlen($bitstream) >= ContentClassifier::STREAM_THRESHOLD;
        $meta += ['reliability' => $contentType === Protocol::VIDEO || $contentType === Protocol::AUDIO ? 'best_effort' : 'must',
            'latency_target_ms' => 1000];
        if (!$stream) {
            $f = Frame::make(Protocol::FACT_BATCH, $contentType, $codec, $priority, $meta + ['sha256' => hash('sha256', $bitstream)], $bitstream, 0);
            $this->transport->send($f);
            return ['mode' => 'single', 'frames' => 1, 'bytes' => strlen($bitstream), 'wire_bytes' => $f->wireLength()];
        }
        $streamId = $this->transport->nodeId . '-s' . (++$this->streamCounter);
        $chunks = str_split($bitstream, max(1024, $chunkSize));
        $wire = 0;
        foreach ($chunks as $seq => $chunk) {
            $last = $seq === count($chunks) - 1;
            $m = $meta + ['stream_id' => $streamId, 'chunk_count' => count($chunks)];
            if ($last) {
                $m['sha256'] = hash('sha256', $bitstream);
                $m['total_bytes'] = strlen($bitstream);
            }
            $f = Frame::make(Protocol::STREAM_CHUNK, $contentType, $codec, $priority, $m, $chunk, 0, $seq, $last ? Protocol::F_END_OF_STREAM : 0);
            $this->transport->send($f);
            $wire += $f->wireLength();
        }
        return ['mode' => 'stream', 'stream_id' => $streamId, 'frames' => count($chunks), 'bytes' => strlen($bitstream), 'wire_bytes' => $wire];
    }

    /**
     * MIXED: several parts with their own content types and codecs in one
     * frame; the envelope is wrapped with $envelopeCodec.
     *
     * @param array<int, array{name:string, content_type:int, compression:int, bytes:string}> $parts
     * @return array<string, mixed>
     */
    public function sendMixed(array $parts, int $envelopeCodec, int $priority = Protocol::P_NORMAL): array
    {
        $block = Multipart::encode($parts);
        $body = Codec::compress($envelopeCodec, $block);
        $f = Frame::make(Protocol::FACT_BATCH, Protocol::MIXED, $envelopeCodec, $priority,
            ['parts' => array_map(fn ($p) => $p['name'], $parts), 'raw_bytes' => strlen($block), 'reliability' => 'must'], $body, 0);
        $this->transport->send($f);
        return ['parts' => count($parts), 'block_bytes' => strlen($block), 'payload_bytes' => strlen($body), 'wire_bytes' => $f->wireLength()];
    }

    /**
     * Ship an HLS or DASH package (from StreamPackager) file by file. Media and
     * init segments go first on the bulk class; manifests last, compressed as
     * text, so Node 2 never holds a manifest that references a missing segment.
     *
     * @param array<string, mixed> $pkg
     * @return array<string, mixed>
     */
    public function sendPackage(array $pkg, string $packageId = ''): array
    {
        $packageId = $packageId !== '' ? $packageId : strtolower($pkg['protocol']) . '-' . substr(hash('sha256', implode('|', $pkg['files']) . $pkg['bytes']), 0, 10);
        $files = $pkg['files'];
        usort($files, fn ($a, $b) => [StreamPackager::role($a) === 'manifest', $a] <=> [StreamPackager::role($b) === 'manifest', $b]);
        $wire = 0;
        $raw = 0;
        $frames = 0;
        foreach ($files as $i => $path) {
            $bytes = (string) file_get_contents($pkg['dir'] . '/' . $path);
            $role = StreamPackager::role($path);
            $meta = ['package_id' => $packageId, 'protocol' => $pkg['protocol'], 'path' => $path, 'role' => $role,
                'file_index' => $i, 'file_count' => count($files), 'root_manifest' => $pkg['manifest'], 'sha256' => hash('sha256', $bytes)];
            $raw += strlen($bytes);
            if ($role === 'manifest') {
                $codec = Codec::preferredText();
                $f = Frame::make(Protocol::FACT_BATCH, Protocol::TEXT, $codec, Protocol::P_NORMAL, $meta + ['reliability' => 'must', 'raw_bytes' => strlen($bytes)], Codec::compress($codec, $bytes), 0);
                $this->transport->send($f);
                $wire += $f->wireLength();
                $frames++;
                continue;
            }
            $content = $this->isAudioRep($pkg, $path) ? Protocol::AUDIO : Protocol::VIDEO;
            $r = $this->sendMedia($bytes, $content, $content === Protocol::AUDIO ? Protocol::C_AAC : Protocol::C_H264, $meta + ['latency_target_ms' => 2000], Protocol::P_BULK, 262144);
            $wire += $r['wire_bytes'];
            $frames += $r['frames'];
        }
        return ['package_id' => $packageId, 'protocol' => $pkg['protocol'], 'files' => count($files), 'frames' => $frames, 'bytes' => $raw, 'wire_bytes' => $wire,
            'overhead_pct' => round(100 * ($wire - $raw) / max(1, $wire), 3)];
    }

    /** DASH: representation ids beyond the video ladder are the audio track. */
    private function isAudioRep(array $pkg, string $path): bool
    {
        return preg_match('/chunk-(\d+)-/', $path, $m) === 1 && (int) $m[1] >= count($pkg['ladder']);
    }

    /** CONTROL ping on the control class; returns its message id (latency arrives with the ACK). */
    public function ping(): int
    {
        $f = Frame::make(Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE, Protocol::P_CONTROL,
            ['control' => 'PING', 'reliability' => 'must', 'latency_target_ms' => 50], '', 0);
        return $this->transport->send($f);
    }

    /**
     * Ask Node 2 an FQL question; the answer arrives as a FACT_BATCH.
     *
     * @return array{records: array<int, array<string, mixed>>, rendered: string, codec: string, wire_bytes: int}
     */
    public function query(string $fql, string $queryId = ''): array
    {
        $parsed = Fql::parse($fql); // fail fast on the producer side
        $f = Frame::make(Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE, Protocol::P_CONTROL,
            ['control' => 'QUERY', 'fql' => $parsed->render(), 'query_id' => $queryId !== '' ? $queryId : 'q-' . substr(hash('sha256', $parsed->render()), 0, 8)], '', 0);
        $reply = $this->transport->request($f);
        $meta = $reply->metaArray();
        if (isset($meta['error'])) {
            throw new RuntimeException('Node 2 refused the query: ' . $meta['error']);
        }
        return [
            'records' => Ufcs::decodeBatch(Codec::decompress($reply->compression, $reply->payload)),
            'rendered' => (string) ($meta['fql'] ?? ''),
            'codec' => Protocol::compressionName($reply->compression),
            'wire_bytes' => $reply->wireLength(),
        ];
    }

    /** @return array<string, mixed> Node 2's ingestion statistics */
    public function remoteStats(): array
    {
        $f = Frame::make(Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE, Protocol::P_CONTROL, ['control' => 'STATS'], '', 0);
        $reply = $this->transport->request($f);
        return (array) json_decode(Codec::decompress($reply->compression, $reply->payload), true);
    }

    public function control(string $command, array $extra = []): void
    {
        $f = Frame::make(Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE, Protocol::P_CONTROL, ['control' => $command] + $extra, '', 0);
        $this->transport->send($f);
        $this->transport->flush(10);
    }
}
