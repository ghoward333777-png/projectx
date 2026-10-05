<?php

declare(strict_types=1);

require __DIR__ . '/_harness.php';

// --- Python-compatible normalisation (the feed's generator is Python) ---
foreach ([[1.0, '1.0'], [0.5, '0.5'], [6.022e23, '6.022e+23'], [1e16, '1e+16'], [1e15, '1000000000000000.0'], [0.0001, '0.0001'],
    [1e-05, '1e-05'], [-2.5, '-2.5'], [123456.789, '123456.789'], [0.1 + 0.2, '0.30000000000000004'], [0.0, '0.0']] as [$f, $py]) {
    check(Ufcs::pyFloat($f) === $py, "pyFloat($py)");
}
check(Ufcs::pyStr(true) === 'True' && Ufcs::pyStr(null) === 'None' && Ufcs::pyStr(42) === '42', 'pyStr scalars');
check(Ufcs::norm("  New\tYork  City ") === 'new york city', 'norm collapses whitespace and lowercases');

// --- Every record of the Prototype Test Kit sample re-validates ---
$sample = Ufcs::sample();
check(count($sample) === 242, 'sample has 242 records');
$bad = array_filter($sample, fn ($r) => Ufcs::validate($r) !== null);
check($bad === [], 'all sample fingerprints re-validate (' . count($bad) . ' failed)');
$numeric = array_filter($sample, fn ($r) => !is_string($r['nucleus']['object']));
check(count($numeric) > 0, 'sample includes numeric objects (exercises pyFloat)');
$t = $sample[0];
$t['nucleus']['object'] = 'Lyon';
check(Ufcs::validate($t) !== null, 'altered record is refused');
$t = $sample[0];
$t['polarity'] = '-';
check(Ufcs::validate($t) !== null, 'flipped polarity is refused');

// --- Synthetic feed ---
$a = Ufcs::synthesize(600, 3);
check($a === Ufcs::synthesize(600, 3), 'synthesis is deterministic');
check(array_filter($a, fn ($r) => Ufcs::validate($r) !== null) === [], 'synthetic records are valid');
check(count(array_unique(array_column($a, 'fuid'))) === 600, 'synthetic fuids are unique');

// --- Store: admit, corroborate, reject ---
$store = new FactStore();
$res = $store->ingest(array_merge($sample, [$t]));
check($res['rejected'] === 1 && $res['admitted'] + $res['merged'] === 242, 'store admits and corroborates, rejects the altered one');
check($store->count() === $res['admitted'], 'restatements merge rather than duplicate');

// --- FQL ---
$q = Fql::parse('find  fact where predicate IN [has_capital, "capital_of"] AND entity = "France" AND trust >= 0.4 rank by trust limit 5');
check($q->render() === 'FIND fact WHERE predicate IN [has_capital, capital_of] AND entity = "France" AND trust >= 0.4 RANK BY trust LIMIT 5', 'FQL parses and renders canonically');
check(Fql::parse($q->render())->render() === $q->render(), 'render is a fixed point');
$hits = $store->query($q);
check(count($hits) >= 1 && array_reduce($hits, fn ($ok, $r) => $ok && Ufcs::trust($r) >= 0.4, true), 'trust filter applies');
check(array_reduce($hits, fn ($ok, $r) => $ok && (Ufcs::norm($r['nucleus']['subject']) === 'france' || Ufcs::norm($r['nucleus']['object']) === 'france'), true), 'entity matches subject or object');
$ranked = $store->query(Fql::parse('FIND fact RANK BY trust LIMIT 20'));
$trusts = array_map([Ufcs::class, 'trust'], $ranked);
$sorted = $trusts;
rsort($sorted);
check($trusts === $sorted && count($ranked) === 20, 'RANK BY trust orders descending; LIMIT applies');
check(count($store->query(Fql::parse('FIND fact WHERE text ~ "capital" AND polarity = "-"'))) === count(array_filter($store->query(Fql::parse('FIND fact WHERE text ~ "capital" LIMIT 1000')), fn ($r) => $r['polarity'] === '-')), 'conjunction semantics');
check($store->query(Fql::parse('FIND fact LIMIT 7')) === $store->query(Fql::parse('FIND fact LIMIT 7')), 'unranked results are deterministic');
throws(fn () => Fql::parse('SELECT * FROM facts'), 'non-FQL refused');
throws(fn () => Fql::parse('FIND fact WHERE colour = "red"'), 'unknown field refused');
throws(fn () => Fql::parse('FIND fact WHERE trust >= high'), 'numeric field needs a number');

done('ufcs-fql-contract');
