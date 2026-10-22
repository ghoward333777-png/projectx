<?php

declare(strict_types=1);

require_once __DIR__ . '/MediaGraphStore.php';

/**
 * Media Analyzer
 *
 * Turns one normalized stock-video record (see StockMediaHarvester) into
 * graph facts: technical profile (resolution class, orientation, aspect,
 * frame rate), provenance (source, creator, license), origin (camera,
 * CGI, AI-generated and which generator), what the clip depicts (concepts
 * from a fixed taxonomy), how it is framed (close-up, waist-up, wide,
 * plain background), what it can teach a model (lip reading, language,
 * culture, places and fashion, world objects, occupations, business,
 * avatar source material) and a 0–100 quality score.
 *
 * Analysis reads metadata only — titles, tags, descriptions and the
 * technical fields the free APIs return. No media is downloaded or stored.
 * Deterministic: the same record always yields the same facts.
 */
final class MediaAnalyzer
{
    /**
     * domain => [label, concepts => [concept => keywords]]
     * Keywords match whole words (a trailing "s" plural also matches).
     */
    public const TAXONOMY = [
        'speech' => ['Speech & language', [
            'talking' => ['talking', 'speaking', 'speaks', 'talks', 'speech', 'conversation', 'dialogue'],
            'interview' => ['interview', 'podcast', 'q and a'],
            'presenter' => ['presenter', 'spokesperson', 'news anchor', 'host', 'vlog', 'vlogger', 'lecture', 'presentation to camera', 'talking head'],
            'sign-language' => ['sign language', 'asl'],
        ]],
        'people' => ['People', [
            'person' => ['person', 'people', 'man', 'woman', 'men', 'women', 'girl', 'boy', 'child', 'children', 'teenager', 'adult', 'elderly', 'senior'],
            'face' => ['face', 'faces', 'facial', 'smile', 'smiling', 'eyes'],
            'family' => ['family', 'mother', 'father', 'grandmother', 'grandfather'],
        ]],
        'culture' => ['Culture & customs', [
            'wedding' => ['wedding', 'bride', 'groom', 'marriage'],
            'festival' => ['festival', 'carnival', 'parade', 'celebration'],
            'holiday' => ['christmas', 'diwali', 'eid', 'ramadan', 'lunar new year', 'chinese new year', 'thanksgiving', 'hanukkah', 'easter', 'halloween'],
            'ritual' => ['ritual', 'ceremony', 'tradition', 'traditional'],
            'dance' => ['dance', 'dancing', 'dancer'],
            'religion' => ['church', 'temple', 'mosque', 'prayer', 'praying', 'monk'],
            'cuisine' => ['food', 'cuisine', 'dinner', 'meal', 'street food', 'tea', 'coffee'],
        ]],
        'places' => ['Places', [
            'city' => ['city', 'downtown', 'urban', 'skyline', 'street', 'streets', 'traffic'],
            'beach' => ['beach', 'coast', 'shore', 'surf'],
            'mountain' => ['mountain', 'mountains', 'alps', 'hill', 'hills'],
            'forest' => ['forest', 'woods', 'jungle', 'rainforest'],
            'desert' => ['desert', 'dunes', 'sand dune'],
            'countryside' => ['countryside', 'village', 'rural', 'field', 'fields'],
            'ocean' => ['ocean', 'sea', 'underwater', 'waves'],
            'river' => ['river', 'lake', 'waterfall'],
        ]],
        'fashion' => ['Clothing, hair & makeup', [
            'clothing' => ['clothing', 'clothes', 'dress', 'suit', 'shirt', 'jacket', 'outfit', 'fashion', 'kimono', 'sari', 'hijab', 'uniform'],
            'hair' => ['hair', 'hairstyle', 'haircut', 'braid', 'braids', 'beard', 'curly hair'],
            'makeup' => ['makeup', 'make up', 'lipstick', 'cosmetics', 'mascara'],
            'accessories' => ['jewelry', 'glasses', 'sunglasses', 'hat', 'watch'],
        ]],
        'weather' => ['Weather', [
            'rain' => ['rain', 'rainy', 'raining', 'rainfall', 'drizzle', 'precipitation', 'umbrella'],
            'snow' => ['snow', 'snowy', 'snowfall', 'blizzard', 'winter'],
            'storm' => ['storm', 'thunder', 'thunderstorm', 'lightning', 'hurricane', 'tornado', 'cyclone'],
            'fog' => ['fog', 'foggy', 'mist', 'misty', 'haze'],
            'sunny' => ['sunny', 'sunshine', 'clear sky', 'heat wave'],
            'clouds' => ['cloud', 'clouds', 'cloudy', 'overcast'],
            'wind' => ['wind', 'windy', 'breeze'],
        ]],
        'vehicles' => ['Vehicles', [
            'car' => ['car', 'cars', 'automobile', 'taxi', 'suv'],
            'truck' => ['truck', 'lorry'],
            'bus' => ['bus', 'tram', 'streetcar'],
            'train' => ['train', 'railway', 'subway', 'metro'],
            'aircraft' => ['airplane', 'plane', 'aircraft', 'jet', 'helicopter', 'airport'],
            'boat' => ['boat', 'ship', 'ferry', 'yacht', 'sailboat'],
            'bicycle' => ['bicycle', 'bike', 'cycling', 'cyclist'],
            'motorcycle' => ['motorcycle', 'scooter', 'motorbike'],
            'spacecraft' => ['rocket', 'spacecraft', 'shuttle', 'space station', 'rover'],
        ]],
        'structures' => ['Structures', [
            'bridge' => ['bridge'],
            'skyscraper' => ['skyscraper', 'tower', 'high rise', 'building', 'buildings'],
            'house' => ['house', 'home', 'apartment', 'cabin'],
            'road' => ['road', 'highway', 'freeway', 'intersection'],
            'factory' => ['factory', 'plant', 'warehouse', 'industrial'],
            'stadium' => ['stadium', 'arena'],
            'landmark' => ['monument', 'cathedral', 'castle', 'palace', 'ruins'],
        ]],
        'occupations' => ['Occupations & skills', [
            'medicine' => ['doctor', 'nurse', 'hospital', 'surgeon', 'medical', 'clinic'],
            'cooking' => ['chef', 'cook', 'cooking', 'kitchen', 'baker', 'baking'],
            'construction' => ['construction', 'builder', 'engineer', 'welder', 'welding', 'carpenter'],
            'farming' => ['farmer', 'farm', 'farming', 'agriculture', 'harvest', 'tractor'],
            'teaching' => ['teacher', 'classroom', 'school', 'student', 'students', 'lesson'],
            'office-work' => ['office', 'laptop', 'computer', 'typing', 'desk'],
            'science' => ['scientist', 'laboratory', 'lab', 'research', 'microscope'],
            'mechanics' => ['mechanic', 'repair', 'garage', 'tools'],
            'crafts' => ['artisan', 'pottery', 'sewing', 'tailor', 'weaving', 'painter'],
            'spaceflight' => ['astronaut', 'mission control', 'launch'],
        ]],
        'business' => ['Economics & business', [
            'meeting' => ['meeting', 'conference', 'boardroom', 'teamwork', 'handshake'],
            'finance' => ['money', 'finance', 'bank', 'stock market', 'trading', 'cash', 'investment', 'economy'],
            'retail' => ['shop', 'store', 'shopping', 'market', 'cashier', 'customer'],
            'startup' => ['startup', 'entrepreneur', 'coworking'],
            'logistics' => ['delivery', 'shipping', 'container', 'logistics', 'port'],
        ]],
        'events' => ['Events', [
            'concert' => ['concert', 'music', 'band', 'singer', 'guitar'],
            'sports' => ['sport', 'sports', 'football', 'soccer', 'basketball', 'tennis', 'running', 'runner', 'gym', 'fitness', 'yoga'],
            'party' => ['party', 'birthday', 'nightlife'],
            'protest' => ['protest', 'rally', 'march', 'demonstration'],
        ]],
        'nature' => ['Nature & science', [
            'animals' => ['animal', 'animals', 'dog', 'cat', 'bird', 'birds', 'horse', 'wildlife', 'fish'],
            'plants' => ['flower', 'flowers', 'tree', 'trees', 'plant', 'plants', 'garden'],
            'earth' => ['earth', 'planet', 'climate', 'water cycle', 'volcano', 'glacier'],
            'space' => ['space', 'galaxy', 'stars', 'moon', 'sun', 'nebula', 'satellite', 'mars'],
        ]],
    ];

