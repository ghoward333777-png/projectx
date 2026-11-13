<?php

declare(strict_types=1);

/**
 * Online magazine front controller. Dependency-free: flat-file storage, no Composer, no database.
 * Run locally with:  php -S 127.0.0.1:8083 -t magazine
 */

require_once __DIR__ . '/MagazineStore.php';
require_once __DIR__ . '/MagazineAuth.php';
require_once __DIR__ . '/BotShield.php';
require_once __DIR__ . '/MagazineMarkup.php';
require_once __DIR__ . '/MagazineShop.php';

const PER_PAGE = 12;

/** Settings come from magazine/config.php when present; environment variables win. */
function magazine_config(): array
{
    $config = [
        'site_name' => 'The Pro-Human Review',
        'tagline' => 'Efficient, local, verifiable, auditable AI, for the people who lead.',
        'base_url' => '',
        'timezone' => 'UTC',
        'data_dir' => __DIR__ . '/data',
        'google_client_id' => '',
        'google_client_secret' => '',
        'turnstile_site_key' => '',
        'turnstile_secret' => '',
        'admin_emails' => [],
        'pow_max' => 50000,
    ];
    if (is_file(__DIR__ . '/config.php')) {
        $config = array_merge($config, (array) require __DIR__ . '/config.php');
    }
    foreach (array_keys($config) as $key) {
        $env = getenv('MAGAZINE_' . strtoupper($key));
        if ($env !== false && $env !== '') {
            $config[$key] = $key === 'admin_emails' ? array_map('trim', explode(',', $env)) : (is_int($config[$key]) ? (int) $env : $env);
        }
    }
    return $config;
}

function e(?string $s): string
{
    return MagazineMarkup::e((string) $s);
}

/** @param array<string, scalar> $params */
function url(array $params = []): string
{
    return 'index.php' . ($params ? '?' . http_build_query($params) : '');
}

function base_url(array $config): string
{
    if ($config['base_url'] !== '') {
        return rtrim($config['base_url'], '/') . '/';
    }
    $https = (($_SERVER['HTTPS'] ?? '') !== '' && $_SERVER['HTTPS'] !== 'off') || ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https';
    $dir = rtrim(str_replace('\\', '/', dirname($_SERVER['SCRIPT_NAME'] ?? '/')), '/');
    return ($https ? 'https' : 'http') . '://' . ($_SERVER['HTTP_HOST'] ?? 'localhost') . $dir . '/';
}

function redirect(string $to): never
{
    header('Location: ' . $to, true, 303);
    exit;
}

function flash(?string $message = null): ?string
{
    if ($message !== null) {
        $_SESSION['flash'] = $message;
        return null;
    }
    $m = $_SESSION['flash'] ?? null;
    unset($_SESSION['flash']);
    return $m;
}

/** Only allow post-login returns to pages of this magazine. */
function safe_next(string $next): string
{
    return preg_match('~^index\.php(\?[A-Za-z0-9_=&%.-]*)?$~', $next) ? $next : url();
}

function when(int $ts): string
{
    return date('F j, Y', $ts);
}

$config = magazine_config();
date_default_timezone_set($config['timezone']);
$store = new MagazineStore($config['data_dir']);
$store->seedIfEmpty();
$auth = new MagazineAuth($store, $config);
$shield = new BotShield($store, $config);
$shop = new MagazineShop($store);
$auth->startSession();
$me = $auth->user();
$staff = MagazineAuth::isStaff($me);
$admin = $me !== null && $me['role'] === 'admin';
$ip = (string) ($_SERVER['REMOTE_ADDR'] ?? '0.0.0.0');
$page = (string) ($_GET['p'] ?? 'home');
$error = null;
$form = [];

header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: strict-origin-when-cross-origin');
header("Content-Security-Policy: default-src 'self'; img-src 'self' https: data:; style-src 'self'; "
    . "script-src 'self' https://challenges.cloudflare.com; "
    . "frame-src https://www.youtube-nocookie.com https://challenges.cloudflare.com; "
    . "base-uri 'self'; form-action 'self'; frame-ancestors 'none'");

// ---- machine endpoints ---------------------------------------------------

if ($page === 'challenge') {
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    if (!$store->hit('challenge:' . $ip, 60, 600)) {
        http_response_code(429);
        echo '{"error":"rate"}';
        exit;
    }
    echo json_encode($shield->challenge());
    exit;
}

if ($page === 'feed') {
    header('Content-Type: application/rss+xml; charset=utf-8');
    $base = base_url($config);
    echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n<rss version=\"2.0\"><channel><title>" . e($config['site_name']) . '</title><link>' . e($base)
        . '</link><description>' . e($config['tagline']) . '</description>';
    foreach (array_slice($store->liveArticles(), 0, 30) as $a) {
        $link = $base . url(['p' => 'article', 'a' => $a['slug']]);
        echo '<item><title>' . e($a['title']) . '</title><link>' . e($link) . '</link><guid>' . e($link) . '</guid><pubDate>' . date(DATE_RSS, $a['publish_at'])
            . '</pubDate><category>' . e($store->department($a['dept'])['name'] ?? '') . '</category><description>' . e($a['dek']) . '</description></item>';
    }
    echo '</channel></rss>';
    exit;
}

if ($page === 'google') {
    if (!$auth->googleEnabled()) {
        flash('Google sign-in has not been configured for this site yet.');
        redirect(url(['p' => 'login']));
    }
    $_SESSION['next'] = safe_next((string) ($_GET['next'] ?? ''));
    redirect($auth->googleAuthUrl(base_url($config) . url(['p' => 'google-callback'])));
}

