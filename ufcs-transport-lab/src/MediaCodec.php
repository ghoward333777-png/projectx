<?php

declare(strict_types=1);

/**
 * Content-aware lossy transcoders for video, audio and images.
 *
 * Video and audio go through ffmpeg (H.264 / H.265 / AV1, Opus / AAC) when it
 * is installed; images go through PHP GD (WebP), so image compression works
 * with no external tools at all. Every encode reports what it actually did —
 * codec, bitrate, resolution, sample rate — so the benchmark never claims a
 * transform that did not happen.
 */
final class MediaCodec
{
    private const VIDEO_ENCODERS = [Protocol::C_H264 => 'libx264', Protocol::C_H265 => 'libx265', Protocol::C_AV1 => 'libsvtav1'];
    private const AUDIO_ENCODERS = [Protocol::C_OPUS => 'libopus', Protocol::C_AAC => 'aac'];

    private static ?string $ffmpeg = null;
    /** @var null|array<string, bool> */
    private static ?array $encoders = null;

    public static function ffmpeg(): string
    {
        if (self::$ffmpeg === null) {
            self::$ffmpeg = ufcs_lab_find_tool('ffmpeg', 'UFCS_LAB_FFMPEG');
        }
        return self::$ffmpeg;
    }

    public static function hasEncoder(string $name): bool
    {
        if (self::$encoders === null) {
            self::$encoders = [];
            if (self::ffmpeg() !== '') {
                $list = (string) self::run([self::ffmpeg(), '-hide_banner', '-encoders'])['stdout'];
                foreach (array_merge(self::VIDEO_ENCODERS, self::AUDIO_ENCODERS) as $enc) {
                    self::$encoders[$enc] = (bool) preg_match('/^\s*[VA]\S*\s+' . preg_quote($enc, '/') . '\s/m', $list);
                }
            }
        }
        return self::$encoders[$name] ?? false;
    }

    /** @return array<string, array{available:bool, kind:string, note:string}> */
    public static function codecMatrix(): array
    {
        $rows = [];
        foreach (self::VIDEO_ENCODERS as $code => $enc) {
            $rows[Protocol::compressionName($code)] = ['available' => self::hasEncoder($enc), 'kind' => 'lossy video', 'note' => 'ffmpeg ' . $enc];
        }
        foreach (self::AUDIO_ENCODERS as $code => $enc) {
            $rows[Protocol::compressionName($code)] = ['available' => self::hasEncoder($enc), 'kind' => 'lossy audio', 'note' => 'ffmpeg ' . $enc];
        }
        return $rows;
    }

    /**
     * Pick a video bitrate from link capacity: the video gets $share of the
     * link minus the audio track, never below 150 kbps.
     */
    public static function targetVideoKbps(int $linkKbps, float $share = 0.8, int $audioKbps = 32): int
    {
        return max(150, (int) floor($linkKbps * $share) - $audioKbps);
    }

    // --- Synthetic test sources (deterministic) ---------------------------

    /** Uncompressed Y4M (yuv420p) — the honest baseline for video ratios. */
    public static function makeTestVideo(string $path, int $width, int $height, float $seconds, int $fps = 30): void
    {
        self::requireFfmpeg();
        self::mustRun([self::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', sprintf('testsrc2=size=%dx%d:rate=%d', $width, $height, $fps),
            '-vf', 'noise=alls=6:allf=t+u:all_seed=7', '-t', (string) $seconds, '-pix_fmt', 'yuv420p', '-f', 'yuv4mpegpipe', $path]);
    }