    /** shot => keywords */
    private const SHOTS = [
        'closeup' => ['close up', 'closeup', 'close-up', 'headshot', 'head shot', 'portrait', 'extreme close up', 'face'],
        'medium' => ['waist up', 'medium shot', 'upper body', 'half body', 'mid shot', 'shoulders', 'talking head', 'to camera'],
        'wide' => ['wide shot', 'aerial', 'drone', 'establishing shot', 'panorama', 'timelapse', 'time lapse'],
    ];

    private const PLAIN_BACKGROUND = ['green screen', 'greenscreen', 'chroma key', 'white background', 'black background', 'isolated', 'plain background', 'studio background', 'studio'];

    private const AI_MARKERS = ['ai generated', 'ai-generated', 'generated by ai', 'generative ai', 'gen ai', 'genai', 'ai video', 'ai art', 'synthetic video', 'text to video', 'image to video', 'ai avatar'];

    /** generator slug => keywords */
    private const GENERATORS = [
        'sora' => ['sora'],
        'runway' => ['runway', 'gen-3', 'gen-4', 'gen 3', 'gen 4'],
        'veo' => ['veo', 'google veo'],
        'kling' => ['kling'],
        'luma' => ['luma', 'dream machine'],
        'pika' => ['pika'],
        'midjourney' => ['midjourney'],
        'stable-diffusion' => ['stable diffusion', 'stable video', 'svd', 'comfyui'],
        'firefly' => ['firefly'],
        'synthesia' => ['synthesia'],
        'heygen' => ['heygen'],
        'wan' => ['wan 2', 'wan2', 'wan video'],
    ];

