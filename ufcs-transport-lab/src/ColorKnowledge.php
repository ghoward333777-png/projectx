<?php

declare(strict_types=1);

/**
 * Colour knowledge as UFCS Fact Units — what the Semantic Colorization
 * Engine (Registry F22 / F75) knows about how materials, scenes, eras and
 * lighting look in colour. Every colour the colorizer paints is resolved from
 * these facts by an FQL query, so each painted region carries the fact
 * (fuid), its source and its trust in the provenance manifest.
 *
 * Facts are ordinary UFCS records: they re-validate with the same semantic
 * fingerprint rule as the transport, and callers extend them with their own
 * (an archive's note that a car was red, a landmark's known colour).
 */
final class ColorKnowledge
{
    public const FILE = __DIR__ . '/../data/color_knowledge.jsonl';

    /** Sources and the trust each is certified at. */
    private const SOURCES = [
        'reference' => ['id' => 'SRC-COLORCHECKER', 'name' => 'ColorChecker Classic reference patches (sRGB, approximate)', 'class' => 'reference', 'trust' => 0.8],
        'curated' => ['id' => 'SRC-LAB-PALETTE', 'name' => 'Lab curated material palette', 'class' => 'curated', 'trust' => 0.6],
        'prior' => ['id' => 'SRC-LAB-PRIORS', 'name' => 'Lab curated scene, era and lighting priors', 'class' => 'curated', 'trust' => 0.55],
        'sensitive' => ['id' => 'SRC-LAB-NEUTRAL', 'name' => 'Deliberately low-trust neutral default', 'class' => 'curated', 'trust' => 0.3],
        'user' => ['id' => 'SRC-USER', 'name' => 'Supplied with the job', 'class' => 'user', 'trust' => 0.9],
    ];

    /**
     * The built-in knowledge, as [subject, predicate, object, source key].
     * Skin is deliberately low-trust: a grayscale frame carries no evidence of
     * a person's skin tone, so the engine withholds rather than guesses unless
     * the job supplies a fact (Registry F182).
     */
    public const BUILTIN = [
        // Material colours
        ['sky_clear', 'has_typical_color', '#627A9D', 'reference'],
        ['foliage', 'has_typical_color', '#576C43', 'reference'],
        ['skin', 'has_typical_color', '#9B7463', 'sensitive'],
        ['grass', 'has_typical_color', '#5E8C3A', 'curated'],
        ['water', 'has_typical_color', '#3B6E8F', 'curated'],
        ['sand', 'has_typical_color', '#C2B280', 'curated'],
        ['soil', 'has_typical_color', '#6B5240', 'curated'],
        ['stone', 'has_typical_color', '#8C8B86', 'curated'],
        ['brick', 'has_typical_color', '#9C4A3A', 'curated'],
        ['wood', 'has_typical_color', '#8B5A2B', 'curated'],
        ['metal', 'has_typical_color', '#9AA0A6', 'curated'],
        ['sky_overcast', 'has_typical_color', '#AEB8C2', 'curated'],
        ['sky_dusk', 'has_typical_color', '#E09A6A', 'curated'],
        // Scene priors: which materials a setting makes likely
        ['beach', 'implies_material', 'sand', 'prior'], ['beach', 'implies_material', 'water', 'prior'], ['beach', 'implies_material', 'sky_clear', 'prior'],
        ['forest', 'implies_material', 'foliage', 'prior'], ['forest', 'implies_material', 'grass', 'prior'], ['forest', 'implies_material', 'soil', 'prior'],
        ['countryside', 'implies_material', 'grass', 'prior'], ['countryside', 'implies_material', 'foliage', 'prior'], ['countryside', 'implies_material', 'sky_clear', 'prior'], ['countryside', 'implies_material', 'soil', 'prior'],
        ['lake', 'implies_material', 'water', 'prior'], ['lake', 'implies_material', 'foliage', 'prior'], ['lake', 'implies_material', 'sky_clear', 'prior'], ['lake', 'implies_material', 'grass', 'prior'],
        ['city', 'implies_material', 'stone', 'prior'], ['city', 'implies_material', 'brick', 'prior'], ['city', 'implies_material', 'metal', 'prior'], ['city', 'implies_material', 'sky_clear', 'prior'],
        ['harbour', 'implies_material', 'water', 'prior'], ['harbour', 'implies_material', 'metal', 'prior'], ['harbour', 'implies_material', 'stone', 'prior'], ['harbour', 'implies_material', 'sky_clear', 'prior'],
        ['desert', 'implies_material', 'sand', 'prior'], ['desert', 'implies_material', 'sky_clear', 'prior'], ['desert', 'implies_material', 'stone', 'prior'],
        ['interior', 'implies_material', 'wood', 'prior'], ['interior', 'implies_material', 'metal', 'prior'],
        ['people', 'implies_material', 'skin', 'prior'],
        // Historical priors (film stock and grading of the period)
        ['era:1920s', 'has_grade', 'saturation=0.55;warmth=0.06', 'prior'],
        ['era:1930s', 'has_grade', 'saturation=0.70;warmth=0.05', 'prior'],
        ['era:1940s', 'has_grade', 'saturation=0.85;warmth=0.03', 'prior'],
        ['era:1950s', 'has_grade', 'saturation=1.20;warmth=0.03', 'prior'],
        ['era:1960s', 'has_grade', 'saturation=1.10;warmth=0.02', 'prior'],
        ['era:1970s', 'has_grade', 'saturation=0.95;warmth=0.06', 'prior'],
        ['era:1980s', 'has_grade', 'saturation=1.05;warmth=0.01', 'prior'],
        ['era:modern', 'has_grade', 'saturation=1.00;warmth=0.00', 'prior'],
        // Lighting
        ['golden_hour', 'has_grade', 'saturation=1.10;warmth=0.08', 'prior'],
        ['midday', 'has_grade', 'saturation=1.00;warmth=0.00', 'prior'],
        ['overcast', 'has_grade', 'saturation=0.85;warmth=-0.02', 'prior'],
        ['night', 'has_grade', 'saturation=0.60;warmth=-0.05', 'prior'],
        ['tungsten', 'has_grade', 'saturation=1.00;warmth=0.07', 'prior'],
        ['golden_hour', 'sky_material', 'sky_dusk', 'prior'],
        ['overcast', 'sky_material', 'sky_overcast', 'prior'],
    ];