if ($page === 'google-callback') {
    try {
        $user = $auth->googleCallback((string) ($_GET['code'] ?? ''), (string) ($_GET['state'] ?? ''), base_url($config) . url(['p' => 'google-callback']));
        $next = safe_next((string) ($_SESSION['next'] ?? ''));
        unset($_SESSION['next']);
        flash('Welcome, ' . $user['name'] . '.');
        redirect($next);
    } catch (DomainException $ex) {
        flash($ex->getMessage());
        redirect(url(['p' => 'login']));
    }
}

// ---- form actions --------------------------------------------------------

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = (string) ($_POST['action'] ?? '');
    $form = $_POST;
    try {
        if (!$auth->checkCsrf((string) ($_POST['csrf'] ?? ''))) {
            throw new DomainException('Your session expired. Please try again.');
        }
        $next = safe_next((string) ($_POST['next'] ?? ''));
        switch ($action) {
            case 'logout':
                $auth->logout();
                redirect(url());

            case 'login':
                $email = (string) ($_POST['email'] ?? '');
                if (!$store->hit('login:' . $ip, 10, 900) || !$store->hit('login:' . MagazineStore::normalizeEmail($email), 10, 900)) {
                    throw new DomainException('Too many sign-in attempts. Please wait a few minutes.');
                }
                if (($blocked = $shield->check($_POST, $ip)) !== null) {
                    throw new DomainException($blocked);
                }
                if (!$auth->login($email, (string) ($_POST['password'] ?? ''))) {
                    throw new DomainException('That email and password do not match an account.');
                }
                redirect($next);

            case 'register':
                if (!$store->hit('register:' . $ip, 5, 3600)) {
                    throw new DomainException('Too many registrations from this address. Please try again later.');
                }
                if (($blocked = $shield->check($_POST, $ip)) !== null) {
                    throw new DomainException($blocked);
                }
                $user = $auth->register((string) ($_POST['name'] ?? ''), (string) ($_POST['email'] ?? ''), (string) ($_POST['password'] ?? ''));
                flash('Welcome, ' . $user['name'] . '. Your account is ready.');
                redirect($next);

            case 'comment':
                $article = $store->articleById((string) ($_POST['article'] ?? ''));
                if ($me === null || $article === null || !$article['comments'] || !(MagazineStore::isLive($article) || $staff)) {
                    throw new DomainException('Comments are not open here.');
                }
                $back = url(['p' => 'article', 'a' => $article['slug']]);
                $page = 'article';
                $_GET['a'] = $article['slug'];
                if (!$store->hit('comment:' . $me['id'], 5, 600)) {
                    throw new DomainException('You are commenting very quickly. Please wait a few minutes.');
                }
                if (($blocked = $shield->check($_POST, $ip)) !== null) {
                    throw new DomainException($blocked);
                }
                $store->addComment($article['id'], $me, (string) ($_POST['body'] ?? ''));
                redirect($back . '#comments');

            case 'comment_delete':
                $article = $store->articleById((string) ($_POST['article'] ?? ''));
                if ($article !== null && $me !== null) {
                    foreach ($store->comments($article['id']) as $c) {
                        if ($c['id'] === ($_POST['comment'] ?? '') && ($staff || $c['user_id'] === $me['id'])) {
                            $store->deleteComment($article['id'], $c['id']);
                        }
                    }
                    redirect(url(['p' => 'article', 'a' => $article['slug']]) . '#comments');
                }
                redirect(url());

            case 'article_save':
                if (!$staff) {
                    throw new DomainException('Only editors can publish.');
                }
                $page = 'write';
                $video = trim((string) ($_POST['video'] ?? ''));
                $videoId = MagazineMarkup::youtubeId($video);
                if ($video !== '' && $videoId === '') {
                    throw new DomainException('The lead video must be a YouTube link.');
                }
                $at = trim((string) ($_POST['publish_at'] ?? ''));
                $publishAt = $at === '' ? time() : strtotime($at);
                if ($publishAt === false) {
                    throw new DomainException('The publish date could not be read.');
                }
                $saved = $store->saveArticle([
                    'id' => ($_POST['id'] ?? '') !== '' ? (string) $_POST['id'] : null,
                    'title' => $_POST['title'] ?? '',
                    'dek' => $_POST['dek'] ?? '',
                    'dept' => $_POST['dept'] ?? '',
                    'body' => $_POST['body'] ?? '',
                    'status' => $_POST['status'] ?? 'draft',
                    'publish_at' => $publishAt,
                    'comments' => isset($_POST['comments']),
                    'video' => $videoId,
                    'author_id' => $me['id'],
                    'author_name' => $me['name'],
                ]);
                flash(MagazineStore::isLive($saved) ? 'Published.' : ($saved['status'] === 'published' ? 'Scheduled for ' . date('F j, Y H:i', $saved['publish_at']) . '.' : 'Draft saved.'));
                redirect(url(['p' => 'article', 'a' => $saved['slug']]));

            case 'article_delete':
                if ($staff) {
                    $store->deleteArticle((string) ($_POST['id'] ?? ''));
                    flash('Article deleted.');
                }
                redirect(url(['p' => 'admin']));

            case 'user_role':
                $target = (string) ($_POST['user'] ?? '');
                $role = (string) ($_POST['role'] ?? '');
                if ($admin && $target !== $me['id'] && in_array($role, MagazineStore::ROLES, true)) {
                    $store->updateUser($target, ['role' => $role]);
                    flash('Role updated.');
                }
                redirect(url(['p' => 'admin-users']));

            case 'shop_settings':
            case 'product_save':
            case 'product_delete':
                if (!$admin) {
                    throw new DomainException('Only administrators manage the shop.');
                }
                $page = 'admin-shop';
                if ($action === 'shop_settings') {
                    $shop->saveSettings($_POST);
                } elseif ($action === 'product_save') {
                    $shop->saveProduct($_POST);
                } else {
                    $shop->deleteProduct((string) ($_POST['id'] ?? ''));
                }
                flash('Shop updated.');
                redirect(url(['p' => 'admin-shop']));

            default:
                throw new DomainException('Unknown action.');
        }
    } catch (DomainException $ex) {
        $error = $ex->getMessage();
        if (in_array($action, ['login', 'register'], true)) {
            $page = $action;
        }
    }
}

