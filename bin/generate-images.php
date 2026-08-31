#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Generate AI images from a manifest produced by IllustrationStudio.
 *
 * Providers:
 *   google    — Imagen via the Generative Language API (GOOGLE_AI_API_KEY or --key)
 *   openai    — gpt-image-1 (OPENAI_API_KEY or --key)
 *   stability — Stable Image Core (STABILITY_API_KEY or --key)
 *
 * Usage:
 *   php bin/generate-images.php --manifest images-manifest.json --out images/
 *   php bin/generate-images.php --manifest m.json --out images/ --key YOUR_KEY --limit 3
 *
 * Resumable: chunks whose output file already exists are skipped.
 */

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

function fail(string $message): never
{
    fwrite(STDERR, 'ERROR: ' . $message . "\n");
    exit(1);
}

function httpPost(string $url, array $headers, string|array $body): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 300,
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
$manifestPath = argValue($argvList, 'manifest') ?? fail('Usage: --manifest <file> --out <dir> [--key KEY] [--limit N]');
$outDir = argValue($argvList, 'out', 'image-output');
$limit = (int) (argValue($argvList, 'limit', '0') ?? '0');

if (!is_file($manifestPath)) {
    fail('Manifest not found: ' . $manifestPath);
}
$manifest = json_decode((string) file_get_contents($manifestPath), true);
if (!is_array($manifest) || !isset($manifest['provider'], $manifest['jobs'])) {
    fail('Invalid manifest: expected JSON with provider and jobs (download it from the Amazon Book Writer page).');
}
$provider = (string) $manifest['provider'];

$keyEnv = ['google' => 'GOOGLE_AI_API_KEY', 'openai' => 'OPENAI_API_KEY', 'stability' => 'STABILITY_API_KEY'][$provider] ?? '';
$key = argValue($argvList, 'key', $keyEnv !== '' ? (getenv($keyEnv) ?: null) : null)
    ?? fail(ucfirst($provider) . ' API key required (--key or ' . $keyEnv . ').');

if (!is_dir($outDir) && !mkdir($outDir, 0775, true)) {
    fail('Could not create output directory: ' . $outDir);
}

$jobs = $manifest['jobs'];
if ($limit > 0) {
    $jobs = array_slice($jobs, 0, $limit);
}
$total = count($jobs);
echo 'Generating ' . $total . ' images via ' . ($manifest['provider_label'] ?? $provider) . ' into ' . $outDir . "/\n";

$done = 0;
foreach ($jobs as $job) {
    $outFile = rtrim($outDir, '/') . '/' . $job['output_file'];
    if (is_file($outFile) && filesize($outFile) > 0) {
        $done++;
        continue;
    }
    if ($provider === 'google') {
        [$status, $response] = httpPost(
            (string) $job['request']['endpoint'],
            ['Content-Type: application/json', 'x-goog-api-key: ' . $key],
            json_encode($job['request']['body'], JSON_THROW_ON_ERROR),
        );
        if ($status !== 200) {
            fail('Google Imagen failed on ' . $job['id'] . ' (HTTP ' . $status . '): ' . substr($response, 0, 400));
        }
        $data = json_decode($response, true);
        $image = base64_decode((string) ($data['predictions'][0]['bytesBase64Encoded'] ?? ''), true);
        if ($image === false || $image === '') {
            fail('Google Imagen returned no image for ' . $job['id']);
        }
        file_put_contents($outFile, $image);
    } elseif ($provider === 'openai') {
        [$status, $response] = httpPost(
            (string) $job['request']['endpoint'],
            ['Content-Type: application/json', 'Authorization: Bearer ' . $key],
            json_encode($job['request']['body'], JSON_THROW_ON_ERROR),
        );
        if ($status !== 200) {
            fail('OpenAI Images failed on ' . $job['id'] . ' (HTTP ' . $status . '): ' . substr($response, 0, 400));
        }
        $data = json_decode($response, true);
        $image = base64_decode((string) ($data['data'][0]['b64_json'] ?? ''), true);
        if ($image === false || $image === '') {
            fail('OpenAI Images returned no image for ' . $job['id']);
        }
        file_put_contents($outFile, $image);
    } elseif ($provider === 'stability') {
        [$status, $response] = httpPost(
            (string) $job['request']['endpoint'],
            ['Authorization: Bearer ' . $key, 'Accept: image/*'],
            $job['request']['fields'],
        );
        if ($status !== 200) {
            fail('Stability failed on ' . $job['id'] . ' (HTTP ' . $status . '): ' . substr($response, 0, 400));
        }
        file_put_contents($outFile, $response);
    } else {
        fail('Unknown provider in manifest: ' . $provider);
    }
    $done++;
    echo sprintf("  [%d/%d] %s → %s\n", $done, $total, $job['id'], $job['output_file']);
    usleep(250000);
}

echo "Done. Place the PNGs beside your manuscript and swap them in for the AI-image placeholders.\n";
