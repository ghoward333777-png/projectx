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
     * The section beats of a chapter with the prose each one carries — the
     * text the visual-selection formula analyzes.
     *
     * @param array<string, mixed> $chapter
     * @return array<int, array{title: string, text: string, word_count: int}>
     */
    public function chapterSectionTexts(array $chapter): array
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
                $current = ['title' => $content, 'text' => '', 'word_count' => 0];
                continue;
            }
            if ($current === null) {
                $current = ['title' => 'Opening', 'text' => '', 'word_count' => 0];
            }
            $current['text'] .= ($current['text'] === '' ? '' : "\n") . $content;
            $current['word_count'] += count(preg_split('/\s+/u', $content, -1, PREG_SPLIT_NO_EMPTY) ?: []);
        }
        if ($current !== null) {
            $sections[] = $current;
        }
        return $sections;
    }

    /**
     * Score a passage 0–3 on each signal the visual-selection formula reads.
     * Deterministic keyword and pattern counting — no services, no keys.
     *
     * @return array<string, int>
     */
    public function scoreVisualSignals(string $text): array
    {
        $patterns = [
            'comparability' => '/\b(compar\w*|versus|vs\.?|alternat\w*|options?\b|trade-?offs?|side by side|either\b|choos\w*|choices?|criteri\w*|differen\w*|contrast\w*|pros and cons)\b/iu',
            'temporal_dynamics' => '/\b(over time|trends?\b|trajector\w*|yearly|decades?\b|monthly|quarters?\b|q[1-4]\b|grow(s|th|ing)?\b|grew\b|declin\w*|increas\w*|decreas\w*|accelerat\w*|timeline|steadily|gradually|history|historical|evolution|era\b|generations?\b)\b/iu',
            'magnitude_contrast' => '/\b(rank\w*|largest|smallest|biggest|highest|lowest|twice\b|doubl(e[sd]?|ing)|tripl(e[sd]?|ing)|times (more|less|as)|outnumber\w*|far (more|less|fewer)|by far|magnitude)\b/iu',
            'proportion_insight' => '/(\d+\s?(%|percent)|\bpercent\w*|\bshares?\b|\bproportions?\b|\bportion\b|\bfraction\b|\bmajority\b|\bminority\b|out of every|\bcomposition\b|of the whole|\bmakeup\b)/iu',
            'mechanism_clarity' => '/\b(steps?\b|process\w*|mechanis\w*|sequences?\b|stages?\b|procedures?\b|workflow|cycles?\b|how it works|first,? then|instructions?\b|methods?\b|pipeline|diagnos\w*|checklists?\b)\b/iu',
            'real_world_anchoring' => '/\b(people|person\b|residents?|faces?\b|hands\b|streets?\b|buildings?\b|houses?\b|rooms?\b|towns?\b|cit(y|ies)|landscapes?\b|fields?\b|scenes?\b|photograph\w*|wearing|standing|machin\w*|storefronts?|farms?\b|kitchens?\b)\b/iu',
            'structure_insight' => '/\b(frameworks?\b|models?\b|concepts?\b|theor\w*|abstract\w*|architecture|structures?\b|relationships?\b|hierarch\w*|layers?\b|components?\b|principles?\b)\b/iu',
            'decision_support' => '/\b(decid\w*|decisions?\b|should (you|we|they)\b|which one|recommend\w*|evaluat\w*|weigh\w*|worth it|whether to|best (choice|option|fit)|pick the|before you commit|small test)\b/iu',
        ];
        $signals = [];
        foreach ($patterns as $name => $pattern) {
            $signals[$name] = min(3, (int) preg_match_all($pattern, $text));
        }
        // Data density: how many numeric facts the passage carries.
        $signals['data_density'] = min(3, intdiv((int) preg_match_all('/(?<![\w.])\d[\d,.]*/', $text), 3));
        // Structure beats keywords: three or more clauses that each open with
        // a process verb are a step sequence, whatever words follow.
        $imperatives = 0;
        foreach (preg_split('/[,;.:]\s*(?:and\s+|then\s+)?/u', $text, -1, PREG_SPLIT_NO_EMPTY) ?: [] as $clause) {
            if (preg_match('/^(diagnose|choose|run|review|test|apply|map|list|measure|plan|build|draft|check|gather|sort|schedule|practice|repeat|learn|compare|name|observe|set up|write down|pick)\b/iu', trim($clause)) === 1) {
                $imperatives++;
            }
        }
        if ($imperatives >= 3) {
            $signals['mechanism_clarity'] = 3;
        }
        return $signals;
    }

    /**
     * The visual-selection formula: Visual = argmax over V of Wp + Ws + Wn.
     *
     *  - Wp (0 or 3): the primary decision tree — the first information type
     *    the passage clearly matches (signal ≥ 2) sets the default visual.
     *  - Ws (0–3): the secondary scoring model — each visual takes the
     *    strongest of the signals that argue for it.
     *  - Wn (0 or 2): the narrative function of the section (from its
     *    purpose) breaks ties: decision→table, persuasion→chart,
     *    insight→graph, instruction→diagram, emotion→photo.
     *
     * Deterministic: equal totals resolve in the tree's own order.
     *
     * @return array{visual: string, kind: string, variant: string, total: int,
     *               scores: array<string, int>, signals: array<string, int>, reason: string}
     */
    public function selectVisual(string $text, string $purpose = ''): array
    {
        $signals = $this->scoreVisualSignals($text);

        // Visual → the signals that argue for it (the decision table).
        $advocates = [
            'table' => ['comparability', 'data_density', 'decision_support'],
            'line graph' => ['temporal_dynamics', 'decision_support'],
            'bar chart' => ['magnitude_contrast', 'comparability'],
            'pie chart' => ['proportion_insight'],
            'illustration' => ['mechanism_clarity'],
            'figure' => ['structure_insight'],
            'photo' => ['real_world_anchoring'],
        ];
        // Primary decision tree, in order; first signal ≥ 2 wins the default.
        $tree = [
            'comparability' => 'table',
            'temporal_dynamics' => 'line graph',
            'magnitude_contrast' => 'bar chart',
            'proportion_insight' => 'pie chart',
            'mechanism_clarity' => 'illustration',
            'structure_insight' => 'figure',
            'real_world_anchoring' => 'photo',
        ];
        $primary = null;
        foreach ($tree as $signal => $visual) {
            if ($signals[$signal] >= 2) {
                $primary = $visual;
                break;
            }
        }
        // Narrative function of the section (the tie-breaker weight).
        $narrative = null;
        foreach ([
            'table' => '/\b(decid\w*|decision|choose|weigh|evaluate|compare)\b/iu',
            'bar chart' => '/\b(persuad\w*|convinc\w*|case for|argu\w*|prove)\b/iu',
            'line graph' => '/\b(insight|discover\w*|understand\w*|reveal\w*|explain\w*|pattern)\b/iu',
            'illustration' => '/\b(instruct\w*|teach\w*|guide\w*|how to|learn\w*|practice|apply)\b/iu',
            'photo' => '/\b(emotion\w*|feel\w*|story|human|life|moment|remember)\b/iu',
        ] as $visual => $pattern) {
            if (preg_match($pattern, $purpose) === 1) {
                $narrative = $visual;
                break;
            }
        }

        $scores = [];
        foreach ($advocates as $visual => $advocateSignals) {
            $ws = 0;
            foreach ($advocateSignals as $signal) {
                $ws = max($ws, $signals[$signal]);
            }
            $scores[$visual] = $ws + ($primary === $visual ? 3 : 0) + ($narrative === $visual ? 2 : 0);
        }
        // argmax; ties resolve in the tree's own order (the array order above).
        $best = 'table';
        foreach ($scores as $visual => $score) {
            if ($score > $scores[$best]) {
                $best = $visual;
            }
        }

        $kinds = [
            'table' => ['table', 'table'],
            'line graph' => ['graph', 'line'],
            'bar chart' => ['chart', 'bar'],
            'pie chart' => ['chart', 'pie'],
            'illustration' => ['diagram', 'steps'],
            'figure' => ['illustration', 'emblem'],
            'photo' => ['ai-image', 'photo'],
        ];
        $reasons = [
            'table' => 'the passage compares items the reader must weigh side by side',
            'line graph' => 'the passage follows change over time',
            'bar chart' => 'the passage turns on differences in size and rank',
            'pie chart' => 'the passage describes parts of a whole',
            'illustration' => 'the passage explains a process the reader must follow',
            'figure' => 'the passage builds an abstract structure worth drawing',
            'photo' => 'the passage describes real people, places, or objects',
        ];
        return [
            'visual' => $best,
            'kind' => $kinds[$best][0],
            'variant' => $kinds[$best][1],
            'total' => $scores[$best],
            'scores' => $scores,
            'signals' => $signals,
            'reason' => $reasons[$best],
        ];
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
        $detail = (string) ($chapter['detail'] ?? '');
        $purpose = (string) ($chapter['purpose'] ?? '');
        $sections = $this->chapterSections($chapter);
        $jobs = $this->chapterJobRows($chapter, $book);
        $clauses = $this->detailClauses($detail);
        $lastSection = $sections !== [] ? $sections[count($sections) - 1]['title'] : 'Opening';
        $items = [];

        // The formula's photo layer: real objects, people, and places anchor
        // the reader, so every chapter plans its opener image — prompted
        // here, excluded from exports until the real image is generated.
        $items[] = $this->aiImageItem($number, $title, $chapter, $metadata);

        // The visual-selection formula, section by section: score every
        // prose beat, let the highest-scoring beats carry a figure, and let
        // each beat's winning information type decide which figure that is.
        $candidates = [];
        $sectionTexts = $this->chapterSectionTexts($chapter);
        foreach ($sectionTexts as $order => $section) {
            if (preg_match('/takeaway|synthesis/i', $section['title']) === 1) {
                continue; // the closer gets its own pull-quote card below
            }
            $candidates[] = [
                'order' => (int) $order,
                'section' => $section['title'],
                'choice' => $this->selectVisual($section['text'], $purpose . ' ' . $section['title']),
            ];
        }
        // A practice chapter's outline detail is itself reader-facing text —
        // a step sequence the reader will follow — so it competes too.
        $isPracticeChapter = preg_match('/framework|practice|how to|playbook|loop|method|steps|guide|checklist|use this/i', $title . ' ' . $purpose) === 1;
        if ($isPracticeChapter && $detail !== '') {
            $candidates[] = [
                'order' => -1,
                'section' => $sectionTexts !== [] ? $sectionTexts[0]['title'] : 'Opening',
                'choice' => $this->selectVisual($purpose . '. ' . $detail, $purpose),
            ];
        }
        usort($candidates, static fn (array $a, array $b): int =>
            [$b['choice']['total'], $a['order']] <=> [$a['choice']['total'], $b['order']]);
        $chosen = [];
        $slots = [];
        foreach ($candidates as $candidate) {
            if (count($chosen) >= 3) {
                break;
            }
            $slot = $candidate['choice']['kind'] . ':' . $candidate['choice']['variant'];
            if (isset($slots[$slot]) || $candidate['choice']['total'] < 2) {
                continue;
            }
            $item = $this->materializeVisual($candidate, $number, $chapter, $book, $sections, $clauses, $jobs);
            if ($item === null) {
                continue;
            }
            $slots[$slot] = true;
            $chosen[] = ['order' => $candidate['order'], 'item' => $item];
        }
        usort($chosen, static fn (array $a, array $b): int => $a['order'] <=> $b['order']);
        foreach ($chosen as $entry) {
            $items[] = $entry['item'];
        }

        // Real data always keeps its seat. Teen-job chapters carry their job
        // cards and schedule chart — the formula's own reasoning (tables
        // compare, bars rank) applied to real rows instead of prose signals.
        if ($jobs !== []) {
            if (!isset($slots['table:table'])) {
                $items[] = [
                    'id' => 'ch' . $number . '-table',
                    'kind' => 'table',
                    'title' => 'Job cards at a glance',
                    'caption' => 'The jobs this chapter explores, side by side.',
                    'after_section' => $lastSection,
                    'table' => $this->buildJobTable($jobs),
                ];
            }
            $mix = $this->scheduleMix($jobs);
            if (!isset($slots['chart:bar']) && count($mix) >= 2) {
                $items[] = [
                    'id' => 'ch' . $number . '-chart',
                    'kind' => 'chart',
                    'title' => 'When these jobs happen',
                    'caption' => 'Schedules named in the job cards above — how many of this chapter\'s jobs mention each.',
                    'after_section' => $lastSection,
                    'svg' => $this->renderBarChart($mix, 'jobs mentioning it', 'Schedules for ' . $title),
                ];
            }
        } elseif (!isset($slots['chart:bar']) && $this->wantsCatalogOverview($title) && ($book['job_catalog'] ?? []) !== []) {
            $items[] = [
                'id' => 'ch' . $number . '-chart',
                'kind' => 'chart',
                'title' => 'The 120 jobs, by kind of work',
                'caption' => 'Every job in this book\'s catalog, grouped the way the chapters explore them.',
                'after_section' => $lastSection,
                'svg' => $this->renderBarChart($this->categoryCounts((array) $book['job_catalog']), 'jobs', 'Catalog overview for ' . $title),
            ];
        }

        // The instruction pairing: a step-flow diagram shows the how, the
        // worksheet turns the same steps into work — a practice chapter that
        // earned the first always ships the second.
        if (isset($slots['diagram:steps']) && !isset($slots['table:table']) && $jobs === [] && count($clauses) >= 3) {
            $items[] = [
                'id' => 'ch' . $number . '-table',
                'kind' => 'table',
                'title' => 'Worksheet: ' . strtolower($this->titleShort($title)),
                'caption' => 'The chapter\'s own checkpoints, ready to work through.',
                'after_section' => $lastSection,
                'table' => $this->buildWorksheetTable($clauses),
            ];
        }

        // Illustration: the chapter's takeaway as a pull-quote card — the
        // Quality Lab and the print companion read it.
        $quote = $this->takeawayQuote((string) ($chapter['content'] ?? ''));
        if ($quote !== '') {
            $items[] = [
                'id' => 'ch' . $number . '-illustration',
                'kind' => 'illustration',
                'title' => 'The takeaway',
                'caption' => 'This chapter\'s message, worth keeping.',
                'after_section' => $lastSection,
                'svg' => $this->renderQuoteCard($quote, $title),
            ];
        }
        return $items;
    }

    /**
     * Turn one formula decision into a rendered media item. Returns null
     * when the chapter lacks the material the chosen visual needs — the
     * next-best section then takes the slot.
     *
     * @param array{order: int, section: string, choice: array<string, mixed>} $candidate
     * @param array<string, mixed> $chapter
     * @param array<string, mixed> $book
     * @param array<int, array{title: string, word_count: int, block_index: int}> $sections
     * @param array<int, string> $clauses
     * @param array<int, array<string, string>> $jobs
     * @return array<string, mixed>|null
     */
    private function materializeVisual(array $candidate, int $number, array $chapter, array $book, array $sections, array $clauses, array $jobs): ?array
    {
        $choice = $candidate['choice'];
        $title = (string) ($chapter['title'] ?? '');
        $short = $this->titleShort($title);
        $base = [
            'id' => 'ch' . $number . '-s' . $candidate['order'] . '-' . str_replace(' ', '-', (string) $choice['visual']),
            'kind' => (string) $choice['kind'],
            'after_section' => $candidate['section'],
            'decision' => [
                'visual' => $choice['visual'],
                'total' => $choice['total'],
                'signals' => $choice['signals'],
                'reason' => $choice['reason'],
            ],
        ];
        switch ((string) $choice['visual']) {
            case 'table':
                if ($jobs !== []) {
                    return $base + [
                        'id' => 'ch' . $number . '-table',
                        'title' => 'Job cards at a glance',
                        'caption' => 'The jobs this chapter explores, side by side.',
                        'table' => $this->buildJobTable($jobs),
                    ];
                }
                if (count($clauses) >= 3) {
                    return $base + [
                        'id' => 'ch' . $number . '-table',
                        'title' => 'Worksheet: ' . strtolower($short),
                        'caption' => 'The chapter\'s own checkpoints, ready to work through.',
                        'table' => $this->buildWorksheetTable($clauses),
                    ];
                }
                if (count($sections) >= 2) {
                    return $base + [
                        'title' => 'The topics, side by side',
                        'caption' => 'Each topic of ' . $short . ' and the attention it carries.',
                        'table' => $this->buildSectionTable($sections),
                    ];
                }
                return null;
            case 'line graph':
                if (count($sections) < 2) {
                    return null;
                }
                return $base + [
                    'title' => 'How ' . strtolower($short) . ' builds',
                    'caption' => 'The ground gained topic by topic across ' . $short . '.',
                    'svg' => $this->renderGraph($sections, $title),
                ];
            case 'bar chart':
                if ($jobs !== []) {
                    $mix = $this->scheduleMix($jobs);
                    if (count($mix) >= 2) {
                        return $base + [
                            'id' => 'ch' . $number . '-chart',
                            'title' => 'When these jobs happen',
                            'caption' => 'Schedules named in the job cards above — how many of this chapter\'s jobs mention each.',
                            'svg' => $this->renderBarChart($mix, 'jobs mentioning it', 'Schedules for ' . $title),
                        ];
                    }
                }
                if (count($sections) < 2) {
                    return null;
                }
                return $base + [
                    'title' => 'Where the weight falls',
                    'caption' => 'The topics of ' . $short . ', ranked by the attention each receives.',
                    'svg' => $this->renderChart($sections, $title),
                ];
            case 'pie chart':
                if (count($sections) < 2) {
                    return null;
                }
                return $base + [
                    'title' => 'The whole, in parts',
                    'caption' => 'How ' . $short . ' divides its ground among its topics.',
                    'svg' => $this->renderPieChart(
                        array_map(static fn (array $s): array => ['label' => (string) $s['title'], 'value' => (int) $s['word_count']], $sections),
                        $title,
                    ),
                ];
            case 'illustration':
                if (count($clauses) < 3) {
                    return null;
                }
                $steps = array_map(
                    fn (string $clause): string => mb_strtoupper(mb_substr($this->subjectClause($clause), 0, 1)) . mb_substr($this->subjectClause($clause), 1),
                    $clauses,
                );
                return $base + [
                    'id' => 'ch' . $number . '-diagram',
                    'title' => $short . ' at a glance',
                    'caption' => 'The ground covered here: ' . $this->subjectClause((string) ($chapter['purpose'] ?? $title)) . '.',
                    'svg' => $this->renderDiagram($steps, $title),
                ];
            case 'figure':
                return $base + [
                    'title' => $short . ', drawn',
                    'caption' => 'The shape of ' . $short . ' — its pieces and how they sit together.',
                    'svg' => $this->renderIllustration('figure:' . $number . ':' . $candidate['section'], $title),
                ];
            case 'photo':
                // The chapter's opener image already anchors it in the real
                // world; a second photo slot yields to the next candidate.
                return null;
        }
        return null;
    }

    /**
     * Split an outline detail into its meaningful instruction clauses —
     * the same segmentation the chapter composer develops.
     *
     * @return array<int, string>
     */
    public function detailClauses(string $detail): array
    {
        $clauses = preg_split('/[,.;:]+|\band\b/i', $detail, -1, PREG_SPLIT_NO_EMPTY) ?: [];
        return array_values(array_filter(array_map('trim', $clauses), static fn (string $part): bool => mb_strlen($part) > 12));
    }

    /**
     * Convert a writer-facing instruction clause into the subject it names —
     * the same verb-stripping rule the chapter composer applies to prose.
     */
    private function subjectClause(string $clause): string
    {
        $clause = trim($clause);
        $clause = (string) preg_replace('/^(follow|describe|examine|show|explain|trace|document|chart|weigh|explore|contrast|tell|assemble|recreate|tally|review|profile|identify|cover|include|use|offer|give|ask|clarify|compare|separate|treat|distinguish|name|count|find|measure|widen|replace|ground|mark|argue for|open with|start with|lay out|look at|bring in|be honest about|be candid about|let|keep|make|move|put|add|end with|close with|hold|watch|note|noting)\b\s*(?:how\s+|that\s+|why\s+|whether\s+)?/iu', '', $clause, 1);
        return trim($clause);
    }

    /** The chapter's closing takeaway sentence, if the draft carries one. */
    public function takeawayQuote(string $content): string
    {
        foreach (["\nChapter takeaway\n\n", "\nThe takeaway\n\n", "\nChapter synthesis\n\n"] as $marker) {
            $pos = strrpos($content, $marker);
            if ($pos !== false) {
                $tail = trim(substr($content, $pos + strlen($marker)));
                $end = strpos($tail, '. ');
                $sentence = $end !== false ? substr($tail, 0, $end + 1) : $tail;
                return trim(mb_substr($sentence, 0, 220));
            }
        }
        return '';
    }

    /**
     * How this chapter's jobs distribute across schedule patterns, counted
     * from the catalog's own schedule fields.
     *
     * @param array<int, array<string, string>> $jobs
     * @return array<int, array{label: string, value: int}>
     */
    public function scheduleMix(array $jobs): array
    {
        $patterns = [
            'After school' => 'after school',
            'Weekends' => 'weekend',
            'Summer' => 'summer',
            'Seasonal' => 'seasonal',
            'Evenings' => 'evening',
            'Flexible' => 'flexible',
        ];
        $rows = [];
        foreach ($patterns as $label => $needle) {
            $count = 0;
            foreach ($jobs as $job) {
                if (str_contains(strtolower((string) ($job['schedule'] ?? '')), $needle)) {
                    $count++;
                }
            }
            if ($count > 0) {
                $rows[] = ['label' => $label, 'value' => $count];
            }
        }
        return $rows;
    }

    /**
     * @param array<int, array<string, string>> $catalog
     * @return array<int, array{label: string, value: int}>
     */
    public function categoryCounts(array $catalog): array
    {
        $counts = [];
        foreach ($catalog as $job) {
            $category = (string) ($job['category'] ?? '');
            if ($category === '') {
                continue;
            }
            $label = preg_replace('/^Jobs in /', '', $category) ?? $category;
            $counts[$label] = ($counts[$label] ?? 0) + 1;
        }
        $rows = [];
        foreach ($counts as $label => $value) {
            $rows[] = ['label' => $label, 'value' => $value];
        }
        return $rows;
    }

    /** Whether a chapter is about the catalog as a whole. */
    private function wantsCatalogOverview(string $title): bool
    {
        return preg_match('/how this list|find real opportunities|compare jobs|use this book/i', $title) === 1;
    }

    /**
     * @param array<int, string> $clauses
     * @return array{columns: array<int, string>, rows: array<int, array<int, string>>}
     */
    public function buildWorksheetTable(array $clauses): array
    {
        $rows = [];
        foreach (array_slice($clauses, 0, 8) as $index => $clause) {
            $rows[] = [(string) ($index + 1), ucfirst($clause), '☐'];
        }
        return ['columns' => ['#', 'Work through this', 'Done'], 'rows' => $rows];
    }

    private function titleShort(string $title): string
    {
        return mb_strlen($title) > 40 ? rtrim(mb_substr($title, 0, 39)) . '…' : $title;
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
            $item['placeholder'] = true;
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

    /**
     * Horizontal bar chart over real labeled data rows.
     *
     * @param array<int, array{label: string, value: int}> $rows
     */
    public function renderBarChart(array $rows, string $valueLabel, string $context): string
    {
        $rows = array_slice($rows, 0, 9);
        if ($rows === []) {
            return $this->renderIllustration('chart:' . $context, $context);
        }
        $max = 1;
        foreach ($rows as $row) {
            $max = max($max, (int) $row['value']);
        }
        $barHeight = 20;
        $gap = 14;
        $chartLeft = 230;
        $chartWidth = 360;
        $height = count($rows) * ($barHeight + $gap) - $gap + 44;
        $svg = $this->svgOpen(640, $height, 'Bar chart: ' . $context);
        foreach ($rows as $index => $row) {
            $y = 16 + $index * ($barHeight + $gap);
            $width = max(6, intdiv(((int) $row['value']) * $chartWidth, $max));
            $svg .= '<text x="' . ($chartLeft - 10) . '" y="' . ($y + 15) . '" text-anchor="end" font-size="13" fill="' . self::INK . '">' . $this->svgText((string) $row['label'], 30) . '</text>';
            $svg .= '<rect x="' . $chartLeft . '" y="' . $y . '" width="' . $width . '" height="' . $barHeight . '" rx="4" fill="' . self::DATA . '"><title>' . $this->svgText((string) $row['label'] . ': ' . $row['value'], 90) . '</title></rect>';
            $svg .= '<text x="' . ($chartLeft + $width + 8) . '" y="' . ($y + 15) . '" font-size="12" fill="' . self::MUTED . '">' . (int) $row['value'] . '</text>';
        }
        $axisY = 16 + count($rows) * ($barHeight + $gap) - $gap + 8;
        $svg .= '<line x1="' . $chartLeft . '" y1="10" x2="' . $chartLeft . '" y2="' . $axisY . '" stroke="' . self::GRID . '" stroke-width="1"/>';
        $svg .= '<text x="' . $chartLeft . '" y="' . ($axisY + 16) . '" font-size="11" fill="' . self::MUTED . '">' . $this->svgText($valueLabel, 40) . '</text>';
        return $svg . '</svg>';
    }

    /** The chapter's takeaway sentence set as a pull-quote card. */
    public function renderQuoteCard(string $quote, string $context): string
    {
        $words = preg_split('/\s+/u', trim($quote), -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $lines = [];
        $current = '';
        foreach ($words as $word) {
            $candidate = $current === '' ? $word : $current . ' ' . $word;
            if (mb_strlen($candidate) > 46) {
                $lines[] = $current;
                $current = $word;
            } else {
                $current = $candidate;
            }
        }
        if ($current !== '') {
            $lines[] = $current;
        }
        $lines = array_slice($lines, 0, 6);
        $height = 90 + count($lines) * 30;
        $svg = $this->svgOpen(640, $height, 'Takeaway: ' . $context);
        $svg .= '<rect x="8" y="8" width="624" height="' . ($height - 16) . '" rx="12" fill="none" stroke="' . self::GRID . '" stroke-width="2"/>';
        $svg .= '<rect x="8" y="8" width="6" height="' . ($height - 16) . '" rx="3" fill="' . self::EMPHASIS . '"/>';
        $svg .= '<text x="44" y="52" font-size="40" fill="' . self::EMPHASIS . '" font-weight="700">&#8220;</text>';
        foreach ($lines as $index => $line) {
            $svg .= '<text x="70" y="' . (58 + $index * 30) . '" font-size="18" font-style="italic" fill="' . self::INK . '">' . $this->svgText($line, 60) . '</text>';
        }
        return $svg . '</svg>';
    }

    /** Horizontal bar chart: words per important topic (used by user-added charts). */
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

    /**
     * Donut chart: each topic's share of the chapter, part to whole.
     *
     * @param array<int, array{label: string, value: int}> $rows
     */
    public function renderPieChart(array $rows, string $context): string
    {
        $rows = array_slice(array_values(array_filter($rows, static fn (array $r): bool => (int) $r['value'] > 0)), 0, 6);
        $total = array_sum(array_map(static fn (array $r): int => (int) $r['value'], $rows));
        if (count($rows) < 2 || $total < 1) {
            return $this->renderIllustration('pie:' . $context, $context);
        }
        $cx = 150;
        $cy = 110;
        $radius = 82;
        $palette = [self::DATA, self::EMPHASIS, self::MUTED, '#4c7fb8', '#c97b2d', '#7c86a0'];
        $svg = $this->svgOpen(640, 220, 'Share chart: ' . $context);
        $angle = -90.0;
        foreach ($rows as $index => $row) {
            $sweep = 360.0 * ((int) $row['value']) / $total;
            $a0 = deg2rad($angle);
            $a1 = deg2rad($angle + $sweep);
            $x0 = $cx + $radius * cos($a0);
            $y0 = $cy + $radius * sin($a0);
            $x1 = $cx + $radius * cos($a1);
            $y1 = $cy + $radius * sin($a1);
            $large = $sweep > 180 ? 1 : 0;
            $svg .= '<path d="M' . round($cx, 1) . ' ' . round($cy, 1)
                . ' L' . round($x0, 1) . ' ' . round($y0, 1)
                . ' A' . $radius . ' ' . $radius . ' 0 ' . $large . ' 1 ' . round($x1, 1) . ' ' . round($y1, 1)
                . ' Z" fill="' . $palette[$index % count($palette)] . '" stroke="' . self::PAPER . '" stroke-width="2">'
                . '<title>' . $this->svgText((string) $row['label'] . ': ' . round(100 * ((int) $row['value']) / $total) . '%', 90) . '</title></path>';
            $angle += $sweep;
        }
        $svg .= '<circle cx="' . $cx . '" cy="' . $cy . '" r="40" fill="' . self::PAPER . '"/>';
        $svg .= '<text x="' . $cx . '" y="' . ($cy + 5) . '" text-anchor="middle" font-size="13" font-weight="700" fill="' . self::INK . '">' . $total . '</text>';
        foreach ($rows as $index => $row) {
            $ly = 40 + $index * 28;
            $svg .= '<rect x="300" y="' . ($ly - 11) . '" width="14" height="14" rx="3" fill="' . $palette[$index % count($palette)] . '"/>';
            $svg .= '<text x="322" y="' . $ly . '" font-size="12" fill="' . self::INK . '">' . $this->svgText((string) $row['label'], 34) . '</text>';
            $svg .= '<text x="620" y="' . $ly . '" text-anchor="end" font-size="12" fill="' . self::MUTED . '">' . round(100 * ((int) $row['value']) / $total) . '%</text>';
        }
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
            'placeholder' => true,
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
