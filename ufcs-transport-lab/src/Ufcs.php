<?php

declare(strict_types=1);

/**
 * UFCS semantic layer: the Fact Unit record (QueryBook UFCS — Record Field
 * Layout & API, Prototype Test Kit 2026-09-25) and the rules a receiving node
 * applies to it.
 *
 * A record re-validates on arrival exactly as the QueryBook importer does:
 * semantic_fingerprint = SHA-256(norm(subject)|norm(predicate)|norm(object)|polarity),
 * where norm() is Python's " ".join(str(x).strip().lower().split()). A record
 * altered in transit no longer matches its fingerprint and is refused.
 */
final class Ufcs
{
    public const SAMPLE_FILE = __DIR__ . '/../data/ufcs_sample.jsonl';

    public static function norm(mixed $value): string
    {
        $s = strtolower(trim(self::pyStr($value)));
        return implode(' ', preg_split('/\s+/u', $s, -1, PREG_SPLIT_NO_EMPTY) ?: []);
    }

    /** Python's str() of a JSON scalar, as the feed generator produced it. */
    public static function pyStr(mixed $v): string
    {
        if (is_string($v)) {
            return $v;
        }
        if (is_bool($v)) {
            return $v ? 'True' : 'False';
        }
        if ($v === null) {
            return 'None';
        }
        if (is_int($v)) {
            return (string) $v;
        }
        if (is_float($v)) {
            return self::pyFloat($v);
        }
        return json_encode($v, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    }

    /** Python repr() of a float: shortest round-trip digits, sci notation outside 1e-4 ≤ |x| < 1e16. */
    public static function pyFloat(float $f): string
    {
        if (is_nan($f)) {
            return 'nan';
        }
        if (is_infinite($f)) {
            return $f > 0 ? 'inf' : '-inf';
        }
        $sign = ($f < 0 || ($f == 0.0 && fdiv(1, $f) < 0)) ? '-' : '';
        $repr = json_encode(abs($f), JSON_PRESERVE_ZERO_FRACTION); // shortest round-trip
        $exp = 0;
        if (preg_match('/^([0-9.]+)e([+-]?\d+)$/i', $repr, $m)) {
            $repr = $m[1];
            $exp = (int) $m[2];
        }
        [$int, $frac] = array_pad(explode('.', $repr), 2, '');
        $digits = ltrim($int . $frac, '0');
        $decpt = strlen($int) + $exp; // position of the point relative to $int.$frac's digits
        $decpt -= strlen($int . $frac) - strlen($digits); // shift for stripped leading zeros
        $digits = rtrim($digits, '0');
        if ($digits === '') {
            return $sign . '0.0';
        }
        if ($decpt > -4 && $decpt <= 16) {
            if ($decpt <= 0) {
                $out = '0.' . str_repeat('0', -$decpt) . $digits;
            } elseif ($decpt >= strlen($digits)) {
                $out = $digits . str_repeat('0', $decpt - strlen($digits)) . '.0';
            } else {
                $out = substr($digits, 0, $decpt) . '.' . substr($digits, $decpt);
            }
            return $sign . $out;
        }
        $e = $decpt - 1;
        $mant = $digits[0] . (strlen($digits) > 1 ? '.' . substr($digits, 1) : '');
        return $sign . $mant . 'e' . ($e < 0 ? '-' : '+') . str_pad((string) abs($e), 2, '0', STR_PAD_LEFT);
    }

    public static function fingerprint(mixed $subject, mixed $predicate, mixed $object, string $polarity): string
    {
        return hash('sha256', self::norm($subject) . '|' . self::norm($predicate) . '|' . self::norm($object) . '|' . $polarity);
    }

    /** @return null|string Why the record is refused, or null when it is admissible. */
    public static function validate(array $r): ?string
    {
        foreach (['fuid', 'nucleus', 'polarity', 'semantic_fingerprint'] as $k) {
            if (!array_key_exists($k, $r)) {
                return 'missing ' . $k;
            }
        }
        $n = (array) $r['nucleus'];
        foreach (['subject', 'predicate', 'object'] as $k) {
            if (!array_key_exists($k, $n)) {
                return 'missing nucleus.' . $k;
            }
        }
        if (!in_array($r['polarity'], ['+', '-'], true)) {
            return 'polarity must be "+" or "-"';
        }
        $fp = self::fingerprint($n['subject'], $n['predicate'], $n['object'], $r['polarity']);
        if ($fp !== strtolower((string) $r['semantic_fingerprint'])) {
            return 'semantic_fingerprint does not re-validate (altered in transit?)';
        }
        return null;
    }

    /** @return array<int, array<string, mixed>> */
    public static function sample(): array
    {
        static $cache = null;
        if ($cache === null) {
            $cache = self::decodeBatch((string) file_get_contents(self::SAMPLE_FILE));
        }
        return $cache;
    }

    /**
     * Deterministic synthetic feed for benchmarks: the sample's records with
     * fresh identities, so hashes stay high-entropy (as in the real feed) and
     * compression ratios are not flattered by verbatim repetition.
     *
     * @return array<int, array<string, mixed>>
     */
    public static function synthesize(int $count, int $seed = 1): array
    {
        $sample = self::sample();
        $out = [];
        for ($i = 0; $i < $count; $i++) {
            $r = $sample[($i * 7 + $seed) % count($sample)];
            $k = $seed . ':' . $i;
            $round = intdiv($i, count($sample));
            if ($round > 0) {
                $r['nucleus']['subject'] = $r['nucleus']['subject'] . ' (' . $round . ')';
            }
            $n = $r['nucleus'];
            $r['semantic_fingerprint'] = self::fingerprint($n['subject'], $n['predicate'], $n['object'], $r['polarity']);
            $r['fuid'] = hash('sha256', 'fuid|' . $k);
            $r['embedding_ref'] = 'emb:' . substr($r['semantic_fingerprint'], 0, 16);
            $r['provenance']['ref'] = hash('sha256', 'prov|' . $k);
            $r['provenance']['chain_index'] = $i + 1;
            $r['provenance']['signature'] = 'ed25519:' . substr(hash('sha256', 'sig|' . $k), 0, 32);
            $r['version']['chain_id'] = substr(hash('sha256', 'chain|' . $k), 0, 16);
            if (!empty($r['links'])) {
                $r['links'][0]['target_fuid'] = hash('sha256', 'link|' . $k);
            }
            $day = 1 + ($i % 28);
            $r['temporal']['anchor'] = sprintf('2026-06-%02dT12:00:00Z', $day);
            $r['temporal']['ingested'] = $r['temporal']['anchor'];
            $out[] = $r;
        }
        return $out;
    }

    /** @param array<int, array<string, mixed>> $records */
    public static function encodeBatch(array $records): string
    {
        $lines = [];
        foreach ($records as $r) {
            $lines[] = json_encode($r, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION);
        }
        return implode("\n", $lines) . "\n";
    }

    /** @return array<int, array<string, mixed>> */
    public static function decodeBatch(string $jsonl): array
    {
        $out = [];
        foreach (explode("\n", $jsonl) as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $r = json_decode($line, true);
            if (is_array($r)) {
                $out[] = $r;
            }
        }
        return $out;
    }

    /** Entities and relations a batch mentions — goes into the frame meta. */
    public static function batchContext(array $records, int $limit = 8): array
    {
        $entities = [];
        $relations = [];
        foreach ($records as $r) {
            $entities[(string) ($r['nucleus']['subject'] ?? '')] = true;
            $relations[(string) ($r['nucleus']['predicate'] ?? '')] = true;
        }
        unset($entities[''], $relations['']);
        return [
            'entity_ids' => array_slice(array_keys($entities), 0, $limit),
            'relation_ids' => array_slice(array_keys($relations), 0, $limit),
        ];
    }

    public static function trust(array $r): float
    {
        return (float) ($r['certification']['trust_score'] ?? 0.0);
    }
}

/**
 * Node 2's QueryBook/UFCS store: admitted records keyed by semantic
 * fingerprint. A restated proposition merges as corroboration rather than
 * becoming a duplicate.
 */
final class FactStore
{
    /** @var array<string, array<string, mixed>> */
    private array $facts = [];
    /** @var array<string, int> */
    private array $corroboration = [];
    public int $rejected = 0;
    /** @var array<int, string> */
    public array $rejections = [];

