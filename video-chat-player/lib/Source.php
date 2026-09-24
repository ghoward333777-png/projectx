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
    private const EXTENSIONS = ['mp4', 'webm', 'm4v'];

    /** @return array{kind: string, src: string, label: string}|null */
    public static function resolve(string $requested, string $mediaDir): ?array
    {
        $requested = trim($requested);
        if ($requested === '') {
            return null;
        }
        if (str_starts_with($requested, 'media/')) {
            $name = substr($requested, 6);
            if (!self::isMediaName($name) || !is_file($mediaDir . '/' . $name)) {
                return null;
            }
            return ['kind' => 'file', 'src' => 'media/' . $name, 'label' => $name];
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

    /** @return array{kind: string, src: string, label: string} */
    public static function defaultSource(): array
    {
        return ['kind' => 'url', 'src' => self::DEFAULT_URL, 'label' => 'Big Buck Bunny (sample MP4)'];
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
