<?php

declare(strict_types=1);

/**
 * MINDATION.AI one-file installer.
 * Upload this file to your website folder, open it in a browser, and fill in the form.
 * It unpacks the site, creates your administrator account, and then deletes itself.
 */

const INSTALL_FILES = '@@FILES@@';

function h(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function page(string $title, string $body): never
{
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: no-store');
    echo '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">'
        . '<title>' . h($title) . '</title><style>'
        . 'body{margin:0;background:#0e0f12;color:#f1efe9;font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}'
        . 'main{max-width:520px;margin:0 auto;padding:48px 20px}'
        . '.logo{font-weight:900;font-size:40px;letter-spacing:-.045em;line-height:1}.logo span{color:#ff4d2e}'
        . 'h1{font:700 28px/1.2 Georgia,serif;margin:28px 0 8px}p{margin:0 0 16px;color:#c9c6bd}'
        . 'form{display:grid;gap:16px;margin-top:24px}label{display:grid;gap:6px;font-size:14px;font-weight:600;color:#f1efe9}small{font-weight:400;color:#a4a8b0}'
        . 'input{font:16px/1.5 inherit;padding:11px 12px;border-radius:6px;border:1px solid #3a3f47;background:#191b20;color:#f1efe9;width:100%;box-sizing:border-box}'
        . 'input:focus-visible,button:focus-visible,a:focus-visible{outline:3px solid #ffd23f;outline-offset:2px}'
        . 'button,.button{display:inline-block;font:700 16px inherit;padding:13px 22px;border:0;border-radius:6px;background:#ff4d2e;color:#fff;cursor:pointer;text-decoration:none;justify-self:start}'
        . '.error{padding:12px 16px;border-left:4px solid #ff8a7d;background:#191b20;color:#ff8a7d}.ok{padding:12px 16px;border-left:4px solid #4fd1b0;background:#191b20;color:#f1efe9}'
        . 'code{background:#191b20;padding:1px 6px;border-radius:4px}'
        . '</style></head><body><main><div class="logo">MINDATION<span>.AI</span></div>' . $body . '</main></body></html>';
    exit;
}

/** Unpack every site file next to this installer. Content in data/ and config.php are never touched. */
function unpack_site(): void
{
    foreach (INSTALL_FILES as $name => $encoded) {
        $path = __DIR__ . '/' . $name;
        if (!is_dir(dirname($path)) && !mkdir(dirname($path), 0755, true) && !is_dir(dirname($path))) {
            throw new RuntimeException('Could not create the folder for ' . $name . '.');
        }
        if (file_put_contents($path, base64_decode($encoded, true)) === false) {
            throw new RuntimeException('Could not write ' . $name . '.');
        }
    }
}

/** A host's placeholder home page would be shown instead of the magazine; set it aside. */
function set_aside_placeholders(): array
{
    $moved = [];
    foreach (['index.html', 'index.htm', 'default.html', 'default.htm'] as $name) {
        if (is_file(__DIR__ . '/' . $name) && @rename(__DIR__ . '/' . $name, __DIR__ . '/old-' . $name)) {
            $moved[] = $name;
        }
    }
    return $moved;
}

function finish(string $heading, string $message, array $moved): never
{
    $removed = @unlink(__FILE__);
    $body = '<h1>' . h($heading) . '</h1><p class="ok">' . h($message) . '</p>';
    if ($moved !== []) {
        $body .= '<p>Your host\'s placeholder page (' . h(implode(', ', $moved)) . ') was renamed with <code>old-</code> in front so the magazine is your home page.</p>';
    }
    $body .= $removed
        ? '<p>This installer has deleted itself.</p>'
        : '<p class="error">Please delete <code>' . h(basename(__FILE__)) . '</code> from your website folder now.</p>';
    page($heading, $body . '<p><a class="button" href="index.php?p=login">Sign in to your magazine</a></p>');
}

$problems = [];
if (PHP_VERSION_ID < 80100) {
    $problems[] = 'This hosting runs PHP ' . PHP_VERSION . '. The magazine needs PHP 8.1 or newer: raise the PHP version in your hosting settings, then reload this page.';
}
if (!is_writable(__DIR__)) {
    $problems[] = 'This folder is not writable by the web server. Set its permissions to 755 (or 775) in File Manager, then reload this page.';
}
if ($problems !== []) {
    page('Not ready yet', '<h1>Not ready yet</h1>' . implode('', array_map(static fn ($p) => '<p class="error">' . h($p) . '</p>', $problems)));
}

$usersFile = __DIR__ . '/data/users.json.php';
$installed = is_file($usersFile) && str_contains((string) file_get_contents($usersFile), '"id"');
$error = null;
$in = ['site_name' => 'MINDATION.AI', 'tagline' => 'Efficient, local, verifiable, auditable AI, for the people who lead.', 'name' => '', 'email' => ''];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        if ($installed) {
            unpack_site();
            finish('Site updated', 'The magazine files were updated. Your articles, members, comments, and settings were kept.', []);
        }
        foreach (array_keys($in) as $key) {
            $in[$key] = trim((string) ($_POST[$key] ?? ''));
        }
        $password = (string) ($_POST['password'] ?? '');
        if ($in['site_name'] === '' || mb_strlen($in['site_name']) > 80) {
            throw new DomainException('Please enter a site name.');
        }
        if (mb_strlen($in['name']) < 2 || mb_strlen($in['name']) > 60) {
            throw new DomainException('Please enter your name (2 to 60 characters).');
        }
        if (filter_var($in['email'], FILTER_VALIDATE_EMAIL) === false) {
            throw new DomainException('Please enter a valid email address.');
        }
        if (strlen($password) < 10) {
            throw new DomainException('Please choose a password of at least 10 characters.');
        }
        unpack_site();
        $moved = set_aside_placeholders();
        require_once __DIR__ . '/MagazineStore.php';
        $store = new MagazineStore(__DIR__ . '/data');
        $store->seedIfEmpty();
        $store->createUser(['name' => $in['name'], 'email' => $in['email'], 'password_hash' => password_hash($password, PASSWORD_DEFAULT), 'role' => 'admin']);
        if (!is_file(__DIR__ . '/config.php')) {
            $https = (($_SERVER['HTTPS'] ?? '') !== '' && $_SERVER['HTTPS'] !== 'off') || ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https';
            $dir = rtrim(str_replace('\\', '/', dirname($_SERVER['SCRIPT_NAME'] ?? '/')), '/');
            $config = [
                'site_name' => $in['site_name'],
                'tagline' => $in['tagline'],
                'base_url' => ($https ? 'https' : 'http') . '://' . ($_SERVER['HTTP_HOST'] ?? 'localhost') . $dir . '/',
                'timezone' => 'UTC',
                'google_client_id' => '',
                'google_client_secret' => '',
                'admin_emails' => [strtolower($in['email'])],
                'turnstile_site_key' => '',
                'turnstile_secret' => '',
            ];
            file_put_contents(__DIR__ . '/config.php', "<?php\n\n// Site settings. See config.sample.php for what each one does.\nreturn " . var_export($config, true) . ";\n");
        }
        finish('Your magazine is live', 'The site is installed and your administrator account is ready. Sign in with the email and password you just chose.', $moved);
    } catch (DomainException $ex) {
        $error = $ex->getMessage();
    } catch (Throwable $ex) {
        $error = 'The install stopped: ' . $ex->getMessage();
    }
}

