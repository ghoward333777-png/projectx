#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Synthesize an audiobook from a manifest produced by AudiobookProducer.
 *
 * Providers:
 *   google      — Google Cloud Text-to-Speech (set GOOGLE_TTS_API_KEY or --key)
 *   elevenlabs  — ElevenLabs (set ELEVENLABS_API_KEY or --key)
 *   local-clone — your own cloning engine via --engine-cmd template
 *
 * Voice cloning from a sampled human recording requires the recorded
 * speaker's explicit consent: pass --consent to confirm it. Without it,
 * cloning jobs are refused.
 *
 * Usage:
 *   php bin/synthesize-audiobook.php --manifest audiobook-manifest.json --out audio/
 *   php bin/synthesize-audiobook.php --manifest m.json --out audio/ --key YOUR_KEY
 *   php bin/synthesize-audiobook.php --manifest m.json --out audio/ \
 *       --engine-cmd 'tts --text {text} --speaker_wav {sample} --language_idx {language} --out_path {out}' --consent
 *   php bin/synthesize-audiobook.php --clone-name "My Voice" --clone-sample s1.wav --consent --key YOUR_KEY
 *
 * After synthesis, join each section's chunks in order, e.g.:
 *   ffmpeg -f concat -safe 0 -i section01.txt -c copy chapter01.mp3
 */

require_once __DIR__ . '/../AudiobookProducer.php';

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

function httpPost(string $url, array $headers, string $body): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 120,
    ]);
    $response = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    if ($response === false) {
        fail('HTTP request failed: ' . $error);
    }
    return [$status, (string) $response];
}

$argvList = array_slice($argv, 1);

// --- One-time ElevenLabs voice cloning ------------------------------------
$cloneName = argValue($argvList, 'clone-name');
if ($cloneName !== null) {
    if (!hasFlag($argvList, 'consent')) {
        fail('Voice cloning requires the recorded speaker\'s explicit consent. Re-run with --consent once you have it.');
    }
    $key = argValue($argvList, 'key', getenv('ELEVENLABS_API_KEY') ?: null) ?? fail('ElevenLabs API key required (--key or ELEVENLABS_API_KEY).');
    $samples = [];
    foreach ($argvList as $i => $arg) {
        if ($arg === '--clone-sample' && isset($argvList[$i + 1])) {
            $samples[] = $argvList[$i + 1];
        }
    }
    if ($samples === []) {
        fail('Provide at least one --clone-sample recording (clean single-speaker WAV/MP3, 1–5 minutes total).');
    }
    $post = ['name' => $cloneName, 'description' => 'Cloned narration voice; recorded speaker consented to cloning.'];
    foreach ($samples as $i => $path) {
        if (!is_file($path)) {
            fail('Sample not found: ' . $path);
        }
        $post['files[' . $i . ']'] = new CURLFile($path);
    }
    $ch = curl_init('https://api.elevenlabs.io/v1/voices/add');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $post,
        CURLOPT_HTTPHEADER => ['xi-api-key: ' . $key],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 300,
    ]);
    $response = (string) curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    if ($status !== 200) {
        fail('Voice clone failed (HTTP ' . $status . '): ' . $response);
    }
    $data = json_decode($response, true);
    echo 'Voice cloned. voice_id: ' . ($data['voice_id'] ?? '(see response)') . "\n";
    echo "Use it as the manifest voice.voice_id, then run synthesis.\n";
    exit(0);
}

// --- Manifest synthesis -----------------------------------------------------
$manifestPath = argValue($argvList, 'manifest') ?? fail('Usage: --manifest <file> --out <dir> [--key KEY] [--engine-cmd TEMPLATE] [--consent] [--limit N]');
$outDir = argValue($argvList, 'out', 'audiobook-output');
$limit = (int) (argValue($argvList, 'limit', '0') ?? '0');

if (!is_file($manifestPath)) {
    fail('Manifest not found: ' . $manifestPath);
}
$manifest = json_decode((string) file_get_contents($manifestPath), true);
if (!is_array($manifest) || !isset($manifest['provider'], $manifest['jobs'])) {
    fail('Invalid manifest: expected JSON with provider and jobs (generate it from the Amazon Book Writer page or AudiobookProducer::synthesisManifest()).');
}
$provider = (string) $manifest['provider'];
$voice = is_array($manifest['voice'] ?? null) ? $manifest['voice'] : [];

