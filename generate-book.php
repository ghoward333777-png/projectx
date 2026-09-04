<?php

declare(strict_types=1);

require_once __DIR__ . '/BookIntelligenceEngine.php';
require_once __DIR__ . '/IllustrationStudio.php';
require_once __DIR__ . '/StudioTheme.php';

session_start();

$engine = new BookIntelligenceEngine();
$studio = new IllustrationStudio();
$topic = trim((string) ($_POST['topic'] ?? $_GET['topic'] ?? $_SESSION['book_topic'] ?? 'Jobs and work for teens'));
$reader = trim((string) ($_POST['reader'] ?? $_GET['reader'] ?? $_SESSION['book_reader'] ?? 'teens exploring a first job while balancing school, safety, and real life'));
$style = trim((string) ($_POST['style'] ?? 'conversational'));
$length = trim((string) ($_POST['length'] ?? 'standard'));
$pageStyle = is_array($_POST['page_style'] ?? null) ? $_POST['page_style'] : [];
$presetPages = ['short' => 120, 'standard' => 240, 'expanded' => 500];
$pageCount = ctype_digit($length) ? max(1, min(1000, (int) $length)) : ($presetPages[$length] ?? 240);
$error = null;
$book = null;

// The Visual Editor's blocks: which figure kinds join the manuscript preview,
// and how many of each the whole manuscript may carry.
$blockCatalog = [
    'table' => ['label' => 'Tables', 'hint' => 'Comparison and reference tables', 'default' => true, 'limit' => 3],
    'chart' => ['label' => 'Charts', 'hint' => 'Bar charts built from real chapter data', 'default' => true, 'limit' => 2],
    'diagram' => ['label' => 'Diagrams', 'hint' => 'Step flows drawn from each chapter', 'default' => true, 'limit' => 2],
    'illustration' => ['label' => 'Figures', 'hint' => 'Takeaway pull-quote cards', 'default' => true, 'limit' => 3],
    'ai-image' => ['label' => 'AI-generated images', 'hint' => 'One contextual prompt per chapter, generated locally', 'default' => false, 'limit' => 3],
];
$postedBlocks = is_array($_POST['blocks'] ?? null) ? $_POST['blocks'] : null;
$postedLimits = is_array($_POST['block_limits'] ?? null) ? $_POST['block_limits'] : [];
$enabledBlocks = [];
$blockLimits = [];
foreach ($blockCatalog as $kind => $definition) {
    $enabledBlocks[$kind] = $postedBlocks === null ? $definition['default'] : !empty($postedBlocks[$kind]);
    $blockLimits[$kind] = max(0, min(120, (int) ($postedLimits[$kind] ?? $definition['limit'])));
}

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
$selectedStyle = null;
foreach ($styles as $writingStyle) {
    if ($writingStyle['id'] === $style) {
        $selectedStyle = $writingStyle;
    }
}
$selectedStyle ??= $styles[0];

// Plan the manuscript's figures, filtered by the Visual Editor's blocks.
$chapterMedia = [];
if ($book !== null) {
    $remaining = $blockLimits;
    foreach ($book['chapters'] as $chapterIndex => $chapter) {
        $items = [];
        foreach ($studio->planChapterMedia($chapter, $book, ['title' => $topic]) as $item) {
            $kind = (string) ($item['kind'] ?? '');
            if (empty($enabledBlocks[$kind]) || ($remaining[$kind] ?? 0) < 1) {
                continue;
            }
            $remaining[$kind]--;
            $items[] = $item;
        }
        $chapterMedia[$chapterIndex] = $items;
    }
}

