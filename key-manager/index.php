<?php

declare(strict_types=1);

/**
 * Cloud Key Manager — a friendlier replacement for the Cloud Console's
 * "APIs & Services → Credentials" pages. Create, view, copy, edit, restrict,
 * delete and restore Google API keys, keep every key (Google or not) in an
 * encrypted local vault, and see per-API traffic.
 *
 * Run locally only:  php -S 127.0.0.1:8090 -t key-manager
 */

require_once __DIR__ . '/KeyVault.php';
require_once __DIR__ . '/GoogleCloudClient.php';

// This app holds secrets: refuse anyone who is not on this machine.
$remote = (string) ($_SERVER['REMOTE_ADDR'] ?? '');
if (!in_array($remote, ['127.0.0.1', '::1'], true) && getenv('KEY_MANAGER_ALLOW_REMOTE') !== '1') {
    http_response_code(403);
    exit('Cloud Key Manager only answers on this computer (127.0.0.1).');
}

header('X-Frame-Options: DENY');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('Cache-Control: no-store');
header("Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'");

session_name('ckm_session');
session_start([
    'cookie_httponly' => true,
    'cookie_samesite' => 'Strict',
    'use_strict_mode' => true,
    'use_only_cookies' => true,
]);

const KM_IDLE_SECONDS = 1200;
const KM_PAD_COOKIE = 'ckm_pad';

$vault = new KeyVault(KeyVault::defaultPath());
$_SESSION['csrf'] ??= bin2hex(random_bytes(16));

// ----------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------

