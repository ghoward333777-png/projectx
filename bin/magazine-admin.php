<?php

declare(strict_types=1);

/**
 * Set a magazine member's role from the command line.
 *
 *   php bin/magazine-admin.php <email> <reader|editor|admin>
 *   php bin/magazine-admin.php --list
 *
 * Use this to promote the first administrator after registering on the site.
 */

// The app normally sits beside this folder as magazine/; on a host where its contents were
// uploaded straight into the web root, public_html/ is found instead (or set MAGAZINE_APP_DIR).
$app = null;
foreach (array_filter([getenv('MAGAZINE_APP_DIR') ?: null, __DIR__ . '/../magazine', __DIR__ . '/../public_html', __DIR__ . '/../htdocs']) as $candidate) {
    if (is_file($candidate . '/MagazineStore.php')) {
        $app = $candidate;
        break;
    }
}
if ($app === null) {
    fwrite(STDERR, "Could not find the magazine files. Set MAGAZINE_APP_DIR to the folder that holds MagazineStore.php.\n");
    exit(2);
}
require_once $app . '/MagazineStore.php';

$dir = getenv('MAGAZINE_DATA_DIR') ?: $app . '/data';
$store = new MagazineStore($dir);

if (($argv[1] ?? '') === '--list') {
    foreach ($store->users() as $u) {
        fwrite(STDOUT, sprintf("%-8s %s <%s>\n", $u['role'], $u['name'], $u['email']));
    }
    exit(0);
}

$email = (string) ($argv[1] ?? '');
$role = (string) ($argv[2] ?? '');
if ($email === '' || !in_array($role, MagazineStore::ROLES, true)) {
    fwrite(STDERR, "Usage: php bin/magazine-admin.php <email> <reader|editor|admin>\n       php bin/magazine-admin.php --list\n");
    exit(2);
}
$user = $store->findUserByEmail($email);
if ($user === null) {
    fwrite(STDERR, "No member has registered with {$email} yet. Register on the site first.\n");
    exit(1);
}
$store->updateUser($user['id'], ['role' => $role]);
fwrite(STDOUT, "{$user['name']} <{$user['email']}> is now: {$role}\n");
