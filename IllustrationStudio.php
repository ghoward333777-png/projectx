<?php

declare(strict_types=1);

/**
 * Illustration Studio
 *
 * Plans and renders the visual layer of a manuscript. For every chapter it
 * finds the important topics (the section beats inside the drafted text) and
 * generates media after each one:
 *
 *  - diagram       — the chapter's path, drawn as a step flow (SVG, local)
 *  - chart         — where the chapter spends its attention (SVG bars, local)
 *  - graph         — reading momentum through the chapter (SVG line, local)
 *  - table         — structured data: job cards or a section overview (rows)
 *  - illustration  — a seeded, deterministic chapter emblem (SVG, local)
 *  - ai-image      — a detailed prompt plus a ready-to-send provider request
 *
 * Local kinds render instantly with no accounts or keys. AI images follow the
 * same adapter pattern as the audiobook: the studio emits a manifest of
 * request payloads and bin/generate-images.php performs the calls with the
 * user's own key (Google, OpenAI, or Stability).
 *
 * Users can add more illustrations to any chapter or section: pass extra
 * media rows and they are planned, rendered, and exported with the rest.
 *
 * Figure palette (validated for contrast and CVD separation on the paper
 * surface): data #2b62ad, emphasis #b45309, ink #202431, grid #d8d0c2.
 */
final class IllustrationStudio
{
    public const KINDS = ['diagram', 'chart', 'graph', 'table', 'illustration', 'ai-image'];
    public const PROVIDERS = ['google', 'openai', 'stability'];

    private const DATA = '#2b62ad';
    private const EMPHASIS = '#b45309';
    private const INK = '#202431';
    private const MUTED = '#5a6070';
    private const GRID = '#d8d0c2';
    private const PAPER = '#f8f4eb';

    private const PROVIDER_LABELS = [
        'google' => 'Google Imagen (Generative Language API)',
        'openai' => 'OpenAI Images (gpt-image-1)',
        'stability' => 'Stability AI (Stable Image Core)',
    ];

    /**
     * Plan the media set for a whole book.
     *
     * @param array<string, mixed> $book Output of generateBookFromTableOfContents().
     * @param array<string, mixed> $metadata Listing metadata (title, author).
     * @param array<int|string, array<int, array<string, mixed>>> $extraMedia
     *   User-added rows keyed by chapter number: [['kind' => ..., 'topic' => ..., 'caption' => ...], ...]
     * @return array{chapters: array<int, array<string, mixed>>, figure_count: int, ai_image_count: int}
     */
    public function planBookMedia(array $book, array $metadata, array $extraMedia = []): array
    {
        $chapters = [];
        $figureCount = 0;
        $aiCount = 0;
        foreach ((array) ($book['chapters'] ?? []) as $chapter) {
            $number = (int) ($chapter['number'] ?? 0);
            $items = $this->planChapterMedia($chapter, $book, $metadata);
            foreach ((array) ($extraMedia[$number] ?? $extraMedia[(string) $number] ?? []) as $extraIndex => $extra) {
                if (!is_array($extra)) {
                    continue;
                }
                $item = $this->buildUserItem($chapter, $book, $metadata, $extra, $extraIndex);
                if ($item !== null) {
                    $items[] = $item;
                }
            }
            $figureCount += count($items);
            foreach ($items as $item) {
                if ($item['kind'] === 'ai-image') {
                    $aiCount++;
                }
            }
            $chapters[] = [
                'number' => $number,
                'title' => (string) ($chapter['title'] ?? ''),
                'sections' => array_map(
                    static fn (array $section): array => ['title' => $section['title'], 'word_count' => $section['word_count']],
                    $this->chapterSections($chapter),
                ),
                'items' => $items,
            ];
        }
        return ['chapters' => $chapters, 'figure_count' => $figureCount, 'ai_image_count' => $aiCount];
    }

