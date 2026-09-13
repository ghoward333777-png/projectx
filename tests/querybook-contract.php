<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../QueryBook.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$writer = new AmazonBookWriter();
$result = $writer->writeBook('Leadership strategy', ['author' => 'Garry S. Howard', 'style' => 'executive', 'length' => 12]);
$book = $result['book'];
$metadata = $result['kdp']['metadata'];
$qb = new QueryBook($book, ['title' => $metadata['title'], 'subtitle' => $metadata['subtitle'], 'topic' => 'Leadership strategy']);

$firstTitle = (string) $book['chapters'][0]['title'];
$chapterCount = count($book['chapters']);

// --- Answers are linked to the target book ----------------------------------
$answer = $qb->ask('How do I build a leadership strategy?');
contract_check($answer['mode'] === 'qa', 'the default answer mode must be Q&A');
contract_check($answer['answer'] !== [] && trim(implode(' ', $answer['answer'])) !== '', 'a Q&A answer must carry prose');
contract_check($answer['sources'] !== [], 'a Q&A answer must cite its source chapters');
foreach ($answer['sources'] as $source) {
    contract_check($source['chapter'] >= 1 && $source['chapter'] <= $chapterCount, 'cited chapters must exist in the target book');
}
contract_check(in_array($answer['confidence'], ['high', 'medium', 'low'], true), 'answers must report a confidence level');

// --- Determinism: same book + same question = same answer -------------------
contract_check($qb->ask('How do I build a leadership strategy?') === $answer, 'answers must be deterministic');

// --- Conversational mode -----------------------------------------------------
$chat = $qb->ask('How do I build a leadership strategy?', ['mode' => 'conversational']);
contract_check($chat['mode'] === 'conversational', 'the conversational mode must be selectable');
contract_check($chat['follow_ups'] !== [], 'conversational answers must invite follow-ups');
contract_check($chat['answer'] !== $answer['answer'], 'conversational answers must read differently from Q&A');

// --- Research mode ------------------------------------------------------------
$research = $qb->ask('How do I build a leadership strategy?', ['mode' => 'research']);
contract_check($research['mode'] === 'research', 'the research mode must be selectable');
contract_check(count($research['answer']) >= count($research['sources']), 'research answers must brief chapter by chapter');

// --- Domain tailoring ----------------------------------------------------------
$finance = $qb->ask('How do I build a leadership strategy?', ['domain' => 'finance']);
contract_check($finance['domain'] === 'finance', 'answers must accept an industry domain');
contract_check($finance['answer'] !== $answer['answer'], 'a domain-tailored answer must differ from the general answer');
contract_check(str_contains(implode(' ', $finance['answer']), 'finance') || str_contains(implode(' ', $finance['answer']), 'Finance'), 'the tailored answer must speak to the chosen domain');
foreach (array_keys(QueryBook::DOMAINS) as $domain) {
    $tailored = $qb->ask('What should I do first?', ['domain' => $domain]);
    contract_check($tailored['domain'] === $domain, "domain {$domain} must be usable");
}

// --- Unanswerable questions fail gracefully -----------------------------------
$miss = $qb->ask('zzxqy plumbing walrus?');
contract_check($miss['confidence'] === 'low', 'an off-book question must come back low-confidence');
contract_check($miss['related_questions'] !== [], 'an off-book answer must suggest questions the book can answer');

// --- Summaries: book and chapter level -----------------------------------------
$bookSummary = $qb->summarize();
contract_check($bookSummary['scope'] === 'book', 'summarize() must default to the whole book');
contract_check(count($bookSummary['chapters']) === $chapterCount, 'the book summary must cover every chapter');
$chapterSummary = $qb->summarize(1);
contract_check($chapterSummary['scope'] === 'chapter', 'summarize(1) must scope to the chapter');
contract_check($chapterSummary['title'] === $firstTitle, 'the chapter summary must name its chapter');
contract_check($chapterSummary['summary'] !== [], 'the chapter summary must carry prose');

// --- Synopsis, abstract, analysis ------------------------------------------------
$synopsis = $qb->synopsis();
contract_check(count($synopsis) >= 2, 'the synopsis must walk the arc in more than one paragraph');
contract_check(str_contains(implode(' ', $synopsis), $firstTitle), 'the synopsis must open where the book opens');

$abstract = $qb->abstractText();
contract_check($abstract !== '' && count(preg_split('/\s+/u', $abstract)) <= 200, 'the abstract must be one compact paragraph');

