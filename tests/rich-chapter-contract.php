<?php

declare(strict_types=1);

require_once __DIR__ . '/../BookIntelligenceEngine.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$engine = new BookIntelligenceEngine();
$defaults = $engine->defaultPageStyle();
contract_check($defaults['page_number_position'] === 'bottom-right', 'default PHP page numbers must be bottom-right');
contract_check($defaults['footer'] === 'Author Garry S. Howard 2026', 'default PHP footer must contain the author copyright notice');
$book = $engine->generateBookFromTableOfContents(
    'Document design',
    [[
        'title' => 'A structured chapter',
        'purpose' => 'Keep the payload readable',
        'detail' => 'Use a heading and paragraphs that a React editor can safely render.',
    ]],
    'conversational',
    1,
    'Editors',
    'Make formatting visible',
    [
        'font_family' => 'Garamond',
        'font_size' => 22,
        'line_height' => 1.8,
        'background' => 'linen',
        'border_style' => 'double',
        'border_width' => 3,
        'border_color' => '#123456',
        'margin' => 'wide',
        'show_page_numbers' => true,
        'page_number_position' => 'bottom-right',
        'header' => 'Field notes',
        'footer' => 'Working manuscript',
    ],
);

contract_check(isset($book['page_style']) && is_array($book['page_style']), 'page_style must be present');
contract_check($book['page_style']['font_family'] === 'Garamond', 'page style values must survive normalization');
contract_check($book['page_style']['background'] === 'linen', 'page background must use the React-compatible enum');
contract_check($book['page_style']['page_number_position'] === 'bottom-right', 'page number position must be compatible');

$chapter = $book['chapters'][0] ?? null;
contract_check(is_array($chapter), 'generated book must contain a chapter');
contract_check(isset($chapter['content'], $chapter['blocks']) && is_array($chapter['blocks']), 'chapter must expose content and structured blocks');

$allowedKinds = ['paragraph', 'heading', 'quote', 'bulletList', 'table', 'chart', 'illustration', 'image', 'pageBreak'];
$projectedContent = [];
foreach ($chapter['blocks'] as $index => $block) {
    contract_check(is_array($block), "block {$index} must be an object");
    contract_check(is_string($block['id'] ?? null) && $block['id'] !== '', "block {$index} needs a stable id");
    contract_check(in_array($block['kind'] ?? null, $allowedKinds, true), "block {$index} kind must match the React vocabulary");
    contract_check(array_key_exists('content', $block), "block {$index} must include the React text content field");
    contract_check(is_string($block['content']), "block {$index} content must be plain text");
    if (($block['kind'] ?? null) === 'heading') {
        contract_check(($block['level'] ?? null) === null || (($block['level'] >= 1) && ($block['level'] <= 10)), "heading {$index} level must be between 1 and 10");
    }
    $projectedContent[] = $block['content'];
}

contract_check(trim(implode("\n\n", $projectedContent)) === trim($chapter['content']), 'structured blocks must retain the chapter text projection');

fwrite(STDOUT, "Rich chapter PHP contract passed\n");