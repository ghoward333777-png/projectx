<?php

declare(strict_types=1);

/**
 * QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab — dashboard.
 *
 *   php -d upload_max_filesize=64M -d post_max_size=64M -S 127.0.0.1:8091 -t ufcs-transport-lab/web
 */
require __DIR__ . '/../src/bootstrap.php';

set_time_limit(600);
$tab = (string) ($_GET['tab'] ?? 'overview');
$tabs = ['overview' => 'Overview', 'inspector' => 'Frame Inspector', 'compress' => 'Compression Lab', 'transfer' => 'Live Transfer', 'streaming' => 'HLS · DASH · RTMP', 'color' => 'Colorization', 'bench' => 'Benchmark'];
if (!isset($tabs[$tab])) {
    $tab = 'overview';
}
$e = fn ($s): string => htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8');
$post = $_SERVER['REQUEST_METHOD'] === 'POST';
$reportsDir = __DIR__ . '/../reports';
$receivedDir = __DIR__ . '/../received';

/** Annotated hex dump: one colour class per frame section. */
function hexdump(string $wire, int $metaLen, int $payloadLen, bool $signed, int $limitPayload = 96): string
{
    $sections = [[0, 32, 'h'], [32, $metaLen, 'm'], [32 + $metaLen, $payloadLen, 'p'], [32 + $metaLen + $payloadLen, 4, 'c']];
    if ($signed) {
        $sections[] = [36 + $metaLen + $payloadLen, 64, 's'];
    }
    $out = '';
    $col = 0;
    foreach ($sections as [$start, $len, $cls]) {
        $show = $cls === 'p' ? min($len, $limitPayload) : $len;
        for ($i = 0; $i < $show; $i++) {
            if ($col % 16 === 0) {
                $out .= ($col ? "\n" : '') . '<span class="off">' . sprintf('%06x', $start + $i) . '</span> ';
            }
            $out .= '<span class="' . $cls . '">' . bin2hex($wire[$start + $i]) . '</span> ';
            $col++;
        }
        if ($show < $len) {
            $out .= "\n" . '<span class="off">  …   </span> <span class="p">… ' . number_format($len - $show) . ' more payload bytes …</span>';
            $col = 0;
            $out .= "\n";
        }
    }
    return $out;
}

ob_start();

// ---------------------------------------------------------------- Overview
if ($tab === 'overview') {
    $caps = Codec::capabilities();
    ?>
    <p class="lede">A transport engine that speaks <b>UFCS/FQL</b> at the semantic layer and rides on plain <b>TCP/IP</b>, compressing every payload by content type — video, audio, images and fact batches — between a producer (Node 1) and a consumer (Node 2).</p>
    <div class="card">
    <svg class="arch" viewBox="0 0 980 360" width="100%" role="img" aria-label="Node 1 modules send frames over three TCP connections to Node 2 modules">
        <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>
        <rect class="node" x="10" y="10" width="300" height="310" rx="12"/><text class="nt" x="160" y="38" text-anchor="middle">Node 1 · Producer</text>
        <?php foreach (['UFCS/FQL encoder', 'Content classifier', 'Compressor (Zstd · H.26x · AV1 · Opus…)', 'Framer (header · CRC32 · Ed25519)', 'Transport mgr (buckets · window)'] as $i => $m): ?>
            <rect class="mod" x="28" y="<?= 52 + $i * 52 ?>" width="264" height="40" rx="8"/><text x="160" y="<?= 77 + $i * 52 ?>" text-anchor="middle"><?= $e($m) ?></text>
        <?php endforeach; ?>
        <rect class="node" x="670" y="10" width="300" height="310" rx="12"/><text class="nt" x="820" y="38" text-anchor="middle">Node 2 · Consumer</text>
        <?php foreach (['Stream reader (resync)', 'Verifier (CRC32 · signature)', 'Decompressor (by codec)', 'UFCS/FQL decoder (fingerprints)', 'Ingestion → UFCS store'] as $i => $m): ?>
            <rect class="mod" x="688" y="<?= 52 + $i * 52 ?>" width="264" height="40" rx="8"/><text x="820" y="<?= 77 + $i * 52 ?>" text-anchor="middle"><?= $e($m) ?></text>
        <?php endforeach; ?>
        <?php foreach ([['control · port P', 'priority 0 · pings, policy, FQL queries', 95, 's1'], ['normal · port P+1', 'priority 1 · UFCS fact batches', 165, 's2'], ['bulk · port P+2', 'priority 2 · media streams, backfill', 235, 's3']] as [$name, $what, $y, $c]): ?>
            <line class="link <?= $c ?>" x1="310" y1="<?= $y ?>" x2="668" y2="<?= $y ?>" marker-end="url(#ar)"/>
            <text class="lt" x="489" y="<?= $y - 8 ?>" text-anchor="middle"><?= $e($name) ?></text>
            <text x="489" y="<?= $y + 18 ?>" text-anchor="middle" class="small"><?= $e($what) ?></text>
        <?php endforeach; ?>
        <text x="489" y="345" text-anchor="middle" class="small">ACKs flow back on each connection with the receiver's window + queue depth</text>
    </svg>
    </div>
    <h2>The UFCS-FQL/1 frame</h2>
    <div class="card"><table>
        <tr><th>Offset</th><th>Size</th><th>Field</th><th>Values</th></tr>
        <?php foreach (Protocol::HEADER_LAYOUT as [$name, $off, $size]): ?>
            <tr><td class="num"><?= $off ?></td><td class="num"><?= $size ?></td><td><code><?= $e($name) ?></code></td><td><?= $e(match ($name) {
                'Magic' => sprintf('0x%04X (0xF0 can never start UTF-8 text, then ASCII “Q”)', Protocol::MAGIC),
                'Version' => (string) Protocol::VERSION,
                'MsgType' => implode(' · ', array_map(fn ($k, $v) => "$k=$v", array_keys(Protocol::MSG_TYPES), Protocol::MSG_TYPES)),
                'ContentType' => implode(' · ', array_map(fn ($k, $v) => "$k=$v", array_keys(Protocol::CONTENT_TYPES), Protocol::CONTENT_TYPES)),
                'CompressionType' => implode(' · ', array_map(fn ($k, $v) => "$k=$v", array_keys(Protocol::COMPRESSIONS), Protocol::COMPRESSIONS)),
                'Flags' => implode(' · ', array_map(fn ($k, $v) => sprintf('0x%04X %s', $k, $v), array_keys(Protocol::FLAG_NAMES), Protocol::FLAG_NAMES)),
                'PayloadLen' => 'payload bytes only (cap 64 MiB)', 'MetaLen' => 'meta JSON bytes (cap 1 MiB)', 'MessageID' => 'unique per sender, echoed in ACKs',
                'Sequence' => 'chunk number within a stream', 'Reserved' => '0 — future use', default => '',
            }) ?></td></tr>
        <?php endforeach; ?>
        <tr><td class="num">32</td><td class="num">MetaLen</td><td><code>Meta</code></td><td>UTF-8 JSON: query_id, entity_ids, relation_ids, source_region, source_node_id, priority, latency_target_ms, reliability, stream_id…</td></tr>
        <tr><td class="num">32+M</td><td class="num">PayloadLen</td><td><code>Payload</code></td><td>already compressed per CompressionType</td></tr>
        <tr><td class="num">32+M+P</td><td class="num">4 (+64)</td><td><code>Footer</code></td><td>CRC32 (IEEE) over header+meta+payload; Ed25519 signature when SIGNED</td></tr>
    </table></div>
    <h2>Codecs on this node</h2>
    <div class="card"><table><tr><th>Codec</th><th>Kind</th><th>Status</th><th>Implementation</th></tr>
        <?php foreach ($caps as $name => $c): ?>
            <tr><td><code><?= $e($name) ?></code></td><td><?= $e($c['kind']) ?></td><td><?= $c['available'] ? '<span class="pass">✔ available</span>' : '<span class="fail">✖ unavailable</span>' ?></td><td><?= $e($c['note']) ?></td></tr>
        <?php endforeach; ?>
    </table></div>
    <h2>Where this sits in the QueryBook canon</h2>
    <div class="card"><table><tr><th>Registry</th><th>Feature</th><th>How the lab realises it</th></tr>
        <tr><td>F57</td><td>Semantic Transport Layer</td><td>Fact Units routed by type and priority class; meta carries query, entity and relation context.</td></tr>
        <tr><td>F61</td><td>QueryBook Format (QBF) binary frames</td><td>Fixed header + CRC; the stream reader resynchronises to the next valid frame, so a corrupt frame costs one frame, not the stream.</td></tr>
        <tr><td>F51</td><td>Multimodal Ingestion Pipeline</td><td>Content classifier picks TEXT / IMAGE / VIDEO / AUDIO / MIXED from magic bytes, then the codec policy.</td></tr>
        <tr><td>F182</td><td>Media interface — semantic compression with provenance</td><td>Every transcode reports codec, bitrate, resolution and sample rate; the frame meta keeps source node and region.</td></tr>
        <tr><td>UFCS</td><td>Record Field Layout (Prototype Test Kit)</td><td>Node 2 recomputes SHA-256(norm(s)|norm(p)|norm(o)|polarity) and refuses altered records; restatements merge as corroboration.</td></tr>
        <tr><td>F22 / F75</td><td>VCUM Semantic Colorization Engine</td><td>Black and white to colour at 1K, 4K and 16K. Colour resolved from UFCS facts by FQL, confidence bounded by fact trust (F224), uncertain regions withheld (F182), colour marked as reconstructed (F225).</td></tr>
        <tr><td>Streaming</td><td>HLS · MPEG-DASH · RTMP</td><td>Ladders planned from link capacity; playlists and segments travel as frames and are rebuilt + hash-verified on Node 2; RTMP publishers are ingested live and repackaged.</td></tr>
        <tr><td>FQL</td><td>QBQL/FQL (QBF-C054/C058)</td><td>Declarative read-only queries travel as CONTROL frames; answers return as compressed FACT_BATCH frames.</td></tr>
    </table></div>
    <?php
}

