<?php
declare(strict_types=1);

/**
 * Resolves what the stage should play: a file from the local media/ folder or an
 * https URL to an MP4/WebM. Anything else is refused so index.php never echoes a
 * hostile value into the page.
 */
final class Source
{
    public const DEFAULT_URL = 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4';
    public const SAMPLE = 'sample.mp4';
    private const EXTENSIONS = ['mp4', 'webm', 'm4v'];

    /** @return array{kind: string, src: string, label: string}|null */
    public static function resolve(string $requested, string $mediaDir): ?array
    {
        $requested = trim($requested);
        if ($requested === '') {
            return null;
        }
        if (str_starts_with($requested, 'media.php?f=')) {
            $requested = 'media/' . rawurldecode(explode('&', substr($requested, 12), 2)[0]);
        }
        if (str_starts_with($requested, 'media/')) {
            $name = substr($requested, 6);
            if (!self::isMediaName($name) || !is_file($mediaDir . '/' . $name)) {
                return null;
            }
            return ['kind' => 'file', 'src' => 'media.php?f=' . rawurlencode($name), 'label' => $name, 'name' => $name];
        }
        $parts = parse_url($requested);
        if (!is_array($parts) || ($parts['scheme'] ?? '') !== 'https' || ($parts['host'] ?? '') === '') {
            return null;
        }
        $path = (string) ($parts['path'] ?? '');
        if (!self::hasMediaExtension($path)) {
            return null;
        }
        $label = rawurldecode(basename($path));
        return ['kind' => 'url', 'src' => $requested, 'label' => $label];
    }

    /** The bundled sample when present, else a public sample MP4. @return array{kind: string, src: string, label: string} */
    public static function defaultSource(string $mediaDir): array
    {
        return self::resolve('media/' . self::SAMPLE, $mediaDir)
            ?? ['kind' => 'url', 'src' => self::DEFAULT_URL, 'label' => 'Big Buck Bunny (sample MP4)'];
    }

    public static function mimeType(string $name): string
    {
        return match (strtolower(pathinfo($name, PATHINFO_EXTENSION))) {
            'webm' => 'video/webm',
            'm4v' => 'video/x-m4v',
            default => 'video/mp4',
        };
    }

    /**
     * Parses an HTTP Range header for a file of $size bytes.
     * Returns [start, end] for a satisfiable range, null when there is no usable range
     * (serve the whole file), or false when the range is unsatisfiable (416).
     * @return array{0: int, 1: int}|null|false
     */
    public static function parseRange(string $header, int $size): array|null|false
    {
        if ($header === '' || $size <= 0 || preg_match('/^bytes=(\d*)-(\d*)$/', trim($header), $m) !== 1) {
            return null;
        }
        [, $from, $to] = $m;
        if ($from === '' && $to === '') {
            return null;
        }
        if ($from === '') {
            $length = (int) $to;
            if ($length === 0) {
                return false;
            }
            return [max(0, $size - $length), $size - 1];
        }
        $start = (int) $from;
        $end = $to === '' ? $size - 1 : min($size - 1, (int) $to);
        if ($start >= $size || $start > $end) {
            return false;
        }
        return [$start, $end];
    }

    /** Files in media/ the loader can offer, sorted by name. @return list<string> */
    public static function library(string $mediaDir): array
    {
        if (!is_dir($mediaDir)) {
            return [];
        }
        $names = [];
        foreach (scandir($mediaDir) ?: [] as $name) {
            if (self::isMediaName($name) && is_file($mediaDir . '/' . $name)) {
                $names[] = $name;
            }
        }
        sort($names, SORT_NATURAL | SORT_FLAG_CASE);
        return $names;
    }

    public static function isMediaName(string $name): bool
    {
        return preg_match('/^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}$/', $name) === 1
            && !str_contains($name, '..')
            && self::hasMediaExtension($name);
    }

    private static function hasMediaExtension(string $path): bool
    {
        $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
        return in_array($ext, self::EXTENSIONS, true);
    }
}
