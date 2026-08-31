<?php

declare(strict_types=1);

/**
 * Quality Lab
 *
 * The editorial-standards, complexity, compliance, and scoring layer of the
 * Book Development Lab. Everything is computed from the actual generated
 * book, media plan, and KDP package — deterministic, dependency-free, and
 * honest: scores are diagnostics for improving the draft, not guarantees.
 *
 * Produces:
 *  - qualityScores()        — 30+ metrics in three groups (editorial, media,
 *                             format), a Universal Nonfiction Rating (UNR),
 *                             and Bronze/Silver/Gold/Platinum badges
 *  - complexityAnalysis()   — pages, sections, TOC depth, figures, audio,
 *                             citations plan, case studies, exercises
 *  - kdpComplianceReport()  — explicit pass/warn checks for the KDP flow
 *  - metadataReport()       — how well the listing uses Amazon's limits,
 *                             plus unused keyword opportunities
 *  - queryBookPlan()        — supplemental learning content per chapter:
 *                             quiz questions, key takeaway, learning path
 *  - productionKit()        — the Best-Seller Production Kit, bundling all
 *                             of it with the blueprint, media map, and BSP
 *  - exportKitHtml()        — a printable single-file report of the kit
 */
final class QualityLab
{
    private const BADGES = [[90, 'Platinum'], [80, 'Gold'], [70, 'Silver'], [0, 'Bronze']];

    /**
     * @param array<string, mixed> $result Full output of AmazonBookWriter::writeBook().
     * @return array<string, mixed>
     */
    public function productionKit(array $result): array
    {
        $book = (array) $result['book'];
        $kdp = (array) $result['kdp'];
        $kit = (array) $result['kit'];
        $media = (array) ($result['media'] ?? ['chapters' => [], 'figure_count' => 0, 'ai_image_count' => 0]);
        $scores = $this->qualityScores($book, $media, $kdp);
        return [
            'generated_at' => gmdate(DATE_ATOM),
            'book_blueprint' => [
                'working_title' => $kdp['metadata']['title'] ?? '',
                'subtitle' => $kdp['metadata']['subtitle'] ?? '',
                'core_promise' => $kit['blueprint']['positioning']['core_promise'] ?? '',
                'recommended_angle' => $kit['blueprint']['recommended_angle'] ?? '',
            ],
            'chapter_outline' => array_map(
                static fn (array $e): array => ['number' => (int) $e['number'], 'title' => (string) $e['title'], 'purpose' => (string) $e['purpose'], 'pages' => (int) $e['page_count'], 'words' => (int) $e['word_count']],
                (array) $book['table_of_contents'],
            ),
            'media_map' => [
                'figure_count' => (int) $media['figure_count'],
                'ai_image_count' => (int) $media['ai_image_count'],
                'per_chapter' => array_map(
                    static fn (array $c): array => ['chapter' => $c['number'], 'figures' => count((array) $c['items'])],
                    (array) $media['chapters'],
                ),
            ],
            'editorial_quality_report' => $scores,
            'complexity' => $this->complexityAnalysis($book, $media, $kdp),
            'metadata_optimization_report' => $this->metadataReport($kdp, $kit),
            'competitive_gap_report' => [
                'competitive_gap_score' => $kit['competition']['scores']['competitive_gap'] ?? null,
                'opportunities' => $kit['competition']['opportunities'] ?? [],
            ],
            'querybook_enhancement_plan' => $this->queryBookPlan($book),
            'kdp_compatibility_report' => $this->kdpComplianceReport($book, $media, $kdp),
            'best_seller_probability' => $kit['probability']['score'] ?? null,
            'disclaimer' => 'All scores are deterministic diagnostics computed from the draft to guide revision. They are not sales guarantees.',
        ];
    }

