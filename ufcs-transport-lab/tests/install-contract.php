<?php

declare(strict_types=1);

// The install check must report this machine as ready, explain every gap with
// a fix, and the start/install scripts must be present and executable.
require __DIR__ . '/_harness.php';

$root = dirname(__DIR__);
exec(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($root . '/bin/doctor.php') . ' --json', $out, $rc);
$report = json_decode(implode("\n", $out), true);
check(is_array($report), 'doctor --json prints JSON');
check($rc === 0 && $report['ready'] === true, 'doctor reports this machine ready (exit 0)');
$names = array_column($report['checks'], 'name');
foreach (['PHP 8.1+', 'PHP sodium', 'PHP zlib', 'ffmpeg', 'zstd', 'Writable folder'] as $need) {
    check(in_array($need, $names, true), "doctor checks $need");
}
foreach ($report['checks'] as $c) {
    check($c['ok'] || $c['fix'] !== '', 'every missing item comes with a fix: ' . $c['name']);
}

// Without ffmpeg the lab is still ready; ffmpeg is reported as optional with a fix.
putenv('UFCS_LAB_FFMPEG=off');
$out = [];
exec(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($root . '/bin/doctor.php') . ' --json', $out, $rc);
putenv('UFCS_LAB_FFMPEG');
$off = json_decode(implode("\n", $out), true);
$ff = array_values(array_filter($off['checks'], fn ($c) => $c['name'] === 'ffmpeg'))[0];
check($rc === 0 && $off['ready'] === true, 'lab is ready without ffmpeg');
check(!$ff['ok'] && !$ff['required'] && $ff['fix'] !== '', 'missing ffmpeg is optional and has a fix');

foreach (['START_LAB.bat', 'CHECK_LAB.bat', 'READ_ME_FIRST.txt', 'qb_lab.py', 'Dockerfile', 'docker-compose.yml'] as $file) {
    check(is_file($root . '/' . $file), "$file is present");
}
foreach (['START_LAB.bat', 'CHECK_LAB.bat', 'READ_ME_FIRST.txt'] as $file) {
    $text = (string) file_get_contents($root . '/' . $file);
    check(substr_count($text, "\r\n") === substr_count($text, "\n"), "$file has Windows (CRLF) line endings");
}
check(str_contains((string) file_get_contents($root . '/START_LAB.bat'), 'qb_lab.py'), 'START_LAB.bat runs the Python launcher');
if (PHP_OS_FAMILY !== 'Windows') {
    foreach (['install.sh', 'start.sh'] as $script) {
        check(is_executable($root . '/' . $script), "$script is executable");
        check(str_starts_with((string) file_get_contents($root . '/' . $script), '#!/usr/bin/env sh'), "$script is POSIX sh");
    }
    exec('sh ' . escapeshellarg($root . '/install.sh') . ' --dry-run 2>&1', $dry, $rc);
    check($rc === 0 && str_contains(implode("\n", $dry), 'Dry run: nothing was installed'), 'install.sh --dry-run runs without installing');
}

done('install contract');