$analysis = $qb->analyze();
contract_check($analysis['chapter_count'] === $chapterCount, 'the analysis must count the real chapters');
contract_check($analysis['total_words'] === (int) $book['total_word_count'], 'the analysis word count must match the book');
contract_check($analysis['key_terms'] !== [], 'the analysis must surface key terms');
$chapterAnalysis = $qb->analyze(1);
contract_check($chapterAnalysis['scope'] === 'chapter' && $chapterAnalysis['title'] === $firstTitle, 'chapter analysis must scope to the chapter');

// --- Comparisons -------------------------------------------------------------------
$comparison = $qb->compareChapters(1, 2);
contract_check(str_contains($comparison['verdict'], $firstTitle), 'chapter comparison must name the chapters');
contract_check(count($comparison['chapters']) === 2, 'chapter comparison must describe both chapters');

$docText = 'Leadership is the craft of setting direction. A leader chooses a strategy, communicates it, and holds the team to it. Strategy without execution is only a wish.';
$docReport = $qb->documentReport($docText, 'the memo');
contract_check($docReport['summary'] !== [] && $docReport['abstract'] !== '', 'document reports must carry a summary and an abstract');
$docComparison = $qb->compareWithDocument($docText, 'the memo');
contract_check($docComparison['closest_chapters'] !== [], 'a related document must map onto the book\'s chapters');

// --- Every answer mode ---------------------------------------------------------
$modeTexts = [];
foreach (array_keys(QueryBook::MODES) as $modeKey) {
    $modeAnswer = $qb->ask('How do I build a leadership strategy?', ['mode' => $modeKey]);
    contract_check($modeAnswer['mode'] === $modeKey && $modeAnswer['answer'] !== [], "mode {$modeKey} must produce an answer");
    $modeTexts[$modeKey] = implode(' ', $modeAnswer['answer']);
}
contract_check(count(array_unique($modeTexts)) === count($modeTexts), 'every answer mode must read differently');
contract_check(str_starts_with($modeTexts['executive'], 'Bottom line:'), 'the executive brief must lead with the bottom line');
contract_check(str_contains($modeTexts['tutorial'], 'Step 1'), 'the tutorial mode must answer in numbered steps');
contract_check(str_contains($modeTexts['quotes'], '” — chapter'), 'the quotes mode must attribute every quote to its chapter');
contract_check($qb->ask('How do I build a leadership strategy?', ['mode' => 'study'])['follow_ups'] !== [], 'study mode must add self-check questions');
contract_check(str_starts_with($modeTexts['argumentative'], 'The claim:'), 'argumentative mode must lead with the claim');

// --- Canon of record: D4 mode coverage (Feature Inventory v59) -------------------
foreach (QueryBook::CANONICAL_D4_MODES as $feature => [$kind, $key]) {
    $catalog = $kind === 'mode' ? QueryBook::MODES : QueryBook::FORMS;
    contract_check(isset($catalog[$key]), "canonical D4 feature '{$feature}' must map to a real {$kind}");
}
contract_check(count(QueryBook::CANONICAL_D4_MODES) === 8, 'all eight mapped D4 modes must stay mapped');

// --- The additive covenant: catalog floors never shrink --------------------------
contract_check(count(QueryBook::MODES) >= 10, 'the mode catalog must never shrink below its shipped floor');
contract_check(count(QueryBook::FORMS) >= 17, 'the form catalog must never shrink below its shipped floor');
contract_check(count(QueryBook::REGISTERS) >= 7, 'the register catalog must never shrink below its shipped floor');
contract_check(count(QueryBook::DOMAINS) >= 7, 'the domain catalog must never shrink below its shipped floor');

// --- Expressive registers: voicing only, one per response, refuse unregistered ---
$plainAnswer = $qb->ask('How do I build a leadership strategy?');
contract_check($plainAnswer['register'] === 'plain', 'the default register must be plain');
foreach (array_keys(QueryBook::REGISTERS) as $registerKey) {
    $voiced = $qb->ask('How do I build a leadership strategy?', ['register' => $registerKey]);
    contract_check($voiced['register'] === $registerKey, "register {$registerKey} must be selectable");
    contract_check($voiced['answer'][0] === $plainAnswer['answer'][0], "register {$registerKey} must not alter the evidence (voicing only)");
    contract_check($voiced['sources'] === $plainAnswer['sources'], "register {$registerKey} must not alter the sources");
}
$refused = false;
try {
    $qb->ask('How do I lead?', ['register' => 'sarcastic']);
} catch (InvalidArgumentException $exception) {
    $refused = true;
}
contract_check($refused, 'an unregistered register must be refused, never approximated');

// --- Context Lock: the determinism key --------------------------------------------
contract_check($plainAnswer['context_key'] !== '', 'every answer must carry its context key');
contract_check($qb->ask('How do I build a leadership strategy?')['context_key'] === $plainAnswer['context_key'], 'identical context must yield an identical key');
contract_check($qb->ask('How do I build a leadership strategy?', ['register' => 'formal'])['context_key'] !== $plainAnswer['context_key'], 'a changed locked dimension must change the key');