    private const CGI_MARKERS = ['cgi', '3d render', '3d animation', 'animation', 'animated', 'visualization', 'simulation', 'motion graphics'];

    /** use => label */
    public const USES = [
        'lip_reading' => 'Lip reading & lip sync',
        'language_learning' => 'Language & dialect learning',
        'culture_customs' => 'Culture & customs',
        'places_fashion' => 'Places, clothing, hair & makeup',
        'world_objects' => 'Weather, vehicles & structures',
        'occupational_skills' => 'Occupational skills',
        'economics_business' => 'Economics & business',
        'avatar_source' => 'Avatar-mill source footage',
    ];

    /**
     * Analyze one normalized record.
     *
     * @param array<string, mixed> $record
     * @return array{subject: string, facts: array<int, array{0: string, 1: string, 2: string}>, profile: array<string, mixed>}
     */
    public function analyze(array $record): array
    {
        $n = MediaGraphStore::NODE;
        $l = MediaGraphStore::LITERAL;
        $source = self::slug((string) $record['source']);
        $subject = 'video:' . $source . ':' . self::slug((string) $record['source_id']);
        $tags = array_values(array_unique(array_filter(array_map(static fn ($t): string => self::slug((string) $t), (array) $record['tags']))));
        $tags = array_slice($tags, 0, 25);
        $text = self::haystack((string) $record['title'] . ' ' . (string) $record['description'] . ' ' . implode(' ', (array) $record['tags']));

        $facts = [['is_a', 'Video', $n], ['from_source', 'source:' . $source, $n]];
        foreach (['title' => 160, 'description' => 500] as $field => $cap) {
            $value = trim((string) $record[$field]);
            if ($value !== '') {
                $facts[] = [$field, mb_substr($value, 0, $cap), $l];
            }
        }
        foreach (['page_url', 'created'] as $field) {
            if ((string) $record[$field] !== '') {
                $facts[] = [$field, (string) $record[$field], $l];
            }
        }
        if ((string) $record['creator'] !== '') {
            $facts[] = ['created_by', 'creator:' . $source . '/' . self::slug((string) $record['creator']), $n];
        }
        $license = (string) $record['license'] !== '' ? (string) $record['license'] : 'unspecified';
        $facts[] = ['licensed_as', 'license:' . self::slug($license), $n];

        $width = (int) $record['width'];
        $height = (int) $record['height'];
        $long = max($width, $height);
        foreach (['width' => $width, 'height' => $height, 'duration_s' => (float) $record['duration'], 'fps' => (float) $record['fps'], 'views' => (int) $record['views'], 'downloads' => (int) $record['downloads']] as $field => $value) {
            if ($value > 0) {
                $facts[] = [$field, MediaGraphStore::number($value), $l];
            }
        }
        $resolution = $this->resolutionClass($long);
        $facts[] = ['resolution_class', 'res:' . $resolution, $n];
        if ($width > 0 && $height > 0) {
            $facts[] = ['orientation', 'orient:' . ($width > $height ? 'landscape' : ($width < $height ? 'portrait' : 'square')), $n];
            $facts[] = ['aspect', 'aspect:' . $this->aspect($width, $height), $n];
        }

        [$origin, $generator] = $this->origin($record, $text);
        $facts[] = ['origin', 'origin:' . $origin, $n];
        if ($generator !== null) {
            $facts[] = ['generated_with', 'gen:' . $generator, $n];
        }

        foreach ($tags as $tag) {
            $facts[] = ['has_tag', 'tag:' . $tag, $n];
        }

        $concepts = $this->concepts($text);
        $domains = [];
        foreach ($concepts as $concept) {
            $facts[] = ['depicts', 'concept:' . $concept, $n];
            $domains[explode('/', $concept)[0]] = true;
        }

        $shots = [];
        foreach (self::SHOTS as $shot => $keywords) {
            if ($this->matchesAny($text, $keywords)) {
                $shots[$shot] = true;
                $facts[] = ['shot', 'shot:' . $shot, $n];
            }
        }
        $plain = $this->matchesAny($text, self::PLAIN_BACKGROUND);
        if ($plain) {
            $facts[] = ['background', 'bg:plain', $n];
        }

        $hasSpeech = isset($domains['speech']);
        $hasPeople = isset($domains['people']) || $hasSpeech;
        $sharp = $long >= 1920;
        $uses = [];
        // Lip reading needs a talking mouth framed close enough to resolve it.
        if ($hasSpeech && (isset($shots['closeup']) || isset($shots['medium'])) && $long >= 1280) {
            $uses[] = 'lip_reading';
        }
        if ($hasSpeech) {
            $uses[] = 'language_learning';
        }
        if (isset($domains['culture'])) {
            $uses[] = 'culture_customs';
        }
        if (isset($domains['places']) || isset($domains['fashion'])) {
            $uses[] = 'places_fashion';
        }
        if (isset($domains['weather']) || isset($domains['vehicles']) || isset($domains['structures'])) {
            $uses[] = 'world_objects';
        }
        if (isset($domains['occupations'])) {
            $uses[] = 'occupational_skills';
        }
        if (isset($domains['business'])) {
            $uses[] = 'economics_business';
        }
        if ($hasPeople && (isset($shots['closeup']) || isset($shots['medium'])) && $sharp) {
            $uses[] = 'avatar_source';
        }
        foreach ($uses as $use) {
            $facts[] = ['supports', 'use:' . $use, $n];
        }

        $score = $this->qualityScore($resolution, (float) $record['fps'], (float) $record['duration'], count($tags), $license !== 'unspecified');
        $facts[] = ['quality_score', (string) $score, $l];

        return [
            'subject' => $subject,
            'facts' => $facts,
            'profile' => [
                'resolution' => $resolution,
                'origin' => $origin,
                'generator' => $generator,
                'concepts' => $concepts,
                'shots' => array_keys($shots),
                'plain_background' => $plain,
                'uses' => $uses,
                'quality_score' => $score,
            ],
        ];
    }

