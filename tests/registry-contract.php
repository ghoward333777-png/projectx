<?php

declare(strict_types=1);

/**
 * QueryBook Technical Registry contract.
 *
 * Mirrors registry/validate.py in dependency-free PHP so the registry gate
 * runs with the rest of the suite (plain `php tests/registry-contract.php`).
 * On top of the validator's own checks it enforces the sync policy:
 *
 *  - Syncs are additive. A newer registry must be a super-set of the one it
 *    replaces — the feature and claim floors below only ever move up.
 *  - The Fact Unit definition and the event-fact-unit specification must
 *    always be present (the anchor features below).
 */

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

/** @return array<int, array<string, mixed>> */
function registry_load(string $file): array
{
    $path = __DIR__ . '/../registry/data/' . $file;
    contract_check(is_file($path), "registry must ship {$file}");
    $decoded = json_decode((string) file_get_contents($path), true);
    contract_check(is_array($decoded), "{$file} must decode as JSON");

    return $decoded;
}

function registry_csv_records(string $file): int
{
    $handle = fopen(__DIR__ . '/../registry/data/' . $file, 'rb');
    contract_check($handle !== false, "registry must ship {$file}");
    $records = 0;
    while (fgetcsv($handle) !== false) {
        $records++;
    }
    fclose($handle);

    return $records - 1; // header row
}

$features = registry_load('features.json');
$claims = registry_load('claims.json');
$domains = registry_load('domains.json');
$transfers = registry_load('transfer_matrix.json');
$paths = registry_load('paths.json');
$excluded = registry_load('excluded_set.json');
$manifest = registry_load('manifest.json');

// --- Sync policy: additive only, floors from the 2026-02-03 registry -------
$featureFloor = 279;
$claimFloor = 341;
contract_check(count($features) >= $featureFloor, 'registry syncs are additive: the feature count must never drop below ' . $featureFloor);
contract_check(count($claims) >= $claimFloor, 'registry syncs are additive: the claim count must never drop below ' . $claimFloor);

$names = array_map(static fn (array $f): string => (string) $f['name'], $features);
foreach ([
    'Fact Unit Schema',
    'Fact Universe Architecture',
    'Fact Graph Visualization',
    'Event Type Catalogue',
    'Environment Vector Normalization',
    'Causal Edge Temporal Validation',
    'Timeline Reconstruction',
] as $anchor) {
    contract_check(in_array($anchor, $names, true), "the Fact Unit / event-fact anchors must survive every sync: missing '{$anchor}'");
}

// --- Claims (registry/validate.py parity) -----------------------------------
$ids = array_map(static fn (array $c): int => (int) $c['id'], $claims);
contract_check($ids === range(1, count($ids)), 'claim ids must be contiguous from 1');
$idSet = array_flip($ids);
$independent = [];
foreach ($claims as $claim) {
    $dependsOn = (array) $claim['depends_on'];
    contract_check(count($dependsOn) <= 1, "claim {$claim['id']} must not have multiple dependencies");
    foreach ($dependsOn as $dependency) {
        contract_check(isset($idSet[(int) $dependency]), "claim {$claim['id']} must not have a dangling dependency");
        contract_check((int) $dependency < (int) $claim['id'], "claim {$claim['id']} must not have a forward or self dependency");
    }
    contract_check(strlen((string) $claim['text']) >= 60, "claim {$claim['id']} must not be under 60 characters");
    if ($dependsOn === []) {
        $independent[] = (int) $claim['id'];
    }
}
contract_check($independent !== [], 'the registry must carry independent claims');

// --- Features (registry/validate.py parity) ---------------------------------
foreach (['name', 'category', 'citation', 'actor', 'algorithm', 'rule', 'domain', 'layer'] as $field) {
    foreach ($features as $feature) {
        contract_check(($feature[$field] ?? '') !== '', "feature {$feature['id']} must not have a blank '{$field}'");
    }
}
$featureIds = array_map(static fn (array $f): int => (int) $f['id'], $features);
contract_check(count(array_unique($featureIds)) === count($features), 'feature ids must be unique');
contract_check(count(array_unique($names)) === count($features), 'feature names must be unique');

$domainIds = array_map(static fn (array $d): string => (string) $d['id'], $domains);
$perDomain = [];
foreach ($features as $feature) {
    $domainId = explode(' ', (string) $feature['domain'])[0];
    contract_check(in_array($domainId, $domainIds, true), "feature {$feature['id']} must sit in a known domain");
    $perDomain[$domainId] = ($perDomain[$domainId] ?? 0) + 1;
}

// --- Architecture (registry/validate.py parity) ------------------------------
contract_check(count($domains) === 15, 'the registry must describe 15 domains');
$layers = array_unique(array_map(static fn (array $d): string => (string) $d['layer'], $domains));
contract_check(count($layers) === 5, 'the registry must describe 5 layers');
$denied = [];
foreach ($transfers as $transfer) {
    if ($transfer['permission'] === 'denied') {
        $denied[$transfer['from'] . '->' . $transfer['to']] = true;
    }
}
foreach (['D11->D0', 'D7->D2', 'D13->D4', 'D13->D7', 'D9->D2'] as $pair) {
    contract_check(isset($denied[$pair]), "the transfer matrix must deny {$pair}");
}

foreach ($domains as $domain) {
    contract_check((int) $domain['feature_count'] === ($perDomain[$domain['id']] ?? 0), "domain {$domain['id']} feature_count must match the feature list");
}

// --- Structural invariants ---------------------------------------------------
contract_check(count((array) $paths['invariants']) === 2, 'both path-separation invariants must be present');
contract_check(count($excluded) >= 9, 'the permanently-excluded set must never shrink');
foreach ($excluded as $exclusion) {
    if ($exclusion['subsystem'] === 'The excluded set itself') {
        $selfExcluded = true;
    }
}
contract_check(isset($selfExcluded), 'the excluded set must exclude itself');

// --- Manifest and CSV mirrors must match the JSON ---------------------------
$counts = (array) $manifest['counts'];
contract_check((int) $counts['features'] === count($features), 'manifest feature count must match features.json');
contract_check((int) $counts['claims'] === count($claims), 'manifest claim count must match claims.json');
contract_check((int) $counts['domains'] === count($domains), 'manifest domain count must match domains.json');
contract_check((int) $counts['independent_claims'] === count($independent), 'manifest independent-claim count must match claims.json');
$withExpression = count(array_filter($features, static fn (array $f): bool => (bool) $f['has_expression']));
contract_check((int) $counts['worked_expressions'] === $withExpression, 'manifest worked-expression count must match features.json');
contract_check((array) $manifest['claim_integrity']['independent'] === $independent, 'manifest independent-claim list must match claims.json');

contract_check(registry_csv_records('features.csv') === count($features), 'features.csv must mirror features.json row for row');
contract_check(registry_csv_records('claims.csv') === count($claims), 'claims.csv must mirror claims.json row for row');

fwrite(STDOUT, 'Registry contract passed: ' . count($features) . ' features, ' . count($claims) . " claims, additive-sync floors intact\n");
