<?php

declare(strict_types=1);

/** Loads the QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab (no Composer). */
foreach (['Protocol', 'Frame', 'FrameReader', 'Codec', 'MediaCodec', 'Ufcs', 'Fql', 'Transport', 'Sender', 'Receiver', 'LocalNode', 'Benchmark', 'ReportView', 'Streaming', 'Rtmp', 'NetemProxy', 'VideoLab', 'VideoReportView', 'ColorKnowledge', 'Colorizer'] as $class) {
    $file = __DIR__ . '/' . $class . '.php';
    if (is_file($file)) {
        require_once $file;
    }
}