// ---- view helpers --------------------------------------------------------

$csrf = $auth->csrfToken();
$departments = $store->departments();

$shieldFields = static function () use ($shield): string {
    $html = '<div class="hp" aria-hidden="true"><label>Leave this field empty <input type="text" name="' . BotShield::HONEYPOT . '" tabindex="-1" autocomplete="off"></label></div>'
        . '<input type="hidden" name="form_token" value="' . e($shield->formToken()) . '"><input type="hidden" name="shield">';
    if ($shield->turnstileSiteKey() !== '') {
        $html .= '<div class="cf-turnstile" data-sitekey="' . e($shield->turnstileSiteKey()) . '"></div>';
    }
    return $html . '<p class="shield-status" data-shield-status>Checking that you are human…</p>'
        . '<noscript><p class="notice error">JavaScript is needed for the automatic human check.</p></noscript>';
};

$card = static function (array $a, bool $lead = false) use ($store): string {
    $d = $store->department($a['dept']);
    $link = url(['p' => 'article', 'a' => $a['slug']]);
    return '<article class="card' . ($lead ? ' lead' : '') . '"><a class="kicker" href="' . e(url(['p' => 'department', 'd' => $a['dept']])) . '">' . e($d['name'] ?? '') . '</a>'
        . '<h3><a href="' . e($link) . '">' . e($a['title']) . '</a></h3>'
        . ($a['dek'] !== '' ? '<p class="dek">' . e($a['dek']) . '</p>' : '')
        . '<p class="meta">' . e($a['author_name']) . ' · <time datetime="' . date('c', $a['publish_at']) . '">' . when($a['publish_at']) . '</time>'
        . ($a['video'] !== '' ? ' · Video' : '') . '</p></article>';
};

$pager = static function (int $total, array $params): string {
    $pages = (int) ceil($total / PER_PAGE);
    $current = max(1, (int) ($_GET['page'] ?? 1));
    if ($pages < 2) {
        return '';
    }
    $html = '<nav class="pager" aria-label="Pages">';
    if ($current > 1) {
        $html .= '<a href="' . e(url($params + ['page' => $current - 1])) . '">← Newer</a>';
    }
    $html .= '<span>Page ' . $current . ' of ' . $pages . '</span>';
    if ($current < $pages) {
        $html .= '<a href="' . e(url($params + ['page' => $current + 1])) . '">Older →</a>';
    }
    return $html . '</nav>';
};

$shareIcons = [
    'x' => ['X', '<path d="M5 4.5l14 15M19 4.5l-14 15" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/>'],
    'facebook' => ['Facebook', '<path d="M13.6 21v-7.6h2.6l.4-3h-3V8.5c0-.9.3-1.5 1.6-1.5h1.6V4.3c-.3 0-1.3-.1-2.3-.1-2.3 0-3.8 1.4-3.8 3.9v2.3H8.1v3h2.6V21z"/>'],
    'linkedin' => ['LinkedIn', '<path d="M5 9.2h3V19H5zM6.5 4.6a1.75 1.75 0 110 3.5 1.75 1.75 0 010-3.5zM10.4 9.2h2.9v1.4c.5-.9 1.6-1.6 3-1.6 2.6 0 3.7 1.6 3.7 4.3V19h-3v-5.1c0-1.3-.4-2.2-1.6-2.2-1.2 0-2 .9-2 2.2V19h-3z"/>'],
    'reddit' => ['Reddit', '<ellipse cx="12" cy="14" rx="8" ry="5.6"/><circle cx="4.6" cy="11.4" r="1.9"/><circle cx="19.4" cy="11.4" r="1.9"/><circle cx="17.6" cy="4.8" r="1.5"/><path d="M12 8.6l1.2-4.4 4.2.8" fill="none" stroke="#fff" stroke-width="1.2"/><circle class="cut" cx="9" cy="13.2" r="1.4"/><circle class="cut" cx="15" cy="13.2" r="1.4"/><path class="cutline" d="M9 16.3c1.8 1.2 4.2 1.2 6 0"/>'],
    'whatsapp' => ['WhatsApp', '<path d="M12 3.4a8.6 8.6 0 00-7.4 13l-1.2 4.2 4.4-1.1A8.6 8.6 0 1012 3.4z"/><path class="cut" d="M9.2 7.7c-.4 0-.7.2-.9.6-.5.9-.4 1.9.3 3.1 1 1.800 2.400 3.100 4.200 3.900 1.100.4 2 .3 2.600-.3.400-.4.400-.9.100-1.100l-1.600-1c-.3-.2-.6-.1-.8.2l-.5.6c-.9-.4-1.800-1.300-2.300-2.300l.5-.5c.2-.2.3-.5.1-.8l-.9-1.900c-.1-.3-.4-.5-.8-.5z"/>'],
    'bluesky' => ['Bluesky', '<path d="M12 11.300C11 9.200 8.300 5.700 5.800 4.700 4 4 3 4.700 3 6.300c0 1 .5 5 .9 5.800.9 2 3.200 2.400 5.200 2-3 .6-4.300 2.200-2.400 4.200 3.300 3.200 4.800-1 5.300-2.300.5 1.300 2 5.500 5.300 2.300 1.900-2 .6-3.600-2.400-4.200 2 .4 4.300 0 5.200-2 .4-.8.9-4.800.9-5.800 0-1.600-1-2.300-2.800-1.600-2.500 1-5.200 4.500-6.200 6.600z"/>'],
    'telegram' => ['Telegram', '<path d="M20.300 4.300L3.500 10.800c-.8.3-.8 1.200.1 1.400l4.200 1.300 1.600 5c.2.600.9.700 1.300.300l2.400-2.300 4.300 3.200c.5.400 1.200.1 1.400-.5l3-13.700c.2-.9-.6-1.500-1.500-1.200z"/><path class="cutline" d="M8.200 13.300l8.300-5.300-6 6.300"/>'],
    'email' => ['Email', '<rect x="3.500" y="6" width="17" height="12" rx="1.800" fill="none" stroke="#fff" stroke-width="1.800"/><path d="M4 7l8 6.200L20 7" fill="none" stroke="#fff" stroke-width="1.800"/>'],
];