// --- Flashcards and timeline (canonical D4 forms) ---------------------------------
$cards = $qb->flashcards();
contract_check(count($cards) === $chapterCount, 'flashcards must deliver one card per chapter');
foreach ($cards as $card) {
    contract_check(str_contains($card['question'], (string) $book['chapters'][$card['chapter'] - 1]['title']), 'each card must derive from exactly its own chapter');
    contract_check($card['answer'] !== '' && $card['source'] !== '', 'each card must carry an answer and its citation');
}
$timeline = $qb->timeline();
contract_check(count($timeline['entries']) === $chapterCount, 'the timeline must cover every chapter');
contract_check($timeline['entries'][0]['starts_on_page'] === 3, 'the timeline must start where the page plan starts');
$previousStart = 0;
foreach ($timeline['entries'] as $entry) {
    contract_check($entry['starts_on_page'] > $previousStart, 'timeline entries must advance in reading order');
    $previousStart = $entry['starts_on_page'];
}

// --- max_words: the MAX_TOKENS analog -------------------------------------------
$capped = $qb->ask('How do I build a leadership strategy?', ['max_words' => 30]);
$cappedWords = count(preg_split('/\s+/u', trim(implode(' ', $capped['answer']))));
contract_check($cappedWords <= 31, 'max_words must cap the answer length');
contract_check($capped['answer'] !== [], 'a capped answer must still say something');

// --- Summary lengths -------------------------------------------------------------
$brief = $qb->summarize(null, 'brief');
$detailed = $qb->summarize(null, 'detailed');
contract_check($brief['chapters'] === [] && count($detailed['chapters']) === $chapterCount, 'summary lengths must change the depth');
contract_check($qb->summarize(1, 'brief')['summary'] !== $qb->summarize(1, 'detailed')['summary'], 'chapter summaries must honor the length');

// --- New deliverables ---------------------------------------------------------------
contract_check($qb->outline()['chapter_count'] === $chapterCount, 'the outline must cover every chapter');
$glossary = $qb->glossary(8);
contract_check(count($glossary) === 8, 'the glossary must deliver the requested number of terms');
foreach ($glossary as $entry) {
    contract_check($entry['term'] !== '' && $entry['in_the_book'] !== '', 'every glossary term must carry a definition');
}
contract_check(count($qb->faq()) >= $chapterCount, 'the FAQ must cover every chapter');
contract_check(count($qb->studyGuide()) === $chapterCount, 'the study guide must cover every chapter');
foreach ($qb->studyGuide() as $guideChapter) {
    contract_check(count($guideChapter['discussion_questions']) >= 2, 'every study-guide chapter needs discussion questions');
}
contract_check(count($qb->keyQuotes()) === $chapterCount, 'every chapter must yield a key quote');
$plan = $qb->readingPlan();
$expectedMinutes = 0;
foreach ($book['chapters'] as $chapter) {
    $expectedMinutes += max(1, (int) ceil((int) $chapter['word_count'] / 200));
}
contract_check($plan['total_minutes'] === $expectedMinutes, 'the reading plan must add up chapter by chapter');
contract_check($plan['sessions'] !== [] && $plan['session_count'] === count($plan['sessions']), 'the reading plan must schedule sessions');

// --- One dispatcher for every form of user-requested output -------------------------
$formOptions = [
    'answer' => ['question' => 'How do I build a leadership strategy?', 'mode' => 'executive', 'domain' => 'technology'],
    'compare-chapters' => ['chapter_a' => 1, 'chapter_b' => 2],
    'compare-document' => ['document' => $docText],
    'document-report' => ['document' => $docText],
];
foreach (array_keys(QueryBook::FORMS) as $form) {
    $request = $qb->request($form, $formOptions[$form] ?? []);
    contract_check($request['form'] === $form && $request['result'] !== [], "form {$form} must produce output");
    contract_check(trim($qb->renderMarkdown($request)) !== '', "form {$form} must render as Markdown");
    contract_check(trim($qb->renderPlainText($request)) !== '', "form {$form} must render as plain text");
    contract_check($qb->request($form, $formOptions[$form] ?? []) === $request, "form {$form} must be deterministic");
}
$failed = false;
try {
    $qb->request('compare-chapters');
} catch (InvalidArgumentException $exception) {
    $failed = true;
}
contract_check($failed, 'a form missing its inputs must fail with a clear message');
$failed = false;
try {
    $qb->request('interpretive-dance');
} catch (InvalidArgumentException $exception) {
    $failed = true;
}
contract_check($failed, 'an unknown form must be rejected by name');

echo "querybook-contract passed\n";
