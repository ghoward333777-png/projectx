<?php

declare(strict_types=1);

require_once __DIR__ . '/FqlEngine.php';

/**
 * QueryBook — saved FQL notebooks over the media graph
 *
 * A QueryBook is an ordered list of cells (title, FQL statement, note).
 * Running a book executes every cell against the graph and returns each
 * result beside its question, so a research thread — "which 4K close-ups
 * of people talking could train lip reading?" — stays reproducible. Books
 * are plain JSON files under `media-graph/querybooks/`.
 *
 * The starter book maps the learning goals the graph is built for: lip
 * reading, language, culture and customs, places and fashion, world
 * objects, occupations, business, AI-generated versus camera footage, and
 * avatar-mill source material.
 */
final class QueryBook
{
    public const STARTER = 'starter';

    private string $dir;

    public function __construct(private FqlEngine $engine, ?string $dir = null)
    {
        $this->dir = $dir ?? $engine->store()->directory() . '/querybooks';
    }

    /** @return array<int, array{title: string, fql: string, note: string}> */
    public static function starterCells(): array
    {
        return [
            ['title' => 'Graph overview', 'fql' => 'COUNT ?v BY ?source WHERE ?v is_a Video AND ?v from_source ?source', 'note' => 'How many videos each free source contributed.'],
            ['title' => 'Coverage by domain', 'fql' => 'COUNT ?v BY ?domain WHERE ?v depicts ?c AND ?c broader ?domain', 'note' => 'What the stock world shows most — and least.'],
            ['title' => 'AI-generated vs camera footage', 'fql' => 'COUNT ?v BY ?origin WHERE ?v is_a Video AND ?v origin ?origin', 'note' => 'Origin as declared or detected from metadata.'],
            ['title' => 'AI generators in the graph', 'fql' => 'COUNT ?v BY ?gen WHERE ?v generated_with ?gen', 'note' => 'Which video models produced the AI footage.'],
            ['title' => 'Lip-reading training set', 'fql' => 'SELECT ?v ?title ?res WHERE ?v supports use:lip_reading AND ?v title ?title AND ?v resolution_class ?res ORDER BY ?title LIMIT 50', 'note' => 'Talking faces framed close enough (≥ 1280 px) to resolve mouth shapes.'],
            ['title' => 'Avatar-mill source faces', 'fql' => 'SELECT ?v ?title ?score WHERE ?v supports use:avatar_source AND ?v title ?title AND ?v quality_score ?score ORDER BY ?score DESC LIMIT 50', 'note' => 'Head, shoulder and waist-up people footage at Full HD or better.'],
            ['title' => 'Plain-background presenters', 'fql' => 'SELECT ?v ?title WHERE ?v background bg:plain AND ?v depicts concept:speech/presenter AND ?v title ?title', 'note' => 'Clean segmentation material for a background-free avatar.'],
            ['title' => 'Culture and customs', 'fql' => 'COUNT ?v BY ?c WHERE ?v supports use:culture_customs AND ?v depicts ?c AND ?c broader domain:culture', 'note' => 'Weddings, festivals, holidays, rituals as stock media sees them.'],
            ['title' => 'Weather in 4K or better', 'fql' => 'SELECT ?v ?title ?res WHERE ?v depicts ?c AND ?c broader domain:weather AND ?v title ?title AND ?v resolution_class ?res AND ?v width ?w FILTER ?w >= 3840 ORDER BY ?title', 'note' => 'High-resolution weather footage for world-object learning.'],
            ['title' => 'Occupations on camera', 'fql' => 'COUNT ?v BY ?c WHERE ?v depicts ?c AND ?c broader domain:occupations', 'note' => 'Which jobs stock libraries film — the basis for occupational-skill coverage.'],
            ['title' => 'Business and economics', 'fql' => 'SELECT ?v ?title WHERE ?v supports use:economics_business AND ?v title ?title ORDER BY ?title LIMIT 50', 'note' => 'Symbolic business imagery: meetings, markets, money.'],
            ['title' => 'Top creators', 'fql' => 'COUNT ?v BY ?creator WHERE ?v created_by ?creator LIMIT 20', 'note' => 'Whose eye shapes the stock world-view.'],
        ];
    }

    /** @return array<int, string> Saved book names (the starter is always available). */
    public function list(): array
    {
        $names = [self::STARTER];
        foreach (glob($this->dir . '/*.json') ?: [] as $file) {
            $name = basename($file, '.json');
            if ($name !== self::STARTER) {
                $names[] = $name;
            }
        }
        sort($names);
        return $names;
    }

    /** @return array<int, array{title: string, fql: string, note: string}> */
    public function load(string $name): array
    {
        $name = self::name($name);
        $file = $this->dir . '/' . $name . '.json';
        if (is_file($file)) {
            $cells = json_decode((string) file_get_contents($file), true);
            if (is_array($cells)) {
                return array_values(array_map(static fn (array $c): array => [
                    'title' => (string) ($c['title'] ?? ''),
                    'fql' => (string) ($c['fql'] ?? ''),
                    'note' => (string) ($c['note'] ?? ''),
                ], array_filter($cells, 'is_array')));
            }
        }
        return $name === self::STARTER ? self::starterCells() : [];
    }

    /** @param array<int, array{title: string, fql: string, note: string}> $cells */
    public function save(string $name, array $cells): string
    {
        $name = self::name($name);
        if (!is_dir($this->dir) && !@mkdir($this->dir, 0775, true) && !is_dir($this->dir)) {
            throw new RuntimeException('Could not create the QueryBook directory: ' . $this->dir);
        }
        file_put_contents($this->dir . '/' . $name . '.json', json_encode(array_values($cells), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
        return $name;
    }

    /** Append one cell to a book (a new book starts empty; the starter is copied first) and save it. */
    public function addCell(string $name, string $title, string $fql, string $note = ''): string
    {
        $this->engine->parse($fql); // refuse to save a statement that does not parse
        $cells = $this->load($name);
        $cells[] = ['title' => trim($title) !== '' ? trim($title) : 'Untitled query', 'fql' => trim($fql), 'note' => trim($note)];
        return $this->save($name, $cells);
    }

    /**
     * Run every cell. A failing cell reports its error without stopping the book.
     *
     * @param array<int, array{title: string, fql: string, note: string}> $cells
     * @return array<int, array{cell: array{title: string, fql: string, note: string}, result: ?array<string, mixed>, error: ?string}>
     */
    public function run(array $cells): array
    {
        $out = [];
        foreach ($cells as $cell) {
            try {
                $out[] = ['cell' => $cell, 'result' => $this->engine->run($cell['fql']), 'error' => null];
            } catch (Throwable $e) {
                $out[] = ['cell' => $cell, 'result' => null, 'error' => $e->getMessage()];
            }
        }
        return $out;
    }

    public static function name(string $name): string
    {
        $name = trim((string) preg_replace('/[^a-z0-9]+/', '-', strtolower($name)), '-');
        return $name === '' ? self::STARTER : substr($name, 0, 60);
    }
}