$shareBar = static function (string $link, string $title) use ($shareIcons): string {
    $u = rawurlencode($link);
    $t = rawurlencode($title);
    $targets = [
        'x' => "https://twitter.com/intent/tweet?url={$u}&text={$t}",
        'facebook' => "https://www.facebook.com/sharer/sharer.php?u={$u}",
        'linkedin' => "https://www.linkedin.com/sharing/share-offsite/?url={$u}",
        'reddit' => "https://www.reddit.com/submit?url={$u}&title={$t}",
        'whatsapp' => 'https://wa.me/?text=' . rawurlencode($title . ' ' . $link),
        'bluesky' => 'https://bsky.app/intent/compose?text=' . rawurlencode($title . ' ' . $link),
        'telegram' => "https://t.me/share/url?url={$u}&text={$t}",
        'email' => "mailto:?subject={$t}&body={$u}",
    ];
    $html = '<section class="share" aria-label="Share this article"><h2>Share this article</h2><ul>';
    foreach ($targets as $key => $href) {
        [$label, $svg] = $shareIcons[$key];
        $html .= '<li><a class="share-btn s-' . $key . '" href="' . e($href) . '"' . ($key === 'email' ? '' : ' target="_blank" rel="noopener noreferrer"')
            . ' aria-label="Share on ' . $label . '" title="' . $label . '"><svg viewBox="0 0 24 24" aria-hidden="true">' . $svg . '</svg></a></li>';
    }
    return $html . '<li><button type="button" class="share-btn s-copy" data-copy="' . e($link) . '" aria-label="Copy link" title="Copy link">'
        . '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 005.700 0l3-3a4 4 0 00-5.700-5.700l-1 1M14 10a4 4 0 00-5.700 0l-3 3a4 4 0 005.700 5.700l1-1" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>'
        . '</button></li></ul><p class="share-note" data-copy-note role="status"></p></section>';
};

// ---- pages ---------------------------------------------------------------

$title = $config['site_name'];
$description = $config['tagline'];
$canonical = base_url($config);
$ogType = 'website';
$status = 200;
ob_start();

if ($page === 'article') {
    $article = $store->article((string) ($_GET['a'] ?? ''));
    if ($article === null || !(MagazineStore::isLive($article) || $staff)) {
        $page = '404';
    } else {
        $d = $store->department($article['dept']);
        $title = $article['title'] . ' · ' . $config['site_name'];
        $description = $article['dek'] !== '' ? $article['dek'] : MagazineMarkup::excerpt($article['body']);
        $canonical = base_url($config) . url(['p' => 'article', 'a' => $article['slug']]);
        $ogType = 'article';
        $self = url(['p' => 'article', 'a' => $article['slug']]);
        ?>
        <article class="story">
            <?php if (!MagazineStore::isLive($article)): ?>
                <p class="notice"><?= $article['status'] === 'draft' ? 'Draft: only editors can see this.' : 'Scheduled for ' . e(date('F j, Y H:i', $article['publish_at'])) . ' (' . e($config['timezone']) . '). Only editors can see it until then.' ?></p>
            <?php endif; ?>
            <header>
                <a class="kicker" href="<?= e(url(['p' => 'department', 'd' => $article['dept']])) ?>"><?= e($d['name']) ?></a>
                <h1><?= e($article['title']) ?></h1>
                <?php if ($article['dek'] !== ''): ?><p class="dek"><?= e($article['dek']) ?></p><?php endif; ?>
                <p class="meta">By <?= e($article['author_name']) ?> · <time datetime="<?= date('c', $article['publish_at']) ?>"><?= when($article['publish_at']) ?></time>
                    <?php if ($staff): ?> · <a href="<?= e(url(['p' => 'write', 'id' => $article['id']])) ?>">Edit</a><?php endif; ?></p>
            </header>
            <?= $article['video'] !== '' ? MagazineMarkup::youtubeEmbed($article['video']) : '' ?>
            <div class="prose"><?= MagazineMarkup::render($article['body']) ?></div>
            <?= $shareBar($canonical, $article['title']) ?>
        </article>

        <section class="comments" id="comments">
            <?php if (!$article['comments']): ?>
                <p class="muted">Comments are closed for this article.</p>
            <?php else: $comments = $store->comments($article['id']); ?>
                <h2>Comments <span class="count"><?= count($comments) ?></span></h2>
                <?php foreach ($comments as $c): ?>
                    <div class="comment">
                        <p class="meta"><strong><?= e($c['name']) ?></strong> · <?= when($c['created']) ?></p>
                        <p><?= nl2br(e($c['body'])) ?></p>
                        <?php if ($me !== null && ($staff || $c['user_id'] === $me['id'])): ?>
                            <form method="post" class="inline"><input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="comment_delete">
                                <input type="hidden" name="article" value="<?= e($article['id']) ?>"><input type="hidden" name="comment" value="<?= e($c['id']) ?>">
                                <button class="link" type="submit">Delete</button></form>
                        <?php endif; ?>
                    </div>
                <?php endforeach; ?>
                <?php if ($comments === []): ?><p class="muted">No comments yet.</p><?php endif; ?>
                <?php if ($me !== null): ?>
                    <?php if ($error !== null): ?><p class="notice error"><?= e($error) ?></p><?php endif; ?>
                    <form method="post" action="<?= e($self) ?>#comments" class="stack" data-shield>
                        <input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="comment"><input type="hidden" name="article" value="<?= e($article['id']) ?>">
                        <label>Add a comment as <?= e($me['name']) ?>
                            <textarea name="body" rows="4" maxlength="2000" required><?= e($error !== null ? ($form['body'] ?? '') : '') ?></textarea></label>
                        <?= $shieldFields() ?>
                        <button type="submit">Post comment</button>
                    </form>
                <?php else: ?>
                    <p><a class="button" href="<?= e(url(['p' => 'login', 'next' => $self])) ?>">Sign in to comment</a></p>
                <?php endif; ?>
            <?php endif; ?>
        </section>
        <?php
    }
}

