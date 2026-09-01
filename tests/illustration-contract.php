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
$studio = $writer->illustrationStudio();

$result = $writer->writeBook('Leadership strategy', [
    'author' => 'Garry S. Howard',
    'style' => 'executive',
    'length' => 12,
    'extra_media' => [
        2 => [
            ['kind' => 'chart', 'topic' => 'How decisions compound', 'caption' => 'A custom look.', 'section' => 'The working model'],
            ['kind' => 'ai-image', 'topic' => 'A team at a whiteboard'],
        ],
    ],
]);
$media = $result['media'];

// --- Plan shape -------------------------------------------------------------
contract_check(count($media['chapters']) === count($result['book']['chapters']), 'media plan must cover every chapter');
contract_check($media['figure_count'] > 0 && $media['ai_image_count'] > 0, 'plan must count figures and AI images');
$kindsSeen = [];
foreach ($media['chapters'] as $chapter) {
    contract_check($chapter['items'] !== [], 'every chapter must get at least one figure');
    contract_check($chapter['sections'] !== [], 'every chapter must expose its important topics');
    foreach ($chapter['items'] as $item) {
        contract_check(in_array($item['kind'], IllustrationStudio::KINDS, true), 'item kind must be valid: ' . $item['kind']);
        contract_check(isset($item['id'], $item['title'], $item['caption'], $item['after_section']), 'items must carry id, title, caption, and placement');
        contract_check(isset($item['svg']) || isset($item['table']), 'every item must render as SVG or table data');
        if (isset($item['svg'])) {
            contract_check(str_starts_with($item['svg'], '<svg ') && str_ends_with($item['svg'], '</svg>'), 'SVG must be a complete element');
            contract_check(!str_contains($item['svg'], '<script'), 'SVG must not contain scripts');
            $dom = new DOMDocument();
            contract_check(@$dom->loadXML($item['svg']) !== false, 'SVG must be well-formed XML: ' . $item['id']);
        }
        if (isset($item['table'])) {
            contract_check($item['table']['rows'] !== [] && count($item['table']['columns']) >= 2, 'tables must have columns and rows');
            foreach ($item['table']['rows'] as $row) {
                contract_check(count($row) === count($item['table']['columns']), 'table rows must match the column count');
            }
        }
        $kindsSeen[$item['kind']] = true;
    }
}
foreach (['diagram', 'table', 'illustration', 'ai-image'] as $kind) {
    contract_check(isset($kindsSeen[$kind]), "the default plan must include a {$kind}");
}
// Content relevance: diagrams and worksheets come from the chapter's own outline detail.
$frameworkChapter = null;
foreach ($media['chapters'] as $chapterMedia) {
    if (str_contains($chapterMedia['title'], 'Framework for Practice')) {
        $frameworkChapter = $chapterMedia;
    }
}
contract_check($frameworkChapter !== null, 'practical books must keep a framework chapter');
$diagram = null;
$worksheet = null;
foreach ($frameworkChapter['items'] as $item) {
    if ($item['kind'] === 'diagram') {
        $diagram = $item;
    }
    if ($item['kind'] === 'table') {
        $worksheet = $item;
    }
}
contract_check($diagram !== null && stripos($diagram['svg'], 'diagnose the situation') !== false, 'diagram steps must come from the chapter\'s own material');
contract_check(!str_contains(strtolower($diagram['caption']), 'this chapter'), 'diagram captions must describe the subject, not the writing plan');
contract_check($worksheet !== null && str_contains(json_encode($worksheet['table']), 'Run a small test'), 'worksheet rows must come from the chapter\'s own criteria');
$quote = null;
foreach ($media['chapters'][0]['items'] as $item) {
    if ($item['kind'] === 'illustration') {
        $quote = $item;
    }
}
contract_check($quote !== null && $quote['title'] === 'The takeaway' && str_contains($quote['svg'], 'leaves off'), 'the illustration must carry the chapter\'s takeaway');

// --- User-added media -------------------------------------------------------
$chapter2 = $media['chapters'][1];
$userItems = array_values(array_filter($chapter2['items'], static fn (array $i): bool => !empty($i['user_added'])));
contract_check(count($userItems) === 2, 'user-added rows must land in their chapter');
contract_check($userItems[0]['kind'] === 'chart' && $userItems[0]['title'] === 'How decisions compound', 'user chart must keep its topic');
contract_check($userItems[0]['after_section'] === 'The working model', 'user items must honor the requested section');
contract_check($userItems[0]['caption'] === 'A custom look.', 'user captions must be kept');
contract_check(isset($userItems[1]['ai']['prompt']) && str_contains($userItems[1]['ai']['prompt'], 'A team at a whiteboard'), 'user AI images must get a prompt');

