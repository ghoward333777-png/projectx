<?php

declare(strict_types=1);

/**
 * Install check: says what the lab needs, what this machine has, and the
 * exact command that fixes each gap on this operating system.
 *
 *   php bin/doctor.php            human-readable checklist
 *   php bin/doctor.php --json     machine-readable (used by install.sh)
 *
 * Exit code 0 = ready to run (optional extras may still be missing),
 * 1 = something required is missing.
 */
if (PHP_VERSION_ID < 80100) {
    fwrite(STDERR, 'PHP ' . PHP_VERSION . " is too old: the lab needs PHP 8.1 or newer.\n");
    exit(1);
}
require __DIR__ . '/../src/bootstrap.php';

$json = in_array('--json', $argv, true);
$pm = doctor_package_manager();

$which = static function (string $tool): string {
    $cmd = PHP_OS_FAMILY === 'Windows' ? 'where ' . $tool . ' 2>NUL' : 'command -v ' . escapeshellarg($tool) . ' 2>/dev/null';
    $out = trim((string) @shell_exec($cmd));
    return $out === '' ? '' : strtok($out, "\r\n");
};

$checks = [];
$add = static function (string $name, bool $ok, bool $required, string $what, string $have, string $fix) use (&$checks): void {
    $checks[] = compact('name', 'ok', 'required', 'what', 'have', 'fix');
};

$add('PHP 8.1+', true, true, 'runs the lab', PHP_VERSION, '');
foreach (['sodium' => 'signs and verifies frames', 'zlib' => 'GZIP and UFCS dictionary compression', 'json' => 'frame metadata', 'mbstring' => 'text handling'] as $ext => $what) {
    $add('PHP ' . $ext, extension_loaded($ext), true, $what, extension_loaded($ext) ? 'loaded' : 'missing', doctor_fix('php-' . $ext, $pm));
}
$webp = function_exists('imagewebp');
$add('PHP gd with WebP', $webp, false, 'image compression and colorization', $webp ? 'loaded' : (extension_loaded('gd') ? 'gd without WebP' : 'missing'), doctor_fix('php-gd', $pm));
$add('PHP pcntl + OPcache', function_exists('pcntl_exec') && extension_loaded('Zend OPcache'), false, 'about 2x faster colorization (JIT)', function_exists('pcntl_exec') ? 'loaded' : 'missing', doctor_fix('php-opcache', $pm));

$ffmpeg = MediaCodec::ffmpeg();
$add('ffmpeg', $ffmpeg !== '', false, 'video and audio codecs, HLS, DASH, RTMP repackaging, video reports', $ffmpeg ?: 'not found', doctor_fix('ffmpeg', $pm));
if ($ffmpeg !== '') {
    $missing = array_keys(array_filter(MediaCodec::codecMatrix(), fn ($r) => !$r['available']));
    $add('ffmpeg codecs', $missing === [], false, 'H.264, H.265, AV1, Opus, AAC', $missing === [] ? 'all present' : 'missing ' . implode(', ', $missing), 'install a full ffmpeg build (the distribution package usually has all of them)');
}
$zstd = $which('zstd');
$add('zstd', $zstd !== '', false, 'Zstd compression (falls back to GZIP)', $zstd ?: 'not found', doctor_fix('zstd', $pm));
$go = $which('go');
$add('Go', $go !== '', false, 'only for the Go reference sender/receiver', $go ?: 'not found', doctor_fix('golang', $pm));
$cargo = $which('cargo');
$add('Rust (cargo)', $cargo !== '', false, 'only for the Rust reference sender/receiver', $cargo ?: 'not found', 'https://rustup.rs');

$root = dirname(__DIR__);
$writable = is_writable($root);
$add('Writable folder', $writable, true, 'reports and received files are saved here', $writable ? $root : 'read-only: ' . $root, 'move the lab to a folder you own');

