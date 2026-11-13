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

require_once __DIR__ . '/../magazine/MagazineStore.php';

$dir = getenv('MAGAZINE_DATA_DIR') ?: __DIR__ . '/../magazine/data';
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
