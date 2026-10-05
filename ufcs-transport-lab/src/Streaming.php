<?php

declare(strict_types=1);

/**
 * Adaptive-streaming packaging: HLS (RFC 8216) and MPEG-DASH (ISO/IEC 23009-1).
 *
 * Node 1 packages a source (file, HLS/DASH URL, or an RTMP-ingested FLV) into a
 * multi-rendition ladder with ffmpeg; every playlist, init segment and media
 * segment then travels between the nodes as UFCS-FQL/1 frames (segments on the
 * bulk class, manifests compressed as text). Node 2 rebuilds the package tree,
 * checks it against its own manifest (every referenced file present and
 * hash-verified) and serves it to ordinary HLS / DASH players.
 */
final class StreamPackager
{
    /**
     * Rendition ladder for a source height and link: the top rung comes from
     * Benchmark::planVideo() (bitrate budget from link capacity), then up to
     * $rungs-1 lower rungs from the bitrate ladder.
     *
     * @return array<int, array{height:int, kbps:int}>
     */
    public static function ladder(int $sourceHeight, float $linkMbps, int $rungs = 2): array
    {
        $top = Benchmark::planVideo($sourceHeight, $linkMbps);
        $out = [['height' => $top['height'], 'kbps' => $top['kbps']]];
        foreach (Benchmark::LADDER as $h => $kbps) {
            if (count($out) >= $rungs) {
                break;
            }
            if ($h < $top['height'] && $kbps < $top['kbps']) {
                $out[] = ['height' => $h, 'kbps' => $kbps];
            }
        }
        return $out;
    }

