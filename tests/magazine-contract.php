<?php

declare(strict_types=1);

require_once __DIR__ . '/../magazine/MagazineStore.php';
require_once __DIR__ . '/../magazine/MagazineAuth.php';
require_once __DIR__ . '/../magazine/BotShield.php';
require_once __DIR__ . '/../magazine/MagazineMarkup.php';
require_once __DIR__ . '/../magazine/MagazineShop.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

function throws(callable $fn): bool
{
    try {
        $fn();
        return false;
    } catch (DomainException) {
        return true;
    }
}

$dir = sys_get_temp_dir() . '/magazine-test-' . bin2hex(random_bytes(4));
$store = new MagazineStore($dir);

// ---- departments and seeded stream ----
$departments = $store->departments();
contract_check(count($departments) === 20, 'the magazine must have exactly 20 permanent departments');
contract_check(count(array_unique(array_column($departments, 'slug'))) === 20, 'department slugs must be unique');
foreach ($departments as $d) {
    contract_check(mb_strlen($d['mission']) > 200, "{$d['name']} must carry a mission paragraph");
    contract_check($d['tagline'] !== '' && $d['opener']['title'] !== '', "{$d['name']} must carry a tagline and an opening brief");
}
contract_check($departments[0]['name'] === 'The Human Multiplier' && $departments[19]['name'] === 'Buyer\'s Brief', 'departments must keep masthead order');

$store->seedIfEmpty();
$store->seedIfEmpty();
contract_check(count($store->liveArticles()) === 20, 'seeding must publish one opening brief per department, once');
foreach ($departments as $d) {
    contract_check(count($store->liveArticles($d['slug'])) === 1, "{$d['name']} must start with an article in its stream");
}
contract_check($store->liveArticles()[0]['dept'] === 'the-human-multiplier', 'the stream must be newest first');
contract_check(str_starts_with((string) file_get_contents($dir . '/articles.json.php'), '<?php http_response_code(404); exit; ?>'), 'data files must carry the exit guard');

// ---- markup, YouTube, scorecard ----
$id = 'dQw4w9WgXcQ';
foreach (["https://www.youtube.com/watch?v={$id}", "https://youtu.be/{$id}?t=4", "https://www.youtube.com/shorts/{$id}", "https://m.youtube.com/watch?feature=x&v={$id}", "https://www.youtube.com/embed/{$id}"] as $link) {
    contract_check(MagazineMarkup::youtubeId($link) === $id, "must read the video id from {$link}");
}
contract_check(MagazineMarkup::youtubeId('https://evil.example/watch?v=' . $id) === '', 'only YouTube hosts may be embedded');
$html = MagazineMarkup::render("## Title\n\nHello **bold** <script>alert(1)</script> [link](https://example.com) [bad](javascript:alert(1))\n\nhttps://youtu.be/{$id}\n\n- one\n- two");
contract_check(str_contains($html, '<h2>Title</h2>') && str_contains($html, '<strong>bold</strong>'), 'markup must render headings and bold');
contract_check(!str_contains($html, '<script>') && str_contains($html, '&lt;script&gt;'), 'markup must escape raw HTML');
contract_check(str_contains($html, '<a href="https://example.com"') && !str_contains($html, 'href="javascript'), 'only http(s) links may render');
contract_check(str_contains($html, 'https://www.youtube-nocookie.com/embed/' . $id), 'a YouTube link on its own line must embed the player');
contract_check(str_contains($html, '<ul><li>one</li><li>two</li></ul>'), 'markup must render lists');
$card = MagazineMarkup::render("[scorecard: Widget <b>]\nLean Compute: 4 | fast\nGlass Box: 2\n[/scorecard]");
contract_check(str_contains($card, 'Widget &lt;b&gt;') && str_contains($card, '6/10') && substr_count($card, 'class="on"') === 6, 'scorecards must total and escape');
$brief = $store->article($store->liveArticles('buyers-brief')[0]['slug']);
contract_check(substr_count(MagazineMarkup::render($brief['body']), '<th scope="row">') === 8, 'the Buyer\'s Brief scorecard must rate the seven principles of departments 2-8');

// ---- articles: scheduling, drafts, comments toggle ----
$now = time();
$future = $store->saveArticle(['title' => 'Tomorrow\'s piece', 'dept' => 'glass-box', 'body' => 'x', 'status' => 'published', 'publish_at' => $now + 86400, 'comments' => false]);
$draft = $store->saveArticle(['title' => 'Tomorrow\'s piece', 'dept' => 'glass-box', 'body' => 'x', 'status' => 'draft', 'publish_at' => $now]);
contract_check($future['slug'] === 'tomorrow-s-piece' && $draft['slug'] === 'tomorrow-s-piece-2', 'slugs must be unique');
contract_check(count($store->liveArticles('glass-box')) === 1, 'scheduled and draft articles must stay out of the stream');
contract_check(count($store->liveArticles('glass-box', $now + 90000)) === 2, 'a scheduled article must go live when its date arrives');
contract_check($future['comments'] === false, 'comments must be switchable per article');
contract_check(throws(fn () => $store->saveArticle(['title' => 'x', 'dept' => 'no-such-department', 'body' => 'x'])), 'articles must belong to a real department');
$edited = $store->saveArticle(['id' => $future['id'], 'title' => 'Renamed', 'dept' => 'glass-box', 'body' => 'y', 'status' => 'published', 'publish_at' => $now]);
contract_check($edited['slug'] === $future['slug'] && $store->article($edited['slug'])['body'] === 'y', 'editing must keep the permanent link');

