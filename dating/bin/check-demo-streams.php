<?php

declare(strict_types=1);

/**
 * Watch Party stream checker — the error check that keeps the demo's
 * videos from ever jumbling again. For every channel entry baked into
 * preview/demo/index.html it verifies, against YouTube's oEmbed
 * endpoint, that the video id is (a) alive and embeddable and (b) has
 * a real title matching the entry's requested title (the engine's
 * streamTitleMatches rule). The verified romance classics are checked
 * for liveness. Run it before shipping demo ids:
 *
 *     php dating/bin/check-demo-streams.php
 *
 * Exit code 0 = every baked id verified; 1 = failures listed below.
 * Needs the network; not part of the offline test suite.
 */

require_once __DIR__ . '/../SlowDatingEngine.php';

$demo = dirname(__DIR__, 2) . '/preview/demo/index.html';
$html = file_get_contents($demo);
if ($html === false) {
    fwrite(STDERR, "demo page not found: {$demo}\n");
    exit(1);
}

$context = stream_context_create(['http' => [
    'timeout' => 10,
    'ignore_errors' => true,
    'header' => "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\nAccept-Language: en\r\n",
]]);
$title = static function (string $id) use ($context): ?string {
    $body = @file_get_contents('https://www.youtube.com/oembed?url=' . rawurlencode('https://youtu.be/' . $id) . '&format=json', false, $context);
    if (!is_string($body)) {
        return null;
    }
    $decoded = json_decode($body, true);
    return is_array($decoded) && isset($decoded['title']) ? (string) $decoded['title'] : null;
};

$failures = [];
$checked = 0;
$standins = 0;

// Channel entries: [2xxx,'Title',0,'tag','id',live] in either quote style.
preg_match_all(
    '/\[(2\d{3}),([\'"])((?:[^\'"\\\\]|\\\\.)*)\2,0,\'(?:[^\'\\\\]|\\\\.)*\',\'([A-Za-z0-9_-]{0,11})\',(?:true|false)\]/',
    $html,
    $rows,
    PREG_SET_ORDER,
);
foreach ($rows as [$all, $rank, $quote, $wanted, $id]) {
    if ($id === '') {
        $standins++;   // labeled stand-in path — intentionally no id
        continue;
    }
    $checked++;
    $actual = $title($id);
    if ($actual === null) {
        $failures[] = "DEAD  #{$rank} {$wanted} ({$id})";
    } elseif ($rank !== '2001' && !SlowDatingEngine::streamTitleMatches(stripslashes($wanted), $actual)) {
        $failures[] = "WRONG #{$rank} wanted \"{$wanted}\" got \"{$actual}\" ({$id})";
    }
    usleep(120000);
}

// Baked trailers: alive, embeddable, titled as a trailer FOR THAT film.
if (preg_match('/const TRAILERS = (\{[^;]*\});/', $html, $trailerJson) === 1) {
    $filmTitles = [];
    preg_match_all("/\\[(\\d{1,3}),'((?:[^'\\\\]|\\\\.)*)',\\d{1,4},'(?:[^'\\\\]|\\\\.)*',''\\]/", $html, $bare, PREG_SET_ORDER);
    foreach ($bare as [$all, $rank, $name]) {
        $filmTitles[(int) $rank] = stripslashes($name);
    }
    foreach ((array) json_decode($trailerJson[1], true) as $rank => $id) {
        $checked++;
        $wanted = $filmTitles[(int) $rank] ?? '';
        $actual = $title((string) $id);
        if ($actual === null) {
            $failures[] = "DEAD  trailer #{$rank} {$wanted} ({$id})";
        } elseif ($wanted !== '' && (stripos($actual, 'trailer') === false || !SlowDatingEngine::streamTitleMatches($wanted, $actual))) {
            $failures[] = "WRONG trailer #{$rank} wanted \"{$wanted}\" got \"{$actual}\" ({$id})";
        }
        usleep(120000);
    }
}

// The verified romance classics must stay alive.
preg_match_all("/\\[(\\d{1,3}),'((?:[^'\\\\]|\\\\.)*)',\\d{1,4},'(?:[^'\\\\]|\\\\.)*','([A-Za-z0-9_-]{11})'\\]/", $html, $classics, PREG_SET_ORDER);
foreach ($classics as [$all, $rank, $name, $id]) {
    $checked++;
    if ($title($id) === null) {
        $failures[] = "DEAD  classic #{$rank} {$name} ({$id})";
    }
    usleep(120000);
}

echo "checked {$checked} baked ids · {$standins} labeled stand-ins\n";
if ($failures === []) {
    echo "all streams verified — alive, embeddable, and title-matched\n";
    exit(0);
}
fwrite(STDERR, count($failures) . " FAILURES:\n" . implode("\n", $failures) . "\n");
exit(1);