    /**
     * @param array<int, array<string, mixed>> $records
     * @return array{admitted:int, merged:int, rejected:int}
     */
    public function ingest(array $records): array
    {
        $res = ['admitted' => 0, 'merged' => 0, 'rejected' => 0];
        foreach ($records as $r) {
            if (($why = Ufcs::validate($r)) !== null) {
                $res['rejected']++;
                $this->rejected++;
                $this->rejections[] = ($r['fuid'] ?? '?') . ': ' . $why;
                if (count($this->rejections) > 50) {
                    array_shift($this->rejections);
                }
                continue;
            }
            $fp = strtolower((string) $r['semantic_fingerprint']);
            if (isset($this->facts[$fp])) {
                $this->corroboration[$fp]++;
                $res['merged']++;
                if (Ufcs::trust($r) > Ufcs::trust($this->facts[$fp])) {
                    $this->facts[$fp] = $r;
                }
                continue;
            }
            $this->facts[$fp] = $r;
            $this->corroboration[$fp] = 1;
            $res['admitted']++;
        }
        return $res;
    }

    public function count(): int
    {
        return count($this->facts);
    }

    public function corroborations(string $fingerprint): int
    {
        return $this->corroboration[strtolower($fingerprint)] ?? 0;
    }

    /** @return array<int, array<string, mixed>> */
    public function query(Fql $q): array
    {
        return $q->execute(array_values($this->facts));
    }

    public function clear(): void
    {
        $this->facts = [];
        $this->corroboration = [];
        $this->rejected = 0;
        $this->rejections = [];
    }
}
