<?php

declare(strict_types=1);

require_once __DIR__ . '/../IllustrationStudio.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$studio = new IllustrationStudio();

// --- The primary decision tree: information type picks the default visual ---
$branches = [
    ['Readers must compare the two options side by side: the criteria differ, the trade-offs differ, and choosing between the alternatives means weighing both.', 'table', 'table'],
    ['Sales increased steadily from Q1 to Q4, with Q3 showing the strongest acceleration in the whole year of growth.', 'line graph', 'graph'],
    ['The largest employer outnumbers the smallest by far: the biggest site holds twice the staff, and the highest earner ranks well above the lowest.', 'bar chart', 'chart'],
    ['Agriculture holds 62 percent of the total share, services a 28 percent portion, and the remaining fraction splits across the minority of small trades.', 'pie chart', 'chart'],
    ['The process runs in stages: the first step opens the sequence, the workflow hands off to the next stage, and the cycle closes the procedure.', 'illustration', 'diagram'],
    ['The framework rests on an abstract model: three layers of components whose relationships form the structure of the whole system.', 'figure', 'illustration'],
    ['People filled the streets between the buildings; a person standing at the storefront watched faces pass the houses in the town.', 'photo', 'ai-image'],
];
foreach ($branches as [$text, $expectedVisual, $expectedKind]) {
    $choice = $studio->selectVisual($text);
    contract_check($choice['visual'] === $expectedVisual, "'{$expectedVisual}' branch must win, got '{$choice['visual']}'");
    contract_check($choice['kind'] === $expectedKind, "'{$expectedVisual}' must map to kind '{$expectedKind}', got '{$choice['kind']}'");
    contract_check(in_array($choice['kind'], IllustrationStudio::KINDS, true), 'every decision must map onto a renderable kind');
}

// --- Signal scores stay in the 0–3 scoring model -----------------------------
$signals = $studio->scoreVisualSignals('Compare, compare, compare, compare: options, options, options, versus, versus, versus.');
foreach ($signals as $name => $score) {
    contract_check($score >= 0 && $score <= 3, "signal {$name} must stay within 0–3, got {$score}");
}
contract_check($signals['comparability'] === 3, 'heavy comparison language must saturate at 3');
contract_check($studio->scoreVisualSignals('A quiet paragraph about nothing in particular.')['comparability'] === 0, 'neutral text must score 0');

// --- Structure beats keywords: an imperative sequence is a mechanism ---------
$steps = $studio->scoreVisualSignals('Diagnose the gap, choose a fix, run a small test, and learn from the result.');
contract_check($steps['mechanism_clarity'] === 3, 'three or more process-verb clauses must read as a step sequence');
contract_check($studio->selectVisual('Diagnose the gap, choose a fix, run a small test, and learn from the result.')['visual'] === 'illustration', 'a step sequence must draw as an illustration');

// --- The narrative function breaks ties --------------------------------------
$ambiguous = 'The figures shifted and the options remained on the table for the year.';
contract_check(
    $studio->selectVisual($ambiguous, 'help the reader decide which option to choose')['visual'] === 'table',
    'a decision-making purpose must tip ambiguous text toward a table',
);
contract_check(
    $studio->selectVisual($ambiguous, 'reveal the pattern and build insight')['visual'] === 'line graph',
    'an insight-discovery purpose must tip ambiguous text toward a graph',
);

// --- Determinism --------------------------------------------------------------
$text = $branches[1][0];
contract_check(
    json_encode($studio->selectVisual($text, 'reveal the pattern')) === json_encode($studio->selectVisual($text, 'reveal the pattern')),
    'the formula must be deterministic',
);

// --- The pie renderer draws a complete, well-formed part-to-whole chart ------
$pie = $studio->renderPieChart([
    ['label' => 'Agriculture', 'value' => 62],
    ['label' => 'Services', 'value' => 28],
    ['label' => 'Trades', 'value' => 10],
], 'Sector shares');
contract_check(str_starts_with($pie, '<svg ') && str_ends_with($pie, '</svg>'), 'pie chart must be a complete SVG element');
$dom = new DOMDocument();
contract_check(@$dom->loadXML($pie) !== false, 'pie chart must be well-formed XML');
contract_check(str_contains($pie, '62%') && str_contains($pie, '28%') && str_contains($pie, '10%'), 'pie legend must name every share');
contract_check(substr_count($pie, '<path ') === 3, 'pie must draw one slice per part');

// --- The plan carries each figure's decision ---------------------------------
require_once __DIR__ . '/../AmazonBookWriter.php';
$writer = new AmazonBookWriter();
$result = $writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12]);
$decided = 0;
foreach ($result['media']['chapters'] as $chapter) {
    foreach ($chapter['items'] as $item) {
        if (isset($item['decision'])) {
            $decided++;
            contract_check(isset($item['decision']['visual'], $item['decision']['signals'], $item['decision']['reason']), 'each formula-chosen figure must carry its decision');
            contract_check($item['decision']['total'] >= 2, 'a figure only earns its place with a clear signal');
        }
    }
}
contract_check($decided > 0, 'the media plan must carry formula-chosen figures');

fwrite(STDOUT, "Visual selection contract passed\n");
