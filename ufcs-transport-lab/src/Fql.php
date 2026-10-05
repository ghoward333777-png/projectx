<?php

declare(strict_types=1);

/**
 * FQL — the declarative, read-only Fact Query Language a node uses to ask its
 * peer for facts (QBQL/FQL, Registry QBF-C054/C058). This is the transport
 * lab's subset, in the same surface form QueryBook renders with every answer:
 *
 *   FIND fact
 *   WHERE predicate IN [has_capital, located_in]
 *     AND entity = "France"
 *     AND trust >= 0.4
 *   RANK BY trust
 *   LIMIT 10
 *
 * Fields: subject, predicate, object, entity (subject or object), group,
 * polarity, fact_type, source (first source class), trust
 * (certification.trust_score), score (confidence.score), text (substring of
 * subject/predicate/object). Operators: = != > >= < <= IN ~ (contains).
 * Conditions are conjunctive. A query is a CONTROL frame; the answer comes
 * back as a FACT_BATCH whose meta carries reply_to and the rendered query.
 */
final class Fql
{
    private const FIELDS = ['subject', 'predicate', 'object', 'entity', 'group', 'polarity', 'fact_type', 'source', 'trust', 'score', 'text'];
    private const NUMERIC = ['trust', 'score'];

    /** @param array<int, array{field:string, op:string, value:mixed}> $where */
    public function __construct(
        public array $where = [],
        public ?string $rankBy = null,
        public int $limit = 100,
    ) {
    }

    public static function parse(string $query): self
    {
        $q = trim(preg_replace('/\s+/', ' ', $query));
        if (!preg_match('/^FIND\s+facts?\b(.*)$/i', $q, $m)) {
            throw new InvalidArgumentException('FQL must start with "FIND fact"');
        }
        $rest = trim($m[1]);
        $limit = 100;
        $rank = null;
        if (preg_match('/\bLIMIT\s+(\d+)\s*$/i', $rest, $lm)) {
            $limit = max(1, min(100000, (int) $lm[1]));
            $rest = trim(substr($rest, 0, -strlen($lm[0])));
        }
        if (preg_match('/\bRANK\s+BY\s+(trust|score)\s*$/i', $rest, $rm)) {
            $rank = strtolower($rm[1]);
            $rest = trim(substr($rest, 0, -strlen($rm[0])));
        }
        $where = [];
        if ($rest !== '') {
            if (!preg_match('/^WHERE\s+(.+)$/i', $rest, $wm)) {
                throw new InvalidArgumentException('Expected WHERE, RANK BY or LIMIT near "' . $rest . '"');
            }
            foreach (self::splitAnd($wm[1]) as $clause) {
                $where[] = self::parseClause($clause);
            }
        }
        return new self($where, $rank, $limit);
    }

    /** @return array<int, string> */
    private static function splitAnd(string $s): array
    {
        $parts = [];
        $buf = '';
        $quote = false;
        $depth = 0;
        $len = strlen($s);
        for ($i = 0; $i < $len; $i++) {
            $c = $s[$i];
            if ($c === '"') {
                $quote = !$quote;
            } elseif (!$quote && $c === '[') {
                $depth++;
            } elseif (!$quote && $c === ']') {
                $depth--;
            } elseif (!$quote && $depth === 0 && strcasecmp(substr($s, $i, 5), ' AND ') === 0) {
                $parts[] = trim($buf);
                $buf = '';
                $i += 4;
                continue;
            }
            $buf .= $c;
        }
        $parts[] = trim($buf);
        return array_values(array_filter($parts, fn ($p) => $p !== ''));
    }

    /** @return array{field:string, op:string, value:mixed} */
    private static function parseClause(string $c): array
    {
        $c = trim($c, " ()");
        if (!preg_match('/^([a-z_]+)\s*(>=|<=|!=|=|>|<|~|\bIN\b)\s*(.+)$/i', $c, $m)) {
            throw new InvalidArgumentException('Cannot parse condition "' . $c . '"');
        }
        $field = strtolower($m[1]);
        if (!in_array($field, self::FIELDS, true)) {
            throw new InvalidArgumentException('Unknown field "' . $field . '" (allowed: ' . implode(', ', self::FIELDS) . ')');
        }
        $op = strtoupper($m[2]);
        $raw = trim($m[3]);
        if ($op === 'IN') {
            if (!preg_match('/^\[(.*)\]$/', $raw, $lm)) {
                throw new InvalidArgumentException('IN needs a [list]');
            }
            preg_match_all('/"([^"]*)"|([^,\s][^,]*)/', $lm[1], $items, PREG_SET_ORDER);
            $value = array_map(fn ($it) => isset($it[2]) && $it[2] !== '' ? trim($it[2]) : $it[1], $items);
        } elseif (preg_match('/^"(.*)"$/', $raw, $sm)) {
            $value = $sm[1];
        } elseif (is_numeric($raw)) {
            $value = (float) $raw;
        } else {
            $value = $raw;
        }
        if (in_array($field, self::NUMERIC, true) && !is_float($value)) {
            throw new InvalidArgumentException($field . ' compares against a number');
        }
        return ['field' => $field, 'op' => $op, 'value' => $value];
    }

