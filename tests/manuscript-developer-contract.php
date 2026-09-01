<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../BookProjectStore.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$writer = new AmazonBookWriter();
$developer = $writer->manuscriptDeveloper();
$result = $writer->writeBook("Why men don't approach women", ['author' => 'Garry S. Howard', 'style' => 'journalistic', 'length' => 40]);

// --- Development plan -------------------------------------------------------
foreach (ManuscriptDeveloper::PROVIDERS as $provider) {
    $plan = $developer->developmentPlan($result['book'], $result['kdp']['metadata'], $provider);
    contract_check($plan['provider'] === $provider && $plan['model'] !== '', "plan must carry provider and model for {$provider}");
    contract_check(count($plan['writer_jobs']) === count($result['book']['chapters']), 'one writer job per chapter');
    contract_check(count($plan['editor_jobs']) === count($result['book']['chapters']), 'one editor job per chapter');
    $first = $plan['writer_jobs'][0];
    contract_check(str_starts_with((string) $first['request']['endpoint'], 'https://'), 'jobs must call HTTPS endpoints');
    contract_check(str_contains((string) json_encode($first['request']['body']), trim((string) json_encode($first['prompt']), '"')), 'request body must carry the writer prompt');
    contract_check(!str_contains(json_encode($first['request']), 'sk-'), 'request specs must never embed a real key');
}
$plan = $developer->developmentPlan($result['book'], $result['kdp']['metadata'], 'anthropic');
contract_check($plan['model'] === 'claude-opus-5', 'anthropic jobs must default to the current Claude model');
$contract = (string) $plan['style_contract'];
foreach (['FOLLOW those directions', 'Real prose only', 'The takeaway', 'No fabricated precision'] as $rule) {
    contract_check(str_contains($contract, $rule), "style contract must carry the rule: {$rule}");
}
$job = $plan['writer_jobs'][4];
contract_check(str_contains((string) $job['prompt'], (string) $result['book']['chapters'][4]['detail']), 'writer prompts must carry the chapter\'s draft directions');
contract_check(str_contains((string) $plan['editor_jobs'][4]['prompt_template'], '{CHAPTER_TEXT}'), 'editor prompts must be templates awaiting the drafted text');

// --- Voice contract (a MUST) ------------------------------------------------
$voiced = $writer->writeBook("Why men don't approach women", [
    'author' => 'Garry S. Howard',
    'style' => 'memoir',
    'length' => 40,
    'narrative_voice' => 'first-person',
    'perspectives' => ['emotional-testimony', 'experiential', 'bogus-factor'],
    'author_voice' => 'a retired engineer in his sixties, plain-spoken and wry',
]);
contract_check(($voiced['book']['voice']['narrative'] ?? '') === 'first-person', 'the narrative voice must travel with the book');
contract_check($voiced['book']['voice']['perspectives'] === ['emotional-testimony', 'experiential'], 'unknown perspective factors must be dropped');
$voicedContract = (string) $developer->developmentPlan($voiced['book'], $voiced['kdp']['metadata'], 'anthropic')['style_contract'];
contract_check(str_contains($voicedContract, 'VOICE CONTRACT (a MUST'), 'the style contract must mark the voice as a hard requirement');
contract_check(str_contains($voicedContract, 'speaks as "I"'), 'the contract must spell out the narrative person');
contract_check(str_contains($voicedContract, 'Emotional testimony') && str_contains($voicedContract, 'lived experience carries the argument'), 'chosen perspective factors must appear in the contract');
contract_check(str_contains($voicedContract, 'retired engineer in his sixties'), 'the author\'s own voice description must appear in the contract');
contract_check(str_contains((string) $developer->developmentPlan($voiced['book'], $voiced['kdp']['metadata'], 'anthropic')['editor_jobs'][0]['prompt_template'], 'VOICE CONTRACT'), 'the editor pass must police voice drift');
$defaultContract = (string) $plan['style_contract'];
contract_check(str_contains($defaultContract, 'Third person'), 'books default to third person');

// --- Response extraction ----------------------------------------------------
contract_check($developer->extractText('anthropic', ['content' => [['type' => 'text', 'text' => 'Chapter 1: A']]]) === 'Chapter 1: A', 'anthropic responses must parse');
contract_check($developer->extractText('google', ['candidates' => [['content' => ['parts' => [['text' => 'Chapter 1: B']]]]]]) === 'Chapter 1: B', 'google responses must parse');
contract_check($developer->extractText('openai', ['choices' => [['message' => ['content' => 'Chapter 1: C']]]]) === 'Chapter 1: C', 'openai responses must parse');

// --- Developed chapters replace the draft directions ------------------------
$texts = [];
foreach ($result['book']['chapters'] as $chapter) {
    $n = (int) $chapter['number'];
    $texts[$n] = "Chapter {$n}: {$chapter['title']}\n\nA short developed opening paragraph about the subject itself.\n\nA second section\n\nMore developed prose for the record.\n\nThe takeaway\n\nOne closing thought.";
}
$developed = $developer->applyDevelopedChapters($result['book'], $texts);
contract_check($developed['chapters'][0]['content'] === $texts[1], 'developed text must replace the engine draft');
contract_check($developed['chapters'][0]['blocks'][0]['kind'] === 'heading', 'developed chapters must project into editor blocks');
contract_check((int) $developed['table_of_contents'][0]['page_number'] === 3, 'contents page numbers must recompute');
contract_check((int) $developed['total_word_count'] === array_sum(array_column($developed['chapters'], 'word_count')), 'word totals must recompute');

$viaOptions = $writer->writeBook("Why men don't approach women", ['length' => 40, 'developed_chapters' => $texts]);
contract_check($viaOptions['book']['chapters'][2]['content'] === $texts[3], 'writeBook must accept developed chapters directly');

// --- Project records --------------------------------------------------------
$dir = sys_get_temp_dir() . '/book-projects-test-' . getmypid();
$store = new BookProjectStore($dir);
$id = $store->save("Why men don't approach women", ['style' => 'journalistic'], $result);
contract_check($store->list()[0]['id'] === $id, 'saved projects must be listed');
$record = $store->load($id);
contract_check($record !== null && count($record['chapters']) === count($result['book']['chapters']), 'the record must keep every chapter');
contract_check($record['table_of_contents'] === array_values((array) $result['book']['table_of_contents']), 'the record must keep the table of contents');
contract_check(($record['chapters'][0]['content'] ?? '') !== '', 'the record must keep the manuscript text');
contract_check($store->load('../evil') === null, 'record ids must be sanitized');
array_map('unlink', glob($dir . '/*.json') ?: []);
@rmdir($dir);

fwrite(STDOUT, "Manuscript developer contract passed\n");