if ($page === 'department') {
    $d = $store->department((string) ($_GET['d'] ?? ''));
    if ($d === null) {
        $page = '404';
    } else {
        $title = $d['name'] . ' · ' . $config['site_name'];
        $description = $d['tagline'];
        $canonical = base_url($config) . url(['p' => 'department', 'd' => $d['slug']]);
        $all = $store->liveArticles($d['slug']);
        $current = max(1, (int) ($_GET['page'] ?? 1));
        ?>
        <header class="dept-head">
            <p class="dept-number">Department <?= sprintf('%02d', $d['number']) ?> of 20</p>
            <h1><?= e($d['name']) ?></h1>
            <p class="dek"><?= e($d['tagline']) ?></p>
            <div class="mission"><h2>Mission</h2><p><?= e($d['mission']) ?></p></div>
        </header>
        <h2 class="rule">The stream</h2>
        <div class="stream">
            <?php foreach (array_slice($all, ($current - 1) * PER_PAGE, PER_PAGE) as $a) { echo $card($a); } ?>
            <?php if ($all === []): ?><p class="muted">The first article in this department is on its way.</p><?php endif; ?>
        </div>
        <?= $pager(count($all), ['p' => 'department', 'd' => $d['slug']]) ?>
        <?php
    }
}

if ($page === 'home') {
    $all = $store->liveArticles();
    $current = max(1, (int) ($_GET['page'] ?? 1));
    $slice = array_slice($all, ($current - 1) * PER_PAGE, PER_PAGE);
    ?>
    <?php if ($current === 1 && $slice !== []): ?>
        <section class="front"><?= $card(array_shift($slice), true) ?></section>
    <?php endif; ?>
    <h2 class="rule">Latest</h2>
    <div class="stream grid"><?php foreach ($slice as $a) { echo $card($a); } ?></div>
    <?= $pager(count($all), []) ?>
    <h2 class="rule" id="departments">The 20 departments</h2>
    <ol class="dept-grid">
        <?php foreach ($departments as $d): ?>
            <li><a href="<?= e(url(['p' => 'department', 'd' => $d['slug']])) ?>"><span class="n"><?= sprintf('%02d', $d['number']) ?></span>
                <strong><?= e($d['name']) ?></strong><span><?= e($d['tagline']) ?></span></a></li>
        <?php endforeach; ?>
    </ol>
    <?php
}

if ($page === 'shop') {
    $title = 'Shop · ' . $config['site_name'];
    $products = $shop->products();
    $settings = $shop->settings();
    $hasAmazon = $settings['amazon_store_url'] !== '' || in_array('amazon', array_column($products, 'kind'), true);
    ?>
    <header class="dept-head"><h1>Shop</h1><p class="dek">Merchandise and recommended reading. Checkout happens securely on PayPal or Amazon.</p></header>
    <?php if ($settings['paypal_store_url'] !== '' || $settings['amazon_store_url'] !== ''): ?>
        <p class="store-links">
            <?php if ($settings['paypal_store_url'] !== ''): ?><a class="button" href="<?= e($settings['paypal_store_url']) ?>" target="_blank" rel="noopener">Visit our PayPal store</a><?php endif; ?>
            <?php if ($settings['amazon_store_url'] !== ''): ?><a class="button" href="<?= e($settings['amazon_store_url']) ?>" target="_blank" rel="sponsored noopener">Visit our Amazon store</a><?php endif; ?>
        </p>
    <?php endif; ?>
    <div class="products">
        <?php foreach ($products as $p): ?>
            <div class="product">
                <?php if ($p['image'] !== ''): ?><img src="<?= e($p['image']) ?>" alt="" loading="lazy" referrerpolicy="no-referrer"><?php else: ?><div class="ph" aria-hidden="true"></div><?php endif; ?>
                <h3><?= e($p['name']) ?></h3>
                <?php if ($p['blurb'] !== ''): ?><p><?= e($p['blurb']) ?></p><?php endif; ?>
                <?php if ($p['price'] !== ''): ?><p class="price"><?= e($p['price']) ?></p><?php endif; ?>
                <a class="button" href="<?= e($p['url']) ?>" target="_blank" rel="<?= $p['kind'] === 'amazon' ? 'sponsored ' : '' ?>noopener"><?= $p['kind'] === 'amazon' ? 'View on Amazon' : 'Buy with PayPal' ?></a>
            </div>
        <?php endforeach; ?>
    </div>
    <?php if ($products === []): ?><p class="muted">The shop is being stocked. Please check back soon.</p><?php endif; ?>
    <?php if ($hasAmazon): ?><p class="muted disclosure"><?= e(MagazineShop::AMAZON_DISCLOSURE) ?></p><?php endif; ?>
    <?php
}