if ($installed) {
    page('Update MINDATION.AI', '<h1>Update the site</h1><p>This magazine is already installed. Updating replaces the site files with the newer ones in this installer and keeps all your articles, members, comments, and settings.</p>'
        . ($error !== null ? '<p class="error">' . h($error) . '</p>' : '') . '<form method="post"><button type="submit">Update the site</button></form>');
}

page('Install MINDATION.AI', '<h1>Install your magazine</h1><p>One step. This creates the site in this folder and makes you its administrator. No database is needed.</p>'
    . ($error !== null ? '<p class="error">' . h($error) . '</p>' : '')
    . '<form method="post" autocomplete="off">'
    . '<label>Site name<input type="text" name="site_name" value="' . h($in['site_name']) . '" maxlength="80" required></label>'
    . '<label>Tagline<input type="text" name="tagline" value="' . h($in['tagline']) . '" maxlength="160"></label>'
    . '<label>Your name<input type="text" name="name" value="' . h($in['name']) . '" minlength="2" maxlength="60" required><small>Shown as the byline on articles you write.</small></label>'
    . '<label>Your email<input type="email" name="email" value="' . h($in['email']) . '" required></label>'
    . '<label>Choose a password<input type="password" name="password" minlength="10" autocomplete="new-password" required><small>At least 10 characters.</small></label>'
    . '<button type="submit">Install</button></form>');
