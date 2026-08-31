<?php

declare(strict_types=1);

require_once __DIR__ . '/../AmazonBookWriter.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$writer = new AmazonBookWriter();
$producer = $writer->audiobookProducer();

$result = $writer->writeBook('Leadership strategy', [
    'reader' => 'new team leads',
    'author' => 'Garry S. Howard',
    'style' => 'executive',
    'length' => 12,
]);
$book = $result['book'];
$metadata = $result['kdp']['metadata'];

// --- Editions --------------------------------------------------------------
$editions = $result['kdp']['editions'];
foreach (['kindle', 'paperback', 'hardcover', 'audiobook'] as $key) {
    contract_check(isset($editions[$key]['label'], $editions[$key]['price'], $editions[$key]['royalty_per_copy']), "editions must include a priced {$key} edition");
}

// --- Hardcover economics ---------------------------------------------------
$hardcover = $result['kdp']['hardcover'];
contract_check($hardcover['page_count'] >= 75 && $hardcover['page_count'] <= 550, 'hardcover page count must respect KDP 75-550 limits');
$expected = round((0.60 * $hardcover['list_price']) - $hardcover['printing_cost'], 2);
contract_check(abs($hardcover['royalty_per_copy'] - max(0.0, $expected)) < 0.01, 'hardcover royalty must follow (60% × list) − printing cost');
$long = $writer->hardcoverPlan(300);
contract_check(abs($long['printing_cost'] - (5.65 + 300 * 0.012)) < 0.001, 'long hardcovers must use the fixed + per-page model');
$short = $writer->hardcoverPlan(10);
contract_check($short['page_count'] === 75, 'hardcovers below 75 pages must be padded to the KDP minimum');

// --- Narration script ------------------------------------------------------
$script = $producer->narrationScript($book, $metadata);
contract_check(str_contains($script['opening_credits'], $metadata['title']), 'opening credits must name the book');
contract_check(str_contains($script['opening_credits'], 'Garry S. Howard'), 'opening credits must name the author');
contract_check(count($script['chapters']) === count($book['chapters']), 'narration script must cover every chapter');
contract_check($script['total_word_count'] > $book['total_word_count'], 'narration word count must include credits');
$text = $producer->narrationScriptText($script);
contract_check(str_contains($text, 'OPENING CREDITS') && str_contains($text, 'CLOSING CREDITS'), 'plain-text script must include credits sections');

// --- Chunking --------------------------------------------------------------
foreach (['google' => 4500, 'elevenlabs' => 4500, 'local-clone' => 1200] as $provider => $limit) {
    $chunks = $producer->chunkText($script['chapters'][0]['text'], $limit);
    contract_check($chunks !== [], "chunking must produce chunks for {$provider}");
    foreach ($chunks as $i => $chunk) {
        contract_check(mb_strlen($chunk) <= $limit, "chunk {$i} must respect the {$provider} limit of {$limit} chars");
    }
    contract_check(
        preg_replace('/\s+/u', ' ', implode(' ', $chunks)) === preg_replace('/\s+/u', ' ', trim($script['chapters'][0]['text'])),
        "chunking must preserve the full text for {$provider}",
    );
}

// --- Plans per provider ----------------------------------------------------
foreach (AudiobookProducer::PROVIDERS as $provider) {
    $plan = $producer->plan($book, $metadata, $provider);
    contract_check($plan['runtime_estimate_hours'] > 0, "{$provider} plan must estimate runtime");
    contract_check($plan['chunk_count'] > 0, "{$provider} plan must count chunks");
    contract_check(isset($plan['acx_specs'], $plan['workflow'], $plan['suggested_retail']), "{$provider} plan must include specs, workflow, and retail");
}
$googlePlan = $producer->plan($book, $metadata, 'google');
contract_check($googlePlan['clone_consent']['required'] === false, 'stock Google voices must not require cloning consent');
$clonePlan = $producer->plan($book, $metadata, 'local-clone');
contract_check($clonePlan['clone_consent']['required'] === true, 'local cloning must require consent');
contract_check(str_contains($clonePlan['clone_consent']['status'], 'BLOCKED'), 'unconsented cloning must read as blocked');

