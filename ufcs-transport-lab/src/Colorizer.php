<?php

declare(strict_types=1);

/**
 * QueryBook Semantic Colorization Engine (VCUM — Registry F22, F75, F76) for
 * black-and-white stills and video, with resolution enhancement to 1K, 4K and
 * 16K.
 *
 * What it uses from QueryBook / UFCS-FQL:
 *  - Colour is knowledge, not guesswork: every colour painted comes from a
 *    UFCS Fact Unit (material palette, scene priors, period grading, lighting,
 *    or a fact supplied with the job such as a landmark's known colour),
 *    resolved by an FQL query and recorded with its fuid, source and trust.
 *  - Confidence is bounded (F224): a region's colour confidence is the lesser
 *    of how sure the material classification is and how trusted the fact is.
 *  - Withhold, don't fabricate (F182): below the confidence floor a region
 *    keeps its observed gray instead of an invented colour.
 *  - Marking (F225): luminance is observed and is preserved exactly; colour is
 *    reconstructed and every output says so (metadata + provenance manifest).
 *  - Determinism (F22): identical inputs and facts give identical output.
 *  - Declared agents (F76): each stage does only its declared task, and the
 *    manifest records what each did.
 *
 * Heavy pixel work runs in ffmpeg: colour is synthesised at an analysis
 * resolution (colour carries far less spatial detail than luminance — the
 * reason every video codec subsamples it), then luminance is resampled to the
 * target and merged with the upsampled colour planes.
 */
final class Colorizer
{
    /** Target widths: 1K, 4K UHD and 16K (15360 × 8640 at 16:9). */
    public const TARGETS = ['1k' => 1024, '4k' => 3840, '16k' => 15360];
    public const WORK_W = 320;
    public const CELL = 8;
    /** Regions below this colour confidence keep their gray (F182). */
    public const WITHHOLD_BELOW = 0.35;
    private const CLASSES = ['sky', 'foliage', 'grass', 'water', 'sand', 'soil', 'stone', 'brick', 'wood', 'metal', 'skin'];
    /** Classes that need scene evidence before they are plausible. */
    private const SCENE_DEPENDENT = ['water', 'sand', 'brick', 'wood', 'metal', 'skin'];

    public const AGENTS = [
        'ingest' => 'Extract the observed luminance at analysis resolution; never alter it.',
        'knowledge' => 'Resolve scene facts and the colour palette from UFCS facts by FQL.',
        'lighting' => 'Resolve lighting from facts: white balance and sky material.',
        'historical_prior' => 'Resolve the period grade (film stock saturation and warmth) from facts.',
        'material' => 'Classify each region into a material class with a confidence.',
        'colorist' => 'Synthesise chroma per region: confidence = min(classification, fact trust); withhold below the floor.',
        'upscale' => 'Resample luminance to each target, merge the colour planes, verify consistency with the source.',
        'marking' => 'Mark colour as reconstructed and write the provenance manifest.',
    ];

    private ColorKnowledge $k;
    private array $agentLog = [];

    public function __construct(?ColorKnowledge $knowledge = null)
    {
        $this->k = $knowledge ?? new ColorKnowledge();
    }