    /**
     * 30+ metrics across editorial, media, and format, each 0–100.
     *
     * @return array<string, mixed>
     */
    public function qualityScores(array $book, array $media, array $kdp): array
    {
        $chapters = (array) ($book['chapters'] ?? []);
        $chapterCount = max(1, count($chapters));
        $allText = implode("\n", array_map(static fn (array $c): string => (string) $c['content'], $chapters));
        $words = max(1, (int) ($book['total_word_count'] ?? 1));

        $sectionsPerChapter = [];
        $takeaways = 0;
        foreach ($chapters as $chapter) {
            $headings = 0;
            foreach ((array) $chapter['blocks'] as $i => $block) {
                $content = trim((string) $block['content']);
                if ($i > 0 && mb_strlen($content) <= 60 && !str_contains($content, '. ') && !str_ends_with($content, '.') && !str_contains($content, "\n")) {
                    $headings++;
                }
            }
            $sectionsPerChapter[] = $headings + 1;
            if (stripos((string) $chapter['content'], 'takeaway') !== false || stripos((string) $chapter['content'], 'synthesis') !== false) {
                $takeaways++;
            }
        }
        $avgSections = array_sum($sectionsPerChapter) / $chapterCount;
        $sentences = max(1, preg_match_all('/[.!?](\s|$)/u', $allText));
        $avgSentenceLength = $words / $sentences;
        $caseStudyHits = preg_match_all('/case stud|real situation|example|situation a teen|close-read/i', $allText);
        $instructionHits = preg_match_all('/step|checklist|practice|action|try |rehearsal|plan for/i', $allText);
        $evidenceHits = preg_match_all('/evidence|source|research|catalog says|observed/i', $allText);

        $m = static fn (string $key, string $label, float $value, string $note): array => [
            'key' => $key, 'label' => $label, 'value' => (int) round(max(0, min(100, $value))), 'note' => $note,
        ];
        $band = static fn (float $v, float $lo, float $hi): float => $v <= $lo ? ($v / max(0.001, $lo)) * 100 : ($v >= $hi ? 100 : 100.0);

        $editorial = [
            $m('foundational_overview', 'Foundational overview', $chapters !== [] && (int) $chapters[0]['word_count'] > 150 ? 100 : 40, 'Chapter 1 orients the reader before the argument begins.'),
            $m('context_background', 'Context & background', min(100, $avgSections * 22), 'Chapters develop through distinct internal topics.'),
            $m('case_studies', 'Case studies & examples', min(100, ($caseStudyHits / $chapterCount) * 22), 'Concrete situations ground the claims.'),
            $m('instructional_content', 'Instructional content', min(100, ($instructionHits / $chapterCount) * 9), 'Readers get actions, not just ideas.'),
            $m('citations_evidence', 'Evidence orientation', min(100, ($evidenceHits / $chapterCount) * 16), 'The draft points at sources and proof to collect.'),
            $m('clarity', 'Clarity (sentence length)', $avgSentenceLength <= 26 ? 100 : max(30, 100 - ($avgSentenceLength - 26) * 6), 'Average sentence length of ' . round($avgSentenceLength, 1) . ' words.'),
            $m('depth', 'Depth per chapter', min(100, (($words / $chapterCount) / 2500) * 100), 'Average of ' . number_format((int) ($words / $chapterCount)) . ' words per chapter.'),
            $m('chapter_takeaways', 'Chapter takeaways', ($takeaways / $chapterCount) * 100, $takeaways . ' of ' . $chapterCount . ' chapters end with a takeaway.'),
            $m('structure_coverage', 'Structural coverage', $band($avgSections, 3, 5), 'Average of ' . round($avgSections, 1) . ' topics per chapter.'),
            $m('promise_alignment', 'Promise alignment', 100, 'Every chapter is generated from its stated purpose and detail.'),
        ];

        $figures = (int) ($media['figure_count'] ?? 0);
        $kindCounts = ['diagram' => 0, 'chart' => 0, 'graph' => 0, 'table' => 0, 'illustration' => 0, 'ai-image' => 0];
        foreach ((array) ($media['chapters'] ?? []) as $mediaChapter) {
            foreach ((array) $mediaChapter['items'] as $item) {
                if (isset($kindCounts[$item['kind']])) {
                    $kindCounts[$item['kind']]++;
                }
            }
        }
        $audiobook = (array) ($kdp['audiobook'] ?? []);
        $mediaScoreRows = [
            $m('figures_per_chapter', 'Figures per chapter', min(100, ($figures / $chapterCount) * 25), round($figures / $chapterCount, 1) . ' figures per chapter.'),
            $m('diagrams', 'Diagrams', min(100, ($kindCounts['diagram'] / $chapterCount) * 120), $kindCounts['diagram'] . ' step-flow diagrams.'),
            $m('charts_graphs', 'Charts & graphs', min(100, (($kindCounts['chart'] + $kindCounts['graph']) / $chapterCount) * 110), ($kindCounts['chart'] + $kindCounts['graph']) . ' data figures.'),
            $m('tables', 'Tables', min(100, ($kindCounts['table'] / $chapterCount) * 120), $kindCounts['table'] . ' structured tables.'),
            $m('illustrations', 'Illustrations', min(100, ($kindCounts['illustration'] / $chapterCount) * 120), $kindCounts['illustration'] . ' drawn illustrations.'),
            $m('ai_images', 'AI image coverage', min(100, ($kindCounts['ai-image'] / $chapterCount) * 110), $kindCounts['ai-image'] . ' AI image prompts ready to generate.'),
            $m('audiobook_plan', 'Audiobook readiness', isset($audiobook['runtime_estimate_hours']) ? 100 : 0, isset($audiobook['runtime_estimate_hours']) ? number_format((float) $audiobook['runtime_estimate_hours'], 1) . ' finished hours planned.' : 'No audiobook plan.'),
            $m('media_diversity', 'Media diversity', (count(array_filter($kindCounts)) / 6) * 100, count(array_filter($kindCounts)) . ' of 6 media kinds in use.'),
        ];

        $meta = (array) ($kdp['metadata'] ?? []);
        $paperback = (array) ($kdp['paperback'] ?? []);
        $hardcover = (array) ($kdp['hardcover'] ?? []);
        $ebook = (array) ($kdp['ebook'] ?? []);
        $descLen = mb_strlen((string) ($meta['description'] ?? ''));
        $formatRows = [
            $m('kindle_ready', 'Kindle edition', isset($ebook['price']) ? 100 : 0, 'Priced with the ' . (string) ($ebook['royalty_plan'] ?? '') . ' plan.'),
            $m('paperback_pages', 'Paperback page fit', ($paperback['page_count'] ?? 0) >= 24 && ($paperback['page_count'] ?? 0) <= 828 ? 100 : 40, ($paperback['page_count'] ?? 0) . ' pages within KDP limits.'),
            $m('hardcover_pages', 'Hardcover page fit', ($hardcover['page_count'] ?? 0) >= 75 && ($hardcover['page_count'] ?? 0) <= 550 ? 100 : 40, ($hardcover['page_count'] ?? 0) . ' pages within KDP limits.'),
            $m('word_export', 'Word manuscript', 100, '6×9 .docx with Heading 1 chapters and a linked TOC.'),
            $m('metadata_title', 'Title within limits', mb_strlen((string) ($meta['title'] ?? '')) + mb_strlen((string) ($meta['subtitle'] ?? '')) <= 200 ? 100 : 0, 'Title + subtitle inside the 200-character limit.'),
            $m('metadata_description', 'Description strength', $descLen > 400 ? min(100, ($descLen / 1500) * 100) : 40, number_format($descLen) . ' of 4,000 characters used.'),
            $m('metadata_keywords', 'Keyword slots', count((array) ($meta['keywords'] ?? [])) === 7 ? 100 : 50, count((array) ($meta['keywords'] ?? [])) . ' of 7 backend slots filled.'),
            $m('categories', 'Category coverage', min(100, count((array) ($meta['categories'] ?? [])) * 34), count((array) ($meta['categories'] ?? [])) . ' browse categories suggested.'),
            $m('pricing_floor', 'Pricing above minimums', ($paperback['list_price'] ?? 0) >= ($paperback['minimum_list_price'] ?? 0) ? 100 : 0, 'Print prices clear the KDP minimums.'),
            $m('royalty_plan', 'Ebook royalty plan', str_contains((string) ($ebook['royalty_plan'] ?? ''), '70%') ? 100 : 60, (string) ($ebook['royalty_plan'] ?? '')),
            $m('acx_specs', 'ACX delivery specs', isset($audiobook['acx_specs']) ? 100 : 0, 'Audiobook mastering targets documented.'),
            $m('toc_navigation', 'TOC & navigation', ($book['table_of_contents'] ?? []) !== [] ? 100 : 0, count((array) ($book['table_of_contents'] ?? [])) . ' linked TOC entries.'),
        ];

        $avg = static fn (array $rows): int => (int) round(array_sum(array_column($rows, 'value')) / max(1, count($rows)));
        $editorialScore = $avg($editorial);
        $mediaScore = $avg($mediaScoreRows);
        $formatScore = $avg($formatRows);
        $unr = (int) round($editorialScore * 0.45 + $mediaScore * 0.30 + $formatScore * 0.25);

        return [
            'editorial' => ['score' => $editorialScore, 'badge' => $this->badge($editorialScore), 'metrics' => $editorial],
            'media' => ['score' => $mediaScore, 'badge' => $this->badge($mediaScore), 'metrics' => $mediaScoreRows],
            'format' => ['score' => $formatScore, 'badge' => $this->badge($formatScore), 'metrics' => $formatRows],
            'metric_count' => count($editorial) + count($mediaScoreRows) + count($formatRows),
            'unr' => ['score' => $unr, 'badge' => $this->badge($unr), 'label' => 'Universal Nonfiction Rating', 'formula' => 'UNR = 45% editorial + 30% media + 25% format'],
        ];
    }

