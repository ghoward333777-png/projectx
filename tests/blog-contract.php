<?php

declare(strict_types=1);

require_once __DIR__ . '/../BlogStore.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$dir = sys_get_temp_dir() . '/blog-contract-' . bin2hex(random_bytes(4));
$store = new BlogStore($dir);

// --- Articles ----------------------------------------------------------------
$articles = $store->articles();
contract_check(count($articles) >= 5, 'the blog must ship with at least five articles');
$slugs = array_column($articles, 'slug');
contract_check(count($slugs) === count(array_unique($slugs)), 'article slugs must be unique');
$atomgraph = 0;
foreach ($articles as $article) {
    $label = (string) $article['slug'];
    contract_check(trim((string) ($article['title'] ?? '')) !== '', "{$label}: title required");
    contract_check(trim((string) ($article['dek'] ?? '')) !== '', "{$label}: dek required");
    contract_check(strtotime((string) ($article['date'] ?? '')) !== false, "{$label}: valid date required");
    contract_check($article['tags'] !== [], "{$label}: at least one tag required");
    $videos = 0;
    foreach ($article['blocks'] as $block) {
        contract_check(in_array($block['type'] ?? '', ['p', 'h', 'quote', 'callout', 'list', 'chips', 'video'], true), "{$label}: unknown block type");
        if ($block['type'] === 'video') {
            $videos++;
            contract_check(BlogStore::validVideoId((string) ($block['id'] ?? '')), "{$label}: video id must be an 11-character YouTube id");
            contract_check(trim((string) ($block['title'] ?? '')) !== '', "{$label}: video title required");
        }
    }
    contract_check($videos >= 1, "{$label}: every article must include a YouTube video");
    if (in_array('AtomGraph', $article['tags'], true)) {
        $atomgraph++;
        $text = json_encode($article['blocks']);
        contract_check(str_contains((string) $text, 'in development'), "{$label}: AtomGraph articles must state that VeriWave is in development");
    }
}
contract_check($atomgraph >= 3, 'the blog must feature the AtomGraph technology in several articles');
contract_check(count($store->videos()) >= count($articles), 'the video library must list the featured videos');
contract_check($store->article('no-such-post') === null, 'unknown slugs must not resolve');

// --- Comments ----------------------------------------------------------------
$slug = (string) $slugs[0];
contract_check($store->comments($slug) === [], 'a new article starts with no comments');
contract_check(!$store->addComment('../etc/passwd', 'Mallory', 'hello there')['ok'], 'comments on unknown or unsafe slugs must be refused');
contract_check(!is_dir($dir), 'a refused comment must not create storage');
contract_check(!$store->addComment($slug, '   ', 'hello there')['ok'], 'a name is required');
contract_check(!$store->addComment($slug, 'Ada', ' ')['ok'], 'a comment body is required');
contract_check(!$store->addComment($slug, str_repeat('n', BlogStore::MAX_NAME + 1), 'hello there')['ok'], 'over-long names must be refused');
contract_check(!$store->addComment($slug, 'Ada', str_repeat('x', BlogStore::MAX_BODY + 1))['ok'], 'over-long comments must be refused');

$first = $store->addComment($slug, "  Ada\u{200B} Lovelace ", "First  line\r\n\r\n\r\n<script>alert(1)</script>");
contract_check($first['ok'] && $first['id'] !== '', 'a valid comment must be stored');
$saved = $store->comments($slug);
contract_check(count($saved) === 1, 'the stored comment must be readable');
contract_check($saved[0]['name'] === 'Ada Lovelace', 'names must pass through manuscript hygiene: ' . $saved[0]['name']);
contract_check($saved[0]['body'] === "First line\n\n<script>alert(1)</script>", 'comment text is stored verbatim after hygiene (escaped at render time)');
contract_check(strtotime($saved[0]['at']) !== false, 'comments must be timestamped');
contract_check(!$store->addComment($slug, 'Ada Lovelace', "First line\n\n<script>alert(1)</script>")['ok'], 'an immediate duplicate must be refused');
contract_check($store->addComment($slug, 'Grace', 'A second view.')['ok'], 'a second comment must be stored');
contract_check($store->commentCount($slug) === 2, 'comment counts must be accurate');
contract_check($store->commentCount((string) $slugs[1]) === 0, 'comments must stay with their own article');

// --- Rendering escapes reader input ---------------------------------------------
$render = static function (array $get) use ($dir): string {
    $code = '$_GET = ' . var_export($get, true) . '; $_SERVER["REQUEST_METHOD"] = "GET";'
        . ' require ' . var_export(__DIR__ . '/../blog.php', true) . ';';
    return (string) shell_exec('BLOG_COMMENTS_DIR=' . escapeshellarg($dir) . ' ' . escapeshellarg(PHP_BINARY) . ' -r ' . escapeshellarg($code) . ' 2>/dev/null');
};
$home = $render([]);
contract_check(str_contains($home, 'id="articles"') && str_contains($home, 'id="videos"'), 'the home page must render the article grid and the video library');
foreach ($articles as $article) {
    contract_check(str_contains($home, 'blog.php?post=' . $article['slug']), 'the home page must link to ' . $article['slug']);
}
$page = $render(['post' => $slug]);
contract_check(str_contains($page, 'id="comment-form"') && str_contains($page, 'name="token"'), 'article pages must carry the comment form with a CSRF token');
contract_check(str_contains($page, 'data-yt="'), 'article pages must render the YouTube player');
contract_check(str_contains($page, '&lt;script&gt;alert(1)&lt;/script&gt;') && !str_contains($page, '<script>alert(1)</script>'), 'comment text must be HTML-escaped when rendered');
contract_check(str_contains($page, 'not affiliated'), 'pages must carry the independence notice');
contract_check(str_contains($render(['post' => 'no-such-post']), "isn't in the record"), 'unknown articles must render the not-found page');

array_map('unlink', glob($dir . '/*.json') ?: []);
@rmdir($dir);

echo "Blog contract passed.\n";