// --- Determinism ------------------------------------------------------------
$again = $writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12]);
contract_check(
    json_encode($again['media']['chapters'][0]['items']) === json_encode(
        $writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12])['media']['chapters'][0]['items'],
    ),
    'media plans must be deterministic',
);

// --- Image manifest ---------------------------------------------------------
foreach (IllustrationStudio::PROVIDERS as $provider) {
    $manifest = $studio->imageManifest($media, $provider);
    contract_check($manifest['provider'] === $provider, "manifest must honor provider {$provider}");
    contract_check($manifest['job_count'] === $media['ai_image_count'], 'manifest must contain every planned AI image');
    $first = $manifest['jobs'][0];
    contract_check(str_ends_with($first['output_file'], '.png'), 'image outputs must be PNGs');
    contract_check(isset($first['request']['endpoint']) && str_starts_with($first['request']['endpoint'], 'https://'), 'jobs must carry an HTTPS endpoint');
    contract_check(str_contains(json_encode($first['request']), $first['prompt'][0] ?? ''), 'payload must carry the prompt');
}
$google = $studio->imageManifest($media, 'google');
contract_check(($google['jobs'][0]['request']['body']['instances'][0]['prompt'] ?? '') === $google['jobs'][0]['prompt'], 'google payload prompt must match');

// --- Teen jobs table --------------------------------------------------------
$teen = $writer->writeBook('Jobs and work for teens', ['author' => 'Garry S. Howard', 'length' => 60, 'style' => 'teen-friendly']);
$foodChapter = null;
foreach ($teen['media']['chapters'] as $chapter) {
    if (str_contains($chapter['title'], 'Food and Restaurant')) {
        $foodChapter = $chapter;
    }
}
contract_check($foodChapter !== null, 'teen book must include the food chapter');
$jobTable = null;
foreach ($foodChapter['items'] as $item) {
    if ($item['kind'] === 'table') {
        $jobTable = $item;
    }
}
contract_check($jobTable !== null && $jobTable['table']['columns'][0] === 'Job', 'teen job chapters must get a job-card table');
contract_check(count($jobTable['table']['rows']) > 0, 'job table must carry rows from the catalog');
$jobChart = null;
foreach ($foodChapter['items'] as $item) {
    if ($item['kind'] === 'chart') {
        $jobChart = $item;
    }
}
contract_check($jobChart !== null && str_contains($jobChart['svg'], 'jobs mentioning it'), 'teen job chapters must chart real schedule data from the catalog');

// --- Exports carry the figures ---------------------------------------------
$exportableFigures = 0;
foreach ($media['chapters'] as $chapter) {
    foreach ($chapter['items'] as $item) {
        if (empty($item['placeholder'])) {
            $exportableFigures++;
        }
    }
}
$html = $writer->exportManuscriptHtml($result['book'], $result['kdp']['metadata'], $media);
contract_check(substr_count($html, '<figure') === $exportableFigures, 'HTML manuscript must embed every real figure and skip placeholders');
contract_check(!str_contains($html, 'AI image — generate with'), 'AI placeholders must stay out of the manuscript exports');
contract_check(str_contains($html, '<svg '), 'HTML manuscript must embed rendered SVGs');
$docx = (new WordManuscriptExporter())->export($result['book'], $result['kdp']['metadata'], $media);
$tmp = tempnam(sys_get_temp_dir(), 'docxfig');
file_put_contents($tmp, $docx);
$zip = new ZipArchive();
contract_check($zip->open($tmp) === true, 'Word export with media must remain a valid package');
$documentXml = (string) $zip->getFromName('word/document.xml');
$zip->close();
unlink($tmp);
contract_check(str_contains($documentXml, 'Figure 1.1'), 'Word export must carry figure captions');
contract_check(str_contains($documentXml, 'svgBlip'), 'Word export must embed the SVG figures as drawings');
contract_check(str_contains($documentXml, '<w:tbl>'), 'Word export must render media tables as native Word tables');
contract_check(!str_contains($documentXml, '<w:hyperlink'), 'Word contents must use standard text, not hyperlinks');
contract_check(str_contains($documentXml, '<w:tab w:val="right" w:leader="dot"'), 'Word contents must carry a dot-leader tab for page numbers');

fwrite(STDOUT, "Illustration studio contract passed\n");