// ---------------------------------------------------------------- Inspector
if ($tab === 'inspector') {
    $in = [
        'msg_type' => (int) ($_POST['msg_type'] ?? Protocol::FACT_BATCH),
        'content_type' => (int) ($_POST['content_type'] ?? Protocol::TEXT),
        'compression' => (int) ($_POST['compression'] ?? Codec::preferredText()),
        'priority' => (int) ($_POST['priority'] ?? Protocol::P_NORMAL),
        'signed' => $post ? isset($_POST['signed']) : true,
        'facts' => max(1, min(242, (int) ($_POST['facts'] ?? 3))),
        'corrupt' => (int) ($_POST['corrupt'] ?? -1),
    ];
    if (!Codec::isLossless($in['compression']) || !Codec::available($in['compression'])) {
        $in['compression'] = Codec::preferredText();
    }
    $records = array_slice(Ufcs::sample(), 0, $in['facts']);
    $jsonl = Ufcs::encodeBatch($records);
    $meta = Ufcs::batchContext($records) + ['query_id' => 'q-inspector', 'source_node_id' => 'node-1', 'source_region' => 'us-west', 'reliability' => 'must', 'latency_target_ms' => 200, 'fact_count' => count($records)];
    $frame = Frame::make($in['msg_type'], $in['content_type'], $in['compression'], $in['priority'], $meta, Codec::compress($in['compression'], $jsonl), 42, 0, Protocol::F_ACK_REQUESTED);
    $wire = $frame->encode($in['signed'] ? NodeKeys::forNode('node-1')['secret'] : null);
    $h = Frame::parseHeader($wire);
    ?>
    <p class="lede">Build a real frame from UFCS sample facts and see every byte. Then corrupt one byte and watch Node 2's stream reader drop exactly that frame and resynchronise on the next.</p>
    <form method="post" class="card form">
        <label>MsgType <select name="msg_type"><?php foreach (Protocol::MSG_TYPES as $k => $v): ?><option value="<?= $k ?>" <?= $k === $in['msg_type'] ? 'selected' : '' ?>><?= $v ?></option><?php endforeach; ?></select></label>
        <label>ContentType <select name="content_type"><?php foreach (Protocol::CONTENT_TYPES as $k => $v): ?><option value="<?= $k ?>" <?= $k === $in['content_type'] ? 'selected' : '' ?>><?= $v ?></option><?php endforeach; ?></select></label>
        <label>Compression <select name="compression"><?php foreach ([0, 1, 2, 9] as $k): if (!Codec::available($k)) { continue; } ?><option value="<?= $k ?>" <?= $k === $in['compression'] ? 'selected' : '' ?>><?= Protocol::compressionName($k) ?></option><?php endforeach; ?></select></label>
        <label>Priority <select name="priority"><?php foreach (Protocol::PRIORITIES as $k => $v): ?><option value="<?= $k ?>" <?= $k === $in['priority'] ? 'selected' : '' ?>><?= $k ?> · <?= $v ?></option><?php endforeach; ?></select></label>
        <label>Facts <input type="number" name="facts" min="1" max="242" value="<?= $in['facts'] ?>"></label>
        <label class="check"><input type="checkbox" name="signed" <?= $in['signed'] ? 'checked' : '' ?>> Ed25519 sign</label>
        <label>Corrupt byte # <input type="number" name="corrupt" min="-1" value="<?= $in['corrupt'] ?>" title="-1 = no corruption"></label>
        <button>Build frame</button>
    </form>
    <div class="kpis">
        <div class="kpi"><b><?= number_format(strlen($wire)) ?></b><span>wire bytes</span></div>
        <div class="kpi"><b><?= number_format(strlen($jsonl)) ?></b><span>raw UFCS JSONL bytes</span></div>
        <div class="kpi"><b><?= round(strlen($jsonl) / max(1, strlen($frame->payload)), 2) ?>×</b><span>payload ratio (<?= Protocol::compressionName($in['compression']) ?>)</span></div>
        <div class="kpi"><b><?= sprintf('%08x', $frame->crc) ?></b><span>CRC32</span></div>
    </div>
    <h2>Header</h2>
    <div class="card"><table><tr><th>Offset</th><th>Field</th><th>Bytes</th><th>Value</th></tr>
        <?php $keys = ['magic', 'version', 'msgType', 'contentType', 'compression', 'flags', 'payloadLen', 'metaLen', 'messageId', 'sequence', 'reserved'];
        foreach (Protocol::HEADER_LAYOUT as $i => [$name, $off, $size]): $v = $h[$keys[$i]]; ?>
            <tr><td class="num"><?= $off ?></td><td><code><?= $name ?></code></td><td><code><?= bin2hex(substr($wire, $off, $size)) ?></code></td><td><?= $e(match ($name) {
                'Magic' => sprintf('0x%04X', $v), 'MsgType' => Protocol::MSG_TYPES[$v], 'ContentType' => Protocol::CONTENT_TYPES[$v], 'CompressionType' => Protocol::compressionName($v),
                'Flags' => sprintf('0x%04X ', $v) . implode(' | ', Protocol::flagNames($v)), default => (string) $v,
            }) ?></td></tr>
        <?php endforeach; ?>
    </table></div>
    <h2>Wire bytes</h2>
    <div class="legend"><span style="--c:var(--hx-h)">header</span><span style="--c:var(--hx-m)">meta</span><span style="--c:var(--hx-p)">payload</span><span style="--c:var(--hx-c)">CRC32</span><span style="--c:var(--hx-s)">signature</span></div>
    <div class="card"><pre class="hex"><?= hexdump($wire, $h['metaLen'], $h['payloadLen'], (bool) ($h['flags'] & Protocol::F_SIGNED)) ?></pre></div>
    <h2>Meta</h2><div class="card"><pre><?= $e(json_encode($frame->metaArray(), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)) ?></pre></div>
    <?php
    // Resync demonstration: [good][this frame, possibly corrupted][good] through one reader.
    $mk = function (int $id) {
        $f = Frame::make(Protocol::CONTROL, Protocol::TEXT, Protocol::C_NONE, Protocol::P_CONTROL, ['control' => 'PING', 'source_node_id' => 'node-1'], '', $id);
        return $f->encode(NodeKeys::forNode('node-1')['secret']);
    };
    $bad = $wire;
    if ($in['corrupt'] >= 0 && $in['corrupt'] < strlen($bad)) {
        $bad[$in['corrupt']] = chr(ord($bad[$in['corrupt']]) ^ 0x5A);
    }
    $reader = new FrameReader(fn (Frame $f) => NodeKeys::forNode((string) ($f->metaArray()['source_node_id'] ?? 'node-1'))['public']);
    $stream = $mk(41) . $bad . $mk(43);
    foreach (str_split($stream, 7) as $piece) { // arrive in awkward 7-byte TCP segments
        $reader->push($piece);
    }
    $got = [];
    while (($f = $reader->next()) !== null) {
        $got[] = $f;
    }
    $got = array_merge($got, $reader->finish());
    ?>
    <h2>Stream reader: [PING #41][this frame #42][PING #43] in 7-byte segments</h2>
    <div class="card"><table><tr><th>Recovered frames</th><th>Corrupt frames</th><th>Bytes skipped</th><th>Reasons</th></tr>
        <tr><td><?= $e(implode(', ', array_map(fn ($f) => '#' . $f->messageId . ' ' . Protocol::MSG_TYPES[$f->msgType], $got))) ?></td><td class="num"><?= $reader->corruptFrames ?></td>
            <td class="num"><?= number_format($reader->skippedBytes) ?></td><td><?= $e(implode('; ', array_unique($reader->errors)) ?: 'none') ?></td></tr></table>
        <p class="note"><?= $in['corrupt'] >= 0 ? 'Byte ' . $in['corrupt'] . ' was XOR-ed with 0x5A. ' : '' ?>A frame that fails its plausibility, CRC or signature check is dropped; the reader rescans for the next <code>F0 51 01</code> anchor, so the frames around it survive.</p></div>
    <?php
}

// ---------------------------------------------------------------- Compression Lab
if ($tab === 'compress') {
    $results = null;
    $error = null;
    $preview = null;
    $src = (string) ($_POST['source'] ?? 'facts');
    $kbps = max(100, (int) ($_POST['kbps'] ?? 800));
    $height = (int) ($_POST['height'] ?? 0);
    $quality = max(10, min(100, (int) ($_POST['quality'] ?? 80)));
    $nfacts = max(1, min(200000, (int) ($_POST['nfacts'] ?? 5000)));
    if ($post) {
        try {
            if ($src === 'upload') {
                if (empty($_FILES['file']['tmp_name']) || !is_uploaded_file($_FILES['file']['tmp_name'])) {
                    throw new RuntimeException('Choose a file to upload (start PHP with -d upload_max_filesize=64M for large media).');
                }
                $path = $_FILES['file']['tmp_name'];
                $name = (string) $_FILES['file']['name'];
                $bytes = (string) file_get_contents($path);
            } else {
                $name = 'ufcs-facts.jsonl';
                $bytes = Ufcs::encodeBatch(Ufcs::synthesize($nfacts));
                $path = null;
            }
            $ct = ContentClassifier::classify($bytes, $name);
            $policy = ContentClassifier::policy($ct, strlen($bytes));
            $rows = [];
            $add = function (string $label, array $enc, ?string $note = null) use (&$rows, $bytes) {
                $rows[] = ['codec' => $label, 'bytes' => strlen($enc['bytes']), 'ratio' => round(strlen($bytes) / max(1, strlen($enc['bytes'])), 2), 'ms' => $enc['encode_ms'] ?? null, 'note' => $note ?? ($enc['mode'] ?? '')];
            };
            if ($ct === Protocol::TEXT || $ct === Protocol::MIXED) {
                foreach ([Protocol::C_GZIP, Protocol::C_ZSTD, Protocol::C_UFCS_DICT] as $c) {
                    if (!Codec::available($c)) {
                        continue;
                    }
                    $t = hrtime(true);
                    $out = Codec::compress($c, $bytes);
                    $ms = round((hrtime(true) - $t) / 1e6, 1);
                    $ok = Codec::decompress($c, $out) === $bytes;
                    $add(Protocol::compressionName($c), ['bytes' => $out, 'encode_ms' => $ms], $ok ? 'lossless round-trip verified' : 'ROUND-TRIP FAILED');
                }
            } elseif ($ct === Protocol::IMAGE) {
                foreach ([[$quality, 0], [$quality, 1280], [max(10, $quality - 25), 960]] as [$q, $mw]) {
                    $enc = MediaCodec::encodeImage($bytes, ['quality' => $q, 'max_width' => $mw]);
                    $add('WEBP q' . $q . ($mw ? ' ≤' . $mw . 'px' : ''), $enc);
                    $preview ??= ['type' => 'image', 'mime' => 'image/webp', 'data' => $enc['bytes']];
                }
            } elseif ($ct === Protocol::VIDEO) {
                foreach ([Protocol::C_H264, Protocol::C_H265, Protocol::C_AV1] as $c) {
                    if (!Codec::available($c)) {
                        continue;
                    }
                    $enc = MediaCodec::encodeVideo($path, ['codec' => $c, 'kbps' => $kbps, 'height' => $height ?: null, 'container' => $c === Protocol::C_H264 ? 'mp4' : null]);
                    $add(Protocol::compressionName($c), $enc, $enc['mode'] . ($height ? ', ' . $height . 'p' : '') . ' · ' . $enc['container']);
                    if ($c === Protocol::C_H264 && strlen($enc['bytes']) < 12 * 1048576) {
                        $preview = ['type' => 'video', 'mime' => 'video/mp4', 'data' => $enc['bytes']];
                    }
                }
            } elseif ($ct === Protocol::AUDIO) {
                foreach ([[Protocol::C_OPUS, 24000, 1, 24], [Protocol::C_OPUS, 48000, 2, 96], [Protocol::C_AAC, 48000, 2, 128]] as [$c, $rate, $ch, $k]) {
                    if (!Codec::available($c)) {
                        continue;
                    }
                    $enc = MediaCodec::encodeAudio($path, ['codec' => $c, 'rate' => $rate, 'channels' => $ch, 'kbps' => $k]);
                    $add(Protocol::compressionName($c), $enc);
                    if ($c === Protocol::C_OPUS && $preview === null) {
                        $preview = ['type' => 'audio', 'mime' => 'audio/ogg', 'data' => $enc['bytes']];
                    }
                }
            }
            $results = ['name' => $name, 'size' => strlen($bytes), 'content' => Protocol::CONTENT_TYPES[$ct], 'policy' => $policy, 'rows' => $rows];
        } catch (Throwable $ex) {
            $error = $ex->getMessage();
        }
    }
    ?>
    <p class="lede">Content-aware compression, not one-size-fits-all. Upload a video, audio clip, image or text file (or use synthetic UFCS facts): the classifier picks the content type and transport policy, then every applicable codec runs on it.</p>
    <form method="post" enctype="multipart/form-data" class="card form">
        <label class="check"><input type="radio" name="source" value="facts" <?= $src !== 'upload' ? 'checked' : '' ?>> UFCS facts</label>
        <label>Count <input type="number" name="nfacts" min="1" max="200000" value="<?= $nfacts ?>"></label>
        <label class="check"><input type="radio" name="source" value="upload" <?= $src === 'upload' ? 'checked' : '' ?>> Upload</label>
        <label><input type="file" name="file"></label>
        <label>Video kbps <input type="number" name="kbps" min="100" value="<?= $kbps ?>"></label>
        <label>Downscale to <select name="height"><option value="0">source</option><?php foreach ([1080, 720, 540, 360, 240] as $hh): ?><option value="<?= $hh ?>" <?= $hh === $height ? 'selected' : '' ?>><?= $hh ?>p</option><?php endforeach; ?></select></label>
        <label>Image quality <input type="number" name="quality" min="10" max="100" value="<?= $quality ?>"></label>
        <button>Compress</button>
    </form>
    <?php if ($error): ?><div class="card fail">✖ <?= $e($error) ?></div><?php endif; ?>
    <?php if ($results): ?>
        <div class="kpis">
            <div class="kpi"><b><?= $e($results['content']) ?></b><span>classified content type</span></div>
            <div class="kpi"><b><?= ReportView::num((float) $results['size'], true) ?></b><span><?= $e($results['name']) ?></span></div>
            <div class="kpi"><b><?= Protocol::MSG_TYPES[$results['policy']['msg_type']] ?></b><span>message type · <?= Protocol::PRIORITIES[$results['policy']['priority']] ?> priority</span></div>
        </div>
        <p class="note">Policy: <?= $e($results['policy']['reason']) ?></p>
        <?= ReportView::table($results['rows'], ['codec' => 'Codec', 'ratio' => 'Ratio ×', 'bytes' => 'Output bytes', 'ms' => 'Encode ms', 'note' => 'What was done']) ?>
        <?php if ($results['rows']): ?><div class="card"><?= ReportView::hbars(array_map(fn ($r) => [$r['codec'], $r['ratio']], $results['rows']), [['ratio', 'var(--s1)']], false, '×') ?></div><?php endif; ?>
        <?php if ($preview): $uri = 'data:' . $preview['mime'] . ';base64,' . base64_encode($preview['data']); ?>
            <h2>Preview of the compressed result</h2><div class="card">
            <?php if ($preview['type'] === 'image'): ?><img src="<?= $uri ?>" alt="WebP result" style="max-width:100%;border-radius:8px">
            <?php elseif ($preview['type'] === 'video'): ?><video src="<?= $uri ?>" controls muted style="max-width:100%;border-radius:8px"></video>
            <?php else: ?><audio src="<?= $uri ?>" controls></audio><?php endif; ?></div>
        <?php endif; ?>
    <?php endif; ?>
    <?php
}

// ---------------------------------------------------------------- Live transfer
if ($tab === 'transfer') {
    $codec = (int) ($_POST['codec'] ?? Codec::preferredText());
    $mode = ($_POST['mode'] ?? 'multi') === 'single' ? 'single' : 'multi';
    $nfacts = max(1, min(100000, (int) ($_POST['nfacts'] ?? 2000)));
    $fql = (string) ($_POST['fql'] ?? 'FIND fact WHERE predicate IN [has_capital, capital_of] AND trust >= 0.4 RANK BY trust LIMIT 10');
    $res = null;
    $error = null;
    if ($post) {
        $node = null;
        try {
            $node = LocalNode::start(['--window=64']);
            $t = new Transport('127.0.0.1', $node->port, ['mode' => $mode, 'sign' => isset($_POST['sign'])]);
            $t->connect();
            $s = new Sender($t);
            $w = microtime(true);
            $sent = $s->sendFacts(array_merge(Ufcs::sample(), Ufcs::synthesize(max(0, $nfacts - 242))), $codec);
            $ok = $t->flush(120);
            $sendS = microtime(true) - $w;
            $q = $s->query($fql);
            $res = ['sent' => $sent, 'ok' => $ok, 'send_s' => $sendS, 'query' => $q, 'transport' => $t->stats(), 'remote' => $s->remoteStats()];
            $s->control('SHUTDOWN');
            $t->close();
            $node->finish();
        } catch (Throwable $ex) {
            $error = $ex->getMessage();
            $node?->kill();
        }
    }
    ?>
    <p class="lede">Starts a real Node 2 process, opens the priority connections, ships UFCS fact batches, then asks Node 2 an FQL question. Everything below crossed TCP as UFCS-FQL/1 frames.</p>
    <form method="post" class="card form">
        <label>Facts <input type="number" name="nfacts" min="1" max="100000" value="<?= $nfacts ?>"></label>
        <label>Codec <select name="codec"><?php foreach ([0, 1, 2, 9] as $k): if (!Codec::available($k)) { continue; } ?><option value="<?= $k ?>" <?= $k === $codec ? 'selected' : '' ?>><?= Protocol::compressionName($k) ?></option><?php endforeach; ?></select></label>
        <label>Connections <select name="mode"><option value="multi">3 (per priority)</option><option value="single" <?= $mode === 'single' ? 'selected' : '' ?>>1 shared</option></select></label>
        <label class="check"><input type="checkbox" name="sign" <?= isset($_POST['sign']) ? 'checked' : '' ?>> Ed25519 sign</label>
        <label class="wide">FQL <input type="text" name="fql" value="<?= $e($fql) ?>"></label>
        <button>Transfer &amp; query</button>
    </form>
    <p class="note">FQL fields: subject, predicate, object, entity, group, polarity, fact_type, source, trust, score, text · operators = != &gt; &gt;= &lt; &lt;= IN ~ · then RANK BY trust|score, LIMIT n.</p>
    <?php if ($error): ?><div class="card fail">✖ <?= $e($error) ?></div><?php endif; ?>
    <?php if ($res): $f = $res['remote']['facts']; ?>
        <div class="kpis">
            <div class="kpi"><b><?= number_format($res['sent']['facts']) ?></b><span>facts in <?= $res['sent']['frames'] ?> FACT_BATCH frames</span></div>
            <div class="kpi"><b><?= round($res['sent']['raw_bytes'] / max(1, $res['sent']['payload_bytes']), 2) ?>×</b><span><?= $e($res['sent']['codec']) ?> ratio</span></div>
            <div class="kpi"><b><?= number_format($f['admitted']) ?> / <?= number_format($f['merged']) ?> / <?= number_format($f['rejected']) ?></b><span>admitted / corroborated / rejected</span></div>
            <div class="kpi"><b><?= round($res['send_s'], 3) ?> s</b><span>compress + transfer + ACK</span></div>
        </div>
        <h2>FQL answer — <?= count($res['query']['records']) ?> facts (<?= $e($res['query']['codec']) ?>, <?= number_format($res['query']['wire_bytes']) ?> wire bytes)</h2>
        <div class="card"><pre><?= $e($res['query']['rendered']) ?></pre>
        <?= ReportView::table(array_map(fn ($r) => ['subject' => $r['nucleus']['subject'], 'predicate' => $r['nucleus']['predicate'], 'object' => Ufcs::pyStr($r['nucleus']['object']),
            'polarity' => $r['polarity'], 'trust' => (float) ($r['certification']['trust_score'] ?? 0), 'source' => $r['sources'][0]['name'] ?? '', 'fp' => substr($r['semantic_fingerprint'], 0, 12) . '…'], $res['query']['records']),
            ['subject' => 'Subject', 'predicate' => 'Predicate', 'object' => 'Object', 'polarity' => '±', 'trust' => 'Trust', 'source' => 'Source', 'fp' => 'Fingerprint']) ?></div>
        <h2>Transport (Node 1)</h2>
        <?= ReportView::table(array_map(fn ($k, $v) => ['conn' => $k, 'frames' => $v['frames_sent'], 'bytes' => $v['bytes_sent'], 'acked' => $v['frames_acked'], 'window' => $v['window'],
            'p50' => $v['latency_ms']['p50'], 'p95' => $v['latency_ms']['p95']], array_keys($res['transport']), $res['transport']),
            ['conn' => 'Connection', 'frames' => 'Frames', 'bytes' => 'Wire bytes', 'acked' => 'ACKed', 'window' => 'Window', 'p50' => 'ACK p50 ms', 'p95' => 'ACK p95 ms']) ?>
        <h2>Ingestion (Node 2)</h2>
        <?= ReportView::table(array_map(fn ($k, $v) => ['class' => $k] + $v, array_keys($res['remote']['by_priority']), $res['remote']['by_priority']),
            ['class' => 'Priority class', 'frames' => 'Frames', 'wire_bytes' => 'Wire bytes', 'payload_bytes' => 'Payload bytes', 'decoded_bytes' => 'Decoded bytes']) ?>
    <?php endif; ?>
    <?php
}

// ---------------------------------------------------------------- Streaming (HLS, DASH, RTMP)
if ($tab === 'streaming') {
    $action = (string) ($_POST['action'] ?? '');
    $error = null;
    $done = [];
    $secs = max(2, min(60, (int) ($_POST['seconds'] ?? 8)));
    $res = (string) ($_POST['res'] ?? '1280x720');
    $link = max(0.5, (float) ($_POST['link'] ?? 20));
    $segS = max(1, min(10, (int) ($_POST['seg'] ?? 2)));
    $protocols = $post ? (array) ($_POST['proto'] ?? []) : ['hls', 'dash'];
    $source = function () use ($res, $secs): string {
        if (!empty($_FILES['file']['tmp_name']) && is_uploaded_file($_FILES['file']['tmp_name'])) {
            $ext = strtolower(pathinfo((string) $_FILES['file']['name'], PATHINFO_EXTENSION)) ?: 'mp4';
            $dst = sys_get_temp_dir() . '/ufcs-upload-' . bin2hex(random_bytes(4)) . '.' . preg_replace('/[^a-z0-9]/', '', $ext);
            move_uploaded_file($_FILES['file']['tmp_name'], $dst);
            return $dst;
        }
        [$w, $h] = array_map('intval', explode('x', preg_match('/^\d+x\d+$/', $res) ? $res : '1280x720'));
        $dst = sys_get_temp_dir() . '/ufcs-av-' . bin2hex(random_bytes(4)) . '.mp4';
        MediaCodec::makeTestAv($dst, $w, $h, $secs);
        return $dst;
    };
    if ($post && $action !== '') {
        $node = null;
        $src = null;
        try {
            if ($action === 'egress') {
                $id = (string) ($_POST['package'] ?? '');
                $url = trim((string) ($_POST['url'] ?? ''));
                $dir = $receivedDir . '/packages/' . $id;
                if (!preg_match('/^[a-z0-9_-]{1,64}$/i', $id) || !is_dir($dir)) {
                    throw new RuntimeException('Choose a received package to push.');
                }
                $root = is_file($dir . '/master.m3u8') ? 'master.m3u8' : (is_file($dir . '/index.m3u8') ? 'index.m3u8' : 'manifest.mpd');
                $r = RtmpPublisher::push($dir . '/' . $root, $url);
                $done[] = ['what' => 'RTMP egress', 'result' => $r['code'] === 0 ? '✔ pushed ' . $id . ' to ' . preg_replace('#/[^/]+$#', '/•••', $url) . ' in ' . $r['ms'] . ' ms' : '✖ ' . $r['stderr']];
            } else {
                $src = $source();
                $node = LocalNode::start(['--window=64', '--out=' . $receivedDir, '--repackage', '--verify-media']);
                $t = new Transport('127.0.0.1', $node->port, ['sign' => isset($_POST['sign'])]);
                $t->connect();
                $s = new Sender($t);
                if ($action === 'package') {
                    foreach (array_intersect(['hls', 'dash'], $protocols) as $kind) {
                        $pkg = StreamPackager::$kind($src, ['link_mbps' => $link, 'segment_seconds' => $segS]);
                        $sent = $s->sendPackage($pkg);
                        $t->flush(120);
                        StreamPackager::removeDir($pkg['dir']);
                        $done[] = ['what' => strtoupper($kind) . ' package ' . $sent['package_id'], 'result' => $sent['files'] . ' files, ' . $pkg['segments'] . ' segments, ladder '
                            . implode(' / ', array_map(fn ($r) => $r['height'] . 'p@' . $r['kbps'] . 'k', $pkg['ladder'])) . ', ' . ReportView::num((float) $sent['bytes'], true) . ', framing overhead ' . $sent['overhead_pct'] . '%'];
                    }
                } elseif ($action === 'rtmp') {
                    $run = RtmpBridge::publishFile($t, $src);
                    $st = $run['stream'];
                    $done[] = ['what' => 'RTMP ingest ' . ($st['stream_id'] ?? ''), 'result' => 'publisher rc ' . $run['publisher_rc'] . ', ' . ($st['tags'] ?? 0) . ' FLV tags ('
                        . ($st['video_codec'] ?? '?') . ' + ' . ($st['audio_codec'] ?? '?') . ') bridged as ' . ($st['chunks'] ?? 0) . ' live STREAM_CHUNK frames in ' . $run['seconds'] . ' s'];
                }
                $remote = $s->remoteStats();
                foreach ($remote['streams'] as $st) {
                    if (isset($st['repackaged'])) {
                        $done[] = ['what' => 'Node 2: ' . $st['stream_id'], 'result' => ($st['intact'] ? 'intact' : 'NOT intact') . ', ' . (($st['decodes']['ok'] ?? false) ? 'decodes' : 'decode failed')
                            . '; repackaged HLS ' . ($st['repackaged']['hls']['ok'] ? '✔' : '✖') . ', DASH ' . ($st['repackaged']['dash']['ok'] ? '✔' : '✖')];
                    }
                }
                foreach ($remote['packages'] as $p) {
                    $done[] = ['what' => 'Node 2 package ' . $p['package_id'], 'result' => ($p['ok'] ? '✔ complete' : '✖ incomplete: ' . implode(', ', $p['missing'] ?? [])) . ', ' . ($p['segments'] ?? 0) . ' segments, ' . ($p['variants'] ?? 0) . ' variant(s)'];
                }
                $s->control('SHUTDOWN');
                $t->close();
                $node->finish();
            }
        } catch (Throwable $ex) {
            $error = $ex->getMessage();
            $node?->kill();
        }
        if ($src !== null) {
            @unlink($src);
        }
    }
    $packages = [];
    foreach (glob($receivedDir . '/packages/*', GLOB_ONLYDIR) ?: [] as $dir) {
        $id = basename($dir);
        $root = is_file($dir . '/master.m3u8') ? 'master.m3u8' : (is_file($dir . '/index.m3u8') ? 'index.m3u8' : (is_file($dir . '/manifest.mpd') ? 'manifest.mpd' : null));
        if ($root === null) {
            continue;
        }
        $check = Manifest::verify($dir, $root);
        $packages[$id] = ['id' => $id, 'protocol' => str_ends_with($root, '.mpd') ? 'DASH' : 'HLS', 'root' => $root, 'ok' => $check['ok'], 'segments' => $check['segments'],
            'variants' => $check['variants'], 'duration' => $check['duration_s'], 'mtime' => filemtime($dir)];
    }
    uasort($packages, fn ($a, $b) => $b['mtime'] <=> $a['mtime']);
    $play = $packages[(string) ($_GET['play'] ?? '')] ?? (reset($packages) ?: null);
    ?>
    <p class="lede">Adaptive streaming carried on the UFCS-FQL transport. <b>HLS</b> and <b>MPEG-DASH</b> packages are encoded as a bitrate ladder planned from the link capacity, then every playlist and segment crosses as a frame (segments on the bulk class, manifests last). Node 2 rebuilds the tree, hash-checks every file against its manifest, and serves it to standard players. <b>RTMP</b> publishers (OBS, ffmpeg, hardware encoders) push to the lab's own RTMP server; the stream is bridged live to Node 2 and repackaged as HLS and DASH.</p>
    <form method="post" enctype="multipart/form-data" class="card form">
        <label>Source <input type="file" name="file" title="leave empty to generate a test source"></label>
        <label>or generate <select name="res"><?php foreach (['640x360', '1280x720', '1920x1080'] as $r): ?><option <?= $r === $res ? 'selected' : '' ?>><?= $r ?></option><?php endforeach; ?></select></label>
        <label>Seconds <input type="number" name="seconds" min="2" max="60" value="<?= $secs ?>"></label>
        <label>Link Mbps <input type="number" name="link" step="0.5" min="0.5" value="<?= $link ?>" title="sets the top rung of the ladder"></label>
        <label>Segment s <input type="number" name="seg" min="1" max="10" value="<?= $segS ?>"></label>
        <label class="check"><input type="checkbox" name="proto[]" value="hls" <?= in_array('hls', $protocols, true) ? 'checked' : '' ?>> HLS</label>
        <label class="check"><input type="checkbox" name="proto[]" value="dash" <?= in_array('dash', $protocols, true) ? 'checked' : '' ?>> DASH</label>
        <label class="check"><input type="checkbox" name="sign" <?= isset($_POST['sign']) ? 'checked' : '' ?>> Ed25519 sign</label>
        <button name="action" value="package">Package &amp; deliver</button>
        <button name="action" value="rtmp">RTMP live ingest</button>
    </form>
    <?php if ($error): ?><div class="card fail">✖ <?= $e($error) ?></div><?php endif; ?>
    <?php if ($done): ?><?= ReportView::table($done, ['what' => 'Step', 'result' => 'Result']) ?><?php endif; ?>
    <?php if ($play): $src = 'media.php?p=' . rawurlencode($play['id']) . '/' . $play['root']; ?>
        <h2>Playing <?= $e($play['id']) ?> · <?= $play['protocol'] ?> from Node 2</h2>
        <div class="card"><video id="player" controls muted playsinline style="width:100%;max-width:960px;border-radius:8px;background:#000"></video>
            <p class="note">Manifest: <a href="<?= $e($src) ?>"><code><?= $e($play['root']) ?></code></a> · <?= $play['segments'] ?> segments · <?= $play['variants'] ?> variant(s) · <?= round($play['duration'], 1) ?> s · players: <?= $play['protocol'] === 'HLS' ? 'hls.js (native HLS on Safari)' : 'dash.js' ?></p></div>
        <?php if ($play['protocol'] === 'HLS'): ?>
            <script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>
            <script>(function(){var v=document.getElementById('player'),u=<?= json_encode($src) ?>;if(window.Hls&&Hls.isSupported()){var h=new Hls();h.loadSource(u);h.attachMedia(v);}else{v.src=u;}})();</script>
        <?php else: ?>
            <script src="https://cdn.jsdelivr.net/npm/dashjs@4/dist/dash.all.min.js"></script>
            <script>(function(){var v=document.getElementById('player');if(window.dashjs){dashjs.MediaPlayer().create().initialize(v,<?= json_encode($src) ?>,false);}})();</script>
        <?php endif; ?>
    <?php endif; ?>
    <h2>Packages on Node 2</h2>
    <?php if ($packages): ?>
        <div class="card"><table><tr><th>Package</th><th>Protocol</th><th>Status</th><th class="num">Segments</th><th class="num">Variants</th><th class="num">Seconds</th><th></th></tr>
        <?php foreach ($packages as $p): ?>
            <tr><td><code><?= $e($p['id']) ?></code></td><td><?= $p['protocol'] ?></td><td><?= $p['ok'] ? '<span class="pass">✔ complete</span>' : '<span class="fail">✖ incomplete</span>' ?></td>
                <td class="num"><?= $p['segments'] ?></td><td class="num"><?= $p['variants'] ?></td><td class="num"><?= round($p['duration'], 1) ?></td><td><a href="?tab=streaming&amp;play=<?= rawurlencode($p['id']) ?>">▶ Play</a></td></tr>
        <?php endforeach; ?></table></div>
        <form method="post" class="card form">
            <label>RTMP egress: push <select name="package"><?php foreach ($packages as $p): ?><option value="<?= $e($p['id']) ?>"><?= $e($p['id']) ?></option><?php endforeach; ?></select></label>
            <label class="wide">to <input type="text" name="url" placeholder="rtmp://a.rtmp.youtube.com/live2/&lt;stream-key&gt;"></label>
            <button name="action" value="egress">Push over RTMP</button>
            <span class="note">Streams in real time (blocks for the clip's duration) with stream copy — no re-encode.</span>
        </form>
    <?php else: ?>
        <div class="card na">No packages yet — package a source or run an RTMP ingest above.</div>
    <?php endif; ?>
    <h2>Live RTMP from OBS or an encoder</h2>
    <div class="card"><pre>php bin/receiver.php --port=9100 --out=received --repackage          # Node 2
php bin/rtmp-ingest.php --port=9100 --rtmp-port=1935 --key=YOUR_KEY   # RTMP edge → Node 1 transport

OBS → Settings → Stream: Service "Custom", Server rtmp://&lt;edge-host&gt;:1935/live, Stream Key YOUR_KEY</pre>
    <p class="note">Each finished stream appears in the table above as <code>…-hls</code> and <code>…-dash</code> packages. The stream key never leaves the edge; frames carry only its SHA-256 prefix.</p></div>
    <?php
}

// ---------------------------------------------------------------- Colorization
if ($tab === 'color') {
    $colorRoot = __DIR__ . '/../colorized';
    $err = null;
    $man = null;
    $job = null;
    $in = [
        'setting' => trim((string) ($_POST['setting'] ?? 'lake, beach')), 'contains' => trim((string) ($_POST['contains'] ?? '')),
        'era' => (string) ($_POST['era'] ?? ''), 'time' => (string) ($_POST['time'] ?? 'midday'),
        'facts' => (string) ($_POST['facts'] ?? ''), 'regions' => (string) ($_POST['regions'] ?? "0.66,0.28,0.82,0.55=stone"),
        'targets' => $post ? (array) ($_POST['targets'] ?? []) : ['1k', '4k'], 'evaluate' => $post ? isset($_POST['evaluate']) : true,
    ];
    if ($post) {
        try {
            $job = gmdate('Ymd-His') . '-' . bin2hex(random_bytes(3));
            $dir = $colorRoot . '/' . $job;
            mkdir($dir, 0775, true);
            if (!empty($_FILES['file']['tmp_name']) && is_uploaded_file($_FILES['file']['tmp_name'])) {
                $ext = preg_replace('/[^a-z0-9]/', '', strtolower(pathinfo((string) $_FILES['file']['name'], PATHINFO_EXTENSION))) ?: 'png';
                $src = $dir . '/source.' . $ext;
                move_uploaded_file($_FILES['file']['tmp_name'], $src);
            } else {
                $src = $dir . '/demo-landscape.png';
                DemoScenes::landscape($src);
            }
            $scene = array_filter(['setting' => $in['setting'], 'contains' => $in['contains'], 'era' => $in['era'], 'time' => $in['time']]);
            $man = (new Colorizer())->run($src, [
                'scene' => $scene, 'facts' => array_filter(array_map('trim', explode("\n", $in['facts']))),
                'regions' => array_filter(array_map('trim', explode("\n", $in['regions']))), 'targets' => $in['targets'] ?: ['1k'],
                'out_dir' => $dir, 'name' => 'out', 'evaluate' => $in['evaluate'], 'max_seconds' => 5, 'max_16k_frames' => 10,
            ]);
        } catch (Throwable $ex) {
            $err = $ex->getMessage();
        }
    }
    $url = fn (string $file, bool $dl = false) => 'colorized.php?f=' . rawurlencode($job) . '/' . rawurlencode(basename($file)) . ($dl ? '&download=1' : '');
    ?>
    <p class="lede">Black and white to colour at <b>1K</b>, <b>4K</b> and <b>16K</b>. Every colour comes from a UFCS fact — material palette, scene, period and lighting — resolved by FQL and recorded with its source and trust. Luminance is kept exactly as observed; colour is marked as reconstructed, and regions the engine is unsure of stay gray rather than receive an invented colour.</p>
    <form method="post" enctype="multipart/form-data" class="card form">
        <label>Black-and-white still or clip <input type="file" name="file" title="leave empty to use the synthetic demo landscape"></label>
        <label>Setting <input type="text" name="setting" value="<?= $e($in['setting']) ?>" placeholder="beach, city, forest…"></label>
        <label>Contains <input type="text" name="contains" value="<?= $e($in['contains']) ?>" placeholder="people"></label>
        <label>Era <select name="era"><option value="">unstated</option><?php foreach (['1920s', '1930s', '1940s', '1950s', '1960s', '1970s', '1980s', 'modern'] as $x): ?><option <?= $x === $in['era'] ? 'selected' : '' ?>><?= $x ?></option><?php endforeach; ?></select></label>
        <label>Light <select name="time"><option value="">unstated</option><?php foreach (['midday', 'golden_hour', 'overcast', 'night', 'tungsten'] as $x): ?><option <?= $x === $in['time'] ? 'selected' : '' ?>><?= $x ?></option><?php endforeach; ?></select></label>
        <label class="check"><input type="checkbox" name="targets[]" value="1k" <?= in_array('1k', $in['targets'], true) ? 'checked' : '' ?>> 1K</label>
        <label class="check"><input type="checkbox" name="targets[]" value="4k" <?= in_array('4k', $in['targets'], true) ? 'checked' : '' ?>> 4K</label>
        <label class="check"><input type="checkbox" name="targets[]" value="16k" <?= in_array('16k', $in['targets'], true) ? 'checked' : '' ?>> 16K</label>
        <label class="check"><input type="checkbox" name="evaluate" <?= $in['evaluate'] ? 'checked' : '' ?>> Score against original colour</label>
        <label class="wide">Known facts, one per line: <code>subject | predicate | object</code> <textarea name="facts" rows="2" placeholder="Golden Gate Bridge | has_color | #C0362C"><?= $e($in['facts']) ?></textarea></label>
        <label class="wide">Region labels, one per line: <code>x0,y0,x1,y1=label</code> (fractions of the frame) <textarea name="regions" rows="2"><?= $e($in['regions']) ?></textarea></label>
        <button>Colorize</button>
    </form>
    <?php if ($err): ?><div class="card fail">✖ <?= $e($err) ?></div><?php endif; ?>
    <?php if ($man): ?>
        <div class="kpis">
            <div class="kpi"><b><?= count($man['outputs']) ?> × <?= $e(implode(' / ', array_map('strtoupper', array_keys($man['outputs'])))) ?></b><span><?= $e($man['input']['kind']) ?>, <?= (int) $man['input']['frames'] ?> frame(s), <?= $e($man['elapsed_s']) ?> s</span></div>
            <?php if (isset($man['evaluation']['skipped'])): ?><div class="kpi"><b>No score</b><span><?= $e($man['evaluation']['skipped']) ?></span></div><?php endif; ?>
            <?php if (isset($man['evaluation']['improvement_pct'])): ?><div class="kpi"><b><?= $e($man['evaluation']['improvement_pct']) ?>%</b><span>closer to the true colour than the gray input (ΔE <?= $e($man['evaluation']['mean_delta_e_colorized']) ?> vs <?= $e($man['evaluation']['mean_delta_e_gray']) ?>)</span></div><?php endif; ?>
            <div class="kpi"><b><?= $e($man['withheld_pct']) ?>%</b><span>kept gray: confidence below <?= Colorizer::WITHHOLD_BELOW ?></span></div>
            <div class="kpi"><b><?= $e(min(array_column($man['outputs'], 'consistency_psnr_db'))) ?> dB</b><span>lowest consistency with the source (luminance)</span></div>
        </div>
        <?php if ($man['preview']): ?><div class="card"><img src="<?= $e($url($man['preview'])) ?>" alt="Black-and-white source beside the colorized result" style="width:100%;border-radius:6px"><p class="note">Left: the black-and-white input. Right: colorized. <?= $e($man['marking']) ?></p></div><?php endif; ?>
        <h2>Downloads</h2>
        <?= ReportView::table(array_map(fn ($o) => ['target' => $o['target'], 'size' => $o['width'] . '×' . $o['height'], 'format' => $o['format'], 'frames' => $o['frames'], 'bytes' => $o['bytes'],
            'psnr' => $o['consistency_psnr_db'], 'ms' => $o['render_ms'], 'link' => '⬇ ' . basename($o['file']) . (is_dir($o['file']) ? '.zip' : '')], $man['outputs']),
            ['target' => 'Target', 'size' => 'Pixels', 'format' => 'Format', 'frames' => 'Frames', 'bytes' => 'Size', 'psnr' => 'Consistency dB', 'ms' => 'Render ms', 'link' => 'File']) ?>
        <p class="note"><?php foreach ($man['outputs'] as $o): ?><a href="<?= $e($url($o['file'], true)) ?>">⬇ <?= $e(strtoupper($o['target'])) ?> <?= $e(basename($o['file'])) ?><?= is_dir($o['file']) ? '.zip' : '' ?></a> · <?php endforeach; ?><a href="<?= $e($url($man['manifest_file'], true)) ?>">⬇ provenance manifest (JSON)</a></p>
        <h2>Where each colour came from</h2>
        <div class="card"><table><tr><th>Region</th><th class="num">Share</th><th>Colour</th><th>Fact</th><th>Source</th><th class="num">Fact trust</th><th class="num">Confidence</th><th class="num">Kept gray</th></tr>
        <?php foreach ($man['regions'] as $cls => $r): $p = $man['palette'][$cls] ?? []; ?>
            <tr><td><?= $e($cls) ?></td><td class="num"><?= $e($r['share_pct']) ?>%</td>
                <td><?php if (!empty($p['hex'])): ?><span style="display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:-2px;background:<?= $e($p['hex']) ?>;border:1px solid var(--line)"></span> <code><?= $e($p['hex']) ?></code><?php else: ?>—<?php endif; ?></td>
                <td><code><?= $e(($p['subject'] ?? '') . ' · ' . substr((string) ($p['fuid'] ?? ''), 0, 10)) ?></code></td><td><?= $e($p['source'] ?? '') ?></td>
                <td class="num"><?= $e($p['trust'] ?? '') ?></td><td class="num"><?= $e($r['mean_confidence']) ?></td><td class="num"><?= $e($r['withheld_pct']) ?>%</td></tr>
        <?php endforeach; ?></table>
        <p class="note">Confidence = the lesser of the material classification and the fact's trust (Registry F224). Grade: lighting <?= $e($man['grade']['lighting']) ?>, era <?= $e($man['grade']['era']) ?>, saturation ×<?= $e($man['grade']['saturation']) ?>, warmth <?= $e($man['grade']['warmth']) ?>.</p></div>
        <h2>Agents and FQL</h2>
        <?= ReportView::table(array_map(fn ($a) => ['agent' => $a['agent'], 'task' => $a['task'], 'ms' => $a['ms']], $man['agents']), ['agent' => 'Agent', 'task' => 'Declared task (F76)', 'ms' => 'ms']) ?>
        <div class="card"><pre><?= $e(implode("\n", $man['fql'])) ?></pre></div>
    <?php endif; ?>
    <?php
}

// ---------------------------------------------------------------- Benchmark
if ($tab === 'bench') {
    $error = null;
    if ($post) {
        try {
            $preset = in_array($_POST['preset'] ?? '', ['smoke', 'quick'], true) ? $_POST['preset'] : 'smoke';
            $report = (new Benchmark(['preset' => $preset, 'sign' => isset($_POST['sign'])]))->run();
            if (!is_dir($reportsDir)) {
                mkdir($reportsDir, 0775, true);
            }
            file_put_contents($reportsDir . '/latest.json', json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
            file_put_contents($reportsDir . '/latest.html', ReportView::page($report));
        } catch (Throwable $ex) {
            $error = $ex->getMessage();
        }
    }
    $latest = is_file($reportsDir . '/latest.json') ? json_decode((string) file_get_contents($reportsDir . '/latest.json'), true) : null;
    ?>
    <p class="lede">The benchmark plan, executable: compression per content type and codec, throughput per priority connection, frame latency, CPU on both nodes, and the mixed workload that proves bulk media cannot starve control traffic.</p>
    <form method="post" class="card form">
        <label>Preset <select name="preset"><option value="smoke">smoke (~5 s)</option><option value="quick">quick (~25 s)</option></select></label>
        <label class="check"><input type="checkbox" name="sign"> Ed25519 sign every frame</label>
        <button>Run benchmark</button>
        <span class="note">For the full preset or a remote Node 2: <code>php bin/bench.php --preset=full --remote=host:9100</code></span>
    </form>
    <?php if ($error): ?><div class="card fail">✖ <?= $e($error) ?></div><?php endif; ?>
    <?php if ($latest): ?>
        <p class="note">Latest report: <?= $e($latest['generated_at'] ?? '') ?> · preset <?= $e($latest['config']['preset'] ?? '') ?></p>
        <?= ReportView::body($latest) ?>
    <?php else: ?>
        <div class="card na">No report yet — run one above.</div>
    <?php endif; ?>
    <?php
}

$content = (string) ob_get_clean();
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UFCS-FQL Compression Lab</title>
<style>
<?= ReportView::CSS ?>
:root{--hx-h:#2a78d6;--hx-m:#eb6834;--hx-p:#7a7974;--hx-c:#1baf7a;--hx-s:#e87ba4}
header.top{border-bottom:1px solid var(--line);background:var(--panel)}header.top .in{max-width:1180px;margin:0 auto;padding:16px}
.eyebrow{color:var(--accent);font-weight:600;font-size:.8rem;letter-spacing:.06em;text-transform:uppercase}
nav{display:flex;flex-wrap:wrap;gap:4px;margin-top:12px}nav a{padding:6px 12px;border-radius:8px;color:var(--text2);text-decoration:none;font-weight:500}
nav a.on{background:var(--accent);color:#fff}nav a:hover:not(.on){background:var(--code)}
.lede{font-size:1.02rem;color:var(--text2);max-width:860px}.note{color:var(--text2);font-size:.88rem}
.form{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.form label{display:flex;flex-direction:column;gap:4px;font-size:.85rem;color:var(--text2)}
.form label.check{flex-direction:row;align-items:center}.form label.wide{flex:1 1 100%}.form input[type=text]{width:100%}
input,select,button{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--text)}
button{background:var(--accent);color:#fff;border:0;padding:8px 16px;font-weight:600;cursor:pointer}
pre.hex{line-height:1.6}.hex .off{color:var(--muted)}.hex .h{color:var(--hx-h)}.hex .m{color:var(--hx-m)}.hex .p{color:var(--hx-p)}.hex .c{color:var(--hx-c);font-weight:700}.hex .s{color:var(--hx-s)}
.arch text{fill:var(--text);font-size:12.5px}.arch .nt{font-weight:700;font-size:15px}.arch .small{fill:var(--text2);font-size:12px}.arch .lt{font-weight:600}
.arch .node{fill:var(--panel);stroke:var(--line);stroke-width:1.5}.arch .mod{fill:var(--code);stroke:var(--line)}
.arch .link{stroke-width:3}.arch .link.s1{stroke:var(--s1)}.arch .link.s2{stroke:var(--s2)}.arch .link.s3{stroke:var(--s3)}.arch .arrowhead{fill:var(--text2)}
</style>
</head>
<body>
<header class="top"><div class="in">
    <div class="eyebrow">QueryBook · <?= Protocol::NAME ?> over TCP/IP</div>
    <h1>QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab</h1>
    <nav><?php foreach ($tabs as $k => $label): ?><a href="?tab=<?= $k ?>" class="<?= $k === $tab ? 'on' : '' ?>"><?= $e($label) ?></a><?php endforeach; ?></nav>
</div></header>
<main><?= $content ?></main>
</body>
</html>
