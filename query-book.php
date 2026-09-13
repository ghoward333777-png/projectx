<?php

declare(strict_types=1);

require_once __DIR__ . '/AmazonBookWriter.php';
require_once __DIR__ . '/QueryBook.php';

session_start();

$writer = new AmazonBookWriter();

$topic = trim((string) ($_POST['topic'] ?? $_GET['topic'] ?? $_SESSION['book_topic'] ?? 'Jobs and work for teens'));
$reader = trim((string) ($_POST['reader'] ?? $_GET['reader'] ?? $_SESSION['book_reader'] ?? 'teens exploring a first job while balancing school, safety, and real life'));
$author = trim((string) ($_POST['author'] ?? $_GET['author'] ?? $_SESSION['book_author'] ?? ''));
$style = trim((string) ($_POST['style'] ?? $_GET['style'] ?? 'conversational'));
$length = trim((string) ($_POST['length'] ?? $_GET['length'] ?? 'standard'));

$question = trim((string) ($_POST['question'] ?? $_GET['question'] ?? ''));
$mode = trim((string) ($_POST['mode'] ?? $_GET['mode'] ?? 'qa'));
$domain = trim((string) ($_POST['domain'] ?? $_GET['domain'] ?? 'general'));
$register = trim((string) ($_POST['register'] ?? $_GET['register'] ?? 'plain'));
$register = isset(QueryBook::REGISTERS[$register]) ? $register : 'plain';
$chapterScope = (int) ($_POST['chapter'] ?? $_GET['chapter'] ?? 0);
$compareA = (int) ($_POST['compare_a'] ?? $_GET['compare_a'] ?? 0);
$compareB = (int) ($_POST['compare_b'] ?? $_GET['compare_b'] ?? 0);
$document = trim((string) ($_POST['document'] ?? $_GET['document'] ?? ''));
$deliver = trim((string) ($_POST['deliver'] ?? $_GET['deliver'] ?? ''));
$download = trim((string) ($_GET['download'] ?? ''));

$error = null;
$queryBook = null;
$book = null;
$answer = null;
$chapterSummary = null;
$chapterAnalysis = null;
$comparison = null;
$documentComparison = null;
$deliverable = null;
$deliverError = null;
$wantsResult = $_SERVER['REQUEST_METHOD'] === 'POST' || isset($_GET['format']) || $question !== '' || $deliver !== '';

if ($wantsResult) {
    try {
        $result = $writer->writeBook($topic, ['reader' => $reader, 'author' => $author, 'style' => $style, 'length' => $length]);
        $book = $result['book'];
        $metadata = $result['kdp']['metadata'];
        $queryBook = new QueryBook($book, [
            'title' => (string) $metadata['title'],
            'subtitle' => (string) $metadata['subtitle'],
            'topic' => $topic,
        ]);
        $_SESSION['book_topic'] = $topic;
        $_SESSION['book_reader'] = $reader;
        $_SESSION['book_author'] = $author;

        if ($question !== '') {
            $answer = $queryBook->ask($question, array_filter([
                'mode' => $mode,
                'domain' => $domain,
                'register' => $register,
                'chapter' => $chapterScope > 0 ? $chapterScope : null,
            ]));
        }
        if ($chapterScope > 0 && $chapterScope <= count($book['chapters'])) {
            $chapterSummary = $queryBook->summarize($chapterScope);
            $chapterAnalysis = $queryBook->analyze($chapterScope);
        }
        if ($compareA > 0 && $compareB > 0 && $compareA !== $compareB) {
            $comparison = $queryBook->compareChapters($compareA, $compareB);
        }
        if ($document !== '') {
            $documentComparison = $queryBook->compareWithDocument($document, 'your document');
        }
        if ($deliver !== '') {
            try {
                $deliverable = $queryBook->request($deliver, [
                    'question' => $question,
                    'mode' => $mode,
                    'domain' => $domain,
                    'register' => $register,
                    'chapter' => $chapterScope > 0 ? $chapterScope : null,
                    'chapter_a' => $compareA,
                    'chapter_b' => $compareB,
                    'document' => $document,
                    'document_label' => 'your document',
                ]);
            } catch (InvalidArgumentException $formException) {
                $deliverError = $formException->getMessage();
            }
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
        $queryBook = null;
    }
}

if ($queryBook !== null && $deliverable !== null && in_array($download, ['md', 'txt', 'json'], true)) {
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic . '-' . $deliver)) . '.' . $download;
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    if ($download === 'json') {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($deliverable, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    } elseif ($download === 'md') {
        header('Content-Type: text/markdown; charset=utf-8');
        echo $queryBook->renderMarkdown($deliverable);
    } else {
        header('Content-Type: text/plain; charset=utf-8');
        echo $queryBook->renderPlainText($deliverable);
    }
    exit;
}