if ($page === 'login' || $page === 'register') {
    if ($me !== null) {
        redirect(url());
    }
    $isLogin = $page === 'login';
    $title = ($isLogin ? 'Sign in' : 'Create an account') . ' · ' . $config['site_name'];
    $next = safe_next((string) ($_REQUEST['next'] ?? ''));
    ?>
    <section class="auth">
        <h1><?= $isLogin ? 'Sign in' : 'Create an account' ?></h1>
        <?php if ($error !== null): ?><p class="notice error"><?= e($error) ?></p><?php endif; ?>
        <?php if ($auth->googleEnabled()): ?>
            <a class="button google" href="<?= e(url(['p' => 'google', 'next' => $next])) ?>"><span class="g" aria-hidden="true">G</span> Continue with Google</a>
            <p class="or"><span>or use your email</span></p>
        <?php endif; ?>
        <form method="post" action="<?= e(url(['p' => $page])) ?>" class="stack" data-shield>
            <input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="<?= $page ?>"><input type="hidden" name="next" value="<?= e($next) ?>">
            <?php if (!$isLogin): ?>
                <label>Display name <input type="text" name="name" value="<?= e($form['name'] ?? '') ?>" minlength="2" maxlength="60" autocomplete="name" required></label>
            <?php endif; ?>
            <label>Email <input type="email" name="email" value="<?= e($form['email'] ?? '') ?>" autocomplete="email" required></label>
            <label>Password <input type="password" name="password" autocomplete="<?= $isLogin ? 'current-password' : 'new-password' ?>" <?= $isLogin ? '' : 'minlength="' . MagazineAuth::MIN_PASSWORD . '"' ?> required>
                <?php if (!$isLogin): ?><small>At least <?= MagazineAuth::MIN_PASSWORD ?> characters.</small><?php endif; ?></label>
            <?= $shieldFields() ?>
            <button type="submit"><?= $isLogin ? 'Sign in' : 'Create account' ?></button>
        </form>
        <p class="muted"><?= $isLogin
            ? 'New here? <a href="' . e(url(['p' => 'register', 'next' => $next])) . '">Create an account</a>.'
            : 'Already registered? <a href="' . e(url(['p' => 'login', 'next' => $next])) . '">Sign in</a>.' ?></p>
        <?php if (!$auth->googleEnabled() && $admin): ?><p class="muted">Google sign-in appears here once its keys are configured.</p><?php endif; ?>
    </section>
    <?php
}

if ($page === 'write') {
    if (!$staff) {
        $page = '403';
    } else {
        $title = 'Write · ' . $config['site_name'];
        $editing = isset($_GET['id']) ? $store->articleById((string) $_GET['id']) : null;
        $f = $error !== null ? $form : ($editing ?? ['comments' => true, 'status' => 'published', 'dept' => (string) ($_GET['d'] ?? '')]);
        $at = $error !== null ? (string) ($form['publish_at'] ?? '') : date('Y-m-d\TH:i', (int) ($editing['publish_at'] ?? time()));
        $videoValue = $error !== null ? (string) ($form['video'] ?? '') : (($editing['video'] ?? '') !== '' ? 'https://youtu.be/' . $editing['video'] : '');
        ?>
        <section class="editor">
            <h1><?= $editing ? 'Edit article' : 'New article' ?></h1>
            <?php if ($error !== null): ?><p class="notice error"><?= e($error) ?></p><?php endif; ?>
            <form method="post" action="<?= e(url(['p' => 'write'] + ($editing ? ['id' => $editing['id']] : []))) ?>" class="stack">
                <input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="article_save">
                <input type="hidden" name="id" value="<?= e($editing['id'] ?? ($form['id'] ?? '')) ?>">
                <label>Department
                    <select name="dept" required>
                        <option value="">Choose a department</option>
                        <?php foreach ($departments as $d): ?>
                            <option value="<?= e($d['slug']) ?>" <?= ($f['dept'] ?? '') === $d['slug'] ? 'selected' : '' ?>><?= sprintf('%02d', $d['number']) ?> · <?= e($d['name']) ?></option>
                        <?php endforeach; ?>
                    </select></label>
                <label>Headline <input type="text" name="title" value="<?= e($f['title'] ?? '') ?>" maxlength="160" required></label>
                <label>Standfirst <input type="text" name="dek" value="<?= e($f['dek'] ?? '') ?>" maxlength="240"><small>One sentence under the headline.</small></label>
                <label>Lead YouTube video <input type="url" name="video" value="<?= e($videoValue) ?>" placeholder="https://www.youtube.com/watch?v=…"><small>Optional. Plays at the top of the article.</small></label>
                <label>Article
                    <textarea name="body" rows="20" required><?= e($f['body'] ?? '') ?></textarea>
                    <small>Blank line between paragraphs. <code>## Heading</code>, <code>&gt; quote</code>, <code>- list</code>, <code>**bold**</code>, <code>*italic*</code>, <code>[text](https://link)</code>.
                        Paste a YouTube link alone on a line to embed the video there. Scorecard: <code>[scorecard: Product]</code>, then lines like <code>Lean Compute: 4 | reasoning</code>, then <code>[/scorecard]</code>.</small></label>
                <div class="row">
                    <label>Status
                        <select name="status">
                            <option value="published" <?= ($f['status'] ?? '') === 'published' ? 'selected' : '' ?>>Publish</option>
                            <option value="draft" <?= ($f['status'] ?? '') === 'draft' ? 'selected' : '' ?>>Draft</option>
                        </select></label>
                    <label>Publish date (<?= e($config['timezone']) ?>) <input type="datetime-local" name="publish_at" value="<?= e($at) ?>"><small>A future date schedules the article.</small></label>
                </div>
                <label class="check"><input type="checkbox" name="comments" <?= !empty($f['comments']) ? 'checked' : '' ?>> Enable comments at the end of this article</label>
                <button type="submit">Save</button>
            </form>
        </section>
        <?php
    }
}

