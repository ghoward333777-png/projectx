<?php
declare(strict_types=1);

/**
 * Builds the WordPress plugin zip and the Joomla module zip, each with the whole player
 * bundled under app/. Pure functions over the file system so a test can build into a
 * temporary folder and inspect the result.
 */
final class IntegrationBuilder
{
    /** Player files that ship inside an integration (relative to the app folder). */
    public const APP_INCLUDE = ['index.php', 'api.php', 'media.php', 'api-docs.php', 'embed-demo.php', 'config.php', 'API.md', 'README.md', 'INTEGRATIONS.md', 'lib', 'assets', 'media/sample.mp4'];
    public const APP_EXCLUDE = ['local-config.php'];

    public static function appFiles(string $appDir): array
    {
        $out = [];
        foreach (self::APP_INCLUDE as $entry) {
            $path = $appDir . '/' . $entry;
            if (is_file($path)) {
                $out[$entry] = $path;
            } elseif (is_dir($path)) {
                $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($path, FilesystemIterator::SKIP_DOTS));
                foreach ($it as $file) {
                    $rel = $entry . '/' . substr((string) $file->getPathname(), strlen($path) + 1);
                    if (!in_array(basename($rel), self::APP_EXCLUDE, true)) {
                        $out[str_replace('\\', '/', $rel)] = (string) $file->getPathname();
                    }
                }
            }
        }
        ksort($out);
        return $out;
    }

    /** @return array<string, string> zip path => source path */
    public static function wordpressFiles(string $appDir): array
    {
        $root = $appDir . '/integrations/wordpress/watch-room';
        $files = ['watch-room/watch-room.php' => $root . '/watch-room.php', 'watch-room/readme.txt' => $root . '/readme.txt'];
        foreach (self::appFiles($appDir) as $rel => $src) {
            $files['watch-room/app/' . $rel] = $src;
        }
        return $files;
    }

    /** @return array<string, string> */
    public static function joomlaFiles(string $appDir): array
    {
        $root = $appDir . '/integrations/joomla/mod_watchroom';
        $files = [];
        $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS));
        foreach ($it as $file) {
            $files[str_replace('\\', '/', substr((string) $file->getPathname(), strlen($root) + 1))] = (string) $file->getPathname();
        }
        foreach (self::appFiles($appDir) as $rel => $src) {
            $files['app/' . $rel] = $src;
        }
        ksort($files);
        return $files;
    }

    /** Writes a zip; the rooms folder placeholder keeps the app runnable before first config. */
    public static function zip(array $files, string $target): int
    {
        if (!class_exists(ZipArchive::class)) {
            throw new RuntimeException('The PHP zip extension is required to build install packages.');
        }
        if (!is_dir(dirname($target))) {
            mkdir(dirname($target), 0775, true);
        }
        $zip = new ZipArchive();
        if ($zip->open($target, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
            throw new RuntimeException("Cannot write {$target}");
        }
        foreach ($files as $inZip => $source) {
            $zip->addFile($source, $inZip);
        }
        $zip->close();
        return count($files);
    }

    /** @return array<string, int> zip path => file count */
    public static function buildAll(string $appDir, string $distDir): array
    {
        return [
            $distDir . '/watch-room-wordpress.zip' => self::zip(self::wordpressFiles($appDir), $distDir . '/watch-room-wordpress.zip'),
            $distDir . '/mod_watchroom-joomla.zip' => self::zip(self::joomlaFiles($appDir), $distDir . '/mod_watchroom-joomla.zip'),
        ];
    }
}
