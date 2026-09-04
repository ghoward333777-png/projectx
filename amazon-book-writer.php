<?php

declare(strict_types=1);

require_once __DIR__ . '/AmazonBookWriter.php';
require_once __DIR__ . '/WordManuscriptExporter.php';
require_once __DIR__ . '/EpubExporter.php';
require_once __DIR__ . '/PrintMediaCompanion.php';
require_once __DIR__ . '/BookProjectStore.php';
require_once __DIR__ . '/StudioTheme.php';

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

$authorVoice = trim((string) ($_POST['author_voice'] ?? $_GET['author_voice'] ?? $_SESSION['book_author_voice'] ?? ''));
$narrativeVoice = trim((string) ($_POST['narrative_voice'] ?? $_GET['narrative_voice'] ?? $_SESSION['book_narrative_voice'] ?? 'third-person'));
if (!isset(ManuscriptDeveloper::NARRATIVE_VOICES[$narrativeVoice])) {
    $narrativeVoice = 'third-person';
}
$rawPerspectives = $_POST['perspectives'] ?? $_GET['perspectives'] ?? $_SESSION['book_perspectives'] ?? [];
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !isset($_POST['perspectives'])) {
    $rawPerspectives = [];
}
$perspectives = array_values(array_filter(
    array_map('strval', is_array($rawPerspectives) ? $rawPerspectives : []),
    static fn (string $factor): bool => isset(ManuscriptDeveloper::PERSPECTIVE_FACTORS[$factor]),
));

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

$extraMedia = [];
$rawExtraMedia = $_POST['extra_media'] ?? $_GET['extra_media'] ?? [];
if (is_array($rawExtraMedia)) {
    foreach ($rawExtraMedia as $chapterNumber => $rows) {
        if (!is_array($rows)) {
            continue;
        }
        foreach ($rows as $row) {
            if (is_array($row) && trim((string) ($row['topic'] ?? '')) !== '') {
                $extraMedia[(int) $chapterNumber][] = [
                    'kind' => (string) ($row['kind'] ?? 'illustration'),
                    'topic' => trim((string) ($row['topic'] ?? '')),
                    'caption' => trim((string) ($row['caption'] ?? '')),
                    'section' => trim((string) ($row['section'] ?? '')),
                ];
            }
        }
    }
}
$newMedia = $_POST['extra_media_new'] ?? [];
if (is_array($newMedia) && trim((string) ($newMedia['topic'] ?? '')) !== '') {
    $extraMedia[(int) ($newMedia['chapter'] ?? 1)][] = [
        'kind' => (string) ($newMedia['kind'] ?? 'illustration'),
        'topic' => trim((string) $newMedia['topic']),
        'caption' => trim((string) ($newMedia['caption'] ?? '')),
        'section' => trim((string) ($newMedia['section'] ?? '')),
    ];
}

$customTocInput = (string) ($_POST['custom_toc'] ?? $_GET['custom_toc'] ?? $_SESSION['book_custom_toc'] ?? '');
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !isset($_POST['custom_toc'])) {
    $customTocInput = '';
}
$customChapters = AmazonBookWriter::parseOutline($customTocInput);

$options = [
    'reader' => $reader,
    'author' => $author,
    'style' => $style,
    'length' => $length,
    'audiobook_provider' => $audiobookProvider,
    'audiobook_voice' => $audiobookVoice,
    'voice_consent' => $voiceConsent,
    'extra_media' => $extraMedia,
    'author_voice' => $authorVoice,
    'narrative_voice' => $narrativeVoice,
    'perspectives' => $perspectives,
];
if ($customChapters !== []) {
    $options['chapters'] = $customChapters;
}
if ($listPriceInput !== '' && is_numeric($listPriceInput)) {
    $options['list_price'] = (float) $listPriceInput;
}
if ($ebookPriceInput !== '' && is_numeric($ebookPriceInput)) {
    $options['ebook_price'] = (float) $ebookPriceInput;
}
if ($hardcoverPriceInput !== '' && is_numeric($hardcoverPriceInput)) {
    $options['hardcover_price'] = (float) $hardcoverPriceInput;
}