if (in_array($page, ['admin', 'admin-users', 'admin-shop'], true)) {
    if (!$staff || ($page !== 'admin' && !$admin)) {
        $page = '403';
    } else {
        $title = 'Newsroom · ' . $config['site_name'];
        ?>
        <nav class="tabs"><a href="<?= e(url(['p' => 'admin'])) ?>">Articles</a>
            <?php if ($admin): ?><a href="<?= e(url(['p' => 'admin-users'])) ?>">Members</a><a href="<?= e(url(['p' => 'admin-shop'])) ?>">Shop</a><?php endif; ?>
            <a class="button" href="<?= e(url(['p' => 'write'])) ?>">New article</a></nav>
        <?php if ($error !== null): ?><p class="notice error"><?= e($error) ?></p><?php endif; ?>
        <?php if ($page === 'admin'): ?>
            <h1>Articles</h1>
            <div class="table-wrap"><table class="admin">
                <tr><th>Headline</th><th>Department</th><th>Status</th><th>Date</th><th></th></tr>
                <?php foreach ($store->articles() as $a): ?>
                    <tr><td><a href="<?= e(url(['p' => 'article', 'a' => $a['slug']])) ?>"><?= e($a['title']) ?></a></td>
                        <td><?= e($store->department($a['dept'])['name'] ?? '') ?></td>
                        <td><?= MagazineStore::isLive($a) ? 'Live' : ($a['status'] === 'draft' ? 'Draft' : 'Scheduled') ?></td>
                        <td><?= e(date('Y-m-d H:i', $a['publish_at'])) ?></td>
                        <td class="actions"><a href="<?= e(url(['p' => 'write', 'id' => $a['id']])) ?>">Edit</a>
                            <form method="post" class="inline" data-confirm="Delete this article and its comments?"><input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="article_delete">
                                <input type="hidden" name="id" value="<?= e($a['id']) ?>"><button class="link" type="submit">Delete</button></form></td></tr>
                <?php endforeach; ?>
            </table></div>
        <?php elseif ($page === 'admin-users'): ?>
            <h1>Members</h1>
            <div class="table-wrap"><table class="admin">
                <tr><th>Name</th><th>Email</th><th>Sign-in</th><th>Role</th></tr>
                <?php foreach ($store->users() as $u): ?>
                    <tr><td><?= e($u['name']) ?></td><td><?= e($u['email']) ?></td><td><?= $u['google_sub'] !== '' ? 'Google' : 'Password' ?></td>
                        <td><?php if ($u['id'] === $me['id']): ?><?= e($u['role']) ?> (you)<?php else: ?>
                            <form method="post" class="inline"><input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="user_role"><input type="hidden" name="user" value="<?= e($u['id']) ?>">
                                <select name="role"><?php foreach (MagazineStore::ROLES as $r): ?><option <?= $u['role'] === $r ? 'selected' : '' ?>><?= $r ?></option><?php endforeach; ?></select>
                                <button class="link" type="submit">Save</button></form><?php endif; ?></td></tr>
                <?php endforeach; ?>
            </table></div>
        <?php else: $settings = $error !== null && ($form['action'] ?? '') === 'shop_settings' ? $form : $shop->settings(); $pf = $error !== null && ($form['action'] ?? '') === 'product_save' ? $form : []; ?>
            <h1>Shop</h1>
            <form method="post" action="<?= e(url(['p' => 'admin-shop'])) ?>" class="stack panel">
                <h2>Store settings</h2>
                <input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="shop_settings">
                <div class="row">
                    <label>Amazon Associates tag <input type="text" name="amazon_tag" value="<?= e($settings['amazon_tag'] ?? '') ?>" placeholder="yourname-20"><small>Added to every Amazon product link.</small></label>
                    <label>Amazon site <input type="text" name="amazon_domain" value="<?= e($settings['amazon_domain'] ?? '') ?>" placeholder="www.amazon.com"></label>
                </div>
                <label>Amazon storefront link <input type="url" name="amazon_store_url" value="<?= e($settings['amazon_store_url'] ?? '') ?>" placeholder="https://www.amazon.com/shop/yourname"></label>
                <label>PayPal store link <input type="url" name="paypal_store_url" value="<?= e($settings['paypal_store_url'] ?? '') ?>" placeholder="https://www.paypal.com/…"></label>
                <button type="submit">Save settings</button>
            </form>
            <form method="post" action="<?= e(url(['p' => 'admin-shop'])) ?>" class="stack panel">
                <h2>Add a product</h2>
                <input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="product_save">
                <label>Name <input type="text" name="name" value="<?= e($pf['name'] ?? '') ?>" maxlength="120" required></label>
                <label>Description <input type="text" name="blurb" value="<?= e($pf['blurb'] ?? '') ?>" maxlength="300"></label>
                <div class="row">
                    <label>Price label <input type="text" name="price" value="<?= e($pf['price'] ?? '') ?>" placeholder="$24.00"></label>
                    <label>Sold through
                        <select name="kind"><option value="paypal" <?= ($pf['kind'] ?? '') === 'paypal' ? 'selected' : '' ?>>PayPal</option><option value="amazon" <?= ($pf['kind'] ?? '') === 'amazon' ? 'selected' : '' ?>>Amazon (Associates)</option></select></label>
                </div>
                <label>Checkout link or ID <input type="text" name="target" value="<?= e($pf['target'] ?? '') ?>" required>
                    <small>PayPal: a hosted button ID, a PayPal payment link, or a paypal.me link. Amazon: a 10-character ASIN or a product link.</small></label>
                <label>Image link <input type="url" name="image" value="<?= e($pf['image'] ?? '') ?>" placeholder="https://…"></label>
                <button type="submit">Add product</button>
            </form>
            <div class="table-wrap"><table class="admin">
                <tr><th>Product</th><th>Sold through</th><th>Link</th><th></th></tr>
                <?php foreach ($shop->products() as $p): ?>
                    <tr><td><?= e($p['name']) ?></td><td><?= $p['kind'] === 'amazon' ? 'Amazon' : 'PayPal' ?></td><td class="url"><?= e($p['url']) ?></td>
                        <td><form method="post" class="inline"><input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="product_delete">
                            <input type="hidden" name="id" value="<?= e($p['id']) ?>"><button class="link" type="submit">Remove</button></form></td></tr>
                <?php endforeach; ?>
            </table></div>
        <?php endif;
    }
}

