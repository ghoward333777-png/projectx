<?php

declare(strict_types=1);

require_once __DIR__ . '/StockMediaHarvester.php';
require_once __DIR__ . '/MediaAnalyzer.php';
require_once __DIR__ . '/QueryBook.php';

$store = new MediaGraphStore();
$engine = new FqlEngine($store);
$querybook = new QueryBook($engine);
$harvester = new StockMediaHarvester();
$analyzer = new MediaAnalyzer();
$e = static fn (string $value): string => htmlspecialchars($value, ENT_QUOTES, 'UTF-8');

$message = null;
$error = null;
$action = (string) ($_POST['action'] ?? '');
try {
    if ($action === 'harvest') {
        $source = (string) ($_POST['source'] ?? '');
        $sources = $source === 'all' ? array_keys(StockMediaHarvester::SOURCES) : [$source];
        $written = 0;
        $notes = [];
        foreach ($sources as $name) {
            if ($source === 'all' && !$harvester->available($name)) {
                continue;
            }
            $result = $harvester->harvest($name, (string) ($_POST['query'] ?? ''), (int) ($_POST['limit'] ?? 20));
            if ($result['error'] !== null) {
                $notes[] = $result['error'];
            }
            $written += count($analyzer->ingest($store, $result['records']));
        }
        $store->save();
        $message = 'Indexed ' . $written . ' videos (metadata only — no footage downloaded).';
        $error = $notes === [] ? null : implode(' ', $notes);
    } elseif ($action === 'import_sample') {
        $manifest = json_decode((string) file_get_contents(__DIR__ . '/data/sample-media.json'), true);
        $written = $analyzer->ingest($store, $harvester->importManifest((array) $manifest, 'sample'));
        $store->save();
        $message = 'Imported ' . count($written) . ' illustrative sample videos.';
    } elseif ($action === 'import_manifest' && isset($_FILES['manifest']['tmp_name']) && is_uploaded_file((string) $_FILES['manifest']['tmp_name'])) {
        $manifest = json_decode((string) file_get_contents((string) $_FILES['manifest']['tmp_name']), true);
        if (!is_array($manifest)) {
            throw new InvalidArgumentException('The manifest must be a JSON list of video records.');
        }
        $written = $analyzer->ingest($store, $harvester->importManifest($manifest, (string) ($_POST['manifest_source'] ?? '') ?: 'manifest'));
        $store->save();
        $message = 'Imported ' . count($written) . ' videos from the manifest.';
    } elseif ($action === 'add_cell') {
        $saved = $querybook->addCell((string) ($_POST['book'] ?? ''), (string) ($_POST['title'] ?? ''), (string) ($_POST['fql'] ?? ''), (string) ($_POST['note'] ?? ''));
        header('Location: media-graph.php?book=' . urlencode($saved) . '#querybook');
        exit;
    }
} catch (Throwable $exception) {
    $error = $exception->getMessage();
}

$fql = trim((string) ($_GET['q'] ?? $_POST['fql'] ?? ''));
$result = null;
$queryError = null;
if ($fql !== '') {
    try {
        $result = $engine->run($fql);
    } catch (Throwable $exception) {
        $queryError = $exception->getMessage();
    }
}