// ---- accounts ----
$auth = new MagazineAuth($store, ['google_client_id' => 'id', 'google_client_secret' => 'secret', 'admin_emails' => ['Boss@Example.com']], static function (string $url, ?array $post, array $headers): array {
    return str_contains($url, 'token')
        ? ['access_token' => 'tok']
        : ['sub' => $GLOBALS['google_sub'], 'email' => $GLOBALS['google_email'], 'email_verified' => true, 'name' => 'G User'];
});
$_SESSION = [];
$user = $auth->register('Ada Reader', 'Ada@Example.com', 'correct horse battery');
contract_check($user['role'] === 'reader' && $user['email'] === 'ada@example.com', 'native registration must create a reader with a normalized email');
contract_check(!str_contains((string) file_get_contents($dir . '/users.json.php'), 'correct horse'), 'passwords must never be stored in plain text');
contract_check(throws(fn () => $auth->register('Ada Again', 'ada@example.com', 'another password')), 'duplicate emails must be refused');
contract_check(throws(fn () => $auth->register('Bo', 'bo@example.com', 'short')), 'short passwords must be refused');
contract_check(throws(fn () => $auth->register('Bo', 'not-an-email', 'long enough password')), 'invalid emails must be refused');
$auth->logout();
contract_check($auth->user() === null && !$auth->login('ada@example.com', 'wrong password'), 'a wrong password must not sign in');
contract_check($auth->login('ADA@example.com', 'correct horse battery') && $auth->user()['name'] === 'Ada Reader', 'the right password must sign in');
$token = $auth->csrfToken();
contract_check($auth->checkCsrf($token) && !$auth->checkCsrf('nope') && !$auth->checkCsrf(''), 'CSRF tokens must be enforced');

// Google sign-in
$auth->logout();
contract_check(str_contains($auth->googleAuthUrl('https://m.test/cb'), 'accounts.google.com') && isset($_SESSION['google_state']), 'Google sign-in must start with a state token');
contract_check(throws(fn () => $auth->googleCallback('code', 'forged-state', 'https://m.test/cb')), 'a forged OAuth state must be refused');
$GLOBALS['google_sub'] = 'sub-1';
$GLOBALS['google_email'] = 'boss@example.com';
$auth->googleAuthUrl('https://m.test/cb');
$boss = $auth->googleCallback('code', $_SESSION['google_state'], 'https://m.test/cb');
contract_check($boss['role'] === 'admin' && $auth->user()['id'] === $boss['id'], 'a configured admin email verified by Google must become an administrator');
$GLOBALS['google_sub'] = 'sub-2';
$GLOBALS['google_email'] = 'ada@example.com';
$auth->googleAuthUrl('https://m.test/cb');
$linked = $auth->googleCallback('code', $_SESSION['google_state'], 'https://m.test/cb');
contract_check($linked['id'] === $user['id'] && $linked['role'] === 'reader', 'Google sign-in must link to the existing account for that email');
$auth->logout();
contract_check(!$auth->login('ada@example.com', 'correct horse battery'), 'linking Google must retire the unverified password');

// ---- comments ----
$article = $store->liveArticles('glass-box')[0];
$store->addComment($article['id'], $user, "  First!\r\n\r\n\r\n\r\nSecond line <b>  ");
$comments = $store->comments($article['id']);
contract_check(count($comments) === 1 && $comments[0]['body'] === "First!\n\nSecond line <b>" && $comments[0]['name'] === 'Ada Reader', 'comments must be stored cleaned and attributed');
contract_check(throws(fn () => $store->addComment($article['id'], $user, '   ')) && throws(fn () => $store->addComment($article['id'], $user, str_repeat('a', 2001))), 'empty and oversized comments must be refused');
$store->deleteComment($article['id'], $comments[0]['id']);
contract_check($store->comments($article['id']) === [], 'comments must be removable');

// ---- anti-robot shield ----
$shield = new BotShield($store, ['pow_max' => 2000]);
$solve = static function (array $c): string {
    for ($n = 0; $n <= $c['max']; $n++) {
        if (hash('sha256', $c['salt'] . $n) === $c['challenge']) {
            return base64_encode((string) json_encode(['salt' => $c['salt'], 'challenge' => $c['challenge'], 'signature' => $c['signature'], 'number' => $n]));
        }
    }
    return '';
};
$c = $shield->challenge($now);
$solution = $solve($c);
contract_check($solution !== '' && $shield->verifyChallenge($solution, $now), 'a solved proof of work must verify');
contract_check(!$shield->verifyChallenge($solution, $now), 'a proof of work must be single-use');
contract_check(!$shield->verifyChallenge($solve($shield->challenge($now)), $now + 601), 'a proof of work must expire');
$forged = $shield->challenge($now);
$forged['challenge'] = hash('sha256', $forged['salt'] . '0');
contract_check(!$shield->verifyChallenge(base64_encode((string) json_encode($forged + ['number' => 0])), $now), 'an unsigned challenge must be refused');
contract_check(!$shield->verifyChallenge('garbage', $now), 'malformed solutions must be refused');

