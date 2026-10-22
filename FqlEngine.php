<?php

declare(strict_types=1);

require_once __DIR__ . '/MediaGraphStore.php';

/**
 * FQL — the Fact Query Language for the media graph
 *
 * A small, readable pattern language over UFCS facts:
 *
 *   SELECT ?v ?title
 *   WHERE ?v supports use:lip_reading AND ?v resolution_class res:4K AND ?v title ?title
 *   FILTER ?title CONTAINS "interview"
 *   ORDER BY ?title ASC
 *   LIMIT 20
 *
 *   COUNT ?v BY ?origin WHERE ?v is_a Video AND ?v origin ?origin
 *   DESCRIBE video:pexels:12345
 *   NEIGHBORS concept:weather/rain DEPTH 2
 *   STATS
 *
 * Terms: `?name` is a variable, `"text"` a literal string, a bare number a
 * numeric literal, anything else a node id. FILTER operators: = != > < >=
 * <= CONTAINS (case-insensitive). Patterns are joined greedily — the most
 * constrained pattern runs first — and results are distinct.
 */
final class FqlEngine
{
    private const MAX_SOLUTIONS = 250000;
    private const KEYWORDS = ['SELECT', 'COUNT', 'BY', 'WHERE', 'AND', 'FILTER', 'ORDER', 'ASC', 'DESC', 'LIMIT', 'DESCRIBE', 'NEIGHBORS', 'DEPTH', 'STATS', 'CONTAINS'];

    public function __construct(private MediaGraphStore $store)
    {
    }

    public function store(): MediaGraphStore
    {
        return $this->store;
    }

    /**
     * Parse and run one FQL statement.
     *
     * @return array{kind: string, columns: array<int, string>, rows: array<int, array<int, string>>, total: int, truncated: bool}
     */
    public function run(string $fql): array
    {
        return $this->execute($this->parse($fql));
    }