$producer = new AudiobookProducer();
if ($producer->requiresCloneConsent($provider, $voice)
    && !hasFlag($argvList, 'consent')
    && empty($manifest['voice_consent'])) {
    fail('This manifest clones a sampled human voice. Confirm the recorded speaker\'s consent with --consent.');
}

if (!is_dir($outDir) && !mkdir($outDir, 0775, true)) {
    fail('Could not create output directory: ' . $outDir);
}

$jobs = $manifest['jobs'];
if ($limit > 0) {
    $jobs = array_slice($jobs, 0, $limit);
}
$total = count($jobs);
echo 'Synthesizing ' . $total . ' chunks via ' . ($manifest['provider_label'] ?? $provider) . ' into ' . $outDir . "/\n";

$done = 0;
foreach ($jobs as $job) {
    $outFile = rtrim($outDir, '/') . '/' . $job['output_file'];
    if (is_file($outFile) && filesize($outFile) > 0) {
        $done++;
        continue; // resumable: skip chunks that already exist
    }
    $text = (string) $job['text'];

    if ($provider === 'google') {
        $key = argValue($argvList, 'key', getenv('GOOGLE_TTS_API_KEY') ?: null)
            ?? fail('Google TTS API key required (--key or GOOGLE_TTS_API_KEY).');
        [$status, $response] = httpPost(
            'https://texttospeech.googleapis.com/v1/text:synthesize?key=' . urlencode($key),
            ['Content-Type: application/json'],
            json_encode($job['request']['body'], JSON_THROW_ON_ERROR),
        );
        if ($status !== 200) {
            fail('Google TTS failed on ' . $job['id'] . ' (HTTP ' . $status . '): ' . substr($response, 0, 400));
        }
        $data = json_decode($response, true);
        $audio = base64_decode((string) ($data['audioContent'] ?? ''), true);
        if ($audio === false || $audio === '') {
            fail('Google TTS returned no audio for ' . $job['id']);
        }
        file_put_contents($outFile, $audio);
    } elseif ($provider === 'elevenlabs') {
        $key = argValue($argvList, 'key', getenv('ELEVENLABS_API_KEY') ?: null)
            ?? fail('ElevenLabs API key required (--key or ELEVENLABS_API_KEY).');
        $endpoint = (string) $job['request']['endpoint'];
        $query = http_build_query($job['request']['query'] ?? []);
        [$status, $response] = httpPost(
            $endpoint . ($query !== '' ? '?' . $query : ''),
            ['Content-Type: application/json', 'xi-api-key: ' . $key],
            json_encode($job['request']['body'], JSON_THROW_ON_ERROR),
        );
        if ($status !== 200) {
            fail('ElevenLabs failed on ' . $job['id'] . ' (HTTP ' . $status . '): ' . substr($response, 0, 400));
        }
        file_put_contents($outFile, $response);
    } elseif ($provider === 'local-clone') {
        $template = argValue($argvList, 'engine-cmd')
            ?? fail('local-clone needs --engine-cmd, e.g. \'tts --text {text} --speaker_wav {sample} --language_idx {language} --out_path {out}\'');
        $params = $job['request']['parameters'];
        $command = str_replace(
            ['{text}', '{sample}', '{language}', '{out}'],
            [
                escapeshellarg((string) $params['text']),
                escapeshellarg((string) $params['sample']),
                escapeshellarg((string) $params['language']),
                escapeshellarg($outFile),
            ],
            $template,
        );
        passthru($command, $exitCode);
        if ($exitCode !== 0) {
            fail('Local engine failed on ' . $job['id'] . ' (exit ' . $exitCode . ').');
        }
    } else {
        fail('Unknown provider in manifest: ' . $provider);
    }

    $done++;
    echo sprintf("  [%d/%d] %s → %s\n", $done, $total, $job['id'], $job['output_file']);
    usleep(150000); // stay polite to rate limits
}

echo "Done. Join each section's chunks in order (ffmpeg concat), then master to ACX specs:\n";
echo "  192 kbps CBR MP3, RMS -23..-18 dB, peaks <= -3 dB, 0.5-1s room tone head/tail.\n";
