<?php
declare(strict_types=1);

require_once __DIR__ . '/lib/Source.php';
require_once __DIR__ . '/lib/RoomStore.php';

header("Content-Security-Policy: default-src 'self'; script-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; frame-src https://www.youtube.com https://www.youtube-nocookie.com; media-src 'self' https: blob:; img-src 'self' https: data:; style-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'");
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: strict-origin-when-cross-origin');

$mediaDir = __DIR__ . '/media';
$library = Source::library($mediaDir);
$requested = isset($_GET['src']) ? (string) $_GET['src'] : '';
$source = Source::resolve($requested, $mediaDir);
$rejected = $requested !== '' && $source === null;
$source ??= Source::defaultSource($mediaDir);
$roomId = isset($_GET['room']) && RoomStore::isRoomId((string) $_GET['room']) ? (string) $_GET['room'] : '';
$idleTimeout = max(1500, min(10000, (int) ($_GET['idle'] ?? 3000)));
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
        <h1 class="topbar__title">Watch Room</h1>
        <div class="roombar">
            <span class="roombar__label">room</span>
            <code class="roombar__id" id="room-id"><?= $roomId !== '' ? $e($roomId) : '…' ?></code>
            <button type="button" class="button button--small" id="room-copy">Copy invite</button>
            <span class="roombar__members" id="room-members"></span>
        </div>
        <form class="namebar" id="room-name-form">
            <label class="visually-hidden" for="room-name">Your name</label>
            <input id="room-name" name="name" maxlength="32" placeholder="Your name" autocomplete="nickname">
            <button type="submit" class="button button--small button--quiet">Set name</button>
        </form>
    </header>

    <p class="notice notice--warn" id="banner" hidden role="status"></p>
    <?php if ($rejected): ?>
    <p class="notice notice--warn" role="alert">That source was not accepted. Use an https link ending in .mp4, .webm or .m4v, a YouTube link, or a file from the media/ folder.</p>
    <?php endif; ?>

    <section class="workspace">
        <div class="stage" id="stage" tabindex="0" aria-label="Video stage"
             data-src="<?= $e($source['src']) ?>" data-kind="<?= $e($source['kind']) ?>" data-label="<?= $e($source['label']) ?>" data-idle-timeout="<?= (int) $idleTimeout ?>">
            <div class="stage__picture" id="stage-picture"></div>
            <div class="stage__cards" id="stage-cards"></div>
            <div class="stage__controls" id="stage-controls">
                <button type="button" class="control" id="ctl-play" aria-label="Play" aria-pressed="false">▶</button>
                <input type="range" class="seek" id="ctl-seek" min="0" max="1000" step="1" value="0" aria-label="Seek">
                <span class="control__time" id="ctl-time">0:00 / –:––</span>
                <button type="button" class="control" id="ctl-mute" aria-label="Mute" aria-pressed="false">🔊</button>
                <input type="range" class="volume" id="ctl-volume" min="0" max="1" step="0.05" value="1" aria-label="Volume">
                <select class="select select--small" id="ctl-rate" aria-label="Speed">
                    <option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1" selected>1×</option>
                    <option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option>
                </select>
                <button type="button" class="control" id="ctl-chat" aria-label="Hide chat" aria-pressed="true">💬</button>
                <button type="button" class="control" id="ctl-fullscreen" aria-label="Full screen" aria-pressed="false">⛶</button>
            </div>
            <div class="stage__chatdot" id="chat-dot" hidden><span id="chat-unread">chat off · press C</span></div>
            <div class="stage__overlay overlay" id="stage-overlay" role="log" aria-live="polite" aria-label="Chat">
                <div class="overlay__list" id="overlay-list"></div>
                <form class="overlay__composer" id="overlay-composer">
                    <input class="overlay__input" id="overlay-input" placeholder="Say something… (Enter)" maxlength="500" autocomplete="off" aria-label="Message">
                    <button type="submit" class="overlay__send" aria-label="Send">⏎</button>
                </form>
            </div>
        </div>
        <aside class="rail">
            <h2 class="rail__title">Now playing</h2>
            <p class="rail__label" id="rail-label"><?= $e($source['label']) ?></p>

            <h2 class="rail__title">Playlist</h2>
            <ol class="pl" id="pl-list"></ol>
            <form class="pl__add" id="pl-form">
                <label class="visually-hidden" for="pl-url">Add a video link</label>
                <input id="pl-url" placeholder="YouTube link, playlist, or .mp4 URL" autocomplete="off" spellcheck="false" list="pl-library">
                <?php if ($library !== []): ?>
                <datalist id="pl-library">
                    <?php foreach ($library as $name): ?><option value="media/<?= $e($name) ?>"></option><?php endforeach; ?>
                </datalist>
                <?php endif; ?>
                <button type="submit" class="button button--small">Add</button>
            </form>
            <p class="rail__note" id="pl-note"></p>

            <form class="settings" id="room-settings" hidden>
                <h2 class="rail__title">Host settings</h2>
                <label class="settings__row"><input type="checkbox" id="set-guests"> Guests can pause and seek for everyone</label>
                <label class="settings__row"><input type="checkbox" id="set-docked"> Chat under the picture for YouTube (docked)</label>
            </form>

            <h2 class="rail__title">System</h2>
            <ul class="health" id="health-list"></ul>

            <details class="rail__details">
                <summary>Stage geometry and keys</summary>
                <dl class="debug" id="debug">
                    <dt>Stage</dt><dd id="dbg-stage">–</dd>
                    <dt>Picture</dt><dd id="dbg-picture">–</dd>
                    <dt>Content rect</dt><dd id="dbg-rect">–</dd>
                    <dt>Full screen</dt><dd id="dbg-fs">no</dd>
                    <dt>State</dt><dd id="dbg-state">loading</dd>
                    <dt>Overlay</dt><dd id="dbg-idle">visible</dd>
                </dl>
                <p class="rail__keys"><kbd>Space</kbd>/<kbd>K</kbd> play · <kbd>←</kbd><kbd>→</kbd> 5 s (<kbd>Shift</kbd> 15 s) · <kbd>J</kbd>/<kbd>L</kbd> 10 s · <kbd>↑</kbd><kbd>↓</kbd> volume · <kbd>M</kbd> mute</p>
                <p class="rail__keys"><kbd>F</kbd> full screen · <kbd>C</kbd> chat on/off · <kbd>Enter</kbd>/<kbd>T</kbd>/<kbd>/</kbd> type · <kbd>Esc</kbd> stop typing · <kbd>N</kbd>/<kbd>P</kbd> next/previous</p>
                <p class="rail__keys">The overlay hides after <?= (int) $idleTimeout ?> ms without mouse or keys. It never hides while you type, hold a draft, hover it, or pause.</p>
            </details>
        </aside>
    </section>
</main>
<script type="module" src="assets/app.js"></script>
</body>
</html>
