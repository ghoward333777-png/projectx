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