    /**
     * The important topics of a chapter: its internal section beats, with the
     * words each one carries. Short heading-like blocks open a section.
     *
     * @param array<string, mixed> $chapter
     * @return array<int, array{title: string, word_count: int, block_index: int}>
     */
    public function chapterSections(array $chapter): array
    {
        $blocks = (array) ($chapter['blocks'] ?? []);
        $sections = [];
        $current = null;
        foreach ($blocks as $index => $block) {
            $content = trim((string) ($block['content'] ?? ''));
            if ($content === '') {
                continue;
            }
            $isHeading = $index > 0
                && mb_strlen($content) <= 60
                && !str_contains($content, '. ')
                && !str_ends_with($content, '.')
                && substr_count($content, "\n") === 0;
            if ($isHeading) {
                if ($current !== null) {
                    $sections[] = $current;
                }
                $current = ['title' => $content, 'word_count' => 0, 'block_index' => (int) $index];
                continue;
            }
            $words = count(preg_split('/\s+/u', $content, -1, PREG_SPLIT_NO_EMPTY) ?: []);
            if ($current === null) {
                $current = ['title' => 'Opening', 'word_count' => 0, 'block_index' => 0];
            }
            $current['word_count'] += $words;
        }
        if ($current !== null) {
            $sections[] = $current;
        }
        return $sections;
    }

    /**
     * The default media set for one chapter: one figure after each important topic.
     *
     * @param array<string, mixed> $chapter
     * @param array<string, mixed> $book
     * @param array<string, mixed> $metadata
     * @return array<int, array<string, mixed>>
     */
    public function planChapterMedia(array $chapter, array $book, array $metadata): array
    {
        $number = (int) ($chapter['number'] ?? 0);
        $title = (string) ($chapter['title'] ?? '');
        $sections = $this->chapterSections($chapter);
        $jobs = $this->chapterJobRows($chapter, $book);
        $items = [];

        $items[] = $this->aiImageItem($number, $title, $chapter, $metadata);
        if (count($sections) >= 2) {
            $items[] = [
                'id' => 'ch' . $number . '-diagram',
                'kind' => 'diagram',
                'title' => 'The path through this chapter',
                'caption' => 'Each step is one of the chapter\'s important topics, in reading order.',
                'after_section' => $sections[0]['title'],
                'svg' => $this->renderDiagram(array_column($sections, 'title'), $title),
            ];
            $items[] = [
                'id' => 'ch' . $number . '-chart',
                'kind' => 'chart',
                'title' => 'Where this chapter spends its attention',
                'caption' => 'Words devoted to each topic — longer bars carry more of the argument.',
                'after_section' => $sections[(int) floor(count($sections) / 2)]['title'],
                'svg' => $this->renderChart($sections, $title),
            ];
        }
        if (count($sections) >= 4) {
            $items[] = [
                'id' => 'ch' . $number . '-graph',
                'kind' => 'graph',
                'title' => 'Reading momentum',
                'caption' => 'How the chapter accumulates, topic by topic, to its full length.',
                'after_section' => $sections[count($sections) - 2]['title'],
                'svg' => $this->renderGraph($sections, $title),
            ];
        }
        $table = $jobs !== []
            ? $this->buildJobTable($jobs)
            : (count($sections) >= 2 ? $this->buildSectionTable($sections) : null);
        if ($table !== null) {
            $items[] = [
                'id' => 'ch' . $number . '-table',
                'kind' => 'table',
                'title' => $jobs !== [] ? 'Job cards at a glance' : 'Chapter topics at a glance',
                'caption' => $jobs !== []
                    ? 'The jobs this chapter explores, side by side.'
                    : 'Every important topic with its role and weight.',
                'after_section' => $sections !== [] ? $sections[count($sections) - 1]['title'] : 'Opening',
                'table' => $table,
            ];
        }
        $items[] = [
            'id' => 'ch' . $number . '-illustration',
            'kind' => 'illustration',
            'title' => 'Chapter emblem',
            'caption' => 'A closing mark for “' . $title . '”.',
            'after_section' => $sections !== [] ? $sections[count($sections) - 1]['title'] : 'Opening',
            'svg' => $this->renderIllustration($number . ':' . $title, $title),
        ];
        return $items;
    }

