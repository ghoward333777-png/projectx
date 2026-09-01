<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../WordManuscriptExporter.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$writer = new AmazonBookWriter();

// --- Full pipeline on a generic topic -------------------------------------
$result = $writer->writeBook('Leadership strategy', [
    'reader' => 'new team leads',
    'author' => 'Garry S. Howard',
    'style' => 'executive',
    'length' => 12,
]);

contract_check(isset($result['kit'], $result['book'], $result['kdp']), 'writeBook must return kit, book, and kdp package');

$meta = $result['kdp']['metadata'];
contract_check(is_string($meta['title']) && $meta['title'] !== '', 'listing must include a title');
contract_check(mb_strlen($meta['title']) + mb_strlen($meta['subtitle']) <= AmazonBookWriter::MAX_TITLE_LENGTH, 'title plus subtitle must fit the 200-character KDP limit');
contract_check($meta['author'] === 'Garry S. Howard', 'author name must flow into the listing');
contract_check(mb_strlen($meta['description']) <= AmazonBookWriter::MAX_DESCRIPTION_LENGTH, 'description must fit the 4,000-character KDP limit');
contract_check(mb_strlen($meta['description']) > 200, 'description must be substantial, not a stub');

$keywords = $meta['keywords'];
contract_check(count($keywords) === AmazonBookWriter::KEYWORD_SLOTS, 'exactly seven keyword slots must be filled');
contract_check(count(array_unique($keywords)) === AmazonBookWriter::KEYWORD_SLOTS, 'keywords must be unique');
foreach ($keywords as $index => $keyword) {
    contract_check(is_string($keyword) && $keyword !== '' && mb_strlen($keyword) <= AmazonBookWriter::MAX_KEYWORD_LENGTH, "keyword {$index} must be 1-50 characters");
}

$categories = $meta['categories'];
contract_check(is_array($categories) && count($categories) >= 1 && count($categories) <= 3, 'one to three category suggestions are required');

// --- Paperback economics ---------------------------------------------------
$paperback = $result['kdp']['paperback'];
contract_check($paperback['page_count'] >= 24 && $paperback['page_count'] <= 828, 'paperback page count must respect KDP limits');
contract_check($paperback['printing_cost'] > 0, 'printing cost must be positive');
contract_check($paperback['list_price'] >= $paperback['minimum_list_price'], 'list price must not fall below the KDP minimum');
$expectedRoyalty = round((0.60 * $paperback['list_price']) - $paperback['printing_cost'], 2);
contract_check(abs($paperback['royalty_per_copy'] - max(0.0, $expectedRoyalty)) < 0.01, 'paperback royalty must follow (60% × list price) − printing cost');

$longBook = $writer->paperbackPlan(300);
contract_check(abs($longBook['printing_cost'] - (1.00 + 300 * 0.012)) < 0.001, 'long paperbacks must use the fixed + per-page printing model');
$shortBook = $writer->paperbackPlan(10);
contract_check($shortBook['page_count'] === 24, 'paperbacks below 24 pages must be padded to the KDP minimum');

// --- Ebook economics -------------------------------------------------------
$ebook = $result['kdp']['ebook'];
contract_check($ebook['price'] > 0, 'ebook price must be positive');
if ($ebook['price'] >= 2.99 && $ebook['price'] <= 9.99) {
    contract_check(abs($ebook['royalty_rate'] - 0.70) < 0.001, 'ebook priced $2.99-$9.99 must land on the 70% plan');
}
$cheapEbook = $writer->ebookPlan(30000, 0.99);
contract_check(abs($cheapEbook['royalty_rate'] - 0.35) < 0.001, 'ebook priced under $2.99 must fall back to the 35% plan');
contract_check(abs($cheapEbook['royalty_per_copy'] - round(0.99 * 0.35, 2)) < 0.01, '35% plan royalty must be 35% of price with no delivery fee');

// --- Checklist -------------------------------------------------------------
$checklist = $result['kdp']['checklist'];
contract_check(is_array($checklist) && count($checklist) >= 5, 'the publishing checklist must cover the KDP flow');
foreach ($checklist as $index => $item) {
    contract_check(isset($item['step'], $item['status'], $item['detail']), "checklist item {$index} must have step, status, and detail");
}

// --- Manuscript export -----------------------------------------------------
$html = $writer->exportManuscriptHtml($result['book'], $meta);
contract_check(str_contains($html, '<!DOCTYPE html>'), 'manuscript export must be a standalone HTML document');
contract_check(str_contains($html, 'Copyright ©'), 'manuscript export must include a copyright page');
contract_check(str_contains($html, 'Table of Contents'), 'manuscript export must include a table of contents');
foreach ($result['book']['chapters'] as $chapter) {
    contract_check(
        str_contains($html, 'Chapter ' . $chapter['number'] . ': ' . htmlspecialchars((string) $chapter['title'], ENT_QUOTES, 'UTF-8')),
        'manuscript export must contain every chapter heading',
    );
}
contract_check(!str_contains($html, '<script'), 'manuscript export must not contain scripts');