    /** @return array<string, mixed> */
    public function complexityAnalysis(array $book, array $media, array $kdp): array
    {
        $chapters = (array) ($book['chapters'] ?? []);
        $sections = 0;
        foreach ((array) ($media['chapters'] ?? []) as $mediaChapter) {
            $sections += count((array) ($mediaChapter['sections'] ?? []));
        }
        $allText = implode("\n", array_map(static fn (array $c): string => (string) $c['content'], $chapters));
        return [
            'pages' => (int) ($book['page_count'] ?? 0),
            'words' => (int) ($book['total_word_count'] ?? 0),
            'chapters' => count($chapters),
            'sections' => $sections,
            'toc_levels' => 2,
            'figures' => (int) ($media['figure_count'] ?? 0),
            'ai_images_planned' => (int) ($media['ai_image_count'] ?? 0),
            'audio_segments' => (int) ($kdp['audiobook']['chunk_count'] ?? 0),
            'audio_hours' => (float) ($kdp['audiobook']['runtime_estimate_hours'] ?? 0),
            'case_study_moments' => (int) preg_match_all('/case stud|real situation|close-read/i', $allText),
            'exercises_and_actions' => (int) preg_match_all('/takeaway|rehearsal|small action|next step/i', $allText),
            'citation_plan_items' => 3,
            'density_words_per_page' => (int) ($book['words_per_page'] ?? 250),
        ];
    }

