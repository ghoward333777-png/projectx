<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../QualityLab.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$writer = new AmazonBookWriter();
$lab = new QualityLab();
$result = $writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12]);
$kit = $lab->productionKit($result);

// --- Quality scores ---------------------------------------------------------
$scores = $kit['editorial_quality_report'];
contract_check($scores['metric_count'] >= 30, 'the lab must evaluate at least 30 metrics');
foreach (['editorial', 'media', 'format'] as $group) {
    contract_check($scores[$group]['score'] >= 0 && $scores[$group]['score'] <= 100, "{$group} score must be 0-100");
    contract_check(in_array($scores[$group]['badge'], ['Bronze', 'Silver', 'Gold', 'Platinum'], true), "{$group} badge must be a certification level");
    foreach ($scores[$group]['metrics'] as $metric) {
        contract_check(isset($metric['key'], $metric['label'], $metric['note']), 'metrics must carry key, label, and note');
        contract_check($metric['value'] >= 0 && $metric['value'] <= 100, 'metric values must be 0-100: ' . $metric['key']);
    }
}
$unr = $scores['unr'];
$expected = (int) round($scores['editorial']['score'] * 0.45 + $scores['media']['score'] * 0.30 + $scores['format']['score'] * 0.25);
contract_check($unr['score'] === $expected, 'UNR must follow the 45/30/25 weighting');

// --- Complexity -------------------------------------------------------------
$c = $kit['complexity'];
foreach (['pages', 'words', 'chapters', 'sections', 'toc_levels', 'figures', 'audio_segments', 'case_study_moments', 'exercises_and_actions'] as $key) {
    contract_check(isset($c[$key]), "complexity must report {$key}");
}
contract_check($c['chapters'] === count($result['book']['chapters']), 'complexity chapter count must match the book');

// --- KDP compliance ---------------------------------------------------------
$compliance = $kit['kdp_compatibility_report'];
contract_check(count($compliance) >= 10, 'the compatibility report must run at least 10 checks');
foreach ($compliance as $check) {
    contract_check(in_array($check['status'], ['pass', 'warn'], true), 'compliance statuses must be pass or warn');
}
$checkNames = array_column($compliance, 'check');
foreach (['Trim size', 'Paperback pages', 'Hardcover pages', 'Title & subtitle', 'Keywords', 'Audiobook (ACX)'] as $name) {
    contract_check(in_array($name, $checkNames, true), "compliance must check {$name}");
}

// --- QueryBook plan ---------------------------------------------------------
$qb = $kit['querybook_enhancement_plan'];
contract_check($qb['chapter_count'] === count($result['book']['chapters']), 'QueryBook plan must cover every chapter');
contract_check($qb['question_count'] === $qb['chapter_count'] * 3, 'every chapter must get three quiz questions');
contract_check(str_contains($qb['chapters'][0]['quiz'][0], $result['book']['chapters'][0]['title']), 'quiz questions must reference the chapter');

// --- Metadata report --------------------------------------------------------
$meta = $kit['metadata_optimization_report'];
contract_check($meta['score'] >= 0 && $meta['score'] <= 100, 'metadata score must be 0-100');
contract_check(str_contains($meta['keyword_slots_used'], '7 / 7'), 'metadata report must count keyword slots');

// --- Kit completeness & determinism ----------------------------------------
foreach (['book_blueprint', 'chapter_outline', 'media_map', 'competitive_gap_report', 'best_seller_probability', 'disclaimer'] as $key) {
    contract_check(isset($kit[$key]), "production kit must include {$key}");
}
contract_check(count($kit['chapter_outline']) === count($result['book']['chapters']), 'chapter outline must cover the book');
$kit2 = $lab->productionKit($writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12]));
unset($kit['generated_at'], $kit2['generated_at']);
contract_check(json_encode($kit) === json_encode($kit2), 'the production kit must be deterministic');

// --- HTML report ------------------------------------------------------------
$kit['generated_at'] = gmdate(DATE_ATOM);
$html = $lab->exportKitHtml($kit);
contract_check(str_contains($html, 'Best-Seller Production Kit'), 'the report must be titled');
contract_check(str_contains($html, 'Universal Nonfiction Rating'), 'the report must include the UNR');
contract_check(str_contains($html, 'KDP Compatibility'), 'the report must include the compliance table');
contract_check(!str_contains($html, '<script'), 'the report must not contain scripts');

fwrite(STDOUT, "Quality lab contract passed\n");