    /**
     * @param array<string, mixed> $o scene (string "setting=beach;era=1950s;time=golden_hour;contains=people"),
     *   facts (array of "subject|predicate|object"), regions (array of "x0,y0,x1,y1=label", fractions 0–1),
     *   targets (["1k","4k","16k"]), out_dir, name, max_seconds (video), max_16k_frames, still_16k ("jpg"|"png"),
     *   evaluate (input is colour ground truth: colorize its gray and score against it)
     * @return array<string, mixed> manifest
     */
    public function run(string $input, array $o = []): array
    {
        if (MediaCodec::ffmpeg() === '') {
            throw new RuntimeException('Colorization needs ffmpeg');
        }
        $t0 = microtime(true);
        $out = rtrim((string) ($o['out_dir'] ?? sys_get_temp_dir() . '/ufcs-colorize'), '/');
        if (!is_dir($out)) {
            mkdir($out, 0775, true);
        }
        $name = preg_replace('/[^A-Za-z0-9_-]/', '_', (string) ($o['name'] ?? pathinfo($input, PATHINFO_FILENAME)));
        // Targets: 1k / 4k / 16k, a scale factor ("2x"), or an explicit width ("w640").
        $targets = array_values(array_filter(array_map('strtolower', (array) ($o['targets'] ?? ['1k', '4k'])),
            fn ($t) => isset(self::TARGETS[$t]) || preg_match('/^(\d+(\.\d+)?x|w\d{2,5})$/', $t)));

        // 1 · ingest
        $ing = $this->agent('ingest', fn () => $this->ingest($input, $o));
        // 2 · knowledge (scene facts, priors, palette)
        $know = $this->agent('knowledge', fn () => $this->knowledge($o));
        // 3 · lighting, 4 · historical prior
        $light = $this->agent('lighting', fn () => $this->lighting($know['scene']));
        $era = $this->agent('historical_prior', fn () => $this->era($know['scene']));
        $grade = ['saturation' => $light['saturation'] * $era['saturation'], 'warmth' => $light['warmth'] + $era['warmth']];
        $palette = $this->palette($know, $light);
        // 5 · material + 6 · colorist, frame by frame
        $col = $this->agent('colorist', fn () => $this->colorize($ing, $know, $palette, $grade, $o));
        $this->agentLog['material'] = ['task' => self::AGENTS['material'], 'ms' => $col['material_ms'], 'result' => ['regions' => $col['regions']]];
        // 7 · upscale to targets
        $base = $out . '/' . $name;
        file_put_contents($base . '.u.raw', $col['u']);
        file_put_contents($base . '.v.raw', $col['v']);
        $outputs = $this->agent('upscale', fn () => $this->upscale($input, $ing, $targets, $base, $o));
        $preview = $this->preview($input, $ing, $base);
        @unlink($base . '.u.raw');
        @unlink($base . '.v.raw');
        // 8 · marking
        $manifest = [
            'engine' => 'QueryBook Semantic Colorization Engine (VCUM) · UFCS-FQL lab',
            'registry' => ['F22 VCUM', 'F75 Semantic Colorization Engine', 'F76 agent specifications', 'F182 provenance + withhold', 'F224 bounded confidence', 'F225 reconstruction marking'],
            'marking' => 'Luminance: observed (from the source, resampled only). Colour: reconstructed by inference from UFCS facts — not observed. Regions under ' . self::WITHHOLD_BELOW . ' confidence keep their gray.',
            'input' => ['file' => basename($input), 'kind' => $ing['video'] ? 'video' : 'still', 'width' => $ing['w'], 'height' => $ing['h'], 'fps' => $ing['fps_text'],
                'frames' => $ing['frames'], 'seconds' => $ing['seconds'], 'analysis' => $ing['ww'] . 'x' . $ing['wh']],
            'scene_facts' => $know['scene_rows'],
            'boosted_materials' => array_values($know['boost']),
            'grade' => ['saturation' => round($grade['saturation'], 3), 'warmth' => round($grade['warmth'], 3), 'lighting' => $light['name'], 'era' => $era['name'],
                'lighting_fact' => $light['fuid'] ?? null, 'era_fact' => $era['fuid'] ?? null],
            'palette' => array_map(fn ($p) => array_diff_key($p, ['cb' => 1, 'cr' => 1]), $palette),
            'regions' => $col['regions'],
            'withheld_pct' => $col['withheld_pct'],
            'neutral_pct' => $col['neutral_pct'],
            'outputs' => $outputs,
            'preview' => $preview,
            'fql' => array_values(array_unique($this->k->queries)),
            'determinism' => ['chroma_sha256' => hash('sha256', $col['u'] . $col['v'])],
            'agents' => array_map(fn ($k) => ['agent' => $k] + $this->agentLog[$k], array_keys(array_intersect_key(self::AGENTS, $this->agentLog))),
        ];
        if (!empty($o['evaluate']) && isset($col['evaluation'])) {
            $manifest['evaluation'] = $col['evaluation'];
        }
        $this->agentLog['marking'] = ['task' => self::AGENTS['marking'], 'ms' => 0, 'result' => ['manifest' => basename($base) . '.colorization.json']];
        $manifest['agents'][] = ['agent' => 'marking'] + $this->agentLog['marking'];
        $manifest['elapsed_s'] = round(microtime(true) - $t0, 2);
        $manifest['manifest_file'] = $base . '.colorization.json';
        file_put_contents($manifest['manifest_file'], json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
        return $manifest;
    }

    private function agent(string $name, callable $fn): array
    {
        $t = hrtime(true);
        $r = $fn();
        $this->agentLog[$name] = ['task' => self::AGENTS[$name], 'ms' => round((hrtime(true) - $t) / 1e6, 1),
            'result' => array_filter($r, fn ($v, $k) => !in_array($k, ['luma', 'hi', 'rgb', 'u', 'v', 'scene', 'scene_rows', 'regions_in', 'boost', 'evaluation', 'cb', 'cr', 'material_ms'], true) && !is_array($v), ARRAY_FILTER_USE_BOTH)];
        return $r;
    }

    // ------------------------------------------------------------------ 1 · ingest

    private function ingest(string $input, array $o): array
    {
        if (!is_file($input)) {
            throw new RuntimeException('Input not found: ' . $input);
        }
        $info = MediaCodec::probe($input);
        if (!$info['video']) {
            throw new RuntimeException('No picture stream in ' . basename($input));
        }
        $ext = strtolower(pathinfo($input, PATHINFO_EXTENSION));
        $video = !in_array($ext, ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'gif'], true) && $info['duration_s'] > 0.2;
        $fps = $video ? self::fps($input) : '1/1';
        [$fn, $fd] = array_map('intval', explode('/', $fps)) + [1 => 1];
        $ww = min(self::WORK_W, $info['width']) & ~1;
        $wh = max(2, (int) round($ww * $info['height'] / $info['width'] / 2) * 2);
        $limit = $video ? ['-t', (string) (float) ($o['max_seconds'] ?? 10)] : ['-frames:v', '1'];
        $raw = MediaCodec::exec(array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-i', $input], $limit,
            ['-vf', "scale={$ww}:{$wh}:flags=area,format=gray", '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1']));
        $frames = intdiv(strlen($raw['stdout']), $ww * $wh);
        if ($frames < 1) {
            throw new RuntimeException('Could not read frames: ' . trim($raw['stderr']));
        }
        // Texture is measured at twice the analysis resolution: fine detail (leaves, grass,
        // grain of a surface) averages away at the size colour is synthesised at.
        $hw = min($info['width'], $ww * 2) & ~1;
        $hh = max(2, (int) round($hw * $info['height'] / $info['width'] / 2) * 2);
        $hi = MediaCodec::exec(array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-i', $input], $limit,
            ['-vf', "scale={$hw}:{$hh}:flags=area,format=gray", '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1']))['stdout'];
        $r = ['video' => $video, 'w' => $info['width'], 'h' => $info['height'], 'ww' => $ww, 'wh' => $wh, 'frames' => $frames, 'fps_text' => $fps,
            'fps' => $fd > 0 ? $fn / $fd : 1.0, 'seconds' => $video ? round($frames * $fd / max(1, $fn), 3) : 0, 'luma' => $raw['stdout'], 'limit' => $limit,
            'hw' => $hw, 'hh' => $hh, 'hi' => $hi];
        if (!empty($o['evaluate'])) {
            $rgb = MediaCodec::exec(array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-i', $input], $limit,
                ['-vf', "scale={$ww}:{$wh}:flags=area", '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']));
            $r['rgb'] = $rgb['stdout'];
        }
        return $r;
    }

    private static function fps(string $input): string
    {
        $probe = dirname(MediaCodec::ffmpeg()) . '/ffprobe';
        $r = MediaCodec::exec([is_executable($probe) ? $probe : 'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate', '-of', 'csv=p=0', $input]);
        $f = trim($r['stdout']);
        return preg_match('#^\d+/\d+$#', $f) && !str_starts_with($f, '0/') ? $f : '30/1';
    }

    // ------------------------------------------------------------------ 2 · knowledge

    private function knowledge(array $o): array
    {
        $rows = [];
        foreach (self::parseScene($o['scene'] ?? '') as [$p, $v]) {
            $rows[] = ['scene', $p, $v, 'user'];
        }
        foreach ((array) ($o['facts'] ?? []) as $line) {
            $parts = array_map('trim', explode('|', (string) $line));
            if (count($parts) === 3 && $parts[0] !== '' && $parts[2] !== '') {
                $rows[] = [$parts[0], $parts[1], $parts[2], 'user'];
            }
        }
        $regions = [];
        foreach ((array) ($o['regions'] ?? []) as $spec) {
            if (preg_match('/^\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*=\s*(.+?)\s*$/', (string) $spec, $m)) {
                $box = [(float) $m[1], (float) $m[2], (float) $m[3], (float) $m[4]];
                $rows[] = ['region:' . implode(',', $box), 'depicts', $m[5], 'user'];
                $regions[] = ['box' => $box, 'label' => $m[5]];
            }
        }
        $this->k->addFacts(ColorKnowledge::records($rows));
        $scene = [];
        foreach ($this->k->ask('FIND fact WHERE subject = "scene" LIMIT 50') as $f) {
            $scene[(string) $f['nucleus']['predicate']][] = (string) $f['nucleus']['object'];
        }
        $boost = [];
        foreach (array_merge($scene['setting'] ?? [], $scene['contains'] ?? []) as $s) {
            foreach ($this->k->materialsFor(Ufcs::norm($s)) as $mat) {
                $boost[$mat] = $mat;
            }
        }
        return ['scene' => $scene, 'scene_rows' => array_map(fn ($r) => $r[0] . ' | ' . $r[1] . ' | ' . $r[2], $rows), 'boost' => $boost,
            'regions_in' => $regions, 'scene_facts' => count($rows), 'materials_boosted' => count($boost)];
    }

    /** @return array<int, array{0:string,1:string}> */
    public static function parseScene(string|array $scene): array
    {
        $pairs = [];
        $alias = ['time' => 'time_of_day', 'when' => 'era', 'place' => 'setting', 'with' => 'contains'];
        foreach (is_array($scene) ? $scene : preg_split('/[;\n]/', $scene) as $k => $v) {
            if (!is_int($k)) {
                $item = $k . '=' . $v;
            } else {
                $item = (string) $v;
            }
            if (!str_contains($item, '=')) {
                continue;
            }
            [$p, $val] = array_map('trim', explode('=', $item, 2));
            $p = $alias[strtolower($p)] ?? strtolower($p);
            foreach (array_filter(array_map('trim', explode(',', $val))) as $one) {
                $pairs[] = [$p, strtolower(str_replace(' ', '_', $one))];
            }
        }
        return $pairs;
    }

    private function lighting(array $scene): array
    {
        $name = $scene['time_of_day'][0] ?? null;
        $g = $name ? $this->k->gradeFor($name) : null;
        $sky = $name ? $this->k->skyMaterialFor($name) : null;
        return ['name' => $g ? $name : 'unstated (neutral)', 'saturation' => $g['saturation'] ?? 1.0, 'warmth' => $g['warmth'] ?? 0.0,
            'sky_material' => $sky ?? 'sky_clear', 'fuid' => $g['fact']['fuid'] ?? null];
    }

    private function era(array $scene): array
    {
        $name = $scene['era'][0] ?? null;
        $g = $name ? $this->k->gradeFor('era:' . $name) : null;
        return ['name' => $g ? $name : 'unstated (neutral)', 'saturation' => $g['saturation'] ?? 1.0, 'warmth' => $g['warmth'] ?? 0.0, 'fuid' => $g['fact']['fuid'] ?? null];
    }

    /** Colour per class (and per region label) from facts. */
    private function palette(array $know, array $light): array
    {
        $pal = [];
        $subjects = array_combine(self::CLASSES, self::CLASSES);
        $subjects['sky'] = $light['sky_material'];
        foreach ($know['regions_in'] as $r) {
            $subjects[$r['label']] = $r['label'];
        }
        foreach ($subjects as $class => $subject) {
            $hit = $this->k->colorOf($subject);
            if ($hit === null) {
                $pal[$class] = ['class' => $class, 'subject' => $subject, 'hex' => null, 'trust' => 0.0, 'fuid' => null, 'source' => 'no fact: withheld'];
                continue;
            }
            [$hex, $fact] = $hit;
            [$cb, $cr] = self::chroma($hex);
            $pal[$class] = ['class' => $class, 'subject' => $subject, 'hex' => strtoupper($hex), 'trust' => (float) $fact['certification']['trust_score'],
                'fuid' => $fact['fuid'], 'source' => $fact['sources'][0]['name'], 'cb' => $cb, 'cr' => $cr];
        }
        return $pal;
    }

    /** BT.601 full-range chroma offsets of an sRGB colour (what yuvj444p expects). */
    public static function chroma(string $hex): array
    {
        [$r, $g, $b] = array_map('hexdec', str_split(ltrim($hex, '#'), 2));
        $y = 0.299 * $r + 0.587 * $g + 0.114 * $b;
        return [($b - $y) * 0.564, ($r - $y) * 0.713];
    }

    // ------------------------------------------------------------------ 5 · material + 6 · colorist

    private function colorize(array $ing, array $know, array $pal, array $grade, array $o): array
    {
        $W = $ing['ww'];
        $H = $ing['wh'];
        $C = self::CELL;
        $cw = intdiv($W + $C - 1, $C);
        $ch = intdiv($H + $C - 1, $C);
        $n = $W * $H;
        // Lookup tables: range weight by luminance difference, luminance weight for chroma.
        $rangeW = [];
        for ($d = 0; $d < 256; $d++) {
            $rangeW[$d] = exp(-($d * $d) / (2 * 11 * 11));
        }
        $lumW = [];
        for ($l = 0; $l < 256; $l++) {
            $x = $l / 255;
            $lumW[$l] = max(0.0, min(1.0, 4 * $x * (1 - $x) * 1.35));
        }
        // Region overrides → cell labels.
        $forced = [];
        foreach ($know['regions_in'] as $r) {
            [$x0, $y0, $x1, $y1] = $r['box'];
            for ($cy = 0; $cy < $ch; $cy++) {
                for ($cx = 0; $cx < $cw; $cx++) {
                    $fx = ($cx + 0.5) * $C / $W;
                    $fy = ($cy + 0.5) * $C / $H;
                    if ($fx >= $x0 && $fx <= $x1 && $fy >= $y0 && $fy <= $y1) {
                        $forced[$cy * $cw + $cx] = $r['label'];
                    }
                }
            }
        }
        $prior = [];
        foreach (self::CLASSES as $cls) {
            $prior[$cls] = in_array($cls, self::SCENE_DEPENDENT, true) ? 0.25 : 1.0;
            if (isset($know['boost'][$cls]) || ($cls === 'sky' && array_intersect(['sky_clear', 'sky_dusk', 'sky_overcast'], $know['boost']))) {
                $prior[$cls] = 1.25;
            }
        }
        $u = '';
        $v = '';
        $emaScore = null;
        $emaCb = $emaCr = null;
        $tally = [];
        $withheld = 0;
        $neutral = 0;
        $cellsTotal = 0;
        $matMs = 0.0;
        $evalSum = ['de_color' => 0.0, 'de_gray' => 0.0, 'n' => 0, 'cf_color' => 0.0, 'cf_truth' => 0.0, 'frames' => 0];
        for ($f = 0; $f < $ing['frames']; $f++) {
            $t = hrtime(true);
            $L = array_values(unpack('C*', substr($ing['luma'], $f * $n, $n)));
            // Per-cell features.
            $mean = $std = $grad = array_fill(0, $cw * $ch, 0.0);
            $cnt = array_fill(0, $cw * $ch, 0);
            for ($y = 0; $y < $H; $y++) {
                $row = $y * $W;
                $cy = intdiv($y, $C) * $cw;
                for ($x = 0; $x < $W; $x++) {
                    $c = $cy + intdiv($x, $C);
                    $mean[$c] += $L[$row + $x];
                    $cnt[$c]++;
                }
            }
            // Texture (local deviation) and edge energy from the 2× luminance.
            $HW = $ing['hw'];
            $HH = $ing['hh'];
            $hn = $HW * $HH;
            $Lh = array_values(unpack('C*', substr($ing['hi'], $f * $hn, $hn)));
            $hcnt = array_fill(0, $cw * $ch, 0);
            $hsum = array_fill(0, $cw * $ch, 0.0);
            $sx = $W / $HW;
            $sy = $H / $HH;
            for ($y = 0; $y < $HH; $y++) {
                $row = $y * $HW;
                $cy = min($ch - 1, intdiv((int) ($y * $sy), $C)) * $cw;
                for ($x = 0; $x < $HW; $x++) {
                    $c = $cy + min($cw - 1, intdiv((int) ($x * $sx), $C));
                    $l = $Lh[$row + $x];
                    $hsum[$c] += $l;
                    $std[$c] += $l * $l;
                    $gx = $x + 1 < $HW ? abs($Lh[$row + $x + 1] - $l) : 0;
                    $gy = $y + 1 < $HH ? abs($Lh[$row + $HW + $x] - $l) : 0;
                    $grad[$c] += $gx + $gy;
                    $hcnt[$c]++;
                }
            }
            for ($c = 0; $c < $cw * $ch; $c++) {
                $mean[$c] /= max(1, $cnt[$c]);
            }
            // Row coherence: share of the cell's row with a similar luminance (water and
            // horizons span the frame; a wall or a face does not).
            $rowCoh = [];
            for ($cy = 0; $cy < $ch; $cy++) {
                for ($cx = 0; $cx < $cw; $cx++) {
                    $c = $cy * $cw + $cx;
                    $same = 0;
                    for ($xx = 0; $xx < $cw; $xx++) {
                        $same += abs($mean[$cy * $cw + $xx] - $mean[$c]) < 10 ? 1 : 0;
                    }
                    $rowCoh[$c] = $same / $cw;
                }
            }
            $scores = [];
            for ($c = 0; $c < $cw * $ch; $c++) {
                $k = max(1, $hcnt[$c]);
                $m = $mean[$c];
                $hm = $hsum[$c] / $k;
                $s = sqrt(max(0.0, $std[$c] / $k - $hm * $hm)) / 255;
                $g = $grad[$c] / $k / 255;
                $yy = (intdiv($c, $cw) + 0.5) / $ch;
                $scores[$c] = self::scoreCell($m / 255, $s, $g, $yy, $rowCoh[$c], $prior);
            }
            if ($emaScore !== null) { // temporal stability for video
                foreach ($scores as $c => $sc) {
                    foreach ($sc as $cls => $val) {
                        $scores[$c][$cls] = 0.5 * $val + 0.5 * $emaScore[$c][$cls];
                    }
                }
            }
            $emaScore = $scores;
            // Label, confidence, cell chroma.
            $label = [];
            $conf = [];
            foreach ($scores as $c => $sc) {
                $m = $mean[$c] / 255;
                if (isset($forced[$c])) {
                    $label[$c] = $forced[$c];
                    $conf[$c] = 0.9;
                    continue;
                }
                if ($m < 0.07 || $m > 0.95) {
                    $label[$c] = 'neutral';
                    $conf[$c] = 0.0;
                    continue;
                }
                arsort($sc);
                $keys = array_keys($sc);
                $top = $sc[$keys[0]];
                $second = $sc[$keys[1]] ?? 0.0;
                $label[$c] = $keys[0];
                $conf[$c] = max(0.0, min(1.0, min(1.0, $top * 1.6) * max(0.0, min(1.0, 0.55 + ($top - $second) * 2.5))));
            }
            $label = self::smoothLabels($label, $conf, $cw, $ch);
            $cb = $cr = array_fill(0, $cw * $ch, 0.0);
            foreach ($label as $c => $cls) {
                $cellsTotal++;
                if ($cls === 'neutral') {
                    $neutral++;
                    continue;
                }
                $p = $pal[$cls] ?? null;
                $cc = $p && $p['hex'] !== null ? min($conf[$c], $p['trust']) : 0.0; // F224
                $tally[$cls]['cells'] = ($tally[$cls]['cells'] ?? 0) + 1;
                $tally[$cls]['conf'] = ($tally[$cls]['conf'] ?? 0) + $cc;
                if ($cc < self::WITHHOLD_BELOW) { // F182: keep the observed gray
                    $withheld++;
                    $tally[$cls]['withheld'] = ($tally[$cls]['withheld'] ?? 0) + 1;
                    continue;
                }
                $w = min(1.0, ($cc - self::WITHHOLD_BELOW) / 0.25 + 0.35);
                $cb[$c] = $p['cb'] * $w;
                $cr[$c] = $p['cr'] * $w;
            }
            if ($emaCb !== null) {
                foreach ($cb as $c => $_) {
                    $cb[$c] = 0.6 * $cb[$c] + 0.4 * $emaCb[$c];
                    $cr[$c] = 0.6 * $cr[$c] + 0.4 * $emaCr[$c];
                }
            }
            $emaCb = $cb;
            $emaCr = $cr;
            $matMs += (hrtime(true) - $t) / 1e6;
            // Edge-aware upsampling of cell chroma to pixels (joint bilateral on luminance).
            $sat = $grade['saturation'];
            $warm = $grade['warmth'] * 60;
            $ub = $vb = '';
            $truth = isset($ing['rgb']) ? substr($ing['rgb'], $f * $n * 3, $n * 3) : null;
            for ($y = 0; $y < $H; $y++) {
                $fy = ($y + 0.5) / $C - 0.5;
                $cy0 = (int) floor($fy);
                for ($x = 0; $x < $W; $x++) {
                    $fx = ($x + 0.5) / $C - 0.5;
                    $cx0 = (int) floor($fx);
                    $l = $L[$y * $W + $x];
                    $sw = $sb = $sr = 0.0;
                    for ($j = 0; $j <= 1; $j++) {
                        $yy = $cy0 + $j;
                        if ($yy < 0 || $yy >= $ch) {
                            continue;
                        }
                        $wy = 1 - abs($fy - $yy);
                        for ($i = 0; $i <= 1; $i++) {
                            $xx = $cx0 + $i;
                            if ($xx < 0 || $xx >= $cw) {
                                continue;
                            }
                            $c = $yy * $cw + $xx;
                            $wgt = $wy * (1 - abs($fx - $xx)) * $rangeW[(int) abs($l - $mean[$c])] + 1e-6;
                            $sw += $wgt;
                            $sb += $wgt * $cb[$c];
                            $sr += $wgt * $cr[$c];
                        }
                    }
                    $lw = $lumW[$l];
                    $bb = ($sb / $sw) * $sat * $lw - $warm * $lw * 0.5;
                    $rr = ($sr / $sw) * $sat * $lw + $warm * $lw;
                    $bb = max(-127, min(127, (int) round($bb)));
                    $rr = max(-127, min(127, (int) round($rr)));
                    $ub .= chr(128 + $bb);
                    $vb .= chr(128 + $rr);
                    if ($truth !== null && ($x % 2 === 0) && ($y % 2 === 0)) {
                        self::evalPixel($evalSum, $l, $bb, $rr, ord($truth[($y * $W + $x) * 3]), ord($truth[($y * $W + $x) * 3 + 1]), ord($truth[($y * $W + $x) * 3 + 2]));
                    }
                }
            }
            $u .= $ub;
            $v .= $vb;
        }
        $regions = [];
        foreach ($tally as $cls => $t) {
            $regions[$cls] = ['share_pct' => round(100 * $t['cells'] / max(1, $cellsTotal), 1), 'mean_confidence' => round($t['conf'] / max(1, $t['cells']), 3),
                'withheld_pct' => round(100 * ($t['withheld'] ?? 0) / max(1, $t['cells']), 1), 'color' => $pal[$cls]['hex'] ?? null];
        }
        uasort($regions, fn ($a, $b) => $b['share_pct'] <=> $a['share_pct']);
        $r = ['u' => $u, 'v' => $v, 'regions' => $regions, 'material_ms' => round($matMs, 1),
            'withheld_pct' => round(100 * $withheld / max(1, $cellsTotal), 1), 'neutral_pct' => round(100 * $neutral / max(1, $cellsTotal), 1),
            'frames' => $ing['frames'], 'cells_per_frame' => $cw * $ch];
        if ($evalSum['n'] > 0 && $evalSum['cf_truth'] / $evalSum['n'] < 2.0) {
            // The source has no colour of its own (a true black-and-white input): nothing to score against.
            $r['evaluation'] = ['skipped' => 'The source is black and white, so there is no original colour to score against.'];
        } elseif ($evalSum['n'] > 0) {
            $r['evaluation'] = ['mean_delta_e_colorized' => round($evalSum['de_color'] / $evalSum['n'], 2), 'mean_delta_e_gray' => round($evalSum['de_gray'] / $evalSum['n'], 2),
                'improvement_pct' => round(100 * (1 - $evalSum['de_color'] / max(1e-9, $evalSum['de_gray'])), 1),
                'colorfulness_colorized' => round($evalSum['cf_color'] / $evalSum['n'], 1), 'colorfulness_truth' => round($evalSum['cf_truth'] / $evalSum['n'], 1),
                'note' => 'CIE76 ΔE in Lab against the colour original at analysis resolution; gray = the black-and-white input.'];
        }
        return $r;
    }

    /** Material class scores for one cell. m = mean luminance, s = texture, g = edge energy, y = vertical position (0 top). */
    private static function scoreCell(float $m, float $s, float $g, float $y, float $row, array $prior): array
    {
        $ss = fn (float $x, float $a, float $b) => $x <= $a ? 0.0 : ($x >= $b ? 1.0 : (($x - $a) / ($b - $a)) ** 2 * (3 - 2 * ($x - $a) / ($b - $a)));
        $band = fn (float $x, float $a, float $b, float $c, float $d) => min($ss($x, $a, $b), 1 - $ss($x, $c, $d));
        $smooth = 1 - $ss($s, 0.02, 0.08);
        $tex = $ss($s, 0.035, 0.10);
        $edgy = $ss($g, 0.03, 0.09);
        $sc = [
            'sky' => $ss($m, 0.3, 0.55) * $smooth * (1 - $ss($y, 0.3, 0.65)),
            'foliage' => $tex * $band($m, 0.07, 0.16, 0.45, 0.6) * (0.55 + 0.45 * $ss($y, 0.15, 0.45)),
            'grass' => $band($s, 0.015, 0.035, 0.09, 0.14) * $band($m, 0.2, 0.3, 0.55, 0.7) * $ss($y, 0.4, 0.7),
            'water' => $smooth * $band($m, 0.18, 0.28, 0.6, 0.75) * $ss($y, 0.35, 0.6) * $ss($row, 0.35, 0.7),
            'sand' => $smooth * $band($m, 0.45, 0.55, 0.85, 0.95) * $ss($y, 0.45, 0.7) * (0.5 + 0.5 * $ss($row, 0.3, 0.6)),
            'soil' => (1 - $ss($s, 0.05, 0.12)) * $band($m, 0.1, 0.18, 0.35, 0.45) * $ss($y, 0.55, 0.8),
            // Stone: built surfaces — edges without fine texture, or flat mid-gray patches that do not span the frame.
            'stone' => max($edgy * (1 - $ss($s, 0.05, 0.09)), $smooth * (1 - $ss($row, 0.3, 0.6)) * 0.8) * $band($m, 0.25, 0.35, 0.72, 0.85) * 0.9,
            'brick' => $edgy * $band($m, 0.18, 0.28, 0.5, 0.6),
            'wood' => $band($s, 0.015, 0.035, 0.1, 0.15) * $band($m, 0.18, 0.28, 0.5, 0.6),
            'metal' => $smooth * $band($m, 0.4, 0.5, 0.8, 0.9) * $edgy,
            'skin' => (1 - $ss($s, 0.015, 0.06)) * $band($m, 0.35, 0.45, 0.7, 0.8),
        ];
        foreach ($sc as $k => $v) {
            $sc[$k] = $v * $prior[$k];
        }
        return $sc;
    }

    /** One pass of confidence-weighted majority over the 3×3 neighbourhood: coherent regions, no speckle. */
    private static function smoothLabels(array $label, array $conf, int $cw, int $ch): array
    {
        $out = $label;
        for ($cy = 0; $cy < $ch; $cy++) {
            for ($cx = 0; $cx < $cw; $cx++) {
                $c = $cy * $cw + $cx;
                if ($label[$c] === 'neutral' || $conf[$c] >= 0.9) {
                    continue;
                }
                $votes = [];
                for ($dy = -1; $dy <= 1; $dy++) {
                    for ($dx = -1; $dx <= 1; $dx++) {
                        $x = $cx + $dx;
                        $y = $cy + $dy;
                        if ($x < 0 || $y < 0 || $x >= $cw || $y >= $ch) {
                            continue;
                        }
                        $k = $y * $cw + $x;
                        if ($label[$k] !== 'neutral') {
                            $votes[$label[$k]] = ($votes[$label[$k]] ?? 0) + $conf[$k] + 0.05;
                        }
                    }
                }
                if ($votes) {
                    arsort($votes);
                    $out[$c] = array_key_first($votes);
                }
            }
        }
        return $out;
    }

    /** Accumulate ΔE (CIE76) of colorized and of gray against the true colour, plus colourfulness. */
    private static function evalPixel(array &$acc, int $l, int $cb, int $cr, int $tr, int $tg, int $tb): void
    {
        // BT.601 full-range inverse of the forward transform used in chroma():
        $r = max(0, min(255, (int) round($l + $cr / 0.713)));
        $b = max(0, min(255, (int) round($l + $cb / 0.564)));
        $g = max(0, min(255, (int) round(($l - 0.299 * $r - 0.114 * $b) / 0.587)));
        $lab = self::lab($r, $g, $b);
        $gray = self::lab($l, $l, $l);
        $truth = self::lab($tr, $tg, $tb);
        $acc['de_color'] += sqrt(($lab[0] - $truth[0]) ** 2 + ($lab[1] - $truth[1]) ** 2 + ($lab[2] - $truth[2]) ** 2);
        $acc['de_gray'] += sqrt(($gray[0] - $truth[0]) ** 2 + ($gray[1] - $truth[1]) ** 2 + ($gray[2] - $truth[2]) ** 2);
        $acc['cf_color'] += sqrt($lab[1] ** 2 + $lab[2] ** 2);
        $acc['cf_truth'] += sqrt($truth[1] ** 2 + $truth[2] ** 2);
        $acc['n']++;
    }

    /** sRGB (0–255) → CIE L*a*b* (D65). */
    public static function lab(int $r, int $g, int $b): array
    {
        $lin = fn (int $c) => ($c /= 255) <= 0.04045 ? $c / 12.92 : (($c + 0.055) / 1.055) ** 2.4;
        [$R, $G, $B] = [$lin($r), $lin($g), $lin($b)];
        $X = (0.4124 * $R + 0.3576 * $G + 0.1805 * $B) / 0.95047;
        $Y = 0.2126 * $R + 0.7152 * $G + 0.0722 * $B;
        $Z = (0.0193 * $R + 0.1192 * $G + 0.9505 * $B) / 1.08883;
        $f = fn (float $t) => $t > 0.008856 ? $t ** (1 / 3) : 7.787 * $t + 16 / 116;
        return [116 * $f($Y) - 16, 500 * ($f($X) - $f($Y)), 200 * ($f($Y) - $f($Z))];
    }

    // ------------------------------------------------------------------ 7 · upscale

    private function upscale(string $input, array $ing, array $targets, string $base, array $o): array
    {
        $outputs = [];
        foreach ($targets as $t) {
            $tw = self::targetWidth($t, $ing['w']);
            $th = (int) round($tw * $ing['h'] / $ing['w'] / 2) * 2;
            $up = $tw > $ing['w'];
            $luma = "[0:v]format=gray,scale={$tw}:{$th}:flags=lanczos" . ($up ? ',unsharp=5:5:0.5:3:3:0' : '') . ',setsar=1[y]';
            $fc = "$luma;[1:v]scale={$tw}:{$th}:flags=bicubic,setsar=1[u];[2:v]scale={$tw}:{$th}:flags=bicubic,setsar=1[v];[y][u][v]mergeplanes=0x001020:yuvj444p";
            $raw = fn (string $p) => ['-f', 'rawvideo', '-pix_fmt', 'gray', '-s', $ing['ww'] . 'x' . $ing['wh'], '-framerate', $ing['fps_text'], '-i', $p];
            $args = array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $input], $raw($base . '.u.raw'), $raw($base . '.v.raw'));
            $meta = ['-metadata', 'comment=QueryBook VCUM colorization: luminance observed, colour reconstructed by inference (Registry F225). See ' . basename($base) . '.colorization.json'];
            $file = null;
            if (!$ing['video']) {
                $fmt = $t === '16k' && ($o['still_16k'] ?? 'jpg') !== 'png' ? 'jpg' : 'png';
                $file = "{$base}-{$t}.{$fmt}";
                $args = array_merge($args, ['-filter_complex', $fc . ($fmt === 'jpg' ? ',format=yuvj420p' : ',format=rgb24'), '-frames:v', '1'], $fmt === 'jpg' ? ['-q:v', '2'] : [], [$file]);
            } elseif ($t === '16k') {
                $dir = "{$base}-16k-frames";
                @mkdir($dir, 0775, true);
                $max = (int) ($o['max_16k_frames'] ?? 30);
                $file = $dir;
                $args = array_merge($args, ['-filter_complex', $fc . ',format=yuvj420p', '-frames:v', (string) min($max, $ing['frames']), '-q:v', '3', $dir . '/frame_%05d.jpg']);
            } else {
                $file = "{$base}-{$t}.mp4";
                $codec = $t === '4k' ? ['-c:v', 'libx265', '-preset', 'fast', '-crf', '22', '-x265-params', 'log-level=error', '-tag:v', 'hvc1'] : ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18'];
                $args = array_merge($args, ['-filter_complex', $fc . ',format=yuv420p', '-frames:v', (string) $ing['frames']], $codec, ['-map', '0:a?', '-c:a', 'aac', '-b:a', '160k', '-shortest'], $meta, ['-movflags', '+faststart', $file]);
            }
            $tm = hrtime(true);
            $r = MediaCodec::exec($args);
            $ms = round((hrtime(true) - $tm) / 1e6, 1);
            if ($r['code'] !== 0) {
                throw new RuntimeException("Upscale to $t failed: " . trim($r['stderr']));
            }
            $bytes = is_dir($file) ? array_sum(array_map('filesize', glob($file . '/*.jpg') ?: [])) : filesize($file);
            $frames = is_dir($file) ? count(glob($file . '/*.jpg') ?: []) : ($ing['video'] ? $ing['frames'] : 1);
            $outputs[$t] = ['target' => strtoupper($t), 'width' => $tw, 'height' => $th, 'file' => $file, 'format' => is_dir($file) ? 'JPEG frame sequence' : strtoupper(pathinfo($file, PATHINFO_EXTENSION)),
                'frames' => $frames, 'bytes' => $bytes, 'render_ms' => $ms, 'scale_factor' => round($tw / $ing['w'], 2),
                'consistency_psnr_db' => $this->consistency($input, $file, $ing), 'sha256' => is_dir($file) ? hash('sha256', implode('', array_map('hash_file', array_fill(0, $frames, 'sha256'), glob($file . '/*.jpg') ?: []))) : hash_file('sha256', $file)];
        }
        return $outputs;
    }

    /** Output width for a target: a named size, a scale factor ("2x") or an explicit width ("w640"); always even. */
    public static function targetWidth(string $t, int $sourceWidth): int
    {
        if (isset(self::TARGETS[$t])) {
            return self::TARGETS[$t];
        }
        if (preg_match('/^(\d+(?:\.\d+)?)x$/', $t, $m)) {
            return max(2, (int) round($sourceWidth * (float) $m[1] / 2) * 2);
        }
        return max(2, (int) round((int) substr($t, 1) / 2) * 2);
    }

    /**
     * Consistency with the source (F22: resolution enhancement must stay consistent
     * with what was observed): bring the output back to the source size and compare
     * its luminance with the source's, frame by frame. Both sides get a 1-pixel
     * Gaussian blur first, so grain moved by resampling does not count — what is
     * measured is whether the picture's structure changed. High = nothing invented.
     */
    private function consistency(string $input, string $out, array $ing): ?float
    {
        $src = is_dir($out) ? ($out . '/frame_00001.jpg') : $out;
        $n = $ing['video'] ? (is_dir($out) ? 1 : min(60, $ing['frames'])) : 1;
        $r = MediaCodec::exec([MediaCodec::ffmpeg(), '-hide_banner', '-nostats', '-i', $src, '-i', $input, '-lavfi',
            "[0:v]scale={$ing['w']}:{$ing['h']}:flags=bicubic,format=gray,gblur=sigma=1,trim=end_frame={$n},setpts=N/30/TB[a];"
            . "[1:v]format=gray,gblur=sigma=1,trim=end_frame={$n},setpts=N/30/TB[b];[a][b]psnr", '-f', 'null', '-']);
        return preg_match('/PSNR .*average:([\d.]+|inf)/', $r['stderr'], $m) ? ($m[1] === 'inf' ? 99.0 : round((float) $m[1], 2)) : null;
    }

    /** Side-by-side preview (source gray | colorized), 960 px wide each half. */
    private function preview(string $input, array $ing, string $base): ?string
    {
        $file = $base . '-preview.png';
        $pw = 640;
        $ph = (int) round($pw * $ing['h'] / $ing['w'] / 2) * 2;
        $raw = fn (string $p) => ['-f', 'rawvideo', '-pix_fmt', 'gray', '-s', $ing['ww'] . 'x' . $ing['wh'], '-framerate', $ing['fps_text'], '-i', $p];
        $fc = "[0:v]format=gray,scale={$pw}:{$ph}:flags=lanczos,setsar=1,split[y][g];[1:v]scale={$pw}:{$ph}:flags=bicubic,setsar=1[u];[2:v]scale={$pw}:{$ph}:flags=bicubic,setsar=1[v];"
            . "[y][u][v]mergeplanes=0x001020:yuvj444p,format=rgb24[c];[g]format=rgb24[gr];[gr][c]hstack=inputs=2";
        $r = MediaCodec::exec(array_merge([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', $input], $raw($base . '.u.raw'), $raw($base . '.v.raw'),
            ['-filter_complex', $fc, '-frames:v', '1', $file]));
        return $r['code'] === 0 ? $file : null;
    }
}