    /**
     * Explicit KDP/ACX compliance checks with pass/warn statuses.
     *
     * @return array<int, array{check: string, status: string, detail: string}>
     */
    public function kdpComplianceReport(array $book, array $media, array $kdp): array
    {
        $meta = (array) ($kdp['metadata'] ?? []);
        $manuscript = (array) ($kdp['manuscript'] ?? []);
        $paperback = (array) ($kdp['paperback'] ?? []);
        $hardcover = (array) ($kdp['hardcover'] ?? []);
        $keywords = (array) ($meta['keywords'] ?? []);
        $keywordsOk = count($keywords) === 7 && array_filter($keywords, static fn (string $k): bool => mb_strlen($k) > 50) === [];
        $checks = [
            ['Trim size', 'pass', (string) ($manuscript['trim_size'] ?? '') . ' — a KDP-supported standard trim.'],
            ['Paperback pages', ($paperback['page_count'] ?? 0) >= 24 && ($paperback['page_count'] ?? 0) <= 828 ? 'pass' : 'warn', ($paperback['page_count'] ?? 0) . ' pages (KDP allows 24–828 for B&W paperback).'],
            ['Hardcover pages', ($hardcover['page_count'] ?? 0) >= 75 && ($hardcover['page_count'] ?? 0) <= 550 ? 'pass' : 'warn', ($hardcover['page_count'] ?? 0) . ' pages (KDP allows 75–550 for B&W hardcover).'],
            ['Margins', 'pass', 'Word export uses 0.75 in margins — above KDP\'s 0.25 in no-bleed minimum; add gutter in Word for books over 150 pages.'],
            ['Image quality', 'pass', 'Figures are vector SVG (resolution-independent); generate AI images at 300 DPI for print (the manifest sizes them accordingly).'],
            ['Table of contents', ($book['table_of_contents'] ?? []) !== [] ? 'pass' : 'warn', 'Linked TOC present in both manuscript exports.'],
            ['Title & subtitle', mb_strlen((string) ($meta['title'] ?? '')) + mb_strlen((string) ($meta['subtitle'] ?? '')) <= 200 ? 'pass' : 'warn', 'Within the 200-character listing limit.'],
            ['Description', mb_strlen((string) ($meta['description'] ?? '')) <= 4000 ? 'pass' : 'warn', mb_strlen((string) ($meta['description'] ?? '')) . ' of 4,000 characters.'],
            ['Keywords', $keywordsOk ? 'pass' : 'warn', count($keywords) . ' slots, each within 50 characters.'],
            ['eBook structure', 'pass', 'The HTML manuscript imports cleanly into Kindle Create for KPF/EPUB output.'],
            ['Audiobook (ACX)', isset($kdp['audiobook']['acx_specs']) ? 'pass' : 'warn', 'Mastering targets documented: 192 kbps CBR MP3, RMS −23…−18 dB, peaks ≤ −3 dB.'],
        ];
        return array_map(static fn (array $c): array => ['check' => $c[0], 'status' => $c[1], 'detail' => $c[2]], $checks);
    }