// --- First-run AI prose -----------------------------------------------------
// With an AI key configured, the generation run itself develops every chapter
// into finished prose (the browser drives one request per chapter; results are
// held in the session per parameter set and injected into writeBook below).
$aiProvider = null;
foreach (ManuscriptDeveloper::KEY_ENV as $providerName => $envName) {
    if ((string) getenv($envName) !== '') {
        $aiProvider = $providerName;
        break;
    }
}
$paramsHash = md5(json_encode([$topic, $reader, $style, $length, $customTocInput, $authorVoice, $narrativeVoice, $perspectives]));
$aiDeveloped = (array) ($_SESSION['ai_developed'][$paramsHash] ?? []);

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['ai_develop_chapter'])) {
    header('Content-Type: application/json; charset=utf-8');
    try {
        $aiProvider !== null || throw new RuntimeException('No AI key configured on the server.');
        $chapterNumber = max(1, (int) $_POST['ai_develop_chapter']);
        $clean = $writer->writeBook($topic, $options);
        $plan = $writer->manuscriptDeveloper()->developmentPlan($clean['book'], $clean['kdp']['metadata'], $aiProvider);
        $job = null;
        foreach ($plan['writer_jobs'] as $candidate) {
            if ((int) $candidate['chapter'] === $chapterNumber) {
                $job = $candidate;
            }
        }
        $job !== null || throw new RuntimeException('No such chapter: ' . $chapterNumber);
        $text = $writer->manuscriptDeveloper()->developChapterText($aiProvider, $job, (string) getenv(ManuscriptDeveloper::KEY_ENV[$aiProvider]), 2);
        $_SESSION['ai_developed'][$paramsHash][$chapterNumber] = $text;
        preg_match_all('/\S+/u', $text, $m);
        echo json_encode(['ok' => true, 'chapter' => $chapterNumber, 'words' => count($m[0]), 'total' => count($plan['writer_jobs']), 'done' => count((array) $_SESSION['ai_developed'][$paramsHash])]);
    } catch (Throwable $exception) {
        http_response_code(500);
        echo json_encode(['ok' => false, 'error' => $exception->getMessage()]);
    }
    exit;
}

if ($aiDeveloped !== []) {
    $options['developed_chapters'] = $aiDeveloped;
}

$error = null;
$result = null;
$download = trim((string) ($_GET['download'] ?? ''));
$companionBaseUrl = trim((string) ($_POST['companion_url'] ?? $_GET['companion_url'] ?? ''));
$wantsResult = $_SERVER['REQUEST_METHOD'] === 'POST' || $download !== '' || isset($_GET['format']);

