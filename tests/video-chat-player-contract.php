<?php
declare(strict_types=1);

// Contract test for the Watch Room player, step 1: the source resolver refuses anything
// that is not an https media URL or a media/ file, and the page shell renders the stage
// with the resolved source. Runs with plain `php tests/video-chat-player-contract.php`.

require __DIR__ . '/../video-chat-player/lib/Source.php';

$failures = 0;
$checks = 0;
$assert = static function (bool $condition, string $label) use (&$failures, &$checks): void {
    $checks++;
    if (!$condition) {
        $failures++;
        fwrite(STDERR, "FAIL  {$label}\n");
    }
};

$mediaDir = sys_get_temp_dir() . '/watchroom-test-media-' . getmypid();
mkdir($mediaDir);
file_put_contents($mediaDir . '/clip one.mp4', 'x');
file_put_contents($mediaDir . '/reel.webm', 'x');
file_put_contents($mediaDir . '/notes.txt', 'x');

// --- media/ files ---
$r = Source::resolve('media/reel.webm', $mediaDir);
$assert($r !== null && $r['kind'] === 'file' && $r['src'] === 'media/reel.webm' && $r['label'] === 'reel.webm', 'media file resolves');
$assert(Source::resolve('media/clip one.mp4', $mediaDir)['kind'] === 'file', 'media file with a space resolves');
$assert(Source::resolve('media/missing.mp4', $mediaDir) === null, 'missing media file is refused');
$assert(Source::resolve('media/notes.txt', $mediaDir) === null, 'non-video media file is refused');
$assert(Source::resolve('media/../lib/Source.php', $mediaDir) === null, 'path traversal is refused');
$assert(Source::resolve('media/..%2Freel.webm', $mediaDir) === null, 'encoded traversal is refused');
$assert(Source::library($mediaDir) === ['clip one.mp4', 'reel.webm'], 'library lists only video files, sorted');
$assert(Source::library($mediaDir . '/nope') === [], 'missing media dir yields an empty library');

// --- URLs ---
$assert(Source::resolve('https://example.com/a/b/film.mp4', $mediaDir)['kind'] === 'url', 'https mp4 resolves');
$assert(Source::resolve('https://example.com/film.MP4?token=1#t=2', $mediaDir)['label'] === 'film.MP4', 'query and fragment are tolerated; label is the file name');
$assert(Source::resolve('https://example.com/my%20film.webm', $mediaDir)['label'] === 'my film.webm', 'label is decoded');
$assert(Source::resolve('http://example.com/film.mp4', $mediaDir) === null, 'plain http is refused');
$assert(Source::resolve('https://example.com/watch?v=abc', $mediaDir) === null, 'non-media URL is refused (YouTube arrives in step 4)');
$assert(Source::resolve('javascript:alert(1)', $mediaDir) === null, 'javascript: is refused');
$assert(Source::resolve('file:///etc/passwd', $mediaDir) === null, 'file: is refused');
$assert(Source::resolve('   ', $mediaDir) === null, 'blank is refused');
$assert(Source::resolve('https:///film.mp4', $mediaDir) === null, 'https without a host is refused');
$assert(Source::defaultSource()['kind'] === 'url' && str_starts_with(Source::defaultSource()['src'], 'https://'), 'default source is an https URL');

// --- page shell ---
$render = static function (array $get): string {
    $_GET = $get;
    ob_start();
    include __DIR__ . '/../video-chat-player/index.php';
    return (string) ob_get_clean();
};
$html = $render([]);
$assert(str_contains($html, 'id="stage"'), 'page renders the stage');
$assert(str_contains($html, 'data-src="' . htmlspecialchars(Source::DEFAULT_URL, ENT_QUOTES, 'UTF-8') . '"'), 'default source is wired into the stage');
$assert(str_contains($html, 'id="stage-overlay"') && str_contains($html, 'id="stage-controls"'), 'overlay and control layers are present');
$assert(!str_contains($html, 'notice--warn'), 'no warning without a request');
$html = $render(['src' => '"><script>alert(1)</script>']);
$assert(!str_contains($html, '<script>alert'), 'hostile source is never echoed raw');
$assert(str_contains($html, 'notice--warn'), 'hostile source shows the warning');
$assert(str_contains($html, 'data-src="https://'), 'hostile source falls back to the default');
$assert(!str_contains($html, '<w:hyperlink'), 'sanity: no Word markup leaks into the player page');

array_map('unlink', glob($mediaDir . '/*') ?: []);
rmdir($mediaDir);

if ($failures > 0) {
    fwrite(STDERR, "video-chat-player contract: {$failures} of {$checks} checks failed\n");
    exit(1);
}
echo "video-chat-player contract: {$checks} checks passed\n";