    private FactStore $store;
    /** @var array<int, string> FQL queries run, rendered — goes into the manifest */
    public array $queries = [];

    public function __construct()
    {
        $this->store = new FactStore();
        $records = is_file(self::FILE) ? Ufcs::decodeBatch((string) file_get_contents(self::FILE)) : self::records(self::BUILTIN);
        $res = $this->store->ingest($records);
        if ($res['rejected'] > 0) {
            throw new RuntimeException('colour knowledge has ' . $res['rejected'] . ' record(s) whose fingerprint does not re-validate');
        }
    }

    /**
     * Build UFCS records from [subject, predicate, object, source] rows.
     *
     * @param array<int, array{0:string,1:string,2:string,3:string}> $rows
     * @return array<int, array<string, mixed>>
     */
    public static function records(array $rows): array
    {
        $out = [];
        foreach ($rows as [$s, $p, $o, $src]) {
            $source = self::SOURCES[$src] ?? self::SOURCES['user'];
            $fp = Ufcs::fingerprint($s, $p, $o, '+');
            $out[] = [
                'fuid' => hash('sha256', 'color|' . $fp . '|' . $source['id']),
                'fact_type' => 'assertion',
                'group' => match ($p) {
                    'has_typical_color', 'has_color' => 'color.material',
                    'implies_material' => 'color.scene_prior',
                    'sky_material' => 'color.lighting',
                    default => str_starts_with($s, 'era:') ? 'color.era_grade' : 'color.lighting',
                },
                'nucleus' => ['subject' => $s, 'predicate' => $p, 'object' => $o],
                'polarity' => '+',
                'semantic_fingerprint' => $fp,
                'confidence' => ['score' => $source['trust']],
                'sources' => [['id' => $source['id'], 'name' => $source['name'], 'class' => $source['class'], 'reputation' => $source['trust']]],
                'certification' => ['authority_class' => $source['class'], 'trust_score' => $source['trust']],
                'safety' => ['classification' => 'PUBLIC', 'acl' => ['reader']],
            ];
        }
        return $out;
    }

    /** Add facts supplied with a job (scene description, region labels, known colours). */
    public function addFacts(array $records): array
    {
        return $this->store->ingest($records);
    }

    /** @return array<int, array<string, mixed>> */
    public function ask(string $fql): array
    {
        $q = Fql::parse($fql);
        $this->queries[] = $q->render();
        return $this->store->query($q);
    }

    /** Best colour fact for a material or entity: [hex, fact record] or null. */
    public function colorOf(string $subject): ?array
    {
        $hits = $this->ask('FIND fact WHERE subject = "' . $subject . '" AND predicate IN [has_color, has_typical_color] RANK BY trust LIMIT 1');
        if (!$hits || !preg_match('/^#[0-9a-f]{6}$/i', (string) $hits[0]['nucleus']['object'])) {
            return null;
        }
        return [(string) $hits[0]['nucleus']['object'], $hits[0]];
    }

    /** @return array<int, string> materials a setting makes likely */
    public function materialsFor(string $setting): array
    {
        return array_map(fn ($r) => (string) $r['nucleus']['object'], $this->ask('FIND fact WHERE subject = "' . $setting . '" AND predicate = "implies_material" LIMIT 20'));
    }

    /** @return null|array{saturation:float, warmth:float, fact:array<string,mixed>} */
    public function gradeFor(string $subject): ?array
    {
        $hits = $this->ask('FIND fact WHERE subject = "' . $subject . '" AND predicate = "has_grade" RANK BY trust LIMIT 1');
        if (!$hits) {
            return null;
        }
        parse_str(str_replace(';', '&', (string) $hits[0]['nucleus']['object']), $g);
        return ['saturation' => (float) ($g['saturation'] ?? 1), 'warmth' => (float) ($g['warmth'] ?? 0), 'fact' => $hits[0]];
    }

    public function skyMaterialFor(string $lighting): ?string
    {
        $hits = $this->ask('FIND fact WHERE subject = "' . $lighting . '" AND predicate = "sky_material" LIMIT 1');
        return $hits ? (string) $hits[0]['nucleus']['object'] : null;
    }

    /** Write the built-in knowledge as a UFCS feed file. */
    public static function writeFeed(string $path = self::FILE): int
    {
        $records = self::records(self::BUILTIN);
        file_put_contents($path, Ufcs::encodeBatch($records));
        return count($records);
    }
}
