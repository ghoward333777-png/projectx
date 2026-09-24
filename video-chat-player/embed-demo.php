<?php
declare(strict_types=1);

// Example host page: the player embedded in another page and driven through embed.js.
// Open it with ?room=<id> to embed an existing room, or without to start a new one.
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; frame-src 'self'; img-src 'self' data:");
$room = isset($_GET['room']) && preg_match('/^[a-z]+-[a-z]+-\d\d$/', (string) $_GET['room']) ? (string) $_GET['room'] : '';
$e = static fn (string $s): string => htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watch Room embed example</title>
<link rel="stylesheet" href="assets/styles.css">
<link rel="stylesheet" href="assets/docs.css">
</head>
<body>
<main class="app docs">
    <header class="topbar">
        <h1 class="topbar__title">Embed example <span class="topbar__step">embed.js</span></h1>
        <nav class="docs__nav"><a href="index.php">Player</a> <a href="api-docs.php">API</a></nav>
    </header>
    <p class="docs__lead">This page is any other website. The player below is an iframe created by <code>WatchRoom.embed()</code>; the buttons talk to it through the bridge, and the log shows the events it sends back.</p>
    <div id="box" data-room="<?= $e($room) ?>"></div>
    <p class="docs__lead" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        <button class="button button--small" id="b-play">Play</button>
        <button class="button button--small" id="b-pause">Pause</button>
        <button class="button button--small" id="b-back">−10 s</button>
        <button class="button button--small" id="b-fwd">+10 s</button>
        <button class="button button--small button--quiet" id="b-chat">Say hello from the host page</button>
        <button class="button button--small button--quiet" id="b-snap">Snapshot</button>
    </p>
    <pre class="docs__pre" id="log" aria-live="polite"></pre>
</main>
<script src="assets/embed.js"></script>
<script src="assets/embed-demo.js"></script>
</body>
</html>
