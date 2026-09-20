<?php

declare(strict_types=1);

/**
 * Shared UI helpers for the SlowDating pages: one responsive stylesheet
 * (desktop and mobile), escaping, and the page frame. No frameworks.
 */

function sd_e(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}

function sd_page_open(string $title, string $eyebrow): void
{
    ?><!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?= sd_e($title) ?></title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #131018; color: #f3eef6; }
        body { margin: 0; background: radial-gradient(circle at top right, #3b1e3f, #131018 45%); min-height: 100vh; }
        main { max-width: 1080px; margin: 0 auto; padding: 32px 16px 80px; }
        header { border-bottom: 1px solid #43364a; padding-bottom: 20px; margin-bottom: 20px; }
        .eyebrow { color: #ff9cc0; font-size: 12px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(28px, 6vw, 52px); line-height: 1.02; margin: 10px 0; letter-spacing: -.04em; }
        h2 { font-size: 20px; margin: 0 0 10px; }
        p { color: #c9bfd2; line-height: 1.6; }
        nav a, .links a { color: #ffb8d2; margin-right: 14px; text-decoration: none; }
        nav a:hover, .links a:hover { text-decoration: underline; }
        form, section { background: #1d1824; border: 1px solid #3d3346; border-radius: 16px; padding: 18px; margin-top: 14px; }
        label { display: block; color: #eadff0; font-size: 13px; font-weight: 700; margin: 10px 0 6px; }
        input, select, textarea { box-sizing: border-box; width: 100%; background: #14101b; border: 1px solid #574a61; border-radius: 10px; color: #fff; padding: 11px 12px; font: inherit; }
        textarea { min-height: 70px; }
        button { border: 0; border-radius: 999px; background: #ff9cc0; color: #2a0f1d; padding: 11px 18px; font: inherit; font-weight: 800; cursor: pointer; margin-top: 12px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
        .card { background: #262030; border-radius: 14px; padding: 14px; }
        .card strong { color: #fff; }
        .pill { display: inline-block; background: #3a2a3e; border-radius: 999px; padding: 3px 10px; font-size: 12px; color: #ffc4da; margin: 2px 4px 2px 0; }
        .metric strong { display: block; font-size: 30px; color: #fff; }
        .metric span { color: #bfb2c8; font-size: 13px; }
        .error { color: #ff9cba; background: #3c1f32; border: 1px solid #7a3755; padding: 12px; border-radius: 10px; margin-top: 14px; }
        .notice { color: #b8ffd3; background: #17351f; border: 1px solid #2e6b40; padding: 12px; border-radius: 10px; margin-top: 14px; word-break: break-all; }
        .chat-log { max-height: 320px; overflow-y: auto; background: #14101b; border-radius: 10px; padding: 10px; }
        .msg { margin: 6px 0; padding: 8px 12px; border-radius: 12px; max-width: 85%; }
        .msg.mine { background: #4a2440; margin-left: auto; }
        .msg.theirs { background: #2b2436; }
        .msg small { display: block; color: #a294ad; font-size: 11px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #3d3346; font-size: 14px; }
        code { color: #ffd4e5; }
        ul { color: #d5c9dd; line-height: 1.8; padding-left: 20px; }
        @media (max-width: 640px) {
            main { padding: 20px 12px 60px; }
            form, section { padding: 14px; }
            th, td { font-size: 13px; padding: 6px; }
        }
    </style>
</head>
<body>
<main>
    <header>
        <div class="eyebrow"><?= sd_e($eyebrow) ?></div>
        <h1><?= sd_e($title) ?></h1>
        <nav>
            <a href="index.php">Member app</a>
            <a href="features.php">Features</a>
            <a href="smart-dating.php">Smart Dating</a>
            <a href="site-tour.php">Site Tour</a>
            <a href="partner-portal.php">Partner portal</a>
            <a href="admin.php">Admin console</a>
            <a href="safety-center.php">Safety center</a>
        </nav>
    </header>
    <?php
}

function sd_page_close(): void
{
    ?>
</main>
<script>
    // Chat logs open at the newest message, like any messenger.
    document.querySelectorAll('.chat-log').forEach(function (log) { log.scrollTop = log.scrollHeight; });
</script>
</body>
</html><?php
}

function sd_flash(?string $error, ?string $notice): void
{
    if ($error !== null && $error !== '') {
        echo '<div class="error">' . sd_e($error) . '</div>';
    }
    if ($notice !== null && $notice !== '') {
        echo '<div class="notice">' . sd_e($notice) . '</div>';
    }
}