    /**
     * Build one user-added media item for a specific chapter or section.
     *
     * @param array<string, mixed> $extra {kind, topic, caption?, section?}
     * @return array<string, mixed>|null
     */
    public function buildUserItem(array $chapter, array $book, array $metadata, array $extra, int $extraIndex): ?array
    {
        $kind = in_array($extra['kind'] ?? '', self::KINDS, true) ? (string) $extra['kind'] : 'illustration';
        $topic = trim((string) ($extra['topic'] ?? ''));
        if ($topic === '') {
            return null;
        }
        $number = (int) ($chapter['number'] ?? 0);
        $title = (string) ($chapter['title'] ?? '');
        $sections = $this->chapterSections($chapter);
        $caption = trim((string) ($extra['caption'] ?? '')) ?: 'Added illustration for “' . $topic . '”.';
        $afterSection = trim((string) ($extra['section'] ?? '')) ?: ($sections !== [] ? $sections[0]['title'] : 'Opening');
        $item = [
            'id' => 'ch' . $number . '-user-' . ($extraIndex + 1),
            'kind' => $kind,
            'title' => $topic,
            'caption' => $caption,
            'after_section' => $afterSection,
            'user_added' => true,
        ];
        if ($kind === 'diagram') {
            $item['svg'] = $this->renderDiagram(array_column($sections, 'title'), $topic);
        } elseif ($kind === 'chart') {
            $item['svg'] = $this->renderChart($sections, $topic);
        } elseif ($kind === 'graph') {
            $item['svg'] = $this->renderGraph($sections, $topic);
        } elseif ($kind === 'table') {
            $jobs = $this->chapterJobRows($chapter, $book);
            $item['table'] = $jobs !== [] ? $this->buildJobTable($jobs) : $this->buildSectionTable($sections);
        } elseif ($kind === 'illustration') {
            $item['svg'] = $this->renderIllustration($number . ':' . $topic, $topic);
        } else {
            $item['ai'] = [
                'prompt' => $this->aiPrompt($topic, $title, $metadata),
                'alt' => $topic,
            ];
            $item['svg'] = $this->renderAiPlaceholder($topic);
        }
        return $item;
    }

    /**
     * The image-synthesis manifest for every planned ai-image, with
     * ready-to-send provider payloads. Consumed by bin/generate-images.php.
     *
     * @param array{chapters: array<int, array<string, mixed>>} $plan
     * @return array<string, mixed>
     */
    public function imageManifest(array $plan, string $provider = 'google'): array
    {
        $provider = in_array($provider, self::PROVIDERS, true) ? $provider : 'google';
        $jobs = [];
        foreach ($plan['chapters'] as $chapter) {
            foreach ($chapter['items'] as $item) {
                if (($item['kind'] ?? '') !== 'ai-image' || !isset($item['ai']['prompt'])) {
                    continue;
                }
                $jobs[] = [
                    'id' => (string) $item['id'],
                    'chapter' => (int) $chapter['number'],
                    'title' => (string) $item['title'],
                    'prompt' => (string) $item['ai']['prompt'],
                    'output_file' => $item['id'] . '.png',
                    'request' => $this->requestPayload($provider, (string) $item['ai']['prompt']),
                ];
            }
        }
        return [
            'version' => 1,
            'provider' => $provider,
            'provider_label' => self::PROVIDER_LABELS[$provider],
            'job_count' => count($jobs),
            'jobs' => $jobs,
        ];
    }

    /**
     * The provider request for one image prompt.
     *
     * @return array<string, mixed>
     */
    public function requestPayload(string $provider, string $prompt): array
    {
        if ($provider === 'openai') {
            return [
                'endpoint' => 'https://api.openai.com/v1/images/generations',
                'method' => 'POST',
                'auth' => 'header Authorization: Bearer API_KEY',
                'body' => ['model' => 'gpt-image-1', 'prompt' => $prompt, 'size' => '1536x1024'],
                'response' => 'JSON with data[0].b64_json',
            ];
        }
        if ($provider === 'stability') {
            return [
                'endpoint' => 'https://api.stability.ai/v2beta/stable-image/generate/core',
                'method' => 'POST (multipart/form-data)',
                'auth' => 'header Authorization: Bearer API_KEY',
                'fields' => ['prompt' => $prompt, 'output_format' => 'png', 'aspect_ratio' => '3:2'],
                'response' => 'binary PNG (send Accept: image/*)',
            ];
        }
        return [
            'endpoint' => 'https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict',
            'method' => 'POST',
            'auth' => 'header x-goog-api-key: API_KEY',
            'body' => [
                'instances' => [['prompt' => $prompt]],
                'parameters' => ['sampleCount' => 1, 'aspectRatio' => '4:3'],
            ],
            'response' => 'JSON with predictions[0].bytesBase64Encoded',
        ];
    }

    /* ---------------- Local SVG renderers ---------------- */

