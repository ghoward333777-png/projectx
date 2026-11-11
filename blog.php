<?php

declare(strict_types=1);

require_once __DIR__ . '/BlogStore.php';

const BLOG_NAME = 'Provenance';
const BLOG_COMMENT_COOLDOWN = 20;

// BLOG_COMMENTS_DIR lets a host (or the contract test) keep comments outside the app folder.
$store = new BlogStore(getenv('BLOG_COMMENTS_DIR') ?: null);

function e(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

/** Escape, then allow the three inline marks the articles use: **bold**, *emphasis*, `code`. */
function blog_inline(string $text): string
{
    $html = e($text);
    $html = (string) preg_replace('/`([^`]+)`/', '<code>$1</code>', $html);
    $html = (string) preg_replace('/\*\*([^*]+)\*\*/', '<strong>$1</strong>', $html);
    return (string) preg_replace('/\*([^*]+)\*/', '<em>$1</em>', $html);
}

function blog_date(string $iso): string
{
    $time = strtotime($iso);
    return $time === false ? '' : gmdate('j M Y', $time);
}

/** Deterministic generative cover: a small typed knowledge graph drawn from the slug. */
function blog_cover(array $article, string $uid): string
{
    $seed = crc32((string) $article['slug']);
    $rand = static function () use (&$seed): float {
        $seed = ($seed * 1103515245 + 12345) & 0x7fffffff;
        return $seed / 0x7fffffff;
    };
    [$h1, $h2] = array_map('intval', (array) ($article['hues'] ?? [190, 270])) + [190, 270];
    $labels = ['ENT', 'EVT', 'SRC', 'CAU', 'RUL', 'AGT', 'PRP', 'GOL', 'AGR', 'Δt'];
    $nodes = [];
    for ($i = 0; $i < 16; $i++) {
        $nodes[] = [40 + $rand() * 720, 30 + $rand() * 340, 3 + $rand() * 7, $labels[(int) floor($rand() * 10) % 10]];
    }
    $svg = '<svg class="cover" viewBox="0 0 800 400" preserveAspectRatio="xMidYMid slice" role="img" aria-label="">'
        . '<defs>'
        . "<linearGradient id=\"bg{$uid}\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop offset=\"0\" stop-color=\"hsl({$h1} 70% 14%)\"/><stop offset=\"1\" stop-color=\"hsl({$h2} 65% 9%)\"/></linearGradient>"
        . "<radialGradient id=\"ga{$uid}\"><stop offset=\"0\" stop-color=\"hsl({$h1} 95% 60%)\" stop-opacity=\".55\"/><stop offset=\"1\" stop-color=\"hsl({$h1} 95% 60%)\" stop-opacity=\"0\"/></radialGradient>"
        . "<radialGradient id=\"gb{$uid}\"><stop offset=\"0\" stop-color=\"hsl({$h2} 95% 62%)\" stop-opacity=\".5\"/><stop offset=\"1\" stop-color=\"hsl({$h2} 95% 62%)\" stop-opacity=\"0\"/></radialGradient>"
        . '</defs>'
        . "<rect width=\"800\" height=\"400\" fill=\"url(#bg{$uid})\"/>"
        . sprintf('<circle cx="%d" cy="%d" r="260" fill="url(#ga%s)"/>', 120 + $rand() * 250, 60 + $rand() * 200, $uid)
        . sprintf('<circle cx="%d" cy="%d" r="300" fill="url(#gb%s)"/>', 450 + $rand() * 280, 180 + $rand() * 200, $uid);
    foreach ($nodes as $i => $a) {
        foreach ($nodes as $j => $b) {
            $distance = hypot($a[0] - $b[0], $a[1] - $b[1]);
            if ($j > $i && $distance < 210) {
                $svg .= sprintf(
                    '<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="hsl(%d 90%% 78%%)" stroke-opacity="%.2f" stroke-width="1.2"/>',
                    $a[0], $a[1], $b[0], $b[1], $j % 2 ? $h1 : $h2, 0.55 - $distance / 420
                );
            }
        }
    }
    foreach ($nodes as $i => $n) {
        $hue = $i % 2 ? $h1 : $h2;
        $svg .= sprintf('<circle cx="%.0f" cy="%.0f" r="%.1f" fill="hsl(%d 95%% 72%%)"/>', $n[0], $n[1], $n[2], $hue);
        $svg .= sprintf('<circle cx="%.0f" cy="%.0f" r="%.1f" fill="none" stroke="hsl(%d 95%% 72%%)" stroke-opacity=".35"/>', $n[0], $n[1], $n[2] + 6, $hue);
        if ($n[2] > 6.5) {
            $svg .= sprintf('<text x="%.0f" y="%.0f" fill="hsl(%d 90%% 86%%)" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13" letter-spacing="1.5">%s</text>', $n[0] + 16, $n[1] + 5, $hue, e($n[3]));
        }
    }
    return $svg . '</svg>';
}

function blog_video(array $block): string
{
    $id = (string) ($block['id'] ?? '');
    if (!BlogStore::validVideoId($id)) {
        return '';
    }
    $title = e((string) ($block['title'] ?? 'Video'));
    $channel = e((string) ($block['channel'] ?? ''));
    return '<figure class="video">'
        . "<button type=\"button\" class=\"yt\" data-yt=\"{$id}\" data-title=\"{$title}\" aria-label=\"Play video: {$title}\">"
        . "<img src=\"https://i.ytimg.com/vi/{$id}/hqdefault.jpg\" alt=\"\" loading=\"lazy\" onerror=\"this.remove()\">"
        . '<span class="play" aria-hidden="true"><svg viewBox="0 0 24 24" width="30" height="30"><path d="M8 5v14l11-7z" fill="currentColor"/></svg></span>'
        . '</button>'
        . "<figcaption><span class=\"vt\">{$title}</span><span class=\"vc\">{$channel} · <a href=\"https://www.youtube.com/watch?v={$id}\" target=\"_blank\" rel=\"noopener\">Watch on YouTube</a></span></figcaption>"
        . '</figure>';
}

function blog_block(array $block): string
{
    switch ((string) ($block['type'] ?? '')) {
        case 'p':
            return '<p>' . blog_inline((string) ($block['text'] ?? '')) . '</p>';
        case 'h':
            return '<h2>' . blog_inline((string) ($block['text'] ?? '')) . '</h2>';
        case 'quote':
            $cite = (string) ($block['cite'] ?? '');
            return '<blockquote><p>' . blog_inline((string) ($block['text'] ?? '')) . '</p>'
                . ($cite !== '' ? '<cite>' . e($cite) . '</cite>' : '') . '</blockquote>';
        case 'callout':
            return '<aside class="callout"><strong>' . e((string) ($block['title'] ?? '')) . '</strong><p>'
                . blog_inline((string) ($block['text'] ?? '')) . '</p></aside>';
        case 'list':
            $items = '';
            foreach ((array) ($block['items'] ?? []) as $item) {
                $items .= '<li>' . blog_inline((string) $item) . '</li>';
            }
            return '<ul>' . $items . '</ul>';
        case 'chips':
            $chips = '';
            foreach ((array) ($block['items'] ?? []) as $item) {
                $tone = preg_replace('/[^a-z]/', '', (string) ($item['tone'] ?? 'cyan'));
                $chips .= "<div class=\"chip tone-{$tone}\"><b>" . e((string) ($item['k'] ?? '')) . '</b><span>' . e((string) ($item['v'] ?? '')) . '</span></div>';
            }
            return '<div class="chips">' . $chips . '</div>';
        case 'video':
            return blog_video($block);
    }
    return '';
}

function blog_initials(string $name): string
{
    $parts = preg_split('/\s+/u', trim($name)) ?: [];
    $first = function_exists('mb_substr') ? mb_substr((string) ($parts[0] ?? '?'), 0, 1) : substr((string) ($parts[0] ?? '?'), 0, 1);
    $last = count($parts) > 1 ? (function_exists('mb_substr') ? mb_substr((string) end($parts), 0, 1) : substr((string) end($parts), 0, 1)) : '';
    return function_exists('mb_strtoupper') ? mb_strtoupper($first . $last) : strtoupper($first . $last);
}

// --- Routing -----------------------------------------------------------------

$slug = (string) ($_GET['post'] ?? '');
$article = $slug !== '' && BlogStore::validSlug($slug) ? $store->article($slug) : null;
$notFound = $slug !== '' && $article === null;
$formError = '';
$formName = '';
$formBody = '';
$csrf = '';

if ($article !== null) {
    session_start();
    if (empty($_SESSION['blog_csrf'])) {
        $_SESSION['blog_csrf'] = bin2hex(random_bytes(16));
    }
    $csrf = (string) $_SESSION['blog_csrf'];
    $formName = (string) ($_SESSION['blog_name'] ?? '');

    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
        $formName = trim((string) ($_POST['name'] ?? ''));
        $formBody = trim((string) ($_POST['comment'] ?? ''));
        $now = time();
        if (!hash_equals($csrf, (string) ($_POST['token'] ?? ''))) {
            $formError = 'Your session expired. Please post again.';
        } elseif (trim((string) ($_POST['website'] ?? '')) !== '') {
            // Honeypot field: people never see it, bots fill it in. Pretend it worked.
            header('Location: blog.php?post=' . rawurlencode($slug) . '#comments', true, 303);
            exit;
        } elseif ($now - (int) ($_SESSION['blog_last_comment'] ?? 0) < BLOG_COMMENT_COOLDOWN) {
            $formError = 'Please wait a few seconds before posting again.';
        } else {
            $result = $store->addComment($slug, $formName, $formBody);
            if ($result['ok']) {
                $_SESSION['blog_last_comment'] = $now;
                $_SESSION['blog_name'] = $formName;
                header('Location: blog.php?post=' . rawurlencode($slug) . '&posted=1#' . $result['id'], true, 303);
                exit;
            }
            $formError = $result['error'];
        }
    }
}