function h(mixed $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function km_flash(string $type, string $message): void
{
    $_SESSION['flash'][] = ['type' => $type, 'message' => $message];
}

/** @param array<string, string> $params */
function km_redirect(array $params = []): never
{
    header('Location: index.php' . ($params !== [] ? '?' . http_build_query($params) : ''), true, 303);
    exit;
}

function km_csrf_field(): string
{
    return '<input type="hidden" name="csrf" value="' . h($_SESSION['csrf']) . '">';
}

/**
 * The unlocked file key is split in two: half in the server session, half in
 * an HttpOnly cookie. Neither the session file nor the cookie alone opens
 * the vault.
 */
function km_remember_key(string $key): void
{
    $pad = random_bytes(strlen($key));
    $_SESSION['vault_half'] = base64_encode($key ^ $pad);
    $_SESSION['last_seen'] = time();
    setcookie(KM_PAD_COOKIE, base64_encode($pad), ['httponly' => true, 'samesite' => 'Strict', 'path' => '/']);
    $_COOKIE[KM_PAD_COOKIE] = base64_encode($pad);
}

function km_key(): ?string
{
    $half = base64_decode((string) ($_SESSION['vault_half'] ?? ''), true);
    $pad = base64_decode((string) ($_COOKIE[KM_PAD_COOKIE] ?? ''), true);
    if ($half === false || $pad === false || $half === '' || strlen($half) !== strlen($pad)) {
        return null;
    }
    if (time() - (int) ($_SESSION['last_seen'] ?? 0) > KM_IDLE_SECONDS) {
        km_lock();
        km_flash('info', 'The vault locked itself after 20 idle minutes.');
        return null;
    }
    $_SESSION['last_seen'] = time();
    return $half ^ $pad;
}

function km_lock(): void
{
    $flash = $_SESSION['flash'] ?? [];
    $_SESSION = ['csrf' => bin2hex(random_bytes(16)), 'flash' => $flash];
    session_regenerate_id(true);
    setcookie(KM_PAD_COOKIE, '', ['expires' => time() - 3600, 'httponly' => true, 'samesite' => 'Strict', 'path' => '/']);
}

/** @param array<string, mixed> $connection */
function km_client(array $connection, ?string $project): GoogleCloudClient
{
    $mode = (string) ($connection['mode'] ?? 'gcloud');
    $inner = match ($mode) {
        'service_account' => GoogleCloudClient::serviceAccountTokenProvider(
            (array) (json_decode((string) ($connection['service_account_json'] ?? ''), true) ?: throw new GoogleApiException('No service account key saved yet. Add one on the Connection tab.'))
        ),
        'token' => GoogleCloudClient::staticTokenProvider((string) ($connection['token'] ?? '')),
        default => GoogleCloudClient::gcloudTokenProvider(trim((string) ($connection['gcloud_path'] ?? '')) ?: 'gcloud'),
    };
    $fingerprint = hash('sha256', json_encode([$mode, $connection['service_account_json'] ?? '', $connection['token'] ?? '', $connection['gcloud_path'] ?? '']) ?: '');
    $provider = static function () use ($inner, $fingerprint, $mode): string {
        $cache = $_SESSION['token_cache'] ?? null;
        if (is_array($cache) && $cache['fp'] === $fingerprint && $cache['expires'] > time()) {
            return (string) $cache['token'];
        }
        $token = $inner();
        if ($mode !== 'token') {
            $_SESSION['token_cache'] = ['fp' => $fingerprint, 'token' => $token, 'expires' => time() + 2700];
        }
        return $token;
    };
    // User sign-ins (gcloud / pasted token) need a project to bill quota to.
    $quota = ($mode !== 'service_account' && ($connection['quota_header'] ?? true) && $project !== null && $project !== '') ? $project : null;
    return new GoogleCloudClient($provider, null, $quota);
}

function km_relative_time(string $iso): string
{
    $time = strtotime($iso);
    if ($time === false) {
        return '';
    }
    $diff = time() - $time;
    return match (true) {
        $diff < 60 => 'just now',
        $diff < 3600 => intdiv($diff, 60) . ' min ago',
        $diff < 86400 => intdiv($diff, 3600) . ' h ago',
        $diff < 86400 * 60 => intdiv($diff, 86400) . ' days ago',
        default => gmdate('M j, Y', $time),
    };
}

function km_number(?float $value, string $suffix = ''): string
{
    if ($value === null) {
        return '—';
    }
    return (floor($value) == $value ? number_format($value) : number_format($value, $value < 10 ? 2 : 1)) . $suffix;
}

// ----------------------------------------------------------------------
// State
// ----------------------------------------------------------------------

$key = $vault->exists() ? km_key() : null;
$data = null;
if ($key !== null) {
    try {
        $data = $vault->read($key);
    } catch (Throwable) {
        km_lock();
        $key = null;
    }
}
$connection = (array) ($data['connection'] ?? []);
$project = (string) ($_SESSION['project'] ?? $connection['default_project'] ?? '');

// ----------------------------------------------------------------------
// Actions (POST → redirect)
// ----------------------------------------------------------------------

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = (string) ($_POST['action'] ?? '');
    $back = ['view' => (string) ($_POST['back'] ?? 'keys')];
    if (!hash_equals((string) $_SESSION['csrf'], (string) ($_POST['csrf'] ?? ''))) {
        km_flash('error', 'That form expired. Please try again.');
        km_redirect();
    }

    try {
        if ($action === 'setup') {
            if ((string) ($_POST['passphrase'] ?? '') !== (string) ($_POST['confirm'] ?? '')) {
                throw new InvalidArgumentException('The two passphrases do not match.');
            }
            session_regenerate_id(true);
            km_remember_key($vault->create((string) $_POST['passphrase']));
            km_flash('ok', 'Your vault is ready. Next: connect your Google account.');
            km_redirect(['view' => 'connection']);
        }
        if ($action === 'unlock') {
            usleep(random_int(100000, 300000));
            $unlocked = $vault->unlock((string) ($_POST['passphrase'] ?? ''));
            session_regenerate_id(true);
            km_remember_key($unlocked);
            km_redirect();
        }
        if ($key === null || $data === null) {
            km_redirect();
        }
        if ($action === 'lock') {
            km_lock();
            km_flash('info', 'Vault locked.');
            km_redirect();
        }

        $save = static function (array $newData) use ($vault, $key): void {
            $vault->write($key, $newData);
        };

        switch ($action) {
            case 'save_connection':
                $mode = (string) ($_POST['mode'] ?? 'gcloud');
                if (!in_array($mode, ['gcloud', 'service_account', 'token'], true)) {
                    throw new InvalidArgumentException('Unknown sign-in method.');
                }
                $json = trim((string) ($_POST['service_account_json'] ?? ''));
                if (isset($_FILES['service_account_file']) && is_uploaded_file((string) $_FILES['service_account_file']['tmp_name'])) {
                    $json = trim((string) file_get_contents((string) $_FILES['service_account_file']['tmp_name']));
                }
                if ($json === '') {
                    $json = (string) ($connection['service_account_json'] ?? '');
                } else {
                    $decoded = json_decode($json, true);
                    if (!is_array($decoded) || ($decoded['type'] ?? '') !== 'service_account') {
                        throw new InvalidArgumentException('That file is not a service account key (it should contain "type": "service_account").');
                    }
                    GoogleCloudClient::serviceAccountAssertion($decoded, time());
                }
                $token = trim((string) ($_POST['token'] ?? ''));
                $default = trim((string) ($_POST['default_project'] ?? ''));
                if ($default !== '') {
                    GoogleCloudClient::assertProject($default);
                }
                $data['connection'] = [
                    'mode' => $mode,
                    'gcloud_path' => trim((string) ($_POST['gcloud_path'] ?? '')),
                    'service_account_json' => $json,
                    'token' => $token !== '' ? $token : (string) ($connection['token'] ?? ''),
                    'quota_header' => isset($_POST['quota_header']),
                    'default_project' => $default,
                ];
                $save($data);
                unset($_SESSION['token_cache'], $_SESSION['projects_cache']);
                if ($default !== '') {
                    $_SESSION['project'] = $default;
                }
                $client = km_client($data['connection'], $default !== '' ? $default : null);
                $count = count($client->searchProjects());
                km_flash('ok', "Connected to Google. You can reach {$count} project" . ($count === 1 ? '' : 's') . '.');
                km_redirect(['view' => 'keys']);

            case 'create_key':
                GoogleCloudClient::assertProject($project);
                $restrictions = GoogleCloudClient::buildRestrictions(
                    (string) ($_POST['app_type'] ?? 'none'),
                    (string) ($_POST['app_values'] ?? ''),
                    array_map('strval', (array) ($_POST['apis'] ?? []))
                );
                $created = km_client($connection, $project)->createKey($project, (string) ($_POST['display_name'] ?? ''), $restrictions);
                $data = KeyVault::upsert($data, [
                    'label' => (string) ($created['displayName'] ?? ''),
                    'provider' => 'Google Cloud',
                    'project' => $project,
                    'google_name' => (string) ($created['name'] ?? ''),
                    'key_string' => (string) ($created['keyString'] ?? ''),
                    'notes' => trim((string) ($_POST['notes'] ?? '')),
                ]);
                $save($data);
                $entry = KeyVault::findByGoogleName($data, (string) ($created['name'] ?? ''));
                km_flash('ok', 'Key created and saved in your vault.');
                km_redirect(['view' => 'keys', 'reveal' => (string) ($entry['id'] ?? '')]);

            case 'update_key':
                $name = (string) ($_POST['key'] ?? '');
                $restrictions = GoogleCloudClient::buildRestrictions(
                    (string) ($_POST['app_type'] ?? 'none'),
                    (string) ($_POST['app_values'] ?? ''),
                    array_map('strval', (array) ($_POST['apis'] ?? []))
                );
                $updated = km_client($connection, $project)->updateKey($name, (string) ($_POST['display_name'] ?? ''), $restrictions, (string) ($_POST['etag'] ?? ''));
                $entry = KeyVault::findByGoogleName($data, $name);
                if ($entry !== null) {
                    $data = KeyVault::upsert($data, ['id' => $entry['id'], 'label' => (string) ($updated['displayName'] ?? $entry['label'])]);
                    $save($data);
                }
                km_flash('ok', 'Key updated. Restriction changes can take a few minutes to reach Google’s servers.');
                km_redirect(['view' => 'keys']);

            case 'reveal_key':
                $name = (string) ($_POST['key'] ?? '');
                $client = km_client($connection, $project);
                $secret = $client->keyString($name);
                $info = $client->getKey($name);
                $entry = KeyVault::findByGoogleName($data, $name);
                $data = KeyVault::upsert($data, [
                    'id' => (string) ($entry['id'] ?? ''),
                    'label' => (string) ($info['displayName'] ?? $entry['label'] ?? ''),
                    'provider' => 'Google Cloud',
                    'project' => $project,
                    'google_name' => $name,
                    'key_string' => $secret,
                    'status' => '',
                ]);
                $save($data);
                $entry = KeyVault::findByGoogleName($data, $name);
                km_redirect(['view' => 'keys', 'reveal' => (string) ($entry['id'] ?? '')]);

            case 'delete_key':
                $name = (string) ($_POST['key'] ?? '');
                km_client($connection, $project)->deleteKey($name);
                $entry = KeyVault::findByGoogleName($data, $name);
                if ($entry !== null) {
                    $data = KeyVault::upsert($data, ['id' => $entry['id'], 'status' => 'Deleted on Google ' . gmdate('M j, Y')]);
                    $save($data);
                }
                km_flash('ok', 'Key deleted. It stops working right away; you can restore it for 30 days from the "Recently deleted" list.');
                km_redirect(['view' => 'keys']);

            case 'restore_key':
                $name = (string) ($_POST['key'] ?? '');
                km_client($connection, $project)->undeleteKey($name);
                $entry = KeyVault::findByGoogleName($data, $name);
                if ($entry !== null) {
                    $data = KeyVault::upsert($data, ['id' => $entry['id'], 'status' => '']);
                    $save($data);
                }
                km_flash('ok', 'Key restored and working again.');
                km_redirect(['view' => 'keys']);

            case 'enable_service':
                GoogleCloudClient::assertProject($project);
                $service = strtolower(trim((string) ($_POST['service'] ?? '')));
                km_client($connection, $project)->enableService($project, $service);
                unset($_SESSION['services_cache']);
                km_flash('ok', "Turned on {$service}.");
                km_redirect($back);

            case 'vault_save':
                $id = (string) ($_POST['id'] ?? '');
                $existing = $id !== '' ? KeyVault::find($data, $id) : null;
                if ($id !== '' && $existing === null) {
                    throw new InvalidArgumentException('That vault entry no longer exists.');
                }
                $label = trim((string) ($_POST['label'] ?? ''));
                $secret = trim((string) ($_POST['key_string'] ?? ''));
                if ($label === '') {
                    throw new InvalidArgumentException('Give the entry a name.');
                }
                if ($existing === null && $secret === '') {
                    throw new InvalidArgumentException('Paste the key you want to store.');
                }
                $entry = [
                    'id' => $id,
                    'label' => mb_substr($label, 0, 120),
                    'provider' => mb_substr(trim((string) ($_POST['provider'] ?? '')) ?: 'Other', 0, 60),
                    'project' => mb_substr(trim((string) ($_POST['project'] ?? '')), 0, 120),
                    'notes' => mb_substr(trim((string) ($_POST['notes'] ?? '')), 0, 2000),
                ];
                if ($secret !== '') {
                    $entry['key_string'] = $secret;
                }
                $data = KeyVault::upsert($data, $entry);
                $save($data);
                km_flash('ok', $existing === null ? 'Saved to your vault.' : 'Vault entry updated.');
                km_redirect(['view' => 'vault']);

            case 'vault_delete':
                $data = KeyVault::remove($data, (string) ($_POST['id'] ?? ''));
                $save($data);
                km_flash('ok', 'Removed from your vault. (Nothing was changed on Google.)');
                km_redirect(['view' => 'vault']);

            case 'change_passphrase':
                $vault->unlock((string) ($_POST['current'] ?? ''));
                if ((string) ($_POST['passphrase'] ?? '') !== (string) ($_POST['confirm'] ?? '')) {
                    throw new InvalidArgumentException('The two new passphrases do not match.');
                }
                km_remember_key($vault->changePassphrase($key, (string) $_POST['passphrase']));
                km_flash('ok', 'Passphrase changed.');
                km_redirect(['view' => 'connection']);
        }
        km_redirect();
    } catch (GoogleApiException $e) {
        if ($e->isServiceDisabled() && $e->service !== '') {
            $_SESSION['needs_service'] = $e->service;
        }
        km_flash('error', $e->getMessage());
    } catch (InvalidArgumentException | RuntimeException | JsonException $e) {
        km_flash('error', $e->getMessage());
    }
    km_redirect(in_array($action, ['setup', 'unlock'], true) ? [] : $back + array_filter(['key' => $action === 'update_key' ? (string) ($_POST['key'] ?? '') : '']));
}

