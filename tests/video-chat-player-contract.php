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
$assert($r !== null && $r['kind'] === 'file' && $r['src'] === 'media.php?f=reel.webm' && $r['label'] === 'reel.webm' && $r['name'] === 'reel.webm', 'media file resolves through the range-aware streamer');
$assert(Source::resolve('media/clip one.mp4', $mediaDir)['src'] === 'media.php?f=clip%20one.mp4', 'file names are URL-encoded in the streamer link');
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
$assert(Source::defaultSource($mediaDir)['kind'] === 'url' && str_starts_with(Source::defaultSource($mediaDir)['src'], 'https://'), 'without a bundled sample the default is the public https URL');
file_put_contents($mediaDir . '/' . Source::SAMPLE, 'x');
$assert(Source::defaultSource($mediaDir)['src'] === 'media.php?f=sample.mp4', 'the bundled sample.mp4 is the default when present');
unlink($mediaDir . '/' . Source::SAMPLE);

// --- byte ranges (media.php) ---
$assert(Source::parseRange('', 1000) === null, 'no Range header serves the whole file');
$assert(Source::parseRange('bytes=0-99', 1000) === [0, 99], 'closed range');
$assert(Source::parseRange('bytes=500-', 1000) === [500, 999], 'open-ended range');
$assert(Source::parseRange('bytes=-100', 1000) === [900, 999], 'suffix range');
$assert(Source::parseRange('bytes=0-5000', 1000) === [0, 999], 'end past the file is clamped');
$assert(Source::parseRange('bytes=1000-', 1000) === false, 'start at the file size is unsatisfiable');
$assert(Source::parseRange('bytes=9-3', 1000) === false, 'inverted range is unsatisfiable');
$assert(Source::parseRange('bytes=0-1,5-9', 1000) === null, 'multipart ranges fall back to the whole file');
$assert(Source::parseRange('items=0-1', 1000) === null, 'non-byte units are ignored');
$assert(Source::mimeType('a.webm') === 'video/webm' && Source::mimeType('a.MP4') === 'video/mp4' && Source::mimeType('a.m4v') === 'video/x-m4v', 'mime types');

// --- page shell ---
$render = static function (array $get): string {
    $_GET = $get;
    ob_start();
    include __DIR__ . '/../video-chat-player/index.php';
    return (string) ob_get_clean();
};
$realDefault = htmlspecialchars(Source::defaultSource(__DIR__ . '/../video-chat-player/media')['src'], ENT_QUOTES, 'UTF-8');
$html = $render([]);
$assert(str_contains($html, 'id="stage"'), 'page renders the stage');
$assert(str_contains($html, 'data-src="' . $realDefault . '"'), 'default source is wired into the stage');
$assert(str_contains($html, 'id="ctl-seek"') && str_contains($html, 'id="ctl-volume"') && str_contains($html, 'id="ctl-chat"'), 'control bar widgets are present');
$assert(str_contains($html, 'data-idle-timeout="3000"'), 'idle timeout defaults to 3000 ms');
$assert(str_contains($render(['idle' => '99']), 'data-idle-timeout="1500"') && str_contains($render(['idle' => '50000']), 'data-idle-timeout="10000"'), 'idle timeout is clamped to 1500–10000');
$assert(str_contains($html, 'id="stage-overlay"') && str_contains($html, 'id="stage-controls"'), 'overlay and control layers are present');
$assert(!str_contains($html, 'notice--warn'), 'no warning without a request');
$html = $render(['src' => '"><script>alert(1)</script>']);
$assert(!str_contains($html, '<script>alert'), 'hostile source is never echoed raw');
$assert(str_contains($html, 'notice--warn'), 'hostile source shows the warning');
$assert(str_contains($html, 'data-src="' . $realDefault . '"'), 'hostile source falls back to the default');
$assert(!str_contains($html, '<w:hyperlink'), 'sanity: no Word markup leaks into the player page');

array_map('unlink', glob($mediaDir . '/*') ?: []);
rmdir($mediaDir);

if ($failures > 0) {
    fwrite(STDERR, "video-chat-player contract: {$failures} of {$checks} checks failed\n");
    exit(1);
}
echo "video-chat-player contract: {$checks} checks passed\n";