if ($wantsResult) {
    try {
        $result = $writer->writeBook($topic, $options);
        $_SESSION['book_topic'] = $topic;
        $_SESSION['book_reader'] = $reader;
        $_SESSION['book_author'] = $author;
        $_SESSION['book_custom_toc'] = $customTocInput;
        $_SESSION['book_author_voice'] = $authorVoice;
        $_SESSION['book_narrative_voice'] = $narrativeVoice;
        $_SESSION['book_perspectives'] = $perspectives;
        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            // Every generation is a project: keep its TOC and manuscript record.
            try {
                $savedProjectId = (new BookProjectStore())->save($topic, $options, $result);
            } catch (Throwable) {
                $savedProjectId = null; // a read-only host must not break generation
            }
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

if ($result !== null && $download === 'manuscript') {
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-kdp-manuscript.html';
    header('Content-Type: text/html; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    $companionPlan = (new PrintMediaCompanion())->companionPlan($result['book'], $result['kdp']['metadata'], $result['media'], $companionBaseUrl);
    echo $writer->exportManuscriptHtml($result['book'], $result['kdp']['metadata'], $result['media'], $companionPlan);
    exit;
}

if ($result !== null && $download === 'epub') {
    $bytes = (new EpubExporter())->export($result['book'], $result['kdp']['metadata'], $result['media']);
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '.epub';
    header('Content-Type: application/epub+zip');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    header('Content-Length: ' . strlen($bytes));
    echo $bytes;
    exit;
}

if ($result !== null && ($download === 'companion' || $download === 'qr-sheet')) {
    $companion = new PrintMediaCompanion();
    if ($download === 'companion') {
        $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-companion.html';
        header('Content-Type: text/html; charset=utf-8');
        header('Content-Disposition: attachment; filename="' . $filename . '"');
        echo $companion->exportCompanionHtml($result['book'], $result['kdp']['metadata'], $result['media'], $companionBaseUrl);
    } else {
        $plan = $companion->companionPlan($result['book'], $result['kdp']['metadata'], $result['media'], $companionBaseUrl);
        $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-qr-sheet.html';
        header('Content-Type: text/html; charset=utf-8');
        header('Content-Disposition: attachment; filename="' . $filename . '"');
        echo $companion->exportQrSheetHtml($plan, $result['kdp']['metadata']);
    }
    exit;
}

if ($result !== null && $download === 'images') {
    $manifest = $writer->illustrationStudio()->imageManifest(
        $result['media'],
        trim((string) ($_GET['image_provider'] ?? 'google')),
    );
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-images-manifest.json';
    header('Content-Type: application/json; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    echo json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

if ($result !== null && $download === 'word') {
    $exporter = new WordManuscriptExporter();
    $bytes = $exporter->export($result['book'], $result['kdp']['metadata'], $result['media']);
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-manuscript.docx';
    header('Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    header('Content-Length: ' . strlen($bytes));
    echo $bytes;
    exit;
}

if ($result !== null && $download === 'drafting-kit') {
    $plan = $writer->manuscriptDeveloper()->developmentPlan($result['book'], $result['kdp']['metadata'], in_array($_GET['ai_provider'] ?? '', ManuscriptDeveloper::PROVIDERS, true) ? (string) $_GET['ai_provider'] : 'anthropic');
    $filename = preg_replace('/[^a-z0-9]+/i', '-', strtolower($topic)) . '-drafting-kit.json';
    header('Content-Type: application/json; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    echo json_encode($plan, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
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
    'companion_url' => $companionBaseUrl,
    'custom_toc' => $customTocInput,
    'author_voice' => $authorVoice,
    'narrative_voice' => $narrativeVoice,
], static fn (string $value): bool => $value !== '') + ($extraMedia !== [] ? ['extra_media' => $extraMedia] : []) + ($perspectives !== [] ? ['perspectives' => $perspectives] : []));
?>
<!doctype html>
<html lang="en">
<head>
    <?php StudioTheme::head('Amazon Book Writer'); ?>
</head>
<body>
<?php StudioTheme::open([
    'active' => 'advanced',
    'current' => 'Amazon packaging',
    'brief' => $topic,
    'progress_label' => 'Write, package, publish',
    'progress_value' => 'Package ready',
    'progress_percent' => 100,
]); ?>

    <div class="page-intro">
        <div>
            <span class="section-label coral">AMAZON BOOK WRITER</span>
            <h1>Write it, package it, publish it on Amazon.</h1>
            <p>Generate the manuscript and a complete Amazon KDP publishing package: listing metadata, keywords, categories, pricing and royalty estimates, and a KDP-ready manuscript export.</p>
        </div>
        <div class="intro-action">
            <a class="outline-button" href="generate-book.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>"><?= StudioTheme::icon('pen', 14) ?> Back to the book generator</a>
            <a class="outline-button" href="book-projects.php"><?= StudioTheme::icon('archive', 14) ?> Book projects</a>
        </div>
    </div>

    <?php if ($error !== null): ?>
        <div class="error"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></div>
    <?php endif; ?>

    <form method="post" class="panel">
        <div class="grid">
            <div>
                <label for="topic">Book topic</label>
                <input id="topic" name="topic" value="<?= htmlspecialchars($topic, ENT_QUOTES, 'UTF-8') ?>" required>
            </div>
            <div>
                <label for="reader">Reader description</label>
                <input id="reader" name="reader" value="<?= htmlspecialchars($reader, ENT_QUOTES, 'UTF-8') ?>" placeholder="e.g. curious practitioners">
            </div>
            <div style="grid-column: 1 / -1;">
                <label for="custom_toc">Your table of contents (optional — one chapter per line; add “| purpose | detail” to steer a chapter; leave empty to let the studio suggest one) <a href="#" id="toc-example" style="color:#ffd9a0; font-weight:400;">insert an example</a></label>
                <textarea id="custom_toc" name="custom_toc" rows="10" autocomplete="off" spellcheck="false" style="width:100%; box-sizing:border-box; resize:vertical; min-height:170px; line-height:1.55;" placeholder="Type or paste your chapters here — one per line."><?= htmlspecialchars($customTocInput, ENT_QUOTES, 'UTF-8') ?></textarea>
                <script>
                    (function () {
                        var box = document.getElementById('custom_toc');
                        var grow = function () { box.style.height = 'auto'; box.style.height = Math.max(170, box.scrollHeight + 4) + 'px'; };
                        box.addEventListener('input', grow);
                        if (box.value.trim() !== '') { grow(); }
                        document.getElementById('toc-example').addEventListener('click', function (e) {
                            e.preventDefault();
                            box.value = '1. Traditional gender relations before WWII\n'
                                + '2. During WWII — women were financially independent for the first time\n'
                                + '3. Families then functioned without a parent at home\n'
                                + '4. The feminist movement discouraged chivalry and manners toward women\n'
                                + '5. Competition between men and women — men retreat from powerful, intelligent women\n'
                                + '6. Fear of being called a harasser has chilled social interaction';
                            grow();
                            box.focus();
                        });
                    })();
                </script>
            </div>
            <div style="grid-column: 1 / -1; border: 1px solid #4a4d61; border-radius: 12px; padding: 14px 16px 6px;">
                <label style="margin-bottom: 10px;">Author's voice &amp; perspective — the AI writer must hold this voice exactly</label>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 0 14px;">
                    <div>
                        <label for="author_voice" style="font-weight: 400;">The author's voice, in your words</label>
                        <input id="author_voice" name="author_voice" value="<?= htmlspecialchars($authorVoice, ENT_QUOTES, 'UTF-8') ?>" placeholder="e.g. a retired engineer in his sixties, plain-spoken, wry, drawing on his own dating years">
                    </div>
                    <div>
                        <label for="narrative_voice" style="font-weight: 400;">Narrative voice (grammatical person)</label>
                        <select id="narrative_voice" name="narrative_voice">
                            <?php foreach (['third-person' => 'Third person (he / she / they)', 'first-person' => 'First person (I)', 'first-person-plural' => 'First person plural (we)', 'second-person' => 'Second person (you)'] as $voiceId => $voiceLabel): ?>
                                <option value="<?= $voiceId ?>" <?= $narrativeVoice === $voiceId ? 'selected' : '' ?>><?= htmlspecialchars($voiceLabel, ENT_QUOTES, 'UTF-8') ?></option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 2px 14px; margin-bottom: 12px;">
                    <?php foreach ([
                        'emotional-testimony' => 'Emotional testimony',
                        'subjective-bias' => 'Openly subjective, argued point of view',
                        'experiential' => 'Experiential — lived experience leads',
                        'objective' => 'Objective and evidence-led',
                        'highly-technical' => 'Highly technical',
                        'detached-observant' => 'Detached and observant',
                    ] as $factorId => $factorLabel): ?>
                        <label style="font-weight: 400; display: flex; gap: 8px; align-items: center; margin-bottom: 4px;">
                            <input type="checkbox" name="perspectives[]" value="<?= $factorId ?>" style="width: auto; margin: 0;" <?= in_array($factorId, $perspectives, true) ? 'checked' : '' ?>>
                            <span><?= htmlspecialchars($factorLabel, ENT_QUOTES, 'UTF-8') ?></span>
                        </label>
                    <?php endforeach; ?>
                </div>
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
            <div>
                <label for="companion_url">Companion page web address (for print QR codes)</label>
                <input id="companion_url" name="companion_url" value="<?= htmlspecialchars($companionBaseUrl, ENT_QUOTES, 'UTF-8') ?>" placeholder="<?= htmlspecialchars(PrintMediaCompanion::DEFAULT_BASE_URL, ENT_QUOTES, 'UTF-8') ?>">
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
        <?php foreach ($extraMedia as $chapterNumber => $rows): ?>
            <?php foreach ($rows as $rowIndex => $row): ?>
                <?php foreach (['kind', 'topic', 'caption', 'section'] as $field): ?>
                    <input type="hidden" name="extra_media[<?= (int) $chapterNumber ?>][<?= (int) $rowIndex ?>][<?= $field ?>]" value="<?= htmlspecialchars((string) ($row[$field] ?? ''), ENT_QUOTES, 'UTF-8') ?>">
                <?php endforeach; ?>
            <?php endforeach; ?>
        <?php endforeach; ?>

        <h2>Add an illustration to a chapter</h2>
        <p class="note">Every chapter already gets figures after its important topics. Use this to add more to a specific chapter or section — it is included when you rebuild.</p>
        <div class="grid">
            <div>
                <label for="extra-chapter">Chapter number</label>
                <input id="extra-chapter" name="extra_media_new[chapter]" type="number" min="1" max="99" placeholder="e.g. 3">
            </div>
            <div>
                <label for="extra-kind">Type</label>
                <select id="extra-kind" name="extra_media_new[kind]">
                    <option value="illustration">Illustration (drawn emblem)</option>
                    <option value="diagram">Diagram (step flow)</option>
                    <option value="chart">Chart (bars)</option>
                    <option value="graph">Graph (line)</option>
                    <option value="table">Table</option>
                    <option value="ai-image">AI image (prompt + manifest)</option>
                </select>
            </div>
            <div>
                <label for="extra-topic">What should it show?</label>
                <input id="extra-topic" name="extra_media_new[topic]" placeholder="e.g. How to compare two job offers">
            </div>
            <div>
                <label for="extra-section">After which section? (optional)</label>
                <input id="extra-section" name="extra_media_new[section]" placeholder="e.g. A practical test">
            </div>
            <div>
                <label for="extra-caption">Caption (optional)</label>
                <input id="extra-caption" name="extra_media_new[caption]" placeholder="Shown under the figure">
            </div>
        </div>
        <button type="submit">Build the Amazon publishing package</button>
    </form>

    <?php if ($result !== null): ?>
        <?php $kdp = $result['kdp']; $meta = $kdp['metadata']; $book = $result['book']; $outlineReview = $result['outline_review'] ?? null; ?>
        <?php if (($savedProjectId ?? null) !== null): ?>
            <p class="note">💾 Project saved — the table of contents and full manuscript are on record as <strong><?= htmlspecialchars((string) $savedProjectId, ENT_QUOTES, 'UTF-8') ?></strong>. Find every book on the <a href="book-projects.php">Book projects</a> page.</p>
        <?php endif; ?>

        <?php $chapterTotal = count((array) $book['chapters']); $developedCount = count($aiDeveloped); ?>
        <?php if ($aiProvider !== null && $developedCount >= $chapterTotal && $chapterTotal > 0): ?>
            <p class="note">✍️ <strong>AI-developed prose</strong> — all <?= $chapterTotal ?> chapters were written by the AI writer (<?= htmlspecialchars($aiProvider, ENT_QUOTES, 'UTF-8') ?>) on this run. Every export below carries the finished book text.</p>
        <?php elseif ($aiProvider !== null): ?>
            <section id="ai-progress-panel">
                <div class="eyebrow">First-run AI prose</div>
                <h2 id="ai-progress-title">Writing the book…</h2>
                <p class="note" id="ai-progress-note">The outline below is ready. The AI writer (<?= htmlspecialchars($aiProvider, ENT_QUOTES, 'UTF-8') ?>) is now developing each chapter's draft directions into finished prose — the page refreshes with the complete book when it's done.</p>
                <p id="ai-progress" style="font-weight:700">Starting…</p>
                <button type="button" id="ai-stop" style="background:#3a2a2a;border:1px solid #5a3a3a;color:#f0c0c0;border-radius:9px;padding:8px 14px;cursor:pointer">Stop (keep chapters written so far)</button>
            </section>
            <script>
                (function () {
                    var total = <?= (int) $chapterTotal ?>;
                    var done = <?= (int) $developedCount ?>;
                    var words = 0;
                    var stopped = false;
                    var form = document.querySelector('form');
                    document.getElementById('ai-stop').addEventListener('click', function () { stopped = true; this.disabled = true; });
                    function finish() {
                        document.getElementById('ai-progress').textContent = 'Applying the developed prose…';
                        form.requestSubmit ? form.requestSubmit() : form.submit();
                    }
                    function next(chapter) {
                        if (stopped || chapter > total) { finish(); return; }
                        document.getElementById('ai-progress').textContent = 'Writing chapter ' + chapter + ' of ' + total + '…' + (words ? ' (' + words.toLocaleString() + ' words so far)' : '');
                        var data = new FormData(form);
                        data.set('ai_develop_chapter', String(chapter));
                        fetch('amazon-book-writer.php', { method: 'POST', body: data })
                            .then(function (r) { return r.json(); })
                            .then(function (info) {
                                if (!info.ok) { throw new Error(info.error || 'development failed'); }
                                words += info.words | 0;
                                done = info.done | 0;
                                next(chapter + 1);
                            })
                            .catch(function (e) {
                                document.getElementById('ai-progress').textContent = 'Stopped at chapter ' + chapter + ': ' + e.message + ' — chapters already written are kept; regenerate to continue.';
                                document.getElementById('ai-stop').disabled = true;
                            });
                    }
                    next(done + 1);
                })();
            </script>
        <?php else: ?>
            <p class="note">✍️ Want finished prose on the first run? Configure an AI key on the server (<?= htmlspecialchars(implode(', ', ManuscriptDeveloper::KEY_ENV), ENT_QUOTES, 'UTF-8') ?>) and the generate button will write every chapter automatically — or run <code>php bin/develop-manuscript.php</code>, or use the AI drafting kit download below.</p>
        <?php endif; ?>

        <?php if ($outlineReview !== null): ?>
        <section>
            <div class="eyebrow">Outline review · <?= htmlspecialchars((string) $outlineReview['agent']['name'], ENT_QUOTES, 'UTF-8') ?></div>
            <h2><?= (int) $outlineReview['score'] ?>/100 · <?= htmlspecialchars((string) $outlineReview['verdict'], ENT_QUOTES, 'UTF-8') ?></h2>
            <p class="note"><?= htmlspecialchars((string) $outlineReview['agent']['mission'], ENT_QUOTES, 'UTF-8') ?> Reviewed <?= (int) $outlineReview['chapter_count'] ?> chapters as a <?= htmlspecialchars((string) $outlineReview['genre'], ENT_QUOTES, 'UTF-8') ?> book.</p>
            <ul>
                <?php foreach ((array) $outlineReview['checks'] as $check): ?>
                    <li><?= $check['passed'] ? '✅' : '⚠️' ?> <?= htmlspecialchars((string) $check['label'], ENT_QUOTES, 'UTF-8') ?></li>
                <?php endforeach; ?>
            </ul>
            <?php if ((array) $outlineReview['suggestions'] !== []): ?>
                <h3>Editor's suggestions</h3>
                <ul>
                    <?php foreach ((array) $outlineReview['suggestions'] as $suggestion): ?>
                        <li><?= htmlspecialchars((string) $suggestion, ENT_QUOTES, 'UTF-8') ?></li>
                    <?php endforeach; ?>
                </ul>
            <?php endif; ?>
        </section>
        <?php endif; ?>
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

        <?php $companionPlanView = (new PrintMediaCompanion())->companionPlan($book, $meta, $result['media'] ?? null, $companionBaseUrl); ?>
        <section>
            <div class="eyebrow">Print media companion · QR-linked</div>
            <p class="note">Print can't play audio or show color media — so every chapter of the print edition gets a QR code pointing readers to your companion web page. Set the web address above (currently <strong style="color:#ffd9a0;"><?= htmlspecialchars($companionPlanView['base_url'], ENT_QUOTES, 'UTF-8') ?></strong>), download the companion page below, upload it there, and print the QR sheet or use the QR codes already embedded in the HTML manuscript export.</p>
            <div class="grid">
                <div style="background:#f8f4eb;border-radius:10px;padding:14px;text-align:center;color:#202431;">
                    <?= $companionPlanView['master']['qr_svg'] ?>
                    <div style="font-size:12px;font-weight:700;">Whole book</div>
                    <div style="font-size:10px;color:#5a6070;word-break:break-all;"><?= htmlspecialchars($companionPlanView['master']['url'], ENT_QUOTES, 'UTF-8') ?></div>
                </div>
                <?php foreach (array_slice($companionPlanView['chapters'], 0, 3) as $entry): ?>
                    <div style="background:#f8f4eb;border-radius:10px;padding:14px;text-align:center;color:#202431;">
                        <?= $entry['qr_svg'] ?>
                        <div style="font-size:12px;font-weight:700;">Ch. <?= (int) $entry['chapter'] ?> · <?= (int) $entry['figure_count'] ?> figures</div>
                        <div style="font-size:10px;color:#5a6070;word-break:break-all;"><?= htmlspecialchars($entry['url'], ENT_QUOTES, 'UTF-8') ?></div>
                    </div>
                <?php endforeach; ?>
            </div>
            <p class="note">All <?= count($companionPlanView['chapters']) ?> chapter codes are on the downloadable QR sheet. The QR codes are generated by the app itself — scannable with any phone camera.</p>
        </section>

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
                <a class="primary" href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=epub">Download eBook (.epub)</a>
                <a class="primary" href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=drafting-kit">Download AI drafting kit (.json)</a>
                <a class="primary" href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=manuscript">Download KDP manuscript (.html)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=metadata">Download KDP metadata (.json)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=narration">Download narration script (.txt)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=manifest">Download audiobook manifest (.json)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=images&amp;image_provider=google">Download AI-image manifest (.json)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=companion">Download companion page (.html)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;download=qr-sheet">Download QR sheet (.html)</a>
                <a href="amazon-book-writer.php?<?= htmlspecialchars($downloadQuery, ENT_QUOTES, 'UTF-8') ?>&amp;format=json">View package as JSON</a>
            </div>
            <p class="note">Want to edit the table of contents or page design first? Draft in <a href="generate-book.php?topic=<?= urlencode($topic) ?>&amp;reader=<?= urlencode($reader) ?>">the book generator</a>, then come back here to package it.</p>
        </section>

        <?php $media = $result['media'] ?? ['chapters' => [], 'figure_count' => 0, 'ai_image_count' => 0]; ?>
        <section>
            <div class="eyebrow">Figures &amp; illustrations · <?= (int) $media['figure_count'] ?> figures · <?= (int) $media['ai_image_count'] ?> AI images planned</div>
            <p class="note">Every chapter gets a figure after each important topic: diagrams, charts, graphs, tables, and illustrations render instantly; AI images ship as prompts in the manifest below and are generated locally with <code style="color:#ffd9a0">php bin/generate-images.php --manifest &lt;file&gt; --out images/</code> using your Google, OpenAI, or Stability key. Use “Add an illustration” above to give any chapter or section more.</p>
            <?php foreach ((array) $media['chapters'] as $mediaChapter): ?>
                <details class="job-catalog" <?= !empty(array_filter((array) $mediaChapter['items'], static fn (array $i): bool => !empty($i['user_added']))) ? 'open' : '' ?>>
                    <summary>Chapter <?= (int) $mediaChapter['number'] ?>: <?= htmlspecialchars((string) $mediaChapter['title'], ENT_QUOTES, 'UTF-8') ?> · <?= count((array) $mediaChapter['items']) ?> figures</summary>
                    <div style="padding: 0 14px 14px;">
                        <?php foreach ((array) $mediaChapter['items'] as $item): ?>
                            <div style="margin-top: 14px; background: #f8f4eb; border-radius: 10px; padding: 16px 18px; color: #202431;">
                                <div style="font: 11px/1.4 ui-monospace, monospace; letter-spacing: .08em; text-transform: uppercase; color: #5a6070;">
                                    <?= htmlspecialchars((string) $item['kind'], ENT_QUOTES, 'UTF-8') ?> · after “<?= htmlspecialchars((string) $item['after_section'], ENT_QUOTES, 'UTF-8') ?>”<?= !empty($item['user_added']) ? ' · added by you' : '' ?>
                                </div>
                                <?php if (isset($item['svg'])): ?>
                                    <?= $item['svg'] ?>
                                <?php elseif (isset($item['table'])): ?>
                                    <div style="overflow-x: auto;"><table style="border-collapse: collapse; width: 100%; font-size: 12px;"><thead><tr>
                                        <?php foreach ((array) $item['table']['columns'] as $column): ?><th style="border: 1px solid #b9b2a2; padding: 5px 8px; text-align: left;"><?= htmlspecialchars((string) $column, ENT_QUOTES, 'UTF-8') ?></th><?php endforeach; ?>
                                    </tr></thead><tbody>
                                        <?php foreach ((array) $item['table']['rows'] as $row): ?><tr><?php foreach ($row as $cell): ?><td style="border: 1px solid #cfc8b8; padding: 5px 8px; vertical-align: top;"><?= htmlspecialchars((string) $cell, ENT_QUOTES, 'UTF-8') ?></td><?php endforeach; ?></tr><?php endforeach; ?>
                                    </tbody></table></div>
                                <?php endif; ?>
                                <div style="font-size: 12px; font-style: italic; margin-top: 8px;"><?= htmlspecialchars((string) $item['title'], ENT_QUOTES, 'UTF-8') ?> — <?= htmlspecialchars((string) $item['caption'], ENT_QUOTES, 'UTF-8') ?></div>
                                <?php if (isset($item['ai']['prompt'])): ?>
                                    <div style="font-size: 11px; margin-top: 6px; color: #5a6070;"><b>Prompt:</b> <?= htmlspecialchars((string) $item['ai']['prompt'], ENT_QUOTES, 'UTF-8') ?></div>
                                <?php endif; ?>
                            </div>
                        <?php endforeach; ?>
                    </div>
                </details>
            <?php endforeach; ?>
        </section>

        <section>
            <div class="eyebrow">Manuscript preview · <?= count((array) $book['chapters']) ?> chapters</div>
            <?php if ($aiProvider !== null && $developedCount >= $chapterTotal && $chapterTotal > 0): ?>
                <p class="note" style="color: #7ee2a8;">✅ Finished prose — every chapter below was written by the AI writer under the voice contract.</p>
            <?php elseif ($aiProvider !== null): ?>
                <div class="error" style="background: #3a2f16; border-color: #7a6337; color: #ffd9a0;">✍️ The AI writer is producing the finished prose now (<?= (int) $developedCount ?> of <?= (int) $chapterTotal ?> chapters done) — the chapters below are still the development plan until the page refreshes with the complete book. Don't export yet.</div>
            <?php else: ?>
                <div class="error">⚠️ What follows is the DEVELOPMENT PLAN — draft directions addressed to a writer, NOT book text, and downloads made now would carry it. Configure an AI key on the server (or run <code>php bin/develop-manuscript.php</code>) and generate again to get the finished book on the first run.</div>
            <?php endif; ?>
            <ul>
                <?php foreach ((array) $book['table_of_contents'] as $entry): ?>
                    <li><strong><?= (int) $entry['number'] ?>. <?= htmlspecialchars((string) $entry['title'], ENT_QUOTES, 'UTF-8') ?></strong> — <?= (int) $entry['page_count'] ?> planned pages</li>
                <?php endforeach; ?>
            </ul>
        </section>
    <?php endif; ?>
<?php StudioTheme::close(); ?>
</body>
</html>
