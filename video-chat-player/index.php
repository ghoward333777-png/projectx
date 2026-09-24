<?php
declare(strict_types=1);

require_once __DIR__ . '/lib/Source.php';

header("Content-Security-Policy: default-src 'self'; script-src 'self' https://www.youtube.com; frame-src https://www.youtube.com https://www.youtube-nocookie.com; media-src 'self' https: blob:; img-src 'self' https: data:; style-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'");
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: strict-origin-when-cross-origin');

$mediaDir = __DIR__ . '/media';
$library = Source::library($mediaDir);
$requested = isset($_GET['src']) ? (string) $_GET['src'] : '';
$source = Source::resolve($requested, $mediaDir);
$rejected = $requested !== '' && $source === null;
$source ??= Source::defaultSource();
$e = static fn (string $s): string => htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watch Room</title>
<link rel="stylesheet" href="assets/styles.css">
</head>
<body>
<main class="app">
    <header class="topbar">
        <h1 class="topbar__title">Watch Room <span class="topbar__step">step 1 · stage</span></h1>
        <form class="loader" method="get" action="index.php">
            <label class="loader__field">
                <span class="visually-hidden">Video URL or media file</span>
                <input name="src" id="src" value="<?= $e($source['src']) ?>" placeholder="https://…/video.mp4 or media/file.mp4" autocomplete="off" spellcheck="false">
            </label>
            <button type="submit" class="button">Load</button>
            <?php if ($library !== []): ?>
            <label class="loader__field">
                <span class="visually-hidden">Local media</span>
                <select id="library" class="select" aria-label="Local media">
                    <option value="">media/ folder…</option>
                    <?php foreach ($library as $name): ?>
                    <option value="media/<?= $e($name) ?>"<?= $source['src'] === 'media/' . $name ? ' selected' : '' ?>><?= $e($name) ?></option>
                    <?php endforeach; ?>
                </select>
            </label>
            <?php endif; ?>
        </form>
    </header>

    <?php if ($rejected): ?>
    <p class="notice notice--warn" role="alert">That source was not accepted. Use an https link ending in .mp4, .webm or .m4v, or a file from the media/ folder. Playing the default instead.</p>
    <?php endif; ?>

    <section class="workspace">
        <div class="stage" id="stage" tabindex="0" aria-label="Video stage"
             data-src="<?= $e($source['src']) ?>" data-kind="<?= $e($source['kind']) ?>" data-label="<?= $e($source['label']) ?>">
            <div class="stage__picture" id="stage-picture"></div>
            <div class="stage__cards" id="stage-cards"></div>
            <div class="stage__controls" id="stage-controls">
                <button type="button" class="control" id="ctl-play" aria-label="Play" aria-pressed="false">▶</button>
                <span class="control__time" id="ctl-time">0:00 / 0:00</span>
                <span class="control__spacer"></span>
                <button type="button" class="control" id="ctl-fullscreen" aria-label="Full screen">⛶</button>
            </div>
            <div class="stage__overlay overlay" id="stage-overlay" role="log" aria-live="polite" aria-label="Chat">
                <div class="overlay__list" id="overlay-list">
                    <p class="overlay__system">Chat overlay. This box is the exact spot the chat will occupy; messages arrive in step 3.</p>
                </div>
                <form class="overlay__composer" id="overlay-composer">
                    <input class="overlay__input" id="overlay-input" placeholder="Say something… (step 3)" disabled aria-label="Message">
                    <button type="submit" class="overlay__send" disabled aria-label="Send">⏎</button>
                </form>
            </div>
        </div>
        <aside class="rail">
            <h2 class="rail__title">Now playing</h2>
            <p class="rail__label" id="rail-label"><?= $e($source['label']) ?></p>
            <h2 class="rail__title">Stage geometry</h2>
            <dl class="debug" id="debug">
                <dt>Stage</dt><dd id="dbg-stage">–</dd>
                <dt>Picture</dt><dd id="dbg-picture">–</dd>
                <dt>Content rect</dt><dd id="dbg-rect">–</dd>
                <dt>Full screen</dt><dd id="dbg-fs">no</dd>
                <dt>State</dt><dd id="dbg-state">loading</dd>
            </dl>
            <h2 class="rail__title">Keys</h2>
            <p class="rail__keys"><kbd>Space</kbd>/<kbd>K</kbd> play · <kbd>F</kbd> full screen · <kbd>←</kbd><kbd>→</kbd> seek 5 s · <kbd>Esc</kbd> leave full screen</p>
            <p class="rail__keys">The playlist rail arrives in step 5.</p>
        </aside>
    </section>
</main>
<script type="module" src="assets/app.js"></script>
</body>
</html>
