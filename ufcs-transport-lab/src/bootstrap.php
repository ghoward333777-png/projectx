<?php

declare(strict_types=1);

/** Loads the QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab (no Composer). */
foreach (['Protocol', 'Frame', 'FrameReader', 'Codec', 'MediaCodec', 'Ufcs', 'Fql', 'Transport', 'Sender', 'Receiver', 'LocalNode', 'Benchmark', 'ReportView', 'Streaming', 'Rtmp', 'NetemProxy', 'VideoLab', 'VideoReportView', 'ColorKnowledge', 'Colorizer'] as $class) {
    $file = __DIR__ . '/' . $class . '.php';
    if (is_file($file)) {
        require_once $file;
    }
}

/** The null device for proc_open: NUL on Windows, /dev/null elsewhere. */
function ufcs_lab_devnull(): string
{
    return PHP_OS_FAMILY === 'Windows' ? 'NUL' : '/dev/null';
}

/**
 * Find a command-line tool (ffmpeg, ffprobe, zstd): $envVar first (a full
 * path, or "off"), then the lab's own runtime/bin folder (where the Windows
 * launcher puts its downloads), the usual install folders, then the PATH.
 */
function ufcs_lab_find_tool(string $name, string $envVar = ''): string
{
    $env = $envVar !== '' ? getenv($envVar) : false;
    if ($env === 'off') {
        return '';
    }
    $win = PHP_OS_FAMILY === 'Windows';
    $exe = $win ? $name . '.exe' : $name;
    $runtime = dirname(__DIR__) . DIRECTORY_SEPARATOR . 'runtime' . DIRECTORY_SEPARATOR . 'bin' . DIRECTORY_SEPARATOR . $exe;
    $candidates = array_filter([$env ?: null, $runtime, '/usr/bin/' . $name, '/usr/local/bin/' . $name, '/opt/homebrew/bin/' . $name]);
    foreach ($candidates as $c) {
        if (is_file($c) && ($win || is_executable($c))) {
            return $c;
        }
    }
    $found = trim((string) @shell_exec($win ? 'where ' . $exe . ' 2>NUL' : 'command -v ' . escapeshellarg($name) . ' 2>/dev/null'));
    $found = $found === '' ? '' : (string) strtok($found, "\r\n");
    return $found !== '' && is_file($found) ? $found : '';
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