if ($notFound) {
    http_response_code(404);
}
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: strict-origin-when-cross-origin');

$articles = $store->articles();
$pageTitle = $article !== null ? (string) $article['title'] . ' · ' . BLOG_NAME : BLOG_NAME . ' · Notes on verifiable AI';
$pageDescription = $article !== null ? (string) $article['dek'] : 'An independent blog about AI, how language models work, and the meaning-first approach AtomGraph is developing with VeriWave.';
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= e($pageTitle) ?></title>
<meta name="description" content="<?= e($pageDescription) ?>">
<meta name="color-scheme" content="dark">
<style>
:root {
    --bg: #05060d; --panel: rgba(18, 21, 38, .72); --line: rgba(160, 175, 255, .14);
    --ink: #eef0fb; --soft: #a9aecb; --dim: #6f7598;
    --cyan: #5ee6ff; --violet: #a78bfa; --amber: #ffc46b; --green: #6ff0b1; --red: #ff7d9c;
    --serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
    --sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--sans); line-height: 1.6; -webkit-font-smoothing: antialiased; overflow-x: hidden; }
a { color: inherit; }
img, svg { max-width: 100%; }
.aurora { position: fixed; inset: 0; z-index: -2; pointer-events: none;
    background:
        radial-gradient(60vw 50vh at 12% -8%, rgba(94, 230, 255, .16), transparent 70%),
        radial-gradient(55vw 55vh at 92% 8%, rgba(167, 139, 250, .2), transparent 70%),
        radial-gradient(70vw 60vh at 50% 110%, rgba(255, 125, 156, .1), transparent 70%); }
