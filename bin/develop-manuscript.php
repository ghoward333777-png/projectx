#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Develop a book's first draft into finished prose — in one run.
 *
 * Pass 1 (engine)  — outline + per-chapter draft directions.
 * Pass 2 (writer)  — an AI writer follows each chapter's directions.
 * Pass 3 (editor)  — an AI editor sweeps each chapter for repetition,
 *                    transitions, and format compliance.
 * Assembly         — the developed chapters flow back through the KDP
 *                    pipeline: figures, tables, contents page, Word + EPUB.
 *
 * Providers: anthropic (ANTHROPIC_API_KEY), google (GOOGLE_AI_API_KEY),
 * openai (OPENAI_API_KEY).
 *
 * Usage:
 *   php bin/develop-manuscript.php --topic "Why men don't approach women" \
 *       --author "Garry S. Howard" --style journalistic --length 250 \
 *       --provider anthropic --out build/approach-book
 *   Optional: --reader "..."  --outline outline.txt (your own TOC, one
 *   chapter per line, `Title | purpose | detail`)  --model <id>
 *   --no-edit (skip pass 3)  --limit N (develop only N chapters this run)
 *
 * Resumable: chapters whose output file already exists are skipped, so an
 * interrupted run continues where it stopped. Without an API key the run
 * writes the full drafting kit (every prompt) and stops, so nothing is lost.
 */

require_once __DIR__ . '/../AmazonBookWriter.php';
require_once __DIR__ . '/../ManuscriptDeveloper.php';
require_once __DIR__ . '/../WordManuscriptExporter.php';
require_once __DIR__ . '/../EpubExporter.php';
require_once __DIR__ . '/../BookProjectStore.php';

function argValue(array $argv, string $name, ?string $default = null): ?string
{
    foreach ($argv as $i => $arg) {
        if ($arg === '--' . $name) {
            return $argv[$i + 1] ?? $default;
        }
        if (str_starts_with($arg, '--' . $name . '=')) {
            return substr($arg, strlen($name) + 3);
        }
    }
    return $default;
}

function hasFlag(array $argv, string $name): bool
{
    return in_array('--' . $name, $argv, true);
}

function fail(string $message): never
{
    fwrite(STDERR, 'ERROR: ' . $message . "\n");
    exit(1);
}

/** Dependency-free HTTPS POST with retries; works with or without ext-curl. */
function httpPostJson(string $url, array $headers, array $body): array
{
    $payload = json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($payload === false) {
        fail('Could not encode the request body.');
    }
    $headerLines = [];
    foreach ($headers as $name => $value) {
        $headerLines[] = $name . ': ' . $value;
    }
    $attempts = 0;
    while (true) {
        $attempts++;
        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_POST => true,
                CURLOPT_POSTFIELDS => $payload,
                CURLOPT_HTTPHEADER => $headerLines,
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_TIMEOUT => 600,
            ]);
            $raw = curl_exec($ch);
            $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            $error = curl_error($ch);
            curl_close($ch);
        } else {
            $context = stream_context_create(['http' => [
                'method' => 'POST',
                'header' => implode("\r\n", $headerLines),
                'content' => $payload,
                'timeout' => 600,
                'ignore_errors' => true,
            ]]);
            $raw = @file_get_contents($url, false, $context);
            $status = 0;
            foreach ($http_response_header ?? [] as $line) {
                if (preg_match('#^HTTP/\S+\s+(\d{3})#', $line, $m) === 1) {
                    $status = (int) $m[1];
                }
            }
            $error = $raw === false ? 'connection failed' : '';
        }
        if ($raw !== false && $status >= 200 && $status < 300) {
            $decoded = json_decode((string) $raw, true);
            if (is_array($decoded)) {
                return $decoded;
            }
            $error = 'response was not JSON';
        }
        $retryable = $raw === false || $status === 429 || $status >= 500;
        if ($attempts >= 4 || !$retryable) {
            fail('API call failed (HTTP ' . $status . ($error !== '' ? ', ' . $error : '') . '): ' . substr((string) $raw, 0, 400));
        }
        $delay = 2 ** $attempts;
        fwrite(STDERR, "  retrying in {$delay}s (HTTP {$status})…\n");
        sleep($delay);
    }
}