/** Synthetic test scenes with known colour, for demos and ground-truth scoring. */
final class DemoScenes
{
    /**
     * A landscape built from the materials the engine knows: sky, wooded hills,
     * a lake, a sandy shore, a grass field and a stone building, with sensor
     * noise. Deterministic. Because it is built from the same material
     * classes, its score measures the pipeline, not real-world accuracy.
     */
    public static function landscape(string $path, int $w = 1280, int $h = 720): void
    {
        $img = imagecreatetruecolor($w, $h);
        mt_srand(42);
        $col = fn (int $r, int $g, int $b) => imagecolorallocate($img, max(0, min(255, $r)), max(0, min(255, $g)), max(0, min(255, $b)));
        for ($y = 0; $y < (int) ($h * 0.42); $y++) { // sky gradient
            $t = $y / ($h * 0.42);
            imageline($img, 0, $y, $w, $y, $col((int) (92 + 70 * $t), (int) (128 + 60 * $t), (int) (196 + 30 * $t)));
        }
        $hill = [];
        for ($x = 0; $x <= $w; $x += 8) {
            $hill[] = $x;
            $hill[] = (int) ($h * 0.36 + 40 * sin($x / 140) + 22 * sin($x / 47));
        }
        array_push($hill, $w, (int) ($h * 0.55), 0, (int) ($h * 0.55));
        imagefilledpolygon($img, $hill, $col(70, 104, 58));
        imagefilledrectangle($img, 0, (int) ($h * 0.55), $w, (int) ($h * 0.70), $col(52, 104, 142)); // lake
        imagefilledrectangle($img, 0, (int) ($h * 0.70), $w, (int) ($h * 0.78), $col(198, 182, 132)); // sand
        imagefilledrectangle($img, 0, (int) ($h * 0.78), $w, $h, $col(96, 146, 62)); // grass
        $bx = (int) ($w * 0.66);
        imagefilledrectangle($img, $bx, (int) ($h * 0.28), $bx + (int) ($w * 0.16), (int) ($h * 0.55), $col(140, 138, 132)); // stone building
        for ($i = 0; $i < 6; $i++) {
            imagefilledrectangle($img, $bx + 18 + $i * 34, (int) ($h * 0.33), $bx + 32 + $i * 34, (int) ($h * 0.40), $col(60, 60, 64));
        }
        for ($y = 0; $y < $h; $y += 2) { // texture: strong in foliage and grass, light elsewhere
            for ($x = 0; $x < $w; $x += 2) {
                $rgb = imagecolorat($img, $x, $y);
                [$r, $g, $b] = [($rgb >> 16) & 255, ($rgb >> 8) & 255, $rgb & 255];
                $leafy = $g > $r + 20 && $g > $b;
                $n = $leafy ? mt_rand(-34, 34) : mt_rand(-5, 5);
                imagefilledrectangle($img, $x, $y, $x + 1, $y + 1, $col($r + $n, $g + $n, $b + $n));
            }
        }
        mt_srand();
        imagepng($img, $path);
        imagedestroy($img);
    }

    /** A short clip panning across the landscape (for video runs). */
    public static function landscapeClip(string $path, float $seconds = 3, int $w = 1280, int $h = 720): void
    {
        $still = $path . '.still.png';
        self::landscape($still, (int) ($w * 1.25), $h);
        $r = MediaCodec::exec([MediaCodec::ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '30', '-i', $still, '-t', (string) $seconds,
            '-vf', "crop={$w}:{$h}:'(in_w-{$w})*t/{$seconds}':0,format=yuv420p", '-c:v', 'libx264', '-crf', '14', '-preset', 'veryfast', $path]);
        @unlink($still);
        if ($r['code'] !== 0) {
            throw new RuntimeException('clip render failed: ' . $r['stderr']);
        }
    }
}
