<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../ManuscriptHygiene.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

// --- Invisible characters ---------------------------------------------------
$dirty = "The\u{200B} approach\u{200C} vanished.\u{FEFF}";
$clean = ManuscriptHygiene::clean($dirty);
contract_check($clean === 'The approach vanished.', 'zero-width characters and BOMs must be stripped: ' . bin2hex($clean));
contract_check(!str_contains(ManuscriptHygiene::clean("soft\u{00AD}hyphen"), "\u{00AD}"), 'soft hyphens must be stripped');

// --- Exotic spaces ----------------------------------------------------------
contract_check(ManuscriptHygiene::clean("a\u{00A0}b\u{2009}c") === 'a b c', 'non-breaking and thin spaces must become ordinary spaces');

// --- Whitespace -------------------------------------------------------------
contract_check(ManuscriptHygiene::clean("one   two\tthree") === 'one two three', 'runs of spaces and tabs must collapse');
contract_check(ManuscriptHygiene::clean("line  \r\nnext") === "line\nnext", 'CRLF must normalize and trailing spaces must go');
contract_check(ManuscriptHygiene::clean("para\n\n\n\n\npara") === "para\n\npara", 'blank-line runs must collapse to one');
contract_check(ManuscriptHygiene::clean("  padded  ") === 'padded', 'leading and trailing whitespace must be trimmed');

// --- Paragraph structure survives ------------------------------------------
$chapter = "Chapter 1: A Title\n\nFirst paragraph here.\n\nSecond paragraph here.";
contract_check(ManuscriptHygiene::clean($chapter) === $chapter, 'clean text must pass through untouched');
contract_check(ManuscriptHygiene::isClean($chapter), 'isClean must recognize already-clean text');
contract_check(!ManuscriptHygiene::isClean("dirty\u{200B}text"), 'isClean must reject text carrying invisibles');

// --- Single lines -----------------------------------------------------------
contract_check(ManuscriptHygiene::cleanLine("  Chapter\u{00A0}one   title \n") === 'Chapter one title', 'cleanLine must flatten to one tidy line');

// --- Determinism ------------------------------------------------------------
contract_check(ManuscriptHygiene::clean($dirty) === ManuscriptHygiene::clean($dirty), 'hygiene must be deterministic');

$writer = new AmazonBookWriter();

// --- Developed chapters are cleaned on the way in ---------------------------
$result = $writer->writeBook('Leadership strategy', ['author' => 'G', 'length' => 12]);
$number = (int) $result['book']['chapters'][0]['number'];
$developed = $writer->writeBook('Leadership strategy', [
    'author' => 'G',
    'length' => 12,
    'developed_chapters' => [$number => "Chapter {$number}: Test\u{200B}\n\n\n\nA  paragraph with   junk.\u{00A0}"],
]);
$stored = (string) $developed['book']['chapters'][0]['content'];
contract_check(!str_contains($stored, "\u{200B}") && !str_contains($stored, "\u{00A0}"), 'developed chapters must be cleaned before becoming book text');
contract_check(!str_contains($stored, '  ') && !str_contains($stored, "\n\n\n"), 'developed chapters must have regular spacing');

// --- Pasted outlines are cleaned -------------------------------------------
$rows = AmazonBookWriter::parseOutline("1.\u{00A0}Traditional gender\u{200B} relations   before WWII");
contract_check($rows[0]['title'] === 'Traditional gender relations before WWII', 'outline rows must be cleaned: ' . $rows[0]['title']);

// --- Rhythm rules reach the writer -----------------------------------------
$contract = (string) $writer->manuscriptDeveloper()->developmentPlan($result['book'], $result['kdp']['metadata'], 'anthropic')['style_contract'];
contract_check(str_contains($contract, 'RHYTHM AND VARIETY'), 'the style contract must carry the rhythm section');
foreach (['Vary sentence length', 'Vary paragraph shape', 'banned outright'] as $rule) {
    contract_check(str_contains($contract, $rule), "rhythm rules must include: {$rule}");
}
$plan = $writer->manuscriptDeveloper()->developmentPlan($result['book'], $result['kdp']['metadata'], 'anthropic');
contract_check(str_contains((string) $plan['writer_jobs'][0]['prompt'], 'Cadence for this chapter:'), 'each chapter must get a cadence directive');
contract_check(
    (string) $plan['writer_jobs'][0]['prompt'] !== (string) $plan['writer_jobs'][1]['prompt'],
    'neighbouring chapters must not share one cadence directive',
);
contract_check(str_contains((string) $plan['editor_jobs'][0]['prompt_template'], 'revise structurally'), 'the editor pass must do structural revision');

// --- Revision report --------------------------------------------------------
$report = $result['revision_report'];
contract_check($report['chapter_count'] === count($result['book']['chapters']), 'the revision report must cover every chapter');
contract_check(isset($report['verdict'], $report['flagged_count']), 'the report must carry a verdict and a flag count');
$thin = $writer->manuscriptDeveloper()->revisionReport(['chapters' => [
    ['number' => 1, 'title' => 'Thin', 'content' => "Chapter 1: Thin\n\nOne short paragraph.", 'word_count' => 6, 'plan_word_target' => 2500],
]]);
$flags = implode(' ', $thin['chapters'][0]['flags']);
contract_check(str_contains($flags, 'Runs short'), 'a short chapter must be flagged');
contract_check(str_contains($flags, 'No closing takeaway'), 'a missing takeaway must be flagged');
contract_check(str_contains($flags, 'paragraphs'), 'a thin chapter must be flagged for paragraph count');
contract_check($thin['flagged_count'] === 1 && str_contains($thin['verdict'], 'want a human pass'), 'the verdict must count flagged chapters');

fwrite(STDOUT, "Manuscript hygiene contract passed\n");