    /**
     * @return array<string, mixed> The statement AST.
     */
    public function parse(string $fql): array
    {
        $tokens = $this->tokenize($fql);
        if ($tokens === []) {
            throw new InvalidArgumentException('Empty FQL statement.');
        }
        $pos = 0;
        $head = $this->upper($tokens[0]);
        if ($head === 'STATS') {
            $this->expectEnd($tokens, 1);
            return ['kind' => 'stats'];
        }
        if ($head === 'DESCRIBE') {
            $node = $this->nodeArg($tokens, 1, 'DESCRIBE');
            $this->expectEnd($tokens, 2);
            return ['kind' => 'describe', 'node' => $node];
        }
        if ($head === 'NEIGHBORS') {
            $node = $this->nodeArg($tokens, 1, 'NEIGHBORS');
            $pos = 2;
            $depth = 1;
            $limit = 200;
            while ($pos < count($tokens)) {
                $kw = $this->upper($tokens[$pos]);
                if ($kw === 'DEPTH' || $kw === 'LIMIT') {
                    $value = $this->intArg($tokens, $pos + 1, $kw);
                    $kw === 'DEPTH' ? $depth = max(1, min(3, $value)) : $limit = max(1, min(2000, $value));
                    $pos += 2;
                    continue;
                }
                throw new InvalidArgumentException('Unexpected "' . $tokens[$pos]['v'] . '" after NEIGHBORS.');
            }
            return ['kind' => 'neighbors', 'node' => $node, 'depth' => $depth, 'limit' => $limit];
        }

        $ast = ['kind' => 'select', 'vars' => [], 'count' => null, 'by' => null, 'patterns' => [], 'filters' => [], 'order' => null, 'limit' => 100];
        if ($head === 'SELECT') {
            $pos = 1;
            while ($pos < count($tokens) && $tokens[$pos]['t'] === 'var') {
                $ast['vars'][] = $tokens[$pos]['v'];
                $pos++;
            }
            if ($ast['vars'] === []) {
                throw new InvalidArgumentException('SELECT needs at least one ?variable.');
            }
        } elseif ($head === 'COUNT') {
            $ast['kind'] = 'count';
            $pos = 1;
            if (($tokens[$pos]['t'] ?? '') === 'var') {
                $ast['count'] = $tokens[$pos]['v'];
                $pos++;
            }
            if ($this->upper($tokens[$pos] ?? null) === 'BY') {
                if (($tokens[$pos + 1]['t'] ?? '') !== 'var') {
                    throw new InvalidArgumentException('COUNT … BY needs a ?variable.');
                }
                $ast['by'] = $tokens[$pos + 1]['v'];
                $pos += 2;
            }
        } else {
            throw new InvalidArgumentException('FQL statements start with SELECT, COUNT, DESCRIBE, NEIGHBORS or STATS.');
        }

        if ($this->upper($tokens[$pos] ?? null) !== 'WHERE') {
            throw new InvalidArgumentException('Expected WHERE followed by patterns like: ?v is_a Video');
        }
        $pos++;
        while (true) {
            $triple = [];
            for ($i = 0; $i < 3; $i++) {
                $token = $tokens[$pos] ?? null;
                if ($token === null || $token['t'] === 'kw' || $token['t'] === 'op') {
                    throw new InvalidArgumentException('Each WHERE pattern needs three terms: subject predicate object.');
                }
                $triple[] = $token;
                $pos++;
            }
            if ($triple[0]['t'] === 'lit' || $triple[0]['t'] === 'num' || $triple[1]['t'] === 'lit' || $triple[1]['t'] === 'num') {
                throw new InvalidArgumentException('Only the object of a pattern may be a literal.');
            }
            $ast['patterns'][] = $triple;
            if ($this->upper($tokens[$pos] ?? null) !== 'AND') {
                break;
            }
            $pos++;
        }

        if ($this->upper($tokens[$pos] ?? null) === 'FILTER') {
            $pos++;
            while (true) {
                $var = $tokens[$pos] ?? null;
                $op = $tokens[$pos + 1] ?? null;
                $value = $tokens[$pos + 2] ?? null;
                if ($var === null || $var['t'] !== 'var' || $op === null || !($op['t'] === 'op' || $this->upper($op) === 'CONTAINS') || $value === null || $value['t'] === 'kw' || $value['t'] === 'var') {
                    throw new InvalidArgumentException('FILTER conditions look like: ?duration > 10 or ?title CONTAINS "rain"');
                }
                $ast['filters'][] = ['var' => $var['v'], 'op' => $this->upper($op) === 'CONTAINS' ? 'CONTAINS' : $op['v'], 'value' => $value];
                $pos += 3;
                if ($this->upper($tokens[$pos] ?? null) !== 'AND') {
                    break;
                }
                $pos++;
            }
        }

        if ($this->upper($tokens[$pos] ?? null) === 'ORDER') {
            if ($this->upper($tokens[$pos + 1] ?? null) !== 'BY' || ($tokens[$pos + 2]['t'] ?? '') !== 'var') {
                throw new InvalidArgumentException('ORDER BY needs a ?variable.');
            }
            $ast['order'] = ['var' => $tokens[$pos + 2]['v'], 'desc' => false];
            $pos += 3;
            $dir = $this->upper($tokens[$pos] ?? null);
            if ($dir === 'ASC' || $dir === 'DESC') {
                $ast['order']['desc'] = $dir === 'DESC';
                $pos++;
            }
        }

        if ($this->upper($tokens[$pos] ?? null) === 'LIMIT') {
            $ast['limit'] = max(1, min(10000, $this->intArg($tokens, $pos + 1, 'LIMIT')));
            $pos += 2;
        }
        $this->expectEnd($tokens, $pos);

        $bound = [];
        foreach ($ast['patterns'] as $triple) {
            foreach ($triple as $term) {
                if ($term['t'] === 'var') {
                    $bound[$term['v']] = true;
                }
            }
        }
        foreach (array_merge($ast['vars'], array_filter([$ast['count'], $ast['by'], $ast['order']['var'] ?? null]), array_column($ast['filters'], 'var')) as $var) {
            if (!isset($bound[$var])) {
                throw new InvalidArgumentException('Variable ' . $var . ' is not used in any WHERE pattern.');
            }
        }
        return $ast;
    }