// ----------------------------------------------------------------------
// GET: choose a project, gather what the view needs
// ----------------------------------------------------------------------

$view = (string) ($_GET['view'] ?? 'keys');
if (!in_array($view, ['keys', 'edit', 'apis', 'vault', 'connection'], true)) {
    $view = 'keys';
}
if ($key !== null && isset($_GET['project'])) {
    $candidate = trim((string) $_GET['project']);
    if (GoogleCloudClient::isProjectId($candidate)) {
        $_SESSION['project'] = $candidate;
        unset($_SESSION['services_cache']);
        $project = $candidate;
    } else {
        km_flash('error', 'That does not look like a project ID.');
    }
}

$flashes = (array) ($_SESSION['flash'] ?? []);
unset($_SESSION['flash']);
$needsService = (string) ($_SESSION['needs_service'] ?? '');
unset($_SESSION['needs_service']);

$errors = [];
$projects = [];
$services = [];
$keys = [];
$deletedKeys = [];
$editKey = null;
$metrics = null;
$window = (int) ($_GET['window'] ?? 2592000);
$windows = [3600 => 'Last hour', 86400 => 'Last day', 604800 => 'Last 7 days', 2592000 => 'Last 30 days'];
if (!isset($windows[$window])) {
    $window = 2592000;
}
$connected = $connection !== [];

