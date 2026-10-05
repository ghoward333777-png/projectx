<?php

declare(strict_types=1);

// Runs every contract test in this directory; exits non-zero on the first failure.
$failed = 0;
foreach (glob(__DIR__ . '/*-contract.php') as $test) {
    passthru(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($test), $rc);
    $failed += $rc !== 0 ? 1 : 0;
}
echo $failed === 0 ? "\nAll lab tests passed.\n" : "\n$failed test file(s) failed.\n";
exit($failed === 0 ? 0 : 1);