$args = array_slice($argv, 1);
$topic = argValue($args, 'topic') ?? fail('Usage: --topic "…" [--author "…"] [--reader "…"] [--style id] [--length pages] [--outline file] [--provider anthropic|google|openai] [--model id] [--out dir] [--no-edit] [--limit N]');
$provider = argValue($args, 'provider', 'anthropic');
$outDir = rtrim((string) argValue($args, 'out', 'book-output'), '/');
$limit = (int) (argValue($args, 'limit', '0') ?? '0');

$options = array_filter([
    'author' => argValue($args, 'author', ''),
    'reader' => argValue($args, 'reader', ''),
    'style' => argValue($args, 'style', 'conversational'),
], static fn (string $v): bool => $v !== '');
$options['length'] = argValue($args, 'length', '250');
$outlineFile = argValue($args, 'outline');
if ($outlineFile !== null) {
    is_file($outlineFile) || fail('Outline file not found: ' . $outlineFile);
    $rows = AmazonBookWriter::parseOutline((string) file_get_contents($outlineFile));
    $rows !== [] || fail('The outline file contains no chapters.');
    $options['chapters'] = $rows;
}

if (!is_dir($outDir) && !mkdir($outDir, 0775, true)) {
    fail('Could not create output directory: ' . $outDir);
}
@mkdir($outDir . '/chapters', 0775, true);
@mkdir($outDir . '/edited', 0775, true);

$writer = new AmazonBookWriter();
$developer = new ManuscriptDeveloper();