if ($key !== null && $data !== null && $connected && in_array($view, ['keys', 'edit', 'apis'], true)) {
    $client = km_client($connection, $project !== '' ? $project : null);
    try {
        $cache = $_SESSION['projects_cache'] ?? null;
        if (is_array($cache) && $cache['expires'] > time()) {
            $projects = $cache['items'];
        } else {
            $projects = $client->searchProjects();
            $_SESSION['projects_cache'] = ['items' => $projects, 'expires' => time() + 300];
        }
        if ($project === '' && $projects !== []) {
            $project = $projects[0]['id'];
            $_SESSION['project'] = $project;
            $client = km_client($connection, $project);
        }
    } catch (Throwable $e) {
        $errors[] = $e->getMessage();
    }

    if ($project !== '') {
        try {
            $cache = $_SESSION['services_cache'] ?? null;
            if (is_array($cache) && $cache['project'] === $project && $cache['expires'] > time()) {
                $services = $cache['items'];
            } else {
                $services = $client->enabledServices($project);
                $_SESSION['services_cache'] = ['project' => $project, 'items' => $services, 'expires' => time() + 300];
            }
        } catch (GoogleApiException $e) {
            $needsService = $e->isServiceDisabled() ? $e->service : $needsService;
            $errors[] = $e->getMessage();
        } catch (Throwable $e) {
            $errors[] = $e->getMessage();
        }

        try {
            if ($view === 'keys') {
                foreach ($client->listKeys($project, true) as $item) {
                    if (!empty($item['deleteTime'])) {
                        $deletedKeys[] = $item;
                    } else {
                        $keys[] = $item;
                    }
                }
            } elseif ($view === 'edit') {
                $editKey = $client->getKey((string) ($_GET['key'] ?? ''));
            } elseif ($view === 'apis') {
                $metrics = $client->serviceMetrics($project, $window);
            }
        } catch (GoogleApiException $e) {
            $needsService = $e->isServiceDisabled() ? $e->service : $needsService;
            $errors[] = $e->getMessage();
        } catch (Throwable $e) {
            $errors[] = $e->getMessage();
        }
    }
}

$reveal = ($data !== null && isset($_GET['reveal'])) ? KeyVault::find($data, (string) $_GET['reveal']) : null;
$editEntry = ($data !== null && isset($_GET['edit'])) ? KeyVault::find($data, (string) $_GET['edit']) : null;
$entries = (array) ($data['entries'] ?? []);
usort($entries, static fn (array $a, array $b): int => strcasecmp((string) $a['provider'] . $a['label'], (string) $b['provider'] . $b['label']));