    /**
     * @param array<string, mixed> $ast
     * @return array{kind: string, columns: array<int, string>, rows: array<int, array<int, string>>, total: int, truncated: bool}
     */
    public function execute(array $ast): array
    {
        return match ($ast['kind']) {
            'stats' => $this->stats(),
            'describe' => $this->describe((string) $ast['node']),
            'neighbors' => $this->neighbors((string) $ast['node'], (int) $ast['depth'], (int) $ast['limit']),
            default => $this->solve($ast),
        };
    }

    /**
     * Graph-wide counts: facts, vertices, videos, and breakdowns by source,
     * resolution, origin, domain and learning use.
     *
     * @return array{kind: string, columns: array<int, string>, rows: array<int, array<int, string>>, total: int, truncated: bool, breakdowns: array<string, array<string, int>>}
     */
    public function stats(): array
    {
        $videos = array_column($this->store->match(null, 'is_a', 'Video', MediaGraphStore::NODE), 's');
        $breakdowns = [];
        foreach (['source' => 'from_source', 'resolution' => 'resolution_class', 'origin' => 'origin', 'use' => 'supports', 'shot' => 'shot'] as $label => $predicate) {
            $breakdowns[$label] = $this->tally($this->store->match(null, $predicate), 'o');
        }
        $domains = [];
        foreach ($this->store->match(null, 'depicts') as $fact) {
            $domain = explode('/', substr($fact['o'], 8))[0];
            $domains['domain:' . $domain][$fact['s']] = true;
        }
        $breakdowns['domain'] = array_map('count', $domains);
        arsort($breakdowns['domain']);
        $rows = [
            ['facts', (string) $this->store->count()],
            ['vertices (subjects)', (string) $this->store->subjectCount()],
            ['videos', (string) count($videos)],
            ['concepts', (string) count($this->store->match(null, 'is_a', 'Concept', MediaGraphStore::NODE))],
            ['creators', (string) count($this->store->match(null, 'is_a', 'Creator', MediaGraphStore::NODE))],
            ['tags', (string) count(array_unique(array_column($this->store->match(null, 'has_tag'), 'o')))],
        ];
        foreach ($breakdowns as $label => $counts) {
            foreach ($counts as $key => $count) {
                $rows[] = [$label . ' ' . $key, (string) $count];
            }
        }
        return ['kind' => 'stats', 'columns' => ['measure', 'value'], 'rows' => $rows, 'total' => count($rows), 'truncated' => false, 'breakdowns' => $breakdowns];
    }

    /** @return array{kind: string, columns: array<int, string>, rows: array<int, array<int, string>>, total: int, truncated: bool} */
    private function describe(string $node): array
    {
        $rows = [];
        foreach ($this->sortFacts($this->store->match($node)) as $fact) {
            $rows[] = ['→', $fact['p'], $fact['o'], $fact['k'] === MediaGraphStore::NODE ? 'node' : 'literal'];
        }
        $incoming = $this->sortFacts($this->store->match(null, null, $node, MediaGraphStore::NODE));
        foreach (array_slice($incoming, 0, 200) as $fact) {
            $rows[] = ['←', $fact['p'], $fact['s'], 'node'];
        }
        return ['kind' => 'describe', 'columns' => ['dir', 'predicate', 'value', 'type'], 'rows' => $rows, 'total' => count($rows) + max(0, count($incoming) - 200), 'truncated' => count($incoming) > 200];
    }

    /** @return array{kind: string, columns: array<int, string>, rows: array<int, array<int, string>>, total: int, truncated: bool} */
    private function neighbors(string $node, int $depth, int $limit): array
    {
        $seen = [$node => true];
        $frontier = [$node];
        $edges = [];
        for ($level = 1; $level <= $depth && $frontier !== []; $level++) {
            $next = [];
            foreach ($frontier as $vertex) {
                $facts = array_merge(
                    $this->store->match($vertex, null, null, MediaGraphStore::NODE),
                    $this->store->match(null, null, $vertex, MediaGraphStore::NODE),
                );
                foreach ($this->sortFacts($facts) as $fact) {
                    $edges[$fact['s'] . "\x1f" . $fact['p'] . "\x1f" . $fact['o']] = [$fact['s'], $fact['p'], $fact['o'], (string) $level];
                    $other = $fact['s'] === $vertex ? $fact['o'] : $fact['s'];
                    if (!isset($seen[$other])) {
                        $seen[$other] = true;
                        $next[] = $other;
                    }
                }
            }
            $frontier = $next;
        }
        $rows = array_values($edges);
        return ['kind' => 'neighbors', 'columns' => ['from', 'predicate', 'to', 'hop'], 'rows' => array_slice($rows, 0, $limit), 'total' => count($rows), 'truncated' => count($rows) > $limit];
    }