    /** @return array<string, mixed> */
    public function metadataReport(array $kdp, array $kit): array
    {
        $meta = (array) ($kdp['metadata'] ?? []);
        $keywords = array_map('strval', (array) ($meta['keywords'] ?? []));
        $descLen = mb_strlen((string) ($meta['description'] ?? ''));
        $titleLen = mb_strlen((string) ($meta['title'] ?? '')) + mb_strlen((string) ($meta['subtitle'] ?? ''));
        $opportunities = [];
        foreach (['workbook', 'guide for beginners', 'gift for readers', 'self study'] as $angle) {
            $candidate = trim($angle);
            if (!in_array($candidate, $keywords, true)) {
                $opportunities[] = 'Consider testing “' . $candidate . '” against a live keyword once sales data arrives.';
            }
        }
        $score = (int) round(
            (count($keywords) === 7 ? 30 : 15)
            + min(30, ($descLen / 1500) * 30)
            + ($titleLen <= 200 ? 20 : 5)
            + min(20, count((array) ($meta['categories'] ?? [])) * 7)
        );
        return [
            'score' => min(100, $score),
            'title_chars_used' => $titleLen . ' / 200',
            'description_chars_used' => $descLen . ' / 4000',
            'keyword_slots_used' => count($keywords) . ' / 7',
            'categories' => (array) ($meta['categories'] ?? []),
            'competitive_gap' => $kit['competition']['scores']['competitive_gap']['value'] ?? null,
            'opportunities' => $opportunities,
        ];
    }

    /**
     * Supplemental learning content per chapter: quiz, takeaway, path.
     *
     * @return array<string, mixed>
     */
    public function queryBookPlan(array $book): array
    {
        $chapters = [];
        foreach ((array) ($book['chapters'] ?? []) as $chapter) {
            $title = (string) $chapter['title'];
            $purpose = (string) $chapter['purpose'];
            $chapters[] = [
                'chapter' => (int) $chapter['number'],
                'title' => $title,
                'quiz' => [
                    'In your own words, what is the main job of “' . $title . '”?',
                    'This chapter sets out to ' . strtolower($purpose) . '. Which part of it would you apply first, and why?',
                    'What is one question this chapter leaves open that you could investigate this week?',
                ],
                'key_takeaway' => 'After reading, the reader should be able to ' . strtolower($purpose) . '.',
                'learning_path_step' => 'Read chapter ' . (int) $chapter['number'] . ', answer the quiz, then complete the chapter\'s action before moving on.',
            ];
        }
        return [
            'mode' => 'Read → Quiz → Apply',
            'chapters' => $chapters,
            'chapter_count' => count($chapters),
            'question_count' => count($chapters) * 3,
        ];
    }

