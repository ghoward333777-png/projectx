<?php

declare(strict_types=1);

require_once __DIR__ . '/AmazonBookWriter.php';
require_once __DIR__ . '/WordManuscriptExporter.php';

session_start();

$writer = new AmazonBookWriter();
$engine = $writer->engine();

$topic = trim((string) ($_POST['topic'] ?? $_GET['topic'] ?? $_SESSION['book_topic'] ?? 'Jobs and work for teens'));
$reader = trim((string) ($_POST['reader'] ?? $_GET['reader'] ?? $_SESSION['book_reader'] ?? 'teens exploring a first job while balancing school, safety, and real life'));
$author = trim((string) ($_POST['author'] ?? $_GET['author'] ?? $_SESSION['book_author'] ?? ''));
$style = trim((string) ($_POST['style'] ?? $_GET['style'] ?? 'conversational'));
$length = trim((string) ($_POST['length'] ?? $_GET['length'] ?? 'standard'));
$listPriceInput = trim((string) ($_POST['list_price'] ?? $_GET['list_price'] ?? ''));
$ebookPriceInput = trim((string) ($_POST['ebook_price'] ?? $_GET['ebook_price'] ?? ''));
$hardcoverPriceInput = trim((string) ($_POST['hardcover_price'] ?? $_GET['hardcover_price'] ?? ''));
$audiobookProvider = trim((string) ($_POST['audiobook_provider'] ?? $_GET['audiobook_provider'] ?? 'google'));
$voiceName = trim((string) ($_POST['voice_name'] ?? $_GET['voice_name'] ?? ''));
$cloneSamplePath = trim((string) ($_POST['clone_sample'] ?? $_GET['clone_sample'] ?? ''));
$voiceConsent = (bool) ($_POST['voice_consent'] ?? $_GET['voice_consent'] ?? false);

$audiobookVoice = [];
if ($audiobookProvider === 'google' && $voiceName !== '') {
    $audiobookVoice['voice_name'] = $voiceName;
}
if ($audiobookProvider === 'elevenlabs') {
    if ($voiceName !== '') {
        $audiobookVoice['voice_id'] = $voiceName;
    }
    if ($cloneSamplePath !== '') {
        $audiobookVoice['clone_sample_path'] = $cloneSamplePath;
        $audiobookVoice['cloned_from_sample'] = true;
    }
}
if ($audiobookProvider === 'local-clone' && $cloneSamplePath !== '') {
    $audiobookVoice['sample_path'] = $cloneSamplePath;
}

$options = [
    'reader' => $reader,
    'author' => $author,
    'style' => $style,
    'length' => $length,
    'audiobook_provider' => $audiobookProvider,
    'audiobook_voice' => $audiobookVoice,
    'voice_consent' => $voiceConsent,
];
if ($listPriceInput !== '' && is_numeric($listPriceInput)) {
    $options['list_price'] = (float) $listPriceInput;
}
if ($ebookPriceInput !== '' && is_numeric($ebookPriceInput)) {
    $options['ebook_price'] = (float) $ebookPriceInput;
}
if ($hardcoverPriceInput !== '' && is_numeric($hardcoverPriceInput)) {
    $options['hardcover_price'] = (float) $hardcoverPriceInput;
}

$error = null;
$result = null;
$download = trim((string) ($_GET['download'] ?? ''));
$wantsResult = $_SERVER['REQUEST_METHOD'] === 'POST' || $download !== '' || isset($_GET['format']);

