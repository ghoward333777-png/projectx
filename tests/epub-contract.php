<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../EpubExporter.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$writer = new AmazonBookWriter();
$exporter = new EpubExporter();
$result = $writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12]);
$epub = $exporter->export($result['book'], $result['kdp']['metadata'], $result['media']);

contract_check(str_starts_with($epub, 'PK'), 'the EPUB must be a ZIP container');

$tmp = tempnam(sys_get_temp_dir(), 'epubtest');
file_put_contents($tmp, $epub);
$zip = new ZipArchive();
contract_check($zip->open($tmp) === true, 'the EPUB must open as a ZIP archive');

// --- OCF requirements -------------------------------------------------------
contract_check($zip->getNameIndex(0) === 'mimetype', 'mimetype must be the first entry');
$stat = $zip->statIndex(0);
contract_check(($stat['comp_method'] ?? -1) === 0, 'mimetype must be stored uncompressed');
contract_check($zip->getFromName('mimetype') === 'application/epub+zip', 'mimetype content must be exact');
contract_check(str_contains((string) $zip->getFromName('META-INF/container.xml'), 'OEBPS/content.opf'), 'container.xml must point at the package document');

// --- Package document -------------------------------------------------------
$opf = (string) $zip->getFromName('OEBPS/content.opf');
contract_check(str_contains($opf, 'version="3.0"'), 'the package must be EPUB 3');
contract_check(str_contains($opf, 'properties="nav"'), 'the manifest must declare the navigation document');
contract_check(str_contains($opf, 'urn:uuid:'), 'the package must carry a UUID identifier');
contract_check(str_contains($opf, 'dcterms:modified'), 'the package must carry dcterms:modified');
contract_check(str_contains($opf, 'Garry S. Howard'), 'the package must credit the author');
foreach ($result['book']['chapters'] as $chapter) {
    contract_check(str_contains($opf, 'chapter-' . $chapter['number'] . '.xhtml'), 'manifest must list chapter ' . $chapter['number']);
}

// --- Every XML part must be well-formed ------------------------------------
for ($i = 0; $i < $zip->numFiles; $i++) {
    $name = (string) $zip->getNameIndex($i);
    if (preg_match('/\.(xhtml|opf|ncx|xml)$/', $name) === 1) {
        $dom = new DOMDocument();
        contract_check(@$dom->loadXML((string) $zip->getFromName($name)) !== false, "part must be well-formed XML: {$name}");
    }
}

// --- Chapters carry the manuscript and the figures --------------------------
$chapter1 = (string) $zip->getFromName('OEBPS/chapter-1.xhtml');
contract_check(str_contains($chapter1, 'Chapter 1:'), 'chapter files must carry their headings');
contract_check(str_contains($chapter1, '<svg '), 'chapter files must embed the SVG figures');
$nav = (string) $zip->getFromName('OEBPS/nav.xhtml');
contract_check(substr_count($nav, '<li>') === count($result['book']['chapters']) + 2, 'nav must list title page, every chapter, and about');
$zip->close();
unlink($tmp);

// --- Determinism ------------------------------------------------------------
$again = $exporter->export($result['book'], $result['kdp']['metadata'], $result['media']);
$partsA = $exporter->buildParts($result['book'], $result['kdp']['metadata'], $result['media']);
$partsB = $exporter->buildParts($result['book'], $result['kdp']['metadata'], $result['media']);
contract_check(json_encode(array_keys($partsA)) === json_encode(array_keys($partsB)), 'part lists must be deterministic');
contract_check($partsA['OEBPS/content.opf'] === $partsB['OEBPS/content.opf'], 'the package document must be deterministic');

fwrite(STDOUT, "EPUB contract passed\n");