    /**
     * @param array<string, mixed> $ast
     * @return array{kind: string, columns: array<int, string>, rows: array<int, array<int, string>>, total: int, truncated: bool}
     */
    private function solve(array $ast): array
    {
        $solutions = [[]];
        $remaining = $ast['patterns'];
        $filters = $ast['filters'];
        while ($remaining !== []) {
            $index = $this->mostConstrained($remaining, array_keys($solutions[0] ?? []));
            $pattern = $remaining[$index];
            unset($remaining[$index]);
            $next = [];
            foreach ($solutions as $binding) {
                foreach ($this->matchPattern($pattern, $binding) as $extended) {
                    $next[] = $extended;
                    if (count($next) > self::MAX_SOLUTIONS) {
                        throw new RuntimeException('The query matches too many combinations; add a more specific pattern or a FILTER.');
                    }
                }
            }
            $solutions = $next;
            if ($solutions === []) {
                break;
            }
            // Apply every filter whose variable is now bound — prune early.
            foreach ($filters as $i => $filter) {
                if (array_key_exists($filter['var'], $solutions[0])) {
                    $solutions = array_values(array_filter($solutions, fn (array $b): bool => $this->passes($b[$filter['var']], $filter)));
                    unset($filters[$i]);
                }
            }
        }

        if ($ast['kind'] === 'count') {
            return $this->countRows($ast, $solutions);
        }

        $rows = [];
        foreach ($solutions as $binding) {
            $row = array_map(static fn (string $var): string => $binding[$var]['v'], $ast['vars']);
            $rows[implode("\x1f", $row)] = ['row' => $row, 'sort' => $ast['order'] !== null ? $binding[$ast['order']['var']]['v'] : null];
        }
        $rows = array_values($rows);
        if ($ast['order'] !== null) {
            $desc = $ast['order']['desc'];
            usort($rows, static function (array $a, array $b) use ($desc): int {
                $cmp = is_numeric($a['sort']) && is_numeric($b['sort']) ? (float) $a['sort'] <=> (float) $b['sort'] : strcmp((string) $a['sort'], (string) $b['sort']);
                $cmp = $desc ? -$cmp : $cmp;
                return $cmp !== 0 ? $cmp : $a['row'] <=> $b['row'];
            });
        } else {
            usort($rows, static fn (array $a, array $b): int => $a['row'] <=> $b['row']);
        }
        $total = count($rows);
        return [
            'kind' => 'select',
            'columns' => $ast['vars'],
            'rows' => array_map(static fn (array $r): array => $r['row'], array_slice($rows, 0, $ast['limit'])),
            'total' => $total,
            'truncated' => $total > $ast['limit'],
        ];
    }

    /**
     * @param array<string, mixed> $ast
     * @param array<int, array<string, array{v: string, k: string}>> $solutions
     * @return array{kind: string, columns: array<int, string>, rows: array<int, array<int, string>>, total: int, truncated: bool}
     */
    private function countRows(array $ast, array $solutions): array
    {
        $groups = [];
        foreach ($solutions as $i => $binding) {
            $group = $ast['by'] !== null ? $binding[$ast['by']]['v'] : '';
            $member = $ast['count'] !== null ? $binding[$ast['count']]['v'] : (string) $i;
            $groups[$group][$member] = true;
        }
        $counts = array_map('count', $groups);
        if ($ast['by'] === null) {
            return ['kind' => 'count', 'columns' => ['count'], 'rows' => [[(string) ($counts[''] ?? 0)]], 'total' => 1, 'truncated' => false];
        }
        uksort($counts, static fn ($a, $b): int => [$counts[$b], (string) $a] <=> [$counts[$a], (string) $b]);
        $rows = [];
        foreach ($counts as $group => $count) {
            $rows[] = [(string) $group, (string) $count];
        }
        $total = count($rows);
        return ['kind' => 'count', 'columns' => [$ast['by'], 'count'], 'rows' => array_slice($rows, 0, $ast['limit']), 'total' => $total, 'truncated' => $total > $ast['limit']];
    }