if ($wantsResult) {
    try {
        $result = $writer->writeBook($topic, $options);
        $_SESSION['book_topic'] = $topic;
        $_SESSION['book_reader'] = $reader;
        $_SESSION['book_author'] = $author;
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

if ($result !== null && $download === 'manuscript') {
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-kdp-manuscript.html';
    header('Content-Type: text/html; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    echo $writer->exportManuscriptHtml($result['book'], $result['kdp']['metadata']);
    exit;
}

if ($result !== null && $download === 'word') {
    $exporter = new WordManuscriptExporter();
    $bytes = $exporter->export($result['book'], $result['kdp']['metadata']);
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-manuscript.docx';
    header('Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    header('Content-Length: ' . strlen($bytes));
    echo $bytes;
    exit;
}

if ($result !== null && $download === 'narration') {
    $producer = $writer->audiobookProducer();
    $script = $producer->narrationScript($result['book'], $result['kdp']['metadata']);
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-narration-script.txt';
    header('Content-Type: text/plain; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    echo $producer->narrationScriptText($script);
    exit;
}

if ($result !== null && $download === 'manifest') {
    try {
        $manifest = $writer->audiobookProducer()->synthesisManifest(
            $result['book'],
            $result['kdp']['metadata'],
            $audiobookProvider,
            ['voice' => $audiobookVoice, 'voice_consent' => $voiceConsent],
        );
        $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-audiobook-manifest.json';
        header('Content-Type: application/json; charset=utf-8');
        header('Content-Disposition: attachment; filename="' . $filename . '"');
        echo json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        exit;
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

if ($result !== null && $download === 'metadata') {
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-kdp-metadata.json';
    header('Content-Type: application/json; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    echo json_encode($writer->exportMetadata($result['kdp']), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

if ($result !== null && ($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'topic' => $topic,
        'kdp' => $result['kdp'],
        'book_summary' => [
            'style' => $result['book']['style_label'],
            'page_count' => $result['book']['page_count'],
            'total_word_count' => $result['book']['total_word_count'],
            'chapters' => count($result['book']['chapters']),
        ],
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

$styles = $engine->writingStyles();
$downloadQuery = http_build_query(array_filter([
    'topic' => $topic,
    'reader' => $reader,
    'author' => $author,
    'style' => $style,
    'length' => $length,
    'list_price' => $listPriceInput,
    'ebook_price' => $ebookPriceInput,
    'hardcover_price' => $hardcoverPriceInput,
    'audiobook_provider' => $audiobookProvider,
    'voice_name' => $voiceName,
    'clone_sample' => $cloneSamplePath,
    'voice_consent' => $voiceConsent ? '1' : '',
], static fn (string $value): bool => $value !== ''));
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Amazon Book Writer · Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #11141c; color: #eef0f6; }
        body { margin: 0; background: radial-gradient(circle at top right, #3b2a10, #11141c 42%); min-height: 100vh; }
        main { max-width: 1100px; margin: 0 auto; padding: 42px 24px 80px; }
        header { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; border-bottom: 1px solid #36384a; padding-bottom: 30px; }
        .eyebrow { color: #ffb84d; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(38px, 7vw, 68px); line-height: .96; max-width: 720px; margin: 14px 0; letter-spacing: -.06em; }
        h2, h3 { letter-spacing: -.035em; }
        p { color: #aeb2c2; line-height: 1.6; }
        a { color: #ffd9a0; }
        form, section { background: #1a1d28; border: 1px solid #343747; border-radius: 18px; padding: 24px; margin-top: 18px; }
        label { display: block; color: #dfe2eb; font-size: 12px; font-weight: 700; margin-bottom: 8px; }
        input, select { box-sizing: border-box; width: 100%; background: #10121a; border: 1px solid #4a4d61; border-radius: 9px; color: #fff; padding: 12px 13px; font: inherit; margin-bottom: 15px; }
        button { border: 0; border-radius: 999px; background: #ffb84d; color: #241a08; padding: 12px 18px; font: inherit; font-weight: 800; cursor: pointer; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
        .metric { background: #222534; border-radius: 14px; padding: 18px; }
        .metric strong { display: block; font-size: 26px; color: #fff; }
        .metric span { color: #b2b5c3; font-size: 12px; line-height: 1.4; }
        .keyword { display: inline-block; background: #2c2416; border: 1px solid #5a4a26; border-radius: 999px; color: #ffd9a0; padding: 6px 12px; margin: 0 6px 8px 0; font-size: 12px; }
        .description-preview { background: #f8f4eb; color: #202431; border-radius: 10px; padding: 20px 24px; font-family: Georgia, serif; white-space: pre-wrap; line-height: 1.55; }
        .check { border-top: 1px solid #36384a; padding: 13px 0; display: grid; grid-template-columns: 130px 1fr; gap: 14px; }
        .check:first-of-type { border-top: 0; }
        .status { font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
        .status.ready { color: #7ee2a8; }
        .status.action { color: #ffb84d; }
        .status.pending { color: #8d91a3; }
        .check p { margin: 4px 0 0; font-size: 13px; }
        .downloads { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; }
        .downloads a { display: inline-block; border-radius: 999px; background: #292d3d; color: #e9e6f4; padding: 12px 18px; font-weight: 800; text-decoration: none; }
        .downloads a.primary { background: #ffb84d; color: #241a08; }
        ul { color: #c8cad5; line-height: 1.8; padding-left: 20px; }
        .error { color: #ff9cba; background: #3c1f32; border: 1px solid #7a3755; padding: 14px; border-radius: 10px; margin-top: 18px; }
        .note { color: #8d91a3; font-size: 12px; }
        @media (max-width: 700px) { header { display: block; } main { padding: 28px 16px 60px; } form, section { padding: 18px; } .check { grid-template-columns: 1fr; gap: 4px; } }
    </style>
</head>
<body>
<main>
    <header>
        <div>
            <div class="eyebrow">Book Intelligence Studio · Amazon Book Writer</div>
            <h1>Write it, package it, publish it on Amazon.</h1>
            <p>Generate the manuscript and a complete Amazon KDP publishing package: listing metadata, keywords, categories, pricing and royalty estimates, and a KDP-ready manuscript export.</p>
        </div>
        <a href="index.php">← Back to intelligence kit</a>
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
                <label for="author">Author name (as it appears on Amazon)</label>
                <input id="author" name="author" value="<?= htmlspecialchars($author, ENT_QUOTES, 'UTF-8') ?>" placeholder="e.g. Garry S. Howard">
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
                <label for="length">Draft length · pages (or short / standard / expanded)</label>
                <input id="length" name="length" value="<?= htmlspecialchars($length, ENT_QUOTES, 'UTF-8') ?>">
            </div>
            <div>
                <label for="list_price">Paperback list price · USD (optional)</label>
                <input id="list_price" name="list_price" type="number" step="0.01" min="0" value="<?= htmlspecialchars($listPriceInput, ENT_QUOTES, 'UTF-8') ?>" placeholder="Leave blank for a suggestion">
            </div>
            <div>
                <label for="ebook_price">Kindle price · USD (optional)</label>
                <input id="ebook_price" name="ebook_price" type="number" step="0.01" min="0" value="<?= htmlspecialchars($ebookPriceInput, ENT_QUOTES, 'UTF-8') ?>" placeholder="Leave blank for a suggestion">
            </div>
            <div>
                <label for="hardcover_price">Hardcover price · USD (optional)</label>
                <input id="hardcover_price" name="hardcover_price" type="number" step="0.01" min="0" value="<?= htmlspecialchars($hardcoverPriceInput, ENT_QUOTES, 'UTF-8') ?>" placeholder="Leave blank for a suggestion">
            </div>
        </div>

        <h2>Audiobook narration</h2>
        <div class="grid">
            <div>
                <label for="audiobook_provider">Voice provider</label>
                <select id="audiobook_provider" name="audiobook_provider">
                    <option value="google" <?= $audiobookProvider === 'google' ? 'selected' : '' ?>>Google Cloud Text-to-Speech</option>
                    <option value="elevenlabs" <?= $audiobookProvider === 'elevenlabs' ? 'selected' : '' ?>>ElevenLabs</option>
                    <option value="local-clone" <?= $audiobookProvider === 'local-clone' ? 'selected' : '' ?>>Internal voice clone (sampled recording)</option>
                </select>
            </div>
            <div>
                <label for="voice_name">Voice name / voice ID (optional)</label>
                <input id="voice_name" name="voice_name" value="<?= htmlspecialchars($voiceName, ENT_QUOTES, 'UTF-8') ?>" placeholder="e.g. en-US-Neural2-D or an ElevenLabs voice_id">
            </div>
            <div>
                <label for="clone_sample">Voice sample recording · path (for cloning)</label>
                <input id="clone_sample" name="clone_sample" value="<?= htmlspecialchars($cloneSamplePath, ENT_QUOTES, 'UTF-8') ?>" placeholder="e.g. samples/narrator.wav">
            </div>
            <div>
                <label for="voice_consent">Cloning consent</label>
                <label style="font-weight:400"><input type="hidden" name="voice_consent" value="0"><input id="voice_consent" type="checkbox" name="voice_consent" value="1" <?= $voiceConsent ? 'checked' : '' ?>> The recorded speaker has given explicit consent to clone their voice</label>
                <div class="note">Required before any cloning job is generated. Not needed for stock Google or ElevenLabs voices.</div>
            </div>
        </div>
        <button type="submit">Build the Amazon publishing package</button>
    </form>

    <?php if ($result !== null): ?>
        <?php $kdp = $result['kdp']; $meta = $kdp['metadata']; $book = $result['book']; ?>
        <section>
            <div class="eyebrow">Amazon listing metadata</div>
            <h2><?= htmlspecialchars($meta['title'], ENT_QUOTES, 'UTF-8') ?></h2>
            <?php if (($meta['subtitle'] ?? '') !== ''): ?>
                <p><em><?= htmlspecialchars($meta['subtitle'], ENT_QUOTES, 'UTF-8') ?></em></p>
            <?php endif; ?>
            <p>By <strong><?= htmlspecialchars($meta['author'], ENT_QUOTES, 'UTF-8') ?></strong> · <?= htmlspecialchars($meta['language'], ENT_QUOTES, 'UTF-8') ?> · <?= htmlspecialchars($book['style_label'], ENT_QUOTES, 'UTF-8') ?> voice</p>
            <h3>Book description · <?= number_format(mb_strlen((string) $meta['description'])) ?> / <?= number_format(AmazonBookWriter::MAX_DESCRIPTION_LENGTH) ?> characters</h3>
            <div class="description-preview"><?= htmlspecialchars((string) $meta['description'], ENT_QUOTES, 'UTF-8') ?></div>
            <h3>Backend search keywords · <?= count((array) $meta['keywords']) ?> of <?= AmazonBookWriter::KEYWORD_SLOTS ?> slots</h3>
            <div>
                <?php foreach ((array) $meta['keywords'] as $keyword): ?>
                    <span class="keyword"><?= htmlspecialchars((string) $keyword, ENT_QUOTES, 'UTF-8') ?></span>
                <?php endforeach; ?>
            </div>
            <h3>Suggested browse categories</h3>
            <ul>
                <?php foreach ((array) $meta['categories'] as $category): ?>
                    <li><?= htmlspecialchars((string) $category, ENT_QUOTES, 'UTF-8') ?></li>
                <?php endforeach; ?>
            </ul>
        </section>

        <section>
            <div class="eyebrow">Print & pricing estimates</div>
            <div class="grid">
                <div class="metric"><strong><?= htmlspecialchars((string) $kdp['manuscript']['trim_size'], ENT_QUOTES, 'UTF-8') ?></strong><span>Trim size · <?= htmlspecialchars((string) $kdp['manuscript']['interior'], ENT_QUOTES, 'UTF-8') ?></span></div>
                <div class="metric"><strong><?= number_format((int) $kdp['manuscript']['kdp_page_estimate']) ?> pages</strong><span><?= number_format((int) $kdp['manuscript']['total_word_count']) ?> words incl. front & back matter</span></div>
                <div class="metric"><strong>$<?= number_format((float) $kdp['paperback']['printing_cost'], 2) ?></strong><span>Estimated printing cost per paperback</span></div>
                <div class="metric"><strong>$<?= number_format((float) $kdp['paperback']['list_price'], 2) ?></strong><span>Paperback list price (min $<?= number_format((float) $kdp['paperback']['minimum_list_price'], 2) ?>)</span></div>
                <div class="metric"><strong>$<?= number_format((float) $kdp['paperback']['royalty_per_copy'], 2) ?></strong><span>Paperback royalty per copy · <?= htmlspecialchars((string) $kdp['paperback']['formula'], ENT_QUOTES, 'UTF-8') ?></span></div>
                <div class="metric"><strong>$<?= number_format((float) $kdp['ebook']['price'], 2) ?></strong><span>Kindle price · <?= htmlspecialchars((string) $kdp['ebook']['royalty_plan'], ENT_QUOTES, 'UTF-8') ?></span></div>
                <div class="metric"><strong>$<?= number_format((float) $kdp['ebook']['royalty_per_copy'], 2) ?></strong><span>Kindle royalty per copy · <?= htmlspecialchars((string) $kdp['ebook']['formula'], ENT_QUOTES, 'UTF-8') ?></span></div>
            </div>
            <p class="note"><?= htmlspecialchars((string) $kdp['manuscript']['page_count_notes'], ENT_QUOTES, 'UTF-8') ?></p>
            <p class="note"><?= htmlspecialchars((string) $kdp['disclaimer'], ENT_QUOTES, 'UTF-8') ?></p>
        </section>

        <section>
            <div class="eyebrow">Editions</div>
            <div class="grid">
                <?php foreach ((array) ($kdp['editions'] ?? []) as $edition): ?>
                    <div class="metric">
                        <strong><?= htmlspecialchars((string) $edition['label'], ENT_QUOTES, 'UTF-8') ?> · $<?= number_format((float) $edition['price'], 2) ?></strong>
                        <span><?= htmlspecialchars((string) $edition['channel'], ENT_QUOTES, 'UTF-8') ?></span>
                        <span>≈ $<?= number_format((float) $edition['royalty_per_copy'], 2) ?>/copy · <?= htmlspecialchars((string) $edition['royalty_plan'], ENT_QUOTES, 'UTF-8') ?></span>
                        <span><?= htmlspecialchars((string) $edition['deliverable'], ENT_QUOTES, 'UTF-8') ?></span>
                    </div>
                <?php endforeach; ?>
            </div>
        </section>

        <?php $ab = $kdp['audiobook'] ?? null; ?>
        <?php if ($ab !== null): ?>
        <section>
            <div class="eyebrow">Audiobook studio</div>
            <div class="grid">
                <div class="metric"><strong><?= number_format((float) $ab['runtime_estimate_hours'], 1) ?> hours</strong><span>Estimated finished runtime at ~<?= number_format(AudiobookProducer::WORDS_PER_FINISHED_HOUR) ?> words/hour</span></div>
                <div class="metric"><strong><?= number_format((int) $ab['chunk_count']) ?> chunks</strong><span><?= number_format((int) $ab['total_char_count']) ?> characters, ≤ <?= number_format((int) $ab['chunk_char_limit']) ?> chars per request</span></div>
                <div class="metric"><strong>$<?= number_format((float) $ab['estimated_synthesis_cost_usd'], 2) ?></strong><span>Estimated synthesis cost · <?= htmlspecialchars((string) $ab['provider_label'], ENT_QUOTES, 'UTF-8') ?></span></div>
                <div class="metric"><strong>$<?= number_format((float) $ab['suggested_retail']['suggested_price'], 2) ?></strong><span>Suggested retail (<?= htmlspecialchars((string) $ab['suggested_retail']['band'], ENT_QUOTES, 'UTF-8') ?> band) · <?= htmlspecialchars((string) $ab['suggested_retail']['royalty_note'], ENT_QUOTES, 'UTF-8') ?></span></div>
            </div>
            <p class="note"><strong>Voice cloning consent:</strong> <?= htmlspecialchars((string) $ab['clone_consent']['status'], ENT_QUOTES, 'UTF-8') ?></p>
            <h3>Production workflow</h3>
            <ul>
                <?php foreach ((array) $ab['workflow'] as $step): ?>
                    <li><?= htmlspecialchars((string) $step, ENT_QUOTES, 'UTF-8') ?></li>
                <?php endforeach; ?>
            </ul>
            <h3>ACX / Audible delivery specs</h3>
            <ul>
                <?php foreach ((array) $ab['acx_specs'] as $spec): ?>
                    <li><?= htmlspecialchars((string) $spec, ENT_QUOTES, 'UTF-8') ?></li>
                <?php endforeach; ?>
            </ul>
            <p class="note">Synthesis runs locally via <code style="color:#ffd9a0">php bin/synthesize-audiobook.php --manifest &lt;file&gt; --out audio/</code> with your own Google or ElevenLabs API key, or your internal cloning engine via <code style="color:#ffd9a0">--engine-cmd</code>. One-time ElevenLabs cloning: <code style="color:#ffd9a0">--clone-name "My Voice" --clone-sample narrator.wav --consent</code>.</p>
        </section>
        <?php endif; ?>

        <section>
            <div class="eyebrow">Publishing checklist</div>
            <?php foreach ((array) $kdp['checklist'] as $item): ?>
                <?php $statusClass = $item['status'] === 'Ready' ? 'ready' : ($item['status'] === 'Pending' ? 'pending' : 'action'); ?>
                <div class="check">
                    <span class="status <?= $statusClass ?>"><?= htmlspecialchars((string) $item['status'], ENT_QUOTES, 'UTF-8') ?></span>
                    <div><strong><?= htmlspecialchars((string) $item['step'], ENT_QUOTES, 'UTF-8') ?></strong><p><?= htmlspecialchars((string) $item['detail'], ENT_QUOTES, 'UTF-8') ?></p></div>
                </div>
            <?php endforeach; ?>
        </section>

        <section>
            <div class="eyebrow">Exports</div>
            <h3>Download the KDP upload files</h3>
            <p>The manuscript export is a clean single-file HTML document that Kindle Create and Word open directly; the metadata export mirrors the KDP setup screens for copy-paste.</p>
            <div class="downloads">
                <a class="primary" href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=word">Download Word manuscript (.docx)</a>
                <a class="primary" href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=manuscript">Download KDP manuscript (.html)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=metadata">Download KDP metadata (.json)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=narration">Download narration script (.txt)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=manifest">Download audiobook manifest (.json)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;format=json">View package as JSON</a>
            </div>
            <p class="note">Want to edit the table of contents or page design first? Draft in <a href="generate-book.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>">the book generator</a>, then come back here to package it.</p>
        </section>

        <section>
            <div class="eyebrow">Manuscript preview · <?= count((array) $book['chapters']) ?> chapters</div>
            <ul>
                <?php foreach ((array) $book['table_of_contents'] as $entry): ?>
                    <li><strong><?= (int) $entry['number'] ?>. <?= htmlspecialchars((string) $entry['title'], ENT_QUOTES, 'UTF-8') ?></strong> — <?= (int) $entry['page_count'] ?> planned pages</li>
                <?php endforeach; ?>
            </ul>
        </section>
    <?php endif; ?>
</main>
</body>
</html>