    /** Near-lossless H.264 + AAC MP4 (an edge-camera style source for HLS/DASH/RTMP runs). */
    public static function makeTestAv(string $path, int $width, int $height, float $seconds): void
    {
        self::requireFfmpeg();
        self::mustRun([self::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', sprintf('testsrc2=size=%dx%d:rate=30', $width, $height),
            '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000', '-t', (string) $seconds,
            '-vf', 'noise=alls=6:allf=t+u:all_seed=7', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '14', '-g', '30', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', $path]);
    }

    /** Does a local file or a manifest (HLS .m3u8 / DASH .mpd) decode end to end? */
    public static function verifyPath(string $path): ?array
    {
        if (self::ffmpeg() === '') {
            return null;
        }
        $r = self::run([self::ffmpeg(), '-hide_banner', '-v', 'error', '-i', $path, '-f', 'null', '-']);
        return ['ok' => $r['code'] === 0 && trim($r['stderr']) === '', 'detail' => trim($r['stderr']) ?: 'decoded cleanly'];
    }

    /**
     * Objective quality of $distorted against $reference: PSNR (Y and average,
     * dB) and SSIM (All), after scaling the distorted video back to the
     * reference resolution. Optional loop/duration lets a looped live feed be
     * compared with its master.
     *
     * @return array{psnr_y:?float, psnr_avg:?float, ssim:?float, frames:?int}
     */
    public static function quality(string $distorted, string $reference, int $w, int $h, ?float $seconds = null, bool $loopReference = false): array
    {
        self::requireFfmpeg();
        $args = [self::ffmpeg(), '-hide_banner', '-nostats', '-i', $distorted];
        if ($loopReference) {
            $args = array_merge($args, ['-stream_loop', '-1']);
        }
        $args = array_merge($args, ['-i', $reference]);
        if ($seconds !== null) {
            $args = array_merge($args, ['-t', (string) $seconds]);
        }
        // Align by frame index (both sides are constant frame rate): container start offsets
        // (MPEG-TS, FLV) would otherwise pair each frame with its neighbour.
        $f = "[0:v]scale={$w}:{$h}:flags=bicubic,format=yuv420p,setpts=N/FRAME_RATE/TB,split[d1][d2];[1:v]format=yuv420p,setpts=N/FRAME_RATE/TB,split[r1][r2];[d1][r1]psnr;[d2][r2]ssim";
        $args = array_merge($args, ['-lavfi', $f, '-f', 'null', '-']);
        $e = self::run($args)['stderr'];
        $out = ['psnr_y' => null, 'psnr_avg' => null, 'ssim' => null, 'frames' => null];
        if (preg_match('/PSNR y:([\d.inf]+).*average:([\d.inf]+)/', $e, $m)) {
            $out['psnr_y'] = is_numeric($m[1]) ? round((float) $m[1], 2) : null;
            $out['psnr_avg'] = is_numeric($m[2]) ? round((float) $m[2], 2) : null;
        }
        if (preg_match('/SSIM .*All:([\d.]+)/', $e, $m)) {
            $out['ssim'] = round((float) $m[1], 4);
        }
        if (preg_match_all('/frame=\s*(\d+)/', $e, $m)) {
            $out['frames'] = (int) end($m[1]);
        }
        return $out;
    }

    /**
     * Decode cost: ffmpeg -benchmark on one thread (cost per core) — wall
     * time, CPU time, and how many times faster than real time.
     *
     * @return array{ok:bool, rtime_s:float, cpu_s:float, media_s:float, realtime_x:?float, cpu_per_media_s:?float}
     */
    public static function decodeCost(string $file, int $threads = 1): array
    {
        self::requireFfmpeg();
        $info = self::probe($file);
        $r = self::run([self::ffmpeg(), '-hide_banner', '-nostats', '-benchmark', '-threads', (string) $threads, '-i', $file, '-f', 'null', '-']);
        $rt = $ut = $st = 0.0;
        if (preg_match('/bench: utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s/', $r['stderr'], $m)) {
            [$ut, $st, $rt] = [(float) $m[1], (float) $m[2], (float) $m[3]];
        }
        $media = $info['duration_s'];
        return ['ok' => $r['code'] === 0, 'rtime_s' => round($rt, 3), 'cpu_s' => round($ut + $st, 3), 'media_s' => round($media, 2),
            'realtime_x' => $rt > 0 ? round($media / $rt, 1) : null, 'cpu_per_media_s' => $media > 0 ? round(($ut + $st) / $media, 3) : null];
    }

    /** Spatial / temporal information (ITU-T P.910) averages — how hard the content is to compress. */
    public static function siti(string $file): array
    {
        self::requireFfmpeg();
        $e = self::run([self::ffmpeg(), '-hide_banner', '-nostats', '-i', $file, '-vf', 'siti=print_summary=1', '-f', 'null', '-'])['stderr'];
        $out = ['si' => null, 'ti' => null];
        if (preg_match('/Spatial Information:\s*Average:\s*([\d.]+)/', $e, $m)) {
            $out['si'] = round((float) $m[1], 1);
        }
        if (preg_match('/Temporal Information:\s*Average:\s*([\d.]+)/', $e, $m)) {
            $out['ti'] = round((float) $m[1], 1);
        }
        return $out;
    }

    /** PCM WAV, 48 kHz stereo s16 — speech-like formant tone with a slow tremolo. */
    public static function makeTestAudio(string $path, float $seconds): void
    {
        self::requireFfmpeg();
        $expr = '0.4*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*3*t))+0.2*sin(2*PI*660*t)*(0.5+0.5*sin(2*PI*5*t))+0.1*sin(2*PI*1240*t)';
        self::mustRun([self::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', 'aevalsrc=' . $expr . '|' . $expr . ':s=48000', '-t', (string) $seconds,
            '-c:a', 'pcm_s16le', $path]);
    }

    /**
     * Deterministic photo-like PNG rendered with GD: smooth gradients and soft
     * shapes under low-amplitude sensor-style noise (what makes real photos
     * expensive as PNG and cheap as lossy WebP).
     */
    public static function makeTestImage(int $width, int $height, int $seed): string
    {
        $img = imagecreatetruecolor($width, $height);
        mt_srand($seed);
        for ($i = 0; $i < 18; $i++) {
            $c = imagecolorallocate($img, mt_rand(40, 230), mt_rand(40, 230), mt_rand(40, 230));
            imagefilledellipse($img, mt_rand(0, $width), mt_rand(0, $height), mt_rand($width / 8, $width / 2), mt_rand($height / 8, $height / 2), $c);
        }
        imagefilter($img, IMG_FILTER_SMOOTH, -6);
        for ($pass = 0; $pass < 6; $pass++) {
            imagefilter($img, IMG_FILTER_GAUSSIAN_BLUR);
        }
        for ($y = 0; $y < $height; $y += 2) {
            for ($x = 0; $x < $width; $x += 2) {
                $rgb = imagecolorat($img, $x, $y);
                $shade = (int) (24 * sin(($x + $seed * 13) / 97.0) * cos(($y + $seed * 7) / 71.0));
                $n = mt_rand(-7, 7) + $shade;
                $r = max(0, min(255, (($rgb >> 16) & 255) + $n));
                $g = max(0, min(255, (($rgb >> 8) & 255) + $n + mt_rand(-3, 3)));
                $b = max(0, min(255, ($rgb & 255) + $n + mt_rand(-3, 3)));
                imagefilledrectangle($img, $x, $y, $x + 1, $y + 1, imagecolorallocate($img, $r, $g, $b));
            }
        }
        imagestring($img, 5, 12, 12, 'UFCS-FQL lab image #' . $seed, imagecolorallocate($img, 255, 255, 255));
        mt_srand();
        ob_start();
        imagepng($img, null, 6);
        imagedestroy($img);
        return (string) ob_get_clean();
    }

    // --- Encoders -----------------------------------------------------------

    /**
     * Transcode a video file. Options: codec (C_H264|C_H265|C_AV1),
     * kbps (target bitrate; omitted → crf quality mode), crf, height (downscale),
     * container (mpegts|mp4), preset.
     *
     * @param array<string, mixed> $o
     * @return array<string, mixed>
     */
    public static function encodeVideo(string $src, array $o = []): array
    {
        self::requireFfmpeg();
        $codec = (int) ($o['codec'] ?? Protocol::C_H264);
        $encoder = self::VIDEO_ENCODERS[$codec] ?? null;
        if ($encoder === null || !self::hasEncoder($encoder)) {
            throw new RuntimeException(Protocol::compressionName($codec) . ' encoder unavailable');
        }
        // AV1 cannot be demuxed from MPEG-TS by common ffmpeg builds; Matroska streams just as well.
        $container = (string) ($o['container'] ?? self::defaultContainer($codec));
        $out = self::tmp(self::extensionFor($codec, $container));
        $args = [self::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $src, '-an', '-c:v', $encoder];
        if (!empty($o['height'])) {
            $args = array_merge($args, ['-vf', 'scale=-2:' . (int) $o['height']]);
        }
        $mode = 'crf ' . (int) ($o['crf'] ?? 28);
        if (!empty($o['kbps'])) {
            $k = (int) $o['kbps'];
            $args = array_merge($args, ['-b:v', $k . 'k', '-maxrate', (int) ($k * 1.2) . 'k', '-bufsize', ($k * 2) . 'k']);
            $mode = 'VBR ' . $k . ' kbps (cap ' . (int) ($k * 1.2) . ')';
        } else {
            $args = array_merge($args, ['-crf', (string) (int) ($o['crf'] ?? ($codec === Protocol::C_AV1 ? 40 : 28))]);
        }
        if ($codec === Protocol::C_H264 || $codec === Protocol::C_H265) {
            $args = array_merge($args, ['-preset', (string) ($o['preset'] ?? 'veryfast'), '-pix_fmt', 'yuv420p']);
        } else {
            $args = array_merge($args, ['-preset', (string) ($o['preset'] ?? '10'), '-pix_fmt', 'yuv420p']);
        }
        if ($codec === Protocol::C_AV1) {
            $args = array_merge($args, ['-svtav1-params', 'log-level=0']);
        }
        if ($codec === Protocol::C_H265) {
            $args = array_merge($args, ['-x265-params', 'log-level=error', '-tag:v', 'hvc1']);
        }
        if ($container === 'mp4') {
            $args = array_merge($args, ['-movflags', '+faststart']);
        }
        $args = array_merge($args, ['-f', $container, $out]);
        $t0 = hrtime(true);
        self::mustRun($args);
        $ms = (hrtime(true) - $t0) / 1e6;
        $bytes = (string) file_get_contents($out);
        @unlink($out);
        return ['bytes' => $bytes, 'codec' => $codec, 'container' => $container, 'mode' => $mode,
            'height' => $o['height'] ?? null, 'encode_ms' => round($ms, 1)];
    }

    /**
     * Transcode audio. Options: codec (C_OPUS|C_AAC), kbps, rate (Hz), channels.
     *
     * @param array<string, mixed> $o
     * @return array<string, mixed>
     */
    public static function encodeAudio(string $src, array $o = []): array
    {
        self::requireFfmpeg();
        $codec = (int) ($o['codec'] ?? Protocol::C_OPUS);
        $encoder = self::AUDIO_ENCODERS[$codec] ?? null;
        if ($encoder === null || !self::hasEncoder($encoder)) {
            throw new RuntimeException(Protocol::compressionName($codec) . ' encoder unavailable');
        }
        $rate = (int) ($o['rate'] ?? 24000);
        $channels = (int) ($o['channels'] ?? 1);
        $kbps = (int) ($o['kbps'] ?? 24);
        $out = self::tmp($codec === Protocol::C_OPUS ? '.ogg' : '.aac');
        $args = [self::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $src, '-vn',
            '-ac', (string) $channels, '-ar', (string) $rate, '-c:a', $encoder, '-b:a', $kbps . 'k'];
        if ($codec === Protocol::C_OPUS) {
            // Constrained VBR: unconstrained Opus VBR overshoots a link-derived target on tonal content.
            $args = array_merge($args, ['-vbr', 'constrained', '-application', $channels === 1 ? 'voip' : 'audio', '-f', 'ogg']);
        } else {
            $args = array_merge($args, ['-f', 'adts']);
        }
        $args[] = $out;
        $t0 = hrtime(true);
        self::mustRun($args);
        $ms = (hrtime(true) - $t0) / 1e6;
        $bytes = (string) file_get_contents($out);
        @unlink($out);
        return ['bytes' => $bytes, 'codec' => $codec, 'rate' => $rate, 'channels' => $channels,
            'mode' => $kbps . ' kbps, ' . ($rate / 1000) . ' kHz, ' . ($channels === 1 ? 'mono' : 'stereo'), 'encode_ms' => round($ms, 1)];
    }

    /**
     * Re-encode an image as WebP with GD. Options: quality (0-100), max_width.
     *
     * @param array<string, mixed> $o
     * @return array<string, mixed>
     */
    public static function encodeImage(string $bytes, array $o = []): array
    {
        if (!function_exists('imagewebp')) {
            throw new RuntimeException('WebP unavailable: PHP GD was built without WebP');
        }
        $t0 = hrtime(true);
        $img = @imagecreatefromstring($bytes);
        if ($img === false) {
            throw new RuntimeException('Image does not decode');
        }
        $w = imagesx($img);
        $h = imagesy($img);
        $max = (int) ($o['max_width'] ?? 0);
        if ($max > 0 && $w > $max) {
            $scaled = imagescale($img, $max, (int) round($h * $max / $w), IMG_BICUBIC);
            imagedestroy($img);
            $img = $scaled;
        }
        $quality = (int) ($o['quality'] ?? 80);
        ob_start();
        imagewebp($img, null, $quality);
        $out = (string) ob_get_clean();
        $outW = imagesx($img);
        $outH = imagesy($img);
        imagedestroy($img);
        return ['bytes' => $out, 'codec' => Protocol::C_WEBP, 'width' => $outW, 'height' => $outH, 'source' => $w . 'x' . $h,
            'mode' => 'WebP q' . $quality . ($outW !== $w ? ', downscaled to ' . $outW . 'px' : ''), 'encode_ms' => round((hrtime(true) - $t0) / 1e6, 1)];
    }

    /**
     * Decode check: does the bitstream decode end to end? Returns frame/sample
     * counts from ffmpeg, or null when ffmpeg is absent.
     *
     * @return null|array{ok:bool, detail:string}
     */
    public static function verifyDecodes(string $bytes, string $ext): ?array
    {
        if (self::ffmpeg() === '') {
            return null;
        }
        $in = self::tmp($ext);
        file_put_contents($in, $bytes);
        $r = self::run([self::ffmpeg(), '-hide_banner', '-v', 'error', '-i', $in, '-f', 'null', '-']);
        @unlink($in);
        return ['ok' => $r['code'] === 0 && trim($r['stderr']) === '', 'detail' => trim($r['stderr']) ?: 'decoded cleanly'];
    }

    public static function defaultContainer(int $codec): string
    {
        return $codec === Protocol::C_AV1 ? 'matroska' : 'mpegts';
    }

    /**
     * Stream facts for a file or URL from ffmpeg's own report.
     *
     * @return array{video:bool, audio:bool, width:int, height:int, duration_s:float, video_codec:?string, audio_codec:?string}
     */
    public static function probe(string $src): array
    {
        self::requireFfmpeg();
        $r = self::run([self::ffmpeg(), '-hide_banner', '-i', $src]);
        $e = $r['stderr'];
        $out = ['video' => false, 'audio' => false, 'width' => 0, 'height' => 0, 'duration_s' => 0.0, 'video_codec' => null, 'audio_codec' => null];
        if (preg_match('/Stream #\S+.*?: Video: (\w+).*?, (\d{2,5})x(\d{2,5})/', $e, $m)) {
            $out = ['video' => true, 'video_codec' => $m[1], 'width' => (int) $m[2], 'height' => (int) $m[3]] + $out;
        }
        if (preg_match('/Stream #\S+.*?: Audio: (\w+)/', $e, $m)) {
            $out['audio'] = true;
            $out['audio_codec'] = $m[1];
        }
        if (preg_match('/Duration: (\d+):(\d+):([\d.]+)/', $e, $m)) {
            $out['duration_s'] = $m[1] * 3600 + $m[2] * 60 + (float) $m[3];
        }
        return $out;
    }

    /**
     * Run a command with both pipes drained.
     *
     * @param array<int, string> $args
     * @return array{code:int, stdout:string, stderr:string}
     */
    public static function exec(array $args): array
    {
        return self::run($args);
    }

    public static function extensionFor(int $codec, ?string $container = null): string
    {
        $container ??= self::defaultContainer($codec);
        return match ($codec) {
            Protocol::C_H264, Protocol::C_H265, Protocol::C_AV1 => ['mp4' => '.mp4', 'matroska' => '.mkv'][$container] ?? '.ts',
            Protocol::C_OPUS => '.ogg',
            Protocol::C_AAC => '.aac',
            Protocol::C_WEBP => '.webp',
            default => '.bin',
        };
    }

    private static function requireFfmpeg(): void
    {
        if (self::ffmpeg() === '') {
            throw new RuntimeException('ffmpeg is not installed; video and audio transcoding are unavailable');
        }
    }

    private static function tmp(string $ext): string
    {
        return sys_get_temp_dir() . '/ufcs-media-' . bin2hex(random_bytes(6)) . $ext;
    }

    /** @param array<int, string> $args */
    private static function mustRun(array $args): void
    {
        $r = self::run($args);
        if ($r['code'] !== 0) {
            throw new RuntimeException('ffmpeg failed: ' . trim($r['stderr']));
        }
    }

    /**
     * @param array<int, string> $args
     * @return array{code:int, stdout:string, stderr:string}
     */
    private static function run(array $args): array
    {
        if (PHP_OS_FAMILY === 'Windows') {
            return self::runViaFiles($args);
        }
        $proc = proc_open($args, [0 => ['file', ufcs_lab_devnull(), 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
        if (!is_resource($proc)) {
            return ['code' => -1, 'stdout' => '', 'stderr' => 'could not start ' . $args[0]];
        }
        // Drain both pipes together so a chatty stderr cannot block stdout.
        $out = $err = '';
        stream_set_blocking($pipes[1], false);
        stream_set_blocking($pipes[2], false);
        while (!feof($pipes[1]) || !feof($pipes[2])) {
            $r = array_filter([$pipes[1], $pipes[2]], fn ($p) => !feof($p));
            $w = $e = null;
            if (@stream_select($r, $w, $e, 1) === false) {
                break;
            }
            foreach ($r as $p) {
                $chunk = (string) fread($p, 65536);
                if ($p === $pipes[1]) {
                    $out .= $chunk;
                } else {
                    $err .= $chunk;
                }
            }
        }
        fclose($pipes[1]);
        fclose($pipes[2]);
        return ['code' => proc_close($proc), 'stdout' => $out, 'stderr' => $err];
    }

    /**
     * Windows cannot stream_select() on process pipes, so a pipe nobody is
     * reading would stall the tool. Send its output to temporary files instead.
     *
     * @param array<int, string> $args
     * @return array{code:int, stdout:string, stderr:string}
     */
    private static function runViaFiles(array $args): array
    {
        $outFile = (string) tempnam(sys_get_temp_dir(), 'ufcs-out-');
        $errFile = (string) tempnam(sys_get_temp_dir(), 'ufcs-err-');
        $proc = proc_open($args, [0 => ['file', ufcs_lab_devnull(), 'r'], 1 => ['file', $outFile, 'w'], 2 => ['file', $errFile, 'w']], $pipes);
        if (!is_resource($proc)) {
            @unlink($outFile);
            @unlink($errFile);
            return ['code' => -1, 'stdout' => '', 'stderr' => 'could not start ' . $args[0]];
        }
        $code = proc_close($proc);
        $out = (string) @file_get_contents($outFile);
        $err = (string) @file_get_contents($errFile);
        @unlink($outFile);
        @unlink($errFile);
        return ['code' => $code, 'stdout' => $out, 'stderr' => $err];
    }
}
