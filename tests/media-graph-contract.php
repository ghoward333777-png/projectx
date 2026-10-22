<?php

declare(strict_types=1);

require_once __DIR__ . '/../StockMediaHarvester.php';
require_once __DIR__ . '/../MediaAnalyzer.php';
require_once __DIR__ . '/../QueryBook.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

function fresh_dir(): string
{
    $dir = sys_get_temp_dir() . '/media-graph-contract-' . bin2hex(random_bytes(4));
    mkdir($dir, 0775, true);
    return $dir;
}

// --- Harvester adapters (offline fixtures, no network) ----------------------
$requested = [];
$fixtures = [
    'images-api.nasa.gov' => ['collection' => ['items' => [['data' => [['nasa_id' => 'jsc-123', 'title' => 'Astronaut interview aboard the space station', 'description' => 'An astronaut talking to camera.', 'keywords' => ['astronaut', 'interview'], 'date_created' => '2020-01-02T00:00:00Z', 'center' => 'JSC']]]]]],
    'archive.org' => ['response' => ['docs' => [['identifier' => 'rain_clip', 'title' => 'Rain on a roof', 'subject' => ['rain', 'weather'], 'licenseurl' => 'http://creativecommons.org/licenses/by/4.0/', 'creator' => 'Someone', 'date' => '2019-05-05T00:00:00Z', 'downloads' => 12]]]],
    'commons.wikimedia.org' => ['query' => ['pages' => ['77' => ['pageid' => 77, 'title' => 'File:Snow_in_Oslo.webm', 'imageinfo' => [['width' => 3840, 'height' => 2160, 'duration' => 12.5, 'descriptionurl' => 'https://commons.wikimedia.org/wiki/File:Snow_in_Oslo.webm', 'extmetadata' => ['LicenseShortName' => ['value' => 'CC BY-SA 4.0'], 'Artist' => ['value' => '<a href="x">Kari</a>'], 'Categories' => ['value' => 'Snow|Oslo']]]]]]]],
    'api.pexels.com' => ['videos' => [['id' => 9, 'url' => 'https://www.pexels.com/video/woman-talking-close-up-9/', 'duration' => 15, 'user' => ['name' => 'Ana'], 'video_files' => [['width' => 1280, 'height' => 720, 'fps' => 25], ['width' => 3840, 'height' => 2160, 'fps' => 29.97]]]]],
    'pixabay.com' => ['hits' => [['id' => 5, 'pageURL' => 'https://pixabay.com/videos/id-5/', 'tags' => 'ai generated, city, skyline', 'duration' => 8, 'user' => 'pix', 'views' => 100, 'downloads' => 7, 'videos' => ['large' => ['width' => 1920, 'height' => 1080], 'small' => ['width' => 960, 'height' => 540]]]]],
];
$fetcher = static function (string $url, array $headers) use (&$requested, $fixtures): string {
    $requested[] = $url;
    $host = (string) parse_url($url, PHP_URL_HOST);
    return json_encode($fixtures[$host] ?? []);
};
$harvester = new StockMediaHarvester($fetcher, ['pexels' => 'k1', 'pixabay' => 'k2']);
$all = [];
foreach (array_keys(StockMediaHarvester::SOURCES) as $source) {
    $result = $harvester->harvest($source, 'test', 5);
    contract_check($result['error'] === null, "{$source} harvest must succeed on its fixture: " . (string) $result['error']);
    contract_check(count($result['records']) === 1, "{$source} must normalize exactly one record");
    $record = $result['records'][0];
    contract_check($record['source'] === $source && $record['source_id'] !== '', "{$source} records must carry source and id");
    foreach (['title', 'tags', 'width', 'height', 'duration', 'license', 'ai_generated'] as $key) {
        contract_check(array_key_exists($key, $record), "{$source} records must have the {$key} key");
    }
    $all[] = $record;
}
contract_check($all[0]['width'] === 3840 && $all[0]['creator'] === 'Kari', 'Wikimedia must read size and strip HTML from the artist');
contract_check($all[1]['license'] === 'CC BY 4.0', 'Internet Archive license URLs must become readable license names');
contract_check($all[3]['width'] === 3840 && $all[3]['fps'] === 29.97, 'Pexels must use the largest rendition');
contract_check(in_array('talking', $all[3]['tags'], true), 'Pexels tags come from the page slug');
foreach ($requested as $url) {
    $host = (string) parse_url($url, PHP_URL_HOST);
    contract_check(in_array($host, ['images-api.nasa.gov', 'archive.org', 'commons.wikimedia.org', 'api.pexels.com', 'pixabay.com'], true), 'only official metadata APIs may be requested: ' . $url);
    contract_check(!preg_match('/\.(mp4|webm|mov|m4v)(\?|$)/i', $url), 'the harvester must never download footage: ' . $url);
}