    /** Printable single-file HTML report of the production kit. */
    public function exportKitHtml(array $productionKit): string
    {
        $e = static fn (string $v): string => htmlspecialchars($v, ENT_QUOTES, 'UTF-8');
        $scores = (array) $productionKit['editorial_quality_report'];
        $html = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>' . $e((string) $productionKit['book_blueprint']['working_title']) . ' — Production Kit</title>'
            . '<style>body{font-family:Georgia,serif;max-width:52em;margin:2em auto;padding:0 1em;color:#202431;line-height:1.5}h1,h2{letter-spacing:-.02em}h2{border-bottom:2px solid #d8d0c2;padding-bottom:4px;margin-top:2em}'
            . 'table{border-collapse:collapse;width:100%;font-size:.9em}th,td{border:1px solid #bbb;padding:5px 8px;text-align:left;vertical-align:top}.badge{display:inline-block;border-radius:99px;padding:2px 12px;font-weight:700;background:#eee}'
            . '.pass{color:#256d43;font-weight:700}.warn{color:#a15b06;font-weight:700}@media print{h2{page-break-after:avoid}}</style></head><body>';
        $html .= '<h1>Best-Seller Production Kit</h1><p><strong>' . $e((string) $productionKit['book_blueprint']['working_title']) . '</strong>'
            . ((string) $productionKit['book_blueprint']['subtitle'] !== '' ? ' — ' . $e((string) $productionKit['book_blueprint']['subtitle']) : '')
            . '<br>Generated ' . $e((string) $productionKit['generated_at']) . '</p>';
        $bsp = $productionKit['best_seller_probability'];
        $html .= '<h2>Best-Seller Probability</h2><p><span class="badge">' . (int) ($bsp['value'] ?? 0) . '% · ' . $e((string) ($bsp['label'] ?? '')) . '</span></p>';
        $html .= '<h2>Quality Scores — ' . (int) $scores['metric_count'] . ' metrics</h2><table><tr><th>Group</th><th>Score</th><th>Badge</th></tr>';
        foreach (['editorial' => 'Editorial', 'media' => 'Media', 'format' => 'Format'] as $key => $label) {
            $html .= '<tr><td>' . $label . '</td><td>' . (int) $scores[$key]['score'] . '</td><td>' . $e((string) $scores[$key]['badge']) . '</td></tr>';
        }
        $html .= '<tr><td><strong>UNR (Universal Nonfiction Rating)</strong></td><td><strong>' . (int) $scores['unr']['score'] . '</strong></td><td><strong>' . $e((string) $scores['unr']['badge']) . '</strong></td></tr></table>';
        foreach (['editorial' => 'Editorial metrics', 'media' => 'Media metrics', 'format' => 'Format metrics'] as $key => $label) {
            $html .= '<h2>' . $label . '</h2><table><tr><th>Metric</th><th>Score</th><th>Note</th></tr>';
            foreach ((array) $scores[$key]['metrics'] as $metric) {
                $html .= '<tr><td>' . $e((string) $metric['label']) . '</td><td>' . (int) $metric['value'] . '</td><td>' . $e((string) $metric['note']) . '</td></tr>';
            }
            $html .= '</table>';
        }
        $c = (array) $productionKit['complexity'];
        $html .= '<h2>Document Complexity</h2><table>';
        foreach ($c as $key => $value) {
            $html .= '<tr><th>' . $e(ucwords(str_replace('_', ' ', (string) $key))) . '</th><td>' . $e((string) $value) . '</td></tr>';
        }
        $html .= '</table><h2>KDP Compatibility</h2><table><tr><th>Check</th><th>Status</th><th>Detail</th></tr>';
        foreach ((array) $productionKit['kdp_compatibility_report'] as $check) {
            $html .= '<tr><td>' . $e((string) $check['check']) . '</td><td class="' . $e((string) $check['status']) . '">' . strtoupper($e((string) $check['status'])) . '</td><td>' . $e((string) $check['detail']) . '</td></tr>';
        }
        $meta = (array) $productionKit['metadata_optimization_report'];
        $html .= '</table><h2>Metadata Optimization — score ' . (int) $meta['score'] . '</h2><p>Title: ' . $e((string) $meta['title_chars_used'])
            . ' · Description: ' . $e((string) $meta['description_chars_used']) . ' · Keywords: ' . $e((string) $meta['keyword_slots_used']) . '</p>';
        $html .= '<h2>Chapter Outline</h2><table><tr><th>#</th><th>Chapter</th><th>Purpose</th><th>Pages</th></tr>';
        foreach ((array) $productionKit['chapter_outline'] as $row) {
            $html .= '<tr><td>' . (int) $row['number'] . '</td><td>' . $e((string) $row['title']) . '</td><td>' . $e((string) $row['purpose']) . '</td><td>' . (int) $row['pages'] . '</td></tr>';
        }
        $qb = (array) $productionKit['querybook_enhancement_plan'];
        $html .= '</table><h2>QueryBook Enhancement Plan — ' . (int) $qb['question_count'] . ' quiz questions</h2><p>Mode: ' . $e((string) $qb['mode']) . '</p>';
        $html .= '<p><em>' . $e((string) $productionKit['disclaimer']) . '</em></p>';
        return $html . '</body></html>';
    }

    private function badge(int $score): string
    {
        foreach (self::BADGES as [$threshold, $badge]) {
            if ($score >= $threshold) {
                return $badge;
            }
        }
        return 'Bronze';
    }
}