.grain { position: fixed; inset: 0; z-index: -1; pointer-events: none; opacity: .5;
    background-image: linear-gradient(rgba(160, 175, 255, .035) 1px, transparent 1px), linear-gradient(90deg, rgba(160, 175, 255, .035) 1px, transparent 1px);
    background-size: 56px 56px; mask-image: radial-gradient(ellipse at 50% 20%, #000 20%, transparent 75%); -webkit-mask-image: radial-gradient(ellipse at 50% 20%, #000 20%, transparent 75%); }
.wrap { width: min(1180px, 100% - 40px); margin-inline: auto; }

/* nav */
.nav { position: sticky; top: 0; z-index: 30; backdrop-filter: blur(16px) saturate(1.4); -webkit-backdrop-filter: blur(16px) saturate(1.4); background: rgba(5, 6, 13, .62); border-bottom: 1px solid var(--line); }
.nav .wrap { display: flex; align-items: center; justify-content: space-between; gap: 16px; height: 62px; }
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; font-family: var(--serif); font-size: 21px; letter-spacing: -.01em; }
.brand i { width: 26px; height: 26px; border-radius: 50%; background: conic-gradient(from 210deg, var(--cyan), var(--violet), var(--red), var(--amber), var(--cyan)); box-shadow: 0 0 22px rgba(120, 160, 255, .55); position: relative; }
.brand i::after { content: ""; position: absolute; inset: 6px; border-radius: 50%; background: var(--bg); }
.nav nav { display: flex; gap: 22px; font-size: 14px; color: var(--soft); }
.nav nav a { text-decoration: none; white-space: nowrap; }
.nav nav a:hover { color: var(--ink); }
.progress { position: fixed; top: 0; left: 0; height: 3px; width: 0; z-index: 40; background: linear-gradient(90deg, var(--cyan), var(--violet), var(--red)); box-shadow: 0 0 14px rgba(140, 150, 255, .8); }

/* hero */
.hero { position: relative; min-height: min(86vh, 760px); display: grid; align-items: center; isolation: isolate; }
.hero canvas { position: absolute; inset: 0; width: 100%; height: 100%; z-index: -2; mask-image: linear-gradient(#000 70%, transparent); -webkit-mask-image: linear-gradient(#000 70%, transparent); }
.hero::before { content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none; background: radial-gradient(70% 80% at 22% 45%, rgba(5, 6, 13, .78), transparent 75%); }
.hero .wrap { padding: 80px 0 90px; }
.eyebrow { font-family: var(--mono); font-size: 12px; letter-spacing: .22em; text-transform: uppercase; color: var(--cyan); display: inline-flex; align-items: center; gap: 10px; }
.eyebrow::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 12px var(--cyan); animation: pulse 2.4s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: .35; transform: scale(.7); } }
.hero h1 { font-family: var(--serif); font-weight: 500; font-size: clamp(42px, 8.2vw, 104px); line-height: .98; letter-spacing: -.035em; margin: 22px 0 24px; max-width: 12ch; text-wrap: balance; }
.grad { background: linear-gradient(100deg, var(--cyan) 5%, var(--violet) 45%, var(--red) 80%, var(--amber)); background-size: 220% 100%; -webkit-background-clip: text; background-clip: text; color: transparent; font-style: italic; animation: sheen 9s ease-in-out infinite alternate; padding-right: .08em; }
@keyframes sheen { to { background-position: 100% 0; } }
.hero p.lead { font-size: clamp(17px, 2vw, 21px); color: var(--soft); max-width: 56ch; margin: 0 0 34px; }
.cta { display: flex; flex-wrap: wrap; gap: 12px; }
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 13px 22px; border-radius: 999px; font-weight: 600; font-size: 15px; text-decoration: none; border: 1px solid var(--line); background: rgba(255, 255, 255, .04); color: var(--ink); cursor: pointer; font-family: inherit; transition: transform .2s, box-shadow .2s, background .2s; }
.btn:hover { transform: translateY(-2px); background: rgba(255, 255, 255, .08); }
.btn.primary { border: 0; color: #060714; background: linear-gradient(100deg, var(--cyan), var(--violet)); box-shadow: 0 10px 40px -10px rgba(120, 150, 255, .8); }
.btn.primary:hover { box-shadow: 0 14px 50px -8px rgba(120, 150, 255, 1); }
.ticker { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 46px; font-family: var(--mono); font-size: 12px; color: var(--dim); }
.ticker span { border: 1px solid var(--line); border-radius: 6px; padding: 4px 9px; background: rgba(10, 12, 24, .6); }
.ticker b { color: var(--cyan); font-weight: 500; }

/* sections */
section { padding: 34px 0 70px; }
.sec-head { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 28px; }
.sec-head h2 { font-family: var(--serif); font-weight: 500; font-size: clamp(28px, 4vw, 42px); letter-spacing: -.02em; margin: 0; line-height: 1.1; }
.sec-head p { margin: 6px 0 0; color: var(--soft); max-width: 60ch; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; }
.filters button { font: inherit; font-size: 13px; color: var(--soft); background: transparent; border: 1px solid var(--line); border-radius: 999px; padding: 7px 14px; cursor: pointer; transition: all .2s; }
.filters button:hover { color: var(--ink); border-color: rgba(160, 175, 255, .4); }
.filters button[aria-pressed="true"] { color: #060714; background: var(--ink); border-color: var(--ink); }

/* cards */
.grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 22px; }
.card { grid-column: span 4; position: relative; display: flex; flex-direction: column; border-radius: 20px; overflow: hidden; background: var(--panel); border: 1px solid var(--line); text-decoration: none; transition: transform .35s cubic-bezier(.2, .8, .2, 1), border-color .3s, box-shadow .35s; transform-style: preserve-3d; }
.card::before { content: ""; position: absolute; inset: 0; z-index: 2; pointer-events: none; opacity: 0; transition: opacity .3s; background: radial-gradient(420px circle at var(--mx, 50%) var(--my, 0%), rgba(150, 190, 255, .16), transparent 60%); }
.card:hover { transform: translateY(-6px); border-color: rgba(160, 190, 255, .4); box-shadow: 0 30px 70px -30px rgba(90, 120, 255, .65); }
.card:hover::before { opacity: 1; }
.card .cover { display: block; width: 100%; aspect-ratio: 2 / 1; transition: transform .8s cubic-bezier(.2, .8, .2, 1); }
.card:hover .cover { transform: scale(1.06); }
.card .art { overflow: hidden; }
.card .body { padding: 22px 24px 24px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
.card h3 { font-family: var(--serif); font-weight: 500; font-size: 23px; line-height: 1.2; letter-spacing: -.015em; margin: 0; text-wrap: balance; }
.card p { margin: 0; color: var(--soft); font-size: 15px; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-family: var(--mono); font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(94, 230, 255, .3); border-radius: 5px; padding: 2px 7px; }
.tag:nth-child(2) { color: var(--violet); border-color: rgba(167, 139, 250, .35); }
.meta { margin-top: auto; padding-top: 8px; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; color: var(--dim); }
.card.feature { grid-column: span 12; flex-direction: row; min-height: 380px; }
.card.feature .art { flex: 1.25; min-width: 0; }
.card.feature .cover { height: 100%; aspect-ratio: auto; }
.card.feature .body { flex: 1; padding: 40px; justify-content: center; gap: 16px; }
.card.feature h3 { font-size: clamp(28px, 3.4vw, 42px); line-height: 1.08; }
.card.feature p { font-size: 17px; }
.card[hidden] { display: none; }

/* video rail */
.rail { display: grid; grid-auto-flow: column; grid-auto-columns: min(340px, 78vw); gap: 18px; overflow-x: auto; padding: 4px 4px 18px; scroll-snap-type: x mandatory; scrollbar-color: rgba(160, 175, 255, .3) transparent; }
.rail .video { scroll-snap-align: start; margin: 0; }
.video { margin: 34px 0; }
.yt { position: relative; display: block; width: 100%; aspect-ratio: 16 / 9; padding: 0; border: 1px solid var(--line); border-radius: 16px; overflow: hidden; cursor: pointer; background: linear-gradient(135deg, #131a3a, #2a1446); box-shadow: 0 24px 60px -30px rgba(90, 120, 255, .7); }
.yt img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .82; transition: transform .6s, opacity .3s; }
.yt:hover img { transform: scale(1.05); opacity: 1; }
.yt::after { content: ""; position: absolute; inset: 0; background: linear-gradient(transparent 45%, rgba(5, 6, 13, .75)); }
.yt .play { position: absolute; z-index: 2; left: 50%; top: 50%; width: 72px; height: 72px; margin: -36px 0 0 -36px; border-radius: 50%; display: grid; place-items: center; color: #060714; background: linear-gradient(120deg, var(--cyan), var(--violet)); box-shadow: 0 0 0 0 rgba(140, 170, 255, .6); animation: ring 2.6s infinite; transition: transform .25s; }
.yt:hover .play { transform: scale(1.1); }
@keyframes ring { 70% { box-shadow: 0 0 0 22px rgba(140, 170, 255, 0); } 100% { box-shadow: 0 0 0 0 rgba(140, 170, 255, 0); } }
.yt iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; z-index: 3; }
.video figcaption { display: flex; flex-direction: column; gap: 2px; margin-top: 12px; }
.video .vt { font-weight: 600; font-size: 15px; line-height: 1.35; }
.video .vc { color: var(--dim); font-size: 13px; }
.video .vc a { color: var(--soft); }
.rail-link { font-size: 13px; color: var(--soft); margin-top: 6px; display: inline-block; }

/* principles band */
.band { border-block: 1px solid var(--line); background: linear-gradient(90deg, rgba(94, 230, 255, .05), rgba(167, 139, 250, .07), rgba(255, 125, 156, .05)); overflow: hidden; padding: 20px 0; }
.marquee { display: flex; gap: 56px; width: max-content; animation: slide 46s linear infinite; font-family: var(--serif); font-style: italic; font-size: clamp(20px, 2.6vw, 30px); color: var(--soft); white-space: nowrap; }
.marquee span::after { content: "◆"; font-style: normal; font-size: .5em; margin-left: 56px; color: var(--violet); vertical-align: middle; }
@keyframes slide { to { transform: translateX(-50%); } }

/* article */
.post-hero { position: relative; isolation: isolate; padding: 60px 0 0; }
.post-hero .back { font-size: 14px; color: var(--soft); text-decoration: none; }
.post-hero .back:hover { color: var(--ink); }
.post-hero h1 { font-family: var(--serif); font-weight: 500; font-size: clamp(34px, 6vw, 68px); line-height: 1.04; letter-spacing: -.03em; margin: 22px 0 18px; max-width: 20ch; text-wrap: balance; }
.post-hero .dek { font-size: clamp(18px, 2.1vw, 22px); color: var(--soft); max-width: 62ch; margin: 0 0 22px; }
.post-hero .meta { font-size: 14px; margin: 0 0 34px; }
.post-cover { border-radius: 24px; overflow: hidden; border: 1px solid var(--line); box-shadow: 0 50px 120px -50px rgba(90, 120, 255, .8); }
.post-cover .cover { display: block; width: 100%; aspect-ratio: 21 / 9; }
.prose { width: min(720px, 100%); margin: 56px auto 0; font-family: var(--serif); font-size: 20px; line-height: 1.72; color: #dfe2f3; }
.prose > p:first-child::first-letter { float: left; font-size: 4.1em; line-height: .82; padding: .08em .12em 0 0; background: linear-gradient(140deg, var(--cyan), var(--violet)); -webkit-background-clip: text; background-clip: text; color: transparent; }
.prose h2 { font-weight: 500; font-size: 32px; line-height: 1.15; letter-spacing: -.02em; color: var(--ink); margin: 54px 0 14px; }
.prose p { margin: 0 0 22px; }
.prose strong { color: var(--ink); }
.prose code { font-family: var(--mono); font-size: .8em; color: var(--cyan); background: rgba(94, 230, 255, .08); border: 1px solid rgba(94, 230, 255, .22); border-radius: 6px; padding: 2px 7px; white-space: nowrap; }
.prose ul { padding-left: 0; list-style: none; margin: 0 0 24px; }
.prose li { position: relative; padding-left: 30px; margin-bottom: 12px; }
.prose li::before { content: ""; position: absolute; left: 6px; top: .66em; width: 8px; height: 8px; border-radius: 50%; background: var(--violet); box-shadow: 0 0 10px var(--violet); }
.prose blockquote { margin: 44px 0; padding: 6px 0 6px 28px; border-left: 3px solid; border-image: linear-gradient(var(--cyan), var(--violet), var(--red)) 1; }
.prose blockquote p { font-style: italic; font-size: 1.42em; line-height: 1.3; color: var(--ink); margin: 0 0 10px; text-wrap: balance; }
.prose cite { font-family: var(--sans); font-style: normal; font-size: 14px; color: var(--dim); }
.callout { font-family: var(--sans); font-size: 15.5px; line-height: 1.6; margin: 34px 0; padding: 18px 22px; border-radius: 14px; border: 1px solid rgba(255, 196, 107, .32); background: rgba(255, 196, 107, .07); color: #f1e3c8; }
.callout strong { display: block; font-family: var(--mono); font-size: 11.5px; letter-spacing: .16em; text-transform: uppercase; color: var(--amber); margin-bottom: 6px; }
.callout p { margin: 0; }
.chips { font-family: var(--sans); display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; margin: 30px 0 34px; }
.chip { --c: var(--cyan); display: flex; flex-direction: column; gap: 3px; padding: 13px 15px; border-radius: 12px; background: rgba(14, 17, 32, .8); border: 1px solid var(--line); border-left: 3px solid var(--c); transition: transform .2s, box-shadow .2s; }
.chip:hover { transform: translateY(-3px); box-shadow: 0 14px 30px -18px var(--c); }
.chip b { font-family: var(--mono); font-size: 13.5px; letter-spacing: .06em; color: var(--c); font-weight: 600; }
.chip span { font-size: 13.5px; line-height: 1.4; color: var(--soft); }
.tone-violet { --c: var(--violet); } .tone-amber { --c: var(--amber); } .tone-green { --c: var(--green); } .tone-red { --c: var(--red); }
.prose .video { font-family: var(--sans); }

/* comments */
.comments { width: min(720px, 100%); margin: 70px auto 0; }
.comments h2 { font-family: var(--serif); font-weight: 500; font-size: 32px; letter-spacing: -.02em; margin: 0 0 6px; }
.comments .sub { color: var(--soft); margin: 0 0 26px; }
.comment { display: flex; gap: 14px; padding: 18px; border-radius: 16px; background: var(--panel); border: 1px solid var(--line); margin-bottom: 12px; scroll-margin-top: 90px; }
.comment:target { border-color: var(--cyan); box-shadow: 0 0 0 4px rgba(94, 230, 255, .12); }
.avatar { flex: none; width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; font-size: 14px; color: #060714; }
.comment .who { font-weight: 600; }
.comment time { color: var(--dim); font-size: 13px; margin-left: 8px; }
.comment .text { margin: 4px 0 0; color: #d6d9ec; white-space: pre-line; overflow-wrap: anywhere; }
.empty { padding: 26px; text-align: center; color: var(--soft); border: 1px dashed var(--line); border-radius: 16px; margin-bottom: 12px; }
.form { margin-top: 26px; padding: 24px; border-radius: 20px; background: var(--panel); border: 1px solid var(--line); display: grid; gap: 14px; scroll-margin-top: 90px; }
.form label { display: grid; gap: 6px; font-size: 14px; color: var(--soft); }
.form input[type=text], .form textarea { font: inherit; font-size: 16px; color: var(--ink); background: rgba(5, 6, 13, .7); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; width: 100%; transition: border-color .2s, box-shadow .2s; }
.form textarea { min-height: 130px; resize: vertical; }
.form input:focus, .form textarea:focus { outline: none; border-color: var(--cyan); box-shadow: 0 0 0 4px rgba(94, 230, 255, .14); }
.form .row { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.form .count { font-size: 13px; color: var(--dim); font-variant-numeric: tabular-nums; }
.hp { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }
.notice { padding: 12px 16px; border-radius: 12px; font-size: 15px; }
.notice.err { color: #ffc2d0; background: rgba(255, 125, 156, .1); border: 1px solid rgba(255, 125, 156, .4); }
.notice.ok { color: #c9f7df; background: rgba(111, 240, 177, .09); border: 1px solid rgba(111, 240, 177, .35); margin-bottom: 14px; }

.more { margin-top: 90px; }
footer { margin-top: 60px; border-top: 1px solid var(--line); padding: 34px 0 50px; color: var(--dim); font-size: 13.5px; }
footer .wrap { display: grid; gap: 10px; }
footer a { color: var(--soft); }
.reveal { opacity: 0; transform: translateY(26px); transition: opacity .8s cubic-bezier(.2, .8, .2, 1), transform .8s cubic-bezier(.2, .8, .2, 1); }
.reveal.in { opacity: 1; transform: none; }
.no-js .reveal { opacity: 1; transform: none; }
:focus-visible { outline: 2px solid var(--cyan); outline-offset: 3px; }

@media (max-width: 960px) {
    .card { grid-column: span 6; }
    .card.feature { flex-direction: column; min-height: 0; }
    .card.feature .cover { aspect-ratio: 2 / 1; height: auto; }
    .card.feature .body { padding: 26px; }
}
@media (max-width: 640px) {
    .wrap { width: calc(100% - 32px); }
    .card { grid-column: span 12; }
    .nav nav { gap: 14px; font-size: 13px; }
    .nav nav .opt { display: none; }
    .hero .wrap { padding: 56px 0 70px; }
    .prose { font-size: 18px; }
    .prose h2 { font-size: 26px; }
    .post-cover .cover { aspect-ratio: 16 / 10; }
    .post-cover { border-radius: 16px; }
}
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
    html { scroll-behavior: auto; }
    .reveal { opacity: 1; transform: none; }
}
</style>
</head>
<body class="no-js">
<script>document.body.classList.remove('no-js');</script>
<div class="aurora"></div>
<div class="grain"></div>
<?php if ($article !== null): ?><div class="progress" id="progress"></div><?php endif; ?>

<div class="nav">
    <div class="wrap">
        <a class="brand" href="blog.php"><i></i><?= e(BLOG_NAME) ?></a>
        <nav>
            <a href="blog.php#articles">Articles</a>
            <a href="blog.php#videos">Videos</a>
            <a class="opt" href="https://atomgraph.ai/" target="_blank" rel="noopener">AtomGraph ↗</a>
            <a class="opt" href="index.php">Studio</a>
        </nav>
    </div>
</div>

<?php if ($notFound): ?>
<main class="wrap" style="padding:120px 0;text-align:center">
    <div class="eyebrow">Status: Unknown</div>
    <h1 style="font-family:var(--serif);font-weight:500;font-size:clamp(36px,6vw,64px);margin:20px 0 12px">That article isn't in the record.</h1>
    <p style="color:var(--soft);margin:0 0 28px">We decline rather than invent one.</p>
    <a class="btn primary" href="blog.php">Back to all articles</a>
</main>

<?php elseif ($article !== null):
    $comments = $store->comments($slug);
?>
<main>
    <header class="post-hero">
        <div class="wrap">
            <a class="back" href="blog.php#articles">← All articles</a>
            <div class="tags" style="margin-top:26px"><?php foreach ($article['tags'] as $tag): ?><span class="tag"><?= e($tag) ?></span><?php endforeach; ?></div>
            <h1><?= e((string) $article['title']) ?></h1>
            <p class="dek"><?= e((string) $article['dek']) ?></p>
            <p class="meta"><span><?= e((string) ($article['author'] ?? '')) ?></span><span><?= e(blog_date((string) ($article['date'] ?? ''))) ?></span><span><?= (int) $article['read_minutes'] ?> min read</span><a href="#comments"><?= count($comments) ?> comment<?= count($comments) === 1 ? '' : 's' ?></a></p>
            <div class="post-cover reveal"><?= blog_cover($article, 'p') ?></div>
        </div>
    </header>

    <div class="wrap">
        <article class="prose" id="prose">
            <?php foreach ($article['blocks'] as $block) { echo blog_block($block), "\n"; } ?>
        </article>

        <section class="comments" id="comments">
            <h2>Discussion</h2>
            <p class="sub"><?= count($comments) === 0 ? 'No comments yet.' : count($comments) . ' comment' . (count($comments) === 1 ? '' : 's') . '.' ?> Disagreement is welcome. Bring a source if you can.</p>
            <?php if (isset($_GET['posted'])): ?><div class="notice ok" role="status">Your comment is posted. Thank you.</div><?php endif; ?>
            <?php if ($comments === []): ?>
                <div class="empty">Be the first to add to the record.</div>
            <?php endif; ?>
            <?php foreach ($comments as $comment):
                $hue = crc32($comment['name']) % 360; ?>
                <div class="comment" id="<?= e($comment['id']) ?>">
                    <div class="avatar" style="background:linear-gradient(135deg,hsl(<?= $hue ?> 90% 70%),hsl(<?= ($hue + 70) % 360 ?> 90% 68%))" aria-hidden="true"><?= e(blog_initials($comment['name'])) ?></div>
                    <div>
                        <span class="who"><?= e($comment['name']) ?></span><time datetime="<?= e($comment['at']) ?>"><?= e(blog_date($comment['at'])) ?></time>
                        <p class="text"><?= e($comment['body']) ?></p>
                    </div>
                </div>
            <?php endforeach; ?>

            <form class="form" id="comment-form" method="post" action="blog.php?post=<?= e(rawurlencode($slug)) ?>#comment-form">
                <?php if ($formError !== ''): ?><div class="notice err" role="alert"><?= e($formError) ?></div><?php endif; ?>
                <input type="hidden" name="token" value="<?= e($csrf) ?>">
                <div class="hp" aria-hidden="true"><label>Leave this field empty <input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>
                <label>Name
                    <input type="text" name="name" maxlength="<?= BlogStore::MAX_NAME ?>" required autocomplete="name" value="<?= e($formName) ?>">
                </label>
                <label>Comment
                    <textarea name="comment" id="comment-body" maxlength="<?= BlogStore::MAX_BODY ?>" required><?= e($formBody) ?></textarea>
                </label>
                <div class="row">
                    <span class="count"><span id="count">0</span> / <?= BlogStore::MAX_BODY ?></span>
                    <button class="btn primary" type="submit">Post comment</button>
                </div>
            </form>
        </section>
    </div>

    <section class="more">
        <div class="wrap">
            <div class="sec-head"><h2>Keep reading</h2></div>
            <div class="grid">
                <?php $shown = 0; foreach ($articles as $i => $other):
                    if ($other['slug'] === $slug || $shown >= 3) { continue; }
                    $shown++; ?>
                    <a class="card reveal" href="blog.php?post=<?= e((string) $other['slug']) ?>">
                        <div class="art"><?= blog_cover($other, 'm' . $i) ?></div>
                        <div class="body">
                            <h3><?= e((string) $other['title']) ?></h3>
                            <div class="meta"><span><?= e(blog_date((string) ($other['date'] ?? ''))) ?></span><span><?= (int) $other['read_minutes'] ?> min read</span></div>
                        </div>
                    </a>
                <?php endforeach; ?>
            </div>
        </div>
    </section>
</main>

<?php else: ?>
<header class="hero">
    <canvas id="graph" aria-hidden="true"></canvas>
    <div class="wrap">
        <div class="eyebrow">Notes on verifiable AI</div>
        <h1>Can a machine <span class="grad">show its work?</span></h1>
        <p class="lead">An independent blog about how today's AI really works, and about the meaning-first engine AtomGraph is developing with VeriWave: structured knowledge, evidence labels, and answers designed to be traced back to their sources.</p>
        <div class="cta">
            <a class="btn primary" href="blog.php?post=<?= e((string) $articles[0]['slug']) ?>">Start with VeriWave →</a>
            <a class="btn" href="#videos">▶ Watch the video library</a>
        </div>
        <div class="ticker" aria-hidden="true">
            <span><b>EVT</b>:replace(object=Pump P-40)</span><span><b>SRC</b>:MP-112 rev. C</span><span><b>status</b>:Verified</span><span><b>Δt</b>:nothing silently overwritten</span>
        </div>
    </div>
</header>

<div class="band" aria-label="AtomGraph's five stated principles">
    <div class="marquee">
        <?php for ($loop = 0; $loop < 2; $loop++): foreach (['Meaning before wording', 'Evidence before assertion', 'Structure before speculation', 'Safety within the architecture', 'Cumulative intelligence'] as $principle): ?>
            <span<?= $loop ? ' aria-hidden="true"' : '' ?>><?= e($principle) ?></span>
        <?php endforeach; endfor; ?>
    </div>
</div>

<main>
    <section id="articles">
        <div class="wrap">
            <div class="sec-head" style="margin-top:40px">
                <div>
                    <h2>Latest articles</h2>
                    <p>Every piece includes at least one video, and every one is open for comments.</p>
                </div>
                <div class="filters" role="group" aria-label="Filter articles by topic">
                    <button type="button" data-filter="" aria-pressed="true">All</button>
                    <?php foreach ($store->tags() as $tag): ?>
                        <button type="button" data-filter="<?= e($tag) ?>" aria-pressed="false"><?= e($tag) ?></button>
                    <?php endforeach; ?>
                </div>
            </div>
            <div class="grid" id="grid">
                <?php foreach ($articles as $i => $item):
                    $count = $store->commentCount((string) $item['slug']); ?>
                    <a class="card reveal<?= $i === 0 ? ' feature' : '' ?>" href="blog.php?post=<?= e((string) $item['slug']) ?>" data-tags="<?= e(implode('|', $item['tags'])) ?>">
                        <div class="art"><?= blog_cover($item, 'c' . $i) ?></div>
                        <div class="body">
                            <div class="tags"><?php foreach ($item['tags'] as $tag): ?><span class="tag"><?= e($tag) ?></span><?php endforeach; ?></div>
                            <h3><?= e((string) $item['title']) ?></h3>
                            <p><?= e((string) $item['dek']) ?></p>
                            <div class="meta"><span><?= e(blog_date((string) ($item['date'] ?? ''))) ?></span><span><?= (int) $item['read_minutes'] ?> min read</span><span><?= $count ?> comment<?= $count === 1 ? '' : 's' ?></span></div>
                        </div>
                    </a>
                <?php endforeach; ?>
            </div>
        </div>
    </section>

    <section id="videos">
        <div class="wrap">
            <div class="sec-head">
                <div>
                    <h2>The video library</h2>
                    <p>Every video featured on the blog, in one place. Press play to load it here.</p>
                </div>
            </div>
            <div class="rail reveal" tabindex="0" aria-label="Featured videos">
                <?php foreach ($store->videos() as $video): ?>
                    <div>
                        <?= blog_video($video) ?>
                        <a class="rail-link" href="blog.php?post=<?= e($video['slug']) ?>">Read the article →</a>
                    </div>
                <?php endforeach; ?>
            </div>
        </div>
    </section>
</main>
<?php endif; ?>

<footer>
    <div class="wrap">
        <div><?= e(BLOG_NAME) ?> is an independent blog. It is not affiliated with or endorsed by AtomGraph Inc. Descriptions of VeriWave are drawn from <a href="https://atomgraph.ai/" target="_blank" rel="noopener">atomgraph.ai</a>; VeriWave is in development and the capabilities described are the company's stated design objectives.</div>
        <div>Videos belong to their creators and play from YouTube. <a href="blog.php">Home</a> · <a href="index.php">Book Intelligence Studio</a></div>
    </div>
</footer>

<script>
(function () {
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Click-to-load YouTube players: nothing is fetched from YouTube's player until asked.
    document.addEventListener('click', function (event) {
        var button = event.target.closest('.yt');
        if (!button || button.querySelector('iframe')) { return; }
        var frame = document.createElement('iframe');
        frame.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(button.dataset.yt) + '?autoplay=1&rel=0';
        frame.title = button.dataset.title || 'Video';
        frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
        frame.referrerPolicy = 'strict-origin-when-cross-origin';
        frame.allowFullscreen = true;
        button.appendChild(frame);
    });

    // Scroll reveal.
    var reveals = document.querySelectorAll('.reveal');
    if ('IntersectionObserver' in window && !reduce) {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) { entry.target.classList.add('in'); observer.unobserve(entry.target); }
            });
        }, { rootMargin: '0px 0px -8% 0px' });
        reveals.forEach(function (el, i) { el.style.transitionDelay = (i % 3) * 90 + 'ms'; observer.observe(el); });
    } else {
        reveals.forEach(function (el) { el.classList.add('in'); });
    }

    // Card spotlight follows the pointer.
    document.querySelectorAll('.card').forEach(function (card) {
        card.addEventListener('pointermove', function (event) {
            var rect = card.getBoundingClientRect();
            card.style.setProperty('--mx', (event.clientX - rect.left) + 'px');
            card.style.setProperty('--my', (event.clientY - rect.top) + 'px');
        });
    });

    // Topic filters.
    var filters = document.querySelectorAll('.filters button');
    filters.forEach(function (button) {
        button.addEventListener('click', function () {
            filters.forEach(function (b) { b.setAttribute('aria-pressed', String(b === button)); });
            var wanted = button.dataset.filter;
            document.querySelectorAll('#grid .card').forEach(function (card, index) {
                var match = !wanted || card.dataset.tags.split('|').indexOf(wanted) !== -1;
                card.hidden = !match;
                card.classList.toggle('feature', !wanted && index === 0);
                card.classList.add('in');
            });
        });
    });

    // Reading progress.
    var bar = document.getElementById('progress');
    var prose = document.getElementById('prose');
    if (bar && prose) {
        var update = function () {
            var rect = prose.getBoundingClientRect();
            var total = rect.height - window.innerHeight * 0.5;
            var done = Math.min(1, Math.max(0, (window.innerHeight * 0.5 - rect.top) / Math.max(1, total)));
            bar.style.width = (done * 100) + '%';
        };
        window.addEventListener('scroll', update, { passive: true });
        window.addEventListener('resize', update);
        update();
    }

    // Comment character counter.
    var body = document.getElementById('comment-body');
    var count = document.getElementById('count');
    if (body && count) {
        var tick = function () { count.textContent = body.value.length; };
        body.addEventListener('input', tick);
        tick();
    }

    // Hero: a living knowledge graph of typed nodes.
    var canvas = document.getElementById('graph');
    if (!canvas) { return; }
    var ctx = canvas.getContext('2d');
    var labels = ['ENT', 'AGT', 'PRP', 'EVT', 'CAU', 'RUL', 'GOL', 'AGR', 'SRC', 'Δt'];
    var hues = [188, 188, 188, 262, 262, 262, 38, 38, 152, 152];
    var nodes = [], width = 0, height = 0, dpr = 1, pointer = { x: -9999, y: -9999 }, pulses = [];
    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        width = canvas.clientWidth; height = canvas.clientHeight;
        canvas.width = width * dpr; canvas.height = height * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        var wanted = Math.max(26, Math.min(80, Math.round(width * height / 15000)));
        nodes = [];
        for (var i = 0; i < wanted; i++) {
            var kind = i % labels.length;
            nodes.push({
                x: Math.random() * width, y: Math.random() * height,
                vx: (Math.random() - .5) * .28, vy: (Math.random() - .5) * .28,
                r: 1.6 + Math.random() * 3.4, kind: kind, labelled: i % 4 === 0
            });
        }
    }
    function frame() {
        ctx.clearRect(0, 0, width, height);
        var reach = Math.min(190, width * .22 + 60);
        for (var i = 0; i < nodes.length; i++) {
            var a = nodes[i];
            a.x += a.vx; a.y += a.vy;
            if (a.x < -20) { a.x = width + 20; } else if (a.x > width + 20) { a.x = -20; }
            if (a.y < -20) { a.y = height + 20; } else if (a.y > height + 20) { a.y = -20; }
            var pd = Math.hypot(a.x - pointer.x, a.y - pointer.y);
            a.glow = pd < 200 ? 1 - pd / 200 : 0;
            for (var j = i + 1; j < nodes.length; j++) {
                var b = nodes[j], d = Math.hypot(a.x - b.x, a.y - b.y);
                if (d < reach) {
                    var alpha = (1 - d / reach) * (.22 + .5 * Math.max(a.glow, b.glow || 0));
                    ctx.strokeStyle = 'hsla(' + hues[a.kind] + ',90%,72%,' + alpha + ')';
                    ctx.lineWidth = 1;
                    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
                    if (Math.random() < .0009 && pulses.length < 14) { pulses.push({ a: a, b: b, t: 0 }); }
                }
            }
        }
        for (var p = pulses.length - 1; p >= 0; p--) {
            var pulse = pulses[p];
            pulse.t += .016;
            if (pulse.t >= 1) { pulses.splice(p, 1); continue; }
            var px = pulse.a.x + (pulse.b.x - pulse.a.x) * pulse.t, py = pulse.a.y + (pulse.b.y - pulse.a.y) * pulse.t;
            ctx.fillStyle = 'rgba(255,255,255,.9)';
            ctx.shadowColor = 'hsl(' + hues[pulse.a.kind] + ',100%,70%)'; ctx.shadowBlur = 12;
            ctx.beginPath(); ctx.arc(px, py, 1.8, 0, 6.283); ctx.fill();
            ctx.shadowBlur = 0;
        }
        ctx.font = '11px ui-monospace, Menlo, Consolas, monospace';
        for (var k = 0; k < nodes.length; k++) {
            var n = nodes[k], hue = hues[n.kind];
            ctx.fillStyle = 'hsla(' + hue + ',95%,' + (68 + n.glow * 20) + '%,' + (.75 + n.glow * .25) + ')';
            ctx.shadowColor = 'hsl(' + hue + ',100%,65%)'; ctx.shadowBlur = 8 + n.glow * 18;
            ctx.beginPath(); ctx.arc(n.x, n.y, n.r + n.glow * 2.5, 0, 6.283); ctx.fill();
            ctx.shadowBlur = 0;
            if (n.labelled || n.glow > .35) {
                ctx.fillStyle = 'hsla(' + hue + ',80%,82%,' + (n.labelled ? .5 + n.glow * .5 : n.glow) + ')';
                ctx.fillText(labels[n.kind], n.x + n.r + 7, n.y + 4);
            }
        }
        if (!reduce) { requestAnimationFrame(frame); }
    }
    canvas.parentElement.addEventListener('pointermove', function (event) {
        var rect = canvas.getBoundingClientRect();
        pointer.x = event.clientX - rect.left; pointer.y = event.clientY - rect.top;
    });
    canvas.parentElement.addEventListener('pointerleave', function () { pointer.x = pointer.y = -9999; });
    window.addEventListener('resize', function () { resize(); if (reduce) { frame(); } });
    resize();
    frame();
})();
</script>
</body>
</html>