echo "Pass 1 — outline and draft directions…\n";
$result = $writer->writeBook($topic, $options);
$plan = $developer->developmentPlan($result['book'], $result['kdp']['metadata'], (string) $provider, array_filter([
    'model' => argValue($args, 'model', ''),
]));
file_put_contents($outDir . '/drafting-kit.json', json_encode($plan, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
echo '  ' . count($plan['writer_jobs']) . " chapters planned; drafting kit saved to {$outDir}/drafting-kit.json\n";

$key = argValue($args, 'key', getenv((string) $plan['key_env']) ?: null);
if ($key === null || $key === '') {
    echo "\nNo API key found in {$plan['key_env']} (or --key). The drafting kit holds every\n";
    echo "writer and editor prompt — run again with a key to develop the book in one go,\n";
    echo "or send the prompts to your own AI tooling and save the replies as\n";
    echo "{$outDir}/chapters/chapter-NN.txt, then re-run to assemble.\n";
    $pending = array_filter($plan['writer_jobs'], fn (array $j): bool => !is_file($outDir . '/chapters/' . $j['output_file']));
    if ($pending !== []) {
        exit(0);
    }
    echo "All chapter files already exist — assembling without an API key.\n";
}

$injectKey = static function (array $headers, string $key): array {
    foreach ($headers as $name => $value) {
        $headers[$name] = preg_replace('/\{[A-Z_]+\}/', $key, (string) $value);
    }
    return $headers;
};

echo "\nPass 2 — writing chapters…\n";
$done = 0;
foreach ($plan['writer_jobs'] as $job) {
    $file = $outDir . '/chapters/' . $job['output_file'];
    if (is_file($file)) {
        echo "  chapter {$job['chapter']}: exists, skipping\n";
        continue;
    }
    if ($limit > 0 && $done >= $limit) {
        echo "  limit reached; run again to continue\n";
        break;
    }
    echo "  chapter {$job['chapter']}: {$job['title']} ({$job['word_target']}w)…\n";
    $response = httpPostJson((string) $job['request']['endpoint'], $injectKey((array) $job['request']['headers'], (string) $key), (array) $job['request']['body']);
    $text = $developer->extractText((string) $provider, $response);
    str_starts_with(trim($text), 'Chapter ') || fail("Chapter {$job['chapter']} reply did not start with the chapter heading; response saved nowhere — re-run to retry.");
    file_put_contents($file, trim($text) . "\n");
    $done++;
}

$missing = array_filter($plan['writer_jobs'], fn (array $j): bool => !is_file($outDir . '/chapters/' . $j['output_file']));
if ($missing !== []) {
    echo "\n" . count($missing) . " chapters still pending — run again to continue.\n";
    exit(0);
}

$readChapter = static function (string $dir, int $number): string {
    return trim((string) file_get_contents(sprintf('%s/chapter-%02d.txt', $dir, $number)));
};

$editedDir = $outDir . '/edited';
if (!hasFlag($args, 'no-edit') && $key !== null && $key !== '') {
    echo "\nPass 3 — editing chapters…\n";
    foreach ($plan['editor_jobs'] as $job) {
        $target = $outDir . '/' . $job['output_file'];
        if (is_file($target)) {
            echo "  chapter {$job['chapter']}: edited, skipping\n";
            continue;
        }
        $number = (int) $job['chapter'];
        $text = $readChapter($outDir . '/chapters', $number);
        $paragraphs = static fn (string $t): array => preg_split('/\R{2,}/u', $t, -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $previousClose = $number > 1 ? implode("\n\n", array_slice($paragraphs($readChapter($outDir . '/chapters', $number - 1)), -2)) : '';
        $nextOpen = $number < count($plan['writer_jobs']) ? implode("\n\n", array_slice($paragraphs($readChapter($outDir . '/chapters', $number + 1)), 1, 2)) : '';
        $prompt = strtr((string) $job['prompt_template'], [
            '{CHAPTER_TEXT}' => $text,
            '{PREVIOUS_CLOSE}' => $previousClose,
            '{NEXT_OPEN}' => $nextOpen,
        ]);
        $spec = $developer->requestSpec((string) $plan['provider'], (string) $plan['model'], (string) $plan['style_contract'], $prompt);
        echo "  chapter {$number}: editing…\n";
        $response = httpPostJson((string) $spec['endpoint'], $injectKey((array) $spec['headers'], (string) $key), (array) $spec['body']);
        $edited = $developer->extractText((string) $provider, $response);
        file_put_contents($target, (str_starts_with(trim($edited), 'Chapter ') ? trim($edited) : $text) . "\n");
    }
} else {
    echo "\nPass 3 — skipped.\n";
}

echo "\nAssembly — figures, contents page, exports…\n";
$texts = [];
foreach ($plan['writer_jobs'] as $job) {
    $number = (int) $job['chapter'];
    $edited = sprintf('%s/chapter-%02d.txt', $editedDir, $number);
    $texts[$number] = trim((string) file_get_contents(is_file($edited) ? $edited : sprintf('%s/chapters/chapter-%02d.txt', $outDir, $number)));
}
$book = $developer->applyDevelopedChapters($result['book'], $texts);
$metadata = $result['kdp']['metadata'];
$media = $writer->illustrationStudio()->planBookMedia($book, $metadata, []);
file_put_contents($outDir . '/manuscript.docx', (new WordManuscriptExporter())->export($book, $metadata, $media));
file_put_contents($outDir . '/book.epub', (new EpubExporter())->export($book, $metadata, $media));
file_put_contents($outDir . '/manuscript.html', $writer->exportManuscriptHtml($book, $metadata, $media));
file_put_contents($outDir . '/metadata.json', json_encode($writer->exportMetadata($result['kdp']), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
$result['book'] = $book;
$projectId = (new BookProjectStore())->save($topic, $options, $result);

echo "Done. {$book['page_count']} pages, {$book['total_word_count']} words, " . count($book['chapters']) . " chapters.\n";
echo "  {$outDir}/manuscript.docx\n  {$outDir}/book.epub\n  {$outDir}/manuscript.html\n  {$outDir}/metadata.json\n";
echo "  project record saved: {$projectId}\n";
