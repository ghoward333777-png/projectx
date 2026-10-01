<?php

declare(strict_types=1);

/**
 * QueryBook Translate — internal admin.
 *
 * Downloads for the internal admin: the Android app (prebuilt APK and Android
 * Studio project), the iPhone/iPad app (Xcode project), and the installable web
 * edition — each optionally pre-connected to a cloud QueryBook store. Also
 * publishes language/domain packs to this server's store.
 *
 * Locked until a password is set:  php translate/admin/set-password.php
 * (or set QBT_ADMIN_PASSWORD_HASH to a password_hash() value).
 */

require_once __DIR__ . '/TranslatePackager.php';
require_once __DIR__ . '/../store/PackStore.php';
require_once __DIR__ . '/../../QrCode.php';

$secure = (($_SERVER['HTTPS'] ?? '') !== '' && ($_SERVER['HTTPS'] ?? '') !== 'off') || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
session_name('qbt_admin');
session_set_cookie_params(['httponly' => true, 'samesite' => 'Strict', 'secure' => $secure, 'path' => '/']);
session_start();
header('X-Frame-Options: DENY');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');
header("Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'");

function admin_hash(): ?string
{
    $env = getenv('QBT_ADMIN_PASSWORD_HASH');
    if (is_string($env) && $env !== '') {
        return $env;
    }
    $file = __DIR__ . '/admin-config.php';
    if (is_file($file)) {
        $cfg = require $file;
        if (is_array($cfg) && !empty($cfg['password_hash'])) {
            return (string) $cfg['password_hash'];
        }
    }
    return null;
}

function e(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function csrf(): string
{
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
    }
    return $_SESSION['csrf'];
}

function csrf_ok(): bool
{
    return isset($_POST['csrf']) && is_string($_POST['csrf']) && hash_equals(csrf(), $_POST['csrf']);
}

function fmt_bytes(int $n): string
{
    return $n < 1048576 ? round($n / 1024, 1) . ' KB' : round($n / 1048576, 1) . ' MB';
}

$hash = admin_hash();
$scheme = $secure ? 'https' : 'http';
$host = $_SERVER['HTTP_HOST'] ?? 'localhost';
$appPath = rtrim(dirname(dirname($_SERVER['SCRIPT_NAME'] ?? '/translate/admin/index.php')), '/');
$appUrl = "{$scheme}://{$host}{$appPath}/";
$storeUrl = "{$scheme}://{$host}{$appPath}/store/index.php/";
$message = '';
$error = '';

// ---------------------------------------------------------------- auth
if (($_POST['action'] ?? '') === 'logout' && csrf_ok()) {
    $_SESSION = [];
    session_regenerate_id(true);
}
if (($_POST['action'] ?? '') === 'login') {
    if ($hash !== null && is_string($_POST['password'] ?? null) && password_verify($_POST['password'], $hash)) {
        session_regenerate_id(true);
        $_SESSION['qbt_admin'] = true;
    } else {
        usleep(800000); // slow down guessing
        $error = 'That password is not correct.';
    }
}
$authed = $hash !== null && !empty($_SESSION['qbt_admin']);

$packager = new TranslatePackager();
$store = new PackStore();

// ---------------------------------------------------------------- actions (admin only)
if ($authed && $_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] !== 'login') {
    if (!csrf_ok()) {
        $error = 'The form expired — please try again.';
    } else {
        $opts = [
            'storeUrl' => !empty($_POST['connect']) ? (string) ($_POST['storeUrl'] ?? '') : '',
            'storeKey' => (string) ($_POST['storeKey'] ?? ''),
            'storeConnected' => !empty($_POST['connect']),
            'gatewayUrl' => (string) ($_POST['gatewayUrl'] ?? ''),
        ];
        try {
            switch ($_POST['action']) {
                case 'download':
                    $edition = (string) ($_POST['edition'] ?? '');
                    $bytes = $packager->export($edition, $opts);
                    $names = ['android' => 'QueryBookTranslate-android-project.zip', 'ios' => 'QueryBookTranslate-ios-project.zip', 'pwa' => 'querybook-translate-web.zip'];
                    header('Content-Type: application/zip');
                    header('Content-Disposition: attachment; filename="' . $names[$edition] . '"');
                    header('Content-Length: ' . strlen($bytes));
                    echo $bytes;
                    exit;
                case 'prebuilt':
                    $path = $packager->prebuiltPath((string) ($_POST['file'] ?? ''));
                    if ($path === null) {
                        throw new RuntimeException('That build is not available.');
                    }
                    $type = str_ends_with($path, '.apk') ? 'application/vnd.android.package-archive' : 'application/octet-stream';
                    header('Content-Type: ' . $type);
                    header('Content-Disposition: attachment; filename="' . basename($path) . '"');
                    header('Content-Length: ' . filesize($path));
                    readfile($path);
                    exit;
                case 'publish':
                    $upload = $_FILES['pack']['tmp_name'] ?? '';
                    if (!is_string($upload) || $upload === '' || !is_uploaded_file($upload)) {
                        throw new RuntimeException('Choose a pack file to publish.');
                    }
                    if (filesize($upload) > 8 * 1024 * 1024) {
                        throw new RuntimeException('Pack files are limited to 8 MB.');
                    }
                    $problems = $store->publish((string) file_get_contents($upload));
                    if ($problems !== []) {
                        throw new RuntimeException('Pack rejected: ' . implode('; ', $problems));
                    }
                    $message = 'Pack published. Connected apps see it on their next catalog refresh.';
                    break;
                case 'unpublish':
                    $message = $store->unpublish((string) ($_POST['id'] ?? '')) ? 'Pack removed from the store.' : 'Nothing to remove.';
                    break;
            }
        } catch (Throwable $ex) {
            $error = $ex->getMessage();
        }
    }
}