$keyless = new StockMediaHarvester($fetcher, []);
contract_check(!$keyless->available('pexels') && $keyless->available('nasa'), 'keyed sources are unavailable without a key; keyless ones always are');
contract_check(str_contains((string) $keyless->harvest('pexels', 'x')['error'], 'PEXELS_API_KEY'), 'a missing key must be explained');
contract_check($harvester->harvest('nowhere', 'x')['error'] !== null, 'unknown sources must be refused');

// --- Analyzer ---------------------------------------------------------------
$analyzer = new MediaAnalyzer();
$talking = $analyzer->analyze(StockMediaHarvester::normalize([
    'source' => 'sample', 'source_id' => 'a1', 'title' => 'Woman talking to camera, close up',
    'tags' => ['talking', 'woman', 'white background'], 'width' => 3840, 'height' => 2160, 'duration' => 12, 'fps' => 30, 'license' => 'CC0',
]));
$facts = array_map(static fn (array $f): string => $f[0] . ' ' . $f[1], $talking['facts']);
foreach (['resolution_class res:4K', 'orientation orient:landscape', 'aspect aspect:16x9', 'shot shot:closeup', 'background bg:plain', 'supports use:lip_reading', 'supports use:avatar_source', 'depicts concept:speech/talking'] as $expected) {
    contract_check(in_array($expected, $facts, true), "a 4K close-up of a woman talking must yield: {$expected}");
}
$ai = $analyzer->analyze(StockMediaHarvester::normalize(['source' => 'sample', 'source_id' => 'a2', 'title' => 'City skyline made with Runway', 'tags' => ['ai generated']]));
contract_check($ai['profile']['origin'] === 'ai_generated' && $ai['profile']['generator'] === 'runway', 'AI markers and generator names must be detected');
$declared = $analyzer->analyze(StockMediaHarvester::normalize(['source' => 'sample', 'source_id' => 'a3', 'title' => 'Plain beach', 'ai_generated' => true]));
contract_check($declared['profile']['origin'] === 'ai_generated', 'an explicit ai_generated flag must win');
contract_check($analyzer->resolutionClass(7680) === '8K' && $analyzer->resolutionClass(1920) === 'FullHD' && $analyzer->resolutionClass(0) === 'unknown', 'resolution classes follow the long side');
contract_check($analyzer->analyze($all[1]) === $analyzer->analyze($all[1]), 'analysis must be deterministic');

// --- Store: ingest, persist, reload, refresh --------------------------------
$sample = json_decode((string) file_get_contents(__DIR__ . '/../data/sample-media.json'), true);
$records = $harvester->importManifest($sample, 'sample');
contract_check(count($records) === 24, 'the sample corpus must import every item');

$dirA = fresh_dir();
$store = new MediaGraphStore($dirA);
$analyzer->ingest($store, $records);
$store->save();
$factCount = $store->count();
contract_check($factCount > 500, 'the sample corpus must produce a substantial graph');

$reloaded = new MediaGraphStore($dirA);
contract_check($reloaded->count() === $factCount, 'a saved graph must reload with every fact');

$analyzer->ingest($reloaded, $records);
contract_check($reloaded->count() === $factCount, 're-ingesting the same videos must not duplicate facts');
$changed = $records;
$changed[0]['title'] = 'Renamed clip';
$analyzer->ingest($reloaded, [$changed[0]]);
contract_check(count($reloaded->match('video:sample:001', 'title')) === 1, 're-harvesting must replace a video\'s facts, not pile them up');

$dirB = fresh_dir();
$storeB = new MediaGraphStore($dirB);
$analyzer->ingest($storeB, array_reverse($records));
$storeB->save();
contract_check(md5_file($dirA . '/facts.jsonl') === md5_file($dirB . '/facts.jsonl'), 'the same inputs must produce a byte-identical graph file, whatever the order');

// --- FQL --------------------------------------------------------------------
$engine = new FqlEngine(new MediaGraphStore($dirA));
$count = $engine->run('COUNT ?v WHERE ?v is_a Video');
contract_check($count['rows'] === [['24']], 'COUNT must count distinct videos');

