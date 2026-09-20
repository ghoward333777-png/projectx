<?php

declare(strict_types=1);

/**
 * Rebuilds dist/slowdating-install.zip from the dating/ app folder:
 * everything except runtime state, plus INSTALL.txt and an empty
 * state/ placeholder. Run from the repository root:
 *
 *     php dating/bin/build-install-zip.php [path/to/INSTALL.txt]
 */

$root = dirname(__DIR__, 2);
$installTxt = $argv[1] ?? ($root . '/INSTALL.txt');
$zipPath = $root . '/dist/slowdating-install.zip';

@unlink($zipPath);
$zip = new ZipArchive();
if ($zip->open($zipPath, ZipArchive::CREATE) !== true) {
    fwrite(STDERR, "Could not open {$zipPath} for writing.\n");
    exit(1);
}
$iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root . '/dating', FilesystemIterator::SKIP_DOTS));
foreach ($iterator as $file) {
    $relative = substr((string) $file, strlen($root . '/dating/'));
    if (str_starts_with($relative, 'state/') || $relative === '.gitignore') {
        continue;
    }
    $zip->addFile((string) $file, 'slowdating/' . $relative);
}
if (is_file($installTxt)) {
    $zip->addFile($installTxt, 'slowdating/INSTALL.txt');
}
$zip->addFromString('slowdating/state/.keep', '');
$count = $zip->numFiles;
$zip->close();
echo "Install zip rebuilt: {$count} files, " . filesize($zipPath) . " bytes\n";
