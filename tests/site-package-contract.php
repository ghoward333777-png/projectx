<?php

declare(strict_types=1);

require_once __DIR__ . '/../SitePackageExporter.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$exporter = new SitePackageExporter();

contract_check($exporter->missingFiles() === [], 'every packaged file must exist in the app directory');

$bytes = $exporter->export();
contract_check(str_starts_with($bytes, 'PK'), 'the hosting package must be a ZIP archive');

$tmp = tempnam(sys_get_temp_dir(), 'sitepkg');
file_put_contents($tmp, $bytes);
$zip = new ZipArchive();
contract_check($zip->open($tmp) === true, 'the hosting package must open as a ZIP archive');

$entries = [];
for ($i = 0; $i < $zip->numFiles; $i++) {
    $entries[] = (string) $zip->getNameIndex($i);
}
foreach ($exporter->packagedFiles() as $file) {
    contract_check(in_array('book-intelligence-studio/' . $file, $entries, true), "package must contain {$file}");
}
contract_check(in_array('book-intelligence-studio/INSTALL.txt', $entries, true), 'package must contain the INSTALL.txt guide');

$install = (string) $zip->getFromName('book-intelligence-studio/INSTALL.txt');
contract_check(str_contains($install, 'PHP 8.1'), 'install guide must state the PHP requirement');
contract_check(str_contains($install, 'public_html'), 'install guide must explain where to upload');
contract_check(str_contains($install, 'explicit') && str_contains($install, 'consent'), 'install guide must carry the voice-cloning consent requirement');

$engine = (string) $zip->getFromName('book-intelligence-studio/BookIntelligenceEngine.php');
contract_check($engine === file_get_contents(__DIR__ . '/../BookIntelligenceEngine.php'), 'packaged files must match the live app byte for byte');
$zip->close();
unlink($tmp);

fwrite(STDOUT, "Site package contract passed\n");
