<?php

declare(strict_types=1);

require_once __DIR__ . '/BookIntelligenceEngine.php';

session_start();

$engine = new BookIntelligenceEngine();
$topic = trim((string) ($_POST['topic'] ?? $_GET['topic'] ?? $_SESSION['book_topic'] ?? 'Jobs and work for teens'));
$reader = trim((string) ($_POST['reader'] ?? $_GET['reader'] ?? $_SESSION['book_reader'] ?? 'teens exploring a first job while balancing school, safety, and real life'));
$style = trim((string) ($_POST['style'] ?? 'conversational'));
$length = trim((string) ($_POST['length'] ?? 'standard'));
$pageStyle = is_array($_POST['page_style'] ?? null) ? $_POST['page_style'] : [];
$presetPages = ['short' => 120, 'standard' => 240, 'expanded' => 500];
$pageCount = ctype_digit($length) ? max(1, min(1000, (int) $length)) : ($presetPages[$length] ?? 240);
$error = null;
$book = null;

try {
    $kit = $engine->buildKit($topic, ['reader' => $reader]);
    $chapters = is_array($_POST['chapters'] ?? null) ? array_values($_POST['chapters']) : $kit['blueprint']['chapters'];
    $legacyTitles = [
        'The leverage audit',
        'The tool-shaped trap',
        'A week that gives time back',
        'The human handoff',
        'The durable operating system',
    ];
    $submittedTitles = array_map(
        static fn ($chapter): string => is_array($chapter) ? trim((string) ($chapter['title'] ?? '')) : '',
        $chapters,
    );
    if (
        preg_match('/teen|teenager|youth|student|high school|young people/i', $topic) === 1
        && count($submittedTitles) === count($legacyTitles)
        && count(array_intersect($submittedTitles, $legacyTitles)) === count($legacyTitles)
    ) {
        $chapters = $kit['blueprint']['chapters'];
    }
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        $book = $engine->generateBookFromTableOfContents(
            $topic,
            $chapters,
            $style,
            $length,
            $reader,
            (string) ($kit['blueprint']['positioning']['core_promise'] ?? ''),
            $pageStyle,
        );
        $_SESSION['book_topic'] = $topic;
        $_SESSION['book_reader'] = $reader;
    }
} catch (Throwable $exception) {
    $error = $exception->getMessage();
    $chapters = [];
}