    /**
     * @param array<int, array{t: string, v: string}> $pattern
     * @param array<string, array{v: string, k: string}> $binding
     * @return array<int, array<string, array{v: string, k: string}>>
     */
    private function matchPattern(array $pattern, array $binding): array
    {
        [$s, $p, $o] = $pattern;
        $subject = $this->resolve($s, $binding);
        $predicate = $this->resolve($p, $binding);
        $object = $this->resolve($o, $binding);
        // A literal bound into subject/predicate position can never match.
        if (($subject !== null && $subject['k'] !== MediaGraphStore::NODE) || ($predicate !== null && $predicate['k'] !== MediaGraphStore::NODE)) {
            return [];
        }
        $out = [];
        foreach ($this->store->match($subject['v'] ?? null, $predicate['v'] ?? null, $object['v'] ?? null, $object['k'] ?? null) as $fact) {
            $extended = $binding;
            foreach ([[$s, $fact['s'], MediaGraphStore::NODE], [$p, $fact['p'], MediaGraphStore::NODE], [$o, $fact['o'], $fact['k']]] as [$term, $value, $kind]) {
                if ($term['t'] !== 'var') {
                    continue;
                }
                if (isset($extended[$term['v']]) && ($extended[$term['v']]['v'] !== $value || $extended[$term['v']]['k'] !== $kind)) {
                    continue 2; // the same variable twice in one pattern must agree
                }
                $extended[$term['v']] = ['v' => $value, 'k' => $kind];
            }
            $out[] = $extended;
        }
        return $out;
    }

    /**
     * @param array{t: string, v: string} $term
     * @param array<string, array{v: string, k: string}> $binding
     * @return array{v: string, k: string}|null
     */
    private function resolve(array $term, array $binding): ?array
    {
        return match ($term['t']) {
            'var' => $binding[$term['v']] ?? null,
            'lit' => ['v' => $term['v'], 'k' => MediaGraphStore::LITERAL],
            'num' => ['v' => MediaGraphStore::number($term['v']), 'k' => MediaGraphStore::LITERAL],
            default => ['v' => $term['v'], 'k' => MediaGraphStore::NODE],
        };
    }

    /**
     * @param array<int, array<int, array{t: string, v: string}>> $patterns
     * @param array<int, string> $boundVars
     */
    private function mostConstrained(array $patterns, array $boundVars): int
    {
        $best = null;
        $bestScore = -1;
        foreach ($patterns as $i => $pattern) {
            $score = 0;
            $connected = false;
            foreach ($pattern as $position => $term) {
                $fixed = $term['t'] !== 'var' || in_array($term['v'], $boundVars, true);
                if ($fixed) {
                    // A fixed subject or object narrows far more than a fixed predicate.
                    $score += $position === 1 ? 1 : 3;
                }
                $connected = $connected || ($term['t'] === 'var' && in_array($term['v'], $boundVars, true));
            }
            if ($boundVars !== [] && $connected) {
                $score += 10;
            }
            if ($score > $bestScore) {
                $best = $i;
                $bestScore = $score;
            }
        }
        return (int) $best;
    }

    /**
     * @param array{v: string, k: string} $bound
     * @param array{var: string, op: string, value: array{t: string, v: string}} $filter
     */
    private function passes(array $bound, array $filter): bool
    {
        $left = $bound['v'];
        $right = $filter['value']['v'];
        if ($filter['op'] === 'CONTAINS') {
            return stripos($left, $right) !== false;
        }
        $numeric = is_numeric($left) && is_numeric($right);
        $cmp = $numeric ? (float) $left <=> (float) $right : strcmp($left, $right);
        return match ($filter['op']) {
            '=' => $cmp === 0,
            '!=' => $cmp !== 0,
            '>' => $cmp > 0,
            '<' => $cmp < 0,
            '>=' => $cmp >= 0,
            '<=' => $cmp <= 0,
            default => false,
        };
    }