    /** Step-flow diagram of the chapter's important topics. */
    public function renderDiagram(array $stepTitles, string $context): string
    {
        $steps = array_slice(array_values(array_filter(array_map('strval', $stepTitles), static fn (string $s): bool => trim($s) !== '')), 0, 6);
        if ($steps === []) {
            $steps = ['Begin', 'Develop', 'Apply'];
        }
        $boxWidth = 520;
        $boxHeight = 40;
        $gap = 26;
        $x = 60;
        $height = count($steps) * ($boxHeight + $gap) - $gap + 40;
        $svg = $this->svgOpen(640, $height, 'Step diagram: ' . $context);
        foreach ($steps as $index => $step) {
            $y = 20 + $index * ($boxHeight + $gap);
            $svg .= '<rect x="' . $x . '" y="' . $y . '" width="' . $boxWidth . '" height="' . $boxHeight . '" rx="8" fill="none" stroke="' . self::DATA . '" stroke-width="2"/>';
            $svg .= '<circle cx="' . ($x - 22) . '" cy="' . ($y + 20) . '" r="13" fill="' . self::DATA . '"/>';
            $svg .= '<text x="' . ($x - 22) . '" y="' . ($y + 25) . '" text-anchor="middle" font-size="13" font-weight="700" fill="' . self::PAPER . '">' . ($index + 1) . '</text>';
            $svg .= '<text x="' . ($x + 18) . '" y="' . ($y + 25) . '" font-size="15" fill="' . self::INK . '">' . $this->svgText($step, 58) . '</text>';
            if ($index < count($steps) - 1) {
                $arrowTop = $y + $boxHeight;
                $svg .= '<line x1="320" y1="' . $arrowTop . '" x2="320" y2="' . ($arrowTop + $gap - 6) . '" stroke="' . self::MUTED . '" stroke-width="2"/>';
                $svg .= '<path d="M320 ' . ($arrowTop + $gap) . ' l-5 -8 l10 0 z" fill="' . self::MUTED . '"/>';
            }
        }
        return $svg . '</svg>';
    }

    /** Horizontal bar chart: words per important topic. */
    public function renderChart(array $sections, string $context): string
    {
        $rows = array_slice($sections, 0, 8);
        if ($rows === []) {
            return $this->renderIllustration('chart:' . $context, $context);
        }
        $max = 1;
        foreach ($rows as $row) {
            $max = max($max, (int) $row['word_count']);
        }
        $barHeight = 20;
        $gap = 14;
        $chartLeft = 230;
        $chartWidth = 360;
        $height = count($rows) * ($barHeight + $gap) - $gap + 44;
        $svg = $this->svgOpen(640, $height, 'Bar chart: ' . $context);
        foreach ($rows as $index => $row) {
            $y = 16 + $index * ($barHeight + $gap);
            $width = max(6, intdiv(((int) $row['word_count']) * $chartWidth, $max));
            $svg .= '<text x="' . ($chartLeft - 10) . '" y="' . ($y + 15) . '" text-anchor="end" font-size="13" fill="' . self::INK . '">' . $this->svgText((string) $row['title'], 30) . '</text>';
            $svg .= '<rect x="' . $chartLeft . '" y="' . $y . '" width="' . $width . '" height="' . $barHeight . '" rx="4" fill="' . self::DATA . '"><title>' . $this->svgText((string) $row['title'] . ': ' . $row['word_count'] . ' words', 90) . '</title></rect>';
            $svg .= '<text x="' . ($chartLeft + $width + 8) . '" y="' . ($y + 15) . '" font-size="12" fill="' . self::MUTED . '">' . (int) $row['word_count'] . '</text>';
        }
        $axisY = 16 + count($rows) * ($barHeight + $gap) - $gap + 8;
        $svg .= '<line x1="' . $chartLeft . '" y1="10" x2="' . $chartLeft . '" y2="' . $axisY . '" stroke="' . self::GRID . '" stroke-width="1"/>';
        $svg .= '<text x="' . $chartLeft . '" y="' . ($axisY + 16) . '" font-size="11" fill="' . self::MUTED . '">words per topic</text>';
        return $svg . '</svg>';
    }