$styles = $engine->writingStyles();
$pageStyle = $book['page_style'] ?? $engine->defaultPageStyle();
$styleLabels = [];
foreach ($styles as $writingStyle) {
    $styleLabels[$writingStyle['id']] = $writingStyle['label'];
}
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Generate Book · Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #11141c; color: #eef0f6; }
        body { margin: 0; background: radial-gradient(circle at top right, #2a2048, #11141c 42%); min-height: 100vh; }
        main { max-width: 1100px; margin: 0 auto; padding: 42px 24px 80px; }
        header { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; border-bottom: 1px solid #36384a; padding-bottom: 30px; }
        .eyebrow { color: #b49cff; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(38px, 7vw, 72px); line-height: .96; max-width: 720px; margin: 14px 0; letter-spacing: -.06em; }
        h2, h3 { letter-spacing: -.035em; }
        p { color: #aeb2c2; line-height: 1.6; }
        a { color: #d5caff; }
        form, section { background: #1a1d28; border: 1px solid #343747; border-radius: 18px; padding: 24px; margin-top: 18px; }
        label { display: block; color: #dfe2eb; font-size: 12px; font-weight: 700; margin-bottom: 8px; }
        input, select, textarea { box-sizing: border-box; width: 100%; background: #10121a; border: 1px solid #4a4d61; border-radius: 9px; color: #fff; padding: 12px 13px; font: inherit; }
        input[type="color"] { padding: 4px; min-height: 44px; }
        input, select { margin-bottom: 15px; }
        textarea { resize: vertical; line-height: 1.55; }
        button { border: 0; border-radius: 999px; background: #b49cff; color: #171225; padding: 12px 18px; font: inherit; font-weight: 800; cursor: pointer; }
        .secondary { background: #292d3d; color: #e9e6f4; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
        .style { display: block; background: #222534; border-radius: 12px; padding: 14px; border: 1px solid #383b4d; }
        .style strong, .style span { display: block; }
        .style span { color: #aeb2c2; font-size: 11px; line-height: 1.4; margin-top: 5px; }
        .toc-row { border-top: 1px solid #36384a; padding: 17px 0 4px; }
        .toc-row strong { color: #b49cff; font-size: 11px; letter-spacing: .1em; }
        .toc-row input, .toc-row textarea { margin-top: 8px; margin-bottom: 8px; }
        .toc-row textarea { min-height: 58px; }
         .chapter { border-top: 1px solid #36384a; padding: 22px 0; }
         .manuscript-front-matter { break-after: page; page-break-after: always; }
         .manuscript-toc { break-before: page; break-after: page; page-break-before: always; page-break-after: always; }
         .manuscript-supporting-material { break-before: page; break-after: page; page-break-before: always; page-break-after: always; }
         .manuscript-chapter { break-before: page; page-break-before: always; }
        .chapter:first-child { border-top: 0; padding-top: 0; }
        .chapter h3 { margin: 6px 0 7px; font-size: 25px; }
        .chapter small { color: #b49cff; }
        .chapter textarea { min-height: 220px; margin-top: 12px; }
        .page-preview { margin-top: 16px; padding: <?= htmlspecialchars(($pageStyle['margin'] ?? 'standard') === 'compact' ? '34px 46px 48px' : (($pageStyle['margin'] ?? 'standard') === 'wide' ? '68px 90px 76px' : '52px 68px 62px'), ENT_QUOTES, 'UTF-8') ?>; background: <?= htmlspecialchars(($pageStyle['background'] ?? 'paper') === 'linen' ? '#f1ede4' : (($pageStyle['background'] ?? 'paper') === 'clean' ? '#fffdfa' : (($pageStyle['background'] ?? 'paper') === 'mist' ? '#edf1ef' : '#f8f4eb')), ENT_QUOTES, 'UTF-8') ?>; color: #202431; border: <?= (int) ($pageStyle['border_width'] ?? 1) ?>px <?= htmlspecialchars($pageStyle['border_style'] ?? 'solid', ENT_QUOTES, 'UTF-8') ?> <?= htmlspecialchars($pageStyle['border_color'] ?? '#d8d0c2', ENT_QUOTES, 'UTF-8') ?>; font-family: "<?= htmlspecialchars($pageStyle['font_family'] ?? 'Times New Roman', ENT_QUOTES, 'UTF-8') ?>", Georgia, serif; font-size: <?= (int) ($pageStyle['font_size'] ?? 12) ?>pt; line-height: <?= htmlspecialchars((string) ($pageStyle['line_height'] ?? 1.5), ENT_QUOTES, 'UTF-8') ?>; box-shadow: 0 15px 40px rgba(0,0,0,.18); }
        .page-preview h4 { margin: 0 0 24px; font-size: 30px; font-weight: 700; line-height: 1.05; }
        .page-preview h5 { margin: 24px 0 8px; font-size: 20px; font-weight: 700; }
        .page-preview p { color: #343947; }
        .page-running { color: #697080; font: 10px/1.4 ui-monospace, monospace; letter-spacing: .08em; text-align: right; text-transform: uppercase; }
         .page-footer { display: flex; justify-content: space-between; gap: 18px; margin-top: 30px; padding-top: 12px; border-top: 1px solid #d8d0c2; color: #697080; font: 10px/1.4 ui-monospace, monospace; text-transform: uppercase; }
         .job-catalog { margin: 20px 0 4px; border: 1px solid #3d4052; border-radius: 10px; background: #202331; }
         .job-catalog summary { cursor: pointer; padding: 13px 15px; color: #d5caff; font-weight: 800; }
         .job-catalog-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 0 12px 12px; }
         .job-card { padding: 11px; border: 1px solid #3a3d4d; border-radius: 8px; }
         .job-card strong, .job-card span { display: block; }
         .job-card strong { color: #fff; }
         .job-card span { margin-top: 5px; color: #aeb2c2; font-size: 11px; line-height: 1.45; }
         @media (max-width: 700px) { .job-catalog-list { grid-template-columns: 1fr; } }
        .error { color: #ff9cba; background: #3c1f32; border: 1px solid #7a3755; padding: 14px; border-radius: 10px; margin-top: 18px; }
        .note { color: #8d91a3; font-size: 12px; }
        @media (max-width: 700px) { header { display: block; } main { padding: 28px 16px 60px; } form, section { padding: 18px; } }
    </style>
</head>
<body>
<main>
    <header>
        <div>
            <div class="eyebrow">Book Intelligence Studio · PHP reference app</div>
            <h1>Draft the book behind the outline.</h1>
            <p>Choose a voice, make any last edits to the table of contents, and generate a working manuscript chapter by chapter.</p>
        </div>
        <div>
            <a href="index.php">← Back to intelligence kit</a><br>
            <a href="amazon-book-writer.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>">Package for Amazon KDP →</a>
        </div>
    </header>

    <?php if ($error !== null): ?>
        <div class="error"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></div>
    <?php endif; ?>

    <form method="post">
        <div class="grid">
            <div>
                <label for="topic">Book topic</label>
                <input id="topic" name="topic" value="<?= htmlspecialchars($topic, ENT_QUOTES, 'UTF-8') ?>" required>
            </div>
            <div>
                <label for="reader">Reader description</label>
                <input id="reader" name="reader" value="<?= htmlspecialchars($reader, ENT_QUOTES, 'UTF-8') ?>" placeholder="e.g. curious practitioners">
            </div>
            <div>
                <label for="style">Writing style</label>
                <select id="style" name="style">
                    <?php foreach ($styles as $writingStyle): ?>
                        <option value="<?= htmlspecialchars($writingStyle['id'], ENT_QUOTES, 'UTF-8') ?>" <?= $style === $writingStyle['id'] ? 'selected' : '' ?>><?= htmlspecialchars($writingStyle['label'], ENT_QUOTES, 'UTF-8') ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="length">Draft length · 1–1,000 pages</label>
                <input id="length" name="length" type="number" min="1" max="1000" value="<?= (int) $pageCount ?>" required>
                <input id="page-range" type="range" min="1" max="1000" value="<?= (int) $pageCount ?>" aria-label="Target book length in pages" oninput="document.getElementById('length').value = this.value">
                <div class="note">Set any target up to 1,000 pages. Presets: 120 short, 240 standard, 500 expanded.</div>
            </div>
        </div>

        <h2>Page design</h2>
        <div class="grid">
            <div>
                <label for="font-family">Book font</label>
                <select id="font-family" name="page_style[font_family]">
                    <?php foreach (['Times New Roman', 'Georgia', 'Garamond', 'Arial', 'Helvetica', 'Courier New'] as $font): ?>
                        <option <?= ($pageStyle['font_family'] ?? 'Times New Roman') === $font ? 'selected' : '' ?>><?= htmlspecialchars($font, ENT_QUOTES, 'UTF-8') ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="page-background">Page tone</label>
                <select id="page-background" name="page_style[background]">
                    <?php foreach (['paper' => 'Warm paper', 'linen' => 'Soft linen', 'clean' => 'Clean white', 'mist' => 'Cool mist'] as $value => $label): ?>
                        <option value="<?= $value ?>" <?= ($pageStyle['background'] ?? 'paper') === $value ? 'selected' : '' ?>><?= $label ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="page-margin">Margins</label>
                <select id="page-margin" name="page_style[margin]">
                    <?php foreach (['compact', 'standard', 'wide'] as $margin): ?>
                        <option <?= ($pageStyle['margin'] ?? 'standard') === $margin ? 'selected' : '' ?>><?= $margin ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="page-border">Border</label>
                <select id="page-border" name="page_style[border_style]">
                    <?php foreach (['solid', 'double', 'dashed', 'none'] as $border): ?>
                        <option <?= ($pageStyle['border_style'] ?? 'solid') === $border ? 'selected' : '' ?>><?= $border ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div>
                <label for="page-border-color">Border color</label>
                <input id="page-border-color" type="color" name="page_style[border_color]" value="<?= htmlspecialchars($pageStyle['border_color'] ?? '#d8d0c2', ENT_QUOTES, 'UTF-8') ?>">
            </div>
            <div>
                <label for="page-number-position">Page numbers</label>
                <select id="page-number-position" name="page_style[page_number_position]">
                    <option value="bottom-center" <?= ($pageStyle['page_number_position'] ?? 'bottom-center') === 'bottom-center' ? 'selected' : '' ?>>Bottom center</option>
                    <option value="bottom-right" <?= ($pageStyle['page_number_position'] ?? 'bottom-center') === 'bottom-right' ? 'selected' : '' ?>>Bottom right</option>
                </select>
                <label><input type="hidden" name="page_style[show_page_numbers]" value="0"><input type="checkbox" name="page_style[show_page_numbers]" value="1" <?= ($pageStyle['show_page_numbers'] ?? true) ? 'checked' : '' ?>> Show page numbers</label>
            </div>
            <div>
                <label for="page-header">Running header</label>
                <input id="page-header" name="page_style[header]" value="<?= htmlspecialchars((string) ($pageStyle['header'] ?? ''), ENT_QUOTES, 'UTF-8') ?>" placeholder="Optional">
            </div>
            <div>
                <label for="page-footer">Running footer</label>
                <input id="page-footer" name="page_style[footer]" value="<?= htmlspecialchars((string) ($pageStyle['footer'] ?? ''), ENT_QUOTES, 'UTF-8') ?>" placeholder="Optional">
            </div>
        </div>

        <h2>Table of contents</h2>
        <p class="note">These fields are the source for the generated manuscript. Edit them before you draft if the argument has moved.</p>
        <?php foreach ($chapters as $index => $chapter): ?>
            <div class="toc-row">
                <strong>CHAPTER <?= (int) ($index + 1) ?></strong>
                <input name="chapters[<?= (int) $index ?>][title]" value="<?= htmlspecialchars((string) ($chapter['title'] ?? ''), ENT_QUOTES, 'UTF-8') ?>" aria-label="Chapter title">
                <input name="chapters[<?= (int) $index ?>][purpose]" value="<?= htmlspecialchars((string) ($chapter['purpose'] ?? ''), ENT_QUOTES, 'UTF-8') ?>" aria-label="Chapter purpose">
                <textarea name="chapters[<?= (int) $index ?>][detail]" aria-label="Chapter detail"><?= htmlspecialchars((string) ($chapter['detail'] ?? ''), ENT_QUOTES, 'UTF-8') ?></textarea>
            </div>
        <?php endforeach; ?>
        <button type="submit">Generate working book</button>
    </form>

    <section>
        <div class="eyebrow">Available voices</div>
        <div class="grid">
            <?php foreach ($styles as $writingStyle): ?>
                <div class="style"><strong><?= htmlspecialchars($writingStyle['label'], ENT_QUOTES, 'UTF-8') ?></strong><span><?= htmlspecialchars($writingStyle['description'], ENT_QUOTES, 'UTF-8') ?></span></div>
            <?php endforeach; ?>
        </div>
    </section>

    <?php if ($book !== null): ?>
         <section>
             <div class="manuscript-front-matter">
                 <div class="eyebrow">Working manuscript · <?= htmlspecialchars($book['style_label'], ENT_QUOTES, 'UTF-8') ?></div>
                 <h2><?= htmlspecialchars($topic, ENT_QUOTES, 'UTF-8') ?></h2>
                 <p class="note">Assigned agent: <?= htmlspecialchars($book['style_agent']['name'] ?? 'Style specialist', ENT_QUOTES, 'UTF-8') ?> · <?= htmlspecialchars($book['style_agent']['mission'] ?? 'Shape the draft for its selected voice.', ENT_QUOTES, 'UTF-8') ?></p>
                 <p class="note">Generated <?= htmlspecialchars($book['generated_at'], ENT_QUOTES, 'UTF-8') ?> · <?= number_format((int) $book['page_count']) ?> planned pages · <?= number_format((int) $book['total_word_count']) ?> words at <?= number_format((int) $book['words_per_page']) ?> words per page. Review claims, sources, examples, and voice before publication.</p>
             </div>
            <?php if (!empty($book['job_catalog'])): ?>
                 <section class="manuscript-supporting-material" aria-labelledby="catalog-heading">
                     <div class="eyebrow">Supporting material</div>
                     <h3 id="catalog-heading">Teen job catalog</h3>
                     <p class="note">Canonical catalog: <?= number_format(count($book['job_catalog'])) ?> records across <?= number_format(count(array_unique(array_column($book['job_catalog'], 'category')))) ?> categories. This catalog is supporting material, not part of the table of contents.</p>
                     <details class="job-catalog">
                         <summary>Show all <?= number_format(count($book['job_catalog'])) ?> catalog records</summary>
                         <div class="job-catalog-list">
                             <?php foreach ($book['job_catalog'] as $job): ?>
                                 <div class="job-card">
                                     <strong><?= htmlspecialchars((string) ($job['title'] ?? ''), ENT_QUOTES, 'UTF-8') ?></strong>
                                     <span><?= htmlspecialchars((string) ($job['category'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                     <span><b>What:</b> <?= htmlspecialchars((string) ($job['does'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                     <span><b>Who it suits:</b> <?= htmlspecialchars((string) ($job['suits'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                     <span><b>Where:</b> <?= htmlspecialchars((string) ($job['find'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                     <span><b>Start:</b> <?= htmlspecialchars((string) ($job['start'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                     <span><b>Skills/training:</b> <?= htmlspecialchars((string) ($job['skills'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                     <span><b>Schedule:</b> <?= htmlspecialchars((string) ($job['schedule'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                     <span><b>Safety:</b> <?= htmlspecialchars((string) ($job['safety'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                                 </div>
                             <?php endforeach; ?>
                         </div>
                     </details>
                 </section>
            <?php endif; ?>
             <div class="chapter manuscript-toc" aria-labelledby="table-of-contents-heading">
                <small>TABLE OF CONTENTS</small>
                <h3 id="table-of-contents-heading">Contents</h3>
                <?php foreach ($book['table_of_contents'] as $entry): ?>
                    <p><strong><?= (int) $entry['number'] ?>. <?= htmlspecialchars($entry['title'], ENT_QUOTES, 'UTF-8') ?><span style="float:right;">Page <?= (int) ($entry['page_number'] ?? 0) ?></span></strong><br><span class="note"><?= (int) $entry['page_count'] ?> planned pages · <?= htmlspecialchars($entry['purpose'], ENT_QUOTES, 'UTF-8') ?></span></p>
                <?php endforeach; ?>
            </div>
            <?php foreach ($book['chapters'] as $chapterIndex => $chapter): ?>
                 <article class="chapter manuscript-chapter">
                    <small>CHAPTER <?= (int) $chapter['number'] ?> · <?= (int) $chapter['page_count'] ?> planned pages · <?= number_format((int) $chapter['word_count']) ?> words · <?= htmlspecialchars($chapter['purpose'], ENT_QUOTES, 'UTF-8') ?></small>
                    <h3><?= htmlspecialchars($chapter['title'], ENT_QUOTES, 'UTF-8') ?></h3>
                    <p class="note"><?= htmlspecialchars($chapter['analysis'], ENT_QUOTES, 'UTF-8') ?></p>
                    <div class="page-preview" aria-label="Formatted page preview for <?= htmlspecialchars($chapter['title'], ENT_QUOTES, 'UTF-8') ?>">
                        <?php if (($pageStyle['header'] ?? '') !== ''): ?><div class="page-running"><?= htmlspecialchars((string) $pageStyle['header'], ENT_QUOTES, 'UTF-8') ?></div><?php endif; ?>
                        <h4><?= htmlspecialchars($chapter['title'], ENT_QUOTES, 'UTF-8') ?></h4>
                        <?php foreach (($chapter['blocks'] ?? []) as $block): ?>
                            <?php if (($block['kind'] ?? '') === 'heading'): ?>
                                <h5><?= htmlspecialchars((string) ($block['content'] ?? ''), ENT_QUOTES, 'UTF-8') ?></h5>
                            <?php else: ?>
                                <p><?= nl2br(htmlspecialchars((string) ($block['content'] ?? ''), ENT_QUOTES, 'UTF-8')) ?></p>
                            <?php endif; ?>
                        <?php endforeach; ?>
                        <?php if (($pageStyle['show_page_numbers'] ?? true) || ($pageStyle['footer'] ?? '') !== ''): ?>
                            <div class="page-footer"><span><?= htmlspecialchars((string) ($pageStyle['footer'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span><?php if ($pageStyle['show_page_numbers'] ?? true): ?><span>Page <?= (int) ($book['table_of_contents'][$chapterIndex]['page_number'] ?? (3 + $chapterIndex)) ?></span><?php endif; ?></div>
                        <?php endif; ?>
                    </div>
                </article>
            <?php endforeach; ?>
        </section>
    <?php endif; ?>
</main>
</body>
</html>