$bySource = $engine->run('COUNT ?v BY ?s WHERE ?v from_source ?s');
contract_check($bySource['rows'] === [['source:sample', '24']], 'COUNT BY must group');

$lip = $engine->run('SELECT ?v ?t WHERE ?v supports use:lip_reading AND ?v title ?t ORDER BY ?t');
contract_check($lip['total'] >= 4, 'the sample corpus must contain lip-reading candidates');
$titles = array_column($lip['rows'], 1);
$sorted = $titles;
sort($sorted, SORT_STRING);
contract_check($titles === $sorted, 'ORDER BY must sort ascending');

$long = $engine->run('SELECT ?v ?d WHERE ?v duration_s ?d FILTER ?d >= 40 ORDER BY ?d DESC LIMIT 2');
contract_check(count($long['rows']) === 2 && (float) $long['rows'][0][1] >= (float) $long['rows'][1][1] && (float) $long['rows'][1][1] >= 40, 'numeric FILTER, DESC order and LIMIT must apply');
contract_check($long['truncated'] === true, 'a LIMIT that cuts results must report truncation');

$fourK = $engine->run('COUNT ?v WHERE ?v width 3840');
contract_check((int) $fourK['rows'][0][0] > 0, 'numeric literals in patterns must match stored numbers');

$contains = $engine->run('SELECT ?v WHERE ?v title ?t FILTER ?t CONTAINS "HEAVY RAIN"');
contract_check(count($contains['rows']) === 1, 'CONTAINS must be case-insensitive');

$join = $engine->run('SELECT ?c WHERE ?v depicts ?c AND ?c broader domain:weather AND ?v resolution_class res:8K');
contract_check($join['rows'] !== [] && str_starts_with($join['rows'][0][0], 'concept:weather/'), 'multi-pattern joins must work');

$describe = $engine->run('DESCRIBE video:sample:004');
contract_check(in_array(['→', 'resolution_class', 'res:8K', 'node'], $describe['rows'], true), 'DESCRIBE must list outgoing facts');
$neighbors = $engine->run('NEIGHBORS concept:weather/rain DEPTH 2');
contract_check($neighbors['total'] > 0 && in_array('2', array_column($neighbors['rows'], 3), true), 'NEIGHBORS must walk more than one hop');
contract_check($engine->run('STATS')['rows'][2] === ['videos', '24'], 'STATS must count videos');

foreach (['', 'SELECT WHERE ?v is_a Video', 'SELECT ?v WHERE ?v is_a', 'SELECT ?x WHERE ?v is_a Video', 'SELECT ?v WHERE "lit" is_a Video', 'DROP everything', 'SELECT ?v WHERE ?v is_a Video LIMIT many'] as $bad) {
    $threw = false;
    try {
        $engine->run($bad);
    } catch (InvalidArgumentException) {
        $threw = true;
    }
    contract_check($threw, 'malformed FQL must be rejected: ' . $bad);
}
contract_check($engine->run('SELECT ?v WHERE ?v is_a Nothing')['rows'] === [], 'no matches must return no rows, not an error');

// --- QueryBook --------------------------------------------------------------
$book = new QueryBook($engine, $dirA . '/querybooks');
foreach ($book->run(QueryBook::starterCells()) as $entry) {
    contract_check($entry['error'] === null, 'every starter QueryBook cell must run: ' . $entry['cell']['title'] . ' — ' . (string) $entry['error']);
    contract_check($entry['result']['rows'] !== [], 'every starter cell must find something in the sample corpus: ' . $entry['cell']['title']);
}
$saved = $book->addCell('My Research', 'Rain', 'SELECT ?v WHERE ?v depicts concept:weather/rain', 'note');
contract_check($saved === 'my-research' && in_array('my-research', $book->list(), true), 'saved books must be listed by slug');
contract_check(count($book->load('my-research')) === 1, 'a new book starts empty and holds the saved cell');
$threw = false;
try {
    $book->addCell('my-research', 'Broken', 'SELECT nonsense');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'a QueryBook must refuse to save FQL that does not parse');

// --- Clean up ---------------------------------------------------------------
foreach ([$dirA, $dirB] as $dir) {
    foreach (array_merge(glob($dir . '/querybooks/*') ?: [], glob($dir . '/*') ?: []) as $file) {
        is_dir($file) ? rmdir($file) : unlink($file);
    }
    rmdir($dir);
}

fwrite(STDOUT, "Media graph contract passed\n");