    /** Line graph: cumulative words across the chapter's topics. */
    public function renderGraph(array $sections, string $context): string
    {
        $rows = array_slice($sections, 0, 10);
        if (count($rows) < 2) {
            return $this->renderIllustration('graph:' . $context, $context);
        }
        $total = 0;
        $points = [];
        foreach ($rows as $row) {
            $total += (int) $row['word_count'];
            $points[] = $total;
        }
        $left = 60;
        $top = 20;
        $plotWidth = 540;
        $plotHeight = 180;
        $max = max(1, $total);
        $coords = [];
        foreach ($points as $index => $value) {
            $px = $left + intdiv($index * $plotWidth, max(1, count($points) - 1));
            $py = $top + $plotHeight - intdiv($value * $plotHeight, $max);
            $coords[] = [$px, $py];
        }
        $svg = $this->svgOpen(640, $plotHeight + 70, 'Line graph: ' . $context);
        for ($i = 1; $i <= 3; $i++) {
            $gy = $top + intdiv($plotHeight * $i, 4);
            $svg .= '<line x1="' . $left . '" y1="' . $gy . '" x2="' . ($left + $plotWidth) . '" y2="' . $gy . '" stroke="' . self::GRID . '" stroke-width="1"/>';
        }
        $svg .= '<line x1="' . $left . '" y1="' . ($top + $plotHeight) . '" x2="' . ($left + $plotWidth) . '" y2="' . ($top + $plotHeight) . '" stroke="' . self::MUTED . '" stroke-width="1"/>';
        $path = '';
        foreach ($coords as $index => [$px, $py]) {
            $path .= ($index === 0 ? 'M' : 'L') . $px . ' ' . $py . ' ';
        }
        $svg .= '<path d="' . trim($path) . '" fill="none" stroke="' . self::DATA . '" stroke-width="2"/>';
        [$lastX, $lastY] = $coords[count($coords) - 1];
        $svg .= '<circle cx="' . $lastX . '" cy="' . $lastY . '" r="5" fill="' . self::EMPHASIS . '"/>';
        $svg .= '<text x="' . ($lastX - 8) . '" y="' . ($lastY - 10) . '" text-anchor="end" font-size="12" font-weight="700" fill="' . self::INK . '">' . $total . ' words</text>';
        $svg .= '<text x="' . $left . '" y="' . ($top + $plotHeight + 24) . '" font-size="11" fill="' . self::MUTED . '">topic 1</text>';
        $svg .= '<text x="' . ($left + $plotWidth) . '" y="' . ($top + $plotHeight + 24) . '" text-anchor="end" font-size="11" fill="' . self::MUTED . '">topic ' . count($rows) . '</text>';
        return $svg . '</svg>';
    }

    /** Seeded, deterministic abstract emblem for a chapter or topic. */
    public function renderIllustration(string $seedText, string $context): string
    {
        $seed = crc32($seedText);
        $svg = $this->svgOpen(640, 200, 'Illustration: ' . $context);
        $palette = [self::DATA, self::EMPHASIS, self::MUTED];
        for ($i = 0; $i < 6; $i++) {
            $h = ($seed >> ($i * 5)) & 0xFF;
            $cx = 80 + (($h * 7 + $i * 89) % 480);
            $cy = 50 + (($h * 11 + $i * 37) % 100);
            $r = 14 + (($h + $i * 13) % 42);
            $color = $palette[($h + $i) % 3];
            $svg .= '<circle cx="' . $cx . '" cy="' . $cy . '" r="' . $r . '" fill="' . $color . '" fill-opacity="0.18" stroke="' . $color . '" stroke-width="2"/>';
        }
        $svg .= '<line x1="40" y1="170" x2="600" y2="170" stroke="' . self::INK . '" stroke-width="2"/>';
        $svg .= '<circle cx="' . (60 + ($seed % 520)) . '" cy="170" r="6" fill="' . self::EMPHASIS . '"/>';
        return $svg . '</svg>';
    }

    /** Framed placeholder shown until the AI image is generated. */
    public function renderAiPlaceholder(string $title): string
    {
        $svg = $this->svgOpen(640, 200, 'AI image placeholder: ' . $title);
        $svg .= '<rect x="8" y="8" width="624" height="184" rx="10" fill="none" stroke="' . self::MUTED . '" stroke-width="2" stroke-dasharray="8 6"/>';
        $svg .= '<circle cx="320" cy="78" r="26" fill="none" stroke="' . self::DATA . '" stroke-width="2"/>';
        $svg .= '<path d="M304 88 l12 -16 l10 12 l8 -8 l12 12" fill="none" stroke="' . self::DATA . '" stroke-width="2"/>';
        $svg .= '<text x="320" y="132" text-anchor="middle" font-size="14" font-weight="700" fill="' . self::INK . '">AI image — generate with bin/generate-images.php</text>';
        $svg .= '<text x="320" y="154" text-anchor="middle" font-size="12" fill="' . self::MUTED . '">' . $this->svgText($title, 80) . '</text>';
        return $svg . '</svg>';
    }