// --- Word (.docx) export ---------------------------------------------------
$docx = (new WordManuscriptExporter())->export($result['book'], $meta);
contract_check(str_starts_with($docx, 'PK'), 'Word export must be a ZIP (OOXML) package');
$tmp = tempnam(sys_get_temp_dir(), 'docxtest');
file_put_contents($tmp, $docx);
$zip = new ZipArchive();
contract_check($zip->open($tmp) === true, 'Word export must open as a ZIP archive');
$documentXml = (string) $zip->getFromName('word/document.xml');
$stylesXml = (string) $zip->getFromName('word/styles.xml');
contract_check($zip->getFromName('[Content_Types].xml') !== false, 'Word export must declare content types');
$zip->close();
unlink($tmp);
contract_check(str_contains($stylesXml, 'Times New Roman'), 'Word styles must set the manuscript font');
contract_check(str_contains($documentXml, '<w:pgSz w:w="8640" w:h="12960"/>'), 'Word export must use the 6x9 KDP trim');
foreach ($result['book']['chapters'] as $chapter) {
    contract_check(
        str_contains($documentXml, 'Chapter ' . $chapter['number'] . ': ' . htmlspecialchars((string) $chapter['title'], ENT_XML1 | ENT_QUOTES, 'UTF-8')),
        'Word export must contain every chapter heading',
    );
}
$domAvailable = class_exists(DOMDocument::class);
if ($domAvailable) {
    $dom = new DOMDocument();
    contract_check($dom->loadXML($documentXml) !== false, 'Word document.xml must be well-formed XML');
}
contract_check(count($result['book']['chapters'][0]['blocks']) > 1, 'chapters must keep paragraph structure after word-target trimming');

// --- Metadata export -------------------------------------------------------
$export = $writer->exportMetadata($result['kdp']);
contract_check(isset($export['kdp_book_details']['title'], $export['kdp_book_details']['keywords'], $export['kdp_pricing']['paperback'], $export['kdp_pricing']['ebook']), 'metadata export must mirror the KDP setup screens');
contract_check(json_encode($export) !== false, 'metadata export must be JSON-serializable');

// --- Teen-jobs flagship topic ---------------------------------------------
$teen = $writer->writeBook('Jobs and work for teens', ['author' => 'Garry S. Howard', 'length' => 60, 'style' => 'teen-friendly']);
contract_check(count($teen['book']['chapters']) === 27, 'teen-jobs manuscript must use the canonical 27-chapter outline');
contract_check(count($teen['book']['job_catalog']) === 120, 'teen-jobs package must carry the 120-job catalog');
$teenCategories = implode(' ', $teen['kdp']['metadata']['categories']);
contract_check(str_contains($teenCategories, 'Teen & Young Adult'), 'teen-jobs listing must suggest a Teen & Young Adult category');

// --- Curated social-issue outlines ----------------------------------------
$engine = new BookIntelligenceEngine();
$approachToc = $engine->suggestTableOfContents("Why men don't approach women");
$approachTitles = implode(' | ', array_column($approachToc, 'title'));
contract_check(count($approachToc) >= 15, 'the approach book must get a full curated outline, not a template');
foreach (['Before World War II', 'When the Men Went to War', 'The Home Without a Parent', 'Chivalry on Trial', 'Rivals, Not Partners', 'Gloria Allred', 'A Date Through the Decades', 'Two Courtships', 'The Paycheck Gap Flips', 'The Retreating Man', 'Relearning the Approach'] as $expected) {
    contract_check(str_contains($approachTitles, $expected), "approach outline must cover: {$expected}");
}
$socialToc = $engine->suggestTableOfContents('The decline of the American family');
contract_check(count($socialToc) === 10 && $socialToc[0]['title'] === 'The State of Affairs Today', 'social topics must get the narrated-history arc');
contract_check(!str_contains(strtolower(implode(' ', array_column($socialToc, 'title'))), 'system'), 'social outlines must never talk about systems');
contract_check($engine->suggestTableOfContents('Leadership strategy')[5]['title'] === 'A Framework for Practice', 'practical topics must keep the how-to arc');

// --- Author-supplied outlines ----------------------------------------------
$rows = AmazonBookWriter::parseOutline("1. Traditional gender relations Pre-WW II\n2) During WWII | Show the rupture | Men overseas, women in factories, first paychecks in their own names.\nChapter 3: Families without a parent at home\n\n");
contract_check(count($rows) === 3, 'outline parsing must keep one chapter per non-empty line');
contract_check($rows[0]['title'] === 'Traditional gender relations Pre-WW II', 'outline parsing must strip leading numbering');
contract_check($rows[1]['purpose'] === 'Show the rupture' && str_contains($rows[1]['detail'], 'first paychecks'), 'pipe-separated purpose and detail must be honored');
$custom = $writer->writeBook("Why men don't approach women", ['chapters' => $rows, 'length' => 12]);
contract_check(count($custom['book']['chapters']) === 3 && $custom['book']['chapters'][0]['title'] === $rows[0]['title'], 'writeBook must draft from the author-supplied outline');

// --- Nonfiction Outline Editor ---------------------------------------------
$review = $engine->reviewOutline("Why men don't approach women", $approachToc);
contract_check($review['agent']['name'] === 'The Nonfiction Outline Editor', 'outline review must come from the editor agent');
contract_check($review['score'] === 100 && $review['verdict'] === 'Ready to draft', 'the curated approach outline must pass every editorial rule');
contract_check($custom['outline_review']['chapter_count'] === 3, 'writeBook must review the outline it actually drafted from');
contract_check($custom['outline_review']['suggestions'] !== [], 'a three-chapter outline must draw editorial suggestions');
$thinReview = $engine->reviewOutline('The decline of community', [['title' => 'Systems Overview', 'purpose' => 'x', 'detail' => 'y']]);
contract_check($thinReview['score'] < 70 && $thinReview['verdict'] === 'Needs restructuring', 'a thin abstract outline must be flagged for restructuring');

fwrite(STDOUT, "Amazon Book Writer contract passed\n");