if (($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($queryError !== null ? ['error' => $queryError] : ($result ?? $engine->stats()), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$bookName = QueryBook::name((string) ($_GET['book'] ?? QueryBook::STARTER));
$bookResults = isset($_GET['book']) || isset($_GET['run_book']) ? $querybook->run($querybook->load($bookName)) : null;
$stats = $engine->stats();
$videoCount = (int) $stats['rows'][2][1];

$cellValue = static function (string $value) use ($e): string {
    if (preg_match('#^(?!https?:)[A-Za-z_]+:[^\s]+$#', $value) || in_array($value, ['Video', 'Concept', 'Domain', 'Creator', 'Source', 'License', 'Generator', 'LearningUse'], true)) {
        return '<a href="media-graph.php?q=' . urlencode('DESCRIBE ' . $value) . '#console">' . $e($value) . '</a>';
    }
    if (preg_match('#^https?://#', $value)) {
        return '<a href="' . $e($value) . '" rel="noopener" target="_blank">' . $e($value) . '</a>';
    }
    return $e($value);
};
$renderTable = static function (array $result) use ($e, $cellValue): string {
    $html = '<table><thead><tr>';
    foreach ($result['columns'] as $column) {
        $html .= '<th>' . $e((string) $column) . '</th>';
    }
    $html .= '</tr></thead><tbody>';
    foreach ($result['rows'] as $row) {
        $html .= '<tr>';
        foreach ($row as $value) {
            $html .= '<td>' . $cellValue((string) $value) . '</td>';
        }
        $html .= '</tr>';
    }
    if ($result['rows'] === []) {
        $html .= '<tr><td colspan="' . max(1, count($result['columns'])) . '" class="muted">No matches.</td></tr>';
    }
    $html .= '</tbody></table>';
    $html .= '<p class="note">' . (int) $result['total'] . ' result' . ($result['total'] === 1 ? '' : 's') . (count($result['rows']) < $result['total'] ? ' · showing ' . count($result['rows']) : '') . '</p>';
    return $html;
};
$examples = [
    'SELECT ?v ?title WHERE ?v supports use:lip_reading AND ?v title ?title LIMIT 25',
    'COUNT ?v BY ?res WHERE ?v resolution_class ?res',
    'SELECT ?v ?title ?d WHERE ?v depicts concept:weather/rain AND ?v title ?title AND ?v duration_s ?d FILTER ?d >= 10 ORDER BY ?d DESC',
    'COUNT ?v BY ?gen WHERE ?v origin origin:ai_generated AND ?v generated_with ?gen',
    'NEIGHBORS concept:speech/presenter DEPTH 2 LIMIT 60',
    'STATS',
];
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Stock Media Graph · Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
        body { margin: 0; background: radial-gradient(circle at top left, #12313a, #11141c 45%), #11141c; color: #eef0f6; min-height: 100vh; }
        main { max-width: 1100px; margin: 0 auto; padding: 42px 24px 80px; }
        .eyebrow { color: #6fd6c3; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(34px, 6vw, 56px); letter-spacing: -.05em; line-height: 1; margin: 12px 0; }
        h2 { margin: 6px 0 12px; }
        p { color: #aeb2c2; line-height: 1.6; }
        a { color: #8fe0d2; }
        nav a { margin-right: 14px; }
        .panel { background: #1a1d28; border: 1px solid #343747; border-radius: 16px; padding: 22px; margin-top: 24px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
        .tile { background: #141722; border: 1px solid #2c2f3d; border-radius: 12px; padding: 14px; }
        .tile strong { display: block; font-size: 26px; letter-spacing: -.03em; }
        .bar { display: flex; align-items: center; gap: 8px; font-size: 13px; margin: 4px 0; }
        .bar span:first-child { width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #cfd3df; }
        .bar i { display: block; height: 8px; border-radius: 4px; background: #6fd6c3; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
        th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #343747; vertical-align: top; word-break: break-word; }
        th { color: #8d91a3; font-size: 11px; text-transform: uppercase; letter-spacing: .1em; }
        input, select, textarea, button { font: inherit; background: #11141c; color: #eef0f6; border: 1px solid #3d4052; border-radius: 10px; padding: 9px 12px; }
        textarea { width: 100%; box-sizing: border-box; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
        button { background: #6fd6c3; color: #0d1117; border: 0; font-weight: 700; cursor: pointer; }
        form.inline { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        code, .fql { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; color: #cfe9e4; }
        .msg { border-radius: 12px; padding: 12px 16px; margin-top: 18px; background: #143229; color: #bff3e6; }
        .err { background: #3a1820; color: #ffc9d2; }
        .note, .muted { color: #8d91a3; font-size: 13px; }
        .cell { border-top: 1px solid #2c2f3d; padding-top: 14px; margin-top: 18px; }
    </style>
</head>
<body>
<main>
    <div class="eyebrow">Book Intelligence Studio · QueryBook / UFCS / FQL</div>
    <h1>Stock media graph.</h1>
    <p>Index free stock and AI-generated video into one graph — what each clip depicts, how it is framed, how sharp it is, who made it, whether a model generated it, and what it could teach: lip reading, language, culture, places and fashion, weather and vehicles, occupations, business, and avatar source footage. Only metadata is read; no footage is downloaded or stored.</p>
    <nav>
        <a href="index.php">🏠 Studio home</a>
        <a href="#harvest">Harvest</a>
        <a href="#console">FQL console</a>
        <a href="#querybook">QueryBook</a>
    </nav>

    <?php if ($message !== null): ?><div class="msg"><?= $e($message) ?></div><?php endif; ?>
    <?php if ($error !== null): ?><div class="msg err"><?= $e($error) ?></div><?php endif; ?>

    <section class="panel">
        <div class="eyebrow">UFCS fact store</div>
        <div class="grid">
            <?php foreach (array_slice($stats['rows'], 0, 6) as [$label, $value]): ?>
                <div class="tile"><span class="note"><?= $e($label) ?></span><strong><?= number_format((int) $value) ?></strong></div>
            <?php endforeach; ?>
        </div>
        <?php if ($videoCount > 0): ?>
            <div class="grid" style="margin-top:16px">
                <?php foreach (['domain' => 'What it depicts', 'use' => 'Learning uses', 'origin' => 'Origin', 'resolution' => 'Resolution'] as $key => $title): ?>
                    <div class="tile">
                        <span class="note"><?= $e($title) ?></span>
                        <?php $counts = array_slice($stats['breakdowns'][$key], 0, 8, true); $max = max(1, ...array_values($counts ?: [1])); ?>
                        <?php foreach ($counts as $node => $count): ?>
                            <div class="bar"><span title="<?= $e((string) $node) ?>"><?= $cellValue((string) $node) ?></span><i style="width:<?= (int) round(90 * $count / $max) ?>px"></i><span><?= (int) $count ?></span></div>
                        <?php endforeach; ?>
                    </div>
                <?php endforeach; ?>
            </div>
        <?php else: ?>
            <p class="note">The graph is empty. Harvest a free source below, or load the illustrative sample corpus to explore the queries.</p>
        <?php endif; ?>
    </section>

    <section class="panel" id="harvest">
        <div class="eyebrow">Harvest free sources</div>
        <h2>Add videos to the graph</h2>
        <form method="post" class="inline">
            <input type="hidden" name="action" value="harvest">
            <select name="source">
                <option value="all">All available sources</option>
                <?php foreach (StockMediaHarvester::SOURCES as $key => $meta): ?>
                    <option value="<?= $e($key) ?>" <?= $harvester->available($key) ? '' : 'disabled' ?>><?= $e($meta['label']) ?><?= $harvester->available($key) ? '' : ' (set ' . $e((string) $meta['key_env']) . ')' ?></option>
                <?php endforeach; ?>
            </select>
            <input name="query" placeholder="Search term, e.g. woman talking" required>
            <input name="limit" type="number" min="1" max="<?= StockMediaHarvester::MAX_PER_REQUEST ?>" value="20" style="width:80px">
            <button type="submit">Harvest metadata</button>
        </form>
        <table>
            <thead><tr><th>Source</th><th>Access</th><th>License</th></tr></thead>
            <tbody>
            <?php foreach (StockMediaHarvester::SOURCES as $key => $meta): ?>
                <tr>
                    <td><a href="<?= $e($meta['site']) ?>" target="_blank" rel="noopener"><?= $e($meta['label']) ?></a></td>
                    <td><?= $meta['key_env'] === null ? 'No key needed' : ($harvester->available($key) ? 'Key configured' : 'Free key — set ' . $e($meta['key_env'])) ?></td>
                    <td><?= $e($meta['license']) ?></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
        <form method="post" enctype="multipart/form-data" class="inline" style="margin-top:16px">
            <input type="hidden" name="action" value="import_manifest">
            <input type="file" name="manifest" accept="application/json,.json" required>
            <input name="manifest_source" placeholder="Source name (e.g. ai-gallery)">
            <button type="submit">Import JSON manifest</button>
        </form>
        <p class="note">Manifests cover any other free source — AI-video galleries, your own exports. One object per video with <code>id, title, description, tags, creator, license, width, height, duration, fps, ai_generated</code>.</p>
        <form method="post" class="inline">
            <input type="hidden" name="action" value="import_sample">
            <button type="submit">Load the illustrative sample corpus</button>
        </form>
    </section>

    <section class="panel" id="console">
        <div class="eyebrow">FQL console</div>
        <h2>Query the graph</h2>
        <form method="get" action="media-graph.php#console">
            <textarea name="q" rows="4" placeholder="SELECT ?v ?title WHERE ?v supports use:lip_reading AND ?v title ?title"><?= $e($fql) ?></textarea>
            <p><button type="submit">Run FQL</button> <a href="media-graph.php?format=json&amp;q=<?= urlencode($fql !== '' ? $fql : 'STATS') ?>">as JSON</a></p>
        </form>
        <p class="note">Examples:
            <?php foreach ($examples as $example): ?>
                <br><a class="fql" href="media-graph.php?q=<?= urlencode($example) ?>#console"><?= $e($example) ?></a>
            <?php endforeach; ?>
        </p>
        <?php if ($queryError !== null): ?><div class="msg err"><?= $e($queryError) ?></div><?php endif; ?>
        <?php if ($result !== null): ?><?= $renderTable($result) ?><?php endif; ?>
        <?php if ($fql !== '' && $queryError === null): ?>
            <form method="post" class="inline" style="margin-top:12px">
                <input type="hidden" name="action" value="add_cell">
                <input type="hidden" name="fql" value="<?= $e($fql) ?>">
                <input name="book" placeholder="QueryBook name" value="<?= $e($bookName === QueryBook::STARTER ? 'my-research' : $bookName) ?>">
                <input name="title" placeholder="Cell title" required>
                <input name="note" placeholder="Note (optional)">
                <button type="submit">Save to QueryBook</button>
            </form>
        <?php endif; ?>
    </section>

    <section class="panel" id="querybook">
        <div class="eyebrow">QueryBook</div>
        <h2>Research notebooks</h2>
        <p>
            <?php foreach ($querybook->list() as $name): ?>
                <a href="media-graph.php?book=<?= urlencode($name) ?>#querybook"><?= $name === $bookName && $bookResults !== null ? '<strong>' . $e($name) . '</strong>' : $e($name) ?></a> &nbsp;
            <?php endforeach; ?>
        </p>
        <?php if ($bookResults === null): ?>
            <p class="note">Open a book to run every cell against the current graph. The starter book covers lip reading, avatar sources, culture, weather, occupations, business and AI-generated footage.</p>
        <?php else: ?>
            <?php foreach ($bookResults as $entry): ?>
                <div class="cell">
                    <strong><?= $e($entry['cell']['title']) ?></strong>
                    <?php if ($entry['cell']['note'] !== ''): ?><span class="note"> — <?= $e($entry['cell']['note']) ?></span><?php endif; ?>
                    <div><a class="fql" href="media-graph.php?q=<?= urlencode($entry['cell']['fql']) ?>#console"><?= $e($entry['cell']['fql']) ?></a></div>
                    <?php if ($entry['error'] !== null): ?>
                        <div class="msg err"><?= $e($entry['error']) ?></div>
                    <?php else: ?>
                        <?= $renderTable(['rows' => array_slice($entry['result']['rows'], 0, 12)] + $entry['result']) ?>
                    <?php endif; ?>
                </div>
            <?php endforeach; ?>
        <?php endif; ?>
    </section>
</main>
</body>
</html>