$downloadQuery = http_build_query([
    'topic' => $topic,
    'reader' => $reader,
    'style' => $style,
    'length' => (string) $pageCount,
]);
$exportFiles = [
    'word' => 'Word manuscript (.docx)',
    'epub' => 'eBook (.epub)',
    'drafting-kit' => 'AI drafting kit (.json)',
    'manuscript' => 'KDP manuscript (.html)',
    'companion' => 'Companion page (.html)',
];
$previewPadding = ($pageStyle['margin'] ?? 'standard') === 'compact' ? '34px 46px 48px' : ((($pageStyle['margin'] ?? 'standard') === 'wide') ? '68px 90px 76px' : '52px 68px 62px');
$previewBackground = ['linen' => '#f1ede4', 'clean' => '#fffdfa', 'mist' => '#edf1ef'][$pageStyle['background'] ?? 'paper'] ?? '#f8f4eb';
$h = static fn (string $v): string => htmlspecialchars($v, ENT_QUOTES, 'UTF-8');
?>
<!doctype html>
<html lang="en">
<head>
    <?php StudioTheme::head('Book generator'); ?>
    <style>
        .page-preview { margin-top: 20px; padding: <?= $h($previewPadding) ?>; background: <?= $h($previewBackground) ?>; color: #202431; border: <?= (int) ($pageStyle['border_width'] ?? 1) ?>px <?= $h((string) ($pageStyle['border_style'] ?? 'solid')) ?> <?= $h((string) ($pageStyle['border_color'] ?? '#d8d0c2')) ?>; font-family: "<?= $h((string) ($pageStyle['font_family'] ?? 'Times New Roman')) ?>", Georgia, serif; font-size: <?= (int) ($pageStyle['font_size'] ?? 12) ?>pt; line-height: <?= $h((string) ($pageStyle['line_height'] ?? 1.5)) ?>; box-shadow: 0 15px 40px rgba(47, 43, 31, .14); border-radius: 3px; }
        .manuscript-front-matter { break-after: page; page-break-after: always; }
        .manuscript-supporting-material { break-before: page; break-after: page; page-break-before: always; page-break-after: always; }
        .manuscript-toc { break-before: page; break-after: page; page-break-before: always; page-break-after: always; }
        .manuscript-chapter { break-before: page; page-break-before: always; }
    </style>
</head>
<body>
<?php StudioTheme::open([
    'active' => 'writer',
    'current' => 'Book generator',
    'brief' => $topic,
    'progress_label' => 'Drafting from table of contents',
    'progress_value' => $book !== null ? 'Draft saved' : 'Ready to write',
    'progress_percent' => $book !== null ? 100 : 60,
]); ?>

    <div class="page-intro">
        <div>
            <span class="section-label coral">BOOK GENERATOR</span>
            <h1>Draft the book behind the outline.</h1>
            <p>Choose a voice, make any last edits to the table of contents, and generate a working manuscript chapter by chapter — figures, page design, and exports included.</p>
        </div>
        <div class="intro-action">
            <a class="outline-button" href="amazon-book-writer.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>"><?= StudioTheme::icon('sparkles', 14) ?> Package for Amazon KDP</a>
        </div>
    </div>

    <?php if ($error !== null): ?>
        <div class="error"><?= $h($error) ?></div>
    <?php endif; ?>

    <form method="post" id="writer-form">
        <div class="paper-card writer-options-card animate-rise-in">
            <div class="card-heading-row">
                <div>
                    <span class="writer-section-label">THE BRIEF</span>
                    <h2>What the book is, and who it is for</h2>
                </div>
                <span class="visual-agent-label"><?= StudioTheme::icon('pen', 11) ?> AGENT · THE MANUSCRIPT DESK</span>
            </div>
            <div class="grid" style="margin-top: 20px;">
                <div>
                    <label for="topic">Book topic</label>
                    <input id="topic" name="topic" value="<?= $h($topic) ?>" required data-testid="field-topic">
                </div>
                <div>
                    <label for="reader">Reader description</label>
                    <input id="reader" name="reader" value="<?= $h($reader) ?>" placeholder="e.g. curious practitioners">
                </div>
            </div>

            <div class="writer-length-row" style="border-top: 0; margin-top: 8px; padding-top: 8px; display: block;">
                <span class="writer-section-label">WRITING VOICE · 13 AGENTS</span>
                <div class="style-grid">
                    <?php foreach ($styles as $writingStyle): ?>
                        <label class="style-option<?= $style === $writingStyle['id'] ? ' active' : '' ?>" data-agent-name="<?= $h((string) ($writingStyle['agent_name'] ?? $writingStyle['label'])) ?>" data-agent-mission="<?= $h((string) ($writingStyle['agent_mission'] ?? $writingStyle['description'])) ?>">
                            <input type="radio" name="style" value="<?= $h($writingStyle['id']) ?>" <?= $style === $writingStyle['id'] ? 'checked' : '' ?>>
                            <span class="style-radio"><?= StudioTheme::icon('check', 10) ?></span>
                            <span><strong><?= $h($writingStyle['label']) ?></strong><small class="style-agent-label"><?= $h((string) ($writingStyle['agent_name'] ?? '')) ?></small><small><?= $h($writingStyle['description']) ?></small></span>
                        </label>
                    <?php endforeach; ?>
                </div>
                <div class="agent-callout" id="style-agent-callout">
                    <?= StudioTheme::icon('sparkles', 14) ?>
                    <span><b id="style-agent-name"><?= $h((string) ($selectedStyle['agent_name'] ?? $selectedStyle['label'])) ?></b> writes every chapter in this draft. <span id="style-agent-mission"><?= $h((string) ($selectedStyle['agent_mission'] ?? $selectedStyle['description'])) ?></span> You can rewrite in another voice at any time.</span>
                </div>
            </div>

            <div class="writer-media-options">
                <div>
                    <span class="writer-section-label">VISUAL BLOCKS</span>
                    <small>Every chapter gets figures after its important topics. Choose which block kinds join the manuscript and cap how many appear in the whole draft — the reader's understanding comes first, and visual blocks remain editable.</small>
                    <span class="visual-agent-label"><?= StudioTheme::icon('palette', 11) ?> AGENT · THE VISUAL EDITOR</span>
                </div>
                <div class="media-option-grid">
                    <?php foreach ($blockCatalog as $kind => $definition): ?>
                        <label class="media-option<?= $enabledBlocks[$kind] ? ' active' : '' ?>">
                            <input type="checkbox" name="blocks[<?= $h($kind) ?>]" value="1" <?= $enabledBlocks[$kind] ? 'checked' : '' ?>>
                            <span style="min-width:0;">
                                <strong><?= $h($definition['label']) ?></strong>
                                <small><?= $h($definition['hint']) ?></small>
                                <span class="media-limit-control"><small>Maximum in manuscript</small><input type="number" name="block_limits[<?= $h($kind) ?>]" min="0" max="120" value="<?= (int) $blockLimits[$kind] ?>" onclick="event.stopPropagation()"></span>
                            </span>
                        </label>
                    <?php endforeach; ?>
                </div>
            </div>

            <div class="writer-length-row">
                <div>
                    <span class="writer-section-label">DRAFT LENGTH · 1–1,000 PAGES</span>
                    <small>Set the target manuscript size. The chapter scaffolding scales with your selection.</small>
                </div>
                <div class="page-control">
                    <div class="length-toggle" role="group" aria-label="Draft length presets">
                        <button type="button" data-pages="120">Short <span>120p</span></button>
                        <button type="button" data-pages="240">Standard <span>240p</span></button>
                        <button type="button" data-pages="500">Expanded <span>500p</span></button>
                    </div>
                    <div class="page-input-row">
                        <input id="page-range" type="range" min="1" max="1000" value="<?= (int) $pageCount ?>" aria-label="Target book length in pages">
                        <span class="page-number-input"><input id="length" name="length" type="number" min="1" max="1000" value="<?= (int) $pageCount ?>" required> pages</span>
                    </div>
                    <span class="page-range-note">Custom length available up to 1,000 pages.</span>
                </div>
            </div>

            <div class="writer-source-note">
                <?= StudioTheme::icon('book-open', 14) ?>
                <span>Source outline: <b><?= count($chapters) ?> chapters</b> · <?= $h($topic) ?></span>
            </div>

            <details class="toc-editor" id="toc-editor">
                <summary><?= StudioTheme::icon('edit-list', 14) ?> Edit table of contents · <?= count($chapters) ?> chapters</summary>
                <div class="toc-editor-rows">
                    <?php foreach ($chapters as $index => $chapter): ?>
                        <div class="toc-row">
                            <strong>CHAPTER <?= (int) ($index + 1) ?></strong>
                            <input name="chapters[<?= (int) $index ?>][title]" value="<?= $h((string) ($chapter['title'] ?? '')) ?>" aria-label="Chapter title">
                            <input name="chapters[<?= (int) $index ?>][purpose]" value="<?= $h((string) ($chapter['purpose'] ?? '')) ?>" aria-label="Chapter purpose">
                            <textarea name="chapters[<?= (int) $index ?>][detail]" aria-label="Chapter detail"><?= $h((string) ($chapter['detail'] ?? '')) ?></textarea>
                        </div>
                    <?php endforeach; ?>
                </div>
            </details>

            <div class="writer-actions">
                <button type="button" class="outline-button" id="open-toc-editor" data-testid="button-edit-toc"><?= StudioTheme::icon('edit-list', 14) ?> Edit table of contents</button>
                <button type="submit" class="primary-button" data-testid="button-generate"><?= StudioTheme::icon($book !== null ? 'refresh' : 'pen', 14) ?> <?= $book !== null ? 'Rewrite manuscript' : 'Generate manuscript' ?></button>
                <a class="primary-button draft-download-button" href="amazon-book-writer.php?<?= $h($downloadQuery) ?>&amp;download=word"><?= StudioTheme::icon('download', 14) ?> Download Word</a>
            </div>

            <?php if ($book !== null): ?>
                <div class="writer-task-progress" role="progressbar" aria-valuemin="0" aria-valuemax="<?= count($exportFiles) ?>" aria-valuenow="<?= count($exportFiles) ?>" data-testid="export-preparation-status">
                    <div><span>ALL DOWNLOAD FILES READY</span><b><?= count($exportFiles) ?>/<?= count($exportFiles) ?> FILES</b></div>
                    <div class="writer-task-track"><span style="width: 100%"></span></div>
                </div>
                <div class="draft-export-actions" style="margin-top: 13px;">
                    <?php foreach ($exportFiles as $format => $label): ?>
                        <a class="outline-button" href="amazon-book-writer.php?<?= $h($downloadQuery) ?>&amp;download=<?= $h($format) ?>"><?= StudioTheme::icon('download', 12) ?> <?= $h($label) ?></a>
                    <?php endforeach; ?>
                </div>
            <?php endif; ?>
        </div>

        <div class="paper-card page-style-panel animate-rise-in">
            <div class="page-style-heading">
                <div>
                    <span class="section-label coral">PAGE DESIGN</span>
                    <h2>How every page looks</h2>
                    <p>Typeface, tone, margins, borders, and running furniture. The same design flows into the on-page preview and the Word, ePub, and KDP exports.</p>
                </div>
                <span class="page-style-icon"><?= StudioTheme::icon('palette', 20) ?></span>
            </div>
            <div class="page-style-grid">
                <div class="page-style-field">Book font
                    <select name="page_style[font_family]">
                        <?php foreach (['Times New Roman', 'Georgia', 'Garamond', 'Arial', 'Helvetica', 'Courier New'] as $font): ?>
                            <option <?= ($pageStyle['font_family'] ?? 'Times New Roman') === $font ? 'selected' : '' ?>><?= $h($font) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="page-style-field">Font size (pt)
                    <input type="number" name="page_style[font_size]" min="8" max="32" value="<?= (int) ($pageStyle['font_size'] ?? 12) ?>">
                </div>
                <div class="page-style-field">Line height
                    <input type="number" name="page_style[line_height]" min="1" max="3" step="0.1" value="<?= $h((string) ($pageStyle['line_height'] ?? 1.5)) ?>">
                </div>
                <div class="page-style-field">Page tone
                    <select name="page_style[background]">
                        <?php foreach (['paper' => 'Warm paper', 'linen' => 'Soft linen', 'clean' => 'Clean white', 'mist' => 'Cool mist'] as $value => $label): ?>
                            <option value="<?= $value ?>" <?= ($pageStyle['background'] ?? 'paper') === $value ? 'selected' : '' ?>><?= $label ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="page-style-field">Margins
                    <select name="page_style[margin]">
                        <?php foreach (['compact', 'standard', 'wide'] as $margin): ?>
                            <option <?= ($pageStyle['margin'] ?? 'standard') === $margin ? 'selected' : '' ?>><?= $margin ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="page-style-field">Border
                    <select name="page_style[border_style]">
                        <?php foreach (['solid', 'double', 'dashed', 'none'] as $border): ?>
                            <option <?= ($pageStyle['border_style'] ?? 'solid') === $border ? 'selected' : '' ?>><?= $border ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="page-style-field">Border width (px)
                    <input type="number" name="page_style[border_width]" min="0" max="12" value="<?= (int) ($pageStyle['border_width'] ?? 1) ?>">
                </div>
                <div class="page-style-field">Border color
                    <input type="color" name="page_style[border_color]" value="<?= $h((string) ($pageStyle['border_color'] ?? '#d8d0c2')) ?>">
                </div>
                <div class="page-style-field">Page numbers
                    <select name="page_style[page_number_position]">
                        <option value="bottom-center" <?= ($pageStyle['page_number_position'] ?? 'bottom-center') === 'bottom-center' ? 'selected' : '' ?>>Bottom center</option>
                        <option value="bottom-right" <?= ($pageStyle['page_number_position'] ?? 'bottom-center') === 'bottom-right' ? 'selected' : '' ?>>Bottom right</option>
                    </select>
                    <label><input type="hidden" name="page_style[show_page_numbers]" value="0"><input type="checkbox" name="page_style[show_page_numbers]" value="1" <?= ($pageStyle['show_page_numbers'] ?? true) ? 'checked' : '' ?>> Show page numbers</label>
                </div>
                <div class="page-style-field">Running header
                    <input name="page_style[header]" value="<?= $h((string) ($pageStyle['header'] ?? '')) ?>" placeholder="Optional">
                </div>
                <div class="page-style-field">Running footer
                    <input name="page_style[footer]" value="<?= $h((string) ($pageStyle['footer'] ?? '')) ?>" placeholder="Optional">
                </div>
            </div>
        </div>
    </form>

    <?php if ($book !== null): ?>
        <div class="writer-output animate-rise-in">
            <div class="writer-output-header">
                <div class="manuscript-front-matter">
                    <span class="section-label coral">WORKING MANUSCRIPT · <?= $h(strtoupper($book['style_label'])) ?></span>
                    <h2><?= $h($topic) ?></h2>
                    <p>Generated <?= $h($book['generated_at']) ?> · <?= number_format((int) $book['page_count']) ?> planned pages · <?= number_format((int) $book['total_word_count']) ?> words at <?= number_format((int) $book['words_per_page']) ?> words per page</p>
                </div>
            </div>
            <div class="agent-callout">
                <?= StudioTheme::icon('pen', 14) ?>
                <span><b><?= $h((string) ($book['style_agent']['name'] ?? 'Style specialist')) ?></b> wrote every chapter in this draft. <?= $h((string) ($book['style_agent']['mission'] ?? 'Shape the draft for its selected voice.')) ?> Review claims, sources, examples, and voice before publication.</span>
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
                                    <strong><?= $h((string) ($job['title'] ?? '')) ?></strong>
                                    <span><?= $h((string) ($job['category'] ?? '')) ?></span>
                                    <span><b>What:</b> <?= $h((string) ($job['does'] ?? '')) ?></span>
                                    <span><b>Who it suits:</b> <?= $h((string) ($job['suits'] ?? '')) ?></span>
                                    <span><b>Where:</b> <?= $h((string) ($job['find'] ?? '')) ?></span>
                                    <span><b>Start:</b> <?= $h((string) ($job['start'] ?? '')) ?></span>
                                    <span><b>Skills/training:</b> <?= $h((string) ($job['skills'] ?? '')) ?></span>
                                    <span><b>Schedule:</b> <?= $h((string) ($job['schedule'] ?? '')) ?></span>
                                    <span><b>Safety:</b> <?= $h((string) ($job['safety'] ?? '')) ?></span>
                                </div>
                            <?php endforeach; ?>
                        </div>
                    </details>
                </section>
            <?php endif; ?>

            <div class="paper-card draft-toc manuscript-toc" aria-labelledby="table-of-contents-heading">
                <div class="draft-toc-heading">
                    <div>
                        <span class="section-label">TABLE OF CONTENTS</span>
                        <h2 id="table-of-contents-heading">Contents</h2>
                    </div>
                </div>
                <ol class="draft-toc-list">
                    <?php foreach ($book['table_of_contents'] as $entry): ?>
                        <li><span><b><?= (int) $entry['number'] ?></b> &nbsp;<?= $h($entry['title']) ?></span><small><?= (int) $entry['page_count'] ?> pages · p. <?= (int) ($entry['page_number'] ?? 0) ?></small></li>
                    <?php endforeach; ?>
                </ol>
            </div>

            <div class="draft-list">
                <?php foreach ($book['chapters'] as $chapterIndex => $chapter): ?>
                    <article class="paper-card draft-chapter manuscript-chapter">
                        <div class="draft-chapter-number"><?= str_pad((string) $chapter['number'], 2, '0', STR_PAD_LEFT) ?></div>
                        <div class="draft-chapter-body">
                            <div class="draft-chapter-heading">
                                <div>
                                    <span class="draft-purpose"><?= $h($chapter['purpose']) ?> · <?= (int) $chapter['page_count'] ?> planned pages · <?= number_format((int) $chapter['word_count']) ?> words</span>
                                    <h3><?= $h($chapter['title']) ?></h3>
                                </div>
                            </div>
                            <p class="draft-analysis"><?= $h($chapter['analysis']) ?></p>
                            <div class="page-preview" aria-label="Formatted page preview for <?= $h($chapter['title']) ?>">
                                <?php if (($pageStyle['header'] ?? '') !== ''): ?><div class="page-running"><?= $h((string) $pageStyle['header']) ?></div><?php endif; ?>
                                <h4><?= $h($chapter['title']) ?></h4>
                                <?php foreach (($chapter['blocks'] ?? []) as $block): ?>
                                    <?php if (($block['kind'] ?? '') === 'heading'): ?>
                                        <h5><?= $h((string) ($block['content'] ?? '')) ?></h5>
                                    <?php else: ?>
                                        <p><?= nl2br($h((string) ($block['content'] ?? ''))) ?></p>
                                    <?php endif; ?>
                                <?php endforeach; ?>
                                <?php if (($pageStyle['show_page_numbers'] ?? true) || ($pageStyle['footer'] ?? '') !== ''): ?>
                                    <div class="page-footer"><span><?= $h((string) ($pageStyle['footer'] ?? '')) ?></span><?php if ($pageStyle['show_page_numbers'] ?? true): ?><span>Page <?= (int) ($book['table_of_contents'][$chapterIndex]['page_number'] ?? (3 + $chapterIndex)) ?></span><?php endif; ?></div>
                                <?php endif; ?>
                            </div>
                            <?php foreach (($chapterMedia[$chapterIndex] ?? []) as $item): ?>
                                <figure class="draft-figure">
                                    <?php if (!empty($item['svg'])): ?>
                                        <?= $item['svg'] ?>
                                    <?php elseif (!empty($item['table'])): ?>
                                        <table>
                                            <thead><tr><?php foreach ((array) $item['table']['columns'] as $column): ?><th><?= $h((string) $column) ?></th><?php endforeach; ?></tr></thead>
                                            <tbody><?php foreach ((array) $item['table']['rows'] as $row): ?><tr><?php foreach ((array) $row as $cell): ?><td><?= $h((string) $cell) ?></td><?php endforeach; ?></tr><?php endforeach; ?></tbody>
                                        </table>
                                    <?php endif; ?>
                                    <figcaption><b><?= $h($blockCatalog[$item['kind']]['label'] ?? (string) $item['kind']) ?></b><?= $h((string) ($item['title'] ?? '')) ?> — <?= $h((string) ($item['caption'] ?? '')) ?></figcaption>
                                </figure>
                            <?php endforeach; ?>
                        </div>
                    </article>
                <?php endforeach; ?>
            </div>
        </div>
    <?php endif; ?>

<?php StudioTheme::close(); ?>
<script>
(function () {
    var lengthInput = document.getElementById('length');
    var rangeInput = document.getElementById('page-range');
    var toggleButtons = Array.prototype.slice.call(document.querySelectorAll('.length-toggle button'));
    function syncToggle(pages) {
        toggleButtons.forEach(function (button) {
            button.classList.toggle('active', Number(button.dataset.pages) === Number(pages));
        });
    }
    toggleButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            lengthInput.value = button.dataset.pages;
            rangeInput.value = button.dataset.pages;
            syncToggle(button.dataset.pages);
        });
    });
    rangeInput.addEventListener('input', function () { lengthInput.value = rangeInput.value; syncToggle(rangeInput.value); });
    lengthInput.addEventListener('input', function () { rangeInput.value = lengthInput.value; syncToggle(lengthInput.value); });
    syncToggle(lengthInput.value);

    document.querySelectorAll('.style-option input[type="radio"]').forEach(function (radio) {
        radio.addEventListener('change', function () {
            document.querySelectorAll('.style-option').forEach(function (option) {
                option.classList.toggle('active', option.contains(radio) && radio.checked);
            });
            var option = radio.closest('.style-option');
            document.getElementById('style-agent-name').textContent = option.dataset.agentName;
            document.getElementById('style-agent-mission').textContent = option.dataset.agentMission;
        });
    });

    document.querySelectorAll('.media-option input[type="checkbox"]').forEach(function (checkbox) {
        checkbox.addEventListener('change', function () {
            checkbox.closest('.media-option').classList.toggle('active', checkbox.checked);
        });
    });

    document.getElementById('open-toc-editor').addEventListener('click', function () {
        var editor = document.getElementById('toc-editor');
        editor.open = !editor.open;
        if (editor.open) { editor.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    });
})();
</script>
</body>
</html>
