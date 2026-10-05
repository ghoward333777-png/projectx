<?php

declare(strict_types=1);

/** Loads the QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab (no Composer). */
foreach (['Protocol', 'Frame', 'FrameReader', 'Codec', 'MediaCodec', 'Ufcs', 'Fql', 'Transport', 'Sender', 'Receiver', 'LocalNode', 'Benchmark', 'ReportView', 'Streaming', 'Rtmp', 'NetemProxy', 'VideoLab', 'VideoReportView', 'ColorKnowledge', 'Colorizer'] as $class) {
    $file = __DIR__ . '/' . $class . '.php';
    if (is_file($file)) {
        require_once $file;
    }
}

/**
 * Re-run the current CLI script with PHP's JIT compiler on, when it is
 * available and off. The colorist's pixel loops run about 2× faster with
 * identical output. Set UFCS_LAB_NO_JIT=1 to skip.
 */
function ufcs_lab_ensure_jit(): void
{
    if (PHP_SAPI !== 'cli' || getenv('UFCS_LAB_NO_JIT') || getenv('UFCS_LAB_JIT_CHILD') || !function_exists('pcntl_exec') || !extension_loaded('Zend OPcache')) {
        return;
    }
    $status = function_exists('opcache_get_status') ? @opcache_get_status(false) : false;
    if (is_array($status) && !empty($status['jit']['on'])) {
        return;
    }
    putenv('UFCS_LAB_JIT_CHILD=1');
    pcntl_exec(PHP_BINARY, array_merge(['-d', 'opcache.enable_cli=1', '-d', 'opcache.jit=tracing', '-d', 'opcache.jit_buffer_size=128M'], $_SERVER['argv']));
}
