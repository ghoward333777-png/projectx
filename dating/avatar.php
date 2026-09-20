<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';

/**
 * Avatar — a deterministic, procedurally generated SVG portrait for any
 * member: same member, same artwork, on every host, with no image files,
 * no uploads, and no external service. Clearly synthetic by design (no
 * real faces), suitable for demo libraries and members who prefer not to
 * upload a photo.
 *
 * Usage: avatar.php?u=<user id>
 */

$engine = new SlowDatingEngine();
$userId = (string) ($_GET['u'] ?? '');
$chatId = (string) ($_GET['chat'] ?? '');
$artOnly = ($_GET['art'] ?? '') !== '';   // force the generated artwork

$servePhoto = static function (array $photo): never {
    header('Content-Type: ' . $photo['mime']);
    header('X-Content-Type-Options: nosniff');
    header('Content-Security-Policy: default-src \'none\'');
    header('Cache-Control: private, max-age=300');
    readfile($photo['path']);
    exit;
};

// Who is looking? The photo-reveal timeframe and the premium "Peek early"
// perk are per-viewer, so every real-picture branch needs the session.
$viewer = null;
if (!$artOnly && $userId !== '') {
    session_start();
    if (isset($_SESSION['sd_member_token'])) {
        $auth = $engine->authenticate((string) $_SESSION['sd_member_token']);
        if ($auth !== null && $auth[1] === 'member') {
            $viewer = $auth[0];
        }
    }
}

// Chat context: inside a chat, each member chose which of their three
// pictures the other person sees. The private picture is served only
// here, only to the other participant, and only when its owner chose it.
// Either way, real pictures wait for the admin-set reveal timeframe —
// unless the viewer is premium ("Peek early").
if ($artOnly) {
    // fall through to the generated art below
} elseif ($chatId !== '' && $userId !== '') {
    $chat = $engine->store()->get('chats', $chatId);
    $participants = (array) ($chat['participants'] ?? []);
    if ($chat !== null && $viewer !== null
        && in_array($viewer, $participants, true) && in_array($userId, $participants, true)
        && $engine->canSeeRealPhotos($viewer, $userId)) {
        $choice = $engine->chatImageChoice($chatId, $userId);
        if ($choice !== 'generated') {
            $photo = $engine->memberPhoto($userId, $choice) ?? $engine->memberPhoto($userId, 'public');
            if ($photo !== null) {
                $servePhoto($photo);
            }
        }
    }
    // No entitlement (or artwork chosen): fall through to the generated art.
} elseif ($engine->avatarMode() === 'uploads') {
    // Admin-controlled global mode: cards across Browse, Matches, and
    // Search show the member's REAL picture — but only once the viewer has
    // earned it (their chat with that member has aged past the reveal
    // timeframe) or holds the premium "Peek early" perk. The private
    // picture never appears in any global context.
    $photo = ($viewer !== null && $engine->canSeeRealPhotos($viewer, $userId))
        ? $engine->memberPhoto($userId, 'public')
        : null;
    if ($photo !== null) {
        $servePhoto($photo);
    }
}

$user = $userId !== '' ? $engine->store()->get('users', $userId) : null;
$name = trim((string) ($user['profile']['display_name'] ?? ''));
$initial = $name !== '' ? mb_strtoupper(mb_substr($name, 0, 1)) : '?';

$seed = crc32($userId !== '' ? $userId : 'slowdating');
$pick = static function (int $offset, int $count) use ($seed): int {
    return abs((int) (($seed >> $offset) ^ ($seed * 2654435761))) % $count;
};

$palettes = [
    ['#3b1e3f', '#ff9cc0', '#ffc4da'], ['#1e2a4a', '#8fb8ff', '#cfe0ff'],
    ['#173a2e', '#7fe3a8', '#c6f5d9'], ['#4a2410', '#ffb08a', '#ffd9c2'],
    ['#3a103a', '#e08aff', '#f0c9ff'], ['#103a3a', '#7fdede', '#c9f2f2'],
    ['#40320f', '#ffd97a', '#ffecb8'], ['#2b1140', '#b49cff', '#d9ccff'],
];
[$deep, $mid, $soft] = $palettes[$pick(3, count($palettes))];

// Deterministic blob field: position, radius, and tone from the seed.
$blobs = '';
for ($i = 0; $i < 5; $i++) {
    $cx = 30 + $pick(2 + $i, 180);
    $cy = 30 + $pick(9 + $i, 180);
    $r = 22 + $pick(16 + $i, 46);
    $tone = ($i % 2 === 0) ? $mid : $soft;
    $opacity = 0.16 + ($pick(23 + $i, 20) / 100);
    $blobs .= sprintf('<circle cx="%d" cy="%d" r="%d" fill="%s" opacity="%.2f"/>', $cx, $cy, $r, $tone, $opacity);
}
$rotation = $pick(5, 360);

header('Content-Type: image/svg+xml; charset=utf-8');
header('Cache-Control: public, max-age=86400');
echo <<<SVG
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" width="240" height="240" role="img" aria-label="Member avatar">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1" gradientTransform="rotate({$rotation} .5 .5)">
      <stop offset="0" stop-color="{$deep}"/>
      <stop offset="1" stop-color="{$mid}"/>
    </linearGradient>
    <clipPath id="frame"><rect width="240" height="240" rx="28"/></clipPath>
  </defs>
  <g clip-path="url(#frame)">
    <rect width="240" height="240" fill="url(#g)"/>
    {$blobs}
    <text x="120" y="121" text-anchor="middle" dominant-baseline="central"
          font-family="Georgia, serif" font-size="112" font-weight="700"
          fill="#ffffff" opacity="0.92">{$initial}</text>
  </g>
</svg>
SVG;