    /**
     * @param array<string, mixed> $o ladder (array of [height,kbps]), segment_seconds, link_mbps
     * @return array<string, mixed> package: protocol, dir, manifest, files (relative paths), ladder, encode_ms
     */
    public static function hls(string $src, array $o = []): array
    {
        $info = MediaCodec::probe($src);
        $ladder = $o['ladder'] ?? self::ladder($info['height'] ?: 720, (float) ($o['link_mbps'] ?? 0));
        $seg = (float) ($o['segment_seconds'] ?? 2);
        $dir = self::workDir('hls');
        [$filter, $maps] = self::ladderFilter($ladder, $info['audio']);
        $vsm = [];
        foreach ($ladder as $i => $_) {
            $vsm[] = 'v:' . $i . ($info['audio'] ? ',a:' . $i : '');
        }
        $args = array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $src, '-filter_complex', $filter], $maps,
            self::encodeArgs($ladder, $info['audio'], $seg),
            ['-f', 'hls', '-hls_time', (string) $seg, '-hls_playlist_type', 'vod', '-hls_flags', 'independent_segments',
                '-hls_segment_type', 'mpegts', '-master_pl_name', 'master.m3u8', '-var_stream_map', implode(' ', $vsm),
                '-hls_segment_filename', $dir . '/v%v/seg%03d.ts', $dir . '/v%v/index.m3u8']);
        $ms = self::ffmpeg($args);
        return self::collect('HLS', $dir, 'master.m3u8', $ladder, $ms);
    }

    /**
     * @param array<string, mixed> $o ladder, segment_seconds, link_mbps
     * @return array<string, mixed>
     */
    public static function dash(string $src, array $o = []): array
    {
        $info = MediaCodec::probe($src);
        $ladder = $o['ladder'] ?? self::ladder($info['height'] ?: 720, (float) ($o['link_mbps'] ?? 0));
        $seg = (float) ($o['segment_seconds'] ?? 2);
        $dir = self::workDir('dash');
        [$filter, $maps] = self::ladderFilter($ladder, $info['audio'], false);
        $sets = 'id=0,streams=v' . ($info['audio'] ? ' id=1,streams=a' : '');
        $args = array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $src, '-filter_complex', $filter], $maps,
            self::encodeArgs($ladder, $info['audio'], $seg, false),
            ['-f', 'dash', '-seg_duration', (string) $seg, '-use_template', '1', '-use_timeline', '1', '-adaptation_sets', $sets,
                '-init_seg_name', 'init-$RepresentationID$.m4s', '-media_seg_name', 'chunk-$RepresentationID$-$Number%05d$.m4s', $dir . '/manifest.mpd']);
        $ms = self::ffmpeg($args);
        return self::collect('DASH', $dir, 'manifest.mpd', $ladder, $ms);
    }

    /** @return array{0:string, 1:array<int, string>} */
    private static function ladderFilter(array $ladder, bool $audio, bool $audioPerRendition = true): array
    {
        $n = count($ladder);
        $filter = '[0:v]split=' . $n . implode('', array_map(fn ($i) => "[s$i]", array_keys($ladder)));
        $maps = [];
        foreach ($ladder as $i => $r) {
            $filter .= ";[s$i]scale=-2:{$r['height']}[v$i]";
            $maps = array_merge($maps, ['-map', "[v$i]"]);
        }
        if ($audio) {
            // HLS: one audio copy per variant (var_stream_map pairs them); DASH: one shared track.
            for ($i = 0; $i < ($audioPerRendition ? $n : 1); $i++) {
                $maps = array_merge($maps, ['-map', '0:a:0']);
            }
        }
        return [$filter, $maps];
    }

    /** @return array<int, string> */
    private static function encodeArgs(array $ladder, bool $audio, float $seg, bool $audioPerRendition = true): array
    {
        // H.264 + AAC: the pairing every HLS and DASH player decodes. Fixed GOP = segment length
        // so every segment starts on a keyframe and renditions switch cleanly.
        $gop = (string) (int) round(30 * $seg);
        $args = ['-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-g', $gop, '-keyint_min', $gop, '-sc_threshold', '0'];
        foreach ($ladder as $i => $r) {
            $args = array_merge($args, ["-b:v:$i", $r['kbps'] . 'k', "-maxrate:v:$i", (int) ($r['kbps'] * 1.2) . 'k', "-bufsize:v:$i", ($r['kbps'] * 2) . 'k']);
        }
        if ($audio) {
            $args = array_merge($args, ['-c:a', 'aac', '-b:a', '96k', '-ac', '2']);
        }
        return $args;
    }

    private static function ffmpeg(array $args): float
    {
        if (MediaCodec::ffmpeg() === '') {
            throw new RuntimeException('ffmpeg is required for HLS/DASH packaging');
        }
        $t = hrtime(true);
        $r = MediaCodec::exec($args);
        if ($r['code'] !== 0) {
            throw new RuntimeException('packaging failed: ' . trim($r['stderr']));
        }
        return round((hrtime(true) - $t) / 1e6, 1);
    }

    private static function workDir(string $kind): string
    {
        $dir = sys_get_temp_dir() . '/ufcs-' . $kind . '-' . bin2hex(random_bytes(5));
        mkdir($dir, 0775, true);
        return $dir;
    }

    private static function collect(string $protocol, string $dir, string $manifest, array $ladder, float $ms): array
    {
        $files = [];
        $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS));
        foreach ($it as $f) {
            $files[] = substr($f->getPathname(), strlen($dir) + 1);
        }
        sort($files);
        $check = Manifest::verify($dir, $manifest);
        if (!$check['ok']) {
            throw new RuntimeException($protocol . ' package is incomplete: ' . implode(', ', $check['missing']));
        }
        return ['protocol' => $protocol, 'dir' => $dir, 'manifest' => $manifest, 'files' => $files, 'ladder' => $ladder, 'encode_ms' => $ms,
            'bytes' => array_sum(array_map(fn ($p) => filesize($dir . '/' . $p), $files)), 'segments' => $check['segments'], 'duration_s' => $check['duration_s']];
    }

    /** Role of a file inside a package (decides content type and priority). */
    public static function role(string $path): string
    {
        $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
        if (in_array($ext, ['m3u8', 'mpd'], true)) {
            return 'manifest';
        }
        return str_starts_with(basename($path), 'init') ? 'init' : 'segment';
    }

    /** A package path is safe when it is relative, has no "..", and uses a conservative alphabet. */
    public static function safePath(string $path): bool
    {
        return $path !== '' && strlen($path) < 200 && preg_match('#^[A-Za-z0-9_][A-Za-z0-9._/-]*$#', $path) === 1
            && !in_array('..', explode('/', $path), true) && !str_contains($path, '//');
    }

    public static function removeDir(string $dir): void
    {
        if (!is_dir($dir)) {
            return;
        }
        $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
        foreach ($it as $f) {
            $f->isDir() ? @rmdir($f->getPathname()) : @unlink($f->getPathname());
        }
        @rmdir($dir);
    }
}