    /* ---------------- Tables ---------------- */

    /**
     * @param array<int, array<string, string>> $jobs
     * @return array{columns: array<int, string>, rows: array<int, array<int, string>>}
     */
    public function buildJobTable(array $jobs): array
    {
        $rows = [];
        foreach (array_slice($jobs, 0, 12) as $job) {
            $rows[] = [
                (string) ($job['title'] ?? ''),
                (string) ($job['schedule'] ?? ''),
                (string) ($job['skills'] ?? ''),
                (string) ($job['safety'] ?? ''),
            ];
        }
        return ['columns' => ['Job', 'Schedule', 'Skills and training', 'Safety and age rules'], 'rows' => $rows];
    }

    /**
     * @param array<int, array{title: string, word_count: int}> $sections
     * @return array{columns: array<int, string>, rows: array<int, array<int, string>>}
     */
    public function buildSectionTable(array $sections): array
    {
        $total = 0;
        foreach ($sections as $section) {
            $total += (int) $section['word_count'];
        }
        $total = max(1, $total);
        $rows = [];
        foreach ($sections as $index => $section) {
            $rows[] = [
                (string) ($index + 1),
                (string) $section['title'],
                (string) $section['word_count'],
                intdiv(((int) $section['word_count']) * 100, $total) . '%',
            ];
        }
        return ['columns' => ['#', 'Topic', 'Words', 'Share of chapter'], 'rows' => $rows];
    }

    /* ---------------- AI image prompts ---------------- */

    private function aiImageItem(int $number, string $title, array $chapter, array $metadata): array
    {
        $prompt = $this->aiPrompt($title, (string) ($chapter['purpose'] ?? ''), $metadata);
        return [
            'id' => 'ch' . $number . '-ai',
            'kind' => 'ai-image',
            'title' => 'Chapter opener image',
            'caption' => 'AI-generated scene for “' . $title . '”. Generate it locally with your own key.',
            'after_section' => 'Opening',
            'ai' => ['prompt' => $prompt, 'alt' => 'Illustration for chapter: ' . $title],
            'svg' => $this->renderAiPlaceholder($title),
        ];
    }

    public function aiPrompt(string $subject, string $context, array $metadata): string
    {
        $bookTitle = (string) ($metadata['title'] ?? 'the book');
        return 'Warm, softly lit editorial illustration for a non-fiction book chapter titled "' . $subject . '"'
            . ($context !== '' ? ' (' . strtolower($context) . ')' : '')
            . ', from the book "' . $bookTitle . '". Friendly and hopeful mood, simple modern flat-illustration style '
            . 'with paper-grain texture, muted blues and warm amber accents, no text or lettering anywhere, '
            . 'clean composition with generous negative space, suitable for a 6x9 book interior.';
    }

    /* ---------------- helpers ---------------- */

    private function svgOpen(int $width, int $height, string $label): string
    {
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' . $width . ' ' . $height . '" width="100%" role="img" aria-label="' . $this->svgText($label, 120) . '" font-family="Georgia, serif">';
    }

    private function svgText(string $value, int $maxChars): string
    {
        $value = trim($value);
        if (mb_strlen($value) > $maxChars) {
            $value = rtrim(mb_substr($value, 0, $maxChars - 1)) . '…';
        }
        return htmlspecialchars($value, ENT_XML1 | ENT_QUOTES, 'UTF-8');
    }

    /**
     * Jobs referenced by this chapter (teen catalog), for table building.
     *
     * @return array<int, array<string, string>>
     */
    private function chapterJobRows(array $chapter, array $book): array
    {
        $catalog = (array) ($book['job_catalog'] ?? []);
        if ($catalog === []) {
            return [];
        }
        $content = (string) ($chapter['content'] ?? '');
        if (!str_contains($content, 'Job cards for ') && !str_contains($content, 'The complete 120-job index')) {
            return [];
        }
        $rows = [];
        foreach ($catalog as $job) {
            if (is_array($job) && str_contains($content, "\n" . 'What you do: ' . (string) ($job['does'] ?? "\x00"))) {
                $rows[] = $job;
            }
            if (count($rows) === 12) {
                break;
            }
        }
        return $rows;
    }
}