    /** @return array<int, array{t: string, v: string}> */
    private function tokenize(string $fql): array
    {
        if (strlen($fql) > 4000) {
            throw new InvalidArgumentException('FQL statements are limited to 4,000 characters.');
        }
        preg_match_all('/\s*(?:("(?:[^"\\\\]|\\\\.)*")|(>=|<=|!=|=|>|<)|(\S+))/u', $fql, $matches, PREG_SET_ORDER);
        $tokens = [];
        foreach ($matches as $m) {
            if (($m[1] ?? '') !== '') {
                $tokens[] = ['t' => 'lit', 'v' => stripcslashes(substr($m[1], 1, -1))];
            } elseif (($m[2] ?? '') !== '') {
                $tokens[] = ['t' => 'op', 'v' => $m[2]];
            } elseif (($m[3] ?? '') !== '') {
                $word = $m[3];
                if ($word[0] === '"') {
                    throw new InvalidArgumentException('Unterminated string literal.');
                }
                if ($word[0] === '?') {
                    if (!preg_match('/^\?[A-Za-z_][A-Za-z0-9_]*$/', $word)) {
                        throw new InvalidArgumentException('Invalid variable name: ' . $word);
                    }
                    $tokens[] = ['t' => 'var', 'v' => $word];
                } elseif (is_numeric($word)) {
                    $tokens[] = ['t' => 'num', 'v' => $word];
                } elseif (in_array(strtoupper($word), self::KEYWORDS, true)) {
                    $tokens[] = ['t' => 'kw', 'v' => strtoupper($word)];
                } else {
                    $tokens[] = ['t' => 'node', 'v' => $word];
                }
            }
        }
        return $tokens;
    }

    /** @param array{t: string, v: string}|null $token */
    private function upper(?array $token): string
    {
        return $token !== null && $token['t'] === 'kw' ? $token['v'] : '';
    }

    /** @param array<int, array{t: string, v: string}> $tokens */
    private function nodeArg(array $tokens, int $pos, string $keyword): string
    {
        if (($tokens[$pos]['t'] ?? '') !== 'node') {
            throw new InvalidArgumentException($keyword . ' needs a node id, e.g. ' . $keyword . ' concept:weather/rain');
        }
        return $tokens[$pos]['v'];
    }

    /** @param array<int, array{t: string, v: string}> $tokens */
    private function intArg(array $tokens, int $pos, string $keyword): int
    {
        if (($tokens[$pos]['t'] ?? '') !== 'num') {
            throw new InvalidArgumentException($keyword . ' needs a number.');
        }
        return (int) $tokens[$pos]['v'];
    }

    /** @param array<int, array{t: string, v: string}> $tokens */
    private function expectEnd(array $tokens, int $pos): void
    {
        if ($pos < count($tokens)) {
            throw new InvalidArgumentException('Unexpected "' . $tokens[$pos]['v'] . '".');
        }
    }

    /**
     * @param array<int, array{s: string, p: string, o: string, k: string}> $facts
     * @return array<string, int>
     */
    private function tally(array $facts, string $field): array
    {
        $counts = [];
        foreach ($facts as $fact) {
            $counts[$fact[$field]] = ($counts[$fact[$field]] ?? 0) + 1;
        }
        uksort($counts, static fn ($a, $b): int => [$counts[$b], (string) $a] <=> [$counts[$a], (string) $b]);
        return $counts;
    }

    /**
     * @param array<int, array{s: string, p: string, o: string, k: string}> $facts
     * @return array<int, array{s: string, p: string, o: string, k: string}>
     */
    private function sortFacts(array $facts): array
    {
        usort($facts, static fn (array $a, array $b): int => [$a['p'], $a['s'], $a['o']] <=> [$b['p'], $b['s'], $b['o']]);
        return $facts;
    }
}
