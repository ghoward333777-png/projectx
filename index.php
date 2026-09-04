<?php

declare(strict_types=1);

require_once __DIR__ . '/BookIntelligenceEngine.php';
require_once __DIR__ . '/StudioTheme.php';

session_start();

$engine = new BookIntelligenceEngine();
$topic = trim((string) ($_POST['topic'] ?? $_SESSION['book_topic'] ?? 'AI ethics'));
$reader = trim((string) ($_POST['reader'] ?? $_SESSION['book_reader'] ?? ''));
$error = null;
$kit = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        $kit = $engine->buildKit($topic, ['reader' => $reader]);
        $_SESSION['book_topic'] = $topic;
        $_SESSION['book_reader'] = $reader;
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
} else {
    $kit = $engine->buildKit($topic, ['reader' => $reader]);
}

if (isset($_GET['format'], $_GET['part']) && $_GET['format'] === 'json' && $_GET['part'] === 'toc') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'topic' => $topic,
        'table_of_contents' => $engine->suggestTableOfContents($topic, $reader),
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

if (isset($_GET['format'], $_GET['part']) && $_GET['format'] === 'json' && $_GET['part'] === 'jobs') {
    header('Content-Type: application/json; charset=utf-8');
    $jobs = $engine->teenJobsCatalog();
    echo json_encode([
        'count' => count($jobs),
        'jobs' => $jobs,
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

if (isset($_GET['format'], $_GET['part']) && $_GET['format'] === 'json' && $_GET['part'] === 'book' && $kit !== null) {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'topic' => $topic,
        'book' => $engine->generateBookFromTableOfContents(
            $topic,
            $kit['blueprint']['chapters'],
            trim((string) ($_GET['style'] ?? 'conversational')),
            trim((string) ($_GET['length'] ?? 'standard')),
            $reader,
            (string) ($kit['blueprint']['positioning']['core_promise'] ?? ''),
            [
                'font_family' => (string) ($_GET['font_family'] ?? 'Times New Roman'),
                'background' => (string) ($_GET['background'] ?? 'paper'),
                'margin' => (string) ($_GET['margin'] ?? 'standard'),
                'border_style' => (string) ($_GET['border_style'] ?? 'solid'),
                'border_color' => (string) ($_GET['border_color'] ?? '#d8d0c2'),
                'page_number_position' => (string) ($_GET['page_number_position'] ?? 'bottom-right'),
            ],
        ),
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

if (isset($_GET['format']) && $_GET['format'] === 'json' && $kit !== null) {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($kit, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

$score = $kit['probability']['score']['value'] ?? 0;
?>
<?php $h = static fn (string $v): string => htmlspecialchars($v, ENT_QUOTES, 'UTF-8'); ?>
<!doctype html>
<html lang="en">
<head>
    <?php StudioTheme::head('Book strategy workspace'); ?>
</head>
<body>
<?php StudioTheme::open([
    'active' => 'topic',
    'current' => 'Strategy kit',
    'brief' => $topic,
    'progress_label' => 'Strategy kit ready',
    'progress_value' => $kit !== null ? '100% mapped' : 'Awaiting topic',
    'progress_percent' => $kit !== null ? 100 : 10,
]); ?>

    <div class="page-intro" id="topic">
        <div>
            <span class="section-label coral">THE STUDIO · FIVE ENGINES</span>
            <h1>Turn a topic into a book strategy.</h1>
            <p>Run the five-engine analysis locally, inspect the scoring breakdown, and carry the kit straight into the book generator. The complete kit is also available as JSON at <code>?format=json</code>.</p>
        </div>
        <div class="intro-action">
            <a class="primary-button" href="generate-book.php"><?= StudioTheme::icon('pen', 14) ?> Open the book generator</a>
            <a class="outline-button" href="download-app.php"><?= StudioTheme::icon('download', 14) ?> Download the app (.zip)</a>
        </div>
    </div>

    <form method="post" class="panel">
        <span class="section-label coral">STEP 01 · TOPIC</span>
        <h2>Find the signal</h2>
        <div class="grid" style="margin-top: 16px;">
            <div>
                <label for="topic-input">Book topic</label>
                <input id="topic-input" name="topic" value="<?= $h($topic) ?>" required>
            </div>
            <div>
                <label for="reader">Optional reader description</label>
                <input id="reader" name="reader" value="<?= $h($reader) ?>" placeholder="e.g. curious practitioners who need a practical framework">
            </div>
        </div>
        <button type="submit"><?= StudioTheme::icon('target', 14) ?> Generate intelligence kit</button>
    </form>

    <?php if ($error !== null): ?>
        <div class="error"><?= $h($error) ?></div>
    <?php elseif ($kit !== null): ?>
        <section id="probability">
            <div class="eyebrow">Step 05 · Probability — make the bet</div>
            <div class="score"><?= (int) $score ?>%</div>
            <p><?= $h($kit['meta']['disclaimer']) ?></p>
            <div class="grid">
                <?php foreach ($kit['probability']['components'] as $component): ?>
                    <div class="metric">
                        <strong><?= (int) $component['score']['value'] ?></strong>
                        <span><?= $h($component['label']) ?></span>
                    </div>
                <?php endforeach; ?>
            </div>
        </section>

        <section id="demand">
            <div class="eyebrow">Step 01 · Topic demand</div>
            <h2><?= $h($kit['kit']['title']) ?></h2>
            <p><?= $h($kit['topic_analysis']['audience_size_estimate']['range']) ?> · <?= $h($kit['topic_analysis']['trend_status']) ?></p>
            <ul>
                <?php foreach ($kit['topic_analysis']['best_angles'] as $angle): ?>
                    <li><strong><?= $h($angle['title']) ?>:</strong> <?= $h($angle['description']) ?></li>
                <?php endforeach; ?>
            </ul>
        </section>

        <section id="scan">
            <div class="eyebrow">Step 02 · Competitive scan — see the field</div>
            <h2><?= (int) $kit['competition']['rival_count'] ?> rivals mapped</h2>
            <?php foreach ($kit['competition']['rivals'] as $rival): ?>
                <div class="metric-row">
                    <div><strong><?= $h((string) $rival['title']) ?></strong><em><?= $h((string) $rival['reader_reaction']) ?> · <?= $h((string) $rival['observed_gap']) ?></em></div>
                    <div class="bar"><span style="width: <?= (int) $rival['editorial_depth']['value'] ?>%"></span></div>
                    <div class="metric-value"><?= (int) $rival['editorial_depth']['value'] ?></div>
                </div>
            <?php endforeach; ?>
        </section>

        <section id="blueprint">
            <div class="eyebrow">Step 03 · Blueprint — shape the argument</div>
            <h2>Suggested table of contents</h2>
            <div class="kit-outline">
                <?php foreach ($kit['blueprint']['chapters'] as $chapter): ?>
                    <div><span><?= str_pad((string) $chapter['number'], 2, '0', STR_PAD_LEFT) ?></span><b><?= $h($chapter['title']) ?></b><small><?= $h($chapter['purpose']) ?></small></div>
                <?php endforeach; ?>
            </div>
            <p class="note" style="margin-top: 12px;">JSON endpoint: <code>?format=json&amp;part=toc</code> · Edit and draft it in the <a href="generate-book.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>">book generator</a>, or go straight to <a href="amazon-book-writer.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>">Amazon packaging</a>.</p>
        </section>

        <section id="media">
            <div class="eyebrow">Step 04 · Media plan — build the flywheel</div>
            <h2>Recommended media mix</h2>
            <div class="grid">
                <?php foreach ($kit['media']['recommended_mix'] as $mix): ?>
                    <div class="metric"><strong><?= (int) $mix['count'] ?></strong><span><strong style="font-size:13px; font-family: var(--app-font-sans);"><?= $h((string) $mix['type']) ?></strong><br><?= $h((string) $mix['role']) ?></span></div>
                <?php endforeach; ?>
            </div>
            <ul style="margin-top: 16px;">
                <?php foreach ($kit['media']['placement_map'] as $placement): ?>
                    <li><strong><?= $h((string) $placement['chapter']) ?>:</strong> <?= $h((string) $placement['media']) ?> — <?= $h((string) $placement['reason']) ?></li>
                <?php endforeach; ?>
            </ul>
        </section>

        <section id="kit">
            <div class="eyebrow">Complete kit · Deliverables</div>
            <h2><?= $h($kit['kit']['subtitle']) ?></h2>
            <ul>
                <?php foreach ($kit['kit']['deliverables'] as $deliverable): ?>
                    <li><?= $h($deliverable['label']) ?> — <?= $h($deliverable['status']) ?></li>
                <?php endforeach; ?>
            </ul>
            <p><strong>Next move:</strong> <?= $h($kit['kit']['next_move']) ?></p>
            <div class="downloads">
                <a class="primary" href="generate-book.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>"><?= StudioTheme::icon('pen', 13) ?> Draft the manuscript</a>
                <a href="amazon-book-writer.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>"><?= StudioTheme::icon('sparkles', 13) ?> Package for Amazon KDP</a>
                <a href="book-lab.php"><?= StudioTheme::icon('flask', 13) ?> Measure it in the quality lab</a>
            </div>
        </section>
    <?php endif; ?>

<?php StudioTheme::close(); ?>
</body>
</html>