$ready = !array_filter($checks, fn ($c) => $c['required'] && !$c['ok']);
if ($json) {
    echo json_encode(['ready' => $ready, 'package_manager' => $pm, 'checks' => $checks], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
    exit($ready ? 0 : 1);
}

echo "QueryBook UFCS-FQL Lab: install check\n\n";
foreach ($checks as $c) {
    $mark = $c['ok'] ? '[ok]  ' : ($c['required'] ? '[NEED]' : '[opt] ');
    printf("%s %-20s %s\n", $mark, $c['name'], $c['ok'] ? $c['have'] : $c['what'] . ' — ' . $c['have']);
    if (!$c['ok'] && $c['fix'] !== '') {
        printf("       %-20s fix: %s\n", '', $c['fix']);
    }
}
echo "\n", $ready
    ? "Ready. Start the dashboard with ./start.sh (Windows: start.bat), then open http://127.0.0.1:8091\n"
    : "Not ready: install the [NEED] items above, or run ./install.sh to do it for you.\n";
if ($ready && array_filter($checks, fn ($c) => !$c['ok'])) {
    echo "[opt] items are extras: the lab runs without them and says which features they unlock.\n";
}
exit($ready ? 0 : 1);

function doctor_package_manager(): string
{
    if (PHP_OS_FAMILY === 'Windows') {
        return 'windows';
    }
    if (PHP_OS_FAMILY === 'Darwin') {
        return 'brew';
    }
    foreach (['apt-get', 'dnf', 'yum', 'apk', 'pacman', 'zypper'] as $pm) {
        if (trim((string) @shell_exec('command -v ' . $pm . ' 2>/dev/null')) !== '') {
            return $pm;
        }
    }
    return 'unknown';
}

/** The install command for one need on this package manager. */
function doctor_fix(string $need, string $pm): string
{
    $v = PHP_MAJOR_VERSION . PHP_MINOR_VERSION;
    $names = [
        'apt-get' => ['php-sodium' => 'php-cli', 'php-zlib' => 'php-cli', 'php-json' => 'php-cli', 'php-mbstring' => 'php-mbstring', 'php-gd' => 'php-gd', 'php-opcache' => 'php-cli', 'ffmpeg' => 'ffmpeg', 'zstd' => 'zstd', 'golang' => 'golang-go'],
        'dnf' => ['php-sodium' => 'php-sodium', 'php-zlib' => 'php-cli', 'php-json' => 'php-cli', 'php-mbstring' => 'php-mbstring', 'php-gd' => 'php-gd', 'php-opcache' => 'php-opcache php-process', 'ffmpeg' => 'ffmpeg (enable RPM Fusion first)', 'zstd' => 'zstd', 'golang' => 'golang'],
        'apk' => ['php-sodium' => "php{$v}-sodium", 'php-zlib' => "php{$v}-zlib", 'php-json' => "php{$v}-json", 'php-mbstring' => "php{$v}-mbstring", 'php-gd' => "php{$v}-gd", 'php-opcache' => "php{$v}-opcache php{$v}-pcntl", 'ffmpeg' => 'ffmpeg', 'zstd' => 'zstd', 'golang' => 'go'],
        'pacman' => ['php-sodium' => 'php-sodium', 'php-zlib' => 'php', 'php-json' => 'php', 'php-mbstring' => 'php', 'php-gd' => 'php-gd', 'php-opcache' => 'php', 'ffmpeg' => 'ffmpeg', 'zstd' => 'zstd', 'golang' => 'go'],
        'brew' => ['php-sodium' => 'php', 'php-zlib' => 'php', 'php-json' => 'php', 'php-mbstring' => 'php', 'php-gd' => 'php', 'php-opcache' => 'php', 'ffmpeg' => 'ffmpeg', 'zstd' => 'zstd', 'golang' => 'go'],
    ];
    $prefix = ['apt-get' => 'sudo apt-get install -y ', 'dnf' => 'sudo dnf install -y ', 'yum' => 'sudo yum install -y ', 'apk' => 'sudo apk add ', 'pacman' => 'sudo pacman -S --needed ', 'zypper' => 'sudo zypper install ', 'brew' => 'brew install '];
    if ($pm === 'yum') {
        $names['yum'] = $names['dnf'];
    }
    if ($pm === 'windows') {
        return match ($need) {
            'ffmpeg' => 'winget install Gyan.FFmpeg   (then reopen the terminal)',
            'zstd' => 'download zstd from https://github.com/facebook/zstd/releases and add it to PATH',
            'golang' => 'winget install GoLang.Go',
            default => 'enable "extension=' . substr($need, 4) . '" in php.ini (it ships with PHP for Windows)',
        };
    }
    if (!isset($names[$pm], $prefix[$pm])) {
        return 'install ' . $need . ' with your package manager, or use Docker: docker compose up';
    }
    return $prefix[$pm] . ($names[$pm][$need] ?? $need);
}