    /**
     * Analyze and write records into the graph, replacing what was known
     * about each video. Also writes the taxonomy vertices (concept → domain,
     * labels) the first time they are referenced. Returns the subjects written.
     *
     * @param array<int, array<string, mixed>> $records Normalized records.
     * @return array<int, string>
     */
    public function ingest(MediaGraphStore $store, array $records): array
    {
        $n = MediaGraphStore::NODE;
        $l = MediaGraphStore::LITERAL;
        $subjects = [];
        foreach ($records as $record) {
            $analysis = $this->analyze($record);
            $store->replaceSubject($analysis['subject'], $analysis['facts']);
            $subjects[] = $analysis['subject'];
            foreach ($analysis['facts'] as [$predicate, $object]) {
                if ($predicate === 'depicts') {
                    [$domain, $concept] = explode('/', substr($object, 8), 2);
                    $store->add($object, 'is_a', 'Concept', $n);
                    $store->add($object, 'label', $concept, $l);
                    $store->add($object, 'broader', 'domain:' . $domain, $n);
                    $store->add('domain:' . $domain, 'is_a', 'Domain', $n);
                    $store->add('domain:' . $domain, 'label', self::TAXONOMY[$domain][0], $l);
                } elseif ($predicate === 'supports') {
                    $store->add($object, 'is_a', 'LearningUse', $n);
                    $store->add($object, 'label', self::USES[substr($object, 4)], $l);
                } elseif ($predicate === 'created_by') {
                    $store->add($object, 'is_a', 'Creator', $n);
                    $store->add($object, 'label', (string) $record['creator'], $l);
                } elseif ($predicate === 'from_source') {
                    $store->add($object, 'is_a', 'Source', $n);
                } elseif ($predicate === 'licensed_as') {
                    $store->add($object, 'is_a', 'License', $n);
                } elseif ($predicate === 'generated_with') {
                    $store->add($object, 'is_a', 'Generator', $n);
                }
            }
        }
        return $subjects;
    }