// --- Consent gate ----------------------------------------------------------
$blocked = false;
try {
    $producer->synthesisManifest($book, $metadata, 'local-clone');
} catch (RuntimeException $e) {
    $blocked = true;
}
contract_check($blocked, 'cloning manifest without consent must be refused');
$blocked = false;
try {
    $producer->elevenLabsCloneRequest('Narrator', ['sample.wav'], false);
} catch (RuntimeException $e) {
    $blocked = true;
}
contract_check($blocked, 'ElevenLabs clone request without consent must be refused');
$cloneRequest = $producer->elevenLabsCloneRequest('Narrator', ['sample.wav'], true);
contract_check(str_contains($cloneRequest['endpoint'], 'voices/add'), 'consented clone request must target the voices/add endpoint');

// --- Manifests -------------------------------------------------------------
$manifest = $producer->synthesisManifest($book, $metadata, 'google');
contract_check($manifest['job_count'] === count($manifest['jobs']) && $manifest['job_count'] > 0, 'google manifest must enumerate jobs');
$first = $manifest['jobs'][0];
contract_check($first['section'] === 'Opening credits', 'the first job must be the opening credits');
contract_check(str_contains($first['request']['endpoint'], 'texttospeech.googleapis.com'), 'google jobs must carry the TTS endpoint');
contract_check(($first['request']['body']['input']['text'] ?? '') === $first['text'], 'google payload text must match the chunk');
$last = $manifest['jobs'][$manifest['job_count'] - 1];
contract_check($last['section'] === 'Closing credits', 'the last job must be the closing credits');

$elManifest = $producer->synthesisManifest($book, $metadata, 'elevenlabs', ['voice' => ['voice_id' => 'abc123']]);
contract_check(str_contains($elManifest['jobs'][0]['request']['endpoint'], 'api.elevenlabs.io/v1/text-to-speech/abc123'), 'elevenlabs jobs must target the chosen voice');

$localManifest = $producer->synthesisManifest($book, $metadata, 'local-clone', [
    'voice' => ['sample_path' => 'samples/narrator.wav'],
    'voice_consent' => true,
]);
contract_check($localManifest['voice_consent'] === true, 'consented local manifest must record consent');
contract_check(($localManifest['jobs'][0]['request']['parameters']['sample'] ?? '') === 'samples/narrator.wav', 'local jobs must carry the sample path');
contract_check(str_ends_with($localManifest['jobs'][0]['output_file'], '.wav'), 'local clone output must be wav');

// --- Package integration ---------------------------------------------------
$withClone = $writer->writeBook('Leadership strategy', [
    'author' => 'Garry S. Howard',
    'length' => 12,
    'audiobook_provider' => 'local-clone',
    'audiobook_voice' => ['sample_path' => 'samples/narrator.wav'],
    'voice_consent' => true,
]);
contract_check($withClone['kdp']['audiobook']['provider'] === 'local-clone', 'package must honor the chosen audiobook provider');
contract_check($withClone['kdp']['audiobook']['clone_consent']['confirmed'] === true, 'package must record confirmed consent');
$checklistSteps = array_column($withClone['kdp']['checklist'], 'step');
contract_check(in_array('Hardcover edition', $checklistSteps, true), 'checklist must include the hardcover edition');
contract_check(in_array('Audiobook production', $checklistSteps, true), 'checklist must include audiobook production');

$export = $writer->exportMetadata($withClone['kdp']);
contract_check(isset($export['kdp_pricing']['hardcover']['list_price']), 'metadata export must include hardcover pricing');
contract_check(isset($export['editions']['audiobook'], $export['audiobook']['runtime_estimate_hours']), 'metadata export must include editions and the audiobook plan');

fwrite(STDOUT, "Audiobook and editions contract passed\n");