if ($queryBook !== null && ($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(array_filter([
        'answer' => $answer,
        'book_summary' => $queryBook->summarize(),
        'synopsis' => $queryBook->synopsis(),
        'abstract' => $queryBook->abstractText(),
        'analysis' => $queryBook->analyze(),
        'chapter_summary' => $chapterSummary,
        'chapter_analysis' => $chapterAnalysis,
        'chapter_comparison' => $comparison,
        'document_comparison' => $documentComparison,
        'deliverable' => $deliverable,
    ]), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$styles = $writer->engine()->writingStyles();
$e = static fn (string $v): string => htmlspecialchars($v, ENT_QUOTES, 'UTF-8');

/** Render any deliverable payload as HTML, whatever its shape. */
function qb_render(mixed $value): string
{
    $escape = static fn (string $v): string => htmlspecialchars($v, ENT_QUOTES, 'UTF-8');
    if (is_scalar($value) || $value === null) {
        return '<p>' . $escape((string) $value) . '</p>';
    }
    $value = (array) $value;
    if ($value === []) {
        return '';
    }
    if (array_is_list($value)) {
        $allScalar = array_reduce($value, static fn (bool $carry, mixed $item): bool => $carry && (is_scalar($item) || $item === null), true);
        if ($allScalar) {
            return '<ul>' . implode('', array_map(static fn (mixed $item): string => '<li>' . $escape((string) $item) . '</li>', $value)) . '</ul>';
        }
        return implode('', array_map(static fn (mixed $item): string => '<div class="item">' . qb_render($item) . '</div>', $value));
    }
    $out = '<dl>';
    foreach ($value as $key => $item) {
        $label = ucfirst(str_replace(['_', '-'], ' ', (string) $key));
        $out .= '<dt>' . $escape($label) . '</dt><dd>' . (is_scalar($item) || $item === null ? $escape((string) $item) : qb_render($item)) . '</dd>';
    }
    return $out . '</dl>';
}
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>QueryBook · Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #11141c; color: #eef0f6; }
        body { margin: 0; background: radial-gradient(circle at top right, #2b1c3f, #11141c 45%); min-height: 100vh; }
        main { max-width: 1100px; margin: 0 auto; padding: 42px 24px 80px; }
        header { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; border-bottom: 1px solid #36384a; padding-bottom: 30px; }
        .eyebrow { color: #c9a3f5; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(36px, 6vw, 62px); line-height: .98; max-width: 720px; margin: 14px 0; letter-spacing: -.06em; }
        h2 { letter-spacing: -.02em; }
        p { color: #aeb2c2; line-height: 1.6; }
        a { color: #d9beff; }
        form, section { background: #1a1d28; border: 1px solid #343747; border-radius: 18px; padding: 24px; margin-top: 18px; }
        label { display: block; color: #dfe2eb; font-size: 12px; font-weight: 700; margin-bottom: 8px; }
        input, select, textarea { box-sizing: border-box; width: 100%; background: #10121a; border: 1px solid #4a4d61; border-radius: 9px; color: #fff; padding: 12px 13px; font: inherit; margin-bottom: 15px; }
        textarea { min-height: 110px; resize: vertical; }
        button { border: 0; border-radius: 999px; background: #c9a3f5; color: #1d0b33; padding: 12px 18px; font: inherit; font-weight: 800; cursor: pointer; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
        .answer p { color: #e6e2f2; font-size: 15px; }
        .pill { display: inline-block; border-radius: 999px; background: #2b2340; border: 1px solid #4d3a6e; color: #d9beff; padding: 4px 13px; font-size: 12px; font-weight: 700; margin-right: 8px; }
        .source { display: grid; grid-template-columns: 90px 1fr 60px; gap: 12px; border-top: 1px solid #2c2f40; padding: 9px 0; font-size: 13px; }
        .source:first-of-type { border-top: 0; }
        .source b { color: #c9a3f5; }
        ul { color: #aeb2c2; line-height: 1.7; }
        details { border: 1px solid #343747; border-radius: 10px; margin-top: 10px; background: #1e2130; }
        summary { cursor: pointer; padding: 12px 15px; font-weight: 700; }
        details div { padding: 0 15px 13px; color: #aeb2c2; font-size: 13px; line-height: 1.6; }
        .error { color: #ff9cba; background: #3c1f32; border: 1px solid #7a3755; padding: 14px; border-radius: 10px; margin-top: 18px; }
        .item { border-top: 1px solid #2c2f40; padding: 10px 0; }
        .item:first-child { border-top: 0; }
        dl { margin: 0; }
        dt { color: #c9a3f5; font-size: 11px; letter-spacing: .1em; text-transform: uppercase; font-weight: 700; margin-top: 10px; }
        dd { margin: 4px 0 0; color: #cfd2e0; font-size: 14px; line-height: 1.6; }
        .downloads { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; }
        .downloads a { display: inline-block; border-radius: 999px; background: #292d3d; color: #e9e6f4; padding: 10px 16px; font-weight: 800; text-decoration: none; font-size: 13px; }
        .note { color: #8d91a3; font-size: 12px; }
        @media (max-width: 700px) { header { display: block; } main { padding: 28px 16px 60px; } .source { grid-template-columns: 70px 1fr; } .source span:last-child { display: none; } }
    </style>
</head>
<body>
<main>
    <header>
        <div>
            <div class="eyebrow">Book Intelligence Studio · QueryBook</div>
            <h1>Ask the book. Get the answer your way.</h1>
            <p>Every answer is linked to a target book. Ask in Q&amp;A, conversational, or research mode; tailor answers to your industry; and pull book, chapter, and document summaries, analysis, synopses, abstracts, and comparisons on demand.</p>
        </div>
        <div>
            <a href="index.php">← Intelligence kit</a><br>
            <a href="book-lab.php">Book Development Lab</a><br>
            <a href="amazon-book-writer.php">Amazon Book Writer</a><br>
            <a href="user-guide.php">User guide</a>
        </div>
    </header>

    <?php if ($error !== null): ?><div class="error"><?= $e($error) ?></div><?php endif; ?>

    <form method="post">
        <h2>1 · The target book</h2>
        <div class="grid">
            <div><label for="topic">Book topic</label><input id="topic" name="topic" value="<?= $e($topic) ?>" required></div>
            <div><label for="reader">Who is it for?</label><input id="reader" name="reader" value="<?= $e($reader) ?>"></div>
            <div><label for="author">Author</label><input id="author" name="author" value="<?= $e($author) ?>"></div>
            <div>
                <label for="style">Writing style</label>
                <select id="style" name="style">
                    <?php foreach ($styles as $styleOption): ?>
                        <option value="<?= $e((string) $styleOption['id']) ?>" <?= $styleOption['id'] === $style ? 'selected' : '' ?>><?= $e((string) $styleOption['label']) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="length">Length</label>
                <select id="length" name="length">
                    <?php foreach (['short' => 'Short (~120 pages)', 'standard' => 'Standard (~240 pages)', 'expanded' => 'Expanded (~500 pages)'] as $value => $label): ?>
                        <option value="<?= $value ?>" <?= $value === $length ? 'selected' : '' ?>><?= $label ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
        </div>

        <h2>2 · Your question</h2>
        <div class="grid">
            <div><label for="question">Ask anything about the book</label><input id="question" name="question" value="<?= $e($question) ?>" placeholder="e.g. What should I do in the first week?"></div>
            <div>
                <label for="mode">Answer mode</label>
                <select id="mode" name="mode">
                    <?php foreach (QueryBook::MODES as $modeKey => $modeLabel): ?>
                        <option value="<?= $e($modeKey) ?>" <?= $modeKey === $mode ? 'selected' : '' ?>><?= $e($modeLabel) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="domain">Tailor the answer to an industry / domain</label>
                <select id="domain" name="domain">
                    <?php foreach (QueryBook::DOMAINS as $domainKey => $profile): ?>
                        <option value="<?= $e($domainKey) ?>" <?= $domainKey === $domain ? 'selected' : '' ?>><?= $e($profile['label']) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="register">Expressive register (voicing only)</label>
                <select id="register" name="register">
                    <?php foreach (QueryBook::REGISTERS as $registerKey => $registerProfile): ?>
                        <option value="<?= $e($registerKey) ?>" <?= $registerKey === $register ? 'selected' : '' ?>><?= $e($registerProfile['label']) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label for="chapter">Focus on one chapter (optional number)</label><input id="chapter" name="chapter" type="number" min="0" value="<?= $chapterScope > 0 ? $chapterScope : '' ?>"></div>
        </div>

        <h2>3 · Comparisons (optional)</h2>
        <div class="grid">
            <div><label for="compare_a">Compare chapter …</label><input id="compare_a" name="compare_a" type="number" min="0" value="<?= $compareA > 0 ? $compareA : '' ?>"></div>
            <div><label for="compare_b">… with chapter</label><input id="compare_b" name="compare_b" type="number" min="0" value="<?= $compareB > 0 ? $compareB : '' ?>"></div>
        </div>
        <label for="document">Or paste an outside document to summarize and compare against the book</label>
        <textarea id="document" name="document" placeholder="Paste a memo, article, or draft here…"><?= $e($document) ?></textarea>

        <h2>4 · Documents on demand (optional)</h2>
        <label for="deliver">Request any output form — rendered on this page and downloadable as Markdown, plain text, or JSON</label>
        <select id="deliver" name="deliver">
            <option value="">— just the standard set (summary · synopsis · abstract · analysis) —</option>
            <?php foreach (QueryBook::FORMS as $formKey => $formLabel): ?>
                <option value="<?= $e($formKey) ?>" <?= $formKey === $deliver ? 'selected' : '' ?>><?= $e($formLabel) ?></option>
            <?php endforeach; ?>
        </select>
        <button type="submit">Query the book</button>
        <p class="note">Deterministic and local: the same book and the same question always produce the same answer. No accounts, no API keys.</p>
    </form>

    <?php if ($answer !== null): ?>
        <section class="answer">
            <div class="eyebrow">The answer · <?= $e((string) $answer['mode_label']) ?></div>
            <p>
                <span class="pill">Domain: <?= $e((string) $answer['domain_label']) ?></span>
                <span class="pill">Register: <?= $e((string) ($answer['register'] ?? 'plain')) ?></span>
                <span class="pill">Scope: <?= $e((string) $answer['scope']) ?></span>
                <span class="pill">Confidence: <?= $e((string) $answer['confidence']) ?></span>
                <span class="pill">Context key: <?= $e((string) ($answer['context_key'] ?? '')) ?></span>
            </p>
            <?php foreach ((array) $answer['answer'] as $paragraph): ?><p><?= $e((string) $paragraph) ?></p><?php endforeach; ?>
            <?php if ((array) $answer['sources'] !== []): ?>
                <h2>Sources in the book</h2>
                <?php foreach ((array) $answer['sources'] as $source): ?>
                    <div class="source"><b>Chapter <?= (int) $source['chapter'] ?></b><span><?= $e((string) $source['title']) ?></span><span><?= (int) $source['relevance'] ?>%</span></div>
                <?php endforeach; ?>
            <?php endif; ?>
            <?php if ((array) $answer['follow_ups'] !== []): ?>
                <h2>Keep the conversation going</h2>
                <ul><?php foreach ((array) $answer['follow_ups'] as $followUp): ?><li><?= $e((string) $followUp) ?></li><?php endforeach; ?></ul>
            <?php endif; ?>
            <?php if ((array) $answer['related_questions'] !== []): ?>
                <p class="note">Questions this book answers well: <?= $e(implode(' · ', (array) $answer['related_questions'])) ?></p>
            <?php endif; ?>
        </section>
    <?php endif; ?>

    <?php if ($deliverError !== null): ?><div class="error"><?= $e($deliverError) ?></div><?php endif; ?>

    <?php if ($deliverable !== null && $queryBook !== null): ?>
        <?php $deliverQuery = http_build_query(array_filter([
            'topic' => $topic, 'reader' => $reader, 'author' => $author, 'style' => $style, 'length' => $length,
            'question' => $question, 'mode' => $mode, 'domain' => $domain, 'register' => $register,
            'chapter' => $chapterScope > 0 ? (string) $chapterScope : '',
            'compare_a' => $compareA > 0 ? (string) $compareA : '', 'compare_b' => $compareB > 0 ? (string) $compareB : '',
            'document' => $document, 'deliver' => $deliver,
        ], static fn (string $v): bool => $v !== '')); ?>
        <section>
            <div class="eyebrow">Requested deliverable · <?= $e((string) $deliverable['label']) ?></div>
            <p class="note">Target book: <?= $e((string) $deliverable['book']) ?></p>
            <?= qb_render($deliverable['result']) ?>
            <div class="downloads">
                <a href="query-book.php?<?= $e($deliverQuery) ?>&amp;download=md">Download (.md)</a>
                <a href="query-book.php?<?= $e($deliverQuery) ?>&amp;download=txt">Download (.txt)</a>
                <a href="query-book.php?<?= $e($deliverQuery) ?>&amp;download=json">Download (.json)</a>
            </div>
        </section>
    <?php endif; ?>

    <?php if ($queryBook !== null): ?>
        <?php $bookSummary = $queryBook->summarize(); $analysis = $queryBook->analyze(); ?>
        <section>
            <div class="eyebrow">Book summary</div>
            <?php foreach ((array) $bookSummary['summary'] as $line): ?><p><?= $e((string) $line) ?></p><?php endforeach; ?>
            <details>
                <summary>Chapter-by-chapter summary (<?= count((array) $bookSummary['chapters']) ?> chapters)</summary>
                <div><?php foreach ((array) $bookSummary['chapters'] as $line): ?><p><?= $e((string) $line) ?></p><?php endforeach; ?></div>
            </details>
            <details>
                <summary>Synopsis — the narrative arc</summary>
                <div><?php foreach ($queryBook->synopsis() as $paragraph): ?><p><?= $e($paragraph) ?></p><?php endforeach; ?></div>
            </details>
            <details>
                <summary>Abstract — one paragraph</summary>
                <div><p><?= $e($queryBook->abstractText()) ?></p></div>
            </details>
            <details>
                <summary>Analysis — structure and emphasis</summary>
                <div>
                    <p><?= (int) $analysis['chapter_count'] ?> chapters · <?= (int) $analysis['total_words'] ?> words · average <?= (int) $analysis['average_chapter_words'] ?> words per chapter.</p>
                    <p>Longest: chapter <?= (int) $analysis['longest_chapter']['chapter'] ?>, “<?= $e((string) $analysis['longest_chapter']['title']) ?>”. Shortest: chapter <?= (int) $analysis['shortest_chapter']['chapter'] ?>, “<?= $e((string) $analysis['shortest_chapter']['title']) ?>”.</p>
                    <p><?= $e((string) $analysis['takeaway_coverage']) ?>. <?= $e((string) $analysis['arc']) ?></p>
                    <p>Key terms: <?= $e(implode(', ', (array) $analysis['key_terms'])) ?>.</p>
                </div>
            </details>
            <p class="note">Full JSON of every deliverable: <a href="query-book.php?<?= $e(http_build_query(array_filter(['topic' => $topic, 'reader' => $reader, 'author' => $author, 'style' => $style, 'length' => $length, 'question' => $question, 'mode' => $mode, 'domain' => $domain, 'format' => 'json']))) ?>">query-book.php?format=json</a></p>
        </section>
    <?php endif; ?>

    <?php if ($chapterSummary !== null && $chapterAnalysis !== null): ?>
        <section>
            <div class="eyebrow">Chapter <?= (int) $chapterSummary['chapter'] ?> · <?= $e((string) $chapterSummary['title']) ?></div>
            <?php foreach ((array) $chapterSummary['summary'] as $line): ?><p><?= $e((string) $line) ?></p><?php endforeach; ?>
            <p class="note"><?= (int) $chapterAnalysis['sentence_count'] ?> sentences · about <?= (int) $chapterAnalysis['average_sentence_words'] ?> words per sentence · takeaway closer: <?= $chapterAnalysis['has_takeaway'] ? 'yes' : 'no' ?> · key terms: <?= $e(implode(', ', (array) $chapterAnalysis['key_terms'])) ?></p>
        </section>
    <?php endif; ?>

    <?php if ($comparison !== null): ?>
        <section>
            <div class="eyebrow">Chapter comparison</div>
            <?php foreach ((array) $comparison['chapters'] as $side): ?>
                <p><b>Chapter <?= (int) $side['chapter'] ?> — <?= $e((string) $side['title']) ?></b> (<?= (int) $side['words'] ?> words): <?= $e((string) $side['purpose']) ?></p>
            <?php endforeach; ?>
            <p><?= $e((string) $comparison['shared_ground']) ?></p>
            <ul><?php foreach ((array) $comparison['distinct_emphasis'] as $line): ?><li><?= $e((string) $line) ?></li><?php endforeach; ?></ul>
            <p><?= $e((string) $comparison['verdict']) ?></p>
        </section>
    <?php endif; ?>

    <?php if ($documentComparison !== null): ?>
        <section>
            <div class="eyebrow">Your document vs. the book</div>
            <p><b>Document summary:</b> <?= $e(implode(' ', (array) $documentComparison['document']['summary'])) ?></p>
            <p><b>Document abstract:</b> <?= $e((string) $documentComparison['document']['abstract']) ?></p>
            <p><?= $e((string) $documentComparison['shared_ground']) ?> <?= $e((string) $documentComparison['document_adds']) ?></p>
            <?php foreach ((array) $documentComparison['closest_chapters'] as $row): ?>
                <div class="source"><b>Chapter <?= (int) $row['chapter'] ?></b><span><?= $e((string) $row['title']) ?></span><span></span></div>
            <?php endforeach; ?>
            <p><?= $e((string) $documentComparison['verdict']) ?></p>
        </section>
    <?php endif; ?>
</main>
</body>
</html>