    /** Canonical rendering — sent in the meta of the answer frame. */
    public function render(): string
    {
        $w = [];
        foreach ($this->where as $c) {
            $v = $c['value'];
            if (is_array($v)) {
                $v = '[' . implode(', ', $v) . ']';
            } elseif (is_float($v)) {
                $v = rtrim(rtrim(sprintf('%.6F', $v), '0'), '.');
            } else {
                $v = '"' . $v . '"';
            }
            $w[] = $c['field'] . ' ' . $c['op'] . ' ' . $v;
        }
        return 'FIND fact' . ($w ? ' WHERE ' . implode(' AND ', $w) : '')
            . ($this->rankBy ? ' RANK BY ' . $this->rankBy : '') . ' LIMIT ' . $this->limit;
    }

    /**
     * @param array<int, array<string, mixed>> $facts
     * @return array<int, array<string, mixed>>
     */
    public function execute(array $facts): array
    {
        $hits = array_values(array_filter($facts, fn ($r) => $this->matches($r)));
        if ($this->rankBy !== null) {
            usort($hits, fn ($a, $b) => [self::field($b, $this->rankBy), $a['fuid'] ?? ''] <=> [self::field($a, $this->rankBy), $b['fuid'] ?? '']);
        } else {
            usort($hits, fn ($a, $b) => strcmp((string) ($a['fuid'] ?? ''), (string) ($b['fuid'] ?? '')));
        }
        return array_slice($hits, 0, $this->limit);
    }

    public function matches(array $r): bool
    {
        foreach ($this->where as $c) {
            if (!$this->test($r, $c)) {
                return false;
            }
        }
        return true;
    }

    private function test(array $r, array $c): bool
    {
        if ($c['field'] === 'entity') {
            return $this->compare(self::field($r, 'subject'), $c) || $this->compare(self::field($r, 'object'), $c);
        }
        if ($c['field'] === 'text') {
            $hay = Ufcs::norm(self::field($r, 'subject') . ' ' . self::field($r, 'predicate') . ' ' . self::field($r, 'object'));
            $needle = Ufcs::norm(is_array($c['value']) ? implode(' ', $c['value']) : $c['value']);
            return $c['op'] === '!=' ? !str_contains($hay, $needle) : str_contains($hay, $needle);
        }
        return $this->compare(self::field($r, $c['field']), $c);
    }

    private function compare(mixed $actual, array $c): bool
    {
        $v = $c['value'];
        if (is_float($v) && $c['op'] !== '~') {
            $a = (float) $actual;
            return match ($c['op']) {
                '=' => abs($a - $v) < 1e-9, '!=' => abs($a - $v) >= 1e-9,
                '>' => $a > $v, '>=' => $a >= $v, '<' => $a < $v, '<=' => $a <= $v,
                default => false,
            };
        }
        $a = Ufcs::norm($actual);
        return match ($c['op']) {
            '=' => $a === Ufcs::norm($v),
            '!=' => $a !== Ufcs::norm($v),
            'IN' => in_array($a, array_map([Ufcs::class, 'norm'], (array) $v), true),
            '~' => str_contains($a, Ufcs::norm($v)),
            default => false,
        };
    }

    private static function field(array $r, string $f): mixed
    {
        return match ($f) {
            'subject', 'predicate', 'object' => $r['nucleus'][$f] ?? '',
            'trust' => (float) ($r['certification']['trust_score'] ?? 0),
            'score' => (float) ($r['confidence']['score'] ?? 0),
            'source' => $r['sources'][0]['class'] ?? '',
            default => $r[$f] ?? '',
        };
    }
}