/** Render the shared create/edit key form fields. */
function km_key_fields(array $form, array $services, string $displayName): void
{
    ?>
    <label>Key name <span class="hint">— something you'll recognise, like "YouTube uploader (laptop)"</span>
        <input name="display_name" required maxlength="63" value="<?= h($displayName) ?>">
    </label>
    <fieldset>
        <legend>Where can this key be used from?</legend>
        <select name="app_type" data-app-type>
            <?php foreach (GoogleCloudClient::APP_TYPES as $value => $label): ?>
                <option value="<?= h($value) ?>" <?= $form['type'] === $value ? 'selected' : '' ?>><?= h($label) ?></option>
            <?php endforeach; ?>
        </select>
        <textarea name="app_values" rows="3" data-app-values placeholder="One per line" <?= $form['type'] === 'none' ? 'hidden' : '' ?>><?= h($form['lines']) ?></textarea>
        <p class="hint" data-app-help></p>
    </fieldset>
    <fieldset>
        <legend>Which APIs can it call? <span class="hint">Leave all unticked to allow every enabled API. Ticking only what an app needs limits the damage if a key leaks.</span></legend>
        <?php $all = $services; foreach ($form['apis'] as $api) { $all[$api] ??= $api; } ?>
        <?php if ($all === []): ?>
            <p class="hint">No enabled APIs found for this project yet.</p>
        <?php else: ?>
            <input class="filter" type="search" placeholder="Filter APIs" data-filter-list="api-list">
            <div class="checks" id="api-list">
                <?php foreach ($all as $service => $title): ?>
                    <label class="check"><input type="checkbox" name="apis[]" value="<?= h($service) ?>" <?= in_array($service, $form['apis'], true) ? 'checked' : '' ?>> <span><?= h($title) ?><small><?= h($service) ?></small></span></label>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>
    </fieldset>
    <?php
}
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Cloud Key Manager</title>
    <style>
        :root { color-scheme: dark; --bg: #11141c; --panel: #1a1d28; --line: #343747; --text: #eef0f6; --muted: #9ea3b5; --accent: #6fd6c3; --danger: #ff8a8a; --warn: #ffd27a; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
        * { box-sizing: border-box; }
        body { margin: 0; background: radial-gradient(circle at top left, #12313a, var(--bg) 45%), var(--bg); color: var(--text); min-height: 100vh; }
        main { max-width: 1100px; margin: 0 auto; padding: 28px 16px 80px; }
        header { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 20px; justify-content: space-between; }
        .brand { font-weight: 800; font-size: 20px; letter-spacing: -.02em; }
        .brand small { display: block; color: var(--accent); font-size: 11px; letter-spacing: .14em; text-transform: uppercase; font-weight: 700; }
        nav.tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 22px 0 6px; }
        nav.tabs a { padding: 9px 14px; border-radius: 999px; color: var(--muted); text-decoration: none; border: 1px solid transparent; font-weight: 600; font-size: 14px; }
        nav.tabs a.on { color: var(--text); border-color: var(--line); background: var(--panel); }
        h1 { font-size: clamp(26px, 4vw, 38px); letter-spacing: -.03em; margin: 18px 0 6px; }
        h2 { font-size: 18px; margin: 0 0 12px; }
        p { color: var(--muted); line-height: 1.55; }
        a { color: #8fe0d2; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px; margin-top: 18px; }
        .narrow { max-width: 460px; margin: 60px auto; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { text-align: left; padding: 10px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
        th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; font-weight: 700; }
        td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .table-wrap { overflow-x: auto; }
        small, .hint { color: var(--muted); font-size: 12px; font-weight: 400; }
        td small { display: block; margin-top: 2px; }
        label { display: block; margin: 12px 0; font-weight: 600; font-size: 14px; }
        input, select, textarea { width: 100%; margin-top: 6px; padding: 10px 12px; border-radius: 9px; border: 1px solid var(--line); background: #0e1118; color: var(--text); font: inherit; font-weight: 400; }
        textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
        fieldset { border: 1px solid var(--line); border-radius: 10px; margin: 14px 0; padding: 12px 14px; }
        legend { font-weight: 600; font-size: 14px; padding: 0 6px; }
        .checks { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 4px 14px; max-height: 280px; overflow-y: auto; margin-top: 8px; }
        label.check { display: flex; gap: 8px; align-items: flex-start; margin: 4px 0; font-weight: 500; }
        label.check input { width: auto; margin-top: 3px; }
        label.check small { display: block; }
        .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .row > * { flex: 0 0 auto; }
        .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0 18px; }
        button, .button { display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; border-radius: 9px; border: 1px solid var(--line); background: #232736; color: var(--text); font: inherit; font-weight: 600; font-size: 14px; cursor: pointer; text-decoration: none; }
        button.primary { background: var(--accent); color: #0b1d1a; border-color: var(--accent); }
        button.danger { color: var(--danger); }
        button.small, .button.small { padding: 5px 10px; font-size: 13px; }
        form.inline { display: inline; }
        .flash { padding: 12px 14px; border-radius: 10px; margin-top: 12px; border: 1px solid var(--line); }
        .flash.ok { border-color: #2f7d6f; background: #153029; }
        .flash.error { border-color: #8a3a3a; background: #331b1e; }
        .flash.info { background: #1f2333; }
        .secret { display: flex; gap: 8px; }
        .secret input { font-family: ui-monospace, Menlo, monospace; margin: 0; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; border: 1px solid var(--line); color: var(--muted); }
        .badge.ok { color: var(--accent); border-color: #2f7d6f; }
        .badge.warn { color: var(--warn); border-color: #7a6431; }
        .mono { font-family: ui-monospace, Menlo, monospace; font-size: 13px; }
        .filter { max-width: 320px; }
        .empty { border: 1px dashed var(--line); border-radius: 12px; padding: 22px; color: var(--muted); }
        details summary { cursor: pointer; font-weight: 600; }
        .choice { display: block; border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin: 8px 0; }
        .choice input[type=radio] { width: auto; margin: 0 8px 0 0; }
        code { background: #0e1118; border: 1px solid var(--line); border-radius: 6px; padding: 1px 6px; font-size: 13px; }
    </style>
</head>
<body>
<main>
<?php if (!$vault->exists()): ?>
    <div class="panel narrow">
        <div class="brand"><small>Cloud Key Manager</small>Create your vault</div>
        <p>Everything you store here — API keys, your Google sign-in settings — is encrypted with a passphrase only you know. Pick something memorable; there is no way to recover it.</p>
        <?php foreach ($flashes as $flash): ?><div class="flash <?= h($flash['type']) ?>"><?= h($flash['message']) ?></div><?php endforeach; ?>
        <form method="post">
            <?= km_csrf_field() ?><input type="hidden" name="action" value="setup">
            <label>Passphrase <input type="password" name="passphrase" minlength="<?= KeyVault::MIN_PASSPHRASE ?>" required autocomplete="new-password"></label>
            <label>Type it again <input type="password" name="confirm" required autocomplete="new-password"></label>
            <button class="primary">Create vault</button>
        </form>
        <p class="hint">Saved to <span class="mono"><?= h($vault->path()) ?></span></p>
    </div>
<?php elseif ($key === null): ?>
    <div class="panel narrow">
        <div class="brand"><small>Cloud Key Manager</small>Unlock your vault</div>
        <?php foreach ($flashes as $flash): ?><div class="flash <?= h($flash['type']) ?>"><?= h($flash['message']) ?></div><?php endforeach; ?>
        <form method="post">
            <?= km_csrf_field() ?><input type="hidden" name="action" value="unlock">
            <label>Passphrase <input type="password" name="passphrase" required autofocus autocomplete="current-password"></label>
            <button class="primary">Unlock</button>
        </form>
    </div>
<?php else: ?>
    <header>
        <div class="brand"><small>Cloud Key Manager</small>Your API keys, without the Console</div>
        <div class="row">
            <?php if ($connected && in_array($view, ['keys', 'apis', 'edit'], true)): ?>
                <form method="get" class="row">
                    <input type="hidden" name="view" value="<?= h($view === 'edit' ? 'keys' : $view) ?>">
                    <?php if ($projects !== []): ?>
                        <select name="project" data-autosubmit aria-label="Project">
                            <?php foreach ($projects as $p): ?>
                                <option value="<?= h($p['id']) ?>" <?= $p['id'] === $project ? 'selected' : '' ?>><?= h($p['name']) ?> (<?= h($p['id']) ?>)</option>
                            <?php endforeach; ?>
                        </select>
                    <?php else: ?>
                        <input name="project" placeholder="project-id" value="<?= h($project) ?>" aria-label="Project ID">
                        <button class="small">Open</button>
                    <?php endif; ?>
                </form>
            <?php endif; ?>
            <form method="post" class="inline"><?= km_csrf_field() ?><input type="hidden" name="action" value="lock"><button class="small">🔒 Lock</button></form>
        </div>
    </header>

    <nav class="tabs">
        <a href="?view=keys" class="<?= in_array($view, ['keys', 'edit'], true) ? 'on' : '' ?>">🔑 Google API keys</a>
        <a href="?view=apis" class="<?= $view === 'apis' ? 'on' : '' ?>">📊 APIs &amp; traffic</a>
        <a href="?view=vault" class="<?= $view === 'vault' ? 'on' : '' ?>">🗄️ Vault (<?= count($entries) ?>)</a>
        <a href="?view=connection" class="<?= $view === 'connection' ? 'on' : '' ?>">⚙️ Connection</a>
    </nav>

    <?php foreach ($flashes as $flash): ?><div class="flash <?= h($flash['type']) ?>"><?= h($flash['message']) ?></div><?php endforeach; ?>
    <?php foreach (array_unique($errors) as $error): ?><div class="flash error"><?= h($error) ?></div><?php endforeach; ?>

    <?php if ($needsService !== '' && $project !== ''): ?>
        <div class="flash info">
            <strong><?= h($needsService) ?></strong> is turned off for <strong><?= h($project) ?></strong>. This app needs it for this page.
            <form method="post" class="inline"><?= km_csrf_field() ?><input type="hidden" name="action" value="enable_service"><input type="hidden" name="back" value="<?= h($view) ?>"><input type="hidden" name="service" value="<?= h($needsService) ?>"> <button class="small primary">Turn it on</button></form>
        </div>
    <?php endif; ?>

    <?php if ($reveal !== null): ?>
        <div class="panel">
            <h2>🔑 <?= h($reveal['label'] ?: 'Key') ?></h2>
            <div class="secret"><input id="revealed" readonly value="<?= h($reveal['key_string']) ?>"><button type="button" data-copy="revealed">Copy</button></div>
            <p class="hint">Saved in your vault. Treat it like a password: don't paste it into chats, emails or public code.</p>
        </div>
    <?php endif; ?>

    <?php if (!$connected && in_array($view, ['keys', 'apis', 'edit'], true)): ?>
        <div class="panel">
            <h2>Connect your Google account first</h2>
            <p>The key manager talks to Google on your behalf. It takes about a minute on the <a href="?view=connection">Connection tab</a>. Meanwhile, you can already store keys in the <a href="?view=vault">Vault</a>.</p>
        </div>

    <?php elseif ($view === 'keys'): ?>
        <h1>API keys<?= $project !== '' ? ' in ' . h($project) : '' ?></h1>
        <div class="panel">
            <div class="row" style="justify-content: space-between">
                <h2 style="margin:0"><?= count($keys) ?> active key<?= count($keys) === 1 ? '' : 's' ?></h2>
                <input class="filter" type="search" placeholder="Filter keys" data-filter-table="keys-table">
            </div>
            <?php if ($keys === []): ?>
                <p class="empty">No API keys in this project yet. Create one below.</p>
            <?php else: ?>
                <div class="table-wrap"><table id="keys-table">
                    <thead><tr><th>Name</th><th>Where it works</th><th>What it can call</th><th>Created</th><th>Vault</th><th></th></tr></thead>
                    <tbody>
                    <?php foreach ($keys as $item):
                        $summary = GoogleCloudClient::describeRestrictions((array) ($item['restrictions'] ?? []), $services);
                        $stored = KeyVault::findByGoogleName($data, (string) $item['name']);
                        $unrestricted = empty($item['restrictions']); ?>
                        <tr>
                            <td><strong><?= h($item['displayName'] ?? '(no name)') ?></strong><small class="mono"><?= h(basename((string) $item['name'])) ?></small></td>
                            <td><?= h($summary['app']) ?></td>
                            <td><?= h($summary['apis']) ?><?php if ($unrestricted): ?><br><span class="badge warn">Unrestricted</span><?php endif; ?></td>
                            <td><?= h(km_relative_time((string) ($item['createTime'] ?? ''))) ?></td>
                            <td><?= $stored !== null && ($stored['key_string'] ?? '') !== '' ? '<span class="badge ok">Saved</span>' : '<span class="badge">—</span>' ?></td>
                            <td class="row">
                                <form method="post" class="inline"><?= km_csrf_field() ?><input type="hidden" name="action" value="reveal_key"><input type="hidden" name="key" value="<?= h($item['name']) ?>"><button class="small">Show key</button></form>
                                <a class="button small" href="?view=edit&amp;key=<?= h(rawurlencode((string) $item['name'])) ?>">Edit</a>
                                <form method="post" class="inline" data-confirm="Delete “<?= h($item['displayName'] ?? '') ?>”? Apps using it stop working immediately. You can restore it for 30 days."><?= km_csrf_field() ?><input type="hidden" name="action" value="delete_key"><input type="hidden" name="key" value="<?= h($item['name']) ?>"><button class="small danger">Delete</button></form>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table></div>
            <?php endif; ?>
        </div>

        <div class="panel">
            <h2>➕ Create a new key</h2>
            <form method="post">
                <?= km_csrf_field() ?><input type="hidden" name="action" value="create_key">
                <?php km_key_fields(['type' => 'none', 'lines' => '', 'apis' => []], $services, ''); ?>
                <label>Notes for yourself <span class="hint">(optional, stored only in your vault)</span><input name="notes" maxlength="2000" placeholder="e.g. used by my book-trailer uploader"></label>
                <button class="primary">Create key</button>
            </form>
        </div>

        <?php if ($deletedKeys !== []): ?>
            <div class="panel">
                <details>
                    <summary>🗑️ Recently deleted (<?= count($deletedKeys) ?>) — restorable for 30 days</summary>
                    <div class="table-wrap"><table>
                        <thead><tr><th>Name</th><th>Deleted</th><th></th></tr></thead>
                        <tbody>
                        <?php foreach ($deletedKeys as $item): ?>
                            <tr>
                                <td><?= h($item['displayName'] ?? '(no name)') ?></td>
                                <td><?= h(km_relative_time((string) $item['deleteTime'])) ?></td>
                                <td><form method="post" class="inline"><?= km_csrf_field() ?><input type="hidden" name="action" value="restore_key"><input type="hidden" name="key" value="<?= h($item['name']) ?>"><button class="small">Restore</button></form></td>
                            </tr>
                        <?php endforeach; ?>
                        </tbody>
                    </table></div>
                </details>
            </div>
        <?php endif; ?>

    <?php elseif ($view === 'edit'): ?>
        <h1>Edit key</h1>
        <p><a href="?view=keys">← Back to all keys</a></p>
        <?php if ($editKey !== null): ?>
            <div class="panel">
                <form method="post">
                    <?= km_csrf_field() ?>
                    <input type="hidden" name="action" value="update_key"><input type="hidden" name="back" value="edit">
                    <input type="hidden" name="key" value="<?= h($editKey['name']) ?>">
                    <input type="hidden" name="etag" value="<?= h($editKey['etag'] ?? '') ?>">
                    <?php km_key_fields(GoogleCloudClient::restrictionsToForm((array) ($editKey['restrictions'] ?? [])), $services, (string) ($editKey['displayName'] ?? '')); ?>
                    <p class="hint">The key string itself never changes when you edit. To get a brand-new string, create a new key, switch your app to it, then delete this one.</p>
                    <button class="primary">Save changes</button>
                </form>
            </div>
        <?php endif; ?>

    <?php elseif ($view === 'apis'): ?>
        <h1>APIs &amp; traffic</h1>
        <div class="panel">
            <div class="row" style="justify-content: space-between">
                <form method="get" class="row">
                    <input type="hidden" name="view" value="apis">
                    <select name="window" data-autosubmit aria-label="Time window">
                        <?php foreach ($windows as $seconds => $label): ?><option value="<?= $seconds ?>" <?= $seconds === $window ? 'selected' : '' ?>><?= h($label) ?></option><?php endforeach; ?>
                    </select>
                </form>
                <input class="filter" type="search" placeholder="Filter" data-filter-table="apis-table">
            </div>
            <?php $rows = $services; foreach (array_keys((array) $metrics) as $svc) { $rows[$svc] ??= $svc; } ?>
            <?php if ($rows === []): ?>
                <p class="empty">No enabled APIs found for this project.</p>
            <?php else: ?>
                <div class="table-wrap"><table id="apis-table">
                    <thead><tr><th>Name</th><th class="num">Requests</th><th class="num">Errors (%)</th><th class="num">Latency, median (ms)</th><th class="num">Latency, 95% (ms)</th></tr></thead>
                    <tbody>
                    <?php foreach ($rows as $svc => $title): $m = $metrics[$svc] ?? null; ?>
                        <tr>
                            <td><?= h($title) ?><small class="mono"><?= h($svc) ?></small></td>
                            <td class="num"><?= $m !== null && $m['requests'] > 0 ? km_number((float) $m['requests']) : '—' ?></td>
                            <td class="num"><?= km_number($m['error_pct'] ?? null) ?></td>
                            <td class="num"><?= km_number($m['p50_ms'] ?? null) ?></td>
                            <td class="num"><?= km_number($m['p95_ms'] ?? null) ?></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table></div>
                <p class="hint">“—” means no traffic in this window. Figures come from Cloud Monitoring and can lag by a few minutes.</p>
            <?php endif; ?>
        </div>
        <div class="panel">
            <h2>Turn on another API</h2>
            <form method="post" class="row">
                <?= km_csrf_field() ?><input type="hidden" name="action" value="enable_service"><input type="hidden" name="back" value="apis">
                <input name="service" list="common-services" placeholder="e.g. youtube.googleapis.com" required style="max-width:380px">
                <datalist id="common-services">
                    <?php foreach ([
                        'aiplatform.googleapis.com' => 'Vertex AI / Agent Platform API',
                        'generativelanguage.googleapis.com' => 'Gemini API',
                        'cloudaicompanion.googleapis.com' => 'Gemini for Google Cloud API',
                        'geminicloudassist.googleapis.com' => 'Gemini Cloud Assist API',
                        'youtube.googleapis.com' => 'YouTube Data API v3',
                        'texttospeech.googleapis.com' => 'Cloud Text-to-Speech API',
                        'speech.googleapis.com' => 'Cloud Speech-to-Text API',
                        'storage.googleapis.com' => 'Cloud Storage',
                        'monitoring.googleapis.com' => 'Cloud Monitoring API',
                        'cloudasset.googleapis.com' => 'Cloud Asset API',
                        'recommender.googleapis.com' => 'Recommender API',
                        'apikeys.googleapis.com' => 'API Keys API',
                        'translate.googleapis.com' => 'Cloud Translation API',
                        'vision.googleapis.com' => 'Cloud Vision API',
                        'maps-backend.googleapis.com' => 'Maps JavaScript API',
                        'books.googleapis.com' => 'Books API',
                        'drive.googleapis.com' => 'Google Drive API',
                        'sheets.googleapis.com' => 'Google Sheets API',
                    ] as $svc => $title): ?>
                        <option value="<?= h($svc) ?>"><?= h($title) ?></option>
                    <?php endforeach; ?>
                </datalist>
                <button class="primary">Turn on</button>
            </form>
        </div>

    <?php elseif ($view === 'vault'): ?>
        <h1>Vault</h1>
        <p>Every key you've stored — Google keys saved automatically when you create or show them, plus any key from any other cloud service you add yourself.</p>
        <div class="panel">
            <div class="row" style="justify-content: space-between">
                <h2 style="margin:0"><?= count($entries) ?> stored key<?= count($entries) === 1 ? '' : 's' ?></h2>
                <input class="filter" type="search" placeholder="Filter" data-filter-table="vault-table">
            </div>
            <?php if ($entries === []): ?>
                <p class="empty">Nothing stored yet.</p>
            <?php else: ?>
                <div class="table-wrap"><table id="vault-table">
                    <thead><tr><th>Name</th><th>Service</th><th>Project / account</th><th>Key</th><th>Updated</th><th></th></tr></thead>
                    <tbody>
                    <?php foreach ($entries as $entry): ?>
                        <tr>
                            <td><strong><?= h($entry['label']) ?></strong><?php if (($entry['notes'] ?? '') !== ''): ?><small><?= h($entry['notes']) ?></small><?php endif; ?><?php if (($entry['status'] ?? '') !== ''): ?><br><span class="badge warn"><?= h($entry['status']) ?></span><?php endif; ?></td>
                            <td><?= h($entry['provider']) ?></td>
                            <td><?= h($entry['project']) ?></td>
                            <td class="mono"><?= h(KeyVault::mask((string) $entry['key_string'])) ?></td>
                            <td><?= h(km_relative_time((string) $entry['updated_at'])) ?></td>
                            <td class="row">
                                <a class="button small" href="?view=vault&amp;reveal=<?= h($entry['id']) ?>">Show</a>
                                <a class="button small" href="?view=vault&amp;edit=<?= h($entry['id']) ?>#entry-form">Edit</a>
                                <form method="post" class="inline" data-confirm="Remove “<?= h($entry['label']) ?>” from your vault? This does not delete the key on Google or anywhere else."><?= km_csrf_field() ?><input type="hidden" name="action" value="vault_delete"><input type="hidden" name="back" value="vault"><input type="hidden" name="id" value="<?= h($entry['id']) ?>"><button class="small danger">Remove</button></form>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table></div>
            <?php endif; ?>
        </div>
        <div class="panel" id="entry-form">
            <h2><?= $editEntry !== null ? '✏️ Edit “' . h($editEntry['label']) . '”' : '➕ Store a key' ?></h2>
            <form method="post">
                <?= km_csrf_field() ?><input type="hidden" name="action" value="vault_save"><input type="hidden" name="back" value="vault"><input type="hidden" name="id" value="<?= h($editEntry['id'] ?? '') ?>">
                <div class="grid2">
                    <label>Name <input name="label" required maxlength="120" value="<?= h($editEntry['label'] ?? '') ?>" placeholder="e.g. Gemini — book writer"></label>
                    <label>Service <input name="provider" maxlength="60" list="providers" value="<?= h($editEntry['provider'] ?? '') ?>" placeholder="Google Cloud, Anthropic, AWS…"></label>
                </div>
                <datalist id="providers"><?php foreach (['Google Cloud', 'Anthropic', 'OpenAI', 'AWS', 'Azure', 'ElevenLabs', 'Stripe', 'GitHub', 'Cloudflare', 'Other'] as $provider): ?><option value="<?= h($provider) ?>"><?php endforeach; ?></datalist>
                <label>Project or account <span class="hint">(optional)</span><input name="project" maxlength="120" value="<?= h($editEntry['project'] ?? '') ?>"></label>
                <label>Key <?= $editEntry !== null ? '<span class="hint">— leave empty to keep the current one</span>' : '' ?><input name="key_string" type="password" autocomplete="off" <?= $editEntry === null ? 'required' : '' ?>></label>
                <label>Notes <span class="hint">(optional)</span><textarea name="notes" rows="2" maxlength="2000"><?= h($editEntry['notes'] ?? '') ?></textarea></label>
                <button class="primary"><?= $editEntry !== null ? 'Save changes' : 'Store key' ?></button>
                <?php if ($editEntry !== null): ?><a class="button" href="?view=vault">Cancel</a><?php endif; ?>
            </form>
        </div>

    <?php elseif ($view === 'connection'): ?>
        <?php $mode = (string) ($connection['mode'] ?? 'gcloud'); ?>
        <h1>Connection</h1>
        <p>How the key manager signs in to Google. Your choice is stored encrypted in the vault. Managing keys needs a real Google sign-in — an API key alone cannot create or change other keys.</p>
        <div class="panel">
            <form method="post" enctype="multipart/form-data">
                <?= km_csrf_field() ?><input type="hidden" name="action" value="save_connection"><input type="hidden" name="back" value="connection">
                <div class="choice"><label class="check"><input type="radio" name="mode" value="gcloud" <?= $mode === 'gcloud' ? 'checked' : '' ?>> <strong>Use my Google sign-in (recommended)</strong></label>
                    <p>Install the <a href="https://cloud.google.com/sdk/docs/install" rel="noreferrer" target="_blank">Google Cloud CLI</a>, then run <code>gcloud auth login</code> once in a terminal and pick your Google Developer account. The app asks gcloud for a fresh token whenever it needs one, and can do anything your account is allowed to do.</p>
                    <label>Path to gcloud <span class="hint">(only if it isn't found automatically)</span><input name="gcloud_path" value="<?= h($connection['gcloud_path'] ?? '') ?>" placeholder="gcloud"></label>
                </div>
                <div class="choice"><label class="check"><input type="radio" name="mode" value="service_account" <?= $mode === 'service_account' ? 'checked' : '' ?>> <strong>Use a service account key file</strong></label>
                    <p>For unattended use. The account needs the “API Keys Admin” and “Service Usage Admin” roles (plus “Monitoring Viewer” for traffic).
                        <?= ($connection['service_account_json'] ?? '') !== '' ? '<span class="badge ok">A key file is saved</span>' : '' ?></p>
                    <input type="file" name="service_account_file" accept=".json,application/json">
                    <textarea name="service_account_json" rows="3" placeholder="…or paste the JSON here"></textarea>
                </div>
                <div class="choice"><label class="check"><input type="radio" name="mode" value="token" <?= $mode === 'token' ? 'checked' : '' ?>> <strong>Paste an access token</strong></label>
                    <p>Run <code>gcloud auth print-access-token</code> and paste the result. Tokens expire after about an hour.
                        <?= ($connection['token'] ?? '') !== '' ? '<span class="badge ok">A token is saved</span>' : '' ?></p>
                    <input name="token" type="password" autocomplete="off" placeholder="ya29.…">
                </div>
                <div class="grid2">
                    <label>Default project <span class="hint">(optional)</span><input name="default_project" value="<?= h($connection['default_project'] ?? '') ?>" placeholder="my-project-id"></label>
                    <label class="check" style="margin-top:34px"><input type="checkbox" name="quota_header" <?= ($connection['quota_header'] ?? true) ? 'checked' : '' ?>> <span>Bill API quota to the selected project <small>Needed by some Google APIs when you sign in as yourself. Untick if you see "serviceusage.services.use" errors.</small></span></label>
                </div>
                <button class="primary">Save &amp; test connection</button>
            </form>
        </div>
        <div class="panel">
            <h2>Change vault passphrase</h2>
            <form method="post">
                <?= km_csrf_field() ?><input type="hidden" name="action" value="change_passphrase"><input type="hidden" name="back" value="connection">
                <div class="grid2">
                    <label>Current passphrase <input type="password" name="current" required autocomplete="current-password"></label>
                    <label>New passphrase <input type="password" name="passphrase" minlength="<?= KeyVault::MIN_PASSPHRASE ?>" required autocomplete="new-password"></label>
                    <label>New passphrase again <input type="password" name="confirm" required autocomplete="new-password"></label>
                </div>
                <button>Change passphrase</button>
            </form>
            <p class="hint">Vault file: <span class="mono"><?= h($vault->path()) ?></span>. Back it up — without it (and your passphrase) the stored keys cannot be recovered, though Google keys can always be shown again from the Keys tab.</p>
        </div>
    <?php endif; ?>
<?php endif; ?>
</main>
<script src="app.js"></script>
</body>
</html>
