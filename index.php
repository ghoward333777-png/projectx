<?php

declare(strict_types=1);

require_once __DIR__ . '/BookIntelligenceEngine.php';

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
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #11141c; color: #eef0f6; }
        body { margin: 0; background: radial-gradient(circle at top right, #2a2048, #11141c 42%); min-height: 100vh; }
        main { max-width: 1000px; margin: 0 auto; padding: 48px 24px 80px; }
        header { border-bottom: 1px solid #36384a; padding-bottom: 32px; margin-bottom: 32px; }
        .eyebrow { color: #b49cff; font-size: 12px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(36px, 8vw, 72px); line-height: .98; max-width: 680px; margin: 14px 0; letter-spacing: -.06em; }
        p { color: #aeb2c2; line-height: 1.6; }
        form, section { background: #1a1d28; border: 1px solid #343747; border-radius: 20px; padding: 24px; margin-top: 18px; }
        label { display: block; color: #dfe2eb; font-size: 13px; font-weight: 700; margin-bottom: 8px; }
        input { box-sizing: border-box; width: 100%; background: #10121a; border: 1px solid #4a4d61; border-radius: 10px; color: #fff; padding: 13px 14px; font: inherit; margin-bottom: 16px; }
        button { border: 0; border-radius: 999px; background: #b49cff; color: #171225; padding: 12px 18px; font: inherit; font-weight: 800; cursor: pointer; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
        .metric { background: #222534; border-radius: 14px; padding: 18px; }
        .metric strong { display: block; font-size: 32px; color: #fff; }
        .metric span { color: #b2b5c3; font-size: 13px; }
        .score { color: #b49cff; font-size: 64px; font-weight: 800; letter-spacing: -.07em; }
        ul { color: #c8cad5; line-height: 1.8; padding-left: 20px; }
        .error { color: #ff9cba; background: #3c1f32; border: 1px solid #7a3755; padding: 14px; border-radius: 10px; }
        code { color: #d5caff; }
    </style>
</head>
<body>
<main>
    <header>
        <div class="eyebrow">Book Intelligence Studio · PHP reference app</div>
        <h1>Turn a topic into a book strategy.</h1>
        <p>Run the five-engine analysis locally, inspect the scoring breakdown, and request the complete kit as JSON at <code>?format=json</code>.</p>
        <p><a href="user-guide.php">New here? Read the friendly user guide</a> · <a href="download-app.php">Download the app for your own website (.zip)</a></p>
    </header>

    <form method="post">
        <label for="topic">Book topic</label>
        <input id="topic" name="topic" value="<?= htmlspecialchars($topic, ENT_QUOTES, 'UTF-8') ?>" required>
        <label for="reader">Optional reader description</label>
        <input id="reader" name="reader" value="<?= htmlspecialchars($reader, ENT_QUOTES, 'UTF-8') ?>" placeholder="e.g. curious practitioners who need a practical framework">
        <button type="submit">Generate intelligence kit</button>
    </form>

    <?php if ($error !== null): ?>
        <div class="error"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></div>
    <?php elseif ($kit !== null): ?>
        <section>
            <div class="eyebrow">Best-seller probability</div>
            <div class="score"><?= $score ?>%</div>
            <p><?= htmlspecialchars($kit['meta']['disclaimer'], ENT_QUOTES, 'UTF-8') ?></p>
            <div class="grid">
                <?php foreach ($kit['probability']['components'] as $component): ?>
                    <div class="metric">
                        <strong><?= (int) $component['score']['value'] ?></strong>
                        <span><?= htmlspecialchars($component['label'], ENT_QUOTES, 'UTF-8') ?></span>
                    </div>
                <?php endforeach; ?>
            </div>
        </section>
        <section>
            <div class="eyebrow">Topic demand</div>
            <h2><?= htmlspecialchars($kit['kit']['title'], ENT_QUOTES, 'UTF-8') ?></h2>
            <p><?= htmlspecialchars($kit['topic_analysis']['audience_size_estimate']['range'], ENT_QUOTES, 'UTF-8') ?> · <?= htmlspecialchars($kit['topic_analysis']['trend_status'], ENT_QUOTES, 'UTF-8') ?></p>
            <ul>
                <?php foreach ($kit['topic_analysis']['best_angles'] as $angle): ?>
                    <li><strong><?= htmlspecialchars($angle['title'], ENT_QUOTES, 'UTF-8') ?>:</strong> <?= htmlspecialchars($angle['description'], ENT_QUOTES, 'UTF-8') ?></li>
                <?php endforeach; ?>
            </ul>
        </section>
        <section>
            <div class="eyebrow">Kit deliverables</div>
            <ul>
                <?php foreach ($kit['kit']['deliverables'] as $deliverable): ?>
                    <li><?= htmlspecialchars($deliverable['label'], ENT_QUOTES, 'UTF-8') ?> — <?= htmlspecialchars($deliverable['status'], ENT_QUOTES, 'UTF-8') ?></li>
                <?php endforeach; ?>
            </ul>
            <p><strong>Next move:</strong> <?= htmlspecialchars($kit['kit']['next_move'], ENT_QUOTES, 'UTF-8') ?></p>
        </section>
        <section>
            <div class="eyebrow">Suggested table of contents</div>
            <ul>
                <?php foreach ($kit['blueprint']['chapters'] as $chapter): ?>
                    <li><strong><?= (int) $chapter['number'] ?>. <?= htmlspecialchars($chapter['title'], ENT_QUOTES, 'UTF-8') ?></strong> — <?= htmlspecialchars($chapter['purpose'], ENT_QUOTES, 'UTF-8') ?></li>
                <?php endforeach; ?>
            </ul>
            <p>JSON endpoint: <code>?format=json&amp;part=toc</code></p>
            <p>Book generator page: <a href="generate-book.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>">generate-book.php</a></p>
            <p>Amazon publishing package: <a href="amazon-book-writer.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>">amazon-book-writer.php</a></p>
        </section>
    <?php endif; ?>
</main>
</body>
</html>