<?php

declare(strict_types=1);

require_once __DIR__ . '/BookProjectStore.php';

$store = new BookProjectStore();
$downloadId = trim((string) ($_GET['download'] ?? ''));
if ($downloadId !== '') {
    $record = $store->load($downloadId);
    if ($record === null) {
        http_response_code(404);
        exit('Project not found.');
    }
    header('Content-Type: application/json; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $record['id'] . '.json"');
    echo json_encode($record, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$viewId = trim((string) ($_GET['view'] ?? ''));
$viewRecord = $viewId !== '' ? $store->load($viewId) : null;
$projects = $store->list();
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Book Projects · Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
        body { margin: 0; background: radial-gradient(circle at top left, #12313a, #11141c 45%), #11141c; color: #eef0f6; min-height: 100vh; }
        main { max-width: 1000px; margin: 0 auto; padding: 42px 24px 80px; }
        .eyebrow { color: #6fd6c3; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(34px, 6vw, 56px); letter-spacing: -.05em; line-height: 1; margin: 12px 0; }
        p { color: #aeb2c2; line-height: 1.6; }
        a { color: #8fe0d2; }
        table { width: 100%; border-collapse: collapse; margin-top: 22px; font-size: 14px; }
        th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #343747; vertical-align: top; }
        th { color: #8d91a3; font-size: 11px; text-transform: uppercase; letter-spacing: .1em; }
        .panel { background: #1a1d28; border: 1px solid #343747; border-radius: 16px; padding: 22px; margin-top: 24px; }
        .toc li { color: #cfd3df; line-height: 1.7; }
        .empty { border: 1px dashed #3d4052; border-radius: 14px; padding: 28px; color: #8d91a3; margin-top: 24px; }
        nav a { margin-right: 14px; }
    </style>
</head>
<body>
<main>
    <div class="eyebrow">Book Intelligence Studio</div>
    <h1>Book projects.</h1>
    <p>Every book you generate is saved here automatically — topic, options, table of contents, and the full manuscript record — so no project is ever lost.</p>
    <nav>
        <a href="amazon-book-writer.php">📦 Amazon Book Writer</a>
        <a href="book-lab.php">🔬 Book Development Lab</a>
        <a href="user-guide.php">📖 User guide</a>
    </nav>

    <?php if ($viewRecord !== null): ?>
        <div class="panel">
            <div class="eyebrow">Project record</div>
            <h2><?= htmlspecialchars((string) ($viewRecord['metadata']['title'] ?? $viewRecord['topic']), ENT_QUOTES, 'UTF-8') ?></h2>
            <p>Saved <?= htmlspecialchars((string) $viewRecord['saved_at'], ENT_QUOTES, 'UTF-8') ?> ·
               <?= (int) ($viewRecord['summary']['chapters'] ?? 0) ?> chapters ·
               <?= number_format((int) ($viewRecord['summary']['total_word_count'] ?? 0)) ?> words ·
               <?= (int) ($viewRecord['summary']['page_count'] ?? 0) ?> pages ·
               <?= htmlspecialchars((string) ($viewRecord['summary']['style'] ?? ''), ENT_QUOTES, 'UTF-8') ?> voice</p>
            <h3>Table of contents</h3>
            <ol class="toc">
                <?php foreach ((array) $viewRecord['table_of_contents'] as $entry): ?>
                    <li><?= htmlspecialchars((string) ($entry['title'] ?? ''), ENT_QUOTES, 'UTF-8') ?> — p. <?= (int) ($entry['page_number'] ?? 0) ?></li>
                <?php endforeach; ?>
            </ol>
            <p>
                <a href="book-projects.php?download=<?= urlencode((string) $viewRecord['id']) ?>">Download the full record (.json)</a> ·
                <a href="amazon-book-writer.php?topic=<?= urlencode((string) $viewRecord['topic']) ?>">Reopen this topic in the writer</a>
            </p>
        </div>
    <?php endif; ?>

    <?php if ($projects === []): ?>
        <div class="empty">No projects yet. Generate a book in the <a href="amazon-book-writer.php">Amazon Book Writer</a> and it will be recorded here automatically.</div>
    <?php else: ?>
        <table>
            <thead><tr><th>Saved</th><th>Book</th><th>Chapters</th><th>Words</th><th>Record</th></tr></thead>
            <tbody>
            <?php foreach ($projects as $project): ?>
                <tr>
                    <td><?= htmlspecialchars(substr((string) $project['saved_at'], 0, 16), ENT_QUOTES, 'UTF-8') ?></td>
                    <td>
                        <strong><?= htmlspecialchars((string) ($project['title'] !== '' ? $project['title'] : $project['topic']), ENT_QUOTES, 'UTF-8') ?></strong><br>
                        <span style="color:#8d91a3"><?= htmlspecialchars((string) $project['topic'], ENT_QUOTES, 'UTF-8') ?></span>
                    </td>
                    <td><?= (int) $project['chapters'] ?></td>
                    <td><?= number_format((int) ($project['summary']['total_word_count'] ?? 0)) ?></td>
                    <td>
                        <a href="book-projects.php?view=<?= urlencode((string) $project['id']) ?>">View</a> ·
                        <a href="book-projects.php?download=<?= urlencode((string) $project['id']) ?>">Download</a>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php endif; ?>
</main>
</body>
</html>