    public function resolutionClass(int $longSide): string
    {
        return match (true) {
            $longSide >= 7680 => '8K',
            $longSide >= 3840 => '4K',
            $longSide >= 2560 => 'QHD',
            $longSide >= 1920 => 'FullHD',
            $longSide >= 1280 => 'HD',
            $longSide > 0 => 'SD',
            default => 'unknown',
        };
    }

    public static function slug(string $value): string
    {
        $value = strtolower(trim($value));
        $value = (string) preg_replace('/[^a-z0-9]+/', '-', $value);
        $value = trim($value, '-');
        return $value === '' ? 'unnamed' : substr($value, 0, 80);
    }

    /** @return array<int, string> "domain/concept", taxonomy order */
    private function concepts(string $text): array
    {
        $found = [];
        foreach (self::TAXONOMY as $domain => [, $concepts]) {
            foreach ($concepts as $concept => $keywords) {
                if ($this->matchesAny($text, $keywords)) {
                    $found[] = $domain . '/' . $concept;
                }
            }
        }
        return $found;
    }

    /**
     * @param array<string, mixed> $record
     * @return array{0: string, 1: ?string}
     */
    private function origin(array $record, string $text): array
    {
        $generator = null;
        foreach (self::GENERATORS as $slug => $keywords) {
            if ($this->matchesAny($text, $keywords)) {
                $generator = $slug;
                break;
            }
        }
        $flag = $record['ai_generated'];
        if ($flag === true || ($flag === null && ($this->matchesAny($text, self::AI_MARKERS) || $generator !== null))) {
            return ['ai_generated', $generator];
        }
        if ($flag === false) {
            return [$this->matchesAny($text, self::CGI_MARKERS) ? 'cgi' : 'camera', null];
        }
        return [$this->matchesAny($text, self::CGI_MARKERS) ? 'cgi' : 'unspecified', null];
    }

    private function qualityScore(string $resolution, float $fps, float $duration, int $tagCount, bool $licensed): int
    {
        $score = ['8K' => 40, '4K' => 35, 'QHD' => 28, 'FullHD' => 22, 'HD' => 14, 'SD' => 6][$resolution] ?? 0;
        $score += $fps >= 50 ? 15 : ($fps >= 24 ? 10 : 0);
        $score += $duration >= 5 && $duration <= 120 ? 15 : ($duration > 0 ? 8 : 0);
        $score += min(10, $tagCount) * 2;
        $score += $licensed ? 10 : 0;
        return min(100, $score);
    }

    private function aspect(int $w, int $h): string
    {
        $ratio = $w / $h;
        foreach (['16x9' => 16 / 9, '9x16' => 9 / 16, '4x3' => 4 / 3, '3x4' => 3 / 4, '1x1' => 1.0, '21x9' => 21 / 9, '4x5' => 4 / 5] as $label => $target) {
            if (abs($ratio - $target) < 0.03) {
                return $label;
            }
        }
        $a = $w;
        $b = $h;
        while ($b !== 0) {
            [$a, $b] = [$b, $a % $b];
        }
        return ($w / $a) . 'x' . ($h / $a);
    }

    private static function haystack(string $text): string
    {
        $text = strtolower(strip_tags($text));
        return ' ' . trim((string) preg_replace('/[^a-z0-9]+/', ' ', $text)) . ' ';
    }

    /** @param array<int, string> $keywords */
    private function matchesAny(string $haystack, array $keywords): bool
    {
        foreach ($keywords as $keyword) {
            $needle = trim((string) preg_replace('/[^a-z0-9]+/', ' ', strtolower($keyword)));
            if ($needle !== '' && (str_contains($haystack, ' ' . $needle . ' ') || str_contains($haystack, ' ' . $needle . 's '))) {
                return true;
            }
        }
        return false;
    }
}
