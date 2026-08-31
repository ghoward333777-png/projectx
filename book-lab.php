<?php

declare(strict_types=1);

require_once __DIR__ . '/AmazonBookWriter.php';
require_once __DIR__ . '/QualityLab.php';

session_start();

$writer = new AmazonBookWriter();
$lab = new QualityLab();

$topic = trim((string) ($_POST['topic'] ?? $_GET['topic'] ?? $_SESSION['book_topic'] ?? 'Jobs and work for teens'));
$reader = trim((string) ($_POST['reader'] ?? $_GET['reader'] ?? $_SESSION['book_reader'] ?? 'teens exploring a first job while balancing school, safety, and real life'));
$author = trim((string) ($_POST['author'] ?? $_GET['author'] ?? $_SESSION['book_author'] ?? ''));
$style = trim((string) ($_POST['style'] ?? $_GET['style'] ?? 'conversational'));
$length = trim((string) ($_POST['length'] ?? $_GET['length'] ?? 'standard'));

$error = null;
$result = null;
$kit = null;
$download = trim((string) ($_GET['download'] ?? ''));
$wantsResult = $_SERVER['REQUEST_METHOD'] === 'POST' || $download !== '' || isset($_GET['format']);

if ($wantsResult) {
    try {
        $result = $writer->writeBook($topic, ['reader' => $reader, 'author' => $author, 'style' => $style, 'length' => $length]);
        $kit = $lab->productionKit($result);
        $_SESSION['book_topic'] = $topic;
        $_SESSION['book_reader'] = $reader;
        $_SESSION['book_author'] = $author;
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

if ($kit !== null && $download === 'kit-html') {
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-production-kit.html';
    header('Content-Type: text/html; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    echo $lab->exportKitHtml($kit);
    exit;
}
if ($kit !== null && $download === 'kit-json') {
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-production-kit.json';
    header('Content-Type: application/json; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    echo json_encode($kit, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}
if ($kit !== null && ($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($kit, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$styles = $writer->engine()->writingStyles();
$downloadQuery = http_build_query(array_filter([
    'topic' => $topic, 'reader' => $reader, 'author' => $author, 'style' => $style, 'length' => $length,
], static fn (string $v): bool => $v !== ''));
$badgeColor = static fn (string $badge): string => match ($badge) {
    'Platinum' => '#c3e6f7', 'Gold' => '#ffd775', 'Silver' => '#cfd4e2', default => '#e0a97d',
};
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Book Development Lab · Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #11141c; color: #eef0f6; }
        body { margin: 0; background: radial-gradient(circle at top right, #123340, #11141c 42%); min-height: 100vh; }
        main { max-width: 1100px; margin: 0 auto; padding: 42px 24px 80px; }
        header { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; border-bottom: 1px solid #36384a; padding-bottom: 30px; }
        .eyebrow { color: #5fd0dd; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(36px, 6vw, 62px); line-height: .98; max-width: 720px; margin: 14px 0; letter-spacing: -.06em; }
        p { color: #aeb2c2; line-height: 1.6; }
        a { color: #a7e4ec; }
        form, section { background: #1a1d28; border: 1px solid #343747; border-radius: 18px; padding: 24px; margin-top: 18px; }
        label { display: block; color: #dfe2eb; font-size: 12px; font-weight: 700; margin-bottom: 8px; }
        input, select { box-sizing: border-box; width: 100%; background: #10121a; border: 1px solid #4a4d61; border-radius: 9px; color: #fff; padding: 12px 13px; font: inherit; margin-bottom: 15px; }
        button { border: 0; border-radius: 999px; background: #5fd0dd; color: #082026; padding: 12px 18px; font: inherit; font-weight: 800; cursor: pointer; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
        .hero { display: flex; gap: 26px; align-items: center; flex-wrap: wrap; }
        .hero-score { font-size: 58px; font-weight: 800; letter-spacing: -.05em; color: #5fd0dd; line-height: 1; }
        .hero-score small { display: block; font-size: 11px; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; color: #8d91a3; margin-top: 6px; }
        .badge { display: inline-block; border-radius: 999px; padding: 4px 14px; font-size: 12px; font-weight: 800; color: #10131b; }
        .metric-row { display: grid; grid-template-columns: 210px 1fr 46px; gap: 12px; align-items: center; border-top: 1px solid #2c2f40; padding: 8px 0; font-size: 13px; }
        .metric-row:first-of-type { border-top: 0; }
        .bar { height: 8px; background: #262a3a; border-radius: 99px; overflow: hidden; }
        .bar span { display: block; height: 100%; background: #5fd0dd; border-radius: 99px; }
        .metric-row em { color: #8d91a3; font-style: normal; font-size: 11px; display: block; }
        .metric-value { text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; }
        .stat { background: #222534; border-radius: 12px; padding: 14px 16px; }
        .stat strong { display: block; font-size: 24px; font-variant-numeric: tabular-nums; }
        .stat span { color: #aeb2c2; font-size: 12px; }
        .check { display: grid; grid-template-columns: 64px 160px 1fr; gap: 12px; border-top: 1px solid #2c2f40; padding: 10px 0; font-size: 13px; }
        .check:first-of-type { border-top: 0; }
        .status-pass { color: #7ee2a8; font-weight: 800; text-transform: uppercase; font-size: 11px; letter-spacing: .08em; }
        .status-warn { color: #ffb84d; font-weight: 800; text-transform: uppercase; font-size: 11px; letter-spacing: .08em; }
        .downloads { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }
        .downloads a { display: inline-block; border-radius: 999px; background: #292d3d; color: #e9e6f4; padding: 12px 18px; font-weight: 800; text-decoration: none; }
        .downloads a.primary { background: #5fd0dd; color: #082026; }
        details { border: 1px solid #343747; border-radius: 10px; margin-top: 10px; background: #1e2130; }
        summary { cursor: pointer; padding: 12px 15px; font-weight: 700; }
        details div { padding: 0 15px 13px; color: #aeb2c2; font-size: 13px; line-height: 1.6; }
        .error { color: #ff9cba; background: #3c1f32; border: 1px solid #7a3755; padding: 14px; border-radius: 10px; margin-top: 18px; }
        .note { color: #8d91a3; font-size: 12px; }
        @media (max-width: 700px) { header { display: block; } main { padding: 28px 16px 60px; } .metric-row { grid-template-columns: 1fr 60px; } .metric-row .bar { grid-column: 1 / -1; } .check { grid-template-columns: 64px 1fr; } .check span:last-child { grid-column: 1 / -1; } }
    </style>
</head>
<body>
<main>
    <header>
        <div>
            <div class="eyebrow">Book Intelligence Studio · Book Development Lab</div>
            <h1>Measure the book. Then make it better.</h1>
            <p>The quality-certification layer: 30 editorial, media, and format metrics, document complexity, KDP compatibility, metadata optimization, a QueryBook learning plan, and the complete Best-Seller Production Kit.</p>
        </div>
        <div>
            <a href="index.php">← Intelligence kit</a><br>
            <a href="amazon-book-writer.php">Amazon Book Writer</a><br>
            <a href="user-guide.php">User guide</a>
        </div>
    </header>

    <?php if ($error !== null): ?><div class="error"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></div><?php endif; ?>

    <form method="post">
        <div class="grid">
            <div><label for="topic">Book topic</label><input id="topic" name="topic" value="<?= htmlspecialchars($topic, ENT_QUOTES, 'UTF-8') ?>" required></div>
            <div><label for="reader">Reader description</label><input id="reader" name="reader" value="<?= htmlspecialchars($reader, ENT_QUOTES, 'UTF-8') ?>"></div>
            <div><label for="author">Author name</label><input id="author" name="author" value="<?= htmlspecialchars($author, ENT_QUOTES, 'UTF-8') ?>"></div>
            <div>
                <label for="style">Writing style</label>
                <select id="style" name="style"><?php foreach ($styles as $writingStyle): ?><option value="<?= htmlspecialchars($writingStyle['id'], ENT_QUOTES, 'UTF-8') ?>" <?= $style === $writingStyle['id'] ? 'selected' : '' ?>><?= htmlspecialchars($writingStyle['label'], ENT_QUOTES, 'UTF-8') ?></option><?php endforeach; ?></select>
            </div>
            <div><label for="length">Length · pages or preset</label><input id="length" name="length" value="<?= htmlspecialchars($length, ENT_QUOTES, 'UTF-8') ?>"></div>
        </div>
        <button type="submit">Run the lab</button>
    </form>

    <?php if ($kit !== null): ?>
        <?php $scores = $kit['editorial_quality_report']; $bsp = $kit['best_seller_probability']; ?>
        <section>
            <div class="eyebrow">Certification</div>
            <div class="hero">
                <div class="hero-score"><?= (int) $scores['unr']['score'] ?><small>UNR · Universal Nonfiction Rating</small></div>
                <div class="hero-score" style="color:#eef0f6;"><?= (int) ($bsp['value'] ?? 0) ?>%<small>Best-seller probability</small></div>
                <div>
                    <span class="badge" style="background: <?= $badgeColor((string) $scores['unr']['badge']) ?>;"><?= htmlspecialchars((string) $scores['unr']['badge'], ENT_QUOTES, 'UTF-8') ?> certification</span>
                    <p class="note" style="margin: 10px 0 0; max-width: 430px;"><?= htmlspecialchars((string) $scores['unr']['formula'], ENT_QUOTES, 'UTF-8') ?> · <?= (int) $scores['metric_count'] ?> metrics evaluated. <?= htmlspecialchars((string) $kit['disclaimer'], ENT_QUOTES, 'UTF-8') ?></p>
                </div>
            </div>
        </section>

        <?php foreach (['editorial' => 'Editorial score', 'media' => 'Media score', 'format' => 'Format score'] as $groupKey => $groupLabel): ?>
            <?php $group = $scores[$groupKey]; ?>
            <section>
                <div class="eyebrow"><?= $groupLabel ?> · <?= (int) $group['score'] ?> · <span class="badge" style="background: <?= $badgeColor((string) $group['badge']) ?>;"><?= htmlspecialchars((string) $group['badge'], ENT_QUOTES, 'UTF-8') ?></span></div>
                <?php foreach ((array) $group['metrics'] as $metric): ?>
                    <div class="metric-row">
                        <div><?= htmlspecialchars((string) $metric['label'], ENT_QUOTES, 'UTF-8') ?><em><?= htmlspecialchars((string) $metric['note'], ENT_QUOTES, 'UTF-8') ?></em></div>
                        <div class="bar"><span style="width: <?= (int) $metric['value'] ?>%;"></span></div>
                        <div class="metric-value"><?= (int) $metric['value'] ?></div>
                    </div>
                <?php endforeach; ?>
            </section>
        <?php endforeach; ?>

        <section>
            <div class="eyebrow">Document complexity</div>
            <div class="grid">
                <?php foreach ((array) $kit['complexity'] as $key => $value): ?>
                    <div class="stat"><strong><?= htmlspecialchars(is_float($value) ? number_format($value, 1) : number_format((int) $value), ENT_QUOTES, 'UTF-8') ?></strong><span><?= htmlspecialchars(ucwords(str_replace('_', ' ', (string) $key)), ENT_QUOTES, 'UTF-8') ?></span></div>
                <?php endforeach; ?>
            </div>
        </section>

        <section>
            <div class="eyebrow">KDP compatibility</div>
            <?php foreach ((array) $kit['kdp_compatibility_report'] as $check): ?>
                <div class="check">
                    <span class="status-<?= htmlspecialchars((string) $check['status'], ENT_QUOTES, 'UTF-8') ?>"><?= htmlspecialchars((string) $check['status'], ENT_QUOTES, 'UTF-8') ?></span>
                    <strong><?= htmlspecialchars((string) $check['check'], ENT_QUOTES, 'UTF-8') ?></strong>
                    <span style="color:#aeb2c2;"><?= htmlspecialchars((string) $check['detail'], ENT_QUOTES, 'UTF-8') ?></span>
                </div>
            <?php endforeach; ?>
        </section>

        <section>
            <div class="eyebrow">Metadata optimization · score <?= (int) $kit['metadata_optimization_report']['score'] ?></div>
            <p>Title <?= htmlspecialchars((string) $kit['metadata_optimization_report']['title_chars_used'], ENT_QUOTES, 'UTF-8') ?> · Description <?= htmlspecialchars((string) $kit['metadata_optimization_report']['description_chars_used'], ENT_QUOTES, 'UTF-8') ?> · Keywords <?= htmlspecialchars((string) $kit['metadata_optimization_report']['keyword_slots_used'], ENT_QUOTES, 'UTF-8') ?></p>
            <?php foreach ((array) $kit['metadata_optimization_report']['opportunities'] as $opportunity): ?>
                <p class="note">→ <?= htmlspecialchars((string) $opportunity, ENT_QUOTES, 'UTF-8') ?></p>
            <?php endforeach; ?>
        </section>

        <section>
            <div class="eyebrow">QueryBook enhancement plan · <?= (int) $kit['querybook_enhancement_plan']['question_count'] ?> quiz questions</div>
            <p class="note">Mode: <?= htmlspecialchars((string) $kit['querybook_enhancement_plan']['mode'], ENT_QUOTES, 'UTF-8') ?> — every chapter gets a three-question quiz, a key takeaway, and a learning-path step.</p>
            <?php foreach (array_slice((array) $kit['querybook_enhancement_plan']['chapters'], 0, 5) as $qb): ?>
                <details>
                    <summary>Chapter <?= (int) $qb['chapter'] ?>: <?= htmlspecialchars((string) $qb['title'], ENT_QUOTES, 'UTF-8') ?></summary>
                    <div>
                        <?php foreach ((array) $qb['quiz'] as $i => $question): ?>Q<?= $i + 1 ?>. <?= htmlspecialchars((string) $question, ENT_QUOTES, 'UTF-8') ?><br><?php endforeach; ?>
                        <strong>Takeaway:</strong> <?= htmlspecialchars((string) $qb['key_takeaway'], ENT_QUOTES, 'UTF-8') ?>
                    </div>
                </details>
            <?php endforeach; ?>
            <?php if (count((array) $kit['querybook_enhancement_plan']['chapters']) > 5): ?>
                <p class="note">…plus <?= count((array) $kit['querybook_enhancement_plan']['chapters']) - 5 ?> more chapters in the downloadable kit.</p>
            <?php endif; ?>
        </section>

        <section>
            <div class="eyebrow">Best-Seller Production Kit</div>
            <p>Everything above in one report: blueprint, chapter outline, media map, quality report, metadata and competitive-gap reports, QueryBook plan, KDP compatibility, and the best-seller probability score.</p>
            <div class="downloads">
                <a class="primary" href="book-lab.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=kit-html">Download production kit (.html report)</a>
                <a href="book-lab.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=kit-json">Download production kit (.json)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>">Open in the Amazon Book Writer →</a>
            </div>
        </section>
    <?php endif; ?>
</main>
</body>
</html>
