<?php

declare(strict_types=1);

/**
 * Stock media graph — command line.
 *
 *   php bin/media-graph.php harvest <source|all> "<query>" [--limit=20]
 *   php bin/media-graph.php import <manifest.json> [--source=name]
 *   php bin/media-graph.php sample
 *   php bin/media-graph.php query "<FQL>" [--json]
 *   php bin/media-graph.php querybook [name]
 *   php bin/media-graph.php stats
 *   php bin/media-graph.php clear --yes
 *
 * Every command accepts --dir=<path> to use a graph other than media-graph/.
 * Sources: wikimedia, archive, nasa (no key), pexels (PEXELS_API_KEY),
 * pixabay (PIXABAY_API_KEY). Only metadata is fetched — never the footage.
 */

require_once __DIR__ . '/../StockMediaHarvester.php';
require_once __DIR__ . '/../MediaAnalyzer.php';
require_once __DIR__ . '/../QueryBook.php';

$args = [];
$options = [];
foreach (array_slice($argv, 1) as $arg) {
    if (preg_match('/^--([a-z]+)(?:=(.*))?$/', $arg, $m)) {
        $options[$m[1]] = $m[2] ?? true;
    } else {
        $args[] = $arg;
    }
}
$command = $args[0] ?? 'help';

$store = new MediaGraphStore(isset($options['dir']) ? (string) $options['dir'] : null);
$engine = new FqlEngine($store);
$harvester = new StockMediaHarvester();
$analyzer = new MediaAnalyzer();

$printTable = static function (array $result): void {
    $rows = array_merge([$result['columns']], $result['rows']);
    $widths = [];
    foreach ($rows as $row) {
        foreach (array_values($row) as $i => $value) {
            $widths[$i] = min(70, max($widths[$i] ?? 0, mb_strlen((string) $value)));
        }
    }
    foreach ($rows as $n => $row) {
        $cells = [];
        foreach (array_values($row) as $i => $value) {
            $value = (string) $value;
            $value = mb_strlen($value) > 70 ? mb_substr($value, 0, 69) . '…' : $value;
            $cells[] = $value . str_repeat(' ', $widths[$i] - mb_strlen($value));
        }
        fwrite(STDOUT, implode('  ', $cells) . "\n");
        if ($n === 0) {
            fwrite(STDOUT, implode('  ', array_map(static fn (int $w): string => str_repeat('-', $w), $widths)) . "\n");
        }
    }
    fwrite(STDOUT, '(' . $result['total'] . ' result' . ($result['total'] === 1 ? '' : 's') . (count($result['rows']) < $result['total'] ? ', showing ' . count($result['rows']) : '') . ")\n");
};

try {
    switch ($command) {
        case 'harvest':
            $source = (string) ($args[1] ?? '');
            $query = (string) ($args[2] ?? '');
            $sources = $source === 'all' ? array_keys(StockMediaHarvester::SOURCES) : [$source];
            $total = 0;
            foreach ($sources as $name) {
                if ($source === 'all' && !$harvester->available($name)) {
                    fwrite(STDOUT, "skip {$name}: no API key\n");
                    continue;
                }
                $result = $harvester->harvest($name, $query, (int) ($options['limit'] ?? 20));
                if ($result['error'] !== null) {
                    fwrite(STDERR, $result['error'] . "\n");
                }
                $count = count($analyzer->ingest($store, $result['records']));
                $total += $count;
                fwrite(STDOUT, "{$name}: indexed {$count} videos\n");
            }
            $store->save();
            fwrite(STDOUT, "Graph now holds {$store->count()} facts ({$total} videos indexed this run).\n");
            break;

        case 'import':
        case 'sample':
            $file = $command === 'sample' ? __DIR__ . '/../data/sample-media.json' : (string) ($args[1] ?? '');
            $manifest = is_file($file) ? json_decode((string) file_get_contents($file), true) : null;
            if (!is_array($manifest)) {
                throw new InvalidArgumentException('Could not read a JSON manifest from: ' . $file);
            }
            $name = $command === 'sample' ? 'sample' : (string) ($options['source'] ?? 'manifest');
            $count = count($analyzer->ingest($store, $harvester->importManifest($manifest, $name)));
            $store->save();
            fwrite(STDOUT, "Imported {$count} videos. Graph now holds {$store->count()} facts.\n");
            break;

        case 'query':
            $result = $engine->run((string) ($args[1] ?? ''));
            if (isset($options['json'])) {
                fwrite(STDOUT, json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
            } else {
                $printTable($result);
            }
            break;

        case 'querybook':
            $book = new QueryBook($engine);
            foreach ($book->run($book->load((string) ($args[1] ?? QueryBook::STARTER))) as $entry) {
                fwrite(STDOUT, "\n## {$entry['cell']['title']}\n{$entry['cell']['fql']}\n");
                if ($entry['error'] !== null) {
                    fwrite(STDOUT, 'ERROR: ' . $entry['error'] . "\n");
                } else {
                    $printTable(['rows' => array_slice($entry['result']['rows'], 0, 15)] + $entry['result']);
                }
            }
            break;

        case 'stats':
            $printTable($engine->stats());
            break;

        case 'clear':
            if (!isset($options['yes'])) {
                throw new InvalidArgumentException('Refusing to clear the graph without --yes.');
            }
            $store->clear();
            fwrite(STDOUT, "Graph cleared.\n");
            break;

        default:
            fwrite(STDOUT, "Usage:\n"
                . "  php bin/media-graph.php harvest <wikimedia|archive|nasa|pexels|pixabay|all> \"<query>\" [--limit=20]\n"
                . "  php bin/media-graph.php import <manifest.json> [--source=name]\n"
                . "  php bin/media-graph.php sample\n"
                . "  php bin/media-graph.php query \"<FQL>\" [--json]\n"
                . "  php bin/media-graph.php querybook [name]\n"
                . "  php bin/media-graph.php stats\n"
                . "  php bin/media-graph.php clear --yes\n"
                . "Options: --dir=<graph directory>\n");
    }
} catch (Throwable $e) {
    fwrite(STDERR, 'Error: ' . $e->getMessage() . "\n");
    exit(1);
}
