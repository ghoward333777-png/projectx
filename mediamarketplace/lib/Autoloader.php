<?php

declare(strict_types=1);

namespace MMS;

/**
 * PSR-4 autoloader for the shared MediaMarketplace library.
 *
 * The library is bundled inside each host extension (WordPress plugin, Joomla
 * component) and never installed on its own. Both hosts call Autoloader::register()
 * with the directory that contains this file.
 */
final class Autoloader
{
    private static bool $registered = false;

    public static function register(?string $baseDir = null): void
    {
        if (self::$registered) {
            return;
        }
        $baseDir = rtrim($baseDir ?? __DIR__, '/\\');
        spl_autoload_register(static function (string $class) use ($baseDir): void {
            if (!str_starts_with($class, 'MMS\\')) {
                return;
            }
            $relative = str_replace('\\', '/', substr($class, 4));
            $file = $baseDir . '/' . $relative . '.php';
            if (is_file($file)) {
                require $file;
            }
        });
        self::$registered = true;
    }

    public static function version(): string
    {
        return '0.1.0';
    }
}
