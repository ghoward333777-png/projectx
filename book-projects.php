<?php

declare(strict_types=1);

require_once __DIR__ . '/BookProjectStore.php';
require_once __DIR__ . '/StudioTheme.php';

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
    <?php StudioTheme::head('Book projects'); ?>
</head>
<body>
<?php StudioTheme::open([
    'active' => 'library',
    'current' => 'Library',
    'progress_label' => 'Completed package archive',
    'progress_value' => StudioTheme::projectCount() . ' saved',
    'progress_percent' => 100,
]); ?>

    <div class="page-intro">
        <div>
            <span class="section-label coral">LIBRARY</span>
            <h1>Book projects.</h1>
            <p>Every book you generate is saved here automatically — topic, options, table of contents, and the full manuscript record — so no project is ever lost.</p>
        </div>
        <div class="intro-action">
            <a class="primary-button" href="generate-book.php"><?= StudioTheme::icon('pen', 14) ?> Generate a new book</a>
        </div>
    </div>

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
<?php StudioTheme::close(); ?>
</body>
</html>