/**
 * Manifest readers for HLS playlists and DASH MPDs — used to validate a
 * package on both nodes and to read remote HLS/DASH sources.
 */
final class Manifest
{
    /** @return array<string, mixed> type master|media, variants, segments, target_duration, endlist */
    public static function parseM3u8(string $text): array
    {
        $lines = preg_split('/\r?\n/', trim($text));
        if (($lines[0] ?? '') !== '#EXTM3U') {
            throw new RuntimeException('Not an HLS playlist (missing #EXTM3U)');
        }
        $out = ['type' => 'media', 'variants' => [], 'segments' => [], 'target_duration' => null, 'endlist' => false, 'version' => null];
        $pending = null;
        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            if (str_starts_with($line, '#EXT-X-STREAM-INF:')) {
                $out['type'] = 'master';
                $pending = ['kind' => 'variant', 'attrs' => self::attrs(substr($line, 18))];
            } elseif (str_starts_with($line, '#EXTINF:')) {
                $pending = ['kind' => 'segment', 'duration' => (float) substr($line, 8)];
            } elseif (str_starts_with($line, '#EXT-X-TARGETDURATION:')) {
                $out['target_duration'] = (int) substr($line, 22);
            } elseif (str_starts_with($line, '#EXT-X-VERSION:')) {
                $out['version'] = (int) substr($line, 15);
            } elseif ($line === '#EXT-X-ENDLIST') {
                $out['endlist'] = true;
            } elseif (str_starts_with($line, '#EXT-X-MAP:')) {
                $out['segments'][] = ['uri' => self::attrs(substr($line, 11))['URI'] ?? '', 'duration' => 0.0, 'init' => true];
            } elseif ($line[0] !== '#' && $pending !== null) {
                if ($pending['kind'] === 'variant') {
                    $out['variants'][] = ['uri' => $line, 'bandwidth' => (int) ($pending['attrs']['BANDWIDTH'] ?? 0),
                        'resolution' => $pending['attrs']['RESOLUTION'] ?? null, 'codecs' => $pending['attrs']['CODECS'] ?? null];
                } else {
                    $out['segments'][] = ['uri' => $line, 'duration' => $pending['duration']];
                }
                $pending = null;
            }
        }
        return $out;
    }

    /** @return array<string, string> */
    private static function attrs(string $s): array
    {
        preg_match_all('/([A-Z0-9-]+)=("[^"]*"|[^,]*)/', $s, $m, PREG_SET_ORDER);
        $out = [];
        foreach ($m as $x) {
            $out[$x[1]] = trim($x[2], '"');
        }
        return $out;
    }

    /** @return array<string, mixed> type, duration_s, representations, files (expanded segment names) */
    public static function parseMpd(string $xml): array
    {
        $prev = libxml_use_internal_errors(true);
        $doc = simplexml_load_string($xml);
        libxml_use_internal_errors($prev);
        if ($doc === false || $doc->getName() !== 'MPD') {
            throw new RuntimeException('Not a DASH MPD');
        }
        $out = ['type' => (string) $doc['type'] ?: 'static', 'duration_s' => self::isoDuration((string) $doc['mediaPresentationDuration']), 'representations' => [], 'files' => []];
        foreach ($doc->Period as $period) {
            foreach ($period->AdaptationSet as $set) {
                foreach ($set->Representation as $rep) {
                    $tpl = $rep->SegmentTemplate ?? null;
                    if ($tpl === null || count($tpl) === 0) {
                        $tpl = $set->SegmentTemplate;
                    }
                    $id = (string) $rep['id'];
                    $r = ['id' => $id, 'bandwidth' => (int) $rep['bandwidth'], 'width' => (int) $rep['width'], 'height' => (int) $rep['height'],
                        'mime' => (string) ($rep['mimeType'] ?: $set['mimeType']), 'codecs' => (string) ($rep['codecs'] ?: $set['codecs']), 'segments' => 0];
                    if ($tpl !== null && count($tpl) > 0) {
                        $sub = fn (string $t, int $n) => preg_replace_callback('/\$(RepresentationID|Number)(%0(\d+)d)?\$/',
                            fn ($m) => $m[1] === 'RepresentationID' ? $id : (isset($m[3]) && $m[3] !== '' ? str_pad((string) $n, (int) $m[3], '0', STR_PAD_LEFT) : (string) $n), $t);
                        if ((string) $tpl['initialization'] !== '') {
                            $out['files'][] = $sub((string) $tpl['initialization'], 0);
                        }
                        $count = 0;
                        if (isset($tpl->SegmentTimeline)) {
                            foreach ($tpl->SegmentTimeline->S as $s) {
                                $count += 1 + (int) $s['r'];
                            }
                        } elseif ((int) $tpl['duration'] > 0) {
                            $count = (int) ceil($out['duration_s'] * max(1, (int) $tpl['timescale']) / (int) $tpl['duration']);
                        }
                        $start = (string) $tpl['startNumber'] !== '' ? (int) $tpl['startNumber'] : 1;
                        for ($n = $start; $n < $start + $count; $n++) {
                            $out['files'][] = $sub((string) $tpl['media'], $n);
                        }
                        $r['segments'] = $count;
                    }
                    $out['representations'][] = $r;
                }
            }
        }
        return $out;
    }

    public static function isoDuration(string $d): float
    {
        if (!preg_match('/^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?$/', $d, $m)) {
            return 0.0;
        }
        return (float) ($m[1] ?? 0) * 86400 + (float) ($m[2] ?? 0) * 3600 + (float) ($m[3] ?? 0) * 60 + (float) ($m[4] ?? 0);
    }

    /**
     * Check a package directory against its root manifest: every playlist,
     * init and media segment it references must exist.
     *
     * @return array{ok:bool, missing:array<int,string>, segments:int, variants:int, duration_s:float}
     */
    public static function verify(string $dir, string $manifest): array
    {
        $missing = [];
        $segments = 0;
        $variants = 0;
        $duration = 0.0;
        $path = $dir . '/' . $manifest;
        if (!is_file($path)) {
            return ['ok' => false, 'missing' => [$manifest], 'segments' => 0, 'variants' => 0, 'duration_s' => 0.0];
        }
        if (str_ends_with($manifest, '.mpd')) {
            $mpd = self::parseMpd((string) file_get_contents($path));
            foreach ($mpd['files'] as $f) {
                if (!is_file($dir . '/' . $f)) {
                    $missing[] = $f;
                }
            }
            $segments = count(array_filter($mpd['files'], fn ($f) => !str_starts_with(basename($f), 'init')));
            return ['ok' => !$missing && $mpd['files'], 'missing' => $missing, 'segments' => $segments, 'variants' => count($mpd['representations']), 'duration_s' => $mpd['duration_s']];
        }
        $root = self::parseM3u8((string) file_get_contents($path));
        $playlists = $root['type'] === 'master' ? array_column($root['variants'], 'uri') : [$manifest];
        $variants = $root['type'] === 'master' ? count($playlists) : 1;
        $base = dirname($manifest) === '.' ? '' : dirname($manifest) . '/';
        foreach ($playlists as $i => $pl) {
            $plPath = $root['type'] === 'master' ? $base . $pl : $pl;
            if (!is_file($dir . '/' . $plPath)) {
                $missing[] = $plPath;
                continue;
            }
            $media = self::parseM3u8((string) file_get_contents($dir . '/' . $plPath));
            $plDir = dirname($plPath) === '.' ? '' : dirname($plPath) . '/';
            $d = 0.0;
            foreach ($media['segments'] as $s) {
                if (!is_file($dir . '/' . $plDir . $s['uri'])) {
                    $missing[] = $plDir . $s['uri'];
                }
                $segments++;
                $d += $s['duration'];
            }
            if ($i === 0) {
                $duration = $d;
            }
        }
        return ['ok' => !$missing && $segments > 0, 'missing' => $missing, 'segments' => $segments, 'variants' => $variants, 'duration_s' => round($duration, 3)];
    }
}