?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Translate Admin</title>
<style>
:root { --bg:#f4f7f6; --surface:#fff; --text:#13201d; --muted:#5b6b67; --line:#d7e1de; --accent:#0b6e5f; --on-accent:#fff; --bad:#b3261e; --good:#1f7a3a; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0d1513; --surface:#15201d; --text:#e6efec; --muted:#9db0ab; --line:#2a3a36; --accent:#3cc4ad; --on-accent:#062520; --bad:#ff8a80; --good:#6fd08a; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }
main { max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }
header { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
h1 { font-size: 1.4rem; margin: 0; }
h2 { font-size: 1.1rem; margin: 0 0 8px; }
.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; margin-top: 16px; }
.card { background: var(--surface); border:1px solid var(--line); border-radius: 16px; padding: 16px; }
.card p, .card li { color: var(--muted); font-size: .92rem; }
button, .btn { font: inherit; border-radius: 10px; border: 1px solid var(--accent); background: var(--accent); color: var(--on-accent); padding: 9px 14px; min-height: 42px; cursor: pointer; font-weight: 600; }
button.secondary { background: transparent; color: var(--accent); }
button.danger { background: transparent; color: var(--bad); border-color: var(--bad); padding: 4px 10px; min-height: 32px; }
input[type=text], input[type=url], input[type=password] { font: inherit; width: 100%; padding: 9px 10px; border-radius: 10px; border: 1px solid var(--line); background: var(--bg); color: var(--text); min-height: 42px; }
label { display:block; font-size: .88rem; margin: 8px 0 4px; }
.row { display:flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
.note { padding: 10px 12px; border-radius: 12px; margin-top: 12px; }
.note.ok { border:1px solid var(--good); color: var(--good); }
.note.bad { border:1px solid var(--bad); color: var(--bad); }
code { font-family: ui-monospace, Menlo, monospace; font-size: .85rem; overflow-wrap: anywhere; }
table { width:100%; border-collapse: collapse; font-size: .85rem; }
td, th { text-align: start; padding: 5px 4px; border-bottom: 1px solid var(--line); vertical-align: top; }
.qr svg { width: 180px; height: 180px; background: #fff; padding: 8px; border-radius: 12px; }
.wide { grid-column: 1 / -1; }
.check { display:flex; gap:8px; align-items:center; }
</style>
</head>
<body>
<main>
<header>
  <h1>QueryBook Translate · Admin</h1>
  <?php if ($authed): ?>
  <form method="post"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>"><button class="secondary" name="action" value="logout">Sign out</button></form>
  <?php endif; ?>
</header>

<?php if ($message !== ''): ?><div class="note ok"><?= e($message) ?></div><?php endif; ?>
<?php if ($error !== ''): ?><div class="note bad"><?= e($error) ?></div><?php endif; ?>

<?php if ($hash === null): ?>
  <div class="card" style="margin-top:16px">
    <h2>Admin is locked</h2>
    <p>No admin password is set, so downloads are disabled. On the server run:</p>
    <p><code>php translate/admin/set-password.php</code></p>
    <p>or set the environment variable <code>QBT_ADMIN_PASSWORD_HASH</code> to the output of <code>php -r 'echo password_hash("your-password", PASSWORD_DEFAULT);'</code>.</p>
  </div>
<?php elseif (!$authed): ?>
  <form class="card" method="post" style="margin-top:16px; max-width:420px">
    <h2>Sign in</h2>
    <label for="pw">Admin password</label>
    <input id="pw" type="password" name="password" autocomplete="current-password" required autofocus>
    <div class="row"><button name="action" value="login">Sign in</button></div>
  </form>
<?php else: ?>
  <?php $prebuilt = $packager->prebuilt(); $catalog = $store->catalog(); ?>
  <form method="post" id="dl" class="card" style="margin-top:16px">
    <input type="hidden" name="csrf" value="<?= e(csrf()) ?>">
    <!-- One shared form carries the store options for every download button below. -->
    <input type="hidden" name="action" value="download">
    <h2>Cloud QueryBook store connection for downloads</h2>
    <p>Optional. When checked, the downloaded app starts connected to this store and lists its packs. Every edition still works fully offline, and the user can change or remove the connection in Settings.</p>
    <label class="check"><input type="checkbox" name="connect" value="1" checked> Pre-connect downloads to a QueryBook store</label>
    <label for="storeUrl">Store URL</label>
    <input id="storeUrl" type="url" name="storeUrl" value="<?= e($storeUrl) ?>" placeholder="https://…/translate/store/index.php/">
    <label for="storeKey">Store access key (only if the store requires one — it is embedded in the app)</label>
    <input id="storeKey" type="password" name="storeKey" autocomplete="off" placeholder="<?= PackStore::accessKey() !== null ? 'this store requires a key' : 'this store is open' ?>">
    <label for="gatewayUrl">Optional cloud gateway URL (enhancement; users must still opt in)</label>
    <input id="gatewayUrl" type="url" name="gatewayUrl" placeholder="https://gateway.example.com">
  </form>

  <div class="grid">
    <section class="card">
      <h2>Android — phones and tablets</h2>
      <?php if ($prebuilt !== []): ?>
        <p>Ready-to-install build (debug-signed, for internal sideloading; it connects to a store from Settings):</p>
        <table>
        <?php foreach ($prebuilt as $b): if ($b['platform'] !== 'android') { continue; } ?>
          <tr><td><code><?= e($b['file']) ?></code><br><?= e(fmt_bytes($b['bytes'])) ?> · <?= e(gmdate('Y-m-d', $b['modified'])) ?></td>
          <td><form method="post"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>"><input type="hidden" name="file" value="<?= e($b['file']) ?>"><button name="action" value="prebuilt">Download APK</button></form></td></tr>
        <?php endforeach; ?>
        </table>
      <?php else: ?>
        <p>No prebuilt APK on this server yet — run <code>translate/tools/build-android.sh</code> or download the CI artifact into <code>translate/dist/</code>.</p>
      <?php endif; ?>
      <p>Android Studio project with the store connection above baked in:</p>
      <div class="row"><button form="dl" name="edition" value="android">Download Android project</button></div>
    </section>

    <section class="card">
      <h2>iPhone and iPad</h2>
      <p>Universal Xcode project (iOS/iPadOS 16+). Open on a Mac, choose your signing team, run on a device or archive for TestFlight.</p>
      <div class="row"><button form="dl" name="edition" value="ios">Download Xcode project</button></div>
      <?php foreach ($prebuilt as $b): if ($b['platform'] !== 'ios') { continue; } ?>
        <form method="post" class="row"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>"><input type="hidden" name="file" value="<?= e($b['file']) ?>"><button name="action" value="prebuilt">Download <?= e($b['file']) ?></button></form>
      <?php endforeach; ?>
      <p>No Mac? Install the web edition on the iPhone/iPad: scan the code, then Safari ▸ Share ▸ Add to Home Screen. It works offline after first launch.</p>
    </section>

    <section class="card">
      <h2>Install on a device now</h2>
      <div class="qr"><?= QrCode::svg($appUrl, 4) ?></div>
      <p><code><?= e($appUrl) ?></code></p>
      <p>Android: Chrome ▸ Install app. iPhone/iPad: Safari ▸ Share ▸ Add to Home Screen.</p>
      <div class="row"><button form="dl" name="edition" value="pwa" class="secondary">Download web edition (.zip)</button></div>
    </section>

    <section class="card wide">
      <h2>This server's QueryBook store</h2>
      <p>Apps connect with the URL <code><?= e($storeUrl) ?></code><?= PackStore::accessKey() !== null ? ' and the store access key.' : ' (open — set QBT_STORE_KEY to require a key).' ?> Published packs override bundled packs with the same id; devices verify each pack's sha256 and keep it offline.</p>
      <form method="post" enctype="multipart/form-data" class="row">
        <input type="hidden" name="csrf" value="<?= e(csrf()) ?>">
        <input type="file" name="pack" accept="application/json,.json" required>
        <button name="action" value="publish">Publish pack</button>
      </form>
      <table style="margin-top:12px">
        <tr><th>Pack</th><th>Version</th><th>Entries</th><th>Size</th><th>Source</th><th></th></tr>
        <?php foreach ($catalog as $p): ?>
        <tr>
          <td><code><?= e($p['id']) ?></code></td><td><?= e((string) $p['version']) ?></td><td><?= e((string) $p['entries']) ?></td><td><?= e(fmt_bytes((int) $p['bytes'])) ?></td><td><?= e($p['origin']) ?></td>
          <td><?php if ($p['origin'] === 'published'): ?><form method="post"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>"><input type="hidden" name="id" value="<?= e($p['id']) ?>"><button class="danger" name="action" value="unpublish">Remove</button></form><?php endif; ?></td>
        </tr>
        <?php endforeach; ?>
      </table>
    </section>
  </div>
<?php endif; ?>
</main>
</body>
</html>
