<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../PrintMediaCompanion.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

// --- QR encoder invariants ---------------------------------------------------
contract_check(QrCode::bchFormat(0b00000) === 0b101010000010010, 'format bits for ECC M / mask 0 must match the spec');
contract_check(QrCode::bchVersion(7) === 0x07C94, 'version information for v7 must match the spec');

$matrix = QrCode::matrix('https://example.com/book#chapter-1');
$size = count($matrix);
contract_check(($size - 17) % 4 === 0 && $size >= 21, 'matrix size must be a valid QR version');
foreach ($matrix as $row) {
    contract_check(count($row) === $size, 'matrix must be square');
    foreach ($row as $module) {
        contract_check($module === 0 || $module === 1, 'every module must be resolved to 0 or 1');
    }
}
// Finder pattern corners: dark outer ring, and light separator inside the symbol.
foreach ([[0, 0], [0, $size - 7], [$size - 7, 0]] as [$r, $c]) {
    contract_check($matrix[$r][$c] === 1, 'finder corner must be dark');
    contract_check($matrix[$r + 3][$c + 3] === 1, 'finder center must be dark');
    contract_check($matrix[$r + 1][$c + 1] === 0, 'finder inner ring must be light');
}
// Timing pattern alternates.
for ($i = 8; $i < $size - 8; $i++) {
    contract_check($matrix[6][$i] === (($i % 2 === 0) ? 1 : 0), 'horizontal timing must alternate');
    contract_check($matrix[$i][6] === (($i % 2 === 0) ? 1 : 0), 'vertical timing must alternate');
}
contract_check($matrix[$size - 8][8] === 1, 'the dark module must be dark');
// Version scaling and capacity limit.
contract_check(count(QrCode::matrix(str_repeat('a', 200))) === 57, '200 bytes must select version 10');
$overflowRejected = false;
try {
    QrCode::matrix(str_repeat('a', 250));
} catch (InvalidArgumentException $e) {
    $overflowRejected = true;
}
contract_check($overflowRejected, 'payloads beyond version 10 must be rejected clearly');
$svg = QrCode::svg('https://example.com/x');
contract_check(str_starts_with($svg, '<svg ') && str_ends_with($svg, '</svg>'), 'QR SVG must be a complete element');
$dom = new DOMDocument();
contract_check(@$dom->loadXML($svg) !== false, 'QR SVG must be well-formed XML');

// --- Companion plan ----------------------------------------------------------
$writer = new AmazonBookWriter();
$companion = new PrintMediaCompanion();
$result = $writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12]);
$plan = $companion->companionPlan($result['book'], $result['kdp']['metadata'], $result['media'], 'https://example.com/my-book/');

contract_check($plan['base_url'] === 'https://example.com/my-book', 'base URLs must be normalized');
contract_check(count($plan['chapters']) === count($result['book']['chapters']), 'every chapter must get a QR entry');
contract_check($plan['chapters'][0]['url'] === 'https://example.com/my-book#chapter-1', 'chapter URLs must anchor to the companion page');
contract_check(str_contains($plan['master']['qr_svg'], '<svg '), 'the master entry must carry a QR SVG');
foreach ($plan['chapters'] as $entry) {
    contract_check(str_contains((string) $entry['qr_svg'], '<svg '), 'chapter entries must carry QR SVGs');
}
$fallback = $companion->companionPlan($result['book'], $result['kdp']['metadata'], $result['media'], 'not-a-url');
contract_check($fallback['base_url'] === PrintMediaCompanion::DEFAULT_BASE_URL, 'invalid base URLs must fall back to the placeholder');

// --- Companion page ----------------------------------------------------------
$page = $companion->exportCompanionHtml($result['book'], $result['kdp']['metadata'], $result['media'], 'https://example.com/my-book');
foreach ($result['book']['chapters'] as $chapter) {
    contract_check(str_contains($page, 'id="chapter-' . $chapter['number'] . '"'), 'companion page must anchor chapter ' . $chapter['number']);
}
contract_check(str_contains($page, '<svg '), 'companion page must carry the chapter figures');
contract_check(!str_contains($page, '<script'), 'companion page must not contain scripts');

// --- QR sheet ----------------------------------------------------------------
$sheet = $companion->exportQrSheetHtml($plan, $result['kdp']['metadata']);
contract_check(substr_count($sheet, '<svg ') === count($plan['chapters']) + 1, 'QR sheet must carry every chapter code plus the master');
contract_check(str_contains($sheet, 'chapter-1'), 'QR sheet must print the URLs');

// --- Manuscript integration --------------------------------------------------
$html = $writer->exportManuscriptHtml($result['book'], $result['kdp']['metadata'], $result['media'], $plan);
contract_check(substr_count($html, 'Scan for this chapter') === count($result['book']['chapters']), 'the print manuscript must embed one QR per chapter');

fwrite(STDOUT, "Print media contract passed\n");