$formToken = $shield->formToken($now - 5);
$post = static fn (array $extra = []) => $extra + ['form_token' => $formToken, 'shield' => $solve($shield->challenge($now)), BotShield::HONEYPOT => ''];
contract_check($shield->check($post(), '1.1.1.1', $now) === null, 'a human-shaped submission must pass');
contract_check($shield->check($post([BotShield::HONEYPOT => 'http://spam']), '1.1.1.1', $now) !== null, 'a filled honeypot must be blocked');
contract_check($shield->check($post(['form_token' => $shield->formToken($now)]), '1.1.1.1', $now) !== null, 'an instant submission must be blocked');
contract_check($shield->check($post(['form_token' => $now - 5 . '.forged']), '1.1.1.1', $now) !== null, 'a forged form token must be blocked');
contract_check($shield->check($post(['shield' => '']), '1.1.1.1', $now) !== null, 'a missing proof of work must be blocked');

$turnstile = new BotShield($store, ['pow_max' => 2000, 'turnstile_site_key' => 'site', 'turnstile_secret' => 'secret'], static fn (string $url, array $fields): array => ['success' => $fields['response'] === 'good']);
contract_check($turnstile->check($post(['cf-turnstile-response' => 'good']), '1.1.1.1', $now) === null, 'a verified Turnstile response must pass');
contract_check($turnstile->check($post(['cf-turnstile-response' => 'bad']), '1.1.1.1', $now) !== null && $turnstile->check($post(), '1.1.1.1', $now) !== null, 'a failed or missing Turnstile response must be blocked');

contract_check($store->hit('k', 2, 60, $now) && $store->hit('k', 2, 60, $now) && !$store->hit('k', 2, 60, $now), 'rate limits must block after the limit');
contract_check($store->hit('k', 2, 60, $now + 61), 'rate limits must reset after the window');

// ---- shop ----
$shop = new MagazineShop($store);
$shop->saveSettings(['amazon_tag' => 'mymag-20', 'amazon_domain' => 'www.amazon.com', 'amazon_store_url' => '', 'paypal_store_url' => 'https://www.paypal.com/ncp/payment/ABC123']);
contract_check($shop->resolveLink('amazon', 'B00EXAMPLE') === 'https://www.amazon.com/dp/B00EXAMPLE?tag=mymag-20', 'an ASIN must become a tagged Associates link');
contract_check($shop->resolveLink('amazon', 'https://www.amazon.com/dp/B00EXAMPLE?tag=other-20&th=1') === 'https://www.amazon.com/dp/B00EXAMPLE?tag=mymag-20&th=1', 'Amazon links must carry this magazine\'s tag');
contract_check($shop->resolveLink('paypal', 'ABCDEFGH12345') === 'https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=ABCDEFGH12345', 'a PayPal hosted button ID must become a checkout link');
contract_check($shop->resolveLink('paypal', 'https://paypal.me/mymag/20') === 'https://paypal.me/mymag/20', 'paypal.me links must be accepted');
contract_check(throws(fn () => $shop->resolveLink('paypal', 'https://paypal.com.evil.example/pay')) && throws(fn () => $shop->resolveLink('amazon', 'http://www.amazon.com/dp/B00EXAMPLE'))
    && throws(fn () => $shop->resolveLink('amazon', 'javascript:alert(1)')), 'look-alike, insecure, and script links must be refused');
$shop->saveProduct(['name' => 'Mug', 'kind' => 'paypal', 'target' => 'ABCDEFGH12345', 'price' => '$14']);
$shop->saveProduct(['name' => 'Book', 'kind' => 'amazon', 'target' => 'B00EXAMPLE', 'image' => 'https://img.example/b.jpg']);
contract_check(throws(fn () => $shop->saveProduct(['name' => 'Bad', 'kind' => 'amazon', 'target' => 'B00EXAMPLE', 'image' => 'http://img.example/b.jpg'])), 'product images must be https');
$products = $shop->products();
contract_check(count($products) === 2 && str_contains($products[1]['url'], 'tag=mymag-20'), 'products must list with resolved links');
$shop->deleteProduct($products[0]['id']);
contract_check(count($shop->products()) === 1, 'products must be removable');
contract_check(throws(fn () => $shop->saveSettings(['amazon_tag' => 'bad tag!'])), 'malformed Associates tags must be refused');

// ---- clean up ----
$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
foreach ($it as $f) {
    $f->isDir() ? rmdir($f->getPathname()) : unlink($f->getPathname());
}
rmdir($dir);

fwrite(STDOUT, "Magazine contract passed\n");
