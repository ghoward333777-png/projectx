<?php

declare(strict_types=1);

/**
 * Build the one-file magazine installer.
 *
 *   php bin/build-magazine-installer.php [output-path]
 *
 * The result (install.php by default) carries every magazine file inside it. The site owner
 * uploads that single file to the web folder, opens it in a browser, fills in a short form,
 * and the installer unpacks the site, creates the administrator, writes config.php, and
 * deletes itself. Re-running a newer installer on a live site updates the code and keeps
 * all content.
 */
function build_magazine_installer(string $output): int
{
    $root = __DIR__ . '/../magazine';
    $files = [];
    foreach (array_merge(glob($root . '/*.php') ?: [], glob($root . '/assets/*') ?: []) as $path) {
        $name = ltrim(str_replace($root, '', $path), '/');
        if ($name !== 'config.php') {
            $files[$name] = base64_encode((string) file_get_contents($path));
        }
    }
    ksort($files);
    $template = (string) file_get_contents(__DIR__ . '/magazine-installer-template.php');
    $marker = "'@@FILES@@'";
    if (substr_count($template, $marker) !== 1) {
        throw new RuntimeException('The installer template has no file marker.');
    }
    file_put_contents($output, str_replace($marker, var_export($files, true), $template));
    return count($files);
}

if (PHP_SAPI === 'cli' && realpath($argv[0] ?? '') === __FILE__) {
    $output = $argv[1] ?? getcwd() . '/install.php';
    $count = build_magazine_installer($output);
    fwrite(STDOUT, "Wrote {$output} with {$count} files (" . number_format((int) filesize($output)) . " bytes)\n");
}