if ($page === '403') {
    $status = 403;
    echo '<section class="auth"><h1>Editors only</h1><p>This page is for the magazine\'s staff. <a href="' . e(url(['p' => 'login'])) . '">Sign in</a> with a staff account.</p></section>';
} elseif (!in_array($page, ['home', 'article', 'department', 'shop', 'login', 'register', 'write', 'admin', 'admin-users', 'admin-shop'], true)) {
    $status = 404;
    echo '<section class="auth"><h1>Page not found</h1><p><a href="' . e(url()) . '">Return to the front page</a>.</p></section>';
}

$content = ob_get_clean();
$notice = flash();
http_response_code($status);
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?= e($title) ?></title>
    <meta name="description" content="<?= e($description) ?>">
    <link rel="canonical" href="<?= e($canonical) ?>">
    <meta property="og:site_name" content="<?= e($config['site_name']) ?>">
    <meta property="og:type" content="<?= $ogType ?>">
    <meta property="og:title" content="<?= e($title) ?>">
    <meta property="og:description" content="<?= e($description) ?>">
    <meta property="og:url" content="<?= e($canonical) ?>">
    <meta name="twitter:card" content="summary">
    <link rel="alternate" type="application/rss+xml" title="<?= e($config['site_name']) ?>" href="<?= e(url(['p' => 'feed'])) ?>">
    <link rel="stylesheet" href="assets/magazine.css">
    <script src="assets/magazine.js" defer></script>
    <?php if ($shield->turnstileSiteKey() !== ''): ?><script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script><?php endif; ?>
</head>
<body>
<header class="masthead">
    <div class="top">
        <span class="date"><?= date('l, F j, Y') ?></span>
        <nav class="account">
            <a href="<?= e(url(['p' => 'shop'])) ?>">Shop</a>
            <?php if ($staff): ?><a href="<?= e(url(['p' => 'admin'])) ?>">Newsroom</a><?php endif; ?>
            <?php if ($me !== null): ?>
                <span class="who"><?= e($me['name']) ?></span>
                <form method="post" class="inline"><input type="hidden" name="csrf" value="<?= e($csrf) ?>"><input type="hidden" name="action" value="logout"><button class="link" type="submit">Sign out</button></form>
            <?php else: ?>
                <a href="<?= e(url(['p' => 'login'])) ?>">Sign in</a><a href="<?= e(url(['p' => 'register'])) ?>">Register</a>
            <?php endif; ?>
        </nav>
    </div>
    <a class="nameplate" href="<?= e(url()) ?>"><?= e($config['site_name']) ?></a>
    <p class="tagline"><?= e($config['tagline']) ?></p>
    <nav class="sections" aria-label="Departments">
        <?php foreach ($departments as $d): ?>
            <a href="<?= e(url(['p' => 'department', 'd' => $d['slug']])) ?>" <?= ($page === 'department' && ($_GET['d'] ?? '') === $d['slug']) ? 'aria-current="page"' : '' ?>><?= e($d['name']) ?></a>
        <?php endforeach; ?>
    </nav>
</header>
<main>
    <?php if ($notice !== null): ?><p class="notice"><?= e($notice) ?></p><?php endif; ?>
    <?= $content ?>
</main>
<footer class="foot">
    <p><?= e($config['site_name']) ?> · <a href="<?= e(url()) ?>#departments">Departments</a> · <a href="<?= e(url(['p' => 'shop'])) ?>">Shop</a> · <a href="<?= e(url(['p' => 'feed'])) ?>">RSS</a></p>
</footer>
</body>
</html>
