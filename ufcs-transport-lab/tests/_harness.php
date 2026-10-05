<?php

declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

$GLOBALS['__checks'] = 0;

function check(bool $cond, string $what): void
{
    $GLOBALS['__checks']++;
    if (!$cond) {
        fwrite(STDERR, "FAIL: $what\n");
        exit(1);
    }
}

function throws(callable $fn, string $what): void
{
    try {
        $fn();
    } catch (Throwable) {
        check(true, $what);
        return;
    }
    check(false, $what . ' (expected an exception)');
}

function done(string $name): void
{
    echo "OK  $name — {$GLOBALS['__checks']} checks\n";
}
